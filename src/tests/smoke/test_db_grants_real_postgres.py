"""
db_roles grants against a real Postgres, in a container made for the test.

Reuses the throwaway harness of test_db_roles_rollback_real_postgres.py: the same container guards,
the same marker database, the same provisioner call. Nothing here can reach lupin_db_dev or
lupin_db_test on the real server.
Venue: host-side, docker required; the :7999 rubric applies only if a run is timed under two minutes.
The merge gate's containers have no docker socket, so there the docker tests skip: read the skip count.
"""

from test_db_roles_rollback_real_postgres import (   # noqa: F401  (fixtures are used by name)
    _docker, _labels_of, _provision, needs_docker, refuse_unless_throwaway, stocked, throwaway,
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
