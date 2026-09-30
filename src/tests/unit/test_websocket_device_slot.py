#!/usr/bin/env python3
"""
Unit — one live /ws/queue slot per (user, device), and supersession (row dc446601).

Tiffany needs mobile "live mode" to hold exactly one queue socket per phone: a
reconnect must displace the phone's previous socket rather than sit beside it,
and the displaced socket must be FULLY deregistered — because the FCM wake fires
only when the device's socket is down, so a half-dead socket that still reads as
connected silently suppresses the wake.

The slot key was a design fork; Mr. Radio ruled it 2026-09-28 21:15 EDT:

    (user_id, device_id) from auth_request, falling back to client_type when
    device_id is absent, and NO SLOT AT ALL for web clients.

That last clause is the load-bearing one. The multiplexer, the legacy client and
the standalone console page (/app/console, a fresh session id per load) can all
be open for one user at once, and a console tab must not kick the multiplexer
off. Giving web clients no slot makes that MECHANICAL — there is no rule to
remember and no arm that could be reached with the wrong input, because a web
session never enters the supersession path at all.

⚠️ ONE MAP, KEYED BY SESSION — deliberately. A slot->session index would be a
second place the truth lives, and the failure it invites is precise: the
displaced socket's own late cleanup evicting its SUCCESSOR from the index,
leaving a live socket that holds no slot. With session->slot only, a disconnect
can pop nothing but its own entry, so that failure is unreachable rather than
guarded. `test_the_displaced_sockets_late_cleanup_cannot_evict_its_successor`
still pins it, because "unreachable by construction" is a claim that should cost
a test.

Venue: :7999 (pure unit — WebSocketManager via __new__, no config, no server).
"""

import asyncio
import os
import sys
from unittest.mock import MagicMock

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.rest import websocket_manager as wsm_module
from cosa.rest.websocket_manager import WebSocketManager, CLOSE_CODE_SUPERSEDED


def _manager():
    """WebSocketManager without the config-heavy __init__ (existing test convention)."""
    mgr = WebSocketManager.__new__( WebSocketManager )
    mgr.active_connections      = {}
    mgr.session_to_user         = {}
    mgr.user_sessions           = {}
    mgr.user_to_email           = {}
    mgr.session_is_admin        = {}
    mgr.session_client_types    = {}
    mgr.cc_transcript_watchers  = {}
    mgr.session_device_slots    = {}
    mgr.resuming_sessions       = set()
    mgr.session_timestamps      = {}
    mgr.session_subscriptions   = {}
    mgr.main_loop               = None
    mgr.single_session_per_user = False
    mgr.available_events        = { "notification_queue_update" }
    return mgr


@pytest.fixture
def closes( monkeypatch ):
    """
    Capture every close the manager SCHEDULES, without an event loop.

    connect()/disconnect() schedule the close through asyncio.run_coroutine_threadsafe
    onto the stored main loop. The loop is what these tests do not have, so the
    scheduler is replaced and the close call itself is read off the socket mock —
    the close CODE is a wire contract Tiffany's client reads, so asserting it is
    not optional.
    """
    scheduled = []
    monkeypatch.setattr( wsm_module.asyncio, "run_coroutine_threadsafe",
                         lambda coro, loop: scheduled.append( coro ) )
    return scheduled


def _live_loop():
    loop = MagicMock( name="main_loop" )
    loop.is_running.return_value = True
    return loop


def _connect( mgr, session_id, user_id="u1", client_type=None, device_id=None ):
    """Connect one socket and hand back the mock so its close() can be read."""
    ws = MagicMock( name=session_id )
    mgr.connect( ws, session_id, user_id, client_type=client_type, device_id=device_id )
    return ws


# ── Slot resolution: who gets a slot, and keyed on what ─────────────────────

