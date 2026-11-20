"""
E2E UI - the draft answer sent when the forecast fold opens.

Opening the forecast fold reports it to the seen route. That report carries `draft_at_reveal`.
It is the answer the card's controls hold at that moment. So the server can tell an answer given
unaided from one changed after the forecast showed. The unit tier checks the reader of the controls
in happy-dom. This file is the part those cannot be: the served bundle in a real browser,
and the request that really leaves it.

What the tests cover:
  - a multiple-choice card with a pick made sends that pick on the fold-open call
  - an open-ended card with typed text sends that text on the fold-open call
  - a yes/no card sends no draft, and neither does the call that reports the render
  - an open-ended card with an empty box sends no draft

The route's stored column and its validation are asserted in the route tests. Here only the browser's
calls are observed.

Venue: :8000 (scheduled). This file is in half B (src/tests/e2e_ui/partition/half-b.txt), so the suite is `e2e_b`.
"""

from __future__ import annotations

import json

from .test_multiplexer_action_required_card_parity import _card, _emit, _open_multiplexer
from .test_prediction_forecast_fold_e2e import SEEN_ROUTE, _hint, _seen_bodies, _watch_posts

_FOLD = 'details[data-testid="prediction-hint-fold"]'


def _open_fold_and_read_bodies( page, nid, posts ):
    """Open the card's fold and return every seen body sent once the fold-open call has left."""
    with page.expect_request( lambda r: SEEN_ROUTE in r.url and "fold_opened" in ( r.post_data or "" ) ):
        _card( page, nid ).locator( _FOLD ).locator( "summary" ).click()
    return _seen_bodies( posts )


def _fold_open_body( bodies ):
    """The one body that reports the fold opening. Fails when there is not exactly one."""
    opened = [ b for b in bodies if b.get( "fold_opened" ) is True ]
    assert len( opened ) == 1, f"expected one fold-open call, got { bodies }"
    return opened[ 0 ]


class TestDraftAtRevealOnTheMultiplexer:

    def test_a_multiple_choice_pick_rides_on_the_fold_open_call( self, logged_in_page ):
        page = logged_in_page
        _open_multiplexer( page )
        posts = _watch_posts( page )
        _emit( page, {
            "id_hash"         : "e2edraft-mc",
            "response_type"   : "multiple_choice",
            "response_options": { "questions": [
                { "header": "db", "question": "Which store?", "options": [ "PostgreSQL", "SQLite" ] },
            ] },
            "prediction_hint" : _hint( "ready", predicted_value = { "answers": { "db": "PostgreSQL" } } ),
        } )
        card = _card( page, "e2edraft-mc" )
        card.locator( '.action-required-option-input[value="SQLite"]' ).check()

        bodies = _open_fold_and_read_bodies( page, "e2edraft-mc", posts )

        opened = _fold_open_body( bodies )
        assert opened[ "draft_at_reveal" ] == { "value": json.dumps( { "answers": { "db": "SQLite" } }, separators = ( ",", ":" ) ) }, (
            f"the fold-open call did not carry the pick as the wire string: { opened }"
        )
        assert { "rendered": True } in bodies, f"the render call must stay a bare report: { bodies }"
        assert card.locator( '.action-required-option-input[value="SQLite"]' ).is_checked(), "reading the draft changed the pick"

    def test_open_ended_typed_text_rides_on_the_fold_open_call( self, logged_in_page ):
        page = logged_in_page
        _open_multiplexer( page )
        posts = _watch_posts( page )
        _emit( page, {
            "id_hash"        : "e2edraft-oe",
            "response_type"  : "open_ended",
            "prediction_hint": _hint( "ready", predicted_value = "ship it" ),
        } )
        box = _card( page, "e2edraft-oe" ).locator( "[data-draft='response']" )
        box.fill( "  hold the release  " )

        bodies = _open_fold_and_read_bodies( page, "e2edraft-oe", posts )

        opened = _fold_open_body( bodies )
        assert opened[ "draft_at_reveal" ] == { "value": "hold the release" }, (
            f"the fold-open call did not carry the typed text, trimmed: { opened }"
        )
        assert { "rendered": True } in bodies, f"the render call must stay a bare report: { bodies }"
        assert box.input_value() == "  hold the release  ", "reading the draft changed what the reader typed"

    def test_a_yes_no_card_sends_no_draft( self, logged_in_page ):
        page = logged_in_page
        _open_multiplexer( page )
        posts = _watch_posts( page )
        _emit( page, { "id_hash": "e2edraft-yn", "response_type": "yes_no", "prediction_hint": _hint( "ready" ) } )

        bodies = _open_fold_and_read_bodies( page, "e2edraft-yn", posts )

        assert _fold_open_body( bodies ) == { "fold_opened": True }, f"a yes/no card must send no draft: { bodies }"
        assert all( "draft_at_reveal" not in b for b in bodies ), f"no seen call may carry a draft: { bodies }"

    def test_an_empty_open_ended_box_sends_no_draft( self, logged_in_page ):
        page = logged_in_page
        _open_multiplexer( page )
        posts = _watch_posts( page )
        _emit( page, { "id_hash": "e2edraft-empty", "response_type": "open_ended", "prediction_hint": _hint( "ready", predicted_value = "ship it" ) } )

        bodies = _open_fold_and_read_bodies( page, "e2edraft-empty", posts )

        assert _fold_open_body( bodies ) == { "fold_opened": True }, f"an empty box must send no draft: { bodies }"
