"""
Unit tests for `src/lupin_model_server/main.py` — Phase 5 of the
2026-05-16 model-server carve-out.

Coverage target: 100% line + branch + function on the non-pragma'd
surfaces (live model-loading + `/transcribe` + `/embeddings/{generate,batch}`
are intentionally `pragma: no cover` in the source — they're exercised by
`src/tests/smoke/test_model_server_smoke.py` against a real `:7998`).

Surfaces covered here (per `91-phase5-smoke-audit.md` §"Refined Phase 5.3 test list"):
    - `_State` class behavior
    - `_load_api_key_plaintext` happy + failure paths
    - `require_api_key` 503 / 401 (missing / wrong-format / hash-mismatch) / success
    - `_update_vram_gauge` (CUDA-available + CUDA-unavailable)
    - `EmbedRequest` / `EmbedBatchRequest` Pydantic validation
    - `/health` 503 / 200 responses
    - `_select_engine` route logic
    - `/embeddings/info` + `/admin/metrics` endpoints (auth + payload)
"""

from unittest.mock import MagicMock, patch

import bcrypt
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture( autouse=True )
def reset_model_server_state():
    """
    Reset module-level `_state` to a fresh `_State()` before each test, and
    restore the original instance after.

    Requires:
        - `lupin_model_server.main` importable

    Ensures:
        - Each test sees a fresh `_state`, isolating models_loaded / load_errors
        - The original module-level singleton is restored on teardown
    """
    from lupin_model_server import main as ms

    original_state = ms._state
    ms._state      = ms._State()
    yield
    ms._state      = original_state


@pytest.fixture
def client():
    """FastAPI TestClient bound to the model-server app."""
    from lupin_model_server import main as ms

    return TestClient( ms.app )


def _set_valid_api_key_hash( plaintext="ck_live_" + "a" * 64 ):
    """Set `_state.api_key_hash` to the bcrypt hash of `plaintext`."""
    from lupin_model_server import main as ms

    ms._state.api_key_hash = bcrypt.hashpw( plaintext.encode( "utf-8" ), bcrypt.gensalt() )
    return plaintext


# ── _State class ────────────────────────────────────────────────────────────


def test_state_init_defaults():
    from lupin_model_server.main import _State

    s = _State()
    assert s.whisper_pipeline is None
    assert s.code_engine      is None
    assert s.prose_engine     is None
    assert s.models_loaded    == []
    assert s.load_errors      == []
    assert s.api_key_hash     is None
    assert isinstance( s.started_at, float )


def test_state_is_ready_false_when_no_models_loaded():
    from lupin_model_server.main import _State

    s = _State()
    assert s.is_ready() is False


def test_state_is_ready_false_when_only_2_models_loaded():
    from lupin_model_server.main import _State

    s = _State()
    s.models_loaded = [ "whisper", "code_rank_embed" ]
    assert s.is_ready() is False


def test_state_is_ready_false_when_load_errors_present():
    from lupin_model_server.main import _State

    s = _State()
    s.models_loaded = [ "whisper", "code_rank_embed", "nomic_embed_text_v1_5" ]
    s.load_errors   = [ "prose_engine: OOM" ]
    assert s.is_ready() is False


def test_state_is_ready_true_when_3_loaded_no_errors():
    from lupin_model_server.main import _State

    s = _State()
    s.models_loaded = [ "whisper", "code_rank_embed", "nomic_embed_text_v1_5" ]
    assert s.is_ready() is True


# ── _load_api_key_plaintext ─────────────────────────────────────────────────


def test_load_api_key_plaintext_reads_file_and_strips( monkeypatch, tmp_path ):
    from lupin_model_server import main as ms

    key_file = tmp_path / "test-key"
    key_file.write_text( "  ck_live_test_xyz  \n" )

    monkeypatch.setattr( ms, "KEYS_DIR", str( tmp_path ) )
    monkeypatch.setattr( ms, "API_KEY_NAME", "test-key" )

    assert ms._load_api_key_plaintext() == "ck_live_test_xyz"


