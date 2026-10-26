"""
Unit tests of the driver, with the real ports wired to simulators.

The worktree is cut in a real git repository.
The server port runs over the docker and database simulators of the server tests.
The acceptance port reads a junit report that a stub client's progress decides.
The session is a stub that gains one passing test per slice.
So the stop conditions, the per-run database and the tamper check are shown through the real ports.
"""
import json
import os
import runpy
import stat
import subprocess
import sys
import types

import pytest

from lupin_mcp.reuse_harness import acceptance
from lupin_mcp.reuse_harness import arms
from lupin_mcp.reuse_harness import driver
from lupin_mcp.reuse_harness import errors as err
from lupin_mcp.reuse_harness import freeze
from lupin_mcp.reuse_harness import log
from lupin_mcp.reuse_harness import run as harness
from lupin_mcp.reuse_harness import server
from lupin_mcp.reuse_harness import session
from lupin_mcp.reuse_harness import worktree
from tests.unit.test_reuse_harness_server import Clock, Databases, Docker
from tests.unit.test_reuse_harness_session import FAKE_CLAUDE

TEST_FILE = f"{freeze.TEST_DIR}/test_x.py"
FEATURES  = "| F01 | a |\n"
COMPOSE   = "services:\n  other:\n    image: nope\n  lupin-rest-test:\n    image: lupin:9.9.9-test\n"


def git_in( root, *args ):
    """Run git in a test repository and return its output."""
    return subprocess.run( [ "git", "-C", str( root ), "-c", "user.name=t", "-c", "user.email=t@example.com", *args ], check=True, capture_output=True, text=True ).stdout.strip()


@pytest.fixture
def repo( tmp_path ):
    """Build a repository of a frozen test, a server file, an old client and the skill."""
    root = tmp_path / "repo"
    root.mkdir()
    git_in( root, "init", "-q", "-b", "main" )
    files = { TEST_FILE : 'import pytest\n\n@pytest.mark.feature( "F01" )\ndef test_a():\n    pass\n\n@pytest.mark.feature( "F01" )\ndef test_b():\n    pass\n',
              "src/cosa/server.py" : "x = 1\n", f"{worktree.CLIENT_ROOT}/old.html" : "old", f"{arms.SKILL_PATH}/SKILL.md" : "skill", freeze.FEATURE_LIST : FEATURES, "docker-compose.yml" : COMPOSE }
    for relative, text in files.items():
        ( root / relative ).parent.mkdir( parents=True, exist_ok=True )
        ( root / relative ).write_text( text )
    git_in( root, "add", "." )
    git_in( root, "commit", "-q", "-m", "frozen" )
    return { "root" : root, "commit" : git_in( root, "rev-parse", "HEAD" ), "data" : tmp_path / "data" }


class Ok:
    """A provisioner that always reports ready."""

    def __call__( self, path ):
        """Answer ready."""
        return { "status" : "ok", "detail" : "" }


class StubSession:
    """A session whose client gains a passing test per slice, and that can tamper with the tests."""

    def __init__( self, ceiling=99, tamper=False ):
        """Choose the ceiling and whether the first slice edits the frozen test file."""
        self.ceiling, self.tamper, self.progress, self.bound = ceiling, tamper, 0, None

    def bind( self, path, handle ):
        """Remember the tree and server."""
        self.bound = ( path, handle )

    def probe( self, config, surface ):
        """Answer a call unless a deny rule names the surface."""
        return arms.DENY_RULES[ surface ] not in config[ "deny_rules" ]

    def work( self, config, path, handle, remaining_hours ):
        """Gain one passing test; optionally edit a frozen test."""
        if self.tamper: open( os.path.join( path, TEST_FILE ), "a" ).write( "\n# edited by the run\n" )
        self.progress = min( self.progress + 1, self.ceiling )
        return { "seat_hours" : 1.0, "finished" : False }


def wire( repo, spec, session_stub, tmp_path ):
    """Wire the real ports over simulators; the junit report follows the stub client's progress."""
    docker    = Docker()
    databases = Databases()
    clock     = Clock()
    run_dir   = driver.run_dir_of( str( repo[ "data" ] ), spec )
    os.makedirs( os.path.join( run_dir, "reports" ) )

    def runner( argv, env=None, cwd=None, timeout=None ):
        """Write a report with as many passing tests as the stub client has gained; answer the build."""
        if "pytest" in argv:
            cases = "".join( f'<testcase classname="{freeze.TEST_DIR.replace( "/", "." )}.test_x" name="{name}">{"" if index < session_stub.progress else "<failure/>"}</testcase>' for index, name in enumerate( [ "test_a", "test_b" ] ) )
            open( [ word for word in argv if word.startswith( "--junitxml=" ) ][ 0 ].split( "=", 1 )[ 1 ], "w" ).write( f"<testsuites><testsuite>{cases}</testsuite></testsuites>" )
            return 1, ""
        return 0, ""

    ports = types.SimpleNamespace(
        worktree = worktree.Worktrees( str( repo[ "root" ] ), venv=Ok(), artifacts=Ok() ),
        server   = server.Servers( databases, "lupin:img", "ck_live_key", runner=docker, environ={ "JWT_SECRET_KEY" : "s" }, login=lambda: ( "u", "p" ), port_free=lambda port: True,
                                   health=lambda url: True, sleep=clock.sleep, clock=clock ),
        session  = session_stub,
        tests    = acceptance.Acceptance( repo[ "commit" ], "ck_live_key", os.path.join( run_dir, "reports" ), runner=runner, environ={} ),
        log      = log.RunLog( run_dir ) )
    return ports, docker, databases, run_dir


