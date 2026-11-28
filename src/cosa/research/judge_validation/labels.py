"""
Build the report's labels file from the two readers' labels and Rick's export.

Rick's answer decides a pair: section B, the dispute he settles after seeing the readers, over
section A, his blind share, over the readers' agreement. A pair Rick could not tell, or a
dispute he has not settled, is unresolved. Only Rick's blind answers are listed as his reading,
so his agreement with each reader is measured on pairs he labelled without seeing theirs.
"""

import argparse
import json
import pathlib
import sys

from cosa.utils import jsonl_file

SECTIONS      = ( "A", "B" )
CHOICES       = { "yes": True, "no": False, "cant_tell": None }
RICK          = "rick"
EXIT_REFUSED  = 1


def read_reader_labels( path, pair_ids ):
    """
    Read one reader's labels, one for every sampled pair and no other.

    Requires:
        - path has one JSON line per pair holding pair_id and material_error

    Ensures:
        - returns { pair_id: bool }

    Raises:
        - ValueError for a repeated, missing or unknown pair id, or a material_error that is not true or false
    """
    held = {}
    for row in jsonl_file.read_jsonl( pathlib.Path( path ) ):
        if row[ "pair_id" ] in held: raise ValueError( f"{path}: pair {row[ 'pair_id' ]} is labelled twice" )
        if not isinstance( row[ "material_error" ], bool ): raise ValueError( f"{path}: pair {row[ 'pair_id' ]}: material_error is not true or false" )
        held[ row[ "pair_id" ] ] = row[ "material_error" ]
    odd = sorted( set( held ) ^ set( pair_ids ) )
    if odd: raise ValueError( f"{path}: labels and sample differ on {len( odd )} ids, for example {odd[ :3 ]}" )
    return held


def read_export( path, pair_ids ):
    """
    Read the export of Rick's page, the latest answer winning for each section and pair.

    Requires:
        - path holds a JSON list of { pair_id, section, material_error, ts }, section "A" or "B"

    Ensures:
        - returns { section: { pair_id: True, False or None } }

    Raises:
        - ValueError for an unknown pair id, section or answer
    """
    latest = {}
    for line in sorted( json.loads( pathlib.Path( path ).read_text( encoding="utf-8" ) ), key=lambda line: line[ "ts" ] ):
        if line[ "pair_id" ] not in pair_ids: raise ValueError( f"{path}: pair {line[ 'pair_id' ]} is not in the sample" )
        if line[ "section" ] not in SECTIONS or line[ "material_error" ] not in CHOICES:
            raise ValueError( f"{path}: pair {line[ 'pair_id' ]}: unknown section or answer {line[ 'section' ]!r}, {line[ 'material_error' ]!r}" )
        latest[ ( line[ "section" ], line[ "pair_id" ] ) ] = CHOICES[ line[ "material_error" ] ]
    return { section: { pair_id: value for ( own, pair_id ), value in latest.items() if own == section } for section in SECTIONS }


def settle( pair_ids, readers, rick ):
    """
    Settle one truth label for each pair.

    Requires:
        - readers is { name: read_reader_labels result } for exactly two readers; rick is read_export's result

    Ensures:
        - returns one row per pair id, in order: pair_id, material_error (True, False or None), readers, settled_by
        - settled_by is "rick_dispute", "rick_blind", "readers_agreed" or "unresolved", the first that applies
        - Rick's answer decides even when it is "cannot tell", which leaves the pair unresolved
        - readers holds both AI readers, and rick only for a blind answer that was yes or no

    Raises:
        - ValueError unless there are two readers, neither named as Rick is
    """
    if len( readers ) != 2 or RICK in readers: raise ValueError( f"two readers are needed, neither named {RICK!r}" )
    rows = []
    for pair_id in pair_ids:
        said  = { name: held[ pair_id ] for name, held in readers.items() }
        first, second = said.values()
        if pair_id in rick[ "B" ]:   value, how = rick[ "B" ][ pair_id ], "rick_dispute"
        elif pair_id in rick[ "A" ]: value, how = rick[ "A" ][ pair_id ], "rick_blind"
        elif first == second:        value, how = first, "readers_agreed"
        else:                        value, how = None, "unresolved"
        if rick[ "A" ].get( pair_id ) is not None: said[ RICK ] = rick[ "A" ][ pair_id ]
        rows.append( { "pair_id": pair_id, "material_error": value, "readers": said, "settled_by": "unresolved" if value is None else how } )
    return rows


def main( argv=None ):
    """
    Write the labels file from the command line.

    Ensures:
        - writes one row per sampled pair to --out, once, prints the counts by settled_by and returns 0
        - a bad input, or an existing output, is printed and returns EXIT_REFUSED with nothing written
    """
    parser = argparse.ArgumentParser( description="Settle the judge validation's truth labels." )
    parser.add_argument( "--sample", required=True )
    parser.add_argument( "--reader", action="append", required=True, metavar="NAME=PATH", help="one reader's labels.jsonl; give two" )
    parser.add_argument( "--rick", required=True, help="the JSON export of Rick's page" )
    parser.add_argument( "--out", required=True )
    args = parser.parse_args( argv )
    try:
        pair_ids = [ row[ "pair_id" ] for row in jsonl_file.read_jsonl( pathlib.Path( args.sample ) ) ]
        readers  = { name: read_reader_labels( path, pair_ids ) for name, path in ( item.split( "=", 1 ) for item in args.reader ) }
        rows     = settle( pair_ids, readers, read_export( args.rick, set( pair_ids ) ) )
        with open( args.out, "x", encoding="utf-8" ) as handle:
            handle.writelines( json.dumps( row, sort_keys=True ) + "\n" for row in rows )
    except ( ValueError, FileExistsError ) as error:
        print( error, file=sys.stderr )
        return EXIT_REFUSED
    how = [ row[ "settled_by" ] for row in rows ]
    print( json.dumps( { name: how.count( name ) for name in sorted( set( how ) ) } ) )
    return 0


if __name__ == "__main__":
    sys.exit( main() )
