"""
Unit tests for predicting and abstaining per multiple-choice field.

They cover the per-field predictor, the `fields` output of PredictionResult and the per-field scoring.
They also cover the typed-Other outcome and the `field_forecasts` round trip through the forecast row.
Each test names what it would catch.
No test calls a model or writes a database: the neighbour lookup is a canned map, apart from one fake session.
"""

import json
import uuid
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from cosa.agents.prediction_engine import config as cfg
from cosa.agents.prediction_engine.accuracy_comparators import (
    compare_multiple_choice, get_comparator, offered_labels, score_field,
)
from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
from cosa.agents.prediction_engine.prediction_result import PredictionResult


def _card( *fields ):
    """A stored response_options: each field is ( header, multi_select, [labels] )."""
    return { "questions": [
        { "header": h, "question": h + "?", "multi_select": m, "options": [ { "label": l, "description": "" } for l in labels ] }
        for h, m, labels in fields
    ] }


CURRENT = _card( ( "Approach", False, [ "Proceed", "Skip" ] ), ( "Tags", True, [ "A", "B", "C" ] ) )


class FakeStore:
    def __init__( self, cases ):
        self._cases = cases
    def find_similar( self, **kwargs ):
        return self._cases


def _case( case_id, answers, pct=90, **extra ):
    record = { "id": case_id, "decision_value": json.dumps( { "answers": answers } ) }
    record.update( extra )
    return ( pct, record )


@pytest.fixture
def engine( monkeypatch ):
    PredictionEngine.reset()
    eng = PredictionEngine( debug=False )
    eng.per_field_mc_enabled = True
    yield eng
    PredictionEngine.reset()


def _wire( engine, monkeypatch, cases, neighbour_cards ):
    """Retrieval returns `cases`; each neighbour id maps to its own card, or None for no row."""
    monkeypatch.setattr( engine, "_get_embedding_store", lambda: FakeStore( cases ) )
    parsed = { cid: ( None if card is None else PredictionEngine._extract_valid_options( card, normalise=True ) ) for cid, card in neighbour_cards.items() }
    monkeypatch.setattr( engine, "_neighbour_options", lambda ids: { i: parsed.get( i ) for i in ids } )


def _predict( engine, options=CURRENT ):
    return engine._predict_multiple_choice( "m", "workflow", [ 0.1 ], options )


# ---- _normalise_text and the extended _extract_valid_options ---------------

def test_normalise_text_folds_case_space_and_trailing_punctuation():
    assert PredictionEngine._normalise_text( "  Proceed  Now. " ) == "proceed now"
    assert PredictionEngine._normalise_text( "Proceed?" ) == PredictionEngine._normalise_text( "proceed" )


def test_extract_valid_options_unchanged_without_normalise():
    result = PredictionEngine._extract_valid_options( CURRENT )
    assert set( result ) == { "Approach", "Tags" } and "by_label" not in result[ "Approach" ]


def test_extract_valid_options_normalised_keys_and_ambiguity():
    result = PredictionEngine._extract_valid_options( CURRENT, normalise=True )
    assert set( result ) == { "approach", "tags" }
    assert result[ "approach" ][ "header" ] == "Approach" and result[ "approach" ][ "ambiguous" ] is False
    assert result[ "approach" ][ "by_label" ] == { "proceed": [ "Proceed" ], "skip": [ "Skip" ] }
    twin_labels  = PredictionEngine._extract_valid_options( _card( ( "F", False, [ "Go", "go" ] ) ), normalise=True )
    twin_headers = PredictionEngine._extract_valid_options( _card( ( "Mode", False, [ "x" ] ), ( "mode:", False, [ "y" ] ) ), normalise=True )
    assert twin_labels[ "f" ][ "ambiguous" ] is True
    assert twin_headers[ "mode" ][ "ambiguous" ] is True


# ---- the predictor ---------------------------------------------------------

