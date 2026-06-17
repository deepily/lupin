#!/usr/bin/env python3
"""
Unit tests — task-store mirror orchestrator (Phase 2 write path).

Venue: :7999-eligible / local — REST client fully faked; map + spool are the
REAL modules operating under tmp_path (their own suites prove them; using
them live here exercises the ordering/idempotence interplay the orchestrator
exists for). Covers every row of the plan §2 mapping table, the C8
spool/drain/TTL/order semantics, the I4 flag-once contract, and the
never-raises belt — 100% lines/branches/functions on task_store_mirror.
"""
import os
import sys

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from lupin_cli.claude_code.hooks.lib import task_store_mirror as mr
from lupin_cli.claude_code.hooks.lib import task_store_map as tm
from lupin_cli.claude_code.hooks.lib import task_store_spool as sp

SID      = "d03e6219-a355-486f-9c94-19fa192cf56a"
SETTINGS = { "enabled": True, "api_base_url": "http://t:7999", "timeout_seconds": 3.0, "spool_ttl_seconds": 86400 }


# ---------------------------------------------------------------------------
# Fakes + fixtures
# ---------------------------------------------------------------------------

class FakeClient:
    """
    Programmable stand-in for task_store_client: each method pops the next
    scripted outcome from its queue (or returns a generic success), recording
    every call.
    """

    def __init__( self ):
        self.calls    = [ ]
        self.outcomes = { }    # method -> list of ( ok, status, body )
        self.created  = 0

    def _next( self, method, default ):
        queue = self.outcomes.get( method )
        if queue:
            return queue.pop( 0 )
        return default

    def read_api_key( self, environ=None ):
        return "test-key"

    def create_task( self, settings, api_key, payload ):
        self.calls.append( ( "create", payload ) )
        self.created += 1
        return self._next( "create", ( True, 201, { "id": f"uuid-{self.created}" } ) )

    def transition_task( self, settings, api_key, item_id, payload ):
        self.calls.append( ( "transition", item_id, payload ) )
        return self._next( "transition", ( True, 200, { "item": { }, "event": { } } ) )

    def correlate_task( self, settings, api_key, item_id, payload ):
        self.calls.append( ( "correlate", item_id, payload ) )
        return self._next( "correlate", ( True, 200, { "item": { }, "event": { } } ) )

    def query_by_correlation_key( self, settings, api_key, ck ):
        self.calls.append( ( "query", ck ) )
        return self._next( "query", ( True, 200, { "tasks": [ ], "count": 0 } ) )


@pytest.fixture
def fake_client( monkeypatch ):
    fake = FakeClient()
    monkeypatch.setattr( mr, "client", fake )
    return fake


@pytest.fixture
def logs( monkeypatch ):
    captured = [ ]
    monkeypatch.setattr( mr, "log_to_stream", lambda name, payload, extra=None: captured.append( extra or { } ) )
    return captured


@pytest.fixture
def manager_env( monkeypatch, fake_client, logs ):
    """Default harness: settings enabled, manager-figure True, persona Tiffany."""
    monkeypatch.setattr( mr, "load_task_store_settings", lambda: dict( SETTINGS ) )
    monkeypatch.setattr( mr, "is_manager_figure", lambda sid, environ=None: True )
    monkeypatch.setattr( mr, "get_voice_persona", lambda sid: { "name": "Tiffany" } )
    monkeypatch.setattr( mr, "derive_project_name", lambda environ=None: "lupin" )


def create_payload( harness_id="5", subject="Build the thing", metadata=None ):
    tool_input = { "subject": subject, "description": "details here" }
    if metadata is not None:
        tool_input[ "metadata" ] = metadata
    return {
        "tool_name"     : "TaskCreate",
        "tool_input"    : tool_input,
        "tool_response" : { "task": { "id": harness_id, "subject": subject } },
    }


def update_payload( harness_id="5", status="in_progress" ):
    tool_input = { "taskId": harness_id }
    if status is not None:
        tool_input[ "status" ] = status
    return { "tool_name": "TaskUpdate", "tool_input": tool_input, "tool_response": { "success": True } }


def mirror( payload, tmp_path ):
    return mr.mirror_task_tool_event( payload, SID, base_dir=tmp_path )


# ---------------------------------------------------------------------------
# Gates
# ---------------------------------------------------------------------------

