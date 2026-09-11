"""
Unit tests for the speech router (`cosa.rest.routers.speech`).

Covers the full module surface:
- Sync helpers: `_run_whisper_with_retry` (success + CUDA-OOM retry), and the
  upload temp-file helpers `resolve_stt_upload_dir`, `audio_suffix_from_filename`,
  `save_audio_upload`, `remove_audio_upload` (row 27bcdd79).
- DI accessors: `get_whisper_pipeline`, `get_speech_provider`,
  `get_websocket_manager`, `get_config_manager`, `get_active_tasks`,
  `get_ask_flow` (dual-key `lupin_app.main` patch).
- Async route handlers: `upload_and_transcribe_mp3_file` (agent / non-agent /
  no-user-401 / no-flow / OOM-503 / generic-500), `get_tts_audio` (all validation branches + success +
  500), `get_tts_audio_elevenlabs` (validation incl. numeric ranges + success),
  `upload_and_transcribe_wav_file` (success + OOM + generic, temp-cleanup arcs).
  Both upload doors run against a REAL temp directory: the file the provider
  receives is checked on disk, and the directory is checked empty afterwards.
- Async streamers: `stream_tts_hybrid` (no-ws / success / mid-stream drop /
  OpenAI-error / general-error), `stream_tts_elevenlabs` (profile load / voice
  fallbacks / api-key-missing / verbose+non-verbose / message-loop arms incl.
  audio/non-audio/isFinal/error-subtypes/JSONDecodeError / client-drop /
  ConnectionClosed / generic), `websocket_pcm_tts_endpoint` (api-key-missing /
  success / WebSocketException / generic).

Boundary-mocked end-to-end — ZERO real GPU/CUDA, ZERO real network (OpenAI,
ElevenLabs, websockets all faked), ZERO real LLM/API spend, NEVER reads a real
API key (`du.get_api_key` patched). `torch.cuda` is never actually invoked.

PROD-BUG (found + tripwired, now FIXED): `stream_tts_elevenlabs` referenced an
undefined `app_debug` at L960 (only `app_verbose` was bound), dead-coding the
`debug_simulate_error` quota simulation. Originally captured here as an
xfail-strict tripwire + pin; the 1-line fix (`app_debug = main_module.app_debug`,
authorized by Tiberius 2026-06-01, flagged for Rick's ratification) landed, and
`TestStreamTtsElevenlabsDebugSimulateError` now asserts the real (formerly dead)
simulation behavior.
"""

import asyncio
import base64
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch, AsyncMock

import cosa.rest.routers.speech as speech
from cosa.rest.routers.speech import (
    _run_whisper_with_retry,
    DEFAULT_STT_UPLOAD_DIR,
    STT_UPLOAD_DIR_KEY,
    resolve_stt_upload_dir,
    audio_suffix_from_filename,
    save_audio_upload,
    remove_audio_upload,
    get_whisper_pipeline,
    get_speech_provider,
    get_websocket_manager,
    get_config_manager,
    get_active_tasks,
    get_ask_flow,
    upload_and_transcribe_mp3_file,
    get_tts_audio,
    get_tts_audio_elevenlabs,
    upload_and_transcribe_wav_file,
    stream_tts_hybrid,
    stream_tts_elevenlabs,
    websocket_pcm_tts_endpoint,
)

from fastapi import HTTPException

_SENTINEL = object()

P = "cosa.rest.routers.speech"


# ── shared fakes ────────────────────────────────────────────────────────────────


def _patch_fastapi_main( mock_main ):
    """Dual-key `lupin_app.main` patch (Gotcha 1)."""
    pkg = MagicMock()
    pkg.main = mock_main
    return patch.dict( sys.modules, { "lupin_app": pkg, "lupin_app.main": mock_main } )


class _ConnClosed( Exception ):
    """Stand-in for websockets.exceptions.ConnectionClosed."""


class _WsExc( Exception ):
    """Stand-in for websockets.exceptions.WebSocketException."""


def _fake_ws_module( connect ):
    """A MagicMock standing in for the `websockets` package global in speech.py."""
    m = MagicMock()
    m.connect = connect
    m.exceptions.ConnectionClosed = _ConnClosed
    m.exceptions.WebSocketException = _WsExc
    return m


class _FakeClientWs:
    """Client-side WebSocket fake — records send_json / send_bytes payloads."""
    def __init__( self ):
        self.json_sent  : list = [ ]
        self.bytes_sent : list = [ ]
        self.closed       = False
        self.send_json_raises = False
        self.fail_json_after  = None   # succeed for N sends, then raise (handler-send failure)
        self._json_calls      = 0
    async def send_json( self, data ):
        self._json_calls += 1
        if self.send_json_raises:
            raise RuntimeError( "client gone" )
        if self.fail_json_after is not None and self._json_calls > self.fail_json_after:
            raise RuntimeError( "client gone mid-handler" )
        self.json_sent.append( data )
    async def send_bytes( self, data ):
        self.bytes_sent.append( data )
    async def accept( self ):
        pass
    async def close( self ):
        self.closed = True


class _FakeElevenWs:
    """Async-CM + async-iterator stand-in for an ElevenLabs websocket connection."""
    def __init__( self, messages ):
        self._messages = messages
        self.sent : list = [ ]
    async def __aenter__( self ):
        return self
    async def __aexit__( self, *a ):
        return False
    async def send( self, data ):
        self.sent.append( data )
    async def __aiter__( self ):
        for m in self._messages:
            yield m


def _b64_audio( raw=b"pcm-bytes" ):
    return base64.b64encode( raw ).decode( "ascii" )


def _run( coro ):
    return asyncio.run( coro )


# ── _run_whisper_with_retry ─────────────────────────────────────────────────────


class TestRunWhisperWithRetry( unittest.TestCase ):

    def test_success_no_retry( self ):
        pipe = MagicMock( return_value="hello world" )
        self.assertEqual( _run_whisper_with_retry( pipe, "/tmp/x.wav", foo="bar" ), "hello world" )
        pipe.assert_called_once_with( "/tmp/x.wav", foo="bar" )

    def test_cuda_oom_then_retry_succeeds( self ):
        pipe = MagicMock( side_effect=[ torch_oom(), "recovered" ] )
        with patch.object( speech, "gc" ) as gc_mock, \
             patch.object( speech.torch.cuda, "empty_cache" ) as empty_mock:
            result = _run_whisper_with_retry( pipe, "/tmp/x.wav", debug=True )
        self.assertEqual( result, "recovered" )
        gc_mock.collect.assert_called_once()
        empty_mock.assert_called_once()
        self.assertEqual( pipe.call_count, 2 )


def torch_oom():
    """Build a torch.cuda.OutOfMemoryError instance (CPU-safe — no CUDA call)."""
    try:
        return speech.torch.cuda.OutOfMemoryError( "oom" )
    except Exception:  # pragma: no cover  # defensive: ctor signature drift across torch versions
        e = speech.torch.cuda.OutOfMemoryError
        return e()


# ── upload temp-file helpers (row 27bcdd79) ─────────────────────────────────────


# `<uid8>-<YYYYmmddTHHMMSS>-<random><suffix>` — the random part is mkstemp's.
_UPLOAD_NAME = re.compile( r"^(?P<uid8>[A-Za-z0-9_-]{1,8})-(?P<stamp>\d{8}T\d{6})-(?P<rand>[A-Za-z0-9_]+)(?P<suffix>\.[A-Za-z0-9]+)$" )