def test_mixed_card_returns_a_scalar_for_one_field_and_a_set_for_another( engine, monkeypatch ):
    cards = { "n1": CURRENT, "n2": CURRENT, "n3": CURRENT }
    cases = [ _case( n, { "Approach": "Proceed", "Tags": [ "A", "B" ] } ) for n in cards ]
    _wire( engine, monkeypatch, cases, cards )
    result = _predict( engine )
    assert result.predicted_value == { "answers": { "Approach": "Proceed", "Tags": [ "A", "B" ] } }
    assert result.fields[ "Approach" ][ "candidate" ] == "Proceed" and result.fields[ "Tags" ][ "candidate" ] == [ "A", "B" ]
    assert result.fields[ "Approach" ][ "cases" ] == 3
    assert result.confidence == pytest.approx( 0.9 * 1.0 )
    assert result.metadata[ "abstained" ] == []


def test_one_unsupported_header_abstains_alone_and_the_card_still_forecasts( engine, monkeypatch ):
    other = _card( ( "Approach", False, [ "Proceed", "Skip" ] ) )   # neighbours never asked "Tags"
    cases = [ _case( "n1", { "Approach": "Skip" } ), _case( "n2", { "Approach": "Skip" } ) ]
    _wire( engine, monkeypatch, cases, { "n1": other, "n2": other } )
    result = _predict( engine )
    assert result.predicted_value == { "answers": { "Approach": "Skip" } }
    assert result.fields[ "Tags" ] == { "reason": "no_aligned_neighbours" }
    assert result.metadata[ "abstained" ] == [ "Tags" ]


def test_reordering_fields_keeps_the_unambiguous_matches( engine, monkeypatch ):
    reordered = _card( ( "Tags", True, [ "C", "B", "A" ] ), ( "Approach", False, [ "Skip", "Proceed" ] ) )
    cases = [ _case( n, { "approach": "proceed", "TAGS": [ "a" ] } ) for n in ( "n1", "n2" ) ]
    _wire( engine, monkeypatch, cases, { "n1": reordered, "n2": reordered } )
    result = _predict( engine )
    assert result.predicted_value == { "answers": { "Approach": "Proceed", "Tags": [ "A" ] } }


def test_two_fields_sharing_a_label_cannot_swap( engine, monkeypatch ):
    twin   = _card( ( "First", False, [ "Proceed", "Stop" ] ), ( "Second", False, [ "Proceed", "Wait" ] ) )
    cases  = [ _case( n, { "First": "Proceed", "Second": "Wait" } ) for n in ( "n1", "n2" ) ]
    _wire( engine, monkeypatch, cases, { "n1": twin, "n2": twin } )
    result = _predict( engine, twin )
    assert result.predicted_value == { "answers": { "First": "Proceed", "Second": "Wait" } }


def test_ambiguous_current_field_abstains_with_its_reason( engine, monkeypatch ):
    twin  = _card( ( "F", False, [ "Go", "go" ] ), ( "Approach", False, [ "Proceed", "Skip" ] ) )
    cases = [ _case( "n1", { "F": "Go", "Approach": "Proceed" } ) ]
    _wire( engine, monkeypatch, cases, { "n1": twin } )
    result = _predict( engine, twin )
    assert result.fields[ "F" ] == { "reason": "ambiguous_labels" }
    assert result.fields[ "Approach" ][ "candidate" ] == "Proceed"


def test_neighbour_without_a_notification_row_gives_no_option_evidence( engine, monkeypatch ):
    cases = [ _case( "n1", { "Approach": "Proceed", "Tags": [ "A" ] } ) ]
    _wire( engine, monkeypatch, cases, { "n1": None } )
    result = _predict( engine )
    assert result.predicted_value is None and result.strategy == cfg.STRATEGY_COLD_START
    assert result.metadata[ "reason" ] == "no_field_candidates"
    assert result.fields == { "Approach": { "reason": "no_aligned_neighbours" }, "Tags": { "reason": "no_aligned_neighbours" } }


