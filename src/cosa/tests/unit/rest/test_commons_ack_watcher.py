"""
Unit tests for CommonsAckWatcher (cosa.rest.commons_ack_watcher).

Covers __init__, register_broadcast (insert / collision-reraise),
unregister_broadcast, is_in_flight (present / expired-pruned / unknown),
_initialize_last_seen_ts (entries / empty / exception with debug-on/off),
tick (FileNotFoundError-zero / rich multi-entry dispatch walking every
update-cursor + skip + inflight arc / all-ts-None final-skip /
latest-equals-last-seen final-skip), _ack_payload, _persist_ack_row (row
4f320c27 S3 — success / bad-uuid refusal / DB fault / state mark / sender_id
derivation) and _push_ack_event (success / exception with debug-on/off /
persist-failure-does-not-block-the-push) — to genuine 100% line + branch +
function.

No threads, no network, NO DATABASE: store, push_notification_fn, get_db and
NotificationRepository are all boundary-mocked; tick, _persist_ack_row and
_push_ack_event are invoked directly. ZERO disk, ZERO real daemon.

🔴 WHY `_AckBase` STUBS THE PERSIST. Every pre-S3 test in this file is about
DISPATCH, and after S3 the dispatch path also saves a row. Left real, those
tests would reach a database on a code path they make no claim about, and the
one asserting silence would fail on the persist's own log line. The base stubs
it and records the calls, so a dispatch test can still SEE that a save was
attempted; `TestPersistAckRow` below calls the real method directly.
"""

import unittest
import uuid
from unittest.mock import Mock, patch

from cosa.rest.commons_ack_watcher import CommonsAckWatcher, _InFlightEntry


class _AckBase( unittest.TestCase ):
    def setUp( self ):
        self.store = Mock( name="store" )
        self.push  = Mock( name="push_fn" )
        self.w     = CommonsAckWatcher( store=self.store, push_notification_fn=self.push,
                                        poll_interval_seconds=1.0, in_flight_ttl_seconds=300.0,
                                        debug=True )
        # See the header: the persist is stubbed for every DISPATCH test, and
        # exercised for real in TestPersistAckRow.
        self.persist = Mock( name="_persist_ack_row", return_value="saved-id" )
        patcher = patch.object( self.w, "_persist_ack_row", self.persist )
        patcher.start()
        self.addCleanup( patcher.stop )


class TestInit( _AckBase ):
    def test_stores_push_fn_and_thread_name( self ):
        self.assertIs( self.w.push_notification_fn, self.push )
        self.assertEqual( self.w._thread_name, "CommonsAckWatcher" )


class TestRegisterBroadcast( _AckBase ):
    def test_insert( self ):
        self.w.register_broadcast( "b1", "user-1", 3 )
        self.assertTrue( self.w.is_in_flight( "b1" ) )

    def test_collision_reraises_domain_message( self ):
        self.w.register_broadcast( "b1", "user-1", 3 )
        with self.assertRaises( ValueError ) as ctx:
            self.w.register_broadcast( "b1", "user-1", 3 )
        self.assertIn( "broadcast_id collision", str( ctx.exception ) )


class TestUnregisterBroadcast( _AckBase ):
    def test_removes_entry( self ):
        self.w.register_broadcast( "b1", "user-1", 3 )
        self.w.unregister_broadcast( "b1" )
        self.assertFalse( self.w.is_in_flight( "b1" ) )

    def test_silent_on_unknown( self ):
        self.w.unregister_broadcast( "nope" )


class TestIsInFlight( _AckBase ):
    def test_present( self ):
        self.w.register_broadcast( "b1", "user-1", 3 )
        self.assertTrue( self.w.is_in_flight( "b1" ) )

    def test_expired_is_pruned( self ):
        self.w.register_broadcast( "b1", "user-1", 3 )
        self.w._in_flight[ "b1" ].expires_at_monotonic = 0.0   # force expiry
        self.assertFalse( self.w.is_in_flight( "b1" ) )

    def test_unknown( self ):
        self.assertFalse( self.w.is_in_flight( "ghost" ) )


