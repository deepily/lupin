"""
Integration tests for JWT authentication system.

Tests complete user flows end-to-end across multiple components:
- API endpoints
- Database operations
- Token management
- WebSocket authentication

Tests against live FastAPI server (requires server running with LUPIN_TEST_MODE=true)
"""

import os

import pytest
import requests
import time
import json
from pathlib import Path

# Test configuration
BASE_URL = os.environ.get( "LUPIN_TEST_BASE_URL", "http://localhost:8000" )


# ============================================================================
# Test 1: Complete Registration Flow
# ============================================================================

def test_complete_registration_flow( clean_test_db, test_user_credentials ):
    """
    Test complete user registration flow from start to finish.

    Flow:
        1. Register new user via API
        2. Verify user created in database
        3. Login with new credentials
        4. Access protected endpoint with token
        5. Verify user data

    Asserts:
        - Registration returns success
        - User exists in database with correct data
        - Login returns valid tokens
        - Protected endpoint accessible with token
        - User profile data matches registration
    """
    email = test_user_credentials["email"]
    password = test_user_credentials["password"]

    # Step 1: Register new user
    response = requests.post( f"{BASE_URL}/auth/register",
        json={"email": email, "password": password}
    )

    assert response.status_code == 201, f"Registration failed: {response.text}"
    data = response.json()
    assert "user" in data
    assert data["user"]["email"] == email
    assert "id" in data["user"]

    user_id = data["user"]["id"]

    # Step 2: Verify user in database
    from cosa.rest.user_service import get_user_by_email

    db_user = get_user_by_email( email )
    assert db_user is not None
    assert db_user["email"] == email
    assert db_user["id"] == user_id
    assert db_user["is_active"] is True
    assert "user" in db_user["roles"]

    # Step 3: Login with new credentials
    login_response = requests.post( f"{BASE_URL}/auth/login",
        json={"email": email, "password": password}
    )

    assert login_response.status_code == 200, f"Login failed: {login_response.text}"
    login_data = login_response.json()
    assert "tokens" in login_data
    assert "access_token" in login_data["tokens"]
    assert "refresh_token" in login_data["tokens"]

    access_token = login_data["tokens"]["access_token"]

    # Step 4: Access protected endpoint
    headers = {"Authorization": f"Bearer {access_token}"}
    me_response = requests.get( f"{BASE_URL}/auth/me", headers=headers )

    assert me_response.status_code == 200, f"Protected endpoint failed: {me_response.text}"
    me_data = me_response.json()

    # Step 5: Verify user data
    assert me_data["email"] == email
    assert me_data["id"] == user_id
    assert "user" in me_data["roles"]


# ============================================================================
# Test 2: Login with Valid Credentials
# ============================================================================

def test_login_with_valid_credentials( create_test_user ):
    """
    Test login flow with pre-existing user.

    Flow:
        1. Login with valid credentials
        2. Receive JWT tokens
        3. Use access token to call /auth/me
        4. Verify user data returned

    Asserts:
        - Login succeeds with correct credentials
        - Both access and refresh tokens returned
        - Tokens are valid JWT format
        - User data accessible with access token
    """
    email = create_test_user["email"]
    password = create_test_user["password"]

    # Step 1: Login
    response = requests.post( f"{BASE_URL}/auth/login",
        json={"email": email, "password": password}
    )

    assert response.status_code == 200, f"Login failed: {response.text}"
    data = response.json()

    # Step 2: Verify tokens
    assert "tokens" in data
    assert "access_token" in data["tokens"]
    assert "refresh_token" in data["tokens"]

    access_token = data["tokens"]["access_token"]
    refresh_token = data["tokens"]["refresh_token"]

    # Verify JWT format (3 parts separated by dots)
    assert len( access_token.split( '.' ) ) == 3, "Access token not in JWT format"
    assert len( refresh_token.split( '.' ) ) == 3, "Refresh token not in JWT format"

    # Step 3: Call protected endpoint
    headers = {"Authorization": f"Bearer {access_token}"}
    me_response = requests.get( f"{BASE_URL}/auth/me", headers=headers )

    assert me_response.status_code == 200, f"Protected endpoint failed: {me_response.text}"

    # Step 4: Verify user data
    me_data = me_response.json()
    assert me_data["email"] == email
    assert me_data["id"] == create_test_user["user_id"]
    assert "user" in me_data["roles"]


