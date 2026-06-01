"""
Unit tests for the commons broadcast router (`cosa.rest.routers.commons`).

Covers the full pure-logic surface (the 100% coverage gate per the module's
design split — route handlers are `# pragma: no cover`'d thin dispatchers):

- `init_commons_state` (singleton wiring).
- Validation helpers: `_body_contains_reminder_framing`, `validate_broadcast_body`,
  `validate_broadcast_id`, `build_pseudo_sender_id`.
- Bridge helpers: `_load_bridge_fields`, `_bridge_last_activity_epoch`,
  `project_session_response`, `filter_and_project_sessions`.
- Broadcast pipeline: `perform_fanout`, `execute_broadcast`.
- History aggregator: `_entry_passes_same_user_scoping`, `_project_history_entry`,
  `_resolve_since_cutoff`, `_dedupe_broadcasts_by_id`,
  `_dedupe_broadcast_acks_by_recipient`, `execute_broadcast_history`.
- Register-question helpers: `make_question_inject_fn`, `_resolve_dm_recipient`,
  `_dispatch_commons_question_received`, `execute_register_question`,
  `execute_unregister_question`.

Zero external dependencies — the commons store, rate limiter, ack/question
watchers, notification queue, and `match_persona` are all boundary-mocked or
injected as callables. No real network / DB / filesystem (temp files only for
`_load_bridge_fields`). Auth is bypassed by calling the pure helpers directly.
"""

import json
import os
import sys
import tempfile
import unittest
import uuid
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

import cosa.rest.routers.commons as commons
from cosa.rest.routers.commons import (
    BroadcastRequestBody,
    RegisterQuestionRequest,
    RecipientResolutionError,
    init_commons_state,
    get_notification_queue,
    _require_initialized,
    _require_question_watcher,
    _body_contains_reminder_framing,
    validate_broadcast_body,
    validate_broadcast_id,
    build_pseudo_sender_id,
    _load_bridge_fields,
    _bridge_last_activity_epoch,
    project_session_response,
    filter_and_project_sessions,
    perform_fanout,
    execute_broadcast,
    _entry_passes_same_user_scoping,
    _project_history_entry,
    _resolve_since_cutoff,
    _dedupe_broadcasts_by_id,
    _dedupe_broadcast_acks_by_recipient,
    execute_broadcast_history,
    make_question_inject_fn,
    _resolve_dm_recipient,
    _dispatch_commons_question_received,
    execute_register_question,
    execute_unregister_question,
)
from cosa.rest.commons_question_watcher import CapExceededError, QuestionNotFound

P = "cosa.rest.routers.commons"


# ── init_commons_state ────────────────────────────────────────────────────────


class TestInitCommonsState( unittest.TestCase ):
    """`init_commons_state` wires the module singletons."""

    def setUp( self ):
        # Snapshot module globals so each test restores them.
        self._snapshot = (
            commons._commons_store,
            commons._commons_rate_limiter,
            commons._commons_ack_watcher,
            commons._commons_question_watcher,
            commons._active_session_threshold_seconds,
        )
        self.addCleanup( self._restore )

    def _restore( self ):
        ( commons._commons_store,
          commons._commons_rate_limiter,
          commons._commons_ack_watcher,
          commons._commons_question_watcher,
          commons._active_session_threshold_seconds ) = self._snapshot

    def test_wires_all_singletons_with_question_watcher( self ):
        store, rl, ack, qw = MagicMock(), MagicMock(), MagicMock(), MagicMock()
        init_commons_state( store, rl, ack, 123, question_watcher=qw )
        self.assertIs( commons._commons_store, store )
        self.assertIs( commons._commons_rate_limiter, rl )
        self.assertIs( commons._commons_ack_watcher, ack )
        self.assertIs( commons._commons_question_watcher, qw )
        self.assertEqual( commons._active_session_threshold_seconds, 123.0 )

    def test_question_watcher_defaults_to_none( self ):
        init_commons_state( MagicMock(), MagicMock(), MagicMock(), 600 )
        self.assertIsNone( commons._commons_question_watcher )


# ── DI accessors + readiness guards ─────────────────────────────────────────────


