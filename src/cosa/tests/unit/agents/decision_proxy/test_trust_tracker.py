#!/usr/bin/env python3
"""
Unit tests for cosa.agents.decision_proxy.trust_tracker.

Covers CategoryTrust (count / beta / blr level models, decay-weighted
effective count, rolling-window prune, demote, serialization) and
TrustTracker (category registry, level lookup, record/demote dispatch,
stats). The scipy.stats.beta.ppf boundary in the beta model is MOCKED —
no real solver is invoked — and the BLR model is mocked where its rate is
asserted. time is controlled via explicit timestamps; no real I/O.
"""

import time
import numpy as np
import pytest
from unittest.mock import patch, MagicMock

from cosa.agents.decision_proxy.trust_tracker import CategoryTrust, TrustTracker


# Low thresholds let count-based levels graduate deterministically from a
# handful of recent successes (weight ≈ 1 when timestamp ≈ now).
SMALL_COUNT_KW = dict(
    trust_model  = "count",
    l2_threshold = 1,
    l3_threshold = 2,
    l4_threshold = 3,
    l5_threshold = 4,
)
LOW_MIN_SAMPLES = { 2: 1, 3: 1, 4: 1, 5: 1 }


def _frozen_time( t=1_000_000.0 ):
    """
    Freeze trust_tracker's clock so the decay weight is exactly 1.0 — i.e. the
    effective decision count equals the integer success count. Without this, the
    micro-elapsed time between record_decision() and a .level read makes eff a
    hair below the integer, dropping the computed level by one.
    """
    return patch( "cosa.agents.decision_proxy.trust_tracker.time.time", return_value=t )


# ============================================================================
# CategoryTrust — construction
# ============================================================================
def test_category_init_defaults_populate_rate_and_samples():
    c = CategoryTrust( "deploy" )
    assert c.category_name == "deploy"
    assert c.cap_level == 5
    assert c.trust_model == "count"
    assert c.thresholds == { 2: 50, 3: 200, 4: 500, 5: 1000 }
    # rate_thresholds / min_samples fall back to module defaults (the `or` arm)
    assert set( c.rate_thresholds.keys() ) == { 2, 3, 4, 5 }
    assert set( c.min_samples.keys() ) == { 2, 3, 4, 5 }
    assert c.decisions == []
    assert c._blr_model is None


def test_category_init_custom_rate_thresholds_and_min_samples():
    rt = { 2: 0.5, 3: 0.6, 4: 0.7, 5: 0.8 }
    ms = { 2: 2, 3: 3, 4: 4, 5: 5 }
    c = CategoryTrust( "deploy", rate_thresholds=rt, min_samples=ms )
    assert c.rate_thresholds is rt
    assert c.min_samples is ms


# ============================================================================
# CategoryTrust — level dispatch + count model
# ============================================================================
def test_level_count_no_decisions_is_one():
    c = CategoryTrust( "x", **SMALL_COUNT_KW )
    assert c.level == 1


def test_level_count_breaks_partway():
    c = CategoryTrust( "x", **SMALL_COUNT_KW )
    with _frozen_time():
        for _ in range( 2 ):
            c.record_decision( True )
        # eff == 2 → >=1 (L2), >=2 (L3), <3 (L4) → break → level 3
        assert c.level == 3


def test_level_count_full_graduation():
    c = CategoryTrust( "x", **SMALL_COUNT_KW )
    with _frozen_time():
        for _ in range( 6 ):
            c.record_decision( True )
        # eff == 6 → all thresholds met → loop completes → level 5
        assert c.level == 5


def test_level_count_capped_at_cap_level():
    c = CategoryTrust( "x", cap_level=2, **SMALL_COUNT_KW )
    with _frozen_time():
        for _ in range( 6 ):
            c.record_decision( True )
        assert c.level == 2


# ============================================================================
# CategoryTrust — beta model (scipy.stats.beta.ppf mocked)
# ============================================================================
def test_level_beta_no_observations_returns_one():
    c = CategoryTrust( "x", trust_model="beta" )
    # n == 0 → early return, ppf never called
    assert c.level == 1


