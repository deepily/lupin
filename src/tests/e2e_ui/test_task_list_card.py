"""
E2E UI tests for the Task List card on the notifications page.

Validates the read-only task-list card ported onto the in-service
`notificationsUI` client (commit 4eeab529): it mounts on notifications.html,
renders owner-grouped rows fetched from GET /api/tasks, surfaces a blocked
row's `blocked_by` + `next_chase_ts`, and degrades gracefully (last-known
rows + a "store unreachable" banner, never blank) when the store read fails.

Two complementary seeding strategies (hardened 2026-06-17 to close a
route-intercept false-pass gap — see below):

1. Route-interception (`page.route`) — the card is a read-only consumer of
   GET /api/tasks, there is no task-store seed helper, and clean_test_db does
   not touch the task_items table, so most tests seed the endpoint
   deterministically in-browser. CRITICAL: the seed now mirrors the REAL
   shapes /api/tasks returns — `blocked_by` is a typed-ref ARRAY
   [{kind, id}] (NOT a string), with null owner_persona / null next_chase_ts
   / varied statuses (queued · in_progress · blocked · done). The original
   seed used string/null blocked_by and never exercised the array path, so a
   render crash (`text.replace is not a function`) on the real array shape
   shipped past a 6/6-green suite: renderTaskList set the count (44) then
   THREW before injecting rows, leaving the container empty (fix 2724b80d).

2. Live, non-intercepted smoke (`TestTaskListCardLiveSmoke`) — seeds REAL
   task_items rows directly into the test DB via the repository model, then
   loads the page with NO route interception so the browser hits the genuine
   GET /api/tasks. This is the layer that would have caught BOTH overnight
   bugs (the missing toolbar entry point 7d169442 AND the array crash
   2724b80d): it exercises real endpoint serialization → real card render and
   asserts `.task-row` count > 0, not merely container presence.

What changed vs. the false-passing original:
  (a) REAL shapes seeded — array blocked_by, null owner, null chase, mixed status.
  (b) The 🗒️ #section-toolbar entry point is DRIVEN (click), not DOM-injected.
  (c) Row RENDER is asserted (`.task-row` count > 0), not just container/section
      presence — a blocked row's blocked_by + next_chase cells are populated.
  (d) A live non-intercepted smoke variant covers real endpoint → DB → render.

Requires:
    - Dev server running on the test venue (:8000) with Testing config
    - Clean test database (via logged_in_page fixture)

Venue: :8000 scheduled — submit via POST /api/test-suite/submit. Do NOT run
against :7999 (monopolize-mode E2E UI suite). The live-smoke variant mutates
the task_items table (seeds + tears down its own rows), reinforcing the :8000
routing.
"""

import json
import re

import pytest

from .conftest import BASE_URL


# ---------------------------------------------------------------------------
# Seed payloads — REAL /api/tasks shapes (route-interception tests)
# ---------------------------------------------------------------------------

# A blocked row's blocked_by is a typed-ref ARRAY in real store rows
# (postgres_models.TaskItem.blocked_by is JSONB [{kind: item|persona|user, id}]).
# The card stringifies each ref to a "kind:id" label and joins with ", ".
# Seeding the genuine array shape is the whole point of the hardening: the old
# string seed bypassed _renderTaskRow's Array.isArray branch and false-passed.
BLOCKED_REFS = [
    { "kind": "item",    "id": "82e4eaf0-7968-47f8-8720-d67f0baeb9e2" },
    { "kind": "persona", "id": "krishna" },
]

# Five rows spanning the real conditions production returns:
#   - tiberius/blocked   : ARRAY blocked_by + tz-aware next_chase_ts (the crash shape)
#   - tiberius/in_progress: EMPTY array blocked_by + null next_chase_ts
#   - krishna/queued     : a second owner so grouping is observable
#   - NULL owner/queued  : must land in the "(Unassigned)" group
#   - tiberius/done      : a TERMINAL row — the card filters it out (not rendered/counted)
SEEDED_TASKS = [
    {
        "id"                  : "t-blocked",
        "title"               : "Wire DM namespace cutover",
        # A non-empty body drives the LIVE (clickable) 📄 detail affordance
        # (design 2026.06.29 row redesign — the overlay renders THIS field).
        "body"                : "Full detail for the DM namespace cutover lives here.",
        "owner_persona"       : "tiberius",
        "status"              : "blocked",
        "blocked_by"          : BLOCKED_REFS,
        "next_chase_ts"       : "2026-06-17T14:30:00+00:00",
        "accountable_manager" : "tiberius",
        "priority"            : "P0",
        "project"             : "lupin",
        "item_class"          : "task",
    },
    {
        "id"                  : "t-active",
        "title"               : "Author task-list E2E",
        # No body → the 📄 is DIMMED in place (disabled / non-clickable, ruling #3).
        "owner_persona"       : "tiberius",
        "status"              : "in_progress",
        "blocked_by"          : [ ],
        "next_chase_ts"       : None,
        "accountable_manager" : "tiberius",
        "priority"            : "P1",
        "project"             : "lupin",
        "item_class"          : "task",
    },
    {
        "id"                  : "t-queued",
        "title"               : "Prune merged-stale worktrees",
        "owner_persona"       : "krishna",
        "status"              : "queued",
        "blocked_by"          : [ ],
        "next_chase_ts"       : None,
        "accountable_manager" : "tiberius",
        "priority"            : "P2",
        "project"             : "lupin",
        "item_class"          : "task",
    },
    {
        "id"                  : "t-unassigned",
        "title"               : "Triage orphaned store rows",
        "owner_persona"       : None,
        "status"              : "queued",
        "blocked_by"          : [ ],
        "next_chase_ts"       : None,
        "accountable_manager" : "tiberius",
        "priority"            : "P3",
        "project"             : "lupin",
        "item_class"          : "task",
    },
    {
        "id"                  : "t-done",
        "title"               : "Closed billing probe",
        "owner_persona"       : "tiberius",
        "status"              : "done",
        "blocked_by"          : [ ],
        "next_chase_ts"       : None,
        "accountable_manager" : "tiberius",
        "priority"            : "P1",
        "project"             : "lupin",
        "item_class"          : "task",
    },
]

# The card renders only OPEN (non-terminal) rows — "done"/"dropped" are filtered
# by isTaskOpenStatus. Four of the five seeded rows are open; the "done" row is
# excluded from both the rendered table and the count badge.
OPEN_TASKS    = [ t for t in SEEDED_TASKS if t[ "status" ] not in ( "done", "dropped" ) ]
DONE_TASK     = next( t for t in SEEDED_TASKS if t[ "status" ] == "done" )
OPEN_COUNT    = len( OPEN_TASKS )   # 4


