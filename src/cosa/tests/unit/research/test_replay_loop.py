"""
The replay loop predicts each ask with the live engine, from what was known at the ask.

Every test runs the real PredictionEngine.predict() over small synthetic asks. The embedding service is
replaced by a function that fails, so a test that passes proves the stored vector was used. The named leak
tests plant a late answer, a later revision and a retry copy, and assert none of them reaches a forecast.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
from cosa.research.phi4_flash_lite_study.replay_harness import pair_records
from cosa.research.preference_replay import replay_loop
from cosa.research.preference_replay.replay_loop import ENGINE_ARM, replay, rows_as_of, summarize
from cosa.research.preference_replay.time_sliced_store import TimeSlicedDecisionStore
from cosa.rest.db.vector_store_models import EMBEDDING_DIM
from cosa.utils.iso_timestamp import aware_moment

SHA   = "0" * 64
NOON  = datetime( 2026, 11, 10, 12, 0, tzinfo=timezone.utc )
OWNER = "user-1"
SENDER = "claude.code@lupin.deepily.ai#00000001"


def _vector( axis ):
    """A vector on one basis axis, long enough to sit inside the stored-vector band."""
    vector = [ 0.0 ] * EMBEDDING_DIM
    vector[ axis ] = 20.0
    return vector


@pytest.fixture
def engine():
    """The real engine, with embedding generation made to fail so a stored vector must be used."""
    PredictionEngine.reset()
    eng = PredictionEngine( debug=False )
    eng._generate_embedding = lambda text: pytest.fail( "the replay embedded a message" )
    yield eng
    PredictionEngine.reset()


def _ask( engine, ask_id, axis, minutes, answer, message=None, title=None, **extra ):
    """One answered yes/no ask `minutes` after noon, asked and answered a minute apart."""
    message  = message or f"Should the synthetic worker {ask_id} proceed?"
    category, _ = engine.classifier.classify( message, sender_id=SENDER )
    asked    = NOON + timedelta( minutes=minutes )
    ask = {
        "id": ask_id, "question": message, "category": category, "decision_value": answer, "ratification_state": "not_required",
        "data_origin": "organic", "response_type": "yes_no", "question_embedding": _vector( axis ), "created_at": "2026-11-10",
        "owner_user_id": OWNER, "answer_source": "human", "responded_at": asked + timedelta( minutes=1 ),
        "title": title if title is not None else f"Worker {ask_id}", "message": message, "sender_id": SENDER, "asked_at": asked,
        "recipient_id": OWNER, "response_options": None, "actual_value": answer,
    }
    ask.update( extra )
    return ask


def _neighbours( run, ask_id, asks ):
    """The neighbour ids the engine used for one ask."""
    index = [ a[ "id" ] for a in asks ].index( ask_id )
    record = next( r for r in run[ "records" ][ ENGINE_ARM ] if r[ "frozen_index" ] == index )
    return record[ "meta" ][ "neighbour_ids" ]


def test_predict_is_the_production_method_and_the_stored_vector_is_used( engine ):
    """The engine under replay is the live class, fed the stored vector, then restored."""
    original = engine._embedding_store
    asks     = [ _ask( engine, "a", 1, 0, "yes" ), _ask( engine, "b", 1, 10, "yes" ) ]
    run      = replay( asks, engine, SHA )
    assert type( engine ).predict is PredictionEngine.predict
    assert engine._embedding_store is original
    assert len( run[ "records" ][ ENGINE_ARM ] ) == 2


def test_the_store_is_put_back_when_a_forecast_raises( engine ):
    """A failure mid-run does not leave the replay's store on the engine."""
    original = engine._embedding_store
    engine.predict = lambda notification, query_vector=None: (_ for _ in ()).throw( RuntimeError( "boom" ) )
    with pytest.raises( RuntimeError ):
        replay( [ _ask( engine, "a", 1, 0, "yes" ) ], engine, SHA )
    assert engine._embedding_store is original


