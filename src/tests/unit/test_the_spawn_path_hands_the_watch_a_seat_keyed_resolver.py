"""
The LIVE spawn path must hand the wake watch a resolver, and that resolver must
key on the spawned seat's own repo.

⚠️ WHY THIS FILE EXISTS. `test_wake_watch_reads_the_seats_own_repo.py` enters at
`arm_watches_for_spawn` with a resolver INJECTED BY THE TEST. That proves the
watch forwards a base_dir it is given; it says nothing about whether anything in
the application ever gives it one. Measured: delete the wiring line
`base_dir_for = _data_root_of_spawn_record`, or break the resolver's own record
lookup, and all 118 tests across the two existing files stay green while the
original defect is live again.

⇒ Every arm here enters at `_arm_respin_wake_watch`, which is the layer the live
re-spin actually goes through. CLAUDE.md § A TEST THAT ENTERS BELOW THE LAYER THE
INCIDENT ENTERED AT CANNOT SPEAK TO THE INCIDENT.
"""
from lupin_cli.claude_code.hooks.lib.heartbeat_hold import fleet_data_root
from lupin_mcp.session_spawner import _resolve_project_root
import cosa.agents.heartbeat_arbiter.respin_wake_check as rwc
import lupin_mcp.cosa_voice_mcp as mcp_mod


def _record( project ):
    return { "session_name": "cc-seat-1", "status": "spawned", "project": project }


def _armed( monkeypatch ):
    """Drive the real wiring and hand back the kwargs it passed the watch."""
    seen = {}
    monkeypatch.setattr( rwc, "arm_watches_for_spawn", lambda spawn_result, **kw: seen.update( kw ) )
    mcp_mod._arm_respin_wake_watch( { "spawned": [ _record( "lupin" ) ] }, "mr radio", "T0" )
    return seen


def test_the_spawn_path_resolves_a_cross_repo_seat_to_that_seats_own_root( monkeypatch ):
    resolver = _armed( monkeypatch )[ "base_dir_for" ]
    expected = str( fleet_data_root( _resolve_project_root( "lupin-mobile" ) ) )
    assert resolver( _record( "lupin-mobile" ) ) == expected, \
        "the live spawn path did not hand the watch a resolver that reads the seat's own repo"


def test_the_same_repo_seat_still_lands_on_the_ambient_root( monkeypatch ):
    """NEGATIVE CONTROL. Without it the arm above is satisfied by a resolver that
    simply always answers something else."""
    resolver = _armed( monkeypatch )[ "base_dir_for" ]
    assert resolver( _record( "lupin" ) ) == str( fleet_data_root() )


def test_a_watch_that_will_not_arm_never_fails_the_spawn( monkeypatch ):
    def boom( *a, **kw ): raise RuntimeError( "arbiter unreachable" )
    monkeypatch.setattr( rwc, "arm_watches_for_spawn", boom )
    mcp_mod._arm_respin_wake_watch( { "spawned": [ _record( "lupin" ) ] }, "mr radio", "T0" )