def _route_tasks( page, state ):
    """
    Install a GET /api/tasks route handler whose behavior follows `state`.

    Requires:
        - page is a Playwright page (route registered BEFORE navigation so the
          card's auto-poll on load is intercepted too)
        - state is a mutable dict with key "mode": "ok" | "unreachable"

    Ensures:
        - mode "ok"          -> 200 { tasks: SEEDED_TASKS, count }
        - mode "unreachable" -> 500 (drives the card's unreachable sentinel)
        - flipping state["mode"] between fetches changes the served response
        - GET /api/tasks/flow-ratio is answered by its OWN route, registered last

    ⚠️ "**/api/tasks*" DOES NOT MATCH /api/tasks/flow-ratio — MEASURED, not read
    off the glob. Playwright compiles `*` to `[^/]*`, so the trailing star stops
    at the slash:

        playwright 1.58.0, playwright._impl._helper.url_matches( None, url, glob )
          "**/api/tasks*"   vs /api/tasks/flow-ratio   -> False
          "**/api/tasks*"   vs /api/tasks?status=open  -> True   (positive control)
          "**/api/tasks/*"  vs /api/tasks/flow-ratio   -> True   (positive control)

    An earlier cut of this docstring claimed the opposite and put the flow-ratio
    body behind an `if` inside this handler, where it was UNREACHABLE: the seed
    never applied, the request went to the live server, and the two header tests
    below were asserting fixture numbers against a real board. Hence a SECOND
    `page.route` on the literal path — registered LAST, because Playwright does
    `self._routes.insert( 0, ... )` and therefore checks the newest handler first.
    """
    def flow_ratio_handler( route ):
        if state[ "mode" ] == "unreachable":
            route.fulfill( status=500, content_type="application/json",
                           body=json.dumps( { "detail": "store down" } ) )
            return
        route.fulfill(
            status       = 200,
            content_type = "application/json",
            body         = json.dumps( state.get( "ratio", {
                "created": 10, "closed": 13, "ratio": 0.77,
                "verdict": "allow", "window_hours": 24
            } ) )
        )

    def handler( route ):
        if state[ "mode" ] == "unreachable":
            route.fulfill( status=500, content_type="application/json",
                           body=json.dumps( { "detail": "store down" } ) )
            return
        route.fulfill(
            status       = 200,
            content_type = "application/json",
            body         = json.dumps( { "tasks": SEEDED_TASKS, "count": len( SEEDED_TASKS ) } )
        )

    page.route( "**/api/tasks*", handler )
    page.route( "**/api/tasks/flow-ratio*", flow_ratio_handler )   # LAST = checked first


def _goto_notifications( page ):
    """Navigate to the classic notifications page and settle the network."""
    page.goto( f"{BASE_URL}/app/notifications?classic=1" )
    page.wait_for_load_state( "networkidle" )


# Measures the open #task-body-overlay's computed position + geometry vs the
# viewport (used by the f7486a9d fixed-centered-modal regression guard).
_OVERLAY_METRICS_JS = """() => {
    const o = document.getElementById( "task-body-overlay" );
    const p = o.querySelector( ".task-body-overlay-content" );
    const cs = getComputedStyle( o );
    const orect = o.getBoundingClientRect();
    const prect = p.getBoundingClientRect();
    return {
        position : cs.position,
        vw       : window.innerWidth,
        vh       : window.innerHeight,
        o_left   : orect.left,
        o_top    : orect.top,
        o_width  : orect.width,
        o_height : orect.height,
        panel_cx : prect.left + prect.width / 2,
    };
}"""


# ---------------------------------------------------------------------------
# Mount
# ---------------------------------------------------------------------------

class TestTaskListCardMount:
    """The card mounts on notifications.html."""

    def test_card_mounts( self, logged_in_page ):
        """
        Task List section + container mount on the notifications page.

        Requires:
            - Authenticated session

        Ensures:
            - #section-task-list and the task-list-container test-id exist in DOM
            - The refresh control is present
        """
        _goto_notifications( logged_in_page )

        assert logged_in_page.locator( "#section-task-list" ).count() > 0
        assert logged_in_page.get_by_test_id( "task-list-container" ).count() > 0
        assert logged_in_page.get_by_test_id( "task-list-refresh-btn" ).count() > 0


# ---------------------------------------------------------------------------
# Toolbar entry point (🗒️) — DRIVE the real button, do NOT DOM-inject the section
# ---------------------------------------------------------------------------

class TestTaskListCardToolbarEntryPoint:
    """
    The 🗒️ section-toolbar button is the card's real entry point (added in
    7d169442 — its absence was the FIRST overnight bug). These tests DRIVE the
    actual button rather than un-hiding the section programmatically, so a
    regression that drops the toolbar wiring fails loudly.
    """

    def test_toolbar_button_present( self, logged_in_page ):
        """
        The 🗒️ task-list toolbar button exists with its data-section wiring.

        Requires:
            - Authenticated session

        Ensures:
            - task-list-toolbar-btn is in the DOM
            - it carries data-section="section-task-list" (the dispatcher key)
        """
        _goto_notifications( logged_in_page )

        btn = logged_in_page.get_by_test_id( "task-list-toolbar-btn" )
        assert btn.count() > 0, "🗒️ task-list toolbar entry point missing (regression of 7d169442)"
        assert btn.get_attribute( "data-section" ) == "section-task-list"

    def test_toolbar_button_toggles_section_and_rows_survive( self, logged_in_page ):
        """
        Clicking the 🗒️ button hides then reveals the section; rows render on reveal.

        The section is shown by default (toolbar btn `active`). We drive the REAL
        button both directions — hide, then reveal — and assert the card renders
        rows through that entry point (not via DOM injection / un-hiding).

        Requires:
            - Authenticated session
            - GET /api/tasks seeded with REAL-shaped rows via route interception

        Ensures:
            - first click adds `section-hidden` (section toggled off)
            - second click removes it (section toggled on) and the seeded OPEN
              rows render beneath the revealed section
        """
        _route_tasks( logged_in_page, { "mode": "ok" } )
        _goto_notifications( logged_in_page )

        # Rows are present on the default-visible section first.
        logged_in_page.wait_for_selector( "#task-list-container .task-row", state="attached" )

        btn     = logged_in_page.get_by_test_id( "task-list-toolbar-btn" )
        section = logged_in_page.locator( "#section-task-list" )
        assert "section-hidden" not in ( section.get_attribute( "class" ) or "" )

        # DRIVE the real button → hide.
        btn.click()
        logged_in_page.wait_for_function(
            "() => document.getElementById( 'section-task-list' ).classList.contains( 'section-hidden' )"
        )

        # DRIVE the real button → reveal, and confirm rows render through the entry point.
        btn.click()
        logged_in_page.wait_for_function(
            "() => !document.getElementById( 'section-task-list' ).classList.contains( 'section-hidden' )"
        )
        logged_in_page.wait_for_selector( "#task-list-container .task-row", state="attached" )
        assert logged_in_page.locator( "#task-list-container .task-row" ).count() == OPEN_COUNT


# ---------------------------------------------------------------------------
# Per-persona accordion (collapse/expand each owner group)
# Plan: src/rnd/v0.1.8/2026.06.17-task-list-accordion/01-design-and-build-plan.md
# ---------------------------------------------------------------------------

# localStorage key + sentinel — the PARITY CONTRACT shared with the TS card.
ACCORDION_KEY        = "lupin.taskList.collapsedOwners"
ACCORDION_UNASSIGNED = "__unassigned__"


