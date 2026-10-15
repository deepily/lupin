"""
Purpose lines: one sentence per index entry that says what the entry is for.

A line is written once per pin by a bounded Claude Code job, and never regenerated on read.
The job receives ids and reads the tree itself. Its output is screened before it is stored.
"""
import collections
import hashlib
import json
import os
import pathlib

PROMPT_TEXT = (
    "For each entry id in the request, read its source in this repository and write one purpose line. "
    "A purpose line is one sentence of at most 25 words that starts with a verb. "
    "It says what the entry is for, in words a colleague would use to describe a need. "
    "It repeats no name, quotes no code and names no file. "
    "Reply with JSON only: a list of objects { \"id\": <entry id>, \"purpose\": <the line> }."
)
MAX_WORDS  = 25
BATCH_SIZE = 25

Screen = collections.namedtuple( "Screen", [ "sendable", "hits" ] )


def prompt_hash():
    """
    Return the short hash of the purpose-line prompt.

    Ensures:
        - returns the first 16 hex characters of the sha256 of PROMPT_TEXT
        - changes whenever the prompt text changes
    """
    return hashlib.sha256( PROMPT_TEXT.encode( "utf-8" ) ).hexdigest()[ :16 ]


def default_screen():
    """
    Return the index's own screening functions, loaded on first use.

    Ensures:
        - returns a Screen of reuse_tools.sendable and reuse_tools.c1_hits
    """
    from lupin_mcp import reuse_tools
    return Screen( reuse_tools.sendable, reuse_tools.c1_hits )


def load_lines( store_path ):
    """
    Read the stored purpose lines.

    Requires:
        - store_path is the purpose.jsonl path

    Ensures:
        - returns { pin: row } where a row holds pin, purpose, prompt_hash and writer_version
        - a missing file is an empty mapping
        - the first row stored for a pin wins
    """
    path = pathlib.Path( store_path )
    if not path.is_file(): return {}
    rows = {}
    for line in path.read_text( encoding="utf-8" ).splitlines():
        if not line.strip(): continue
        row = json.loads( line )
        rows.setdefault( row[ "pin" ], row )
    return rows


def judge_purpose( purpose, hits ):
    """
    Decide whether a written line may be stored.

    Requires:
        - hits is the screening function that names the sensitive shapes in a record

    Ensures:
        - returns None when the line is acceptable
        - otherwise returns the reason: "not_text", "empty", "too_long" or "screen:<kinds>"
    """
    if not isinstance( purpose, str ): return "not_text"
    if not purpose.strip(): return "empty"
    if len( purpose.split() ) > MAX_WORDS: return "too_long"
    found = hits( { "id": "", "sig": "", "doc": purpose } )
    if found: return "screen:" + ",".join( found )
    return None


def write_purpose_lines( entries, writer, store_path, writer_version, screen, batch_size=BATCH_SIZE ):
    """
    Write the lines that are missing, and keep the ones that are stored.

    Requires:
        - entries is a list of index records with id, sig, doc and pin
        - writer is a callable taking a list of ids and returning { id: purpose }
        - screen is a Screen of the index's sendable and hits functions

    Ensures:
        - only entries that pass sendable and hold no stored line for their pin are sent
        - the writer receives ids only, never source text
        - a line that fails judge_purpose is dropped and listed, never stored
        - a stored row is never rewritten, and a changed pin is written as a new row
        - returns { written, kept, dropped_screen, dropped_output, missing }, each a count or sorted id list
    """
    stored                       = load_lines( store_path )
    kept_entries, dropped_screen = screen.sendable( entries )
    todo, seen, kept             = [], set(), 0
    for e in kept_entries:
        if e[ "pin" ] in stored: kept += 1; continue
        if e[ "pin" ] in seen: continue
        seen.add( e[ "pin" ] )
        todo.append( e )
    written, dropped_output, missing = 0, [], []
    path = pathlib.Path( store_path )
    path.parent.mkdir( parents=True, exist_ok=True )
    for i in range( 0, len( todo ), batch_size ):
        batch   = todo[ i:i + batch_size ]
        answers = writer( [ e[ "id" ] for e in batch ] )
        rows    = []
        for e in batch:
            if e[ "id" ] not in answers: missing.append( e[ "id" ] ); continue
            reason = judge_purpose( answers[ e[ "id" ] ], screen.hits )
            if reason is not None: dropped_output.append( { "id": e[ "id" ], "reason": reason } ); continue
            rows.append( { "pin": e[ "pin" ], "purpose": answers[ e[ "id" ] ].strip(), "prompt_hash": prompt_hash(), "writer_version": writer_version } )
        if rows:
            with open( path, "a", encoding="utf-8" ) as f:
                for r in rows: f.write( json.dumps( r, sort_keys=True ) + "\n" )
                f.flush()
                os.fsync( f.fileno() )
            written += len( rows )
    return { "written": written, "kept": kept, "dropped_screen": sorted( dropped_screen ),
             "dropped_output": sorted( dropped_output, key=lambda d: d[ "id" ] ), "missing": sorted( missing ) }
