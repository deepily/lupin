#!/usr/bin/env python3
"""
Unit tests for cosa.agents.deep_research_to_podcast.job

Target: DeepResearchToPodcastJob — the queue-executable wrapper around the
chained DR -> Podcast pipeline. AgenticJobBase.__init__ is self-contained
(no network / config), so the job is instantiated directly; the pipeline
agent, the deep_research voice_io/cosa_interface modules, and asyncio.sleep
are all mocked at the boundary so NO real LLM / SDK / network / sleep occurs.

Strategy:
    - __init__ / last_question_asked: exercised directly
    - do_all: self._execute patched -> success + failure (re-raise) branches
    - _execute: fake deep_research module + fake agent module; real
      PipelineState enum drives COMPLETED / CANCELLED / FAILED branches;
      finally-clause job_id clearing verified
    - _execute_dry_run: fake voice_io/cosa_interface + patched asyncio.sleep;
      all breadcrumbs + mock artifacts asserted

quick_smoke_test() and the __main__ guard are coverage-excluded by repo config.
"""

import sys
import types
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from cosa.agents.deep_research_to_podcast.job import DeepResearchToPodcastJob
from cosa.agents.deep_research_to_podcast.state import PipelineState, ChainedResult
from cosa.rest.job_state import JobState


def _make_module( name, **attrs ):
    mod = types.ModuleType( name )
    for key, value in attrs.items():
        setattr( mod, key, value )
    return mod


def _run( coro ):
    return asyncio.run( coro )


def _job( **kw ):
    defaults = dict( query="quantum", user_id="u1", user_email="u@test.com", session_id="s1" )
    defaults.update( kw )
    return DeepResearchToPodcastJob( **defaults )


# ----------------------------------------------------------------------------
# __init__ + last_question_asked
# ----------------------------------------------------------------------------
class TestInitAndDisplay:
    """
    Construction + display-string contract.

    Ensures:
        - JOB_TYPE / JOB_PREFIX class constants are pinned
        - id_hash carries the rp- prefix (via AgenticJobBase)
        - pipeline params stored; target_languages defaults to ["en"]
        - result fields start as None; state PENDING
        - last_question_asked renders the [Research->Podcast] prefix
    """

    def test_class_constants( self ):
        assert DeepResearchToPodcastJob.JOB_TYPE   == "research_to_podcast"
        assert DeepResearchToPodcastJob.JOB_PREFIX == "rp"

    def test_stores_params_and_defaults( self ):
        job = _job( budget=2.0, max_segments=4, dry_run=True,
                    audience="expert", audience_context="phds", verbose=True )
        assert job.id_hash.startswith( "rp-" )
        assert job.query            == "quantum"
        assert job.budget           == 2.0
        assert job.target_languages == [ "en" ]          # default
        assert job.max_segments     == 4
        assert job.dry_run          is True
        assert job.audience         == "expert"
        assert job.audience_context == "phds"
        assert job.verbose          is True
        assert job.research_path is None
        assert job.audio_path    is None
        assert job.script_path   is None
        assert job.cost_summary  is None
        assert job.state == JobState.PENDING

    def test_explicit_target_languages_passthrough( self ):
        job = _job( target_languages=[ "es" ] )
        assert job.target_languages == [ "es" ]

    def test_last_question_asked( self ):
        job = _job( query="state of AI" )
        assert job.last_question_asked == "[Research→Podcast] state of AI"


