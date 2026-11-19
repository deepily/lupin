"""
Replay the live prediction engine over past asks, in the order they were asked.

Each ask is predicted from what was knowable when it was asked, and only then does its answer
become knowable to later asks. The forecasts come from the real ``PredictionEngine.predict()``;
the engine reads past cases through a time-sliced store this module loads for each ask.

Two rules keep the answer out of its own forecast:

- A case reaches the store with the answer and the ratification state it had at the ask, never the
  final ones. A case whose value at the ask cannot be rebuilt is left out and counted.
- The target's own retry group is left out of its neighbours, so a retry copy cannot lead.
"""

import copy

from cosa.agents.prediction_engine.accuracy_comparators import get_comparator
from cosa.agents.prediction_engine.ask_family import classify_asks
from cosa.agents.prediction_engine.config import RESPONSE_TYPE_MULTIPLE_CHOICE, RESPONSE_TYPE_OPEN_ENDED_BATCH
from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
from cosa.agents.prediction_engine.prediction_result import PredictionResult
from cosa.utils.iso_timestamp import aware_moment
from cosa.utils.notification_utils import extract_qualifier_comment
from cosa.research.phi4_flash_lite_study.statistics import (
    DiscordantFloorNotMet,
    assert_floor_pre_stated,
    mcnemar_exact,
    wilson_interval,
)
from cosa.research.preference_replay.time_sliced_store import RECORD_FIELDS, TimeSlicedDecisionStore

ENGINE_ARM = "engine"

# The only fields of an ask known when it was asked. A field not listed here, such as the answer, the
# ratification state, the answer source or the old log's prediction, never reaches a provider or an arm.
ASK_KNOWN_FIELDS = ( "id", "question", "category", "response_type", "question_embedding", "title", "message", "sender_id",
                     "asked_at", "recipient_id", "response_options", "owner_user_id", "data_origin" )


def rows_as_of( cases, asked_at, excluded_ids=() ):
    """
    Build the store rows for one ask, each case as it stood at that moment.

    Requires:
        - cases is a list of dicts holding every store record field plus responded_at
        - a case may carry versions, a list of { at, answer, ratification_state }
        - asked_at is an aware datetime or an ISO-8601 string
        - excluded_ids are the case ids to leave out, the target's own retry group

    Ensures:
        - returns ( rows, unrebuildable_ids ); rows keep the order of cases
        - a case with no versions key passes through unchanged
        - a case with versions reads its decision_value and ratification_state from the latest
          version at or before the ask, never from the final row
        - a case answered at or before the ask whose versions list is empty, or starts after the ask,
          is left out of rows and named in unrebuildable_ids
        - a case answered after the ask is left to the store, which hides it
        - an excluded case is in neither list
    """
    asked_at  = aware_moment( asked_at )
    excluded  = set( excluded_ids )
    rows      = []
    lost      = []
    for case in cases:
        if case[ "id" ] in excluded: continue
        row = dict( case )
        if row[ "responded_at" ] is not None: row[ "responded_at" ] = aware_moment( row[ "responded_at" ] )
        if "versions" in case:
            answered = case[ "responded_at" ] is not None and aware_moment( case[ "responded_at" ] ) <= asked_at
            known    = [ v for v in case[ "versions" ] if aware_moment( v[ "at" ] ) <= asked_at ]
            if known:
                latest = max( known, key=lambda v: aware_moment( v[ "at" ] ) )
                row[ "decision_value" ]     = latest[ "answer" ]
                row[ "ratification_state" ] = latest[ "ratification_state" ]
            elif answered:
                lost.append( case[ "id" ] )
                continue
        row.pop( "versions", None )
        rows.append( row )
    return rows, lost


def predicted_value_for( result ):
    """
    Wrap a forecast the way the engine wraps one before comparing it with an answer.

    Requires:
        - result is a PredictionResult

    Ensures:
        - returns the dict the comparators read, or None when there is no forecast
    """
    return result._wrap_predicted_value()


