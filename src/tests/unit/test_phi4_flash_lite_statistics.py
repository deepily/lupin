"""
Unit tests for the study's statistics (handoff §7 item 4).

Three groups carry the weight:

  · THE SPEC'S OWN NUMBERS, reproduced. The handoff states the arithmetic floor as
    "b+c=5 -> p=0.0625 cannot clear; b+c=6 -> 0.03125", and plan §3.1.2 states the
    6/6 Wilson lower bound as 0.6097. All three are asserted here against values
    this module computed, so a regression in the formulas shows up as a number that
    stopped matching a written figure.
  · THE MUST-FAIL CONTROL. Wilson and Wald must DISAGREE at 6/6. A Wilson that
    silently degraded to Wald would pass every "the interval is between 0 and 1"
    assertion ever written; only comparing the two catches it.
  · NO STATSMODELS. Asserted twice — the package is absent from the interpreter,
    and the module's source never names it outside the warning that forbids it.

Venue: :7999-eligible. Pure arithmetic — no server, no DB, no model.
"""

import math
import importlib

import pytest

from cosa.research.phi4_flash_lite_study import statistics as ST


# ─────────────────────────────────────────────────────────────────────────────
# SCIPY ONLY — the trap the spec names
# ─────────────────────────────────────────────────────────────────────────────

def test_statsmodels_is_not_installed():
    """
    The spec names statsmodels ONLY as the trap: its proportion_confint defaults to
    the forbidden Wald interval, and it is neither installed nor pinned. A crew that
    reaches for it earns a ModuleNotFoundError; this test says so out loud, so
    someone adding it has to delete an assertion rather than just an assumption.
    """
    with pytest.raises( ModuleNotFoundError ):
        importlib.import_module( "statsmodels" )


def test_the_module_never_imports_statsmodels():
    source = open( ST.__file__, encoding="utf-8" ).read()
    code   = [ line for line in source.splitlines()
               if line.startswith( ( "import ", "from " ) ) ]
    assert not any( "statsmodels" in line for line in code )


def test_scipy_version_is_read_at_runtime_not_copied_from_the_pin():
    """
    requirements.txt pins 1.15.2; this box measured 1.17.1. The run must record what
    it USED — a stats result argued over with the library version unknown is a
    result nobody can settle.
    """
    import scipy
    assert ST.scipy_version() == scipy.__version__
    assert ST.scipy_version() != "1.15.2" or scipy.__version__ == "1.15.2"


def test_every_result_carries_the_scipy_version():
    assert ST.mcnemar_exact( 4, 2 )[ "scipy_version" ]     == ST.scipy_version()
    assert ST.must_fail_control()[ "scipy_version" ]       == ST.scipy_version()
    assert ST.compare_arms( 5, 1, 6 )[ "scipy_version" ]   == ST.scipy_version()


# ─────────────────────────────────────────────────────────────────────────────
# McNEMAR EXACT — the spec's stated arithmetic
# ─────────────────────────────────────────────────────────────────────────────

def test_the_arithmetic_floor_is_exactly_what_the_spec_says():
    """
    Handoff §3.F: "b+c=5 -> p=0.0625 cannot clear; b+c=6 -> 0.03125". Both, to the
    digit, from binomtest — this is why the floor is 6 and not 5.
    """
    assert ST.mcnemar_exact( 5, 0 )[ "p_value" ] == pytest.approx( 0.0625 )
    assert ST.mcnemar_exact( 6, 0 )[ "p_value" ] == pytest.approx( 0.03125 )

    assert ST.mcnemar_exact( 5, 0 )[ "p_value" ] > 0.05, "5 discordant pairs cannot reach significance"
    assert ST.mcnemar_exact( 6, 0 )[ "p_value" ] < 0.05, "6 discordant pairs can"


