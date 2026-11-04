"""
db_roles grants against a real Postgres, in a container made for the test.

Reuses the throwaway harness of test_db_roles_rollback_real_postgres.py: the same container guards,
the same marker database, the same provisioner call. Nothing here can reach lupin_db_dev or
lupin_db_test on the real server.
Venue: host-side, docker required; the :7999 rubric applies only if a run is timed under two minutes.
The merge gate's containers have no docker socket, so there the docker tests skip: read the skip count.
"""

import os
import subprocess
import sys

import pytest

from cosa.utils import db_grants

from test_db_roles_rollback_real_postgres import (   # noqa: F401  (fixtures are used by name)
    ROLES_SQL, ROOT, SUPERUSER, _assert_marker, _clean_env, _docker, _labels_of, _provision, _psql,
    STOCK_BY_DATABASE, needs_docker, refuse_unless_throwaway, stocked, stocked_tables, throwaway,
)


def _psql_as( box, role, database, sql ):
    """Run SQL inside the throwaway container as a plain login role; returns stdout."""
    refuse_unless_throwaway( box[ "name" ], _labels_of( box[ "name" ] ) )
    done = _docker( "exec", "-i", box[ "name" ], "psql", "-U", role, "-d", database, "-v", "ON_ERROR_STOP=1", "-tA", stdin=sql )
    assert done.returncode == 0, f"psql as {role} failed in {database}: {done.stderr}"
    return done.stdout.strip()


# ── the instrument: can a plain login ask about another role? ────────────────

@needs_docker
def test_a_plain_login_can_ask_what_another_role_may_do( stocked, tmp_path ):
    _provision( stocked, tmp_path )
    # lupin_test is not a superuser, and it is the login the check will run as inside a test.
    assert _psql_as( stocked, "lupin_test", "lupin_db_test", "SELECT rolsuper FROM pg_roles WHERE rolname = current_user;" ) == "f"
    ask = "SELECT has_table_privilege( '{role}', 'public.widgets', 'SELECT' );"
    assert _psql_as( stocked, "lupin_test", "lupin_db_test", ask.format( role="lupin_app" ) )  == "t", "lupin_app was granted every table"
    assert _psql_as( stocked, "lupin_test", "lupin_db_test", ask.format( role="lupin_host" ) ) == "f", "lupin_host has no grant in the test database"
    assert _psql_as( stocked, "lupin_host", "lupin_db_dev", ask.format( role="lupin_host" ) ) == "t", "the same question from another login"
    assert _psql_as( stocked, "lupin_host", "lupin_db_dev", ask.format( role="lupin_test" ) ) == "f", "lupin_test has no grant in the dev database"


def _grants_only( box, database="lupin_db_dev" ):
    """The real provisioner with --grants-only and no password file; returns the process."""
    assert ROOT, "LUPIN_ROOT is not set, so the provisioner would run from the wrong tree"
    _assert_marker( box )
    psql = f"docker exec -i {box[ 'name' ]} psql -U {SUPERUSER} -d {database}"
    args = [ sys.executable, "-m", "cosa.utils.db_roles", "--psql", psql, "--apply", "--grants-only" ]
    env  = _clean_env( LUPIN_ROOT=ROOT, PYTHONPATH=os.path.join( ROOT, "src" ) )
    return subprocess.run( args, capture_output=True, text=True, timeout=120, env=env, cwd=ROOT )


def _may( box, role, database, table, privilege="SELECT" ):
    sql = f"SELECT has_table_privilege( '{role}', 'public.{table}', '{privilege}' );"
    return _psql_as( box, "lupin_test" if database == "lupin_db_test" else "lupin_host", database, sql ) == "t"


# ── --grants-only ────────────────────────────────────────────────────────────

