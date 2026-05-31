"""
Unit tests for cosa.memory.speech_to_text_provider.SpeechToTextProvider.

SpeechToTextProvider is a thread-safe singleton that routes transcription
requests between an in-process Whisper pipeline and an HTTP proxy to
lupin-model-server. Tests cover:

- Singleton identity + double-checked __init__ guard
- declare_in_process_owner / declare_remote_only class-flag flips
- _should_use_local routing decision matrix
- _resolve_model_server_url (env / INI / default / exception arms)
- _model_server_api_key (success / failure-→-None arm)
- transcribe() local path (missing-pipeline raise, dict/str results, CUDA-OOM retry)
  and the HTTP delegation
- _call_with_retry (success, 5xx-retry, 5xx-exhaust-return, Timeout-retry,
  Timeout-exhaust-raise, 4xx-immediate)
- _transcribe_via_http (no-key / file-read-error / RequestException / non-200 /
  success / malformed-json arms)

SINGLETON HYGIENE: the class caches `_instance` and a class-level
`_is_in_process_owner` flag. setUp/tearDown reset BOTH so tests are order-
independent and do not leak owner state into sibling test modules.

ConfigurationManager / requests / open / torch.cuda / du.get_api_key are all
mocked at the boundary — no real config dependency, network, GPU, or filesystem.

Created 2026-05-31 by Sam 🎙️ (CoSA coverage campaign, memory group, provider/engine lane).
"""

import unittest
from unittest.mock import Mock, patch

from cosa.memory.speech_to_text_provider import SpeechToTextProvider


def _reset_singleton():
    """Clear the cached instance + owner flag so each test starts clean."""
    SpeechToTextProvider._instance            = None
    SpeechToTextProvider._is_in_process_owner = False


def _build_provider( provider_value="local", owner=False, debug=False, verbose=False ):
    """
    Construct a fresh SpeechToTextProvider with ConfigurationManager mocked.

    Args:
        provider_value : raw string the config returns for the provider key
                         (chain .lower().strip() runs on it in __init__)
        owner          : value for the class-level _is_in_process_owner flag
        debug/verbose  : forwarded to the constructor
    """
    _reset_singleton()
    SpeechToTextProvider._is_in_process_owner = owner
    mock_cfg = Mock()
    mock_cfg.get.return_value = provider_value
    with patch( "cosa.memory.speech_to_text_provider.ConfigurationManager", return_value=mock_cfg ):
        return SpeechToTextProvider( debug=debug, verbose=verbose )


