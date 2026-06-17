#!/usr/bin/env python3
"""
lupin-arbiter-app — the live-push-to-Rick hop (2b-1), outcome-returning since the
2026.06.11 outreach-receipts design (Item B §3.2/§3.3).

The arbiter's escalations land durably on the `fleet-escalations` commons topic;
this module builds the BEST-EFFORT :7999 hops that fleet_arbiter_loop injects —
escalation-path ONLY (never per-poll; detection stays :7999-free, R4):

  • the LIVE notify transport (`make_notify_transport`) — POST /api/notify to
    Rick. Pre-design, `_http_post` discarded the response BODY, so a
    `user_not_available` miss (HTTP 200!) was invisible — the latent L1 failure
    behind the 2026-06-11 21:28/22:01 silent misses. The transport now parses
    the body's `status` into a structured OUTCOME dict and NEVER raises:
    failures become outcome values, journaled by the caller under the
    outreach_id (no hop may fail silently — §1.5).

  • the DM PUSH hop (`make_dm_push_fn`) — POST /api/dm/send with
    recipient_persona + the outreach body INLINE (notification-native AI↔AI
    DM, direction='ai_to_ai'): the recipient's listener delivers the body
    directly via `_handle_peer_dm` → tmux injection → the manager WAKES.
    Pre-design the arbiter's manager DMs were board-only writes (root-cause
    R6 — Tiberius never got pushed). Migrated off the legacy
    register-question / CommonsQuestionWatcher claim-check path 2026-06-15
    (cosa-voice token-reduction Phase 4) — the durable dm-<persona> board
    write in `_emit_dm` is unchanged (presence/receipt-polling substrate).

Outcome contract (every hop returns one dict):
    { "channel": "live"|"dm_push", "outcome": <vocabulary>, ...detail fields }
Delivered outcomes for the live channel: DELIVERED_OUTCOMES — ONLY these enter
the dedup window (the L2 kill: a user_not_available no longer suppresses
retries), and only these count as a Rick-side delivery receipt.

Two seams keep the logic 100% unit-testable — only the literal urllib round
trips (`_http_post`, `_http_post_json`) and the config/credential read (in
app.create_production_app) are the IO boundary, pragma'd there.
"""
import datetime
import json
from typing import Any, Callable, Optional
from urllib.parse import urlencode

from lupin_arbiter_app.health_watcher import SystemClock
from cosa.agents.heartbeat_arbiter.arbiter_journal import make_log_fn, DELIVERED_OUTCOMES


# the :7999 notification ingress (POST /api/notify; X-API-Key or JWT auth)
NOTIFY_PATH      = "/api/notify"
# the :7999 notification-native DM-push ingress (POST /api/dm/send — §3.3,
# migrated off /api/commons/register-question 2026-06-15: body rides INLINE)
DM_SEND_PATH = "/api/dm/send"


# Item A (2026.06.11 receipts design §2.3): the line shape has ONE owner —
# arbiter_journal.make_log_fn (ts + ts_local).
_default_log_fn = make_log_fn( loop="fleet_arbiter_live_notify" )


def build_notify_request(
    message       : str,
    *,
    base_url      : str,
    target_user   : str,
    sender_id     : str,
    api_key       : str,
    priority      : str  = "high",
    notify_type   : str  = "alert",
    title         : str  = "Fleet arbiter escalation",
    suppress_ding : bool = False,
):
    """
    Build the (url, headers) for a POST :7999/api/notify live push.

    PURE — the testable shape of the :7999 hop (the urllib round-trip is the
    pragma'd IO boundary, `_http_post`). Every notify field is a Query param (the
    endpoint declares them as Query), so they ride the URL query string even on a
    POST.

    Requires:
        - message / base_url / target_user / sender_id / api_key are strings

    Ensures:
        - returns (url, headers) where url = <base>/api/notify?<encoded params>
          carrying message + type + priority + target_user + sender_id + title +
          suppress_ding, and headers carries the X-API-Key
        - base_url's trailing slash is normalised (no double slash)
        - never raises
    """
    params = urlencode( {
        "message"       : message,
        "type"          : notify_type,
        "priority"      : priority,
        "target_user"   : target_user,
        "sender_id"     : sender_id,
        "title"         : title,
        "suppress_ding" : "true" if suppress_ding else "false",
    } )
    url     = f"{base_url.rstrip( '/' )}{NOTIFY_PATH}?{params}"
    headers = { "X-API-Key": api_key }
    return url, headers


