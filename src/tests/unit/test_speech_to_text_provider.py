"""
Unit tests for `cosa.memory.speech_to_text_provider.SpeechToTextProvider`.

Phase 5 of the 2026-05-16 model-server carve-out.

Coverage target: 100% line + branch + function on
`src/cosa/memory/speech_to_text_provider.py` (modulo the two existing
`pragma: no cover` markers at L255 and L257 which mark genuinely-unreachable
defensive paths inside `_call_with_retry`).

See:
    - src/rnd/v0.1.7/2026.05.16-model-server-carveout/01-design.md
    - src/rnd/v0.1.7/2026.05.16-model-server-carveout/02-phase5-unit-tests-and-coverage-design.md
"""

from unittest.mock import MagicMock, patch

import pytest
import requests


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_mock_config_mgr( provider="local", url=None ):
    """
    Build a MagicMock ConfigurationManager whose `.get` returns the supplied
    `provider` for the speech-provider INI key and the supplied `url` for
    the model-server-URL key (or the caller-supplied default otherwise).
    """
    mock = MagicMock()

    def _get( key, default=None, silent=False, **kwargs ):
        if key == "speech to text provider":
            return provider
        if key == "model server url":
            return url if url is not None else default
        return default

    mock.get.side_effect = _get
    return mock


@pytest.fixture
def mock_config_local( monkeypatch ):
    """Patch ConfigurationManager so `__init__` resolves provider='local'."""
    cfg = _make_mock_config_mgr( provider="local" )
    monkeypatch.setattr(
        "cosa.memory.speech_to_text_provider.ConfigurationManager",
        lambda **kwargs: cfg,
    )
    return cfg


@pytest.fixture
def mock_config_model_server( monkeypatch ):
    """Patch ConfigurationManager so `__init__` resolves provider='model-server'."""
    cfg = _make_mock_config_mgr( provider="model-server" )
    monkeypatch.setattr(
        "cosa.memory.speech_to_text_provider.ConfigurationManager",
        lambda **kwargs: cfg,
    )
    return cfg


# ── §3.1 Singleton + init ───────────────────────────────────────────────────


def test_singleton_returns_same_instance_across_calls(
    reset_speech_provider_singleton, mock_config_local
):
    from cosa.memory.speech_to_text_provider import SpeechToTextProvider
    p1 = SpeechToTextProvider()
    p2 = SpeechToTextProvider()
    assert p1 is p2


def test_singleton_double_checked_locking_inner_branch(
    reset_speech_provider_singleton, mock_config_local
):
    """
    Cover the inner `if cls._instance is None` False branch in `__new__`
    (the double-checked locking pattern: another thread set _instance
    while we were waiting for the lock).
    """
    from cosa.memory.speech_to_text_provider import SpeechToTextProvider

    original_lock      = SpeechToTextProvider._lock
    race_set_sentinel  = object()

    class _RaceLock:
        def __enter__( self ):
            # Simulate another thread having set the instance between the
            # outer `if cls._instance is None` check and our lock acquisition.
            SpeechToTextProvider._instance = race_set_sentinel
            return None

        def __exit__( self, *args ):
            return False

    SpeechToTextProvider._lock = _RaceLock()
    try:
        result = SpeechToTextProvider.__new__( SpeechToTextProvider )
        # Inner `if cls._instance is None` was False → we return the
        # race-set sentinel rather than creating a fresh instance.
        assert result is race_set_sentinel
    finally:
        SpeechToTextProvider._lock = original_lock


def test_init_runs_once_even_with_multiple_constructions(
    reset_speech_provider_singleton, monkeypatch
):
    construction_count = [ 0 ]

    def mock_constructor( **kwargs ):
        construction_count[ 0 ] += 1
        return _make_mock_config_mgr( provider="local" )

    monkeypatch.setattr(
        "cosa.memory.speech_to_text_provider.ConfigurationManager",
        mock_constructor,
    )
    from cosa.memory.speech_to_text_provider import SpeechToTextProvider
    SpeechToTextProvider()
    SpeechToTextProvider()
    SpeechToTextProvider()
    assert construction_count[ 0 ] == 1


