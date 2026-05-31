"""
Unit tests for runtime_argument_expeditor/expeditor.py special handlers:
  - _handle_fuzzy_file_match     : fs scan + LLM fuzzy match + multi-match disambiguation
  - _handle_tfe_checkpoint_match : resume_resolver candidates + fast-path + fuzzy match

ALL boundaries mocked: ConfigurationManager, FuzzyFileMatchResponse, resume_resolver,
os.path/listdir/walk, LlmClientFactory, cu helpers, and _ask_for_arg (the user-prompt
seam). NO LLM/network/fs.

Created 2026-05-31 by Extra 1 🪨 (CoSA coverage campaign, runtime_argument_expeditor lane).
"""

import sys
import types
import unittest
from unittest.mock import MagicMock, patch

import cosa.agents.runtime_argument_expeditor.expeditor as ex_mod
from cosa.agents.runtime_argument_expeditor.expeditor import RuntimeArgumentExpeditor


def _mk_expeditor( debug=False ):
    cfg = MagicMock()
    cfg.get.side_effect = lambda key, default=None, **kw: default
    with patch.object( ex_mod, "LlmClientFactory", MagicMock() ):
        o = RuntimeArgumentExpeditor( cfg, debug=debug )
    o._job_id       = None
    o._bearer_token = None
    o.llm_spec_key  = "rae-llm-spec"
    return o


def _inner_config_mgr( search_paths="/src", template="/t.txt", llm_spec="fuzzy-spec" ):
    """Fake ConfigurationManager used inside the handler (late import)."""
    cm = MagicMock()
    def _get( key, default=None, **kw ):
        if "source search paths" in key:
            return search_paths if search_paths is not None else default
        if key == "prompt template for fuzzy file matching":
            return template
        if key == "llm spec key for fuzzy file matching":
            return llm_spec
        return default
    cm.get.side_effect = _get
    return cm


def _patch_config_mgr( cm ):
    mod = types.ModuleType( "cosa.config.configuration_manager" )
    mod.ConfigurationManager = MagicMock( return_value=cm )
    return patch.dict( sys.modules, { "cosa.config.configuration_manager": mod } )


def _patch_fuzzy_model( matches ):
    mod = types.ModuleType( "cosa.agents.io_models.xml_models" )
    resp = MagicMock()
    resp.get_matches_list.return_value = matches
    mod.FuzzyFileMatchResponse = MagicMock()
    mod.FuzzyFileMatchResponse.from_xml.return_value = resp
    return patch.dict( sys.modules, { "cosa.agents.io_models.xml_models": mod } )


# ============================================================================
# _handle_fuzzy_file_match
# ============================================================================

