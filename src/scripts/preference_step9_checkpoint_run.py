"""
The run script that made the committed checkpoint report.

It is committed unchanged except for one line. The original read step8_result.json from its own scratchpad.
This copy takes that folder as its one argument.
It ran at commit 086f95590 and calls read_cohort( session ).
After the stored-vectors change to read_cohort( session, vectors ) it needs that stored-vectors path to reproduce the Before column.
The replay code it ran against is commit 086f95590, and the frozen settings are from commit ba045c7ce.
Run from the repository root with LUPIN_ROOT and PYTHONPATH pinned to the tree.
"""

import json, subprocess, hashlib, sys
from cosa.rest.db.database import get_db
from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
from cosa.research.preference_replay import retune as rt
from cosa.research.preference_replay.before_after_columns import _mix, _scores
from cosa.research.preference_replay.retune_run import read_cohort, _open_engine
from cosa.research.preference_replay.replay_loop import replay, summarize, ENGINE_ARM
from cosa.research.preference_replay.checkpoint_report import render_report, write_checkpoint, refuse_post_checkpoint_report
from cosa.research.phi4_flash_lite_study.freeze_corpus import sha256_of_rows

SCR   = sys.argv[ 1 ].rstrip( "/" ) + "/"   # the folder holding step8_result.json; the original run read its own scratchpad
FLOOR = 10
frozen = json.load( open( "src/conf/prediction-retune-report.json" ) )
step8  = json.load( open( SCR + "step8_result.json" ) )
head   = subprocess.check_output( [ "git", "rev-parse", "HEAD" ], text=True ).strip()
settings_commit = subprocess.check_output( [ "git", "rev-parse", "ba045c7ce" ], text=True ).strip()

with get_db() as s: asks, facts = read_cohort( s )
frozen_ids = { json.loads( line )[ "id" ] for line in open( "src/conf/prediction-checkpoint-cohort.jsonl" ) }
print( "live asks", len( asks ), "not in the frozen cohort", sum( 1 for a in asks if a[ "id" ] not in frozen_ids ), flush=True )
asks = [ a for a in asks if a[ "id" ] in frozen_ids ]
snapshot = sha256_of_rows( [ { "id": a[ "id" ] } for a in asks ] )
assert snapshot == frozen[ "cohort_sha256_all_ids" ], "cohort moved since the freeze"
eng = _open_engine()
eng.retrieval_metric, eng.similarity_threshold, eng.cbr_top_k = "cosine", 0.5, 10
run = replay( asks, eng, snapshot, target_types=rt.ELIGIBLE_TYPES )
engine_records = run[ "records" ][ ENGINE_ARM ]
tune_n, final_n = rt.split_windows( len( engine_records ) )
final_ids = { r[ "meta" ][ "notification_id" ] for r in engine_records[ tune_n: ] }
tune_mix  = _mix( engine_records[ :tune_n ] )
final_mix = _mix( engine_records[ tune_n: ] )
final_correct = sum( 1 for r in engine_records[ tune_n: ] if r[ "meta" ][ "correct" ] )
print( "final correct", final_correct, "frozen", frozen[ "best_point" ][ "final_correct" ], flush=True )
assert final_correct == frozen[ "best_point" ][ "final_correct" ], "replay at the frozen settings disagrees with the freeze"

def final_run( kind ):
    keep = lambda r: r[ "meta" ][ "response_type" ] == kind and r[ "meta" ][ "notification_id" ] in final_ids
    recs = { arm: [ r for r in rs if keep( r ) ] for arm, rs in run[ "records" ].items() }
    return { "records": recs, "not_replayable": sum( 1 for a in asks if a[ "response_type" ] == kind and a[ "question_embedding" ] is None ),
             "unrebuildable_cases": run[ "unrebuildable_cases" ], "families": len( { r[ "meta" ][ "family" ] for r in recs[ ENGINE_ARM ] } ) }
