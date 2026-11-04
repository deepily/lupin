"""
The "Make a podcast" card on the legacy page, drawn and answered.

The card reaches the page two ways, and each has a case. Pushed: the page is open, the card is filed through
the real `POST /api/notify` as the test account, and the page draws it. Filed before the page opened: the row
is already waiting, and the page draws it from `GET /api/notifications/awaiting-response` at load.
The second used to draw nothing. Rick would not have met a card sent while he was away.

The title, question and abstract come from the podcast door's own builders.
Those are `check_source`, `asker_label`, `card_payload` and `card_text`.
A builder that drops the file's name or size reddens the page asserts below.
The waiting row is written with the door's own repository call, with the test account as recipient.

Not covered: the pushed card's stored row carries no payload, because the notify route has no payload field.
So the operator-only answer gate and the start door are not exercised.
Nothing here starts a podcast. The page only posts to `/api/notify/response`, so no job is queued and no audio is bought.

Venue: port 8000, scheduled through `POST /api/v2/submit` with test type `e2e_b`. The file is listed
in `partition/half-b.txt`.
"""

import json

import pytest
import requests

from cosa.rest.podcast_proxy import human_size

from .conftest import BASE_URL, wait_for_ws_connected
from .podcast_card import SENDER_ID, build_card, seed_waiting_card, stored_answer

_RESPONSE_ROUTE = "/api/notify/response"


def _push_card( page, email, question, abstract ):
    """
    Push the card to the open page through the real notify route.

    Ensures: returns ( response, frames, card_id ); the stream stays open, so the caller reads the answer frame and closes it.
    """
    token = page.evaluate( "() => localStorage.getItem( 'lupin_access_token' )" )
    resp  = requests.post(
        f"{BASE_URL}/api/notify",
        params  = {
            "message"            : question,
            "abstract"           : abstract,
            "title"              : "Make a podcast",
            "type"               : "custom",
            "priority"           : "high",
            "target_user"        : email,
            "response_requested" : "true",
            "response_type"      : "yes_no",
            "response_default"   : "no",
            "timeout_seconds"    : 120,
            "sender_id"          : SENDER_ID,
            "suppress_ding"      : "true",
            "human_only"         : "true",
        },
        headers = { "Authorization": f"Bearer {token}" },
        stream  = True,
        timeout = 20,
    )
    assert resp.status_code == 200, f"notify POST failed: {resp.status_code} {resp.text[ :300 ]}"
    frames = (
        json.loads( line[ len( "data:" ): ].strip() )
        for line in resp.iter_lines( decode_unicode=True )
        if line and line.startswith( "data:" )
    )
    ack = next( frames, None )
    assert ack is not None and ack.get( "status" ) == "ack", f"first stream frame was not the ack: {ack}"
    return resp, frames, ack[ "notification_id" ]


def _open_legacy_page( page ):
    page.goto( f"{BASE_URL}/app/notifications?classic=1" )
    page.wait_for_load_state( "networkidle" )
    wait_for_ws_connected( page )


def _assert_card_drawn( card, question, payload ):
    """The card shows the builder's question, the file's name and size, and three buttons."""
    card.wait_for( state="visible", timeout=15000 )

    # The question element alone, since the abstract below it also names the file and its size.
    # The name and size come from the measured file, not card_text, so a builder that drops one reddens here.
    drawn = card.locator( ".action-required-message" ).inner_text()
    assert question in drawn, "the card must show the builder's question"
    assert payload[ "name" ] in drawn
    assert human_size( payload[ "size" ] ) in drawn
    assert card.locator( ".response-button.yes" ).count() == 1
    assert card.locator( ".response-button.no" ).count() == 1
    assert card.locator( ".response-button.neither" ).count() == 1
    assert "default-value" in ( card.locator( ".response-button.no" ).get_attribute( "class" ) or "" ), \
        "the card's default is No, so No carries the default mark"


def _tap( page, card, card_id, answer ):
    """Tap the answer, check what the page posted, and wait for the card to go."""
    with page.expect_request( lambda r: r.url.endswith( _RESPONSE_ROUTE ) and r.method == "POST", timeout=10000 ) as sent:
        card.locator( f".response-button.{answer}" ).click()

    assert json.loads( sent.value.post_data ) == { "notification_id": card_id, "response_value": answer }, \
        "the tap must post exactly the card id and the word tapped"
    card.wait_for( state="detached", timeout=10000 )


def _assert_stored( card_id, answer ):
    state, stored = stored_answer( card_id )
    assert state == "responded"
    assert stored[ "value" ] == answer, f"the server must have stored {answer!r}, got {stored!r}"


@pytest.mark.parametrize( "answer", [ "yes", "no" ] )
def test_a_pushed_card_is_drawn_and_a_tap_posts_the_answer( logged_in_page, test_user_credentials, answer ):
    page = logged_in_page
    question, abstract, payload = build_card()

    _open_legacy_page( page )

    resp, frames, card_id = _push_card( page, test_user_credentials[ "email" ], question, abstract )
    try:
        card = page.locator( f"#action-required-{card_id}" )
        _assert_card_drawn( card, question, payload )
        _tap( page, card, card_id, answer )
        answered = next( frames, None )
    finally:
        resp.close()

    assert answered is not None, "the asker's stream ended before the answer frame"
    assert answered[ "status" ] == "responded", f"the server did not deliver the answer: {answered}"
    assert answered[ "response" ] == answer, f"the asker received a different answer: {answered}"
    _assert_stored( card_id, answer )


@pytest.mark.parametrize( "answer", [ "yes", "no" ] )
def test_a_card_filed_before_the_page_opened_is_drawn_at_load( logged_in_page, test_user_credentials, answer ):
    page = logged_in_page
    question, abstract, payload = build_card()
    card_id = seed_waiting_card( test_user_credentials[ "email" ], question, abstract, payload )

    _open_legacy_page( page )

    card = page.locator( f"#action-required-{card_id}" )
    _assert_card_drawn( card, question, payload )
    _tap( page, card, card_id, answer )
    _assert_stored( card_id, answer )