# ----------------------------------------------------------------------------
# do_all (success / failure) with _execute patched
# ----------------------------------------------------------------------------
class TestDoAll:
    """
    do_all bridges to async _execute via asyncio.run and manages job state.

    Ensures:
        - success: state COMPLETED, result + answer_conversational set, returns answer
        - failure: state FAILED, error captured, conversational error set, re-raises
        - debug=True prints start/duration (success) and traceback (failure)
    """

    def test_success_sets_completed_state( self, capsys ):
        job = _job( debug=True )
        with patch.object( job, "_execute", AsyncMock( return_value="ANSWER" ) ):
            out = job.do_all()
        assert out == "ANSWER"
        assert job.state == JobState.COMPLETED
        assert job.result == "ANSWER"
        assert job.answer_conversational == "ANSWER"
        assert job.started_at   is not None
        assert job.completed_at is not None
        printed = capsys.readouterr().out
        assert "Starting do_all()" in printed
        assert "Completed in"      in printed

    def test_success_debug_false_is_quiet( self, capsys ):
        job = _job( debug=False )
        with patch.object( job, "_execute", AsyncMock( return_value="A" ) ):
            job.do_all()
        assert capsys.readouterr().out == ""

    def test_failure_sets_failed_and_reraises( self, capsys ):
        job = _job( debug=True )
        with patch.object( job, "_execute", AsyncMock( side_effect=RuntimeError( "kaboom" ) ) ):
            with pytest.raises( RuntimeError, match="kaboom" ):
                job.do_all()
        assert job.state == JobState.FAILED
        assert job.error == "kaboom"
        assert job.answer_conversational == "Research→Podcast pipeline failed: kaboom"
        assert job.completed_at is not None
        assert "Failed: kaboom" in capsys.readouterr().out

    def test_failure_debug_false_no_traceback( self ):
        job = _job( debug=False )
        with patch.object( job, "_execute", AsyncMock( side_effect=ValueError( "x" ) ) ):
            with pytest.raises( ValueError ):
                job.do_all()
        assert job.state == JobState.FAILED


# ----------------------------------------------------------------------------
# _execute (non-dry-run) — fake DR module + fake agent module, real enum
# ----------------------------------------------------------------------------
class _ExecGraph:
    """
    Installs fake deep_research + fake pipeline-agent modules for _execute.

    The agent's run_async returns a real ChainedResult so the job's
    PipelineState comparisons run against the genuine enum.
    """

    def __init__( self, result ):
        self.voice_io = MagicMock()
        self.voice_io.notify = AsyncMock()
        self.cosa_interface = MagicMock()
        self.cosa_interface._get_sender_id.return_value = "sender-id"

        agent_inst = MagicMock()
        agent_inst.run_async = AsyncMock( return_value=result )
        self.agent_ctor = MagicMock( return_value=agent_inst )

        self.modules = {
            "cosa.agents.deep_research": _make_module(
                "cosa.agents.deep_research",
                voice_io       = self.voice_io,
                cosa_interface = self.cosa_interface,
            ),
            "cosa.agents.deep_research_to_podcast.agent": _make_module(
                "cosa.agents.deep_research_to_podcast.agent",
                DeepResearchToPodcastAgent = self.agent_ctor,
            ),
        }

    def patcher( self ):
        return patch.dict( sys.modules, self.modules )


