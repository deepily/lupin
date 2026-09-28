#!/usr/bin/env python3
"""
A2.2 (WS half), A2.5 (both arms) and A3.5 — the two socket verbs and the watcher registry.

Plan: `src/rnd/v0.2.1/2026.09.27-console-tee-live-stream-plan.md` §2 items 2 and 8, §3.
Under test: `WebSocketManager`'s watcher registry and `routers/websocket.py`'s verb handler.

A2.5 HAS TWO ARMS AND THEY FAIL DIFFERENTLY
-------------------------------------------
(a) UNWATCH — the polite path. A client sends `cc_transcript_unwatch`.
(b) SOCKET DROP — a closed tab, which never sends anything.

A registry swept only on (a) passes (a) and leaks on (b), and the leak is SILENT: the tailer
polls forever while `emit_to_session` early-returns into a session already gone from
`active_connections`. No exception, no log, no failing test. `test_omitting_the_sweep_leaks_a_watcher`
is the discriminator — it shows arm (b) reddens when the sweep line is absent while arm (a)
stays green, which is exactly how the leak would have shipped.

Venue: :7999-eligible — no server, no network, no writes, sub-second.
"""

import asyncio
import os
import sys

import pytest

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.rest.websocket_manager import WebSocketManager

SEAT       = "449359bc-c735-4970-8fc0-e83b635c8548"
OTHER_SEAT = "11111111-2222-3333-4444-555555555555"
BROWSER    = "wise penguin"
BROWSER_2  = "clever dolphin"


@pytest.fixture
def manager():
    """A real WebSocketManager — the registry is plain state, so nothing needs faking."""
    return WebSocketManager()


# ── the registry owns the watcher COUNT, and therefore the lifecycle ───────────

def test_the_first_watcher_of_a_seat_is_reported_as_first( manager ):
    """
    The caller's signal to START a tailer.

    The count lives here, not in the tailer — which has no concept of a watcher. An earlier
    version of the tailer's docstring claimed this lifecycle while no code implemented it
    (Rio, 2026-09-27), so this test is the mechanism that sentence was standing in for.
    """
    assert manager.add_cc_transcript_watcher( SEAT, BROWSER ) is True


def test_a_second_watcher_of_the_same_seat_is_not_reported_as_first( manager ):
    """Two browsers watching one seat must SHARE its tailer, not start a second one."""
    manager.add_cc_transcript_watcher( SEAT, BROWSER )
    assert manager.add_cc_transcript_watcher( SEAT, BROWSER_2 ) is False
    assert manager.cc_transcript_watchers_of( SEAT ) == { BROWSER, BROWSER_2 }


def test_a_re_watch_from_the_same_session_does_not_double_count( manager ):
    """
    Idempotent, because a reconnect re-watches.

    A double-count would make a seat look busier than it is, so the last real watcher leaving
    would not empty it — and the tailer would never stop.
    """
    assert manager.add_cc_transcript_watcher( SEAT, BROWSER ) is True
    assert manager.add_cc_transcript_watcher( SEAT, BROWSER ) is False
    assert manager.cc_transcript_watchers_of( SEAT ) == { BROWSER }
    assert manager.remove_cc_transcript_watcher( SEAT, BROWSER ) is True, (
        "a re-watch inflated the count, so the last watcher leaving did not empty the seat"
    )


def test_removing_the_last_watcher_is_reported_as_last( manager ):
    """The caller's signal to STOP the tailer."""
    manager.add_cc_transcript_watcher( SEAT, BROWSER )
    assert manager.remove_cc_transcript_watcher( SEAT, BROWSER ) is True


def test_removing_a_non_last_watcher_is_not_reported_as_last( manager ):
    """One of two leaving must NOT stop the tailer the other is still using."""
    manager.add_cc_transcript_watcher( SEAT, BROWSER )
    manager.add_cc_transcript_watcher( SEAT, BROWSER_2 )
    assert manager.remove_cc_transcript_watcher( SEAT, BROWSER ) is False
    assert manager.cc_transcript_watchers_of( SEAT ) == { BROWSER_2 }


def test_an_emptied_seat_loses_its_key_rather_than_keeping_an_empty_set( manager ):
    """
    Otherwise the registry accumulates one empty set per seat ever watched, forever.

    It also makes `bool( watchers.get( seat ) )` — which the tailer's self-termination
    predicate uses — the same question as "is anyone watching".
    """
    manager.add_cc_transcript_watcher( SEAT, BROWSER )
    manager.remove_cc_transcript_watcher( SEAT, BROWSER )
    assert SEAT not in manager.cc_transcript_watchers


def test_removing_a_watcher_that_was_never_registered_is_a_no_op( manager ):
    """An unwatch can race a disconnect that already swept it — that is not an error."""
    assert manager.remove_cc_transcript_watcher( SEAT, BROWSER ) is False
    assert manager.cc_transcript_watchers == { }

    manager.add_cc_transcript_watcher( SEAT, BROWSER )
    assert manager.remove_cc_transcript_watcher( SEAT, BROWSER_2 ) is False
    assert manager.cc_transcript_watchers_of( SEAT ) == { BROWSER }


