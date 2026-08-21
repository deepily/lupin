#!/usr/bin/env python3
"""
Door 8 end to end: a spoken agentic command reaches a REAL flow and is dispatched.

WHY THIS FILE EXISTS AND THE EXISTING DOOR-8 TESTS DID NOT CATCH THE DEFECT. Those tests
hand the door a MagicMock flow and assert that `ask` was called with the transcription.
That proves the transcription REACHES the flow. It cannot prove the flow can do anything
with it — a mock answers every call, including the ones a real flow would refuse. Behind
the mock, `ask` resolved every agentic command to None and answered the receptionist's
"I do not understand", so "do a deep research on the state of AI" was unanswerable by
voice while door 8's own suite stayed green (bug b7fe8941, raised by María).

So this file puts a REAL AskFlow behind the real door. Everything the flow talks to is a
stand-in — no model server, no Postgres, no TTS, no whisper — but the flow itself is the
production object, and the branch under test is its own.

Venue: :7999-eligible. Pure in-process; no server, no network, no GPU.
"""

import base64
import sys
import types
import unittest
from unittest.mock import MagicMock, patch, mock_open, AsyncMock

import cosa.rest.routers.speech as speech
from cosa.rest.routers.speech import upload_and_transcribe_mp3_file
from cosa.rest.v2.flow import AskFlow

P = "cosa.rest.routers.speech"


# ────────────────────────────────────────────────────────── stand-ins for the flow's stack

class _Router:
    """Stands in for the LLM router: says what command the words mean."""

    def __init__( self, command ):
        self.command = command

    def route( self, question ):
        return ( self.command, question )


class _Expeditor:
    """Stands in for the argument expeditor: hands back a fixed extraction."""

    def __init__( self, final_args=None, missing=() ):
        self._final_args = final_args if final_args is not None else { }
        self._missing    = list( missing )
        self.calls       = [ ]

    def extract( self, command, raw_args, question, spec ):
        self.calls.append( command )
        return types.SimpleNamespace(
            final_args=dict( self._final_args ), missing=list( self._missing ),
            fallback_questions={ arg: f"What {arg} would you like?" for arg in self._missing },
            fallback_defaults={ }, special_handlers={ },
        )


class _Executor:
    """Stands in for the queued executor: accepts the work and reports it running."""

    def __init__( self ):
        self.works = [ ]

    def submit( self, work, trace ):
        self.works.append( work )
        return types.SimpleNamespace( status="waiting", answer=None, answer_raw=None,
                                      job_id="job-1", error=None, snapshotable=False )


class _Cache:
    def lookup( self, question ):
        return types.SimpleNamespace( is_replay_hit=False, snapshot=None, similarity=0.0,
                                      candidates=[ ], embed_cached=False )

    def normalize( self, q ): return q
    def gist( self, q ):      return q


class _Pending:
    def __init__( self ): self.put_calls = [ ]

    def put( self, **kwargs ):
        self.put_calls.append( kwargs )
        return "pend-1"

    def get( self, pending_id ):                     # pragma: no cover - the door never resumes
        return None

    def set_status( self, *a, **kw ):                # pragma: no cover - the door never resumes
        return None


class _Receptionist:
    """Answers like the real receptionist so a degrade is visible rather than a crash."""

    def __init__( self, **kwargs ):
        self.kwargs = kwargs
        self.routing_command = "agent router go to receptionist"

    def run_prompt( self, **kwargs ):                # pragma: no cover - executor is faked
        return "I do not understand"


class _Job:
    """The job the agentic factory hands back — enough surface for the queue path."""

    def __init__( self, **kwargs ):
        self.kwargs             = kwargs
        self.routing_command    = kwargs.get( "command", "agent router go to deep research" )
        self.scheduled_at       = None
        self.monopolize         = False
        self.spawned_by_id_hash = None


class _Factory:
    """Records what the flow asked it to build."""

    def __init__( self ):
        self.calls = [ ]

    def __call__( self, **kwargs ):
        self.calls.append( kwargs )
        return _Job( **kwargs )


def _flow( tmpdir, command, final_args=None, missing=(), factory=None ):
    """A REAL AskFlow with stand-in collaborators — the object under test is the flow."""
    return AskFlow(
        _Cache(), _Router( command ), _Expeditor( final_args, missing ), _Executor(), _Pending(),
        crud_enabled=False, similarity_floor=100.0, writeback_enabled=False,
        receptionist_factory=_Receptionist, notifier=lambda request: None,
        agentic_factory=factory or _Factory(), trace_dir=tmpdir,
    )


def _patch_fastapi_main( mock_main ):
    """Dual-key `lupin_app.main` patch, as the speech router's own suite does."""
    pkg = MagicMock()
    pkg.main = mock_main
    return patch.dict( sys.modules, { "lupin_app": pkg, "lupin_app.main": mock_main } )


