"""
Reclaim accumulated `.dm-inbox-hwm-<sid8>.json` files once their sessions are gone.

What these files are: `.dm-inbox-hwm-<session_id8>.json` is one session's DM-inbox
high-water mark, a `cursor_ts` plus the `surfaced_ids` already shown to that
session. The ledger is what makes DM surfacing at-least-once. Without it, a peer DM
arriving mid-turn lands in a lossy JSONL voice buffer and is lost if the session
ends first. The files live in the repo root because surviving `/clear`
is their purpose. Nothing here may tidy them into a directory the reconcile cannot find.

The defect: `surfaced_ids` inside each file is capped (`SURFACED_IDS_CAP = 500`,
FIFO tail), but the number of files was never bounded. One file exists per
session and every `/clear` mints a new session id. This is tidiness, not capacity.

Why this is not `classify_hold_file`: pointing the hold janitor's glob at a second
family would build a sweeper that deletes nothing and reports success. On a real
HWM file it answers verdict `keep`, reason `no_provable_age`. Two reasons:
  1. It keeps any file whose age it cannot prove from `held_at` + `ttl_seconds`,
     and an HWM body `{cursor_ts, seeded, surfaced_ids}` has neither.
  2. Its live-session guard reads `hold.get( "session_id" )`. An HWM body has no
     `session_id`, because the sid8 lives in the filename.
What is reusable is the traversal (`_iter_hold_paths`, family-parameterized) and the
reclaim loop. This module supplies the meaning of a file.

The one real hazard is liveness. Deleting a live session's HWM does not cause a
duplicate DM. A missing HWM file reads as `seeded: False` (`read_hwm`), and
`dm_inbox_reconcile.surface_dm_inbox` treats that as a first-ever activation. It
records the current inbox as already seen, advances the cursor, and surfaces
nothing, so activation never replays a live backlog. Deleting a live HWM therefore
silently swallows every DM sitting un-surfaced in that inbox, permanently. The
live-set gate is correctness-critical: it is the only thing between this janitor
and the DM-loss defect it tidies up after. This is why `live_session_ids is None`
keeps everything instead of degrading to age-only. A short grace window makes a
live-but-unlisted session more likely to still be inside it, so keep it long.
HWM files are safer in kind than hold files, being regenerable and carrying no hand-written cargo, yet their failure is silent and so not lesser.
The grace window follows the operator's last ruling and must not be quietly re-tuned.

Venue: pure filesystem + mtime. No network, no DB, no container.
"""
import time
from pathlib import Path

# FULL package path, matching every sibling in this lib (heartbeat_hold_warn,
# heartbeat_decision, task_store_spool, dm_inbox_reconcile). A bare
# `from heartbeat_hold import ...` resolves only when this directory is on
# sys.path — true under hook execution and in a test that inserts it, FALSE when
# the arbiter imports this module by its package path, which is what production
# does. The bare form was the first draft here and it broke arbiter collection.
from lupin_cli.claude_code.hooks.lib.heartbeat_hold import (
    _iter_hold_paths, _file_mtime, _resolve_base_dir,
    DEFAULT_SWEEP_MAX_DEPTH, SWEEP_SKIP_DIR_NAMES,
)

# The family this janitor owns. Deliberately NOT folded into HOLD_GLOB — see the
# module docstring for why one glob over two families would be a silent no-op.
HWM_GLOB   = ".dm-inbox-hwm-*.json"
HWM_PREFIX = ".dm-inbox-hwm-"
HWM_SUFFIX = ".json"

# Rick's ruling, 2026-07-26: 7 days. Clears 263 of 435 on the day it was chosen,
# which keeps the pile visibly small — the complaint that opened the row.
DEFAULT_HWM_GRACE_SECONDS = 7 * 24 * 60 * 60

VERDICT_KEEP     = "keep"
VERDICT_PRUNABLE = "prunable"

PRUNE_ORPHANED_AND_AGED = "orphaned_and_aged"

KEEP_LIVE_SESSION    = "live_session"
KEEP_NO_LIVE_SET     = "no_authoritative_live_set"
KEEP_TOO_YOUNG       = "within_grace_window"
KEEP_NO_PROVABLE_AGE = "no_provable_age"
KEEP_UNPARSEABLE     = "unparseable_name"


