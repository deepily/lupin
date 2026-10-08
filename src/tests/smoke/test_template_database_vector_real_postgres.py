"""
A template database holding pgvector lets a plain login create vector databases.

Pocholo wrote this as a probe and it is taken in here as a test. It runs the real provisioner, which makes
the template, in a throwaway Postgres made for the test. Three arms follow.

1. lupin_test clones the template, then uses a vector(3) column. It succeeds.
2. Control: lupin_test makes a database without the template, then asks for the extension. Postgres refuses it.
3. lupin_host cannot create a database, even from the template.

It reuses the throwaway harness of test_db_roles_rollback_real_postgres.py: the same container guards and marker
database. The roles carry the attributes init-db-roles.sql gives them: lupin_test may create databases,
lupin_host may not, and neither is a superuser.
Venue: host-side, docker required. The merge gate's containers have no docker socket, so there it skips.
"""

import pytest

from test_db_roles_rollback_real_postgres import (   # noqa: F401  (fixtures are used by name)
    SUPERUSER, _assert_marker, _docker, _labels_of, _provision, _psql, needs_docker,
    refuse_unless_throwaway, throwaway,
)

TEMPLATE = "lupin_template_vector"


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


def _ok( box, role, database, sql ):
    """Like _as, but the statement must succeed; returns stdout."""
    code, out, err = _as( box, role, database, sql )
    assert code == 0, f"{role} in {database} failed: {err}"
    return out


@pytest.fixture
def provisioned( throwaway, tmp_path ):
    """The throwaway server after the real provisioner ran: three roles and the vector template."""
    _provision( throwaway, tmp_path )
    _assert_marker( throwaway )
    name = throwaway[ "name" ]
    # The roles must carry the attributes the arms depend on; read them, do not assume them.
    attrs = _psql( name, "postgres", "SELECT rolname || '|' || rolcreatedb || '|' || rolsuper FROM pg_roles WHERE rolname IN ( 'lupin_test', 'lupin_host' ) ORDER BY 1;\n" )
    assert attrs.splitlines() == [ "lupin_host|false|false", "lupin_test|true|false" ], f"the provisioned roles are not the ones this probe is about: {attrs!r}"
    flags = _psql( name, "postgres", f"SELECT datistemplate || '|' || datallowconn FROM pg_database WHERE datname = '{TEMPLATE}';\n" ).strip()
    assert flags == "true|false", f"the template is not marked as a template that refuses connections: {flags!r}"
    return throwaway


@needs_docker
def test_arm1_lupin_test_clones_the_template_and_uses_a_vector_column( provisioned ):
    cloned = _as( provisioned, "lupin_test", "postgres", f"CREATE DATABASE t1 TEMPLATE {TEMPLATE};\n" )
    assert cloned[ 0 ] == 0, f"the clone was refused: {cloned[ 2 ]}"
    assert _ok( provisioned, "lupin_test", "t1", "SELECT extname FROM pg_extension WHERE extname = 'vector';\n" ) == "vector", "the clone does not carry the extension"
    again = _as( provisioned, "lupin_test", "t1", "CREATE EXTENSION IF NOT EXISTS vector;\n" )
    assert again[ 0 ] == 0, f"IF NOT EXISTS was refused in the clone: {again[ 2 ]}"
    _ok( provisioned, "lupin_test", "t1", "CREATE TABLE vecs ( id serial PRIMARY KEY, v vector(3) );\nINSERT INTO vecs ( v ) VALUES ( '[1,2,3]' );\n" )
    assert _ok( provisioned, "lupin_test", "t1", "SELECT v FROM vecs;\n" ) == "[1,2,3]"
    owner = _ok( provisioned, "lupin_test", "postgres", "SELECT pg_get_userbyid( datdba ) FROM pg_database WHERE datname = 't1';\n" )
    assert owner == "lupin_test", f"the clone is owned by {owner}, so alembic and create_all would not own their tables"


@needs_docker
def test_arm2_control_without_the_template_lupin_test_is_refused_the_extension( provisioned ):
    made = _as( provisioned, "lupin_test", "postgres", "CREATE DATABASE t2;\n" )
    assert made[ 0 ] == 0, f"the plain database was refused, so the control never reached the wall: {made[ 2 ]}"
    code, _out, err = _as( provisioned, "lupin_test", "t2", "CREATE EXTENSION vector;\n" )
    assert code != 0 and 'permission denied to create extension "vector"' in err, f"the wall was not seen: code={code} err={err!r}"
    # Positive control: the same statement, same database, by the superuser, works; so the refusal above is the login, not the database.
    assert _as( provisioned, SUPERUSER, "t2", "CREATE EXTENSION vector;\n" )[ 0 ] == 0


@needs_docker
def test_arm3_lupin_host_cannot_create_a_database_even_from_the_template( provisioned ):
    code, _out, err = _as( provisioned, "lupin_host", "postgres", f"CREATE DATABASE t3 TEMPLATE {TEMPLATE};\n" )
    assert code != 0 and "permission denied to create database" in err, f"the wall was not seen: code={code} err={err!r}"
    exists = _psql( provisioned[ "name" ], "postgres", "SELECT count(*) FROM pg_database WHERE datname = 't3';\n" ).strip()
    assert exists == "0", "the refused statement left a database behind"
