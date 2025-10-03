"""
Pytest configuration and fixtures for integration tests.

Provides test database, test client, and helper functions for authentication flow testing.
"""

import pytest
import os
import sys
from pathlib import Path

# Add project root to Python path
project_root = Path( __file__ ).parent.parent.parent
sys.path.insert( 0, str( project_root ) )

# Test configuration
TEST_DB_PATH = project_root / "tests" / "integration" / "test_auth.db"
TEST_BASE_URL = "http://localhost:7999"


@pytest.fixture( scope="session" )
def test_db_path():
    """
    Provide path to test database.

    Returns:
        Path: Path to test authentication database
    """
    return TEST_DB_PATH


@pytest.fixture( scope="function", autouse=True )
def clean_test_db():
    """
    Clean up test database before and after each test.

    This ensures tests run in isolation with a clean database state.

    Note: Integration tests use the configured auth database path.
    Make sure to backup production database before running tests!
    """
    from cosa.rest.auth_database import get_auth_db_path, init_auth_database, get_auth_db_connection

    # Get configured database path
    db_path = get_auth_db_path()

    # Remove existing database if it exists
    if db_path.exists():
        db_path.unlink()

    # Initialize fresh database with schema
    init_auth_database()

    yield

    # Cleanup after test - remove test database
    if db_path.exists():
        db_path.unlink()


@pytest.fixture( scope="function" )
def test_user_credentials():
    """
    Provide test user credentials for registration and login tests.

    Returns:
        dict: Test user email and password
    """
    return {
        "email": "integration_test@example.com",
        "password": "TestPassword123!",
        "roles": ["user"]
    }


@pytest.fixture( scope="function" )
def test_admin_credentials():
    """
    Provide test admin user credentials.

    Returns:
        dict: Test admin email and password
    """
    return {
        "email": "admin_test@example.com",
        "password": "AdminPassword123!",
        "roles": ["user", "admin"]
    }


@pytest.fixture( scope="function" )
def create_test_user( test_user_credentials ):
    """
    Create a test user in the database for login/auth tests.

    Returns:
        dict: Created user data including user_id
    """
    from cosa.rest.user_service import create_user

    success, message, user_id = create_user(
        email=test_user_credentials["email"],
        password=test_user_credentials["password"],
        roles=test_user_credentials["roles"]
    )

    if not success:
        raise Exception( f"Failed to create test user: {message}" )

    # Get full user data
    from cosa.rest.user_service import get_user_by_id
    user_data = get_user_by_id( user_id )

    return {
        **test_user_credentials,
        "user_id": user_data["id"],
        "email_verified": user_data["email_verified"]
    }


@pytest.fixture( scope="function" )
def create_test_admin( test_admin_credentials ):
    """
    Create a test admin user in the database.

    Returns:
        dict: Created admin user data including user_id
    """
    from cosa.rest.user_service import create_user

    success, message, user_id = create_user(
        email=test_admin_credentials["email"],
        password=test_admin_credentials["password"],
        roles=test_admin_credentials["roles"]
    )

    if not success:
        raise Exception( f"Failed to create test admin: {message}" )

    # Get full user data
    from cosa.rest.user_service import get_user_by_id
    user_data = get_user_by_id( user_id )

    return {
        **test_admin_credentials,
        "user_id": user_data["id"],
        "email_verified": user_data["email_verified"]
    }


@pytest.fixture( scope="function" )
def auth_headers( create_test_user ):
    """
    Create authenticated session with JWT tokens.

    Returns:
        dict: Authorization headers with valid access token
    """
    from cosa.rest.jwt_service import create_access_token

    # Create access token for test user
    access_token = create_access_token(
        user_id=create_test_user["user_id"],
        email=create_test_user["email"],
        roles=create_test_user.get( "roles", ["user"] )
    )

    return {
        "Authorization": f"Bearer {access_token}"
    }


@pytest.fixture( scope="session" )
def base_url():
    """
    Provide base URL for API requests.

    Returns:
        str: Base URL for FastAPI server
    """
    return TEST_BASE_URL


# Helper functions for integration tests

def make_request( method, endpoint, base_url=TEST_BASE_URL, headers=None, json=None ):
    """
    Make HTTP request to API endpoint.

    Args:
        method: HTTP method (GET, POST, PUT, DELETE)
        endpoint: API endpoint path (e.g., '/auth/login')
        base_url: Base URL for server
        headers: Optional request headers
        json: Optional JSON request body

    Returns:
        Response object
    """
    import requests

    url = f"{base_url}{endpoint}"

    if method.upper() == "GET":
        return requests.get( url, headers=headers )
    elif method.upper() == "POST":
        return requests.post( url, headers=headers, json=json )
    elif method.upper() == "PUT":
        return requests.put( url, headers=headers, json=json )
    elif method.upper() == "DELETE":
        return requests.delete( url, headers=headers, json=json )
    else:
        raise ValueError( f"Unsupported HTTP method: {method}" )


def register_user( email, password, base_url=TEST_BASE_URL ):
    """
    Helper to register a new user via API.

    Args:
        email: User email
        password: User password
        base_url: Base URL for server

    Returns:
        Response object
    """
    import requests

    return requests.post(
        f"{base_url}/auth/register",
        json={"email": email, "password": password}
    )


def login_user( email, password, base_url=TEST_BASE_URL ):
    """
    Helper to login user and get tokens.

    Args:
        email: User email
        password: User password
        base_url: Base URL for server

    Returns:
        Response object with tokens
    """
    import requests

    return requests.post(
        f"{base_url}/auth/login",
        json={"email": email, "password": password}
    )


def get_auth_header( access_token ):
    """
    Create Authorization header dict from access token.

    Args:
        access_token: JWT access token

    Returns:
        dict: Headers with Authorization
    """
    return {"Authorization": f"Bearer {access_token}"}
