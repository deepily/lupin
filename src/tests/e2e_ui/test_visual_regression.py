"""
E2E UI visual regression tests for all Lupin pages.

Phase 8: Visual Regression — parametrized screenshot comparison for all 12 pages.
Uses pytest-playwright-visual-snapshot to capture and compare baseline screenshots.

Dynamic elements (clocks, session IDs, WS status indicators) are normalized
IN THIS FILE by NORMALIZE_SPECS below — each spec declares the pages it applies
to, and `normalize_dynamic_content()` FAILS when a spec claims a page and finds
nothing there.

There is no pytest.ini mask configuration. An earlier version of this docstring
said masks came from a `playwright_visual_snapshot_masks` key; no such key has
ever existed in this repo (repo-wide fixed-string search returns exactly one
hit — the sentence that claimed it). That sentence told every author of a visual
snapshot the clocks were already handled while four selectors below matched
nothing, which is why the guard now refuses silence instead of describing it.

Requires:
    - The test server on port 8000 with Testing config — NOT :7999. `BASE_URL`
      (conftest.py:28) defaults to http://localhost:8000, overridable with
      LUPIN_TEST_BASE_URL. An earlier version of this line said 7999; it was
      describing a venue this suite has not used, and a reader who believed it
      would point a visual run at the dev server and compare its own baselines.
    - Clean test database (via clean_test_db fixture)
    - Baseline snapshots in src/tests/e2e_ui/__snapshots__/
      (auto-created on first run, update with --update-snapshots)
"""

import pytest

from .conftest import (
    BASE_URL, PAGE_URLS,
    PUBLIC_PAGES, AUTH_PAGES, ADMIN_PAGES, HYBRID_PAGES,
    fill_login_form, fill_register_form,
)


# ---------------------------------------------------------------------------
# Dynamic Content Normalization
# ---------------------------------------------------------------------------

# Normalization is PER PAGE. A selector that is legitimately absent from the page
# under test must not redden the run, and a selector that CLAIMS the page under
# test and matches nothing must. The previous flat list could express neither:
# it ran `querySelector` over every page and silently skipped every miss, so four
# dead entries (#clock-display, #time-display, [data-testid="session-id"],
# [data-testid="current-time"]) sat here looking like protection. Measured
# 2026-09-15: 4 of 8 selectors matched nothing anywhere under src/lupin_app.
#
# Two further consequences of that silence, both fixed here:
#   - #clock-display was the real element #clock, off by a suffix
#     (notifications.html:100). /app/multiplexer builds a SECOND element with the
#     same id at runtime (NotificationsHeaderRenderer.ts:173-175), but that page
#     is not in PAGE_URLS, so it is out of this suite's scope — noted so the next
#     reader does not re-derive it.
#   - [data-testid="session-id"] exists only on scratch pages under static/html/test/.
#     The live session ids on /app/notifications are #queue-session and
#     #audio-session (notifications.js:2510-2511), and nothing was normalizing them.
#
# Each spec: sel, text, pages. `pages` names PAGE_URLS keys and is checked
# statically by test_normalize_specs_name_real_pages.

NORMALIZE_SPECS = (
    { "sel": '[data-testid="profile-user-id"]', "text": "00000000-0000-0000-0000-000000000000", "pages": ( "profile", ) },
    { "sel": "#clock",           "text": "12:00",          "pages": ( "notifications", ) },
    { "sel": "#queue-session",   "text": "stable-session", "pages": ( "notifications", ) },
    { "sel": "#audio-session",   "text": "stable-session", "pages": ( "notifications", ) },
    { "sel": "#queue-ws-status", "text": "Connected",      "pages": ( "notifications", ) },
    { "sel": "#audio-ws-status", "text": "Connected",      "pages": ( "notifications", ) },
    { "sel": "#auth-status",     "text": "Authenticated",  "pages": ( "notifications", ) },
    # proxy-ratify.js:119 — formatRelativeTime( summary.oldest_pending ). Has an id,
    # so unlike the table cells below it takes an ordinary spec.
    { "sel": "#stat-oldest",     "text": "12h ago",        "pages": ( "admin-ratify", ) },
)

# Column-indexed normalizers. These cannot ride NORMALIZE_SPECS because the
# drifting value is a bare <td> with no selector of its own — only its position in
# the row identifies it.
#
# admin-users   Created / Last Login render via formatDate() as relative times
#               ("Just now", "3 hours ago") that drift every run.
# admin-ratify  proxy-ratify.js:192, column 7 — formatRelativeTime( created_at ).
# admin-trust   proxy-dashboard.js:343, column 0 — the SAME function, a
#               byte-identical second copy at proxy-dashboard.js:429.
#
# MEASURED at :7999 on 2026-09-15, read-only, no capture: admin-trust served FIVE
# cells reading "6m ago" and was normalized by nothing. admin-ratify's #stat-oldest
# read "2/26/2026" — stable only because its data is >7 days old, where that same
# function falls through to toLocaleDateString(). Latent, not safe.
#
# Both admin tables use id="decisions-tbody", so the id CANNOT discriminate them.
# Keyed on their data-testid instead, which differs per page.

