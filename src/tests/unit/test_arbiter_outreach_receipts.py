#!/usr/bin/env python3
"""
Item B receipts (2026-06-11 outreach-receipts design §3) — the end-to-end
delivery-receipt machinery on ArbiterConsumerJob:

  • the outreach_id dot-connect spine: `arbiter_outreach` (intent, PLANNED
    recipients) → `arbiter_outreach_result` per (recipient, channel) hop →
    `arbiter_outreach_receipt` per terminal state — the R4 kill, regression-
    pinned: a failed live push can NEVER again journal "rick" as reached.
  • _emit_to_rick: delivered receipt / user_not_available → pending ledger /
    seam blow-up → http_error outcome / unacked-notes ride the next advisory.
  • _emit_dm: durable board write + best-effort dm_push, every case journaled;
    expects_ack registers the §3.4 tracker; resends derive "-rN" question_ids.
  • _check_outreach_receipts: threaded-ack receipt (acked-ledger principle),
    one bounded re-send, terminal unacked — at most 2 sends, no recursion.
  • _check_pending_outreach: re-announce-on-return (milestone-must-land) with
    interval/TTL governance and ledger-error visibility.
  • TONIGHT'S EXACT CHAIN regression: a 404-shaped live failure journals an
    http_error result and no delivered claim (the 21:28/22:01 silent miss can
    never hide again).

Venue: :7999-eligible / local — pure + mocked + tmp_path.
Design: src/rnd/v0.1.8/2026.06.11-arbiter-outreach-delivery-receipts-and-local-timestamps.md.
"""
import datetime
import os
import sys

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.agents.heartbeat_arbiter.arbiter_job import ArbiterConsumerJob
from cosa.agents.heartbeat_arbiter.outreach_ledger import add_pending, read_pending


NOW = datetime.datetime( 2026, 6, 11, 21, 28, 46, tzinfo=datetime.timezone.utc )


class _GW:
    """Fake gateway: records sends (with metadata) + serves canned topic reads."""
    def __init__( self ):
        self.sent    = [ ]                 # ( recipient, body, metadata )
        self.posts   = [ ]
        self.replies = { }                 # topic -> entries returned by read()
        self.send_boom = False
    def who( self, retention_hours=24 ): return [ ]
    def send_to( self, r, b, metadata=None ):
        if self.send_boom: raise RuntimeError( "store down" )
        self.sent.append( ( r, b, metadata ) )
    def post( self, t, b ): self.posts.append( ( t, b ) )
    def read( self, topic, since=None, limit=50 ): return self.replies.get( topic, [ ] )


class _Log:
    def __init__( self ):
        self.events = [ ]
    def __call__( self, event, **fields ):
        self.events.append( ( event, fields ) )
    def of( self, name ):
        return [ f for e, f in self.events if e == name ]


class _FixedClock:
    """now_iso seam pinned to a movable instant (the job parses it everywhere)."""
    def __init__( self, t=NOW ):
        self.t = t
    def now_iso( self ):
        return self.t.isoformat()
    def monotonic( self ):
        return 0.0
    async def sleep( self, seconds ):
        return None


def _job( gw=None, log=None, notify=None, **overrides ):
    cfg = dict(
        commons           = gw or _GW(),
        poll_seconds      = 5,
        manager_recipient = "DeclaredMgr",
        notify_fn         = notify or ( lambda m: [ { "channel": "live", "outcome": "queued" } ] ),
        log_fn            = log if log is not None else _Log(),
        clock             = _FixedClock(),
    )
    cfg.update( overrides )
    return ArbiterConsumerJob( **cfg )


def _notify_returning( *outcomes ):
    """A notify seam returning a fixed outcome list (the §3.2 contract)."""
    return lambda m: [ dict( o ) for o in outcomes ]


# ── constructor: the receipt knobs fail fast when config-dead ─────────────────

