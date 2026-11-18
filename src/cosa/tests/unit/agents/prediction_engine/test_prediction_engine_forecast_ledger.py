"""
Unit tests for the ask-time forecast ledger on PredictionEngine and its evidence recorder.

The rows are written by the real PredictionLogRepository (its log_prediction and update_outcome run);
only storage is replaced, by a dict keyed on notification id. So the one-row-per-notification rule and the
refusal of a second outcome are decided by the real repository code, not by the fake.

Restart: a unit test asks, clears the router's pending map, builds a new engine, then answers.
"""
import threading
import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from cosa.agents.prediction_engine import config as cfg
from cosa.agents.prediction_engine import evidence_recorder
from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
from cosa.agents.prediction_engine.prediction_result import PredictionResult
from cosa.rest.db.repositories.prediction_log_repository import PredictionLogRepository
from cosa.rest.postgres_models import PredictionLog


_NID = "12345678-1234-5678-1234-567812345678"


class _Store( dict ):
    """notification_id -> PredictionLog, shared by every repository the fake get_db hands out."""


class _MemoryRepo( PredictionLogRepository ):
    """The real repository with storage swapped for a dict. create() keeps the unique constraint."""

    rows = None

    def create( self, **kwargs ):
        key = kwargs[ "notification_id" ]
        if key in self.rows: raise IntegrityError( "INSERT", {}, Exception( "uq_prediction_log_notification_id" ) )
        entity = PredictionLog( **kwargs )
        self.rows[ key ] = entity
        return entity

    def get_by_notification_id( self, notification_id, for_update=False ):
        return self.rows.get( uuid.UUID( notification_id ) )


class _Session:
    def __init__( self ): self.commits = 0
    def commit( self ):   self.commits += 1
    def flush( self ):    pass


class _Ctx:
    def __init__( self, session ): self._s = session
    def __enter__( self ):         return self._s
    def __exit__( self, *_e ):     return False


@pytest.fixture
def rows( monkeypatch ):
    store = _Store()
    sess  = _Session()

    class _Repo( _MemoryRepo ):
        pass
    _Repo.rows = store

    monkeypatch.setattr( "cosa.rest.db.database.get_db", lambda: _Ctx( sess ) )
    monkeypatch.setattr( "cosa.rest.db.repositories.prediction_log_repository.PredictionLogRepository",
                         lambda session: _Repo( session ) )
    store.session = sess
    return store


class _Provider:
    def generate_embedding( self, text, content_type="prose" ): return [ 0.1, 0.2, 0.3 ]


class _CaseStore:
    def __init__( self, cases=None ):
        self.cases = cases or []
        self.added = []
    def find_similar( self, **kw ): return self.cases
    def add_decision( self, **kw ): self.added.append( kw )


@pytest.fixture
def engine():
    PredictionEngine.reset()
    eng = PredictionEngine( debug=True )
    eng._embedding_provider = _Provider()
    yield eng
    PredictionEngine.reset()


def _result( **over ):
    kw = dict( response_type="yes_no", category="permission", strategy=cfg.STRATEGY_CBR_MAJORITY,
               predicted_value="yes", confidence=0.8, similar_case_count=2,
               metadata={ "evidence_ids": [ "c1", "c2" ], "evidence_scores": [ 91.0, 80.5 ], "latency_ms": 12.3,
                          "original_message": "Deploy?" } )
    kw.update( over )
    return PredictionResult( **kw )


_ND = { "message": "Deploy?", "response_type": "yes_no", "sender_id": "claude.code@lupin.deepily.ai#abc" }