class TestSingletonAndInit( unittest.TestCase ):
    """Singleton identity + __init__ guard + class-flag declarations."""

    def setUp( self ):
        _reset_singleton()

    def tearDown( self ):
        _reset_singleton()

    def test_singleton_returns_same_instance( self ):
        """__new__ caches a single instance across constructions."""
        mock_cfg = Mock()
        mock_cfg.get.return_value = "local"
        with patch( "cosa.memory.speech_to_text_provider.ConfigurationManager", return_value=mock_cfg ):
            a = SpeechToTextProvider()
            b = SpeechToTextProvider()
        self.assertIs( a, b )

    def test_init_is_idempotent( self ):
        """The _initialized guard makes a second __init__ a no-op (no config re-read)."""
        mock_cfg = Mock()
        mock_cfg.get.return_value = "model-server"
        with patch( "cosa.memory.speech_to_text_provider.ConfigurationManager", return_value=mock_cfg ) as mock_cm:
            first  = SpeechToTextProvider()
            second = SpeechToTextProvider()    # _initialized already True → early return
        self.assertIs( first, second )
        # ConfigurationManager constructed only ONCE despite two __init__ calls
        mock_cm.assert_called_once()
        self.assertEqual( first._provider, "model-server" )

    def test_init_debug_prints( self ):
        """debug=True prints the init banner line."""
        _reset_singleton()
        mock_cfg = Mock()
        mock_cfg.get.return_value = "local"
        with patch( "cosa.memory.speech_to_text_provider.ConfigurationManager", return_value=mock_cfg ), \
             patch( "builtins.print" ) as mock_print:
            SpeechToTextProvider( debug=True )
        self.assertTrue( mock_print.called )

    def test_provider_value_normalized( self ):
        """The provider key is lower-cased and stripped."""
        provider = _build_provider( provider_value="  MODEL-SERVER  " )
        self.assertEqual( provider._provider, "model-server" )

    def test_declare_in_process_owner_and_remote_only( self ):
        """declare_in_process_owner sets the flag; declare_remote_only clears it."""
        _reset_singleton()
        SpeechToTextProvider.declare_in_process_owner()
        self.assertTrue( SpeechToTextProvider._is_in_process_owner )
        SpeechToTextProvider.declare_remote_only()
        self.assertFalse( SpeechToTextProvider._is_in_process_owner )

    def test_new_double_checked_lock_inner_guard( self ):
        """
        Exercise the inner double-checked-locking guard (the 'another thread won
        the race' arm): _instance is None at the outer check but becomes set
        while acquiring the lock, so the inner `if cls._instance is None` is
        False and __new__ returns the already-created instance.
        """
        _reset_singleton()
        sentinel = Mock()

        class _SettingLock:
            def __enter__( self_lock ):
                # Simulate a competing thread that created the instance first
                SpeechToTextProvider._instance = sentinel
                return self_lock

            def __exit__( self_lock, *exc ):
                return False

        with patch.object( SpeechToTextProvider, "_lock", _SettingLock() ):
            result = SpeechToTextProvider()
        self.assertIs( result, sentinel )


class TestShouldUseLocal( unittest.TestCase ):
    """_should_use_local routing matrix."""

    def tearDown( self ):
        _reset_singleton()

    def test_local_and_owner_true( self ):
        """provider=local AND owner → run locally."""
        provider = _build_provider( provider_value="local", owner=True )
        self.assertTrue( provider._should_use_local() )

    def test_local_but_not_owner_false( self ):
        """provider=local but NOT owner → HTTP path."""
        provider = _build_provider( provider_value="local", owner=False )
        self.assertFalse( provider._should_use_local() )

    def test_model_server_even_if_owner_false( self ):
        """provider=model-server → HTTP path regardless of ownership."""
        provider = _build_provider( provider_value="model-server", owner=True )
        self.assertFalse( provider._should_use_local() )


class TestResolveModelServerUrl( unittest.TestCase ):
    """_resolve_model_server_url env / INI / default / exception arms."""

    def tearDown( self ):
        _reset_singleton()

    def test_env_var_wins( self ):
        """A non-empty LUPIN_MODEL_SERVER_URL is returned (stripped)."""
        with patch.dict( "os.environ", { "LUPIN_MODEL_SERVER_URL": "  http://env-host:9000  " } ):
            url = SpeechToTextProvider._resolve_model_server_url()
        self.assertEqual( url, "http://env-host:9000" )

    def test_ini_used_when_env_unset( self ):
        """Env unset → INI value returned."""
        mock_cfg = Mock()
        mock_cfg.get.return_value = "http://ini-host:7998"
        with patch.dict( "os.environ", { "LUPIN_MODEL_SERVER_URL": "" } ), \
             patch( "cosa.memory.speech_to_text_provider.ConfigurationManager", return_value=mock_cfg ):
            url = SpeechToTextProvider._resolve_model_server_url()
        self.assertEqual( url, "http://ini-host:7998" )

    def test_default_when_ini_blank( self ):
        """Env unset + INI blank → hardcoded default."""
        mock_cfg = Mock()
        mock_cfg.get.return_value = "   "    # strips to empty
        with patch.dict( "os.environ", { "LUPIN_MODEL_SERVER_URL": "" } ), \
             patch( "cosa.memory.speech_to_text_provider.ConfigurationManager", return_value=mock_cfg ):
            url = SpeechToTextProvider._resolve_model_server_url()
        self.assertEqual( url, "http://lupin-model-server:7998" )

    def test_default_when_config_raises( self ):
        """ConfigurationManager raising → default (never raises)."""
        with patch.dict( "os.environ", { "LUPIN_MODEL_SERVER_URL": "" } ), \
             patch( "cosa.memory.speech_to_text_provider.ConfigurationManager",
                    side_effect=Exception( "config boom" ) ):
            url = SpeechToTextProvider._resolve_model_server_url()
        self.assertEqual( url, "http://lupin-model-server:7998" )


