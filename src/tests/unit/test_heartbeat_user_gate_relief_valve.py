#!/usr/bin/env python3
"""
Unit tests — Stop-hook user-gate re-ask RELIEF VALVE (bug 75f392c0).

Target: 100% line + branch + function coverage of the relief-valve surface added
to src/lupin_cli/claude_code/hooks/lib/heartbeat_user_gates.py:
    - new schema fields   next_chase_ts / reask_count / reask_cap (make_gate)
    - is_chase_deferred    (fix #1 — future next_chase_ts ⇒ not due until then)
    - is_reask_capped      (fix #2 — N re-asks then quiet when no chase scheduled)
    - pokeable_gates       (the deferral-aware eligible set — feeds Face B)
    - due_gates            (now filtered through pokeable_gates FIRST)
    - bump_reask_count     (per-re-ask budget increment)
    - defer_to_chase       (fix #1 + #3 — offline/timeout default ⇒ defer to chase)

The module is PURE — every test injects parsed gate rows + an injected `now`
(no clock, no IO). The final section is the end-to-end REPRO: a gate deferred to
a future chase must NOT poke THROUGH an honored hold (the exact 75f392c0 storm),
while the same gate WITHOUT a chase DOES (the RED contrast the fix must preserve).
"""
import datetime as _dt

from lupin_cli.claude_code.hooks.lib import heartbeat_user_gates as ug
from lupin_cli.claude_code.hooks.lib import heartbeat_work_owed as owed_mod
from lupin_cli.claude_code.hooks.lib import heartbeat_decision as dec_mod


_T0  = _dt.datetime( 2026, 7, 3, 6, 0, 0, tzinfo=_dt.timezone.utc )
_NOW = _T0.timestamp()


def _ago( seconds ):
    """ISO-8601 string for `seconds` BEFORE the fixed _NOW reference (past)."""
    return ( _T0 - _dt.timedelta( seconds=seconds ) ).isoformat()


def _ahead( seconds ):
    """ISO-8601 string for `seconds` AFTER the fixed _NOW reference (future)."""
    return ( _T0 + _dt.timedelta( seconds=seconds ) ).isoformat()


# ── make_gate: new relief-valve fields ────────────────────────────────────────

def test_make_gate_relief_valve_defaults():
    g = ug.make_gate( "g1", "q", "ask_yes_no" )
    assert tuple( g.keys() ) == ug.GATE_FIELDS          # new fields in the schema
    assert g[ "next_chase_ts" ] is None
    assert g[ "reask_count" ]   == 0
    assert g[ "reask_cap" ]     == ug.DEFAULT_REASK_CAP


def test_make_gate_relief_valve_explicit():
    g = ug.make_gate( "g1", "q", "ask_yes_no",
                      next_chase_ts=_ahead( 3600 ), reask_count=2, reask_cap=5 )
    assert g[ "next_chase_ts" ] == _ahead( 3600 )
    assert g[ "reask_count" ]   == 2
    assert g[ "reask_cap" ]     == 5


# ── is_chase_deferred (fix #1) ────────────────────────────────────────────────

def test_is_chase_deferred_future_ts_is_deferred():
    g = ug.make_gate( "g", "q", "ask_yes_no", next_chase_ts=_ahead( 1800 ) )
    assert ug.is_chase_deferred( g, _NOW ) is True


def test_is_chase_deferred_past_ts_not_deferred():
    g = ug.make_gate( "g", "q", "ask_yes_no", next_chase_ts=_ago( 1 ) )
    assert ug.is_chase_deferred( g, _NOW ) is False


def test_is_chase_deferred_boundary_now_equals_ts_not_deferred():
    # Chase has ARRIVED exactly ⇒ eligible to re-ask (mirrors the >= due boundary).
    g = ug.make_gate( "g", "q", "ask_yes_no", next_chase_ts=_ago( 0 ) )
    assert ug.is_chase_deferred( g, _NOW ) is False


def test_is_chase_deferred_absent_not_deferred():
    g = ug.make_gate( "g", "q", "ask_yes_no" )              # next_chase_ts None
    assert ug.is_chase_deferred( g, _NOW ) is False


