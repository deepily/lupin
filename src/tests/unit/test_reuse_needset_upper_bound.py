"""
The miss-rate bound of the need set's report, pinned by an independent route.
"""
import math

import pytest


def test_scipy_importable():
    try:
        import scipy.stats  # noqa: F401
    except ImportError as e:
        pytest.fail( f"scipy is not importable in this interpreter, so every bound pin would error: {e} (owner: Tiffany, plan step 6.D D7)" )


def bisect_bound( misses, trials, confidence=0.95 ):
    """Return the upper bound found by bisection on the exact binomial sum."""
    def cdf( p ): return sum( math.comb( trials, k ) * p ** k * ( 1 - p ) ** ( trials - k ) for k in range( misses + 1 ) )

    low, high = 0.0, 1.0
    for _ in range( 100 ):
        mid = ( low + high ) / 2
        if cdf( mid ) > 1 - confidence: low = mid
        else: high = mid
    return ( low + high ) / 2


@pytest.mark.parametrize( "misses, trials, rounded", [ ( 0, 300, 0.0099 ), ( 3, 300, 0.0256 ) ] )
def test_the_bound_is_pinned_to_four_places_and_to_an_independent_bisection( misses, trials, rounded ):
    from cosa.repo.doc_lint import harness_report
    got = harness_report.upper_bound( misses, trials )
    assert round( got, 4 ) == rounded
    assert got == pytest.approx( bisect_bound( misses, trials ), abs=1e-9 )


def test_all_found_in_300_bounds_the_miss_rate_at_about_one_percent():
    from cosa.repo.doc_lint import harness_report
    assert harness_report.upper_bound( 0, 300 ) == pytest.approx( 1 - 0.05 ** ( 1 / 300 ) )


def test_no_trials_give_no_bound_and_every_miss_gives_one():
    from cosa.repo.doc_lint import harness_report
    assert harness_report.upper_bound( 0, 0 ) is None and harness_report.upper_bound( 5, 5 ) == 1.0
