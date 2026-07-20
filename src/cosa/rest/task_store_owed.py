"""
Task-store OWED definition — the ONE home for "is this row owed work?".

Three independent readers ask that question and MUST agree (design
src/rnd/v0.1.9/2026.07.19-parked-status-board-hygiene.md):

    1. `task_query`         — the board / MCP surface
    2. the Stop-hook oracle — the per-session self-poke (src/lupin_cli/.../hooks/)
    3. the :8001 arbiter    — the fleet detectors (heartbeat_arbiter/)

Divergence across those readers has bitten this fleet repeatedly, so the rule
lives here exactly once.

WHY A SEPARATE MODULE FROM task_store_rules
-------------------------------------------
`task_store_rules` declares itself PURE in its own docstring ("Every function is
pure (no DB, no HTTP)"). The SQLAlchemy twin below is not pure by that
definition, and a module whose docstring lies is how the next reader gets misled
(Krishna's catch, ruled by Mr. Radio 2026-07-19). The owed definition gets its
own home and IMPORTS the enums from `task_store_rules`, whose purity contract
stays intact and untouched.

Named `_owed`, not `_parked`: it owns the OWED definition, of which parked-ness
is one term.

THE PARK CONTRACT
-----------------
    park_is_active  ==  status == "parked" AND next_chase_ts > now

Expiry is computed at READ time and NEVER written back. A parked row whose chase
has passed is not parked any more — it rejoins the owed count automatically. No
daemon, no sweeper, no cron, no human action. Parking buys BOUNDED,
SELF-EXPIRING silence, never an exit.

Arithmetic rather than a background job, on purpose: a sweeper that stops running
leaves rows parked forever (silent); a predicate that stops running returns
nothing at all (loud).

WHY `owed_only` DEFINES THE SET IN ONE CALL (and why "additive" was wrong)
--------------------------------------------------------------------------
An earlier ruling had park-suppression apply ON TOP of whatever status filter a
caller already passed. It cannot express what it ordered, and the trace is short:

    status=queued                          -> the Stop hook counts it
    park it (status=parked, chase FUTURE)  -> matches neither queued nor
                                              in_progress -> not counted (desired)
    the chase PASSES (status=parked, PAST) -> STILL matches neither
                                           -> STILL NOT COUNTED  <-- the bug

Park-suppression is SUBTRACTIVE: it can only remove rows from a set. An expired
parked row was never IN the Stop hook's set, because parking MOVED its status out
of `queued`. Subtracting nothing from a set that already excludes it leaves it
excluded forever — and the rejoin is the single most important behavior here.

A second defect kills the additive shape outright: `query_owed`
(task_store_client.py) LOOPS the status tuple and SUMS the per-status counts.
Per-status admission would count every expired-parked row TWICE — parking a row
would make the board look BUSIER than never parking it, inverting the feature.

So the admission happens ONCE, server-side:

    owed_only=True, status=None  ->  queued ∪ in_progress ∪ (parked AND NOT park-active)

This is NOT a widening. `is_park_legal_from` (below) makes park legal ONLY from
("queued","in_progress"), so the restored set is a SUBSET of those same two
statuses BY CONSTRUCTION. Nothing new is admitted; blocked/claimed/review
membership is unchanged for every reader.

REJECTED ALTERNATIVE — a `parked_from_status` column. Rick overruled that exact
shape today: a new field where a rule suffices. The write-time rule gives the
same guarantee with nothing to keep in sync.

THE TWO TWINS ARE DELIBERATELY INDEPENDENT
------------------------------------------
`park_is_active()` (Python) and `park_is_active_clause()` (SQLAlchemy) express
the same rule in two languages, because the readers need both: the arbiter holds
loaded rows in memory, while `task_query` / `count_only` must filter in Postgres
BEFORE LIMIT/OFFSET (filtering after LIMIT is wrong; pulling the whole board
defeats the unscoped guard).

Neither calls the other, and neither derives from a shared third helper. That
duplication is LICENSED, not accidental: the parity gate proves them identical by
perturbing ONE side and requiring RED. A twin pair sharing an implementation
cannot be mutation-tested — an equivalence test over a shared helper proves only
that the helper equals itself.

`now` IS A REQUIRED PARAMETER on both. The predicates never read a clock; callers
resolve it at the boundary. An internally-sourced clock makes the boundary case
(chase == now) unreachable without monkeypatching module state, which is exactly
where that test goes flaky.
"""

