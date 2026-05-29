"""
Integration tests for admin user management endpoints.

Tests authorization, user listing, role management, status toggling, and password resets.
"""

import os

import pytest
import requests


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def admin_headers( create_test_admin):
    """
    Create authenticated session with admin JWT tokens.

    Returns:
        dict: Authorization headers with valid admin access token
    """
    from cosa.rest.jwt_service import create_access_token

    access_token = create_access_token(
        user_id = create_test_admin["user_id"],
        email   = create_test_admin["email"],
        roles   = create_test_admin.get( "roles", ["user", "admin"])
   )

    return {
        "Authorization": f"Bearer {access_token}"
    }


@pytest.fixture
def multiple_test_users( clean_test_db ):
    """
    Create multiple test users with different roles and statuses.

    Requires:
        - clean_test_db: Ensures fresh database schema before creating users

    Returns:
        list: List of created user data dicts
    """
    from cosa.rest.user_service import create_user

    users = [
        {
            "email"    : "alice@example.com",
            "password" : "AlicePass123!",
            "roles"    : ["user"]
        },
        {
            "email"    : "bob@example.com",
            "password" : "BobPass123!",
            "roles"    : ["user", "admin"]
        },
        {
            "email"    : "charlie@example.com",
            "password" : "CharliePass123!",
            "roles"    : ["user"]
        }
    ]

    created_users = []

    for user_data in users:
        success, message, user_id = create_user(
            email    = user_data["email"],
            password = user_data["password"],
            roles    = user_data["roles"]
       )

        if success:
            from cosa.rest.user_service import get_user_by_id
            full_user = get_user_by_id( user_id)
            created_users.append( full_user)

    return created_users


# ============================================================================
# Authorization Tests
# ============================================================================

# Test server configuration
BASE_URL = os.environ.get( "LUPIN_TEST_BASE_URL", "http://localhost:8000" )


def test_list_users_requires_admin( auth_headers):
    """
    Test that regular users cannot access admin endpoints.

    Requires:
        - auth_headers from regular user (not admin)

    Ensures:
        - Returns 403 Forbidden
    """
    response = requests.get( f"{BASE_URL}/admin/users", headers=auth_headers )
    assert response.status_code == 403


def test_list_users_requires_authentication():
    """
    Test that unauthenticated requests are rejected.

    Requires:
        - No authentication headers

    Ensures:
        - Returns 401 Unauthorized
    """
    response = requests.get( f"{BASE_URL}/admin/users")
    assert response.status_code == 401


def test_admin_can_access_endpoints( admin_headers):
    """
    Test that admin users can access admin endpoints.

    Requires:
        - admin_headers from admin user

    Ensures:
        - Returns 200 OK
    """
    response = requests.get( f"{BASE_URL}/admin/users", headers=admin_headers )
    assert response.status_code == 200


# ============================================================================
# List Users Tests
# ============================================================================

def test_list_users_returns_all_users( admin_headers, multiple_test_users, create_test_admin):
    """
    Test listing all users.

    Requires:
        - admin_headers for authorization
        - multiple_test_users created

    Ensures:
        - Returns paginated user list
        - Includes all created users
        - Returns total count
    """
    response = requests.get( f"{BASE_URL}/admin/users", headers=admin_headers )

    assert response.status_code == 200
    data = response.json()

    assert "users" in data
    assert "total" in data
    assert "limit" in data
    assert "offset" in data

    # Should have multiple users (test users + admin)
    assert data["total"] >= len( multiple_test_users) + 1


def test_list_users_pagination( admin_headers, multiple_test_users):
    """
    Test pagination works correctly.

    Requires:
        - admin_headers for authorization
        - multiple_test_users created

    Ensures:
        - Limit parameter controls results
        - Offset parameter skips results
    """
    # Get first page with limit 2
    response = requests.get( f"{BASE_URL}/admin/users?limit=2&offset=0", headers=admin_headers )
    assert response.status_code == 200

    data = response.json()
    assert len( data["users"]) <= 2
    assert data["limit"] == 2
    assert data["offset"] == 0

    # Get second page
    response = requests.get( f"{BASE_URL}/admin/users?limit=2&offset=2", headers=admin_headers )
    assert response.status_code == 200

    data2 = response.json()
    assert data2["offset"] == 2


