"""
THE COSA-VOICE DESCRIPTIONS SAY WHICH DEADLINE IS RICK'S — row dbe42964, done-means 3.

A relay read `resolves_by` (the 480 s stall deadline) as Rick's answer window (the 120 s
ask timeout) twice on 2026-09-10. These read the REGISTERED descriptions a seat actually
receives for `task_create` and `task_promotion_status`, and tie the numbers to the real
deadline function rather than restating them.

⚠️ READ THROUGH A PINNED-TREE IMPORT, like `test_task_create_describes_the_p0_petition.py`:
a seat's stdio MCP server keeps the description it loaded at seat start.

Venue: :7999-eligible (pure unit — no server, no DB).
"""

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

import lupin_mcp.cosa_voice_mcp as cv
from cosa.rest import task_promotion_gate as promotion_gate
from cosa.rest import task_promotion_resolver as promotion_resolver
from cosa.rest.postgres_models import TaskPromotionTicket
from cosa.rest.routers import tasks


MINTED_AT = datetime( 2026, 9, 10, 12, 0, tzinfo=timezone.utc )


def _flat( text ):
    return " ".join( text.split() )


@pytest.fixture
def status_description():
    return _flat( cv.task_promotion_status.description )


@pytest.fixture
def create_description():
    return _flat( cv.task_create.description )


def _default_deadlines():
    return promotion_resolver.deadlines_for(
        MINTED_AT,
        timeout_fn = lambda: promotion_gate.FALLBACK_ASK_TIMEOUT_SECONDS,
        grace_fn   = lambda: promotion_resolver.FALLBACK_NOTIFICATION_GRACE_SECONDS,
    )


def test_the_descriptions_are_read_from_the_tree_under_test():
    root = os.environ.get( "LUPIN_ROOT" )
    assert root, "LUPIN_ROOT must be pinned"
    assert os.path.realpath( cv.__file__ ).startswith( os.path.realpath( root ) + os.sep )


def test_the_poll_description_names_every_deadline_key_the_poll_returns( status_description ):
    """The keys come from the real serializer, never a hand-written list."""
    ticket = TaskPromotionTicket(
        id=uuid.uuid4(), item_id=uuid.uuid4(), to_status="queued", requested_by="mr radio 1",
        requested_at=MINTED_AT, answer_by=_default_deadlines().answer_by,
        resolves_by=_default_deadlines().resolves_by, state=promotion_resolver.TICKET_PENDING,
    )
    keys = [ k for k in tasks._serialize_ticket( ticket ) if k in ( "answer_by", "resolves_by", "deadlines" ) ]
    assert sorted( keys ) == [ "answer_by", "deadlines", "resolves_by" ], (
        f"the poll's deadline keys are {keys} — this arm would otherwise pass over fewer" )
    for key in keys:
        assert f"`{key}`" in status_description or f"{key} " in status_description, (
            f"the poll returns {key!r} and task_promotion_status never names it" )


def test_the_poll_description_gives_the_window_and_the_stall_as_different_numbers( status_description ):
    deadlines = _default_deadlines()
    window    = int( ( deadlines.answer_by   - MINTED_AT ).total_seconds() )
    stall     = int( ( deadlines.resolves_by - MINTED_AT ).total_seconds() )
    assert window == promotion_gate.FALLBACK_ASK_TIMEOUT_SECONDS
    assert window != stall
    assert f"answer_by when his ANSWER WINDOW closes — the ask timeout ({window}s by default)" in status_description
    assert f"resolves_by the STALL deadline — ask timeout + notification grace + apply margin ({stall}s by default)" in status_description


def test_the_create_description_says_answer_by_is_the_window_to_relay( create_description ):
    window = promotion_gate.FALLBACK_ASK_TIMEOUT_SECONDS
    assert (
        f"`answer_by` is when his answer window closes: the promotion ask timeout ({window}s by default)"
    ) in create_description
    assert "Relay `answer_by`, never `resolves_by`, as his deadline." in create_description


def test_the_create_description_lists_answer_by_in_the_petition_field( create_description ):
    assert 'requesting: "P0", answer_by, resolves_by, deadlines,' in create_description
