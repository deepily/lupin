#!/usr/bin/env python3
"""
Unit tests for POST /api/v2/transcribe — the transcribe-only door (routers/v2_ask.py, row fcebf532).

The phone's Quick Ask review mode and its focus-mode voice reply need the words BEFORE anything is
sent, so they still called the legacy /api/upload-and-transcribe-wav. This door is /api/v2/ask-audio
with the ask taken out: same identity check, same upload handling, same error statuses and details
where the meaning is the same, and a JSON body holding the transcript and nothing else.

Hermetic: the router is mounted on a bare FastAPI app and identity, the speech provider, the whisper
pipeline and the config manager are overridden; the io-row writer is monkeypatched. :7999-eligible.
"""

import io
import os
import types

import pytest
import torch
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.datastructures import UploadFile

from cosa.rest.routers import speech, v2_ask


USER         = { "uid": "u1234567890", "email": "u@x.com" }
UPLOAD_BYTES = 4096
TRANSCRIPT   = "buy oat milk on the way home"


# ────────────────────────────────────────────────────────────── fakes

class FakeProvider:
    """Records the path it was handed and whether that file existed then."""

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
    rows = []
    monkeypatch.setattr( speech, "insert_stt_io_row", lambda **kw: rows.append( kw ) )
    return rows


def _app( provider, upload_dir, user=USER ):
    app = FastAPI()
    app.include_router( v2_ask.router )
    app.dependency_overrides[ v2_ask.get_current_user ]     = lambda: user
    app.dependency_overrides[ speech.get_speech_provider ]  = lambda: provider
    app.dependency_overrides[ speech.get_whisper_pipeline ] = lambda: None
    app.dependency_overrides[ speech.get_config_manager ]   = lambda: FakeConfig( upload_dir )
    return app


def _post( client, filename="reply.ogg", content=b"\1" * UPLOAD_BYTES ):
    return client.post( "/api/v2/transcribe", files={ "file": ( filename, content, "audio/ogg" ) } )


def _pin_stt_ms( monkeypatch, span_seconds=0.1234 ):
    ticks = iter( [ 50.0, 50.0 + span_seconds ] )
    monkeypatch.setattr( v2_ask, "time", types.SimpleNamespace( perf_counter=lambda: next( ticks ) ) )


# ────────────────────────────────────────────────────────────── the body

def test_200_body_is_the_transcript_and_its_trace_and_nothing_else( tmp_path, monkeypatch, io_rows ):
    _pin_stt_ms( monkeypatch )
    resp = _post( TestClient( _app( FakeProvider(), str( tmp_path ) ) ) )
    assert resp.status_code == 200
    assert resp.headers[ "content-type" ].startswith( "application/json" )
    assert resp.json() == { "transcription": TRANSCRIPT, "trace": { "stt_ms": 123.4, "upload_bytes": UPLOAD_BYTES } }


def test_the_transcript_is_stripped( tmp_path, io_rows ):
    resp = _post( TestClient( _app( FakeProvider( text="  hello there \n" ), str( tmp_path ) ) ) )
    assert resp.json()[ "transcription" ] == "hello there"


def test_no_ask_flow_is_needed_so_a_disabled_v2_flow_does_not_block_it( tmp_path, io_rows ):
    # Nothing is asked, so the v2 flow's feature gate is not this door's business.
    app = _app( FakeProvider(), str( tmp_path ) )
    def _disabled(): raise HTTPException( status_code=503, detail="CJ Flow v2 is disabled (v2 flow enabled = False)." )
    app.dependency_overrides[ v2_ask.get_ask_flow ] = _disabled
    assert _post( TestClient( app ) ).status_code == 200


def test_io_row_names_this_door( tmp_path, io_rows ):
    _post( TestClient( _app( FakeProvider(), str( tmp_path ) ) ) )
    assert io_rows == [ { "input_type": "stt_transcribe", "input": TRANSCRIPT, "output_raw": TRANSCRIPT, "output_final": TRANSCRIPT } ]


# ────────────────────────────────────────────────────────────── the file

@pytest.mark.parametrize( "filename, suffix", [ ( "reply.ogg", ".ogg" ), ( "reply.wav", ".wav" ), ( "noext", ".wav" ), ( "../../a b.ogg;rm", ".wav" ) ] )
def test_the_extension_is_kept_and_nothing_else_of_the_filename( tmp_path, io_rows, filename, suffix ):
    provider = FakeProvider()
    assert _post( TestClient( _app( provider, str( tmp_path ) ) ), filename=filename ).status_code == 200
    path = provider.paths[ 0 ]
    assert os.path.dirname( path ) == str( tmp_path )
    assert path.endswith( suffix )
    assert os.path.basename( path ).startswith( "u1234567-" )
    assert ".." not in os.path.basename( path ) and ";" not in path and " " not in os.path.basename( path )


def test_temp_file_is_removed_after_success( tmp_path, io_rows ):
    provider = FakeProvider()
    _post( TestClient( _app( provider, str( tmp_path ) ) ) )
    assert len( provider.paths ) == 1 and os.listdir( tmp_path ) == []