def test_level_beta_graduates_with_high_lower_bound():
    c = CategoryTrust( "x", trust_model="beta", min_samples=LOW_MIN_SAMPLES )
    now = time.time()
    for _ in range( 3 ):
        c.record_decision( True, timestamp=now )
    with patch( "scipy.stats.beta.ppf", return_value=0.99 ):
        assert c.level == 5     # lb 0.99 ≥ all rate thresholds, samples_ok


def test_level_beta_breaks_when_rate_below_threshold():
    c = CategoryTrust( "x", trust_model="beta", min_samples=LOW_MIN_SAMPLES )
    now = time.time()
    for _ in range( 3 ):
        c.record_decision( True, timestamp=now )
    with patch( "scipy.stats.beta.ppf", return_value=0.5 ):
        assert c.level == 1     # 0.5 < L2 rate threshold → break immediately


def test_level_beta_breaks_when_samples_insufficient():
    # default min_samples (L2=20) not met by 3 obs → samples_ok False even if rate ok
    c = CategoryTrust( "x", trust_model="beta" )
    now = time.time()
    for _ in range( 3 ):
        c.record_decision( True, timestamp=now )
    with patch( "scipy.stats.beta.ppf", return_value=0.99 ):
        assert c.level == 1


# ============================================================================
# CategoryTrust — blr model
# ============================================================================
def test_level_blr_falls_back_to_beta_when_few_observations():
    c = CategoryTrust( "x", trust_model="blr" )
    # 0 decisions → n < 30 → _level_beta → n == 0 → 1 (no scipy call)
    assert c.level == 1


def test_level_blr_falls_back_when_model_missing():
    c = CategoryTrust( "x", trust_model="blr", min_samples=LOW_MIN_SAMPLES )
    now = time.time()
    for _ in range( 30 ):
        c.record_decision( True, timestamp=now )      # n >= 30 but _blr_model is None
    with patch( "scipy.stats.beta.ppf", return_value=0.99 ):
        assert c.level == 5     # falls back to beta path


def test_level_blr_uses_posterior_rate_when_ready():
    c = CategoryTrust( "x", trust_model="blr", min_samples=LOW_MIN_SAMPLES )
    now = time.time()
    for _ in range( 30 ):
        c.record_decision( True, timestamp=now )
    c._blr_model = MagicMock()
    c._blr_model.posterior_mean_rate.return_value = 0.99
    level = c.level
    c._blr_model.posterior_mean_rate.assert_called_once()
    assert level == 5


def test_level_blr_breaks_when_posterior_rate_low():
    c = CategoryTrust( "x", trust_model="blr", min_samples=LOW_MIN_SAMPLES )
    now = time.time()
    for _ in range( 30 ):
        c.record_decision( True, timestamp=now )
    c._blr_model = MagicMock()
    c._blr_model.posterior_mean_rate.return_value = 0.1     # below L2 → break
    assert c.level == 1


# ============================================================================
# CategoryTrust — build_feature_vector
# ============================================================================
def test_build_feature_vector_with_explicit_hour():
    vec = CategoryTrust.build_feature_vector( "two words here", category_index=3, hour_of_day=12 )
    assert isinstance( vec, np.ndarray )
    assert vec.shape == ( 4, )
    assert vec[ 0 ] == pytest.approx( 3 / 6.0 )
    assert vec[ 1 ] == pytest.approx( 3 / 50.0 )    # 3 words
    assert vec[ 2 ] == pytest.approx( 12 / 24.0 )
    assert vec[ 3 ] == 0.0


def test_build_feature_vector_default_hour_uses_clock():
    vec = CategoryTrust.build_feature_vector( "q", category_index=0 )
    assert 0.0 <= vec[ 2 ] < 1.0


def test_build_feature_vector_empty_question_zero_words():
    vec = CategoryTrust.build_feature_vector( "", category_index=0, hour_of_day=0 )
    assert vec[ 1 ] == 0.0


# ============================================================================
# CategoryTrust — record_decision_with_features
# ============================================================================
def test_record_with_features_lazy_inits_blr_model():
    c = CategoryTrust( "x", trust_model="blr" )
    assert c._blr_model is None
    c.record_decision_with_features( True, np.array( [ 0.1, 0.2, 0.3, 0.0 ] ) )
    assert c._blr_model is not None
    assert c.total_decisions == 1
    assert c.total_successes == 1


