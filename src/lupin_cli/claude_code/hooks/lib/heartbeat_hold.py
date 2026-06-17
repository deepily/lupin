#!/usr/bin/env python3
"""
Heartbeat Hook — hold-artifact read/write module.

Standalone helper for the per-session "declared hold" artifact that the
Heartbeat Hook's `Stop`-hook decision logic consults. A paused instance
*defends its quiescence* by writing a hold file; the hook honors a present,
fresh, reasoned hold and declines to poke.

Design authority (LOCKED): planning-is-prompting →
    src/rnd/2026.06.02-stop-hook-natural-heartbeat-poker.md  §0 decision #7.
Lupin-side seam analysis: lupin →
    src/rnd/v0.1.8/2026.06.04-heartbeat-hook/01-spike-findings-and-stop-py-seam-analysis.md

Artifact: per-session JSON file `.heartbeat-hold-<session_id>.json` in the
project root (runtime-state family with `.claude-session.md` /
`.claude-memento.md`; gitignored). **Per-session filename = multi-writer
safe** — each instance writes/reads only its own file (derived from the
`session_id` in the hook input); a future fleet Poker globs
`.heartbeat-hold-*.json` for the cross-session view.

Schema (§0 decision #7 — the public interface; hold to it exactly):
    session_id  : str   — = filename suffix
    persona     : str   — owning persona (e.g. "María 🌸")
    held_at     : str   — ISO-8601 timestamp the hold was declared
    ttl_seconds : int   — freshness window; expired ⇒ undeclared ⇒ pokeable
    work_owed   : bool  — False ⇒ done ⇒ never poke
    reason      : str   — why the instance is holding
    awaiting    : str   — "user:<name>" / "peer:<persona>" / "commons:<topic>" / "none"

This module deals ONLY with the declared hold artifact. The work-owed
*oracle* (TODO / Pending-Decisions scan, §0 #3) and the `Stop`-hook decision
flow itself (Branch C of stop.py) are SEPARATE concerns built later, after
the 3-way shared-substrate seam review with Rachel + María.
"""
import os
import json
import datetime
from pathlib import Path


# Public interface constants — §0 decision #7
HOLD_FILENAME_TEMPLATE = ".heartbeat-hold-{session_id}.json"
HOLD_SCHEMA_FIELDS     = ( "session_id", "persona", "held_at", "ttl_seconds", "work_owed", "reason", "awaiting" )
DEFAULT_TTL_SECONDS    = 900
AWAITING_NONE          = "none"


def _resolve_base_dir( base_dir ):
    """
    Resolve the directory that holds `.heartbeat-hold-*.json` files.

    Requires:
        - base_dir is a path-like, a string, or None

    Ensures:
        - Returns a Path
        - base_dir provided  → Path( base_dir )
        - base_dir is None   → project root via cu.get_project_root()
          (PATH MANAGEMENT mandate — never __file__ chains)
    """
    if base_dir is not None:
        return Path( base_dir )
    import cosa.utils.util as cu
    return Path( cu.get_project_root() )


def resolve_hold_base_dir( cwd=None ):
    """
    Per-SESSION base dir for `.heartbeat-hold-*.json` artifacts (c121037b facet 3).

    The hold lives in the session's OWN project root (runtime-state family with
    .claude-session.md). Resolving it from the hardwired LUPIN_ROOT
    (cu.get_project_root) made every NON-lupin session's hold land under lupin —
    invisible to that session's own Stop-hook reads. The Stop hook now threads its
    payload `cwd` (the session's actual working dir = where the poked agent writes
    its hold) so the hold resolves per-session.

    Requires:
        - cwd is a path-like / string / None (the Stop-hook payload's cwd)

    Ensures:
        - Truthy cwd → Path( cwd )  (the session's own root — per-session)
        - Falsy/None cwd → cu.get_project_root()  (LUPIN_ROOT fallback; the
          test seam patches cu.get_project_root for isolation)
        - Never raises
    """
    if cwd:
        return Path( cwd )
    import cosa.utils.util as cu
    return Path( cu.get_project_root() )


def hold_path( session_id, base_dir=None ):
    """
    Compute the per-session hold-file path.

    Requires:
        - session_id is a string (may be empty)
        - base_dir is a path-like / string / None

    Ensures:
        - Returns Path = <base_dir>/.heartbeat-hold-<session_id>.json
        - Empty session_id collapses to the literal suffix "unknown"
          (never produces a bare ".heartbeat-hold-.json")
    """
    suffix = session_id if session_id else "unknown"
    return _resolve_base_dir( base_dir ) / HOLD_FILENAME_TEMPLATE.format( session_id=suffix )