class TestModelServerApiKey( unittest.TestCase ):
    """_model_server_api_key success / failure arms."""

    def test_returns_key_on_success( self ):
        """du.get_api_key success → key returned."""
        with patch( "cosa.memory.speech_to_text_provider.du.get_api_key", return_value="ck_live_abc" ):
            self.assertEqual( SpeechToTextProvider._model_server_api_key(), "ck_live_abc" )

    def test_returns_none_on_failure( self ):
        """du.get_api_key raising → None (never raises)."""
        with patch( "cosa.memory.speech_to_text_provider.du.get_api_key",
                    side_effect=Exception( "no key file" ) ):
            self.assertIsNone( SpeechToTextProvider._model_server_api_key() )


class TestTranscribe( unittest.TestCase ):
    """transcribe() local-path branches + HTTP delegation."""

    def tearDown( self ):
        _reset_singleton()

    def test_local_missing_pipeline_raises( self ):
        """Local mode without a whisper_pipeline arg → RuntimeError."""
        provider = _build_provider( provider_value="local", owner=True )
        with self.assertRaises( RuntimeError ):
            provider.transcribe( "/audio.wav", whisper_pipeline=None )

    def test_local_dict_result_returns_text( self ):
        """Local pipeline returning {'text': ...} → the text string."""
        provider = _build_provider( provider_value="local", owner=True )
        pipeline = Mock( return_value={ "text": "hello world" } )
        result = provider.transcribe( "/audio.wav", whisper_pipeline=pipeline )
        self.assertEqual( result, "hello world" )

    def test_local_non_dict_result_stringified( self ):
        """Local pipeline returning a non-dict → str(result)."""
        provider = _build_provider( provider_value="local", owner=True )
        pipeline = Mock( return_value=12345 )
        result = provider.transcribe( "/audio.wav", whisper_pipeline=pipeline )
        self.assertEqual( result, "12345" )

    def test_local_cuda_oom_retries_once( self ):
        """First call OOMs → cache cleared + retried; second call succeeds."""
        import torch
        provider = _build_provider( provider_value="local", owner=True, debug=True )
        pipeline = Mock( side_effect=[ torch.cuda.OutOfMemoryError( "oom" ), { "text": "recovered" } ] )
        with patch( "torch.cuda.empty_cache" ) as mock_empty, \
             patch( "gc.collect" ) as mock_collect, \
             patch( "builtins.print" ):
            result = provider.transcribe( "/audio.wav", whisper_pipeline=pipeline )
        self.assertEqual( result, "recovered" )
        self.assertEqual( pipeline.call_count, 2 )
        mock_empty.assert_called_once()
        mock_collect.assert_called_once()

    def test_local_cuda_oom_retries_debug_off( self ):
        """OOM retry with debug=False → the silent cache-clear arm (no log print)."""
        import torch
        provider = _build_provider( provider_value="local", owner=True, debug=False )
        pipeline = Mock( side_effect=[ torch.cuda.OutOfMemoryError( "oom" ), { "text": "recovered" } ] )
        with patch( "torch.cuda.empty_cache" ) as mock_empty, \
             patch( "gc.collect" ) as mock_collect:
            result = provider.transcribe( "/audio.wav", whisper_pipeline=pipeline )
        self.assertEqual( result, "recovered" )
        mock_empty.assert_called_once()
        mock_collect.assert_called_once()

    def test_http_path_delegates( self ):
        """Non-local routing delegates to _transcribe_via_http."""
        provider = _build_provider( provider_value="model-server", owner=True )
        with patch.object( provider, "_transcribe_via_http", return_value="via http" ) as mock_http:
            result = provider.transcribe( "/audio.wav", chunk_length_s=30 )
        self.assertEqual( result, "via http" )
        mock_http.assert_called_once()


