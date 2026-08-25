"""
E2E UI tests for the Epic Board accordion on the notifications page.

Plan: src/rnd/v0.2.0/2026.08.24-epic-accordion-mini-plan.md

The Epic Board is the MACRO twin of the Task List card: the SAME rows, grouped
on `correlation_key` ("epic:<slug>") instead of on `owner_persona`. Rick toggles
between the two to move between "who owes what" and "what are we trying to
finish".

What these tests pin, in the order the plan's definition-of-done lists it:
  1. The section mounts BELOW the task list and renders epic-grouped rows.
  2. The 🗂️ toolbar button toggles it — and, critically, lands clear of the
     `.task-accordion-btn` pair so collapse-all still drives the TASK LIST.
     That adjacency is the one trap the plan flags by name, and a DOM test is
     the only thing that catches it: both buttons look fine in isolation.
  3. Groups expand on click and the choice survives a reload.
  4. The drift group renders rather than being silently dropped.
  5. The row total across all epic groups MATCHES the task list's row total —
     two views of one fetch cannot disagree about which rows exist.
  6. NO second poll: exactly one GET /api/tasks serves both panes.

Seeding is by route-interception, mirroring test_task_list_card.py: the board is
a read-only consumer, and the shapes seeded here are the REAL ones /api/tasks
returns — `blocked_by` as a typed-ref ARRAY, `correlation_key` present, absent,
AND overwritten by a non-epic key (the respawn-adoption shape that a plain
truthiness check would misfile).

Requires:
    - Dev server running on the test venue (:8000) with Testing config
    - Clean test database (via logged_in_page fixture)

Venue: :8000 scheduled — submit via POST /api/test-suite/submit.
"""

import json

import pytest

from .conftest import BASE_URL


# ---------------------------------------------------------------------------
# Seed payloads — REAL /api/tasks shapes
# ---------------------------------------------------------------------------

# Three epics of DIFFERENT sizes so group ordering (biggest first) is
# observable, plus the two drift shapes and one row blocked on Rick.
SEEDED_TASKS = [
    {
        "id"                  : "e1000000-0000-0000-0000-000000000001",
        "title"               : "Block the network in the unit tier",
        "body"                : "",
        "owner_persona"       : "tiberius",
        "status"              : "blocked",
        "blocked_by"          : [ { "kind": "item", "id": "82e4eaf0-7968-47f8-8720-d67f0baeb9e2" } ],
        "next_chase_ts"       : "2026-08-25T14:30:00+00:00",
        "accountable_manager" : "tiberius",
        "priority"            : "P1",
        "project"             : "lupin",
        "item_class"          : "task",
        "correlation_key"     : "epic:seal-the-test-tier",
    },
    {
        "id"                  : "e1000000-0000-0000-0000-000000000002",
        "title"               : "Widen the coverage frame",
        "owner_persona"       : "krishna",
        "status"              : "queued",
        "blocked_by"          : [ ],
        "next_chase_ts"       : None,
        "accountable_manager" : "tiberius",
        "priority"            : "P2",
        "project"             : "lupin",
        "item_class"          : "task",
        "correlation_key"     : "epic:seal-the-test-tier",
    },
    {
        "id"                  : "e1000000-0000-0000-0000-000000000003",
        "title"               : "Audit the skipped tests",
        "owner_persona"       : "krishna",
        "status"              : "in_progress",
        "blocked_by"          : [ ],
        "next_chase_ts"       : None,
        "accountable_manager" : "tiberius",
        "priority"            : "P2",
        "project"             : "lupin",
        "item_class"          : "task",
        "correlation_key"     : "epic:seal-the-test-tier",
    },
    {
        # Blocked on RICK — drives the ⏳ highlight section. It must ALSO stay
        # under its own epic; the plan calls this a highlight, not a move.
        "id"                  : "e1000000-0000-0000-0000-000000000004",
        "title"               : "Rick can see his own board",
        "owner_persona"       : "tiberius",
        "status"              : "blocked",
        "blocked_by"          : [ { "kind": "user", "id": "rick" } ],
        "next_chase_ts"       : "2026-08-25T09:00:00+00:00",
        "accountable_manager" : "tiberius",
        "priority"            : "P0",
        "project"             : "lupin",
        "item_class"          : "decision",
        "correlation_key"     : "epic:board-visibility",
    },
    {
        # DRIFT shape 1: minted with NO correlation_key at all.
        "id"                  : "e1000000-0000-0000-0000-000000000005",
        "title"               : "Minted without an epic",
        "owner_persona"       : None,
        "status"              : "queued",
        "blocked_by"          : [ ],
        "next_chase_ts"       : None,
        "accountable_manager" : "tiberius",
        "priority"            : "P2",
        "project"             : "lupin",
        "item_class"          : "task",
        "correlation_key"     : None,
    },
    {
        # DRIFT shape 2: the key exists but is NOT an epic (respawn adoption
        # overwrote it). A truthiness check would file this under its own group.
        "id"                  : "e1000000-0000-0000-0000-000000000006",
        "title"               : "Key overwritten by a respawn",
        "owner_persona"       : "krishna",
        "status"              : "queued",
        "blocked_by"          : [ ],
        "next_chase_ts"       : None,
        "accountable_manager" : "tiberius",
        "priority"            : "P1",
        "project"             : "lupin",
        "item_class"          : "task",
        "correlation_key"     : "cc-task:respawn-adoption",
    },
    {
        # TERMINAL — filtered out of BOTH panes.
        "id"                  : "e1000000-0000-0000-0000-000000000007",
        "title"               : "Closed already",
        "owner_persona"       : "tiberius",
        "status"              : "done",
        "blocked_by"          : [ ],
        "next_chase_ts"       : None,
        "accountable_manager" : "tiberius",
        "priority"            : "P1",
        "project"             : "lupin",
        "item_class"          : "task",
        "correlation_key"     : "epic:seal-the-test-tier",
    },
]

