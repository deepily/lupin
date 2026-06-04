#!/usr/bin/env python3
"""
Heartbeat Hook — poke-outcome event emitter ("EMIT NOW, CONSUME LATER").

v1's Stop-hook decision path writes a FIRE-AND-FORGET, per-session JSON Lines
record of each meaningful heartbeat outcome. The v2 fleet arbiter (deferred)
lands as a PURE CONSUMER that globs the fleet dir — zero hook retrofit. The
emit must NEVER raise into / block the poke path: an emission failure leaves
the poke proceeding unchanged.

Design authority: canonical schema in planning-is-prompting →
    src/rnd/2026.06.02-stop-hook-natural-heartbeat-poker.md §0.2 (María, arbiter owner).
Lupin-side seam: lupin →
    src/rnd/v0.1.8/2026.06.04-heartbeat-hook/02-stop-py-seam-factoring-proposal.md

**Location — FLEET-WIDE (deliberate divergence from the hold artifact).** The
events log's consumer is the cross-fleet arbiter, so the files live in ONE
fleet dir — `~/.claude/heartbeat-events/<session_id>.jsonl` — giving the
arbiter a single glob across all sessions/projects, durable across reboots.
This is the ONE place the `cu.get_project_root()` path mandate intentionally
does NOT apply (the consumer is fleet-wide, not project-local). Per-session
filename keeps it multi-writer-safe (no append contention). `base_dir` is
injectable for tests; production uses the fleet dir.

Record (schema_version 1) — one line per EMITTED heartbeat decision:
    schema_version · session_id · persona · ts (ISO-8601 UTC)
    outcome    : "poke" | "honored" | "cap_reached"   (raw decide_heartbeat outcome)
    poke_count : per-session heartbeat count AFTER this event · cap
    work_owed  : bool — **null in v1** (oracle_verdict=None); real bool at v2, ZERO schema change
    awaiting   : str | null   (from the hold artifact, else null)
    reason     : str          (present ONLY when outcome == "poke")

**Emit policy:** ONLY {poke, honored, cap_reached}. `not_owed` is skipped — a
Stop hook fires after every ordinary turn, so it would be constant per-turn
noise, not fleet signal. Disabled / malformed-config sessions never reach the
emit (no decide_heartbeat outcome).

**Deferred to v2 (flagged, NOT built):** JSONL rotation / line-cap so the file
cannot grow unbounded.
"""
import os
import json
import datetime
from pathlib import Path

from lupin_cli.claude_code.hooks.lib.heartbeat_decision import (
    OUTCOME_POKE, OUTCOME_HONORED, OUTCOME_CAP_REACHED,
)


SCHEMA_VERSION           = 1
EVENTS_FILENAME_TEMPLATE = "{session_id}.jsonl"

# Fleet-wide events dir (NOT project root — see module docstring).
FLEET_EVENTS_DIR = Path( os.path.expanduser( "~/.claude/heartbeat-events" ) )

# Only these outcomes are emitted (not_owed is per-turn noise; skipped).
EMITTED_OUTCOMES = ( OUTCOME_POKE, OUTCOME_HONORED, OUTCOME_CAP_REACHED )


def _resolve_base_dir( base_dir ):
    """
    Ensures:
        - base_dir provided → Path( base_dir )
        - base_dir is None  → the FLEET dir (~/.claude/heartbeat-events).
          NOTE: intentionally NOT cu.get_project_root() — the consumer is the
          cross-fleet arbiter, not a project-local reader.
    """
    if base_dir is not None:
        return Path( base_dir )
    return FLEET_EVENTS_DIR


def events_path( session_id, base_dir=None ):
    """
    Ensures:
        - Returns <base_dir-or-fleet-dir>/<session_id>.jsonl
        - Empty session_id collapses to the literal suffix "unknown".
    """
    suffix = session_id if session_id else "unknown"
    return _resolve_base_dir( base_dir ) / EVENTS_FILENAME_TEMPLATE.format( session_id=suffix )


def _now_iso():
    """Ensures: returns the current UTC instant as an ISO-8601 string (seconds)."""
    return datetime.datetime.now( datetime.timezone.utc ).isoformat( timespec="seconds" )


