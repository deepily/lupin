#!/usr/bin/env python3
"""
Guards for `lupin_mcp.fleet_cap_admission` — the fleet cap enforced in the LAUNCHER.

🔴 WHAT THESE TESTS ARE FOR, AND IT IS NOT COVERAGE. The defect this module answers is
that the cap's enforcement code is frozen at seat boot, so the fleet exceeded a cap of 8
by 4 on 2026-09-04 with the enforcing code sitting in the checkout. The property that
matters is therefore BEHAVIOURAL: a launch over cap must be refused, a launch under it
must be admitted, and two simultaneous launches must not both take the last seat.

⚠️ EVERY FIXTURE HERE HONOURS ITS INPUT. A fake census that returned the same list
whatever the caller asked would make each assertion below true by construction — the
defect this repo has measured repeatedly, where a suite at 100% reports on its own
harness. The census fakes read a mutable list the test owns, and the bridge lookup reads
a set the test owns, so a wrong decision produces a DIFFERENT observation.
"""
import json
import os
import sys
from pathlib import Path

import pytest

from lupin_mcp import fleet_cap_admission as fca


# ── helpers ──────────────────────────────────────────────────────────────────────────

def _census_of( n ):
    """A census fake returning n live sessions — honours n at CALL time."""
    return lambda: [ ( f"/bridge/{i}", f"sid{i}", {} ) for i in range( n ) ]


def _no_bridges( _name ):
    """Nothing has materialised yet."""
    return None


def _write_reservation( directory, name, ts, **extra ):
    directory.mkdir( parents=True, exist_ok=True )
    record = { "session_name": name, "reserved_ts": ts }
    record.update( extra )
    path = directory / f"{name}.json"
    with open( path, "w" ) as handle:
        json.dump( record, handle )
    return path


def _admit( tmp_path, *, name="cc-worker-1", headless=True, cap=8, live=0,
            bridges=None, now=1000.0, ttl=fca.DEFAULT_RESERVATION_TTL_SECONDS ):
    bridges = bridges or set()
    return fca.admit(
        name,
        headless      = headless,
        cap_fn        = lambda: cap,
        census_fn     = _census_of( live ),
        bridge_lookup = lambda n: n in bridges,
        directory     = tmp_path / fca.RESERVATION_SUBDIR,
        now_fn        = lambda: now,
        ttl_seconds   = ttl,
    )


# ── reservation_dir ──────────────────────────────────────────────────────────────────

def test_reservation_dir_sits_under_the_sessions_directory():
    got = fca.reservation_dir( sessions_dir_fn=lambda: Path( "/tmp/seats" ) )
    assert got == Path( "/tmp/seats" ) / fca.RESERVATION_SUBDIR


def test_reservation_dir_resolves_the_sessions_dir_at_call_time( monkeypatch, tmp_path ):
    """The LUPIN_HOOK_SESSIONS_DIR seam must be honoured however this module imported."""
    monkeypatch.setenv( "LUPIN_HOOK_SESSIONS_DIR", str( tmp_path ) )
    assert fca.reservation_dir() == tmp_path / fca.RESERVATION_SUBDIR


def test_reservation_dir_does_not_create_the_directory( tmp_path ):
    got = fca.reservation_dir( sessions_dir_fn=lambda: tmp_path )
    assert not got.exists()


# ── read_reservations ────────────────────────────────────────────────────────────────

def test_read_reservations_is_empty_for_an_absent_directory( tmp_path ):
    assert fca.read_reservations( tmp_path / "nope" ) == []


def test_read_reservations_returns_what_was_written( tmp_path ):
    _write_reservation( tmp_path, "cc-a", 10.0 )
    got = fca.read_reservations( tmp_path )
    assert [ e[ "session_name" ] for e in got ] == [ "cc-a" ]
    assert got[ 0 ][ "_path" ].endswith( "cc-a.json" )


