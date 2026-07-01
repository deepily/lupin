"""
Pytest configuration and fixtures for Playwright E2E UI tests.

Provides browser fixtures, authentication helpers, and page navigation
utilities for end-to-end browser testing against the live FastAPI server.

IMPORTANT: Tests require live server running with Testing config block.
Use the automated runner:
    ./src/scripts/run-e2e-ui-tests.sh -v

Or manually:
    Terminal 1: ./src/scripts/run-fastapi-lupin.sh
    Terminal 2: ./src/tests/run-integration-tests.sh  (to hot-swap to Testing)
    Terminal 3: pytest src/tests/e2e_ui/ -v
"""

import os

# CRITICAL: Set config environment variable BEFORE any other imports
# This ensures config_mgr singleton initializes with Testing block
os.environ[ "LUPIN_CONFIG_MGR_CLI_ARGS" ] = "config_path=/src/conf/lupin-app.ini splainer_path=/src/conf/lupin-app-splainer.ini config_block_id=Lupin:+Testing"

import pytest
import requests

# Test server configuration — defaults to the dedicated test container (port 8000).
# Override via LUPIN_TEST_BASE_URL env var for custom setups or Docker-internal routing.
BASE_URL = os.environ.get( "LUPIN_TEST_BASE_URL", "http://localhost:8000" )

# Height-tolerant snapshot comparison core (bug 660d02b4). Imported via a
# path-guard so the pure helper resolves regardless of pytest import mode.
import sys as _sys_vt
_THIS_DIR = os.path.dirname( os.path.abspath( __file__ ) )
if _THIS_DIR not in _sys_vt.path:
    _sys_vt.path.insert( 0, _THIS_DIR )
from visual_height_tolerance import compare_pngs_height_tolerant


# ---------------------------------------------------------------------------
# Deterministic Font Rendering for Visual Regression
# ---------------------------------------------------------------------------

@pytest.fixture( scope="session" )
def browser_type_launch_args( browser_type_launch_args ):
    """
    Override Chromium launch args to stabilize font rendering across runs.

    Headless Chromium's default font rendering uses LCD subpixel anti-aliasing
    and platform-dependent font hinting, producing slightly different pixel
    values depending on session context, cache state, and fontconfig config.
    These flags disable the non-deterministic rendering paths so visual
    regression baselines remain stable across cold/warm, isolated/full-suite,
    and host/container execution modes.

    Requires:
        - browser_type_launch_args is the default pytest-playwright fixture

    Ensures:
        - Font hinting disabled (no rasterization variation between sessions)
        - LCD subpixel rendering disabled (eliminates text ghosting in diffs)
        - Color profile locked to sRGB (standardizes color pipeline)
        - Device scale factor locked to 1 (prevents DPI-dependent rendering)

    See src/rnd/v0.1.6/2026.04.10-visual-regression-cold-warm-drift.md
    """
    return {
        **browser_type_launch_args,
        "args": [
            *browser_type_launch_args.get( "args", [] ),
            "--font-render-hinting=none",
            "--disable-lcd-text",
            "--force-color-profile=srgb",
            "--force-device-scale-factor=1",
        ],
    }


# ---------------------------------------------------------------------------
# Deterministic Viewport for Visual Regression  (bug 99326963)
# ---------------------------------------------------------------------------

@pytest.fixture( scope="session" )
def browser_context_args( browser_context_args ):
    """
    Pin the Playwright viewport to a FIXED size for every e2e_ui context.

    Root cause of bug 99326963 (mux visual-e2e render non-determinism):
    pytest-playwright leaves `viewport` UNSET on `browser.new_context()`, so
    Playwright falls back to Chromium's built-in default. That fallback is an
    ENVIRONMENT-dependent value — it can differ between pytest-playwright
    versions, host vs container, and headless vs headed — so a visual baseline
    captured in one environment can render at a DIFFERENT width than a COMPARE
    run in another. Element screenshots inherit the context width, so the whole
    image dimension flips (observed: 1280-wide baselines vs 960-wide recaptures)
    and pixelmatch fails on a size mismatch that NO rebaseline can reconcile.

    Pinning the viewport here makes EVERY capture and EVERY compare use
    byte-identical context dimensions, so `--update-snapshots` and a plain
    COMPARE run can never diverge on size. The width (1280) matches the
    multiplexer's intended layout target (the horizontal-mode toggle hint reads
    "Best at viewports >= 1200px wide"); height (720) is the standard 16:9 pair.
    Element screenshots taller than 720 still capture in full (Playwright scrolls
    the element), so the height pin does not clip tall panes — only the WIDTH is
    load-bearing for the size-mismatch class this fixes.

    Requires:
        - browser_context_args is the default pytest-playwright fixture

    Ensures:
        - Every browser context is created with viewport 1280x720
        - Capture and compare runs share identical context dimensions

    See bug 99326963 + src/rnd/v0.1.6/2026.04.10-visual-regression-cold-warm-drift.md
    (sibling determinism fixture `browser_type_launch_args` above).
    """
    return {
        **browser_context_args,
        "viewport": { "width": 1280, "height": 720 },
    }


