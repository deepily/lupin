"""
The "Make a podcast" card on the legacy page, pushed to an open page and answered.

The page draws a response card only from a pushed event. A card filed while the page is closed is not drawn
when the page opens. Pocholo's check of that is `io/tmp/2026.10.09-pocholo-check-legacy-page-draws-no-card-at-load.md`.
So this file opens the page first, waits for its socket, and then pushes.

The push goes through the real `POST /api/notify` as the test account. The title, question and abstract
come from the podcast door's own builders. Those are `check_source`, `asker_label`, `card_payload` and `card_text`.
A builder that drops the file's name or size reddens the page asserts below.

Not covered: the stored row carries no payload, because that route has no payload field.
So the operator-only answer gate and the start door are not exercised.
A card filed while the page is closed is not covered either.
Nothing here starts a podcast. The page only posts to `/api/notify/response`, so no job is queued and no audio is bought.

Venue: port 8000, scheduled through `POST /api/v2/submit` with test type `e2e_b`. The file is listed
in `partition/half-b.txt`.
"""

import json

import pytest
import requests

from cosa.rest.podcast_proxy import human_size

from .conftest import BASE_URL, wait_for_ws_connected

_DOC            = "lupin/README.md"
_ASKER_SESSION  = "e2e0pod1"
_SENDER_ID      = f"claude.code@lupin.deepily.ai#{_ASKER_SESSION}"
_RESPONSE_ROUTE = "/api/notify/response"


def _build_card():
    """
    Build the card's text and facts with the door's own builders.

    Ensures: returns ( question, abstract, payload ); nothing is written anywhere.
    """
    from cosa.rest import podcast_proxy as proxy

    facts    = proxy.check_source( _DOC )
    asker    = proxy.asker_label( _ASKER_SESSION, "Tiffany" )
    payload  = proxy.card_payload( facts, asker, _ASKER_SESSION )
    question, abstract = proxy.card_text( payload )
    return question, abstract, payload


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
            "sender_id"          : _SENDER_ID,
            "suppress_ding"      : "true",
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


def _stored_answer( card_id ):
    """Read the card's stored state and answer straight from the test database."""
    import uuid

    from cosa.rest.db.database import get_db
    from cosa.rest.postgres_models import Notification

    with get_db() as session:
        row = session.get( Notification, uuid.UUID( card_id ) )
        return row.state, row.response_value


@pytest.mark.parametrize( "answer", [ "yes", "no" ] )
def test_a_pushed_card_is_drawn_and_a_tap_posts_the_answer( logged_in_page, test_user_credentials, answer ):
    page = logged_in_page
    question, abstract, payload = _build_card()

    page.goto( f"{BASE_URL}/app/notifications?classic=1" )
    page.wait_for_load_state( "networkidle" )
    wait_for_ws_connected( page )

    resp, frames, card_id = _push_card( page, test_user_credentials[ "email" ], question, abstract )
    try:
        card = page.locator( f"#action-required-{card_id}" )
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

        with page.expect_request( lambda r: r.url.endswith( _RESPONSE_ROUTE ) and r.method == "POST", timeout=10000 ) as sent:
            card.locator( f".response-button.{answer}" ).click()

        assert json.loads( sent.value.post_data ) == { "notification_id": card_id, "response_value": answer }, \
            "the tap must post exactly the card id and the word tapped"
        card.wait_for( state="detached", timeout=10000 )

        answered = next( frames, None )
    finally:
        resp.close()

    assert answered is not None, "the asker's stream ended before the answer frame"
    assert answered[ "status" ] == "responded", f"the server did not deliver the answer: {answered}"
    assert answered[ "response" ] == answer, f"the asker received a different answer: {answered}"

    state, stored = _stored_answer( card_id )
    assert state == "responded"
    assert stored[ "value" ] == answer, f"the server must have stored {answer!r}, got {stored!r}"
