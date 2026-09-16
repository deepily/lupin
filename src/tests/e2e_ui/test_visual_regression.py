"""
E2E UI visual regression tests for all Lupin pages.

Phase 8: Visual Regression — parametrized screenshot comparison for all 12 pages.
Uses pytest-playwright-visual-snapshot to capture and compare baseline screenshots.

Dynamic elements (clocks, session IDs, WS status indicators) are normalized
IN THIS FILE by NORMALIZE_SPECS below — each spec declares the pages it applies
to, and `normalize_dynamic_content()` FAILS when a spec claims a page and finds
nothing there.

⚠️ Read this precisely: pytest.ini DOES configure visual snapshots — three keys
at :92-94, a threshold and two paths. What it has never had is a MASK key. An
earlier version of this docstring said masks came from
`playwright_visual_snapshot_masks`; a repo-wide fixed-string search for that name
returns exactly one hit, the sentence that claimed it. So "pytest.ini handles it"
is half true, and the half that is false is the half about clocks. That sentence told every author of a visual
snapshot the clocks were already handled while four selectors below matched
nothing, which is why the guard now refuses silence instead of describing it.

Requires:
    - The test server on port 8000 with Testing config — NOT :7999. `BASE_URL`
      (conftest.py:28) defaults to http://localhost:8000, overridable with
      LUPIN_TEST_BASE_URL. An earlier version of this line said 7999; it was
      describing a venue this suite has not used, and a reader who believed it
      would point a visual run at the dev server and compare its own baselines.
    - Clean test database (via clean_test_db fixture)
    - Baselines under io/test-suite/visual-baselines/ — 39 PNGs, configured at
      pytest.ini:92-94 (`playwright_visual_snapshots_path`, plus the failure
      path and a 0.1 threshold). NOT src/tests/e2e_ui/__snapshots__/, which an
      earlier version of this line named and which DOES NOT EXIST: 0 files
      tracked there. io/ is gitignored and backed up outside the repo so
      baselines survive a clean checkout.
      🔴 `--update-snapshots` OVERWRITES those 39 files. It creates nothing and the
      path is not empty. Pass it only for an authorised rebaseline of a named UI
      change, and verify afterwards that each baseline which moved moved for the
      expected reason.
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

    # 🔴 THE V1 SELF-INCONSISTENCY (row e453a854). notifications.js addDebugMessage()
    # stamps every entry with `new Date().toLocaleTimeString()`, prepends it and caps
    # the list at 20, so all 20 lines carry a wall clock that moves every load.
    # MEASURED 2026-09-15 at :7999, ten consecutive load-pairs, same browser and host:
    # 10 of 10 pairs differed, ~10,100 px at threshold >16, and the differences sit in
    # rows 9312-9550 — the debug log's own band at the page foot.
    # Count and page height were CONSTANT across loads (20 entries, 9663 px), which is
    # what rules out a reflow and leaves the timestamp text as the whole story.
    # Pinned to ONE LINE so the row height is unchanged.
    { "sel": "#debug-log .debug-info", "text": "[12:00:00 PM] debug", "pages": ( "notifications", ) },

    # The four "updated HH:MM:SS EDT" stamps, same row e453a854. Each is written
    # from the wall clock when its pane refreshes, so each moves between loads.
    # MEASURED in the residual after the debug log was pinned: #epic-board-updated
    # was still differing at rows 7375-7381. The other three are its siblings by
    # class `task-list-updated` and are specified here by ID rather than by class —
    # a class selector is not expressible in this spec shape by design, and naming
    # the siblings NOW is cheaper than waiting for each to surface in a diff.
    # ALL FOUR OBSERVED, 2026-09-15, six consecutive loads — 6 distinct values each,
    # so every one of them moves. An earlier version of this comment marked three of
    # them "named from the template, not observed"; Mr. Radio 🦉 required the
    # observation, and the observation paid for itself:
    #
    # 🔴 #finished-tasks-updated RENDERS A DIFFERENT FORMAT from its three siblings.
    #    the other three  "updated 22:10:44 EDT"   (20 chars, 24h + zone)
    #    this one         "10:10:44 PM"            (11 chars, 12h, no "updated")
    #    Pinning all four to one string would have replaced an 11-char run with a
    #    20-char one and moved the layout — a determinism fix that introduces its own
    #    diff. Each is pinned in ITS OWN shape. This is exactly the defect a good
    #    prior hides: same construct, same class, different rendering.
    { "sel": "#task-list-updated",     "text": "updated 12:00:00 EDT", "pages": ( "notifications", ) },
    { "sel": "#epic-board-updated",    "text": "updated 12:00:00 EDT", "pages": ( "notifications", ) },
    { "sel": "#finished-tasks-updated","text": "12:00:00 PM",          "pages": ( "notifications", ) },
    { "sel": "#fleet-status-updated",  "text": "updated 12:00:00 EDT", "pages": ( "notifications", ) },
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
# MEASURED at :7999 on 2026-09-15, read-only, no capture. admin-trust:
#   50 of 50 column-0 cells drifting — "52m ago" x28, "53m ago" x7, "1h ago" x15
# normalized by nothing. ⚠️ A FIGURE OF FIVE APPEARED HERE EARLIER AND WAS WRONG:
# it was this author's own `.slice(0,5)` in the probe, an instrument limit reported
# as a property of the page. Tiffany caught it against the 50-row count relayed in
# the same breath. Re-measured with no slice — the answer is 50 of 50.
#
# The three distinct values matter more than the count: the cells DISAGREE inside a
# single capture, straddling the 59m->1h boundary. So the snapshot is a function of
# wall-clock at capture even within one run, not merely between runs.
#
# Drift shown across THREE readings of the same unchanged page: "6m ago" 21:09,
# "11m ago" 21:16, "52m/53m/1h" 21:57.
#
# admin-ratify's #stat-oldest read "2/26/2026" — stable ONLY because its data is
# >7 days old, where that same function falls through to toLocaleDateString().
# Latent, not safe.
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

    # 🔴 STRING KEYS AT THE BOUNDARY. Playwright serialises the payload as JSON and
    # REFUSES an object with numeric keys — verbatim, 2026-09-15:
    #     "arg.value.a[0].o[1].v.o[0].k: expected string, got number"
    # It raises BEFORE the page is touched, so every table page's visual test died
    # at this line without ever reaching a comparison (Mr. Radio 🦉, ts-fd09e5e0).
    # The spec keeps INT keys — they are row indices, and the well-formedness guard
    # type-checks them as ints — and they are stringified here, at the one place
    # that crosses into the browser. `_NORMALIZE_TABLE_JS` already does Number( index ).
    wire_specs = [ { **spec, "columns": { str( i ): t for i, t in spec[ "columns" ].items() } }
                   for spec in specs ]

    report = browser_page.evaluate( _NORMALIZE_TABLE_JS, wire_specs )
    empty  = sorted( sel for sel, rows in report.items() if rows == 0 )

    assert not empty, (
        f"{page_name}: table normalizer matched ZERO rows for {empty}. Two different "
        f"causes, and they need different fixes: the SELECTOR may be wrong (fix the "
        f"spec), or the FIXTURE may seed no rows for this page (a data condition — the "
        f"columns then need no normalizing, so narrow the spec's `pages`). Do not "
        f"delete the assertion: a loop over zero rows leaves the cells live."
    )

    return report


# ---------------------------------------------------------------------------
# Clear-and-inject: the LIVE FEED normalizer (row e453a854)
# ---------------------------------------------------------------------------
#
# The commons activity feed is not stabilised by pinning text, because its ENTRIES
# change between loads — bodies, icons and "Show more" toggles, not just clocks.
# MEASURED 2026-09-15: after the debug log and the four stamps were pinned, 6 of 10
# load-pairs still differed at rows 2039-2047, 2728-2740, 3250-3258, 3499-3507, all
# inside the feed.
#
# 🔴 WHY NOT JUST EXCLUDE THE REGION. Mr. Radio 🦉's ruling, 2026-09-15, and it is the
# reason this file exists: an exclusion does not stabilise the pane, it stops WATCHING
# the pane — permanently, including every real regression that ever lands there. That
# buys a green by shrinking the denominator and reporting it as a pass, which is the
# same defect as four dead selectors that looked like protection.
#
# Clear-and-inject keeps the pane IN FRAME and makes it deterministic, so a later
# change to the feed can still redden something. The pattern is not invented here —
# test_dm_recent_activity.py:162-168 already does exactly this: empty the live
# container, append one entry with a frozen timestamp, wait on a testid of its own.
#
# ── COVERAGE LEDGER ─────────────────────────────────────────────────────────────
# Freezing a region means the snapshot stops watching part of it. Writing down WHICH
# part is the price of doing it, so a later reader can tell protection from habit.
#
#   NO LONGER MONITORED in the commons pane: the live entries themselves — their
#   content, their count, their ordering, and any regression in how a real entry
#   renders. A change to _renderCommonsEntry would NOT redden this snapshot.
#   STILL MONITORED: the pane's frame, its position and size in the page, its
#   heading and chrome, everything around it, and the rendering of the injected
#   entry — so the entry markup's own layout is still under test.
#
# ⚠️ NOTHING ELSE ON THIS PAGE IS FROZEN, and that is a measured decision rather than
# an omission. With this freeze and the specs applied, the DOM is IDENTICAL across
# loads: 2942 leaf elements, +0/-0 differences over four consecutive loads,
# 2026-09-15. Fleet Status, the queue indicator and Finished Tasks were each named as
# suspects from pixel bands and then measured directly — all text-stable across six
# loads. Freezing them would have cost monitoring and bought no determinism.
# ⇒ Residual pixel variance below the comparator's threshold is not a defect.
# `playwright_visual_snapshot_threshold = 0.1` (pytest.ini:92) is the gate; a raw
# pixel count taken with a stricter instrument is not (Mr. Radio 🦉's ruling).

_FREEZE_COMMONS_FEED_JS = """
( config ) => {
    const list = document.getElementById( config.containerId );
    if ( !list ) return { container: false, injected: 0 };

    list.innerHTML = "";

    for ( const entry of config.entries ) {
        const row  = document.createElement( "div" );
        row.className = "commons-activity-entry";
        row.setAttribute( "data-testid", "frozen-commons-entry" );

        const icon = document.createElement( "div" );
        icon.className = "commons-activity-entry-icon";
        icon.textContent = entry.icon;

        const name = document.createElement( "div" );
        name.className = "commons-activity-entry-name";
        name.textContent = entry.name;

        const time = document.createElement( "div" );
        time.className = "commons-activity-entry-time";
        time.textContent = entry.time;

        const body = document.createElement( "p" );
        body.textContent = entry.body;

        row.append( icon, name, time, body );
        list.appendChild( row );
    }

    return { container: true, injected: list.children.length };
}
"""

# One deterministic entry per load. Deliberately fixed content: a frozen clock, a
# frozen persona, a frozen body. Nothing here is read from the live feed.
_FROZEN_COMMONS_ENTRIES = (
    { "icon": "💬", "name": "frozen", "time": "12:00",
      "body": "Frozen commons entry for the visual baseline." },
)

_COMMONS_FEED_PAGES = ( "notifications", )


def freeze_live_feeds( browser_page, page_name ):
    """
    Replace the live commons feed with fixed entries, keeping the pane in frame.

    Requires:
        - browser_page is navigated and settled
        - page_name is a key in PAGE_URLS

    Ensures:
        - pages outside _COMMONS_FEED_PAGES are skipped, not failed
        - the container must EXIST on a page that claims it — a missing container
          fails rather than returning a quiet zero, because "nothing to freeze" and
          "the container moved" print identically otherwise
        - the injected count equals the number of frozen entries
        - returns the report dict

    Raises:
        - AssertionError if the container is absent, or the wrong count landed
    """
    if page_name not in _COMMONS_FEED_PAGES:
        return {}

    report = browser_page.evaluate(
        _FREEZE_COMMONS_FEED_JS,
        { "containerId": "commons-recent-activity-entries",
          "entries"    : list( _FROZEN_COMMONS_ENTRIES ) },
    )

    assert report[ "container" ], (
        f"{page_name}: #commons-recent-activity-entries is ABSENT. Either the feed "
        f"container moved — fix the id here — or this page no longer carries it, in "
        f"which case drop it from _COMMONS_FEED_PAGES. Do not silently skip: an "
        f"unfrozen live feed goes straight into the snapshot."
    )
    assert report[ "injected" ] == len( _FROZEN_COMMONS_ENTRIES ), (
        f"{page_name}: injected {report[ 'injected' ]} entries, expected "
        f"{len( _FROZEN_COMMONS_ENTRIES )}"
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
        # Clear-and-inject FIRST: it rewrites whole entries, so pinning text before
        # it would pin text that is about to be replaced.
        freeze_live_feeds( browser_page, page_name )

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


def _assert_selectors_are_served( selectors ):
    """
    Raise if any selector's literal appears in no served source file.

    🔴 THE PREDICATE LIVES HERE FOR THE REASON `_assert_not_over_broad` DOES.
    Tiffany 💍 flagged 2026-09-15 that this guard and the template one still held
    their check inline while their controls re-implemented the matcher beside them
    — and a control that re-implements the thing it is controlling agrees with a
    broken original exactly as readily as with a correct one. Extracted so the
    control drives THIS code.

    Requires:
        - selectors is a non-empty list of id or data-testid selectors

    Ensures:
        - returns None when every selector's literal is found in some served file
        - the failure names each (selector, literal) pair and the corpus size

    Raises:
        - AssertionError on an empty list, or on any unserved selector
    """
    assert selectors, "no selectors handed in — a loop over nothing passes every assertion"

    sources = _static_sources()
    missing = []

    for selector in selectors:
        # Anchor only — a descendant selector like "#debug-log .debug-info" is
        # identified by the part that carries an id or testid. The template and
        # over-broad checkers already split this way; this one did not, which made
        # a perfectly good spec unrepresentable.
        token = _selector_source_token( selector.split( " " )[ 0 ] )
        if not any( token in text for _, text in sources ):
            missing.append( ( selector, token ) )

    assert not missing, (
        f"{len( missing )} selector(s) match NOTHING in {len( sources )} served source "
        f"files: {missing}. Each pair is (selector, the literal searched for). A "
        f"selector nobody serves normalizes nothing, and the snapshot captures live data."
    )


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
    _assert_selectors_are_served( [ s[ "sel" ] for s in NORMALIZE_SPECS ] )


def test_the_source_guard_can_actually_fail():
    """
    Positive control — the REAL checker must reject a selector nothing serves.

    ⚠️ This test used to re-implement the matcher: it searched the corpus itself
    and asserted on its own result. Measured 2026-09-15, that made three mutations
    of `_assert_selectors_are_served` SURVIVE — deleting its assertion, and
    removing its empty-list refusal — because nothing was driving the real code.
    Extracting the checker was necessary and NOT sufficient; the control has to
    call it. Tiffany 💍's point, and the measurement is hers too.

    Ensures:
        - the checker RAISES on a selector nothing serves, naming it
        - the checker PASSES on a known-served selector, in the same corpus
    """
    with pytest.raises( AssertionError ) as exc:
        _assert_selectors_are_served( [ "#surely-nothing-serves-this-id" ] )

    assert "surely-nothing-serves-this-id" in str( exc.value ), (
        f"the failure did not name the unserved selector: {exc.value}"
    )

    # Same corpus, a selector that IS served — must not raise.
    _assert_selectors_are_served( [ "#clock" ] )


def test_the_source_guard_refuses_an_empty_selector_list():
    """
    An empty selector list raises rather than passing.

    Ensures:
        - AssertionError on an empty list, so "nothing to check" cannot read as
          "nothing wrong"
    """
    with pytest.raises( AssertionError ):
        _assert_selectors_are_served( [] )


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
    _assert_selectors_are_served(
        [ s[ "sel" ].split( " " )[ 0 ] for s in NORMALIZE_TABLE_SPECS ]
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


def _assert_selectors_are_in_their_pages_templates( specs ):
    """
    Raise if a spec's selector is absent from the template of a page it claims.

    🔴 Extracted for the same reason as the two checkers above (Tiffany 💍,
    2026-09-15): the control must drive THIS code, not a copy of it standing
    beside it. A re-implemented matcher agrees with a broken original as readily
    as with a correct one, which is how a guard goes quietly dead.

    Requires:
        - specs is a non-empty list of dicts carrying `sel` and `pages`

    Ensures:
        - returns None when every claimed page's template carries the selector
        - the failure names (selector, page, literal) and both repairs

    Raises:
        - AssertionError on an empty list, no pairs checked, or any absent pair

    ⚠️ EQUIVALENT-MUTANT NOTE. Deleting the `assert specs` line below kills no test,
    and that is correct rather than a gap: for an empty list the `assert checked`
    further down fires on the same input, so the observable behaviour is identical.
    Both lines stay because they catch DIFFERENT inputs — a non-empty list of specs
    that all declare no pages reaches `assert checked` and not `assert specs`.
    Measured 2026-09-15; recorded so the next reader does not "fix" a survivor by
    writing a test that can only assert on the message text.
    """
    assert specs, "no specs handed in — a loop over nothing passes every assertion"

    checked = 0
    missing = []

    for spec in specs:
        anchor = spec[ "sel" ].split( " " )[ 0 ]
        token  = _selector_source_token( anchor )
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
    _assert_selectors_are_in_their_pages_templates( NORMALIZE_SPECS )


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
    _assert_selectors_are_in_their_pages_templates( NORMALIZE_TABLE_SPECS )


def test_the_template_guard_can_actually_fail():
    """
    Positive control — the REAL checker must reject a right-selector/wrong-page pair.

    ⚠️ Same defect as the source control above, same fix: this used to read the two
    templates and assert on its own comparison, which left mutations of
    `_assert_selectors_are_in_their_pages_templates` unexercised. It now drives the
    checker.

    `#clock` is real and served by notifications, so a spec claiming `login` is the
    wrong-page defect with nothing else wrong — precisely what the source guard
    cannot see.

    Ensures:
        - the checker RAISES on a spec claiming a page whose template lacks it,
          naming the page
        - the checker PASSES on the same selector claiming its real page
    """
    with pytest.raises( AssertionError ) as exc:
        _assert_selectors_are_in_their_pages_templates(
            [ { "sel": "#clock", "pages": ( "login", ) } ]
        )

    assert "login" in str( exc.value ), f"the failure did not name the page: {exc.value}"

    _assert_selectors_are_in_their_pages_templates(
        [ { "sel": "#clock", "pages": ( "notifications", ) } ]
    )


def test_the_template_guard_refuses_an_empty_spec_list():
    """
    An empty spec list raises rather than passing.

    Ensures:
        - AssertionError on an empty list
    """
    with pytest.raises( AssertionError ):
        _assert_selectors_are_in_their_pages_templates( [] )


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


def test_freeze_live_feeds_fails_when_the_container_is_absent():
    """
    A missing feed container fails, naming both repairs.

    "Nothing to freeze" and "the container moved" print identically if the helper
    returns a quiet zero — and the second case sends a live feed into the snapshot.

    Ensures:
        - AssertionError names the container id and both repairs
    """
    page = _StubPage( {} )
    page.evaluate = lambda js, cfg=None: { "container": False, "injected": 0 }

    with pytest.raises( AssertionError ) as exc:
        freeze_live_feeds( page, "notifications" )

    message = str( exc.value )
    assert "commons-recent-activity-entries" in message, f"container not named: {message}"
    assert "_COMMONS_FEED_PAGES" in message, f"the second repair is not named: {message}"


def test_freeze_live_feeds_fails_on_a_short_injection():
    """
    Injecting fewer entries than specified fails rather than passing quietly.

    Ensures:
        - AssertionError when the reported count does not match the spec
    """
    page = _StubPage( {} )
    page.evaluate = lambda js, cfg=None: { "container": True, "injected": 0 }

    with pytest.raises( AssertionError ):
        freeze_live_feeds( page, "notifications" )


def test_freeze_live_feeds_skips_a_page_that_has_no_feed():
    """
    A page outside _COMMONS_FEED_PAGES is skipped, not failed.

    Ensures:
        - returns an empty report
        - the browser is never asked to evaluate anything
    """
    page = _StubPage( {} )
    calls = []
    page.evaluate = lambda js, cfg=None: calls.append( js ) or { "container": True, "injected": 1 }

    assert freeze_live_feeds( page, "login" ) == {}
    assert not calls, "evaluated on a page with no feed"


def test_frozen_commons_entries_carry_no_live_values():
    """
    The injected entries are fixed literals, not anything read from the feed.

    An entry that copied a live value would reintroduce the drift the freeze exists
    to remove, and the snapshot would still move while looking deliberate.

    Ensures:
        - the entry list is non-empty
        - every entry has all four fields, each a non-empty string
        - the frozen time matches a fixed HH:MM literal, so a wall clock cannot
          have leaked into it
    """
    import re

    assert _FROZEN_COMMONS_ENTRIES, "no frozen entries — the freeze would empty the pane"

    for entry in _FROZEN_COMMONS_ENTRIES:
        assert set( entry ) == { "icon", "name", "time", "body" }, f"malformed: {entry}"
        for field, value in entry.items():
            assert isinstance( value, str ) and value, f"{field} is empty in {entry}"

        assert re.fullmatch( r"\d{2}:\d{2}", entry[ "time" ] ), (
            f"frozen time {entry[ 'time' ]!r} is not a fixed HH:MM literal"
        )


def test_the_commons_feed_container_exists_in_the_notifications_template():
    """
    The container the freeze targets is really in the page it claims.

    Same venue-free question the spec guards ask, for the clear-and-inject target —
    which is not a NORMALIZE_SPECS entry and so is not covered by them.

    Ensures:
        - id="commons-recent-activity-entries" is in every page _COMMONS_FEED_PAGES names
    """
    for page in _COMMONS_FEED_PAGES:
        assert 'id="commons-recent-activity-entries"' in _template_text_for_page( page ), (
            f"{page}: the feed container is not in this page's template"
        )


class _PayloadCheckingStubPage:
    """
    A stub that VALIDATES the payload the way Playwright does, instead of ignoring it.

    🔴 THE PLAIN STUB IS WHY THE INT-KEY CRASH SHIPPED. `_StubPage.evaluate` reads
    only the spec list and answers from its own dict, so it returned a healthy report
    for a payload Playwright rejects outright — a fake that ignores its input answers
    the same however the code behaves, and every assertion over it inherits that.
    This one enforces the real constraint: JSON object keys must be strings.
    """

    def __init__( self, rows ):
        self.rows        = rows
        self.seen_payload = None

    def evaluate( self, js, payload=None ):
        self.seen_payload = payload

        for spec in payload:
            for key in spec.get( "columns", {} ):
                if not isinstance( key, str ):
                    raise TypeError(
                        f"arg.value...k: expected string, got {type( key ).__name__} "
                        f"({key!r}) — Playwright refuses this payload"
                    )

        return { spec[ "sel" ]: self.rows.get( spec[ "sel" ], 0 ) for spec in payload }


def test_table_columns_cross_the_browser_boundary_with_string_keys():
    """
    The payload handed to the browser carries STRING column keys, not ints.

    Playwright serialises to JSON and rejects numeric object keys outright, before
    the page is touched — so an int key is not a subtle bug, it is every table
    page's visual test dying at the evaluate() call with no comparison performed.

    Ensures:
        - the real function survives a stub that enforces Playwright's rule
        - every column key in the payload is a string
        - the spec itself still holds ints, so the well-formedness guard keeps
          type-checking them

    Raises:
        - TypeError from the stub if a numeric key ever reaches the boundary again
    """
    page = _PayloadCheckingStubPage( { "#users-tbody tr": 3 } )

    report = normalize_table_columns( page, "admin-users" )

    assert report == { "#users-tbody tr": 3 }

    for spec in page.seen_payload:
        for key in spec[ "columns" ]:
            assert isinstance( key, str ), f"numeric key {key!r} reached the browser"

    # And the SPEC is still ints — the stringification is a boundary concern only.
    shipped = [ s for s in NORMALIZE_TABLE_SPECS if "admin-users" in s[ "pages" ] ][ 0 ]
    assert all( isinstance( k, int ) for k in shipped[ "columns" ] ), (
        "the spec's own keys were mutated; stringify at the boundary, not in the spec"
    )


def test_the_payload_checking_stub_actually_rejects_int_keys():
    """
    Positive control — the stub must refuse what Playwright refuses.

    Without this, the test above could pass against a stub that checks nothing,
    which is precisely the failure that let the int-key crash reach a live run.

    Ensures:
        - the stub raises TypeError on a numeric column key
    """
    page = _PayloadCheckingStubPage( { "x": 1 } )

    with pytest.raises( TypeError ):
        page.evaluate( "() => {}", [ { "sel": "x", "columns": { 5: "a" } } ] )


def test_the_selector_token_pins_its_closing_quote():
    """
    The translated literal includes the CLOSING quote, and that quote is load-bearing.

    Tiffany 💍's nit, 2026-09-15, and it guards a live hole rather than a style
    point: without the trailing quote the token for `#clock` is `id="clock`, which is
    a PREFIX of `id="clock-display"`. A dead selector would then match a different
    element's id and every guard in this file would pass it — the superstring failure
    that made an earlier mutation kill accidental rather than earned.

    Ensures:
        - the token is the exact full literal, equality not containment
        - the token does NOT match a longer id that merely starts the same way
    """
    token = _selector_source_token( "#clock" )

    assert token == 'id="clock"', f"expected the closing quote, got {token!r}"
    assert token not in 'id="clock-display"', (
        f"{token!r} is a prefix of a longer id — the closing quote is missing and "
        f"every selector guard here would pass a dead selector that shares a stem"
    )

    testid = _selector_source_token( '[data-testid="multiplexer-notifications-clock"]' )
    assert testid == 'data-testid="multiplexer-notifications-clock"', (
        f"testid token lost its closing quote: {testid!r}"
    )


def test_table_column_indices_are_within_the_row_they_index():
    """
    Every table spec's column index is plausible for the table it names.

    Tiffany 💍's second nit: the indices were type-checked as ints and otherwise
    unguarded at every tier. An index past the end of a row silently normalizes
    nothing — `row.children[ 99 ]` is undefined and the JS skips it — so the cell
    goes to the snapshot live while the row-count assertion still passes.

    ⚠️ This is a SANITY bound, not a schema: it cannot know a table's real width
    without a browser. It catches a transposition or an off-by-a-lot, not an
    off-by-one. Saying so here beats implying a precision it does not have.

    Ensures:
        - every index is >= 0 and < 32
        - no spec normalizes the same column twice
    """
    for spec in NORMALIZE_TABLE_SPECS:
        indices = list( spec[ "columns" ] )

        assert len( indices ) == len( set( indices ) ), (
            f"{spec[ 'sel' ]} names a column twice: {indices}"
        )

        for index in indices:
            assert 0 <= index < 32, (
                f"{spec[ 'sel' ]} column {index} is outside any plausible row width; "
                f"an index past the end normalizes nothing and fails no assertion"
            )
