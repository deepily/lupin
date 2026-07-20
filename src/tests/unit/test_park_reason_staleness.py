"""
THE STALENESS GATE for `park_reason` (PARK-REASON-STALENESS build, 2026-07-19).

Seat 3 (session 092d7ae6). Design: src/rnd/v0.1.9/2026.07.19-park-reason-staleness-detection.md
Store row: 4ce27ba1. Builds on `a877e7b3` (parked status), whose behavior AC7 freezes.

WHAT THIS FILE PROVES — AND WHAT IT DOES NOT
--------------------------------------------
It proves the PREDICATE: that `park_reason_is_stale` and its SQL twin select
identical row sets across the boundary matrix, that only parked rows can ever
report stale, and that every guard in both twins is verified RED against a
mutant.

⚠️ IT IS SILENT ON TWO THINGS, STATED HERE RATHER THAN DISCOVERED LATER (§6
rule 14 — a control licenses only what its scope covers):

  1. WHETHER A ROW CAN EVER REACH `parked` CARRYING A CAPTURE TIMESTAMP. Rows
     here are constructed directly in SQLite. That is exactly the licensing
     error §8 of the design records: a 33-passed parity gate over constructed
     rows was read as "the feature works" while `park_reason` had no wire path
     at all. This file does not re-license reachability. AC6-live
     (test_parked_status_ac6_live.py, run ts-0e8c0fb2) covers it.

  2. THE §3.4 ORDERING — that park captures the POST-write `updated_ts`. That
     is a property of the WRITE, not of the predicate, and AC3 demands it be
     asserted as EQUALITY rather than sampled through `stale == False`. A
     predicate test cannot see it: `stale == False` holds for the correct
     implementation AND for a `now()`-written-after implementation that leaves
     an undetectable amendment window. AC3 and live-AC4 therefore belong to a
     Postgres-backed integration run, NOT here.

  (AC10 — same-transaction agreement with the `task_events` park row — is NOT
  in this seat's scope. Moved to seat 2 on :8000 by the manager, 2026-07-19:
  SQLite cannot attest transactional agreement, so a unit "AC10" would be a
  control narrower than its claim wearing a green.)

⚠️ THE SUBSTRATE HAS NO CHECK TO VIOLATE — READ THIS BEFORE TRUSTING A GREEN
The `StalenessRow` model below carries the twins' three COLUMNS and none of the
table's CONSTRAINTS. Production `task_items` holds
`status != 'parked' OR park_reason_captured_at IS NOT NULL` (migration
`d47487369407`), so a parked row with a NULL capture is IMPOSSIBLE there — and
the matrix here contains four of them.

That is deliberate: the predicate must be TOTAL, because in-memory readers call
it without the CHECK travelling with them. But it means a green here says
NOTHING about which row shapes are reachable, and the difference is not academic.
On 2026-07-19 seat 2's write sequence passed 156 unit tests and 500'd on the
first real park: the unit tier had not failed to test the sequence, it had tested
it AGAINST A SUBSTRATE WITH NO CHECK TO VIOLATE. Green meant "no CHECK here" and
was read as "the sequence works." (Arnold's sharpening of the day's pattern —
in every instance, the instrument said yes about a path nothing had run.)

⇒ Rows in this file are shapes the PREDICATE must survive, NOT shapes the
  DATABASE can hold. Never cite a green here as evidence about the latter.

WHY ASSERTING ON UNREACHABLE SHAPES IS STILL CORRECT (seat 1's caveat, routed
here because their matrix is a scratchpad harness and this file is what later
readers actually meet): the predicate must be TOTAL over its INPUT DOMAIN, and
that domain is wider than the table. `park_reason_is_stale` is called on plain
dicts decoded from an HTTP body and on in-memory rows, not only on rows that
survived a CHECK — no constraint travels with those callers. So "parked + NULL
capture is handled" must never be read as "parked + NULL capture happens."

IS THE PROJECTION NULL REACHABLE IN PRODUCTION? NO — derived here rather than
assumed, because the answer changes what the projection arm is FOR:

  · `updated_ts` is `nullable=False` with a server_default (postgres_models.py).
  · `park_reason_captured_at` is nullable, BUT the CHECK
    `status != 'parked' OR park_reason_captured_at IS NOT NULL`
    (migration d47487369407) forbids NULL on exactly the rows whose comparison
    the clause evaluates.
  · SQL three-valued logic does the rest: `FALSE AND NULL` is FALSE, so a
    NON-parked row cannot project NULL even with the guards dropped. Only
    `TRUE AND NULL` — a PARKED row with a NULL operand — yields NULL.

  ⇒ The two conditions that jointly produce a NULL are unreachable on a real
    `task_items` row. The NULL the projection mutant produces below comes from a
    matrix row the CHECK forbids.

⇒ SO THE NULL GUARDS ARE, IN PRODUCTION, UNREACHABLE DEFENSIVE CODE, and the
  projection arm proves them TOTAL for the non-DB callers — NOT that it prevents
  a live `park_reason_stale: None` on the wire. Stated because the arm was added
  under the belief that a live None was possible; it is not, on any shape the
  table can hold. The arm still earns its place: a filter-shaped gate cannot see
  those guards AT ALL, and the day someone relaxes that CHECK they become
  load-bearing with nothing else watching them.

WHY SQLITE
----------
`park_reason_is_stale_clause` takes `model` as a parameter, so the SQL twin runs
against a minimal three-column model on in-memory SQLite: no Postgres, no
persistent state, well under 2 minutes ⇒ :7999-eligible per CLAUDE.md
§TESTING VENUES. Fidelity limit inherited from the parked-status parity gate:
SQLite has no timestamptz, so timestamps are naive-UTC on both sides. The LOGIC
(status guard, null arms, strict-vs-inclusive boundary) is exercised faithfully;
Postgres tz-aware comparison is NOT proven here.
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import Column, DateTime, Integer, String, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from cosa.rest.task_store_owed import (
    PARK_STATUS,
    is_owed,
    owed_status_row,
    park_is_active,
)
from cosa.rest.task_store_rules import VALID_STATUSES

# ---------------------------------------------------------------------------
# Seat-1 landing gate — LOUD, never a skip
# ---------------------------------------------------------------------------
#
# A skip reads as green on a summary line, and the whole point of this build is
# that a thing can stop being true without going red. So the absence of seat 1's
# predicate FAILS one named test rather than quietly skipping the file. When the
# predicate lands, this test goes green with no edit.
#
# Manager ruling 2026-07-19: FAIL, not xfail. One named red carrying the missing
# symbols is the gate WORKING, not noise.

try:
    from cosa.rest.task_store_owed import (
        park_reason_is_stale,
        park_reason_is_stale_clause,
    )
    _PREDICATE_LANDED = True
    _IMPORT_ERROR     = None
except ImportError as exc:
    park_reason_is_stale        = None
    park_reason_is_stale_clause = None
    _PREDICATE_LANDED           = False
    _IMPORT_ERROR               = str( exc )


def test_seat_one_predicate_has_landed():
    """
    The staleness twins exist and are importable.

    RED until seat 1 ships. Deliberately a FAILURE and not a skip: this suite
    exists because a green that cannot go red is not a green, and a skipped file
    is exactly that.
    """
    assert _PREDICATE_LANDED, (
        f"seat 1's staleness predicate is NOT in task_store_owed — every test "
        f"below is vacuous until it lands. Import error: {_IMPORT_ERROR}. "
        f"Expected per design §3.2: park_reason_is_stale( status, "
        f"park_reason_captured_at, updated_ts ) plus park_reason_is_stale_clause"
        f"( model ) as a GENUINELY independent twin. NOTE: the clause takes NO "
        f"`now` — staleness compares two ROW COLUMNS and reads no clock, unlike "
        f"park_is_active_clause( model, now )."
    )


pytestmark = pytest.mark.skipif(
    not _PREDICATE_LANDED,
    reason="seat 1 predicate absent — test_seat_one_predicate_has_landed carries the LOUD red",
)


Base = declarative_base()


class StalenessRow( Base ):
    """
    Minimal stand-in for TaskItem carrying only the three columns the twins read.

    Deliberately NOT the real TaskItem: that model needs JSONB + UUID + a
    Postgres server. The clause builder is model-parameterized, so a three-column
    model exercises the identical expression tree.
    """
    __tablename__           = "staleness_rows"
    id                      = Column( Integer, primary_key=True )
    status                  = Column( String )
    park_reason_captured_at = Column( DateTime )
    updated_ts              = Column( DateTime )


# ---------------------------------------------------------------------------
# The matrix — every status x every capture shape x every updated shape
# ---------------------------------------------------------------------------

CAP = datetime( 2026, 7, 19, 12, 0, 0 )

CAPTURE_SHAPES = {
    "null"   : None,    # pre-ship rows: no capture timestamp, must read not-stale
    "at_cap" : CAP,
}

UPDATED_SHAPES = {
    "null"   : None,                        # a row with no updated_ts at all
    "before" : CAP - timedelta( hours=6 ),  # clock skew / backdated write
    "equal"  : CAP,                         # THE BOUNDARY — freshly parked
    "after"  : CAP + timedelta( hours=6 ),  # amended after park -> STALE
}


def _build_matrix():
    """
    Every VALID_STATUSES value crossed with every capture and updated shape.

    Ensures:
        - returns a list of ( id, status, captured_or_None, updated_or_None )
        - covers all 8 statuses x 2 capture shapes x 4 updated shapes = 64 rows
        - contains the four AC6 boundary cases: equal timestamps, null capture,
          null updated_ts, and every status
    """
    rows    = []
    next_id = 1
    for status in VALID_STATUSES:
        for captured in CAPTURE_SHAPES.values():
            for updated in UPDATED_SHAPES.values():
                rows.append( ( next_id, status, captured, updated ) )
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
    for row_id, status, captured, updated in MATRIX:
        sess.add( StalenessRow(
            id                      = row_id,
            status                  = status,
            park_reason_captured_at = captured,
            updated_ts              = updated,
        ) )
    sess.commit()
    yield sess
    sess.close()


def _python_side( predicate=None ):
    """Ids the PYTHON twin calls stale. `predicate` is injectable for mutants."""
    predicate = predicate or park_reason_is_stale
    return {
        row_id for row_id, status, captured, updated in MATRIX
        if predicate( status, captured, updated )
    }


def _sql_side( session, clause_builder=None ):
    """
    Ids the SQL twin calls stale, in FILTER shape. Injectable for mutants.

    ⚠️ FILTER SHAPE IS BLIND TO THE NULL GUARDS — see `_sql_projection` below.
    """
    clause_builder = clause_builder or park_reason_is_stale_clause
    rows = session.query( StalenessRow ).filter( clause_builder( StalenessRow ) ).all()
    return { r.id for r in rows }


def _sql_projection( session, clause_builder=None ):
    """
    The clause's VALUE per row — `{ id: True | False | None }`. Injectable for mutants.

    ⚠️ WHY THIS EXISTS, AND WHY A FILTER-ONLY GATE FALSE-GREENS (seat 1, 15474267):
    in a WHERE clause `updated_ts > captured_at` with a NULL operand evaluates to
    NULL, and the engine DISCARDS the row — which is the same OBSERVABLE OUTCOME
    as an explicit `isnot(None)` guard excluding it. So the null guards are
    INVISIBLE to any filter-shaped test: drop them and the selected row set does
    not move. Seat 1's first gate ran 3/4 with the drop-null-guards mutant
    SURVIVING, and they ran it to ground as "my gate has the wrong shape" rather
    than "the mutant is inert" — which is the call that found it.

    In PROJECTION the difference is loud: the guarded clause returns FALSE, the
    unguarded one returns NULL. §3.3 surfaces `park_reason_stale` as a BOOL on
    every parked row, so projection — not membership — is the shape the feature
    actually ships in. A `None` there is exactly what §3.3 promises it is not.
    """
    clause_builder = clause_builder or park_reason_is_stale_clause
    rows = session.query(
        StalenessRow.id, clause_builder( StalenessRow ).label( "stale" )
    ).all()
    return { row.id: row.stale for row in rows }


# ===========================================================================
# AC6 — THE PARITY GATE: set equality across the boundary matrix
# ===========================================================================

def test_twins_agree_exactly_on_the_full_matrix( session ):
    """
    AC6: Python and SQL twins select IDENTICAL row sets.

    Set equality, both directions, over all 64 rows — not a spot check. The
    twins are independent by design (§3.2); this equality is what licenses that
    duplication, and the mutant sweep below is what proves the equality can fail.
    """
    py  = _python_side()
    sql = _sql_side( session )

    assert py == sql, (
        f"TWIN DIVERGENCE — python-only={sorted( py - sql )} "
        f"sql-only={sorted( sql - py )}"
    )


def test_the_matrix_covers_every_ac6_boundary_case():
    """
    The matrix actually contains the four shapes AC6 names.

    A parity gate over a matrix missing its boundaries is decorative — it would
    agree perfectly and prove nothing. This asserts the fixture's own coverage
    rather than trusting the loop that built it.
    """
    statuses = { status for _, status, _, _ in MATRIX }
    captures = { captured for _, _, captured, _ in MATRIX }
    updateds = { updated for _, _, _, updated in MATRIX }

    assert statuses == set( VALID_STATUSES ),  "matrix does not cover all 8 statuses"
    assert None in captures,                   "matrix lacks the null-capture case"
    assert None in updateds,                   "matrix lacks the null-updated_ts case"
    assert CAP in captures and CAP in updateds, "matrix lacks the equal-timestamps boundary"
    assert len( MATRIX ) == len( VALID_STATUSES ) * 2 * 4


def test_the_matrix_contains_rows_on_both_sides( session ):
    """
    POSITIVE CONTROL for the parity gate itself.

    A gate comparing two empty sets passes vacuously and forever. This requires
    the matrix to contain at least one stale row AND at least one non-stale row,
    so the equality above is a real comparison rather than {} == {}.

    The control does not perturb what it measures: it reads the same sets the
    gate reads and asserts only that they are non-degenerate.
    """
    stale = _sql_side( session )

    assert stale,                        "matrix produced NO stale rows — parity gate is vacuous"
    assert len( stale ) < len( MATRIX ), "matrix produced ALL-stale rows — parity gate is vacuous"


# ===========================================================================
# AC5 — non-parked rows never report stale
# ===========================================================================

def test_only_parked_rows_are_ever_stale():
    """
    AC5: whatever the timestamps say, a non-parked row is never stale.

    The status guard is checked FIRST in both twins for the same reason it is in
    `park_is_active`: a status-guard slip plus a wrong null arm would paint the
    entire board stale, inside the very fix meant to make staleness meaningful.
    """
    for row_id, status, captured, updated in MATRIX:
        if status != PARK_STATUS:
            assert not park_reason_is_stale( status, captured, updated ), (
                f"row {row_id} status={status!r} reported STALE — only parked "
                f"rows may ever be stale (AC5)"
            )


def test_non_parked_rows_are_never_stale_on_the_sql_side( session ):
    """AC5, SQL twin. Same claim, the other expression — not inferred from parity."""
    stale_rows = session.query( StalenessRow ).filter(
        park_reason_is_stale_clause( StalenessRow )
    ).all()

    for row in stale_rows:
        assert row.status == PARK_STATUS, (
            f"SQL twin called row {row.id} (status={row.status!r}) stale — AC5"
        )


def test_a_parked_row_amended_after_park_is_stale():
    """
    AC4 at the predicate level: captured < updated_ts ⇒ STALE.

    ⚠️ SCOPE: this proves the PREDICATE's arithmetic. The load-bearing form of
    AC4 — that a real amendment through the real write path bumps `updated_ts`
    past the capture — is a live-Postgres claim. A predicate cannot attest that
    the ORM's `onupdate` fires.
    """
    assert park_reason_is_stale( PARK_STATUS, CAP, CAP + timedelta( hours=6 ) )


def test_a_freshly_parked_row_reads_not_stale():
    """
    The equal-timestamps boundary: captured == updated_ts ⇒ NOT stale.

    ⚠️ THIS IS NOT AC3, AND MUST NOT BE READ AS AC3. AC3 requires asserting
    `park_reason_captured_at == updated_ts` as EQUALITY on a row the write path
    actually parked. What is asserted here is the strictly weaker consequence
    (`stale == False`), which the design (§3.4) records as one assertion short:
    it also passes for a `now()`-written-after implementation. Naming it
    correctly is the whole point — AC3 is a live claim, not this one.
    """
    assert not park_reason_is_stale( PARK_STATUS, CAP, CAP )


def test_a_parked_row_with_no_capture_reads_not_stale():
    """
    A parked row with NO capture time reads not-stale — we cannot know what its
    quote described, so claiming staleness would be a fabrication, not a
    detection.

    ⚠️ THIS ROW SHAPE CANNOT EXIST IN PRODUCTION, and the docstring that used to
    live here said it could. Corrected 2026-07-19 19:12; the correction is left
    visible for the same reason as the one in the live fixture.

    WAS: "Pre-ship rows (§7, no backfill) carry no capture timestamp." That cited
    §7's original "no backfill" clause — which has since been OVERTURNED as
    unsatisfiable: migration `d47487369407` adds the CHECK
    `status != 'parked' OR park_reason_captured_at IS NOT NULL`, so a parked row
    with a NULL capture violates it, and the migration BACKFILLS every pre-ship
    parked row with a labelled-fabricated capture time instead. There are no
    pre-ship rows of this shape. The justification was stale; the test is not.

    WHAT IT IS NOW: a FAIL-SAFE on an input the database forbids. Kept
    deliberately — the predicate is called by in-memory readers that do not carry
    the CHECK with them, and the safe direction on an impossible input is
    not-stale (a false STALE defames a correct quote and teaches readers to
    ignore the flag). It proves the predicate is total, NOT that the shape occurs.
    """
    assert not park_reason_is_stale( PARK_STATUS, None, CAP + timedelta( hours=6 ) )


def test_a_parked_row_with_no_updated_ts_reads_not_stale():
    """A null `updated_ts` cannot be greater than anything — not stale, never raises."""
    assert not park_reason_is_stale( PARK_STATUS, CAP, None )


# ===========================================================================
# AC7 — staleness is ADVISORY. Regression guard on a877e7b3.
# ===========================================================================

def test_owed_predicates_do_not_read_the_staleness_columns():
    """
    AC7, at the MECHANISM rather than at a consequence.

    `park_is_active` / `is_owed` / `owed_status_row` cannot be influenced by
    staleness because they do not ACCEPT it: their signatures take
    ( status, next_chase_ts, now ) and nothing else. Wire a capture timestamp
    into any of them and this goes red immediately — whereas a value-level test
    would only go red once someone also changed the value.

    This is the a877e7b3 freeze, asserted structurally.
    """
    import inspect

    for fn in ( park_is_active, is_owed, owed_status_row ):
        params = list( inspect.signature( fn ).parameters )
        assert params == [ "status", "next_chase_ts", "now" ], (
            f"{fn.__name__} signature moved to {params} — staleness must NOT "
            f"reach the owed path (AC7, freezing a877e7b3)"
        )


def test_stale_and_fresh_rows_have_byte_identical_owed_results():
    """
    AC7 at the value level, complementing the structural guard above.

    Two rows identical in status and chase but differing in staleness must
    produce identical answers from every owed-path predicate. Byte-identical, as
    the AC words it — `is` on the returned bools, not merely `==`.
    """
    now      = CAP
    chase    = CAP + timedelta( hours=1 )
    stale_in = ( PARK_STATUS, CAP, CAP + timedelta( hours=6 ) )   # stale
    fresh_in = ( PARK_STATUS, CAP, CAP )                          # fresh

    assert park_reason_is_stale( *stale_in ) is True,  "fixture's stale row is not stale"
    assert park_reason_is_stale( *fresh_in ) is False, "fixture's fresh row is not fresh"

    # The owed path sees the SAME inputs in both cases — that is the point. If
    # staleness ever reaches it, these constants stop being sufficient and the
    # structural guard above fires first.
    assert park_is_active(   PARK_STATUS, chase, now ) is True
    assert is_owed(          PARK_STATUS, chase, now ) is False
    assert owed_status_row(  PARK_STATUS, chase, now ) is False


# ===========================================================================
# AC9 — MUTANTS. Every guard verified RED.
# ===========================================================================
#
# Each mutant perturbs exactly ONE expression on ONE side. The parity gate MUST
# reject it. A mutant that survives means the guard it targets is decorative.
# The four the design names at minimum: `>` -> `>=`, `>` -> `<`, drop the status
# guard, invert the null arm. All four are here on BOTH sides.

def _mutant_boundary_inclusive( status, captured, updated ):
    """MUTANT: `>=` instead of `>` — a freshly parked row is born STALE (§3.4's trap)."""
    if status != PARK_STATUS: return False
    if captured is None or updated is None: return False
    return updated >= captured


def _mutant_boundary_reversed( status, captured, updated ):
    """MUTANT: `<` instead of `>` — amendments read fresh, backdated writes read stale."""
    if status != PARK_STATUS: return False
    if captured is None or updated is None: return False
    return updated < captured


def _mutant_no_status_guard( status, captured, updated ):
    """MUTANT: status guard dropped — any amended row looks stale, parked or not."""
    if captured is None or updated is None: return False
    return updated > captured


def _mutant_null_arm_inverted( status, captured, updated ):
    """MUTANT: a null capture reported STALE — every pre-ship row goes red at once."""
    if status != PARK_STATUS: return False
    if captured is None: return True
    if updated is None: return False
    return updated > captured


MUTANTS_PY = [
    ( "boundary >= instead of >",  _mutant_boundary_inclusive ),
    ( "boundary < instead of >",   _mutant_boundary_reversed ),
    ( "status guard dropped",      _mutant_no_status_guard ),
    ( "null capture arm inverted", _mutant_null_arm_inverted ),
]


def _mutant_clause_boundary_inclusive( model ):
    """MUTANT (SQL): `>=` instead of `>`."""
    from sqlalchemy import and_
    return and_(
        model.status == PARK_STATUS,
        model.park_reason_captured_at.isnot( None ),
        model.updated_ts.isnot( None ),
        model.updated_ts >= model.park_reason_captured_at,
    )


def _mutant_clause_boundary_reversed( model ):
    """MUTANT (SQL): `<` instead of `>`."""
    from sqlalchemy import and_
    return and_(
        model.status == PARK_STATUS,
        model.park_reason_captured_at.isnot( None ),
        model.updated_ts.isnot( None ),
        model.updated_ts < model.park_reason_captured_at,
    )


def _mutant_clause_no_status_guard( model ):
    """MUTANT (SQL): status conjunct dropped."""
    from sqlalchemy import and_
    return and_(
        model.park_reason_captured_at.isnot( None ),
        model.updated_ts.isnot( None ),
        model.updated_ts > model.park_reason_captured_at,
    )


def _mutant_clause_null_arm_inverted( model ):
    """MUTANT (SQL): a null capture selected as stale."""
    from sqlalchemy import and_, or_
    return and_(
        model.status == PARK_STATUS,
        or_(
            model.park_reason_captured_at.is_( None ),
            model.updated_ts > model.park_reason_captured_at,
        ),
    )


def _mutant_clause_drop_null_guards( model ):
    """
    MUTANT (SQL): both `isnot( None )` guards DROPPED.

    ⚠️ THE ONE A FILTER CANNOT SEE. `updated_ts > captured_at` with a NULL operand
    is NULL; a WHERE clause discards the row, which is indistinguishable from the
    guard excluding it. Identical row set, different VALUE — NULL where the twin
    says False. Killable only in projection.
    """
    from sqlalchemy import and_
    return and_(
        model.status == PARK_STATUS,
        model.updated_ts > model.park_reason_captured_at,
    )


MUTANTS_SQL = [
    ( "SQL boundary >= instead of >",  _mutant_clause_boundary_inclusive ),
    ( "SQL boundary < instead of >",   _mutant_clause_boundary_reversed ),
    ( "SQL status guard dropped",      _mutant_clause_no_status_guard ),
    ( "SQL null capture arm inverted", _mutant_clause_null_arm_inverted ),
]

# ── STRUCTURAL COMPLETION (seat 1's generator, folded 2026-07-19 post-run) ──
#
# ⚠️ THE LIST ABOVE WAS DERIVED FROM AC9's NAMED MINIMUM, AND THAT IS THE BUG.
# AC9 wrote "at minimum" and it was read as a ceiling, so the sweep covered the
# four mutations the AC happened to name and was SILENT about every guard it did
# not. A missing mutant is invisible by construction: no rerun, and no amount of
# rigor against the list you have, can report on a mutant that does not exist.
#
# ⇒ THE RULE, which replaces judgement with derivation: take the clause's
#   STRUCTURE — it is a conjunction of 4 terms — and emit DROP each + NEGATE each,
#   plus the operator variants on the one comparison. 4x2 + 3 = 11. A list built
#   this way cannot be short by forgetting.
#
# ⇒ AND THE HALF THAT OUTRANKS THE COUNT: cross-referencing each mutant against
#   REACHABILITY turns the sweep from pass/fail into a statement about what each
#   guard IS —
#       dies in every shape                      -> LIVE GUARD
#       dies only in some shapes, REACHABLE rows -> SHAPE-SENSITIVE (a filter-only
#                                                   gate false-greens on it)
#       dies only on UNREACHABLE rows            -> FAIL-SAFE (keep it, but do not
#                                                   call it a live defense)
#       survives everywhere on reachable data    -> DEAD CODE or a blind gate
#
# Generator verdict on this clause (48 rows, 31 reachable):
#   LIVE 9 · SHAPE-SENSITIVE 0 · FAIL-SAFE 2 · SURVIVES-EVERYWHERE 0
# The two FAIL-SAFEs are the null-guard DROPs, identified mechanically rather than
# by a human deciding. SURVIVES-EVERYWHERE=0 also answers "is any of this dead
# code" — a question nobody had thought to ask.
#
# Tool: src/tmp/mutant-adequacy-generator-for-seat3-2026.07.19.py (seat 1, 15474267).
# ⚠️ That path is GITIGNORED and will die. If the generator is kept it belongs
# committed beside the suites it audits, with the classification table as its
# output contract.
#
# NOTE the DROP/NEGATE asymmetry, which is why "invert the null arm" was never a
# substitute for "drop" it: for the SAME guard, NEGATE lands LIVE (inverting ADDS
# rows, so a filter sees it) while DROP lands FAIL-SAFE (deletion is invisible to
# a filter). Opposite verdicts, same guard, purely from mutation direction.

def _mutant_clause_negate_status_guard( model ):
    """MUTANT: status guard NEGATED — every non-parked row becomes eligible."""
    from sqlalchemy import and_
    return and_(
        model.status != PARK_STATUS,
        model.park_reason_captured_at.isnot( None ),
        model.updated_ts.isnot( None ),
        model.updated_ts > model.park_reason_captured_at,
    )


def _mutant_clause_drop_ordering( model ):
    """MUTANT: the comparison DROPPED — every parked row with both timestamps is stale."""
    from sqlalchemy import and_
    return and_(
        model.status == PARK_STATUS,
        model.park_reason_captured_at.isnot( None ),
        model.updated_ts.isnot( None ),
    )


def _mutant_clause_negate_ordering( model ):
    """MUTANT: comparison NEGATED — `updated <= captured`, the complement of stale."""
    from sqlalchemy import and_
    return and_(
        model.status == PARK_STATUS,
        model.park_reason_captured_at.isnot( None ),
        model.updated_ts.isnot( None ),
        model.updated_ts <= model.park_reason_captured_at,
    )


def _mutant_clause_negate_updated_notnull( model ):
    """
    MUTANT: the UPDATED null guard NEGATED — `updated_ts IS NULL`, which then
    cannot satisfy the comparison. Selects nothing.

    Caught by `test_the_mutant_list_is_STRUCTURALLY_complete` on its FIRST run:
    I completed the list from the generator's table and still omitted this one.
    The guard bit immediately, on its author, which is the only reason it is here.
    """
    from sqlalchemy import and_
    return and_(
        model.status == PARK_STATUS,
        model.park_reason_captured_at.isnot( None ),
        model.updated_ts.is_( None ),
        model.updated_ts > model.park_reason_captured_at,
    )


def _mutant_clause_boundary_not_equal( model ):
    """MUTANT: `!=` instead of `>` — a BACKDATED write reads stale too."""
    from sqlalchemy import and_
    return and_(
        model.status == PARK_STATUS,
        model.park_reason_captured_at.isnot( None ),
        model.updated_ts.isnot( None ),
        model.updated_ts != model.park_reason_captured_at,
    )


# The structural mutants the AC-derived list above was missing. All LIVE — each
# moves the row set, so the filter gate sees every one.
MUTANTS_SQL_STRUCTURAL = [
    ( "SQL status guard NEGATED",       _mutant_clause_negate_status_guard ),
    ( "SQL updated null guard NEGATED", _mutant_clause_negate_updated_notnull ),
    ( "SQL ordering DROPPED",           _mutant_clause_drop_ordering ),
    ( "SQL ordering NEGATED",           _mutant_clause_negate_ordering ),
    ( "SQL boundary != instead of >",   _mutant_clause_boundary_not_equal ),
]


def _mutant_clause_drop_capture_notnull( model ):
    """MUTANT: only the CAPTURE null guard dropped. FAIL-SAFE — projection-only."""
    from sqlalchemy import and_
    return and_(
        model.status == PARK_STATUS,
        model.updated_ts.isnot( None ),
        model.updated_ts > model.park_reason_captured_at,
    )


def _mutant_clause_drop_updated_notnull( model ):
    """MUTANT: only the UPDATED null guard dropped. FAIL-SAFE — projection-only."""
    from sqlalchemy import and_
    return and_(
        model.status == PARK_STATUS,
        model.park_reason_captured_at.isnot( None ),
        model.updated_ts > model.park_reason_captured_at,
    )


# Swept ONLY in projection — see `_sql_projection`. Listed separately rather than
# folded in, because adding these to MUTANTS_SQL would make the filter sweep report
# SURVIVORS and invite someone to "fix" it by deleting the mutants.
#
# These are the FAIL-SAFE two: they die only on rows the CHECK forbids. Kept, and
# labelled so nobody reports them as live defenses.
MUTANTS_SQL_PROJECTION_ONLY = [
    ( "SQL null guards dropped",         _mutant_clause_drop_null_guards ),
    ( "SQL capture null guard dropped",  _mutant_clause_drop_capture_notnull ),
    ( "SQL updated null guard dropped",  _mutant_clause_drop_updated_notnull ),
]


@pytest.mark.parametrize( "name,mutant", MUTANTS_PY, ids=[ m[ 0 ] for m in MUTANTS_PY ] )
def test_python_mutant_breaks_parity( session, name, mutant ):
    """AC9: each Python-side mutant MUST diverge from the real SQL twin."""
    assert _python_side( mutant ) != _sql_side( session ), (
        f"MUTANT SURVIVED: {name!r} — the parity gate cannot detect it, so the "
        f"guard it targets is decorative"
    )


@pytest.mark.parametrize(
    "name,mutant",
    MUTANTS_SQL + MUTANTS_SQL_STRUCTURAL,
    ids=[ m[ 0 ] for m in MUTANTS_SQL + MUTANTS_SQL_STRUCTURAL ],
)
def test_sql_mutant_breaks_parity( session, name, mutant ):
    """AC9: each SQL-side mutant MUST diverge from the real Python twin."""
    assert _python_side() != _sql_side( session, mutant ), (
        f"MUTANT SURVIVED: {name!r} — the parity gate cannot detect it, so the "
        f"guard it targets is decorative"
    )


def test_the_mutant_list_is_STRUCTURALLY_complete():
    """
    THE GUARD AGAINST THE LIST GOING SHORT AGAIN — which is the defect that
    actually happened here, and the one no amount of re-running could surface.

    The SQL clause is a conjunction of 4 terms. A structurally-derived list emits
    DROP each + NEGATE each (8), plus the operator variants on the single
    comparison (3) = 11. This asserts the count we actually carry against that
    derivation, so ADDING A CONJUNCT to the clause without adding its two mutants
    fails HERE rather than passing silently forever.

    ⚠️ A count is a weak check and it is deliberately paired with the naming
    assertion below: 11 arbitrary mutants would satisfy an arithmetic test. What
    makes it bite is that every conjunct must appear by NAME in both directions.
    """
    sql_mutants = MUTANTS_SQL + MUTANTS_SQL_STRUCTURAL + MUTANTS_SQL_PROJECTION_ONLY
    names       = { name for name, _ in sql_mutants }

    conjuncts = [ "status", "capture", "updated", "ordering" ]
    op_variants = [ ">=", "<", "!=" ]

    # Every conjunct mutated in BOTH directions. `_mutant_clause_drop_null_guards`
    # drops capture+updated together, so the two individual drops carry those.
    for term in conjuncts:
        assert any( term in n.lower() and ( "drop" in n.lower() ) for n in names ), (
            f"no DROP mutant for the {term!r} conjunct — a dropped guard is the "
            f"INVISIBLE direction and the one that survived last time"
        )
        assert any( term in n.lower() and ( "negat" in n.lower() or "invert" in n.lower() ) for n in names ), (
            f"no NEGATE mutant for the {term!r} conjunct"
        )

    for op in op_variants:
        assert any( op in n for n in names ), f"no operator-variant mutant for {op!r}"

    assert len( sql_mutants ) >= 11, (
        f"SQL mutant list carries {len( sql_mutants )}, structural derivation "
        f"requires >= 11 (4 conjuncts x DROP+NEGATE, plus 3 operator variants). "
        f"A list derived from the AC table instead of the CODE goes short and is "
        f"silent about it."
    )


def test_twins_agree_in_PROJECTION_and_the_sql_side_is_never_null( session ):
    """
    AC6 in the shape the feature SHIPS in: value-per-row, not membership.

    §3.3 surfaces `park_reason_stale` as a BOOL on every parked row. So the SQL
    twin must return an actual False — never NULL — for every row the Python twin
    calls not-stale. Three-valued logic leaking to the wire is precisely what
    §3.3 promises does not happen.
    """
    py         = _python_side()
    projection = _sql_projection( session )

    assert len( projection ) == len( MATRIX ), "projection dropped rows — it must value EVERY row"

    for row_id, value in projection.items():
        assert value is not None, (
            f"row {row_id} projects NULL — the null guards are not doing their job "
            f"and `park_reason_stale` would reach the wire as None, not a bool (§3.3)"
        )
        assert bool( value ) == ( row_id in py ), (
            f"row {row_id}: projection={value!r} disagrees with the Python twin"
        )


@pytest.mark.parametrize(
    "name,mutant", MUTANTS_SQL_PROJECTION_ONLY, ids=[ m[ 0 ] for m in MUTANTS_SQL_PROJECTION_ONLY ]
)
def test_projection_only_mutant_is_invisible_to_filter_and_dies_in_projection( session, name, mutant ):
    """
    AC9's blind spot, closed — and the control that PROVES it was a blind spot.

    Asserts BOTH halves, because either alone is misleading:
      1. the mutant SURVIVES the filter gate (identical row set) — which is why a
         filter-only sweep reports a clean green over a real defect;
      2. the mutant DIES in projection (NULL where the twin says False).

    Half 1 is not a formality. If it ever starts failing, the filter shape has
    become able to see this class and the projection arm may be redundant — but
    until then, half 1 is the evidence that the arm earns its place.
    """
    assert _sql_side( session, mutant ) == _sql_side( session ), (
        f"{name!r} is visible to the FILTER gate — the premise of this test is "
        f"wrong and the projection arm may not be needed for it"
    )

    mutated  = _sql_projection( session, mutant )
    baseline = _sql_projection( session )

    assert mutated != baseline, (
        f"MUTANT SURVIVED BOTH SHAPES: {name!r} — the null guards are decorative"
    )
    assert any( v is None for v in mutated.values() ), (
        f"{name!r} did not produce a NULL — the three-valued-logic mechanism this "
        f"test exists to catch is not being exercised"
    )


def test_the_mutant_sweep_itself_is_connected( session ):
    """
    POSITIVE CONTROL on the sweep — the control that MUST be able to fail.

    A mutant sweep coming back all-clean is likelier to be a disconnected
    harness than a perfect implementation. So: the real twins must AGREE (the
    harness is not simply rejecting everything) while at least one mutant must
    DIVERGE (the harness can actually see a difference). Without the first half,
    a comparison that returned unequal for every input would make every mutant
    test above pass vacuously.

    The control does not perturb what it measures — it evaluates the same two
    sides on the same fixture and writes nothing.
    """
    assert _python_side() == _sql_side( session ), (
        "harness rejects the REAL pair — every mutant test above is passing "
        "vacuously and the sweep proves nothing"
    )
    assert _python_side( _mutant_no_status_guard ) != _sql_side( session ), (
        "harness accepts a known mutant — sweep is disconnected"
    )


def test_every_mutant_is_distinguishable_on_this_fixture( session ):
    """
    Each mutant must move at least one row ON THIS MATRIX.

    A mutant that is merely equivalent to the original on the chosen fixture
    tests the fixture's poverty, not the guard. This names which mutant is inert
    rather than letting the sweep report a green it did not earn.
    """
    baseline = _python_side()

    for name, mutant in MUTANTS_PY:
        assert _python_side( mutant ) != baseline, (
            f"INERT MUTANT: {name!r} selects the same rows as the real predicate "
            f"on this matrix — the matrix cannot distinguish it"
        )

    for name, mutant in MUTANTS_SQL:
        assert _sql_side( session, mutant ) != baseline, (
            f"INERT MUTANT: {name!r} selects the same rows as the real predicate "
            f"on this matrix — the matrix cannot distinguish it"
        )


# ===========================================================================
# AC8 — the coercion arms the 64-row matrix cannot reach
# ===========================================================================
#
# The matrix is built from naive datetimes and None, so three arms of the Python
# twin's coercion never execute under it: the ISO-STRING branch, the UNPARSEABLE
# branch, and the ALREADY-AWARE branch. Coverage found them; they are reached
# here directly rather than by widening the matrix, because widening it would
# also change what the parity gate and the mutant sweep are comparing — a fixture
# edit that moves a gate is not a coverage fix, it is a new gate.

def test_iso_string_timestamps_are_accepted_on_both_sides():
    """Both parameters accept ISO-8601 strings, matching `park_is_active`'s contract."""
    assert park_reason_is_stale( PARK_STATUS, "2026-07-19T12:00:00", "2026-07-19T18:00:00" ) is True
    assert park_reason_is_stale( PARK_STATUS, "2026-07-19T12:00:00", "2026-07-19T12:00:00" ) is False


def test_a_trailing_z_is_accepted_as_utc():
    """`Z` is not ISO-parseable on its own in Python; the twin rewrites it to +00:00."""
    assert park_reason_is_stale( PARK_STATUS, "2026-07-19T12:00:00Z", "2026-07-19T18:00:00Z" ) is True


def test_an_unparseable_capture_reads_not_stale():
    """
    Garbage in the capture column reads NOT-stale — the direction this instrument
    lies, and the safe one: a false STALE defames a correct quote and teaches
    readers to ignore the flag, which disarms the feature permanently.
    """
    assert park_reason_is_stale( PARK_STATUS, "not-a-timestamp", "2026-07-19T18:00:00" ) is False


def test_an_unparseable_updated_ts_reads_not_stale():
    """Same rule, the other column — asserted separately so one arm cannot cover for the other."""
    assert park_reason_is_stale( PARK_STATUS, "2026-07-19T12:00:00", "not-a-timestamp" ) is False


def test_a_non_timestamp_type_reads_not_stale():
    """An int/list/object in either column returns False rather than raising (§ never raises)."""
    assert park_reason_is_stale( PARK_STATUS, 12345, CAP ) is False
    assert park_reason_is_stale( PARK_STATUS, CAP, 12345 ) is False


def test_tz_aware_timestamps_compare_without_being_re_stamped():
    """
    Already-aware datetimes take the OTHER arm of the tz normalization — the one
    the all-naive matrix never exercises.

    Mixed naive/aware is the case that would raise, so the twin normalizes both
    to UTC first; this pins that an aware pair still compares correctly and that
    an aware/naive pair does not blow up.
    """
    from datetime import timezone as _tz

    aware_cap   = CAP.replace( tzinfo=_tz.utc )
    aware_later = ( CAP + timedelta( hours=6 ) ).replace( tzinfo=_tz.utc )

    assert park_reason_is_stale( PARK_STATUS, aware_cap, aware_later ) is True
    assert park_reason_is_stale( PARK_STATUS, aware_cap, aware_cap )   is False
    assert park_reason_is_stale( PARK_STATUS, aware_cap, CAP )         is False   # aware + naive
    assert park_reason_is_stale( PARK_STATUS, CAP, aware_later )       is True    # naive + aware


# ===========================================================================
# Independence — the duplication licence
# ===========================================================================

def test_the_twins_are_genuinely_independent():
    """
    §3.2: neither twin may call the other, and they share no helper.

    If the SQL twin delegates to the Python one (or both route through a common
    helper), the mutant sweep cannot move the two sides apart and every gate
    above degrades to proving that a helper equals itself.
    """
    import inspect

    py_src  = inspect.getsource( park_reason_is_stale )
    sql_src = inspect.getsource( park_reason_is_stale_clause )

    assert "park_reason_is_stale_clause" not in py_src, (
        "the Python twin calls the SQL twin — the parity gate is now circular"
    )
    assert "park_reason_is_stale(" not in sql_src, (
        "the SQL twin calls the Python twin — the parity gate is now circular"
    )