from datetime import datetime, timezone

from cosa.rest.task_store_rules import (
    PARK_LEGAL_FROM_STATUSES,
    PARK_STATUS,
    TERMINAL_STATUSES,
    VALID_STATUSES,
    is_park_legal_from,
)


# ---------------------------------------------------------------------------
# The parked status — vocabulary imported, predicate owned here
# ---------------------------------------------------------------------------
#
# PARK_STATUS / PARK_LEGAL_FROM_STATUSES / is_park_legal_from live with the other
# enums in `task_store_rules` (one home for the store's WORDS) and are re-exported
# here so a reader needs exactly one import for the whole owed contract. The
# dependency runs owed -> rules and never back, which is what keeps rules.py's
# "no DB, no HTTP" purity contract true with a SQLAlchemy twin in the tree.
# The statuses that are owed BEFORE any park handling — the set every reader
# already counts today (stop.py's STORE_OWED_STATUSES, pre-deletion). Published
# here so the four hardcoded copies fold onto one definition (a de-duplication
# with NO behavior change: same constants, each reader's current set preserved).
OWED_BASE_STATUSES = ( "queued", "in_progress" )

# ── THE INVARIANT THAT MAKES RE-ADMISSION EXACT (Rachel's catch, 2026-07-19) ──
#
# `owed_status_clause` re-admits the WHOLE expired-parked set. That is a
# RESTORATION rather than a WIDENING only while every parkable row came from a
# status the readers already counted — i.e.
#
#       PARK_LEGAL_FROM_STATUSES  ⊆  OWED_BASE_STATUSES
#
# Widen park-legality to, say, "blocked" without touching the admission set and
# an expired ex-blocked row starts being counted as owed. Nothing else would
# fail: both twins still agree with each other, every existing test still passes,
# and the fleet quietly starts getting poked about rows it never was before.
#
# So the coupling is asserted here, at import, where a divergence is LOUD.
#
# SUBSET, not equality — the relation the proof actually needs. Narrowing park
# (e.g. legal only from "queued") keeps restoration exact and must stay legal;
# only escaping the owed base set breaks it. An equality assertion would forbid a
# safe change and, worse, teach the next reader the wrong invariant.
#
# The two names are kept distinct because they answer different questions
# ("what counts as owed?" vs "what may be parked?"). The assertion is what makes
# that separation safe instead of merely tidy.
assert set( PARK_LEGAL_FROM_STATUSES ) <= set( OWED_BASE_STATUSES ), (
    f"park-legality {PARK_LEGAL_FROM_STATUSES} escapes the owed base set "
    f"{OWED_BASE_STATUSES} — re-admitting expired-parked rows would WIDEN what "
    f"the Stop hook and arbiter count, not restore it. Either narrow "
    f"PARK_LEGAL_FROM_STATUSES or deliberately re-cut OWED_BASE_STATUSES and "
    f"the AC11 no-drift guard together."
)

__all__ = [
    "PARK_STATUS",
    "PARK_LEGAL_FROM_STATUSES",
    "OWED_BASE_STATUSES",
    "is_park_legal_from",
    "park_is_active",
    "is_owed",
    "park_reason_is_stale",
    "park_reason_is_stale_clause",
    "park_is_active_clause",
    "owed_clause",
    "owed_status_clause",
    "owed_status_row",
]

# Fail at IMPORT time if the enum ever drops `parked` — otherwise every reader
# would silently stop suppressing, which is the exact failure class this module
# exists to prevent.
assert PARK_STATUS in VALID_STATUSES, (
    f"'{PARK_STATUS}' is missing from task_store_rules.VALID_STATUSES — the owed "
    f"predicate would silently stop suppressing parked rows"
)
assert PARK_STATUS not in TERMINAL_STATUSES, (
    f"'{PARK_STATUS}' must be NON-terminal — parking buys bounded silence, never an exit"
)


