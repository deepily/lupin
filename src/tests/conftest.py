"""
Top-level pytest configuration - bootstraps Python path for all tests.

This file runs BEFORE cosa is importable, so it must use manual
path manipulation. All other test files can then import cosa directly.
"""
import sys
import os

import pytest

# Bootstrap using LUPIN_ROOT environment variable
lupin_root = os.environ.get( 'LUPIN_ROOT' )
if lupin_root is None:
    raise RuntimeError(
        "LUPIN_ROOT environment variable not set.\n"
        "Set it before running tests:\n"
        "  export LUPIN_ROOT=/mnt/DATA01/include/www.deepily.ai/projects/lupin\n"
        "  pytest src/tests/"
    )

# Add src to Python path (manual - cosa not yet importable)
src_path = os.path.join( lupin_root, 'src' )
if src_path not in sys.path:
    sys.path.insert( 0, src_path )

# Now cosa is importable - other test files can just: import cosa.utils.util as du


# ── FM-21: hermetic-config module boundary ────────────────────────────────────
#
# Design + nod trail: src/rnd/v0.1.8/2026.06.11-fm21-test-isolation-hermetic-config-fixture.md
# Verify pair: src/tests/unit/test_hermetic_config_fixture_{a,b}.py — the _b
# module fails RED if this fixture is removed.

# LUPIN_TEST_HERMETIC_SENTINEL is never set in real runs — it exists as the
# verify pair's leak channel AND keeps the delete-on-restore arm exercised on
# every module teardown.
_HERMETIC_TRACKED_ENV_VARS = (
    "LUPIN_CONFIG_MGR_CLI_ARGS",
    "LUPIN_ROOT",
    "LUPIN_TEST_HERMETIC_SENTINEL",
)


@pytest.fixture( scope="module", autouse=True )
def hermetic_config_module_boundary():
    """
    Guarantee a virgin ConfigurationManager world at every test-module boundary.

    Module-scoped (not function-scoped) on purpose: the stated contract is
    "config state cannot leak between test MODULES"; intra-module setup
    patterns that share a CM instance across tests stay valid, and the
    singleton is not churned per-test.

    Requires:
        - cosa.config.configuration_manager importable (path bootstrap above)
        - LUPIN_CONFIG_MGR_CLI_ARGS / LUPIN_ROOT hold canonical values when
          a module starts (suite invariant)

    Ensures:
        - The CM singleton registry entry is dropped before AND after each
          module — first CM use per module re-derives from the canonical env;
          existing in-module references stay valid (reset drops the registry
          entry, not the object)
        - set_config() mutations, _reset_singleton recreations with custom
          INIs, and bare os.environ writes to the tracked vars cannot cross
          a module boundary
        - Tracked env vars absent at module start are absent again at module
          end (delete arm); present ones are restored to their snapshot value
          (restore arm)

    Raises:
        - None
    """
    from cosa.config.configuration_manager import ConfigurationManager

    ConfigurationManager.reset_for_testing()
    env_snapshot = { var : os.environ.get( var ) for var in _HERMETIC_TRACKED_ENV_VARS }

    yield

    ConfigurationManager.reset_for_testing()
    for var, saved_value in env_snapshot.items():
        if saved_value is None:
            os.environ.pop( var, None )
        else:
            os.environ[ var ] = saved_value


# ── Phase 5 fixtures: model-server carveout testing ──────────────────────────
#
# These fixtures support unit tests for the 2026-05-16 model-server carve-out
# (see src/rnd/v0.1.7/2026.05.16-model-server-carveout/). They are OPT-IN
# (NOT autouse) so they have zero effect on existing tests that don't
# reference them.
#
# Pattern reference:
#   - SpeechToTextProvider/EmbeddingProvider are class-level singletons; any
#     test that touches their state MUST reset _instance + ownership flags
#     before AND after to avoid cross-test pollution.
#   - The fake_model_server_client fixture provides a controllable double
#     for the lupin-model-server HTTP API so router + lifespan tests don't
#     need a live :7998.


@pytest.fixture
def reset_speech_provider_singleton():
    """
    Reset `SpeechToTextProvider` singleton state before and after the test.

    Requires:
        - cosa.memory.speech_to_text_provider importable
        - test does NOT rely on a pre-existing singleton instance

    Ensures:
        - `SpeechToTextProvider._instance` is None entering and exiting the test
        - `SpeechToTextProvider._is_in_process_owner` is False entering and
          exiting the test
        - `SpeechToTextProvider._initialized` (if present on a leftover
          instance) is cleared by virtue of the instance being None
    """
    from cosa.memory.speech_to_text_provider import SpeechToTextProvider

    SpeechToTextProvider._instance            = None
    SpeechToTextProvider._is_in_process_owner = False
    yield
    SpeechToTextProvider._instance            = None
    SpeechToTextProvider._is_in_process_owner = False


