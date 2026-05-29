#!/usr/bin/env python3
"""
Rate Limiter for COSA Deep Research Agent Web Search.

Implements sliding window token tracking with proactive delay enforcement
to stay within Anthropic's 30,000 tokens/minute web search limit.

Design Principles:
- Proactive delay (wait BEFORE calling) vs reactive (retry after 429)
- Dynamic delay calculation based on actual token usage (no hardcoded delays)
- Sliding window for accurate velocity calculation
- User notification during enforced delays with explanation
- Thread-safe for potential parallel execution
"""

import asyncio
import time
import threading
from dataclasses import dataclass, field
from typing import Optional, Callable, Awaitable
from collections import deque


@dataclass
class TokenRecord:
    """
    Record of tokens used in a single API call.

    Requires:
        - timestamp is a valid Unix timestamp
        - tokens >= 0

    Ensures:
        - Immutable record of token usage
    """
    timestamp : float
    tokens    : int
    call_type : str = "web_search"


class WebSearchRateLimiter:
    """
    Rate limiter for Anthropic web search tool.

    Implements a sliding window algorithm that tracks actual token usage
    and calculates required delays dynamically - no arbitrary minimums.

    Requires:
        - tokens_per_minute > 0
        - window_seconds > 0

    Ensures:
        - Proactive delays before calls to prevent 429 errors
        - Sliding window token tracking over configurable window
        - Thread-safe operation
        - Async-compatible for non-blocking delays
        - User notification for delays with explanation

    Example:
        limiter = WebSearchRateLimiter(
            tokens_per_minute = 30000,
            window_seconds    = 60,
            notify_callback   = my_notify_func,
        )

        # Before each web search call:
        delay = await limiter.wait_if_needed()

        # After receiving response:
        limiter.record_usage( response.input_tokens )
    """

    def __init__(
        self,
        tokens_per_minute     : int   = 30_000,
        window_seconds        : float = 60.0,
        notify_threshold      : float = 5.0,
        notify_callback       : Optional[ Callable[ [ str, str ], Awaitable[ None ] ] ] = None,
        debug                 : bool  = False
    ):
        """
        Initialize the rate limiter.

        Requires:
            - tokens_per_minute > 0
            - window_seconds > 0
            - notify_threshold >= 0

        Args:
            tokens_per_minute: Maximum tokens allowed per minute (Anthropic limit: 30,000)
            window_seconds: Sliding window size for token tracking (default: 60)
            notify_threshold: Only notify user if delay > this many seconds (default: 5)
            notify_callback: Async callback for notifying user about delays
                             Signature: async def callback( message: str, priority: str )
            debug: Enable debug output
        """
        self.tokens_per_minute = tokens_per_minute
        self.window_seconds    = window_seconds
        self.notify_threshold  = notify_threshold
        self.notify_callback   = notify_callback
        self.debug             = debug

        self._records : deque[ TokenRecord ] = deque()
        self._lock    = threading.Lock()

    async def wait_if_needed( self ) -> float:
        """
        Wait if necessary before making a web search call.

        Calculates delay dynamically based on actual tokens in the sliding window.
        If tokens_in_window >= tokens_per_minute, waits until oldest record expires.

        Ensures:
            - Returns delay applied in seconds (0 if no wait needed)
            - Notifies user if waiting > notify_threshold seconds
            - Non-blocking async wait

        Returns:
            float: Seconds waited (0 if no delay needed)
        """
        delay_needed = self._calculate_delay()

        if delay_needed > 0:
            # Notify user about the wait with explanation
            if self.notify_callback and delay_needed > self.notify_threshold:
                tokens_in_window = self.get_tokens_in_window()
                await self.notify_callback(
                    f"Rate limit pause: {tokens_in_window:,} tokens used in the last minute "
                    f"(limit: {self.tokens_per_minute:,}). Waiting {delay_needed:.0f} seconds.",
                    "medium"
                )

            if self.debug:
                print( f"[RateLimiter] Waiting {delay_needed:.1f}s before web search" )

            await asyncio.sleep( delay_needed )

        return delay_needed

    def record_usage( self, tokens: int, call_type: str = "web_search" ) -> None:
        """
        Record tokens used by a completed API call.

        Requires:
            - tokens >= 0

        Ensures:
            - Adds record to sliding window
            - Cleans up expired records

        Args:
            tokens: Actual tokens used (from response.usage.input_tokens)
            call_type: Type of call for tracking (default: "web_search")
        """
        with self._lock:
            now = time.time()
            self._records.append( TokenRecord(
                timestamp = now,
                tokens    = tokens,
                call_type = call_type
            ) )
            self._cleanup_old_records( now )

            if self.debug:
                print( f"[RateLimiter] Recorded {tokens:,} tokens ({call_type}), "
                       f"window total: {self._get_window_tokens():,}" )

    def get_tokens_in_window( self ) -> int:
        """
        Get current tokens in sliding window for user feedback.

        Ensures:
            - Returns sum of tokens from non-expired records
            - Thread-safe

        Returns:
            int: Total tokens currently in the sliding window
        """
        with self._lock:
            now = time.time()
            self._cleanup_old_records( now )
            return self._get_window_tokens()

    def get_estimated_wait_for_next_call( self, estimated_tokens: int = 83_000 ) -> float:
        """
        Estimate wait time for next call given expected token count.

        Useful for giving user feedback about upcoming delays.

        Args:
            estimated_tokens: Expected tokens for upcoming call (default: 83,000)

        Returns:
            float: Estimated seconds until next call can proceed
        """
        with self._lock:
            now = time.time()
            self._cleanup_old_records( now )

            current_tokens = self._get_window_tokens()
            projected_tokens = current_tokens + estimated_tokens

            if projected_tokens < self.tokens_per_minute:
                return 0

            # Find how long until enough tokens expire
            if not self._records:
                return 0

            # Calculate when we'll be back under limit
            # We need to wait until oldest records expire to make room
            target_tokens = self.tokens_per_minute - estimated_tokens
            if target_tokens <= 0:
                # Single call exceeds limit - need full window to expire
                oldest = self._records[ 0 ]
                return max( 0, ( oldest.timestamp + self.window_seconds ) - now )

            # Find when enough tokens will have expired
            cumulative = 0
            for record in self._records:
                cumulative += record.tokens
                if current_tokens - cumulative <= target_tokens:
                    return max( 0, ( record.timestamp + self.window_seconds ) - now )

            return 0

    def estimate_total_time( self, num_calls: int, tokens_per_call: int = 83_000 ) -> float:
        """
        Estimate total time needed for multiple calls.

        Args:
            num_calls: Number of API calls to make
            tokens_per_call: Expected tokens per call (default: 83,000)

        Returns:
            float: Estimated total seconds for all calls
        """
        if num_calls <= 0:
            return 0

        if num_calls == 1:
            return self.get_estimated_wait_for_next_call( tokens_per_call )

        # If each call exceeds the per-minute limit, we need ~1 window per call
        if tokens_per_call >= self.tokens_per_minute:
            # First call may proceed immediately, subsequent need full window
            return ( num_calls - 1 ) * self.window_seconds

        # Calculate how many calls fit in one window
        calls_per_window = max( 1, self.tokens_per_minute // tokens_per_call )
        full_windows = ( num_calls - 1 ) // calls_per_window

        return full_windows * self.window_seconds

    def get_status( self ) -> dict:
        """
        Get current rate limiter status for monitoring.

        Returns:
            dict: Current state including tokens in window, calls, time until next allowed
        """
        with self._lock:
            now = time.time()
            self._cleanup_old_records( now )

            oldest_timestamp = self._records[ 0 ].timestamp if self._records else None
            time_until_oldest_expires = None
            if oldest_timestamp:
                time_until_oldest_expires = max( 0, ( oldest_timestamp + self.window_seconds ) - now )

            return {
                "tokens_in_window"          : self._get_window_tokens(),
                "tokens_per_minute_limit"   : self.tokens_per_minute,
                "calls_in_window"           : len( self._records ),
                "window_seconds"            : self.window_seconds,
                "time_until_oldest_expires" : time_until_oldest_expires,
                "would_need_delay"          : self._get_window_tokens() >= self.tokens_per_minute,
            }

    def _calculate_delay( self ) -> float:
        """
        Calculate required delay before next call.

        Uses DYNAMIC calculation based on actual tokens in window.
        Waits until ENOUGH records expire to get back under limit.

        Returns:
            float: Seconds to wait (0 if no delay needed)
        """
        with self._lock:
            now = time.time()
            self._cleanup_old_records( now )

            tokens_in_window = self._get_window_tokens()

            # If under limit, no delay needed
            if tokens_in_window < self.tokens_per_minute:
                return 0

            # Over limit - find how long until enough records expire
            if not self._records:
                return 0

            # Calculate how many tokens need to expire to get under limit
            tokens_to_remove = tokens_in_window - self.tokens_per_minute + 1

            # Find the record whose expiration brings us under the limit
            cumulative_tokens = 0
            for record in self._records:
                cumulative_tokens += record.tokens
                if cumulative_tokens >= tokens_to_remove:
                    # This record's expiration will bring us under limit
                    time_until_expires = ( record.timestamp + self.window_seconds ) - now
                    return max( 0, time_until_expires )

            # Fallback: wait for all records to expire (shouldn't reach here)
            last_record = self._records[ -1 ]
            return max( 0, ( last_record.timestamp + self.window_seconds ) - now )

    def _get_window_tokens( self ) -> int:
        """Get sum of tokens in current window (must hold lock)."""
        return sum( r.tokens for r in self._records )

    def _cleanup_old_records( self, now: float ) -> None:
        """Remove records outside the sliding window (must hold lock)."""
        cutoff = now - self.window_seconds
        while self._records and self._records[ 0 ].timestamp < cutoff:
            self._records.popleft()


def quick_smoke_test():
    """
    Quick smoke test for WebSearchRateLimiter.

    Requires:
        - asyncio available

    Ensures:
        - Tests instantiation, recording, delay calculation, and async wait
        - Returns True if all tests pass
    """
    import cosa.utils.util as cu

    cu.print_banner( "WebSearchRateLimiter Smoke Test", prepend_nl=True )

    try:
        # Test 1: Instantiation with defaults
        print( "Testing instantiation with defaults..." )
        limiter = WebSearchRateLimiter( debug=True )
        assert limiter.tokens_per_minute == 30_000
        assert limiter.window_seconds == 60.0
        print( "✓ Limiter instantiated with defaults" )

        # Test 2: First call should have no delay (empty window)
        print( "Testing first call (no delay expected)..." )
        delay = limiter._calculate_delay()
        assert delay == 0, f"Expected 0 delay, got {delay}"
        print( "✓ First call has no delay" )

        # Test 3: Record usage
        print( "Testing record_usage..." )
        limiter.record_usage( 83_000, "web_search" )
        tokens = limiter.get_tokens_in_window()
        assert tokens == 83_000, f"Expected 83000 tokens, got {tokens}"
        print( f"✓ Usage recorded: {tokens:,} tokens in window" )

        # Test 4: Second call should require delay (over limit)
        print( "Testing second call (delay expected)..." )
        delay = limiter._calculate_delay()
        assert delay > 0, f"Expected delay > 0, got {delay}"
        print( f"✓ Second call delay: {delay:.1f}s (waiting for window to clear)" )

        # Test 5: Status reporting
        print( "Testing get_status..." )
        status = limiter.get_status()
        assert status[ "tokens_in_window" ] == 83_000
        assert status[ "calls_in_window" ] == 1
        assert status[ "would_need_delay" ] is True
        print( f"✓ Status: {status[ 'calls_in_window' ]} calls, {status[ 'tokens_in_window' ]:,} tokens" )

        # Test 6: Estimate total time
        print( "Testing estimate_total_time..." )
        # With 83k tokens per call and 30k limit, each call after first needs full window
        estimate = limiter.estimate_total_time( num_calls=3, tokens_per_call=83_000 )
        expected = 2 * 60  # 2 full windows (first call immediate, next 2 need waits)
        assert estimate == expected, f"Expected {expected}s, got {estimate}s"
        print( f"✓ Estimated time for 3 calls: {estimate}s" )

        # Test 7: Async wait_if_needed (brief test)
        print( "Testing async wait_if_needed..." )

        async def test_async():
            # Create limiter with very short window for testing
            short_limiter = WebSearchRateLimiter(
                tokens_per_minute = 1000,
                window_seconds    = 0.1,  # 100ms window
                debug             = True
            )

            # First call - no wait
            d1 = await short_limiter.wait_if_needed()
            assert d1 == 0, f"First call should have no delay, got {d1}"

            # Record usage that exceeds limit
            short_limiter.record_usage( 2000 )

            # Second call - should wait for window to clear
            # But window is only 100ms, so wait should be very short
            d2 = await short_limiter.wait_if_needed()
            # d2 might be 0 if window already expired during execution
            return True

        result = asyncio.run( test_async() )
        assert result
        print( "✓ Async wait_if_needed works correctly" )

        # Test 8: Window expiration
        print( "Testing window expiration..." )
        expiry_limiter = WebSearchRateLimiter(
            tokens_per_minute = 30_000,
            window_seconds    = 0.05,  # 50ms window
            debug             = True
        )
        expiry_limiter.record_usage( 50_000 )
        tokens_before = expiry_limiter.get_tokens_in_window()
        assert tokens_before == 50_000

        # Wait for window to expire
        time.sleep( 0.1 )
        tokens_after = expiry_limiter.get_tokens_in_window()
        assert tokens_after == 0, f"Expected 0 tokens after expiry, got {tokens_after}"
        print( "✓ Window expiration clears old records" )

        # Test 9: Multi-record delay calculation
        print( "Testing multi-record delay calculation..." )
        multi_limiter = WebSearchRateLimiter(
            tokens_per_minute = 30_000,
            window_seconds    = 60.0,
            debug             = True
        )
        # Simulate 3 calls of ~90k tokens each
        multi_limiter.record_usage( 90_000 )
        time.sleep( 0.01 )  # Small gap between records
        multi_limiter.record_usage( 90_000 )
        time.sleep( 0.01 )
        multi_limiter.record_usage( 90_000 )

        tokens = multi_limiter.get_tokens_in_window()
        delay = multi_limiter._calculate_delay()
        # With 270k tokens, need to remove 240k to get under 30k
        # That means waiting for 3rd record to expire (all 3 records)
        # Delay should be ~60s (waiting for 3rd record, not just 1st)
        print( f"  Multi-record scenario: {tokens:,} tokens, delay: {delay:.1f}s" )
        assert delay > 50, f"Expected delay > 50s for 270k tokens, got {delay:.1f}s"
        print( "✓ Multi-record delay calculation correct" )

        print( "\n✓ WebSearchRateLimiter smoke test completed successfully" )
        return True

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    quick_smoke_test()