class TestInitializeLastSeenTs( _AckBase ):
    def test_with_entries_sets_cursor( self ):
        self.store.read.return_value = [ { "ts": "2026-01-01T00:00:00Z" } ]
        self.w._initialize_last_seen_ts()
        self.assertEqual( self.w._last_seen_ts, "2026-01-01T00:00:00Z" )
        self.assertTrue( self.w._initialized_last_seen )

    def test_empty_leaves_cursor_none( self ):
        self.store.read.return_value = []
        self.w._initialize_last_seen_ts()
        self.assertIsNone( self.w._last_seen_ts )
        self.assertTrue( self.w._initialized_last_seen )

    def test_exception_debug_on_prints( self ):
        self.store.read.side_effect = RuntimeError( "store down" )
        with patch( "builtins.print" ) as mp:
            self.w._initialize_last_seen_ts()
        self.assertTrue( self.w._initialized_last_seen )
        self.assertTrue( any( "startup _last_seen_ts init failed" in str( c ) for c in mp.call_args_list ) )

    def test_exception_debug_off_silent( self ):
        self.w.debug = False
        self.store.read.side_effect = RuntimeError( "store down" )
        with patch( "builtins.print" ) as mp:
            self.w._initialize_last_seen_ts()
        mp.assert_not_called()
        self.assertTrue( self.w._initialized_last_seen )


class TestTick( _AckBase ):
    def test_file_not_found_returns_zero( self ):
        self.store.read.side_effect = FileNotFoundError
        self.assertEqual( self.w.tick(), 0 )

    def test_rich_multi_entry_dispatch( self ):
        self.w.register_broadcast( "b1", "user-1", 5 )
        self.store.read.return_value = [
            { "ts": None,  "metadata": {} },                                   # ts None skip; no bid → continue
            { "ts": "t1",  "metadata": { "broadcast_id": "unknown" } },        # latest None→t1; inflight None → continue
            { "ts": "t2",  "metadata": { "broadcast_id": "b1", "status": "ok", "body_summary": "x" },
              "sender_session_id": "s", "persona_name": "p", "persona_icon": "i", "persona_color": "c" },  # t2>t1 update; dispatch
            { "ts": "t0",  "metadata": { "broadcast_id": "b1" } },             # t0>t2 False no-update; dispatch
        ]
        dispatched = self.w.tick()
        self.assertEqual( dispatched, 2 )
        self.assertEqual( self.w._last_seen_ts, "t2" )          # final update (latest != None)
        self.assertEqual( self.w._in_flight[ "b1" ].received_acks, 2 )
        self.assertEqual( self.push.call_count, 2 )

    def test_all_ts_none_dispatches_without_cursor_update( self ):
        self.w.register_broadcast( "b1", "user-1", 5 )
        self.store.read.return_value = [ { "ts": None, "metadata": { "broadcast_id": "b1" } } ]
        self.assertEqual( self.w.tick(), 1 )
        self.assertIsNone( self.w._last_seen_ts )               # latest_ts None → final skip

    def test_latest_equals_last_seen_no_update( self ):
        self.w._last_seen_ts = "t5"
        self.w.register_broadcast( "b1", "user-1", 5 )
        self.store.read.return_value = [ { "ts": "t5", "metadata": { "broadcast_id": "b1" } } ]
        self.assertEqual( self.w.tick(), 1 )
        self.assertEqual( self.w._last_seen_ts, "t5" )          # latest == last_seen → final skip


class TestPushAckEvent( _AckBase ):
    def test_success_passes_payload( self ):
        entry = { "sender_session_id": "s", "persona_name": "p",
                  "persona_icon": "i", "persona_color": "c" }
        self.w._push_ack_event( entry, "b1", "user-1", { "status": "ok", "body_summary": "z" } )
        kwargs = self.push.call_args.kwargs
        self.assertEqual( kwargs[ "type" ], "commons_broadcast_ack" )
        self.assertEqual( kwargs[ "user_id" ], "user-1" )
        self.assertEqual( kwargs[ "payload" ][ "broadcast_id" ], "b1" )

    def test_exception_debug_on_prints( self ):
        self.push.side_effect = RuntimeError( "push boom" )
        with patch( "builtins.print" ) as mp:
            self.w._push_ack_event( {}, "b1", "user-1", {} )
        self.assertTrue( any( "push failed for b1" in str( c ) for c in mp.call_args_list ) )

    def test_exception_debug_off_silent( self ):
        self.w.debug = False
        self.push.side_effect = RuntimeError( "push boom" )
        with patch( "builtins.print" ) as mp:
            self.w._push_ack_event( {}, "b1", "user-1", {} )
        mp.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════════════