def _upload_dir( test ):
    """A real, empty directory removed when `test` ends."""
    d = tempfile.mkdtemp( prefix="stt-upload-test-" )
    test.addCleanup( shutil.rmtree, d, True )
    return d


class _RecordingProvider:
    """A provider that records the path it was given and what was on disk there.

    Reads the file at call time, so a test can tell "the provider saw this audio"
    from "the path was right but the file was already gone".
    """
    def __init__( self, text="transcribed", raises=None ):
        self.text    = text
        self.raises  = raises
        self.path    = None
        self.content = None
    def transcribe( self, path, **kwargs ):
        self.path = path
        with open( path, "rb" ) as f:
            self.content = f.read()
        if self.raises is not None:
            raise self.raises
        return self.text


class TestResolveSttUploadDir( unittest.TestCase ):

    def test_reads_the_key_and_strips_it( self ):
        cfg = MagicMock(); cfg.get.return_value = "  /tmp/elsewhere  "
        self.assertEqual( resolve_stt_upload_dir( cfg ), "/tmp/elsewhere" )
        cfg.get.assert_called_once_with( STT_UPLOAD_DIR_KEY, default=DEFAULT_STT_UPLOAD_DIR, silent=True )

    def test_the_key_is_the_one_the_ini_ships( self ):
        self.assertEqual( STT_UPLOAD_DIR_KEY, "speech upload temp dir" )
        self.assertEqual( DEFAULT_STT_UPLOAD_DIR, "/tmp/lupin-stt" )

    def test_missing_key_gets_the_declared_default( self ):
        """María's fix 2: a deployment without the key still gets a dedicated
        directory. The fake answers the way ConfigurationManager does for a missing
        key — it hands back the default it was given."""
        cfg = MagicMock(); cfg.get.side_effect = lambda key, default=None, silent=False: default
        self.assertEqual( resolve_stt_upload_dir( cfg ), "/tmp/lupin-stt" )

    def test_blank_or_none_gets_the_declared_default( self ):
        for value in ( "", "   ", None ):
            cfg = MagicMock(); cfg.get.return_value = value
            self.assertEqual( resolve_stt_upload_dir( cfg ), "/tmp/lupin-stt", repr( value ) )


class TestAudioSuffixFromFilename( unittest.TestCase ):

    def test_keeps_a_plain_extension( self ):
        self.assertEqual( audio_suffix_from_filename( "rec.wav", ".x" ), ".wav" )
        self.assertEqual( audio_suffix_from_filename( "clip.tar.ogg", ".x" ), ".ogg" )

    def test_anything_unusual_gets_the_fallback( self ):
        for name in ( None, "", "noext", "../../etc/passwd", "a.toolong", "a.w v", "a./x", ".hidden/" ):
            self.assertEqual( audio_suffix_from_filename( name, ".wav" ), ".wav", repr( name ) )


class TestSaveAudioUpload( unittest.TestCase ):

    def test_writes_the_content_under_the_upload_dir_with_the_documented_name( self ):
        d    = _upload_dir( self )
        path = save_audio_upload( b"abc123", "u1234567890", ".mp3", d )
        self.assertEqual( os.path.dirname( path ), d )
        m = _UPLOAD_NAME.match( os.path.basename( path ) )
        self.assertIsNotNone( m, os.path.basename( path ) )
        self.assertEqual( m.group( "uid8" ),   "u1234567" )
        self.assertEqual( m.group( "suffix" ), ".mp3" )
        datetime.strptime( m.group( "stamp" ), "%Y%m%dT%H%M%S" )
        with open( path, "rb" ) as f:
            self.assertEqual( f.read(), b"abc123" )

    def test_two_uploads_in_the_same_second_get_two_files( self ):
        """The defect this row exists for: one fixed path, so a second upload
        overwrote the first. The clock is pinned, so the random part alone has to
        keep them apart."""
        d     = _upload_dir( self )
        fixed = MagicMock(); fixed.now.return_value = datetime( 2026, 9, 11, 14, 0, 0 )
        with patch.object( speech, "datetime", fixed ):
            a = save_audio_upload( b"first",  "u1234567890", ".mp3", d )
            b = save_audio_upload( b"second", "u1234567890", ".mp3", d )
        self.assertNotEqual( a, b )
        self.assertIn( "-20260911T140000-", a )
        self.assertIn( "-20260911T140000-", b )
        with open( a, "rb" ) as f: self.assertEqual( f.read(), b"first" )
        with open( b, "rb" ) as f: self.assertEqual( f.read(), b"second" )

    def test_an_existing_name_is_never_reused( self ):
        """O_EXCL: when the candidate name already exists, the existing file is left
        alone and a different name is taken."""
        d     = _upload_dir( self )
        fixed = MagicMock(); fixed.now.return_value = datetime( 2026, 9, 11, 14, 0, 0 )
        taken = os.path.join( d, "u1234567-20260911T140000-same.mp3" )
        with open( taken, "wb" ) as f: f.write( b"someone else's audio" )
        with patch.object( speech, "datetime", fixed ), \
             patch.object( tempfile, "_get_candidate_names", return_value=iter( [ "same", "other" ] ) ):
            path = save_audio_upload( b"mine", "u1234567890", ".mp3", d )
        self.assertEqual( path, os.path.join( d, "u1234567-20260911T140000-other.mp3" ) )
        with open( taken, "rb" ) as f: self.assertEqual( f.read(), b"someone else's audio" )

    def test_no_user_is_anon( self ):
        path = save_audio_upload( b"x", None, ".wav", _upload_dir( self ) )
        self.assertTrue( os.path.basename( path ).startswith( "anon-" ), path )

    def test_hostile_user_id_characters_are_dropped( self ):
        d = _upload_dir( self )
        path = save_audio_upload( b"x", "../../e v/il@x.com", ".wav", d )
        self.assertEqual( os.path.dirname( path ), d )
        self.assertTrue( os.path.basename( path ).startswith( "evilxcom-" ), path )
        only_hostile = save_audio_upload( b"x", "../@@ /", ".wav", d )
        self.assertTrue( os.path.basename( only_hostile ).startswith( "anon-" ), only_hostile )

    def test_creates_a_missing_directory( self ):
        d = os.path.join( _upload_dir( self ), "not", "there", "yet" )
        path = save_audio_upload( b"x", "u1", ".wav", d )
        self.assertTrue( os.path.isfile( path ) )

    def test_a_failed_write_leaves_no_file_behind( self ):
        """María's fix 1: mkstemp has already created the file when the write
        fails, so without the unlink an empty file would outlive the request."""
        d = _upload_dir( self )

        class _FailingFile:
            def __init__( self, fd, mode ): self.fd = fd
            def __enter__( self ): return self
            def __exit__( self, *a ): os.close( self.fd ); return False
            def write( self, content ): raise OSError( 28, "No space left on device" )

        with patch.object( speech.os, "fdopen", _FailingFile ):
            with self.assertRaises( OSError ):
                save_audio_upload( b"x" * 10, "u1", ".wav", d )
        self.assertEqual( os.listdir( d ), [ ] )


