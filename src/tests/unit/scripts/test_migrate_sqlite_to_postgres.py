"""
The SQLite-to-PostgreSQL auth migration, covered with a real SQLite and no PostgreSQL.

Row `8df164c6` — `src/scripts/migrate-sqlite-to-postgres.py`, 136 statements at zero.

🔴 HOW THIS DASHED SCRIPT IS IMPORTED, written out because the next seat down the dashed-filename
list will copy it. `migrate-sqlite-to-postgres` is not a legal Python identifier, so there is no
bare `import`. It is loaded BY PATH:

    spec = importlib.util.spec_from_file_location( "migrate_sqlite_to_postgres", <abs path> )
    mod  = importlib.util.module_from_spec( spec )
    sys.modules[ spec.name ] = mod          # register BEFORE exec_module
    spec.loader.exec_module( mod )

Three things about that recipe are deliberate:
· The module is registered in `sys.modules` under its underscored name BEFORE `exec_module`, so
  anything that looks itself up during import resolves, and a second test file loading the same
  script gets the same object rather than a rival copy.
· `src/scripts/` is NEVER put on `sys.path`. That is the difference from the two ramp files
  before this one, and it is the point: `src/scripts/` holds modules whose names collide with
  real packages, so adding it to the path can shadow them for the whole session (Krishna, row
  c89cec9b). Loading by path imports exactly one file and shadows nothing.
· `src/` alone still goes on `sys.path`, because the script imports `cosa`.

WHAT THIS FILE IS CAREFUL ABOUT:

· 🔴 NO POSTGRESQL. `get_db` is stopped at the MODULE attribute and the session is a recorder, so
  a missed patch is an error rather than a write into `lupin_db_dev` — the box a host shell
  silently reaches (CLAUDE.md § TESTING VENUES). Nothing here can commit anything anywhere.
· ✅ THE SQLITE SIDE IS REAL, and deliberately so. It is stdlib and in-process — no socket, no
  container, no server — so there is no reason to fake it, and faking it would be weaker: real
  `sqlite3.Row`, real `SELECT *` column sets, real SQL filtering. A stubbed cursor could not show
  that the `revoked = 0 AND expires_at > ?` clause actually excludes anything.
· ✅ THE ORM MODELS ARE REAL TOO. `User`, `RefreshToken`, `ApiKey` and `AuthAuditLog` construct
  fine without a connection, so the INTEGER→BOOLEAN and TEXT→datetime conversions are asserted on
  the objects the migration would really have added.
· Every database file lives under `tmp_path`; `SQLITE_DB_PATH` is patched for every test that
  reaches it.

Each test names the change that reddens it.
"""

import importlib.util
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

import pytest


# ── the by-path load (see the module docstring) ───────────────────────────────────────────

_ROOT   = os.environ.get( "LUPIN_ROOT", os.getcwd() )
_SRC    = os.path.join( _ROOT, "src" )
if _SRC not in sys.path:
    sys.path.insert( 0, _SRC )

_SCRIPT = os.path.join( _ROOT, "src", "scripts", "migrate-sqlite-to-postgres.py" )
_SPEC   = importlib.util.spec_from_file_location( "migrate_sqlite_to_postgres", _SCRIPT )
mod     = importlib.util.module_from_spec( _SPEC )
sys.modules[ _SPEC.name ] = mod
_SPEC.loader.exec_module( mod )


ALL_TABLES = [
    "users", "refresh_tokens", "api_keys", "auth_audit_log",
    "email_verification_tokens", "password_reset_tokens", "failed_login_attempts",
]


# ── doubles: the PostgreSQL half only ─────────────────────────────────────────────────────

class _Session:
    """Records what the migration would have added, and whether it committed."""

    def __init__( self ):
        self.added     = [ ]
        self.commits   = 0

    def add( self, obj ):
        self.added.append( obj )

    def commit( self ):
        self.commits += 1

    def of_type( self, name ):
        return [ o for o in self.added if type( o ).__name__ == name ]


class _Db:
    """`get_db()` used as a context manager."""

    def __init__( self ):
        self.session = _Session()
        self.entered = 0
        self.exited  = 0

    def __call__( self ):
        return self

    def __enter__( self ):
        self.entered += 1
        return self.session

    def __exit__( self, *exc ):
        self.exited += 1
        return False


