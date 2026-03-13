"""
Offline UI smoke tests for Proxy Ratification and Trust Dashboard pages.

Tests HTML structure, JavaScript analysis, and CSS class verification
by reading files directly from disk — no server required.

Three tiers:
    A: HTML Structure — parse HTML, verify DOM elements, CSS/JS references
    B: JS Static Analysis — verify function declarations, API endpoints, element IDs
    C: CSS Class Verification — verify expected class definitions exist

Uses stdlib html.parser only — no external dependencies.

Generated on: 2026-02-23
"""

import os
import re

import pytest

# ============================================================================
# Paths
# ============================================================================

_PROJECT_ROOT = os.environ.get( "LUPIN_ROOT", "/mnt/DATA01/include/www.deepily.ai/projects/lupin" )
_STATIC_DIR   = os.path.join( _PROJECT_ROOT, "src", "fastapi_app", "static" )

_RATIFY_HTML      = os.path.join( _STATIC_DIR, "html", "auth", "admin", "proxy-ratify.html" )
_DASHBOARD_HTML   = os.path.join( _STATIC_DIR, "html", "auth", "admin", "proxy-dashboard.html" )
_RATIFY_JS        = os.path.join( _STATIC_DIR, "html", "auth", "admin", "js", "proxy-ratify.js" )
_DASHBOARD_JS     = os.path.join( _STATIC_DIR, "html", "auth", "admin", "js", "proxy-dashboard.js" )
_RATIFY_CSS       = os.path.join( _STATIC_DIR, "html", "auth", "admin", "css", "proxy-ratify.css" )
_DASHBOARD_CSS    = os.path.join( _STATIC_DIR, "html", "auth", "admin", "css", "proxy-dashboard.css" )
_AUTH_JS          = os.path.join( _STATIC_DIR, "html", "auth", "js", "auth.js" )
_LUPIN_BASE_CSS   = os.path.join( _STATIC_DIR, "css", "lupin-base.css" )
_LUPIN_NAV_CSS    = os.path.join( _STATIC_DIR, "css", "lupin-nav.css" )
_LUPIN_NAV_JS     = os.path.join( _STATIC_DIR, "js", "lupin-nav.js" )
_ADMIN_CSS        = os.path.join( _STATIC_DIR, "html", "auth", "admin", "css", "admin.css" )


# ============================================================================
# Helpers
# ============================================================================

def _read( path ):
    """
    Read a file and return its contents as a string.

    Requires:
        - path is a valid file path

    Ensures:
        - Returns file contents as string
        - Asserts file exists before reading

    Raises:
        - AssertionError if file does not exist
    """
    assert os.path.isfile( path ), f"File not found: {path}"
    with open( path, "r", encoding="utf-8" ) as f:
        return f.read()


def _find_css_links( html_content ):
    """
    Extract all CSS href values from link tags in HTML content.

    Requires:
        - html_content is a non-empty string

    Ensures:
        - Returns list of href strings from link[rel=stylesheet] tags
    """
    return re.findall( r'<link[^>]+href=["\']([^"\']+\.css)["\']', html_content )


def _find_script_srcs( html_content ):
    """
    Extract all script src values from script tags in HTML content.

    Requires:
        - html_content is a non-empty string

    Ensures:
        - Returns list of src strings from script tags
    """
    return re.findall( r'<script[^>]+src=["\']([^"\']+\.js)["\']', html_content )


def _find_ids( html_content ):
    """
    Extract all id attribute values from HTML content.

    Requires:
        - html_content is a non-empty string

    Ensures:
        - Returns set of id strings
    """
    return set( re.findall( r'id=["\']([^"\']+)["\']', html_content ) )


def _find_function_declarations( js_content ):
    """
    Extract all function names from JS content (named functions and async functions).

    Requires:
        - js_content is a non-empty string

    Ensures:
        - Returns set of function name strings
    """
    # Match: function name( or async function name(
    return set( re.findall( r'(?:async\s+)?function\s+(\w+)\s*\(', js_content ) )


def _find_getelementbyid_refs( js_content ):
    """
    Extract all getElementById argument strings from JS content.

    Requires:
        - js_content is a non-empty string

    Ensures:
        - Returns set of element ID strings referenced in JS
    """
    return set( re.findall( r'getElementById\(\s*["\']([^"\']+)["\']', js_content ) )


def _find_css_classes( css_content ):
    """
    Extract all CSS class selectors from CSS content.

    Requires:
        - css_content is a non-empty string

    Ensures:
        - Returns set of class name strings (without the leading dot)
    """
    return set( re.findall( r'\.([a-zA-Z][\w-]*)\s*[{,:]', css_content ) )


