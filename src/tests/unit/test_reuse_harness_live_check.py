"""
Unit tests of the live check script.

The real CLI and docker never start here.
The ports are the real adapters over the simulators of the other harness tests.
The session is a stub that prints a real-shaped init event.
So each step of the script runs and none of it spends anything.
"""
import json
import os
import runpy
import sys

import pytest

from lupin_mcp.reuse_harness import arms
from lupin_mcp.reuse_harness import errors as err
from lupin_mcp.reuse_harness import live_check
from tests.unit.test_reuse_harness_driver import StubSession, repo, wire   # repo is a fixture, imported by name

SHOWN_TOOLS = [ "Bash", "Read", "mcp__cosa-voice__check_exists", "mcp__cosa-voice__fetch_similar", "mcp__cosa-voice__read_capability" ]


class LiveSession( StubSession ):
    """A session whose probes answer by the deny rules and leave a stream with an init event."""

    def __init__( self, leaky=False ):
        """Choose whether the arm without the tools wrongly reaches them."""
        super().__init__()
        self.leaky       = leaky
        self.last_output = None
        self.slice_calls = 0

    def probe( self, config, surface ):
        """Answer a call unless a deny rule names the surface, and keep a stream like the CLI's."""
        self.last_output = json.dumps( { "type" : "system", "subtype" : "init", "tools" : SHOWN_TOOLS, "skills" : [] } )
        return self.leaky or arms.DENY_RULES[ surface ] not in config[ "deny_rules" ]


def argv_of( repo, tmp_path, *extra ):
    """Return the command line of one live check."""
    return [ "--repo-root", str( repo[ "root" ] ), "--data-root", str( tmp_path / "data" ), "--frozen-sha", repo[ "commit" ], "--model-id", "claude-opus-5-5", *extra ]


def factory_of( repo, tmp_path, session_stub, seen=None, docker_after_stop=True ):
    """Return a ports factory over the simulators, remembering the ports it built."""
    def factory( spec, repo_root, data_root, image, mcp_config, environ ):
        ports, docker, databases, run_dir = wire( repo, spec, session_stub, tmp_path )
        docker.stats_needs_container = docker_after_stop
        if seen is not None: seen.append( ( spec, ports, docker, databases, mcp_config ) )
        return ports
    return factory


def test_without_execute_it_prints_the_plan_with_the_exact_command_and_starts_nothing( repo, tmp_path, capsys ):
    def factory( *args ): raise AssertionError( "a plan must not build ports" )
    code = live_check.main( argv_of( repo, tmp_path, "--mcp-config", "/cfg/m.json" ), factory=factory )
    text = capsys.readouterr().out
    assert code == 0 and text.startswith( "PLAN (nothing has been started):" )
    assert f"--frozen-sha {repo[ 'commit' ]} --model-id claude-opus-5-5 --mcp-config /cfg/m.json --execute" in text
    assert f"LUPIN_ROOT={repo[ 'root' ]} PYTHONPATH={repo[ 'root' ]}/src" in text and "8 short probe sessions" in text
    assert not ( tmp_path / "data" ).exists()


def test_the_plan_leaves_out_the_mcp_flag_when_none_is_given( repo, tmp_path, capsys ):
    live_check.main( argv_of( repo, tmp_path ) )
    assert "--mcp-config" not in capsys.readouterr().out


def test_execute_proves_both_arms_boots_a_server_and_writes_the_summary_and_init_events( repo, tmp_path, capsys ):
    seen = []
    code = live_check.main( argv_of( repo, tmp_path, "--execute", "--mcp-config", "/cfg/m.json" ), factory=factory_of( repo, tmp_path, LiveSession(), seen ) )
    out  = tmp_path / "data" / "live-check"
    summary = json.loads( ( out / live_check.SUMMARY_FILE ).read_text() )
    assert code == 0 and json.loads( capsys.readouterr().out ) == summary
    assert summary[ "arms" ] == { "with" : { surface : True for surface in arms.SURFACES }, "without" : { surface : False for surface in arms.SURFACES } }
    assert summary[ "boot" ] == { "url" : summary[ "boot" ][ "url" ], "fresh" : True, "sample" : { "mem_bytes" : int( 12.5 * 1024 ** 2 ), "cpu_percent" : 1.5 },
                                  "passing_tests" : 0, "total_tests" : 2, "client_builds" : True, "gone_after_stop" : True }
    assert sorted( path.name for path in out.iterdir() ) == sorted( [ live_check.SUMMARY_FILE, f"init-event-{arms.ARM_LABELS[ 'with' ]}.json", f"init-event-{arms.ARM_LABELS[ 'without' ]}.json" ] )
    assert json.loads( ( out / f"init-event-{arms.ARM_LABELS[ 'with' ]}.json" ).read_text() )[ "tools" ] == SHOWN_TOOLS
    assert [ spec[ "run_id" ] for spec, *_ in seen ] == list( live_check.RUN_IDS.values() ) and all( entry[ 4 ] == "/cfg/m.json" for entry in seen )
    assert all( entry[ 2 ].containers == set() and entry[ 3 ].dbs == {} for entry in seen )


