"""
The PostgreSQL migration validator, covered without a database.

Row `2af4a38b` — `src/scripts/validate-postgres-migration.py`, 122 statements at zero.

🔴 HOW THIS DASHED SCRIPT IS IMPORTED — the same recipe as `test_migrate_sqlite_to_postgres.py`
(row 8df164c6), repeated here rather than cross-referenced because the next seat reads one file,
not two. `validate-postgres-migration` is not a legal Python identifier, so there is no bare
`import`. It is loaded BY PATH:

    spec = importlib.util.spec_from_file_location( "validate_postgres_migration", <abs path> )
    mod  = importlib.util.module_from_spec( spec )
    sys.modules[ spec.name ] = mod          # register BEFORE exec_module
    spec.loader.exec_module( mod )

`src/scripts/` is NEVER put on `sys.path`: it holds modules whose names collide with real
packages, so pathing it can shadow them for the rest of the session (Krishna, row c89cec9b).
`src/` alone goes on, because the script imports `cosa`.

WHAT THIS FILE IS CAREFUL ABOUT:

· 🔴 NO POSTGRESQL. `get_db` is stopped at the MODULE attribute, so a missed patch is an error
  rather than a read of `lupin_db_dev` — the box a host shell silently reaches (CLAUDE.md
  § TESTING VENUES). This script only reads, but a unit test that reaches a shared database is
  still a unit test that fails for reasons that have nothing to do with the code.
· ✅ THE SQLALCHEMY CRITERIA ARE EVALUATED FOR REAL. `session.query( User ).filter( User.id ==
  token.user_id ).first()` is not stubbed into "return the row I planted": the fake query reads
  the actual criterion object the script built — its column key and its bound value — and
  applies it to in-memory rows. So a token pointing at a user who is not there genuinely finds
  nothing, which is the whole point of the foreign-key check.
· ✅ THE ORM MODELS ARE REAL. `User`, `RefreshToken`, `ApiKey` and `AuthAuditLog` construct fine
  without a connection.

⚠️ ONE TEST HERE PINS A KNOWN DEFECT RATHER THAN A REQUIREMENT — see
`test_the_script_prepends_an_unnormalised_parent_path_on_every_import` at the bottom, and bug
row `bef58663`. Whoever fixes that bug must update that test in the same commit.

Each test names the change that reddens it.
"""

import importlib.util
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest


# ── the by-path load (see the module docstring) ───────────────────────────────────────────

_ROOT = os.environ.get( "LUPIN_ROOT", os.getcwd() )
_SRC  = os.path.join( _ROOT, "src" )
if _SRC not in sys.path:
    sys.path.insert( 0, _SRC )

_SCRIPT = os.path.join( _ROOT, "src", "scripts", "validate-postgres-migration.py" )
_SPEC   = importlib.util.spec_from_file_location( "validate_postgres_migration", _SCRIPT )
mod     = importlib.util.module_from_spec( _SPEC )
sys.modules[ _SPEC.name ] = mod
_SPEC.loader.exec_module( mod )


UTC = timezone.utc


# ── a fake session that evaluates the script's OWN criteria ───────────────────────────────

def _wanted( criterion ):
    """
    The value a SQLAlchemy `Column == x` criterion is asking for.

    Two shapes arrive here and both must work. `User.id == token.user_id` keeps the value in a
    BindParameter, reachable as `.right.value`. `ApiKey.is_active == True` is folded by
    SQLAlchemy into a `True_` literal with no `.value` at all — measured, not assumed, because
    the first version of this helper crashed on exactly that.
    """

    right = criterion.right
    name  = type( right ).__name__
    if name in ( "True_", "False_" ):
        return name == "True_"

    return right.value


class _Query:
    """`session.query( Model )`, filtered by really reading the criterion the script built."""

    def __init__( self, rows ):
        self._rows = list( rows )

    def count( self ):
        return len( self._rows )

    def all( self ):
        return list( self._rows )

    def filter( self, *criteria ):
        rows = self._rows
        for c in criteria:
            key  = c.left.key
            want = _wanted( c )
            rows = [ r for r in rows if getattr( r, key ) == want ]

        return _Query( rows )

    def first( self ):
        return self._rows[ 0 ] if self._rows else None


