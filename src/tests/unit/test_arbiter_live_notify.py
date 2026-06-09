#!/usr/bin/env python3
"""
Unit tests for the lupin-arbiter-app live-push-to-Rick hop (2b-1):
arbiter_live_notify.build_notify_request (the :7999 request shape) +
make_live_notify_fn (the content+window DEDUP guard, receipt b) + a full
escalation-path E2E (receipt c) that drives a REAL whole-fleet-stall escalation
through the production-shaped composition and captures it at the :7999 hop.

Venue: :7999-eligible / local — pure + fully mocked (no urllib, no server, no
real wait). The live urllib round-trip (_http_post) is the pragma'd IO boundary.
"""
import datetime
import os
import sys

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from lupin_arbiter_app.arbiter_live_notify import (
    build_notify_request, make_live_notify_fn, _default_log_fn, quick_smoke_test, NOTIFY_PATH,
)
from lupin_arbiter_app.fleet_arbiter_loop import make_escalation_notify_fn, ESCALATION_TOPIC
from cosa.agents.heartbeat_arbiter.arbiter_job import ArbiterConsumerJob


NOW = datetime.datetime( 2026, 6, 9, 0, 0, 0, tzinfo=datetime.timezone.utc )


class FixedClock:
    """A `.now()` seam whose time advances only when the test moves it."""
    def __init__( self, t=NOW ):
        self.t = t
    def now( self ):
        return self.t


# ── build_notify_request — the :7999 hop request SHAPE ─────────────────────────

class TestBuildNotifyRequest:
    def test_shape_carries_all_fields_and_api_key_header( self ):
        url, headers = build_notify_request(
            "WHOLE-FLEET-STALL — escalating to Rick",
            base_url="http://127.0.0.1:7999", target_user="rick@x.com",
            sender_id="heartbeat-arbiter@lupin.deepily.ai", api_key="k-123",
        )
        assert url.startswith( f"http://127.0.0.1:7999{NOTIFY_PATH}?" )
        # defaults: alert / high / suppress_ding=false / the fleet-arbiter title
        assert "type=alert" in url and "priority=high" in url and "suppress_ding=false" in url
        assert "target_user=rick" in url and "sender_id=heartbeat-arbiter" in url
        assert "title=Fleet" in url
        # message is url-encoded (spaces → +, em-dash → %)
        assert "WHOLE-FLEET-STALL" in url and " " not in url
        assert headers == { "X-API-Key": "k-123" }

    def test_trailing_slash_in_base_url_is_normalised( self ):
        url, _ = build_notify_request(
            "x", base_url="http://127.0.0.1:7999/", target_user="r@x.com",
            sender_id="s", api_key="k",
        )
        assert url.startswith( f"http://127.0.0.1:7999{NOTIFY_PATH}?" )   # no `//api`
        assert "7999//api" not in url

    def test_suppress_ding_true_and_custom_fields( self ):
        url, _ = build_notify_request(
            "y", base_url="http://h:7999", target_user="r@x.com", sender_id="s",
            api_key="k", priority="urgent", notify_type="custom",
            title="Custom Title", suppress_ding=True,
        )
        assert "suppress_ding=true" in url
        assert "priority=urgent" in url and "type=custom" in url and "title=Custom" in url


# ── make_live_notify_fn — the DEDUP guard (receipt b) ──────────────────────────

class TestLiveNotifyDedup:
    def test_n_identical_escalations_push_once( self ):
        """RECEIPT (b): N identical escalations within the window → exactly 1 push."""
        clk, pushed = FixedClock(), [ ]
        live = make_live_notify_fn( pushed.append, dedup_window_seconds=900, clock=clk )
        for _ in range( 7 ):
            live( "WHOLE-FLEET-STALL — escalating to Rick" )
        assert pushed == [ "WHOLE-FLEET-STALL — escalating to Rick" ]     # 7 → 1

    def test_distinct_messages_each_push( self ):
        clk, pushed = FixedClock(), [ ]
        live = make_live_notify_fn( pushed.append, dedup_window_seconds=900, clock=clk )
        live( "alert A" ); live( "alert B" ); live( "alert A" )           # A deduped, B distinct
        assert pushed == [ "alert A", "alert B" ]

    def test_window_elapse_allows_resend_and_prunes( self ):
        clk, pushed = FixedClock(), [ ]
        live = make_live_notify_fn( pushed.append, dedup_window_seconds=600, clock=clk )
        live( "same" )                                                    # pushed
        clk.t = NOW + datetime.timedelta( seconds=601 )                   # past the window
        live( "same" )                                                    # window elapsed → re-send + prune
        assert pushed == [ "same", "same" ]

    def test_failed_push_is_not_deduped_away( self ):
        """A transport that RAISES must not record the message — a later retry of
        the SAME text can still push (the failure propagates to the caller's
        swallow in make_escalation_notify_fn)."""
        clk, calls = FixedClock(), [ ]
        def boom( m ):
            calls.append( m )
            raise RuntimeError( ":7999 unreachable" )
        live = make_live_notify_fn( boom, dedup_window_seconds=900, clock=clk )
        with pytest.raises( RuntimeError ):
            live( "x" )
        with pytest.raises( RuntimeError ):
            live( "x" )                                                   # NOT deduped — retried
        assert calls == [ "x", "x" ]

    def test_default_clock_seam_resolves( self ):
        pushed = [ ]
        live = make_live_notify_fn( pushed.append )                       # clock=None → SystemClock
        live( "real-clock alert" )
        assert pushed == [ "real-clock alert" ]

    def test_default_log_fn_used_on_dedup( self, capsys ):
        clk, pushed = FixedClock(), [ ]
        live = make_live_notify_fn( pushed.append, dedup_window_seconds=900, clock=clk )  # log_fn=None
        live( "z" ); live( "z" )                                          # 2nd is deduped → default log
        out = capsys.readouterr().out
        assert "live_notify_deduped" in out and pushed == [ "z" ]


