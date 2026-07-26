"""
Reclaim accumulated `.dm-inbox-hwm-<sid8>.json` files — row 8758d0b1.

WHAT THESE FILES ARE (read this before deciding anything here is disposable)
---------------------------------------------------------------------------
`.dm-inbox-hwm-<session_id8>.json` is one session's DM-inbox high-water mark: a
`cursor_ts` plus the `surfaced_ids` already shown to that session. They are the
durable fix for bug `59f355e0` — a peer DM arriving mid-turn used to land in a
lossy JSONL voice buffer and was LOST if the session ended before a later hook
drained it (84 orphaned DMs across 46 stale buffers at triage). This ledger is
what makes DM surfacing at-least-once.

They live in the repo root ON PURPOSE — surviving `/clear` is the entire point.
Nothing here may "tidy" them into a directory the reconcile cannot find.

THE DEFECT
----------
The design bounded the wrong axis. `surfaced_ids` INSIDE each file is capped
(`SURFACED_IDS_CAP = 500`, FIFO tail); the NUMBER of files was never bounded and
no cleanup code existed anywhere. 435 files / 1.8 MB / ~18 per day since
2026-07-02, one per session, and every `/clear` mints a new session id.

⚠️ TIDINESS, NOT CAPACITY. Nothing is at risk. Keep the framing honest.

WHY THIS IS NOT `classify_hold_file`
------------------------------------
The obvious remedy — point the existing hold janitor's glob at a second family —
builds a sweeper that deletes NOTHING and reports success. Measured before
writing a line of this module:

    classify_hold_file( <a real HWM file> )
        -> verdict='keep'  reason='no_provable_age'  session_id=None

Two structural reasons, both in `heartbeat_hold.classify_hold_file`:

  1. It keeps any file whose age it cannot prove from `held_at` + `ttl_seconds`.
     An HWM body is `{cursor_ts, seeded, surfaced_ids}` — it has NEITHER.
  2. Its live-session guard reads `hold.get( "session_id" )`. An HWM body has NO
     `session_id` field at all; the sid8 lives in the FILENAME.

So the hold classifier is hold-SHAPED by construction, and correctly so. What is
reusable is the TRAVERSAL (`_iter_hold_paths`, now family-parameterized) and the
reclaim loop — not the meaning of a file. This module supplies the meaning.

THE ONE REAL HAZARD — LIVENESS, AND IT IS WORSE THAN THE PLAN SAID
------------------------------------------------------------------
🔴 The row's plan (§5) and the first draft of this module both stated that
deleting a live session's HWM makes it RE-SURFACE its DM history — "worst case a
duplicate DM, not data loss" — and that asymmetry was the stated justification
for a simpler rule than the cargo-bearing hold family's.

**It is backwards. Measured 2026-07-26; three predictions, three confirmed:**

    with an existing seeded HWM   ->  the pending DM IS surfaced   (330 chars)
    after the HWM is deleted      ->  surfaced? False              (0 chars)
    on the next turn              ->  surfaced? False, ids=['m1']

Mechanism — `dm_inbox_reconcile.surface_dm_inbox:327-328`:

    if not state.get( "seeded", False ):
        context = ""

A MISSING HWM file reads as `seeded: False` (`read_hwm:187`), which the reconcile
treats as a first-ever activation: it records the current inbox as already-seen,
advances the cursor, and surfaces NOTHING — deliberately, so activation never
replays a live session's backlog (constraint 4).

⇒ **Deleting a live session's HWM SILENTLY SWALLOWS every DM sitting un-surfaced
in its inbox at that moment, permanently.** Not a duplicate — that is bug
`59f355e0`, the DM-loss bug this whole file family was built to fix, re-created
for that session.

⇒ **The live-set gate is CORRECTNESS-CRITICAL, not politeness.** It is the only
thing standing between this janitor and the defect it is tidying up after.

⇒ The "safer than hold files" argument is RETIRED. These are safer in KIND
(regenerable, no hand-written cargo) but the failure is SILENT, and a silent
failure is not a lesser one: a reaped hold loses a note someone can see is
missing; a reaped live HWM loses a DM nobody ever knew arrived.

⚠️ The 7-day window (Rick's ruling, 2026-07-26) was chosen against the OLD
duplicate-DM framing. A shorter window leaves a live-but-unlisted session more
likely to still be inside it, so window length and live-set reliability trade
against each other on a worse axis than was presented. Re-raised with Rick; this
module follows whatever he last ruled and does not quietly re-tune itself.

⇒ And it is exactly why `live_session_ids is None` keeps EVERYTHING rather than
degrading to age-only: a transient live-set failure must never be able to eat
DMs.

Venue: pure filesystem + mtime. No network, no DB, no container.
"""
import time
from pathlib import Path

