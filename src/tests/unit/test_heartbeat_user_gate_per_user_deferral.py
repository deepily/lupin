#!/usr/bin/env python3
"""
Unit tests — per-USER gate deferral (store row be56bff8).

The defect: a user-gate deferred via the STORE (task_transition -> blocked +
future next_chase_ts, the ONLY deferral verb an agent seat actually has) still
reads as DUE in the hold file, because the hold-file relief valve (75f392c0)
keys ONLY on the hold-file gate row's OWN next_chase_ts — which the store
deferral never touches, and which the agent cannot touch (defer_to_chase is
host-side only). Two independent representations of one fact, no key to link
them.

The reconciliation (Mr. Radio, 2026-08-03): make it a per-USER question, not a
per-gate one. "Rick is unreachable until T" is one fact about a person; every
gate awaiting that person inherits it. So the suppression asks "is this gate's
user deferred right now?" — a single store-derived instant, `user_chase_until`
— and no hold-file gate ever has to be linked to a store row.

Expiry is at READ time, exactly like a parked row: once now >= user_chase_until,
the store row's chase is in the past, the IO shell computes no future chase, and
the gate re-surfaces. No sweeper, no daemon.

PURE layer only — the store query + `user_chase_until` derivation lives in the
Stop-hook IO shell; here we inject the resolved epoch, no clock, no IO.
"""
import datetime as _dt

from lupin_cli.claude_code.hooks.lib import heartbeat_user_gates as ug


_T0  = _dt.datetime( 2026, 8, 3, 6, 0, 0, tzinfo=_dt.timezone.utc )
_NOW = _T0.timestamp()


def _ago( seconds ):
    """ISO-8601 string for `seconds` BEFORE the fixed _NOW reference (past)."""
    return ( _T0 - _dt.timedelta( seconds=seconds ) ).isoformat()


def _ahead_epoch( seconds ):
    """POSIX epoch `seconds` AFTER the fixed _NOW reference (future)."""
    return ( _T0 + _dt.timedelta( seconds=seconds ) ).timestamp()


# A stale, never-deferred hold-file gate: no OWN next_chase_ts, last asked 2h ago.
# Under the CURRENT relief valve this gate is unambiguously DUE and pokeable — it
# is the exact storm the store deferral was supposed to have silenced.
def _stale_undeferred_gate():
    return ug.make_gate( "g1", "Proceed with the push?", "ask_yes_no",
                         last_asked_ts=_ago( 7200 ) )


# ── control: WITHOUT a per-user deferral the gate stays due (unchanged) ─────────

def test_control_stale_gate_is_due_when_user_not_deferred():
    gate = _stale_undeferred_gate()
    assert ug.due_gates( [ gate ], _NOW ) == [ gate ]
    assert ug.pokeable_gates( [ gate ], _NOW ) == [ gate ]


# ── the fix: a FUTURE per-user chase suppresses every gate ──────────────────────

def test_future_user_chase_suppresses_pokeable():
    gate = _stale_undeferred_gate()
    until = _ahead_epoch( 3600 )                    # store says user deferred 1h out
    assert ug.pokeable_gates( [ gate ], _NOW, user_chase_until_epoch=until ) == [ ]


def test_future_user_chase_suppresses_due():
    gate = _stale_undeferred_gate()
    until = _ahead_epoch( 3600 )
    assert ug.due_gates( [ gate ], _NOW, user_chase_until_epoch=until ) == [ ]


def test_future_user_chase_suppresses_arbiter_aged():
    # The arbiter's aged-resurface reads the SAME hold file; it must honor the
    # same per-user deferral (sibling-gate lesson: wire every consumer).
    gate = _stale_undeferred_gate()
    until = _ahead_epoch( 3600 )
    assert ug.aged_open_gates( [ gate ], _NOW, 600, user_chase_until_epoch=until ) == [ ]


# ── read-time expiry: a PAST user chase no longer suppresses ────────────────────

def test_past_user_chase_does_not_suppress():
    gate = _stale_undeferred_gate()
    until = ( _T0 - _dt.timedelta( seconds=1 ) ).timestamp()   # chase already passed
    assert ug.due_gates( [ gate ], _NOW, user_chase_until_epoch=until ) == [ gate ]


