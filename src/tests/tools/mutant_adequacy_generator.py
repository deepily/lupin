"""
HOW BIG SHOULD A MUTANT LIST BE? — derive it from the CODE'S STRUCTURE, not from imagination.

Author: seat 1 (session 15474267), park_reason-staleness build, 2026-07-19.
Committed here by seat 1's request routed through Mr. Radio; it originally lived
at a gitignored `src/tmp/` path and would have died with the tree.

THE PROBLEM THIS ANSWERS. Seat 3's sweep was 8/8 green over a guard that had NO
mutant testing it. The list was assembled by asking "what could go wrong?", which
is bounded by what the author thought of. The hole was found by accident.

THE RULE. `park_reason_is_stale_clause` is a conjunction of N terms. For a
conjunction, the structurally-complete mutant set is, per term:
    DROP it        (does anything notice this term is gone?)
    NEGATE it      (does anything notice it inverted?)
plus, per comparison operator, its boundary and direction variants.
That count is a PROPERTY OF THE CODE. It is not a judgement call, and it cannot
be short by forgetting.

⚠️ THE DROP/NEGATE ASYMMETRY IS THE WHOLE POINT, not bookkeeping. For the SAME
guard the two directions land on OPPOSITE verdicts: NEGATE lands LIVE, because
inverting ADDS rows a filter can see; DROP lands FAIL-SAFE, because deleting a
null-guard changes no row set under a filter (a NULL comparison is discarded
exactly as the guard would have excluded it). A sweep carrying only NEGATE
reports a clean green over an untested guard. That is precisely what happened.

THE SECOND HALF, which is the real finding. A mutant that survives is not
automatically a missing test. Run every mutant through EVERY SHAPE the predicate
is used in (filter AND projection), and the survival pattern CLASSIFIES the term:

    dies in every shape        -> LIVE GUARD. Load-bearing, properly tested.
    dies ONLY in some shapes   -> SHAPE-SENSITIVE. A gate testing only the other
                                  shape false-greens. (This is the hole.)
    survives every shape, but
      the shape is unreachable
      in production            -> FAIL-SAFE. Correct to keep, wrong to call a
                                  defense. Document as total-ness.
    survives every shape on
      reachable data           -> DEAD CODE, or the gate is blind. Investigate.

That classification is what "how many mutants" should actually produce — not a
number, but a verdict per term.

═══ OUTPUT CONTRACT ═══
A table, one row per structural mutant, with columns:
    mutant | filter | projctn | reachable? | verdict
followed by the tally line:
    LIVE=<n>  SHAPE-SENSITIVE=<n>  FAIL-SAFE=<n>  SURVIVES-EVERYWHERE=<n>

Known-good result for the current clause (4 conjuncts ⇒ 11 mutants, 48 rows,
31 reachable): LIVE=9  SHAPE-SENSITIVE=0  FAIL-SAFE=2  SURVIVES-EVERYWHERE=0.
The two FAIL-SAFEs are the null-guard DROPs. SURVIVES-EVERYWHERE=0 also answers
"is any of this dead code", which is not otherwise asked anywhere.

═══ HOW TO RUN ═══
    LUPIN_ROOT=$PWD python3 src/tests/tools/mutant_adequacy_generator.py

⚠️ NOT A PYTEST FILE and deliberately not named like one — it is an AUDIT TOOL
whose output a human reads. It is not collected (no `test_` prefix) and asserts
nothing; the assertions it informs live in
`src/tests/unit/test_park_reason_staleness.py`, whose
`test_the_mutant_list_is_STRUCTURALLY_complete` is the committed guard that the
hand-maintained list has not gone short.

⚠️ VENUE: connects to the TEST database and creates a TEMPORARY table, which is
session-scoped and vanishes on disconnect — it writes no persistent state and
touches no existing row. Do NOT run it during a live `:8000` job anyway; a
monopolize-mode run owns that server.
"""
import os
import sys

from datetime import datetime, timedelta, timezone

from sqlalchemy import (
    Column, DateTime, MetaData, String, Table, and_, create_engine, not_, select,
)

