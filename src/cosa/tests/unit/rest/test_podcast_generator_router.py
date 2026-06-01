"""
Unit tests for the Podcast Generator router (`cosa.rest.routers.podcast_generator`).

This router wraps the already-100%-covered `cosa.agents.podcast_generator` package
(FM-17 agent-vs-router split). It is NOT an SSE-streaming router — it is sync-return
job-orchestration plus an LLM-powered fuzzy file matcher. Every external collaborator
is boundary-mocked: NO real LLM call, NO agentic job, NO queue, NO voice I/O, NO network.
Filesystem-touching paths (`match_research_docs`) run against a real `TemporaryDirectory`
so `os.walk`/`os.listdir`/`os.path.exists` exercise genuine behaviour with zero risk.

Covers:
- `get_todo_queue` / `get_websocket_mgr` — dual-key `fastapi_app.main` patch (Gotcha 1).
- `is_research_path` — every detection arm (deep-research prefix w/ + w/o leading slash,
  email-in-text + .md, general path + extension, description → False).
- `validate_source_path` — absolute + relative normalisation, traversal rejection,
  exact-project-root arm.
- `match_research_docs` — empty-docs, tier-1/2/3a/3b match resolution, pre-filter
  (>MAX_CANDIDATES with + without keyword overlap), source-2 dedup, LLM-raises → [].
- `get_user_document_selection` — label truncation, label/relpath selection match,
  Cancel, empty selection, no-match fallthrough.
- `submit_podcast_job` — Flow A (direct path): empty-400, traversal-403, missing-404,
  factory-None-500, full-options happy, relative-path minimal happy; Flow B (description):
  no-match-404 teardown, cancel teardown, traversal-403 teardown, missing-404 teardown,
  factory-None-500 teardown, full happy + spec-id inheritance + finally clear_job_id.

Auth is bypassed by passing `current_user` explicitly (Depends not invoked).
"""

import os
import sys
import time
import asyncio
import tempfile
import unittest
from unittest.mock import Mock, MagicMock, AsyncMock, patch

from fastapi import HTTPException

from cosa.rest.routers.podcast_generator import (
    get_todo_queue,
    get_websocket_mgr,
    is_research_path,
    validate_source_path,
    match_research_docs,
    get_user_document_selection,
    submit_podcast_job,
    PodcastSubmitRequest,
    PodcastSubmitResponse,
    PodcastMatchingResponse,
)

M = "cosa.rest.routers.podcast_generator"


def _patch_fastapi_main( mock_main ):
    """Dual-key patch for `fastapi_app.main` (Gotcha 1)."""
    pkg = Mock()
    pkg.main = mock_main
    return patch.dict( sys.modules, { "fastapi_app": pkg, "fastapi_app.main": mock_main } )


def _fake_config( mapping ):
    """
    Build a ConfigurationManager stand-in whose .get( key, default=... ) reads `mapping`.

    Requires:
        - mapping is a dict of config-key → value
    Ensures:
        - returns a MagicMock; .get returns mapping[key] or the passed default
    """
    cfg = MagicMock()
    def _get( key, default=None ):
        return mapping.get( key, default )
    cfg.get.side_effect = _get
    return cfg


# ═══════════════════════════════════════════════════════════════════════════════
# Dependency providers
# ═══════════════════════════════════════════════════════════════════════════════

class TestDependencyProviders( unittest.TestCase ):
    """
    Ensures:
        - get_todo_queue / get_websocket_mgr read off fastapi_app.main
    """

    def test_get_todo_queue_reads_main( self ):
        """Ensures: get_todo_queue returns main_module.jobs_todo_queue."""
        mock_main = MagicMock()
        mock_main.jobs_todo_queue = "Q"
        with _patch_fastapi_main( mock_main ):
            self.assertEqual( get_todo_queue(), "Q" )

    def test_get_websocket_mgr_reads_main( self ):
        """Ensures: get_websocket_mgr returns main_module.websocket_manager."""
        mock_main = MagicMock()
        mock_main.websocket_manager = "WS"
        with _patch_fastapi_main( mock_main ):
            self.assertEqual( get_websocket_mgr(), "WS" )


# ═══════════════════════════════════════════════════════════════════════════════
# is_research_path
# ═══════════════════════════════════════════════════════════════════════════════

