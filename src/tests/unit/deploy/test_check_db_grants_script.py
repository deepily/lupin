"""
lib/check-db-grants.sh and the two scripts that call it.

A stub psql stands in for the database: it answers the check's script from a state file and records every
repair it is asked for. Nothing here reaches Postgres or docker, and no bounce or preflight probe is run
for real. The preflight script's probe is pinned by its text, since its other probes need a container.
Venue: :7999 (unit, stub psql).
"""

import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT   = os.environ[ "LUPIN_ROOT" ]
HELPER = os.path.join( ROOT, "src/scripts/lib/check-db-grants.sh" )
BOUNCE = os.path.join( ROOT, "src/scripts/bounce-dev-server.sh" )
PREFLIGHT = os.path.join( ROOT, "src/scripts/preflight-test-container.sh" )

RED   = "lupin_db_dev|tables||3|\\nlupin_db_dev|missing|lupin_host|widgets|INSERT\\nlupin_db_test|tables||2|\\n"
CLEAN = "lupin_db_dev|tables||3|\\nlupin_db_test|tables||2|\\n"

STUB = f"""#!{sys.executable}
import os, sys
state = os.environ[ "STUB_STATE" ]
stdin = sys.stdin.read()
log   = open( state + ".log", "a" )
if "set grants_only 1" in stdin:
    log.write( "repair\\n" )
    if os.environ.get( "STUB_REPAIR_FAILS" ): sys.exit( 4 )
    if not os.environ.get( "STUB_REPAIR_NO_EFFECT" ): open( state, "w" ).write( "clean" )
    sys.exit( 0 )
log.write( "check\\n" )
if os.environ.get( "STUB_PSQL_FAILS" ): print( "connection refused", file=sys.stderr ); sys.exit( 3 )
print( "{CLEAN}" if open( state ).read() == "clean" else "{RED}", end="" )
"""


@pytest.fixture
def stub( tmp_path ):
    psql = tmp_path / "stub-psql"
    psql.write_text( STUB )
    psql.chmod( psql.stat().st_mode | stat.S_IEXEC )
    state = tmp_path / "state"
    def make( start, **env ):
        state.write_text( start )
        base = dict( os.environ, DB_GRANTS_PSQL=str( psql ), DB_GRANTS_PYTHON=sys.executable, DB_GRANTS_SECRETS_DIR="", STUB_STATE=str( state ) )
        base.update( env )
        return base
    make.calls = lambda: ( tmp_path / "state.log" ).read_text().split() if ( tmp_path / "state.log" ).exists() else []
    return make


def _helper( env, *args ):
    return subprocess.run( [ "bash", HELPER, *args ], env=env, capture_output=True, text=True, timeout=60 )


def test_a_clean_database_exits_zero_and_asks_once_without_repairing( stub ):
    done = _helper( stub( "clean" ), "--repair" )
    assert done.returncode == 0 and "lupin_db_dev: 3 tables" in done.stdout
    assert stub.calls() == [ "check" ]


def test_a_red_check_without_repair_exits_three_and_repairs_nothing( stub ):
    done = _helper( stub( "red" ) )
    assert done.returncode == 3 and "lupin_host cannot INSERT widgets" in done.stdout
    assert stub.calls() == [ "check" ]


def test_a_red_check_with_repair_repairs_once_checks_again_and_exits_zero( stub ):
    done = _helper( stub( "red" ), "--repair" )
    assert done.returncode == 0 and "repaired" in done.stdout
    assert stub.calls() == [ "check", "repair", "check" ]


def test_repair_when_enabled_repairs_only_with_the_switch_on( stub ):
    off = _helper( stub( "red" ), "--repair-when-enabled" )
    assert off.returncode == 3 and stub.calls() == [ "check" ]
    on = _helper( stub( "red", LUPIN_DB_GRANTS_REPAIR="on" ), "--repair-when-enabled" )
    assert on.returncode == 0 and stub.calls() == [ "check", "check", "repair", "check" ]
    other = _helper( stub( "red", LUPIN_DB_GRANTS_REPAIR="yes" ), "--repair-when-enabled" )
    assert other.returncode == 3, "only the word on enables the repair"


def test_a_repair_that_changes_nothing_exits_one_and_says_still_red( stub ):
    done = _helper( stub( "red", STUB_REPAIR_NO_EFFECT="1" ), "--repair" )
    assert done.returncode == 1 and "STILL RED" in done.stderr
    assert stub.calls() == [ "check", "repair", "check" ]


def test_a_repair_that_fails_exits_one_and_does_not_check_again( stub ):
    done = _helper( stub( "red", STUB_REPAIR_FAILS="1" ), "--repair" )
    assert done.returncode == 1 and "the repair itself failed" in done.stderr
    assert stub.calls() == [ "check", "repair" ]


