"""
Unit tests for ApiResourceManager singleton (v0.1.7 Phase 1 CJ Flow async multi-lane).

Design anchor:
    src/rnd/v0.1.7/2026.04.23-cj-flow-async-multi-lane/02-phase-1-rlock-config-and-resource-manager.md

Covers singleton lifecycle, idempotency, passthrough timing, signature-regression
(no `tokens` arg on acquire), mocked delegation to WebSearchRateLimiter, and the
verbatim-passthrough shape of get_status().
"""

import asyncio
import inspect
import time
from unittest.mock import MagicMock, patch

import pytest

from cosa.utils import api_resource_manager as arm_mod
from cosa.utils.api_resource_manager import (
    ApiResourceManager,
    init_arm,
    get_arm,
    reset_arm,
)


@pytest.fixture( autouse=True )
def _reset_singleton():
    """Ensure every test starts with a clean singleton state."""
    reset_arm()
    yield
    reset_arm()


class TestSingletonLifecycle:
    """init_arm / get_arm / reset_arm contract."""

    def test_get_arm_raises_before_init( self ):
        """get_arm() raises RuntimeError when init_arm() has not been called."""
        with pytest.raises( RuntimeError, match="ApiResourceManager not initialised" ):
            get_arm()

    def test_init_arm_is_idempotent( self ):
        """Two init_arm() calls return the same instance; second call does not create a new one."""
        arm1 = init_arm()
        arm2 = init_arm()
        assert arm1 is arm2

    def test_get_arm_returns_singleton( self ):
        """After init_arm(), two get_arm() calls return the same identical object."""
        arm1 = init_arm()
        assert get_arm() is arm1
        assert get_arm() is get_arm()


class TestAcquire:
    """acquire() signature + delegation."""

    def test_acquire_passthrough_provider_returns_immediately( self ):
        """await arm.acquire('openai') completes in <10ms (no rate-limit wait)."""
        arm = init_arm()

        async def _measure( provider: str ) -> float:
            t0 = time.perf_counter()
            await arm.acquire( provider )
            return time.perf_counter() - t0

        for provider in ( "anthropic", "openai", "gemini" ):
            elapsed = asyncio.run( _measure( provider ) )
            assert elapsed < 0.01, \
                f"Passthrough {provider!r} took {elapsed*1000:.2f}ms, expected <10ms"

    def test_acquire_web_search_delegates_to_rate_limiter( self ):
        """acquire('anthropic_web_search') invokes WebSearchRateLimiter.wait_if_needed() once."""
        arm = init_arm()
        mock_limiter = MagicMock()

        async def _noop_async():
            return 0.0
        mock_limiter.wait_if_needed = MagicMock( return_value=_noop_async() )

        # Inject the mock as the cached limiter; bypass lazy construction
        arm._web_search_limiter = mock_limiter

        asyncio.run( arm.acquire( "anthropic_web_search" ) )

        mock_limiter.wait_if_needed.assert_called_once()

    def test_acquire_no_tokens_arg( self ):
        """
        Regression test for 2026-04-23 fitness-review decision: acquire()
        signature must accept only `provider` (no `tokens` kw). WebSearchRateLimiter
        is reactive, not predictive — there is no pre-flight token budget to pass.
        """
        sig = inspect.signature( ApiResourceManager.acquire )
        params = set( sig.parameters.keys() )
        # Expected: self + provider only
        assert params == { "self", "provider" }, \
            f"acquire() should accept only (self, provider); got {params}"


class TestRecordCall:
    """record_call() delegation behaviour."""

    def test_record_call_passthrough_is_noop( self ):
        """record_call('openai', tokens=100) doesn't raise, doesn't mutate any state."""
        arm = init_arm()
        arm.record_call( "openai", tokens=100 )
        arm.record_call( "anthropic", tokens=50 )
        arm.record_call( "gemini", tokens=10, latency_ms=123.4 )
        # No state to assert on — just assert no raise and no limiter instantiation
        assert arm._web_search_limiter is None

    def test_record_call_web_search_delegates( self ):
        """record_call('anthropic_web_search', tokens=N) invokes WebSearchRateLimiter.record_usage(tokens=N) once."""
        arm = init_arm()
        mock_limiter = MagicMock()
        arm._web_search_limiter = mock_limiter

        arm.record_call( "anthropic_web_search", tokens=1234 )

        mock_limiter.record_usage.assert_called_once_with( 1234 )