@pytest.fixture
def reset_embedding_provider_singleton():
    """
    Reset `EmbeddingProvider` singleton state before and after the test.

    Mirrors `reset_speech_provider_singleton` for the embedding side.

    Requires:
        - cosa.memory.embedding_provider importable
        - test does NOT rely on a pre-existing singleton instance

    Ensures:
        - `EmbeddingProvider._instance` is None entering and exiting
        - `EmbeddingProvider._is_in_process_engine_owner` is False entering
          and exiting
    """
    from cosa.memory.embedding_provider import EmbeddingProvider

    EmbeddingProvider._instance                    = None
    EmbeddingProvider._is_in_process_engine_owner  = False
    yield
    EmbeddingProvider._instance                    = None
    EmbeddingProvider._is_in_process_engine_owner  = False


@pytest.fixture
def fake_model_server_client( monkeypatch ):
    """
    Yield a controllable fake of the lupin-model-server HTTP client surface.

    The returned handle exposes:
        - `set_transcribe_response(text_or_exception)` — set the next
          `/transcribe` response (text string OR exception instance to raise)
        - `set_embed_response(vec_or_exception)` — set the next
          `/embeddings/*` response (list of floats OR exception)
        - `recorded_calls` — list of dicts, one per intercepted call

    Side effects (patched via `monkeypatch`):
        - `cosa.utils.util.get_api_key` → returns a stub `ck_live_*` key
        - `LUPIN_MODEL_SERVER_URL` env var → sentinel value pointing at the fake
        - `SpeechToTextProvider._transcribe_via_http` → routes into the fake's
          `transcribe()` method
        - `EmbeddingProvider`'s HTTP-fallback method → routes into the fake's
          `embed()` method (patched lazily by tests that need it; we only
          publish the fake here and let callers wire the patch with the right
          method name once EmbeddingProvider's HTTP entry point name is
          confirmed in Phase 5.4)

    Requires:
        - `cosa.memory.speech_to_text_provider` importable
        - `cosa.utils.util.get_api_key` importable

    Ensures:
        - The fake handle is yielded; all monkeypatches auto-revert at
          fixture teardown (pytest's monkeypatch contract)
        - Calls to the patched HTTP method appear in `recorded_calls`
        - Setting an Exception via `set_transcribe_response` causes the next
          patched call to raise that exception
    """
    class _FakeModelServerClient:
        """In-process fake mimicking the lupin-model-server HTTP API surface."""

        def __init__( self ):
            self._transcribe_response = "default fake transcription"
            self._embed_response      = [ 0.1 ] * 768
            self.recorded_calls       = []

        def set_transcribe_response( self, response ):
            """
            Configure the next `/transcribe` response.

            Requires:
                - response is either a str (success path) or an Exception
                  instance (to be raised on next call)
            """
            self._transcribe_response = response

        def set_embed_response( self, vec_or_exception ):
            """
            Configure the next `/embeddings/*` response.

            Requires:
                - vec_or_exception is either a list[float] (success path) or
                  an Exception instance (to be raised on next call)
            """
            self._embed_response = vec_or_exception

        def transcribe( self, audio_path, **kwargs ):
            """
            Stand-in for `SpeechToTextProvider._transcribe_via_http`.

            Records the call and either returns the configured text or
            raises the configured exception.
            """
            self.recorded_calls.append( {
                "method"     : "transcribe",
                "audio_path" : audio_path,
                "kwargs"     : kwargs,
            } )
            if isinstance( self._transcribe_response, Exception ):
                raise self._transcribe_response
            return self._transcribe_response

        def embed( self, text, **kwargs ):
            """
            Stand-in for `EmbeddingProvider`'s HTTP embedding call.

            Records the call and either returns the configured vector or
            raises the configured exception.
            """
            self.recorded_calls.append( {
                "method" : "embed",
                "text"   : text,
                "kwargs" : kwargs,
            } )
            if isinstance( self._embed_response, Exception ):
                raise self._embed_response
            return self._embed_response

    fake = _FakeModelServerClient()

    # Stub the API key resolution to a syntactically-valid ck_live_* string
    # so downstream regex / hash checks don't reject.
    monkeypatch.setattr(
        "cosa.utils.util.get_api_key",
        lambda name, **kwargs: "ck_live_" + "x" * 64,
    )

    # Sentinel env var so any code that reads LUPIN_MODEL_SERVER_URL sees a
    # non-empty value pointing at the fake.
    monkeypatch.setenv( "LUPIN_MODEL_SERVER_URL", "http://fake-model-server:7998" )

    # Patch the speech HTTP fallback to route into the fake.
    monkeypatch.setattr(
        "cosa.memory.speech_to_text_provider.SpeechToTextProvider._transcribe_via_http",
        lambda self, audio_path, **kwargs: fake.transcribe( audio_path, **kwargs ),
    )

    yield fake
