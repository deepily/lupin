#!/usr/bin/env python3
"""
Tests that the skeleton crew switch is enforced at both spawn gates.

Every seat is started through one of two gates. The early gate is `default_fleet_gate`, which
the spawn tool calls. The gate that binds is the launcher's admission command, which every
launch passes through whatever called it.

The early gate must refuse with the switch on, even when the cap has room. The launcher must
refuse on every launch that is not a person at a terminal. A launch from the operator's own
terminal stays allowed. A manager's shell has no terminal, so dropping the headless flag does
not get a manager through.

These tests drive the real gate and the real launcher entry point, one level below their
injection seams, so the policy itself runs.

Every test reads a file in tmp_path or an injected manager. The live file is never touched.
"""
import os
import subprocess
import sys

import pytest

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from lupin_mcp import fleet_cap_admission as fca
from lupin_mcp import fleet_size_cap as fsc
from lupin_mcp import session_spawner as ss
from lupin_mcp import skeleton_crew as sc


SPAWN_TEXT  = sc.refusal_text( "spawn" )
LAUNCH_TEXT = sc.refusal_text( "launch" )


class _Config:
    def __init__( self, **values ):
        self._values = { fsc.FLEET_CAP_KEY: 15, fsc.FLEET_CEILING_KEY: 18, sc.SKELETON_CREW_KEY: False }
        self._values.update( { k.replace( "_", " " ): v for k, v in values.items() } )

    def with_switch( self, on ):
        self._values[ sc.SKELETON_CREW_KEY ] = on
        return self

    def get( self, key, default=None, return_type=None, silent=False ):
        return self._values.get( key, default )


def _on():
    return _Config().with_switch( True )


def _off():
    return _Config().with_switch( False )


# ── the early gate ───────────────────────────────────────────────────────────

def test_the_early_gate_refuses_with_the_switch_on_even_when_the_cap_has_room():
    refusal = ss.default_fleet_gate( 1, config_fn=_on, census_fn=lambda: [] )
    assert refusal == SPAWN_TEXT


def test_the_early_gate_allows_with_the_switch_off_and_room():
    assert ss.default_fleet_gate( 1, config_fn=_off, census_fn=lambda: [] ) is None


def test_the_switch_answers_before_the_cap_when_both_would_refuse():
    sessions = [ ( f"/tmp/b{i}.json", f"s{i}", f"p{i}" ) for i in range( 20 ) ]
    refusal  = ss.default_fleet_gate( 1, config_fn=_on, census_fn=lambda: sessions )
    assert refusal == SPAWN_TEXT


def test_with_the_switch_off_the_cap_still_refuses_a_full_fleet():
    sessions = [ ( f"/tmp/b{i}.json", f"s{i}", f"p{i}" ) for i in range( 15 ) ]
    refusal  = ss.default_fleet_gate( 1, config_fn=_off, census_fn=lambda: sessions )
    assert refusal is not None and "FLEET CAP REFUSED" in refusal


def test_the_default_source_reads_the_file_fresh( tmp_path, monkeypatch ):
    path = tmp_path / "switch.ini"
    path.write_text( f"[Lupin: Baseline]\n{sc.SKELETON_CREW_KEY} = true\n", encoding="utf-8" )
    monkeypatch.setenv( sc.INI_OVERRIDE_ENV, str( path ) )
    assert ss.default_fleet_gate( 1, census_fn=lambda: [] ) == SPAWN_TEXT
    path.write_text( f"[Lupin: Baseline]\n{sc.SKELETON_CREW_KEY} = false\n", encoding="utf-8" )
    assert ss.default_fleet_gate( 1, census_fn=lambda: [] ) is None


def test_an_injected_configuration_is_not_outvoted_by_the_live_file( tmp_path, monkeypatch ):
    path = tmp_path / "switch.ini"
    path.write_text( f"[Lupin: Baseline]\n{sc.SKELETON_CREW_KEY} = true\n", encoding="utf-8" )
    monkeypatch.setenv( sc.INI_OVERRIDE_ENV, str( path ) )
    assert ss.default_fleet_gate( 1, config_fn=_off, census_fn=lambda: [] ) is None


def test_the_spawn_tool_raises_the_refusal_and_starts_nothing( tmp_path ):
    started = []
    def runner( argv, env=None ):
        started.append( argv )
    with pytest.raises( ValueError ) as raised:
        ss.spawn_sessions(
            1, "brief", "mgr", script_path="/nonexistent", runner=runner, session_dir=tmp_path,
            fleet_config_fn=_on, fleet_census_fn=lambda: [] )
    assert str( raised.value ) == SPAWN_TEXT
    assert started == []


# ── the launcher ─────────────────────────────────────────────────────────────

