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
    build_notify_request, build_notify_peer_payload, make_dm_push_fn,
    make_live_notify_fn, make_notify_transport, parse_notify_outcome,
    resolve_arbiter_api_key, validate_live_notify_target,
    _default_log_fn, quick_smoke_test, NOTIFY_PATH, NOTIFY_PEER_PATH,
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


def _queued_transport( pushed ):
    """An outcome-returning fake transport (2026.06.11 receipts contract): records
    the message and reports a DELIVERED outcome (`queued`)."""
    def transport( message ):
        pushed.append( message )
        return { "channel": "live", "outcome": "queued" }
    return transport


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
        live = make_live_notify_fn( _queued_transport( pushed ), dedup_window_seconds=900, clock=clk )
        for _ in range( 7 ):
            live( "WHOLE-FLEET-STALL — escalating to Rick" )
        assert pushed == [ "WHOLE-FLEET-STALL — escalating to Rick" ]     # 7 → 1

    def test_distinct_messages_each_push( self ):
        clk, pushed = FixedClock(), [ ]
        live = make_live_notify_fn( _queued_transport( pushed ), dedup_window_seconds=900, clock=clk )
        live( "alert A" ); live( "alert B" ); live( "alert A" )           # A deduped, B distinct
        assert pushed == [ "alert A", "alert B" ]

    def test_window_elapse_allows_resend_and_prunes( self ):
        clk, pushed = FixedClock(), [ ]
        live = make_live_notify_fn( _queued_transport( pushed ), dedup_window_seconds=600, clock=clk )
        live( "same" )                                                    # pushed
        clk.t = NOW + datetime.timedelta( seconds=601 )                   # past the window
        live( "same" )                                                    # window elapsed → re-send + prune
        assert pushed == [ "same", "same" ]

    def test_failed_push_is_not_deduped_away( self ):
        """A FAILED push must not record the message — a later retry of the SAME
        text can still push (2026.06.11 receipts contract: failures are outcome
        VALUES, never raises; only DELIVERED outcomes enter the dedup window)."""
        clk, calls = FixedClock(), [ ]
        def boom( m ):
            calls.append( m )
            raise RuntimeError( ":7999 unreachable" )
        live = make_live_notify_fn( boom, dedup_window_seconds=900, clock=clk,
                                    log_fn=lambda *a, **k: None )
        assert live( "x" )[ "outcome" ] == "http_error"                   # degraded, not raised
        assert live( "x" )[ "outcome" ] == "http_error"                   # NOT deduped — retried
        assert calls == [ "x", "x" ]

    def test_undelivered_outcome_is_not_deduped_away( self ):
        """The L2 kill, asserted directly: a user_not_available outcome (Rick's WS
        offline — tonight's latent miss) must NOT enter the dedup window; the next
        identical send goes out, and only a DELIVERED outcome starts deduping."""
        clk, answers, calls = FixedClock(), [ "user_not_available", "queued", "queued" ], [ ]
        def transport( m ):
            calls.append( m )
            return { "channel": "live", "outcome": answers[ len( calls ) - 1 ] }
        live = make_live_notify_fn( transport, dedup_window_seconds=900, clock=clk,
                                    log_fn=lambda *a, **k: None )
        assert live( "alert" )[ "outcome" ] == "user_not_available"       # miss → not recorded
        assert live( "alert" )[ "outcome" ] == "queued"                   # retried, delivered → recorded
        assert live( "alert" )[ "outcome" ] == "deduped"                  # now deduped
        assert calls == [ "alert", "alert" ]

    def test_default_clock_seam_resolves( self ):
        pushed = [ ]
        live = make_live_notify_fn( _queued_transport( pushed ) )         # clock=None → SystemClock
        live( "real-clock alert" )
        assert pushed == [ "real-clock alert" ]

    def test_default_log_fn_used_on_dedup( self, capsys ):
        clk, pushed = FixedClock(), [ ]
        live = make_live_notify_fn( _queued_transport( pushed ), dedup_window_seconds=900, clock=clk )  # log_fn=None
        live( "z" ); live( "z" )                                          # 2nd is deduped → default log
        out = capsys.readouterr().out
        assert "live_notify_deduped" in out and pushed == [ "z" ]


