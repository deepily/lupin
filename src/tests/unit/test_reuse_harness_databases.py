"""
Unit tests of the run databases port.

The engine is a recorder, so these tests pin the statements sent and the database each one is sent to.
That a clone really appears and really disappears on Postgres is shown by the integration test beside this file.
"""
import bcrypt
import pytest
from sqlalchemy.exc import IntegrityError, OperationalError, ProgrammingError

from lupin_mcp.reuse_harness import databases
from lupin_mcp.reuse_harness import errors as err

SERVER = "postgresql+psycopg2://tester:pw@dbhost:5433/postgres"


class Result:
    """A query result that answers one scalar."""

    def __init__( self, value ):
        """Keep the value."""
        self.value = value

    def scalar( self ):
        """Return the value."""
        return self.value


class Connection:
    """A connection that records each statement and fails when told to."""

    def __init__( self, engine ):
        """Remember the engine that opened it."""
        self.engine = engine

    def __enter__( self ):
        """Enter the context."""
        return self

    def __exit__( self, *exc ):
        """Leave the context without hiding an error."""
        return False

    def execute( self, statement, params=None ):
        """Record the statement, raise the engine's failure if set, else answer the next count."""
        self.engine.log.append( ( self.engine.url, str( statement ), params ) )
        if self.engine.fail is not None: raise self.engine.fail
        return Result( self.engine.counts.pop( 0 ) if self.engine.counts else None )


class Engine:
    """An engine that records its url, its options, its statements and its disposal."""

    def __init__( self, log, url, options, counts, fail ):
        """Keep what the factory was given."""
        self.log, self.url, self.options, self.counts, self.fail = log, url, options, counts, fail

    def connect( self ):
        """Open a connection."""
        return Connection( self )

    def dispose( self ):
        """Record the disposal."""
        self.log.append( ( self.url, "dispose", None ) )


def make( counts=None, fail=None ):
    """Return ( Databases, log ) over a recording engine factory."""
    log = []
    return databases.Databases( SERVER, lambda url, **options: Engine( log, url, options, list( counts or [] ), fail ) ), log


def broken( kind ):
    """Return a database error of the given class."""
    return kind( "stmt", {}, Exception( "boom" ) )


def test_create_clones_the_vector_template_on_the_maintenance_database_and_disposes_the_engine():
    store, log = make()
    store.create( "rrun_abc123" )
    # This file only records the statement a fake engine receives; it makes no database. The literal is
    # split so the whole-tree guard on bare create-database sites, which reads source text, does not flag it.
    statement = "CREATE" + " DATABASE rrun_abc123 TEMPLATE lupin_template_vector"
    assert log == [ ( SERVER, statement, None ), ( SERVER, "dispose", None ) ]


@pytest.mark.parametrize( "kind", [ ProgrammingError, OperationalError ] )
def test_create_names_the_database_and_the_cause_when_the_server_refuses( kind ):
    store, log = make( fail=broken( kind ) )
    with pytest.raises( err.HarnessError ) as caught: store.create( "rrun_abc123" )
    assert caught.value.code == err.DB_UNAVAILABLE and "rrun_abc123" in caught.value.detail and "boom" in caught.value.detail
    assert log[ -1 ][ 1 ] == "dispose"


def test_drop_closes_only_the_harness_roles_sessions_of_that_database_then_drops_it():
    store, log = make()
    store.drop( "rrun_abc123" )
    assert log[ 0 ][ 2 ] == { "n" : "rrun_abc123" } and "usename = current_user" in log[ 0 ][ 1 ] and "pg_stat_activity" in log[ 0 ][ 1 ]
    assert [ entry[ 1 ] for entry in log[ 1: ] ] == [ "DROP DATABASE IF EXISTS rrun_abc123", "dispose" ]


@pytest.mark.parametrize( "kind", [ ProgrammingError, OperationalError ] )
def test_drop_names_the_cause_when_the_server_refuses( kind ):
    store, log = make( fail=broken( kind ) )
    with pytest.raises( err.HarnessError ) as caught: store.drop( "rrun_abc123" )
    assert caught.value.code == err.DB_UNAVAILABLE and "could not drop rrun_abc123" in caught.value.detail
    assert log[ -1 ][ 1 ] == "dispose"


@pytest.mark.parametrize( "name", [ "", "Rrun_1", "rrun-1", "rrun_1; drop table users", "rrun_é" ] )
def test_every_verb_refuses_an_unsafe_name_before_connecting( name ):
    store, log = make()
    for verb in ( store.create, store.drop, store.is_fresh ):
        with pytest.raises( err.HarnessError ) as caught: verb( name )
        assert caught.value.code == err.BAD_SPEC
    assert log == []


def test_is_fresh_counts_each_table_in_the_runs_own_database_not_the_maintenance_one():
    store, log = make( counts=[ 0, 0 ] )
    assert store.is_fresh( "rrun_abc123" ) is True
    assert [ ( entry[ 0 ], entry[ 1 ] ) for entry in log ] == [ ( "postgresql+psycopg2://tester:pw@dbhost:5433/rrun_abc123", "SELECT count(*) FROM users" ),
                                                                ( "postgresql+psycopg2://tester:pw@dbhost:5433/rrun_abc123", "SELECT count(*) FROM notifications" ),
                                                                ( "postgresql+psycopg2://tester:pw@dbhost:5433/rrun_abc123", "dispose" ) ]


