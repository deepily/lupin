"""
Score one context arm per ask on the final window, at the settings its retune froze.

The retune reports hold grid points but no per-ask records. A paired test needs the records.
This runs one replay of the arm's vectors at the frozen settings and keeps the final window.
The always-yes baseline is replayed beside it, on the same asks.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional, Sequence

import cosa.utils.util as cu
from cosa.repo.doc_lint.pool_builder import resolve_commit
from cosa.research.phi4_flash_lite_study.freeze_corpus import sha256_of_rows
from cosa.rest.db.database import get_db
from cosa.research.preference_replay.question_vectors import load_side_file
from cosa.research.preference_replay.replay_loop import ENGINE_ARM, always_yes_arm, replay
from cosa.research.preference_replay.retune import ELIGIBLE_TYPES, FROZEN_METRIC, METRIC_KEY, THRESHOLD_KEY, TOP_K_KEY, split_windows
from cosa.research.preference_replay.retune_run import _open_engine, check_vectors_cover, read_cohort, restrict_to_ids
from cosa.utils.file_hash import file_sha256

BASELINE_NAME = "always_yes"


def load_frozen( report_path: str ) -> Dict[str, Any]:
    """
    Read the frozen settings out of a retune report.

    Requires:
        - report_path names a retune report file

    Ensures:
        - returns threshold, top_k and metric as the engine takes them

    Raises:
        - ValueError if the metric is not the frozen cosine metric
    """
    with open( report_path, encoding="utf-8" ) as handle: frozen = json.load( handle )[ "frozen_settings" ]
    if frozen[ METRIC_KEY ] != FROZEN_METRIC: raise ValueError( f"{report_path} freezes metric {frozen[ METRIC_KEY ]!r}, not {FROZEN_METRIC!r}" )
    return { "threshold": frozen[ THRESHOLD_KEY ], "top_k": frozen[ TOP_K_KEY ], "metric": frozen[ METRIC_KEY ] }


def final_window( run: Dict[str, Any] ) -> Dict[str, Any]:
    """
    Cut a replay run to its final window, the same cut the retune makes.

    Requires:
        - run is the dict replay returns, with records for the engine arm

    Ensures:
        - returns a run whose every arm holds only the records after the tune window, re-indexed from zero
        - the counts of not-replayable and unrebuildable cases carry over unchanged
    """
    tune_size, _ = split_windows( len( run[ "records" ][ ENGINE_ARM ] ) )
    cut = { arm: [ dict( record, row_index=index ) for index, record in enumerate( records[ tune_size: ] ) ] for arm, records in run[ "records" ].items() }
    return { "records": cut, "not_replayable": run[ "not_replayable" ], "unrebuildable_cases": run[ "unrebuildable_cases" ], "families": run[ "families" ] }


def compact( run: Dict[str, Any] ) -> Dict[str, Any]:
    """
    Reduce a final-window run to the fields the report reads.

    Requires:
        - run is what final_window returns, holding the engine arm and the always-yes baseline over the same asks

    Ensures:
        - returns { asks, not_replayable, unrebuildable_cases, families }, asks holding per ask the id, answer type,
          forecast, confidence, correct and always_yes_correct, in run order
    """
    return { "asks": [ { "id": engine[ "meta" ][ "notification_id" ], "response_type": engine[ "meta" ][ "response_type" ],
                         "forecast": engine[ "meta" ][ "forecast" ], "confidence": engine[ "meta" ][ "confidence" ],
                         "correct": engine[ "meta" ][ "correct" ], "always_yes_correct": baseline[ "meta" ][ "correct" ] }
                       for engine, baseline in zip( run[ "records" ][ ENGINE_ARM ], run[ "records" ][ BASELINE_NAME ] ) ],
             "not_replayable": run[ "not_replayable" ], "unrebuildable_cases": run[ "unrebuildable_cases" ], "families": run[ "families" ] }


def expand( compacted: Dict[str, Any] ) -> Dict[str, Any]:
    """
    Rebuild a replay-shaped run from a compact one, so the report's comparison can read it.

    Requires:
        - compacted is what compact returns

    Ensures:
        - returns a run whose engine and always-yes records carry notification_id, response_type and correct, and the engine's also forecast and confidence
        - expand( compact( run ) ) holds the same per-ask figures as run
    """
    engine   = [ { "arm": ENGINE_ARM, "row_index": i, "meta": { "notification_id": a[ "id" ], "response_type": a[ "response_type" ], "forecast": a[ "forecast" ],
                                                                "confidence": a[ "confidence" ], "correct": a[ "correct" ] } } for i, a in enumerate( compacted[ "asks" ] ) ]
    baseline = [ { "arm": BASELINE_NAME, "row_index": i, "meta": { "notification_id": a[ "id" ], "response_type": a[ "response_type" ], "correct": a[ "always_yes_correct" ] } }
                 for i, a in enumerate( compacted[ "asks" ] ) ]
    return { "records": { ENGINE_ARM: engine, BASELINE_NAME: baseline }, "not_replayable": compacted[ "not_replayable" ],
             "unrebuildable_cases": compacted[ "unrebuildable_cases" ], "families": compacted[ "families" ] }


def score_arm( asks, engine, frozen: Dict[str, Any], snapshot_sha256: str ) -> Dict[str, Any]:
    """
    Replay the asks once at the frozen settings and keep the final window.

    Requires:
        - asks and engine are as replay takes them; frozen is what load_frozen returns

    Ensures:
        - returns the final-window run holding the engine arm and the always-yes baseline
        - the engine's three settings are restored, even when the replay raises
    """
    saved = ( engine.similarity_threshold, engine.cbr_top_k, engine.retrieval_metric )
    try:
        engine.similarity_threshold = frozen[ "threshold" ]
        engine.cbr_top_k            = frozen[ "top_k" ]
        engine.retrieval_metric     = frozen[ "metric" ]
        run = replay( asks, engine, snapshot_sha256, baselines={ BASELINE_NAME: always_yes_arm }, target_types=ELIGIBLE_TYPES )
    finally:
        engine.similarity_threshold, engine.cbr_top_k, engine.retrieval_metric = saved
    return final_window( run )


def main( argv: Optional[Sequence[str]] = None, printer: Callable = print, session_factory: Optional[Callable] = None,
          engine_factory: Optional[Callable] = None, code_sha: Optional[str] = None, clock: Optional[Callable] = None ) -> int:
    """
    Score one arm from the command line and write the per-ask run file.

    Requires:
        - argv holds --arm, --vectors, --settings (a retune report), --only-ids and --out

    Ensures:
        - reads the cohort read-only, cuts it to the frozen ids, replays once, writes the compact final-window run with sorted keys
        - the file names the arm, the settings, the side file and the ids file with their checksums
        - it also records the exact command line, the code sha and the start time; code_sha and clock are injected by tests
        - returns 0 and prints the arm, the window size and the correct count

    Raises:
        - ValueError if an eligible ask has no vector, or the report's metric is not cosine
    """
    parser = argparse.ArgumentParser( description="Score one context arm per ask on the final window." )
    for name in ( "--arm", "--vectors", "--settings", "--only-ids", "--out" ): parser.add_argument( name, required=True )
    args   = parser.parse_args( argv )
    started = ( clock or ( lambda: datetime.now( timezone.utc ) ) )().isoformat()
    command = "python -m cosa.research.preference_replay.arm_scoring " + " ".join( list( argv ) if argv is not None else sys.argv[ 1: ] )
    frozen = load_frozen( args.settings )
    header, vectors = load_side_file( args.vectors )
    with ( session_factory or get_db )() as session:
        asks, _ = read_cohort( session, vectors )
    asks, only = restrict_to_ids( asks, args.only_ids )
    check_vectors_cover( asks, header )
    run = score_arm( asks, ( engine_factory or _open_engine )(), frozen, sha256_of_rows( [ { "id": ask[ "id" ] } for ask in asks ] ) )
    document = { "arm": args.arm, "frozen": frozen, "settings_report": args.settings, "vector_side_file": args.vectors,
                 "vector_side_file_sha256": file_sha256( args.vectors ), "settings_report_sha256": file_sha256( args.settings ),
                 "vector_rejects": len( header[ "rejects" ] ), "ids": only, "command": command, "started": started,
                 "code_sha": code_sha if code_sha is not None else resolve_commit( cu.get_project_root(), "HEAD" ), "run": compact( run ) }
    with open( args.out, "w", encoding="utf-8" ) as handle:
        json.dump( document, handle, sort_keys=True, default=str, separators=( ",", ":" ) )
        handle.write( "\n" )
    correct = sum( 1 for ask in document[ "run" ][ "asks" ] if ask[ "correct" ] )
    printer( f"{args.arm}: {len( document[ 'run' ][ 'asks' ] )} final-window asks, {correct} correct" )
    return 0


if __name__ == "__main__":  # pragma: no cover - thin process entry, main() is what the tests drive
    sys.exit( main() )
