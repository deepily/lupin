"""
The "Make a podcast" card on the multiplexer page, filed before it opened and answered.

The multiplexer took response cards only from a live push, so a card filed while the page was closed was never
drawn. At boot the page now asks `GET /api/notifications/awaiting-response` and the store adds
each waiting card as a push would. This file seeds a waiting row for the test account, opens the page, and taps.

The title, question and abstract come from the podcast door's own builders.
A builder that drops the file's name or size reddens the page asserts.
The row is written with the door's own repository call.

Not covered: a card pushed to the open multiplexer page by the real notify route. Nothing here starts a podcast:
the page only posts to `/api/notify/response`, so no job is queued and no audio is bought.

Venue: port 8000, scheduled through `POST /api/v2/submit` with test type `e2e_a`. The file is listed
in `partition/half-a.txt`.
"""

import json

import pytest

from cosa.rest.podcast_proxy import human_size

from .conftest import BASE_URL
from .podcast_card import build_card, seed_waiting_card, stored_answer

_RESPONSE_ROUTE = "/api/notify/response"


def _open_multiplexer( page ):
    page.goto( f"{BASE_URL}/app/multiplexer" )
    page.wait_for_load_state( "networkidle" )
    page.wait_for_function(
        "() => window.__multiplexerTestHook"
        " && window.__multiplexerTestHook.stores"
        " && window.__multiplexerTestHook.stores.actionRequired",
        timeout=15000,
    )


_PERSONA = { "name": "tiffany", "display_name": "Tiffany", "voice_id": "e2e-voice", "icon": "💍", "color": "#FFD600", "borrowed": False }


def _give_the_card_a_persona( page, card_id, seen ):
    """
    Add a persona to the real answer for one card.

    The persona comes from the session bridge, which the test server lacks for the seeded sender.
    The answer is fetched for real and only that card's `voice_persona` is filled in.
    So the page's own path from the answer to the badge is what the test watches.
    `seen` collects the real answer's keys.
    """
    def patch( route ):
        response = route.fetch()
        body     = response.json()
        for item in body[ "notifications" ]:
            seen.append( sorted( item.keys() ) )
            if item[ "id" ] == card_id: item[ "voice_persona" ] = _PERSONA
        route.fulfill( response=response, json=body )
    page.route( "**/api/notifications/awaiting-response", patch )


@pytest.mark.parametrize( "answer", [ "yes", "no" ] )
def test_a_card_filed_before_the_page_opened_is_drawn_at_load( logged_in_page, test_user_credentials, answer ):
    page = logged_in_page
    question, abstract, payload = build_card()
    card_id = seed_waiting_card( test_user_credentials[ "email" ], question, abstract, payload )

    seen = []
    _give_the_card_a_persona( page, card_id, seen )
    _open_multiplexer( page )

    widget = page.locator( f"[data-testid='multiplexer-action-required'][data-id-hash='{card_id}']" )
    widget.wait_for( state="visible", timeout=15000 )

    drawn = widget.locator( ".action-required-prompt" ).inner_text()
    assert question in drawn, "the card must show the builder's question"
    assert payload[ "name" ] in drawn
    assert human_size( payload[ "size" ] ) in drawn
    assert "voice_persona" in seen[ 0 ], "the real answer must carry the persona key a push carries"
    assert widget.locator( ".persona-badge-name" ).inner_text() == _PERSONA[ "name" ], "the card must show its sender's persona badge"
    assert widget.locator( ".action-required-btn-yes" ).count() == 1
    assert widget.locator( ".action-required-btn-no" ).count() == 1

    with page.expect_response( lambda r: r.url.endswith( _RESPONSE_ROUTE ) and r.request.method == "POST", timeout=10000 ) as sent:
        widget.locator( f".action-required-btn-{answer}" ).click()

    assert json.loads( sent.value.request.post_data ) == { "notification_id": card_id, "response_value": answer }, \
        "the tap must post exactly the card id and the word tapped"
    assert sent.value.ok, f"the server refused the answer: {sent.value.status}"

    state, stored = stored_answer( card_id )
    assert state == "responded"
    assert stored[ "value" ] == answer, f"the server must have stored {answer!r}, got {stored!r}"
