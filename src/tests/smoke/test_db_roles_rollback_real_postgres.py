"""
db_roles --rollback against a real Postgres, in a container made for the test.

The provisioner is run for real, through docker exec, against a throwaway server.
Venue: host-side, docker required; the :7999 rubric applies only if a run is timed under two minutes.
The merge gate's containers have no docker socket, so there the two docker tests skip: read the skip count.
The container is removed afterwards, and a start-of-run sweep removes old leftovers.
"""

# Why a server of its own: roles are cluster-wide, and the provisioner changes owners and
# privileges. On the shared test server that is the live cluster. Here the databases named
# lupin_db_dev and lupin_db_test are copies of nothing.
#
# Three layers keep the test away from the real databases:
#   1. no route: no published port, no shared network, and psql is reached by `docker exec` on the
#      generated container name alone
#   2. a marker: a database that only this container has, checked before every provisioner call
#   3. a name guard: the prefix and the label must both match, and lupin-postgres is refused

import json
import os
import secrets
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest

IMAGE            = "pgvector/pgvector:pg16"
NAME_PREFIX      = "lupin-dbroles-test-"
LABEL            = "lupin.test=db-roles-rollback"
REAL_CONTAINERS  = ( "lupin-postgres", )
RUN_LABEL_KEY    = "lupin.test.run"
RUN_ID           = uuid.uuid4().hex[ :12 ]
SWEEP_MIN_AGE    = timedelta( minutes=30 )
READY_SECONDS    = 90
SUPERUSER        = "lupin_dev"
ROOT             = os.environ.get( "LUPIN_ROOT", "" )


# ── guards, tested without docker ───────────────────────────────────────────

def refuse_unless_throwaway( name, labels ):
    """
    Refuse any container that is not one this test made.

    Requires:
        - name is a container name; labels is a list of "key=value" strings

    Ensures:
        - returns None only when the name has the throwaway prefix and the label is present
        - raises RuntimeError for anything else, including the real database container
    """
    refuse_unless_named_like_a_throwaway( name )
    if LABEL not in labels: raise RuntimeError( f"SAFETY: {name!r} does not carry the label {LABEL!r}" )


def refuse_unless_named_like_a_throwaway( name ):
    """The name half of the guard, checked before any docker command is spent on the name."""
    if name in REAL_CONTAINERS: raise RuntimeError( f"SAFETY: {name} is a real database container" )
    if not name.startswith( NAME_PREFIX ): raise RuntimeError( f"SAFETY: {name!r} does not start with {NAME_PREFIX!r}" )


def removable( name, labels ):
    """Whether the sweep may remove this container: both the name prefix and the label must hold."""
    try:
        refuse_unless_throwaway( name, labels )
    except RuntimeError:
        return False
    return True


def sweepable( name, labels, created, now ):
    """
    Whether the sweep may remove this container now.

    Ensures:
        - requires removable( name, labels )
        - never a container labelled with this run's id
        - never one younger than SWEEP_MIN_AGE, so a peer run's live server survives
    """
    if not removable( name, labels ): return False
    if f"{RUN_LABEL_KEY}={RUN_ID}" in labels: return False
    return now - created >= SWEEP_MIN_AGE


@pytest.mark.parametrize( "name, labels, ok", [
    ( NAME_PREFIX + "abc", [ LABEL ],              True ),
    ( NAME_PREFIX + "abc", [ ],                    False ),
    ( NAME_PREFIX + "abc", [ "other=1" ],          False ),
    ( "lupin-postgres",    [ LABEL ],              False ),
    ( "lupin-rest-test",   [ LABEL ],              False ),
    ( "some-other",        [ ],                    False ),
    ( "x" + NAME_PREFIX,   [ LABEL ],              False ),
] )
def test_the_guard_and_the_sweep_need_both_the_name_prefix_and_the_label( name, labels, ok ):
    assert removable( name, labels ) is ok
    if ok:
        assert refuse_unless_throwaway( name, labels ) is None
    else:
        with pytest.raises( RuntimeError ):
            refuse_unless_throwaway( name, labels )


NOW = datetime( 2026, 1, 1, 12, 0, tzinfo=timezone.utc )