class TestAccessorsAndGuards( unittest.TestCase ):
    """`get_notification_queue` + `_require_initialized` + `_require_question_watcher`."""

    def setUp( self ):
        self._snapshot = (
            commons._commons_store,
            commons._commons_rate_limiter,
            commons._commons_ack_watcher,
            commons._commons_question_watcher,
        )
        self.addCleanup( self._restore )

    def _restore( self ):
        ( commons._commons_store,
          commons._commons_rate_limiter,
          commons._commons_ack_watcher,
          commons._commons_question_watcher ) = self._snapshot

    def test_get_notification_queue( self ):
        mock_main = MagicMock()
        mock_main.jobs_notification_queue = "NQ"
        pkg = MagicMock(); pkg.main = mock_main
        with patch.dict( sys.modules, { "fastapi_app": pkg, "fastapi_app.main": mock_main } ):
            self.assertEqual( get_notification_queue(), "NQ" )

    def test_require_initialized_passes_when_all_wired( self ):
        commons._commons_store        = MagicMock()
        commons._commons_rate_limiter = MagicMock()
        commons._commons_ack_watcher  = MagicMock()
        _require_initialized()  # no raise

    def test_require_initialized_raises_503_when_missing( self ):
        commons._commons_store        = None
        commons._commons_rate_limiter = MagicMock()
        commons._commons_ack_watcher  = MagicMock()
        with self.assertRaises( HTTPException ) as c:
            _require_initialized()
        self.assertEqual( c.exception.status_code, 503 )

    def test_require_question_watcher_passes_when_wired( self ):
        commons._commons_question_watcher = MagicMock()
        _require_question_watcher()  # no raise

    def test_require_question_watcher_raises_503_when_none( self ):
        commons._commons_question_watcher = None
        with self.assertRaises( HTTPException ) as c:
            _require_question_watcher()
        self.assertEqual( c.exception.status_code, 503 )


# ── validation helpers ─────────────────────────────────────────────────────────


class TestReminderFraming( unittest.TestCase ):

    def test_open_tag_detected( self ):
        self.assertTrue( _body_contains_reminder_framing( "hi <SYSTEM-REMINDER> there" ) )

    def test_close_tag_detected( self ):
        self.assertTrue( _body_contains_reminder_framing( "x </system-reminder>" ) )

    def test_clean_body( self ):
        self.assertFalse( _body_contains_reminder_framing( "perfectly normal text" ) )


class TestValidateBroadcastBody( unittest.TestCase ):

    def test_non_string( self ):
        ok, err = validate_broadcast_body( None )
        self.assertFalse( ok )
        self.assertEqual( err, "message body is required" )

    def test_whitespace_only( self ):
        ok, err = validate_broadcast_body( "   \t " )
        self.assertFalse( ok )
        self.assertEqual( err, "message body is required" )

    def test_reminder_framing_rejected( self ):
        ok, err = validate_broadcast_body( "hey <system-reminder>" )
        self.assertFalse( ok )
        self.assertEqual( err, "message must not contain system-reminder framing tags" )

    def test_valid( self ):
        ok, err = validate_broadcast_body( "a real message" )
        self.assertTrue( ok )
        self.assertIsNone( err )


class TestValidateBroadcastId( unittest.TestCase ):

    def test_none_allowed( self ):
        ok, err = validate_broadcast_id( None )
        self.assertTrue( ok )
        self.assertIsNone( err )

    def test_non_string( self ):
        ok, err = validate_broadcast_id( 12345 )
        self.assertFalse( ok )
        self.assertEqual( err, "broadcast_id must be a UUIDv4" )

    def test_malformed_uuid( self ):
        ok, err = validate_broadcast_id( "not-a-uuid" )
        self.assertFalse( ok )
        self.assertEqual( err, "broadcast_id must be a UUIDv4" )

    def test_valid_uuidv4( self ):
        ok, err = validate_broadcast_id( str( uuid.uuid4() ) )
        self.assertTrue( ok )
        self.assertIsNone( err )


class TestBuildPseudoSenderId( unittest.TestCase ):

    def test_format_and_determinism( self ):
        sid = build_pseudo_sender_id( "user-42" )
        self.assertTrue( sid.startswith( "broadcast-" ) )
        self.assertEqual( len( sid ), len( "broadcast-" ) + 8 )
        # Deterministic for the same input; never contains '@'.
        self.assertEqual( sid, build_pseudo_sender_id( "user-42" ) )
        self.assertNotIn( "@", sid )


# ── bridge helpers ──────────────────────────────────────────────────────────────


class TestLoadBridgeFields( unittest.TestCase ):

    def test_valid_json( self ):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join( d, "bridge.json" )
            with open( p, "w" ) as f:
                json.dump( { "a": 1 }, f )
            self.assertEqual( _load_bridge_fields( p ), { "a": 1 } )

    def test_bad_json_returns_none( self ):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join( d, "bad.json" )
            with open( p, "w" ) as f:
                f.write( "{not valid json" )
            self.assertIsNone( _load_bridge_fields( p ) )

    def test_missing_file_returns_none( self ):
        self.assertIsNone( _load_bridge_fields( "/no/such/bridge/file.json" ) )


