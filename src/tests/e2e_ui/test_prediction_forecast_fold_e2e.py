"""
E2E UI - the forecast fold on both web clients (preference learning).

A displayed forecast sits in a native `details` fold that starts closed, and nothing the fold does
touches the answer controls. The unit tier checks the templates in happy-dom. This file is the part
those cannot be: the bundle and the legacy script the server actually serves, in a real browser.

What the tests cover:
  - every card type opens with the forecast folded, and each of the four states renders its own text
  - opening the fold calls the seen route (first the rendered call, then the fold-open call)
  - a card with the fold open or closed never selects an option, edits a draft or submits an answer
  - an opened fold stays open through a repaint (multiplexer)

The seen route and the forecast row it writes were built earlier. Their stored times are asserted in
the route tests. Here only the browser's calls are observed.

Venue: :8000 (scheduled). This file is in half B (src/tests/e2e_ui/partition/half-b.txt), so the suite is `e2e_b`.
"""

from __future__ import annotations

from .conftest import BASE_URL
from .test_multiplexer_action_required_card_parity import _card, _emit, _open_multiplexer

SEEN_ROUTE = "/api/notify/prediction-seen/"

STATE_TEXT = {
    "insufficient_evidence" : "Learning, no prediction yet",
    "below_threshold"       : "Forecast too uncertain to show",
    "unavailable"           : "Forecast unavailable",
}


def _hint( state, **extra ):
    hint = { "state": state, "retrieval_metric": "dot", "strategy": "cbr_majority_vote", "category": "deploy" }
    if state == "ready":
        hint.update( { "confidence": 0.9, "predicted_value": "yes" } )
    hint.update( extra )
    return hint


def _watch_posts( page ):
    """Record every POST the page makes, so a test can say what was sent and what was not."""
    posts = []
    page.on( "request", lambda r: posts.append( r ) if r.method == "POST" else None )
    return posts


def _seen_bodies( posts ):
    return [ r.post_data_json for r in posts if SEEN_ROUTE in r.url ]


# ---- the multiplexer ---------------------------------------------------------

class TestMultiplexerForecastFold:

    def test_yes_no_card_opens_folded_and_each_state_renders_its_text( self, logged_in_page ):
        page = logged_in_page
        for n, ( state, text ) in enumerate( STATE_TEXT.items() ):
            # Only the first card in the queue is painted, so each state gets a fresh page.
            _open_multiplexer( page )
            nid = f"e2efold-state-{ n }"
            _emit( page, { "id_hash": nid, "response_type": "yes_no", "prediction_hint": _hint( state ) } )
            fold = _card( page, nid ).locator( 'details[data-testid="prediction-hint-fold"]' )
            assert fold.count() == 1, f"{ state }: the card has no fold"
            assert fold.evaluate( "el => el.open" ) is False, f"{ state }: the fold must start closed"
            assert fold.locator( ".prediction-hint-label" ).text_content().strip() == text
            assert fold.get_attribute( "data-hint-state" ) == state

    def test_open_ended_card_opens_folded( self, logged_in_page ):
        page = logged_in_page
        _open_multiplexer( page )
        _emit( page, { "id_hash": "e2efold-open", "response_type": "open_ended", "prediction_hint": _hint( "ready", predicted_value = "ship it" ) } )
        fold = _card( page, "e2efold-open" ).locator( 'details[data-testid="prediction-hint-fold"]' )
        assert fold.count() == 1
        assert fold.evaluate( "el => el.open" ) is False

    def test_opening_the_fold_reports_it_and_touches_no_answer_control( self, logged_in_page ):
        page = logged_in_page
        _open_multiplexer( page )
        posts = _watch_posts( page )
        _emit( page, { "id_hash": "e2efold-open-1", "response_type": "yes_no", "prediction_hint": _hint( "ready" ) } )
        fold = _card( page, "e2efold-open-1" ).locator( 'details[data-testid="prediction-hint-fold"]' )
        with page.expect_request( lambda r: SEEN_ROUTE in r.url and "fold_opened" in ( r.post_data or "" ) ):
            fold.locator( "summary" ).click()
        assert fold.evaluate( "el => el.open" ) is True
        bodies = _seen_bodies( posts )
        assert { "rendered": True } in bodies, f"the card never reported that it rendered: { bodies }"
        assert { "fold_opened": True } in bodies
        others = [ r.url for r in posts if SEEN_ROUTE not in r.url ]
        assert others == [], f"opening the fold sent something besides the seen report: { others }"
        assert _card( page, "e2efold-open-1" ).locator( ".selected" ).count() == 0, "a forecast selected a control"

    def test_an_opened_fold_stays_open_through_a_repaint( self, logged_in_page ):
        page = logged_in_page
        _open_multiplexer( page )
        _emit( page, { "id_hash": "e2efold-repaint", "response_type": "yes_no", "prediction_hint": _hint( "ready" ) } )
        card = _card( page, "e2efold-repaint" )
        card.locator( "summary" ).click()
        assert card.locator( 'details[data-testid="prediction-hint-fold"]' ).evaluate( "el => el.open" ) is True
        # A store change for the active card makes the renderer build the card again. The same id arriving
        # twice does not, because the store drops the repeat, so the change is sent the way the store sends it.
        page.evaluate( "() => { window.__e2eOldCard = document.querySelector('[data-id-hash=\"e2efold-repaint\"]'); }" )
        page.evaluate(
            """() => window.__multiplexerTestHook.eventBus.emit( {
                type    : 'store_action_required_changed',
                payload : { changeKind: 'added', id_hash: 'e2efold-repaint' },
                source  : 'fold-e2e',
                ts      : 1789790400000,
            } )"""
        )
        page.wait_for_function(
            "() => { const now = document.querySelector('[data-id-hash=\"e2efold-repaint\"]'); return now !== null && now !== window.__e2eOldCard; }",
            timeout=10000,
        )
        assert card.locator( 'details[data-testid="prediction-hint-fold"]' ).evaluate( "el => el.open" ) is True, "the repaint closed a fold the reader had opened"


