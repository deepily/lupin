#!/usr/bin/env python3
"""
lupin-arbiter-app: the best-effort live pushes to the operator and to managers.

Every hop returns an outcome dict and never raises.

The arbiter's escalations land durably on the `fleet-escalations` commons topic.
This module builds the best-effort :7999 hops that fleet_arbiter_loop injects.
They run on the escalation path only, never per poll, so detection stays free of :7999 calls.

  - The live notify transport (`make_notify_transport`) POSTs /api/notify to the operator.
    /api/notify answers HTTP 200 even for `user_not_available`, so the transport parses the
    body's `status` into a structured outcome dict and never raises. Failures become outcome
    values, journaled by the caller under the outreach_id. No hop may fail silently.

  - The DM push hop (`make_dm_push_fn`) POSTs /api/dm/send with recipient_persona and the
    outreach body inline (an AI-to-AI DM, direction='ai_to_ai'). The recipient's listener
    delivers the body through `_handle_peer_dm` and tmux injection, so the manager wakes.
    The durable dm-<persona> board write in `_emit_dm` is unchanged. It stays the substrate
    for presence and receipt polling.

Outcome contract (every hop returns one dict):
    { "channel": "live"|"dm_push", "outcome": <vocabulary>, ...detail fields }
Delivered outcomes for the live channel are DELIVERED_OUTCOMES. Only these enter the dedup
window, so a user_not_available miss never suppresses a retry. Only these count as a
delivery receipt on the operator side.

Two seams keep the logic fully unit-testable. The urllib round trips (`_http_post`,
`_http_post_json`) and the config and credential read (in app.create_production_app)
are the IO boundary and carry the no-cover pragma.
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
    persist       : bool = True,
    abstract      : Optional[ str ] = None,
):
    """
    Build the (url, headers) for a POST :7999/api/notify live push.

    Pure function: it is the testable shape of the :7999 hop. The urllib round trip is the
    no-cover IO boundary, `_http_post`. The endpoint declares every notify field as a
    Query param, so they ride the URL query string even on a POST.

    Requires:
        - message / base_url / target_user / sender_id / api_key are strings

    Ensures:
        - returns (url, headers) where url = <base>/api/notify?<encoded params>
          carrying message + type + priority + target_user + sender_id + title +
          suppress_ding + persist, and headers carries the X-API-Key
        - persist=False rides as `persist=false`, the re-announce flood guard:
          a delivery-only retry must not mint a duplicate DB row
        - base_url's trailing slash is normalised (no double slash)
        - abstract (the card's detail, not spoken) rides as `abstract` only when given, so
          every caller that omits it gets a byte-identical URL
        - never raises
    """
    fields = {
        "message"       : message,
        "type"          : notify_type,
        "priority"      : priority,
        "target_user"   : target_user,
        "sender_id"     : sender_id,
        "title"         : title,
        "suppress_ding" : "true" if suppress_ding else "false",
        "persist"       : "true" if persist else "false",
    }
    if abstract is not None:
        fields[ "abstract" ] = abstract
    params = urlencode( fields )
    url     = f"{base_url.rstrip( '/' )}{NOTIFY_PATH}?{params}"
    headers = { "X-API-Key": api_key }
    return url, headers


def parse_notify_outcome( http_status: int, body: Any ) -> dict:
    """
    Map a /api/notify HTTP response to the live-channel outcome dict.

    Pure function. The body carries the real delivery state, because all three
    delivery states ride HTTP 200.

    Requires:
        - http_status is an int
        - body is the parsed response body (dict) or None/non-dict on parse fail

    Ensures:
        - body status "queued" / "delivered_via_listener" / "user_not_available"
          → that outcome verbatim (+ connection_count when present)
        - any other body, or an unparseable body, on a 2xx → outcome
          "unexpected_response" with the body head as detail (visible, and never
          assumed delivered)
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
    timeout_seconds : int                  = 30,
    persist         : bool                 = True,
    http_post_fn    : Optional[ Callable ] = None,
    log_fn          : Optional[ Callable ] = None,
) -> Callable[ [ str ], dict ]:
    """
    Build the live transport: transport( message ) returns a live-channel outcome dict.

    Requires:
        - base_url / target_user / sender_id / api_key are strings
        - http_post_fn (if given) is ( url, headers, timeout_seconds ) ->
          ( http_status, parsed_body ) — test seam; default the urllib boundary

    Ensures:
        - POSTs the build_notify_request shape (with this transport's `persist`)
          and returns parse_notify_outcome( status, body )
        - persist=False builds the re-announce flood-guard transport: every retry
          re-attempts live delivery without re-persisting a forensic row. The
          first-send transport keeps persist=True
        - any transport exception (HTTPError 4xx/5xx, timeout, refused) becomes
          { channel: "live", outcome: "http_error", detail } and never raises.
          Failures are outcome values, so a swallowed 404 becomes a per-outreach
          journaled result
        - logs `live_notify_sent` with the outcome on every attempt (the
          loop-level trace; the per-outreach result event is the caller's)
    """
    http_post_fn = http_post_fn if http_post_fn is not None else _http_post
    log_fn       = log_fn       if log_fn       is not None else _default_log_fn

    def transport( message: str, abstract: Optional[ str ] = None ) -> dict:
        url, headers = build_notify_request(
            message, base_url=base_url, target_user=target_user,
            sender_id=sender_id, api_key=api_key, persist=persist, abstract=abstract,
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
    Wrap an outcome-returning transport with a content-and-window dedup guard.

    The arbiter's detectors already escalate once per episode. This guard is a second
    layer. It covers a recycle re-emit, two detectors emitting the same line, and a retry
    storm. The operator never gets the same alert twice in a window.

    Requires:
        - transport is a callable taking the message and returning a live-
          channel outcome dict
        - dedup_window_seconds is a positive int

    Ensures:
        - the first occurrence of a given message calls transport(message) and
          returns its outcome; an identical message seen again within the window
          is skipped (logged `live_notify_deduped`, outcome "deduped")
        - a send is recorded into the window only on a delivered outcome. A
          user_not_available, http_error or unexpected_response attempt is not
          deduped away, so any offline operator's miss never suppresses retries
        - entries older than the window are pruned on each call (bounded memory)
        - never raises; returns the outcome dict
    """
    clock  = clock  if clock  is not None else SystemClock()
    log_fn = log_fn if log_fn is not None else _default_log_fn
    sent   : dict = { }    # message -> last-DELIVERED aware datetime

    def live_notify( message: str, abstract: Optional[ str ] = None ) -> dict:
        # 🔴 THE DEDUP KEY INCLUDES THE ABSTRACT WHEN THERE IS ONE (Mr. Radio, row 033538f6).
        # A spoken line can repeat while its detail changes: "2 worktrees refused" is the
        # same message whether the two are A+B or A+C. Keyed on the message alone, the
        # second announcement was silently deduped and the operator never heard about C.
        # Message-only callers keep a message-only key, so nothing changes for them.
        key = message if abstract is None else ( message, abstract )
        now = clock.now()
        # prune expired entries first — anything that survives is within the window
        for stale in [ m for m, t in sent.items()
                       if ( now - t ).total_seconds() >= dedup_window_seconds ]:
            del sent[ stale ]
        if key in sent:
            log_fn( "live_notify_deduped", message=message )
            return { "channel": "live", "outcome": "deduped" }
        try:
            # The abstract is passed only when given, so a message-only transport (every
            # caller before row 033538f6, and the test fakes) keeps working unchanged.
            outcome = transport( message ) if abstract is None else transport( message, abstract=abstract )
        except Exception as e:              # a raising transport degrades to an outcome (never raises)
            outcome = { "channel": "live", "outcome": "http_error", "detail": str( e )[ :160 ] }
        if isinstance( outcome, dict ) and outcome.get( "outcome" ) in DELIVERED_OUTCOMES:
            sent[ key ] = now               # record ONLY a delivered push
        return outcome

    return live_notify


def validate_live_notify_target( target_user: str ) -> Optional[ str ]:
    """
    Pre-flight validation of the live-push target_user, a misconfiguration guard.

    Pure function. If the systemd unit env lacks LUPIN_DEV_EMAIL, `os.path.expandvars`
    leaves the literal `${LUPIN_DEV_EMAIL}` in the INI value and every push 404s.
    This catches that class of error at startup.

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
    Resolve the live-push X-API-Key from `~/.lupin/config`, degrading to None on failure.

    The testable branch logic, lifted out of the no-cover IO boundary in app.py.
    The two `cosa.utils.config_loader` functions are injected, not imported here, so the
    try/except is unit-testable without real files or env.

    Requires:
        - get_api_config_fn( env=... ) → dict carrying an "api_key_file" path
          (raises FileNotFoundError if ~/.lupin/config is absent, ValueError if
          the env/fields are malformed)
        - load_api_key_fn( path ) → a validated `ck_live_…` key string (raises
          ValueError on a missing/unreadable/bad-format file)
        - env is the ~/.lupin/config section name (e.g. "development")

    Ensures:
        - happy path → returns the validated api_key string
        - any of FileNotFoundError / ValueError / KeyError → logs
          `live_notify_disabled` (with env + error) and returns None
        - never raises. A missing or bad credential disables live push (escalations
          stay durable on the commons topic) and never crashes arbiter startup
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
    sender_session_id  : str,
    sender_project    : str,
):
    """
    Build the JSON payload for the /api/dm/send DM-push hop (a pure function).

    The body rides inline, with no commons board claim-check. dm/send resolves the
    recipient persona to its active session (same-user scoped). It delivers `body` as a
    direction='ai_to_ai' notification, so the manager wakes with the text in hand.

    Ensures:
        - thread_id == the caller's outreach/question id. The manager's threaded
          reply names the outreach via thread_id, and board-polling receipts
          correlate on the same id
        - body travels inline (DmSendRequest.body is required)
        - no topic / question_id / ttl_seconds / expect_reply — dm/send is
          stateless (no tracker), the durable dm-<persona> board write in
          `_emit_dm` remains the receipt-polling substrate
        - sender_project is a required argument here because the server requires
          it: a payload without it is answered 422 before it is stored or pushed.
          A required argument turns every omission into a TypeError at the call
          site instead of a quiet 422 at runtime
    """
    return {
        "sender_session_id" : sender_session_id,
        "sender_project"    : sender_project,
        "recipient_persona" : recipient_persona,
        "body"              : body,
        "thread_id"         : thread_id,
    }


