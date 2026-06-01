"""
Unit tests for cosa.rest.admin_service.

Every seam is mocked: get_db ( session + chainable query ), UserRepository, the
user_service helpers ( get_user_by_id / create_user / mark_email_verified ),
password_service, refresh_token_service, auth_audit, uuid, secrets. The real
postgres_models column objects are used only as opaque args to the mocked query
chain ( no DB ). NO database, crypto, or network.

Covers list_users · get_user_details · update_user_roles · toggle_user_status ·
admin_reset_password · admin_create_user · admin_delete_user.
"""

import unittest
from datetime import datetime
from unittest.mock import patch, MagicMock

from cosa.rest.admin_service import (
    list_users,
    get_user_details,
    update_user_roles,
    toggle_user_status,
    admin_reset_password,
    admin_create_user,
    admin_delete_user,
)

MODULE = "cosa.rest.admin_service"


def _user( **kw ):
    """
    Requires:
        - optional field overrides

    Ensures:
        - Returns a MagicMock user row with admin-relevant defaults
    """
    row = MagicMock()
    row.id             = kw.get( "id", "user-uuid-123" )
    row.email          = kw.get( "email", "user@example.com" )
    row.roles          = kw.get( "roles", [ "user" ] )
    row.email_verified = kw.get( "email_verified", True )
    row.is_active      = kw.get( "is_active", True )
    row.created_at     = kw.get( "created_at", datetime( 2025, 9, 29, 12, 0, 0 ) )
    row.last_login_at  = kw.get( "last_login_at", datetime( 2025, 9, 30, 8, 0, 0 ) )
    return row


def _session_on( mock_get_db ):
    """
    Requires:
        - mock_get_db is a patched get_db

    Ensures:
        - Wires a chainable SQLAlchemy-style session as the context value
        - Returns ( session, query ) where query.filter/order_by/limit/offset chain to itself
    """
    session = MagicMock()
    q = session.query.return_value
    q.filter.return_value = q
    q.order_by.return_value = q
    q.limit.return_value = q
    q.offset.return_value = q
    mock_get_db.return_value.__enter__.return_value = session
    return session, q


class TestListUsers( unittest.TestCase ):
    """
    Tests for list_users().

    Ensures:
        - Filter arms ( search / role / status variants ), row mapping, and failure
    """

    def test_no_filters_full_and_bare_rows( self ):
        """
        Ensures:
            - Maps rows with both truthy and falsy roles/timestamps
        """
        with patch( f"{MODULE}.get_db" ) as mock_db, patch( f"{MODULE}.UserRepository" ):
            _, q = _session_on( mock_db )
            q.count.return_value = 2
            q.all.return_value = [
                _user( roles=[ "admin" ] ),
                _user( roles=[], created_at=None, last_login_at=None ),
            ]
            users, total = list_users()
            self.assertEqual( total, 2 )
            self.assertEqual( users[0][ "roles" ], [ "admin" ] )
            self.assertEqual( users[0][ "created_at" ], "2025-09-29T12:00:00" )
            self.assertEqual( users[1][ "roles" ], [ "user" ] )
            self.assertIsNone( users[1][ "created_at" ] )
            self.assertIsNone( users[1][ "last_login_at" ] )

    def test_search_role_status_active_filters( self ):
        """
        Ensures:
            - search + valid role_filter + status='active' all apply without error
        """
        with patch( f"{MODULE}.get_db" ) as mock_db, patch( f"{MODULE}.UserRepository" ):
            _, q = _session_on( mock_db )
            q.count.return_value = 1
            q.all.return_value = [ _user() ]
            users, total = list_users( search="alice", role_filter="admin", status_filter="active" )
            self.assertEqual( total, 1 )

    def test_invalid_role_filter_and_status_inactive( self ):
        """
        Ensures:
            - role_filter not in allowed list is ignored; status='inactive' applies
        """
        with patch( f"{MODULE}.get_db" ) as mock_db, patch( f"{MODULE}.UserRepository" ):
            _, q = _session_on( mock_db )
            q.count.return_value = 0
            q.all.return_value = []
            users, total = list_users( role_filter="superuser", status_filter="inactive" )
            self.assertEqual( ( users, total ), ( [], 0 ) )

    def test_unknown_status_filter_noop( self ):
        """
        Ensures:
            - A status_filter that is neither active/inactive applies no status clause
        """
        with patch( f"{MODULE}.get_db" ) as mock_db, patch( f"{MODULE}.UserRepository" ):
            _, q = _session_on( mock_db )
            q.count.return_value = 0
            q.all.return_value = []
            users, total = list_users( status_filter="banned" )
            self.assertEqual( total, 0 )

    def test_exception_returns_empty( self ):
        """
        Ensures:
            - A query failure -> ([], 0)
        """
        with patch( f"{MODULE}.get_db" ) as mock_db, patch( f"{MODULE}.UserRepository" ):
            mock_db.return_value.__enter__.side_effect = Exception( "db down" )
            self.assertEqual( list_users(), ( [], 0 ) )