EPIC_STORIES = {
    "_README"                 : "Hand-maintained.",
    "epic:seal-the-test-tier" : {
        "title" : "Seal the test tier",
        "story" : "A green run does not mean what it says.",
    },
    # board-visibility is DELIBERATELY absent — it must render de-slugged.
}

OPEN_TASKS  = [ t for t in SEEDED_TASKS if t[ "status" ] not in ( "done", "dropped" ) ]
OPEN_COUNT  = len( OPEN_TASKS )   # 6
EPIC_COUNT  = 2                   # seal-the-test-tier + board-visibility
DRIFT_COUNT = 2


def _route_tasks( page, state ):
    """
    Install GET /api/tasks + GET /api/epic-stories route handlers.

    Requires:
        - page is a Playwright page (routes registered BEFORE navigation so the
          card's auto-poll on load is intercepted too)
        - state is a mutable dict with key "mode": "ok" | "unreachable", and an
          integer "task_calls" the handler increments

    Ensures:
        - mode "ok"          -> 200 { tasks: SEEDED_TASKS, count }
        - mode "unreachable" -> 500
        - state["task_calls"] counts every GET /api/tasks the page makes, which
          is what proves ONE fetch feeds BOTH panes
    """
    def tasks_handler( route ):
        state[ "task_calls" ] = state.get( "task_calls", 0 ) + 1
        if state[ "mode" ] == "unreachable":
            route.fulfill( status=500, content_type="application/json",
                           body=json.dumps( { "detail": "store down" } ) )
            return
        route.fulfill(
            status       = 200,
            content_type = "application/json",
            body         = json.dumps( { "tasks": SEEDED_TASKS, "count": len( SEEDED_TASKS ) } )
        )

    def stories_handler( route ):
        state[ "story_calls" ] = state.get( "story_calls", 0 ) + 1
        route.fulfill(
            status       = 200,
            content_type = "application/json",
            body         = json.dumps( { "stories": EPIC_STORIES, "count": 1 } )
        )

    page.route( "**/api/tasks*", tasks_handler )
    page.route( "**/api/epic-stories*", stories_handler )