def test_load_api_key_plaintext_returns_none_on_missing_file( monkeypatch, tmp_path ):
    from lupin_model_server import main as ms

    monkeypatch.setattr( ms, "KEYS_DIR", str( tmp_path ) )
    monkeypatch.setattr( ms, "API_KEY_NAME", "does-not-exist" )

    assert ms._load_api_key_plaintext() is None


def test_load_api_key_plaintext_returns_none_on_empty_file( monkeypatch, tmp_path ):
    from lupin_model_server import main as ms

    key_file = tmp_path / "empty-key"
    key_file.write_text( "   \n  " )

    monkeypatch.setattr( ms, "KEYS_DIR", str( tmp_path ) )
    monkeypatch.setattr( ms, "API_KEY_NAME", "empty-key" )

    assert ms._load_api_key_plaintext() is None


# ── require_api_key ─────────────────────────────────────────────────────────


def test_require_api_key_raises_503_when_hash_not_loaded():
    from lupin_model_server.main import require_api_key

    # _state.api_key_hash is None (reset fixture)
    with pytest.raises( HTTPException ) as exc_info:
        require_api_key( x_api_key="ck_live_" + "a" * 64 )

    assert exc_info.value.status_code == 503
    assert "not configured" in exc_info.value.detail.lower()


def test_require_api_key_raises_401_on_missing_header():
    from lupin_model_server.main import require_api_key

    _set_valid_api_key_hash()
    with pytest.raises( HTTPException ) as exc_info:
        require_api_key( x_api_key=None )

    assert exc_info.value.status_code == 401
    assert "Missing X-API-Key" in exc_info.value.detail


def test_require_api_key_raises_401_on_empty_header():
    from lupin_model_server.main import require_api_key

    _set_valid_api_key_hash()
    with pytest.raises( HTTPException ) as exc_info:
        require_api_key( x_api_key="" )

    assert exc_info.value.status_code == 401


def test_require_api_key_raises_401_on_wrong_prefix():
    from lupin_model_server.main import require_api_key

    _set_valid_api_key_hash()
    with pytest.raises( HTTPException ) as exc_info:
        require_api_key( x_api_key="ck_internal_" + "x" * 64 )

    assert exc_info.value.status_code == 401
    assert "format" in exc_info.value.detail.lower()


def test_require_api_key_raises_401_on_too_short_key():
    from lupin_model_server.main import require_api_key

    _set_valid_api_key_hash()
    with pytest.raises( HTTPException ) as exc_info:
        require_api_key( x_api_key="ck_live_short" )

    assert exc_info.value.status_code == 401
    assert "format" in exc_info.value.detail.lower()


def test_require_api_key_raises_401_on_hash_mismatch():
    from lupin_model_server.main import require_api_key

    _set_valid_api_key_hash()
    with pytest.raises( HTTPException ) as exc_info:
        require_api_key( x_api_key="ck_live_" + "b" * 64 )  # wrong key, correct format

    assert exc_info.value.status_code == 401
    assert "Invalid X-API-Key" in exc_info.value.detail


def test_require_api_key_returns_key_on_success():
    from lupin_model_server.main import require_api_key

    plaintext = _set_valid_api_key_hash( "ck_live_" + "c" * 64 )
    result    = require_api_key( x_api_key=plaintext )
    assert result == plaintext


# ── _update_vram_gauge ──────────────────────────────────────────────────────


def test_update_vram_gauge_reads_cuda_memory_when_available():
    from lupin_model_server import main as ms

    with patch( "lupin_model_server.main.torch.cuda.is_available", return_value=True ):
        with patch(
            "lupin_model_server.main.torch.cuda.memory_allocated", return_value=1024 * 1024 * 512
        ):
            ms._update_vram_gauge()

    # Gauge value is MB
    value = ms._VRAM_USED_MB._value.get()
    assert value == pytest.approx( 512.0 )


def test_update_vram_gauge_sets_zero_when_cuda_unavailable():
    from lupin_model_server import main as ms

    with patch( "lupin_model_server.main.torch.cuda.is_available", return_value=False ):
        ms._update_vram_gauge()

    value = ms._VRAM_USED_MB._value.get()
    assert value == 0


# ── Model loader helpers (lightweight coverage) ─────────────────────────────