final_by_type = { kind: len( final_run( kind )[ "records" ][ ENGINE_ARM ] ) for kind in rt.ELIGIBLE_TYPES }
summaries = { "yes_no": { arm: json.loads( json.dumps( summarize( final_run( "yes_no" ), arm, FLOOR ), default=float ) ) for arm in ( "always_yes", "prior_majority" ) } }

prov = frozen[ "provenance" ]
coverage = { "cohort_asks": len( asks ), "replayable": len( engine_records ), "tune_mix": tune_mix, "final_mix": final_mix,
             "scores": { "tune": _scores( engine_records[ :tune_n ] ), "final": _scores( engine_records[ tune_n: ] ) } }
print( "scores", coverage[ "scores" ], flush=True )
ys = summaries[ "yes_no" ][ "always_yes" ]
bp = frozen[ "best_point" ]
findings = [
 { "title": "Retune provenance", "detail": f"The frozen settings come from the tool-written retune report at settings commit {settings_commit[:9]}. Its code sha is {prov[ 'code_sha' ][:9]} and its driver sha256 is {prov[ 'driver_sha256' ]}. The command was `{prov[ 'command' ]}`. A second run from the committed tool matched the freeze in grid, sweep, best point and sizes." },
 { "title": "On yes/no the baselines beat the predictor on the final window", "detail": f"Of 215 final-window yes/no asks, the predictor was right on {ys[ 'engine_correct' ]}. Always-yes was right on {ys[ 'baseline_correct' ]}. The predictor alone was right on {ys[ 'engine_only_right' ]} asks, and always-yes alone on {ys[ 'baseline_only_right' ]}. That meets the floor of {FLOOR} discordant pairs. Prior-majority gives the same counts. The verdict on yes/no is baseline better." },
 { "title": "Two asks scored after the freeze are left out", "detail": "The live database held 3610 scored asks when this report was made. Two were scored after the retune and are left out, so the cohort stays the 3608 the freeze names. The replay at the frozen settings gives the same 177 final-window correct as the retune report." },
 { "title": "Multiple choice is mostly wrong", "detail": f"The predictor was right on {coverage[ 'scores' ][ 'tune' ][ 'multiple_choice' ][ 'correct' ]} of {coverage[ 'scores' ][ 'tune' ][ 'multiple_choice' ][ 'asks' ]} tune-window multiple-choice asks and {coverage[ 'scores' ][ 'final' ][ 'multiple_choice' ][ 'correct' ]} of {coverage[ 'scores' ][ 'final' ][ 'multiple_choice' ][ 'asks' ]} final-window ones. Yes/no was right on {coverage[ 'scores' ][ 'tune' ][ 'yes_no' ][ 'correct' ]} of {coverage[ 'scores' ][ 'tune' ][ 'yes_no' ][ 'asks' ]} and {coverage[ 'scores' ][ 'final' ][ 'yes_no' ][ 'correct' ]} of {coverage[ 'scores' ][ 'final' ][ 'yes_no' ][ 'asks' ]}. Yes/no scores 76.1 and 75.8 correct per 100 in the two windows, and multiple choice 1.8 and 8.0. The report does not say why multiple choice scores so low." },
 { "title": "Windows differ in kind and in result", "detail": f"The final window beat the tune window at the frozen settings. Correct per 100 asks was {bp[ 'final_per_100' ]:.2f} against {bp[ 'tune_per_100' ]:.2f}. The answer rate was {bp[ 'final_answer_rate_per_100' ]:.1f} against {bp[ 'tune_answer_rate_per_100' ]:.1f}. Multiple choice is {100 * tune_mix[ 'multiple_choice' ] / tune_n:.0f}% of the tune window and {100 * final_mix[ 'multiple_choice' ] / final_n:.0f}% of the final window. The report states both facts and does not say why." },
 { "title": "Only yes/no majority vote gets a useful calibration fit", "detail": "The yes/no majority-vote cell is fitted on 342 tune asks and scored on 205 final asks. Its Brier score is 0.2239 raw and 0.1728 calibrated." },
 { "title": "Multiple-choice cold start is degenerate", "detail": "Every multiple-choice cold-start forecast has confidence 0 and is scored a miss. Its Brier score is 0.0 raw and calibrated, on 536 tune asks and 161 final asks. The map carries no information." },
 { "title": "Two calibration cells are not fitted", "detail": "Multiple-choice majority vote has 11 tune asks, and yes/no cold start has 22. Each needs 50, so each is reported as not fitted. Calibration enabled stays false." },
 { "title": "Multiple choice has no baseline arm", "detail": "The always-yes and prior-majority arms forecast yes/no asks only. The paired comparison therefore covers yes/no. Multiple choice is reported by the retune table and the calibration alone." },
 { "title": "Audit windows key on the prediction time", "detail": "Windowing by ask time instead moves exactly one ask from after the cut-over to undetermined. It was asked just before the cut-over and predicted after it. By prediction time the yes/no windows are 25, 54 and 60 asks, matching the old-engine artifact. This was measured on the 285-ask export, which holds 139 yes/no asks." },
 { "title": "Title-collision counts (Sam)", "detail": "On the 285-ask export the plan's family key gives 263 families. Titles cut at 50 characters number 148 of 285. No distinct messages share a family because of the cut. Three families hold more than one distinct message, covering 7 asks, all with titles under the cap. Retry copies are 4 in 281 groups. The export, not the stored title, is the population measured." },
 { "title": "Session window is an assumption (Maya)", "detail": "The context rebuild keeps a 2 hour sender-session window as a named constant. Among asks only there are 920 sessions and 6,822 gaps, with median 11.2 minutes, p90 97.2, p99 488 and 7.8% over 2 hours. Counting asks and non-asks from 4 to 18 Nov, there are 564 sessions and 79,524 gaps. The median is 0.1 minutes, p99 is 12.1, and 0.1% are over 2 hours. The rebuild over 7,863 asks gives 6,909 reconstructed, 857 no_context and 97 ambiguous_only. From 4 Nov, 529 of 535 are reconstructed. The earlier figure is a lower bound." },
]
retune_doc = { "points": frozen[ "grid_points" ], "best": frozen[ "best_point" ], "tune_size": frozen[ "tune_size" ], "final_size": frozen[ "final_size" ],
               "eligible": frozen[ "eligible" ], "tune_cohort_sha256": frozen[ "tune_cohort_sha256" ] }