def test_zero_ack_window_raises():
    with pytest.raises( ValueError, match="outreach_ack_window_seconds" ):
        _job( outreach_ack_window_seconds=0 )


def test_zero_reannounce_interval_raises():
    with pytest.raises( ValueError, match="reannounce_interval_seconds" ):
        _job( reannounce_interval_seconds=0 )


def test_ttl_not_above_interval_raises():
    with pytest.raises( ValueError, match="reannounce_ttl_seconds" ):
        _job( reannounce_interval_seconds=300, reannounce_ttl_seconds=300 )


# ── _normalize_notify_results: the seam boundary ─────────────────────────────

def test_normalize_none_is_legacy_not_delivered():
    out = ArbiterConsumerJob._normalize_notify_results( None )
    assert out == [ { "channel": "live", "outcome": "legacy_notify" } ]


def test_normalize_single_dict_wraps_and_list_passes():
    one = { "channel": "live", "outcome": "queued" }
    assert ArbiterConsumerJob._normalize_notify_results( one ) == [ one ]
    assert ArbiterConsumerJob._normalize_notify_results( [ one ] ) == [ one ]


# ── _route: intent (planned) + per-hop results — the R4 kill ─────────────────

def test_route_journals_intent_results_and_delivered_receipt():
    gw, log = _GW(), _Log()
    job = _job( gw, log=log, notify=_notify_returning(
        { "channel": "durable", "outcome": "posted" },
        { "channel": "live", "outcome": "queued", "http_status": 200 } ) )
    job._route( 11, "WHOLE-FLEET-STALL", active_managers=[ "Tiberius" ] )

    intent = log.of( "arbiter_outreach" )[ 0 ]
    assert intent[ "recipients" ] == [ "rick", "Tiberius" ]            # the PLANNED set
    oid = intent[ "outreach_id" ]

    results = log.of( "arbiter_outreach_result" )
    by_hop  = { ( f[ "recipient" ], f[ "channel" ] ): f for f in results }
    assert by_hop[ ( "rick", "durable" ) ][ "outcome" ]      == "posted"
    assert by_hop[ ( "rick", "live" ) ][ "outcome" ]         == "queued"
    assert by_hop[ ( "Tiberius", "dm" ) ][ "outcome" ]       == "posted"
    assert by_hop[ ( "Tiberius", "dm_push" ) ][ "outcome" ]  == "disabled"   # no hop wired
    assert all( f[ "outreach_id" ] == oid for f in results )            # ONE grep shows the chain

    receipt = log.of( "arbiter_outreach_receipt" )[ 0 ]
    assert receipt[ "recipient" ] == "rick" and receipt[ "outcome" ] == "delivered"


def test_route_failed_live_push_never_claims_delivery_TONIGHTS_CHAIN():
    """REGRESSION PIN for the 2026-06-11 21:28/22:01 silent miss (R4): the live
    hop 404s → the journal carries an http_error RESULT and NO delivered
    receipt — the intent event alone can never again read as 'rick reached'."""
    gw, log = _GW(), _Log()
    job = _job( gw, log=log, notify=_notify_returning(
        { "channel": "durable", "outcome": "posted" },
        { "channel": "live", "outcome": "http_error", "http_status": 404,
          "detail": "404 User not found: ${LUPIN_DEV_EMAIL}" } ) )
    job._route( 11, "WHOLE-FLEET-STALL", active_managers=[ "Tiberius" ] )

    live = [ f for f in log.of( "arbiter_outreach_result" )
             if f[ "recipient" ] == "rick" and f[ "channel" ] == "live" ][ 0 ]
    assert live[ "outcome" ] == "http_error" and live[ "http_status" ] == 404
    assert log.of( "arbiter_outreach_receipt" ) == [ ]                  # NO delivery claim, anywhere