@needs_docker
def test_grants_only_reaches_a_table_made_after_the_roles_and_resets_no_password( stocked, tmp_path ):
    _provision( stocked, tmp_path )
    # A database provisioned before the default privileges existed: take them away, then make the table.
    for database in ( "lupin_db_dev", "lupin_db_test" ):
        _psql( stocked[ "name" ], database,
               "ALTER DEFAULT PRIVILEGES FOR ROLE lupin_dev IN SCHEMA public REVOKE ALL ON TABLES FROM lupin_app, lupin_host, lupin_test;\n"
               "CREATE TABLE late_arrival ( id serial PRIMARY KEY );\n" )
    assert not _may( stocked, "lupin_app", "lupin_db_test", "late_arrival" ), "the setup did not make a table the roles cannot reach"
    roles_before = _psql( stocked[ "name" ], "postgres", ROLES_SQL )

    done = _grants_only( stocked )
    assert done.returncode == 0, f"{done.stdout[ -400: ]} {done.stderr[ -400: ]}"

    assert _may( stocked, "lupin_app",  "lupin_db_test", "late_arrival" )
    assert _may( stocked, "lupin_test", "lupin_db_test", "late_arrival", "DELETE" )
    assert _may( stocked, "lupin_host", "lupin_db_dev",  "late_arrival", "UPDATE" )
    assert _psql( stocked[ "name" ], "postgres", ROLES_SQL ) == roles_before, "grants-only changed a role or a password hash"


@needs_docker
def test_grants_only_on_a_server_without_the_roles_fails_and_names_them( stocked ):
    done = _grants_only( stocked )
    assert done.returncode != 0
    text = done.stdout + done.stderr
    assert "missing roles lupin_app, lupin_host, lupin_test" in text and "grants_only does not create roles" in text
    assert _psql( stocked[ "name" ], "postgres", "SELECT count(*) FROM pg_roles WHERE rolname LIKE 'lupin_a%' OR rolname LIKE 'lupin_h%' OR rolname LIKE 'lupin_t%';" ).strip() == "0"


# ── default privileges ───────────────────────────────────────────────────────

def _asks( box, database, table, role, privilege ):
    """has_table_privilege, asked from a login that can connect to the database."""
    asker = "lupin_test" if database == "lupin_db_test" else "lupin_host"
    sql = f"SELECT has_table_privilege( '{role}', 'public.{table}', '{privilege}' );"
    return _psql_as( box, asker, database, sql ) == "t"


@needs_docker
def test_a_table_made_by_any_creating_role_after_the_run_is_already_granted( stocked, tmp_path ):
    _provision( stocked, tmp_path )
    # who creates, in which database, and who must be able to reach the new table
    plan = [
        ( "lupin_dev",  "lupin_db_test", [ ( "lupin_app", "DELETE" ), ( "lupin_test", "DELETE" ) ] ),
        ( "lupin_test", "lupin_db_test", [ ( "lupin_app", "DELETE" ), ( "lupin_test", "DELETE" ) ] ),
        ( "lupin_app",  "lupin_db_test", [ ( "lupin_test", "DELETE" ) ] ),
        ( "lupin_dev",  "lupin_db_dev",  [ ( "lupin_app", "DELETE" ), ( "lupin_host", "UPDATE" ) ] ),
        ( "lupin_app",  "lupin_db_dev",  [ ( "lupin_host", "UPDATE" ) ] ),
    ]
    for creator, database, recipients in plan:
        table = f"fresh_{creator}"
        _psql_as( stocked, creator, database, f"CREATE TABLE {table} ( id serial PRIMARY KEY );" )
        for role, privilege in recipients:
            assert _asks( stocked, database, table, role, privilege ), f"{role} cannot {privilege} a table {creator} made in {database}"
            # An insert uses the serial column's sequence, so this fails with "permission denied for sequence"
            # when the sequence default privilege is missing, which has_table_privilege cannot see.
            _psql_as( stocked, role, database, f"INSERT INTO {table} DEFAULT VALUES;" )
        _psql_as( stocked, creator, database, f"INSERT INTO {table} DEFAULT VALUES;" )
    # the dev database gives lupin_test nothing, whoever made the table
    assert not _asks( stocked, "lupin_db_dev", "fresh_lupin_dev", "lupin_test", "SELECT" )


