"""
Compare two live-run arms on a PRE-REGISTERED metric.

🔴 THE METRIC, FIXED BEFORE THE DATA LANDED (María, 2026-08-07):

    expected saving per message ATTEMPTED = delivery_rate × mean_gain

per band, token-based, with the fail-closed rate reported beside it — never
compression alone.

WHY THIS AND NOT DELIVERED-MEAN-GAIN. Delivered-mean is survivor-biased. Push
the model harder and more messages fail validation; the ones that survive are
exactly the ones where aggressive compression happened to work. So an arm's
DELIVERED mean can RISE while the arm is WORSE overall. An arm that compresses
30% of messages by 40% beats one that compresses 10% by 60%, and only the
attempted-basis metric says so.

Reading a delivered-mean and calling it a win is the specific mistake this
script exists to prevent, which is why the metric was written down before the
second arm finished rather than chosen afterwards from what the numbers offered.

Usage:  python compare_arms.py io/arm4/live-run-50per-band.jsonl \\
                              io/arm4/live-run-50per-band-armB.jsonl
"""

import json
import statistics
import sys

BANDS       = [ "<80", "80-150", "150-250", "250+" ]
BAND_TARGET = { "<80": 0.15, "80-150": 0.30, "150-250": 0.45, "250+": 0.60 }


REQUIRED = ( "band", "delivered", "token_ratio", "in_tokens", "out_tokens", "latency" )


def load( path ):
    """
    Read one arm's rows, refusing anything this script cannot read honestly.

    The schema check is not ceremony. Rows written by an earlier version of the
    harness lack `band`, and without this the failure is a bare KeyError three
    frames deep — which reads as a bug in the comparison rather than as "you
    pointed this at the wrong file". Fail loud, and say which file and which key.
    """
    rows = []
    with open( path ) as handle:
        for line in handle:
            line = line.strip()
            if line: rows.append( json.loads( line ) )

    if not rows: raise SystemExit( f"{path}: no rows" )

    missing = [ k for k in REQUIRED if k not in rows[ 0 ] ]
    if missing:
        raise SystemExit(
            f"{path}: rows are missing {missing} — this file was written by an older "
            f"harness and cannot be compared on the pre-registered metric. Re-run it."
        )

    return rows


def band_stats( rows, band ):
    """
    The pre-registered numbers for one band.

    Ensures:
        - attempted_mean is delivery_rate * delivered_mean, computed directly
          over every sampled message so a fallback contributes a real zero
        - returns None when the band has no rows
    """
    in_band = [ r for r in rows if r[ "band" ] == band ]
    if not in_band: return None

    won = [ r for r in in_band if r[ "delivered" ] ]

    return {
        "n"              : len( in_band ),
        "delivery_rate"  : len( won ) / len( in_band ),
        "delivered_mean" : statistics.mean( r[ "token_ratio" ] for r in won ) if won else 0.0,
        # THE metric. Equivalent to delivery_rate * delivered_mean, but computed
        # over all rows so it cannot drift from the definition.
        "attempted_mean" : statistics.mean(
            r[ "token_ratio" ] if r[ "delivered" ] else 0.0 for r in in_band
        ),
        "tokens_in"      : sum( r[ "in_tokens" ] for r in in_band ),
        "tokens_saved"   : sum( r[ "in_tokens" ] - r[ "out_tokens" ] for r in won ),
        "latency_p50"    : statistics.median( r[ "latency" ] for r in in_band ),
    }


def report( label, rows ):
    print( f"\n### {label}  (n={len(rows)})" )
    print( f"{'band':<9}{'n':>4}{'deliv':>8}{'attempted':>11}{'delivered':>11}{'target':>8}   verdict" )

    for b in BANDS:
        s = band_stats( rows, b )
        if not s: continue
        target  = BAND_TARGET[ b ]
        verdict = "MEETS" if s[ "attempted_mean" ] >= target else f"short {target - s['attempted_mean']:.0%}"
        print( f"{b:<9}{s['n']:>4}{s['delivery_rate']:>7.0%}"
               f"{s['attempted_mean']:>11.1%}{s['delivered_mean']:>11.1%}"
               f"{target:>8.0%}   {verdict}" )

    total_in    = sum( r[ "in_tokens" ] for r in rows )
    total_saved = sum( r[ "in_tokens" ] - r[ "out_tokens" ] for r in rows if r[ "delivered" ] )
    print( f"{'ALL':<9}{len(rows):>4}"
           f"{sum(1 for r in rows if r['delivered'])/len(rows):>7.0%}"
           f"{total_saved/total_in:>11.1%}" )


def compare( a_rows, b_rows ):
    print( "\n" + "=" * 78 )
    print( "ARM B minus ARM A, on the pre-registered metric (attempted basis)" )
    print( f"{'band':<9}{'A attempt':>11}{'B attempt':>11}{'delta':>9}   "
           f"{'A deliv':>9}{'B deliv':>9}   note" )

    for b in BANDS:
        sa, sb = band_stats( a_rows, b ), band_stats( b_rows, b )
        if not ( sa and sb ): continue

        delta      = sb[ "attempted_mean" ] - sa[ "attempted_mean" ]
        deliv_drop = sb[ "delivery_rate" ] - sa[ "delivery_rate" ]

        # The survivor-bias tell: delivered-mean up while the attempted basis is
        # flat or down means the arm bought its headline number by failing more.
        note = ""
        if sb[ "delivered_mean" ] > sa[ "delivered_mean" ] and delta <= 0:
            note = "⚠️ delivered-mean UP but attempted DOWN — survivor bias"
        elif deliv_drop < -0.10:
            note = f"fail-closed rose {abs(deliv_drop):.0%}"

        print( f"{b:<9}{sa['attempted_mean']:>11.1%}{sb['attempted_mean']:>11.1%}"
               f"{delta:>+9.1%}   {sa['delivery_rate']:>8.0%}{sb['delivery_rate']:>9.0%}   {note}" )

    a_saved = sum( r[ "in_tokens" ] - r[ "out_tokens" ] for r in a_rows if r[ "delivered" ] )
    b_saved = sum( r[ "in_tokens" ] - r[ "out_tokens" ] for r in b_rows if r[ "delivered" ] )
    a_in    = sum( r[ "in_tokens" ] for r in a_rows )

    print()
    print( f"whole-sample saving: A {a_saved/a_in:.1%}  →  B {b_saved/a_in:.1%}"
           f"  ({b_saved - a_saved:+,} tokens on {a_in:,})" )

    print()
    print( "⚠️ CONFOUND, stated rather than left implicit: arm B changes BOTH the"
           " target number\n   AND the amount of instruction. If B wins, this run"
           " cannot say which did it.\n   A third arm — same extra instruction,"
           " no number — would separate them. Not run today." )


if __name__ == "__main__":
    if len( sys.argv ) < 3:
        print( __doc__ )
        sys.exit( 1 )

    a_rows, b_rows = load( sys.argv[ 1 ] ), load( sys.argv[ 2 ] )
    report( "ARM A — control (template as written)", a_rows )
    report( "ARM B — band target injected per message", b_rows )
    compare( a_rows, b_rows )