# ============================================================================
# Tier A: Ratification Page — HTML Structure (14 tests)
# ============================================================================

class TestRatifyHtmlStructure:
    """Tier A — Ratification page HTML structural verification."""

    @pytest.fixture( autouse=True )
    def setup( self ):
        self.html = _read( _RATIFY_HTML )

    def test_css_cascade_order( self ):
        """CSS files load in correct 4-layer cascade order."""
        links = _find_css_links( self.html )
        assert len( links ) >= 4, f"Expected >= 4 CSS links, got {len( links )}"

        # Verify ordering: lupin-base → admin → proxy-ratify → lupin-nav
        base_idx   = next( ( i for i, l in enumerate( links ) if "lupin-base.css" in l ), -1 )
        admin_idx  = next( ( i for i, l in enumerate( links ) if "admin.css" in l ), -1 )
        ratify_idx = next( ( i for i, l in enumerate( links ) if "proxy-ratify.css" in l ), -1 )
        nav_idx    = next( ( i for i, l in enumerate( links ) if "lupin-nav.css" in l ), -1 )

        assert base_idx >= 0, "Missing lupin-base.css"
        assert admin_idx >= 0, "Missing admin.css"
        assert ratify_idx >= 0, "Missing proxy-ratify.css"
        assert nav_idx >= 0, "Missing lupin-nav.css"
        assert base_idx < admin_idx < ratify_idx < nav_idx, \
            f"CSS cascade order wrong: base={base_idx}, admin={admin_idx}, ratify={ratify_idx}, nav={nav_idx}"

    def test_script_references( self ):
        """Page loads auth.js, proxy-ratify.js, and lupin-nav.js."""
        scripts = _find_script_srcs( self.html )
        script_names = [ os.path.basename( s ) for s in scripts ]

        assert "auth.js" in script_names, "Missing auth.js script"
        assert "proxy-ratify.js" in script_names, "Missing proxy-ratify.js script"
        assert "lupin-nav.js" in script_names, "Missing lupin-nav.js script"

    def test_breadcrumb_structure( self ):
        """Breadcrumb contains Home > Admin > Pending Ratification."""
        assert 'href="/app"' in self.html, "Breadcrumb missing Home link"
        assert 'href="/app/admin"' in self.html, "Breadcrumb missing Admin link"
        assert "Pending Ratification" in self.html, "Breadcrumb missing current page text"

    def test_summary_card_ids( self ):
        """Summary cards have expected stat IDs."""
        ids = _find_ids( self.html )
        expected = { "stat-pending", "stat-approved", "stat-rejected", "stat-oldest" }
        assert expected.issubset( ids ), f"Missing summary card IDs: {expected - ids}"

    def test_filter_category_options( self ):
        """Category filter has 7 options (All + 6 categories)."""
        # Count option tags inside filter-category select
        category_block = re.search(
            r'id=["\']filter-category["\'][^>]*>(.+?)</select>',
            self.html, re.DOTALL
        )
        assert category_block, "filter-category select not found"
        options = re.findall( r'<option', category_block.group( 1 ) )
        assert len( options ) == 7, f"Expected 7 category options, got {len( options )}"

    def test_filter_trust_level_options( self ):
        """Trust level filter has 6 options (All + L1-L5)."""
        trust_block = re.search(
            r'id=["\']filter-trust-level["\'][^>]*>(.+?)</select>',
            self.html, re.DOTALL
        )
        assert trust_block, "filter-trust-level select not found"
        options = re.findall( r'<option', trust_block.group( 1 ) )
        assert len( options ) == 6, f"Expected 6 trust level options, got {len( options )}"

    def test_filter_action_options( self ):
        """Action filter has 5 options (All + shadow/suggest/act/defer)."""
        action_block = re.search(
            r'id=["\']filter-action["\'][^>]*>(.+?)</select>',
            self.html, re.DOTALL
        )
        assert action_block, "filter-action select not found"
        options = re.findall( r'<option', action_block.group( 1 ) )
        assert len( options ) == 5, f"Expected 5 action options, got {len( options )}"

    def test_decisions_table_headers( self ):
        """Decisions table has 8 column headers."""
        thead_block = re.search( r'<thead>(.+?)</thead>', self.html, re.DOTALL )
        assert thead_block, "Decisions table thead not found"
        headers = re.findall( r'<th', thead_block.group( 1 ) )
        assert len( headers ) == 8, f"Expected 8 table headers, got {len( headers )}"

    def test_bulk_actions_present( self ):
        """Bulk actions bar with approve/reject buttons exists."""
        ids = _find_ids( self.html )
        assert "bulk-actions" in ids, "Missing bulk-actions element"
        assert "selected-count" in ids, "Missing selected-count element"
        assert "bulkApprove()" in self.html, "Missing bulkApprove onclick"
        assert "bulkReject()" in self.html, "Missing bulkReject onclick"

    def test_detail_modal_structure( self ):
        """Detail modal has expected structure."""
        ids = _find_ids( self.html )
        assert "detail-modal" in ids, "Missing detail-modal"
        assert "decision-detail" in ids, "Missing decision-detail"
        assert "feedback-text" in ids, "Missing feedback-text textarea"
        assert "modal-approve-btn" in ids, "Missing modal-approve-btn"
        assert "modal-reject-btn" in ids, "Missing modal-reject-btn"

    def test_confirm_modal_structure( self ):
        """Confirm modal for bulk rejection exists."""
        ids = _find_ids( self.html )
        assert "confirm-modal" in ids, "Missing confirm-modal"
        assert "confirm-message" in ids, "Missing confirm-message"
        assert "confirm-yes" in ids, "Missing confirm-yes button"

    def test_pagination_controls( self ):
        """Pagination prev/next buttons and page info exist."""
        ids = _find_ids( self.html )
        assert "pagination-container" in ids, "Missing pagination-container"
        assert "prev-page" in ids, "Missing prev-page button"
        assert "next-page" in ids, "Missing next-page button"
        assert "page-info" in ids, "Missing page-info span"

    def test_empty_state( self ):
        """Empty state element exists."""
        ids = _find_ids( self.html )
        assert "empty-state" in ids, "Missing empty-state element"

    def test_loading_and_messages( self ):
        """Loading state and message divs exist."""
        ids = _find_ids( self.html )
        assert "loading" in ids, "Missing loading element"
        assert "error-message" in ids, "Missing error-message"
        assert "success-message" in ids, "Missing success-message"
        assert "main-content" in ids, "Missing main-content"


