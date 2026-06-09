#!/usr/bin/env python3
"""
lupin-arbiter-app — the live-push-to-Rick hop (2b-1).

The arbiter's escalations land durably on the `fleet-escalations` commons topic,
but until 2b-1 nobody consumed them (the consumption gap, design Part 3:
`live_notify_fn = None`, never fires). This module builds the BEST-EFFORT live
notify_fn that fleet_arbiter_loop injects as `live_notify_fn` — the ONLY
:7999-capable hop, ESCALATION-PATH ONLY (never per-poll; the detection path stays
:7999-free, R4). Each escalation becomes a `POST :7999/api/notify` so the alert
reaches Rick instead of rotting on a topic nobody polls.

Two seams keep the logic 100% unit-testable — only the literal urllib POST
(`_http_post`) and the config/credential read (in app.create_production_app) are
the IO boundary, pragma'd there:

  • `build_notify_request` — PURE: the exact request SHAPE of the :7999 hop
    (url + headers); fully tested.
  • `make_live_notify_fn` — a content+window DEDUP guard (2b-1 receipt b):
    identical escalation text within `dedup_window_seconds` is pushed ONCE. The
    arbiter's detectors already escalate-once-per-episode (`_stall_escalated` /
    `_manager_down_escalated` / the decision cursor); this is belt-and-suspenders
    against a recycle re-emit, two detectors emitting the same line, or a retry
    storm — so Rick never gets the same alert twice in a window. The injected
    `transport( message )` is the real sender (urllib) in production, a recorder
    in tests.

Degrade-safe: a transport failure propagates to make_escalation_notify_fn's
swallow (escalation_live_notify_error) and the escalation still lands durably on
the commons topic — the live push never gates detection.
"""
import datetime
import json
from typing import Any, Callable, Optional
from urllib.parse import urlencode

from lupin_arbiter_app.health_watcher import SystemClock


# the :7999 notification ingress (POST /api/notify; X-API-Key or JWT auth)
NOTIFY_PATH = "/api/notify"


def _default_log_fn( event: str, **fields: Any ) -> None:
    """Structured JSON line (loop:fleet_arbiter_live_notify) → systemd journal."""
    line : dict = {
        "ts"      : datetime.datetime.now( datetime.timezone.utc ).isoformat(),
        "service" : "lupin-arbiter-app",
        "loop"    : "fleet_arbiter_live_notify",
        "event"   : event,
    }
    line.update( fields )
    print( json.dumps( line, default=str ), flush=True )


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


def make_live_notify_fn(
    transport            : Callable[ [ str ], None ],
    *,
    dedup_window_seconds : int                  = 900,
    clock                : Optional[ Any ]      = None,
    log_fn               : Optional[ Callable ] = None,
) -> Callable[ [ str ], None ]:
    """
    Wrap a one-arg `transport(message)` with a content+window DEDUP guard.

    Requires:
        - transport is a callable taking the escalation message string
        - dedup_window_seconds is a positive int

    Ensures:
        - the FIRST occurrence of a given message calls transport(message); an
          identical message seen again within dedup_window_seconds is SKIPPED
          (logged `live_notify_deduped`) — N identical escalations in a window →
          exactly 1 push (receipt b)
        - the send is recorded ONLY after transport returns, so a FAILED push
          (transport raises) is NOT deduped away — the failure propagates to the
          caller's swallow (make_escalation_notify_fn) and a later retry can
          re-send
        - entries older than the window are pruned on each call (bounded memory)
        - returns the wrapped `live_notify( message ) -> None`
    """
    clock  = clock  if clock  is not None else SystemClock()
    log_fn = log_fn if log_fn is not None else _default_log_fn
    sent   : dict = { }    # message -> last-sent aware datetime

    def live_notify( message: str ) -> None:
        now = clock.now()
        # prune expired entries first — anything that survives is within the window
        for stale in [ m for m, t in sent.items()
                       if ( now - t ).total_seconds() >= dedup_window_seconds ]:
            del sent[ stale ]
        if message in sent:
            log_fn( "live_notify_deduped", message=message )
            return
        transport( message )            # may raise → propagate to caller's swallow
        sent[ message ] = now           # record ONLY after a successful push

    return live_notify


def _http_post( url, headers, timeout_seconds=5 ):   # pragma: no cover - real urllib IO boundary (:7999 hop)
    """
    POST to `url` with `headers` (empty body) and return the HTTP status.

    The literal urllib round-trip — the ONLY IO in this module. Marked no-cover;
    exercised live against :7999, never in unit tests (the request SHAPE it sends
    is `build_notify_request`, which IS tested).
    """
    import urllib.request
    req = urllib.request.Request( url, data=b"", headers=headers, method="POST" )
    with urllib.request.urlopen( req, timeout=timeout_seconds ) as resp:
        return resp.status


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

    # dedup: N identical → 1 transport call
    class _Clk:
        def __init__( self ): self.t = datetime.datetime( 2026, 6, 9, 0, 0, 0, tzinfo=datetime.timezone.utc )
        def now( self ): return self.t
    clk  = _Clk()
    sent = [ ]
    live = make_live_notify_fn( sent.append, dedup_window_seconds=600, clock=clk )
    for _ in range( 5 ):
        live( "same alert" )
    assert sent == [ "same alert" ]                                  # deduped 5 → 1
    clk.t = clk.t + datetime.timedelta( seconds=601 )                # past the window
    live( "same alert" )
    assert sent == [ "same alert", "same alert" ]                    # window elapsed → re-sent
    return True


if __name__ == "__main__":   # pragma: no cover - manual smoke entrypoint
    ok = quick_smoke_test()
    print( f"arbiter_live_notify smoke: {'PASS' if ok else 'FAIL'}" )
