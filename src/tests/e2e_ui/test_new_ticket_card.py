"""
E2E UI tests for Rick's New Ticket card, on BOTH clients (row c9895403).

HIS WORDS, 2026-09-10: *"create a card that allows me to manually create a new
ticket without you having to file it for me ... within the task list bar right next
to the find functionality."* One card, built by `shared/task-create.js`, opened by a
＋ New button on the legacy notifications page and on the multiplexer.

What this file drives, in a real browser, on each client:

  1. The button opens the card with Rick's defaults (P2, approved, task, lupin,
     epic:unassigned), and a blank title is refused WITHOUT a request.
  2. Create sends ONE POST carrying those defaults, the title, and the Details text
     as `body`; the card closes; the client looks the new row up through Find.
  3. A refusal (422) keeps the card open, shows the server's own words, and keeps
     what was typed.
  4. A 500 with a cause shows that cause and the status code — the review follow-up
     fixed at d16a0026 — instead of "try again".

⚠️ WHY THE POST IS INTERCEPTED, NOT SENT. The operator exemptions (P0, the ratio gate)
key on Rick's validated account, and the E2E users are not Rick. A live create here
would test the ratio gate against whatever the test database holds, not the card. The
server half is covered at the real door by
`src/tests/unit/test_the_operator_skips_the_ratio_gate_at_the_create_door.py`. What only
a browser can prove is the half driven here: the button is mounted, the card opens, the
wire carries the defaults, and each outcome renders.

Both clients' transports are real — legacy `authedFetch`, multiplexer `ApiClient` via
`apiPostTicket` — so the 422 and 500 arms exercise the two different ways a failure
reaches the shared card.

Venue: :8000 scheduled — submit via POST /api/test-suite/submit. The routes are stubbed,
so nothing persists, but the file belongs to the monopolize-mode E2E UI batch.
"""

import json
import os
import time

import pytest
import requests

from .conftest import BASE_URL


# ---------------------------------------------------------------------------
# Seeds — the shapes GET /api/tasks, GET /api/tasks/{id} and POST /api/tasks return
# ---------------------------------------------------------------------------

CREATED_ID = "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"

CREATED_ROW = {
    "id"                  : CREATED_ID,
    "item_class"          : "task",
    "title"               : "E2E new ticket from the card",
    "body"                : "Background for whoever picks this up.",
    "owner_persona"       : None,
    "accountable_manager" : None,
    "status"              : "queued",
    "priority"            : "P2",
    "project"             : "lupin",
    "correlation_key"     : "epic:unassigned",
    "blocked_by"          : [ ],
    "next_chase_ts"       : None,
}

LIST_BODY = {
    "tasks" : [
        {
            "id"                  : "11111111-2222-4333-8444-555555555555",
            "item_class"          : "task",
            "title"               : "An existing row",
            "owner_persona"       : "tiberius",
            "accountable_manager" : "tiberius",
            "status"              : "queued",
            "priority"            : "P1",
            "project"             : "lupin",
            "blocked_by"          : [ ],
            "next_chase_ts"       : None,
        },
    ],
    "count" : 1,
}

RATIO_BODY = { "created": 0, "closed": 0, "ratio": None, "verdict": "idle", "window_hours": 24 }

CLIENTS = {
    "legacy"      : { "button": "task-new-ticket",                  "prefix": "new-ticket" },
    "multiplexer" : { "button": "multiplexer-task-list-new-ticket", "prefix": "multiplexer-new-ticket" },
}


# ---------------------------------------------------------------------------
# Routes + page openers
# ---------------------------------------------------------------------------

def _new_state( post_status=201, post_body=None ):
    """
    A mutable record of what the page sent, plus how to answer its POST.

    Ensures:
        - "posts" and "lookups" start empty
        - "post_reply" is ( status, body ); body defaults to CREATED_ROW
    """
    return {
        "posts"      : [ ],
        "lookups"    : [ ],
        "post_reply" : ( post_status, CREATED_ROW if post_body is None else post_body ),
    }


