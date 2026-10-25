"""The proof bar as pure functions, the self-agreement count and the per-stratum rates."""
import fractions

from cosa.repo.doc_lint import harness_report
from cosa.repo.semdup import errors as err
from cosa.repo.semdup.judge import FLAG_VERDICTS

FOUND_BAR     = fractions.Fraction( 4, 5 )
CORRECT_BAR   = fractions.Fraction( 4, 5 )
AGREEMENT_BAR = fractions.Fraction( 9, 10 )


def _figure( successes, trials, bar ):
    """Return one figure with its exact fraction, interval and whether it reaches the bar."""
    ratio = fractions.Fraction( successes, trials )
    return { "successes": successes, "trials": trials, "fraction": str( ratio ), "value": float( ratio ), "interval": harness_report.interval( successes, trials ),
             "passes": ratio >= bar }


def evaluate_bar( counts ):
    """
    Compare the three proof figures with their bars, using exact fractions.

    Requires:
        - counts holds true_pairs and found (true pairs the checker flagged), flags and correct (flags that are true pairs),
          and both and agree (pairs judged in both passes, and those whose flag is the same)

    Ensures:
        - returns { "found", "correct", "agreement", "passed" }: each figure with its counts, fraction, interval and whether it reaches its bar
        - a figure passes when it is at or above its bar, so 80 of 100 passes and 79 of 100 fails
        - passed is True only when all three pass

    Raises:
        - SemdupError NO_FLAGS if the proof raised no flag, because the share of flags that are right is undefined
        - ValueError if there are no true pairs or no pair judged in both passes, or a count exceeds its total
    """
    if counts[ "flags" ] == 0: raise err.SemdupError( err.NO_FLAGS, "the proof raised no flag, so the share of flags that are right is undefined" )
    for total, part in ( ( "true_pairs", "found" ), ( "flags", "correct" ), ( "both", "agree" ) ):
        if counts[ total ] < 1: raise ValueError( f"{total} must be 1 or more, got {counts[ total ]}" )
        if not 0 <= counts[ part ] <= counts[ total ]: raise ValueError( f"{part} must be between 0 and {total} ({counts[ total ]}), got {counts[ part ]}" )
    figures = { "found"     : _figure( counts[ "found" ], counts[ "true_pairs" ], FOUND_BAR ),
                "correct"   : _figure( counts[ "correct" ], counts[ "flags" ], CORRECT_BAR ),
                "agreement" : _figure( counts[ "agree" ], counts[ "both" ], AGREEMENT_BAR ) }
    return { **figures, "passed": all( f[ "passes" ] for f in figures.values() ) }


def agreement( pass0, pass1 ):
    """
    Count how often two passes over the same pairs give the same flag.

    Requires:
        - pass0 and pass1 are lists of verdict rows { id, candidate, verdict }; each ( id, candidate ) pair appears once per pass

    Ensures:
        - returns { flag_agree, four_way_agree, pairs_in_both, pairs_one_pass }
        - only pairs judged in both passes are counted, so the denominator is pairs_in_both and a pair seen in one pass is left out
        - a pair agrees on the flag when both passes put it on the same side of duplicate and near_duplicate against related and distinct
        - a pair agrees four-way when the two verdict words are equal
        - the gated figure is flag_agree over pairs_in_both; four_way_agree is reported beside it and gates nothing

    Raises:
        - ValueError if a pass judges one pair twice
    """
    rulings = []
    for rows in ( pass0, pass1 ):
        seen = {}
        for r in rows:
            key = ( r[ "id" ], r[ "candidate" ] )
            if key in seen: raise ValueError( f"pair {key} is judged twice in one pass" )
            seen[ key ] = r[ "verdict" ]
        rulings.append( seen )
    first, second = rulings
    both          = sorted( set( first ) & set( second ) )
    return { "flag_agree"     : sum( 1 for k in both if ( first[ k ] in FLAG_VERDICTS ) == ( second[ k ] in FLAG_VERDICTS ) ),
             "four_way_agree" : sum( 1 for k in both if first[ k ] == second[ k ] ),
             "pairs_in_both"  : len( both ),
             "pairs_one_pass" : len( set( first ) ^ set( second ) ) }


def stratum_rates( outcomes ):
    """
    Report the found rate of each stratum with its interval.

    Requires:
        - outcomes is a list of { "stratum": name, "found": bool } for the true pairs

    Ensures:
        - returns { stratum: { found, true, value, interval } } in the order the strata first appear
        - reporting only: the figures change no gate
    """
    totals = {}
    for o in outcomes:
        hit, n = totals.get( o[ "stratum" ], ( 0, 0 ) )
        totals[ o[ "stratum" ] ] = ( hit + ( 1 if o[ "found" ] else 0 ), n + 1 )
    return { name: { "found": hit, "true": n, "value": hit / n, "interval": harness_report.interval( hit, n ) } for name, ( hit, n ) in totals.items() }