class TestDoor8DispatchesASpokenAgenticCommand( unittest.IsolatedAsyncioTestCase ):
    """
    The spoken door, the real flow, and an agentic transcription — the combination the
    mock-flow tests could not exercise.
    """

    _USER = { "uid": "u1234567890", "email": "t@t.com" }

    def _request( self ):
        req = MagicMock()
        req.body        = AsyncMock( return_value=base64.b64encode( b"rawaudio" ) )
        req.client.host = "1.2.3.4"
        req.headers     = { }
        return req

    def _munger( self, transcription ):
        munger = MagicMock()
        munger.is_agent.return_value  = True
        munger.transcription          = transcription
        munger.get_jsons.return_value = '{"ok": true}'
        return munger

    async def _call( self, munger, flow ):
        provider = MagicMock()
        provider.transcribe.return_value = MagicMock( strip=MagicMock( return_value=munger.transcription ) )
        config_mgr = MagicMock()
        config_mgr.get.return_value = "/audio.wav"
        main = MagicMock(); main.app_debug = False; main.app_verbose = False
        with _patch_fastapi_main( main ), \
             patch( "builtins.open", mock_open() ), \
             patch.object( speech.du, "get_project_root", return_value="/root" ), \
             patch.object( speech.du, "write_string_to_file" ), \
             patch( f"{P}.mmm.MultiModalMunger", return_value=munger ), \
             patch( f"{P}.InputAndOutputTable" ):
            return await upload_and_transcribe_mp3_file(
                request=self._request(), prefix="pfx", prompt_key="generic",
                prompt_verbose="verbose", websocket_id=None,
                whisper_pipeline=MagicMock(), provider=provider,
                config_mgr=config_mgr, ask_flow=flow, current_user=dict( self._USER ),
            )

    async def test_a_spoken_deep_research_request_becomes_a_job( self ):
        """
        THE CASE THAT WAS MISSING. Before the ask-side agentic arm this came back
        path="receptionist" — the user spoke a command the registry knows and was told it
        was not understood.

        RED ON REVERT: drop the resolve_agentic fallback in AskFlow.ask and the two
        assertions below fail together.
        """
        factory = _Factory()
        flow    = _flow( self.enterContext( __import__( "tempfile" ).TemporaryDirectory() ),
                         "agent router go to deep research",
                         final_args={ "query": "the state of AI" }, factory=factory )
        munger  = self._munger( "do a deep research on the state of AI" )

        resp = await self._call( munger, flow )

        self.assertEqual( resp.status_code, 200 )
        self.assertNotEqual( munger.results[ "path" ], "receptionist", munger.results )
        self.assertEqual( munger.results[ "route_reason" ], "submitted_prebuilt" )
        self.assertEqual( len( factory.calls ), 1, "the spoken command must reach the agentic factory" )
        self.assertEqual( factory.calls[ 0 ][ "command" ], "agent router go to deep research" )
        self.assertEqual( factory.calls[ 0 ][ "args_dict" ], { "query": "the state of AI" } )

    async def test_the_spoken_words_are_what_the_arguments_come_from( self ):
        """The door hands over a transcription and nothing else, so the extraction the
        job is built from has to be made from those words — not from anything the caller
        decided in advance, because the caller is a microphone."""
        expeditor_seen = [ ]
        factory = _Factory()
        flow    = _flow( self.enterContext( __import__( "tempfile" ).TemporaryDirectory() ),
                         "agent router go to swe team",
                         final_args={ "task": "fix the parser" }, factory=factory )
        flow.expeditor.calls = expeditor_seen

        await self._call( self._munger( "get the swe team to fix the parser" ), flow )

        self.assertEqual( expeditor_seen, [ "agent router go to swe team" ] )
        self.assertEqual( factory.calls[ 0 ][ "args_dict" ], { "task": "fix the parser" } )

    async def test_a_spoken_command_missing_an_argument_asks_instead_of_building( self ):
        """There is a human at the microphone, so a gap is a question — parked for a
        second turn, never a job built from an argument nobody supplied."""
        factory = _Factory()
        flow    = _flow( self.enterContext( __import__( "tempfile" ).TemporaryDirectory() ),
                         "agent router go to deep research",
                         missing=[ "query" ], factory=factory )

        munger = self._munger( "do a deep research" )
        await self._call( munger, flow )

        self.assertEqual( munger.results[ "path" ],   "needs_input" )
        self.assertEqual( munger.results[ "status" ], "parked" )
        self.assertIsNotNone( munger.results[ "pending_id" ] )
        self.assertEqual( factory.calls, [ ], "nothing may be built while an argument is missing" )

    async def test_a_spoken_command_neither_reader_knows_still_gets_the_receptionist( self ):
        """The negative control. Without it, a flow that dispatched EVERYTHING would pass
        every test above while having lost the refusal entirely."""
        factory = _Factory()
        flow    = _flow( self.enterContext( __import__( "tempfile" ).TemporaryDirectory() ),
                         "agent router go to nowhere at all", factory=factory )

        munger = self._munger( "do the thing that does not exist" )
        await self._call( munger, flow )

        self.assertEqual( munger.results[ "path" ],         "receptionist" )
        self.assertEqual( munger.results[ "route_reason" ], "unknown_command" )
        self.assertEqual( factory.calls, [ ] )


if __name__ == "__main__":
    unittest.main()
