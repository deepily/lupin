#!/usr/bin/env python3
"""
Unit tests for the Heartbeat Hook pure decision composition.

Target: 100% line + branch + function coverage of
    src/lupin_cli/claude_code/hooks/lib/heartbeat_decision.py

Exhaustive over the §0 5-step decision matrix. All state injected; `now` is
pinned so freshness is deterministic.
"""
import datetime

from lupin_cli.claude_code.hooks.lib import heartbeat_decision as hd
from lupin_cli.claude_code.hooks.lib import heartbeat_work_owed as owed_mod


UTC = datetime.timezone.utc
NOW = datetime.datetime( 2026, 6, 4, 12, 0, 0, tzinfo=UTC )


def _hold( held_at=None, ttl_seconds=900, reason="r", work_owed=True ):
    return {
        "session_id"  : "s",
        "persona"     : "P",
        "held_at"     : held_at if held_at is not None else NOW.isoformat(),
        "ttl_seconds" : ttl_seconds,
        "work_owed"   : work_owed,
        "reason"      : reason,
        "awaiting"    : "none",
    }


def _owed_verdict():
    return owed_mod.evaluate_work_owed(
        todo_items=[ { "status": owed_mod.TODO_IN_PROGRESS, "owned_by_me": True } ]
    )


# ── Step 2 — honored hold ─────────────────────────────────────────────────────

def test_honored_fresh_reasoned_hold_does_not_poke():
    r = hd.decide_heartbeat( _hold(), None, 0, 3, now=NOW )
    assert r[ "outcome" ]     == hd.OUTCOME_HONORED
    assert r[ "hook_output" ] == { "continue": True }
    assert r[ "should_increment" ]  is False
    assert r[ "should_notify_cap" ] is False


# ── Step 3 — work-owed determination ──────────────────────────────────────────

def test_hold_declares_done_never_pokes():
    # Not honored (empty reason) + work_owed False → done
    hold = _hold( reason="", work_owed=False )
    r    = hd.decide_heartbeat( hold, _owed_verdict(), 0, 3, now=NOW )
    assert r[ "outcome" ]     == hd.OUTCOME_NOT_OWED
    assert r[ "hook_output" ] == { "continue": True }


def test_no_hold_oracle_empty_not_owed():
    r = hd.decide_heartbeat( None, owed_mod.evaluate_work_owed(), 0, 3, now=NOW )
    assert r[ "outcome" ] == hd.OUTCOME_NOT_OWED


def test_no_hold_none_oracle_not_owed():
    r = hd.decide_heartbeat( None, None, 0, 3, now=NOW )
    assert r[ "outcome" ] == hd.OUTCOME_NOT_OWED


# ── Step 4 — poke (under cap) ─────────────────────────────────────────────────

def test_oracle_owed_under_cap_pokes_with_oracle_reason():
    r = hd.decide_heartbeat( None, _owed_verdict(), 0, 3, now=NOW )
    assert r[ "outcome" ] == hd.OUTCOME_POKE
    assert r[ "hook_output" ][ "decision" ] == "block"
    assert "in-progress TODO" in r[ "hook_output" ][ "reason" ]
    assert r[ "should_increment" ] is True


def test_declared_owed_without_oracle_specifics_uses_declared_reason():
    # work owed via the hold's self-declared work_owed=True, but the hold is
    # NOT honored (empty reason) and the oracle is empty → declared-owed reason
    hold = _hold( reason="", work_owed=True )
    r    = hd.decide_heartbeat( hold, owed_mod.evaluate_work_owed(), 0, 3, now=NOW )
    assert r[ "outcome" ] == hd.OUTCOME_POKE
    assert r[ "hook_output" ][ "reason" ] == hd.DECLARED_OWED_REASON
    assert r[ "should_increment" ] is True


def test_expired_hold_with_work_owed_true_pokes():
    # Expired (not fresh) hold, work_owed True → pokeable; oracle also owed
    old  = ( NOW - datetime.timedelta( seconds=10_000 ) ).isoformat()
    hold = _hold( held_at=old, reason="was holding", work_owed=True )
    r    = hd.decide_heartbeat( hold, _owed_verdict(), 1, 3, now=NOW )
    assert r[ "outcome" ] == hd.OUTCOME_POKE


# ── Step 5 — cap reached ──────────────────────────────────────────────────────

def test_owed_at_cap_stops_nudging():
    r = hd.decide_heartbeat( None, _owed_verdict(), 3, 3, now=NOW )
    assert r[ "outcome" ]            == hd.OUTCOME_CAP_REACHED
    assert r[ "hook_output" ]        == { "continue": True }
    assert r[ "should_notify_cap" ]  is True
    assert r[ "should_increment" ]   is False


def test_owed_over_cap_stops_nudging():
    r = hd.decide_heartbeat( None, _owed_verdict(), 5, 3, now=NOW )
    assert r[ "outcome" ] == hd.OUTCOME_CAP_REACHED


# ── quick_smoke_test ──────────────────────────────────────────────────────────

def test_quick_smoke_test_passes():
    assert hd.quick_smoke_test() is True