def test_read_reservations_skips_a_file_that_does_not_parse( tmp_path ):
    _write_reservation( tmp_path, "cc-good", 10.0 )
    ( tmp_path / "broken.json" ).write_text( "{not json" )
    assert [ e[ "session_name" ] for e in fca.read_reservations( tmp_path ) ] == [ "cc-good" ]


def test_read_reservations_skips_a_record_without_a_session_name( tmp_path ):
    tmp_path.mkdir( parents=True, exist_ok=True )
    ( tmp_path / "headless.json" ).write_text( json.dumps( { "reserved_ts": 1.0 } ) )
    ( tmp_path / "alist.json"   ).write_text( json.dumps( [ 1, 2, 3 ] ) )
    assert fca.read_reservations( tmp_path ) == []


def test_read_reservations_skips_a_file_it_cannot_open( tmp_path, monkeypatch ):
    _write_reservation( tmp_path, "cc-a", 10.0 )

    def _boom( *args, **kwargs ):
        raise OSError( "permission denied" )

    monkeypatch.setattr( "builtins.open", _boom )
    assert fca.read_reservations( tmp_path ) == []


# ── unmaterialised_reservations ──────────────────────────────────────────────────────

def test_a_fresh_unmaterialised_reservation_holds_its_seat():
    entries = [ { "session_name": "cc-a", "reserved_ts": 100.0 } ]
    got = fca.unmaterialised_reservations( entries, _no_bridges, now=110.0, ttl_seconds=120 )
    assert len( got ) == 1


def test_a_reservation_whose_bridge_appeared_stops_holding_a_seat():
    """THE MECHANISM: materialisation, not the clock, is what retires a reservation."""
    entries = [ { "session_name": "cc-a", "reserved_ts": 100.0 } ]
    got = fca.unmaterialised_reservations( entries, lambda n: n == "cc-a",
                                           now=110.0, ttl_seconds=120 )
    assert got == []


def test_an_expired_reservation_stops_holding_a_seat():
    entries = [ { "session_name": "cc-a", "reserved_ts": 100.0 } ]
    got = fca.unmaterialised_reservations( entries, _no_bridges, now=1000.0, ttl_seconds=120 )
    assert got == []


def test_an_undateable_reservation_is_treated_as_expired():
    """A seat held by a record we cannot date would be a seat held forever."""
    for bad in ( None, "not-a-number", {} ):
        entries = [ { "session_name": "cc-a", "reserved_ts": bad } ]
        assert fca.unmaterialised_reservations( entries, _no_bridges, now=110.0 ) == []


def test_a_bridge_lookup_that_raises_keeps_the_seat():
    """Unknown is not evidence the seat is free — the conservative direction."""
    def _boom( _name ):
        raise RuntimeError( "bridge scan failed" )

    entries = [ { "session_name": "cc-a", "reserved_ts": 100.0 } ]
    got = fca.unmaterialised_reservations( entries, _boom, now=110.0, ttl_seconds=120 )
    assert len( got ) == 1


# ── prune ────────────────────────────────────────────────────────────────────────────

def test_prune_is_a_noop_on_an_absent_directory( tmp_path ):
    assert fca.prune( tmp_path / "nope", [] ) == 0


def test_prune_removes_only_what_is_not_kept( tmp_path ):
    _write_reservation( tmp_path, "cc-keep", 1.0 )
    _write_reservation( tmp_path, "cc-drop", 1.0 )
    keep = [ e for e in fca.read_reservations( tmp_path ) if e[ "session_name" ] == "cc-keep" ]
    assert fca.prune( tmp_path, keep ) == 1
    assert [ p.name for p in tmp_path.glob( "*.json" ) ] == [ "cc-keep.json" ]


def test_prune_survives_a_file_it_cannot_remove( tmp_path, monkeypatch ):
    _write_reservation( tmp_path, "cc-drop", 1.0 )

    def _boom( self ):
        raise OSError( "read-only" )

    monkeypatch.setattr( Path, "unlink", _boom )
    assert fca.prune( tmp_path, [] ) == 0