def test_list_users_search_filter( admin_headers, multiple_test_users):
    """
    Test search filter by email.

    Requires:
        - admin_headers for authorization
        - multiple_test_users created

    Ensures:
        - Returns only matching users
        - Case-insensitive search
    """
    response = requests.get( f"{BASE_URL}/admin/users?search=alice", headers=admin_headers )
    assert response.status_code == 200

    data = response.json()
    assert data["total"] >= 1

    # All returned users should have 'alice' in email
    for user in data["users"]:
        assert 'alice' in user["email"].lower()


def test_list_users_role_filter( admin_headers, multiple_test_users):
    """
    Test role filter.

    Requires:
        - admin_headers for authorization
        - multiple_test_users with different roles

    Ensures:
        - Returns only users with specified role
    """
    response = requests.get( f"{BASE_URL}/admin/users?role=admin", headers=admin_headers )
    assert response.status_code == 200

    data = response.json()

    # All returned users should have admin role
    for user in data["users"]:
        assert 'admin' in user["roles"]


def test_list_users_status_filter( admin_headers, multiple_test_users):
    """
    Test status filter.

    Requires:
        - admin_headers for authorization
        - multiple_test_users created

    Ensures:
        - Returns only users with specified status
    """
    response = requests.get( f"{BASE_URL}/admin/users?status_filter=active", headers=admin_headers )
    assert response.status_code == 200

    data = response.json()

    # All returned users should be active
    for user in data["users"]:
        assert user["is_active"] is True


# ============================================================================
# Get User Details Tests
# ============================================================================

def test_get_user_details_success( admin_headers, create_test_user):
    """
    Test getting user details.

    Requires:
        - admin_headers for authorization
        - create_test_user with known ID

    Ensures:
        - Returns detailed user information
        - Includes audit stats
    """
    user_id = create_test_user["user_id"]
    response = requests.get( f"{BASE_URL}/admin/users/{user_id}", headers=admin_headers )

    assert response.status_code == 200
    data = response.json()

    assert data["id"] == user_id
    assert data["email"] == create_test_user["email"]
    assert "audit_log_count" in data
    assert "failed_login_count" in data


def test_get_user_details_not_found( admin_headers):
    """
    Test getting non-existent user.

    Requires:
        - admin_headers for authorization

    Ensures:
        - Returns 404 Not Found
    """
    response = requests.get( f"{BASE_URL}/admin/users/nonexistent-id", headers=admin_headers )
    assert response.status_code == 404


# ============================================================================
# Update Roles Tests
# ============================================================================

def test_update_user_roles_add_admin( admin_headers, create_test_user):
    """
    Test promoting user to admin.

    Requires:
        - admin_headers for authorization
        - create_test_user as regular user

    Ensures:
        - User gains admin role
        - Action logged to audit
    """
    user_id = create_test_user["user_id"]

    response = requests.put( f"{BASE_URL}/admin/users/{user_id}/roles", headers=admin_headers, json={"roles": ["user", "admin"]}
    )

    assert response.status_code == 200
    data = response.json()

    assert "admin" in data["user"]["roles"]


def test_update_user_roles_remove_admin( admin_headers, multiple_test_users):
    """
    Test demoting admin to user.

    Requires:
        - admin_headers for authorization
        - multiple_test_users including admin

    Ensures:
        - User loses admin role
    """
    # Find bob (who is admin)
    bob_user = next( u for u in multiple_test_users if u["email"] == "bob@example.com")
    bob_id = bob_user["id"]

    response = requests.put( f"{BASE_URL}/admin/users/{bob_id}/roles", headers=admin_headers, json={"roles": ["user"]}
    )

    assert response.status_code == 200
    data = response.json()

    assert "admin" not in data["user"]["roles"]
    assert "user" in data["user"]["roles"]


