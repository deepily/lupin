"""
Two small statistics shared by the duplicate check proof and the reuse tools.

Both are pure functions over numbers, with no file, model or network access.
"""
import math


def mcnemar_exact( only_a, only_b ):
    """
    Return the exact two-sided McNemar p of two discordant counts.

    Requires:
        - only_a and only_b are non-negative integers, the pairs only one side got right

    Ensures:
        - returns 1.0 when both are zero
        - otherwise returns twice the binomial tail at the smaller count, capped at 1.0
    """
    n = only_a + only_b
    if n == 0: return 1.0
    low = min( only_a, only_b )
    return min( 1.0, 2 * sum( math.comb( n, i ) for i in range( low + 1 ) ) / 2 ** n )


def percentile( values, q ):
    """
    Return the q-th percentile of values by linear interpolation.

    Requires:
        - values is a list of numbers, in any order
        - q is between 0 and 1

    Ensures:
        - returns None for an empty list
        - otherwise returns the interpolated value between the two nearest ranks
    """
    if not values: return None
    ordered = sorted( values )
    place   = q * ( len( ordered ) - 1 )
    low     = math.floor( place )
    return ordered[ low ] + ( place - low ) * ( ordered[ min( low + 1, len( ordered ) - 1 ) ] - ordered[ low ] )