def test_a_check_that_cannot_run_exits_two_and_is_not_a_pass( stub ):
    done = _helper( stub( "red", STUB_PSQL_FAILS="1" ), "--repair" )
    assert done.returncode == 2 and "grants were not verified" in done.stderr
    assert stub.calls() == [ "check" ], "a repair was attempted on a check that never ran"


def _five_python( tmp_path ):
    """A stand-in interpreter that exits 5, the answer for an unsearchable directory."""
    fake = tmp_path / "five-python"
    fake.write_text( "#!/bin/sh\necho \"$@\" >> " + str( tmp_path ) + "/args.log\necho 'note: the secret files were not checked'\nexit 5\n" )
    fake.chmod( 0o755 )
    return fake


def test_a_check_that_could_not_look_at_the_secret_files_exits_four_and_says_not_checked( stub, tmp_path ):
    done = _helper( stub( "clean", DB_GRANTS_PYTHON=str( _five_python( tmp_path ) ), DB_GRANTS_SECRETS_DIR="/etc/lupin/secrets" ), "--repair" )
    assert done.returncode == 4 and "NOT checked" in done.stderr and "/etc/lupin/secrets" in done.stderr
    assert "--secrets-dir /etc/lupin/secrets" in ( tmp_path / "args.log" ).read_text(), "the helper did not pass the directory on"
    assert stub.calls() == [ ], "a repair was attempted on a check that never looked"


def test_an_empty_secrets_directory_setting_skips_the_secret_files( stub, tmp_path ):
    _helper( stub( "clean", DB_GRANTS_PYTHON=str( _five_python( tmp_path ) ) ) )
    assert "--secrets-dir" not in ( tmp_path / "args.log" ).read_text()


def _unset_default( stub, tmp_path ):
    """The environment of a caller that never mentions the secrets directory."""
    env = stub( "clean", DB_GRANTS_PYTHON=str( _five_python( tmp_path ) ) )
    del env[ "DB_GRANTS_SECRETS_DIR" ]
    return env


def test_the_helper_checks_etc_lupin_secrets_when_nobody_names_a_directory( stub, tmp_path ):
    done = _helper( _unset_default( stub, tmp_path ) )
    assert done.returncode == 4 and "/etc/lupin/secrets" in done.stderr
    assert "--secrets-dir /etc/lupin/secrets" in ( tmp_path / "args.log" ).read_text()


def test_a_bounce_with_no_directory_named_says_the_secret_files_were_not_checked( stub, tmp_path ):
    done = _bounce( _unset_default( stub, tmp_path ) )
    assert done.returncode == 0 and "NOT checked" in done.stderr


def test_the_repair_checks_the_secret_files_again_and_does_not_hide_a_gap( stub, tmp_path ):
    fake = tmp_path / "gap-python"
    fake.write_text( "#!/bin/sh\necho \"$@\" >> " + str( tmp_path ) + "/args.log\ncase \"$*\" in *grants-only*) exit 0;; esac\necho 'secret file is absent'\nexit 1\n" )
    fake.chmod( 0o755 )
    done = _helper( stub( "clean", DB_GRANTS_PYTHON=str( fake ), DB_GRANTS_SECRETS_DIR="/etc/lupin/secrets" ), "--repair" )
    assert done.returncode == 1 and "STILL RED" in done.stderr
    assert ( tmp_path / "args.log" ).read_text().count( "--secrets-dir /etc/lupin/secrets" ) == 2, "the recheck dropped the directory"


def _recheck_python( tmp_path ):
    """A stand-in interpreter: red check, working repair, then an unsearchable directory."""
    fake = tmp_path / "recheck-python"
    fake.write_text( "#!/bin/sh\necho \"$@\" >> " + str( tmp_path ) + "/args.log\n"
                     "case \"$*\" in *grants-only*) exit 0;; esac\n"
                     "n=$(grep -c -e '--check' " + str( tmp_path ) + "/args.log)\n"
                     "[ \"$n\" -eq 1 ] && exit 1\nexit 5\n" )
    fake.chmod( 0o755 )
    return fake


def test_a_repair_that_works_on_a_host_that_cannot_search_the_directory_exits_four_not_one( stub, tmp_path ):
    fake = _recheck_python( tmp_path )
    done = _helper( stub( "clean", DB_GRANTS_PYTHON=str( fake ), DB_GRANTS_SECRETS_DIR="/etc/lupin/secrets" ), "--repair" )
    assert done.returncode == 4 and "repaired" in done.stderr and "NOT checked" in done.stderr, done.stderr
    assert "STILL RED" not in done.stderr