class TestBridgeLastActivityEpoch( unittest.TestCase ):

    def test_numeric_first_field( self ):
        self.assertEqual( _bridge_last_activity_epoch( { "last_activity_epoch": 100 } ), 100.0 )

    def test_numeric_second_field( self ):
        self.assertEqual( _bridge_last_activity_epoch( { "last_activity": 55.5 } ), 55.5 )

    def test_numeric_third_field( self ):
        self.assertEqual( _bridge_last_activity_epoch( { "updated_at": 7 } ), 7.0 )

    def test_idle_detection_not_dict_returns_none( self ):
        # No numeric field, idle_detection missing entirely.
        self.assertIsNone( _bridge_last_activity_epoch( { } ) )
        # idle_detection present but not a dict (schema drift).
        self.assertIsNone( _bridge_last_activity_epoch( { "idle_detection": "nope" } ) )

    def test_idle_iso_valid( self ):
        iso = "2026-05-13T12:00:00+00:00"
        result = _bridge_last_activity_epoch( { "idle_detection": { "last_interaction_at": iso } } )
        self.assertIsInstance( result, float )

    def test_idle_iso_invalid_returns_none( self ):
        self.assertIsNone(
            _bridge_last_activity_epoch( { "idle_detection": { "last_interaction_at": "garbage-date" } } )
        )

    def test_idle_iso_missing_or_empty_returns_none( self ):
        # last_interaction_at not a string.
        self.assertIsNone( _bridge_last_activity_epoch( { "idle_detection": { } } ) )
        # last_interaction_at empty string (falsy).
        self.assertIsNone( _bridge_last_activity_epoch( { "idle_detection": { "last_interaction_at": "" } } ) )


class TestProjectSessionResponse( unittest.TestCase ):

    def _persona( self ):
        return { "name": "Arnold", "icon": "🪨", "color": "#FFD600" }

    def test_last_seen_from_last_activity_iso( self ):
        out = project_session_response( "sid1", self._persona(), { "last_activity_iso": "ISO-A", "speakerphone_on": True } )
        self.assertEqual( out[ "last_seen_iso" ], "ISO-A" )
        self.assertEqual( out[ "session_id" ], "sid1" )
        self.assertEqual( out[ "persona_name" ], "Arnold" )
        self.assertTrue( out[ "speakerphone_on" ] )

    def test_last_seen_from_updated_at_iso( self ):
        out = project_session_response( "s", self._persona(), { "updated_at_iso": "ISO-B" } )
        self.assertEqual( out[ "last_seen_iso" ], "ISO-B" )
        self.assertFalse( out[ "speakerphone_on" ] )

    def test_last_seen_from_idle_detection( self ):
        out = project_session_response( "s", self._persona(), { "idle_detection": { "last_interaction_at": "ISO-C" } } )
        self.assertEqual( out[ "last_seen_iso" ], "ISO-C" )

    def test_idle_block_not_dict_yields_none_last_seen( self ):
        out = project_session_response( "s", self._persona(), { "idle_detection": [ "list" ] } )
        self.assertIsNone( out[ "last_seen_iso" ] )


class TestFilterAndProjectSessions( unittest.TestCase ):

    def _persona( self ):
        return { "name": "P", "icon": "i", "color": "c" }

    def test_bridge_none_skipped( self ):
        raw = [ ( "pathA", "sidA", self._persona() ) ]
        out = filter_and_project_sessions(
            raw_sessions=raw, authenticated_user_id="u", active_session_threshold_seconds=600,
            now_epoch=1000.0, bridge_loader=lambda p: None,
        )
        self.assertEqual( out, [ ] )

    def test_owner_mismatch_skipped( self ):
        raw = [ ( "p", "s", self._persona() ) ]
        out = filter_and_project_sessions(
            raw_sessions=raw, authenticated_user_id="u", active_session_threshold_seconds=600,
            now_epoch=1000.0, bridge_loader=lambda p: { "owner_user_id": "OTHER" },
        )
        self.assertEqual( out, [ ] )

    def test_owner_none_passes_graceful( self ):
        raw = [ ( "p", "s", self._persona() ) ]
        out = filter_and_project_sessions(
            raw_sessions=raw, authenticated_user_id="u", active_session_threshold_seconds=600,
            now_epoch=1000.0, bridge_loader=lambda p: { "owner_user_id": None },
        )
        self.assertEqual( len( out ), 1 )

    def test_owner_match_passes( self ):
        raw = [ ( "p", "s", self._persona() ) ]
        out = filter_and_project_sessions(
            raw_sessions=raw, authenticated_user_id="u", active_session_threshold_seconds=600,
            now_epoch=1000.0, bridge_loader=lambda p: { "owner_user_id": "u" },
        )
        self.assertEqual( len( out ), 1 )

    def test_stale_activity_skipped( self ):
        raw = [ ( "p", "s", self._persona() ) ]
        out = filter_and_project_sessions(
            raw_sessions=raw, authenticated_user_id="u", active_session_threshold_seconds=10,
            now_epoch=1000.0, bridge_loader=lambda p: { "last_activity_epoch": 500.0 },
        )
        self.assertEqual( out, [ ] )

    def test_fresh_activity_passes( self ):
        raw = [ ( "p", "s", self._persona() ) ]
        out = filter_and_project_sessions(
            raw_sessions=raw, authenticated_user_id="u", active_session_threshold_seconds=10000,
            now_epoch=1000.0, bridge_loader=lambda p: { "last_activity_epoch": 999.0 },
        )
        self.assertEqual( len( out ), 1 )

    def test_originator_excluded_when_flag_false( self ):
        raw = [ ( "p", "ME", self._persona() ) ]
        out = filter_and_project_sessions(
            raw_sessions=raw, authenticated_user_id="u", active_session_threshold_seconds=600,
            now_epoch=1000.0, bridge_loader=lambda p: { }, originator_session_id="ME",
            include_originator=False,
        )
        self.assertEqual( out, [ ] )

    def test_originator_none_not_excluded( self ):
        raw = [ ( "p", "s", self._persona() ) ]
        out = filter_and_project_sessions(
            raw_sessions=raw, authenticated_user_id="u", active_session_threshold_seconds=600,
            now_epoch=1000.0, bridge_loader=lambda p: { }, originator_session_id=None,
            include_originator=False,
        )
        self.assertEqual( len( out ), 1 )