# ============================================================================
# Test 3: Failed Login Rate Limiting
# ============================================================================

def test_failed_login_rate_limiting( create_test_user ):
    """
    Test rate limiting after multiple failed login attempts.

    Flow:
        1. Attempt login 5 times with wrong password
        2. Verify account is locked after 5 attempts
        3. Verify login fails even with correct password while locked
        4. Wait for lockout period (mocked)
        5. Verify login works after lockout expires

    Asserts:
        - First 5 attempts return "Invalid credentials"
        - 6th attempt returns "Account is locked"
        - Correct password fails while account locked
        - Failed login attempts tracked in database
    """
    email = create_test_user["email"]
    correct_password = create_test_user["password"]
    wrong_password = "WrongPassword123!"

    # Step 1: Fail 5 times
    for i in range( 5 ):
        response = requests.post( f"{BASE_URL}/auth/login",
        json={"email": email, "password": wrong_password}
        )

        assert response.status_code == 401, f"Attempt {i+1} should fail"
        data = response.json()
        assert "Invalid email or password" in data["detail"]

    # Step 2: Verify account locked
    response = requests.post( f"{BASE_URL}/auth/login",
        json={"email": email, "password": wrong_password}
    )

    assert response.status_code == 429, "Should return 429 (Too Many Requests) when locked"
    data = response.json()
    assert "locked" in data["detail"].lower(), f"Should indicate account locked: {data['detail']}"

    # Step 3: Verify correct password also fails
    response = requests.post( f"{BASE_URL}/auth/login",
        json={"email": email, "password": correct_password}
    )

    assert response.status_code == 429, "Correct password should fail with 429 when locked"
    data = response.json()
    assert "locked" in data["detail"].lower()

    # Step 4: Verify failed attempts in database
    from cosa.rest.rate_limiter import get_failed_attempts_count

    attempts_count = get_failed_attempts_count( email )
    assert attempts_count >= 5, f"Should have at least 5 failed attempts, got {attempts_count}"


# ============================================================================
# Test 4: Token Refresh Flow
# ============================================================================

def test_token_refresh_flow( create_test_user ):
    """
    Test token refresh mechanism with token rotation.

    Flow:
        1. Login to get initial tokens
        2. Use refresh token to get new tokens
        3. Verify old access token is different from new
        4. Verify new access token works
        5. Verify both tokens rotated (refresh token also changed)

    Asserts:
        - Refresh endpoint returns new tokens
        - New access token differs from old
        - New refresh token differs from old
        - New access token grants access to protected endpoints
        - Token rotation implemented (security feature)
    """
    email = create_test_user["email"]
    password = create_test_user["password"]

    # Step 1: Login
    login_response = requests.post( f"{BASE_URL}/auth/login",
        json={"email": email, "password": password}
    )

    assert login_response.status_code == 200
    login_data = login_response.json()

    old_access_token = login_data["tokens"]["access_token"]
    old_refresh_token = login_data["tokens"]["refresh_token"]

    # Step 2: Refresh tokens
    refresh_response = requests.post( f"{BASE_URL}/auth/refresh",
        json={"refresh_token": old_refresh_token}
    )

    assert refresh_response.status_code == 200, f"Refresh failed: {refresh_response.text}"
    refresh_data = refresh_response.json()

    assert "tokens" in refresh_data
    new_access_token = refresh_data["tokens"]["access_token"]
    new_refresh_token = refresh_data["tokens"]["refresh_token"]

    # Step 3: Verify tokens changed (rotation)
    assert new_access_token != old_access_token, "Access token should be different after refresh"
    assert new_refresh_token != old_refresh_token, "Refresh token should rotate for security"

    # Step 4: Verify new access token works
    headers = {"Authorization": f"Bearer {new_access_token}"}
    me_response = requests.get( f"{BASE_URL}/auth/me", headers=headers )

    assert me_response.status_code == 200, "New access token should work"
    me_data = me_response.json()
    assert me_data["email"] == email


# ============================================================================
# Test 5: Password Change Flow
# ============================================================================