class TestIsResearchPath( unittest.TestCase ):
    """
    Requires:
        - ConfigurationManager boundary-mocked ("deep research output path")
    Ensures:
        - every detection arm classifies path-vs-description correctly
    """

    def setUp( self ):
        self.email = "u@test.com"
        self.cfg   = _fake_config( { "deep research output path": "/io/deep-research" } )

    def _call( self, text ):
        with patch( "cosa.config.configuration_manager.ConfigurationManager", return_value=self.cfg ):
            return is_research_path( text, self.email )

    def test_deep_research_prefix_with_leading_slash( self ):
        """Ensures: '/io/deep-research/<email>/x.md' → True (prefix arm)."""
        self.assertTrue( self._call( "/io/deep-research/u@test.com/report.md" ) )

    def test_deep_research_prefix_without_leading_slash( self ):
        """Ensures: 'io/deep-research/<email>/x.md' → True (lstripped-prefix arm)."""
        self.assertTrue( self._call( "io/deep-research/u@test.com/report.md" ) )

    def test_email_in_text_and_md_suffix( self ):
        """Ensures: text containing the email + ending .md → True (email arm)."""
        self.assertTrue( self._call( "notes-u@test.com-summary.md" ) )

    def test_general_path_with_extension( self ):
        """Ensures: '/'-containing path ending in a doc extension → True (general arm)."""
        self.assertTrue( self._call( "src/docs/guide.txt" ) )
        self.assertTrue( self._call( "src/docs/page.html" ) )

    def test_description_returns_false( self ):
        """Ensures: a natural-language description → False (no arm fires)."""
        self.assertFalse( self._call( "my latest Claude Code research" ) )


# ═══════════════════════════════════════════════════════════════════════════════
# validate_source_path
# ═══════════════════════════════════════════════════════════════════════════════

class TestValidateSourcePath( unittest.TestCase ):
    """
    Ensures:
        - absolute + relative paths inside the project root validate True
        - traversal escapes validate False
        - the resolved == project_root arm validates True
    """

    def test_absolute_inside_root( self ):
        """Ensures: a leading-slash path inside the root → True."""
        self.assertTrue( validate_source_path( "/src/rnd/report.md" ) )

    def test_relative_inside_root( self ):
        """Ensures: a relative path inside the root → True (else-normalise arm)."""
        self.assertTrue( validate_source_path( "src/rnd/report.md" ) )

    def test_traversal_escape_false( self ):
        """Ensures: '../../etc/passwd' escapes the root → False."""
        self.assertFalse( validate_source_path( "../../etc/passwd" ) )
        self.assertFalse( validate_source_path( "/src/../../../etc/passwd" ) )

    def test_resolves_to_project_root_exactly( self ):
        """Ensures: a path resolving to the root itself → True (== project_root arm)."""
        self.assertTrue( validate_source_path( "/" ) )


# ═══════════════════════════════════════════════════════════════════════════════
# match_research_docs  (real filesystem via TemporaryDirectory; LLM boundary-mocked)
# ═══════════════════════════════════════════════════════════════════════════════