def test_boundary_now_equals_user_chase_is_eligible():
    # Chase arrived EXACTLY now ⇒ eligible (mirrors is_chase_deferred's >= boundary).
    gate = _stale_undeferred_gate()
    assert ug.due_gates( [ gate ], _NOW, user_chase_until_epoch=_NOW ) == [ gate ]


def test_none_user_chase_is_backward_compatible():
    gate = _stale_undeferred_gate()
    assert ug.due_gates( [ gate ], _NOW, user_chase_until_epoch=None ) == [ gate ]


# ── predicate ───────────────────────────────────────────────────────────────

def test_is_user_deferred_predicate():
    assert ug.is_user_deferred( _NOW, _ahead_epoch( 1 ) ) is True
    assert ug.is_user_deferred( _NOW, _NOW ) is False                 # boundary
    assert ug.is_user_deferred( _NOW, ( _T0 - _dt.timedelta( 1 ) ).timestamp() ) is False
    assert ug.is_user_deferred( _NOW, None ) is False


# ── _blocked_by_has_user ──────────────────────────────────────────────────────

def test_blocked_by_has_user():
    assert ug._blocked_by_has_user( [ { "kind": "user", "id": "rick" } ] ) is True
    assert ug._blocked_by_has_user( [ { "kind": "item", "id": "x" },
                                      { "kind": "user", "id": "rick" } ] ) is True
    assert ug._blocked_by_has_user( [ { "kind": "persona", "id": "tiberius" } ] ) is False
    assert ug._blocked_by_has_user( [ "junk", None ] ) is False       # non-dict refs skipped
    assert ug._blocked_by_has_user( None ) is False                   # non-list
    assert ug._blocked_by_has_user( "not-a-list" ) is False


# ── derive_user_chase_until ───────────────────────────────────────────────────

def _blocked_row( next_chase_ts, kind="user" ):
    return { "status": "blocked", "next_chase_ts": next_chase_ts,
             "blocked_by": [ { "kind": kind, "id": "rick" } ] }


def test_derive_picks_soonest_future_user_chase():
    # soonest LAST (updates on the 2nd row) AND soonest FIRST (2nd row kept, not
    # replaced — the not-soonest branch) both exercised.
    rows_soonest_last  = [ _blocked_row( ( _T0 + _dt.timedelta( seconds=7200 ) ).isoformat() ),
                           _blocked_row( ( _T0 + _dt.timedelta( seconds=1800 ) ).isoformat() ) ]
    rows_soonest_first = [ _blocked_row( ( _T0 + _dt.timedelta( seconds=1800 ) ).isoformat() ),
                           _blocked_row( ( _T0 + _dt.timedelta( seconds=7200 ) ).isoformat() ) ]
    for rows in ( rows_soonest_last, rows_soonest_first ):
        got = ug.derive_user_chase_until( rows, _NOW )
        assert abs( got - _ahead_epoch( 1800 ) ) < 1e-6


def test_derive_ignores_past_and_non_user_and_unparseable():
    rows = [ _blocked_row( ( _T0 - _dt.timedelta( seconds=60 ) ).isoformat() ),     # past
             _blocked_row( ( _T0 + _dt.timedelta( seconds=900 ) ).isoformat(),
                           kind="persona" ),                                        # not a user
             _blocked_row( "not-a-timestamp" ),                                     # unparseable
             _blocked_row( None ),                                                  # absent chase
             "junk" ]                                                               # non-dict row
    assert ug.derive_user_chase_until( rows, _NOW ) is None


def test_derive_boundary_now_chase_is_not_future():
    # chase == now ⇒ arrived ⇒ not future ⇒ no deferral (mirrors is_user_deferred)
    rows = [ _blocked_row( _T0.isoformat() ) ]
    assert ug.derive_user_chase_until( rows, _NOW ) is None


def test_derive_empty_and_none():
    assert ug.derive_user_chase_until( [ ], _NOW ) is None
    assert ug.derive_user_chase_until( None, _NOW ) is None
