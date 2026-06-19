"""
Carveout-scoped unit tests for `cosa.rest.routers.speech` — Phase 5.5 of the
2026-05-16 model-server carve-out (Q9 hybrid ratification: carveout-scoped
on this modified router file).

Surfaces covered (carveout-only):
    - `_run_whisper_with_retry` (DEPRECATED but retained for one release cycle —
      OOM-retry contract preservation per Q13 ratification)
    - `save_upload_to_temp` (Phase 3.5 helper extraction)
    - `get_whisper_pipeline` (post-carveout fallback-to-None semantics)
    - `get_speech_provider` (Phase 3.3 Depends helper)

NOT covered here (legacy routes outside the carveout intent):
    - Full TestClient round-trip on `/api/upload-and-transcribe-*` (those
      hit live Whisper at the smoke tier via `test_model_server_smoke.py`)
"""

import sys
import types
from unittest.mock import MagicMock, patch

import pytest


# ── _run_whisper_with_retry (Q13 contract preservation) ─────────────────────


def test_run_whisper_with_retry_returns_result_on_first_success():
    from cosa.rest.routers.speech import _run_whisper_with_retry

    pipeline = MagicMock( return_value={ "text": "first try success" } )
    result = _run_whisper_with_retry( pipeline, "/tmp/audio.mp3" )
    assert result == { "text": "first try success" }
    assert pipeline.call_count == 1


def test_run_whisper_with_retry_retries_once_on_cuda_oom():
    """Q13 contract: one retry on CUDA OOM, gc + empty_cache between."""
    import torch

    from cosa.rest.routers.speech import _run_whisper_with_retry

    call_count = [ 0 ]

    def _pipeline( path, **kwargs ):
        call_count[ 0 ] += 1
        if call_count[ 0 ] == 1:
            raise torch.cuda.OutOfMemoryError( "fake OOM" )
        return { "text": "recovered" }

    with patch( "cosa.rest.routers.speech.gc.collect" ) as mock_gc, \
         patch( "cosa.rest.routers.speech.torch.cuda.empty_cache" ) as mock_empty:
        result = _run_whisper_with_retry( _pipeline, "/tmp/a.mp3" )

    assert result == { "text": "recovered" }
    assert call_count[ 0 ] == 2
    mock_gc.assert_called_once()
    mock_empty.assert_called_once()


def test_run_whisper_with_retry_propagates_oom_when_retry_fails():
    import torch

    from cosa.rest.routers.speech import _run_whisper_with_retry

    def _pipeline( path, **kwargs ):
        raise torch.cuda.OutOfMemoryError( "perma-OOM" )

    with patch( "cosa.rest.routers.speech.gc.collect" ), \
         patch( "cosa.rest.routers.speech.torch.cuda.empty_cache" ):
        with pytest.raises( torch.cuda.OutOfMemoryError ):
            _run_whisper_with_retry( _pipeline, "/tmp/a.mp3" )


def test_run_whisper_with_retry_debug_print_on_oom( capsys ):
    """Debug-gated print fires on the OOM branch."""
    import torch

    from cosa.rest.routers.speech import _run_whisper_with_retry

    call_count = [ 0 ]

    def _pipeline( path, **kwargs ):
        call_count[ 0 ] += 1
        if call_count[ 0 ] == 1:
            raise torch.cuda.OutOfMemoryError( "fake OOM" )
        return { "text": "ok" }

    with patch( "cosa.rest.routers.speech.gc.collect" ), \
         patch( "cosa.rest.routers.speech.torch.cuda.empty_cache" ):
        _run_whisper_with_retry( _pipeline, "/tmp/a.mp3", debug=True )

    captured = capsys.readouterr()
    assert "CUDA OOM on Whisper inference" in captured.out


# ── save_upload_to_temp (Phase 3.5 helper) ──────────────────────────────────


