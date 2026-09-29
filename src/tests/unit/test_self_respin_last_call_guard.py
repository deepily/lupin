"""
Unit tests for the self_respin Last Call guard (row b134feb9, lupin half of row 6380199b).

perform_self_respin refuses when planning-is-prompting's last_call_window check says a
Last Call closing time is within 60 minutes ("skip"), proceeds on "proceed", and proceeds
WITH A NOTE on "unknown" or when the check itself raises. Every seam is injected; the one
test of the default seam fakes only subprocess.run.
"""

import datetime
import json
import subprocess

import pytest

import lupin_mcp.self_respin_core as sr


UTC  = datetime.timezone.utc
NOW  = datetime.datetime( 2026, 8, 14, 2, 21, tzinfo=UTC )
BODY = ( "board state: row b134feb9 in progress, manager mr radio, venue :7999 idle.\n" ) * 8

SKIP    = { "verdict": "skip", "row": "6380199b-aaaa", "close_at": "2026-09-29T23:00:00", "minutes_left": 29.0, "unread": [ ] }
PROCEED = { "verdict": "proceed", "row": None, "close_at": None, "minutes_left": None, "unread": [ ] }
UNKNOWN = { "verdict": "unknown", "row": None, "close_at": None, "minutes_left": None, "unread": [ "abc12345" ] }


class _Spy:
    def __init__( self, ret=None ):
        self.calls = 0
        self.args  = [ ]
        self.ret   = ret
    def __call__( self, *a, **k ):
        self.calls += 1
        self.args.append( a )
        return self.ret


def _run( tmp_path, check_fn, ask=None, sched=None ):
    memento = tmp_path / "memento.md"
    memento.write_text( "# memento\n" + BODY + sr.build_nonce_line( "u1", NOW - datetime.timedelta( minutes=1 ) ) + "\n" )
    ask   = ask   if ask   is not None else _Spy( "yes" )
    sched = sched if sched is not None else _Spy()
    r = sr.perform_self_respin(
        "sid1", persona="cheech", memento_path=str( memento ), memento_nonce="u1",
        pre_clear_status="over_budget", pre_clear_pct=61.0, now=NOW,
        resolve_tmux_fn=lambda sid: "cheech-mgr", verify_slot_fn=lambda *a, **k: ( True, "" ),
        ask_fn=ask, schedule_fn=sched, base_dir=str( tmp_path ), repo_root=str( tmp_path ),
        last_call_check_fn=check_fn,
    )
    return r, ask, sched


def test_skip_verdict_refuses_quoting_row_close_at_and_minutes_left( tmp_path ):
    r, ask, sched = _run( tmp_path, lambda within: SKIP )
    assert r.status == "aborted"
    assert "6380199b-aaaa" in r.reason and "2026-09-29T23:00:00" in r.reason and "29.0" in r.reason
    assert ask.calls == 0 and sched.calls == 0
    assert list( tmp_path.glob( ".self-respin-*" ) ) == [ ]


def test_proceed_verdict_schedules_with_no_note( tmp_path ):
    r, ask, sched = _run( tmp_path, lambda within: PROCEED )
    assert r.status == "scheduled"
    assert sched.calls == 1 and ask.calls == 1
    assert not any( "Last Call" in w for w in r.warnings )


def test_unknown_verdict_schedules_with_a_note_naming_the_unread_row( tmp_path ):
    r, ask, sched = _run( tmp_path, lambda within: UNKNOWN )
    assert r.status == "scheduled"
    assert sched.calls == 1
    notes = [ w for w in r.warnings if "Last Call check could not look" in w ]
    assert len( notes ) == 1 and "abc12345" in notes[ 0 ]
    assert r.reason.startswith( "NOTE: the Last Call check could not look" )


def test_raising_check_is_unknown_not_a_crash( tmp_path ):
    def boom( within ): raise OSError( "store on fire" )
    r, ask, sched = _run( tmp_path, boom )
    assert r.status == "scheduled"
    assert sched.calls == 1
    assert any( "OSError: store on fire" in w for w in r.warnings )


def test_the_check_is_asked_for_the_sixty_minute_window( tmp_path ):
    spy = _Spy( PROCEED )
    _run( tmp_path, spy )
    assert spy.args == [ ( 60, ) ]


@pytest.mark.parametrize( "answer", [ None, [ "skip" ], { "verdict": "maybe" }, { } ] )
def test_a_malformed_answer_is_unknown( answer ):
    verdict, result = sr.last_call_verdict( lambda within: answer )
    assert verdict == "unknown"
    assert "error" in result


def test_skip_beats_a_declined_ask_ordering( tmp_path ):
    """The guard fires before the ask: a skip never reaches the human."""
    ask = _Spy( "no" )
    r, ask, _ = _run( tmp_path, lambda within: SKIP, ask=ask )
    assert r.status == "aborted" and ask.calls == 0


# ---- the default seam: subprocess to last_call_window.py --------------------------------
def _completed( code, out ):
    return subprocess.CompletedProcess( [ ], code, stdout=out, stderr="err text" )


def test_default_check_runs_the_script_from_the_env_root( monkeypatch ):
    monkeypatch.setenv( "PLANNING_IS_PROMPTING_ROOT", "/pip" )
    seen = { }
    def fake_run( argv, **kw ):
        seen[ "argv" ], seen[ "kw" ] = argv, kw
        return _completed( 0, json.dumps( SKIP ) )
    monkeypatch.setattr( sr.subprocess, "run", fake_run )
    assert sr._default_last_call_check( 60 ) == SKIP
    assert seen[ "argv" ][ 1: ] == [ "/pip/workflow/scripts/last_call_window.py", "check", "--within", "60", "--json" ]
    assert seen[ "kw" ][ "timeout" ] == sr.LAST_CALL_CHECK_TIMEOUT_SECONDS


def test_default_check_raises_when_root_unset( monkeypatch ):
    monkeypatch.delenv( "PLANNING_IS_PROMPTING_ROOT", raising=False )
    with pytest.raises( RuntimeError, match="not set" ):
        sr._default_last_call_check( 60 )
    verdict, _ = sr.last_call_verdict( sr._default_last_call_check )
    assert verdict == "unknown"


def test_default_check_raises_on_an_exit_code_outside_the_contract( monkeypatch ):
    monkeypatch.setenv( "PLANNING_IS_PROMPTING_ROOT", "/pip" )
    monkeypatch.setattr( sr.subprocess, "run", lambda argv, **kw: _completed( 3, "" ) )
    with pytest.raises( RuntimeError, match="exited 3" ):
        sr._default_last_call_check( 60 )


def test_default_check_against_the_real_script_and_an_empty_schedule_dir( monkeypatch, tmp_path ):
    """Real producer, real reader: the conftest's empty LAST_CALL_STATE_DIR ⇒ 'proceed'."""
    import os
    if not os.environ.get( "PLANNING_IS_PROMPTING_ROOT" ): pytest.skip( "PLANNING_IS_PROMPTING_ROOT unset" )
    monkeypatch.setenv( "LAST_CALL_STATE_DIR", str( tmp_path / "empty" ) )
    assert sr._default_last_call_check( 60 )[ "verdict" ] == "proceed"
