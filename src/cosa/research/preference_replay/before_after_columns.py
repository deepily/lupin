"""
Run one column of the before-and-after report and write it as a JSON file.

A column is one replay of the asks at one pair of retrieval settings, from one vector source.
This module replays the asks and cuts the run into its tune and final windows.
It scores each window by answer type and fits and scores the calibration.
It also compares the predictor with always-yes on the yes/no asks.
The figures are those of the checkpoint report, computed here from the replay records.
Rescoring a run on another run's final-window asks is the same code with a list of ids.
"""

import argparse
import collections
import json
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

import cosa.utils.util as cu
from cosa.repo.doc_lint.pool_builder import resolve_commit
from cosa.research.phi4_flash_lite_study.freeze_corpus import sha256_of_rows
from cosa.research.preference_replay.calibration_fit import fit_and_evaluate
from cosa.research.preference_replay.replay_loop import ENGINE_ARM, replay, summarize
from cosa.research.preference_replay.retune import ELIGIBLE_TYPES, split_windows
from cosa.research.preference_replay.retune_run import _open_engine, check_vectors_cover, read_cohort, restrict_to_ids
from cosa.research.preference_replay.before_after_report import final_correct
from cosa.research.preference_replay.question_vectors import load_side_file
from cosa.rest.db.database import get_db
from cosa.utils.atomic_json import write_json_atomic
from cosa.utils.file_hash import file_sha256

FLOOR = 10


def _scores( records: Sequence[Dict[str, Any]] ) -> Dict[str, Dict[str, int]]:
    """
    Count asks, scorable asks and correct forecasts by answer type.

    Requires:
        - records are engine records whose meta holds response_type and correct, and scorable (replay_loop.answer_split's)
          on a record replayed since 27 Nov 2026

    Ensures:
        - returns type to asks, scorable, correct and correct_scorable, with every eligible type present, zero when it has no records
        - correct counts every correct ask, as before 27 Nov 2026; scorable counts the asks whose answer can be scored at all
          (only a multiple-choice ask can fall short), and correct_scorable the correct asks among them, so correct_scorable
          over scorable is the accuracy over scorable cards
        - scorable and correct_scorable are None for a type when any of its records has no scorable flag (a record replayed
          or cached before 27 Nov 2026), because a count over only some of them would read as one over all
    """
    scores = {}
    for kind in ELIGIBLE_TYPES:
        metas          = [ r[ "meta" ] for r in records if r[ "meta" ][ "response_type" ] == kind ]
        recorded       = all( "scorable" in meta for meta in metas )
        scores[ kind ] = { "asks"             : len( metas ),
                           "scorable"         : sum( 1 for meta in metas if meta[ "scorable" ] ) if recorded else None,
                           "correct"          : sum( 1 for meta in metas if meta[ "correct" ] ),
                           "correct_scorable" : sum( 1 for meta in metas if meta[ "scorable" ] and meta[ "correct" ] ) if recorded else None }
    return scores


def _mix( records: Sequence[Dict[str, Any]] ) -> Dict[str, int]:
    """
    Count records by answer type.

    Requires:
        - records are engine records whose meta holds response_type

    Ensures:
        - returns type to count, only for types that occur
    """
    return dict( collections.Counter( r[ "meta" ][ "response_type" ] for r in records ) )


def _rows( records: Iterable[Dict[str, Any]] ) -> List[tuple]:
    """
    Turn engine records into the rows the calibration fit reads.

    Requires:
        - records are engine records whose meta holds response_type, strategy, confidence and correct

    Ensures:
        - returns ( type, strategy, confidence, correct ) for each record that has a confidence
    """
    return [ ( r[ "meta" ][ "response_type" ], r[ "meta" ][ "strategy" ], r[ "meta" ][ "confidence" ], bool( r[ "meta" ][ "correct" ] ) )
             for r in records if r[ "meta" ][ "confidence" ] is not None ]


def build_column( run: Dict[str, Any], header: Dict[str, Any], rescore_ids: Optional[Sequence[str]] = None, fit_time: Optional[str] = None ) -> Dict[str, Any]:
    """
    Build the figures of one column from a replay.

    Requires:
        - run is what replay returns, with engine and always_yes records, over the asks of header's ask count
        - header holds label, commit, vector_source, threshold, top_k, produced_by and cohort_asks
        - rescore_ids is None, or the final-window ask ids of another column to score this run on

    Ensures:
        - the run's replayable asks are cut into tune and final windows by position, as the retune does
        - without rescore_ids the final window is the run's own; with it the final asks are those ids from
          anywhere in the run, the tune window is the run's own minus those ids, and the tune window figures
          are marked not applicable by a tune_note
        - the calibration is fitted on the tune window and scored on the final asks
        - the yes/no summary compares the predictor with always-yes on the final yes/no asks
        - returns a column dict with every key check_columns requires
    """
    records = run[ "records" ][ ENGINE_ARM ]
    tune_n, _ = split_windows( len( records ) )
    tune    = records[ :tune_n ]
    final   = records[ tune_n: ]
    column  = dict( header )
    if rescore_ids is not None:
        wanted = set( rescore_ids )
        final  = [ r for r in records if r[ "meta" ][ "notification_id" ] in wanted ]
        tune   = [ r for r in tune if r[ "meta" ][ "notification_id" ] not in wanted ]
        column[ "tune_note" ] = "n/a: scored only on the final-window asks of column 1"
    final_ids = [ r[ "meta" ][ "notification_id" ] for r in final ]
    keep      = set( final_ids )
    final_yes_no = { arm: [ r for r in recs if r[ "meta" ][ "response_type" ] == "yes_no" and r[ "meta" ][ "notification_id" ] in keep ] for arm, recs in run[ "records" ].items() }
    families  = len( { r[ "meta" ][ "family" ] for r in final_yes_no[ ENGINE_ARM ] } )
    summary   = summarize( { "records": final_yes_no, "not_replayable": run[ "not_replayable" ], "unrebuildable_cases": run[ "unrebuildable_cases" ], "families": families }, "always_yes", FLOOR )
    snapshot  = sha256_of_rows( [ { "id": r[ "meta" ][ "notification_id" ] } for r in tune ] )
    _, report = fit_and_evaluate( _rows( tune ), _rows( final ), snapshot, fit_time or datetime.now( timezone.utc ).isoformat() )
    column.update( {
        "ask_count"      : len( records ),
        "ask_ids"        : [ r[ "meta" ][ "notification_id" ] for r in records ],
        "final_ids"      : final_ids,
        "coverage"       : { "cohort_asks": header[ "cohort_asks" ], "replayable": len( records ), "tune_mix": {} if rescore_ids is not None else _mix( tune ),
                             "final_mix": _mix( final ), "scores": { "tune": _scores( tune ), "final": _scores( final ) } },
        "calibration"    : report,
        "yes_no_summary" : json.loads( json.dumps( summary, default=float ) ),
    } )
    del column[ "cohort_asks" ]
    return column