class TestGates:

    def test_disabled_settings_short_circuit( self, tmp_path, fake_client, logs, monkeypatch ):
        monkeypatch.setattr( mr, "load_task_store_settings", lambda: { **SETTINGS, "enabled": False } )
        assert mirror( create_payload(), tmp_path ) == { "action": "disabled" }
        assert fake_client.calls == [ ]

    def test_malformed_settings_fail_safe_disabled( self, tmp_path, fake_client, logs, monkeypatch ):
        def explode():
            raise ValueError( "bad ttl" )
        monkeypatch.setattr( mr, "load_task_store_settings", explode )
        assert mirror( create_payload(), tmp_path ) == { "action": "disabled" }
        assert any( l.get( "phase" ) == "task_store_mirror_settings_invalid" for l in logs )

    def test_non_manager_never_writes( self, tmp_path, fake_client, logs, monkeypatch ):
        monkeypatch.setattr( mr, "load_task_store_settings", lambda: dict( SETTINGS ) )
        monkeypatch.setattr( mr, "is_manager_figure", lambda sid, environ=None: False )
        assert mirror( create_payload(), tmp_path ) == { "action": "not_manager" }
        assert fake_client.calls == [ ]

    def test_unexpected_error_is_belted( self, tmp_path, fake_client, logs, monkeypatch ):
        monkeypatch.setattr( mr, "load_task_store_settings", lambda: dict( SETTINGS ) )
        def explode( sid, environ=None ):
            raise RuntimeError( "boom" )
        monkeypatch.setattr( mr, "is_manager_figure", explode )
        assert mirror( create_payload(), tmp_path ) == { "action": "error" }
        assert any( l.get( "phase" ) == "task_store_mirror_error" for l in logs )

    def test_belt_survives_log_failure_too( self, tmp_path, fake_client, monkeypatch ):
        monkeypatch.setattr( mr, "load_task_store_settings", lambda: dict( SETTINGS ) )
        def explode( sid, environ=None ):
            raise RuntimeError( "boom" )
        monkeypatch.setattr( mr, "is_manager_figure", explode )
        def log_explodes( *a, **k ):
            raise RuntimeError( "log boom" )
        monkeypatch.setattr( mr, "log_to_stream", log_explodes )
        assert mirror( create_payload(), tmp_path ) == { "action": "error" }


# ---------------------------------------------------------------------------
# Mapping table (plan §2)
# ---------------------------------------------------------------------------

class TestCreateMapping:

    def test_create_posts_full_payload_and_records_map( self, tmp_path, manager_env, fake_client ):
        assert mirror( create_payload( harness_id="5" ), tmp_path ) == { "action": "mirrored:create" }
        method, payload = fake_client.calls[ -1 ]
        assert method == "create"
        assert payload == {
            "item_class"          : "task",
            "title"               : "Build the thing",
            "body"                : "details here",
            "project"             : "lupin",
            "created_by"          : "tiffany d03e6219",
            "owner_persona"       : "tiffany",
            "accountable_manager" : "tiffany",
            "authority"           : "standing",
            "correlation_key"     : f"cc-task:{SID}:g0:5",
        }
        entry = tm.read_map( SID, base_dir=tmp_path )[ "tasks" ][ "0:5" ]
        assert entry == { "item_id": "uuid-1", "last_status": "pending" }

    def test_create_with_adoption_metadata_correlates( self, tmp_path, manager_env, fake_client ):
        payload = create_payload( harness_id="9", metadata={ "task_store_id": "inherited-uuid" } )
        assert mirror( payload, tmp_path ) == { "action": "mirrored:correlate" }
        method, item_id, body = fake_client.calls[ -1 ]
        assert ( method, item_id ) == ( "correlate", "inherited-uuid" )
        assert body == { "correlation_key": f"cc-task:{SID}:g0:9", "actor": "tiffany d03e6219", "authority": "standing" }
        assert tm.read_map( SID, base_dir=tmp_path )[ "tasks" ][ "0:9" ][ "item_id" ] == "inherited-uuid"

    def test_create_missing_harness_id_skips( self, tmp_path, manager_env, fake_client, logs ):
        payload = create_payload()
        payload[ "tool_response" ] = { }
        assert mirror( payload, tmp_path ) == { "action": "skipped:create_missing_harness_id" }
        assert any( l.get( "phase" ) == "task_store_mirror_skip" for l in logs )

    def test_create_non_dict_response_task_skips( self, tmp_path, manager_env, fake_client ):
        payload = create_payload()
        payload[ "tool_response" ] = { "task": "not-a-dict" }
        assert mirror( payload, tmp_path ) == { "action": "skipped:create_missing_harness_id" }

    def test_create_non_dict_response_skips( self, tmp_path, manager_env, fake_client ):
        payload = create_payload()
        payload[ "tool_response" ] = "string response"
        assert mirror( payload, tmp_path ) == { "action": "skipped:create_missing_harness_id" }

    def test_create_missing_subject_skips( self, tmp_path, manager_env, fake_client ):
        payload = create_payload( subject="" )
        assert mirror( payload, tmp_path ) == { "action": "skipped:create_missing_subject" }