# ── admit: the decision ──────────────────────────────────────────────────────────────

def test_a_launch_under_the_cap_is_admitted( tmp_path ):
    verdict = _admit( tmp_path, cap=8, live=7 )
    assert verdict[ "admitted" ] is True
    assert verdict[ "reason" ] is None
    assert ( verdict[ "cap" ], verdict[ "live" ], verdict[ "occupancy" ] ) == ( 8, 7, 7 )


def test_the_launch_that_would_exceed_the_cap_is_refused( tmp_path ):
    verdict = _admit( tmp_path, cap=8, live=8 )
    assert verdict[ "admitted" ] is False
    assert "FLEET CAP REFUSED THIS LAUNCH" in verdict[ "reason" ]


def test_the_boundary_is_occupancy_plus_one( tmp_path ):
    """The 8th seat is admitted; the 9th is not. Off-by-one is the whole failure mode."""
    assert _admit( tmp_path, cap=8, live=7, name="cc-8th" )[ "admitted" ] is True
    assert _admit( tmp_path, cap=8, live=8, name="cc-9th" )[ "admitted" ] is False


def test_the_refusal_names_every_number_a_caller_needs( tmp_path ):
    _write_reservation( tmp_path / fca.RESERVATION_SUBDIR, "cc-inflight", 1000.0 )
    verdict = _admit( tmp_path, cap=8, live=7, now=1000.0 )
    reason  = verdict[ "reason" ]
    assert "the cap is 8"        in reason
    assert "occupies 8 seat(s)"  in reason
    assert "7 live session(s)"   in reason
    assert "1 launch(es)"        in reason
    assert "0 seat(s) free"      in reason


def test_the_refusal_says_nothing_was_terminated( tmp_path ):
    """Rick's ruling: over cap REFUSES the new spawn and REAPS NOBODY."""
    verdict = _admit( tmp_path, cap=1, live=5 )
    assert "Nothing was terminated" in verdict[ "reason" ]


def test_an_in_flight_reservation_occupies_a_seat( tmp_path ):
    """THE RACE THIS MODULE EXISTS FOR: a launched child with no bridge yet still counts."""
    _write_reservation( tmp_path / fca.RESERVATION_SUBDIR, "cc-inflight", 1000.0 )
    verdict = _admit( tmp_path, cap=8, live=7, now=1000.0 )
    assert verdict[ "reserved" ]  == 1
    assert verdict[ "occupancy" ] == 8
    assert verdict[ "admitted" ]  is False


def test_a_reservation_that_became_a_session_is_not_counted_twice( tmp_path ):
    """Its bridge exists, so the census already counts it. Counting both would over-refuse."""
    _write_reservation( tmp_path / fca.RESERVATION_SUBDIR, "cc-arrived", 1000.0 )
    verdict = _admit( tmp_path, cap=8, live=7, now=1000.0, bridges={ "cc-arrived" } )
    assert verdict[ "reserved" ]  == 0
    assert verdict[ "occupancy" ] == 7
    assert verdict[ "admitted" ]  is True


def test_admission_writes_a_reservation_the_next_caller_can_see( tmp_path ):
    directory = tmp_path / fca.RESERVATION_SUBDIR
    _admit( tmp_path, name="cc-first", cap=8, live=6, now=1000.0 )
    assert [ e[ "session_name" ] for e in fca.read_reservations( directory ) ] == [ "cc-first" ]

    second = _admit( tmp_path, name="cc-second", cap=8, live=6, now=1000.0 )
    assert second[ "reserved" ]  == 1
    assert second[ "occupancy" ] == 7


def test_a_refusal_writes_nothing( tmp_path ):
    directory = tmp_path / fca.RESERVATION_SUBDIR
    _admit( tmp_path, name="cc-refused", cap=1, live=5 )
    assert fca.read_reservations( directory ) == []