# ============================================================================
# Tier A: Trust Dashboard — HTML Structure (10 tests)
# ============================================================================

class TestDashboardHtmlStructure:
    """Tier A — Trust Dashboard HTML structural verification."""

    @pytest.fixture( autouse=True )
    def setup( self ):
        self.html = _read( _DASHBOARD_HTML )

    def test_css_cascade_order( self ):
        """CSS files load in correct 5-layer cascade order (includes proxy-ratify for badges)."""
        links = _find_css_links( self.html )
        assert len( links ) >= 5, f"Expected >= 5 CSS links, got {len( links )}"

        base_idx      = next( ( i for i, l in enumerate( links ) if "lupin-base.css" in l ), -1 )
        admin_idx     = next( ( i for i, l in enumerate( links ) if "admin.css" in l ), -1 )
        ratify_idx    = next( ( i for i, l in enumerate( links ) if "proxy-ratify.css" in l ), -1 )
        dashboard_idx = next( ( i for i, l in enumerate( links ) if "proxy-dashboard.css" in l ), -1 )
        nav_idx       = next( ( i for i, l in enumerate( links ) if "lupin-nav.css" in l ), -1 )

        assert base_idx >= 0, "Missing lupin-base.css"
        assert nav_idx >= 0, "Missing lupin-nav.css"
        assert dashboard_idx >= 0, "Missing proxy-dashboard.css"
        assert base_idx < dashboard_idx < nav_idx, "CSS cascade order wrong"

    def test_script_references( self ):
        """Page loads auth.js, proxy-dashboard.js, and lupin-nav.js."""
        scripts = _find_script_srcs( self.html )
        script_names = [ os.path.basename( s ) for s in scripts ]

        assert "auth.js" in script_names, "Missing auth.js script"
        assert "proxy-dashboard.js" in script_names, "Missing proxy-dashboard.js script"
        assert "lupin-nav.js" in script_names, "Missing lupin-nav.js script"

    def test_breadcrumb_structure( self ):
        """Breadcrumb contains Home > Admin > Trust Dashboard."""
        assert 'href="/app"' in self.html, "Breadcrumb missing Home link"
        assert 'href="/app/admin"' in self.html, "Breadcrumb missing Admin link"
        assert "Trust Dashboard" in self.html, "Breadcrumb missing current page text"

    def test_mode_bar_elements( self ):
        """Mode bar has selector, domain, user, and status dot."""
        ids = _find_ids( self.html )
        expected = { "mode-trust-select", "mode-domain", "mode-user", "mode-status-dot" }
        assert expected.issubset( ids ), f"Missing mode bar IDs: {expected - ids}"

    def test_mode_select_options( self ):
        """Mode selector has 4 options: DISABLED, SHADOW, SUGGEST, ACTIVE."""
        mode_block = re.search(
            r'id=["\']mode-trust-select["\'][^>]*>(.+?)</select>',
            self.html, re.DOTALL
        )
        assert mode_block, "mode-trust-select select not found"
        options = re.findall( r'<option', mode_block.group( 1 ) )
        assert len( options ) == 4, f"Expected 4 mode options, got {len( options )}"

        # Verify option values
        values = re.findall( r'value=["\'](\w+)["\']', mode_block.group( 1 ) )
        assert set( values ) == { "disabled", "shadow", "suggest", "active" }, \
            f"Unexpected mode values: {values}"

    def test_trust_cards_grid( self ):
        """Trust cards grid container exists."""
        ids = _find_ids( self.html )
        assert "trust-cards-grid" in ids, "Missing trust-cards-grid"

    def test_category_selector_options( self ):
        """Category selector has 7 options (All + 6 categories)."""
        cat_block = re.search(
            r'id=["\']category-selector["\'][^>]*>(.+?)</select>',
            self.html, re.DOTALL
        )
        assert cat_block, "category-selector not found"
        options = re.findall( r'<option', cat_block.group( 1 ) )
        assert len( options ) == 7, f"Expected 7 category options, got {len( options )}"

    def test_decisions_table_headers( self ):
        """Dashboard decisions table has 6 column headers."""
        thead_block = re.search( r'<thead>(.+?)</thead>', self.html, re.DOTALL )
        assert thead_block, "Dashboard table thead not found"
        headers = re.findall( r'<th', thead_block.group( 1 ) )
        assert len( headers ) == 6, f"Expected 6 table headers, got {len( headers )}"

    def test_pagination_and_empty_state( self ):
        """Pagination and empty state elements exist."""
        ids = _find_ids( self.html )
        assert "pagination-container" in ids, "Missing pagination-container"
        assert "decisions-empty" in ids, "Missing decisions-empty"

    def test_loading_and_messages( self ):
        """Loading state and message divs exist."""
        ids = _find_ids( self.html )
        assert "loading" in ids, "Missing loading element"
        assert "error-message" in ids, "Missing error-message"
        assert "success-message" in ids, "Missing success-message"
        assert "main-content" in ids, "Missing main-content"


