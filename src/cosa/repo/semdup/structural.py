"""Structural clone pairs from jscpd (script) and dups (Python), mapped to definitions."""
import collections
import pathlib

from cosa.repo.symindex import dups
from cosa.repo.symindex.py_index import module_name


def _covered( fragment, by_file, cover ):
    """
    List the ids of the definitions a clone fragment covers by a share of their lines.

    Requires:
        - fragment is a jscpd { name, start, end } with 1-based inclusive lines
        - by_file maps a file path to its definitions
        - cover is a share from 0 to 1

    Ensures:
        - a definition is listed when the lines it shares with the fragment are at least cover times its own line count
        - a fragment that spans two definitions lists both, when each is covered enough
        - a definition the fragment does not touch is never listed
    """
    ids = []
    for d in by_file.get( fragment[ "name" ], [] ):
        length  = d[ "end_line" ] - d[ "line" ] + 1
        overlap = min( fragment[ "end" ], d[ "end_line" ] ) - max( fragment[ "start" ], d[ "line" ] ) + 1
        if overlap > 0 and overlap >= cover * length: ids.append( d[ "id" ] )
    return ids


def parse_jscpd( report, defs, cover ):
    """
    Turn a jscpd JSON report into pairs of definitions.

    Requires:
        - report is the parsed jscpd-report.json, with file names relative to the root the definitions are relative to
        - defs are script definition records from extract
        - cover is the frozen clone_cover

    Ensures:
        - returns pairs { ids, size, source }, ids sorted, size the clone's token count, source "jscpd"
        - two definitions are paired when one clone covers each by at least cover of its lines
        - a pair found by several clones keeps the largest size
        - ordered by size, largest first, then by ids
        - a definition is never paired with itself
    """
    by_file = collections.defaultdict( list )
    for d in defs: by_file[ d[ "file" ] ].append( d )
    sizes = {}
    for clone in report[ "duplicates" ]:
        for a in _covered( clone[ "firstFile" ], by_file, cover ):
            for b in _covered( clone[ "secondFile" ], by_file, cover ):
                if a == b: continue
                key = tuple( sorted( ( a, b ) ) )
                sizes[ key ] = max( sizes.get( key, 0 ), clone[ "tokens" ] )
    return sorted( ( { "ids": list( ids ), "size": size, "source": "jscpd" } for ids, size in sizes.items() ), key=lambda p: ( -p[ "size" ], p[ "ids" ] ) )


def _dups_keys( spec, paths, defs ):
    """
    Map the ids dups.find_duplicates gives to the definition ids of this package.

    Requires:
        - paths are the Python files in the order extract_tree read them, and defs their definitions in extraction order

    Ensures:
        - returns { dups id: definition id }, numbering a repeated dups id "~2", "~3" as dups does

    Raises:
        - ValueError if a definition's file is not among the paths
    """
    modules = {}
    for p in paths: modules[ pathlib.Path( p ).relative_to( spec.root ).as_posix() ] = module_name( spec, pathlib.Path( p ) )
    keys, seen = {}, collections.Counter()
    for d in defs:
        if d[ "file" ] not in modules: raise ValueError( f"{d[ 'file' ]} is not one of the Python files given" )
        key = ".".join( x for x in ( modules[ d[ "file" ] ], d[ "name" ] ) if x )
        seen[ key ] += 1
        keys[ key if seen[ key ] == 1 else f"{key}~{seen[ key ]}" ] = d[ "id" ]
    return keys


def python_clones( spec, paths, defs, min_nodes, threshold=dups.DEFAULT_THRESH ):
    """
    Map the exact and near pairs of dups.find_duplicates onto definitions.

    Requires:
        - spec is the IndexSpec of the root; paths are the Python files in the order extract_tree read them
        - defs are the Python definitions extract_tree returned for those files, in its order
        - min_nodes is the frozen minimum; threshold is the near-pair Jaccard cut, the dups default unless given

    Ensures:
        - returns pairs { ids, size, source }, ids sorted, source "dups", ordered by size and then ids
        - an exact clone has similarity 1.0; a near clone carries the Jaccard dups found
        - size is the similarity times the node count of the smaller definition, rounded, so it grows with the code shared
        - a group of three exact clones gives all three pairs

    Raises:
        - ValueError if a file of defs is not among the paths, or dups names a definition this package does not have
    """
    keys  = _dups_keys( spec, paths, defs )
    nodes = { d[ "id" ]: d[ "nodes" ] for d in defs }
    found = dups.find_duplicates( spec, [ pathlib.Path( p ) for p in paths ], min_nodes=min_nodes, threshold=threshold )
    sims  = {}
    for group in found[ "exact" ]:
        for i, a in enumerate( group ):
            for b in group[ i + 1: ]: sims[ ( a, b ) ] = 1.0
    for near in found[ "near" ]: sims[ tuple( near[ "ids" ] ) ] = near[ "jaccard" ]
    pairs = {}
    for ( a, b ), sim in sims.items():
        for name in ( a, b ):
            if name not in keys: raise ValueError( f"dups reported {name}, which is not a definition of the given files" )
        ids = tuple( sorted( ( keys[ a ], keys[ b ] ) ) )
        pairs[ ids ] = { "ids": list( ids ), "size": round( sim * min( nodes[ ids[ 0 ] ], nodes[ ids[ 1 ] ] ) ), "source": "dups" }
    return sorted( pairs.values(), key=lambda p: ( -p[ "size" ], p[ "ids" ] ) )


def clone_pairs( *pair_lists ):
    """
    Merge pair lists from the structural sources into one.

    Requires:
        - each argument is a list of pairs from parse_jscpd or python_clones

    Ensures:
        - returns one list ordered by size, largest first, then by ids
        - a pair found by two sources keeps its larger size and the source that gave it
        - size is a token count for jscpd and an AST-node figure for dups, so the two are not on one scale; script and Python
          definitions are never paired by these sources, and the larger-size rule matters only for lists built by hand
    """
    best = {}
    for pairs in pair_lists:
        for p in pairs:
            key = tuple( p[ "ids" ] )
            if key not in best or p[ "size" ] > best[ key ][ "size" ]: best[ key ] = p
    return sorted( best.values(), key=lambda p: ( -p[ "size" ], p[ "ids" ] ) )