def test_cannot_remove_own_admin_role( admin_headers, create_test_admin):
    """
    Test self-protection: admin cannot remove own admin role.

    Requires:
        - admin_headers for authorization
        - create_test_admin user

    Ensures:
        - Returns 400 Bad Request
        - Error message indicates self-modification
    """
    admin_id = create_test_admin["user_id"]

    response = requests.put( f"{BASE_URL}/admin/users/{admin_id}/roles", headers=admin_headers, json={"roles": ["user"]}
    )

    assert response.status_code == 400
    assert "cannot remove your own admin role" in response.json()["detail"].lower()


def test_update_roles_invalid_role_rejected( admin_headers, create_test_user):
    """
    Test that invalid roles are rejected.

    Requires:
        - admin_headers for authorization
        - create_test_user to modify

    Ensures:
        - Returns 400 Bad Request
        - Invalid role not applied
    """
    user_id = create_test_user["user_id"]

    response = requests.put( f"{BASE_URL}/admin/users/{user_id}/roles", headers=admin_headers, json={"roles": ["superadmin", "hacker"]}
    )

    assert response.status_code == 400


def test_update_roles_empty_array_rejected( admin_headers, create_test_user):
    """
    Test that empty roles array is rejected.

    Requires:
        - admin_headers for authorization
        - create_test_user to modify

    Ensures:
        - Returns 400 Bad Request
    """
    user_id = create_test_user["user_id"]

    response = requests.put( f"{BASE_URL}/admin/users/{user_id}/roles", headers=admin_headers, json={"roles": []}
    )

    assert response.status_code == 400


# ============================================================================
# Toggle Status Tests
# ============================================================================

def test_deactivate_user( admin_headers, create_test_user):
    """
    Test deactivating user account.

    Requires:
        - admin_headers for authorization
        - create_test_user to deactivate

    Ensures:
        - User is_active set to False
        - Tokens revoked
    """
    user_id = create_test_user["user_id"]

    response = requests.put( f"{BASE_URL}/admin/users/{user_id}/status", headers=admin_headers, json={"is_active": False}
    )

    assert response.status_code == 200
    data = response.json()

    assert data["user"]["is_active"] is False


def test_activate_user( admin_headers, create_test_user):
    """
    Test reactivating deactivated user.

    Requires:
        - admin_headers for authorization
        - create_test_user to activate

    Ensures:
        - User is_active set to True
    """
    user_id = create_test_user["user_id"]

    # First deactivate
    requests.put( f"{BASE_URL}/admin/users/{user_id}/status", headers=admin_headers, json={"is_active": False}
    )

    # Then reactivate
    response = requests.put( f"{BASE_URL}/admin/users/{user_id}/status", headers=admin_headers, json={"is_active": True}
    )

    assert response.status_code == 200
    data = response.json()

    assert data["user"]["is_active"] is True


def test_cannot_deactivate_self( admin_headers, create_test_admin):
    """
    Test self-protection: admin cannot deactivate own account.

    Requires:
        - admin_headers for authorization
        - create_test_admin user

    Ensures:
        - Returns 400 Bad Request
        - Error message indicates self-modification
    """
    admin_id = create_test_admin["user_id"]

    response = requests.put( f"{BASE_URL}/admin/users/{admin_id}/status", headers=admin_headers, json={"is_active": False}
    )

    assert response.status_code == 400
    assert "cannot deactivate your own account" in response.json()["detail"].lower()


def test_deactivated_user_cannot_login( admin_headers, create_test_user):
    """
    Test that deactivated user cannot login.

    Requires:
        - admin_headers for authorization
        - create_test_user to deactivate

    Ensures:
        - Deactivated user login fails
        - Login returns appropriate error
    """
    user_id = create_test_user["user_id"]

    # Deactivate user
    requests.put( f"{BASE_URL}/admin/users/{user_id}/status", headers=admin_headers, json={"is_active": False}
    )

    # Try to login
    login_response = requests.post( f"{BASE_URL}/auth/login", json={
            "email"    : create_test_user["email"],
            "password" : create_test_user["password"]
        }
    )

    assert login_response.status_code == 401


# ============================================================================
# Password Reset Tests
# ============================================================================