# Row 4f320c27 S3 — the ack is SAVED, not only pushed
# ═══════════════════════════════════════════════════════════════════════════════

_USER_UUID = "aaaaaaaa-1111-2222-3333-bbbbbbbbbbbb"

_ENTRY = {
    "sender_session_id" : "f19a8996-2fdc-425d-82bc-0e99f3cd8db2",
    "persona_name"      : "PERSONA-NAME-VALUE",
    "persona_icon"      : "PERSONA-ICON-VALUE",
    "persona_color"     : "PERSONA-COLOR-VALUE",
}
_METADATA = { "status": "STATUS-VALUE", "body_summary": "BODY-SUMMARY-VALUE" }


class _FakeRepo:
    """
    Records what the watcher asked the repository to do.

    Deliberately NOT a bare Mock: `create_notification` must hand back an object
    carrying an `id`, because the state mark is keyed on it — a Mock would return a
    Mock, the mark would be made against the wrong thing, and every assertion here
    would still pass.
    """
    def __init__( self, row_id="NEW-ROW-ID", create_error=None ):
        self.created      = []
        self.state_marks  = []
        self._row_id      = row_id
        self._create_error = create_error

    def create_notification( self, **kwargs ):
        self.created.append( kwargs )
        if self._create_error is not None:
            raise self._create_error
        return type( "Row", (), { "id": self._row_id } )()

    def update_state( self, notification_id, state ):
        self.state_marks.append( ( notification_id, state ) )


class _FakeDb:
    """A get_db() stand-in: a context manager yielding one sentinel session."""
    def __init__( self, enter_error=None ):
        self.session      = object()
        self._enter_error = enter_error
        self.entered      = 0

    def __call__( self ):
        return self

    def __enter__( self ):
        self.entered += 1
        if self._enter_error is not None:
            raise self._enter_error
        return self.session

    def __exit__( self, *exc ):
        return False


class _PersistBase( unittest.TestCase ):
    """Like _AckBase but with the REAL _persist_ack_row and a mocked DB boundary."""

    def setUp( self ):
        self.store = Mock( name="store" )
        self.push  = Mock( name="push_fn" )
        self.w     = CommonsAckWatcher( store=self.store, push_notification_fn=self.push,
                                        poll_interval_seconds=1.0, in_flight_ttl_seconds=300.0,
                                        debug=True )
        self.db    = _FakeDb()
        self.repo  = _FakeRepo()
        self.repo_built_on = []

        def _repo_factory( session ):
            self.repo_built_on.append( session )
            return self.repo

        for patcher in (
            patch( "cosa.rest.commons_ack_watcher.get_db", self.db ),
            patch( "cosa.rest.commons_ack_watcher.NotificationRepository", _repo_factory ),
        ):
            patcher.start()
            self.addCleanup( patcher.stop )

    def _payload( self ):
        return self.w._ack_payload( _ENTRY, "BROADCAST-ID-VALUE", _METADATA )


class TestAckPayload( _PersistBase ):
    """The one definition both the saved row and the live push read."""

    def test_it_carries_the_broadcast_and_the_whole_seat_identity( self ):
        payload = self._payload()
        self.assertEqual( payload, {
            "broadcast_id"  : "BROADCAST-ID-VALUE",
            "session_id"    : _ENTRY[ "sender_session_id" ],
            "persona_name"  : "PERSONA-NAME-VALUE",
            "persona_icon"  : "PERSONA-ICON-VALUE",
            "persona_color" : "PERSONA-COLOR-VALUE",
            "status"        : "STATUS-VALUE",
            "body_summary"  : "BODY-SUMMARY-VALUE",
        } )

    def test_a_missing_body_summary_is_an_empty_string_not_a_missing_key( self ):
        payload = self.w._ack_payload( _ENTRY, "b1", { "status": "ok" } )
        self.assertEqual( payload[ "body_summary" ], "" )

    def test_an_entry_with_no_identity_yields_nulls_rather_than_raising( self ):
        payload = self.w._ack_payload( { }, "b1", { } )
        self.assertIsNone( payload[ "session_id" ] )
        self.assertIsNone( payload[ "persona_name" ] )
        self.assertEqual( payload[ "broadcast_id" ], "b1" )