class TestExecute:
    """
    _execute orchestration branches (non-dry-run).

    Ensures:
        - COMPLETED -> stores paths/artifacts/cost_summary, returns summary
        - CANCELLED -> cancel notify + cancellation string
        - FAILED    -> urgent notify + raised Exception(error)
        - job_id always cleared in finally (even on raise)
        - debug prints budget line (set vs unlimited)
    """

    def _completed_result( self ):
        return ChainedResult(
            research_path     = "/io/dr/r.md",
            research_abstract = "abs",
            audio_path        = "/io/pod/a.mp3",
            script_path       = "/io/pod/s.md",
            dr_cost           = 1.0,
            pg_cost           = 0.5,
            total_cost        = 1.5,
            state             = PipelineState.COMPLETED,
        )

    def test_completed_stores_results( self, capsys ):
        job   = _job( budget=2.0, debug=True )
        graph = _ExecGraph( self._completed_result() )
        with graph.patcher():
            out = _run( job._execute() )
        assert "Pipeline complete!" in out
        assert "$1.5000" in out
        assert job.research_path == "/io/dr/r.md"
        assert job.audio_path    == "/io/pod/a.mp3"
        assert job.script_path   == "/io/pod/s.md"
        assert job.artifacts[ "research_abstract" ] == "abs"
        assert job.cost_summary == {
            "dr_cost_usd"    : 1.0,
            "pg_cost_usd"    : 0.5,
            "total_cost_usd" : 1.5,
        }
        # boundary wiring
        assert job.cost_summary is job.artifacts[ "cost_summary" ]
        graph.voice_io.set_job_id.assert_called_once_with( job.id_hash )
        graph.voice_io.clear_job_id.assert_called_once_with()    # finally
        assert "Budget: $2.0" in capsys.readouterr().out

    def test_completed_unlimited_budget_debug_line( self, capsys ):
        job   = _job( budget=None, debug=True )
        graph = _ExecGraph( self._completed_result() )
        with graph.patcher():
            _run( job._execute() )
        assert "Budget: unlimited" in capsys.readouterr().out

    def test_cancelled_returns_cancel_message( self ):
        result = ChainedResult( state=PipelineState.CANCELLED )
        job    = _job()
        graph  = _ExecGraph( result )
        with graph.patcher():
            out = _run( job._execute() )
        assert out == "Research→Podcast pipeline was cancelled by the user."
        graph.voice_io.clear_job_id.assert_called_once_with()

    def test_failed_raises_with_error_message( self ):
        result = ChainedResult( state=PipelineState.FAILED, error="dr exploded" )
        job    = _job()
        graph  = _ExecGraph( result )
        with graph.patcher():
            with pytest.raises( Exception, match="dr exploded" ):
                _run( job._execute() )
        # urgent notify fired and job_id cleared despite the raise
        urgent = [ c for c in graph.voice_io.notify.await_args_list if c.kwargs.get( "priority" ) == "urgent" ]
        assert len( urgent ) == 1
        graph.voice_io.clear_job_id.assert_called_once_with()

    def test_failed_with_none_error_uses_unknown( self ):
        result = ChainedResult( state=PipelineState.FAILED, error=None )
        job    = _job()
        graph  = _ExecGraph( result )
        with graph.patcher():
            with pytest.raises( Exception, match="Unknown error" ):
                _run( job._execute() )

    def test_dry_run_routes_to_dry_run_helper( self ):
        # dry_run=True must short-circuit to _execute_dry_run before any agent build.
        job   = _job( dry_run=True )
        graph = _ExecGraph( self._completed_result() )
        with graph.patcher(), patch.object(
            job, "_execute_dry_run", AsyncMock( return_value="DRY" )
        ) as dry:
            out = _run( job._execute() )
        assert out == "DRY"
        dry.assert_awaited_once()
        graph.agent_ctor.assert_not_called()                 # never built the real agent