def test_init_reads_provider_from_ini_lowercased_stripped(
    reset_speech_provider_singleton, monkeypatch
):
    cfg = _make_mock_config_mgr( provider="  MODEL-SERVER  " )
    monkeypatch.setattr(
        "cosa.memory.speech_to_text_provider.ConfigurationManager",
        lambda **kwargs: cfg,
    )
    from cosa.memory.speech_to_text_provider import SpeechToTextProvider
    p = SpeechToTextProvider()
    assert p._provider == "model-server"


def test_init_defaults_provider_to_local_when_ini_returns_default(
    reset_speech_provider_singleton, monkeypatch
):
    cfg = MagicMock()
    cfg.get.side_effect = lambda key, default=None, **kw: default
    monkeypatch.setattr(
        "cosa.memory.speech_to_text_provider.ConfigurationManager",
        lambda **kwargs: cfg,
    )
    from cosa.memory.speech_to_text_provider import SpeechToTextProvider
    p = SpeechToTextProvider()
    assert p._provider == "local"


def test_debug_prints_init_state_when_debug_true(
    reset_speech_provider_singleton, mock_config_local, capsys
):
    from cosa.memory.speech_to_text_provider import SpeechToTextProvider
    SpeechToTextProvider( debug=True )
    captured = capsys.readouterr()
    assert "[SpeechToTextProvider] init" in captured.out
    assert "provider=" in captured.out
    assert "owner=" in captured.out


def test_no_debug_print_when_debug_false(
    reset_speech_provider_singleton, mock_config_local, capsys
):
    from cosa.memory.speech_to_text_provider import SpeechToTextProvider
    SpeechToTextProvider( debug=False )
    captured = capsys.readouterr()
    assert "[SpeechToTextProvider] init" not in captured.out


# ── §3.2 Owner-flag class methods ───────────────────────────────────────────


def test_declare_in_process_owner_sets_flag( reset_speech_provider_singleton ):
    from cosa.memory.speech_to_text_provider import SpeechToTextProvider
    SpeechToTextProvider.declare_in_process_owner()
    assert SpeechToTextProvider._is_in_process_owner is True


def test_declare_in_process_owner_is_idempotent( reset_speech_provider_singleton ):
    from cosa.memory.speech_to_text_provider import SpeechToTextProvider
    SpeechToTextProvider.declare_in_process_owner()
    SpeechToTextProvider.declare_in_process_owner()
    assert SpeechToTextProvider._is_in_process_owner is True


def test_declare_remote_only_resets_flag( reset_speech_provider_singleton ):
    from cosa.memory.speech_to_text_provider import SpeechToTextProvider
    SpeechToTextProvider._is_in_process_owner = True
    SpeechToTextProvider.declare_remote_only()
    assert SpeechToTextProvider._is_in_process_owner is False


# ── §3.3 URL resolution ─────────────────────────────────────────────────────


def test_url_returns_env_when_set_and_nonempty( monkeypatch ):
    from cosa.memory.speech_to_text_provider import SpeechToTextProvider
    monkeypatch.setenv( "LUPIN_MODEL_SERVER_URL", "http://test:9999" )
    assert SpeechToTextProvider._resolve_model_server_url() == "http://test:9999"


def test_url_strips_env_whitespace( monkeypatch ):
    from cosa.memory.speech_to_text_provider import SpeechToTextProvider
    monkeypatch.setenv( "LUPIN_MODEL_SERVER_URL", "  http://test:9999  " )
    assert SpeechToTextProvider._resolve_model_server_url() == "http://test:9999"


def test_url_falls_back_to_ini_when_env_unset( monkeypatch ):
    from cosa.memory.speech_to_text_provider import SpeechToTextProvider
    monkeypatch.delenv( "LUPIN_MODEL_SERVER_URL", raising=False )
    cfg = _make_mock_config_mgr( provider="local", url="http://ini-url:7998" )
    monkeypatch.setattr(
        "cosa.memory.speech_to_text_provider.ConfigurationManager",
        lambda **kwargs: cfg,
    )
    assert SpeechToTextProvider._resolve_model_server_url() == "http://ini-url:7998"


def test_url_falls_back_to_hardcoded_default_when_ini_returns_empty( monkeypatch ):
    from cosa.memory.speech_to_text_provider import SpeechToTextProvider
    monkeypatch.delenv( "LUPIN_MODEL_SERVER_URL", raising=False )
    cfg = _make_mock_config_mgr( provider="local", url="" )
    monkeypatch.setattr(
        "cosa.memory.speech_to_text_provider.ConfigurationManager",
        lambda **kwargs: cfg,
    )
    assert SpeechToTextProvider._resolve_model_server_url() == "http://lupin-model-server:7998"


