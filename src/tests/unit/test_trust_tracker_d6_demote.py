#!/usr/bin/env python3
"""
Unit tests for demote() on the beta and BLR trust models (trust tracker demotion).
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


class TestDemoteBeta:

    def test_demote_lowers_beta_level_by_one( self ):
        cat = CategoryTrust( "x", trust_model="beta" )
        _fill( cat, 120, 2 )
        before = cat.level
        assert before >= 3
        cat.demote( levels=1 )
        assert cat.level == before - 1

    def test_demote_keeps_rejections_and_syncs_total( self ):
        cat = CategoryTrust( "x", trust_model="beta" )
        _fill( cat, 120, 2 )
        cat.demote( levels=1 )
        assert cat.total_rejections == 2
        assert cat.total_decisions == cat.total_successes + 2
        assert cat.total_successes < 120

    def test_demote_to_l1( self ):
        cat = CategoryTrust( "x", trust_model="beta" )
        _fill( cat, 120, 2 )
        cat.demote( levels=9 )
        assert cat.level == 1
        assert cat.decisions == []


class TestDemoteBlr:

    def test_demote_drops_blr_model_and_lowers_level( self ):
        cat = CategoryTrust( "x", trust_model="blr" )
        now = time.time()
        for i in range( 120 ):
            vec = CategoryTrust.build_feature_vector( "q", 0, 12, recent_error_rate=0.0 )
            cat.record_decision_with_features( True, vec, timestamp=now - i )
        assert cat._blr_model is not None
        before = cat.level
        assert before >= 2
        cat.demote( levels=1 )
        assert cat._blr_model is None
        assert cat.level == before - 1


def test_count_model_demote_leaves_counters_alone():
    cat = CategoryTrust( "x", l2_threshold=2, l3_threshold=4, l4_threshold=6, l5_threshold=8 )
    _fill( cat, 5, 0 )
    cat.demote( levels=1 )
    assert cat.total_successes == 5


class TestDemoteLandsOnTheTarget:

    @pytest.mark.parametrize( "model", [ "beta", "blr" ] )
    @pytest.mark.parametrize( "levels", [ 1, 2 ] )
    def test_demote_k_lands_exactly_k_levels_down( self, model, levels ):
        cat = CategoryTrust( "x", trust_model=model )
        now = time.time()
        for i in range( 400 ):
            vec = CategoryTrust.build_feature_vector( "q", 0, 12 )
            cat.record_decision_with_features( True, vec, timestamp=now - i )
        before = cat.level
        assert before >= 4
        cat.demote( levels=levels )
        assert cat.level == before - levels

    def test_a_new_decision_after_demote_does_not_drop_the_level_further( self ):
        cat = CategoryTrust( "x", trust_model="blr" )
        now = time.time()
        for i in range( 400 ):
            cat.record_decision_with_features( True, CategoryTrust.build_feature_vector( "q", 0, 12 ), timestamp=now - i )
        cat.demote( levels=1 )
        landed = cat.level
        cat.record_decision_with_features( True, CategoryTrust.build_feature_vector( "q", 0, 12 ) )
        assert cat._blr_model is not None and cat._blr_model.n_observations == 1
        assert cat.level >= landed      # one success can only raise it
