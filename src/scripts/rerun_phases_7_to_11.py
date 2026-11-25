#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
Replay the preference engine from stored vectors with no model call.

Plan: src/rnd/v0.2.4/2026.11.17-online-preference-learning-upgrades/2026.11.24-rerun-phases-7-to-11-plan.md.
Every model entry point raises while the replay runs. The cohort is read in a read-only transaction.
Nothing is written to a database. Output files are new; no earlier result is edited.

Run from a seat tree, pinning all three:

    cd <tree> && LUPIN_ROOT="$PWD" PYTHONPATH="$PWD/src" .venv/bin/python src/scripts/rerun_phases_7_to_11.py \
        --vectors <side file> --records <run 2 records.jsonl> --out-dir <folder>
"""

import argparse
import collections
import functools
import os
import pickle
import subprocess
import sys

sys.path.insert( 0, os.path.dirname( os.path.abspath( __file__ ) ) )

import zero_model_proof as zmp
from cosa.repo.labelling.rick_page import ids_sha256 as sha256_of_ids
from cosa.research.preference_replay import replay_loop
from cosa.research.preference_replay.before_after_columns import _scores
from cosa.research.preference_replay.retune import TUNE_FRACTION, split_windows
from cosa.research.preference_replay.retune_run import read_id_list
from cosa.utils.atomic_json import write_json_atomic
from cosa.utils.file_hash import file_sha256
from scripts.check_bundle_freshness import current_sha

# The names this script's callers and tests have always used, now the shared helpers themselves.
sha256_of   = file_sha256
read_ids    = read_id_list
paired_wins = replay_loop.paired_wins
code_sha    = functools.partial( current_sha, short=False )

FROZEN            = { "threshold": 0.5, "top_k": 10, "metric": "cosine" }
OLD_CONTROL       = { "final_all": 177, "final_yes_no": 163, "final_mc": 14, "final_mc_asks": 176, "final_yes_no_asks": 215, "tune": 911, "final": 391 }
SWITCHES          = ( "prediction engine full answer reply enabled", "prediction engine per field multiple choice enabled",
                      "prediction engine complete action scoring enabled", "prediction engine lookup neither forecast enabled",
                      "prediction engine failure visibility enabled", "prediction engine calibration enabled",
                      "prediction engine three way enabled", "decision proxy neither means reframe enabled" )


def columns_of( record_ids, second_ids, old_ids, replayable_ids ):
    """
    Name the plan's cohort columns, each a set of ask ids usable as a case pool.

    Requires:
        - the arguments are lists of ids; replayable_ids are the ids the database cohort holds with a stored vector

    Ensures:
        - returns second, record and old_1302 as sets, each cut to replayable_ids; a column's replay uses only its own asks as cases
        - the record ids outside replayable_ids are in no column; the caller reports their count
    """
    keep = set( replayable_ids )
    return { "second": set( second_ids ) & keep, "record": set( record_ids ) & keep, "old_1302": set( old_ids ) & keep }


def split_by_time( ordered_ids, fraction=TUNE_FRACTION ):
    """
    Cut ids, already in ask order, into a tune list and a final list by position.

    Requires:
        - ordered_ids are in ask-time order; 0 < fraction < 1

    Ensures:
        - tune is the first floor( fraction x count ) ids, final is the rest; the two share no id
    """
    cut, _ = split_windows( len( ordered_ids ), fraction )
    return ordered_ids[ :cut ], ordered_ids[ cut: ]


def replay_config( asks, engine, per_field, failure_visibility, extra_arms, label ):
    """
    Replay the asks against themselves as cases, with two engine switches set.

    Requires:
        - asks are cohort asks, already cut to one column; engine is a PredictionEngine; extra_arms maps a name to a baseline arm

    Ensures:
        - returns { run, reasons } where run is replay's result and reasons lists the engine's abstention reason, or None, per replayed ask in replay order
        - the engine's per_field_mc_enabled and failure_visibility_enabled are restored, even when the replay raises
    """
    from cosa.research.preference_replay import replay_loop
    saved   = ( engine.per_field_mc_enabled, engine.failure_visibility_enabled, engine.predict )
    reasons = []
    real    = engine.predict

    def recording( notification, **kwargs ):
        result = real( notification, **kwargs )
        reasons.append( result.metadata.get( "reason" ) )
        return result

    try:
        engine.per_field_mc_enabled       = per_field
        engine.failure_visibility_enabled = failure_visibility
        engine.predict                    = recording
        baselines = { "always_yes": replay_loop.always_yes_arm, **extra_arms }
        run = replay_loop.replay( asks, engine, label, baselines=baselines, target_types=( "yes_no", "multiple_choice" ) )
    finally:
        engine.per_field_mc_enabled, engine.failure_visibility_enabled, engine.predict = saved
    return { "run": run, "reasons": reasons }


def window_counts( records ):
    """
    Count correct forecasts in the freeze's final window, by response type.

    Requires:
        - records are one arm's replay records in ask order, over every type

    Ensures:
        - returns tune and final sizes, and for the final window the asks and correct counts of all, yes/no and multiple choice
    """
    tune, final = split_windows( len( records ) )
    tail        = records[ tune: ]
    scores      = _scores( tail )
    return { "tune": tune, "final": final, "final_all": sum( 1 for r in tail if r[ "meta" ][ "correct" ] ),
             "final_yes_no_asks": scores[ "yes_no" ][ "asks" ], "final_yes_no": scores[ "yes_no" ][ "correct" ],
             "final_mc_asks": scores[ "multiple_choice" ][ "asks" ], "final_mc": scores[ "multiple_choice" ][ "correct" ] }


def control_mismatches( counts ):
    """Return the control figures that differ from the old record."""
    return [ ( name, counts[ name ], expected ) for name, expected in OLD_CONTROL.items() if counts[ name ] != expected ]


def with_reasons( records, reasons ):
    """
    Put each ask's abstention reason into its record's meta, for the engine arm.

    Requires:
        - reasons has one entry per record, in the same order

    Ensures:
        - returns the records with meta[ "reason" ] set; the input is not changed
    """
    return [ dict( record, meta=dict( record[ "meta" ], reason=reason ) ) for record, reason in zip( records, reasons, strict=True ) ]


def per_ask_document( arm, records_by_column, header ):
    """
    Build one arm's per-ask document, with one list of asks per column.

    Requires:
        - records_by_column maps a column name to the arm's replay records for that column's own replay; header is a dict of stamps

    Ensures:
        - returns a dict holding the header and run.asks_by_column, one entry per record
        - each ask carries id, response_type, forecast, confidence, correct, probabilities, strategy and reason
    """
    columns = {}
    for name, records in records_by_column.items():
        asks = []
        for record in records:
            meta     = record[ "meta" ]
            forecast = meta[ "forecast" ]
            asks.append( { "id": meta[ "notification_id" ], "response_type": meta[ "response_type" ], "forecast": forecast,
                           "confidence": meta.get( "confidence" ), "correct": meta[ "correct" ],
                           "probabilities": forecast.get( "probabilities" ) if isinstance( forecast, dict ) else None,
                           "strategy": meta.get( "strategy" ), "reason": meta.get( "reason" ) } )
        columns[ name ] = asks
    return dict( header, arm=arm, run={ "asks_by_column": columns } )


def write_json( path, document ):
    """Write a document as sorted, indented JSON and return the file's sha256."""
    write_json_atomic( path, document, indent=1, sort_keys=True )
    return sha256_of( path )