def _goto_notifications( page ):
    """Navigate to the classic notifications page and settle the network."""
    page.goto( f"{BASE_URL}/app/notifications?classic=1" )
    page.wait_for_load_state( "networkidle" )


def _seeded_page( page, mode="ok" ):
    """Route-seed, navigate, and wait for the epic board's first render."""
    state = { "mode": mode, "task_calls": 0, "story_calls": 0 }
    _route_tasks( page, state )
    _goto_notifications( page )
    if mode == "ok":
        page.wait_for_selector( "#epic-board-container tbody.epic-group", state="attached" )
    return state


# ---------------------------------------------------------------------------


class TestEpicBoardMount:
    """The section exists, sits below the task list, and renders."""

    def test_section_mounts_with_its_controls( self, logged_in_page ):
        """
        Ensures:
            - #section-epic-board, its container, and its three controls exist
        """
        _goto_notifications( logged_in_page )

        assert logged_in_page.locator( "#section-epic-board" ).count() > 0
        assert logged_in_page.get_by_test_id( "epic-board-container" ).count() > 0
        assert logged_in_page.get_by_test_id( "epic-board-refresh-btn" ).count() > 0
        assert logged_in_page.get_by_test_id( "epic-board-collapse-all-btn" ).count() > 0
        assert logged_in_page.get_by_test_id( "epic-board-expand-all-btn" ).count() > 0

    def test_section_sits_immediately_below_the_task_list( self, logged_in_page ):
        """
        Rick's ask was for an accordion "immediately underneath of the task
        list" so he can toggle between them without hunting. Position is the
        feature here, not decoration.

        Ensures:
            - #section-epic-board is the NEXT sibling of #section-task-list
        """
        _goto_notifications( logged_in_page )

        next_id = logged_in_page.evaluate(
            """() => {
                const tl = document.getElementById( "section-task-list" );
                return tl && tl.nextElementSibling ? tl.nextElementSibling.id : null;
            }"""
        )
        assert next_id == "section-epic-board"

    def test_rows_render_grouped_by_epic( self, logged_in_page ):
        """
        Ensures:
            - one <tbody.epic-group> per epic, plus the drift + on-Rick groups
            - the epic count badge reports EPICS (the macro unit), not rows
        """
        _seeded_page( logged_in_page )

        keys = logged_in_page.eval_on_selector_all(
            "#epic-board-container tbody.epic-group[data-epic]",
            "els => els.map( e => e.dataset.epic )"
        )
        assert "epic:seal-the-test-tier" in keys
        assert "epic:board-visibility" in keys
        assert "__drift__" in keys
        assert "__on_rick__" in keys

        assert logged_in_page.locator( "#epic-board-count" ).inner_text() == str( EPIC_COUNT )

    def test_a_known_epic_shows_its_story_and_an_unknown_one_de_slugs( self, logged_in_page ):
        """
        A missing story entry is a NUDGE, never an error (plan §5 step 3).

        Ensures:
            - the epic WITH a story renders its hand-written title + story line
            - the epic WITHOUT one renders its de-slugged key and no story row
        """
        _seeded_page( logged_in_page )

        board = logged_in_page.locator( "#epic-board-container" )
        assert "Seal the test tier" in board.inner_text()
        assert "A green run does not mean what it says." in board.inner_text()
        # board-visibility has no entry → de-slugged, and still rendered.
        assert "board visibility" in board.inner_text()