class TestTaskListCardAccordion:
    """
    Each owner group header is a collapse/expand accordion bar; the collapsed
    set persists per-persona across reload, with collapse-all / expand-all
    controls in the #section-toolbar.
    """

    def test_groups_render_as_per_owner_tbodies_expanded( self, logged_in_page ):
        """
        Each owner renders as its own <tbody.task-group data-owner> — expanded by default.

        Requires:
            - Authenticated session, seeded rows via route interception

        Ensures:
            - one tbody.task-group per owner (tiberius, krishna, __unassigned__)
            - each header carries role/tabindex/aria-expanded=true + a ▾ chevron
            - first-load default is expanded (no `collapsed` class)
        """
        _route_tasks( logged_in_page, { "mode": "ok" } )
        _goto_notifications( logged_in_page )
        logged_in_page.wait_for_selector( "#task-list-container .task-row", state="attached" )

        groups = logged_in_page.locator( "#task-list-container tbody.task-group" )
        assert groups.count() == 3
        for owner in ( "tiberius", "krishna", ACCORDION_UNASSIGNED ):
            tb = logged_in_page.locator( f'#task-list-container tbody.task-group[data-owner="{owner}"]' )
            assert tb.count() == 1, f"missing per-owner tbody for {owner!r}"
            assert "collapsed" not in ( tb.get_attribute( "class" ) or "" )

        header = logged_in_page.locator(
            '#task-list-container tbody.task-group[data-owner="tiberius"] .task-group-header' )
        assert header.get_attribute( "role" ) == "button"
        assert header.get_attribute( "tabindex" ) == "0"
        assert header.get_attribute( "aria-expanded" ) == "true"
        assert "▾" in header.locator( ".task-group-chevron" ).text_content()

    def test_header_click_collapses_only_that_owner( self, logged_in_page ):
        """
        Clicking an owner header hides ONLY that owner's rows; header + count stay.

        Requires:
            - Authenticated session, seeded rows

        Ensures:
            - the clicked owner's .task-row become hidden; its header stays visible
              with its "owner · N" count; chevron flips to ▸; aria-expanded=false
            - other owners' rows stay visible; the global count badge is unchanged
            - the collapsed owner is persisted to localStorage
        """
        _route_tasks( logged_in_page, { "mode": "ok" } )
        _goto_notifications( logged_in_page )
        logged_in_page.wait_for_selector( "#task-list-container .task-row", state="attached" )

        tib = logged_in_page.locator( '#task-list-container tbody.task-group[data-owner="tiberius"]' )
        kri = logged_in_page.locator( '#task-list-container tbody.task-group[data-owner="krishna"]' )
        header = tib.locator( ".task-group-header" )

        assert tib.locator( ".task-row" ).first.is_visible()
        header.click()
        logged_in_page.wait_for_function(
            "() => document.querySelector('tbody.task-group[data-owner=\"tiberius\"]').classList.contains('collapsed')"
        )

        assert not tib.locator( ".task-row" ).first.is_visible(), "tiberius rows should hide"
        assert header.is_visible(), "header bar stays visible when collapsed"
        assert "tiberius · 2" in header.text_content()
        assert header.get_attribute( "aria-expanded" ) == "false"
        assert "▸" in header.locator( ".task-group-chevron" ).text_content()
        assert kri.locator( ".task-row" ).first.is_visible(), "other owners unaffected"
        assert logged_in_page.locator( "#task-list-count" ).text_content() == f"Live: {OPEN_COUNT}"

        stored = logged_in_page.evaluate( f'JSON.parse( localStorage.getItem( "{ACCORDION_KEY}" ) || "[]" )' )
        assert stored == [ "tiberius" ], f"collapsed owner not persisted; got {stored!r}"

    def test_collapse_state_survives_reload( self, logged_in_page ):
        """
        A collapsed owner stays collapsed after a page reload (localStorage).

        Requires:
            - Authenticated session, seeded rows

        Ensures:
            - collapse tiberius → reload → tiberius renders collapsed (rows hidden)
              while other owners render expanded
        """
        _route_tasks( logged_in_page, { "mode": "ok" } )
        _goto_notifications( logged_in_page )
        logged_in_page.wait_for_selector( "#task-list-container .task-row", state="attached" )

        logged_in_page.locator(
            '#task-list-container tbody.task-group[data-owner="tiberius"] .task-group-header' ).click()
        logged_in_page.wait_for_function(
            "() => document.querySelector('tbody.task-group[data-owner=\"tiberius\"]').classList.contains('collapsed')"
        )

        # Reload — render reads the persisted collapsed set.
        _goto_notifications( logged_in_page )
        logged_in_page.wait_for_selector( "#task-list-container .task-row", state="attached" )

        tib = logged_in_page.locator( '#task-list-container tbody.task-group[data-owner="tiberius"]' )
        assert "collapsed" in ( tib.get_attribute( "class" ) or "" ), "collapse did not survive reload"
        assert not tib.locator( ".task-row" ).first.is_visible()
        assert logged_in_page.locator(
            '#task-list-container tbody.task-group[data-owner="krishna"] .task-row' ).first.is_visible()

    def test_collapse_all_then_expand_all( self, logged_in_page ):
        """
        The #section-toolbar collapse-all / expand-all controls drive every group.

        Requires:
            - Authenticated session, seeded rows

        Ensures:
            - collapse-all: every group collapses; the persisted set holds all owner
              keys incl. the Unassigned sentinel; no .task-row is visible
            - expand-all: no group collapsed; persisted set empty; all rows visible
        """
        _route_tasks( logged_in_page, { "mode": "ok" } )
        _goto_notifications( logged_in_page )
        logged_in_page.wait_for_selector( "#task-list-container .task-row", state="attached" )

        logged_in_page.get_by_test_id( "task-list-collapse-all-btn" ).click()
        logged_in_page.wait_for_function(
            "() => Array.from( document.querySelectorAll('#task-list-container tbody.task-group') )"
            ".every( e => e.classList.contains('collapsed') )"
        )
        assert logged_in_page.locator( "#task-list-container .task-row:visible" ).count() == 0
        stored = sorted( logged_in_page.evaluate( f'JSON.parse( localStorage.getItem( "{ACCORDION_KEY}" ) || "[]" )' ) )
        assert stored == sorted( [ "tiberius", "krishna", ACCORDION_UNASSIGNED ] ), stored

        logged_in_page.get_by_test_id( "task-list-expand-all-btn" ).click()
        logged_in_page.wait_for_function(
            "() => Array.from( document.querySelectorAll('#task-list-container tbody.task-group') )"
            ".every( e => !e.classList.contains('collapsed') )"
        )
        assert logged_in_page.locator( "#task-list-container .task-row:visible" ).count() == OPEN_COUNT
        stored = logged_in_page.evaluate( f'JSON.parse( localStorage.getItem( "{ACCORDION_KEY}" ) || "[]" )' )
        assert stored == [ ], f"expand-all should clear the set; got {stored!r}"

    def test_keyboard_enter_toggles_focused_header( self, logged_in_page ):
        """
        A focused header toggles on Enter (keyboard a11y).

        Requires:
            - Authenticated session, seeded rows

        Ensures:
            - focusing a header + pressing Enter collapses that owner's rows
        """
        _route_tasks( logged_in_page, { "mode": "ok" } )
        _goto_notifications( logged_in_page )
        logged_in_page.wait_for_selector( "#task-list-container .task-row", state="attached" )

        header = logged_in_page.locator(
            '#task-list-container tbody.task-group[data-owner="krishna"] .task-group-header' )
        header.focus()
        logged_in_page.keyboard.press( "Enter" )
        logged_in_page.wait_for_function(
            "() => document.querySelector('tbody.task-group[data-owner=\"krishna\"]').classList.contains('collapsed')"
        )
        assert not logged_in_page.locator(
            '#task-list-container tbody.task-group[data-owner="krishna"] .task-row' ).first.is_visible()


# ---------------------------------------------------------------------------
# Seeded rows, grouped by owner — REAL shapes, RENDER asserted
# ---------------------------------------------------------------------------