# ---------------------------------------------------------------------------
# The predicate (Python) — twin (a)
# ---------------------------------------------------------------------------
#
# Self-contained BY DESIGN. Does not call twin (b); shares no helper with it.
# See the module docstring: the parity gate perturbs one side and requires RED.

def park_is_active( status, next_chase_ts, now ) -> bool:
    """
    True iff the row is parked AND its chase has NOT yet come due.

    THE SELF-EXPIRY RULE, computed at read time and never written back.

    Requires:
        - status is the row's status string (any value accepted)
        - next_chase_ts is an ISO-8601 string, a datetime, or None
        - now is the comparison instant as a datetime — REQUIRED, never
          defaulted (the predicate reads no clock; the caller resolves it).
          A naive `now` is interpreted as UTC.

    Ensures:
        - status != PARK_STATUS                -> False (checked FIRST, so a
          non-parked row is never touched by the chase logic at all — NULL is
          the modal chase value on this board, and a status-guard slip plus a
          wrong NULL arm would silence the entire board inside the very fix
          meant to prevent that)
        - parked AND next_chase_ts >  now      -> True  (silence still bought)
        - parked AND next_chase_ts == now      -> False (the boundary: the chase
          has COME DUE, so the row has rejoined owed work)
        - parked AND next_chase_ts <  now      -> False (EXPIRED — rejoins owed)
        - parked AND next_chase_ts is None     -> False (fail-loud-toward-owed:
          a malformed park is VISIBLE work; the write rule + DB CHECK make this
          unreachable through the API)
        - parked AND next_chase_ts unparseable -> False (same rationale)
        - never raises
    """
    if status != PARK_STATUS:
        return False

    if isinstance( next_chase_ts, datetime ):
        chase_ts = next_chase_ts
    elif isinstance( next_chase_ts, str ):
        try:
            chase_ts = datetime.fromisoformat( next_chase_ts.strip().replace( "Z", "+00:00" ) )
        except ValueError:
            return False
    else:
        return False

    if chase_ts.tzinfo is None:
        chase_ts = chase_ts.replace( tzinfo=timezone.utc )
    comparison_now = now.replace( tzinfo=timezone.utc ) if now.tzinfo is None else now

    return chase_ts > comparison_now


def is_owed( status, next_chase_ts, now ) -> bool:
    """
    The honest GENERAL owed predicate: non-terminal AND not currently park-active.

    ⚠️ SCOPE: no reader adopts this as its owed definition in this pass. The
    readers use the one-call `owed_only` set (queued ∪ in_progress ∪ expired-
    parked) described in the module docstring. Adopting this wholesale would
    start counting blocked/claimed/review rows — an unordered behavior change.
    It is the right long-term shape and is named here so the general rule has a
    home; adopting it fleet-wide is a separate, ruled decision.

    Requires:
        - status / next_chase_ts / now as per park_is_active

    Ensures:
        - terminal status (done/dropped) -> False
        - park-active                    -> False
        - anything else                  -> True
        - never raises
    """
    if status in TERMINAL_STATUSES:
        return False
    return not park_is_active( status, next_chase_ts, now )


