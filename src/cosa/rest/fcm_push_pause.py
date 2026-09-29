"""
Global mobile-push pause — an in-memory override of `fcm wake push enabled`.

Row 7df08e59 (Rick, 2026-09-29, design: src/rnd/v0.2.1/2026.09.29-mobile-push-kill-switch-design.md
§ Revision 1). The ConfigurationManager is a process-wide singleton and `set_config()` changes
memory only, never the INI file. So a pause is: set the key False in memory, and (optionally)
arm a timer that puts it back. Nothing is written to disk and nothing survives a restart —
Rick RULED that in R1.4: the next boot reads the file and pushes resume.

The other half of the mechanism lives in `FcmWakeService.maybe_send_wake`, which re-reads the
live key on every call. Without that, setting the key would change nothing the service looks at.
"""

import asyncio
import threading
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

PUSH_ENABLED_KEY = "fcm wake push enabled"
MAX_PAUSE_MINUTES = 24 * 60   # a typo must not pause pushes for a year


class PushPauseController:
    """
    Owns the pause state, the resume timer and the boot-time value the resume restores.

    Requires:
        - config_mgr has get( key, default, return_type, silent ) and set_config( key, value )

    Ensures:
        - the INI file is never written: every change goes through set_config (memory only)
        - at most ONE resume timer is armed at any moment
        - a resume restores the value the key had at CONSTRUCTION (the boot-time INI value),
          never a hard-coded True, so a server configured off in the file stays off
    """

    def __init__( self, config_mgr, clock: Optional[Callable[[], datetime]]=None ) -> None:
        """
        Requires:
            - constructed at startup, before any pause, so the value captured IS the INI value

        Ensures:
            - self.boot_value holds the key's value now; the state starts un-paused
        """
        self._config_mgr  = config_mgr
        self._clock       = clock if clock is not None else ( lambda: datetime.now( timezone.utc ) )
        self._lock        = threading.Lock()
        self._handle      = None
        self._paused      = False
        self._resumes_at  = None
        self._set_by      = None
        self._set_at      = None
        self.boot_value   = config_mgr.get( PUSH_ENABLED_KEY, default=True, return_type="boolean", silent=True )

    def pause( self, minutes: Optional[int], user: str, loop: asyncio.AbstractEventLoop ) -> dict:
        """
        Turn pushes off in memory, replacing any earlier pause and its timer.

        Requires:
            - minutes is None (until resumed or restarted) or 1..MAX_PAUSE_MINUTES
            - loop is the server's running event loop (call_later is not thread-safe)

        Ensures:
            - the previous resume timer, if any, is cancelled BEFORE the new state is set,
              so an old timer cannot fire in the middle of a newer pause
            - with minutes: exactly one timer is armed for minutes * 60 seconds
            - returns status()

        Raises:
            - ValueError when minutes is outside 1..MAX_PAUSE_MINUTES
        """
        if minutes is not None and not ( 1 <= minutes <= MAX_PAUSE_MINUTES ):
            raise ValueError( f"minutes must be between 1 and {MAX_PAUSE_MINUTES} (24 h); got {minutes}" )
        with self._lock:
            self._cancel_timer_locked()
            now = self._clock()
            self._config_mgr.set_config( PUSH_ENABLED_KEY, False )
            self._paused     = True
            self._set_by     = user
            self._set_at     = now
            self._resumes_at = now + timedelta( minutes=minutes ) if minutes is not None else None
            if minutes is not None:
                self._handle = loop.call_later( minutes * 60, self._on_timer )
        until = self._resumes_at.isoformat() if self._resumes_at is not None else "until resumed or restarted"
        print( f"[FCM-PAUSE] PAUSED by {user} at {now.isoformat()}, {until}" )
        return self.status()

    def resume( self, user: str ) -> dict:
        """
        Turn pushes back to the boot-time value now, cancelling any timer.

        Ensures:
            - the timer is cancelled and the key equals boot_value
            - returns status()
        """
        with self._lock:
            self._restore_locked()
        print( f"[FCM-PAUSE] RESUMED by {user} at {self._clock().isoformat()}" )
        return self.status()

    def status( self ) -> dict:
        """
        Ensures:
            - returns { paused, resumes_at (iso|None), set_by, set_at (iso|None), push_enabled }
              where push_enabled is the LIVE key, so the read-back is never a guess
        """
        with self._lock:
            return {
                "paused"       : self._paused,
                "resumes_at"   : self._resumes_at.isoformat() if self._resumes_at is not None else None,
                "set_by"       : self._set_by,
                "set_at"       : self._set_at.isoformat() if self._set_at is not None else None,
                "push_enabled" : self._config_mgr.get( PUSH_ENABLED_KEY, default=True, return_type="boolean", silent=True ),
            }

    def shutdown( self ) -> None:
        """
        Cancel the timer; log a line when a pause is still active (R1.4: nothing is persisted,
        so a restart ends it, and the log is the only record that it ended early).

        Ensures:
            - no timer remains armed
            - never raises
        """
        with self._lock:
            active = self._paused
            until  = self._resumes_at.isoformat() if self._resumes_at is not None else "no end time"
            by     = self._set_by
            self._cancel_timer_locked()
        if active:
            print( f"[FCM-PAUSE] Shutting down with a push pause ACTIVE (set by {by}, {until}); "
                   f"it is not persisted, so pushes resume at the next boot" )

    def _on_timer( self ) -> None:
        """The armed timer fired: restore the boot-time value."""
        with self._lock:
            self._handle = None   # this timer is spent; nothing to cancel
            self._restore_locked()
        print( f"[FCM-PAUSE] RESUMED by timer at {self._clock().isoformat()}" )

    def _restore_locked( self ) -> None:
        """Caller holds self._lock."""
        self._cancel_timer_locked()
        self._config_mgr.set_config( PUSH_ENABLED_KEY, self.boot_value )
        self._paused     = False
        self._resumes_at = None

    def _cancel_timer_locked( self ) -> None:
        """Caller holds self._lock."""
        if self._handle is not None:
            self._handle.cancel()
            self._handle = None


_controller = None


def init_controller( config_mgr ) -> PushPauseController:
    """
    Build the process-wide controller at startup and return it.

    Ensures:
        - replaces any earlier controller (a re-init in tests, or a lifespan re-run)
    """
    global _controller
    _controller = PushPauseController( config_mgr )
    return _controller


def get_controller() -> PushPauseController:
    """
    Return the process-wide controller, building it from the live config if startup never did.

    Ensures:
        - returns a controller; the lazy path captures the key's current value, which equals
          the boot value only if nothing has set it yet — startup init is what guarantees that
    """
    global _controller
    if _controller is None:
        from cosa.config.configuration_manager import ConfigurationManager
        _controller = PushPauseController( ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" ) )
    return _controller
