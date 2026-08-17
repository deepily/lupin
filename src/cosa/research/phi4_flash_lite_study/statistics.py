"""
Inferential statistics for the Phi-4 vs Flash-Lite study (handoff §7 item 4).

Two tests, both SCIPY-ONLY:

  · McNemar's EXACT test — `scipy.stats.binomtest( min( b, c ), b + c, 0.5 )`.
    The arms are PAIRED: every body goes through both, so the concordant rows
    (both blocked, or neither) carry no information about which model is more
    honest. Only the discordant pairs do, and under the null a discordant pair is
    a coin flip. The exact binomial test is used rather than the chi-square
    approximation because the discordant counts here are small, which is exactly
    where the approximation is worst.

  · WILSON score interval — computed CLOSED-FORM from `scipy.stats.norm`.

⚠️ `statsmodels` IS NAMED IN THE SPEC ONLY AS THE TRAP TO AVOID. Its
`proportion_confint` DEFAULTS to the Wald interval, which is forbidden here, and
the package is neither installed nor pinned in any requirements file — verified on
this box: `import statsmodels` raises ModuleNotFoundError. Do NOT add it. The
closed-form Wilson below has no such dependency.

WHY WALD IS FORBIDDEN, in one number: at 6 successes out of 6, Wald's standard
error is sqrt( 1 * 0 / 6 ) = 0, so its interval collapses to [1.0, 1.0] — it claims
certainty from six observations. Wilson gives [0.6097, 1.0]. `wald_lower_bound`
below exists ONLY as that must-fail control, and `must_fail_control()` asserts the
two disagree. It is never used to report a result.

⚠️ THE DISCORDANT FLOOR IS NOT SET HERE. The arithmetic minimum is 6 (`b + c = 5`
gives a best-case p of 0.0625, which cannot clear 0.05 no matter how lopsided;
`b + c = 6` gives 0.03125). The OPERATIONAL floor — the effect-size-worthy number —
is Rick's, pre-stated before arm 1. `assert_floor_pre_stated` takes it as a
required argument and has no default.

SCIPY VERSION. Read from `scipy.__version__` at run time and recorded in every
result, never copied from the pin: `src/cosa/requirements.txt:210` pins 1.15.2 and
this box measured 1.17.1. `binomtest` and `norm.ppf` predate both, so the numbers
are not version-sensitive — but a stats result must never be argued over with the
library version unknown.
"""

import math

import scipy
from scipy.stats import norm, binomtest


# The arithmetic bound, not the operational one. With b + c = 5 the smallest
# attainable two-sided exact p is 2 * 0.5**5 = 0.0625 > 0.05, so five discordant
# pairs cannot reach significance however they split. Six can (0.03125).
ARITHMETIC_DISCORDANT_FLOOR = 6

DEFAULT_CONFIDENCE = 0.95


class DiscordantFloorNotMet( RuntimeError ):
    """Too few discordant pairs for the comparison to be able to say anything."""


class FloorNotPreStated( RuntimeError ):
    """Someone asked for a verdict without an operational floor stated up front."""


def scipy_version():
    """
    The scipy build this run actually used.

    Requires:
        - nothing

    Ensures:
        - returns the INSTALLED version string, read at run time
        - is never the pinned version copied from requirements.txt; the two differ
          on this box (pin 1.15.2, installed 1.17.1)

    Raises:
        - nothing
    """
    return scipy.__version__