# ── perform_fanout ──────────────────────────────────────────────────────────────


class TestPerformFanout( unittest.TestCase ):

    def _sessions( self, n ):
        return [ { "session_id": f"sess-{i:08d}" } for i in range( n ) ]

    def test_all_succeed( self ):
        store, nq = MagicMock(), MagicMock()
        ok, failed = perform_fanout(
            broadcast_id="bid", message="m", sessions=self._sessions( 2 ),
            sender_user_id="u", store=store, notification_queue=nq,
            build_sender_id=lambda sid: f"sender-{sid}",
        )
        self.assertEqual( ok, 2 )
        self.assertEqual( failed, [ ] )
        self.assertEqual( store.post.call_count, 2 )
        self.assertEqual( nq.push_notification.call_count, 2 )

    def test_store_post_failure_isolated( self ):
        store, nq = MagicMock(), MagicMock()
        store.post.side_effect = Exception( "boom" )
        ok, failed = perform_fanout(
            broadcast_id="bid", message="m", sessions=self._sessions( 1 ),
            sender_user_id="u", store=store, notification_queue=nq,
            build_sender_id=lambda sid: sid,
        )
        self.assertEqual( ok, 0 )
        self.assertEqual( len( failed ), 1 )
        nq.push_notification.assert_not_called()

    def test_notification_failure_isolated( self ):
        store, nq = MagicMock(), MagicMock()
        nq.push_notification.side_effect = Exception( "push-fail" )
        ok, failed = perform_fanout(
            broadcast_id="bid", message="m", sessions=self._sessions( 1 ),
            sender_user_id="u", store=store, notification_queue=nq,
            build_sender_id=lambda sid: sid,
        )
        self.assertEqual( ok, 0 )
        self.assertEqual( len( failed ), 1 )


# ── execute_broadcast ───────────────────────────────────────────────────────────