def test_load_whisper_dtype_selection_branch( monkeypatch ):
    """
    Cover the `torch.float16 if torch.cuda.is_available() else torch.float32`
    dtype branch inside `_load_whisper()` (line 212 in main.py). The
    surrounding pipeline-construction lines are `pragma: no cover` (real
    transformers model load), but the dtype selection is not pragma'd and
    needs explicit coverage.
    """
    import sys

    from lupin_model_server import main as ms

    fake_transformers = MagicMock()
    fake_transformers.pipeline = MagicMock( return_value="fake-pipeline" )

    with patch.dict( sys.modules, { "transformers": fake_transformers } ):
        result = ms._load_whisper()

    assert result == "fake-pipeline"
    fake_transformers.pipeline.assert_called_once()


# ── Pydantic models ─────────────────────────────────────────────────────────


def test_embed_request_accepts_code():
    from lupin_model_server.main import EmbedRequest

    req = EmbedRequest( text="def foo(): pass", content_type="code" )
    assert req.content_type == "code"


def test_embed_request_accepts_prose():
    from lupin_model_server.main import EmbedRequest

    req = EmbedRequest( text="hello", content_type="prose" )
    assert req.content_type == "prose"


def test_embed_request_defaults_content_type_to_prose():
    from lupin_model_server.main import EmbedRequest

    req = EmbedRequest( text="hello" )
    assert req.content_type == "prose"


def test_embed_request_rejects_invalid_content_type():
    from pydantic import ValidationError

    from lupin_model_server.main import EmbedRequest

    with pytest.raises( ValidationError ):
        EmbedRequest( text="hello", content_type="audio" )


def test_embed_request_rejects_empty_text():
    from pydantic import ValidationError

    from lupin_model_server.main import EmbedRequest

    with pytest.raises( ValidationError ):
        EmbedRequest( text="", content_type="prose" )


def test_embed_batch_request_accepts_code():
    from lupin_model_server.main import EmbedBatchRequest

    req = EmbedBatchRequest( texts=[ "a", "b" ], content_type="code" )
    assert req.content_type == "code"


def test_embed_batch_request_rejects_invalid_content_type():
    from pydantic import ValidationError

    from lupin_model_server.main import EmbedBatchRequest

    with pytest.raises( ValidationError ):
        EmbedBatchRequest( texts=[ "a" ], content_type="audio" )


# ── /health endpoint ────────────────────────────────────────────────────────


def test_health_returns_503_when_not_ready( client ):
    from lupin_model_server import main as ms

    # Default _state has no models loaded → not ready
    resp = client.get( "/health" )
    assert resp.status_code == 503
    body = resp.json()
    assert body[ "status" ]        == "loading"
    assert body[ "models_loaded" ] == []
    assert body[ "load_errors" ]   == []
    assert "uptime_seconds" in body
    assert "vram_used_mb"   in body


def test_health_returns_200_when_ready( client ):
    from lupin_model_server import main as ms

    ms._state.models_loaded = [ "whisper", "code_rank_embed", "nomic_embed_text_v1_5" ]
    resp = client.get( "/health" )
    assert resp.status_code == 200
    body = resp.json()
    assert body[ "status" ]        == "ready"
    assert len( body[ "models_loaded" ] ) == 3


# ── _select_engine ──────────────────────────────────────────────────────────


def test_select_engine_returns_code_engine_for_code():
    from lupin_model_server import main as ms

    ms._state.code_engine = MagicMock( name="code_engine" )
    engine = ms._select_engine( "code" )
    assert engine is ms._state.code_engine


def test_select_engine_returns_prose_engine_for_prose():
    from lupin_model_server import main as ms

    ms._state.prose_engine = MagicMock( name="prose_engine" )
    engine = ms._select_engine( "prose" )
    assert engine is ms._state.prose_engine


def test_select_engine_raises_503_when_engine_none():
    from lupin_model_server import main as ms

    # code_engine is None by default
    with pytest.raises( HTTPException ) as exc_info:
        ms._select_engine( "code" )
    assert exc_info.value.status_code == 503
    assert "code engine not loaded" in exc_info.value.detail


def test_select_engine_raises_503_when_prose_engine_none():
    from lupin_model_server import main as ms

    with pytest.raises( HTTPException ) as exc_info:
        ms._select_engine( "prose" )
    assert exc_info.value.status_code == 503
    assert "prose engine not loaded" in exc_info.value.detail


