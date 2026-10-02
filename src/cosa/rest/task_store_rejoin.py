"""
Rejoin blocked task rows whose blockers are all done, and refuse to rejoin dropped ones.

`blocker_is_terminal` in `src/cosa/rest/task_store_owed.py` only flags a stranded row.
This module acts on the done half of that split and leaves the dropped half alone.

    blocker `done`    -> rejoin. The precondition happened, so no judgment call is left.
    blocker `dropped` -> flag only. Dropping was a decision, and a rejoin would overturn it.

The dropped arm never rejoins here. Transposing the two arms would silently overturn
human decisions, so a negative-control test pins the split.

Park expiry is a read-time predicate. The rejoin is a write because it must leave a
dormancy stamp in the row body. A row that rejoins after weeks otherwise reads as freshly
vetted, even when its premises went false while it waited. A derived boolean cannot carry
that warning to the next reader. The caller is `src/scripts/rejoin-done-blocked-rows.py`,
which is dry-run by default.

This instrument errs toward not rejoining, the opposite polarity of `blocker_is_terminal`.
A false hold leaves a row where the defect already left it. A false rejoin puts a row that
is waiting on a human in front of a seat that will work it.

An unresolvable canonical blocker id is flagged by `blocker_is_terminal` but never rejoined
here. A flag says the edge is dead, while a rejoin says the precondition happened, and an
absent row never happened. Such a row is a finding for a human.

The stamp cannot say what moved under the row while it waited, because no field holds that.
It says so in its own text and points the reader at the blocker's closing receipts.
"""

from datetime import datetime, timezone

from cosa.rest.task_store_rules import BLOCKED_STATUS, TERMINAL_STATUSES


# The one status a blocker may hold for the row to rejoin. Named rather than inlined so
# the done/dropped split is greppable — the two arms differ by this constant alone, and
# a transposition here IS the failure mode the negative control exists to catch.
REJOIN_BLOCKER_STATUS = "done"

# Verdicts. `rejoin` is the only one that licenses a write; every other value is a HOLD
# carrying the reason it held, so the caller reports WHY a stranded row was left alone
# instead of printing an unexplained silence.
VERDICT_REJOIN = "rejoin"

HOLD_NOT_BLOCKED        = "not_blocked"
HOLD_NO_ITEM_BLOCKER    = "no_item_blocker"
HOLD_NON_ITEM_BLOCKER   = "non_item_blocker"
HOLD_UNRESOLVED_BLOCKER = "unresolved_blocker"
HOLD_DROPPED_BLOCKER    = "dropped_blocker"
HOLD_LIVE_BLOCKER       = "live_blocker"

__all__ = [
    "REJOIN_BLOCKER_STATUS",
    "VERDICT_REJOIN",
    "HOLD_NOT_BLOCKED",
    "HOLD_NO_ITEM_BLOCKER",
    "HOLD_NON_ITEM_BLOCKER",
    "HOLD_UNRESOLVED_BLOCKER",
    "HOLD_DROPPED_BLOCKER",
    "HOLD_LIVE_BLOCKER",
    "classify_blocked_row",
    "dormancy_days",
    "dormancy_stamp",
    "scope_disclosure",
]

assert REJOIN_BLOCKER_STATUS in TERMINAL_STATUSES, (
    f"'{REJOIN_BLOCKER_STATUS}' must be TERMINAL — the done arm rejoins a row whose "
    f"precondition can never move again; a non-terminal blocker is a LIVE wait"
)


def _parse_ts( value ):
    """
    An ISO-8601 string or datetime as a UTC-aware datetime, else None.

    Requires:
        - value is any object

    Ensures:
        - a datetime returns UTC-aware (naive is interpreted as UTC)
        - an ISO-8601 string (trailing 'Z' accepted) returns UTC-aware
        - anything else — None, junk, unparseable text — returns None
        - never raises
    """
    if isinstance( value, datetime ):
        parsed = value
    elif isinstance( value, str ):
        try:
            parsed = datetime.fromisoformat( value.strip().replace( "Z", "+00:00" ) )
        except ValueError:
            return None
    else:
        return None

    return parsed.replace( tzinfo=timezone.utc ) if parsed.tzinfo is None else parsed


