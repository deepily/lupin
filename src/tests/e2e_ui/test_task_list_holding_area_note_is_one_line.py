#!/usr/bin/env python3
"""
E2E — the classic task list shows the server's HOLDING AREA note as one short line (row 081dac6d).

Rick, 2026-09-16: the task list printed the holding-area note word for word, "way too goddamn
verbose". The note is written for Claude sessions (it names `task_query`), and the task list's
all-statuses query draws it on every load. The page now shows "N waiting for your approval" in its
place, and every other server warning still prints verbatim after "⚠️ Server:".

WHAT THIS MEASURES, AND WHY IT ENTERS HERE:
    - the served page, in a real browser, after a real login, reads the board's `/api/tasks`
      answer and paints the short line in `#task-list-container`, with none of the long note
    - an unrelated warning in the same answer still prints verbatim, and does not absorb the note

    The unit tier (`src/tests/unit/test_the_task_list_page_shortens_the_holding_area_note.py`) runs
    the recognizer under node against the router's note. It cannot see the page that is actually
    SERVED — a saved `notifications.js` that the page does not load (stale `?v=` cache-bust, a
    bundle nobody bounced) is green there and red here. That is the defect this file exists for.

⚠️ THE NOTE IS THE ROUTER'S, NOT A LITERAL. Only `GET /api/tasks` is routed, and its body is
produced in this process by the REAL `cosa.rest.routers.tasks` router over a faked repository
(7 held rows). Reword the note in tasks.py so the page's recognizer no longer matches it, and the
long paragraph comes back on the page and these tests go red — the coupling Rick's ruling needs.

⚠️ THE HOLDING AREA'S OWN QUERY IS ANSWERED EMPTY. `tasks_route_handler` keeps the two questions
apart (see `task_panes.py`); these tests read only the board pane.

Venue: :8000 (scheduled) — `logged_in_page` resets lupin_db_test and registers a user. Select with
`-k holding_area_note`.
"""

import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from .conftest import BASE_URL
from .task_panes import EMPTY_TASKS, LEGACY_TASK_LIST_PANE, tasks_route_handler


HELD_COUNT       = 7
SHORT_LINE       = f"{HELD_COUNT} waiting for your approval"
OTHER_WARNING    = "e2e: an unrelated server warning that must still print word for word"
HOLDING_NOTE_SEL = f"{LEGACY_TASK_LIST_PANE} .task-list-holding-note"
PAINT_TIMEOUT_MS = 20_000

# Words only the long note carries. Pinned as literals on purpose: if the page ever prints the
# paragraph again, these are what a reader would see.
LONG_NOTE_MARKERS = [ "HOLDING AREA", "task_query" ]


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


def _open_task_list( page, board_body ):
    """
    Route `/api/tasks`, open the classic page, and wait for the board pane's first paint.

    Ensures:
        - returns the dict of request URLs seen, so a test can prove the board query was answered
    """
    seen = { "board": [ ], "holding": [ ] }
    page.route( "**/api/tasks*", tasks_route_handler( board_body, EMPTY_TASKS, seen ) )
    page.goto( f"{BASE_URL}/app/notifications?classic=1" )
    page.wait_for_load_state( "networkidle" )
    page.wait_for_selector( f"{LEGACY_TASK_LIST_PANE} .task-list-message", state="attached", timeout=PAINT_TIMEOUT_MS )
    return seen


def _pane_text( page ):
    return page.eval_on_selector( LEGACY_TASK_LIST_PANE, "el => el.textContent" )


class TestTheHoldingAreaNoteIsOneLine:

    def test_the_task_list_shows_the_short_line_and_none_of_the_long_note( self, logged_in_page ):
        """
        The page shows "7 waiting for your approval" once, and not one word of the paragraph.

        🔴 BOTH HALVES ARE THE ASSERTION. A page that printed the short line AND the paragraph
        would pass a presence check; a page that printed nothing would pass an absence check.
        """
        seen = _open_task_list( logged_in_page, _real_router_body() )

        assert seen[ "board" ], "the board query was never made, so nothing below measured the routed answer"

        notes = logged_in_page.locator( HOLDING_NOTE_SEL )
        assert notes.count() == 1, f"expected exactly one short holding line, found {notes.count()}"
        assert notes.first.text_content().strip() == SHORT_LINE

        text = _pane_text( logged_in_page )
        for marker in LONG_NOTE_MARKERS:
            assert marker not in text, f"the long holding-area note is back on the page ({marker!r} found): {text[ :400 ]!r}"
        assert "⚠️ Server:" not in text, f"the note printed as a verbatim server warning: {text[ :400 ]!r}"

    def test_an_unrelated_warning_still_prints_word_for_word( self, logged_in_page ):
        """
        The recognizer claims the holding note and nothing else.

        ⚠️ Without this test, a page that silently dropped EVERY warning would pass the one above.
        """
        _open_task_list( logged_in_page, _real_router_body( extra_warnings=[ OTHER_WARNING ] ) )

        verbatim = logged_in_page.locator( f"{LEGACY_TASK_LIST_PANE} .task-list-message", has_text="⚠️ Server:" )
        assert verbatim.count() == 1, f"expected one verbatim server-warning line, found {verbatim.count()}"
        line = verbatim.first.text_content()
        assert OTHER_WARNING in line, f"the unrelated warning did not print verbatim: {line!r}"
        for marker in LONG_NOTE_MARKERS:
            assert marker not in line, f"the holding note leaked into the verbatim line: {line!r}"

        assert logged_in_page.locator( HOLDING_NOTE_SEL ).count() == 1
