"""
Unit tests for cosa.agents.deep_research.rate_limiter.WebSearchRateLimiter.

NEW FILE 2026-05-31 by Rio ⚡ (CoSA coverage campaign, deep_research lane). Pure
sliding-window rate-limit math + one async wait method. The module clock
(time.time) is patched to a fixed value for deterministic delays; asyncio.sleep is
stubbed so no real waiting occurs. No network/LLM.

THREE defensive "shouldn't reach here" fallbacks are GENUINELY UNREACHABLE and
listed as pragma candidates in the sub-batch report (window tokens derive from
records, so "over-limit with no records" / "loop exhausts without crossing the
threshold" cannot occur): _calculate_delay :301-302 and :316-318, and
get_estimated_wait_for_next_call :225.
"""

import asyncio
import unittest
from unittest.mock import patch, AsyncMock, Mock

from cosa.agents.deep_research.rate_limiter import WebSearchRateLimiter, TokenRecord


_RL = "cosa.agents.deep_research.rate_limiter"
_NOW = 1000.0


def _limiter( **kw ):
    kw.setdefault( "tokens_per_minute", 30_000 )
    kw.setdefault( "window_seconds", 60.0 )
    return WebSearchRateLimiter( **kw )


def _rec( ts, tokens ):
    return TokenRecord( timestamp=ts, tokens=tokens )


class TestRecordAndWindow( unittest.TestCase ):

    def test_record_usage_appends_and_debug( self ):
        lim = _limiter( debug=True )
        with patch( f"{_RL}.time.time", return_value=_NOW ):
            lim.record_usage( 5000, call_type="web_search" )
        self.assertEqual( len( lim._records ), 1 )
        self.assertEqual( lim._records[ 0 ].tokens, 5000 )
        self.assertEqual( lim._records[ 0 ].timestamp, _NOW )

    def test_get_tokens_in_window_sums( self ):
        lim = _limiter()
        with patch( f"{_RL}.time.time", return_value=_NOW ):
            lim._records.extend( [ _rec( _NOW - 5, 1000 ), _rec( _NOW - 2, 2000 ) ] )
            self.assertEqual( lim.get_tokens_in_window(), 3000 )

    def test_cleanup_removes_expired_on_record( self ):
        lim = _limiter()
        # one stale record (outside 60s window) + record a fresh one → stale dropped
        lim._records.append( _rec( _NOW - 120, 9999 ) )       # expired
        with patch( f"{_RL}.time.time", return_value=_NOW ):
            lim.record_usage( 100 )
        tokens = [ r.tokens for r in lim._records ]
        self.assertEqual( tokens, [ 100 ] )                   # stale 9999 cleaned out


class TestCalculateDelay( unittest.TestCase ):

    def test_under_limit_no_delay( self ):
        lim = _limiter()
        with patch( f"{_RL}.time.time", return_value=_NOW ):
            lim._records.append( _rec( _NOW - 5, 10_000 ) )   # < 30k
            self.assertEqual( lim._calculate_delay(), 0 )

    def test_over_limit_waits_for_record_expiry( self ):
        lim = _limiter()
        with patch( f"{_RL}.time.time", return_value=_NOW ):
            lim._records.append( _rec( _NOW - 10, 40_000 ) )  # ≥ 30k → over limit
            delay = lim._calculate_delay()
        # single 40k record: expires at (now-10)+60 → 50s from now
        self.assertAlmostEqual( delay, 50.0 )

    def test_over_limit_multi_record_picks_crossing_record( self ):
        lim = _limiter()
        with patch( f"{_RL}.time.time", return_value=_NOW ):
            # 3×20k = 60k; need to remove 60k-30k+1 = 30001 → cumulative crosses at 2nd record
            lim._records.extend( [ _rec( _NOW - 30, 20_000 ), _rec( _NOW - 20, 20_000 ), _rec( _NOW - 10, 20_000 ) ] )
            delay = lim._calculate_delay()
        # 2nd record expires at (now-20)+60 = 40s from now
        self.assertAlmostEqual( delay, 40.0 )

    def test_expired_record_brings_under_limit( self ):
        lim = _limiter()
        with patch( f"{_RL}.time.time", return_value=_NOW ):
            # the over-limit record already expired → cleanup drops it → under limit → 0
            lim._records.append( _rec( _NOW - 120, 50_000 ) )
            self.assertEqual( lim._calculate_delay(), 0 )