@pytest.mark.parametrize( "labels, age_minutes, expected", [
    ( [ LABEL ],                                          31, True ),
    ( [ LABEL ],                                          30, True ),
    ( [ LABEL ],                                          29, False ),
    ( [ LABEL ],                                           0, False ),
    ( [ LABEL, f"{RUN_LABEL_KEY}={RUN_ID}" ],            600, False ),
    ( [ LABEL, f"{RUN_LABEL_KEY}=somebody-else" ],       600, True ),
    ( [ ],                                               600, False ),
] )
def test_the_sweep_spares_young_containers_and_its_own_run( labels, age_minutes, expected ):
    created = NOW - timedelta( minutes=age_minutes )
    assert sweepable( NAME_PREFIX + "abc", labels, created, NOW ) is expected


def test_the_sweep_never_removes_a_real_container_however_old( ):
    assert sweepable( "lupin-postgres", [ LABEL ], NOW - timedelta( days=9 ), NOW ) is False


def test_the_sweep_removes_with_volumes_only_the_old_labelled_ones( monkeypatch ):
    module = sys.modules[ __name__ ]
    old    = datetime.now( timezone.utc ) - timedelta( hours=3 )
    young  = datetime.now( timezone.utc )
    calls  = [ ]
    def fake_docker( *args, **kwargs ):
        calls.append( args )
        class Done: returncode = 0; stdout = f"{NAME_PREFIX}old {NAME_PREFIX}young {NAME_PREFIX}mine"; stderr = ""
        return Done()
    monkeypatch.setattr( module, "_docker", fake_docker )
    monkeypatch.setattr( module, "_labels_of", lambda n: [ LABEL, f"{RUN_LABEL_KEY}={RUN_ID}" ] if n.endswith( "mine" ) else [ LABEL ] )
    monkeypatch.setattr( module, "_created_of", lambda n: young if n.endswith( "young" ) else old )
    assert sweep_leftovers() == [ NAME_PREFIX + "old" ]
    assert ( "rm", "-fv", NAME_PREFIX + "old" ) in calls
    assert not any( a[ :2 ] == ( "rm", "-fv" ) and a[ 2 ] != NAME_PREFIX + "old" for a in calls )


def test_the_real_database_container_is_refused_before_any_docker_command( monkeypatch ):
    calls = [ ]
    monkeypatch.setattr( sys.modules[ __name__ ], "_docker", lambda *a, **k: calls.append( a ) )
    with pytest.raises( RuntimeError, match="real database container" ):
        _psql( "lupin-postgres", "lupin_db_dev", "SELECT 1;" )
    assert calls == [ ], "a docker command was spent on the real container's name"


def test_an_empty_lupin_root_stops_the_provisioner_before_anything_else( monkeypatch, tmp_path ):
    module = sys.modules[ __name__ ]
    monkeypatch.setattr( module, "ROOT", "" )
    monkeypatch.setattr( module, "_psql", lambda *a, **k: pytest.fail( "a database was asked before LUPIN_ROOT was checked" ) )
    with pytest.raises( AssertionError, match="LUPIN_ROOT is not set" ):
        _provision( { "name": NAME_PREFIX + "x", "marker": "throwaway_marker_x" }, tmp_path )


def test_a_missing_marker_stops_the_provisioner_before_it_runs( monkeypatch, tmp_path ):
    ran = [ ]
    module = sys.modules[ __name__ ]
    monkeypatch.setattr( module, "_psql", lambda *a, **k: "" )
    monkeypatch.setattr( module.subprocess, "run", lambda *a, **k: ran.append( a ) )
    with pytest.raises( AssertionError, match="marker database is missing" ):
        _provision( { "name": NAME_PREFIX + "x", "marker": "throwaway_marker_x" }, tmp_path )
    assert ran == [ ], "the provisioner ran although the marker check failed"


# ── docker plumbing ─────────────────────────────────────────────────────────

def _clean_env( **extra ):
    """A minimal environment, so no database variable from the seat reaches a child."""
    env = { key: os.environ[ key ] for key in ( "PATH", "HOME", "DOCKER_HOST", "DOCKER_CONFIG" ) if key in os.environ }
    env.update( extra )
    return env


def _docker( *args, stdin=None, timeout=120 ):
    return subprocess.run( [ "docker", *args ], input=stdin, capture_output=True, text=True, timeout=timeout, env=_clean_env() )


def _docker_usable():
    if shutil.which( "docker" ) is None: return False
    try:
        return _docker( "info", timeout=20 ).returncode == 0
    except ( subprocess.TimeoutExpired, OSError ):
        return False


needs_docker = pytest.mark.skipif( not _docker_usable(), reason="docker is not usable on this host" )


