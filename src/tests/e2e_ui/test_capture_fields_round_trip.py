"""
E2E UI: how each answer was given reaches the stored row (capture fields, input_route).

A card is seeded for the test account as the ask door does. The real multiplexer draws it and a real
click or typing answers it. Then the stored `notifications.response_value` is read back.

Requires:
    - the :8000 server has `notification capture fields enabled = true` for this run. With the switch
      off the stored row carries no route and every test here fails with a message that says so.
    - the multiplexer bundle was rebuilt after the merge (see the bundle-rebuild bug row)

Voice is driven through the store's own `respondAndAwait` with the `voice` route, the same call the card
makes once the microphone has filled the field. The audio capture is outside this change.

Venue: :8000, half A (src/tests/e2e_ui/partition/half-a.txt), suite `e2e_a`.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from .conftest import BASE_URL
from .podcast_card import stored_answer

SENDER_ID = "claude.code@lupin.deepily.ai#e2ecapt1"
SWITCH_HINT = "the stored row has no input_route: turn on `notification capture fields enabled` in the :8000 INI for this run"
QUESTION = { "header": "Database", "question": "Which database?", "multi_select": False,
             "options": [ { "label": "PostgreSQL", "description": "Relational" }, { "label": "SQLite", "description": "Embedded" } ] }


def _seed( email, response_type, options=None, default=None ):
    """
    Write one waiting card for `email` and return its id.

    Requires:
        - the test account exists; response_type is yes_no, open_ended or multiple_choice

    Ensures:
        - the row is built through NotificationRepository.create_notification, as the ask door does
    """
    from cosa.rest.db.database import get_db
    from cosa.rest.db.repositories.notification_repository import NotificationRepository
    from cosa.rest.user_service import get_user_by_email

    user = get_user_by_email( email )
    assert user is not None, f"the test account {email} must exist before a card can be sent to it"
    with get_db() as session:
        card = NotificationRepository( session ).create_notification(
            sender_id=SENDER_ID, sender_persona="Tiffany", sender_icon="💍", recipient_id=uuid.UUID( str( user[ "id" ] ) ),
            message="Capture fields card", type="custom", priority="high", title="Capture fields",
            response_requested=True, response_type=response_type, response_default=default, response_options=options,
            timeout_seconds=300, expires_at=datetime.now( timezone.utc ) + timedelta( seconds=300 ),
        )
        return str( card.id )


def _open( page, card_id ):
    page.goto( f"{BASE_URL}/app/multiplexer" )
    page.wait_for_load_state( "networkidle" )
    widget = page.locator( f"[data-testid='multiplexer-action-required'][data-id-hash='{card_id}']" )
    widget.wait_for( state="visible", timeout=15000 )
    return widget


def _answer( page, widget, act ):
    with page.expect_response( lambda r: r.url.endswith( "/api/notify/response" ) and r.request.method == "POST", timeout=10000 ) as sent:
        act()
    assert sent.value.ok, f"the server refused the answer: {sent.value.status}"
    return sent.value.request.post_data_json


def _stored( card_id ):
    state, stored = stored_answer( card_id )
    assert state == "responded"
    assert "input_route" in stored, SWITCH_HINT
    return stored


def test_a_click_on_yes_is_stored_as_a_click( logged_in_page, test_user_credentials ):
    card_id = _seed( test_user_credentials[ "email" ], "yes_no", default="no" )
    widget  = _open( logged_in_page, card_id )
    body    = _answer( logged_in_page, widget, lambda: widget.locator( ".action-required-btn-yes" ).click() )
    assert body[ "input_route" ] == "click"
    assert _stored( card_id )[ "input_route" ] == "click"


def test_an_answer_through_the_comment_box_is_stored_as_a_comment( logged_in_page, test_user_credentials ):
    card_id = _seed( test_user_credentials[ "email" ], "yes_no", default="no" )
    widget  = _open( logged_in_page, card_id )
    widget.locator( ".yes-no-comment-input" ).fill( "but leave config alone" )
    body = _answer( logged_in_page, widget, lambda: widget.locator( ".action-required-btn-yes" ).click() )
    assert body[ "input_route" ] == "comment"
    assert _stored( card_id )[ "input_route" ] == "comment"


def test_typed_text_is_stored_as_typed( logged_in_page, test_user_credentials ):
    card_id = _seed( test_user_credentials[ "email" ], "open_ended" )
    widget  = _open( logged_in_page, card_id )
    widget.locator( ".action-required-input" ).fill( "a free answer" )
    body = _answer( logged_in_page, widget, lambda: widget.locator( ".action-required-btn-submit" ).click() )
    assert body[ "input_route" ] == "typed"
    assert _stored( card_id )[ "input_route" ] == "typed"


def test_a_click_on_a_listed_option_is_stored_as_a_click( logged_in_page, test_user_credentials ):
    card_id = _seed( test_user_credentials[ "email" ], "multiple_choice", options={ "questions": [ QUESTION ] } )
    widget  = _open( logged_in_page, card_id )
    widget.locator( "input[value='PostgreSQL']" ).check()
    body = _answer( logged_in_page, widget, lambda: widget.locator( ".action-required-btn-submit" ).click() )
    assert body[ "input_route" ] == { "Database": "click" }
    assert _stored( card_id )[ "input_route" ] == { "Database": "click" }


def test_a_typed_answer_equal_to_a_label_is_stored_as_typed( logged_in_page, test_user_credentials ):
    card_id = _seed( test_user_credentials[ "email" ], "multiple_choice", options={ "questions": [ QUESTION ] } )
    widget  = _open( logged_in_page, card_id )
    widget.locator( ".mc-other-radio" ).check()
    widget.locator( ".mc-other-input" ).fill( "PostgreSQL" )
    body = _answer( logged_in_page, widget, lambda: widget.locator( ".action-required-btn-submit" ).click() )
    assert body[ "input_route" ] == { "Database": "typed" }
    stored = _stored( card_id )
    assert stored[ "input_route" ] == { "Database": "typed" } and "PostgreSQL" in stored[ "value" ]


def test_a_voice_route_is_stored_as_voice( logged_in_page, test_user_credentials ):
    card_id = _seed( test_user_credentials[ "email" ], "open_ended" )
    widget  = _open( logged_in_page, card_id )
    _answer( logged_in_page, widget, lambda: logged_in_page.evaluate(
        "( id ) => window.__multiplexerTestHook.stores.actionRequired.respondAndAwait( id, 'spoken words', 'voice' )", card_id ) )
    assert _stored( card_id )[ "input_route" ] == "voice"