class TestSlotResolution:

    def test_mobile_with_a_device_id_is_keyed_on_the_device_id( self ):
        mgr = _manager()
        _connect( mgr, "s1", client_type="mobile", device_id="phone-A" )
        assert mgr.device_slot_of( "s1" ) == ( "u1", "phone-A" )

    def test_mobile_WITHOUT_a_device_id_gets_no_slot( self ):
        # Tiffany's revision, 2026-09-28, replacing the client_type fallback this
        # first shipped with. Two phones on one account are indistinguishable
        # without a device id, so they would share one slot and displace each
        # other — and the app IGNORES close codes today and reconnects after ANY
        # close, so that is not one bump but two phones knocking each other off
        # forever. Holding NO slot is strictly better than holding a wrong one.
        mgr = _manager()
        _connect( mgr, "s1", client_type="mobile" )
        assert mgr.device_slot_of( "s1" ) is None

    def test_a_web_client_gets_NO_slot( self ):
        mgr = _manager()
        _connect( mgr, "s1", client_type="web" )
        assert mgr.device_slot_of( "s1" ) is None

    def test_a_client_that_sends_no_marker_at_all_gets_no_slot( self ):
        # The audio WS calls connect() without client_type. Slots are a queue-WS
        # concern; the audio socket must never claim one.
        mgr = _manager()
        _connect( mgr, "s1" )
        assert mgr.device_slot_of( "s1" ) is None

    def test_a_web_client_sending_a_device_id_STILL_gets_no_slot( self ):
        # "No slot for web clients" is the whole clause, not a default that a
        # field can override. A browser that learned to send device_id must not
        # be able to opt itself into displacing anything.
        mgr = _manager()
        _connect( mgr, "s1", client_type="web", device_id="phone-A" )
        assert mgr.device_slot_of( "s1" ) is None

    def test_only_the_exact_string_mobile_earns_a_slot( self ):
        # Same normalization the F-S6-1 client-type marker uses. A check and the
        # thing it checks can agree on the field and disagree on the key.
        mgr = _manager()
        for i, junk in enumerate( ( "Mobile", "MOBILE", " mobile", "mobile ", "ios", "" ) ):
            # device_id supplied throughout, so the ONLY thing under test is the
            # client_type comparison — otherwise the missing-device_id rule could
            # satisfy every case and this would prove nothing.
            _connect( mgr, f"s{i}", client_type=junk, device_id="phone-A" )
            assert mgr.device_slot_of( f"s{i}" ) is None, f"{junk!r} earned a slot"

    def test_the_slot_is_scoped_to_the_user( self ):
        # Two users, same physical device id, two different slots — neither can
        # displace the other.
        mgr = _manager()
        _connect( mgr, "s1", user_id="u1", client_type="mobile", device_id="phone-A" )
        _connect( mgr, "s2", user_id="u2", client_type="mobile", device_id="phone-A" )
        assert mgr.is_connected( "s1" ) and mgr.is_connected( "s2" )
        assert mgr.device_slot_of( "s1" ) != mgr.device_slot_of( "s2" )


# ── Supersession ────────────────────────────────────────────────────────────