def make_spec( repo, arm=arms.ARM_WITH, run_id="run1", cap=10 ):
    """Build a run spec over the frozen test ids."""
    return { "run_id" : run_id, "arm" : arm, "model_id" : "claude-opus-5-5", "server_commit" : repo[ "commit" ], "cap_seat_hours" : cap, "test_ids" : [ f"{TEST_FILE}::test_a", f"{TEST_FILE}::test_b" ] }


def test_a_run_ends_at_the_first_verdict_where_every_test_passes_and_leaves_nothing_running( repo, tmp_path ):
    spec = make_spec( repo )
    ports, docker, databases, run_dir = wire( repo, spec, StubSession(), tmp_path )
    result = driver.execute( spec, ports, run_dir )
    assert ( result[ "stop" ], result[ "passing_tests" ], result[ "pass_rate" ], result[ "seat_hours" ] ) == ( harness.STOP_ALL_PASS, 2, 1.0, 2.0 )
    assert docker.containers == set() and databases.dbs == {} and docker.verbs().count( "run" ) == 1
    assert json.load( open( os.path.join( run_dir, driver.RESULT_FILE ) ) ) == result


def test_a_run_whose_client_stalls_stops_at_the_cap_and_is_scored_as_it_stands( repo, tmp_path ):
    spec = make_spec( repo, cap=3 )
    ports, docker, databases, run_dir = wire( repo, spec, StubSession( ceiling=1 ), tmp_path )
    result = driver.execute( spec, ports, run_dir )
    assert ( result[ "stop" ], result[ "passing_tests" ], result[ "pass_rate" ], result[ "seat_hours" ] ) == ( harness.STOP_CAP, 1, 0.5, 3.0 )
    assert docker.containers == set() and databases.dbs == {}


def test_each_run_gets_its_own_database_and_container_and_a_second_run_starts_clean( repo, tmp_path ):
    first_spec  = make_spec( repo, run_id="run1" )
    second_spec = make_spec( repo, run_id="run2" )
    ports, docker, databases, run_dir = wire( repo, first_spec, StubSession(), tmp_path )
    driver.execute( first_spec, ports, run_dir )
    second_ports, _, _, second_dir = wire( repo, second_spec, StubSession(), tmp_path )
    second_ports.server.databases, second_ports.server.runner = databases, docker
    driver.execute( second_spec, second_ports, second_dir )
    created = [ entry[ 1 ] for entry in databases.history if entry[ 0 ] == "create" ]
    assert created == [ harness.db_name( "run1" ), harness.db_name( "run2" ) ] and len( set( created ) ) == 2
    assert [ entry[ 1 ] for entry in databases.history if entry[ 0 ] == "provision" ] == created and databases.dbs == {}


def test_the_sender_key_is_seeded_into_the_runs_database_after_it_is_found_clean( repo, tmp_path ):
    spec = make_spec( repo )
    ports, _, databases, run_dir = wire( repo, spec, StubSession(), tmp_path )
    driver.execute( spec, ports, run_dir )
    kinds = [ entry[ 0 ] for entry in databases.history ]
    assert kinds.index( "create" ) < kinds.index( "provision" ) < kinds.index( "drop" ) and ( "provision", harness.db_name( "run1" ), "ck_live_key" ) in databases.history


def test_a_run_that_edits_the_frozen_tests_is_refused_stops_its_server_and_writes_no_result( repo, tmp_path ):
    spec = make_spec( repo )
    ports, docker, databases, run_dir = wire( repo, spec, StubSession( tamper=True ), tmp_path )
    with pytest.raises( err.HarnessError ) as caught: driver.execute( spec, ports, run_dir )
    assert caught.value.code == err.TESTS_TAMPERED
    assert docker.containers == set() and databases.dbs == {} and not os.path.exists( os.path.join( run_dir, driver.RESULT_FILE ) )