NORMALIZE_TABLE_SPECS = (
    { "sel": "#users-tbody tr",
      "columns": { 5: "1/1/2026", 6: "Never" },
      "pages"  : ( "admin-users", ) },

    { "sel": '[data-testid="ratify-decisions-table"] tr',
      "columns": { 7: "12h ago" },
      "pages"  : ( "admin-ratify", ) },

    { "sel": '[data-testid="trust-decisions-table"] tr',
      "columns": { 0: "12h ago" },
      "pages"  : ( "admin-trust", ) },
)

_NORMALIZE_JS = """
( specs ) => {
    const report = {};
    for ( const { sel, text } of specs ) {
        const els = document.querySelectorAll( sel );
        els.forEach( el => { el.textContent = text; } );
        report[ sel ] = els.length;
    }
    return report;
}
"""

_NORMALIZE_TABLE_JS = """
( specs ) => {
    const report = {};
    for ( const { sel, columns } of specs ) {
        const rows = document.querySelectorAll( sel );
        rows.forEach( ( row ) => {
            for ( const [ index, text ] of Object.entries( columns ) ) {
                const cell = row.children[ Number( index ) ];
                if ( cell ) cell.textContent = text;
            }
        } );
        report[ sel ] = rows.length;
    }
    return report;
}
"""


def normalize_table_columns( browser_page, page_name ):
    """
    Normalize column-indexed drifting cells on this page.

    Requires:
        - browser_page is navigated and settled (these tables render from a fetch)
        - page_name is a key in PAGE_URLS

    Ensures:
        - specs not claiming page_name are skipped, not failed
        - a spec claiming this page whose table matches NO rows fails, because a
          loop over zero rows normalizes nothing while passing every assertion
          inside it
        - returns the {selector: row_count} report

    Raises:
        - AssertionError if a claimed table yields zero rows
    """
    specs = [ s for s in NORMALIZE_TABLE_SPECS if page_name in s[ "pages" ] ]

    if not specs:
        return {}

    report = browser_page.evaluate( _NORMALIZE_TABLE_JS, specs )
    empty  = sorted( sel for sel, rows in report.items() if rows == 0 )

    assert not empty, (
        f"{page_name}: table normalizer matched ZERO rows for {empty}. Two different "
        f"causes, and they need different fixes: the SELECTOR may be wrong (fix the "
        f"spec), or the FIXTURE may seed no rows for this page (a data condition — the "
        f"columns then need no normalizing, so narrow the spec's `pages`). Do not "
        f"delete the assertion: a loop over zero rows leaves the cells live."
    )

    return report


def normalize_dynamic_content( browser_page, page_name ):
    """
    Normalize this page's dynamic text to stable placeholders before capture.

    Requires:
        - browser_page is navigated and settled
        - page_name is a key in PAGE_URLS

    Ensures:
        - every spec CLAIMING page_name matched at least one element, or the
          test fails naming the selector — silence is the defect being guarded
        - specs not claiming page_name are skipped, not failed
        - returns the {selector: match_count} report

    Raises:
        - AssertionError if a spec claims this page and matches nothing
    """
    specs = [ s for s in NORMALIZE_SPECS if page_name in s[ "pages" ] ]

    if not specs:
        return {}

    report  = browser_page.evaluate( _NORMALIZE_JS, specs )
    missing = sorted( sel for sel, count in report.items() if count == 0 )

    assert not missing, (
        f"{page_name}: {len( missing )} of {len( specs )} normalizer selectors matched "
        f"NOTHING on this page: {missing}. Either the element moved (fix the selector) "
        f"or it no longer belongs to this page (fix the spec's `pages`). Do not delete "
        f"the assertion — an unmatched selector normalizes nothing and the snapshot "
        f"captures live data."
    )

    return report


# ---------------------------------------------------------------------------
# Page Definitions for Parametrization
# ---------------------------------------------------------------------------

# Each entry: ( page_name, fixture_type )
# fixture_type determines which auth fixture to use:
#   "public"  — no auth (raw page fixture)
#   "auth"    — logged_in_page fixture
#   "admin"   — admin_page fixture

