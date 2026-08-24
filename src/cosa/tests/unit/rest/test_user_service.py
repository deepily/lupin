"""
Unit tests for cosa.rest.user_service.

All seams mocked: get_db, UserRepository, hash_password / verify_password /
validate_password_strength, uuid. NO real DB, crypto, or network. Covers every branch
of the 8 user-lifecycle functions ( create / authenticate / get-by-id / get-by-email /
update-password / deactivate / mark-verified / reset-password ).
"""

import unittest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from sqlalchemy.exc import IntegrityError

from cosa.rest import user_service
from cosa.rest.user_service import (
    create_user,
    authenticate_user,
    get_user_by_id,
    get_user_by_email,
    update_user_password,
    deactivate_user,
    mark_email_verified,
    reset_password_with_token,
)

MODULE = "cosa.rest.user_service"


def _user( **kw ):
    """
    Requires:
        - optional field overrides

    Ensures:
        - Returns a MagicMock user row with sensible auth defaults
    """
    row = MagicMock()
    row.id             = kw.get( "id", "user-uuid-123" )
    row.email          = kw.get( "email", "user@example.com" )
    row.roles          = kw.get( "roles", [ "user" ] )
    row.email_verified = kw.get( "email_verified", True )
    row.is_active      = kw.get( "is_active", True )
    row.password_hash  = kw.get( "password_hash", "$hash" )
    row.created_at     = kw.get( "created_at", datetime( 2025, 9, 29, 12, 0, 0 ) )
    row.last_login_at  = kw.get( "last_login_at", datetime( 2025, 9, 30, 8, 0, 0 ) )
    return row


class TestCreateUser( unittest.TestCase ):
    """
    Tests for create_user().

    Ensures:
        - Email validation, weak-password rejection, hashing failure, roles default,
          success, duplicate ( IntegrityError ), and generic DB error
    """

    def test_invalid_email_empty( self ):
        """
        Ensures:
            - Empty email -> (False, "Invalid email address", None)
        """
        ok, msg, uid = create_user( "", "pw" )
        self.assertFalse( ok )
        self.assertIsNone( uid )

    def test_invalid_email_no_at( self ):
        """
        Ensures:
            - Email without '@' -> (False, "Invalid email address", None)
        """
        ok, msg, uid = create_user( "no-at", "pw" )
        self.assertFalse( ok )
        self.assertIn( "Invalid email", msg )

    def test_weak_password_rejected( self ):
        """
        Ensures:
            - A weak password is rejected with its strength error
        """
        with patch( f"{MODULE}.validate_password_strength", return_value=( False, "too weak" ) ):
            ok, msg, uid = create_user( "a@b.com", "weak" )
            self.assertFalse( ok )
            self.assertEqual( msg, "too weak" )

    def test_hashing_failure( self ):
        """
        Ensures:
            - A hashing exception -> (False, "Password hashing failed...", None)
        """
        with patch( f"{MODULE}.validate_password_strength", return_value=( True, "" ) ), \
             patch( f"{MODULE}.hash_password", side_effect=Exception( "bcrypt boom" ) ):
            ok, msg, uid = create_user( "a@b.com", "GoodPass123!" )
            self.assertFalse( ok )
            self.assertIn( "Password hashing failed", msg )

    def test_success_defaults_roles( self ):
        """
        Ensures:
            - Valid input with roles=None defaults to ["user"] and persists
        """
        with patch( f"{MODULE}.validate_password_strength", return_value=( True, "" ) ), \
             patch( f"{MODULE}.hash_password", return_value="$hash" ), \
             patch( f"{MODULE}.get_db" ), \
             patch( f"{MODULE}.UserRepository" ) as mock_repo_cls:
            mock_repo_cls.return_value.create_user.return_value = _user( id="new-id" )
            ok, msg, uid = create_user( "a@b.com", "GoodPass123!" )
            self.assertTrue( ok )
            self.assertEqual( uid, "new-id" )
            _, kwargs = mock_repo_cls.return_value.create_user.call_args
            self.assertEqual( kwargs[ "roles" ], [ "user" ] )

    def test_success_explicit_roles( self ):
        """
        Ensures:
            - Explicit roles are passed through to the repository
        """
        with patch( f"{MODULE}.validate_password_strength", return_value=( True, "" ) ), \
             patch( f"{MODULE}.hash_password", return_value="$hash" ), \
             patch( f"{MODULE}.get_db" ), \
             patch( f"{MODULE}.UserRepository" ) as mock_repo_cls:
            mock_repo_cls.return_value.create_user.return_value = _user( id="new-id" )
            create_user( "a@b.com", "GoodPass123!", roles=[ "user", "admin" ] )
            _, kwargs = mock_repo_cls.return_value.create_user.call_args
            self.assertEqual( kwargs[ "roles" ], [ "user", "admin" ] )

    def test_duplicate_email( self ):
        """
        Ensures:
            - IntegrityError -> (False, "Email already registered", None)
        """
        with patch( f"{MODULE}.validate_password_strength", return_value=( True, "" ) ), \
             patch( f"{MODULE}.hash_password", return_value="$hash" ), \
             patch( f"{MODULE}.get_db" ), \
             patch( f"{MODULE}.UserRepository" ) as mock_repo_cls:
            mock_repo_cls.return_value.create_user.side_effect = IntegrityError( "s", "p", Exception( "dup" ) )
            ok, msg, uid = create_user( "a@b.com", "GoodPass123!" )
            self.assertFalse( ok )
            self.assertIn( "already registered", msg )

    def test_generic_db_error( self ):
        """
        Ensures:
            - A generic DB exception -> (False, "Database error...", None)
        """
        with patch( f"{MODULE}.validate_password_strength", return_value=( True, "" ) ), \
             patch( f"{MODULE}.hash_password", return_value="$hash" ), \
             patch( f"{MODULE}.get_db" ), \
             patch( f"{MODULE}.UserRepository" ) as mock_repo_cls:
            mock_repo_cls.return_value.create_user.side_effect = Exception( "db down" )
            ok, msg, uid = create_user( "a@b.com", "GoodPass123!" )
            self.assertFalse( ok )
            self.assertIn( "Database error", msg )


