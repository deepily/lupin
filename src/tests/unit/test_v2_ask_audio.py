#!/usr/bin/env python3
"""
Unit tests for POST /api/v2/ask-audio — the spoken-ask door (routers/v2_ask.py).

Plan: lupin-mobile src/rnd/2026.09.11-spoken-ask-streamed-door-implementation-plan.md, §2.4.

Hermetic: the router is mounted on a bare FastAPI app and every dependency — identity, the
flow, the speech provider, the whisper pipeline and the config manager — is overridden, so no
auth backend, no transcriber and no AskFlow stack are touched. The D4 arms call the handler
directly, so they can hold the response without iterating it. :7999-eligible.
"""

import asyncio
import gc
import io
import json
import os
import re
import threading
import types

import pytest
import torch
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.datastructures import UploadFile

import cosa.utils.util as cu
from cosa.rest.routers import speech, v2_ask


FIXTURE_PATH  = os.path.join( cu.get_project_root(), "src", "tests", "fixtures", "ask_audio_ndjson_contract.json" )
USER          = { "uid": "u1234567890", "email": "u@x.com" }
UPLOAD_BYTES  = 249000
TRANSCRIPT    = "what's the weather in Boston"


# ────────────────────────────────────────────────────────────── fakes

def _fixture():
    with open( FIXTURE_PATH ) as f: return json.load( f )


def _fixture_result():
    """The AskResponse the fixture's line 2 carries — what FakeFlow returns for the byte test."""
    return json.loads( _fixture()[ "body" ].split( "\n" )[ 1 ] )[ "result" ]


def _result( **overrides ):
    base = _fixture_result()
    base.update( overrides )
    return base


class FakeFlow:
    """Records each ask; can block until released, or raise."""

    def __init__( self, result=None, raises=None, gate=None ):
        self.result    = result if result is not None else _result()
        self.raises    = raises
        self.gate      = gate
        self.asked     = threading.Event()
        self.finished  = threading.Event()
        self.ask_calls = []

    def ask( self, **kwargs ):
        self.ask_calls.append( kwargs )
        self.asked.set()
        if self.gate is not None: self.gate.wait( 5 )
        try:
            if self.raises is not None: raise self.raises
            return self.result
        finally:
            self.finished.set()


class FakeProvider:
    def __init__( self, text=TRANSCRIPT, raises=None ):
        self.text   = text
        self.raises = raises
        self.paths  = []

    def transcribe( self, path, whisper_pipeline=None ):
        self.paths.append( path )
        assert os.path.exists( path ), "transcribe must be handed a file that exists"
        if self.raises is not None: raise self.raises
        return self.text


class FakeConfig:
    def __init__( self, upload_dir ):
        self.upload_dir = upload_dir

    def get( self, key, default=None, silent=False, **kwargs ):
        return self.upload_dir if key == speech.STT_UPLOAD_DIR_KEY else default


@pytest.fixture
def io_rows( monkeypatch ):
    """speech.insert_stt_io_row is the seam F5 moved; record instead of writing a table."""
    rows = []
    monkeypatch.setattr( speech, "insert_stt_io_row", lambda **kw: rows.append( kw ) )
    return rows


def _app( flow, provider, upload_dir, user=USER ):
    app = FastAPI()
    app.include_router( v2_ask.router )
    app.dependency_overrides[ v2_ask.get_current_user ]         = lambda: user
    app.dependency_overrides[ v2_ask.get_ask_flow ]             = lambda: flow
    app.dependency_overrides[ speech.get_speech_provider ]      = lambda: provider
    app.dependency_overrides[ speech.get_whisper_pipeline ]     = lambda: None
    app.dependency_overrides[ speech.get_config_manager ]       = lambda: FakeConfig( upload_dir )
    return app


def _post( client, filename="question.wav", content=b"\0" * UPLOAD_BYTES, params=None ):
    return client.post( "/api/v2/ask-audio", params=params or {}, files={ "file": ( filename, content, "audio/wav" ) } )


def _upload( filename="question.wav", content=b"\0" * UPLOAD_BYTES ):
    return UploadFile( file=io.BytesIO( content ), filename=filename )