class TestUpdateMapping:

    @pytest.mark.parametrize( "harness_status,to_status", [
        ( "pending", "queued" ),
        ( "in_progress", "in_progress" ),
        ( "completed", "review" ),
    ] )
    def test_status_transitions( self, tmp_path, manager_env, fake_client, harness_status, to_status ):
        mirror( create_payload( harness_id="5" ), tmp_path )
        tm.record_task( SID, 0, "5", "uuid-1", "primed", tmp_path )   # avoid same-status skip for 'pending'
        assert mirror( update_payload( "5", harness_status ), tmp_path ) == { "action": "mirrored:transition" }
        method, item_id, payload = fake_client.calls[ -1 ]
        assert ( method, item_id ) == ( "transition", "uuid-1" )
        assert payload == { "to_status": to_status, "actor": "tiffany d03e6219", "authority": "standing" }
        assert tm.read_map( SID, base_dir=tmp_path )[ "tasks" ][ "0:5" ][ "last_status" ] == harness_status

    def test_deleted_maps_to_dropped_with_reason( self, tmp_path, manager_env, fake_client ):
        mirror( create_payload( harness_id="5" ), tmp_path )
        assert mirror( update_payload( "5", "deleted" ), tmp_path ) == { "action": "mirrored:transition" }
        _, _, payload = fake_client.calls[ -1 ]
        assert payload[ "to_status" ] == "dropped"
        assert payload[ "reason" ] == "harness-deleted (TaskUpdate)"

    def test_hook_never_writes_done_blocked_or_claimed( self ):
        # The full never-hook-written exclusion set (plan §2 + module
        # docstring), pinned structurally: 'done' unreachable from any harness
        # status (ruling #1 — no receipt-theater, ever); 'blocked' rides only
        # explicit transitions (the oracle's blocked_by {kind:user} contract);
        # 'claimed' has no harness-status source either.
        for never_written in ( "done", "blocked", "claimed" ):
            assert never_written not in mr.STATUS_TRANSITIONS.values()

    def test_update_missing_task_id_skips( self, tmp_path, manager_env, fake_client ):
        payload = { "tool_name": "TaskUpdate", "tool_input": { "status": "completed" } }
        assert mirror( payload, tmp_path ) == { "action": "skipped:update_missing_task_id" }

    def test_metadata_only_update_is_silent_noop( self, tmp_path, manager_env, fake_client, logs ):
        assert mirror( update_payload( "5", None ), tmp_path ) == { "action": "skipped:update_no_status_change" }
        # High-frequency benign case: NOT logged (no skip-noise in the stream).
        assert not any( l.get( "phase" ) == "task_store_mirror_skip" for l in logs )

    def test_unknown_status_skips_loudly( self, tmp_path, manager_env, fake_client, logs ):
        assert mirror( update_payload( "5", "paused" ), tmp_path ) == { "action": "skipped:update_unknown_status:paused" }
        assert any( l.get( "phase" ) == "task_store_mirror_skip" for l in logs )

    def test_same_status_idempotent_skip( self, tmp_path, manager_env, fake_client ):
        mirror( create_payload( harness_id="5" ), tmp_path )
        mirror( update_payload( "5", "in_progress" ), tmp_path )
        calls_before = len( fake_client.calls )
        assert mirror( update_payload( "5", "in_progress" ), tmp_path ) == { "action": "skipped:status_unchanged" }
        assert len( fake_client.calls ) == calls_before

    def test_locally_terminal_item_skips( self, tmp_path, manager_env, fake_client ):
        mirror( create_payload( harness_id="5" ), tmp_path )
        mirror( update_payload( "5", "deleted" ), tmp_path )
        calls_before = len( fake_client.calls )
        assert mirror( update_payload( "5", "in_progress" ), tmp_path ) == { "action": "skipped:terminal" }
        assert len( fake_client.calls ) == calls_before

    def test_unmirrored_harness_task_drops( self, tmp_path, manager_env, fake_client ):
        # No create ever mirrored (predates enablement) → orphan transition.
        assert mirror( update_payload( "77", "completed" ), tmp_path ) == { "action": "dropped:transition" }