def test_the_reservation_record_carries_its_identity( tmp_path ):
    directory = tmp_path / fca.RESERVATION_SUBDIR
    _admit( tmp_path, name="cc-rec", cap=8, live=0, now=4242.0, headless=True )
    record = fca.read_reservations( directory )[ 0 ]
    assert record[ "session_name" ] == "cc-rec"
    assert record[ "reserved_ts" ]  == 4242.0
    assert record[ "headless" ]     is True
    assert record[ "pid" ]          == os.getpid()


def test_admit_prunes_expired_reservations_from_disk( tmp_path ):
    """The store cannot grow without bound, and a dead launch cannot hold a seat forever."""
    directory = tmp_path / fca.RESERVATION_SUBDIR
    _write_reservation( directory, "cc-stale", 1.0 )
    _admit( tmp_path, name="cc-new", cap=8, live=0, now=10_000.0 )
    names = { e[ "session_name" ] for e in fca.read_reservations( directory ) }
    assert names == { "cc-new" }


def test_a_session_name_with_path_characters_cannot_escape_the_directory( tmp_path ):
    directory = tmp_path / fca.RESERVATION_SUBDIR
    _admit( tmp_path, name="../../evil name", cap=8, live=0 )
    written = list( directory.glob( "*.json" ) )
    assert len( written ) == 1
    assert written[ 0 ].parent == directory
    assert ".." not in written[ 0 ].name


def test_a_reservation_that_cannot_be_written_is_reported_not_swallowed( tmp_path, monkeypatch ):
    """A clean-looking admission whose reservation vanished is the failure shape we refuse."""
    real_open = open

    def _boom( path, *args, **kwargs ):
        if str( path ).endswith( ".json" ) and "w" in ( args[ 0 ] if args else kwargs.get( "mode", "r" ) ):
            raise OSError( "disk full" )
        return real_open( path, *args, **kwargs )

    monkeypatch.setattr( "builtins.open", _boom )
    verdict = _admit( tmp_path, cap=8, live=0 )
    assert verdict[ "admitted" ] is True
    assert "disk full" in verdict[ "reservation_error" ]


# ── release ──────────────────────────────────────────────────────────────────────────

def test_release_drops_a_reservation( tmp_path ):
    directory = tmp_path / fca.RESERVATION_SUBDIR
    _admit( tmp_path, name="cc-dead", cap=8, live=0 )
    assert fca.release( "cc-dead", directory ) is True
    assert fca.read_reservations( directory ) == []


def test_release_of_something_absent_is_false_not_an_error( tmp_path ):
    assert fca.release( "cc-never", tmp_path / fca.RESERVATION_SUBDIR ) is False


# ── admit_under_lock ─────────────────────────────────────────────────────────────────

def test_admit_under_lock_returns_the_same_verdict_as_admit( tmp_path ):
    verdict = fca.admit_under_lock(
        "cc-locked", headless=True, cap_fn=lambda: 8, census_fn=_census_of( 2 ),
        bridge_lookup=_no_bridges, directory=tmp_path / fca.RESERVATION_SUBDIR,
        now_fn=lambda: 1000.0 )
    assert verdict[ "admitted" ] is True
    assert "lock_error" not in verdict


def test_two_sequential_admissions_under_the_lock_cannot_both_take_the_last_seat( tmp_path ):
    """The reservation is what makes the SECOND caller see the FIRST one's seat."""
    directory = tmp_path / fca.RESERVATION_SUBDIR
    common    = dict( headless=True, cap_fn=lambda: 8, census_fn=_census_of( 7 ),
                      bridge_lookup=_no_bridges, directory=directory, now_fn=lambda: 1000.0 )
    first  = fca.admit_under_lock( "cc-a", **common )
    second = fca.admit_under_lock( "cc-b", **common )
    assert first[ "admitted" ]  is True
    assert second[ "admitted" ] is False


