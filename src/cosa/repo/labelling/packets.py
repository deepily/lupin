"""
Blind packets, one per reviewer, and the reader of the labels they send back.

A packet holds the items and nothing else: no model verdict, no other label, no reason the item was picked.
"""
import json
import pathlib
import random
import re

from cosa.repo.labelling import errors as er
from cosa.repo.labelling import items as it

AS_PROPOSED = "AS_PROPOSED"
OTHER       = "OTHER"
NONE        = "NONE"
CHOICES     = ( AS_PROPOSED, OTHER, NONE )
LABEL_KEYS  = ( "item_id", "reviewer", "choice", "symbols", "note", "ts" )
NAME_RE     = re.compile( r"[A-Za-z0-9_-]+" )
MAX_ORDER_TRIES = 50


def packet_path( out_dir, reviewer ):
    """Return the path of one reviewer's packet file."""
    return pathlib.Path( out_dir ) / f"packet-{reviewer}.jsonl"


def blind_form( item ):
    """
    Return an item as a reviewer may see it.

    Ensures:
        - the item is validated, and holds only the top-level fields and the payload fields its type allows

    Raises:
        - LabellingError BAD_ITEM from validation
        - LabellingError PACKET_LEAK naming the extra field when the item carries any other field
    """
    it.validate_item( item )
    extra = sorted( set( item ) - set( it.TOP_KEYS ) ) + sorted( set( item[ "payload" ] ) - it.ALLOWED[ item[ "type" ] ] )
    if extra: raise er.LabellingError( er.PACKET_LEAK, f"{item[ 'item_id' ]}: fields a reviewer may not see: {', '.join( extra )}" )
    return { "item_id": item[ "item_id" ], "type": item[ "type" ], "payload": item[ "payload" ] }


def seeded_order( items, seed, taken ):
    """
    Order the items for the next reviewer.

    Ensures:
        - the order is a shuffle seeded by the seed, tried again until it differs from the orders in taken, up to MAX_ORDER_TRIES times
    """
    order = list( items )
    for k in range( MAX_ORDER_TRIES ):
        order = sorted( items, key=lambda i: i[ "item_id" ] )
        random.Random( f"{seed}|{k}" ).shuffle( order )
        if [ i[ "item_id" ] for i in order ] not in taken: return order
    return order


def export_packets( items, reviewers, seed, out_dir ):
    """
    Write one blind packet per reviewer.

    Requires:
        - items are labelling items with distinct item ids; reviewers are two or more distinct names of letters, digits, _ and -

    Ensures:
        - returns { reviewer: path } and writes one JSON line per item, the same items for every reviewer in a different seeded order
        - the bytes written are read back and every line is checked to hold the blind form only; on a leak the files are removed

    Raises:
        - LabellingError BAD_ITEM for an invalid item, duplicate ids, or fewer than two or repeated reviewers
        - LabellingError PACKET_LEAK for a field a reviewer may not see
    """
    clean = [ blind_form( i ) for i in items ]
    if len( {i[ "item_id" ] for i in clean} ) != len( clean ): raise er.LabellingError( er.BAD_ITEM, "item ids repeat" )
    if len( reviewers ) < 2 or len( set( reviewers ) ) != len( reviewers ) or not all( NAME_RE.fullmatch( r ) for r in reviewers ):
        raise er.LabellingError( er.BAD_ITEM, "two or more distinct reviewer names are needed" )
    out, taken, paths = pathlib.Path( out_dir ), [], {}
    out.mkdir( parents=True, exist_ok=True )
    for reviewer in reviewers:
        order = seeded_order( clean, seed, taken )
        taken.append( [ i[ "item_id" ] for i in order ] )
        paths[ reviewer ] = packet_path( out, reviewer )
        paths[ reviewer ].write_text( "".join( json.dumps( i, sort_keys=True ) + "\n" for i in order ), encoding="utf-8" )
    try:
        for path in paths.values():
            for line in path.read_text( encoding="utf-8" ).splitlines(): blind_form( json.loads( line ) )
    except er.LabellingError:
        for path in paths.values(): path.unlink()
        raise
    return paths


def _bad( path, n, why ):
    """Raises: LabellingError BAD_LABEL naming the file, line and reason."""
    raise er.LabellingError( er.BAD_LABEL, f"{path}:{n}: {why}" )


def read_labels( path ):
    """
    Read one reviewer's labels.

    Requires:
        - path holds one JSON object per line with item_id, reviewer, choice, symbols, note and ts

    Ensures:
        - returns the labels in file order
        - a choice is AS_PROPOSED, the other-choice or none; symbols is a non-empty list of ids exactly when the choice is the other-choice
        - an item is labelled once per reviewer, and a file holds one reviewer's labels

    Raises:
        - LabellingError BAD_LABEL naming the line
    """
    labels, seen = [], set()
    for n, line in enumerate( pathlib.Path( path ).read_text( encoding="utf-8" ).splitlines(), 1 ):
        try:
            label = json.loads( line )
        except ValueError:
            _bad( path, n, "not JSON" )
        if not isinstance( label, dict ) or set( label ) != set( LABEL_KEYS ): _bad( path, n, f"a label needs exactly the fields {LABEL_KEYS}" )
        if not all( isinstance( label[ k ], str ) and label[ k ].strip() for k in ( "item_id", "reviewer", "ts" ) ) or not isinstance( label[ "note" ], str ):
            _bad( path, n, "item_id, reviewer, ts and note must be strings, the first three not empty" )
        if label[ "choice" ] not in CHOICES: _bad( path, n, f"choice must be one of {CHOICES}" )
        symbols = label[ "symbols" ]
        if not isinstance( symbols, list ) or not all( isinstance( s, str ) and s.strip() for s in symbols ) or bool( symbols ) != ( label[ "choice" ] == OTHER ):
            _bad( path, n, "symbols must be a non-empty list of ids when the choice is OTHER, and empty otherwise" )
        if labels and label[ "reviewer" ] != labels[ 0 ][ "reviewer" ]: _bad( path, n, "a file holds one reviewer's labels" )
        if label[ "item_id" ] in seen: _bad( path, n, f"item {label[ 'item_id' ]} is labelled twice" )
        seen.add( label[ "item_id" ] )
        labels.append( label )
    return labels