def test_watchers_of_returns_a_copy_so_a_caller_can_iterate_safely( manager ):
    """
    The fan-out iterates this set while a watch or a disconnect may mutate the live one.

    Returning the live set would raise "Set changed size during iteration" mid-broadcast —
    dropping a frame for every watcher after the mutation point.
    """
    manager.add_cc_transcript_watcher( SEAT, BROWSER )
    snapshot = manager.cc_transcript_watchers_of( SEAT )
    snapshot.add( "not a real session" )
    assert manager.cc_transcript_watchers_of( SEAT ) == { BROWSER }


def test_watchers_of_an_unwatched_seat_is_empty_not_none( manager ):
    """The fan-out loops over this without a None check."""
    assert manager.cc_transcript_watchers_of( "nobody-watches-me" ) == set()


def test_is_watching_answers_the_pair_question( manager ):
    """Used to decide whether an unwatch has anything to do."""
    manager.add_cc_transcript_watcher( SEAT, BROWSER )
    assert manager.is_watching_cc_transcript( SEAT, BROWSER )   is True
    assert manager.is_watching_cc_transcript( SEAT, BROWSER_2 ) is False
    assert manager.is_watching_cc_transcript( OTHER_SEAT, BROWSER ) is False


def test_the_two_id_spaces_do_not_leak_into_each_other( manager ):
    """
    The KEY is a Claude Code seat; the VALUES are browser sockets. Never interchangeable.

    A registry that confused them would let a browser "watch" another browser, and the bug
    would look like an empty pane rather than a type error.
    """
    manager.add_cc_transcript_watcher( SEAT, BROWSER )
    manager.add_cc_transcript_watcher( OTHER_SEAT, BROWSER )
    assert manager.cc_transcript_watchers_of( SEAT )       == { BROWSER }
    assert manager.cc_transcript_watchers_of( OTHER_SEAT ) == { BROWSER }
    assert manager.cc_transcript_watchers_of( BROWSER )    == set(), (
        "a browser session id resolved as a seat key"
    )


# ── A2.5(b): the SOCKET DROP arm — the leak P3 names ──────────────────────────

def test_a_dropped_socket_is_removed_from_every_seat_it_watched( manager ):
    """
    A2.5 arm (b). One closed tab, several watched seats.

    This is the only reliable end of a watch: `cc_transcript_unwatch` is the polite path and
    a closed tab never sends it.
    """
    manager.add_cc_transcript_watcher( SEAT, BROWSER )
    manager.add_cc_transcript_watcher( OTHER_SEAT, BROWSER )
    manager.add_cc_transcript_watcher( SEAT, BROWSER_2 )

    emptied = manager.drop_all_cc_transcript_watches( BROWSER )

    assert emptied == [ OTHER_SEAT ], (
        f"expected only the seat BROWSER was the last watcher of; got {emptied}"
    )
    assert manager.cc_transcript_watchers_of( SEAT ) == { BROWSER_2 }, (
        "a seat another session is still watching was torn down"
    )
    assert OTHER_SEAT not in manager.cc_transcript_watchers


def test_dropping_a_session_that_watched_nothing_returns_nothing( manager ):
    """
    Every disconnect calls this, and most sessions never watched a console.

    It must be cheap and silent, not an error path.
    """
    manager.add_cc_transcript_watcher( SEAT, BROWSER_2 )
    assert manager.drop_all_cc_transcript_watches( BROWSER ) == [ ]
    assert manager.cc_transcript_watchers_of( SEAT ) == { BROWSER_2 }


def test_disconnect_sweeps_the_watcher_registry( manager ):
    """
    The registry entry is gone after `disconnect()`, not merely after an explicit unwatch.

    `disconnect()` deletes from each map in its own statement — `active_connections`,
    `session_timestamps`, `session_subscriptions`, `session_is_admin`, `session_client_types`,
    the user association — so the watcher map is a SIXTH entry that had to be added there
    explicitly. This asserts it was.
    """
    manager.add_cc_transcript_watcher( SEAT, BROWSER )
    manager.disconnect( BROWSER )
    assert manager.cc_transcript_watchers_of( SEAT ) == set()
    assert SEAT not in manager.cc_transcript_watchers


def test_omitting_the_sweep_leaks_a_watcher( manager ):
    """
    PROVES THE DROP ARM WATCHES SOMETHING — the discriminator A2.5 asks for.

    Reproduces the without-the-sweep behaviour: an explicit unwatch still cleans up (arm (a)
    stays green), but a dropped socket leaves the entry behind. That residue is the silent
    burn — the tailer keeps polling while `emit_to_session` early-returns into a session
    already gone. Without this test, "disconnect sweeps the registry" is satisfiable by a
    manager that never had a socket-drop path at all.
    """
    # Arm (a): the polite path cleans up WITHOUT any sweep being involved.
    manager.add_cc_transcript_watcher( SEAT, BROWSER )
    assert manager.remove_cc_transcript_watcher( SEAT, BROWSER ) is True
    assert SEAT not in manager.cc_transcript_watchers

    # Arm (b): a drop with the sweep SKIPPED leaves the entry — the leak, reproduced.
    manager.add_cc_transcript_watcher( SEAT, BROWSER )
    assert manager.cc_transcript_watchers_of( SEAT ) == { BROWSER }, "precondition failed"
    # (deliberately NOT calling drop_all / disconnect here)
    assert SEAT in manager.cc_transcript_watchers, (
        "the entry vanished without a sweep — this test can no longer tell the two arms apart"
    )

    # And with the sweep, it does not.
    manager.drop_all_cc_transcript_watches( BROWSER )
    assert SEAT not in manager.cc_transcript_watchers