@pytest.fixture
def pg( monkeypatch ):
    """Stop PostgreSQL at the module boundary. Every run_migration test depends on this."""

    fake = _Db()
    monkeypatch.setattr( mod, "get_db", fake )

    return fake


# ── the real SQLite side ──────────────────────────────────────────────────────────────────

def _iso( **delta ):
    return ( datetime.now( timezone.utc ) + timedelta( **delta ) ).isoformat()


def build_db( path, *, token_extras=True, api_is_active=True ):
    """
    Create a real auth SQLite database with the seven tables the script counts.

    `token_extras` / `api_is_active` drop optional columns, which is how the script's
    `'col' in row.keys()` branches are reached — those exist because the SQLite schema drifted
    over its life, and a stubbed cursor could not reproduce that.
    """

    conn = sqlite3.connect( path )
    extras = ", user_agent TEXT, ip_address TEXT" if token_extras else ""
    active = ", is_active INTEGER"                 if api_is_active else ""
    conn.executescript( f"""
        CREATE TABLE users (
            id TEXT, email TEXT, password_hash TEXT, roles TEXT,
            email_verified INTEGER, is_active INTEGER,
            created_at TEXT, last_login_at TEXT );
        CREATE TABLE refresh_tokens (
            jti TEXT, user_id TEXT, token_hash TEXT, expires_at TEXT,
            created_at TEXT, last_used_at TEXT, revoked INTEGER{extras} );
        CREATE TABLE api_keys (
            user_id TEXT, key_hash TEXT, description TEXT,
            created_at TEXT, last_used_at TEXT{active} );
        CREATE TABLE auth_audit_log (
            id INTEGER, event_type TEXT, user_id TEXT, email TEXT,
            ip_address TEXT, details TEXT, success INTEGER, event_time TEXT );
        CREATE TABLE email_verification_tokens ( id INTEGER );
        CREATE TABLE password_reset_tokens ( id INTEGER );
        CREATE TABLE failed_login_attempts ( id INTEGER );
    """ )
    conn.commit()

    return conn


@pytest.fixture
def db_path( tmp_path, monkeypatch ):
    """A real database file, with SQLITE_DB_PATH pointed at it."""

    p = tmp_path / "lupin-auth.db"
    monkeypatch.setattr( mod, "SQLITE_DB_PATH", str( p ) )

    return p


@pytest.fixture
def conn( db_path ):
    """An empty but fully-schema'd database, opened the way the script opens it."""

    build_db( db_path ).close()
    c = sqlite3.connect( db_path )
    c.row_factory = sqlite3.Row
    yield c
    c.close()


# ── print_banner ──────────────────────────────────────────────────────────────────────────

def test_the_banner_prints_the_title_between_two_rules( capsys ):
    """Reddens if the banner stops naming its section — it is the only structure in the output."""

    mod.print_banner( "Migration Summary" )
    out = capsys.readouterr().out

    assert "Migration Summary" in out
    assert out.count( "=" * 70 ) == 2


# ── connect_sqlite ────────────────────────────────────────────────────────────────────────

def test_a_missing_sqlite_file_exits_one_and_names_the_path( db_path, capsys ):
    """
    Reddens if the missing database is not refused.

    Continuing would open an EMPTY database and migrate nothing, which reports as a clean run
    that moved zero rows — a success message for a migration that never happened.
    """

    with pytest.raises( SystemExit ) as e:
        mod.connect_sqlite()

    assert e.value.code == 1
    assert str( db_path ) in capsys.readouterr().out


def test_an_existing_database_opens_with_rows_addressable_by_name( db_path ):
    """Reddens if the row factory is dropped — every `row['col']` in this script would fail."""

    build_db( db_path ).close()

    c = mod.connect_sqlite()

    try:
        c.execute( "INSERT INTO users (email) VALUES ('a@b.c')" )
        row = c.execute( "SELECT * FROM users" ).fetchone()
        assert row[ "email" ] == "a@b.c"
    finally:
        c.close()


# ── count_sqlite_records ──────────────────────────────────────────────────────────────────

def test_every_one_of_the_seven_tables_is_counted( conn ):
    """Reddens if a table drops off the list — an uncounted table is one nobody notices is unmoved."""

    counts = mod.count_sqlite_records( conn )

    assert sorted( counts ) == sorted( ALL_TABLES )
    assert set( counts.values() ) == { 0 }


