"""
Shared helpers for the task-pane E2E files (row 1657a852).

Two facts about the task panes that every E2E touching them has to respect, written once:

1. THE PAGE ASKS `/api/tasks` TWO DIFFERENT QUESTIONS. The board query, and the holding
   area's `status=not_approved` query (`HOLDING_AREA_QUERY` in
   `src/lupin_app/static/js/shared/task-list-query.js`). The real server answers them with
   DISJOINT sets — `not_approved` is in the store's BOARD_INVISIBLE_STATUSES. A route
   mock that answers both with the board fixture renders every row a second time, in the
   Holding Area, and a test reading that page is reading a page no server can produce.
   `tasks_route_handler` answers each question with its own body.

2. A ROW'S CONTROLS ARE NOT INSIDE THE ROW. Per `ROW_SCHEMA` (`multiplexer/render/
   rowSchema.ts`) the row carries id, title, class, status and priority. Blocked-by, chase,
   accountable, filer, project, the 📄 detail icon and the action controls live in a
   separate `tr.task-controls-row[data-controls-for=<id>]`, created `hidden` and opened by
   `.task-disclose-button[data-task-id=<id>]`. Both clients build it the same way.
   `disclose_row` opens it and hands it back.

The Epic Board renders the board's rows too, from the same fetch and with the same row
classes, by design. So a locator that is not scoped to one pane can match a row twice even
when the mock is honest — scope to `MUX_TASK_LIST_PANE` / `LEGACY_TASK_LIST_PANE`.
"""

from __future__ import annotations

import json


MUX_TASK_LIST_PANE     = '[data-testid="multiplexer-task-list-container"]'
MUX_HOLDING_AREA_PANE  = '[data-testid="multiplexer-holding-area-container"]'
LEGACY_TASK_LIST_PANE  = "#task-list-container"

# The one parameter that tells the holding area's query from the board's. Read from
# HOLDING_AREA_QUERY, not guessed: "/api/tasks?limit=500&unscoped_audit=true&status=not_approved&char_budget=0".
HOLDING_AREA_QUERY_MARK = "status=not_approved"

EMPTY_TASKS = { "tasks": [ ], "count": 0 }

# ROW_SCHEMA, copied as literals. The TypeScript unit tier pins the schema itself; these
# pin that the page the browser is served follows it.
ROW_LINE1_COLUMNS = [ "task-col-id", "task-col-title", "task-col-class", "task-col-status", "task-col-priority" ]
DISCLOSED_FIELDS  = [ "task-col-blocked", "task-col-chase", "task-col-accountable", "task-col-filer",
                      "task-col-project", "task-col-detail", "task-col-actions" ]


def is_holding_area_query( url: str ) -> bool:
    """
    Whether a `/api/tasks?…` request is the holding area's query.

    Ensures:
        - True iff the URL carries `status=not_approved`
    """
    return HOLDING_AREA_QUERY_MARK in url


def tasks_route_handler( board_body, holding_body=None, seen=None ):
    """
    A `page.route` handler for `**/api/tasks*` that answers each query with its own body.

    Requires:
        - board_body is a dict, or a zero-argument callable returning one (so a test can
          flip what the board answers between fetches)
        - holding_body is a dict or None (None → EMPTY_TASKS)
        - seen is a dict with lists "board" and "holding", or None

    Ensures:
        - a holding-area query is answered 200 with holding_body
        - any other query is answered 200 with board_body
        - when seen is given, each request URL is appended to seen["board"] or seen["holding"]
    """
    def _handler( route ):
        url = route.request.url
        if is_holding_area_query( url ):
            if seen is not None: seen[ "holding" ].append( url )
            body = holding_body if holding_body is not None else EMPTY_TASKS
        else:
            if seen is not None: seen[ "board" ].append( url )
            body = board_body() if callable( board_body ) else board_body
        route.fulfill( status=200, content_type="application/json", body=json.dumps( body ) )
    return _handler


def disclose_row( pane, task_id: str, timeout_ms: int = 3000 ):
    """
    Open a row's controls row and return it.

    Requires:
        - pane is a Playwright Locator for one task pane
        - the row for task_id is rendered in that pane

    Ensures:
        - clicks the row's disclosure button, waits for its controls row to be visible,
          and returns that `tr.task-controls-row` Locator

    Raises:
        - playwright TimeoutError if the controls row never becomes visible
    """
    pane.locator( f'.task-disclose-button[data-task-id="{task_id}"]' ).click()
    controls = pane.locator( f'tr.task-controls-row[data-controls-for="{task_id}"]' )
    controls.wait_for( state="visible", timeout=timeout_ms )
    return controls


def disclosed_value( controls, field_class: str ) -> str:
    """
    The VALUE of one disclosed field, without its label.

    Each field renders `<span class="task-disclosed-label">Blocked by</span>` next to its
    value, so the field's own text is never empty — a "not blank, not —" check on the
    whole field passes even when the value is missing. Read the value span.

    Requires:
        - controls is a controls-row Locator; field_class is e.g. "task-col-chase"
    """
    return controls.locator( f".{field_class} .task-disclosed-value" ).text_content().strip()