class TestEvidenceRecorder:

    def test_notes_each_case_in_order_and_collect_clears( self ):
        evidence_recorder.begin()
        evidence_recorder.note( [ ( 90.123456, { "id": "a" } ), ( 80.0, { "id": "b" } ) ] )
        evidence_recorder.note( [ ( 70.0, { "id": "c" } ) ] )
        assert evidence_recorder.collect() == ( [ "a", "b", "c" ], [ 90.1235, 80.0, 70.0 ] )
        assert evidence_recorder.collect() == ( [], [] )

    def test_begin_drops_what_an_earlier_ask_left( self ):
        evidence_recorder.begin()
        evidence_recorder.note( [ ( 1.0, { "id": "old" } ) ] )
        evidence_recorder.begin()
        assert evidence_recorder.collect() == ( [], [] )

    def test_a_thread_that_never_began_records_and_returns_nothing( self ):
        out = {}
        def work():
            evidence_recorder.note( [ ( 1.0, { "id": "x" } ) ] )
            out[ "got" ] = evidence_recorder.collect()
        t = threading.Thread( target=work ); t.start(); t.join()
        assert out[ "got" ] == ( [], [] )

    def test_threads_do_not_see_each_others_evidence( self ):
        evidence_recorder.begin()
        evidence_recorder.note( [ ( 1.0, { "id": "mine" } ) ] )
        out = {}
        def work():
            evidence_recorder.begin()
            evidence_recorder.note( [ ( 2.0, { "id": "theirs" } ) ] )
            out[ "got" ] = evidence_recorder.collect()
        t = threading.Thread( target=work ); t.start(); t.join()
        assert out[ "got" ] == ( [ "theirs" ], [ 2.0 ] )
        assert evidence_recorder.collect() == ( [ "mine" ], [ 1.0 ] )


class TestPredictStampsTheEvidence:

    def test_a_real_retrieval_leaves_its_case_ids_and_scores_on_the_result( self, engine, monkeypatch ):
        cases = [ ( 95.0, { "id": "c1", "decision_value": "yes" } ), ( 80.0, { "id": "c2", "decision_value": "yes" } ) ]
        monkeypatch.setattr( engine, "_get_embedding_store", lambda: _CaseStore( cases ) )
        monkeypatch.setattr( engine.classifier, "classify", lambda m, sender_id=None: ( "permission", 1.0 ) )
        r = engine.predict( { "message": "Deploy?", "response_type": "yes_no" } )
        assert r.metadata[ "evidence_ids" ]    == [ "c1", "c2" ]
        assert r.metadata[ "evidence_scores" ] == [ 95.0, 80.0 ]
        assert r.metadata[ "latency_ms" ] >= 0.0

    def test_an_ask_that_retrieved_nothing_stores_empty_lists( self, engine, monkeypatch ):
        monkeypatch.setattr( engine, "_get_embedding_store", lambda: _CaseStore( [] ) )
        monkeypatch.setattr( engine.classifier, "classify", lambda m, sender_id=None: ( "permission", 1.0 ) )
        r = engine.predict( { "message": "Deploy?", "response_type": "yes_no" } )
        assert ( r.metadata[ "evidence_ids" ], r.metadata[ "evidence_scores" ] ) == ( [], [] )

    def test_a_result_with_no_metadata_gets_a_dict( self, engine, monkeypatch ):
        bare = PredictionResult( response_type="yes_no", category="c", strategy=cfg.STRATEGY_COLD_START, metadata=None )
        monkeypatch.setattr( engine, "_predict_core", lambda nd, query_vector=None: bare )
        assert engine.predict( _ND ).metadata[ "evidence_ids" ] == []

    def test_the_second_ask_on_a_thread_does_not_inherit_the_first_asks_evidence( self, engine, monkeypatch ):
        monkeypatch.setattr( engine.classifier, "classify", lambda m, sender_id=None: ( "permission", 1.0 ) )
        monkeypatch.setattr( engine, "_get_embedding_store",
                             lambda: _CaseStore( [ ( 95.0, { "id": "c1", "decision_value": "yes" } ) ] ) )
        engine.predict( { "message": "first", "response_type": "yes_no" } )
        monkeypatch.setattr( engine, "_get_embedding_store", lambda: _CaseStore( [] ) )
        second = engine.predict( { "message": "second", "response_type": "yes_no" } )
        assert second.metadata[ "evidence_ids" ] == []