def test_a_bounce_after_that_repair_warns_and_exits_zero( stub, tmp_path ):
    fake = _recheck_python( tmp_path )
    done = _bounce( stub( "clean", DB_GRANTS_PYTHON=str( fake ), DB_GRANTS_SECRETS_DIR="/etc/lupin/secrets", LUPIN_DB_GRANTS_REPAIR="on" ) )
    assert done.returncode == 0 and "NOT checked" in done.stderr and "still lack grants" not in done.stderr


def test_an_unknown_argument_exits_two_and_help_exits_zero( stub ):
    assert _helper( stub( "clean" ), "--bogus" ).returncode == 2
    helped = _helper( stub( "clean" ), "--help" )
    assert helped.returncode == 0 and "Usage:" in helped.stdout and stub.calls() == []


# ── the bounce script ────────────────────────────────────────────────────────

def _bounce( env, **extra ):
    tmp     = tempfile.mkdtemp()
    scripts = Path( tmp ) / "src" / "scripts"
    scripts.mkdir( parents=True )
    ( scripts / "bounce_dev_warn.py" ).write_text( "import sys\nsys.exit( 0 )\n" )
    ( scripts / "bounce_busy_probe.py" ).write_text( "import sys\nsys.exit( 0 )\n" )
    fakebin = Path( tmp ) / "bin"
    fakebin.mkdir()
    ( fakebin / "docker" ).write_text( "#!/bin/sh\nif [ \"$1\" = \"inspect\" ]; then date -u +%Y-%m-%dT%H:%M:%S.000000000Z; fi\nexit 0\n" )
    ( fakebin / "docker" ).chmod( 0o755 )
    ( fakebin / "curl" ).write_text( "#!/bin/sh\nexit 0\n" )
    ( fakebin / "curl" ).chmod( 0o755 )
    run_env = dict( env, LUPIN_ROOT=tmp, PATH=str( fakebin ) + os.pathsep + env[ "PATH" ], UNWARNED_PAUSE_SECS="0", HEALTH_CONSECUTIVE="1" )
    run_env.update( extra )
    return subprocess.run( [ "bash", BOUNCE, "--quiet" ], env=run_env, capture_output=True, text=True, timeout=60 )


def test_a_bounce_with_red_grants_and_repair_off_warns_checks_once_and_exits_zero( stub ):
    done = _bounce( stub( "red" ) )
    assert done.returncode == 0 and "WARNING: the database roles lack grants" in done.stderr
    assert "lupin_host cannot INSERT widgets" in done.stdout
    assert stub.calls() == [ "check" ]


def test_a_bounce_with_repair_on_repairs_a_red_database_and_exits_zero( stub ):
    done = _bounce( stub( "red" ), LUPIN_DB_GRANTS_REPAIR="on" )
    assert done.returncode == 0
    assert stub.calls() == [ "check", "repair", "check" ]


def test_a_bounce_with_repair_on_and_roles_still_short_exits_one( stub ):
    done = _bounce( stub( "red", STUB_REPAIR_NO_EFFECT="1" ), LUPIN_DB_GRANTS_REPAIR="on" )
    assert done.returncode == 1 and "still lack grants after a repair" in done.stderr


def test_a_bounce_with_clean_grants_under_quiet_prints_no_grants_lines( stub ):
    done = _bounce( stub( "clean" ) )
    assert done.returncode == 0 and "tables" not in done.stdout
    assert "grants" not in done.stderr and stub.calls() == [ "check" ]


def test_a_bounce_whose_check_cannot_run_warns_and_exits_zero( stub ):
    done = _bounce( stub( "red", STUB_PSQL_FAILS="1" ) )
    assert done.returncode == 0 and "could not be checked" in done.stderr


def test_a_bounce_whose_secret_files_were_not_checked_says_so_and_exits_zero( stub, tmp_path ):
    done = _bounce( stub( "clean", DB_GRANTS_PYTHON=str( _five_python( tmp_path ) ), DB_GRANTS_SECRETS_DIR="/etc/lupin/secrets" ) )
    assert done.returncode == 0 and "NOT checked" in done.stderr and "could not be checked" not in done.stderr


def test_a_bounce_with_the_check_skipped_never_asks( stub ):
    done = _bounce( stub( "red" ), LUPIN_DB_GRANTS_CHECK="skip" )
    assert done.returncode == 0 and stub.calls() == []


# ── the preflight script's probe ─────────────────────────────────────────────

PROBE = os.path.join( ROOT, "src/scripts/lib/preflight-db-grants-probe.sh" )

HARNESS = """
say_ok()   { echo "OK: $1"; }
say_warn() { echo "WARN: $1"; }
say_fail() { echo "FAIL: $1"; }
remedy()   { echo "REMEDY: $1"; }
VERBOSE="${HARNESS_VERBOSE:-false}"
source "$PROBE"
probe_db_grants
"""


