"""
Unit tests for the full-page chrome parity-oracle PURE logic — the parseable
helpers added to tests.e2e_ui.parity_oracle plus the non-browser glue in
tests.parity_oracle_fullpage._fullpage_helpers. No browser, no live server (the
one HTTP path — login_tokens — is exercised via a stubbed requests.post).

100% lines/branches/functions on the new pure logic per CLAUDE.md §100% COVERAGE
MANDATE. The browser-driven tier bodies (open_and_walk's page interaction) are the
integration layer, exercised on :7999 by test_tier0/1/2_3 + test_golden_capture.

Venue: :7999 / unit-eligible — no state mutation, milliseconds.
"""

from __future__ import annotations

import pytest

from tests.e2e_ui import parity_oracle as po
from tests.parity_oracle_fullpage import _fullpage_helpers as h


# --------------------------------------------------------------------------- #
# chrome_rows_for                                                              #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize( "client", [ "legacy", "mux" ] )
def test_chrome_rows_for_resolves_each_client( client ):
    rows = po.chrome_rows_for( client )
    assert len( rows ) == len( po.CHROME_ROWS )
    assert [ r[ "key" ] for r in rows ] == [ r[ "key" ] for r in po.CHROME_ROWS ]
    for r in rows:
        assert set( r ) == { "key", "sel", "category" }
    # The mux-native V13 toolbar has no legacy selector but a real mux one.
    by_key = { r[ "key" ]: r for r in rows }
    if client == "legacy":
        assert by_key[ "V13-toolbar" ][ "sel" ] is None
    else:
        assert by_key[ "V13-toolbar" ][ "sel" ] == "#section-toolbar-mount"


def test_chrome_rows_for_rejects_unknown_client():
    with pytest.raises( ValueError, match="unknown client" ):
        po.chrome_rows_for( "firefox" )


# --------------------------------------------------------------------------- #
# links_stylesheet                                                            #
# --------------------------------------------------------------------------- #
def test_links_stylesheet_matches_with_dir_prefix_and_cache_buster():
    assert po.links_stylesheet( '<link href="/static/css/lupin-nav.css">', "lupin-nav.css" )
    assert po.links_stylesheet( '<link href="/static/css/notifications.css?v=20260530c">', "notifications.css" )


def test_links_stylesheet_returns_false_when_absent():
    assert not po.links_stylesheet( '<link href="/static/css/other.css">', "lupin-nav.css" )


# --------------------------------------------------------------------------- #
# hashes / paths / staleness                                                  #
# --------------------------------------------------------------------------- #
def test_chrome_css_hashes_shape():
    hashes = po.chrome_css_hashes()
    assert set( hashes ) == { "lupin-nav.css", "notifications.css", "broadcast-panel.css" }
    assert all( len( v ) == 12 for v in hashes.values() )


def test_legacy_chrome_sheet_paths_point_at_css():
    paths = po.legacy_chrome_sheet_paths()
    assert len( paths ) == 3
    assert all( str( p ).endswith( ".css" ) for p in paths )


def test_fullpage_golden_path_is_separate_from_sender_card_golden():
    p = po.fullpage_golden_path()
    assert p.name == "notifications-legacy-fullpage.golden.json"
    assert p.name != "notifications-legacy.golden.json"


def test_fullpage_golden_is_stale_true_when_hashes_missing_or_wrong():
    assert po.fullpage_golden_is_stale( {} ) is True
    assert po.fullpage_golden_is_stale( { "css_hashes": { "lupin-nav.css": "deadbeef0000" } } ) is True


def test_fullpage_golden_is_stale_false_when_hashes_match_live():
    fresh = { "css_hashes": po.chrome_css_hashes() }
    assert po.fullpage_golden_is_stale( fresh ) is False


# --------------------------------------------------------------------------- #
# module constants sanity                                                      #
# --------------------------------------------------------------------------- #
def test_known_open_rows_are_real_chrome_rows():
    keys = { r[ "key" ] for r in po.CHROME_ROWS }
    # Any pinned-open row must be a real chrome row; the set is EMPTY post-H2 batch-merge
    # (V2 env-label + clock promoted to present-required). It stays as the future-gap hook.
    assert po.KNOWN_OPEN_CHROME_ROWS <= keys
    assert po.KNOWN_OPEN_CHROME_ROWS == set()


def test_v5_header_row_measures_the_region_boundary():
    """V5 mux selector is the header REGION (spans both mounts), not the sub-mount —
    Rachel's boundary fix so the TTS-slider relocation doesn't false-flag a width gap."""
    v5 = next( r for r in po.CHROME_ROWS if r[ "key" ] == "V5-header" )
    assert v5[ "mux" ] == ".notifications-header-region"
    assert v5[ "mux" ] != "#notifications-header-mount"


def test_shared_chrome_sheets_and_style_props_populated():
    assert "lupin-nav.css" in po.SHARED_CHROME_SHEETS
    assert "background-color" in po.CHROME_STYLE_PROPS
    assert po.PAGE_CHROME_WALK_JS.strip().startswith( "(" )


# --------------------------------------------------------------------------- #
# _fullpage_helpers: base_url + login_tokens (stubbed requests)               #
# --------------------------------------------------------------------------- #
def test_base_url_default_and_override( monkeypatch ):
    monkeypatch.delenv( "LUPIN_TEST_BASE_URL", raising=False )
    assert h.base_url() == "http://localhost:7999"
    monkeypatch.setenv( "LUPIN_TEST_BASE_URL", "http://localhost:8000" )
    assert h.base_url() == "http://localhost:8000"