def make_dm_push_fn(
    *,
    base_url          : str,
    api_key           : str,
    sender_session_id  : str,
    sender_project    : str,
    timeout_seconds   : int                  = 30,
    http_post_json_fn : Optional[ Callable ] = None,
    log_fn            : Optional[ Callable ] = None,
) -> Callable[ [ str, str, str ], dict ]:
    """
    Build the manager DM-push seam: dm_push( recipient_persona, thread_id, body ).

    The returned function gives a dm_push-channel outcome dict.

    Requires:
        - http_post_json_fn (if given) is ( url, headers, payload_dict,
          timeout_seconds ) -> ( http_status, parsed_body ) — test seam;
          default the urllib boundary

    Ensures:
        - POSTs :7999/api/dm/send with the body inline; a 201 (dm/send always
          dispatches an ai_to_ai push on resolve) → outcome "dispatched". The
          manager's listener delivers the body via _handle_peer_dm and tmux
          injection, so the manager wakes with the text in hand
        - any failure (422 recipient-resolution, timeout, refused, non-2xx) →
          outcome "push_unavailable" with detail. The caller degrades, visibly,
          to the durable board write it already made. Never raises
        - logs `dm_push_attempted` with the outcome on every call, and on a failure also
          the http_status and detail (the response body), so the reason for a refusal
          survives into the journal instead of only the word "push_unavailable"
    """
    http_post_json_fn = http_post_json_fn if http_post_json_fn is not None else _http_post_json
    log_fn            = log_fn            if log_fn            is not None else _default_log_fn
    url               = f"{base_url.rstrip( '/' )}{DM_SEND_PATH}"
    headers           = { "X-API-Key": api_key, "Content-Type": "application/json" }

    def dm_push( recipient_persona: str, thread_id: str, body: str ) -> dict:
        payload = build_dm_send_payload(
            recipient_persona=recipient_persona, body=body,
            thread_id=thread_id, sender_session_id=sender_session_id,
            sender_project=sender_project,
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
        failure = { k: outcome[ k ] for k in ( "http_status", "detail" ) if k in outcome }
        log_fn( "dm_push_attempted", recipient=recipient_persona,
                thread_id=thread_id, outcome=outcome[ "outcome" ], **failure )
        return outcome

    return dm_push


# ── the TMUX-push wake hop (Thread C+D — host-side direct injection) ──────────

def _default_tmux_resolve( session_id ):   # pragma: no cover - host-side bridge IO boundary
    """Probe the real bridge: session_id to bridge dict, or None. Tests inject the seam."""
    from lupin_cli.claude_code.hooks.lib.session_bridge import find_session_by_id
    return find_session_by_id( session_id )


def _default_tmux_inject( session_id, text, wrap ):   # pragma: no cover - host-side tmux IO boundary
    """Inject a wake into a tmux pane with inject_qualifier_via_tmux (send-keys and Enter)."""
    from lupin_cli.claude_code.hooks.lib.hook_common import inject_qualifier_via_tmux
    inject_qualifier_via_tmux( session_id, text, wrap=wrap )


def _default_peer_dm_reminder( body, persona, icon, msg_id, thread_id ):
    """Frame a peer DM with the shared build_peer_dm_reminder, one-way.

    The arbiter is an observer with no inbox. Its pokes must never carry a dm_send
    reply line, because the poked session cannot deliver one. one_way=True swaps that
    line for the real signal path. Resuming work is the acknowledgement. So are fresh
    bridge, hold and store state.
    """
    from lupin_cli.claude_code.hooks.lib.hook_common import build_peer_dm_reminder
    return build_peer_dm_reminder( body, persona=persona, icon=icon, msg_id=msg_id, thread_id=thread_id, one_way=True )


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
    Build the host-side tmux wake seam: tmux_push( session_id, thread_id, body ).

    The arbiter runs on the host with the CC tmux server's uid, so it can reach a dormant
    pane's tmux socket. The returned function wakes the pane with no EVENT_IDLE gate. So it
    reaches a stale or owed manager, and an idle one that never emitted EVENT_IDLE.

    Requires:
        - resolve_fn (if given) is session_id -> bridge dict | None (test seam;
          default the real find_session_by_id bridge probe)
        - inject_fn (if given) is ( session_id, text, wrap ) -> None (test seam;
          default the real inject_qualifier_via_tmux)
        - reminder_fn (if given) is ( body, persona, icon, msg_id, thread_id ) ->
          framed text (test seam; default the real build_peer_dm_reminder)

    Ensures:
        - a resolvable bridge with a tmux_session → frame body as a peer-DM
          <system-reminder> (wrap=False, verbatim) + inject → outcome "dispatched"
        - no bridge / no tmux_session → outcome "push_unavailable", the
          degrade-safe signal that lets _emit_dm fall back to dm_push_fn
        - any exception (bridge read, framing, inject) → outcome
          "push_unavailable" with detail, and never raises
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

def _http_post( url, headers, timeout_seconds=30 ):   # pragma: no cover - real urllib IO boundary (:7999 hop)
    """
    POST to `url` with `headers` (empty body); return ( status, parsed_body ).

    The literal urllib round trip. It is marked no-cover and exercised live against
    :7999, never in unit tests. The request shape is `build_notify_request` and the
    response mapping is `parse_notify_outcome`, and both are tested. It reads the body,
    because /api/notify reports the real delivery state there.
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


def _parse_json_or_none( raw ):
    """Parse a response body as JSON; None when it is empty or not JSON."""
    try:
        return json.loads( raw ) if raw else None
    except ValueError:
        return None


def _http_post_json( url, headers, payload, timeout_seconds=30 ):
    """
    POST a JSON payload; return ( status, parsed_body ).

    urllib raises on a 4xx/5xx, and the caller would then see only "HTTP Error 422:
    Unprocessable Content" and lose the reason. An HTTP error is an answer, not a
    transport failure. It is returned as ( status, body ) like a success, and the
    caller reads the reason out of the body. Only a failure with no HTTP answer
    (refused, timeout) still raises.
    """
    import urllib.error
    import urllib.request
    data = json.dumps( payload ).encode( "utf-8" )
    req  = urllib.request.Request( url, data=data, headers=headers, method="POST" )
    try:
        with urllib.request.urlopen( req, timeout=timeout_seconds ) as resp:
            return resp.status, _parse_json_or_none( resp.read() )
    except urllib.error.HTTPError as e:
        return e.code, _parse_json_or_none( e.read() )


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
    assert "persist=true" in url                                       # default persists (byte-identical)
    assert headers[ "X-API-Key" ] == "k-123"

    # persist=False flood-guard shape (bug e1bbe011): the re-announce transport
    url_np, _ = build_notify_request(
        "re-announce retry", base_url="http://127.0.0.1:7999",
        target_user="rick@x.com", sender_id="s", api_key="k", persist=False,
    )
    assert "persist=false" in url_np

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
        thread_id="o-1", sender_session_id="lupin-arbiter-app-8001", sender_project="lupin",
    )
    assert payload[ "recipient_persona" ] == "Mr Radio" and payload[ "thread_id" ] == "o-1"
    assert payload[ "body" ] == "WHOLE-FLEET-STALL — please advise"
    assert payload[ "sender_project" ] == "lupin"
    push = make_dm_push_fn( base_url="http://x", api_key="k", sender_session_id="s", sender_project="lupin",
                            http_post_json_fn=lambda u, h, p, t: ( 201, { "dispatched": True } ),
                            log_fn=quiet )
    assert push( "Tiberius", "o-2", "wake up" )[ "outcome" ] == "dispatched"
    push = make_dm_push_fn( base_url="http://x", api_key="k", sender_session_id="s", sender_project="lupin",
                            http_post_json_fn=lambda u, h, p, t: ( 422, { "detail": "recipient_not_found" } ),
                            log_fn=quiet )
    assert push( "Ghost", "o-3", "wake up" )[ "outcome" ] == "push_unavailable"
    return True


if __name__ == "__main__":   # pragma: no cover - manual smoke entrypoint
    ok = quick_smoke_test()
    print( f"arbiter_live_notify smoke: {'PASS' if ok else 'FAIL'}" )
