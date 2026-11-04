"""
FCM wake-push sender, the silent-relay backend for the mobile app.

Sends a content-free, high-priority, data-only `ws_wake` push to a user's registered
mobile devices. It fires when the parent has traffic for them and no live mobile queue-WS
exists. The push is a summons, not a message: no `notification` block, no content, no sender
identity. The woken handler fetches everything over the authenticated notifications API.

Trigger policy lives entirely in this class (`maybe_send_wake`). The notification
fan-out hook therefore stays a one-liner. Every policy arm is unit-testable: enabled,
no live mobile WS, debounce, at least one registered token, send.

Firebase separation: the real `firebase_admin` FCM init here is a separate touchpoint from
the mock Firebase auth layer in `auth.py`. It has distinct credentials (own INI-named env
var), a named firebase app ("lupin-fcm-wake"), and zero shared initialization.

Firebase-absent tolerance: console provisioning is a later human step. Until the
service-account JSON exists, or if `firebase_admin` is not installed, the service boots
disabled with one clear log line. Every wake attempt then returns "disabled". It never
raises and never crashes the notification path.

See: lupin-mobile/src/rnd/2026.06.11-focus-mode-voice-chat/15-section-s6-fcm-backend-interface.md
(in the sibling lupin-mobile repo)
"""

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Callable, List, Optional

# The two-value reason ENUM (S6 §3.2, aligned with S5 §3.1 per F-S5-2.ii).
# Value semantics (parent-pinned per the Stage-2 residual fold):
#     "undelivered"    — the notification-enqueued trigger (§3.3); the ONLY
#                        automatic emitter in v1
#     "reconnect-hint" — administrative/manual summons (debug or test sends,
#                        future server-lifecycle hints); informational
WAKE_REASON_UNDELIVERED    = "undelivered"
WAKE_REASON_RECONNECT_HINT = "reconnect-hint"
WAKE_REASONS               = ( WAKE_REASON_UNDELIVERED, WAKE_REASON_RECONNECT_HINT )

FIREBASE_APP_NAME = "lupin-fcm-wake"


def build_wake_payload( reason: str ) -> dict:
    """
    Build the data-only `ws_wake` payload in its contract shape.

    FCM data payloads are string→string maps, so every value is a str.

    Requires:
        - reason is one of WAKE_REASONS ("undelivered" | "reconnect-hint")

    Ensures:
        - returns the key set {"type", "reason", "ts"} — content-free
        - "type" is the literal "ws_wake"
        - "ts" is an ISO-8601 UTC timestamp
        - all values are strings

    Raises:
        - ValueError if reason is not in the two-value enum
    """
    if reason not in WAKE_REASONS:
        raise ValueError( f"FCM wake reason {reason!r} is not in the contract enum {WAKE_REASONS}" )

    return {
        "type"   : "ws_wake",
        "reason" : reason,
        "ts"     : datetime.now( timezone.utc ).isoformat( timespec="seconds" )
    }


def _default_timer_factory( delay: float, callback: Callable[[], None] ) -> threading.Timer:
    """
    Build the one-shot daemon timer a deferred wake rides.

    A plain threading.Timer is non-daemon, so a pending trailing wake would hold the
    process open for the rest of its window at shutdown. Nothing about a wake is worth
    delaying an exit for.

    Requires:
        - delay is a non-negative number of seconds
        - callback takes no arguments

    Ensures:
        - returns an unstarted daemon timer (the caller starts it, so the
          pending-marker write and the start happen under one lock)

    Raises:
        - None
    """
    timer        = threading.Timer( delay, callback )
    timer.daemon = True
    return timer