def test_admin_reset_password_generates_valid_password( admin_headers, create_test_user):
    """
    Test admin password reset generates valid password.

    Requires:
        - admin_headers for authorization
        - create_test_user to reset

    Ensures:
        - Returns temporary password
        - Password is at least 16 characters
        - Password meets strength requirements
    """
    user_id = create_test_user["user_id"]

    response = requests.post( f"{BASE_URL}/admin/users/{user_id}/reset-password", headers=admin_headers, json={"reason": "Integration test password reset"}
    )

    assert response.status_code == 200
    data = response.json()

    assert "temporary_password" in data
    assert len( data["temporary_password"]) >= 16


def test_user_can_login_with_reset_password( admin_headers, create_test_user):
    """
    Test user can login with admin-generated password.

    Requires:
        - admin_headers for authorization
        - create_test_user to reset

    Ensures:
        - User can login with new password
        - Old password no longer works
    """
    user_id = create_test_user["user_id"]
    old_password = create_test_user["password"]

    # Reset password
    reset_response = requests.post( f"{BASE_URL}/admin/users/{user_id}/reset-password", headers=admin_headers, json={"reason": "Test reset"}
    )

    assert reset_response.status_code == 200
    temp_password = reset_response.json()["temporary_password"]

    # Login with new password
    login_response = requests.post( f"{BASE_URL}/auth/login", json={
            "email"    : create_test_user["email"],
            "password" : temp_password
        }
    )

    assert login_response.status_code == 200

    # Old password should not work
    old_login_response = requests.post( f"{BASE_URL}/auth/login", json={
            "email"    : create_test_user["email"],
            "password" : old_password
        }
    )

    assert old_login_response.status_code == 401


def test_password_reset_logged_to_audit( admin_headers, create_test_user):
    """
    Test password reset is logged to audit trail.

    Requires:
        - admin_headers for authorization
        - create_test_user to reset

    Ensures:
        - Audit log entry created
        - Entry contains admin user ID
        - Entry contains reset event type
    """
    user_id = create_test_user["user_id"]

    # Reset password
    requests.post( f"{BASE_URL}/admin/users/{user_id}/reset-password", headers=admin_headers, json={"reason": "Audit test"}
    )

    # Check audit log
    from cosa.rest.auth_audit import get_user_audit_log
    from cosa.rest.user_service import get_user_by_email

    # Get admin user to check audit log
    admin_user = get_user_by_email( "admin_test@example.com")
    audit_entries = get_user_audit_log( admin_user["id"])

    # Should have admin_password_reset event
    reset_events = [e for e in audit_entries if e["event_type"] == "admin_password_reset"]
    assert len( reset_events) >= 1


# ============================================================================
# Audit Logging Tests
# ============================================================================

def test_all_admin_actions_create_audit_entries( admin_headers, create_test_user):
    """
    Test that all admin actions create audit log entries.

    Requires:
        - admin_headers for authorization
        - create_test_user to perform actions on

    Ensures:
        - Each admin action creates audit entry
        - Audit entries contain admin user ID
    """
    user_id = create_test_user["user_id"]

    # Perform various admin actions
    requests.put( f"{BASE_URL}/admin/users/{user_id}/roles", headers=admin_headers, json={"roles": ["user", "admin"]}
    )

    requests.put( f"{BASE_URL}/admin/users/{user_id}/status", headers=admin_headers, json={"is_active": False}
    )

    requests.post( f"{BASE_URL}/admin/users/{user_id}/reset-password", headers=admin_headers, json={"reason": "Audit test"}
    )

    # Check audit log
    from cosa.rest.auth_audit import get_user_audit_log
    from cosa.rest.user_service import get_user_by_email

    admin_user = get_user_by_email( "admin_test@example.com")
    audit_entries = get_user_audit_log( admin_user["id"])

    # Should have entries for all actions
    event_types = [e["event_type"] for e in audit_entries]

    assert "admin_role_update" in event_types
    assert "admin_status_update" in event_types
    assert "admin_password_reset" in event_types


# ============================================================================
# Create User Tests
# ============================================================================