class TestAlwaysYesRate:

    def test_the_engine_returns_what_the_repository_counts( self, engine, monkeypatch ):
        calls = []
        class _Repo:
            def __init__( self, session ): pass
            def always_yes_counts( self, recipient_id ):
                calls.append( recipient_id )
                return { "yes": 3, "n": 4, "rate": 0.75 }
        monkeypatch.setattr( "cosa.rest.db.database.get_db", lambda: _Ctx( _Session() ) )
        monkeypatch.setattr( "cosa.rest.db.repositories.prediction_log_repository.PredictionLogRepository", _Repo )
        assert engine.always_yes_rate( "u-1" ) == { "yes": 3, "n": 4, "rate": 0.75 }
        assert calls == [ "u-1" ]

    def test_a_failure_returns_none_and_never_raises( self, engine, monkeypatch ):
        def boom(): raise RuntimeError( "db down" )
        monkeypatch.setattr( "cosa.rest.db.database.get_db", boom )
        assert engine.always_yes_rate( "u-1" ) is None

    def test_the_forecast_row_stores_the_rate_it_is_given( self, engine, rows ):
        rate = { "yes": 52, "n": 59, "rate": 0.8814 }
        engine.record_forecast( _NID, _ND, prediction_result=_result(), display_decision="ready", always_yes_rate=rate )
        row = rows[ uuid.UUID( _NID ) ]
        assert row.always_yes_rate == rate and row.display_decision == "ready"

    def test_a_forecast_without_a_rate_stores_none( self, engine, rows ):
        engine.record_forecast( _NID, _ND, prediction_result=_result() )
        assert rows[ uuid.UUID( _NID ) ].always_yes_rate is None


class TestConfigVersion:

    def test_the_same_settings_give_the_same_version_and_a_changed_one_differs( self, engine ):
        first = engine.config_version()
        assert len( first ) == 12 and engine.config_version() == first
        engine.cbr_top_k += 1
        assert engine.config_version() != first

    def test_the_retrieval_metric_changes_the_version( self, engine ):
        first = engine.config_version()
        engine.retrieval_metric = "cosine"
        assert engine.config_version() != first

    def test_the_calibration_switch_changes_the_version( self, engine ):
        first = engine.config_version()
        engine.calibration_enabled = True
        assert engine.config_version() != first


class TestRecordForecast:

    def test_a_forecast_stores_its_value_evidence_and_ledger_fields( self, engine, rows ):
        assert engine.record_forecast( _NID, _ND, prediction_result=_result(), display_decision="shown",
                                       owner_email="rick@example.com" ) is True
        row = rows[ uuid.UUID( _NID ) ]
        assert ( row.response_type, row.category, row.prediction_strategy ) == ( "yes_no", "permission", cfg.STRATEGY_CBR_MAJORITY )
        assert row.predicted_value == { "value": "yes" }
        assert ( row.prediction_confidence, row.similar_case_count ) == ( 0.8, 2 )
        assert row.evidence_ids == [ "c1", "c2" ] and row.evidence_scores == [ 91.0, 80.5 ]
        assert row.latency_ms == 12.3
        assert row.sender_id == _ND[ "sender_id" ]
        assert row.owner_email == "rick@example.com" and row.display_decision == "shown"
        assert row.forecast_source == cfg.FORECAST_SOURCE_FOUNDATION
        assert row.predictor_version == cfg.PREDICTOR_VERSION and row.config_version == engine.config_version()
        assert row.original_message == "Deploy?" and row.abstention_reason is None
        assert row.asked_at is not None and row.forecast_ready_at is not None
        assert row.rendered_at is None and row.fold_opened_at is None
        assert set( row.code_identity ) >= { "git_sha", "imported_at" }
        assert rows.session.commits == 1

    def test_a_cold_start_names_its_abstention_reason( self, engine, rows ):
        cold = PredictionResult( response_type="yes_no", category="permission", strategy=cfg.STRATEGY_COLD_START,
                                 metadata={ "reason": "no_similar_cases" } )
        engine.record_forecast( _NID, _ND, prediction_result=cold )
        row = rows[ uuid.UUID( _NID ) ]
        assert row.abstention_reason == "no_similar_cases" and row.predicted_value is None

    def test_a_prediction_error_result_is_stored_as_a_predictor_error_naming_the_class( self, engine, rows, monkeypatch ):
        def boom( *a, **k ): raise KeyError( "handler-fail" )
        monkeypatch.setattr( engine, "_predict_yes_no", boom )
        monkeypatch.setattr( engine, "_get_embedding_store", lambda: _CaseStore() )
        monkeypatch.setattr( engine.classifier, "classify", lambda m, sender_id=None: ( "permission", 1.0 ) )
        result = engine.predict( { "message": "Deploy?", "response_type": "yes_no" } )
        engine.record_forecast( _NID, _ND, prediction_result=result )
        row = rows[ uuid.UUID( _NID ) ]
        assert row.abstention_reason == "predictor_error: KeyError"
        assert row.prediction_strategy == cfg.STRATEGY_ERROR and row.predicted_value is None
        assert row.category == "permission"

    def test_the_callers_abstention_reason_beats_the_results( self, engine, rows ):
        engine.record_forecast( _NID, _ND, prediction_result=_result(), abstention_reason="caller says" )
        assert rows[ uuid.UUID( _NID ) ].abstention_reason == "caller says"

    def test_a_batch_forecast_keeps_its_question_key( self, engine, rows ):
        batch = _result( metadata={ "batch_question_key": "KEY-TEXT" } )
        engine.record_forecast( _NID, _ND, prediction_result=batch )
        assert rows[ uuid.UUID( _NID ) ].batch_question_key == "KEY-TEXT"

    def test_no_result_writes_the_stated_filler_values_and_the_classifiers_category( self, engine, rows, monkeypatch ):
        monkeypatch.setattr( engine.classifier, "classify", lambda m, sender_id=None: ( "decision", 0.9 ) )
        engine.record_forecast( _NID, _ND, strategy=cfg.STRATEGY_ERROR, abstention_reason="predictor_error: RuntimeError" )
        row = rows[ uuid.UUID( _NID ) ]
        assert ( row.prediction_strategy, row.prediction_confidence, row.similar_case_count ) == ( "error", 0.0, 0 )
        assert row.category == "decision" and row.predicted_value is None
        assert row.abstention_reason == "predictor_error: RuntimeError"

    def test_a_failing_classifier_gives_the_category_unknown( self, engine, rows, monkeypatch ):
        def boom( *a, **k ): raise RuntimeError( "classifier down" )
        monkeypatch.setattr( engine.classifier, "classify", boom )
        assert engine.record_forecast( _NID, _ND, strategy=cfg.STRATEGY_TEST_OVERRIDE,
                                       forecast_source=cfg.FORECAST_SOURCE_TEST_OVERRIDE ) is True
        row = rows[ uuid.UUID( _NID ) ]
        assert row.category == "unknown" and row.forecast_source == "test_override"

    def test_a_second_forecast_for_one_notification_is_refused_and_the_first_stands( self, engine, rows ):
        assert engine.record_forecast( _NID, _ND, prediction_result=_result() ) is True
        assert engine.record_forecast( _NID, _ND, prediction_result=_result( predicted_value="no" ) ) is False
        assert len( rows ) == 1 and rows[ uuid.UUID( _NID ) ].predicted_value == { "value": "yes" }

    def test_a_database_failure_returns_false_and_never_raises( self, engine, monkeypatch ):
        def boom(): raise RuntimeError( "db down" )
        monkeypatch.setattr( "cosa.rest.db.database.get_db", boom )
        assert engine.record_forecast( _NID, _ND, prediction_result=_result() ) is False