def parse_notify_outcome( http_status: int, body: Any ) -> dict:
    """
    Map a /api/notify HTTP response (status + parsed JSON body) to the live-
    channel outcome dict — PURE (§3.2: the body carries the REAL delivery state;
    all three delivery states ride HTTP 200).

    Requires:
        - http_status is an int
        - body is the parsed response body (dict) or None/non-dict on parse fail

    Ensures:
        - body status "queued" / "delivered_via_listener" / "user_not_available"
          → that outcome verbatim (+ connection_count when present)
        - any other body / unparseable body on a 2xx → outcome
          "unexpected_response" with the body head as detail (visible, never
          silently assumed delivered)
        - non-2xx http_status → outcome "http_error" (+ http_status)
        - never raises
    """
    if not ( 200 <= http_status < 300 ):
        return { "channel": "live", "outcome": "http_error", "http_status": http_status }
    status = body.get( "status" ) if isinstance( body, dict ) else None
    if status in ( "queued", "delivered_via_listener", "user_not_available" ):
        outcome = { "channel": "live", "outcome": status, "http_status": http_status }
        if isinstance( body.get( "connection_count" ), int ):
            outcome[ "connection_count" ] = body[ "connection_count" ]
        return outcome
    return { "channel": "live", "outcome": "unexpected_response",
             "http_status": http_status, "detail": str( body )[ :160 ] }


def make_notify_transport(
    *,
    base_url        : str,
    target_user     : str,
    sender_id       : str,
    api_key         : str,
    timeout_seconds : int                  = 5,
    http_post_fn    : Optional[ Callable ] = None,
    log_fn          : Optional[ Callable ] = None,
) -> Callable[ [ str ], dict ]:
    """
    Build the live transport: transport( message ) -> live-channel outcome dict.

    Requires:
        - base_url / target_user / sender_id / api_key are strings
        - http_post_fn (if given) is ( url, headers, timeout_seconds ) ->
          ( http_status, parsed_body ) — test seam; default the urllib boundary

    Ensures:
        - POSTs the build_notify_request shape and returns
          parse_notify_outcome( status, body )
        - ANY transport exception (HTTPError 4xx/5xx, timeout, refused) becomes
          { channel: "live", outcome: "http_error", detail } — NEVER raises
          (failures are outcome VALUES per §1.5; tonight's swallowed 404 becomes
          a per-outreach journaled result instead)
        - logs `live_notify_sent` with the outcome on every attempt (the
          loop-level trace; the per-outreach result event is the caller's)
    """
    http_post_fn = http_post_fn if http_post_fn is not None else _http_post
    log_fn       = log_fn       if log_fn       is not None else _default_log_fn

    def transport( message: str ) -> dict:
        url, headers = build_notify_request(
            message, base_url=base_url, target_user=target_user,
            sender_id=sender_id, api_key=api_key,
        )
        try:
            status, body = http_post_fn( url, headers, timeout_seconds )
            outcome = parse_notify_outcome( status, body )
        except Exception as e:
            http_status = getattr( e, "code", None )
            outcome = { "channel": "live", "outcome": "http_error", "detail": str( e )[ :160 ] }
            if http_status is not None: outcome[ "http_status" ] = http_status
        log_fn( "live_notify_sent", outcome=outcome[ "outcome" ],
                http_status=outcome.get( "http_status" ), target_user=target_user )
        return outcome

    return transport


