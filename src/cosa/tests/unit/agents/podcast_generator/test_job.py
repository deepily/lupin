#!/usr/bin/env python3
"""
Unit tests for cosa.agents.podcast_generator.job

Target: PodcastGeneratorJob — queue-executable wrapper around the podcast
orchestrator. AgenticJobBase.__init__ is self-contained, so the job is
instantiated directly; voice_io / cosa_interface / orchestrator / config /
ConfigurationManager / filesystem / asyncio.sleep are all mocked so NO real
LLM / TTS / SDK / network / disk / sleep occurs.

quick_smoke_test() and the __main__ guard are coverage-excluded by repo config.
"""

import sys
import types
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from cosa.agents.podcast_generator.job import PodcastGeneratorJob
from cosa.rest.job_state import JobState


def _make_module( name, **attrs ):
    mod = types.ModuleType( name )
    for key, value in attrs.items():
        setattr( mod, key, value )
    return mod


def _run( coro ):
    return asyncio.run( coro )


def _job( **kw ):
    defaults = dict(
        research_path="/io/dr/report.md", user_id="u1",
        user_email="u@test.com", session_id="s1",
    )
    defaults.update( kw )
    return PodcastGeneratorJob( **defaults )


# ----------------------------------------------------------------------------
# __init__ + last_question_asked
# ----------------------------------------------------------------------------
class TestInitAndDisplay:
    """
    Construction + display-string contract.

    Ensures JOB_TYPE/JOB_PREFIX, pg- id prefix, stored params (incl.
    target_languages default + force_failure_mode), and the [Podcast] basename
    display string.
    """

    def test_class_constants( self ):
        assert PodcastGeneratorJob.JOB_TYPE   == "podcast"
        assert PodcastGeneratorJob.JOB_PREFIX == "pg"

    def test_stores_params_and_defaults( self ):
        job = _job( max_segments=5, dry_run=True, force_failure_mode="code_bug",
                    audience="expert", audience_context="phds", verbose=True )
        assert job.id_hash.startswith( "pg-" )
        assert job.research_path      == "/io/dr/report.md"
        assert job.target_languages   == [ "en" ]
        assert job.max_segments       == 5
        assert job.dry_run            is True
        assert job.force_failure_mode == "code_bug"
        assert job.audience           == "expert"
        assert job.audience_context   == "phds"
        assert job.verbose            is True
        assert job.audio_path   is None
        assert job.script_path  is None
        assert job.cost_summary is None
        assert job.state == JobState.PENDING

    def test_explicit_target_languages( self ):
        assert _job( target_languages=[ "es", "fr" ] ).target_languages == [ "es", "fr" ]

    def test_last_question_asked_uses_basename( self ):
        assert _job( research_path="/io/dr/2026.01-topic.md" ).last_question_asked == "[Podcast] 2026.01-topic.md"


