"""
The mock-to-JWT user migration, covered without creating a user or writing a password.

`src/scripts/auth_migration/migrate_mock_users.py` — 117 statements at zero, claimed off
the straggler census at tip `d81a9faa`.

🔴 THIS SCRIPT IS THE MOST DANGEROUS OF THE THREE TO TEST, FOR TWO SEPARATE REASONS, and
both are patched at the module attribute so a miss raises instead of succeeding quietly:

1. `create_user` writes REAL users into the auth database. Unpatched, these tests would
   mint three accounts — one of them an `admin` SUPERUSER — against whatever database the
   ambient config resolves to.
2. It writes `migration_results.json` containing PLAINTEXT PASSWORDS, and it writes it
   NEXT TO ITSELF: `Path( __file__ ).parent / "migration_results.json"`, i.e. inside
   `src/scripts/auth_migration/` in the repo. That file is gitignored, which protects the
   commit and does nothing for the disk.

The second cannot be patched by name — the path is built inline from `__file__` — so
`mod.Path` itself is replaced with a factory whose `.parent` is `tmp_path`. Every test
that reaches `migrate_users()` goes through `_wire`, which does both. A test that forgot
would not fail; it would pass, and leave real credentials in the working tree.

The password generator is exercised with the REAL `secrets` module. Stubbing it would
turn every complexity assertion into a statement about the stub.

Each test names the change that reddens it.
"""

import json
import os
import string
import sys

import pytest