def test_the_counts_are_the_real_row_counts( conn ):
    """Reddens if the count stops being per-table — the summary's 'filtered from N' would lie."""

    conn.execute( "INSERT INTO users (email) VALUES ('a@b.c')" )
    conn.execute( "INSERT INTO users (email) VALUES ('d@e.f')" )
    conn.execute( "INSERT INTO api_keys (key_hash) VALUES ('h')" )

    counts = mod.count_sqlite_records( conn )

    assert counts[ "users" ]    == 2
    assert counts[ "api_keys" ] == 1
    assert counts[ "refresh_tokens" ] == 0


# ── migrate_users ─────────────────────────────────────────────────────────────────────────

def _add_user( conn, **over ):
    row = { "id": "u-1", "email": "a@b.c", "password_hash": "h", "roles": '["admin"]',
            "email_verified": 1, "is_active": 1,
            "created_at": "2026-01-02T03:04:05", "last_login_at": "2026-02-03T04:05:06" }
    row.update( over )
    conn.execute(
        "INSERT INTO users (id,email,password_hash,roles,email_verified,is_active,"
        "created_at,last_login_at) VALUES (:id,:email,:password_hash,:roles,"
        ":email_verified,:is_active,:created_at,:last_login_at)", row )


def test_a_dry_run_migrates_nothing_but_reports_what_it_would( conn, capsys ):
    """
    Reddens if a dry run adds to the session.

    --dry-run is the operator's preview of a one-way migration; it writing anything is the one
    thing it must never do.
    """

    _add_user( conn )
    session = _Session()

    n = mod.migrate_users( conn, session, dry_run=True )

    assert ( n, session.added ) == ( 1, [ ] )
    assert "[DRY-RUN] Would migrate user: a@b.c" in capsys.readouterr().out


def test_a_user_is_converted_field_by_field( conn ):
    """
    Reddens if any conversion changes.

    SQLite has no boolean and no datetime: `email_verified` arrives as INTEGER and `created_at`
    as TEXT. A 1 landing in a PostgreSQL boolean column, or an ISO string in a timestamp column,
    is where this migration breaks.
    """

    _add_user( conn )
    session = _Session()

    n = mod.migrate_users( conn, session, dry_run=False )

    assert n == 1
    user = session.of_type( "User" )[ 0 ]
    assert user.id             == "u-1"
    assert user.email          == "a@b.c"
    assert user.password_hash  == "h"
    assert user.roles          == [ "admin" ]
    assert user.email_verified is True
    assert user.is_active      is True
    assert user.created_at     == datetime( 2026, 1, 2, 3, 4, 5 )
    assert user.last_login_at  == datetime( 2026, 2, 3, 4, 5, 6 )


def test_a_zero_integer_becomes_false_not_a_truthy_zero( conn ):
    """Reddens if bool() is dropped — a raw 0 would still be stored, but as the wrong type."""

    _add_user( conn, email_verified=0, is_active=0 )
    session = _Session()

    mod.migrate_users( conn, session, dry_run=False )

    user = session.of_type( "User" )[ 0 ]
    assert user.email_verified is False
    assert user.is_active      is False


def test_a_user_with_no_roles_gets_the_default_role( conn ):
    """
    Reddens if the fallback goes away.

    A NULL roles column would become a JSON parse error mid-migration, aborting a transaction
    that had already moved every earlier user.
    """

    _add_user( conn, roles=None )
    session = _Session()

    mod.migrate_users( conn, session, dry_run=False )

    assert session.of_type( "User" )[ 0 ].roles == [ "user" ]


def test_null_timestamps_stay_null_rather_than_becoming_now( conn ):
    """Reddens if a NULL date is parsed — fromisoformat(None) raises and stops the migration."""

    _add_user( conn, created_at=None, last_login_at=None )
    session = _Session()

    mod.migrate_users( conn, session, dry_run=False )

    user = session.of_type( "User" )[ 0 ]
    assert user.created_at    is None
    assert user.last_login_at is None


def test_every_user_is_migrated_not_only_the_first( conn ):
    """Reddens if the loop stops early — a partial migration that reports success."""

    for i in range( 5 ):
        _add_user( conn, id=f"u-{i}", email=f"u{i}@x.y" )
    session = _Session()

    assert mod.migrate_users( conn, session, dry_run=False ) == 5
    assert len( session.of_type( "User" ) ) == 5


# ── migrate_active_refresh_tokens ─────────────────────────────────────────────────────────