# ── parse_notify_outcome + make_notify_transport — the §3.2 body-reading hop ───

class TestParseNotifyOutcome:
    """The L1 kill: /api/notify reports the REAL delivery state in the response
    BODY (all three states ride HTTP 200) — pre-design the body was discarded."""

    def test_delivery_states_pass_verbatim_with_connection_count( self ):
        out = parse_notify_outcome( 200, { "status": "queued", "connection_count": 2 } )
        assert out[ "outcome" ] == "queued" and out[ "connection_count" ] == 2
        assert parse_notify_outcome( 200, { "status": "user_not_available" } )[ "outcome" ] == "user_not_available"
        assert parse_notify_outcome( 200, { "status": "delivered_via_listener" } )[ "outcome" ] == "delivered_via_listener"

    def test_non_2xx_is_http_error( self ):
        out = parse_notify_outcome( 404, None )
        assert out[ "outcome" ] == "http_error" and out[ "http_status" ] == 404

    def test_unknown_or_unparseable_body_is_unexpected_response( self ):
        assert parse_notify_outcome( 200, { "weird": True } )[ "outcome" ] == "unexpected_response"
        assert parse_notify_outcome( 200, None )[ "outcome" ] == "unexpected_response"
        out = parse_notify_outcome( 200, { "status": "queued", "connection_count": "2" } )
        assert "connection_count" not in out                          # non-int count not echoed


class TestMakeNotifyTransport:
    _ARGS = dict( base_url="http://x:7999", target_user="rick@x.com",
                  sender_id="arb@x", api_key="k" )

    def test_success_parses_body_and_logs( self ):
        logged = [ ]
        t = make_notify_transport(
            http_post_fn=lambda u, h, s: ( 200, { "status": "queued" } ),
            log_fn=lambda e, **f: logged.append( ( e, f ) ), **self._ARGS )
        out = t( "alert" )
        assert out[ "outcome" ] == "queued" and out[ "http_status" ] == 200
        assert logged[ 0 ][ 0 ] == "live_notify_sent" and logged[ 0 ][ 1 ][ "outcome" ] == "queued"

    def test_http_error_with_code_attr_carried( self ):
        """Tonight's exact 404: urllib.HTTPError carries .code — it must surface."""
        class _Err( Exception ):
            code = 404
        def boom( u, h, s ): raise _Err( "HTTP Error 404: Not Found" )
        t = make_notify_transport( http_post_fn=boom, log_fn=lambda e, **f: None, **self._ARGS )
        out = t( "alert" )
        assert out[ "outcome" ] == "http_error" and out[ "http_status" ] == 404
        assert "404" in out[ "detail" ]

    def test_plain_exception_without_code( self ):
        def boom( u, h, s ): raise TimeoutError( "timed out" )
        t = make_notify_transport( http_post_fn=boom, log_fn=lambda e, **f: None, **self._ARGS )
        out = t( "alert" )
        assert out[ "outcome" ] == "http_error" and "http_status" not in out

    def test_default_log_fn_traces_attempt( self, capsys ):
        t = make_notify_transport( http_post_fn=lambda u, h, s: ( 200, { "status": "queued" } ),
                                   **self._ARGS )                     # log_fn=None → module default
        t( "alert" )
        out = capsys.readouterr().out
        assert "live_notify_sent" in out and '"outcome": "queued"' in out


# ── validate_live_notify_target — the §3.6 misconfig guard (tonight's R1) ──────