# ----------------------------------------------------------------------------
# _execute_dry_run — patched asyncio.sleep, fake voice_io/cosa_interface
# ----------------------------------------------------------------------------
class TestExecuteDryRun:
    """
    _execute_dry_run simulates the pipeline with breadcrumb notifications.

    Ensures:
        - 10 breadcrumb notifies + 1 completion notify fire (11 total)
        - asyncio.sleep is awaited 10 times (mocked — no real delay)
        - mock artifact paths + zeroed cost summary are stored
        - job_id set then cleared; returns the dry-run summary string
        - debug=True prints the DRY RUN banner
    """

    def _voice_and_iface( self ):
        voice_io = MagicMock()
        voice_io.notify = AsyncMock()
        cosa_interface = MagicMock()
        cosa_interface._get_sender_id.return_value = "sid"
        return voice_io, cosa_interface

    def test_dry_run_full_flow( self, capsys ):
        job = _job( debug=True )
        voice_io, cosa_interface = self._voice_and_iface()
        with patch( "asyncio.sleep", AsyncMock() ) as slp:
            out = _run( job._execute_dry_run( voice_io, cosa_interface ) )

        assert out == "Dry run complete. Research and podcast simulation finished."
        assert voice_io.notify.await_count == 11             # 10 breadcrumbs + completion
        assert slp.await_count == 10
        # mock artifacts
        assert job.research_path.endswith( "/report.md" )
        assert job.audio_path.endswith( "/podcast.mp3" )
        assert job.script_path.endswith( "/script.md" )
        assert job.artifacts[ "research_abstract" ] == "Mock abstract from dry-run mode."
        assert job.cost_summary == {
            "dr_cost_usd"    : 0.0,
            "pg_cost_usd"    : 0.0,
            "total_cost_usd" : 0.0,
        }
        voice_io.set_job_id.assert_called_once_with( job.id_hash )
        voice_io.clear_job_id.assert_called_once_with()
        assert "DRY RUN MODE" in capsys.readouterr().out

    def test_dry_run_debug_false_no_banner( self, capsys ):
        job = _job( debug=False )
        voice_io, cosa_interface = self._voice_and_iface()
        with patch( "asyncio.sleep", AsyncMock() ):
            _run( job._execute_dry_run( voice_io, cosa_interface ) )
        assert "DRY RUN MODE" not in capsys.readouterr().out