class TestAuthenticateUser( unittest.TestCase ):
    """
    Tests for authenticate_user().

    Ensures:
        - Missing creds, unknown user, inactive, wrong password, success ( both
          roles/created_at arms ), and generic error
    """

    def test_missing_credentials( self ):
        """
        Ensures:
            - Empty email/password -> (False, "Email and password required", None)
        """
        ok, msg, data = authenticate_user( "", "" )
        self.assertFalse( ok )
        self.assertIsNone( data )

    def test_unknown_user( self ):
        """
        Ensures:
            - get_by_email None -> (False, "Invalid email or password", None)
        """
        with patch( f"{MODULE}.get_db" ), patch( f"{MODULE}.UserRepository" ) as mock_repo_cls:
            mock_repo_cls.return_value.get_by_email.return_value = None
            ok, msg, data = authenticate_user( "a@b.com", "pw" )
            self.assertFalse( ok )
            self.assertIn( "Invalid email or password", msg )

    def test_inactive_account( self ):
        """
        Ensures:
            - Inactive user -> (False, "Account is inactive", None)
        """
        with patch( f"{MODULE}.get_db" ), patch( f"{MODULE}.UserRepository" ) as mock_repo_cls:
            mock_repo_cls.return_value.get_by_email.return_value = _user( is_active=False )
            ok, msg, data = authenticate_user( "a@b.com", "pw" )
            self.assertFalse( ok )
            self.assertIn( "inactive", msg )

    def test_wrong_password( self ):
        """
        Ensures:
            - verify_password False -> (False, "Invalid email or password", None)
        """
        with patch( f"{MODULE}.get_db" ), patch( f"{MODULE}.UserRepository" ) as mock_repo_cls, \
             patch( f"{MODULE}.verify_password", return_value=False ):
            mock_repo_cls.return_value.get_by_email.return_value = _user()
            ok, msg, data = authenticate_user( "a@b.com", "pw" )
            self.assertFalse( ok )
            self.assertIn( "Invalid email or password", msg )

    def test_success_full_row( self ):
        """
        Ensures:
            - Valid login updates last_login + returns data ( roles + created_at present )
        """
        with patch( f"{MODULE}.get_db" ), patch( f"{MODULE}.UserRepository" ) as mock_repo_cls, \
             patch( f"{MODULE}.verify_password", return_value=True ):
            row = _user( roles=[ "admin" ], created_at=datetime( 2025, 9, 29, 12, 0, 0 ) )
            mock_repo_cls.return_value.get_by_email.return_value = row
            ok, msg, data = authenticate_user( "a@b.com", "pw" )
            self.assertTrue( ok )
            self.assertEqual( data[ "roles" ], [ "admin" ] )
            self.assertEqual( data[ "created_at" ], "2025-09-29T12:00:00" )
            mock_repo_cls.return_value.update_last_login.assert_called_once()

    def test_last_login_at_carries_a_utc_offset( self ):
        """
        Ensures:
            - last_login_at parses as a TIMEZONE-AWARE instant (row 3b4002fe)

        This asserts the string carries an OFFSET, not that it equals a literal.
        Pinning the literal would only re-freeze whichever spelling happens to be
        current, and would pass just as happily on the naive one.

        Why it matters: created_at on the line above comes off a TIMESTAMPTZ column
        and serialises with +00:00, while last_login_at used to be a naive
        utcnow().isoformat() carrying no offset at all. Both land in this one dict,
        and admin-users.js renders both through new Date( ... ) - which reads a
        zone-less string as LOCAL time. So the admin users table showed created_at
        correctly and last_login_at shifted by the operator's UTC offset, on the
        same row, with nothing in the code to say why.
        """
        with patch( f"{MODULE}.get_db" ), patch( f"{MODULE}.UserRepository" ) as mock_repo_cls, \
             patch( f"{MODULE}.verify_password", return_value=True ):
            mock_repo_cls.return_value.get_by_email.return_value = _user()
            ok, msg, data = authenticate_user( "a@b.com", "pw" )

        self.assertTrue( ok )
        parsed = datetime.fromisoformat( data[ "last_login_at" ] )
        self.assertIsNotNone(
            parsed.tzinfo,
            "last_login_at was serialised without a UTC offset - a browser parsing it "
            "with new Date( ... ) reads it as LOCAL time and displays it shifted"
        )
        self.assertEqual( parsed.utcoffset(), timedelta( 0 ) )

    def test_success_bare_row( self ):
        """
        Ensures:
            - Empty roles default to ["user"]; None created_at -> None
        """
        with patch( f"{MODULE}.get_db" ), patch( f"{MODULE}.UserRepository" ) as mock_repo_cls, \
             patch( f"{MODULE}.verify_password", return_value=True ):
            mock_repo_cls.return_value.get_by_email.return_value = _user( roles=[], created_at=None )
            ok, msg, data = authenticate_user( "a@b.com", "pw" )
            self.assertTrue( ok )
            self.assertEqual( data[ "roles" ], [ "user" ] )
            self.assertIsNone( data[ "created_at" ] )

    def test_generic_error( self ):
        """
        Ensures:
            - A DB exception -> (False, "Authentication error...", None)
        """
        with patch( f"{MODULE}.get_db" ), patch( f"{MODULE}.UserRepository" ) as mock_repo_cls:
            mock_repo_cls.return_value.get_by_email.side_effect = Exception( "db error" )
            ok, msg, data = authenticate_user( "a@b.com", "pw" )
            self.assertFalse( ok )
            self.assertIn( "Authentication error", msg )