class TestIdentityFallback:

    def test_missing_persona_stamps_unknown( self, tmp_path, manager_env, fake_client, monkeypatch ):
        monkeypatch.setattr( mr, "get_voice_persona", lambda sid: None )
        mirror( create_payload(), tmp_path )
        _, payload = fake_client.calls[ -1 ]
        assert payload[ "created_by" ] == "unknown d03e6219"

    def test_persona_with_null_name_stamps_unknown( self, tmp_path, manager_env, fake_client, monkeypatch ):
        monkeypatch.setattr( mr, "get_voice_persona", lambda sid: { "name": None } )
        mirror( create_payload(), tmp_path )
        _, payload = fake_client.calls[ -1 ]
        assert payload[ "created_by" ] == "unknown d03e6219"


# ---------------------------------------------------------------------------
# C8 spool + drain + I4 flag-once
# ---------------------------------------------------------------------------

class TestSpoolOnFailure:

    def test_transport_failure_spools_and_flags( self, tmp_path, manager_env, fake_client, logs ):
        fake_client.outcomes[ "query" ]  = [ ( False, None, { "error": "refused" } ) ]
        assert mirror( create_payload( harness_id="5" ), tmp_path ) == { "action": "spooled:create" }
        entries = sp.read_entries( SID, base_dir=tmp_path )
        assert len( entries ) == 1 and entries[ 0 ][ "op" ] == "create"
        assert tm.read_map( SID, base_dir=tmp_path )[ "flagged_at" ] is not None
        assert any( l.get( "phase" ) == "task_store_mirror_write_failing" for l in logs )

    def test_5xx_spools_too( self, tmp_path, manager_env, fake_client ):
        fake_client.outcomes[ "query" ]  = [ ( True, 200, { "tasks": [ ], "count": 0 } ) ]
        fake_client.outcomes[ "create" ] = [ ( False, 503, { "error": "saturated" } ) ]
        assert mirror( create_payload( harness_id="5" ), tmp_path ) == { "action": "spooled:create" }

    def test_4xx_verdict_drops_and_flags( self, tmp_path, manager_env, fake_client, logs ):
        fake_client.outcomes[ "query" ]  = [ ( True, 200, { "tasks": [ ], "count": 0 } ) ]
        fake_client.outcomes[ "create" ] = [ ( False, 422, { "detail": { "errors": [ "bad" ] } } ) ]
        assert mirror( create_payload( harness_id="5" ), tmp_path ) == { "action": "dropped:create" }
        assert sp.read_entries( SID, base_dir=tmp_path ) == [ ]
        assert tm.read_map( SID, base_dir=tmp_path )[ "flagged_at" ] is not None

    def test_flag_fires_once_per_outage( self, tmp_path, manager_env, fake_client, logs ):
        # Three failures: live op #1 (flags), then call #2's drain attempt AND
        # live op #2 (both inside the same outage → silent, flag already set).
        fake_client.outcomes[ "query" ] = [ ( False, None, { "error": "x" } ) ] * 3
        assert mirror( create_payload( harness_id="5" ), tmp_path ) == { "action": "spooled:create" }
        assert mirror( create_payload( harness_id="6" ), tmp_path ) == { "action": "spooled:create" }
        flag_lines = [ l for l in logs if l.get( "phase" ) == "task_store_mirror_write_failing" ]
        assert len( flag_lines ) == 1
        assert not any( l.get( "phase" ) == "task_store_mirror_recovered" for l in logs )

    def test_success_clears_flag_and_logs_recovery( self, tmp_path, manager_env, fake_client, logs ):
        tm.set_flagged( SID, "t0", tmp_path )
        assert mirror( create_payload( harness_id="5" ), tmp_path ) == { "action": "mirrored:create" }
        assert tm.read_map( SID, base_dir=tmp_path )[ "flagged_at" ] is None
        assert any( l.get( "phase" ) == "task_store_mirror_recovered" for l in logs )

    def test_clear_flag_noop_when_not_flagged( self, tmp_path, manager_env, fake_client, logs ):
        mirror( create_payload( harness_id="5" ), tmp_path )
        assert not any( l.get( "phase" ) == "task_store_mirror_recovered" for l in logs )

    def test_flag_once_survives_unwritable_map( self, tmp_path, manager_env, fake_client, logs, monkeypatch ):
        def explode( *a, **k ):
            raise OSError( "disk" )
        monkeypatch.setattr( mr.task_map, "set_flagged", explode )
        fake_client.outcomes[ "query" ] = [ ( False, None, { "error": "x" } ) ]
        assert mirror( create_payload( harness_id="5" ), tmp_path ) == { "action": "spooled:create" }
        assert any( l.get( "phase" ) == "task_store_mirror_write_failing" for l in logs )

    def test_clear_flag_survives_unwritable_map( self, tmp_path, manager_env, fake_client, monkeypatch ):
        tm.set_flagged( SID, "t0", tmp_path )
        def explode( *a, **k ):
            raise OSError( "disk" )
        monkeypatch.setattr( mr.task_map, "set_flagged", explode )
        assert mirror( create_payload( harness_id="5" ), tmp_path ) == { "action": "mirrored:create" }