class TestTaskListCardRows:
    """The card renders seeded GET /api/tasks rows (real shapes), grouped by owner."""

    def test_renders_seeded_rows_grouped_by_owner( self, logged_in_page ):
        """
        Seeded tasks render as owner-grouped table rows — with REAL shapes.

        This is the core false-pass closer (AC c): the seed carries an ARRAY
        blocked_by + null owner + null chase + a terminal row, and we assert
        rows ACTUALLY RENDER (`.task-row` count), not just that a container is
        present. On the pre-fix card this row count was 0 while the badge said 4.

        Requires:
            - Authenticated session
            - GET /api/tasks seeded with SEEDED_TASKS via route interception

        Ensures:
            - One .task-row per OPEN seeded task (4; the done row is filtered out)
            - Owner group headers present: "tiberius · 2", "krishna · 1", "(Unassigned)"
            - The count badge reflects the OPEN-row total (4)
            - Each OPEN seeded title renders; the terminal "done" title does NOT
        """
        _route_tasks( logged_in_page, { "mode": "ok" } )
        _goto_notifications( logged_in_page )

        logged_in_page.wait_for_selector( "#task-list-container .task-row", state="attached" )

        rows = logged_in_page.locator( "#task-list-container .task-row" )
        assert rows.count() == OPEN_COUNT

        headers = logged_in_page.locator( "#task-list-container .task-group-header" ).all_text_contents()
        joined  = " ".join( headers )
        assert "tiberius · 2" in joined
        assert "krishna · 1" in joined
        assert "(Unassigned)" in joined

        assert logged_in_page.locator( "#task-list-count" ).text_content() == f"Live: {OPEN_COUNT}"

        table_text = logged_in_page.locator( "#task-list-container" ).text_content()
        for task in OPEN_TASKS:
            assert task[ "title" ] in table_text
        # The terminal row is filtered, never rendered.
        assert DONE_TASK[ "title" ] not in table_text

    def test_null_owner_row_lands_in_unassigned_group( self, logged_in_page ):
        """
        A row with null owner_persona renders under the "(Unassigned)" group.

        Requires:
            - Authenticated session
            - GET /api/tasks seeded with a null-owner row via route interception

        Ensures:
            - the "(Unassigned)" group header is present and is the LAST group
            - the null-owner seeded title renders (real-shape null owner handled)
        """
        _route_tasks( logged_in_page, { "mode": "ok" } )
        _goto_notifications( logged_in_page )

        logged_in_page.wait_for_selector( "#task-list-container .task-row", state="attached" )

        headers = logged_in_page.locator( "#task-list-container .task-group-header" ).all_text_contents()
        assert any( "(Unassigned)" in h for h in headers )
        assert "(Unassigned)" in headers[ -1 ], f"Unassigned group should sort last; headers were {headers}"

        table_text = logged_in_page.locator( "#task-list-container" ).text_content()
        assert "Triage orphaned store rows" in table_text

    def test_blocked_row_surfaces_array_blocked_by_and_chase( self, logged_in_page ):
        """
        The blocked row surfaces an ARRAY blocked_by (kind:id labels) + a chase ts.

        This is the regression guard for 2724b80d: blocked_by is the real typed-ref
        ARRAY, and the card must stringify each ref to "kind:id" (not throw on
        `.replace`). The original test seeded the string "krishna" and never hit
        this path.

        Requires:
            - Authenticated session
            - GET /api/tasks seeded with a blocked row whose blocked_by is an
              ARRAY [{kind, id}] + a tz-aware next_chase_ts

        Ensures:
            - A row carries the task-status-blocked accent class
            - Its Blocked-by cell shows BOTH typed refs as "kind:id" labels
              ("item:82e4eaf0…" and "persona:krishna")
            - Its Next-chase cell is a parsed timestamp, not the em-dash sentinel
        """
        _route_tasks( logged_in_page, { "mode": "ok" } )
        _goto_notifications( logged_in_page )

        blocked = logged_in_page.locator( "#task-list-container .task-row.task-status-blocked" )
        blocked.first.wait_for( state="attached" )
        assert blocked.count() == 1

        blocked_cell = blocked.locator( ".task-col-blocked" ).text_content()
        # Each typed ref renders as "kind:id"; the item-ref id is a UUID prefix.
        assert "persona:krishna" in blocked_cell, f"expected stringified persona ref, got {blocked_cell!r}"
        assert "item:82e4eaf0" in blocked_cell,   f"expected stringified item ref, got {blocked_cell!r}"

        chase_cell = blocked.locator( ".task-col-chase" ).text_content().strip()
        assert chase_cell not in ( "", "—" ), f"expected a formatted chase time, got {chase_cell!r}"

    def test_blocked_row_sorts_first_in_group( self, logged_in_page ):
        """
        Within the tiberius owner group the blocked row sorts ahead of in_progress.

        Owner groups render alphabetically (krishna before tiberius), so the
        blocked row is NOT first across the whole table — it is first WITHIN its
        group. Both tiberius rows are contiguous, so asserting the blocked title
        precedes the in_progress title in render order captures the by-status
        within-group sort (blocked rank 0 < in_progress rank 1).

        Requires:
            - Authenticated session, seeded rows

        Ensures:
            - The blocked row's title appears before the in_progress row's title
              in DOM render order
        """
        _route_tasks( logged_in_page, { "mode": "ok" } )
        _goto_notifications( logged_in_page )

        logged_in_page.wait_for_selector( "#task-list-container .task-row", state="attached" )

        titles      = logged_in_page.locator(
            "#task-list-container .task-row .task-col-title"
        ).all_text_contents()
        blocked_idx = titles.index( "Wire DM namespace cutover" )   # tiberius / blocked
        active_idx  = titles.index( "Author task-list E2E" )        # tiberius / in_progress
        assert blocked_idx < active_idx, (
            f"blocked row should precede in_progress within the group; "
            f"order was {titles}"
        )


# ---------------------------------------------------------------------------
# Row redesign 2026.06.29 — leading ID column + title truncation/tooltip +
# 📄 body-overlay (AUGMENT ruling: added alongside the existing columns).
# ---------------------------------------------------------------------------