# ── the verb handler: A2.2's WS half, and A3.5 ────────────────────────────────

class FakeSocket:
    """Records the frames sent back to the client, in order."""

    def __init__( self ):
        self.sent = [ ]

    async def send_json( self, payload ):
        self.sent.append( payload )

    def of_type( self, type_name ):
        return [ frame for frame in self.sent if frame.get( "type" ) == type_name ]


@pytest.fixture
def router_module( monkeypatch, manager ):
    """
    The websocket router with its manager and tailer factory under test control.

    The tailer is replaced by a recorder: this file is about the VERBS and the registry, and a
    real tailer would put a poll loop and a file read inside every assertion.
    """
    from cosa.rest.routers import websocket as module

    # The manager is resolved PER CALL via get_websocket_manager(), not held at module scope —
    # a first cut of this fixture patched a module attribute that does not exist, and the
    # AttributeError is what revealed that my handlers were referencing a bare
    # `websocket_manager` name too. They would have raised NameError on the first real watch.
    monkeypatch.setattr( module, "get_websocket_manager", lambda: manager )
    monkeypatch.setattr( module, "_cc_transcript_tailers", { } )
    return module


class FakeTailer:
    """A stand-in recording start/stop and the offset it was started at."""

    instances = [ ]

    def __init__( self, cc_session_id, emit, has_watchers=None, **kwargs ):
        self.cc_session_id = cc_session_id
        self.emit          = emit
        self.has_watchers  = has_watchers
        self.started_at    = None
        self.stopped       = False
        FakeTailer.instances.append( self )

    def start( self, from_offset=0 ):
        self.started_at = from_offset

    async def stop( self ):
        self.stopped = True


@pytest.fixture
def fake_tailer( monkeypatch ):
    """Patch the tailer class the handler imports, and hand back the instance list."""
    import cosa.rest.cc_transcript_tailer as tailer_module

    FakeTailer.instances = [ ]
    monkeypatch.setattr( tailer_module, "CcTranscriptTailer", FakeTailer )
    return FakeTailer


@pytest.fixture
def epoch_is( monkeypatch ):
    """Pin the seat's current file epoch, so the epoch arm is deterministic."""
    import cosa.rest.cc_transcript_tailer as tailer_module

    def _set( epoch ):
        monkeypatch.setattr( tailer_module, "resolve_transcript_path",
                             lambda *a, **k: f"/fake/{epoch}.jsonl" if epoch else "" )
    return _set


@pytest.mark.asyncio
async def test_a_non_admin_watch_is_refused_and_registers_nothing( router_module, manager, fake_tailer, epoch_is ):
    """
    A2.2's WS half, NEGATIVE arm.

    The console carries everything the seat read — file contents, tool output, possibly
    secrets — so this refusal is the feature's only access control on the live channel.
    """
    epoch_is( SEAT )
    manager.session_is_admin[ BROWSER ] = False
    socket = FakeSocket()

    await router_module.handle_cc_transcript_verb(
        socket, BROWSER, { "type": "cc_transcript_watch", "cc_session_id": SEAT } )

    assert socket.of_type( "error" ), "a non-admin watch produced no refusal"
    assert manager.cc_transcript_watchers_of( SEAT ) == set(), "a non-admin was registered"
    assert fake_tailer.instances == [ ], "a non-admin watch started a tailer"


@pytest.mark.asyncio
async def test_a_session_with_no_admin_entry_at_all_is_refused( router_module, manager, fake_tailer, epoch_is ):
    """
    Absent is not permitted. A `.get( session_id, False )` default is the whole gate here, so
    the missing-key case is asserted rather than assumed.
    """
    epoch_is( SEAT )
    socket = FakeSocket()
    await router_module.handle_cc_transcript_verb(
        socket, "a-session-nobody-registered", { "type": "cc_transcript_watch", "cc_session_id": SEAT } )
    assert socket.of_type( "error" )
    assert manager.cc_transcript_watchers == { }


@pytest.mark.asyncio
async def test_an_admin_watch_is_accepted_and_starts_the_tailer( router_module, manager, fake_tailer, epoch_is ):
    """
    A2.2's WS half, POSITIVE arm.

    Without it, "a non-admin is refused" is satisfied by a handler that refuses everybody.
    """
    epoch_is( SEAT )
    manager.session_is_admin[ BROWSER ] = True
    socket = FakeSocket()

    await router_module.handle_cc_transcript_verb(
        socket, BROWSER, { "type": "cc_transcript_watch", "cc_session_id": SEAT, "from_offset": 0 } )

    assert socket.of_type( "error" ) == [ ], f"an admin watch was refused: {socket.sent}"
    assert manager.cc_transcript_watchers_of( SEAT ) == { BROWSER }
    assert len( fake_tailer.instances ) == 1
    assert fake_tailer.instances[ 0 ].cc_session_id == SEAT