# ── --check ──────────────────────────────────────────────────────────────────

def _check( box, database="lupin_db_dev", login=SUPERUSER, *extra ):
    """The real `db_roles --check` against the throwaway container; returns the finished process."""
    assert ROOT, "LUPIN_ROOT is not set, so the check would run from the wrong tree"
    _assert_marker( box )
    psql = f"docker exec -i {box[ 'name' ]} psql -U {login} -d {database}"
    args = [ sys.executable, "-m", "cosa.utils.db_roles", "--psql", psql, "--check", *extra ]
    env  = _clean_env( LUPIN_ROOT=ROOT, PYTHONPATH=os.path.join( ROOT, "src" ) )
    return subprocess.run( args, capture_output=True, text=True, timeout=120, env=env, cwd=ROOT )


def _sql_of( box, database, sql ):
    return _psql( box[ "name" ], database, sql )


@needs_docker
def test_check_is_clean_after_the_provisioning_and_prints_both_counts( stocked, tmp_path ):
    _provision( stocked, tmp_path )
    done = _check( stocked )
    assert done.returncode == 0, done.stdout + done.stderr
    counts = { database: len( stocked_tables( database ) ) for database in STOCK_BY_DATABASE }
    assert all( counts.values() ), "the fixture stocks no tables, so a count read from it proves nothing"
    assert done.stdout.splitlines() == [ f"{database}: {counts[ database ]} tables, 3 roles, 0 problems" for database in ( "lupin_db_dev", "lupin_db_test" ) ]


@needs_docker
def test_check_names_a_grant_that_was_taken_away_and_the_remedy_repairs_it( stocked, tmp_path ):
    _provision( stocked, tmp_path )
    _sql_of( stocked, "lupin_db_dev",  "REVOKE INSERT ON widgets FROM lupin_host;\n" )
    _sql_of( stocked, "lupin_db_test", "REVOKE ALL ON gadgets FROM lupin_test;\n" )
    done = _check( stocked )
    assert done.returncode == 1
    lines = done.stdout.splitlines()
    assert "  lupin_host cannot INSERT widgets" in lines
    assert "  lupin_test cannot SELECT gadgets" in lines and "  lupin_test cannot TRIGGER gadgets" in lines
    assert lines[ -1 ].startswith( "remedy: python -m cosa.utils.db_roles --psql " ) and lines[ -1 ].endswith( "--grants-only --apply" )
    assert _grants_only( stocked ).returncode == 0
    assert _check( stocked ).returncode == 0, "the remedy line's command did not repair what the check found"


@needs_docker
def test_check_never_misses_a_grant_that_was_never_made( stocked, tmp_path ):
    _provision( stocked, tmp_path )
    _sql_of( stocked, "lupin_db_test", "CREATE TABLE ungranted ( id int );\nREVOKE ALL ON ungranted FROM lupin_app, lupin_test;\n" )
    done = _check( stocked )
    assert done.returncode == 1 and "  lupin_app cannot SELECT ungranted" in done.stdout.splitlines()


@needs_docker
def test_check_reports_a_write_the_host_role_must_not_have_on_approval_settings( stocked, tmp_path ):
    _sql_of( stocked, "lupin_db_dev", "CREATE TABLE approval_settings ( id int );\n" )
    _provision( stocked, tmp_path )
    assert _check( stocked ).returncode == 0, "the provisioning leaves the host role read-only on approval_settings"
    _sql_of( stocked, "lupin_db_dev", "GRANT UPDATE ON approval_settings TO lupin_host;\n" )
    done = _check( stocked )
    assert done.returncode == 1 and "  lupin_host can UPDATE approval_settings and must not" in done.stdout.splitlines()


