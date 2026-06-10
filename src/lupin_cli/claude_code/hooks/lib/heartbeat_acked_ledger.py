#!/usr/bin/env python3
"""
Heartbeat Hook — acked-inbound ledger read/write module.

Spec part (c) of the work-owed oracle acked-inbound ledger (Rick 2026-06-10,
"the self-poke backlog is way too goddamn big... pull these things off and mark
them as looked at"): an EXPLICIT looked-at ledger a manager can bulk-write so
the unanswered-inbound gatherer SUBTRACTS already-reviewed question-ids from the
owed count.

Artifact: per-session JSON file `.heartbeat-acked-<session_id>.json` in the
project root — same runtime-state family as `.heartbeat-hold-<session_id>.json`
(gitignored, per-session ⇒ multi-writer safe; each instance reads/writes only
its own file). The base-dir resolver is REUSED from `heartbeat_hold` so the two
artifacts always co-locate (single source of truth for the directory).

Schema: a JSON array of question-id strings the owner has marked "looked at":
    [ "6e9aca6f-...", "53a95e30-...", ... ]

Reads are degrade-safe (any error ⇒ empty set — never raises, never blocks the
Stop). Writes MERGE (idempotent union) so repeated bulk-marks accrete instead of
clobbering, and are atomic (tmp-write + rename) like the hold artifact.
"""

import json
import os
import uuid
from pathlib import Path

from lupin_cli.claude_code.hooks.lib.heartbeat_hold import _resolve_base_dir

ACKED_FILENAME_TEMPLATE = ".heartbeat-acked-{session_id}.json"


def acked_ledger_path( session_id, base_dir=None ):
    """
    Compute the per-session acked-ledger file path.

    Requires:
        - session_id is a string (may be empty)
        - base_dir is a path-like / string / None

    Ensures:
        - Returns Path = <base_dir>/.heartbeat-acked-<session_id>.json
        - Empty session_id collapses to the literal suffix "unknown"
          (never produces a bare ".heartbeat-acked-.json")
        - base_dir is resolved by heartbeat_hold._resolve_base_dir so the
          ledger always co-locates with the hold artifact
    """
    suffix = session_id if session_id else "unknown"
    return _resolve_base_dir( base_dir ) / ACKED_FILENAME_TEMPLATE.format( session_id=suffix )


def read_acked_qids( session_id, base_dir=None ):
    """
    Read the set of question-ids this session has marked "looked at".

    Requires:
        - session_id is a string
        - base_dir is a path-like / string / None

    Ensures:
        - Returns a set[str] of qids (empty set when the file is missing,
          unreadable, malformed, or not a JSON array)
        - Only string entries are kept (non-string array members are skipped)
        - DEGRADE-SAFE: never raises — any error ⇒ empty set (the gatherer
          must never break the Stop on a ledger read)
    """
    try:
        path = acked_ledger_path( session_id, base_dir )
        with open( path ) as f:
            raw = json.load( f )
        if not isinstance( raw, list ):
            return set()
        return { q for q in raw if isinstance( q, str ) }
    except Exception:
        return set()


def mark_acked( session_id, qids, base_dir=None ):
    """
    Merge `qids` into this session's acked ledger (idempotent union).

    Requires:
        - session_id is a string
        - qids is an iterable of strings
        - base_dir is a path-like / string / None

    Ensures:
        - The ledger file contains the UNION of its prior contents and the
          string members of `qids` (existing entries are preserved — bulk-marks
          accrete, never clobber)
        - Non-string members of `qids` are ignored
        - Write is atomic (tmp-write + rename), mirroring the hold artifact
        - The temp file carries a per-writer pid+uuid suffix, so two managers
          bulk-marking the SAME session ledger concurrently never share one
          `.tmp` path (a shared name lets writer A's partial json be renamed
          into place by writer B). Each writer's `replace()` is still atomic;
          last-writer-wins on the final file (acceptable — both merge over the
          same prior contents, so neither loses the other's prior-state union)
        - Returns the resulting sorted list[str] of acked qids
        - Raises OSError if the target directory is not writable
    """
    existing = read_acked_qids( session_id, base_dir )
    merged   = existing | { q for q in qids if isinstance( q, str ) }
    ordered  = sorted( merged )
    path = acked_ledger_path( session_id, base_dir )
    tmp  = path.parent / f"{path.name}.{os.getpid()}-{uuid.uuid4().hex}.tmp"
    with open( tmp, "w" ) as f:
        json.dump( ordered, f )
    tmp.replace( path )
    return ordered


def quick_smoke_test():
    """
    Self-contained smoke test of the ledger read/write round-trip.

    Ensures:
        - Returns True if path/read/merge/degrade-safe behave as designed;
          raises AssertionError otherwise.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        # Missing file → empty set (degrade-safe)
        assert read_acked_qids( "sid", base_dir=d ) == set()

        # Mark two → present; mark again with overlap → union, no clobber
        assert mark_acked( "sid", [ "q1", "q2", 7 ], base_dir=d ) == [ "q1", "q2" ]
        assert read_acked_qids( "sid", base_dir=d ) == { "q1", "q2" }
        assert mark_acked( "sid", [ "q2", "q3" ], base_dir=d ) == [ "q1", "q2", "q3" ]

        # Path shape + empty-session fallback
        assert acked_ledger_path( "sid", base_dir=d ).name == ".heartbeat-acked-sid.json"
        assert acked_ledger_path( "", base_dir=d ).name    == ".heartbeat-acked-unknown.json"

        # Malformed (non-array) JSON → empty set
        bad = acked_ledger_path( "bad", base_dir=d )
        bad.write_text( '{"not":"a list"}' )
        assert read_acked_qids( "bad", base_dir=d ) == set()

    return True


if __name__ == "__main__":   # pragma: no cover - manual smoke entrypoint
    ok = quick_smoke_test()
    print( f"heartbeat_acked_ledger smoke: {'PASS' if ok else 'FAIL'}" )
