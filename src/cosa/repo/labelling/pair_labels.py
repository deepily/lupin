"""
Labels for semdup_pair items: what a choice means, and the store a page writes.

A pair is labelled "same job" or "not the same job". The labelling format has three choices made for need matching.
This module fixes how a pair uses them, once, for the proof's loader and every labelling page.
"""
import json
import os
import pathlib
import threading
from datetime import datetime, timezone

from cosa.repo.labelling import errors as er
from cosa.repo.labelling import items as it
from cosa.repo.labelling import packets as pk

SAME_JOB_OF_CHOICE = { pk.AS_PROPOSED: True, pk.NONE: False }
"""
How a semdup_pair label becomes the boolean the proof takes (Cheech, 2026-10-26).

AS_PROPOSED means the two definitions do the same job (True). NONE means they do not (False).
OTHER is never used for a pair: read_labels demands symbol ids with it, and a pair has none.
Unsure is not a choice. It is the leaning choice plus a note that starts with UNSURE_PREFIX.
"""

UNSURE_PREFIX = "UNSURE:"
LABELS_PREFIX = "labels-"
MAX_NOTE      = 2000

_write_lock = threading.Lock()


def same_job( label ):
    """
    Return whether a pair label says the two definitions do the same job.

    Requires:
        - label is a label read by read_labels

    Ensures:
        - returns True for AS_PROPOSED and False for the none-choice

    Raises:
        - LabellingError BAD_LABEL for the other-choice, which a pair never carries
    """
    if label[ "choice" ] not in SAME_JOB_OF_CHOICE: raise er.LabellingError( er.BAD_LABEL, f"{label[ 'item_id' ]}: a pair is never labelled {label[ 'choice' ]}" )
    return SAME_JOB_OF_CHOICE[ label[ "choice" ] ]


def is_unsure( label ):
    """Ensures: returns True when the label's note starts with UNSURE_PREFIX."""
    return label[ "note" ].startswith( UNSURE_PREFIX )


def user_note( label ):
    """Ensures: returns the note without UNSURE_PREFIX and the space after it."""
    return label[ "note" ][ len( UNSURE_PREFIX ): ].lstrip( " " ) if is_unsure( label ) else label[ "note" ]


def same_job_labels( path ):
    """
    Read a pair labels file as the proof wants it.

    Requires:
        - path is a labels file of one reviewer

    Ensures:
        - returns { item_id: bool } with the unsure items included at their leaning choice

    Raises:
        - LabellingError BAD_LABEL from read_labels, or for the other-choice
    """
    return { label[ "item_id" ]: same_job( label ) for label in pk.read_labels( path ) }


def reviewer_of( packet_path ):
    """
    Return the reviewer a packet file belongs to.

    Raises:
        - LabellingError BAD_ITEM when the name is not packet-<reviewer>.jsonl
    """
    name = pathlib.Path( packet_path ).name
    stem = name[ len( "packet-" ):-len( ".jsonl" ) ] if name.startswith( "packet-" ) and name.endswith( ".jsonl" ) else ""
    if not pk.NAME_RE.fullmatch( stem ): raise er.LabellingError( er.BAD_ITEM, f"{name}: not a packet-<reviewer>.jsonl file" )
    return stem


def labels_path( packet_path ):
    """Ensures: returns labels-<reviewer>.jsonl beside the packet."""
    return pathlib.Path( packet_path ).with_name( f"{LABELS_PREFIX}{reviewer_of( packet_path )}.jsonl" )


def load_items( packet_path ):
    """
    Read a packet for display.

    Ensures:
        - returns the items in packet order as { item_id, a, b } and nothing else; the type is dropped
        - every line has been through blind_form

    Raises:
        - LabellingError BAD_ITEM or PACKET_LEAK for a line that is not a blind semdup_pair
    """
    items = []
    for line in pathlib.Path( packet_path ).read_text( encoding="utf-8" ).splitlines():
        item = pk.blind_form( json.loads( line ) )
        if item[ "type" ] != it.SEMDUP_PAIR: raise er.LabellingError( er.BAD_ITEM, f"{item[ 'item_id' ]}: not a semdup_pair" )
        items.append( { "item_id": item[ "item_id" ], "a": item[ "payload" ][ "a" ], "b": item[ "payload" ][ "b" ] } )
    return items


