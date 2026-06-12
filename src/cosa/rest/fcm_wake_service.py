"""
FCM wake-push sender — the S6 silent-relay backend (Q10).

Sends a content-free, high-priority, DATA-ONLY `ws_wake` push to a user's
registered mobile devices when the parent has traffic for them and no live
MOBILE queue-WS exists (S6 §3.2/§3.3). The push is a summons, not a message:
NO `notification` block, NO content, NO sender identity — the woken handler
fetches everything over the authenticated notifications API.

Trigger policy lives entirely in this class (`maybe_send_wake`) so the
notification fan-out hook stays a one-liner and every policy arm is unit-
testable: enabled → no-live-mobile-WS → debounce → ≥1 registered token → send.

Firebase separation (F-S6-2): the REAL `firebase_admin` FCM init here is a
SEPARATE touchpoint from the MOCK Firebase AUTH layer in `auth.py` — distinct
credentials (own INI-named env var), a NAMED firebase app ("lupin-fcm-wake"),
zero shared initialization.

Firebase-absent tolerance (OSQ-7): console provisioning is a later HUMAN step.
Until the service-account JSON exists (or if `firebase_admin` isn't installed),
the service boots DISABLED with one clear log line and every wake attempt
returns "disabled" — it never raises, never crashes the notification path.

See: src/lupin-mobile/src/rnd/2026.06.11-focus-mode-voice-chat/15-section-s6-fcm-backend-interface.md
"""

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Callable, List, Optional

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
    Build the data-only `ws_wake` payload (S6 §3.2 contract shape).

    FCM data payloads are string→string maps, so every value is a str.

    Requires:
        - reason is one of WAKE_REASONS ("undelivered" | "reconnect-hint")

    Ensures:
        - returns exactly the keys {"type", "reason", "ts"} — content-free
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