async def _call( flow, provider, upload_dir, **kwargs ):
    """Call the handler directly, as FastAPI would after resolving its dependencies."""
    return await v2_ask.ask_audio(
        file=kwargs.get( "file", _upload() ), websocket_id=kwargs.get( "websocket_id" ), speak=True,
        interactive=True, current_user=USER, flow=flow, provider=provider, whisper_pipeline=None,
        config_mgr=FakeConfig( upload_dir ) )


def _pin_stt_ms( monkeypatch, span_seconds=0.2714 ):
    """trace.stt_ms is a perf_counter span; pin it so the body is byte-comparable."""
    # Replace the module's `time` name, not time.perf_counter itself: the server stack under
    # TestClient calls the real perf_counter too, and a global patch would starve it.
    ticks = iter( [ 100.0, 100.0 + span_seconds ] )
    monkeypatch.setattr( v2_ask, "time", types.SimpleNamespace( perf_counter=lambda: next( ticks ) ) )


# ────────────────────────────────────────────────────────────── the contract

def test_body_is_byte_identical_to_the_contract_fixture( tmp_path, monkeypatch, io_rows ):
    """The fixture is HAND-AUTHORED (S-D3); the handler has to match it, never the reverse."""
    _pin_stt_ms( monkeypatch )
    flow   = FakeFlow()
    client = TestClient( _app( flow, FakeProvider(), str( tmp_path ) ) )
    resp   = _post( client )
    assert resp.status_code == 200
    assert resp.headers[ "content-type" ].startswith( "application/x-ndjson" )
    assert resp.text == _fixture()[ "body" ]


def test_body_is_two_lines_transcript_then_ask( tmp_path, io_rows ):
    client = TestClient( _app( FakeFlow(), FakeProvider(), str( tmp_path ) ) )
    lines  = _post( client ).text.split( "\n" )
    assert lines[ 2 ] == "" and len( lines ) == 3
    first, second = json.loads( lines[ 0 ] ), json.loads( lines[ 1 ] )
    assert first[ "type" ] == "transcript" and first[ "transcription" ] == TRANSCRIPT
    assert first[ "trace" ][ "upload_bytes" ] == UPLOAD_BYTES
    assert isinstance( first[ "trace" ][ "stt_ms" ], float )
    assert second[ "type" ] == "ask"


def test_line_two_is_the_full_askresponse_in_model_order_even_when_the_flow_omits_fields( tmp_path, io_rows ):
    """A flow result missing defaulted fields still goes out as the whole AskResponse."""
    partial = { k: v for k, v in _result().items() if k not in ( "replayed_snapshot_id", "error", "similarity" ) }
    client  = TestClient( _app( FakeFlow( result=partial ), FakeProvider(), str( tmp_path ) ) )
    result  = json.loads( _post( client ).text.split( "\n" )[ 1 ] )[ "result" ]
    assert list( result ) == list( v2_ask.AskResponse.model_fields )
    assert result[ "replayed_snapshot_id" ] is None


def test_flow_is_asked_with_the_transcript_and_the_token_identity( tmp_path, io_rows ):
    flow   = FakeFlow()
    client = TestClient( _app( flow, FakeProvider(), str( tmp_path ) ) )
    _post( client, params={ "websocket_id": "wise penguin", "speak": "false", "interactive": "false" } )
    assert flow.ask_calls == [ { "question": TRANSCRIPT, "user_id": USER[ "uid" ], "user_email": USER[ "email" ],
                                 "session_id": "wise penguin", "websocket_id": "wise penguin",
                                 "speak": False, "interactive": False } ]


def test_session_falls_back_to_api_uid8_without_a_websocket_id( tmp_path, io_rows ):
    flow   = FakeFlow()
    client = TestClient( _app( flow, FakeProvider(), str( tmp_path ) ) )
    _post( client )
    assert flow.ask_calls[ 0 ][ "session_id" ] == "api-u1234567"
    assert flow.ask_calls[ 0 ][ "websocket_id" ] == "api-u1234567"


def test_websocket_id_in_the_form_body_is_ignored( tmp_path, io_rows ):
    """CB1: the id is a QUERY parameter. Sent in the form it silently falls back — pinned here."""
    flow   = FakeFlow()
    client = TestClient( _app( flow, FakeProvider(), str( tmp_path ) ) )
    client.post( "/api/v2/ask-audio", data={ "websocket_id": "wise penguin" },
                 files={ "file": ( "q.wav", b"\0" * 10, "audio/wav" ) } )
    assert flow.ask_calls[ 0 ][ "session_id" ] == "api-u1234567"