class TestGetUserById( unittest.TestCase ):
    """
    Tests for get_user_by_id().

    Ensures:
        - Empty id, not found, success ( full + bare row ), invalid uuid / error -> None
    """

    def test_empty_id( self ):
        """
        Ensures:
            - Empty user_id -> None
        """
        self.assertIsNone( get_user_by_id( "" ) )

    def test_not_found( self ):
        """
        Ensures:
            - get_by_id None -> None
        """
        with patch( f"{MODULE}.uuid" ), patch( f"{MODULE}.get_db" ), \
             patch( f"{MODULE}.UserRepository" ) as mock_repo_cls:
            mock_repo_cls.return_value.get_by_id.return_value = None
            self.assertIsNone( get_user_by_id( "uid" ) )

    def test_success_full_row( self ):
        """
        Ensures:
            - Full row maps all fields ( roles, iso timestamps )
        """
        with patch( f"{MODULE}.uuid" ), patch( f"{MODULE}.get_db" ), \
             patch( f"{MODULE}.UserRepository" ) as mock_repo_cls:
            mock_repo_cls.return_value.get_by_id.return_value = _user( roles=[ "admin" ] )
            data = get_user_by_id( "uid" )
            self.assertEqual( data[ "roles" ], [ "admin" ] )
            self.assertEqual( data[ "created_at" ], "2025-09-29T12:00:00" )
            self.assertEqual( data[ "last_login_at" ], "2025-09-30T08:00:00" )

    def test_success_bare_row( self ):
        """
        Ensures:
            - Empty roles default; None timestamps -> None
        """
        with patch( f"{MODULE}.uuid" ), patch( f"{MODULE}.get_db" ), \
             patch( f"{MODULE}.UserRepository" ) as mock_repo_cls:
            mock_repo_cls.return_value.get_by_id.return_value = _user( roles=[], created_at=None, last_login_at=None )
            data = get_user_by_id( "uid" )
            self.assertEqual( data[ "roles" ], [ "user" ] )
            self.assertIsNone( data[ "created_at" ] )
            self.assertIsNone( data[ "last_login_at" ] )

    def test_invalid_uuid_returns_none( self ):
        """
        Ensures:
            - uuid.UUID ValueError -> None ( caught by except (ValueError, Exception) )
        """
        with patch( f"{MODULE}.uuid" ) as mock_uuid:
            mock_uuid.UUID.side_effect = ValueError( "bad" )
            self.assertIsNone( get_user_by_id( "bad" ) )