class TestRemoveAudioUpload( unittest.TestCase ):

    def test_removes_the_file( self ):
        path = save_audio_upload( b"x", "u1", ".wav", _upload_dir( self ) )
        remove_audio_upload( path )
        self.assertFalse( os.path.exists( path ) )

    def test_none_and_already_gone_are_quiet( self ):
        remove_audio_upload( None )
        remove_audio_upload( os.path.join( _upload_dir( self ), "gone.wav" ) )

    def test_any_other_os_error_is_printed_not_raised( self ):
        """Cleanup runs in `finally`; a raise there would replace the request's own
        answer or error with a cleanup fault."""
        with patch.object( speech.os, "remove", side_effect=PermissionError( "nope" ) ), \
             patch( "builtins.print" ) as p:
            remove_audio_upload( "/tmp/lupin-stt/x.wav" )
        self.assertIn( "could not remove audio upload", p.call_args.args[ 0 ] )


# ── DI accessors ────────────────────────────────────────────────────────────────


class TestDependencyAccessors( unittest.TestCase ):

    def test_get_whisper_pipeline( self ):
        m = MagicMock()
        m.whisper_pipeline = "PIPE"
        with _patch_fastapi_main( m ):
            self.assertEqual( get_whisper_pipeline(), "PIPE" )

    def test_get_speech_provider( self ):
        m = MagicMock()
        m.app_debug   = True
        m.app_verbose = False
        with _patch_fastapi_main( m ), patch( f"{P}.SpeechToTextProvider" ) as Prov:
            Prov.return_value = "PROVIDER"
            self.assertEqual( get_speech_provider(), "PROVIDER" )
            Prov.assert_called_once_with( debug=True, verbose=False )

    def test_get_websocket_manager( self ):
        m = MagicMock(); m.websocket_manager = "WSM"
        with _patch_fastapi_main( m ):
            self.assertEqual( get_websocket_manager(), "WSM" )

    def test_get_config_manager( self ):
        m = MagicMock(); m.config_mgr = "CFG"
        with _patch_fastapi_main( m ):
            self.assertEqual( get_config_manager(), "CFG" )

    def test_get_active_tasks( self ):
        m = MagicMock(); m.active_tasks = { "a": 1 }
        with _patch_fastapi_main( m ):
            self.assertEqual( get_active_tasks(), { "a": 1 } )

    def test_get_ask_flow( self ):
        """Door 8: the router reads the FLOW off lupin_app.main, not the queue.

        `get_todo_queue` used to live here and went with door 8 — this module had
        exactly one queue caller and it hands its transcription to the flow now.
        """
        m = MagicMock(); m.ask_flow = "FLOW"
        with _patch_fastapi_main( m ):
            self.assertEqual( get_ask_flow(), "FLOW" )


# ── upload_and_transcribe_mp3_file ──────────────────────────────────────────────