def classify_blocked_row( status, blocked_by, status_by_id ):
    """
    Decide whether one blocked row's wait is over, which is the done-arm predicate.

    Every blocker must be an item, looked up, and `done`. Any other shape holds, because a
    rejoin asserts that every named precondition happened. Persona and user blockers hold,
    though `item_blocker_ids` drops them when flagging.

    Requires:
        - status is the row's status string (any value accepted)
        - blocked_by is the row's blocked_by value (any type; non-list holds)
        - status_by_id maps blocker-id str -> status str, with an explicit None for an id
          that was looked up and not found, as `TaskRepository.statuses_for_ids` answers
        - a key absent from the map was never looked up

    Ensures:
        - returns { "verdict": str|None, "reason": str|None, "closed_blocker_ids": [str] }
        - verdict is VERDICT_REJOIN, with reason None, only when status == BLOCKED_STATUS, blocked_by
          holds at least one entry, every entry is {kind:"item"} with a str id, every id is present
          in status_by_id, and every resolved status == REJOIN_BLOCKER_STATUS
        - every other case is a hold: verdict is None and reason carries the HOLD_ value
        - status != BLOCKED_STATUS         -> HOLD_NOT_BLOCKED
        - no blockers at all               -> HOLD_NO_ITEM_BLOCKER
        - any persona/user/malformed entry -> HOLD_NON_ITEM_BLOCKER
        - any id absent from the map, or present as None -> HOLD_UNRESOLVED_BLOCKER
          (an absent row never happened; see the module docstring)
        - any blocker in a terminal status other than done (dropped or wont_fix)
                                           -> HOLD_DROPPED_BLOCKER (never rejoined here)
        - any blocker non-terminal         -> HOLD_LIVE_BLOCKER (a genuine wait)
        - one done + one dropped           -> HOLD_DROPPED_BLOCKER (dropped dominates)
        - the hold reason is order-independent: several disqualifying blockers report the
          same reason in any order, by the precedence non-item > dropped > unresolved > live
        - closed_blocker_ids lists the done blockers seen, in list order, on every verdict
        - never raises
    """
    if status != BLOCKED_STATUS:
        return { "verdict": None, "reason": HOLD_NOT_BLOCKED, "closed_blocker_ids": [ ] }

    if not isinstance( blocked_by, list ) or not blocked_by:
        return { "verdict": None, "reason": HOLD_NO_ITEM_BLOCKER, "closed_blocker_ids": [ ] }

    closed = [ ]
    seen   = set()

    for ref in blocked_by:
        if not isinstance( ref, dict ) or ref.get( "kind" ) != "item":
            seen.add( HOLD_NON_ITEM_BLOCKER )
            continue

        ref_id = ref.get( "id" )
        if not isinstance( ref_id, str ) or not ref_id:
            seen.add( HOLD_NON_ITEM_BLOCKER )
            continue

        if ref_id not in status_by_id:
            seen.add( HOLD_UNRESOLVED_BLOCKER )
            continue

        blocker_status = status_by_id[ ref_id ]
        if blocker_status == REJOIN_BLOCKER_STATUS:  closed.append( ref_id )
        elif blocker_status is None:                 seen.add( HOLD_UNRESOLVED_BLOCKER )
        elif blocker_status in TERMINAL_STATUSES:    seen.add( HOLD_DROPPED_BLOCKER )
        else:                                        seen.add( HOLD_LIVE_BLOCKER )

    # Fixed precedence, most-disqualifying first. `dropped` outranks `unresolved` and
    # `live` because it is the one arm a human deliberately ruled; `non_item` outranks
    # everything because it means the row's real blocker was never examined at all.
    for reason in ( HOLD_NON_ITEM_BLOCKER, HOLD_DROPPED_BLOCKER, HOLD_UNRESOLVED_BLOCKER, HOLD_LIVE_BLOCKER ):
        if reason in seen:
            return { "verdict": None, "reason": reason, "closed_blocker_ids": closed }

    return { "verdict": VERDICT_REJOIN, "reason": None, "closed_blocker_ids": closed }