class TestGetUserDetails( unittest.TestCase ):
    """
    Tests for get_user_details().

    Ensures:
        - Empty id, invalid uuid, not found, success ( full + bare ), generic error
    """

    def test_empty_id( self ):
        """
        Ensures:
            - Empty user_id -> None
        """
        self.assertIsNone( get_user_details( "" ) )

    def test_invalid_uuid( self ):
        """
        Ensures:
            - uuid ValueError -> None
        """
        with patch( f"{MODULE}.uuid" ) as mock_uuid, patch( "builtins.print" ):
            mock_uuid.UUID.side_effect = ValueError( "bad" )
            self.assertIsNone( get_user_details( "bad" ) )

    def test_not_found( self ):
        """
        Ensures:
            - get_by_id None -> None
        """
        with patch( f"{MODULE}.get_db" ) as mock_db, patch( f"{MODULE}.uuid" ), \
             patch( f"{MODULE}.UserRepository" ) as mock_repo_cls, \
             patch( f"{MODULE}.AuthAuditLogRepository" ), patch( f"{MODULE}.FailedLoginAttemptRepository" ):
            _session_on( mock_db )
            mock_repo_cls.return_value.get_by_id.return_value = None
            self.assertIsNone( get_user_details( "uid" ) )

    def test_success_full_and_bare( self ):
        """
        Ensures:
            - Returns enhanced details with audit + failed-login counts ( both row arms )
        """
        with patch( f"{MODULE}.get_db" ) as mock_db, patch( f"{MODULE}.uuid" ), \
             patch( f"{MODULE}.UserRepository" ) as mock_repo_cls, \
             patch( f"{MODULE}.AuthAuditLogRepository" ), patch( f"{MODULE}.FailedLoginAttemptRepository" ):
            _, q = _session_on( mock_db )
            q.count.return_value = 5
            mock_repo_cls.return_value.get_by_id.return_value = _user( roles=[ "admin" ] )
            full = get_user_details( "uid" )
            self.assertEqual( full[ "audit_log_count" ], 5 )
            self.assertEqual( full[ "failed_login_count" ], 5 )
            self.assertEqual( full[ "roles" ], [ "admin" ] )
            self.assertEqual( full[ "created_at" ], "2025-09-29T12:00:00" )

            mock_repo_cls.return_value.get_by_id.return_value = _user( roles=[], created_at=None, last_login_at=None )
            bare = get_user_details( "uid" )
            self.assertEqual( bare[ "roles" ], [ "user" ] )
            self.assertIsNone( bare[ "created_at" ] )
            self.assertIsNone( bare[ "last_login_at" ] )

    def test_generic_error( self ):
        """
        Ensures:
            - A non-ValueError exception -> None
        """
        with patch( f"{MODULE}.get_db" ) as mock_db, patch( f"{MODULE}.uuid" ), \
             patch( f"{MODULE}.UserRepository" ) as mock_repo_cls, \
             patch( f"{MODULE}.AuthAuditLogRepository" ), patch( f"{MODULE}.FailedLoginAttemptRepository" ), \
             patch( "builtins.print" ):
            _session_on( mock_db )
            mock_repo_cls.return_value.get_by_id.side_effect = Exception( "db error" )
            self.assertIsNone( get_user_details( "uid" ) )


