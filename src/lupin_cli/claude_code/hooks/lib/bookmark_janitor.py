"""
Liveness-based expiry for session BOOKMARK files — row bd5c27e1.

WHAT THESE FILES ARE (read before deciding anything here is disposable)
----------------------------------------------------------------------
A session "bookmark" is a per-session high-water mark / ledger co-located with the
heartbeat hold+acked family in `fleet_data_root()`. Each records what one session
has already processed, keyed on the session id IN THE FILENAME (the body carries no
session_id). They are the OPPOSITE of ephemeral — surviving `/clear` is the point —
which is why they do NOT follow holds/mementos to /tmp.

This module owns the THREE milder families. The fourth — `.dm-inbox-hwm-*` — keeps
its own proven, already-wired janitor (`dm_inbox_hwm_janitor.py`) because deleting a
live one SILENTLY SWALLOWS DMs (bug `59f355e0`); that correctness-critical path is
left untouched here. Folding all four onto this one mechanism is a clean follow-up
once this is proven in production.

    family                 delete-a-LIVE-one failure mode      writer
    .ask-answer-hwm-*       benign DUPLICATE (re-surfaces owed)  answer_catchup.py
    .task-store-map-*       regenerable (recreated on next need) task_store_map.py
    .heartbeat-acked-*      regenerable (recreated on next need) heartbeat_acked_ledger.py

All three are strictly milder than dm-inbox's silent loss — but the live-set gate
still protects every one of them: a live session's bookmark is NEVER reaped, at any
age. The gate is the only thing standing between this janitor and the mess it tidies.

THE RULES, INHERITED FROM THE PROVEN dm-inbox JANITOR (do not weaken)
--------------------------------------------------------------------
  * LIVE GATE FIRST, BIAS TO KEEP. `live_session_ids is None` keeps EVERYTHING,
    regardless of age: a transient live-set enumeration failure must never eat a
    bookmark. An empty-but-authoritative set is different from a failed one — the
    caller passes non-None ONLY when it genuinely enumerated live sessions.
  * CLASSIFY BY SESSION ID, NEVER PER-FILE MTIME. A live session can hold a stale
    ledger of one family beside a current one of another; a per-file rule reaps the
    first and breaks it. The session id is the unit of liveness.
  * COMPARE [:8] PREFIXES. The dm-inbox names truncate the id to 8 chars; these
    three carry the full id. An [:8] prefix of a full id still matches an [:8] live
    prefix, and the truncation OVER-matches (a prefix collision makes MORE files
    look live → KEEPS more). Over-match is the safe direction; do not "fix" it into
    a full-id compare, which would make a truncated peer name miss every live id.
  * NEGATIVE / UNREADABLE AGE = NOT-PROVABLE-AGE = KEEP. A future mtime (clock skew,
    restored backup) is not evidence of youth; it means mtime cannot be read as a
    clock, so it is trusted in NEITHER direction.
  * SENTINEL NAMES = KEEP. A filename whose fragment is a non-session sentinel
    (`unknown` from the acked empty-id fallback; `stable-s` for the persistent
    pseudo-session) has no owning session to be dead — never reaped, typed reason.

⚠️ Grace window: 7 days, uniform with dm-inbox (Rick's ruling 2026-07-26, sibling row
`8758d0b1`; confirmed applicable here by Cheech 2026-08-16 — these families' failure
modes are strictly milder than the dm-inbox loss that window was chosen against). With
a real bridge-file live set the age arm is only a backstop; the live gate does the work.

Venue: pure filesystem + mtime. No network, no DB, no container.
"""
import time
from dataclasses import dataclass, field
from pathlib import Path

# FULL package path (see dm_inbox_hwm_janitor for why a bare import breaks arbiter
# collection): the arbiter imports this by package path in production.
from lupin_cli.claude_code.hooks.lib.heartbeat_hold import (
    _iter_hold_paths, _file_mtime, _resolve_base_dir,
    DEFAULT_SWEEP_MAX_DEPTH, SWEEP_SKIP_DIR_NAMES,
)

# 7 days — uniform with the dm-inbox sibling (Rick 2026-07-26; confirmed here by
# Cheech 2026-08-16). A shorter window trades against live-set reliability.
DEFAULT_BOOKMARK_GRACE_SECONDS = 7 * 24 * 60 * 60

VERDICT_KEEP     = "keep"
VERDICT_PRUNABLE = "prunable"

PRUNE_ORPHANED_AND_AGED = "orphaned_and_aged"

KEEP_LIVE_SESSION    = "live_session"
KEEP_NO_LIVE_SET     = "no_authoritative_live_set"
KEEP_TOO_YOUNG       = "within_grace_window"
KEEP_NO_PROVABLE_AGE = "no_provable_age"
KEEP_UNPARSEABLE     = "unparseable_name"      # not this family, or a non-session sentinel


