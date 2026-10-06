#!/usr/bin/env python3
"""
Persists the arbiter's lineage-carry map to a JSON file so it survives restarts.

A reaped worker loses both lineage sources at reap: `dismiss_sessions` drops its
manifest record and unlinks its bridge. The in-poll `carry_forward_lineage` map
is then the only thing keeping its decaying Fleet-Status row under its manager.
That map is in memory, so a :8001 restart would dump the row into "(Unmanaged)".
This file keeps the mapping alive for the rows' decay window.

Shape is a flat JSON object, session_id -> last-known manager persona:
    { "<session_id>": "Tiberius", ... }

The file stays small because the caller persists the already-pruned mapping.
`carry_forward_lineage` prunes to the current full-snapshot session ids each poll.
A row that leaves the snapshot therefore leaves the file on the same poll.

Same file family and idioms as `outreach_ledger` (io/arbiter/, reads that
degrade to empty, atomic per-writer tmp-write then rename).
"""
import json
import os
import uuid
from pathlib import Path


def read_carry( path ) -> dict:
    """
    Read the persisted lineage-carry mapping.

    Requires:
        - path is a path-like / string

    Ensures:
        - returns { session_id: manager_persona } (empty dict when the file is
          missing, unreadable, malformed, or not a JSON object)
        - only non-empty-string keys and values are kept (a malformed member is
          skipped, never propagated into the snapshot)
        - degrade-safe: never raises, and any error gives an empty dict (a carry
          read must never break a poll; the worst case is no carried lineage)
    """
    try:
        with open( path ) as f:
            raw = json.load( f )
        if not isinstance( raw, dict ):
            return { }
        return { k: v for k, v in raw.items()
                 if isinstance( k, str ) and k and isinstance( v, str ) and v }
    except Exception:
        return { }


def write_carry( path, mapping: dict ) -> None:
    """
    Persist the lineage-carry mapping atomically.

    Requires:
        - path is a path-like / string
        - mapping is { session_id: manager_persona }

    Ensures:
        - the file contains exactly `mapping` (the caller owns prune semantics —
          it persists carry_forward_lineage's already-pruned output)
        - parent directory is created if absent
        - write is atomic (per-writer pid+uuid-suffixed tmp + rename)
        - raises OSError if the target is not writable (the caller journals
          `lineage_carry_error` — visible, never silent)
    """
    path = Path( path )
    path.parent.mkdir( parents=True, exist_ok=True )
    tmp  = path.parent / f"{path.name}.{os.getpid()}-{uuid.uuid4().hex}.tmp"
    with open( tmp, "w" ) as f:
        json.dump( mapping, f, default=str )
    tmp.replace( path )


def quick_smoke_test():
    """Self-contained smoke test of the carry round-trip. Returns True or raises."""
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        path = Path( d ) / "sub" / "lineage-carry.json"

        # missing file → empty (degrade-safe); parent auto-created on write
        assert read_carry( path ) == { }
        write_carry( path, { "sid-1": "Tiberius", "sid-2": "Mr. Radio" } )
        assert read_carry( path ) == { "sid-1": "Tiberius", "sid-2": "Mr. Radio" }
        assert not list( path.parent.glob( "*.tmp" ) )                # tmp renamed away

        # caller-owned prune: a smaller write REPLACES (no merge)
        write_carry( path, { "sid-2": "Mr. Radio" } )
        assert read_carry( path ) == { "sid-2": "Mr. Radio" }

        # malformed members skipped; malformed file → empty
        write_carry( path, { "ok": "Ann", "": "X", "bad": 7 } )
        assert read_carry( path ) == { "ok": "Ann" }
        bad = Path( d ) / "bad.json"
        bad.write_text( '["not an object"]' )
        assert read_carry( bad ) == { }
        bad.write_text( "{not json" )
        assert read_carry( bad ) == { }

    return True


if __name__ == "__main__":   # pragma: no cover - manual smoke entrypoint
    ok = quick_smoke_test()
    print( f"lineage_carry smoke: {'PASS' if ok else 'FAIL'}" )
