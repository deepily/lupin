#!/usr/bin/env python3
"""
Unit tests for the prediction engine's retrieval metric switch.

The INI key ``prediction engine retrieval metric`` chooses how the engine's three neighbour
searches rank cases. The replay retune froze it at ``cosine``, with the floor and top k, in
the committed retune report. All mocked, no DB or server, so :7999-eligible.
"""

import json
import re
from unittest.mock import MagicMock

import pytest

import cosa.utils.util as cu
from cosa.agents.prediction_engine.config import DEFAULT_RETRIEVAL_METRIC, VALID_RETRIEVAL_METRICS
from cosa.agents.prediction_engine.prediction_engine import PredictionEngine


def _engine_with_metric( metric ):
    """Build an engine whose config manager answers the metric key and defaults for the rest."""
    PredictionEngine._instance = None
    cfg = MagicMock()
    cfg.get.side_effect = lambda key, default=None, return_type=None: metric if key == "prediction engine retrieval metric" else default
    return PredictionEngine( config_mgr=cfg )


def _recording_engine( metric ):
    """Engine on `metric` whose store records every find_similar call and returns no cases."""
    engine = _engine_with_metric( metric )
    engine._embedding_store = MagicMock()
    engine._embedding_store.find_similar.return_value = []
    return engine


def _ini_value( path, key ):
    """Return the value of `key` on its single line in an INI file, or None."""
    with open( path ) as handle:
        hits = re.findall( rf"^{re.escape( key )}\s*=\s*(.*?)\s*$", handle.read(), flags=re.MULTILINE )
    assert len( hits ) == 1, f"{key!r} must appear exactly once in {path}, found {len( hits )}"
    return hits[ 0 ]


@pytest.fixture( autouse=True )
def _reset_singleton():
    """Give every test a fresh engine singleton and leave none behind."""
    PredictionEngine._instance = None
    yield
    PredictionEngine._instance = None


class TestRetrievalMetricSwitch:

    def test_committed_ini_values_equal_the_frozen_retune_report( self ):
        root     = cu.get_project_root()
        ini      = root + "/src/conf/lupin-app.ini"
        with open( root + "/src/conf/prediction-retune-report.json", encoding="utf-8" ) as handle: report = json.load( handle )
        frozen   = report[ "frozen_settings" ]
        assert sorted( frozen ) == [ "prediction engine cbr similarity threshold", "prediction engine cbr top k", "prediction engine retrieval metric" ]
        for key, value in frozen.items(): assert _ini_value( ini, key ) == str( value ), key
        assert ( frozen[ "prediction engine cbr similarity threshold" ], frozen[ "prediction engine cbr top k" ], frozen[ "prediction engine retrieval metric" ] ) == ( 0.5, 10, "cosine" )
        assert ( report[ "best_point" ][ "threshold" ], report[ "best_point" ][ "top_k" ] ) == ( 0.5, 10 )
        assert report[ "tune_cohort_sha256" ] == "63f19406bae9696f308504fd7ac35b1de75b240bc04f1949ab6b8d99e8ba87bd"
        assert ( report[ "tune_size" ], report[ "final_size" ], report[ "eligible" ] ) == ( 911, 391, 1302 )

    def test_the_open_ended_keys_are_untouched_by_the_freeze( self ):
        ini = cu.get_project_root() + "/src/conf/lupin-app.ini"
        assert _ini_value( ini, "prediction engine open ended cbr top k" ) == "5"
        assert _ini_value( ini, "prediction engine open ended cbr threshold" ) == "0.85"
        assert _ini_value( ini, "prediction engine open ended match threshold" ) == "0.75"

    def test_key_has_an_explainer( self ):
        root = cu.get_project_root()
        assert _ini_value( root + "/src/conf/lupin-app-splainer.ini", "prediction engine retrieval metric" ).endswith( "Default is dot." )

    def test_default_is_dot_and_valid_set_is_closed( self ):
        assert DEFAULT_RETRIEVAL_METRIC == "dot"
        assert VALID_RETRIEVAL_METRICS == ( "dot", "cosine" )
        assert PredictionEngine().retrieval_metric == "dot"

    @pytest.mark.parametrize( "metric", [ "dot", "cosine" ] )
    def test_ini_value_is_read( self, metric ):
        assert _engine_with_metric( metric ).retrieval_metric == metric

    def test_unknown_metric_fails_loudly_at_construction( self ):
        with pytest.raises( ValueError, match="retrieval metric" ):
            _engine_with_metric( "euclid" )

    @pytest.mark.parametrize( "metric", [ "dot", "cosine" ] )
    def test_yes_no_call_site_passes_the_metric( self, metric ):
        engine = _recording_engine( metric )
        engine._predict_yes_no( "q", "general", [ 0.1 ] )
        assert engine._embedding_store.find_similar.call_args.kwargs[ "metric" ] == metric

    @pytest.mark.parametrize( "metric", [ "dot", "cosine" ] )
    def test_multiple_choice_call_site_passes_the_metric( self, metric ):
        engine = _recording_engine( metric )
        engine._predict_multiple_choice( "q", "general", [ 0.1 ], [ { "label": "a" } ] )
        assert engine._embedding_store.find_similar.call_args.kwargs[ "metric" ] == metric

    @pytest.mark.parametrize( "metric", [ "dot", "cosine" ] )
    def test_open_ended_call_site_passes_the_metric( self, metric ):
        engine = _recording_engine( metric )
        engine._predict_open_ended( "q", "general", [ 0.1 ] )
        assert engine._embedding_store.find_similar.call_args.kwargs[ "metric" ] == metric

    @pytest.mark.parametrize( "metric", [ "dot", "cosine" ] )
    def test_open_ended_batch_call_site_passes_the_metric( self, metric ):
        engine = _recording_engine( metric )
        engine._predict_open_ended_batch( "q", "general", [ 0.1 ] )
        assert engine._embedding_store.find_similar.call_args.kwargs[ "metric" ] == metric


