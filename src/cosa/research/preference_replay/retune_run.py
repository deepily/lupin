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
        - argv holds --out, the report path, and one of --vectors, the side file, or --stored-vectors, the case rows' own vectors; the factories and code_sha are injected by tests and default to the real ones

    Ensures:
        - reads the cohort read-only, runs the grid and the sweep, writes the report with sorted keys
        - the provenance names the exact command line, the code sha, the sha256 of this file, the start time, and the vector source: the stored vectors, or the side file with its sha256, model, revision and reject count
        - returns 0 after the report is written, and prints the frozen settings

    Raises:
        - ValueError when no ask is eligible
    """
    parser = argparse.ArgumentParser( description="Run the retune over the real cohort and write its report." )
    parser.add_argument( "--out", required=True )
    source = parser.add_mutually_exclusive_group( required=True )
    source.add_argument( "--vectors", help="the question-vector side file every ask's vector is read from" )
    source.add_argument( "--stored-vectors", action="store_true", help="read each vector from its case row, as the control run does" )
    args   = parser.parse_args( argv )
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
    if header is not None: check_vectors_cover( asks, header )
    report = run_report( asks, facts, engine_factory(), run_facts )
    with open( args.out, "w", encoding="utf-8" ) as handle:
        json.dump( report, handle, indent=2, sort_keys=True )
        handle.write( "\n" )
    printer( json.dumps( report[ "frozen_settings" ], sort_keys=True ) )
    return 0


if __name__ == "__main__":  # pragma: no cover - thin process entry, main() is what the tests drive
    sys.exit( main() )