class TestCallWithRetry( unittest.TestCase ):
    """_call_with_retry success / 5xx / transient-exception arms."""

    def _resp( self, status ):
        r = Mock()
        r.status_code = status
        return r

    def test_success_first_try( self ):
        """2xx on the first attempt → returned immediately."""
        ok = self._resp( 200 )
        fn = Mock( return_value=ok )
        result = SpeechToTextProvider._call_with_retry( fn )
        self.assertIs( result, ok )
        fn.assert_called_once()

    def test_4xx_returns_immediately( self ):
        """4xx is non-retryable → returned on the first attempt."""
        not_found = self._resp( 404 )
        fn = Mock( return_value=not_found )
        with patch( "time.sleep" ) as mock_sleep:
            result = SpeechToTextProvider._call_with_retry( fn )
        self.assertIs( result, not_found )
        mock_sleep.assert_not_called()

    def test_5xx_retries_then_succeeds( self ):
        """5xx then 200 → one backoff sleep, then the success response."""
        fn = Mock( side_effect=[ self._resp( 503 ), self._resp( 200 ) ] )
        with patch( "time.sleep" ) as mock_sleep:
            result = SpeechToTextProvider._call_with_retry( fn, max_retries=3, backoff_seq=( 0, 0, 0 ) )
        self.assertEqual( result.status_code, 200 )
        self.assertEqual( fn.call_count, 2 )
        mock_sleep.assert_called_once()

    def test_5xx_exhausts_and_returns_last( self ):
        """Persistent 5xx → last attempt returns the 5xx response (no raise)."""
        fn = Mock( side_effect=[ self._resp( 500 ), self._resp( 500 ) ] )
        with patch( "time.sleep" ):
            result = SpeechToTextProvider._call_with_retry( fn, max_retries=2, backoff_seq=( 0, 0 ) )
        self.assertEqual( result.status_code, 500 )
        self.assertEqual( fn.call_count, 2 )

    def test_timeout_retries_then_succeeds( self ):
        """Timeout then 200 → retried and succeeds."""
        import requests
        fn = Mock( side_effect=[ requests.Timeout( "slow" ), self._resp( 200 ) ] )
        with patch( "time.sleep" ):
            result = SpeechToTextProvider._call_with_retry( fn, max_retries=3, backoff_seq=( 0, 0, 0 ) )
        self.assertEqual( result.status_code, 200 )

    def test_connection_error_exhausts_and_raises( self ):
        """Persistent ConnectionError → last attempt re-raises."""
        import requests
        fn = Mock( side_effect=[ requests.ConnectionError( "down" ), requests.ConnectionError( "down" ) ] )
        with patch( "time.sleep" ):
            with self.assertRaises( requests.ConnectionError ):
                SpeechToTextProvider._call_with_retry( fn, max_retries=2, backoff_seq=( 0, 0 ) )