class FcmWakeService:
    """
    Debounced, policy-gated FCM wake-push sender.

    Collaborators are injected as callables, so the service has zero import-time
    coupling to the token store or the WebSocket manager. It is trivially
    unit-testable with fakes.

    - token_lookup( user_id )    -> List[str]  registered FCM tokens
    - mobile_liveness( user_id ) -> bool       live mobile queue-WS exists?
    - transport( token, data )   -> None       delivers one wake

    A transport of None means the real firebase_admin transport when credentials
    resolve, else disabled.

    Usage:
        service = FcmWakeService( config_mgr,
                                  token_lookup    = repo_lookup,
                                  mobile_liveness = ws_manager.has_live_mobile_session )
        service.maybe_send_wake( user_id )   # called from notification fan-out
    """

    def __init__( self, config_mgr, token_lookup: Callable[[str], List[str]],
                  mobile_liveness: Callable[[str], bool],
                  transport: Optional[Callable[[str, dict], None]] = None,
                  debug: bool = False, verbose: bool = False,
                  timer_factory: Optional[Callable[[float, Callable[[], None]], Any]] = None ):
        """
        Initialize the wake service, resolving Firebase credentials if present.

        Requires:
            - config_mgr is a ConfigurationManager
            - token_lookup is a callable user_id -> list of token strings
            - mobile_liveness is a callable user_id -> bool
            - transport (optional) overrides the real FCM transport (tests)
            - timer_factory (optional) builds the deferred-wake timer; it takes
              ( delay_seconds, zero-arg callback ) and returns an object with
              start() and cancel(). Defaults to _default_timer_factory

        Ensures:
            - self.enabled is True only when the master INI switch is on and a
              working transport exists (injected, or real firebase_admin init
              succeeded — via the "fcm wake auth mode" fork: "key_file" against
              the service-account JSON at the INI-named env var, or "adc" via
              Application Default Credentials)
            - when disabled, self.disabled_reason names the single cause and one
              clear log line was printed — construction never raises
            - per-user debounce window loaded from "fcm wake debounce seconds"
              (default 60)
            - at most one pending trailing wake per user
            - auth mode loaded from "fcm wake auth mode" (default "key_file")

        Raises:
            - None (all init failure modes degrade to disabled)
        """
        self.debug             = debug
        self.verbose           = verbose
        self._config_mgr       = config_mgr   # kept so the live push switch can be re-read per call (row 7df08e59)
        self._token_lookup     = token_lookup
        self._mobile_liveness  = mobile_liveness
        self._transport        = transport
        self.disabled_reason   = None

        self.debounce_seconds  = config_mgr.get( "fcm wake debounce seconds", default=60, return_type="int", silent=True )
        master_switch          = config_mgr.get( "fcm wake push enabled", default=True, return_type="boolean", silent=True )
        self._credentials_env  = config_mgr.get( "fcm service account credentials env var", default="FCM_SERVICE_ACCOUNT_JSON", silent=True )
        self._auth_mode        = config_mgr.get( "fcm wake auth mode", default="key_file", silent=True )

        # Per-user debounce state: user_id → monotonic time of last wake attempt.
        # In-memory by design — a debounce window is transient state; a restart
        # resetting it costs at most one extra (harmless) wake per user.
        self._last_wake_at = {}
        self._debounce_lock = threading.Lock()

        # Row ed76b897: a notify arriving INSIDE a debounce window used to return
        # "debounced" and end there — no wake, no deferral, and (the arm was gated
        # on debug AND verbose) no log line either. The item then sat unplayed
        # until something else woke the device. One trailing wake per user is
        # scheduled instead, and this map is what makes it ONE: a burst inside a
        # window collapses onto the timer already here, rather than becoming a
        # burst of pushes when the window closes. Guarded by _debounce_lock, the
        # same lock the window itself is read under — the pending marker and the
        # window are one decision and must not be read apart.
        self._timer_factory  = timer_factory or _default_timer_factory
        self._pending_timers = {}

        # Single worker keeps the notification emit path non-blocking: the
        # network send rides this executor, never the caller's thread.
        self._executor = ThreadPoolExecutor( max_workers=1, thread_name_prefix="fcm-wake" )

        if not master_switch:
            self._disable( "master switch 'fcm wake push enabled' is false" )
        elif self._transport is not None:
            self.enabled = True
            if self.debug: print( "[FCM-WAKE] Enabled with injected transport" )
        else:
            self.enabled = self._init_real_transport()

    def _disable( self, reason: str ) -> None:
        """
        Mark the service disabled with a single, clear, greppable log line.

        Requires:
            - reason is a non-empty human-readable string

        Ensures:
            - self.enabled is False and self.disabled_reason is set
            - exactly one [FCM-WAKE] `DISABLED` line is printed
        """
        self.enabled         = False
        self.disabled_reason = reason
        print( f"[FCM-WAKE] DISABLED — {reason}. Wake pushes will not be sent; "
               f"the mobile silent-relay channel is offline until this is resolved (see OSQ-7 runbook)." )

    def _init_real_transport( self ) -> bool:
        """
        Initialize the named FCM app via the configured auth mode.

        Two permanent auth modes fork on the "fcm wake auth mode" INI key; neither is a
        deprecation ramp.

        Requires:
            - self._auth_mode is "key_file" or "adc"
            - in "key_file" mode, self._credentials_env names the env var holding
              the JSON path

        Ensures:
            - returns True with self._transport set on success
            - returns False after _disable() naming the exact failure arm:
              key_file → env var unset, file missing, module missing, init error;
              adc → module missing, ADC resolution / init error
            - "key_file" (the default) resolves a downloaded Firebase service-account JSON
              via the INI-named env var, then `credentials.Certificate(path)`
            - "adc" resolves Application Default Credentials (the runtime service account,
              e.g. the GCE VM's attached SA) via `credentials.ApplicationDefault()`, with no
              key file and no env var; org policy `iam.disableServiceAccountKeyCreation`
              requires this keyless path
            - both arms feed the same get_app/initialize_app + messaging transport flow,
              with their own credential object and named app, sharing no state with the
              mock Firebase auth layer in auth.py
            - never raises
        """
        if self._auth_mode == "adc":
            return self._init_real_transport_adc()
        return self._init_real_transport_key_file()

    def _init_real_transport_key_file( self ) -> bool:
        """
        Initialize the named FCM app from a downloaded service-account JSON key.

        The default key-file auth path. Resolves the JSON path from the INI-named env
        var, requires the file to exist, then builds a `credentials.Certificate` and
        feeds the shared init flow.

        Requires:
            - self._credentials_env names the env var holding the JSON path

        Ensures:
            - returns True with self._transport set on success
            - returns False after _disable() naming the exact failure arm:
              env var unset, file missing, module missing, or init error
            - never raises
        """
        credentials_path = os.environ.get( self._credentials_env )
        if not credentials_path:
            self._disable( f"env var {self._credentials_env} is not set (Firebase service-account JSON not yet provisioned)" )
            return False

        if not os.path.isfile( credentials_path ):
            self._disable( f"credentials file not found at {self._credentials_env}={credentials_path}" )
            return False

        try:
            import firebase_admin
            from firebase_admin import credentials, messaging
        except ImportError as e:
            self._disable( f"firebase_admin not importable ({e}) — install the 'firebase-admin' dependency" )
            return False

        try:
            cred = credentials.Certificate( credentials_path )
        except Exception as e:
            self._disable( f"Firebase init failed for {self._credentials_env}={credentials_path}: {type( e ).__name__}: {e}" )
            return False

        return self._finalize_real_transport( firebase_admin, messaging, cred, f"key_file from {self._credentials_env}" )

    def _init_real_transport_adc( self ) -> bool:
        """
        Initialize the named FCM app from Application Default Credentials (keyless).

        The keyless ADC path: no key file, no env var. It resolves the runtime service
        account via `credentials.ApplicationDefault()`, then feeds the shared init flow.
        Org policy `iam.disableServiceAccountKeyCreation` makes it the only option.

        Requires:
            - the runtime environment exposes Application Default Credentials
              (an attached service account, or GOOGLE_APPLICATION_CREDENTIALS)

        Ensures:
            - returns True with self._transport set on success
            - returns False after _disable() naming the exact failure arm:
              module missing, or ADC resolution / init error
            - never raises
        """
        try:
            import firebase_admin
            from firebase_admin import credentials, messaging
        except ImportError as e:
            self._disable( f"firebase_admin not importable ({e}) — install the 'firebase-admin' dependency" )
            return False

        try:
            cred = credentials.ApplicationDefault()
        except Exception as e:
            self._disable( f"Application Default Credentials could not be resolved (ADC auth mode): {type( e ).__name__}: {e}" )
            return False

        return self._finalize_real_transport( firebase_admin, messaging, cred, "ADC" )

    def _finalize_real_transport( self, firebase_admin, messaging, cred, source_label: str ) -> bool:
        """
        Build the named FCM app and messaging transport from a resolved credential.

        Shared tail of both auth arms: get-or-create the named app, wire the data-only
        high-priority transport, and emit the single Enabled log line. The calling arm
        already imported firebase_admin and messaging, so no import guard is repeated.

        Requires:
            - firebase_admin and messaging are the imported firebase_admin modules
            - cred is a resolved firebase_admin credential object
            - source_label names the credential source for the log line

        Ensures:
            - returns True with self._transport set on success
            - returns False after _disable() on any get_app/init/transport error
            - never raises
        """
        try:
            try:
                app = firebase_admin.get_app( FIREBASE_APP_NAME )
            except ValueError:
                app = firebase_admin.initialize_app( cred, name=FIREBASE_APP_NAME )

            def _real_transport( token: str, data: dict ) -> None:
                message = messaging.Message(
                    token   = token,
                    data    = data,
                    android = messaging.AndroidConfig( priority="high" )
                )
                messaging.send( message, app=app )

            self._transport = _real_transport
            print( f"[FCM-WAKE] Enabled — Firebase app '{FIREBASE_APP_NAME}' initialized ({source_label})" )
            return True
        except Exception as e:
            self._disable( f"Firebase init failed ({source_label}): {type( e ).__name__}: {e}" )
            return False

    def maybe_send_wake( self, user_id: str, reason: str = WAKE_REASON_UNDELIVERED ) -> str:
        """
        Apply the full trigger policy and submit a wake if it passes.

        Policy order (cheapest first): enabled, no live mobile WS, debounce, at least
        one registered token, off-thread send. Called synchronously from the fan-out
        path, so everything on this thread is in-memory except the indexed token lookup.

        Requires:
            - user_id is a non-empty string
            - reason is one of WAKE_REASONS

        Ensures:
            - returns a status string naming the outcome arm:
              "disabled" | "paused" | "mobile_ws_live" | "deferred" | "debounced" |
              "no_tokens" | "submitted"
            - "paused" means the live `fcm wake push enabled` key is False (an admin
              pause): nothing else ran — no liveness check, no debounce slot burned,
              no token lookup
            - "deferred": this call scheduled a trailing wake; "debounced": one was
              already pending and this call collapsed onto it
            - a notify inside a live debounce window is deferred, never dropped: the
              first schedules one trailing wake for the moment the window closes, and
              every later one collapses onto it
            - the trailing wake re-runs this whole method with no override, so a device
              that reconnected meanwhile is not woken: a deferral is a request, not a
              promise
            - the trailing wake honours the window like any other caller. A descheduled
              timer fires late, when an ordinary notify may have opened a new window, and
              a forced send would put two wakes inside it. Woken early it would send
              before the window closed. Re-entering here avoids both: it re-defers for
              what is left, and each delay strictly decreases, so it converges
            - never more than one wake per user per window, including from a late timer
            - at most one wake per user per debounce window, and at most one
              pending trailing wake per user (the slot is burned at attempt time,
              even when the token lookup then comes up empty)
            - the send itself runs on the executor; this method never blocks on
              the network and never raises (the fan-out path must stay safe)

        Raises:
            - None (lookup/send failures are logged, not propagated)
        """
        if not self.enabled:
            return "disabled"

        # Row 7df08e59 — the admin pause. `self.enabled` is a COPY taken at startup, so a
        # set_config() on the key changes nothing it looks at; the live key is re-read here on
        # every call. It sits BEFORE the liveness check, the debounce and the token lookup so a
        # paused server does no work at all, and because a trailing wake re-enters this method
        # it also stops any wake already scheduled. The boot-time INI value is restored by
        # cosa.rest.fcm_push_pause, not here.
        if not self._config_mgr.get( "fcm wake push enabled", default=True, return_type="boolean", silent=True ):
            return "paused"

        try:
            if self._mobile_liveness( user_id ):
                if self.debug and self.verbose: print( f"[FCM-WAKE] Skipping wake for {user_id}: live mobile WS" )
                return "mobile_ws_live"

            now = time.monotonic()
            with self._debounce_lock:
                last = self._last_wake_at.get( user_id )
                if last is not None and ( now - last ) < self.debounce_seconds:
                    remaining = self.debounce_seconds - ( now - last )
                    scheduled = self._schedule_trailing_wake_locked( user_id, reason, remaining )
                    if not scheduled:
                        if self.debug: print( f"[FCM-WAKE] Debounced wake for {user_id} — a trailing wake is already pending" )
                        return "debounced"
                    # UNGATED. The measured failure (row ed76b897) was SILENCE: a
                    # notify 37 s into a window produced no wake and no line saying
                    # so, and debug being off is exactly the condition under which
                    # that goes unread. One line per window per user is cheap; the
                    # per-notify collapse above stays gated so a burst cannot flood.
                    print( f"[FCM-WAKE] DEFERRED wake for {user_id}: inside the "
                           f"{self.debounce_seconds}s window, trailing wake scheduled in "
                           f"{remaining:.1f}s (reason={reason})" )
                    return "deferred"
                self._last_wake_at[ user_id ] = now

            tokens = self._token_lookup( user_id )
            if not tokens:
                return "no_tokens"

            payload = build_wake_payload( reason )
            self._executor.submit( self._send_to_all, user_id, list( tokens ), payload )
            if self.debug: print( f"[FCM-WAKE] Wake submitted for {user_id}: {len( tokens )} device(s), reason={reason}" )
            return "submitted"
        except Exception as e:
            print( f"[FCM-WAKE] ⚠️ Wake policy error for user {user_id}: {type( e ).__name__}: {e}" )
            return "error"

    def _schedule_trailing_wake_locked( self, user_id: str, reason: str, delay: float ) -> bool:
        """
        Arm the one trailing wake for a user whose window is still open.

        Caller must hold self._debounce_lock. The pending marker and the window it
        belongs to are a single decision. Reading them apart would let two notifies
        each believe they were first.

        Requires:
            - self._debounce_lock is held by the calling thread
            - delay is the seconds remaining in user_id's debounce window

        Ensures:
            - returns False and changes nothing when a trailing wake is already
              pending for this user (the collapse arm)
            - otherwise builds, records and starts one timer, and returns True
            - the timer is recorded before it is started, so a timer that fires
              immediately still finds its own marker to clear

        Raises:
            - None
        """
        if user_id in self._pending_timers:
            return False

        timer = self._timer_factory( delay, lambda: self._fire_trailing_wake( user_id, reason ) )
        self._pending_timers[ user_id ] = timer
        timer.start()
        return True

    def _fire_trailing_wake( self, user_id: str, reason: str ) -> str:
        """
        Run the deferred wake now that the window has closed (timer thread).

        Requires:
            - the debounce window this was deferred for has elapsed

        Ensures:
            - releases the pending marker first, so a notify arriving during this
              call can arm the next window's trailing wake rather than being lost —
              and so a re-defer has a free marker to take
            - re-runs the full policy with no override: a device that reconnected
              returns "mobile_ws_live" and is not woken, an empty token list
              returns "no_tokens", and a window that is somehow still open (a
              late or early timer) returns "deferred" — re-armed, not dropped
            - logs the outcome whatever the debug flags — nothing returns this value to a
              caller, so the log line is the only place the outcome is visible
            - never raises: this runs on a timer thread with nobody to catch it

        Raises:
            - None
        """
        with self._debounce_lock:
            self._pending_timers.pop( user_id, None )

        status = self.maybe_send_wake( user_id, reason )
        print( f"[FCM-WAKE] TRAILING wake for {user_id} fired at window close: {status} (reason={reason})" )
        return status

    def shutdown( self ) -> None:
        """
        Cancel every pending trailing wake and stop the send executor.

        Requires:
            - None (safe to call with nothing pending, and more than once)

        Ensures:
            - every pending timer is cancelled and self._pending_timers is empty
            - the send executor is shut down

        Raises:
            - None
        """
        with self._debounce_lock:
            for timer in self._pending_timers.values():
                timer.cancel()
            self._pending_timers.clear()
        self._executor.shutdown( wait=False )

    def _send_to_all( self, user_id: str, tokens: List[str], payload: dict ) -> int:
        """
        Deliver the wake payload to every registered device (executor thread).

        Requires:
            - tokens is a non-empty list of FCM token strings
            - payload is a build_wake_payload() dict

        Ensures:
            - attempts every token even when earlier ones fail (per-token
              isolation — one dead token must not mask a live device)
            - returns the count of successful sends
            - never raises (executor thread must not die)
        """
        sent = 0
        for token in tokens:
            try:
                self._transport( token, payload )
                sent += 1
            except Exception as e:
                print( f"[FCM-WAKE] ⚠️ Send failed for user {user_id} token …{token[ -8: ]}: {type( e ).__name__}: {e}" )
        if self.debug: print( f"[FCM-WAKE] Wake delivered for {user_id}: {sent}/{len( tokens )} device(s)" )
        return sent


