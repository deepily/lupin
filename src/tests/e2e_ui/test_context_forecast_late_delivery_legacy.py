"""
E2E UI - the late context forecast on the legacy notifications page.

The legacy page and the multiplexer show the same card. With the display switch on, the fold carries a child that
reads "Haiku forecast: still forecasting". The background job answers later, and the answer reaches the card two
ways. The server sends prediction_hint_updated to an open card. A fold opened afterwards reads
GET /api/notify/prediction-hint/{id}.

This file drives the script the server actually serves, in a real browser. The card is made by the page's own
handleNotificationUpdate, and the late frame goes through its own handleQueueMessage dispatcher, the function a
WebSocket frame reaches. The fetch is answered by the browser's route table, so no model runs and nothing is stored.

What the test covers, on three cards (the page is loaded again between them, so each is the only card):
  - a card open on "still forecasting" is updated in place by the late frame, and its fold stays open
  - a fold opened after the card was painted reads the prediction-hint route, and shows what it returns
  - a late frame for a closed fold changes its text and leaves it closed
  - none of this selects an option or sends anything but the seen report

Venue: :8000 (scheduled). Run it only once the client half of the late forecast is on the served script.
This file is in half B (src/tests/e2e_ui/partition/half-b.txt), so the suite is `e2e_b`.
"""

from __future__ import annotations

import json

from .conftest import BASE_URL, wait_for_ws_connected
from .test_prediction_forecast_fold_e2e import SEEN_ROUTE, _hint, _watch_posts

HINT_ROUTE   = "/api/notify/prediction-hint/"
EVENT_TYPE   = "prediction_hint_updated"
CARD_ROOT    = "#action-required-content"
FOLD         = f'{ CARD_ROOT } details[data-testid="prediction-hint-fold"]'
CONTEXT      = f'{ FOLD } [data-testid="prediction-hint-context"]'
FORECASTING  = "Haiku forecast: still forecasting"
READY_YES    = "Haiku forecast: Yes (90%)"
READY        = { "state": "ready", "retrieval_metric": "dot", "strategy": "context_baseline", "predicted_value": "yes", "confidence": 0.9 }

_PAINT_JS = """( args ) => {
    window.notificationsUI.handleNotificationUpdate( {
        notification: {
            id                 : args.nid,
            id_hash            : args.nid,
            type               : 'custom',
            response_requested : true,
            response_type      : 'yes_no',
            message            : 'Deploy to prod?',
            timeout_seconds    : 300,
            sender_id          : 'claude.code@lupin.deepily.ai#latefc1',
            prediction_hint    : args.hint,
        }
    } );
}"""

_LATE_JS = """( args ) => window.notificationsUI.handleQueueMessage( {
    data : JSON.stringify( { type: args.type, notification_id: args.nid, context_forecast: args.payload } )
} )"""


def _fresh_page( page ):
    """Load the legacy page again, so the card made next is the only one on it.

    The page saves its action-required queue in localStorage and restores it on load.
    The earlier card would come back first and show its own fold instead of the new card's.
    """
    page.evaluate( "() => window.localStorage.removeItem( 'notifications_action_required' )" )
    page.add_init_script( "window.localStorage.removeItem( 'notifications_action_required' )" )
    page.goto( f"{ BASE_URL }/app/notifications?classic=1" )
    page.wait_for_load_state( "networkidle" )
    wait_for_ws_connected( page )


def _paint_card_with_pending_forecast( page, nid ):
    """Paint a yes/no card whose context forecast is still being made, and return its fold."""
    hint = _hint( "ready" )
    hint[ "context_forecast" ] = { "state": "forecasting" }
    page.evaluate( _PAINT_JS, { "nid": nid, "hint": hint } )
    page.wait_for_selector( FOLD, timeout=10000 )
    fold = page.locator( FOLD )
    assert fold.count() == 1, f"{ nid }: the card has no fold"
    assert fold.evaluate( "el => el.open" ) is False, f"{ nid }: the fold must start closed"
    return fold


def _deliver_late_forecast( page, nid, payload ):
    page.evaluate( _LATE_JS, { "type": EVENT_TYPE, "nid": nid, "payload": payload } )


def _wait_for_context_state( page, state ):
    page.wait_for_function(
        "( args ) => { const el = document.querySelector( args.selector ); return el && el.getAttribute( 'data-context-state' ) === args.state; }",
        arg={ "selector": CONTEXT, "state": state }, timeout=10000,
    )


class TestLegacyLateForecast:

    def test_a_late_forecast_reaches_an_open_fold_a_later_fold_and_a_closed_fold( self, notifications_page ):
        page  = notifications_page
        posts = _watch_posts( page )

        # 1. An open fold on "still forecasting" is updated in place and stays open.
        fold = _paint_card_with_pending_forecast( page, "e2elate-legacy-open" )
        assert page.locator( CONTEXT ).get_attribute( "data-context-state" ) == "forecasting"
        assert page.locator( CONTEXT ).text_content().strip() == FORECASTING
        fold.locator( "summary" ).click()
        assert fold.evaluate( "el => el.open" ) is True
        _deliver_late_forecast( page, "e2elate-legacy-open", READY )
        _wait_for_context_state( page, "ready" )
        assert page.locator( CONTEXT ).text_content().strip() == READY_YES
        assert fold.evaluate( "el => el.open" ) is True, "the late forecast closed a fold the reader had opened"
        assert page.locator( f"{ CARD_ROOT } .selected" ).count() == 0, "a late forecast selected a control"

        # 2. A fold opened later reads the route. The browser's route table answers it, so the server is not asked.
        later_id = "e2elate-legacy-fetch"
        page.route( f"**{ HINT_ROUTE }{ later_id }", lambda route: route.fulfill(
            status=200, content_type="application/json",
            body=json.dumps( { "status": "success", "notification_id": later_id, "context_forecast": READY } ) ) )
        _fresh_page( page )
        fold = _paint_card_with_pending_forecast( page, later_id )
        with page.expect_request( lambda r: r.method == "GET" and f"{ HINT_ROUTE }{ later_id }" in r.url ):
            fold.locator( "summary" ).click()
        _wait_for_context_state( page, "ready" )
        assert page.locator( CONTEXT ).text_content().strip() == READY_YES

        # 3. A late frame for a closed fold changes its text and leaves it closed.
        _fresh_page( page )
        fold = _paint_card_with_pending_forecast( page, "e2elate-legacy-closed" )
        _deliver_late_forecast( page, "e2elate-legacy-closed", { "state": "forecast_timed_out" } )
        _wait_for_context_state( page, "forecast_timed_out" )
        assert page.locator( CONTEXT ).text_content().strip() == "Haiku forecast timed out"
        assert fold.evaluate( "el => el.open" ) is False, "a late frame opened a fold the reader had not opened"

        # Nothing here answered a card: the only POSTs are the seen reports.
        others = [ r.url for r in posts if SEEN_ROUTE not in r.url ]
        assert others == [], f"late delivery sent something besides the seen report: { others }"
