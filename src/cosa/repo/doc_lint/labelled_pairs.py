"""
Loader for the labelled before/after set, in the shape the judge harness reads.

The labelled set keeps each pair in one file and its key in another. A pair names its design
document linked_doc, and its key holds the seeded span as text. The harness wants design and a
( start, end ) span in the old text. This module joins the two. It refuses any path that names
the gate split or a gate key, so an implementer's run cannot open them by accident.
"""

import json
import os


def refuse_gate_path( path ):
    """
    Refuse a path that names the gate split or a gate key file.

    Requires:
        - path is a str or path-like

    Raises:
        - ValueError if any component of the path is "gate" or starts with "gate-"
    """
    for part in os.path.normpath( os.fspath( path ) ).split( os.sep ):
        if part == "gate" or part.startswith( "gate-" ):
            raise ValueError( f"{path} names the gate split; only the dev split may be opened here" )


def _read_jsonl( path ):
    """Return the records of a JSON Lines file, skipping blank lines."""
    with open( path, encoding="utf-8" ) as f:
        return [ json.loads( line ) for line in f if line.strip() ]


def load_pairs( pairs_path, keys_path ):
    """
    Join a pairs file and its keys file into harness pairs.

    Requires:
        - pairs_path and keys_path name JSON Lines files whose ids match one to one
        - neither path names the gate split

    Ensures:
        - returns one { id, old, new, design, seed_span } per pair, in file order
        - design is the pair's linked_doc, or None when that is empty
        - seed_span is ( start, end ) of the key's x_span_in_old in the old text when the key is a
          seeded positive, otherwise None; a relocated claim is not a seeded removal

    Raises:
        - ValueError for a gate path, ids that do not match, or a seeded span that is not in the old text
    """
    refuse_gate_path( pairs_path )
    refuse_gate_path( keys_path )
    pairs = _read_jsonl( pairs_path )
    keys  = { key[ "id" ]: key for key in _read_jsonl( keys_path ) }
    if sorted( keys ) != sorted( pair[ "id" ] for pair in pairs ):
        raise ValueError( "pair ids and key ids do not match one to one" )
    out = []
    for pair in pairs:
        key  = keys[ pair[ "id" ] ]
        span = None
        if key[ "seeded_positive" ]:
            start = pair[ "old" ].find( key[ "x_span_in_old" ] )
            if start < 0: raise ValueError( f"pair {pair[ 'id' ]}: the seeded span is not in the old text" )
            span = ( start, start + len( key[ "x_span_in_old" ] ) )
        out.append( { "id": pair[ "id" ], "old": pair[ "old" ], "new": pair[ "new" ],
                      "design": pair[ "linked_doc" ] or None, "seed_span": span } )
    return out
