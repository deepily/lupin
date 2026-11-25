"""
Read back the answers Rick's offline page exported, and record them as his gold labels.

Each exported line becomes one gold-store line with source "human" and reader "rick", the pair gold_store.settled reads as Rick.
"""
import argparse
import hashlib
import json
import pathlib
import re
import sys

from cosa.repo.labelling import errors as er
from cosa.repo.labelling import gold_store as gs
from cosa.repo.labelling import packets as pk
from cosa.repo.labelling import rick_page as rp
import cosa.utils.util as cu

EXPORT_KEYS = ( "item_id", "relation", "note", "seconds", "ts" )
READER      = "rick"
ARCHIVE_DIR = "/io/gold-labels/rick-exports"


def _bad( why ):
    """Raises: LabellingError BAD_LABEL with the reason."""
    raise er.LabellingError( er.BAD_LABEL, why )


def read_export( text ):
    """
    Parse the text the page exports.

    Requires:
        - text is the downloaded file or the copied text: a JSON list of lines, or { "lines": [ ... ] }

    Ensures:
        - returns the lines in file order when each holds exactly EXPORT_KEYS, item_id, relation and ts as non-empty text, note as text and seconds as a number of 0 or more
        - an empty list is a valid export

    Raises:
        - LabellingError BAD_LABEL when the text is not JSON, a line is malformed, or an item id appears twice
    """
    try:
        data = json.loads( text )
    except ValueError:
        _bad( "the export is not JSON" )
    lines = data.get( "lines" ) if isinstance( data, dict ) else data
    if not isinstance( lines, list ): _bad( "the export must be a list of lines, or an object with a lines list" )
    for n, line in enumerate( lines ):
        if not isinstance( line, dict ) or set( line ) != set( EXPORT_KEYS ): _bad( f"line {n}: needs exactly the fields {EXPORT_KEYS}" )
        if not all( isinstance( line[ k ], str ) and line[ k ].strip() for k in ( "item_id", "relation", "ts" ) ) or not isinstance( line[ "note" ], str ):
            _bad( f"line {n}: item_id, relation and ts must be non-empty text and note must be text" )
        if isinstance( line[ "seconds" ], bool ) or not isinstance( line[ "seconds" ], ( int, float ) ) or line[ "seconds" ] < 0: _bad( f"line {n}: seconds must be a number of 0 or more" )
    ids = [ l[ "item_id" ] for l in lines ]
    if len( set( ids ) ) != len( ids ): _bad( "an item id appears more than once in the export" )
    return lines


def batch_id_of( page, section ):
    """Ensures: returns rick-<page id>-<section slug>, the batch id of one section's lines."""
    return f"rick-{page}-" + re.sub( r"[^a-z0-9]+", "-", section.lower() ).strip( "-" )


def gold_lines( lines, packet, sections ):
    """
    Turn exported lines into gold-store lines.

    Requires:
        - lines is read_export's result; packet is { blind, disputes, refs }
        - sections maps each section name of the page to its item ids, as the generator wrote them

    Ensures:
        - returns one gold line per exported line, in order: source "human", reader "rick", the card's stance class, notification id and field key from the packet, the line's time as ts
        - the batch id names the page and the section the item was in
        - a relation counts only when it is valid for that item's kind (rick_page.relations_for)
        - the note and the seconds are not part of a gold line and are left out

    Raises:
        - LabellingError BAD_LABEL for an id that is in no section or has no ref, or a relation that does not suit the item
        - LabellingError BAD_ITEM from the packet's item check
    """
    known   = { i[ "item_id" ]: i for i in packet[ "blind" ] + packet[ "disputes" ] }
    section = { i: name for name, ids in sections.items() for i in ids }
    page    = rp.page_id( list( section ) )
    out     = []
    for line in lines:
        item_id = line[ "item_id" ]
        ref     = packet[ "refs" ].get( item_id )
        if item_id not in section or item_id not in known or ref is None: _bad( f"{item_id}: not an item of this page" )
        item = pk.blind_form( known[ item_id ] )
        if line[ "relation" ] not in rp.relations_for( item ): _bad( f"{item_id}: {line[ 'relation' ]} is not a relation this card allows" )
        out.append( { "item_id": item_id, "notification_id": ref[ "notification_id" ], "field_key": ref[ "field_key" ], "relation": line[ "relation" ],
                      "card_stance": item[ "payload" ][ "stance_class" ], "source": gs.SOURCE_HUMAN, "reader": READER, "batch_id": batch_id_of( page, section[ item_id ] ), "ts": line[ "ts" ] } )
    return out


def main( argv=None ):
    """
    Record an exported answer file in the gold store.

    Requires:
        - argv is --export FILE --packet FILE --sections FILE (the page's .sections.json), with optional --store and --archive-dir

    Ensures:
        - writes the lines to the store, copies the export file to the archive directory under its content hash (never overwritten) and prints a JSON summary:
          written, items on the page, items still unanswered, and Rick's labelled cards by stance class; returns 0
        - an export with no lines writes nothing to the store and returns 0
        - returns 2, writing nothing, when a file cannot be read or the export is invalid for the page
        - returns 3, writing nothing to the store, when the store is locked or damaged
    """
    ap = argparse.ArgumentParser( description="Record Rick's exported answers as gold labels." )
    ap.add_argument( "--export", required=True )
    ap.add_argument( "--packet", required=True )
    ap.add_argument( "--sections", required=True )
    ap.add_argument( "--store", default=None )
    ap.add_argument( "--archive-dir", default=cu.get_project_root() + ARCHIVE_DIR )
    args = ap.parse_args( argv )
    try:
        text    = pathlib.Path( args.export ).read_text( encoding="utf-8" )
        packet  = json.loads( pathlib.Path( args.packet ).read_text( encoding="utf-8" ) )
        secs    = json.loads( pathlib.Path( args.sections ).read_text( encoding="utf-8" ) )
        allowed = { i for ids in secs.values() for i in ids }
        lines   = gold_lines( read_export( text ), packet, secs )
    except ( OSError, ValueError, KeyError, TypeError, er.LabellingError ) as e:
        return er.fail( f"cannot read the export: {e!r}", 2 )
    path = pathlib.Path( args.store ) if args.store else gs.default_path()
    try:
        if lines: gs.append_gold( path, lines )
        counts = gs.human_card_counts( gs.read_gold( path ) )
    except er.LabellingError as e:
        return er.fail( f"the gold store refused the write: {e}", 3 )
    archive = pathlib.Path( args.archive_dir )
    archive.mkdir( parents=True, exist_ok=True )
    saved   = archive / f"rick-{hashlib.sha256( text.encode( "utf-8" ) ).hexdigest()[ :12 ]}.json"
    if not saved.exists(): saved.write_text( text, encoding="utf-8" )
    print( json.dumps( { "written": len( lines ), "items_on_page": len( allowed ), "unanswered": len( allowed - { l[ "item_id" ] for l in lines } ),
                         "human_labelled_by_stance": counts, "archived_as": str( saved ) }, sort_keys=True ) )
    return 0


if __name__ == "__main__":  # pragma: no cover - entry point
    sys.exit( main() )
