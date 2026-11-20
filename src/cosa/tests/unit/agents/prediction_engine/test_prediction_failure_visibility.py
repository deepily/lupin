"""
Unit tests for the named abstention reasons of silent prediction failures.

Each failure kind is planted as it happens in production. The test reads the row back from the real
PredictionLogRepository. Storage is the ledger test's dict, so the one-row rule is the real one.
No model is called.
"""
import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from cosa.agents.prediction_engine import config as cfg
from cosa.agents.prediction_engine import failure_visibility as fv
from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
from cosa.agents.prediction_engine.prediction_result import PredictionResult
from cosa.tests.unit.agents.prediction_engine.test_prediction_engine_forecast_ledger import (   # noqa: F401  fixtures
    _CaseStore, _Ctx, _ND, _NID, engine, rows )


class _BrokenStore( _CaseStore ):
    """An embedding store whose retrieval raises, as a LanceDB outage does."""
    def find_similar( self, **kw ): raise RuntimeError( "lancedb down" )


def _on( engine ):
    engine.failure_visibility_enabled = True
    return engine


def _plant_classifier( engine, monkeypatch ):
    monkeypatch.setattr( engine.classifier, "classify", lambda m, sender_id=None: ( "permission", 1.0 ) )


def _failure_lines( capsys ):
    return [ line for line in capsys.readouterr().out.splitlines() if line.startswith( fv.FAILURE_LOG_PREFIX ) ]


class TestNaming:

    def test_no_embedding_is_renamed_and_other_reasons_pass_through( self ):
        assert fv.name_failure( "no_embedding" ) == "embedding_missing"
        assert fv.name_failure( "no_similar_cases" ) == "no_similar_cases"
        assert fv.name_failure( "engine_disabled" ) == "engine_disabled"
        assert fv.name_failure( None ) is None

    def test_no_similar_cases_with_a_store_error_names_the_class( self ):
        assert fv.name_failure( "no_similar_cases", "RuntimeError" ) == "store_error: RuntimeError"
        assert fv.name_failure( "no_embedding", "RuntimeError" ) == "embedding_missing"

    @pytest.mark.parametrize( "reason, expected", [
        ( "embedding_missing", True ), ( "store_write_failed", True ), ( "store_error: KeyError", True ),
        ( "no_similar_cases", False ), ( "predictor_error: KeyError", False ), ( None, False ) ] )
    def test_is_failure_reason( self, reason, expected ):
        assert fv.is_failure_reason( reason ) is expected

    def test_log_failure_prints_one_prefixed_line_and_returns_it( self, capsys ):
        line = fv.log_failure( _NID, "embedding_missing" )
        assert capsys.readouterr().out.splitlines() == [ line ]
        assert line == f"[PREDICTION-FAILURE] notification={_NID} reason=embedding_missing"
        assert fv.log_failure( None, "store_write_failed", "OperationalError" ).endswith( "detail=OperationalError" )

    def test_the_switch_is_off_in_the_committed_ini_and_the_default( self ):
        import cosa.utils.util as cu
        ini = open( cu.get_project_root() + "/src/conf/lupin-app.ini" ).read()
        assert "prediction engine failure visibility enabled                = false" in ini
        assert cfg.DEFAULT_FAILURE_VISIBILITY_ENABLED is False
        PredictionEngine.reset()
        assert PredictionEngine().failure_visibility_enabled is False
        PredictionEngine.reset()

    def test_the_switch_is_read_from_the_config_manager( self ):
        class _Cfg:
            def get( self, key, default=None, return_type=None ):
                if key == "prediction engine failure visibility enabled": return True
                return {
                    "int": lambda: int( default ), "float": lambda: float( default ),
                    "boolean": lambda: str( default ).lower() == "true" }.get( return_type, lambda: default )()
        PredictionEngine.reset()
        try: assert PredictionEngine( config_mgr=_Cfg() ).failure_visibility_enabled is True
        finally: PredictionEngine.reset()


