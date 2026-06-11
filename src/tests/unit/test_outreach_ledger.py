#!/usr/bin/env python3
"""
Item B §3.5 receipts (2026-06-11 outreach-receipts design) — the file-backed
pending-outreach ledger behind re-announce-on-return: degrade-safe reads, atomic
merge-don't-clobber writes, attempt recording, resolution removal. File-backed so
an undelivered Rick-bound advisory survives BOTH the 12h job recycle AND a
service restart (the S7 recycle-boundary scenario pins the consumer side).

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

from cosa.agents.heartbeat_arbiter.outreach_ledger import (
    add_pending, quick_smoke_test, read_pending, record_attempt,
    remove_pending, write_pending,
)


def _add( path, oid, **kw ):
    defaults = dict( message="WHOLE-FLEET-STALL", kind="stall", case=11,
                     created_ts="2026-06-11T21:28:46+00:00",
                     last_outcome="user_not_available" )
    defaults.update( kw )
    return add_pending( path, oid, **defaults )


# ── reads: degrade-safe in every failure shape ───────────────────────────────

def test_missing_file_reads_empty( tmp_path ):
    assert read_pending( tmp_path / "nope.json" ) == { }


def test_malformed_json_reads_empty( tmp_path ):
    p = tmp_path / "bad.json"
    p.write_text( "{not json" )
    assert read_pending( p ) == { }


def test_non_object_json_reads_empty( tmp_path ):
    p = tmp_path / "list.json"
    p.write_text( '["not", "an", "object"]' )
    assert read_pending( p ) == { }


def test_non_dict_members_are_skipped( tmp_path ):
    p = tmp_path / "mixed.json"
    p.write_text( json.dumps( { "good": { "message": "m" }, "bad": "a string" } ) )
    assert set( read_pending( p ) ) == { "good" }


# ── writes: atomic, parent-creating, fail-loud on unwritable target ─────────

def test_write_creates_parent_and_round_trips( tmp_path ):
    p = tmp_path / "sub" / "dir" / "pending.json"
    write_pending( p, { "o1": { "message": "m" } } )
    assert read_pending( p )[ "o1" ][ "message" ] == "m"
    assert not list( p.parent.glob( "*.tmp" ) )                       # tmp renamed away, never left behind


def test_write_unwritable_target_raises_oserror( tmp_path ):
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    blocked.chmod( 0o500 )                                            # no write permission
    try:
        with pytest.raises( OSError ):
            write_pending( blocked / "pending.json", { "o1": { } } )
    finally:
        blocked.chmod( 0o700 )


# ── add / record / remove lifecycle ──────────────────────────────────────────

def test_add_pending_initializes_entry( tmp_path ):
    p = tmp_path / "pending.json"
    _add( p, "o1" )
    entry = read_pending( p )[ "o1" ]
    assert entry[ "attempts" ] == 1 and entry[ "last_outcome" ] == "user_not_available"
    assert entry[ "last_attempt_ts" ] == entry[ "created_ts" ]
    assert entry[ "kind" ] == "stall" and entry[ "case" ] == 11


def test_add_same_id_refreshes_others_preserved( tmp_path ):
    p = tmp_path / "pending.json"
    _add( p, "o1" )
    record_attempt( p, "o1", attempt_ts="t1", outcome="user_not_available" )
    _add( p, "o2", kind="fleet_dark", case=15 )
    _add( p, "o1" )                                                   # refresh — attempts reset, no dupe
    entries = read_pending( p )
    assert entries[ "o1" ][ "attempts" ] == 1 and "o2" in entries and len( entries ) == 2


def test_record_attempt_increments_and_updates( tmp_path ):
    p = tmp_path / "pending.json"
    _add( p, "o1" )
    record_attempt( p, "o1", attempt_ts="t9", outcome="http_error" )
    entry = read_pending( p )[ "o1" ]
    assert entry[ "attempts" ] == 2
    assert entry[ "last_attempt_ts" ] == "t9" and entry[ "last_outcome" ] == "http_error"


def test_record_attempt_unknown_id_noops( tmp_path ):
    p = tmp_path / "pending.json"
    _add( p, "o1" )
    record_attempt( p, "ghost", attempt_ts="t9", outcome="x" )
    assert set( read_pending( p ) ) == { "o1" }


def test_remove_pending_resolves_and_unknown_noops( tmp_path ):
    p = tmp_path / "pending.json"
    _add( p, "o1" )
    _add( p, "o2" )
    remove_pending( p, "o1" )
    assert set( read_pending( p ) ) == { "o2" }
    remove_pending( p, "ghost" )                                      # no-op, no raise
    assert set( read_pending( p ) ) == { "o2" }


def test_module_quick_smoke_test_passes():
    assert quick_smoke_test() is True


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