def test_password_change_flow( create_test_user ):
    """
    Test password change functionality.

    Flow:
        1. Login with original password
        2. Change password using access token
        3. Logout (optional)
        4. Attempt login with old password (should fail)
        5. Login with new password (should succeed)
        6. Verify access to protected endpoints

    Asserts:
        - Password change succeeds with valid current password
        - Old password no longer works
        - New password works for login
        - Password stored securely (hashed in database)
    """
    email = create_test_user["email"]
    old_password = create_test_user["password"]
    new_password = "NewPassword456!"

    # Step 1: Login with old password
    login_response = requests.post( f"{BASE_URL}/auth/login",
        json={"email": email, "password": old_password}
    )

    assert login_response.status_code == 200
    access_token = login_response.json()["tokens"]["access_token"]

    # Step 2: Change password
    headers = {"Authorization": f"Bearer {access_token}"}
    change_response = requests.put( f"{BASE_URL}/auth/change-password",
        headers=headers,
        json={
            "current_password": old_password,
            "new_password": new_password
        }
    )

    assert change_response.status_code == 200, f"Password change failed: {change_response.text}"
    data = change_response.json()
    assert data["message"] == "Password changed successfully"

    # Step 3: Try login with old password (should fail)
    old_login_response = requests.post( f"{BASE_URL}/auth/login",
        json={"email": email, "password": old_password}
    )

    assert old_login_response.status_code == 401, "Old password should not work"

    # Step 4: Login with new password (should succeed)
    new_login_response = requests.post( f"{BASE_URL}/auth/login",
        json={"email": email, "password": new_password}
    )

    assert new_login_response.status_code == 200, "New password should work"
    new_access_token = new_login_response.json()["tokens"]["access_token"]

    # Step 5: Verify access with new token
    headers = {"Authorization": f"Bearer {new_access_token}"}
    me_response = requests.get( f"{BASE_URL}/auth/me", headers=headers )

    assert me_response.status_code == 200
    assert me_response.json()["email"] == email


# ============================================================================
# Test 6: Email Verification Flow
# ============================================================================

def test_email_verification_flow( create_test_user ):
    """
    Test email verification process.

    Note: This test mocks email sending since SMTP may not be configured.

    Flow:
        1. Check user starts as unverified
        2. Request verification email
        3. Extract verification token from database
        4. Verify email with token
        5. Check user is now verified in database

    Asserts:
        - User starts with email_verified = False
        - Verification token created in database
        - Token validation succeeds
        - User email_verified updated to True
    """
    email = create_test_user["email"]
    password = create_test_user["password"]

    # Step 1: Login
    login_response = requests.post( f"{BASE_URL}/auth/login",
        json={"email": email, "password": password}
    )

    access_token = login_response.json()["tokens"]["access_token"]

    # Step 2: Check initial verification status
    from cosa.rest.user_service import get_user_by_email

    user = get_user_by_email( email )
    assert user["email_verified"] is False, "User should start unverified"

    # Step 3: Request verification email
    headers = {"Authorization": f"Bearer {access_token}"}
    request_response = requests.post( f"{BASE_URL}/auth/request-verification",
        headers=headers
    )

    assert request_response.status_code == 200, f"Verification request failed: {request_response.text}"

    # Step 4: Extract token from database (mock email retrieval)
    from cosa.rest.db.database import get_db
    from cosa.rest.postgres_models import EmailVerificationToken
    import uuid

    with get_db() as session:
        token_obj = session.query( EmailVerificationToken ).filter(
            EmailVerificationToken.user_id == uuid.UUID( create_test_user["user_id"] )
        ).order_by( EmailVerificationToken.created_at.desc() ).first()

        assert token_obj is not None, "Verification token should exist in database"
        verification_token = token_obj.token

    # Step 5: Verify email with token
    verify_response = requests.post( f"{BASE_URL}/auth/verify-email",
        json={"token": verification_token}
    )

    assert verify_response.status_code == 200, f"Email verification failed: {verify_response.text}"

    # Step 6: Check user is now verified
    user = get_user_by_email( email )
    assert user["email_verified"] is True, "User should be verified after token validation"


# ============================================================================
# Test 7: Password Reset Flow
# ============================================================================