def test_login_tokens_skips_when_credentials_unset( monkeypatch ):
    monkeypatch.delenv( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL", raising=False )
    monkeypatch.delenv( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD", raising=False )
    with pytest.raises( pytest.skip.Exception ):
        h.login_tokens( "http://localhost:7999" )


class _Resp:
    def __init__( self, status, payload=None ):
        self.status_code = status
        self._payload    = payload or {}
        self.text        = "err"

    def json( self ):
        return self._payload


def test_login_tokens_returns_tokens_on_200( monkeypatch ):
    monkeypatch.setenv( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL", "a@b.com" )
    monkeypatch.setenv( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD", "pw" )
    payload = { "tokens": { "access_token": "AAA", "refresh_token": "RRR" } }
    monkeypatch.setattr( h.requests, "post", lambda *a, **k: _Resp( 200, payload ) )
    assert h.login_tokens( "http://localhost:7999" ) == ( "AAA", "RRR" )


def test_login_tokens_asserts_on_non_200( monkeypatch ):
    monkeypatch.setenv( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL", "a@b.com" )
    monkeypatch.setenv( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD", "pw" )
    monkeypatch.setattr( h.requests, "post", lambda *a, **k: _Resp( 401 ) )
    with pytest.raises( AssertionError, match="login failed" ):
        h.login_tokens( "http://localhost:7999" )


# --------------------------------------------------------------------------- #
# Tier golden-load SKIP branches ("a SKIP is a finding, not a pass") — pure     #
# (no browser); covered here so the freshness-guard defensive paths are 100%.   #
# --------------------------------------------------------------------------- #
def test_tier1_load_golden_skips_when_absent( monkeypatch, tmp_path ):
    from tests.parity_oracle_fullpage import test_tier1 as t1
    monkeypatch.setattr( t1, "fullpage_golden_path", lambda: tmp_path / "nope.json" )
    with pytest.raises( pytest.skip.Exception, match="golden not captured" ):
        t1._load_golden()


def test_tier23_golden_skips_when_absent( monkeypatch, tmp_path ):
    from tests.parity_oracle_fullpage import test_tier2_tier3 as t23
    monkeypatch.setattr( t23, "fullpage_golden_path", lambda: tmp_path / "nope.json" )
    with pytest.raises( pytest.skip.Exception, match="golden absent" ):
        t23._golden()


def test_tier23_golden_skips_when_stale( monkeypatch, tmp_path ):
    from tests.parity_oracle_fullpage import test_tier2_tier3 as t23
    golden = tmp_path / "g.json"
    golden.write_text( '{"css_hashes": {"lupin-nav.css": "stale00000000"}, "rows": {}}' )
    monkeypatch.setattr( t23, "fullpage_golden_path", lambda: golden )
    monkeypatch.setattr( t23, "fullpage_golden_is_stale", lambda g: True )
    with pytest.raises( pytest.skip.Exception, match="STALE" ):
        t23._golden()


def test_tier23_golden_returns_when_fresh( monkeypatch, tmp_path ):
    from tests.parity_oracle_fullpage import test_tier2_tier3 as t23
    golden = tmp_path / "g.json"
    golden.write_text( '{"css_hashes": {}, "rows": {"V1-nav": {"present": true}}}' )
    monkeypatch.setattr( t23, "fullpage_golden_path", lambda: golden )
    monkeypatch.setattr( t23, "fullpage_golden_is_stale", lambda g: False )
    assert t23._golden()[ "rows" ][ "V1-nav" ][ "present" ] is True


# --------------------------------------------------------------------------- #
# open_and_walk — duck-typed fake `page` so the browser-driver body (both the    #
# mux and legacy branches) is unit-covered in-process (no real browser). The     #
# live Chromium runs are the integration proof; this closes the branch coverage. #
# --------------------------------------------------------------------------- #
class _FakeContext:
    def __init__( self ):
        self.init_scripts = []

    def add_init_script( self, script ):
        self.init_scripts.append( script )


class _FakePage:
    def __init__( self, evaluate_result ):
        self.context          = _FakeContext()
        self._evaluate_result = evaluate_result
        self.calls            = []

    def goto( self, url, **kwargs ):
        self.calls.append( ( "goto", url ) )

    def wait_for_function( self, expr, **kwargs ):
        self.calls.append( ( "wait_for_function", expr ) )

    def wait_for_selector( self, sel, **kwargs ):
        self.calls.append( ( "wait_for_selector", sel ) )

    def wait_for_timeout( self, ms ):
        self.calls.append( ( "wait_for_timeout", ms ) )

    def evaluate( self, js, arg ):
        self.calls.append( ( "evaluate", arg ) )
        return self._evaluate_result


@pytest.fixture
def _authed( monkeypatch ):
    monkeypatch.setenv( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL", "a@b.com" )
    monkeypatch.setenv( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD", "pw" )
    payload = { "tokens": { "access_token": "AAA", "refresh_token": "RRR" } }
    monkeypatch.setattr( h.requests, "post", lambda *a, **k: _Resp( 200, payload ) )


def test_open_and_walk_mux_waits_for_test_hook( _authed ):
    page = _FakePage( { "V1-nav": { "present": True } } )
    result = h.open_and_walk( page, "http://x/app/multiplexer", client="mux", wait_selector="#action-required-section" )
    assert result == { "V1-nav": { "present": True } }
    kinds = [ c[ 0 ] for c in page.calls ]
    assert "wait_for_function" in kinds, "mux branch must wait for __multiplexerTestHook"
    assert page.context.init_scripts, "auth must be injected before navigation"


def test_open_and_walk_legacy_skips_test_hook( _authed ):
    page = _FakePage( {} )
    h.open_and_walk( page, "http://x/app/notifications?classic=1", client="legacy", wait_selector=".container" )
    kinds = [ c[ 0 ] for c in page.calls ]
    assert "wait_for_function" not in kinds, "legacy branch must NOT wait for the mux test hook"
    assert "evaluate" in kinds