class TestSupersede:

    def test_a_new_socket_for_the_same_device_closes_the_old_one_with_4004( self, closes ):
        # 4004, NOT 4001 and NOT 4003 — both were tried and both were taken. 4001 is
        # auth failure, which the browser answers with a pointless token refresh;
        # 4003 is reserved server-side but LIVE on the client, where
        # QueueTransport.ts and notifications.js already render it as
        # permission-denied. A reserved server code can still be a spoken-for
        # client one.
        mgr = _manager()
        mgr.main_loop = _live_loop()
        old = _connect( mgr, "s-old", client_type="mobile", device_id="phone-A" )
        _connect( mgr, "s-new", client_type="mobile", device_id="phone-A" )
        old.close.assert_called_once()
        assert old.close.call_args.kwargs[ "code" ] == CLOSE_CODE_SUPERSEDED == 4004
        assert old.close.call_args.kwargs[ "reason" ] == "superseded"

    def test_the_new_socket_holds_the_slot_and_the_old_one_is_gone( self, closes ):
        mgr = _manager()
        mgr.main_loop = _live_loop()
        _connect( mgr, "s-old", client_type="mobile", device_id="phone-A" )
        _connect( mgr, "s-new", client_type="mobile", device_id="phone-A" )
        assert mgr.is_connected( "s-new" ) is True
        assert mgr.is_connected( "s-old" ) is False
        assert mgr.device_slot_of( "s-new" ) == ( "u1", "phone-A" )
        assert mgr.device_slot_of( "s-old" ) is None

    def test_the_displaced_socket_is_FULLY_deregistered( self, closes ):
        # The amendment's first requirement, and the reason it is not cosmetic: a
        # half-dead socket that survives in ANY of these maps can make the device
        # read as connected and suppress the FCM wake. Every per-session map is
        # asserted, not just the connection.
        mgr = _manager()
        mgr.main_loop = _live_loop()
        _connect( mgr, "s-old", client_type="mobile", device_id="phone-A" )
        _connect( mgr, "s-new", client_type="mobile", device_id="phone-A" )
        assert "s-old" not in mgr.active_connections
        assert "s-old" not in mgr.session_client_types
        assert "s-old" not in mgr.session_device_slots
        assert "s-old" not in mgr.session_subscriptions
        assert "s-old" not in mgr.session_to_user
        assert "s-old" not in mgr.session_timestamps
        assert "s-old" not in mgr.user_sessions.get( "u1", [] )

    def test_a_reconnect_reusing_the_SAME_session_id_still_lands_one_live_socket( self, closes ):
        # A phone that keeps its session id across a reconnect must not end up
        # with the manager holding the dead socket.
        mgr = _manager()
        mgr.main_loop = _live_loop()
        _connect( mgr, "s1", client_type="mobile", device_id="phone-A" )
        new = _connect( mgr, "s1", client_type="mobile", device_id="phone-A" )
        assert mgr.active_connections[ "s1" ] is new
        assert mgr.device_slot_of( "s1" ) == ( "u1", "phone-A" )

    def test_a_DIFFERENT_device_does_not_supersede( self, closes ):
        mgr = _manager()
        mgr.main_loop = _live_loop()
        a = _connect( mgr, "s-a", client_type="mobile", device_id="phone-A" )
        _connect( mgr, "s-b", client_type="mobile", device_id="phone-B" )
        a.close.assert_not_called()
        assert mgr.is_connected( "s-a" ) and mgr.is_connected( "s-b" )

    def test_the_displaced_sockets_late_cleanup_cannot_evict_its_successor( self, closes ):
        # THE RACE THE ROW NAMES. The displaced socket's endpoint coroutine is
        # still parked in receive(); it wakes up later and runs disconnect() for
        # its own id. That must not take the successor's slot or connection with
        # it. Unreachable by construction here — a disconnect pops only its own
        # session's entry — which is exactly why it is worth a test.
        mgr = _manager()
        mgr.main_loop = _live_loop()
        _connect( mgr, "s-old", client_type="mobile", device_id="phone-A" )
        _connect( mgr, "s-new", client_type="mobile", device_id="phone-A" )
        mgr.disconnect( "s-old" )   # the late cleanup, arriving after the handover
        assert mgr.is_connected( "s-new" ) is True
        assert mgr.device_slot_of( "s-new" ) == ( "u1", "phone-A" )
        assert mgr.has_live_mobile_session( "u1" ) is True


# ── The fallback is NOT a slot: two device-id-less phones coexist ───────────

class TestNoSupersedeWithoutADeviceId:

    def test_two_fallback_sockets_for_one_user_BOTH_stay_open( self, closes ):
        # Tiffany's requirement. Superseding here would not be one displacement:
        # the app ignores close codes today and reconnects after ANY close, so two
        # phones would knock each other off forever, and every reconnect re-opens
        # the loop. Neither socket holds a slot, so neither can start it.
        mgr = _manager()
        mgr.main_loop = _live_loop()
        first  = _connect( mgr, "s-phone-1", client_type="mobile" )
        second = _connect( mgr, "s-phone-2", client_type="mobile" )
        first.close.assert_not_called()
        second.close.assert_not_called()
        assert mgr.is_connected( "s-phone-1" ) and mgr.is_connected( "s-phone-2" )
        assert mgr.get_user_connection_count( "u1" ) == 2

    def test_a_device_id_socket_does_not_displace_a_fallback_one( self, closes ):
        # The fallback holds no slot, so there is nothing for a real device_id to
        # claim from it — they are not competing for the same thing.
        mgr = _manager()
        mgr.main_loop = _live_loop()
        fallback = _connect( mgr, "s-old-app", client_type="mobile" )
        _connect( mgr, "s-new-app", client_type="mobile", device_id="phone-A" )
        fallback.close.assert_not_called()
        assert mgr.is_connected( "s-old-app" ) is True

    def test_both_fallback_sockets_still_report_the_device_as_live( self, closes ):
        # The wake trigger reads the client_type marker, not the slot, so dropping
        # the fallback slot must not have cost these sessions their liveness.
        mgr = _manager()
        mgr.main_loop = _live_loop()
        _connect( mgr, "s-phone-1", client_type="mobile" )
        assert mgr.has_live_mobile_session( "u1" ) is True

    def test_a_stale_fallback_socket_is_bounded_by_the_websocket_ping( self ):
        # María's worry: with no supersede, a stale fallback socket stays
        # registered and suppresses the wake. The bound is uvicorn's own ping —
        # see test_uvicorn_websocket_ping_bound.py, which asserts main.py does not
        # disable it. Named here so a reader of THIS file finds the answer rather
        # than re-deriving the worry.
        mgr = _manager()
        mgr.main_loop = _live_loop()
        _connect( mgr, "s-phone-1", client_type="mobile" )
        mgr.disconnect( "s-phone-1" )
        assert mgr.has_live_mobile_session( "u1" ) is False