def make_live_notify_fn(
    transport            : Callable[ [ str ], dict ],
    *,
    dedup_window_seconds : int                  = 900,
    clock                : Optional[ Any ]      = None,
    log_fn               : Optional[ Callable ] = None,
) -> Callable[ [ str ], dict ]:
    """
    Wrap an outcome-returning transport with a content+window DEDUP guard.

    The arbiter's detectors already escalate-once-per-episode; this is
    belt-and-suspenders against a recycle re-emit, two detectors emitting the
    same line, or a retry storm — Rick never gets the same alert twice in a
    window.

    Requires:
        - transport is a callable taking the message and returning a live-
          channel outcome dict
        - dedup_window_seconds is a positive int

    Ensures:
        - the FIRST occurrence of a given message calls transport(message) and
          returns its outcome; an identical message seen again within the window
          is SKIPPED (logged `live_notify_deduped`, outcome "deduped")
        - a send is recorded into the window ONLY on a DELIVERED outcome — a
          user_not_available / http_error / unexpected_response attempt is NOT
          deduped away (the §1.3 L2 kill: pre-design, ANY non-raising call was
          recorded, so an offline-Rick miss suppressed retries for 15 min)
        - entries older than the window are pruned on each call (bounded memory)
        - never raises; returns the outcome dict
    """
    clock  = clock  if clock  is not None else SystemClock()
    log_fn = log_fn if log_fn is not None else _default_log_fn
    sent   : dict = { }    # message -> last-DELIVERED aware datetime

    def live_notify( message: str ) -> dict:
        now = clock.now()
        # prune expired entries first — anything that survives is within the window
        for stale in [ m for m, t in sent.items()
                       if ( now - t ).total_seconds() >= dedup_window_seconds ]:
            del sent[ stale ]
        if message in sent:
            log_fn( "live_notify_deduped", message=message )
            return { "channel": "live", "outcome": "deduped" }
        try:
            outcome = transport( message )
        except Exception as e:              # a raising transport degrades to an outcome (never raises)
            outcome = { "channel": "live", "outcome": "http_error", "detail": str( e )[ :160 ] }
        if isinstance( outcome, dict ) and outcome.get( "outcome" ) in DELIVERED_OUTCOMES:
            sent[ message ] = now           # record ONLY a delivered push
        return outcome

    return live_notify


def validate_live_notify_target( target_user: str ) -> Optional[ str ]:
    """
    Pre-flight validation of the live-push target_user — the §3.6 misconfig
    guard (PURE).

    Tonight's root cause R1: the systemd unit env lacked LUPIN_DEV_EMAIL, so
    `os.path.expandvars` left the LITERAL `${LUPIN_DEV_EMAIL}` in the INI value
    and every push 404'd, silently, forever. This catches that class at startup.

    Ensures:
        - returns None when target_user looks usable (non-empty, no surviving
          `${` env-var skeleton, has an @)
        - returns a human-readable error string otherwise; never raises
    """
    if not target_user or not target_user.strip():
        return "target_user is empty — set `arbiter live notify target user` (or the env var it references)"
    if "${" in target_user:
        return ( f"target_user {target_user!r} contains an UNRESOLVED env-var skeleton — "
                 f"the referenced variable is not set in the service environment "
                 f"(the 2026-06-11 R1 root cause: systemd's clean env lacked it)" )
    if "@" not in target_user:
        return f"target_user {target_user!r} is not an email address"
    return None


def resolve_arbiter_api_key( get_api_config_fn, load_api_key_fn, *, env, log_fn=None ):
    """
    PURE-SEAM (degrade-safe) resolver for the live-push X-API-Key out of
    `~/.lupin/config` — the testable branch logic lifted OUT of the app.py
    no-cover IO boundary (§7.4 of 2026.06.09-arbiter-notify-key-from-lupin-config).

    The two `cosa.utils.config_loader` functions are INJECTED (not imported here)
    so the try/except is unit-testable without touching real files or env: the
    literal file IO lives inside the injected callables; this seam is purely the
    branch decision (key-or-None).

    Requires:
        - get_api_config_fn( env=... ) → dict carrying an "api_key_file" path
          (raises FileNotFoundError if ~/.lupin/config is absent, ValueError if
          the env/fields are malformed)
        - load_api_key_fn( path ) → a validated `ck_live_…` key string (raises
          ValueError on a missing/unreadable/bad-format file)
        - env is the ~/.lupin/config section name (e.g. "development")

    Ensures:
        - happy path → returns the validated api_key string
        - ANY of FileNotFoundError / ValueError / KeyError → logs
          `live_notify_disabled` (with env + error) and returns None
        - never raises — a missing/bad credential disables live push (escalations
          stay durable on the commons topic), it NEVER crashes arbiter startup
    """
    log_fn = log_fn if log_fn is not None else _default_log_fn
    try:
        api_cfg = get_api_config_fn( env=env )
        return load_api_key_fn( api_cfg[ "api_key_file" ] )
    except ( FileNotFoundError, ValueError, KeyError ) as e:
        log_fn( "live_notify_disabled",
                reason=f"could not load api key from ~/.lupin/config [{env}]: {e}" )
        return None


# ── the DM-push hop (§3.3 — manager-bound notification-native peer DM) ────────