def _actual_dict( actual_value, response_type=None ):
    """
    Wrap an answer the way the engine does before comparing.

    Requires:
        - actual_value is a string, a dict or any value with a string form

    Ensures:
        - returns a dict; a bare value is stored under "value"
        - for a multiple-choice or batch ask, a JSON string holding answers is decoded, as the engine does
    """
    actual = actual_value if isinstance( actual_value, dict ) else { "value": actual_value if isinstance( actual_value, str ) else str( actual_value ) }
    if response_type in ( RESPONSE_TYPE_MULTIPLE_CHOICE, RESPONSE_TYPE_OPEN_ENDED_BATCH ) and isinstance( actual.get( "value" ), str ):
        decoded = PredictionEngine._parse_mc_decision_value( actual[ "value" ] )
        if decoded is not None: return decoded
    return actual


def _score( response_type, predicted, actual_value, response_options ):
    """
    Say whether a forecast matched the answer, scored as the engine scores it.

    Requires:
        - predicted is the dict predicted_value_for returns, or None

    Ensures:
        - returns True only when the comparator says match; no forecast and an unscored answer read False,
          so an abstention is charged as a miss
    """
    match, _ = get_comparator( response_type, response_options=response_options )( predicted, _actual_dict( actual_value, response_type ) )
    return match is True


def always_yes_arm( row, visible_rows ):
    """
    Forecast yes for a yes/no ask, whatever came before.

    Requires:
        - row is an ask dict

    Ensures:
        - returns { "value": "yes" } for a yes/no ask and None for any other type
    """
    return { "value": "yes" } if row[ "response_type" ] == "yes_no" else None


def prior_majority_arm( row, visible_rows ):
    """
    Forecast the stance most often given before, among visible yes/no cases.

    Requires:
        - visible_rows are the store rows as of the ask, in load order

    Ensures:
        - returns { "value": stance } for the most frequent earlier stance; ties go to the stance seen first
        - returns None for a card that is not yes/no, or when no earlier case with a stance is visible
    """
    if row[ "response_type" ] != "yes_no": return None
    counts = {}
    for case in visible_rows:
        if case[ "response_type" ] != "yes_no" or case[ "category" ] != row[ "category" ]: continue
        stance, _ = extract_qualifier_comment( case[ "decision_value" ] )
        if stance: counts[ stance ] = counts.get( stance, 0 ) + 1
    if not counts: return None
    best = max( counts.values() )
    return { "value": next( answer for answer, count in counts.items() if count == best ) }


BASELINE_ARMS = { "always_yes": always_yes_arm, "prior_majority": prior_majority_arm }