def dormancy_days( closed_at, now ):
    """
    Count the whole days a row sat stranded, from its blocker's close to `now`.

    Requires:
        - closed_at is an ISO-8601 string, a datetime, or None (the blocker's close time)
        - now is the comparison instant as a datetime, never defaulted, because this module
          reads no clock (the caller resolves it, as with `park_is_active`); a naive `now`
          is interpreted as UTC

    Ensures:
        - returns a non-negative int, or None when closed_at is missing/unparseable
        - truncates toward zero: a row stranded 47 hours reports 1 day, not 2
        - a closed_at in the future (clock skew) returns 0, never a negative count
        - never raises
    """
    closed_ts = _parse_ts( closed_at )
    if closed_ts is None: return None

    comparison_now = now.replace( tzinfo=timezone.utc ) if now.tzinfo is None else now

    elapsed = ( comparison_now - closed_ts ).total_seconds()
    return max( 0, int( elapsed // 86400 ) )


def dormancy_stamp( closed_blockers, now ):
    """
    Build the amendment text that marks a rejoined row as not freshly vetted.

    A row that rejoins after weeks reads as freshly vetted, even when its premises went
    false while it waited. The stamp reports the dormancy and the blockers, and says the
    premise is unverified. It cannot say what moved, since no field holds that.

    Requires:
        - closed_blockers is a list of { "id": str, "closed_at": <iso|datetime|None> }
        - now is the comparison instant as a datetime (naive interpreted as UTC)

    Ensures:
        - returns a non-empty str suitable as a `task_amend` note
        - the headline dormancy is measured from the latest close, the instant the row
          actually became free
        - the headline is the minimum of the per-blocker spans, the shortest true wait
          across the blockers, so a multi-blocker row is not inflated
        - every blocker's own span is listed underneath, so the headline never hides them
        - a blocker whose close time is unparseable is listed with "close time unknown"
          rather than dropped or defaulted to zero days
        - states, unprompted, that the premise is unverified and not computed
        - never raises
    """
    lines = [ ]
    spans = [ ]

    for blocker in closed_blockers:
        blocker_id = blocker.get( "id" )
        days       = dormancy_days( blocker.get( "closed_at" ), now )
        if days is None:
            lines.append( f"  · blocker {blocker_id} closed `done` — close time unknown" )
        else:
            spans.append( days )
            lines.append( f"  · blocker {blocker_id} closed `done` {days}d ago" )

    dormancy = f"{min( spans )}d" if spans else "unknown"

    return (
        f"AUTO-REJOINED — this row's blockers are all `done`, so its wait was over and it "
        f"was still reading as blocked (store row 00a6bde2, item 3, the mechanical arm).\n"
        f"\n"
        f"DORMANCY: {dormancy} — the row sat stranded that long after its last blocker closed.\n"
        + "\n".join( lines ) + "\n"
        f"\n"
        f"⚠️ THIS ROW IS NOT FRESHLY VETTED. What moved underneath it while it waited is NOT "
        f"computed and cannot be — no field carries it. Two of the first three rows rejoined "
        f"by hand had premises that had already gone false, and both read as ready. BEFORE "
        f"WORKING THIS ROW, read the closing receipts of the blocker(s) named above and "
        f"confirm this body still describes the world."
    )


def scope_disclosure( counts ):
    """
    Describe what the rejoin pass did and which rows it left alone.

    The report is required output. A pass that prints "3 rejoined" reads as "the stranded
    rows are handled" while every dropped-blocked and unresolvable row is still untouched.

    Requires:
        - counts is a dict of the pass's tallies (missing keys read as 0)

    Ensures:
        - returns a multi-line str naming the examined set, each hold bucket, and both
          out-of-scope arms (the dropped arm awaiting a human ruling; the persona and
          prose arms this pass cannot see at all)
        - never raises
    """
    def tally( key ): return counts.get( key, 0 )

    return (
        f"SCOPE OF THIS PASS — read before treating a clean run as 'no stranded rows':\n"
        f"  examined                    : {tally( 'examined' )} blocked rows\n"
        f"  REJOINED (all blockers done): {tally( VERDICT_REJOIN )}\n"
        f"  held, a blocker was dropped : {tally( HOLD_DROPPED_BLOCKER )}  <- Rick's ruling, NEVER auto-rejoined\n"
        f"  held, a blocker is live     : {tally( HOLD_LIVE_BLOCKER )}  (a genuine wait)\n"
        f"  held, a blocker unresolvable: {tally( HOLD_UNRESOLVED_BLOCKER )}  (dead or prefix-spelled edge — a finding for a human)\n"
        f"  held, persona/user blocker  : {tally( HOLD_NON_ITEM_BLOCKER )}  (no registry exists to resolve one)\n"
        f"  held, no blocker at all     : {tally( HOLD_NO_ITEM_BLOCKER )}  (blocked with an empty edge — a different defect)\n"
        f"\n"
        f"NOT COVERED BY THIS PASS:\n"
        f"  · the `dropped` arm — flagged by blocker_terminal, disposition is Rick's alone.\n"
        f"  · rows citing a dead precondition in PROSE with no edge — that is the item-4\n"
        f"    scanner (src/scripts/scan-prose-task-refs.py), a separate instrument.\n"
        f"  · persona edges — no persona lifecycle exists to resolve them against.\n"
    )


def quick_smoke_test():
    """
    Run the positive and negative cases for both arms and print the results.

    A run that only covers the happy path cannot tell a working rejoin from one that
    rejoins every row.
    """
    import cosa.utils.util as du

    du.print_banner( "task_store_rejoin — done-arm rejoin smoke test", prepend_nl=True )

    done_id    = "11111111-1111-4111-8111-111111111111"
    dropped_id = "22222222-2222-4222-8222-222222222222"
    statuses   = { done_id: "done", dropped_id: "dropped" }
    now        = datetime( 2026, 7, 26, 12, 0, 0, tzinfo=timezone.utc )

    positive = classify_blocked_row( BLOCKED_STATUS, [ { "kind": "item", "id": done_id } ], statuses )
    negative = classify_blocked_row( BLOCKED_STATUS, [ { "kind": "item", "id": dropped_id } ], statuses )
    persona  = classify_blocked_row( BLOCKED_STATUS, [ { "kind": "persona", "id": "sam" } ], statuses )

    print( f"✓ done blocker      : {positive[ 'verdict' ]} (expected 'rejoin')" )
    print( f"✓ dropped blocker   : {negative[ 'reason' ]} (expected '{HOLD_DROPPED_BLOCKER}' — Rick's arm)" )
    print( f"✓ persona blocker   : {persona[ 'reason' ]} (expected '{HOLD_NON_ITEM_BLOCKER}')" )
    print( f"✓ dormancy          : {dormancy_days( '2026-07-19T12:00:00Z', now )}d (expected 7)" )
    print()
    print( dormancy_stamp( [ { "id": done_id, "closed_at": "2026-07-19T12:00:00Z" } ], now ) )
    print()
    print( scope_disclosure( { "examined": 3, VERDICT_REJOIN: 1,
                               HOLD_DROPPED_BLOCKER: 1, HOLD_NON_ITEM_BLOCKER: 1 } ) )


if __name__ == "__main__":
    quick_smoke_test()
