#!/usr/bin/env python3
"""
Unit tests for cosa.agents.decision_proxy.conformal_wrapper.

ConformalDecisionWrapper provides split-conformal prediction sets over scalar
probabilities. Tests cover the insufficient-calibration early return, the
label==1 vs label==0 nonconformity-score arms, quantile-index clamping, and
the predict_set branch matrix (uncalibrated, approve-only, reject-only,
ambiguous-both, empty-set fallback) plus should_defer + get_status. Pure
math — no I/O.
"""

from cosa.agents.decision_proxy.conformal_wrapper import ConformalDecisionWrapper


# ----------------------------------------------------------------------------
# __init__ / is_calibrated
# ----------------------------------------------------------------------------
def test_init_defaults():
    w = ConformalDecisionWrapper()
    assert w.alpha == 0.10
    assert w.min_calibration_size == 30
    assert w._scores == []
    assert w._quantile is None
    assert w._calibrated is False
    assert w._calibration_size == 0
    assert w.is_calibrated is False


# ----------------------------------------------------------------------------
# calibrate
# ----------------------------------------------------------------------------
def test_calibrate_insufficient_data_stays_uncalibrated():
    w = ConformalDecisionWrapper( alpha=0.1, min_calibration_size=5 )
    w.calibrate( [ 0.9, 0.8 ], [ 1, 0 ] )
    assert w.is_calibrated is False
    assert w._quantile is None


def test_calibrate_sufficient_data_sets_quantile_and_scores():
    w = ConformalDecisionWrapper( alpha=0.1, min_calibration_size=5 )
    probs  = [ 0.9, 0.8, 0.7, 0.6, 0.2, 0.3 ]
    labels = [ 1,   1,   0,   1,   0,   1   ]   # exercises label==1 AND label==0 arms
    w.calibrate( probs, labels )
    assert w.is_calibrated is True
    assert w._calibration_size == 6
    assert w._quantile is not None
    # nonconformity: label 1 → 1-p ; label 0 → p
    expected = sorted( [ 1 - 0.9, 1 - 0.8, 0.7, 1 - 0.6, 0.2, 1 - 0.3 ] )
    assert w._scores == expected


def test_calibrate_small_alpha_clamps_quantile_index():
    w = ConformalDecisionWrapper( alpha=0.001, min_calibration_size=5 )
    w.calibrate( [ 0.5, 0.5, 0.5, 0.5, 0.5 ], [ 1, 1, 1, 1, 1 ] )
    assert w.is_calibrated is True
    # q_index would exceed n-1 → clamped to the max score
    assert w._quantile == max( w._scores )


# ----------------------------------------------------------------------------
# predict_set
# ----------------------------------------------------------------------------
def test_predict_set_uncalibrated_returns_both_classes():
    w = ConformalDecisionWrapper()
    assert w.predict_set( 0.9 ) == { "approve", "reject" }


def test_predict_set_singleton_approve():
    w = ConformalDecisionWrapper()
    w._calibrated = True
    w._quantile = 0.3
    # approve_score = 1-0.9 = 0.1 <= 0.3 ; reject_score = 0.9 > 0.3
    assert w.predict_set( 0.9 ) == { "approve" }


def test_predict_set_singleton_reject():
    w = ConformalDecisionWrapper()
    w._calibrated = True
    w._quantile = 0.3
    # reject_score = 0.1 <= 0.3 ; approve_score = 0.9 > 0.3
    assert w.predict_set( 0.1 ) == { "reject" }


def test_predict_set_ambiguous_returns_both():
    w = ConformalDecisionWrapper()
    w._calibrated = True
    w._quantile = 0.6
    # both scores 0.5 <= 0.6
    assert w.predict_set( 0.5 ) == { "approve", "reject" }


def test_predict_set_empty_falls_back_to_both():
    w = ConformalDecisionWrapper()
    w._calibrated = True
    w._quantile = 0.2
    # both scores 0.5 > 0.2 → empty set → safe fallback
    assert w.predict_set( 0.5 ) == { "approve", "reject" }


# ----------------------------------------------------------------------------
# should_defer
# ----------------------------------------------------------------------------
def test_should_defer_uncalibrated_is_true():
    w = ConformalDecisionWrapper()
    assert w.should_defer( 0.9 ) is True


def test_should_defer_singleton_is_false():
    w = ConformalDecisionWrapper()
    w._calibrated = True
    w._quantile = 0.3
    assert w.should_defer( 0.9 ) is False


def test_should_defer_ambiguous_is_true():
    w = ConformalDecisionWrapper()
    w._calibrated = True
    w._quantile = 0.6
    assert w.should_defer( 0.5 ) is True


# ----------------------------------------------------------------------------
# get_status
# ----------------------------------------------------------------------------
def test_get_status_fresh():
    w = ConformalDecisionWrapper( alpha=0.05 )
    assert w.get_status() == {
        "calibrated": False,
        "alpha": 0.05,
        "quantile": None,
        "calibration_size": 0,
    }


def test_get_status_after_calibration():
    w = ConformalDecisionWrapper( alpha=0.1, min_calibration_size=5 )
    w.calibrate( [ 0.9, 0.8, 0.7, 0.6, 0.5 ], [ 1, 0, 1, 0, 1 ] )
    status = w.get_status()
    assert status[ "calibrated" ] is True
    assert status[ "calibration_size" ] == 5
    assert status[ "quantile" ] is not None
    assert status[ "alpha" ] == 0.1
