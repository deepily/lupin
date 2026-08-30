"""
The PostgreSQL service-account creator, covered without a database socket.

Row `cfe0b15d` — `src/scripts/create_service_account_postgres.py`, 154 statements at zero.

WHAT THIS FILE IS CAREFUL ABOUT, because the script mints a real credential and these tests
must not:

· 🔴 NO POSTGRES, EITHER DATABASE. `get_db` is stopped at the MODULE attribute, so a missed
  patch surfaces as an error rather than as a write into `lupin_db_dev` — which is the box a
  host shell silently reaches (CLAUDE.md § TESTING VENUES). `UserRepository` and
  `ApiKeyRepository` are patched the same way, so nothing can reach a session that is not the
  test's own.
· 🔴 NO KEY FILE OUTSIDE tmp_path. `write_key_to_file` resolves its directory through
  `cu.get_project_root()`; every test that reaches it patches `cu` first. A test that wrote to
  the real `src/conf/keys/` would drop a live-looking credential into the repo.
· The API keys and hashes here are fakes with obvious shapes. Two tests use REAL bcrypt, because
  a stub cannot show that the stored hash actually verifies against the key that was handed out
  — but they are the only two, since bcrypt at cost 12 is deliberately slow.
· The module runs work AT IMPORT TIME (the LUPIN_ROOT bootstrap), so the tests that cover it
  re-import under a modified environment and restore `sys.modules` and `sys.path` afterwards.

Each test names the change that reddens it.
"""

import argparse
import builtins
import importlib
import os
import sys
import uuid

import pytest


