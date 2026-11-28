"""
The write-in outcome, tested over literal replies and one real reply; no model call.

Each test names what it would catch:
  - a probability read from the wrong field, or dropped                 -> test_attach_*
  - a reply without the outcome accepted, or a bad number accepted      -> test_a_reply_*
  - the switch changing the plain full-answer prompt, reply or version  -> test_switch_off_*
  - a precision or recall computed over the wrong denominator           -> test_precision_*
"""

import asyncio
import copy
import json

import pytest

import cosa.agents.prediction_engine.context_baseline as cb
import cosa.agents.prediction_engine.episode_view as ev
import cosa.agents.prediction_engine.full_answer as fa
import cosa.agents.prediction_engine.write_in_outcome as wo
import cosa.utils.util as cu
from cosa.agents.prediction_engine.accuracy_comparators import compare_multiple_choice
from cosa.agents.prediction_engine.principles_forecast import CapGate
from cosa.rest.postgres_models import PredictionArmForecast
from tests.unit.test_full_answer import CHOICES, DOCS, PLAN_B, TESTS, ask, card, episode, factory, good, replying  # noqa: F401  (factory is a fixture)

FULL_VERSION = "context-baseline-9b7d5ebc72"   # cb.predictor_version( ALL_LAYERS, True ) at 9b1d76ac9, before this module existed


def with_outcome( plan=0.1, extras=0.7 ):
    """The good multiple-choice reply with a write-in probability on each option field."""
    reply = copy.deepcopy( good( "multiple_choice" ) )
    reply[ "fields" ][ "Plan" ][ wo.PROBABILITY_KEY ]   = plan
    reply[ "fields" ][ "Extras" ][ wo.PROBABILITY_KEY ] = extras
    return reply


def baseline( tmp_path, **switches ):
    """A full-answer baseline over a throwaway ledger."""
    return cb.ContextBaseline( "haiku-x", 5, cb.ALL_LAYERS, cb.open_ledger( str( tmp_path / "ledger.jsonl" ) ), **switches )


def test_attach_puts_each_fields_probability_on_the_field_and_in_the_outcome_map_and_leaves_the_selection( factory ):
    ep     = episode( factory, "multiple_choice" )
    text   = json.dumps( with_outcome() )
    plain  = fa.parse_full_reply( text, ep )
    record = wo.attach( text, ep, fa.parse_full_reply( text, ep ) )
    assert record[ wo.OUTCOME_KEY ] == { "Plan": 0.1, "Extras": 0.7 }
    assert record[ "fields" ][ "Plan" ] == { "option_ids": [ PLAN_B ], wo.PROBABILITY_KEY: 0.1 }
    assert record[ "fields" ][ "Extras" ] == { "option_ids": [ DOCS, TESTS ], wo.PROBABILITY_KEY: 0.7 }
    assert record[ "answers" ] == plain[ "answers" ] == { "Plan": "Plan B (Recommended)", "Extras": [ "Docs", "Tests" ] }, "the labels are unchanged"
    assert "Note" not in record[ wo.OUTCOME_KEY ], "a free-text field is not forecast, so it has no outcome"


def test_attach_finds_a_field_the_reply_keyed_by_its_question( factory ):
    ep    = episode( factory, "multiple_choice" )
    reply = with_outcome( plan=0.3 )
    reply[ "fields" ][ "Which plan?" ] = reply[ "fields" ].pop( "Plan" )
    text  = json.dumps( reply )
    assert wo.attach( text, ep, fa.parse_full_reply( text, ep ) )[ wo.OUTCOME_KEY ][ "Plan" ] == 0.3


def test_a_reply_that_leaves_a_fields_probability_out_is_refused_as_field_missing( factory ):
    ep    = episode( factory, "multiple_choice" )
    reply = with_outcome()
    del reply[ "fields" ][ "Extras" ][ wo.PROBABILITY_KEY ]
    text  = json.dumps( reply )
    with pytest.raises( fa.ReplyRefused ) as refusal: wo.attach( text, ep, fa.parse_full_reply( text, ep ) )
    assert refusal.value.reason == fa.REASON_FIELD_MISSING and "'Extras'" in str( refusal.value )