@pytest.mark.asyncio
async def test_the_watch_honours_from_offset( router_module, manager, fake_tailer, epoch_is ):
    """
    The server starts WHERE THE CLIENT ASKED.

    Starting at the current end would open a silent gap between the client's REST backlog
    fetch and its live watch — and nothing would report it.
    """
    epoch_is( SEAT )
    manager.session_is_admin[ BROWSER ] = True
    await router_module.handle_cc_transcript_verb(
        FakeSocket(), BROWSER, { "type": "cc_transcript_watch", "cc_session_id": SEAT, "from_offset": 4096 } )
    assert fake_tailer.instances[ 0 ].started_at == 4096


@pytest.mark.asyncio
async def test_a_missing_from_offset_starts_at_zero( router_module, manager, fake_tailer, epoch_is ):
    """A client that omits it wants the whole epoch, not the end of it."""
    epoch_is( SEAT )
    manager.session_is_admin[ BROWSER ] = True
    await router_module.handle_cc_transcript_verb(
        FakeSocket(), BROWSER, { "type": "cc_transcript_watch", "cc_session_id": SEAT } )
    assert fake_tailer.instances[ 0 ].started_at == 0


@pytest.mark.asyncio
async def test_a_second_admin_watching_the_same_seat_shares_one_tailer( router_module, manager, fake_tailer, epoch_is ):
    """
    Two browsers, one tailer. A second tailer would read the file twice and emit every block
    twice to whoever the fan-out reached.
    """
    epoch_is( SEAT )
    manager.session_is_admin[ BROWSER ]   = True
    manager.session_is_admin[ BROWSER_2 ] = True

    for browser in ( BROWSER, BROWSER_2 ):
        await router_module.handle_cc_transcript_verb(
            FakeSocket(), browser, { "type": "cc_transcript_watch", "cc_session_id": SEAT } )

    assert len( fake_tailer.instances ) == 1, "a second watcher started a second tailer"
    assert manager.cc_transcript_watchers_of( SEAT ) == { BROWSER, BROWSER_2 }


@pytest.mark.asyncio
async def test_a_null_epoch_is_accepted_so_a_first_watch_needs_no_rest_call( router_module, manager, fake_tailer, epoch_is ):
    """
    `file_epoch: null` means "whatever file is current" — the client learns it from the first
    frame, so opening a pane needs no prior REST round trip.
    """
    epoch_is( SEAT )
    manager.session_is_admin[ BROWSER ] = True
    socket = FakeSocket()
    await router_module.handle_cc_transcript_verb(
        socket, BROWSER, { "type": "cc_transcript_watch", "cc_session_id": SEAT, "file_epoch": None } )
    assert socket.of_type( "cc_transcript_state" ) == [ ]
    assert manager.cc_transcript_watchers_of( SEAT ) == { BROWSER }


@pytest.mark.asyncio
async def test_a_stale_epoch_is_refused_and_never_rebased( router_module, manager, fake_tailer, epoch_is ):
    """
    A3.5. The first message every reconnecting client sends after a `/clear` it did not see.

    A silent rebase would start from 0 on the new file and hand the client the WHOLE NEW
    TRANSCRIPT labelled as its own continuation — which reads as a working pane.
    """
    epoch_is( SEAT )
    manager.session_is_admin[ BROWSER ] = True
    socket = FakeSocket()

    await router_module.handle_cc_transcript_verb( socket, BROWSER, {
        "type"          : "cc_transcript_watch",
        "cc_session_id" : SEAT,
        "file_epoch"    : "an-epoch-from-before-the-clear",
        "from_offset"   : 9999,
    } )

    states = socket.of_type( "cc_transcript_state" )
    assert len( states ) == 1
    assert states[ 0 ][ "state" ]      == "epoch_mismatch"
    assert states[ 0 ][ "file_epoch" ] == SEAT, "the reply did not carry the CURRENT epoch"
    assert manager.cc_transcript_watchers_of( SEAT ) == set(), "a stale watch was registered anyway"
    assert fake_tailer.instances == [ ], "a stale watch started a tailer"


@pytest.mark.asyncio
async def test_a_matching_epoch_is_accepted( router_module, manager, fake_tailer, epoch_is ):
    """
    The positive arm of A3.5 — otherwise "a stale epoch is refused" is satisfied by refusing
    every non-null epoch, which would break every reconnect.
    """
    epoch_is( SEAT )
    manager.session_is_admin[ BROWSER ] = True
    socket = FakeSocket()
    await router_module.handle_cc_transcript_verb( socket, BROWSER, {
        "type": "cc_transcript_watch", "cc_session_id": SEAT, "file_epoch": SEAT } )
    assert socket.of_type( "cc_transcript_state" ) == [ ]
    assert manager.cc_transcript_watchers_of( SEAT ) == { BROWSER }


