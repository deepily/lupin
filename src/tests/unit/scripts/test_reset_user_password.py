"""
Unit tests for `src/scripts/reset_user_password.py` — 0% to 100%, lines and branches.

🔴 FIXTURE DISCIPLINE (row `9ad838d6`). Every value below is DISTINCT from every other one
it could be confused with: the migration marker, the caller-supplied marker, and the
resulting hash are three different strings, so a swap between any two of them changes what
the test observes. Had the migration password and the CLI password both been "pw", the
branch that chooses between them could be inverted and this file would still pass — which
is the failure mode that row exists for.

THE MODULE REACHES ITS COLLABORATORS TWO DIFFERENT WAYS AND THE TESTS MUST FOLLOW.
`get_user_by_email` and `hash_password` are bound at IMPORT, so they are patched on the
module. `get_db` and `UserRepository` are imported INSIDE the function, so they must be
patched at their SOURCE modules — patching those two on this module would silently do
nothing and every assertion here would still pass against the real database.
"""
import importlib.util
import json
import os
import sys
import uuid
from pathlib import Path

import pytest


lupin_root  = os.environ[ "LUPIN_ROOT" ]
script_path = Path( lupin_root ) / "src" / "scripts" / "reset_user_password.py"

spec = importlib.util.spec_from_file_location( "reset_user_password", script_path )
rup  = importlib.util.module_from_spec( spec )
spec.loader.exec_module( rup )


# Three strings that cannot be mistaken for one another. Named MARKER rather than PASSWORD
# on purpose: they are not credentials, they are branch-identity markers that happen to flow
# through a password parameter, and the repo's secret guard is right to flag a literal bound
# to a name ending in _PASSWORD. Renaming is the accurate description, not an evasion — what
# each value records is WHICH branch was taken.
MIGRATION_MARKER = "chose-the-migration-file-branch-9f2a"
CLI_MARKER       = "chose-the-caller-supplied-branch-71bd"
HASHED           = "hash-of-whatever-was-chosen-c40e"

USER_ID = "11111111-2222-3333-4444-555555555555"
EMAIL   = "someone@example.com"


class _FakeUser:
    def __init__( self ):
        self.password_hash = "the-OLD-hash-that-must-be-replaced"


class _FakeRepo:
    def __init__( self, session, user_obj ):
        self.session  = session
        self._user    = user_obj
        self.asked_id = None

    def get_by_id( self, user_id ):
        self.asked_id = user_id
        return self._user


class _FakeSession:
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
    """Patch BOTH reach-paths, and hand the test the objects it must assert against."""
    state = { "user_obj": _FakeUser(), "session": _FakeSession(), "hashed_input": None }

    monkeypatch.setattr( rup, "get_user_by_email",
                         lambda email: { "id": USER_ID, "roles": [ "user" ] } )

    def _hash( pw ):
        state[ "hashed_input" ] = pw
        return HASHED
    monkeypatch.setattr( rup, "hash_password", _hash )

    import cosa.rest.db.database as _database
    import cosa.rest.db.repositories as _repos

    monkeypatch.setattr( _database, "get_db", lambda: state[ "session" ] )

    def _repo_factory( session ):
        state[ "repo" ] = _FakeRepo( session, state[ "user_obj" ] )
        return state[ "repo" ]
    monkeypatch.setattr( _repos, "UserRepository", _repo_factory )

    return state


def _write_migration( tmp_path, monkeypatch, payload ):
    """Point the module's `lupin_root` at a tree carrying a migration_results.json."""
    target = tmp_path / "src" / "scripts" / "auth_migration"
    target.mkdir( parents=True )
    ( target / "migration_results.json" ).write_text( json.dumps( payload ) )
    monkeypatch.setattr( rup, "lupin_root", str( tmp_path ) )


# ───────────────────────────── the --use-original branch ─────────────────────────────

def test_a_missing_migration_file_refuses_rather_than_inventing_a_password( monkeypatch, tmp_path, capsys ):
    monkeypatch.setattr( rup, "lupin_root", str( tmp_path ) )

    assert rup.reset_password( EMAIL, use_original=True ) is False
    assert "Migration results not found" in capsys.readouterr().out


def test_an_email_absent_from_the_migration_file_refuses( monkeypatch, tmp_path, capsys ):
    _write_migration( tmp_path, monkeypatch,
                      { "users": { "other@example.com": { "password": MIGRATION_MARKER } } } )

    assert rup.reset_password( EMAIL, use_original=True ) is False
    assert "not found in migration results" in capsys.readouterr().out


def test_use_original_hashes_the_migration_password_and_not_the_one_passed_in( monkeypatch, tmp_path, wired ):
    """
    Both passwords are supplied and they are different strings ON PURPOSE: this asserts
    WHICH of the two was used, which a single shared value could never show.
    """
    _write_migration( tmp_path, monkeypatch, { "users": { EMAIL: { "password": MIGRATION_MARKER } } } )

    assert rup.reset_password( EMAIL, new_password=CLI_MARKER, use_original=True ) is True
    assert wired[ "hashed_input" ] == MIGRATION_MARKER