class TestUpdateUserRoles( unittest.TestCase ):
    """
    Tests for update_user_roles().

    Ensures:
        - Role validation, self-protection, not-found ( both ), uuid error, success, error
    """

    def test_invalid_roles_empty( self ):
        """
        Ensures:
            - Empty roles -> (False, "Invalid roles...", None)
        """
        ok, msg, u = update_user_roles( "a", "b", [] )
        self.assertFalse( ok )
        self.assertIn( "Invalid roles", msg )

    def test_invalid_role_value( self ):
        """
        Ensures:
            - An unknown role -> (False, "Invalid roles...", None)
        """
        ok, msg, u = update_user_roles( "a", "b", [ "superuser" ] )
        self.assertFalse( ok )

    def test_self_demotion_blocked( self ):
        """
        Ensures:
            - Admin removing own admin role -> (False, "Cannot remove your own admin role", None)
        """
        ok, msg, u = update_user_roles( "same", "same", [ "user" ] )
        self.assertFalse( ok )
        self.assertIn( "Cannot remove your own admin role", msg )

    def test_target_not_found( self ):
        """
        Ensures:
            - get_user_by_id None -> (False, "User not found", None)
        """
        with patch( f"{MODULE}.get_user_by_id", return_value=None ):
            ok, msg, u = update_user_roles( "admin", "target", [ "user" ] )
            self.assertFalse( ok )
            self.assertIn( "User not found", msg )

    def test_invalid_uuid( self ):
        """
        Ensures:
            - uuid ValueError -> (False, "Invalid UUID format", None)
        """
        with patch( f"{MODULE}.get_user_by_id", return_value={ "roles": [ "user" ], "email": "t@x" } ), \
             patch( f"{MODULE}.uuid" ) as mock_uuid:
            mock_uuid.UUID.side_effect = ValueError( "bad" )
            ok, msg, u = update_user_roles( "admin", "target", [ "admin" ] )
            self.assertFalse( ok )
            self.assertIn( "Invalid UUID format", msg )

    def test_repo_user_missing( self ):
        """
        Ensures:
            - repo.get_by_id None -> (False, "User not found", None)
        """
        with patch( f"{MODULE}.get_user_by_id", return_value={ "roles": [ "user" ], "email": "t@x" } ), \
             patch( f"{MODULE}.uuid" ), patch( f"{MODULE}.get_db" ) as mock_db, \
             patch( f"{MODULE}.UserRepository" ) as mock_repo_cls:
            _session_on( mock_db )
            mock_repo_cls.return_value.get_by_id.return_value = None
            ok, msg, u = update_user_roles( "admin", "target", [ "admin" ] )
            self.assertFalse( ok )
            self.assertIn( "User not found", msg )

    def test_success( self ):
        """
        Ensures:
            - Valid update flushes, logs, and returns the refreshed user
        """
        updated = { "roles": [ "admin" ], "email": "t@x" }
        with patch( f"{MODULE}.get_user_by_id", side_effect=[ { "roles": [ "user" ], "email": "t@x" }, updated ] ), \
             patch( f"{MODULE}.uuid" ), patch( f"{MODULE}.get_db" ) as mock_db, \
             patch( f"{MODULE}.UserRepository" ) as mock_repo_cls, \
             patch( f"{MODULE}.log_auth_event" ) as mock_log:
            _session_on( mock_db )
            mock_repo_cls.return_value.get_by_id.return_value = _user()
            ok, msg, u = update_user_roles( "admin", "target", [ "admin" ] )
            self.assertTrue( ok )
            self.assertEqual( u, updated )
            mock_log.assert_called_once()

    def test_generic_error( self ):
        """
        Ensures:
            - A non-ValueError exception -> (False, "Role update failed...", None)
        """
        with patch( f"{MODULE}.get_user_by_id", return_value={ "roles": [ "user" ], "email": "t@x" } ), \
             patch( f"{MODULE}.uuid" ), patch( f"{MODULE}.get_db" ) as mock_db, \
             patch( f"{MODULE}.UserRepository" ) as mock_repo_cls:
            _session_on( mock_db )
            mock_repo_cls.return_value.get_by_id.side_effect = Exception( "boom" )
            ok, msg, u = update_user_roles( "admin", "target", [ "admin" ] )
            self.assertFalse( ok )
            self.assertIn( "Role update failed", msg )