def test_route_notify_seam_blowup_degrades_to_http_error_outcome():
    gw, log = _GW(), _Log()
    def boom( m ): raise RuntimeError( ":7999 vaporized" )
    job = _job( gw, log=log, notify=boom )
    job._route( 10, "DECISION-NEEDED" )                                 # Rick-only tier
    results = log.of( "arbiter_outreach_result" )
    assert results[ 0 ][ "outcome" ] == "http_error" and "vaporized" in results[ 0 ][ "detail" ]


def test_route_legacy_none_notify_journals_legacy_not_delivered():
    gw, log = _GW(), _Log()
    job = _job( gw, log=log, notify=lambda m: None )                    # legacy seam shape
    job._route( 10, "DECISION-NEEDED" )
    assert log.of( "arbiter_outreach_result" )[ 0 ][ "outcome" ] == "legacy_notify"
    assert log.of( "arbiter_outreach_receipt" ) == [ ]                  # never claimed delivered


# ── _emit_to_rick: ledger entry on user_not_available ────────────────────────

def test_user_not_available_enters_pending_ledger( tmp_path ):
    path = tmp_path / "pending.json"
    gw, log = _GW(), _Log()
    job = _job( gw, log=log, pending_ledger_path=str( path ),
                notify=_notify_returning( { "channel": "live", "outcome": "user_not_available" } ) )
    job._route( 11, "WHOLE-FLEET-STALL", active_managers=[ ] )
    entries = read_pending( path )
    assert len( entries ) == 1
    entry = next( iter( entries.values() ) )
    assert entry[ "kind" ] == "stall" and entry[ "case" ] == 11
    assert entry[ "message" ] == "WHOLE-FLEET-STALL" and entry[ "attempts" ] == 1
    assert log.of( "arbiter_outreach_receipt" ) == [ ]                  # not terminal yet — pending


def test_user_not_available_without_ledger_path_is_resultonly():
    gw, log = _GW(), _Log()
    job = _job( gw, log=log,
                notify=_notify_returning( { "channel": "live", "outcome": "user_not_available" } ) )
    job._route( 11, "WHOLE-FLEET-STALL", active_managers=[ ] )
    assert log.of( "arbiter_outreach_result" )[ 0 ][ "outcome" ] == "user_not_available"


def test_ledger_write_failure_is_journaled_not_raised( tmp_path ):
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    blocked.chmod( 0o500 )
    try:
        gw, log = _GW(), _Log()
        job = _job( gw, log=log, pending_ledger_path=str( blocked / "sub" / "pending.json" ),
                    notify=_notify_returning( { "channel": "live", "outcome": "user_not_available" } ) )
        job._route( 11, "WHOLE-FLEET-STALL", active_managers=[ ] )      # must not raise
        assert log.of( "outreach_ledger_error" )                        # visible, never silent
    finally:
        blocked.chmod( 0o700 )


def test_unacked_notes_ride_next_rick_advisory():
    gw, log = _GW(), _Log()
    captured = [ ]
    def notify( m ):
        captured.append( m )
        return [ { "channel": "live", "outcome": "queued" } ]
    job = _job( gw, log=log, notify=notify )
    job._unacked_notes.append( "stall abc12345 to Tiberius" )
    job._route( 10, "DECISION-NEEDED" )
    assert "[unacked prior outreach: stall abc12345 to Tiberius]" in captured[ 0 ]
    assert job._unacked_notes == [ ]                                    # consumed once
    job._route( 10, "SECOND" )
    assert "unacked prior" not in captured[ 1 ]


# ── _emit_dm: board write + push hop, every case journaled ───────────────────

def test_emit_dm_stamps_threading_metadata_and_registers_ack():
    gw, log = _GW(), _Log()
    job = _job( gw, log=log )
    job._emit_dm( "oid1", "stall", "Tiberius", "body", expects_ack=True )
    recipient, body, metadata = gw.sent[ 0 ]
    assert recipient == "Tiberius" and body == "body"
    assert metadata[ "outreach_id" ] == "oid1" and metadata[ "question_id" ] == "oid1"
    assert metadata[ "expects_ack" ] is True
    assert "oid1" in job._awaiting_ack and job._awaiting_ack[ "oid1" ][ "persona" ] == "Tiberius"