# ----------------------------------------------------------------------------
# Real-path completion abstract (bug 2da4095a)
# ----------------------------------------------------------------------------
class TestRealPathCompletionAbstract:
    """
    bug 2da4095a: the real (non-dry-run) path must BUILD a completion abstract with
    per-language Play-Here links and store it in artifacts["abstract"] so the promoted
    running→done card renders links WITHOUT a page reload. Before the fix the real
    path returned a bare "Pipeline complete!" string and stored no abstract, so
    running_fifo_queue._transition_to_done emitted abstract=None → blank done card.
    Sibling of 9b481811 but deeper — a missing BUILD, not just a missing store.
    """

    def _two_lang_result( self ):
        return ChainedResult(
            research_path     = "/proj/io/dr/report.md",
            research_abstract = "abs",
            audio_path        = "/proj/io/pod/ep-en.mp3",
            script_path       = "/proj/io/pod/ep-en.md",
            dr_cost           = 1.0,
            pg_cost           = 0.5,
            total_cost        = 1.5,
            state             = PipelineState.COMPLETED,
            pg_artifacts      = {
                "audio_paths_by_language"  : {
                    "en"    : "/proj/io/pod/ep-en.mp3",
                    "es-MX" : "/proj/io/pod/ep-es-MX.mp3",
                },
                "script_paths_by_language" : {
                    "en"    : "/proj/io/pod/ep-en.md",
                    "es-MX" : "/proj/io/pod/ep-es-MX.md",
                },
            },
        )

    def test_real_path_stores_both_language_abstract( self ):
        """en + es-MX → abstract carries a Play Here per language, and is stored."""
        job   = _job( target_languages=[ "en", "es-MX" ] )
        graph = _ExecGraph( self._two_lang_result() )
        with graph.patcher(), patch( "cosa.utils.util.get_project_root", return_value="/proj" ):
            _run( job._execute() )

        abstract = job.artifacts.get( "abstract" )
        assert abstract, "real-path completion did not store artifacts['abstract'] (bug 2da4095a)"
        assert "ep-en.mp3"    in abstract
        assert "ep-es-MX.mp3" in abstract
        assert abstract.count( "▶️ Play Here" ) == 2, (
            "abstract must carry a Play Here per language — losing half the content "
            "silently is exactly bug 00e6aba1's failure mode"
        )
        assert "report.md" in abstract, "research report link missing from abstract"
        # the stored abstract is the SAME string the completion notify received
        completion = [ c for c in graph.voice_io.notify.await_args_list if c.kwargs.get( "abstract" ) ]
        assert len( completion ) == 1
        assert completion[ 0 ].kwargs[ "abstract" ] == abstract

    def test_real_path_single_language_fallback( self ):
        """No per-language maps → fall back to the single primary audio/script path."""
        result = ChainedResult(
            research_path = "/proj/io/dr/r.md",
            audio_path    = "/proj/io/pod/only-en.mp3",
            script_path   = "/proj/io/pod/only-en.md",
            total_cost    = 0.9,
            state         = PipelineState.COMPLETED,
        )
        job   = _job( target_languages=[ "en" ] )
        graph = _ExecGraph( result )
        with graph.patcher(), patch( "cosa.utils.util.get_project_root", return_value="/proj" ):
            _run( job._execute() )

        abstract = job.artifacts.get( "abstract" )
        assert abstract
        assert abstract.count( "▶️ Play Here" ) == 1
        assert "only-en.mp3" in abstract

    def test_real_path_edge_arcs_and_notify_failure( self, capsys ):
        """
        Exercise the abstract-builder edge arcs in one pass:
          - a relative "io/"-prefixed path,
          - None-valued language entries (script/research missing),
          - a language present in the maps but NOT in target_languages (appended),
          - a language whose links are all empty (line skipped),
          - research_path absent (no research line),
          - the completion notify raising (caught + logged, run still completes).
        """
        result = ChainedResult(
            research_path = None,                        # → no research line
            audio_path    = "/proj/io/pod/primary.mp3",  # unused: per-lang maps present
            script_path   = None,
            total_cost    = 0.4,
            state         = PipelineState.COMPLETED,
            pg_artifacts  = {
                "audio_paths_by_language"  : {
                    "en"    : "io/pod/en.mp3",   # already-relative path
                    "es-MX" : None,              # extra lang, empty → skipped
                    "fr"    : None,              # extra lang, empty → skipped
                },
                "script_paths_by_language" : { "en": None },
            },
        )
        job = _job( target_languages=[ "en" ] )
        graph = _ExecGraph( result )

        async def _raise_on_completion( *a, **k ):
            if k.get( "abstract" ): raise RuntimeError( "notify boom" )
        graph.voice_io.notify = AsyncMock( side_effect=_raise_on_completion )

        with graph.patcher(), patch( "cosa.utils.util.get_project_root", return_value="/proj" ):
            out = _run( job._execute() )

        abstract = job.artifacts.get( "abstract" )
        assert abstract, "abstract must still be stored even when the notify fails"
        assert "pod/en.mp3"      in abstract           # "io/" prefix stripped
        assert abstract.count( "▶️ Play Here" ) == 1   # only en had audio
        assert "Research Report" not in abstract       # research_path was None
        assert "Pipeline complete!" in out             # run completed despite notify raise
        assert "completion notify failed" in capsys.readouterr().out


class TestLanguageLabelSingleSource:
    """
    Row 81040071: the DRP job once hand-copied podcast_generator's LANGUAGE_NAMES
    into a module-level _LANGUAGE_NAMES — two label maps that WILL drift and
    mislabel a language in front of an audience. The fix moved the map to a leaf
    module both consumers import. These identity assertions BITE the moment anyone
    re-inlines a copy: a fresh dict literal breaks `is` even if the values match.
    """

    def test_drp_job_uses_the_canonical_leaf_map( self ):
        from cosa.agents.language_names import LANGUAGE_NAMES
        from cosa.agents.deep_research_to_podcast import job as drp_job
        assert drp_job._LANGUAGE_NAMES is LANGUAGE_NAMES, \
            "DRP job must import the single-source map, not re-inline it (row 81040071)"

    def test_podcast_config_reexports_the_canonical_leaf_map( self ):
        from cosa.agents.language_names import LANGUAGE_NAMES
        from cosa.agents.podcast_generator.config import LANGUAGE_NAMES as cfg_names
        assert cfg_names is LANGUAGE_NAMES, \
            "podcast_generator.config must re-export the single-source map (row 81040071)"
