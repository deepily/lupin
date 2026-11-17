#!/usr/bin/env python3
"""
Unit tests for the BLR feature vector and its recent error rate.
"""

import time

import numpy as np
import pytest

from cosa.agents.decision_proxy.trust_tracker import CategoryTrust


def _fill( cat, successes, rejections ):
    now = time.time()
    for i in range( successes ):
        cat.record_decision( success=True, timestamp=now - i )
    for i in range( rejections ):
        cat.record_decision( success=False, timestamp=now - successes - i )


class TestRecentErrorRate:

    def test_empty_history_is_zero( self ):
        assert CategoryTrust( "x" ).recent_error_rate() == 0.0

    def test_counts_rejections_in_the_latest_window_only( self ):
        cat = CategoryTrust( "x" )
        now = time.time()
        for i in range( 10 ): cat.record_decision( False, timestamp=now - 100 - i )   # old rejections
        for i in range( 4 ):  cat.record_decision( True,  timestamp=now - i )         # 4 newest successes
        cat.record_decision( False, timestamp=now + 1 )                                # newest: a rejection
        assert cat.recent_error_rate( window=5 ) == pytest.approx( 1 / 5 )
        assert cat.recent_error_rate( window=100 ) == pytest.approx( 11 / 15 )


class TestFeatureThree:

    def test_feature_three_carries_the_caller_rate( self ):
        vec = CategoryTrust.build_feature_vector( "a b", category_index=1, hour_of_day=6, recent_error_rate=0.25 )
        assert vec[ 3 ] == 0.25

    def test_default_rate_is_zero( self ):
        assert CategoryTrust.build_feature_vector( "a", 0, 0 )[ 3 ] == 0.0

    def test_blr_sees_a_varying_fourth_feature( self ):
        cat = CategoryTrust( "x", trust_model="blr" )
        for ok, rate in [ ( True, 0.0 ), ( False, 0.9 ) ]:
            vec = CategoryTrust.build_feature_vector( "q", 0, 12, recent_error_rate=rate )
            cat.record_decision_with_features( ok, vec )
        assert cat._blr_model is not None
