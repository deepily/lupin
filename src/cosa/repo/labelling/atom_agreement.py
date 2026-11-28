"""
Agreement between two readers on condition atoms: atom-level precision and recall.

An atom is one action-critical condition a reader named for an item, written as a string.
Two atoms are the same when their strings are equal, so the caller settles spelling and wording before it calls.
A figure with no atoms in its denominator is None with the reason, never 0 or 1.
The plan is 2026.11.23-answer-signal-experiment-plan.md, the section on gold labels and a validated judge.
"""
from cosa.agents.prediction_engine.accuracy_comparators import decompose_atoms
from cosa.repo.labelling import errors as er

NO_OTHER_ATOMS     = "the other reader named no atom"
NO_REFERENCE_ATOMS = "the reference reader named no atom"


def atom_agreement( reference, other ):
    """
    Score one reader's condition atoms against another's, pooled over all items.

    Requires:
        - reference and other map an item id to a collection of atom strings; a reader who named no condition for an item gives it an empty collection

    Ensures:
        - returns { items, reference_atoms, other_atoms, shared_atoms, precision, precision_reason, recall, recall_reason, only_reference, only_other }
        - an atom counts once for each item, however often one reader repeats it, and matches only under the same item
        - precision is shared_atoms over other_atoms and recall is shared_atoms over reference_atoms
        - a figure with an empty denominator is None and its reason says whose atoms are missing; a defined figure has the reason None
        - only_reference and only_other list the unmatched ( item id, atom ) pairs, sorted

    Raises:
        - LabellingError BAD_LABEL when there is no item, when the readers did not label the same items, or when an item's atoms are one string or hold a value that is not a non-blank string
    """
    if set( reference ) != set( other ): raise er.LabellingError( er.BAD_LABEL, f"the readers labelled different items: {sorted( set( reference ) ^ set( other ) )[ :5 ]}" )
    if not reference: raise er.LabellingError( er.BAD_LABEL, "no items to compare" )
    sides = []
    for labels in ( reference, other ):
        pairs = set()
        for item_id, atoms in labels.items():
            if isinstance( atoms, str ) or not all( isinstance( a, str ) and a.strip() for a in atoms ):
                raise er.LabellingError( er.BAD_LABEL, f"{item_id}: atoms must be a collection of non-blank strings" )
            pairs.update( ( item_id, a ) for a in atoms )
        sides.append( pairs )
    first, second = sides
    split         = decompose_atoms( second, first )
    shared        = len( split[ "hits" ] )
    return { "items": len( reference ), "reference_atoms": len( first ), "other_atoms": len( second ), "shared_atoms": shared,
             "precision": split[ "precision" ] if second else None, "precision_reason": None if second else NO_OTHER_ATOMS,
             "recall": split[ "recall" ] if first else None, "recall_reason": None if first else NO_REFERENCE_ATOMS,
             "only_reference": split[ "omissions" ], "only_other": split[ "additions" ] }