class TestOrderPreservation:

    def test_transition_queues_behind_spooled_create( self, tmp_path, manager_env, fake_client ):
        fake_client.outcomes[ "query" ] = [ ( False, None, { "error": "down" } ) ]
        mirror( create_payload( harness_id="5" ), tmp_path )                       # spooled
        fake_client.outcomes[ "query" ] = [ ( False, None, { "error": "down" } ) ] # drain attempt also fails
        assert mirror( update_payload( "5", "in_progress" ), tmp_path ) == { "action": "spooled:transition" }
        assert [ e[ "op" ] for e in sp.read_entries( SID, base_dir=tmp_path ) ] == [ "create", "transition" ]
        # The transition was never sent live — order preserved.
        assert not any( c[ 0 ] == "transition" for c in fake_client.calls )

    def test_drain_replays_fifo_then_mirrors_live( self, tmp_path, manager_env, fake_client, logs ):
        fake_client.outcomes[ "query" ] = [ ( False, None, { "error": "down" } ) ]
        mirror( create_payload( harness_id="5" ), tmp_path )                       # spooled create
        # Server back up: next event drains (create replays; query finds nothing) then mirrors live.
        assert mirror( update_payload( "5", "completed" ), tmp_path ) == { "action": "mirrored:transition" }
        assert sp.read_entries( SID, base_dir=tmp_path ) == [ ]
        assert any( l.get( "phase" ) == "task_store_mirror_spool_replayed" for l in logs )
        method_sequence = [ c[ 0 ] for c in fake_client.calls ]
        assert method_sequence == [ "query", "query", "create", "transition" ]

    def test_replay_adopts_existing_item_instead_of_duplicating( self, tmp_path, manager_env, fake_client ):
        fake_client.outcomes[ "query" ] = [ ( False, None, { "error": "down" } ) ]
        mirror( create_payload( harness_id="5" ), tmp_path )                       # spooled create
        # The original POST actually landed server-side: the probe finds it. The
        # store returns the full serialized item — its title MATCHES the create's,
        # so the collision guard adopts it (legit C8 lost-response replay).
        fake_client.outcomes[ "query" ] = [ ( True, 200, { "tasks": [ { "id": "landed-uuid", "title": "Build the thing" } ], "count": 1 } ) ]
        assert mirror( update_payload( "5", "in_progress" ), tmp_path ) == { "action": "mirrored:transition" }
        assert fake_client.created == 0   # no duplicate POST
        assert tm.read_map( SID, base_dir=tmp_path )[ "tasks" ][ "0:5" ][ "item_id" ] == "landed-uuid"
        _, item_id, _ = fake_client.calls[ -1 ]
        assert item_id == "landed-uuid"


