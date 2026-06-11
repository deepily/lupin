#!/usr/bin/env python3
"""
Outreach pending ledger — the re-announce-on-return persistence leaf (Item B §3.5
of `src/rnd/v0.1.8/2026.06.11-arbiter-outreach-delivery-receipts-and-local-
timestamps.md`).

A Rick-bound advisory whose live push reported `user_not_available` (his WS was
offline — the 2026-06-11 latent L1 failure mode) must NOT evaporate: it enters
this ledger and the arbiter re-announces it each poll (bounded by the reannounce
interval) until a delivered outcome or TTL expiry — the milestone-must-land
doctrine, mechanized.

File-backed (NOT in-memory) by explicit design: the ledger survives BOTH the 12h
job recycle AND a full service restart, so a stall advisory fired while Rick
sleeps still greets his morning return across a deploy. Pattern mirrored
line-for-line from the stop-hook oracle's `heartbeat_acked_ledger`: degrade-safe
reads (any error ⇒ empty — telemetry must never kill a poll), atomic writes
(tmp-write + per-writer-suffixed rename), merge-don't-clobber.

Schema — a JSON object keyed by outreach_id:
    { "<outreach_id>": { "message": str, "kind": str, "case": int|None,
                         "created_ts": iso, "attempts": int,
                         "last_attempt_ts": iso, "last_outcome": str }, ... }
"""
import json
import os
import uuid
from pathlib import Path


def read_pending( path ) -> dict:
    """
    Read the pending-outreach ledger.

    Requires:
        - path is a path-like / string

    Ensures:
        - returns a dict of outreach_id -> entry dict (empty dict when the file
          is missing, unreadable, malformed, or not a JSON object)
        - only dict-valued entries are kept (malformed members are skipped)
        - DEGRADE-SAFE: never raises — any error ⇒ empty dict (a ledger read
          must never break a poll)
    """
    try:
        with open( path ) as f:
            raw = json.load( f )
        if not isinstance( raw, dict ):
            return { }
        return { k: v for k, v in raw.items() if isinstance( v, dict ) }
    except Exception:
        return { }


def write_pending( path, entries: dict ) -> None:
    """
    Persist the pending-outreach ledger atomically.

    Requires:
        - path is a path-like / string
        - entries is a dict of outreach_id -> entry dict

    Ensures:
        - the file contains exactly `entries` (the caller owns merge semantics —
          it read-modify-writes within the single-threaded poll loop)
        - parent directory is created if absent
        - write is atomic (tmp-write + rename); the temp file carries a
          per-writer pid+uuid suffix so concurrent writers never share a path
        - raises OSError if the target directory is not writable (a ledger that
          CANNOT persist must fail loud at the write site — the caller's
          journaled swallow makes it visible, not silent)
    """
    path = Path( path )
    path.parent.mkdir( parents=True, exist_ok=True )
    tmp  = path.parent / f"{path.name}.{os.getpid()}-{uuid.uuid4().hex}.tmp"
    with open( tmp, "w" ) as f:
        json.dump( entries, f, default=str )
    tmp.replace( path )


def add_pending( path, outreach_id: str, *, message: str, kind: str, case,
                 created_ts: str, last_outcome: str ) -> dict:
    """
    Add (or refresh) one undelivered Rick-bound outreach.

    Requires:
        - path is a path-like / string
        - outreach_id / message / kind / created_ts / last_outcome are strings
        - case is an int or None

    Ensures:
        - the ledger contains an entry for outreach_id with attempts=1 and
          last_attempt_ts=created_ts (an existing entry for the SAME id is
          refreshed, never duplicated — merge-don't-clobber on the id key)
        - other entries are preserved
        - returns the resulting ledger dict
    """
    entries = read_pending( path )
    entries[ outreach_id ] = {
        "message"         : message,
        "kind"            : kind,
        "case"            : case,
        "created_ts"      : created_ts,
        "attempts"        : 1,
        "last_attempt_ts" : created_ts,
        "last_outcome"    : last_outcome,
    }
    write_pending( path, entries )
    return entries


def record_attempt( path, outreach_id: str, *, attempt_ts: str, outcome: str ) -> dict:
    """
    Record a re-announce attempt's outcome against a pending entry.

    Ensures:
        - the entry's attempts increments, last_attempt_ts / last_outcome update
        - an unknown outreach_id is a no-op (entry may have been resolved by a
          concurrent path — degrade-safe, never raises KeyError)
        - returns the resulting ledger dict
    """
    entries = read_pending( path )
    entry   = entries.get( outreach_id )
    if entry is not None:
        entry[ "attempts" ]        = int( entry.get( "attempts", 0 ) ) + 1
        entry[ "last_attempt_ts" ] = attempt_ts
        entry[ "last_outcome" ]    = outcome
        write_pending( path, entries )
    return entries


def remove_pending( path, outreach_id: str ) -> dict:
    """
    Remove a resolved (delivered or expired) entry.

    Ensures:
        - the entry is absent afterward; unknown id is a no-op
        - returns the resulting ledger dict
    """
    entries = read_pending( path )
    if outreach_id in entries:
        del entries[ outreach_id ]
        write_pending( path, entries )
    return entries


def quick_smoke_test():
    """Self-contained smoke test of the ledger round-trip. Returns True or raises."""
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        path = Path( d ) / "sub" / "outreach-pending.json"

        # missing file → empty (degrade-safe); parent auto-created on first add
        assert read_pending( path ) == { }
        add_pending( path, "o1", message="stall", kind="stall", case=11,
                     created_ts="t0", last_outcome="user_not_available" )
        assert read_pending( path )[ "o1" ][ "attempts" ] == 1

        # attempt recording increments + updates; unknown id no-ops
        record_attempt( path, "o1", attempt_ts="t1", outcome="user_not_available" )
        entry = read_pending( path )[ "o1" ]
        assert entry[ "attempts" ] == 2 and entry[ "last_attempt_ts" ] == "t1"
        record_attempt( path, "ghost", attempt_ts="t1", outcome="x" )   # no-op
        assert "ghost" not in read_pending( path )

        # same-id refresh, other entries preserved; removal resolves
        add_pending( path, "o2", message="dark", kind="fleet_dark", case=15,
                     created_ts="t2", last_outcome="user_not_available" )
        add_pending( path, "o1", message="stall", kind="stall", case=11,
                     created_ts="t3", last_outcome="user_not_available" )
        assert read_pending( path )[ "o1" ][ "attempts" ] == 1 and "o2" in read_pending( path )
        remove_pending( path, "o1" )
        assert set( read_pending( path ) ) == { "o2" }

        # malformed (non-object) JSON → empty
        bad = Path( d ) / "bad.json"
        bad.write_text( '["not", "an", "object"]' )
        assert read_pending( bad ) == { }

    return True


if __name__ == "__main__":   # pragma: no cover - manual smoke entrypoint
    ok = quick_smoke_test()
    print( f"outreach_ledger smoke: {'PASS' if ok else 'FAIL'}" )
