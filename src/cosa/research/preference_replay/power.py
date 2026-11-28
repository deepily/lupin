"""
Power and minimum detectable gain for two arms scored on the same cards.

The two arms are paired, so the figures come from the share of cards on which they disagree, not from two
independent proportions. The formulas are the normal approximation to the paired test of two proportions
(Connor, 1987). They treat cards as independent, which one owner's cards are not.
The plan is 2026.11.23-answer-signal-experiment-plan.md, on the smallest worthwhile gain.
"""
import math
from statistics import NormalDist

NO_GAIN_LARGE_ENOUGH = "no gain up to the disagreement rate reaches the power on this many cards"
ALPHA                = 0.05
TARGET_POWER         = 0.8


def _check( disagreement, cards, alpha ):
    """
    Refuse inputs no power figure exists for.

    Raises:
        - ValueError when disagreement is outside ( 0, 1 ], cards is below 1 or alpha is outside ( 0, 1 )
    """
    if not 0 < disagreement <= 1: raise ValueError( f"the disagreement rate must be above 0 and at most 1, not {disagreement}" )
    if not cards >= 1: raise ValueError( f"at least 1 card is needed, not {cards}" )
    if not 0 < alpha < 1: raise ValueError( f"alpha must be between 0 and 1, not {alpha}" )


def power( gain, disagreement, cards, alpha=ALPHA ):
    """
    Return the chance that a two-sided paired test at alpha finds a gain of this size.

    Requires:
        - gain is the difference between the two arms' shares of correct cards, in the better arm's favour
        - disagreement is the share of cards on which exactly one arm is right; cards is the number of paired cards

    Ensures:
        - returns Phi( ( gain * sqrt( cards ) - z * sqrt( disagreement ) ) / sqrt( disagreement - gain ** 2 ) ), z the two-sided point of alpha
        - the chance of a significant result in the wrong direction is left out, so a gain of 0 gives alpha / 2
        - when gain and disagreement are both 1 every card favours one arm, and the figure is 1 if gain * sqrt( cards ) passes z, else 0

    Raises:
        - ValueError as _check does, or when gain is below 0 or above the disagreement rate
    """
    _check( disagreement, cards, alpha )
    if not 0 <= gain <= disagreement: raise ValueError( f"the gain must be from 0 to the disagreement rate {disagreement}, not {gain}" )
    excess = gain * math.sqrt( cards ) - NormalDist().inv_cdf( 1 - alpha / 2 ) * math.sqrt( disagreement )
    spread = math.sqrt( disagreement - gain * gain )
    if spread == 0: return 1.0 if excess > 0 else 0.0
    return NormalDist().cdf( excess / spread )


def minimum_detectable_gain( disagreement, cards, target=TARGET_POWER, alpha=ALPHA ):
    """
    Return the smallest gain these cards detect at the target power.

    Requires:
        - disagreement, cards and alpha are as power takes them; target is from 0.5 up to, not including, 1

    Ensures:
        - returns { gain, reason, disagreement, cards, power, alpha }
        - gain is the g that solves g * sqrt( cards ) = z * sqrt( disagreement ) + z_target * sqrt( disagreement - g ** 2 )
        - gain is None with the reason when no g up to the disagreement rate reaches the target

    Raises:
        - ValueError as _check does, or when target is outside [ 0.5, 1 )
    """
    _check( disagreement, cards, alpha )
    if not 0.5 <= target < 1: raise ValueError( f"the target power must be from 0.5 up to 1, not {target}" )
    out    = { "gain": None, "reason": NO_GAIN_LARGE_ENOUGH, "disagreement": disagreement, "cards": cards, "power": target, "alpha": alpha }
    needed = NormalDist().inv_cdf( 1 - alpha / 2 ) * math.sqrt( disagreement )
    spread = NormalDist().inv_cdf( target )
    inside = disagreement * ( cards + spread * spread ) - needed * needed
    if inside < 0: return out
    gain   = ( needed * math.sqrt( cards ) + spread * math.sqrt( inside ) ) / ( cards + spread * spread )
    if gain <= disagreement: out.update( gain=gain, reason=None )
    return out
