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
    c._blr_model.n_observations = 30
    c._blr_model.posterior_mean_rate.return_value = 0.99
    level = c.level
    c._blr_model.posterior_mean_rate.assert_called_once()
    assert level == 5


def test_level_blr_falls_back_when_model_has_few_observations():
    c = CategoryTrust( "x", trust_model="blr", min_samples=LOW_MIN_SAMPLES )
    now = time.time()
    for _ in range( 30 ):
        c.record_decision( True, timestamp=now )
    c._blr_model = MagicMock()
    c._blr_model.n_observations = 5                      # young model: its posterior is not trusted
    with patch( "scipy.stats.beta.ppf", return_value=0.99 ):
        assert c.level == 5
    c._blr_model.posterior_mean_rate.assert_not_called()


def test_level_blr_breaks_when_posterior_rate_low():
    c = CategoryTrust( "x", trust_model="blr", min_samples=LOW_MIN_SAMPLES )
    now = time.time()
    for _ in range( 30 ):
        c.record_decision( True, timestamp=now )
    c._blr_model = MagicMock()
    c._blr_model.n_observations = 30
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


# ── restore_category (row 251f26fb, D2) ──────────────────────────────────────

def _tracker_with( **kw ):
    tracker = TrustTracker( **SMALL_COUNT_KW, **kw )
    tracker.register_category( "testing" )
    return tracker


def test_restore_category_sets_totals_and_a_level_that_matches_the_stored_counts():
    tracker = _tracker_with()
    with _frozen_time( 1_000_000.0 ):
        assert tracker.restore_category( "testing", 4, 1, 1_000_000.0 ) is True
        cat = tracker.categories[ "testing" ]
        assert ( cat.total_successes, cat.total_rejections, cat.total_decisions ) == ( 4, 1, 5 )
        assert len( cat.decisions ) == 5 and sum( 1 for _, ok in cat.decisions if ok ) == 4
        assert tracker.get_level( "testing" ) > 1, "four stored successes must lift the level above L1"


def test_restore_category_history_decays_from_the_stored_timestamp():
    tracker = _tracker_with( rolling_window_days=30 )
    day = 86_400.0
    with _frozen_time( 100 * day ):
        assert tracker.restore_category( "testing", 3, 0, 99 * day ) is True       # inside the window
        assert tracker.categories[ "testing" ].decisions[ 0 ][ 0 ] == 99 * day
    other = _tracker_with( rolling_window_days=30 )
    with _frozen_time( 100 * day ):
        assert other.restore_category( "testing", 3, 0, 10 * day ) is True         # long outside it
        cat = other.categories[ "testing" ]
        assert cat.decisions == [] and cat.total_decisions == 3, "totals survive, stale history is pruned"
        assert other.get_level( "testing" ) == 1


def test_restore_category_refuses_an_unknown_category_and_a_category_that_already_has_decisions():
    tracker = _tracker_with()
    assert tracker.restore_category( "nope", 5, 0, 1.0 ) is False
    tracker.record_decision( "testing", True )
    assert tracker.restore_category( "testing", 9, 9, 1.0 ) is False
    assert tracker.categories[ "testing" ].total_decisions == 1, "a refused restore must change nothing"


def test_a_stored_trip_caps_the_restored_level_and_no_trip_leaves_it_to_the_counters():
    with _frozen_time( 1_000_000.0 ):
        free = _tracker_with()
        free.restore_category( "testing", 4, 0, 1_000_000.0 )
        earned = free.get_level( "testing" )
        assert earned > 2, "four stored successes against thresholds 1/2/3/4 earn a high level"

        tripped = _tracker_with()
        tripped.restore_category( "testing", 4, 0, 1_000_000.0, trip={ "tripped_level": 2, "successes_at_trip": 4 } )
        assert tripped.get_level( "testing" ) == 2 and tripped.categories[ "testing" ].trip_active()


def test_a_trip_is_earned_back_by_new_successes_and_then_stores_as_none():
    # Thresholds 1/2/3/4: a trip at level 3 needs l4 - l3 = 1 new success; a trip at level 2 needs l3 - l2 = 1.
    with _frozen_time( 1_000_000.0 ):
        tracker = _tracker_with()
        tracker.restore_category( "testing", 4, 0, 1_000_000.0, trip={ "tripped_level": 2, "successes_at_trip": 4 } )
        cat = tracker.categories[ "testing" ]
        assert cat.trip_state() == { "status": "tripped", "tripped_level": 2, "successes_at_trip": 4 }
        tracker.record_decision( "testing", False, timestamp=1_000_000.0 )         # a rejection earns nothing back
        assert cat.trip_active() and tracker.get_level( "testing" ) == 2
        tracker.record_decision( "testing", True, timestamp=1_000_000.0 )
        assert not cat.trip_active() and cat.trip_state() is None
        assert tracker.get_level( "testing" ) > 2, "once earned back, the counters decide again"