# ── /embeddings/info ────────────────────────────────────────────────────────


def test_embeddings_info_returns_metadata_with_valid_key( client ):
    from lupin_model_server import main as ms

    plaintext = _set_valid_api_key_hash()
    ms._state.models_loaded = [ "code_rank_embed", "nomic_embed_text_v1_5" ]

    resp = client.get( "/embeddings/info", headers={ "X-API-Key": plaintext } )
    assert resp.status_code == 200
    body = resp.json()
    assert "code_model"   in body
    assert "prose_model"  in body
    assert body[ "code_loaded" ]  is True
    assert body[ "prose_loaded" ] is True


def test_embeddings_info_returns_401_without_key( client ):
    _set_valid_api_key_hash()

    resp = client.get( "/embeddings/info" )
    assert resp.status_code == 401


def test_embeddings_info_returns_503_when_hash_not_loaded( client ):
    # api_key_hash is None (reset fixture)
    resp = client.get( "/embeddings/info", headers={ "X-API-Key": "ck_live_" + "x" * 64 } )
    assert resp.status_code == 503


# ── /admin/metrics ──────────────────────────────────────────────────────────


def test_admin_metrics_returns_prometheus_text_with_valid_key( client ):
    plaintext = _set_valid_api_key_hash()
    resp = client.get( "/admin/metrics", headers={ "X-API-Key": plaintext } )
    assert resp.status_code == 200
    assert "model_server_requests_total" in resp.text
    assert resp.headers[ "content-type" ].startswith( "text/plain" )


def test_admin_metrics_returns_401_without_key( client ):
    _set_valid_api_key_hash()
    resp = client.get( "/admin/metrics" )
    assert resp.status_code == 401


# ── /transcribe decode kwargs (row 05ddc8f0) ────────────────────────────────


def _ready_state_with_pipeline( pipeline ):
    from lupin_model_server import main as ms

    ms._state.models_loaded    = [ "whisper", "code_rank_embed", "nomic_embed_text_v1_5" ]
    ms._state.whisper_pipeline = pipeline
    return _set_valid_api_key_hash()


def test_transcribe_decodes_with_timestamps_on( client ):
    """
    Without return_timestamps the model ends the transcript at the first pause on
    noisy audio (row 05ddc8f0). The kwargs are pinned to LITERALS, not to the
    module constant, so emptying the constant reddens this test.
    """
    pipeline = MagicMock( return_value={ "text": "Testing, testing. One, two, three." } )
    key      = _ready_state_with_pipeline( pipeline )

    resp = client.post( "/transcribe", headers={ "x-api-key": key }, files={ "audio": ( "a.wav", b"RIFF", "audio/wav" ) } )

    assert resp.status_code == 200
    assert resp.json() == { "text": "Testing, testing. One, two, three." }
    assert pipeline.call_count == 1
    assert pipeline.call_args.kwargs == { "chunk_length_s": 30, "stride_length_s": 5, "return_timestamps": True }


def test_transcribe_oom_retry_decodes_with_the_same_kwargs( client ):
    """The CUDA-OOM retry must not fall back to the old kwargs — both calls share one dict."""
    import torch

    pipeline = MagicMock( side_effect=[ torch.cuda.OutOfMemoryError( "oom" ), { "text": "after retry" } ] )
    key      = _ready_state_with_pipeline( pipeline )

    with patch( "torch.cuda.empty_cache" ):
        resp = client.post( "/transcribe", headers={ "x-api-key": key }, files={ "audio": ( "a.wav", b"RIFF", "audio/wav" ) } )

    assert resp.status_code == 200
    assert resp.json() == { "text": "after retry" }
    assert pipeline.call_count == 2
    expected = { "chunk_length_s": 30, "stride_length_s": 5, "return_timestamps": True }
    assert [ c.kwargs for c in pipeline.call_args_list ] == [ expected, expected ]


# ── role on /embeddings/{generate,batch} and the engines block of /embeddings/info ──────────────────


import torch