class TestExecuteBroadcast( unittest.TestCase ):

    def _kwargs( self, **over ):
        store, rl, ack, nq = MagicMock(), MagicMock(), MagicMock(), MagicMock()
        rl.check_and_record.return_value = ( True, 0.0 )
        base = dict(
            authenticated_user_id="u",
            store=store, rate_limiter=rl, ack_watcher=ack, notification_queue=nq,
            active_session_threshold_seconds=600,
            raw_sessions_fn=lambda: [ ],
            bridge_loader=lambda p: { },
            build_sender_id=lambda sid: sid,
            now_epoch_fn=lambda: 1000.0,
        )
        base.update( over )
        return base

    def test_invalid_body_400( self ):
        kw = self._kwargs()
        res = execute_broadcast( body=BroadcastRequestBody( message="   " ), **kw )
        self.assertEqual( res[ "http_status" ], 400 )

    def test_invalid_broadcast_id_400( self ):
        kw = self._kwargs()
        body = BroadcastRequestBody( message="ok", broadcast_id="bad-uuid" )
        res = execute_broadcast( body=body, **kw )
        self.assertEqual( res[ "http_status" ], 400 )

    def test_rate_limited_429( self ):
        kw = self._kwargs()
        kw[ "rate_limiter" ].check_and_record.return_value = ( False, 12.5 )
        res = execute_broadcast( body=BroadcastRequestBody( message="ok" ), **kw )
        self.assertEqual( res[ "http_status" ], 429 )
        self.assertEqual( res[ "retry_after" ], 12.5 )

    def test_register_collision_409( self ):
        kw = self._kwargs()
        kw[ "ack_watcher" ].register_broadcast.side_effect = ValueError( "dup" )
        res = execute_broadcast( body=BroadcastRequestBody( message="ok", require_ack=True ), **kw )
        self.assertEqual( res[ "http_status" ], 409 )

    def test_zero_sessions_with_ack_unregisters( self ):
        kw = self._kwargs( raw_sessions_fn=lambda: [ ] )
        res = execute_broadcast( body=BroadcastRequestBody( message="ok", require_ack=True ), **kw )
        self.assertEqual( res[ "http_status" ], 200 )
        self.assertEqual( res[ "recipients" ], 0 )
        self.assertEqual( res[ "status" ], "no-active-sessions" )
        kw[ "ack_watcher" ].unregister_broadcast.assert_called_once()

    def test_zero_sessions_no_ack_no_unregister( self ):
        kw = self._kwargs( raw_sessions_fn=lambda: [ ] )
        res = execute_broadcast( body=BroadcastRequestBody( message="ok", require_ack=False ), **kw )
        self.assertEqual( res[ "http_status" ], 200 )
        kw[ "ack_watcher" ].unregister_broadcast.assert_not_called()

    def test_fanout_with_ack_updates_expected_recipients( self ):
        raw = [ ( "p", "s1", { "name": "P" } ) ]
        kw  = self._kwargs( raw_sessions_fn=lambda: raw, bridge_loader=lambda p: { "owner_user_id": "u" } )
        entry = MagicMock()
        kw[ "ack_watcher" ]._in_flight = { }  # populated below by broadcast_id
        # Make register set up the in-flight entry keyed by generated broadcast_id.
        def _reg( bid, uid, expected_recipients ):
            kw[ "ack_watcher" ]._in_flight[ bid ] = entry
        kw[ "ack_watcher" ].register_broadcast.side_effect = _reg
        res = execute_broadcast( body=BroadcastRequestBody( message="ok", require_ack=True ), **kw )
        self.assertEqual( res[ "http_status" ], 200 )
        self.assertEqual( res[ "recipients" ], 1 )
        self.assertEqual( res[ "status" ], "queued" )
        self.assertEqual( entry.expected_recipients, 1 )

    def test_fanout_with_ack_entry_missing_skips_update( self ):
        raw = [ ( "p", "s1", { "name": "P" } ) ]
        kw  = self._kwargs( raw_sessions_fn=lambda: raw, bridge_loader=lambda p: { "owner_user_id": "u" } )
        kw[ "ack_watcher" ]._in_flight = { }  # stays empty → entry is None
        res = execute_broadcast( body=BroadcastRequestBody( message="ok", require_ack=True ), **kw )
        self.assertEqual( res[ "http_status" ], 200 )
        self.assertEqual( res[ "recipients" ], 1 )

    def test_fanout_no_ack( self ):
        raw = [ ( "p", "s1", { "name": "P" } ) ]
        kw  = self._kwargs( raw_sessions_fn=lambda: raw, bridge_loader=lambda p: { "owner_user_id": "u" } )
        body = BroadcastRequestBody( message="ok", require_ack=False, broadcast_id=str( uuid.uuid4() ) )
        res = execute_broadcast( body=body, **kw )
        self.assertEqual( res[ "http_status" ], 200 )
        kw[ "ack_watcher" ].register_broadcast.assert_not_called()


# ── history aggregator helpers ──────────────────────────────────────────────────


class TestEntryPassesSameUserScoping( unittest.TestCase ):

    def test_branch1_sender_user_id_match( self ):
        entry = { "metadata": { "sender_user_id": "u" } }
        self.assertTrue( _entry_passes_same_user_scoping( entry, "u", set(), lambda s: None ) )

    def test_branch2_target_session_match( self ):
        entry = { "metadata": { "target_session_id": "T" } }
        self.assertTrue( _entry_passes_same_user_scoping( entry, "u", { "T" }, lambda s: "OTHER" ) )

    def test_branch3_owner_none_graceful( self ):
        entry = { "sender_session_id": "S" }
        self.assertTrue( _entry_passes_same_user_scoping( entry, "u", set(), lambda s: None ) )

    def test_branch3_owner_match( self ):
        entry = { "sender_session_id": "S" }
        self.assertTrue( _entry_passes_same_user_scoping( entry, "u", set(), lambda s: "u" ) )

    def test_all_fail( self ):
        # No metadata (md → {}); target falsy; sender owner mismatch.
        entry = { "sender_session_id": "S" }
        self.assertFalse( _entry_passes_same_user_scoping( entry, "u", set(), lambda s: "OTHER" ) )

    def test_no_sender_sid_falls_through_false( self ):
        entry = { "metadata": None }  # md → {}, no target, no sender_session_id
        self.assertFalse( _entry_passes_same_user_scoping( entry, "u", set(), lambda s: "u" ) )