def test_neighbour_with_an_ambiguous_field_casts_no_evidence( engine, monkeypatch ):
    twin  = _card( ( "Approach", False, [ "Go", "go" ] ), ( "Tags", True, [ "A", "B", "C" ] ) )
    cases = [ _case( "n1", { "Approach": "Go", "Tags": [ "A" ] } ) ]
    _wire( engine, monkeypatch, cases, { "n1": twin } )
    result = _predict( engine )
    assert result.fields[ "Approach" ] == { "reason": "no_aligned_neighbours" }
    assert result.fields[ "Tags" ][ "candidate" ] == [ "A" ]


def test_neighbour_answer_missing_or_duplicated_under_the_header_casts_no_evidence( engine, monkeypatch ):
    cases = [ _case( "n1", { "Tags": [ "A" ] } ),                                   # no Approach answer
              _case( "n2", { "Approach": "Skip", "approach": "Proceed", "Tags": [ "A" ] } ) ]   # two answers, one normalised header
    _wire( engine, monkeypatch, cases, { "n1": CURRENT, "n2": CURRENT } )
    result = _predict( engine )
    assert result.fields[ "Approach" ] == { "reason": "no_aligned_neighbours" }


def test_option_the_neighbour_never_offered_is_not_counted_against_it( engine, monkeypatch ):
    # n1 and n2 offered only A and B; n3 offered A, B, C. C was chosen once, by the one neighbour that could have chosen it.
    narrow = _card( ( "Approach", False, [ "Proceed", "Skip" ] ), ( "Tags", True, [ "A", "B" ] ) )
    cases  = [ _case( "n1", { "Approach": "Proceed", "Tags": [ "A" ] } ),
               _case( "n2", { "Approach": "Proceed", "Tags": [ "A" ] } ),
               _case( "n3", { "Approach": "Proceed", "Tags": [ "A", "C" ] } ) ]
    _wire( engine, monkeypatch, cases, { "n1": narrow, "n2": narrow, "n3": CURRENT } )
    assert _predict( engine ).fields[ "Tags" ][ "candidate" ] == [ "A", "C" ]    # C: 1 vote of 1 neighbour that offered it


def test_a_pick_the_neighbour_offered_but_the_current_card_does_not_is_no_evidence( engine, monkeypatch ):
    wider = _card( ( "Approach", False, [ "Proceed", "Skip", "Defer" ] ), ( "Tags", True, [ "A", "B", "C" ] ) )
    cases = [ _case( "n1", { "Approach": "Defer", "Tags": [ "A" ] } ), _case( "n2", { "Approach": "Skip", "Tags": [ "A" ] } ) ]
    _wire( engine, monkeypatch, cases, { "n1": wider, "n2": wider } )
    assert _predict( engine ).fields[ "Approach" ][ "candidate" ] == "Skip"


def test_a_field_whose_neighbours_all_picked_foreign_labels_has_no_option_evidence( engine, monkeypatch ):
    wider = _card( ( "Approach", False, [ "Proceed", "Skip", "Defer" ] ), ( "Tags", True, [ "A", "B", "C" ] ) )
    cases = [ _case( "n1", { "Approach": "Defer", "Tags": [ "A" ] } ) ]
    _wire( engine, monkeypatch, cases, { "n1": wider } )
    assert _predict( engine ).fields[ "Approach" ] == { "reason": "no_option_evidence" }


def test_typed_other_outweighing_the_best_option_abstains_a_single_select( engine, monkeypatch ):
    cases = [ _case( "n1", { "Approach": "something else entirely", "Tags": [ "A" ] } ),
              _case( "n2", { "Approach": "a typed answer", "Tags": [ "A" ] } ),
              _case( "n3", { "Approach": "Proceed", "Tags": [ "A" ] } ) ]
    _wire( engine, monkeypatch, cases, { n: CURRENT for n in ( "n1", "n2", "n3" ) } )
    result = _predict( engine )
    assert result.fields[ "Approach" ] == { "reason": "other_likely" }
    assert result.predicted_value == { "answers": { "Tags": [ "A" ] } }