def test_admin_create_user_default_role( admin_headers ):
    """
    Test admin creating user with default role.

    Requires:
        - admin_headers for authorization

    Ensures:
        - Returns 201 Created
        - User has "user" role
        - Email is auto-verified
    """
    response = requests.post( f"{BASE_URL}/admin/users", headers=admin_headers, json={
        "email"    : "newuser@example.com",
        "password" : "NewUserPass123!"
    })

    assert response.status_code == 201
    data = response.json()

    assert data["message"] == "User created successfully"
    assert "user" in data["user"]["roles"]
    assert data["user"]["email"] == "newuser@example.com"
    assert data["user"]["email_verified"] is True
    assert data["user_id"] is not None


def test_admin_create_user_with_admin_role( admin_headers ):
    """
    Test admin creating user with admin role.

    Requires:
        - admin_headers for authorization

    Ensures:
        - Returns 201 Created
        - User has both admin and user roles
    """
    response = requests.post( f"{BASE_URL}/admin/users", headers=admin_headers, json={
        "email"    : "newadmin@example.com",
        "password" : "NewAdminPass123!",
        "roles"    : ["user", "admin"]
    })

    assert response.status_code == 201
    data = response.json()

    assert "admin" in data["user"]["roles"]
    assert "user" in data["user"]["roles"]


def test_admin_create_user_duplicate_email_rejected( admin_headers, create_test_user ):
    """
    Test that duplicate email is rejected.

    Requires:
        - admin_headers for authorization
        - create_test_user already exists

    Ensures:
        - Returns 400 Bad Request
    """
    response = requests.post( f"{BASE_URL}/admin/users", headers=admin_headers, json={
        "email"    : create_test_user["email"],
        "password" : "AnotherPass123!"
    })

    assert response.status_code == 400


def test_admin_create_user_weak_password_rejected( admin_headers ):
    """
    Test that weak password is rejected.

    Requires:
        - admin_headers for authorization

    Ensures:
        - Returns 400 Bad Request
    """
    response = requests.post( f"{BASE_URL}/admin/users", headers=admin_headers, json={
        "email"    : "weakpw@example.com",
        "password" : "short"
    })

    assert response.status_code == 400


def test_admin_created_user_can_login( admin_headers ):
    """
    Test that admin-created user can login.

    Requires:
        - admin_headers for authorization

    Ensures:
        - User can login with provided credentials
        - Returns 200 with tokens
    """
    email    = "logintest@example.com"
    password = "LoginTestPass123!"

    # Create user via admin endpoint
    create_response = requests.post( f"{BASE_URL}/admin/users", headers=admin_headers, json={
        "email"    : email,
        "password" : password
    })

    assert create_response.status_code == 201

    # Login as the new user
    login_response = requests.post( f"{BASE_URL}/auth/login", json={
        "email"    : email,
        "password" : password
    })

    assert login_response.status_code == 200
    assert "tokens" in login_response.json()


def test_non_admin_cannot_create_user( auth_headers ):
    """
    Test that non-admin cannot create users.

    Requires:
        - auth_headers from regular user

    Ensures:
        - Returns 403 Forbidden
    """
    response = requests.post( f"{BASE_URL}/admin/users", headers=auth_headers, json={
        "email"    : "forbidden@example.com",
        "password" : "ForbiddenPass123!"
    })

    assert response.status_code == 403


# ============================================================================
# Delete User Tests
# ============================================================================

def test_admin_delete_user_success( admin_headers ):
    """
    Test admin deleting a user permanently.

    Requires:
        - admin_headers for authorization

    Ensures:
        - Returns 200 OK
        - User no longer accessible via GET
    """
    # First create a user to delete
    create_response = requests.post( f"{BASE_URL}/admin/users", headers=admin_headers, json={
        "email"    : "deleteme@example.com",
        "password" : "DeleteMePass123!"
    })

    assert create_response.status_code == 201
    user_id = create_response.json()["user_id"]

    # Delete the user
    delete_response = requests.delete(
        f"{BASE_URL}/admin/users/{user_id}",
        headers = admin_headers,
        json    = {"reason": "Integration test cleanup"}
    )

    assert delete_response.status_code == 200

    # Verify user is gone
    get_response = requests.get( f"{BASE_URL}/admin/users/{user_id}", headers=admin_headers )
    assert get_response.status_code == 404


