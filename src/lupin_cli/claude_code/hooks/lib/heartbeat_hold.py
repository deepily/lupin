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
    awaiting    : str   — "user:<name>" / "peer:<persona>" / "commons:<topic>" /
                          "cadence:<what>" / "none".
                          "cadence:<what>" (task c7ae9033, 2026-07-02) = an
                          OBSERVATION/TIMER cadence: work owed, but NOBODY owes
                          this session anything — it re-polls at its own TTL
                          (e.g. "cadence:observation-ttl" for a steward
                          drift-watch). Use it INSTEAD of a "peer:" label when
                          no peer owes you a deliverable: only "peer:" strings
                          mint arbiter blocking edges (dependency_graph
                          _parse_peer_target), so a cadence hold is
                          WAITING-BY-DESIGN by construction — never read as
                          BLOCKED, never chased.
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
import subprocess
from fnmatch import fnmatch
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

# Multi-root sweep (2026-07-16). The janitor was called with NO base_dir → it
# resolved to LUPIN_ROOT and swept exactly ONE directory, non-recursively, while
# holds land wherever a session's cwd happened to be (measured: 7 distinct dirs
# across 3 project trees, incl. lupin/src/migrations/versions/). The sweep now
# accepts a ROOT LIST — supplied by the CALLER, never looked up here: where the
# fleet's roots come from is an OPEN design question and this module must not
# manufacture an answer (a config-derived list resolves to CONTAINER paths that
# do not exist on the host, where the arbiter actually runs).
DEFAULT_SWEEP_MAX_DEPTH = 4
SWEEP_SKIP_DIR_NAMES    = ( ".venv", "node_modules", ".git", "__pycache__" )

# Classification vocabulary (report mode). The verdict is what the janitor WOULD
# do; the reason is WHY — a kept file always says which guard kept it, so an empty
# prune list is never mistaken for an unexamined one.
VERDICT_PRUNABLE          = "prunable"
VERDICT_KEEP              = "keep"
KEEP_UNREADABLE           = "unreadable"
KEEP_NOT_AN_OBJECT        = "not_an_object"
KEEP_LIVE_SESSION         = "live_session"
KEEP_NO_PROVABLE_AGE      = "no_provable_age"
KEEP_WITHIN_THRESHOLD     = "within_threshold"
KEEP_CARGO_BEARING        = "cargo_bearing"
# Store row 8670731d. The two anchors are no longer merely REPORTED against each
# other — where they disagree, the file is KEPT. Prune requires BOTH clocks to call
# it ancient. See classify_hold_file for why the guard sits ahead of the cargo guard.
KEEP_ANCHOR_DISAGREEMENT  = "anchor_disagreement"

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


DATA_DIR_ENV      = "DEEPILY_DATA_DIR"
DATA_DIR_FALLBACK = "projects-data"          # sibling of the projects tree — Rick, 2026-07-26


def _main_repo_path( repo_root ):
    """
    The MAIN repo's absolute directory for a tree — a worktree resolves to its
    parent checkout, a normal checkout to itself.

    Requires:
        - repo_root is a path-like

    Ensures:
        - returns an absolute Path; falls back to the resolved repo_root when git
          is unavailable or the path is not a repo
        - never raises

    ⚠️ Both the identity AND the fallback base must derive from THIS, not from the
    passed tree. Deriving the base from a worktree path yields
    `.claude/projects-data/...` — measured, and the first version of this did it.
    """
    try:
        out = subprocess.run(
            [ "git", "-C", str( repo_root ), "rev-parse", "--path-format=absolute", "--git-common-dir" ],
            capture_output=True, text=True, timeout=10
        )
        common = out.stdout.strip()
        if out.returncode == 0 and common:
            return Path( common ).parent               # <repo>/.git -> <repo>
    except ( OSError, subprocess.SubprocessError ):
        pass                                           # git missing / not a repo
    return Path( repo_root ).resolve()


def _repo_identity( repo_root ):
    """
    The REPO a tree belongs to — the fleet-global key for its runtime data.

    Fleet-global means one data dir per REPO, shared by every worktree of it, so
    the key must be repo identity and not tree identity: `--git-common-dir`
    resolves a worktree to its main repo where a basename resolves it to itself.

    ⚠️ `--git-common-dir` returns a RELATIVE `.git` from the main checkout, which
    naively compared collides every repo into one identity. `--path-format=absolute`
    is not optional.

    ⚠️ AND THIS IS NOT THE PREDICATE THE SWEEP USES. `_compute_hold_roots` dedupes
    on REALPATH, ruled 2026-07-16, because a worktree and its main repo are
    different directories holding different FILES — deduping sweep roots on repo
    identity would drop a worktree root. Both rules stand; they answer different
    questions (Rick confirmed 2026-07-26). Do not "unify" them.

    Requires:
        - repo_root is a path-like pointing inside a git tree (or not)

    Ensures:
        - returns the main repo's directory name; falls back to the basename of
          repo_root when git is unavailable or the path is not a repo
        - never raises
    """
    return _main_repo_path( repo_root ).name


