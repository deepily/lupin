"""
The receipt writer for the verdict layer's fitted threshold.

It joins the answered pairs of a run to the negatives record. It fits the old question's one cut-off on
the fit half of the recorded split. Then it writes a receipt.
The rate of false reuse it may tolerate is a required argument with no default.
The strong cut-off is recorded as a default that was not fitted, since the answered rows carry no confidence.
No model is called.
"""
import argparse
import hashlib
import json
import pathlib

from cosa.repo.symindex import labelled_set as ls
from lupin_mcp import reuse_stage2_fit as fit

FORMAT        = "verdict-fit-1"
STRONG_VALUE  = 0.9
BAND_MISSING_REASON = "not measured: the band is set from repeat jitter of the same answers, which needs a repeat run; no band is invented here"
BAND_GIVEN_REASON   = "given on the command line from a measurement made elsewhere; it was not fitted here"
STRONG_REASON = "the answered rows carry p_overlap but no probabilities, so no confidence; strong needs overlap and confidence both at the cut, so it is not fitted here"


def receipt( negatives, rows, split, rate, rows_sha256, band=None ):
    """
    Fit the threshold and describe the labelled set it was fitted on.

    Requires:
        - negatives is a stage2-negatives-1 record; rows are stage2-rows-1 rows; split is a recorded split
        - rate is the allowed false-reuse rate, chosen by a person
        - band is None or a band measured elsewhere

    Ensures:
        - returns the receipt: format, rate, inputs, set counts, uncovered pairs by class, the fitted threshold,
          strong as a default that was not fitted with its reason, and the chosen cut read on both halves
        - the threshold is the old question's one cut-off, fitted on the fit half only
        - band is recorded as given and not fitted, or as not measured when None; a band the labelled set's check refuses is never recorded

    Raises:
        - ValueError when an uncovered pair is a twin, since the fit would then read a set missing its positives
        - ValueError from ls.check_band for a band outside 0.05 up to 0.5
        - the errors of ls.build and of the fit
    """
    if band is not None: ls.check_band( band )
    built = ls.build( negatives, rows )
    if built[ "uncovered_counts" ][ "twins" ]: raise ValueError( f"{built[ 'uncovered_counts' ][ 'twins' ]} twin pair(s) have no answer; the fit would read a set missing its positives" )
    rep = fit.old_report( built[ "rows" ], split, rate )
    return { "format": FORMAT, "rate": rate,
             "inputs": { **{ k: negatives[ "inputs" ][ k ] for k in ( "manifest_sha256", "symbols_sha256", "old_stage2_sha256" ) }, "answered_rows_sha256": rows_sha256 },
             "set": { "rows": built[ "answered" ], "twin_rows": sum( 1 for r in built[ "rows" ] if r[ "label" ] ), "held_out": built[ "held_out" ], "ignored_rows": built[ "ignored_rows" ] },
             "uncovered_counts": built[ "uncovered_counts" ], "uncovered": built[ "uncovered" ],
             "threshold": { "value": rep[ "chosen" ][ "cut" ], "fitted": True, "rate_binds": rep[ "rate_binds" ], "tied": rep[ "tied" ], "edges": rep[ "edges" ] },
             "strong": { "value": STRONG_VALUE, "fitted": False, "reason": STRONG_REASON },
             "band": { "value": band, "fitted": False, "reason": BAND_MISSING_REASON if band is None else BAND_GIVEN_REASON },
             "on_fit": rep[ "on_fit" ], "on_check": rep[ "on_check" ], "counts": rep[ "counts" ] }


def main( argv=None ):
    """
    Write the receipt for a negatives record, a rows file and a recorded split.

    Ensures:
        - writes the receipt to --out and prints the threshold line, then returns 0

    Raises:
        - FileExistsError when the output file exists, which the exclusive create decides at the moment of writing, so a recorded fit is never overwritten
    """
    ap = argparse.ArgumentParser( description=__doc__ )
    for flag in ( "--negatives", "--rows", "--split", "--out" ): ap.add_argument( flag, required=True )
    ap.add_argument( "--rate", type=float, required=True, help="the false-reuse rate allowed; there is no default" )
    ap.add_argument( "--band", type=float, default=None, help="a band measured from repeat jitter elsewhere; refused under 0.05" )
    a   = ap.parse_args( argv )
    out = pathlib.Path( a.out )
    raw  = pathlib.Path( a.rows ).read_bytes()
    data = json.loads( raw )
    rec  = receipt( json.loads( pathlib.Path( a.negatives ).read_text() ), data[ "rows" ] if isinstance( data, dict ) else data,
                    json.loads( pathlib.Path( a.split ).read_text() ), a.rate, hashlib.sha256( raw ).hexdigest(), a.band )
    with open( out, "x", encoding="utf-8" ) as handle: handle.write( json.dumps( rec, indent=1, sort_keys=True ) + "\n" )
    print( f"threshold={rec[ 'threshold' ][ 'value' ]} rate={a.rate} rows={rec[ 'set' ][ 'rows' ]} uncovered={rec[ 'uncovered_counts' ]}" )
    return 0


if __name__ == "__main__":
    raise SystemExit( main() )
