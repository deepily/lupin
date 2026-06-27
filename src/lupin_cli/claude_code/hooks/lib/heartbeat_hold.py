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

Schema (§0 decision #7 + 6929f4ac §9.2 — the public interface; hold to it exactly):
    session_id  : str   — = filename suffix
    persona     : str   — owning persona (e.g. "María 🌸")
    held_at     : str   — ISO-8601 timestamp the hold was declared
    ttl_seconds : int   — freshness window; expired ⇒ undeclared ⇒ pokeable
    work_owed   : bool  — False ⇒ done ⇒ never poke
    reason      : str   — why the instance is holding
    awaiting    : str   — "user:<name>" / "peer:<persona>" / "commons:<topic>" / "none"
    pending_user_gates           : list — structured open/answered direct-user-gate
                                          rows (6929f4ac §9.2 outward twin; promotes
                                          the free-text `awaiting: user:rick` to
                                          re-askable rows). See heartbeat_user_gates.
    last_looked_in_on_workers_ts : str|None — ISO-8601 of the MANAGER's most-recent
                                          worker-verification look-in (6929f4ac
                                          §3-§5 inward twin debounce clock); None ⇒
                                          never looked in. The agent stamps this
                                          when it verifies workers (explicit v1).
    last_spinup_check_ts         : str|None — ISO-8601 of the MANAGER's most-recent
                                          spin-up self-check (proactive-manager A1
                                          Face A debounce clock); None ⇒ never. The
                                          agent stamps it after considering a crew.
    last_surfaced_questions_ts   : str|None — ISO-8601 of the session's most-recent
                                          operator-gate re-surface (A1 Face B
                                          debounce clock); None ⇒ never. The agent
                                          stamps it after re-firing its open asks.

This module deals ONLY with the declared hold artifact. The work-owed
*oracle* (TODO / Pending-Decisions scan, §0 #3) and the `Stop`-hook decision
flow itself (Branch C of stop.py) are SEPARATE concerns built later, after
the 3-way shared-substrate seam review with Rachel + María.
"""
import os
import json
import datetime
from pathlib import Path


# Public interface constants — §0 decision #7 + 6929f4ac §9.2
HOLD_FILENAME_TEMPLATE = ".heartbeat-hold-{session_id}.json"
HOLD_SCHEMA_FIELDS     = ( "session_id", "persona", "held_at", "ttl_seconds",
                           "work_owed", "reason", "awaiting",
                           "pending_user_gates", "last_looked_in_on_workers_ts",
                           "last_spinup_check_ts", "last_surfaced_questions_ts" )
DEFAULT_TTL_SECONDS    = 900
AWAITING_NONE          = "none"
HOLD_GLOB              = ".heartbeat-hold-*.json"
# Janitor grace (bug b39562e4 pt2): a hold must be EXPIRED by at least this margin
# BEYOND its own ttl before it is prunable — 6h is far past any plausible live or
# long-single-turn session, so the janitor can never reap a hold still in use.
DEFAULT_PRUNE_GRACE_SECONDS = 21600

# 6929f4ac field names (single-source so readers/writers never drift)
PENDING_USER_GATES_FIELD = "pending_user_gates"
LAST_LOOKED_IN_FIELD     = "last_looked_in_on_workers_ts"

# B1 mtime-anchored freshness (2026-06-27, bug d44b7068) — read-time annotation
# key. The READER (read_hold) stats the resolved hold file and stamps its
# host-real mtime (epoch seconds) into the returned dict under THIS key, so
# is_fresh can anchor the freshness window on when the file was actually written
# (host truth) rather than the agent-supplied `held_at`. Agents have no reliable
# wall-clock, so `held_at` (anchored to a stale past receipt) can make a
# JUST-WRITTEN hold read stale → relentless false re-pokes. The mtime cannot lie
# about when the agent last refreshed its hold. This is an IN-MEMORY annotation
# only — it is NEVER persisted (write_hold writes EXACTLY HOLD_SCHEMA_FIELDS); the
# leading underscore marks it as non-schema. is_fresh falls back to the legacy
# `held_at` path when the annotation is absent (a hand-built hold dict / a
# write_hold return value), preserving back-compat for every existing caller.
HOLD_MTIME_ANNOTATION = "_hold_file_mtime_epoch"

# Proactive-manager debounce clocks (fcb5dbc0, Lane A1) — the per-manager Face A /
# Face B stamps the agent writes after it acts. Persisted in the hold artifact so
# they SURVIVE /clear (the hold file outlives a context reset), exactly like the
# 6929f4ac look-in stamp above. Single-source field names so readers/writers never drift.
LAST_SPINUP_CHECK_FIELD      = "last_spinup_check_ts"
LAST_SURFACED_QUESTIONS_FIELD = "last_surfaced_questions_ts"


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


def _file_mtime( path ):
    """
    Host-real modification time (epoch seconds) of a hold file — the B1 freshness
    anchor (bug d44b7068). Best-effort + degrade-safe: a clean testable seam for
    the stat-failure branch so read_hold need not inline the try/except.

    Requires:
        - path is a pathlib.Path (or any object with a .stat() → st_mtime)

    Ensures:
        - Returns float st_mtime on success
        - Returns None when the file cannot be stat'd (OSError) — read_hold then
          omits the annotation and is_fresh falls back to held_at
        - Never raises
    """
    try:
        return path.stat().st_mtime
    except OSError:
        return None


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
                held_at=None, base_dir=None,
                pending_user_gates=None, last_looked_in_on_workers_ts=None,
                last_spinup_check_ts=None, last_surfaced_questions_ts=None ):
    """
    Write (atomically) this session's hold artifact and return the dict.

    Requires:
        - session_id is a non-empty string
        - persona and reason are strings
        - work_owed is a bool
        - ttl_seconds is a positive int
        - awaiting is a string (see schema)
        - pending_user_gates is a list of gate-row dicts or None (⇒ [])
        - last_looked_in_on_workers_ts is an ISO-8601 string or None
        - last_spinup_check_ts / last_surfaced_questions_ts are ISO-8601 strings
          or None (the Face A / Face B proactive-manager debounce stamps, A1)

    Ensures:
        - Writes <base_dir>/.heartbeat-hold-<session_id>.json with EXACTLY
          the HOLD_SCHEMA_FIELDS fields, in order (incl. the two 6929f4ac fields
          AND the two A1 proactive-manager debounce fields)
        - pending_user_gates defaults to [] (no open gates) when not supplied;
          last_looked_in_on_workers_ts / last_spinup_check_ts /
          last_surfaced_questions_ts default to None (never run)
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
        "session_id"                   : session_id,
        "persona"                      : persona,
        "held_at"                      : held_at,
        "ttl_seconds"                  : ttl_seconds,
        "work_owed"                    : work_owed,
        "reason"                       : reason,
        "awaiting"                     : awaiting,
        "pending_user_gates"           : list( pending_user_gates ) if pending_user_gates else [ ],
        "last_looked_in_on_workers_ts" : last_looked_in_on_workers_ts,
        "last_spinup_check_ts"         : last_spinup_check_ts,
        "last_surfaced_questions_ts"   : last_surfaced_questions_ts,
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
        - Stamps the resolved file's host-real mtime (epoch seconds) into the
          returned dict under HOLD_MTIME_ANNOTATION so is_fresh can anchor
          freshness on when the hold was actually written, not the agent-supplied
          held_at (B1, bug d44b7068). The stamp is best-effort: a stat failure
          simply omits it (is_fresh then falls back to the held_at path)
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
    # B1 — annotate with the host-real file mtime (the freshness anchor). The
    # write path persists only HOLD_SCHEMA_FIELDS, so this in-memory key never
    # round-trips to disk. Best-effort: a stat failure leaves it absent.
    mtime = _file_mtime( path )
    if mtime is not None:
        data[ HOLD_MTIME_ANNOTATION ] = mtime
    return data


def read_hold_resilient( session_id, cwd=None ):
    """
    Read this session's hold, searching EVERY directory it could plausibly live
    in, so a written honored hold is found regardless of the reading session's cwd.

    Why this exists (bug 1789f197): `write_hold` defaults `base_dir=None` →
    `cu.get_project_root()` (LUPIN_ROOT), but the Stop hook historically resolved
    the read directory from the session's own `cwd` (resolve_hold_base_dir, facet
    3). When a session's cwd is NOT the project root — e.g. a worker operating
    from a git worktree — the hold was WRITTEN under the project root but READ
    under the worktree → never found → the session was re-poked forever despite a
    fresh, honored hold. Searching both candidate roots closes that gap while
    preserving the per-session (cwd-first) preference facet 3 introduced.

    Requires:
        - session_id is a string
        - cwd is the Stop-hook payload's cwd (path-like / string / None)

    Ensures:
        - Returns the first hold found across the ordered, de-duplicated candidate
          dirs [ resolve_hold_base_dir( cwd ), project-root ] — cwd first so a
          genuine per-session hold wins, then the project-root where write_hold
          defaults (the two collapse to one when cwd IS the project root)
        - Returns None when no candidate dir holds a readable hold
        - Never raises (delegates to read_hold, which swallows all errors)
    """
    candidates = []
    seen       = set()
    for base in ( resolve_hold_base_dir( cwd ), _resolve_base_dir( None ) ):
        key = str( base )
        if key in seen:
            continue
        seen.add( key )
        candidates.append( base )
    for base in candidates:
        hold = read_hold( session_id, base_dir=base )
        if hold is not None:
            return hold
    return None


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


def prune_stale_hold_files( base_dir=None, now=None,
                            grace_seconds=DEFAULT_PRUNE_GRACE_SECONDS,
                            live_session_ids=None ):
    """
    Reclaim hold artifacts that have been EXPIRED far longer than any plausible
    live session — the accumulating `.heartbeat-hold-*.json` cruft in the project
    root (bug b39562e4 pt2 — the arbiter-side janitor seam).

    A file is PRUNABLE iff ALL of:
      - its session_id is NOT in `live_session_ids` (belt-and-suspenders: never
        reap a currently-live session's hold even if its clock looks ancient), AND
      - its held_at parses AND its age has passed the applicable threshold:
          * NO authoritative live-set (`live_session_ids` is None) → the
            CONSERVATIVE threshold `ttl_seconds + grace_seconds` (expired beyond
            the generous grace window — a live or long-single-turn session
            refreshes well inside this, so it is never at risk).
          * an AUTHORITATIVE live-set was provided AND this hold carries a real
            session_id ABSENT from it → POSITIVE-dead reading: prune as soon as
            its own `ttl_seconds` has expired (NO +grace). This is the ping-storm
            Fix 1 belt-and-suspenders (2026-06-24): an UNGRACEFUL death (crash /
            /exit / tmux-kill) bypasses the reap-time hold-clear, leaving an orphan
            hold the arbiter re-derives phantom edges from for TTL+6h — far too
            long. Knowing the session is dead lets the janitor reclaim it at TTL.

    BIAS-TO-KEEP — the +grace shortcut is dropped ONLY on a POSITIVE dead reading
    (authoritative live-set provided AND session_id present AND absent from it). A
    LIVE session can carry a stale hold, so an absent authoritative set or a hold
    with no session_id keeps the conservative TTL+grace threshold. The CALLER is
    responsible for passing a non-None `live_session_ids` ONLY when it has genuinely
    enumerated live sessions — passing None (the default) keeps the legacy behavior.

    CONSERVATIVE BY CONSTRUCTION — a file that is unreadable, non-JSON, not a
    dict, missing/unparseable held_at, or carrying a non-numeric ttl is KEPT: the
    janitor only ever deletes a hold it can PROVE is ancient.

    Requires:
        - base_dir is path-like / str / None; now is an aware datetime or None;
          grace_seconds >= 0; live_session_ids is an iterable of session-id
          strings (AUTHORITATIVE live-set) or None (no authoritative set)

    Ensures:
        - deletes only provably-stale hold files (conservative TTL+grace, OR TTL on
          a positive-dead reading); returns the sorted list of pruned paths (strings)
        - never raises (a per-file OSError / JSON error skips that file)
    """
    if now is None:
        now = _now()
    authoritative = live_session_ids is not None           # a positive-dead source was supplied
    live   = set( live_session_ids or ( ) )
    base   = _resolve_base_dir( base_dir )
    pruned = [ ]
    try:
        candidates = sorted( base.glob( HOLD_GLOB ) )
    except OSError:
        return pruned
    for path in candidates:
        try:
            hold = json.loads( path.read_text() )
        except ( OSError, ValueError ):
            continue                                       # unreadable/garbage → KEEP
        if not isinstance( hold, dict ):
            continue
        sid = hold.get( "session_id" )
        if sid in live:
            continue                                       # live session → never reap
        held_dt = _parse_iso( hold.get( "held_at" ) )
        ttl     = hold.get( "ttl_seconds" )
        if held_dt is None or isinstance( ttl, bool ) or not isinstance( ttl, ( int, float ) ):
            continue                                       # can't prove age → KEEP
        # POSITIVE-dead reading (authoritative live-set + a real session_id absent
        # from it) drops the +grace shortcut → prune at TTL; else stay conservative.
        threshold = ttl if ( authoritative and sid ) else ttl + grace_seconds
        if ( now - held_dt ).total_seconds() >= threshold:
            try:
                path.unlink()
                pruned.append( str( path ) )
            except OSError:
                pass                                       # racing delete → fine
    return pruned


def is_fresh( hold, now=None ):
    """
    Is this hold still within its freshness window?

    B1 mtime-anchoring (2026-06-27, bug d44b7068): the freshness window is
    measured from the hold FILE's host-real mtime (the HOLD_MTIME_ANNOTATION the
    reader stamps) when present, NOT the agent-supplied `held_at`. Agents have no
    reliable wall-clock — the no-reliable-clock rule forces anchoring `held_at` to
    a stale past receipt, so a JUST-WRITTEN hold could read stale and the session
    was re-poked forever despite a fresh hold. The host's mtime cannot lie about
    when the agent last refreshed its hold. `held_at` remains the fallback anchor
    for a hold dict carrying no mtime annotation (a hand-built dict, a write_hold
    return value, or a stat failure) — preserving every existing caller's behavior.

    Requires:
        - hold is a dict or None
        - now is an aware datetime or None (defaults to current UTC)

    Ensures:
        - Returns False for a missing hold or a non-numeric ttl_seconds (bool is
          explicitly rejected)
        - When the hold carries a numeric HOLD_MTIME_ANNOTATION: returns
          (now - mtime) < ttl_seconds — the host-real freshness rule (B1)
        - Otherwise (no usable mtime): returns (now - held_at) < ttl_seconds for a
          parseable held_at; False when held_at is absent/unparseable (legacy rule)
        - Never raises
    """
    if not hold:
        return False
    ttl = hold.get( "ttl_seconds" )
    if isinstance( ttl, bool ) or not isinstance( ttl, ( int, float ) ):
        return False
    if now is None:
        now = _now()

    # B1 — prefer the host-real file mtime (when the reader stamped one) over the
    # agent's unreliable held_at. bool is rejected (True must not read as 1.0).
    mtime = hold.get( HOLD_MTIME_ANNOTATION )
    if not isinstance( mtime, bool ) and isinstance( mtime, ( int, float ) ):
        elapsed_seconds = now.timestamp() - mtime
        return elapsed_seconds < ttl

    # Legacy fallback — no mtime annotation: anchor on the supplied held_at.
    held_dt = _parse_iso( hold.get( "held_at" ) )
    if held_dt is None:
        return False
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


def get_pending_user_gates( hold ):
    """
    The hold's structured pending-user-gate rows (6929f4ac §9.2 outward twin).

    Requires:
        - hold is a dict or None

    Ensures:
        - Returns the list value of hold["pending_user_gates"] when it is a list
        - Returns [] when there is no hold, the field is absent, or it is non-list
          (a pre-6929f4ac hold has no gates ⇒ [] ⇒ outward twin silent)
        - Never raises
    """
    if not hold:
        return [ ]
    value = hold.get( PENDING_USER_GATES_FIELD )
    return value if isinstance( value, list ) else [ ]


def get_last_looked_in_ts( hold ):
    """
    The MANAGER's most-recent worker-verification look-in stamp (6929f4ac §3-§5).

    The inward-twin debounce clock: the IO shell feeds this to
    manager_needs_verification. A pre-6929f4ac hold (or one that never looked in)
    yields None ⇒ a manager with workers out reads as owing a first look-in.

    Requires:
        - hold is a dict or None

    Ensures:
        - Returns the str value of hold["last_looked_in_on_workers_ts"] when present
        - Returns None when there is no hold, the field is absent, or it is non-str
        - Never raises
    """
    if not hold:
        return None
    value = hold.get( LAST_LOOKED_IN_FIELD )
    return value if isinstance( value, str ) else None


def get_last_spinup_check_ts( hold ):
    """
    The MANAGER's most-recent spin-up-check stamp (Face A, fcb5dbc0 A1).

    The Face A debounce clock: the IO shell feeds this to
    manager_needs_spinup_check. A hold without the field (pre-A1, or a manager
    that never ran the check) yields None ⇒ a manager with a backlog + idle
    capacity reads as owing a first spin-up nudge.

    Requires:
        - hold is a dict or None

    Ensures:
        - Returns the str value of hold["last_spinup_check_ts"] when present
        - Returns None when there is no hold, the field is absent, or it is non-str
        - Never raises
    """
    if not hold:
        return None
    value = hold.get( LAST_SPINUP_CHECK_FIELD )
    return value if isinstance( value, str ) else None


def get_last_surfaced_questions_ts( hold ):
    """
    The session's most-recent operator-gate re-surface stamp (Face B, fcb5dbc0 A1).

    The Face B debounce clock: the IO shell feeds this to
    manager_needs_question_surface. A hold without the field (pre-A1, or a session
    that never re-surfaced) yields None ⇒ a session holding an open operator gate
    reads as owing a first re-surface.

    Requires:
        - hold is a dict or None

    Ensures:
        - Returns the str value of hold["last_surfaced_questions_ts"] when present
        - Returns None when there is no hold, the field is absent, or it is non-str
        - Never raises
    """
    if not hold:
        return None
    value = hold.get( LAST_SURFACED_QUESTIONS_FIELD )
    return value if isinstance( value, str ) else None


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
        gate = { "id": "g1", "answered": False }
        write_hold( sid, "Tiffany 💍", "holding on the 3-way seam review",
                    work_owed=True, ttl_seconds=900, awaiting="peer:Rachel", base_dir=tmp,
                    pending_user_gates=[ gate ], last_looked_in_on_workers_ts="2026-06-22T12:00:00+00:00",
                    last_spinup_check_ts="2026-06-23T10:00:00+00:00",
                    last_surfaced_questions_ts="2026-06-23T11:00:00+00:00" )
        hold = read_hold( sid, base_dir=tmp )
        assert hold is not None,                      "round-trip read failed"
        # Schema check excludes the `_`-prefixed read-time mtime annotation (B1) —
        # only the persisted (non-underscore) fields define the schema.
        persisted = tuple( k for k in hold.keys() if not k.startswith( "_" ) )
        assert persisted == HOLD_SCHEMA_FIELDS,       "schema field set/order drift"
        assert HOLD_MTIME_ANNOTATION in hold,         "reader must stamp the mtime annotation (B1)"
        assert is_fresh( hold ),                      "fresh hold reported stale"
        assert is_honored( hold ),                    "reasoned fresh hold not honored"
        assert declared_work_owed( hold ) is True,    "work_owed not read back"
        assert get_pending_user_gates( hold ) == [ gate ], "gates not read back"
        assert get_last_looked_in_ts( hold ) == "2026-06-22T12:00:00+00:00", "look-in ts not read back"
        assert get_last_spinup_check_ts( hold ) == "2026-06-23T10:00:00+00:00", "spinup ts not read back"
        assert get_last_surfaced_questions_ts( hold ) == "2026-06-23T11:00:00+00:00", "surface ts not read back"
        # Defaults: a hold written without the 6929f4ac / A1 fields → [] / None
        write_hold( sid, "Tiffany 💍", "plain hold", base_dir=tmp )
        plain = read_hold( sid, base_dir=tmp )
        assert get_pending_user_gates( plain ) == [ ] and get_last_looked_in_ts( plain ) is None
        assert get_last_spinup_check_ts( plain ) is None and get_last_surfaced_questions_ts( plain ) is None

        # B1 — a hold with an ANCIENT held_at but a FRESH file mtime is HONORED:
        # the host-real mtime is the freshness anchor, immune to the agent's
        # unreliable clock (the core d44b7068 repro). Reading right after the write
        # gives a now-ish mtime regardless of the 10000s-old held_at.
        ancient = ( _now() - datetime.timedelta( seconds=10_000 ) ).isoformat( timespec="seconds" )
        write_hold( sid, "Tiffany 💍", "stale held_at, fresh file", ttl_seconds=900,
                    held_at=ancient, base_dir=tmp )
        assert is_honored( read_hold( sid, base_dir=tmp ) ), \
            "fresh-mtime hold with old held_at must be honored (B1)"

        # Expired hold → not honored: drive expiry via the FILE mtime (host truth),
        # not held_at — push the mtime well past the ttl into the past.
        stale_path = hold_path( sid, base_dir=tmp )
        old_epoch  = ( _now() - datetime.timedelta( seconds=10_000 ) ).timestamp()
        os.utime( stale_path, ( old_epoch, old_epoch ) )
        assert not is_honored( read_hold( sid, base_dir=tmp ) ), "mtime-expired hold still honored"

        # Legacy fallback — a hold dict with NO mtime annotation anchors on held_at:
        # old held_at ⇒ stale, recent held_at ⇒ fresh (back-compat preserved).
        assert not is_fresh( { "held_at": ancient, "ttl_seconds": 900, "reason": "x" } ), \
            "legacy held_at fallback must still expire"
        assert is_fresh( { "held_at": _now().isoformat(), "ttl_seconds": 900, "reason": "x" } ), \
            "legacy held_at fallback must read fresh when recent"

        # Cleared hold → absent
        clear_hold( sid, base_dir=tmp )
        assert read_hold( sid, base_dir=tmp ) is None, "clear_hold did not remove file"

    return True


if __name__ == "__main__":   # pragma: no cover - manual smoke entrypoint
    ok = quick_smoke_test()
    print( f"heartbeat_hold smoke: {'PASS' if ok else 'FAIL'}" )