class TestTaskListRowRedesign:
    """The 8-char ID column, title truncation + tooltip, and 📄 body overlay."""

    def test_id_column_shows_first_8_chars( self, logged_in_page ):
        """
        The NEW leftmost ID column renders the first 8 chars of the row id.

        Requires:
            - Authenticated session, seeded rows
        Ensures:
            - the t-active row (id 't-active', exactly 8 chars) shows 't-active'
              in its .task-col-id cell
        """
        _route_tasks( logged_in_page, { "mode": "ok" } )
        _goto_notifications( logged_in_page )
        logged_in_page.wait_for_selector( "#task-list-container .task-row", state="attached" )

        ids = logged_in_page.locator( "#task-list-container .task-row .task-col-id" ).all_text_contents()
        assert "t-active" in [ i.strip() for i in ids ], f"id column missing first-8 id; got {ids}"

    def test_title_cell_carries_full_title_tooltip( self, logged_in_page ):
        """
        The Title cell carries the FULL title in a `title=` hover-tooltip attr.

        Requires:
            - Authenticated session, seeded rows
        Ensures:
            - a .task-col-title cell's title attribute equals the full seeded title
        """
        _route_tasks( logged_in_page, { "mode": "ok" } )
        _goto_notifications( logged_in_page )
        logged_in_page.wait_for_selector( "#task-list-container .task-row", state="attached" )

        cell = logged_in_page.locator(
            "#task-list-container .task-row .task-col-title", has_text="Wire DM namespace cutover"
        ).first
        assert cell.get_attribute( "title" ) == "Wire DM namespace cutover"

    def test_live_detail_emoji_opens_body_overlay( self, logged_in_page ):
        """
        Clicking a LIVE 📄 opens an overlay rendering the task `body`.

        Requires:
            - Authenticated session; the t-blocked row carries a non-empty body
        Ensures:
            - the overlay appears with the body text; Escape dismisses it
        """
        _route_tasks( logged_in_page, { "mode": "ok" } )
        _goto_notifications( logged_in_page )
        logged_in_page.wait_for_selector( "#task-list-container .task-row", state="attached" )

        # The t-blocked row is the only one with a live (non-dimmed) 📄.
        emoji = logged_in_page.locator(
            "#task-list-container .task-detail-emoji:not(.task-detail-empty)"
        ).first
        emoji.click()

        logged_in_page.wait_for_selector( "#task-body-overlay", state="attached" )
        body = logged_in_page.locator( "#task-body-overlay .task-body-overlay-body" ).text_content()
        assert "DM namespace cutover" in body

        logged_in_page.keyboard.press( "Escape" )
        logged_in_page.wait_for_selector( "#task-body-overlay", state="detached" )

    def test_body_overlay_dismisses_on_backdrop_click( self, logged_in_page ):
        """
        A click on the overlay backdrop (outside the panel) dismisses it.

        Requires:
            - Authenticated session; a live 📄 row
        Ensures:
            - opening then clicking the backdrop removes the overlay
        """
        _route_tasks( logged_in_page, { "mode": "ok" } )
        _goto_notifications( logged_in_page )
        logged_in_page.wait_for_selector( "#task-list-container .task-row", state="attached" )

        logged_in_page.locator(
            "#task-list-container .task-detail-emoji:not(.task-detail-empty)"
        ).first.click()
        logged_in_page.wait_for_selector( "#task-body-overlay", state="attached" )

        # Click the backdrop at a corner, away from the centered content panel.
        logged_in_page.locator( "#task-body-overlay" ).click( position={ "x": 5, "y": 5 } )
        logged_in_page.wait_for_selector( "#task-body-overlay", state="detached" )

    def test_empty_body_emoji_is_dimmed_in_place( self, logged_in_page ):
        """
        A row with no body keeps its 📄 in the column but DIMMED (disabled).

        Requires:
            - Authenticated session; the t-active row has no body
        Ensures:
            - at least one .task-detail-emoji.task-detail-empty is rendered, and
              it carries no data-task-body payload (inert)
        """
        _route_tasks( logged_in_page, { "mode": "ok" } )
        _goto_notifications( logged_in_page )
        logged_in_page.wait_for_selector( "#task-list-container .task-row", state="attached" )

        dimmed = logged_in_page.locator( "#task-list-container .task-detail-emoji.task-detail-empty" )
        assert dimmed.count() >= 1
        assert dimmed.first.get_attribute( "data-task-body" ) is None

    def test_live_body_overlay_computes_fixed_centered_modal( self, logged_in_page ):
        """
        REGRESSION GUARD (bug f7486a9d): the opened 📄 overlay must COMPUTE
        position:fixed and cover the full viewport, centering its content — NOT
        flow to the page foot as a position:static block (the symptom a stale
        task-list.css cache-bust token produced: the overlay div attached fine
        but rendered static because the cached CSS lacked the .task-body-overlay
        rule). This is the computed-style assertion the open/dismiss tests above
        do not make — they would pass even with the overlay dumped at page-foot.

        Requires:
            - Authenticated session; the t-blocked row carries a live 📄
        Ensures:
            - getComputedStyle(#task-body-overlay).position == "fixed"
            - the overlay rect anchors at the viewport origin and spans it (inset:0)
            - the content panel is horizontally centered in the viewport
        """
        _route_tasks( logged_in_page, { "mode": "ok" } )
        _goto_notifications( logged_in_page )
        logged_in_page.wait_for_selector( "#task-list-container .task-row", state="attached" )

        logged_in_page.locator(
            "#task-list-container .task-detail-emoji:not(.task-detail-empty)"
        ).first.click()
        logged_in_page.wait_for_selector( "#task-body-overlay", state="attached" )

        metrics = logged_in_page.evaluate( _OVERLAY_METRICS_JS )

        assert metrics[ "position" ] == "fixed", \
            f"overlay must be position:fixed (regression: stale CSS → static); got {metrics[ 'position' ]!r}"
        # inset:0 → the fixed overlay anchors at the origin (NOT below page content)
        assert abs( metrics[ "o_left" ] ) <= 1 and abs( metrics[ "o_top" ] ) <= 1, \
            f"fixed overlay must anchor at viewport origin, not page-foot; got left={metrics[ 'o_left' ]} top={metrics[ 'o_top' ]}"
        assert abs( metrics[ "o_width" ] - metrics[ "vw" ] ) <= 2 and abs( metrics[ "o_height" ] - metrics[ "vh" ] ) <= 2, \
            "fixed overlay must span the full viewport (inset:0)"
        # flex centering → the content panel sits at the horizontal center
        assert abs( metrics[ "panel_cx" ] - metrics[ "vw" ] / 2 ) <= 2, \
            "overlay content panel must be horizontally centered"

        logged_in_page.keyboard.press( "Escape" )
        logged_in_page.wait_for_selector( "#task-body-overlay", state="detached" )


# ---------------------------------------------------------------------------
# Graceful degradation
# ---------------------------------------------------------------------------

class TestTaskListCardDegradation:
    """When the store read is unreachable the card never blanks."""

    def test_unreachable_replays_last_known_rows_with_banner( self, logged_in_page ):
        """
        Store-unreachable shows a banner AND replays last-known rows.

        Requires:
            - Authenticated session
            - A prior good fetch (seeds _taskListLastGoodTasks), then a 500

        Ensures:
            - The "store unreachable" banner becomes visible
            - The last-known OPEN .task-row rows remain rendered (never blank)
        """
        state = { "mode": "ok" }
        _route_tasks( logged_in_page, state )
        _goto_notifications( logged_in_page )

        # Prime: a good fetch records last-known rows.
        logged_in_page.wait_for_selector( "#task-list-container .task-row", state="attached" )

        # Flip the store to unreachable and force a refresh via the ⟳ control.
        state[ "mode" ] = "unreachable"
        logged_in_page.get_by_test_id( "task-list-refresh-btn" ).click()

        logged_in_page.wait_for_selector(
            "#task-list-container .task-list-unreachable", state="attached"
        )

        banner = logged_in_page.locator( "#task-list-container .task-list-unreachable" )
        assert banner.count() == 1

        # Last-known OPEN rows survive the outage (graceful degradation, never blank).
        rows = logged_in_page.locator( "#task-list-container .task-row" )
        assert rows.count() == OPEN_COUNT

    def test_unreachable_from_cold_shows_banner_not_blank( self, logged_in_page ):
        """
        Unreachable with no prior good fetch shows the banner, never a blank card.

        Requires:
            - Authenticated session
            - GET /api/tasks fails (500) from the very first poll

        Ensures:
            - The unreachable banner is present
            - The container is not empty (carries the banner message)
        """
        _route_tasks( logged_in_page, { "mode": "unreachable" } )
        _goto_notifications( logged_in_page )

        logged_in_page.wait_for_selector(
            "#task-list-container .task-list-unreachable", state="attached"
        )

        assert logged_in_page.locator( "#task-list-container .task-list-unreachable" ).count() == 1
        container_text = logged_in_page.locator( "#task-list-container" ).text_content().strip()
        assert container_text != ""


