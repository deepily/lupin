"""
Unit tests for the ApiResourceManager singleton (cosa.utils.api_resource_manager).

Covers the Phase-1 rate-limit / API-contention surface:
- Module-level singleton lifecycle: init_arm() / get_arm() / reset_arm()
- Lazy WebSearchRateLimiter backing (utils -> agents import-cycle avoidance)
- acquire() delegation vs. passthrough
- record_call() delegation vs. no-op
- get_status() snapshot shape for /api/queue/pool-status

The real WebSearchRateLimiter is replaced by a faithful in-memory fake so the
tests touch no network and no wall-clock sleeps. Assertions harvested and
strengthened from the module's quick_smoke_test() block (now superseded).
"""

import asyncio
import unittest
from unittest.mock import patch

import cosa.utils.api_resource_manager as arm_mod
from cosa.utils.api_resource_manager import (
    init_arm, get_arm, reset_arm, ApiResourceManager
)

# Patch target: the lazy `from cosa.agents...import WebSearchRateLimiter` inside
# _get_web_search_limiter() resolves against this fully-qualified name.
_LIMITER_PATH = "cosa.agents.deep_research.rate_limiter.WebSearchRateLimiter"


class _FakeWebSearchLimiter:
    """
    Minimal faithful stand-in for WebSearchRateLimiter.

    Ensures:
        - wait_if_needed() is awaitable and records invocation count
        - record_usage() records the tokens it was handed
        - get_status() returns the six-key contract the real limiter exposes
    """

    def __init__( self ):
        self.wait_calls   = 0
        self.record_calls = []

    async def wait_if_needed( self ):
        self.wait_calls += 1
        return 0.0

    def record_usage( self, tokens, call_type="web_search" ):
        self.record_calls.append( ( tokens, call_type ) )

    def get_status( self ):
        return {
            "tokens_in_window"          : 0,
            "tokens_per_minute_limit"   : 20000,
            "calls_in_window"           : 0,
            "window_seconds"            : 60,
            "time_until_oldest_expires" : 0.0,
            "would_need_delay"          : False,
        }


class TestApiResourceManagerSingleton( unittest.TestCase ):
    """
    Singleton lifecycle: init_arm / get_arm / reset_arm.

    Ensures:
        - get_arm() before init raises a clear RuntimeError
        - init_arm() is idempotent and returns an ApiResourceManager
        - reset_arm() restores the uninitialised state
    """

    def setUp( self ):
        reset_arm()

    def tearDown( self ):
        reset_arm()

    def test_get_arm_raises_before_init( self ):
        """get_arm() must fail loudly when init_arm() has not run."""
        with self.assertRaises( RuntimeError ) as ctx:
            get_arm()
        self.assertIn( "init_arm()", str( ctx.exception ) )

    def test_init_arm_creates_instance( self ):
        """init_arm() returns a live ApiResourceManager and populates the module global."""
        arm = init_arm()
        self.assertIsInstance( arm, ApiResourceManager )
        self.assertIs( arm_mod._arm_instance, arm )

    def test_init_arm_is_idempotent( self ):
        """A second init_arm() returns the same instance (no re-construction)."""
        first  = init_arm()
        second = init_arm()
        self.assertIs( first, second )

    def test_get_arm_returns_singleton( self ):
        """get_arm() hands back exactly the instance init_arm() created."""
        created = init_arm()
        self.assertIs( get_arm(), created )

    def test_reset_arm_clears_singleton( self ):
        """After reset_arm() the global is None and get_arm() raises again."""
        init_arm()
        reset_arm()
        self.assertIsNone( arm_mod._arm_instance )
        with self.assertRaises( RuntimeError ):
            get_arm()

    def test_reset_arm_allows_fresh_instance( self ):
        """init_arm() after reset_arm() yields a brand-new, distinct instance."""
        original = init_arm()
        reset_arm()
        replacement = init_arm()
        self.assertIsNot( original, replacement )


class TestApiResourceManagerBehavior( unittest.TestCase ):
    """
    Per-provider behaviour of acquire / record_call / get_status with the
    WebSearchRateLimiter backing faked out.

    Ensures:
        - anthropic_web_search delegates to the limiter
        - passthrough providers never construct or touch the limiter
        - get_status() returns the documented snapshot shape
    """

    def setUp( self ):
        reset_arm()
        self.patcher = patch( _LIMITER_PATH, _FakeWebSearchLimiter )
        self.patcher.start()
        self.arm = ApiResourceManager()

    def tearDown( self ):
        self.patcher.stop()
        reset_arm()

    def test_init_defers_limiter_construction( self ):
        """A freshly-built manager holds no limiter until first web-search use."""
        self.assertIsNone( self.arm._web_search_limiter )

    def test_get_web_search_limiter_constructs_lazily( self ):
        """_get_web_search_limiter() builds the limiter on first call."""
        limiter = self.arm._get_web_search_limiter()
        self.assertIsInstance( limiter, _FakeWebSearchLimiter )
        self.assertIs( self.arm._web_search_limiter, limiter )

    def test_get_web_search_limiter_reuses_instance( self ):
        """Subsequent calls return the cached limiter, not a new one."""
        first  = self.arm._get_web_search_limiter()
        second = self.arm._get_web_search_limiter()
        self.assertIs( first, second )

    def test_acquire_web_search_delegates_to_limiter( self ):
        """acquire('anthropic_web_search') awaits the limiter's wait_if_needed()."""
        asyncio.run( self.arm.acquire( ApiResourceManager._WEB_SEARCH_PROVIDER ) )
        self.assertIsInstance( self.arm._web_search_limiter, _FakeWebSearchLimiter )
        self.assertEqual( self.arm._web_search_limiter.wait_calls, 1 )

    def test_acquire_passthrough_does_not_construct_limiter( self ):
        """acquire() for a passthrough provider returns immediately and builds no limiter."""
        asyncio.run( self.arm.acquire( "openai" ) )
        self.assertIsNone( self.arm._web_search_limiter )

    def test_record_call_web_search_delegates_tokens( self ):
        """record_call('anthropic_web_search', tokens) forwards tokens to record_usage()."""
        self.arm.record_call( ApiResourceManager._WEB_SEARCH_PROVIDER, tokens=123 )
        self.assertEqual( self.arm._web_search_limiter.record_calls, [ ( 123, "web_search" ) ] )

    def test_record_call_passthrough_is_noop( self ):
        """record_call() for a passthrough provider records nothing and builds no limiter."""
        self.arm.record_call( "anthropic", tokens=100 )
        self.assertIsNone( self.arm._web_search_limiter )

    def test_get_status_returns_all_provider_sections( self ):
        """get_status() exposes the web-search section verbatim plus 3 passthrough sections."""
        status = self.arm.get_status()

        # web-search section is a verbatim passthrough of the limiter's status
        self.assertIn( ApiResourceManager._WEB_SEARCH_PROVIDER, status )
        ws = status[ ApiResourceManager._WEB_SEARCH_PROVIDER ]
        for key in (
            "tokens_in_window", "tokens_per_minute_limit", "calls_in_window",
            "window_seconds", "time_until_oldest_expires", "would_need_delay",
        ):
            self.assertIn( key, ws )

        # each passthrough provider gets a uniform marker section
        for provider in ApiResourceManager._PASSTHROUGH_PROVIDERS:
            self.assertEqual(
                status[ provider ], { "provider_wait_state" : "passthrough" }
            )


if __name__ == "__main__":
    unittest.main()