# ── Single-session policy: ONE close, carrying 4002 ────────────────────────

class TestSingleSessionPolicyClose:

    def test_the_displaced_session_gets_exactly_one_close_carrying_4002( self, closes ):
        # María's find, and the same race as the supersede path: this used to close
        # the socket here AND again inside disconnect() with the default 1000. Two
        # closes race, and if 1000 wins the client reads a retryable close where the
        # contract says permanent — a deliberate displacement becomes a reconnect
        # loop. call_count is asserted because ONE close is the fix; the code alone
        # would pass with two if the right one happened to land first.
        mgr = _manager()
        mgr.main_loop = _live_loop()
        mgr.single_session_per_user = True
        old = _connect( mgr, "wise penguin", client_type="web" )
        _connect( mgr, "happy cat", client_type="web" )
        assert old.close.call_count == 1, "two closes race and the wrong code can win"
        assert old.close.call_args.kwargs[ "code" ] == 4002
        assert old.close.call_args.kwargs[ "reason" ] == "session_conflict_displaced"
        assert mgr.is_connected( "wise penguin" ) is False

    def test_single_session_policy_off_leaves_both_open( self, closes ):
        # The control. Without it the assertion above is satisfiable by a manager
        # that closes everything all the time.
        mgr = _manager()
        mgr.main_loop = _live_loop()
        old = _connect( mgr, "wise penguin", client_type="web" )
        _connect( mgr, "happy cat", client_type="web" )
        old.close.assert_not_called()


# ── The wake trigger keys on the slot (row requirement 3) ───────────────────

class TestWakeLivenessKeysOnTheSlot:

    def test_after_supersede_the_device_still_reads_as_connected( self, closes ):
        mgr = _manager()
        mgr.main_loop = _live_loop()
        _connect( mgr, "s-old", client_type="mobile", device_id="phone-A" )
        _connect( mgr, "s-new", client_type="mobile", device_id="phone-A" )
        assert mgr.has_live_mobile_session( "u1" ) is True

    def test_when_the_SURVIVING_socket_closes_the_device_reads_as_disconnected( self, closes ):
        # The amendment's named test: after a supersede AND after the new socket
        # closes, the wake path must fire. A displaced socket left registered
        # anywhere would keep this True and silently suppress the wake.
        mgr = _manager()
        mgr.main_loop = _live_loop()
        _connect( mgr, "s-old", client_type="mobile", device_id="phone-A" )
        _connect( mgr, "s-new", client_type="mobile", device_id="phone-A" )
        mgr.disconnect( "s-new" )
        assert mgr.has_live_mobile_session( "u1" ) is False

    def test_a_live_web_session_does_not_keep_the_device_looking_connected( self, closes ):
        # Unchanged F-S6-1 rule, re-pinned here because the slot work touches the
        # same path: a desktop browser must never suppress the phone's wake.
        mgr = _manager()
        mgr.main_loop = _live_loop()
        _connect( mgr, "s-phone", client_type="mobile", device_id="phone-A" )
        _connect( mgr, "s-web", client_type="web" )
        mgr.disconnect( "s-phone" )
        assert mgr.has_live_mobile_session( "u1" ) is False


# ── Web tabs coexist — the clause the ruling turns into a mechanism ─────────

class TestWebTabsAreNeverSuperseded:

    def test_multiplexer_legacy_and_console_all_stay_open_for_one_user( self, closes ):
        mgr = _manager()
        mgr.main_loop = _live_loop()
        mux     = _connect( mgr, "wise penguin",  client_type="web" )
        legacy  = _connect( mgr, "happy cat",     client_type="web" )
        console = _connect( mgr, "clever dolphin", client_type="web" )
        for ws in ( mux, legacy, console ):
            ws.close.assert_not_called()
        assert mgr.get_user_connection_count( "u1" ) == 3

    def test_opening_a_console_tab_does_not_kick_the_multiplexer_off( self, closes ):
        # Stated as its own case because it is the requirement in Mr. Radio's own
        # words, and a reader looking for it should find it by name.
        mgr = _manager()
        mgr.main_loop = _live_loop()
        mux = _connect( mgr, "wise penguin", client_type="web" )
        _connect( mgr, "clever dolphin", client_type="web" )   # the console tab
        mux.close.assert_not_called()
        assert mgr.is_connected( "wise penguin" ) is True

    def test_a_phone_connecting_does_not_close_any_web_tab( self, closes ):
        mgr = _manager()
        mgr.main_loop = _live_loop()
        mux = _connect( mgr, "wise penguin", client_type="web" )
        _connect( mgr, "s-phone", client_type="mobile", device_id="phone-A" )
        mux.close.assert_not_called()
        assert mgr.is_connected( "wise penguin" ) is True

    def test_a_web_tab_cannot_displace_the_phone( self, closes ):
        mgr = _manager()
        mgr.main_loop = _live_loop()
        phone = _connect( mgr, "s-phone", client_type="mobile", device_id="phone-A" )
        _connect( mgr, "wise penguin", client_type="web" )
        phone.close.assert_not_called()
        assert mgr.has_live_mobile_session( "u1" ) is True