class _Session:
    def __init__( self, tables ):
        self.tables  = tables
        self.queried = [ ]

    def query( self, model ):
        self.queried.append( model.__name__ )

        return _Query( self.tables.get( model.__name__, [ ] ) )


class _Db:
    """`get_db()` used as a context manager; counts entries so a leaked session is visible."""

    def __init__( self, tables ):
        self.session = _Session( tables )
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


# ── row builders ──────────────────────────────────────────────────────────────────────────

def make_user( uid="u-1", email="a@b.c", roles=None, pw="$2b$12$abcdefghijklmnopqrstuv",
               created_at="aware", last_login_at="aware" ):
    u = mod.User( email=email )
    u.id             = uid
    u.roles          = [ "user" ] if roles is None else roles
    u.password_hash  = pw
    u.created_at     = _stamp( created_at )
    u.last_login_at  = _stamp( last_login_at )

    return u


def _stamp( kind ):
    if kind == "aware": return datetime( 2026, 1, 2, 3, 4, 5, tzinfo=UTC )
    if kind == "naive": return datetime( 2026, 1, 2, 3, 4, 5 )

    return None


def make_token( jti="t-1", user_id="u-1" ):
    t = mod.RefreshToken()
    t.jti     = jti
    t.user_id = user_id

    return t


def make_key( kid="k-1", user_id="u-1", is_active=True, description="CI key",
              last_used_at=None ):
    k = mod.ApiKey()
    k.id           = kid
    k.user_id      = user_id
    k.is_active    = is_active
    k.description  = description
    k.last_used_at = last_used_at

    return k


def make_audit( aid=1 ):
    a = mod.AuthAuditLog()
    a.id = aid

    return a


@pytest.fixture
def db( monkeypatch ):
    """
    Stop the database at the module boundary and return a factory.

    Call `db( users=[...], api_keys=[...] )` to install the tables a test needs; the installed
    `_Db` is returned so entry/exit counts can be asserted.
    """

    holder = { }

    def install( users=(), refresh_tokens=(), api_keys=(), audit_logs=() ):
        fake = _Db( { "User"         : list( users ),
                      "RefreshToken" : list( refresh_tokens ),
                      "ApiKey"       : list( api_keys ),
                      "AuthAuditLog" : list( audit_logs ) } )
        monkeypatch.setattr( mod, "get_db", fake )
        holder[ "db" ] = fake

        return fake

    return install


# ── print_banner ──────────────────────────────────────────────────────────────────────────

def test_the_banner_prints_the_title_between_two_rules( capsys ):
    """Reddens if the banner stops naming its section — it is the only structure in the output."""

    mod.print_banner( "Validation Complete" )
    out = capsys.readouterr().out

    assert "Validation Complete" in out
    assert out.count( "=" * 70 ) == 2


# ── validate_record_counts ────────────────────────────────────────────────────────────────

def test_the_counts_are_reported_and_returned_per_table( db, capsys ):
    """Reddens if a table stops being counted — the summary is the operator's only tally."""

    db( users=[ make_user() ], refresh_tokens=[ make_token() ],
        api_keys=[ make_key() ], audit_logs=[ make_audit(), make_audit( 2 ) ] )

    counts = mod.validate_record_counts()

    assert counts == { "users": 1, "refresh_tokens": 1, "api_keys": 1, "audit_logs": 2 }
    out = capsys.readouterr().out
    assert "Users:          1"  in out
    assert "Audit Logs:     2"  in out
    assert "✓ Record counts validated" in out


def test_an_empty_users_table_fails_validation( db ):
    """
    Reddens if a migration that moved no users passes.

    Zero users is the signature of a migration that connected, ran, committed nothing and
    reported success — the exact failure this script exists to catch.
    """

    db( users=[ ], api_keys=[ make_key() ] )

    with pytest.raises( AssertionError, match="No users found" ):
        mod.validate_record_counts()


