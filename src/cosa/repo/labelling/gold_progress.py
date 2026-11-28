"""
Track Rick's gold labels of no and neither cards, and when a class may leave the stamp.

The meaning labeller is certified on yes cards only (plan section 6). A class is triggered by 20 cards Rick labelled himself.
It lifts only when the held-back slice also holds 30 cards of the class.
The AI readers' settled count is printed beside Rick's and lifts nothing.
This module never reads the slice ids. The caller hands it the number of slice cards per class.
"""
from cosa.repo.labelling import gold_store as gs

CLASSES     = ( "no", "neither" )
TARGET      = 20
SLICE_FLOOR = 30
CERTIFIED   = ( "yes", )
UNCERTIFIED = ( "no", "neither", "support-on-no", "dissent", "re_frame" )
BASIS       = f"fewer than {TARGET} of Rick's own labelled cards in the class, or fewer than {SLICE_FLOOR} slice cards"


def stamp_line( lifted=() ):
    """
    Write the certification stamp with the lifted classes moved to certified.

    Requires:
        - lifted holds names from the classes list

    Ensures:
        - with nothing lifted, returns the plan's stamp line unchanged

    Raises:
        - ValueError for a class that has no lift rule
    """
    for klass in lifted:
        if klass not in CLASSES: raise ValueError( f"{klass!r} cannot be lifted; only {CLASSES} can" )
    certified   = list( CERTIFIED ) + [ k for k in CLASSES if k in lifted ]
    uncertified = [ k for k in UNCERTIFIED if k not in lifted ]
    return f"certified_classes: [{', '.join( certified )}]   uncertified: [{', '.join( uncertified )}]   basis: {BASIS}"


def labeller_pass_line( klass, slice_counts=None ):
    """
    Re-check one triggered class against the held-back slice.

    Requires:
        - klass is a name from the classes list
        - slice_counts is None, or { class: number of cards of that class in the slice }, as the slice's holder reports it

    Ensures:
        - returns { class, slice_cards, floor, scorable, status }
        - scorable only when the slice holds at least SLICE_FLOOR cards of the class
        - status reads "triggered, scorable" or "triggered, not scorable", with the count when one was given

    Raises:
        - ValueError for a class with no trigger
    """
    if klass not in CLASSES: raise ValueError( f"{klass!r} has no trigger; only {CLASSES} do" )
    held     = ( slice_counts or {} ).get( klass )
    scorable = held is not None and held >= SLICE_FLOOR
    if held is None: status = "triggered, not scorable: no slice count was given"
    else: status = f"triggered, {'' if scorable else 'not '}scorable: the slice holds {held} of {SLICE_FLOOR}"
    return { "class": klass, "slice_cards": held, "floor": SLICE_FLOOR, "scorable": scorable, "status": status }


def gold_progress( gold_labels, slice_counts=None ):
    """
    Count gold no and neither cards and say which classes are triggered and which lift.

    Requires:
        - gold_labels is gold_store.read_gold's list
        - slice_counts is as labeller_pass_line takes it

    Ensures:
        - returns { rick, settled, target, reached, stamp_lifts_for, pass_lines }
        - rick counts the cards Rick labelled himself, settled the cards with a settled label, both by the card's stance class
        - reached and stamp_lifts_for come from the rick counts alone
        - pass_lines holds labeller_pass_line's result for each reached class
        - a class is in stamp_lifts_for only when it is reached and its slice count makes it scorable
    """
    own     = gs.human_card_counts( gold_labels )
    done    = [ entry[ "card_stance" ] for entry in gs.settled( gold_labels )[ "settled" ].values() ]
    reached = [ k for k in CLASSES if own[ k ] >= TARGET ]
    lines   = { k: labeller_pass_line( k, slice_counts ) for k in reached }
    return { "rick": { k: own[ k ] for k in CLASSES }, "settled": { k: done.count( k ) for k in CLASSES }, "target": TARGET,
             "reached": reached, "stamp_lifts_for": [ k for k in reached if lines[ k ][ "scorable" ] ], "pass_lines": lines }