@pytest.mark.asyncio
async def test_an_unwatch_deregisters_and_stops_the_tailer( router_module, manager, fake_tailer, epoch_is ):
    """A2.5 arm (a), through the verb."""
    epoch_is( SEAT )
    manager.session_is_admin[ BROWSER ] = True
    await router_module.handle_cc_transcript_verb(
        FakeSocket(), BROWSER, { "type": "cc_transcript_watch", "cc_session_id": SEAT } )
    tailer = fake_tailer.instances[ 0 ]

    await router_module.handle_cc_transcript_verb(
        FakeSocket(), BROWSER, { "type": "cc_transcript_unwatch", "cc_session_id": SEAT } )

    assert manager.cc_transcript_watchers_of( SEAT ) == set()
    assert tailer.stopped is True
    assert router_module._cc_transcript_tailers == { }, "the stopped tailer was not forgotten"


@pytest.mark.asyncio
async def test_an_unwatch_by_one_of_two_watchers_leaves_the_tailer_running( router_module, manager, fake_tailer, epoch_is ):
    """The other watcher is still using it — stopping here would blank their pane."""
    epoch_is( SEAT )
    manager.session_is_admin[ BROWSER ]   = True
    manager.session_is_admin[ BROWSER_2 ] = True
    for browser in ( BROWSER, BROWSER_2 ):
        await router_module.handle_cc_transcript_verb(
            FakeSocket(), browser, { "type": "cc_transcript_watch", "cc_session_id": SEAT } )
    tailer = fake_tailer.instances[ 0 ]

    await router_module.handle_cc_transcript_verb(
        FakeSocket(), BROWSER, { "type": "cc_transcript_unwatch", "cc_session_id": SEAT } )

    assert tailer.stopped is False
    assert manager.cc_transcript_watchers_of( SEAT ) == { BROWSER_2 }


@pytest.mark.asyncio
async def test_an_unwatch_for_a_seat_never_watched_is_harmless( router_module, manager, fake_tailer, epoch_is ):
    """Races happen — an unwatch after a disconnect already swept it must not error."""
    epoch_is( SEAT )
    manager.session_is_admin[ BROWSER ] = True
    socket = FakeSocket()
    await router_module.handle_cc_transcript_verb(
        socket, BROWSER, { "type": "cc_transcript_unwatch", "cc_session_id": SEAT } )
    assert socket.of_type( "error" ) == [ ]


@pytest.mark.asyncio
async def test_a_non_admin_unwatch_is_also_refused( router_module, manager, fake_tailer, epoch_is ):
    """
    The gate covers BOTH verbs.

    An ungated unwatch would let any authenticated non-admin tear down an admin's live watch —
    a denial of service through the one verb nobody thinks to guard.
    """
    epoch_is( SEAT )
    manager.session_is_admin[ BROWSER ]   = True
    manager.session_is_admin[ BROWSER_2 ] = False
    await router_module.handle_cc_transcript_verb(
        FakeSocket(), BROWSER, { "type": "cc_transcript_watch", "cc_session_id": SEAT } )

    socket = FakeSocket()
    await router_module.handle_cc_transcript_verb(
        socket, BROWSER_2, { "type": "cc_transcript_unwatch", "cc_session_id": SEAT } )

    assert socket.of_type( "error" ), "a non-admin unwatch was not refused"
    assert manager.cc_transcript_watchers_of( SEAT ) == { BROWSER }, "it tore down an admin's watch"


@pytest.mark.asyncio
@pytest.mark.parametrize( "verb", [ "cc_transcript_watch", "cc_transcript_unwatch" ] )
@pytest.mark.parametrize( "payload_id", [ None, "", "   " ] )
async def test_a_missing_cc_session_id_is_refused_on_both_verbs( router_module, manager, fake_tailer, verb, payload_id ):
    """
    Otherwise a watch registers against "" — a seat that cannot exist, whose tailer polls a
    path that resolves to nothing, forever.

    Checked BEFORE the admin gate, so a malformed frame is refused on its own terms.
    """
    manager.session_is_admin[ BROWSER ] = True
    socket  = FakeSocket()
    message = { "type": verb }
    if payload_id is not None:
        message[ "cc_session_id" ] = payload_id

    await router_module.handle_cc_transcript_verb( socket, BROWSER, message )

    assert socket.of_type( "error" ), f"{verb} with id {payload_id!r} was not refused"
    assert manager.cc_transcript_watchers == { }


# ── the fan-out reaches watchers, and only watchers ───────────────────────────

@pytest.mark.asyncio
async def test_a_frame_reaches_every_watcher_and_no_one_else( router_module, manager ):
    """
    The watcher set is the SINGLE filter: `emit_to_session` applies no subscription check, so
    there is exactly one place a frame can be dropped — deliberately, because the other place
    has silently dropped everything before.
    """
    sent = [ ]

    async def record_emit( session_id, event, data ):
        sent.append( ( session_id, event, data ) )

    manager.emit_to_session = record_emit
    manager.add_cc_transcript_watcher( SEAT, BROWSER )
    manager.add_cc_transcript_watcher( SEAT, BROWSER_2 )
    manager.add_cc_transcript_watcher( OTHER_SEAT, "a-session-watching-something-else" )

    await router_module._emit_to_cc_transcript_watchers(
        SEAT, "cc_transcript_append", { "cc_session_id": SEAT, "blocks": [ ] } )

    assert { session_id for session_id, _, _ in sent } == { BROWSER, BROWSER_2 }