VISUAL_PAGES = (
    [ ( name, "public" ) for name in PUBLIC_PAGES ] +
    [ ( name, "auth" )   for name in AUTH_PAGES + HYBRID_PAGES ] +
    [ ( name, "admin" )  for name in ADMIN_PAGES ]
)


# ---------------------------------------------------------------------------
# Visual Regression Tests
# ---------------------------------------------------------------------------

class TestVisualRegression:
    """Full-page screenshot comparison for all Lupin pages."""

    @pytest.mark.parametrize(
        "page_name,fixture_type",
        VISUAL_PAGES,
        ids=[ name for name, _ in VISUAL_PAGES ],
    )
    def test_visual_page( self, request, clean_test_db, assert_snapshot, page_name, fixture_type ):
        """
        Capture full-page screenshot and compare against baseline.

        Requires:
            - page_name is a valid key in PAGE_URLS
            - fixture_type is one of: public, auth, admin
            - assert_snapshot fixture from pytest-playwright-visual-snapshot

        Ensures:
            - Page loads successfully (200 status)
            - Screenshot matches baseline within configured threshold
            - Dynamic elements are normalized, and a spec claiming this page
              that matches nothing fails the test rather than being skipped
        """
        # Get the appropriate page fixture based on auth requirements
        if fixture_type == "admin":
            browser_page = request.getfixturevalue( "admin_page" )
        elif fixture_type == "auth":
            browser_page = request.getfixturevalue( "logged_in_page" )
        else:
            browser_page = request.getfixturevalue( "page" )

        url      = f"{BASE_URL}{PAGE_URLS[ page_name ]}"
        response = browser_page.goto( url )
        browser_page.wait_for_load_state( "networkidle" )

        assert response.status == 200, f"{page_name}: HTTP {response.status}"

        # Normalize dynamic content (UUIDs, timestamps, session ids, WS status) to
        # stable placeholders before screenshotting. More reliable than Playwright
        # mask overlays which produce subpixel rendering differences between runs.
        # This FAILS if a spec claims this page and matches nothing — the guard is
        # the point, not the normalization (see NORMALIZE_SPECS).
        normalize_dynamic_content( browser_page, page_name )

        normalize_table_columns( browser_page, page_name )

        # fonts.ready + 2 RAFs so any NotoColorEmoji glyphs (persona/status icons
        # on the notifications/multiplexer/etc. full-page captures) are loaded
        # before the pixel snapshot — the emoji font-race the Gate D fix closed
        # (3c7e0aab / task_editing.py). No-op on the non-emoji pages.
        browser_page.evaluate( "() => document.fonts.ready" )
        browser_page.evaluate( "() => new Promise( resolve => requestAnimationFrame( () => requestAnimationFrame( resolve ) ) )" )

        # Take screenshot and compare against baseline.
        # The name parameter creates human-readable snapshot filenames.
        assert_snapshot(
            browser_page,
            name=f"{page_name}.png",
        )

        print( f"✓ {page_name}: visual snapshot compared" )


# ---------------------------------------------------------------------------
# Spec guards — no browser, no server (these run at the unit tier)
# ---------------------------------------------------------------------------

def test_normalize_specs_name_real_pages():
    """
    Every spec's `pages` must name a real PAGE_URLS key.

    A spec claiming a page that does not exist is never applied and never
    reported — the same silence this module's guard exists to remove, moved one
    level up. Asking PAGE_URLS rather than restating its contents: two pieces of
    code deciding one rule agree until they do not.

    Ensures:
        - the spec list is non-empty (a loop over nothing passes every assertion)
        - every declared page is a PAGE_URLS key
    """
    assert NORMALIZE_SPECS, "NORMALIZE_SPECS is empty — every guard below it is vacuous"

    unknown = sorted(
        ( spec[ "sel" ], page )
        for spec in NORMALIZE_SPECS
        for page in spec[ "pages" ]
        if page not in PAGE_URLS
    )
    assert not unknown, (
        f"specs name pages that are not in PAGE_URLS: {unknown}. "
        f"Known pages: {sorted( PAGE_URLS )}"
    )


def test_normalize_specs_are_well_formed():
    """
    Each spec carries all three keys, and claims at least one page.

    A spec with an empty `pages` is applied on no page at all — dead weight that
    reads as coverage, which is the exact shape of the defect this file carried.

    Ensures:
        - every spec has sel / text / pages
        - every spec claims >= 1 page
        - no selector is declared twice for the same page
    """
    seen = set()

    for spec in NORMALIZE_SPECS:
        assert set( spec ) == { "sel", "text", "pages" }, f"malformed spec: {spec}"
        assert spec[ "pages" ], f"spec claims no page, so it never runs: {spec[ 'sel' ]}"

        for page in spec[ "pages" ]:
            key = ( spec[ "sel" ], page )
            assert key not in seen, f"duplicate spec for {key} — one of them is dead"
            seen.add( key )