class TestUploadAndTranscribeMp3( unittest.IsolatedAsyncioTestCase ):

    def _request( self ):
        req = MagicMock()
        req.body = AsyncMock( return_value=base64.b64encode( b"rawaudio" ) )
        req.client.host = "1.2.3.4"
        req.headers = { }
        return req

    def _main( self, debug=False, verbose=False ):
        m = MagicMock(); m.app_debug = debug; m.app_verbose = verbose
        return m

    _USER = { "uid": "u1234567890", "email": "t@t.com" }

    async def _call( self, *, munger, ask_flow=_SENTINEL, provider=None, main=None,
                     current_user=_SENTINEL, websocket_id=None ):
        self.provider   = provider or _RecordingProvider()
        self.upload_dir = _upload_dir( self )
        config_mgr      = MagicMock()
        config_mgr.get.return_value = self.upload_dir
        ask_flow        = MagicMock() if ask_flow is _SENTINEL else ask_flow
        user            = dict( self._USER ) if current_user is _SENTINEL else current_user
        main            = main or self._main( debug=True )
        with _patch_fastapi_main( main ), \
             patch.object( speech.du, "get_project_root", return_value="/root" ), \
             patch.object( speech.du, "write_string_to_file" ), \
             patch( f"{P}.mmm.MultiModalMunger", return_value=munger ), \
             patch( f"{P}.InputAndOutputTable" ) as Iot:
            self._iot = Iot
            return await upload_and_transcribe_mp3_file(
                request=self._request(), prefix="pfx", prompt_key="generic",
                prompt_verbose="verbose", websocket_id=websocket_id,
                whisper_pipeline=MagicMock(), provider=self.provider,
                config_mgr=config_mgr, ask_flow=ask_flow, current_user=user,
            )

    def _assert_upload_seen_then_removed( self, uid8 ):
        """The provider read the request's own audio from a file under the upload dir
        named for the user, and that file is gone now the request is over."""
        self.assertEqual( os.path.dirname( self.provider.path ), self.upload_dir )
        self.assertTrue( os.path.basename( self.provider.path ).startswith( f"{uid8}-" ), self.provider.path )
        self.assertEqual( self.provider.content, b"rawaudio" )
        self.assertEqual( os.listdir( self.upload_dir ), [ ] )

    def _agent_munger( self ):
        munger = MagicMock()
        munger.is_agent.return_value = True
        munger.transcription = "do a thing"
        munger.get_jsons.return_value = '{"ok": true}'
        return munger

    async def test_agent_path_asks_the_flow( self ):
        """Door 8: the spoken agent request goes to `ask`, and its result is the
        munger's result.

        A BARE QUESTION, so `ask` and not `submit`: nothing about a transcription has
        been decided, and submit would skip the routing it needs.
        """
        munger = self._agent_munger()
        flow   = MagicMock(); flow.ask.return_value = { "status": "waiting", "job_id": "j1" }
        resp   = await self._call( munger=munger, ask_flow=flow )
        flow.ask.assert_called_once()
        flow.submit.assert_not_called()
        kw = flow.ask.call_args.kwargs
        self.assertEqual( kw[ "question" ],   "do a thing" )
        self.assertEqual( kw[ "user_id" ],    "u1234567890" )
        self.assertEqual( kw[ "user_email" ], "t@t.com" )
        self.assertEqual( munger.results, { "status": "waiting", "job_id": "j1" } )
        self.assertEqual( resp.status_code, 200 )

    async def test_agent_path_derives_a_session_when_the_caller_sends_none( self ):
        """Neither browser caller sends a websocket id yet, so the session is derived
        from the user id — the same shape /api/v2/ask uses."""
        flow = MagicMock()
        await self._call( munger=self._agent_munger(), ask_flow=flow )
        kw = flow.ask.call_args.kwargs
        self.assertEqual( kw[ "session_id" ],   "mp3-u1234567" )
        self.assertEqual( kw[ "websocket_id" ], "mp3-u1234567" )

    async def test_agent_path_uses_the_session_the_caller_names( self ):
        """The query parameter is not decoration: a caller that names its session must
        get the answer's events on that channel, not on the derived one."""
        flow = MagicMock()
        await self._call( munger=self._agent_munger(), ask_flow=flow, websocket_id="ws-abc" )
        kw = flow.ask.call_args.kwargs
        self.assertEqual( kw[ "session_id" ],   "ws-abc" )
        self.assertEqual( kw[ "websocket_id" ], "ws-abc" )

    async def test_agent_path_without_a_user_is_401_and_never_asks( self ):
        """An ASK creates work, and work has an owner. Refuse by name.

        The assertion that matters is `flow.ask.assert_not_called()`: a 401 that still
        ran the request would have minted an ownerless row before answering.
        """
        flow = MagicMock()
        with self.assertRaises( HTTPException ) as ctx:
            await self._call( munger=self._agent_munger(), ask_flow=flow, current_user=None )
        self.assertEqual( ctx.exception.status_code, 401 )
        flow.ask.assert_not_called()

    async def test_agent_path_with_a_token_carrying_no_identity_is_401( self ):
        flow = MagicMock()
        with self.assertRaises( HTTPException ) as ctx:
            await self._call( munger=self._agent_munger(), ask_flow=flow,
                              current_user={ "uid": "", "email": "" } )
        self.assertEqual( ctx.exception.status_code, 401 )
        flow.ask.assert_not_called()

    async def test_the_401_is_not_swallowed_into_a_500( self ):
        """HTTPException is an Exception, and this handler has a catch-all that turns
        anything into a 500 saying post-processing failed. Without the re-raise, a
        caller that simply needs to send its token would be told the server broke."""
        with self.assertRaises( HTTPException ) as ctx:
            await self._call( munger=self._agent_munger(), current_user=None )
        self.assertEqual( ctx.exception.status_code, 401 )
        self.assertIn( "signed-in user", ctx.exception.detail )

    async def test_agent_path_without_a_flow_is_a_500_naming_the_stage( self ):
        """No flow is a wiring gap at boot, not a caller error — and there is no
        fallback to a direct queue push, which is the whole point of door 8."""
        with self.assertRaises( HTTPException ) as ctx:
            await self._call( munger=self._agent_munger(), ask_flow=None )
        self.assertEqual( ctx.exception.status_code, 500 )
        self.assertIn( "agent request", ctx.exception.detail )

    async def test_agent_path_debug_off( self ):
        # Agent path with app_debug False → covers the False arc of `if app_debug:`.
        resp = await self._call( munger=self._agent_munger(), main=self._main( debug=False ) )
        self.assertEqual( resp.status_code, 200 )

    async def test_non_agent_path_needs_no_user_at_all( self ):
        """Dictation, snapshot search and insert-at-cursor stay tokenless. This is the
        test that fails if someone "tidies" the 401 up to the route level."""
        munger = MagicMock()
        munger.is_agent.return_value = False
        munger.transcription = "plain text"
        munger.results = None
        munger.get_jsons.return_value = '{"ok": 3}'
        flow = MagicMock()
        resp = await self._call( munger=munger, ask_flow=flow, current_user=None )
        self.assertEqual( resp.status_code, 200 )
        flow.ask.assert_not_called()
        self._iot.return_value.insert_io_row.assert_called_once()

    async def test_non_agent_with_results( self ):
        munger = MagicMock()
        munger.is_agent.return_value = False
        munger.transcription = "plain text"
        munger.results = "special-result"
        munger.get_jsons.return_value = '{"ok": 1}'
        await self._call( munger=munger )
        # I/O table insert fired for non-agent request.
        self._iot.return_value.insert_io_row.assert_called_once()

    async def test_non_agent_without_results( self ):
        munger = MagicMock()
        munger.is_agent.return_value = False
        munger.transcription = "plain text"
        munger.results = None
        munger.get_jsons.return_value = '{"ok": 2}'
        await self._call( munger=munger, main=self._main( debug=False ) )
        self._iot.return_value.insert_io_row.assert_called_once()

    async def test_cuda_oom_returns_503( self ):
        provider = _RecordingProvider( raises=torch_oom() )
        munger = MagicMock()
        with self.assertRaises( HTTPException ) as ctx:
            await self._call( munger=munger, provider=provider )
        self.assertEqual( ctx.exception.status_code, 503 )
        self._assert_upload_seen_then_removed( "u1234567" )

    async def test_generic_error_returns_500( self ):
        provider = _RecordingProvider( raises=ValueError( "decode fail" ) )
        with self.assertRaises( HTTPException ) as ctx:
            await self._call( munger=MagicMock(), provider=provider )
        self.assertEqual( ctx.exception.status_code, 500 )
        self._assert_upload_seen_then_removed( "u1234567" )

    # ── the upload file (row 27bcdd79) ─────────────────────────────────────────

    async def test_success_transcribes_a_file_named_for_the_user_and_removes_it( self ):
        await self._call( munger=self._agent_munger() )
        self._assert_upload_seen_then_removed( "u1234567" )
        self.assertNotIn( "t@t.com", self.provider.path )
        self.assertNotIn( "recording.mp3", self.provider.path )
        self.assertTrue( self.provider.path.endswith( ".mp3" ) )

    async def test_the_401_still_removes_the_upload( self ):
        """The refusal comes AFTER transcription, so the file exists when it fires."""
        with self.assertRaises( HTTPException ):
            await self._call( munger=self._agent_munger(), current_user=None )
        self._assert_upload_seen_then_removed( "anon" )

    async def test_dictation_without_a_user_is_anon( self ):
        munger = MagicMock()
        munger.is_agent.return_value = False
        munger.results = None
        munger.get_jsons.return_value = '{"ok": 4}'
        await self._call( munger=munger, current_user=None )
        self._assert_upload_seen_then_removed( "anon" )

    async def test_two_requests_never_share_a_file( self ):
        """The defect itself: both requests used io/recording.mp3."""
        paths = [ ]
        for _ in range( 2 ):
            await self._call( munger=self._agent_munger() )
            paths.append( os.path.basename( self.provider.path ) )
        self.assertNotEqual( paths[ 0 ], paths[ 1 ] )


# ── get_tts_audio (OpenAI) ──────────────────────────────────────────────────────