def park_reason_is_stale( status, park_reason_captured_at, updated_ts ) -> bool:
    """
    True iff the row's `park_reason` quote is provably OLDER than the row itself.

    `park_reason` is a FROZEN QUOTE captured at park time. Amend the row afterward
    and the quote stays syntactically valid while it stops being true, and NOTHING
    GOES RED. This predicate is the red: it does not stop prose going stale, it
    makes the divergence VISIBLE (design
    src/rnd/v0.1.9/2026.07.19-park-reason-staleness-detection.md §3.2).

    READS NO CLOCK — deliberately, and unlike `park_is_active`. Staleness is a
    comparison of two values ALREADY ON THE ROW; `now` has no part in it. A `now`
    parameter here would be an invitation to write `now() > captured_at`, which is
    true of every parked row the instant after it is parked.

    THE ORDERING THIS DEPENDS ON (§3.4 — read it before changing the writer):
    `park_reason_captured_at` is set at park time to the POST-write `updated_ts`,
    the value the park write itself stamps. So immediately after park
    `captured_at == updated_ts` EXACTLY, and this returns False. Capture the
    PRE-write value instead and `captured_at < updated_ts` the instant park
    commits — every row born STALE, the trap this plan's own §3.4 prescribed in
    draft. Capture `now()` and it races the `updated_ts` stamp.

    WHICH WAY THIS INSTRUMENT LIES: every ambiguous arm returns False
    (NOT-stale) — the OPPOSITE direction from `park_is_active`'s
    fail-loud-toward-owed, and deliberately so. Staleness is ADVISORY (§3.3): it
    changes no owed-ness and blocks nothing, so a false STALE has no mechanism to
    correct it — it merely defames a correct quote and teaches readers to ignore
    the flag, which disarms the feature permanently. A false FRESH is exactly the
    status quo this change improves on. Silence is recoverable here; a crying wolf
    is not.

    Requires:
        - status is the row's status string (any value accepted)
        - park_reason_captured_at is an ISO-8601 string, a datetime, or None
        - updated_ts is an ISO-8601 string, a datetime, or None
        - naive datetimes on either side are interpreted as UTC

    Ensures:
        - status != PARK_STATUS                     -> False (checked FIRST; a
          non-parked row is never stale whatever its timestamps say — AC5)
        - park_reason_captured_at is None           -> False (a row parked before
          this shipped has no capture time; we cannot know what its quote
          described, so we do not accuse it — §7, no backfill)
        - updated_ts is None                        -> False (no evidence of any
          write after capture)
        - either side unparseable                   -> False (same rationale)
        - updated_ts >  park_reason_captured_at     -> True  (STALE — the row was
          amended after its quote was frozen, AC4)
        - updated_ts == park_reason_captured_at     -> False (the freshly-parked
          state, AC3 — the boundary, and the one the ordering trap turns on)
        - updated_ts <  park_reason_captured_at     -> False
        - never raises
    """
    if status != PARK_STATUS:
        return False

    if isinstance( park_reason_captured_at, datetime ):
        captured_ts = park_reason_captured_at
    elif isinstance( park_reason_captured_at, str ):
        try:
            captured_ts = datetime.fromisoformat( park_reason_captured_at.strip().replace( "Z", "+00:00" ) )
        except ValueError:
            return False
    else:
        return False

    if isinstance( updated_ts, datetime ):
        amended_ts = updated_ts
    elif isinstance( updated_ts, str ):
        try:
            amended_ts = datetime.fromisoformat( updated_ts.strip().replace( "Z", "+00:00" ) )
        except ValueError:
            return False
    else:
        return False

    if captured_ts.tzinfo is None:
        captured_ts = captured_ts.replace( tzinfo=timezone.utc )
    if amended_ts.tzinfo is None:
        amended_ts = amended_ts.replace( tzinfo=timezone.utc )

    return amended_ts > captured_ts


# ---------------------------------------------------------------------------
# The predicate (SQLAlchemy) — twin (b)
# ---------------------------------------------------------------------------
#
# Self-contained BY DESIGN. Does not call twin (a); shares no helper with it.

def park_is_active_clause( model, now ):
    """
    The SQL twin of `park_is_active`: a SQLAlchemy boolean expression true for
    exactly the rows the Python predicate calls park-active.

    Requires:
        - model is the mapped TaskItem class (or an alias) exposing `status` and
          `next_chase_ts`
        - now is the comparison instant as a datetime — REQUIRED, never
          defaulted. A naive `now` is interpreted as UTC.

    Ensures:
        - returns a SQLAlchemy boolean expression, never a Python bool
        - TRUE iff status == PARK_STATUS AND next_chase_ts IS NOT NULL
                                         AND next_chase_ts > now
        - a NULL next_chase_ts yields FALSE, not NULL — three-valued logic would
          drop the row from BOTH sides of a filter, and it must land on the OWED
          side (fail-loud-toward-owed), matching twin (a)'s NULL branch
        - the status test is the FIRST conjunct, mirroring twin (a)'s guard
    """
    from sqlalchemy import and_

    comparison_now = now.replace( tzinfo=timezone.utc ) if now.tzinfo is None else now

    return and_(
        model.status == PARK_STATUS,
        model.next_chase_ts.isnot( None ),
        model.next_chase_ts > comparison_now,
    )


