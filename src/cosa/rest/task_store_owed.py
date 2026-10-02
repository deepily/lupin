"""
Task-store owed definition: the single home for "is this row owed work?".

Three readers ask that question and must agree: `task_query` (the board and MCP surface),
the Stop-hook oracle (per-session self-poke) and the :8001 arbiter (fleet detectors).
The rule lives here once so the readers cannot diverge.

This module is separate from `task_store_rules`, which declares itself pure (no DB, no HTTP).
The SQLAlchemy twins here are not pure, so they live here and import the enums from the rules module.

Park contract: a row is park-active when its status is "parked" and `next_chase_ts` is later than now.
Expiry is computed at read time and never written back.
A parked row whose chase has passed rejoins the owed count with no daemon, sweeper or cron.
Arithmetic is used instead of a background job because a stopped sweeper leaves rows parked silently forever.
A stopped predicate returns nothing at all, which is loud.

The `owed_only` admission defines the owed set in one call: queued, in_progress, and parked rows that are not park-active.
Park-suppression layered on a caller's status filter can only subtract rows, so it cannot restore an expired parked row.
A client loop that sums per-status counts would count each expired parked row twice.
So admission happens once, server-side.

This is a restoration, not a widening: park entry is legal only from `PARK_LEGAL_FROM_STATUSES`.
That set is a subset of the two base statuses, and an import-time assert enforces it.
`is_park_legal_from` also admits parked to parked, a quote refresh that admits nothing new.
A `parked_from_status` column was rejected because the write-time rule gives the same guarantee with nothing to keep in sync.

Both twins exist because the arbiter holds loaded rows in memory, while `task_query` and `count_only` must filter in Postgres before the query's limit and offset apply.
The Python and SQLAlchemy twins are independent: neither calls the other and they share no helper.
The parity gate perturbs one side and requires a failure, which a shared implementation cannot support.
`now` is a required parameter on both, so the boundary case (chase equals now) is testable without patching.
"""

import uuid

from datetime import datetime, timezone