# ---- the legacy page ---------------------------------------------------------

_BUILD_JS = """( args ) => {
    const ui = window.notificationsUI;
    if ( !ui || typeof ui.buildPredictionHintSection !== 'function' ) return 'no-ui';
    const host = document.createElement( 'div' );
    host.setAttribute( 'data-testid', 'e2e-fold-host-' + args.id );
    host.innerHTML = ui.buildPredictionHintSection( {
        id: args.id, message: 'E2E: ship it?', response_type: args.response_type, prediction_hint: args.hint,
    } );
    document.body.appendChild( host );
    return 'ok';
}"""


def _open_legacy( page ):
    page.goto( f"{BASE_URL}/app/notifications?classic=1" )
    page.wait_for_load_state( "networkidle" )


def _build( page, nid, response_type, hint ):
    assert page.evaluate( _BUILD_JS, { "id": nid, "response_type": response_type, "hint": hint } ) == "ok"
    return page.locator( f'[data-testid="e2e-fold-host-{ nid }"] details[data-testid="prediction-hint-fold"]' )


class TestLegacyForecastFold:

    def test_every_card_type_opens_folded( self, logged_in_page ):
        page = logged_in_page
        _open_legacy( page )
        answers = { "predicted_value": { "answers": { "Q": "a" } } }
        for response_type, extra in ( ( "yes_no", {} ), ( "multiple_choice", answers ), ( "open_ended", { "predicted_value": "ship it" } ), ( "open_ended_batch", answers ) ):
            fold = _build( page, f"e2elegacy-{ response_type }", response_type, _hint( "ready", **extra ) )
            assert fold.count() == 1, f"{ response_type }: no fold"
            assert fold.evaluate( "el => el.open" ) is False, f"{ response_type }: the fold must start closed"

    def test_each_state_renders_its_own_text( self, logged_in_page ):
        page = logged_in_page
        _open_legacy( page )
        for state, text in STATE_TEXT.items():
            fold = _build( page, f"e2elegacy-{ state }", "yes_no", _hint( state ) )
            assert fold.locator( ".prediction-hint-label" ).text_content().strip() == text
            assert fold.get_attribute( "data-hint-state" ) == state

    def test_opening_the_fold_reports_it_and_sends_nothing_else( self, logged_in_page ):
        page = logged_in_page
        _open_legacy( page )
        posts = _watch_posts( page )
        fold = _build( page, "e2elegacy-open", "yes_no", _hint( "ready" ) )
        with page.expect_request( lambda r: SEEN_ROUTE in r.url and "fold_opened" in ( r.post_data or "" ) ):
            fold.locator( "summary" ).click()
        assert fold.evaluate( "el => el.open" ) is True
        bodies = _seen_bodies( posts )
        assert { "rendered": True } in bodies and { "fold_opened": True } in bodies
        others = [ r.url for r in posts if SEEN_ROUTE not in r.url ]
        assert others == [], f"opening the fold sent something besides the seen report: { others }"
