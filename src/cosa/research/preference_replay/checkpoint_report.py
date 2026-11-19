"""
The checkpoint report and the freeze file that keeps it frozen.

The report is a thin renderer. It takes the replay summaries, the calibration scores and the recorded
findings, and writes plain Markdown. Its intervals and McNemar results come from the replay's own summaries,
and its Brier scores from the calibration fit, so nothing is hand-computed here. ``label_metrics`` is a
scikit-learn per-label scorer that nothing calls yet. The summaries carry counts, not label lists, so the
renderer does not call it. It applies the pre-stated deferral rule: an interaction
type with fewer than 20 eligible asks in the final window is deferred until the data grows.

The freeze file, ``checkpoint.json``, names the report's sha256, the cohort's ``sha256_of_rows`` and the
commit that froze the settings. A later report is refused, with the mismatch named, when the baseline arm's
``snapshot_sha256`` is not the one in that file.
"""

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sklearn.metrics import confusion_matrix, jaccard_score, precision_recall_fscore_support

from cosa.research.phi4_flash_lite_study.freeze_corpus import sha256_of_rows, verify_snapshot, write_snapshot

DEFERRAL_FLOOR = 20


class CheckpointMismatch( RuntimeError ):
    """A later report's cohort is not the frozen one."""


def deferral( final_window_asks: Dict[str, int] ) -> Dict[str, Dict[str, Any]]:
    """
    Apply the deferral rule to each interaction type.

    Requires:
        - final_window_asks maps an interaction type to its eligible asks in the final window

    Ensures:
        - returns type to { "asks": n, "deferred": True when n is under DEFERRAL_FLOOR }
        - counts asks, not disagreeing pairs; the discordant floor is applied afterwards, to a phase's own result
    """
    return { name: { "asks": count, "deferred": count < DEFERRAL_FLOOR } for name, count in sorted( final_window_asks.items() ) }


def label_metrics( actual: Sequence[str], predicted: Sequence[str], labels: Sequence[str] ) -> Dict[str, Any]:
    """
    Score one arm's labels with scikit-learn.

    Requires:
        - actual and predicted are the same length and not empty
        - labels lists the possible labels, in the order the matrix is reported

    Ensures:
        - returns the confusion matrix, per-label precision, recall and f-score with support, and per-label Jaccard
    """
    precision, recall, f_score, support = precision_recall_fscore_support( actual, predicted, labels=list( labels ), zero_division=0 )
    return {
        "labels"           : list( labels ),
        "confusion_matrix" : confusion_matrix( actual, predicted, labels=list( labels ) ).tolist(),
        "precision"        : [ float( v ) for v in precision ],
        "recall"           : [ float( v ) for v in recall ],
        "f_score"          : [ float( v ) for v in f_score ],
        "support"          : [ int( v ) for v in support ],
        "jaccard"          : [ float( v ) for v in jaccard_score( actual, predicted, labels=list( labels ), average=None, zero_division=0 ) ],
    }


