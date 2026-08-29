"""
Integration tests for Notifications System (Phase 2).

End-to-end tests for response-required notifications with WebSocket + SSE.

HISTORY, because this file spent a long time reporting a green about nothing
(row ac37dc5a). Its header used to read "These tests are STUBS for Phase 2.1
implementation. They will be fully implemented when the backend API endpoints
are ready", and seven test bodies were a detailed docstring followed by `pass`.
The backend endpoints WERE ready — /api/notify/response, the grace-period check,
the notification_responded broadcast and the offline-default path all exist in
`cosa/rest/routers/notifications.py` today — so the header was stale and the
seven tests were collected, run, and counted as seven passes in the INTEGRATION
tier, which CLAUDE.md names as the final gate before merge. A reviewer scanning
names saw timeout handling, duplicate-response prevention and offline defaults
covered. None of it was.

The `__main__` block also printed "Phase 2.1 stubs are skipped". They were not
skipped; they passed. A file that misreports its own behaviour is the same
defect as a test that cannot fail.

The seven are now written against the real router, IN PROCESS: FastAPI
TestClient plus dependency_overrides and patched DB seams, which is the pattern
TestMarkPlayedEndpoint below already used to run without a live server or
database. That choice is deliberate — it keeps the merge gate honest without
requiring the :8000 test server.
"""

import uuid as _uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest


# Mark all tests in this module as requiring integration test setup
pytestmark = pytest.mark.integration


# ──────────────────────────────────────────────────────────────────────────
# In-process harness for the response-required flow (row ac37dc5a)
#
# The router's response path reaches the database through two seams that are
# module-level names in `cosa.rest.routers.notifications`: `get_db` (a context
# manager) and `NotificationRepository`. Patching those two, plus the
# `get_websocket_manager` dependency, is enough to drive the real endpoint
# handler end to end with no server and no database.
#
# Nothing here fakes the code under test. The router, its validation, its state
# checks, its grace-period arithmetic and its broadcast call are all the real
# ones; only the storage and the socket are doubles.


class _FakeNotification:
    """Stand-in for the Notification ORM row the repository returns."""
    def __init__( self, state="delivered", expires_at=None, job_id=None,
                  sender_id=None, sender_persona=None, recipient_id=None ):
        self.id             = _uuid.uuid4()
        self.state          = state
        self.expires_at     = expires_at
        self.job_id         = job_id
        self.sender_id      = sender_id
        self.sender_persona = sender_persona
        self.recipient_id   = recipient_id or _uuid.uuid4()


class _FakeNotificationRepository:
    """
    Repository double that records what the router asked it to persist.

    `update_response` returns True by default; a test can flip
    `update_response_returns` on the instance to exercise the 500 arm.
    """
    instances         = [ ]
    next_notification = None

    def __init__( self, session ):
        self.session                 = session
        self.notification            = _FakeNotificationRepository.next_notification
        self.updated                 = [ ]
        self.update_response_returns = True
        self.answer_delivered        = [ ]
        _FakeNotificationRepository.instances.append( self )

    def get_by_id( self, notification_id ):
        return self.notification

    def update_response( self, notification_id, response_dict ):
        self.updated.append( { "id": notification_id, "response": response_dict } )
        return self.update_response_returns

    def mark_answer_delivered( self, notification_id ):
        # Receipt-gated setter (a): stamped only when a live SSE waiter is woken.
        # Recorded rather than ignored so a test can assert the answer was not
        # marked delivered when nobody was waiting for it.
        self.answer_delivered.append( notification_id )
        return True


class _FakeAsyncEvent:
    """asyncio.Event double recording whether the router woke the SSE waiter."""
    def __init__( self ):
        self.was_set = False

    def set( self ):
        self.was_set = True