class TestPersistAckRow( _PersistBase ):

    def test_the_saved_row_carries_the_payload_verbatim( self ):
        """
        🔴 THE ONE CLAIM THE WHOLE ROW EXISTS FOR. An ack row without its payload is
        the state we already had — a bodiless notification nothing can attribute.
        """
        payload = self._payload()
        self.w._persist_ack_row( "BROADCAST-ID-VALUE", _USER_UUID, payload )
        self.assertEqual( len( self.repo.created ), 1 )
        self.assertEqual( self.repo.created[ 0 ][ "payload" ], payload )

    def test_it_is_addressed_to_the_broadcaster_and_typed_as_an_ack( self ):
        self.w._persist_ack_row( "b1", _USER_UUID, self._payload() )
        created = self.repo.created[ 0 ]
        self.assertEqual( created[ "recipient_id" ], uuid.UUID( _USER_UUID ) )
        self.assertEqual( created[ "type" ], "commons_broadcast_ack" )

    def test_the_seat_identity_also_lands_on_the_first_class_persona_columns( self ):
        """
        The payload is the machine-readable record; sender_persona / sender_icon are
        what every existing notification surface already reads. Both, or the UI shows
        an anonymous row next to a perfectly attributed payload.
        """
        self.w._persist_ack_row( "b1", _USER_UUID, self._payload() )
        created = self.repo.created[ 0 ]
        self.assertEqual( created[ "sender_persona" ], "PERSONA-NAME-VALUE" )
        self.assertEqual( created[ "sender_icon" ],    "PERSONA-ICON-VALUE" )

    def test_the_sender_id_carries_the_acking_seats_first_eight_characters( self ):
        """
        The fleet convention is `...deepily.ai#<hash8>`, and the persona resolver
        matches on exactly those eight characters. A full session id there resolves
        to nobody.
        """
        self.w._persist_ack_row( "b1", _USER_UUID, self._payload() )
        self.assertEqual( self.repo.created[ 0 ][ "sender_id" ],
                          "claude.code@lupin.deepily.ai#f19a8996" )

    def test_an_ack_with_no_session_id_still_saves_under_the_bare_project_sender( self ):
        payload = self.w._ack_payload( { }, "b1", { } )
        self.w._persist_ack_row( "b1", _USER_UUID, payload )
        self.assertEqual( self.repo.created[ 0 ][ "sender_id" ], "claude.code@lupin.deepily.ai" )

    def test_the_row_is_marked_delivered_so_it_never_joins_the_afk_inbox( self ):
        """
        🔴 THE STORM GUARD. An ack left in 'created' is an undelivered notification,
        and the AFK drain replays undelivered rows on reconnect — a bodiless
        commons_broadcast_ack would arrive as a "missed notification" for every seat
        that ever acked. S4 finds the row anyway because it does not filter on state.
        """
        self.w._persist_ack_row( "b1", _USER_UUID, self._payload() )
        self.assertEqual( self.repo.state_marks, [ ( "NEW-ROW-ID", "delivered" ) ] )

    def test_the_mark_is_keyed_to_the_row_that_was_just_created( self ):
        """A mark against some other id would leave THIS row undelivered forever."""
        self.repo = _FakeRepo( row_id="THE-ACTUAL-NEW-ROW" )
        self.w._persist_ack_row( "b1", _USER_UUID, self._payload() )
        self.assertEqual( self.repo.state_marks[ 0 ][ 0 ], "THE-ACTUAL-NEW-ROW" )

    def test_it_returns_the_new_row_id( self ):
        self.assertEqual( self.w._persist_ack_row( "b1", _USER_UUID, self._payload() ), "NEW-ROW-ID" )

    def test_the_repository_is_built_on_the_session_get_db_handed_out( self ):
        self.w._persist_ack_row( "b1", _USER_UUID, self._payload() )
        self.assertEqual( self.repo_built_on, [ self.db.session ] )

    # ── the failure arcs ─────────────────────────────────────────────────────────

    def test_a_non_uuid_broadcaster_is_refused_BEFORE_the_database_is_touched( self ):
        with patch( "builtins.print" ):
            out = self.w._persist_ack_row( "b1", "not-a-uuid", self._payload() )
        self.assertIsNone( out )
        self.assertEqual( self.db.entered, 0 )
        self.assertEqual( self.repo.created, [] )

    def test_a_non_uuid_broadcaster_is_logged_LOUD_even_with_debug_off( self ):
        """
        🔴 NOT GATED ON self.debug. A silently-unsaved ack is the exact defect this
        row exists to close; logging it only under a debug flag re-creates it in the
        configuration everything actually runs in.
        """
        self.w.debug = False
        with patch( "builtins.print" ) as mp:
            self.w._persist_ack_row( "b1", None, self._payload() )
        self.assertTrue( any( "NOT SAVED" in str( c ) for c in mp.call_args_list ),
                         f"expected a loud NOT SAVED line, saw {mp.call_args_list!r}" )

    def test_a_dead_database_returns_None_and_is_logged_LOUD_with_debug_off( self ):
        self.w.debug = False
        self.db._enter_error = RuntimeError( "connection reset" )
        with patch( "builtins.print" ) as mp:
            out = self.w._persist_ack_row( "b1", _USER_UUID, self._payload() )
        self.assertIsNone( out )
        self.assertTrue( any( "NOT SAVED" in str( c ) for c in mp.call_args_list ) )

    def test_a_create_fault_returns_None_rather_than_raising( self ):
        self.repo = _FakeRepo( create_error=RuntimeError( "insert failed" ) )
        with patch( "builtins.print" ):
            self.assertIsNone( self.w._persist_ack_row( "b1", _USER_UUID, self._payload() ) )

    def test_the_loud_line_names_the_broadcast_and_the_seat( self ):
        """A log line that cannot be traced to an ack is not a receipt."""
        self.db._enter_error = RuntimeError( "connection reset" )
        with patch( "builtins.print" ) as mp:
            self.w._persist_ack_row( "BROADCAST-ID-VALUE", _USER_UUID, self._payload() )
        printed = " ".join( str( c ) for c in mp.call_args_list )
        self.assertIn( "BROADCAST-ID-VALUE", printed )
        self.assertIn( "PERSONA-NAME-VALUE", printed )