class TestEpicBoardToolbarEntryPoint:
    """
    The 🗂️ button — and the adjacency trap the plan flags.

    The two `.task-accordion-btn` controls are deliberately NOT `.toolbar-btn`
    and carry NO `data-section`; dropping a new button between them is the
    obvious way to break collapse-all, and nothing about either button LOOKS
    wrong when it happens.
    """

    def test_toolbar_button_present_and_is_a_section_toggle( self, logged_in_page ):
        _goto_notifications( logged_in_page )

        btn = logged_in_page.get_by_test_id( "epic-board-toolbar-btn" )
        assert btn.count() == 1
        assert btn.get_attribute( "data-section" ) == "section-epic-board"
        assert "toolbar-btn" in ( btn.get_attribute( "class" ) or "" )

    def test_button_lands_AFTER_the_task_list_button( self, logged_in_page ):
        _goto_notifications( logged_in_page )

        order = logged_in_page.evaluate(
            """() => Array.from( document.querySelectorAll( "#section-toolbar .toolbar-btn" ) )
                          .map( b => b.dataset.section )"""
        )
        assert order.index( "section-epic-board" ) == order.index( "section-task-list" ) + 1

    def test_the_task_accordion_pair_is_STILL_adjacent( self, logged_in_page ):
        """
        THE TRAP. The collapse-all / expand-all pair must remain immediate
        siblings with nothing wedged between them.

        Ensures:
            - #task-list-expand-all is the NEXT sibling of #task-list-collapse-all
            - neither has acquired a data-section (they are actions, not toggles)
        """
        _goto_notifications( logged_in_page )

        result = logged_in_page.evaluate(
            """() => {
                const c = document.getElementById( "task-list-collapse-all" );
                const n = c ? c.nextElementSibling : null;
                return {
                    nextId       : n ? n.id : null,
                    collapseSect : c ? c.dataset.section || null : "MISSING",
                    expandSect   : n ? n.dataset.section || null : "MISSING",
                };
            }"""
        )
        assert result[ "nextId" ] == "task-list-expand-all", \
            "a button was wedged between the task-list accordion pair — collapse-all is broken"
        assert result[ "collapseSect" ] is None
        assert result[ "expandSect" ] is None

    def test_collapse_all_still_drives_the_TASK_LIST_not_the_epic_board( self, logged_in_page ):
        """
        The behavioral half of the trap: the toolbar pair must still collapse
        the OWNER groups. Adjacency alone would not catch a mis-wired handler.
        """
        _seeded_page( logged_in_page )
        logged_in_page.wait_for_selector( "#task-list-container tbody.task-group", state="attached" )

        logged_in_page.get_by_test_id( "task-list-collapse-all-btn" ).click()
        logged_in_page.wait_for_function(
            """() => {
                const gs = document.querySelectorAll( "#task-list-container tbody.task-group" );
                return gs.length > 0 && Array.from( gs ).every( g => g.classList.contains( "collapsed" ) );
            }"""
        )

    def test_toolbar_button_toggles_the_section( self, logged_in_page ):
        _seeded_page( logged_in_page )

        btn     = logged_in_page.get_by_test_id( "epic-board-toolbar-btn" )
        section = logged_in_page.locator( "#section-epic-board" )

        btn.click()
        logged_in_page.wait_for_function(
            """() => document.getElementById( "section-epic-board" )
                             .classList.contains( "section-hidden" )"""
        )

        btn.click()
        logged_in_page.wait_for_function(
            """() => !document.getElementById( "section-epic-board" )
                              .classList.contains( "section-hidden" )"""
        )
        assert section.locator( "tbody.epic-group" ).count() > 0, "rows survive the toggle"