def test_named_leak_a_late_answer_is_absent_from_the_neighbours( engine ):
    """A perfect match answered after the ask never reaches the forecast; an earlier one does."""
    asks = [ _ask( engine, "early", 3, 0, "yes" ), _ask( engine, "target", 3, 30, "no" ),
             _ask( engine, "late", 3, 60, "no" ) ]
    run = replay( asks, engine, SHA )
    assert _neighbours( run, "target", asks ) == [ "early" ]
    assert "target" not in _neighbours( run, "target", asks ), "the target's own answer reached its forecast"
    assert sorted( _neighbours( run, "late", asks ) ) == [ "early", "target" ], "control: later asks do see earlier answers"


def test_the_targets_own_retry_group_is_left_out_of_its_neighbours( engine ):
    """A retry copy answered before the target is not independent evidence."""
    message = "Restart the synthetic worker now?"
    asks = [ _ask( engine, "sibling", 4, -600, "yes", message=message, title="Restart worker 3?" ),
             _ask( engine, "copy", 4, 28, "yes", message=message, title="Restart worker 99?" ),
             _ask( engine, "target", 4, 30, "no", message=message, title="Restart worker 17?" ) ]
    run = replay( asks, engine, SHA )
    assert _neighbours( run, "target", asks ) == [ "sibling" ]
    assert set( _neighbours( run, "copy", asks ) ) == { "sibling" }, "a retry copy is its own group's first ask and sees only the sibling"


def test_the_value_a_case_had_at_the_ask_is_what_the_store_gets():
    """A revision after the ask does not rewrite the case the forecast sees."""
    case = { "id": "c", "responded_at": NOON, "decision_value": "no", "ratification_state": "rejected",
             "versions": [ { "at": NOON, "answer": "yes", "ratification_state": "not_required" },
                           { "at": NOON + timedelta( minutes=80 ), "answer": "no", "ratification_state": "rejected" } ] }
    rows, lost = rows_as_of( [ case ], NOON + timedelta( minutes=30 ) )
    assert lost == []
    assert ( rows[ 0 ][ "decision_value" ], rows[ 0 ][ "ratification_state" ] ) == ( "yes", "not_required" )
    assert "versions" not in rows[ 0 ]
    later, _ = rows_as_of( [ case ], NOON + timedelta( minutes=90 ) )
    assert ( later[ 0 ][ "decision_value" ], later[ 0 ][ "ratification_state" ] ) == ( "no", "rejected" ), "control: after the revision the new value shows"


def test_a_version_at_the_ask_instant_counts_and_one_just_after_does_not():
    """The rule is at or before the ask, on both the answer time and the version time."""
    at_ask = { "id": "c", "responded_at": NOON, "decision_value": "later", "ratification_state": "x",
               "versions": [ { "at": NOON, "answer": "yes", "ratification_state": "not_required" } ] }
    rows, lost = rows_as_of( [ at_ask ], NOON )
    assert lost == [] and rows[ 0 ][ "decision_value" ] == "yes"
    after = dict( at_ask, versions=[ { "at": NOON + timedelta( microseconds=1 ), "answer": "yes", "ratification_state": "not_required" } ] )
    rows, lost = rows_as_of( [ after ], NOON )
    assert rows == [] and lost == [ "c" ], "a case answered at the ask whose only version is later cannot be rebuilt"
    unanswered = dict( after, responded_at=NOON + timedelta( microseconds=1 ) )
    rows, lost = rows_as_of( [ unanswered ], NOON )
    assert lost == [] and len( rows ) == 1, "control: answered after the ask is left to the store, not counted lost"