def test_url_returns_hardcoded_default_when_config_manager_raises( monkeypatch ):
    from cosa.memory.speech_to_text_provider import SpeechToTextProvider
    monkeypatch.delenv( "LUPIN_MODEL_SERVER_URL", raising=False )

    def _raises( **kwargs ):
        raise RuntimeError( "config-manager-boom" )

    monkeypatch.setattr(
        "cosa.memory.speech_to_text_provider.ConfigurationManager",
        _raises,
    )
    # Must NOT re-raise
    assert SpeechToTextProvider._resolve_model_server_url() == "http://lupin-model-server:7998"


def test_url_returns_env_value_even_when_ini_set( monkeypatch ):
    """Env takes precedence over INI."""
    from cosa.memory.speech_to_text_provider import SpeechToTextProvider
    monkeypatch.setenv( "LUPIN_MODEL_SERVER_URL", "http://env-wins:9999" )
    cfg = _make_mock_config_mgr( provider="local", url="http://ini-loses:7998" )
    monkeypatch.setattr(
        "cosa.memory.speech_to_text_provider.ConfigurationManager",
        lambda **kwargs: cfg,
    )
    assert SpeechToTextProvider._resolve_model_server_url() == "http://env-wins:9999"


# ── §3.4 API-key resolution ─────────────────────────────────────────────────


def test_api_key_returns_string_when_file_present( monkeypatch ):
    from cosa.memory.speech_to_text_provider import SpeechToTextProvider
    monkeypatch.setattr(
        "cosa.memory.speech_to_text_provider.du.get_api_key",
        lambda name, **kw: "ck_live_abc123",
    )
    assert SpeechToTextProvider._model_server_api_key() == "ck_live_abc123"


def test_api_key_returns_none_when_get_api_key_raises( monkeypatch ):
    from cosa.memory.speech_to_text_provider import SpeechToTextProvider

    def _raises( name, **kw ):
        raise FileNotFoundError( "no key file" )

    monkeypatch.setattr(
        "cosa.memory.speech_to_text_provider.du.get_api_key",
        _raises,
    )
    assert SpeechToTextProvider._model_server_api_key() is None


# ── §3.5 Routing decision: `_should_use_local` ──────────────────────────────


@pytest.mark.parametrize(
    "provider_val,owner_flag,expected",
    [
        ( "local",        True,  True ),
        ( "local",        False, False ),
        ( "model-server", True,  False ),
        ( "model-server", False, False ),
    ],
)
def test_should_use_local_matrix(
    reset_speech_provider_singleton,
    monkeypatch,
    provider_val,
    owner_flag,
    expected,
):
    cfg = _make_mock_config_mgr( provider=provider_val )
    monkeypatch.setattr(
        "cosa.memory.speech_to_text_provider.ConfigurationManager",
        lambda **kwargs: cfg,
    )
    from cosa.memory.speech_to_text_provider import SpeechToTextProvider
    SpeechToTextProvider._is_in_process_owner = owner_flag
    p = SpeechToTextProvider()
    assert p._should_use_local() is expected


# ── §3.6 `transcribe()` ─────────────────────────────────────────────────────


def test_transcribe_local_raises_when_no_pipeline_passed(
    reset_speech_provider_singleton, mock_config_local
):
    from cosa.memory.speech_to_text_provider import SpeechToTextProvider
    SpeechToTextProvider._is_in_process_owner = True
    p = SpeechToTextProvider()
    with pytest.raises( RuntimeError, match="local-mode called without whisper_pipeline" ):
        p.transcribe( "/tmp/audio.mp3", whisper_pipeline=None )


def test_transcribe_local_returns_text_from_dict_result(
    reset_speech_provider_singleton, mock_config_local
):
    from cosa.memory.speech_to_text_provider import SpeechToTextProvider
    SpeechToTextProvider._is_in_process_owner = True
    p = SpeechToTextProvider()
    pipeline_mock = MagicMock( return_value={ "text": "hello world", "chunks": [] } )
    result = p.transcribe( "/tmp/audio.mp3", whisper_pipeline=pipeline_mock )
    assert result == "hello world"
    pipeline_mock.assert_called_once_with( "/tmp/audio.mp3" )