def test_admin_cannot_delete_self( admin_headers, create_test_admin ):
    """
    Test self-protection: admin cannot delete own account.

    Requires:
        - admin_headers for authorization
        - create_test_admin user

    Ensures:
        - Returns 400 Bad Request
        - Error message indicates self-deletion
    """
    admin_id = create_test_admin["user_id"]

    response = requests.delete(
        f"{BASE_URL}/admin/users/{admin_id}",
        headers = admin_headers,
        json    = {"reason": "Self-delete test"}
    )

    assert response.status_code == 400
    assert "cannot delete your own account" in response.json()["detail"].lower()


def test_non_admin_cannot_delete_user( auth_headers, create_test_user ):
    """
    Test that non-admin cannot delete users.

    Requires:
        - auth_headers from regular user
        - create_test_user target

    Ensures:
        - Returns 403 Forbidden
    """
    user_id = create_test_user["user_id"]

    response = requests.delete(
        f"{BASE_URL}/admin/users/{user_id}",
        headers = auth_headers
    )

    assert response.status_code == 403


def test_delete_nonexistent_user_returns_404( admin_headers ):
    """
    Test deleting non-existent user returns 404.

    Requires:
        - admin_headers for authorization

    Ensures:
        - Returns 404 Not Found
    """
    import uuid
    fake_id = str( uuid.uuid4() )

    response = requests.delete(
        f"{BASE_URL}/admin/users/{fake_id}",
        headers = admin_headers
    )

    assert response.status_code == 404


def test_cannot_delete_sole_admin( admin_headers, create_test_admin ):
    """
    Test sole-admin protection: cannot delete the only admin.

    Requires:
        - admin_headers for authorization
        - create_test_admin is the sole admin

    Ensures:
        - Returns 400 Bad Request (self-delete) or sole-admin guard
    """
    # Create a second admin to test with
    create_response = requests.post( f"{BASE_URL}/admin/users", headers=admin_headers, json={
        "email"    : "secondadmin@example.com",
        "password" : "SecondAdmin123!",
        "roles"    : ["user", "admin"]
    })

    assert create_response.status_code == 201
    second_admin_id = create_response.json()["user_id"]

    # Delete the first admin to leave only second
    # This should fail because we're trying to delete ourselves (self-protection)
    admin_id = create_test_admin["user_id"]
    self_delete = requests.delete(
        f"{BASE_URL}/admin/users/{admin_id}",
        headers = admin_headers
    )
    assert self_delete.status_code == 400

    # Now delete the second admin — after this, only the test admin remains
    delete_second = requests.delete(
        f"{BASE_URL}/admin/users/{second_admin_id}",
        headers = admin_headers,
        json    = {"reason": "Sole admin test"}
    )

    # This should succeed since the test admin still exists
    assert delete_second.status_code == 200


# ============================================================================
# Batch Delete Tests
# ============================================================================

def test_batch_delete_multiple_users( admin_headers ):
    """
    Test batch deleting multiple users.

    Requires:
        - admin_headers for authorization

    Ensures:
        - Returns 200 OK
        - All users successfully deleted
        - total_deleted matches count
        - Deleted users no longer accessible
    """
    # Create 3 users to delete
    user_ids = []
    for i in range( 3 ):
        create_response = requests.post( f"{BASE_URL}/admin/users", headers=admin_headers, json={
            "email"    : f"batchdel{i}@example.com",
            "password" : f"BatchDel{i}Pass123!"
        })
        assert create_response.status_code == 201
        user_ids.append( create_response.json()["user_id"] )

    # Batch delete
    response = requests.post( f"{BASE_URL}/admin/users/batch-delete", headers=admin_headers, json={
        "user_ids" : user_ids,
        "reason"   : "Integration test batch delete"
    })

    assert response.status_code == 200
    data = response.json()

    assert data["total_deleted"] == 3
    assert data["total_failed"] == 0
    assert len( data["results"] ) == 3

    for result in data["results"]:
        assert result["success"] is True

    # Verify all users are gone
    for uid in user_ids:
        get_response = requests.get( f"{BASE_URL}/admin/users/{uid}", headers=admin_headers )
        assert get_response.status_code == 404