def fleet_data_root( repo_root=None ):
    """
    The fleet-global runtime-data directory for this repo — row 8758d0b1 / f56fc63b.

    Runtime state (hold files, DM-inbox bookmarks, acked ledgers, task-store maps)
    moved OUT of the repo root, because a gitignored path inside the tree is on
    `git clean -xdf`'s kill list, not shielded by it: measured 2026-07-26, a dry
    run listed 448 runtime files as "would remove", including cargo-bearing holds.

    Ensures:
        - returns <DEEPILY_DATA_DIR>/<repo-name>
        - falls back to <projects-parent>/projects-data/<repo-name> when the env
          var is unset. NOT a silent degradation to the repo root — that would
          recreate the clutter this exists to remove. It is the SAME location the
          env var names, derived rather than read, so a long-lived session whose
          environment predates the variable still writes where everyone else reads.
        - never raises
    """
    import cosa.utils.util as cu
    root = Path( repo_root ) if repo_root is not None else Path( cu.get_project_root() )
    main = _main_repo_path( root )                     # a worktree resolves to its parent checkout
    base = os.environ.get( DATA_DIR_ENV ) or str( main.parent.parent / DATA_DIR_FALLBACK )
    return Path( base ) / main.name


def hold_correct_zone( swept_roots=None ):
    """
    The directory tree a correctly-placed hold MUST live under — the fleet data
    root's PARENT (the shared `projects-data` dir), so a hold at
    <projects-data>/<any-repo>/.heartbeat-hold-*.json is CORRECT and one at a repo
    root or inside a worktree is NOT.

    Requires:
        - swept_roots is None or an iterable of the roots the sweep will scan (the
          arbiter passes report_hold_files's roots_swept); None runs the floor only

    Ensures:
        - returns fleet_data_root().parent, resolved
        - returns None if the root cannot be resolved — a resolution failure must
          NOT make the sweep raise; the caller treats None as "cannot judge"
        - FAIL-CLOSED, floor (row 011f1f90, Rachel/Mr Radio 2026-08-06): a zone at
          the filesystem root ("/") is an ancestor of EVERY path, so
          hold_is_misplaced would return False for everything and the detector would
          go permanently silent WHILE LOOKING HEALTHY. A zone with fewer than 2 path
          parts returns None. Cheap, but only catches "/".
        - FAIL-CLOSED, STRUCTURAL (Mr Radio's ruling 2026-08-06 — structural over a
          magic number): the zone is TOO BROAD if any swept REPO ROOT sits UNDER it
          (e.g. DEEPILY_DATA_DIR=/mnt → zone "/mnt" is an ancestor of the repo roots
          at /mnt/DATA01/.../<repo>, which the parts-count floor cannot catch). When
          `swept_roots` is provided and any of them is under the zone, returns None —
          EXCLUDING fleet_data_root's OWN subtree, which legitimately lives under the
          zone (it is where correct holds go). Today's deep root passes both checks;
          this makes the /mnt-class failure impossible rather than merely improbable.
    """
    try:
        fdr = fleet_data_root().resolve()
    except Exception:
        return None
    zone = fdr.parent
    if len( zone.parts ) < 2:
        return None
    if swept_roots:
        for root in swept_roots:
            try:
                rp = Path( root ).resolve()
            except Exception:
                continue
            # a swept root UNDER the zone that is NOT fleet_data_root or its subtree
            # ⇒ the zone spans real repo roots ⇒ too broad to judge misplacement.
            if zone in rp.parents and rp != fdr and fdr not in rp.parents:
                return None
    return zone


def hold_is_misplaced( path, correct_zone ):
    """
    Is this hold file OUTSIDE the fleet data root (row 011f1f90)? A repo-root or
    worktree hold reads True.

    This is the LOCATION signal the arbiter's resilient read now HIDES: teaching
    the veto to read a repo-root hold makes a misplaced hold FUNCTION, so the only
    symptom anyone noticed (the relentless poke) disappears. The sweep must still
    surface the file as misplaced or the leak goes silent — hence location is a
    first-class field, not folded into cargo_bearing (Mr Radio, 2026-08-06).

    Ensures:
        - True iff `correct_zone` is NOT an ancestor of `path`
        - fail-safe: an unresolved zone (None) or an unresolvable path returns
          False — the detector never OVER-flags a hold it cannot place
    """
    if correct_zone is None:
        return False
    try:
        return correct_zone not in Path( path ).resolve().parents
    except Exception:
        return False