def test_a_typed_other_with_no_offered_pick_at_all_is_other_likely( engine, monkeypatch ):
    cases = [ _case( "n1", { "Approach": "typed", "Tags": [ "A" ] } ) ]
    _wire( engine, monkeypatch, cases, { "n1": CURRENT } )
    assert _predict( engine ).fields[ "Approach" ] == { "reason": "other_likely" }


def test_typed_other_in_half_the_neighbours_abstains_a_multi_select( engine, monkeypatch ):
    cases = [ _case( "n1", { "Approach": "Proceed", "Tags": [ "free text" ] } ),
              _case( "n2", { "Approach": "Proceed", "Tags": [ "A" ] } ) ]
    _wire( engine, monkeypatch, cases, { "n1": CURRENT, "n2": CURRENT } )
    assert _predict( engine ).fields[ "Tags" ] == { "reason": "other_likely" }


def test_multi_select_falls_back_to_the_top_option_when_none_reaches_half( engine, monkeypatch ):
    cases = [ _case( n, { "Approach": "Proceed", "Tags": [ t ] } ) for n, t in ( ( "n1", "A" ), ( "n2", "B" ), ( "n3", "C" ), ( "n4", "C" ), ( "n5", "A" ) ) ]
    # A 2/5, B 1/5, C 2/5: nothing reaches half, so the highest (ties broken by label) is kept
    _wire( engine, monkeypatch, cases, { c[ 1 ][ "id" ]: CURRENT for c in cases } )
    assert _predict( engine ).fields[ "Tags" ][ "candidate" ] == [ "C" ]


def test_rejected_cases_steer_away_and_all_rejected_means_no_positive_evidence( engine, monkeypatch ):
    cases = [ _case( "n1", { "Approach": "Proceed", "Tags": [ "A" ] }, ratification_state="rejected" ) ]
    _wire( engine, monkeypatch, cases, { "n1": CURRENT } )
    result = _predict( engine )
    assert result.fields[ "Approach" ] == { "reason": "no_positive_evidence" }
    assert result.strategy == cfg.STRATEGY_COLD_START


def test_a_rejected_vote_cancels_an_approving_one_and_a_lone_rejection_leaves_no_option_evidence( engine, monkeypatch ):
    cases = [ _case( "n1", { "Approach": "Proceed", "Tags": [ "A" ] } ),
              _case( "n2", { "Approach": "Skip",    "Tags": [ "A" ] }, ratification_state="rejected" ) ]
    _wire( engine, monkeypatch, cases, { "n1": CURRENT, "n2": CURRENT } )
    result = _predict( engine )
    assert result.fields[ "Approach" ][ "candidate" ] == "Proceed"


def test_unparseable_decision_value_is_skipped( engine, monkeypatch ):
    cases = [ ( 90, { "id": "n1", "decision_value": "not json" } ), _case( "n2", { "Approach": "Proceed", "Tags": [ "A" ] } ) ]
    _wire( engine, monkeypatch, cases, { "n1": CURRENT, "n2": CURRENT } )
    assert _predict( engine ).metadata[ "valid_cases" ] == 1


def test_switch_off_keeps_the_whole_card_predictor( engine, monkeypatch ):
    engine.per_field_mc_enabled = False
    other = _card( ( "Approach", False, [ "Proceed", "Skip" ] ) )
    cases = [ _case( "n1", { "Approach": "Skip" } ) ]
    _wire( engine, monkeypatch, cases, { "n1": other } )
    result = _predict( engine )
    assert result.fields is None and result.metadata[ "reason" ] == "no_evidence_for_question_headers"