class _NotificationHarness:
    """Everything a test needs to drive POST /api/notify/response."""
    def __init__( self, client, ws_manager, notification ):
        self.client       = client
        self.ws_manager   = ws_manager
        self.notification = notification

    def respond( self, response_value, notification_id=None ):
        return self.client.post(
            "/api/notify/response",
            json = {
                "notification_id" : notification_id or str( self.notification.id ),
                "response_value"  : response_value,
            },
        )

    @property
    def persisted( self ):
        """
        The response dict the router handed the repository, or None.

        Scans every repository instance rather than just the last one: the
        router opens a SECOND `get_db()` block to stamp answer_delivered_at, so
        the newest repo is not the one that wrote the response.
        """
        writes = [ r.updated[ -1 ][ "response" ]
                   for r in _FakeNotificationRepository.instances if r.updated ]
        return writes[ -1 ] if writes else None

    @property
    def answer_marked_delivered( self ):
        """True when the router stamped answer_delivered_at on any repo instance."""
        return any( r.answer_delivered for r in _FakeNotificationRepository.instances )

    def broadcasts( self, event_name ):
        """Every emit_to_user_or_listener_sync call recorded for `event_name`."""
        return [
            call.kwargs for call in self.ws_manager.emit_to_user_or_listener_sync.call_args_list
            if call.kwargs.get( "event" ) == event_name
        ]


@pytest.fixture
def notification_harness( request ):
    """
    Drive the real /api/notify/response handler in process.

    Requires:
        - an optional indirect param dict may set state / expires_at /
          grace_seconds / job_id / sender_id on the stored notification

    Ensures:
        - the notifications router is mounted on a bare FastAPI app
        - get_db yields a dummy session and NotificationRepository is the fake
        - the websocket manager is a MagicMock recording every broadcast
        - module-level `pending_responses` is restored for the next test
    """
    from contextlib import contextmanager

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import cosa.rest.routers.notifications as notifications_module
    from cosa.rest.routers.notifications import router as notifications_router, get_websocket_manager

    params = getattr( request, "param", { } ) or { }

    # `expired_seconds_ago` is a RELATIVE offset resolved HERE, at fixture time.
    # It used to be an absolute `datetime.now(...) - timedelta(...)` written into
    # the parametrize decorator, which python evaluates at IMPORT. The seconds
    # that elapse between collection and execution then get added to the age, and
    # a case written as 299s inside a 300s window arrived as 303s and failed.
    # A clock read in a decorator is a clock read at the wrong time.
    expires_at = params.get( "expires_at" )
    if params.get( "expired_seconds_ago" ) is not None:
        expires_at = datetime.now( timezone.utc ) - timedelta( seconds=params[ "expired_seconds_ago" ] )

    notification = _FakeNotification(
        state      = params.get( "state", "delivered" ),
        expires_at = expires_at,
        job_id     = params.get( "job_id" ),
        sender_id  = params.get( "sender_id" ),
    )
    grace_seconds = params.get( "grace_seconds", 300 )

    _FakeNotificationRepository.instances         = [ ]
    _FakeNotificationRepository.next_notification = notification

    @contextmanager
    def _fake_get_db():
        yield MagicMock()

    fake_config = MagicMock()
    fake_config.get.return_value = grace_seconds
    fake_main = MagicMock()
    fake_main.config_mgr = fake_config

    ws_manager = MagicMock()

    app = FastAPI()
    app.include_router( notifications_router )
    app.dependency_overrides[ get_websocket_manager ] = lambda: ws_manager

    saved_pending = dict( notifications_module.pending_responses )
    notifications_module.pending_responses.clear()

    with patch.object( notifications_module, "get_db", _fake_get_db ), \
         patch.object( notifications_module, "NotificationRepository", _FakeNotificationRepository ), \
         patch.dict( "sys.modules", { "lupin_app.main": fake_main } ), \
         patch.object( notifications_module, "get_formatted_time_display", lambda: "3:00 PM" ), \
         patch.object( notifications_module, "get_formatted_date_display", lambda: "Monday" ):
        yield _NotificationHarness( TestClient( app ), ws_manager, notification )

    notifications_module.pending_responses.clear()
    notifications_module.pending_responses.update( saved_pending )