class TestGetTtsAudio( unittest.IsolatedAsyncioTestCase ):

    def _request( self, data ):
        req = MagicMock()
        if isinstance( data, Exception ):
            req.json = AsyncMock( side_effect=data )
        else:
            req.json = AsyncMock( return_value=data )
        req.client.host = "h"
        req.headers = { }
        return req

    async def _call( self, data, *, ws_connected=True, debug=True, active_tasks=None ):
        ws = MagicMock()
        ws.is_connected.return_value = ws_connected
        ws.active_connections = { }
        main = MagicMock(); main.app_debug = debug; main.app_verbose = True
        active_tasks = active_tasks if active_tasks is not None else { }
        with _patch_fastapi_main( main ), \
             patch( f"{P}.stream_tts_hybrid", new=MagicMock( return_value="CORO" ) ), \
             patch.object( speech.asyncio, "create_task", return_value="TASK" ):
            return await get_tts_audio(
                request=self._request( data ), ws_manager=ws,
                active_tasks=active_tasks, current_user_id="u1",
            ), ws, active_tasks

    async def test_body_not_dict_400( self ):
        with self.assertRaises( HTTPException ) as c:
            await self._call( [ "list" ] )
        self.assertEqual( c.exception.status_code, 400 )

    async def test_missing_fields_400( self ):
        with self.assertRaises( HTTPException ) as c:
            await self._call( { "session_id": "", "text": "" } )
        self.assertEqual( c.exception.status_code, 400 )

    async def test_non_string_fields_400( self ):
        with self.assertRaises( HTTPException ) as c:
            await self._call( { "session_id": 1, "text": 2 } )
        self.assertEqual( c.exception.status_code, 400 )

    async def test_session_id_too_long_400( self ):
        with self.assertRaises( HTTPException ) as c:
            await self._call( { "session_id": "x" * 256, "text": "hi" } )
        self.assertEqual( c.exception.status_code, 400 )

    async def test_text_too_long_400( self ):
        with self.assertRaises( HTTPException ) as c:
            await self._call( { "session_id": "s", "text": "y" * 10001 } )
        self.assertEqual( c.exception.status_code, 400 )

    async def test_empty_after_strip_400( self ):
        with self.assertRaises( HTTPException ) as c:
            await self._call( { "session_id": "s", "text": "    " } )
        self.assertEqual( c.exception.status_code, 400 )

    async def test_not_connected_404_with_debug( self ):
        with self.assertRaises( HTTPException ) as c:
            await self._call( { "session_id": "s", "text": "hi" }, ws_connected=False, debug=True )
        self.assertEqual( c.exception.status_code, 404 )

    async def test_not_connected_404_debug_off( self ):
        # debug=False → covers the False arcs of the top debug print (412) and the
        # not-connected debug print (463).
        with self.assertRaises( HTTPException ) as c:
            await self._call( { "session_id": "s", "text": "hi" }, ws_connected=False, debug=False )
        self.assertEqual( c.exception.status_code, 404 )

    async def test_success_starts_task( self ):
        resp, ws, tasks = await self._call( { "session_id": "s", "text": "hi" } )
        self.assertEqual( resp.status_code, 200 )
        self.assertIn( "s", tasks )
        ws.register_session_user.assert_called_once_with( "s", "u1" )

    async def test_generic_error_500( self ):
        with self.assertRaises( HTTPException ) as c:
            await self._call( ValueError( "boom" ) )
        self.assertEqual( c.exception.status_code, 500 )


# ── get_tts_audio_elevenlabs ────────────────────────────────────────────────────


class TestGetTtsAudioElevenlabs( unittest.IsolatedAsyncioTestCase ):

    def _request( self, data ):
        req = MagicMock()
        req.json = AsyncMock( return_value=data )
        req.client.host = "h"; req.headers = { }
        return req

    async def _call( self, data, *, ws_connected=True, debug=True ):
        ws = MagicMock(); ws.is_connected.return_value = ws_connected; ws.active_connections = { }
        main = MagicMock(); main.app_debug = debug; main.app_verbose = True
        tasks = { }
        with _patch_fastapi_main( main ), \
             patch( f"{P}.stream_tts_elevenlabs", new=MagicMock( return_value="CORO" ) ), \
             patch.object( speech.asyncio, "create_task", return_value="TASK" ):
            return await get_tts_audio_elevenlabs(
                request=self._request( data ), ws_manager=ws, active_tasks=tasks,
                config_mgr=MagicMock(), current_user_id="u1",
            ), tasks

    def _ok( self, **over ):
        base = { "session_id": "s", "text": "hello there" }
        base.update( over )
        return base

    async def test_not_dict_400( self ):
        with self.assertRaises( HTTPException ) as c:
            await self._call( "string-body" )
        self.assertEqual( c.exception.status_code, 400 )

    async def test_missing_400( self ):
        with self.assertRaises( HTTPException ) as c:
            await self._call( { "session_id": "", "text": "" } )
        self.assertEqual( c.exception.status_code, 400 )

    async def test_non_string_400( self ):
        with self.assertRaises( HTTPException ) as c:
            await self._call( { "session_id": 1, "text": 2 } )
        self.assertEqual( c.exception.status_code, 400 )

    async def test_session_too_long_400( self ):
        with self.assertRaises( HTTPException ) as c:
            await self._call( self._ok( session_id="x" * 256 ) )
        self.assertEqual( c.exception.status_code, 400 )

    async def test_text_too_long_400( self ):
        with self.assertRaises( HTTPException ) as c:
            await self._call( self._ok( text="y" * 10001 ) )
        self.assertEqual( c.exception.status_code, 400 )

    async def test_stability_out_of_range_400( self ):
        with self.assertRaises( HTTPException ) as c:
            await self._call( self._ok( stability=2.0 ) )
        self.assertEqual( c.exception.status_code, 400 )

    async def test_similarity_out_of_range_400( self ):
        with self.assertRaises( HTTPException ) as c:
            await self._call( self._ok( similarity_boost=-0.1 ) )
        self.assertEqual( c.exception.status_code, 400 )

    async def test_speed_out_of_range_400( self ):
        with self.assertRaises( HTTPException ) as c:
            await self._call( self._ok( speed=9.0 ) )
        self.assertEqual( c.exception.status_code, 400 )

    async def test_empty_after_strip_400( self ):
        with self.assertRaises( HTTPException ) as c:
            await self._call( self._ok( text="   " ) )
        self.assertEqual( c.exception.status_code, 400 )

    async def test_not_connected_404( self ):
        with self.assertRaises( HTTPException ) as c:
            await self._call( self._ok(), ws_connected=False )
        self.assertEqual( c.exception.status_code, 404 )

    async def test_not_connected_404_debug_off( self ):
        # debug=False → covers the False arc of the not-connected debug print (617).
        with self.assertRaises( HTTPException ) as c:
            await self._call( self._ok(), ws_connected=False, debug=False )
        self.assertEqual( c.exception.status_code, 404 )

    async def test_success_with_debug_simulate_flag( self ):
        resp, tasks = await self._call( self._ok( debug_simulate_error=True, voice_id="V" ) )
        self.assertEqual( resp.status_code, 200 )
        self.assertIn( "s", tasks )

    async def test_generic_error_500( self ):
        ws = MagicMock(); ws.register_session_user.side_effect = RuntimeError( "boom" )
        ws.is_connected.return_value = True; ws.active_connections = { }
        main = MagicMock(); main.app_debug = False; main.app_verbose = False
        with _patch_fastapi_main( main ), \
             patch( f"{P}.stream_tts_elevenlabs", new=MagicMock( return_value="CORO" ) ), \
             patch.object( speech.asyncio, "create_task", return_value="TASK" ):
            with self.assertRaises( HTTPException ) as c:
                await get_tts_audio_elevenlabs(
                    request=self._request( self._ok() ), ws_manager=ws, active_tasks={ },
                    config_mgr=MagicMock(), current_user_id="u1",
                )
        self.assertEqual( c.exception.status_code, 500 )


# ── upload_and_transcribe_wav_file ──────────────────────────────────────────────