# ---------------------------------------------------------------------------
# Live, non-intercepted smoke — real endpoint → real DB → real render
# ---------------------------------------------------------------------------

# Seeded rows are tagged with this created_by marker so the teardown can delete
# exactly the rows this suite created (and nothing else in the shared store).
SMOKE_MARKER         = "e2e-tasklist-smoke@sam"
SMOKE_BLOCKED_REF_ID = "82e4eaf0-7968-47f8-8720-d67f0baeb9e2"
SMOKE_BLOCKED_TITLE  = "SMOKE Wire DM namespace cutover"


def _seed_live_task_rows():
    """
    Seed REAL task_items rows directly into the test DB (no API, no interception).

    Mirrors the production row shape so the live GET /api/tasks serializes a
    typed-ref ARRAY blocked_by exactly as the real store does. SAFETY: refuses
    to run against anything but lupin_db_test (mirrors clean_test_db's guard).

    Requires:
        - Server hot-swapped to Testing config (lupin_db_test)

    Ensures:
        - One blocked row (ARRAY blocked_by + tz-aware next_chase_ts), one
          in_progress, one queued, and one terminal (done) row are inserted,
          all tagged created_by=SMOKE_MARKER
        - Returns the list of inserted UUIDs (as strings)
    """
    from datetime import datetime, timezone

    from cosa.rest.db import database as db_module
    from cosa.rest.db.database import get_db
    from cosa.rest.postgres_models import TaskItem

    db_url = str( db_module.engine.url )
    assert "lupin_db_test" in db_url, \
        f"SAFETY: _seed_live_task_rows must only run against lupin_db_test, got: {db_url}"

    specs = [
        {
            "item_class"          : "task",
            "title"               : SMOKE_BLOCKED_TITLE,
            "project"             : "lupin",
            "created_by"          : SMOKE_MARKER,
            "owner_persona"       : "tiberius",
            "accountable_manager" : "tiberius",
            "status"              : "blocked",
            "blocked_by"          : [ { "kind": "item", "id": SMOKE_BLOCKED_REF_ID } ],
            "next_chase_ts"       : datetime( 2026, 6, 17, 14, 30, tzinfo=timezone.utc ),
            "priority"            : "P0",
        },
        {
            "item_class"          : "task",
            "title"               : "SMOKE Author task-list E2E",
            "project"             : "lupin",
            "created_by"          : SMOKE_MARKER,
            "owner_persona"       : "tiberius",
            "accountable_manager" : "tiberius",
            "status"              : "in_progress",
            "blocked_by"          : [ ],
            "priority"            : "P1",
        },
        {
            "item_class"          : "task",
            "title"               : "SMOKE Triage orphaned store rows",
            "project"             : "lupin",
            "created_by"          : SMOKE_MARKER,
            "owner_persona"       : None,
            "accountable_manager" : "tiberius",
            "status"              : "queued",
            "blocked_by"          : [ ],
            "priority"            : "P3",
        },
        {
            "item_class"          : "task",
            "title"               : "SMOKE Closed billing probe",
            "project"             : "lupin",
            "created_by"          : SMOKE_MARKER,
            "owner_persona"       : "tiberius",
            "accountable_manager" : "tiberius",
            "status"              : "done",
            "blocked_by"          : [ ],
            "priority"            : "P1",
        },
    ]

    created_ids = [ ]
    with get_db() as session:
        for spec in specs:
            item = TaskItem( **spec )
            session.add( item )
            session.flush()
            created_ids.append( str( item.id ) )

    return created_ids


def _delete_live_task_rows():
    """
    Delete every task_items row tagged created_by=SMOKE_MARKER (events cascade).

    Ensures:
        - The shared store is restored to its pre-seed state (no test pollution)
    """
    from cosa.rest.db.database import get_db
    from cosa.rest.postgres_models import TaskItem

    with get_db() as session:
        for item in session.query( TaskItem ).filter( TaskItem.created_by == SMOKE_MARKER ).all():
            session.delete( item )


@pytest.fixture( scope="function" )
def live_seeded_tasks():
    """Seed real task_items rows; tear them down after the test (no pollution)."""
    _delete_live_task_rows()   # belt-and-suspenders: clear any leak from a prior crash
    ids = _seed_live_task_rows()
    yield ids
    _delete_live_task_rows()


class TestTaskListCardLiveSmoke:
    """
    Non-intercepted smoke: real DB rows → real GET /api/tasks → real card render.

    This is the layer the original suite lacked. Route interception fully
    controls the JSON, so it cannot catch a mismatch between what the endpoint
    actually serializes (typed-ref ARRAY blocked_by) and what the card expects.
    These tests hit the genuine endpoint and assert rows RENDER.
    """

    def test_live_endpoint_renders_rows( self, logged_in_page, live_seeded_tasks ):
        """
        With NO route interception, the card renders rows from the live endpoint.

        Requires:
            - Authenticated session
            - Real task_items rows seeded into lupin_db_test (live_seeded_tasks)

        Ensures:
            - GET /api/tasks is NOT intercepted (real serialization path)
            - `.task-row` count > 0 (the assertion that would have caught both bugs)
            - the seeded blocked title renders (real array blocked_by survived render)
        """
        _goto_notifications( logged_in_page )

        logged_in_page.wait_for_selector( "#task-list-container .task-row", state="attached" )
        rows = logged_in_page.locator( "#task-list-container .task-row" )
        assert rows.count() > 0, "live endpoint produced 0 rendered rows (the false-pass symptom)"

        table_text = logged_in_page.locator( "#task-list-container" ).text_content()
        assert SMOKE_BLOCKED_TITLE in table_text

    def test_live_blocked_row_renders_array_blocked_by( self, logged_in_page, live_seeded_tasks ):
        """
        The live blocked row's ARRAY blocked_by renders as a kind:id label.

        This is the end-to-end proof of the 2724b80d fix on the REAL path:
        the DB stores a JSONB array, the endpoint serializes it as an array,
        and the card stringifies it to "item:<uuid-prefix>" without throwing.

        Requires:
            - Authenticated session
            - live_seeded_tasks (one blocked row with an item-typed ref)

        Ensures:
            - exactly one blocked-accent row is present
            - its Blocked-by cell shows the "item:<id>" label (array path exercised)
            - its Next-chase cell is a formatted timestamp, not the em-dash sentinel
        """
        _goto_notifications( logged_in_page )

        blocked = logged_in_page.locator( "#task-list-container .task-row.task-status-blocked" )
        blocked.first.wait_for( state="attached" )

        # Locate the specific seeded blocked row by its title cell, then read its
        # blocked_by / chase cells (other store rows may also be blocked).
        seeded = blocked.filter( has_text=SMOKE_BLOCKED_TITLE )
        assert seeded.count() == 1, "seeded blocked row not found among rendered blocked rows"

        blocked_cell = seeded.locator( ".task-col-blocked" ).text_content()
        assert f"item:{SMOKE_BLOCKED_REF_ID}" in blocked_cell, \
            f"expected stringified item ref, got {blocked_cell!r}"

        chase_cell = seeded.locator( ".task-col-chase" ).text_content().strip()
        assert chase_cell not in ( "", "—" ), f"expected a formatted chase time, got {chase_cell!r}"