def test_an_empty_api_keys_table_fails_validation( db ):
    """Reddens if the API-key check drops — the notification path would be dead on arrival."""

    db( users=[ make_user() ], api_keys=[ ] )

    with pytest.raises( AssertionError, match="No API keys found" ):
        mod.validate_record_counts()


def test_zero_refresh_tokens_and_zero_audit_logs_are_acceptable( db ):
    """
    Reddens if either is asserted non-empty.

    Both are legitimately empty after a migration: every token may have expired, and the audit
    window keeps only recent rows. Failing on them would make a good migration look broken.
    """

    counts = mod.validate_record_counts() if db(
        users=[ make_user() ], api_keys=[ make_key() ] ) else None

    assert counts[ "refresh_tokens" ] == 0
    assert counts[ "audit_logs" ]     == 0


# ── validate_uuids ────────────────────────────────────────────────────────────────────────

def test_populated_identifiers_pass_and_are_counted( db, capsys ):
    """Reddens if the report stops naming how many of each were checked."""

    db( users=[ make_user() ], refresh_tokens=[ make_token() ], api_keys=[ make_key() ] )

    mod.validate_uuids()

    assert "Validated UUIDs for 1 users, 1 tokens, 1 API keys" in capsys.readouterr().out


def test_a_user_with_no_id_fails_and_the_message_names_the_email( db ):
    """Reddens if the identity in the message is dropped — it is how an operator finds the row."""

    db( users=[ make_user( uid=None, email="orphan@x.y" ) ], api_keys=[ make_key() ] )

    with pytest.raises( AssertionError, match="orphan@x.y" ):
        mod.validate_uuids()


def test_a_refresh_token_with_no_jti_fails( db ):
    """Reddens if the jti check drops — a token with no identity cannot be revoked."""

    db( users=[ make_user() ], refresh_tokens=[ make_token( jti=None ) ] )

    with pytest.raises( AssertionError, match="NULL jti" ):
        mod.validate_uuids()


def test_a_refresh_token_with_no_user_fails( db ):
    """Reddens if the ownerless-token check drops."""

    db( users=[ make_user() ], refresh_tokens=[ make_token( user_id=None ) ] )

    with pytest.raises( AssertionError, match="NULL user_id" ):
        mod.validate_uuids()


def test_an_api_key_with_no_user_fails( db ):
    """
    Reddens if an ownerless API key passes.

    A key with no user cannot be attributed or revoked through its owner, which is how keys are
    revoked.
    """

    db( users=[ make_user() ], api_keys=[ make_key( user_id=None ) ] )

    with pytest.raises( AssertionError, match="API key has NULL user_id" ):
        mod.validate_uuids()


# ── validate_foreign_keys ─────────────────────────────────────────────────────────────────

def test_references_that_resolve_pass_and_are_counted( db, capsys ):
    """Reddens if the resolution check stops running — see the dangling tests below."""

    db( users=[ make_user( uid="u-1" ) ],
        refresh_tokens=[ make_token( user_id="u-1" ) ],
        api_keys=[ make_key( user_id="u-1" ) ] )

    mod.validate_foreign_keys()

    assert "All foreign keys valid (1 token refs, 1 API key refs)" in capsys.readouterr().out


def test_a_refresh_token_pointing_at_a_missing_user_fails( db ):
    """
    Reddens if the lookup stops being real.

    This is the check that a stubbed query would quietly destroy: if `filter().first()` returned
    a planted row regardless of the criterion, a dangling reference would pass. The fake query
    here evaluates the script's own `User.id == token.user_id` against the rows present.
    """

    db( users=[ make_user( uid="u-1" ) ],
        refresh_tokens=[ make_token( jti="orphan", user_id="u-GONE" ) ] )

    with pytest.raises( AssertionError, match="orphan references non-existent user u-GONE" ):
        mod.validate_foreign_keys()


def test_an_api_key_pointing_at_a_missing_user_fails( db ):
    """Reddens if the API-key half of the foreign-key check drops."""

    db( users=[ make_user( uid="u-1" ) ],
        api_keys=[ make_key( kid="k-9", user_id="u-GONE" ) ] )

    with pytest.raises( AssertionError, match="API key k-9 references non-existent user" ):
        mod.validate_foreign_keys()


