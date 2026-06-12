#!/usr/bin/env python3
"""
F-A receipts (2026-06-11 lineage-persistence design) — the file-backed lineage
carry behind reaped-worker manager retention: degrade-safe reads, atomic
replace-not-merge writes (the caller persists carry_forward_lineage's already-
pruned output), plus the arbiter_job seam (seed at construction, write-on-change,
journaled write failure). The composed restart-boundary proof is scenario S8.

Venue: :7999-eligible / local — tmp_path only.
"""
import json
import os
import sys

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.agents.heartbeat_arbiter.lineage_carry import read_carry, write_carry, quick_smoke_test
from cosa.agents.heartbeat_arbiter.arbiter_job import ArbiterConsumerJob


class _GW:
    def __init__( self ):
        self.sent = [ ]
    def who( self, retention_hours=24 ): return [ ]
    def send_to( self, r, b, metadata=None ): self.sent.append( ( r, b ) )
    def post( self, t, b ): pass
    def read( self, topic, since=None, limit=50 ): return [ ]


class _Log:
    def __init__( self ):
        self.events = [ ]
    def __call__( self, event, **fields ):
        self.events.append( ( event, fields ) )
    def of( self, name ):
        return [ f for e, f in self.events if e == name ]


def _job( log=None, **overrides ):
    cfg = dict(
        commons           = _GW(),
        poll_seconds      = 5,
        manager_recipient = "DeclaredMgr",
        notify_fn         = lambda m: [ { "channel": "live", "outcome": "queued" } ],
        log_fn            = log if log is not None else _Log(),
    )
    cfg.update( overrides )
    return ArbiterConsumerJob( **cfg )


# ── read_carry: degrade-safe in every failure shape ──────────────────────────

def test_missing_file_reads_empty( tmp_path ):
    assert read_carry( tmp_path / "nope.json" ) == { }


def test_malformed_and_non_object_read_empty( tmp_path ):
    p = tmp_path / "bad.json"
    p.write_text( "{not json" )
    assert read_carry( p ) == { }
    p.write_text( '["a", "list"]' )
    assert read_carry( p ) == { }


def test_malformed_members_skipped( tmp_path ):
    p = tmp_path / "mixed.json"
    p.write_text( json.dumps( { "ok": "Tiberius", "": "X", "bad": 7, "also-bad": "" } ) )
    assert read_carry( p ) == { "ok": "Tiberius" }


# ── write_carry: atomic, parent-creating, replace-not-merge, fail-loud ───────

def test_round_trip_creates_parent_no_tmp_residue( tmp_path ):
    p = tmp_path / "sub" / "lineage-carry.json"
    write_carry( p, { "sid-1": "Tiberius" } )
    assert read_carry( p ) == { "sid-1": "Tiberius" }
    assert not list( p.parent.glob( "*.tmp" ) )


def test_write_replaces_not_merges( tmp_path ):
    """The caller owns prune semantics — a smaller mapping REPLACES (an evicted
    row leaves the file on the same poll it leaves the snapshot)."""
    p = tmp_path / "lineage-carry.json"
    write_carry( p, { "sid-1": "Tiberius", "sid-2": "Mr. Radio" } )
    write_carry( p, { "sid-2": "Mr. Radio" } )
    assert read_carry( p ) == { "sid-2": "Mr. Radio" }


def test_unwritable_target_raises_oserror( tmp_path ):
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    blocked.chmod( 0o500 )
    try:
        with pytest.raises( OSError ):
            write_carry( blocked / "lineage-carry.json", { "s": "T" } )
    finally:
        blocked.chmod( 0o700 )


def test_module_quick_smoke_test_passes():
    assert quick_smoke_test() is True


# ── the arbiter_job seam: seed / write-on-change / journaled failure ─────────

def test_job_seeds_lineage_from_carry_file( tmp_path ):
    p = tmp_path / "lineage-carry.json"
    write_carry( p, { "reaped-sid": "Tiberius" } )
    job = _job( lineage_carry_path=str( p ) )
    assert job._manager_lineage == { "reaped-sid": "Tiberius" }       # restart-seeded


def test_job_without_path_is_volatile_prefix_behavior():
    job = _job()
    assert job._manager_lineage == { } and job._lineage_carry_path is None


def test_publish_writes_carry_only_on_change( tmp_path ):
    """Write-on-change: the file's mtime/content moves only when the mapping
    moves. Driven through _publish_fleet_snapshot with a lineage-resolving seam."""
    p   = tmp_path / "lineage-carry.json"
    now = __import__( "datetime" ).datetime( 2026, 6, 11, 22, 0, 0,
                                             tzinfo=__import__( "datetime" ).timezone.utc )
    job = _job(
        lineage_carry_path = str( p ),
        bridge_mtime_fn    = lambda sid: now.timestamp(),
        resolve_manager_fn = lambda sid, declared_manager=None: {
            "manager_persona": "Tiberius", "source": "lineage" },
        snapshot_sink      = lambda s: None,
        render_sink        = lambda s: None,
    )
    fleet = { "w1": { "session_id": "w1", "persona": "Cheech", "state": "idle",
                      "alive": True, "holding_on": None } }
    job._publish_fleet_snapshot( fleet, now )
    assert read_carry( p ) == { "w1": "Tiberius" }                    # first poll → written
    stamp = p.stat().st_mtime_ns
    job._publish_fleet_snapshot( fleet, now )                         # unchanged mapping
    assert p.stat().st_mtime_ns == stamp                              # NO rewrite (write-on-change)


def test_publish_carry_write_failure_journaled_not_raised( tmp_path ):
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    log = _Log()
    now = __import__( "datetime" ).datetime( 2026, 6, 11, 22, 0, 0,
                                             tzinfo=__import__( "datetime" ).timezone.utc )
    job = _job(
        log                = log,
        lineage_carry_path = str( blocked / "sub" / "lineage-carry.json" ),
        bridge_mtime_fn    = lambda sid: now.timestamp(),
        resolve_manager_fn = lambda sid, declared_manager=None: {
            "manager_persona": "Tiberius", "source": "lineage" },
        snapshot_sink      = lambda s: None,
        render_sink        = lambda s: None,
    )
    fleet = { "w1": { "session_id": "w1", "persona": "Cheech", "state": "idle",
                      "alive": True, "holding_on": None } }
    blocked.chmod( 0o500 )
    try:
        job._publish_fleet_snapshot( fleet, now )                     # must not raise
    finally:
        blocked.chmod( 0o700 )
    assert log.of( "lineage_carry_error" )                            # visible, never silent


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