class _Capture:
    def __init__( self ): self.text = ""
    def write( self, chunk ): self.text += chunk


def _main( argv, skeleton, tty, environ, admitted=True ):
    err    = _Capture()
    calls  = []

    def admit_fn( name, **kwargs ):
        calls.append( name )
        return { "admitted": admitted, "reason": "no room" }

    code = fca.main(
        argv,
        admit_fn          = admit_fn,
        release_fn        = lambda name, directory: calls.append( ( "release", name ) ),
        dir_fn            = lambda: "/tmp",
        stderr            = err,
        skeleton_fn       = skeleton,
        stdin_is_tty_fn   = lambda: tty,
        environ           = environ )
    return code, err.text, calls


def test_a_headless_launch_is_refused_with_the_switch_on():
    code, err, calls = _main( [ "--session-name", "cc-a", "--headless" ], lambda: LAUNCH_TEXT, True, {} )
    assert code == fca.EXIT_REFUSED
    assert LAUNCH_TEXT in err and "[SKELETON-CREW]" in err
    assert calls == []


def test_dropping_the_headless_flag_without_a_terminal_is_refused():
    code, err, calls = _main( [ "--session-name", "cc-a" ], lambda: LAUNCH_TEXT, False, {} )
    assert code == fca.EXIT_REFUSED
    assert LAUNCH_TEXT in err
    assert calls == []


@pytest.mark.parametrize( "marker", [ "CLAUDECODE", "COSA_VOICE_SPAWNED_BY" ] )
def test_an_agent_marker_in_the_environment_is_refused_even_with_a_terminal( marker ):
    code, err, calls = _main( [ "--session-name", "cc-a" ], lambda: LAUNCH_TEXT, True, { marker: "1" } )
    assert code == fca.EXIT_REFUSED
    assert calls == []


def test_a_person_at_a_terminal_is_not_refused():
    code, err, calls = _main( [ "--session-name", "cc-a" ], lambda: LAUNCH_TEXT, True, {} )
    assert code == fca.EXIT_ADMITTED
    assert calls == [ "cc-a" ]


def test_an_empty_marker_does_not_count():
    code, err, calls = _main( [ "--session-name", "cc-a" ], lambda: LAUNCH_TEXT, True, { "CLAUDECODE": "" } )
    assert code == fca.EXIT_ADMITTED


def test_with_the_switch_off_a_headless_launch_goes_on_to_the_cap():
    code, err, calls = _main( [ "--session-name", "cc-a", "--headless" ], lambda: None, False, {} )
    assert code == fca.EXIT_ADMITTED
    assert calls == [ "cc-a" ]


def test_release_is_never_refused_by_the_switch():
    code, err, calls = _main( [ "--session-name", "cc-a", "--release" ], lambda: LAUNCH_TEXT, False, {} )
    assert code == fca.EXIT_ADMITTED
    assert calls == [ ( "release", "cc-a" ) ]


def test_a_switch_check_that_raises_allows_the_launch_and_says_so():
    def boom():
        raise RuntimeError( "cannot read" )
    code, err, calls = _main( [ "--session-name", "cc-a", "--headless" ], boom, False, {} )
    assert code == fca.EXIT_ADMITTED
    assert "[SKELETON-CREW]" in err and "ALLOWING" in err
    assert calls == [ "cc-a" ]


def test_the_default_wiring_reads_the_file_and_the_real_streams( tmp_path, monkeypatch ):
    path = tmp_path / "switch.ini"
    path.write_text( f"[Lupin: Baseline]\n{sc.SKELETON_CREW_KEY} = true\n", encoding="utf-8" )
    monkeypatch.setenv( sc.INI_OVERRIDE_ENV, str( path ) )
    err  = _Capture()
    code = fca.main( [ "--session-name", "cc-a", "--headless" ], dir_fn=lambda: tmp_path / "res",
                     admit_fn=lambda name, **kw: { "admitted": True }, stderr=err )
    assert code == fca.EXIT_REFUSED
    assert LAUNCH_TEXT in err.text


def test_the_real_entry_point_refuses_a_launch_with_no_terminal( tmp_path ):
    path = tmp_path / "switch.ini"
    path.write_text( f"[Lupin: Baseline]\n{sc.SKELETON_CREW_KEY} = true\n", encoding="utf-8" )
    env = dict( os.environ )
    env[ sc.INI_OVERRIDE_ENV ] = str( path )
    env[ "PYTHONPATH" ]        = _src_path
    done = subprocess.run(
        [ sys.executable, "-m", "lupin_mcp.fleet_cap_admission", "--session-name", "cc-never-launched" ],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, env=env, timeout=60 )
    assert done.returncode == fca.EXIT_REFUSED
    assert LAUNCH_TEXT in done.stderr
