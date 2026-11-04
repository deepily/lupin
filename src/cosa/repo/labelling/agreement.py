"""Agreement between two reviewers: Cohen's kappa, raw agreement and the choice counts."""
import collections

from cosa.repo.labelling import errors as er
from cosa.repo.labelling.packets import OTHER


def cohen_kappa( pairs, categories ):
    """
    Compute Cohen's kappa over two reviewers' choices.

    Requires:
        - pairs is a non-empty list of ( choice of A, choice of B ); every choice is in categories

    Ensures:
        - returns ( observed - expected ) / ( 1 - expected ), where expected is the agreement two reviewers with these marginals would reach by chance

    Raises:
        - LabellingError BAD_LABEL for an empty list or a choice outside categories
        - LabellingError KAPPA_UNDEFINED when the expected agreement is 1, which is when both reviewers used one category throughout
    """
    if not pairs: raise er.LabellingError( er.BAD_LABEL, "no pairs to compare" )
    for pair in pairs:
        if pair[ 0 ] not in categories or pair[ 1 ] not in categories: raise er.LabellingError( er.BAD_LABEL, f"a choice outside {tuple( categories )}: {pair}" )
    n        = len( pairs )
    observed = sum( 1 for a, b in pairs if a == b ) / n
    first, second = collections.Counter( a for a, _ in pairs ), collections.Counter( b for _, b in pairs )
    expected = sum( ( first[ c ] / n ) * ( second[ c ] / n ) for c in categories )
    if expected == 1: raise er.LabellingError( er.KAPPA_UNDEFINED, "every label is one category" )
    return ( observed - expected ) / ( 1 - expected )


def paired( labels_a, labels_b ):
    """
    Join two reviewers' labels by item.

    Requires:
        - each list holds one label per item

    Ensures:
        - returns [ ( label of A, label of B ) ] in item id order

    Raises:
        - LabellingError BAD_LABEL when the two reviewers did not label the same items
    """
    by_a, by_b = { l[ "item_id" ]: l for l in labels_a }, { l[ "item_id" ]: l for l in labels_b }
    if set( by_a ) != set( by_b ): raise er.LabellingError( er.BAD_LABEL, f"the reviewers labelled different items: {sorted( set( by_a ) ^ set( by_b ) )[ :5 ]}" )
    return [ ( by_a[ i ], by_b[ i ] ) for i in sorted( by_a ) ]


def agreement_report( labels_a, labels_b, categories ):
    """
    Report how far two reviewers agree.

    Requires:
        - the reviewers labelled the same items

    Ensures:
        - returns { n, kappa, raw_agreement, per_category, other_both, other_equal_symbols }
        - kappa reads the choice only; other_both counts the pairs where both chose the other-choice and other_equal_symbols those whose symbol sets are equal
        - raw_agreement counts a pair as agreed when the choices match and, for the other-choice, the symbol sets too

    Raises:
        - LabellingError KAPPA_UNDEFINED or BAD_LABEL as cohen_kappa does
    """
    pairs = paired( labels_a, labels_b )
    kappa = cohen_kappa( [ ( a[ "choice" ], b[ "choice" ] ) for a, b in pairs ], categories )
    both  = [ ( a, b ) for a, b in pairs if a[ "choice" ] == OTHER and b[ "choice" ] == OTHER ]
    equal = sum( 1 for a, b in both if set( a[ "symbols" ] ) == set( b[ "symbols" ] ) )
    agreed = sum( 1 for a, b in pairs if a[ "choice" ] == b[ "choice" ] and set( a[ "symbols" ] ) == set( b[ "symbols" ] ) )
    return { "n": len( pairs ), "kappa": kappa, "raw_agreement": agreed / len( pairs ),
             "per_category": { c: { "a": sum( 1 for a, _ in pairs if a[ "choice" ] == c ), "b": sum( 1 for _, b in pairs if b[ "choice" ] == c ) } for c in categories },
             "other_both": len( both ), "other_equal_symbols": equal }