def _install_routes( page, state ):
    """
    Stub the task store's three doors the card and Find touch.

    Requires:
        - page is a Playwright page; call BEFORE navigation

    Ensures:
        - POST /api/tasks is recorded (its JSON body) and answered with state["post_reply"]
        - GET /api/tasks?… answers LIST_BODY
        - GET /api/tasks/flow-ratio answers RATIO_BODY
        - GET /api/tasks/<id> is recorded (its URL) and answers CREATED_ROW

    ⚠️ Two globs, and the order is load-bearing. Playwright compiles `*` to `[^/]*`, so
    "**/api/tasks*" never matches /api/tasks/<id> (measured and written down in
    test_task_list_card.py `_route_tasks`). The detail route is registered LAST because
    Playwright checks the newest handler first.
    """
    def list_or_create( route ):
        request = route.request
        if request.method == "POST":
            state[ "posts" ].append( request.post_data_json )
            status, body = state[ "post_reply" ]
            payload = body if isinstance( body, str ) else json.dumps( body )
            route.fulfill( status=status, content_type="application/json", body=payload )
            return
        route.fulfill( status=200, content_type="application/json", body=json.dumps( LIST_BODY ) )

    def detail( route ):
        url = route.request.url
        if "/api/tasks/flow-ratio" in url:
            route.fulfill( status=200, content_type="application/json", body=json.dumps( RATIO_BODY ) )
            return
        state[ "lookups" ].append( url )
        route.fulfill( status=200, content_type="application/json", body=json.dumps( CREATED_ROW ) )

    page.route( "**/api/tasks*", list_or_create )
    page.route( "**/api/tasks/*", detail )   # LAST = checked first


def _open_legacy( page, state ):
    """Stub the store, load the classic notifications page, and settle the network."""
    _install_routes( page, state )
    page.goto( f"{BASE_URL}/app/notifications?classic=1" )
    page.wait_for_load_state( "networkidle" )
    return page