def park_reason_is_stale_clause( model ):
    """
    The SQL twin of `park_reason_is_stale`: a SQLAlchemy boolean expression true
    for exactly the rows the Python predicate calls stale.

    Self-contained BY DESIGN. Does not call twin (a); shares no helper with it.
    That duplication is LICENSED (module docstring): the parity gate proves the
    two identical by perturbing ONE side and requiring RED, which a pair sharing
    an implementation cannot support.

    NO `now` PARAMETER, matching twin (a) — staleness compares two columns of the
    same row, and a clock has no part in it.

    Requires:
        - model is the mapped TaskItem class (or an alias) exposing `status`,
          `park_reason_captured_at` and `updated_ts`

    Ensures:
        - returns a SQLAlchemy boolean expression, never a Python bool
        - TRUE iff status == PARK_STATUS
                  AND park_reason_captured_at IS NOT NULL
                  AND updated_ts             IS NOT NULL
                  AND updated_ts > park_reason_captured_at
        - a NULL on EITHER timestamp yields FALSE, not NULL — three-valued logic
          would drop the row from BOTH sides of a filter, and it must land on the
          NOT-STALE side, matching twin (a)'s null arms
        - the status test is the FIRST conjunct, mirroring twin (a)'s guard
    """
    from sqlalchemy import and_

    return and_(
        model.status == PARK_STATUS,
        model.park_reason_captured_at.isnot( None ),
        model.updated_ts.isnot( None ),
        model.updated_ts > model.park_reason_captured_at,
    )


def owed_clause( model, now ):
    """
    The park-suppression clause: TRUE for every row that is NOT park-active.

    A bare boolean expression, droppable straight into `query.filter( ... )` on
    BOTH the row query and the COUNT(*) query — the count side is where a reader
    diverges silently, so it takes the identical expression, not a variant.

    NOTE the scope discipline (module docstring): this clause SUBTRACTS
    park-active rows. It does NOT by itself restore expired-parked rows to a
    status-filtered set — that restoration is the `owed_only` admission, which
    must select the status set in ONE call. Using this clause alone on top of a
    ("queued","in_progress") filter reproduces the bug it was meant to fix.

    Requires:
        - model is the mapped TaskItem class (or an alias)
        - now is the comparison instant as a datetime — REQUIRED

    Ensures:
        - returns a SQLAlchemy boolean expression
        - an EXPIRED parked row passes (it has rejoined owed work)
        - a parked row with a NULL chase passes (fail-loud-toward-owed)
        - a park-active row does NOT pass
    """
    from sqlalchemy import not_

    return not_( park_is_active_clause( model, now ) )


def owed_status_clause( model, now ):
    """
    THE `owed_only=True` SET, in ONE expression:

        queued ∪ in_progress ∪ (parked AND NOT park-active)

    This is the admission the Stop-hook oracle and the arbiter select on. It is
    ONE clause because the owed set is SERVER-OWNED: no client holds a status
    tuple, so there is no second thing to remember to pair, and the seam fails
    CLOSED. A per-status admission would count every expired-parked row TWICE
    (admitted on the queued call AND the in_progress call), making a parked board
    look BUSIER than an unparked one — which inverts the feature.

    ⚠️ CORRECTED 2026-07-20. This previously read "ONE clause rather than a
    per-status loop BECAUSE `query_owed` SUMS per-status counts" — stale AND
    backwards. `query_owed` stopped summing per-status on 2026-07-19; and the
    causation ran the wrong way, naming the client loop as the REASON for the
    server clause when the clause exists precisely so that no client loop is
    needed. A reader reasoning from the old text could conclude the loop is
    load-bearing and must be preserved. The double-count warning was always
    correct; only its stated cause was wrong.

    Not a widening: `is_park_legal_from` restricts park to
    PARK_LEGAL_FROM_STATUSES, so the admitted expired-parked rows provably came
    from those same two statuses. blocked/claimed/review membership is unchanged.

    Requires:
        - model is the mapped TaskItem class (or an alias)
        - now is the comparison instant as a datetime — REQUIRED

    Ensures:
        - returns a SQLAlchemy boolean expression
        - TRUE for every queued / in_progress row, regardless of chase value
        - TRUE for a parked row whose chase has come due (or is NULL)
        - FALSE for a park-active row, and for every other status
    """
    from sqlalchemy import and_, not_, or_

    return or_(
        model.status.in_( OWED_BASE_STATUSES ),
        and_(
            model.status == PARK_STATUS,
            not_( park_is_active_clause( model, now ) ),
        ),
    )