cohort_rows = [ { "id": a[ "id" ] } for a in asks ]
text = render_report( summaries, final_by_type, step8[ "report" ], findings, snapshot, settings_commit, [ a[ "id" ] for a in asks ],
                      retune=retune_doc, sweep_points=frozen[ "report_only_sweep_points" ], coverage=coverage )
open( "src/conf/prediction-checkpoint-report.md", "w", encoding="utf-8" ).write( text )
doc = write_checkpoint( text, cohort_rows, "src/conf/prediction-checkpoint-cohort.jsonl", "src/conf/prediction-checkpoint-cohort-manifest.json",
                        "src/conf/prediction-checkpoint.json", settings_commit )
print( json.dumps( doc, indent=1 ) )
ok_records   = [ { "snapshot_sha256": snapshot } ]
bad_records  = [ { "snapshot_sha256": "0" * 64 } ]
print( "matching records ->", refuse_post_checkpoint_report( ok_records, "src/conf/prediction-checkpoint.json" ) )
print( "planted mismatch ->", refuse_post_checkpoint_report( bad_records, "src/conf/prediction-checkpoint.json" ) )
print( "baseline arm shas ->", sorted( { r[ "snapshot_sha256" ] for r in run[ "records" ][ "always_yes" ] } ) == [ snapshot ] )
print( "final_by_type", final_by_type, "summaries", { b: ( v[ "engine_correct" ], v[ "baseline_correct" ], v[ "engine_only_right" ], v[ "baseline_only_right" ], v[ "floor_met" ], v[ "verdict" ] ) for b, v in summaries[ "yes_no" ].items() } )
print( "head", head )