def test_default_log_fn_emits_structured_json( capsys ):
    _default_log_fn( "live_notify_sent", status=200, target_user="r@x.com" )
    out = capsys.readouterr().out
    assert '"loop": "fleet_arbiter_live_notify"' in out
    assert '"event": "live_notify_sent"' in out and '"status": 200' in out


def test_module_quick_smoke_test_passes():
    assert quick_smoke_test() is True


# ── live-push E2E (receipt c) — drive a REAL escalation through the :7999 hop ───

class _FakeGW:
    """Durable commons sink + the consumer-protocol stubs (no IO)."""
    def __init__( self ):
        self.posts, self.sent = [ ], [ ]
    def who( self, retention_hours=24 ): return [ ]
    def send_to( self, r, b ): self.sent.append( ( r, b ) )
    def post( self, t, b ): self.posts.append( ( t, b ) )
    def read( self, topic, since=None, limit=50 ): return [ ]


def _live_stuck( sid ):
    return { "session_id": sid, "persona": sid, "state": "stuck", "stuck": True,
             "holding_on": "none", "alive": True }


def test_live_push_e2e_real_escalation_reaches_7999_hop():
    """
    RECEIPT (c): wire the PRODUCTION-shaped escalation composition (durable commons
    post + best-effort live push) and drive a REAL whole-fleet-stall escalation via
    the dev path (a frozen LIVE fleet over the stall window — NOT waiting on a real
    stall). Assert the escalation lands BOTH on the durable `fleet-escalations`
    topic AND at the captured :7999 live hop, and that the captured message forms a
    well-formed POST :7999/api/notify request.
    """
    gw      = _FakeGW()
    clk     = FixedClock()
    pushed  = [ ]                                          # the captured :7999 hop
    live    = make_live_notify_fn( pushed.append, dedup_window_seconds=900, clock=clk )
    # the EXACT production escalation sink: durable-primary + best-effort live
    escalation_notify = make_escalation_notify_fn( gw, live_notify_fn=live, log_fn=lambda *a, **k: None )

    job = ArbiterConsumerJob(
        commons                    = gw,
        poll_seconds               = 5,
        manager_recipient          = "manager-on-duty",
        fleet_stall_window_seconds = 600,
        notify_fn                  = escalation_notify,
    )

    fleet = { "s1": _live_stuck( "s1" ) }
    assert job._check_fleet_stall( fleet, NOW ) == 0                                  # baseline
    assert job._check_fleet_stall( fleet, NOW + datetime.timedelta( seconds=700 ) ) == 1  # REAL escalation

    # (1) durable commons post landed on the escalation topic
    durable = [ b for t, b in gw.posts if t == ESCALATION_TOPIC ]
    assert durable and "WHOLE-FLEET-STALL" in durable[ 0 ]
    # (2) the SAME escalation reached the live :7999 hop (captured, deduped to 1)
    assert pushed == [ durable[ 0 ] ] and "escalating to Rick" in pushed[ 0 ]
    # (3) the captured message forms a well-formed POST :7999/api/notify request
    url, headers = build_notify_request(
        pushed[ 0 ], base_url="http://127.0.0.1:7999",
        target_user="rick@x.com", sender_id="heartbeat-arbiter@lupin.deepily.ai", api_key="k",
    )
    assert url.startswith( f"http://127.0.0.1:7999{NOTIFY_PATH}?" )
    assert "WHOLE-FLEET-STALL" in url and headers[ "X-API-Key" ] == "k"


def test_live_push_e2e_dedups_repeat_escalation_to_single_push():
    """The composition end-to-end honours dedup: the same escalation message
    arriving twice (e.g. across a job recycle) reaches the :7999 hop ONCE while the
    durable topic records each call (the durable channel is intentionally not
    deduped — it's the audit trail)."""
    gw, clk, pushed = _FakeGW(), FixedClock(), [ ]
    live = make_live_notify_fn( pushed.append, dedup_window_seconds=900, clock=clk )
    notify = make_escalation_notify_fn( gw, live_notify_fn=live, log_fn=lambda *a, **k: None )
    notify( "WHOLE-FLEET-STALL — escalating to Rick" )
    notify( "WHOLE-FLEET-STALL — escalating to Rick" )                 # repeat (recycle re-emit)
    assert len( pushed ) == 1                                          # live hop: 1 push
    assert len( gw.posts ) == 2                                        # durable: full audit trail


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