# ----------------------------------------------------------------------------
# do_all
# ----------------------------------------------------------------------------
class TestDoAll:
    """
    do_all bridges to async _execute and manages job state.

    Ensures success -> COMPLETED; _cancel_requested -> CANCELLED (with fallback
    answer); exception -> FAILED + re-raise; debug prints per branch.
    """

    def test_success( self, capsys ):
        job = _job( debug=True )
        with patch.object( job, "_execute", AsyncMock( return_value="ANSWER" ) ):
            out = job.do_all()
        assert out == "ANSWER"
        assert job.state == JobState.COMPLETED
        assert job.answer_conversational == "ANSWER"
        printed = capsys.readouterr().out
        assert "Starting do_all()" in printed
        assert "Completed in"      in printed

    def test_success_debug_false_quiet( self, capsys ):
        job = _job( debug=False )
        with patch.object( job, "_execute", AsyncMock( return_value="A" ) ):
            job.do_all()
        assert capsys.readouterr().out == ""

    def test_cancel_requested_with_result_uses_result( self, capsys ):
        job = _job( debug=True )
        job._cancel_requested = True
        with patch.object( job, "_execute", AsyncMock( return_value="partial answer" ) ):
            out = job.do_all()
        assert job.state == JobState.CANCELLED
        assert job.error == "Cancelled by user request"
        assert out == "partial answer"
        assert "Cancelled by user request" in capsys.readouterr().out

    def test_cancel_requested_without_result_uses_fallback( self ):
        job = _job()
        job._cancel_requested = True
        with patch.object( job, "_execute", AsyncMock( return_value=None ) ):
            out = job.do_all()
        assert job.state == JobState.CANCELLED
        assert out == "Podcast generation was cancelled by the user."

    def test_failure_reraises( self, capsys ):
        job = _job( debug=True )
        with patch.object( job, "_execute", AsyncMock( side_effect=RuntimeError( "kaboom" ) ) ):
            with pytest.raises( RuntimeError, match="kaboom" ):
                job.do_all()
        assert job.state == JobState.FAILED
        assert job.error == "kaboom"
        assert job.answer_conversational == "Podcast generation failed: kaboom"
        assert "Failed: kaboom" in capsys.readouterr().out

    def test_failure_debug_false( self ):
        job = _job( debug=False )
        with patch.object( job, "_execute", AsyncMock( side_effect=ValueError( "x" ) ) ):
            with pytest.raises( ValueError ):
                job.do_all()
        assert job.state == JobState.FAILED


# ----------------------------------------------------------------------------
# _execute (non-dry-run)
# ----------------------------------------------------------------------------
class _ExecGraph:
    """
    Installs fake voice_io/cosa_interface + orchestrator/config/ConfigurationManager
    modules for PodcastGeneratorJob._execute.

    Tunables: do_all_async script result (or None), api_client presence,
    podcast state (audio/script paths), and a notify failure injector.
    """

    def __init__( self, script="SCRIPT", has_api_client=True, state=None,
                  segment_count=3, duration=12.5, completion_notify_raises=False ):
        self.voice_io = MagicMock()
        if completion_notify_raises:
            async def _notify( *a, **kw ):
                if kw.get( "abstract" ) is not None:
                    raise RuntimeError( "notify boom" )
            self.voice_io.notify = AsyncMock( side_effect=_notify )
        else:
            self.voice_io.notify = AsyncMock()
        self.cosa_interface = MagicMock()
        self.cosa_interface._get_sender_id.return_value = "sender-id"

        self.orch = MagicMock()
        self.orch.podcast_id = "pg-abc"
        self.orch._podcast_state = state or {
            "final_audio_path"  : "/proj/io/pod/ep.mp3",
            "final_script_path" : "/proj/io/pod/ep.md",
        }
        if script:
            deck = MagicMock()
            deck.get_segment_count.return_value = segment_count
            deck.estimated_duration_minutes     = duration
            self.orch.do_all_async = AsyncMock( return_value=deck )
        else:
            self.orch.do_all_async = AsyncMock( return_value=None )
        if has_api_client:
            self.orch._api_client = MagicMock()
            self.orch.api_client.cost_estimate.estimated_cost_usd = 0.5
        else:
            self.orch._api_client = None

        self.orch_ctor   = MagicMock( return_value=self.orch )
        self.config_obj  = MagicMock()
        podcast_config   = MagicMock()
        podcast_config.from_config.return_value = self.config_obj
        self.podcast_config = podcast_config

        self.modules = {
            "cosa.agents.podcast_generator": _make_module(
                "cosa.agents.podcast_generator",
                voice_io=self.voice_io, cosa_interface=self.cosa_interface,
            ),
            "cosa.agents.podcast_generator.orchestrator": _make_module(
                "cosa.agents.podcast_generator.orchestrator",
                PodcastOrchestratorAgent=self.orch_ctor,
            ),
            "cosa.agents.podcast_generator.config": _make_module(
                "cosa.agents.podcast_generator.config",
                PodcastConfig=podcast_config,
            ),
            "cosa.config.configuration_manager": _make_module(
                "cosa.config.configuration_manager",
                ConfigurationManager=MagicMock(),
            ),
        }

    def patcher( self ):
        return patch.dict( sys.modules, self.modules )