def _labels_of( name ):
    shown = _docker( "inspect", "--format", "{{json .Config.Labels}}", name )
    assert shown.returncode == 0, shown.stderr
    labels = json.loads( shown.stdout ) or { }
    return [ f"{k}={v}" for k, v in labels.items() ]


def _created_of( name ):
    """When docker made the container, as an aware datetime."""
    shown = _docker( "inspect", "--format", "{{.Created}}", name )
    assert shown.returncode == 0, shown.stderr
    text = shown.stdout.strip()
    return datetime.fromisoformat( text[ :19 ] + "+00:00" )


def sweep_leftovers():
    """Remove old containers that carry the label and the name prefix, and nothing else."""
    listed = _docker( "ps", "-a", "--filter", f"label={LABEL}", "--format", "{{.Names}}" )
    removed = [ ]
    now = datetime.now( timezone.utc )
    for name in listed.stdout.split():
        if sweepable( name, _labels_of( name ), _created_of( name ), now ):
            _docker( "rm", "-fv", name )
            removed.append( name )
    return removed


def _psql( name, database, sql, flags=( "-tA", ) ):
    """Run SQL as the superuser inside the throwaway container; returns stdout."""
    refuse_unless_named_like_a_throwaway( name )
    refuse_unless_throwaway( name, _labels_of( name ) )
    done = _docker( "exec", "-i", name, "psql", "-U", SUPERUSER, "-d", database, "-v", "ON_ERROR_STOP=1", *flags, stdin=sql )
    assert done.returncode == 0, f"psql failed in {database}: {done.stderr}"
    return done.stdout


@pytest.fixture
def throwaway():
    """A fresh Postgres container with the marker database, removed afterwards."""
    sweep_leftovers()
    name   = NAME_PREFIX + uuid.uuid4().hex[ :10 ]
    marker = "throwaway_marker_" + uuid.uuid4().hex[ :10 ]
    image = _docker( "image", "inspect", IMAGE )
    assert image.returncode == 0, f"the image {IMAGE} is not on this host; pull it deliberately, the test will not"
    started = _docker( "run", "-d", "--rm", "--name", name, "--label", LABEL, "--label", f"{RUN_LABEL_KEY}={RUN_ID}",
                       "--memory", "1g", "--cpus", "1",
                       "-e", "POSTGRES_USER=" + SUPERUSER, "-e", "POSTGRES_PASSWORD=" + secrets.token_hex( 16 ),
                       "-e", "POSTGRES_DB=lupin_db_dev", IMAGE )
    assert started.returncode == 0, f"could not start the container: {started.stderr}"
    try:
        deadline = time.monotonic() + READY_SECONDS
        while _docker( "exec", name, "pg_isready", "-U", SUPERUSER, "-d", "lupin_db_dev" ).returncode != 0:
            assert time.monotonic() < deadline, "the throwaway Postgres did not become ready"
            time.sleep( 0.5 )
        # The official image restarts once after its init scripts; wait for a query to work twice.
        for _ in range( 2 ):
            while _docker( "exec", name, "psql", "-U", SUPERUSER, "-d", "lupin_db_dev", "-tAc", "SELECT 1" ).returncode != 0:
                assert time.monotonic() < deadline, "the throwaway Postgres did not accept queries"
                time.sleep( 0.5 )
        _psql( name, "postgres", f"CREATE DATABASE {marker};\nCREATE DATABASE lupin_db_test;\n" )
        yield { "name": name, "marker": marker }
    finally:
        _docker( "rm", "-fv", name )


def _assert_marker( box ):
    """The target must hold the marker database that only this test creates."""
    found = _psql( box[ "name" ], "postgres", f"SELECT 1 FROM pg_database WHERE datname = '{box[ 'marker' ]}';\n" ).strip()
    assert found == "1", "SAFETY: the marker database is missing, so this is not the throwaway server"


# ── fixture objects and snapshots ───────────────────────────────────────────

FIXTURE_SQL = """
CREATE TABLE widgets ( id serial PRIMARY KEY, note text );
CREATE TABLE gadgets ( id bigserial PRIMARY KEY );
CREATE SEQUENCE standalone_seq;
CREATE VIEW widget_view AS SELECT id FROM widgets;
CREATE MATERIALIZED VIEW widget_mat AS SELECT id FROM widgets;
CREATE TYPE mood AS ENUM ( 'ok', 'bad' );
CREATE DOMAIN positive_int AS integer CHECK ( VALUE > 0 );
CREATE FUNCTION add_one( x integer ) RETURNS integer LANGUAGE sql AS 'SELECT x + 1';
CREATE PROCEDURE do_nothing( x integer ) LANGUAGE sql AS 'SELECT 1';
"""