class TestUploadAndTranscribeWav( unittest.IsolatedAsyncioTestCase ):

    def _file( self, read_side=b"wavbytes" ):
        f = MagicMock()
        f.filename = "rec.wav"
        if isinstance( read_side, Exception ):
            f.read = AsyncMock( side_effect=read_side )
        else:
            f.read = AsyncMock( return_value=read_side )
        return f

    _USER = { "uid": "w9876543210", "email": "t@t.com" }

    async def _call( self, *, file=None, provider=None, debug=True, current_user=_SENTINEL ):
        file            = file or self._file()
        self.provider   = provider or _RecordingProvider( text="  wav text  " )
        self.upload_dir = _upload_dir( self )
        config_mgr      = MagicMock()
        config_mgr.get.return_value = self.upload_dir
        user            = dict( self._USER ) if current_user is _SENTINEL else current_user
        main = MagicMock(); main.app_debug = debug; main.app_verbose = True
        with _patch_fastapi_main( main ), \
             patch( f"{P}.InputAndOutputTable" ):
            return await upload_and_transcribe_wav_file(
                file=file, prefix=None, whisper_pipeline=MagicMock(), provider=self.provider,
                config_mgr=config_mgr, current_user=user,
            )

    def _assert_upload_seen_then_removed( self, uid8, suffix=".wav" ):
        self.assertEqual( os.path.dirname( self.provider.path ), self.upload_dir )
        self.assertTrue( os.path.basename( self.provider.path ).startswith( f"{uid8}-" ), self.provider.path )
        self.assertTrue( self.provider.path.endswith( suffix ), self.provider.path )
        self.assertEqual( self.provider.content, b"wavbytes" )
        self.assertEqual( os.listdir( self.upload_dir ), [ ] )

    async def test_success_returns_text_and_cleans_up( self ):
        result = await self._call( provider=_RecordingProvider( text="  hello wav " ) )
        self.assertEqual( result, "hello wav" )
        self._assert_upload_seen_then_removed( "w9876543" )
        self.assertNotIn( "t@t.com", self.provider.path )

    async def test_success_debug_off( self ):
        # app_debug False → covers the False arcs of the two `if app_debug:` prints.
        result = await self._call( provider=_RecordingProvider( text="quiet wav" ), debug=False )
        self.assertEqual( result, "quiet wav" )
        self._assert_upload_seen_then_removed( "w9876543" )

    async def test_oom_503_with_cleanup( self ):
        with self.assertRaises( HTTPException ) as c:
            await self._call( provider=_RecordingProvider( raises=torch_oom() ) )
        self.assertEqual( c.exception.status_code, 503 )
        self._assert_upload_seen_then_removed( "w9876543" )

    async def test_generic_500_with_cleanup( self ):
        with self.assertRaises( HTTPException ) as c:
            await self._call( provider=_RecordingProvider( raises=ValueError( "bad" ) ) )
        self.assertEqual( c.exception.status_code, 500 )
        self._assert_upload_seen_then_removed( "w9876543" )

    async def test_generic_500_before_anything_was_saved( self ):
        # file.read() raises before the upload is written → nothing to remove, and
        # the cleanup must not turn that into a different error.
        with self.assertRaises( HTTPException ) as c:
            await self._call( file=self._file( read_side=ValueError( "early" ) ) )
        self.assertEqual( c.exception.status_code, 500 )
        self.assertIn( "early", c.exception.detail )
        self.assertIsNone( self.provider.path )
        self.assertEqual( os.listdir( self.upload_dir ), [ ] )

    async def test_the_client_filename_never_reaches_the_path( self ):
        """The old helper built `/tmp/<uuid>-<file.filename>`: a `../` in the client's
        filename was part of the path. Now only a vetted extension survives."""
        f = self._file(); f.filename = "../../../var/lupin/src/conf/lupin-app"
        await self._call( file=f, current_user=None )
        self.assertNotIn( "..", self.provider.path )
        self.assertNotIn( "lupin-app", self.provider.path )
        self._assert_upload_seen_then_removed( "anon", suffix=".wav" )

    async def test_a_traversal_filename_contributes_its_extension_only( self ):
        f = self._file(); f.filename = "../../../var/lupin/src/conf/lupin-app.ini"
        await self._call( file=f )
        self.assertNotIn( "..", self.provider.path )
        self.assertNotIn( "lupin-app", self.provider.path )
        self._assert_upload_seen_then_removed( "w9876543", suffix=".ini" )

    async def test_a_plain_client_extension_is_kept( self ):
        f = self._file(); f.filename = "clip.ogg"
        await self._call( file=f )
        self._assert_upload_seen_then_removed( "w9876543", suffix=".ogg" )


# ── stream_tts_hybrid (OpenAI) ──────────────────────────────────────────────────


class _SyncCM:
    def __init__( self, response ): self._r = response
    def __enter__( self ): return self._r
    def __exit__( self, *a ): return False


class TestStreamTtsHybrid( unittest.IsolatedAsyncioTestCase ):

    def _wsm( self, ws, connected=True ):
        wsm = MagicMock()
        wsm.active_connections = { "s": ws } if ws is not None else { }
        wsm.is_connected.return_value = connected
        return wsm

    async def test_no_websocket_returns_early( self ):
        wsm = self._wsm( None )
        await stream_tts_hybrid( "s", "hi", wsm )  # returns immediately, no raise

    async def test_success_streams_chunks( self ):
        ws = _FakeClientWs()
        wsm = self._wsm( ws, connected=True )
        response = MagicMock()
        response.iter_bytes.return_value = [ b"a", b"b", b"c" ]
        client = MagicMock()
        client.audio.speech.with_streaming_response.create.return_value = _SyncCM( response )
        with patch( f"{P}.OpenAI", return_value=client ), \
             patch.object( speech.du, "get_api_key", return_value="KEY" ):
            await stream_tts_hybrid( "s", "hi", wsm )
        self.assertEqual( len( ws.bytes_sent ), 3 )
        self.assertTrue( any( m.get( "type" ) == "audio_streaming_complete" for m in ws.json_sent ) )

    async def test_connection_lost_mid_stream( self ):
        ws = _FakeClientWs()
        wsm = MagicMock()
        wsm.active_connections = { "s": ws }
        wsm.is_connected.side_effect = [ False ]  # lost on first chunk check
        response = MagicMock(); response.iter_bytes.return_value = [ b"a", b"b" ]
        client = MagicMock()
        client.audio.speech.with_streaming_response.create.return_value = _SyncCM( response )
        with patch( f"{P}.OpenAI", return_value=client ), \
             patch.object( speech.du, "get_api_key", return_value="KEY" ):
            await stream_tts_hybrid( "s", "hi", wsm )
        self.assertEqual( ws.bytes_sent, [ ] )

    async def test_openai_api_error_sends_error( self ):
        ws = _FakeClientWs()
        wsm = self._wsm( ws )
        client = MagicMock()
        client.audio.speech.with_streaming_response.create.side_effect = RuntimeError( "api down" )
        with patch( f"{P}.OpenAI", return_value=client ), \
             patch.object( speech.du, "get_api_key", return_value="KEY" ):
            await stream_tts_hybrid( "s", "hi", wsm )
        self.assertTrue( any( m.get( "type" ) == "error" for m in ws.json_sent ) )

    async def test_general_error_sends_error( self ):
        ws = _FakeClientWs()
        wsm = self._wsm( ws )
        # du.get_api_key raises → general (outer) except.
        with patch.object( speech.du, "get_api_key", side_effect=RuntimeError( "no key" ) ):
            await stream_tts_hybrid( "s", "hi", wsm )
        self.assertTrue( any( m.get( "type" ) == "error" for m in ws.json_sent ) )

    async def test_general_error_send_json_also_fails_swallowed( self ):
        ws = _FakeClientWs()
        ws.send_json_raises = True
        wsm = self._wsm( ws )
        with patch.object( speech.du, "get_api_key", side_effect=RuntimeError( "no key" ) ):
            await stream_tts_hybrid( "s", "hi", wsm )  # nested except: pass — no raise