class TestToggleUserStatus( unittest.TestCase ):
    """
    Tests for toggle_user_status().

    Ensures:
        - Self-protection, not-found, uuid error, activate ( no revoke ),
          deactivate ( revoke ), generic error
    """

    def test_self_deactivate_blocked( self ):
        """
        Ensures:
            - Admin deactivating self -> (False, "Cannot deactivate your own account", None)
        """
        ok, msg, u = toggle_user_status( "same", "same", is_active=False )
        self.assertFalse( ok )
        self.assertIn( "Cannot deactivate your own account", msg )

    def test_not_found( self ):
        """
        Ensures:
            - get_user_by_id None -> (False, "User not found", None)
        """
        with patch( f"{MODULE}.get_user_by_id", return_value=None ):
            ok, msg, u = toggle_user_status( "admin", "target", is_active=True )
            self.assertFalse( ok )

    def test_invalid_uuid( self ):
        """
        Ensures:
            - uuid ValueError -> (False, "Invalid UUID format", None)
        """
        with patch( f"{MODULE}.get_user_by_id", return_value={ "email": "t@x" } ), \
             patch( f"{MODULE}.uuid" ) as mock_uuid:
            mock_uuid.UUID.side_effect = ValueError( "bad" )
            ok, msg, u = toggle_user_status( "admin", "target", is_active=True )
            self.assertFalse( ok )
            self.assertIn( "Invalid UUID format", msg )

    def test_activate_success_no_revoke( self ):
        """
        Ensures:
            - Activating does NOT revoke tokens; logs + returns user
        """
        with patch( f"{MODULE}.get_user_by_id", side_effect=[ { "email": "t@x" }, { "email": "t@x", "is_active": True } ] ), \
             patch( f"{MODULE}.uuid" ), patch( f"{MODULE}.get_db" ) as mock_db, \
             patch( f"{MODULE}.UserRepository" ) as mock_repo_cls, \
             patch( f"{MODULE}.revoke_all_user_tokens" ) as mock_revoke, \
             patch( f"{MODULE}.log_auth_event" ):
            _session_on( mock_db )
            mock_repo_cls.return_value.get_by_id.return_value = _user()
            ok, msg, u = toggle_user_status( "admin", "target", is_active=True )
            self.assertTrue( ok )
            self.assertIn( "activated", msg )
            mock_revoke.assert_not_called()

    def test_deactivate_success_revokes( self ):
        """
        Ensures:
            - Deactivating ( different admin ) revokes tokens + logs
        """
        with patch( f"{MODULE}.get_user_by_id", side_effect=[ { "email": "t@x" }, { "email": "t@x", "is_active": False } ] ), \
             patch( f"{MODULE}.uuid" ), patch( f"{MODULE}.get_db" ) as mock_db, \
             patch( f"{MODULE}.UserRepository" ) as mock_repo_cls, \
             patch( f"{MODULE}.revoke_all_user_tokens" ) as mock_revoke, \
             patch( f"{MODULE}.log_auth_event" ):
            _session_on( mock_db )
            mock_repo_cls.return_value.get_by_id.return_value = _user()
            ok, msg, u = toggle_user_status( "admin", "target", is_active=False )
            self.assertTrue( ok )
            self.assertIn( "deactivated", msg )
            mock_revoke.assert_called_once_with( "target" )

    def test_repo_user_missing( self ):
        """
        Ensures:
            - repo.get_by_id None -> (False, "User not found", None)
        """
        with patch( f"{MODULE}.get_user_by_id", return_value={ "email": "t@x" } ), \
             patch( f"{MODULE}.uuid" ), patch( f"{MODULE}.get_db" ) as mock_db, \
             patch( f"{MODULE}.UserRepository" ) as mock_repo_cls:
            _session_on( mock_db )
            mock_repo_cls.return_value.get_by_id.return_value = None
            ok, msg, u = toggle_user_status( "admin", "target", is_active=True )
            self.assertFalse( ok )

    def test_generic_error( self ):
        """
        Ensures:
            - A non-ValueError exception -> (False, "Status update failed...", None)
        """
        with patch( f"{MODULE}.get_user_by_id", return_value={ "email": "t@x" } ), \
             patch( f"{MODULE}.uuid" ), patch( f"{MODULE}.get_db" ) as mock_db, \
             patch( f"{MODULE}.UserRepository" ) as mock_repo_cls:
            _session_on( mock_db )
            mock_repo_cls.return_value.get_by_id.side_effect = Exception( "boom" )
            ok, msg, u = toggle_user_status( "admin", "target", is_active=True )
            self.assertFalse( ok )
            self.assertIn( "Status update failed", msg )