# ── validate_password_hashes ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize( "prefix", [ "$2b$", "$2a$" ] )
def test_both_accepted_bcrypt_prefixes_pass( db, prefix, capsys ):
    """
    Reddens if either variant is rejected.

    `$2a$` is the older bcrypt revision and real rows carry it; accepting only `$2b$` would
    fail a correct migration of an older database.
    """

    db( users=[ make_user( pw=prefix + "12$abcdefghijklmnopqrstuv" ) ] )

    mod.validate_password_hashes()

    assert "Validated 1 password hashes" in capsys.readouterr().out


def test_a_user_with_no_password_hash_fails( db ):
    """Reddens if a NULL hash passes — that account can never authenticate."""

    db( users=[ make_user( pw=None, email="nohash@x.y" ) ] )

    with pytest.raises( AssertionError, match="nohash@x.y has NULL password_hash" ):
        mod.validate_password_hashes()


def test_a_hash_that_is_not_bcrypt_fails( db ):
    """
    Reddens if the format check drops.

    A plaintext or differently-hashed value in that column is a credential the login path will
    never match — and, if it is plaintext, a leak.
    """

    db( users=[ make_user( pw="plaintext-password", email="bad@x.y" ) ] )

    with pytest.raises( AssertionError, match="bad@x.y has invalid bcrypt hash format" ):
        mod.validate_password_hashes()


# ── validate_active_api_key ───────────────────────────────────────────────────────────────

def test_an_active_key_passes_and_is_described( db, capsys ):
    """Reddens if the key's description or last-used stamp stops being printed."""

    db( api_keys=[ make_key( description="notification key",
                             last_used_at=datetime( 2026, 2, 3, tzinfo=UTC ) ) ] )

    mod.validate_active_api_key()

    out = capsys.readouterr().out
    assert "Active API key: notification key" in out
    assert "Found 1 active API key(s)"        in out


def test_a_database_whose_keys_are_all_inactive_fails( db ):
    """
    Reddens if the `is_active == True` filter is dropped or inverted.

    Keys existing is not the same as a key working; a migration that carried every key across
    with is_active false leaves the notification path dead while the row count looks right.
    """

    db( api_keys=[ make_key( is_active=False ), make_key( kid="k-2", is_active=False ) ] )

    with pytest.raises( AssertionError, match="No active API keys found" ):
        mod.validate_active_api_key()


def test_only_the_active_keys_are_counted( db, capsys ):
    """Reddens if inactive keys are counted as active — the filter really is evaluated."""

    db( api_keys=[ make_key( kid="k-1", is_active=True,  description="live" ),
                   make_key( kid="k-2", is_active=False, description="retired" ) ] )

    mod.validate_active_api_key()

    out = capsys.readouterr().out
    assert "Found 1 active API key(s)" in out
    assert "retired" not in out


# ── validate_user_roles ───────────────────────────────────────────────────────────────────

def test_admins_and_users_are_counted_separately( db, capsys ):
    """Reddens if either tally drops — a migration that lost every admin still looks fine."""

    db( users=[ make_user( uid="u-1", roles=[ "admin", "user" ] ),
                make_user( uid="u-2", roles=[ "user" ] ),
                make_user( uid="u-3", roles=[ "service_account" ] ) ] )

    mod.validate_user_roles()

    out = capsys.readouterr().out
    assert "Admin users: 1"   in out
    assert "Regular users: 2" in out
    assert "All 3 users have valid roles" in out


def test_a_user_with_null_roles_fails( db ):
    """Reddens if NULL roles pass — that account has none of the access it was migrated with."""

    db( users=[ make_user( roles=False, email="noroles@x.y" ) ] )
    # `roles=False` is not None, so set it explicitly to exercise the NULL branch:
    mod.get_db.session.tables[ "User" ][ 0 ].roles = None

    with pytest.raises( AssertionError, match="noroles@x.y has NULL roles" ):
        mod.validate_user_roles()