class TestValidateLiveNotifyTarget:
    def test_usable_email_passes( self ):
        assert validate_live_notify_target( "rick@x.com" ) is None

    def test_unresolved_env_skeleton_caught( self ):
        err = validate_live_notify_target( "${LUPIN_DEV_EMAIL}" )
        assert err is not None and "UNRESOLVED" in err and "LUPIN_DEV_EMAIL" in err

    def test_empty_and_whitespace_caught( self ):
        assert "empty" in validate_live_notify_target( "" )
        assert "empty" in validate_live_notify_target( "   " )

    def test_non_email_caught( self ):
        assert "not an email" in validate_live_notify_target( "rick" )


# ── make_dm_push_fn + payload — the §3.3 manager wake hop (notify-peer) ────────

class TestDmPush:
    _ARGS = dict( base_url="http://x:7999/", api_key="k",
                  asker_session_id="lupin-arbiter-app-8001" )

    def test_payload_carries_body_inline_and_threads_on_outreach_id( self ):
        p = build_notify_peer_payload(
            recipient_persona="Mr Radio", body="WHOLE-FLEET-STALL — please advise",
            thread_id="oid-1", asker_session_id="lupin-arbiter-app-8001" )
        assert p[ "recipient_persona" ] == "Mr Radio"
        assert p[ "thread_id" ] == "oid-1"                            # threaded reply names the outreach
        assert p[ "body" ] == "WHOLE-FLEET-STALL — please advise"     # body travels INLINE
        assert p[ "asker_session_id" ] == "lupin-arbiter-app-8001"

    def test_dispatched_201_posts_notify_peer_with_body( self ):
        seen = [ ]
        def post( url, headers, payload, timeout ):
            seen.append( ( url, headers, payload ) )
            return 201, { "dispatched": True, "message_id": "m1", "thread_id": "oid-1" }
        push = make_dm_push_fn( http_post_json_fn=post, log_fn=lambda e, **f: None, **self._ARGS )
        assert push( "Tiberius", "oid-1", "wake up — stall" )[ "outcome" ] == "dispatched"
        url, headers, payload = seen[ 0 ]
        assert url == f"http://x:7999{NOTIFY_PEER_PATH}"              # trailing slash normalised
        assert headers[ "X-API-Key" ] == "k" and payload[ "recipient_persona" ] == "Tiberius"
        assert payload[ "body" ] == "wake up — stall"                # inline body

    def test_non_201_is_push_unavailable_with_status( self ):
        push = make_dm_push_fn( http_post_json_fn=lambda u, h, p, t: ( 422, { "detail": "recipient_not_found" } ),
                                log_fn=lambda e, **f: None, **self._ARGS )
        out = push( "Ghost", "oid-1", "wake up" )
        assert out[ "outcome" ] == "push_unavailable" and out[ "http_status" ] == 422

    def test_exception_with_code_attr_carried( self ):
        class _Err( Exception ):
            code = 401
        def boom( u, h, p, t ): raise _Err( "auth" )
        push = make_dm_push_fn( http_post_json_fn=boom, log_fn=lambda e, **f: None, **self._ARGS )
        out = push( "Tiberius", "oid-1", "wake up" )
        assert out[ "outcome" ] == "push_unavailable" and out[ "http_status" ] == 401

    def test_plain_exception_without_code( self ):
        def boom( u, h, p, t ): raise TimeoutError( "timed out" )
        push = make_dm_push_fn( http_post_json_fn=boom, log_fn=lambda e, **f: None, **self._ARGS )
        out = push( "Tiberius", "oid-1", "wake up" )
        assert out[ "outcome" ] == "push_unavailable" and "http_status" not in out

    def test_default_log_fn_traces_attempt( self, capsys ):
        push = make_dm_push_fn( http_post_json_fn=lambda u, h, p, t: ( 201, { "dispatched": True } ),
                                **self._ARGS )                        # log_fn=None → module default
        push( "Tiberius", "oid-1", "wake up" )
        out = capsys.readouterr().out
        assert "dm_push_attempted" in out and "dispatched" in out


# ── resolve_arbiter_api_key — the §7.4 degrade-safe pure-seam resolver ─────────

