"""
The gold-label store: an append-only file of Rick's and the AI readers' labels.

One line per label. A card's settled label is derived on read, never stored.
"""
import fcntl
import json
import os
import pathlib
import threading

from cosa.repo.labelling import errors as er
from cosa.repo.labelling import items as it
from cosa.repo.labelling import packets as pk
import cosa.utils.util as cu

STORE_RELATIVE = "/io/gold-labels/answer-meaning-gold.jsonl"
LINE_KEYS      = ( "item_id", "notification_id", "field_key", "relation", "card_stance", "source", "reader", "batch_id", "ts" )
SOURCE_HUMAN   = "human"
SOURCE_READER  = "ai_reader"
SOURCES        = ( SOURCE_HUMAN, SOURCE_READER )
SETTLED_AGREED = "readers_agreed"
SETTLED_RICK   = "rick_tiebreak"
_write_lock    = threading.Lock()


def default_path():
    """
    Name the store file.

    Ensures:
        - returns the path under the project root, which is the main checkout when run from it; a worktree's copy is swept
    """
    return pathlib.Path( cu.get_project_root() + STORE_RELATIVE )


def _bad( where, why ):
    """Raises: LabellingError BAD_LABEL naming where and why."""
    raise er.LabellingError( er.BAD_LABEL, f"{where}: {why}" )


def check_line( line, where="line" ):
    """
    Check one gold line.

    Requires:
        - line is any object

    Ensures:
        - returns None when the line holds exactly LINE_KEYS, every field a non-empty string, a source of human or ai_reader,
          a relation in the answer labels and a card stance in the stance classes

    Raises:
        - LabellingError BAD_LABEL naming where and the first violation
    """
    if not isinstance( line, dict ) or set( line ) != set( LINE_KEYS ): _bad( where, f"a gold line needs exactly the fields {LINE_KEYS}" )
    if not all( isinstance( line[ k ], str ) and line[ k ].strip() for k in LINE_KEYS ): _bad( where, "every field must be a non-empty string" )
    if line[ "source" ] not in SOURCES: _bad( where, f"source must be one of {SOURCES}" )
    if line[ "relation" ] not in pk.ANSWER_LABELS: _bad( where, f"relation must be one of {pk.ANSWER_LABELS}" )
    if line[ "card_stance" ] not in it.STANCE_CLASSES: _bad( where, f"card_stance must be one of {it.STANCE_CLASSES}" )


def read_gold( path ):
    """
    Read every line of the store, in file order.

    Requires:
        - path is the store file, or does not exist

    Ensures:
        - returns the checked lines; an absent or empty file gives []
        - an earlier line of an item stays in the list beside a later one

    Raises:
        - LabellingError BAD_LABEL for a torn last line (one with no end of line), an unreadable line or a line that fails check_line
    """
    path = pathlib.Path( path )
    if not path.exists(): return []
    text = path.read_text( encoding="utf-8" )
    if text and not text.endswith( "\n" ): _bad( f"{path}", "the last line is torn (no end of line); the file needs repair, nothing was skipped" )
    out = []
    for n, raw in enumerate( text.splitlines(), 1 ):
        try:
            line = json.loads( raw )
        except ValueError:
            _bad( f"{path}:{n}", "not JSON" )
        check_line( line, f"{path}:{n}" )
        out.append( line )
    return out


def append_gold( path, lines ):
    """
    Add lines to the store.

    Requires:
        - lines is a list of dicts

    Ensures:
        - every line is checked before anything is written; on a bad line nothing is written
        - the lines go to the end in one write, flushed and synced, and the directory is synced; no earlier line changes
        - an exclusive file lock is held for the write, beside an in-process lock
        - returns the number of lines written

    Raises:
        - LabellingError BAD_LABEL for a bad line, or for a store whose last line is torn
        - LabellingError STORE_LOCKED when another process holds the file; nothing is written
    """
    path = pathlib.Path( path )
    for n, line in enumerate( lines ): check_line( line, f"line {n}" )
    path.parent.mkdir( parents=True, exist_ok=True )
    with _write_lock, open( path, "a+b" ) as f:
        try:
            fcntl.flock( f, fcntl.LOCK_EX | fcntl.LOCK_NB )
        except BlockingIOError:
            raise er.LabellingError( er.STORE_LOCKED, f"{path}: another process holds the gold store" )
        read_gold( path )
        f.write( "".join( json.dumps( l, sort_keys=True ) + "\n" for l in lines ).encode( "utf-8" ) )
        f.flush()
        os.fsync( f.fileno() )
    fd = os.open( path.parent, os.O_RDONLY )
    try:
        os.fsync( fd )
    finally:
        os.close( fd )
    return len( lines )


def latest_lines( lines ):
    """
    Pick the line that counts for each item and labeller.

    Requires:
        - lines is read_gold's list

    Ensures:
        - returns one line per ( item_id, source, reader ): the last in file order, held at the place that key first appeared
    """
    latest = {}
    for line in lines: latest[ ( line[ "item_id" ], line[ "source" ], line[ "reader" ] ) ] = line
    return list( latest.values() )


def settled( lines ):
    """
    Give each card its settled label.

    Requires:
        - lines is read_gold's list

    Ensures:
        - returns { "settled": { item_id: { relation, card_stance, settled_by } }, "unsettled": [ item_id ] }
        - a card is settled by the AI readers when at least two readers have labelled it and their latest relations are all the same
        - otherwise by Rick's latest human line, which breaks a tie and also settles a card fewer than two readers saw
        - otherwise it is unsettled, listed in sorted order, and is not in the gold set
    """
    by_item = {}
    for line in latest_lines( lines ): by_item.setdefault( line[ "item_id" ], [] ).append( line )
    done, open_ = {}, []
    for item_id, group in by_item.items():
        readers = [ l for l in group if l[ "source" ] == SOURCE_READER ]
        humans  = [ l for l in group if l[ "source" ] == SOURCE_HUMAN ]
        if len( readers ) >= 2 and len( { l[ "relation" ] for l in readers } ) == 1:
            done[ item_id ] = { "relation": readers[ 0 ][ "relation" ], "card_stance": readers[ 0 ][ "card_stance" ], "settled_by": SETTLED_AGREED }
        elif humans:
            done[ item_id ] = { "relation": humans[ -1 ][ "relation" ], "card_stance": humans[ -1 ][ "card_stance" ], "settled_by": SETTLED_RICK }
        else:
            open_.append( item_id )
    return { "settled": done, "unsettled": sorted( open_ ) }


def human_card_counts( lines ):
    """
    Count the cards Rick has labelled, by the card's stance class.

    Requires:
        - lines is read_gold's list

    Ensures:
        - returns { stance class: number of distinct cards with a human line }, every stance class present, 0 when none
    """
    counts = { c: 0 for c in it.STANCE_CLASSES }
    for line in latest_lines( lines ):
        if line[ "source" ] == SOURCE_HUMAN: counts[ line[ "card_stance" ] ] += 1
    return counts
