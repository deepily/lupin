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
    """
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


def _goto_notifications( page ):
    """Navigate to the classic notifications page and settle the network."""
    page.goto( f"{BASE_URL}/app/notifications?classic=1" )
    page.wait_for_load_state( "networkidle" )


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

        assert logged_in_page.locator( "#task-list-count" ).text_content() == str( OPEN_COUNT )

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
