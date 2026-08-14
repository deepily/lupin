#!/usr/bin/env python3
"""
Unit coverage for the self-re-spin E2E harness engine
(src/tests/e2e/self_respin_disposable_seat_harness.py, row 9e0678f6).

Proves the harness's SAFETY and its VERDICT MAPPING without ever spawning a seat or
firing a clear: the firing gate (no go → nothing fires), the disposable guard (go
but not disposable → nothing fires), and each observer verdict → harness result,
including the timeout when a seat never resolves. Observation runs the REAL oracle
over a real on-disk marker; only the pressure payload + clock are faked.

Venue: :7999-eligible / local — tmp-dir marker + injected pressure/clock, no server.
"""
import datetime
import json
import os
import sys

import pytest

# Bootstrap: src on path, plus the e2e harness module's directory.
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )
_e2e_path = os.path.join( _src_path, "tests", "e2e" )
if _e2e_path not in sys.path:
    sys.path.insert( 0, _e2e_path )

import self_respin_disposable_seat_harness as H
from cosa.agents.heartbeat_arbiter.self_respin_observer import build_marker_dict, MARKER_PREFIX

UTC     = datetime.timezone.utc
FIRED   = datetime.datetime( 2026, 8, 14, 2, 0, 0, tzinfo=UTC )
SESSION = "9662b5ac"
TMUX    = "cc-author-maria-1"


def _write_marker( base_dir ):
    m = build_marker_dict(
        session_id=SESSION, persona="maria", tmux_session=TMUX, fired_at=FIRED,
        delay_seconds=5, pre_clear_status="over_budget", pre_clear_pct=61.0,
        memento_path="io/mementos/maria.md", memento_verified=True, grace_seconds=120,
    )
    ( base_dir / f"{MARKER_PREFIX}{SESSION}.json" ).write_text( json.dumps( m ) )


def _section( **record ):
    return { "personas": { "maria": { "session_id": SESSION, "tmux_session": TMUX, **record } } }


_EMPTY = { "personas": {} }
_AFTER    = FIRED + datetime.timedelta( seconds=30 )
_PAST_DUE = FIRED + datetime.timedelta( seconds=600 )
_INSIDE   = FIRED + datetime.timedelta( seconds=60 )     # before expected_return_by (FIRED+125s)


class _Recorder:
    def __init__( self ): self.calls = []
    def __call__( self, sid ): self.calls.append( sid )


# ── The firing gate + disposable guard: nothing fires unless BOTH hold ──────────

def test_no_go_returns_awaiting_and_never_fires():
    fire = _Recorder()
    result, a = H.run( session_id=SESSION, go=False, disposable=True, steps=[], base_dir="/nope", fire_fn=fire )
    assert result == H.AWAITING_GO and a is None
    assert fire.calls == []


def test_go_but_not_disposable_refuses_and_never_fires():
    fire = _Recorder()
    result, a = H.run( session_id=SESSION, go=True, disposable=False, steps=[], base_dir="/nope", fire_fn=fire )
    assert result == H.REFUSED_NOT_DISPOSABLE and a is None
    assert fire.calls == []


def test_default_fire_fn_refuses_by_construction():
    """The default fire_fn raises — the harness cannot fire unless a real one is injected."""
    with pytest.raises( RuntimeError ):
        H.run( session_id=SESSION, go=True, disposable=True, steps=[], base_dir="/nope" )


# ── Verdict mapping over the REAL observer + a real on-disk marker ──────────────

def test_returned_maps_to_success( tmp_path ):
    _write_marker( tmp_path )
    fire = _Recorder()
    steps = [ ( _AFTER, _section( status="within_budget", last_turn_age_s=10 ) ) ]
    result, a = H.run( session_id=SESSION, go=True, disposable=True, steps=steps,
                       base_dir=str( tmp_path ), fire_fn=fire )
    assert result == H.SUCCESS_RETURNED
    assert fire.calls == [ SESSION ]                     # fired exactly once


def test_dead_no_return_maps_to_failure( tmp_path ):
    _write_marker( tmp_path )
    steps = [ ( _PAST_DUE, _EMPTY ) ]                    # nobody came back, past the deadline
    result, a = H.run( session_id=SESSION, go=True, disposable=True, steps=steps,
                       base_dir=str( tmp_path ), fire_fn=_Recorder() )
    assert result == H.FAIL_DEAD_NO_RETURN


def test_identity_mismatch_maps_to_failure( tmp_path ):
    _write_marker( tmp_path )
    steps = [ ( _AFTER, _section( status="within_budget", last_turn_age_s=10, tmux_session="cc-other-9" ) ) ]
    result, a = H.run( session_id=SESSION, go=True, disposable=True, steps=steps,
                       base_dir=str( tmp_path ), fire_fn=_Recorder() )
    assert result == H.FAIL_IDENTITY_MISMATCH


def test_pending_then_returned_polls_until_terminal( tmp_path ):
    _write_marker( tmp_path )
    steps = [
        ( _INSIDE, _EMPTY ),                                              # PENDING — keep polling
        ( _AFTER,  _section( status="within_budget", last_turn_age_s=10 ) ),  # RETURNED
    ]
    result, a = H.run( session_id=SESSION, go=True, disposable=True, steps=steps,
                       base_dir=str( tmp_path ), fire_fn=_Recorder() )
    assert result == H.SUCCESS_RETURNED


def test_never_resolving_times_out( tmp_path ):
    _write_marker( tmp_path )
    steps = [ ( _INSIDE, _EMPTY ), ( _INSIDE, _EMPTY ) ]                  # PENDING every tick, never terminal
    result, a = H.run( session_id=SESSION, go=True, disposable=True, steps=steps,
                       base_dir=str( tmp_path ), fire_fn=_Recorder() )
    assert result == H.FAIL_TIMEOUT
    assert a is not None and a.verdict.value == "PENDING"                # last seen was pending


def test_timeout_with_no_marker_returns_none_assessment( tmp_path ):
    """No marker on disk at all → no assessment for the session → FAIL_TIMEOUT, last None."""
    steps = [ ( _INSIDE, _EMPTY ) ]
    result, a = H.run( session_id=SESSION, go=True, disposable=True, steps=steps,
                       base_dir=str( tmp_path ), fire_fn=_Recorder() )
    assert result == H.FAIL_TIMEOUT and a is None


def test_assessment_for_session_returns_none_when_absent():
    assert H.assessment_for_session( [], "whatever" ) is None


def test_assessment_for_session_skips_nonmatching_then_none():
    """A list with a non-matching assessment exercises the loop's continue edge."""
    from types import SimpleNamespace
    others = [ SimpleNamespace( session_id="someone-else" ) ]
    assert H.assessment_for_session( others, SESSION ) is None


def test_arg_parser_parses_the_gate_flags():
    """Cover the CLI arg wiring: required session id + the go/disposable flags."""
    args = H._build_arg_parser().parse_args(
        [ "--session-id", "sess-x", "--go", "--i-am-disposable", "--deadline-seconds", "300" ]
    )
    assert args.session_id == "sess-x" and args.go is True
    assert args.i_am_disposable is True and args.deadline_seconds == 300


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
