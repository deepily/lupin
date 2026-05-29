"""
API Resource Manager — centralized rate-limit / API contention surface.

Phase 1 (v0.1.7 CJ Flow async multi-lane): stub that wraps the existing
WebSearchRateLimiter and passes through for other providers. No agents
call this module yet — init_arm() wires the singleton into server startup
so the infrastructure is alive from boot; per-agent migration is Phase 2/3.

Design anchor: src/rnd/v0.1.7/2026.04.23-cj-flow-async-multi-lane/02-phase-1-rlock-config-and-resource-manager.md
Singleton pattern mirrors: src/cosa/rest/test_suite_completion_watchdog.py:327-354
"""

from typing import Optional


_arm_instance: Optional["ApiResourceManager"] = None


def init_arm() -> "ApiResourceManager":
    """
    Initialize the process-wide ApiResourceManager singleton.

    Requires:
        - Called once during single-threaded server startup (no construction race)

    Ensures:
        - _arm_instance is populated with a live ApiResourceManager
        - Subsequent calls return the same instance (idempotent)

    Returns:
        ApiResourceManager: the singleton instance

    Raises:
        - None
    """
    global _arm_instance
    if _arm_instance is None:
        _arm_instance = ApiResourceManager()
    return _arm_instance


def get_arm() -> "ApiResourceManager":
    """
    Return the ApiResourceManager singleton.

    Requires:
        - init_arm() has been called (typically during server startup)

    Ensures:
        - Returns the singleton instance

    Returns:
        ApiResourceManager: the singleton instance

    Raises:
        - RuntimeError if init_arm() has not been called
    """
    if _arm_instance is None:
        raise RuntimeError( "ApiResourceManager not initialised. Call init_arm() at startup." )
    return _arm_instance


def reset_arm() -> None:
    """
    Clear the singleton. Used by tests to avoid cross-test contamination.

    Requires:
        - None

    Ensures:
        - _arm_instance is None after call
        - Next init_arm() call creates a fresh instance

    Raises:
        - None
    """
    global _arm_instance
    _arm_instance = None


class ApiResourceManager:
    """
    Singleton managing contention decisions across external APIs.

    Phase 1 scope: thin wrapper around existing per-agent rate limiters.
    Primary backing: WebSearchRateLimiter for Anthropic web-search.
    Other providers: pass-through (no limit enforced beyond what the SDK
    itself does) until their per-agent logic migrates here.

    Future scope (Phase 2+): per-provider sliding-window call history,
    cost estimation, dispatcher back-pressure.

    Requires:
        - Accessed through init_arm() / get_arm() module helpers
        - Not instantiated directly by callers

    Ensures:
        - acquire() delegates to WebSearchRateLimiter for anthropic_web_search
        - acquire() is a no-op (immediate return) for other providers in Phase 1
        - record_call() delegates to WebSearchRateLimiter.record_usage for
          anthropic_web_search, no-op for others
        - get_status() returns a snapshot suitable for /api/queue/pool-status

    Raises:
        - None from __init__
    """

    _PASSTHROUGH_PROVIDERS = ( "anthropic", "openai", "gemini" )
    _WEB_SEARCH_PROVIDER   = "anthropic_web_search"

    def __init__( self ) -> None:
        """
        Initialise the manager with lazy WebSearchRateLimiter backing.

        Requires:
            - None

        Ensures:
            - _web_search_limiter is None until first use
            - No imports from cosa.agents at this point (breaks utils → agents cycle)

        Raises:
            - None
        """
        # Lazy-assigned in _get_web_search_limiter() to avoid utils → agents
        # import cycle at module load time.
        self._web_search_limiter = None

    def _get_web_search_limiter( self ):
        """
        Lazy-construct (or return) the WebSearchRateLimiter instance.

        Requires:
            - cosa.agents.deep_research.rate_limiter is importable

        Ensures:
            - Returns a live WebSearchRateLimiter
            - Single instance reused across calls (under CPython GIL, double-init
              is harmless: one instance wins, the other is GC'd)

        Returns:
            WebSearchRateLimiter

        Raises:
            - ImportError if deep_research.rate_limiter is unavailable (should not
              happen in a correctly-installed tree)
        """
        if self._web_search_limiter is None:
            from cosa.agents.deep_research.rate_limiter import WebSearchRateLimiter
            self._web_search_limiter = WebSearchRateLimiter()
        return self._web_search_limiter

    async def acquire( self, provider: str ) -> None:
        """
        Wait until it is safe to call `provider` (possibly zero wait).

        Requires:
            - provider is a non-empty string

        Ensures:
            - For anthropic_web_search: delegates to WebSearchRateLimiter.wait_if_needed()
              which is reactive (tracks its own sliding window internally)
            - For anthropic / openai / gemini: returns immediately (no pre-flight delay)
            - Unknown providers also pass through

        Args:
            provider: one of "anthropic_web_search", "anthropic", "openai", "gemini"

        Raises:
            - None
        """
        if provider == self._WEB_SEARCH_PROVIDER:
            limiter = self._get_web_search_limiter()
            await limiter.wait_if_needed()
        # passthrough providers: no wait

    def record_call( self, provider: str, tokens: int = 0, latency_ms: float = 0.0 ) -> None:
        """
        Record a completed call against the provider's rolling history.

        Requires:
            - provider is a non-empty string
            - tokens >= 0
            - latency_ms >= 0.0

        Ensures:
            - For anthropic_web_search: delegates to WebSearchRateLimiter.record_usage(tokens)
            - For other providers: no-op in Phase 1

        Args:
            provider: one of "anthropic_web_search", "anthropic", "openai", "gemini"
            tokens: actual tokens used (from response.usage.input_tokens if known)
            latency_ms: wall-clock latency of the call, for future per-provider telemetry

        Raises:
            - None
        """
        if provider == self._WEB_SEARCH_PROVIDER:
            limiter = self._get_web_search_limiter()
            limiter.record_usage( tokens )
        # passthrough providers: no-op

    def get_status( self ) -> dict:
        """
        Return a dict snapshot suitable for /api/queue/pool-status.

        Requires:
            - None

        Ensures:
            - Returns a dict with keys for all four providers
            - anthropic_web_search section is a VERBATIM passthrough of
              WebSearchRateLimiter.get_status() (keys: tokens_in_window,
              tokens_per_minute_limit, calls_in_window, window_seconds,
              time_until_oldest_expires, would_need_delay)
            - Each passthrough provider's section has provider_wait_state == "passthrough"

        Returns:
            dict: per-provider status snapshot

        Raises:
            - None
        """
        limiter = self._get_web_search_limiter()
        status = {
            self._WEB_SEARCH_PROVIDER: limiter.get_status(),
        }
        for provider in self._PASSTHROUGH_PROVIDERS:
            status[ provider ] = { "provider_wait_state" : "passthrough" }
        return status


