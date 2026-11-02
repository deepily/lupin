"""
The control stage of the first 1,000 calls, as a function for the stage runner.

The stage runner takes a zero-argument async function, and this builds the one for the positive control.

It asks the checker about each of Set A's 20 planted pairs in a fixed order. Then it removes them and proves the pool is as it was.
It makes no call of its own. Any call the checker makes is counted by the shared cap that the runner has installed.
"""
from lupin_mcp.reuse_needset import positive_control as pc

NEED_KIND = "work_alike"


def need_for( pair, text ):
    """
    Build the need record the checker takes for one planted pair.

    Requires:
        - pair comes from positive_control.load_pairs; text is the need sentence written from the pair's original

    Ensures:
        - returns { kind, write_lang, seed, need }: the seed is the original's id; it matches no index id, so nothing is left out
        - write_lang is the original's language
    """
    return { "kind": NEED_KIND, "write_lang": pair[ "original" ][ "lang" ], "seed": pair[ "original" ][ "id" ], "need": text }


def control_stage( records, pairs, ask, build_stage ):
    """
    Return the stage function for the positive control.

    Requires:
        - ask is an async function ask( planted pool, pair ) returning the ids the checker sent to the judge for that pair's need
        - records, pairs and build_stage are as positive_control.run_control takes them

    Ensures:
        - the returned function takes no argument and returns a report dict
        - the pool is fingerprinted before the first ask, so a trace left by an ask is caught as well as one left by the plant
        - the pairs are asked one at a time in file order, so the calls fall in a fixed order
        - the report is run_control's, plus by_lang ( found and total per rewrite language ), restored true and stop false
        - a missed pair does not stop the run; the caller scores the misses and sets stop by its own rule

    Raises:
        - NeedsetError CONTROL_NOT_RESTORED from the returned function when the pool or the stage ids changed
        - whatever ask raises, including CALL_CAP_REACHED, which the stage runner turns into a report
    """
    async def stage():
        """Ensures: returns the control report."""
        before  = pc.snapshot( records, build_stage )
        planted = pc.plant( records, pairs )
        asked   = {}
        for p in pairs: asked[ p[ "rewrite" ][ "id" ] ] = await ask( planted, p )
        rep     = pc.run_control( records, pairs, lambda _pool, p: asked[ p[ "rewrite" ][ "id" ] ], build_stage, before )
        by_lang = {}
        for p in pairs:
            row = by_lang.setdefault( p[ "rewrite" ][ "lang" ], { "found": 0, "total": 0 } )
            row[ "total" ] += 1
            row[ "found" ] += 0 if p[ "rewrite" ][ "id" ] in rep[ "missed" ] else 1
        return { **rep, "by_lang": dict( sorted( by_lang.items() ) ), "restored": True, "stop": False }
    return stage