def test_table_specs_are_well_formed_and_name_real_pages():
    """
    Every column-indexed table spec is complete and points at a real page.

    Ensures:
        - the spec list is non-empty (a loop over nothing passes every assertion)
        - each spec carries sel / columns / pages, and claims >= 1 page
        - column indices are non-negative ints and their replacements are strings
        - every declared page is a PAGE_URLS key, asked of PAGE_URLS not restated
    """
    assert NORMALIZE_TABLE_SPECS, "empty — every table guard below it is vacuous"

    for spec in NORMALIZE_TABLE_SPECS:
        assert set( spec ) == { "sel", "columns", "pages" }, f"malformed: {spec}"
        assert spec[ "pages" ],   f"claims no page, so it never runs: {spec[ 'sel' ]}"
        assert spec[ "columns" ], f"normalizes no column: {spec[ 'sel' ]}"

        for index, text in spec[ "columns" ].items():
            assert isinstance( index, int ) and index >= 0, f"bad column {index!r}"
            assert isinstance( text, str ),                 f"bad replacement {text!r}"

        for page in spec[ "pages" ]:
            assert page in PAGE_URLS, f"{spec[ 'sel' ]} names unknown page {page!r}"


class _StubPage:
    """
    Minimal stand-in for a Playwright page that reports what the specs asked for.

    It reads the specs it is HANDED and answers from `present`, so replacing the
    code under test with a constant changes its answer — a fixture that ignored
    its input would report the same counts however `normalize_dynamic_content`
    behaved, and every assertion written over it would inherit that blindness.
    """

    def __init__( self, present ):
        self.present   = present   # {selector: match_count} the "DOM" would return
        self.seen_specs = None     # what the function actually asked us to apply

    def evaluate( self, js, specs=None ):
        self.seen_specs = specs
        return { spec[ "sel" ]: self.present.get( spec[ "sel" ], 0 ) for spec in specs }


def test_normalize_fails_naming_the_unmatched_selector():
    """
    The guard fails, and the failure names WHICH selector matched nothing.

    This is the defect's inverse: the old loop returned successfully while
    normalizing nothing. A guard that failed with only a count would send the
    next reader to re-derive which entry died.

    Ensures:
        - AssertionError is raised when a claimed selector matches nothing
        - the message carries the selector, the page, and both counts
    """
    page = _StubPage( { "#clock": 0, "#queue-session": 1, "#audio-session": 1,
                        "#queue-ws-status": 1, "#audio-ws-status": 1, "#auth-status": 1 } )

    with pytest.raises( AssertionError ) as exc:
        normalize_dynamic_content( page, "notifications" )

    message = str( exc.value )
    assert "#clock" in message, f"failure does not name the dead selector: {message}"
    assert "notifications" in message, f"failure does not name the page: {message}"


def test_normalize_passes_and_reports_counts_when_every_claim_matches():
    """
    A page whose claimed selectors all match returns the per-selector report.

    Ensures:
        - no assertion fires
        - the report carries one entry per claimed spec
        - the specs handed to the page are exactly those claiming that page
    """
    claimed = [ s for s in NORMALIZE_SPECS if "notifications" in s[ "pages" ] ]
    page    = _StubPage( { s[ "sel" ]: 1 for s in claimed } )

    report = normalize_dynamic_content( page, "notifications" )

    assert report == { s[ "sel" ]: 1 for s in claimed }
    assert [ s[ "sel" ] for s in page.seen_specs ] == [ s[ "sel" ] for s in claimed ]


def test_normalize_skips_a_page_no_spec_claims():
    """
    A page no spec claims is skipped, not failed.

    Tiffany's design point (2026-09-15): "matches nothing" is only meaningful per
    page. A guard that asserted every entry matched on every page would redden on
    entries legitimately absent there, and people would learn to skip it.

    Ensures:
        - returns an empty report
        - the browser is never asked to evaluate anything
    """
    page   = _StubPage( {} )
    report = normalize_dynamic_content( page, "login" )

    assert report == {}
    assert page.seen_specs is None, "evaluated on a page no spec claims"