def test_a_case_answered_exactly_at_the_ask_is_visible_and_one_microsecond_later_is_not( engine ):
    """The visibility edge: responded_at equal to asked_at counts."""
    for offset, expected in ( ( timedelta( 0 ), [ "other" ] ), ( timedelta( microseconds=1 ), [] ) ):
        other  = _ask( engine, "other", 5, 0, "yes" )
        target = _ask( engine, "target", 5, 10, "no" )
        other[ "responded_at" ] = target[ "asked_at" ] + offset
        asks = [ other, target ]
        run  = replay( asks, engine, SHA )
        assert _neighbours( run, "target", asks ) == expected, offset


def test_a_baseline_sees_a_case_answered_at_the_ask_instant_and_not_one_a_microsecond_later( engine ):
    """The baselines read the same at-or-before edge as the store."""
    for offset, expected in ( ( timedelta( 0 ), { "value": "no" } ), ( timedelta( microseconds=1 ), None ) ):
        other  = _ask( engine, "other", 5, 0, "no" )
        target = _ask( engine, "target", 5, 10, "yes" )
        other[ "responded_at" ] = target[ "asked_at" ] + offset
        run = replay( [ other, target ], engine, SHA )
        assert run[ "records" ][ "prior_majority" ][ 1 ][ "meta" ][ "forecast" ] == expected, offset


def test_the_engine_record_carries_the_forecasts_confidence_and_strategy( engine ):
    """Only the engine arm carries confidence and strategy; a cold start reads 0.0."""
    run = replay( [ _ask( engine, "a", 8, 0, "yes" ), _ask( engine, "b", 8, 10, "yes" ) ], engine, SHA )
    first, second = [ r[ "meta" ] for r in run[ "records" ][ ENGINE_ARM ] ]
    assert ( first[ "confidence" ], first[ "strategy" ] ) == ( 0.0, first[ "strategy" ] ) and isinstance( first[ "strategy" ], str )
    assert second[ "confidence" ] > 0.0 and isinstance( second[ "strategy" ], str )
    assert "confidence" not in run[ "records" ][ "always_yes" ][ 0 ][ "meta" ]


def test_records_follow_ask_order_whatever_order_the_asks_arrive_in( engine ):
    """Asks given out of order are replayed by asked_at; a tie keeps the input order."""
    late, early = _ask( engine, "late", 6, 20, "yes" ), _ask( engine, "early", 6, 0, "yes" )
    tie_a, tie_b = _ask( engine, "tie-a", 7, 40, "yes" ), _ask( engine, "tie-b", 7, 40, "yes", message="Should another synthetic worker go?" )
    run = replay( [ late, early, tie_b, tie_a ], engine, SHA )
    records = run[ "records" ][ ENGINE_ARM ]
    assert [ r[ "meta" ][ "notification_id" ] for r in records ] == [ "early", "late", "tie-b", "tie-a" ]
    assert [ r[ "frozen_index" ] for r in records ] == [ 1, 0, 2, 3 ]
    assert [ r[ "row_index" ] for r in records ] == [ 0, 1, 2, 3 ]


def test_a_case_with_no_versions_key_passes_through_unchanged():
    """Only a case that carries a history is rebuilt."""
    case = { "id": "plain", "responded_at": NOON, "decision_value": "yes", "ratification_state": "not_required" }
    rows, lost = rows_as_of( [ case ], NOON + timedelta( hours=1 ) )
    assert rows == [ case ] and lost == []


def test_an_answered_case_with_no_rebuildable_value_is_excluded_and_counted():
    """A case with no usable history at the ask is excluded, never filled from a later value."""
    empty  = { "id": "empty", "responded_at": NOON, "decision_value": "no", "ratification_state": "rejected", "versions": [] }
    starts = { "id": "starts", "responded_at": NOON, "decision_value": "no", "ratification_state": "rejected",
               "versions": [ { "at": NOON + timedelta( hours=2 ), "answer": "no", "ratification_state": "rejected" } ] }
    unanswered_yet = { "id": "later", "responded_at": NOON + timedelta( hours=3 ), "decision_value": "no", "ratification_state": "x", "versions": [] }
    rows, lost = rows_as_of( [ empty, starts, unanswered_yet ], NOON + timedelta( hours=1 ) )
    assert lost == [ "empty", "starts" ]
    assert [ r[ "id" ] for r in rows ] == [ "later" ], "a case answered after the ask is left to the store, not counted"