def build_dm_send_payload(
    *,
    recipient_persona : str,
    body              : str,
    thread_id         : str,
    asker_session_id  : str,
):
    """
    Build the JSON payload for the /api/dm/send DM-push hop — PURE.

    Migrated off register-question 2026-06-15: the body rides INLINE (no
    commons board claim-check). dm/send resolves the recipient persona →
    active session (same-user scoped) and delivers `body` as a
    direction='ai_to_ai' notification — the manager WAKES with the text in hand.

    Ensures:
        - thread_id == the caller's outreach/question id (the dot-connect key:
          the manager's threaded reply names the outreach via thread_id, and
          §3.4 board-polling receipts still correlate on the same id)
        - body travels inline (DmSendRequest.body is required)
        - no topic / question_id / ttl_seconds / expect_reply — dm/send is
          stateless (no tracker), the durable dm-<persona> board write in
          `_emit_dm` remains the receipt-polling substrate
    """
    return {
        "asker_session_id"  : asker_session_id,
        "recipient_persona" : recipient_persona,
        "body"              : body,
        "thread_id"         : thread_id,
    }


def make_dm_push_fn(
    *,
    base_url          : str,
    api_key           : str,
    asker_session_id  : str,
    timeout_seconds   : int                  = 5,
    http_post_json_fn : Optional[ Callable ] = None,
    log_fn            : Optional[ Callable ] = None,
) -> Callable[ [ str, str, str ], dict ]:
    """
    Build the manager DM-push seam: dm_push( recipient_persona, thread_id, body )
    -> dm_push-channel outcome dict.

    Requires:
        - http_post_json_fn (if given) is ( url, headers, payload_dict,
          timeout_seconds ) -> ( http_status, parsed_body ) — test seam;
          default the urllib boundary

    Ensures:
        - POSTs :7999/api/dm/send with the body INLINE; a 201
          (dm/send always dispatches an ai_to_ai push on resolve) → outcome
          "dispatched" (the manager's listener delivers the body via
          _handle_peer_dm → tmux injection — they WAKE with the text in hand)
        - ANY failure (422 recipient-resolution, timeout, refused, non-2xx) →
          outcome "push_unavailable" with detail — the caller degrades to the
          durable board write it already made, VISIBLY (never raises)
        - logs `dm_push_attempted` with the outcome on every call
    """
    http_post_json_fn = http_post_json_fn if http_post_json_fn is not None else _http_post_json
    log_fn            = log_fn            if log_fn            is not None else _default_log_fn
    url               = f"{base_url.rstrip( '/' )}{DM_SEND_PATH}"
    headers           = { "X-API-Key": api_key, "Content-Type": "application/json" }

    def dm_push( recipient_persona: str, thread_id: str, body: str ) -> dict:
        payload = build_dm_send_payload(
            recipient_persona=recipient_persona, body=body,
            thread_id=thread_id, asker_session_id=asker_session_id,
        )
        try:
            status, resp = http_post_json_fn( url, headers, payload, timeout_seconds )
            if status == 201:
                outcome = { "channel": "dm_push", "outcome": "dispatched" }
            else:
                outcome = { "channel": "dm_push", "outcome": "push_unavailable",
                            "http_status": status, "detail": str( resp )[ :160 ] }
        except Exception as e:
            http_status = getattr( e, "code", None )
            outcome = { "channel": "dm_push", "outcome": "push_unavailable",
                        "detail": str( e )[ :160 ] }
            if http_status is not None: outcome[ "http_status" ] = http_status
        log_fn( "dm_push_attempted", recipient=recipient_persona,
                thread_id=thread_id, outcome=outcome[ "outcome" ] )
        return outcome

    return dm_push


# ── the TMUX-push wake hop (Thread C+D — host-side direct injection) ──────────

def _default_tmux_resolve( session_id ):   # pragma: no cover - host-side bridge IO boundary
    """Real bridge probe: session_id → bridge dict (or None). No-cover; the seam is injected in tests."""
    from lupin_cli.claude_code.hooks.lib.session_bridge import find_session_by_id
    return find_session_by_id( session_id )


def _default_tmux_inject( session_id, text, wrap ):   # pragma: no cover - host-side tmux IO boundary
    """Real wake injector: reuse the existing inject_qualifier_via_tmux primitive (send-keys + Enter)."""
    from lupin_cli.claude_code.hooks.lib.hook_common import inject_qualifier_via_tmux
    inject_qualifier_via_tmux( session_id, text, wrap=wrap )


def _default_peer_dm_reminder( body, persona, icon, msg_id, thread_id ):   # pragma: no cover - host-side framing import
    """Real envelope: reuse the SHARED build_peer_dm_reminder so the woken pane frames it identically to a peer DM."""
    from lupin_cli.claude_code.hooks.lib.hook_common import build_peer_dm_reminder
    return build_peer_dm_reminder( body, persona=persona, icon=icon, msg_id=msg_id, thread_id=thread_id )