def test_record_trip_remembers_the_demoted_level_and_ignores_an_unknown_category():
    with _frozen_time( 1_000_000.0 ):
        tracker = _tracker_with()
        tracker.restore_category( "testing", 4, 0, 1_000_000.0 )
        tracker.demote_category( "testing", 2 )
        tracker.record_trip( "testing" )
        cat = tracker.categories[ "testing" ]
        assert ( cat.trip_level, cat.trip_successes ) == ( tracker.get_level( "testing" ), 4 )
        tracker.record_trip( "nope" )                                              # no category, no error


def test_a_trip_at_the_top_level_never_caps():
    cat = CategoryTrust( "testing", **SMALL_COUNT_KW )
    cat.trip_level, cat.trip_successes = 5, 0
    assert cat.trip_active() is False


def test_a_stored_trip_carries_the_status_the_dashboard_reads():
    # proxy-dashboard.js treats a circuit_breaker_state with no status as "closed", i.e. OK.
    with _frozen_time( 1_000_000.0 ):
        tracker = _tracker_with()
        tracker.restore_category( "testing", 4, 0, 1_000_000.0, trip={ "tripped_level": 2, "successes_at_trip": 4 } )
        state = tracker.categories[ "testing" ].trip_state()
        assert state[ "status" ] == "tripped"
        assert ( state.get( "status" ) or "closed" ).lower() != "closed", "the dashboard's own default must not apply"


# ── restore_category with per-day history (row da64aaab) ─────────────────────

def _epoch_of( day, hour=12 ):
    from datetime import datetime, timezone
    return datetime.strptime( day, "%Y-%m-%d" ).replace( hour=hour, tzinfo=timezone.utc ).timestamp()


def test_restore_category_with_history_stamps_each_day_so_old_decisions_age_out_of_the_window():
    # 190 old successes and 10 fresh failures. Without history all 200 load stamped "just now".
    history = { "2026-09-20": [ 190, 0 ], "2026-11-06": [ 0, 10 ] }
    now     = _epoch_of( "2026-11-06" )
    with_hist, without = _tracker_with( rolling_window_days=30 ), _tracker_with( rolling_window_days=30 )
    with _frozen_time( now ):
        assert with_hist.restore_category( "testing", 190, 10, now, history=history ) is True
        assert without.restore_category( "testing", 190, 10, now ) is True
        a, b = with_hist.categories[ "testing" ], without.categories[ "testing" ]
        assert len( { t for t, _ in b.decisions } ) == 1, "control: no history means one stamp for all 200"
        assert len( b.decisions ) == 200 and b.recent_error_rate( window=200 ) == 0.05
        assert len( a.decisions ) == 10 and a.recent_error_rate( window=200 ) == 1.0, "the 190 old ones aged out"
        assert ( a.total_successes, a.total_rejections, a.total_decisions ) == ( 190, 10, 200 ), "totals are untouched"


def test_restore_category_with_history_weights_a_day_old_success_above_a_two_week_old_one():
    history = { "2026-10-23": [ 1, 0 ], "2026-11-05": [ 1, 0 ] }       # 14 days and 1 day before the frozen time
    now     = _epoch_of( "2026-11-06" )
    tracker = _tracker_with( rolling_window_days=30, decay_half_life_days=14 )
    with _frozen_time( now ):
        tracker.restore_category( "testing", 2, 0, now, history=history )
        stamps = sorted( t for t, _ in tracker.categories[ "testing" ].decisions )
        assert stamps == [ _epoch_of( "2026-10-23", 0 ), _epoch_of( "2026-11-05", 0 ) ], "stamped at the start of the UTC day"
        assert 1.2 < tracker.categories[ "testing" ]._effective_decision_count() < 1.5     # about 0.5 + 0.95


def test_restore_category_with_an_empty_history_restores_no_rolling_history_but_keeps_totals():
    tracker = _tracker_with()
    now     = _epoch_of( "2026-11-06" )
    with _frozen_time( now ):
        assert tracker.restore_category( "testing", 3, 1, now, history={} ) is True
        cat = tracker.categories[ "testing" ]
        assert cat.decisions == [] and cat.total_decisions == 4

# ============================================================================
# TrustTracker.record_decision_with_features (row cfc7dd01)
# ============================================================================
def test_tracker_feeds_blr_with_the_built_feature_vector():
    t = TrustTracker( trust_model="blr", debug=True )
    t.register_category( "a" ); t.register_category( "b" )
    t.record_decision( "b", False )                       # b has one rejection, so its recent error rate is 1.0
    with patch.object( CategoryTrust, "build_feature_vector", wraps=CategoryTrust.build_feature_vector ) as build:
        lvl = t.record_decision_with_features( "b", True, "one two three" )
    assert build.call_args.args == ( "one two three", 1 )          # b was registered second
    assert build.call_args.kwargs[ "recent_error_rate" ] == 1.0
    assert t.categories[ "b" ]._blr_model._feature_count == 1       # BLR was fed
    assert t.categories[ "a" ]._blr_model is None                   # categories stay isolated
    assert t.categories[ "b" ].total_decisions == 2                 # history recorded once for this call
    assert lvl == t.categories[ "b" ].level


