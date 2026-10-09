"""
The "Make a podcast" card on the legacy page, drawn from a stored row and answered.

The ask door files every card to the operator's account. The test account cannot be sent one by the
door. This file seeds the row for the test account instead. The row is built by the door's own
functions (`check_source`, `asker_label`, `card_payload`, `card_text`) and written with the door's own
repository call. The door and the operator-only answer gate are not exercised here.

Nothing here starts a podcast. The page only posts to `/api/notify/response`, and the start door is
never called, so no job is queued and no audio is bought.

One case seeds the row before the page opens. That is how Rick meets a card he was sent while away:
the server drains it when the page connects. The pushed-event path (page open first) is not covered,
because a test process cannot push through the server's socket.

Venue: port 8000, scheduled through `POST /api/v2/submit` with test type `e2e_b`. The file is listed
in `partition/half-b.txt`.
"""

import json

import pytest

from cosa.rest.podcast_proxy import human_size

from .conftest import BASE_URL, wait_for_ws_connected

_DOC            = "lupin/README.md"
_ASKER_SESSION  = "e2e0pod1"
_SENDER_ID      = f"claude.code@lupin.deepily.ai#{_ASKER_SESSION}"
_RESPONSE_ROUTE = "/api/notify/response"


def _seed_podcast_card( email ):
    """
    Write one waiting card for `email`, as the ask door does, and return it.

    Ensures: returns ( card_id, question, payload ); every field comes from the door's builders; only the recipient differs.
    """
    import uuid
    from datetime import datetime, timedelta, timezone

    from cosa.rest import podcast_proxy as proxy
    from cosa.rest.db.database import get_db
    from cosa.rest.db.repositories.notification_repository import NotificationRepository
    from cosa.rest.user_service import get_user_by_email

    facts    = proxy.check_source( _DOC )
    asker    = proxy.asker_label( _ASKER_SESSION, "Tiffany" )
    payload  = proxy.card_payload( facts, asker, _ASKER_SESSION )
    question, abstract = proxy.card_text( payload )
    age      = proxy.max_age_seconds()
    user     = get_user_by_email( email )
    assert user is not None, f"the test account {email} must exist before a card can be sent to it"

    with get_db() as session:
        card = NotificationRepository( session ).create_notification(
            sender_id          = _SENDER_ID,
            sender_persona     = "Tiffany",
            sender_icon        = "💍",
            recipient_id       = uuid.UUID( str( user[ "id" ] ) ),
            message            = question,
            type               = "custom",
            priority           = "high",
            title              = "Make a podcast",
            abstract           = abstract,
            response_requested = True,
            response_type      = "yes_no",
            response_default   = "no",
            timeout_seconds    = age,
            expires_at         = datetime.now( timezone.utc ) + timedelta( seconds=age ),
            payload            = payload,
        )
        card_id = str( card.id )
    return card_id, question, payload


def _open_legacy_page( page ):
    page.goto( f"{BASE_URL}/app/notifications?classic=1" )
    page.wait_for_load_state( "networkidle" )
    wait_for_ws_connected( page )


def _stored_answer( card_id ):
    """Read the card's stored state and answer straight from the test database."""
    import uuid

    from cosa.rest.db.database import get_db
    from cosa.rest.postgres_models import Notification

    with get_db() as session:
        row = session.get( Notification, uuid.UUID( card_id ) )
        return row.state, row.response_value


@pytest.mark.parametrize( "answer", [ "yes", "no" ] )
def test_a_waiting_card_is_drawn_on_load_and_a_tap_posts_the_answer( logged_in_page, test_user_credentials, answer ):
    page = logged_in_page
    card_id, question, payload = _seed_podcast_card( test_user_credentials[ "email" ] )

    _open_legacy_page( page )

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

    state, stored = _stored_answer( card_id )
    assert state == "responded"
    assert stored[ "value" ] == answer, f"the server must have stored {answer!r}, got {stored!r}"