class TestEstimatedWait( unittest.TestCase ):

    def test_projected_under_limit_zero( self ):
        lim = _limiter()
        with patch( f"{_RL}.time.time", return_value=_NOW ):
            self.assertEqual( lim.get_estimated_wait_for_next_call( estimated_tokens=1000 ), 0 )

    def test_no_records_but_estimate_exceeds_limit( self ):
        lim = _limiter()
        with patch( f"{_RL}.time.time", return_value=_NOW ):
            # estimate alone ≥ limit, no records → projected ≥ limit, then `if not records: return 0`
            self.assertEqual( lim.get_estimated_wait_for_next_call( estimated_tokens=40_000 ), 0 )

    def test_single_call_exceeds_limit_waits_full_window( self ):
        lim = _limiter()
        with patch( f"{_RL}.time.time", return_value=_NOW ):
            lim._records.append( _rec( _NOW - 15, 5_000 ) )
            # estimated 40k ≥ 30k → target_tokens ≤ 0 → oldest expiry: (now-15)+60 = 45
            delay = lim.get_estimated_wait_for_next_call( estimated_tokens=40_000 )
        self.assertAlmostEqual( delay, 45.0 )

    def test_partial_expiry_brings_under_target( self ):
        lim = _limiter()
        with patch( f"{_RL}.time.time", return_value=_NOW ):
            # current 28k, estimate 10k → projected 38k ≥ 30k; target = 30k-10k = 20k
            # need current-cumulative ≤ 20k → after 1st 10k record (28-10=18 ≤ 20) → its expiry
            lim._records.extend( [ _rec( _NOW - 25, 10_000 ), _rec( _NOW - 5, 18_000 ) ] )
            delay = lim.get_estimated_wait_for_next_call( estimated_tokens=10_000 )
        self.assertAlmostEqual( delay, 35.0 )                 # (now-25)+60 = 35

    def test_first_record_does_not_cross_target_loop_continues( self ):
        lim = _limiter()
        with patch( f"{_RL}.time.time", return_value=_NOW ):
            # current 50k, estimate 10k → target 20k. After r0(10k): 50-10=40 > 20 → loop CONTINUES
            # (the 222->220 false arc). After r1(25k): 50-35=15 ≤ 20 → return r1 expiry.
            lim._records.extend( [ _rec( _NOW - 40, 10_000 ), _rec( _NOW - 18, 25_000 ), _rec( _NOW - 5, 15_000 ) ] )
            delay = lim.get_estimated_wait_for_next_call( estimated_tokens=10_000 )
        self.assertAlmostEqual( delay, 42.0 )                 # r1 expires at (now-18)+60 = 42


class TestEstimateTotalTime( unittest.TestCase ):

    def test_non_positive_calls( self ):
        self.assertEqual( _limiter().estimate_total_time( 0 ), 0 )
        self.assertEqual( _limiter().estimate_total_time( -3 ), 0 )

    def test_single_call_delegates( self ):
        lim = _limiter()
        with patch.object( lim, "get_estimated_wait_for_next_call", return_value=12.5 ) as g:
            self.assertEqual( lim.estimate_total_time( 1, tokens_per_call=50_000 ), 12.5 )
        g.assert_called_once_with( 50_000 )

    def test_per_call_exceeds_limit( self ):
        lim = _limiter()
        # tokens_per_call ≥ limit → (num_calls-1) full windows
        self.assertEqual( lim.estimate_total_time( 3, tokens_per_call=83_000 ), 2 * 60.0 )

    def test_multiple_calls_fit_per_window( self ):
        lim = _limiter()
        # 30k limit / 10k per call = 3 calls/window; 7 calls → (7-1)//3 = 2 full windows
        self.assertEqual( lim.estimate_total_time( 7, tokens_per_call=10_000 ), 2 * 60.0 )


class TestGetStatus( unittest.TestCase ):

    def test_status_with_records( self ):
        lim = _limiter()
        with patch( f"{_RL}.time.time", return_value=_NOW ):
            lim._records.append( _rec( _NOW - 10, 35_000 ) )
            status = lim.get_status()
        self.assertEqual( status[ "tokens_in_window" ], 35_000 )
        self.assertEqual( status[ "calls_in_window" ], 1 )
        self.assertTrue( status[ "would_need_delay" ] )       # 35k ≥ 30k
        self.assertAlmostEqual( status[ "time_until_oldest_expires" ], 50.0 )

    def test_status_empty( self ):
        lim = _limiter()
        with patch( f"{_RL}.time.time", return_value=_NOW ):
            status = lim.get_status()
        self.assertEqual( status[ "tokens_in_window" ], 0 )
        self.assertEqual( status[ "calls_in_window" ], 0 )
        self.assertIsNone( status[ "time_until_oldest_expires" ] )
        self.assertFalse( status[ "would_need_delay" ] )


class TestWaitIfNeeded( unittest.IsolatedAsyncioTestCase ):

    async def test_no_delay_returns_zero( self ):
        lim = _limiter()
        with patch.object( lim, "_calculate_delay", return_value=0 ), \
             patch( f"{_RL}.asyncio.sleep", new=AsyncMock() ) as sleep:
            self.assertEqual( await lim.wait_if_needed(), 0 )
        sleep.assert_not_called()

    async def test_delay_with_notify_and_debug( self ):
        cb  = AsyncMock()
        lim = _limiter( notify_callback=cb, notify_threshold=5.0, debug=True )
        with patch.object( lim, "_calculate_delay", return_value=10.0 ), \
             patch( f"{_RL}.asyncio.sleep", new=AsyncMock() ) as sleep:
            delay = await lim.wait_if_needed()
        self.assertEqual( delay, 10.0 )
        cb.assert_awaited_once()                              # delay 10 > threshold 5 → notify
        sleep.assert_awaited_once_with( 10.0 )

    async def test_delay_without_callback( self ):
        lim = _limiter( notify_callback=None )
        with patch.object( lim, "_calculate_delay", return_value=8.0 ), \
             patch( f"{_RL}.asyncio.sleep", new=AsyncMock() ) as sleep:
            delay = await lim.wait_if_needed()
        self.assertEqual( delay, 8.0 )
        sleep.assert_awaited_once_with( 8.0 )

    async def test_delay_below_threshold_no_notify( self ):
        cb  = AsyncMock()
        lim = _limiter( notify_callback=cb, notify_threshold=5.0 )
        with patch.object( lim, "_calculate_delay", return_value=3.0 ), \
             patch( f"{_RL}.asyncio.sleep", new=AsyncMock() ) as sleep:
            await lim.wait_if_needed()
        cb.assert_not_awaited()                               # 3 ≤ threshold 5 → no notify
        sleep.assert_awaited_once_with( 3.0 )


if __name__ == "__main__":
    unittest.main()