class TestEmbeddingMissing:

    def _ask( self, engine, monkeypatch ):
        _plant_classifier( engine, monkeypatch )
        monkeypatch.setattr( engine, "_generate_embedding", lambda text: None )
        return engine.predict( { "message": "Deploy?", "response_type": "yes_no" } )

    def test_a_missing_embedding_writes_one_row_with_its_reason_and_one_log_line( self, engine, rows, monkeypatch, capsys ):
        result = self._ask( _on( engine ), monkeypatch )
        capsys.readouterr()
        assert engine.record_forecast( _NID, _ND, prediction_result=result ) is True
        row = rows[ uuid.UUID( _NID ) ]
        assert len( rows ) == 1 and row.abstention_reason == "embedding_missing" and row.predicted_value is None
        assert _failure_lines( capsys ) == [ f"[PREDICTION-FAILURE] notification={_NID} reason=embedding_missing" ]

    def test_with_the_switch_off_the_old_reason_stays_and_nothing_is_logged( self, engine, rows, monkeypatch, capsys ):
        result = self._ask( engine, monkeypatch )
        capsys.readouterr()
        engine.record_forecast( _NID, _ND, prediction_result=result )
        assert rows[ uuid.UUID( _NID ) ].abstention_reason == "no_embedding"
        assert _failure_lines( capsys ) == []

    def test_an_ordinary_cold_start_is_not_a_failure_and_logs_nothing( self, engine, rows, capsys ):
        cold = PredictionResult( response_type="yes_no", category="permission", strategy=cfg.STRATEGY_COLD_START,
                                 metadata={ "reason": "no_similar_cases" } )
        _on( engine ).record_forecast( _NID, _ND, prediction_result=cold )
        assert rows[ uuid.UUID( _NID ) ].abstention_reason == "no_similar_cases"
        assert _failure_lines( capsys ) == []


class TestStoreError:

    @pytest.mark.parametrize( "message_type, options", [
        ( "yes_no", None ), ( "multiple_choice", { "questions": [ { "header": "H", "options": [ { "label": "A" } ] } ] } ),
        ( "open_ended", None ), ( "open_ended_batch", None ) ] )
    def test_a_swallowed_retrieval_error_writes_its_exception_class( self, engine, rows, monkeypatch, capsys, message_type, options ):
        _on( engine )
        _plant_classifier( engine, monkeypatch )
        monkeypatch.setattr( engine, "_get_embedding_store", lambda: _BrokenStore() )
        monkeypatch.setattr( engine, "_generate_embedding", lambda text: [ 0.1, 0.2 ] )
        result = engine.predict( { "message": "Deploy?", "response_type": message_type, "response_options": options } )
        capsys.readouterr()
        nd = dict( _ND, response_type=message_type )
        assert engine.record_forecast( _NID, nd, prediction_result=result ) is True
        row = rows[ uuid.UUID( _NID ) ]
        assert len( rows ) == 1 and row.abstention_reason == "store_error: RuntimeError"
        assert _failure_lines( capsys ) == [ f"[PREDICTION-FAILURE] notification={_NID} reason=store_error: RuntimeError" ]

    def test_with_the_switch_off_an_outage_still_reads_as_no_similar_cases( self, engine, rows, monkeypatch, capsys ):
        _plant_classifier( engine, monkeypatch )
        monkeypatch.setattr( engine, "_get_embedding_store", lambda: _BrokenStore() )
        monkeypatch.setattr( engine, "_generate_embedding", lambda text: [ 0.1, 0.2 ] )
        result = engine.predict( { "message": "Deploy?", "response_type": "yes_no" } )
        engine.record_forecast( _NID, _ND, prediction_result=result )
        assert rows[ uuid.UUID( _NID ) ].abstention_reason == "no_similar_cases"
        assert _failure_lines( capsys ) == []

    def test_an_empty_store_without_an_error_is_not_a_store_error( self, engine, monkeypatch ):
        _on( engine )
        _plant_classifier( engine, monkeypatch )
        monkeypatch.setattr( engine, "_get_embedding_store", lambda: _CaseStore( [] ) )
        monkeypatch.setattr( engine, "_generate_embedding", lambda text: [ 0.1, 0.2 ] )
        result = engine.predict( { "message": "Deploy?", "response_type": "yes_no" } )
        assert result.metadata[ "reason" ] == "no_similar_cases"


