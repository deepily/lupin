"""
The labelled set of the verdict layer.

build() joins the answered pairs of a run to the negatives record. The record lists the twins, the lexical
neighbours and the random negatives of each member. A pair the record lists and the run never answered is
reported by class. A pair held out for a person to read is left out and counted.

The uncertain band is set from measured repeat jitter.
It may not be narrower than MIN_BAND.
It may not reach MAX_BAND.
decide() takes any band, since it is a pure function of its policy.
The record step refuses a band outside that range through check_band.
"""

MIN_BAND = 0.05      # the plan's exit gate: the band is at least 0.05
MAX_BAND = 0.5       # a band of one half or more would cover the whole range around both cut-offs


def check_band( band ):
    """
    Return the band when it may be recorded.

    Requires:
        - band is a number

    Ensures:
        - returns band unchanged when MIN_BAND <= band < MAX_BAND, so a NaN, an infinity, a bool and a band that covers the range are refused

    Raises:
        - ValueError naming the band and the allowed range otherwise
    """
    if isinstance( band, bool ) or not ( MIN_BAND <= band < MAX_BAND ): raise ValueError( f"band {band!r} is outside the allowed range {MIN_BAND} to under {MAX_BAND}; the plan sets it from measured repeat jitter and at least {MIN_BAND}" )
    return band


CLASSES = ( "twins", "lexical", "random" )


def _id( entry ):
    """Ensures: returns the id of a record entry, which is a bare id or a dict with an id."""
    return entry if isinstance( entry, str ) else entry[ "id" ]


def build( negatives, answered_rows ):
    """
    Join a negatives record to the rows a run answered.

    Requires:
        - negatives is a stage2-negatives-1 record: members with twins, lexical, random and held_out lists
        - answered_rows are dicts with member, candidate, label and the answer fields

    Ensures:
        - returns { rows, uncovered, uncovered_counts, held_out, answered, ignored_rows }
        - rows are the answered rows whose pair the record lists, in the record's member order, then twins, lexical, random
        - a row that was never asked, came back malformed or has no overlap is not answered: its pair is uncovered under its class
        - the label of a row is true exactly when its pair is a twin pair of the record
        - uncovered maps each class to the [ member, candidate ] pairs the record lists and no row answered
        - a held-out pair is in no class; held_out counts them
        - ignored_rows counts the answered rows whose pair is in none of the three classes, a held-out pair among them

    Raises:
        - ValueError naming the pair when the record lists it twice, lists it as held out and in a class, a row answers it twice, or a row's label disagrees with the record
    """
    classed = {}
    for member, entry in negatives[ "members" ].items():
        for cls in CLASSES:
            for item in entry[ cls ]:
                pair = ( member, _id( item ) )
                if pair in classed: raise ValueError( f"pair {pair} is listed twice in the record" )
                classed[ pair ] = cls
    held = { ( member, _id( item ) ) for member, entry in negatives[ "members" ].items() for item in entry[ "held_out" ] }
    for pair in sorted( held & set( classed ) ): raise ValueError( f"pair {pair} is held out and also listed as {classed[ pair ]}" )
    seen = {}
    for row in answered_rows:
        pair = ( row[ "member" ], row[ "candidate" ] )
        if pair in seen: raise ValueError( f"pair {pair} is answered twice" )
        seen[ pair ] = row
    rows, uncovered = [], { cls: [] for cls in CLASSES }
    for pair, cls in classed.items():
        row = seen.get( pair )
        if row is None or row[ "unasked" ] or row[ "malformed" ] is not None or row[ "p_overlap" ] is None:
            uncovered[ cls ].append( list( pair ) )
            continue
        if bool( row[ "label" ] ) != ( cls == "twins" ): raise ValueError( f"pair {pair} is labelled {row[ 'label' ]} but the record lists it as {cls}" )
        rows.append( row )
    return { "rows": rows, "uncovered": uncovered, "uncovered_counts": { cls: len( uncovered[ cls ] ) for cls in CLASSES },
             "held_out": sum( len( e[ "held_out" ] ) for e in negatives[ "members" ].values() ), "answered": len( rows ),
             "ignored_rows": sum( 1 for pair in seen if pair not in classed ) }
