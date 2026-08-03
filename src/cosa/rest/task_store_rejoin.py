"""
Task-store DONE-ARM REJOIN — store row 00a6bde2, item 3.

WHAT THIS IS FOR
----------------
`blocker_is_terminal` (task_store_owed) made a stranded row VISIBLE and stopped there:
advisory, changes no owed-ness, transitions nothing. Row 00a6bde2 §2 then split the
disposition, and the split is the whole reason this module can exist at all:

    blocker `done`    -> AUTO-REJOIN. The precondition ACTUALLY HAPPENED; the row should
                         have rejoined the moment it did. No judgment call exists — it is
                         LOST WORK waiting on nothing. MECHANICAL, ships without a gate.
    blocker `dropped` -> FLAG ONLY. Dropping was a DECISION, and a silent rejoin would
                         overturn it. Rick's ruling, and ONLY there.

This module implements the DONE arm and refuses to touch the other one. `dropped` never
rejoins here, and the negative control that proves it is a required test, not a nicety —
if the two arms are ever transposed, this code starts overturning human decisions
silently, which is strictly worse than the defect it was built to fix.

WHY THIS IS A WRITE WHEN PARK-EXPIRY IS A READ (a deliberate divergence — record 00a6bde2)
------------------------------------------------------------------------------------------
Park expiry is computed at READ time and never written back: arithmetic on two values
already on the row, so a predicate suffices and no daemon can rot. The rejoin cannot copy
that shape, for one reason that is not a matter of taste:

    THE DORMANCY STAMP IS THE POINT, AND A READ-TIME PREDICATE CANNOT STAMP ANYTHING.

§3 of the row measured this: María rejoined three rows by hand (dormancy 4 / 7 / 10 days)
and the marker EARNED ITSELF ON TWO OF THE THREE IMMEDIATELY — both had premises that had
gone false while they waited, and BOTH WOULD HAVE READ AS READY. The failure being fixed
is not that the row stayed blocked; it is that A RESURRECTED ROW READS AS FRESHLY-VETTED.
A derived boolean cannot carry that warning into the body where the next reader meets it.

So: a write, with a durable stamp, driven by a caller (`src/scripts/rejoin-done-blocked-rows.py`)
that is DRY-RUN BY DEFAULT.

⚠️ WHICH WAY THIS INSTRUMENT LIES: toward NOT REJOINING — the OPPOSITE polarity from
`blocker_is_terminal`, and for the same underlying reason. That predicate lies toward
not-flagged because a false flag defames a correct row. This lies toward not-rejoining
because a rejoin is a WRITE that moves a row into the workable set where a seat will pick
it up. A false HOLD leaves a row exactly where the defect already left it (recoverable,
and the very state this fixes). A false REJOIN puts a row genuinely waiting on a human in
front of someone who will work it. Both lie toward DOING NOTHING.

⚠️ ONE INTENTIONAL ASYMMETRY WITH ITEM 2 — READ BEFORE "FIXING" IT
------------------------------------------------------------------
`blocker_is_terminal` FLAGS a canonical blocker id that was looked up and NOT FOUND: on a
typed edge an unresolvable canonical id is unambiguously a dead reference. This module
does NOT rejoin on that same input, and the divergence is deliberate:

    FLAGGING says "this edge is dead — look at it."
    REJOINING says "the precondition HAPPENED."

An absent row never happened. A dead edge and a satisfied precondition are opposite facts,
and only one of them licenses an automatic unblock. A row whose blocker cannot be resolved
is a finding for a human (item 2 already surfaces it), never an input to this write.

WHAT IT STILL DOES NOT DO
-------------------------
The stamp names the dormancy and the blocker that closed. It CANNOT name "what moved
underneath the row while it waited" — that is not derivable from any field, and claiming
it would be the same false-green this row family is made of. The stamp therefore says so
in its own text and points the reader at the blocker's closing receipts.
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
    Decide whether ONE blocked row's wait is over — the done-arm predicate.

    EVERY blocker must be an ITEM, must have been LOOKED UP, and must be `done`. Any other
    shape holds. The conjunction is the safety property: a rejoin asserts that EVERY
    precondition this row named actually happened, and a partial answer cannot support that.

    THE NON-ITEM ARM HOLDS RATHER THAN BEING FILTERED OUT. `item_blocker_ids` drops
    persona/user refs for FLAGGING purposes, because neither has a resolvable lifecycle and
    scanning them would manufacture false findings. Here their presence is DISQUALIFYING,
    not ignorable: a `{kind:"persona"}` edge is a real wait on a real seat, and rejoining a
    row that still carries one would unblock work whose actual blocker was never examined.
    The unresolvable arm must stop the write, not be skipped past.

    Requires:
        - status is the row's status string (any value accepted)
        - blocked_by is the row's blocked_by value (any type; non-list holds)
        - status_by_id maps blocker-id str -> status str, with an explicit None for an id
          that was looked up and NOT FOUND, exactly as `TaskRepository.statuses_for_ids`
          answers. A key ABSENT from the map was never looked up.

    Ensures:
        - returns { "verdict": str, "reason": str|None, "closed_blocker_ids": [str] }
        - verdict is VERDICT_REJOIN only when status == BLOCKED_STATUS, blocked_by holds at
          least one entry, EVERY entry is {kind:"item"} with a str id, EVERY id is present
          in status_by_id, and EVERY resolved status == REJOIN_BLOCKER_STATUS
        - status != BLOCKED_STATUS         -> HOLD_NOT_BLOCKED
        - no blockers at all               -> HOLD_NO_ITEM_BLOCKER
        - any persona/user/malformed entry -> HOLD_NON_ITEM_BLOCKER
        - any id absent from the map, or present as None -> HOLD_UNRESOLVED_BLOCKER
          (an absent row never HAPPENED — see the module docstring's asymmetry note)
        - any blocker `dropped`            -> HOLD_DROPPED_BLOCKER (Rick's arm; never here)
        - any blocker non-terminal         -> HOLD_LIVE_BLOCKER (a genuine wait)
        - one done + one dropped           -> HOLD_DROPPED_BLOCKER (dropped DOMINATES)
        - THE HOLD REASON IS ORDER-INDEPENDENT. A row with several disqualifying blockers
          reports the same reason whichever order they sit in, by the fixed precedence
          non-item > dropped > unresolved > live. Short-circuiting on first sight would
          make the reported reason an artifact of list order, and a reason that changes
          when nothing about the row changed is not a reason a reader can act on.
        - closed_blocker_ids lists the done blockers seen, in list order, on EVERY verdict
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
    Whole days a row sat stranded — from its blocker's close to `now`.

    Requires:
        - closed_at is an ISO-8601 string, a datetime, or None (the blocker's close time)
        - now is the comparison instant as a datetime — REQUIRED, never defaulted (this
          module reads no clock; the caller resolves it at the boundary, matching
          `park_is_active`). A naive `now` is interpreted as UTC.

    Ensures:
        - returns a non-negative int, or None when closed_at is missing/unparseable
        - truncates toward zero: a row stranded 47 hours reports 1 day, not 2
        - a closed_at in the FUTURE (clock skew) returns 0, never a negative count
        - never raises
    """
    closed_ts = _parse_ts( closed_at )
    if closed_ts is None: return None

    comparison_now = now.replace( tzinfo=timezone.utc ) if now.tzinfo is None else now

    elapsed = ( comparison_now - closed_ts ).total_seconds()
    return max( 0, int( elapsed // 86400 ) )


def dormancy_stamp( closed_blockers, now ):
    """
    The amendment text a rejoined row carries — §3's marker, which is the load-bearing half.

    A ROW THAT REJOINS AFTER WEEKS READS AS FRESHLY-VETTED, and that is the actual defect
    §3 measured: two of María's three rejoins had premises that had already gone false, and
    both would have read as ready. The stamp exists to break that read.

    ⚠️ IT DOES NOT CLAIM WHAT MOVED. "What moved underneath the row while it waited" is not
    derivable from any field this store holds, and a stamp that implied otherwise would be
    the same instrument-answering-a-narrower-question shape the whole row family is about.
    It reports the dormancy and the blocker, then says plainly that the premise is
    UNVERIFIED and names where the reader must look.

    Requires:
        - closed_blockers is a list of { "id": str, "closed_at": <iso|datetime|None> }
        - now is the comparison instant as a datetime (naive interpreted as UTC)

    Ensures:
        - returns a non-empty str suitable as a `task_amend` note
        - the headline dormancy is measured from the LATEST close — the instant the row
          actually became free, since an earlier-closing blocker did not release it while
          a later one still gated it. That is the SHORTEST true wait across the blockers
          (hence `min` of the per-blocker spans), and reporting the longest instead would
          inflate the number on exactly the multi-blocker rows where it matters most
        - every blocker's own span is listed underneath, so the headline never hides them
        - a blocker whose close time is unparseable is listed with "close time unknown"
          rather than silently dropped or defaulted to zero days
        - states, unprompted, that the premise is unverified and NOT computed
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
    What the rejoin pass DID and, more importantly, WHAT IT LEFT ALONE.

    Required output, not a courtesy line — the same mandate item 4's scanner carries. A
    pass reporting "3 rejoined" reads as "the stranded rows are handled" while every
    `dropped`-blocked and unresolvable row sits underneath it, untouched by design.

    Requires:
        - counts is a dict of the pass's tallies (missing keys read as 0)

    Ensures:
        - returns a multi-line str naming the examined set, each hold bucket, and BOTH
          out-of-scope arms (the dropped arm awaiting Rick's ruling; the persona/prose arms
          this pass cannot see at all)
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
    Exercise both arms, positive AND negative — a smoke test that only runs the happy path
    cannot tell a working rejoin from one that rejoins everything.
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
