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

# Set GCS environment variables for LanceDB GCS integration tests
os.environ["GOOGLE_CLOUD_PROJECT"] = "hello-world-foo-423219"
os.environ["GOOGLE_CLOUD_LOCATION"] = "us-central1"

import pytest
import requests
from pathlib import Path

# Python path configured by src/tests/conftest.py

# Test server configuration — defaults to the dedicated test container (port 8000).
# Override via LUPIN_TEST_BASE_URL env var for custom setups or Docker-internal routing.
BASE_URL = os.environ.get( "LUPIN_TEST_BASE_URL", "http://localhost:8000" )


@pytest.fixture( scope="session", autouse=True )
def verify_test_environment():
    """
    One-time validation that server is running with Testing configuration.

    Runs once at start of entire test session (scope="session").
    Checks /api/server-info to confirm the hot-swap to Testing config
    has taken effect (database points to lupin_db_test).

    Requires:
        - Server running on port 7999
        - Server hot-swapped to [Lupin: Testing] via /api/init

    Ensures:
        - Server is accessible and responsive
        - Config block is [Lupin: Testing]
        - Database URL contains lupin_db_test
        - Aborts entire test suite if environment invalid

    Raises:
        - RuntimeError: Server not accessible or misconfigured
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

        # Verify server is in Testing mode via /api/server-info
        info_response = requests.get( f"{BASE_URL}/api/server-info", timeout=2 )
        if info_response.status_code == 200:
            info = info_response.json()
            config_block = info.get( "config_block_id", "unknown" )
            db_url       = info.get( "database_url", "unknown" )

            print( f"✓ Config block: {config_block}" )
            print( f"✓ Database URL: {db_url}" )

            if "lupin_db_test" not in db_url:
                raise RuntimeError(
                    f"Server database is NOT lupin_db_test!\n"
                    f"  Current: {db_url}\n\n"
                    f"Run integration tests via:\n"
                    f"  ./src/tests/run-integration-tests.sh -v"
                )
        else:
            print( f"⚠ /api/server-info returned {info_response.status_code} — skipping config validation" )

        print( "\nUse automated test runner:" )
        print( "  ./src/tests/run-integration-tests.sh -v" )
        print( "="*60 + "\n" )

    except requests.exceptions.ConnectionError:
        raise RuntimeError(
            f"\n{'='*60}\n"
            f"ERROR: Cannot connect to test server at {BASE_URL}\n\n"
            f"Please start the dev server, then run:\n"
            f"  ./src/tests/run-integration-tests.sh -v\n"
            f"{'='*60}\n"
        )


@pytest.fixture( scope="function" )
def clean_test_db():
    """
    Clean PostgreSQL test database before each test.

    Uses hot-swap mechanism: the integration test runner calls /api/init
    to swap the running dev server to [Lupin: Testing] config block,
    which points to lupin_db_test.

    Safety Mechanism:
        - Asserts engine.url contains 'lupin_db_test' before any destructive ops
        - Verifies users table is empty after schema reset
        - DROP/CREATE provides complete isolation between tests

    Requires:
        - PostgreSQL Docker container running (lupin-postgres)
        - Test server running on port 8000 with [Lupin: Testing] config (lupin_db_test)

    Ensures:
        - Fresh database schema before each test
        - Complete isolation between tests
        - Tests never affect development database
    """
    # Re-import to get the current (possibly hot-swapped) engine
    from cosa.rest.db import database as db_module
    from cosa.rest.postgres_models import Base
    from sqlalchemy import text

    engine = db_module.engine
    db_url = str( engine.url )
    assert "lupin_db_test" in db_url, \
        f"SAFETY: clean_test_db must only run against lupin_db_test, got: {db_url}"

    # Drop all tables (complete cleanup)
    Base.metadata.drop_all( bind=engine )

    # Recreate all tables with fresh schema
    Base.metadata.create_all( bind=engine )

    # Verify the reset worked
    with engine.connect() as conn:
        count = conn.execute( text( "SELECT count(*) FROM users" ) ).scalar()
        assert count == 0, f"SAFETY: users table not empty after clean ({count} rows)"

    yield


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
    from cosa.rest.db.database import get_db
    from cosa.rest.db.repositories import UserRepository

    with get_db() as session:
        user_repo = UserRepository( session )
        user = user_repo.get_by_email( email )
        if user:
            user.roles = ["user", "admin"]
            # session.commit() happens automatically on context exit

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
def ws_connection( create_test_user ):
    """
    Establish a WebSocket connection for the test user so
    is_user_connected() returns True during notification tests.

    Requires:
        - create_test_user fixture (provides access_token)
        - FastAPI server running on port 7999

    Ensures:
        - WebSocket connected and authenticated before test runs
        - Connection closed after test completes
        - User appears "online" to notification router
    """
    import threading
    import asyncio
    import json
    import urllib.parse
    import websockets

    token      = create_test_user[ "access_token" ]
    session_id = "test penguin"
    encoded    = urllib.parse.quote( session_id )
    uri        = f"ws://{BASE_URL.replace( 'http://', '' )}/ws/queue/{encoded}"

    connected_event = threading.Event()
    stop_event      = threading.Event()
    ws_error        = {}

    def run_ws():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop( loop )

        async def connect_and_hold():
            try:
                async with websockets.connect( uri ) as ws:
                    auth_msg = {
                        "type"              : "auth_request",
                        "token"             : f"Bearer {token}",
                        "subscribed_events" : [
                            "auth_success", "auth_error",
                            "notification_new", "notification_response_required"
                        ]
                    }
                    await ws.send( json.dumps( auth_msg ) )
                    response = await asyncio.wait_for( ws.recv(), timeout=5.0 )
                    data = json.loads( response )

                    if data.get( "type" ) != "auth_success":
                        ws_error[ "msg" ] = f"WebSocket auth failed: {data}"
                        connected_event.set()
                        return

                    connected_event.set()

                    # Hold connection open until test signals stop
                    while not stop_event.is_set():
                        try:
                            await asyncio.wait_for( ws.recv(), timeout=0.5 )
                        except asyncio.TimeoutError:
                            pass
            except Exception as e:
                ws_error[ "msg" ] = str( e )
                connected_event.set()

        loop.run_until_complete( connect_and_hold() )
        loop.close()

    thread = threading.Thread( target=run_ws, daemon=True )
    thread.start()

    connected_event.wait( timeout=10.0 )
    if ws_error:
        pytest.fail( f"WebSocket connection failed: {ws_error[ 'msg' ]}" )

    yield create_test_user

    stop_event.set()
    thread.join( timeout=5.0 )


@pytest.fixture( scope="function" )
def seeded_job_history( create_test_user ):
    """
    Seed 5 standard job_history rows owned by the test user.

    Requires:
        - create_test_user fixture (chains through clean_test_db)

    Ensures:
        - 5 rows inserted: 2 completed, 1 failed, 1 interrupted, 1 pending
        - Returns dict with 'records' list and 'user' dict
    """
    from tests.helpers.job_history_seed import seed_standard_job_set
    records = seed_standard_job_set(
        user_id    = create_test_user[ "user_id" ],
        user_email = create_test_user[ "email" ]
    )
    return { "records": records, "user": create_test_user }


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


# GCS Credential Validation Fixture

@pytest.fixture( scope="session" )
def gcs_credentials_available():
    """
    Session-scoped fixture that validates GCS credentials once.

    Validates Google Cloud Storage credentials at test session start.
    If credentials are missing, expired, or invalid, all GCS-dependent
    tests are skipped gracefully with clear remediation instructions.

    This prevents cryptic test failures when developers haven't authenticated
    or when CI/CD environments don't have GCS configured.

    Scope:
        session - Validates once per test run (not per test)

    Requires:
        - google-auth library (installed as LanceDB dependency)
        - Either:
          - GOOGLE_APPLICATION_CREDENTIALS env var set, OR
          - gcloud auth application-default login completed

    Ensures:
        - Returns True if credentials valid
        - Raises pytest.skip() if credentials invalid/missing/expired
        - Skip message includes clear remediation steps

    Usage:
        Inject into GCS-dependent fixtures:

        @pytest.fixture
        def gcs_manager(gcs_credentials_available):
            # gcs_credentials_available validates before this runs
            manager = LanceDBSolutionManager( gcs_config )
            manager.initialize()  # Won't fail due to auth
            return manager

    Returns:
        bool: True if credentials valid (otherwise skips)

    Raises:
        pytest.skip: If credentials invalid, with detailed message
    """
    from .gcs_utils import check_gcs_credentials

    is_valid, message = check_gcs_credentials()

    if not is_valid:
        pytest.skip(
            f"\n{'='*70}\n"
            f"GCS Integration Tests Skipped\n"
            f"{'='*70}\n\n"
            f"{message}\n\n"
            f"To enable GCS tests:\n"
            f"  1. gcloud auth application-default login\n"
            f"  2. Re-run tests\n"
            f"\n"
            f"Note: All non-GCS tests will still run normally.\n"
            f"{'='*70}\n"
        )

    # Credentials valid - print success message
    print( f"\n✓ GCS credentials validated: {message}" )
    return True