def test_excluded_ids_are_in_neither_list():
    """The target's retry group leaves quietly."""
    case = { "id": "copy", "responded_at": NOON, "decision_value": "no", "ratification_state": "x", "versions": [] }
    assert rows_as_of( [ case ], NOON + timedelta( hours=1 ), excluded_ids=[ "copy" ] ) == ( [], [] )


def test_times_given_as_text_are_read_as_utc():
    """An ISO string with no offset is UTC."""
    case = { "id": "t", "responded_at": "2026-11-10T12:00:00", "decision_value": "yes", "ratification_state": "x" }
    rows, _ = rows_as_of( [ case ], "2026-11-10T12:00:00" )
    assert rows[ 0 ][ "responded_at" ] == NOON


def test_unrebuildable_cases_are_counted_once_each_across_the_run( engine ):
    """The counter names distinct cases, not case-and-ask pairs."""
    asks = [ _ask( engine, "gone", 5, 0, "yes", versions=[] ), _ask( engine, "t1", 5, 30, "yes" ), _ask( engine, "t2", 5, 60, "yes" ) ]
    run  = replay( asks, engine, SHA )
    assert run[ "unrebuildable_cases" ] == 1
    assert "gone" not in _neighbours( run, "t1", asks )


def test_an_ask_with_no_stored_vector_is_counted_as_not_replayable( engine ):
    """The replay calls no embedding service for a vectorless ask."""
    asks = [ _ask( engine, "novec", 6, 0, "yes", question_embedding=None ), _ask( engine, "ok", 6, 10, "yes" ) ]
    run  = replay( asks, engine, SHA )
    assert run[ "not_replayable" ] == 1 and run[ "not_replayable_ids" ] == [ "novec" ]
    assert [ r[ "meta" ][ "notification_id" ] for r in run[ "records" ][ ENGINE_ARM ] ] == [ "ok" ]
    assert [ r[ "frozen_index" ] for r in run[ "records" ][ ENGINE_ARM ] ] == [ 1 ]


def test_every_arm_has_one_record_per_ask_in_the_same_order_and_pairs( engine ):
    """The records have the shape pair_records needs, so the arms can be paired."""
    asks = [ _ask( engine, f"a{i}", 7, i * 10, "yes" if i % 2 == 0 else "no" ) for i in range( 6 ) ]
    run  = replay( asks, engine, SHA )
    for arm, records in run[ "records" ].items():
        assert [ r[ "frozen_index" ] for r in records ] == [ 0, 1, 2, 3, 4, 5 ], arm
        assert all( set( r ) == { "arm", "row_index", "frozen_index", "body", "snapshot_sha256", "meta" } for r in records ), arm
        assert all( isinstance( r[ "meta" ][ "correct" ], bool ) for r in records ), arm
    paired = pair_records( run[ "records" ][ ENGINE_ARM ], run[ "records" ][ "always_yes" ] )
    assert len( paired ) == 6 and paired[ 0 ][ ENGINE_ARM ][ "arm" ] == ENGINE_ARM


def test_correct_is_scored_as_the_engine_scores_and_an_abstention_is_a_miss( engine ):
    """The first ask has no history, so the engine abstains and is charged a miss."""
    asks = [ _ask( engine, "first", 8, 0, "yes" ), _ask( engine, "second", 8, 10, "yes" ) ]
    run  = replay( asks, engine, SHA )
    first, second = run[ "records" ][ ENGINE_ARM ]
    assert first[ "meta" ][ "correct" ] is False and first[ "meta" ][ "forecast" ] is None
    assert second[ "meta" ][ "correct" ] is True
    assert run[ "records" ][ "always_yes" ][ 0 ][ "meta" ][ "correct" ] is True