def test_the_lock_is_released_even_when_the_decision_raises( tmp_path ):
    """A held lock would wedge every later launch on this box."""
    directory = tmp_path / fca.RESERVATION_SUBDIR

    def _boom():
        raise RuntimeError( "census exploded" )

    with pytest.raises( RuntimeError ):
        fca.admit_under_lock( "cc-x", headless=True, cap_fn=lambda: 8, census_fn=_boom,
                              bridge_lookup=_no_bridges, directory=directory )

    # If the lock had leaked, this second call would block forever rather than return.
    verdict = fca.admit_under_lock( "cc-y", headless=True, cap_fn=lambda: 8,
                                    census_fn=_census_of( 0 ), bridge_lookup=_no_bridges,
                                    directory=directory )
    assert verdict[ "admitted" ] is True


def _admit_locked( tmp_path, name="cc-z" ):
    return fca.admit_under_lock( name, headless=True, cap_fn=lambda: 8,
                                 census_fn=_census_of( 0 ), bridge_lookup=_no_bridges,
                                 directory=tmp_path / fca.RESERVATION_SUBDIR )


def test_a_lock_that_cannot_be_taken_does_not_block_the_launch( tmp_path, monkeypatch ):
    """Fail-open: a resource limit must not take the fleet down over a lock error."""
    monkeypatch.setattr( fca.fcntl, "flock",
                         lambda *a, **k: ( _ for _ in () ).throw( OSError( "no flock here" ) ) )
    verdict = _admit_locked( tmp_path )
    assert verdict[ "admitted" ]  is True
    assert "no flock here" in verdict[ "lock_error" ]


def test_a_lock_file_that_cannot_even_be_opened_does_not_block_the_launch( tmp_path, monkeypatch ):
    """The lock FILE failing is a different branch from the flock CALL failing."""
    real_open = open

    def _boom( path, *args, **kwargs ):
        if str( path ).endswith( fca.LOCK_FILENAME ):
            raise OSError( "cannot create lock file" )
        return real_open( path, *args, **kwargs )

    monkeypatch.setattr( "builtins.open", _boom )
    verdict = _admit_locked( tmp_path )
    assert verdict[ "admitted" ]  is True
    assert "cannot create lock file" in verdict[ "lock_error" ]


def test_a_lock_handle_that_will_not_close_does_not_block_the_launch( tmp_path, monkeypatch ):
    """Cleanup failing after a lock error must not turn fail-open into a raise."""
    real_open = open

    class _Unclosable:
        def __init__( self, wrapped ): self._wrapped = wrapped
        def fileno( self ): return self._wrapped.fileno()
        def close( self ): raise OSError( "close refused" )

    def _wrap( path, *args, **kwargs ):
        handle = real_open( path, *args, **kwargs )
        return _Unclosable( handle ) if str( path ).endswith( fca.LOCK_FILENAME ) else handle

    monkeypatch.setattr( "builtins.open", _wrap )
    monkeypatch.setattr( fca.fcntl, "flock",
                         lambda *a, **k: ( _ for _ in () ).throw( OSError( "no flock here" ) ) )
    verdict = _admit_locked( tmp_path )
    assert verdict[ "admitted" ] is True


def test_an_unlock_that_fails_does_not_lose_the_verdict( tmp_path, monkeypatch ):
    """The decision was already taken; a cleanup error must not swallow it."""
    calls = { "n": 0 }

    def _flock( fd, op ):
        calls[ "n" ] += 1
        if op == fca.fcntl.LOCK_UN:
            raise OSError( "unlock refused" )

    monkeypatch.setattr( fca.fcntl, "flock", _flock )
    verdict = _admit_locked( tmp_path )
    assert verdict[ "admitted" ] is True
    assert "lock_error" not in verdict


# ── main: the exit codes the launcher reads ──────────────────────────────────────────

class _Capture:
    def __init__( self ): self.text = ""
    def write( self, chunk ): self.text += chunk