def test_is_chase_deferred_unparseable_not_deferred():
    g = { "id": "g", "next_chase_ts": "not-a-timestamp" }
    assert ug.is_chase_deferred( g, _NOW ) is False


def test_is_chase_deferred_non_dict_not_deferred():
    assert ug.is_chase_deferred( "junk", _NOW ) is False
    assert ug.is_chase_deferred( None, _NOW )  is False


# ── is_reask_capped (fix #2) ──────────────────────────────────────────────────

def test_is_reask_capped_under_cap_no_chase():
    g = ug.make_gate( "g", "q", "ask_yes_no", reask_count=2, reask_cap=3 )
    assert ug.is_reask_capped( g ) is False


def test_is_reask_capped_at_cap_no_chase():
    g = ug.make_gate( "g", "q", "ask_yes_no", reask_count=3, reask_cap=3 )
    assert ug.is_reask_capped( g ) is True


def test_is_reask_capped_over_cap_no_chase():
    g = ug.make_gate( "g", "q", "ask_yes_no", reask_count=9, reask_cap=3 )
    assert ug.is_reask_capped( g ) is True


def test_is_reask_capped_governed_by_chase_when_scheduled():
    # A scheduled chase (any next_chase_ts) governs the quiet window, NOT the count
    # cap — so an exhausted budget WITH a chase is NOT "capped" (is_chase_deferred
    # owns the future-window; a past chase resumes with a single re-engage poke).
    g = ug.make_gate( "g", "q", "ask_yes_no", reask_count=9, reask_cap=3,
                      next_chase_ts=_ahead( 3600 ) )
    assert ug.is_reask_capped( g ) is False


def test_is_reask_capped_missing_counts_default_under_cap():
    assert ug.is_reask_capped( { "id": "g" } ) is False    # count 0 < default cap


def test_is_reask_capped_bad_count_type_treated_zero():
    g = { "id": "g", "reask_count": "nope", "reask_cap": 3 }
    assert ug.is_reask_capped( g ) is False                # "nope" ⇒ 0 < 3


def test_is_reask_capped_bool_count_rejected():
    g = { "id": "g", "reask_count": True, "reask_cap": 3 }
    assert ug.is_reask_capped( g ) is False                # bool ⇒ 0 < 3


def test_is_reask_capped_bad_cap_falls_back_to_default():
    # A non-positive / bad cap falls back to DEFAULT_REASK_CAP; count at default
    # ⇒ capped.
    g = { "id": "g", "reask_count": ug.DEFAULT_REASK_CAP, "reask_cap": 0 }
    assert ug.is_reask_capped( g ) is True
    g2 = { "id": "g", "reask_count": ug.DEFAULT_REASK_CAP, "reask_cap": "x" }
    assert ug.is_reask_capped( g2 ) is True
    g3 = { "id": "g", "reask_count": ug.DEFAULT_REASK_CAP, "reask_cap": True }
    assert ug.is_reask_capped( g3 ) is True


def test_is_reask_capped_non_dict():
    assert ug.is_reask_capped( "junk" ) is False
    assert ug.is_reask_capped( None )   is False


# ── pokeable_gates ────────────────────────────────────────────────────────────

def test_pokeable_gates_excludes_deferred_and_capped_keeps_normal():
    normal   = ug.make_gate( "ok",  "q", "ask_yes_no", last_asked_ts=_ago( 660 ) )
    deferred = ug.make_gate( "def", "q", "ask_yes_no", last_asked_ts=_ago( 660 ),
                             next_chase_ts=_ahead( 1800 ) )
    capped   = ug.make_gate( "cap", "q", "ask_yes_no", last_asked_ts=_ago( 660 ),
                             reask_count=3, reask_cap=3 )
    out = [ g[ "id" ] for g in ug.pokeable_gates( [ normal, deferred, capped ], _NOW ) ]
    assert out == [ "ok" ]


def test_pokeable_gates_excludes_answered():
    answered = ug.make_gate( "a", "q", "ask_yes_no", answered=True )
    assert ug.pokeable_gates( [ answered ], _NOW ) == [ ]


