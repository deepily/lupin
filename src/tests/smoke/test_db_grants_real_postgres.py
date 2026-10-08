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

from test_db_roles_rollback_real_postgres import (   # noqa: F401  (fixtures are used by name)
    ROLES_SQL, ROOT, SUPERUSER, _assert_marker, _clean_env, _docker, _labels_of, _provision, _psql,
    needs_docker, refuse_unless_throwaway, stocked, throwaway,
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
        _psql_as( stocked, creator, database, f"INSERT INTO {table} DEFAULT VALUES;" )
    # the dev database gives lupin_test nothing, whoever made the table
    assert not _asks( stocked, "lupin_db_dev", "fresh_lupin_dev", "lupin_test", "SELECT" )