def replay( asks, engine, snapshot_sha256, baselines=None, store_factory=TimeSlicedDecisionStore, target_types=None,
            context_arms=(), episode_view_provider=None, principles_provider=None ):
    """
    Predict every replayable ask in time order with the live engine, and with each baseline.

    Requires:
        - asks is a list of dicts with the store record fields, responded_at and these ask fields:
          title, message, sender_id, asked_at, recipient_id, response_options, actual_value
        - an ask with no question_embedding is not replayable
        - engine is a PredictionEngine; its embedding store is replaced for the run
        - baselines is a dict of arm name to function( ask, visible_rows ), default BASELINE_ARMS
        - target_types is None to predict every ask, or the response types to predict; the other asks still
          serve as cases and are neither predicted nor counted
        - context_arms names the baselines that receive context; each name is a key of baselines. The default,
          an empty tuple, leaves every baseline called as arm( ask, visible_rows ), exactly as before
        - episode_view_provider is None or a function( ask_at_ask, visible_rows ); principles_provider is None
          or a function( ask_at_ask, asked_at ). Neither is called unless context_arms is not empty
        - the real episode_view and principle store are never imported here; the caller passes them in

    Ensures:
        - the forecast of an ask is made by engine.predict() with the ask's stored vector, so no embedding
          service is called
        - each ask is predicted from the cases answered at or before its ask time, as they stood then,
          without its own retry group
        - returns { records, not_replayable, unrebuildable_cases, families } where records maps each arm to
          one record per replayable ask, in the same order, with arm, row_index, frozen_index, body,
          snapshot_sha256 and meta; meta["correct"] is a bool
        - not_replayable counts the asks with no vector and not_replayable_ids names them, in ask order;
          meta carries notification_id, the ask's id; unrebuildable_cases counts the distinct cases
          left out for want of a rebuildable value, however many asks they were left out of
        - families is the number of distinct families among the replayed asks
        - the engine's embedding store is put back as it was
        - a context arm is called as arm( ask_at_ask, visible_rows, episode_view=..., principles=... ), where
          each value is the provider's answer for this ask, or None when that provider was not passed
        - ask_at_ask is the ask cut to its ASK_KNOWN_FIELDS, so a provider and a context arm are
          never handed the answer to the ask they are forecasting; both are deep copies, so a change by
          an arm reaches neither the replay nor the next arm; visible_rows are only cases answered at
          or before the ask, as they stood then; the providers are called once per replayed ask, in ask order

    Raises:
        - ValueError if context_arms names an arm that is not in baselines
    """
    baselines = BASELINE_ARMS if baselines is None else baselines
    unknown   = [ name for name in context_arms if name not in baselines ]
    if unknown: raise ValueError( f"context_arms {unknown} are not in baselines {sorted( baselines )}" )
    classes   = classify_asks( asks )
    groups    = {}
    for index, info in enumerate( classes ): groups.setdefault( info[ "retry_group" ], [] ).append( asks[ index ][ "id" ] )
    order     = sorted( range( len( asks ) ), key=lambda i: ( aware_moment( asks[ i ][ "asked_at" ] ), i ) )
    records   = { ENGINE_ARM: [] }
    records.update( { name: [] for name in baselines } )
    not_replayable = []
    unrebuildable  = set()
    families       = set()
    saved_store    = engine._embedding_store
    try:
        for index in order:
            ask = asks[ index ]
            if target_types is not None and ask[ "response_type" ] not in target_types: continue
            if ask[ "question_embedding" ] is None:
                not_replayable.append( ask[ "id" ] )
                continue
            asked_at     = aware_moment( ask[ "asked_at" ] )
            rows, lost   = rows_as_of( asks, asked_at, excluded_ids=groups[ classes[ index ][ "retry_group" ] ] )
            unrebuildable.update( lost )
            store        = store_factory( rows )
            store.advance_to( asked_at )
            engine._embedding_store = store
            result = engine.predict( _notification_dict( ask ), query_vector=ask[ "question_embedding" ] )
            families.add( classes[ index ][ "family" ] )
            visible = [ row for row in rows if row[ "responded_at" ] is not None and aware_moment( row[ "responded_at" ] ) <= asked_at ]
            forecasts = { ENGINE_ARM: _forecast_of( result ) }
            if context_arms:
                view       = None if episode_view_provider is None else episode_view_provider( _ask_at_ask( ask ), copy.deepcopy( visible ) )
                principles = None if principles_provider is None else principles_provider( _ask_at_ask( ask ), asked_at )
            for name, arm in baselines.items():
                if name in context_arms: forecasts[ name ] = arm( _ask_at_ask( ask ), copy.deepcopy( visible ), episode_view=view, principles=principles )
                else: forecasts[ name ] = arm( ask, visible )
            for arm_name, predicted in forecasts.items():
                records[ arm_name ].append( {
                    "arm"             : arm_name,
                    "row_index"       : len( records[ arm_name ] ),
                    "frozen_index"    : index,
                    "body"            : ask[ "message" ],
                    "snapshot_sha256" : snapshot_sha256,
                    "meta"            : {
                        "notification_id" : ask[ "id" ],
                        "correct"       : _score( ask[ "response_type" ], predicted, ask[ "actual_value" ], ask[ "response_options" ] ),
                        "response_type" : ask[ "response_type" ],
                        "family"        : classes[ index ][ "family" ],
                        "forecast"      : predicted,
                    },
                } )
            engine_meta = records[ ENGINE_ARM ][ -1 ][ "meta" ]
            engine_meta[ "neighbour_ids" ] = list( result.metadata.get( "evidence_ids", [] ) )
            engine_meta[ "confidence" ]    = result.confidence if isinstance( result, PredictionResult ) else None
            engine_meta[ "strategy" ]      = result.strategy if isinstance( result, PredictionResult ) else None
    finally:
        engine._embedding_store = saved_store
    return {
        "records"             : records,
        "not_replayable"      : len( not_replayable ),
        "not_replayable_ids"  : not_replayable,
        "unrebuildable_cases" : len( unrebuildable ),
        "families"            : len( families ),
    }