@pytest.mark.parametrize( "bad", [ 1.5, -0.1, "0.2", True, None ] )
def test_a_reply_whose_probability_is_not_a_number_from_0_to_1_is_refused( factory, bad ):
    ep   = episode( factory, "multiple_choice" )
    text = json.dumps( with_outcome( plan=bad ) )
    with pytest.raises( fa.ReplyRefused ) as refusal: wo.attach( text, ep, fa.parse_full_reply( text, ep ) )
    assert refusal.value.reason == fa.REASON_NOT_NORMALISED


def test_attach_and_the_note_leave_any_other_card_type_alone( factory ):
    ep     = episode( factory, "yes_no" )
    text   = json.dumps( good( "yes_no" ) )
    record = fa.parse_full_reply( text, ep )
    assert wo.attach( text, ep, record ) == fa.parse_full_reply( text, ep ) and wo.OUTCOME_KEY not in record
    assert wo.with_note( "prompt", ep ) == "prompt"
    assert wo.with_note( "prompt", episode( factory, "multiple_choice" ) ) == "prompt" + wo.FORMAT_NOTE


def test_the_switch_ships_off_in_the_ini_and_reads_off_when_unreadable( monkeypatch, capsys ):
    assert wo.write_in_outcome_enabled() is False
    monkeypatch.setattr( wo, "ConfigurationManager", lambda env_var_name: ( _ for _ in () ).throw( RuntimeError( "no ini" ) ) )
    assert wo.write_in_outcome_enabled() is False and "unreadable, treated as off" in capsys.readouterr().out


def test_switch_off_the_full_answer_version_prompt_and_reply_are_what_they_were( factory, tmp_path ):
    c0 = baseline( tmp_path, full=True, write_in=False )
    ep = episode( factory, "multiple_choice" )
    assert c0.predictor_version == cb.predictor_version( cb.ALL_LAYERS, True ) == FULL_VERSION
    assert c0.build_prompts( ep )[ 1 ] == cb.build_full_user_prompt( ep ) and wo.FORMAT_NOTE not in c0.build_prompts( ep )[ 1 ]
    assert wo.OUTCOME_KEY not in c0.parse( json.dumps( good( "multiple_choice" ) ), ep ), "a plain reply still parses, with no outcome"


def test_the_baseline_reads_the_switch_once_and_with_it_on_asks_for_and_parses_the_outcome_under_its_own_version( factory, tmp_path, monkeypatch ):
    monkeypatch.setattr( fa, "full_answer_enabled", lambda: True )
    monkeypatch.setattr( wo, "write_in_outcome_enabled", lambda: True )
    c0 = baseline( tmp_path )
    monkeypatch.setattr( wo, "write_in_outcome_enabled", lambda: False )
    ep = episode( factory, "multiple_choice" )
    assert c0.write_in is True and c0.build_prompts( ep )[ 1 ].endswith( wo.FORMAT_NOTE )
    assert c0.parse( json.dumps( with_outcome() ), ep )[ wo.OUTCOME_KEY ] == { "Plan": 0.1, "Extras": 0.7 }
    assert c0.predictor_version == cb.predictor_version( cb.ALL_LAYERS, True, True ) != FULL_VERSION
    with pytest.raises( fa.ReplyRefused ): c0.parse( json.dumps( good( "multiple_choice" ) ), ep )


def test_with_full_off_the_write_in_switch_is_never_read_and_reads_false( tmp_path, monkeypatch ):
    monkeypatch.setattr( wo, "write_in_outcome_enabled", lambda: pytest.fail( "read with the full-answer reply off" ) )
    assert baseline( tmp_path, full=False ).write_in is False
    assert baseline( tmp_path, full=False, write_in=True ).write_in is False


def test_a_change_to_the_module_is_a_new_version_only_while_its_switch_is_on( monkeypatch ):
    full, on = cb.predictor_version( cb.ALL_LAYERS, True ), cb.predictor_version( cb.ALL_LAYERS, True, True )
    real     = cb.inspect.getsource
    monkeypatch.setattr( cb.inspect, "getsource", lambda target: real( target ) + "# changed" if target is wo else real( target ) )
    assert cb.predictor_version( cb.ALL_LAYERS, True, True ) != on and cb.predictor_version( cb.ALL_LAYERS, True ) == full