class TestPersistAndPushTogether( _PersistBase ):
    """`_push_ack_event` with the REAL persist underneath it."""

    def test_the_saved_row_and_the_live_push_carry_THE_SAME_payload_object( self ):
        """
        🔴 ONE IDENTITY, TWO DESTINATIONS. Two separately-built dicts would agree on
        the day they were written and drift the first time either is edited — and the
        drift would be invisible, because each side is internally consistent.
        """
        self.w._push_ack_event( _ENTRY, "BROADCAST-ID-VALUE", _USER_UUID, _METADATA )
        saved  = self.repo.created[ 0 ][ "payload" ]
        pushed = self.push.call_args.kwargs[ "payload" ]
        self.assertIs( saved, pushed )

    def test_the_save_happens_BEFORE_the_push( self ):
        """A crash between the two must cost the transient frame, not the record."""
        order = []
        self.push.side_effect = lambda **kw: order.append( "push" )
        real_create = self.repo.create_notification
        self.repo.create_notification = lambda **kw: ( order.append( "save" ), real_create( **kw ) )[ 1 ]
        self.w._push_ack_event( _ENTRY, "b1", _USER_UUID, _METADATA )
        self.assertEqual( order, [ "save", "push" ] )

    def test_a_persist_failure_does_NOT_block_the_live_push( self ):
        """
        🔴 THE USER IS WATCHING THE PUSH. Coupling the two would turn a database
        hiccup into a broadcast whose tally never moves — strictly worse than today.
        """
        self.db._enter_error = RuntimeError( "connection reset" )
        with patch( "builtins.print" ):
            self.w._push_ack_event( _ENTRY, "b1", _USER_UUID, _METADATA )
        self.assertEqual( self.push.call_count, 1 )
        self.assertEqual( self.push.call_args.kwargs[ "payload" ][ "broadcast_id" ], "b1" )

    def test_a_push_failure_does_not_undo_the_saved_row( self ):
        """The record is the durable half; a dropped frame must not take it down."""
        self.push.side_effect = RuntimeError( "push boom" )
        with patch( "builtins.print" ):
            self.w._push_ack_event( _ENTRY, "b1", _USER_UUID, _METADATA )
        self.assertEqual( len( self.repo.created ), 1 )
        self.assertEqual( self.repo.state_marks, [ ( "NEW-ROW-ID", "delivered" ) ] )

    def test_a_tick_dispatch_saves_the_ack_end_to_end( self ):
        """
        Entered at tick(), where the incident enters: an ack lands in the commons
        topic and the row must exist afterwards. Asserting only on _push_ack_event
        would leave tick() free to stop calling it.
        """
        self.w.register_broadcast( "b1", _USER_UUID, 3 )
        self.store.read.return_value = [
            dict( _ENTRY, ts="t1", metadata=dict( _METADATA, broadcast_id="b1" ) ),
        ]
        self.assertEqual( self.w.tick(), 1 )
        self.assertEqual( len( self.repo.created ), 1 )
        self.assertEqual( self.repo.created[ 0 ][ "payload" ][ "broadcast_id" ], "b1" )
        self.assertEqual( self.repo.created[ 0 ][ "payload" ][ "session_id" ],
                          _ENTRY[ "sender_session_id" ] )


