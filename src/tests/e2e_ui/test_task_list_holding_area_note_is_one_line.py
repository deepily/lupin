#!/usr/bin/env python3
"""
E2E — the classic task list never prints the server's HOLDING AREA paragraph (row 081dac6d).

Rick, 2026-09-16: the task list printed the holding-area note word for word, "way too goddamn
verbose". The note is written for Claude sessions (it names `task_query`), and the task list's
all-statuses query draws it on every load. The ruling, as built by Rio in d0c0b9f7 + 563c14b6:
    - the Holding Area header shows its count  -> the task list shows NOTHING for the note
    - the header has no count ("—", unreadable) -> the task list shows "N waiting for your approval"
    - every other server warning still prints verbatim after "⚠️ Server:"

WHAT THIS MEASURES, AND WHY IT ENTERS HERE:
    The served page, in a real browser, after a real login. The unit tier
    (`src/tests/unit/test_the_task_list_page_shortens_the_holding_area_note.py`) runs the
    recognizer under node; it cannot see the page that is actually SERVED, so a saved
    `notifications.js` the page does not load (stale `?v=` cache-bust, an unbounced server) is
    green there and red here.

⚠️ THE TASK LIST IS DRAWN BEFORE THE HOLDING AREA, SO EACH TEST PRESSES ⟳ ONCE. `refreshTaskList`
renders the board, then fetches and paints the holding area in the same tick. The hide/keep
decision reads `#holding-area-count` at board-render time, so the first paint reads the HTML
placeholder, not the pane's count. Each test waits for the holding pane's own count, presses the
task list's refresh button, and reads the board drawn AFTER it — the state a reader sees from the
second tick on.

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

import pytest

from .conftest import BASE_URL
from .task_panes import LEGACY_TASK_LIST_PANE, is_holding_area_query


HELD_COUNT       = 7
SHORT_LINE       = f"{HELD_COUNT} waiting for your approval"
OTHER_WARNING    = "e2e: an unrelated server warning that must still print word for word"
HOLDING_NOTE_SEL = f"{LEGACY_TASK_LIST_PANE} .task-list-holding-note"
HOLDING_COUNT    = "#holding-area-count"
REFRESH_BUTTON   = '[data-testid="task-list-refresh-btn"]'
PAINT_TIMEOUT_MS = 20_000

# Words only the long note carries. Pinned as literals on purpose: if the page ever prints the
# paragraph again, these are what a reader would see.
LONG_NOTE_MARKERS = [ "HOLDING AREA", "task_query" ]

# Seven held rows, so the holding pane's own count equals the note's count.
HELD_ROWS = [
    {
        "id"                  : f"0ab1a095-1eed-4e7e-be83-aa7c43b8be5{i}",
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
    for i in range( HELD_COUNT )
]


def _real_router_body( extra_warnings=() ):
    """
    The board's `/api/tasks` answer, produced by the real tasks router over a faked repository.

    Requires:
        - cosa is importable in this process

    Ensures:
        - returns the router's JSON body for `GET /api/tasks`, with one open row
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
        id = uuid.uuid4(), item_class = "task", title = "e2e: an open row beside the note", body = None,
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