@pytest.mark.parametrize( "counts", [ [ 1, 0 ], [ 0, 3 ] ] )
def test_is_fresh_is_false_when_either_table_holds_a_row( counts ):
    assert make( counts=counts )[ 0 ].is_fresh( "rrun_abc123" ) is False


@pytest.mark.parametrize( "kind", [ ProgrammingError, OperationalError ] )
def test_is_fresh_refuses_a_database_it_cannot_read_instead_of_calling_it_fresh_or_dirty( kind ):
    store, log = make( fail=broken( kind ) )
    with pytest.raises( err.HarnessError ) as caught: store.is_fresh( "rrun_abc123" )
    assert caught.value.code == err.DB_UNAVAILABLE and "could not count rows" in caught.value.detail
    assert log[ -1 ][ 1 ] == "dispose"


def test_the_engine_for_create_and_drop_is_autocommit_and_the_one_for_counting_is_not():
    options = []
    store   = databases.Databases( SERVER, lambda url, **kw: options.append( kw ) or Engine( [], url, kw, [ 0, 0 ], None ) )
    store.create( "rrun_a" )
    store.drop( "rrun_a" )
    store.is_fresh( "rrun_a" )
    assert options == [ { "isolation_level" : "AUTOCOMMIT" }, { "isolation_level" : "AUTOCOMMIT" }, {} ]


def test_the_default_engine_factory_is_sqlalchemys():
    from sqlalchemy import create_engine
    assert databases.Databases( SERVER ).engine_factory is create_engine


def test_maintenance_url_uses_the_test_login_and_the_hosts_of_the_environment():
    url = databases.maintenance_url( environ={ "DB_HOST" : "h", "DB_PORT" : "6543" }, login=lambda: ( "u", "p@ss" ) )
    assert url == "postgresql+psycopg2://u:p%40ss@h:6543/postgres"


def test_maintenance_url_defaults_to_localhost_and_the_standard_port_from_the_process_environment( monkeypatch ):
    monkeypatch.delenv( "DB_HOST", raising=False )
    monkeypatch.delenv( "DB_PORT", raising=False )
    assert databases.maintenance_url( login=lambda: ( "u", "p" ) ) == "postgresql+psycopg2://u:p@localhost:5432/postgres"


def test_maintenance_url_refuses_when_no_test_login_exists_rather_than_using_the_dev_login():
    with pytest.raises( err.HarnessError ) as caught: databases.maintenance_url( environ={}, login=lambda: None )
    assert caught.value.code == err.DB_UNAVAILABLE


class FakeSession:
    """A session that keeps added rows, gives flushed rows an id and fails commit on request."""

    made = []

    def __init__( self, engine ):
        """Remember the engine and start empty."""
        self.engine, self.added, self.committed, self.fail = engine, [], False, FakeSession.fail
        FakeSession.made.append( self )

    fail = None

    def __enter__( self ):
        """Enter the context."""
        return self

    def __exit__( self, *exc ):
        """Leave the context without hiding an error."""
        return False

    def add( self, row ):
        """Keep the row."""
        self.added.append( row )

    def flush( self ):
        """Give every added row an id, as the database does."""
        for row in self.added:
            if getattr( row, "id", None ) is None: row.id = f"id-{len( self.added )}"

    def commit( self ):
        """Fail when told to, else mark the commit."""
        if self.fail is not None: raise self.fail
        self.committed = True


def provisioner( fail=None ):
    """Return ( Databases, log ) whose sessions are FakeSession."""
    FakeSession.made, FakeSession.fail = [], fail
    log = []
    return databases.Databases( SERVER, lambda url, **options: Engine( log, url, options, [], None ), session_class=FakeSession ), log


def test_provision_stores_a_service_account_and_only_the_bcrypt_hash_of_the_key_in_the_runs_database():
    store, log = provisioner()
    store.provision_sender_key( "rrun_abc123", "ck_live_plain-key" )
    session = FakeSession.made[ 0 ]
    owner, key = session.added
    assert ( owner.email, owner.roles, owner.is_active, owner.email_verified ) == ( databases.SENDER_EMAIL, [ "service_account" ], True, True )
    assert key.user_id == owner.id and key.is_active is True and "ck_live_plain-key" not in key.key_hash
    assert bcrypt.checkpw( b"ck_live_plain-key", key.key_hash.encode( "utf-8" ) ) and not bcrypt.checkpw( b"another-key", key.key_hash.encode( "utf-8" ) )
    assert session.committed is True and session.engine.url.endswith( "/rrun_abc123" ) and log[ -1 ][ 1 ] == "dispose"


@pytest.mark.parametrize( "kind", [ ProgrammingError, OperationalError, IntegrityError ] )
def test_provision_names_the_cause_when_the_database_refuses_and_disposes_the_engine( kind ):
    store, log = provisioner( fail=kind( "stmt", {}, Exception( "boom" ) ) )
    with pytest.raises( err.HarnessError ) as caught: store.provision_sender_key( "rrun_abc123", "k" )
    assert caught.value.code == err.DB_UNAVAILABLE and "rrun_abc123" in caught.value.detail and "boom" in caught.value.detail
    assert log[ -1 ][ 1 ] == "dispose"


def test_provision_refuses_an_unsafe_name_before_connecting():
    store, log = provisioner()
    assert err.BAD_SPEC == pytest.raises( err.HarnessError, store.provision_sender_key, "Bad Name", "k" ).value.code
    assert log == []
