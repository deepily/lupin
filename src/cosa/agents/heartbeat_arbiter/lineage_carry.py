#!/usr/bin/env python3
"""
Lineage-carry persistence — the file-backed half of the Fleet-Status offline-
lineage fix (F-A of `src/rnd/v0.1.8/2026.06.11-arbiter-lineage-persistence-and-
persona-matching.md`).

A reaped worker loses BOTH lineage sources at the moment of reap
(`dismiss_sessions` drops its manifest record AND unlinks its bridge), so the
arbiter's in-poll `carry_forward_lineage` map is the ONLY thing keeping its
decaying Fleet-Status row under its manager — and that map was in-memory: each
:8001 restart (4× on 2026-06-11 alone) wiped it, dumping Cheech + old-Rio into
"(Unmanaged)". This module persists the carry to a small JSON file so the
mapping survives restarts for exactly the rows' decay window.

Shape — a flat JSON object, session_id -> last-known manager persona:
    { "<session_id>": "Tiberius", ... }

Bounded by construction: the caller persists the POST-prune mapping
(`carry_forward_lineage` prunes to the current full-snapshot sids each poll),
so the file tracks exactly the decay-window population and a row that evicts
from the snapshot evicts from the file on the same poll.

Same file family + idioms as `outreach_ledger` (io/arbiter/, degrade-safe
reads ⇒ empty, atomic per-writer-suffixed tmp-write + rename).
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
        - only non-empty-string keys AND values are kept (a malformed member is
          skipped, never propagated into the snapshot)
        - DEGRADE-SAFE: never raises — any error ⇒ empty dict (a carry read
          must never break a poll; worst case is today's pre-fix behavior)
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