def _now():
    """
    Ensures:
        - Returns a timezone-aware (UTC) datetime for "now".
    """
    return datetime.datetime.now( datetime.timezone.utc )


def _parse_iso( value ):
    """
    Parse an ISO-8601 timestamp into a timezone-aware datetime.

    Requires:
        - value is anything (defensive)

    Ensures:
        - Returns an aware datetime on success (naive input assumed UTC)
        - Accepts a trailing "Z" (Zulu) by normalizing to "+00:00"
        - Returns None on empty / non-string / unparseable input
        - Never raises
    """
    if not value or not isinstance( value, str ):
        return None
    text = value.strip()
    if text.endswith( "Z" ):
        text = text[ :-1 ] + "+00:00"
    try:
        parsed = datetime.datetime.fromisoformat( text )
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace( tzinfo=datetime.timezone.utc )
    return parsed


def write_hold( session_id, persona, reason, work_owed=True,
                ttl_seconds=DEFAULT_TTL_SECONDS, awaiting=AWAITING_NONE,
                held_at=None, base_dir=None ):
    """
    Write (atomically) this session's hold artifact and return the dict.

    Requires:
        - session_id is a non-empty string
        - persona and reason are strings
        - work_owed is a bool
        - ttl_seconds is a positive int
        - awaiting is a string (see schema)

    Ensures:
        - Writes <base_dir>/.heartbeat-hold-<session_id>.json with EXACTLY
          the 7 schema fields, in HOLD_SCHEMA_FIELDS order
        - held_at defaults to now (UTC, seconds precision) when not supplied
        - Write is atomic (temp file + os.replace) so a concurrent fleet
          Poker never reads a half-written file
        - Returns the hold dict that was written

    Raises:
        - OSError if the target directory is not writable / does not exist
    """
    if held_at is None:
        held_at = _now().isoformat( timespec="seconds" )

    hold = {
        "session_id"  : session_id,
        "persona"     : persona,
        "held_at"     : held_at,
        "ttl_seconds" : ttl_seconds,
        "work_owed"   : work_owed,
        "reason"      : reason,
        "awaiting"    : awaiting,
    }

    path = hold_path( session_id, base_dir=base_dir )
    tmp  = path.parent / ( path.name + ".tmp" )
    tmp.write_text( json.dumps( hold, indent=2 ) )
    os.replace( tmp, path )
    return hold


def _read_hold_path( session_id, base_dir=None ):
    """
    Resolve which hold file `read_hold` should read — exact id first, else a
    hold whose filename shares this session's 8-char id prefix (c121037b facet 2).

    An agent that WRITES a hold may use the SHORT bridge id (get_session_info
    hands it the 8-char form) while the Stop hook reads with the FULL stable id;
    without this fallback that hold is silently ignored and the session is poked
    forever despite having declared a hold.

    Requires:
        - session_id is a string (may be empty)
        - base_dir is a path-like / string / None

    Ensures:
        - Returns the exact <base>/.heartbeat-hold-<session_id>.json when present
        - Else, for a non-empty session_id, returns the hold file whose id-suffix
          shares session_id[:8] (ignoring `.tmp` atomic-write artifacts); on
          multiple id-form matches, prefers the longest suffix (a full hyphenated
          id over a short 8-char form), then lexical — deterministic, clock-free
        - Else returns the exact path (which read_hold treats as absent)
        - Never raises (glob OSError → the exact path)
    """
    exact = hold_path( session_id, base_dir=base_dir )
    if exact.exists() or not session_id:
        return exact
    prefix  = session_id[ :8 ]
    pattern = HOLD_FILENAME_TEMPLATE.format( session_id=prefix + "*" )
    try:
        matches = [ p for p in _resolve_base_dir( base_dir ).glob( pattern )
                    if not p.name.endswith( ".tmp" ) ]
    except OSError:
        return exact
    if not matches:
        return exact
    return sorted( matches, key=lambda p: ( len( p.name ), p.name ), reverse=True )[ 0 ]


def read_hold( session_id, base_dir=None ):
    """
    Read this session's hold artifact.

    Requires:
        - session_id is a string

    Ensures:
        - Returns the hold dict if the file exists and parses to a JSON object
        - Falls back across short/full id forms when the exact file is absent
          (c121037b facet 2 — see _read_hold_path)
        - Returns None if no hold is found, unreadable, malformed, or parses to a
          non-object JSON value
        - Never raises
    """
    path = _read_hold_path( session_id, base_dir=base_dir )
    try:
        if not path.exists():
            return None
        data = json.loads( path.read_text() )
    except ( OSError, ValueError ):
        return None
    if not isinstance( data, dict ):
        return None
    return data