def _main( argv, verdict=None, raises=None, tmp_path=None, release_calls=None ):
    err = _Capture()

    def _admit_fn( name, **kwargs ):
        if raises is not None:
            raise raises
        return verdict

    def _release_fn( name, directory ):
        if release_calls is not None:
            release_calls.append( name )

    code = fca.main( argv, admit_fn=_admit_fn, release_fn=_release_fn,
                     dir_fn=lambda: ( tmp_path or Path( "/tmp" ) ), stderr=err )
    return code, err.text


def test_main_exits_zero_when_admitted( tmp_path ):
    code, err = _main( [ "--session-name", "cc-a", "--headless" ],
                       verdict={ "admitted": True }, tmp_path=tmp_path )
    assert code == fca.EXIT_ADMITTED
    assert err == ""


def test_main_refuses_a_headless_launch_over_cap( tmp_path ):
    code, err = _main( [ "--session-name", "cc-a", "--headless" ],
                       verdict={ "admitted": False, "reason": "no room" }, tmp_path=tmp_path )
    assert code == fca.EXIT_REFUSED
    assert "REFUSING TO LAUNCH" in err
    assert "no room" in err


def test_main_allows_an_interactive_launch_over_cap_but_says_so( tmp_path ):
    """A cap that locks the operator out of his own terminal cannot be undone from inside it."""
    code, err = _main( [ "--session-name", "cc-a" ],
                       verdict={ "admitted": False, "reason": "no room" }, tmp_path=tmp_path )
    assert code == fca.EXIT_ADMITTED
    assert "OVER CAP" in err
    assert "INTERACTIVE" in err
    assert "no room" in err


def test_main_fails_open_and_says_why( tmp_path ):
    code, err = _main( [ "--session-name", "cc-a", "--headless" ],
                       raises=RuntimeError( "bridges unreadable" ), tmp_path=tmp_path )
    assert code == fca.EXIT_ADMITTED
    assert "ALLOWING the launch" in err
    assert "bridges unreadable" in err


def test_main_release_drops_the_reservation_and_exits_zero( tmp_path ):
    calls = []
    code, err = _main( [ "--session-name", "cc-a", "--release" ],
                       tmp_path=tmp_path, release_calls=calls )
    assert code  == fca.EXIT_ADMITTED
    assert calls == [ "cc-a" ]


def test_main_requires_a_session_name():
    with pytest.raises( SystemExit ):
        fca.main( [ "--headless" ], stderr=_Capture() )


# ── the live wiring: it delegates, it does not hold a second policy ──────────────────

def test_live_cap_delegates_to_fleet_size_cap( monkeypatch ):
    from lupin_mcp import fleet_size_cap
    seen = {}

    def _resolve( config_mgr, disk_fn=None ):
        seen[ "disk_fn" ] = disk_fn
        return 11

    monkeypatch.setattr( fleet_size_cap, "resolve_fleet_cap", _resolve )
    assert fca._live_cap() == 11
    assert seen[ "disk_fn" ] is fleet_size_cap.default_disk_cap_reader


def test_live_cap_survives_an_unreadable_configuration_manager( monkeypatch ):
    from lupin_mcp import fleet_size_cap
    import cosa.config.configuration_manager as cm

    monkeypatch.setattr( cm, "ConfigurationManager",
                         lambda *a, **k: ( _ for _ in () ).throw( RuntimeError( "no ini" ) ) )
    monkeypatch.setattr( fleet_size_cap, "resolve_fleet_cap",
                         lambda config_mgr, disk_fn=None: 7 if config_mgr is None else 99 )
    assert fca._live_cap() == 7


def test_live_census_counts_persona_less_seats_too( monkeypatch ):
    """
    The MCP gate's census filters to seats that HAVE a persona; this one must not.
    A live seat whose allocation failed still occupies a seat.
    """
    import lupin_cli.claude_code.hooks.lib.session_bridge as sb
    seen = {}

    def _find( require_persona=True, **kwargs ):
        seen[ "require_persona" ] = require_persona
        return [ ( "/b/1", "sid1", {} ) ]

    monkeypatch.setattr( sb, "find_active_sessions", _find )
    assert len( fca._live_census() ) == 1
    assert seen[ "require_persona" ] is False