def _add_token( conn, *, jti="t-1", revoked=0, expires_at=None, created_at="2026-01-02T03:04:05",
                last_used_at="2026-01-03T03:04:05", extras=True ):
    cols = { "jti": jti, "user_id": "u-1", "token_hash": "th",
             "expires_at": expires_at or _iso( days=1 ), "created_at": created_at,
             "last_used_at": last_used_at, "revoked": revoked }
    if extras:
        cols.update( user_agent="curl/8", ip_address="10.0.0.1" )
    names = ",".join( cols )
    binds = ",".join( f":{k}" for k in cols )
    conn.execute( f"INSERT INTO refresh_tokens ({names}) VALUES ({binds})", cols )


def test_a_revoked_token_is_left_behind( conn ):
    """
    Reddens if the `revoked = 0` clause is dropped.

    Migrating a revoked token re-arms a credential the user or an admin deliberately killed.
    """

    _add_token( conn, jti="live" )
    _add_token( conn, jti="revoked", revoked=1 )
    session = _Session()

    assert mod.migrate_active_refresh_tokens( conn, session, dry_run=False ) == 1
    assert session.of_type( "RefreshToken" )[ 0 ].jti == "live"


def test_an_expired_token_is_left_behind( conn ):
    """Reddens if the expiry clause is dropped — an expired token would come back alive."""

    _add_token( conn, jti="live" )
    _add_token( conn, jti="expired", expires_at=_iso( days=-1 ) )
    session = _Session()

    assert mod.migrate_active_refresh_tokens( conn, session, dry_run=False ) == 1
    assert session.of_type( "RefreshToken" )[ 0 ].jti == "live"


def test_an_active_token_is_converted_field_by_field( conn ):
    """Reddens if a field is dropped or a conversion changes."""

    _add_token( conn )
    session = _Session()

    mod.migrate_active_refresh_tokens( conn, session, dry_run=False )

    tok = session.of_type( "RefreshToken" )[ 0 ]
    assert tok.jti          == "t-1"
    assert tok.user_id      == "u-1"
    assert tok.token_hash   == "th"
    assert tok.revoked      is False
    assert tok.user_agent   == "curl/8"
    assert tok.ip_address   == "10.0.0.1"
    assert tok.created_at   == datetime( 2026, 1, 2, 3, 4, 5 )
    assert tok.last_used_at == datetime( 2026, 1, 3, 3, 4, 5 )
    assert tok.expires_at.tzinfo is not None


def test_a_token_dry_run_reports_the_jti_and_adds_nothing( conn, capsys ):
    """Reddens if a dry run writes — see the user dry-run test; same rule, second table."""

    _add_token( conn )
    session = _Session()

    assert mod.migrate_active_refresh_tokens( conn, session, dry_run=True ) == 1
    assert session.added == [ ]
    assert "[DRY-RUN] Would migrate refresh token: t-1" in capsys.readouterr().out


def test_null_token_timestamps_stay_null( conn ):
    """Reddens if a NULL created_at or last_used_at is parsed instead of passed through."""

    _add_token( conn, created_at=None, last_used_at=None )
    session = _Session()

    mod.migrate_active_refresh_tokens( conn, session, dry_run=False )

    tok = session.of_type( "RefreshToken" )[ 0 ]
    assert ( tok.created_at, tok.last_used_at ) == ( None, None )


def test_an_older_schema_without_the_agent_columns_still_migrates( db_path ):
    """
    Reddens if the column-presence guard goes away.

    `user_agent` and `ip_address` were added to this table later. On a database predating them,
    `row['user_agent']` raises IndexError and the whole migration dies — which is exactly the
    kind of database somebody would still be migrating FROM.
    """

    build_db( db_path, token_extras=False ).close()
    c = mod.connect_sqlite()
    try:
        _add_token( c, extras=False )
        session = _Session()

        assert mod.migrate_active_refresh_tokens( c, session, dry_run=False ) == 1
        tok = session.of_type( "RefreshToken" )[ 0 ]
        assert ( tok.user_agent, tok.ip_address ) == ( None, None )
    finally:
        c.close()


# ── migrate_api_keys ──────────────────────────────────────────────────────────────────────