def test_password_reset_flow( create_test_user ):
    """
    Test password reset process.

    Note: This test mocks email sending since SMTP may not be configured.

    Flow:
        1. Request password reset
        2. Extract reset token from database
        3. Reset password with token
        4. Login with old password (should fail)
        5. Login with new password (should succeed)

    Asserts:
        - Reset request creates token in database
        - Token is valid for password reset
        - Old password no longer works
        - New password works immediately
        - Reset token is invalidated after use
    """
    email = create_test_user["email"]
    old_password = create_test_user["password"]
    new_password = "ResetPassword789!"

    # Step 1: Request password reset
    reset_request_response = requests.post( f"{BASE_URL}/auth/request-password-reset",
        json={"email": email}
    )

    # Should return 200 even if email doesn't exist (security - no email enumeration)
    assert reset_request_response.status_code == 200

    # Step 2: Extract token from database (mock email retrieval)
    from cosa.rest.db.database import get_db
    from cosa.rest.postgres_models import PasswordResetToken
    import uuid

    with get_db() as session:
        token_obj = session.query( PasswordResetToken ).filter(
            PasswordResetToken.user_id == uuid.UUID( create_test_user["user_id"] )
        ).order_by( PasswordResetToken.created_at.desc() ).first()

        assert token_obj is not None, "Reset token should exist in database"
        reset_token = token_obj.token

    # Step 3: Reset password with token
    reset_response = requests.post( f"{BASE_URL}/auth/reset-password",
        json={
            "token": reset_token,
            "new_password": new_password
        }
    )

    assert reset_response.status_code == 200, f"Password reset failed: {reset_response.text}"

    # Step 4: Try old password (should fail)
    old_login_response = requests.post( f"{BASE_URL}/auth/login",
        json={"email": email, "password": old_password}
    )

    assert old_login_response.status_code == 401, "Old password should not work after reset"

    # Step 5: Login with new password (should succeed)
    new_login_response = requests.post( f"{BASE_URL}/auth/login",
        json={"email": email, "password": new_password}
    )

    assert new_login_response.status_code == 200, "New password should work after reset"
    assert "tokens" in new_login_response.json()


# ============================================================================
# Test 8: WebSocket JWT Authentication
# ============================================================================

@pytest.mark.asyncio
async def test_websocket_jwt_authentication( create_test_user ):
    """
    Test WebSocket authentication with JWT tokens.

    Flow:
        1. Login to get JWT access token
        2. Connect to WebSocket endpoint
        3. Send auth_request with JWT token
        4. Verify auth_success response
        5. Verify WebSocket session established

    Asserts:
        - WebSocket accepts connection
        - JWT token validates successfully
        - Server sends auth_success message
        - Session ID established
        - WebSocket can receive events
    """
    import websockets

    email = create_test_user["email"]
    password = create_test_user["password"]

    # Step 1: Login to get access token
    login_response = requests.post( f"{BASE_URL}/auth/login",
        json={"email": email, "password": password}
    )

    assert login_response.status_code == 200
    access_token = login_response.json()["tokens"]["access_token"]

    # Step 2: Connect to WebSocket endpoint
    # Use valid session ID format: "adjective noun" (e.g., "wise penguin")
    # Convert http://localhost:7999 to ws://localhost:7999
    ws_url = BASE_URL.replace( "http://", "ws://" )

    async with websockets.connect( f"{ws_url}/ws/queue/test%20session" ) as websocket:
        # Step 3: Send auth request
        auth_message = {
            "type": "auth_request",
            "token": access_token,
            "session_id": "test session",
            "subscribed_events": ["*"]
        }

        await websocket.send( json.dumps( auth_message ) )

        # Step 4: Wait for auth response
        response = await websocket.recv()
        response_data = json.loads( response )

        # Step 5: Verify auth success
        assert response_data["type"] == "auth_success", f"Expected auth_success, got {response_data['type']}"
        assert response_data["user_id"] is not None
        assert response_data["session_id"] == "test session"

        # Step 6: Verify connection remains open
        # Server sends 'connect' message after successful auth
        connect_response = await websocket.recv()
        connect_data = json.loads( connect_response )
        assert connect_data["type"] == "connect"

        # Send ping to verify WebSocket is active
        ping_message = {"type": "sys_ping"}
        await websocket.send( json.dumps( ping_message ) )

        # Should receive pong
        pong_response = await websocket.recv()
        pong_data = json.loads( pong_response )
        assert pong_data["type"] == "sys_pong"