def main( argv: Optional[Sequence[str]] = None, session_factory: Optional[Callable] = None, engine_factory: Optional[Callable] = None,
          printer: Callable = print, code_sha: Optional[str] = None ) -> int:
    """
    Replay the cohort at one setting and write the column file.

    Requires:
        - argv holds --out, --label, --threshold, --top-k and one of --vectors or --stored-vectors
        - an optional --only-ids cuts the cohort; an optional --rescore-from names a column file whose final ids the run is also scored on, with --rescored-out and --rescored-label
        - the database is read, never written

    Ensures:
        - writes the column as sorted-key JSON, naming the code commit, the vector source and the command line
        - with --rescore-from, also writes the rescored column, built from the same replay
        - returns 0 after the file is written

    Raises:
        - ValueError when --rescore-from names final asks that are not all in the run
    """
    parser = argparse.ArgumentParser( description="Replay the cohort at one setting and write one column of the before-and-after report." )
    parser.add_argument( "--out", required=True )
    parser.add_argument( "--label", required=True )
    parser.add_argument( "--threshold", type=float, required=True )
    parser.add_argument( "--top-k", type=int, required=True )
    source = parser.add_mutually_exclusive_group( required=True )
    source.add_argument( "--vectors" )
    source.add_argument( "--stored-vectors", action="store_true" )
    parser.add_argument( "--only-ids" )
    parser.add_argument( "--rescore-from", help="a column file whose final-window ask ids this run is also scored on, read after the replay" )
    parser.add_argument( "--rescored-out", help="where the rescored column goes" )
    parser.add_argument( "--rescored-label" )
    args   = parser.parse_args( argv )
    given = [ args.rescore_from, args.rescored_out, args.rescored_label ]
    if any( value is not None for value in given ) and None in given:
        parser.error( "--rescore-from, --rescored-out and --rescored-label go together" )
    commit = code_sha if code_sha is not None else resolve_commit( cu.get_project_root(), "HEAD" )
    side_header, vectors = ( None, None ) if args.stored_vectors else load_side_file( args.vectors )
    if side_header is None: vector_source = "stored vectors, read from each case row"
    else: vector_source = { "model": side_header[ "model" ], "revision": side_header[ "revision" ] }
    with ( session_factory or get_db )() as session:
        asks, _ = read_cohort( session, vectors )
    if args.only_ids is not None: asks, _ = restrict_to_ids( asks, args.only_ids )
    if side_header is not None: check_vectors_cover( asks, side_header )
    engine = ( engine_factory or _open_engine )()
    engine.retrieval_metric, engine.similarity_threshold, engine.cbr_top_k = "cosine", args.threshold, args.top_k
    snapshot = sha256_of_rows( [ { "id": ask[ "id" ] } for ask in asks ] )
    run      = replay( asks, engine, snapshot, target_types=ELIGIBLE_TYPES )
    command = "python -m cosa.research.preference_replay.before_after_columns " + " ".join( list( argv ) if argv is not None else [] )
    side    = f"side file sha256 {file_sha256( args.vectors )[ :12 ]}, " if args.vectors is not None else ""
    header  = { "label": args.label, "commit": commit, "vector_source": vector_source, "threshold": args.threshold, "top_k": args.top_k,
                "cohort_asks": len( asks ), "produced_by": f"commit {commit[ :9 ]}, {side}`{command}`" }
    column  = build_column( run, header )
    write_json_atomic( args.out, column, indent=1, trailing_newline=True, sort_keys=True )
    printer( f"{args.label}: {column[ 'ask_count' ]} replayed, final correct {final_correct( column )}" )
    if args.rescore_from is not None:
        with open( args.rescore_from, encoding="utf-8" ) as handle: rescore = json.load( handle )[ "final_ids" ]
        absent = sorted( set( rescore ) - set( column[ "ask_ids" ] ) )
        if absent: raise ValueError( f"{len( absent )} ids of {args.rescore_from} are not in this run, first: {absent[ :5 ]}" )
        rescored = build_column( run, dict( header, label=args.rescored_label ), rescore )
        write_json_atomic( args.rescored_out, rescored, indent=1, trailing_newline=True, sort_keys=True )
        printer( f"{args.rescored_label}: scored on {len( rescore )} asks, final correct {final_correct( rescored )}" )
    return 0


if __name__ == "__main__":  # pragma: no cover - thin process entry, main() is what the tests drive
    import sys
    sys.exit( main( sys.argv[ 1: ] ) )