class TestDrainEdges:

    def test_ttl_expired_entries_dropped_and_logged( self, tmp_path, manager_env, fake_client, logs ):
        sp.append_entry( SID, { "op": "create", "ts": 1.0, "harness_id": "5",
                                "harness_status": "pending", "correlation_key": "ck", "payload": { } }, tmp_path )
        assert mirror( update_payload( "9", None ), tmp_path )[ "action" ] == "skipped:update_no_status_change"
        assert sp.read_entries( SID, base_dir=tmp_path ) == [ ]
        assert any( l.get( "phase" ) == "task_store_mirror_spool_expired" for l in logs )

    def test_unknown_op_entries_skipped_loudly( self, tmp_path, manager_env, fake_client, logs ):
        import time
        sp.append_entry( SID, { "op": "frobnicate", "ts": time.time() }, tmp_path )
        mirror( update_payload( "9", None ), tmp_path )
        assert sp.read_entries( SID, base_dir=tmp_path ) == [ ]
        assert any( l.get( "phase" ) == "task_store_mirror_spool_unknown_op" for l in logs )

    def test_drain_stops_at_first_transport_failure_keeping_tail( self, tmp_path, manager_env, fake_client ):
        import time
        now = time.time()
        for hid in ( "1", "2" ):
            sp.append_entry( SID, { "op": "create", "ts": now, "harness_id": hid,
                                    "harness_status": "pending", "correlation_key": f"ck-{hid}",
                                    "payload": { "title": hid } }, tmp_path )
        # First create replays fine; second hits a transport failure mid-drain.
        fake_client.outcomes[ "query" ] = [ ( True, 200, { "tasks": [ ], "count": 0 } ),
                                            ( False, None, { "error": "down" } ) ]
        result = mirror( update_payload( "9", None ), tmp_path )
        remaining = sp.read_entries( SID, base_dir=tmp_path )
        assert [ e[ "harness_id" ] for e in remaining ] == [ "2" ]

    def test_drain_replayed_transition_resolves_item_from_map( self, tmp_path, manager_env, fake_client ):
        import time
        tm.record_task( SID, 0, "5", "uuid-5", "pending", tmp_path )
        sp.append_entry( SID, { "op": "transition", "ts": time.time(), "generation": 0, "harness_id": "5",
                                "harness_status": "completed",
                                "correlation_key": f"cc-task:{SID}:g0:5",
                                "payload": { "to_status": "review", "actor": "a", "authority": "standing" } }, tmp_path )
        mirror( update_payload( "9", None ), tmp_path )
        assert ( "transition", "uuid-5", { "to_status": "review", "actor": "a", "authority": "standing" } ) in fake_client.calls
        assert tm.read_map( SID, base_dir=tmp_path )[ "tasks" ][ "0:5" ][ "last_status" ] == "completed"

    def test_drain_orphan_transition_drops_and_flags( self, tmp_path, manager_env, fake_client, logs ):
        import time
        sp.append_entry( SID, { "op": "transition", "ts": time.time(), "harness_id": "404",
                                "harness_status": "completed", "correlation_key": "ck",
                                "payload": { "to_status": "review", "actor": "a", "authority": "standing" } }, tmp_path )
        mirror( update_payload( "9", None ), tmp_path )
        assert sp.read_entries( SID, base_dir=tmp_path ) == [ ]
        assert any( l.get( "phase" ) == "task_store_mirror_write_failing" for l in logs )

    def test_drain_rewrite_failure_is_swallowed( self, tmp_path, manager_env, fake_client, monkeypatch ):
        import time
        sp.append_entry( SID, { "op": "create", "ts": time.time(), "harness_id": "5",
                                "harness_status": "pending", "correlation_key": "ck",
                                "payload": { "title": "t" } }, tmp_path )
        def explode( *a, **k ):
            raise OSError( "disk" )
        monkeypatch.setattr( mr.spool, "rewrite_entries", explode )
        # Must not raise; the live op still proceeds.
        assert mirror( create_payload( harness_id="6" ), tmp_path ) == { "action": "mirrored:create" }