def test_io_row_is_written_through_the_shared_speech_helper( tmp_path, io_rows ):
    client = TestClient( _app( FakeFlow(), FakeProvider(), str( tmp_path ) ) )
    _post( client )
    assert io_rows == [ { "input_type": "stt_wav_ask", "input": TRANSCRIPT, "output_raw": TRANSCRIPT, "output_final": TRANSCRIPT } ]


# ────────────────────────────────────────────────────────────── statuses before the stream

@pytest.mark.parametrize( "user, detail", [
    ( { "email": "u@x.com" },           "User id not found in authentication token." ),
    ( { "uid": "u1" },                  "User email not found in authentication token." ),
] )
def test_401_without_identity_and_nothing_is_transcribed( tmp_path, io_rows, user, detail ):
    flow, provider = FakeFlow(), FakeProvider()
    resp = _post( TestClient( _app( flow, provider, str( tmp_path ), user=user ) ) )
    assert resp.status_code == 401 and resp.json()[ "detail" ] == detail
    assert provider.paths == [] and flow.ask_calls == []


def test_503_when_the_flow_is_disabled( tmp_path, io_rows ):
    app = _app( FakeFlow(), FakeProvider(), str( tmp_path ) )
    def _disabled(): raise HTTPException( status_code=503, detail="CJ Flow v2 is disabled (v2 flow enabled = False)." )
    app.dependency_overrides[ v2_ask.get_ask_flow ] = _disabled
    assert _post( TestClient( app ) ).status_code == 503


def test_422_on_empty_transcript_and_the_flow_is_never_called( tmp_path, io_rows ):
    flow = FakeFlow()
    resp = _post( TestClient( _app( flow, FakeProvider( text="   " ), str( tmp_path ) ) ) )
    assert resp.status_code == 422
    assert resp.json()[ "detail" ] == "No speech was recognised, so nothing was asked."
    assert flow.ask_calls == [] and io_rows == []
    assert os.listdir( tmp_path ) == []


def test_503_with_retry_after_on_gpu_oom( tmp_path, io_rows ):
    flow = FakeFlow()
    resp = _post( TestClient( _app( flow, FakeProvider( raises=torch.cuda.OutOfMemoryError( "oom" ) ), str( tmp_path ) ) ) )
    assert resp.status_code == 503 and resp.headers[ "retry-after" ] == "5"
    assert resp.json()[ "detail" ] == "Server GPU memory temporarily unavailable. Please retry in a few seconds."
    assert flow.ask_calls == [] and os.listdir( tmp_path ) == []


def test_500_on_a_transcribe_failure_sends_the_fixed_detail_and_no_exception_text( tmp_path, io_rows ):
    """E4: follow the MP3 door — one fixed message; the exception goes to the log, not the client."""
    flow = FakeFlow()
    resp = _post( TestClient( _app( flow, FakeProvider( raises=RuntimeError( "model server said secret-xyz" ) ), str( tmp_path ) ) ) )
    assert resp.status_code == 500
    assert resp.json()[ "detail" ] == "Could not accept the audio. Nothing was asked."
    assert "secret-xyz" not in resp.text
    assert flow.ask_calls == [] and os.listdir( tmp_path ) == []


def test_500_when_the_save_raises_oserror_and_transcribe_never_runs( tmp_path, monkeypatch, io_rows ):
    """E4b: the save is inside the try. At rev 12 this escaped as a bare FastAPI 500."""
    def _full_disk( *a, **k ): raise OSError( 28, "No space left on device" )
    monkeypatch.setattr( speech, "save_audio_upload", _full_disk )
    flow, provider = FakeFlow(), FakeProvider()
    resp = _post( TestClient( _app( flow, provider, str( tmp_path ) ), raise_server_exceptions=False ) )
    assert resp.status_code == 500
    assert resp.json() == { "detail": "Could not accept the audio. Nothing was asked." }
    assert provider.paths == [] and flow.ask_calls == []