def test_transcribe_local_returns_str_from_non_dict_result(
    reset_speech_provider_singleton, mock_config_local
):
    from cosa.memory.speech_to_text_provider import SpeechToTextProvider
    SpeechToTextProvider._is_in_process_owner = True
    p = SpeechToTextProvider()
    pipeline_mock = MagicMock( return_value="raw-string-result" )
    result = p.transcribe( "/tmp/audio.mp3", whisper_pipeline=pipeline_mock )
    assert result == "raw-string-result"


def test_transcribe_forwards_kwargs_to_pipeline(
    reset_speech_provider_singleton, mock_config_local
):
    from cosa.memory.speech_to_text_provider import SpeechToTextProvider
    SpeechToTextProvider._is_in_process_owner = True
    p = SpeechToTextProvider()
    pipeline_mock = MagicMock( return_value={ "text": "ok" } )
    p.transcribe(
        "/tmp/a.mp3",
        whisper_pipeline=pipeline_mock,
        chunk_length_s=30,
        stride_length_s=5,
    )
    pipeline_mock.assert_called_once_with( "/tmp/a.mp3", chunk_length_s=30, stride_length_s=5 )


def test_transcribe_local_retries_once_on_cuda_oom_and_succeeds(
    reset_speech_provider_singleton, mock_config_local
):
    """
    Mirrors the historical `_run_whisper_with_retry` contract (per plan Q4
    ratification): one retry on CUDA OOM, gc + empty_cache between attempts.
    """
    import torch

    from cosa.memory.speech_to_text_provider import SpeechToTextProvider
    SpeechToTextProvider._is_in_process_owner = True
    p = SpeechToTextProvider()

    # First call raises OOM, second succeeds.
    call_count = [ 0 ]

    def _pipeline( path, **kwargs ):
        call_count[ 0 ] += 1
        if call_count[ 0 ] == 1:
            raise torch.cuda.OutOfMemoryError( "fake OOM" )
        return { "text": "recovered" }

    with patch( "gc.collect" ) as mock_gc, patch( "torch.cuda.empty_cache" ) as mock_empty:
        result = p.transcribe( "/tmp/a.mp3", whisper_pipeline=_pipeline )

    assert result == "recovered"
    assert call_count[ 0 ] == 2
    mock_gc.assert_called_once()
    mock_empty.assert_called_once()


def test_transcribe_local_propagates_oom_when_retry_also_fails(
    reset_speech_provider_singleton, mock_config_local
):
    """Second OOM propagates per historical contract."""
    import torch

    from cosa.memory.speech_to_text_provider import SpeechToTextProvider
    SpeechToTextProvider._is_in_process_owner = True
    p = SpeechToTextProvider()

    def _pipeline( path, **kwargs ):
        raise torch.cuda.OutOfMemoryError( "fake OOM, both attempts" )

    with patch( "gc.collect" ), patch( "torch.cuda.empty_cache" ):
        with pytest.raises( torch.cuda.OutOfMemoryError ):
            p.transcribe( "/tmp/a.mp3", whisper_pipeline=_pipeline )


def test_transcribe_oom_debug_print_when_debug_true(
    reset_speech_provider_singleton, mock_config_local, capsys
):
    """Confirm the debug-gated print fires on the OOM retry branch."""
    import torch

    from cosa.memory.speech_to_text_provider import SpeechToTextProvider
    SpeechToTextProvider._is_in_process_owner = True
    p = SpeechToTextProvider( debug=True )
    # capsys captured the init print; clear it.
    capsys.readouterr()

    call_count = [ 0 ]

    def _pipeline( path, **kwargs ):
        call_count[ 0 ] += 1
        if call_count[ 0 ] == 1:
            raise torch.cuda.OutOfMemoryError( "fake OOM" )
        return { "text": "ok" }

    with patch( "gc.collect" ), patch( "torch.cuda.empty_cache" ):
        p.transcribe( "/tmp/a.mp3", whisper_pipeline=_pipeline )

    captured = capsys.readouterr()
    assert "CUDA OOM on local Whisper" in captured.out


def test_transcribe_routes_to_http_when_not_owner(
    reset_speech_provider_singleton, mock_config_local
):
    """provider=local but owner=False → HTTP path."""
    from cosa.memory.speech_to_text_provider import SpeechToTextProvider
    SpeechToTextProvider._is_in_process_owner = False
    p = SpeechToTextProvider()

    with patch.object(
        SpeechToTextProvider, "_transcribe_via_http", return_value="from-http"
    ) as mock_http:
        result = p.transcribe( "/tmp/a.mp3", whisper_pipeline=MagicMock() )

    assert result == "from-http"
    mock_http.assert_called_once()