class TestFuzzyFileMatch( unittest.TestCase ):

    def test_no_docs_found_falls_back_to_ask( self ):
        o = _mk_expeditor( debug=True )
        cm = _inner_config_mgr( search_paths="/nope" )
        with _patch_config_mgr( cm ), \
             patch.object( ex_mod.cu, "get_project_root", return_value="/p" ), \
             patch.object( ex_mod.os.path, "exists", return_value=False ), \
             patch.object( o, "_ask_for_arg", return_value="/fallback/doc.md" ) as ask:
            out = o._handle_fuzzy_file_match( "u@x" )
        self.assertEqual( out, "/fallback/doc.md" )
        ask.assert_called_once()

    def _fs_with_one_research_doc( self ):
        """exists True for research dir; listdir → one .md; walk → nothing new."""
        def _exists( p ): return "deep-research" in p
        return _exists

    def test_description_none_returns_none( self ):
        o = _mk_expeditor()
        cm = _inner_config_mgr( search_paths="/src" )
        with _patch_config_mgr( cm ), \
             patch.object( ex_mod.cu, "get_project_root", return_value="/p" ), \
             patch.object( ex_mod.os.path, "exists", side_effect=lambda p: "deep-research" in p ), \
             patch.object( ex_mod.os, "listdir", return_value=[ "report.md" ] ), \
             patch.object( ex_mod.os, "walk", return_value=[] ), \
             patch.object( o, "_ask_for_arg", return_value=None ):   # user gives no description
            self.assertIsNone( o._handle_fuzzy_file_match( "u@x" ) )

    def test_exact_relpath_match( self ):
        o = _mk_expeditor()
        cm = _inner_config_mgr()
        rel = "io/deep-research/u@x/report.md"
        with _patch_config_mgr( cm ), \
             patch.object( ex_mod.cu, "get_project_root", return_value="/p" ), \
             patch.object( ex_mod.os.path, "exists", side_effect=lambda p: "deep-research" in p ), \
             patch.object( ex_mod.os, "listdir", return_value=[ "report.md" ] ), \
             patch.object( ex_mod.os, "walk", return_value=[] ), \
             patch.object( o, "_ask_for_arg", return_value=rel ):
            out = o._handle_fuzzy_file_match( "u@x" )
        self.assertTrue( out.endswith( "/report.md" ) )

    def test_basename_match( self ):
        o = _mk_expeditor()
        cm = _inner_config_mgr()
        with _patch_config_mgr( cm ), \
             patch.object( ex_mod.cu, "get_project_root", return_value="/p" ), \
             patch.object( ex_mod.os.path, "exists", side_effect=lambda p: "deep-research" in p ), \
             patch.object( ex_mod.os, "listdir", return_value=[ "report.md" ] ), \
             patch.object( ex_mod.os, "walk", return_value=[] ), \
             patch.object( o, "_ask_for_arg", return_value="report.md" ):
            out = o._handle_fuzzy_file_match( "u@x" )
        self.assertTrue( out.endswith( "/report.md" ) )

    def test_fuzzy_single_match( self ):
        o = _mk_expeditor()
        cm = _inner_config_mgr()
        with _patch_config_mgr( cm ), _patch_fuzzy_model( [ "io/deep-research/u@x/report.md" ] ), \
             patch.object( ex_mod.cu, "get_project_root", return_value="/p" ), \
             patch.object( ex_mod.cu, "get_file_as_string", return_value="tmpl {description} {file_list}" ), \
             patch.object( ex_mod, "PromptTemplateProcessor" ) as PTP, \
             patch.object( ex_mod.os.path, "exists", side_effect=lambda p: "deep-research" in p ), \
             patch.object( ex_mod.os, "listdir", return_value=[ "report.md" ] ), \
             patch.object( ex_mod.os, "walk", return_value=[] ), \
             patch.object( o, "_ask_for_arg", return_value="the AI report" ):
            PTP.return_value.process_template.side_effect = lambda t, n: t
            o.llm_factory.get_client = MagicMock( return_value=MagicMock( run=MagicMock( return_value="<xml/>" ) ) )
            out = o._handle_fuzzy_file_match( "u@x" )
        self.assertTrue( out.endswith( "/report.md" ) )

    def test_fuzzy_no_matches_asks_fallback( self ):
        o = _mk_expeditor( debug=True )
        cm = _inner_config_mgr()
        with _patch_config_mgr( cm ), _patch_fuzzy_model( [] ), \
             patch.object( ex_mod.cu, "get_project_root", return_value="/p" ), \
             patch.object( ex_mod.cu, "get_file_as_string", return_value="t {description} {file_list}" ), \
             patch.object( ex_mod, "PromptTemplateProcessor" ) as PTP, \
             patch.object( ex_mod.os.path, "exists", side_effect=lambda p: "deep-research" in p ), \
             patch.object( ex_mod.os, "listdir", return_value=[ "report.md" ] ), \
             patch.object( ex_mod.os, "walk", return_value=[] ), \
             patch.object( o, "_ask_for_arg", side_effect=[ "desc", "/manual/path.md" ] ):
            PTP.return_value.process_template.side_effect = lambda t, n: t
            o.llm_factory.get_client = MagicMock( return_value=MagicMock( run=MagicMock( return_value="<xml/>" ) ) )
            out = o._handle_fuzzy_file_match( "u@x" )
        self.assertEqual( out, "/manual/path.md" )

    def _multi_match_setup( self, pick ):
        o = _mk_expeditor()
        cm = _inner_config_mgr()
        matches = [ "io/deep-research/u@x/alpha.md", "io/deep-research/u@x/beta.md" ]
        ctx = [
            _patch_config_mgr( cm ),
            _patch_fuzzy_model( matches ),
            patch.object( ex_mod.cu, "get_project_root", return_value="/p" ),
            patch.object( ex_mod.cu, "get_file_as_string", return_value="t {description} {file_list}" ),
            patch.object( ex_mod, "PromptTemplateProcessor" ),
            patch.object( ex_mod.os.path, "exists", side_effect=lambda p: "deep-research" in p ),
            patch.object( ex_mod.os, "listdir", return_value=[ "alpha.md", "beta.md" ] ),
            patch.object( ex_mod.os, "walk", return_value=[] ),
            patch.object( o, "_ask_for_arg", side_effect=[ "something", pick ] ),
        ]
        return o, ctx

    def _run_multi( self, o, ctx ):
        started = [ c.start() for c in ctx ]
        # the 5th patch is PromptTemplateProcessor → wire process_template
        ex_mod.PromptTemplateProcessor.return_value.process_template.side_effect = lambda t, n: t
        o.llm_factory.get_client = MagicMock( return_value=MagicMock( run=MagicMock( return_value="<xml/>" ) ) )
        try:
            return o._handle_fuzzy_file_match( "u@x" )
        finally:
            for c in ctx: c.stop()

    def test_fuzzy_multi_pick_by_number( self ):
        o, ctx = self._multi_match_setup( pick="2" )
        out = self._run_multi( o, ctx )
        self.assertTrue( out.endswith( "/beta.md" ) )

    def test_fuzzy_multi_pick_by_name( self ):
        o, ctx = self._multi_match_setup( pick="alpha" )
        out = self._run_multi( o, ctx )
        self.assertTrue( out.endswith( "/alpha.md" ) )

    def test_fuzzy_multi_pick_none_returns_none( self ):
        o, ctx = self._multi_match_setup( pick=None )
        out = self._run_multi( o, ctx )
        self.assertIsNone( out )

    def test_fuzzy_multi_pick_no_match_falls_back_to_first( self ):
        o, ctx = self._multi_match_setup( pick="99 nonsense" )
        out = self._run_multi( o, ctx )
        self.assertTrue( out.endswith( "/alpha.md" ) )   # fallback: first match

    def test_fuzzy_exception_asks_fallback( self ):
        o = _mk_expeditor( debug=True )
        cm = _inner_config_mgr()
        with _patch_config_mgr( cm ), \
             patch.object( ex_mod.cu, "get_project_root", return_value="/p" ), \
             patch.object( ex_mod.cu, "get_file_as_string", side_effect=RuntimeError( "tmpl boom" ) ), \
             patch.object( ex_mod.os.path, "exists", side_effect=lambda p: "deep-research" in p ), \
             patch.object( ex_mod.os, "listdir", return_value=[ "report.md" ] ), \
             patch.object( ex_mod.os, "walk", return_value=[] ), \
             patch.object( o, "_ask_for_arg", side_effect=[ "desc", "/manual.md" ] ):
            out = o._handle_fuzzy_file_match( "u@x" )
        self.assertEqual( out, "/manual.md" )

    def test_extension_skip_and_duplicate_arcs( self ):
        # 911->910 / 919->918 / 940->939 (non-matching files skipped) + 943->939 (dup relpath).
        o = _mk_expeditor()
        cm = _inner_config_mgr( search_paths="/src" )
        def _exists( p ): return ( "deep-research" in p ) or ( "presentations" in p ) or ( "/p/src" in p )
        def _listdir( d ):
            if "deep-research" in d: return [ "report.md", "skip.log" ]      # .log skipped
            if "presentations" in d: return [ "s.yaml", "note.txt" ]          # .txt skipped (yaml-only dir)
            return []
        # walk yields a file already mapped (dup) + a non-matching file
        walk = [ ( "/p/src", [], [ "report.md", "ignore.bin" ] ) ]
        with _patch_config_mgr( cm ), \
             patch.object( ex_mod.cu, "get_project_root", return_value="/p" ), \
             patch.object( ex_mod.os.path, "exists", side_effect=_exists ), \
             patch.object( ex_mod.os, "listdir", side_effect=_listdir ), \
             patch.object( ex_mod.os, "walk", return_value=walk ), \
             patch.object( ex_mod.os.path, "relpath", side_effect=lambda a, b: "io/deep-research/u@x/report.md" ), \
             patch.object( o, "_ask_for_arg", return_value="report.md" ):
            out = o._handle_fuzzy_file_match( "u@x" )
        self.assertTrue( out.endswith( "/report.md" ) )

    def test_fuzzy_match_returned_as_basename( self ):
        # 996-999: LLM returns a bare basename (not a rel path) → matched via basename loop.
        o = _mk_expeditor()
        cm = _inner_config_mgr()
        with _patch_config_mgr( cm ), _patch_fuzzy_model( [ "report.md" ] ), \
             patch.object( ex_mod.cu, "get_project_root", return_value="/p" ), \
             patch.object( ex_mod.cu, "get_file_as_string", return_value="t {description} {file_list}" ), \
             patch.object( ex_mod, "PromptTemplateProcessor" ) as PTP, \
             patch.object( ex_mod.os.path, "exists", side_effect=lambda p: "deep-research" in p ), \
             patch.object( ex_mod.os, "listdir", return_value=[ "report.md" ] ), \
             patch.object( ex_mod.os, "walk", return_value=[] ), \
             patch.object( o, "_ask_for_arg", return_value="the report" ):
            PTP.return_value.process_template.side_effect = lambda t, n: t
            o.llm_factory.get_client = MagicMock( return_value=MagicMock( run=MagicMock( return_value="<xml/>" ) ) )
            out = o._handle_fuzzy_file_match( "u@x" )
        self.assertTrue( out.endswith( "/report.md" ) )

    def test_fuzzy_basename_validation_scans_and_skips( self ):
        # 997->996 (first rel_path basename != m → next) + 996->992 (a fuzzy m matching no
        # basename → inner loop exhausts → next outer m). docs_map has 2 entries.
        o = _mk_expeditor()
        cm = _inner_config_mgr()
        with _patch_config_mgr( cm ), _patch_fuzzy_model( [ "beta.md", "ghost.md" ] ), \
             patch.object( ex_mod.cu, "get_project_root", return_value="/p" ), \
             patch.object( ex_mod.cu, "get_file_as_string", return_value="t {description} {file_list}" ), \
             patch.object( ex_mod, "PromptTemplateProcessor" ) as PTP, \
             patch.object( ex_mod.os.path, "exists", side_effect=lambda p: "deep-research" in p ), \
             patch.object( ex_mod.os, "listdir", return_value=[ "alpha.md", "beta.md" ] ), \
             patch.object( ex_mod.os, "walk", return_value=[] ), \
             patch.object( o, "_ask_for_arg", return_value="the beta one" ):
            PTP.return_value.process_template.side_effect = lambda t, n: t
            o.llm_factory.get_client = MagicMock( return_value=MagicMock( run=MagicMock( return_value="<xml/>" ) ) )
            out = o._handle_fuzzy_file_match( "u@x" )
        self.assertTrue( out.endswith( "/beta.md" ) )   # only beta.md basename-matched

    def test_fuzzy_multi_pick_int_out_of_range_falls_to_first( self ):
        # 1025->1031: a valid int that is out of range → skip the numeric return, fall to name/first.
        o, ctx = self._multi_match_setup( pick="9" )
        out = self._run_multi( o, ctx )
        self.assertTrue( out.endswith( "/alpha.md" ) )   # out-of-range int → fallback first

    def test_agent_specific_search_path_and_presentations_dir( self ):
        # Exercises the agent-specific search-paths branch + presentations dir scan + os.walk.
        o = _mk_expeditor( debug=True )
        cm = _inner_config_mgr( search_paths="/extra" )
        def _exists( p ): return ( "deep-research" in p ) or ( "presentations" in p ) or ( "/p/extra" in p )
        with _patch_config_mgr( cm ), \
             patch.object( ex_mod.cu, "get_project_root", return_value="/p" ), \
             patch.object( ex_mod.os.path, "exists", side_effect=_exists ), \
             patch.object( ex_mod.os, "listdir", side_effect=lambda d: [ "r.md" ] if "deep-research" in d else [ "slides.yaml" ] ), \
             patch.object( ex_mod.os, "walk", return_value=[ ( "/p/extra", [], [ "more.md" ] ) ] ), \
             patch.object( o, "_ask_for_arg", return_value="slides.yaml" ):
            out = o._handle_fuzzy_file_match( "u@x", agent_display_name="Podcast Generator" )
        self.assertTrue( out.endswith( "slides.yaml" ) )


