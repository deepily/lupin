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