def test_500_when_the_io_row_insert_fails_and_nothing_is_asked( tmp_path, monkeypatch ):
    """J-A2: the insert is inside the try, as both existing doors keep it. A DB fault is the shaped 500."""
    def _db_down( **kw ): raise RuntimeError( "connection refused: postgres-secret-host" )
    monkeypatch.setattr( speech, "insert_stt_io_row", _db_down )
    flow = FakeFlow()
    resp = _post( TestClient( _app( flow, FakeProvider(), str( tmp_path ) ), raise_server_exceptions=False ) )
    assert resp.status_code == 500
    assert resp.json() == { "detail": "Could not accept the audio. Nothing was asked." }
    assert "postgres-secret-host" not in resp.text
    assert flow.ask_calls == [] and os.listdir( tmp_path ) == []


def test_500_when_reading_the_upload_fails( tmp_path, monkeypatch, io_rows ):
    """The read is inside the try too; the finally then removes a path that was never set."""
    removed = []
    monkeypatch.setattr( speech, "remove_audio_upload", lambda p: removed.append( p ) )
    upload = _upload()
    async def _broken_read(): raise OSError( "client went away mid-upload" )
    upload.read = _broken_read
    with pytest.raises( HTTPException ) as caught:
        asyncio.run( _call( FakeFlow(), FakeProvider(), str( tmp_path ), file=upload ) )
    assert caught.value.status_code == 500
    assert removed == [ None ]


# ────────────────────────────────────────────────────────────── line 2 variants

def test_error_line_when_the_ask_raises( tmp_path, io_rows ):
    client = TestClient( _app( FakeFlow( raises=ValueError( "router down" ) ), FakeProvider(), str( tmp_path ) ) )
    lines  = _post( client ).text.split( "\n" )
    assert json.loads( lines[ 0 ] )[ "type" ] == "transcript"
    assert json.loads( lines[ 1 ] ) == { "type": "error", "stage": "ask", "detail": "router down" }
    assert lines[ 2 ] == ""


@pytest.mark.parametrize( "status, pending_id", [ ( "parked", "pend-1" ), ( "needs_input", None ) ] )
def test_needs_input_and_parked_results_pass_through_whole( tmp_path, io_rows, status, pending_id ):
    result = _result( path="needs_input", status=status, pending_id=pending_id, job_id=None,
                      args_missing=[ "location" ], answer="Which city?" )
    client = TestClient( _app( FakeFlow( result=result ), FakeProvider(), str( tmp_path ) ) )
    got    = json.loads( _post( client ).text.split( "\n" )[ 1 ] )[ "result" ]
    assert got == result


# ────────────────────────────────────────────────────────────── the uploaded file

def test_temp_file_is_removed_after_success( tmp_path, io_rows ):
    provider = FakeProvider()
    _post( TestClient( _app( FakeFlow(), provider, str( tmp_path ) ) ) )
    assert len( provider.paths ) == 1 and not os.path.exists( provider.paths[ 0 ] )
    assert os.listdir( tmp_path ) == []


@pytest.mark.parametrize( "filename, suffix", [ ( "x.ogg", ".ogg" ), ( "../../a b.wav;rm", ".wav" ), ( "noext", ".wav" ) ] )
def test_suffix_is_vetted_and_no_client_filename_text_reaches_the_path( tmp_path, io_rows, filename, suffix ):
    provider = FakeProvider()
    _post( TestClient( _app( FakeFlow(), provider, str( tmp_path ) ) ), filename=filename )
    path = provider.paths[ 0 ]
    assert os.path.dirname( path ) == str( tmp_path )
    assert path.endswith( suffix )
    # 🔴 A WHITELIST, NOT A FRAGMENT BLACKLIST. This used to loop over ( "..", " ",
    # ";", "rm", "noext", "x.ogg" ) asserting none appeared in the basename — but the
    # basename ends in `tempfile.mkstemp`'s RANDOM 8-character token, so the check ran
    # over a string nobody controls. Measured red 2026-09-19 on
    # `u1234567-20260919T220640-rmmvxp9i.wav`: the token happened to start "rm", the
    # fragment from `../../a b.wav;rm`. Roughly a 1-in-200 false accusation per run,
    # and it passes on re-run, which is the worst shape a test can have.
    #
    # Matching the whole structure is strictly STRONGER than the blacklist it replaces:
    # the name is permitted to be `<uid8>-<stamp>-<token><suffix>` and nothing else, so
    # NO client-supplied text can appear anywhere in it, including fragments nobody
    # thought to enumerate. Same predicate the cosa suite already uses
    # (`_UPLOAD_NAME` in `cosa/tests/unit/rest/test_speech_router.py`).
    assert re.fullmatch(
        r"u1234567-\d{8}T\d{6}-[A-Za-z0-9_]{8}" + re.escape( suffix ),
        os.path.basename( path ),
    ), os.path.basename( path )