def test_transcribe_routes_to_http_when_provider_is_model_server(
    reset_speech_provider_singleton, mock_config_model_server
):
    """provider=model-server (any owner flag) → HTTP path."""
    from cosa.memory.speech_to_text_provider import SpeechToTextProvider
    SpeechToTextProvider._is_in_process_owner = True
    p = SpeechToTextProvider()

    with patch.object(
        SpeechToTextProvider, "_transcribe_via_http", return_value="from-http"
    ) as mock_http:
        result = p.transcribe( "/tmp/a.mp3", whisper_pipeline=MagicMock() )

    assert result == "from-http"
    mock_http.assert_called_once()


# ── §3.7 `_call_with_retry` ─────────────────────────────────────────────────


def test_retry_returns_2xx_immediately():
    from cosa.memory.speech_to_text_provider import SpeechToTextProvider
    response = MagicMock( status_code=200 )
    fn = MagicMock( return_value=response )

    result = SpeechToTextProvider._call_with_retry( fn, max_retries=3 )

    assert result is response
    assert fn.call_count == 1


def test_retry_returns_4xx_immediately_without_retry():
    from cosa.memory.speech_to_text_provider import SpeechToTextProvider
    response = MagicMock( status_code=422 )
    fn = MagicMock( return_value=response )

    with patch( "time.sleep" ) as mock_sleep:
        result = SpeechToTextProvider._call_with_retry( fn, max_retries=3 )

    assert result is response
    assert fn.call_count == 1
    mock_sleep.assert_not_called()


def test_retry_sleeps_and_retries_on_5xx_then_succeeds():
    from cosa.memory.speech_to_text_provider import SpeechToTextProvider
    resp_503 = MagicMock( status_code=503 )
    resp_200 = MagicMock( status_code=200 )
    fn = MagicMock( side_effect=[ resp_503, resp_200 ] )

    with patch( "time.sleep" ) as mock_sleep:
        result = SpeechToTextProvider._call_with_retry(
            fn, max_retries=3, backoff_seq=( 2, 4, 8 )
        )

    assert result is resp_200
    assert fn.call_count == 2
    mock_sleep.assert_called_once_with( 2 )


def test_retry_returns_5xx_when_all_attempts_exhausted():
    from cosa.memory.speech_to_text_provider import SpeechToTextProvider
    resp_503 = MagicMock( status_code=503 )
    fn = MagicMock( return_value=resp_503 )

    with patch( "time.sleep" ):
        result = SpeechToTextProvider._call_with_retry(
            fn, max_retries=3, backoff_seq=( 0.01, 0.01 )
        )

    # When all attempts return 5xx, the LAST 5xx response is returned
    # (the loop falls through on the final attempt because no sleep gate).
    assert result is resp_503
    assert fn.call_count == 3


def test_retry_sleeps_and_retries_on_timeout_then_succeeds():
    from cosa.memory.speech_to_text_provider import SpeechToTextProvider
    resp_200 = MagicMock( status_code=200 )
    fn = MagicMock( side_effect=[ requests.Timeout( "slow" ), resp_200 ] )

    with patch( "time.sleep" ) as mock_sleep:
        result = SpeechToTextProvider._call_with_retry(
            fn, max_retries=3, backoff_seq=( 0.01, 0.02 )
        )

    assert result is resp_200
    assert fn.call_count == 2
    mock_sleep.assert_called_once_with( 0.01 )


def test_retry_raises_timeout_when_all_attempts_exhausted():
    from cosa.memory.speech_to_text_provider import SpeechToTextProvider
    fn = MagicMock( side_effect=requests.Timeout( "perma-slow" ) )

    with patch( "time.sleep" ):
        with pytest.raises( requests.Timeout ):
            SpeechToTextProvider._call_with_retry(
                fn, max_retries=3, backoff_seq=( 0.01, 0.01 )
            )

    assert fn.call_count == 3


def test_retry_raises_connection_error_when_all_attempts_exhausted():
    from cosa.memory.speech_to_text_provider import SpeechToTextProvider
    fn = MagicMock( side_effect=requests.ConnectionError( "no route" ) )

    with patch( "time.sleep" ):
        with pytest.raises( requests.ConnectionError ):
            SpeechToTextProvider._call_with_retry(
                fn, max_retries=3, backoff_seq=( 0.01, 0.01 )
            )

    assert fn.call_count == 3