class TestTheAckPersistPathNeverTouchesTheEventLoop( unittest.TestCase ):

    def test_the_module_imports_no_event_loop_machinery( self ):
        """
        🔴 THE "OFF THE EVENT LOOP" CLAIM, MADE CHECKABLE. `_persist_ack_row` is a
        blocking DB call and is safe only because tick() runs on the watcher's own
        daemon thread. The day someone makes this path async without moving the
        persist to a worker thread, the notify hot path stalls behind it — and
        nothing else in this file would notice.
        """
        import ast, inspect
        import cosa.rest.commons_ack_watcher as module

        tree     = ast.parse( inspect.getsource( module ) )
        imported = set()
        for node in ast.walk( tree ):
            if isinstance( node, ast.Import ):
                imported.update( alias.name.split( "." )[ 0 ] for alias in node.names )
            elif isinstance( node, ast.ImportFrom ) and node.module:
                imported.add( node.module.split( "." )[ 0 ] )
        self.assertNotIn( "asyncio", imported, "the watcher must stay synchronous" )

        coroutines = [ n.name for n in ast.walk( tree ) if isinstance( n, ast.AsyncFunctionDef ) ]
        self.assertEqual( coroutines, [], f"the watcher must define no coroutines, found {coroutines!r}" )

    def test_the_control_can_see_a_positive( self ):
        """
        A search proves nothing until it has been watched finding something. This
        runs the SAME two predicates over a module that deliberately has both.
        """
        import ast
        tree = ast.parse( "import asyncio\nasync def f():\n    pass\n" )
        imported = { a.name for n in ast.walk( tree ) if isinstance( n, ast.Import ) for a in n.names }
        self.assertIn( "asyncio", imported )
        self.assertEqual( [ n.name for n in ast.walk( tree ) if isinstance( n, ast.AsyncFunctionDef ) ], [ "f" ] )


def isolated_unit_test():
    """
    Run the CommonsAckWatcher unit tests in isolation.

    Ensures:
        - Returns (success, duration, message) for the smoke-runner harness
    """
    import time
    start_time = time.time()
    suite = unittest.TestLoader().loadTestsFromModule( __import__( __name__ ) )
    result = unittest.TextTestRunner( verbosity=2 ).run( suite )
    duration = time.time() - start_time
    success = result.wasSuccessful()
    message = f"{result.testsRun} run, {len( result.failures )} failed, {len( result.errors )} errors"
    return success, duration, message


if __name__ == "__main__":
    ok, secs, msg = isolated_unit_test()
    print( f"\n{'✅ PASS' if ok else '❌ FAIL'} CommonsAckWatcher tests in {secs:.3f}s — {msg}" )
