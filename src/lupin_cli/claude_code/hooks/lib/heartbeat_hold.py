#!/usr/bin/env python3
"""
Hold artifact read, write and janitor helpers for the heartbeat Stop hook.

A paused session defends its quiescence by writing a per-session hold file. The Stop hook honors a
present, fresh, reasoned hold and declines to poke. This module handles only that artifact.
The work-owed oracle and the Stop hook decision flow are separate concerns.

See: src/rnd/v0.1.8/2026.06.04-heartbeat-hook/01-spike-findings-and-stop-py-seam-analysis.md
See: planning-is-prompting/src/rnd/2026.06.02-stop-hook-natural-heartbeat-poker.md

The artifact is `.heartbeat-hold-<session_id>.json`, gitignored, one file per session. Each session
writes and reads only its own file, which makes it multi-writer safe. A fleet poker globs
`.heartbeat-hold-*.json` for the cross-session view. Default location is the fleet data root.

Schema, the public interface (hold to it exactly):
    `session_id` (str): Filename suffix.
    `persona` (str): Owning persona.
    `held_at` (str): ISO-8601 timestamp the hold was declared.
    `ttl_seconds` (int): Freshness window; an expired hold is undeclared and so pokeable.
    `work_owed` (bool): False means done, so never poke.
    `reason` (str): Why the session is holding.
    `awaiting` (str): "user:<name>", "peer:<persona>", "commons:<topic>", "cadence:<what>" or "none".
    `pending_user_gates` (list): Structured open or answered direct-user-gate rows. They promote the free-text
        "awaiting: user:rick" to re-askable rows.
    `last_looked_in_on_workers_ts` (str or None): Manager's latest worker look-in, a debounce clock; None means never.
        The agent stamps it when it verifies workers.
    `last_spinup_check_ts` (str or None): Manager's latest spin-up self-check, a debounce clock; None means never.
        The agent stamps it after considering a crew.
    `last_surfaced_questions_ts` (str or None): Latest operator-gate re-surface, a debounce clock; None means never.
        The agent stamps it after re-firing its open asks.

The "cadence:<what>" form marks an observation or timer cadence: work is owed but nobody owes this
session anything, and it re-polls at its own ttl. Use it instead of "peer:" when no peer owes a
deliverable, because only "peer:" strings mint arbiter blocking edges (dependency_graph
_parse_peer_target). A cadence hold is therefore waiting on its own timer, never read as blocked, never chased.
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
PROJECTS_DIR_NAME = "projects"               # the fleet's tree of repos; DATA_DIR_FALLBACK is its SIBLING


def _main_repo_path( repo_root ):
    """
    Absolute directory of a tree's main repo; a worktree resolves to its parent checkout.

    A normal checkout resolves to itself.

    Requires:
        - repo_root is a path-like

    Ensures:
        - returns an absolute Path; falls back to the resolved repo_root when git
          is unavailable or the path is not a repo
        - never raises
        - both the repo identity and the fallback data base derive from this path, not from
          the passed tree, because a base derived from a worktree path yields `.claude/projects-data/...`
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
    Name of the main repo a tree belongs to, the fleet-global key for its runtime data.

    One data dir per repo is shared by every worktree of it, so the key is repo identity, not tree identity.

    Requires:
        - repo_root is a path-like pointing inside a git tree (or not)

    Ensures:
        - returns the main repo's directory name; falls back to the basename of
          repo_root when git is unavailable or the path is not a repo
        - never raises
        - `--git-common-dir` resolves a worktree to its main repo where a basename resolves it to itself,
          and it returns a relative `.git` from the main checkout, so `--path-format=absolute` is not optional
        - the sweep does not use this predicate: `_compute_hold_roots` dedupes on realpath because a worktree
          and its main repo are different directories holding different files. Both rules stand; do not unify them
    """
    return _main_repo_path( repo_root ).name


def _enclosing_tree_root( path ):
    """
    Git working tree that `path` sits inside, or None when it sits inside none.

    The test is structural (a `.git` entry on the ancestor chain), not `git rev-parse`, for two reasons.
    The path may not exist yet, and `git -C <missing>` answers about the CWD's repo instead.
    It also runs on every hold read, where a subprocess per call is real cost.

    Requires:
        - path is path-like

    Ensures:
        - returns the nearest ancestor-or-self holding a `.git` entry, else None
        - never raises
        - `.git` is a directory in a main checkout and a file in a linked worktree; both count,
          which is why the test uses existence and not is_dir
    """
    here = Path( os.path.realpath( path ) )            # realpath: no strict mode, so no raise
    for candidate in [ here, *here.parents ]:
        if ( candidate / ".git" ).exists():             # Path.exists() swallows OSError itself
            return candidate
    return None


def _fleet_data_base( main ):
    """
    Directory the per-repo data dirs live in: one directory for the whole fleet.

    The base anchors on the outermost `projects` directory, not on a depth, as the comment on
    `DATA_DIR_FALLBACK` promises ("sibling of the projects tree"). A base derived from a fixed depth
    is correct only for a repo exactly one level under `projects/`.

    Requires:
        - main is the main repo path (a worktree already resolved to its checkout)

    Ensures:
        - returns the env var verbatim when `DEEPILY_DATA_DIR` is set; a deployment
          that names its own base is not second-guessed
        - otherwise returns <outermost `projects` ancestor>.parent / projects-data
        - with no `projects` ancestor, returns the legacy depth arithmetic, walked up
          out of any git working tree it lands in
        - never raises
        - a fleet-global directory cannot come from a per-repo depth. A repo at `projects/lupin/src/lupin-mobile`
          landed in `projects/lupin/projects-data`, inside the lupin tree where the arbiter and Stop hook do not look
        - a repo at `projects/google/weil-parallel-search` landed in `projects/projects-data`, outside every
          tree but still not the fleet dir. The outermost `projects` ancestor wins, so a repo holding its own
          `projects/` subtree still maps to the single fleet dir
        - the escape loop covers the last-resort branch, for a repo outside any `projects/` tree, so no data
          root ever resolves inside a git working tree
    """
    env = os.environ.get( DATA_DIR_ENV )
    if env:
        return Path( env )

    parts = Path( os.path.realpath( main ) ).parts     # absolute ⇒ parts[0] is the anchor, never a match
    for i, part in enumerate( parts ):                 # outermost `projects` wins
        if part == PROJECTS_DIR_NAME:
            return Path( *parts[ :i ] ) / DATA_DIR_FALLBACK

    base = Path( main ).parent.parent                  # last resort: the pre-1facc18e arithmetic
    while True:
        tree = _enclosing_tree_root( base )
        if tree is None:
            break
        base = tree.parent                             # strictly up ⇒ terminates at the filesystem root
    return base / DATA_DIR_FALLBACK


def fleet_data_root( repo_root=None ):
    """
    Fleet-global runtime-data directory for this repo.

    Runtime state (hold files, DM-inbox bookmarks, acked ledgers, task-store maps) lives outside the repo
    root. A gitignored path inside the tree is on the kill list of `git clean -xdf`, not shielded by it.
    A dry run listed cargo-bearing holds as would-remove.

    Ensures:
        - returns <DEEPILY_DATA_DIR>/<repo-name>
        - falls back to <projects-parent>/projects-data/<repo-name> when the env
          var is unset. This is not a silent degradation to the repo root, which would
          recreate the clutter. It is the same location the env var names, derived rather
          than read, so a long-lived session whose environment predates the variable still
          writes where everyone else reads
        - the derivation anchors on the `projects` directory, not on a depth, so a
          nested repo (src/lupin-mobile) and a grouped one (google/...) land in the
          one fleet dir. See _fleet_data_base for why the result never sits inside a working tree
        - never raises
    """
    import cosa.utils.util as cu
    root = Path( repo_root ) if repo_root is not None else Path( cu.get_project_root() )
    main = _main_repo_path( root )                     # a worktree resolves to its parent checkout
    return _fleet_data_base( main ) / main.name


def hold_correct_zone( swept_roots=None ):
    """
    Directory tree a correctly placed hold must live under: the parent of the fleet data root.

    A hold at <projects-data>/<any-repo>/.heartbeat-hold-*.json is correct. One at a repo root or
    inside a worktree is not.

    Requires:
        - swept_roots is None or an iterable of the roots the sweep will scan (the
          arbiter passes report_hold_files's roots_swept); None runs the floor only

    Ensures:
        - returns fleet_data_root().parent, resolved
        - returns None if the root cannot be resolved; a resolution failure must
          not make the sweep raise, and the caller treats None as "cannot judge"
        - fails closed on a floor: a zone at the filesystem root ("/") is an ancestor of every path,
          so hold_is_misplaced would return False for everything and the detector would
          go permanently silent while looking healthy. A zone with fewer than 2 path
          parts returns None. This cheap check only catches "/"
        - fails closed structurally: the zone is too broad if any swept repo root sits under it
          (for example DEEPILY_DATA_DIR=/mnt gives zone "/mnt", an ancestor of the repo roots at
          /mnt/DATA01/.../<repo>, which the parts-count floor cannot catch). When swept_roots is provided and any of them is under the
          zone, returns None, excluding the fleet data root's own subtree, which legitimately lives
          under the zone. This makes the /mnt-class failure impossible rather than merely improbable
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
    Report whether a hold file sits outside the fleet data root; repo-root holds read True.

    This is the location signal that the arbiter's resilient read now hides. Teaching the veto to read a
    repo-root hold makes a misplaced hold function, so its only symptom (the relentless poke) disappears.
    The sweep must still surface the file or the leak goes silent, so location is its own field.

    Ensures:
        - True iff `correct_zone` is not an ancestor of `path`
        - fail-safe: an unresolved zone (None) or an unresolvable path returns
          False, so the detector never over-flags a hold it cannot place
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
        - base_dir provided: Path( base_dir ), so tests and explicit callers win
        - base_dir is None: the fleet data root, not the project root (never __file__ chains)
        - when base_dir is None, creates the fleet data root if absent: every caller either writes into
          it or globs it, and a missing dir would surface as "no files", the silent-empty reading
          this family keeps being bitten by. An unwritable root is left for callers to fail loudly on
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
    Per-session base directory for hold files, taken from the Stop-hook cwd.

    The hold lives in the session's own project root. Resolving it from the hardwired LUPIN_ROOT made
    every non-lupin session's hold land under lupin, invisible to that session's own Stop-hook reads.
    The Stop hook therefore threads its payload `cwd`, the directory where the poked agent writes its hold.

    Requires:
        - cwd is a path-like / string / None (the Stop-hook payload's cwd)

    Ensures:
        - Truthy cwd: Path( cwd ), the session's own root
        - Falsy or None cwd: cu.get_project_root() (LUPIN_ROOT fallback; the
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
    Current time as a timezone-aware `UTC` datetime.

    Ensures:
        - Returns a timezone-aware (`UTC`) datetime for "now".
    """
    return datetime.datetime.now( datetime.timezone.utc )


def _file_mtime( path ):
    """
    Host-real modification time (epoch seconds) of a hold file, or None on a stat failure.

    This is the freshness anchor. Best-effort and degrade-safe: a clean testable seam for the
    stat-failure branch, so read_hold need not inline the try/except.

    Requires:
        - path is a pathlib.Path (or any object with a .stat() returning st_mtime)

    Ensures:
        - Returns float st_mtime on success
        - Returns None when the file cannot be stat'd (OSError); read_hold then
          omits the annotation and is_fresh falls back to held_at
        - Never raises
    """
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _parse_iso( value ):
    """
    Parse an ISO-8601 timestamp into a timezone-aware datetime, or None when unusable.

    Requires:
        - value is anything (defensive)

    Ensures:
        - Returns an aware datetime on success (naive input assumed `UTC`)
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
    Write this session's hold artifact atomically and return the dict that was written.

    Requires:
        - session_id is a non-empty string
        - persona and reason are strings
        - work_owed is a bool
        - ttl_seconds is a positive number (int or float)
        - awaiting is a string (see schema)
        - pending_user_gates is a list of gate-row dicts or None (None becomes [])
        - last_looked_in_on_workers_ts is an ISO-8601 string or None
        - last_spinup_check_ts / last_surfaced_questions_ts are ISO-8601 strings
          or None (the Face A / Face B debounce stamps)

    Ensures:
        - Writes <base_dir>/.heartbeat-hold-<session_id>.json with exactly
          the `HOLD_SCHEMA_FIELDS` fields, in order (gate, look-in and debounce fields included)
        - pending_user_gates defaults to [] (no open gates) when not supplied;
          last_looked_in_on_workers_ts / last_spinup_check_ts /
          last_surfaced_questions_ts default to None (never run)
        - held_at defaults to now (`UTC`, seconds precision) when not supplied
        - Write is atomic (temp file + os.replace) so a concurrent fleet
          Poker never reads a half-written file
        - Returns the hold dict that was written

    Raises:
        - ValueError if ttl_seconds is not a positive, non-bool number. The old Requires line was prose
          that nothing enforced: `write_hold( ttl_seconds=None )` wrote a null ttl, while sibling defaults were normalized. An unusable ttl makes `is_fresh` False,
          so `is_honored` is False and the session is poked forever despite its hold. Fail at the write,
          loudly, rather than mint a hold that cannot defend anything
        - ValueError if reason is empty or whitespace-only. `is_honored` requires a non-empty reason, so an
          empty one lands a hold that declares quiescence and defends nothing. On a refresh it would overwrite
          a live honored hold and cost the running session the defense it already had. The guard is the exact
          complement of the `is_honored` predicate (`bool( reason and str( reason ).strip() )`). A guard that
          rejected only "" would let "   " pass the writer and fail the reader. Two checks on one property
          must agree on it, or the stricter one is just a smaller version of the hole
        - OSError if the target directory is not writable / does not exist

    Both raises precede every filesystem touch, which is required, not tidy: a refused write must leave a
    pre-existing hold as it found it. Validating after `os.replace` would make every refusal destructive.
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
    Resolve which hold file `read_hold` reads: exact id first, else the 8-char id prefix.

    An agent that writes a hold may use the short bridge id (get_session_info hands it the 8-char form).
    The Stop hook reads with the full stable id. Without this fallback that hold is silently ignored.
    The session is then poked forever despite having declared a hold.

    Requires:
        - session_id is a string (may be empty)
        - base_dir is a path-like / string / None

    Ensures:
        - Returns the exact <base>/.heartbeat-hold-<session_id>.json when present
        - Else, for a non-empty session_id, returns the hold file whose id-suffix
          shares session_id[:8] (ignoring `.tmp` atomic-write artifacts); on
          multiple id-form matches, prefers the longest suffix (a full hyphenated
          id over a short 8-char form), then lexical; deterministic, clock-free
        - Else returns the exact path (which read_hold treats as absent)
        - Never raises (glob OSError returns the exact path)
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
    Read this session's hold artifact, stamped with the file's host-real mtime.

    Requires:
        - session_id is a string

    Ensures:
        - Returns the hold dict if the file exists and parses to a JSON object
        - Falls back across short/full id forms when the exact file is absent
          (see _read_hold_path)
        - Stamps the resolved file's host-real mtime (epoch seconds) into the
          returned dict under `HOLD_MTIME_ANNOTATION` so is_fresh can anchor
          freshness on when the hold was actually written, not the agent-supplied
          held_at. The stamp is best-effort: a stat failure
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
    Read only this session id's own hold file, with no prefix fallback, ever.

    For guards that protect a write or a delete. `read_hold` is prefix-tolerant, which suits a read: the wrong file costs a missed poke.
    A guard must not do that, because `write_hold` and `clear_hold` act on the exact path. A prefix-tolerant guard would vouch for a file its action never touches.
    That let the cargo guard refuse a session its hold over cargo in a different file.

    Requires:
        - session_id is a string
        - base_dir is a path-like / string / None

    Ensures:
        - Returns the hold dict at exactly <base_dir>/.heartbeat-hold-<id>.json
        - Returns None when that path is absent, unreadable, malformed, or parses
          to a non-object; a prefix sibling is never consulted
        - Carries no mtime annotation: freshness is a question about a resolved
          hold, and this reader resolves nothing at all
        - Never raises
        - use it wherever the question is what is in the file about to be replaced or deleted;
          use `read_hold` where the question is whether this session has a hold anywhere
    """
    path = hold_path( session_id, base_dir=base_dir )
    try:
        if not path.exists():
            return None
        data = json.loads( path.read_text() )
    except ( OSError, ValueError ):
        return None
    return data if isinstance( data, dict ) else None


def hold_search_dirs( cwd=None ):
    """
    Ordered, de-duplicated directories the Stop hook searches for a session's hold.

    The middle entry exists because the fleet data root derives from the hook's own LUPIN_ROOT, always lupin's.
    The write verb defaults to `projects-data/<repo>` for the repo it runs in. A session in another repo
    wrote its hold there and was poked on every tick.

    Requires:
        - cwd is the Stop-hook payload's cwd (path-like / string / None)

    Ensures:
        - returns a list of Paths, cwd-first, with no directory listed twice
        - [ resolve_hold_base_dir( cwd ), fleet_data_root( cwd ), _resolve_base_dir( None ) ]
          when cwd is truthy; the middle entry is omitted when it is not
        - for a lupin session the middle entry is the same directory as the last and collapses
        - never raises (fleet_data_root and resolve_hold_base_dir never raise)
    """
    bases = [ resolve_hold_base_dir( cwd ) ]
    if cwd: bases.append( fleet_data_root( repo_root=cwd ) )
    bases.append( _resolve_base_dir( None ) )

    candidates = []
    seen       = set()
    for base in bases:
        key = str( base )
        if key in seen:
            continue
        seen.add( key )
        candidates.append( base )
    return candidates


def read_hold_resilient( session_id, cwd=None ):
    """
    Read this session's hold from every directory it could plausibly live in.

    A written, honored hold is found whatever the reading session's cwd. `write_hold` defaults to the
    fleet data root, but the Stop hook once read only from the session's own cwd. A worker in a git
    worktree then never found its hold and was re-poked forever.

    Requires:
        - session_id is a string
        - cwd is the Stop-hook payload's cwd (path-like / string / None)

    Ensures:
        - Returns the first hold found across `hold_search_dirs( cwd )`: cwd first
          so a per-session hold wins, then the fleet data dir of the cwd's
          repo (where the write verb defaults), then the hook's own fleet data dir
        - Returns None when no candidate dir holds a readable hold
        - Never raises (delegates to read_hold, which swallows all errors)
    """
    for base in hold_search_dirs( cwd ):
        hold = read_hold( session_id, base_dir=base )
        if hold is not None:
            return hold
    return None


def read_hold_via_bridge( session_id, log_fn=None ):
    """
    Read a session's hold for a caller with no cwd, using the cwd in its bridge snapshot.

    The caller is the arbiter. The bridge snapshot holds the session's own cwd, written at SessionStart.
    Plain `read_hold` resolves only the fleet data root. A hold leaked to a repo root is then invisible
    to the arbiter's honored-hold veto, and a parked session keeps getting poked.

    Requires:
        - session_id is a string
        - log_fn is None or a callable ( event_name, **fields ), the arbiter's
          journal fn, injected so the fallback below is visible

    Ensures:
        - Returns read_hold_resilient( session_id, cwd=<bridge cwd> ); the bridge
          cwd catches a repo-root hold in any project (planning-is-prompting,
          worktrees), closing both gaps a bare cwd=None would strand
        - A missing or unreadable bridge degrades to cwd=None, not a crash:
          find_session_by_id returns None on a miss, so the guard `( ... or {} )`
          avoids an AttributeError, which must not happen, and cwd=None still searches the project root
          and fleet data root, so a bridge-less session never regresses to the blind fleet-only read
        - whenever cwd resolves to None (no_bridge / bridge_without_cwd /
          bridge_error) and log_fn is provided, emits one
          `arbiter_hold_reader_cwd_fallback` line with session_id and reason. A silent
          degrade to cwd=None would restore the blind path invisibly, so a future bridge
          regression that puts the arbiter back to poking parked sessions shows in the
          journal. The cwd-present path never logs (no per-tick noise)
        - Never raises (any bridge-resolution failure gives cwd=None; the delegate
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
    Delete this session's hold artifact; safe to call when none exists.

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
    Report whether a hold's `ttl_seconds` can anchor a freshness window.

    This is the single discriminator behind both loud paths. is_fresh returns False for an unusable ttl, so is_honored is False and the session is poked.
    The janitor refuses to age a file it cannot prove old. A check such as `ttl is None` cannot tell absent from null from present-and-fine.
    This helper asks only whether the value is usable.

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
    Sorted list of the non-schema keys a hold file carries, its "cargo".

    Hold files are hand-written with continuity payload the schema has no room for (for example
    `note_to_my_successor`, `board`, `harvest_state`). Those files are mementos wearing a hold's
    filename, and they are irreplaceable. The janitor must say so before anything is deleted.

    Requires:
        - hold is a dict or None

    Ensures:
        - Returns the sorted list of keys not in `HOLD_SCHEMA_FIELDS`, excluding
          `_`-prefixed in-memory annotations (`HOLD_MTIME_ANNOTATION` is stamped by
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
    Report whether the recursive sweep must refuse to descend into a directory.

    Requires:
        - path is a Path; skip_dir_names is a container of directory names

    Ensures:
        - Returns True for a dir named in skip_dir_names, or for the
          `.claude/worktrees` tree specifically (a worktree's holds belong to the
          worktree's own lineage, not the main tree's sweep)
        - Never raises
    """
    if path.name in skip_dir_names:
        return True
    return path.name == "worktrees" and path.parent.name == ".claude"


def _probe_dir_for_holds( root, max_depth, glob_pat=None ):
    """
    Count hold files inside a directory the sweep is skipping, depth-bounded.

    A skip-list that silently swallows hold-bearing directories reports zero found and reads as
    nothing there. A hold lives under `lupin/.claude/worktrees/cheech-orphan-bridge`, which the skip-list
    excludes. The sweep still refuses to descend, but it says what it stepped over.

    Requires:
        - root is a Path; max_depth is a non-negative int
        - glob_pat is an fnmatch pattern, or None for the default `HOLD_GLOB`

    Ensures:
        - Returns the list of matching Paths found under root within max_depth
        - Never descends into a nested skipped dir; never raises (OSError gives [])
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
    Depth-bounded recursive scan of one root for hold files.

    Requires:
        - root is a Path; max_depth is a non-negative int; skip_dir_names is a
          container of directory names
        - glob_pat is an fnmatch pattern, or None for the default `HOLD_GLOB`

    Ensures:
        - Returns ( hold_paths, skipped_dirs ) where skipped_dirs is a list of
          { "dir": str, "hold_count": int } for skip-listed dirs that contain holds
          (a skipped empty dir is not reported; only a swallowed hold is news)
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
    Enumerate hold files across one or many roots; the shared sweep front-end.

    Requires:
        - base_dir is path-like / str / None (legacy single-root mode)
        - base_dirs is an iterable of path-like roots, or None
        - max_depth is a non-negative int; skip_dir_names is a container of names
        - glob_pat selects the file family to enumerate; None means `HOLD_GLOB`, so
          every pre-existing caller keeps its exact behavior. The traversal is
          family-agnostic: what a file means is the classifier's business, not
          the walker's, so a second runtime-state family can reuse this
          without touching classify_hold_file

    Ensures:
        - base_dirs is None: legacy mode, the single resolved base_dir, globbed
          non-recursively, byte-for-byte the pre-multi-root behavior every existing
          caller depends on (a glob OSError yields no paths)
        - base_dirs provided: each root de-duplicated by path, swept recursively
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
    Decide what the janitor would do with one hold file, and never touch it.

    This is the single decision rule: `prune_stale_hold_files` acts on this verdict and
    `report_hold_files` only prints it. One rule with two consumers means the report cannot drift
    from the deletion it is evidence for.

    Requires:
        - path is a Path to a candidate hold file
        - now is an aware datetime or None; grace_seconds >= 0
        - live_session_ids is an iterable of live session-id strings, or None
          (no authoritative live-set; see prune_stale_hold_files, bias to keep)
        - allow_cargo_deletion is False by default; see the cargo guard below

    Ensures:
        - Returns a row dict: path, verdict (`VERDICT_PRUNABLE` or `VERDICT_KEEP`),
          reason, session_id, persona, ttl_seconds, ttl_usable,
          held_at_age_seconds, mtime_age_seconds, threshold_seconds,
          cargo_bearing, cargo_keys, anchor_disagreement
        - conservative: unreadable / non-object / live-session /
          unprovable-age / within-threshold / cargo-bearing files all yield `VERDICT_KEEP`
          with the reason naming the guard that kept it
        - the cargo guard: a file carrying non-schema cargo can never be prunable while
          allow_cargo_deletion is False, which is the default. It lives here and not at the call site,
          because cargo was reported here but protected by callers, one forgotten argument deep. The
          unmodified janitor, handed roots alone, deleted 20 files, 10 of them cargo-bearing mementos.
          It must stay openable: triage is copy-forward, so rescued originals keep their cargo keys, and a
          permanent guard would make those husks unreclaimable. The gated reclamation step passes
          allow_cargo_deletion=True, but only after the triage is verified. It overrides at the prunable
          decision rather than on entry, because an earlier check would relabel every cargo file that some
          other guard already kept, and the tally could no longer say how many would have been deleted
          but for the cargo guard. A `cargo_bearing` reason means exactly that
        - anchor_disagreement flags a file the janitor would prune on its `held_at` age while the hook
          would still call it fresh on the file's mtime. The two readers anchor on different clocks. The file
          is kept with reason `KEEP_ANCHOR_DISAGREEMENT`, never pruned, so pruning needs both clocks to call
          it ancient. This guard sits ahead of the cargo guard, since liveness outranks cargo, and it is not
          openable, because overriding "one clock says this session is alive" is never correct
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
    Reach and classify every hold file, and delete nothing, ever.

    This function contains no unlink and calls nothing that does, which is structural, not a flag.
    Reclamation is a separate, gated step run after cargo triage. A hold's non-schema keys are the only
    copy of a reaped session's continuity record. An empty report is how a wrong root list shows up.

    Requires:
        - base_dir / base_dirs / max_depth / skip_dir_names per _iter_hold_paths
        - now is an aware datetime or None; grace_seconds >= 0
        - live_session_ids is an iterable of live session ids, or None

    Ensures:
        - Returns { roots_requested, roots_swept, roots_unreachable,
                    skipped_dirs_with_holds, files_found, files, location_zone,
                    misplaced_paths, counts, deleted }
        - counts carries prunable, keep, cargo_bearing, ttl_unusable,
          anchor_disagreement, misplaced and reachable_but_kept_reasons (per-guard tally)
        - location_zone is None when the zone was unjudgeable; the caller must treat that distinctly
          from a real zero misplaced, so a fail-closed zone surfaces loudly and not as a false all-clear
        - roots_swept being empty is reported distinctly from prunable being 0: "swept nothing" and
          "swept everything and found nothing to reap" are opposite facts that a lone zero cannot tell apart
        - deleted is always 0; the field exists so a reader never has to infer it
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
    Delete hold files provably dead or expired far longer than any plausible live session.

    It reclaims the accumulating `.heartbeat-hold-*.json` cruft. Deletion follows classify_hold_file's verdict only.

    Requires:
        - base_dir is path-like / str / None; now is an aware datetime or None;
          grace_seconds >= 0; live_session_ids is an iterable of session-id
          strings (authoritative live-set) or None (no authoritative set)
        - base_dirs is an iterable of roots (recursive multi-root mode) or None
          (legacy single-root mode); max_depth / skip_dir_names bound the recursion

    Ensures:
        - deletes only provably-stale hold files (conservative ttl plus grace, or ttl alone
          on a positive-dead reading); returns the sorted list of pruned paths (strings)
        - the keep or prune decision is classify_hold_file's, one rule shared with
          report_hold_files, so the dry-run evidence cannot drift from the act
        - never raises (a per-file OSError / JSON error skips that file)
        - a file is prunable only if its session_id is not in `live_session_ids` and its held_at parses and its age
          passed the threshold. With no authoritative live-set the threshold is ttl_seconds plus grace_seconds,
          so a live or long-single-turn session that refreshes well inside it is never at risk
        - with an authoritative live-set and a hold whose real session_id is absent from it, the threshold is its
          own ttl_seconds with no grace. An ungraceful death (crash, exit, tmux kill) bypasses the reap-time
          hold-clear and leaves an orphan hold the arbiter derives phantom edges from for the ttl plus 6 hours
        - bias to keep: the grace is dropped only on a positive dead reading. A live session can carry a stale
          hold, so an absent live-set or a hold with no session_id keeps ttl plus grace. The caller must pass a
          non-None `live_session_ids` only when it has enumerated live sessions; None keeps the legacy behavior
        - a file that is unreadable, non-JSON, not a dict, missing or unparseable held_at, or carrying a
          non-numeric ttl is kept; the janitor only ever deletes a hold it can prove is ancient
        - base_dirs sweeps a caller-supplied list of roots recursively (depth-bounded, skip-listed); base_dir
          alone keeps the exact legacy single-root, non-recursive behavior. The root list is never derived here
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
    Report whether a hold is within its freshness window, anchored on file mtime if known.

    The window is measured from the hold file's host-real mtime (`HOLD_MTIME_ANNOTATION`, stamped by the reader) when present, not the agent-supplied `held_at`.
    Agents have no reliable wall-clock, so a just-written hold could read stale and the session was re-poked forever.
    `held_at` stays the fallback for a hold dict with no mtime annotation.

    Requires:
        - hold is a dict or None
        - now is an aware datetime or None (defaults to current `UTC`)

    Ensures:
        - Returns False for a missing hold or a non-numeric ttl_seconds (bool is
          explicitly rejected)
        - When the hold carries a numeric `HOLD_MTIME_ANNOTATION`: returns
          (now - mtime) < ttl_seconds, the host-real freshness rule
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
    Report whether the hook should honor this hold, meaning not poke.

    A hold is honored only when it is declared, fresh and reasoned, the "defend your quiescence" test.

    Requires:
        - hold is a dict or None
        - now is an aware datetime or None

    Ensures:
        - Returns True iff hold is fresh and has a non-empty reason
        - Returns False otherwise
        - Never raises
    """
    if not is_fresh( hold, now=now ):
        return False
    reason = hold.get( "reason" )
    return bool( reason and str( reason ).strip() )


def declared_work_owed( hold ):
    """
    Return the hold's self-declared work_owed flag, or None when it has none.

    It is the first source of work-owed truth in the Branch C decision flow, ahead of the
    TODO and Pending-Decisions oracle.

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
    Return the hold's structured pending-user-gate rows (the outward twin), or [].

    Requires:
        - hold is a dict or None

    Ensures:
        - Returns the list value of hold["pending_user_gates"] when it is a list
        - Returns [] when there is no hold, the field is absent, or it is non-list
          (an older hold has no gates, so [] keeps the outward twin silent)
        - Never raises
    """
    if not hold:
        return [ ]
    value = hold.get( PENDING_USER_GATES_FIELD )
    return value if isinstance( value, list ) else [ ]


def get_last_looked_in_ts( hold ):
    """
    Return the manager's latest worker-verification look-in stamp, or None.

    This is the inward-twin debounce clock: the IO shell feeds it to manager_needs_verification.
    An older hold, or one that never looked in, yields None, so a manager with workers out reads as
    owing a first look-in.

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
    Return the manager's latest spin-up-check stamp (Face A), or None.

    This is the Face A debounce clock, fed by the IO shell to manager_needs_spinup_check.
    A hold without the field yields None. A manager with a backlog and idle capacity then reads
    as owing a first spin-up nudge.

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
    Return the session's latest operator-gate re-surface stamp (Face B), or None.

    This is the Face B debounce clock, fed by the IO shell to manager_needs_question_surface.
    A hold without the field yields None. A session holding an open operator gate then reads
    as owing a first re-surface.

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
    Self-contained, side-effect-free smoke test that uses a temp dir.

    Ensures:
        - Returns True if write then read round-trips and freshness/honor/owed
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