# ── stream_tts_elevenlabs ───────────────────────────────────────────────────────


class TestStreamTtsElevenlabs( unittest.IsolatedAsyncioTestCase ):

    def _wsm( self, ws, connected=True ):
        wsm = MagicMock()
        wsm.active_connections = { "s": ws } if ws is not None else { }
        wsm.is_connected.return_value = connected
        return wsm

    def _config( self ):
        cfg = MagicMock()
        cfg.get.side_effect = lambda key, default=None, **kw: default
        return cfg

    async def _run_with_messages( self, messages, *, ws=None, wsm=None, config_mgr=None,
                                  voice_id="V", verbose=True, connect=None, **kw ):
        ws  = ws or _FakeClientWs()
        wsm = wsm or self._wsm( ws )
        connect = connect or AsyncMock( return_value=_FakeElevenWs( messages ) )
        main = MagicMock(); main.app_verbose = verbose
        with _patch_fastapi_main( main ), \
             patch.object( speech, "websockets", _fake_ws_module( connect ) ), \
             patch.object( speech.du, "get_api_key", return_value="KEY" ), \
             patch.object( speech.du, "print_banner" ):
            await stream_tts_elevenlabs( "s", "hi", wsm, voice_id=voice_id,
                                         config_mgr=config_mgr, **kw )
        return ws

    async def test_no_websocket_returns_early( self ):
        await stream_tts_elevenlabs( "s", "hi", self._wsm( None ) )

    async def test_success_audio_and_final( self ):
        msgs = [
            json.dumps( { "audio": _b64_audio() } ),
            json.dumps( { "audio": _b64_audio( b"more" ) } ),
            json.dumps( { "normalizedAlignment": { "x": 1 } } ),  # non-audio passthrough
            json.dumps( { "isFinal": True } ),
        ]
        ws = await self._run_with_messages( msgs, config_mgr=self._config() )
        self.assertEqual( len( ws.bytes_sent ), 2 )
        self.assertTrue( any( m.get( "type" ) == "audio_streaming_complete" for m in ws.json_sent ) )

    async def test_audio_only_natural_exhaustion_many_chunks( self ):
        # 4 audio chunks, NO isFinal → loop exhausts naturally (1045->1114 completion)
        # and chunk #4 takes the `chunk_count <= 3` False arc (1066->1045).
        msgs = [ json.dumps( { "audio": _b64_audio( bytes([ i ]) ) } ) for i in range( 4 ) ]
        ws = await self._run_with_messages( msgs, config_mgr=self._config() )
        self.assertEqual( len( ws.bytes_sent ), 4 )
        self.assertTrue( any( m.get( "type" ) == "audio_streaming_complete" for m in ws.json_sent ) )

    async def test_verbose_false_branch( self ):
        msgs = [ json.dumps( { "isFinal": True } ) ]
        await self._run_with_messages( msgs, verbose=False, config_mgr=self._config() )

    async def test_voice_id_none_with_config_default( self ):
        cfg = MagicMock()
        cfg.get.side_effect = lambda key, default=None, **kw: "DEFAULTVOICE" if "default voice" in key else default
        msgs = [ json.dumps( { "isFinal": True } ) ]
        await self._run_with_messages( msgs, voice_id=None, config_mgr=cfg )

    async def test_voice_id_none_no_config_last_resort( self ):
        msgs = [ json.dumps( { "isFinal": True } ) ]
        await self._run_with_messages( msgs, voice_id=None, config_mgr=None )

    async def test_custom_profile_skips_profile_load( self ):
        msgs = [ json.dumps( { "isFinal": True } ) ]
        await self._run_with_messages( msgs, config_mgr=self._config(), quality_profile="custom" )

    async def test_api_key_missing_raises_into_generic( self ):
        ws = _FakeClientWs()
        wsm = self._wsm( ws )
        main = MagicMock(); main.app_verbose = False
        with _patch_fastapi_main( main ), \
             patch.object( speech, "websockets", _fake_ws_module( AsyncMock() ) ), \
             patch.object( speech.du, "get_api_key", return_value="" ):
            await stream_tts_elevenlabs( "s", "hi", wsm, voice_id="V", config_mgr=None )
        self.assertTrue( any( m.get( "type" ) == "error" for m in ws.json_sent ) )

    async def test_error_message_quota_exceeded( self ):
        msgs = [ json.dumps( { "error": "quota_exceeded: out of credits" } ) ]
        ws = await self._run_with_messages( msgs, config_mgr=self._config() )
        errs = [ m for m in ws.json_sent if m.get( "type" ) == "tts_error" ]
        self.assertEqual( errs[ 0 ][ "error_code" ], "quota_exceeded" )

    async def test_error_message_rate_limit( self ):
        msgs = [ json.dumps( { "error": "rate_limit hit" } ) ]
        ws = await self._run_with_messages( msgs, config_mgr=self._config() )
        self.assertTrue( any( m.get( "error_code" ) == "rate_limit" for m in ws.json_sent ) )

    async def test_error_message_auth( self ):
        msgs = [ json.dumps( { "error": "unauthorized request" } ) ]
        ws = await self._run_with_messages( msgs, config_mgr=self._config() )
        self.assertTrue( any( m.get( "error_code" ) == "auth_error" for m in ws.json_sent ) )

    async def test_error_message_unknown( self ):
        msgs = [ json.dumps( { "error": "something weird" } ) ]
        ws = await self._run_with_messages( msgs, config_mgr=self._config() )
        self.assertTrue( any( m.get( "error_code" ) == "unknown" for m in ws.json_sent ) )

    async def test_json_decode_error_continues( self ):
        msgs = [ "not-json-at-all", json.dumps( { "isFinal": True } ) ]
        ws = await self._run_with_messages( msgs, config_mgr=self._config() )
        self.assertTrue( any( m.get( "type" ) == "audio_streaming_complete" for m in ws.json_sent ) )

    async def test_client_connection_lost_breaks( self ):
        ws = _FakeClientWs()
        wsm = MagicMock(); wsm.active_connections = { "s": ws }
        wsm.is_connected.return_value = False  # lost at first loop iteration
        msgs = [ json.dumps( { "audio": _b64_audio() } ) ]
        await self._run_with_messages( msgs, ws=ws, wsm=wsm, config_mgr=self._config() )
        self.assertEqual( ws.bytes_sent, [ ] )

    async def test_connection_closed_arm( self ):
        ws = _FakeClientWs()
        wsm = self._wsm( ws )
        connect = AsyncMock( side_effect=_ConnClosed( "closed" ) )
        await self._run_with_messages( [ ], ws=ws, wsm=wsm, config_mgr=self._config(), connect=connect )
        self.assertTrue( any( m.get( "type" ) == "error" for m in ws.json_sent ) )

    async def test_connection_closed_send_also_fails_swallowed( self ):
        # First (status) send succeeds; connect raises ConnectionClosed; the handler's
        # send_json then fails → covers the ConnectionClosed handler's `except: pass`.
        ws = _FakeClientWs(); ws.fail_json_after = 1
        wsm = self._wsm( ws )
        connect = AsyncMock( side_effect=_ConnClosed( "closed" ) )
        await self._run_with_messages( [ ], ws=ws, wsm=wsm, config_mgr=self._config(), connect=connect )

    async def test_generic_exception_arm( self ):
        ws = _FakeClientWs()
        wsm = self._wsm( ws )
        connect = AsyncMock( side_effect=RuntimeError( "kaboom" ) )
        await self._run_with_messages( [ ], ws=ws, wsm=wsm, config_mgr=self._config(), connect=connect )
        self.assertTrue( any( m.get( "type" ) == "error" for m in ws.json_sent ) )

    async def test_generic_exception_send_also_fails_swallowed( self ):
        ws = _FakeClientWs(); ws.send_json_raises = True
        wsm = self._wsm( ws )
        connect = AsyncMock( side_effect=RuntimeError( "kaboom" ) )
        await self._run_with_messages( [ ], ws=ws, wsm=wsm, config_mgr=self._config(), connect=connect )