def quick_smoke_test():
    """
    Quick smoke test for ApiResourceManager singleton.

    Requires:
        - asyncio available

    Ensures:
        - Tests singleton init/get/reset, acquire passthrough, get_status shape
    """
    import asyncio
    import cosa.utils.util as cu

    cu.print_banner( "ApiResourceManager Smoke Test", prepend_nl=True )

    try:
        # Test 1: get_arm before init raises
        reset_arm()
        try:
            get_arm()
            print( "✗ Expected RuntimeError before init_arm()" )
        except RuntimeError:
            print( "✓ get_arm() correctly raises before init_arm()" )

        # Test 2: init_arm is idempotent
        arm1 = init_arm()
        arm2 = init_arm()
        assert arm1 is arm2, "init_arm() should be idempotent"
        print( "✓ init_arm() is idempotent" )

        # Test 3: get_arm returns same instance
        arm3 = get_arm()
        assert arm3 is arm1, "get_arm() should return singleton"
        print( "✓ get_arm() returns singleton instance" )

        # Test 4: passthrough acquire returns immediately
        async def _test_passthrough():
            import time
            t0 = time.time()
            await arm1.acquire( "openai" )
            elapsed = time.time() - t0
            assert elapsed < 0.01, f"Passthrough should be <10ms, got {elapsed*1000:.1f}ms"
            return elapsed

        elapsed = asyncio.run( _test_passthrough() )
        print( f"✓ Passthrough acquire returned in {elapsed*1000:.2f}ms" )

        # Test 5: record_call passthrough is no-op
        arm1.record_call( "openai", tokens=100 )
        arm1.record_call( "anthropic", tokens=100 )
        arm1.record_call( "gemini", tokens=100 )
        print( "✓ record_call passthrough providers do not raise" )

        # Test 6: get_status shape
        status = arm1.get_status()
        assert "anthropic_web_search" in status
        assert "anthropic" in status
        assert "openai" in status
        assert "gemini" in status
        ws_status = status[ "anthropic_web_search" ]
        assert "tokens_in_window" in ws_status
        assert "tokens_per_minute_limit" in ws_status
        assert "calls_in_window" in ws_status
        assert "window_seconds" in ws_status
        assert "time_until_oldest_expires" in ws_status
        assert "would_need_delay" in ws_status
        assert status[ "openai" ][ "provider_wait_state" ] == "passthrough"
        print( "✓ get_status() shape: anthropic_web_search passthrough + 3 passthrough providers" )

        print( "\n✓ ApiResourceManager smoke test completed successfully" )
        return True

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()
        return False
    finally:
        reset_arm()


if __name__ == "__main__":
    quick_smoke_test()