def test_record_with_features_reuses_model_and_handles_failure():
    c = CategoryTrust( "x", trust_model="blr" )
    c.record_decision_with_features( True, np.array( [ 0.1, 0.2, 0.3, 0.0 ] ) )
    model = c._blr_model
    c.record_decision_with_features( False, np.array( [ 0.4, 0.5, 0.6, 0.0 ] ) )
    assert c._blr_model is model           # not re-initialized
    assert c.total_decisions == 2
    assert c.total_rejections == 1


# ============================================================================
# CategoryTrust — success_rate / error_rate
# ============================================================================
def test_success_and_error_rate_empty():
    c = CategoryTrust( "x" )
    assert c.success_rate == 0.0
    assert c.error_rate == 0.0


def test_success_and_error_rate_populated():
    c = CategoryTrust( "x" )
    now = time.time()
    c.record_decision( True, timestamp=now )
    c.record_decision( True, timestamp=now )
    c.record_decision( False, timestamp=now )
    assert c.success_rate == pytest.approx( 2 / 3 )
    assert c.error_rate == pytest.approx( 1 / 3 )


# ============================================================================
# CategoryTrust — record_decision / prune / effective count
# ============================================================================
def test_record_decision_default_timestamp_and_counters():
    c = CategoryTrust( "x" )
    c.record_decision( True )       # timestamp None → now
    c.record_decision( False )
    assert c.total_decisions == 2
    assert c.total_successes == 1
    assert c.total_rejections == 1
    assert len( c.decisions ) == 2


def test_prune_rolling_window_drops_old_keeps_recent():
    c = CategoryTrust( "x", rolling_window_days=30 )
    now = time.time()
    old    = now - 31 * 86400
    recent = now - 1 * 86400
    c.decisions = [ ( old, True ), ( recent, True ) ]
    c._prune_rolling_window()
    assert c.decisions == [ ( recent, True ) ]


def test_effective_count_weights_successes_and_skips_failures():
    c = CategoryTrust( "x", decay_half_life_days=14 )
    now = time.time()
    c.decisions = [ ( now, True ), ( now, False ) ]
    eff = c._effective_decision_count()
    # one recent success → weight ≈ 1.0 ; failure skipped (continue)
    assert eff == pytest.approx( 1.0, abs=1e-3 )


# ============================================================================
# CategoryTrust — demote
# ============================================================================
def test_demote_to_l1_clears_history():
    c = CategoryTrust( "x", **SMALL_COUNT_KW )
    with _frozen_time():
        c.record_decision( True )                 # level 2
        c.demote( levels=5 )                       # target_level <= 1 → clear
    assert c.decisions == []


def test_demote_partial_keeps_target_count_successes():
    c = CategoryTrust( "x", **SMALL_COUNT_KW )
    with _frozen_time():
        for _ in range( 3 ):
            c.record_decision( True )
        c.record_decision( False )                 # failure → exercises the `if s` false arm
        assert c.level == 4                         # eff == 3
        c.demote( levels=1 )                        # target_level 3 (>1) → prune path
    kept_successes = sum( 1 for _, s in c.decisions if s )
    assert kept_successes == c.thresholds[ 3 ]     # == 2
    assert any( not s for _, s in c.decisions )    # the failure was retained


# ============================================================================
# CategoryTrust — to_dict
# ============================================================================
def test_to_dict_count_model_has_no_beta_or_blr_keys():
    c = CategoryTrust( "deploy", **SMALL_COUNT_KW )
    now = time.time()
    c.record_decision( True, timestamp=now )
    d = c.to_dict()
    assert d[ "category_name" ] == "deploy"
    assert d[ "trust_model" ] == "count"
    assert d[ "total_decisions" ] == 1
    assert "alpha" not in d
    assert "blr_state" not in d


def test_to_dict_beta_model_includes_alpha_beta():
    c = CategoryTrust( "x", trust_model="beta" )    # 0 decisions → level=1 no ppf
    d = c.to_dict()
    assert d[ "alpha" ] == 1
    assert d[ "beta" ] == 1


