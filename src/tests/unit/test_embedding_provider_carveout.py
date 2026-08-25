"""
Carveout-scoped unit tests for `cosa.memory.embedding_provider.EmbeddingProvider`.

Phase 5.4 of the 2026-05-16 model-server carve-out (per Q9 hybrid ratification:
carveout-scoped 100% coverage on this modified file — tests target the new
surfaces only, not the legacy ones).

Carveout-modified surfaces covered here:
    - `_is_in_process_engine_owner` class flag
    - `declare_in_process_engine_owner` class method
    - `_resolve_model_server_url` static method (NEW)
    - `_http_api_key` static method (touched 2026-05-16 — same `ck_live_*`
      namespace per María's brief)
    - `_resolve_http_target` class method (NEW)

See:
    - src/rnd/v0.1.7/2026.05.16-model-server-carveout/01-design.md
    - src/rnd/v0.1.7/2026.05.16-model-server-carveout/02-phase5-unit-tests-and-coverage-design.md §5
"""

from unittest.mock import MagicMock

import pytest


# ── declare_in_process_engine_owner ─────────────────────────────────────────


def test_declare_in_process_engine_owner_sets_flag( reset_embedding_provider_singleton ):
    from cosa.memory.embedding_provider import EmbeddingProvider

    EmbeddingProvider.declare_in_process_engine_owner()
    assert EmbeddingProvider._is_in_process_engine_owner is True


def test_declare_in_process_engine_owner_is_idempotent( reset_embedding_provider_singleton ):
    from cosa.memory.embedding_provider import EmbeddingProvider

    EmbeddingProvider.declare_in_process_engine_owner()
    EmbeddingProvider.declare_in_process_engine_owner()
    assert EmbeddingProvider._is_in_process_engine_owner is True


# ── _resolve_model_server_url ───────────────────────────────────────────────


def test_resolve_model_server_url_returns_env_when_set( monkeypatch ):
    from cosa.memory.embedding_provider import EmbeddingProvider

    monkeypatch.setenv( "LUPIN_MODEL_SERVER_URL", "http://test-env:9999" )
    assert EmbeddingProvider._resolve_model_server_url() == "http://test-env:9999"


def test_resolve_model_server_url_strips_env_whitespace( monkeypatch ):
    from cosa.memory.embedding_provider import EmbeddingProvider

    monkeypatch.setenv( "LUPIN_MODEL_SERVER_URL", "  http://strip-me:8888  " )
    assert EmbeddingProvider._resolve_model_server_url() == "http://strip-me:8888"


def test_resolve_model_server_url_falls_back_to_ini_when_env_unset( monkeypatch ):
    from cosa.memory.embedding_provider import EmbeddingProvider

    monkeypatch.delenv( "LUPIN_MODEL_SERVER_URL", raising=False )

    cfg = MagicMock()
    cfg.get.side_effect = lambda key, default=None, silent=False, **kw: (
        "http://ini-fallback:7998" if key == "model server url" else default
    )
    # _resolve_model_server_url constructs ConfigurationManager inside the
    # function body via a local import, so we patch at the import site.
    monkeypatch.setattr(
        "cosa.config.configuration_manager.ConfigurationManager",
        lambda **kwargs: cfg,
    )
    assert EmbeddingProvider._resolve_model_server_url() == "http://ini-fallback:7998"


def test_resolve_model_server_url_returns_none_when_both_unset( monkeypatch ):
    from cosa.memory.embedding_provider import EmbeddingProvider

    monkeypatch.delenv( "LUPIN_MODEL_SERVER_URL", raising=False )

    cfg = MagicMock()
    cfg.get.side_effect = lambda key, default=None, silent=False, **kw: default

    monkeypatch.setattr(
        "cosa.config.configuration_manager.ConfigurationManager",
        lambda **kwargs: cfg,
    )
    assert EmbeddingProvider._resolve_model_server_url() is None


def test_resolve_model_server_url_returns_none_on_config_manager_error( monkeypatch ):
    from cosa.memory.embedding_provider import EmbeddingProvider

    monkeypatch.delenv( "LUPIN_MODEL_SERVER_URL", raising=False )

    def _raises( **kwargs ):
        raise RuntimeError( "config-load-failure" )

    monkeypatch.setattr(
        "cosa.config.configuration_manager.ConfigurationManager",
        _raises,
    )
    # MUST NOT re-raise
    assert EmbeddingProvider._resolve_model_server_url() is None


