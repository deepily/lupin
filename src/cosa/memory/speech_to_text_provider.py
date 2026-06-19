"""
SpeechToTextProvider — process-aware routing between in-process Whisper
pipeline and HTTP proxy to lupin-model-server.

Mirrors `EmbeddingProvider` architecture exactly (singleton + class-level
in-process-owner flag + INI-key switch + HTTP-fallback path) so the carve-out
introduces a single, consistent pattern rather than two ad-hoc abstractions.

Routing decision (per call):
    1. INI `speech to text provider = local` AND this process owns the pipeline
       → call the local `whisper_pipeline(...)` global
    2. INI `speech to text provider = model-server` OR this process does NOT
       own the pipeline → POST to model-server `/transcribe`
    3. INI unset/invalid → defaults to `local` (preserves today's behavior)

The "ownership" flag mirrors `EmbeddingProvider._is_in_process_engine_owner`
— set by `main.py` lifespan AFTER the Whisper pipeline successfully loads.
A non-owner process (test, script, subagent, or a remote-mode compute
container) always routes via HTTP.

See: src/rnd/v0.1.7/2026.05.16-model-server-carveout/01-design.md
"""

import os
import threading
from typing import Optional

import cosa.utils.util as du
from cosa.config.configuration_manager import ConfigurationManager


