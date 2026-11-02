"""
Blind packets, one per reviewer, and the reader of the labels they send back.

A packet holds the items and nothing else: no model verdict, no other label, no reason the item was picked.
"""
import json
import pathlib
import random
import re
from datetime import datetime, timezone

from cosa.repo.labelling import errors as er
from cosa.repo.labelling import items as it

AS_PROPOSED = "AS_PROPOSED"
OTHER       = "OTHER"
NONE        = "NONE"
CHOICES     = ( AS_PROPOSED, OTHER, NONE )
LABEL_KEYS  = ( "item_id", "reviewer", "choice", "symbols", "note", "ts" )
NAME_RE     = re.compile( r"[A-Za-z0-9_-]+" )
MAX_ORDER_TRIES = 50
PROVENANCE_KEYS = ( "source_commit", "index_generation" )
COMMIT_RE       = re.compile( r"[0-9a-f]{7,40}" )


def packet_path( out_dir, reviewer ):
    """Return the path of one reviewer's packet file."""
    return pathlib.Path( out_dir ) / f"packet-{reviewer}.jsonl"


def _provenance_path( packet ):
    """Return the path of the provenance file that sits beside one packet."""
    return pathlib.Path( packet ).with_suffix( ".provenance.json" )


def check_provenance( record, where="provenance" ):
    """
    Refuse a record that does not name the commit and the index generation a run was cut from.

    Requires:
        - record is a dict

    Ensures:
        - returns { source_commit, index_generation } when the commit is 7 to 40 lowercase hex digits and the generation is a non-empty name
        - other fields of the record are left out of the result

    Raises:
        - LabellingError PROVENANCE_MISSING naming where and which field is absent or malformed
    """
    if not isinstance( record, dict ): raise er.LabellingError( er.PROVENANCE_MISSING, f"{where}: not a record" )
    commit, gen = record.get( "source_commit" ), record.get( "index_generation" )
    if not isinstance( commit, str ) or not COMMIT_RE.fullmatch( commit ): raise er.LabellingError( er.PROVENANCE_MISSING, f"{where}: source_commit must be a git commit id, got {commit!r}" )
    if not isinstance( gen, str ) or not gen.strip(): raise er.LabellingError( er.PROVENANCE_MISSING, f"{where}: index_generation must be a generation name, got {gen!r}" )
    return { "source_commit": commit, "index_generation": gen }


def read_provenance( packet ):
    """
    Read the commit and index generation one packet was cut from.

    The 25 Oct run was cut before this record existed. It has no file, and its commit is inferred, never recorded.

    Requires:
        - packet is the path of a packet export_packets or export_subset_packet wrote

    Ensures:
        - returns { source_commit, index_generation } as check_provenance accepts them

    Raises:
        - LabellingError PROVENANCE_MISSING when the file is absent, unreadable or incomplete
    """
    path = _provenance_path( packet )
    try:
        record = json.loads( path.read_text( encoding="utf-8" ) )
    except ( OSError, ValueError ):
        raise er.LabellingError( er.PROVENANCE_MISSING, f"{path}: no readable provenance file; this packet was cut before the commit was recorded" )
    return check_provenance( record, str( path ) )


def _write_provenance( packet, provenance ):
    """Ensures: writes the checked provenance beside the packet and returns its path."""
    path = _provenance_path( packet )
    path.write_text( json.dumps( check_provenance( provenance ), sort_keys=True ), encoding="utf-8" )
    return path


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


def export_packets( items, reviewers, seed, out_dir, provenance ):
    """
    Write one blind packet per reviewer.

    Requires:
        - items are labelling items with distinct item ids; reviewers are two or more distinct names of letters, digits, _ and -
        - provenance names the source_commit and index_generation the items were cut from

    Ensures:
        - returns { reviewer: path } and writes one JSON line per item, the same items for every reviewer in a different seeded order
        - writes the provenance beside each packet, and writes nothing when it is missing or malformed
        - the bytes written are read back and every line is checked to hold the blind form only; on a leak the files are removed

    Raises:
        - LabellingError BAD_ITEM for an invalid item, duplicate ids, or fewer than two or repeated reviewers
        - LabellingError PACKET_LEAK for a field a reviewer may not see
        - LabellingError PROVENANCE_MISSING for a provenance without a commit or an index generation
    """
    provenance = check_provenance( provenance )
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
        _write_provenance( paths[ reviewer ], provenance )
    try:
        for path in paths.values():
            for line in path.read_text( encoding="utf-8" ).splitlines(): blind_form( json.loads( line ) )
    except er.LabellingError:
        for path in paths.values():
            path.unlink()
            _provenance_path( path ).unlink()
        raise
    return paths


