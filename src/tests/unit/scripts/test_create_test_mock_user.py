"""
Tests for create_test_mock_user.py, the test-mock-jobs account creator.

They run without a database and without a real password. This script has three differences
from the admin-account sibling. Its roles are ["user"] only. A new account is marked
email-verified. An existing account is reset, not promoted.

Notes for the next reader:
- Every outward seam (get_db, UserRepository, hash_password, validate_password_strength) is
  patched on the module, so a missed patch fails loudly and never writes to a real database.
- Every credential is an obvious fake assembled from parts.
- The bootstrap block is reached by re-running the source with runpy under a changed
  environment, because LUPIN_ROOT is read at import time.
- The roles are compared to a literal tuple, not to the script's constant. Widening the
  constant to include "admin" then reddens the tests.
"""

import importlib.util
import os
import runpy
import sys

import pytest


_ROOT       = os.environ.get( "LUPIN_ROOT", os.getcwd() )
SCRIPT_PATH = os.path.join( _ROOT, "src", "scripts", "create_test_mock_user.py" )

for _p in ( os.path.join( _ROOT, "src", "scripts" ), os.path.join( _ROOT, "src" ) ):
    if _p not in sys.path:
        sys.path.insert( 0, _p )

_spec = importlib.util.spec_from_file_location( "create_test_mock_user", SCRIPT_PATH )
mod   = importlib.util.module_from_spec( _spec )
_spec.loader.exec_module( mod )


_EMAIL_VAR = "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL"
_PW_VAR    = "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD"

# Obvious fakes, assembled from parts.
_EMAIL = "mock.user.fake@lupin.deepily.ai"
_PW    = "not" + "-a-real-" + "secret"
_HASH  = "$2b$12$" + "x" * 22 + "obviouslyfake" + "x" * 18


class _User:
    """The attributes the script reads back off a repository result, and an id."""
    def __init__( self, email, roles, uid=7 ):
        self.email = email
        self.roles = roles
        self.id    = uid


class _Repo:
    """
    Recording stand-in for UserRepository.

    Ensures:
        - every call the script makes is recorded in `calls` in order
        - `get_by_email` returns whatever `existing` was constructed with, the single switch
          between the create path and the reset path
    """
    def __init__( self, session, existing=None ):
        self.session  = session
        self.existing = existing
        self.calls    = [ ]

    def get_by_email( self, email ):
        self.calls.append( ( "get_by_email", email ) )
        return self.existing

    def create_user( self, email, password_hash, roles ):
        self.calls.append( ( "create_user", email, password_hash, tuple( roles ) ) )
        return _User( email, list( roles ), uid=21 )

    def mark_email_verified( self, uid ):
        self.calls.append( ( "mark_email_verified", uid ) )
        email = self.existing.email if self.existing is not None else _EMAIL
        return _User( email, [ "user" ], uid )

    def update_password( self, uid, password_hash ):
        self.calls.append( ( "update_password", uid, password_hash ) )

    def update_roles( self, uid, roles ):
        self.calls.append( ( "update_roles", uid, tuple( roles ) ) )

    def activate( self, uid ):
        self.calls.append( ( "activate", uid ) )


class _Session:
    """Minimal session — the script's only use of it is `commit`."""
    def __init__( self ):
        self.commits = 0

    def commit( self ):
        self.commits += 1

    def __enter__( self ):
        return self

    def __exit__( self, *exc ):
        return False


@pytest.fixture
def wired( monkeypatch ):
    """
    Patch every outward seam and hand back the objects the assertions read.

    Ensures:
        - no database connection is opened and no password is ever hashed for real
        - returns ( session, holder ) where holder[ "repo" ] is the repository the script built
    """
    session = _Session()
    holder  = { "repo": None, "existing": None }

    def make_repo( sess ):
        holder[ "repo" ] = _Repo( sess, existing=holder[ "existing" ] )
        return holder[ "repo" ]

    monkeypatch.setattr( mod, "get_db",                     lambda: session )
    monkeypatch.setattr( mod, "UserRepository",             make_repo )
    monkeypatch.setattr( mod, "hash_password",              lambda pw: _HASH )
    monkeypatch.setattr( mod, "validate_password_strength", lambda pw: ( True, "" ) )
    return session, holder


@pytest.fixture
def creds( monkeypatch ):
    """Set both credential variables to the fakes above."""
    monkeypatch.setenv( _EMAIL_VAR, _EMAIL )
    monkeypatch.setenv( _PW_VAR,    _PW    )


# ── the missing-variable branches ────────────────────────────────────────────

@pytest.mark.parametrize( "unset,named", [
    ( [ _EMAIL_VAR           ], [ _EMAIL_VAR           ] ),
    ( [ _PW_VAR              ], [ _PW_VAR              ] ),
    ( [ _EMAIL_VAR, _PW_VAR  ], [ _EMAIL_VAR, _PW_VAR  ] ),
] )
def test_missing_variables_exit_one_and_name_every_one_missing( unset, named, creds, monkeypatch, capsys ):
    """An unset variable is a refusal, and the message names every missing one."""
    for name in unset:
        monkeypatch.delenv( name )

    assert mod.main() == 1

    err = capsys.readouterr().err
    for name in named:
        assert name in err


def test_empty_string_counts_as_missing( creds, monkeypatch, capsys ):
    """The guard is falsiness, so an exported-but-empty variable is refused too."""
    monkeypatch.setenv( _PW_VAR, "" )

    assert mod.main() == 1
    assert _PW_VAR in capsys.readouterr().err