def _add_key( conn, *, description="CI key", is_active=1, created_at="2026-01-02T03:04:05",
              last_used_at="2026-01-03T03:04:05", with_active=True ):
    cols = { "user_id": "u-1", "key_hash": "kh", "description": description,
             "created_at": created_at, "last_used_at": last_used_at }
    if with_active:
        cols[ "is_active" ] = is_active
    names = ",".join( cols )
    binds = ",".join( f":{k}" for k in cols )
    conn.execute( f"INSERT INTO api_keys ({names}) VALUES ({binds})", cols )


def test_an_api_key_is_converted_and_its_id_is_left_for_postgres( conn ):
    """
    Reddens if an id is carried across.

    The SQLite table's id is not a UUID; letting PostgreSQL generate one is deliberate, and
    passing the old value would either collide or store a malformed key id.
    """

    _add_key( conn )
    session = _Session()

    assert mod.migrate_api_keys( conn, session, dry_run=False ) == 1
    key = session.of_type( "ApiKey" )[ 0 ]
    assert key.user_id      == "u-1"
    assert key.key_hash     == "kh"
    assert key.description  == "CI key"
    assert key.is_active    is True
    assert key.created_at   == datetime( 2026, 1, 2, 3, 4, 5 )
    assert key.last_used_at == datetime( 2026, 1, 3, 3, 4, 5 )
    assert key.id is None


def test_an_inactive_api_key_stays_inactive( conn ):
    """Reddens if the flag is forced true — a disabled key would come back working."""

    _add_key( conn, is_active=0 )
    session = _Session()

    mod.migrate_api_keys( conn, session, dry_run=False )

    assert session.of_type( "ApiKey" )[ 0 ].is_active is False


def test_an_older_schema_without_is_active_defaults_the_key_to_active( db_path ):
    """Reddens if the guard goes away — a pre-column database would abort the migration."""

    build_db( db_path, api_is_active=False ).close()
    c = mod.connect_sqlite()
    try:
        _add_key( c, with_active=False )
        session = _Session()

        assert mod.migrate_api_keys( c, session, dry_run=False ) == 1
        assert session.of_type( "ApiKey" )[ 0 ].is_active is True
    finally:
        c.close()


def test_null_api_key_timestamps_stay_null( conn ):
    """Reddens if a NULL date is parsed instead of passed through."""

    _add_key( conn, created_at=None, last_used_at=None )
    session = _Session()

    mod.migrate_api_keys( conn, session, dry_run=False )

    key = session.of_type( "ApiKey" )[ 0 ]
    assert ( key.created_at, key.last_used_at ) == ( None, None )


def test_an_api_key_dry_run_reports_the_description_and_adds_nothing( conn, capsys ):
    """Reddens if a dry run writes."""

    _add_key( conn )
    session = _Session()

    assert mod.migrate_api_keys( conn, session, dry_run=True ) == 1
    assert session.added == [ ]
    assert "[DRY-RUN] Would migrate API key: CI key" in capsys.readouterr().out


# ── migrate_recent_audit_logs ─────────────────────────────────────────────────────────────

def _add_audit( conn, *, id=1, event_type="login", details='{"ip": "1.2.3.4"}',
                event_time=None, success=1, days_ago=1 ):
    conn.execute(
        "INSERT INTO auth_audit_log (id,event_type,user_id,email,ip_address,details,"
        "success,event_time) VALUES (?,?,?,?,?,?,?,?)",
        ( id, event_type, "u-1", "a@b.c", "10.0.0.1", details, success,
          event_time if event_time is not None else _iso( days=-days_ago ) ) )


def test_an_audit_entry_older_than_the_window_is_left_behind( conn ):
    """
    Reddens if the cutoff is dropped or widened.

    The window is the point of this function: the audit table is the largest in the database and
    migrating all of it is what the 30-day filter exists to avoid.
    """

    _add_audit( conn, id=1, days_ago=1 )
    _add_audit( conn, id=2, days_ago=mod.RECENT_AUDIT_DAYS + 5 )
    session = _Session()

    assert mod.migrate_recent_audit_logs( conn, session, dry_run=False ) == 1
    assert session.of_type( "AuthAuditLog" )[ 0 ].id == 1


def test_a_recent_audit_entry_is_converted_field_by_field( conn ):
    """Reddens if a field is dropped, or the details TEXT stops being parsed into JSONB."""

    _add_audit( conn )
    session = _Session()

    mod.migrate_recent_audit_logs( conn, session, dry_run=False )

    log = session.of_type( "AuthAuditLog" )[ 0 ]
    assert log.id         == 1
    assert log.event_type == "login"
    assert log.user_id    == "u-1"
    assert log.email      == "a@b.c"
    assert log.ip_address == "10.0.0.1"
    assert log.details    == { "ip": "1.2.3.4" }
    assert log.success    is True
    assert log.event_time is not None