class TestGetStatus:
    """get_status() shape."""

    def test_get_status_shape( self ):
        """
        Returned dict has all 4 provider keys. anthropic_web_search section is a
        verbatim passthrough of WebSearchRateLimiter.get_status() (keys:
        tokens_in_window, tokens_per_minute_limit, calls_in_window, window_seconds,
        time_until_oldest_expires, would_need_delay). Passthrough providers have
        key provider_wait_state == 'passthrough'.
        """
        arm = init_arm()

        mock_limiter = MagicMock()
        mock_limiter.get_status.return_value = {
            "tokens_in_window"          : 1000,
            "tokens_per_minute_limit"   : 30_000,
            "calls_in_window"           : 2,
            "window_seconds"            : 60.0,
            "time_until_oldest_expires" : 45.0,
            "would_need_delay"          : False,
        }
        arm._web_search_limiter = mock_limiter

        status = arm.get_status()

        assert set( status.keys() ) == { "anthropic_web_search", "anthropic", "openai", "gemini" }

        ws = status[ "anthropic_web_search" ]
        expected_keys = {
            "tokens_in_window", "tokens_per_minute_limit", "calls_in_window",
            "window_seconds", "time_until_oldest_expires", "would_need_delay",
        }
        assert set( ws.keys() ) == expected_keys, \
            f"anthropic_web_search must be a verbatim passthrough; got keys {set( ws.keys() )}"
        # Actual values passed through unchanged
        assert ws[ "tokens_in_window" ] == 1000
        assert ws[ "would_need_delay" ] is False

        for provider in ( "anthropic", "openai", "gemini" ):
            assert status[ provider ] == { "provider_wait_state" : "passthrough" }


class TestDeepResearchMigration:
    """
    Phase 3 regression tests: DeepResearch api_client routes rate-limit
    decisions through ApiResourceManager instead of its own _rate_limiter.
    Falls back to local _rate_limiter when ARM is uninitialised (test/startup).
    """

    def _make_mock_client_and_response( self ):
        """Build a minimal ResearchAPIClient stub + fake response for tests."""
        from unittest.mock import MagicMock

        # Fake APIResponse
        fake_response = MagicMock()
        fake_response.input_tokens = 5000

        # Minimal config stub
        class _Cfg:
            subagent_model = "claude-sonnet-4-6"

        # MagicMock spec'd off the real class, with _call_api coroutine mocked
        from cosa.agents.deep_research.api_client import ResearchAPIClient
        client = ResearchAPIClient.__new__( ResearchAPIClient )
        client.config        = _Cfg()
        client.debug         = False
        client._rate_limiter = MagicMock()  # local fallback; tests check it's NOT called
        async def _noop_async( *a, **kw ): return fake_response
        client._call_api     = _noop_async
        return client, fake_response

    def test_deep_research_calls_acquire_through_singleton( self, monkeypatch ):
        """call_subagent(use_web_search=True) triggers arm.acquire('anthropic_web_search')."""
        import asyncio
        from cosa.utils import api_resource_manager as arm_mod

        client, _ = self._make_mock_client_and_response()

        # Init ARM + instrument
        arm = init_arm()
        called_with = [ ]
        async def traced_acquire( provider ):
            called_with.append( provider )
        monkeypatch.setattr( arm, "acquire", traced_acquire )
        monkeypatch.setattr( arm, "record_call", lambda **kw: None )

        asyncio.run( client.call_subagent(
            system_prompt  = "sys",
            user_message   = "msg",
            subquery_index = 0,
            use_web_search = True,
        ) )

        assert called_with == [ "anthropic_web_search" ]
        # Local fallback was NOT consulted
        client._rate_limiter.wait_if_needed.assert_not_called()

    def test_deep_research_records_call_after_success( self, monkeypatch ):
        """After successful call_subagent, arm.record_call fires with matching tokens."""
        import asyncio

        client, fake_response = self._make_mock_client_and_response()
        arm = init_arm()
        monkeypatch.setattr( arm, "acquire", lambda provider: _async_noop() )
        record_calls = [ ]
        monkeypatch.setattr( arm, "record_call", lambda **kw: record_calls.append( kw ) )

        asyncio.run( client.call_subagent(
            system_prompt  = "sys",
            user_message   = "msg",
            subquery_index = 0,
            use_web_search = True,
        ) )

        assert len( record_calls ) == 1
        assert record_calls[ 0 ][ "provider" ] == "anthropic_web_search"
        assert record_calls[ 0 ][ "tokens" ]   == 5000
        client._rate_limiter.record_usage.assert_not_called()

    def test_deep_research_falls_back_when_arm_uninitialised( self, monkeypatch ):
        """When get_arm() raises RuntimeError (ARM not initialised), DR uses its local _rate_limiter."""
        import asyncio
        from unittest.mock import AsyncMock

        reset_arm()  # ensure ARM is UNinitialised
        client, _ = self._make_mock_client_and_response()
        # local limiter returns an awaitable delay of 0s
        client._rate_limiter.wait_if_needed = AsyncMock( return_value=0.0 )

        asyncio.run( client.call_subagent(
            system_prompt  = "sys",
            user_message   = "msg",
            subquery_index = 0,
            use_web_search = True,
        ) )

        # Local limiter was consulted (fallback worked)
        client._rate_limiter.wait_if_needed.assert_called_once()
        client._rate_limiter.record_usage.assert_called_once()


async def _async_noop( *a, **kw ):
    return None


if __name__ == "__main__":
    pytest.main( [ __file__, "-v" ] )
