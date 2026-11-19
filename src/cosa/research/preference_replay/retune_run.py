"""
Run the retune over the real cohort and write its report, reading the database only.

The command reads the yes/no and multiple-choice cohorts in a read-only transaction. It replays the
live engine over them with the retune grid and with the report-only sweep, then writes one JSON report.
The report holds the frozen settings, the cohort checksums and every grid point. It also holds the
exact command and code that made it, so the frozen baseline can be made again from the tree.

Run it from the repository root, with the config and database the report should describe:

    python -m cosa.research.preference_replay.retune_run --out /tmp/prediction-retune-report.json
"""

import argparse
import collections
import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import text

import cosa.utils.util as cu
from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
from cosa.repo.doc_lint.pool_builder import resolve_commit
from cosa.research.phi4_flash_lite_study.freeze_corpus import sha256_of_rows
from cosa.research.preference_replay.cohorts import cohort_asks
from cosa.research.preference_replay.question_vectors import load_side_file
from cosa.research.preference_replay.retune import ELIGIBLE_TYPES, eligible_asks, frozen_settings, report_only_sweep, retune
from cosa.rest.db.database import get_db
from cosa.utils.file_hash import file_sha256

REPORT_VERSION = 1
FACTS_SQL      = ( "select current_database(), current_user, now(), (select count(*) from prediction_decisions), "
                   "(select count(*) from prediction_decisions where answer_source is null)" )
NOTES          = [
    "Objective: correct forecasts per 100 eligible asks on the tune window, abstention charged as a miss.",
    "Eligible means yes/no or multiple-choice asks that carry a stored vector. Asks with no vector are excluded and counted, not re-embedded.",
    "The answered-ask figures and the sweep below the grid are report-only and never choose the best point. Open-ended keys are untouched.",
]