def make_tmux_push_fn(
    *,
    sender_persona : str                  = "heartbeat-arbiter",
    sender_icon    : Optional[ str ]      = "🛰️",
    resolve_fn     : Optional[ Callable ] = None,
    inject_fn      : Optional[ Callable ] = None,
    reminder_fn    : Optional[ Callable ] = None,
    log_fn         : Optional[ Callable ] = None,
) -> Callable[ [ str, str, str ], dict ]:
    """
    Build the host-side TMUX wake seam: tmux_push( session_id, thread_id, body )
    -> dm_push-channel outcome dict.

    The arbiter app is host-side (systemd --user, same uid as the CC tmux
    server), so it can reach a dormant pane's tmux socket directly. This seam
    WAKES that pane by reusing the existing inject_qualifier_via_tmux primitive
    (resolve tmux from the bridge → send-keys -l … Enter, UNCONDITIONALLY — no
    EVENT_IDLE gate). That is the whole point of Thread C+D: bypass the
    listener's buffer-vs-inject gate that drops the arbiter poke for a
    stale/owed or an idle-but-EVENT_IDLE-never-emitted manager.

    Requires:
        - resolve_fn (if given) is session_id -> bridge dict | None (test seam;
          default the real find_session_by_id bridge probe)
        - inject_fn (if given) is ( session_id, text, wrap ) -> None (test seam;
          default the real inject_qualifier_via_tmux)
        - reminder_fn (if given) is ( body, persona, icon, msg_id, thread_id ) ->
          framed text (test seam; default the real build_peer_dm_reminder)

    Ensures:
        - a resolvable bridge WITH a tmux_session → frame body as a peer-DM
          <system-reminder> (wrap=False, verbatim) + inject → outcome "dispatched"
        - no bridge / no tmux_session → outcome "push_unavailable" (the
          degrade-safe signal that lets _emit_dm fall back to dm_push_fn, rider a)
        - ANY exception (bridge read, framing, inject) → outcome
          "push_unavailable" with detail — NEVER raises
        - logs `tmux_push_attempted` with the outcome on every call
    """
    log_fn   = log_fn   if log_fn   is not None else _default_log_fn
    resolve  = resolve_fn  if resolve_fn  is not None else _default_tmux_resolve
    inject   = inject_fn   if inject_fn   is not None else _default_tmux_inject
    reminder = reminder_fn if reminder_fn is not None else _default_peer_dm_reminder

    def tmux_push( session_id: str, thread_id: str, body: str ) -> dict:
        try:
            bridge       = resolve( session_id )
            tmux_session = bridge.get( "tmux_session" ) if isinstance( bridge, dict ) else None
            if not tmux_session:
                outcome = { "channel": "dm_push", "outcome": "push_unavailable",
                            "detail": "no tmux_session in bridge" }
            else:
                framed = reminder( body, sender_persona, sender_icon, thread_id, thread_id )
                inject( session_id, framed, False )
                outcome = { "channel": "dm_push", "outcome": "dispatched" }
        except Exception as e:
            outcome = { "channel": "dm_push", "outcome": "push_unavailable",
                        "detail": str( e )[ :160 ] }
        log_fn( "tmux_push_attempted", session_id=session_id,
                thread_id=thread_id, outcome=outcome[ "outcome" ] )
        return outcome

    return tmux_push


# ── the literal urllib IO boundaries ─────────────────────────────────────────

def _http_post( url, headers, timeout_seconds=5 ):   # pragma: no cover - real urllib IO boundary (:7999 hop)
    """
    POST to `url` with `headers` (empty body); return ( status, parsed_body ).

    The literal urllib round-trip. Marked no-cover; exercised live against
    :7999, never in unit tests (the request SHAPE is `build_notify_request` and
    the response MAPPING is `parse_notify_outcome` — both ARE tested). Unlike
    the pre-design version this READS the body: /api/notify reports the real
    delivery state there (§1.3 L1).
    """
    import urllib.request
    req = urllib.request.Request( url, data=b"", headers=headers, method="POST" )
    with urllib.request.urlopen( req, timeout=timeout_seconds ) as resp:
        raw = resp.read()
        try:
            body = json.loads( raw ) if raw else None
        except ValueError:
            body = None
        return resp.status, body