def clear_hold( session_id, base_dir=None ):
    """
    Delete this session's hold artifact (idempotent).

    Requires:
        - session_id is a string

    Ensures:
        - Removes the hold file if present; no-op if absent
        - Never raises (OSError is swallowed)
    """
    path = hold_path( session_id, base_dir=base_dir )
    try:
        path.unlink( missing_ok=True )
    except OSError:
        pass


def is_fresh( hold, now=None ):
    """
    Is this hold still within its freshness window?

    Requires:
        - hold is a dict or None
        - now is an aware datetime or None (defaults to current UTC)

    Ensures:
        - Returns False for a missing hold, an unparseable/absent held_at,
          or a non-numeric ttl_seconds (bool is explicitly rejected)
        - Otherwise returns (now - held_at) < ttl_seconds  (§0 freshness rule)
        - Never raises
    """
    if not hold:
        return False
    held_dt = _parse_iso( hold.get( "held_at" ) )
    if held_dt is None:
        return False
    ttl = hold.get( "ttl_seconds" )
    if isinstance( ttl, bool ) or not isinstance( ttl, ( int, float ) ):
        return False
    if now is None:
        now = _now()
    elapsed_seconds = ( now - held_dt ).total_seconds()
    return elapsed_seconds < ttl


def is_honored( hold, now=None ):
    """
    Should the hook HONOR this hold (i.e. NOT poke)?

    A hold is honored only when it is DECLARED, FRESH, and REASONED — the
    "defend your quiescence" discriminator (§0 decision #3).

    Requires:
        - hold is a dict or None
        - now is an aware datetime or None

    Ensures:
        - Returns True iff hold is fresh AND has a non-empty reason
        - Returns False otherwise
        - Never raises
    """
    if not is_fresh( hold, now=now ):
        return False
    reason = hold.get( "reason" )
    return bool( reason and str( reason ).strip() )


def declared_work_owed( hold ):
    """
    The hold's self-declared work_owed flag, if any.

    Used as the FIRST source of work-owed truth in the Branch-C decision
    flow (§0 step 3) before falling back to the TODO/Pending oracle.

    Requires:
        - hold is a dict or None

    Ensures:
        - Returns the bool value of hold["work_owed"] when present and boolean
        - Returns None when there is no hold or the field is absent/non-bool
        - Never raises
    """
    if not hold:
        return None
    value = hold.get( "work_owed" )
    if isinstance( value, bool ):
        return value
    return None


def quick_smoke_test():
    """
    Self-contained, side-effect-free smoke test (uses a temp dir).

    Ensures:
        - Returns True if write → read round-trips and freshness/honor/owed
          semantics behave as designed; raises AssertionError otherwise.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        sid = "smoke1234"

        # Fresh declared hold → honored, not pokeable
        write_hold( sid, "Tiffany 💍", "holding on the 3-way seam review",
                    work_owed=True, ttl_seconds=900, awaiting="peer:Rachel", base_dir=tmp )
        hold = read_hold( sid, base_dir=tmp )
        assert hold is not None,                      "round-trip read failed"
        assert tuple( hold.keys() ) == HOLD_SCHEMA_FIELDS, "schema field set/order drift"
        assert is_fresh( hold ),                      "fresh hold reported stale"
        assert is_honored( hold ),                    "reasoned fresh hold not honored"
        assert declared_work_owed( hold ) is True,    "work_owed not read back"

        # Expired hold → undeclared ⇒ pokeable (not honored)
        old = ( _now() - datetime.timedelta( seconds=10_000 ) ).isoformat( timespec="seconds" )
        write_hold( sid, "Tiffany 💍", "stale", ttl_seconds=900, held_at=old, base_dir=tmp )
        assert not is_honored( read_hold( sid, base_dir=tmp ) ), "expired hold still honored"

        # Cleared hold → absent
        clear_hold( sid, base_dir=tmp )
        assert read_hold( sid, base_dir=tmp ) is None, "clear_hold did not remove file"

    return True


if __name__ == "__main__":   # pragma: no cover - manual smoke entrypoint
    ok = quick_smoke_test()
    print( f"heartbeat_hold smoke: {'PASS' if ok else 'FAIL'}" )