class TestGetUserByEmail( unittest.TestCase ):
    """
    Tests for get_user_by_email().

    Ensures:
        - Empty email, not found, success ( full + bare ), error -> None
    """

    def test_empty_email( self ):
        """
        Ensures:
            - Empty email -> None
        """
        self.assertIsNone( get_user_by_email( "" ) )

    def test_not_found( self ):
        """
        Ensures:
            - get_by_email None -> None
        """
        with patch( f"{MODULE}.get_db" ), patch( f"{MODULE}.UserRepository" ) as mock_repo_cls:
            mock_repo_cls.return_value.get_by_email.return_value = None
            self.assertIsNone( get_user_by_email( "a@b.com" ) )

    def test_success_full_and_bare( self ):
        """
        Ensures:
            - Full row maps fields; bare row defaults roles + None timestamps
        """
        with patch( f"{MODULE}.get_db" ), patch( f"{MODULE}.UserRepository" ) as mock_repo_cls:
            mock_repo_cls.return_value.get_by_email.return_value = _user( roles=[ "admin" ] )
            full = get_user_by_email( "a@b.com" )
            self.assertEqual( full[ "roles" ], [ "admin" ] )
            self.assertEqual( full[ "last_login_at" ], "2025-09-30T08:00:00" )

            mock_repo_cls.return_value.get_by_email.return_value = _user( roles=[], created_at=None, last_login_at=None )
            bare = get_user_by_email( "a@b.com" )
            self.assertEqual( bare[ "roles" ], [ "user" ] )
            self.assertIsNone( bare[ "created_at" ] )
            self.assertIsNone( bare[ "last_login_at" ] )

    def test_error_returns_none( self ):
        """
        Ensures:
            - A DB exception -> None
        """
        with patch( f"{MODULE}.get_db" ), patch( f"{MODULE}.UserRepository" ) as mock_repo_cls:
            mock_repo_cls.return_value.get_by_email.side_effect = Exception( "db error" )
            self.assertIsNone( get_user_by_email( "a@b.com" ) )