class TestExecute:
    """
    _execute branch coverage (non-dry-run) with all boundaries faked.

    Ensures: path resolution (relative/absolute); missing-file FileNotFoundError;
    audience/audience_context overrides; script-None cancel; the _to_rel helper's
    four arcs (None / io_base / "io/" / lstrip); cost from api_client vs 0.0;
    the three completion-TTS variants; completion-notify failure swallowed;
    job_id cleared in finally.
    """

    def test_happy_full_with_overrides_and_links( self, capsys ):
        job   = _job( debug=True, max_segments=5, audience="expert", audience_context="phds" )
        graph = _ExecGraph()
        with graph.patcher(), \
             patch( "os.path.exists", return_value=True ), \
             patch( "cosa.utils.util.get_project_root", return_value="/proj" ):
            out = _run( job._execute() )
        assert "Podcast complete! Generated 3 segments" in out
        # overrides applied to config
        assert graph.config_obj.audience         == "expert"
        assert graph.config_obj.audience_context == "phds"
        # _to_rel io_base branch
        assert job.artifacts[ "audio_path" ]  == "pod/ep.mp3"
        assert job.artifacts[ "script_path" ] == "pod/ep.md"
        assert job.artifacts[ "podcast_id" ]  == "pg-abc"
        assert job.cost_summary[ "total_cost_usd" ] == 0.5
        assert job.cost_summary is job.artifacts[ "cost_summary" ]
        graph.voice_io.set_job_id.assert_called_once_with( job.id_hash )
        graph.voice_io.clear_job_id.assert_called_once_with()
        out_txt = capsys.readouterr().out
        assert "Research document:" in out_txt
        assert "Max segments: 5"    in out_txt

    def test_completion_abstract_emits_play_here_and_listen_links( self ):
        """
        Ensures: the completion abstract carries BOTH audio links, same path,
        in the on-stage order Play Here | Listen | Download —
            - Play Here -> /app/audio?path=<enc>&embed=1 (floating overlay; leads)
            - Listen    -> /app/audio?path=<enc>         (standalone tab; no &embed)
            - Download  -> /api/io/file?path=<enc>&download=true
        Only Play Here carries &embed=1, so the two audio forms are distinct.
        """
        job   = _job()
        graph = _ExecGraph()
        with graph.patcher(), \
             patch( "os.path.exists", return_value=True ), \
             patch( "cosa.utils.util.get_project_root", return_value="/proj" ):
            _run( job._execute() )

        completion = [ c for c in graph.voice_io.notify.await_args_list if c.kwargs.get( "abstract" ) ]
        assert len( completion ) == 1
        abstract = completion[ 0 ].kwargs[ "abstract" ]

        enc       = "pod/ep.mp3"                                    # quote( audio_rel ), '/' is safe
        play_here = f"[▶️ Play Here](/app/audio?path={enc}&embed=1)"
        listen    = f"[🎧 Listen](/app/audio?path={enc})"
        download  = f"[⬇️ Download](/api/io/file?path={enc}&download=true)"

        # both audio forms present, plus download
        assert play_here in abstract
        assert listen    in abstract
        assert download  in abstract

        # the two forms differ ONLY by &embed=1 — Listen must not carry it
        assert abstract.count( "&embed=1" ) == 1

        # on-stage order: overlay first, standalone tab second, download last
        assert abstract.index( play_here ) < abstract.index( listen ) < abstract.index( download )

    def test_dry_run_routes_to_dry_run_helper( self ):
        # dry_run=True must short-circuit to _execute_dry_run after reconfigure,
        # before importing/building the orchestrator.
        job   = _job( dry_run=True )
        graph = _ExecGraph()
        with graph.patcher(), patch.object(
            job, "_execute_dry_run", AsyncMock( return_value="DRY" )
        ) as dry:
            out = _run( job._execute() )
        assert out == "DRY"
        dry.assert_awaited_once()
        graph.orch_ctor.assert_not_called()
        graph.voice_io.reconfigure.assert_called_once_with()

    def test_debug_without_max_segments_skips_line( self, capsys ):
        # debug=True, max_segments=None exercises the 235->238 skip arc.
        job   = _job( debug=True, max_segments=None )
        graph = _ExecGraph()
        with graph.patcher(), \
             patch( "os.path.exists", return_value=True ), \
             patch( "cosa.utils.util.get_project_root", return_value="/proj" ):
            _run( job._execute() )
        out = capsys.readouterr().out
        assert "Research document:" in out
        assert "Max segments:" not in out

    def test_relative_path_resolution( self ):
        job   = _job( research_path="io/dr/report.md" )
        graph = _ExecGraph()
        with graph.patcher(), \
             patch( "os.path.exists", return_value=True ), \
             patch( "cosa.utils.util.get_project_root", return_value="/proj" ):
            _run( job._execute() )
        # orchestrator built with the project-root-joined absolute path
        assert graph.orch_ctor.call_args.kwargs[ "research_doc_path" ] == "/proj/io/dr/report.md"

    def test_missing_file_raises( self ):
        job   = _job()
        graph = _ExecGraph()
        with graph.patcher(), \
             patch( "os.path.exists", return_value=False ), \
             patch( "cosa.utils.util.get_project_root", return_value="/proj" ):
            with pytest.raises( FileNotFoundError, match="Research document not found" ):
                _run( job._execute() )

    def test_script_none_returns_cancelled( self ):
        job   = _job()
        graph = _ExecGraph( script=None )
        with graph.patcher(), \
             patch( "os.path.exists", return_value=True ), \
             patch( "cosa.utils.util.get_project_root", return_value="/proj" ):
            out = _run( job._execute() )
        assert out == "Podcast generation was cancelled by the user."
        graph.voice_io.clear_job_id.assert_called_once_with()

    def test_no_audio_uses_second_tts_variant_and_no_audio_links( self ):
        # final_audio_path None -> _to_rel None arc; has_audio False, segments>0
        job   = _job()
        graph = _ExecGraph( state={ "final_audio_path": None, "final_script_path": "/proj/io/pod/ep.md" } )
        with graph.patcher(), \
             patch( "os.path.exists", return_value=True ), \
             patch( "cosa.utils.util.get_project_root", return_value="/proj" ):
            _run( job._execute() )
        # second variant: script complete, audio pending
        completion = [ c for c in graph.voice_io.notify.await_args_list if c.kwargs.get( "abstract" ) ]
        assert len( completion ) == 1
        assert "script complete" in completion[ 0 ].args[ 0 ].lower()
        assert job.artifacts[ "audio_path" ] is None

    def test_no_segments_uses_third_tts_variant( self ):
        job   = _job()
        graph = _ExecGraph( segment_count=0, state={ "final_audio_path": None, "final_script_path": None } )
        with graph.patcher(), \
             patch( "os.path.exists", return_value=True ), \
             patch( "cosa.utils.util.get_project_root", return_value="/proj" ):
            _run( job._execute() )
        completion = [ c for c in graph.voice_io.notify.await_args_list if c.kwargs.get( "abstract" ) ]
        assert "no segments produced" in completion[ 0 ].args[ 0 ].lower()
        # script_rel None -> script_link absent; audio_rel None -> audio_links absent
        assert job.artifacts[ "script_path" ] is None

    def test_to_rel_io_prefix_and_lstrip_branches( self ):
        # audio "io/..." -> [3:] arc; script "/srv/..." -> lstrip("/") arc
        job   = _job()
        graph = _ExecGraph( state={ "final_audio_path": "io/x/a.mp3", "final_script_path": "/srv/s.md" } )
        with graph.patcher(), \
             patch( "os.path.exists", return_value=True ), \
             patch( "cosa.utils.util.get_project_root", return_value="/proj" ):
            _run( job._execute() )
        assert job.artifacts[ "audio_path" ]  == "x/a.mp3"
        assert job.artifacts[ "script_path" ] == "srv/s.md"

    def test_no_api_client_cost_zero( self ):
        job   = _job()
        graph = _ExecGraph( has_api_client=False )
        with graph.patcher(), \
             patch( "os.path.exists", return_value=True ), \
             patch( "cosa.utils.util.get_project_root", return_value="/proj" ):
            _run( job._execute() )
        assert job.cost_summary[ "total_cost_usd" ] == 0.0

    def test_completion_notify_failure_is_swallowed( self, capsys ):
        job   = _job()
        graph = _ExecGraph( completion_notify_raises=True )
        with graph.patcher(), \
             patch( "os.path.exists", return_value=True ), \
             patch( "cosa.utils.util.get_project_root", return_value="/proj" ):
            out = _run( job._execute() )
        # despite completion notify raising, _execute returns its answer
        assert "Podcast complete!" in out
        assert "completion notify failed" in capsys.readouterr().out
        graph.voice_io.clear_job_id.assert_called_once_with()