def test_a_card_that_does_not_parse_uses_the_whole_card_predictor( engine, monkeypatch ):
    cases = [ _case( "n1", { "Approach": "Skip" } ) ]
    _wire( engine, monkeypatch, cases, { "n1": CURRENT } )
    assert _predict( engine, None ).fields is None


# ---- the neighbour options lookup ------------------------------------------

def test_neighbour_options_reads_one_query_and_maps_unknowns_to_none( engine, monkeypatch ):
    known, missing = str( uuid.uuid4() ), str( uuid.uuid4() )
    calls = []

    class Query:
        def filter( self, *a ): calls.append( "filter" ); return self
        def all( self ): return [ SimpleNamespace( id=uuid.UUID( known ), response_options=CURRENT ) ]

    class Session:
        def query( self, *a ): calls.append( "query" ); return Query()

    @contextmanager
    def fake_db(): yield Session()

    monkeypatch.setattr( "cosa.rest.db.database.get_db", fake_db )
    found = engine._neighbour_options( [ known, missing, "not-a-uuid", None ] )
    assert calls == [ "query", "filter" ]
    assert set( found[ known ] ) == { "approach", "tags" }
    assert found[ missing ] is None and found[ "not-a-uuid" ] is None and found[ None ] is None


def test_neighbour_options_with_no_usable_id_does_no_query( engine, monkeypatch ):
    monkeypatch.setattr( "cosa.rest.db.database.get_db", lambda: pytest.fail( "no query expected" ) )
    assert engine._neighbour_options( [ "x" ] ) == { "x": None }


def test_a_neighbour_lookup_error_is_recorded_as_prediction_error_with_its_class( engine, monkeypatch ):
    cases = [ _case( str( uuid.uuid4() ), { "Approach": "Proceed", "Tags": [ "A" ] } ) ]
    monkeypatch.setattr( engine, "_get_embedding_store", lambda: FakeStore( cases ) )
    def broken(): raise RuntimeError( "db down" )
    monkeypatch.setattr( "cosa.rest.db.database.get_db", broken )
    result = engine.predict( { "message": "m", "response_type": "multiple_choice", "sender_id": "s", "response_options": CURRENT }, query_vector=[ 0.1 ] )
    assert result.strategy == cfg.STRATEGY_COLD_START and result.fields is None
    assert result.metadata[ "reason" ] == "prediction_error" and result.metadata[ "error_class" ] == "RuntimeError"


# ---- the result, the hint payload and the forecast row ----------------------

def test_hint_carries_fields_only_when_ready():
    fields = { "Approach": { "candidate": "Proceed", "confidence": 0.9, "cases": 3 }, "Tags": { "reason": "other_likely" } }
    ready  = PredictionResult( "multiple_choice", "c", "cbr_majority_vote", predicted_value={ "answers": { "Approach": "Proceed" } }, confidence=0.9, fields=fields )
    low    = PredictionResult( "multiple_choice", "c", "cbr_majority_vote", predicted_value={ "answers": { "Approach": "Proceed" } }, confidence=0.1, fields=fields )
    plain  = PredictionResult( "multiple_choice", "c", "cbr_majority_vote", predicted_value={ "answers": { "Approach": "Proceed" } }, confidence=0.9 )
    assert ready.to_hint_dict( 0.6, "cosine" )[ "fields" ] == fields
    assert "fields" not in low.to_hint_dict( 0.6, "cosine" ) and "fields" not in plain.to_hint_dict( 0.6, "cosine" )


