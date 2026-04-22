"""
Integration tests for the central navigation hub.

Tests all /app/* clean URLs and legacy /static/html/* paths return 200
with HTML content-type. Also verifies nav component assets are accessible.

Tests against live FastAPI server (requires server running on port 7999).

Generated on: 2026-02-21
"""

import os

import pytest
import requests

BASE_URL = os.environ.get( "LUPIN_TEST_BASE_URL", "http://localhost:8000" )


# ============================================================================
# Clean URL tests — /app/* routes
# ============================================================================

@pytest.mark.parametrize( "path", [
    "/app",
    "/app/notifications",
    "/app/auth/login",
    "/app/auth/register",
    "/app/auth/profile",
    "/app/auth/change-password",
    "/app/admin",
    "/app/admin/users",
    "/app/admin/snapshots",
    "/app/admin/proxy-ratify",
    "/app/admin/proxy-dashboard",
    "/app/admin/dev-tools",
] )
def test_clean_url_returns_200( path ):
    """
    Verify all /app/* clean URLs return 200 with HTML content.

    Requires:
        - FastAPI server running on port 7999
        - Pages router registered in main.py

    Ensures:
        - HTTP 200 status code
        - Content-Type includes text/html
    """
    response = requests.get( f"{BASE_URL}{path}", timeout=5 )
    assert response.status_code == 200, f"{path} returned {response.status_code}"
    assert "text/html" in response.headers.get( "content-type", "" ), f"{path} not HTML"


# ============================================================================
# Legacy URL backward-compatibility tests
# ============================================================================

@pytest.mark.parametrize( "path", [
    "/static/html/notifications.html",
    "/static/html/auth/login.html",
    "/static/html/auth/register.html",
    "/static/html/auth/profile.html",
    "/static/html/auth/change-password.html",
    "/static/html/admin/dashboard.html",
    "/static/html/admin/snapshots.html",
    "/static/html/auth/admin/users.html",
    "/static/html/auth/admin/proxy-ratify.html",
    "/static/html/auth/admin/proxy-dashboard.html",
] )
def test_legacy_url_returns_200( path ):
    """
    Verify all legacy /static/html/* paths still work (backwards compatibility).

    Requires:
        - FastAPI server running on port 7999
        - Static files mount still active

    Ensures:
        - HTTP 200 status code
        - Content-Type includes text/html
    """
    response = requests.get( f"{BASE_URL}{path}", timeout=5 )
    assert response.status_code == 200, f"Legacy {path} returned {response.status_code}"
    assert "text/html" in response.headers.get( "content-type", "" ), f"Legacy {path} not HTML"


# ============================================================================
# Navigation component asset tests
# ============================================================================

@pytest.mark.parametrize( "path,expected_type", [
    ( "/static/js/lupin-nav.js", "javascript" ),
    ( "/static/css/lupin-nav.css", "css" ),
] )
def test_nav_assets_accessible( path, expected_type ):
    """
    Verify navigation JS and CSS assets are accessible.

    Requires:
        - FastAPI server running on port 7999
        - Static files mount active

    Ensures:
        - HTTP 200 status code
        - Content-Type matches expected type
    """
    response = requests.get( f"{BASE_URL}{path}", timeout=5 )
    assert response.status_code == 200, f"Nav asset {path} returned {response.status_code}"
    content_type = response.headers.get( "content-type", "" )
    assert expected_type in content_type, f"Nav asset {path} has wrong content-type: {content_type}"


# ============================================================================
# Root health check test (/ serves system health, not redirect)
# ============================================================================

def test_root_serves_health_check():
    """
    Verify / returns the system health check (not a redirect).

    Requires:
        - FastAPI server running on port 7999
        - System router registered

    Ensures:
        - HTTP 200 status code
        - JSON response with status field
    """
    response = requests.get( f"{BASE_URL}/", timeout=5 )
    assert response.status_code == 200, f"Root returned {response.status_code}, expected 200"
    data = response.json()
    assert "status" in data, "Root health check missing 'status' field"


# ============================================================================
# Nav injection smoke test — verify nav CSS/JS referenced in HTML pages
# ============================================================================

@pytest.mark.parametrize( "path", [
    "/app",
    "/app/notifications",
    "/app/auth/login",
    "/app/admin",
] )
def test_pages_include_nav_assets( path ):
    """
    Verify representative pages include the nav CSS and JS references.

    Requires:
        - FastAPI server running on port 7999

    Ensures:
        - Response body contains lupin-nav.css reference
        - Response body contains lupin-nav.js reference
    """
    response = requests.get( f"{BASE_URL}{path}", timeout=5 )
    assert response.status_code == 200

    body = response.text
    assert "lupin-nav.css" in body, f"{path} missing lupin-nav.css"
    assert "lupin-nav.js" in body, f"{path} missing lupin-nav.js"
