"""
Notify backpressure — lever E of the messaging-coordination plane.

A per-source (per-`sender_id`) sliding-window rate limiter: at most N sends per
window; over that, the caller is told to back off (429 + Retry-After). Paired with
the durable outbox (Phase 1), which honors `retry-after` on its flush — so a
throttled send is queued + retried, never lost.

Why per-session: under fleet load many sessions each hammer the shared :7999;
per-`sender_id` caps throttle the noisy worker WITHOUT touching the user's
interactive session (which also rides the express lane). Decision: Rick 2026-06-02.

Design: src/rnd/v0.1.8/2026.06.02-messaging-coordination-plane-design.md (lever E1).

The cap VALUE / window / retry-after live in lupin-app.ini and are read mtime-gated
(runtime-tunable, no restart — same pattern as the TTS spoken-brevity cap).
"""

import os
import time
import threading
from collections import defaultdict, deque
from typing import Optional, Tuple


class NotifyRateLimiter:
    """
    Per-source sliding-window limiter. The cap + window are passed in per call so
    they can be tuned at runtime without rebuilding the limiter (state = timestamps).
    Thread-safe (a single lock; the DB/loop work happens elsewhere).
    """

    def __init__( self ):
        self._hits = defaultdict( deque )   # source -> deque[ float timestamps ]
        self._lock = threading.Lock()

    def check_and_record( self, source, max_per_window, window_seconds, now=None ):
        """
        Atomic check-and-record against a sliding window.

        Requires:
            - source is a hashable key (the sender_id)
            - max_per_window is a positive int; window_seconds a positive float

        Ensures:
            - prunes timestamps older than the window first
            - if the window already holds >= max_per_window hits → returns
              (False, retry_after_seconds) and does NOT record
            - otherwise records `now` and returns (True, None)

        Returns:
            (allowed: bool, retry_after_seconds: Optional[float])
        """
        if now is None:
            now = time.time()
        with self._lock:
            dq     = self._hits[ source ]
            cutoff = now - window_seconds
            while dq and dq[ 0 ] <= cutoff:
                dq.popleft()
            if len( dq ) >= max_per_window:
                retry_after = dq[ 0 ] + window_seconds - now
                return ( False, max( 0.0, retry_after ) )
            dq.append( now )
            return ( True, None )

    def reset( self, source=None ):
        """Clear recorded hits — for one source, or all when source is None (tests)."""
        with self._lock:
            if source is None:
                self._hits.clear()
            else:
                self._hits.pop( source, None )


# ── Config (mtime-gated, runtime-tunable) + the enforcement entry point ───────

_BP_DEFAULTS = { "enabled": True, "max": 60, "window": 10.0, "retry_after": 5 }
_bp_cache    = { "cfg": dict( _BP_DEFAULTS ), "ini_mtime": None }
_limiter     = NotifyRateLimiter()


def _backpressure_config():
    """
    Resolve backpressure config from lupin-app.ini, mtime-gated (runtime-tunable).

    Ensures:
        - returns { enabled, max, window, retry_after }
        - re-reads via ConfigurationManager only when the INI mtime changes
        - fails SAFE to the last good value / defaults on any error
    """
    try:
        import cosa.utils.util as cu
        ini_path = cu.get_project_root() + "/src/conf/lupin-app.ini"
        mtime    = os.path.getmtime( ini_path )
        if mtime != _bp_cache[ "ini_mtime" ]:
            from cosa.config.configuration_manager import ConfigurationManager
            cm  = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS", _reset_singleton=True )
            cfg = {
                "enabled"     : cm.get( "messaging backpressure enabled",            default=_BP_DEFAULTS[ "enabled" ],     return_type="boolean", silent=True ),
                "max"         : cm.get( "messaging backpressure max per session",    default=_BP_DEFAULTS[ "max" ],         return_type="int",     silent=True ),
                "window"      : cm.get( "messaging backpressure window seconds",     default=_BP_DEFAULTS[ "window" ],      return_type="float",   silent=True ),
                "retry_after" : cm.get( "messaging backpressure retry after seconds", default=_BP_DEFAULTS[ "retry_after" ], return_type="int",     silent=True ),
            }
            _bp_cache[ "cfg" ]       = cfg
            _bp_cache[ "ini_mtime" ] = mtime
        return _bp_cache[ "cfg" ]
    except Exception:
        return _bp_cache.get( "cfg", dict( _BP_DEFAULTS ) )


def check_notify_allowed( source ) -> Tuple[ bool, Optional[ float ] ]:
    """
    Backpressure gate for a notify from `source` (sender_id).

    Ensures:
        - returns (True, None) when backpressure is disabled in config
        - else consults the per-source sliding window; on deny returns
          (False, retry_after) using the window remainder, or the configured
          floor when the window can't supply one
    """
    cfg = _backpressure_config()
    if not cfg[ "enabled" ]:
        return ( True, None )
    allowed, retry_after = _limiter.check_and_record( source, cfg[ "max" ], cfg[ "window" ] )
    if not allowed:
        return ( False, retry_after if retry_after is not None else float( cfg[ "retry_after" ] ) )
    return ( True, None )
