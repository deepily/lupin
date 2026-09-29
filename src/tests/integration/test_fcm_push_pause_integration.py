"""
Integration — the global mobile-push pause (row 04186802, split from 7df08e59; design R1.6).

Two halves, because a test process cannot see the SERVER's Firebase call: the live service has no
injected transport and nothing in the API reports a send. So:

    1. TestLivePauseEndpoint — over HTTP against the live test server (:8000). Admin pause, GET
       reads it back, non-admin is refused, resume. Always resumes in a `finally`, so a failing
       assertion cannot leave the server's pushes paused.
    2. TestPauseStopsTheRealSend — in THIS process, the real FcmWakeService + NotificationFifoQueue
       + PushPauseController, a real token row in lupin_db_test, and a recording transport standing
       in for Firebase. Paused notify -> zero transport calls; resume -> the next notify -> one.

Venue: :8000 (scheduled, POST /api/test-suite/submit). NEVER :7999 — half 1 toggles the live
global pause, and half 2 writes a token row and a notification row.
"""

import threading
import time

import pytest
import requests

from tests.integration.conftest import BASE_URL, get_auth_header

PUSH_PAUSE_URL = f"{BASE_URL}/api/fcm/push-pause"
TEST_TOKEN     = "itest-fcm-token-push-pause-r1-6"


class TestLivePauseEndpoint:

    def test_admin_pause_reads_back_and_resume_restores( self, create_test_admin, create_test_user ):
        admin_headers = get_auth_header( create_test_admin[ "access_token" ] )
        user_headers  = get_auth_header( create_test_user[ "access_token" ] )

        before = requests.get( PUSH_PAUSE_URL, headers=admin_headers )
        assert before.status_code == 200
        if before.json()[ "paused" ]:
            pytest.skip( "pushes were already paused before this test started — not ours to resume" )

        try:
            # A non-admin is refused and changes nothing.
            refused = requests.post( PUSH_PAUSE_URL, json={ "paused": True, "minutes": 5 }, headers=user_headers )
            assert refused.status_code == 403
            assert requests.get( PUSH_PAUSE_URL, headers=admin_headers ).json()[ "paused" ] is False

            # `minutes` is a backstop: even if the finally never ran, the server resumes itself.
            paused = requests.post( PUSH_PAUSE_URL, json={ "paused": True, "minutes": 5 }, headers=admin_headers )
            assert paused.status_code == 200
            assert paused.json()[ "paused" ] is True
            assert paused.json()[ "push_enabled" ] is False
            assert paused.json()[ "resumes_at" ] is not None

            read_back = requests.get( PUSH_PAUSE_URL, headers=admin_headers ).json()
            assert read_back[ "paused" ] is True
            assert read_back[ "push_enabled" ] is False
        finally:
            requests.post( PUSH_PAUSE_URL, json={ "paused": False }, headers=admin_headers )

        after = requests.get( PUSH_PAUSE_URL, headers=admin_headers ).json()
        assert after[ "paused" ] is False
        assert after[ "push_enabled" ] == before.json()[ "push_enabled" ]   # the boot-time value, not a hard-coded True


class _LiveConfig:
    """Real in-memory get / set_config, like the ConfigurationManager singleton's — kept private so
    this test never flips the process-wide config the other integration tests read."""

    def __init__( self ):
        self.values = { "fcm wake push enabled": True, "fcm wake debounce seconds": 60 }

    def get( self, key, default=None, return_type=None, silent=False ):
        return self.values.get( key, default )

    def set_config( self, key, value ):
        self.values[ key ] = value


class _RecordingTransport:
    """Stands in for Firebase: records every ( token, payload ) the service tries to send."""

    def __init__( self ):
        self.calls  = []
        self._event = threading.Event()

    def __call__( self, token, data ):
        self.calls.append( ( token, data ) )
        self._event.set()

    def wait_for_call( self, timeout=5.0 ) -> bool:
        return self._event.wait( timeout )


@pytest.fixture
def registered_device( create_test_user ):
    """A real fcm_tokens row for the test user in lupin_db_test; removed afterwards."""
    from cosa.rest.db.database import get_db
    from cosa.rest.db.repositories.fcm_token_repository import FcmTokenRepository

    with get_db() as session:
        FcmTokenRepository( session ).upsert_token( TEST_TOKEN, create_test_user[ "user_id" ], create_test_user[ "email" ] )
    yield create_test_user
    with get_db() as session:
        FcmTokenRepository( session ).delete_token( TEST_TOKEN )


@pytest.fixture
def wired( registered_device ):
    """The real service, queue and controller over one live config and one recording transport."""
    from cosa.rest.db.database import get_db
    from cosa.rest.db.repositories.fcm_token_repository import FcmTokenRepository
    from cosa.rest.fcm_push_pause import PushPauseController
    from cosa.rest.fcm_wake_service import FcmWakeService
    from cosa.rest.notification_fifo_queue import NotificationFifoQueue

    def token_lookup( user_id ):
        with get_db() as session:
            return FcmTokenRepository( session ).get_tokens_for_user( user_id )

    config     = _LiveConfig()
    transport  = _RecordingTransport()
    service    = FcmWakeService( config, token_lookup=token_lookup, mobile_liveness=lambda user_id: False, transport=transport )
    queue      = NotificationFifoQueue( websocket_mgr=None, emit_enabled=False, fcm_wake_service=service )
    controller = PushPauseController( config )

    yield { "user_id": registered_device[ "user_id" ], "service": service, "queue": queue, "controller": controller, "transport": transport }
    service.shutdown()


class TestPauseStopsTheRealSend:

    def test_paused_notification_makes_no_send_and_the_next_one_after_resume_does( self, wired ):
        service, queue, controller, transport = wired[ "service" ], wired[ "queue" ], wired[ "controller" ], wired[ "transport" ]
        user_id = wired[ "user_id" ]

        # Guard the premise: the service really is live, so a zero below means the PAUSE stopped it.
        assert service.enabled is True

        controller.pause( None, "itest", loop=None )   # untimed: no timer, so no event loop is needed
        queue.push_notification( "paused — must not reach Firebase", user_id=user_id )
        assert transport.wait_for_call( timeout=1.0 ) is False
        assert transport.calls == []
        assert service.maybe_send_wake( user_id ) == "paused"

        controller.resume( "itest" )
        queue.push_notification( "resumed — must reach Firebase", user_id=user_id )
        assert transport.wait_for_call( timeout=5.0 ) is True
        assert [ token for token, _ in transport.calls ] == [ TEST_TOKEN ]
