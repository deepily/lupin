"""
The hard-negative selector for the labelled-pair run.

For each member of a twin group it picks neighbours that look alike on the surface but are not
twins. The look-alike measure is the overlap of identifier words. No model chooses, so it cannot
flatter either question. Each member keeps the random negatives the first labelled run drew for it,
when they are still in the index. It gains up to 25 lexical neighbours from its own package.

A neighbour whose words overlap the member's by 0.9 or more is held out for a person to read.
It may be a true twin that the manifest missed. A wrong label would corrupt the figures.
No model is called and nothing is sent anywhere.
"""
import argparse
import hashlib
import json
import pathlib
import re
import statistics

FORMAT             = "stage2-negatives-1"
LEXICAL_PER_MEMBER = 25
HELD_OUT_AT        = 0.9
MIN_WORD_LENGTH    = 3
PACKAGE_DEPTH      = 2
STOP_WORDS         = frozenset( ( "self", "cls", "the", "and", "for", "with", "from", "that", "this", "none", "true", "false", "are", "was", "not" ) )

_PIECES = re.compile( r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|[0-9]+" )


def words( text ):
    """
    Split text into identifier words.

    Ensures:
        - returns a frozenset of lower-case words cut at underscores, dots, digits and case changes
        - a run of capitals such as HTTP is one word
        - words shorter than the minimum, pure digits and the stop words are left out
    """
    out = set()
    for piece in _PIECES.findall( text ):
        w = piece.lower()
        if w.isdigit() or len( w ) < MIN_WORD_LENGTH or w in STOP_WORDS: continue
        out.add( w )
    return frozenset( out )


def surface_words( rec ):
    """
    Take the surface words of a symbol.

    Ensures:
        - returns the words of its own name, its signature and its first doc line, never its path
    """
    return words( rec[ "id" ].rsplit( ".", 1 )[ -1 ] ) | words( rec[ "sig" ] ) | words( rec[ "doc" ] )


def package_of( symbol_id ):
    """
    Name the package of an id.

    Ensures:
        - returns the first dotted parts of the id, as many as the depth; a shorter id is its own package
    """
    return ".".join( symbol_id.split( "." )[ :PACKAGE_DEPTH ] )


def jaccard( a, b ):
    """
    Measure the overlap of two word sets.

    Ensures:
        - returns the size of the intersection over the size of the union, or 0.0 when both are empty
    """
    union = a | b
    return len( a & b ) / len( union ) if union else 0.0


def lexical_negatives( member, entries, excluded, n ):
    """
    Pick the look-alike neighbours of one member.

    Requires:
        - member and entries are symbol dicts with id, sig, doc and lang
        - excluded is a set of ids that may not be chosen, such as the member's twins
    Ensures:
        - returns { chosen, held_out, pool }; pool counts the eligible entries
        - an eligible entry is of the member's language and package, is not the member, and is not excluded
        - chosen holds at most n entries with an overlap above zero and below the held-out bar,
          best first, ties by id, as { id, score }
        - held_out holds the eligible entries at or above the bar, in the same order
        - there is no top-up from another package, so a small package gives a short list
    """
    mine = surface_words( member )
    pool = [ e for e in entries if e[ "id" ] != member[ "id" ] and e[ "id" ] not in excluded
             and e[ "lang" ] == member[ "lang" ] and package_of( e[ "id" ] ) == package_of( member[ "id" ] ) ]
    scored = sorted( ( ( jaccard( mine, surface_words( e ) ), e[ "id" ] ) for e in pool ), key=lambda x: ( -x[ 0 ], x[ 1 ] ) )
    return { "chosen"   : [ { "id": i, "score": round( s, 6 ) } for s, i in scored if 0.0 < s < HELD_OUT_AT ][ :n ],
             "held_out" : [ { "id": i, "score": round( s, 6 ) } for s, i in scored if s >= HELD_OUT_AT ],
             "pool"     : len( pool ) }


def old_random_by_member( rows, twin_map ):
    """
    Read the random negatives the first labelled run drew.

    Requires:
        - rows are dicts with member and candidate; twin_map maps each member to its twins
    Ensures:
        - returns { member: [candidate, ...] } for every member of twin_map, in the order drawn
        - a twin of the member and a repeat are left out, and rows of other members are ignored
    """
    out = { m: [] for m in twin_map }
    for r in rows:
        m, c = r[ "member" ], r[ "candidate" ]
        if m in out and c not in twin_map[ m ] and c not in out[ m ]: out[ m ].append( c )
    return out


def select_negatives( twin_map, by_id, old_random ):
    """
    Choose the negatives of every member.

    Requires:
        - twin_map maps each member id to its twin ids; by_id maps each sendable id to its symbol dict
        - old_random maps a member to the random ids drawn for it before
    Ensures:
        - returns { members, summary }; for each member: twins, lexical, random, random_dropped, held_out,
          lexical_pool and short_by
        - random keeps the old draws that are still in the index and below the held-out bar, in the order drawn
        - random_dropped lists the old draws no longer in the index
        - an old draw is never chosen again as a lexical neighbour
        - the result does not depend on the order of the inputs
    Raises:
        - ValueError naming a member, or a twin, that is not in the index
    """
    for m in sorted( twin_map ):
        if m not in by_id: raise ValueError( f"member {m!r} is not in the index" )
        for t in twin_map[ m ]:
            if t not in by_id: raise ValueError( f"twin {t!r} of {m!r} is not in the index" )
    entries, members = [ by_id[ k ] for k in sorted( by_id ) ], {}
    for m in sorted( twin_map ):
        rec, twins, drawn = by_id[ m ], sorted( twin_map[ m ] ), old_random.get( m, [] )
        mine, kept, dropped, held = surface_words( rec ), [], [], []
        for c in drawn:
            if c not in by_id: dropped.append( c ); continue
            s = jaccard( mine, surface_words( by_id[ c ] ) )
            if s >= HELD_OUT_AT: held.append( { "id": c, "score": round( s, 6 ) } )
            else: kept.append( c )
        lex = lexical_negatives( rec, entries, set( twins ) | set( drawn ), LEXICAL_PER_MEMBER )
        members[ m ] = { "twins": twins, "lexical": lex[ "chosen" ], "random": kept, "random_dropped": dropped,
                         "held_out": sorted( held + lex[ "held_out" ], key=lambda c: ( -c[ "score" ], c[ "id" ] ) ),
                         "lexical_pool": lex[ "pool" ], "short_by": max( 0, LEXICAL_PER_MEMBER - len( lex[ "chosen" ] ) ) }
    return { "members": members, "summary": _summary( members ) }


def _summary( members ):
    """
    Count the selection.

    Ensures:
        - returns the shortfalls, drops, held-out entries and pairs
    """
    got = [ len( v[ "lexical" ] ) for v in members.values() ]
    twin_pairs, lexical_pairs = sum( len( v[ "twins" ] ) for v in members.values() ), sum( got )
    random_kept = sum( len( v[ "random" ] ) for v in members.values() )
    return { "members": len( members ), "short_of_25": sum( 1 for g in got if g < LEXICAL_PER_MEMBER ), "got_none": sum( 1 for g in got if g == 0 ),
             "got_none_members": sorted( m for m, v in members.items() if not v[ "lexical" ] ),
             "lexical_min": min( got ) if got else None, "lexical_median": statistics.median( got ) if got else None, "lexical_max": max( got ) if got else None,
             "twin_pairs": twin_pairs, "lexical_pairs": lexical_pairs, "random_kept": random_kept,
             "random_dropped": sum( len( v[ "random_dropped" ] ) for v in members.values() ),
             "held_out": sum( len( v[ "held_out" ] ) for v in members.values() ), "pairs": twin_pairs + lexical_pairs + random_kept }


def main( argv=None ):
    """
    Write the negatives record for a manifest, an index and the first run's pairs.

    Ensures:
        - reads the symbols through the one place that decides what may leave the machine
        - writes a record with the input sha256s, the constants, the members, the summary and the ids not sendable
        - prints the summary line and returns 0
    Raises:
        - FileExistsError when the output file exists, so a recorded selection is never overwritten
    """
    from cosa.repo.symindex import stage2_split as s2
    from lupin_mcp import reuse_tools as rt
    ap = argparse.ArgumentParser( description=__doc__ )
    for flag in ( "--manifest", "--symbols", "--old-stage2", "--out" ): ap.add_argument( flag, required=True )
    a   = ap.parse_args( argv )
    out = pathlib.Path( a.out )
    if out.exists(): raise FileExistsError( f"{out} already exists; a recorded selection is never overwritten" )
    raws = { k: pathlib.Path( getattr( a, k ) ).read_bytes() for k in ( "manifest", "symbols", "old_stage2" ) }
    twin_map = {}
    for g in s2.twin_groups( json.loads( raws[ "manifest" ] ) ):
        for i in g[ "members" ]: twin_map[ i ] = sorted( set( g[ "members" ] ) - { i } )
    kept, dropped = rt.sendable( [ json.loads( l ) for l in raws[ "symbols" ].decode().splitlines() if l.strip() ] )
    old   = old_random_by_member( json.loads( raws[ "old_stage2" ] )[ "rows" ], twin_map )
    chosen = select_negatives( twin_map, { r[ "id" ]: r for r in kept }, old )
    record = { "format": FORMAT, "inputs": { f"{k}_sha256": hashlib.sha256( v ).hexdigest() for k, v in raws.items() },
               "constants": { "lexical_per_member": LEXICAL_PER_MEMBER, "held_out_at": HELD_OUT_AT, "min_word_length": MIN_WORD_LENGTH, "package_depth": PACKAGE_DEPTH },
               "summary": chosen[ "summary" ], "members": chosen[ "members" ], "not_sendable": sorted( dropped ) }
    out.write_text( json.dumps( record, indent=1, sort_keys=True ) + "\n" )
    s = chosen[ "summary" ]
    print( f"members={s[ 'members' ]} short_of_25={s[ 'short_of_25' ]} got_none={s[ 'got_none' ]} lexical_median={s[ 'lexical_median' ]} "
           f"random_kept={s[ 'random_kept' ]} random_dropped={s[ 'random_dropped' ]} held_out={s[ 'held_out' ]} pairs={s[ 'pairs' ]}" )
    return 0


if __name__ == "__main__":
    raise SystemExit( main() )