class TestTaskListHeaderFlowRatio:
    """
    The closed-vs-new ratio in the task-list header (2026-09-01).

    Rick's durable replacement for the ticket moratorium he declared by voice:
    "It's way too easy for you guys to add tickets to the list and way too hard to
    get them removed." The gate refuses a create; THIS is the half he can see.

    🔴 THESE TWO TESTS PIN THE HEADER'S EXACT COPY, ON PURPOSE, AND THAT MAKES THEM
    THE ONES TO EDIT WHEN THE COPY CHANGES. Deliberate: somebody must own the
    wording, and a mocked test with a fixed payload is the cheap place to own it.

    ⇒ THAT SHORTENING HAS LANDED (Rick, 2026-09-01, commit 3919a1ea). The bar reads
    "Gate: 77%" and the long "Closed vs New Ratio (24hrs)" form moved to the hover
    title. The assertions below were updated with it. Change the strings here to
    whatever you ship; do not weaken them to a substring match, or nothing anywhere
    pins the wording and a blank label passes every test we have.

    ⚠️ AN ASSERTION IS NOT THE ONLY THING THAT PINS THE COPY. Each test WAITS on the
    clause before reading it, and that wait names a word too. When the label changed,
    the assertions here were updated and BOTH waits were left polling for "Ratio" — a
    word the bar no longer contains. They would not have failed on the assertion; they
    would have hung until the wait timed out, reporting a timeout rather than the copy
    change that caused it. Fixed 2026-09-01. If you edit the copy again, grep this file
    for the OLD word rather than only re-reading the asserts.
    """

    def test_header_shows_the_ratio_with_its_window( self, logged_in_page ):
        """
        The header renders the ratio AND the window that produced it.

        Requires:
            - Authenticated session, /api/tasks and /api/tasks/flow-ratio seeded

        Ensures:
            - #task-list-count carries the LABELLED live count, not a bare integer
            - #task-list-flow-ratio carries the ratio as a PERCENT — "Gate: 77%",
              not "0.77" — because the bar and the threshold slider must read in
              one unit rather than asking the operator to convert in their head
            - the window is still checkable, but from the HOVER title now: the same
              board reads 77% over 24h and 110% over 168h, so a ratio without its
              window cannot be checked, and shortening the bar moved it rather
              than dropping it
        """
        _route_tasks( logged_in_page, { "mode": "ok" } )
        _goto_notifications( logged_in_page )

        logged_in_page.wait_for_selector( "#task-list-container .task-row", state="attached" )
        logged_in_page.wait_for_function(
            "() => document.getElementById( 'task-list-flow-ratio' ).textContent.includes( 'Gate' )"
        )

        assert logged_in_page.locator( "#task-list-count" ).text_content() == f"Live: {OPEN_COUNT}"

        ratio_text = logged_in_page.locator( "#task-list-flow-ratio" ).text_content()
        # Updated 2026-09-01 for Rick's shortened header: the visible bar reads
        # "Gate: 77%", and the long "Closed vs New Ratio (24hrs)" form moved to the
        # hover text. PERCENT, not hundredths — 0.77 renders as 77%.
        assert "Gate: 77%" in ratio_text, ratio_text
        assert "0.77" not in ratio_text, "hundredths leaked into the percent header"

    def test_a_window_with_no_closures_shows_infinity_not_a_zero( self, logged_in_page ):
        """
        created > 0 with closed == 0 renders ∞, never a number.

        A window in which NOTHING was closed is the worst case. Rendering it as "0%"
        would read as the BEST, which is why the endpoint sends ratio:null rather than
        a sentinel number.

        ⚠️ THIS TEST USED TO ASSERT AN EM DASH AND ITS PREMISE WAS WRONG, not just its
        string. The 2026-09-01 percent rewrite splits what this conflated: nothing
        closed WITH rows created is ∞ — the honest rendering of a divide-by-zero — while
        an idle window that created nothing either is an em dash. A big number like 999%
        would be a lie carrying a number's authority; so would folding both cases into
        one dash.

        Ensures:
            - the clause shows ∞ for the divide-by-zero case
            - "0%" and "0.00" appear nowhere
        """
        _route_tasks( logged_in_page, {
            "mode"  : "ok",
            "ratio" : { "created": 4, "closed": 0, "ratio": None,
                        "verdict": "refuse", "window_hours": 24 },
        } )
        _goto_notifications( logged_in_page )

        logged_in_page.wait_for_function(
            "() => document.getElementById( 'task-list-flow-ratio' ).textContent.includes( 'Gate' )"
        )
        ratio_text = logged_in_page.locator( "#task-list-flow-ratio" ).text_content()
        assert "\u221e" in ratio_text, ratio_text
        assert "0%" not in ratio_text and "0.00" not in ratio_text, \
            "an unmeasurable ratio must never render as a number"

    def test_an_idle_window_shows_an_em_dash_not_infinity( self, logged_in_page ):
        """
        created == 0 AND closed == 0 is IDLE, and idle is not failing.

        The twin of the test above, and the reason ∞ alone is not enough: a quiet board
        that filed nothing has no ratio to report, but it has not failed at anything.
        Showing ∞ there would read as "catastrophically behind" on the calmest possible
        day.
        """
        _route_tasks( logged_in_page, {
            "mode"  : "ok",
            "ratio" : { "created": 0, "closed": 0, "ratio": None,
                        "verdict": "idle", "window_hours": 24 },
        } )
        _goto_notifications( logged_in_page )

        logged_in_page.wait_for_function(
            "() => document.getElementById( 'task-list-flow-ratio' ).textContent.includes( 'Gate' )"
        )
        ratio_text = logged_in_page.locator( "#task-list-flow-ratio" ).text_content()
        assert "\u2014" in ratio_text, ratio_text
        assert "\u221e" not in ratio_text, "an idle window is not a failing window"


def _payload_digest( body ):
    """
    The fields that decide what the header should say, for an assertion message.

    🔴 WHY THIS EXISTS. This test failed on 2026-09-01 and could not answer for itself:
    it asserted only `window_hours`, so when a reviewer asked what `ratio`, `created` and
    `closed` had been, the log did not know — and the run was gone. A live test that does
    not record the payload it judged forces the next reader to re-run it, by which time
    the board has moved and the answer is about a different moment.

    Requires:
        - body is the decoded /api/tasks/flow-ratio payload, or None

    Ensures:
        - returns a short one-line digest naming ratio / created / closed / verdict
        - never raises, including on a None or partial body — a diagnostic that can fail
          takes the real failure's message down with it
    """
    if not isinstance( body, dict ):
        return f"payload={body!r}"
    fields = ( "ratio", "created", "closed", "verdict", "window_hours" )
    return " ".join( f"{k}={body.get( k )!r}" for k in fields )


