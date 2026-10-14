"""The miss record: a reuse-check miss as a fenced JSON block in a row body."""
import json
import os
import re
import tempfile
from dataclasses import dataclass

FIELDS     = ( "receipt_id", "symbol", "caught_by", "repaired" )
TEXT_KEYS  = ( "receipt_id", "symbol", "caught_by" )
BLOCK_RE   = re.compile( r"```json\n(.*?)\n```", re.DOTALL )


def is_miss( value ):
    """
    Say whether a value is a well-formed miss.

    Requires:
        - nothing

    Ensures:
        - returns True iff value is a dict whose keys are the four miss fields and no others
        - the three text fields are non-empty strings and repaired is a bool

    Raises:
        - nothing
    """
    if not isinstance( value, dict ) or set( value ) != set( FIELDS ): return False
    if not all( isinstance( value[ k ], str ) and value[ k ].strip() for k in TEXT_KEYS ): return False
    return isinstance( value[ "repaired" ], bool )


def render_block( miss ):
    """
    Write a miss as the fenced JSON block a row body carries.

    Requires:
        - miss satisfies is_miss

    Ensures:
        - returns a ```json fenced string that parse_block reads back to an equal dict
        - keys are sorted, so one miss always renders to the same bytes

    Raises:
        - ValueError naming the fields when miss is not well formed
    """
    if not is_miss( miss ): raise ValueError( f"a miss needs exactly {', '.join( FIELDS )}; got {miss!r}" )
    return "```json\n" + json.dumps( miss, sort_keys=True ) + "\n```"


def scan_blocks( body ):
    """
    Read a row body, keeping the well-formed misses and naming every block it could not use.

    Requires:
        - body is a string

    Ensures:
        - returns ( misses, skipped ), misses in body order
        - CRLF line endings are read as LF, so a block saved on Windows is not lost
        - skipped holds one reason string per ```json block that is not JSON or not a miss
        - a body with no block returns two empty lists

    Raises:
        - nothing
    """
    found, skipped = [], []
    for raw in BLOCK_RE.findall( body.replace( "\r\n", "\n" ) ):
        try:
            value = json.loads( raw )
        except json.JSONDecodeError as err:
            skipped.append( f"not JSON: {err.msg}" )
            continue
        if is_miss( value ): found.append( value )
        else: skipped.append( "not a miss: needs exactly " + ", ".join( FIELDS ) )
    return found, skipped


def parse_block( body ):
    """
    Read every well-formed miss block out of a row body.

    Requires:
        - body is a string

    Ensures:
        - returns the misses of scan_blocks, in body order, empty when none is found
        - a block that cannot be used is dropped here; scan_blocks names it

    Raises:
        - nothing
    """
    return scan_blocks( body )[ 0 ]


def collect_with_skips( rows ):
    """
    Gather the misses of many store rows, and the blocks that could not be read.

    Requires:
        - rows is an iterable of dicts with a "body" key, a string or None
        - a row may carry "updated_ts", an ISO-8601 string, and "title"

    Ensures:
        - returns ( misses, skipped ), misses sorted by ( receipt_id, symbol ), one per pair
        - rows are read oldest first by updated_ts, so the newest state of a pair wins
        - a repair that was re-broken later therefore reads as not repaired
        - skipped is a list of { "title", "reason" }, one per unusable block

    Raises:
        - nothing
    """
    by_key, skipped = {}, []
    for row in sorted( rows, key=lambda r: r.get( "updated_ts" ) or "" ):
        found, bad = scan_blocks( row[ "body" ] or "" )
        skipped += [ { "title": row.get( "title" ), "reason": reason } for reason in bad ]
        for miss in found: by_key[ ( miss[ "receipt_id" ], miss[ "symbol" ] ) ] = miss
    return [ by_key[ k ] for k in sorted( by_key ) ], skipped


def collect( rows ):
    """
    Gather the misses of many store rows into one list.

    Requires:
        - rows is as collect_with_skips takes it

    Ensures:
        - returns the misses of collect_with_skips

    Raises:
        - nothing
    """
    return collect_with_skips( rows )[ 0 ]


@dataclass
class Export:
    """
    The outcome of one export.

    Ensures:
        - written is the number of lines written
        - skipped lists every block that could not be read, as collect_with_skips gives it
    """

    written : int
    skipped : list


def export_report( rows, path, allow_empty=False ):
    """
    Write the misses of many store rows to a JSON Lines file, replacing it atomically.

    Requires:
        - rows is as collect_with_skips takes it
        - the folder of path exists

    Ensures:
        - path holds one sorted-key JSON object per line, in collect order, UTF-8, mode 0644
        - a reader never sees a half-written file, and a failed write leaves the old file
        - returns an Export, so the caller can log the skipped blocks

    Raises:
        - ValueError when there are no misses, path holds bytes and allow_empty is False
        - OSError when the folder cannot be written
    """
    misses, skipped = collect_with_skips( rows )
    if not misses and not allow_empty and os.path.exists( path ) and os.path.getsize( path ) > 0:
        raise ValueError( f"refusing to replace a populated {path} with an empty export; pass allow_empty to do it" )
    text    = "".join( json.dumps( m, sort_keys=True ) + "\n" for m in misses )
    fd, tmp = tempfile.mkstemp( dir=os.path.dirname( os.path.abspath( path ) ), prefix=".misses-" )
    try:
        with os.fdopen( fd, "w", encoding="utf-8" ) as handle: handle.write( text )
        os.chmod( tmp, 0o644 )
        os.replace( tmp, path )
    except BaseException:
        if os.path.exists( tmp ): os.unlink( tmp )
        raise
    return Export( len( misses ), skipped )


def export_misses( rows, path, allow_empty=False ):
    """
    Write the misses of many store rows to a JSON Lines file.

    Requires:
        - the arguments of export_report

    Ensures:
        - returns the number of lines written, as export_report counts them

    Raises:
        - what export_report raises
    """
    return export_report( rows, path, allow_empty ).written
