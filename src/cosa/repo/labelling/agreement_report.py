"""
Agreement report: Rick against each AI reader, and the readers against each other.

Rick's side is his blind share. Kappa comes from agreement.cohen_kappa and is read against the 0.7 bar. A kappa that cannot be computed is None with the reason.
The plan is 2026.11.23-answer-signal-experiment-plan.md, the section on who the readers are.
"""
import argparse
import hashlib
import json
import pathlib
import sys

from cosa.repo.labelling import agreement as ag
from cosa.repo.labelling import errors as er
from cosa.repo.labelling import gold_store as gs
from cosa.repo.labelling import packets as pk
from cosa.repo.labelling import rick_export as rx
from cosa.repo.labelling import rick_page as rp

KAPPA_BAR     = 0.7
READERS       = ( "reader-1", "reader-2" )
BLIND_SUFFIX  = rx.batch_id_of( "", rp.DRAW_SECTION )[ len( "rick--" ): ]
KIND_ALL      = "all"
NO_PAIRS      = "no pairs to compare"


def kappa_or_none( pairs ):
    """
    Compute kappa over answer labels, or say why it cannot be computed.

    Requires:
        - pairs is a list of ( label of A, label of B ), every label one of the answer labels

    Ensures:
        - returns { n, kappa, reason, raw_agreement, meets_bar }
        - kappa is cohen_kappa's value, or None with the reason when the list is empty or both sides used one label throughout
        - meets_bar is kappa at or above KAPPA_BAR, or None when kappa is None
        - raw_agreement is the share of pairs with equal labels, None for an empty list
    """
    n = len( pairs )
    agreed = None if not n else sum( 1 for a, b in pairs if a == b ) / n
    if not n: return { "n": 0, "kappa": None, "reason": NO_PAIRS, "raw_agreement": None, "meets_bar": None }
    try:
        kappa = ag.cohen_kappa( pairs, pk.ANSWER_LABELS )
    except er.LabellingError as e:
        if e.code != er.KAPPA_UNDEFINED: raise
        return { "n": n, "kappa": None, "reason": e.detail, "raw_agreement": agreed, "meets_bar": None }
    return { "n": n, "kappa": kappa, "reason": None, "raw_agreement": agreed, "meets_bar": kappa >= KAPPA_BAR }


def relations_by_item( lines, source, reader, batch_suffix=None ):
    """
    Pick one labeller's latest relation for each item.

    Requires:
        - lines is gold_store.read_gold's list; batch_suffix is None or text

    Ensures:
        - returns { item_id: relation } from the latest line of that source and reader
        - with a batch_suffix, only lines whose batch id ends with it are considered before the latest is taken, so a later line from another batch never overrides
    """
    kept = [ l for l in lines if batch_suffix is None or l[ "batch_id" ].endswith( batch_suffix ) ]
    return { l[ "item_id" ]: l[ "relation" ] for l in gs.latest_lines( kept ) if l[ "source" ] == source and l[ "reader" ] == reader }


def rick_blind_share( lines ):
    """
    Pick Rick's labels of his blind share.

    Requires:
        - lines is gold_store.read_gold's list

    Ensures:
        - returns { item_id: relation } from his latest line inside the blind-share batches, whatever he said about the item in a later batch
        - a line from his reader-disagreement section is left out, since it is not a blind label
    """
    return relations_by_item( lines, gs.SOURCE_HUMAN, rx.READER, BLIND_SUFFIX )


def compare( first, second, types ):
    """
    Report kappa between two labellers, overall and by card type.

    Requires:
        - first and second map item ids to relations; types maps item ids to a card type

    Ensures:
        - returns { "all": report, "<type>": report, ... } with a kappa_or_none report for every type that appears in types, whether or not both labelled one
        - only items both labelled are paired
        - an item with no type is counted in all and in no type
    """
    shared = sorted( set( first ) & set( second ) )
    out    = { KIND_ALL: kappa_or_none( [ ( first[ i ], second[ i ] ) for i in shared ] ) }
    for kind in sorted( set( types.values() ) ): out[ kind ] = kappa_or_none( [ ( first[ i ], second[ i ] ) for i in shared if types.get( i ) == kind ] )
    return out


def report( lines, types, readers=READERS ):
    """
    Build the agreement report.

    Requires:
        - lines is gold_store.read_gold's list; types maps item ids to a card type; readers are two reader names

    Ensures:
        - returns { bar, rick_items, rick_against: { reader: compare }, readers_against_each_other: compare }
        - rick_against pairs Rick's blind-share labels with that reader's, and is the figure the bar applies to
        - readers_against_each_other pairs the two readers on every item both labelled and is a reproducibility figure, not a human bar
        - a kappa that cannot be computed is None with its reason, never 0 or 1
    """
    rick = rick_blind_share( lines )
    each = { r: relations_by_item( lines, gs.SOURCE_READER, r ) for r in readers }
    return { "bar": KAPPA_BAR, "rick_items": len( rick ), "rick_against": { r: compare( rick, each[ r ], types ) for r in readers },
             "readers_against_each_other": compare( each[ readers[ 0 ] ], each[ readers[ 1 ] ], types ) }


def main( argv=None ):
    """
    Print the agreement report as JSON.

    Requires:
        - argv is --types FILE (the item-to-card-type mapping), with optional --store and --out

    Ensures:
        - reads the types file and the gold store and changes neither; prints the report as sorted-key json with the types file's sha256, and writes it to --out when given and not yet present; returns 0
        - returns 2 when a file cannot be read, or the --out file exists
    """
    ap = argparse.ArgumentParser( description="Rick-against-reader agreement report." )
    ap.add_argument( "--types", required=True )
    ap.add_argument( "--store", default=None )
    ap.add_argument( "--out", default=None )
    args = ap.parse_args( argv )
    try:
        raw   = pathlib.Path( args.types ).read_bytes()
        types = json.loads( raw.decode( "utf-8" ) )
        lines = gs.read_gold( pathlib.Path( args.store ) if args.store else gs.default_path() )
    except ( OSError, ValueError, er.LabellingError ) as e:
        print( f"cannot read the types file or the store: {e!r}", file=sys.stderr )
        return 2
    text = json.dumps( { **report( lines, types ), "card_types": { "file": args.types, "sha256": hashlib.sha256( raw ).hexdigest(), "items": len( types ) } }, indent=1, sort_keys=True )
    if args.out:
        try:
            with open( args.out, "x", encoding="utf-8" ) as f: f.write( text + "\n" )
        except OSError as e:
            print( f"cannot write {args.out}: {e!r}", file=sys.stderr )
            return 2
    print( text )
    return 0


if __name__ == "__main__":  # pragma: no cover - entry point
    sys.exit( main() )