def test_pokeable_gates_none_is_empty():
    assert ug.pokeable_gates( None, _NOW ) == [ ]


# ── due_gates: the relief valve applied (THE core 75f392c0 fix) ────────────────

def test_due_gates_deferred_future_chase_not_due_even_when_stale():
    # THE BUG: last asked 2h ago (way past the 10-min cadence) but a future chase
    # is scheduled ⇒ must NOT be due (no every-turn re-ask storm).
    g = ug.make_gate( "g", "q", "ask_yes_no", last_asked_ts=_ago( 7200 ),
                      next_chase_ts=_ahead( 10_800 ) )
    assert ug.due_gates( [ g ], _NOW ) == [ ]


def test_due_gates_capped_no_chase_not_due_even_when_stale():
    g = ug.make_gate( "g", "q", "ask_yes_no", last_asked_ts=_ago( 7200 ),
                      reask_count=3, reask_cap=3 )
    assert ug.due_gates( [ g ], _NOW ) == [ ]


def test_due_gates_past_chase_stale_is_due_again():
    # Chase time has arrived (past) + stale ⇒ due again (resume the conversation).
    g = ug.make_gate( "g", "q", "ask_yes_no", last_asked_ts=_ago( 7200 ),
                      next_chase_ts=_ago( 60 ) )
    assert [ x[ "id" ] for x in ug.due_gates( [ g ], _NOW ) ] == [ "g" ]


def test_due_gates_past_chase_overrides_exhausted_count_single_reengage():
    # Budget exhausted BUT the scheduled chase arrived ⇒ one re-engage poke is due
    # (is_reask_capped is False when a chase is set; is_chase_deferred is False for
    # a past chase). This is the "quiet until the chase, then resume" behavior.
    g = ug.make_gate( "g", "q", "ask_yes_no", last_asked_ts=_ago( 7200 ),
                      reask_count=9, reask_cap=3, next_chase_ts=_ago( 60 ) )
    assert [ x[ "id" ] for x in ug.due_gates( [ g ], _NOW ) ] == [ "g" ]


def test_due_gates_deferred_but_not_stale_still_not_due():
    g = ug.make_gate( "g", "q", "ask_yes_no", last_asked_ts=_ago( 60 ),
                      next_chase_ts=_ahead( 1800 ) )
    assert ug.due_gates( [ g ], _NOW ) == [ ]


def test_due_gates_normal_open_still_due_backward_compatible():
    # No relief-valve fields set ⇒ identical to legacy cadence behavior.
    g = ug.make_gate( "g", "q", "ask_yes_no", last_asked_ts=_ago( 660 ) )
    assert [ x[ "id" ] for x in ug.due_gates( [ g ], _NOW ) ] == [ "g" ]


# ── bump_reask_count ──────────────────────────────────────────────────────────

def test_bump_reask_count_increments():
    g   = ug.make_gate( "g", "q", "ask_yes_no", reask_count=1 )
    out = ug.bump_reask_count( [ g ], "g" )
    assert out[ 0 ][ "reask_count" ] == 2


def test_bump_reask_count_from_missing_is_one():
    out = ug.bump_reask_count( [ { "id": "g" } ], "g" )
    assert out[ 0 ][ "reask_count" ] == 1


def test_bump_reask_count_bad_type_treated_zero():
    out = ug.bump_reask_count( [ { "id": "g", "reask_count": "x" } ], "g" )
    assert out[ 0 ][ "reask_count" ] == 1
    out2 = ug.bump_reask_count( [ { "id": "g", "reask_count": True } ], "g" )
    assert out2[ 0 ][ "reask_count" ] == 1


def test_bump_reask_count_id_miss_is_noop():
    out = ug.bump_reask_count( [ ug.make_gate( "g", "q", "ask_yes_no", reask_count=4 ) ], "nope" )
    assert out[ 0 ][ "reask_count" ] == 4


def test_bump_reask_count_preserves_non_dicts_and_none():
    assert ug.bump_reask_count( None, "g" ) == [ ]
    assert ug.bump_reask_count( [ "junk" ], "g" ) == [ "junk" ]