class TestMatchResearchDocs( unittest.TestCase ):
    """
    Requires:
        - cu.get_project_root → a temp dir; ConfigurationManager / LlmClientFactory /
          PromptTemplateProcessor / FuzzyFileMatchResponse / cu.get_file_as_string all mocked
    Ensures:
        - doc discovery, pre-filter, 3-tier match resolution, and error arms behave
    """

    def setUp( self ):
        self._tmp      = tempfile.TemporaryDirectory()
        self.root      = self._tmp.name
        self.email     = "u@test.com"
        self.research  = os.path.join( self.root, "io", "deep-research", self.email )

    def tearDown( self ):
        self._tmp.cleanup()

    def _write( self, relpath, body="x" ):
        """Create a file under the temp root at relpath."""
        full = os.path.join( self.root, relpath )
        os.makedirs( os.path.dirname( full ), exist_ok=True )
        with open( full, "w" ) as fh:
            fh.write( body )
        return full

    def _run( self, description, llm_matches, *, search_paths="/nowhere", debug=False,
              llm_raises=False ):
        """
        Drive match_research_docs with the LLM stack mocked.

        Requires:
            - llm_matches is the list get_matches_list() returns
        Ensures:
            - returns the function's valid_matches list
        """
        cfg = _fake_config( {
            "podcast generator source search paths" : search_paths,
            "prompt template for fuzzy file matching" : "/tmpl.txt",
            "llm spec key for fuzzy file matching"    : "phi4",
        } )

        parsed = MagicMock()
        parsed.get_matches_list.return_value = llm_matches

        client = MagicMock()
        if llm_raises:
            client.run.side_effect = RuntimeError( "boom" )
        else:
            client.run.return_value = "<response/>"
        factory = MagicMock()
        factory.get_client.return_value = client

        processor = MagicMock()
        processor.process_template.side_effect = lambda tmpl, _name: tmpl

        with patch( "cosa.config.configuration_manager.ConfigurationManager", return_value=cfg ), \
             patch( f"{M}.cu.get_project_root", return_value=self.root ), \
             patch( f"{M}.cu.get_file_as_string", return_value="{description}\n{file_list}" ), \
             patch( "cosa.agents.llm_client_factory.LlmClientFactory", return_value=factory ), \
             patch( "cosa.agents.io_models.utils.prompt_template_processor.PromptTemplateProcessor",
                    return_value=processor ), \
             patch( "cosa.agents.io_models.xml_models.FuzzyFileMatchResponse" ) as ffmr:
            ffmr.from_xml.return_value = parsed
            return asyncio.run( match_research_docs( self.email, description, debug=debug ) )

    def test_no_documents_returns_empty( self ):
        """Ensures: zero markdown anywhere (+ missing search dir) → [] (debug arm)."""
        result = self._run( "anything", [], search_paths="/missing-dir", debug=True )
        self.assertEqual( result, [] )

    def test_tier1_direct_relpath_match( self ):
        """Ensures: an exact relative-path LLM hit resolves via tier 1 (debug arm)."""
        self._write( f"io/deep-research/{self.email}/topic.md" )
        rel = f"io/deep-research/{self.email}/topic.md"
        result = self._run( "topic", [ rel ], debug=True )
        self.assertEqual( result, [ { "filename": "topic.md", "relative_path": rel } ] )

    def test_tier2_bare_filename_match( self ):
        """Ensures: a bare-filename LLM hit resolves via tier 2 (debug off)."""
        self._write( f"io/deep-research/{self.email}/alpha.md" )
        rel = f"io/deep-research/{self.email}/alpha.md"
        result = self._run( "alpha", [ "alpha.md" ], debug=False )
        self.assertEqual( result, [ { "filename": "alpha.md", "relative_path": rel } ] )

    def test_tier3_fuzzy_path_match( self ):
        """Ensures: a near-miss full path resolves via tier-3 fuzzy path."""
        self._write( f"io/deep-research/{self.email}/quantum-computing-overview.md" )
        rel  = f"io/deep-research/{self.email}/quantum-computing-overview.md"
        near = f"io/deep-research/{self.email}/quantum-computing-overviewX.md"
        result = self._run( "quantum", [ near ], debug=True )
        self.assertEqual( result, [ { "filename": "quantum-computing-overview.md", "relative_path": rel } ] )

    def test_tier3_fuzzy_name_match( self ):
        """Ensures: a near-miss bare name resolves via tier-3 fuzzy name."""
        self._write( f"io/deep-research/{self.email}/longuniquetitle.md" )
        rel = f"io/deep-research/{self.email}/longuniquetitle.md"
        result = self._run( "title", [ "longuniquetitleX.md" ], debug=True )
        self.assertEqual( result, [ { "filename": "longuniquetitle.md", "relative_path": rel } ] )

    def test_unresolvable_match_dropped( self ):
        """Ensures: an LLM hit matching nothing (all tiers miss) is silently dropped."""
        self._write( f"io/deep-research/{self.email}/real.md" )
        result = self._run( "real", [ "zzzzzzzzzzcompletelyunrelated.md" ], debug=True )
        self.assertEqual( result, [] )

    def test_source2_dedup_skips_already_mapped( self ):
        """Ensures: a search dir re-walking the research dir hits the rel-already-mapped arm."""
        self._write( f"io/deep-research/{self.email}/dup.md" )
        rel = f"io/deep-research/{self.email}/dup.md"
        # search path "/io" re-discovers the same file → rel already in docs_map → skipped
        result = self._run( "dup", [ rel ], search_paths="/io", debug=True )
        self.assertEqual( result, [ { "filename": "dup.md", "relative_path": rel } ] )

    def test_prefilter_with_keyword_overlap( self ):
        """Ensures: >MAX_CANDIDATES docs + keyword overlap → pre-filter narrows then matches."""
        # 60 generic docs (no overlap) + 1 keyword-bearing doc
        for i in range( 60 ):
            self._write( f"bulk/doc_{i:03d}.md" )
        self._write( "bulk/quantum-entanglement.md" )
        rel = "bulk/quantum-entanglement.md"
        result = self._run( "quantum entanglement", [ rel ], search_paths="/bulk", debug=True )
        self.assertEqual( result, [ { "filename": "quantum-entanglement.md", "relative_path": rel } ] )

    def test_prefilter_no_keyword_overlap_uses_full_map( self ):
        """Ensures: >MAX_CANDIDATES docs but zero overlap → 'no keyword matches' else arm."""
        for i in range( 55 ):
            self._write( f"bulk/report_{i:03d}.md" )
        # description keywords (len>2, non-stopword) that match no path component
        result = self._run( "xylophone wombat", [], search_paths="/bulk", debug=True )
        self.assertEqual( result, [] )   # LLM returns no matches; exercising the else arm is the point

    def test_llm_exception_returns_empty( self ):
        """Ensures: an LLM .run() exception is caught → [] (except arm, debug print)."""
        self._write( f"io/deep-research/{self.email}/topic.md" )
        result = self._run( "topic", [], llm_raises=True, debug=True )
        self.assertEqual( result, [] )

    def test_non_md_files_skipped_both_sources( self ):
        """Ensures: non-.md files are skipped in source-1 listdir AND source-2 walk."""
        self._write( f"io/deep-research/{self.email}/keep.md" )
        self._write( f"io/deep-research/{self.email}/skip.txt" )   # source-1 non-.md → skipped
        self._write( "extra/walkkeep.md" )
        self._write( "extra/walkskip.log" )                        # source-2 non-.md → skipped
        result = self._run( "keep", [], search_paths="/extra", debug=False )
        self.assertEqual( result, [] )

    def test_tier3_fuzzy_name_decoy_checked_before_match( self ):
        """Ensures: tier-3b loop skips a non-matching decoy (source-1) before the source-2 match."""
        # source-1 decoy inserted FIRST (different basename) → checked + skipped;
        # source-2 deeply-nested target inserted SECOND → fuzzy-name winner, matched.
        self._write( f"io/deep-research/{self.email}/decoy.md" )
        target_rel = "extra/aa/bb/cc/dd/ee/ff/zzztargetdoc.md"
        self._write( target_rel )
        result = self._run( "zzztargetdoc", [ "zzztargetdocX.md" ], search_paths="/extra", debug=True )
        self.assertEqual( result, [ { "filename": "zzztargetdoc.md", "relative_path": target_rel } ] )

    def test_prefilter_with_keyword_overlap_debug_off( self ):
        """Ensures: pre-filter + scored-non-empty path runs with debug off (skips the debug print)."""
        for i in range( 60 ):
            self._write( f"bulk/doc_{i:03d}.md" )
        self._write( "bulk/quantum-entanglement.md" )
        rel = "bulk/quantum-entanglement.md"
        result = self._run( "quantum entanglement", [ rel ], search_paths="/bulk", debug=False )
        self.assertEqual( result, [ { "filename": "quantum-entanglement.md", "relative_path": rel } ] )


