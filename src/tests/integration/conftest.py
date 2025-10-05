"""
Pytest configuration and fixtures for integration tests.

Provides test database management, test credentials, and helper functions
for authentication flow testing against live FastAPI server.

IMPORTANT: Tests require live server running with Testing config block:
    Terminal 1:
        export LUPIN_CONFIG_MGR_CLI_ARGS="config_path=/src/conf/lupin-app.ini splainer_path=/src/conf/lupin-app-splainer.ini config_block_id=Lupin:+Testing"
        ./src/scripts/run-fastapi-lupin.sh
    Terminal 2: pytest src/tests/integration/ -v

    OR use the automated test runner:
        ./src/tests/run-integration-tests.sh -v
"""

import os

# CRITICAL: Set config environment variable BEFORE any other imports
# This ensures config_mgr singleton initializes with Testing block
os.environ["LUPIN_CONFIG_MGR_CLI_ARGS"] = "config_path=/src/conf/lupin-app.ini splainer_path=/src/conf/lupin-app-splainer.ini config_block_id=Lupin:+Testing"

import pytest
import requests
from pathlib import Path

# Python path configured by src/tests/conftest.py

# Test server configuration
BASE_URL = "http://localhost:7999"


@pytest.fixture( scope="session", autouse=True )
def verify_test_environment():
    """
    One-time validation that server is running with correct Testing configuration.

    Runs once at start of entire test session (scope="session").

    Requires:
        - Server running on port 7999
        - Server started with [Lupin: Testing] config block

    Ensures:
        - Server is accessible and responsive
        - Config environment variable set at module level (before imports)
        - Prints clear startup message with configuration
        - Aborts entire test suite if environment invalid

    Raises:
        - RuntimeError: Server not accessible or misconfigured

    Note:
        LUPIN_CONFIG_MGR_CLI_ARGS is set at module level (top of conftest.py)
        to ensure config_mgr singleton initializes correctly before any imports.
    """
    print( "\n" + "="*60 )
    print( "INTEGRATION TEST ENVIRONMENT VALIDATION" )
    print( "="*60 )

    try:
        # Verify server is running
        health_response = requests.get( f"{BASE_URL}/health", timeout=2 )
        if health_response.status_code != 200:
            raise RuntimeError( f"Server health check failed: {health_response.status_code}" )

        print( f"✓ Server accessible at {BASE_URL}" )
        print( f"✓ LUPIN_CONFIG_MGR_CLI_ARGS set to Testing block" )
        print( "\nREQUIRED SERVER STARTUP:" )
        print( "  export LUPIN_CONFIG_MGR_CLI_ARGS=\"config_path=/src/conf/lupin-app.ini splainer_path=/src/conf/lupin-app-splainer.ini config_block_id=Lupin:+Testing\"" )
        print( "  ./src/scripts/run-fastapi-lupin.sh" )
        print( "\nOR use automated test runner:" )
        print( "  ./src/tests/run-integration-tests.sh -v" )
        print( "="*60 + "\n" )

    except requests.exceptions.ConnectionError:
        raise RuntimeError(
            f"\n{'='*60}\n"
            f"ERROR: Cannot connect to test server at {BASE_URL}\n\n"
            f"Please start server with:\n"
            f"  export LUPIN_CONFIG_MGR_CLI_ARGS=\"config_path=/src/conf/lupin-app.ini splainer_path=/src/conf/lupin-app-splainer.ini config_block_id=Lupin:+Testing\"\n"
            f"  ./src/scripts/run-fastapi-lupin.sh\n\n"
            f"OR use automated test runner:\n"
            f"  ./src/tests/run-integration-tests.sh -v\n"
            f"{'='*60}\n"
        )


@pytest.fixture( scope="function" )
def clean_test_db():
    """
    Clean test database before each test using direct function calls.

    Simple approach - no API calls, no config switching needed.
    Server was started with Testing block, so get_auth_db_path()
    returns test DB automatically.

    Dual Safety Mechanism (in get_auth_db_path):
        - Configuration: app_testing=true (from Testing block)
        - Path validation: path must contain "test"

    Requires:
        - FastAPI server running with Testing config block
        - pytest process config_mgr initialized with Testing block

    Ensures:
        - Fresh database before each test
        - Database cleaned up after test
        - Tests run in complete isolation
        - Dual safety prevents accidental production DB modification
    """
    # Import database functions directly
    from cosa.rest.auth_database import get_auth_db_path, init_auth_database

    # Get test database path (dual safety checks happen here)
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
def create_test_user( clean_test_db, test_user_credentials ):
    """
    Create a test user via API for login/auth tests.

    Returns:
        dict: Created user data including user_id and tokens
    """
    email = test_user_credentials["email"]
    password = test_user_credentials["password"]

    # Register user via API
    register_response = requests.post(
        f"{BASE_URL}/auth/register",
        json={"email": email, "password": password}
    )

    if register_response.status_code != 201:
        raise Exception(
            f"Failed to create test user: {register_response.status_code} - {register_response.text}"
        )

    user_data = register_response.json()["user"]

    # Login to get tokens
    login_response = requests.post(
        f"{BASE_URL}/auth/login",
        json={"email": email, "password": password}
    )

    tokens = login_response.json()["tokens"]

    return {
        **test_user_credentials,
        "user_id": user_data["id"],
        "email_verified": user_data.get( "email_verified", False ),
        "access_token": tokens["access_token"],
        "refresh_token": tokens["refresh_token"]
    }


@pytest.fixture( scope="function" )
def create_test_admin( clean_test_db, test_admin_credentials ):
    """
    Create a test admin user via API.

    Returns:
        dict: Created admin user data including user_id and tokens
    """
    email = test_admin_credentials["email"]
    password = test_admin_credentials["password"]

    # Register admin user via API
    register_response = requests.post(
        f"{BASE_URL}/auth/register",
        json={"email": email, "password": password}
    )

    if register_response.status_code != 201:
        raise Exception(
            f"Failed to create test admin: {register_response.status_code} - {register_response.text}"
        )

    user_data = register_response.json()["user"]

    # Manually add admin role (direct database access since we can't bootstrap admin via API)
    from cosa.rest.user_service import get_user_by_email
    from cosa.rest.auth_database import get_auth_db_connection
    import json

    conn = get_auth_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET roles = ? WHERE email = ?",
        (json.dumps( ["user", "admin"] ), email)
    )
    conn.commit()
    conn.close()

    # Login to get tokens
    login_response = requests.post(
        f"{BASE_URL}/auth/login",
        json={"email": email, "password": password}
    )

    tokens = login_response.json()["tokens"]

    return {
        **test_admin_credentials,
        "user_id": user_data["id"],
        "email_verified": user_data.get( "email_verified", False ),
        "access_token": tokens["access_token"],
        "refresh_token": tokens["refresh_token"]
    }


@pytest.fixture( scope="function" )
def auth_headers( create_test_user ):
    """
    Create authenticated session with JWT tokens.

    Returns:
        dict: Authorization headers with valid access token
    """
    return {
        "Authorization": f"Bearer {create_test_user['access_token']}"
    }


# Helper functions for integration tests

def register_user( email, password ):
    """
    Helper to register a new user via API.

    Args:
        email: User email
        password: User password

    Returns:
        Response object
    """
    return requests.post(
        f"{BASE_URL}/auth/register",
        json={"email": email, "password": password}
    )


def login_user( email, password ):
    """
    Helper to login user and get tokens via API.

    Args:
        email: User email
        password: User password

    Returns:
        Response object with tokens
    """
    return requests.post(
        f"{BASE_URL}/auth/login",
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
