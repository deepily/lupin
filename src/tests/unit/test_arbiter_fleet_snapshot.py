#!/usr/bin/env python3
"""
Unit tests for the v2.1 direct-state wiring in ArbiterConsumerJob:
_publish_fleet_snapshot + the injected bridge-mtime / snapshot / render seams
(arbiter design `03` §10.2-§10.4). Covers the change-vs-tick render branches,
the snapshot push, and the default-seam resolution.
"""
import datetime
import os
import sys

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.agents.heartbeat_arbiter.arbiter_job import ArbiterConsumerJob
from cosa.agents.heartbeat_arbiter import arbiter_job as aj
import cosa.rest.arbiter_snapshot_store as snapshot_store
from lupin_cli.claude_code.hooks.lib import session_bridge


NOW = datetime.datetime( 2026, 6, 6, 22, 41, 0, tzinfo=datetime.timezone.utc )


class _FakeGateway:
    def who( self, retention_hours=24 ): return [ ]
    def send_to( self, recipient, body ): pass
    def post( self, topic, body ): pass


def _view( state="working", stuck=False, event_age_min=2 ):
    return {
        "s1": {
            "session_id"    : "s1",
            "persona"       : "Ann",
            "state"         : state,
            "holding_on"    : "none",
            "stuck"         : stuck,
            "last_event_ts" : NOW - datetime.timedelta( minutes=event_age_min ),
        }
    }


def _make_job( **seams ):
    return ArbiterConsumerJob(
        commons                 = _FakeGateway(),
        poll_seconds            = 5,
        manager_recipient       = "Tiberius",
        alive_threshold_seconds = 600,
        quiet_threshold_seconds = 300,
        **seams,
    )


# ── _publish_fleet_snapshot: change-vs-tick ───────────────────────────────────

class TestPublishFleetSnapshot:

    def test_first_poll_renders_table_and_pushes( self ):
        rendered_out, pushed = [ ], [ ]
        job = _make_job(
            bridge_mtime_fn = lambda sid: NOW.timestamp() - 4,   # fresh bridge ⇒ LIVE
            render_sink     = rendered_out.append,
            snapshot_sink   = pushed.append,
        )
        result = job._publish_fleet_snapshot( _view(), NOW )

        assert result == "table"
        assert len( rendered_out ) == 1 and "Fleet arbiter" in rendered_out[ 0 ]
        assert job._last_change_at == NOW
        # pushed snapshot keeps state + liveness orthogonal (C4) and shows the bridge age
        assert len( pushed ) == 1
        row = pushed[ 0 ][ "sessions" ][ 0 ]
        assert row[ "state" ] == "working" and row[ "liveness" ][ "verdict" ] == "LIVE"
        assert row[ "liveness" ][ "bridge_age_s" ] == 4

    def test_unchanged_second_poll_renders_tick( self ):
        rendered_out = [ ]
        job = _make_job(
            bridge_mtime_fn = lambda sid: NOW.timestamp() - 4,
            render_sink     = rendered_out.append,
            snapshot_sink   = lambda s: None,
        )
        job._publish_fleet_snapshot( _view(), NOW )               # table
        later = NOW + datetime.timedelta( seconds=30 )
        result = job._publish_fleet_snapshot( _view(), later )    # same semantic frame

        assert result == "tick"
        assert "tick · no changes for" in rendered_out[ 1 ]
        assert job._last_change_at == NOW                          # unchanged since first poll

    def test_state_change_renders_table_again( self ):
        rendered_out = [ ]
        job = _make_job(
            bridge_mtime_fn = lambda sid: NOW.timestamp() - 4,
            render_sink     = rendered_out.append,
            snapshot_sink   = lambda s: None,
        )
        job._publish_fleet_snapshot( _view( state="working" ), NOW )
        later = NOW + datetime.timedelta( seconds=30 )
        result = job._publish_fleet_snapshot( _view( state="stuck", stuck=True ), later )

        assert result == "table"
        assert job._last_change_at == later                        # change resets the clock

    def test_bridge_reader_called_per_session( self ):
        seen = [ ]
        def reader( sid ):
            seen.append( sid )
            return None
        job = _make_job( bridge_mtime_fn=reader, render_sink=lambda s: None, snapshot_sink=lambda s: None )
        job._publish_fleet_snapshot( _view(), NOW )
        assert seen == [ "s1" ]


# ── _poll_once integration (the "rendered" key + real push) ───────────────────

class TestPollOnceWiring:

    def test_poll_once_reports_rendered_and_pushes_to_store( self, tmp_path ):
        snapshot_store.clear_snapshot()
        job = _make_job(
            events_dir      = str( tmp_path ),                    # empty → zero sessions
            bridge_mtime_fn = lambda sid: None,
            render_sink     = lambda s: None,
            # snapshot_sink left default → the real server singleton
        )
        summary = job._poll_once()
        assert summary[ "rendered" ] == "table"                   # first poll always a table
        assert snapshot_store.get_snapshot() is not None          # pushed to the GET surface
        assert snapshot_store.get_snapshot()[ "session_count" ] == 0
        snapshot_store.clear_snapshot()


# ── default-seam resolution (the else-branches) ───────────────────────────────

class TestDefaultSeams:

    def test_defaults_resolve_to_canonical_impls( self ):
        job = ArbiterConsumerJob( commons=_FakeGateway(), poll_seconds=5, manager_recipient="T" )
        assert job._bridge_mtime_fn is session_bridge.get_bridge_mtime
        assert job._snapshot_sink   is snapshot_store.set_snapshot
        assert job._render_sink      is print
        assert job._last_frame_sig is None and job._last_change_at is None


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