from cosa.rest.task_store_rules import (
    BLOCKED_STATUS,
    NOT_APPROVED_STATUS,
    PARK_LEGAL_FROM_STATUSES,
    PARK_STATUS,
    TERMINAL_STATUSES,
    VALID_STATUSES,
    WONT_FIX_STATUS,
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

# ── THE HOLDING AREA MUST NOT BE OWED (Rick's P0, 2026-09-02) ────────────────
#
# Same shape as the assertion above, and here for the same reason its comment
# gives: a silent widening "would fail nothing". `not_approved` is a row nobody
# has admitted to a board yet. If it ever entered the owed base set, the Stop
# hook and the arbiter would start poking every seat about work that has not
# been approved to exist — and no test would notice, because both twins would
# still agree with each other.
#
# `wont_fix` gets the same guard for the mirror reason: it is TERMINAL, and a
# terminal status in the owed set would poke the fleet about finished work
# forever. It is asserted rather than assumed because terminality is declared in
# ANOTHER module, so a future re-cut of TERMINAL_STATUSES cannot quietly drag it
# in here.
#
# DISJOINTNESS, not subset — the relation this proof needs. Neither word may
# appear in the owed base set under any narrowing or widening of either tuple.
assert NOT_APPROVED_STATUS not in OWED_BASE_STATUSES, (
    f"'{NOT_APPROVED_STATUS}' entered OWED_BASE_STATUSES {OWED_BASE_STATUSES} — the "
    f"holding area would become owed work, and the Stop hook and arbiter would poke "
    f"every seat about rows nobody has approved. Nothing else would fail: both twins "
    f"would still agree with each other."
)
assert WONT_FIX_STATUS not in OWED_BASE_STATUSES, (
    f"'{WONT_FIX_STATUS}' entered OWED_BASE_STATUSES {OWED_BASE_STATUSES} — a TERMINAL "
    f"status in the owed set pokes the fleet about finished work forever. Terminality "
    f"is declared in task_store_rules, so this is asserted here rather than assumed."
)
assert WONT_FIX_STATUS in TERMINAL_STATUSES, (
    f"'{WONT_FIX_STATUS}' left TERMINAL_STATUSES {TERMINAL_STATUSES} — terminal "
    f"membership is what hides it from every denylist reader and what makes "
    f"blocker_is_terminal correct for a row blocked on a won't-fix row. Removing it "
    f"re-opens both at once, silently."
)
assert NOT_APPROVED_STATUS not in TERMINAL_STATUSES, (
    f"'{NOT_APPROVED_STATUS}' entered TERMINAL_STATUSES {TERMINAL_STATUSES} — it is "
    f"PRE-queued, not finished. Terminality would tell blocker_is_terminal that a row "
    f"waiting on an unapproved row may proceed, which is the opposite of the truth."
)

__all__ = [
    "PARK_STATUS",
    "NOT_APPROVED_STATUS",
    "holding_is_active",
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
    True when the row is parked and its chase has not yet come due.

    Expiry is computed at read time and never written back.

    Requires:
        - status is the row's status string (any value accepted)
        - next_chase_ts is an ISO-8601 string, a datetime, or None
        - now is the comparison instant as a datetime, required and never defaulted
          (the predicate reads no clock; the caller resolves it)
        - a naive `now` is interpreted as UTC

    Ensures:
        - status != PARK_STATUS -> False (checked first, so a non-parked row never reaches
          the chase logic; NULL is the common chase value on the board)
        - parked and next_chase_ts > now  -> True (silence still in force)
        - parked and next_chase_ts == now -> False (the chase has come due, so the row is owed)
        - parked and next_chase_ts < now  -> False (expired, so the row rejoins owed work)
        - parked and next_chase_ts is None -> False (a malformed park surfaces as visible work;
          the write rule and the DB check make this unreachable through the API)
        - parked and next_chase_ts unparseable -> False (same rationale)
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
    True when the row is non-terminal and not currently park-active.

    No reader adopts this as its owed definition yet; readers use the `owed_only` set from the module docstring.
    Adopting it would start counting blocked, claimed and review rows, which changes behavior.

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


def park_reason_is_stale( status, park_reason_captured_at, body_changed_ts ) -> bool:
    """
    True when the row body changed after its `park_reason` quote was captured.

    It compares `body_changed_ts`, not `updated_ts`, which moves on every write and flagged correct quotes as stale after priority-only edits and transitions.
    It reads no clock and returns False on ambiguity. A false stale cannot be corrected and teaches readers to ignore the flag; the flag is advisory.
    A False answer means no body change since capture, never "verified still true". A basis `OUTSIDE` the row changes nothing in it; that limit is recorded on the store item aa543525. The real property is `CONTENT CONTRADICTION`. No timestamp can answer it, so the chase is the backstop.

    Requires:
        - status is the row's status string (any value accepted)
        - park_reason_captured_at is an ISO-8601 string, a datetime, or None
        - body_changed_ts is an ISO-8601 string, a datetime, or None
        - naive datetimes on either side are interpreted as UTC
        - both stamps come from the database clock, so a skew cannot produce a false fresh

    Ensures:
        - status != PARK_STATUS -> False (checked first; a non-parked row is never stale)
        - park_reason_captured_at is None -> False (a row parked before capture existed has no quote to judge)
        - body_changed_ts is None -> False (the body has not changed since the column shipped; no backfill)
        - either side unparseable -> False (same rationale)
        - body_changed_ts >  park_reason_captured_at -> True (the body changed after the quote was frozen)
        - body_changed_ts == park_reason_captured_at -> False (the freshly parked state)
        - body_changed_ts <  park_reason_captured_at -> False (the quote was taken from the current text)
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

    if isinstance( body_changed_ts, datetime ):
        amended_ts = body_changed_ts
    elif isinstance( body_changed_ts, str ):
        try:
            amended_ts = datetime.fromisoformat( body_changed_ts.strip().replace( "Z", "+00:00" ) )
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

def holding_is_active( status, next_chase_ts, now ) -> bool:
    """
    True when the row is in the holding area and its triage chase has not come due.

    A `not_approved` row expires like a parked row: computed at read time, never written back.
    Expiry makes the row visible on the board but not owed, and an import-time assert keeps it out of the owed set.
    A `not_approved` row was never owed by anyone, so re-admitting it on expiry would poke seats about work nobody approved.

    Requires:
        - status is a status string
        - next_chase_ts is an ISO-8601 string, a datetime, or None
        - now is a datetime (naive treated as UTC)

    Ensures:
        - non-holding status                      -> False (checked first, so an unrelated row skips the chase arithmetic)
        - holding and next_chase_ts >  now        -> True (still awaiting triage)
        - holding and next_chase_ts == now        -> False (the chase has come due, matching park_is_active)
        - holding and next_chase_ts <  now        -> False (expired, so the row becomes visible)
        - holding and next_chase_ts None/unparsed -> False (a row whose chase cannot be read must surface,
          not hide indefinitely)
        - never raises
    """
    if status != NOT_APPROVED_STATUS:
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


def park_is_active_clause( model, now ):
    """
    SQLAlchemy twin of `park_is_active`: a boolean expression true for park-active rows.

    Requires:
        - model is the mapped TaskItem class (or an alias) exposing `status` and `next_chase_ts`
        - now is the comparison instant as a datetime, required and never defaulted
        - a naive `now` is interpreted as UTC

    Ensures:
        - returns a SQLAlchemy boolean expression, never a Python bool
        - True iff status == PARK_STATUS and next_chase_ts is not NULL and next_chase_ts > now
        - a NULL next_chase_ts yields False, not NULL, because three-valued logic would drop the row
          from both sides of a filter; it must land on the owed side, matching twin (a)'s NULL branch
        - the status test is the first conjunct, mirroring twin (a)'s guard
    """
    from sqlalchemy import and_

    comparison_now = now.replace( tzinfo=timezone.utc ) if now.tzinfo is None else now

    return and_(
        model.status == PARK_STATUS,
        model.next_chase_ts.isnot( None ),
        model.next_chase_ts > comparison_now,
    )


def holding_is_active_clause( model, now ):
    """
    SQLAlchemy twin of `holding_is_active`, shaped like `park_is_active_clause`.

    The `isnot( None )` test is needed beside `>`: in SQL a comparison against NULL yields NULL, not False.
    Without it a row with no chase would be in neither set.
    The Python twin reaches the same verdict through its `else` branch, so both need their own tests.

    Requires:
        - model is the TaskItem class (or a mapped alias)
        - now is a datetime (naive treated as UTC)

    Ensures:
        - returns a SQLAlchemy boolean expression, never a Python bool
        - True for a holding-area row whose chase is still in the future
        - False for an expired, absent or unparseable chase, so the row surfaces
    """
    from sqlalchemy import and_

    comparison_now = now.replace( tzinfo=timezone.utc ) if now.tzinfo is None else now

    return and_(
        model.status == NOT_APPROVED_STATUS,
        model.next_chase_ts.isnot( None ),
        model.next_chase_ts > comparison_now,
    )


def item_blocker_ids( blocked_by ):
    """
    Return every `{kind: "item"}` id in a `blocked_by` list, as strings.

    Only the item kind has an oracle: an item id resolves against this store and returns a status.
    A persona ref has no registry and a user ref has no lifecycle.
    Scanning those kinds would mark live but quiet seats as dead.

    Requires:
        - blocked_by is the row's blocked_by value (any type; non-list yields [])

    Ensures:
        - returns a list of str ids for entries shaped {kind: "item", id: <non-empty str>}
        - a malformed entry (not a dict, wrong kind, missing/blank/non-str id) is skipped, never raised on,
          because this runs on the read path of every query
        - order is the list's own; duplicates are preserved (the caller batches)
        - never raises
    """
    if not isinstance( blocked_by, list ):
        return [ ]

    ids = [ ]
    for ref in blocked_by:
        if not isinstance( ref, dict ):                 continue
        if ref.get( "kind" ) != "item":                 continue
        ref_id = ref.get( "id" )
        if not isinstance( ref_id, str ) or not ref_id: continue
        ids.append( ref_id )
    return ids


def is_canonical_uuid( value ):
    """
    True when `value` is a full canonical UUID string.

    `blocker_is_terminal` calls an unresolved id dead only when it is spelled in full.
    A shorter form is an abbreviation the read verbs accept, so its non-resolution describes the lookup.

    Requires:
        - value is any object

    Ensures:
        - True only for a 36-char dashed UUID string
        - False for an 8-hex prefix, a compact 32-char form, a non-string, or junk
        - never raises
    """
    if not isinstance( value, str ) or len( value ) != 36: return False
    try:
        return str( uuid.UUID( value ) ) == value.lower()
    except ( ValueError, AttributeError, TypeError ):
        return False


def blocker_is_terminal( status, blocked_by, status_by_id ):
    """
    True when this row's wait can never be satisfied by the blocker it relies on.

    A row blocked on an item that became `done` or `dropped` stays `blocked` forever; nothing re-examines the edge.
    The flag is advisory: it changes no owed-ness and transitions nothing; a `dropped` blocker needs the owner's call.
    Only a full canonical UUID that fails to resolve counts as dead; an id absent from `status_by_id` is no evidence.

    Requires:
        - status is the row's status string (any value accepted)
        - blocked_by is the row's blocked_by value (any type)
        - status_by_id maps blocker-id str -> status str, with an explicit None value for an id
          that was looked up and not found; a key absent from the map was never looked up and yields no finding

    Ensures:
        - status != BLOCKED_STATUS -> False (checked first; a queued row with a leftover blocked_by is not waiting)
        - no {kind:"item"} blocker -> False (persona and user arms have no oracle)
        - any item blocker resolving to a terminal status -> True
        - a canonical-UUID blocker present in the map as None (looked up, absent) -> True
        - a non-canonical (prefix) blocker present as None -> False (unresolvable by width means "cannot tell")
        - every item blocker resolving to a non-terminal status -> False
        - an id absent from status_by_id contributes nothing either way
        - one terminal blocker plus one live blocker -> True (the dead half still gates the row)
        - never raises
    """
    if status != BLOCKED_STATUS:
        return False

    for ref_id in item_blocker_ids( blocked_by ):
        if ref_id not in status_by_id: continue
        blocker_status = status_by_id[ ref_id ]
        if blocker_status in TERMINAL_STATUSES:        return True
        # UNRESOLVED. Only a CANONICAL id may be condemned on this arm — see the
        # width caveat above. A non-canonical id that failed to resolve means
        # "I cannot tell", and this predicate lies toward NOT-flagged.
        if blocker_status is None and is_canonical_uuid( ref_id ): return True
    return False


def park_reason_is_stale_clause( model ):
    """
    SQLAlchemy twin of `park_reason_is_stale`: a boolean expression true for stale rows.

    The twin is self-contained: it does not call twin (a) and shares no helper with it, so the parity gate can perturb one side.
    It takes no `now`, because staleness compares two columns of one row.
    It reads `body_changed_ts`, not `updated_ts`, and must move together with twin (a) or the two halves disagree.

    Requires:
        - model is the mapped TaskItem class (or an alias) exposing `status`,
          `park_reason_captured_at` and `body_changed_ts`

    Ensures:
        - returns a SQLAlchemy boolean expression, never a Python bool
        - True iff status == PARK_STATUS and park_reason_captured_at is not NULL
          and body_changed_ts is not NULL and body_changed_ts > park_reason_captured_at
        - a NULL on either timestamp yields False, not NULL, because three-valued logic would drop
          the row from both sides of a filter; it must land on the not-stale side, matching twin (a)
        - the status test is the first conjunct, mirroring twin (a)'s guard
    """
    from sqlalchemy import and_

    return and_(
        model.status == PARK_STATUS,
        model.park_reason_captured_at.isnot( None ),
        model.body_changed_ts.isnot( None ),
        model.body_changed_ts > model.park_reason_captured_at,
    )


def owed_clause( model, now ):
    """
    Return the park-suppression clause: true for every row that is not park-active.

    The expression drops into `query.filter( ... )` on both the row query and the count query.
    It only subtracts park-active rows; restoring expired parked rows needs `owed_status_clause`.

    Requires:
        - model is the mapped TaskItem class (or an alias)
        - now is the comparison instant as a datetime, required

    Ensures:
        - returns a SQLAlchemy boolean expression
        - an expired parked row passes (it has rejoined owed work)
        - a parked row with a NULL chase passes (it surfaces as owed)
        - a park-active row does not pass
    """
    from sqlalchemy import not_

    return not_( park_is_active_clause( model, now ) )


def owed_status_clause( model, now ):
    """
    Return the `owed_only=True` set: queued, in_progress, and parked rows not park-active.

    The Stop-hook oracle and the arbiter select on this admission, so the server owns the owed set.
    A per-status admission would count each expired parked row twice.
    It does not widen the set: park entry is restricted to `PARK_LEGAL_FROM_STATUSES`.

    Requires:
        - model is the mapped TaskItem class (or an alias)
        - now is the comparison instant as a datetime, required

    Ensures:
        - returns a SQLAlchemy boolean expression
        - true for every queued / in_progress row, regardless of chase value
        - true for a parked row whose chase has come due (or is NULL)
        - false for a park-active row, and for every other status
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
    Row-level twin of `owed_status_clause`: True when the row is in the `owed_only=True` set.

    Readers that hold plain dicts, such as `task_store_drain`, cannot evaluate a SQLAlchemy expression, so they call this verb.
    It is not `is_owed`, which would admit blocked, claimed and review rows.
    It calls neither `park_is_active` nor the clause, so the equivalence gate can perturb one side and require a failure.

    Requires:
        - status is the row's status string (any value accepted)
        - next_chase_ts is an ISO-8601 string, a datetime, or None
        - now is the comparison instant as a datetime, required and never defaulted
        - a naive `now` is interpreted as UTC

    Ensures:
        - status in OWED_BASE_STATUSES -> True, whatever the chase value
        - status == PARK_STATUS and the chase has come due / is NULL / is unparseable -> True
          (rejoined, or a malformed park surfaces as owed)
        - status == PARK_STATUS and the chase is still in the future -> False
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
    Smoke-test the owed predicates on a fixed clock.

    Exercises every branch of park_is_active, plus is_owed, owed_status_row, staleness and park legality.
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
        # DERIVED from VALID_STATUSES, not hand-listed. A literal tuple here silently
        # stops covering every status added after it was written — and this assertion's
        # whole job is "no NON-parked status ever reports stale", a claim about the set
        # as a whole. It was a literal until 2026-09-02, when `not_approved` and
        # `wont_fix` landed and it would have gone on passing while checking neither.
        for other in ( st for st in VALID_STATUSES if st != PARK_STATUS ):
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