class TestExecutorMapWriteFailures:

    def test_create_map_write_failure_spools( self, tmp_path, manager_env, fake_client, monkeypatch ):
        def explode( *a, **k ):
            raise OSError( "disk" )
        monkeypatch.setattr( mr.task_map, "record_task", explode )
        assert mirror( create_payload( harness_id="5" ), tmp_path ) == { "action": "spooled:create" }

    def test_correlate_map_write_failure_spools( self, tmp_path, manager_env, fake_client, monkeypatch ):
        def explode( *a, **k ):
            raise OSError( "disk" )
        monkeypatch.setattr( mr.task_map, "record_task", explode )
        payload = create_payload( harness_id="9", metadata={ "task_store_id": "u" } )
        assert mirror( payload, tmp_path ) == { "action": "spooled:correlate" }

    def test_transition_map_write_failure_tolerated( self, tmp_path, manager_env, fake_client, monkeypatch ):
        mirror( create_payload( harness_id="5" ), tmp_path )
        def explode( *a, **k ):
            raise OSError( "disk" )
        monkeypatch.setattr( mr.task_map, "record_task", explode )
        # Server-side state advanced; local last_status stale is acceptable.
        assert mirror( update_payload( "5", "completed" ), tmp_path ) == { "action": "mirrored:transition" }

    def test_correlate_4xx_drops( self, tmp_path, manager_env, fake_client ):
        fake_client.outcomes[ "correlate" ] = [ ( False, 422, { "detail": { "errors": [ "terminal" ] } } ) ]
        payload = create_payload( harness_id="9", metadata={ "task_store_id": "u" } )
        assert mirror( payload, tmp_path ) == { "action": "dropped:correlate" }

    def test_correlate_transport_failure_spools( self, tmp_path, manager_env, fake_client ):
        fake_client.outcomes[ "correlate" ] = [ ( False, None, { "error": "down" } ) ]
        payload = create_payload( harness_id="9", metadata={ "task_store_id": "u" } )
        assert mirror( payload, tmp_path ) == { "action": "spooled:correlate" }

    def test_transition_5xx_spools( self, tmp_path, manager_env, fake_client ):
        mirror( create_payload( harness_id="5" ), tmp_path )
        fake_client.outcomes[ "transition" ] = [ ( False, 500, { "error": "ise" } ) ]
        assert mirror( update_payload( "5", "completed" ), tmp_path ) == { "action": "spooled:transition" }


class TestBuildCorrelationKey:

    def test_shape( self ):
        assert mr.build_correlation_key( "sid-full", 0, "7" ) == "cc-task:sid-full:g0:7"

    def test_generation_segment_distinguishes_reused_counter( self ):
        # The whole point of bug 9b23d5bc: same sid + same counter, different
        # generation ⇒ DISTINCT key (the pre-clear/post-clear "1" never alias).
        assert mr.build_correlation_key( "s", 0, "1" ) != mr.build_correlation_key( "s", 1, "1" )
        assert mr.build_correlation_key( "s", 1, "1" ) == "cc-task:s:g1:1"


# ---------------------------------------------------------------------------
# bug 9b23d5bc — correlation-key / map collision across a /clear counter reset
# ---------------------------------------------------------------------------

