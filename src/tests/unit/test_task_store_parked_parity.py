"""
THE PARITY GATE for the `parked` status (PARKED-STATUS build, 2026-07-19).

Seat 3 (Rachel 🕊️). Design: src/rnd/v0.1.9/2026.07.19-parked-status-board-hygiene.md
Triage + marker predicate: src/rnd/v0.1.9/2026.07.19-parked-status-marker-predicate-and-triage.md
Store rows: 954428b3 (design) · d291028e (seat 2) · 6b61a22c (this seat)

WHAT THIS FILE IS FOR
---------------------
`task_store_owed` carries TWO deliberately independent expressions of one rule:

    park_is_active( status, next_chase_ts, now )   — Python, for in-memory readers
    park_is_active_clause( model, now )            — SQLAlchemy, for the DB readers

Neither calls the other and they share no helper. That duplication is LICENSED
only because this file proves them identical — and proves it in a way that can
FAIL. A twin pair sharing an implementation cannot be mutation-tested: an
equivalence test over a shared helper proves only that the helper equals itself.

⚠️ THE POINT OF THE MUTANT SWEEP (§ MUTANTS below)
A green test that cannot go red is not a green. This fleet shipped exactly that
defect twice in one week. So every guard here is verified RED against a mutant
that perturbs ONE expression — if a mutant passes, the guard is decorative and
the sweep fails LOUD rather than reporting success.

WHY SQLITE AND NOT POSTGRES
---------------------------
Both clause builders take `model` as a PARAMETER rather than importing TaskItem,
so the SQL twin can be exercised against a minimal two-column model on in-memory
SQLite. That keeps the parity gate a true unit test: no Postgres, no persistent
state, no queue enqueues, well under 2 minutes ⇒ :7999-eligible per CLAUDE.md
§TESTING VENUES.

⚠️ FIDELITY LIMIT, STATED RATHER THAN PAPERED OVER: SQLite has no native
timestamptz. Timestamps here are stored NAIVE-UTC and `now` is passed naive-UTC
so the comparison is well-defined on both sides. That exercises the LOGIC of the
twins faithfully (status guard, NULL arm, strict-vs-inclusive boundary) but it
does NOT prove Postgres's tz-aware comparison semantics. The aware-boundary case
needs a Postgres-backed integration run on :8000 — tracked, not silently assumed.
See test_tz_fidelity_limit_is_documented_not_assumed.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import Column, DateTime, Integer, String, and_, create_engine, not_, or_
from sqlalchemy.orm import declarative_base, sessionmaker

from cosa.rest.task_store_owed import (
    OWED_BASE_STATUSES,
    PARK_LEGAL_FROM_STATUSES,
    PARK_STATUS,
    is_owed,
    is_park_legal_from,
    owed_clause,
    owed_status_clause,
    owed_status_row,
    park_is_active,
    park_is_active_clause,
)
from cosa.rest.task_store_rules import TERMINAL_STATUSES, VALID_STATUSES

# ⚠️ RUNNING THIS SUITE WHILE PEERS ARE EDITING — AND THE TRAP INSIDE THAT ADVICE
# (Krishna 🦚 + Clayton 😎, 2026-07-19)
#
# A suite result is evidence only about the tree AS IT EXISTED WHEN THE RUN STARTED.
# Three seats wrote this build concurrently, and a run whose green began before
# someone's edit landed is a false green with a timestamp on it.
#
# 🔴 BUT "it was probably a stale run" IS THE MOST DANGEROUS TOOL IN THIS BOX: it
# explains away a real red with a mechanism that requires no fix, and it is
# UNFALSIFIABLE unless the re-run happens on UNCHANGED FILES. It was used here on
# 4 migration failures that were REAL defects — a migration-id collision and an
# ORM/DDL drift, both caught by guards doing exactly their job. They went green
# because they were FIXED, and the fix was read as confirmation of staleness.
#
# ⇒ A STALE-RUN CLAIM NEEDS ITS OWN CONTROL. Green on a re-run is evidence of
#   staleness ONLY if no file changed in between; otherwise you have observed a
#   fix, not a phantom. The one claim that survived that bar did so because the
#   reported failures named tests that DO NOT EXIST on the settled tree — a check
#   falsifiable independently of anyone's edits.
#
# ⇒ DEFAULT: assume a red you did not cause is REAL, and go find the change that
#   made it green.

Base = declarative_base()


class ParityRow( Base ):
    """
    Minimal stand-in for TaskItem carrying only the two columns the twins read.

    Deliberately NOT the real TaskItem: that model needs JSONB + UUID + a
    Postgres server. The clause builders are model-parameterized, so a two-column
    model exercises the identical expression tree.
    """
    __tablename__   = "parity_rows"
    id              = Column( Integer, primary_key=True )
    status          = Column( String )
    next_chase_ts   = Column( DateTime )


# ---------------------------------------------------------------------------
# The matrix — every status crossed with every chase shape
# ---------------------------------------------------------------------------

NOW = datetime( 2026, 7, 19, 12, 0, 0 )

CHASE_SHAPES = {
    "past"    : NOW - timedelta( hours=6 ),
    "now"     : NOW,                            # the boundary — >= vs > lives here
    "future"  : NOW + timedelta( hours=6 ),
    "null"    : None,                           # the MODAL shape on the real board
}


def _build_matrix():
    """
    Every VALID_STATUSES value crossed with every chase shape.

    Ensures:
        - returns a list of ( id, status, chase_datetime_or_None )
        - covers all 8 statuses x 4 chase shapes = 32 rows
    """
    rows = []
    next_id = 1
    for status in VALID_STATUSES:
        for shape in CHASE_SHAPES:
            rows.append( ( next_id, status, CHASE_SHAPES[ shape ] ) )
            next_id += 1
    return rows


MATRIX = _build_matrix()


@pytest.fixture
def session():
    """
    In-memory SQLite seeded with the full matrix. Function-scoped: each test gets
    a private database, so nothing leaks between tests and nothing persists.
    """
    engine = create_engine( "sqlite:///:memory:" )
    Base.metadata.create_all( engine )
    sess = sessionmaker( bind=engine )()
    for row_id, status, chase in MATRIX:
        sess.add( ParityRow( id=row_id, status=status, next_chase_ts=chase ) )
    sess.commit()
    yield sess
    sess.close()


def _python_side( predicate=park_is_active ):
    """Ids the PYTHON twin calls park-active. `predicate` is injectable for mutants."""
    return { row_id for row_id, status, chase in MATRIX if predicate( status, chase, NOW ) }


def _sql_side( session, clause_builder=park_is_active_clause ):
    """Ids the SQL twin calls park-active. `clause_builder` is injectable for mutants."""
    rows = session.query( ParityRow ).filter( clause_builder( ParityRow, NOW ) ).all()
    return { r.id for r in rows }


def _admission_python_side( predicate=owed_status_row ):
    """Ids the row-level ADMISSION twin calls owed. Injectable for mutants."""
    return { row_id for row_id, status, chase in MATRIX if predicate( status, chase, NOW ) }


def _admission_sql_side( session, clause_builder=owed_status_clause ):
    """Ids the SQL ADMISSION twin calls owed. Injectable for mutants."""
    rows = session.query( ParityRow ).filter( clause_builder( ParityRow, NOW ) ).all()
    return { r.id for r in rows }


# ===========================================================================
# 1. THE PARITY GATE — set equality, both directions
# ===========================================================================

def test_admission_twins_agree_exactly_on_the_full_matrix( session ):
    """
    🔴 THE PRIMARY MERGE GATE — `owed_status_clause` ≡ `owed_status_row`.

    THIS is the selection R2 (the Stop-hook oracle) actually reads. Everything the
    fleet gets poked about flows through this expression.

    ⚠️ WHY IT OUTRANKS THE SUPPRESSION PAIR (Krishna 🦚's catch, 2026-07-19):
    for a while the ADMISSION half had no row-level twin at all, so the gate could
    only prove SUPPRESSION. That left the riskiest expression in the module as the
    one nothing compared — and admission is where EVERY defect in this build has
    lived: subtraction that cannot re-admit an expired row, and the per-status
    double-count. The suppression pair is now the secondary assertion.

    Set equality on ids, both directions. Not a count match: a count match passes
    when two rows swap sides, which is exactly the divergence that would be
    invisible and permanent.
    """
    py  = _admission_python_side()
    sql = _admission_sql_side( session )

    assert py == sql, (
        f"ADMISSION TWIN DIVERGENCE — the owed set the Stop hook reads is wrong.\n"
        f"  row-twin only : {sorted( py - sql )}\n"
        f"  sql-twin only : {sorted( sql - py )}"
    )
    assert len( py ) > 0, "matrix produced zero owed rows — the gate is vacuous"


def test_admission_row_twin_is_independent_of_the_suppression_predicate():
    """
    The admission twin must NOT be implemented by calling `park_is_active`.

    If it delegates, the mutant sweep cannot move the two sides apart and the
    primary gate becomes decorative — an equivalence test over a shared helper
    proves only that the helper equals itself.
    """
    import ast
    import inspect

    tree  = ast.parse( inspect.getsource( owed_status_row ) )
    calls = { n.func.id for n in ast.walk( tree )
              if isinstance( n, ast.Call ) and isinstance( n.func, ast.Name ) }

    assert "park_is_active" not in calls, (
        "owed_status_row delegates to park_is_active — the twins are no longer "
        "independent and the primary parity gate cannot go red"
    )
    assert "is_owed" not in calls, "owed_status_row delegates to is_owed — same problem"


def test_twins_agree_exactly_on_the_full_matrix( session ):
    """
    THE MERGE GATE. Set equality on ids, both directions — NOT a count match.

    A count match passes when two rows swap sides, which is precisely the
    divergence that would be invisible and permanent.
    """
    py  = _python_side()
    sql = _sql_side( session )

    assert py == sql, (
        f"TWIN DIVERGENCE.\n"
        f"  python-only : {sorted( py - sql )}\n"
        f"  sql-only    : {sorted( sql - py )}"
    )
    # A gate that passes vacuously proves nothing: assert the matrix actually
    # contains park-active rows, so set-equality is equality of NON-EMPTY sets.
    assert len( py ) > 0, "matrix produced zero park-active rows — the gate is vacuous"


def test_only_parked_rows_are_ever_park_active():
    """The status guard is the first conjunct on both sides; nothing else can be park-active."""
    for row_id, status, chase in MATRIX:
        if park_is_active( status, chase, NOW ):
            assert status == PARK_STATUS, f"non-parked status {status!r} reported park-active"


# ===========================================================================
# 2. THE FOUR MANDATED PROOFS
# ===========================================================================

def test_expired_park_rejoins_owed( session ):
    """
    MANDATED PROOF 1: a parked row whose next_chase_ts has PASSED rejoins owed.

    Self-expiry is computed at READ time — no daemon, no sweeper, no human.
    """
    past = CHASE_SHAPES[ "past" ]
    assert park_is_active( PARK_STATUS, past, NOW ) is False
    assert is_owed( PARK_STATUS, past, NOW ) is True

    owed_ids = { r.id for r in session.query( ParityRow ).filter( owed_status_clause( ParityRow, NOW ) ).all() }
    expired  = next( rid for rid, s, c in MATRIX if s == PARK_STATUS and c == past )
    assert expired in owed_ids, "an EXPIRED parked row did not rejoin the owed set"


def test_park_active_row_is_suppressed_but_expired_one_is_not( session ):
    """
    MANDATED PROOF 2 (the visibility half): park-active is hidden, expired is not.

    NEGATIVE CONTROL — without this, proof 1 passes for the wrong reason: a clause
    that admits EVERYTHING also admits the expired row.
    """
    owed_ids = { r.id for r in session.query( ParityRow ).filter( owed_status_clause( ParityRow, NOW ) ).all() }
    active   = next( rid for rid, s, c in MATRIX if s == PARK_STATUS and c == CHASE_SHAPES[ "future" ] )

    assert active not in owed_ids, "a park-ACTIVE row leaked into the owed set — parking buys no silence"


def test_boundary_chase_equals_now_is_owed_not_parked( session ):
    """
    MANDATED PROOF 3: chase EXACTLY == now resolves OWED on BOTH sides.

    The ruling is >= for owed, i.e. strictly > for park-active. This is the case a
    naive/aware timezone mismatch would surface first, and the case an internally
    sourced clock would make unreachable.
    """
    assert park_is_active( PARK_STATUS, NOW, NOW ) is False, "boundary used > instead of >= for owed"

    boundary = next( rid for rid, s, c in MATRIX if s == PARK_STATUS and c == NOW )
    assert boundary not in _sql_side( session ), "SQL twin disagrees with Python at the boundary"


def test_null_chase_fails_toward_owed_on_both_sides( session ):
    """
    MANDATED PROOF 4: a parked row with a NULL chase is OWED, never silent.

    ⚠️ NOT AN EDGE CASE. next_chase_ts is NULL on all 70 queued rows measured
    2026-07-19 — NULL is the MODAL shape. A wrong NULL arm does not silence one
    row, it silences the entire board. (Krishna 🦚's escalation; measurement in
    the triage artifact §2.1.)

    SQL note: the clause must yield FALSE, not NULL. Three-valued logic would drop
    the row from BOTH sides of a filter, i.e. from the owed count AND the board.
    """
    assert park_is_active( PARK_STATUS, None, NOW ) is False
    assert is_owed( PARK_STATUS, None, NOW ) is True

    null_row = next( rid for rid, s, c in MATRIX if s == PARK_STATUS and c is None )
    assert null_row not in _sql_side( session ), "SQL twin treated a NULL chase as park-active"

    owed_ids = { r.id for r in session.query( ParityRow ).filter( owed_status_clause( ParityRow, NOW ) ).all() }
    assert null_row in owed_ids, "a NULL-chase parked row vanished from the owed set — three-valued-logic drop"


# ===========================================================================
# 3. THE ADMISSION SET — restoration, not widening
# ===========================================================================

def test_owed_set_is_exactly_queued_in_progress_plus_expired_parked( session ):
    """
    The `owed_only=True` set, pinned as an EXACT id set against the fixture.

    Exact, not a delta and not a truthy count — see the double-count guard below
    for why an exact total is the only form that catches a summation defect.
    """
    owed_ids = { r.id for r in session.query( ParityRow ).filter( owed_status_clause( ParityRow, NOW ) ).all() }

    expected = set()
    for row_id, status, chase in MATRIX:
        if status in PARK_LEGAL_FROM_STATUSES:
            expected.add( row_id )
        elif status == PARK_STATUS and not park_is_active( status, chase, NOW ):
            expected.add( row_id )

    assert owed_ids == expected, (
        f"admission set wrong.\n  missing: {sorted( expected - owed_ids )}\n"
        f"  extra  : {sorted( owed_ids - expected )}"
    )


def test_admission_is_restoration_not_widening():
    """
    The proof that re-admitting expired-parked rows widens nothing:
    park is LEGAL only from the same statuses the owed set already contained.

    ⚠️ THE LOAD-BEARING INVARIANT. If these two sets ever diverge, the
    "exact restoration" claim silently becomes a widening (or a narrowing) and
    NO twin-parity assertion would notice — both twins would still agree.
    """
    for status in VALID_STATUSES:
        if is_park_legal_from( status ):
            assert status in PARK_LEGAL_FROM_STATUSES

    # SUBSET, not equality (Clayton 😎's correction, 2026-07-19, and he is right):
    # NARROWING park-legality — say, legal only from "queued" — keeps restoration
    # exact and must stay legal. Only ESCAPING the owed base set breaks the proof.
    # An equality pin would forbid a safe change AND teach the next reader the
    # wrong invariant, which is worse than the missing guard it replaced.
    assert set( PARK_LEGAL_FROM_STATUSES ) <= set( OWED_BASE_STATUSES ), (
        f"park-legality {PARK_LEGAL_FROM_STATUSES} escapes the owed base set "
        f"{OWED_BASE_STATUSES} — re-admitting expired-parked rows would WIDEN what "
        f"the Stop hook and arbiter count, not restore it"
    )

    for status in ( "blocked", "claimed", "review", "done", "dropped", PARK_STATUS ):
        assert is_park_legal_from( status ) is False, f"park must be illegal from {status!r}"


def test_blocked_claimed_review_membership_is_unchanged( session ):
    """No reader's owed definition changes except for parked rows (the NARROW ruling)."""
    owed_ids = { r.id for r in session.query( ParityRow ).filter( owed_status_clause( ParityRow, NOW ) ).all() }
    for row_id, status, _chase in MATRIX:
        if status in ( "blocked", "claimed", "review" ):
            assert row_id not in owed_ids, f"{status!r} row leaked into the owed set — this is a widening"


def test_parked_is_non_terminal():
    """Parking buys bounded silence, never an exit. A terminal `parked` would be an exit."""
    assert PARK_STATUS in VALID_STATUSES
    assert PARK_STATUS not in TERMINAL_STATUSES


# ===========================================================================
# 4. THE COUNT SEAM — where R2 diverges silently
# ===========================================================================

def test_count_equals_len_of_rows( session ):
    """
    The COUNT(*) seam. R2 (Stop hook) receives a count, never rows, so this is the
    one boundary where the page and the poke can disagree with nothing to show it.
    """
    clause    = owed_status_clause( ParityRow, NOW )
    row_count = len( session.query( ParityRow ).filter( clause ).all() )
    agg_count = session.query( ParityRow ).filter( clause ).count()

    assert row_count == agg_count, f"COUNT(*) says {agg_count}, rows say {row_count}"


def test_expired_park_is_counted_exactly_once( session ):
    """
    🔴 THE DOUBLE-COUNT GUARD (Krishna 🦚's defect #4).

    The retired shape had `query_owed` LOOP the status tuple and SUM per-status
    counts. Under per-status admission an expired-parked row is admitted on the
    `queued` pass AND again on the `in_progress` pass — counted TWICE. Parking a
    row would make the board look BUSIER than never parking it. The feature
    inverts on its own axis.

    ⚠️ NOTHING ELSE IN THIS FILE CATCHES THAT. The predicate is correct per row;
    the arithmetic error lives in the CALLER's summation. Every twin-parity
    assertion passes green while the count is wrong — a per-row-correct predicate
    summed wrongly is invisible to a predicate-level gate.

    Asserted as an EXACT total against a known fixture. Never a delta, never
    "> 0": a delta assertion passes at 2 when the baseline was also doubled.
    """
    clause = owed_status_clause( ParityRow, NOW )
    total  = session.query( ParityRow ).filter( clause ).count()

    # 2 park-legal statuses x 4 chase shapes = 8, plus parked rows whose chase is
    # past / now / null = 3. Future-chased parked row is the only one suppressed.
    expected = len( PARK_LEGAL_FROM_STATUSES ) * len( CHASE_SHAPES ) + 3
    assert total == expected, f"owed count is {total}, expected exactly {expected} (double-count?)"

    parked_in_owed = [
        r.id for r in session.query( ParityRow ).filter( clause ).all()
        if r.status == PARK_STATUS
    ]
    assert len( parked_in_owed ) == len( set( parked_in_owed ) ), "a parked row appears TWICE in the owed set"


# ===========================================================================
# 5. MUTANTS — every guard above is verified RED
# ===========================================================================
#
# Each mutant perturbs exactly ONE expression on ONE side. The parity gate MUST
# reject it. A mutant that survives means the guard it targets is decorative.

def _mutant_boundary_inclusive( status, next_chase_ts, now ):
    """MUTANT: `>=` instead of `>` — a chase that has come due stays silent."""
    if status != PARK_STATUS or next_chase_ts is None:
        return False
    return next_chase_ts >= now


def _mutant_null_is_parked( status, next_chase_ts, now ):
    """MUTANT: NULL chase treated as park-active — silences the whole board."""
    if status != PARK_STATUS:
        return False
    if next_chase_ts is None:
        return True
    return next_chase_ts > now


def _mutant_no_status_guard( status, next_chase_ts, now ):
    """MUTANT: status guard dropped — any row with a future chase looks parked."""
    if next_chase_ts is None:
        return False
    return next_chase_ts > now


def _mutant_clause_null_is_parked( model, now ):
    """MUTANT (SQL side): drop the IS NOT NULL arm, letting NULL fall through."""
    return or_( and_( model.status == PARK_STATUS, model.next_chase_ts > now ),
                and_( model.status == PARK_STATUS, model.next_chase_ts.is_( None ) ) )


def _mutant_clause_no_status_guard( model, now ):
    """MUTANT (SQL side): drop the status conjunct."""
    return and_( model.next_chase_ts.isnot( None ), model.next_chase_ts > now )


def _mutant_clause_drop_null_guard( model, now ):
    """
    MUTANT (SQL side): drop the `IS NOT NULL` arm.

    ☠️ THIS ONE SURVIVED THE FIRST SWEEP, and finding that was the point.

    It is INVISIBLE in a positive filter: `NULL > now` evaluates to NULL, and a
    WHERE clause discards NULL rows anyway, so the park-active set is unchanged.
    The arm's entire protective value lives in the NEGATED path —
    `not_( and_( TRUE, NULL ) )` is NULL, which drops the row from the owed set
    AND the board simultaneously. On a board where NULL is the modal chase value,
    that suppresses every row on the board, not one.

    ⇒ A parity gate that only tests the POSITIVE direction cannot see this class
    of defect at all. That is why the suppression/admission assertion below is a
    separate test and not a corollary.
    """
    return and_( model.status == PARK_STATUS, model.next_chase_ts > now )


MUTANTS_PY = [
    ( "boundary >= instead of >", _mutant_boundary_inclusive ),
    ( "NULL chase treated as parked", _mutant_null_is_parked ),
    ( "status guard dropped", _mutant_no_status_guard ),
]

MUTANTS_SQL = [
    ( "SQL NULL arm inverted", _mutant_clause_null_is_parked ),
    ( "SQL status guard dropped", _mutant_clause_no_status_guard ),
]

# Mutants invisible to POSITIVE-direction parity — they only diverge once the
# clause is negated. Swept separately below; see _mutant_clause_drop_null_guard.
MUTANTS_SQL_NEGATED_ONLY = [
    ( "SQL IS NOT NULL arm dropped", _mutant_clause_drop_null_guard ),
]


@pytest.mark.parametrize(
    "name,mutant", MUTANTS_SQL_NEGATED_ONLY, ids=[ m[ 0 ] for m in MUTANTS_SQL_NEGATED_ONLY ]
)
def test_negated_path_catches_three_valued_logic_mutants( session, name, mutant ):
    """
    THE NEGATED-DIRECTION GATE.

    Asserts the suppression path (`not_( park_is_active_clause )`) still admits
    every non-park-active row under the mutant. A three-valued-logic regression
    makes NULL-chase rows vanish from BOTH sides of the filter — the row stops
    being owed AND stops being visible, which is the worst available outcome and
    the one a positive-only parity test cannot see.
    """
    mutated_suppression = not_( mutant( ParityRow, NOW ) )
    survivors = { r.id for r in session.query( ParityRow ).filter( mutated_suppression ).all() }
    expected  = { rid for rid, status, chase in MATRIX if not park_is_active( status, chase, NOW ) }

    assert survivors != expected, (
        f"MUTANT SURVIVED: {name!r} — the negated path cannot detect it either, "
        f"so NULL-chase rows can silently leave the board"
    )


def test_suppression_path_keeps_null_chase_rows_visible( session ):
    """
    The positive statement of the above: under the REAL clause, negation admits
    every non-park-active row — including NULL-chase parked rows.

    This is the assertion the surviving mutant was hiding behind.
    """
    survivors = { r.id for r in session.query( ParityRow ).filter( owed_clause( ParityRow, NOW ) ).all() }
    expected  = { rid for rid, status, chase in MATRIX if not park_is_active( status, chase, NOW ) }

    assert survivors == expected, (
        f"suppression path lost rows to three-valued logic.\n"
        f"  vanished: {sorted( expected - survivors )}"
    )


def _mutant_admission_drops_expired_parked( status, next_chase_ts, now ):
    """
    MUTANT (admission): drop the expired-parked arm entirely.

    ☠️ THE HEADLINE DEFECT OF THIS WHOLE BUILD. This is what the retired
    "subtractive / additive-on-top" shape actually did: an expired parked row
    keeps status="parked", so a set built only from queued/in_progress never
    re-admits it. Parking would buy PERMANENT silence from the one reader that
    fires the pokes — the exact opposite of the feature.
    """
    return status in OWED_BASE_STATUSES


def _mutant_admission_widens_to_all_non_terminal( status, next_chase_ts, now ):
    """
    MUTANT (admission): admit every non-terminal status.

    Would drag blocked / claimed / review into R2's owed count — a WIDENING, not
    the exact restoration the design promises. It reads like a simplification.
    """
    return status not in TERMINAL_STATUSES


def _mutant_admission_never_expires( status, next_chase_ts, now ):
    """MUTANT (admission): parked never rejoins, whatever the chase says."""
    return status in OWED_BASE_STATUSES and status != PARK_STATUS


MUTANTS_ADMISSION = [
    ( "admission drops expired-parked arm", _mutant_admission_drops_expired_parked ),
    ( "admission widens to all non-terminal", _mutant_admission_widens_to_all_non_terminal ),
    ( "admission never expires a park", _mutant_admission_never_expires ),
]


@pytest.mark.parametrize(
    "name,mutant", MUTANTS_ADMISSION, ids=[ m[ 0 ] for m in MUTANTS_ADMISSION ]
)
def test_admission_mutant_breaks_the_primary_gate( session, name, mutant ):
    """
    Every admission-side mutant MUST diverge from the real SQL admission clause.

    These are the mutants that had NOTHING watching them until `owed_status_row`
    landed. If one survives, the owed set the fleet is poked about can be wrong
    with the whole suite green.
    """
    assert _admission_python_side( mutant ) != _admission_sql_side( session ), (
        f"MUTANT SURVIVED: {name!r} — the PRIMARY gate cannot detect it, so the "
        f"owed set ships unproven"
    )


def test_the_fixture_contains_a_row_that_would_move( session ):
    """
    ☠️ THE DISCRIMINATION CHECK — does this fixture contain a row whose
    membership DEPENDS on the behaviour under test?

    Reference case (Krishna 🦚, 2026-07-19): a live probe scoped to a persona with
    one queued row and no blocked rows returned 1 whether the flag was honored or
    ignored, so the control matched the treatment and the probe proved nothing.
    A fixture with no discriminating row cannot discriminate, however careful the
    control around it.

    So: assert the matrix contains at least one row of EACH kind whose
    classification would flip under a wrong implementation.
    """
    parked = [ ( rid, c ) for rid, s, c in MATRIX if s == PARK_STATUS ]

    assert any( c is not None and c < NOW for _rid, c in parked ), "no EXPIRED parked row — expiry is untested"
    assert any( c is not None and c > NOW for _rid, c in parked ), "no ACTIVE parked row — suppression is untested"
    assert any( c is None for _rid, c in parked ), "no NULL-chase parked row — the modal shape is untested"
    assert any( c == NOW for _rid, c in parked ), "no BOUNDARY parked row — >= vs > is untested"
    assert any( s in ( "blocked", "claimed", "review" ) for _rid, s, _c in MATRIX ), (
        "no non-owed non-terminal row — a widening would be invisible"
    )

    # And the discriminator itself: the owed set must NOT equal the whole matrix,
    # or every "is it in the owed set?" assertion passes for free.
    owed = _admission_sql_side( session )
    assert 0 < len( owed ) < len( MATRIX ), (
        f"owed set is {len( owed )} of {len( MATRIX )} rows — it does not discriminate"
    )


@pytest.mark.parametrize( "name,mutant", MUTANTS_PY, ids=[ m[ 0 ] for m in MUTANTS_PY ] )
def test_python_mutant_breaks_parity( session, name, mutant ):
    """Each Python-side mutant MUST diverge from the real SQL twin."""
    assert _python_side( mutant ) != _sql_side( session ), (
        f"MUTANT SURVIVED: {name!r} — the parity gate cannot detect it, so it is decorative"
    )


@pytest.mark.parametrize( "name,mutant", MUTANTS_SQL, ids=[ m[ 0 ] for m in MUTANTS_SQL ] )
def test_sql_mutant_breaks_parity( session, name, mutant ):
    """Each SQL-side mutant MUST diverge from the real Python twin."""
    assert _python_side() != _sql_side( session, mutant ), (
        f"MUTANT SURVIVED: {name!r} — the parity gate cannot detect it, so it is decorative"
    )


def test_the_mutant_sweep_itself_is_connected( session ):
    """
    ☠️ THE CONTROL ON THE CONTROL.

    A mutant sweep that comes back all-clean is far more likely to be a
    disconnected harness than a perfect implementation. This asserts the sweep is
    actually wired: the REAL predicate must PASS parity (so the harness is not
    rejecting everything) while at least one mutant FAILS it (so the harness is
    not accepting everything).

    Without this, a bug in `_python_side` / `_sql_side` that returned the same
    constant for every input would make every mutant test above pass vacuously.
    """
    assert _python_side() == _sql_side( session ), "harness rejects the REAL predicate — sweep is miscalibrated"
    assert _python_side( _mutant_null_is_parked ) != _sql_side( session ), "harness accepts a known mutant — sweep is disconnected"


# ===========================================================================
# 6. IMPORT PURITY — the guard that outlives this build
# ===========================================================================

def test_task_store_rules_stays_free_of_sqlalchemy():
    """
    `task_store_rules` declares itself PURE ("no DB, no HTTP") and is imported by
    the Stop-hook path. A SQLAlchemy import there would drag the ORM into the
    hook's import graph — an invisible latency regression, and a docstring that
    lies.

    Asserted on the RESOLVED module graph, not on source text: a grep for
    "sqlalchemy" passes happily while a transitive import drags it in anyway.

    ⚠️ RUN IN A SUBPROCESS, DELIBERATELY. The honest way to measure a module's
    import graph is to start from a clean interpreter. Doing that in-process means
    purging `sys.modules`, which corrupts SQLAlchemy's global registry for every
    test that runs afterwards — measured here: it broke a later test in this same
    file. A test that mutates shared interpreter state to make its own
    measurement is buying its result with someone else's correctness.
    """
    import subprocess
    import sys
    import textwrap

    probe = textwrap.dedent( """
        import sys
        import cosa.rest.task_store_rules
        leaked = sorted( m for m in sys.modules if m == "sqlalchemy" or m.startswith( "sqlalchemy." ) )
        print( "|".join( leaked[ :5 ] ) )
    """ )

    result = subprocess.run(
        [ sys.executable, "-c", probe ],
        capture_output=True, text=True, timeout=60,
    )

    assert result.returncode == 0, f"purity probe failed to run: {result.stderr[ -500: ]}"
    leaked = [ m for m in result.stdout.strip().split( "|" ) if m ]
    assert not leaked, (
        f"task_store_rules pulled SQLAlchemy into its import graph: {leaked} — "
        f"its purity docstring is now false and the Stop-hook path pays for it"
    )


def test_owed_module_imports_rules_and_never_the_reverse():
    """
    The dependency runs owed -> rules, one direction only. A cycle would break purity.

    Asserted over the AST's actual import nodes, NOT a substring search of the
    source. `task_store_rules` legitimately NAMES `task_store_owed` in prose
    (explaining where the predicate lives), and a text grep cannot tell a comment
    from an import — it fails on documentation, which trains the next reader to
    delete the guard rather than trust it.
    """
    import ast
    import inspect

    import cosa.rest.task_store_rules as rules

    tree     = ast.parse( inspect.getsource( rules ) )
    imported = set()
    for node in ast.walk( tree ):
        if isinstance( node, ast.Import ):
            imported.update( alias.name for alias in node.names )
        elif isinstance( node, ast.ImportFrom ) and node.module:
            imported.add( node.module )

    offenders = [ m for m in imported if "task_store_owed" in m ]
    assert not offenders, f"task_store_rules imports {offenders} — dependency cycle"

    sqla = [ m for m in imported if m == "sqlalchemy" or m.startswith( "sqlalchemy." ) ]
    assert not sqla, f"task_store_rules imports {sqla} — its purity docstring is false"


# ===========================================================================
# 7. FIDELITY LIMIT — named, not assumed
# ===========================================================================

def test_tz_fidelity_limit_is_documented_not_assumed():
    """
    ⚠️ THIS FILE DOES NOT PROVE POSTGRES TIMEZONE SEMANTICS.

    SQLite has no timestamptz; this suite stores naive-UTC on both sides so the
    comparison is well-defined. That faithfully exercises the twins' LOGIC but not
    Postgres's aware-comparison behaviour at the boundary.

    What IS proven here: the Python twin coerces a naive value to UTC rather than
    raising, so a naive/aware mix cannot silently shift the boundary by the UTC
    offset. The aware-vs-aware Postgres boundary still needs an integration run
    on :8000 — recorded so the gap is visible rather than implied-clean.
    """
    from datetime import timezone

    aware_now    = datetime( 2026, 7, 19, 12, 0, 0, tzinfo=timezone.utc )
    naive_future = datetime( 2026, 7, 19, 18, 0, 0 )

    assert park_is_active( PARK_STATUS, naive_future, aware_now ) is True

    naive_past = datetime( 2026, 7, 19, 6, 0, 0 )
    assert park_is_active( PARK_STATUS, naive_past, aware_now ) is False


def test_unparseable_chase_fails_toward_owed():
    """A malformed chase string is VISIBLE work, never silence. Must not raise."""
    assert park_is_active( PARK_STATUS, "not-a-date", NOW ) is False
    assert park_is_active( PARK_STATUS, 12345, NOW ) is False
    assert is_owed( PARK_STATUS, "not-a-date", NOW ) is True


def test_iso_string_chase_is_accepted():
    """Readers hand this predicate ISO strings off the wire as well as datetimes."""
    future_iso = ( NOW + timedelta( hours=6 ) ).isoformat()
    past_iso   = ( NOW - timedelta( hours=6 ) ).isoformat()

    assert park_is_active( PARK_STATUS, future_iso, NOW ) is True
    assert park_is_active( PARK_STATUS, past_iso, NOW ) is False
    assert park_is_active( PARK_STATUS, future_iso.replace( "+00:00", "Z" ), NOW ) is True


def test_terminal_rows_are_never_owed():
    """done/dropped are terminal on every path."""
    for status in TERMINAL_STATUSES:
        assert is_owed( status, None, NOW ) is False
        assert is_owed( status, CHASE_SHAPES[ "past" ], NOW ) is False


def test_owed_clause_suppresses_without_admitting( session ):
    """
    `owed_clause` is SUPPRESSION ONLY — it removes park-active rows and does not
    re-admit anything. Pinned so nobody mistakes it for the admission set: using
    it alone on top of a ("queued","in_progress") filter reproduces the exact bug
    the one-call admission was built to fix.
    """
    suppressed = { r.id for r in session.query( ParityRow ).filter( owed_clause( ParityRow, NOW ) ).all() }
    admitted   = { r.id for r in session.query( ParityRow ).filter( owed_status_clause( ParityRow, NOW ) ).all() }

    assert admitted < suppressed, "the admission set must be a strict subset of the suppression set"
    for row_id, status, _c in MATRIX:
        if status in ( "blocked", "done" ):
            assert row_id in suppressed, "suppression-only wrongly dropped a non-parked row"


# ===========================================================================
# COVERAGE — `owed_status_row`'s OWN coercion arms
# ===========================================================================
#
# Added 2026-07-19 by the park_reason-staleness build (row 4ce27ba1), closing a
# pre-existing gap rather than a new one: `task_store_owed` measured 94% with
# lines 532-535 and branches 226->228 / 539->541 unreached. Seat 1's staleness
# work is provably not the cause — that diff is 3 hunks, purely additive, 0
# deletions, and touches neither function's body.
#
# ⚠️ WHY THE GAP EXISTED, because it will re-open otherwise: `owed_status_row`
# does its OWN coercion and does NOT call `park_is_active` — that INDEPENDENCE is
# deliberate and load-bearing (it is what lets the mutant sweep move one side).
# But independence DUPLICATES THE COVERAGE DUTY, and only `park_is_active`'s arms
# had tests. The string and tz arms above prove nothing about the twin below.
# Every future arm added to one of these functions needs its own test in both.

def test_owed_status_row_accepts_iso_string_chases():
    """The admission twin takes ISO strings off the wire, exactly as `park_is_active` does."""
    future_iso = ( NOW + timedelta( hours=6 ) ).isoformat()
    past_iso   = ( NOW - timedelta( hours=6 ) ).isoformat()

    assert owed_status_row( PARK_STATUS, future_iso, NOW ) is False   # still silenced
    assert owed_status_row( PARK_STATUS, past_iso, NOW )   is True    # chase came due
    assert owed_status_row( PARK_STATUS, future_iso.replace( "+00:00", "Z" ), NOW ) is False


def test_owed_status_row_fails_toward_owed_on_junk():
    """
    A malformed or non-timestamp chase makes the row OWED on the admission twin —
    the same fail-loud direction `park_is_active` takes, asserted here because
    the two functions share no code and one cannot vouch for the other.
    """
    assert owed_status_row( PARK_STATUS, "not-a-date", NOW ) is True
    assert owed_status_row( PARK_STATUS, 12345, NOW )        is True


def test_owed_status_row_handles_an_already_aware_chase():
    """
    An aware chase takes the other arm of the tz normalization — the arm the
    all-naive matrix never reaches.
    """
    aware_future = ( NOW + timedelta( hours=6 ) ).replace( tzinfo=timezone.utc )
    aware_past   = ( NOW - timedelta( hours=6 ) ).replace( tzinfo=timezone.utc )

    assert owed_status_row( PARK_STATUS, aware_future, NOW ) is False
    assert owed_status_row( PARK_STATUS, aware_past, NOW )   is True


def test_park_is_active_handles_an_already_aware_now():
    """
    An aware `now` takes the else-arm of the comparison-instant ternary. Both
    sides of that ternary must be exercised: a reader passing an aware `now` is
    the normal case on the live board, where timestamps come back tz-aware from
    Postgres, and the naive case is the one the fixtures happen to use.
    """
    aware_now    = NOW.replace( tzinfo=timezone.utc )
    aware_future = ( NOW + timedelta( hours=6 ) ).replace( tzinfo=timezone.utc )

    assert park_is_active( PARK_STATUS, aware_future, aware_now ) is True
    assert owed_status_row( PARK_STATUS, aware_future, aware_now ) is False