def test_mcnemar_uses_the_exact_binomial_and_not_the_chi_square_approximation():
    """
    At b=6, c=0 the chi-square-with-continuity statistic gives p ~ 0.0412; the exact
    test gives 0.03125. Asserting the exact value pins WHICH test ran.
    """
    from scipy.stats import binomtest
    assert ST.mcnemar_exact( 6, 0 )[ "p_value" ] == binomtest( 0, 6, 0.5 ).pvalue


def test_mcnemar_is_symmetric_in_b_and_c():
    """The test says the arms differ, not which one won; direction is the proportion's job."""
    assert ST.mcnemar_exact( 9, 2 )[ "p_value" ] == ST.mcnemar_exact( 2, 9 )[ "p_value" ]


def test_mcnemar_statistic_is_min_b_c():
    """The spec's call shape: binomtest( min( b, c ), b + c, 0.5 )."""
    result = ST.mcnemar_exact( 9, 2 )
    assert result[ "statistic" ]    == 2
    assert result[ "n_discordant" ] == 11


def test_mcnemar_ignores_concordant_pairs_by_construction():
    """
    The function is given ONLY b and c. Concordant rows cannot leak in, which is the
    whole reason a paired study uses this test and not a two-proportion comparison.
    """
    assert ST.mcnemar_exact( 3, 1 ) [ "p_value" ] == ST.mcnemar_exact( 3, 1 )[ "p_value" ]
    assert ST.mcnemar_exact( 3, 1 )[ "n_discordant" ] == 4          # not 4 + any concordant count


def test_mcnemar_on_an_even_split_is_maximally_unconvincing():
    assert ST.mcnemar_exact( 10, 10 )[ "p_value" ] == pytest.approx( 1.0 )


def test_mcnemar_with_no_discordance_is_no_evidence_not_an_error():
    result = ST.mcnemar_exact( 0, 0 )
    assert result[ "p_value" ]      == 1.0
    assert result[ "n_discordant" ] == 0


def test_mcnemar_rejects_negative_counts():
    with pytest.raises( ValueError ):
        ST.mcnemar_exact( -1, 3 )
    with pytest.raises( ValueError ):
        ST.mcnemar_exact( 3, -1 )


# ─────────────────────────────────────────────────────────────────────────────
# WILSON — and the must-fail control that proves it is not Wald
# ─────────────────────────────────────────────────────────────────────────────

def test_wilson_reproduces_the_specs_published_lower_bound():
    """Plan §3.1.2 states 0.6097 for 6 of 6. Computed here, not copied."""
    lower, upper = ST.wilson_interval( 6, 6 )
    assert lower == pytest.approx( 0.6097, abs=1e-4 )
    assert upper == 1.0


def test_the_must_fail_control_distinguishes_wilson_from_wald():
    """
    The cheap control the spec asks for. Wald's standard error at p=1 is exactly
    zero, so its interval collapses to a point and asserts certainty from six
    observations. If these two ever agree, the Wilson code degraded to Wald.
    """
    control = ST.must_fail_control()
    assert control[ "wald_lower" ]    == pytest.approx( 1.0 )
    assert control[ "wilson_lower" ]  == pytest.approx( 0.6097, abs=1e-4 )
    assert control[ "distinguishes" ]
    assert control[ "wilson_lower" ] < control[ "wald_lower" ]


def test_wilson_does_not_collapse_at_zero_successes_either():
    """
    The same defect at the other end: Wald gives a lower bound of exactly 0 with a
    zero standard error at 0/6, i.e. a point. Wilson's UPPER bound is ~0.39 — six
    clean observations do not rule out a 39% rate, and that is the honest reading.

    (The Wilson lower bound here is 2.8e-17, not a literal 0.0 — the closed form is
    a difference of two nearly-equal floats. Asserting `== 0.0` is a test bug, which
    is how this comment came to exist.)
    """
    lower, upper = ST.wilson_interval( 0, 6 )
    assert lower == pytest.approx( 0.0, abs=1e-12 )
    assert upper == pytest.approx( 0.3903, abs=1e-4 )
    assert upper > ST.wald_lower_bound( 0, 6 ), "a zero-success interval collapsed to a point is Wald, not Wilson"