def test_the_baselines_forecast_from_what_was_visible( engine ):
    """Always yes says yes; the prior majority follows visible stances and skips other cards."""
    asks = [ _ask( engine, "a", 9, 0, "no" ), _ask( engine, "b", 9, 10, "no" ), _ask( engine, "c", 9, 20, "yes" ), _ask( engine, "d", 9, 30, "yes" ) ]
    run  = replay( asks, engine, SHA )
    majority = [ r[ "meta" ][ "forecast" ] for r in run[ "records" ][ "prior_majority" ] ]
    assert majority == [ None, { "value": "no" }, { "value": "no" }, { "value": "no" } ]
    visible = [ { "response_type": "yes_no", "category": "k", "decision_value": v } for v in ( "yes", "no", "no [comment: x]", "maybe" ) ]
    visible += [ { "response_type": "open_ended", "category": "k", "decision_value": "yes" } ] * 3 + [ { "response_type": "yes_no", "category": "other", "decision_value": "yes" } ] * 3
    assert replay_loop.prior_majority_arm( { "response_type": "yes_no", "category": "k" }, visible ) == { "value": "no" }
    assert replay_loop.prior_majority_arm( { "response_type": "open_ended", "category": "k" }, visible ) is None
    assert replay_loop.always_yes_arm( { "response_type": "open_ended" }, [] ) is None
    assert replay_loop.always_yes_arm( { "response_type": "yes_no" }, [] ) == { "value": "yes" }


def test_a_baseline_can_be_supplied_and_replaces_the_defaults( engine ):
    """The caller names the baseline arms."""
    run = replay( [ _ask( engine, "a", 1, 0, "yes" ) ], engine, SHA, baselines={ "always_no": lambda ask, visible: { "value": "no" } } )
    assert sorted( run[ "records" ] ) == [ "always_no", ENGINE_ARM ]


def test_an_answer_that_is_not_text_or_a_dict_is_scored_by_its_string_form( engine ):
    """A bare value is wrapped the way the engine wraps it."""
    assert replay_loop._score( "yes_no", { "value": "yes" }, { "value": "yes" }, None ) is True
    assert replay_loop._score( "yes_no", { "value": "yes" }, 5, None ) is False


def test_a_json_answer_under_value_is_decoded_for_multiple_choice_and_batch_asks_only():
    """The engine decodes the JSON string a router stores; the replay must read the same answer."""
    wrapped = json.dumps( { "answers": { "Pick": [ "a" ] } } )
    for kind in ( "multiple_choice", "open_ended_batch" ):
        assert replay_loop._actual_dict( { "value": wrapped }, kind ) == { "answers": { "Pick": [ "a" ] } }
        assert replay_loop._actual_dict( wrapped, kind ) == { "answers": { "Pick": [ "a" ] } }
        assert replay_loop._actual_dict( { "value": "not json" }, kind ) == { "value": "not json" }
        assert replay_loop._actual_dict( { "answers": { "Pick": [ "b" ] } }, kind ) == { "answers": { "Pick": [ "b" ] } }
    assert replay_loop._actual_dict( { "value": wrapped }, "yes_no" ) == { "value": wrapped }
    assert replay_loop._actual_dict( { "value": wrapped } ) == { "value": wrapped }


def test_the_family_count_counts_distinct_families( engine ):
    """Two asks of one family and one of another make two."""
    asks = [ _ask( engine, "a", 1, 0, "yes", title="Restart worker 1?" ), _ask( engine, "b", 1, 600, "yes", title="Restart worker 2?" ),
             _ask( engine, "c", 1, 1200, "yes", title="Delete the branch?" ) ]
    assert replay( asks, engine, SHA )[ "families" ] == 2