def owed_status_row( status, next_chase_ts, now ) -> bool:
    """
    The ROW-LEVEL twin of `owed_status_clause`: True iff the row is in the
    `owed_only=True` set —

        queued ∪ in_progress ∪ (parked AND NOT park-active)

    Needed because not every reader holds ORM rows. `task_store_drain` filters
    task DICTS decoded from an HTTP body, so it cannot evaluate a SQLAlchemy
    expression — without this verb it would have to compose the admission inline,
    which is a second expression of the rule living outside this module.

    ⚠️ NOT `is_owed`. That is the general non-terminal predicate and would admit
    blocked / claimed / review. This is pinned to the two base statuses plus the
    restored expired-parked set.

    INDEPENDENCE (deliberate, load-bearing): this does its OWN inline coercion
    and its OWN park-window comparison. It does NOT call `park_is_active`, and
    `owed_status_clause` does not call it. That duplication is what lets the
    equivalence gate mutate ONE side and require RED — the ADMISSION half is
    where every defect in this build has lived, so it is exactly the half that
    must be mutation-provable rather than assumed.

    Requires:
        - status is the row's status string (any value accepted)
        - next_chase_ts is an ISO-8601 string, a datetime, or None
        - now is the comparison instant as a datetime — REQUIRED, never
          defaulted. A naive `now` is interpreted as UTC.

    Ensures:
        - status in OWED_BASE_STATUSES        -> True, whatever the chase value
        - status == PARK_STATUS AND the chase has come due / is NULL / is
          unparseable                          -> True (rejoined, or fail-loud-
          toward-owed)
        - status == PARK_STATUS AND the chase is still in the future -> False
        - every other status (blocked/claimed/review/done/dropped) -> False
        - never raises
    """
    if status in OWED_BASE_STATUSES:
        return True

    if status != PARK_STATUS:
        return False

    # Parked: owed iff the chase has come due. Coerced independently of every
    # other predicate in this module — see INDEPENDENCE above.
    if isinstance( next_chase_ts, datetime ):
        chase_ts = next_chase_ts
    elif isinstance( next_chase_ts, str ):
        try:
            chase_ts = datetime.fromisoformat( next_chase_ts.strip().replace( "Z", "+00:00" ) )
        except ValueError:
            return True
    else:
        return True

    if chase_ts.tzinfo is None:
        chase_ts = chase_ts.replace( tzinfo=timezone.utc )
    comparison_now = now.replace( tzinfo=timezone.utc ) if now.tzinfo is None else now

    return not ( chase_ts > comparison_now )