def test_record_forecast_stores_fields_and_result_from_row_restores_them( engine, monkeypatch ):
    stored = {}

    class Repo:
        def __init__( self, session ): pass
        def log_prediction( self, **kwargs ): stored.update( kwargs )

    @contextmanager
    def fake_db():
        yield SimpleNamespace( commit=lambda: None )

    monkeypatch.setattr( "cosa.rest.db.database.get_db", fake_db )
    monkeypatch.setattr( "cosa.rest.db.repositories.prediction_log_repository.PredictionLogRepository", Repo )
    fields = { "Approach": { "candidate": "Proceed", "confidence": 0.9, "cases": 3 } }
    result = PredictionResult( "multiple_choice", "c", "cbr_majority_vote", predicted_value={ "answers": { "Approach": "Proceed" } }, confidence=0.9, fields=fields )
    assert engine.record_forecast( str( uuid.uuid4() ), { "message": "m", "response_type": "multiple_choice" }, result ) is True
    assert stored[ "ledger" ][ "field_forecasts" ] == fields
    assert engine.record_forecast( str( uuid.uuid4() ), { "message": "m", "response_type": "multiple_choice" }, None, abstention_reason="x" ) is True
    assert stored[ "ledger" ][ "field_forecasts" ] is None
    row = SimpleNamespace( predicted_value={ "answers": { "Approach": "Proceed" } }, response_type="multiple_choice", category="c",
                           prediction_strategy="cbr_majority_vote", prediction_confidence=0.9, similar_case_count=3,
                           field_forecasts=fields, original_message="m", batch_question_key=None, evidence_ids=None, evidence_scores=None )
    assert PredictionEngine._result_from_row( row ).fields == fields


def test_config_version_changes_only_when_the_switch_is_on( engine ):
    engine.per_field_mc_enabled = False
    off = engine.config_version()
    engine.per_field_mc_enabled = True
    on  = engine.config_version()
    assert off != on


def test_the_switch_is_off_by_default_and_read_from_the_ini():
    assert cfg.DEFAULT_PER_FIELD_MC_ENABLED is False
    PredictionEngine.reset()
    assert PredictionEngine( debug=False ).per_field_mc_enabled is False
    PredictionEngine.reset()

    class Cfg:
        def get( self, key, default=None, return_type=None ):
            if key == "prediction engine per field multiple choice enabled": return True
            return { "boolean": False, "int": 5, "float": 0.5 }.get( return_type, default )

    eng = PredictionEngine( config_mgr=Cfg() )
    assert eng.per_field_mc_enabled is True
    PredictionEngine.reset()


# ---- scoring: the typed Other outcome, abstained fields, coverage ------------

def test_offered_labels_reads_stripped_labels_and_tolerates_a_bad_field():
    assert offered_labels( { "options": [ { "label": " Proceed " }, { "label": 3 }, "x", {} ] } ) == { "Proceed" }
    assert offered_labels( { "options": "nope" } ) == set() and offered_labels( {} ) == set()


def test_score_field_without_per_field_has_no_outcome_key():
    assert "outcome" not in score_field( CURRENT[ "questions" ][ 0 ], "Proceed", "Proceed" )


def test_score_field_names_exact_miss_and_other_write_in():
    field = CURRENT[ "questions" ][ 0 ]
    assert score_field( field, "Proceed", "Proceed", per_field=True )[ "outcome" ] == "exact"
    assert score_field( field, "Proceed", "Skip", per_field=True )[ "outcome" ] == "miss"
    typed = score_field( field, "Proceed", "do it differently", per_field=True )
    assert typed[ "outcome" ] == "other_write_in" and typed[ "exact" ] is False


def test_score_field_other_needs_a_schema_that_lists_options_and_catches_a_multi_select_write_in():
    assert score_field( { "header": "H" }, "a", "typed", per_field=True )[ "outcome" ] == "miss"
    multi = CURRENT[ "questions" ][ 1 ]
    assert score_field( multi, [ "A" ], [ "A", "typed" ], per_field=True )[ "outcome" ] == "other_write_in"
    assert score_field( multi, [ "A" ], [ "A" ], per_field=True )[ "outcome" ] == "exact"