# ────────────────────────────────────────────────────────────── threads and headers

def test_transcribe_and_ask_both_run_through_run_in_threadpool( tmp_path, monkeypatch, io_rows ):
    """A-C3: named mechanism — a spy on the module's run_in_threadpool, not an inference."""
    real, called = v2_ask.run_in_threadpool, []
    async def _spy( fn, *a, **k ):
        called.append( threading.current_thread().name )
        return await real( fn, *a, **k )
    monkeypatch.setattr( v2_ask, "run_in_threadpool", _spy )
    provider, flow = FakeProvider(), FakeFlow()
    _post( TestClient( _app( flow, provider, str( tmp_path ) ) ) )
    # transcribe, the io row, and the ask — three hops off the loop, in that order
    assert len( called ) == 3
    assert provider.paths and flow.ask_calls


def test_stream_headers_are_exactly_the_two_and_not_the_sse_set():
    assert v2_ask._stream_headers() == { "Cache-Control": "no-cache", "X-Accel-Buffering": "no" }


def test_ndjson_line_is_compact_and_newline_terminated():
    assert v2_ask._ndjson( { "a": 1, "b": [ 1, 2 ] } ) == '{"a":1,"b":[1,2]}\n'


# ────────────────────────────────────────────────────────────── D4, five arms

async def _drain_to_first_line( response ):
    gen   = response.body_iterator
    first = await gen.__anext__()
    return gen, first


def test_d4a_the_ask_runs_even_when_the_body_is_never_iterated( tmp_path, io_rows ):
    flow = FakeFlow()
    async def scenario():
        await _call( flow, FakeProvider(), str( tmp_path ) )
        for _ in range( 200 ):
            if flow.finished.is_set(): return True
            await asyncio.sleep( 0.01 )
        return False
    assert asyncio.run( scenario() ) is True
    assert len( flow.ask_calls ) == 1


def test_d4b_closing_the_generator_after_line_one_does_not_stop_the_ask( tmp_path, io_rows ):
    gate = threading.Event()
    flow = FakeFlow( gate=gate )
    async def scenario():
        response   = await _call( flow, FakeProvider(), str( tmp_path ) )
        gen, first = await _drain_to_first_line( response )
        assert json.loads( first )[ "type" ] == "transcript"
        await gen.aclose()                      # the client went away after line 1
        gate.set()
        for _ in range( 200 ):
            if flow.finished.is_set(): return True
            await asyncio.sleep( 0.01 )
        return False
    assert asyncio.run( scenario() ) is True


def test_d4c_the_ask_task_exists_before_the_response_object_does( tmp_path, monkeypatch, io_rows ):
    """
    S-D4, test-side only. At StreamingResponse construction there is one registered ask task
    and it has not finished. Do NOT assert FakeFlow's event here: create_task only schedules,
    so a correct handler has not started its thread yet at this moment.
    """
    seen      = []
    real_resp = v2_ask.StreamingResponse
    def _spy( *a, **k ):
        seen.append( ( len( v2_ask._INFLIGHT_ASKS ), [ t.done() for t in v2_ask._INFLIGHT_ASKS ] ) )
        return real_resp( *a, **k )
    monkeypatch.setattr( v2_ask, "StreamingResponse", _spy )
    gate = threading.Event()
    async def scenario():
        await _call( FakeFlow( gate=gate ), FakeProvider(), str( tmp_path ) )
        gate.set()
        await asyncio.sleep( 0.05 )
    asyncio.run( scenario() )
    assert seen == [ ( 1, [ False ] ) ]


def test_d4c_control_an_ask_created_inside_the_generator_is_seen_as_absent( monkeypatch ):
    """The spy above can fail: with nothing registered before construction it records zero."""
    seen      = []
    real_resp = v2_ask.StreamingResponse
    def _spy( *a, **k ):
        seen.append( len( v2_ask._INFLIGHT_ASKS ) )
        return real_resp( *a, **k )
    monkeypatch.setattr( v2_ask, "StreamingResponse", _spy )
    async def wrong_shape():
        async def lines():
            task = asyncio.create_task( asyncio.sleep( 0 ) )
            v2_ask._INFLIGHT_ASKS.add( task )
            yield "x"
        return v2_ask.StreamingResponse( lines() )
    asyncio.run( wrong_shape() )
    assert seen == [ 0 ]