class TestUpdateUserPassword( unittest.TestCase ):
    """
    Tests for update_user_password().

    Ensures:
        - Missing fields, weak new password, invalid uuid, user-not-found,
          wrong old password, update-failed, success, generic error
    """

    def test_missing_fields( self ):
        """
        Ensures:
            - Any missing field -> (False, "All fields required")
        """
        ok, msg = update_user_password( "", "old", "new" )
        self.assertFalse( ok )

    def test_weak_new_password( self ):
        """
        Ensures:
            - Weak new password rejected with its strength error
        """
        with patch( f"{MODULE}.validate_password_strength", return_value=( False, "too weak" ) ):
            ok, msg = update_user_password( "uid", "old", "weak" )
            self.assertFalse( ok )
            self.assertEqual( msg, "too weak" )

    def test_invalid_uuid( self ):
        """
        Ensures:
            - Bad user_id -> (False, "Invalid user ID format")
        """
        with patch( f"{MODULE}.validate_password_strength", return_value=( True, "" ) ), \
             patch( f"{MODULE}.uuid" ) as mock_uuid:
            mock_uuid.UUID.side_effect = ValueError( "bad" )
            ok, msg = update_user_password( "bad", "old", "GoodPass123!" )
            self.assertFalse( ok )
            self.assertIn( "Invalid user ID format", msg )

    def test_user_not_found( self ):
        """
        Ensures:
            - get_by_id None -> (False, "User not found")
        """
        with patch( f"{MODULE}.validate_password_strength", return_value=( True, "" ) ), \
             patch( f"{MODULE}.uuid" ), patch( f"{MODULE}.get_db" ), \
             patch( f"{MODULE}.UserRepository" ) as mock_repo_cls:
            mock_repo_cls.return_value.get_by_id.return_value = None
            ok, msg = update_user_password( "uid", "old", "GoodPass123!" )
            self.assertFalse( ok )
            self.assertIn( "User not found", msg )

    def test_wrong_old_password( self ):
        """
        Ensures:
            - verify_password False -> (False, "Current password is incorrect")
        """
        with patch( f"{MODULE}.validate_password_strength", return_value=( True, "" ) ), \
             patch( f"{MODULE}.uuid" ), patch( f"{MODULE}.get_db" ), \
             patch( f"{MODULE}.UserRepository" ) as mock_repo_cls, \
             patch( f"{MODULE}.verify_password", return_value=False ):
            mock_repo_cls.return_value.get_by_id.return_value = _user()
            ok, msg = update_user_password( "uid", "wrong", "GoodPass123!" )
            self.assertFalse( ok )
            self.assertIn( "Current password is incorrect", msg )

    def test_update_failed( self ):
        """
        Ensures:
            - update_password returns falsy -> (False, "Password update failed")
        """
        with patch( f"{MODULE}.validate_password_strength", return_value=( True, "" ) ), \
             patch( f"{MODULE}.uuid" ), patch( f"{MODULE}.get_db" ), \
             patch( f"{MODULE}.UserRepository" ) as mock_repo_cls, \
             patch( f"{MODULE}.verify_password", return_value=True ), \
             patch( f"{MODULE}.hash_password", return_value="$new" ):
            mock_repo_cls.return_value.get_by_id.return_value = _user()
            mock_repo_cls.return_value.update_password.return_value = None
            ok, msg = update_user_password( "uid", "old", "GoodPass123!" )
            self.assertFalse( ok )
            self.assertIn( "Password update failed", msg )

    def test_success( self ):
        """
        Ensures:
            - Valid update -> (True, "Password updated successfully")
        """
        with patch( f"{MODULE}.validate_password_strength", return_value=( True, "" ) ), \
             patch( f"{MODULE}.uuid" ), patch( f"{MODULE}.get_db" ), \
             patch( f"{MODULE}.UserRepository" ) as mock_repo_cls, \
             patch( f"{MODULE}.verify_password", return_value=True ), \
             patch( f"{MODULE}.hash_password", return_value="$new" ):
            mock_repo_cls.return_value.get_by_id.return_value = _user()
            mock_repo_cls.return_value.update_password.return_value = _user()
            ok, msg = update_user_password( "uid", "old", "GoodPass123!" )
            self.assertTrue( ok )

    def test_generic_error( self ):
        """
        Ensures:
            - A non-ValueError exception -> (False, "Password update failed: ...")
        """
        with patch( f"{MODULE}.validate_password_strength", return_value=( True, "" ) ), \
             patch( f"{MODULE}.uuid" ), patch( f"{MODULE}.get_db" ), \
             patch( f"{MODULE}.UserRepository" ) as mock_repo_cls:
            mock_repo_cls.return_value.get_by_id.side_effect = Exception( "db down" )
            ok, msg = update_user_password( "uid", "old", "GoodPass123!" )
            self.assertFalse( ok )
            self.assertIn( "Password update failed", msg )