def test_other_write_in_is_not_a_miss_and_is_left_out_of_the_total():
    match, detail = compare_multiple_choice(
        { "answers": { "Approach": "Proceed", "Tags": [ "A" ] } },
        { "answers": { "Approach": "typed", "Tags": [ "A" ] } }, CURRENT, per_field=True )
    assert match is True
    assert ( detail[ "matches" ], detail[ "total" ], detail[ "other_write_in" ], detail[ "abstained" ] ) == ( 1, 1, 1, 0 )


def test_an_abstained_field_is_left_out_of_total_and_coverage_is_reported():
    match, detail = compare_multiple_choice(
        { "answers": { "Approach": "Proceed" } },
        { "answers": { "Approach": "Skip", "Tags": [ "A" ] } }, CURRENT, per_field=True )
    assert match is False
    assert ( detail[ "matches" ], detail[ "total" ], detail[ "abstained" ], detail[ "field_coverage" ] ) == ( 0, 1, 1, 0.5 )
    assert [ f[ "abstained" ] for f in detail[ "fields" ] ] == [ False, True ]


def test_a_card_with_nothing_left_to_score_is_not_scored():
    match, detail = compare_multiple_choice(
        { "answers": { "Approach": "Proceed" } },
        { "answers": { "Approach": "typed", "Tags": [ "A" ] } }, CURRENT, per_field=True )
    assert match is None and detail[ "total" ] == 0 and detail[ "other_write_in" ] == 1 and detail[ "abstained" ] == 1


def test_an_abstained_typed_other_is_reported_as_other_with_abstained_true():
    _, detail = compare_multiple_choice(
        { "answers": { "Tags": [ "A" ] } },
        { "answers": { "Approach": "typed", "Tags": [ "A" ] } }, CURRENT, per_field=True )
    approach = detail[ "fields" ][ 0 ]
    assert approach[ "outcome" ] == "other_write_in" and approach[ "abstained" ] is True
    assert ( detail[ "other_write_in" ], detail[ "total" ], detail[ "matches" ] ) == ( 1, 1, 1 )


def test_per_field_scoring_with_a_malformed_schema_reports_it():
    _, detail = compare_multiple_choice( { "answers": { "H": "a" } }, { "answers": { "H": "a" } }, "nonsense", per_field=True )
    assert detail[ "schema_reason" ] == "malformed_schema" and detail[ "matches" ] == 1


def test_whole_card_scoring_is_unchanged_with_the_switch_off():
    match, detail = compare_multiple_choice(
        { "answers": { "Approach": "Proceed" } },
        { "answers": { "Approach": "typed", "Tags": [ "A" ] } }, CURRENT )
    assert match is False and ( detail[ "matches" ], detail[ "total" ] ) == ( 0, 2 ) and "other_write_in" not in detail


def test_get_comparator_passes_per_field_through():
    comparator = get_comparator( "multiple_choice", response_options=CURRENT, per_field=True )
    assert comparator.keywords[ "per_field" ] is True
    assert "per_field" not in get_comparator( "multiple_choice", response_options=CURRENT ).keywords


def test_record_outcome_scores_per_field_when_the_switch_is_on( engine, monkeypatch ):
    seen = {}

    class Repo:
        def __init__( self, session ): pass
        def update_outcome( self, **kwargs ): seen.update( kwargs ); return True

    @contextmanager
    def fake_db():
        yield SimpleNamespace( commit=lambda: None )

    monkeypatch.setattr( "cosa.rest.db.database.get_db", fake_db )
    monkeypatch.setattr( "cosa.rest.db.repositories.prediction_log_repository.PredictionLogRepository", Repo )
    monkeypatch.setattr( engine, "_store_decision", lambda *a, **k: None )
    result = PredictionResult( "multiple_choice", "c", "cbr_majority_vote", predicted_value={ "answers": { "Approach": "Proceed" } }, confidence=0.9 )
    engine.record_outcome( str( uuid.uuid4() ), result, json.dumps( { "answers": { "Approach": "typed", "Tags": [ "A" ] } } ), "multiple_choice", None, CURRENT )
    assert seen[ "accuracy_match" ] is None and seen[ "accuracy_detail" ][ "other_write_in" ] == 1