def test_roles_stored_as_a_string_rather_than_a_list_fails( db ):
    """
    Reddens if the type check drops.

    The SQLite column was TEXT holding JSON; if the migration stored the raw string instead of
    parsing it, `"admin" in user.roles` becomes a SUBSTRING test that silently half-works.
    """

    db( users=[ make_user( roles='["admin"]', email="strroles@x.y" ) ] )

    with pytest.raises( AssertionError, match="strroles@x.y roles is not a list" ):
        mod.validate_user_roles()


# ── validate_timestamps ───────────────────────────────────────────────────────────────────

def test_timezone_aware_timestamps_pass( db, capsys ):
    """Reddens if aware timestamps start failing — the normal case."""

    db( users=[ make_user() ] )

    mod.validate_timestamps()

    assert "All timestamps have timezone information" in capsys.readouterr().out


def test_a_naive_created_at_fails( db ):
    """
    Reddens if the timezone check drops.

    A naive timestamp in a timestamptz column is silently interpreted in the server's zone; the
    row is not wrong-looking, it is wrong by however many hours the offset is.
    """

    db( users=[ make_user( created_at="naive", email="naive@x.y" ) ] )

    with pytest.raises( AssertionError, match="naive@x.y created_at missing timezone" ):
        mod.validate_timestamps()


def test_a_naive_last_login_fails( db ):
    """Reddens if only created_at is checked — last_login_at drifts the same way."""

    db( users=[ make_user( last_login_at="naive", email="naive2@x.y" ) ] )

    with pytest.raises( AssertionError, match="naive2@x.y last_login_at missing timezone" ):
        mod.validate_timestamps()


def test_null_timestamps_are_skipped_rather_than_failed( db ):
    """
    Reddens if the None guards go away.

    A user who has never logged in has a NULL last_login_at, and `None.tzinfo` is an
    AttributeError — the validator would crash on a perfectly good row.
    """

    db( users=[ make_user( created_at=None, last_login_at=None ) ] )

    mod.validate_timestamps()          # must not raise


# ── run_validation ────────────────────────────────────────────────────────────────────────

@pytest.fixture
def valid( db ):
    """A database that passes every check, so a test can break exactly one thing."""

    return db( users=[ make_user( uid="u-1", roles=[ "admin", "user" ] ) ],
               refresh_tokens=[ make_token( user_id="u-1" ) ],
               api_keys=[ make_key( user_id="u-1" ) ],
               audit_logs=[ make_audit() ] )


def test_a_clean_migration_reports_every_check_and_the_summary( valid, capsys ):
    """Reddens if a check is skipped or the summary stops echoing the counts."""

    mod.run_validation()

    out = capsys.readouterr().out
    assert "All validation checks passed" in out
    assert "Users:          1"            in out
    assert "Refresh Tokens: 1"            in out
    assert "API Keys:       1"            in out
    assert "Audit Logs:     1"            in out
    assert "ready for production use"     in out


def test_every_check_actually_runs_in_order( valid, monkeypatch ):
    """
    Reddens if a check is dropped from the sequence.

    A validator that silently stops calling one of its checks still prints "All validation
    checks passed" — the failure mode this test exists for.
    """

    called = [ ]
    for name in ( "validate_uuids", "validate_foreign_keys", "validate_password_hashes",
                  "validate_active_api_key", "validate_user_roles", "validate_timestamps" ):
        monkeypatch.setattr( mod, name,
                             ( lambda n: lambda: called.append( n ) )( name ) )

    mod.run_validation()

    assert called == [ "validate_uuids", "validate_foreign_keys", "validate_password_hashes",
                       "validate_active_api_key", "validate_user_roles", "validate_timestamps" ]


def test_a_failed_check_exits_one_and_prints_the_reason( db, capsys ):
    """
    Reddens if a failed validation exits 0.

    Exit 0 here tells an operator the migrated database is ready for production when a check
    just said it is not.
    """

    db( users=[ ], api_keys=[ make_key() ] )

    with pytest.raises( SystemExit ) as e:
        mod.run_validation()

    assert e.value.code == 1
    out = capsys.readouterr().out
    assert "Validation failed: No users found" in out
    assert "All validation checks passed" not in out