class TestQueryVectorRefusedBecomesTheAbstentionReason:

    def _refusing_engine( self ):
        """Engine on the cosine metric whose store refuses the query vector."""
        from cosa.rest.db.vector_errors import QueryVectorRefused
        engine = _engine_with_metric( "cosine" )
        engine._embedding_store = MagicMock()
        engine._embedding_store.find_similar.side_effect = QueryVectorRefused( "wrong dimension 3 (expected 768)" )
        return engine

    @pytest.mark.parametrize( "call, response_type", [
        ( lambda e: e._predict_yes_no( "q", "general", [ 0.1 ] ),                          "yes_no" ),
        ( lambda e: e._predict_multiple_choice( "q", "general", [ 0.1 ], [ { "label": "a" } ] ), "multiple_choice" ),
        ( lambda e: e._predict_open_ended( "q", "general", [ 0.1 ] ),                      "open_ended" ),
        ( lambda e: e._predict_open_ended_batch( "q", "general", [ 0.1 ] ),                "open_ended_batch" ),
    ] )
    def test_each_call_site_abstains_with_the_named_reason( self, call, response_type ):
        result = call( self._refusing_engine() )
        assert result.strategy == "cold_start"
        assert result.response_type == response_type
        assert result.metadata[ "reason" ] == "query_vector_refused: wrong dimension 3 (expected 768)"
        assert result.predicted_value is None

    def test_an_ordinary_store_error_still_reads_as_no_similar_cases( self ):
        engine = _engine_with_metric( "cosine" )
        engine._embedding_store = MagicMock()
        engine._embedding_store.find_similar.side_effect = RuntimeError( "boom" )
        assert engine._predict_yes_no( "q", "general", [ 0.1 ] ).metadata[ "reason" ] == "no_similar_cases"


class TestConfigVersionCarriesBothSwitches:

    def _version( self, metric, calibration ):
        """Return config_version of an engine whose INI says `metric` and `calibration`."""
        PredictionEngine._instance = None
        values = { "prediction engine retrieval metric": metric, "prediction engine calibration enabled": calibration }
        cfg    = MagicMock()
        cfg.get.side_effect = lambda key, default=None, return_type=None: values.get( key, default )
        return PredictionEngine( config_mgr=cfg ).config_version()

    def test_each_switch_alone_changes_the_version( self ):
        base = self._version( "dot", False )
        assert self._version( "cosine", False ) != base, "the retrieval metric must reach config_version"
        assert self._version( "dot", True ) != base, "the calibration switch must reach config_version"
        assert self._version( "cosine", True ) not in ( base, self._version( "cosine", False ), self._version( "dot", True ) )

    def test_the_ini_values_survive_construction( self ):
        self._version( "cosine", True )
        engine = PredictionEngine()
        assert ( engine.retrieval_metric, engine.calibration_enabled ) == ( "cosine", True )