def read_switches( ini_path ):
    """Return the plan's switches as the INI file states them; an absent key reads as None."""
    found = {}
    with open( ini_path, encoding="utf-8" ) as handle:
        for line in handle:
            if "=" in line and not line.lstrip().startswith( "#" ):
                key, value = line.split( "=", 1 )
                found[ key.strip() ] = value.strip()
    return { name: found.get( name ) for name in SWITCHES }


OLD_DIFFERENCES = {
    "phase7 per_field against control, multiple choice, final window" : 0,    # prediction-phase7-paired-report.json, strict_paired.header_vs_off: 0 and 0 discordant
    "phase8 three_way against always_yes, yes/no, final window"       : 0,    # prediction-three-way-replay-report.md: 173 and 173, 0 discordant
    "phase8 three_way against margin rule, yes/no, final window"      : 10,   # same report: challenger right alone on 10, margin rule on none
}
OPERATIONAL_FLOOR = 10


def sign_of( value ):
    """Return 1, -1 or 0 for the sign of a number; 0 means no sign."""
    return ( value > 0 ) - ( value < 0 )


def reversal( old, new ):
    """
    Say whether a paired difference reversed sign, by Rick's V6 rule.

    Requires:
        - old and new are integers, the arm's wins minus the other's

    Ensures:
        - returns "no sign" when either difference is 0, "sign reversed" when they differ in sign, else "same sign"
    """
    if sign_of( old ) == 0 or sign_of( new ) == 0: return "no sign"
    return "same sign" if sign_of( old ) == sign_of( new ) else "sign reversed"