def _records( correct_by_arm ):
    """Records for two arms from lists of booleans."""
    return { arm: [ { "meta": { "correct": value } } for value in values ] for arm, values in correct_by_arm.items() }


def test_the_summary_carries_every_denominator_and_says_not_decisive_below_the_floor():
    """Two disagreements against a floor of 10 give no verdict."""
    run = { "records": _records( { ENGINE_ARM: [ True ] * 8 + [ False ] * 2, "always_yes": [ True ] * 7 + [ False ] * 3 } ),
            "not_replayable": 4, "unrebuildable_cases": 1, "families": 3 }
    report = summarize( run, "always_yes", operational_floor=10 )
    assert report[ "asks_replayed" ] == 10 and report[ "not_replayable" ] == 4 and report[ "families" ] == 3
    assert report[ "unrebuildable_cases" ] == 1 and report[ "baseline" ] == "always_yes"
    assert ( report[ "engine_correct" ], report[ "baseline_correct" ] ) == ( 8, 7 )
    assert ( report[ "engine_only_right" ], report[ "baseline_only_right" ] ) == ( 1, 0 )
    assert report[ "mcnemar" ][ "n_discordant" ] == 1 and report[ "floor_met" ] is False
    assert report[ "verdict" ] == "not decisive"
    low, high = report[ "engine_interval" ]
    assert 0.0 < low < 0.8 < high < 1.0


def test_the_verdict_at_the_floor_follows_mcnemar():
    """Twelve discordant pairs one way win, a split is no difference, the other way loses."""
    def run_for( wins, losses ):
        engine   = [ True ] * wins + [ False ] * losses
        baseline = [ False ] * wins + [ True ] * losses
        return { "records": _records( { ENGINE_ARM: engine, "b": baseline } ), "not_replayable": 0, "unrebuildable_cases": 0, "families": 1 }
    assert summarize( run_for( 12, 0 ), "b", 10 )[ "verdict" ] == "engine better"
    assert summarize( run_for( 6, 6 ), "b", 10 )[ "verdict" ] == "no difference"
    assert summarize( run_for( 0, 12 ), "b", 10 )[ "verdict" ] == "baseline better"
    assert summarize( run_for( 12, 0 ), "b", 10 )[ "floor_met" ] is True


def test_the_floor_and_the_mcnemar_cut_each_flip_at_one_pair():
    """The floor flips between 9 and 10 discordant pairs, the McNemar cut between 8-2 and 9-1."""
    def run_for( wins, losses ):
        engine   = [ True ] * wins + [ False ] * losses
        baseline = [ False ] * wins + [ True ] * losses
        return { "records": _records( { ENGINE_ARM: engine, "b": baseline } ), "not_replayable": 0, "unrebuildable_cases": 0, "families": 1 }
    assert ( summarize( run_for( 9, 1 ), "b", 10 )[ "floor_met" ], summarize( run_for( 9, 1 ), "b", 10 )[ "verdict" ] ) == ( True, "engine better" )
    assert summarize( run_for( 8, 2 ), "b", 10 )[ "verdict" ] == "no difference"
    short = summarize( run_for( 9, 0 ), "b", 10 )
    assert ( short[ "mcnemar" ][ "n_discordant" ], short[ "floor_met" ], short[ "verdict" ] ) == ( 9, False, "not decisive" )


def test_the_floor_is_required_before_the_run_is_summarised():
    """A missing floor is refused, not defaulted."""
    run = { "records": _records( { ENGINE_ARM: [ True ], "b": [ False ] } ), "not_replayable": 0, "unrebuildable_cases": 0, "families": 1 }
    with pytest.raises( Exception ) as error:
        summarize( run, "b", None )
    assert "PRE-STATED" in str( error.value )