class TestSimpleUuidGuardedMutations( unittest.TestCase ):
    """
    Tests for deactivate_user / mark_email_verified ( same id-guard + repo-result shape ).

    Ensures:
        - Missing id, invalid uuid, not-found, success, and generic error
    """

    def test_deactivate_missing_id( self ):
        """
        Ensures:
            - Empty user_id -> (False, "User ID required")
        """
        ok, msg = deactivate_user( "" )
        self.assertFalse( ok )

    def test_deactivate_invalid_uuid( self ):
        """
        Ensures:
            - Bad uuid -> (False, "Invalid user ID format")
        """
        with patch( f"{MODULE}.uuid" ) as mock_uuid:
            mock_uuid.UUID.side_effect = ValueError( "bad" )
            ok, msg = deactivate_user( "bad" )
            self.assertFalse( ok )
            self.assertIn( "Invalid user ID format", msg )

    def test_deactivate_not_found( self ):
        """
        Ensures:
            - deactivate returns falsy -> (False, "User not found")
        """
        with patch( f"{MODULE}.uuid" ), patch( f"{MODULE}.get_db" ), \
             patch( f"{MODULE}.UserRepository" ) as mock_repo_cls:
            mock_repo_cls.return_value.deactivate.return_value = None
            ok, msg = deactivate_user( "uid" )
            self.assertFalse( ok )
            self.assertIn( "User not found", msg )

    def test_deactivate_success( self ):
        """
        Ensures:
            - deactivate returns user -> (True, "deactivated successfully")
        """
        with patch( f"{MODULE}.uuid" ), patch( f"{MODULE}.get_db" ), \
             patch( f"{MODULE}.UserRepository" ) as mock_repo_cls:
            mock_repo_cls.return_value.deactivate.return_value = _user()
            ok, msg = deactivate_user( "uid" )
            self.assertTrue( ok )

    def test_deactivate_generic_error( self ):
        """
        Ensures:
            - A non-ValueError exception -> (False, "Deactivation failed: ...")
        """
        with patch( f"{MODULE}.uuid" ), patch( f"{MODULE}.get_db" ), \
             patch( f"{MODULE}.UserRepository" ) as mock_repo_cls:
            mock_repo_cls.return_value.deactivate.side_effect = Exception( "db down" )
            ok, msg = deactivate_user( "uid" )
            self.assertFalse( ok )
            self.assertIn( "Deactivation failed", msg )

    def test_mark_verified_missing_id( self ):
        """
        Ensures:
            - Empty user_id -> (False, "User ID required")
        """
        ok, msg = mark_email_verified( "" )
        self.assertFalse( ok )

    def test_mark_verified_invalid_uuid( self ):
        """
        Ensures:
            - Bad uuid -> (False, "Invalid user ID format")
        """
        with patch( f"{MODULE}.uuid" ) as mock_uuid:
            mock_uuid.UUID.side_effect = ValueError( "bad" )
            ok, msg = mark_email_verified( "bad" )
            self.assertFalse( ok )
            self.assertIn( "Invalid user ID format", msg )

    def test_mark_verified_not_found( self ):
        """
        Ensures:
            - mark_email_verified returns falsy -> (False, "User not found")
        """
        with patch( f"{MODULE}.uuid" ), patch( f"{MODULE}.get_db" ), \
             patch( f"{MODULE}.UserRepository" ) as mock_repo_cls:
            mock_repo_cls.return_value.mark_email_verified.return_value = None
            ok, msg = mark_email_verified( "uid" )
            self.assertFalse( ok )
            self.assertIn( "User not found", msg )

    def test_mark_verified_success( self ):
        """
        Ensures:
            - mark_email_verified returns user -> (True, "verified successfully")
        """
        with patch( f"{MODULE}.uuid" ), patch( f"{MODULE}.get_db" ), \
             patch( f"{MODULE}.UserRepository" ) as mock_repo_cls:
            mock_repo_cls.return_value.mark_email_verified.return_value = _user()
            ok, msg = mark_email_verified( "uid" )
            self.assertTrue( ok )

    def test_mark_verified_generic_error( self ):
        """
        Ensures:
            - A non-ValueError exception -> (False, "Email verification failed: ...")
        """
        with patch( f"{MODULE}.uuid" ), patch( f"{MODULE}.get_db" ), \
             patch( f"{MODULE}.UserRepository" ) as mock_repo_cls:
            mock_repo_cls.return_value.mark_email_verified.side_effect = Exception( "db down" )
            ok, msg = mark_email_verified( "uid" )
            self.assertFalse( ok )
            self.assertIn( "Email verification failed", msg )