def read_existing( packet_path ):
    """Ensures: returns the labels so far in file order, or an empty list."""
    path = labels_path( packet_path )
    return pk.read_labels( path ) if path.exists() else []


def progress( items, labels ):
    """
    Count what is done.

    Ensures:
        - returns { total, labelled, unsure, resume }: resume is the position of the first unlabelled item, else of the first unsure one, else None
    """
    done   = { l[ "item_id" ]: l for l in labels }
    unsure = [ n for n, i in enumerate( items ) if i[ "item_id" ] in done and is_unsure( done[ i[ "item_id" ] ] ) ]
    fresh  = [ n for n, i in enumerate( items ) if i[ "item_id" ] not in done ]
    return { "total": len( items ), "labelled": len( done ), "unsure": len( unsure ), "resume": fresh[ 0 ] if fresh else ( unsure[ 0 ] if unsure else None ) }


def build_label( item_id, reviewer, same, unsure, note, clock ):
    """
    Build one label line.

    Requires:
        - same is a bool; unsure is a bool; note is a string
        - clock is a callable giving the time as text

    Ensures:
        - the choice is AS_PROPOSED for same and the none-choice otherwise, and symbols are empty
        - an unsure label's note starts with UNSURE_PREFIX

    Raises:
        - LabellingError BAD_LABEL for a note over MAX_NOTE characters
    """
    note = note.strip()
    if len( note ) > MAX_NOTE: raise er.LabellingError( er.BAD_LABEL, f"{item_id}: the note is over {MAX_NOTE} characters" )
    if unsure: note = f"{UNSURE_PREFIX} {note}".rstrip()
    choice = next( c for c, s in SAME_JOB_OF_CHOICE.items() if s is same )
    return { "item_id": item_id, "reviewer": reviewer, "choice": choice, "symbols": [], "note": note, "ts": clock() }


def now_text():
    """Ensures: returns the current UTC time as ISO-8601 text."""
    return datetime.now( timezone.utc ).isoformat( timespec="seconds" )


def save_label( packet_path, item_id, same, unsure=False, note="", clock=now_text ):
    """
    Write one label to disk, replacing the reviewer's earlier label of that item.

    Requires:
        - item_id names an item of the packet

    Ensures:
        - the whole labels file is written to a temp file beside it, flushed, checked with read_labels, and renamed over the old file
        - a first label goes to the end; a re-answer keeps the line's place; no item is ever written twice
        - the labels file passes read_labels when this returns, and a failure leaves the old file as it was
        - returns the label written

    Raises:
        - LabellingError BAD_ITEM for an item not in the packet; BAD_LABEL from build_label or the check
    """
    reviewer = reviewer_of( packet_path )
    if item_id not in { i[ "item_id" ] for i in load_items( packet_path ) }: raise er.LabellingError( er.BAD_ITEM, f"{item_id}: not in {pathlib.Path( packet_path ).name}" )
    label = build_label( item_id, reviewer, same, unsure, note, clock )
    path  = labels_path( packet_path )
    tmp   = path.with_name( path.name + ".tmp" )
    with _write_lock:
        kept = read_existing( packet_path )
        out  = [ label if l[ "item_id" ] == item_id else l for l in kept ]
        if all( l[ "item_id" ] != item_id for l in kept ): out.append( label )
        try:
            with open( tmp, "w", encoding="utf-8" ) as f:
                f.write( "".join( json.dumps( l, sort_keys=True ) + "\n" for l in out ) )
                f.flush()
                os.fsync( f.fileno() )
            pk.read_labels( tmp )
            os.replace( tmp, path )
        finally:
            if tmp.exists(): tmp.unlink()
        _sync_directory( path.parent )
    return label


def _sync_directory( folder ):
    """Ensures: the rename is on disk when this returns."""
    fd = os.open( folder, os.O_RDONLY )
    try:
        os.fsync( fd )
    finally:
        os.close( fd )