class TestAdminResetPassword( unittest.TestCase ):
    """
    Tests for admin_reset_password().

    Ensures:
        - Not-found, first-pass valid, retry-needed, retry-fails, hashing-failure,
          uuid error, update-failed, success ( with reason ), generic error
    """

    def test_not_found( self ):
        """
        Ensures:
            - get_user_by_id None -> (False, "User not found", None)
        """
        with patch( f"{MODULE}.get_user_by_id", return_value=None ):
            ok, msg, pw = admin_reset_password( "admin", "target" )
            self.assertFalse( ok )

    def test_retry_needed_then_valid( self ):
        """
        Ensures:
            - First strength check fails, retry ( length 20 ) passes -> success
        """
        with patch( f"{MODULE}.get_user_by_id", side_effect=[ { "email": "t@x" } ] ), \
             patch( f"{MODULE}.validate_password_strength", side_effect=[ ( False, "weak" ), ( True, "" ) ] ), \
             patch( f"{MODULE}.hash_password", return_value="$h" ), \
             patch( f"{MODULE}.uuid" ), patch( f"{MODULE}.get_db" ) as mock_db, \
             patch( f"{MODULE}.UserRepository" ) as mock_repo_cls, \
             patch( f"{MODULE}.log_auth_event" ):
            _session_on( mock_db )
            mock_repo_cls.return_value.update_password.return_value = _user()
            ok, msg, pw = admin_reset_password( "admin", "target" )
            self.assertTrue( ok )
            self.assertEqual( len( pw ), 20 )

    def test_retry_still_invalid( self ):
        """
        Ensures:
            - Both strength checks fail -> (False, "Failed to generate valid password...", None)
        """
        with patch( f"{MODULE}.get_user_by_id", return_value={ "email": "t@x" } ), \
             patch( f"{MODULE}.validate_password_strength", side_effect=[ ( False, "weak" ), ( False, "still weak" ) ] ):
            ok, msg, pw = admin_reset_password( "admin", "target" )
            self.assertFalse( ok )
            self.assertIn( "Failed to generate", msg )

    def test_hashing_failure( self ):
        """
        Ensures:
            - A hashing exception -> (False, "Password hashing failed...", None)
        """
        with patch( f"{MODULE}.get_user_by_id", return_value={ "email": "t@x" } ), \
             patch( f"{MODULE}.validate_password_strength", return_value=( True, "" ) ), \
             patch( f"{MODULE}.hash_password", side_effect=Exception( "boom" ) ):
            ok, msg, pw = admin_reset_password( "admin", "target" )
            self.assertFalse( ok )
            self.assertIn( "Password hashing failed", msg )

    def test_invalid_uuid( self ):
        """
        Ensures:
            - uuid ValueError -> (False, "Invalid UUID format", None)
        """
        with patch( f"{MODULE}.get_user_by_id", return_value={ "email": "t@x" } ), \
             patch( f"{MODULE}.validate_password_strength", return_value=( True, "" ) ), \
             patch( f"{MODULE}.hash_password", return_value="$h" ), \
             patch( f"{MODULE}.uuid" ) as mock_uuid:
            mock_uuid.UUID.side_effect = ValueError( "bad" )
            ok, msg, pw = admin_reset_password( "admin", "target" )
            self.assertFalse( ok )
            self.assertIn( "Invalid UUID format", msg )

    def test_update_failed( self ):
        """
        Ensures:
            - update_password None -> (False, "Password update failed", None)
        """
        with patch( f"{MODULE}.get_user_by_id", return_value={ "email": "t@x" } ), \
             patch( f"{MODULE}.validate_password_strength", return_value=( True, "" ) ), \
             patch( f"{MODULE}.hash_password", return_value="$h" ), \
             patch( f"{MODULE}.uuid" ), patch( f"{MODULE}.get_db" ) as mock_db, \
             patch( f"{MODULE}.UserRepository" ) as mock_repo_cls:
            _session_on( mock_db )
            mock_repo_cls.return_value.update_password.return_value = None
            ok, msg, pw = admin_reset_password( "admin", "target" )
            self.assertFalse( ok )
            self.assertIn( "Password update failed", msg )

    def test_success_with_reason( self ):
        """
        Ensures:
            - Happy path with a reason -> (True, success, temp_password)
        """
        with patch( f"{MODULE}.get_user_by_id", return_value={ "email": "t@x" } ), \
             patch( f"{MODULE}.validate_password_strength", return_value=( True, "" ) ), \
             patch( f"{MODULE}.hash_password", return_value="$h" ), \
             patch( f"{MODULE}.uuid" ), patch( f"{MODULE}.get_db" ) as mock_db, \
             patch( f"{MODULE}.UserRepository" ) as mock_repo_cls, \
             patch( f"{MODULE}.log_auth_event" ) as mock_log:
            _session_on( mock_db )
            mock_repo_cls.return_value.update_password.return_value = _user()
            ok, msg, pw = admin_reset_password( "admin", "target", reason="forgot" )
            self.assertTrue( ok )
            self.assertEqual( len( pw ), 16 )
            self.assertIn( "Reason: forgot", mock_log.call_args.kwargs[ "details" ] )

    def test_generic_error( self ):
        """
        Ensures:
            - A non-ValueError exception during DB work -> (False, "Password reset failed...", None)
        """
        with patch( f"{MODULE}.get_user_by_id", return_value={ "email": "t@x" } ), \
             patch( f"{MODULE}.validate_password_strength", return_value=( True, "" ) ), \
             patch( f"{MODULE}.hash_password", return_value="$h" ), \
             patch( f"{MODULE}.uuid" ), patch( f"{MODULE}.get_db" ) as mock_db, \
             patch( f"{MODULE}.UserRepository" ) as mock_repo_cls:
            _session_on( mock_db )
            mock_repo_cls.return_value.update_password.side_effect = Exception( "boom" )
            ok, msg, pw = admin_reset_password( "admin", "target" )
            self.assertFalse( ok )
            self.assertIn( "Password reset failed", msg )