# ---------------------------------------------------------------------------
# The spec-DATA guard (Tiffany 💍, 2026-09-15) — venue-free, no server, no browser
# ---------------------------------------------------------------------------
#
# WHY THIS EXISTS. The guards above mutate CODE and are killed by it. They are
# blind to a mutation of the spec DATA: measured 2026-09-15, changing "#clock" to
# "#clock-TYPO" — and three more like it — left all six tests GREEN, 4 survivors
# out of 4. A spec list full of garbage passed everything, which is the ORIGINAL
# defect of this module reproduced one level up.
#
# So this asks the app source whether each selector exists at all. It is
# deliberately the WEAKER of the two questions, because it is the one that can be
# answered without a venue:
#     "does this selector match nothing ANYWHERE"  <- here, unit tier, no server
#     "does it match on the page its spec claims"  <- E2E only, needs a browser
# The second is not restated here. A projection of a gate must ask the gate.

import re
from pathlib import Path


_STATIC_ROOT = Path( __file__ ).resolve().parents[ 3 ] / "src" / "lupin_app" / "static"


def _selector_source_token( selector ):
    """
    Translate a spec selector into the literal an HTML/TS author would have typed.

    Requires:
        - selector is an id selector (`#name`) or an attribute selector on
          data-testid (`[data-testid="name"]`)

    Ensures:
        - returns the exact substring to search the app source for
        - raises rather than guessing at a shape it does not handle, so a new
          selector kind fails loudly here instead of silently passing the guard

    Raises:
        - ValueError for any selector shape not listed above
    """
    id_match = re.fullmatch( r"#([A-Za-z0-9_-]+)", selector )
    if id_match:
        return f'id="{id_match.group( 1 )}"'

    testid_match = re.fullmatch( r'\[data-testid="([^"]+)"\]', selector )
    if testid_match:
        return f'data-testid="{testid_match.group( 1 )}"'

    raise ValueError(
        f"unhandled selector shape: {selector!r}. Teach _selector_source_token about "
        f"it — do NOT relax this to a substring match, which would pass on anything."
    )


def _static_sources():
    """
    Every served HTML/JS/TS file, read once.

    Ensures:
        - returns a non-empty list of (path, text)
        - the emptiness check is the loop-found-something guard: a search over
          zero files reports every selector as present-nowhere, or absent-
          everywhere, depending which way the assertion runs
    """
    files = [ p for p in _STATIC_ROOT.rglob( "*" )
              if p.suffix in ( ".html", ".js", ".ts" ) and p.is_file() ]
    assert files, f"no source files under {_STATIC_ROOT} — the guard would be vacuous"
    return [ ( p, p.read_text( encoding="utf-8", errors="replace" ) ) for p in files ]


def test_every_spec_selector_exists_somewhere_in_the_app_source():
    """
    A spec selector that matches nothing anywhere is a typo, and fails here.

    This is the venue-free half of the question. It cannot tell you the spec
    claims the RIGHT page — that is the E2E run's job and is not restated here.

    Ensures:
        - the source corpus is non-empty
        - every NORMALIZE_SPECS selector appears in at least one served file
        - the failure names the selector AND the token searched for, so the next
          reader does not have to re-derive the translation
    """
    sources = _static_sources()
    missing = []

    for spec in NORMALIZE_SPECS:
        token = _selector_source_token( spec[ "sel" ] )
        if not any( token in text for _, text in sources ):
            missing.append( ( spec[ "sel" ], token ) )

    assert not missing, (
        f"{len( missing )} spec selector(s) match NOTHING in {len( sources )} served "
        f"source files: {missing}. Each pair is (selector, the literal searched for). "
        f"A selector nobody serves normalizes nothing, and the snapshot captures live data."
    )


def test_the_source_guard_can_actually_fail():
    """
    The guard's own positive control — it must reject a selector that is not there.

    A guard nobody has watched fail is a guard that might be asserting over an
    empty corpus, a swallowed exception, or a token that matches everything.

    Ensures:
        - a deliberately bogus selector is reported missing
        - a known-present selector is NOT reported missing, in the same corpus
    """
    sources = _static_sources()

    bogus   = _selector_source_token( "#surely-nothing-serves-this-id" )
    present = _selector_source_token( "#clock" )

    assert not any( bogus   in text for _, text in sources ), "the bogus control was FOUND"
    assert     any( present in text for _, text in sources ), "the positive control was MISSING"


def test_selector_translation_refuses_shapes_it_does_not_understand():
    """
    An unhandled selector shape raises rather than quietly passing.

    Ensures:
        - a class selector, a compound and an empty string all raise ValueError
    """
    for bad in ( ".some-class", "#a .b", "", "div" ):
        try:
            _selector_source_token( bad )
        except ValueError:
            continue
        raise AssertionError( f"{bad!r} was accepted; it should have raised" )