# ── The endpoint seam: device_id has to actually REACH connect() ────────────
#
# Everything above drives WebSocketManager directly, and every one of those cases
# would stay green if the router never read `device_id` off auth_request at all —
# a component can be complete, correct, fully covered and never wired. These two
# enter at the endpoint, through the real receive loop and the real auth path.

class _StubMain:
    """Stands in for `lupin_app.main`, which the queue endpoint reads the manager off."""

    def __init__( self, manager ):
        self.websocket_manager = manager
        self.active_tasks      = {}
        self.app_debug         = False
        self.app_verbose       = False


class _AuthSocket:
    """A socket that authenticates with the given auth_request, then disconnects."""

    def __init__( self, auth_message ):
        self._auth = auth_message
        self.sent  = []

    async def accept( self ): pass

    async def close( self, *args, **kwargs ): pass

    async def send_json( self, payload ): self.sent.append( payload )

    async def receive_json( self ): return self._auth

    async def receive_text( self ):
        from fastapi import WebSocketDisconnect
        raise WebSocketDisconnect()


async def _drive_endpoint( monkeypatch, mgr, session_id, auth_message ):
    """Run the real queue endpoint once with this auth_request; return the socket."""
    from unittest.mock import AsyncMock, Mock

    from cosa.rest.routers.websocket import websocket_queue_endpoint

    main_stub         = _StubMain( mgr )
    package_stub      = Mock()
    package_stub.main = main_stub
    monkeypatch.setitem( sys.modules, "lupin_app", package_stub )
    monkeypatch.setitem( sys.modules, "lupin_app.main", main_stub )
    monkeypatch.setattr( "cosa.rest.auth.verify_token",
                         AsyncMock( return_value={ "uid": "u1", "email": "a@b.c" } ) )

    socket = _AuthSocket( auth_message )
    await websocket_queue_endpoint( websocket=socket, session_id=session_id )
    return socket


class TestTheEndpointReadsDeviceId:

    @pytest.mark.asyncio
    async def test_device_id_from_auth_request_reaches_the_slot( self, monkeypatch ):
        mgr = _manager()
        # The endpoint's finally-block disconnects the session it just registered, so
        # the slot is read from the manager's own claim as it happened, not afterwards.
        claimed = {}
        original = mgr.connect
        def spy( *args, **kwargs ):
            original( *args, **kwargs )
            claimed[ "slot" ] = mgr.device_slot_of( kwargs.get( "session_id" ) or args[ 1 ] )
        monkeypatch.setattr( mgr, "connect", spy )

        await _drive_endpoint( monkeypatch, mgr, "wise penguin", {
            "type"        : "auth_request",
            "token"       : "good",
            "client_type" : "mobile",
            "device_id"   : "phone-A"
        } )
        assert claimed[ "slot" ] == ( "u1", "phone-A" ), (
            "the router never passed device_id to connect() — every manager-level "
            "case above stays green in exactly that world"
        )

    @pytest.mark.asyncio
    async def test_a_browser_auth_request_claims_no_slot_through_the_endpoint( self, monkeypatch ):
        mgr = _manager()
        claimed = {}
        original = mgr.connect
        def spy( *args, **kwargs ):
            original( *args, **kwargs )
            claimed[ "slot" ] = mgr.device_slot_of( kwargs.get( "session_id" ) or args[ 1 ] )
        monkeypatch.setattr( mgr, "connect", spy )

        await _drive_endpoint( monkeypatch, mgr, "wise penguin", {
            "type"  : "auth_request",
            "token" : "good"
        } )
        assert claimed[ "slot" ] is None


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