# Bootstrap: this runs before `cosa` is importable, so resolve from LUPIN_ROOT
# per the PATH MANAGEMENT mandate. The original carried an absolute path
# hardcoded to one developer's checkout, which is why this block exists.
_lupin_root = os.environ.get( "LUPIN_ROOT" )
if _lupin_root is None:
    raise RuntimeError( "LUPIN_ROOT not set — export LUPIN_ROOT=/path/to/project" )
_src_path = os.path.join( _lupin_root, "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.rest.db.database import get_database_url
from cosa.rest.task_store_owed import PARK_STATUS

T0    = datetime( 2026, 7, 19, 12, 0, 0, tzinfo=timezone.utc )
LATER = T0 + timedelta( minutes=5 )

# The full input domain: every status x every timestamp shape.
ALL_STATUSES = ( "queued", "in_progress", "blocked", "claimed", "review", "parked", "done", "dropped" )
TS_SHAPES = (
    ( T0,    LATER ),   # amended after capture
    ( T0,    T0    ),   # the equality boundary
    ( LATER, T0    ),   # reverse order
    ( None,  LATER ),   # null capture   <- UNREACHABLE for parked rows (CHECK)
    ( T0,    None  ),   # null updated   <- UNREACHABLE always (NOT NULL)
    ( None,  None  ),   # both null      <- UNREACHABLE
)


def resolve_test_database_url():
    """
    The TEST database URL, from the app's own resolver rather than a literal.

    Requires:
        - the process can import cosa.rest.db.database

    Ensures:
        - returns the URL `get_database_url()` yields with LUPIN_ENV=testing
        - restores any pre-existing LUPIN_ENV before returning

    ⚠️ The original hardcoded a full `postgresql+psycopg2://user:password@host/db`
    literal. That is a second record of a fact the app already owns — the same
    two-records-of-one-fact class this whole build exists to fix — and it bakes a
    credential into a committed file. Resolved through the app instead.
    """
    previous = os.environ.get( "LUPIN_ENV" )
    os.environ[ "LUPIN_ENV" ] = "testing"
    try:
        return get_database_url()
    finally:
        if previous is None: os.environ.pop( "LUPIN_ENV", None )
        else:                os.environ[ "LUPIN_ENV" ] = previous


def is_reachable( status, captured, updated ):
    """
    Can this row shape actually occur in production, given the schema?

    Ensures:
        - False when updated_ts is NULL      (column is NOT NULL)
        - False when a PARKED row has a NULL captured_at
          (ck_task_items_parked_requires_captured_at, migration d47487369407)
        - True otherwise
    """
    if updated is None:                              return False   # NOT NULL
    if status == PARK_STATUS and captured is None:   return False   # the CHECK
    return True


# ---- the four conjuncts of the real clause, named ----
TERMS = [
    ( "status-guard",    lambda t: t.c.status == PARK_STATUS ),
    ( "capture-notnull", lambda t: t.c.captured.isnot( None ) ),
    ( "updated-notnull", lambda t: t.c.updated.isnot( None ) ),
    ( "ordering",        lambda t: t.c.updated > t.c.captured ),
]


def clause_from( terms, t ):
    return and_( *[ fn( t ) for _name, fn in terms ] )


def real_clause( t ):
    return clause_from( TERMS, t )


def structural_mutants():
    """
    Generate the mutant list FROM THE STRUCTURE: drop-each-term + negate-each-term,
    plus the operator variants on the one comparison. Count is a property of the code.

    Ensures:
        - returns 2*len(TERMS) + 3 (label, clause_builder) pairs
        - every term appears in BOTH directions — the asymmetry above is why
    """
    mutants = []
    for index, ( name, _fn ) in enumerate( TERMS ):
        dropped = [ term for position, term in enumerate( TERMS ) if position != index ]
        mutants.append( ( f"DROP {name}", lambda t, d=dropped: clause_from( d, t ) ) )

        negated = list( TERMS )
        negated[ index ] = ( name, lambda t, f=_fn: not_( f( t ) ) )
        mutants.append( ( f"NEGATE {name}", lambda t, n=negated: clause_from( n, t ) ) )

    head = TERMS[ :3 ]
    mutants.append( ( "OP  > -> >=", lambda t: and_( *[ f( t ) for _n, f in head ], t.c.updated >= t.c.captured ) ) )
    mutants.append( ( "OP  > -> <",  lambda t: and_( *[ f( t ) for _n, f in head ], t.c.updated <  t.c.captured ) ) )
    mutants.append( ( "OP  > -> !=", lambda t: and_( *[ f( t ) for _n, f in head ], t.c.updated != t.c.captured ) ) )
    return mutants


def main():
    rows, index = [], 0
    for status in ALL_STATUSES:
        for captured, updated in TS_SHAPES:
            rows.append( ( f"r{index:03d}", status, captured, updated, is_reachable( status, captured, updated ) ) )
            index += 1

    engine, metadata = create_engine( resolve_test_database_url() ), MetaData()
    matrix = Table(
        "_adequacy_matrix", metadata,
        Column( "row_id", String( 16 ), primary_key=True ),
        Column( "status", String( 32 ) ),
        Column( "captured", DateTime( timezone=True ) ),
        Column( "updated",  DateTime( timezone=True ) ),
        prefixes=[ "TEMPORARY" ],
    )

    with engine.begin() as conn:
        metadata.create_all( conn )
        conn.execute( matrix.insert(), [
            { "row_id": r, "status": s, "captured": c, "updated": u } for r, s, c, u, _ok in rows
        ] )

        reachable_ids = { r for r, _s, _c, _u, ok in rows if ok }

        def filter_set( cl ):
            return { row[ 0 ] for row in conn.execute( select( matrix.c.row_id ).where( cl( matrix ) ) ) }

        def projection_map( cl ):
            return dict( conn.execute( select( matrix.c.row_id, cl( matrix ) ) ).all() )

        base_filter, base_proj = filter_set( real_clause ), projection_map( real_clause )

        mutants = structural_mutants()
        print( "=" * 96 )
        print( "MUTANT-LIST ADEQUACY — list derived from STRUCTURE, verdict derived from SHAPE + REACHABILITY" )
        print( "=" * 96 )
        print( f"conjuncts={len( TERMS )}  ->  structural mutants={len( mutants )}  (drop+negate per term, plus 3 operator variants)" )
        print( f"matrix rows={len( rows )}  of which REACHABLE in production={len( reachable_ids )}\n" )
        print( f"{'mutant':22s} {'filter':>8s} {'projctn':>8s} {'reachable?':>11s}   verdict" )
        print( "-" * 96 )

        tally = {}
        for label, mutant in mutants:
            dies_filter = filter_set( mutant ) != base_filter

            mutant_proj          = projection_map( mutant )
            differing            = { r for r in base_proj if mutant_proj[ r ] != base_proj[ r ] }
            dies_proj            = bool( differing )
            differs_on_reachable = bool( differing & reachable_ids )

            if dies_filter and dies_proj:      verdict, key = "LIVE GUARD — tested in both shapes", "live"
            elif dies_proj and not dies_filter:
                verdict, key = ( "SHAPE-SENSITIVE — a filter-only gate FALSE-GREENS", "shape" ) if differs_on_reachable \
                               else ( "FAIL-SAFE — dies only on UNREACHABLE rows", "failsafe" )
            elif dies_filter and not dies_proj: verdict, key = "filter-only difference", "live"
            else:                               verdict, key = "SURVIVES EVERYWHERE — dead code or blind gate", "dead"

            tally[ key ] = tally.get( key, 0 ) + 1
            print( f"{label:22s} {str( dies_filter ):>8s} {str( dies_proj ):>8s} {str( differs_on_reachable ):>11s}   {verdict}" )

        print( "-" * 96 )
        print( f"LIVE={tally.get('live',0)}  SHAPE-SENSITIVE={tally.get('shape',0)}  "
               f"FAIL-SAFE={tally.get('failsafe',0)}  SURVIVES-EVERYWHERE={tally.get('dead',0)}" )
    return 0


if __name__ == "__main__":
    sys.exit( main() )
