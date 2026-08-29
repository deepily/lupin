#!/usr/bin/env python3
"""
The adversarial MUST-FAIL CONTROL for the REAL self-re-spin liveness observer
(store row 9e0678f6, work item 1; demanded by the reviewer).

This file is NOT the observer's coverage suite — that is Tiffany's
test_self_respin_observer.py. This file exists to answer ONE question Krishna put
to the oracle: when the seat fires a self-clear and DOES NOT come back, does the
REAL observer go red (alarm), or could an always-green stub pass the same input?

So every assertion here drives the shipped code
cosa.agents.heartbeat_arbiter.self_respin_observer — classify_marker and the fleet
path observe_fleet_self_respin (real disk glob + an injected pressure seam) — never
a local toy. The teeth-check swaps in an always-green oracle and shows it disagrees
with the real one on exactly the dead-seat case, proving the control discriminates.

Venue: :7999-eligible / local — pure classify + a tmp-dir marker read, no server.
"""
import datetime
import json
import os
import sys

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.agents.heartbeat_arbiter.self_respin_observer import (
    build_marker_dict,
    classify_marker,
    observe_fleet_self_respin,
    SelfRespinVerdict,
    SelfRespinAssessment,
    MARKER_PREFIX,
)

UTC     = datetime.timezone.utc
FIRED   = datetime.datetime( 2026, 8, 14, 2, 0, 0, tzinfo=UTC )
SESSION = "9662b5ac"
TMUX    = "cc-author-maria-1"


WAKE_NONCE = "wake-nonce-control"


def _marker( **overrides ):
    m = build_marker_dict(
        session_id       = SESSION,
        persona          = "maria",
        tmux_session     = TMUX,
        fired_at         = FIRED,
        delay_seconds    = 5,
        pre_clear_status = "over_budget",
        pre_clear_pct    = 61.0,
        memento_path     = "io/mementos/maria.md",
        memento_verified = True,
        wake_nonce       = WAKE_NONCE,
        grace_seconds    = 120,        # expected_return_by = FIRED + 125s
    )
    m.update( overrides )
    return m


def _record( *, status, last_turn_age_s, session_id=SESSION, tmux_session=TMUX ):
    return {
        "session_id"      : session_id,
        "tmux_session"    : tmux_session,
        "status"          : status,
        "last_turn_age_s" : last_turn_age_s,
    }


# ── Positive: a real return is NOT an alarm ────────────────────────────────────

def test_real_observer_confirms_a_genuine_return():
    """Same seat, over_budget→within_budget, fresh turn after the clear → RETURNED,
    no alarm. The one green the oracle is allowed to give."""
    record = _record( status="within_budget", last_turn_age_s=10 )   # last turn ~10s ago, after FIRED
    now    = FIRED + datetime.timedelta( seconds=30 )
    proof_at = FIRED + datetime.timedelta( seconds=10 )             # the seat wrote its proof, after the clear
    a = classify_marker( _marker(), record, now=now, wake_proof_nonce=WAKE_NONCE, wake_proof_at=proof_at )
    assert a.verdict == SelfRespinVerdict.RETURNED
    assert a.is_alarm is False


# ── MUST-FAIL CONTROL: fired, never came back → the REAL observer goes red ──────

def test_control_dead_no_return_is_an_alarm_in_the_real_observer():
    """The silently-dead-seat case: past the deadline with no matching record (the
    seat never returned). The REAL classify_marker MUST return DEAD_NO_RETURN with
    is_alarm True — a red, not a green."""
    now = FIRED + datetime.timedelta( seconds=600 )                  # well past expected_return_by
    a = classify_marker( _marker(), None, now=now )                  # no record = seat absent
    assert a.verdict == SelfRespinVerdict.DEAD_NO_RETURN
    assert a.is_alarm is True


def test_control_no_clear_effect_still_over_budget_past_deadline_alarms():
    """A seat still reading over_budget past the deadline (the clear had no effect)
    is also a dead-no-return alarm — 'alive' is not 'came back'."""
    record = _record( status="over_budget", last_turn_age_s=10 )
    now    = FIRED + datetime.timedelta( seconds=600 )
    a = classify_marker( _marker(), record, now=now )
    assert a.verdict == SelfRespinVerdict.DEAD_NO_RETURN
    assert a.is_alarm is True


# ── Cheech's ruling at the observer layer: "unknown" is never a return ──────────

def test_control_unknown_pre_status_is_never_confirmed_as_returned():
    """Sensor-down at fire time records pre_clear_status='unknown' (never a forged
    over_budget). Even with a perfect-looking within_budget, same-seat, fresh-turn
    record, the observer must NOT classify it RETURNED — it refuses to claim an
    over→within transition whose high side was never observed."""
    marker = _marker( pre_clear_status="unknown" )
    record = _record( status="within_budget", last_turn_age_s=10 )
    now    = FIRED + datetime.timedelta( seconds=30 )                # inside the return window
    a = classify_marker( marker, record, now=now )
    assert a.verdict != SelfRespinVerdict.RETURNED                   # no manufactured confirmation
    assert a.verdict == SelfRespinVerdict.PENDING and a.is_alarm is False


# ── Teeth: an always-green oracle would pass the dead-seat input ────────────────

def test_control_has_teeth_the_real_observer_diverges_from_always_green():
    """Prove the control discriminates: an always-green oracle returns no alarm on
    the dead-seat input, where the REAL observer alarms. If the two ever agreed on
    this input, the negative case would be decorative."""
    def always_green( marker, record, *, now ):
        return SelfRespinAssessment(
            session_id=marker.get( "session_id", "" ), persona=marker.get( "persona", "" ),
            verdict=SelfRespinVerdict.RETURNED, reason="stub", is_alarm=False,
        )

    now  = FIRED + datetime.timedelta( seconds=600 )
    real = classify_marker( _marker(), None, now=now )
    foil = always_green( _marker(), None, now=now )
    assert real.is_alarm is True and foil.is_alarm is False          # they must disagree here
    assert real.verdict != foil.verdict


# ── The fleet path end-to-end: real disk read + injected pressure seam ──────────

def test_control_fleet_path_alarms_on_a_disk_marker_with_no_return( tmp_path ):
    """Drive observe_fleet_self_respin over a REAL marker file on disk with a pressure
    payload that has no matching seat (nobody came back) → one DEAD_NO_RETURN alarm.
    Exercises the shipped glob + match + classify chain, not just the pure oracle."""
    marker_path = tmp_path / f"{MARKER_PREFIX}{SESSION}.json"
    marker_path.write_text( json.dumps( _marker() ) )

    now = FIRED + datetime.timedelta( seconds=600 )
    assessments = observe_fleet_self_respin(
        base_dir       = str( tmp_path ),
        now            = now,
        fetch_pressure = lambda: { "personas": {} },                 # nobody returned
    )
    assert len( assessments ) == 1
    assert assessments[ 0 ].verdict == SelfRespinVerdict.DEAD_NO_RETURN
    assert assessments[ 0 ].is_alarm is True


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