class TestStoreWriteFailed:

    def _fail_first_write( self, monkeypatch, error ):
        """The first get_db() raises `error`; later calls hand back the ledger test's session."""
        from cosa.rest.db import database
        real  = database.get_db
        calls = { "n": 0 }

        def flaky():
            calls[ "n" ] += 1
            if calls[ "n" ] == 1: raise error
            return real()
        monkeypatch.setattr( "cosa.rest.db.database.get_db", flaky )
        return calls

    def test_a_failed_write_logs_once_and_stores_one_bare_row_naming_it( self, engine, rows, monkeypatch, capsys ):
        _on( engine )
        calls = self._fail_first_write( monkeypatch, RuntimeError( "connection reset" ) )
        result = PredictionResult( response_type="yes_no", category="permission", strategy=cfg.STRATEGY_CBR_MAJORITY,
                                   predicted_value="yes", confidence=0.9, similar_case_count=3, metadata={} )
        assert engine.record_forecast( _NID, _ND, prediction_result=result, display_decision="ready" ) is True
        row = rows[ uuid.UUID( _NID ) ]
        assert calls[ "n" ] == 2 and len( rows ) == 1
        assert row.abstention_reason == "store_write_failed" and row.predicted_value is None
        assert row.prediction_strategy == cfg.STRATEGY_ERROR and row.display_decision == "ready"
        assert _failure_lines( capsys ) == [
            f"[PREDICTION-FAILURE] notification={_NID} reason=store_write_failed detail=RuntimeError" ]

    def test_the_retry_failing_too_returns_false_logs_once_and_does_not_retry_again( self, engine, rows, monkeypatch, capsys ):
        _on( engine )
        def boom(): raise RuntimeError( "db down" )
        monkeypatch.setattr( "cosa.rest.db.database.get_db", boom )
        assert engine.record_forecast( _NID, _ND, prediction_result=None ) is False
        assert len( rows ) == 0
        assert len( _failure_lines( capsys ) ) == 1

    def test_a_duplicate_row_is_not_a_failure_and_is_not_retried( self, engine, rows, capsys ):
        _on( engine )
        assert engine.record_forecast( _NID, _ND, strategy=cfg.STRATEGY_ERROR, abstention_reason="x" ) is True
        capsys.readouterr()
        assert engine.record_forecast( _NID, _ND, strategy=cfg.STRATEGY_ERROR, abstention_reason="y" ) is False
        assert rows[ uuid.UUID( _NID ) ].abstention_reason == "x"
        assert _failure_lines( capsys ) == []

    def test_with_the_switch_off_a_failed_write_is_as_it_was( self, engine, rows, monkeypatch, capsys ):
        calls = self._fail_first_write( monkeypatch, RuntimeError( "connection reset" ) )
        assert engine.record_forecast( _NID, _ND, strategy=cfg.STRATEGY_ERROR, abstention_reason="x" ) is False
        assert calls[ "n" ] == 1 and len( rows ) == 0
        assert _failure_lines( capsys ) == []

    def test_a_failed_answer_case_write_is_logged_only_with_the_switch_on( self, engine, monkeypatch, capsys ):
        class _FailingStore( _CaseStore ):
            def add_decision( self, **kw ): raise OSError( "disk full" )
        monkeypatch.setattr( engine, "_get_embedding_store", lambda: _FailingStore() )
        result = PredictionResult( response_type="yes_no", category="permission", strategy=cfg.STRATEGY_CBR_MAJORITY,
                                   predicted_value="yes", confidence=0.9, metadata={ "original_message": "Deploy?" } )
        engine._store_decision( _NID, result, "yes", "yes_no" )
        assert _failure_lines( capsys ) == []
        _on( engine )._store_decision( _NID, result, "yes", "yes_no" )
        assert _failure_lines( capsys ) == [ f"[PREDICTION-FAILURE] notification={_NID} reason=store_write_failed detail=OSError" ]