class TestAdminCreateUser( unittest.TestCase ):
    """
    Tests for admin_create_user().

    Ensures:
        - Role validation, create failure, verify-warning, success, generic error
    """

    def test_invalid_roles( self ):
        """
        Ensures:
            - Empty/unknown roles -> (False, "Invalid roles...", None)
        """
        ok, msg, u = admin_create_user( "admin", "a@b.com", "pw", [] )
        self.assertFalse( ok )

    def test_create_fails( self ):
        """
        Ensures:
            - create_user failure is propagated
        """
        with patch( f"{MODULE}.create_user", return_value=( False, "weak password", None ) ):
            ok, msg, u = admin_create_user( "admin", "a@b.com", "pw", [ "user" ] )
            self.assertFalse( ok )
            self.assertEqual( msg, "weak password" )

    def test_success_with_verify_warning( self ):
        """
        Ensures:
            - Even if mark_email_verified fails, the create succeeds ( warning only )
        """
        with patch( f"{MODULE}.create_user", return_value=( True, "ok", "new-id" ) ), \
             patch( f"{MODULE}.mark_email_verified", return_value=( False, "verify failed" ) ), \
             patch( f"{MODULE}.log_auth_event" ), \
             patch( f"{MODULE}.get_user_by_id", return_value={ "id": "new-id" } ), \
             patch( "builtins.print" ):
            ok, msg, u = admin_create_user( "admin", "a@b.com", "pw", [ "user" ] )
            self.assertTrue( ok )
            self.assertEqual( u, { "id": "new-id" } )

    def test_success_clean( self ):
        """
        Ensures:
            - Happy path -> (True, "User created successfully", user_data)
        """
        with patch( f"{MODULE}.create_user", return_value=( True, "ok", "new-id" ) ), \
             patch( f"{MODULE}.mark_email_verified", return_value=( True, "verified" ) ), \
             patch( f"{MODULE}.log_auth_event" ), \
             patch( f"{MODULE}.get_user_by_id", return_value={ "id": "new-id" } ):
            ok, msg, u = admin_create_user( "admin", "a@b.com", "pw", [ "user", "admin" ] )
            self.assertTrue( ok )

    def test_generic_error( self ):
        """
        Ensures:
            - An unexpected exception -> (False, "User creation failed...", None)
        """
        with patch( f"{MODULE}.create_user", side_effect=Exception( "boom" ) ):
            ok, msg, u = admin_create_user( "admin", "a@b.com", "pw", [ "user" ] )
            self.assertFalse( ok )
            self.assertIn( "User creation failed", msg )


