"""
E2E UI - the late context forecast on the multiplexer.

A card opens with its foundation forecast and, with the display switch on, a child of the fold that reads
"Haiku forecast: still forecasting". The background job answers later, and the answer reaches the card two ways.
The server sends prediction_hint_updated to an open card. A fold opened afterwards reads
GET /api/notify/prediction-hint/{id}.

This file drives the multiplexer bundle the server actually serves, in a real browser. The server half is tested
in the unit tier. Here the event enters through the real event bus. The browser's route table answers the fetch,
so no model runs and nothing is stored.

What the test covers, on three cards:
  - a card open on "still forecasting" is updated in place by the late event, and its fold stays open
  - a fold opened after the card was painted reads the prediction-hint route, and shows what it returns
  - a late event for a closed fold changes its text and leaves it closed
  - none of this selects an option or sends anything but the seen report

Venue: :8000 (scheduled). Run it only once the client half of the late forecast is on the served bundle.
This file is in half B (src/tests/e2e_ui/partition/half-b.txt), so the suite is `e2e_b`.
"""

from __future__ import annotations

import json

from .test_multiplexer_action_required_card_parity import _card, _emit, _open_multiplexer
from .test_prediction_forecast_fold_e2e import SEEN_ROUTE, _forget_saved_queue, _hint, _watch_posts

HINT_ROUTE   = "/api/notify/prediction-hint/"
EVENT_TYPE   = "prediction_hint_updated"
CONTEXT_ID   = '[data-testid="prediction-hint-context"]'
FOLD         = 'details[data-testid="prediction-hint-fold"]'
FORECASTING  = "Haiku forecast: still forecasting"
READY_YES    = "Haiku forecast: Yes (90%)"
READY        = { "state": "ready", "retrieval_metric": "dot", "strategy": "context_baseline", "predicted_value": "yes", "confidence": 0.9 }


def _card_with_pending_forecast( page, nid ):
    """Paint a yes/no card whose context forecast is still being made, and return its fold."""
    hint = _hint( "ready" )
    hint[ "context_forecast" ] = { "state": "forecasting" }
    _emit( page, { "id_hash": nid, "response_type": "yes_no", "prediction_hint": hint } )
    fold = _card( page, nid ).locator( FOLD )
    assert fold.count() == 1, f"{ nid }: the card has no fold"
    assert fold.evaluate( "el => el.open" ) is False, f"{ nid }: the fold must start closed"
    return fold


def _deliver_late_forecast( page, nid, payload ):
    """Send prediction_hint_updated through the real event bus, as the server's frame arrives."""
    page.evaluate(
        """( args ) => window.__multiplexerTestHook.eventBus.emit( {
            type    : args.type,
            payload : { notification_id: args.nid, context_forecast: args.payload },
            source  : 'late-forecast-e2e',
            ts      : 1789790400000,
        } )""",
        { "type": EVENT_TYPE, "nid": nid, "payload": payload },
    )


def _context( fold ):
    return fold.locator( CONTEXT_ID )


class TestMultiplexerLateForecast:

    def test_a_late_forecast_reaches_an_open_fold_a_later_fold_and_a_closed_fold( self, logged_in_page ):
        page = logged_in_page
        _forget_saved_queue( page )
        _open_multiplexer( page )
        posts = _watch_posts( page )

        # 1. An open fold on "still forecasting" is updated in place and stays open.
        open_id = "e2elate-open"
        fold    = _card_with_pending_forecast( page, open_id )
        assert _context( fold ).get_attribute( "data-context-state" ) == "forecasting"
        assert _context( fold ).text_content().strip() == FORECASTING
        fold.locator( "summary" ).click()
        assert fold.evaluate( "el => el.open" ) is True
        _deliver_late_forecast( page, open_id, READY )
        page.wait_for_function(
            "( id ) => { const el = document.querySelector( `[data-id-hash=\"${ id }\"] [data-testid=\"prediction-hint-context\"]` ); return el && el.getAttribute( 'data-context-state' ) === 'ready'; }",
            arg=open_id, timeout=10000,
        )
        assert _context( fold ).text_content().strip() == READY_YES
        assert fold.evaluate( "el => el.open" ) is True, "the late forecast closed a fold the reader had opened"
        assert _card( page, open_id ).locator( ".selected" ).count() == 0, "a late forecast selected a control"

        # 2. A fold opened later reads the route. The browser's route table answers it, so the server is not asked.
        later_id = "e2elate-fetch"
        page.route( f"**{ HINT_ROUTE }{ later_id }", lambda route: route.fulfill(
            status=200, content_type="application/json",
            body=json.dumps( { "status": "success", "notification_id": later_id, "context_forecast": READY } ) ) )
        _forget_saved_queue( page )
        _open_multiplexer( page )
        fold = _card_with_pending_forecast( page, later_id )
        with page.expect_request( lambda r: r.method == "GET" and f"{ HINT_ROUTE }{ later_id }" in r.url ):
            fold.locator( "summary" ).click()
        page.wait_for_function(
            "( id ) => { const el = document.querySelector( `[data-id-hash=\"${ id }\"] [data-testid=\"prediction-hint-context\"]` ); return el && el.getAttribute( 'data-context-state' ) === 'ready'; }",
            arg=later_id, timeout=10000,
        )
        assert _context( fold ).text_content().strip() == READY_YES

        # 3. A late event for a closed fold changes its text and leaves it closed.
        closed_id = "e2elate-closed"
        _forget_saved_queue( page )
        _open_multiplexer( page )
        fold = _card_with_pending_forecast( page, closed_id )
        _deliver_late_forecast( page, closed_id, { "state": "forecast_timed_out" } )
        page.wait_for_function(
            "( id ) => { const el = document.querySelector( `[data-id-hash=\"${ id }\"] [data-testid=\"prediction-hint-context\"]` ); return el && el.getAttribute( 'data-context-state' ) === 'forecast_timed_out'; }",
            arg=closed_id, timeout=10000,
        )
        assert _context( fold ).text_content().strip() == "Haiku forecast timed out"
        assert fold.evaluate( "el => el.open" ) is False, "a late event opened a fold the reader had not opened"

        # Nothing here answered a card: the only POSTs are the seen reports.
        others = [ r.url for r in posts if SEEN_ROUTE not in r.url ]
        assert others == [], f"late delivery sent something besides the seen report: { others }"