# ---- review fixes: coverage of an answered typed Other, the half tie, headers that normalise alike ----

def test_an_answered_field_that_turned_out_to_be_a_typed_other_is_outside_coverage():
    match, detail = compare_multiple_choice(
        { "answers": { "Approach": "Proceed", "Tags": [ "A" ] } },
        { "answers": { "Approach": "typed", "Tags": [ "A" ] } }, CURRENT, per_field=True )
    approach = detail[ "fields" ][ 0 ]
    assert approach[ "outcome" ] == "other_write_in" and approach[ "abstained" ] is False
    assert ( detail[ "abstained" ], detail[ "other_write_in" ], detail[ "total" ], detail[ "field_coverage" ] ) == ( 0, 1, 1, 0.5 )


def test_a_multi_select_option_chosen_by_exactly_half_of_its_offerers_is_included( engine, monkeypatch ):
    cases = [ _case( "n1", { "Approach": "Proceed", "Tags": [ "A", "B" ] } ), _case( "n2", { "Approach": "Proceed", "Tags": [ "A" ] } ) ]
    _wire( engine, monkeypatch, cases, { "n1": CURRENT, "n2": CURRENT } )
    assert _predict( engine ).fields[ "Tags" ][ "candidate" ] == [ "A", "B" ]      # B: 1 of 2 = 0.5, the boundary is in


def test_a_multi_select_option_just_under_half_is_left_out( engine, monkeypatch ):
    cases = [ _case( "n1", { "Approach": "Proceed", "Tags": [ "A", "B" ] } ), _case( "n2", { "Approach": "Proceed", "Tags": [ "A" ] } ),
              _case( "n3", { "Approach": "Proceed", "Tags": [ "A" ] } ) ]
    _wire( engine, monkeypatch, cases, { n: CURRENT for n in ( "n1", "n2", "n3" ) } )
    assert _predict( engine ).fields[ "Tags" ][ "candidate" ] == [ "A" ]           # B: 1 of 3


def test_typed_other_in_exactly_half_of_the_neighbours_abstains_a_single_select( engine, monkeypatch ):
    cases = [ _case( "n1", { "Approach": "typed", "Tags": [ "A" ] } ), _case( "n2", { "Approach": "Proceed", "Tags": [ "A" ] } ) ]
    _wire( engine, monkeypatch, cases, { "n1": CURRENT, "n2": CURRENT } )
    assert _predict( engine ).fields[ "Approach" ][ "candidate" ] == "Proceed"     # other mass 1 does not exceed the winner's 1


def test_two_headers_that_normalise_alike_both_stay_in_the_options_and_in_fields( engine, monkeypatch ):
    twin = _card( ( "Mode", False, [ "x", "y" ] ), ( "mode:", False, [ "p", "q" ] ), ( "Tags", True, [ "A", "B", "C" ] ) )
    parsed = PredictionEngine._extract_valid_options( twin, normalise=True )
    assert [ info[ "header" ] for info in parsed.values() ] == [ "Mode", "mode:", "Tags" ] and all( parsed[ k ][ "ambiguous" ] for k in list( parsed )[ :2 ] )
    cases = [ _case( "n1", { "Mode": "x", "Tags": [ "A" ] } ) ]
    _wire( engine, monkeypatch, cases, { "n1": twin } )
    result = _predict( engine, twin )
    assert result.fields[ "Mode" ] == { "reason": "ambiguous_labels" } and result.fields[ "mode:" ] == { "reason": "ambiguous_labels" }
    assert result.fields[ "Tags" ][ "candidate" ] == [ "A" ] and result.metadata[ "abstained" ] == [ "Mode", "mode:" ]