def test_emit_dm_no_ack_does_not_register():
    gw, log = _GW(), _Log()
    job = _job( gw, log=log )
    job._emit_dm( "oid1", "stuck_poke", "Worker", "body", expects_ack=False )
    assert job._awaiting_ack == { }


def test_emit_dm_send_failure_is_post_error_outcome():
    gw, log = _GW(), _Log()
    gw.send_boom = True
    job = _job( gw, log=log )
    job._emit_dm( "oid1", "stall", "Tiberius", "body" )                 # must not raise
    dm = [ f for f in log.of( "arbiter_outreach_result" ) if f[ "channel" ] == "dm" ][ 0 ]
    assert dm[ "outcome" ] == "post_error" and "store down" in dm[ "detail" ]


def test_emit_dm_push_hop_outcome_journaled_and_resend_derives_qid():
    gw, log = _GW(), _Log()
    pushes = [ ]
    def dm_push( persona, qid ):
        pushes.append( ( persona, qid ) )
        return { "channel": "dm_push", "outcome": "dispatched" }
    job = _job( gw, log=log, dm_push_fn=dm_push )
    job._emit_dm( "oid1", "stall", "Tiberius", "body", attempt=1 )
    job._emit_dm( "oid1", "stall", "Tiberius", "body", attempt=2 )      # resend
    assert pushes == [ ( "Tiberius", "oid1" ), ( "Tiberius", "oid1-r2" ) ]   # no 409 collision
    assert gw.sent[ 1 ][ 2 ][ "question_id" ] == "oid1-r2"              # board metadata matches
    push_results = [ f for f in log.of( "arbiter_outreach_result" ) if f[ "channel" ] == "dm_push" ]
    assert [ f[ "attempt" ] for f in push_results ] == [ 1, 2 ]


def test_emit_dm_push_hop_blowup_degrades_to_push_unavailable():
    gw, log = _GW(), _Log()
    def boom( persona, qid ): raise RuntimeError( "register-question down" )
    job = _job( gw, log=log, dm_push_fn=boom )
    job._emit_dm( "oid1", "stall", "Tiberius", "body" )
    push = [ f for f in log.of( "arbiter_outreach_result" ) if f[ "channel" ] == "dm_push" ][ 0 ]
    assert push[ "outcome" ] == "push_unavailable" and "register-question" in push[ "detail" ]


# ── _check_outreach_receipts: ack → resend-once → terminal unacked ───────────

def _ack_entry( qid ):
    return { "metadata": { "in_reply_to": qid }, "body": "ack" }


def test_threaded_reply_closes_with_acked_receipt():
    gw, log = _GW(), _Log()
    job = _job( gw, log=log )
    job._emit_dm( "oid1", "stall", "Tiberius", "body", expects_ack=True )
    gw.replies[ "dm-tiberius" ] = [ _ack_entry( "oid1" ) ]
    assert job._check_outreach_receipts( NOW + datetime.timedelta( seconds=74 ) ) == 1
    receipt = log.of( "arbiter_outreach_receipt" )[ 0 ]
    assert receipt[ "outcome" ] == "acked" and receipt[ "latency_s" ] == 74
    assert job._awaiting_ack == { }


def test_reply_to_resend_qid_also_acks():
    """A reply threading the '-r2' resend question_id still closes the ORIGINAL
    outreach (startswith matching)."""
    gw, log = _GW(), _Log()
    job = _job( gw, log=log )
    job._emit_dm( "oid1", "stall", "Tiberius", "body", expects_ack=True )
    gw.replies[ "dm-tiberius" ] = [ _ack_entry( "oid1-r2" ) ]
    assert job._check_outreach_receipts( NOW + datetime.timedelta( seconds=10 ) ) == 1