@dataclass( frozen=True )
class BookmarkFamily:
    """
    One bookmark family's naming, so classify/report/sweep share ONE rule across all
    three families instead of three copy-paste modules that can drift.

    Requires:
        - prefix / suffix bracket the session-id fragment in the filename
        - sentinel_ids are filename fragments that name NO session (never reaped)

    Ensures:
        - glob is prefix + "*" + suffix, scoped so a loose match cannot reach a
          neighbouring family (e.g. `.heartbeat-acked-*` never catches
          `.heartbeat-hold-*`)
    """
    name         : str
    prefix       : str
    suffix       : str = ".json"
    sentinel_ids : frozenset = field( default_factory=frozenset )

    @property
    def glob( self ):
        return self.prefix + "*" + self.suffix


# ── The three families this module owns. `.heartbeat-hold-*` is DELIBERATELY ABSENT
# ── — those move to /tmp in a separate Phase 1; the acked prefix is distinct from
# ── the hold prefix, so this glob never reaches them.
FAMILY_ASK_ANSWER     = BookmarkFamily( "ask_answer",     ".ask-answer-hwm-" )
FAMILY_TASK_STORE_MAP = BookmarkFamily( "task_store_map", ".task-store-map-" )
FAMILY_HEARTBEAT_ACKED = BookmarkFamily(
    "heartbeat_acked", ".heartbeat-acked-", sentinel_ids=frozenset( { "unknown" } ) )

BOOKMARK_FAMILIES = ( FAMILY_ASK_ANSWER, FAMILY_TASK_STORE_MAP, FAMILY_HEARTBEAT_ACKED )


def family_session_fragment( path, family ):
    """
    Extract the session-id fragment a bookmark filename encodes for `family`.

    The body carries no session_id — the fragment is the filename's business, exactly
    as for the dm-inbox sibling.

    Requires:
        - path is a Path or str; family is a BookmarkFamily

    Ensures:
        - returns the fragment between family.prefix and family.suffix
        - returns None when the name is not this family's, so a caller cannot treat
          a foreign file as a zero-length session id
        - never raises
    """
    name = Path( path ).name
    if not name.startswith( family.prefix ) or not name.endswith( family.suffix ):
        return None
    frag = name[ len( family.prefix ) : -len( family.suffix ) ]
    return frag or None


def _live_prefixes( live_session_ids ):
    """
    Normalize an authoritative live-set to the 8-char prefixes a bookmark name carries.

    The [:8] truncation is NOT injective, and the gate depends on that being safe: a
    prefix collision makes MORE files look live, which only ever KEEPS more. Widening
    to a full-id compare would make a truncated peer filename miss every live id and
    start reaping live cursors — the lossy key is load-bearing.

    Requires:
        - live_session_ids is an iterable of session-id strings

    Ensures:
        - returns a set of [:8] prefixes; skips non-string / empty entries
    """
    out = set()
    for sid in live_session_ids:
        if isinstance( sid, str ) and sid:
            out.add( sid[ :8 ] )
    return out


def classify_bookmark_file( path, family, now_ts=None,
                            grace_seconds=DEFAULT_BOOKMARK_GRACE_SECONDS,
                            live_session_ids=None ):
    """
    Decide KEEP vs PRUNABLE for one bookmark file — the single rule report and sweep
    share, so the dry-run evidence cannot drift from the act.

    A file is PRUNABLE iff ALL of:
      - an AUTHORITATIVE live-set was supplied (not None), AND
      - its filename fragment is not a sentinel, AND
      - its [:8] prefix is ABSENT from the live set, AND
      - its mtime age is >= grace_seconds.

    BIAS-TO-KEEP, ordering deliberate: a None live-set keeps EVERYTHING regardless of
    age; an empty set must never read as "nothing is alive". mtime is the ONLY clock a
    bookmark has, so an unreadable/future mtime is not-provable-age → KEEP.

    Requires:
        - path is a Path; family is a BookmarkFamily
        - now_ts is a POSIX timestamp (float) or None; grace_seconds >= 0
        - live_session_ids is an iterable or None

    Ensures:
        - returns a row dict: path / family / verdict / reason / sid / mtime_age_seconds
        - deletes nothing; never raises
    """
    if now_ts is None:
        now_ts = time.time()

    row = {
        "path"              : str( path ),
        "family"            : family.name,
        "verdict"           : VERDICT_KEEP,
        "reason"            : KEEP_UNPARSEABLE,
        "sid"               : None,
        "mtime_age_seconds" : None,
    }

    frag = family_session_fragment( path, family )
    if frag is None or frag in family.sentinel_ids:
        return row                                     # not ours / sentinel → KEEP, typed
    row[ "sid" ] = frag

    mtime = _file_mtime( path )
    if mtime is not None:
        row[ "mtime_age_seconds" ] = now_ts - mtime

    # Live gate FIRST — load-bearing; at a 7-day window it does more work than age.
    if live_session_ids is None:
        row[ "reason" ] = KEEP_NO_LIVE_SET
        return row
    if frag[ :8 ] in _live_prefixes( live_session_ids ):
        row[ "reason" ] = KEEP_LIVE_SESSION
        return row                                     # live session → never reap, any age

    age = row[ "mtime_age_seconds" ]
    # Negative age = future mtime = clock not readable as a clock → trust neither way.
    if age is None or age < 0:
        row[ "reason" ] = KEEP_NO_PROVABLE_AGE
        return row
    if age < grace_seconds:
        row[ "reason" ] = KEEP_TOO_YOUNG
        return row

    row[ "verdict" ] = VERDICT_PRUNABLE
    row[ "reason" ]  = PRUNE_ORPHANED_AND_AGED
    return row