def test_save_upload_to_temp_writes_content( tmp_path, monkeypatch ):
    from cosa.rest.routers.speech import save_upload_to_temp

    # Redirect /tmp to tmp_path for hermetic testing
    monkeypatch.setattr( "uuid.uuid4", lambda: "fixed-uuid" )

    upload_file = MagicMock( filename="test.mp3" )
    content     = b"fake-audio-bytes"

    with patch( "builtins.open", create=False ) as mock_open:
        mock_file = MagicMock()
        mock_open.return_value.__enter__.return_value = mock_file
        path = save_upload_to_temp( upload_file, content )

    assert path == "/tmp/fixed-uuid-test.mp3"
    mock_open.assert_called_once_with( "/tmp/fixed-uuid-test.mp3", "wb" )
    mock_file.write.assert_called_once_with( content )


# ── get_whisper_pipeline (post-carveout semantics) ──────────────────────────


def test_get_whisper_pipeline_returns_pipeline_when_present( monkeypatch ):
    from cosa.rest.routers import speech as speech_module

    # Build a fake lupin_app.main module exposing a whisper_pipeline attr
    fake_main = types.ModuleType( "lupin_app.main" )
    fake_main.whisper_pipeline = "fake-pipeline-handle"

    monkeypatch.setitem( sys.modules, "lupin_app", types.ModuleType( "lupin_app" ) )
    monkeypatch.setitem( sys.modules, "lupin_app.main", fake_main )

    result = speech_module.get_whisper_pipeline()
    assert result == "fake-pipeline-handle"


def test_get_whisper_pipeline_returns_none_when_attr_missing( monkeypatch ):
    """Remote mode: main module has no whisper_pipeline → None per post-carveout contract."""
    from cosa.rest.routers import speech as speech_module

    fake_main = types.ModuleType( "lupin_app.main" )
    # No whisper_pipeline attr set

    monkeypatch.setitem( sys.modules, "lupin_app", types.ModuleType( "lupin_app" ) )
    monkeypatch.setitem( sys.modules, "lupin_app.main", fake_main )

    result = speech_module.get_whisper_pipeline()
    assert result is None


# ── get_speech_provider (Phase 3.3) ─────────────────────────────────────────


def test_get_speech_provider_returns_provider_instance(
    reset_speech_provider_singleton, monkeypatch
):
    from cosa.rest.routers import speech as speech_module
    from cosa.memory.speech_to_text_provider import SpeechToTextProvider

    # Mock the underlying ConfigurationManager inside the provider's init
    cfg = MagicMock()
    cfg.get.side_effect = lambda key, default=None, **kw: (
        "local" if key == "speech to text provider" else default
    )
    monkeypatch.setattr(
        "cosa.memory.speech_to_text_provider.ConfigurationManager",
        lambda **kwargs: cfg,
    )

    # Fake main module with debug + verbose attrs
    fake_main = types.ModuleType( "lupin_app.main" )
    fake_main.app_debug   = True
    fake_main.app_verbose = False

    monkeypatch.setitem( sys.modules, "lupin_app", types.ModuleType( "lupin_app" ) )
    monkeypatch.setitem( sys.modules, "lupin_app.main", fake_main )

    provider = speech_module.get_speech_provider()
    assert isinstance( provider, SpeechToTextProvider )


def test_get_speech_provider_defaults_when_main_missing_attrs(
    reset_speech_provider_singleton, monkeypatch
):
    """If main module lacks debug/verbose attrs, getattr falls back to False defaults."""
    from cosa.rest.routers import speech as speech_module
    from cosa.memory.speech_to_text_provider import SpeechToTextProvider

    cfg = MagicMock()
    cfg.get.side_effect = lambda key, default=None, **kw: (
        "local" if key == "speech to text provider" else default
    )
    monkeypatch.setattr(
        "cosa.memory.speech_to_text_provider.ConfigurationManager",
        lambda **kwargs: cfg,
    )

    # Fake main module WITHOUT debug/verbose attrs
    fake_main = types.ModuleType( "lupin_app.main" )

    monkeypatch.setitem( sys.modules, "lupin_app", types.ModuleType( "lupin_app" ) )
    monkeypatch.setitem( sys.modules, "lupin_app.main", fake_main )

    provider = speech_module.get_speech_provider()
    assert isinstance( provider, SpeechToTextProvider )