def _http_post_json( url, headers, payload, timeout_seconds=5 ):   # pragma: no cover - real urllib IO boundary (:7999 hop)
    """POST a JSON payload; return ( status, parsed_body ). Same boundary contract as _http_post."""
    import urllib.request
    data = json.dumps( payload ).encode( "utf-8" )
    req  = urllib.request.Request( url, data=data, headers=headers, method="POST" )
    with urllib.request.urlopen( req, timeout=timeout_seconds ) as resp:
        raw = resp.read()
        try:
            body = json.loads( raw ) if raw else None
        except ValueError:
            body = None
        return resp.status, body


def quick_smoke_test():
    """Self-contained smoke test (no IO). Returns True or raises AssertionError."""
    # build_notify_request shape
    url, headers = build_notify_request(
        "WHOLE-FLEET-STALL — escalating to Rick",
        base_url="http://127.0.0.1:7999/", target_user="rick@x.com",
        sender_id="heartbeat-arbiter@lupin.deepily.ai", api_key="k-123",
    )
    assert url.startswith( "http://127.0.0.1:7999/api/notify?" )      # trailing slash normalised
    assert "type=alert" in url and "priority=high" in url and "target_user=rick" in url
    assert headers[ "X-API-Key" ] == "k-123"

    # body-status mapping — the L1 kill: user_not_available is now VISIBLE
    assert parse_notify_outcome( 200, { "status": "queued", "connection_count": 2 } )[ "outcome" ] == "queued"
    assert parse_notify_outcome( 200, { "status": "user_not_available" } )[ "outcome" ] == "user_not_available"
    assert parse_notify_outcome( 200, { "weird": True } )[ "outcome" ] == "unexpected_response"
    assert parse_notify_outcome( 404, None )[ "outcome" ] == "http_error"

    # dedup-on-DELIVERED-only — the L2 kill
    class _Clk:
        def __init__( self ): self.t = datetime.datetime( 2026, 6, 9, 0, 0, 0, tzinfo=datetime.timezone.utc )
        def now( self ): return self.t
    clk      = _Clk()
    answers  = [ { "channel": "live", "outcome": "user_not_available" },
                 { "channel": "live", "outcome": "queued" } ]
    calls    = [ ]
    def fake_transport( message ):
        calls.append( message )
        return answers[ min( len( calls ) - 1, 1 ) ]
    quiet = lambda event, **f: None
    live  = make_live_notify_fn( fake_transport, dedup_window_seconds=600, clock=clk, log_fn=quiet )
    assert live( "alert" )[ "outcome" ] == "user_not_available"       # miss → NOT recorded
    assert live( "alert" )[ "outcome" ] == "queued"                   # retry NOT deduped (L2 kill)
    assert live( "alert" )[ "outcome" ] == "deduped"                  # delivered → now deduped
    clk.t = clk.t + datetime.timedelta( seconds=601 )                  # past the window
    assert live( "alert" )[ "outcome" ] == "queued"                   # window elapsed → re-sent

    # misconfig guard — tonight's R1 class
    assert validate_live_notify_target( "rick@x.com" ) is None
    assert "UNRESOLVED" in validate_live_notify_target( "${LUPIN_DEV_EMAIL}" )
    assert validate_live_notify_target( "" ) is not None
    assert validate_live_notify_target( "not-an-email" ) is not None

    # dm_push outcome mapping — notification-native /api/dm/send (body inline)
    payload = build_dm_send_payload(
        recipient_persona="Mr Radio", body="WHOLE-FLEET-STALL — please advise",
        thread_id="o-1", asker_session_id="lupin-arbiter-app-8001",
    )
    assert payload[ "recipient_persona" ] == "Mr Radio" and payload[ "thread_id" ] == "o-1"
    assert payload[ "body" ] == "WHOLE-FLEET-STALL — please advise"
    push = make_dm_push_fn( base_url="http://x", api_key="k", asker_session_id="s",
                            http_post_json_fn=lambda u, h, p, t: ( 201, { "dispatched": True } ),
                            log_fn=quiet )
    assert push( "Tiberius", "o-2", "wake up" )[ "outcome" ] == "dispatched"
    push = make_dm_push_fn( base_url="http://x", api_key="k", asker_session_id="s",
                            http_post_json_fn=lambda u, h, p, t: ( 422, { "detail": "recipient_not_found" } ),
                            log_fn=quiet )
    assert push( "Ghost", "o-3", "wake up" )[ "outcome" ] == "push_unavailable"
    return True


if __name__ == "__main__":   # pragma: no cover - manual smoke entrypoint
    ok = quick_smoke_test()
    print( f"arbiter_live_notify smoke: {'PASS' if ok else 'FAIL'}" )