# ═══════════════════════════════════════════════════════════════════════════════
# get_user_document_selection
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetUserDocumentSelection( unittest.TestCase ):
    """
    Requires:
        - cosa.agents.podcast_generator.voice_io / cosa_interface boundary-mocked
    Ensures:
        - selection-by-label, selection-by-relpath, Cancel, empty, and no-match arms
    """

    LONG = "io/deep-research/u@test.com/a-very-long-relative-path-name-exceeding-forty-five-chars.md"
    SHORT = "io/x.md"

    def _label( self, rel ):
        label = rel[ -45: ] if len( rel ) > 45 else rel
        if len( rel ) > 45:
            label = "..." + label
        return label

    def _run( self, selection_answer, debug=True ):
        matches = [
            { "filename": "long.md",  "relative_path": self.LONG },
            { "filename": "short.md", "relative_path": self.SHORT },
        ]
        voice_io = MagicMock()
        voice_io.present_choices = AsyncMock( return_value={ "answers": { "Document": selection_answer } } )
        cosa_interface = MagicMock()
        with patch( "cosa.agents.podcast_generator.voice_io", voice_io ), \
             patch( "cosa.agents.podcast_generator.cosa_interface", cosa_interface ):
            result = asyncio.run( get_user_document_selection( "u@test.com", "sess-1", matches, debug=debug ) )
        return result, voice_io

    def test_select_by_truncated_label( self ):
        """Ensures: selecting the truncated label of a long rel returns that match."""
        result, _ = self._run( self._label( self.LONG ) )
        self.assertEqual( result[ "relative_path" ], self.LONG )

    def test_select_by_relative_path( self ):
        """Ensures: selecting a short rel (untruncated) returns that match."""
        result, _ = self._run( self.SHORT )
        self.assertEqual( result[ "relative_path" ], self.SHORT )

    def test_cancel_returns_none( self ):
        """Ensures: the 'Cancel' sentinel returns None."""
        result, _ = self._run( "Cancel" )
        self.assertIsNone( result )

    def test_empty_selection_returns_none( self ):
        """Ensures: a falsy/empty selection returns None."""
        result, _ = self._run( "" )
        self.assertIsNone( result )

    def test_no_match_fallthrough_returns_none( self ):
        """Ensures: a selection matching no option falls through the loop → None."""
        result, _ = self._run( "something-not-in-the-list" )
        self.assertIsNone( result )

    def test_select_by_relative_path_debug_off( self ):
        """Ensures: the debug-off arms (skip both debug prints) still resolve a selection."""
        result, _ = self._run( self.SHORT, debug=False )
        self.assertEqual( result[ "relative_path" ], self.SHORT )


