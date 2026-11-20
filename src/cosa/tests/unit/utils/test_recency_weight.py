"""
Unit tests for the shared half-life weight and for its use by the trust tracker.

The literals are worked out by hand from the formula exp( -0.693 * age / half_life ).
The trust tracker has always used that figure, so its weights stay what they were.
"""
import time

import pytest

from cosa.agents.decision_proxy.trust_tracker import CategoryTrust
from cosa.utils.recency_weight import recency_weight

DAY = 86400


@pytest.mark.parametrize( "age_days, half_life, expected", [
    ( 0,  14, 1.0 ),
    ( 14, 14, 0.500074 ),        # exp( -0.693 )
    ( 28, 14, 0.250074 ),        # exp( -1.386 )
    ( 7,  14, 0.707159 ),        # exp( -0.3465 )
    ( 14, 28, 0.707159 ),        # a longer half-life ages slower
] )
def test_the_weight_at_fixed_ages_is_the_trust_trackers( age_days, half_life, expected ):
    assert recency_weight( age_days * DAY, half_life ) == pytest.approx( expected, abs=1e-5 )


def test_the_weight_falls_with_age_and_never_exceeds_one():
    weights = [ recency_weight( days * DAY, 14 ) for days in ( 0, 1, 10, 100 ) ]
    assert weights == sorted( weights, reverse=True ) and weights[ 0 ] == 1.0 and weights[ -1 ] < 0.01


@pytest.mark.parametrize( "half_life", [ 0, -3 ] )
def test_a_half_life_that_is_not_positive_is_refused( half_life ):
    with pytest.raises( ValueError, match="half_life_days must be positive" ):
        recency_weight( DAY, half_life )


def test_the_trust_tracker_sums_the_shared_weight_over_its_successes():
    tracker = CategoryTrust( "x", decay_half_life_days=14 )
    now = time.time()
    tracker.decisions = [ ( now, True ), ( now - 14 * DAY, True ), ( now - 28 * DAY, True ), ( now - 3 * DAY, False ) ]
    # 1.0 + 0.500074 + 0.250074, the failure counting for nothing
    assert tracker._effective_decision_count() == pytest.approx( 1.750148, abs=1e-3 )