class TestProjectHistoryEntry( unittest.TestCase ):

    def test_reserved_topic( self ):
        out = _project_history_entry( { "ts": "T", "body": "b" }, "broadcasts" )
        self.assertEqual( out[ "topic_kind" ], "reserved" )
        self.assertEqual( out[ "topic" ], "broadcasts" )
        self.assertEqual( out[ "metadata" ], { } )

    def test_free_form_topic( self ):
        out = _project_history_entry( { "metadata": { "k": "v" } }, "dm-arnold" )
        self.assertEqual( out[ "topic_kind" ], "free-form" )
        self.assertEqual( out[ "metadata" ], { "k": "v" } )


class TestResolveSinceCutoff( unittest.TestCase ):

    def test_since_iso_passthrough( self ):
        self.assertEqual( _resolve_since_cutoff( "2026-01-01T00:00:00", 5, lambda: "now" ), "2026-01-01T00:00:00" )

    def test_hours_computes_window( self ):
        result = _resolve_since_cutoff( None, 2, lambda: "2026-05-13T12:00:00Z" )
        # 2 hours before 12:00 → 10:00.
        self.assertTrue( result.startswith( "2026-05-13T10:00:00" ) )

    def test_neither_returns_none( self ):
        self.assertIsNone( _resolve_since_cutoff( None, None, lambda: "now" ) )


class TestDedupeBroadcastsById( unittest.TestCase ):

    def test_non_broadcasts_passthrough( self ):
        merged = [ ( "dm-x", { "metadata": { "broadcast_id": "b" } } ) ]
        self.assertEqual( _dedupe_broadcasts_by_id( merged ), merged )

    def test_missing_broadcast_id_passthrough( self ):
        merged = [ ( "broadcasts", { "metadata": { } } ) ]
        self.assertEqual( _dedupe_broadcasts_by_id( merged ), merged )

    def test_dedupes_and_strips_target_session( self ):
        merged = [
            ( "broadcasts", { "metadata": { "broadcast_id": "b1", "target_session_id": "t1" } } ),
            ( "broadcasts", { "metadata": { "broadcast_id": "b1", "target_session_id": "t2" } } ),
        ]
        out = _dedupe_broadcasts_by_id( merged )
        self.assertEqual( len( out ), 1 )
        self.assertNotIn( "target_session_id", out[ 0 ][ 1 ][ "metadata" ] )
        self.assertEqual( out[ 0 ][ 1 ][ "metadata" ][ "broadcast_id" ], "b1" )


class TestDedupeBroadcastAcksByRecipient( unittest.TestCase ):

    def test_non_acks_passthrough( self ):
        merged = [ ( "broadcasts", { } ) ]
        self.assertEqual( _dedupe_broadcast_acks_by_recipient( merged ), merged )

    def test_missing_key_passthrough( self ):
        merged = [ ( "broadcast-acks", { "metadata": { "broadcast_id": "b" }, "sender_session_id": "s" } ) ]  # no status
        self.assertEqual( _dedupe_broadcast_acks_by_recipient( merged ), merged )

    def test_dedupes_identical_acks( self ):
        e = { "metadata": { "broadcast_id": "b", "status": "completed" }, "sender_session_id": "s" }
        merged = [ ( "broadcast-acks", e ), ( "broadcast-acks", dict( e ) ) ]
        out = _dedupe_broadcast_acks_by_recipient( merged )
        self.assertEqual( len( out ), 1 )


class TestExecuteBroadcastHistory( unittest.TestCase ):

    def _store( self, topics, reads ):
        store = MagicMock()
        store._all_topic_names.return_value = topics
        store.read.side_effect = lambda t, since, limit: reads.get( t, [ ] )
        return store

    def test_full_pipeline_filters_sorts_caps_projects( self ):
        reads = {
            "broadcasts": [
                { "ts": "2026-05-13T03:00:00", "metadata": { "sender_user_id": "u", "broadcast_id": "b1", "target_session_id": "t" } },
            ],
            "dm-arnold": [
                { "ts": "2026-05-13T05:00:00", "metadata": { "sender_user_id": "u" } },
                { "ts": "2026-05-13T01:00:00", "metadata": { "sender_user_id": "OTHER" } },  # filtered out
            ],
        }
        store = self._store( [ "broadcasts", "dm-arnold", "presence" ], reads )
        res = execute_broadcast_history(
            authenticated_user_id="u", store=store, since_iso=None, hours=None,
            limit=10, excluded_topics=[ "presence" ], max_entries_ceiling=100,
            user_session_ids_fn=lambda: set(), bridge_owner_lookup=lambda s: "OTHER",
            now_iso_fn=lambda: "2026-05-13T12:00:00+00:00",
        )
        # presence excluded; OTHER-user entry filtered; 2 entries remain, newest first.
        self.assertEqual( len( res[ "entries" ] ), 2 )
        self.assertEqual( res[ "entries" ][ 0 ][ "ts" ], "2026-05-13T05:00:00" )
        self.assertIsNone( res[ "next_cursor" ] )

    def test_file_not_found_topic_skipped( self ):
        store = MagicMock()
        store._all_topic_names.return_value = [ "ghost" ]
        store.read.side_effect = FileNotFoundError
        res = execute_broadcast_history(
            authenticated_user_id="u", store=store, since_iso="2026-01-01T00:00:00",
            hours=None, limit=10, excluded_topics=[ ], max_entries_ceiling=100,
            user_session_ids_fn=lambda: set(), bridge_owner_lookup=lambda s: None,
        )
        self.assertEqual( res[ "entries" ], [ ] )
        self.assertEqual( res[ "since_used" ], "2026-01-01T00:00:00" )

    def test_limit_cap_applied( self ):
        reads = { "t": [ { "ts": f"2026-05-13T0{i}:00:00", "metadata": { "sender_user_id": "u" } } for i in range( 5 ) ] }
        store = self._store( [ "t" ], reads )
        res = execute_broadcast_history(
            authenticated_user_id="u", store=store, since_iso=None, hours=None,
            limit=2, excluded_topics=[ ], max_entries_ceiling=100,
            user_session_ids_fn=lambda: set(), bridge_owner_lookup=lambda s: None,
        )
        self.assertEqual( len( res[ "entries" ] ), 2 )