def emit_outcome( session_id, persona, outcome, poke_count, cap,
                  work_owed=None, awaiting=None, reason=None, ts=None, base_dir=None ):
    """
    Append one fire-and-forget poke-outcome record. NEVER raises.

    Requires:
        - session_id is a string
        - persona is a string or None (from the session — known even with no hold)
        - outcome is a decide_heartbeat OUTCOME_* string
        - poke_count (AFTER this event's increment) and cap are ints
        - work_owed is a bool or None (None in v1)
        - awaiting is a string or None (caller passes the hold's awaiting, else None)
        - reason is the poke text (included ONLY when outcome == "poke")

    Ensures:
        - Emits ONLY for {poke, honored, cap_reached}; any other outcome
          (incl. not_owed / unknown) → returns False, writes nothing
        - Creates the fleet dir if missing (parents, idempotent)
        - Appends exactly one JSON line (schema_version 1 record)
        - reason key present ONLY for the poke outcome (omitted otherwise)
        - Returns True on a successful append; False on a skipped outcome or
          any write / serialization failure — NEVER raises into the caller
    """
    try:
        if outcome not in EMITTED_OUTCOMES:
            return False

        record = {
            "schema_version" : SCHEMA_VERSION,
            "session_id"     : session_id,
            "persona"        : persona,
            "ts"             : ts if ts is not None else _now_iso(),
            "outcome"        : outcome,
            "poke_count"     : poke_count,
            "cap"            : cap,
            "work_owed"      : work_owed,
            "awaiting"       : awaiting,
        }
        if outcome == OUTCOME_POKE and reason is not None:
            record[ "reason" ] = reason

        path = events_path( session_id, base_dir=base_dir )
        path.parent.mkdir( parents=True, exist_ok=True )
        with open( path, "a" ) as f:
            f.write( json.dumps( record ) + "\n" )
        return True
    except ( OSError, TypeError, ValueError ):
        return False


def read_events( session_id, base_dir=None ):
    """
    Read this session's event records (for the v2 arbiter + tests).

    Requires:
        - session_id is a string

    Ensures:
        - Returns a list of record dicts in append order
        - Missing file → [] ; unreadable file → [] (never raises)
        - Blank / malformed / non-object JSON lines are skipped (resilient tail)
    """
    path = events_path( session_id, base_dir=base_dir )
    records = [ ]
    try:
        if not path.exists():
            return records
        with open( path ) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads( line )
                except ValueError:
                    continue
                if isinstance( obj, dict ):
                    records.append( obj )
    except OSError:
        return records
    return records


def quick_smoke_test():
    """
    Self-contained smoke test (temp dir — never touches the real fleet dir).

    Ensures:
        - Returns True if emit → read round-trips for the emitted outcomes,
          not_owed is skipped, and reason rides only the poke; raises otherwise.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        sid = "smoke321"

        assert emit_outcome( sid, "Tiffany 💍", OUTCOME_POKE, 1, 3,
                             awaiting="peer:Rachel", reason="poke text", base_dir=tmp ) is True
        assert emit_outcome( sid, "Tiffany 💍", OUTCOME_HONORED, 0, 3,
                             awaiting="peer:Rachel", reason="ignored", base_dir=tmp ) is True
        # not_owed is skipped — no line, returns False
        assert emit_outcome( sid, "Tiffany 💍", "not_owed", 0, 3, base_dir=tmp ) is False

        events = read_events( sid, base_dir=tmp )
        assert len( events ) == 2,                      "two emitted events expected"
        assert events[ 0 ][ "outcome" ] == "poke"
        assert events[ 0 ][ "reason" ] == "poke text"
        assert events[ 0 ][ "work_owed" ] is None,      "v1 work_owed is null"
        assert events[ 0 ][ "awaiting" ] == "peer:Rachel"
        assert events[ 1 ][ "outcome" ] == "honored"
        assert "reason" not in events[ 1 ],             "reason rides ONLY the poke"

    return True


if __name__ == "__main__":   # pragma: no cover - manual smoke entrypoint
    ok = quick_smoke_test()
    print( f"heartbeat_events smoke: {'PASS' if ok else 'FAIL'}" )