class TestResolveArbiterApiKey:
    """§7.4 pure seam: the X-API-Key resolver lifted OUT of the app.py no-cover IO
    boundary. The two config_loader functions are INJECTED, so the degrade-safe
    try/except is fully testable without touching real files or env — covering the
    happy path + all 3 failure branches (FileNotFoundError / ValueError / KeyError)
    at 100% L/B."""

    def test_happy_path_returns_validated_key( self ):
        logged = [ ]
        good_key = "ck_live_" + "A" * 64
        def get_cfg( env ):
            assert env == "development"
            return { "api_url": "http://x:7999", "api_key_file": "/keys/notify-dev" }
        def load_key( path ):
            assert path == "/keys/notify-dev"
            return good_key
        key = resolve_arbiter_api_key(
            get_cfg, load_key, env="development",
            log_fn=lambda *a, **k: logged.append( ( a, k ) ),
        )
        assert key == good_key
        assert logged == [ ]                                   # happy path logs nothing

    def test_missing_config_file_not_found_disables( self ):
        """(b) ~/.lupin/config absent → get_api_config raises FileNotFoundError → None + log."""
        logged = [ ]
        def get_cfg( env ): raise FileNotFoundError( "~/.lupin/config not found" )
        def load_key( path ): raise AssertionError( "load_key must not be reached" )
        key = resolve_arbiter_api_key(
            get_cfg, load_key, env="development",
            log_fn=lambda event, **k: logged.append( ( event, k ) ),
        )
        assert key is None
        assert logged[ 0 ][ 0 ] == "live_notify_disabled"
        assert "development" in logged[ 0 ][ 1 ][ "reason" ]

    def test_bad_key_format_value_error_disables( self ):
        """(c) bad/missing key file → load_api_key raises ValueError → None + log."""
        logged = [ ]
        def get_cfg( env ): return { "api_key_file": "/keys/bad" }
        def load_key( path ): raise ValueError( "Invalid API key format in /keys/bad" )
        key = resolve_arbiter_api_key(
            get_cfg, load_key, env="testing",
            log_fn=lambda event, **k: logged.append( ( event, k ) ),
        )
        assert key is None
        assert logged[ 0 ][ 0 ] == "live_notify_disabled"
        assert "testing" in logged[ 0 ][ 1 ][ "reason" ]

    def test_missing_api_key_file_key_error_disables( self ):
        """(d) config dict lacks 'api_key_file' → KeyError → None + log."""
        logged = [ ]
        def get_cfg( env ): return { "api_url": "http://x:7999" }   # no api_key_file → KeyError
        def load_key( path ): raise AssertionError( "load_key must not be reached" )
        key = resolve_arbiter_api_key(
            get_cfg, load_key, env="development",
            log_fn=lambda event, **k: logged.append( ( event, k ) ),
        )
        assert key is None
        assert logged[ 0 ][ 0 ] == "live_notify_disabled"

    def test_default_log_fn_seam_resolves_on_failure( self, capsys ):
        """log_fn=None → _default_log_fn is used (covers the default-arg branch)."""
        def get_cfg( env ): raise ValueError( "boom" )
        key = resolve_arbiter_api_key( get_cfg, lambda p: "x", env="development" )
        assert key is None
        out = capsys.readouterr().out
        assert "live_notify_disabled" in out and "development" in out


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
    def send_to( self, r, b, metadata=None ): self.sent.append( ( r, b ) )
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
    live    = make_live_notify_fn( _queued_transport( pushed ), dedup_window_seconds=900, clock=clk )
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
    live = make_live_notify_fn( _queued_transport( pushed ), dedup_window_seconds=900, clock=clk )
    notify = make_escalation_notify_fn( gw, live_notify_fn=live, log_fn=lambda *a, **k: None )
    notify( "WHOLE-FLEET-STALL — escalating to Rick" )
    notify( "WHOLE-FLEET-STALL — escalating to Rick" )                 # repeat (recycle re-emit)
    assert len( pushed ) == 1                                          # live hop: 1 push
    assert len( gw.posts ) == 2                                        # durable: full audit trail


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