def render_report( summaries: Dict[str, Dict[str, Dict]], final_window_asks: Dict[str, int], calibration: Dict,
                   findings: List[Dict[str, str]], cohort_sha256: str, settings_commit: str, cohort_ids: Sequence[str],
                   retune: Optional[Dict[str, Any]] = None, sweep_points: Optional[List[Dict[str, Any]]] = None ) -> str:
    """
    Render the checkpoint report as Markdown.

    Requires:
        - summaries maps interaction type to baseline name to a replay_loop.summarize result
        - final_window_asks maps each type to its eligible final-window asks
        - calibration is the report half of calibration_fit.fit_and_evaluate
        - findings is a list of { title, detail } recorded before the run
        - cohort_ids names the asks in the cohort
        - retune is None or the retune result, whose points carry the answered figures for each window
        - sweep_points is None or the report-only sweep's points, in the same shape; they are shown only with a retune result

    Ensures:
        - returns text holding, per type, each baseline against the predictor with denominators, paired
          differences, intervals and unique families, the deferral verdict, the calibration cells, the findings,
          the cohort sha, the settings commit and every cohort id
        - with a retune result, a report-only table of every point's answered count, answer rate, accuracy among
          answered asks and correct per 100 asks, in each window, in threshold then top k order
        - a sweep point is labelled "report only", a retune point "grid", and the best line is retune's own best, never recomputed
        - the table informs a re-plan; it never picks the settings
        - the same inputs give the same text
    """
    lines = [ "# Checkpoint report", "", f"- cohort sha256: `{cohort_sha256}`", f"- settings commit: `{settings_commit}`",
              f"- cohort asks: {len( cohort_ids )}", "" ]
    for name, rule in deferral( final_window_asks ).items():
        lines += [ f"## {name}", "", f"Eligible final-window asks: {rule[ 'asks' ]}. " +
                   ( f"Deferred: fewer than {DEFERRAL_FLOOR} asks." if rule[ "deferred" ] else "Not deferred." ), "" ]
        for baseline, summary in sorted( summaries.get( name, {} ).items() ):
            lines += [ f"### Predictor against {baseline}", "",
                       f"- asks replayed: {summary[ 'asks_replayed' ]}; not replayable: {summary[ 'not_replayable' ]}; unique families: {summary[ 'families' ]}",
                       f"- predictor correct: {summary[ 'engine_correct' ]} {summary[ 'engine_interval' ]}",
                       f"- baseline correct: {summary[ 'baseline_correct' ]} {summary[ 'baseline_interval' ]}",
                       f"- discordant pairs: predictor only {summary[ 'engine_only_right' ]}, baseline only {summary[ 'baseline_only_right' ]}",
                       f"- McNemar exact: {summary[ 'mcnemar' ]}",
                       f"- discordant floor {summary[ 'operational_floor' ]} met: {summary[ 'floor_met' ]}; verdict: {summary[ 'verdict' ]}", "" ]
    lines += [ "## Calibration", "", f"Tune asks {calibration[ 'tune_size' ]}, final asks {calibration[ 'final_size' ]}.", "" ]
    for key, cell in sorted( calibration[ "cells" ].items() ):
        lines.append( f"- {key}: {cell[ 'status' ]}" + ( f", Brier raw {cell[ 'brier_raw' ]:.4f}, calibrated {cell[ 'brier_calibrated' ]:.4f}" if cell[ "status" ] == "evaluated" else "" ) )
    if retune is not None:
        lines += [ "", "## Retune sweep (report only)", "",
                   f"Tune asks {retune[ 'tune_size' ]}, final asks {retune[ 'final_size' ]}. Answer rate is answered asks per 100 asks;"
                   " accuracy among answered is correct per 100 answered asks. The settings were chosen on tune correct per 100 alone.", "",
                   "| threshold | top k | tune answered | tune answer rate | tune accuracy among answered | tune correct per 100 |"
                   " final answered | final answer rate | final accuracy among answered | final correct per 100 | set |",
                   "|---|---|---|---|---|---|---|---|---|---|---|" ]
        labelled = [ ( point, "grid" ) for point in retune[ "points" ] ] + [ ( point, "report only" ) for point in ( sweep_points or [] ) ]
        for point, label in sorted( labelled, key=lambda pair: ( pair[ 0 ][ "threshold" ], pair[ 0 ][ "top_k" ] ) ):
            lines.append( f"| {point[ 'threshold' ]} | {point[ 'top_k' ]} | {point[ 'tune_answered' ]} | {point[ 'tune_answer_rate_per_100' ]:.1f} |"
                          f" {point[ 'tune_accuracy_answered_per_100' ]:.1f} | {point[ 'tune_per_100' ]:.1f} | {point[ 'final_answered' ]} |"
                          f" {point[ 'final_answer_rate_per_100' ]:.1f} | {point[ 'final_accuracy_answered_per_100' ]:.1f} | {point[ 'final_per_100' ]:.1f} | {label} |" )
        lines += [ "", f"Best on the tune window: threshold {retune[ 'best' ][ 'threshold' ]}, top k {retune[ 'best' ][ 'top_k' ]}." ]
    lines += [ "", "## Recorded findings", "" ] + [ f"- **{finding[ 'title' ]}**: {finding[ 'detail' ]}" for finding in findings ]
    lines += [ "", "## Cohort ids", "" ] + [ f"- {ask_id}" for ask_id in cohort_ids ] + [ "" ]
    return "\n".join( lines )


