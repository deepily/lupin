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

    Ensures:
        - both the path as written and the real path it resolves to are checked, so a symlink
          named after a dev file cannot lead to a gate file

    Raises:
        - ValueError if any component of either is "gate" or starts with "gate-"
    """
    for candidate in ( os.path.normpath( os.fspath( path ) ), os.path.realpath( os.fspath( path ) ) ):
        for part in candidate.split( os.sep ):
            if part == "gate" or part.startswith( "gate-" ):
                raise ValueError( f"{path} names the gate split; only the dev split may be opened here" )


def _read_jsonl( path ):
    """Return the records of a JSON Lines file, skipping blank lines."""
    with open( path, encoding="utf-8" ) as f:
        return [ json.loads( line ) for line in f if line.strip() ]


def load_pairs( pairs_path, keys_path, gate=False ):
    """
    Join a pairs file and its keys file into harness pairs.

    Requires:
        - pairs_path and keys_path name JSON Lines files whose ids match one to one
        - neither path names the gate split, unless gate is True
        - gate is True only for the sanctioned gate run: the caller has already checked that the
          thresholds, the prompt versions and the sha of the pairs file are the frozen ones, and the
          run is made by a seat other than the implementer

    Ensures:
        - returns one { id, old, new, design, seed_span } per pair, in file order
        - design is the pair's linked_doc, or None when that is empty
        - seed_span is ( start, end ) of the key's x_span_in_old in the old text when the key is a
          seeded positive, otherwise None; a relocated claim is not a seeded removal

    Raises:
        - ValueError for a gate path without gate=True, a repeated id in either file, ids that do not
          match, or a seeded span that is absent from the old text or occurs there more than once
    """
    if not gate:
        refuse_gate_path( pairs_path )
        refuse_gate_path( keys_path )
    pairs   = _read_jsonl( pairs_path )
    key_rows = _read_jsonl( keys_path )
    pair_ids = [ pair[ "id" ] for pair in pairs ]
    key_ids  = [ key[ "id" ] for key in key_rows ]
    if len( set( pair_ids ) ) != len( pair_ids ) or len( set( key_ids ) ) != len( key_ids ):
        raise ValueError( "an id is repeated in the pairs file or the keys file" )
    if sorted( key_ids ) != sorted( pair_ids ):
        raise ValueError( "pair ids and key ids do not match one to one" )
    keys = { key[ "id" ]: key for key in key_rows }
    out = []
    for pair in pairs:
        key  = keys[ pair[ "id" ] ]
        span = None
        if key[ "seeded_positive" ]:
            found = pair[ "old" ].count( key[ "x_span_in_old" ] )
            if found != 1: raise ValueError( f"pair {pair[ 'id' ]}: the seeded span is not in the old text exactly once ({found} times)" )
            start = pair[ "old" ].find( key[ "x_span_in_old" ] )
            span = ( start, start + len( key[ "x_span_in_old" ] ) )
        out.append( { "id": pair[ "id" ], "old": pair[ "old" ], "new": pair[ "new" ],
                      "design": pair[ "linked_doc" ] or None, "seed_span": span } )
    return out