class TestAttachingTheAnswerFromTheStoredRow:

    def test_a_restart_between_ask_and_answer_still_gives_one_outcome_row_and_one_case( self, rows, monkeypatch ):
        PredictionEngine.reset()
        asking = PredictionEngine( debug=True )
        asking.record_forecast( _NID, _ND, prediction_result=_result() )

        import cosa.rest.routers.notifications as notifications
        notifications.pending_responses.clear()          # what a restart loses
        PredictionEngine.reset()
        fresh = PredictionEngine( debug=True )           # a new engine with no memory of the ask
        store = _CaseStore()
        monkeypatch.setattr( fresh, "_get_embedding_store", lambda: store )
        fresh._embedding_provider = _Provider()

        assert fresh.record_outcome_from_ledger( _NID, "yes", { "user_id": "u1", "method": "x" } ) is True

        row = rows[ uuid.UUID( _NID ) ]
        assert len( rows ) == 1
        assert row.actual_value == { "value": "yes" } and row.accuracy_match is True and row.responded_at is not None
        assert len( store.added ) == 1 and store.added[ 0 ][ "question" ] == "Deploy?"
        assert store.added[ 0 ][ "owner_user_id" ] == "u1"
        PredictionEngine.reset()

    def test_a_wrong_prediction_is_scored_against_the_rebuilt_row( self, engine, rows, monkeypatch ):
        engine.record_forecast( _NID, _ND, prediction_result=_result( predicted_value="no" ) )
        monkeypatch.setattr( engine, "_get_embedding_store", lambda: _CaseStore() )
        engine.record_outcome_from_ledger( _NID, "yes" )
        assert rows[ uuid.UUID( _NID ) ].accuracy_match is False

    def test_the_forecast_qualifier_and_dict_value_survive_the_round_trip( self, engine, rows, monkeypatch ):
        mc = _result( response_type="multiple_choice", predicted_value={ "answers": { "Go": "Yes" } }, predicted_qualifier="but careful" )
        engine.record_forecast( _NID, _ND, prediction_result=mc )
        rebuilt = engine._result_from_row( rows[ uuid.UUID( _NID ) ] )
        assert rebuilt.predicted_value == { "answers": { "Go": "Yes" } }
        assert rebuilt.predicted_qualifier == "but careful"
        assert rebuilt.metadata[ "original_message" ] == "Deploy?"

    def test_a_row_with_no_stored_value_rebuilds_with_none( self, engine, rows ):
        engine.record_forecast( _NID, _ND, strategy=cfg.STRATEGY_ERROR, abstention_reason="predictor_error: X" )
        rebuilt = engine._result_from_row( rows[ uuid.UUID( _NID ) ] )
        assert rebuilt.predicted_value is None and rebuilt.predicted_qualifier is None

    def test_no_row_returns_false_and_writes_nothing( self, engine, rows ):
        assert engine.record_outcome_from_ledger( _NID, "yes" ) is False
        assert len( rows ) == 0

    def test_a_duplicate_callback_leaves_the_first_outcome_and_stores_no_second_case( self, engine, rows, monkeypatch ):
        engine.record_forecast( _NID, _ND, prediction_result=_result() )
        store = _CaseStore()
        monkeypatch.setattr( engine, "_get_embedding_store", lambda: store )
        engine.record_outcome_from_ledger( _NID, "yes" )
        first_at = rows[ uuid.UUID( _NID ) ].responded_at
        engine.record_outcome_from_ledger( _NID, "no" )
        row = rows[ uuid.UUID( _NID ) ]
        assert row.actual_value == { "value": "yes" } and row.responded_at == first_at
        assert len( store.added ) == 1

    def test_a_test_override_row_gets_the_answer_and_no_accuracy_and_no_case( self, engine, rows, monkeypatch ):
        engine.record_forecast( _NID, _ND, forecast_source=cfg.FORECAST_SOURCE_TEST_OVERRIDE,
                                strategy=cfg.STRATEGY_TEST_OVERRIDE, abstention_reason="test_override" )
        store = _CaseStore()
        monkeypatch.setattr( engine, "_get_embedding_store", lambda: store )
        assert engine.record_outcome_from_ledger( _NID, { "value": "yes" } ) is True
        row = rows[ uuid.UUID( _NID ) ]
        assert row.actual_value == { "value": "yes" } and row.accuracy_match is None and row.responded_at is not None
        assert store.added == []

    def test_a_test_override_answer_that_is_not_a_dict_is_wrapped( self, engine, rows ):
        engine.record_forecast( _NID, _ND, forecast_source=cfg.FORECAST_SOURCE_TEST_OVERRIDE, strategy=cfg.STRATEGY_TEST_OVERRIDE )
        engine.record_outcome_from_ledger( _NID, "yes" )
        assert rows[ uuid.UUID( _NID ) ].actual_value == { "value": "yes" }

    def test_a_second_answer_on_a_test_override_row_is_ignored( self, engine, rows ):
        engine.record_forecast( _NID, _ND, forecast_source=cfg.FORECAST_SOURCE_TEST_OVERRIDE, strategy=cfg.STRATEGY_TEST_OVERRIDE )
        engine.record_outcome_from_ledger( _NID, "yes" )
        assert engine.record_outcome_from_ledger( _NID, "no" ) is True
        assert rows[ uuid.UUID( _NID ) ].actual_value == { "value": "yes" }

    def test_a_database_failure_returns_false( self, engine, monkeypatch ):
        def boom(): raise RuntimeError( "db down" )
        monkeypatch.setattr( "cosa.rest.db.database.get_db", boom )
        assert engine.record_outcome_from_ledger( _NID, "yes" ) is False

    def test_record_outcome_writes_the_row_and_outcome_together_when_the_ask_predates_the_ledger( self, engine, rows, monkeypatch ):
        monkeypatch.setattr( engine, "_get_embedding_store", lambda: _CaseStore() )
        engine.record_outcome( _NID, _result(), "yes", "yes_no" )
        row = rows[ uuid.UUID( _NID ) ]
        assert row.predicted_value == { "value": "yes" } and row.actual_value == { "value": "yes" }
        assert row.forecast_source is None, "a legacy row carries no ledger fields"
