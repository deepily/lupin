"""
E2E UI tests for the Task List card on the notifications page.

Validates the read-only task-list card ported onto the in-service
`notificationsUI` client (commit 4eeab529): it mounts on notifications.html,
renders owner-grouped rows fetched from GET /api/tasks, surfaces a blocked
row's `blocked_by` + `next_chase_ts`, and degrades gracefully (last-known
rows + a "store unreachable" banner, never blank) when the store read fails.

Seeding strategy: the card is a read-only consumer of GET /api/tasks. There is
no task-store seed helper and the clean_test_db fixture does not touch the
tasks table, so these tests seed the endpoint deterministically via Playwright
route interception (`page.route`). This exercises the real
fetchTaskList -> renderTaskList pipeline in a live browser while keeping the
seeded rows (and the unreachable branch) fully under test control.

Requires:
    - Dev server running on the test venue (:8000) with Testing config
    - Clean test database (via logged_in_page fixture)

Venue: :8000 scheduled — submit via POST /api/test-suite/submit. Do NOT run
against :7999 (monopolize-mode E2E UI suite).
"""

import json

import pytest

from .conftest import BASE_URL


# ---------------------------------------------------------------------------
# Seed payloads
# ---------------------------------------------------------------------------

# Two owners (tiberius · 2, krishna · 1) so grouping is observable. The
# tiberius "blocked" row carries blocked_by + a tz-aware next_chase_ts so the
# blocked-surfacing assertion has real values; blocked-first sort puts it ahead
# of the in_progress row within the group.
SEEDED_TASKS = [
    {
        "id"                  : "t-blocked",
        "title"               : "Wire DM namespace cutover",
        "owner_persona"       : "tiberius",
        "status"              : "blocked",
        "blocked_by"          : "krishna",
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
        "blocked_by"          : None,
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
        "blocked_by"          : None,
        "next_chase_ts"       : None,
        "accountable_manager" : "tiberius",
        "priority"            : "P2",
        "project"             : "lupin",
        "item_class"          : "task",
    },
]


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
# Seeded rows, grouped by owner
# ---------------------------------------------------------------------------

class TestTaskListCardRows:
    """The card renders seeded GET /api/tasks rows, grouped by owner."""

    def test_renders_seeded_rows_grouped_by_owner( self, logged_in_page ):
        """
        Seeded tasks render as owner-grouped table rows.

        Requires:
            - Authenticated session
            - GET /api/tasks seeded with SEEDED_TASKS via route interception

        Ensures:
            - One .task-row per seeded task (3)
            - Owner group headers present: "tiberius · 2" and "krishna · 1"
            - The count badge reflects the open-row total (3)
            - Each seeded title is rendered
        """
        _route_tasks( logged_in_page, { "mode": "ok" } )
        _goto_notifications( logged_in_page )

        logged_in_page.wait_for_selector( "#task-list-container .task-row", state="attached" )

        rows = logged_in_page.locator( "#task-list-container .task-row" )
        assert rows.count() == len( SEEDED_TASKS )

        headers = logged_in_page.locator( "#task-list-container .task-group-header" ).all_text_contents()
        joined  = " ".join( headers )
        assert "tiberius · 2" in joined
        assert "krishna · 1" in joined

        assert logged_in_page.locator( "#task-list-count" ).text_content() == "3"

        table_text = logged_in_page.locator( "#task-list-container" ).text_content()
        for task in SEEDED_TASKS:
            assert task[ "title" ] in table_text

    def test_blocked_row_surfaces_blocked_by_and_chase( self, logged_in_page ):
        """
        The blocked row surfaces blocked_by + a formatted next_chase_ts.

        Requires:
            - Authenticated session
            - GET /api/tasks seeded with a blocked row (blocked_by + next_chase_ts)

        Ensures:
            - A row carries the task-status-blocked accent class
            - Its Blocked-by cell shows the blocker ("krishna")
            - Its Next-chase cell is a parsed timestamp, not the em-dash sentinel
        """
        _route_tasks( logged_in_page, { "mode": "ok" } )
        _goto_notifications( logged_in_page )

        blocked = logged_in_page.locator( "#task-list-container .task-row.task-status-blocked" )
        blocked.first.wait_for( state="attached" )
        assert blocked.count() == 1

        blocked_cell = blocked.locator( ".task-col-blocked" ).text_content()
        assert "krishna" in blocked_cell

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
            - The last-known .task-row rows remain rendered (never blank)
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

        # Last-known rows survive the outage (graceful degradation, never blank).
        rows = logged_in_page.locator( "#task-list-container .task-row" )
        assert rows.count() == len( SEEDED_TASKS )

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