# ============================================================================
# Tier B: JavaScript Static Analysis (13 tests)
# ============================================================================

class TestRatifyJsAnalysis:
    """Tier B — proxy-ratify.js static analysis."""

    @pytest.fixture( autouse=True )
    def setup( self ):
        self.js = _read( _RATIFY_JS )

    def test_require_auth_call( self ):
        """Page calls requireAuth() at top level."""
        assert "requireAuth()" in self.js, "Missing requireAuth() call"

    def test_api_endpoint_pending( self ):
        """JS references /proxy/pending/ endpoint."""
        assert "/proxy/pending/" in self.js, "Missing /proxy/pending/ endpoint"

    def test_api_endpoint_ratify( self ):
        """JS references /proxy/ratify/ endpoint."""
        assert "/proxy/ratify/" in self.js, "Missing /proxy/ratify/ endpoint"

    def test_expected_function_declarations( self ):
        """All 18+ expected functions are declared."""
        funcs = _find_function_declarations( self.js )

        expected = {
            "loadPending", "ratifyDecision",
            "renderSummaryCards", "renderTable", "showEmptyState",
            "getActionBadge", "getTrustBadge", "getRatificationBadge",
            "applyFilters", "clearFilters",
            "toggleSelect", "toggleSelectAll", "updateBulkActions",
            "bulkApprove", "bulkReject", "confirmBulkReject",
            "quickApprove", "quickReject",
        }
        missing = expected - funcs
        assert not missing, f"Missing function declarations: {missing}"

    def test_escape_html_function( self ):
        """XSS protection: escapeHtml function exists."""
        funcs = _find_function_declarations( self.js )
        assert "escapeHtml" in funcs, "Missing escapeHtml function"

    def test_element_id_cross_reference( self ):
        """JS getElementById refs match IDs in HTML."""
        js_refs  = _find_getelementbyid_refs( self.js )
        html_ids = _find_ids( _read( _RATIFY_HTML ) )

        # Every JS ref should have a matching HTML ID
        orphan_refs = js_refs - html_ids
        # Allow some IDs that are referenced but created dynamically
        assert len( orphan_refs ) == 0, f"JS references IDs not in HTML: {orphan_refs}"

    def test_websocket_connection( self ):
        """Page establishes WebSocket for real-time updates."""
        assert "connectProxyWebSocket" in self.js, "Missing WebSocket function"
        assert "proxy_decision_new" in self.js, "Missing proxy_decision_new event subscription"