# ═══════════════════════════════════════════════════════════════════════════════
# submit_podcast_job — Flow A (direct path)
# ═══════════════════════════════════════════════════════════════════════════════

class TestSubmitFlowA( unittest.TestCase ):
    """
    Requires:
        - is_research_path / validate_source_path / create_agentic_job / user_job_tracker
          / os.path.exists / cu.get_project_root boundary-mocked
    Ensures:
        - empty-400, traversal-403, missing-404, factory-None-500, full + minimal happy paths
    """

    def setUp( self ):
        self.user  = { "uid": "user_42", "email": "u@test.com", "session_id": "sess-1" }
        self.queue = MagicMock()
        self.ws    = MagicMock()
        self.root  = "/proj/root"

    def _call( self, body ):
        return asyncio.run( submit_podcast_job(
            request       = body,
            current_user  = self.user,
            todo_queue    = self.queue,
            websocket_mgr = self.ws,
        ) )

    def test_empty_source_400( self ):
        """Ensures: whitespace-only research_source → 400 before any routing."""
        with self.assertRaises( HTTPException ) as ctx:
            self._call( PodcastSubmitRequest( research_source="   " ) )
        self.assertEqual( ctx.exception.status_code, 400 )

    def test_traversal_403( self ):
        """Ensures: a path failing validate_source_path → 403."""
        with patch( f"{M}.is_research_path", return_value=True ), \
             patch( f"{M}.validate_source_path", return_value=False ):
            with self.assertRaises( HTTPException ) as ctx:
                self._call( PodcastSubmitRequest( research_source="/io/deep-research/u@test.com/x.md" ) )
        self.assertEqual( ctx.exception.status_code, 403 )

    def test_missing_file_404( self ):
        """Ensures: a valid path that does not exist → 404."""
        with patch( f"{M}.is_research_path", return_value=True ), \
             patch( f"{M}.validate_source_path", return_value=True ), \
             patch( f"{M}.cu.get_project_root", return_value=self.root ), \
             patch( "os.path.exists", return_value=False ):
            with self.assertRaises( HTTPException ) as ctx:
                self._call( PodcastSubmitRequest( research_source="/io/x.md" ) )
        self.assertEqual( ctx.exception.status_code, 404 )

    def test_factory_none_500( self ):
        """Ensures: create_agentic_job returning None → 500."""
        tracker = MagicMock()
        with patch( f"{M}.is_research_path", return_value=True ), \
             patch( f"{M}.validate_source_path", return_value=True ), \
             patch( f"{M}.cu.get_project_root", return_value=self.root ), \
             patch( "os.path.exists", return_value=True ), \
             patch( f"{M}.create_agentic_job", return_value=None ), \
             patch( f"{M}.user_job_tracker", tracker ):
            with self.assertRaises( HTTPException ) as ctx:
                self._call( PodcastSubmitRequest( research_source="/io/x.md" ) )
        self.assertEqual( ctx.exception.status_code, 500 )

    def test_full_options_happy_absolute_debug( self ):
        """Ensures: absolute path + all optional fields + debug thread through to a queued response."""
        self.user[ "debug" ] = True
        self.queue.size.return_value = 7
        job = MagicMock(); job.id_hash = "init"
        tracker = MagicMock(); tracker.register_scoped_job.return_value = "pg-scoped"
        body = PodcastSubmitRequest(
            research_source    = "/io/deep-research/u@test.com/r.md",
            target_languages   = [ "en", "es" ],
            max_segments       = 4,
            dry_run            = True,
            force_failure_mode = "code_bug",
            audience           = "students",
            audience_context   = "intro course",
            scheduled_at       = "2026-06-02T02:30:00-04:00",
            monopolize         = True,
        )
        with patch( f"{M}.is_research_path", return_value=True ), \
             patch( f"{M}.validate_source_path", return_value=True ), \
             patch( f"{M}.cu.get_project_root", return_value=self.root ), \
             patch( "os.path.exists", return_value=True ), \
             patch( f"{M}.create_agentic_job", return_value=job ) as m_create, \
             patch( f"{M}.user_job_tracker", tracker ):
            result = self._call( body )

        self.assertIsInstance( result, PodcastSubmitResponse )
        self.assertEqual( result.job_id, "pg-scoped" )
        self.assertEqual( result.queue_position, 7 )
        _, kwargs = m_create.call_args
        args_dict = kwargs[ "args_dict" ]
        self.assertEqual( args_dict[ "research" ], self.root + "/io/deep-research/u@test.com/r.md" )
        self.assertEqual( args_dict[ "languages" ], "en,es" )
        self.assertTrue( args_dict[ "dry_run" ] )
        self.assertEqual( args_dict[ "force_failure_mode" ], "code_bug" )
        self.assertEqual( args_dict[ "audience" ], "students" )
        self.assertEqual( args_dict[ "audience_context" ], "intro course" )
        self.assertEqual( job.max_segments, 4 )
        self.assertEqual( job.scheduled_at, "2026-06-02T02:30:00-04:00" )
        self.assertTrue( job.monopolize )
        self.queue.push.assert_called_once_with( job )

    def test_minimal_happy_relative_no_debug( self ):
        """Ensures: relative path + no optional fields + debug-off → queued response (else-normalise arm)."""
        self.queue.size.return_value = 1
        job = MagicMock(); job.id_hash = "init"
        tracker = MagicMock(); tracker.register_scoped_job.return_value = "pg-rel"
        body = PodcastSubmitRequest( research_source="io/deep-research/u@test.com/r.md" )
        with patch( f"{M}.is_research_path", return_value=True ), \
             patch( f"{M}.validate_source_path", return_value=True ), \
             patch( f"{M}.cu.get_project_root", return_value=self.root ), \
             patch( "os.path.exists", return_value=True ), \
             patch( f"{M}.create_agentic_job", return_value=job ) as m_create, \
             patch( f"{M}.user_job_tracker", tracker ):
            result = self._call( body )

        self.assertEqual( result.job_id, "pg-rel" )
        _, kwargs = m_create.call_args
        args_dict = kwargs[ "args_dict" ]
        self.assertEqual( args_dict[ "research" ], self.root + "/io/deep-research/u@test.com/r.md" )
        self.assertNotIn( "languages", args_dict )
        self.assertNotIn( "dry_run", args_dict )
        self.assertNotIn( "audience", args_dict )