def column_run( run, ids, response_type=None ):
    """
    Cut a replay run to the asks of one column, optionally to one response type.

    Requires:
        - run is replay's result; ids is a set of ask ids

    Ensures:
        - every arm keeps only the records whose ask is in ids (and of response_type, when given), in order and re-indexed
        - the counts of not-replayable and unrebuildable cases and the family count carry over unchanged
    """
    def keep( record ):
        meta = record[ "meta" ]
        return meta[ "notification_id" ] in ids and ( response_type is None or meta[ "response_type" ] == response_type )
    cut = { arm: [ dict( r, row_index=i ) for i, r in enumerate( [ r for r in records if keep( r ) ] ) ] for arm, records in run[ "records" ].items() }
    return { "records": cut, "not_replayable": run[ "not_replayable" ], "unrebuildable_cases": run[ "unrebuildable_cases" ], "families": run[ "families" ] }


def of_type( records, kind ):
    """Keep the records of one response type, in order."""
    return [ r for r in records if r[ "meta" ][ "response_type" ] == kind ]


def final_records( records ):
    """
    Cut an arm's records, over every response type, to the freeze's final window by position.

    Requires:
        - records are in ask order and cover every type of the column

    Ensures:
        - returns the records after the first floor( 0.7 x count ), as retune and the old reports cut them
    """
    from cosa.research.preference_replay.retune import split_windows
    tune, _ = split_windows( len( records ) )
    return records[ tune: ]


def phase7_column( control_run, new_run, ids ):
    """
    Compare per-field multiple choice with the control on one column.

    Requires:
        - both runs cover the same asks in the same order; ids is the column's id set

    Ensures:
        - the final window is the freeze's, cut over every type before the multiple-choice asks are kept, as the old report cut it
        - returns the whole-column and final-window counts for each arm, the paired wins, and the sign test against the old difference
    """
    old = column_run( control_run, ids )[ "records" ][ "engine" ]
    new = column_run( new_run, ids )[ "records" ][ "engine" ]
    out = {}
    for window, a, b in ( ( "column", old, new ), ( "final", final_records( old ), final_records( new ) ) ):
        a, b = of_type( a, "multiple_choice" ), of_type( b, "multiple_choice" )
        run  = { "records": { "control": a, "per_field": b } }
        only_new, only_old = paired_wins( run, "per_field", "control" )
        out[ window ] = { "asks": len( a ), "control_correct": sum( r[ "meta" ][ "correct" ] for r in a ), "per_field_correct": sum( r[ "meta" ][ "correct" ] for r in b ),
                          "only_per_field_right": only_new, "only_control_right": only_old, "difference": only_new - only_old }
    out[ "old_difference" ] = OLD_DIFFERENCES[ "phase7 per_field against control, multiple choice, final window" ]
    out[ "sign_test" ]      = reversal( out[ "old_difference" ], out[ "final" ][ "difference" ] )
    return out


