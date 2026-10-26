"""Repr tests for two ORM models whose repr no other test reads."""

import uuid

from cosa.rest.postgres_models import FcmToken, TaskPromotionTicket


def test_ticket_repr_names_the_ids_the_state_and_the_target_status():
    ticket_id, item_id = uuid.uuid4(), uuid.uuid4()
    ticket = TaskPromotionTicket( id=ticket_id, item_id=item_id, state="pending", to_status="queued" )
    assert repr( ticket ) == (
        f"<TaskPromotionTicket(id={ticket_id}, item_id={item_id}, "
        f"state='pending', to_status='queued')>"
    )


def test_fcm_token_repr_shows_only_the_last_eight_characters_of_the_token():
    secret = "FAKE" + "z" * 20 + "TAIL1234"
    shown  = repr( FcmToken( user_id="u1", platform="android", token=secret ) )
    assert shown == "<FcmToken(user_id='u1', platform='android', token='…TAIL1234')>"
    assert secret not in shown and "zzzz" not in shown