def export_subset_packet( packet_dir, item_ids, reviewer, seed ):
    """
    Write one more reviewer's blind packet of some items already sent out.

    A third rater's packet of the disputed items is the case it was written for.

    Requires:
        - packet_dir holds the packets export_packets wrote; item_ids are ids those packets hold; reviewer is a new name of letters, digits, _ and -

    Ensures:
        - returns the new packet's path, holding the named items in a seeded order that differs from each earlier packet's order of the same items
        - the new packet carries the provenance of the earlier ones, which must all agree
        - the bytes written are read back and checked to hold the blind form only; on a leak the file is removed

    Raises:
        - LabellingError BAD_ITEM for no earlier packet, no items, an id no packet holds, a bad name, or a reviewer who already has a packet
        - LabellingError PACKET_LEAK for a field a reviewer may not see
        - LabellingError PROVENANCE_MISSING when an earlier packet has no provenance, or two of them differ
    """
    earlier = sorted( pathlib.Path( packet_dir ).glob( "packet-*.jsonl" ) )
    if not earlier: raise er.LabellingError( er.BAD_ITEM, f"{packet_dir}: no packets to draw from" )
    if not NAME_RE.fullmatch( reviewer ) or packet_path( packet_dir, reviewer ).exists():
        raise er.LabellingError( er.BAD_ITEM, f"{reviewer}: needs a new name of letters, digits, _ and -" )
    provs  = [ read_provenance( p ) for p in earlier ]
    if any( x != provs[ 0 ] for x in provs ): raise er.LabellingError( er.PROVENANCE_MISSING, f"{packet_dir}: the earlier packets were cut from different commits or index generations" )
    wanted = set( item_ids )
    orders = [ [ json.loads( line ) for line in path.read_text( encoding="utf-8" ).splitlines() ] for path in earlier ]
    by_id  = { i[ "item_id" ]: i for i in orders[ 0 ] }
    absent = sorted( wanted - set( by_id ) )
    if not wanted or absent: raise er.LabellingError( er.BAD_ITEM, f"items to export must be named and already sent out; not found: {', '.join( absent )}" )
    taken  = [ [ i[ "item_id" ] for i in order if i[ "item_id" ] in wanted ] for order in orders ]
    order  = seeded_order( [ blind_form( by_id[ i ] ) for i in sorted( wanted ) ], f"{seed}|{reviewer}", taken )
    path   = packet_path( packet_dir, reviewer )
    path.write_text( "".join( json.dumps( i, sort_keys=True ) + "\n" for i in order ), encoding="utf-8" )
    _write_provenance( path, provs[ 0 ] )
    try:
        for line in path.read_text( encoding="utf-8" ).splitlines(): blind_form( json.loads( line ) )
    except er.LabellingError:
        path.unlink()
        _provenance_path( path ).unlink()
        raise
    return path


def _bad( path, n, why ):
    """Raises: LabellingError BAD_LABEL naming the file, line and reason."""
    raise er.LabellingError( er.BAD_LABEL, f"{path}:{n}: {why}" )


def moment( ts ):
    """Return an ISO-8601 time as an aware datetime (no zone means UTC), or None if unreadable."""
    try:
        when = datetime.fromisoformat( ts )
    except ValueError:
        return None
    return when if when.tzinfo is not None else when.replace( tzinfo=timezone.utc )


def read_history( path ):
    """
    Read every line of one reviewer's labels file, the earlier answers included.

    Requires:
        - path holds one JSON object per line with item_id, reviewer, choice, symbols, note and ts

    Ensures:
        - returns the labels in file order; an item answered again appears once per answer, the latest last
        - a choice is AS_PROPOSED, the other-choice or none; symbols is a non-empty list of ids exactly when the choice is the other-choice
        - a file holds one reviewer's labels
        - an item answered again carries a time that can be read and is not earlier than the answer before it, as save_label always writes it; a repeat that breaks this is refused, but a hand edit with a later time still loads

    Raises:
        - LabellingError BAD_LABEL naming the line
    """
    labels, last = [], {}
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
        if label[ "item_id" ] in last:
            before, now = moment( last[ label[ "item_id" ] ] ), moment( label[ "ts" ] )
            if before is None or now is None: _bad( path, n, f"item {label[ 'item_id' ]} is answered again and the time of the two answers cannot be read" )
            if now < before: _bad( path, n, f"item {label[ 'item_id' ]} is answered again with a time earlier than the answer before it; save_label never writes that" )
        last[ label[ "item_id" ] ] = label[ "ts" ]
        labels.append( label )
    return labels


def latest_labels( history ):
    """
    Pick the answer that counts for each item.

    Requires:
        - history is read_history's list

    Ensures:
        - returns one label per item: the last one in file order, held at the place the item first appeared
    """
    latest = {}
    for label in history: latest[ label[ "item_id" ] ] = label
    return list( latest.values() )


def read_labels( path ):
    """
    Read one reviewer's labels as they stand: the latest answer of each item.

    Requires:
        - path is as read_history needs

    Ensures:
        - returns latest_labels( read_history( path ) ); an item answered again counts once, at its latest answer

    Raises:
        - LabellingError BAD_LABEL naming the line, from read_history
    """
    return latest_labels( read_history( path ) )