def test_the_run_folder_is_named_by_the_arms_blind_label_and_no_log_line_names_the_arm( repo, tmp_path ):
    for arm in arms.ARMS:
        spec = make_spec( repo, arm=arm, run_id=f"pair-{arms.ARMS.index( arm )}" )
        ports, _, _, run_dir = wire( repo, spec, StubSession(), tmp_path )
        driver.execute( spec, ports, run_dir )
        assert os.path.basename( os.path.dirname( run_dir ) ) == arms.ARM_LABELS[ arm ]
        records = [ json.loads( line ) for line in open( os.path.join( run_dir, log.LOG_FILE ) ) ]
        assert all( "arm" not in record and record[ "arm_label" ] == arms.ARM_LABELS[ arm ] for record in records ) and records[ -1 ][ "event" ] == "stop"


def test_a_second_result_in_the_same_folder_is_refused_after_the_run_has_finished( repo, tmp_path ):
    spec = make_spec( repo )
    ports, _, _, run_dir = wire( repo, spec, StubSession(), tmp_path )
    driver.execute( spec, ports, run_dir )
    again = make_spec( repo, run_id="run1b" )
    other_ports = wire( repo, again, StubSession(), tmp_path )[ 0 ]
    with pytest.raises( FileExistsError ): driver.execute( again, other_ports, run_dir )


def real_sessions( tmp_path, leaky=False ):
    """Return Sessions over a fake CLI subprocess; a leaky one ignores deny rules."""
    path = tmp_path / ( "claude-leaky" if leaky else "claude" )
    text = FAKE_CLAUDE.format( python=sys.executable )
    if leaky: text = text.replace( 'denied = argv[ argv.index( "--disallowedTools" ) + 1 ].split( "," ) if "--disallowedTools" in argv else []', "denied = []" )
    path.write_text( text )
    path.chmod( path.stat().st_mode | stat.S_IXUSR )
    return session.Sessions( "k", claude=str( path ), environ=dict( os.environ ) )


@pytest.mark.parametrize( "arm", arms.ARMS )
def test_a_dry_run_of_each_arm_proves_the_switch_with_no_server_and_removes_its_tree( repo, tmp_path, arm ):
    spec = make_spec( repo, arm=arm )
    ports, docker, databases, _ = wire( repo, spec, real_sessions( tmp_path ), tmp_path )
    answers = driver.dry_run( spec, ports )
    assert answers == { surface : arm == arms.ARM_WITH for surface in arms.SURFACES }
    assert docker.calls == [] and databases.history == [] and os.path.exists( os.path.join( str( repo[ "root" ] ), worktree.BASE_DIR, "run1" ) ) is False


def test_a_dry_run_of_the_arm_without_the_tools_fails_loudly_on_a_leaky_cli_and_still_removes_its_tree( repo, tmp_path ):
    spec = make_spec( repo, arm=arms.ARM_WITHOUT )
    ports, _, _, _ = wire( repo, spec, real_sessions( tmp_path, leaky=True ), tmp_path )
    with pytest.raises( err.HarnessError ) as caught: driver.dry_run( spec, ports )
    assert caught.value.code == err.SURFACE_REACHABLE
    assert os.path.exists( os.path.join( str( repo[ "root" ] ), worktree.BASE_DIR, "run1" ) ) is False


def test_a_dry_run_refuses_a_bad_spec_before_cutting_a_tree( repo, tmp_path ):
    spec = make_spec( repo )
    ports, _, _, _ = wire( repo, spec, StubSession(), tmp_path )
    spec[ "cap_seat_hours" ] = 0
    with pytest.raises( err.HarnessError ) as caught: driver.dry_run( spec, ports )
    assert caught.value.code == err.BAD_SPEC and os.path.exists( os.path.join( str( repo[ "root" ] ), worktree.BASE_DIR ) ) is False


def test_image_of_reads_the_test_servers_image_and_refuses_a_file_without_one():
    assert driver.image_of( COMPOSE ) == "lupin:9.9.9-test"
    for text in ( "services: {}\n", "services:\n  lupin-rest-test:\n    build: .\n", "x: 1\n" ):
        with pytest.raises( err.HarnessError ) as caught: driver.image_of( text )
        assert caught.value.code == err.BAD_SPEC


def test_make_key_has_the_servers_key_format_and_is_new_each_time():
    first, second = driver.make_key(), driver.make_key()
    assert first.startswith( "ck_live_" ) and len( first ) >= 64 and first != second