def _ask_at_ask( ask ):
    """
    Show an ask as it stood when it was asked, without its answer.

    Requires:
        - ask is an ask dict

    Ensures:
        - returns a new dict holding a deep copy of only the ASK_KNOWN_FIELDS the ask has; the ask is not changed,
          and a caller that changes the copy cannot change the replay's rows
    """
    return { key: copy.deepcopy( ask[ key ] ) for key in ASK_KNOWN_FIELDS if key in ask }


def _forecast_of( result ):
    """
    Read the forecast dict out of a result.

    Requires:
        - result is a PredictionResult

    Ensures:
        - returns the wrapped predicted value, or None for a cold start
    """
    return predicted_value_for( result ) if isinstance( result, PredictionResult ) else None


def _notification_dict( ask ):
    """
    Build the notification dict the engine's predict() reads, from an ask.

    Requires:
        - ask has message, response_type, sender_id, recipient_id and response_options

    Ensures:
        - returns a new dict; the ask is not changed
    """
    return {
        "message"          : ask[ "message" ],
        "response_type"    : ask[ "response_type" ],
        "sender_id"        : ask[ "sender_id" ],
        "recipient_id"     : ask[ "recipient_id" ],
        "response_options" : copy.deepcopy( ask[ "response_options" ] ),
    }


def summarize( run, baseline_arm, operational_floor, arm=ENGINE_ARM ):
    """
    Compare the engine, or another arm, with one baseline, paired on the same asks.

    Requires:
        - run is the dict replay returns, with records for arm and baseline_arm
        - arm is ENGINE_ARM, or the name of any arm in the run, so one run pairs a context arm with its comparator the way
          _paired_with_q pairs an arm with Q, with no second harness
        - operational_floor is the discordant-pair floor stated before the run

    Ensures:
        - the arm's records are read in the engine's place; the keys and the verdict words stay the engine's,
          so "engine better" means the arm is better, as it does for Q in context_arms_report
        - returns denominators, the not-replayable count, each arm's correct count with its Wilson interval,
          the discordant pairs b and c, McNemar's exact result, the floor and whether it was met, and the
          number of families
        - below the floor, verdict is "not decisive"; it is never "no effect"
        - at or above the floor, verdict is "engine better", "baseline better" or "no difference" by McNemar's p below 0.05
    """
    engine   = run[ "records" ][ arm ]
    baseline = run[ "records" ][ baseline_arm ]
    n        = len( engine )
    wins     = sum( 1 for e, b in zip( engine, baseline ) if e[ "meta" ][ "correct" ] and not b[ "meta" ][ "correct" ] )
    losses   = sum( 1 for e, b in zip( engine, baseline ) if b[ "meta" ][ "correct" ] and not e[ "meta" ][ "correct" ] )
    engine_correct   = sum( 1 for r in engine if r[ "meta" ][ "correct" ] )
    baseline_correct = sum( 1 for r in baseline if r[ "meta" ][ "correct" ] )
    test     = mcnemar_exact( wins, losses )
    try:
        assert_floor_pre_stated( wins + losses, operational_floor )
        floor_met = True
    except DiscordantFloorNotMet:
        floor_met = False
    if not floor_met:
        verdict = "not decisive"
    elif test[ "p_value" ] >= 0.05:
        verdict = "no difference"
    else:
        verdict = "engine better" if wins > losses else "baseline better"
    return {
        "arm"                 : arm,
        "baseline"            : baseline_arm,
        "asks_replayed"       : n,
        "not_replayable"      : run[ "not_replayable" ],
        "unrebuildable_cases" : run[ "unrebuildable_cases" ],
        "families"            : run[ "families" ],
        "engine_correct"      : engine_correct,
        "engine_interval"     : wilson_interval( engine_correct, n ),
        "baseline_correct"    : baseline_correct,
        "baseline_interval"   : wilson_interval( baseline_correct, n ),
        "engine_only_right"   : wins,
        "baseline_only_right" : losses,
        "mcnemar"             : test,
        "operational_floor"   : operational_floor,
        "floor_met"           : floor_met,
        "verdict"             : verdict,
    }