# ── register-question helpers ───────────────────────────────────────────────────


class TestMakeQuestionInjectFn( unittest.TestCase ):

    def test_inject_pushes_notification( self ):
        nq = MagicMock()
        inject = make_question_inject_fn(
            notification_queue=nq, user_id="u", question_id="q1",
            asker_session_id="askersession", build_sender_id=lambda s: f"sender-{s}",
        )
        inject( { "body": "answer", "persona_name": "Rio", "sender_session_id": "ans", "ts": "T" } )
        nq.push_notification.assert_called_once()
        _, kwargs = nq.push_notification.call_args
        self.assertEqual( kwargs[ "title" ], "action:commons_answer_received" )
        self.assertEqual( kwargs[ "payload" ][ "question_id" ], "q1" )
        self.assertEqual( kwargs[ "payload" ][ "body" ], "answer" )


class TestResolveDmRecipient( unittest.TestCase ):

    def _kwargs( self, **over ):
        base = dict(
            recipient_session_id=None, recipient_persona=None, authenticated_user_id="u",
            raw_sessions_fn=lambda: [ ( "p", "sid-active", { "name": "Rio" } ) ],
            bridge_loader=lambda p: { "owner_user_id": "u" },
            active_session_threshold_seconds=600, now_epoch_fn=lambda: 1000.0,
        )
        base.update( over )
        return base

    def test_session_id_match( self ):
        res = _resolve_dm_recipient( **self._kwargs( recipient_session_id="sid-active" ) )
        self.assertEqual( res[ "http_status" ], 200 )
        self.assertEqual( res[ "session_id" ], "sid-active" )
        self.assertEqual( res[ "persona_name" ], "Rio" )

    def test_session_id_no_match_422( self ):
        res = _resolve_dm_recipient( **self._kwargs( recipient_session_id="ghost" ) )
        self.assertEqual( res[ "http_status" ], 422 )
        self.assertEqual( res[ "detail" ][ "error" ], "recipient_inactive" )

    def test_persona_match( self ):
        with patch( f"{P}.match_persona", return_value="Rio" ):
            res = _resolve_dm_recipient( **self._kwargs( recipient_persona="rio" ) )
        self.assertEqual( res[ "http_status" ], 200 )
        self.assertEqual( res[ "persona_name" ], "Rio" )

    def test_persona_match_persona_returns_none_422( self ):
        with patch( f"{P}.match_persona", return_value=None ):
            res = _resolve_dm_recipient( **self._kwargs( recipient_persona="nobody" ) )
        self.assertEqual( res[ "http_status" ], 422 )
        self.assertEqual( res[ "detail" ][ "error" ], "recipient_not_found" )

    def test_persona_matcher_raises_treated_as_unresolved( self ):
        with patch( f"{P}.match_persona", side_effect=RuntimeError( "phi4 down" ) ):
            res = _resolve_dm_recipient( **self._kwargs( recipient_persona="rio" ) )
        self.assertEqual( res[ "http_status" ], 422 )
        self.assertEqual( res[ "detail" ][ "error" ], "recipient_not_found" )

    def test_persona_matched_but_session_lookup_fails_422( self ):
        # match_persona returns a name that is NOT among active personas.
        with patch( f"{P}.match_persona", return_value="Ghost" ):
            res = _resolve_dm_recipient( **self._kwargs( recipient_persona="ghost" ) )
        self.assertEqual( res[ "http_status" ], 422 )
        self.assertIn( "session lookup failed", res[ "detail" ][ "suggested_next_action" ] )

    def test_neither_supplied_required_422( self ):
        res = _resolve_dm_recipient( **self._kwargs() )
        self.assertEqual( res[ "http_status" ], 422 )
        self.assertEqual( res[ "detail" ][ "error" ], "recipient_required" )


