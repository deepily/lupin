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
        base = dict( os.environ, DB_GRANTS_PSQL=str( psql ), DB_GRANTS_PYTHON=sys.executable, STUB_STATE=str( state ) )
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


def test_a_bounce_with_the_check_skipped_never_asks( stub ):
    done = _bounce( stub( "red" ), LUPIN_DB_GRANTS_CHECK="skip" )
    assert done.returncode == 0 and stub.calls() == []


# ── the preflight script's probe ─────────────────────────────────────────────

def test_the_preflight_script_calls_the_helper_before_its_summary_and_lets_the_helper_decide_the_repair():
    text  = open( PREFLIGHT ).read()
    probe = text.index( "# ── 7. Database grants" )
    assert probe < text.index( "# ── Summary" )
    assert "lib/check-db-grants.sh" in text[ probe: ] and "--repair-when-enabled" in text[ probe: ]
    assert "--repair )" not in text[ probe: ], "the probe repairs without asking the helper"
    assert subprocess.run( [ "bash", "-n", PREFLIGHT ] ).returncode == 0