def phase8_column( new_run, ids, asks_by_id ):
    """
    Compare margin rule, three-way and always-yes on one column's yes/no asks.

    Requires:
        - new_run holds the arms engine, always_yes and three_way over the same asks; asks_by_id maps id to its ask

    Ensures:
        - the final window is the freeze's, cut over every type before the yes/no asks are kept, as the old report cut it
        - returns the three_way_report on that window, the whole-column yes/no count, the paired wins and the sign tests
    """
    from cosa.research.preference_replay import three_way_report
    whole = column_run( new_run, ids )
    final = { "records": { arm: of_type( final_records( records ), "yes_no" ) for arm, records in whole[ "records" ].items() },
              "not_replayable": whole[ "not_replayable" ], "unrebuildable_cases": whole[ "unrebuildable_cases" ], "families": whole[ "families" ] }
    kept   = [ r[ "meta" ][ "notification_id" ] for r in final[ "records" ][ "engine" ] ]
    report = three_way_report.build_report( final, [ asks_by_id[ i ] for i in kept ], OPERATIONAL_FLOOR )
    vs_yes_a, vs_yes_b = paired_wins( final, "three_way", "always_yes" )
    vs_mar_a, vs_mar_b = paired_wins( final, "three_way", "engine" )
    right = { arm: sum( r[ "meta" ][ "correct" ] for r in records ) for arm, records in final[ "records" ].items() }
    return { "asks": len( of_type( whole[ "records" ][ "engine" ], "yes_no" ) ), "final_asks": len( kept ), "final_correct": right, "report": report,
             "three_way_against_always_yes": { "only_three_way": vs_yes_a, "only_always_yes": vs_yes_b, "difference": vs_yes_a - vs_yes_b,
                                               "sign_test": reversal( OLD_DIFFERENCES[ "phase8 three_way against always_yes, yes/no, final window" ], vs_yes_a - vs_yes_b ) },
             "three_way_against_margin_rule": { "only_three_way": vs_mar_a, "only_margin_rule": vs_mar_b, "difference": vs_mar_a - vs_mar_b,
                                                "sign_test": reversal( OLD_DIFFERENCES[ "phase8 three_way against margin rule, yes/no, final window" ], vs_mar_a - vs_mar_b ) } }


def phase9_column( new_run, ids, fit_time, label ):
    """
    Fit calibration on a tune window and score it on a disjoint final window.

    Requires:
        - new_run holds the engine arm; ids is the column's id set; label names the column

    Ensures:
        - returns the tune and final id lists with their sizes and shas, whether they share an id, and fit_and_evaluate's report
        - every figure belongs to the tune or the final window of the report, and the lists share no id
    """
    from cosa.research.preference_replay.calibration_fit import fit_and_evaluate
    records = column_run( new_run, ids )[ "records" ][ "engine" ]
    tune, final = split_by_time( records )
    rows  = lambda part: [ ( r[ "meta" ][ "response_type" ], r[ "meta" ][ "strategy" ], r[ "meta" ][ "confidence" ], r[ "meta" ][ "correct" ] ) for r in part
                           if r[ "meta" ][ "strategy" ] is not None and r[ "meta" ][ "confidence" ] is not None and r[ "meta" ][ "forecast" ] is not None ]
    tune_ids  = [ r[ "meta" ][ "notification_id" ] for r in tune ]
    final_ids = [ r[ "meta" ][ "notification_id" ] for r in final ]
    document, report = fit_and_evaluate( rows( tune ), rows( final ), sha256_of_ids( tune_ids ), fit_time )
    return { "column": label, "tune_size": len( tune_ids ), "final_size": len( final_ids ), "tune_ids_sha256": sha256_of_ids( tune_ids ),
             "final_ids_sha256": sha256_of_ids( final_ids ), "shared_ids": len( set( tune_ids ) & set( final_ids ) ),
             "tune_ids": tune_ids, "final_ids": final_ids, "report": report, "fitted_cells": sorted( document[ "cells" ] ) }


def phase11_column( plain_run, visible_run, plain_reasons, visible_reasons, ids ):
    """
    Count abstention reasons for one column with failure visibility off and on.

    Requires:
        - the two runs and their reason lists cover the same asks in the same order

    Ensures:
        - returns the count of each reason in each setting and whether the per-ask reasons are identical
    """
    def counted( run, reasons ):
        recs = run[ "records" ][ "engine" ]
        return collections.Counter( str( reason ) for rec, reason in zip( recs, reasons, strict=True ) if rec[ "meta" ][ "notification_id" ] in ids )
    off, on = counted( plain_run, plain_reasons ), counted( visible_run, visible_reasons )
    return { "reasons_off": dict( off ), "reasons_on": dict( on ), "identical_per_ask": plain_reasons == visible_reasons }