# ---------------------------------------------------------------------------
# Height-tolerant snapshot assertion  (bug 660d02b4)
# ---------------------------------------------------------------------------

@pytest.fixture
def assert_snapshot_height_tolerant( pytestconfig, request ):
    """
    A snapshot assertion that tolerates a bounded HEIGHT-only delta.

    Straggler bug 660d02b4: `test_task_editing_controls_visual` renders the
    task-list card at 960x169 on `--update-snapshots` but 960x170 on a plain
    COMPARE — a benign sub-pixel row-height rounding that flips run-to-run in the
    SAME container. The stock `assert_snapshot` is zero-tolerance on dimensions
    (it raises `ValueError` the instant the sizes differ), so no rebaseline can
    reconcile the flap. This fixture forgives ONLY a benign bottom-edge ±N px
    (default 1) via `compare_pngs_height_tolerant`, while staying strict on
    width, on pixels within the overlapping region, and on the size of the delta
    — it can never green a genuine regression (a content SHIFT still fails).

    Requires:
        - the pytest-playwright-visual-snapshot ini keys are set
          (`playwright_visual_snapshots_path`, `..._threshold`,
          `..._failures_path`) — the same config the stock fixture reads
        - the passed object is a Playwright Locator/Page (screenshotted here) or
          raw PNG bytes

    Ensures:
        - `--update-snapshots` writes the capture as the baseline (then fails the
          test with a "review" note, mirroring the stock fixture)
        - a missing baseline is created (then flagged for review)
        - otherwise the capture is compared height-tolerantly; a mismatch calls
          `pytest.fail` and saves actual/expected artifacts under the failures dir
    """
    from pathlib import Path as _Path
    from playwright.sync_api import Locator as _Locator, Page as _Page

    root_dir       = _Path( pytestconfig.rootdir )
    snapshots_path = root_dir / pytestconfig.getini( "playwright_visual_snapshots_path" )
    failures_path  = root_dir / pytestconfig.getini( "playwright_visual_snapshot_failures_path" )
    threshold      = float( pytestconfig.getini( "playwright_visual_snapshot_threshold" ) )
    update         = bool( request.config.getoption( "--update-snapshots" ) )

    test_file_stem = _Path( request.node.fspath ).stem
    test_name      = request.node.name.split( "[", 1 )[ 0 ]

    def _assert( locator_or_bytes, *, name, max_height_delta=1 ):
        if isinstance( locator_or_bytes, ( _Locator, _Page ) ):
            img = locator_or_bytes.screenshot( animations="disabled", type="png" )
        else:
            img = locator_or_bytes

        snapshot_dir  = snapshots_path / test_file_stem / test_name
        snapshot_dir.mkdir( parents=True, exist_ok=True )
        baseline_file = snapshot_dir / name

        if update or not baseline_file.exists():
            baseline_file.write_bytes( img )
            verb = "updated" if update else "created (new)"
            pytest.fail( f"[height-tolerant-snapshot] Snapshot {verb}; please review. {baseline_file}" )

        result = compare_pngs_height_tolerant(
            img, baseline_file.read_bytes(),
            threshold=threshold, max_height_delta=max_height_delta,
        )
        if result.matched:
            return

        # Save artifacts for triage (parity with the stock fixture's layout).
        fail_dir = failures_path / test_file_stem / test_name
        fail_dir.mkdir( parents=True, exist_ok=True )
        ( fail_dir / f"actual_{name}" ).write_bytes( img )
        ( fail_dir / f"expected_{name}" ).write_bytes( baseline_file.read_bytes() )
        pytest.fail( f"[height-tolerant-snapshot] Snapshots DO NOT match! {name} — {result.reason}" )

    return _assert