# ═══════════════════════════════════════════════════════════════════════════════
# submit_podcast_job — Flow B (description / fuzzy matching)
# ═══════════════════════════════════════════════════════════════════════════════

class TestSubmitFlowB( unittest.TestCase ):
    """
    Requires:
        - is_research_path False; match_research_docs / get_user_document_selection async-mocked;
          voice_io / cosa_interface / emit_job_state_transition / create_agentic_job /
          user_job_tracker / validate_source_path / os.path.exists / cu.get_project_root mocked
    Ensures:
        - no-match-404 teardown, cancel teardown, traversal-403 teardown, missing-404 teardown,
          factory-None-500 teardown, full happy w/ spec-id inheritance + finally clear_job_id
    """

    def setUp( self ):
        self.user  = { "uid": "user_42", "email": "u@test.com", "session_id": "sess-1" }
        self.queue = MagicMock()
        self.ws    = MagicMock()
        self.root  = "/proj/root"
        self.voice = MagicMock()
        self.iface = MagicMock()

    def _call( self, body ):
        return asyncio.run( submit_podcast_job(
            request       = body,
            current_user  = self.user,
            todo_queue    = self.queue,
            websocket_mgr = self.ws,
        ) )

    def _base_patches( self, *, matches, selection, job, tracker_ret="pg-spec" ):
        tracker = MagicMock(); tracker.register_scoped_job.return_value = tracker_ret
        ctxs = [
            patch( f"{M}.is_research_path", return_value=False ),
            patch( f"{M}.cu.get_project_root", return_value=self.root ),
            patch( f"{M}.emit_job_state_transition" ),
            patch( f"{M}.user_job_tracker", tracker ),
            patch( f"{M}.match_research_docs", new=AsyncMock( return_value=matches ) ),
            patch( f"{M}.get_user_document_selection", new=AsyncMock( return_value=selection ) ),
            patch( f"{M}.create_agentic_job", return_value=job ),
            patch( "cosa.agents.podcast_generator.voice_io", self.voice ),
            patch( "cosa.agents.podcast_generator.cosa_interface", self.iface ),
        ]
        return tracker, ctxs

    def _enter( self, ctxs ):
        return [ c.__enter__() for c in ctxs ]

    def _exit( self, ctxs ):
        for c in reversed( ctxs ):
            c.__exit__( None, None, None )

    def test_no_matches_404_teardown( self ):
        """Ensures: empty fuzzy-match result → spec-card teardown + 404; clear_job_id in finally."""
        tracker, ctxs = self._base_patches( matches=[], selection=None, job=MagicMock() )
        self._enter( ctxs )
        try:
            with self.assertRaises( HTTPException ) as ctx:
                self._call( PodcastSubmitRequest( research_source="some description" ) )
            self.assertEqual( ctx.exception.status_code, 404 )
            tracker.remove_job.assert_called()
            self.voice.clear_job_id.assert_called_once()
        finally:
            self._exit( ctxs )

    def test_cancel_returns_matching_response( self ):
        """Ensures: user-cancel selection → teardown + PodcastMatchingResponse(cancelled)."""
        tracker, ctxs = self._base_patches(
            matches=[ { "filename": "a.md", "relative_path": "io/a.md" } ], selection=None,
            job=MagicMock() )
        self._enter( ctxs )
        try:
            result = self._call( PodcastSubmitRequest( research_source="some description" ) )
            self.assertIsInstance( result, PodcastMatchingResponse )
            self.assertEqual( result.status, "cancelled" )
            tracker.remove_job.assert_called()
            self.voice.clear_job_id.assert_called_once()
        finally:
            self._exit( ctxs )

    def test_selected_traversal_403_teardown( self ):
        """Ensures: a selected doc failing validate_source_path → teardown + 403."""
        selection = { "filename": "a.md", "relative_path": "io/a.md" }
        tracker, ctxs = self._base_patches(
            matches=[ selection ], selection=selection, job=MagicMock() )
        ctxs.append( patch( f"{M}.validate_source_path", return_value=False ) )
        self._enter( ctxs )
        try:
            with self.assertRaises( HTTPException ) as ctx:
                self._call( PodcastSubmitRequest( research_source="desc" ) )
            self.assertEqual( ctx.exception.status_code, 403 )
            tracker.remove_job.assert_called()
        finally:
            self._exit( ctxs )

    def test_selected_missing_404_teardown( self ):
        """Ensures: a selected doc that doesn't exist on disk → teardown + 404."""
        selection = { "filename": "a.md", "relative_path": "io/a.md" }
        tracker, ctxs = self._base_patches(
            matches=[ selection ], selection=selection, job=MagicMock() )
        ctxs.append( patch( f"{M}.validate_source_path", return_value=True ) )
        ctxs.append( patch( "os.path.exists", return_value=False ) )
        self._enter( ctxs )
        try:
            with self.assertRaises( HTTPException ) as ctx:
                self._call( PodcastSubmitRequest( research_source="desc" ) )
            self.assertEqual( ctx.exception.status_code, 404 )
            tracker.remove_job.assert_called()
        finally:
            self._exit( ctxs )

    def test_factory_none_500_teardown( self ):
        """Ensures: create_agentic_job None in Flow B → teardown + 500."""
        selection = { "filename": "a.md", "relative_path": "io/a.md" }
        tracker, ctxs = self._base_patches(
            matches=[ selection ], selection=selection, job=None )
        ctxs.append( patch( f"{M}.validate_source_path", return_value=True ) )
        ctxs.append( patch( "os.path.exists", return_value=True ) )
        self._enter( ctxs )
        try:
            with self.assertRaises( HTTPException ) as ctx:
                self._call( PodcastSubmitRequest( research_source="desc" ) )
            self.assertEqual( ctx.exception.status_code, 500 )
            tracker.remove_job.assert_called()
        finally:
            self._exit( ctxs )

    def test_minimal_happy_no_optionals_debug_off( self ):
        """Ensures: Flow B happy path with zero optional fields + debug off (falsy arms of every optional)."""
        self.queue.size.return_value = 1
        selection = { "filename": "a.md", "relative_path": "io/a.md" }
        job = MagicMock(); job.id_hash = "init"
        tracker, ctxs = self._base_patches(
            matches=[ selection ], selection=selection, job=job, tracker_ret="pg-min" )
        ctxs.append( patch( f"{M}.validate_source_path", return_value=True ) )
        ctxs.append( patch( "os.path.exists", return_value=True ) )
        self._enter( ctxs )
        try:
            with patch( f"{M}.create_agentic_job" ) as m_create:
                m_create.return_value = job
                result = self._call( PodcastSubmitRequest( research_source="plain description" ) )
            self.assertIsInstance( result, PodcastSubmitResponse )
            self.assertEqual( result.job_id, "pg-min" )
            _, kwargs = m_create.call_args
            args_dict = kwargs[ "args_dict" ]
            self.assertNotIn( "languages", args_dict )
            self.assertNotIn( "dry_run", args_dict )
            self.assertNotIn( "force_failure_mode", args_dict )
            self.assertNotIn( "audience", args_dict )
            self.voice.clear_job_id.assert_called_once()
        finally:
            self._exit( ctxs )

    def test_full_happy_inherits_spec_id_and_clears( self ):
        """Ensures: Flow B happy path — full options, job.id_hash==spec_id, finally clear_job_id."""
        self.user[ "debug" ] = True
        self.queue.size.return_value = 3
        selection = { "filename": "a.md", "relative_path": "io/a.md" }
        job = MagicMock(); job.id_hash = "init"
        tracker, ctxs = self._base_patches(
            matches=[ selection ], selection=selection, job=job, tracker_ret="pg-final" )
        ctxs.append( patch( f"{M}.validate_source_path", return_value=True ) )
        ctxs.append( patch( "os.path.exists", return_value=True ) )
        body = PodcastSubmitRequest(
            research_source  = "deep dive on agents",
            target_languages = [ "en" ],
            max_segments     = 2,
            dry_run          = True,
            force_failure_mode = "rate_limit",
            audience         = "execs",
            audience_context = "board deck",
            scheduled_at     = "2026-06-02T03:00:00-04:00",
            monopolize       = True,
        )
        self._enter( ctxs )
        try:
            result = self._call( body )
            self.assertIsInstance( result, PodcastSubmitResponse )
            self.assertEqual( result.job_id, "pg-final" )      # inherited spec_id
            self.assertEqual( result.queue_position, 3 )
            self.assertEqual( job.id_hash, "pg-final" )
            self.assertEqual( job.max_segments, 2 )
            self.assertEqual( job.scheduled_at, "2026-06-02T03:00:00-04:00" )
            self.assertTrue( job.monopolize )
            self.queue.push.assert_called_once_with( job )
            self.voice.clear_job_id.assert_called_once()
        finally:
            self._exit( ctxs )


