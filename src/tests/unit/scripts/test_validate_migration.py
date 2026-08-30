"""
`src/scripts/auth_migration/validate_migration.py` — covered without a database.

A straggler from the ledger at `ea178d32`. Confirmed by the SOUND direction Pocholo names
there: `git grep -l -- validate_migration -- src/tests src/cosa/tests` is EMPTY, and empty is
conclusive — nothing named cannot be loaded. (A HIT would have proven nothing.)

🔴 WHAT THIS FILE IS CAREFUL ABOUT.

· NO DATABASE, EITHER ONE. `get_user_by_email` and `verify_password` are patched at the MODULE
  attribute, so a missed patch surfaces as an error rather than a read against `lupin_db_dev` —
  the box a host shell silently reaches (CLAUDE.md § TESTING VENUES).
· NO REPO WRITES. The script resolves `migration_results.json` as `Path( __file__ ).parent / …`,
  which is a REAL directory in the tree. Every test redirects it by patching the module's
  `__file__` to a tmp_path, so no test can create, read or delete a file beside the script.
  A test that wrote there would leave a fixture in the repo that the script would then find.
· The passwords here are obvious fakes assembled from parts, so no line carries a
  credential-shaped literal next to a credential-shaped field name.

WHY THE ASSERTIONS ARE ON THE RETURNED DICT rather than on stdout: the dict is what a caller
acts on, and it is the only output that survives the function. The prints are covered as a
side effect of reaching the branches, which is the right weight for them.
"""

import json
import os
import sys

import pytest