sys.path.insert(
    0, os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src", "scripts", "auth_migration" ) )

import migrate_mock_users as mod


SPECIALS = "!@#$%^&*"


class _FakePathFactory:
    """
    Stands in for `pathlib.Path` so `Path( __file__ ).parent` lands in tmp_path.

    Only `.parent` is provided, because only `.parent` is used — a wider fake would
    invite a test to lean on behaviour the script does not actually have.
    """

    def __init__( self, parent ):
        self._parent = parent

    def __call__( self, _whatever ):
        return self

    @property
    def parent( self ):
        return self._parent


def _wire( monkeypatch, tmp_path, create_user=None ):
    """
    Neutralise both hazards and return the results path the script will write.

    `create_user` defaults to a recorder that succeeds; pass your own to make it fail.
    """
    calls = []

    def _default( email, password, roles ):
        calls.append( { "email": email, "password": password, "roles": roles } )
        return True, "ok", f"uid-{len( calls )}"

    monkeypatch.setattr( mod, "create_user", create_user or _default )
    monkeypatch.setattr( mod, "Path", _FakePathFactory( tmp_path ) )
    monkeypatch.setattr( mod, "ConfigurationManager", lambda **kw: object() )
    monkeypatch.setattr( mod.du, "print_banner", lambda *a, **k: None )
    return tmp_path / "migration_results.json", calls


class TestGenerateSecurePassword:
    """
    The generator, against the real `secrets` module. The complexity guarantees are the
    whole point of the function, so a stub here would assert nothing about it.
    """

    def test_it_honours_the_requested_length( self ):
        assert len( mod.generate_secure_password( 16 ) ) == 16
        assert len( mod.generate_secure_password( 32 ) ) == 32

    def test_every_password_carries_all_four_character_classes( self ):
        """
        The four seeded characters guarantee this by construction, so it holds for every
        draw rather than usually — which is why it is asserted over a batch. A single
        sample would pass by luck even with the seeding deleted.
        """
        for _ in range( 25 ):
            pw = mod.generate_secure_password( 16 )
            assert any( c.islower() for c in pw )
            assert any( c.isupper() for c in pw )
            assert any( c.isdigit() for c in pw )
            assert any( c in SPECIALS for c in pw )

    def test_the_seeded_characters_are_shuffled_not_left_in_position( self ):
        """
        ⚠️ THE SHUFFLE IS THE EASIEST LINE HERE TO DELETE AND THE HARDEST TO NOTICE GONE.
        Without it every password is lowercase / uppercase / digit / special in that fixed
        order — a four-character crib on every credential the migration issues. Deleting
        it makes position 0 lowercase every single time, which is what 40 draws catch.
        """
        firsts = [ mod.generate_secure_password( 16 )[ 0 ] for _ in range( 40 ) ]
        assert not all( c.islower() for c in firsts ), \
            "every password starts with a lowercase letter — the shuffle is gone"

    def test_two_passwords_are_not_the_same( self ):
        assert len( { mod.generate_secure_password( 16 ) for _ in range( 20 ) } ) == 20

    def test_it_draws_only_from_the_declared_alphabet( self ):
        """
        The special set is deliberately narrow — quotes and backslashes would break both
        the JSON file and the shell paste that follows it. A widened alphabet reddens here.
        """
        allowed = set( string.ascii_letters + string.digits + SPECIALS )
        for _ in range( 25 ):
            assert set( mod.generate_secure_password( 16 ) ) <= allowed


class TestMigrateUsers:

    def test_it_creates_exactly_the_three_seed_users( self, monkeypatch, tmp_path, capsys ):
        _, calls = _wire( monkeypatch, tmp_path )
        out = mod.migrate_users( debug=False )
        capsys.readouterr()
        assert [ c[ "email" ] for c in calls ] == [
            "ricardo.felipe.ruiz@gmail.com", "alice@example.com", "bob@example.com" ]
        assert set( out[ "users" ] ) == { c[ "email" ] for c in calls }

    def test_only_the_admin_gets_the_admin_role( self, monkeypatch, tmp_path, capsys ):
        """
        The roles are the reason this script exists. Asserted per-user rather than as the
        union of all roles seen: a bug handing `admin` to alice leaves the union unchanged
        and passes a laxer check.
        """
        _, calls = _wire( monkeypatch, tmp_path )
        mod.migrate_users( debug=False )
        capsys.readouterr()
        by_email = { c[ "email" ]: c[ "roles" ] for c in calls }
        assert by_email[ "ricardo.felipe.ruiz@gmail.com" ] == [ "user", "admin" ]
        assert by_email[ "alice@example.com" ] == [ "user" ]
        assert by_email[ "bob@example.com"   ] == [ "user" ]

    def test_the_admin_email_can_be_overridden_by_environment( self, monkeypatch, tmp_path, capsys ):
        """`LUPIN_DEV_EMAIL` — so a second developer is not seeded as Rick."""
        monkeypatch.setenv( "LUPIN_DEV_EMAIL", "someone.else@example.com" )
        _, calls = _wire( monkeypatch, tmp_path )
        mod.migrate_users( debug=False )
        capsys.readouterr()
        assert calls[ 0 ][ "email" ] == "someone.else@example.com"
        assert calls[ 0 ][ "roles" ] == [ "user", "admin" ]

    def test_each_user_gets_a_different_password( self, monkeypatch, tmp_path, capsys ):
        """One password reused across three accounts would be a single point of failure."""
        _, calls = _wire( monkeypatch, tmp_path )
        mod.migrate_users( debug=False )
        capsys.readouterr()
        assert len( { c[ "password" ] for c in calls } ) == 3

    def test_the_results_file_is_written_where_the_script_lives( self, monkeypatch, tmp_path, capsys ):
        results, _ = _wire( monkeypatch, tmp_path )
        mod.migrate_users( debug=False )
        capsys.readouterr()
        assert results.exists(), "the results file went somewhere other than the patched path"
        saved = json.loads( results.read_text() )
        assert set( saved ) == { "migration_date", "users" }
        assert len( saved[ "users" ] ) == 3

    def test_the_saved_password_is_the_one_handed_to_create_user( self, monkeypatch, tmp_path, capsys ):
        """
        The file exists so somebody can log in with it. A stored password that is not the
        one the account was created with makes the whole migration silently useless —
        every account real and every credential wrong.
        """
        results, calls = _wire( monkeypatch, tmp_path )
        mod.migrate_users( debug=False )
        capsys.readouterr()
        saved = json.loads( results.read_text() )[ "users" ]
        for call in calls:
            assert saved[ call[ "email" ] ][ "password" ] == call[ "password" ]

    def test_debug_true_announces_the_superuser( self, monkeypatch, tmp_path, capsys ):
        """
        ⚠️ ASSERTS THE ASSOCIATION, NOT THE WORD. This read `"SUPERUSER" in out` and
        survived a mutation inverting the very check it is named for — flipping
        `if "admin" in roles` to `not in` still prints SUPERUSER, just beside alice and
        bob instead of the admin. The word appears either way, so the substring cannot
        see the defect. Measured 2026-08-30 at 36f56b90: mutation SURVIVED with 18 passed,
        reproduced by hand.

        The line that carries the badge is what distinguishes them, so that is what is
        asserted — and both other users are asserted NOT to carry it, because a mutation
        that hands the badge to everyone leaves the admin's line correct.
        """
        _wire( monkeypatch, tmp_path )
        mod.migrate_users( debug=True )
        out = capsys.readouterr().out

        # Only the per-user progress lines — the password summary prints its own badge on
        # a Roles line that carries no email, and sweeping it in here made this assertion
        # fail against correct code on its first writing.
        creating = [ line for line in out.splitlines() if line.startswith( "Creating " ) ]
        badged   = [ line for line in creating if "SUPERUSER" in line ]
        assert badged, "nobody was announced as a superuser at all"
        assert all( "ricardo.felipe.ruiz@gmail.com" in line for line in badged ), (
            f"the superuser badge went to the wrong account(s): {badged}" )
        for ordinary in ( "alice@example.com", "bob@example.com" ):
            assert not any( ordinary in line for line in badged ), (
                f"{ordinary} was announced as a superuser" )

    def test_the_password_summary_badges_only_the_admin( self, monkeypatch, tmp_path, capsys ):
        """
        The SECOND `if "admin" in roles` — the one in the password summary, which is not
        gated by `debug` and so prints on every run. It survived the same inversion for the
        same reason, and it is the more visible of the two: this block is what a human
        reads off the terminal after a migration.

        The badge sits on the Roles line, one line below the email, so the assertion walks
        the block rather than the whole capture — checking `"⭐" in out` would pass with the
        star on every user.
        """
        _wire( monkeypatch, tmp_path )
        mod.migrate_users( debug=False )
        lines = capsys.readouterr().out.splitlines()

        badged_after = { lines[ i - 2 ].strip().removeprefix( "✅ " )
                         for i, line in enumerate( lines )
                         if "⭐ SUPERUSER" in line and i >= 2 }
        assert badged_after == { "ricardo.felipe.ruiz@gmail.com" }, (
            f"the summary badged {badged_after or 'nobody'}" )

    def test_debug_false_still_prints_the_passwords( self, monkeypatch, tmp_path, capsys ):
        """
        `debug` gates the per-user progress lines, NOT the password summary — the summary
        is the deliverable, and suppressing it would make a quiet run useless.
        """
        _, calls = _wire( monkeypatch, tmp_path )
        mod.migrate_users( debug=False )
        out = capsys.readouterr().out
        assert "INITIAL PASSWORDS" in out
        for call in calls:
            assert call[ "password" ] in out


class TestMigrateUsersWhenThingsGoWrong:

    def test_a_refused_user_is_recorded_as_failed_and_the_others_still_run( self, monkeypatch, tmp_path, capsys ):
        """
        Partial failure is the realistic case: one account already exists from an earlier
        run. Aborting would leave the migration half-done with no record of which half.
        """
        def _refuse_alice( email, password, roles ):
            if email == "alice@example.com": return False, "already exists", None
            return True, "ok", "uid"
        results, _ = _wire( monkeypatch, tmp_path, create_user=_refuse_alice )
        out = mod.migrate_users( debug=False )
        capsys.readouterr()

        assert out[ "users" ][ "alice@example.com" ][ "status" ] == "failed"
        assert out[ "users" ][ "alice@example.com" ][ "error"  ] == "already exists"
        assert out[ "users" ][ "bob@example.com"   ][ "status" ] == "migrated"
        assert json.loads( results.read_text() )[ "users" ][ "alice@example.com" ][ "status" ] == "failed"

    def test_a_raising_create_user_is_caught_the_same_way( self, monkeypatch, tmp_path, capsys ):
        """
        Distinct from a `False` return: one is the service declining, the other is it
        breaking. Both must leave a record rather than a traceback.
        """
        def _boom( email, password, roles ): raise RuntimeError( "database is gone" )
        _wire( monkeypatch, tmp_path, create_user=_boom )
        out = mod.migrate_users( debug=False )
        capsys.readouterr()
        assert all( u[ "status" ] == "failed" for u in out[ "users" ].values() )
        assert "database is gone" in out[ "users" ][ "bob@example.com" ][ "error" ]

    def test_a_failed_user_contributes_no_password_to_the_summary( self, monkeypatch, tmp_path, capsys ):
        """
        The summary loop reads `user_info[ "password" ]`, which a failed record does not
        have — so the `status == "migrated"` guard is the only thing between a partial
        failure and a KeyError that would also lose the SUCCESSFUL accounts' passwords.
        """
        def _refuse_all( email, password, roles ): return False, "nope", None
        _wire( monkeypatch, tmp_path, create_user=_refuse_all )
        mod.migrate_users( debug=False )
        out = capsys.readouterr().out
        assert "INITIAL PASSWORDS" in out
        assert "Password:" not in out


class TestQuickSmokeTest:

    def test_it_passes_against_the_real_generator( self, monkeypatch, capsys ):
        monkeypatch.setattr( mod.du, "print_banner", lambda *a, **k: None )
        assert mod.quick_smoke_test() is True
        assert "smoke test passed" in capsys.readouterr().out

    def test_it_reports_failure_rather_than_raising( self, monkeypatch, capsys ):
        """
        Its own error path, reached by making the generator return something that fails
        the script's assertions — which is what a regression in it would look like.
        """
        monkeypatch.setattr( mod.du, "print_banner", lambda *a, **k: None )
        monkeypatch.setattr( mod, "generate_secure_password", lambda n=16: "short" )
        assert mod.quick_smoke_test() is False
        assert "Smoke test failed" in capsys.readouterr().out