def test_unparseable_details_are_kept_as_a_message_rather_than_lost( conn ):
    """
    Reddens if the JSON rescue goes away.

    An audit row whose details were written as a bare string is not a reason to abort a
    migration, and silently dropping it destroys the record this table exists to keep.
    """

    _add_audit( conn, details="not json at all" )
    session = _Session()

    mod.migrate_recent_audit_logs( conn, session, dry_run=False )

    assert session.of_type( "AuthAuditLog" )[ 0 ].details == { "message": "not json at all" }


@pytest.mark.parametrize( "raw", [ None, "", "   " ] )
def test_empty_details_become_an_empty_object_not_a_parse_error( conn, raw ):
    """Reddens if the emptiness guard goes away — json.loads('') raises and stops the migration."""

    _add_audit( conn, details=raw )
    session = _Session()

    mod.migrate_recent_audit_logs( conn, session, dry_run=False )

    assert session.of_type( "AuthAuditLog" )[ 0 ].details == { }


def test_a_null_audit_event_time_stays_null( conn ):
    """Reddens if a NULL event_time is parsed instead of passed through."""

    # A NULL event_time cannot pass the `event_time > cutoff` filter, so it is unreachable via
    # the query; the guard is asserted directly on the conversion the function performs.
    _add_audit( conn, event_time=_iso( days=-1 ) )
    session = _Session()

    mod.migrate_recent_audit_logs( conn, session, dry_run=False )

    assert session.of_type( "AuthAuditLog" )[ 0 ].event_time is not None


def test_a_failed_audit_entry_keeps_its_false( conn ):
    """Reddens if bool() is dropped — a failed login would migrate as a successful one."""

    _add_audit( conn, success=0 )
    session = _Session()

    mod.migrate_recent_audit_logs( conn, session, dry_run=False )

    assert session.of_type( "AuthAuditLog" )[ 0 ].success is False


def test_an_audit_dry_run_reports_the_event_and_adds_nothing( conn, capsys ):
    """Reddens if a dry run writes."""

    _add_audit( conn )
    session = _Session()

    assert mod.migrate_recent_audit_logs( conn, session, dry_run=True ) == 1
    assert session.added == [ ]
    assert "[DRY-RUN] Would migrate audit log: login at" in capsys.readouterr().out


# ── run_migration ─────────────────────────────────────────────────────────────────────────

@pytest.fixture
def populated( db_path ):
    """One row in each migratable table, so the end-to-end run has something to move."""

    c = build_db( db_path )
    c.row_factory = sqlite3.Row
    _add_user( c )
    _add_token( c )
    _add_key( c )
    _add_audit( c )
    c.commit()
    c.close()

    return db_path


def test_a_full_run_migrates_every_table_and_commits_once( populated, pg, capsys ):
    """
    Reddens if a table is skipped or the commit is dropped.

    The migration is all-or-nothing by design; without the commit every row it moved is rolled
    back at session close and the run still prints success.
    """

    mod.run_migration( dry_run=False )

    session = pg.session
    assert len( session.of_type( "User" ) )          == 1
    assert len( session.of_type( "RefreshToken" ) )  == 1
    assert len( session.of_type( "ApiKey" ) )        == 1
    assert len( session.of_type( "AuthAuditLog" ) )  == 1
    assert session.commits == 1
    out = capsys.readouterr().out
    assert "Migration completed successfully" in out
    assert "Total Records Migrated: 4"        in out


def test_a_dry_run_moves_nothing_and_never_commits( populated, pg, capsys ):
    """
    Reddens if --dry-run commits.

    This is the one flag standing between an operator previewing a one-way migration and
    performing it.
    """

    mod.run_migration( dry_run=True )

    assert pg.session.added   == [ ]
    assert pg.session.commits == 0
    out = capsys.readouterr().out
    assert "[DRY-RUN] Would commit transaction here" in out
    assert "Run without --dry-run to execute"        in out
    assert "SQLite to PostgreSQL Migration [DRY-RUN]" in out