def hwm_sid8( path ):
    """
    Extract the session-id fragment an HWM filename encodes.

    The sid8 lives in the filename, because an HWM body carries no session_id.
    It is a `[:8]` truncation of whatever `_hwm_path` was handed, not a guaranteed 8-char hex string.

    Requires:
        - path is a Path or str

    Ensures:
        - returns the fragment between the family prefix and the .json suffix
        - returns None when the name does not belong to this family, so a caller
          cannot silently treat a foreign file as a zero-length session id
        - never raises

    Notes:
        - That is why the hold classifier's live gate cannot work on this family.
        - A real file in the repo root is `.dm-inbox-hwm-stable-s.json`.
        - Any gate built on this must compare 8-char prefixes on both sides, must never assume hex, never parse, and never raise on a surprising value.
    """
    name = Path( path ).name
    if not name.startswith( HWM_PREFIX ) or not name.endswith( HWM_SUFFIX ):
        return None
    sid8 = name[ len( HWM_PREFIX ) : -len( HWM_SUFFIX ) ]
    return sid8 or None


def _live_prefixes( live_session_ids ):
    """
    Normalize an authoritative live-set to the 8-char prefixes an HWM name carries.

    The truncation is not injective, and this gate depends on that being safe.
    Distinct session ids can share a prefix (several literals truncate to `stable-s`).
    Comparing prefixes over-matches, which is the safe direction: a collision makes more files look live.

    Requires:
        - live_session_ids is an iterable of session-id strings

    Ensures:
        - returns a set of `[:8]` prefixes, so a full uuid in the live set matches
          the truncated fragment in a filename
        - skips non-string / empty entries rather than raising

    Notes:
        - Do not change this into a full-id comparison. Every truncated filename would then fail to match any live id.
        - The gate would then start reaping live sessions' cursors, so the lossy key is what keeps the gate safe.
    """
    out = set()
    for sid in live_session_ids:
        if isinstance( sid, str ) and sid:
            out.add( sid[ :8 ] )
    return out


def classify_hwm_file( path, now_ts=None, grace_seconds=DEFAULT_HWM_GRACE_SECONDS,
                       live_session_ids=None ):
    """
    Decide keep or prunable for one HWM file; the report and the reclaim share this rule.

    Sharing it means the dry-run evidence cannot drift from the act.

    Requires:
        - path is a Path; now_ts is a POSIX timestamp (float) or None
        - grace_seconds >= 0; live_session_ids is an iterable or None

    Ensures:
        - returns a row dict: path / verdict / reason / sid8 / mtime_age_seconds
        - deletes nothing; never raises

    Rule:
        - A file is prunable iff all three hold: an authoritative live-set was supplied (not None),
          its filename sid8 is absent from that set, and its mtime age is >= grace_seconds.
        - It biases to keep. A None live-set keeps everything regardless of age.
        - An empty set must never read as "nothing is alive", because that inversion is how a janitor reaps the fleet.
        - The caller passes a non-None set only after enumerating live sessions.
        - mtime is the only clock an HWM file has, so an unreadable or negative mtime is not provable age and is kept.
    """
    if now_ts is None:
        now_ts = time.time()

    row = {
        "path"              : str( path ),
        "verdict"           : VERDICT_KEEP,
        "reason"            : KEEP_UNPARSEABLE,
        "sid8"              : None,
        "mtime_age_seconds" : None,
    }

    sid8 = hwm_sid8( path )
    if sid8 is None:
        return row                                     # not ours → KEEP, with a typed reason
    row[ "sid8" ] = sid8

    mtime = _file_mtime( path )
    if mtime is not None:
        row[ "mtime_age_seconds" ] = now_ts - mtime

    # The live gate FIRST: it is load-bearing, and at a 7-day window it is doing
    # more work than the age arm.
    if live_session_ids is None:
        row[ "reason" ] = KEEP_NO_LIVE_SET
        return row
    if sid8 in _live_prefixes( live_session_ids ):
        row[ "reason" ] = KEEP_LIVE_SESSION
        return row                                     # live session → never reap, at ANY age

    age = row[ "mtime_age_seconds" ]
    # A NEGATIVE age means the mtime is in the FUTURE — clock skew, a bad touch, a
    # restored backup. That is not evidence of youth; it is evidence the mtime
    # cannot be read as a clock at all, so it must not be trusted in EITHER
    # direction. Same lesson the hold janitor learned when a frozen `now` gave
    # every fixture a future mtime and the guard kept all of them — including the
    # control that proved deletion worked at all.
    if age is None or age < 0:
        row[ "reason" ] = KEEP_NO_PROVABLE_AGE
        return row
    if age < grace_seconds:
        row[ "reason" ] = KEEP_TOO_YOUNG
        return row

    row[ "verdict" ] = VERDICT_PRUNABLE
    row[ "reason" ]  = PRUNE_ORPHANED_AND_AGED
    return row