def test_resolve_model_server_url_resolves_cloud_run_https_and_env_wins( monkeypatch ):
    """
    Local → Cloud Run 'transmogrification': a Cloud Run https URL via the
    LUPIN_MODEL_SERVER_URL env override resolves verbatim AND wins over a
    local `model server url` INI value — the env-switch from a local GPU
    container to the scale-to-zero Cloud Run service is this single value.

    See: src/rnd/v0.1.9/2026.06.30-gpu-model-server-cloud-run-split/01-design.md
    """
    from cosa.memory.embedding_provider import EmbeddingProvider

    cloud_url = "https://lupin-model-server-abcd1234-uc.a.run.app"
    monkeypatch.setenv( "LUPIN_MODEL_SERVER_URL", cloud_url )

    cfg = MagicMock()
    cfg.get.side_effect = lambda key, default=None, silent=False, **kw: (
        "http://lupin-model-server:7998" if key == "model server url" else default
    )
    monkeypatch.setattr(
        "cosa.config.configuration_manager.ConfigurationManager",
        lambda **kwargs: cfg,
    )
    assert EmbeddingProvider._resolve_model_server_url() == cloud_url


# ── _http_api_key ───────────────────────────────────────────────────────────


def test_http_api_key_returns_value_when_get_api_key_succeeds( monkeypatch ):
    from cosa.memory.embedding_provider import EmbeddingProvider

    monkeypatch.setattr(
        "cosa.memory.embedding_provider.du.get_api_key",
        lambda name, **kw: "ck_live_test_xyz",
    )
    assert EmbeddingProvider._http_api_key() == "ck_live_test_xyz"


def test_http_api_key_returns_none_when_get_api_key_raises( monkeypatch ):
    from cosa.memory.embedding_provider import EmbeddingProvider

    def _raises( name, **kw ):
        raise FileNotFoundError( "no file" )

    monkeypatch.setattr(
        "cosa.memory.embedding_provider.du.get_api_key",
        _raises,
    )
    assert EmbeddingProvider._http_api_key() is None


# ── _resolve_http_target ────────────────────────────────────────────────────


def test_resolve_http_target_returns_model_server_when_url_set( monkeypatch ):
    """When model-server URL resolves, target is (model-server URL, key, /embeddings)."""
    from cosa.memory.embedding_provider import EmbeddingProvider

    monkeypatch.setenv( "LUPIN_MODEL_SERVER_URL", "http://model-srv:7998" )
    monkeypatch.setattr(
        "cosa.memory.embedding_provider.du.get_api_key",
        lambda name, **kw: "ck_live_xyz",
    )
    base, key, prefix = EmbeddingProvider._resolve_http_target()
    assert base   == "http://model-srv:7998"
    assert key    == "ck_live_xyz"
    assert prefix == "/embeddings"


def test_resolve_http_target_falls_back_to_fastapi_when_model_server_unset( monkeypatch ):
    """When model-server URL is None, target is (FastAPI URL, key, /api/embeddings)."""
    from cosa.memory.embedding_provider import EmbeddingProvider

    monkeypatch.delenv( "LUPIN_MODEL_SERVER_URL", raising=False )
    monkeypatch.setenv( "LUPIN_APP_SERVER_URL", "http://fastapi-srv:7999" )

    cfg = MagicMock()
    cfg.get.side_effect = lambda key, default=None, silent=False, **kw: default

    monkeypatch.setattr(
        "cosa.config.configuration_manager.ConfigurationManager",
        lambda **kwargs: cfg,
    )
    monkeypatch.setattr(
        "cosa.memory.embedding_provider.du.get_api_key",
        lambda name, **kw: "ck_live_fastapi",
    )

    base, key, prefix = EmbeddingProvider._resolve_http_target()
    assert base   == "http://fastapi-srv:7999"
    assert key    == "ck_live_fastapi"
    assert prefix == "/api/embeddings"


# ── _resolve_server_url (FastAPI URL resolution — touched by carveout) ──────


def test_resolve_server_url_returns_env_when_set( monkeypatch ):
    from cosa.memory.embedding_provider import EmbeddingProvider

    monkeypatch.setenv( "LUPIN_APP_SERVER_URL", "http://fastapi-test:9999" )
    assert EmbeddingProvider._resolve_server_url() == "http://fastapi-test:9999"


def test_resolve_server_url_returns_default_when_env_unset( monkeypatch ):
    from cosa.memory.embedding_provider import EmbeddingProvider

    monkeypatch.delenv( "LUPIN_APP_SERVER_URL", raising=False )
    assert EmbeddingProvider._resolve_server_url() == "http://localhost:7999"


def test_resolve_server_url_strips_env_whitespace( monkeypatch ):
    from cosa.memory.embedding_provider import EmbeddingProvider

    monkeypatch.setenv( "LUPIN_APP_SERVER_URL", "  http://wsp:7999  " )
    assert EmbeddingProvider._resolve_server_url() == "http://wsp:7999"