def main( argv=None ):
    """
    Run the control, then every comparison, with every model entry point raising.

    Requires:
        - argv holds --vectors, --records and --out-dir; --cohort and --old-ids default to the committed files
        - the database named by the configuration is reachable and is read in a read-only transaction

    Ensures:
        - the control (switches as the old record had them, the old 1,302 asks) must reproduce 177, 163 and 14 of 176, or nothing is written and 2 is returned
        - otherwise writes one per-ask file per arm and one report, each stamped with its sha, and returns 0
        - returns 1, after writing, when any model call was attempted or the positive control did not fire
    """
    parser = argparse.ArgumentParser( description="Re-run phases 7, 8, 9 and 11 from stored vectors." )
    parser.add_argument( "--vectors", required=True )
    parser.add_argument( "--records", required=True, help="run 2's records.jsonl: the 1,926 cards of record" )
    parser.add_argument( "--out-dir", required=True )
    parser.add_argument( "--cache", default=None, help="a pickle of the replays: read when it exists, written after the control passes" )
    parser.add_argument( "--cohort", default=None, help="the 18 Nov checkpoint cohort; default src/conf/prediction-checkpoint-cohort.jsonl" )
    parser.add_argument( "--old-ids", default=None, help="the old replayable ids; default src/conf/prediction-before-replayable-ids.txt" )
    args  = parser.parse_args( argv )
    calls = collections.Counter()
    zmp.install_guards( calls )
    import cosa.utils.util as cu
    from datetime import datetime, timezone
    from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
    from cosa.research.preference_replay import three_way_report
    from cosa.research.preference_replay.question_vectors import load_side_file
    from cosa.research.preference_replay.retune_run import read_cohort
    from cosa.rest.db.database import get_db
    root   = cu.get_project_root()
    cohort = args.cohort or root + "/src/conf/prediction-checkpoint-cohort.jsonl"
    old    = args.old_ids or root + "/src/conf/prediction-before-replayable-ids.txt"
    header, vectors = load_side_file( args.vectors )
    with get_db() as session: asks, facts = read_cohort( session, vectors )
    by_id      = { ask[ "id" ]: ask for ask in asks }
    record_ids = read_ids( args.records )
    columns    = columns_of( record_ids, read_ids( cohort ), read_ids( old ), [ a[ "id" ] for a in asks if a[ "question_embedding" ] is not None ] )
    outside    = len( set( record_ids ) - set( columns[ "record" ] ) )
    PredictionEngine.reset()
    engine  = PredictionEngine( debug=False )
    # A bare engine reads no INI, so it runs on code defaults; the frozen retrieval settings are set here, as the retune sets them.
    engine.similarity_threshold, engine.cbr_top_k, engine.retrieval_metric = FROZEN[ "threshold" ], FROZEN[ "top_k" ], FROZEN[ "metric" ]
    arm     = three_way_report.make_three_way_arm( engine.recency_half_life_days )
    pool    = { name: [ a for a in asks if a[ "id" ] in ids ] for name, ids in columns.items() }
    control = replay_config( pool[ "old_1302" ], engine, False, False, {}, "control" )
    counts  = window_counts( control[ "run" ][ "records" ][ "engine" ] )
    wrong   = control_mismatches( counts )
    print( "control", counts )
    if wrong:
        print( "CONTROL MISMATCH, nothing written:", wrong )
        return 2
    if args.cache is not None and os.path.exists( args.cache ):
        with open( args.cache, "rb" ) as handle: runs = pickle.load( handle )
    else:
        runs = { name: { "old": replay_config( pool[ name ], engine, False, False, {}, "old-switches" ),
                         "new": replay_config( pool[ name ], engine, True, False, { "three_way": arm }, "new-switches" ),
                         "vis": replay_config( pool[ name ], engine, True, True, {}, "failure-visibility-on" ) } for name in columns }
        if args.cache is not None:
            with open( args.cache, "wb" ) as handle: pickle.dump( runs, handle )
    print( "replayed", { name: len( pool[ name ] ) for name in columns }, "record ids outside every column", outside )
    os.makedirs( args.out_dir, exist_ok=True )
    switches = read_switches( root + "/src/conf/lupin-app.ini" )
    stamps   = { "code_sha": code_sha( root ), "command": "python src/scripts/rerun_phases_7_to_11.py " + " ".join( argv if argv is not None else sys.argv[ 1: ] ),
                 "frozen": { "metric": engine.retrieval_metric, "threshold": engine.similarity_threshold, "top_k": engine.cbr_top_k },
                 "checkpoint_cohort_sha256": sha256_of( cohort ),
                 "columns": { name: { "count": len( ids ), "sha256_of_sorted_ids": sha256_of_ids( ids ) } for name, ids in columns.items() },
                 "record_ids_outside_every_column": outside, "vector_file_sha256": sha256_of( args.vectors ), "database": facts[ "database" ],
                 "case_pool": "each column is replayed against only its own asks as cases, as the freeze's control was",
                 "switches_in_ini_not_read_by_the_replay": switches,
                 "engine_attributes_in_effect": { name: getattr( engine, name ) for name in ( "yes_no_no_margin", "confidence_threshold", "three_way_enabled", "lookup_neither_forecast_enabled",
                                                                                              "calibration_enabled", "similarity_threshold", "cbr_top_k", "retrieval_metric" ) },
                 "engine_config": "a bare engine reads no INI, so every switch below is a code default unless the replay sets it","switches_run_with": { "per_field_multiple_choice": "off for control arms, on for new arms", "complete_action_scoring": "off",
                                                                  "lookup_neither_forecast": "off", "full_answer_reply": "not read by the replay path", "failure_visibility": "off, on in phase 11 only" } }

    def arm_records( kind, arm_name, reasons=False ):
        return { name: ( with_reasons( runs[ name ][ kind ][ "run" ][ "records" ][ arm_name ], runs[ name ][ kind ][ "reasons" ] ) if reasons
                         else runs[ name ][ kind ][ "run" ][ "records" ][ arm_name ] ) for name in columns }

    files = {}
    for name, records in ( ( "phase7-control", arm_records( "old", "engine" ) ), ( "phase7-per-field", arm_records( "new", "engine" ) ),
                           ( "phase8-margin-rule", arm_records( "new", "engine" ) ), ( "phase8-three-way", arm_records( "new", "three_way" ) ),
                           ( "phase8-always-yes", arm_records( "new", "always_yes" ) ), ( "phase9-engine-confidence", arm_records( "new", "engine" ) ),
                           ( "phase11-failure-visibility-off", arm_records( "new", "engine", True ) ), ( "phase11-failure-visibility-on", arm_records( "vis", "engine", True ) ) ):
        path = f"{args.out_dir}/prediction-rerun-{name}-per-ask.json"
        files[ path ] = write_json( path, per_ask_document( name, records, stamps ) )
    fit_time = datetime.now( timezone.utc ).isoformat()
    report   = { "stamps": stamps, "control": counts, "phase7": {}, "phase8": {}, "phase9": {}, "phase11": {}, "phase10": "not run: nothing was built or measured; plan section 2" }
    note11   = "identical by construction: failure visibility acts when a forecast is recorded, and a replay records none; this is a count of reasons, not a measured null"
    for label in columns:
        ids = columns[ label ]
        report[ "phase7" ][ label ]  = phase7_column( runs[ label ][ "old" ][ "run" ], runs[ label ][ "new" ][ "run" ], ids )
        report[ "phase8" ][ label ]  = phase8_column( runs[ label ][ "new" ][ "run" ], ids, by_id )
        report[ "phase9" ][ label ]  = phase9_column( runs[ label ][ "new" ][ "run" ], ids, fit_time, label )
        report[ "phase11" ][ label ] = dict( phase11_column( runs[ label ][ "new" ][ "run" ], runs[ label ][ "vis" ][ "run" ], runs[ label ][ "new" ][ "reasons" ],
                                                             runs[ label ][ "vis" ][ "reasons" ], ids ), label=note11 )
    attempts = sum( calls.values() )
    report[ "model_call_attempts" ] = attempts
    report[ "per_ask_files" ]       = files
    path = f"{args.out_dir}/prediction-rerun-phases-7-to-11-report.json"
    print( "report", path, write_json( path, report ) )
    print( "model-call attempts:", dict( calls ) or 0 )
    from cosa.agents.prediction_engine.prediction_engine import PredictionEngine as Engine
    fired = False
    try: Engine._get_llm_client( engine )
    except AssertionError as error:
        fired = True
        print( "positive control fired:", error )
    return 0 if attempts == 0 and fired else 1


if __name__ == "__main__":
    sys.exit( main() )