def write_checkpoint( report_text: str, cohort_rows: List[Dict], snapshot_path: str, manifest_path: str,
                      checkpoint_path: str, settings_commit: str, frozen_at: Optional[str] = None ) -> Dict[str, Any]:
    """
    Freeze the cohort and write the freeze file.

    Requires:
        - report_text is the rendered report; cohort_rows is the list of cohort row dicts
        - the three paths are writable; settings_commit names the commit that froze the settings

    Ensures:
        - writes the cohort with write_snapshot and a manifest verify_snapshot reads
        - re-derives the cohort sha from the file on disk and refuses when it disagrees
        - writes checkpoint.json with the report sha256, the cohort sha256 and row count, and the settings commit
        - returns the freeze document

    Raises:
        - CheckpointMismatch if verify_snapshot does not re-derive the cohort sha
    """
    cohort_sha = sha256_of_rows( cohort_rows )
    write_snapshot( cohort_rows, snapshot_path )
    with open( manifest_path, "w", encoding="utf-8" ) as handle:
        json.dump( { "snapshot_sha256": cohort_sha, "snapshot_row_count": len( cohort_rows ), "minimum_rows": 1 }, handle, sort_keys=True )
    ok, detail = verify_snapshot( snapshot_path, manifest_path )
    if not ok: raise CheckpointMismatch( f"the cohort file does not re-derive its sha: {detail}" )
    document = {
        "report_sha256"   : hashlib.sha256( report_text.encode( "utf-8" ) ).hexdigest(),
        "cohort_sha256"   : cohort_sha,
        "cohort_rows"     : len( cohort_rows ),
        "settings_commit" : settings_commit,
        "frozen_at"       : frozen_at if frozen_at is not None else datetime.now( timezone.utc ).isoformat(),
    }
    with open( checkpoint_path, "w", encoding="utf-8" ) as handle:
        json.dump( document, handle, indent=2, sort_keys=True )
        handle.write( "\n" )
    return document


def refuse_post_checkpoint_report( records: List[Dict], checkpoint_path: str, printer=print ) -> int:
    """
    Refuse a report whose baseline arm is not on the frozen cohort.

    Requires:
        - records are the baseline arm's replay records, each with snapshot_sha256
        - checkpoint_path names a checkpoint.json written by write_checkpoint

    Ensures:
        - returns 0 when every record's snapshot_sha256 equals the freeze file's cohort sha256
        - otherwise prints the mismatch, naming both shas, and returns 3
        - an empty record list is refused, because it matches nothing

    Raises:
        - OSError if the freeze file cannot be read
    """
    with open( checkpoint_path, "r", encoding="utf-8" ) as handle:
        frozen = json.load( handle )[ "cohort_sha256" ]
    seen = sorted( { record[ "snapshot_sha256" ] for record in records } )
    if seen == [ frozen ]: return 0
    printer( f"REFUSED: the baseline arm's snapshot_sha256 {seen or 'none (no records)'} is not the frozen cohort sha256 {frozen}" )
    return 3


def main( argv: Optional[Sequence[str]] = None, printer=print ) -> int:
    """
    Check a replay's baseline records against the freeze file from the command line.

    Requires:
        - argv holds --records, a JSON file of baseline-arm records, and --checkpoint, the freeze file

    Ensures:
        - returns refuse_post_checkpoint_report's code, so a mismatch is a non-zero exit
    """
    import argparse
    parser = argparse.ArgumentParser( description="Refuse a report that is not on the frozen cohort." )
    parser.add_argument( "--records", required=True )
    parser.add_argument( "--checkpoint", required=True )
    args = parser.parse_args( argv )
    with open( args.records, "r", encoding="utf-8" ) as handle:
        records = json.load( handle )
    return refuse_post_checkpoint_report( records, args.checkpoint, printer )


if __name__ == "__main__":  # pragma: no cover - thin process entry, main() is what the tests drive
    import sys
    sys.exit( main() )