def _probe( tmp_path, rc, **env ):
    """Run probe_db_grants with a stub helper that records its run and exits rc."""
    helper = tmp_path / "stub-helper"
    helper.write_text( f"#!/bin/sh\necho ran >> {tmp_path}/helper.log\necho 'helper says hello'\nexit {rc}\n" )
    helper.chmod( helper.stat().st_mode | stat.S_IEXEC )
    run_env = dict( os.environ, PROBE=PROBE, DB_GRANTS_HELPER=str( helper ) )
    run_env.pop( "LUPIN_DB_GRANTS_CHECK", None )
    run_env.update( env )
    done = subprocess.run( [ "bash", "-c", HARNESS ], env=run_env, capture_output=True, text=True, timeout=30 )
    ran = ( tmp_path / "helper.log" ).read_text().split() if ( tmp_path / "helper.log" ).exists() else [ ]
    return done, ran


@pytest.mark.parametrize( "rc, first_line", [
    ( 0, "OK: database roles hold every grant the matrix requires" ),
    ( 1, "FAIL: database roles still lack grants after a repair" ),
    ( 3, "WARN: database roles lack grants (repair is off)" ),
    ( 2, "WARN: database grants could not be checked (exit 2)" ),
    ( 7, "WARN: database grants could not be checked (exit 7)" ),
    ( 4, "WARN: database grants are clean, but the secret files were NOT checked (this login cannot search the directory)" ),
] )
def test_each_helper_exit_code_maps_to_one_verdict_line( tmp_path, rc, first_line ):
    done, ran = _probe( tmp_path, rc )
    verdicts = [ l for l in done.stdout.splitlines() if l.split( ":" )[ 0 ] in ( "OK", "WARN", "FAIL" ) ]
    assert verdicts == [ first_line ], done.stdout
    assert ran == [ "ran" ], "the helper must run exactly once"


@pytest.mark.parametrize( "rc, remedy_word", [ ( 1, "provision-db-roles.sh" ), ( 3, "LUPIN_DB_GRANTS_REPAIR=on" ), ( 4, "group 1002" ) ] )
def test_a_red_answer_prints_its_remedy( tmp_path, rc, remedy_word ):
    done, _ = _probe( tmp_path, rc )
    assert [ l for l in done.stdout.splitlines() if l.startswith( "REMEDY:" ) and remedy_word in l ]


def test_a_clean_answer_is_quiet_unless_verbose_and_a_red_answer_always_shows_the_helper_lines( tmp_path ):
    assert "helper says hello" not in _probe( tmp_path, 0 )[ 0 ].stdout
    assert "       helper says hello" in _probe( tmp_path, 0, HARNESS_VERBOSE="true" )[ 0 ].stdout
    assert "       helper says hello" in _probe( tmp_path, 3 )[ 0 ].stdout


def test_the_probe_through_the_real_helper_checks_the_default_directory_and_warns_not_checked( stub, tmp_path ):
    env = _unset_default( stub, tmp_path )
    env.update( PROBE=PROBE, DB_GRANTS_HELPER=HELPER )
    done = subprocess.run( [ "bash", "-c", HARNESS ], env=env, capture_output=True, text=True, timeout=30 )
    assert "WARN: database grants are clean, but the secret files were NOT checked" in done.stdout, done.stdout
    assert "--secrets-dir /etc/lupin/secrets" in ( tmp_path / "args.log" ).read_text()


def test_the_skip_switch_warns_and_never_runs_the_helper( tmp_path ):
    done, ran = _probe( tmp_path, 1, LUPIN_DB_GRANTS_CHECK="skip" )
    assert done.stdout.splitlines() == [ "WARN: database grants probe skipped (LUPIN_DB_GRANTS_CHECK=skip)" ]
    assert ran == [ ]


def test_the_probe_calls_the_helper_once_and_lets_the_helper_decide_the_repair():
    calls = [ l for l in open( PROBE ).read().splitlines() if '"$helper"' in l ]
    assert len( calls ) == 1 and '"$helper" --repair-when-enabled ' in calls[ 0 ]


def test_the_preflight_script_sources_the_probe_and_calls_it_before_its_summary():
    text  = open( PREFLIGHT ).read()
    probe = text.index( "# ── 7. Database grants" )
    section = text[ probe: text.index( "# ── 8. Test login secret" ) ]
    assert 'lib/preflight-db-grants-probe.sh"' in section and section.rstrip().endswith( "probe_db_grants" )
    assert subprocess.run( [ "bash", "-n", PREFLIGHT ] ).returncode == 0
    assert subprocess.run( [ "bash", "-n", PROBE ] ).returncode == 0