def test_target_types_limit_which_asks_are_predicted_but_every_ask_stays_a_case( engine ):
    """A free-text ask is not predicted or counted, yet a yes/no ask can still retrieve it."""
    asks = [ _ask( engine, "text", 2, 0, "yes", response_type="open_ended" ), _ask( engine, "yn", 2, 10, "yes" ) ]
    run  = replay( asks, engine, SHA, target_types=( "yes_no", ) )
    assert [ r[ "meta" ][ "notification_id" ] for r in run[ "records" ][ ENGINE_ARM ] ] == [ "yn" ]
    assert run[ "not_replayable" ] == 0


def test_the_replay_uses_the_time_sliced_store_by_default( engine ):
    """The store the engine reads in the replay is the time-sliced one."""
    seen = []
    def factory( rows ):
        store = TimeSlicedDecisionStore( rows )
        seen.append( store )
        return store
    replay( [ _ask( engine, "a", 1, 0, "yes" ) ], engine, SHA, store_factory=factory )
    assert len( seen ) == 1 and isinstance( seen[ 0 ], TimeSlicedDecisionStore )
    assert seen[ 0 ].refused_writes == 0, "the engine tried to write a case during the replay"


def _context_arm( ask, visible, episode_view=None, principles=None ):
    """A double arm that forecasts yes and keeps what it was handed."""
    _context_arm.calls.append( { "ask": ask, "visible": visible, "episode_view": episode_view, "principles": principles } )
    return { "value": "yes" }


def test_a_context_arm_gets_its_view_and_principles_and_other_baselines_are_called_as_before( engine ):
    """Only a named arm receives context; always_yes keeps its two-argument call."""
    _context_arm.calls = []
    asks  = [ _ask( engine, "a", 1, 0, "yes" ), _ask( engine, "b", 1, 10, "no" ) ]
    seen  = []
    view  = lambda ask, visible: seen.append( ( "view", ask[ "id" ], [ r[ "id" ] for r in visible ] ) ) or f"view-{ask[ 'id' ]}"
    prin  = lambda ask, asked_at: seen.append( ( "prin", ask[ "id" ], asked_at ) ) or f"prin-{ask[ 'id' ]}"
    run   = replay( asks, engine, SHA, baselines={ "b1": _context_arm, "always_yes": replay_loop.always_yes_arm },
                    context_arms=( "b1", ), episode_view_provider=view, principles_provider=prin )
    assert [ ( c[ "episode_view" ], c[ "principles" ] ) for c in _context_arm.calls ] == [ ( "view-a", "prin-a" ), ( "view-b", "prin-b" ) ]
    assert seen[ 1 ] == ( "prin", "a", NOON ) and seen[ 2 ] == ( "view", "b", [ "a" ] )
    assert [ r[ "meta" ][ "forecast" ] for r in run[ "records" ][ "always_yes" ] ] == [ { "value": "yes" } ] * 2


KNOWN_AT_ASK = [ "asked_at", "category", "created_at", "data_origin", "id", "message", "owner_user_id", "question", "question_embedding",
                 "recipient_id", "response_options", "response_type", "sender_id", "title" ]


def _cohort_shaped( engine, ask_id, axis, minutes, answer ):
    """An ask shaped like cohort_asks output, its answer fields spelling out the answer."""
    ask = _ask( engine, ask_id, axis, minutes, answer )
    ask.update( { "logged_value": f"SECRET-{answer}", "logged_match": f"SECRET-{answer}", "ratification_state": f"SECRET-{answer}",
                  "answer_source": f"SECRET-{answer}", "decision_value": f"SECRET-{answer}", "actual_value": f"SECRET-{answer}" } )
    return ask