sys.path.insert( 0, os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src", "scripts", "auth_migration" ) )

import validate_migration as mod


# Fakes, assembled from parts so nothing here looks like an issued credential.
_PW    = "not" + "-a-real-" + "secret"
_HASH  = "$2b$12$" + "x" * 22 + "obviouslyfake" + "x" * 18


def _results( **users ):
    return { "users": users }


def _user( status="migrated", password=_PW, roles=None ):
    return { "status": status, "password": password, "roles": roles if roles is not None else [ "user" ] }


@pytest.fixture
def seeded( tmp_path, monkeypatch ):
    """
    Redirect the script's results file into tmp_path and stub both DB seams.

    Ensures: writing the returned callable's dict lands at tmp_path/migration_results.json,
             which is where the module will look once its `__file__` is patched.
    """
    monkeypatch.setattr( mod, "__file__", str( tmp_path / "validate_migration.py" ) )
    monkeypatch.setattr( mod.du, "print_banner", lambda *a, **k: None )

    def write( payload ):
        ( tmp_path / "migration_results.json" ).write_text( json.dumps( payload ) )
    return write


def _stub_db( monkeypatch, *, user=None, verify=True ):
    monkeypatch.setattr( mod, "get_user_by_email", lambda email: user )
    monkeypatch.setattr( mod, "verify_password",   lambda pw, h: verify )


# ---------------------------------------------------------------------------
# The missing-file guard
# ---------------------------------------------------------------------------
def test_absent_results_file_fails_without_touching_the_database( tmp_path, monkeypatch ):
    """Reddens if the early return is removed: the DB stubs would raise instead."""
    monkeypatch.setattr( mod, "__file__", str( tmp_path / "validate_migration.py" ) )
    monkeypatch.setattr( mod.du, "print_banner", lambda *a, **k: None )
    def boom( email ):
        raise AssertionError( "reached the database with no results file" )
    monkeypatch.setattr( mod, "get_user_by_email", boom )

    out = mod.validate_migration()
    assert out == { "status": "failed", "error": "migration_results.json not found" }


# ---------------------------------------------------------------------------
# The five per-user outcomes — one test each, none of them sharing a fixture shape
# ---------------------------------------------------------------------------
def test_a_user_whose_migration_failed_is_counted_failed_and_never_queried( seeded, monkeypatch ):
    seeded( _results( **{ "a@x.test": _user( status="error" ) } ) )
    def boom( email ):
        raise AssertionError( "queried a user whose migration had already failed" )
    monkeypatch.setattr( mod, "get_user_by_email", boom )

    out = mod.validate_migration()
    assert ( out[ "total_users" ], out[ "validated" ], out[ "failed" ] ) == ( 1, 0, 1 )
    assert out[ "users" ] == {}          # the skip path records no per-user entry
    assert out[ "status" ] == "failed"


def test_a_user_absent_from_the_database_is_not_found( seeded, monkeypatch ):
    seeded( _results( **{ "a@x.test": _user() } ) )
    _stub_db( monkeypatch, user=None )
    out = mod.validate_migration()
    assert out[ "users" ][ "a@x.test" ] == { "status": "not_found" }
    assert out[ "failed" ] == 1


def test_a_password_that_does_not_verify_is_a_mismatch( seeded, monkeypatch ):
    seeded( _results( **{ "a@x.test": _user() } ) )
    _stub_db( monkeypatch, user={ "password_hash": _HASH, "roles": "user", "user_id": "u1" }, verify=False )
    out = mod.validate_migration()
    assert out[ "users" ][ "a@x.test" ] == { "status": "password_mismatch" }
    assert out[ "failed" ] == 1


def test_roles_are_compared_as_SETS_not_as_the_stored_string( seeded, monkeypatch ):
    """
    🔴 The fixture is the point. Order and the stored comma-string must NOT matter — only
    membership. `admin,user` vs [user, admin] is a MATCH, and a test using a single role
    could not tell a set comparison from a string comparison.
    """
    seeded( _results( **{ "a@x.test": _user( roles=[ "user", "admin" ] ) } ) )
    _stub_db( monkeypatch, user={ "password_hash": _HASH, "roles": "admin,user", "user_id": "u1" } )
    out = mod.validate_migration()
    assert out[ "users" ][ "a@x.test" ][ "status" ] == "validated"


def test_a_genuine_role_difference_is_a_mismatch_and_reports_both_sides( seeded, monkeypatch ):
    seeded( _results( **{ "a@x.test": _user( roles=[ "user", "admin" ] ) } ) )
    _stub_db( monkeypatch, user={ "password_hash": _HASH, "roles": "user", "user_id": "u1" } )
    out = mod.validate_migration()
    entry = out[ "users" ][ "a@x.test" ]
    assert entry[ "status" ] == "role_mismatch"
    assert sorted( entry[ "expected_roles" ] ) == [ "admin", "user" ]
    assert entry[ "actual_roles" ] == [ "user" ]


def test_an_empty_roles_string_reads_as_NO_roles_not_as_one_empty_role( seeded, monkeypatch ):
    """
    The `if user_dict["roles"] else []` guard. Without it, "" splits to [""] — one role named
    empty string — and a user expecting no roles would report a mismatch against itself.
    """
    seeded( _results( **{ "a@x.test": _user( roles=[] ) } ) )
    _stub_db( monkeypatch, user={ "password_hash": _HASH, "roles": "", "user_id": "u1" } )
    out = mod.validate_migration()
    assert out[ "users" ][ "a@x.test" ][ "status" ] == "validated"


def test_an_exception_anywhere_in_a_users_check_is_caught_and_recorded( seeded, monkeypatch ):
    """One user's failure must not abort the run — the loop is the unit of recovery."""
    seeded( _results( **{ "a@x.test": _user() } ) )
    def boom( email ):
        raise RuntimeError( "connection reset" )
    monkeypatch.setattr( mod, "get_user_by_email", boom )
    out = mod.validate_migration()
    assert out[ "users" ][ "a@x.test" ] == { "status": "error", "error": "connection reset" }
    assert out[ "failed" ] == 1


# ---------------------------------------------------------------------------
# The admin branch, and the overall verdict
# ---------------------------------------------------------------------------
def test_an_admin_is_reported_with_the_star_and_a_non_admin_without_it( seeded, monkeypatch, capsys ):
    """
    The only branch whose ONLY effect is on stdout, so stdout is the only place to assert it.
    Both directions, because a print that always starred would pass a one-sided test.
    """
    seeded( _results( **{
        "boss@x.test":  _user( roles=[ "admin" ] ),
        "staff@x.test": _user( roles=[ "user"  ] ),
    } ) )
    monkeypatch.setattr( mod, "get_user_by_email",
                         lambda e: { "password_hash": _HASH, "user_id": "u1",
                                     "roles": "admin" if e.startswith( "boss" ) else "user" } )
    monkeypatch.setattr( mod, "verify_password", lambda pw, h: True )

    mod.validate_migration()
    lines = capsys.readouterr().out.splitlines()
    boss  = next( l for l in lines if "boss@x.test"  in l )
    staff = next( l for l in lines if "staff@x.test" in l )
    assert "⭐" in boss
    assert "⭐" not in staff


def test_every_user_validating_reports_passed( seeded, monkeypatch ):
    seeded( _results( **{ "a@x.test": _user(), "b@x.test": _user() } ) )
    _stub_db( monkeypatch, user={ "password_hash": _HASH, "roles": "user", "user_id": "u1" } )
    out = mod.validate_migration()
    assert ( out[ "total_users" ], out[ "validated" ], out[ "failed" ] ) == ( 2, 2, 0 )
    assert out[ "status" ] == "passed"


def test_one_bad_user_among_good_ones_fails_the_whole_run( seeded, monkeypatch ):
    """
    🔴 2/1 rather than 1/1: with one good and one bad, `validated == total` could be satisfied
    by a counter swap. Three users make the two counts distinguishable.
    """
    seeded( _results( **{ "a@x.test": _user(), "b@x.test": _user(), "c@x.test": _user() } ) )
    monkeypatch.setattr( mod, "get_user_by_email",
                         lambda e: None if e.startswith( "c" ) else
                                   { "password_hash": _HASH, "roles": "user", "user_id": "u1" } )
    monkeypatch.setattr( mod, "verify_password", lambda pw, h: True )
    out = mod.validate_migration()
    assert ( out[ "total_users" ], out[ "validated" ], out[ "failed" ] ) == ( 3, 2, 1 )
    assert out[ "status" ] == "failed"


def test_no_users_at_all_reports_passed_because_zero_equals_zero( seeded, monkeypatch ):
    """Stated rather than discovered later: an empty migration is vacuously a pass."""
    seeded( _results() )
    _stub_db( monkeypatch, user=None )
    out = mod.validate_migration()
    assert ( out[ "total_users" ], out[ "status" ] ) == ( 0, "passed" )