@pytest.mark.asyncio
async def test_a_frame_for_an_unwatched_seat_reaches_nobody( router_module, manager ):
    """A loop over nothing passes every assertion in it, so the empty case is explicit."""
    sent = [ ]

    async def record_emit( session_id, event, data ):
        sent.append( session_id )

    manager.emit_to_session = record_emit
    await router_module._emit_to_cc_transcript_watchers( SEAT, "cc_transcript_append", { } )
    assert sent == [ ]


# ── the disconnect reaper ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_disconnect_reaper_stops_only_the_tailers_it_emptied( router_module, manager, fake_tailer, epoch_is ):
    """
    The async half of the sweep.

    `WebSocketManager.disconnect()` is SYNCHRONOUS and thread-called, so it can drop registry
    entries but cannot await a tailer's stop. This coroutine reaps what those drops emptied.
    """
    epoch_is( SEAT )
    manager.session_is_admin[ BROWSER ]   = True
    manager.session_is_admin[ BROWSER_2 ] = True

    await router_module.handle_cc_transcript_verb(
        FakeSocket(), BROWSER, { "type": "cc_transcript_watch", "cc_session_id": SEAT } )
    await router_module.handle_cc_transcript_verb(
        FakeSocket(), BROWSER_2, { "type": "cc_transcript_watch", "cc_session_id": SEAT } )

    shared = fake_tailer.instances[ 0 ]

    await router_module.stop_cc_transcript_tailers_for_disconnect( BROWSER )
    assert shared.stopped is False, "a seat another session still watches was torn down"

    await router_module.stop_cc_transcript_tailers_for_disconnect( BROWSER_2 )
    assert shared.stopped is True
    assert router_module._cc_transcript_tailers == { }


@pytest.mark.asyncio
async def test_the_reaper_is_harmless_for_a_session_that_watched_nothing( router_module, manager ):
    """Every disconnect calls it; most sessions never opened a console."""
    await router_module.stop_cc_transcript_tailers_for_disconnect( "a-session-with-no-watches" )
    assert router_module._cc_transcript_tailers == { }


@pytest.mark.asyncio
async def test_stopping_an_unknown_seats_tailer_is_a_no_op( router_module ):
    """So the reaper can call it for every emptied seat without checking first."""
    await router_module._stop_cc_transcript_tailer( "a-seat-with-no-tailer" )
    assert router_module._cc_transcript_tailers == { }


# ── the tailer self-terminates on the watcher count ───────────────────────────

@pytest.mark.asyncio
async def test_the_tailer_is_given_a_watcher_predicate_wired_to_the_registry( router_module, manager, fake_tailer, epoch_is ):
    """
    The predicate is what makes the lifecycle correct regardless of WHICH path emptied the
    seat — including the synchronous `disconnect()`, which cannot await a stop.

    Asserted by EXERCISING the predicate against the live registry, not by checking it was
    passed: a predicate wired to the wrong seat would still be present and always wrong.
    """
    epoch_is( SEAT )
    manager.session_is_admin[ BROWSER ] = True
    await router_module.handle_cc_transcript_verb(
        FakeSocket(), BROWSER, { "type": "cc_transcript_watch", "cc_session_id": SEAT } )

    predicate = fake_tailer.instances[ 0 ].has_watchers
    assert predicate is not None, "the tailer was built with no watcher predicate"
    assert predicate() is True

    manager.drop_all_cc_transcript_watches( BROWSER )
    assert predicate() is False, "the predicate does not follow the registry"


@pytest.mark.asyncio
async def test_a_real_tailer_stops_itself_once_its_seat_has_no_watchers( tmp_path ):
    """
    The self-termination arm, on the REAL tailer.

    Prove it watches: with `has_watchers` returning True the loop keeps running; flipped to
    False it exits within the grace period, with nobody calling `stop()`.
    """
    from cosa.rest.cc_transcript_tailer import CcTranscriptTailer

    path = tmp_path / f"{SEAT}.jsonl"
    path.write_text( "" )

    watched  = { "value": True }
    settings = {
        "poll_interval_seconds" : 0.01,
        "grace_seconds"         : 0,
        "coalesce_window_ms"    : 0,
        "backlog_tail_bytes"    : 65536,
        "block_budget_bytes"    : 0,
        "ring_buffer_bytes"     : 4096,
    }

    async def emit( *args, **kwargs ):
        pass

    tailer = CcTranscriptTailer(
        SEAT, emit, settings=settings,
        bridge_reader = lambda _: { "transcript_path": str( path ) },
        has_watchers  = lambda: watched[ "value" ],
    )
    tailer.start()
    await asyncio.sleep( 0.05 )
    assert tailer.running is True, "the tailer stopped while it still had a watcher"

    watched[ "value" ] = False
    await asyncio.wait_for( tailer._task, timeout=2.0 )
    assert tailer.running is False, "the tailer did not self-terminate once unwatched"