def test_the_run_ids_do_not_name_the_arm():
    assert not any( word in run_id for run_id in live_check.RUN_IDS.values() for word in ( "with", "without" ) )


def test_a_leaky_without_arm_is_refused_with_its_code_and_no_summary_is_written( repo, tmp_path, capsys ):
    code = live_check.main( argv_of( repo, tmp_path, "--execute" ), factory=factory_of( repo, tmp_path, LiveSession( leaky=True ) ) )
    assert code == 2 and capsys.readouterr().out.startswith( f"REFUSED {err.SURFACE_REACHABLE}" )
    assert not ( tmp_path / "data" / "live-check" / live_check.SUMMARY_FILE ).exists()


def test_a_server_that_is_still_there_after_the_stop_is_reported_as_not_gone( repo, tmp_path, capsys ):
    live_check.main( argv_of( repo, tmp_path, "--execute" ), factory=factory_of( repo, tmp_path, LiveSession(), docker_after_stop=False ) )
    assert json.loads( capsys.readouterr().out )[ "boot" ][ "gone_after_stop" ] is False


def test_the_boot_check_removes_the_server_the_database_and_the_tree_when_the_tests_fail( repo, tmp_path ):
    seen = []
    live_check.main( argv_of( repo, tmp_path, "--execute" ), factory=factory_of( repo, tmp_path, LiveSession(), seen ) )
    boot_spec, ports, docker, databases, _ = seen[ -1 ]
    again   = boot_spec | { "run_id" : "livecheck-again" }
    present = {}
    def broken( handle, path, test_ids ):
        present.update( tree=os.path.isdir( path ), container=bool( docker.containers ), database=bool( databases.dbs ), path=path )
        raise err.HarnessError( err.TESTS_NOT_RUN, "pytest died" )
    ports.tests.run = broken
    with pytest.raises( err.HarnessError ) as caught: live_check.boot_check( again, ports )
    assert caught.value.code == err.TESTS_NOT_RUN
    assert ( present[ "tree" ], present[ "container" ], present[ "database" ] ) == ( True, True, True )
    assert docker.containers == set() and databases.dbs == {} and not os.path.exists( present[ "path" ] )


def booted_ports( repo, tmp_path ):
    """Run a whole check, then hand back the boot run's spec and ports for one more boot."""
    seen = []
    live_check.main( argv_of( repo, tmp_path, "--execute" ), factory=factory_of( repo, tmp_path, LiveSession(), seen ) )
    return seen[ -1 ]


def test_the_boot_seeds_the_sender_key_into_the_runs_own_database_after_the_fresh_check( repo, tmp_path ):
    spec, ports, docker, databases, _ = booted_ports( repo, tmp_path )
    kinds = [ entry[ 0 ] for entry in databases.history if entry[ 1 ] == harness_db( spec ) ]
    assert kinds == [ "create", "provision", "drop" ]


def harness_db( spec ):
    """Return the database name a run id gets."""
    from lupin_mcp.reuse_harness import run as harness
    return harness.db_name( spec[ "run_id" ] )


def test_a_database_that_is_not_fresh_is_reported_as_not_fresh_by_the_boot( repo, tmp_path ):
    spec, ports, *_ = booted_ports( repo, tmp_path )
    ports.server.db_is_fresh = lambda handle: False
    assert live_check.boot_check( spec | { "run_id" : "livecheck-dirty" }, ports )[ "fresh" ] is False


def test_the_boot_runs_the_arm_with_the_tools_so_its_tree_keeps_the_skill_folder( repo, tmp_path ):
    spec, ports, *_ = booted_ports( repo, tmp_path )
    seen = {}
    real = ports.tests.run
    def spy( handle, path, test_ids ):
        seen[ "skill" ] = os.path.exists( os.path.join( path, arms.SKILL_PATH ) )
        return real( handle, path, test_ids )
    ports.tests.run = spy
    live_check.boot_check( spec | { "run_id" : "livecheck-skill" }, ports )
    assert spec[ "arm" ] == arms.ARM_WITH and seen[ "skill" ] is True


def test_the_module_entry_point_exits_with_the_checks_code( repo, tmp_path, monkeypatch, capsys ):
    monkeypatch.setattr( sys, "argv", [ "live_check", *argv_of( repo, tmp_path ) ] )
    monkeypatch.delitem( sys.modules, "lupin_mcp.reuse_harness.live_check" )
    with pytest.raises( SystemExit ) as caught: runpy.run_module( "lupin_mcp.reuse_harness.live_check", run_name="__main__" )
    assert caught.value.code == 0 and "PLAN" in capsys.readouterr().out
