"""
How the two-question answer to a packed request is read.

Each entry has a Noul question (does it provide the capability) and a Score question (how much of
the need does it cover, four levels). The Choice reader in reuse_pack needs a probabilities mapping
and would mark every Noul unasked, so this reader is separate. Nothing here sends anything.
"""
import math

LEVELS        = ( "0", "1", "2", "3" )
SUM_TOLERANCE = 0.02            # the policy's sum_tolerance


def _number( value ):
    """Ensures: returns True for an int or float that is not a bool."""
    return isinstance( value, ( int, float ) ) and not isinstance( value, bool )


def _unit_number( value ):
    """Ensures: returns None for a finite number from 0 to 1, else the failed check name."""
    if not _number( value ): return "number"
    if not math.isfinite( value ) or value < 0 or value > 1: return "range"
    return None


def _read_noul( answer ):
    """
    Read one Noul answer.

    Ensures:
        - returns ( value, reasons ): value is the Noul number when reasons is empty, else None
    """
    if answer.get( "type" ) != "noul": return None, [ f"provides: type is {answer.get( 'type' )!r}, not 'noul'" ]
    wrong = _unit_number( answer.get( "noul" ) )
    if wrong: return None, [ f"provides: noul fails the {wrong} check: {answer.get( 'noul' )!r}" ]
    return answer[ "noul" ], []


def _read_score( answer ):
    """
    Read one Score answer.

    Ensures:
        - returns ( probabilities, reasons ): probabilities maps "0" to "3" to numbers, or is None with reasons
    """
    if answer.get( "type" ) != "score": return None, [ f"coverage: type is {answer.get( 'type' )!r}, not 'score'" ]
    probs = answer.get( "probabilities" )
    if not isinstance( probs, dict ) or sorted( probs ) != list( LEVELS ):
        return None, [ f"coverage: levels are not exactly {', '.join( LEVELS )}" ]
    reasons = []
    for level in LEVELS:
        wrong = _unit_number( probs[ level ] )
        if wrong: reasons.append( f"coverage: level {level} fails the {wrong} check: {probs[ level ]!r}" )
    if reasons: return None, reasons
    total = sum( probs[ level ] for level in LEVELS )
    if abs( total - 1 ) > SUM_TOLERANCE: return None, [ f"coverage: probabilities sum to {total:.4f}, not 1 within {SUM_TOLERANCE}" ]
    return probs, []


def pair_answers( response, qmap ):
    """
    Read one response against the two questions asked about each entry.

    Requires:
        - qmap maps an entry id to { "provides": noul question key, "coverage": score question key }
    Ensures:
        - returns ( answered, unasked, malformed ), each entry in exactly one of them, in the order of qmap
        - answered maps an id to { provides, coverage, score, confidence, probabilities }: coverage is the
          sum of levels 2 and 3, and score is the Score's own float or None
        - an answer that is missing or not a mapping is absent; an entry with an absent answer and no
          wrong one is unasked, never read as unrelated
        - an answer that is present and wrong makes the whole entry malformed, listed as
          { id, reasons }; malformed wins over unasked and a valid half is never used
        - two entries that share a question key are both malformed, since one answer cannot be two
        - an answer for a question that was not asked is ignored
    """
    try: answers = response[ "answers" ]
    except ( KeyError, TypeError ): answers = None
    if not isinstance( answers, dict ): return {}, list( qmap ), []
    uses = {}
    for pair in qmap.values():
        for key in ( pair[ "provides" ], pair[ "coverage" ] ): uses[ key ] = uses.get( key, 0 ) + 1
    answered, unasked, malformed = {}, [], []
    for entry_id, pair in qmap.items():
        reasons, absent = [], []
        for key in ( pair[ "provides" ], pair[ "coverage" ] ):
            if uses[ key ] > 1: reasons.append( f"question key {key!r} is repeated across entries" )
        noul_a, score_a = answers.get( pair[ "provides" ] ), answers.get( pair[ "coverage" ] )
        value, probs = None, None
        if isinstance( noul_a, dict ):
            value, found = _read_noul( noul_a )
            reasons += found
        else: absent.append( "provides: no answer" )
        if isinstance( score_a, dict ):
            probs, found = _read_score( score_a )
            reasons += found
        else: absent.append( "coverage: no answer" )
        if reasons: malformed.append( { "id": entry_id, "reasons": reasons + absent } )
        elif absent: unasked.append( entry_id )
        else:
            answered[ entry_id ] = { "provides": value, "coverage": probs[ "2" ] + probs[ "3" ], "score": score_a[ "score" ] if _number( score_a.get( "score" ) ) else None,
                                     "confidence": score_a.get( "confidence" ), "probabilities": dict( probs ) }
    return answered, unasked, malformed