class TestTranscribeViaHttp( unittest.TestCase ):
    """_transcribe_via_http no-key / read-error / RequestException / non-200 / success / malformed arms."""

    def tearDown( self ):
        _reset_singleton()

    def _provider( self ):
        return _build_provider( provider_value="model-server", owner=False )

    def test_no_api_key_raises( self ):
        """Missing API key → RuntimeError before any HTTP attempt."""
        provider = self._provider()
        with patch.object( provider, "_resolve_model_server_url", return_value="http://host:7998" ), \
             patch.object( provider, "_model_server_api_key", return_value=None ):
            with self.assertRaises( RuntimeError ):
                provider._transcribe_via_http( "/audio.wav" )

    def test_file_read_error_raises( self ):
        """Unreadable audio file → RuntimeError naming the path."""
        provider = self._provider()
        with patch.object( provider, "_resolve_model_server_url", return_value="http://host:7998" ), \
             patch.object( provider, "_model_server_api_key", return_value="ck_live_x" ), \
             patch( "builtins.open", side_effect=OSError( "no such file" ) ):
            with self.assertRaises( RuntimeError ):
                provider._transcribe_via_http( "/missing.wav" )

    def test_request_exception_raises( self ):
        """_call_with_retry raising requests.RequestException → RuntimeError (unreachable)."""
        import requests
        provider = self._provider()
        with patch.object( provider, "_resolve_model_server_url", return_value="http://host:7998" ), \
             patch.object( provider, "_model_server_api_key", return_value="ck_live_x" ), \
             patch( "builtins.open", new=_fake_open( b"audio" ) ), \
             patch.object( provider, "_call_with_retry", side_effect=requests.RequestException( "boom" ) ):
            with self.assertRaises( RuntimeError ):
                provider._transcribe_via_http( "/audio.wav" )

    def test_non_200_raises( self ):
        """A non-200 response → RuntimeError carrying status + body snippet."""
        provider = self._provider()
        bad = Mock()
        bad.status_code = 500
        bad.text        = "internal error"
        with patch.object( provider, "_resolve_model_server_url", return_value="http://host:7998" ), \
             patch.object( provider, "_model_server_api_key", return_value="ck_live_x" ), \
             patch( "builtins.open", new=_fake_open( b"audio" ) ), \
             patch.object( provider, "_call_with_retry", return_value=bad ):
            with self.assertRaises( RuntimeError ):
                provider._transcribe_via_http( "/audio.wav" )

    def test_success_returns_text( self ):
        """200 with {'text': ...} JSON → the transcribed text."""
        provider = self._provider()
        ok = Mock()
        ok.status_code = 200
        ok.json.return_value = { "text": "transcribed!" }
        with patch.object( provider, "_resolve_model_server_url", return_value="http://host:7998" ), \
             patch.object( provider, "_model_server_api_key", return_value="ck_live_x" ), \
             patch( "builtins.open", new=_fake_open( b"audio" ) ), \
             patch.object( provider, "_call_with_retry", return_value=ok ):
            result = provider._transcribe_via_http( "/audio.wav" )
        self.assertEqual( result, "transcribed!" )

    def test_http_post_closure_executes( self ):
        """
        Drive the real _post closure: _call_with_retry is NOT mocked, so it
        invokes _post → requests.post (mocked). Covers the closure's POST call.
        """
        provider = self._provider()
        ok = Mock()
        ok.status_code = 200
        ok.json.return_value = { "text": "posted ok" }
        with patch.object( provider, "_resolve_model_server_url", return_value="http://host:7998" ), \
             patch.object( provider, "_model_server_api_key", return_value="ck_live_x" ), \
             patch( "builtins.open", new=_fake_open( b"audio" ) ), \
             patch( "requests.post", return_value=ok ) as mock_post:
            result = provider._transcribe_via_http( "/audio.wav" )
        self.assertEqual( result, "posted ok" )
        mock_post.assert_called_once()

    def test_malformed_json_raises( self ):
        """200 but JSON missing 'text' (KeyError) → RuntimeError."""
        provider = self._provider()
        ok = Mock()
        ok.status_code = 200
        ok.json.return_value = { "not_text": "oops" }
        with patch.object( provider, "_resolve_model_server_url", return_value="http://host:7998" ), \
             patch.object( provider, "_model_server_api_key", return_value="ck_live_x" ), \
             patch( "builtins.open", new=_fake_open( b"audio" ) ), \
             patch.object( provider, "_call_with_retry", return_value=ok ):
            with self.assertRaises( RuntimeError ):
                provider._transcribe_via_http( "/audio.wav" )


def _fake_open( data: bytes ):
    """Return an mock_open-style callable yielding `data` for context-managed reads."""
    from unittest.mock import mock_open
    return mock_open( read_data=data )


if __name__ == "__main__":
    unittest.main()
