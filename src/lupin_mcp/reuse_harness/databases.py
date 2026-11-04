"""
The throwaway databases of the run harness: one per run, cloned from a template.

A run's database is dropped when the run ends.

The server migrates an empty database on boot, so a clone of the template is all a run needs. The template carries the
vector extension, which a login that may not install extensions cannot add itself.
"""
import os

import bcrypt
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError, OperationalError, ProgrammingError
from sqlalchemy.orm import Session

import cosa.utils.dotenv_password as dp
from cosa.rest.postgres_models import ApiKey, User
from lupin_mcp.reuse_harness import errors as err

TEMPLATE_NAME = "lupin_template_vector"
SENDER_EMAIL  = "exp-key-owner@lupin.deepily.ai"
SENDER_ROLES  = [ "service_account" ]
BCRYPT_ROUNDS = 12

# A run's database counts as fresh when no account and no notification exists yet. Other tables hold rows the server seeds at boot.
FRESH_TABLES  = ( "users", "notifications" )

_TERMINATE    = ( "SELECT pg_terminate_backend( pid ) FROM pg_stat_activity "
                  "WHERE datname = :n AND pid <> pg_backend_pid() AND backend_type = 'client backend' AND usename = current_user" )


def maintenance_url( environ=None, login=dp.clone_login ):
    """
    Build the URL of the server's maintenance database, logged in as the test role.

    Requires:
        - environ, when given, maps DB_HOST and DB_PORT; defaults are localhost and 5432
        - login returns ( user, password ) or None

    Ensures:
        - the URL names the database postgres, never a Lupin database

    Raises:
        - HarnessError DB_UNAVAILABLE if no test login exists, because the harness never uses the dev or prod login
    """
    environ = os.environ if environ is None else environ
    found   = login()
    if found is None: raise err.HarnessError( err.DB_UNAVAILABLE, "no test-role login: set LUPIN_TEST_DB_USER and LUPIN_TEST_DB_PASSWORD" )
    return make_url( "postgresql+psycopg2://" ).set( username=found[ 0 ], password=found[ 1 ], host=environ.get( "DB_HOST", "localhost" ),
                                                    port=int( environ.get( "DB_PORT", "5432" ) ), database="postgres" ).render_as_string( hide_password=False )


class Databases:
    """Creates, inspects and drops the databases of runs on one Postgres server."""

    def __init__( self, server_url, engine_factory=create_engine, session_class=Session ):
        """
        Remember the server and how to open an engine.

        Requires:
            - server_url names the maintenance database of a provisioned server

        Ensures:
            - nothing is connected yet
        """
        self.server_url     = server_url
        self.engine_factory = engine_factory
        self.session_class  = session_class

    def create( self, name ):
        """
        Clone the vector template into a new database.

        Requires:
            - name is a lowercase identifier of letters, digits and underscores

        Ensures:
            - the database exists and holds the template's contents only

        Raises:
            - HarnessError BAD_SPEC for an unsafe name
            - HarnessError DB_UNAVAILABLE if the template is missing, the login may not create databases, or the server refuses
        """
        self._check_name( name )
        engine = self.engine_factory( self.server_url, isolation_level="AUTOCOMMIT" )
        try:
            with engine.connect() as conn: conn.execute( text( f"CREATE DATABASE {name} TEMPLATE {TEMPLATE_NAME}" ) )
        except ( ProgrammingError, OperationalError ) as error:
            raise err.HarnessError( err.DB_UNAVAILABLE, f"could not create {name} from {TEMPLATE_NAME}: {error.orig}" ) from error
        finally:
            engine.dispose()

    def drop( self, name ):
        """
        Close the database's sessions and drop it.

        Requires:
            - name is a lowercase identifier of letters, digits and underscores

        Ensures:
            - the database is gone; one already gone is not an error
            - only sessions of the harness's own role are closed

        Raises:
            - HarnessError BAD_SPEC for an unsafe name
            - HarnessError DB_UNAVAILABLE if the server refuses, or a session of another role holds the database
        """
        self._check_name( name )
        engine = self.engine_factory( self.server_url, isolation_level="AUTOCOMMIT" )
        try:
            with engine.connect() as conn:
                conn.execute( text( _TERMINATE ), { "n" : name } )
                conn.execute( text( f"DROP DATABASE IF EXISTS {name}" ) )
        except ( ProgrammingError, OperationalError ) as error:
            raise err.HarnessError( err.DB_UNAVAILABLE, f"could not drop {name}: {error.orig}" ) from error
        finally:
            engine.dispose()

    def is_fresh( self, name ):
        """
        Say whether the database holds no account and no notification.

        Requires:
            - the server has migrated the database

        Ensures:
            - true exactly when every table of FRESH_TABLES has zero rows

        Raises:
            - HarnessError DB_UNAVAILABLE if a table is missing or the database cannot be read
        """
        self._check_name( name )
        engine = self.engine_factory( make_url( self.server_url ).set( database=name ).render_as_string( hide_password=False ) )
        try:
            with engine.connect() as conn: counts = [ conn.execute( text( f"SELECT count(*) FROM {table}" ) ).scalar() for table in FRESH_TABLES ]
        except ( ProgrammingError, OperationalError ) as error:
            raise err.HarnessError( err.DB_UNAVAILABLE, f"could not count rows in {name}: {error.orig}" ) from error
        finally:
            engine.dispose()
        return all( count == 0 for count in counts )

    def provision_sender_key( self, name, key ):
        """
        Give the database an account that owns the sender key; only the key's hash is stored.

        Requires:
            - the server has migrated the database
            - key is the plaintext key the tests send in X-API-Key

        Ensures:
            - one service account and one active api_keys row exist, so the server accepts the key
            - the plaintext key is not stored
            - the account is created after the freshness check, so it never counts against it

        Raises:
            - HarnessError DB_UNAVAILABLE if the tables are missing, the rows exist already or the database cannot be written
        """
        self._check_name( name )
        engine = self.engine_factory( make_url( self.server_url ).set( database=name ).render_as_string( hide_password=False ) )
        try:
            with self.session_class( engine ) as session:
                owner = User( email=SENDER_EMAIL, password_hash="!", roles=SENDER_ROLES, is_active=True, email_verified=True )
                session.add( owner )
                session.flush()
                session.add( ApiKey( user_id=owner.id, key_hash=bcrypt.hashpw( key.encode( "utf-8" ), bcrypt.gensalt( rounds=BCRYPT_ROUNDS ) ).decode( "utf-8" ),
                                     description="experiment sender key", is_active=True ) )
                session.commit()
        except ( ProgrammingError, OperationalError, IntegrityError ) as error:
            raise err.HarnessError( err.DB_UNAVAILABLE, f"could not provision the sender key in {name}: {error.orig}" ) from error
        finally:
            engine.dispose()

    def _check_name( self, name ):
        """Refuse a name that is not a plain lowercase identifier, because it goes into SQL text."""
        if not ( name.replace( "_", "" ).isalnum() and name == name.lower() and name.isascii() ): raise err.HarnessError( err.BAD_SPEC, f"unsafe database name {name!r}" )