class TestTaskListHeaderFlowRatioLive:
    """
    The ratio header against the REAL endpoint, with NO route mock (2026-09-01).

    WHY THIS CLASS EXISTS. `GET /api/tasks/flow-ratio` shipped registered BELOW
    `GET /api/tasks/{task_id}`. FastAPI matches in registration order, so the
    literal path was swallowed by its parameterised sibling and answered 422 for
    as long as it existed. Three tests were nominally proving that endpoint and
    all three were blind to it:

      · test_flow_ratio_endpoint.py     calls the handler, so ordering never applies
      · task_list_panel.test.ts         renders a hand-built payload, no HTTP at all
      · TestTaskListHeaderFlowRatio     `page.route`s this very path — it faked the
                                        exact call that was broken

    The client hides the failure BY DESIGN: `fetchFlowRatio` returns null on any
    non-2xx and `_renderFlowRatio` writes an empty string, so a broken endpoint
    and a quiet board render identically. Nothing short of driving the real wire
    can tell them apart, which is why this class mocks nothing.

    ⚠️ IT ASSERTS THE WINDOW AND THE SHAPE, NEVER THE DIGITS. The ratio is live
    state — the fleet files and closes rows while the suite runs — so an exact
    number would be flaky for a reason that has nothing to do with the defect.
    `window_hours` is a server constant and cannot drift.
    """

    def test_the_app_s_own_fetch_of_the_real_flow_ratio_answers_200( self, logged_in_page ):
        """
        The page's OWN request to the real endpoint comes back 200, not 422.

        Requires:
            - Authenticated session (logged_in_page)
            - NO page.route anywhere in this test — the wire is the subject

        Ensures:
            - the browser actually issued GET /api/tasks/flow-ratio (an absent
              request fails LOUDLY rather than passing vacuously)
            - it answered 200
            - a 401 is called out as an AUTH failure, distinct from the 422
              routing defect — otherwise a broken fixture reads as the bug and
              this guard reports on the auth layer instead of the route table

        RED ON REVERT: move the `/tasks/flow-ratio` registration in
        `src/cosa/rest/routers/tasks.py` back below `/tasks/{task_id}` and the
        observed status becomes 422.
        """
        seen: list[ dict ] = []

        def _record( response ):
            if "/api/tasks/flow-ratio" in response.url:
                seen.append( { "status": response.status, "url": response.url } )

        logged_in_page.on( "response", _record )
        _goto_notifications( logged_in_page )

        # The card fetches the ratio on its first tick; wait for the wire, not a
        # fixed sleep. An empty `seen` here means the request was never issued —
        # which is a failure of this test's premise and must not read as a pass.
        logged_in_page.wait_for_function(
            "() => !!document.getElementById( 'task-list-flow-ratio' )"
        )
        logged_in_page.wait_for_timeout( 2000 )

        assert seen, (
            "the page never requested /api/tasks/flow-ratio — this guard proves "
            "nothing until it does; check the card mounted and its first tick ran"
        )

        statuses = [ r[ "status" ] for r in seen ]
        assert 401 not in statuses, (
            f"AUTH failed, not routing — statuses {statuses}. This guard is about the "
            f"route table; a 401 means it never got far enough to measure that."
        )
        assert all( s == 200 for s in statuses ), (
            f"expected every /api/tasks/flow-ratio response to be 200, got {statuses}. "
            f"422 is the registration-order defect: the literal path parked below "
            f"/api/tasks/{{task_id}} and was swallowed by it."
        )

    def test_the_real_payload_reaches_the_rendered_header( self, logged_in_page ):
        """
        The clause in the header is the one the LIVE endpoint just produced.

        The status check above proves the endpoint answers. This proves the answer
        travelled endpoint → fetchFlowRatio → _formatFlowRatio → the DOM, which is
        the leg no unit or TypeScript test can reach.

        Requires:
            - Authenticated session, NO route mock

        Ensures:
            - the live payload carries window_hours (without it the client renders
              an empty clause and this test would be asserting nothing)
            - #task-list-flow-ratio is NON-EMPTY and names that same window
            - it carries a 2dp number or the em dash — never "0.00" standing in for
              an unmeasurable window
        """
        _goto_notifications( logged_in_page )

        payload = logged_in_page.evaluate(
            """async () => {
                const r = await window.notificationsUI.authedFetch( "/api/tasks/flow-ratio" );
                return { status: r.status, body: r.ok ? await r.json() : null };
            }"""
        )

        assert payload[ "status" ] == 200, \
            f"live endpoint answered {payload['status']} — see the status guard above"

        body = payload[ "body" ]
        assert isinstance( body.get( "window_hours" ), int ), (
            f"live payload has no integer window_hours ({body!r}); the client renders "
            f"an EMPTY clause in that case, so the assertion below would pass on a "
            f"header that shows nothing"
        )

        logged_in_page.wait_for_function(
            "() => { const e = document.getElementById( 'task-list-flow-ratio' );"
            "        return e && e.textContent.includes( 'Gate' ); }"
        )
        ratio_text = logged_in_page.locator( "#task-list-flow-ratio" ).text_content()

        # ⚠️ ASSERTS THE PROPERTY, NOT THE COPY. This test's job is "the live payload
        # reached the DOM" — it is NOT the place to pin the header's wording or the
        # number's format. Rick is actively shortening this label and moving the value to
        # percent (2026-09-01), and an E2E that reddens on a copy edit is a brake on the
        # people editing the copy, not a guard on the wire. The exact strings ARE pinned,
        # deliberately, in the mocked TestTaskListHeaderFlowRatio above and in the
        # TypeScript unit tier — the right altitude for wording.
        #
        # What must hold whatever the copy says: the window the endpoint just returned
        # appears in the header, and some number does. Both are properties of the payload
        # having travelled, and neither cares how it is spelled.
        # ⚠️ THE WINDOW LEFT THE VISIBLE BAR on 2026-09-01 — Rick's shortening moved the
        # long "Closed vs New Ratio (Nhrs)" form into the hover text, so asserting it in
        # textContent would now fail for a reason that has nothing to do with the wire.
        # Read it where it actually lives; if the title is absent, that IS a finding.
        long_form = logged_in_page.locator( "#task-list-flow-ratio" ).get_attribute( "title" ) or ""
        assert str( body[ "window_hours" ] ) in ( ratio_text + long_form ), (
            f"neither the header clause {ratio_text!r} nor its hover text {long_form!r} "
            f"carries the window the live endpoint returned ({body['window_hours']}) — "
            f"the payload did not reach the DOM. Payload: {_payload_digest( body )}"
        )

        # 🔴 AN EM-DASH IS THE CORRECT RENDER FOR AN IDLE WINDOW, AND THIS ASSERTION USED
        # TO CALL IT A DEFECT. It read `assert ratio_text.strip() and re.search( r"\d", … )`
        # unconditionally, so it demanded a DIGIT whatever the payload said. Measured
        # 2026-09-01: `:8000` answers `{"created": 0, "closed": 0, "ratio": null,
        # "verdict": "idle", "window_hours": 24}` because it runs against `lupin_db_test`,
        # which is empty — so the header correctly shows " · Gate: —" and this test could
        # NEVER pass in the venue it is routed to. `:7999`, for contrast, answers
        # `created 2, closed 17, ratio 0.12, verdict allow` and renders a number.
        #
        # The failure message above it already named the ambiguity — "a broken endpoint and
        # a quiet board both render empty" — and then asserted straight through it. Naming a
        # trap in the message you print is not the same as handling it in the predicate.
        #
        # ⚠️ WHICH BRANCH APPLIES IS DECIDED BY THE PAYLOAD, NOT BY THE VENUE. Keying this
        # on "is this :8000" would go wrong the first time the test database has rows in it.
        idle = body.get( "ratio" ) is None and body.get( "created" ) == 0

        if idle:
            assert "—" in ratio_text or "-" in ratio_text, (
                f"the live payload is IDLE ({_payload_digest( body )}) so the header must "
                f"render a dash, and it rendered {ratio_text!r} instead. A number here would "
                f"mean the client invented one for a window with nothing in it."
            )
        else:
            assert ratio_text.strip() and re.search( r"\d", ratio_text ), (
                f"header clause {ratio_text!r} carries no value, but the live payload is NOT "
                f"idle ({_payload_digest( body )}) — it has a ratio and a non-zero created "
                f"count, so a number was owed and none arrived. This is the case the test "
                f"exists for: the wire answered and the DOM did not show it."
            )