def _open_task_list( page, board_body, holding_readable, expected_count ):
    """
    Route `/api/tasks`, open the classic page, wait for the holding pane's count, then press ⟳.

    Requires:
        - holding_readable True answers the holding query with HELD_ROWS; False answers it 500
        - expected_count is the text the holding pane writes into #holding-area-count

    Ensures:
        - returns after the board has been drawn a SECOND time, from a board request made after
          the holding pane painted its count
        - returns the list of board request URLs seen
    """
    board_urls = [ ]

    def _handler( route ):
        url = route.request.url
        if is_holding_area_query( url ):
            if holding_readable:
                route.fulfill( status=200, content_type="application/json",
                               body=json.dumps( { "tasks": HELD_ROWS, "count": len( HELD_ROWS ) } ) )
            else:
                route.fulfill( status=500, content_type="application/json", body=json.dumps( { "detail": "e2e: store down" } ) )
            return
        board_urls.append( url )
        route.fulfill( status=200, content_type="application/json", body=json.dumps( board_body ) )

    page.route( "**/api/tasks*", _handler )
    page.goto( f"{BASE_URL}/app/notifications?classic=1" )
    page.wait_for_load_state( "networkidle" )
    page.wait_for_function(
        "([sel, want]) => { const el = document.querySelector( sel ); return !!el && el.textContent.trim() === want; }",
        arg     = [ HOLDING_COUNT, expected_count ],
        timeout = PAINT_TIMEOUT_MS,
    )

    first_tick = len( board_urls )
    assert first_tick >= 1, "the board query was never made, so nothing below measured the routed answer"

    page.locator( REFRESH_BUTTON ).click()
    page.wait_for_function(
        "([sel, want]) => { const el = document.querySelector( sel ); return !!el && el.textContent.trim() === want; }",
        arg     = [ HOLDING_COUNT, expected_count ],
        timeout = PAINT_TIMEOUT_MS,
    )
    page.wait_for_load_state( "networkidle" )
    assert len( board_urls ) > first_tick, "pressing ⟳ did not re-fetch the board, so the second paint was never measured"
    page.wait_for_selector( f"{LEGACY_TASK_LIST_PANE} .task-list-message", state="attached", timeout=PAINT_TIMEOUT_MS )
    return board_urls


def _pane_text( page ):
    return page.eval_on_selector( LEGACY_TASK_LIST_PANE, "el => el.textContent" )


def _assert_no_long_note( text ):
    for marker in LONG_NOTE_MARKERS:
        assert marker not in text, f"the long holding-area note is on the page ({marker!r} found): {text[ :400 ]!r}"


class TestTheHoldingAreaNoteNeverPrintsInFull:

    def test_a_shown_holding_count_hides_the_note_entirely( self, logged_in_page ):
        """
        The Holding Area header reads 7, so the task list says nothing about held rows.

        🔴 THE ABSENCE OF "⚠️ Server:" IS THE COUPLING ARM. If the recognizer stops matching the
        router's note, the note falls through to the verbatim line — and that line is what fails
        here, not the short line.
        """
        _open_task_list( logged_in_page, _real_router_body(), holding_readable=True, expected_count=str( HELD_COUNT ) )

        assert logged_in_page.locator( HOLDING_NOTE_SEL ).count() == 0, \
            "the short line is shown although the Holding Area header already shows its count"
        text = _pane_text( logged_in_page )
        _assert_no_long_note( text )
        assert "⚠️ Server:" not in text, f"the note printed as a verbatim server warning: {text[ :400 ]!r}"

    def test_no_holding_count_keeps_one_short_line( self, logged_in_page ):
        """
        The holding pane cannot read the store and shows "—", so the task list says "7 waiting".

        🔴 BOTH HALVES ARE THE ASSERTION. The line alone would pass a page that also printed the
        paragraph; the absence alone would pass a page that printed nothing.
        """
        _open_task_list( logged_in_page, _real_router_body(), holding_readable=False, expected_count="—" )

        notes = logged_in_page.locator( HOLDING_NOTE_SEL )
        assert notes.count() == 1, f"expected exactly one short holding line, found {notes.count()}"
        assert notes.first.text_content().strip() == SHORT_LINE

        text = _pane_text( logged_in_page )
        _assert_no_long_note( text )
        assert "⚠️ Server:" not in text, f"the note printed as a verbatim server warning: {text[ :400 ]!r}"

    def test_an_unrelated_warning_still_prints_word_for_word( self, logged_in_page ):
        """
        The recognizer claims the holding note and nothing else.

        ⚠️ Without this test, a page that silently dropped EVERY warning would pass the two above.
        """
        _open_task_list( logged_in_page, _real_router_body( extra_warnings=[ OTHER_WARNING ] ),
                         holding_readable=True, expected_count=str( HELD_COUNT ) )

        verbatim = logged_in_page.locator( f"{LEGACY_TASK_LIST_PANE} .task-list-message", has_text="⚠️ Server:" )
        assert verbatim.count() == 1, f"expected one verbatim server-warning line, found {verbatim.count()}"
        line = verbatim.first.text_content()
        assert OTHER_WARNING in line, f"the unrelated warning did not print verbatim: {line!r}"
        _assert_no_long_note( line )
