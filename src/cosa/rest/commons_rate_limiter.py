"""
In-process sliding-window rate limiter for the commons broadcast endpoint.

Per AC3 + F1 (REUSE) + T4 (Pass 2 Adversarial) of
src/rnd/v0.1.7/2026.05.09-inter-session-commons/03-phase2-user-broadcast-design.md.

**Distinct from `src/cosa/rest/rate_limiter.py`** — that module is auth-specific
(DB-backed `FailedLoginAttemptRepository`, count-based account-lockout). The
broadcast use case needs a different shape: in-process sliding-window per-user
"1 broadcast per N seconds" with `Retry-After` header for HTTP 429 responses.

**Single-uvicorn-worker assumption** (per T4): this module's state is held in a
process-local dict guarded by a `threading.Lock`. If Lupin is ever deployed
with multiple uvicorn workers, this rate limiter ceases to be a global enforcer
(each worker has its own state). Lupin currently runs single-worker per
container — same assumption as `speakerphone.py` `_speakerphone_lock`.
Phase 4 (Postgres-backed commons) is the natural upgrade path if multi-worker
becomes a need.
"""

import threading
import time
from typing import Optional


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
        - State is held in a process-local dict guarded by `self._lock`
        - Entries expire LAZILY — only checked + pruned on the next `check_and_record`
          for that user, plus on explicit `reset()` calls
    """

    def __init__( self, window_seconds: float ):
        if window_seconds <= 0:
            raise ValueError( f"window_seconds must be positive, got {window_seconds}" )
        self.window_seconds = float( window_seconds )
        self._last_post_by_user: dict[ str, float ] = { }
        self._lock = threading.Lock()

    def check_and_record( self, user_id: str ) -> tuple[ bool, Optional[ float ] ]:
        """
        Atomic check-and-record. If the user is within their window, returns
        (False, retry_after_seconds). Otherwise records the current time and
        returns (True, None).

        Lazy expiry: stale entries (older than `window_seconds`) are overwritten
        in place when the user posts again, so the dict size is bounded by the
        active-user count, not by the all-time-user count.
        """
        now = time.monotonic()
        with self._lock:
            last = self._last_post_by_user.get( user_id )
            if last is not None:
                elapsed = now - last
                if elapsed < self.window_seconds:
                    retry_after = self.window_seconds - elapsed
                    return ( False, retry_after )
            self._last_post_by_user[ user_id ] = now
            return ( True, None )

    def reset( self, user_id: Optional[ str ] = None ) -> None:
        """
        Test-only hook. When `user_id` is None, clears ALL state (for whole-module
        isolation between test cases). When `user_id` is supplied, clears that
        user's entry only.

        Production code MUST NOT call this. Tests should call it in setup/teardown.
        """
        with self._lock:
            if user_id is None:
                self._last_post_by_user.clear()
            else:
                self._last_post_by_user.pop( user_id, None )

    def _peek( self, user_id: str ) -> Optional[ float ]:
        """Test-only inspection of the last-post time for a user. Returns None if unset."""
        with self._lock:
            return self._last_post_by_user.get( user_id )