def test_d4d_a_failing_ask_after_the_client_left_is_retrieved_not_reported( tmp_path, io_rows ):
    gate    = threading.Event()
    flow    = FakeFlow( raises=RuntimeError( "boom" ), gate=gate )
    reports = []
    async def scenario():
        asyncio.get_running_loop().set_exception_handler( lambda loop, ctx: reports.append( ctx.get( "message" ) ) )
        response   = await _call( flow, FakeProvider(), str( tmp_path ) )
        gen, _     = await _drain_to_first_line( response )
        await gen.aclose()
        del response, gen
        gate.set()
        for _ in range( 200 ):
            if not v2_ask._INFLIGHT_ASKS: break
            await asyncio.sleep( 0.01 )
        gc.collect()
        await asyncio.sleep( 0.01 )
    asyncio.run( scenario() )
    assert flow.finished.is_set()
    assert not [ m for m in reports if m and "never retrieved" in m ]


def test_d4e_registration_held_while_in_flight_and_released_on_success_and_failure( tmp_path, io_rows ):
    ok_gate, bad_gate = threading.Event(), threading.Event()
    ok_flow  = FakeFlow( gate=ok_gate )
    bad_flow = FakeFlow( gate=bad_gate, raises=RuntimeError( "boom" ) )
    async def scenario():
        v2_ask._INFLIGHT_ASKS.clear()
        await _call( ok_flow,  FakeProvider(), str( tmp_path ) )
        await _call( bad_flow, FakeProvider(), str( tmp_path ) )
        both_held = len( v2_ask._INFLIGHT_ASKS ) == 2       # overlapping asks do not evict each other
        ok_gate.set()
        for _ in range( 200 ):
            if len( v2_ask._INFLIGHT_ASKS ) == 1: break
            await asyncio.sleep( 0.01 )
        one_left = len( v2_ask._INFLIGHT_ASKS ) == 1
        bad_gate.set()
        for _ in range( 200 ):
            if not v2_ask._INFLIGHT_ASKS: break
            await asyncio.sleep( 0.01 )
        return both_held, one_left, len( v2_ask._INFLIGHT_ASKS )
    assert asyncio.run( scenario() ) == ( True, True, 0 )


def test_d4_a_cancelled_ask_task_is_released_without_touching_its_exception( tmp_path, io_rows ):
    """
    _release must not call exception() on a cancelled task — that raises CancelledError inside
    the done-callback, which the loop reports. Nothing in this door cancels the ask, but shutdown can.
    """
    gate    = threading.Event()
    reports = []
    async def scenario():
        asyncio.get_running_loop().set_exception_handler( lambda loop, ctx: reports.append( ctx ) )
        v2_ask._INFLIGHT_ASKS.clear()
        await _call( FakeFlow( gate=gate ), FakeProvider(), str( tmp_path ) )
        ( task, ) = tuple( v2_ask._INFLIGHT_ASKS )
        task.cancel()
        gate.set()
        for _ in range( 200 ):
            if task.done() and not v2_ask._INFLIGHT_ASKS: break
            await asyncio.sleep( 0.01 )
        await asyncio.sleep( 0.01 )
        return task.cancelled(), len( v2_ask._INFLIGHT_ASKS )
    assert asyncio.run( scenario() ) == ( True, 0 )
    assert reports == []


def test_d4_cancelled_generator_reraises_cancellation( tmp_path, io_rows ):
    """The CancelledError arm re-raises, so Starlette's cancel is honoured and the ask keeps running."""
    gate = threading.Event()
    flow = FakeFlow( gate=gate )
    async def scenario():
        response   = await _call( flow, FakeProvider(), str( tmp_path ) )
        gen, _     = await _drain_to_first_line( response )
        pending    = asyncio.ensure_future( gen.__anext__() )
        await asyncio.sleep( 0.02 )
        pending.cancel()
        try:
            await pending
            return "no-cancel"
        except asyncio.CancelledError:
            gate.set()
            for _ in range( 200 ):
                if flow.finished.is_set(): return "cancelled-ask-finished"
                await asyncio.sleep( 0.01 )
            return "cancelled-ask-stuck"
    assert asyncio.run( scenario() ) == "cancelled-ask-finished"