VECTOR_SQL = "CREATE EXTENSION IF NOT EXISTS vector;\nCREATE TABLE vecs ( id serial PRIMARY KEY, v vector(3) );\n"

OWNERS_SQL = """
SELECT 'rel|' || c.relkind::text || '|' || c.relname || '|' || o.rolname
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace JOIN pg_roles o ON o.oid = c.relowner
 WHERE n.nspname = 'public' AND c.relkind IN ( 'r', 'S', 'v', 'm' )
UNION ALL
SELECT 'type|' || t.typtype::text || '|' || t.typname || '|' || o.rolname
  FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace JOIN pg_roles o ON o.oid = t.typowner
 WHERE n.nspname = 'public' AND t.typtype IN ( 'e', 'd' )
UNION ALL
SELECT 'proc|' || p.prokind::text || '|' || p.proname || '|' || o.rolname
  FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace JOIN pg_roles o ON o.oid = p.proowner
 WHERE n.nspname = 'public'
   AND NOT EXISTS ( SELECT FROM pg_depend d WHERE d.classid = 'pg_proc'::regclass AND d.objid = p.oid AND d.deptype = 'e' )
UNION ALL
SELECT 'schema|' || n.nspname || '|' || o.rolname FROM pg_namespace n JOIN pg_roles o ON o.oid = n.nspowner WHERE n.nspname = 'public'
UNION ALL
SELECT 'database|' || d.datname || '|' || o.rolname FROM pg_database d JOIN pg_roles o ON o.oid = d.datdba WHERE d.datname = current_database()
ORDER BY 1;
"""

ROLES_SQL = ( "SELECT rolname || '|' || rolcanlogin || '|' || rolsuper || '|' || rolcreatedb || '|' || coalesce( rolpassword, '' ) "
              "FROM pg_authid WHERE rolname LIKE 'lupin_%' ORDER BY 1;\n" )
DEFACL_SQL  = "SELECT defaclrole::regrole || '|' || defaclnamespace::regnamespace || '|' || defaclobjtype::text || '|' || defaclacl::text FROM pg_default_acl ORDER BY 1;\n"
EXT_SQL     = "SELECT proowner::regrole FROM pg_proc WHERE proname = 'vector_in';\n"


def _snapshot( box ):
    """Owners, roles with password hashes, default privileges and the extension owner."""
    name = box[ "name" ]
    return {
        "dev_owners"   : _psql( name, "lupin_db_dev",  OWNERS_SQL ),
        "test_owners"  : _psql( name, "lupin_db_test", OWNERS_SQL ),
        "roles"        : _psql( name, "postgres",      ROLES_SQL ),
        "dev_defacl"   : _psql( name, "lupin_db_dev",  DEFACL_SQL ),
        "test_defacl"  : _psql( name, "lupin_db_test", DEFACL_SQL ),
        "vector_owner" : _psql( name, "lupin_db_dev",  EXT_SQL ),
    }


def _provision( box, tmp_path, *flags, database="lupin_db_dev" ):
    """Run the real provisioner against the throwaway container; returns the finished process."""
    assert ROOT, "LUPIN_ROOT is not set, so the provisioner would run from the wrong tree"
    _assert_marker( box )
    files = { }
    for role in ( "app", "host", "test" ):
        path = tmp_path / f"{role}_pw"
        path.write_text( secrets.token_hex( 16 ) )
        path.chmod( 0o600 )
        files[ role ] = str( path )
    psql = f"docker exec -i {box[ 'name' ]} psql -U {SUPERUSER} -d {database}"
    args = [ sys.executable, "-m", "cosa.utils.db_roles", "--psql", psql, "--apply", *flags ]
    if "--rollback" not in flags:
        args += [ "--app-pw-file", files[ "app" ], "--host-pw-file", files[ "host" ], "--test-pw-file", files[ "test" ] ]
    env = _clean_env( LUPIN_ROOT=ROOT, PYTHONPATH=os.path.join( ROOT, "src" ) )
    done = subprocess.run( args, capture_output=True, text=True, timeout=120, env=env, cwd=ROOT )
    assert done.returncode == 0, f"provisioner {flags} failed: {done.stdout[ -500: ]} {done.stderr[ -500: ]}"
    return done