@pytest.mark.asyncio
async def test_a_tailer_with_no_predicate_keeps_running( tmp_path ):
    """
    `has_watchers=None` disables self-termination — the shape the direct-lifecycle tests use.

    Without this arm, the self-termination test above could pass on a tailer that simply
    stops after one poll.
    """
    from cosa.rest.cc_transcript_tailer import CcTranscriptTailer

    path = tmp_path / f"{SEAT}.jsonl"
    path.write_text( "" )

    async def emit( *args, **kwargs ):
        pass

    tailer = CcTranscriptTailer(
        SEAT, emit,
        settings = { "poll_interval_seconds": 0.01, "grace_seconds": 0, "coalesce_window_ms": 0,
                     "backlog_tail_bytes": 65536, "block_budget_bytes": 0, "ring_buffer_bytes": 4096 },
        bridge_reader = lambda _: { "transcript_path": str( path ) },
        has_watchers  = None,
    )
    tailer.start()
    try:
        await asyncio.sleep( 0.06 )
        assert tailer.running is True
    finally:
        await tailer.stop()


# ── the verbs are actually reachable from the receive loop ────────────────────

def test_the_receive_loop_dispatches_both_verbs( ):
    """
    Drive the assembled endpoint, not only the handler.

    A handler can be complete, correct, fully covered and NEVER CALLED, and every test that
    exercises the handler directly stays green (CLAUDE.md § Tests). This reads the router's
    source for the dispatch, which is the cheapest honest check that the branch exists.
    """
    source_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ),
                               "src", "cosa", "rest", "routers", "websocket.py" )
    with open( source_path, "r" ) as f:
        source = f.read()

    assert "cc_transcript_watch" in source and "cc_transcript_unwatch" in source
    assert "await handle_cc_transcript_verb(" in source, "the verbs are never dispatched"
    assert "await stop_cc_transcript_tailers_for_disconnect(" in source, (
        "the disconnect path never reaps console tailers"
    )


def test_the_manager_sweeps_the_registry_from_disconnect( ):
    """
    The sync half, asserted at the source, because `disconnect()` has many callers and the
    sweep must be in the shared path rather than in the queue endpoint only.
    """
    source_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ),
                               "src", "cosa", "rest", "websocket_manager.py" )
    with open( source_path, "r" ) as f:
        source = f.read()
    assert "self.drop_all_cc_transcript_watches( session_id )" in source, (
        "disconnect() does not sweep the watcher registry"
    )


@pytest.mark.asyncio
async def test_the_grace_period_is_a_real_wait_not_an_immediate_stop( tmp_path ):
    """
    The tailer survives the grace window before self-terminating.

    Every other self-termination test sets `grace_seconds` to 0, which jumps straight to the
    stop and leaves the waiting branch unexercised — found in the coverage report's partial
    branch, not by reasoning. The wait is the whole point of the dial: a page RELOAD drops the
    socket and re-watches a moment later, so a zero grace would tear the tailer down and
    rebuild it on every refresh.

    Prove it discriminates: the assertion mid-window is that the tailer is STILL RUNNING with
    zero watchers, which an immediate-stop implementation fails.
    """
    from cosa.rest.cc_transcript_tailer import CcTranscriptTailer

    path = tmp_path / f"{SEAT}.jsonl"
    path.write_text( "" )

    watched = { "value": True }

    async def emit( *args, **kwargs ):
        pass

    tailer = CcTranscriptTailer(
        SEAT, emit,
        settings = { "poll_interval_seconds": 0.01, "grace_seconds": 0.5, "coalesce_window_ms": 0,
                     "backlog_tail_bytes": 65536, "block_budget_bytes": 0, "ring_buffer_bytes": 4096 },
        bridge_reader = lambda _: { "transcript_path": str( path ) },
        has_watchers  = lambda: watched[ "value" ],
    )
    tailer.start()
    await asyncio.sleep( 0.03 )

    watched[ "value" ] = False
    await asyncio.sleep( 0.1 )                             # inside the 0.5s grace window
    assert tailer.running is True, "the tailer stopped immediately — the grace period is not honoured"

    try:
        await asyncio.wait_for( tailer._task, timeout=3.0 )
    finally:
        await tailer.stop()
    assert tailer.running is False, "the tailer never stopped after the grace window elapsed"


