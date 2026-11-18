#!/usr/bin/env python3
"""
Unit tests for the prediction engine's retrieval metric switch.

The INI key ``prediction engine retrieval metric`` chooses how the engine's three neighbour
searches rank cases. It stays ``dot`` until the replay harness retunes the floors. All mocked,
no DB or server, so :7999-eligible.
"""

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

    def test_committed_ini_value_is_dot( self ):
        root = cu.get_project_root()
        assert _ini_value( root + "/src/conf/lupin-app.ini", "prediction engine retrieval metric" ) == "dot"

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