class SpeechToTextProvider:
    """
    Singleton routing transcription requests between the in-process Whisper
    pipeline and the lupin-model-server HTTP endpoint.

    Architecture mirrors `EmbeddingProvider`:
        - `_instance` + double-checked locking for thread-safe lazy init
        - `_is_in_process_owner` class flag flipped by main.py lifespan AFTER
          Whisper successfully loads
        - INI key `speech to text provider` selects local vs model-server
        - `LUPIN_MODEL_SERVER_URL` env override mirrors `LUPIN_APP_SERVER_URL`
    """

    _instance: Optional[ "SpeechToTextProvider" ] = None
    _lock                                        = threading.Lock()
    _is_in_process_owner                         = False

    def __new__( cls, *args, **kwargs ):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__( cls )
        return cls._instance

    def __init__( self, debug: bool = False, verbose: bool = False ):
        if getattr( self, "_initialized", False ):
            return
        self._debug       = debug
        self._verbose     = verbose
        self._config_mgr  = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        self._provider    = self._config_mgr.get(
            "speech to text provider", default="local", silent=True
        ).lower().strip()
        if self._debug:
            print( f"[SpeechToTextProvider] init provider={self._provider} owner={self._is_in_process_owner}" )
        self._initialized = True

    @classmethod
    def declare_in_process_owner( cls ) -> None:
        """
        Flip the class flag indicating THIS process owns the Whisper pipeline.

        Called by `src/lupin_app/main.py` lifespan AFTER `load_stt_model()`
        returns successfully and `whisper_pipeline` is bound. Mirrors
        `EmbeddingProvider.declare_in_process_engine_owner()` semantically and
        in call-site placement.

        Idempotent — safe to call multiple times.
        """
        cls._is_in_process_owner = True

    @classmethod
    def declare_remote_only( cls ) -> None:
        """
        Reset the in-process-owner flag. Used by tests + (in the future) by
        the Phase 3.6 lifespan remote-mode branch to make process-ownership
        state explicit when the lifespan SKIPS the Whisper load.
        """
        cls._is_in_process_owner = False

    @staticmethod
    def _resolve_model_server_url() -> Optional[ str ]:
        """
        Resolve the lupin-model-server URL at call time. Returns None when
        unset → caller falls through to local-mode (or raises if local-mode
        is impossible).

        Reads `LUPIN_MODEL_SERVER_URL` env var first (Phase 3.6 + compose
        injection), then falls back to the `model server url` INI key with
        a hardcoded default of `http://lupin-model-server:7998`.

        Ensures:
            - Returns the stripped env value when set and non-empty
            - Returns the INI value when env is unset
            - Returns "http://lupin-model-server:7998" when both are unset
            - Never raises
        """
        url = os.environ.get( "LUPIN_MODEL_SERVER_URL", "" ).strip()
        if url:
            return url
        try:
            cfg = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
            ini = cfg.get( "model server url", default="http://lupin-model-server:7998", silent=True ).strip()
            return ini if ini else "http://lupin-model-server:7998"
        except Exception:
            return "http://lupin-model-server:7998"

    @staticmethod
    def _model_server_api_key() -> Optional[ str ]:
        """
        Load the `ck_live_*` plaintext key used to authenticate against
        lupin-model-server's X-API-Key middleware.

        Per María's 2026-05-16 brief, the model-server reuses the existing
        `notification-api-claude-code-dev` key — no parallel `ck_internal_*`
        namespace. Same key the FastAPI HTTP paths use.

        Ensures:
            - Returns the plaintext key string when the file is present
            - Returns None on any failure (missing file, read error)
            - Never raises
        """
        try:
            return du.get_api_key( "notification-api-claude-code-dev" )
        except Exception:
            return None

    def _should_use_local( self ) -> bool:
        """
        Decide whether THIS call should run the in-process Whisper pipeline
        (True) or HTTP-proxy to the model-server (False).

        Returns True ONLY when both:
            1. INI `speech to text provider = local`
            2. This process declared itself the in-process owner (lifespan flag)

        Otherwise returns False → HTTP path.
        """
        return self._provider == "local" and self._is_in_process_owner

    def transcribe( self, audio_path: str, whisper_pipeline=None, **kwargs ) -> str:
        """
        Route a transcription request to local pipeline or model-server.

        Requires:
            - audio_path is a non-empty string pointing to a readable file
              OR audio bytes if the in-process path is used differently
            - whisper_pipeline is the in-process pipeline handle (for local mode)
              — passed in by the caller (typically speech.py via Depends)
            - kwargs are forwarded to the underlying pipeline call (e.g.,
              chunk_length_s, stride_length_s)

        Ensures:
            - Returns the transcribed text string on success
            - Raises RuntimeError on HTTP failure with a clear message
            - Never silently returns the wrong path's result

        The local-mode path delegates to the existing `whisper_pipeline` global
        passed in by the caller, which preserves the existing
        `_run_whisper_with_retry` retry semantics intact (the caller wraps
        this call).
        """
        if self._should_use_local():
            if whisper_pipeline is None:
                raise RuntimeError(
                    "SpeechToTextProvider local-mode called without whisper_pipeline arg — "
                    "caller must pass the Depends-injected pipeline handle"
                )
            # CUDA OOM retry — mirrors the historical `_run_whisper_with_retry`
            # logic in cosa/rest/routers/speech.py:39-60 so the local path
            # retains the same one-retry-on-OOM behavior post-refactor.
            # torch + gc imported lazily so non-GPU processes (test workers,
            # cloud-run cold-paths) don't pay the import tax.
            import gc as _gc
            import torch as _torch
            try:
                result = whisper_pipeline( audio_path, **kwargs )
            except _torch.cuda.OutOfMemoryError:
                if self._debug:
                    print( "[SpeechToTextProvider] CUDA OOM on local Whisper, clearing cache + retrying" )
                _gc.collect()
                _torch.cuda.empty_cache()
                result = whisper_pipeline( audio_path, **kwargs )
            # Whisper returns {"text": "...", ...}. Caller wants the text string.
            if isinstance( result, dict ) and "text" in result:
                return result[ "text" ]
            return str( result )
        return self._transcribe_via_http( audio_path, **kwargs )

    @staticmethod
    def _call_with_retry( fn, max_retries: int = 3, backoff_seq: tuple = ( 2, 4, 8 ) ):
        """
        Run `fn()` with exponential-backoff retry on transient HTTP errors.

        Phase 3.4 of the carve-out: lightweight retry wrapper for HTTP calls
        to lupin-model-server. Retries on:
            - `requests.Timeout` (network or server-side hang)
            - `requests.ConnectionError` (target unreachable)
            - Response 5xx status codes (server-side transient)

        Does NOT retry on:
            - 4xx status codes (caller's fault; bail immediately)
            - `RuntimeError` raised by `fn` itself (caller-decided fatal)

        Requires:
            - `fn` is a no-arg callable returning a `requests.Response`-like
              object (with `.status_code`)
            - `max_retries` >= 1
            - `backoff_seq` has at least `max_retries - 1` entries

        Ensures:
            - Returns the first success response
            - Raises the last transient exception when all retries exhaust
            - Returns the first non-retryable response (4xx) immediately

        Args:
            fn: callable performing one HTTP call
            max_retries: total attempt count (e.g., 3 = try once + retry twice)
            backoff_seq: seconds to sleep between attempts (only first
                `max_retries - 1` values are used)

        Returns:
            requests.Response: the response object (caller checks status)
        """
        import time as _time
        import requests as _requests

        last_exc = None
        for attempt in range( max_retries ):
            try:
                response = fn()
                # Retry on 5xx; bail on 2xx-3xx-4xx immediately
                if 500 <= response.status_code < 600 and attempt < max_retries - 1:
                    _time.sleep( backoff_seq[ attempt ] )
                    continue
                return response
            except ( _requests.Timeout, _requests.ConnectionError ) as e:
                last_exc = e
                if attempt < max_retries - 1:
                    _time.sleep( backoff_seq[ attempt ] )
                    continue
                raise
        # Loop exit only via exception above; defensive
        if last_exc is not None:                                              # pragma: no cover — unreachable
            raise last_exc
        return None                                                            # pragma: no cover — unreachable

    def _transcribe_via_http( self, audio_path: str, **kwargs ) -> str:
        """
        POST the audio file at `audio_path` to lupin-model-server `/transcribe`.

        Requires:
            - LUPIN_MODEL_SERVER_URL reachable (or INI `model server url`)
            - `src/conf/keys/notification-api-claude-code-dev` readable
            - audio_path points to a readable file

        Ensures:
            - Returns transcribed text on success
            - Raises RuntimeError on missing key, unreachable URL, non-200,
              or malformed response

        Raises:
            RuntimeError: with a clear message naming the failure layer
        """
        import requests

        base_url = self._resolve_model_server_url()
        api_key  = self._model_server_api_key()
        if not api_key:
            raise RuntimeError(
                "SpeechToTextProvider HTTP fallback: no API key at "
                "src/conf/keys/notification-api-claude-code-dev. This is the same "
                "canonical ck_live_* key used by the FastAPI HTTP path; "
                "provision via the existing admin minting flow."
            )

        url = f"{base_url}/transcribe"
        try:
            with open( audio_path, "rb" ) as f:
                audio_bytes = f.read()
        except OSError as e:
            raise RuntimeError( f"SpeechToTextProvider could not read {audio_path}: {e}" )

        def _post():
            return requests.post(
                url,
                files   = { "audio": ( os.path.basename( audio_path ), audio_bytes, "application/octet-stream" ) },
                headers = { "X-API-Key": api_key },
                timeout = 120
            )

        try:
            response = self._call_with_retry( _post )
        except requests.RequestException as e:
            raise RuntimeError(
                f"SpeechToTextProvider HTTP unreachable at {url}: {type( e ).__name__}: {e}"
            )

        if response.status_code != 200:
            raise RuntimeError(
                f"SpeechToTextProvider HTTP returned {response.status_code} from {url}: "
                f"{response.text[:200]}"
            )

        try:
            return response.json()[ "text" ]
        except ( KeyError, ValueError ) as e:
            raise RuntimeError(
                f"SpeechToTextProvider HTTP: malformed response from {url}: {e}"
            )