def test_bump_reask_count_does_not_mutate_input():
    src = [ ug.make_gate( "g", "q", "ask_yes_no", reask_count=1 ) ]
    ug.bump_reask_count( src, "g" )
    assert src[ 0 ][ "reask_count" ] == 1


# ── defer_to_chase (fix #1 + #3) ──────────────────────────────────────────────

def test_defer_to_chase_sets_ts_and_resets_count():
    g   = ug.make_gate( "g", "q", "ask_yes_no", reask_count=3 )
    out = ug.defer_to_chase( [ g ], "g", _ahead( 10_800 ) )
    assert out[ 0 ][ "next_chase_ts" ] == _ahead( 10_800 )
    assert out[ 0 ][ "reask_count" ]   == 0        # fresh chase window
    # …and the deferred gate is no longer due despite being long-unasked
    assert ug.due_gates( out, _NOW ) == [ ]


def test_defer_to_chase_id_miss_is_noop():
    g   = ug.make_gate( "g", "q", "ask_yes_no" )
    out = ug.defer_to_chase( [ g ], "nope", _ahead( 3600 ) )
    assert out[ 0 ][ "next_chase_ts" ] is None


def test_defer_to_chase_preserves_non_dicts_and_none():
    assert ug.defer_to_chase( None, "g", _ahead( 3600 ) ) == [ ]
    assert ug.defer_to_chase( [ "junk" ], "g", _ahead( 3600 ) ) == [ "junk" ]


def test_defer_to_chase_does_not_mutate_input():
    src = [ ug.make_gate( "g", "q", "ask_yes_no", reask_count=2 ) ]
    ug.defer_to_chase( src, "g", _ahead( 3600 ) )
    assert src[ 0 ][ "next_chase_ts" ] is None and src[ 0 ][ "reask_count" ] == 2


# ── END-TO-END REPRO (bug 75f392c0): deferred gate must NOT poke a honored hold ─

def _honored_hold():
    """A fresh, reasoned, honored hold (the manager legitimately waiting)."""
    held_at = _dt.datetime( 2026, 7, 3, 5, 59, 0, tzinfo=_dt.timezone.utc ).isoformat()
    return { "held_at": held_at, "ttl_seconds": 900,
             "reason": "waiting on Rick (offline) — chase scheduled", "work_owed": True }


def test_repro_deferred_gate_does_not_poke_through_honored_hold():
    # A user-gate blocked on an OFFLINE user with a FUTURE chase: due_gates is
    # empty ⇒ no outstanding_user_gate ⇒ the honored hold is respected (NO poke).
    gate      = ug.make_gate( "7d50a03a", "Proceed?", "ask_yes_no",
                              last_asked_ts=_ago( 7200 ), next_chase_ts=_ahead( 10_800 ) )
    due       = ug.due_gates( [ gate ], _NOW )
    verdict   = owed_mod.evaluate_work_owed( open_user_gates=due )
    assert "outstanding_user_gate" not in verdict[ "signals" ]
    result    = dec_mod.decide_heartbeat( _honored_hold(), verdict, 0, 3, now=_T0 )
    assert result[ "outcome" ] == dec_mod.OUTCOME_HONORED   # relief valve engaged


def test_repro_contrast_undeferred_stale_gate_still_pokes():
    # RED contrast the fix must PRESERVE: the SAME stale gate with NO chase still
    # overrides the honored hold and pokes (a genuinely-unattended user-gate).
    gate      = ug.make_gate( "7d50a03a", "Proceed?", "ask_yes_no",
                              last_asked_ts=_ago( 7200 ) )
    due       = ug.due_gates( [ gate ], _NOW )
    verdict   = owed_mod.evaluate_work_owed( open_user_gates=due )
    assert "outstanding_user_gate" in verdict[ "signals" ]
    result    = dec_mod.decide_heartbeat( _honored_hold(), verdict, 0, 3, now=_T0 )
    assert result[ "outcome" ] == dec_mod.OUTCOME_POKE      # still surfaces (override)
