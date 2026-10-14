"""The miss record: a reuse-check miss as a fenced JSON block in a row body."""
import json
import os
import re
import tempfile

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


def parse_block( body ):
    """
    Read every well-formed miss block out of a row body.

    Requires:
        - body is a string

    Ensures:
        - returns a list of miss dicts in body order, empty when none is found
        - a block that is not JSON, or not a well-formed miss, is skipped, never repaired

    Raises:
        - nothing
    """
    found = []
    for raw in BLOCK_RE.findall( body ):
        try:
            value = json.loads( raw )
        except json.JSONDecodeError:
            continue
        if is_miss( value ): found.append( value )
    return found


def collect( rows ):
    """
    Gather the misses of many store rows into one list.

    Requires:
        - rows is an iterable of dicts with a "body" key, a string or None

    Ensures:
        - returns misses sorted by ( receipt_id, symbol ), one per pair
        - when a pair appears twice, the repaired one wins, so a later repair is never lost

    Raises:
        - nothing
    """
    by_key = {}
    for row in rows:
        for miss in parse_block( row[ "body" ] or "" ):
            key = ( miss[ "receipt_id" ], miss[ "symbol" ] )
            if key not in by_key or miss[ "repaired" ]: by_key[ key ] = miss
    return [ by_key[ k ] for k in sorted( by_key ) ]


def export_misses( rows, path ):
    """
    Write the misses of many store rows to a JSON Lines file, replacing it atomically.

    Requires:
        - rows is an iterable of dicts with a "body" key, as collect reads them
        - the folder of path exists

    Ensures:
        - path holds one sorted-key JSON object per line, in collect order, UTF-8
        - a reader never sees a half-written file, and a failed write leaves the old file
        - returns the number of misses written; zero writes an empty file

    Raises:
        - OSError when the folder cannot be written
    """
    misses = collect( rows )
    text   = "".join( json.dumps( m, sort_keys=True ) + "\n" for m in misses )
    fd, tmp = tempfile.mkstemp( dir=os.path.dirname( os.path.abspath( path ) ), prefix=".misses-" )
    try:
        with os.fdopen( fd, "w", encoding="utf-8" ) as handle: handle.write( text )
        os.replace( tmp, path )
    except BaseException:
        if os.path.exists( tmp ): os.unlink( tmp )
        raise
    return len( misses )
