"""
The send response must state what it does NOT know (row 298af249).

`dispatched: True` was being read as "the recipient got it". It is not that — it
goes true the moment the row is persisted and the notification is queued. The
recipient's listener may BUFFER the message while the session is busy, and if the
session ends before a hook drains that buffer, nobody ever reads it.

Measured 2026-08-30: 45 orphaned buffer files holding 67 such messages, oldest
last written 2026-07-02. Every sender was told the send succeeded.

These tests hold the response to stating its own limit.
"""

import pytest

from cosa.rest.routers.dm import _dispatch_outbound


class _Queue:
    def __init__( self ): self.pushed = []
    def push_notification( self, **kw ): self.pushed.append( kw )


class _Body:
    sender_persona = "Tiberius"
    sender_icon    = "👑"
    reply_to       = None
    body           = "KRISHNA'S 88631dc1 — APPROVED, merge by branch name."


def _dispatch( persist_fn=None ):
    prep = ( "sender#f0", "93a8751c", "msg-1", "thr-1", "[stamp] body" )
    return _dispatch_outbound(
        prep                  = prep,
        body                  = _Body(),
        authenticated_user_id = "user-1",
        notification_queue    = _Queue(),
        persist_fn            = persist_fn or ( lambda **kw: "db-1" ),
        target_session_id     = "93a8751c-de87-498b-8846-96479824c933",
        target_persona        = "mr radio",
    )


def test_the_response_carries_an_explicit_delivery_limit():
    """
    The key must be PRESENT. Its absence is what let `dispatched` be read as
    receipt for months — an unstated limit is indistinguishable from no limit.
    """
    assert "delivery_confirmed" in _dispatch()


def test_delivery_is_never_confirmed_at_send_time():
    """
    At this instant the server genuinely does not know, so the only honest value
    is False. A True here would be the original defect wearing a new key.
    """
    assert _dispatch()[ "delivery_confirmed" ] is False


def test_dispatched_still_reports_the_hand_off_it_actually_performed():
    """
    The fix must not overcorrect. The hand-off DID happen and callers rely on
    knowing it; the defect was the missing second fact, not this one.
    """
    assert _dispatch()[ "dispatched" ] is True


def test_the_two_keys_disagree_which_is_the_entire_point():
    """
    A response where both keys said the same thing would carry no more information
    than the single key it replaced.
    """
    out = _dispatch()
    assert out[ "dispatched" ] != out[ "delivery_confirmed" ]


def test_the_limit_is_stated_even_when_the_store_assigns_no_id():
    """
    `db_id` falsy takes the `db_id or message_id` branch. The honesty of the
    response must not depend on which id it happened to return.
    """
    out = _dispatch( persist_fn=lambda **kw: None )
    assert out[ "message_id" ] == "msg-1"
    assert out[ "delivery_confirmed" ] is False