def isolated_unit_test():
    """
    Run the podcast-generator router unit tests in isolation.

    Ensures:
        - Executes all TestCases and reports (success, duration, message)
    """
    import cosa.utils.util as du

    start_time = time.time()
    try:
        loader = unittest.TestLoader()
        suite  = unittest.TestSuite()
        for tc in (
            TestDependencyProviders, TestIsResearchPath, TestValidateSourcePath,
            TestMatchResearchDocs, TestGetUserDocumentSelection,
            TestSubmitFlowA, TestSubmitFlowB,
        ):
            suite.addTests( loader.loadTestsFromTestCase( tc ) )
        result = unittest.TextTestRunner( verbosity=2 ).run( suite )

        duration  = time.time() - start_time
        tests_run = result.testsRun
        failures  = len( result.failures )
        errors    = len( result.errors )

        success = failures == 0 and errors == 0
        if success:
            du.print_banner( "✅ ALL PODCAST-GENERATOR ROUTER TESTS PASSED", prepend_nl=True )
            message = f"All {tests_run} tests passed successfully in {duration:.3f}s"
        else:
            du.print_banner( "❌ SOME PODCAST-GENERATOR ROUTER TESTS FAILED", prepend_nl=True )
            message = f"{failures} failures, {errors} errors out of {tests_run} tests"

        return success, duration, message

    except Exception as e:
        duration  = time.time() - start_time
        error_msg = f"Unit test execution failed: {str( e )}"
        du.print_banner( f"💥 PODCAST-GENERATOR ROUTER TEST ERROR: {error_msg}", prepend_nl=True )
        return False, duration, error_msg


if __name__ == "__main__":
    success, duration, message = isolated_unit_test()
    status = "✅ PASS" if success else "❌ FAIL"
    print( f"\n{status} Podcast-generator router unit tests completed in {duration:.3f}s" )
    print( f"Result: {message}" )