class TestEpicBoardAccordion:
    """Groups expand on click, and the choice survives a reload."""

    def test_epics_start_collapsed_and_the_rick_highlight_starts_open( self, logged_in_page ):
        """
        Plan §6: "Default state: all epics collapsed." The ⏳ highlight is the
        documented exception — a collapsed highlight highlights nothing.
        """
        _seeded_page( logged_in_page )

        seal = logged_in_page.locator( '#epic-board-container tbody.epic-group[data-epic="epic:seal-the-test-tier"]' )
        rick = logged_in_page.locator( '#epic-board-container tbody.epic-group[data-epic="__on_rick__"]' )
        assert "collapsed" in ( seal.get_attribute( "class" ) or "" )
        assert "collapsed" not in ( rick.get_attribute( "class" ) or "" )

    def test_clicking_a_group_header_expands_it( self, logged_in_page ):
        _seeded_page( logged_in_page )

        header = logged_in_page.locator(
            '#epic-board-container tbody.epic-group[data-epic="epic:seal-the-test-tier"] .epic-group-header'
        )
        header.click()
        logged_in_page.wait_for_function(
            """() => {
                const t = document.querySelector(
                    '#epic-board-container tbody.epic-group[data-epic="epic:seal-the-test-tier"]' );
                return t && !t.classList.contains( "collapsed" );
            }"""
        )
        assert header.get_attribute( "aria-expanded" ) == "true"
        # Its three OPEN rows are now visible (the terminal one is filtered).
        rows = logged_in_page.locator(
            '#epic-board-container tbody.epic-group[data-epic="epic:seal-the-test-tier"] .epic-row'
        )
        assert rows.count() == 3

    def test_the_expand_choice_survives_a_page_reload( self, logged_in_page ):
        """DoD: "Collapse state persists across a page reload"."""
        _seeded_page( logged_in_page )

        logged_in_page.locator(
            '#epic-board-container tbody.epic-group[data-epic="epic:seal-the-test-tier"] .epic-group-header'
        ).click()
        logged_in_page.wait_for_function(
            """() => !document.querySelector(
                '#epic-board-container tbody.epic-group[data-epic="epic:seal-the-test-tier"]'
            ).classList.contains( "collapsed" )"""
        )

        _goto_notifications( logged_in_page )
        logged_in_page.wait_for_selector( "#epic-board-container tbody.epic-group", state="attached" )

        seal = logged_in_page.locator(
            '#epic-board-container tbody.epic-group[data-epic="epic:seal-the-test-tier"]' )
        assert "collapsed" not in ( seal.get_attribute( "class" ) or "" ), \
            "the open/closed choice did not survive the reload"

    def test_collapse_all_and_expand_all_drive_every_group( self, logged_in_page ):
        _seeded_page( logged_in_page )

        logged_in_page.get_by_test_id( "epic-board-expand-all-btn" ).click()
        logged_in_page.wait_for_function(
            """() => {
                const gs = document.querySelectorAll( "#epic-board-container tbody.epic-group" );
                return gs.length > 0 && Array.from( gs ).every( g => !g.classList.contains( "collapsed" ) );
            }"""
        )

        logged_in_page.get_by_test_id( "epic-board-collapse-all-btn" ).click()
        logged_in_page.wait_for_function(
            """() => {
                const gs = document.querySelectorAll( "#epic-board-container tbody.epic-group" );
                return gs.length > 0 && Array.from( gs ).every( g => g.classList.contains( "collapsed" ) );
            }"""
        )


class TestEpicBoardDriftAndParity:
    """Drift is not dropped, and the two panes agree on the row set."""

    def test_the_drift_group_renders_and_holds_BOTH_drift_shapes( self, logged_in_page ):
        """DoD: "Drift group renders and is not silently dropped"."""
        _seeded_page( logged_in_page )

        logged_in_page.locator(
            '#epic-board-container tbody.epic-group[data-epic="__drift__"] .epic-group-header'
        ).click()
        logged_in_page.wait_for_function(
            """() => !document.querySelector(
                '#epic-board-container tbody.epic-group[data-epic="__drift__"]'
            ).classList.contains( "collapsed" )"""
        )

        rows = logged_in_page.locator(
            '#epic-board-container tbody.epic-group[data-epic="__drift__"] .epic-row' )
        assert rows.count() == DRIFT_COUNT, \
            "both the no-key row AND the non-epic-key row must land in drift"

    def test_the_rick_row_appears_in_the_highlight_AND_under_its_epic( self, logged_in_page ):
        """The plan calls the ⏳ section a highlight, not a move."""
        _seeded_page( logged_in_page )

        logged_in_page.get_by_test_id( "epic-board-expand-all-btn" ).click()
        logged_in_page.wait_for_function(
            """() => Array.from( document.querySelectorAll( "#epic-board-container tbody.epic-group" ) )
                          .every( g => !g.classList.contains( "collapsed" ) )"""
        )

        in_highlight = logged_in_page.locator(
            '#epic-board-container tbody.epic-group[data-epic="__on_rick__"] .epic-row' ).count()
        in_epic = logged_in_page.locator(
            '#epic-board-container tbody.epic-group[data-epic="epic:board-visibility"] .epic-row' ).count()

        assert in_highlight == 1
        assert in_epic == 1, "the highlighted row is ALSO still under its own epic"

    def test_epic_row_total_matches_the_task_lists_row_total( self, logged_in_page ):
        """
        DoD: "counts match the task list's row total". Two views of one fetch
        cannot disagree about which rows exist — the drift group is what makes
        this hold, since a dropped-drift bug would show up here as a shortfall.
        """
        _seeded_page( logged_in_page )
        logged_in_page.wait_for_selector( "#task-list-container tbody.task-group", state="attached" )

        logged_in_page.get_by_test_id( "epic-board-expand-all-btn" ).click()
        logged_in_page.wait_for_function(
            """() => Array.from( document.querySelectorAll( "#epic-board-container tbody.epic-group" ) )
                          .every( g => !g.classList.contains( "collapsed" ) )"""
        )

        # The on-Rick group is a HIGHLIGHT and double-counts by design, so it is
        # excluded from the parity sum — the epics + drift are the partition.
        epic_rows = logged_in_page.eval_on_selector_all(
            "#epic-board-container tbody.epic-group[data-epic]",
            """els => els.filter( e => e.dataset.epic !== "__on_rick__" )
                         .reduce( ( n, e ) => n + e.querySelectorAll( ".epic-row" ).length, 0 )"""
        )
        task_rows = logged_in_page.locator( "#task-list-container .task-row" ).count()

        assert epic_rows == task_rows == OPEN_COUNT