# ============================================================================
# _handle_tfe_checkpoint_match
# ============================================================================

def _patch_resume_resolver( candidates, fuzzy_matches=None ):
    mod = types.ModuleType( "cosa.agents.test_fix_expediter.resume_resolver" )
    mod.list_resume_candidates = MagicMock( return_value=candidates )
    mod.fuzzy_match_candidates = MagicMock( return_value=fuzzy_matches or [] )
    return patch.dict( sys.modules, { "cosa.agents.test_fix_expediter.resume_resolver": mod } )


class TestTfeCheckpointMatch( unittest.TestCase ):

    def test_no_candidates_asks_fallback( self ):
        o = _mk_expeditor( debug=True )
        with _patch_resume_resolver( [] ), \
             patch.object( o, "_ask_for_arg", return_value="tfe-12345678" ) as ask:
            out = o._handle_tfe_checkpoint_match( "u@x" )
        self.assertEqual( out, "tfe-12345678" )
        ask.assert_called_once()

    def test_description_prompt_none_returns_none( self ):
        o = _mk_expeditor()
        with _patch_resume_resolver( [ { "job_id": "tfe-1" } ] ), \
             patch.object( o, "_ask_for_arg", return_value=None ):
            self.assertIsNone( o._handle_tfe_checkpoint_match( "u@x" ) )

    def test_fast_path_job_id( self ):
        o = _mk_expeditor( debug=True )
        with _patch_resume_resolver( [ { "job_id": "tfe-1" } ] ):
            out = o._handle_tfe_checkpoint_match( "u@x", user_description="tfe-abcd1234" )
        self.assertEqual( out, "tfe-abcd1234" )

    def test_fast_path_plan_path( self ):
        o = _mk_expeditor()
        with _patch_resume_resolver( [ { "job_id": "tfe-1" } ] ):
            out = o._handle_tfe_checkpoint_match( "u@x", user_description="/x/plans/foo-plan.md" )
        self.assertEqual( out, "/x/plans/foo-plan.md" )

    def test_auto_accept_high_confidence_stalled( self ):
        o = _mk_expeditor( debug=True )
        fm = [ { "job_id": "tfe-aaa", "confidence": 0.95, "status": "stalled" } ]
        with _patch_resume_resolver( [ { "job_id": "tfe-aaa" } ], fuzzy_matches=fm ):
            out = o._handle_tfe_checkpoint_match( "u@x", user_description="the auth one" )
        self.assertEqual( out, "tfe-aaa" )

    def test_no_fuzzy_matches_asks_fallback( self ):
        o = _mk_expeditor( debug=True )
        with _patch_resume_resolver( [ { "job_id": "tfe-1" } ], fuzzy_matches=[] ), \
             patch.object( o, "_ask_for_arg", return_value="tfe-99999999" ):
            out = o._handle_tfe_checkpoint_match( "u@x", user_description="vague" )
        self.assertEqual( out, "tfe-99999999" )

    def _low_conf_matches( self ):
        return [ { "job_id": "tfe-alpha111", "confidence": 0.5, "status": "stalled", "summary": "auth bug" },
                 { "job_id": "tfe-beta2222", "confidence": 0.4, "status": "done", "summary": "ui bug" } ]

    def test_prompts_for_description_then_proceeds( self ):
        # 1089->1094: user_description=None → prompt returns a value → continue to fuzzy.
        o = _mk_expeditor()
        fm = [ { "job_id": "tfe-aaa", "confidence": 0.95, "status": "stalled" } ]
        with _patch_resume_resolver( [ { "job_id": "tfe-aaa" } ], fuzzy_matches=fm ), \
             patch.object( o, "_ask_for_arg", return_value="the auth one" ):
            out = o._handle_tfe_checkpoint_match( "u@x" )   # no user_description → prompts
        self.assertEqual( out, "tfe-aaa" )

    def test_disambiguate_pick_int_out_of_range_falls_to_top( self ):
        # 1132->1138: valid int out of range → skip numeric return, fall to partial/top.
        o = _mk_expeditor()
        with _patch_resume_resolver( [ {} ], fuzzy_matches=self._low_conf_matches() ), \
             patch.object( o, "_ask_for_arg", return_value="9" ):
            out = o._handle_tfe_checkpoint_match( "u@x", user_description="bug" )
        self.assertEqual( out, "tfe-alpha111" )

    def test_disambiguate_pick_by_number( self ):
        o = _mk_expeditor()
        with _patch_resume_resolver( [ {} ], fuzzy_matches=self._low_conf_matches() ), \
             patch.object( o, "_ask_for_arg", return_value="2" ):
            out = o._handle_tfe_checkpoint_match( "u@x", user_description="bug" )
        self.assertEqual( out, "tfe-beta2222" )

    def test_disambiguate_pick_none_returns_none( self ):
        o = _mk_expeditor()
        with _patch_resume_resolver( [ {} ], fuzzy_matches=self._low_conf_matches() ), \
             patch.object( o, "_ask_for_arg", return_value=None ):
            self.assertIsNone( o._handle_tfe_checkpoint_match( "u@x", user_description="bug" ) )

    def test_disambiguate_partial_id_match( self ):
        o = _mk_expeditor()
        with _patch_resume_resolver( [ {} ], fuzzy_matches=self._low_conf_matches() ), \
             patch.object( o, "_ask_for_arg", return_value="alpha111" ):
            out = o._handle_tfe_checkpoint_match( "u@x", user_description="bug" )
        self.assertEqual( out, "tfe-alpha111" )

    def test_disambiguate_no_match_falls_back_to_top( self ):
        o = _mk_expeditor()
        with _patch_resume_resolver( [ {} ], fuzzy_matches=self._low_conf_matches() ), \
             patch.object( o, "_ask_for_arg", return_value="zzz nonsense" ):
            out = o._handle_tfe_checkpoint_match( "u@x", user_description="bug" )
        self.assertEqual( out, "tfe-alpha111" )   # last resort: top match

    def test_exception_asks_fallback( self ):
        o = _mk_expeditor( debug=True )
        mod = types.ModuleType( "cosa.agents.test_fix_expediter.resume_resolver" )
        mod.list_resume_candidates = MagicMock( side_effect=RuntimeError( "resolver boom" ) )
        mod.fuzzy_match_candidates = MagicMock()
        with patch.dict( sys.modules, { "cosa.agents.test_fix_expediter.resume_resolver": mod } ), \
             patch.object( o, "_ask_for_arg", return_value="tfe-fallback" ):
            out = o._handle_tfe_checkpoint_match( "u@x", user_description="x" )
        self.assertEqual( out, "tfe-fallback" )


if __name__ == "__main__":
    unittest.main()
