#!/usr/bin/env python3
"""
Regression tests for bug 9b481811 — done-card abstract stuck at "loading…".

Root cause: the podcast job built its completion abstract (with the Play Here
links) ONLY for voice_io.notify and never stored it in self.artifacts["abstract"].
So running_fifo_queue._transition_to_done — which builds the running→done
job_state_transition metadata from artifacts.get("abstract") — emitted
abstract=None, and the client rendered the promoted done card with no abstract
(→ "loading…" placeholder, no Play Here) until a page reload re-fetched from the
persisted notification.

These guard the fix across BOTH completion branches AND the transition seam:
  1. real _execute stores a both-LANGUAGE abstract in artifacts["abstract"];
  2. _execute_dry_run stores its abstract too (the dry-run twin);
  3. _transition_to_done carries artifacts["abstract"] into the emitted
     transition metadata VERBATIM — so a both-language abstract cannot silently
     lose half its content on the way to the client.

All boundaries mocked — NO real LLM / TTS / SDK / network / disk / sleep.
"""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from cosa.agents.podcast_generator.job import PodcastGeneratorJob
from cosa.rest.job_state import JobState

# Reuse the podcast job's own test harness (same package): the fully-mocked
# _execute graph, the job factory, and the asyncio.run helper.
from cosa.tests.unit.agents.podcast_generator.test_job import _ExecGraph, _job, _run


# Both-language completion state: an en + es-MX run wrote two mp3s (bug 00e6aba1).
_TWO_LANG_STATE = {
    "final_audio_path"  : "/proj/io/pod/ep-en.mp3",
    "final_script_path" : "/proj/io/pod/ep-en.md",
    "audio_paths_by_language"  : {
        "en"    : "/proj/io/pod/ep-en.mp3",
        "es-MX" : "/proj/io/pod/ep-es-MX.mp3",
    },
    "script_paths_by_language" : {
        "en"    : "/proj/io/pod/ep-en.md",
        "es-MX" : "/proj/io/pod/ep-es-MX.md",
    },
}


class TestArtifactsAbstractStored:
    """Both completion branches must populate artifacts["abstract"] (the fix)."""

    def test_real_path_stores_both_language_abstract( self ):
        """
        _execute (non-dry-run, en + es-MX) stores an abstract in artifacts, and
        that abstract carries a Play Here link for BOTH languages — not just the
        first. This is the content that must ride the transition.
        """
        job   = _job( target_languages=[ "en", "es-MX" ] )
        graph = _ExecGraph( state=_TWO_LANG_STATE )
        with graph.patcher(), \
             patch( "os.path.exists", return_value=True ), \
             patch( "cosa.utils.util.get_project_root", return_value="/proj" ):
            _run( job._execute() )

        abstract = job.artifacts.get( "abstract" )
        assert abstract, "real-path completion did not store artifacts['abstract'] (bug 9b481811)"
        # both languages present, each with its own Play Here
        assert "ep-en.mp3" in abstract
        assert "ep-es-MX.mp3" in abstract
        assert abstract.count( "▶️ Play Here" ) == 2, (
            "abstract must carry a Play Here per language — losing half the content "
            "silently is exactly bug 00e6aba1's failure mode"
        )
        # the stored abstract is the SAME object the notify received
        completion = [ c for c in graph.voice_io.notify.await_args_list if c.kwargs.get( "abstract" ) ]
        assert len( completion ) == 1
        assert completion[ 0 ].kwargs[ "abstract" ] == abstract

    def test_dry_run_stores_abstract( self ):
        """
        _execute_dry_run stores its own abstract (the dry-run twin of the bug).
        Guards the dry-run abstract-storage line so a later edit can't delete it
        and re-break the dry-run done card.
        """
        # asyncio.sleep is awaited between dry-run breadcrumbs; make it a no-op coroutine
        async def _nosleep( *a, **k ):
            return None

        job   = _job( dry_run=True )
        graph = _ExecGraph()
        with graph.patcher(), \
             patch( "asyncio.sleep", _nosleep ), \
             patch( "os.path.exists", return_value=True ), \
             patch( "cosa.utils.util.get_project_root", return_value="/proj" ):
            _run( job._execute() )

        abstract = job.artifacts.get( "abstract" )
        assert abstract, "dry-run completion did not store artifacts['abstract'] (bug 9b481811 twin)"
        assert "Dry Run" in abstract


def _make_running_queue():
    """Minimal RunningFifoQueue with heavy construction deps stubbed.

    Mirrors src/tests/unit/test_agentic_pool.py::_make_running_queue — the
    LanceDB IO table + spaCy GistNormalizer are mocked so construction is fast.
    """
    from cosa.rest.running_fifo_queue import RunningFifoQueue
    from cosa.rest.fifo_queue import FifoQueue

    class _ConfigMgr:
        def get( self, key, default=None, return_type=None ):
            if key == "cj flow max concurrent agentic jobs":
                return 1
            return default

    with patch( "cosa.rest.running_fifo_queue.InputAndOutputTable" ) as MockIOT, \
         patch( "cosa.rest.running_fifo_queue.GistNormalizer" ) as MockGN:
        MockIOT.return_value = MagicMock()
        MockGN.return_value  = MagicMock()
        rq = RunningFifoQueue(
            app                  = None,
            websocket_mgr        = MagicMock(),
            snapshot_mgr         = MagicMock(),
            jobs_todo_queue      = FifoQueue(),
            jobs_done_queue      = FifoQueue(),
            jobs_dead_queue      = FifoQueue(),
            config_mgr           = _ConfigMgr(),
            emit_speech_callback = None,
        )
    rq._notify                = MagicMock()
    rq._evaluate_for_auto_fix = MagicMock()
    return rq


class TestAbstractRidesTransition:
    """_transition_to_done must carry artifacts['abstract'] into the emitted metadata."""

    def test_both_language_abstract_carried_verbatim( self ):
        """
        Given a job whose artifacts['abstract'] holds a two-language block, the
        running→done job_state_transition metadata must carry that abstract
        VERBATIM — both language link sets intact. This is the seam that, before
        the fix, emitted abstract=None and left the client card blank.
        """
        both_lang_abstract = (
            "**Podcast Activity Report**\n\n"
            "**English**: [▶️ Play Here](/app/audio?path=ep-en.mp3&embed=1)\n"
            "**Mexican Spanish**: [▶️ Play Here](/app/audio?path=ep-es-MX.mp3&embed=1)"
        )

        job = _job( target_languages=[ "en", "es-MX" ] )
        job.artifacts[ "abstract" ] = both_lang_abstract
        job.answer_conversational   = "done"
        job.state                   = JobState.COMPLETED

        rq = _make_running_queue()
        with patch( "cosa.rest.running_fifo_queue.emit_job_state_transition" ) as mock_emit:
            rq._transition_to_done( job )

        assert mock_emit.called, "_transition_to_done did not emit a job_state_transition"
        # metadata is passed as the last positional arg or the `metadata` kwarg
        call = mock_emit.call_args
        metadata = call.kwargs.get( "metadata" )
        if metadata is None:
            metadata = call.args[ -1 ]
        assert metadata[ "abstract" ] == both_lang_abstract, (
            "the transition dropped or altered the abstract — the client would render "
            "a blank/partial done card (bug 9b481811)"
        )
        # both language link sets survived the seam
        assert metadata[ "abstract" ].count( "▶️ Play Here" ) == 2
