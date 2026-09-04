"""
Guard for row 4aca76d9, second half — the fallback must announce itself where
the reader is actually looking.

THE INCIDENT. Rick saw "Received: Mania I want you to" — the first five words
of what he sent, rendered as if it were a summary. A 2026-07-27 fix had already
made that path fail LOUD, and it worked: cc-listeners.log carried
"DEGRADED: gist unavailable" for every occurrence. Nobody read it.

MEASURED, on the delivered record for that exact event — notification
9bb8eef6-2a0f-43a4-b13e-5b034e3e206a, every field opened:

    message   Received: Mania I want you to
    abstract  (EMPTY)          title  (EMPTY)
    type      progress         priority  low
    state     delivered

⇒ The record that reached his screen was byte-for-byte indistinguishable from a
successful gist. A failure that explains itself in a field the reader was never
looking at teaches the reader nothing at all.

WHY THESE TESTS USE THE REAL AsyncNotificationRequest. The existing coverage
suite patches that model with a MagicMock, so it can assert the notification was
SENT but can say nothing about what was IN it — a MagicMock accepts any kwarg
and reports any attribute. These tests construct the real model and read the
real `abstract`, which is the field that reaches the API and the DB column that
was empty in the incident. That is the layer the incident entered at.

THE DISCRIMINATING ARM is test_a_healthy_gist_carries_no_degraded_banner. Without
it, "abstract is stamped" would be satisfied by stamping EVERY notification —
which would make the banner meaningless and is a worse bug than the one fixed.

Created 2026-09-04 — Clayton 😎, row 4aca76d9.
"""

from unittest.mock import MagicMock, patch

import pytest

import lupin_cli.claude_code.hooks.lib.cc_notification_listener as listener_module
from lupin_cli.claude_code.hooks.lib.cc_notification_listener import CCNotificationListener


# The utterance and the head-of-string from the incident record.
INCIDENT_TEXT       = "Mania I want you to look into the notification client for me please"
INCIDENT_FIVE_WORDS = "Mania I want you to"


@pytest.fixture
def listener():
    """A listener with an explicit tmux override — no bridge lookup, no WS connect."""
    lst = CCNotificationListener(
        email           = "service@lupin.deepily.ai",
        password        = "",             # never used — nothing connects in these tests
        session_id_hash = "abc12345",
        tmux_session    = "test tmux",
        host            = "localhost",
        port            = 7999,
    )
    lst._log = MagicMock()
    return lst


def _send_and_capture( listener, notification, gister_patch ):
    """
    Drive the REAL _send_gist_response and return the REAL request object it built.

    Ensures:
        - AsyncNotificationRequest is NOT mocked — the returned object is the
          real Pydantic model, so `.abstract` is the value that would reach the API
        - notify_user_async is stubbed, so nothing leaves the process

    Returns:
        The AsyncNotificationRequest instance passed to notify_user_async.
    """
    captured = {}

    def _capture( request ):
        captured[ "request" ] = request

    with gister_patch, \
         patch( "lupin_cli.notifications.notify_user_async.notify_user_async", _capture ), \
         patch.object( listener_module, "build_sender_id_for_cc",
                       return_value="claude.code@lupin.deepily.ai#abc12345" ):
        listener._send_gist_response( notification )

    assert "request" in captured, "precondition: notify_user_async was never reached"
    return captured[ "request" ]


class TestADegradedGistSaysSoOnTheCard:
    """
    Ensures:
        - A Gister exception stamps `abstract` with a DEGRADED banner naming the cause
        - An empty gist (no exception) is also banner-stamped, with its own wording
        - The message still carries the 5-word head (the fallback itself is unchanged)
        - A HEALTHY gist leaves `abstract` None — the banner means something
    """

    def test_a_gister_exception_stamps_the_abstract_with_the_cause( self, listener ):
        """
        The incident's exact shape: Gister raises, the 5-word head ships.

        Ensures:
            - abstract is not None (the empty-abstract defect is closed)
            - it warns it is NOT a model-generated gist
            - it names the actual exception, so the card says WHY
            - the message is still the 5-word head — the fallback is unchanged
        """
        request = _send_and_capture(
            listener,
            { "message": INCIDENT_TEXT, "sender_id": "user@x.com" },
            patch( "cosa.memory.gister.Gister",
                   side_effect=RuntimeError( "fe_sendauth: no password supplied" ) ),
        )

        assert request.message == f"Received: {INCIDENT_FIVE_WORDS}"
        assert request.abstract is not None, "the delivered record must not be silent"
        assert "DEGRADED" in request.abstract
        assert "NOT a model-generated gist" in request.abstract
        assert "fe_sendauth: no password supplied" in request.abstract
        assert "RuntimeError" in request.abstract

    def test_an_empty_gist_without_an_exception_is_also_stamped( self, listener ):
        """
        The other way the fallback fires: get_gist returns "" and raises nothing.

        Ensures:
            - abstract is still stamped (the banner does not depend on an exception)
            - the wording says so explicitly rather than naming a phantom error
        """
        gister_inst = MagicMock()
        gister_inst.get_gist.return_value = ""

        request = _send_and_capture(
            listener,
            { "message": INCIDENT_TEXT, "sender_id": "user@x.com" },
            patch( "cosa.memory.gister.Gister", return_value=gister_inst ),
        )

        assert request.abstract is not None
        assert "DEGRADED" in request.abstract
        assert "no exception raised" in request.abstract

    def test_a_healthy_gist_carries_no_degraded_banner( self, listener ):
        """
        The discriminating control. Without this arm, stamping EVERY notification
        would satisfy both tests above — and a banner on every card is a banner
        that means nothing.

        Ensures:
            - A successful gist ships with abstract None
            - The message is the model's gist, not a head-of-string
        """
        gister_inst = MagicMock()
        gister_inst.get_gist.return_value = "Looking into the notification client"

        request = _send_and_capture(
            listener,
            { "message": INCIDENT_TEXT, "sender_id": "user@x.com" },
            patch( "cosa.memory.gister.Gister", return_value=gister_inst ),
        )

        assert request.abstract is None, "a healthy gist must NOT be branded degraded"
        assert request.message == "Received: Looking into the notification client"
        assert INCIDENT_FIVE_WORDS not in request.message

    def test_the_abstract_actually_reaches_the_api_params( self, listener ):
        """
        A stamped field nobody transmits is the same defect one level down.

        Ensures:
            - to_api_params() carries the banner, so it reaches the notifications
              row's `abstract` column — the field measured EMPTY in the incident
        """
        request = _send_and_capture(
            listener,
            { "message": INCIDENT_TEXT, "sender_id": "user@x.com" },
            patch( "cosa.memory.gister.Gister", side_effect=RuntimeError( "boom" ) ),
        )

        params = request.to_api_params()
        assert "abstract" in params, "the banner never leaves the process"
        assert "DEGRADED" in params[ "abstract" ]
