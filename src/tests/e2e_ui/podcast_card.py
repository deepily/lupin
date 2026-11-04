"""
The podcast card for browser tests: built by the door's functions, seeded, read back.

Requires:
    - the test database is the one the server under test uses
"""

import uuid
from datetime import datetime, timedelta, timezone

DOC            = "lupin/README.md"
ASKER_SESSION  = "e2e0pod1"
SENDER_ID      = f"claude.code@lupin.deepily.ai#{ASKER_SESSION}"


def build_card():
    """
    Build the card's text and facts with the door's own builders.

    Ensures: returns ( question, abstract, payload ); nothing is written anywhere.
    """
    from cosa.rest import podcast_proxy as proxy

    facts    = proxy.check_source( DOC )
    asker    = proxy.asker_label( ASKER_SESSION, "Tiffany" )
    payload  = proxy.card_payload( facts, asker, ASKER_SESSION )
    question, abstract = proxy.card_text( payload )
    return question, abstract, payload


def seed_waiting_card( email, question, abstract, payload ):
    """
    Write one waiting card for `email`, as the ask door does, and return its id.

    Ensures: the row is built from the given door-builder text and payload; only the recipient differs from the door's.
    """
    from cosa.rest import podcast_proxy as proxy
    from cosa.rest.db.database import get_db
    from cosa.rest.db.repositories.notification_repository import NotificationRepository
    from cosa.rest.user_service import get_user_by_email

    age  = proxy.max_age_seconds()
    user = get_user_by_email( email )
    assert user is not None, f"the test account {email} must exist before a card can be sent to it"

    with get_db() as session:
        card = NotificationRepository( session ).create_notification(
            sender_id          = SENDER_ID,
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
        return str( card.id )


def stored_answer( card_id ):
    """Read the card's stored state and answer straight from the test database."""
    from cosa.rest.db.database import get_db
    from cosa.rest.postgres_models import Notification

    with get_db() as session:
        row = session.get( Notification, uuid.UUID( card_id ) )
        return row.state, row.response_value