def mcnemar_exact( b, c ):
    """
    McNemar's exact test on the two discordant cells.

    `b` and `c` are the counts of pairs where exactly ONE arm hit the outcome.
    Concordant pairs are deliberately absent: they cannot distinguish the arms, and
    including them is the classic way to turn a paired comparison into a weaker
    unpaired one.

    Requires:
        - b and c are non-negative ints

    Ensures:
        - returns a dict with b, c, n_discordant, p_value, statistic, test name,
          and the scipy version that computed it
        - p_value is the TWO-SIDED exact binomial p under H0: p = 0.5
        - returns p_value 1.0 for b = c = 0 rather than raising — no discordance is
          "no evidence either way", not an error
        - the statistic is min( b, c ), matching the spec's call shape

    Raises:
        - ValueError if either count is negative
    """
    if b < 0 or c < 0:
        raise ValueError( f"discordant counts must be non-negative, got b={b}, c={c}" )

    n = b + c
    if n == 0:
        p_value = 1.0
    else:
        p_value = binomtest( min( b, c ), n, 0.5 ).pvalue

    return {
        "test"          : "mcnemar_exact",
        "b"             : b,
        "c"             : c,
        "n_discordant"  : n,
        "statistic"     : min( b, c ),
        "p_value"       : p_value,
        "scipy_version" : scipy_version(),
    }


def wilson_interval( successes, trials, confidence=DEFAULT_CONFIDENCE ):
    """
    Wilson score interval, closed-form from `scipy.stats.norm`.

        centre = ( p + z^2/2n ) / ( 1 + z^2/n )
        half   = z * sqrt( p(1-p)/n + z^2/4n^2 ) / ( 1 + z^2/n )

    Requires:
        - 0 <= successes <= trials
        - trials >= 0
        - 0 < confidence < 1

    Ensures:
        - returns ( lower, upper ), both clamped into [ 0, 1 ]
        - returns ( 0.0, 1.0 ) for trials = 0 — total ignorance, honestly stated
        - does NOT collapse to a point at 0 or 100% successes, which is the whole
          reason Wald is refused here
        - uses scipy.stats.norm.ppf and nothing from statsmodels

    Raises:
        - ValueError on impossible counts or a confidence outside ( 0, 1 )
    """
    if trials < 0:             raise ValueError( f"trials must be >= 0, got {trials}" )
    if successes < 0:          raise ValueError( f"successes must be >= 0, got {successes}" )
    if successes > trials:     raise ValueError( f"successes {successes} exceeds trials {trials}" )
    if not 0 < confidence < 1: raise ValueError( f"confidence must be in (0, 1), got {confidence}" )

    if trials == 0: return ( 0.0, 1.0 )

    z          = norm.ppf( 1 - ( 1 - confidence ) / 2 )
    n          = float( trials )
    proportion = successes / n

    denominator = 1 + z * z / n
    centre      = ( proportion + z * z / ( 2 * n ) ) / denominator
    half        = ( z * math.sqrt( proportion * ( 1 - proportion ) / n + z * z / ( 4 * n * n ) ) ) / denominator

    return ( max( 0.0, centre - half ), min( 1.0, centre + half ) )


def wald_lower_bound( successes, trials, confidence=DEFAULT_CONFIDENCE ):
    """
    The FORBIDDEN interval's lower bound — the must-fail control, never a result.

    Present so `must_fail_control()` can demonstrate on real numbers that the two
    methods disagree where it matters. `statsmodels.proportion_confint` defaults to
    this, which is why the spec names that package only as a trap.

    Requires:
        - 0 <= successes <= trials, trials > 0

    Ensures:
        - returns p - z * sqrt( p(1-p)/n ), which is exactly 1.0 at p = 1 because
          the standard error is zero there — certainty asserted from a handful of
          observations

    Raises:
        - ValueError on impossible counts or trials = 0
    """
    if trials <= 0:        raise ValueError( "the Wald bound is undefined for zero trials" )
    if successes > trials: raise ValueError( f"successes {successes} exceeds trials {trials}" )

    z          = norm.ppf( 1 - ( 1 - confidence ) / 2 )
    proportion = successes / float( trials )
    return proportion - z * math.sqrt( proportion * ( 1 - proportion ) / trials )