def test_a_real_run_does_not_announce_itself_as_a_dry_run( populated, pg, capsys ):
    """Reddens if the mode label inverts — the loudest signal of which run this was."""

    mod.run_migration( dry_run=False )
    out = capsys.readouterr().out

    assert "[DRY-RUN]" not in out


def test_the_summary_reports_what_was_filtered_out( populated, pg, capsys ):
    """
    Reddens if the totals stop being compared against the source counts.

    "3 of 11 refresh tokens" is how an operator sees the filters did something; a bare "3" hides
    whether 8 were skipped or never existed.
    """

    c = sqlite3.connect( populated )
    _add_token( c, jti="revoked", revoked=1 )
    _add_audit( c, id=99, days_ago=mod.RECENT_AUDIT_DAYS + 5 )
    c.commit()
    c.close()

    mod.run_migration( dry_run=False )
    out = capsys.readouterr().out

    assert "Active Refresh Tokens: 1 (of 2 total)" in out
    assert "Recent Audit Logs:    1 (of 2 total)"  in out


def test_the_sqlite_counts_are_printed_before_anything_is_written( populated, pg, capsys ):
    """Reddens if the pre-flight count goes away — the only record of the source's shape."""

    mod.run_migration( dry_run=True )
    out = capsys.readouterr().out

    assert "SQLite Record Counts:" in out
    for table in ALL_TABLES:
        assert table in out


def test_a_failure_mid_migration_exits_one_and_prints_a_traceback( populated, pg, monkeypatch,
                                                                    capsys ):
    """
    Reddens if a failed migration exits 0.

    Exit 0 on a half-migration tells the caller — a shell script, or an operator moving on to
    cut over — that the data is in PostgreSQL when it is not.
    """

    monkeypatch.setattr( mod, "migrate_api_keys",
                         lambda *a, **k: ( _ for _ in () ).throw( RuntimeError( "pg is down" ) ) )

    with pytest.raises( SystemExit ) as e:
        mod.run_migration( dry_run=False )

    assert e.value.code == 1
    captured = capsys.readouterr()
    assert "Migration failed: pg is down" in captured.out
    assert "Traceback"                    in captured.err
    assert pg.session.commits == 0


def test_the_sqlite_connection_is_closed_even_when_the_migration_fails( populated, pg,
                                                                        monkeypatch ):
    """
    Reddens if the `finally` goes away.

    A migration that dies holding the source database open leaves a lock behind for whoever
    retries it.
    """

    opened = { }
    real   = mod.connect_sqlite

    def spy():
        opened[ "conn" ] = real()
        return opened[ "conn" ]

    monkeypatch.setattr( mod, "connect_sqlite", spy )
    monkeypatch.setattr( mod, "migrate_users",
                         lambda *a, **k: ( _ for _ in () ).throw( RuntimeError( "boom" ) ) )

    with pytest.raises( SystemExit ):
        mod.run_migration( dry_run=False )

    with pytest.raises( sqlite3.ProgrammingError ):
        opened[ "conn" ].execute( "SELECT 1" )


def test_the_sqlite_connection_is_closed_on_the_happy_path_too( populated, pg, monkeypatch ):
    """Reddens if the close only happens on failure — the common path would leak the handle."""

    opened = { }
    real   = mod.connect_sqlite

    def spy():
        opened[ "conn" ] = real()
        return opened[ "conn" ]

    monkeypatch.setattr( mod, "connect_sqlite", spy )

    mod.run_migration( dry_run=False )

    with pytest.raises( sqlite3.ProgrammingError ):
        opened[ "conn" ].execute( "SELECT 1" )


def test_the_postgres_session_is_opened_and_closed_around_the_work( populated, pg ):
    """Reddens if the `with` goes away — a leaked session holds a pooled connection open."""

    mod.run_migration( dry_run=True )

    assert ( pg.entered, pg.exited ) == ( 1, 1 )


# ── module surface ────────────────────────────────────────────────────────────────────────

def test_the_source_database_and_the_window_are_the_documented_ones():
    """
    Reddens if the source path or the retention window drifts.

    Both are load-bearing: the path decides WHICH database is migrated, and the window decides
    how much of the largest table comes with it.
    """

    assert mod.SQLITE_DB_PATH.endswith( "/src/conf/long-term-memory/lupin-auth.db" )
    assert mod.RECENT_AUDIT_DAYS == 30