def test_live_bridge_lookup_asks_by_tmux_session_name( monkeypatch ):
    import lupin_cli.claude_code.hooks.lib.session_bridge as sb
    monkeypatch.setattr( sb, "find_session_by_tmux",
                         lambda name: { "found": name } )
    assert fca._live_bridge_lookup( "cc-a" ) == { "found": "cc-a" }


# ── THE WIRING: a guard the launcher never calls cannot refuse anything ──────────────
#
# 🔴 WHY THESE EXIST. Every test above passes whether or not `start-cc-with-tmux.sh` ever
# invokes this module. That is the "implemented but not installed" shape: the component is
# complete, correct, fully covered, and absent from the running system. Unwire the call
# site and the module stays at 100% while the fleet overruns exactly as it did on
# 2026-09-04. These read the ASSEMBLED launcher, not the class.

def _launcher_text():
    root = Path( os.environ.get( "LUPIN_ROOT", "" ) or Path( __file__ ).resolve().parents[ 3 ] )
    path = root / "src" / "scripts" / "start-cc-with-tmux.sh"
    assert path.exists(), f"launcher not found at {path}"
    return path.read_text()


def test_the_launcher_actually_invokes_this_guard():
    text = _launcher_text()
    assert "lupin_mcp.fleet_cap_admission" in text
    assert "--session-name" in text


def test_the_guard_runs_before_the_tmux_session_is_created():
    """A cap checked AFTER the launch is a cap that records the overrun."""
    text  = _launcher_text()
    guard = text.index( "python3 -m lupin_mcp.fleet_cap_admission" )
    birth = text.index( "tmux new-session -s " )
    assert guard < birth, "the fleet-cap guard must run BEFORE the session is created"


def test_the_guard_invocation_survives_set_e():
    """
    MEASURED DEFECT, 2026-09-05. Written as a bare call plus `if [[ $? -eq 3 ]]`, the
    first real run exited 3 and the `if` never executed — `set -e` had already aborted
    the script. The refusal still happened, so the arm LOOKED like a pass while the
    branch meant to distinguish a refusal from a crash was dead. Under `set -e` any
    non-zero exit kills the launch, which turns a fail-OPEN guard into one that fails
    closed for the whole fleet on an argparse error.
    """
    text = _launcher_text()
    assert "set -euo pipefail" in text, "this guard assumes the launcher runs under set -e"
    call = text[ text.index( "python3 -m lupin_mcp.fleet_cap_admission" ) : ]
    call = call[ : call.index( "\nif [[" ) ]
    assert "|| _fleet_rc=$?" in call, "the guard call must capture its own exit code"


def test_only_exit_three_refuses_the_launch():
    """Every other non-zero exit must ALLOW — a resource limit must not fail closed."""
    text = _launcher_text()
    block = text[ text.index( '_fleet_rc=$?' ) : ]
    block = block[ : block.index( "# Check if session already exists" ) ]
    assert '[[ "$_fleet_rc" -eq 3 ]]' in block
    assert '-ne 0 ]]' in block and "ALLOWING the launch" in block


def test_a_reserved_seat_is_handed_back_when_no_session_is_created():
    """
    Three non-launch paths follow the reservation: an existing tmux session, a bad
    --work-dir, and a failed `tmux new-session`. Each must release, or the seat is held
    against the next spawn for the whole TTL.
    """
    text = _launcher_text()
    assert "_release_fleet_seat() {" in text
    after = text[ text.index( "_release_fleet_seat() {" ) : ]
    assert after.count( "_release_fleet_seat\n" ) >= 3, \
        "every path that reserves a seat and then does not launch must release it"