def test_to_dict_blr_model_includes_state_when_model_present():
    c = CategoryTrust( "x", trust_model="blr" )
    c.record_decision_with_features( True, np.array( [ 0.1, 0.2, 0.3, 0.0 ] ) )
    with patch( "scipy.stats.beta.ppf", return_value=0.5 ):   # to_dict computes level → beta fallback
        d = c.to_dict()
    assert "blr_state" in d
    assert isinstance( d[ "blr_state" ], dict )


# ============================================================================
# TrustTracker
# ============================================================================
def test_tracker_init_defaults():
    t = TrustTracker()
    assert t.categories == {}
    assert t.trust_model == "count"
    assert t.debug is False


def test_register_category_creates_and_is_idempotent():
    t = TrustTracker()
    t.register_category( "deploy", cap_level=3 )
    assert "deploy" in t.categories
    assert t.categories[ "deploy" ].cap_level == 3
    first = t.categories[ "deploy" ]
    t.register_category( "deploy" )            # already registered → no-op
    assert t.categories[ "deploy" ] is first


def test_register_category_debug_prints( capsys ):
    t = TrustTracker( debug=True )
    t.register_category( "deploy" )
    assert "Registered category" in capsys.readouterr().out


def test_get_level_unregistered_returns_one():
    t = TrustTracker()
    assert t.get_level( "nope" ) == 1


def test_get_level_registered_delegates_to_category():
    t = TrustTracker( **SMALL_COUNT_KW )
    t.register_category( "deploy" )
    assert t.get_level( "deploy" ) == 1


def test_record_decision_unregistered_returns_one_with_debug( capsys ):
    t = TrustTracker( debug=True )
    assert t.record_decision( "ghost", True ) == 1
    assert "Unknown category" in capsys.readouterr().out


def test_record_decision_updates_and_returns_new_level():
    t = TrustTracker( **SMALL_COUNT_KW )
    t.register_category( "deploy" )
    with _frozen_time():
        level = t.record_decision( "deploy", True )
    assert level == 2          # eff == 1 → L2


def test_record_decision_debug_prints_on_level_change( capsys ):
    t = TrustTracker( debug=True, **SMALL_COUNT_KW )
    t.register_category( "deploy" )
    capsys.readouterr()        # clear the registration print
    with _frozen_time():
        t.record_decision( "deploy", True )  # L1 → L2 graduation
    out = capsys.readouterr().out
    assert "graduated" in out


def test_demote_category_unregistered_is_noop():
    t = TrustTracker()
    t.demote_category( "ghost" )      # no error, no entry created
    assert "ghost" not in t.categories


def test_demote_category_demotes_with_debug( capsys ):
    t = TrustTracker( debug=True, **SMALL_COUNT_KW )
    t.register_category( "deploy" )
    now = time.time()
    for _ in range( 3 ):
        t.record_decision( "deploy", True, timestamp=now )
    capsys.readouterr()
    t.demote_category( "deploy", levels=5 )      # clears → drops to L1
    out = capsys.readouterr().out
    assert "Demoted deploy" in out
    assert t.get_level( "deploy" ) == 1


def test_demote_category_registered_quiet_when_debug_off( capsys ):
    # registered category + debug=False → reaches the if-self.debug FALSE arm (no print)
    t = TrustTracker( **SMALL_COUNT_KW )
    t.register_category( "deploy" )
    with _frozen_time():
        t.record_decision( "deploy", True )
        t.demote_category( "deploy", levels=1 )
    assert capsys.readouterr().out == ""


def test_get_all_levels_maps_each_category():
    t = TrustTracker( **SMALL_COUNT_KW )
    t.register_category( "a" )
    t.register_category( "b" )
    levels = t.get_all_levels()
    assert levels == { "a": 1, "b": 1 }


def test_get_stats_returns_per_category_dicts():
    t = TrustTracker( **SMALL_COUNT_KW )
    t.register_category( "a" )
    now = time.time()
    t.record_decision( "a", True, timestamp=now )
    stats = t.get_stats()
    assert "a" in stats
    assert stats[ "a" ][ "category_name" ] == "a"
    assert stats[ "a" ][ "total_decisions" ] == 1
