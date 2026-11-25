#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
Write the card type of every sample item, for the agreement report.

The type comes read-only from the same source as the draw, build_answer_card_sample.population().
The packet file is read and never changed; the mapping file is written once and never overwritten.

Run from the main checkout, pinning all three:

    cd <tree> && LUPIN_ROOT="$PWD" PYTHONPATH="$PWD/src" .venv/bin/python src/scripts/build_item_card_types.py --packet <packet> --out <file>
"""

import argparse
import hashlib
import json
import os
import pathlib
import sys

import cosa.utils.util as cu
import build_answer_card_sample as bas
import filter_stop_hook_cards as fsh
from cosa.repo.labelling import errors as er
from cosa.repo.labelling.rick_page import ids_sha256


def card_types( packet, population ):
    """
    Give every item of the packet the type of its card.

    Requires:
        - packet is { blind, refs } as build_answer_card_sample writes it
        - population is { card type: [ card ids ] } as build_answer_card_sample.population returns

    Ensures:
        - returns { item_id: card type } for every item of the packet

    Raises:
        - LabellingError BAD_ITEM for an item with no ref, a card in no type's population or a card in more than one
    """
    of_card = {}
    for card_type, ids in population.items():
        for card in ids: of_card.setdefault( card, [] ).append( card_type )
    out = {}
    for item in packet[ "blind" ]:
        ref = packet[ "refs" ].get( item[ "item_id" ] )
        if ref is None: raise er.LabellingError( er.BAD_ITEM, f"{item[ 'item_id' ]}: no ref in the packet" )
        found = of_card.get( ref[ "notification_id" ], [] )
        if len( found ) != 1: raise er.LabellingError( er.BAD_ITEM, f"{item[ 'item_id' ]}: card {ref[ 'notification_id' ]} is in {len( found )} populations, not one" )
        out[ item[ "item_id" ] ] = found[ 0 ]
    return out


def main( argv=None, session_scope=None ):
    """
    Write the item-to-card-type mapping and print its receipt.

    Requires:
        - the database named by the configuration is reachable, unless session_scope is given

    Ensures:
        - writes { item_id: card type } once as sorted-key json and prints the receipt: the file's sha256, the item count per type,
          and each type's population count and sha256 for comparison with the pinned values; returns 0
        - returns 2, writing nothing, when the packet cannot be read, an item has no single type, or the output file exists
    """
    root   = cu.get_project_root()
    parser = argparse.ArgumentParser( description="Write the card type of every sample item (read only)." )
    parser.add_argument( "--packet", required=True )
    parser.add_argument( "--out", required=True )
    parser.add_argument( "--cohort", default=root + fsh.COHORT )
    args = parser.parse_args( argv )
    if os.path.exists( args.out ):
        print( f"refused: {args.out} exists, and a mapping is never overwritten", file=sys.stderr )
        return 2
    if session_scope is None:
        from cosa.rest.db.database import get_db as session_scope
    try:
        packet = json.loads( pathlib.Path( args.packet ).read_text( encoding="utf-8" ) )
        with session_scope() as session: pool = bas.population( session, args.cohort )[ "population" ]
        mapping = card_types( packet, pool )
    except ( OSError, ValueError, KeyError, TypeError, er.LabellingError ) as e:
        print( f"cannot build the mapping: {e!r}", file=sys.stderr )
        return 2
    text = json.dumps( mapping, indent=1, sort_keys=True ) + "\n"
    with open( args.out, "x", encoding="utf-8" ) as handle: handle.write( text )
    receipt = { "file_sha256": hashlib.sha256( text.encode( "utf-8" ) ).hexdigest(), "items": len( mapping ),
                "items_by_type": { t: sum( 1 for v in mapping.values() if v == t ) for t in pool },
                "population": { t: { "count": len( ids ), "sha256": ids_sha256( ids ) } for t, ids in pool.items() } }
    print( json.dumps( receipt, indent=1, sort_keys=True ) )
    return 0


if __name__ == "__main__":  # pragma: no cover - entry point
    sys.exit( main() )