def quick_smoke_test():
    """
    Quick smoke test for the owed predicate — exercises every branch of
    park_is_active plus is_owed and the park-legality rule, on a fixed clock.
    """
    from datetime import timedelta

    import cosa.utils.util as cu

    cu.print_banner( "Task-Store Owed Predicate Smoke Test", prepend_nl=True )

    try:
        now    = datetime( 2026, 7, 19, 12, 0, 0, tzinfo=timezone.utc )
        future = ( now + timedelta( hours=6 ) ).isoformat()
        past   = ( now - timedelta( hours=6 ) ).isoformat()

        print( "Testing the park-active window..." )
        assert park_is_active( "parked", future, now ) is True
        assert park_is_active( "parked", past,   now ) is False
        assert park_is_active( "queued", future, now ) is False
        print( "✓ parked + future chase is silent; parked + past chase is not" )

        print( "Testing the boundary (chase == now)..." )
        assert park_is_active( "parked", now.isoformat(), now ) is False
        print( "✓ a chase that has COME DUE has rejoined owed work" )

        print( "Testing self-expiry rejoins owed work..." )
        assert is_owed( "parked", future, now ) is False
        assert is_owed( "parked", past,   now ) is True
        print( "✓ an EXPIRED park rejoins the owed count with no daemon" )

        print( "Testing fail-loud-toward-owed..." )
        assert park_is_active( "parked", None,         now ) is False
        assert park_is_active( "parked", "not-a-date", now ) is False
        assert is_owed( "parked", None, now ) is True
        print( "✓ a malformed park is VISIBLE work, never silent" )

        print( "Testing terminal states..." )
        assert is_owed( "done",    None, now ) is False
        assert is_owed( "dropped", None, now ) is False
        assert is_owed( "queued",  None, now ) is True
        print( "✓ terminal rows are never owed" )

        print( "Testing tz-naive coercion..." )
        naive = ( now + timedelta( hours=1 ) ).replace( tzinfo=None )
        assert park_is_active( "parked", naive, now ) is True
        print( "✓ a naive timestamp is read as UTC" )

        print( "Testing the ADMISSION set (owed_status_row)..." )
        assert owed_status_row( "queued",      None,   now ) is True
        assert owed_status_row( "in_progress", None,   now ) is True
        assert owed_status_row( "parked",      past,   now ) is True   # rejoined
        assert owed_status_row( "parked",      future, now ) is False  # still silent
        assert owed_status_row( "parked",      None,   now ) is True   # fail-loud
        assert owed_status_row( "blocked",     None,   now ) is False  # NOT widened
        assert owed_status_row( "claimed",     None,   now ) is False
        assert owed_status_row( "review",      None,   now ) is False
        assert owed_status_row( "done",        None,   now ) is False
        print( "✓ admission = queued ∪ in_progress ∪ expired-parked, nothing widened" )

        print( "Testing park_reason STALENESS (amendment-relative, no clock)..." )
        captured = now
        amended  = now + timedelta( minutes=5 )
        assert park_reason_is_stale( "parked", captured, amended  ) is True    # AC4
        assert park_reason_is_stale( "parked", captured, captured ) is False   # AC3 boundary
        assert park_reason_is_stale( "parked", amended,  captured ) is False
        print( "✓ a row amended after its quote was frozen is STALE; equal is NOT" )

        print( "Testing staleness is status-gated (AC5)..." )
        for other in ( "queued", "in_progress", "blocked", "claimed", "review", "done", "dropped" ):
            assert park_reason_is_stale( other, captured, amended ) is False
        print( "✓ no non-parked status ever reports stale, whatever the timestamps say" )

        print( "Testing the null arms (fail-QUIET, opposite of park_is_active)..." )
        assert park_reason_is_stale( "parked", None,         amended ) is False
        assert park_reason_is_stale( "parked", captured,     None    ) is False
        assert park_reason_is_stale( "parked", "not-a-date", amended ) is False
        assert park_reason_is_stale( "parked", captured, "not-a-date" ) is False
        print( "✓ an unknown capture time is never an accusation — an advisory flag must not cry wolf" )

        print( "Testing staleness reads ISO strings and naive datetimes..." )
        assert park_reason_is_stale( "parked", captured.isoformat(), amended.isoformat() ) is True
        assert park_reason_is_stale( "parked", captured.replace( tzinfo=None ), amended ) is True
        print( "✓ string and naive-UTC inputs agree with the datetime path" )

        print( "Testing staleness is ADVISORY — owed-ness untouched (AC7)..." )
        assert park_is_active(   "parked", future, now ) is True
        assert owed_status_row(  "parked", future, now ) is False
        assert park_is_active(   "parked", past,   now ) is False
        assert owed_status_row(  "parked", past,   now ) is True
        print( "✓ a stale quote changes no owed-ness, unparks nothing, blocks nothing" )

        print( "Testing park legality..." )
        assert is_park_legal_from( "queued" )      is True
        assert is_park_legal_from( "in_progress" ) is True
        assert is_park_legal_from( "blocked" )     is False
        assert is_park_legal_from( "done" )        is False
        print( "✓ park is legal ONLY from queued / in_progress" )

        print( "\n✓ Smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