def _families_arg( families ):
    """Normalize the families argument to a tuple; None → all three owned families."""
    return tuple( families ) if families is not None else BOOKMARK_FAMILIES


def report_bookmark_files( base_dir=None, base_dirs=None, now_ts=None,
                           grace_seconds=DEFAULT_BOOKMARK_GRACE_SECONDS,
                           live_session_ids=None, families=None,
                           max_depth=DEFAULT_SWEEP_MAX_DEPTH,
                           skip_dir_names=SWEEP_SKIP_DIR_NAMES ):
    """
    Dry-run triage across the owned families — classify, tally, delete NOTHING.

    Its `prunable` count is a PREDICTION of what sweep_and_reclaim_bookmark_files
    would delete under the same clock and live-set; a disagreement is itself the
    finding, the same auditable pairing the dm-inbox janitor uses.

    Requires:
        - traversal args match _iter_hold_paths' contract
        - now_ts is a POSIX timestamp or None; grace_seconds >= 0

    Ensures:
        - returns { roots_requested, roots_swept, roots_unreachable,
                    skipped_dirs_with_holds, files_found, counts, rows, deleted }
          with deleted always 0
        - counts carries prunable / keep, a kept-reason histogram, and per-family tallies
        - never raises
    """
    if now_ts is None:
        now_ts = time.time()
    fams = _families_arg( families )

    requested = list( base_dirs ) if base_dirs is not None else [ str( _resolve_base_dir( base_dir ) ) ]

    rows            = [ ]
    roots_all       = [ ]
    unreachable_all = [ ]
    skipped_all     = [ ]
    files_found     = 0
    for family in fams:
        roots, unreachable, paths, skipped = _iter_hold_paths(
            base_dir=base_dir, base_dirs=base_dirs, max_depth=max_depth,
            skip_dir_names=skip_dir_names, glob_pat=family.glob
        )
        roots_all       = roots            # identical across families (same traversal)
        unreachable_all = unreachable
        skipped_all     = skipped
        files_found    += len( paths )
        rows.extend( classify_bookmark_file( p, family, now_ts=now_ts,
                                             grace_seconds=grace_seconds,
                                             live_session_ids=live_session_ids )
                     for p in paths )

    reasons     = { }
    per_family  = { }
    for r in rows:
        per_family.setdefault( r[ "family" ], { "prunable": 0, "keep": 0 } )
        if r[ "verdict" ] == VERDICT_KEEP:
            reasons[ r[ "reason" ] ] = reasons.get( r[ "reason" ], 0 ) + 1
            per_family[ r[ "family" ] ][ "keep" ] += 1
        else:
            per_family[ r[ "family" ] ][ "prunable" ] += 1

    return {
        "roots_requested"         : [ str( r ) for r in requested ],
        "roots_swept"             : roots_all,
        "roots_unreachable"       : unreachable_all,
        "skipped_dirs_with_holds" : skipped_all,
        "files_found"             : files_found,
        "counts"                  : {
            "prunable"                   : sum( 1 for r in rows if r[ "verdict" ] == VERDICT_PRUNABLE ),
            "keep"                       : sum( 1 for r in rows if r[ "verdict" ] == VERDICT_KEEP ),
            "reachable_but_kept_reasons" : reasons,
            "per_family"                 : per_family,
        },
        "rows"                    : rows,
        "deleted"                 : 0,
    }


def sweep_and_reclaim_bookmark_files( base_dir=None, base_dirs=None, now_ts=None,
                                      grace_seconds=DEFAULT_BOOKMARK_GRACE_SECONDS,
                                      live_session_ids=None, families=None,
                                      max_depth=DEFAULT_SWEEP_MAX_DEPTH,
                                      skip_dir_names=SWEEP_SKIP_DIR_NAMES ):
    """
    Delete the bookmark files classify_bookmark_file proves are orphaned AND aged.

    Requires:
        - same contract as report_bookmark_files

    Ensures:
        - deletes ONLY files whose verdict is PRUNABLE under this exact clock and
          live-set; returns the sorted list of deleted paths (strings)
        - a per-file OSError (racing delete) skips that file; never raises
    """
    if now_ts is None:
        now_ts = time.time()
    fams = _families_arg( families )

    pruned = [ ]
    for family in fams:
        _roots, _unreachable, paths, _skipped = _iter_hold_paths(
            base_dir=base_dir, base_dirs=base_dirs, max_depth=max_depth,
            skip_dir_names=skip_dir_names, glob_pat=family.glob
        )
        for path in paths:
            row = classify_bookmark_file( path, family, now_ts=now_ts,
                                          grace_seconds=grace_seconds,
                                          live_session_ids=live_session_ids )
            if row[ "verdict" ] != VERDICT_PRUNABLE:
                continue
            try:
                path.unlink()
                pruned.append( str( path ) )
            except OSError:
                pass                                   # racing delete → fine
    return sorted( pruned )