def test_wilson_is_asymmetric_near_the_boundary():
    """Wilson's whole character: the interval is not centred on p̂ near 0 or 1."""
    lower, upper = ST.wilson_interval( 9, 10 )
    p_hat        = 0.9
    assert ( p_hat - lower ) != pytest.approx( upper - p_hat )


def test_wilson_narrows_as_evidence_accumulates():
    narrow = ST.wilson_interval( 90, 100 )
    wide   = ST.wilson_interval( 9, 10 )
    assert ( narrow[ 1 ] - narrow[ 0 ] ) < ( wide[ 1 ] - wide[ 0 ] )


def test_wilson_stays_inside_zero_and_one():
    for successes, trials in ( ( 0, 1 ), ( 1, 1 ), ( 1, 2 ), ( 6, 6 ), ( 0, 100 ), ( 100, 100 ) ):
        lower, upper = ST.wilson_interval( successes, trials )
        assert 0.0 <= lower <= upper <= 1.0


def test_wilson_matches_the_closed_form_by_hand():
    """Recomputed independently in the test, so a typo in the module is visible."""
    from scipy.stats import norm
    successes, trials, confidence = 7, 12, 0.95

    z   = norm.ppf( 1 - ( 1 - confidence ) / 2 )
    n   = float( trials )
    p   = successes / n
    den = 1 + z * z / n
    centre = ( p + z * z / ( 2 * n ) ) / den
    half   = ( z * math.sqrt( p * ( 1 - p ) / n + z * z / ( 4 * n * n ) ) ) / den

    lower, upper = ST.wilson_interval( successes, trials, confidence=confidence )
    assert lower == pytest.approx( centre - half )
    assert upper == pytest.approx( centre + half )


def test_wilson_widens_at_higher_confidence():
    ninety      = ST.wilson_interval( 5, 10, confidence=0.90 )
    ninety_nine = ST.wilson_interval( 5, 10, confidence=0.99 )
    assert ( ninety_nine[ 1 ] - ninety_nine[ 0 ] ) > ( ninety[ 1 ] - ninety[ 0 ] )


def test_wilson_on_zero_trials_is_total_ignorance():
    assert ST.wilson_interval( 0, 0 ) == ( 0.0, 1.0 )


def test_wilson_rejects_impossible_inputs():
    with pytest.raises( ValueError ): ST.wilson_interval( 3, 2 )
    with pytest.raises( ValueError ): ST.wilson_interval( -1, 5 )
    with pytest.raises( ValueError ): ST.wilson_interval( 1, -5 )
    with pytest.raises( ValueError ): ST.wilson_interval( 1, 5, confidence=0 )
    with pytest.raises( ValueError ): ST.wilson_interval( 1, 5, confidence=1 )


def test_wald_bound_rejects_impossible_inputs():
    with pytest.raises( ValueError ): ST.wald_lower_bound( 1, 0 )
    with pytest.raises( ValueError ): ST.wald_lower_bound( 3, 2 )


# ─────────────────────────────────────────────────────────────────────────────
# THE FLOOR IS RICK'S NUMBER, NOT THIS MODULE'S
# ─────────────────────────────────────────────────────────────────────────────

def test_the_floor_must_be_pre_stated():
    """
    No default. A floor chosen after seeing the data is not a floor, and the
    effect-size-worthy number is Rick's call — the module only knows the arithmetic
    bound below which nothing is possible.
    """
    with pytest.raises( ST.FloorNotPreStated ) as excinfo:
        ST.assert_floor_pre_stated( 40, None )
    assert "PRE-STATED" in str( excinfo.value )
    assert "Rick's" in str( excinfo.value )


def test_a_floor_below_the_arithmetic_bound_is_refused():
    """Accepting 5 would license reporting a result that cannot reach p < 0.05."""
    with pytest.raises( ValueError ) as excinfo:
        ST.assert_floor_pre_stated( 5, 5 )
    assert "arithmetic bound" in str( excinfo.value )