class TestCollisionRegression:
    """
    The reproduction the fix exists for: a harness counter that RESTARTS after
    /clear (same stable session id) must mint a DISTINCT store row, leave the
    prior-generation same-numbered row untouched, and route a post-clear
    TaskUpdate to the NEW item — never the stale old one.
    """

    def test_counter_reset_inserts_fresh_row_old_untouched_update_hits_new( self, tmp_path, manager_env, fake_client ):
        # --- Generation 0 (pre-/clear): counter "1" → uuid-1, advanced to in_progress.
        assert mirror( create_payload( harness_id="1", subject="Old task" ), tmp_path ) == { "action": "mirrored:create" }
        assert mirror( update_payload( "1", "in_progress" ), tmp_path ) == { "action": "mirrored:transition" }
        gen0_row = dict( tm.read_map( SID, base_dir=tmp_path )[ "tasks" ][ "0:1" ] )
        assert gen0_row[ "item_id" ] == "uuid-1"

        # --- /clear: the harness counter restarts at "1" for a DIFFERENT task.
        assert mirror( create_payload( harness_id="1", subject="New task" ), tmp_path ) == { "action": "mirrored:create" }

        data = tm.read_map( SID, base_dir=tmp_path )
        # (i) NEW item inserted under a fresh generation key + DISTINCT correlation key.
        assert data[ "generation" ] == 1
        assert data[ "tasks" ][ "1:1" ][ "item_id" ] == "uuid-2"
        create_calls = [ c for c in fake_client.calls if c[ 0 ] == "create" ]
        assert create_calls[ 0 ][ 1 ][ "correlation_key" ]  == f"cc-task:{SID}:g0:1"
        assert create_calls[ -1 ][ 1 ][ "correlation_key" ] == f"cc-task:{SID}:g1:1"
        # (ii) the OLD same-numbered row is byte-for-byte UNTOUCHED.
        assert data[ "tasks" ][ "0:1" ] == gen0_row

        # (iii) the post-clear TaskUpdate transitions the NEW item, never uuid-1.
        assert mirror( update_payload( "1", "completed" ), tmp_path ) == { "action": "mirrored:transition" }
        method, item_id, _ = fake_client.calls[ -1 ]
        assert ( method, item_id ) == ( "transition", "uuid-2" )

    def test_sequential_new_counters_do_not_false_trigger_reset( self, tmp_path, manager_env, fake_client ):
        # Monotonic new counters (1, 2, 3) within one generation must NOT bump —
        # only a re-seen counter is reset-proof.
        for hid in ( "1", "2", "3" ):
            assert mirror( create_payload( harness_id=hid, subject=f"t{hid}" ), tmp_path ) == { "action": "mirrored:create" }
        data = tm.read_map( SID, base_dir=tmp_path )
        assert data[ "generation" ] == 0
        assert set( data[ "tasks" ] ) == { "0:1", "0:2", "0:3" }

    def test_double_reset_advances_generation_twice( self, tmp_path, manager_env, fake_client ):
        # Two successive /clears on the same counter → generations 0 → 1 → 2.
        mirror( create_payload( harness_id="1", subject="g0" ), tmp_path )
        mirror( create_payload( harness_id="1", subject="g1" ), tmp_path )
        mirror( create_payload( harness_id="1", subject="g2" ), tmp_path )
        data = tm.read_map( SID, base_dir=tmp_path )
        assert data[ "generation" ] == 2
        assert set( data[ "tasks" ] ) == { "0:1", "1:1", "2:1" }


class TestCollisionGuard:
    """The _execute_create title-match adoption guard (defense-in-depth)."""

    def test_probe_title_mismatch_refuses_adoption_inserts_fresh( self, tmp_path, manager_env, fake_client ):
        # The probe lands on a row whose title is NOT ours (residual collision):
        # refuse adoption, POST a fresh item instead of mutating the stranger.
        fake_client.outcomes[ "query" ] = [ ( True, 200, { "tasks": [ { "id": "stranger", "title": "Someone else" } ], "count": 1 } ) ]
        assert mirror( create_payload( harness_id="5", subject="Mine" ), tmp_path ) == { "action": "mirrored:create" }
        assert fake_client.created == 1
        method, payload = fake_client.calls[ -1 ]
        assert method == "create" and payload[ "title" ] == "Mine"
        assert tm.read_map( SID, base_dir=tmp_path )[ "tasks" ][ "0:5" ][ "item_id" ] == "uuid-1"

    def test_probe_title_match_adopts_without_duplicating( self, tmp_path, manager_env, fake_client ):
        # Same-title probe row IS the same task (lost-response replay) → adopt it.
        fake_client.outcomes[ "query" ] = [ ( True, 200, { "tasks": [ { "id": "landed", "title": "Build the thing" } ], "count": 1 } ) ]
        assert mirror( create_payload( harness_id="5" ), tmp_path ) == { "action": "mirrored:create" }
        assert fake_client.created == 0
        assert tm.read_map( SID, base_dir=tmp_path )[ "tasks" ][ "0:5" ][ "item_id" ] == "landed"


class TestLegacySpoolTolerance:

    def test_legacy_spool_entry_without_generation_drains_into_gen0( self, tmp_path, manager_env, fake_client ):
        import time
        # A pre-fix spooled create line carries NO 'generation' field — the
        # executor must default it to 0 and replay safely (never KeyError).
        sp.append_entry( SID, { "op": "create", "ts": time.time(), "harness_id": "5",
                                "harness_status": "pending", "correlation_key": "cc-task:legacy:5",
                                "payload": { "title": "legacy" } }, tmp_path )
        mirror( update_payload( "9", None ), tmp_path )   # triggers the opportunistic drain
        assert sp.read_entries( SID, base_dir=tmp_path ) == [ ]
        assert tm.read_map( SID, base_dir=tmp_path )[ "tasks" ][ "0:5" ][ "item_id" ] == "uuid-1"