class TestEpicBoardSharesOneFetch:
    """The DoD's headline claim, asserted at the network layer."""

    def test_one_GET_api_tasks_serves_BOTH_panes( self, logged_in_page ):
        """
        DoD: "A second poll was NOT added — verified by counting timers against
        /api/tasks". Counting the actual REQUESTS is the stronger form of the
        same check: a second timer, a second fetch call, or an eager re-fetch
        on render would each push this above one.
        """
        state = _seeded_page( logged_in_page )
        logged_in_page.wait_for_selector( "#task-list-container tbody.task-group", state="attached" )

        assert state[ "task_calls" ] == 1, \
            f"expected ONE /api/tasks fetch feeding both panes, saw {state['task_calls']}"
        # And both panes actually rendered off it.
        assert logged_in_page.locator( "#epic-board-container table.epic-board-table" ).count() == 1
        assert logged_in_page.locator( "#task-list-container table.task-list-table" ).count() == 1

    def test_the_shared_refresh_button_updates_BOTH_panes( self, logged_in_page ):
        state = _seeded_page( logged_in_page )
        before = state[ "task_calls" ]

        logged_in_page.get_by_test_id( "epic-board-refresh-btn" ).click()
        logged_in_page.wait_for_function(
            f"""() => document.getElementById( "epic-board-updated" ).textContent.startsWith( "updated" )"""
        )

        assert state[ "task_calls" ] == before + 1, "one refresh, one fetch, two panes"

    def test_the_story_file_is_fetched_ONCE_not_every_tick( self, logged_in_page ):
        """
        The story text is a hand-edited file, not live state. Re-fetching it on
        every 60s tick would be waste dressed up as freshness.
        """
        state = _seeded_page( logged_in_page )

        logged_in_page.get_by_test_id( "epic-board-refresh-btn" ).click()
        logged_in_page.wait_for_timeout( 500 )
        logged_in_page.get_by_test_id( "epic-board-refresh-btn" ).click()
        logged_in_page.wait_for_timeout( 500 )

        assert state[ "story_calls" ] == 1, \
            f"epic-stories must be fetched once per page load, saw {state['story_calls']}"


class TestEpicBoardDegradesGracefully:
    """An outage says so; it does not blank the page."""

    def test_an_unreachable_store_shows_an_indicator_not_an_empty_pane( self, logged_in_page ):
        _seeded_page( logged_in_page, mode="unreachable" )
        logged_in_page.wait_for_selector( "#epic-board-container .task-list-message", state="attached" )

        text = logged_in_page.locator( "#epic-board-container" ).inner_text()
        assert "unreachable" in text.lower()