class TestDashboardJsAnalysis:
    """Tier B — proxy-dashboard.js static analysis."""

    @pytest.fixture( autouse=True )
    def setup( self ):
        self.js = _read( _DASHBOARD_JS )

    def test_require_auth_call( self ):
        """Page calls requireAuth() at top level."""
        assert "requireAuth()" in self.js, "Missing requireAuth() call"

    def test_api_endpoint_trust( self ):
        """JS references /proxy/trust/ endpoint."""
        assert "/proxy/trust/" in self.js, "Missing /proxy/trust/ endpoint"

    def test_api_endpoint_decisions( self ):
        """JS references /proxy/decisions/ endpoint."""
        assert "/proxy/decisions/" in self.js, "Missing /proxy/decisions/ endpoint"

    def test_api_endpoint_mode( self ):
        """JS references /proxy/mode endpoint."""
        assert "/proxy/mode" in self.js, "Missing /proxy/mode endpoint"

    def test_swe_categories_constant( self ):
        """SWE_CATEGORIES constant defines 6 categories."""
        assert "SWE_CATEGORIES" in self.js, "Missing SWE_CATEGORIES constant"
        # Count key entries
        keys = re.findall( r'key:\s*"(\w+)"', self.js )
        assert len( keys ) == 6, f"Expected 6 SWE categories, got {len( keys )}: {keys}"

    def test_trust_labels_constant( self ):
        """TRUST_LABELS constant maps 5 levels."""
        assert "TRUST_LABELS" in self.js, "Missing TRUST_LABELS constant"
        labels = re.findall( r'\d\s*:\s*"([^"]+)"', self.js )
        assert len( labels ) == 5, f"Expected 5 trust labels, got {len( labels )}: {labels}"


# ============================================================================
# Tier C: CSS Class Verification (7 tests)
# ============================================================================

class TestRatifyCssClasses:
    """Tier C — proxy-ratify.css class verification."""

    @pytest.fixture( autouse=True )
    def setup( self ):
        self.css = _read( _RATIFY_CSS )
        self.classes = _find_css_classes( self.css )

    def test_summary_card_classes( self ):
        """Summary card variant classes exist."""
        expected = { "summary-cards", "summary-card", "summary-card-pending",
                     "summary-card-approved", "summary-card-rejected", "summary-card-oldest" }
        missing = expected - self.classes
        assert not missing, f"Missing summary card classes: {missing}"

    def test_action_badge_classes( self ):
        """Action badge classes exist (shadow, suggest, act, defer)."""
        expected = { "badge-shadow", "badge-suggest", "badge-act", "badge-defer" }
        missing = expected - self.classes
        assert not missing, f"Missing action badge classes: {missing}"

    def test_trust_badge_classes( self ):
        """Trust level badge classes exist (1-5)."""
        expected = { f"badge-trust-{i}" for i in range( 1, 6 ) }
        missing = expected - self.classes
        assert not missing, f"Missing trust badge classes: {missing}"

    def test_ratification_badge_classes( self ):
        """Ratification state badge classes exist."""
        expected = { "badge-pending", "badge-approved", "badge-rejected", "badge-nr" }
        missing = expected - self.classes
        assert not missing, f"Missing ratification badge classes: {missing}"

    def test_decisions_table_class( self ):
        """Decisions table class exists."""
        assert "decisions-table" in self.classes, "Missing decisions-table class"


class TestDashboardCssClasses:
    """Tier C — proxy-dashboard.css class verification."""

    @pytest.fixture( autouse=True )
    def setup( self ):
        self.css = _read( _DASHBOARD_CSS )
        self.classes = _find_css_classes( self.css )

    def test_mode_bar_classes( self ):
        """Mode bar classes exist."""
        expected = { "mode-bar", "mode-label", "mode-value", "mode-selector", "mode-status-dot" }
        missing = expected - self.classes
        assert not missing, f"Missing mode bar classes: {missing}"

    def test_trust_cards_and_levels( self ):
        """Trust card grid and level color classes exist."""
        expected = { "trust-cards-grid", "trust-card" }
        # Level classes
        for i in range( 1, 6 ):
            expected.add( f"trust-card-level-{i}" )
        missing = expected - self.classes
        assert not missing, f"Missing trust card classes: {missing}"


# ============================================================================
# Quick smoke test entry point
# ============================================================================

if __name__ == "__main__":
    pytest.main( [ __file__, "-v", "--tb=short" ] )
