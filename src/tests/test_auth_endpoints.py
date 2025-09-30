#!/usr/bin/env python3
"""
Manual test script for authentication endpoints.

Tests all auth endpoints against running FastAPI server on port 7999.
Requires server to be running: src/scripts/run-fastapi-lupin.sh
"""

import requests
import json
import sys

BASE_URL = "http://127.0.0.1:7999"
TEST_EMAIL = "test_auth_endpoints@example.com"
TEST_PASSWORD = "TestPass123!"

def print_test( test_name: str ):
    """Print test header."""
    print( f"\n{'='*60}" )
    print( f"TEST: {test_name}" )
    print( f"{'='*60}" )

def print_response( response ):
    """Print formatted response."""
    print( f"Status: {response.status_code}" )
    try:
        data = response.json()
        print( f"Response:\n{json.dumps( data, indent=2 )}" )
    except:
        print( f"Response: {response.text}" )

def test_register():
    """Test POST /auth/register"""
    print_test( "Register New User" )

    response = requests.post(
        f"{BASE_URL}/auth/register",
        json={
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD,
            "roles": ["user", "tester"]
        }
    )

    print_response( response )

    if response.status_code == 201:
        data = response.json()
        print( "\n✓ Registration successful!" )
        print( f"  User ID: {data['user']['id']}" )
        print( f"  Email: {data['user']['email']}" )
        print( f"  Roles: {data['user']['roles']}" )
        print( f"  Access Token: {data['tokens']['access_token'][:50]}..." )
        print( f"  Refresh Token: {data['tokens']['refresh_token'][:50]}..." )
        return data['tokens']
    else:
        print( "\n✗ Registration failed!" )
        return None

def test_register_duplicate():
    """Test POST /auth/register with duplicate email"""
    print_test( "Register Duplicate Email (Should Fail)" )

    response = requests.post(
        f"{BASE_URL}/auth/register",
        json={
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD
        }
    )

    print_response( response )

    if response.status_code == 400:
        print( "\n✓ Duplicate email correctly rejected!" )
        return True
    else:
        print( "\n✗ Duplicate email was accepted (should fail)!" )
        return False

def test_login():
    """Test POST /auth/login"""
    print_test( "Login with Email and Password" )

    response = requests.post(
        f"{BASE_URL}/auth/login",
        json={
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD
        }
    )

    print_response( response )

    if response.status_code == 200:
        data = response.json()
        print( "\n✓ Login successful!" )
        print( f"  User ID: {data['user']['id']}" )
        print( f"  Email: {data['user']['email']}" )
        print( f"  Access Token: {data['tokens']['access_token'][:50]}..." )
        print( f"  Refresh Token: {data['tokens']['refresh_token'][:50]}..." )
        return data['tokens']
    else:
        print( "\n✗ Login failed!" )
        return None

def test_login_wrong_password():
    """Test POST /auth/login with wrong password"""
    print_test( "Login with Wrong Password (Should Fail)" )

    response = requests.post(
        f"{BASE_URL}/auth/login",
        json={
            "email": TEST_EMAIL,
            "password": "WrongPassword123!"
        }
    )

    print_response( response )

    if response.status_code == 401:
        print( "\n✓ Wrong password correctly rejected!" )
        return True
    else:
        print( "\n✗ Wrong password was accepted (should fail)!" )
        return False

def test_me( access_token: str ):
    """Test GET /auth/me"""
    print_test( "Get Current User Info" )

    response = requests.get(
        f"{BASE_URL}/auth/me",
        headers={
            "Authorization": f"Bearer {access_token}"
        }
    )

    print_response( response )

    if response.status_code == 200:
        data = response.json()
        print( "\n✓ User info retrieved!" )
        print( f"  User ID: {data['id']}" )
        print( f"  Email: {data['email']}" )
        print( f"  Roles: {data['roles']}" )
        return True
    else:
        print( "\n✗ Failed to get user info!" )
        return False

def test_me_no_token():
    """Test GET /auth/me without token"""
    print_test( "Get Current User Without Token (Should Fail)" )

    response = requests.get( f"{BASE_URL}/auth/me" )

    print_response( response )

    if response.status_code == 401:
        print( "\n✓ Request correctly rejected (no token)!" )
        return True
    else:
        print( "\n✗ Request was accepted without token (should fail)!" )
        return False

