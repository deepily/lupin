"""
Integration tests for Proxy UI page content served by live FastAPI server.

Tier D tests — verify HTML pages include expected scripts, CSS, and content
when served over HTTP. Follows test_navigation_links.py pattern.

Requires:
    - FastAPI server running on port 7999

Generated on: 2026-02-23
"""

import pytest
import requests

BASE_URL = "http://localhost:7999"


# ============================================================================
# Ratification Page Content Tests
# ============================================================================

class TestRatifyPageContent:
    """Verify proxy-ratify page serves correct content via live server."""

    @pytest.fixture( autouse=True )
    def setup( self ):
        self.response = requests.get( f"{BASE_URL}/app/admin/proxy-ratify", timeout=5 )
        self.body     = self.response.text

    def test_page_returns_200( self ):
        """Ratification page returns HTTP 200."""
        assert self.response.status_code == 200

    def test_page_title( self ):
        """Page title includes 'Pending Ratification'."""
        assert "Pending Ratification" in self.body, "Missing page title"

    def test_includes_required_css( self ):
        """Page includes all 4 CSS layers."""
        assert "lupin-base.css" in self.body, "Missing lupin-base.css"
        assert "admin.css" in self.body, "Missing admin.css"
        assert "proxy-ratify.css" in self.body, "Missing proxy-ratify.css"
        assert "lupin-nav.css" in self.body, "Missing lupin-nav.css"

    def test_includes_required_scripts( self ):
        """Page includes auth.js, proxy-ratify.js, and lupin-nav.js."""
        assert "auth.js" in self.body, "Missing auth.js"
        assert "proxy-ratify.js" in self.body, "Missing proxy-ratify.js"
        assert "lupin-nav.js" in self.body, "Missing lupin-nav.js"

    def test_admin_header_present( self ):
        """Page contains the Decision Proxy admin header."""
        assert "Decision Proxy" in self.body, "Missing admin header text"


# ============================================================================
# Trust Dashboard Page Content Tests
# ============================================================================

class TestDashboardPageContent:
    """Verify proxy-dashboard page serves correct content via live server."""

    @pytest.fixture( autouse=True )
    def setup( self ):
        self.response = requests.get( f"{BASE_URL}/app/admin/proxy-dashboard", timeout=5 )
        self.body     = self.response.text

    def test_page_returns_200( self ):
        """Trust Dashboard page returns HTTP 200."""
        assert self.response.status_code == 200

    def test_page_title( self ):
        """Page title includes 'Trust Dashboard'."""
        assert "Trust Dashboard" in self.body, "Missing page title"

    def test_includes_required_css( self ):
        """Page includes all 5 CSS layers."""
        assert "lupin-base.css" in self.body, "Missing lupin-base.css"
        assert "admin.css" in self.body, "Missing admin.css"
        assert "proxy-dashboard.css" in self.body, "Missing proxy-dashboard.css"
        assert "lupin-nav.css" in self.body, "Missing lupin-nav.css"

    def test_includes_required_scripts( self ):
        """Page includes auth.js, proxy-dashboard.js, and lupin-nav.js."""
        assert "auth.js" in self.body, "Missing auth.js"
        assert "proxy-dashboard.js" in self.body, "Missing proxy-dashboard.js"
        assert "lupin-nav.js" in self.body, "Missing lupin-nav.js"

    def test_admin_header_present( self ):
        """Page contains the Decision Proxy admin header."""
        assert "Decision Proxy" in self.body, "Missing admin header text"


# ============================================================================
# CSS and JS Asset Accessibility Tests
# ============================================================================

@pytest.mark.parametrize( "path,expected_type", [
    ( "/static/html/auth/admin/css/proxy-ratify.css", "css" ),
    ( "/static/html/auth/admin/css/proxy-dashboard.css", "css" ),
    ( "/static/html/auth/admin/css/admin.css", "css" ),
    ( "/static/html/auth/admin/js/proxy-ratify.js", "javascript" ),
    ( "/static/html/auth/admin/js/proxy-dashboard.js", "javascript" ),
] )
def test_proxy_assets_accessible( path, expected_type ):
    """
    Verify proxy UI CSS and JS assets return 200 with correct content-type.

    Requires:
        - FastAPI server running on port 7999
        - Static files mount active

    Ensures:
        - HTTP 200 status code
        - Content-Type includes expected type string
    """
    response = requests.get( f"{BASE_URL}{path}", timeout=5 )
    assert response.status_code == 200, f"Asset {path} returned {response.status_code}"
    content_type = response.headers.get( "content-type", "" )
    assert expected_type in content_type, f"Asset {path} has wrong content-type: {content_type}"


# ============================================================================
# Quick smoke test entry point
# ============================================================================

if __name__ == "__main__":
    pytest.main( [ __file__, "-v", "--tb=short" ] )
