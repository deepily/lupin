"""
Split a total into whole parts by a mix, rounding by the largest remainders.

Shared by the labelled-pair seeder and the diagnostic need set, so a split is computed one way.
"""
import math


def quotas( total, mix ):
    """
    Split total by mix with largest remainders, so the parts sum to total exactly.

    Requires:
        - total is a whole number of 0 or more
        - mix maps each part name to a share of 0 or more; the shares need to sum to 1 for a full split

    Ensures:
        - returns a dict with the keys of mix and whole-number values
        - the values sum to total whenever the shares sum to 1
        - ties between equal remainders go to the smaller key
    """
    raw   = { k: total * v for k, v in mix.items() }
    parts = { k: int( math.floor( v ) ) for k, v in raw.items() }
    for k in sorted( raw, key=lambda k: ( -( raw[ k ] - parts[ k ] ), k ) )[ :total - sum( parts.values() ) ]: parts[ k ] += 1
    return parts
