"""
Census: how often does the DM condenser corrupt a pass/fail claim? — row `96b10a7b`.

Reads the traffic corpus, which retains BOTH halves of every DM (`body` = submitted,
`delivered_body` = delivered). Counts a denominator and a numerator, and prints the
positive controls first so a run that misses them is visibly measuring the wrong thing.

Run: PYTHONPATH=src python3 src/rnd/v0.2.0/dm_passfail_census.py
"""

import json
import os
import re
import sys

CORPUS = "/mnt/DATA01/include/www.deepily.ai/projects-data/lupin/dm-corpus/dm_traffic.jsonl"

# Words that make a numeral a RESULT rather than a quantity in passing.
OUTCOME = r"(?:passed|passing|failed|failing|failure|green|red|xfail|skipped|exits?|exit code|status)"

# A ratio: "19 out of 21", "19/21", "19 of 21".
RATIO = re.compile( r"\b(\d+)\s*(?:out of|of|/)\s*(\d+)\b", re.I )

# A numeral bound to an outcome word, either order: "19 passed", "exits 4", "exit code 4".
BOUND = re.compile( rf"\b(\d+)\s+{OUTCOME}\b|\b{OUTCOME}\s+(?:of\s+|code\s+|with\s+)?(\d+)\b", re.I )

# Delivered text asserting something went wrong.
ASSERTS_FAILURE = re.compile( r"\b(?:failure|failed|failing|error|did not exit|not exit|unsuccessful)\b", re.I )


def carries_a_result( submitted ):
    """True when the SUBMITTED body states a test or exit result at all — the denominator."""

    return bool( BOUND.search( submitted ) )


def bound_numerals( text ):
    """The numerals this text binds to an outcome word."""

    return { a or b for a, b in BOUND.findall( text ) }


def ratios( text ):
    """The (numerator, denominator) pairs this text states."""

    return set( RATIO.findall( text ) )


def fabricated_ratio( submitted, delivered ):
    """D1 — a pass/total ratio the delivered text states and the submitted never did."""

    return sorted( ratios( delivered ) - ratios( submitted ) )


def dropped_result_with_failure_claim( submitted, delivered ):
    """
    D2 — the GREEN-DELIVERED-AS-RED shape, and it is deliberately narrow.

    Requires ALL THREE, because any two of them fire constantly on honest condensation:
      · a numeral the submitted bound to an outcome word is absent from the delivered
      · the delivered asserts failure
      · the SUBMITTED does NOT assert failure — the sender reported no failure at all

    ⚠️ THE THIRD CONDITION IS WHAT MAKES THIS A MEASUREMENT. Without it the detector
    fires on every message that mentions a failure the sender genuinely reported and
    drops any numeral while condensing — measured at 135 hits and a 15.14% "rate" that
    is an artefact of the detector, not a property of the condenser. Sampling those hits
    showed honest rows: "4 failed / 8844 passed" delivered with the counts intact and an
    unrelated numeral dropped. A rate I cannot defend is worse than no rate.
    """

    if ASSERTS_FAILURE.search( submitted ): return []
    if not ASSERTS_FAILURE.search( delivered ): return []

    dropped = { n for n in bound_numerals( submitted ) if n not in delivered }

    return sorted( dropped )


def main():

    if not os.path.exists( CORPUS ):
        print( f"corpus not found: {CORPUS}" ); return 2

    rows = [ json.loads( l ) for l in open( CORPUS, encoding="utf-8", errors="replace" ) if l.strip() ]
    live = [ r for r in rows if r.get( "origin" ) == "live" and r.get( "body_was_rewritten" ) ]

    denom, d1_hits, d2_hits = [], [], []
    for r in live:
        sub, del_ = r.get( "body" ) or "", r.get( "delivered_body" ) or ""
        if not carries_a_result( sub ): continue
        denom.append( r )
        if fabricated_ratio( sub, del_ ):                 d1_hits.append( r )
        if dropped_result_with_failure_claim( sub, del_ ): d2_hits.append( r )

    corrupted = { id( r ) for r in d1_hits } | { id( r ) for r in d2_hits }

    print( "=" * 78 )
    print( "POSITIVE CONTROLS — a method that misses these is measuring something else" )
    print( "=" * 78 )
    for label, needle in ( ( "1  Rio  19-of-21 (re-bound quantity)", "those 21 tests need" ),
                           ( "2  Tiberius exit-4 (dropped + inverted)", "it does not exit 0" ) ):
        found = [ r for r in denom if needle in ( r.get( "body" ) or "" ) ]
        caught = [ r for r in found if id( r ) in corrupted ]
        print( f"  {label:42s} in denominator: {len(found)}   flagged: {len(caught)}" )

    print()
    print( "=" * 78 )
    print( "CENSUS" )
    print( "=" * 78 )
    print( f"  corpus rows                                    {len(rows):6d}" )
    print( f"  live AND rewritten by the condenser            {len(live):6d}" )
    print( f"  DENOMINATOR: of those, submitted states a result {len(denom):5d}" )
    print( f"  D1 fabricated ratio                            {len(d1_hits):6d}" )
    print( f"  D2 dropped result + failure claim              {len(d2_hits):6d}" )
    print( f"  corrupted (union)                              {len(corrupted):6d}" )
    if denom:
        print( f"  RATE                                           {100*len(corrupted)/len(denom):6.2f}%  "
               f"({len(corrupted)}/{len(denom)})" )
    if rows:
        span = ( min( r.get("ts","") for r in rows ), max( r.get("ts","") for r in rows ) )
        print( f"  window                                         {span[0]}  ->  {span[1]}" )

    print()
    print( "=" * 78 )
    print( "EVERY FLAGGED ROW — for manual adjudication, since a detector is not a verdict" )
    print( "=" * 78 )
    for r in sorted( { id(x): x for x in d1_hits + d2_hits }.values(), key=lambda x: x.get("ts","") ):
        sub, del_ = r.get("body") or "", r.get("delivered_body") or ""
        tags = []
        if fabricated_ratio( sub, del_ ):                 tags.append( f"D1 ratio={fabricated_ratio(sub,del_)}" )
        if dropped_result_with_failure_claim( sub, del_ ): tags.append( f"D2 dropped={dropped_result_with_failure_claim(sub,del_)}" )
        print( f"\n  {r.get('ts')}  {r.get('from')} -> {r.get('to')}   {' | '.join(tags)}" )
        print( f"    SUB: ...{' '.join(sub.split())[:170]}..." )
        print( f"    DEL: ...{' '.join(del_.split())[:170]}..." )

    return 0


if __name__ == "__main__":
    sys.exit( main() )