def _login_tokens():
    """
    Log in with the shared test credentials, as the multiplexer E2E files do.

    Ensures:
        - returns ( access_token, refresh_token )
        - skips the test when the credentials are not in the environment
    """
    email    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
    password = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )
    if not email or not password:
        pytest.skip( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL / _PASSWORD env vars not set" )
    resp = requests.post( f"{BASE_URL}/auth/login", json={ "email": email, "password": password }, timeout=10 )
    assert resp.status_code == 200, f"login failed: {resp.status_code} {resp.text}"
    tokens = resp.json()[ "tokens" ]
    return tokens[ "access_token" ], tokens[ "refresh_token" ]


def _open_multiplexer( page, state ):
    """Seed auth, stub the store, load the multiplexer, and wait for its boot test hook."""
    access, refresh = _login_tokens()
    page.context.add_init_script(
        f"window.localStorage.setItem('lupin_access_token', {json.dumps( access )});"
        f"window.localStorage.setItem('lupin_refresh_token', {json.dumps( refresh )});"
    )
    _install_routes( page, state )
    page.goto( f"{BASE_URL}/app/multiplexer", wait_until="networkidle", timeout=15_000 )
    page.wait_for_function(
        "() => window.__multiplexerTestHook !== undefined && window.__multiplexerTestHook.eventBus !== undefined",
        timeout=10_000,
    )
    return page


# ---------------------------------------------------------------------------
# Shared bodies — one per behaviour, run on each client
# ---------------------------------------------------------------------------

def _tid( prefix, field=None ):
    return f'[data-testid="{prefix}"]' if field is None else f'[data-testid="{prefix}-{field}"]'


def _open_card( page, client ):
    """Click the client's real ＋ New button and wait for the card."""
    spec   = CLIENTS[ client ]
    button = page.locator( f'[data-testid="{spec["button"]}"]' )
    button.wait_for( state="visible", timeout=10_000 )
    assert "New" in button.text_content(), f"{client}: the ＋ New button reads {button.text_content()!r}"
    button.click()
    page.wait_for_selector( _tid( spec[ "prefix" ] ), state="visible", timeout=5_000 )
    return spec[ "prefix" ]


def _wait_until( page, predicate, what, timeout_ms=5_000 ):
    """
    Pump the page until `predicate()` holds, so route handlers get to run.

    Ensures:
        - returns as soon as the predicate is true
        - fails naming `what` when it never becomes true
    """
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        if predicate(): return
        page.wait_for_timeout( 100 )
    pytest.fail( f"timed out after {timeout_ms} ms waiting for {what}" )


def _wait_result_state( page, prefix, state_name ):
    page.wait_for_function(
        "( [ sel, want ] ) => { const e = document.querySelector( sel ); return !!e && e.getAttribute( 'data-state' ) === want; }",
        arg=[ _tid( prefix, "result" ), state_name ],
        timeout=5_000,
    )


def _check_defaults_and_blank_title( page, client, state ):
    prefix = _open_card( page, client )

    assert page.locator( _tid( prefix, "priority" ) ).input_value()        == "P2"
    assert page.locator( _tid( prefix, "approved" ) ).input_value()        == "yes"
    assert page.locator( _tid( prefix, "item_class" ) ).input_value()      == "task"
    assert page.locator( _tid( prefix, "project" ) ).input_value()         == "lupin"
    assert page.locator( _tid( prefix, "correlation_key" ) ).input_value() == "epic:unassigned"
    assert page.locator( _tid( prefix, "details" ) ).count() == 1, f"{client}: no Details field"

    page.locator( _tid( prefix, "create" ) ).click()
    _wait_result_state( page, prefix, "invalid-form" )
    page.wait_for_timeout( 500 )
    assert state[ "posts" ] == [ ], f"{client}: a blank title sent a request: {state['posts']!r}"
    assert page.locator( _tid( prefix ) ).is_visible(), f"{client}: the card closed on a blank title"


def _check_create_sends_defaults_and_pins_the_row( page, client, state ):
    prefix = _open_card( page, client )
    page.locator( _tid( prefix, "title" ) ).fill( CREATED_ROW[ "title" ] )
    page.locator( _tid( prefix, "details" ) ).fill( CREATED_ROW[ "body" ] )
    page.locator( _tid( prefix, "create" ) ).click()

    _wait_until( page, lambda: len( state[ "posts" ] ) >= 1, f"{client}: the POST to /api/tasks" )
    page.wait_for_selector( _tid( prefix ), state="detached", timeout=5_000 )

    assert len( state[ "posts" ] ) == 1, f"{client}: expected one POST, got {len( state['posts'] )}"
    sent = state[ "posts" ][ 0 ]
    expected = {
        "title"           : CREATED_ROW[ "title" ],
        "body"            : CREATED_ROW[ "body" ],
        "priority"        : "P2",
        "status"          : "queued",
        "item_class"      : "task",
        "project"         : "lupin",
        "correlation_key" : "epic:unassigned",
        "created_by"      : "rick",
    }
    for key, value in expected.items():
        assert sent.get( key ) == value, f"{client}: POST {key}={sent.get( key )!r}, expected {value!r}; sent {sent!r}"
    assert "owner_persona" not in sent, f"{client}: a blank Assigned-to was sent: {sent!r}"

    _wait_until(
        page,
        lambda: any( CREATED_ID in url for url in state[ "lookups" ] ),
        f"{client}: Find looking up the created row {CREATED_ID}",
    )


def _check_refusal_keeps_the_card( page, client, state ):
    prefix = _open_card( page, client )
    page.locator( _tid( prefix, "title" ) ).fill( "Keep me" )
    page.locator( _tid( prefix, "details" ) ).fill( "and me" )
    page.locator( _tid( prefix, "create" ) ).click()

    _wait_result_state( page, prefix, "invalid" )
    assert page.locator( _tid( prefix, "result" ) ).text_content() == "ratio gate says no"
    assert page.locator( _tid( prefix, "title" ) ).input_value()   == "Keep me"
    assert page.locator( _tid( prefix, "details" ) ).input_value() == "and me"
    assert page.locator( _tid( prefix ) ).is_visible(), f"{client}: a refusal closed the card"


def _check_server_error_shows_its_cause( page, client, state ):
    prefix = _open_card( page, client )
    page.locator( _tid( prefix, "title" ) ).fill( "A ticket the store fails on" )
    page.locator( _tid( prefix, "create" ) ).click()

    _wait_result_state( page, prefix, "failed" )
    text = page.locator( _tid( prefix, "result" ) ).text_content()
    assert text == "The store answered 500: database is locked", f"{client}: result read {text!r}"
    assert page.locator( _tid( prefix ) ).is_visible(), f"{client}: a 500 closed the card"


REFUSAL = ( 422, { "detail": "ratio gate says no" } )
FAILURE = ( 500, { "detail": "database is locked" } )


# ---------------------------------------------------------------------------
# The legacy notifications page
# ---------------------------------------------------------------------------

class TestNewTicketCardLegacy:
    """The ＋ New button in the legacy Task List's Find row."""

    def test_opens_with_ricks_defaults_and_refuses_a_blank_title( self, logged_in_page ):
        """
        Requires: authenticated session; store stubbed
        Ensures: defaults P2 · approved · task · lupin · epic:unassigned; a blank title
                 sends nothing and keeps the card open
        """
        state = _new_state()
        _check_defaults_and_blank_title( _open_legacy( logged_in_page, state ), "legacy", state )

    def test_create_sends_the_defaults_and_pins_the_new_row( self, logged_in_page ):
        """
        Requires: authenticated session; POST answers 201 with CREATED_ROW
        Ensures: one POST with the defaults, title and body; the card closes; Find is
                 filled with the new id and looks it up
        """
        state = _new_state()
        page  = _open_legacy( logged_in_page, state )
        _check_create_sends_defaults_and_pins_the_row( page, "legacy", state )
        assert page.locator( "#task-lookup-input" ).input_value() == CREATED_ID

    def test_a_refusal_keeps_the_card_and_what_was_typed( self, logged_in_page ):
        """
        Requires: authenticated session; POST answers 422 with a detail
        Ensures: the detail is shown verbatim; title and details survive; the card stays
        """
        state = _new_state( *REFUSAL )
        _check_refusal_keeps_the_card( _open_legacy( logged_in_page, state ), "legacy", state )

    def test_a_server_error_shows_its_cause_not_try_again( self, logged_in_page ):
        """
        Requires: authenticated session; POST answers 500 with a detail
        Ensures: "The store answered 500: <detail>"; the card stays
        """
        state = _new_state( *FAILURE )
        _check_server_error_shows_its_cause( _open_legacy( logged_in_page, state ), "legacy", state )


# ---------------------------------------------------------------------------
# The multiplexer
# ---------------------------------------------------------------------------

class TestNewTicketCardMultiplexer:
    """The ＋ New button in the multiplexer's Task List header, after Find."""

    def test_opens_with_ricks_defaults_and_refuses_a_blank_title( self, page ):
        """
        Requires: shared test credentials; store stubbed
        Ensures: the same defaults and blank-title refusal as the legacy client
        """
        state = _new_state()
        _check_defaults_and_blank_title( _open_multiplexer( page, state ), "multiplexer", state )

    def test_create_sends_the_defaults_and_pins_the_new_row( self, page ):
        """
        Requires: shared test credentials; POST answers 201 with CREATED_ROW
        Ensures: one POST with the defaults through ApiClient; the card closes; the
                 lookup box looks the new id up
        """
        state = _new_state()
        _check_create_sends_defaults_and_pins_the_row( _open_multiplexer( page, state ), "multiplexer", state )

    def test_a_refusal_keeps_the_card_and_what_was_typed( self, page ):
        """
        Requires: shared test credentials; POST answers 422 with a detail
        Ensures: ApiClient's thrown ApiError still reaches the card as the server's words
        """
        state = _new_state( *REFUSAL )
        _check_refusal_keeps_the_card( _open_multiplexer( page, state ), "multiplexer", state )

    def test_a_server_error_shows_its_cause_not_try_again( self, page ):
        """
        Requires: shared test credentials; POST answers 500 with a detail
        Ensures: "The store answered 500: <detail>" through the ApiClient path
        """
        state = _new_state( *FAILURE )
        _check_server_error_shows_its_cause( _open_multiplexer( page, state ), "multiplexer", state )