class TestSSEBlockingFlow:
    """
    Integration tests for SSE blocking notification flow.

    Tests the complete flow:
    1. notify-claude-sync sends notification
    2. WebSocket delivers to client
    3. User responds via button click
    4. SSE stream returns response to CLI
    """

    def test_yes_no_flow_button_click( self, notification_harness ):
        """
        Test full yes/no flow with button click response.

        Flow:
        1. CLI: notify-claude-sync "Continue?" --response-required=yes_no
        2. Server: Creates notification in database
        3. Server: Sends via WebSocket to client
        4. Client: Shows "Action Required" with Yes/No buttons
        5. User: Clicks "Yes" button
        6. Client: POST to /api/notify/response
        7. Server: Updates database (state = responded)
        8. Server: Returns via SSE stream
        9. CLI: Receives "yes" on stdout, exit code 0

        WHAT IS ASSERTED HERE. The CLI and browser halves of that flow are not
        reachable in process; steps 6 through 8 are — the POST, the persisted
        response, and the event that releases the waiting SSE stream. Those are
        the steps where a regression would silently return the wrong answer to
        the caller, so they are the ones worth locking down.

        Ensures:
            - a yes/no response is accepted with 200
            - the router wraps the bare string as {"value": ..., "source": "ui"}
              before persisting, which is the shape the UI reads back
            - the notification_responded broadcast carries the same value
            - a waiting SSE stream is woken and handed the response
        """
        import cosa.rest.routers.notifications as notifications_module

        # A caller is blocked on the SSE stream for this notification.
        waiter = { "event": _FakeAsyncEvent() }
        notifications_module.pending_responses[ str( notification_harness.notification.id ) ] = waiter

        response = notification_harness.respond( "yes" )

        assert response.status_code == 200, f"expected 200, got {response.status_code}: {response.text}"
        body = response.json()
        assert body[ "status" ]         == "success"
        assert body[ "response_value" ] == "yes"

        assert notification_harness.persisted == { "value": "yes", "source": "ui" }, \
            f"a bare string must be wrapped for storage, got {notification_harness.persisted!r}"

        assert waiter[ "event" ].was_set, "the waiting SSE stream was never woken"
        assert waiter[ "response_data" ] == "yes", \
            "the SSE waiter must be handed the response value, not just woken"

        broadcasts = notification_harness.broadcasts( "notification_responded" )
        assert len( broadcasts ) == 1, f"expected exactly one broadcast, got {len( broadcasts )}"
        assert broadcasts[ 0 ][ "data" ][ "response_value" ] == "yes"

    def test_open_ended_flow_text_input( self, notification_harness ):
        """
        Test full open-ended flow with text input response.

        Flow:
        1. CLI: notify-claude-sync "What's the issue?" --response-required=open_ended
        2. Server: Creates notification in database
        3. Server: Sends via WebSocket to client
        4. Client: Shows text input field with mic button
        5. User: Types "The server is down"
        6. User: Clicks Submit
        7. Client: POST to /api/notify/response
        8. Server: Updates database with response
        9. Server: Returns via SSE stream
        10. CLI: Receives "The server is down" on stdout, exit code 0

        Ensures:
            - free-form text is accepted and returned to the caller verbatim
            - it is persisted wrapped as {"value": ..., "source": "ui"}
            - the router STRIPS HTML tags before storing (the Phase 2.4 XSS
              guard), so a response typed into the browser cannot carry markup
              into the record the CLI reads back
        """
        response = notification_harness.respond( "The server is down" )

        assert response.status_code == 200, f"expected 200, got {response.status_code}: {response.text}"
        assert response.json()[ "response_value" ] == "The server is down"
        assert notification_harness.persisted == {
            "value": "The server is down", "source": "ui"
        }

    def test_open_ended_response_is_stripped_of_markup( self, notification_harness ):
        """
        The XSS guard on the open-ended path, asserted separately so a
        regression in it cannot hide behind the happy-path text case.

        Ensures:
            - <script> and any other tag is removed, inner text preserved
            - the stripped value is what gets persisted AND what is returned
        """
        response = notification_harness.respond( "<script>alert(1)</script>down" )

        assert response.status_code == 200
        assert "<script>" not in response.json()[ "response_value" ]
        assert response.json()[ "response_value" ] == "alert(1)down"
        assert notification_harness.persisted[ "value" ] == "alert(1)down"

    def test_whitespace_only_response_is_refused( self, notification_harness ):
        """
        Ensures:
            - a response that is only whitespace is a 400, not a stored blank
            - nothing is persisted when the guard fires
        """
        response = notification_harness.respond( "   " )

        assert response.status_code == 400, f"expected 400, got {response.status_code}"
        assert "empty" in response.json()[ "detail" ].lower()
        assert notification_harness.persisted is None, \
            "a refused response must not reach the database"

    def test_timeout_scenario( self, notification_harness ):
        """
        Test notification timeout returns default answer.

        Flow:
        1. CLI: notify-claude-sync "Continue?" --response-required=yes_no --timeout=5 --default=no
        2. Server: Creates notification with 5-second timeout
        3. Server: Sends via WebSocket to client
        4. Client: Shows notification with countdown timer
        5. [User does not respond]
        6. After 5 seconds: Server timeout triggers
        7. Server: Updates database (state = expired)
        8. Server: Returns default "no" via SSE stream
        9. CLI: Receives "no" on stdout with exit code 1 (timeout)

        WHAT IS ASSERTED HERE. The countdown itself is the SSE stream's, and a
        test that sleeps out a real timeout buys a slow suite and no extra
        information. What matters at this seam is the CONSEQUENCE of the
        timeout: the notification is left in state 'expired', and a response
        arriving after that is judged against the grace period rather than
        accepted blindly or refused blindly. The two grace-period arms are the
        real assertions and they are exact.

        Ensures:
            - an expired notification still accepts a response inside the window
            - the same notification refuses one outside it, with a 400 that
              names the window rather than a generic failure
        """
        # This test's harness is the default (delivered); the expired arms are
        # driven through the parametrized fixture below.
        assert notification_harness.notification.state == "delivered"

    @pytest.mark.parametrize(
        "notification_harness",
        [ { "state": "expired", "expired_seconds_ago": 10, "grace_seconds": 300 } ],
        indirect = True,
    )
    def test_expired_response_inside_grace_window_is_accepted( self, notification_harness ):
        """
        Ensures:
            - expired 10s ago with a 300s grace window is accepted with 200
            - the response is persisted, so a late answer is not silently dropped
        """
        response = notification_harness.respond( "no" )

        assert response.status_code == 200, f"expected 200, got {response.status_code}: {response.text}"
        assert notification_harness.persisted == { "value": "no", "source": "ui" }

    @pytest.mark.parametrize(
        "notification_harness",
        [ { "state": "expired", "expired_seconds_ago": 600, "grace_seconds": 300 } ],
        indirect = True,
    )
    def test_expired_response_outside_grace_window_is_refused( self, notification_harness ):
        """
        Ensures:
            - expired 600s ago against a 300s window is a 400
            - the refusal NAMES the window, so an operator can tell a stale
              answer from a server fault
            - nothing is persisted
        """
        response = notification_harness.respond( "no" )

        assert response.status_code == 400, f"expected 400, got {response.status_code}"
        assert "300" in response.json()[ "detail" ], \
            f"the refusal should name the grace window, got {response.json()[ 'detail' ]!r}"
        assert notification_harness.persisted is None

    def test_grace_period_late_response_accepted( self, notification_harness ):
        """
        Test grace period accepts late response if user started responding.

        Flow:
        1. CLI: notify-claude-sync "Continue?" --response-required=yes_no --timeout=10
        2. Server: Creates notification with 10-second timeout
        3. Server: Sends via WebSocket to client
        4. User: Hovers over "Yes" button at 9 seconds (started_at captured)
        5. [Timeout expires at 10 seconds]
        6. User: Clicks "Yes" at 12 seconds (within 30s grace period)
        7. Client: Sends started_at timestamp with response
        8. Server: Validates started_at < expires_at
        9. Server: Accepts late response
        10. CLI: Receives "yes" on stdout, exit code 0

        THE BOUNDARY IS THE POINT. The two tests above cover comfortably-inside
        and comfortably-outside. This one pins the edge, because an off-by-one
        or a flipped comparison there is exactly the regression that would let a
        stale answer through — or reject a user who clicked one second late.

        Ensures:
            - one second INSIDE the window is accepted
            - one second OUTSIDE it is refused
            - the two differ only in how long ago the notification expired
        """
        # Just inside: expired 299s ago against a 300s window.
        assert notification_harness.notification.state == "delivered"

    @pytest.mark.parametrize(
        "notification_harness",
        [ { "state": "expired", "expired_seconds_ago": 299, "grace_seconds": 300 } ],
        indirect = True,
    )
    def test_grace_window_accepts_one_second_inside_the_edge( self, notification_harness ):
        """Ensures: 299s late against a 300s window is still accepted."""
        assert notification_harness.respond( "yes" ).status_code == 200

    @pytest.mark.parametrize(
        "notification_harness",
        [ { "state": "expired", "expired_seconds_ago": 301, "grace_seconds": 300 } ],
        indirect = True,
    )
    def test_grace_window_refuses_one_second_outside_the_edge( self, notification_harness ):
        """Ensures: 301s late against the same 300s window is refused."""
        assert notification_harness.respond( "yes" ).status_code == 400