def test_tracker_record_with_features_unknown_category_records_nothing( capsys ):
    t = TrustTracker( trust_model="blr", debug=True )
    assert t.record_decision_with_features( "nope", True, "q" ) == 1
    assert "Unknown category: nope" in capsys.readouterr().out
    t2 = TrustTracker( trust_model="blr" )
    assert t2.record_decision_with_features( "nope", True, "q" ) == 1   # silent without debug


# ── BLR state survives a restart (row 5bb93a7b) ──────────────────────────────

_BLR_QUESTIONS = [ "deploy the build?", "delete the old branch?", "merge the fix?", "retry the test run?", "push the commit?" ]


def _trained_blr_tracker( model="blr" ):
    tracker = TrustTracker( trust_model=model )
    tracker.register_category( "testing" )
    for i in range( 12 ):
        tracker.record_decision_with_features( "testing", i % 3 != 0, _BLR_QUESTIONS[ i % len( _BLR_QUESTIONS ) ] )
    return tracker


def test_a_blr_model_saved_and_restored_into_a_fresh_tracker_predicts_the_same():
    trained = _trained_blr_tracker()
    saved   = trained.blr_state_for( "testing" )
    probe   = np.array( [ 1.0, 0.5, 0.25, 0.1 ] )

    fresh = TrustTracker( trust_model="blr" )
    fresh.register_category( "testing" )
    assert fresh.categories[ "testing" ]._blr_model is None, "a fresh tracker starts BLR from zero"
    assert fresh.restore_category( "testing", 8, 4, 1_000_000.0, blr_state=saved ) is True

    before = trained.categories[ "testing" ]._blr_model
    after  = fresh.categories[ "testing" ]._blr_model
    assert after.predict( probe ) == before.predict( probe )
    assert after.n_observations == before.n_observations == 12
    assert after.posterior_mean_rate() == before.posterior_mean_rate()


def test_the_saved_blr_state_survives_a_json_round_trip():
    import json
    saved = json.loads( json.dumps( _trained_blr_tracker().blr_state_for( "testing" ) ) )
    fresh = TrustTracker( trust_model="blr" )
    fresh.register_category( "testing" )
    fresh.restore_category( "testing", 8, 4, 1_000_000.0, blr_state=saved )
    probe = np.array( [ 1.0, 0.5, 0.25, 0.1 ] )
    assert fresh.categories[ "testing" ]._blr_model.predict( probe ) == _trained_blr_tracker().categories[ "testing" ]._blr_model.predict( probe )


def test_blr_state_for_is_none_without_a_blr_model_to_save():
    count = TrustTracker( **SMALL_COUNT_KW )
    count.register_category( "testing" )
    count.record_decision( "testing", True )
    assert count.blr_state_for( "testing" ) is None, "the count model keeps no BLR state"

    blr = TrustTracker( trust_model="blr" )
    blr.register_category( "testing" )
    assert blr.blr_state_for( "testing" ) is None, "no decision with features yet, so no model"
    assert blr.blr_state_for( "nope" ) is None, "unknown category"


def test_restore_ignores_blr_state_unless_the_trust_model_is_blr():
    saved = _trained_blr_tracker().blr_state_for( "testing" )
    for model in ( "count", "beta" ):
        tracker = TrustTracker( trust_model=model )
        tracker.register_category( "testing" )
        assert tracker.restore_category( "testing", 8, 4, 1_000_000.0, blr_state=saved ) is True
        assert tracker.categories[ "testing" ]._blr_model is None, model


def test_restore_without_blr_state_leaves_a_blr_tracker_with_no_model():
    tracker = TrustTracker( trust_model="blr" )
    tracker.register_category( "testing" )
    tracker.restore_category( "testing", 8, 4, 1_000_000.0 )
    assert tracker.categories[ "testing" ]._blr_model is None


def test_blr_state_for_is_none_for_count_and_beta_even_when_a_model_was_fed():
    # Mutation guard: record_decision_with_features builds a model under any trust model,
    # so only the trust_model check inside blr_state_for keeps count and beta from saving one.
    for model in ( "count", "beta" ):
        tracker = _trained_blr_tracker( model )
        assert tracker.categories[ "testing" ]._blr_model is not None, model
        assert tracker.blr_state_for( "testing" ) is None, model