def read_cohort( session, vectors: Optional[Dict[str, List[float]]] = None, response_types: Sequence[str] = ELIGIBLE_TYPES ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Read the scored cohort and the facts that date it, in a read-only transaction.

    Requires:
        - session is an active SQLAlchemy session on the database the report should describe
        - vectors maps ask id to its side-file vector, or is None, the default, for the stored vectors, as the checkpoint run script calls it; response_types are names cohort_asks accepts

    Ensures:
        - the first statement makes the transaction read-only, so the database refuses any write
        - returns ( asks, facts ): the ask dicts of every type in order, and the database name, role,
          read time, prediction_decisions row count and the count of rows with no answer source
        - ends the transaction with a rollback
    """
    session.execute( text( "SET TRANSACTION READ ONLY" ) )
    row   = session.execute( text( FACTS_SQL ) ).fetchall()[ 0 ]
    facts = { "database": row[ 0 ], "db_role": row[ 1 ], "read_at": str( row[ 2 ] ),
              "prediction_decisions_rows": row[ 3 ], "answer_source_null_rows": row[ 4 ] }
    asks  = []
    for kind in response_types: asks += cohort_asks( session, kind, vectors=vectors )
    session.rollback()
    return asks, facts


def read_id_list( ids_path: str ) -> List[str]:
    """
    Read a committed id list in either of its two forms.

    Requires:
        - ids_path is a file with one id per line, either bare or as a JSON object with an "id" key

    Ensures:
        - returns the ids in file order, blank lines skipped
        - a line starting with an opening brace is JSON; any other line is a bare id

    Raises:
        - ValueError naming the file when its lines mix the two forms
    """
    with open( ids_path, encoding="utf-8" ) as handle: lines = [ line.strip() for line in handle if line.strip() ]
    as_json = [ line.startswith( "{" ) for line in lines ]
    if any( as_json ) and not all( as_json ): raise ValueError( f"{ids_path} mixes JSON lines and bare ids" )
    return [ json.loads( line )[ "id" ] for line in lines ] if any( as_json ) else lines


def restrict_to_ids( asks: List[Dict[str, Any]], ids_path: str ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Keep only the asks a committed id list names, in cohort order.

    Requires:
        - asks are cohort_asks dicts; ids_path is a file read by read_id_list

    Ensures:
        - returns ( kept, facts ), kept holding the asks whose id is listed, in their original order
        - facts names the file, its sha256 and the number of ids it lists

    Raises:
        - ValueError naming the count and the first ids when a listed id is not in the cohort
        - ValueError when the file mixes the two id forms
    """
    wanted  = read_id_list( ids_path )
    present = { ask[ "id" ] for ask in asks }
    absent  = [ ask_id for ask_id in wanted if ask_id not in present ]
    if absent: raise ValueError( f"{len( absent )} listed ids are not in the cohort, first: {absent[ :5 ]}" )
    keep = set( wanted )
    return [ ask for ask in asks if ask[ "id" ] in keep ], { "only_ids_file": ids_path, "only_ids_sha256": file_sha256( ids_path ), "only_ids_count": len( keep ) }


class ControlMismatch( RuntimeError ):
    """The control run did not reproduce the committed baseline."""


def write_control_ids( report: Dict[str, Any], asks: List[Dict[str, Any]], path: str, expect_replayable: int, expect_final_correct: int ) -> None:
    """
    Write the replayable ask ids, but only when the run reproduces the committed baseline.

    Requires:
        - report is what run_report returns; asks is the cohort it replayed

    Ensures:
        - checks that the replayable count equals expect_replayable and that the frozen point
          (threshold 0.5, top k 10) has expect_final_correct correct forecasts in the final window
        - on a match, writes the replayable ids one per line in cohort order, through a temporary name
        - on a mismatch, writes nothing

    Raises:
        - ControlMismatch naming each figure that differs, the measured value and the expected one
    """
    point    = next( point for point in report[ "grid_points" ] if point[ "threshold" ] == 0.5 and point[ "top_k" ] == 10 )
    measured = { "replayable": report[ "eligible" ], "final_correct": point[ "final_correct" ] }
    expected = { "replayable": expect_replayable, "final_correct": expect_final_correct }
    wrong    = [ f"{name}: measured {measured[ name ]}, expected {expected[ name ]}" for name in expected if measured[ name ] != expected[ name ] ]
    if wrong: raise ControlMismatch( "the control run does not reproduce the baseline; " + "; ".join( wrong ) )
    scratch = path + ".part"
    with open( scratch, "w", encoding="utf-8" ) as handle:
        for ask in eligible_asks( asks ): handle.write( ask[ "id" ] + "\n" )
    os.replace( scratch, path )


def check_vectors_cover( asks: List[Dict[str, Any]], header: Dict[str, Any] ) -> None:
    """
    Refuse a cohort that holds an ask with no vector the side file explains.

    Requires:
        - asks are cohort_asks dicts; header is the side file's header, whose rejects list { id, reason } entries

    Ensures:
        - returns None when every ask without a vector is one the side file lists as rejected

    Raises:
        - ValueError naming the count and the first ids of the asks that have no vector and no reject entry
    """
    rejected = { reject[ "id" ] for reject in header[ "rejects" ] }
    missing  = [ ask[ "id" ] for ask in asks if ask[ "question_embedding" ] is None and ask[ "id" ] not in rejected ]
    if missing: raise ValueError( f"{len( missing )} cohort asks have no vector in the side file and no reject entry, first: {missing[ :5 ]}" )


def build_report( result: Dict[str, Any], sweep_points: List[Dict[str, Any]], provenance: Dict[str, Any] ) -> Dict[str, Any]:
    """
    Assemble the report document from a retune result, the sweep and the provenance.

    Requires:
        - result is the dict retune returns; sweep_points is the list report_only_sweep returns
        - provenance holds cohort_sha256_all_ids and the run's facts

    Ensures:
        - returns a JSON-ready dict with the frozen settings, the best point, the window sizes, both checksums,
          the provenance, every grid point and every sweep point
        - the sweep never feeds the frozen settings or the best point
    """
    return {
        "version"                  : REPORT_VERSION,
        "what"                     : "The retune of the two retrieval settings and the metric. The committed INI values must equal frozen_settings; a unit test asserts it.",
        "frozen_settings"          : frozen_settings( result ),
        "best_point"               : result[ "best" ],
        "tune_size"                : result[ "tune_size" ],
        "final_size"               : result[ "final_size" ],
        "eligible"                 : result[ "eligible" ],
        "tune_cohort_sha256"       : result[ "tune_cohort_sha256" ],
        "cohort_sha256_all_ids"    : provenance[ "cohort_sha256_all_ids" ],
        "provenance"               : { key: value for key, value in provenance.items() if key != "cohort_sha256_all_ids" },
        "grid_points"              : result[ "points" ],
        "report_only_sweep_points" : sweep_points,
        "notes"                    : list( NOTES ),
    }


def run_report( asks: List[Dict[str, Any]], facts: Dict[str, Any], engine, run_facts: Dict[str, Any] ) -> Dict[str, Any]:
    """
    Replay the grid and the sweep over the cohort and build the report.

    Requires:
        - asks and facts are what read_cohort returns; engine is a PredictionEngine with embedding generation disabled
        - run_facts holds command, code_sha, driver_sha256 and started

    Ensures:
        - the snapshot checksum is the sha256 of every ask id in cohort order
        - the provenance names the replayable and not-replayable counts by type, the seconds taken and run_facts
        - returns the build_report document

    Raises:
        - ValueError when no ask is eligible, as retune raises
    """
    began    = time.time()
    snapshot = sha256_of_rows( [ { "id": ask[ "id" ] } for ask in asks ] )
    result   = retune( asks, engine, snapshot )
    sweep    = report_only_sweep( asks, engine, snapshot )
    usable   = eligible_asks( asks )
    provenance = dict( facts )
    provenance.update( {
        "cohort_asks"           : len( asks ),
        "cohort_asks_by_type"   : dict( collections.Counter( ask[ "response_type" ] for ask in asks ) ),
        "replayable_by_type"    : dict( collections.Counter( ask[ "response_type" ] for ask in usable ) ),
        "not_replayable"        : len( asks ) - len( usable ),
        "response_types"        : list( ELIGIBLE_TYPES ),
        "seconds"               : round( time.time() - began, 1 ),
        "cohort_sha256_all_ids" : snapshot,
    } )
    provenance.update( run_facts )
    return build_report( result, sweep, provenance )


def _open_engine():
    """
    Build the live engine from the real configuration, with embedding generation switched off.

    Ensures:
        - returns a fresh PredictionEngine whose embedding call raises, so a replay can use stored vectors only
    """
    PredictionEngine.reset()
    engine = PredictionEngine( debug=False )

    def _refuse( text_to_embed ):
        raise RuntimeError( "the retune embedded a message; it must use stored vectors only" )

    engine._generate_embedding = _refuse
    return engine


def main( argv: Optional[Sequence[str]] = None, printer: Callable = print, session_factory: Optional[Callable] = None,
          engine_factory: Optional[Callable] = None, code_sha: Optional[str] = None, clock: Optional[Callable] = None ) -> int:
    """
    Run the retune from the command line and write the report file.

    Requires:
        - argv holds --out, the report path, and one of --vectors, the side file, or --stored-vectors, the case rows' own vectors
        - an optional --only-ids names a committed list of ids to keep
        - an optional --control-ids-out needs --expect-replayable and --expect-final-correct
        - the factories and code_sha are injected by tests and default to the real ones

    Ensures:
        - reads the cohort read-only, runs the grid and the sweep, writes the report with sorted keys
        - with --control-ids-out, the report is written first and the id file only when the baseline is reproduced
        - the provenance names the exact command line, the code sha, the sha256 of this file, the start time, and the vector source: the stored vectors, or the side file with its sha256, model, revision and reject count
        - returns 0 after the report is written, and prints the frozen settings

    Raises:
        - ValueError when no ask is eligible
        - ControlMismatch when a control run does not reproduce its expected figures
    """
    parser = argparse.ArgumentParser( description="Run the retune over the real cohort and write its report." )
    parser.add_argument( "--out", required=True )
    source = parser.add_mutually_exclusive_group( required=True )
    source.add_argument( "--vectors", help="the question-vector side file every ask's vector is read from" )
    source.add_argument( "--stored-vectors", action="store_true", help="read each vector from its case row, as the control run does" )
    parser.add_argument( "--only-ids", help="a JSON-lines file of ask ids; the cohort is cut to exactly these, as the control run needs" )
    parser.add_argument( "--control-ids-out", help="write the replayable ids here, only if the baseline is reproduced; needs both --expect options" )
    parser.add_argument( "--expect-replayable", type=int, help="the replayable count the control must reproduce" )
    parser.add_argument( "--expect-final-correct", type=int, help="the final-window correct count at threshold 0.5 and top k 10 the control must reproduce" )
    args   = parser.parse_args( argv )
    if args.control_ids_out is not None and ( args.expect_replayable is None or args.expect_final_correct is None ):
        parser.error( "--control-ids-out needs --expect-replayable and --expect-final-correct" )
    session_factory = session_factory or get_db
    engine_factory  = engine_factory or _open_engine
    driver_sha256 = file_sha256( __file__ )
    command = "python -m cosa.research.preference_replay.retune_run " + " ".join( list( argv ) if argv is not None else sys.argv[ 1: ] )
    run_facts = {
        "command"       : command,
        "code_sha"      : code_sha if code_sha is not None else resolve_commit( cu.get_project_root(), "HEAD" ),
        "driver_sha256" : driver_sha256,
        "started"       : ( clock or ( lambda: datetime.now( timezone.utc ) ) )().isoformat(),
    }
    header, vectors = ( None, None ) if args.stored_vectors else load_side_file( args.vectors )
    if header is None: run_facts.update( { "vector_source": "stored" } )
    else:
        run_facts.update( { "vector_source": "side_file", "vector_side_file": args.vectors, "vector_side_file_sha256": file_sha256( args.vectors ),
                            "vector_model": header[ "model" ], "vector_revision": header[ "revision" ], "vector_rejects": len( header[ "rejects" ] ) } )
    with session_factory() as session:
        asks, facts = read_cohort( session, vectors )
    if args.only_ids is not None:
        asks, only = restrict_to_ids( asks, args.only_ids )
        run_facts.update( only )
    if header is not None: check_vectors_cover( asks, header )
    report = run_report( asks, facts, engine_factory(), run_facts )
    with open( args.out, "w", encoding="utf-8" ) as handle:
        json.dump( report, handle, indent=2, sort_keys=True )
        handle.write( "\n" )
    printer( json.dumps( report[ "frozen_settings" ], sort_keys=True ) )
    if args.control_ids_out is not None: write_control_ids( report, asks, args.control_ids_out, args.expect_replayable, args.expect_final_correct )
    return 0


if __name__ == "__main__":  # pragma: no cover - thin process entry, main() is what the tests drive
    sys.exit( main() )