def test_no_database_is_touched_when_a_variable_is_missing( creds, monkeypatch ):
    """The refusal comes before `get_db`; a bomb in its place proves it was never reached."""
    monkeypatch.delenv( _EMAIL_VAR )

    def bomb():
        raise AssertionError( "get_db must not be reached when a variable is missing" )

    monkeypatch.setattr( mod, "get_db", bomb )

    assert mod.main() == 1


# ── the password-policy branch ───────────────────────────────────────────────

def test_weak_password_is_refused_by_the_live_policy( wired, creds, monkeypatch, capsys ):
    """The script defers to `validate_password_strength`; the rejection reason is passed through."""
    monkeypatch.setattr( mod, "validate_password_strength", lambda pw: ( False, "too short" ) )

    assert mod.main() == 1
    assert "too short" in capsys.readouterr().err


def test_rejected_password_is_not_echoed( wired, creds, monkeypatch, capsys ):
    """The password is never echoed, least of all in the message that explains its rejection."""
    monkeypatch.setattr( mod, "validate_password_strength", lambda pw: ( False, "too short" ) )

    mod.main()

    captured = capsys.readouterr()
    assert _PW not in captured.out
    assert _PW not in captured.err


def test_no_database_is_touched_when_the_password_is_rejected( creds, monkeypatch ):
    """The policy check also precedes `get_db` — same bomb, second gate."""
    monkeypatch.setattr( mod, "validate_password_strength", lambda pw: ( False, "nope" ) )

    def bomb():
        raise AssertionError( "get_db must not be reached when the password is rejected" )

    monkeypatch.setattr( mod, "get_db", bomb )

    assert mod.main() == 1


# ── the create path ──────────────────────────────────────────────────────────

def test_absent_account_is_created_with_the_user_role_only_and_verified( wired, creds, capsys ):
    """A missing account is created with ["user"] only, then email-verified."""
    session, holder = wired

    assert mod.main() == 0

    assert holder[ "repo" ].calls == [
        ( "get_by_email",       _EMAIL ),
        ( "create_user",        _EMAIL, _HASH, ( "user", ) ),
        ( "mark_email_verified", 21 ),
    ]
    assert session.commits == 1
    assert "created" in capsys.readouterr().out


def test_created_account_hashes_the_password_rather_than_storing_it( wired, creds, capsys ):
    """What reaches `create_user` is the hash, and the password appears nowhere in the output."""
    _, holder = wired

    mod.main()

    ( _, _, stored_hash, _ ) = holder[ "repo" ].calls[ 1 ]
    assert stored_hash == _HASH
    assert _PW not in capsys.readouterr().out


# ── the reset path ───────────────────────────────────────────────────────────

def test_existing_account_is_reset_in_place( wired, creds, capsys ):
    """An existing admin account is reset to ["user"], not duplicated."""
    session, holder = wired
    holder[ "existing" ] = _User( _EMAIL, [ "user", "admin" ], uid=11 )

    assert mod.main() == 0

    assert holder[ "repo" ].calls == [
        ( "get_by_email",        _EMAIL ),
        ( "update_password",     11, _HASH ),
        ( "update_roles",        11, ( "user", ) ),
        ( "activate",            11 ),
        ( "mark_email_verified", 11 ),
    ]
    assert session.commits == 1
    assert "reset" in capsys.readouterr().out


def test_reset_is_idempotent_for_an_account_already_in_shape( wired, creds ):
    """A second run on an account already in shape ends the same way."""
    _, holder = wired
    holder[ "existing" ] = _User( _EMAIL, [ "user" ], uid=11 )

    assert mod.main() == 0
    assert holder[ "repo" ].calls[ -1 ] == ( "mark_email_verified", 11 )


def test_roles_constant_is_the_plain_user_role_only( ):
    """USER_ROLES is exactly ["user"]: this account must stay non-admin."""
    assert mod.USER_ROLES == [ "user" ]


# ── module-level bootstrap and the __main__ block ────────────────────────────

def test_missing_lupin_root_refuses_at_import( monkeypatch ):
    """The bootstrap raises rather than guessing a root, reached by re-executing the source."""
    monkeypatch.delenv( "LUPIN_ROOT", raising=False )

    with pytest.raises( RuntimeError, match="LUPIN_ROOT" ):
        runpy.run_path( SCRIPT_PATH, run_name="not_main" )


def test_src_path_is_not_inserted_twice( monkeypatch ):
    """The insert is guarded, so `src` already on the path is not added twice."""
    monkeypatch.setenv( "LUPIN_ROOT", _ROOT )
    src = os.path.join( _ROOT, "src" )
    monkeypatch.setattr( sys, "path", [ src ] + list( sys.path ) )
    before = list( sys.path ).count( src )

    runpy.run_path( SCRIPT_PATH, run_name="not_main" )

    assert list( sys.path ).count( src ) == before


def test_src_path_is_inserted_when_absent( monkeypatch ):
    """With `src` off the path, re-executing the bootstrap puts it first."""
    monkeypatch.setenv( "LUPIN_ROOT", _ROOT )
    src = os.path.join( _ROOT, "src" )
    monkeypatch.setattr( sys, "path", [ p for p in sys.path if p != src ] )

    runpy.run_path( SCRIPT_PATH, run_name="not_main" )

    assert sys.path[ 0 ] == src


def test_main_block_exits_with_the_return_code( monkeypatch ):
    """The `__main__` block turns the return code into the exit code; run with credentials unset."""
    monkeypatch.setenv( "LUPIN_ROOT", _ROOT )
    monkeypatch.delenv( _EMAIL_VAR, raising=False )
    monkeypatch.delenv( _PW_VAR,    raising=False )

    with pytest.raises( SystemExit ) as exit_info:
        runpy.run_path( SCRIPT_PATH, run_name="__main__" )

    assert exit_info.value.code == 1