# ----------------------------------------------------------------------------
# _execute_dry_run
# ----------------------------------------------------------------------------
class TestExecuteDryRun:
    """
    _execute_dry_run breadcrumb simulation.

    Ensures 5 breadcrumbs + 1 completion (6 notifies), 5 mocked sleeps, mock
    artifacts + zeroed cost summary, the dry-run summary string, debug banner,
    and the force_failure_mode hook (raises through _raise_forced_failure).
    """

    def _voice_iface( self ):
        voice_io = MagicMock()
        voice_io.notify = AsyncMock()
        cosa_interface = MagicMock()
        cosa_interface._get_sender_id.return_value = "sid"
        return voice_io, cosa_interface

    def test_dry_run_full_flow( self, capsys ):
        job = _job( debug=True )
        voice_io, cosa_interface = self._voice_iface()
        with patch( "asyncio.sleep", AsyncMock() ) as slp:
            out = _run( job._execute_dry_run( voice_io, cosa_interface ) )
        assert out == "Dry run complete. Podcast simulation finished."
        assert voice_io.notify.await_count == 6                # 5 breadcrumbs + completion
        assert slp.await_count == 5
        assert job.audio_path.endswith( "/podcast.mp3" )
        assert job.script_path.endswith( "/script.md" )
        assert job.artifacts[ "podcast_id" ].startswith( "dry-run-" )
        assert job.cost_summary == {
            "script_cost_usd" : 0.0,
            "audio_cost_usd"  : 0.0,
            "total_cost_usd"  : 0.0,
        }
        assert "DRY RUN MODE" in capsys.readouterr().out

    def test_dry_run_debug_false_no_banner( self, capsys ):
        job = _job( debug=False )
        voice_io, cosa_interface = self._voice_iface()
        with patch( "asyncio.sleep", AsyncMock() ):
            _run( job._execute_dry_run( voice_io, cosa_interface ) )
        assert "DRY RUN MODE" not in capsys.readouterr().out

    def test_force_failure_mode_raises( self ):
        # force_failure_mode hook calls AgenticJobBase._raise_forced_failure
        # which raises KeyError for "code_bug".
        job = _job( force_failure_mode="code_bug" )
        voice_io, cosa_interface = self._voice_iface()
        with patch( "asyncio.sleep", AsyncMock() ):
            with pytest.raises( KeyError ):
                _run( job._execute_dry_run( voice_io, cosa_interface ) )