# ── stream_tts_elevenlabs debug_simulate_error path ─────────────────────────────
#
# Was a PROD-BUG tripwire (xfail-strict + pin): stream_tts_elevenlabs referenced an
# undefined `app_debug` at L960, dead-coding the quota simulation. Fix landed
# (`app_debug = main_module.app_debug` bound next to `app_verbose`, authorized by
# Tiberius 2026-06-01, flagged for Rick's ratification) — these are now REAL
# assertions covering the (formerly dead) simulation block.


class TestStreamTtsElevenlabsDebugSimulateError( unittest.TestCase ):
    """debug_simulate_error=True sends the simulated quota `tts_error` (post app_debug fix)."""

    def _run( self, app_debug ):
        ws  = _FakeClientWs()
        wsm = MagicMock(); wsm.active_connections = { "s": ws }; wsm.is_connected.return_value = True
        main = MagicMock(); main.app_debug = app_debug; main.app_verbose = True
        with _patch_fastapi_main( main ), \
             patch.object( speech, "websockets", _fake_ws_module( AsyncMock() ) ), \
             patch.object( speech.du, "get_api_key", return_value="KEY" ), \
             patch.object( speech.du, "print_banner" ), \
             patch.object( speech.asyncio, "sleep", new=AsyncMock() ):
            asyncio.run( stream_tts_elevenlabs(
                "s", "hi", wsm, voice_id="V", config_mgr=None, debug_simulate_error=True,
            ) )
        return ws.json_sent

    def test_debug_on_sends_simulated_tts_error( self ):
        # app_debug True + app_verbose True → covers the L960 debug-print True arc;
        # the simulation sends the "Connecting..." status then a quota tts_error.
        sent = self._run( app_debug=True )
        self.assertTrue( any( m.get( "type" ) == "audio_streaming_status" for m in sent ) )
        self.assertTrue( any( m.get( "type" ) == "tts_error" for m in sent ) )

    def test_debug_off_still_sends_simulated_tts_error( self ):
        # app_debug False → covers the L960 debug-print False arc; simulation still fires.
        sent = self._run( app_debug=False )
        self.assertTrue( any( m.get( "type" ) == "tts_error" for m in sent ) )


# ── websocket_pcm_tts_endpoint ──────────────────────────────────────────────────


class TestWebsocketPcmTtsEndpoint( unittest.IsolatedAsyncioTestCase ):

    async def _run( self, *, api_key="KEY", messages=None, connect=None ):
        ws = _FakeClientWs()
        messages = messages if messages is not None else [ json.dumps( { "isFinal": True } ) ]
        connect = connect or AsyncMock( return_value=_FakeElevenWs( messages ) )
        with patch.object( speech, "websockets", _fake_ws_module( connect ) ), \
             patch.object( speech.du, "get_api_key", return_value=api_key ):
            await websocket_pcm_tts_endpoint( websocket=ws, model_id="m", voice_id="v" )
        return ws

    async def test_api_key_missing_closes( self ):
        ws = await self._run( api_key="" )
        self.assertTrue( ws.closed )
        self.assertTrue( any( m.get( "type" ) == "error" for m in ws.json_sent ) )

    async def test_success_audio_and_final_and_complete( self ):
        msgs = [
            json.dumps( { "audio": _b64_audio() } ),
            json.dumps( { "audio": _b64_audio( b"two" ) } ),
            json.dumps( { "isFinal": True } ),
        ]
        ws = await self._run( messages=msgs )
        self.assertEqual( len( ws.bytes_sent ), 2 )
        self.assertTrue( any( m.get( "type" ) == "complete" for m in ws.json_sent ) )

    async def test_audio_only_natural_exhaustion_many_chunks( self ):
        # 6 audio chunks + a no-key passthrough message, NO isFinal → loop exhausts
        # naturally (1254->1287 completion), chunk #6 takes the `chunk_count <= 5`
        # False arc (1267->1254), and the passthrough message takes 1274->1254.
        msgs  = [ json.dumps( { "audio": _b64_audio( bytes([ i ]) ) } ) for i in range( 6 ) ]
        msgs += [ json.dumps( { "normalizedAlignment": { "x": 1 } } ) ]
        ws = await self._run( messages=msgs )
        self.assertEqual( len( ws.bytes_sent ), 6 )
        self.assertTrue( any( m.get( "type" ) == "complete" for m in ws.json_sent ) )

    async def test_elevenlabs_error_message( self ):
        msgs = [ json.dumps( { "error": "boom" } ) ]
        ws = await self._run( messages=msgs )
        self.assertTrue( any( m.get( "type" ) == "error" for m in ws.json_sent ) )

    async def test_json_decode_error_handled( self ):
        msgs = [ "garbage", json.dumps( { "isFinal": True } ) ]
        ws = await self._run( messages=msgs )
        self.assertTrue( any( m.get( "type" ) == "complete" for m in ws.json_sent ) )

    async def test_websocket_exception_arm( self ):
        connect = AsyncMock( side_effect=_WsExc( "ws fail" ) )
        ws = await self._run( connect=connect )
        self.assertTrue( any( m.get( "type" ) == "error" for m in ws.json_sent ) )

    async def test_websocket_exception_send_also_fails_swallowed( self ):
        ws = _FakeClientWs(); ws.send_json_raises = True
        connect = AsyncMock( side_effect=_WsExc( "ws fail" ) )
        with patch.object( speech, "websockets", _fake_ws_module( connect ) ), \
             patch.object( speech.du, "get_api_key", return_value="KEY" ):
            await websocket_pcm_tts_endpoint( websocket=ws, model_id="m", voice_id="v" )

    async def test_generic_exception_arm( self ):
        connect = AsyncMock( side_effect=RuntimeError( "kaboom" ) )
        ws = await self._run( connect=connect )
        self.assertTrue( any( m.get( "type" ) == "error" for m in ws.json_sent ) )

    async def test_generic_exception_send_also_fails_swallowed( self ):
        ws = _FakeClientWs(); ws.send_json_raises = True
        connect = AsyncMock( side_effect=RuntimeError( "kaboom" ) )
        with patch.object( speech, "websockets", _fake_ws_module( connect ) ), \
             patch.object( speech.du, "get_api_key", return_value="KEY" ):
            await websocket_pcm_tts_endpoint( websocket=ws, model_id="m", voice_id="v" )


if __name__ == "__main__":
    unittest.main()