def test_refresh( refresh_token: str ):
    """Test POST /auth/refresh"""
    print_test( "Refresh Access Token" )

    response = requests.post(
        f"{BASE_URL}/auth/refresh",
        json={
            "refresh_token": refresh_token
        }
    )

    print_response( response )

    if response.status_code == 200:
        data = response.json()
        print( "\n✓ Token refreshed successfully!" )
        print( f"  New Access Token: {data['tokens']['access_token'][:50]}..." )
        print( f"  New Refresh Token: {data['tokens']['refresh_token'][:50]}..." )
        return data['tokens']
    else:
        print( "\n✗ Token refresh failed!" )
        return None

def test_refresh_with_revoked_token( refresh_token: str ):
    """Test POST /auth/refresh with already-used token"""
    print_test( "Refresh with Revoked Token (Should Fail)" )

    response = requests.post(
        f"{BASE_URL}/auth/refresh",
        json={
            "refresh_token": refresh_token
        }
    )

    print_response( response )

    if response.status_code == 401:
        print( "\n✓ Revoked token correctly rejected!" )
        return True
    else:
        print( "\n✗ Revoked token was accepted (should fail)!" )
        return False

def test_logout( refresh_token: str ):
    """Test POST /auth/logout"""
    print_test( "Logout (Revoke Refresh Token)" )

    response = requests.post(
        f"{BASE_URL}/auth/logout",
        json={
            "refresh_token": refresh_token
        }
    )

    print_response( response )

    if response.status_code == 200:
        print( "\n✓ Logout successful!" )
        return True
    else:
        print( "\n✗ Logout failed!" )
        return False

def main():
    """Run all authentication endpoint tests."""
    print( "\n" + "="*60 )
    print( "AUTHENTICATION ENDPOINTS TEST SUITE" )
    print( "="*60 )
    print( f"Server: {BASE_URL}" )
    print( f"Test Email: {TEST_EMAIL}" )
    print( "="*60 )

    results = []

    # Test 1: Register new user
    tokens = test_register()
    results.append( ("Register", tokens is not None) )
    if not tokens:
        print( "\n✗ Cannot continue without successful registration" )
        return

    # Test 2: Try to register duplicate email
    result = test_register_duplicate()
    results.append( ("Register Duplicate", result) )

    # Test 3: Login with credentials
    tokens = test_login()
    results.append( ("Login", tokens is not None) )
    if not tokens:
        print( "\n✗ Cannot continue without successful login" )
        return

    # Test 4: Try login with wrong password
    result = test_login_wrong_password()
    results.append( ("Login Wrong Password", result) )

    # Test 5: Get current user with access token
    result = test_me( tokens['access_token'] )
    results.append( ("Get Current User", result) )

    # Test 6: Try to get user without token
    result = test_me_no_token()
    results.append( ("Get User No Token", result) )

    # Test 7: Refresh access token
    old_refresh_token = tokens['refresh_token']
    tokens = test_refresh( old_refresh_token )
    results.append( ("Refresh Token", tokens is not None) )
    if not tokens:
        print( "\n✗ Cannot continue without successful refresh" )
        return

    # Test 8: Try to use old refresh token (should fail - token rotation)
    result = test_refresh_with_revoked_token( old_refresh_token )
    results.append( ("Refresh Revoked Token", result) )

    # Test 9: Logout (revoke refresh token)
    result = test_logout( tokens['refresh_token'] )
    results.append( ("Logout", result) )

    # Print summary
    print( "\n" + "="*60 )
    print( "TEST SUMMARY" )
    print( "="*60 )

    passed = 0
    failed = 0

    for test_name, passed_test in results:
        status = "✓ PASS" if passed_test else "✗ FAIL"
        print( f"{status:8} | {test_name}" )
        if passed_test:
            passed += 1
        else:
            failed += 1

    print( "="*60 )
    print( f"Total: {passed + failed} tests" )
    print( f"Passed: {passed}" )
    print( f"Failed: {failed}" )
    print( "="*60 )

    if failed == 0:
        print( "\n✓ All authentication endpoint tests passed!" )
        return 0
    else:
        print( f"\n✗ {failed} test(s) failed" )
        return 1

if __name__ == "__main__":
    try:
        sys.exit( main() )
    except KeyboardInterrupt:
        print( "\n\nTests interrupted by user" )
        sys.exit( 1 )
    except Exception as e:
        print( f"\n\n✗ Test suite failed with error: {e}" )
        import traceback
        traceback.print_exc()
        sys.exit( 1 )