def test_within_window_no_ack_waits():
    gw, log = _GW(), _Log()
    job = _job( gw, log=log, outreach_ack_window_seconds=900 )
    job._emit_dm( "oid1", "stall", "Tiberius", "body", expects_ack=True )
    assert job._check_outreach_receipts( NOW + datetime.timedelta( seconds=100 ) ) == 0
    assert "oid1" in job._awaiting_ack                                  # still tracked, no resend
    assert len( gw.sent ) == 1


def test_window_elapsed_resends_once_then_terminal_unacked():
    gw, log = _GW(), _Log()
    job = _job( gw, log=log, outreach_ack_window_seconds=900 )
    job._emit_dm( "oid1", "stall", "Tiberius", "body", expects_ack=True )

    # window 1 elapses → ONE resend (attempt 2), tracker stays
    t1 = NOW + datetime.timedelta( seconds=901 )
    assert job._check_outreach_receipts( t1 ) == 0
    assert len( gw.sent ) == 2 and gw.sent[ 1 ][ 2 ][ "question_id" ] == "oid1-r2"
    assert job._awaiting_ack[ "oid1" ][ "resends" ] == 1

    # window 2 elapses, still nothing → terminal unacked + the fact queued for Rick
    t2 = t1 + datetime.timedelta( seconds=901 )
    assert job._check_outreach_receipts( t2 ) == 0
    receipt = log.of( "arbiter_outreach_receipt" )[ 0 ]
    assert receipt[ "outcome" ] == "unacked" and receipt[ "resends" ] == 1
    assert job._awaiting_ack == { }
    assert len( gw.sent ) == 2                                          # at most 2 sends — no third, ever
    assert any( "Tiberius" in note for note in job._unacked_notes )


def test_gateway_read_blowup_degrades_to_window_governance():
    gw, log = _GW(), _Log()
    job = _job( gw, log=log )
    job._emit_dm( "oid1", "stall", "Tiberius", "body", expects_ack=True )
    def boom( topic, since=None, limit=50 ): raise RuntimeError( "fs down" )
    gw.read = boom
    assert job._check_outreach_receipts( NOW + datetime.timedelta( seconds=10 ) ) == 0   # no raise
    assert "oid1" in job._awaiting_ack


# ── _check_pending_outreach: re-announce-on-return ───────────────────────────

def _pending_job( tmp_path, retry_outcomes, log=None, **overrides ):
    """A job with a real ledger file + a scripted live_retry_fn."""
    path  = tmp_path / "pending.json"
    calls = [ ]
    def live_retry( message ):
        calls.append( message )
        out = retry_outcomes[ min( len( calls ) - 1, len( retry_outcomes ) - 1 ) ]
        if isinstance( out, Exception ):
            raise out
        return { "channel": "live", "outcome": out }
    job = _job( _GW(), log=log if log is not None else _Log(),
                pending_ledger_path=str( path ), live_retry_fn=live_retry, **overrides )
    return job, path, calls


def test_inert_without_ledger_or_retry_fn( tmp_path ):
    job = _job( _GW(), log=_Log() )                                     # neither wired
    assert job._check_pending_outreach( NOW ) == 0
    job2 = _job( _GW(), log=_Log(), pending_ledger_path=str( tmp_path / "p.json" ) )
    assert job2._check_pending_outreach( NOW ) == 0                     # no retry fn → inert


def test_reannounce_delivers_and_resolves( tmp_path ):
    log = _Log()
    job, path, calls = _pending_job( tmp_path, [ "queued" ], log=log )
    add_pending( path, "oid1", message="STALL", kind="stall", case=11,
                 created_ts=NOW.isoformat(), last_outcome="user_not_available" )
    fired = job._check_pending_outreach( NOW + datetime.timedelta( seconds=301 ) )
    assert fired == 1 and calls == [ "STALL" ]
    receipt = log.of( "arbiter_outreach_receipt" )[ 0 ]
    assert receipt[ "outcome" ] == "reannounced_delivered" and receipt[ "attempts" ] == 2
    assert read_pending( path ) == { }                                  # resolved