def test_table_spec_selectors_exist_in_the_app_source():
    """
    A table spec's selector must resolve to something the app actually serves.

    Same venue-free question as the selector guard above, for the column-indexed
    specs: does this match NOTHING anywhere. Whether it matches on the page the
    spec claims is E2E's to answer.

    ⚠️ Both admin decision tables carry id="decisions-tbody", so the id cannot tell
    them apart — these specs key on data-testid, and this guard checks that testid.

    Ensures:
        - every table spec's anchor appears in at least one served source file
        - the failure names the selector and the literal searched for
    """
    sources = _static_sources()
    missing = []

    for spec in NORMALIZE_TABLE_SPECS:
        anchor = spec[ "sel" ].split( " " )[ 0 ]      # strip the descendant part
        token  = _selector_source_token( anchor )
        if not any( token in text for _, text in sources ):
            missing.append( ( spec[ "sel" ], token ) )

    assert not missing, (
        f"{len( missing )} table spec anchor(s) match NOTHING in {len( sources )} served "
        f"source files: {missing}. Each pair is (selector, the literal searched for)."
    )


def test_normalize_table_columns_fails_on_an_empty_table():
    """
    A claimed table that yields zero rows fails, naming the selector.

    A loop over zero rows normalizes nothing and passes every assertion inside
    itself — the same silence this module exists to remove, one shape over.

    Ensures:
        - AssertionError names the selector
        - the message distinguishes the two causes, since they need different fixes
    """
    page = _StubPage( { '[data-testid="trust-decisions-table"] tr': 0 } )

    with pytest.raises( AssertionError ) as exc:
        normalize_table_columns( page, "admin-trust" )

    message = str( exc.value )
    assert "trust-decisions-table" in message, f"selector not named: {message}"
    assert "SELECTOR" in message and "FIXTURE" in message, f"causes not separated: {message}"


def test_normalize_table_columns_skips_a_page_no_table_spec_claims():
    """
    A page with no table spec is skipped, not failed.

    Ensures:
        - returns an empty report
        - the browser is never asked to evaluate anything
    """
    page   = _StubPage( {} )
    report = normalize_table_columns( page, "notifications" )

    assert report == {}
    assert page.seen_specs is None, "evaluated on a page no table spec claims"


def test_the_two_admin_decision_tables_are_told_apart_by_testid_not_id():
    """
    The discriminator is real: both tables share an id, and the specs avoid it.

    This is the assertion that would have caught the tempting wrong fix — keying
    on #decisions-tbody, which resolves on BOTH admin pages and would normalize
    the wrong column on one of them.

    Ensures:
        - no table spec anchors on the shared id
        - the two admin specs use different data-testid anchors
        - both testids appear in the served source
    """
    admin = [ s for s in NORMALIZE_TABLE_SPECS
              if s[ "pages" ] in ( ( "admin-ratify", ), ( "admin-trust", ) ) ]
    assert len( admin ) == 2, f"expected both admin table specs, got {len( admin )}"

    for spec in admin:
        assert "#decisions-tbody" not in spec[ "sel" ], (
            f"{spec[ 'sel' ]} anchors on the SHARED id — it resolves on both admin "
            f"pages and would normalize the wrong column on one of them"
        )

    anchors = { s[ "sel" ].split( " " )[ 0 ] for s in admin }
    assert len( anchors ) == 2, f"both admin specs share an anchor: {anchors}"

    sources = _static_sources()
    for anchor in anchors:
        token = _selector_source_token( anchor )
        assert any( token in text for _, text in sources ), f"{token} is served nowhere"


# ---------------------------------------------------------------------------
# The PER-PAGE template guard (Mr. Radio 🦉, 2026-09-15) — still venue-free
# ---------------------------------------------------------------------------
#
# The source guard above asks "does this selector match NOTHING anywhere". This
# asks the sharper question it deliberately left alone: does the element appear in
# the template THIS PAGE ACTUALLY SERVES. A selector can exist in the tree and be
# served by a page no spec claims — that is the wrong-page defect, and until now
# only the E2E could see it.
#
# It composes two maps and INVENTS NEITHER:
#     PAGE_URLS      page name -> URL           (conftest, the suite's own registry)
#     _ROUTE_TABLE   URL       -> template file (pages.py, what the server serves)
# Restating either would be a second source of truth that agrees until it doesn't.
#
# ⚠️ WHAT IT STILL CANNOT SEE: an element the page builds at RUNTIME is absent from
# the template and present in the DOM. /app/multiplexer's clock is exactly that
# (NotificationsHeaderRenderer.ts:173) — it is not in PAGE_URLS, so no spec claims
# it, but a future spec on a JS-rendered element would need an exemption here with
# a stated reason, NOT a relaxed assertion.