def quick_smoke_test():
    """
    Quick smoke test for FcmWakeService — disabled boot, policy arms, payload contract.

    Ensures:
        - disabled construction never raises with no Firebase anywhere
        - payload builder pins the contract shape + enum
        - injected-transport policy walk reaches "submitted"
    """
    import cosa.utils.util as du
    du.print_banner( "FcmWakeService Smoke Test", prepend_nl=True )

    class _FakeConfig:
        def get( self, key, default=None, return_type=None, silent=False ): return default

    try:
        # Test 1: Firebase-absent boot tolerance
        service = FcmWakeService( _FakeConfig(), token_lookup=lambda u: [], mobile_liveness=lambda u: False )
        assert service.enabled is False and service.disabled_reason
        assert service.maybe_send_wake( "u1" ) == "disabled"
        print( "✓ Disabled boot (no credentials) tolerated" )

        # Test 2: payload contract
        payload = build_wake_payload( WAKE_REASON_UNDELIVERED )
        assert set( payload.keys() ) == { "type", "reason", "ts" } and payload[ "type" ] == "ws_wake"
        try:
            build_wake_payload( "bogus" )
            assert False, "enum violation accepted"
        except ValueError:
            pass
        print( "✓ Payload contract pinned (keys + enum)" )

        # Test 3: full policy walk with injected transport
        sent = []
        service = FcmWakeService( _FakeConfig(), token_lookup=lambda u: [ "tok-1" ],
                                  mobile_liveness=lambda u: False, transport=lambda t, d: sent.append( t ) )
        assert service.maybe_send_wake( "u2" ) == "submitted"
        # Row ed76b897: the second notify lands inside the window and is DEFERRED —
        # it arms one trailing wake rather than being dropped. A third collapses
        # onto that same pending timer instead of arming a second.
        assert service.maybe_send_wake( "u2" ) == "deferred"
        assert service.maybe_send_wake( "u2" ) == "debounced"
        service.shutdown()
        service._executor.shutdown( wait=True )
        assert sent == [ "tok-1" ]
        print( "✓ Policy walk: submitted → deferred → debounced, transport hit once" )

        print( "\n✓ FcmWakeService smoke test PASSED" )
    except Exception as e:
        print( f"\n✗ FcmWakeService smoke test FAILED: {e}" )
        raise


if __name__ == "__main__":
    quick_smoke_test()