# ---------------------------------------------------------------------------
# Test ordering — force visual regression to run FIRST
# ---------------------------------------------------------------------------

def pytest_collection_modifyitems( config, items ):
    """
    Reorder collected tests so visual regression runs before everything else.

    Visual regression tests compare screenshots against pixel baselines captured
    by pytest-playwright-visual-snapshot. Chromium's font/render cache warms up
    over the course of test execution, and anti-aliased text renders with
    slightly different subpixel values in cold vs warm Chromium state. Baselines
    are captured in the cold state (during isolated -k visual runs), so running
    visual tests LAST in the suite produces subpixel drift failures even when
    no real regression exists.

    Forcing visual regression to run FIRST keeps the cache state consistent
    with baseline capture — matching the pixel-identical conditions of a cold
    Chromium start.

    See src/rnd/v0.1.6/2026.04.10-visual-regression-cold-warm-drift.md for
    the full analysis.
    """
    visual = [ i for i in items if "test_visual_regression" in str( i.fspath ) ]
    other  = [ i for i in items if "test_visual_regression" not in str( i.fspath ) ]
    items[ : ] = visual + other


# ---------------------------------------------------------------------------
# Environment Validation
# ---------------------------------------------------------------------------

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
    print( "\n" + "=" * 60 )
    print( "E2E UI TEST ENVIRONMENT VALIDATION" )
    print( "=" * 60 )

    try:
        health_response = requests.get( f"{BASE_URL}/health", timeout=5 )
        if health_response.status_code != 200:
            raise RuntimeError( f"Server health check failed: {health_response.status_code}" )

        print( f"✓ Server accessible at {BASE_URL}" )

        info_response = requests.get( f"{BASE_URL}/api/server-info", timeout=5 )
        if info_response.status_code == 200:
            info         = info_response.json()
            config_block = info.get( "config_block_id", "unknown" )
            db_url       = info.get( "database_url", "unknown" )

            print( f"✓ Config block: {config_block}" )
            print( f"✓ Database URL: {db_url}" )

            if "lupin_db_test" not in db_url:
                raise RuntimeError(
                    f"Server database is NOT lupin_db_test!\n"
                    f"  Current: {db_url}\n\n"
                    f"Run E2E UI tests via:\n"
                    f"  ./src/scripts/run-e2e-ui-tests.sh -v"
                )
        else:
            print( f"⚠ /api/server-info returned {info_response.status_code} — skipping config validation" )

        print( "=" * 60 + "\n" )

    except requests.exceptions.ConnectionError:
        raise RuntimeError(
            f"\n{'=' * 60}\n"
            f"ERROR: Cannot connect to test server at {BASE_URL}\n\n"
            f"Run E2E UI tests via:\n"
            f"  ./src/scripts/run-e2e-ui-tests.sh -v\n"
            f"{'=' * 60}\n"
        )


# ---------------------------------------------------------------------------
# Database Cleanup
# ---------------------------------------------------------------------------

@pytest.fixture( scope="function" )
def clean_test_db():
    """
    Clean PostgreSQL test database before each test.

    Reuses the same pattern as integration tests: drop all tables,
    recreate schema, verify empty state.

    Requires:
        - Server hot-swapped to Testing config (lupin_db_test)

    Ensures:
        - Fresh database schema before each test
        - Complete isolation between tests
        - Tests never affect development database
    """
    from cosa.rest.db import database as db_module
    from cosa.rest.postgres_models import Base
    from sqlalchemy import text

    engine = db_module.engine
    db_url = str( engine.url )
    assert "lupin_db_test" in db_url, \
        f"SAFETY: clean_test_db must only run against lupin_db_test, got: {db_url}"

    import sys as _sys, pathlib as _pathlib, cosa.utils.util as _cu
    _scripts = _pathlib.Path( _cu.get_project_root() ) / "src" / "scripts"
    if str( _scripts ) not in _sys.path:
        _sys.path.insert( 0, str( _scripts ) )
    from seed_test_companions import COMPANION_EMAILS

    # Row-level DELETE: wipe test-generated rows, companions survive via is_protected
    with engine.begin() as conn:
        conn.execute( text( "DELETE FROM users WHERE NOT is_protected" ) )
        conn.execute( text(
            "TRUNCATE TABLE auth_audit_log, failed_login_attempts, "
            "job_history, proxy_decisions, trust_states"
        ) )

    with engine.connect() as conn:
        count    = conn.execute( text( "SELECT count(*) FROM users WHERE is_protected" ) ).scalar()
        expected = len( COMPANION_EMAILS )
        assert count == expected, (
            f"SAFETY: expected {expected} protected companions after teardown, got {count}"
        )

    yield


