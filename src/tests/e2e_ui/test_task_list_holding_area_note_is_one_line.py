#!/usr/bin/env python3
"""
E2E — the classic task list never prints the server's HOLDING AREA paragraph (row 081dac6d).

Rick, 2026-09-16: the task list printed the holding-area note word for word, "way too goddamn
verbose". The note is written for Claude sessions (it names `task_query`), and the task list's
all-statuses query draws it on every load. The ruling, as built by Rio in d0c0b9f7 + 563c14b6 +
5d81461c:
    - the Holding Area header shows the SAME number as the note -> the task list shows nothing for it
    - the header shows a placeholder "0", a different number, or "—" -> one short line,
      "N waiting for your approval"
    - every other server warning still prints verbatim after "⚠️ Server:"

WHAT THIS MEASURES, AND WHY IT ENTERS HERE:
    The served page, in a real browser, after a real login. The unit tier
    (`src/tests/unit/test_the_task_list_page_shortens_the_holding_area_note.py`) runs the
    recognizer under node; it cannot see the page that is actually SERVED, so a saved
    `notifications.js` the page does not load (stale `?v=` cache-bust, an unbounced server) is
    green there and red here.

⚠️ THE TASK LIST IS DRAWN BEFORE THE HOLDING AREA, SO EACH TEST READS THE SECOND TICK.
`refreshTaskList` renders the board, then fetches and paints the holding area in the same tick,
so the first board reads the HTML placeholder "0". Each test lets the first tick finish, presses the
task list's ⟳, and reads the board that tick drew — found in review by Rio (race + a hidden note
leaving no `.task-list-message` to wait on).

⚠️ ⟳ IS SWALLOWED WHILE A TICK IS IN FLIGHT. `refreshTaskList` returns early on
`_taskListFetchInFlight` (the debounce guard), and the tick keeps that flag up through the holding
pane and the request badges. So the click waits for the flag to drop, and the second tick is known
to have drawn its board once ITS holding-area response has arrived, because the board is rendered
before that request is made.

⚠️ THE NOTE IS THE ROUTER'S, NOT A LITERAL. Only `GET /api/tasks` is routed. The board's body is
produced in this process by the REAL `cosa.rest.routers.tasks` router over a faked repository
(7 held rows). Reword the note in tasks.py so the page's recognizer stops matching it, and the long
paragraph returns as a "⚠️ Server:" line, which every test here refuses.

Venue: :8000 (scheduled) — `logged_in_page` resets lupin_db_test and registers a user. Select with
`-k holding_area_note`.
"""

import json
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import MagicMock
from urllib.parse import urlparse

import pytest

from .conftest import BASE_URL
from .task_panes import LEGACY_TASK_LIST_PANE, is_holding_area_query


HELD_COUNT       = 7
SHORT_LINE       = f"{HELD_COUNT} waiting for your approval"
BOARD_ROW_TITLE  = "e2e: an open row beside the note"
OTHER_WARNING    = "e2e: an unrelated server warning that must still print word for word"
HOLDING_NOTE_SEL = f"{LEGACY_TASK_LIST_PANE} .task-list-holding-note"
HOLDING_COUNT    = "#holding-area-count"
REFRESH_BUTTON   = '[data-testid="task-list-refresh-btn"]'
PAINT_TIMEOUT_MS = 20_000

# Words only the long note carries. Pinned as literals on purpose: if the page ever prints the
# paragraph again, these are what a reader would see.
LONG_NOTE_MARKERS = [ "HOLDING AREA", "task_query" ]


def _held_rows( n ):
    """`n` held rows in the real `/api/tasks` row shape, so the holding pane's header reads `n`."""
    return [
        {
            "id"                  : f"0ab1a095-1eed-4e7e-be83-aa7c43b8be{i:02d}",
            "title"               : f"e2e: held row {i}",
            "body"                : "",
            "owner_persona"       : "chloe",
            "status"              : "not_approved",
            "item_class"          : "task",
            "blocked_by"          : [ ],
            "next_chase_ts"       : None,
            "accountable_manager" : "maria",
            "created_by"          : "chloe e2e",
            "priority"            : "P3",
            "project"             : "lupin"
        }
        for i in range( n )
    ]