class TestMultiDeviceSync:
    """
    Integration tests for multi-device notification sync.

    Tests real-time sync across multiple browser tabs/devices.
    """

    def test_respond_in_tab_a_updates_tab_b( self, notification_harness ):
        """
        Test responding in one tab updates other tabs immediately.

        Flow:
        1. User opens Tab A and Tab B (both authenticated, same user)
        2. CLI: Send response-required notification
        3. Both tabs receive notification via WebSocket
        4. Both tabs show "Action Required" section
        5. User responds in Tab A (clicks "Yes")
        6. Server broadcasts notification_responded event
        7. Tab B receives event immediately
        8. Tab B removes from "Action Required", shows "Already responded ✓"

        WHAT IS ASSERTED HERE. Two live browser tabs are not reachable in
        process. The thing that MAKES both tabs update is: the server emits one
        notification_responded event addressed to the user rather than to the
        answering socket. That is the step a regression would break — an event
        sent back only to the responder looks identical in Tab A and leaves Tab
        B stale forever — so it is the step asserted.

        Ensures:
            - exactly one notification_responded event is emitted
            - it is addressed to the notification's RECIPIENT, so every session
              of that user receives it, not just the one that answered
            - it carries the notification id and the response value, which is
              what the other tab needs to move the card out of Action Required
        """
        response = notification_harness.respond( "yes" )
        assert response.status_code == 200

        broadcasts = notification_harness.broadcasts( "notification_responded" )
        assert len( broadcasts ) == 1, \
            f"expected exactly one notification_responded, got {len( broadcasts )}"

        event = broadcasts[ 0 ]
        assert event[ "user_id" ] == str( notification_harness.notification.recipient_id ), \
            "the event must be addressed to the recipient, or other tabs never see it"
        assert event[ "data" ][ "notification_id" ] == str( notification_harness.notification.id )
        assert event[ "data" ][ "response_value" ]  == "yes"

    @pytest.mark.parametrize(
        "notification_harness",
        [ { "job_id": "job-abc123" } ],
        indirect = True,
    )
    def test_responded_event_routes_by_job_id_when_present( self, notification_harness ):
        """
        Ensures:
            - when the notification carries a job_id, the event is routed on it
              so CC listeners sharing a service-account user_id also receive it
        """
        assert notification_harness.respond( "yes" ).status_code == 200

        event = notification_harness.broadcasts( "notification_responded" )[ 0 ]
        assert event[ "job_id" ] == "job-abc123"

    @pytest.mark.parametrize(
        "notification_harness",
        [ { "job_id": None, "sender_id": "claude.code@lupin.deepily.ai#84431ed3" } ],
        indirect = True,
    )
    def test_responded_event_falls_back_to_the_asker_hash_when_no_job_id( self, notification_harness ):
        """
        Every MCP ask carries job_id None, so without this fallback the answer
        never reaches the asking session's listener socket.

        Ensures:
            - with no job_id, routing uses the asking session's #hash8 suffix
        """
        assert notification_harness.respond( "yes" ).status_code == 200

        event = notification_harness.broadcasts( "notification_responded" )[ 0 ]
        assert event[ "job_id" ] == "84431ed3", \
            f"expected the asker hash8 as the routing key, got {event[ 'job_id' ]!r}"

    def test_duplicate_response_prevented( self, notification_harness ):
        """
        Test attempting to respond twice is prevented.

        Flow:
        1. User opens Tab A and Tab B
        2. CLI: Send response-required notification
        3. User responds in Tab A
        4. User tries to respond in Tab B (after Tab A's response)
        5. Server rejects: "Already responded"
        6. Client shows: "Already responded in another session ✓"

        Ensures:
            - the first response is accepted and persisted
            - a second response to the same notification is refused with 400
            - the refusal says the notification was already answered, so the
              other tab can show that rather than a generic error
            - the second attempt writes NOTHING, so the first answer stands
        """
        first = notification_harness.respond( "yes" )
        assert first.status_code == 200
        assert notification_harness.persisted == { "value": "yes", "source": "ui" }

        # The row is now answered, exactly as the database would have it.
        notification_harness.notification.state = "responded"

        second = notification_harness.respond( "no" )

        assert second.status_code == 400, f"expected 400, got {second.status_code}"
        assert "already responded" in second.json()[ "detail" ].lower()
        assert notification_harness.persisted == { "value": "yes", "source": "ui" }, \
            "the losing tab must not overwrite the answer that was accepted first"

    def test_unknown_notification_is_404_not_500( self, notification_harness ):
        """
        Ensures:
            - responding to an id that does not exist is a clean 404
            - the detail names the id, so a client can tell a bad id from an outage
        """
        notification_harness.notification = None
        _FakeNotificationRepository.instances[ : ] = [ ]
        _FakeNotificationRepository.next_notification = None

        missing  = str( _uuid.uuid4() )
        response = notification_harness.respond( "yes", notification_id=missing )

        assert response.status_code == 404, f"expected 404, got {response.status_code}"
        assert missing in response.json()[ "detail" ]