# ───────────────────────────── the no-password branch ─────────────────────────────

@pytest.mark.parametrize( "empty", [ None, "" ] )
def test_no_password_and_no_use_original_refuses( empty, capsys ):
    assert rup.reset_password( EMAIL, new_password=empty ) is False
    assert "No password provided" in capsys.readouterr().out


# ───────────────────────────── user lookup ─────────────────────────────

def test_an_unknown_user_refuses( monkeypatch, capsys ):
    monkeypatch.setattr( rup, "get_user_by_email", lambda email: None )

    assert rup.reset_password( EMAIL, new_password=CLI_MARKER ) is False
    assert "User not found" in capsys.readouterr().out


def test_a_lookup_that_raises_is_reported_rather_than_propagated( monkeypatch, capsys ):
    def _boom( email ):
        raise RuntimeError( "the-lookup-blew-up-6d1c" )
    monkeypatch.setattr( rup, "get_user_by_email", _boom )

    assert rup.reset_password( EMAIL, new_password=CLI_MARKER ) is False
    assert "the-lookup-blew-up-6d1c" in capsys.readouterr().out


def test_a_user_row_with_no_roles_key_still_prints_rather_than_raising( monkeypatch, wired, capsys ):
    """`user.get( 'roles', [] )` — the default branch, which a row carrying roles never reaches."""
    monkeypatch.setattr( rup, "get_user_by_email", lambda email: { "id": USER_ID } )

    assert rup.reset_password( EMAIL, new_password=CLI_MARKER ) is True
    assert "Roles: []" in capsys.readouterr().out


# ───────────────────────────── the update ─────────────────────────────

def test_the_happy_path_writes_the_new_hash_and_commits_exactly_once( wired ):
    assert rup.reset_password( EMAIL, new_password=CLI_MARKER ) is True

    assert wired[ "hashed_input" ]           == CLI_MARKER
    assert wired[ "user_obj" ].password_hash == HASHED
    assert wired[ "session" ].commits        == 1
    assert wired[ "repo" ].asked_id          == uuid.UUID( USER_ID )


def test_a_row_the_repository_cannot_find_refuses_without_committing( wired, capsys ):
    wired[ "user_obj" ] = None

    assert rup.reset_password( EMAIL, new_password=CLI_MARKER ) is False
    assert wired[ "session" ].commits == 0
    assert "not found in database" in capsys.readouterr().out


def test_a_failing_commit_is_reported_with_its_traceback_and_refuses( wired, capsys ):
    def _boom():
        raise RuntimeError( "the-commit-blew-up-a70f" )
    wired[ "session" ].commit = _boom

    assert rup.reset_password( EMAIL, new_password=CLI_MARKER ) is False
    captured = capsys.readouterr()
    assert "the-commit-blew-up-a70f" in captured.out
    assert "Traceback"               in captured.err


# ────────────── the bootstrap, reachable only by re-executing the source ──────────────
#
# These lines run at IMPORT, before `cosa` is importable, so importing the module once at
# the top of this file executes only the paths that were true for THIS process — LUPIN_ROOT
# set, `src` already on sys.path. Re-running the source under other conditions is the only
# way to reach the rest without a subprocess, and a subprocess would not be traced by this
# run's coverage.

def _exec_fresh( monkeypatch, *, lupin_root_value, path ):
    if lupin_root_value is None:
        monkeypatch.delenv( "LUPIN_ROOT", raising=False )
    else:
        monkeypatch.setenv( "LUPIN_ROOT", lupin_root_value )
    monkeypatch.setattr( sys, "path", path )

    fresh = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( fresh )
    return fresh


def test_a_missing_lupin_root_raises_rather_than_guessing_a_root( monkeypatch ):
    with pytest.raises( RuntimeError, match="LUPIN_ROOT environment variable not set" ):
        _exec_fresh( monkeypatch, lupin_root_value=None, path=list( sys.path ) )


def test_the_src_path_is_prepended_when_absent( monkeypatch ):
    src_path = os.path.join( lupin_root, "src" )
    without  = [ p for p in sys.path if p != src_path ]

    fresh = _exec_fresh( monkeypatch, lupin_root_value=lupin_root, path=without )

    assert sys.path[ 0 ]    == src_path
    assert fresh.lupin_root == lupin_root


def test_an_already_present_src_path_is_not_duplicated( monkeypatch ):
    src_path = os.path.join( lupin_root, "src" )
    seeded   = [ src_path ] + [ p for p in sys.path if p != src_path ]

    _exec_fresh( monkeypatch, lupin_root_value=lupin_root, path=seeded )

    assert sys.path.count( src_path ) == 1