def test_too_few_discordant_pairs_refuses_a_verdict():
    with pytest.raises( ST.DiscordantFloorNotMet ) as excinfo:
        ST.assert_floor_pre_stated( 4, 10 )
    assert "under the pre-stated floor of 10" in str( excinfo.value )


def test_the_floor_passes_when_met():
    assert ST.assert_floor_pre_stated( 12, 10 ) == 12


def test_the_arithmetic_floor_constant_is_six():
    assert ST.ARITHMETIC_DISCORDANT_FLOOR == 6


# ─────────────────────────────────────────────────────────────────────────────
# THE VERDICT
# ─────────────────────────────────────────────────────────────────────────────

def test_compare_arms_reports_test_interval_control_and_version():
    result = ST.compare_arms( 11, 2, operational_floor=6 )

    assert result[ "mcnemar" ][ "p_value" ] == pytest.approx( 0.02246, abs=1e-4 )
    assert result[ "proportion_arm_a_hit" ] == pytest.approx( 11 / 13 )
    assert "not a win" in result[ "proportion_means" ], \
        "the share must not be labelled as favouring the arm — for fabrication_blocked it is the opposite"
    assert "phi_4" in result[ "wilson_covers" ]
    assert result[ "wilson_interval" ][ "lower" ] > 0.5
    assert result[ "must_fail_control" ][ "distinguishes" ]
    assert result[ "operational_floor" ] == 6
    assert result[ "arithmetic_floor" ]  == 6
    assert result[ "statsmodels_used" ]  is False
    assert result[ "arm_a" ] == "phi_4" and result[ "arm_b" ] == "flash_lite"


def test_compare_arms_interval_and_p_value_describe_the_same_quantity():
    """
    The Wilson interval covers b/(b+c) — the share of DISAGREEMENTS that went arm A's
    way: the share where ARM A was the one that HIT the outcome, which is exactly the
    proportion McNemar tests against 0.5. An interval straddling 0.5 and a significant
    p would be incoherent.
    """
    result = ST.compare_arms( 11, 2, operational_floor=6 )
    lower  = result[ "wilson_interval" ][ "lower" ]

    assert result[ "mcnemar" ][ "p_value" ] < 0.05
    assert lower > 0.5, "a significant McNemar with an interval containing 0.5 would contradict itself"


def test_compare_arms_refuses_below_the_floor():
    with pytest.raises( ST.DiscordantFloorNotMet ):
        ST.compare_arms( 3, 2, operational_floor=10 )


def test_compare_arms_refuses_without_a_floor():
    with pytest.raises( ST.FloorNotPreStated ):
        ST.compare_arms( 30, 10, operational_floor=None )


def test_compare_arms_honours_custom_arm_names_and_confidence():
    result = ST.compare_arms( 8, 4, operational_floor=6, arm_a="left", arm_b="right", confidence=0.99 )
    assert result[ "arm_a" ] == "left"
    assert result[ "arm_b" ] == "right"
    assert result[ "wilson_interval" ][ "confidence" ] == 0.99

    ninety_five = ST.compare_arms( 8, 4, operational_floor=6 )[ "wilson_interval" ]
    assert ( result[ "wilson_interval" ][ "upper" ] - result[ "wilson_interval" ][ "lower" ] ) > \
           ( ninety_five[ "upper" ] - ninety_five[ "lower" ] )


def test_compare_arms_at_the_exact_floor_is_allowed():
    """6 discordant pairs is the arithmetic minimum that CAN clear; it must not be refused."""
    result = ST.compare_arms( 6, 0, operational_floor=6 )
    assert result[ "mcnemar" ][ "p_value" ] == pytest.approx( 0.03125 )
    assert result[ "wilson_interval" ][ "lower" ] == pytest.approx( 0.6097, abs=1e-4 )