@pytest.fixture( scope="session", autouse=True )
def restore_companions_after_suite():
    """
    Belt-and-suspenders: ensure companions are present after the E2E suite exits.

    With is_protected teardown, companions survive every clean_test_db call so
    this fixture is now a lightweight safety net rather than a full DROP+RECREATE.
    seed_if_missing() is idempotent — it's a no-op if all 5 are already present.
    """
    yield

    import os as _os
    _os.environ.setdefault( "DB_HOST", "localhost" )

    import sys as _sys, pathlib as _pathlib, cosa.utils.util as _cu
    _scripts = _pathlib.Path( _cu.get_project_root() ) / "src" / "scripts"
    if str( _scripts ) not in _sys.path:
        _sys.path.insert( 0, str( _scripts ) )

    from seed_test_companions import seed_if_missing
    seed_if_missing()


# ---------------------------------------------------------------------------
# Test Credentials
# ---------------------------------------------------------------------------

@pytest.fixture( scope="function" )
def test_user_credentials():
    """
    Provide test user credentials for E2E browser tests.

    Returns:
        dict: Test user email, password, and roles
    """
    return {
        "email"    : "e2e_test@example.com",
        "password" : "TestPassword123!",
        "roles"    : [ "user" ]
    }


@pytest.fixture( scope="function" )
def test_admin_credentials():
    """
    Provide test admin user credentials for E2E browser tests.

    Returns:
        dict: Test admin email, password, and roles
    """
    return {
        "email"    : "e2e_admin@example.com",
        "password" : "AdminPassword123!",
        "roles"    : [ "user", "admin" ]
    }


# ---------------------------------------------------------------------------
# Page URL Registry
# ---------------------------------------------------------------------------

PAGE_URLS = {
    "login"           : "/app/auth/login",
    "register"        : "/app/auth/register",
    "change-password" : "/app/auth/change-password",
    "profile"         : "/app/auth/profile",
    "landing"         : "/app",
    "notifications"   : "/app/notifications",
    "admin-dashboard" : "/app/admin",
    "admin-snapshots" : "/app/admin/snapshots",
    "admin-users"     : "/app/admin/users",
    "admin-ratify"    : "/app/admin/proxy-ratify",
    "admin-trust"     : "/app/admin/proxy-dashboard",
    "dev-tools"       : "/app/admin/dev-tools",
}

# Pages accessible without authentication
PUBLIC_PAGES = [ "login", "register" ]

# Pages requiring a logged-in user
AUTH_PAGES = [ "change-password", "profile", "notifications" ]

# Pages that show different content when logged in but don't require auth
HYBRID_PAGES = [ "landing" ]

# Pages requiring admin role
ADMIN_PAGES = [ "admin-dashboard", "admin-snapshots", "admin-users", "admin-ratify", "admin-trust", "dev-tools" ]


# ---------------------------------------------------------------------------
# Browser Auth Helpers
# ---------------------------------------------------------------------------

def fill_login_form( page, email, password ):
    """
    Fill and submit the login form via browser.

    Requires:
        - page is navigated to /app/auth/login
        - email and password are non-empty strings

    Ensures:
        - Login form fields are filled and submitted
    """
    page.get_by_test_id( "login-email-input" ).fill( email )
    page.get_by_test_id( "login-password-input" ).fill( password )
    page.get_by_test_id( "login-submit-btn" ).click()


def fill_register_form( page, email, password ):
    """
    Fill and submit the registration form via browser.

    Requires:
        - page is navigated to /app/auth/register
        - email and password are non-empty strings

    Ensures:
        - Registration form fields are filled and submitted
    """
    page.get_by_test_id( "register-email-input" ).fill( email )
    page.get_by_test_id( "register-password-input" ).fill( password )
    page.get_by_test_id( "register-confirm-password-input" ).fill( password )
    page.get_by_test_id( "register-submit-btn" ).click()


def assert_error_message( page, expected_text ):
    """
    Assert that an error message is visible and contains expected text.

    Requires:
        - page has a visible element with data-testid ending in '-error-message'
        - expected_text is a non-empty string

    Ensures:
        - Error message element is visible
        - Error message contains expected_text (case-insensitive)
    """
    error = page.locator( "[data-testid$='-error-message']" ).first
    error.wait_for( state="visible", timeout=5000 )
    assert expected_text.lower() in error.text_content().lower()


