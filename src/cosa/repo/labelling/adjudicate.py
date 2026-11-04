"""Disputes between two reviewers, and the final label of every item."""
from cosa.repo.labelling import errors as er
from cosa.repo.labelling.agreement import paired
from cosa.repo.labelling.packets import CHOICES, OTHER

AGREED          = "agreed"
RICK_TIEBREAK   = "rick_tiebreak"
MODEL_AGREED    = "model_agreed"


def differs( a, b ):
    """Return True when two labels of one item disagree on the choice or the symbols."""
    return a[ "choice" ] != b[ "choice" ] or set( a[ "symbols" ] ) != set( b[ "symbols" ] )


def disputes( labels_a, labels_b ):
    """
    List the items the two reviewers did not settle between themselves.

    Requires:
        - the reviewers labelled the same items

    Ensures:
        - returns the item ids, sorted, where the choices differ or the symbol sets of the other-choice differ
    """
    return [ a[ "item_id" ] for a, b in paired( labels_a, labels_b ) if differs( a, b ) ]


def resolve( labels_a, labels_b, tiebreaks, unlabelled=() ):
    """
    Give every item its final label.

    Requires:
        - tiebreaks maps a disputed item id to { choice, symbols }; unlabelled lists items no human saw

    Ensures:
        - returns { item_id: { choice, symbols, final_source } } with final_source agreed, rick_tiebreak or model_agreed
        - an item both reviewers settled keeps their label; a disputed item takes the tiebreak; an unlabelled item has choice and symbols None

    Raises:
        - LabellingError BAD_LABEL for a dispute without a tiebreak, a tiebreak for an item that is not disputed or is invalid, or an unlabelled id that was labelled
    """
    final, disputed = {}, set( disputes( labels_a, labels_b ) )
    for a, b in paired( labels_a, labels_b ):
        if a[ "item_id" ] not in disputed: final[ a[ "item_id" ] ] = { "choice": a[ "choice" ], "symbols": list( a[ "symbols" ] ), "final_source": AGREED }
    stray = sorted( set( tiebreaks ) - disputed )
    if stray: raise er.LabellingError( er.BAD_LABEL, f"tiebreaks for items that are not disputed: {stray[ :5 ]}" )
    for item in sorted( disputed ):
        if item not in tiebreaks: raise er.LabellingError( er.BAD_LABEL, f"{item}: a dispute needs a tiebreak" )
        tie = tiebreaks[ item ]
        if tie[ "choice" ] not in CHOICES or bool( tie[ "symbols" ] ) != ( tie[ "choice" ] == OTHER ):
            raise er.LabellingError( er.BAD_LABEL, f"{item}: the tiebreak needs a choice, and symbols exactly when the choice is OTHER" )
        final[ item ] = { "choice": tie[ "choice" ], "symbols": list( tie[ "symbols" ] ), "final_source": RICK_TIEBREAK }
    for item in unlabelled:
        if item in final: raise er.LabellingError( er.BAD_LABEL, f"{item}: listed as unlabelled but a reviewer labelled it" )
        final[ item ] = { "choice": None, "symbols": None, "final_source": MODEL_AGREED }
    return final