@needs_docker
def test_check_reports_a_connect_right_that_is_wrong_in_either_direction( stocked, tmp_path ):
    _provision( stocked, tmp_path )
    _sql_of( stocked, "postgres", "GRANT CONNECT ON DATABASE lupin_db_dev TO lupin_test;\nREVOKE CONNECT ON DATABASE lupin_db_test FROM lupin_test;\n" )
    lines = _check( stocked ).stdout.splitlines()
    assert "  lupin_test can CONNECT lupin_db_dev and must not" in lines
    assert "  lupin_test cannot CONNECT lupin_db_test" in lines


@needs_docker
def test_check_fails_on_a_database_with_no_tables( stocked, tmp_path ):
    _provision( stocked, tmp_path )
    names = stocked_tables( "lupin_db_test" )
    assert names, "the fixture stocks no tables, so dropping them proves nothing"
    _sql_of( stocked, "lupin_db_test", f"DROP TABLE {', '.join( names )} CASCADE;\n" )
    done = _check( stocked )
    assert done.returncode == 1 and "lupin_db_test: 0 tables, 3 roles, 1 problems" in done.stdout.splitlines()
    assert "  lupin_db_test has no public tables, so nothing was checked" in done.stdout.splitlines()


@needs_docker
def test_check_names_the_roles_that_do_not_exist_and_asks_for_the_full_provisioning( stocked ):
    done = _check( stocked )
    assert done.returncode == 1
    assert "  role lupin_app does not exist" in done.stdout.splitlines()
    assert "full provisioning" in done.stdout.splitlines()[ -1 ]


@needs_docker
def test_a_plain_login_gets_the_same_answer_as_the_superuser( stocked, tmp_path ):
    _provision( stocked, tmp_path )
    _sql_of( stocked, "lupin_db_test", "REVOKE DELETE ON widgets FROM lupin_app;\n" )
    sql = db_grants.build_check_sql( "lupin_db_test" )
    as_plain = _psql_as( stocked, "lupin_test", "lupin_db_test", sql )
    as_super = _sql_of( stocked, "lupin_db_test", sql ).strip()
    assert as_plain == as_super, "a plain login saw something other than the superuser"
    report = db_grants.evaluate( "lupin_db_test", db_grants.parse_rows( as_plain ) )
    assert report[ "problems" ] == [ ( "missing", "lupin_app", "widgets", "DELETE" ) ]


@needs_docker
def test_check_names_a_sequence_a_role_cannot_use( stocked, tmp_path ):
    _provision( stocked, tmp_path )
    _sql_of( stocked, "lupin_db_dev", "REVOKE ALL ON SEQUENCE widgets_id_seq FROM lupin_app;\n" )
    done = _check( stocked )
    lines = done.stdout.splitlines()
    assert done.returncode == 1
    assert all( f"  lupin_app cannot {p} widgets_id_seq" in lines for p in ( "USAGE", "SELECT", "UPDATE" ) )
    assert _grants_only( stocked ).returncode == 0 and _check( stocked ).returncode == 0


@needs_docker
@pytest.mark.parametrize( "login, database", [ ( "lupin_test", "lupin_db_test" ), ( "lupin_host", "lupin_db_dev" ), ( "lupin_app", "lupin_db_dev" ) ] )
def test_a_plain_login_checks_its_own_database_with_the_database_option( stocked, tmp_path, login, database ):
    _provision( stocked, tmp_path )
    done = _check( stocked, database, login, "--database", database )
    assert done.returncode == 0, done.stdout + done.stderr
    assert done.stdout.splitlines() == [ f"{database}: {len( stocked_tables( database ) )} tables, 3 roles, 0 problems" ]


@needs_docker
def test_a_login_that_cannot_reach_a_database_gets_exit_two_without_the_database_option( stocked, tmp_path ):
    _provision( stocked, tmp_path )
    done = _check( stocked, "lupin_db_test", "lupin_test" )
    assert done.returncode == 2 and "CONNECT privilege" in done.stdout