def _template_text_for_page( page_name ):
    """
    Read the template file the server actually serves for this page.

    Requires:
        - page_name is a key in PAGE_URLS

    Ensures:
        - returns the template's text
        - fails loudly if the route is unknown or the file is missing, rather than
          returning an empty string, which every `in` test below would pass over

    Raises:
        - AssertionError if the URL has no route-table entry or the file is absent
    """
    from cosa.rest.routers.pages import _ROUTE_TABLE

    url = PAGE_URLS[ page_name ]
    assert url in _ROUTE_TABLE, (
        f"{page_name} -> {url} is not in pages.py's _ROUTE_TABLE. Either the suite "
        f"registry and the server disagree, or the route moved."
    )

    path = _STATIC_ROOT / _ROUTE_TABLE[ url ]
    assert path.is_file(), f"{page_name}: template {path} does not exist"

    return path.read_text( encoding="utf-8", errors="replace" )


def test_every_spec_selector_is_in_the_template_its_page_serves():
    """
    A spec's selector must appear in the template of every page it claims.

    This is the wrong-page defect the venue-free source guard cannot catch: a
    selector that exists somewhere in the tree but not on the page asserting it.

    Ensures:
        - at least one (spec, page) pair was checked — a loop over nothing passes
        - every claimed page's template contains the selector's literal
        - the failure names spec, page, template and the literal searched for
    """
    checked = 0
    missing = []

    for spec in NORMALIZE_SPECS:
        token = _selector_source_token( spec[ "sel" ] )
        for page in spec[ "pages" ]:
            checked += 1
            if token not in _template_text_for_page( page ):
                missing.append( ( spec[ "sel" ], page, token ) )

    assert checked, "no (spec, page) pairs checked — this guard is vacuous"
    assert not missing, (
        f"{len( missing )} of {checked} spec/page pairs name an element the page's "
        f"OWN template does not contain: {missing}. Each triple is (selector, page, "
        f"literal searched for). Either the spec claims the wrong page, or the "
        f"element is built at runtime and needs an exemption with a stated reason."
    )


def test_every_table_spec_anchor_is_in_the_template_its_page_serves():
    """
    Same per-page question for the column-indexed table specs.

    ⚠️ The two admin decision tables share id="decisions-tbody", so this checks the
    data-testid anchor — which is the thing that differs between them and the only
    reason the right column gets normalized on the right page.

    Ensures:
        - at least one pair was checked
        - every claimed page's template contains the anchor's literal
    """
    checked = 0
    missing = []

    for spec in NORMALIZE_TABLE_SPECS:
        anchor = spec[ "sel" ].split( " " )[ 0 ]
        token  = _selector_source_token( anchor )
        for page in spec[ "pages" ]:
            checked += 1
            if token not in _template_text_for_page( page ):
                missing.append( ( spec[ "sel" ], page, token ) )

    assert checked, "no (table spec, page) pairs checked — this guard is vacuous"
    assert not missing, (
        f"{len( missing )} of {checked} table spec/page pairs name an anchor the "
        f"page's OWN template does not contain: {missing}."
    )


def test_the_template_guard_can_actually_fail():
    """
    Positive control — the per-page guard must reject a right-selector/wrong-page pair.

    `#clock` is real and served by notifications. Asserting it against the login
    template must fail, or the guard is not reading templates per page at all and
    would pass a spec that claims any page in the registry.

    Ensures:
        - a known selector is present in its own page's template
        - the SAME selector is absent from a page that does not serve it
    """
    token = _selector_source_token( "#clock" )

    assert token in     _template_text_for_page( "notifications" ), "positive control MISSING"
    assert token not in _template_text_for_page( "login" ),         "negative control FOUND"


# ---------------------------------------------------------------------------
# The OVER-BROAD guard (Tiffany 💍, 2026-09-15) — the converse question
# ---------------------------------------------------------------------------
#
# The two guards above ask whether a selector is PRESENT where its spec claims it.
# Neither asks whether it is ALSO present somewhere no spec claims — and that is a
# silent drift source, not a harmless surplus: `normalize_dynamic_content` only
# applies specs claiming the page under test, so an element matching the same
# selector on an UNCLAIMED page is captured live, every run, guarded by nothing.
#
# The concrete case is already in this file. id="decisions-tbody" resolves on BOTH
# admin decision pages; a spec written against it would normalize admin-ratify and
# leave admin-trust drifting, while every present-where-claimed guard stayed green.
#
# Measured 2026-09-15: zero over-broad selectors today. A guard whose green is
# structural rather than earned is worth nothing, so
# test_the_over_broad_guard_can_actually_fail pins the detector against the shared
# id and fails if that id ever STOPS being shared — at which point this guard has
# lost its only real specimen and someone should say so out loud.