def test_retry_uses_backoff_sequence_in_order():
    """Exponential backoff: first sleep uses backoff_seq[0], second uses [1]."""
    from cosa.memory.speech_to_text_provider import SpeechToTextProvider
    resp_503 = MagicMock( status_code=503 )
    resp_200 = MagicMock( status_code=200 )
    fn = MagicMock( side_effect=[ resp_503, resp_503, resp_200 ] )

    with patch( "time.sleep" ) as mock_sleep:
        SpeechToTextProvider._call_with_retry(
            fn, max_retries=3, backoff_seq=( 2, 4, 8 )
        )

    assert mock_sleep.call_args_list == [
        ( ( 2, ), {} ),
        ( ( 4, ), {} ),
    ]


# ── §3.8 `_transcribe_via_http` ─────────────────────────────────────────────


def test_http_raises_when_api_key_missing(
    reset_speech_provider_singleton, mock_config_model_server, monkeypatch
):
    from cosa.memory.speech_to_text_provider import SpeechToTextProvider
    p = SpeechToTextProvider()
    monkeypatch.setattr(
        "cosa.memory.speech_to_text_provider.du.get_api_key",
        lambda name, **kw: ( _ for _ in () ).throw( FileNotFoundError() ),
    )
    with pytest.raises( RuntimeError, match="notification-api-claude-code-dev" ):
        p._transcribe_via_http( "/tmp/a.mp3" )


def test_http_raises_when_audio_file_unreadable(
    reset_speech_provider_singleton, mock_config_model_server, monkeypatch
):
    from cosa.memory.speech_to_text_provider import SpeechToTextProvider
    p = SpeechToTextProvider()
    monkeypatch.setattr(
        "cosa.memory.speech_to_text_provider.du.get_api_key",
        lambda name, **kw: "ck_live_" + "x" * 64,
    )

    def _raise_open( *args, **kwargs ):
        raise OSError( "no such file" )

    monkeypatch.setattr( "builtins.open", _raise_open )

    with pytest.raises( RuntimeError, match="could not read" ):
        p._transcribe_via_http( "/tmp/missing.mp3" )


def test_http_raises_runtime_error_when_call_with_retry_raises_request_exception(
    reset_speech_provider_singleton, mock_config_model_server, monkeypatch, tmp_path
):
    from cosa.memory.speech_to_text_provider import SpeechToTextProvider
    p = SpeechToTextProvider()
    monkeypatch.setattr(
        "cosa.memory.speech_to_text_provider.du.get_api_key",
        lambda name, **kw: "ck_live_" + "x" * 64,
    )

    audio = tmp_path / "a.mp3"
    audio.write_bytes( b"fake-audio" )

    def _raise_request_exc( fn, **kwargs ):
        raise requests.ConnectionError( "boom" )

    monkeypatch.setattr(
        SpeechToTextProvider, "_call_with_retry", staticmethod( _raise_request_exc )
    )

    with pytest.raises( RuntimeError, match="HTTP unreachable" ):
        p._transcribe_via_http( str( audio ) )


def test_http_raises_runtime_error_on_non_200_response(
    reset_speech_provider_singleton, mock_config_model_server, monkeypatch, tmp_path
):
    from cosa.memory.speech_to_text_provider import SpeechToTextProvider
    p = SpeechToTextProvider()
    monkeypatch.setattr(
        "cosa.memory.speech_to_text_provider.du.get_api_key",
        lambda name, **kw: "ck_live_" + "x" * 64,
    )

    audio = tmp_path / "a.mp3"
    audio.write_bytes( b"fake-audio" )

    bad_response = MagicMock( status_code=500, text="boom-detail" )
    monkeypatch.setattr(
        SpeechToTextProvider, "_call_with_retry",
        staticmethod( lambda fn, **kw: bad_response ),
    )

    with pytest.raises( RuntimeError, match="HTTP returned 500" ):
        p._transcribe_via_http( str( audio ) )