class TestResetPasswordWithToken( unittest.TestCase ):
    """
    Tests for reset_password_with_token().

    Ensures:
        - Missing fields, weak password, invalid uuid, user-not-found, success, error
    """

    def test_missing_fields( self ):
        """
        Ensures:
            - Missing user_id/new_password -> (False, "User ID and new password required")
        """
        ok, msg = reset_password_with_token( "", "" )
        self.assertFalse( ok )

    def test_weak_password( self ):
        """
        Ensures:
            - Weak new password rejected with its error
        """
        with patch( f"{MODULE}.validate_password_strength", return_value=( False, "too weak" ) ):
            ok, msg = reset_password_with_token( "uid", "weak" )
            self.assertFalse( ok )
            self.assertEqual( msg, "too weak" )

    def test_invalid_uuid( self ):
        """
        Ensures:
            - Bad uuid -> (False, "Invalid user ID format")
        """
        with patch( f"{MODULE}.validate_password_strength", return_value=( True, "" ) ), \
             patch( f"{MODULE}.uuid" ) as mock_uuid:
            mock_uuid.UUID.side_effect = ValueError( "bad" )
            ok, msg = reset_password_with_token( "bad", "GoodPass123!" )
            self.assertFalse( ok )
            self.assertIn( "Invalid user ID format", msg )

    def test_user_not_found( self ):
        """
        Ensures:
            - update_password returns falsy -> (False, "User not found")
        """
        with patch( f"{MODULE}.validate_password_strength", return_value=( True, "" ) ), \
             patch( f"{MODULE}.uuid" ), patch( f"{MODULE}.hash_password", return_value="$new" ), \
             patch( f"{MODULE}.get_db" ), patch( f"{MODULE}.UserRepository" ) as mock_repo_cls:
            mock_repo_cls.return_value.update_password.return_value = None
            ok, msg = reset_password_with_token( "uid", "GoodPass123!" )
            self.assertFalse( ok )
            self.assertIn( "User not found", msg )

    def test_success( self ):
        """
        Ensures:
            - Valid reset -> (True, "Password reset successfully")
        """
        with patch( f"{MODULE}.validate_password_strength", return_value=( True, "" ) ), \
             patch( f"{MODULE}.uuid" ), patch( f"{MODULE}.hash_password", return_value="$new" ), \
             patch( f"{MODULE}.get_db" ), patch( f"{MODULE}.UserRepository" ) as mock_repo_cls:
            mock_repo_cls.return_value.update_password.return_value = _user()
            ok, msg = reset_password_with_token( "uid", "GoodPass123!" )
            self.assertTrue( ok )

    def test_generic_error( self ):
        """
        Ensures:
            - A non-ValueError exception -> (False, "Password reset failed: ...")
        """
        with patch( f"{MODULE}.validate_password_strength", return_value=( True, "" ) ), \
             patch( f"{MODULE}.uuid" ), patch( f"{MODULE}.hash_password", return_value="$new" ), \
             patch( f"{MODULE}.get_db" ), patch( f"{MODULE}.UserRepository" ) as mock_repo_cls:
            mock_repo_cls.return_value.update_password.side_effect = Exception( "db down" )
            ok, msg = reset_password_with_token( "uid", "GoodPass123!" )
            self.assertFalse( ok )
            self.assertIn( "Password reset failed", msg )


if __name__ == "__main__":
    unittest.main()
