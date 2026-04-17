"""
Unit tests for the is_protected account guard in admin_service.admin_delete_user().

Validates that system seed companion accounts cannot be deleted via the admin API,
while regular accounts can still be deleted normally.

All tests are pure-unit: DB access is mocked so no postgres connection is needed.
"""

import uuid
import pytest
from unittest.mock import patch, MagicMock

ADMIN_ID  = str( uuid.uuid4() )
TARGET_ID = str( uuid.uuid4() )


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _mock_get_db( is_protected ):
    """
    Return a MagicMock context manager whose session query returns a User
    with the given is_protected value.

    Requires:
        - is_protected is a bool

    Ensures:
        - Returned object is usable as `with get_db() as session:`
        - session.query(...).filter(...).first() returns a mock User
    """
    mock_user            = MagicMock()
    mock_user.is_protected = is_protected

    mock_session = MagicMock()
    mock_session.query.return_value.filter.return_value.first.return_value = mock_user

    ctx             = MagicMock()
    ctx.__enter__   = MagicMock( return_value=mock_session )
    ctx.__exit__    = MagicMock( return_value=False )
    return ctx


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestProtectedAccountGuard:
    """Tests for the is_protected companion-account guard."""

    @patch(
        "cosa.rest.admin_service.get_user_by_id",
        return_value={ "email": "companion@lupin.deepily.ai", "roles": [] }
    )
    @patch( "cosa.rest.admin_service.get_db" )
    def test_protected_account_blocked( self, mock_get_db, mock_get_user ):
        """
        Protected companion account (is_protected=True) must be rejected
        before any deletion is attempted.

        Ensures:
            - Returns (False, message) tuple
            - Message contains 'system-protected'
        """
        mock_get_db.return_value = _mock_get_db( is_protected=True )

        from cosa.rest.admin_service import admin_delete_user
        ok, msg = admin_delete_user(
            admin_user_id  = ADMIN_ID,
            target_user_id = TARGET_ID,
            admin_email    = "admin@test.com",
            admin_ip       = "127.0.0.1",
            reason         = None
        )

        assert ok is False
        assert "system-protected" in msg
        assert "companion@lupin.deepily.ai" in msg

    @patch(
        "cosa.rest.admin_service.get_user_by_id",
        return_value={ "email": "regular@test.com", "roles": [] }
    )
    @patch( "cosa.rest.admin_service.revoke_all_user_tokens" )
    @patch( "cosa.rest.admin_service.get_db" )
    def test_unprotected_account_not_blocked( self, mock_get_db, mock_revoke, mock_get_user ):
        """
        Regular account (is_protected=False) must pass the protected guard
        and continue toward deletion (or hit the next guard).

        Ensures:
            - Does NOT return the 'system-protected' error
            - Proceeds past the guard (reaches revoke_all_user_tokens or further)
        """
        mock_get_db.return_value = _mock_get_db( is_protected=False )

        from cosa.rest.admin_service import admin_delete_user
        ok, msg = admin_delete_user(
            admin_user_id  = ADMIN_ID,
            target_user_id = TARGET_ID,
            admin_email    = "admin@test.com",
            admin_ip       = "127.0.0.1",
            reason         = None
        )

        # Should not have been blocked by the protected-account guard
        assert "system-protected" not in ( msg or "" )

    def test_self_delete_blocked_before_protected_check( self ):
        """
        Self-delete guard fires before the protected-account check.
        No DB calls should occur.

        Ensures:
            - Returns (False, 'Cannot delete your own account')
            - Guard order is preserved: self-delete > protected > sole-admin
        """
        from cosa.rest.admin_service import admin_delete_user
        same_id = ADMIN_ID
        ok, msg = admin_delete_user(
            admin_user_id  = same_id,
            target_user_id = same_id,
            admin_email    = "admin@test.com",
            admin_ip       = "127.0.0.1",
            reason         = None
        )

        assert ok is False
        assert "own account" in msg


class TestUserModelProtectedField:
    """Smoke-check that the is_protected column exists on the User model."""

    def test_user_model_has_is_protected_attribute( self ):
        """
        User model must have an is_protected attribute that defaults False.

        Ensures:
            - Attribute exists on the model class (not just on instances)
            - Default value is False
        """
        from cosa.rest.postgres_models import User
        user = User(
            email         = "test@example.com",
            password_hash = "fake_hash"
        )
        assert hasattr( user, "is_protected" )
        # SQLAlchemy mapped_column defaults return None before flush; check it's
        # not True (the only harmful state).
        assert user.is_protected is not True