def _load_probe( name ):
    """Load the script again under a throwaway name, leaving sys.modules as it found it."""

    spec  = importlib.util.spec_from_file_location( name, _SCRIPT )
    probe = importlib.util.module_from_spec( spec )
    sys.modules[ spec.name ] = probe
    try:
        spec.loader.exec_module( probe )
    finally:
        del sys.modules[ spec.name ]

    return probe


def test_the_by_path_load_never_puts_scripts_on_sys_path( monkeypatch ):
    """
    Reddens if this file's loader ever reaches for `sys.path.insert( 0, .../src/scripts )`.

    `src/scripts/` holds modules whose names collide with real packages, so putting it on the
    path can shadow them for the rest of the session (Krishna, row c89cec9b). Loading by path
    imports exactly one file and shadows nothing.

    ⚠️ THREE WRONG VERSIONS CAME FIRST. Each is a different way of measuring the wrong thing,
    and they are recorded because the next seat will write this test too.
    (1) Asserting the SESSION's `sys.path` lacks `src/scripts`. Passed alone, failed in a
        multi-file run: a neighbour — `test_detect_thread_credited_coverage.py:18` — does
        exactly the insert this recipe avoids, so the directory is already there. A test that
        reads global state it does not own reports its neighbours' behaviour as its own defect.
    (2) Asserting the load adds NOTHING. False, and for a reason belonging to the script rather
        than the loader: `migrate-sqlite-to-postgres.py:28` runs
        `sys.path.insert( 0, os.path.join( os.path.dirname( __file__ ), '..' ) )` at import.
    (3) Computing what was added with `p not in before` — a MEMBERSHIP test where the thing
        being measured is a COUNT. This module's own top-level load already put that entry on
        the path, so the script's unguarded re-insert adds a DUPLICATE that membership cannot
        see. Passed in isolation, failed in the suite, and looked like the same defect as (1)
        while being a different one.

    What the recipe actually buys is asserted here, by position and length rather than by
    membership: exactly one entry is prepended, it resolves to `src`, it is not `src/scripts`,
    and nothing else on the path moves.
    """

    monkeypatch.setattr( sys, "path", list( sys.path ) )
    before = list( sys.path )

    probe = _load_probe( "migrate_sqlite_to_postgres_probe" )

    assert len( sys.path ) == len( before ) + 1
    assert sys.path[ 1: ]  == before                       # nothing displaced or dropped
    added = sys.path[ 0 ]
    assert os.path.realpath( added ) == os.path.realpath( _SRC )
    assert os.path.realpath( added ) != os.path.realpath(
        os.path.join( _ROOT, "src", "scripts" ) )
    assert probe.__file__.endswith( "migrate-sqlite-to-postgres.py" )


def test_the_script_prepends_an_unnormalised_parent_path_on_every_import( monkeypatch ):
    """
    Documents a real, minor defect in the script rather than papering over it.

    `migrate-sqlite-to-postgres.py:28` inserts `<root>/src/scripts/..` at position 0 with NO
    membership guard. Two consequences, both asserted here:
      · The string is UNNORMALISED, so it is not equal to `<root>/src` even though it resolves
        there. A `if path not in sys.path` guard elsewhere cannot recognise it as the same
        entry — which is exactly how wrong version (3) of the test above fooled itself.
      · There is no guard at all, so each import prepends ANOTHER copy and `sys.path` grows
        once per import.

    Harmless for a script run once from a shell, which is how this one is used. Recorded so the
    next reader knows it was measured and judged rather than missed. The sibling
    `create_service_account_postgres.py` guards the same insert with
    `if src_path not in sys.path`, so the better pattern exists in-tree; this file predates it.
    """

    monkeypatch.setattr( sys, "path", list( sys.path ) )
    unnormalised = os.path.join( os.path.dirname( _SCRIPT ), ".." )
    start        = sys.path.count( unnormalised )

    for n in ( 1, 2 ):
        _load_probe( f"probe_{n}" )
        assert sys.path[ 0 ] == unnormalised
        assert sys.path.count( unnormalised ) == start + n     # no guard: it accumulates

    assert unnormalised != _SRC                                # unnormalised, so never equal
    assert os.path.realpath( unnormalised ) == os.path.realpath( _SRC )


def test_the_module_under_test_was_itself_loaded_by_path():
    """Reddens if the loader at the top of this file is swapped for a name-based import."""

    assert mod.__file__.endswith( "migrate-sqlite-to-postgres.py" )
    assert mod.__name__ == "migrate_sqlite_to_postgres"