def _pages_whose_template_contains( token ):
    """
    Every page in PAGE_URLS whose served template contains this literal.

    Requires:
        - token is the source literal from _selector_source_token

    Ensures:
        - returns a set of PAGE_URLS keys, possibly empty
        - a page whose route or file is missing raises via _template_text_for_page
          rather than being silently skipped, which would under-report
    """
    return { page for page in PAGE_URLS
             if token in _template_text_for_page( page ) }


def _assert_not_over_broad( specs ):
    """
    Raise if any spec's selector resolves on a page that spec does not claim.

    🔴 THE ASSERTION LIVES HERE, NOT IN THE TEST, AND THAT IS THE POINT. With the
    check inline in the test, deleting it or inverting the set subtraction changed
    NOTHING — measured 2026-09-15, two mutation arms survived — because today no
    spec is over-broad, so both the right answer and the wrong one are the empty
    set. The guard was structurally green: unexercised, and indistinguishable from
    a broken detector. Put here, the control below drives this exact code with a
    synthetic over-broad spec, so a deleted or inverted check reddens by name.

    Requires:
        - specs is a list of dicts carrying `sel` and `pages`

    Ensures:
        - returns None when every selector resolves only on pages its spec claims
        - the failure names selector, claimed pages, surplus pages and both repairs

    Raises:
        - AssertionError if the spec list is empty, or any selector is over-broad
    """
    assert specs, "no specs handed in — a loop over nothing passes every assertion"

    over_broad = []

    for spec in specs:
        anchor  = spec[ "sel" ].split( " " )[ 0 ]
        token   = _selector_source_token( anchor )
        claimed = set( spec[ "pages" ] )
        surplus = _pages_whose_template_contains( token ) - claimed

        if surplus:
            over_broad.append( ( spec[ "sel" ], sorted( claimed ), sorted( surplus ) ) )

    assert not over_broad, (
        f"{len( over_broad )} selector(s) resolve on pages no spec claims: {over_broad}. "
        f"Each triple is (selector, claimed, ALSO resolves on). Two different repairs: "
        f"add those pages to the spec's `pages` if they should be normalized too, or "
        f"narrow the selector if the match is accidental. Leaving it means the "
        f"unclaimed page captures that element LIVE on every run."
    )


def test_no_spec_selector_resolves_on_a_page_it_does_not_claim():
    """
    No shipped spec is over-broad.

    An unclaimed page carrying the same selector is never normalized — the runtime
    applies only specs claiming the page under test — so its element reaches the
    snapshot live while every present-where-claimed guard stays green.

    Ensures:
        - both spec families are checked, and neither list is empty
    """
    _assert_not_over_broad( list( NORMALIZE_SPECS ) + list( NORMALIZE_TABLE_SPECS ) )


def test_the_over_broad_guard_can_actually_fail():
    """
    Positive control — the detector reports a genuinely over-broad spec.

    Drives `_assert_not_over_broad` itself, not a re-implementation of it, so
    deleting its assertion or inverting its set subtraction reddens HERE.

    The specimen is id="decisions-tbody", which both admin decision templates carry.
    A spec anchored on it while claiming one page is the exact defect: admin-ratify
    normalized, admin-trust drifting, every other guard green.

    ⚠️ If this fails because decisions-tbody is no longer shared, the guard has lost
    its only specimen. Do not delete this test — find another shared anchor, or
    record in the row that none exists.

    Ensures:
        - the specimen still resolves on 2+ page templates
        - the real checker RAISES on a spec claiming only one of them
        - the message names the surplus page, not merely a count
    """
    shared = _pages_whose_template_contains( _selector_source_token( "#decisions-tbody" ) )

    assert len( shared ) >= 2, (
        f"the shared-id specimen is gone: decisions-tbody resolves on {sorted( shared )}. "
        f"The over-broad guard has nothing left to prove itself against."
    )

    claimed, surplus = sorted( shared )[ 0 ], sorted( shared )[ 1 ]
    synthetic = [ { "sel": "#decisions-tbody tr", "pages": ( claimed, ) } ]

    with pytest.raises( AssertionError ) as exc:
        _assert_not_over_broad( synthetic )

    assert surplus in str( exc.value ), (
        f"the failure did not name the surplus page {surplus!r}: {exc.value}"
    )


def test_the_over_broad_checker_refuses_an_empty_spec_list():
    """
    An empty spec list raises rather than passing.

    A loop over nothing satisfies every assertion inside it, so "no specs" must not
    read as "no problems".

    Ensures:
        - AssertionError on an empty list
    """
    with pytest.raises( AssertionError ):
        _assert_not_over_broad( [] )