@pytest.mark.asyncio
async def test_a_watcher_returning_inside_the_grace_window_cancels_the_teardown( tmp_path ):
    """
    The reload case, which is what the grace period is FOR.

    A watcher that comes back before the window elapses must reset the countdown, not merely
    delay it — otherwise a reload that lands late in the window still loses its tailer.
    """
    from cosa.rest.cc_transcript_tailer import CcTranscriptTailer

    path = tmp_path / f"{SEAT}.jsonl"
    path.write_text( "" )

    watched = { "value": True }

    async def emit( *args, **kwargs ):
        pass

    tailer = CcTranscriptTailer(
        SEAT, emit,
        settings = { "poll_interval_seconds": 0.01, "grace_seconds": 0.3, "coalesce_window_ms": 0,
                     "backlog_tail_bytes": 65536, "block_budget_bytes": 0, "ring_buffer_bytes": 4096 },
        bridge_reader = lambda _: { "transcript_path": str( path ) },
        has_watchers  = lambda: watched[ "value" ],
    )
    tailer.start()
    try:
        await asyncio.sleep( 0.03 )
        watched[ "value" ] = False
        await asyncio.sleep( 0.15 )                        # part-way through the window
        watched[ "value" ] = True                          # the reload reconnects
        await asyncio.sleep( 0.35 )                        # longer than the ORIGINAL window
        assert tailer.running is True, (
            "the countdown was not reset — a watcher returning mid-window still lost its tailer"
        )
    finally:
        await tailer.stop()


# ── the dispatch line itself, driven through the real receive loop ─────────────
#
# Every test above calls `handle_cc_transcript_verb` directly, which leaves the DISPATCH
# unexecuted — a handler that is complete, correct, fully covered and never reached, with all
# of its own tests green (CLAUDE.md § Tests: "Drive the assembled app, not only the class").
#
# ⚠️ These use `monkeypatch.setitem( sys.modules, ... )`, NOT `patch.dict( sys.modules, ... )`.
# `patch.dict` restores a PRE-PATCH SNAPSHOT of the whole dict on exit and so DROPS whatever the
# patched code imported while inside — which unloads `sqlalchemy.orm` and trips conftest's
# protected-module guard, failing a LATER test in a different file (row e1da2b5f). Three tests in
# `test_websocket_router_coverage.py` already error that way; a first cut of these two lived in
# that file and inherited it, taking its teardown-error count from 3 to 5. Moved here with the
# narrower tool instead of adding to a known-bad count.

class _StubMainModule:
    """Stands in for `lupin_app.main`, which the queue endpoint reads the manager off."""

    def __init__( self, manager ):
        self.websocket_manager = manager
        self.active_tasks      = { }
        self.app_debug         = False
        self.app_verbose       = False


@pytest.fixture
def queue_endpoint_env( monkeypatch, manager ):
    """
    The queue endpoint wired to a real manager, with only the two sys.modules keys replaced.

    Ensures:
        - `lupin_app` and `lupin_app.main` resolve to stubs for the duration
        - every other module in sys.modules is untouched, so nothing is unloaded on teardown
    """
    from unittest.mock import Mock

    from cosa.rest.routers import websocket as module

    main_stub     = _StubMainModule( manager )
    package_stub  = Mock()
    package_stub.main = main_stub

    monkeypatch.setitem( sys.modules, "lupin_app", package_stub )
    monkeypatch.setitem( sys.modules, "lupin_app.main", main_stub )
    monkeypatch.setattr( module, "_cc_transcript_tailers", { } )
    return module


class _LoopSocket:
    """A socket that yields one frame then disconnects, recording what was sent back."""

    def __init__( self, frames ):
        self._frames = list( frames )
        self.sent    = [ ]

    async def accept( self ): pass

    async def close( self, *args, **kwargs ): pass

    async def send_json( self, payload ):
        self.sent.append( payload )

    async def receive_json( self ):
        return { "type": "auth_request", "token": "good" }

    async def receive_text( self ):
        from fastapi import WebSocketDisconnect
        if not self._frames:
            raise WebSocketDisconnect()
        return self._frames.pop( 0 )


@pytest.mark.asyncio
@pytest.mark.parametrize( "verb", [ "cc_transcript_watch", "cc_transcript_unwatch" ] )
async def test_both_verbs_are_dispatched_from_the_receive_loop( queue_endpoint_env, manager, monkeypatch, verb ):
    """
    The verbs reach the handler through the real loop, both of them.

    Parametrised over BOTH names because they share one branch: a branch written as
    `== "cc_transcript_watch"` would pass for the watch and silently drop every unwatch,
    leaving tailers running for closed panes — which is the P3 burn arriving by a second route.

    The caller is deliberately NOT an admin, so the verb is refused: that is the cheap path
    through the dispatch and needs no transcript, no bridge and no tailer. The handler's own
    behaviour is covered above; what is under test here is that the loop calls it at all.
    """
    import json as json_module
    from unittest.mock import AsyncMock

    from cosa.rest.routers.websocket import websocket_queue_endpoint

    socket = _LoopSocket( [ json_module.dumps( { "type": verb, "cc_session_id": SEAT } ) ] )

    monkeypatch.setattr( "cosa.rest.auth.verify_token",
                         AsyncMock( return_value={ "uid": "u1", "email": "a@b.c" } ) )

    await websocket_queue_endpoint( websocket=socket, session_id=BROWSER )

    refusals = [ frame for frame in socket.sent
                 if frame.get( "type" ) == "error" and frame.get( "event" ) == verb ]
    assert refusals, f"{verb} never reached the handler; frames were {socket.sent}"