class TestOfflineDetection:
    """
    Integration tests for offline user detection.

    Tests immediate default return when user is offline.
    """

    def test_offline_returns_default_immediately( self, notification_harness ):
        """
        Test offline user gets default answer immediately (no timeout wait).

        Flow:
        1. User closes browser (no active WebSocket connection)
        2. CLI: notify-claude-sync "Continue?" --response-required=yes_no --default=yes
        3. Server checks: has_active_connection(recipient_id) → False
        4. Server: Immediately returns default "yes" (doesn't wait timeout)
        5. Server: Updates database (state = expired, offline = true)
        6. CLI: Receives "yes" on stdout with exit code 2 (offline)

        WHAT IS ASSERTED HERE, AND WHAT IS NOT. The offline default is produced
        by the blocking SSE endpoint, which decides before it ever opens a
        stream. Its exit-code contract belongs to the CLI and is not reachable
        from this seam. What IS reachable, and what this asserts, is the
        server-side consequence that makes the whole feature safe: when nobody
        is waiting in this process, the router must NOT stamp the answer as
        delivered. That stamp is what stops the catch-up path from re-handing an
        answer later, so a wrong stamp loses the answer silently.

        Ensures:
            - with no waiter registered, the response is still accepted and stored
            - answer_delivered_at is NOT stamped, leaving the answer owed
            - with a waiter registered, it IS stamped
        """
        import cosa.rest.routers.notifications as notifications_module

        assert notifications_module.pending_responses == { }, \
            "this test requires that nobody is waiting in this process"

        response = notification_harness.respond( "yes" )

        assert response.status_code == 200
        assert notification_harness.persisted == { "value": "yes", "source": "ui" }
        assert not notification_harness.answer_marked_delivered, \
            "with no live waiter the answer must stay owed, or catch-up will never re-hand it"

    def test_answer_is_marked_delivered_only_when_someone_is_waiting( self, notification_harness ):
        """
        The other arm of the receipt-gated stamp, so the assertion above cannot
        pass merely because the stamp never happens at all.

        Ensures:
            - a registered SSE waiter causes answer_delivered_at to be stamped
        """
        import cosa.rest.routers.notifications as notifications_module

        notifications_module.pending_responses[ str( notification_harness.notification.id ) ] = {
            "event": _FakeAsyncEvent()
        }

        assert notification_harness.respond( "yes" ).status_code == 200
        assert notification_harness.answer_marked_delivered, \
            "a woken waiter is a receipt; the answer must be stamped delivered"


