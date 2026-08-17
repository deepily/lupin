#!/usr/bin/env python3
"""
Build a BLIND hand-labelling sheet from a finished paired run (handoff §7 item 5).

WHY IT EXISTS. Blocking on the fabrication guard is DETECTABILITY, not honesty: it
counts what the guard caught, and the guard is one imperfect judge applied identically
to both arms. The handoff asks for a hand-labelled sample of each arm's DELIVERED
output before any honesty claim is made. Nothing automated can do the labelling — but
everything around it can be, and the part that is easy to get wrong is the part a
script should own.

WHY BLIND, AND WHY IT IS THE WHOLE POINT. A labeller who can see which arm produced a
line is not measuring the line. This sheet therefore:
  - strips the arm name and the spec key from every item
  - shuffles the two arms' outputs within each pair, seeded, so position carries no
    information
  - writes the answer key to a SEPARATE file, so the sheet can be handed to a labeller
    (or to a model) with no way to recover the arm
Scoring re-joins the two files by item id.

WHAT THE LABELLER IS ASKED. One question per item, deliberately narrow: does the
delivered text assert anything the source message does not support? That is the
fabrication question the study's headline rests on. Style, brevity and tone are NOT
asked about — they are a different study, and mixing them in is how a labelling task
turns into an opinion poll.

Usage:
    PYTHONPATH=$LUPIN_ROOT/src python src/scripts/phi4_flash_lite_label_sheet.py \
        --results <run>/results.jsonl --out-sheet <run>/label-sheet.md \
        --out-key <run>/label-key.json --sample-size 40 --seed 20260817
"""
import argparse
import json
import random
import sys


def build_items( records, sample_size, seed ):
    """
    Draw paired rows and emit blinded items plus the answer key.

    Requires:
        - records carry `arm`, `row_index`, `body`, `delivered` and `meta`
        - both arms are present for every drawn row_index

    Ensures:
        - returns ( items, key ) where each item holds a source body and TWO blinded
          outputs in a seeded-shuffled order, and the key maps item id + slot -> arm
        - a row whose two arms delivered IDENTICAL text is kept and flagged, not
          dropped: agreement is data, and dropping it would bias the sample toward
          disagreement

    Raises:
        - ValueError if a drawn row is missing one of its arms
    """
    by_row = {}
    for record in records:
        by_row.setdefault( record[ "row_index" ], {} )[ record[ "arm" ] ] = record

    complete = sorted( index for index, arms in by_row.items() if len( arms ) == 2 )
    rng      = random.Random( seed )
    drawn    = sorted( rng.sample( complete, min( sample_size, len( complete ) ) ) )

    items = []
    key   = {}
    for position, row_index in enumerate( drawn, start=1 ):
        arms = by_row[ row_index ]
        if len( arms ) != 2:
            raise ValueError( f"row {row_index} has arms {sorted( arms )}, expected two" )

        item_id = f"item-{position:03d}"
        pair    = sorted( arms.items() )                       # deterministic before the shuffle
        rng.shuffle( pair )                                    # slot A/B carries no arm information

        items.append( {
            "item_id"   : item_id,
            "row_index" : row_index,
            "source"    : pair[ 0 ][ 1 ][ "body" ],
            "outputs"   : [ record[ "delivered" ] for _, record in pair ],
            "identical" : pair[ 0 ][ 1 ][ "delivered" ] == pair[ 1 ][ 1 ][ "delivered" ],
        } )
        key[ item_id ] = {
            "row_index" : row_index,
            "A"         : { "arm": pair[ 0 ][ 0 ], "outcome": pair[ 0 ][ 1 ][ "meta" ].get( "tutor_outcome" ) },
            "B"         : { "arm": pair[ 1 ][ 0 ], "outcome": pair[ 1 ][ 1 ][ "meta" ].get( "tutor_outcome" ) },
        }
    return items, key


def render_sheet( items, seed ):
    """
    Render the blinded sheet as markdown.

    Requires:
        - items came from build_items

    Ensures:
        - returns a string containing no arm name, no spec key and no outcome label
        - every item asks the SAME single question, so answers are comparable

    Raises:
        - nothing
    """
    lines = [
        "# Hand-labelling sheet — Phi-4 vs Flash-Lite, delivered output",
        "",
        f"Blinded, seed `{seed}`. Which model produced A or B is **not** recoverable from this file;",
        "the answer key is a separate file and must stay closed until every item is answered.",
        "",
        "**For each item, answer for A and for B separately:**",
        "",
        "> Does the delivered text assert anything the source message does not support?",
        "> `yes` / `no` / `unsure` — and if `yes`, quote the unsupported part.",
        "",
        "Do **not** judge style, length or tone. Those are a different question, and mixing them in",
        "turns a measurement into an opinion poll.",
        "",
        "---",
        "",
    ]
    for item in items:
        lines.append( f"## {item[ 'item_id' ]}" )
        if item[ "identical" ]:
            lines.append( "" )
            lines.append( "*(A and B delivered identical text — answer once; it counts for both.)*" )
        lines.append( "" )
        lines.append( "### Source message" )
        lines.append( "" )
        lines.append( "```" )
        lines.append( item[ "source" ] )
        lines.append( "```" )
        for slot, output in zip( ( "A", "B" ), item[ "outputs" ] ):
            lines.append( "" )
            lines.append( f"### Delivered {slot}" )
            lines.append( "" )
            lines.append( "```" )
            lines.append( output if output else "(nothing delivered)" )
            lines.append( "```" )
            lines.append( "" )
            lines.append( f"- **{slot} unsupported claim?** `____`  quote: `____`" )
        lines.append( "" )
        lines.append( "---" )
        lines.append( "" )
    return "\n".join( lines )


def main( argv=None, printer=print ):
    """
    Write the blinded sheet and its separate answer key.

    Requires:
        - --results names a finished paired run

    Ensures:
        - the sheet contains no arm attribution; the key is written elsewhere
        - returns 0

    Raises:
        - ValueError from build_items on an unpaired row
    """
    parser = argparse.ArgumentParser( description="Blind hand-labelling sheet for a paired run" )
    parser.add_argument( "--results",     required=True )
    parser.add_argument( "--out-sheet",   required=True )
    parser.add_argument( "--out-key",     required=True )
    parser.add_argument( "--sample-size", type=int, default=40 )
    parser.add_argument( "--seed",        type=int, required=True )
    args = parser.parse_args( argv )

    records = [ json.loads( line ) for line in open( args.results, encoding="utf-8" ) ]
    records = [ r for r in records if r.get( "record_kind" ) != "run_header" ]

    items, key = build_items( records, args.sample_size, args.seed )

    with open( args.out_sheet, "w", encoding="utf-8" ) as handle:
        handle.write( render_sheet( items, args.seed ) )
    with open( args.out_key, "w", encoding="utf-8" ) as handle:
        json.dump( { "seed": args.seed, "sample_size": len( items ), "key": key }, handle, indent=2 )

    printer( f"sheet: {len( items )} items -> {args.out_sheet}" )
    printer( f"key  : {args.out_key} (keep closed until labelling is finished)" )
    return 0


if __name__ == "__main__":
    sys.exit( main() )