def assert_success_message( page, expected_text ):
    """
    Assert that a success message is visible and contains expected text.

    Requires:
        - page has a visible element with data-testid ending in '-success-message'
        - expected_text is a non-empty string

    Ensures:
        - Success message element is visible
        - Success message contains expected_text (case-insensitive)
    """
    success = page.locator( "[data-testid$='-success-message']" ).first
    success.wait_for( state="visible", timeout=5000 )
    assert expected_text.lower() in success.text_content().lower()


# ---------------------------------------------------------------------------
# Authenticated Page Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture( scope="function" )
def logged_in_page( page, clean_test_db, test_user_credentials ):
    """
    Provide a Playwright page logged in as a regular user.

    Registers a new user via browser UI, then logs in via browser UI.

    Requires:
        - Server running with Testing config
        - Clean test database

    Ensures:
        - Returns a Playwright page with an authenticated session
        - User tokens stored in browser localStorage
    """
    email    = test_user_credentials[ "email" ]
    password = test_user_credentials[ "password" ]

    # Register via browser
    page.goto( f"{BASE_URL}/app/auth/register" )
    fill_register_form( page, email, password )
    page.wait_for_url( "**/login**", timeout=10000 )

    # Login via browser
    page.goto( f"{BASE_URL}/app/auth/login" )
    fill_login_form( page, email, password )
    page.wait_for_url( "**/app**", timeout=10000 )

    # Wait for localStorage tokens to be populated
    page.wait_for_function(
        'localStorage.getItem( "lupin_access_token" ) !== null',
        timeout=5000
    )

    return page


@pytest.fixture( scope="function" )
def admin_page( page, clean_test_db, test_admin_credentials ):
    """
    Provide a Playwright page logged in as an admin user.

    Registers a new user via browser UI, assigns admin role via DB,
    then logs in via browser UI.

    Requires:
        - Server running with Testing config
        - Clean test database

    Ensures:
        - Returns a Playwright page with an admin-authenticated session
        - User has both 'user' and 'admin' roles
    """
    email    = test_admin_credentials[ "email" ]
    password = test_admin_credentials[ "password" ]

    # Register via browser
    page.goto( f"{BASE_URL}/app/auth/register" )
    fill_register_form( page, email, password )
    page.wait_for_url( "**/login**", timeout=10000 )

    # Assign admin role via DB (no API for this)
    from cosa.rest.db.database import get_db
    from cosa.rest.db.repositories import UserRepository
    from sqlalchemy.orm.attributes import flag_modified

    with get_db() as session:
        user_repo = UserRepository( session )
        user      = user_repo.get_by_email( email )
        if user:
            user.roles = [ "user", "admin" ]
            flag_modified( user, "roles" )

    # Login via browser
    page.goto( f"{BASE_URL}/app/auth/login" )
    fill_login_form( page, email, password )
    page.wait_for_url( "**/app**", timeout=10000 )

    # Wait for localStorage tokens to be populated
    page.wait_for_function(
        'localStorage.getItem( "lupin_access_token" ) !== null',
        timeout=5000
    )

    return page


# ---------------------------------------------------------------------------
# Notifications Page Fixture (Phase 7)
# ---------------------------------------------------------------------------

@pytest.fixture( scope="function" )
def notifications_page( logged_in_page ):
    """
    Provide a Playwright page on the notifications page with WebSocket connections established.

    Requires:
        - logged_in_page fixture (authenticated session)

    Ensures:
        - Page navigated to /app/notifications
        - Queue WebSocket shows 'Connected' status
    """
    logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
    logged_in_page.wait_for_load_state( "networkidle" )

    # Wait for queue WS to connect
    wait_for_ws_connected( logged_in_page )

    return logged_in_page


# ---------------------------------------------------------------------------
# WebSocket Helpers (Phase 7)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Job History Seed Helpers (Phase 6 — Session 372)
# ---------------------------------------------------------------------------

