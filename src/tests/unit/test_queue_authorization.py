"""
Unit Tests for Queue Authorization

Tests the authorize_queue_filter() function from cosa.rest.queue_auth module.
Validates role-based access control for queue filtering operations.
"""

import pytest
from fastapi import HTTPException
from cosa.rest.queue_auth import authorize_queue_filter


class TestQueueAuthorization:
    """Unit tests for queue filtering authorization logic."""

    # ==================== Regular User Scenarios ====================

    def test_regular_user_no_filter_returns_own_id(self):
        """Regular user with no filter parameter gets their own user_id."""
        user = {"uid": "user_123", "roles": ["user"]}

        result = authorize_queue_filter(user, None)

        assert result == "user_123"

    def test_regular_user_wildcard_raises_403(self):
        """Regular user requesting wildcard '*' raises 403 Forbidden."""
        user = {"uid": "user_123", "roles": ["user"]}

        with pytest.raises(HTTPException) as exc:
            authorize_queue_filter(user, "*")

        assert exc.value.status_code == 403
        assert "admin" in exc.value.detail.lower()

    def test_regular_user_other_user_raises_403(self):
        """Regular user requesting another user's jobs raises 403 Forbidden."""
        user = {"uid": "user_123", "roles": ["user"]}

        with pytest.raises(HTTPException) as exc:
            authorize_queue_filter(user, "user_456")

        assert exc.value.status_code == 403
        assert "cannot access other users" in exc.value.detail.lower()

    def test_regular_user_own_id_explicit_returns_own(self):
        """Regular user explicitly requesting their own ID succeeds."""
        user = {"uid": "user_123", "roles": ["user"]}

        result = authorize_queue_filter(user, "user_123")

        assert result == "user_123"

    # ==================== Admin User Scenarios ====================

    def test_admin_no_filter_returns_own_id(self):
        """Admin with no filter parameter gets their own user_id (not wildcard)."""
        user = {"uid": "admin_123", "roles": ["admin", "user"]}

        result = authorize_queue_filter(user, None)

        assert result == "admin_123"

    def test_admin_wildcard_returns_wildcard(self):
        """Admin requesting wildcard '*' succeeds and returns wildcard."""
        user = {"uid": "admin_123", "roles": ["admin", "user"]}

        result = authorize_queue_filter(user, "*")

        assert result == "*"

    def test_admin_specific_user_returns_user_id(self):
        """Admin requesting specific user's jobs succeeds."""
        user = {"uid": "admin_123", "roles": ["admin"]}

        result = authorize_queue_filter(user, "user_456")

        assert result == "user_456"

    def test_admin_own_id_explicit_returns_own(self):
        """Admin explicitly requesting their own ID succeeds."""
        user = {"uid": "admin_123", "roles": ["admin"]}

        result = authorize_queue_filter(user, "admin_123")

        assert result == "admin_123"

    def test_admin_role_only_sufficient(self):
        """Admin role alone (without user role) is sufficient for admin operations."""
        user = {"uid": "admin_456", "roles": ["admin"]}  # No "user" role

        result = authorize_queue_filter(user, "*")

        assert result == "*"

    # ==================== "!self" (Not Mine) Filter Scenarios ====================

    def test_admin_not_self_returns_exclamation_prefix(self):
        """Admin requesting '!self' gets '!<own_user_id>' sentinel."""
        user = {"uid": "admin_123", "roles": ["admin", "user"]}

        result = authorize_queue_filter( user, "!self" )

        assert result == "!admin_123"

    def test_admin_not_self_preserves_user_id(self):
        """'!self' sentinel contains the requesting admin's actual user_id."""
        user = {"uid": "ricardo_felipe_ruiz_6bdc", "roles": ["admin"]}

        result = authorize_queue_filter( user, "!self" )

        assert result == "!ricardo_felipe_ruiz_6bdc"
        assert result.startswith( "!" )
        assert result[ 1: ] == "ricardo_felipe_ruiz_6bdc"

    def test_regular_user_not_self_raises_403(self):
        """Regular user requesting '!self' raises 403 Forbidden."""
        user = {"uid": "user_123", "roles": ["user"]}

        with pytest.raises( HTTPException ) as exc:
            authorize_queue_filter( user, "!self" )

        assert exc.value.status_code == 403
        assert "admin" in exc.value.detail.lower()

    def test_empty_roles_not_self_raises_403(self):
        """User with empty roles requesting '!self' raises 403."""
        user = {"uid": "user_789", "roles": []}

        with pytest.raises( HTTPException ) as exc:
            authorize_queue_filter( user, "!self" )

        assert exc.value.status_code == 403

    # ==================== Edge Cases ====================

    def test_empty_roles_treated_as_regular_user(self):
        """User with empty roles list treated as regular user (no admin privileges)."""
        user = {"uid": "user_789", "roles": []}

        with pytest.raises(HTTPException) as exc:
            authorize_queue_filter(user, "*")

        assert exc.value.status_code == 403

    def test_missing_roles_field_treated_as_regular_user(self):
        """User dict without 'roles' field treated as regular user."""
        user = {"uid": "user_999"}  # No 'roles' key

        # Should still work for own jobs (default behavior)
        result = authorize_queue_filter(user, None)
        assert result == "user_999"

        # But should fail for wildcard
        with pytest.raises(HTTPException) as exc:
            authorize_queue_filter(user, "*")
        assert exc.value.status_code == 403

    def test_case_sensitive_role_check(self):
        """Role checking is case-sensitive (Admin != admin)."""
        user = {"uid": "user_case", "roles": ["User", "Admin"]}  # Wrong case

        # This depends on auth_middleware.is_admin() implementation
        # Assuming it checks for lowercase "admin"
        with pytest.raises(HTTPException) as exc:
            authorize_queue_filter(user, "*")
        assert exc.value.status_code == 403

    def test_multiple_roles_admin_included(self):
        """User with multiple roles including 'admin' has admin privileges."""
        user = {"uid": "multi_role", "roles": ["user", "moderator", "admin", "developer"]}

        result = authorize_queue_filter(user, "*")

        assert result == "*"

    # ==================== Authorization Matrix Validation ====================

    def test_authorization_matrix_regular_user(self):
        """Validate complete authorization matrix for regular users."""
        user = {"uid": "regular_user", "roles": ["user"]}

        # None → own_id ✓
        assert authorize_queue_filter(user, None) == "regular_user"

        # "*" → 403 ✗
        with pytest.raises(HTTPException) as exc:
            authorize_queue_filter(user, "*")
        assert exc.value.status_code == 403

        # "!self" → 403 ✗
        with pytest.raises(HTTPException) as exc:
            authorize_queue_filter(user, "!self")
        assert exc.value.status_code == 403

        # other_id → 403 ✗
        with pytest.raises(HTTPException) as exc:
            authorize_queue_filter(user, "other_user")
        assert exc.value.status_code == 403

        # own_id → own_id ✓
        assert authorize_queue_filter(user, "regular_user") == "regular_user"

    def test_authorization_matrix_admin_user(self):
        """Validate complete authorization matrix for admin users."""
        user = {"uid": "admin_user", "roles": ["admin", "user"]}

        # None → own_id ✓
        assert authorize_queue_filter(user, None) == "admin_user"

        # "*" → "*" ✓
        assert authorize_queue_filter(user, "*") == "*"

        # "!self" → "!admin_user" ✓
        assert authorize_queue_filter(user, "!self") == "!admin_user"

        # other_id → other_id ✓
        assert authorize_queue_filter(user, "other_user") == "other_user"

        # own_id → own_id ✓
        assert authorize_queue_filter(user, "admin_user") == "admin_user"

    # ==================== Error Message Validation ====================

    def test_error_message_clarity_wildcard(self):
        """403 error for wildcard has clear, helpful message."""
        user = {"uid": "user_123", "roles": ["user"]}

        with pytest.raises(HTTPException) as exc:
            authorize_queue_filter(user, "*")

        detail = exc.value.detail.lower()
        assert "admin" in detail
        assert "all jobs" in detail or "own jobs" in detail

    def test_error_message_clarity_other_user(self):
        """403 error for other user access has clear, helpful message."""
        user = {"uid": "user_123", "roles": ["user"]}

        with pytest.raises(HTTPException) as exc:
            authorize_queue_filter(user, "user_456")

        detail = exc.value.detail.lower()
        assert "cannot access" in detail or "own jobs" in detail