def must_fail_control():
    """
    The spec's cheap control: at 6/6, Wilson and Wald must disagree.

    Requires:
        - nothing

    Ensures:
        - returns a dict holding both lower bounds and `distinguishes: True` only
          when the Wilson bound is strictly below the Wald bound
        - a run where these agree means the Wilson code silently degraded to Wald,
          which no assertion about "the interval" would otherwise catch

    Raises:
        - nothing
    """
    wilson_low, _ = wilson_interval( 6, 6 )
    wald_low      = wald_lower_bound( 6, 6 )
    return {
        "case"          : "6 of 6",
        "wilson_lower"  : wilson_low,
        "wald_lower"    : wald_low,
        "distinguishes" : wilson_low < wald_low,
        "scipy_version" : scipy_version(),
    }


def assert_floor_pre_stated( n_discordant, operational_floor ):
    """
    Refuse a verdict when too few pairs disagreed, against a floor stated up front.

    Requires:
        - operational_floor is an int stated BEFORE arm 1 ran. There is no default:
          the arithmetic bound is 6, but the effect-size-worthy number is Rick's,
          and a floor chosen after seeing the data is not a floor

    Ensures:
        - returns n_discordant when it meets both the operational floor AND the
          arithmetic bound of 6
        - the message names both numbers, so a refusal is diagnosable

    Raises:
        - FloorNotPreStated when operational_floor is None
        - ValueError when operational_floor is below the arithmetic bound
        - DiscordantFloorNotMet when there were too few discordant pairs
    """
    if operational_floor is None:
        raise FloorNotPreStated(
            "the operational discordant floor must be PRE-STATED before arm 1 — it is Rick's "
            f"number, not this module's. The arithmetic minimum is {ARITHMETIC_DISCORDANT_FLOOR} "
            "(b+c=5 gives a best-case p of 0.0625 and cannot clear 0.05); the effect-size-worthy "
            "number is his call."
        )
    if operational_floor < ARITHMETIC_DISCORDANT_FLOOR:
        raise ValueError(
            f"an operational floor of {operational_floor} is below the arithmetic bound of "
            f"{ARITHMETIC_DISCORDANT_FLOOR} — no split of that many discordant pairs can reach "
            f"p < 0.05, so the study could not report a result even in principle."
        )
    if n_discordant < operational_floor:
        raise DiscordantFloorNotMet(
            f"{n_discordant} discordant pair(s), under the pre-stated floor of {operational_floor}. "
            f"The arms did not disagree often enough for this comparison to say anything."
        )
    return n_discordant


def compare_arms( b, c, operational_floor, arm_a="phi_4", arm_b="flash_lite",
                  confidence=DEFAULT_CONFIDENCE ):
    """
    The study's verdict on one outcome: McNemar exact plus a Wilson interval.

    The proportion the interval covers is b / ( b + c ) — among the pairs where the
    arms DISAGREED, the share that went arm_a's way. That is the quantity McNemar
    tests, so the interval and the p-value describe the same number.

    Requires:
        - b, c are the discordant counts from `replay_harness.discordant_counts`
        - operational_floor was stated before arm 1 ran

    Ensures:
        - returns a dict carrying the test result, the Wilson interval, the
          must-fail control, the floor that was applied, and the scipy version
        - RAISES rather than returning a verdict when the floor is unmet

    Raises:
        - FloorNotPreStated / DiscordantFloorNotMet / ValueError per the guards
    """
    assert_floor_pre_stated( b + c, operational_floor )

    test         = mcnemar_exact( b, c )
    lower, upper = wilson_interval( b, b + c, confidence=confidence )

    return {
        "arm_a"                  : arm_a,
        "arm_b"                  : arm_b,
        "mcnemar"                : test,
        "proportion_favouring_a" : b / float( b + c ),
        "wilson_interval"        : { "lower": lower, "upper": upper, "confidence": confidence },
        "operational_floor"      : operational_floor,
        "arithmetic_floor"       : ARITHMETIC_DISCORDANT_FLOOR,
        "must_fail_control"      : must_fail_control(),
        "scipy_version"          : scipy_version(),
        "statsmodels_used"       : False,
    }