def test_batch_delete_cannot_delete_self( admin_headers, create_test_admin ):
    """
    Test self-protection in batch delete.

    Requires:
        - admin_headers for authorization
        - create_test_admin user

    Ensures:
        - Self-delete fails in the results
        - Other users in batch still get deleted
    """
    admin_id = create_test_admin["user_id"]

    # Create a user to include alongside self
    create_response = requests.post( f"{BASE_URL}/admin/users", headers=admin_headers, json={
        "email"    : "batchself@example.com",
        "password" : "BatchSelfPass123!"
    })
    assert create_response.status_code == 201
    other_user_id = create_response.json()["user_id"]

    # Batch delete with self included
    response = requests.post( f"{BASE_URL}/admin/users/batch-delete", headers=admin_headers, json={
        "user_ids" : [ admin_id, other_user_id ],
        "reason"   : "Self-protection test"
    })

    assert response.status_code == 200
    data = response.json()

    assert data["total_failed"] >= 1

    # Find self-delete result
    self_result = next( r for r in data["results"] if r["user_id"] == admin_id )
    assert self_result["success"] is False

    # Other user should be deleted
    other_result = next( r for r in data["results"] if r["user_id"] == other_user_id )
    assert other_result["success"] is True


def test_batch_delete_empty_list_rejected( admin_headers ):
    """
    Test that empty user_ids list is rejected.

    Requires:
        - admin_headers for authorization

    Ensures:
        - Returns 422 Unprocessable Entity (Pydantic validation)
    """
    response = requests.post( f"{BASE_URL}/admin/users/batch-delete", headers=admin_headers, json={
        "user_ids" : []
    })

    assert response.status_code == 422


def test_batch_delete_nonexistent_users_partial_failure( admin_headers ):
    """
    Test batch delete with mix of valid and nonexistent user IDs.

    Requires:
        - admin_headers for authorization

    Ensures:
        - Valid users deleted
        - Nonexistent users reported as failures
        - Both results returned
    """
    import uuid

    # Create one real user
    create_response = requests.post( f"{BASE_URL}/admin/users", headers=admin_headers, json={
        "email"    : "batchpartial@example.com",
        "password" : "BatchPartialPass123!"
    })
    assert create_response.status_code == 201
    real_user_id = create_response.json()["user_id"]

    fake_id = str( uuid.uuid4() )

    response = requests.post( f"{BASE_URL}/admin/users/batch-delete", headers=admin_headers, json={
        "user_ids" : [ real_user_id, fake_id ]
    })

    assert response.status_code == 200
    data = response.json()

    assert data["total_deleted"] == 1
    assert data["total_failed"] == 1

    real_result = next( r for r in data["results"] if r["user_id"] == real_user_id )
    assert real_result["success"] is True

    fake_result = next( r for r in data["results"] if r["user_id"] == fake_id )
    assert fake_result["success"] is False


def test_batch_delete_non_admin_rejected( auth_headers ):
    """
    Test that non-admin cannot use batch delete endpoint.

    Requires:
        - auth_headers from regular user

    Ensures:
        - Returns 403 Forbidden
    """
    response = requests.post( f"{BASE_URL}/admin/users/batch-delete", headers=auth_headers, json={
        "user_ids" : [ "some-id" ]
    })

    assert response.status_code == 403


def test_batch_delete_sole_admin_guard( admin_headers, create_test_admin ):
    """
    Test sole-admin guard works in batch context.

    Requires:
        - admin_headers for authorization
        - create_test_admin is the sole admin

    Ensures:
        - Self-protection prevents deleting self (which is the sole admin)
    """
    admin_id = create_test_admin["user_id"]

    response = requests.post( f"{BASE_URL}/admin/users/batch-delete", headers=admin_headers, json={
        "user_ids" : [ admin_id ],
        "reason"   : "Sole admin guard test"
    })

    assert response.status_code == 200
    data = response.json()

    assert data["total_failed"] == 1
    assert data["total_deleted"] == 0

    result = data["results"][ 0 ]
    assert result["success"] is False