class FcmWakeService:
    """
    Debounced, policy-gated FCM wake-push sender.

    Collaborators are injected as callables so the service has zero import-time
    coupling to the token store or the WebSocket manager (and is trivially
    unit-testable with fakes):

        token_lookup( user_id )    -> List[str]  registered FCM tokens
        mobile_liveness( user_id ) -> bool       live mobile queue-WS exists?
        transport( token, data )   -> None       delivers one wake (None ⇒ real
                                                 firebase_admin transport when
                                                 credentials resolve, else disabled)

    Usage:
        service = FcmWakeService( config_mgr,
                                  token_lookup    = repo_lookup,
                                  mobile_liveness = ws_manager.has_live_mobile_session )
        service.maybe_send_wake( user_id )   # called from notification fan-out
    """

    def __init__( self, config_mgr, token_lookup: Callable[[str], List[str]],
                  mobile_liveness: Callable[[str], bool],
                  transport: Optional[Callable[[str, dict], None]] = None,
                  debug: bool = False, verbose: bool = False ):
        """
        Initialize the wake service, resolving Firebase credentials if present.

        Requires:
            - config_mgr is a ConfigurationManager
            - token_lookup is a callable user_id -> list of token strings
            - mobile_liveness is a callable user_id -> bool
            - transport (optional) overrides the real FCM transport (tests)

        Ensures:
            - self.enabled is True only when the master INI switch is on AND a
              working transport exists (injected, or real firebase_admin init
              succeeded against the service-account JSON at the INI-named env var)
            - when disabled, self.disabled_reason names the single cause and one
              clear log line was printed — construction NEVER raises (OSQ-7)
            - per-user debounce window loaded from "fcm wake debounce seconds"
              (default 60)

        Raises:
            - None (all init failure modes degrade to disabled)
        """
        self.debug             = debug
        self.verbose           = verbose
        self._token_lookup     = token_lookup
        self._mobile_liveness  = mobile_liveness
        self._transport        = transport
        self.disabled_reason   = None

        self.debounce_seconds  = config_mgr.get( "fcm wake debounce seconds", default=60, return_type="int", silent=True )
        master_switch          = config_mgr.get( "fcm wake push enabled", default=True, return_type="boolean", silent=True )
        self._credentials_env  = config_mgr.get( "fcm service account credentials env var", default="FCM_SERVICE_ACCOUNT_JSON", silent=True )

        # Per-user debounce state: user_id → monotonic time of last wake attempt.
        # In-memory by design — a debounce window is transient state; a restart
        # resetting it costs at most one extra (harmless) wake per user.
        self._last_wake_at = {}
        self._debounce_lock = threading.Lock()

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
            - exactly one [FCM-WAKE] DISABLED line is printed
        """
        self.enabled         = False
        self.disabled_reason = reason
        print( f"[FCM-WAKE] DISABLED — {reason}. Wake pushes will not be sent; "
               f"the mobile silent-relay channel is offline until this is resolved (see OSQ-7 runbook)." )

    def _init_real_transport( self ) -> bool:
        """
        Lazily import firebase_admin and initialize the NAMED FCM app.

        Kept separate from the mock Firebase AUTH layer in auth.py (F-S6-2):
        own env var, own credential object, own named app — no shared state.

        Requires:
            - self._credentials_env names the env var holding the JSON path

        Ensures:
            - returns True with self._transport set on success
            - returns False after _disable() naming the exact failure arm:
              env var unset, file missing, module missing, or init error
            - NEVER raises (OSQ-7 tolerance)
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
            print( f"[FCM-WAKE] Enabled — Firebase app '{FIREBASE_APP_NAME}' initialized from {self._credentials_env}" )
            return True
        except Exception as e:
            self._disable( f"Firebase init failed for {self._credentials_env}={credentials_path}: {type( e ).__name__}: {e}" )
            return False

    def maybe_send_wake( self, user_id: str, reason: str = WAKE_REASON_UNDELIVERED ) -> str:
        """
        Apply the full S6 §3.3 trigger policy and submit a wake if it passes.

        Policy order (cheapest first): enabled → no-live-mobile-WS → debounce →
        ≥1 registered token → off-thread send. Called synchronously from the
        notification fan-out path, so everything on this thread is in-memory
        except the indexed token lookup; the network send is off-thread.

        Requires:
            - user_id is a non-empty string
            - reason is one of WAKE_REASONS

        Ensures:
            - returns a status string naming the outcome arm:
              "disabled" | "mobile_ws_live" | "debounced" | "no_tokens" | "submitted"
            - at most one wake per user per debounce window (the slot is burned
              at attempt time, even when the token lookup then comes up empty)
            - the send itself runs on the executor; this method never blocks on
              the network and NEVER raises (the fan-out path must stay safe)

        Raises:
            - None (lookup/send failures are logged, not propagated)
        """
        if not self.enabled:
            return "disabled"

        try:
            if self._mobile_liveness( user_id ):
                if self.debug and self.verbose: print( f"[FCM-WAKE] Skipping wake for {user_id}: live mobile WS" )
                return "mobile_ws_live"

            now = time.monotonic()
            with self._debounce_lock:
                last = self._last_wake_at.get( user_id )
                if last is not None and ( now - last ) < self.debounce_seconds:
                    if self.debug and self.verbose: print( f"[FCM-WAKE] Debounced wake for {user_id}" )
                    return "debounced"
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
            - NEVER raises (executor thread must not die)
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
        assert service.maybe_send_wake( "u2" ) == "debounced"
        service._executor.shutdown( wait=True )
        assert sent == [ "tok-1" ]
        print( "✓ Policy walk: submitted → debounced, transport hit once" )

        print( "\n✓ FcmWakeService smoke test PASSED" )
    except Exception as e:
        print( f"\n✗ FcmWakeService smoke test FAILED: {e}" )
        raise


if __name__ == "__main__":
    quick_smoke_test()