@pytest.fixture
def stocked( throwaway ):
    """The throwaway server with the same objects in both databases, and vector in dev."""
    for database in ( "lupin_db_dev", "lupin_db_test" ):
        _psql( throwaway[ "name" ], database, FIXTURE_SQL )
    _psql( throwaway[ "name" ], "lupin_db_dev", VECTOR_SQL )
    return throwaway


def _owners( text ):
    return [ line for line in text.splitlines() if line ]


def _changed( before, after, key ):
    return before[ key ] != after[ key ]


# ── the tests ───────────────────────────────────────────────────────────────

@needs_docker
def test_a_rollback_after_a_reassign_returns_every_owner_and_touches_no_role( stocked, tmp_path ):
    started = time.perf_counter()
    s0 = _snapshot( stocked )
    assert all( line.endswith( "|lupin_dev" ) or line.endswith( "|pg_database_owner" ) for line in _owners( s0[ "dev_owners" ] ) )

    _provision( stocked, tmp_path )
    s1 = _snapshot( stocked )
    _provision( stocked, tmp_path, "--reassign" )
    s2 = _snapshot( stocked )
    reassigned = _owners( s2[ "dev_owners" ] )
    assert any( line == "rel|r|widgets|lupin_app" for line in reassigned ), "the reassign did not move the table; the rollback has nothing to undo"
    assert "schema|public|lupin_app" in reassigned and "database|lupin_db_dev|lupin_app" in reassigned
    assert s2[ "vector_owner" ].strip() == SUPERUSER, "the reassign must leave extension objects alone"

    _provision( stocked, tmp_path, "--rollback" )
    s3 = _snapshot( stocked )
    _provision( stocked, tmp_path, "--rollback" )
    s4 = _snapshot( stocked )

    assert s3[ "dev_owners" ] == s0[ "dev_owners" ], "the rollback did not return every owner in the dev database"
    assert "schema|public|pg_database_owner" in _owners( s3[ "dev_owners" ] )
    assert f"database|lupin_db_dev|{SUPERUSER}" in _owners( s3[ "dev_owners" ] )
    for key in ( "roles", "dev_defacl", "test_defacl", "test_owners", "vector_owner" ):
        assert s3[ key ] == s2[ key ], f"the rollback changed {key}"
    assert s4 == s3, "a second rollback changed something"
    assert _changed( s0, s1, "roles"), "the provisioner created no roles, so the role comparison above proves nothing"
    print( f"[db-roles-rollback] elapsed {time.perf_counter() - started:.1f}s" )


@needs_docker
def test_a_rollback_after_provisioning_only_changes_no_owner( stocked, tmp_path ):
    _provision( stocked, tmp_path )
    before = _snapshot( stocked )
    _provision( stocked, tmp_path, "--rollback" )
    after = _snapshot( stocked )
    assert after == before, "a rollback with no reassign behind it changed something"


@needs_docker
def test_a_rollback_leaves_a_database_and_schema_owned_by_a_third_role( stocked, tmp_path ):
    _provision( stocked, tmp_path )
    _psql( stocked[ "name" ], "postgres", "ALTER DATABASE lupin_db_dev OWNER TO lupin_host;\n" )
    _psql( stocked[ "name" ], "lupin_db_dev", "ALTER SCHEMA public OWNER TO lupin_host;\n" )
    before = _owners( _snapshot( stocked )[ "dev_owners" ] )
    assert "database|lupin_db_dev|lupin_host" in before and "schema|public|lupin_host" in before, "the setup did not hand both to the third role"
    _provision( stocked, tmp_path, "--rollback" )
    assert _owners( _snapshot( stocked )[ "dev_owners" ] ) == before, "a rollback moved a database or schema that lupin_app does not own"


@needs_docker
def test_a_rollback_started_on_another_database_still_returns_the_dev_owners( stocked, tmp_path ):
    _provision( stocked, tmp_path )
    before = _owners( _snapshot( stocked )[ "dev_owners" ] )
    _provision( stocked, tmp_path, "--reassign" )
    _provision( stocked, tmp_path, "--rollback", database="postgres" )
    assert _owners( _snapshot( stocked )[ "dev_owners" ] ) == before, "the rollback acted on the database it started in, not lupin_db_dev"