def _real_router_body( extra_warnings=() ):
    """
    The board's `/api/tasks` answer, produced by the real tasks router over a faked repository.

    Requires:
        - cosa is importable in this process

    Ensures:
        - returns the router's JSON body for `GET /api/tasks`, with one open row titled BOARD_ROW_TITLE
        - body["warnings"] holds exactly one holding-area note, counting HELD_COUNT rows,
          followed by extra_warnings in order

    Raises:
        - AssertionError when the router no longer emits exactly one holding note for this
          fixture, named so it is not read as a rendering failure
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt
    from cosa.rest.postgres_models import TaskItem
    from cosa.rest.routers import tasks

    now  = datetime.now( timezone.utc )
    item = TaskItem(
        id = uuid.uuid4(), item_class = "task", title = BOARD_ROW_TITLE, body = None,
        project = "lupin", owner_persona = "chloe", accountable_manager = "maria", created_by = "chloe e2e",
        status = "queued", blocked_by = [ ], next_chase_ts = None, gate_class = "none", priority = "P3",
        source_qid = None, correlation_key = None, created_ts = now, updated_ts = now, title_trimmed = False,
    )

    fake = MagicMock()
    fake.count_tasks.side_effect               = lambda **kw: HELD_COUNT if kw.get( "status" ) == "not_approved" else 1
    fake.query_tasks.side_effect               = lambda **kw: [ item ]
    fake.statuses_for_ids.return_value         = { }
    fake.count_tasks_by_project.return_value   = { }
    fake.count_tasks_by_priority.return_value  = { }
    fake.count_tasks_by_status.return_value    = { }
    fake.count_created_and_closed.return_value = { "created": 0, "closed": 0 }

    @contextmanager
    def _fake_get_db():
        yield MagicMock()

    app = FastAPI()
    app.include_router( tasks.router )
    app.dependency_overrides[ require_api_key_or_jwt ] = lambda: "e2e-user"

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr( tasks, "get_db", _fake_get_db )
        mp.setattr( tasks, "TaskRepository", lambda session: fake )
        response = TestClient( app ).get( "/api/tasks" )

    assert response.status_code == 200, f"PRECONDITION: the router answered {response.status_code}: {response.text[ :300 ]}"
    body = response.json()
    held = [ w for w in body.get( "warnings", [ ] ) if "not_approved" in w ]
    assert len( held ) == 1, f"PRECONDITION: the router must emit one holding note for this fixture: {body.get( 'warnings' )}"

    body[ "warnings" ] = list( body[ "warnings" ] ) + list( extra_warnings )
    return body


def _is_tasks_list( url ):
    return urlparse( url ).path == "/api/tasks"


def _is_board_query( url ):
    return _is_tasks_list( url ) and not is_holding_area_query( url )


def _is_holding_query( url ):
    return _is_tasks_list( url ) and is_holding_area_query( url )


def _wait_tick_settled( page, expected_count ):
    """Wait until no task-list tick is in flight and the holding header reads `expected_count`."""
    page.wait_for_function(
        """([sel, want]) => {
            const ui = window.notificationsUI;
            const el = document.querySelector( sel );
            return !!ui && ui._taskListFetchInFlight === false && !!el && el.textContent.trim() === want;
        }""",
        arg     = [ HOLDING_COUNT, expected_count ],
        timeout = PAINT_TIMEOUT_MS,
    )


def _open_task_list( page, board_body, held_rows, expected_count ):
    """
    Route `/api/tasks`, open the classic page, let the first tick finish, press ⟳, and wait
    for the second tick to draw.

    Requires:
        - held_rows is a list of held rows for the holding query, or None to answer it 500
        - expected_count is the text the holding pane writes into #holding-area-count

    Ensures:
        - returns after a board drawn by a tick that began AFTER the holding header held
          expected_count, with that tick settled
        - the board row BOARD_ROW_TITLE is in the pane, so a pane with no message line is
          still a painted pane
    """
    def _handler( route ):
        url = route.request.url
        if _is_holding_query( url ):
            if held_rows is None:
                route.fulfill( status=500, content_type="application/json", body=json.dumps( { "detail": "e2e: store down" } ) )
            else:
                route.fulfill( status=200, content_type="application/json",
                               body=json.dumps( { "tasks": held_rows, "count": len( held_rows ) } ) )
            return
        route.fulfill( status=200, content_type="application/json", body=json.dumps( board_body ) )

    page.route( "**/api/tasks*", _handler )
    # The flag starts false and the header starts "0", so for the header-zero case the settle
    # check alone could pass before the first tick has begun. Waiting for that tick's holding
    # response first makes "settled" mean the first tick has run.
    with page.expect_response( lambda r: _is_holding_query( r.url ), timeout=PAINT_TIMEOUT_MS ):
        page.goto( f"{BASE_URL}/app/notifications?classic=1" )
    _wait_tick_settled( page, expected_count )

    with page.expect_response( lambda r: _is_holding_query( r.url ), timeout=PAINT_TIMEOUT_MS ):
        with page.expect_request( lambda r: _is_board_query( r.url ), timeout=PAINT_TIMEOUT_MS ):
            page.locator( REFRESH_BUTTON ).click()

    _wait_tick_settled( page, expected_count )
    page.locator( LEGACY_TASK_LIST_PANE ).get_by_text( BOARD_ROW_TITLE ).first.wait_for( state="attached", timeout=PAINT_TIMEOUT_MS )


def _pane_text( page ):
    return page.eval_on_selector( LEGACY_TASK_LIST_PANE, "el => el.textContent" )


def _assert_no_long_note( text ):
    for marker in LONG_NOTE_MARKERS:
        assert marker not in text, f"the long holding-area note is on the page ({marker!r} found): {text[ :400 ]!r}"


class TestTheHoldingAreaNoteNeverPrintsInFull:

    def test_a_header_showing_the_same_count_hides_the_note_entirely( self, logged_in_page ):
        """
        The Holding Area header reads 7 and the note counts 7, so the task list says nothing more.

        🔴 THE ABSENCE OF "⚠️ Server:" IS THE COUPLING ARM. If the recognizer stops matching the
        router's note, the note falls through to the verbatim line — and that line is what fails
        here, not the short line.
        """
        _open_task_list( logged_in_page, _real_router_body(), _held_rows( HELD_COUNT ), str( HELD_COUNT ) )

        assert logged_in_page.locator( HOLDING_NOTE_SEL ).count() == 0, \
            "the short line is shown although the Holding Area header already shows the same count"
        text = _pane_text( logged_in_page )
        _assert_no_long_note( text )
        assert "⚠️ Server:" not in text, f"the note printed as a verbatim server warning: {text[ :400 ]!r}"

    @pytest.mark.parametrize( "held_rows, header", [
        pytest.param( None,            "—", id="header-dash-store-down" ),
        pytest.param( [ ],             "0", id="header-zero" ),
        pytest.param( _held_rows( 3 ), "3", id="header-different-count" ),
    ] )
    def test_a_header_without_the_same_count_keeps_one_short_line( self, logged_in_page, held_rows, header ):
        """
        The header shows "—", "0" or "3" — none of them the note's 7 — so the task list says "7 waiting".

        🔴 BOTH HALVES ARE THE ASSERTION. The line alone would pass a page that also printed the
        paragraph; the absence alone would pass a page that printed nothing.
        """
        _open_task_list( logged_in_page, _real_router_body(), held_rows, header )

        notes = logged_in_page.locator( HOLDING_NOTE_SEL )
        assert notes.count() == 1, f"header {header!r}: expected exactly one short holding line, found {notes.count()}"
        assert notes.first.text_content().strip() == SHORT_LINE

        text = _pane_text( logged_in_page )
        _assert_no_long_note( text )
        assert "⚠️ Server:" not in text, f"the note printed as a verbatim server warning: {text[ :400 ]!r}"

    def test_an_unrelated_warning_still_prints_word_for_word( self, logged_in_page ):
        """
        The recognizer claims the holding note and nothing else.

        ⚠️ Without this test, a page that silently dropped EVERY warning would pass the ones above.
        """
        _open_task_list( logged_in_page, _real_router_body( extra_warnings=[ OTHER_WARNING ] ),
                         _held_rows( HELD_COUNT ), str( HELD_COUNT ) )

        verbatim = logged_in_page.locator( f"{LEGACY_TASK_LIST_PANE} .task-list-message", has_text="⚠️ Server:" )
        assert verbatim.count() == 1, f"expected one verbatim server-warning line, found {verbatim.count()}"
        line = verbatim.first.text_content()
        assert OTHER_WARNING in line, f"the unrelated warning did not print verbatim: {line!r}"
        _assert_no_long_note( line )
