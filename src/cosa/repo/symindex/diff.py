"""
Diff two index snapshots: symbols added, removed or changed between them.
"""
import json
import pathlib

from cosa.repo.symindex.build import read_header, read_symbols


def diff_symbols( old, new ):
    """
    Compare two lists of symbol dicts by id.

    Requires:
        - ids are unique inside each list
    Ensures:
        - returns { "added": [ids], "removed": [ids], "changed": [ { id, was, now } ] }, each sorted
        - a symbol is changed when its pin differs
    """
    o = { r[ "id" ]: r for r in old }
    n = { r[ "id" ]: r for r in new }
    return { "added"  : sorted( set( n ) - set( o ) ),
             "removed": sorted( set( o ) - set( n ) ),
             "changed": [ { "id": i, "was": o[ i ][ "pin" ], "now": n[ i ][ "pin" ] } for i in sorted( set( o ) & set( n ) ) if o[ i ][ "pin" ] != n[ i ][ "pin" ] ] }


def diff_generations( old_gen, new_gen, all_symbols=False ):
    """
    Diff two published generations.

    Ensures:
        - with all_symbols=False only public symbols are compared; with True every definition is,
          including _private names and nested helpers
        - when the two generations were built with different pin algorithms the result is
          { "algorithm_changed": { "was", "now" } } and no per-symbol list, since every pin would differ
    """
    a, b = read_header( old_gen )[ "pin_algorithm" ], read_header( new_gen )[ "pin_algorithm" ]
    if a != b: return { "algorithm_changed": { "was": a, "now": b } }
    return diff_symbols( read_symbols( old_gen, all_symbols ), read_symbols( new_gen, all_symbols ) )