def test_a_provider_and_an_arm_are_handed_only_the_fields_known_at_the_ask( engine ):
    """The ask they see has the listed keys and no answer text."""
    _context_arm.calls = []
    asks  = [ _cohort_shaped( engine, "early", 2, 0, "ONE" ), _cohort_shaped( engine, "mid", 2, 30, "TWO" ), _cohort_shaped( engine, "late", 2, 60, "THREE" ) ]
    got   = []
    def view( ask, visible ):
        got.append( ( ask, visible ) )
    replay( asks, engine, SHA, baselines={ "b1": _context_arm }, context_arms=( "b1", ), episode_view_provider=view )
    assert len( got ) == 3
    for ask, _ in got + [ ( c[ "ask" ], None ) for c in _context_arm.calls ]:
        assert sorted( ask ) == KNOWN_AT_ASK
        assert "SECRET-" + { "early": "ONE", "mid": "TWO", "late": "THREE" }[ ask[ "id" ] ] not in json.dumps( ask, default=str )
    for ask, visible in got:
        assert all( r[ "responded_at" ] <= aware_moment( ask[ "asked_at" ] ) for r in visible )
    assert [ [ r[ "id" ] for r in v ] for _, v in got ] == [ [], [ "early" ], [ "early", "mid" ] ]
    assert asks[ 0 ][ "actual_value" ] == "SECRET-ONE" and asks[ 0 ][ "logged_match" ] == "SECRET-ONE"


def test_an_arm_that_clears_its_inputs_changes_nothing_for_the_next_ask_or_arm( engine ):
    """Clearing the copies leaves the replay's rows and a second arm intact."""
    def vandal( ask, visible, episode_view=None, principles=None ):
        for row in visible: row[ "response_options" ] = "gone"; row.clear()
        visible.clear()
        ask[ "response_options" ] = "gone"
        ask.clear()
        return { "value": "yes" }
    _context_arm.calls = []
    asks = [ _ask( engine, "a", 3, 0, "yes", response_options=[ "x" ] ), _ask( engine, "b", 3, 10, "yes", response_options=[ "x" ] ),
             _ask( engine, "c", 3, 20, "yes", response_options=[ "x" ] ) ]
    replay( asks, engine, SHA, baselines={ "vandal": vandal, "after": _context_arm }, context_arms=( "vandal", "after" ) )
    assert [ [ r[ "id" ] for r in c[ "visible" ] ] for c in _context_arm.calls ] == [ [], [ "a" ], [ "a", "b" ] ]
    assert [ c[ "ask" ][ "response_options" ] for c in _context_arm.calls ] == [ [ "x" ] ] * 3
    assert [ a[ "response_options" ] for a in asks ] == [ [ "x" ] ] * 3


def test_a_context_arm_without_providers_gets_none_and_an_unknown_name_is_refused( engine ):
    """Missing providers read as None; an unknown arm name raises before any ask is replayed."""
    _context_arm.calls = []
    replay( [ _ask( engine, "a", 1, 0, "yes" ) ], engine, SHA, baselines={ "b1": _context_arm }, context_arms=( "b1", ) )
    assert _context_arm.calls[ 0 ][ "episode_view" ] is None and _context_arm.calls[ 0 ][ "principles" ] is None
    with pytest.raises( ValueError, match="ghost" ):
        replay( [ _ask( engine, "a", 1, 0, "yes" ) ], engine, SHA, baselines={ "b1": _context_arm }, context_arms=( "ghost", ) )


def test_summarize_pairs_an_arm_against_a_comparator_through_the_same_run( engine ):
    """One run pairs a context arm with a comparator; the arm's records replace the engine's."""
    run = { "records": _records( { ENGINE_ARM: [ False ] * 12, "b1": [ True ] * 12, "c0": [ False ] * 12 } ),
            "not_replayable": 0, "unrebuildable_cases": 0, "families": 1 }
    report = summarize( run, "c0", 10, arm="b1" )
    assert report[ "arm" ] == "b1" and report[ "baseline" ] == "c0"
    assert ( report[ "engine_correct" ], report[ "baseline_correct" ], report[ "engine_only_right" ] ) == ( 12, 0, 12 )
    assert report[ "verdict" ] == "engine better"
    assert summarize( run, "c0", 10 )[ "arm" ] == ENGINE_ARM