def test_the_baseline_job_stores_the_outcome_on_the_forecast_row( factory, tmp_path ):
    c0  = cb.ContextBaseline( "haiku-x", 5, cb.ALL_LAYERS, cb.open_ledger( str( tmp_path / "ledger.jsonl" ) ), query_fn=replying( json.dumps( with_outcome( 0.2, 0.9 ) ) ),
                              full=True, write_in=True )
    out = asyncio.run( cb.run_context_forecast( card( factory, "multiple_choice" ), session_factory=factory, c0=c0, gate=CapGate( 2 ), enabled=True ) )
    with factory() as db: row = db.query( PredictionArmForecast ).one()
    assert out[ "status" ] != "failed" and row.forecast[ wo.OUTCOME_KEY ] == { "Plan": 0.2, "Extras": 0.9 } and row.predictor_version == c0.predictor_version


def _fields( answers, forecast=None ):
    """The per-field records compare_multiple_choice gives for an answer."""
    return compare_multiple_choice( forecast or { "answers": { "Plan": "Plan A" } }, { "answers": answers }, CHOICES, per_field=True )[ 1 ][ "fields" ]


def test_field_outcomes_pair_each_forecast_field_with_whether_rick_typed_it():
    fields   = _fields( { "Plan": "ask me tomorrow", "Extras": [ "Docs" ], "Note": "busy" } )
    forecast = { wo.OUTCOME_KEY: { "Plan": 0.8, "Extras": 0.5 } }
    assert wo.field_outcomes( forecast, fields ) == [ { "header": "Plan", "probability": 0.8, "predicted": True, "actual": True },
                                                      { "header": "Extras", "probability": 0.5, "predicted": True, "actual": False } ], \
        "0.5 is forecast typed; Note has no probability, so it is not paired"
    assert wo.field_outcomes( None, fields ) == [] and wo.field_outcomes( { "answers": {} }, fields ) == []


def test_precision_and_recall_use_the_forecast_typed_and_the_actually_typed_fields_as_their_denominators():
    pairs  = [ { "probability": 0.9, "predicted": True, "actual": True }, { "probability": 0.6, "predicted": True, "actual": False },
               { "probability": 0.2, "predicted": False, "actual": True }, { "probability": 0.1, "predicted": False, "actual": True } ]
    scores = wo.precision_recall( pairs )
    assert ( scores[ "fields" ], scores[ "actual" ], scores[ "predicted" ], scores[ "true_positive" ] ) == ( 4, 3, 2, 1 )
    assert scores[ "precision" ] == 0.5 and scores[ "recall" ] == 1 / 3
    assert scores[ "brier" ] == pytest.approx( ( 0.01 + 0.36 + 0.64 + 0.81 ) / 4 )
    assert wo.precision_recall( [] ) == { "fields": 0, "actual": 0, "predicted": 0, "true_positive": 0, "precision": None, "recall": None, "brier": None }


REAL = json.load( open( cu.get_project_root() + "/src/tests/unit/fixtures/write_in_outcome_real_reply.json", encoding="utf-8" ) )


def test_a_real_haiku_reply_parses_through_the_baseline_with_its_outcome_and_labels( factory, tmp_path ):
    """Captured from the 27 Nov probe run: the real producer's reply, read by the real reader."""
    nid = ask( factory, title=REAL[ "card" ][ "title" ], message=REAL[ "card" ][ "message" ], response_type=REAL[ "card" ][ "response_type" ],
               response_options=REAL[ "card" ][ "response_options" ], response_default=REAL[ "card" ][ "response_default" ] )
    with factory() as db: ep = ev.episode_view( db, nid, limit=50 )
    record = baseline( tmp_path, full=True, write_in=True ).parse( REAL[ "reply" ], ep )
    assert record[ wo.OUTCOME_KEY ] == REAL[ "expected_outcomes" ] and record[ "answers" ] == REAL[ "expected_answers" ]
    assert set( record[ wo.OUTCOME_KEY ] ) == { q[ "header" ] for q in REAL[ "card" ][ "response_options" ][ "questions" ] if q.get( "options" ) }