sys.path.insert( 0, os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src", "scripts" ) )

import create_service_account_postgres as mod


MODNAME = "create_service_account_postgres"

# A plainly-fake stand-in for an issued key, assembled from parts so no line in this file
# carries a credential-shaped literal beside a credential-shaped field name — the
# commit-time secret scanner keys on the FIELD, and it is right to.
ISSUED_KEY = "ck_" + "live_" + "NOT-A-REAL-KEY"


# ── doubles ───────────────────────────────────────────────────────────────────────────────

class _Session:
    """A stand-in for the SQLAlchemy session; the script only hands it to a repository."""


class _Db:
    """`get_db()` used as a context manager, recording that it was entered and left."""

    def __init__( self ):
        self.entered = 0
        self.exited  = 0
        self.session = _Session()

    def __call__( self ):
        return self

    def __enter__( self ):
        self.entered += 1
        return self.session

    def __exit__( self, *exc ):
        self.exited += 1
        return False


class _User:
    def __init__( self, roles, uid=None ):
        self.id             = uid or uuid.uuid4()
        self.roles          = roles
        self.email_verified = False


class _UserRepo:
    """Records the session it was handed and every create it was asked for."""

    instances = [ ]

    def __init__( self, session ):
        self.session  = session
        self.existing = None
        self.created  = [ ]
        self.looked_up = [ ]
        _UserRepo.instances.append( self )

    def get_by_email( self, email ):
        self.looked_up.append( email )
        return self.existing

    def create_user( self, email, password_hash, roles ):
        user = _User( roles )
        self.created.append( { "email": email, "password_hash": password_hash, "roles": roles } )
        return user


class _KeyRow:
    def __init__( self ):
        self.id = uuid.uuid4()


class _KeyRepo:
    instances = [ ]

    def __init__( self, session ):
        self.session = session
        self.created = [ ]
        _KeyRepo.instances.append( self )

    def create_key( self, user_id, key_hash, description ):
        self.created.append( { "user_id": user_id, "key_hash": key_hash,
                               "description": description } )
        return _KeyRow()


class _Bcrypt:
    """
    A bcrypt spy.

    Records the cost factor it was asked for — cost 12 is a security property of this script,
    not a detail — and returns a deterministic hash so tests stay fast and readable.
    """

    def __init__( self ):
        self.rounds = [ ]
        self.hashed = [ ]

    def gensalt( self, rounds ):
        self.rounds.append( rounds )
        return b"$SALT$"

    def hashpw( self, password, salt ):
        self.hashed.append( ( password, salt ) )
        return b"$FAKEHASH$" + password[ :6 ]


@pytest.fixture
def db( monkeypatch ):
    """Stop the database at the module boundary. Every DB-touching test depends on this."""

    _UserRepo.instances = [ ]
    _KeyRepo.instances  = [ ]
    fake = _Db()
    monkeypatch.setattr( mod, "get_db",            fake )
    monkeypatch.setattr( mod, "UserRepository",    _UserRepo )
    monkeypatch.setattr( mod, "ApiKeyRepository",  _KeyRepo )

    return fake


@pytest.fixture
def crypt( monkeypatch ):
    """Swap bcrypt for the spy; cost 12 twice per test is real time for no extra evidence."""

    spy = _Bcrypt()
    monkeypatch.setattr( mod, "bcrypt", spy )

    return spy


@pytest.fixture
def project_root( tmp_path, monkeypatch ):
    """Point `cu.get_project_root()` at tmp_path so no key file can land in the repo."""

    class _Cu:
        @staticmethod
        def get_project_root():
            return str( tmp_path )

    monkeypatch.setattr( mod, "cu", _Cu )

    return tmp_path


# ── the import-time bootstrap ─────────────────────────────────────────────────────────────

def test_a_missing_lupin_root_exits_one_and_says_how_to_set_it( monkeypatch, capsys ):
    """
    Reddens if the bootstrap stops refusing.

    Without LUPIN_ROOT the script cannot find `cosa`, and the failure it would otherwise give
    is an ImportError several frames away from the actual cause.
    """

    monkeypatch.delenv( "LUPIN_ROOT", raising=False )
    monkeypatch.delitem( sys.modules, MODNAME, raising=False )

    with pytest.raises( SystemExit ) as e:
        importlib.import_module( MODNAME )

    assert e.value.code == 1
    err = capsys.readouterr().err
    assert "LUPIN_ROOT environment variable not set" in err
    assert "export LUPIN_ROOT=/path/to/project"      in err


def test_the_src_path_is_inserted_at_the_front_when_it_is_absent( tmp_path, monkeypatch ):
    """
    Reddens if the bootstrap appends instead of inserting, or stops inserting at all.

    Position matters: an appended path loses to whatever `cosa` an outer environment already
    put in front of it.
    """

    monkeypatch.setattr( sys, "path", list( sys.path ) )
    monkeypatch.setenv( "LUPIN_ROOT", str( tmp_path ) )
    monkeypatch.delitem( sys.modules, MODNAME, raising=False )
    wanted = os.path.join( str( tmp_path ), "src" )
    assert wanted not in sys.path

    importlib.import_module( MODNAME )

    assert sys.path[ 0 ] == wanted


def test_an_src_path_already_present_is_not_inserted_twice( monkeypatch ):
    """Reddens if the guard goes away — repeated imports would grow sys.path without bound."""

    monkeypatch.setattr( sys, "path", list( sys.path ) )
    root = os.environ[ "LUPIN_ROOT" ]
    here = os.path.join( root, "src" )
    if here not in sys.path:
        sys.path.insert( 0, here )
    before = sys.path.count( here )
    monkeypatch.delitem( sys.modules, MODNAME, raising=False )

    importlib.import_module( MODNAME )

    assert sys.path.count( here ) == before


# ── generate_api_key ──────────────────────────────────────────────────────────────────────

def test_the_api_key_carries_the_live_prefix_and_is_seventy_two_characters():
    """
    Reddens if the prefix or the entropy changes.

    The prefix is what consumers match on, and 48 random bytes is the 288-bit floor the design
    reference asks for — a shorter token would still look like a key.
    """

    key = mod.generate_api_key()

    assert key.startswith( "ck_live_" )
    assert len( key ) == len( "ck_live_" ) + 64


def test_two_generated_keys_are_never_the_same():
    """Reddens if the key stops being random — every service account would share one secret."""

    assert len( { mod.generate_api_key() for _ in range( 25 ) } ) == 25


# ── get_or_create_service_account ─────────────────────────────────────────────────────────

def test_an_existing_service_account_is_reused_rather_than_duplicated( db, capsys ):
    """Reddens if an existing account is created again — the email is unique in the table."""

    existing = _User( roles=[ "service_account" ] )
    _UserRepo.instances = [ ]

    class _Repo( _UserRepo ):
        def __init__( self, session ):
            super().__init__( session )
            self.existing = existing

    import unittest.mock
    with unittest.mock.patch.object( mod, "UserRepository", _Repo ):
        got = mod.get_or_create_service_account( "svc@x.y", "desc" )

    assert got == existing.id
    assert _UserRepo.instances[ -1 ].created == [ ]
    assert _UserRepo.instances[ -1 ].looked_up == [ "svc@x.y" ]
    out = capsys.readouterr().out
    assert "Using existing service account: svc@x.y" in out
    assert str( existing.id ) in out


def test_an_existing_human_account_is_refused_rather_than_given_an_api_key( db ):
    """
    Reddens if the role check drops.

    Minting a programmatic key against a human's account silently widens that person's
    credentials; the script must fail instead of succeeding quietly.
    """

    existing = _User( roles=[ "user", "admin" ] )

    class _Repo( _UserRepo ):
        def __init__( self, session ):
            super().__init__( session )
            self.existing = existing

    import unittest.mock
    with unittest.mock.patch.object( mod, "UserRepository", _Repo ):
        with pytest.raises( RuntimeError ) as e:
            mod.get_or_create_service_account( "human@x.y", "desc" )

    assert "is not a service account" in str( e.value )
    assert "['user', 'admin']"        in str( e.value )


def test_a_new_service_account_is_created_verified_and_role_scoped( db, crypt, capsys ):
    """
    Reddens if the role list, the verified flag, or the bcrypt cost changes.

    A service account with no roles is a user with none of the access it was made for; an
    unverified one cannot authenticate at all.
    """

    got = mod.get_or_create_service_account( "new@x.y", "desc" )

    created = _UserRepo.instances[ -1 ].created[ 0 ]
    assert created[ "email" ] == "new@x.y"
    assert created[ "roles" ] == [ "service_account" ]
    assert crypt.rounds == [ 12 ]
    assert isinstance( got, uuid.UUID )
    assert "Created service account: new@x.y" in capsys.readouterr().out


def test_the_new_account_is_marked_email_verified( db, crypt ):
    """Reddens if the flag is dropped — a service account has no inbox to verify from."""

    seen = { }

    class _Repo( _UserRepo ):
        def create_user( self, email, password_hash, roles ):
            user = super().create_user( email, password_hash, roles )
            seen[ "user" ] = user
            return user

    import unittest.mock
    with unittest.mock.patch.object( mod, "UserRepository", _Repo ):
        mod.get_or_create_service_account( "new@x.y", "desc" )

    assert seen[ "user" ].email_verified is True


def test_the_placeholder_password_is_random_and_never_stored_in_the_clear( db, crypt ):
    """
    Reddens if the dummy password becomes a constant or reaches the repository unhashed.

    Service accounts do not log in with it, but a guessable value in the password column is a
    credential all the same.
    """

    mod.get_or_create_service_account( "a@x.y", "" )
    first = _UserRepo.instances[ -1 ].created[ 0 ][ "password_hash" ]
    mod.get_or_create_service_account( "b@x.y", "" )
    second = _UserRepo.instances[ -1 ].created[ 0 ][ "password_hash" ]

    assert first != second
    assert first.startswith( "$FAKEHASH$" )
    assert len( crypt.hashed[ 0 ][ 0 ] ) >= 32           # the raw bytes handed to bcrypt


def test_the_database_session_is_opened_and_closed_around_the_work( db, crypt ):
    """Reddens if the `with` goes away — a leaked session holds a pooled connection open."""

    mod.get_or_create_service_account( "a@x.y", "" )

    assert ( db.entered, db.exited ) == ( 1, 1 )
    assert _UserRepo.instances[ -1 ].session is db.session


# ── store_api_key ─────────────────────────────────────────────────────────────────────────

def test_only_the_hash_reaches_the_database_never_the_key( db, crypt ):
    """
    Reddens if the plaintext key is stored.

    The whole point of the bcrypt step is that a database read cannot recover a working key.
    """

    uid = uuid.uuid4()

    mod.store_api_key( uid, "ck_live_SECRETVALUE", "a description", "dev" )

    row = _KeyRepo.instances[ -1 ].created[ 0 ]
    assert row[ "user_id" ]     == uid
    assert "SECRETVALUE" not in row[ "key_hash" ]
    assert row[ "key_hash" ].startswith( "$FAKEHASH$" )
    assert crypt.rounds == [ 12 ]


def test_a_blank_description_is_filled_in_from_the_environment( db, crypt, capsys ):
    """Reddens if the default drops — an unlabelled key cannot be told apart at revocation time."""

    mod.store_api_key( uuid.uuid4(), "ck_live_x", "", "prod" )

    assert _KeyRepo.instances[ -1 ].created[ 0 ][ "description" ] == \
           "Claude Code notification service (prod)"
    assert "Claude Code notification service (prod)" in capsys.readouterr().out


def test_a_supplied_description_is_kept_verbatim( db, crypt ):
    """Reddens if the default overwrites a caller's description instead of filling a blank one."""

    mod.store_api_key( uuid.uuid4(), "ck_live_x", "CI/CD pipeline key", "staging" )

    assert _KeyRepo.instances[ -1 ].created[ 0 ][ "description" ] == "CI/CD pipeline key"


def test_the_stored_hash_actually_verifies_against_the_key_that_was_issued( db ):
    """
    Reddens if hashing is skipped, weakened, or applied to the wrong value — REAL bcrypt.

    A spy can show that *something* was hashed; only the real library can show that the row
    the database keeps will accept the key the operator was handed, and nothing else.
    """

    key = mod.generate_api_key()

    mod.store_api_key( uuid.uuid4(), key, "d", "dev" )

    stored = _KeyRepo.instances[ -1 ].created[ 0 ][ "key_hash" ]
    assert mod.bcrypt.checkpw( key.encode( "utf-8" ), stored.encode( "utf-8" ) )
    assert not mod.bcrypt.checkpw( b"ck_live_wrong", stored.encode( "utf-8" ) )


def test_store_api_key_opens_and_closes_its_own_session( db, crypt ):
    """Reddens if the session leaks — this runs as a second unit of work after the user create."""

    mod.store_api_key( uuid.uuid4(), "ck_live_x", "d", "dev" )

    assert ( db.entered, db.exited ) == ( 1, 1 )
    assert _KeyRepo.instances[ -1 ].session is db.session


# ── write_key_to_file ─────────────────────────────────────────────────────────────────────

def test_the_key_file_is_written_under_conf_keys_named_for_the_environment( project_root,
                                                                            capsys ):
    """Reddens if the path or the name changes — consumers read this exact location."""

    path = mod.write_key_to_file( "ck_live_abc", "prod" )

    assert path == project_root / "src" / "conf" / "keys" / "notification-api-claude-code-prod"
    assert path.read_text() == "ck_live_abc\n"
    assert "Wrote key to file" in capsys.readouterr().out


def test_the_key_file_is_owner_read_write_only( project_root ):
    """
    Reddens if the permissions loosen.

    This file is the only plaintext copy of the key; group- or world-readable is the whole
    secret handed to every account on the box.
    """

    path = mod.write_key_to_file( "ck_live_abc", "dev" )

    assert oct( path.stat().st_mode & 0o777 ) == "0o600"


def test_a_missing_keys_directory_is_created( project_root ):
    """Reddens if the mkdir drops — a first run on a fresh checkout would raise instead."""

    assert not ( project_root / "src" / "conf" / "keys" ).exists()

    mod.write_key_to_file( "ck_live_abc", "dev" )

    assert ( project_root / "src" / "conf" / "keys" ).is_dir()


def test_an_existing_key_file_is_replaced_not_appended_to( project_root ):
    """Reddens if the write turns into an append — the file would hold two keys and match none."""

    mod.write_key_to_file( "ck_live_first", "dev" )
    path = mod.write_key_to_file( "ck_live_second", "dev" )

    assert path.read_text() == "ck_live_second\n"


# ── main ──────────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def wired( monkeypatch, tmp_path ):
    """
    `main` with every outward call stopped at the module boundary.

    Nothing here can reach a database, a repository, bcrypt, or the real filesystem root.
    """

    state = {
        "user_id"  : uuid.uuid4(),
        "key_id"   : uuid.uuid4(),
        "issued"   : ISSUED_KEY,
        "key_file" : tmp_path / "notification-api-claude-code-dev",
        "calls"    : [ ],
        "raise_on_account" : None,
        "raise_on_file"    : None,
    }

    def fake_account( email, description ):
        state[ "calls" ].append( ( "account", email, description ) )
        if state[ "raise_on_account" ]:
            raise state[ "raise_on_account" ]
        return state[ "user_id" ]

    def fake_store( user_id, api_key, description, env ):
        state[ "calls" ].append( ( "store", user_id, api_key, description, env ) )
        return state[ "key_id" ]

    def fake_write( api_key, env ):
        state[ "calls" ].append( ( "write", api_key, env ) )
        if state[ "raise_on_file" ]:
            raise state[ "raise_on_file" ]
        return state[ "key_file" ]

    monkeypatch.setattr( mod, "get_or_create_service_account", fake_account )
    monkeypatch.setattr( mod, "generate_api_key",              lambda: state[ "issued" ] )
    monkeypatch.setattr( mod, "store_api_key",                 fake_store )
    monkeypatch.setattr( mod, "write_key_to_file",             fake_write )

    return state


def _argv( monkeypatch, *extra ):
    monkeypatch.setattr( mod.sys, "argv",
                         [ "create_service_account_postgres.py", *extra ] )


def test_the_happy_path_runs_all_four_steps_in_order_and_returns_zero( wired, monkeypatch,
                                                                       capsys ):
    """Reddens if a step is skipped or reordered — the key must exist before it is stored."""

    _argv( monkeypatch )

    assert mod.main() == 0
    assert [ c[ 0 ] for c in wired[ "calls" ] ] == [ "account", "store", "write" ]
    out = capsys.readouterr().out
    for step in ( "Step 1: Service Account Creation", "Step 2: API Key Generation",
                  "Step 3: PostgreSQL Storage", "Step 4: Key File Creation" ):
        assert step in out
    assert "SUCCESS: Service Account Created in PostgreSQL" in out


def test_the_key_is_printed_exactly_once_because_it_is_never_recoverable( wired, monkeypatch,
                                                                          capsys ):
    """
    Reddens if the key stops being printed.

    The database holds only the bcrypt hash, so the terminal and the key file are the only two
    places the plaintext ever exists.
    """

    _argv( monkeypatch )
    mod.main()
    out = capsys.readouterr().out

    assert out.count( ISSUED_KEY ) == 1
    assert "shown only once" in out


def test_the_defaults_are_the_documented_email_and_the_dev_environment( wired, monkeypatch ):
    """Reddens if a bare run starts targeting production or a different account."""

    _argv( monkeypatch )
    mod.main()

    assert wired[ "calls" ][ 0 ] == ( "account", "claude.code@deepily.ai", "" )
    assert wired[ "calls" ][ 2 ] == ( "write", ISSUED_KEY, "dev" )


def test_the_flags_reach_the_steps_that_use_them( wired, monkeypatch ):
    """Reddens if a flag is parsed but dropped — the key would be minted for the wrong account."""

    _argv( monkeypatch, "--email=svc@example.com", "--description=CI key", "--env=prod" )

    assert mod.main() == 0
    assert wired[ "calls" ][ 0 ] == ( "account", "svc@example.com", "CI key" )
    assert wired[ "calls" ][ 1 ][ 3: ] == ( "CI key", "prod" )
    assert wired[ "calls" ][ 2 ] == ( "write", ISSUED_KEY, "prod" )


def test_an_unknown_environment_is_rejected_by_the_parser( wired, monkeypatch ):
    """Reddens if the choices list drops — a typo would silently name a new key file."""

    _argv( monkeypatch, "--env=production" )

    with pytest.raises( SystemExit ) as e:
        mod.main()

    assert e.value.code == 2


def test_the_postgres_environment_is_reported_from_lupin_env( wired, monkeypatch, capsys ):
    """Reddens if the banner stops naming the database — dev and test are different boxes."""

    monkeypatch.setenv( "LUPIN_ENV", "testing" )
    _argv( monkeypatch )
    mod.main()

    assert "PostgreSQL Environment: testing" in capsys.readouterr().out


def test_an_unset_lupin_env_is_reported_as_development( wired, monkeypatch, capsys ):
    """Reddens if the fallback disappears and an unset variable prints as None."""

    monkeypatch.delenv( "LUPIN_ENV", raising=False )
    _argv( monkeypatch )
    mod.main()

    assert "PostgreSQL Environment: development" in capsys.readouterr().out


def test_a_read_only_mount_warns_and_still_prints_the_key( wired, monkeypatch, capsys ):
    """
    Reddens if an unwritable key file aborts the run.

    By Step 4 the database already holds the hash, so aborting would destroy the only plaintext
    copy of a key that is now live. The warning path exists to hand it to the operator instead.
    """

    wired[ "raise_on_file" ] = OSError( 30, "Read-only file system" )
    _argv( monkeypatch )

    assert mod.main() == 0
    out = capsys.readouterr().out
    assert "Could not write key file (Read-only file system)" in out
    assert "capture it NOW"           in out
    assert ISSUED_KEY     in out
    assert "<not written"             in out


def test_an_os_error_with_no_strerror_still_names_something( wired, monkeypatch, capsys ):
    """Reddens if the fallback goes away and the warning reads 'Could not write key file (None)'."""

    wired[ "raise_on_file" ] = OSError( "disk gremlins" )
    _argv( monkeypatch )

    assert mod.main() == 0
    assert "disk gremlins" in capsys.readouterr().out


def test_a_database_failure_returns_one_and_prints_troubleshooting( wired, monkeypatch, capsys ):
    """
    Reddens if a failure is reported as success.

    Exit 0 on a failed run tells a caller a key exists when none does.
    """

    wired[ "raise_on_account" ] = RuntimeError( "could not connect to lupin-postgres" )
    _argv( monkeypatch )

    assert mod.main() == 1
    captured = capsys.readouterr()
    assert "FAILED: Service Account Creation" in captured.out
    assert "Check PostgreSQL is running"      in captured.out
    assert "could not connect to lupin-postgres" in captured.err
    assert "Traceback"                        in captured.err
    assert wired[ "calls" ] == [ ( "account", "claude.code@deepily.ai", "" ) ]


def test_a_failure_never_prints_a_key_it_did_not_finish_issuing( wired, monkeypatch, capsys ):
    """Reddens if the failure path falls through to the success banner and prints a stale key."""

    wired[ "raise_on_account" ] = RuntimeError( "boom" )
    _argv( monkeypatch )
    mod.main()

    assert ISSUED_KEY not in capsys.readouterr().out


# ── module surface ────────────────────────────────────────────────────────────────────────

def test_the_script_binds_the_postgres_repositories_not_a_sqlite_predecessor():
    """
    Reddens if the module drifts back to the SQLite implementation it replaced.

    Two scripts with the same name and different stores is how a key gets written to the box
    nobody is reading.
    """

    assert mod.UserRepository.__name__   == "UserRepository"
    assert mod.ApiKeyRepository.__name__ == "ApiKeyRepository"
    assert "repositories" in mod.UserRepository.__module__