def test_reannounce_interval_governs( tmp_path ):
    job, path, calls = _pending_job( tmp_path, [ "queued" ] )
    add_pending( path, "oid1", message="STALL", kind="stall", case=11,
                 created_ts=NOW.isoformat(), last_outcome="user_not_available" )
    assert job._check_pending_outreach( NOW + datetime.timedelta( seconds=100 ) ) == 0
    assert calls == [ ]                                                 # not due yet


def test_reannounce_miss_records_attempt( tmp_path ):
    log = _Log()
    job, path, calls = _pending_job( tmp_path, [ "user_not_available" ], log=log )
    add_pending( path, "oid1", message="STALL", kind="stall", case=11,
                 created_ts=NOW.isoformat(), last_outcome="user_not_available" )
    assert job._check_pending_outreach( NOW + datetime.timedelta( seconds=301 ) ) == 1
    entry = read_pending( path )[ "oid1" ]
    assert entry[ "attempts" ] == 2 and entry[ "last_outcome" ] == "user_not_available"
    result = log.of( "arbiter_outreach_result" )[ 0 ]
    assert result[ "attempt" ] == 2 and result[ "outcome" ] == "user_not_available"


def test_reannounce_retry_blowup_degrades_to_http_error( tmp_path ):
    log = _Log()
    job, path, calls = _pending_job( tmp_path, [ RuntimeError( "down" ) ], log=log )
    add_pending( path, "oid1", message="STALL", kind="stall", case=11,
                 created_ts=NOW.isoformat(), last_outcome="user_not_available" )
    assert job._check_pending_outreach( NOW + datetime.timedelta( seconds=301 ) ) == 1
    assert log.of( "arbiter_outreach_result" )[ 0 ][ "outcome" ] == "http_error"


def test_ttl_expiry_is_terminal_expired_receipt( tmp_path ):
    log = _Log()
    job, path, calls = _pending_job( tmp_path, [ "queued" ], log=log,
                                     reannounce_ttl_seconds=86400 )
    add_pending( path, "oid1", message="STALL", kind="stall", case=11,
                 created_ts=NOW.isoformat(), last_outcome="user_not_available" )
    fired = job._check_pending_outreach( NOW + datetime.timedelta( seconds=86401 ) )
    assert fired == 0 and calls == [ ]                                  # expired BEFORE any retry
    receipt = log.of( "arbiter_outreach_receipt" )[ 0 ]
    assert receipt[ "outcome" ] == "expired" and receipt[ "attempts" ] == 1
    assert read_pending( path ) == { }


def test_malformed_ledger_entry_is_expired_with_detail( tmp_path ):
    log = _Log()
    job, path, calls = _pending_job( tmp_path, [ "queued" ], log=log )
    from cosa.agents.heartbeat_arbiter.outreach_ledger import write_pending
    write_pending( path, { "bad": { "created_ts": "not-a-ts" } } )
    assert job._check_pending_outreach( NOW ) == 0
    receipt = log.of( "arbiter_outreach_receipt" )[ 0 ]
    assert receipt[ "outcome" ] == "expired" and "malformed" in receipt[ "detail" ]
    assert read_pending( path ) == { }                                  # removed, not skipped forever


def test_emit_to_rick_without_live_channel_outcome_no_receipt():
    """A notify seam reporting only the durable channel (no live hop wired into
    its composition) journals the result and stops — no receipt, no ledger."""
    gw, log = _GW(), _Log()
    job = _job( gw, log=log,
                notify=_notify_returning( { "channel": "durable", "outcome": "posted" } ) )
    job._route( 10, "DECISION-NEEDED" )
    assert log.of( "arbiter_outreach_result" )[ 0 ][ "channel" ] == "durable"
    assert log.of( "arbiter_outreach_receipt" ) == [ ]