class TestAdminDeleteUser( unittest.TestCase ):
    """
    Tests for admin_delete_user().

    Ensures:
        - Self-protection, not-found, protected-account, sole-admin, delete-failed,
          success ( admin w/ co-admins + non-admin ), uuid error, generic error
    """

    def _setup_delete( self, mock_db, protected=False, admin_count=2, deleted=True ):
        """
        Requires:
            - mock_db patched get_db; flags for the protected/sole-admin/delete arms

        Ensures:
            - Wires the protected-check first(), admin-count count(), and repo.delete()
        """
        session, q = _session_on( mock_db )
        prot_row = MagicMock( is_protected=protected )
        q.first.return_value = prot_row
        q.count.return_value = admin_count
        return session

    def test_self_delete_blocked( self ):
        """
        Ensures:
            - admin == target -> (False, "Cannot delete your own account")
        """
        ok, msg = admin_delete_user( "same", "same" )
        self.assertFalse( ok )
        self.assertIn( "Cannot delete your own account", msg )

    def test_not_found( self ):
        """
        Ensures:
            - get_user_by_id None -> (False, "User not found")
        """
        with patch( f"{MODULE}.get_user_by_id", return_value=None ):
            ok, msg = admin_delete_user( "admin", "target" )
            self.assertFalse( ok )

    def test_protected_account( self ):
        """
        Ensures:
            - A system-protected target -> (False, "Cannot delete system-protected...")
        """
        with patch( f"{MODULE}.get_user_by_id", return_value={ "email": "seed@x", "roles": [ "user" ] } ), \
             patch( f"{MODULE}.uuid" ), patch( f"{MODULE}.get_db" ) as mock_db:
            self._setup_delete( mock_db, protected=True )
            ok, msg = admin_delete_user( "admin", "target" )
            self.assertFalse( ok )
            self.assertIn( "system-protected", msg )

    def test_sole_admin_blocked( self ):
        """
        Ensures:
            - Deleting the last active admin -> (False, "Cannot delete the sole admin account")
        """
        with patch( f"{MODULE}.get_user_by_id", return_value={ "email": "a@x", "roles": [ "admin" ] } ), \
             patch( f"{MODULE}.uuid" ), patch( f"{MODULE}.get_db" ) as mock_db:
            self._setup_delete( mock_db, protected=False, admin_count=1 )
            ok, msg = admin_delete_user( "admin", "target" )
            self.assertFalse( ok )
            self.assertIn( "sole admin", msg )

    def test_admin_with_co_admins_success( self ):
        """
        Ensures:
            - Deleting an admin with co-admins revokes tokens, deletes, logs -> success
        """
        with patch( f"{MODULE}.get_user_by_id", return_value={ "email": "a@x", "roles": [ "admin" ] } ), \
             patch( f"{MODULE}.uuid" ), patch( f"{MODULE}.get_db" ) as mock_db, \
             patch( f"{MODULE}.UserRepository" ) as mock_repo_cls, \
             patch( f"{MODULE}.revoke_all_user_tokens" ) as mock_revoke, \
             patch( f"{MODULE}.log_auth_event" ):
            self._setup_delete( mock_db, protected=False, admin_count=3 )
            mock_repo_cls.return_value.delete.return_value = True
            ok, msg = admin_delete_user( "admin", "target", reason="cleanup" )
            self.assertTrue( ok )
            mock_revoke.assert_called_once_with( "target" )

    def test_non_admin_delete_success( self ):
        """
        Ensures:
            - A non-admin target skips the sole-admin guard and deletes cleanly
        """
        with patch( f"{MODULE}.get_user_by_id", return_value={ "email": "u@x", "roles": [ "user" ] } ), \
             patch( f"{MODULE}.uuid" ), patch( f"{MODULE}.get_db" ) as mock_db, \
             patch( f"{MODULE}.UserRepository" ) as mock_repo_cls, \
             patch( f"{MODULE}.revoke_all_user_tokens" ), patch( f"{MODULE}.log_auth_event" ):
            self._setup_delete( mock_db, protected=False )
            mock_repo_cls.return_value.delete.return_value = True
            ok, msg = admin_delete_user( "admin", "target" )
            self.assertTrue( ok )

    def test_delete_failed( self ):
        """
        Ensures:
            - repo.delete falsy -> (False, "Failed to delete user")
        """
        with patch( f"{MODULE}.get_user_by_id", return_value={ "email": "u@x", "roles": [ "user" ] } ), \
             patch( f"{MODULE}.uuid" ), patch( f"{MODULE}.get_db" ) as mock_db, \
             patch( f"{MODULE}.UserRepository" ) as mock_repo_cls, \
             patch( f"{MODULE}.revoke_all_user_tokens" ):
            self._setup_delete( mock_db, protected=False )
            mock_repo_cls.return_value.delete.return_value = False
            ok, msg = admin_delete_user( "admin", "target" )
            self.assertFalse( ok )
            self.assertIn( "Failed to delete", msg )

    def test_invalid_uuid( self ):
        """
        Ensures:
            - uuid ValueError -> (False, "Invalid UUID format")
        """
        with patch( f"{MODULE}.get_user_by_id", return_value={ "email": "u@x", "roles": [ "user" ] } ), \
             patch( f"{MODULE}.uuid" ) as mock_uuid, patch( f"{MODULE}.get_db" ) as mock_db:
            _session_on( mock_db )
            mock_uuid.UUID.side_effect = ValueError( "bad" )
            ok, msg = admin_delete_user( "admin", "target" )
            self.assertFalse( ok )
            self.assertIn( "Invalid UUID format", msg )

    def test_generic_error( self ):
        """
        Ensures:
            - A non-ValueError exception -> (False, "User deletion failed...")
        """
        with patch( f"{MODULE}.get_user_by_id", side_effect=Exception( "boom" ) ):
            ok, msg = admin_delete_user( "admin", "target" )
            self.assertFalse( ok )
            self.assertIn( "User deletion failed", msg )


if __name__ == "__main__":
    unittest.main()