def test_422_when_the_file_part_is_absent_and_nothing_is_transcribed( tmp_path, io_rows ):
    provider = FakeProvider()
    resp = TestClient( _app( provider, str( tmp_path ) ) ).post( "/api/v2/transcribe" )
    assert resp.status_code == 422
    assert resp.json()[ "detail" ][ 0 ][ "loc" ] == [ "body", "file" ]
    assert provider.paths == [] and io_rows == []


def test_422_when_the_file_is_empty_and_nothing_is_saved_or_transcribed( tmp_path, io_rows ):
    provider = FakeProvider()
    resp = _post( TestClient( _app( provider, str( tmp_path ) ) ), content=b"" )
    assert resp.status_code == 422
    assert resp.json() == { "detail": "The audio upload was empty, so nothing was transcribed." }
    assert provider.paths == [] and io_rows == [] and os.listdir( tmp_path ) == []


# ────────────────────────────────────────────────────────────── refusals and failures

@pytest.mark.parametrize( "user, detail", [
    ( { "email": "u@x.com" }, "User id not found in authentication token." ),
    ( { "uid": "u1" },        "User email not found in authentication token." ),
] )
def test_401_without_identity_and_nothing_is_transcribed( tmp_path, io_rows, user, detail ):
    provider = FakeProvider()
    resp = _post( TestClient( _app( provider, str( tmp_path ), user=user ) ) )
    assert resp.status_code == 401 and resp.json()[ "detail" ] == detail
    assert provider.paths == [] and os.listdir( tmp_path ) == []


def test_401_from_the_real_auth_dependency_when_no_token_is_sent( tmp_path, io_rows ):
    app = _app( FakeProvider(), str( tmp_path ) )
    del app.dependency_overrides[ v2_ask.get_current_user ]
    assert _post( TestClient( app ) ).status_code == 401


def test_422_on_empty_speech( tmp_path, io_rows ):
    resp = _post( TestClient( _app( FakeProvider( text="   " ), str( tmp_path ) ) ) )
    assert resp.status_code == 422
    assert resp.json() == { "detail": "No speech was recognised." }
    assert io_rows == [] and os.listdir( tmp_path ) == []


def test_503_with_retry_after_on_gpu_oom( tmp_path, io_rows ):
    resp = _post( TestClient( _app( FakeProvider( raises=torch.cuda.OutOfMemoryError( "oom" ) ), str( tmp_path ) ) ) )
    assert resp.status_code == 503 and resp.headers[ "retry-after" ] == "5"
    assert resp.json()[ "detail" ] == "Server GPU memory temporarily unavailable. Please retry in a few seconds."
    assert os.listdir( tmp_path ) == []


def test_500_on_a_transcribe_failure_sends_the_fixed_detail_and_no_exception_text( tmp_path, io_rows ):
    resp = _post( TestClient( _app( FakeProvider( raises=RuntimeError( "model server said secret-xyz" ) ), str( tmp_path ) ) ) )
    assert resp.status_code == 500
    assert resp.json() == { "detail": "Could not transcribe the audio." }
    assert "secret-xyz" not in resp.text and os.listdir( tmp_path ) == []


def test_500_when_the_save_raises_oserror_and_transcribe_never_runs( tmp_path, monkeypatch, io_rows ):
    def _full_disk( *a, **k ): raise OSError( 28, "No space left on device" )
    monkeypatch.setattr( speech, "save_audio_upload", _full_disk )
    provider = FakeProvider()
    resp = _post( TestClient( _app( provider, str( tmp_path ) ), raise_server_exceptions=False ) )
    assert resp.status_code == 500 and resp.json() == { "detail": "Could not transcribe the audio." }
    assert provider.paths == []


def test_500_when_the_io_row_insert_fails( tmp_path, monkeypatch ):
    def _db_down( **kw ): raise RuntimeError( "db down" )
    monkeypatch.setattr( speech, "insert_stt_io_row", _db_down )
    resp = _post( TestClient( _app( FakeProvider(), str( tmp_path ) ), raise_server_exceptions=False ) )
    assert resp.status_code == 500 and resp.json() == { "detail": "Could not transcribe the audio." }
    assert os.listdir( tmp_path ) == []


def test_500_when_reading_the_upload_fails( tmp_path, io_rows ):
    class _Broken( UploadFile ):
        async def read( self, size=-1 ): raise OSError( "client went away" )
    provider = FakeProvider()
    import asyncio
    with pytest.raises( HTTPException ) as caught:
        asyncio.run( v2_ask.transcribe(
            file=_Broken( file=io.BytesIO( b"x" ), filename="r.ogg" ), current_user=USER,
            provider=provider, whisper_pipeline=None, config_mgr=FakeConfig( str( tmp_path ) ) ) )
    assert caught.value.status_code == 500 and caught.value.detail == "Could not transcribe the audio."
    assert provider.paths == []


def test_transcribe_runs_through_run_in_threadpool( tmp_path, monkeypatch, io_rows ):
    calls = []
    real  = v2_ask.run_in_threadpool
    async def _spy( fn, *a, **k ):
        calls.append( fn )
        return await real( fn, *a, **k )
    monkeypatch.setattr( v2_ask, "run_in_threadpool", _spy )
    assert _post( TestClient( _app( FakeProvider(), str( tmp_path ) ) ) ).status_code == 200
    assert len( calls ) == 2, "transcribe and the io-row insert must both leave the event loop"