def test_http_raises_runtime_error_on_malformed_json(
    reset_speech_provider_singleton, mock_config_model_server, monkeypatch, tmp_path
):
    from cosa.memory.speech_to_text_provider import SpeechToTextProvider
    p = SpeechToTextProvider()
    monkeypatch.setattr(
        "cosa.memory.speech_to_text_provider.du.get_api_key",
        lambda name, **kw: "ck_live_" + "x" * 64,
    )

    audio = tmp_path / "a.mp3"
    audio.write_bytes( b"fake-audio" )

    good_response = MagicMock( status_code=200 )
    good_response.json.side_effect = ValueError( "not json" )
    monkeypatch.setattr(
        SpeechToTextProvider, "_call_with_retry",
        staticmethod( lambda fn, **kw: good_response ),
    )

    with pytest.raises( RuntimeError, match="malformed response" ):
        p._transcribe_via_http( str( audio ) )


def test_http_raises_runtime_error_when_text_key_missing(
    reset_speech_provider_singleton, mock_config_model_server, monkeypatch, tmp_path
):
    from cosa.memory.speech_to_text_provider import SpeechToTextProvider
    p = SpeechToTextProvider()
    monkeypatch.setattr(
        "cosa.memory.speech_to_text_provider.du.get_api_key",
        lambda name, **kw: "ck_live_" + "x" * 64,
    )

    audio = tmp_path / "a.mp3"
    audio.write_bytes( b"fake-audio" )

    good_response = MagicMock( status_code=200 )
    good_response.json.return_value = { "foo": "bar" }
    monkeypatch.setattr(
        SpeechToTextProvider, "_call_with_retry",
        staticmethod( lambda fn, **kw: good_response ),
    )

    with pytest.raises( RuntimeError, match="malformed response" ):
        p._transcribe_via_http( str( audio ) )


def test_http_happy_path_returns_transcribed_text(
    reset_speech_provider_singleton, mock_config_model_server, monkeypatch, tmp_path
):
    from cosa.memory.speech_to_text_provider import SpeechToTextProvider
    p = SpeechToTextProvider()
    monkeypatch.setattr(
        "cosa.memory.speech_to_text_provider.du.get_api_key",
        lambda name, **kw: "ck_live_" + "x" * 64,
    )

    audio = tmp_path / "a.mp3"
    audio.write_bytes( b"fake-audio-bytes" )

    good_response = MagicMock( status_code=200 )
    good_response.json.return_value = { "text": "hello world from http" }
    monkeypatch.setattr(
        SpeechToTextProvider, "_call_with_retry",
        staticmethod( lambda fn, **kw: good_response ),
    )

    result = p._transcribe_via_http( str( audio ) )
    assert result == "hello world from http"


def test_http_posts_to_resolved_url_with_correct_headers(
    reset_speech_provider_singleton, mock_config_model_server, monkeypatch, tmp_path
):
    """
    Confirm the inner _post closure receives the right URL + X-API-Key.

    Implementation detail: we capture the closure argument passed into
    `_call_with_retry`, then invoke it ourselves to inspect the request.
    """
    from cosa.memory.speech_to_text_provider import SpeechToTextProvider
    p = SpeechToTextProvider()
    monkeypatch.setattr(
        "cosa.memory.speech_to_text_provider.du.get_api_key",
        lambda name, **kw: "ck_live_secret_key_value",
    )
    monkeypatch.setenv( "LUPIN_MODEL_SERVER_URL", "http://probe-server:7998" )

    audio = tmp_path / "a.mp3"
    audio.write_bytes( b"fake-audio" )

    # Mock requests.post inside the speech_to_text_provider module's `requests` import
    captured = { "url": None, "headers": None, "files": None }

    def _capture_post( url, files=None, headers=None, timeout=None ):
        captured[ "url" ]     = url
        captured[ "headers" ] = headers
        captured[ "files" ]   = files
        resp = MagicMock( status_code=200 )
        resp.json.return_value = { "text": "ok" }
        return resp

    # Patch requests.post inside the module-level requests import
    import requests as real_requests
    monkeypatch.setattr( real_requests, "post", _capture_post )

    # _call_with_retry just invokes fn() once and returns
    monkeypatch.setattr(
        SpeechToTextProvider, "_call_with_retry",
        staticmethod( lambda fn, **kw: fn() ),
    )

    result = p._transcribe_via_http( str( audio ) )
    assert result == "ok"
    assert captured[ "url" ] == "http://probe-server:7998/transcribe"
    assert captured[ "headers" ][ "X-API-Key" ] == "ck_live_secret_key_value"
    assert "audio" in captured[ "files" ]