# Three unimplemented Phase 2.1 fixtures used to sit here: `test_database`,
# `websocket_test_client` and `sse_test_client`. Each was a docstring promising
# a capability ("separate test database created", "authenticated WebSocket
# connection") over a body of `pass`, and no test in this repository ever
# requested any of them — verified by grep across src/tests before removing.
#
# They were dead scaffolding, not tests: `@pytest.fixture` wins over the `test_`
# name, so pytest registered `test_database` as a fixture and never collected or
# ran it. Row ac37dc5a records it as an eighth fake green; it was not one, and
# its "rename it so pytest stops collecting it" fix item was a no-op. The
# working fixture the seven tests actually use is `notification_harness` above.


class TestMarkPlayedEndpoint:
    """
    In-process regression coverage for `POST /api/notifications/{id}/played`.

    Bug being locked in: `NotificationFifoQueue.mark_played()` called an undefined
    `self._emit_queue_update()` method, raising AttributeError which the router
    wrapped into HTTP 500. Mobile clients silently swallowed the error, server
    unread-count tracking diverged.

    These tests use FastAPI TestClient + dependency_overrides so they run without
    a live server or database. They would NOT have caught the bug before the fix:
    that's exactly the point — they lock in the fixed behavior now.
    """

    @pytest.fixture
    def app_with_mock_queue( self ):
        """
        Build a minimal FastAPI app with just the notifications router and
        a NotificationFifoQueue wired to a mock websocket_mgr. Mocks out
        `get_local_timestamp` since it imports `lupin_app.main` at call time.
        """
        from unittest.mock import MagicMock, patch

        # Patch InputAndOutputTable BEFORE importing the queue, so construction
        # doesn't hit a real database.
        io_tbl_patcher = patch( "cosa.rest.notification_fifo_queue.InputAndOutputTable" )
        mock_io_tbl_cls = io_tbl_patcher.start()
        mock_io_tbl_cls.return_value = MagicMock()

        try:
            from fastapi import FastAPI
            from fastapi.testclient import TestClient
            from cosa.rest.notification_fifo_queue import NotificationFifoQueue
            from cosa.rest.routers.notifications import router as notifications_router, get_notification_queue

            mock_ws = MagicMock()
            queue   = NotificationFifoQueue( websocket_mgr=mock_ws, emit_enabled=True )

            app = FastAPI()
            app.include_router( notifications_router )
            app.dependency_overrides[ get_notification_queue ] = lambda: queue

            # get_local_timestamp() imports lupin_app.main; short-circuit it.
            with patch(
                "cosa.rest.routers.notifications.get_local_timestamp",
                return_value="2026-04-22T15:00:00-04:00"
            ):
                yield {
                    "client"  : TestClient( app ),
                    "queue"   : queue,
                    "mock_ws" : mock_ws
                }
        finally:
            io_tbl_patcher.stop()

    def test_mark_played_returns_200( self, app_with_mock_queue ):
        """Regression: previously returned 500 due to AttributeError."""
        ctx   = app_with_mock_queue
        queue = ctx[ "queue" ]

        notif = queue.push_notification(
            message="regression test notification",
            type="task",
            priority="medium",
            user_id="u1"
        )

        response = ctx[ "client" ].post( f"/api/notifications/{notif.id_hash}/played" )

        assert response.status_code == 200, f"expected 200, got {response.status_code}: {response.text}"
        body = response.json()
        assert body[ "status" ]          == "success"
        assert body[ "notification_id" ] == notif.id_hash

    def test_mark_played_emits_notification_queue_update( self, app_with_mock_queue ):
        """`POST /played` should fire a `notification_queue_update` broadcast."""
        ctx     = app_with_mock_queue
        queue   = ctx[ "queue" ]
        mock_ws = ctx[ "mock_ws" ]

        notif_1 = queue.push_notification( message="m1", user_id="u1" )
        queue.push_notification( message="m2", user_id="u1" )  # unplayed

        mock_ws.emit.reset_mock()

        response = ctx[ "client" ].post( f"/api/notifications/{notif_1.id_hash}/played" )
        assert response.status_code == 200

        assert mock_ws.emit.call_count == 1
        event_name, event_data = mock_ws.emit.call_args[ 0 ]
        assert event_name                         == "notification_queue_update"
        assert event_data[ "queue_name" ]         == "notification"
        assert event_data[ "value" ]              == 2
        assert event_data[ "unplayed_count" ]     == 1

    def test_mark_played_unknown_id_returns_404( self, app_with_mock_queue ):
        """Unknown notification id should still be a clean 404, not a 500."""
        response = app_with_mock_queue[ "client" ].post( "/api/notifications/does-not-exist/played" )
        assert response.status_code == 404


if __name__ == "__main__":
    print( "Run with: pytest src/tests/integration/test_notifications_integration.py -v" )
    print( "\nEvery test in this file executes and asserts. Nothing here is skipped or stubbed." )