def _resolve_base_dir( base_dir ):
    """
    Resolve the directory that holds the runtime-state families.

    Requires:
        - base_dir is a path-like, a string, or None

    Ensures:
        - Returns a Path
        - base_dir provided  → Path( base_dir )  (tests + explicit callers win)
        - base_dir is None   → the FLEET DATA ROOT, not the project root
          (PATH MANAGEMENT mandate — never __file__ chains)
        - creates the directory if absent: every caller of this either writes into
          it or globs it, and a missing dir would surface as "no files" — the
          silent-empty reading this whole family keeps being bitten by
    """
    if base_dir is not None:
        return Path( base_dir )
    root = fleet_data_root()
    try:
        root.mkdir( parents=True, exist_ok=True )
    except OSError:
        pass                                           # unwritable → callers fail loudly on use
    return root


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
        - ValueError if ttl_seconds is not a positive, non-bool number — the
          "Requires: ttl_seconds is a positive int" contract above was prose
          enforced by NOTHING: `write_hold( ttl_seconds=None )` emitted a null
          ttl straight to disk while its SIBLING defaults were normalized
          (held_at=None → _now(), pending_user_gates=None → []). An unusable ttl
          makes is_fresh False ⇒ is_honored False ⇒ the session is poked forever
          despite having declared a hold. Fail at the write, loudly, rather than
          mint a hold that silently cannot defend anything.
        - ValueError if reason is empty or whitespace-only — the SECOND prose
          contract this function enforced with nothing, found by adversarial
          review (Rio ⚡, 2026-07-21, row 3ebc6c3d finding A-1) and reproduced
          both ways. `is_honored` requires a non-empty reason, so an empty one
          lands a hold that declares quiescence and defends nothing: EXACTLY the
          22-file corpus this milestone exists to stop minting. Worse on a
          REFRESH — measured, before/after: a live hold (`honored=True`,
          reason='holding on the seam review', ttl 14400) was OVERWRITTEN by an
          empty-reason write and came back `honored=False`, costing a running
          session the defense it already had and restoring the ping-storm the
          row's OUT-OF-SCOPE section names by name.

          THE GUARD IS THE EXACT COMPLEMENT OF `is_honored`'s PREDICATE
          (`bool( reason and str( reason ).strip() )`), deliberately and not
          incidentally. A guard that rejected only `""` would let `"   "`
          through — whitespace passes the writer, fails the reader, and mints
          the same unhonorable hold through a narrower door. Two checks on one
          property must agree on the property, or the stricter one is just a
          smaller version of the hole.
        - OSError if the target directory is not writable / does not exist

    BOTH RAISES PRECEDE EVERY FILESYSTEM TOUCH, and that ordering is load-bearing
    rather than tidy: a refused write must leave a PRE-EXISTING hold exactly as it
    found it. Validating after `os.replace` would make every refusal destructive
    for the one caller who needed the old hold most — the live session refreshing
    the hold that is currently defending it.
    """
    if not ( reason and str( reason ).strip() ):
        raise ValueError(
            f"reason must be a non-empty, non-whitespace string, got {reason!r} — is_honored "
            f"requires a reason, so a hold without one declares quiescence and defends "
            f"nothing: it is never honored, and the session it was written to defend gets "
            f"poked anyway."
        )
    if isinstance( ttl_seconds, bool ) or not isinstance( ttl_seconds, ( int, float ) ):
        raise ValueError(
            f"ttl_seconds must be a positive number, got {ttl_seconds!r} — a hold with an "
            f"unusable ttl is never fresh, so it is never honored, so the session it was "
            f"written to defend gets poked anyway."
        )
    if ttl_seconds <= 0:
        raise ValueError(
            f"ttl_seconds must be POSITIVE, got {ttl_seconds!r} — a non-positive freshness "
            f"window expires the hold the instant it is written."
        )

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


def read_hold_exact( session_id, base_dir=None ):
    """
    Read ONLY this session id's own hold file — no prefix fallback, ever.

    FOR GUARDS THAT PROTECT A WRITE OR A DELETE (bug 8abdcbbf). `read_hold` is
    deliberately prefix-tolerant so a hold written under the short bridge id is
    still FOUND by a hook reading the full stable id — correct for a READ, where
    resolving to the wrong file costs at worst a missed poke. It is the wrong
    reader for a guard, because `write_hold`/`clear_hold` act on the EXACT path:
    a guard that resolves prefix-tolerantly vouches for (or objects to) a file
    its action will never touch. That split is what let the cargo guard refuse a
    session its hold over cargo living in a DIFFERENT file — possibly another
    session's — at exit 6, against a path that did not exist.

    ⇒ Use this wherever the question is "what is in the file I am about to
    replace or delete"; use `read_hold` where the question is "does this session
    have a hold anywhere".

    Requires:
        - session_id is a string
        - base_dir is a path-like / string / None

    Ensures:
        - Returns the hold dict at EXACTLY <base_dir>/.heartbeat-hold-<id>.json
        - Returns None when that path is absent, unreadable, malformed, or parses
          to a non-object — a prefix sibling is NEVER consulted
        - Carries no mtime annotation: freshness is a question about a resolved
          hold, and this reader deliberately resolves nothing
        - Never raises
    """
    path = hold_path( session_id, base_dir=base_dir )
    try:
        if not path.exists():
            return None
        data = json.loads( path.read_text() )
    except ( OSError, ValueError ):
        return None
    return data if isinstance( data, dict ) else None


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


def read_hold_via_bridge( session_id, log_fn=None ):
    """
    Resilient hold read for a caller that holds NO per-session cwd of its own —
    the ARBITER (row 011f1f90). It sources the session's OWN cwd from its bridge
    snapshot (SessionStart `cwd`, written once and stable for the session), then
    delegates to read_hold_resilient so a hold written to ANY repo root — not just
    LUPIN_ROOT — is found.

    Why the arbiter needs this: read_hold (base_dir=None) resolves fleet_data_root
    ONLY, so a hold that leaked to a repo root is invisible to the arbiter's
    honored-hold VETO → the session is parked but keeps getting poked (the row's
    correctness bug). read_hold_resilient closes it, but its cwd param is the
    session's own working dir, which the arbiter does not carry per session; the
    bridge does.

    Requires:
        - session_id is a string
        - log_fn is None or a callable ( event_name, **fields ) — the arbiter's
          journal fn, injected so the fallback below is VISIBLE

    Ensures:
        - Returns read_hold_resilient( session_id, cwd=<bridge cwd> ) — the bridge
          cwd catches a repo-root hold in ANY project (planning-is-prompting,
          worktrees), closing both gaps a bare cwd=None would strand
        - A MISSING or unreadable bridge degrades to cwd=None, NOT a crash:
          find_session_by_id returns None on a miss, so the guard `( … or {} )`
          keeps this from AttributeError-ing (Rachel's must-fix) and cwd=None still
          searches LUPIN_ROOT + fleet_data_root — a bridge-less session (dead-PID
          prune, id-form mismatch) never regresses to the blind fleet-only read
        - WHENEVER cwd resolves to None (no_bridge / bridge_without_cwd /
          bridge_error) AND log_fn is provided, emits ONE
          `arbiter_hold_reader_cwd_fallback` line with session_id + reason. A
          SILENT degrade to cwd=None would restore the blind path invisibly
          (Rachel/Mr Radio 2026-08-06) — so a future bridge regression that puts
          the arbiter back to poking parked sessions is visible in the journal. The
          cwd-PRESENT path never logs (no per-tick noise).
        - Never raises (any bridge-resolution failure → cwd=None; the delegate
          read_hold_resilient swallows its own IO errors)
    """
    cwd    = None
    reason = None
    try:
        # Lazy import: session_bridge does NOT import this module, so there is no
        # cycle at module load — but keep it local so a hold read never depends on
        # the bridge module importing cleanly.
        from lupin_cli.claude_code.hooks.lib.session_bridge import find_session_by_id
        bridge = find_session_by_id( session_id )
        if bridge is None:
            reason = "no_bridge"
        else:
            cwd = bridge.get( "cwd" )
            if not cwd:
                cwd, reason = None, "bridge_without_cwd"
    except Exception:
        cwd, reason = None, "bridge_error"
    if cwd is None and log_fn is not None:
        log_fn( "arbiter_hold_reader_cwd_fallback", session_id=session_id, reason=reason )
    return read_hold_resilient( session_id, cwd=cwd )


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


def ttl_is_usable( hold ):
    """
    Can this hold's `ttl_seconds` actually anchor a freshness window?

    The single discriminator behind BOTH loud paths: is_fresh returns False for an
    unusable ttl (⇒ is_honored False ⇒ the session is poked despite its hold), and
    the janitor refuses to age a file it cannot prove old. Measured on the live
    corpus: 22 files carry NO ttl key at all and ZERO carry a literal null — so any
    check written as `hold.get("ttl_seconds") is None` cannot tell "absent" from
    "null" from "present-and-fine", which is exactly how the population was
    mis-diagnosed three times. This helper asks the only question that matters —
    *is it usable* — and is blind to how it got that way.

    Requires:
        - hold is a dict or None

    Ensures:
        - Returns True iff hold["ttl_seconds"] is a non-bool int/float
          (bool is rejected explicitly: True must never read as 1)
        - Returns False for a missing hold / absent key / null / non-numeric
        - Never raises
    """
    if not hold:
        return False
    ttl = hold.get( "ttl_seconds" )
    return not isinstance( ttl, bool ) and isinstance( ttl, ( int, float ) )


def hold_cargo_keys( hold ):
    """
    The NON-schema keys a hold file carries — its "cargo".

    Why this exists: hold files are being hand-written with continuity payload the
    schema has no room for (`note_to_my_successor`,
    `the_lesson_that_should_outlive_this_session`, `board`, `harvest_state`,
    `the_nights_finding`). Those files are MEMENTOS wearing a hold's filename, and
    they are irreplaceable. The janitor must be able to SAY SO before anything is
    ever deleted — a report that cannot distinguish a husk from a memento is not
    evidence, it is a countdown.

    Requires:
        - hold is a dict or None

    Ensures:
        - Returns the sorted list of keys not in HOLD_SCHEMA_FIELDS, excluding
          `_`-prefixed in-memory annotations (HOLD_MTIME_ANNOTATION is stamped by
          the reader and is not cargo)
        - Returns [] for a missing / non-dict hold
        - Never raises
    """
    if not isinstance( hold, dict ):
        return [ ]
    return sorted( k for k in hold
                   if k not in HOLD_SCHEMA_FIELDS and not str( k ).startswith( "_" ) )


def _is_skipped_dir( path, skip_dir_names ):
    """
    Should the recursive sweep refuse to descend into this directory?

    Requires:
        - path is a Path; skip_dir_names is a container of directory names

    Ensures:
        - Returns True for a dir named in skip_dir_names, OR for the
          `.claude/worktrees` tree specifically (a worktree's holds belong to the
          worktree's own lineage, not the main tree's sweep)
        - Never raises
    """
    if path.name in skip_dir_names:
        return True
    return path.name == "worktrees" and path.parent.name == ".claude"


def _probe_dir_for_holds( root, max_depth, glob_pat=None ):
    """
    Count hold files inside a directory the sweep is SKIPPING — depth-bounded.

    A skip-list that silently swallows hold-bearing directories reports "0 found"
    and reads as "nothing there." Measured: a hold lives under
    `lupin/.claude/worktrees/cheech-orphan-bridge`, which the skip-list excludes.
    The sweep still refuses to descend — but it SAYS what it stepped over, so an
    unreachable hold is a visible number instead of a silence.

    Requires:
        - root is a Path; max_depth is a non-negative int
        - glob_pat is an fnmatch pattern, or None for the default HOLD_GLOB

    Ensures:
        - Returns the list of matching Paths found under root within max_depth
        - Never descends into a nested skipped dir; never raises (OSError → [])
    """
    if glob_pat is None: glob_pat = HOLD_GLOB
    found = [ ]
    stack = [ ( root, 0 ) ]
    while stack:
        current, depth = stack.pop()
        try:
            entries = list( os.scandir( current ) )
        except OSError:
            continue                                   # unreadable → nothing to report here
        for entry in entries:
            try:
                is_dir = entry.is_dir( follow_symlinks=False )
            except OSError:
                continue
            if is_dir:
                if depth < max_depth and not _is_skipped_dir( Path( entry.path ), SWEEP_SKIP_DIR_NAMES ):
                    stack.append( ( Path( entry.path ), depth + 1 ) )
            elif fnmatch( entry.name, glob_pat ):
                found.append( Path( entry.path ) )
    return found


def _walk_hold_files( root, max_depth, skip_dir_names, glob_pat=None ):
    """
    Depth-bounded recursive scan of ONE root for hold files.

    Requires:
        - root is a Path; max_depth is a non-negative int; skip_dir_names is a
          container of directory names
        - glob_pat is an fnmatch pattern, or None for the default HOLD_GLOB

    Ensures:
        - Returns ( hold_paths, skipped_dirs ) where skipped_dirs is a list of
          { "dir": str, "hold_count": int } for skip-listed dirs that CONTAIN holds
          (a skipped EMPTY dir is not reported — only a swallowed hold is news)
        - Follows no symlinked directories; a per-directory OSError skips that
          directory only
        - Never raises
    """
    if glob_pat is None: glob_pat = HOLD_GLOB
    found, skipped = [ ], [ ]
    stack = [ ( root, 0 ) ]
    while stack:
        current, depth = stack.pop()
        try:
            entries = list( os.scandir( current ) )
        except OSError:
            continue                                   # unreadable dir → skip it, keep sweeping
        for entry in entries:
            try:
                is_dir = entry.is_dir( follow_symlinks=False )
            except OSError:
                continue
            if is_dir:
                child = Path( entry.path )
                if _is_skipped_dir( child, skip_dir_names ):
                    holds = _probe_dir_for_holds( child, max_depth, glob_pat=glob_pat )
                    if holds:
                        skipped.append( { "dir": str( child ), "hold_count": len( holds ) } )
                elif depth < max_depth:
                    stack.append( ( child, depth + 1 ) )
            elif fnmatch( entry.name, glob_pat ):
                found.append( Path( entry.path ) )
    return found, skipped


def _iter_hold_paths( base_dir=None, base_dirs=None, max_depth=DEFAULT_SWEEP_MAX_DEPTH,
                      skip_dir_names=SWEEP_SKIP_DIR_NAMES, glob_pat=None ):
    """
    Enumerate hold files across one or many roots — the shared sweep front-end.

    Requires:
        - base_dir is path-like / str / None (LEGACY single-root mode)
        - base_dirs is an iterable of path-like roots, or None
        - max_depth is a non-negative int; skip_dir_names is a container of names
        - glob_pat selects the FILE FAMILY to enumerate; None means HOLD_GLOB, so
          every pre-existing caller keeps its exact behavior. The traversal is
          family-agnostic — what a file MEANS is the classifier's business, not
          the walker's, which is why a second runtime-state family can reuse this
          without touching classify_hold_file (row 8758d0b1).

    Ensures:
        - base_dirs is None → LEGACY mode: the single resolved base_dir, glob'd
          NON-recursively, byte-for-byte the pre-multi-root behavior every existing
          caller depends on (a glob OSError yields no paths)
        - base_dirs provided → each root de-duplicated by path, swept RECURSIVELY
          (depth-bounded, skip-listed); a root that is not an existing directory is
          reported in roots_unreachable rather than silently contributing nothing
        - Returns ( roots_swept, roots_unreachable, paths, skipped_dirs ) with paths
          sorted deterministically
        - Never raises
    """
    if glob_pat is None: glob_pat = HOLD_GLOB
    if base_dirs is None:
        base = _resolve_base_dir( base_dir )
        try:
            return [ str( base ) ], [ ], sorted( base.glob( glob_pat ) ), [ ]
        except OSError:
            return [ ], [ { "root": str( base ), "error": "glob_failed" } ], [ ], [ ]

    roots_swept, roots_unreachable, paths, skipped = [ ], [ ], [ ], [ ]
    seen = set()
    for raw in base_dirs:
        root = Path( raw )
        key  = str( root )
        if key in seen:
            continue                                   # same root twice → sweep once
        seen.add( key )
        try:
            reachable = root.is_dir()
        except OSError:
            reachable = False
        if not reachable:
            roots_unreachable.append( { "root": key, "error": "not_a_directory" } )
            continue
        found, skipped_here = _walk_hold_files( root, max_depth, skip_dir_names, glob_pat=glob_pat )
        roots_swept.append( key )
        paths.extend( found )
        skipped.extend( skipped_here )
    return roots_swept, roots_unreachable, sorted( paths ), skipped


def classify_hold_file( path, now=None, grace_seconds=DEFAULT_PRUNE_GRACE_SECONDS,
                        live_session_ids=None, allow_cargo_deletion=False ):
    """
    Decide what the janitor WOULD do with one hold file — and never touch it.

    This is the SINGLE decision rule: `prune_stale_hold_files` acts on this
    verdict, `report_hold_files` only prints it. One rule, two consumers ⇒ the
    report cannot drift from the deletion it is evidence for.

    Requires:
        - path is a Path to a candidate hold file
        - now is an aware datetime or None; grace_seconds >= 0
        - live_session_ids is an iterable of live session-id strings, or None
          (no authoritative live-set — see prune_stale_hold_files' BIAS-TO-KEEP)
        - allow_cargo_deletion is False by DEFAULT — see the CARGO GUARD below

    Ensures:
        - Returns a row dict: path · verdict (VERDICT_PRUNABLE|VERDICT_KEEP) ·
          reason · session_id · persona · ttl_seconds · ttl_usable ·
          held_at_age_seconds · mtime_age_seconds · threshold_seconds ·
          cargo_bearing · cargo_keys · anchor_disagreement
        - CONSERVATIVE BY CONSTRUCTION: unreadable / non-object / live-session /
          unprovable-age / within-threshold / CARGO-BEARING all yield VERDICT_KEEP
          with the reason naming the guard that kept it
        - THE CARGO GUARD (precondition 1 of 11461241; Rio F-A, BINDING): a file
          carrying non-schema cargo can never be PRUNABLE while
          allow_cargo_deletion is False, which is the DEFAULT.

          WHY IT LIVES HERE AND NOT AT THE CALL SITE: A0 — this milestone's origin
          bug — WAS a call-site bug. Cargo was REPORTED by this function and
          PROTECTED by whoever happened to call it, so protection was one forgotten
          argument deep. Rio proved by execution that the real unmodified janitor,
          handed roots alone, deletes 20 files, 10 of them cargo-bearing
          hand-written mementos. The guard belongs where the bug was.

          WHY IT IS OPENABLE AND MUST STAY OPENABLE: triage is COPY-FORWARD, so
          rescued originals KEEP their cargo keys. A permanent cargo guard would
          make those husks unreclaimable forever and defeat Rick's Q4 ("if the
          janitor can't reclaim them, it isn't fixed"). The gated reclamation step
          passes allow_cargo_deletion=True — but only AFTER the triage is verified,
          and it has to say so out loud to do it.

          WHY IT OVERRIDES AT THE PRUNABLE DECISION RATHER THAN ON ENTRY: placing
          it earlier would relabel every cargo file that some OTHER guard already
          kept, and the per-guard tally would stop being able to answer the one
          question the triage needs — how many files WOULD have been deleted but
          for the cargo guard. A `cargo_bearing` reason now means exactly that.
        - anchor_disagreement flags a file the janitor would prune on its `held_at`
          age while the HOOK would still call it fresh on the file's mtime (B1).
          The two readers anchor on different clocks; where they disagree, a hold
          the fleet is actively honoring looks deletable. Reported as DATA, not
          acted on — the deletion path is out of this milestone's scope.
        - Deletes nothing. Never raises.
    """
    if now is None:
        now = _now()
    authoritative = live_session_ids is not None
    live          = set( live_session_ids or ( ) )

    row = {
        "path"                 : str( path ),
        "verdict"              : VERDICT_KEEP,
        "reason"               : KEEP_UNREADABLE,
        "session_id"           : None,
        "persona"              : None,
        "ttl_seconds"          : None,
        "ttl_usable"           : False,
        "held_at_age_seconds"  : None,
        "mtime_age_seconds"    : None,
        "threshold_seconds"    : None,
        "cargo_bearing"        : False,
        "cargo_keys"           : [ ],
        "anchor_disagreement"  : False,
    }

    mtime = _file_mtime( path )
    if mtime is not None:
        row[ "mtime_age_seconds" ] = now.timestamp() - mtime

    try:
        hold = json.loads( path.read_text() )
    except ( OSError, ValueError ):
        return row                                     # unreadable/garbage → KEEP
    if not isinstance( hold, dict ):
        row[ "reason" ] = KEEP_NOT_AN_OBJECT
        return row

    sid                    = hold.get( "session_id" )
    row[ "session_id" ]    = sid
    row[ "persona" ]       = hold.get( "persona" )
    row[ "ttl_seconds" ]   = hold.get( "ttl_seconds" )
    row[ "ttl_usable" ]    = ttl_is_usable( hold )
    row[ "cargo_keys" ]    = hold_cargo_keys( hold )
    row[ "cargo_bearing" ] = bool( row[ "cargo_keys" ] )

    held_dt = _parse_iso( hold.get( "held_at" ) )
    if held_dt is not None:
        row[ "held_at_age_seconds" ] = ( now - held_dt ).total_seconds()

    if sid in live:
        row[ "reason" ] = KEEP_LIVE_SESSION
        return row                                     # live session → never reap
    if held_dt is None or not row[ "ttl_usable" ]:
        row[ "reason" ] = KEEP_NO_PROVABLE_AGE
        return row                                     # can't prove age → KEEP

    ttl                        = hold[ "ttl_seconds" ]
    threshold                  = ttl if ( authoritative and sid ) else ttl + grace_seconds
    row[ "threshold_seconds" ] = threshold
    if row[ "held_at_age_seconds" ] >= threshold:
        mtime_age = row[ "mtime_age_seconds" ]
        # A NEGATIVE mtime age means the file's mtime is in the FUTURE relative to
        # `now` — clock skew, a bad `touch`, a restored backup. That is not evidence
        # of liveness; it is evidence the mtime cannot be read as a clock at all, so
        # it must not count as "fresh". Requiring `mtime_age >= 0` keeps the guard
        # anchored on usable evidence and falls through to the `held_at` decision,
        # which is the only clock left saying anything intelligible.
        #
        # Found by measurement, not foresight: the adversarial suite freezes `now` a
        # month BEFORE its fixtures are written, so every fixture had a future mtime
        # and the first version of this guard kept ALL of them — including the control
        # that proves the janitor can delete at all. A guard that keeps everything is
        # indistinguishable from a janitor pointed at the wrong directory.
        row[ "anchor_disagreement" ] = ( mtime_age is not None
                                         and 0 <= mtime_age < ttl )
        if row[ "anchor_disagreement" ]:
            # TWO-ANCHOR GUARD (store row 8670731d). Pruning now requires BOTH clocks
            # to call the file ancient. Where they disagree, KEEP.
            #
            # This is not a new policy — it is this module's stated bias-to-keep finally
            # applied to the one place that had two clocks and trusted the worse of them.
            # B1 exists BECAUSE `held_at` is agent-written and "agents have no reliable
            # wall-clock"; the janitor then aged on that very field. A live session that
            # refreshes its hold with a stale receipt read HONORED to the hook and
            # PRUNABLE to the janitor, and lost its hold to the janitor.
            #
            # ⚠️ THE GUARD SITS AHEAD OF THE CARGO GUARD, DELIBERATELY, AND IT MOVES A
            # NUMBER. A disagreement is a suspected-LIVENESS signal, and liveness
            # outranks cargo as a reason not to delete — `KEEP_LIVE_SESSION` is already
            # checked before everything. The consequence, stated rather than discovered:
            # a file that is BOTH cargo-bearing and anchor-disagreeing now reports
            # `anchor_disagreement` instead of `cargo_bearing`, so the triage's
            # "how many would have been deleted but for the cargo guard" tally counts
            # only files where cargo was the LAST line of defense. That is the more
            # honest reading of that number, but it is a different one.
            #
            # NOT OPENABLE, unlike the cargo guard, and that asymmetry is on purpose:
            # cargo has a legitimate reclamation step (triage, then delete the husk),
            # whereas "one clock says this session is alive" has no state in which
            # overriding it is correct. If the disagreement is spurious the fix is to
            # stop the anchors diverging, not to add a flag that ignores them.
            row[ "reason" ] = KEEP_ANCHOR_DISAGREEMENT
            return row
        if row[ "cargo_bearing" ] and not allow_cargo_deletion:
            row[ "reason" ] = KEEP_CARGO_BEARING     # verdict stays KEEP — the guard, structurally
            return row
        row[ "verdict" ] = VERDICT_PRUNABLE
        row[ "reason" ]  = VERDICT_PRUNABLE
    else:
        row[ "reason" ] = KEEP_WITHIN_THRESHOLD
    return row


def report_hold_files( base_dir=None, base_dirs=None, now=None,
                       grace_seconds=DEFAULT_PRUNE_GRACE_SECONDS,
                       live_session_ids=None, max_depth=DEFAULT_SWEEP_MAX_DEPTH,
                       skip_dir_names=SWEEP_SKIP_DIR_NAMES,
                       allow_cargo_deletion=False ):
    """
    REACH and CLASSIFY every hold file — and DELETE NOTHING. Ever.

    This function contains no unlink and calls nothing that does. That is
    structural, not a flag: the acceptance test for the widened sweep is that the
    janitor can REACH and CLASSIFY the existing corpus — it is NOT that it can
    delete it. Reclamation is a SEPARATE, gated step that runs only after the
    cargo-bearing files have been triaged, because a hold file's non-schema keys
    are the only copy of a reaped session's continuity record.

    This report is also the NEGATIVE CONTROL on the multi-root sweep itself: a
    janitor pointed at the wrong roots produces an EMPTY report, and an empty
    report is how we learn the root list is wrong. `roots_swept: []` is therefore
    reported distinctly from `prunable: 0` — "I swept nothing" and "I swept
    everything and there was nothing to reap" are opposite facts that a lone zero
    cannot tell apart.

    Requires:
        - base_dir / base_dirs / max_depth / skip_dir_names per _iter_hold_paths
        - now is an aware datetime or None; grace_seconds >= 0
        - live_session_ids is an iterable of live session ids, or None

    Ensures:
        - Returns { roots_requested, roots_swept, roots_unreachable,
                    skipped_dirs_with_holds, files_found, files, counts, deleted }
        - counts carries prunable · keep · cargo_bearing · ttl_unusable ·
          anchor_disagreement · reachable_but_kept_reasons (per-guard tally)
        - deleted is ALWAYS 0 — the field exists so a reader never has to infer it
        - Never raises
    """
    if now is None:
        now = _now()
    roots_requested = [ str( r ) for r in base_dirs ] if base_dirs is not None else None
    roots_swept, roots_unreachable, paths, skipped = _iter_hold_paths(
        base_dir=base_dir, base_dirs=base_dirs, max_depth=max_depth, skip_dir_names=skip_dir_names
    )

    files  = [ classify_hold_file( p, now=now, grace_seconds=grace_seconds,
                                   live_session_ids=live_session_ids,
                                   allow_cargo_deletion=allow_cargo_deletion ) for p in paths ]
    # LOCATION is first-class (row 011f1f90, Mr Radio 2026-08-06): flag every hold
    # that sits OUTSIDE the fleet data root — a repo-root or worktree leak. The
    # arbiter's resilient veto now makes such a hold FUNCTION, hiding the only
    # symptom (the poke), so this is the surviving signal that the file is still in
    # the wrong place. Not folded into cargo_bearing — a misplaced hold and a
    # cargo-bearing one are orthogonal facts.
    correct_zone = hold_correct_zone( swept_roots=roots_swept )
    reasons = { }
    for row in files:
        row[ "misplaced" ] = hold_is_misplaced( row[ "path" ], correct_zone )
        if row[ "verdict" ] == VERDICT_KEEP:
            reasons[ row[ "reason" ] ] = reasons.get( row[ "reason" ], 0 ) + 1

    misplaced_paths = [ r[ "path" ] for r in files if r[ "misplaced" ] ]

    return {
        "roots_requested"         : roots_requested if roots_requested is not None else roots_swept,
        "roots_swept"             : roots_swept,
        "roots_unreachable"       : roots_unreachable,
        "skipped_dirs_with_holds" : skipped,
        "files_found"             : len( files ),
        "files"                   : files,
        # location_zone is None when the zone was UNJUDGEABLE (unresolved / shallow):
        # the caller MUST treat that distinctly from a real "0 misplaced" so a
        # fail-closed zone surfaces loudly instead of as a false all-clear (row 011f1f90).
        "location_zone"           : str( correct_zone ) if correct_zone is not None else None,
        "misplaced_paths"         : misplaced_paths,   # first-class location signal (row 011f1f90)
        "counts"                  : {
            "prunable"                 : sum( 1 for r in files if r[ "verdict" ] == VERDICT_PRUNABLE ),
            "keep"                     : sum( 1 for r in files if r[ "verdict" ] == VERDICT_KEEP ),
            "cargo_bearing"            : sum( 1 for r in files if r[ "cargo_bearing" ] ),
            "ttl_unusable"             : sum( 1 for r in files if not r[ "ttl_usable" ] ),
            "anchor_disagreement"      : sum( 1 for r in files if r[ "anchor_disagreement" ] ),
            "misplaced"                : len( misplaced_paths ),
            "reachable_but_kept_reasons" : reasons,
        },
        "deleted"                 : 0,                 # structural: this path cannot delete
    }


def prune_stale_hold_files( base_dir=None, now=None,
                            grace_seconds=DEFAULT_PRUNE_GRACE_SECONDS,
                            live_session_ids=None, base_dirs=None,
                            max_depth=DEFAULT_SWEEP_MAX_DEPTH,
                            skip_dir_names=SWEEP_SKIP_DIR_NAMES,
                            allow_cargo_deletion=False ):
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

    MULTI-ROOT (2026-07-16): `base_dirs` sweeps a CALLER-SUPPLIED list of roots
    RECURSIVELY (depth-bounded + skip-listed), while `base_dir` alone preserves the
    exact legacy single-root, non-recursive behavior for every existing caller. The
    root list is never derived here — see the module's multi-root note.

    Requires:
        - base_dir is path-like / str / None; now is an aware datetime or None;
          grace_seconds >= 0; live_session_ids is an iterable of session-id
          strings (AUTHORITATIVE live-set) or None (no authoritative set)
        - base_dirs is an iterable of roots (recursive multi-root mode) or None
          (legacy single-root mode); max_depth / skip_dir_names bound the recursion

    Ensures:
        - deletes only provably-stale hold files (conservative TTL+grace, OR TTL on
          a positive-dead reading); returns the sorted list of pruned paths (strings)
        - the KEEP/PRUNE decision is classify_hold_file's — one rule shared with
          report_hold_files, so the dry-run evidence cannot drift from the act
        - never raises (a per-file OSError / JSON error skips that file)
    """
    if now is None:
        now = _now()
    _roots, _unreachable, candidates, _skipped = _iter_hold_paths(
        base_dir=base_dir, base_dirs=base_dirs, max_depth=max_depth, skip_dir_names=skip_dir_names
    )
    pruned = [ ]
    for path in candidates:
        row = classify_hold_file( path, now=now, grace_seconds=grace_seconds,
                                  live_session_ids=live_session_ids,
                                  allow_cargo_deletion=allow_cargo_deletion )
        if row[ "verdict" ] != VERDICT_PRUNABLE:
            continue
        try:
            path.unlink()
            pruned.append( str( path ) )
        except OSError:
            pass                                           # racing delete → fine
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