class FakeEncoder:
    """A stand-in engine: records what it was asked, answers with fixed pooled vectors."""

    def __init__( self, width=4, dtype=torch.float16, device="cpu" ):
        self.calls  = []
        self.width  = width
        self.dtype  = dtype
        self.device = device
        self.auto_model = MagicMock()
        self.auto_model.config._commit_hash = "abc123"

    def __getitem__( self, i ):
        return self

    def parameters( self ):
        yield torch.zeros( 1, dtype=self.dtype, device=self.device )

    def encode( self, texts, convert_to_tensor=False, normalize_embeddings=False ):
        self.calls.append( { "texts": list( texts ), "tensor": convert_to_tensor, "normalize": normalize_embeddings } )
        rows = torch.tensor( [ [ float( i + 1 ), 2.0, 0.0, 4.0 ] for i in range( len( texts ) ) ] )
        return rows if convert_to_tensor else MagicMock( tolist=lambda: rows.tolist() )


def _loaded( code=None, prose=None ):
    from lupin_model_server import main as ms
    ms._state.code_engine  = code if code is not None else FakeEncoder()
    ms._state.prose_engine = prose if prose is not None else FakeEncoder()
    return ms


def _post( client, path, plaintext, **body ):
    return client.post( path, json=body, headers={ "X-API-Key": plaintext } )


def test_batch_without_a_role_is_the_original_path_and_echoes_none( client ):
    ms = _loaded()
    key = _set_valid_api_key_hash()
    resp = _post( client, "/embeddings/batch", key, texts=[ "a", "b" ], content_type="prose" )
    assert resp.status_code == 200
    body = resp.json()
    assert body[ "role" ] is None and body[ "count" ] == 2
    assert ms._state.prose_engine.calls == [ { "texts": [ "a", "b" ], "tensor": False, "normalize": False } ]


def test_batch_code_query_prefixes_the_text_and_document_does_not( client ):
    ms = _loaded()
    key = _set_valid_api_key_hash()
    q = _post( client, "/embeddings/batch", key, texts=[ "find x" ], content_type="code", role="query" )
    d = _post( client, "/embeddings/batch", key, texts=[ "def x" ], content_type="code", role="document" )
    assert q.json()[ "role" ] == "query" and d.json()[ "role" ] == "document"
    assert ms._state.code_engine.calls == [
        { "texts": [ f"{ms.CODE_QUERY_PREFIX} find x" ], "tensor": False, "normalize": True },
        { "texts": [ "def x" ], "tensor": False, "normalize": True } ]


def test_batch_prose_roles_use_their_own_prefix_and_the_layer_norm_truncate_normalize_steps( client, monkeypatch ):
    ms = _loaded()
    monkeypatch.setattr( ms, "PROSE_MATRYOSHKA_DIM", 2 )
    key = _set_valid_api_key_hash()
    q = _post( client, "/embeddings/batch", key, texts=[ "t" ], content_type="prose", role="query" )
    d = _post( client, "/embeddings/batch", key, texts=[ "t" ], content_type="prose", role="document" )
    assert [ c[ "texts" ] for c in ms._state.prose_engine.calls ] == [ [ f"{ms.PROSE_QUERY_PREFIX} t" ], [ f"{ms.PROSE_DOCUMENT_PREFIX} t" ] ]
    assert all( c[ "tensor" ] and not c[ "normalize" ] for c in ms._state.prose_engine.calls )
    pooled = torch.tensor( [ [ 1.0, 2.0, 0.0, 4.0 ] ] )
    expect = torch.nn.functional.normalize( torch.nn.functional.layer_norm( pooled, ( 4, ) )[ :, :2 ], p=2, dim=1 ).tolist()[ 0 ]
    got = q.json()[ "embeddings" ][ 0 ]
    assert len( got ) == 2 and got == pytest.approx( expect, abs=1e-6 )
    assert abs( sum( v * v for v in got ) - 1.0 ) < 1e-6
    assert d.json()[ "embeddings" ][ 0 ] == pytest.approx( expect, abs=1e-6 )


def test_generate_carries_the_role_and_returns_one_vector( client ):
    ms = _loaded()
    key = _set_valid_api_key_hash()
    resp = _post( client, "/embeddings/generate", key, text="hello", content_type="code", role="query" )
    body = resp.json()
    assert resp.status_code == 200 and body[ "role" ] == "query" and body[ "dim" ] == 4
    assert ms._state.code_engine.calls[ 0 ][ "texts" ] == [ f"{ms.CODE_QUERY_PREFIX} hello" ]