from heartbeat_hold import _iter_hold_paths, _file_mtime, _resolve_base_dir
from heartbeat_hold import DEFAULT_SWEEP_MAX_DEPTH, SWEEP_SKIP_DIR_NAMES

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

    The sid8 is the FILENAME's business here — an HWM body carries no session_id,
    which is precisely why the hold classifier's live gate cannot work on this
    family.

    ⚠️ It is a `[:8]` TRUNCATION of whatever `_hwm_path` was handed
    (`dm_inbox_reconcile.py:167`), NOT a guaranteed 8-char hex string. A real file
    in the repo root today is `.dm-inbox-hwm-stable-s.json`. Any gate built on
    this must compare 8-char prefixes on both sides, must never assume hex, never
    parse, and never raise on a surprising value.

    Requires:
        - path is a Path or str

    Ensures:
        - returns the fragment between the family prefix and the .json suffix
        - returns None when the name does not belong to this family, so a caller
          cannot silently treat a foreign file as a zero-length session id
        - never raises
    """
    name = Path( path ).name
    if not name.startswith( HWM_PREFIX ) or not name.endswith( HWM_SUFFIX ):
        return None
    sid8 = name[ len( HWM_PREFIX ) : -len( HWM_SUFFIX ) ]
    return sid8 or None


def _live_prefixes( live_session_ids ):
    """
    Normalize an authoritative live-set to the 8-char prefixes an HWM name carries.

    ⚠️ THE TRUNCATION IS NOT INJECTIVE, AND THIS GATE DEPENDS ON THAT BEING SAFE.
    Distinct session ids can share an 8-char prefix — four literals in this repo
    truncate to `stable-s` alone (María, 2026-07-26). Comparing PREFIXES rather
    than full ids therefore over-matches, and the over-match is the safe
    direction: a collision makes MORE files look live, so the gate KEEPS more. It
    can never make a live session's file look dead.

    ⇒ Do NOT "fix" this into a full-id comparison. Widening the key to full ids
    would make every truncated filename fail to match any live id, and the gate
    would start reaping live sessions' cursors. The lossy key is load-bearing.

    Requires:
        - live_session_ids is an iterable of session-id strings

    Ensures:
        - returns a set of `[:8]` prefixes, so a full uuid in the live set matches
          the truncated fragment in a filename
        - skips non-string / empty entries rather than raising
    """
    out = set()
    for sid in live_session_ids:
        if isinstance( sid, str ) and sid:
            out.add( sid[ :8 ] )
    return out


def classify_hwm_file( path, now_ts=None, grace_seconds=DEFAULT_HWM_GRACE_SECONDS,
                       live_session_ids=None ):
    """
    Decide KEEP vs PRUNABLE for one HWM file — the single rule both the report and
    the reclaim share, so the dry-run evidence cannot drift from the act.

    A file is PRUNABLE iff ALL of:
      - an AUTHORITATIVE live-set was supplied (not None), AND
      - its filename sid8 is ABSENT from that set, AND
      - its mtime age is >= grace_seconds.

    BIAS-TO-KEEP, and the ordering is deliberate: a None live-set keeps EVERYTHING
    regardless of age. An empty live set must never read as "nothing is alive" —
    that inversion is how a janitor reaps the fleet it was meant to tidy up after.
    The caller passes a non-None set ONLY when it has genuinely enumerated live
    sessions.

    mtime is the ONLY clock an HWM file has (no held_at, no ttl_seconds), so an
    unreadable mtime is not-provable-age and therefore KEEP.

    Requires:
        - path is a Path; now_ts is a POSIX timestamp (float) or None
        - grace_seconds >= 0; live_session_ids is an iterable or None

    Ensures:
        - returns a row dict: path / verdict / reason / sid8 / mtime_age_seconds
        - deletes nothing; never raises
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
    Dry-run triage over the HWM family — classify, tally, delete NOTHING.

    Its `prunable` count is a PREDICTION of what sweep_and_reclaim_hwm_files would
    delete under the same clock and the same live-set. If the two ever disagree,
    the disagreement is itself the finding — the same auditable pairing the hold
    janitor uses.

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
    Delete the HWM files classify_hwm_file proves are orphaned AND aged.

    Requires:
        - same contract as report_hwm_files

    Ensures:
        - deletes ONLY files whose verdict is PRUNABLE under this exact clock and
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