def report_hwm_files( base_dir=None, base_dirs=None, now_ts=None,
                      grace_seconds=DEFAULT_HWM_GRACE_SECONDS, live_session_ids=None,
                      max_depth=DEFAULT_SWEEP_MAX_DEPTH,
                      skip_dir_names=SWEEP_SKIP_DIR_NAMES ):
    """
    Dry-run triage over the HWM family: classify and tally, delete nothing.

    Its `prunable` count predicts what sweep_and_reclaim_hwm_files would delete under the same clock and live-set.
    If the two ever disagree, the disagreement is itself the finding.

    Requires:
        - the traversal args match _iter_hold_paths' contract
        - now_ts is a POSIX timestamp or None; grace_seconds >= 0

    Ensures:
        - returns { roots_requested, roots_swept, roots_unreachable,
                    skipped_dirs_with_holds, files_found, counts, rows, deleted }
          with deleted always 0
        - counts carries prunable / keep and a kept-reason histogram
        - never raises
    """
    if now_ts is None:
        now_ts = time.time()

    requested = list( base_dirs ) if base_dirs is not None else [ str( _resolve_base_dir( base_dir ) ) ]
    roots, unreachable, paths, skipped = _iter_hold_paths(
        base_dir=base_dir, base_dirs=base_dirs, max_depth=max_depth,
        skip_dir_names=skip_dir_names, glob_pat=HWM_GLOB
    )

    rows    = [ classify_hwm_file( p, now_ts=now_ts, grace_seconds=grace_seconds,
                                   live_session_ids=live_session_ids ) for p in paths ]
    reasons = { }
    for r in rows:
        if r[ "verdict" ] == VERDICT_KEEP:
            reasons[ r[ "reason" ] ] = reasons.get( r[ "reason" ], 0 ) + 1

    return {
        "roots_requested"         : [ str( r ) for r in requested ],
        "roots_swept"             : roots,
        "roots_unreachable"       : unreachable,
        "skipped_dirs_with_holds" : skipped,
        "files_found"             : len( paths ),
        "counts"                  : {
            "prunable"                   : sum( 1 for r in rows if r[ "verdict" ] == VERDICT_PRUNABLE ),
            "keep"                       : sum( 1 for r in rows if r[ "verdict" ] == VERDICT_KEEP ),
            "reachable_but_kept_reasons" : reasons,
        },
        "rows"                    : rows,
        "deleted"                 : 0,
    }


def sweep_and_reclaim_hwm_files( base_dir=None, base_dirs=None, now_ts=None,
                                 grace_seconds=DEFAULT_HWM_GRACE_SECONDS,
                                 live_session_ids=None,
                                 max_depth=DEFAULT_SWEEP_MAX_DEPTH,
                                 skip_dir_names=SWEEP_SKIP_DIR_NAMES ):
    """
    Delete the HWM files classify_hwm_file proves are orphaned and aged.

    Requires:
        - same contract as report_hwm_files

    Ensures:
        - deletes only files whose verdict is prunable under this exact clock and
          this exact live-set; returns the sorted list of deleted paths (strings)
        - a per-file OSError (racing delete) skips that file; never raises
    """
    if now_ts is None:
        now_ts = time.time()

    _roots, _unreachable, paths, _skipped = _iter_hold_paths(
        base_dir=base_dir, base_dirs=base_dirs, max_depth=max_depth,
        skip_dir_names=skip_dir_names, glob_pat=HWM_GLOB
    )

    pruned = [ ]
    for path in paths:
        row = classify_hwm_file( path, now_ts=now_ts, grace_seconds=grace_seconds,
                                 live_session_ids=live_session_ids )
        if row[ "verdict" ] != VERDICT_PRUNABLE:
            continue
        try:
            path.unlink()
            pruned.append( str( path ) )
        except OSError:
            pass                                       # racing delete → fine
    return sorted( pruned )