class TestDispatchCommonsQuestionReceived( unittest.TestCase ):

    def _kwargs( self, nq ):
        return dict(
            notification_queue=nq, target_session_id="targetsession", target_persona="Rio",
            question_id="q", topic="dm-rio", asker_session_id="asker",
            authenticated_user_id="u", build_sender_id=lambda s: s,
        )

    def test_dispatch_success( self ):
        nq = MagicMock()
        self.assertTrue( _dispatch_commons_question_received( **self._kwargs( nq ) ) )
        nq.push_notification.assert_called_once()

    def test_dispatch_failure_returns_false( self ):
        nq = MagicMock()
        nq.push_notification.side_effect = Exception( "down" )
        self.assertFalse( _dispatch_commons_question_received( **self._kwargs( nq ) ) )


class TestExecuteRegisterQuestion( unittest.TestCase ):

    def _body( self, **over ):
        base = dict( topic="dm-rio", question_id="q1", asker_session_id="asker" )
        base.update( over )
        return RegisterQuestionRequest( **base )

    def _kwargs( self, qw, **over ):
        base = dict(
            authenticated_user_id="u", question_watcher=qw, notification_queue=MagicMock(),
            build_sender_id=lambda s: s,
            raw_sessions_fn=lambda: [ ( "p", "sid-active", { "name": "Rio" } ) ],
            bridge_loader=lambda p: { "owner_user_id": "u" },
            active_session_threshold_seconds=600, now_epoch_fn=lambda: 1000.0,
        )
        base.update( over )
        return base

    def test_cap_exceeded_429( self ):
        qw = MagicMock()
        qw.register_question.side_effect = CapExceededError( "cap" )
        res = execute_register_question( body=self._body(), **self._kwargs( qw ) )
        self.assertEqual( res[ "http_status" ], 429 )

    def test_collision_409( self ):
        qw = MagicMock()
        qw.register_question.side_effect = ValueError( "dup" )
        res = execute_register_question( body=self._body(), **self._kwargs( qw ) )
        self.assertEqual( res[ "http_status" ], 409 )

    def test_success_no_recipient_201( self ):
        qw = MagicMock()
        res = execute_register_question( body=self._body(), **self._kwargs( qw ) )
        self.assertEqual( res[ "http_status" ], 201 )
        self.assertIsNone( res[ "dm_dispatched" ] )

    def test_recipient_set_but_resolvers_none_skips_dm( self ):
        qw = MagicMock()
        body = self._body( recipient_persona="rio" )
        res = execute_register_question( body=body, **self._kwargs( qw, raw_sessions_fn=None, bridge_loader=None ) )
        self.assertEqual( res[ "http_status" ], 201 )
        self.assertIsNone( res[ "dm_dispatched" ] )

    def test_resolution_422_unregisters_and_returns( self ):
        qw = MagicMock()
        body = self._body( recipient_session_id="ghost" )
        res = execute_register_question( body=body, **self._kwargs( qw ) )
        self.assertEqual( res[ "http_status" ], 422 )
        qw.unregister_question.assert_called_once()

    def test_resolution_422_unregister_question_not_found_swallowed( self ):
        qw = MagicMock()
        qw.unregister_question.side_effect = QuestionNotFound( "gone" )
        body = self._body( recipient_session_id="ghost" )
        res = execute_register_question( body=body, **self._kwargs( qw ) )
        self.assertEqual( res[ "http_status" ], 422 )

    def test_resolution_success_dispatches_dm( self ):
        qw = MagicMock()
        body = self._body( recipient_session_id="sid-active" )
        res = execute_register_question( body=body, **self._kwargs( qw ) )
        self.assertEqual( res[ "http_status" ], 201 )
        self.assertTrue( res[ "dm_dispatched" ] )


class TestExecuteUnregisterQuestion( unittest.TestCase ):

    def test_question_not_found_404( self ):
        qw = MagicMock()
        qw.unregister_question.side_effect = QuestionNotFound( "x" )
        res = execute_unregister_question( authenticated_user_id="u", question_id="q", question_watcher=qw )
        self.assertEqual( res[ "http_status" ], 404 )

    def test_success_204( self ):
        qw = MagicMock()
        res = execute_unregister_question( authenticated_user_id="u", question_id="q", question_watcher=qw )
        self.assertEqual( res[ "http_status" ], 204 )


# ── Pydantic model smoke (RecipientResolutionError default factories) ───────────


class TestRecipientResolutionErrorModel( unittest.TestCase ):

    def test_defaults( self ):
        err = RecipientResolutionError( error="x", suggested_next_action="do y" )
        self.assertEqual( err.resolution_chain_attempted, [ ] )
        self.assertEqual( err.candidate_alternatives, [ ] )
        self.assertIsNone( err.supplied_persona )


if __name__ == "__main__":
    unittest.main()
