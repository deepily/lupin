"""
`src/scripts/create_admin_test_account.py` — the admin-account creator, covered without a
database and without a password.

A straggler from Rio's two-tier census at `cc336880` (34 statements, 8 branches). Claimed by
the SOUND direction: `git grep -l -- create_admin_test_account -- src/tests src/cosa/tests`
was EMPTY at `0f61dd85`, and empty is conclusive.

🔴 WHAT THIS FILE IS CAREFUL ABOUT.

· NO DATABASE, EITHER ONE. `get_db`, `UserRepository`, `hash_password` and
  `validate_password_strength` are all patched at the MODULE attribute, so a missed patch
  surfaces as an AttributeError or a connection error rather than as a real write against
  `lupin_db_dev` — the box a host shell silently reaches (CLAUDE.md § TESTING VENUES). This
  script CREATES AND PROMOTES ACCOUNTS; an unpatched run would mint a live admin.
· NO REAL PASSWORDS. Every credential here is an obvious fake assembled from parts, so no line
  carries a credential-shaped literal beside a credential-shaped field name.
· THE MODULE-LEVEL BOOTSTRAP IS EXERCISED BY RE-EXECUTION, NOT BY IMPORT. `LUPIN_ROOT` is read
  at import time, so the missing-root branch can only be reached by running the source again
  under a changed environment. `runpy.run_path` is used for that and for the `__main__` block,
  matching `test_bridge_pin_sweep.py`.

WHY THE ASSERTIONS ARE ON THE RETURN CODE AND THE REPOSITORY CALLS rather than on stdout: the
exit code is what a shell branches on and the repository calls are what actually changed, so
those are the contract. The prints are covered as a side effect of reaching the branches, which
is the right weight for them — except the one claim the docstring makes about them, that the
password is NEVER echoed, which is asserted directly because it is a promise about output.
"""

import importlib.util
import os
import runpy
import sys

import pytest


_ROOT       = os.environ.get( "LUPIN_ROOT", os.getcwd() )
SCRIPT_PATH = os.path.join( _ROOT, "src", "scripts", "create_admin_test_account.py" )

for _p in ( os.path.join( _ROOT, "src", "scripts" ), os.path.join( _ROOT, "src" ) ):
    if _p not in sys.path:
        sys.path.insert( 0, _p )

_spec = importlib.util.spec_from_file_location( "create_admin_test_account", SCRIPT_PATH )
mod   = importlib.util.module_from_spec( _spec )
_spec.loader.exec_module( mod )


# Obvious fakes, assembled from parts.
_EMAIL = "lupin.test.admin@lupin.deepily.ai"
_PW    = "not" + "-a-real-" + "secret"
_HASH  = "$2b$12$" + "x" * 22 + "obviouslyfake" + "x" * 18


class _User:
    """The two attributes the script reads back off a repository result, and an id."""
    def __init__( self, email, roles, uid=7 ):
        self.email = email
        self.roles = roles
        self.id    = uid