def test_an_unexpected_error_exits_one_with_a_traceback( valid, monkeypatch, capsys ):
    """
    Reddens if a non-assertion failure is swallowed or reported as success.

    A dropped connection is not an AssertionError, and it must not read as a clean validation.
    """

    monkeypatch.setattr( mod, "validate_uuids",
                         lambda: ( _ for _ in () ).throw( RuntimeError( "connection lost" ) ) )

    with pytest.raises( SystemExit ) as e:
        mod.run_validation()

    assert e.value.code == 1
    captured = capsys.readouterr()
    assert "Unexpected error during validation: connection lost" in captured.out
    assert "Traceback" in captured.err


def test_an_assertion_failure_is_not_reported_as_an_unexpected_error( db, capsys ):
    """Reddens if the two except arms merge — they say different things to the operator."""

    db( users=[ ], api_keys=[ make_key() ] )

    with pytest.raises( SystemExit ):
        mod.run_validation()

    assert "Unexpected error" not in capsys.readouterr().out


def test_each_check_opens_and_closes_its_own_session( valid ):
    """
    Reddens if a `with get_db()` goes away.

    Seven checks each open one; a leaked session holds a pooled connection for the life of the
    process.
    """

    mod.run_validation()

    assert valid.entered == 7
    assert valid.exited  == 7


# ── module surface ────────────────────────────────────────────────────────────────────────

def test_the_source_database_path_is_the_documented_one():
    """Reddens if the constant drifts — it names which database this run is about."""

    assert mod.SQLITE_DB_PATH.endswith( "/src/conf/long-term-memory/lupin-auth.db" )


def test_the_module_under_test_was_loaded_by_path():
    """Reddens if the loader at the top of this file is swapped for a name-based import."""

    assert mod.__file__.endswith( "validate-postgres-migration.py" )
    assert mod.__name__ == "validate_postgres_migration"


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

    Asserted by POSITION AND LENGTH, not by membership. Membership is the wrong instrument here
    and cost me three wrong versions of this test on row 8df164c6: the entry involved may
    ALREADY be on the path under a different spelling, so `p not in before` reports "nothing
    added" while a duplicate is being prepended.
    """

    monkeypatch.setattr( sys, "path", list( sys.path ) )
    before = list( sys.path )

    probe = _load_probe( "validate_postgres_migration_probe" )

    assert len( sys.path ) == len( before ) + 1
    assert sys.path[ 1: ]  == before                       # nothing displaced or dropped
    added = sys.path[ 0 ]
    assert os.path.realpath( added ) == os.path.realpath( _SRC )
    assert os.path.realpath( added ) != os.path.realpath(
        os.path.join( _ROOT, "src", "scripts" ) )
    assert probe.__file__.endswith( "validate-postgres-migration.py" )


def test_the_script_prepends_an_unnormalised_parent_path_on_every_import( monkeypatch ):
    """
    🔴 THIS TEST PINS A KNOWN DEFECT, NOT A REQUIREMENT — bug row `bef58663`.

    `validate-postgres-migration.py:26` inserts `<root>/src/scripts/..` at position 0 with NO
    membership guard. Two consequences, both asserted here:
      · The string is UNNORMALISED, so it is not equal to `<root>/src` even though it resolves
        there. A `if path not in sys.path` guard written elsewhere cannot recognise it as the
        same entry.
      · There is no guard at all, so each import prepends ANOTHER copy.

    ⚠️ WHOEVER FIXES bef58663 MUST UPDATE THIS TEST IN THE SAME COMMIT. That is the standing
    cost of covering a file before fixing it: the ramp does not leave a defect where it found
    it, it leaves it nailed down by a passing test. A fix that leaves this green has not fixed
    anything; a fix that turns it red without updating it reads as a regression.

    The sibling `migrate-sqlite-to-postgres.py` carries the identical defect and its own
    identically-named pinning test (commit 0ca03736). Those two files are the entire blast
    radius — measured, 37 files under src/scripts touch sys.path, 31 are guarded, and only
    these two are both unguarded and unnormalised.
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