def get_user_id_from_page( page ):
    """
    Extract user_id (uid) from JWT access token in browser localStorage.

    Requires:
        - page has lupin_access_token in localStorage (logged-in session)

    Ensures:
        - Returns the uid string from the JWT payload

    Returns:
        str: User ID (UUID string from users table)
    """
    import json
    import base64

    token   = page.evaluate( 'localStorage.getItem( "lupin_access_token" )' )
    # JWT is header.payload.signature — decode the payload
    payload = token.split( "." )[ 1 ]
    # Add padding for base64 decoding
    padding = 4 - len( payload ) % 4
    if padding != 4:
        payload += "=" * padding
    decoded = json.loads( base64.b64decode( payload ) )
    # JWT uses "sub" claim for user ID; the API's get_current_user maps it to "uid"
    return decoded[ "sub" ]


@pytest.fixture( scope="function" )
def seeded_history_page( logged_in_page ):
    """
    Seed 5 standard job_history rows for the logged-in user, navigate to notifications.

    Requires:
        - logged_in_page fixture (authenticated browser session)

    Ensures:
        - 5 job_history rows inserted for the current user
        - Page navigated to /app/notifications
        - Returns (page, records) tuple

    Returns:
        tuple: (Playwright page, list of seeded record dicts)
    """
    from tests.helpers.job_history_seed import seed_standard_job_set

    user_id    = get_user_id_from_page( logged_in_page )
    user_email = "e2e_test@example.com"
    records    = seed_standard_job_set( user_id, user_email )

    logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
    logged_in_page.wait_for_load_state( "networkidle" )

    return logged_in_page, records


@pytest.fixture( scope="function" )
def seeded_time_window_page( logged_in_page ):
    """
    Seed 3 jobs at 3d/10d/40d ago for time-window filter testing.

    Requires:
        - logged_in_page fixture

    Ensures:
        - 3 job_history rows with varied ages
        - Page navigated to /app/notifications
        - Returns (page, records) tuple
    """
    from tests.helpers.job_history_seed import seed_time_window_jobs

    user_id    = get_user_id_from_page( logged_in_page )
    user_email = "e2e_test@example.com"
    records    = seed_time_window_jobs( user_id, user_email )

    logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
    logged_in_page.wait_for_load_state( "networkidle" )

    return logged_in_page, records


@pytest.fixture( scope="function" )
def seeded_pagination_page( logged_in_page ):
    """
    Seed 25 jobs for pagination testing (API limit=20 per page).

    Requires:
        - logged_in_page fixture

    Ensures:
        - 25 job_history rows inserted
        - Page navigated to /app/notifications
        - Returns (page, records) tuple
    """
    from tests.helpers.job_history_seed import seed_pagination_jobs

    user_id    = get_user_id_from_page( logged_in_page )
    user_email = "e2e_test@example.com"
    records    = seed_pagination_jobs( user_id, user_email, count=25 )

    logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
    logged_in_page.wait_for_load_state( "networkidle" )

    return logged_in_page, records


# ---------------------------------------------------------------------------
# WebSocket Helpers (Phase 7)
# ---------------------------------------------------------------------------

def capture_websockets( page ):
    """
    Register WebSocket listener before navigation. Returns list that fills as WS connections open.

    Requires:
        - page is a Playwright page object
        - Must be called BEFORE page.goto() so listener catches WS opens

    Ensures:
        - Returns a list that accumulates WebSocket objects as they open
    """
    websockets = []
    page.on( "websocket", lambda ws: websockets.append( ws ) )
    return websockets


def wait_for_ws_connected( page, timeout=10000 ):
    """
    Wait for queue WS status indicator to show 'Connected'.

    Requires:
        - page is on the notifications page
        - WebSocket connections are being established

    Ensures:
        - Returns when queue-ws-status element contains 'Connected'

    Raises:
        - TimeoutError if status doesn't update within timeout
    """
    page.wait_for_function(
        """() => {
            const el = document.getElementById( 'queue-ws-status' );
            return el && el.textContent.includes( 'Connected' );
        }""",
        timeout=timeout
    )


def get_ws_status( page, ws_type="queue" ):
    """
    Read current WS status indicator text and CSS class.

    Requires:
        - page is on the notifications page
        - ws_type is 'queue', 'audio', or 'auth'

    Ensures:
        - Returns dict with 'text' and 'class_name' keys
    """
    element_id = {
        "queue" : "queue-ws-status",
        "audio" : "audio-ws-status",
        "auth"  : "auth-status",
    }[ ws_type ]

    return page.evaluate(
        """( eid ) => {
            const el = document.getElementById( eid );
            if ( !el ) return { text: null, class_name: null };
            return { text: el.textContent, class_name: el.className };
        }""",
        element_id
    )
