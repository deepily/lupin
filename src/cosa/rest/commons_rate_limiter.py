"""
In-process sliding-window rate limiter for the commons broadcast endpoint.

Design: src/rnd/v0.1.7/2026.05.09-inter-session-commons/03-phase2-user-broadcast-design.md

**Distinct from `src/cosa/rest/rate_limiter.py`** — that module is auth-specific
(DB-backed `FailedLoginAttemptRepository`, count-based account-lockout). The
broadcast use case needs a different shape: in-process sliding-window per-user
"1 broadcast per N seconds" with `Retry-After` header for HTTP 429 responses.

**Single-uvicorn-worker assumption**: this module's state is held in a
process-local dict guarded by a `threading.Lock`. If Lupin is ever deployed
with multiple uvicorn workers, this rate limiter ceases to be a global enforcer
(each worker has its own state). Lupin currently runs single-worker per
container — same assumption as `speakerphone.py` `_speakerphone_lock`.
A Postgres-backed commons is the natural upgrade path if multi-worker
becomes a need.
"""

import time
from typing import Optional

from cosa.rest.notify_rate_limiter import NotifyRateLimiter


class CommonsBroadcastRateLimiter:
    """
    Sliding-window per-user rate limiter for broadcast POST requests.

    Requires:
        - `window_seconds` is a positive float (the slide window length)

    Ensures:
        - `check_and_record(user_id)` returns (allowed, retry_after_seconds)
        - `allowed=True` means the call is within the window quota (1 per window)
        - `allowed=False` means the window's quota is exhausted; `retry_after_seconds`
          is the seconds remaining until the limiter clears for that user
        - State is held by a `NotifyRateLimiter` (limit 1 per window), whose lock guards it
        - Entries expire lazily — only checked + pruned on the next `check_and_record`
          for that user, plus on explicit `reset()` calls
    """

    def __init__( self, window_seconds: float ):
        """
        Set the window length in seconds and start with no user recorded.

        Ensures:
            - window_seconds is kept as a float

        Raises:
            - ValueError when window_seconds is zero or negative
        """
        if window_seconds <= 0:
            raise ValueError( f"window_seconds must be positive, got {window_seconds}" )
        self.window_seconds = float( window_seconds )
        self._core          = NotifyRateLimiter()

    def check_and_record( self, user_id: str ) -> tuple[ bool, Optional[ float ] ]:
        """
        Atomically check a user against the window, recording the call if allowed.

        Returns (False, retry_after_seconds) when the user is within their window.
        Otherwise it records the current time and returns (True, None).

        Stale entries (older than `window_seconds`) are pruned when the user
        posts again. The state size is therefore bounded by the active-user
        count, not by the all-time-user count.
        """
        return self._core.check_and_record( user_id, 1, self.window_seconds, now=time.monotonic() )

    def reset( self, user_id: Optional[ str ] = None ) -> None:
        """
        Test-only hook that clears the stored rate-limit state.

        With `user_id` None it clears every user (whole-module isolation between
        test cases). With `user_id` supplied it clears that user's entry only.
        Production code never calls it. Tests call it in setup and teardown.
        """
        self._core.reset( user_id )

    def _peek( self, user_id: str ) -> Optional[ float ]:
        """Test-only inspection of the last-post time for a user. Returns None if unset."""
        hits = self._core._hits.get( user_id )
        return hits[ -1 ] if hits else None
