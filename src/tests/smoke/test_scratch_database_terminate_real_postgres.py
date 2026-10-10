"""
The scratch-database terminate statement must leave a superuser's session alone.

The helper in tests/helpers/template_database.py closes every session on a scratch database before the drop.
Run as the restricted test login, Postgres refuses to end a session owned by a superuser, so one such session
makes the whole statement fail. This file reproduces that with a superuser client session standing in for the
foreign session. It is a stand-in: it shows the refusal and what the fixed statement must do, not which real
process held the database in the field.

Arms:
1. A superuser client session and an own-role session are on the scratch database. The statement, run as
   lupin_test, must finish, end the own session and leave the superuser session alive.
2. Control: a bare terminate over every session, as the helper wrote it before, is refused by Postgres with the
   superuser message, so arm 1 fails for the reason named and not for an unrelated one.
3. The drop. With the superuser session still attached, the statement succeeds and the drop is refused with
   "is being accessed by other users". Once that session is gone the same pair of steps drops the database.
   The helper cannot end a superuser's session. The fix covers a foreign backend that is not a client session.
   It does not make the drop pass while a superuser client session stays on the database.

It reuses the throwaway harness of test_db_roles_rollback_real_postgres.py. Docker is reached by exec only.
Venue: host-side, docker required. The merge gate's containers have no docker socket, so there it skips.
"""

import subprocess
import time

import pytest

import tests.helpers.template_database as td
from test_db_roles_rollback_real_postgres import (   # noqa: F401  (fixtures are used by name)
    SUPERUSER, _assert_marker, _docker, _labels_of, _provision, _psql, needs_docker,
    refuse_unless_throwaway, throwaway,
)

SCRATCH   = "scratch_terminate_probe"
REFUSAL   = "SUPERUSER attribute"
UNFILTERED = "SELECT pg_terminate_backend( pid ) FROM pg_stat_activity WHERE datname = :n AND pid <> pg_backend_pid()"


def _as( box, role, database, sql ):
    """
    Run SQL in the throwaway container as a login role; returns the code, stdout and stderr.

    Requires:
        - box is the throwaway fixture; the container name and label are checked before any command
    Ensures:
        - a refusal by Postgres is returned, not raised, so a test can assert the refusal text
    """
    refuse_unless_throwaway( box[ "name" ], _labels_of( box[ "name" ] ) )
    done = _docker( "exec", "-i", box[ "name" ], "psql", "-U", role, "-d", database, "-v", "ON_ERROR_STOP=1", "-tA", stdin=sql )
    return done.returncode, done.stdout.strip(), done.stderr.strip()


def _hold_session( box, role, database ):
    """
    Open a client session that stays on the database until it is ended.

    Requires:
        - box is the throwaway fixture; the container name and label are checked before the command
    Ensures:
        - returns the Popen handle of a docker exec psql running pg_sleep
    """
    refuse_unless_throwaway( box[ "name" ], _labels_of( box[ "name" ] ) )
    return subprocess.Popen( [ "docker", "exec", box[ "name" ], "psql", "-U", role, "-d", database, "-tAc", "SELECT pg_sleep( 120 )" ],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL )


def _sessions( box, database ):
    """Return the sorted user names of the client sessions on a database."""
    sql = f"SELECT usename FROM pg_stat_activity WHERE datname = '{database}' AND backend_type = 'client backend' AND pid <> pg_backend_pid() ORDER BY 1;\n"
    return _psql( box[ "name" ], "postgres", sql ).split()


def _wait_for_sessions( box, database, expected ):
    """Poll until the sessions on the database match the expected user names."""
    deadline = time.monotonic() + 15
    seen = _sessions( box, database )
    while seen != expected and time.monotonic() < deadline:
        time.sleep( 0.3 )
        seen = _sessions( box, database )
    assert seen == expected, f"the sessions on {database} are {seen}, not the {expected} the test set up"


@pytest.fixture
def scratch( throwaway, tmp_path ):
    """The provisioned server with a scratch database holding two sessions."""
    _provision( throwaway, tmp_path )
    _assert_marker( throwaway )
    made = _as( throwaway, "lupin_test", "postgres", f"CREATE DATABASE {SCRATCH};\n" )
    assert made[ 0 ] == 0, f"lupin_test could not make the scratch database: {made[ 2 ]}"
    held = [ _hold_session( throwaway, SUPERUSER, SCRATCH ), _hold_session( throwaway, "lupin_test", SCRATCH ) ]
    try:
        _wait_for_sessions( throwaway, SCRATCH, sorted( [ SUPERUSER, "lupin_test" ] ) )
        yield throwaway
    finally:
        for proc in held:
            proc.kill()
            proc.wait()


def _run( box, statement ):
    """Run a terminate statement as lupin_test; returns the code and stderr."""
    code, _out, err = _as( box, "lupin_test", "postgres", statement.replace( ":n", f"'{SCRATCH}'" ) + ";\n" )
    return code, err


@needs_docker
def test_arm1_the_helper_statement_ends_the_own_session_and_spares_the_superuser_one( scratch ):
    code, err = _run( scratch, td.terminate_sessions_sql( True ) )
    assert code == 0, f"the helper statement was refused: {err}"
    assert _sessions( scratch, SCRATCH ) == [ SUPERUSER ], "the superuser session must stay and the own session must go"


@needs_docker
def test_arm2_control_the_unfiltered_statement_is_refused_for_the_superuser_session( scratch ):
    code, err = _run( scratch, UNFILTERED )
    assert code != 0 and REFUSAL in err, f"the wall was not seen: code={code} err={err!r}"


@needs_docker
def test_arm3_a_superuser_client_session_still_blocks_the_drop_until_it_is_gone( scratch ):
    drop = f"DROP DATABASE IF EXISTS {SCRATCH};\n"
    code, err = _run( scratch, td.terminate_sessions_sql( True ) )
    assert code == 0, f"the helper statement was refused: {err}"
    blocked, _out, why = _as( scratch, "lupin_test", "postgres", drop )
    assert blocked != 0 and "being accessed by other users" in why, f"the drop was not refused for the named reason: code={blocked} err={why!r}"
    assert _sessions( scratch, SCRATCH ) == [ SUPERUSER ], "the superuser session must be what blocks the drop"
    _psql( scratch[ "name" ], "postgres", f"SELECT pg_terminate_backend( pid ) FROM pg_stat_activity WHERE datname = '{SCRATCH}' AND usename = '{SUPERUSER}';\n" )
    _wait_for_sessions( scratch, SCRATCH, [ ] )
    code, err = _run( scratch, td.terminate_sessions_sql( True ) )
    assert code == 0, f"the helper statement was refused: {err}"
    dropped, _out, why = _as( scratch, "lupin_test", "postgres", drop )
    assert dropped == 0, f"the drop failed with no superuser session left: {why}"
    gone = _psql( scratch[ "name" ], "postgres", f"SELECT count(*) FROM pg_database WHERE datname = '{SCRATCH}';\n" ).strip()
    assert gone == "0", "the database is still there after a successful drop"