def test_generate_without_a_role_echoes_none( client ):
    _loaded()
    key = _set_valid_api_key_hash()
    resp = _post( client, "/embeddings/generate", key, text="hello", content_type="prose" )
    assert resp.status_code == 200 and resp.json()[ "role" ] is None


def test_batch_refuses_empty_texts_and_an_unknown_role( client ):
    _loaded()
    key = _set_valid_api_key_hash()
    assert _post( client, "/embeddings/batch", key, texts=[], content_type="prose" ).status_code == 400
    assert _post( client, "/embeddings/batch", key, texts=[ "a" ], content_type="prose", role="other" ).status_code == 422


def test_batch_answers_503_when_the_engine_is_not_loaded( client ):
    from lupin_model_server import main as ms
    key = _set_valid_api_key_hash()
    resp = _post( client, "/embeddings/batch", key, texts=[ "a" ], content_type="code", role="query" )
    assert resp.status_code == 503 and ms._state.code_engine is None


def test_info_reports_engines_with_revision_dtype_device_prefixes_and_libraries( client, monkeypatch ):
    ms = _loaded( code=FakeEncoder( dtype=torch.float16 ), prose=FakeEncoder( dtype=torch.float32 ) )
    monkeypatch.setattr( ms, "_device_class", lambda d: f"class-of-{d}" )
    key = _set_valid_api_key_hash()
    body = client.get( "/embeddings/info", headers={ "X-API-Key": key } ).json()
    eng = body[ "engines" ]
    assert eng[ "code" ][ "revision" ] == "abc123" and eng[ "prose" ][ "revision" ] == "abc123"
    assert eng[ "code" ][ "dtype" ] == "float16" and eng[ "prose" ][ "dtype" ] == "float32"
    assert eng[ "code" ][ "query_prefix" ] == ms.CODE_QUERY_PREFIX and eng[ "code" ][ "document_prefix" ] == ""
    assert eng[ "prose" ][ "document_prefix" ] == ms.PROSE_DOCUMENT_PREFIX
    assert eng[ "prose" ][ "dimensions" ] == ms.PROSE_MATRYOSHKA_DIM
    assert eng[ "code" ][ "loaded" ] is True and eng[ "device_class" ] == f"class-of-{ms.DEVICE}"
    assert set( eng[ "libraries" ] ) == { "torch", "transformers", "sentence-transformers", "numpy" }


def test_info_reports_a_null_revision_for_an_engine_that_is_not_loaded( client ):
    key = _set_valid_api_key_hash()
    body = client.get( "/embeddings/info", headers={ "X-API-Key": key } ).json()
    assert body[ "engines" ][ "code" ][ "revision" ] is None and body[ "engines" ][ "code" ][ "loaded" ] is False
    assert body[ "engines" ][ "code" ][ "dtype" ] is None


def test_device_class_names_the_card_when_cuda_is_available_and_the_string_otherwise( monkeypatch ):
    from lupin_model_server import main as ms
    assert ms._device_class( "cpu" ) == "cpu"
    monkeypatch.setattr( ms.torch.cuda, "is_available", lambda: False )
    assert ms._device_class( "cuda:0" ) == "cuda:0"
    monkeypatch.setattr( ms.torch.cuda, "is_available", lambda: True )
    monkeypatch.setattr( ms.torch.cuda, "get_device_capability", lambda d: ( 8, 9 ) )
    monkeypatch.setattr( ms.torch.cuda, "get_device_name", lambda d: "Card" )
    assert ms._device_class( "cuda:1" ) == "Card, sm_89"


def test_library_versions_returns_none_for_a_missing_package( monkeypatch ):
    from importlib import metadata
    from lupin_model_server import main as ms

    def fake_version( name ):
        if name == "numpy": raise metadata.PackageNotFoundError( name )
        return "1.0"

    monkeypatch.setattr( metadata, "version", fake_version )
    assert ms._library_versions() == { "torch": "1.0", "transformers": "1.0", "sentence-transformers": "1.0", "numpy": None }