def test_pending_ledger_removal_failures_are_journaled( tmp_path ):
    """All four §3.5 ledger-write-failure legs (malformed-remove, TTL-remove,
    delivered-remove, miss-record) journal outreach_ledger_error and never raise."""
    from cosa.agents.heartbeat_arbiter.outreach_ledger import write_pending
    path = tmp_path / "pending.json"
    write_pending( path, {
        "bad"  : { "created_ts": "not-a-ts" },
        "old"  : { "message": "OLD", "kind": "stall", "case": 11,
                   "created_ts": ( NOW - datetime.timedelta( days=2 ) ).isoformat(),
                   "attempts": 3,
                   "last_attempt_ts": ( NOW - datetime.timedelta( days=2 ) ).isoformat() },
        "due"  : { "message": "DUE", "kind": "stall", "case": 11,
                   "created_ts": NOW.isoformat(), "attempts": 1,
                   "last_attempt_ts": NOW.isoformat() },
        "due2" : { "message": "DUE2", "kind": "stall", "case": 11,
                   "created_ts": NOW.isoformat(), "attempts": 1,
                   "last_attempt_ts": NOW.isoformat() },
    } )
    outcomes = { "DUE": "queued", "DUE2": "user_not_available" }
    log = _Log()
    job = _job( _GW(), log=log, pending_ledger_path=str( path ),
                live_retry_fn=lambda m: { "channel": "live", "outcome": outcomes[ m ] } )
    tmp_path.chmod( 0o500 )                                           # ledger dir now unwritable
    try:
        job._check_pending_outreach( NOW + datetime.timedelta( seconds=301 ) )   # must not raise
    finally:
        tmp_path.chmod( 0o700 )
    errors = log.of( "outreach_ledger_error" )
    assert { e[ "outreach_id" ] for e in errors } == { "bad", "old", "due", "due2" }
    # the receipts themselves still journaled (visibility unbroken by the bad disk)
    receipt_outcomes = { f[ "outreach_id" ]: f[ "outcome" ] for f in log.of( "arbiter_outreach_receipt" ) }
    assert receipt_outcomes[ "bad" ] == "expired" and receipt_outcomes[ "old" ] == "expired"
    assert receipt_outcomes[ "due" ] == "reannounced_delivered"


# ── direct-send sites carry the spine too ────────────────────────────────────

def test_decision_cc_uses_emit_dm_with_ack():
    gw, log = _GW(), _Log()
    job = _job( gw, log=log,
                resolve_manager_fn=lambda sid, declared_manager=None: { "manager_persona": "MgrX" } )
    job._cc_decision_manager( { "sender_session_id": "s1", "body": "pick A or B" } )
    intent = log.of( "arbiter_outreach" )[ 0 ]
    assert intent[ "kind" ] == "decision_cc" and intent[ "outreach_id" ]
    assert gw.sent[ 0 ][ 2 ][ "expects_ack" ] is True
    assert len( job._awaiting_ack ) == 1


def test_poll_error_escalation_rides_the_spine():
    gw, log = _GW(), _Log()
    job = _job( gw, log=log, poll_error_escalate_threshold=1,
                notify=_notify_returning( { "channel": "live", "outcome": "queued" } ) )
    job._on_poll_error( RuntimeError( "boom" ) )
    intent = log.of( "arbiter_outreach" )[ 0 ]
    assert intent[ "kind" ] == "poll_error_escalation" and intent[ "outreach_id" ]
    result = log.of( "arbiter_outreach_result" )[ 0 ]
    assert result[ "outreach_id" ] == intent[ "outreach_id" ]
    assert log.of( "arbiter_outreach_receipt" )[ 0 ][ "outcome" ] == "delivered"


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