class _Repo:
    """
    Recording stand-in for UserRepository.

    Ensures:
        - every call the script makes is recorded in `calls` in order
        - `get_by_email` returns whatever `existing` was constructed with, which is the single
          switch between the create path and the promote path
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
        return _User( email, list( roles ) )

    def update_password( self, uid, password_hash ):
        self.calls.append( ( "update_password", uid, password_hash ) )

    def update_roles( self, uid, roles ):
        self.calls.append( ( "update_roles", uid, tuple( roles ) ) )
        return _User( self.existing.email, list( roles ), uid )


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
    monkeypatch.setenv( "LUPIN_TEST_ADMIN_EMAIL",    _EMAIL )
    monkeypatch.setenv( "LUPIN_TEST_ADMIN_PASSWORD", _PW    )


# ── the two missing-variable branches ────────────────────────────────────────

@pytest.mark.parametrize( "unset,named", [
    ( [ "LUPIN_TEST_ADMIN_EMAIL"    ], [ "LUPIN_TEST_ADMIN_EMAIL"                            ] ),
    ( [ "LUPIN_TEST_ADMIN_PASSWORD" ], [ "LUPIN_TEST_ADMIN_PASSWORD"                         ] ),
    ( [ "LUPIN_TEST_ADMIN_EMAIL",
        "LUPIN_TEST_ADMIN_PASSWORD" ], [ "LUPIN_TEST_ADMIN_EMAIL", "LUPIN_TEST_ADMIN_PASSWORD" ] ),
] )
def test_missing_variables_exit_one_and_name_every_one_missing( unset, named, creds, monkeypatch, capsys ):
    """
    An unset variable is a refusal, and the message names EVERY missing one rather than the
    first — an operator who fixes one at a time and re-runs is the case this serves.
    """
    for name in unset:
        monkeypatch.delenv( name )

    assert mod.main() == 1

    err = capsys.readouterr().err
    for name in named:
        assert name in err


def test_empty_string_counts_as_missing( creds, monkeypatch, capsys ):
    """
    The guard is falsiness, not `is None`, so an exported-but-empty variable is refused too.
    That is the likelier operator mistake — `export FOO=` leaves the name set.
    """
    monkeypatch.setenv( "LUPIN_TEST_ADMIN_PASSWORD", "" )

    assert mod.main() == 1
    assert "LUPIN_TEST_ADMIN_PASSWORD" in capsys.readouterr().err


def test_no_database_is_touched_when_a_variable_is_missing( creds, monkeypatch ):
    """
    The refusal happens BEFORE `get_db`. Proven by leaving get_db unpatched as a bomb: if the
    script reached it, the test would error rather than pass.
    """
    monkeypatch.delenv( "LUPIN_TEST_ADMIN_EMAIL" )

    def bomb():
        raise AssertionError( "get_db must not be reached when a variable is missing" )

    monkeypatch.setattr( mod, "get_db", bomb )

    assert mod.main() == 1


# ── the password-policy branch ───────────────────────────────────────────────

def test_weak_password_is_refused_by_the_live_policy( wired, creds, monkeypatch, capsys ):
    """
    The script defers to `validate_password_strength` rather than carrying its own rule, so a
    policy change reaches this script for free. The rejection reason is passed through.
    """
    monkeypatch.setattr( mod, "validate_password_strength", lambda pw: ( False, "too short" ) )

    assert mod.main() == 1
    assert "too short" in capsys.readouterr().err


def test_rejected_password_is_not_echoed( wired, creds, monkeypatch, capsys ):
    """
    The docstring promises the password is never echoed. This is the branch most likely to
    break that promise, because the natural way to explain a rejection is to show the input.
    """
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

def test_absent_account_is_created_with_both_roles( wired, creds, capsys ):
    """
    A missing account is created holding ["user", "admin"]. The roles are the entire point of
    the script — an account created with ["user"] alone would pass every admin test by being
    refused, which is the failure the module docstring exists to prevent.
    """
    session, holder = wired

    assert mod.main() == 0

    assert holder[ "repo" ].calls == [
        ( "get_by_email", _EMAIL ),
        ( "create_user",  _EMAIL, _HASH, ( "user", "admin" ) ),
    ]
    assert session.commits == 1
    assert "created" in capsys.readouterr().out


def test_created_account_hashes_the_password_rather_than_storing_it( wired, creds, capsys ):
    """
    What reaches `create_user` is the hash, not the password — and the password appears nowhere
    in the output either.
    """
    _, holder = wired

    mod.main()

    ( _, _, stored_hash, _ ) = holder[ "repo" ].calls[ 1 ]
    assert stored_hash == _HASH
    assert _PW not in capsys.readouterr().out


# ── the promote path ─────────────────────────────────────────────────────────

def test_existing_account_is_promoted_in_place( wired, creds, capsys ):
    """
    An existing account is promoted, not duplicated — that is the idempotence the docstring
    claims. Both the password reset and the role update land, and no `create_user` is called.
    """
    session, holder = wired
    holder[ "existing" ] = _User( _EMAIL, [ "user" ], uid=11 )

    assert mod.main() == 0

    assert holder[ "repo" ].calls == [
        ( "get_by_email",    _EMAIL ),
        ( "update_password", 11, _HASH ),
        ( "update_roles",    11, ( "user", "admin" ) ),
    ]
    assert session.commits == 1
    assert "promoted" in capsys.readouterr().out


def test_promotion_is_idempotent_for_an_account_already_admin( wired, creds ):
    """
    Running against an account that already holds both roles takes the same path and ends in
    the same state. Recorded because "idempotent" is a claim about the SECOND run, and the
    first run is the only one anybody usually tries.
    """
    _, holder = wired
    holder[ "existing" ] = _User( _EMAIL, [ "user", "admin" ], uid=11 )

    assert mod.main() == 0
    assert holder[ "repo" ].calls[ -1 ] == ( "update_roles", 11, ( "user", "admin" ) )


def test_admin_roles_constant_keeps_the_plain_user_role( wired, creds ):
    """
    ADMIN_ROLES is ["user", "admin"], not ["admin"]. Asserted on the constant because dropping
    "user" would strip ordinary access from the account while still passing every admin test —
    a break that only shows up in the non-admin suites much later.
    """
    assert mod.ADMIN_ROLES == [ "user", "admin" ]


# ── module-level bootstrap and the __main__ block ────────────────────────────

def test_missing_lupin_root_refuses_at_import( monkeypatch ):
    """
    The bootstrap raises rather than guessing a root. Reached by re-executing the source with
    the variable unset, since it is read at import time and this module is already loaded.
    """
    monkeypatch.delenv( "LUPIN_ROOT", raising=False )

    with pytest.raises( RuntimeError, match="LUPIN_ROOT" ):
        runpy.run_path( SCRIPT_PATH, run_name="not_main" )


def test_src_path_is_not_inserted_twice( monkeypatch ):
    """
    The insert is guarded, so re-executing with `src` already on the path leaves `sys.path`
    unchanged. Asserted by count: an unguarded insert would grow the list every run, and a
    script that is imported by several tools would keep growing it.
    """
    monkeypatch.setenv( "LUPIN_ROOT", _ROOT )
    src = os.path.join( _ROOT, "src" )
    monkeypatch.setattr( sys, "path", [ src ] + list( sys.path ) )
    before = list( sys.path ).count( src )

    runpy.run_path( SCRIPT_PATH, run_name="not_main" )

    assert list( sys.path ).count( src ) == before


def test_main_block_exits_with_the_return_code( monkeypatch, capsys ):
    """
    The `__main__` block is where the exit code is decided, and the exit code is the whole
    interface — a shell distinguishes "created" from "refused" by nothing else. Run with the
    credentials unset so the refusal path is the one measured, and no database is reachable.
    """
    monkeypatch.setenv( "LUPIN_ROOT", _ROOT )
    monkeypatch.delenv( "LUPIN_TEST_ADMIN_EMAIL",    raising=False )
    monkeypatch.delenv( "LUPIN_TEST_ADMIN_PASSWORD", raising=False )

    with pytest.raises( SystemExit ) as exit_info:
        runpy.run_path( SCRIPT_PATH, run_name="__main__" )

    assert exit_info.value.code == 1