def test_build_ports_shares_one_key_makes_the_run_folder_and_starts_nothing( repo, monkeypatch ):
    monkeypatch.setenv( "LUPIN_TEST_DB_USER", "tester" )
    monkeypatch.setenv( "LUPIN_TEST_DB_PASSWORD", "pw" )
    spec  = make_spec( repo )
    ports = driver.build_ports( spec, str( repo[ "root" ] ), str( repo[ "data" ] ), "lupin:img", mcp_config="/cfg/mcp.json", environ={ "PATH" : "/bin" } )
    assert ports.server.sender_key == ports.tests.notify_api_key == ports.session.notify_api_key and ports.server.sender_key.startswith( "ck_live_" )
    assert ports.session.mcp_config == "/cfg/mcp.json" and ports.server.environ[ "JWT_SECRET_KEY" ] and ports.server.image == "lupin:img"
    assert os.path.isdir( os.path.join( driver.run_dir_of( str( repo[ "data" ] ), spec ), "reports" ) ) and ports.tests.commit == repo[ "commit" ]


def test_build_ports_keeps_a_jwt_secret_the_environment_already_has( repo, monkeypatch ):
    monkeypatch.setenv( "LUPIN_TEST_DB_USER", "tester" )
    monkeypatch.setenv( "LUPIN_TEST_DB_PASSWORD", "pw" )
    ports = driver.build_ports( make_spec( repo ), str( repo[ "root" ] ), str( repo[ "data" ] ), "i", environ={ "JWT_SECRET_KEY" : "mine" } )
    assert ports.server.environ[ "JWT_SECRET_KEY" ] == "mine"


def test_build_ports_reads_the_process_environment_by_default( repo, monkeypatch ):
    monkeypatch.setenv( "LUPIN_TEST_DB_USER", "tester" )
    monkeypatch.setenv( "LUPIN_TEST_DB_PASSWORD", "pw" )
    monkeypatch.setenv( "JWT_SECRET_KEY", "from-process" )
    assert driver.build_ports( make_spec( repo ), str( repo[ "root" ] ), str( repo[ "data" ] ), "i" ).server.environ[ "JWT_SECRET_KEY" ] == "from-process"


def argv_of( repo, *extra, arm="with", sha=None ):
    """Return the command line of one driver call."""
    return [ "--repo-root", str( repo[ "root" ] ), "--data-root", str( repo[ "data" ] ), "--run-id", "run1", "--arm", arm, "--model-id", "claude-opus-5-5",
             "--frozen-sha", sha or repo[ "commit" ], "--cap-seat-hours", "5", *extra ]


def test_main_dry_run_prints_the_answers_per_surface_and_exits_zero( repo, tmp_path, capsys ):
    def factory( spec, repo_root, data_root, image, mcp_config, environ ):
        assert image == "lupin:9.9.9-test" and spec[ "server_commit" ] == repo[ "commit" ] and spec[ "test_ids" ] == [ f"{TEST_FILE}::test_a", f"{TEST_FILE}::test_b" ]
        return wire( repo, spec, real_sessions( tmp_path ), tmp_path )[ 0 ]
    assert driver.main( argv_of( repo, "--dry-run", arm="without" ), factory=factory ) == driver.EXIT_DONE
    assert json.loads( capsys.readouterr().out ) == { surface : False for surface in arms.SURFACES }


def test_main_runs_an_arm_and_prints_its_result( repo, tmp_path, capsys ):
    def factory( spec, repo_root, data_root, image, mcp_config, environ ):
        return wire( repo, spec, StubSession(), tmp_path )[ 0 ]
    assert driver.main( argv_of( repo ), factory=factory ) == driver.EXIT_DONE
    assert json.loads( capsys.readouterr().out )[ "stop" ] == harness.STOP_ALL_PASS


def test_main_turns_a_refusal_into_exit_code_two_and_prints_its_code( repo, capsys ):
    assert driver.main( argv_of( repo, sha="0" * 40 ), factory=None ) == driver.EXIT_REFUSED
    assert capsys.readouterr().out.startswith( f"REFUSED {err.NOT_FROZEN}" )


def test_main_passes_the_mcp_config_and_environment_to_the_factory( repo, tmp_path ):
    seen = {}
    def factory( spec, repo_root, data_root, image, mcp_config, environ ):
        seen.update( mcp_config=mcp_config, environ=environ )
        return wire( repo, spec, real_sessions( tmp_path ), tmp_path )[ 0 ]
    driver.main( argv_of( repo, "--dry-run", "--mcp-config", "/cfg/m.json" ), factory=factory, environ={ "A" : "1" } )
    assert seen == { "mcp_config" : "/cfg/m.json", "environ" : { "A" : "1" } }


def test_the_module_entry_point_exits_with_the_drivers_code( monkeypatch ):
    monkeypatch.setattr( sys, "argv", [ "reuse_harness" ] )
    monkeypatch.setattr( driver, "main", lambda argv: 7 )
    with pytest.raises( SystemExit ) as caught: runpy.run_module( "lupin_mcp.reuse_harness", run_name="__main__" )
    assert caught.value.code == 7
