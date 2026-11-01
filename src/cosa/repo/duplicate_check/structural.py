"""Structural clone pairs from jscpd (script) and dups (Python), mapped to definitions."""
import collections
import json
import pathlib
import subprocess
import tempfile

import cosa.utils.util as cu
from cosa.repo.semdup import errors as err
from cosa.repo.symindex import dups, js_index
from cosa.repo.symindex.py_index import module_name


JSCPD_TIMEOUT = 600
JSCPD_FORMATS = "typescript,javascript"


def _jscpd_script():
    """
    Find the installed jscpd launcher and the node that runs it.

    Ensures:
        - returns ( node path, launcher path )

    Raises:
        - SemdupError DEPENDENCY_MISSING if node or node_modules/.bin/jscpd is missing
    """
    launcher = pathlib.Path( cu.get_project_root() ) / "node_modules" / ".bin" / "jscpd"
    if not launcher.is_file(): raise err.SemdupError( err.DEPENDENCY_MISSING, f"{launcher} is missing; install the lock with npm ci" )
    try:
        return js_index.find_node(), launcher
    except js_index.DependencyMissing as exc:
        raise err.SemdupError( err.DEPENDENCY_MISSING, str( exc ) ) from exc


def run_jscpd( root, dirs, cfg ):
    """
    Run the installed jscpd over directories of a root and return its parsed JSON report.

    Requires:
        - root is a directory; dirs are folder names under it, relative to it, without a leading "./"
        - cfg is a frozen configuration whose jscpd block names the version, min_tokens, min_lines and max_size (jscpd skips any larger file without a word)

    Ensures:
        - jscpd scans "." from root, because it names files relative to the one folder it was given and two folders would give names that are not root-relative
        - returns the parsed report, the same shape parse_jscpd reads, keeping only clones whose two fragments both lie under dirs
        - the report is written to a temporary folder that is removed afterwards

    Raises:
        - SemdupError DEPENDENCY_MISSING if node or jscpd is missing, or the installed jscpd is not the frozen version
        - SemdupError RUN_INCOMPLETE if jscpd exits non-zero or writes no report
    """
    node, launcher = _jscpd_script()
    want           = cfg[ "jscpd" ][ "version" ]
    got            = subprocess.run( [ node, str( launcher ), "--version" ], capture_output=True, text=True, timeout=JSCPD_TIMEOUT ).stdout.strip()
    if got != f"jscpd {want}": raise err.SemdupError( err.DEPENDENCY_MISSING, f"the frozen jscpd version is {want}, the installed one says {got!r}" )
    with tempfile.TemporaryDirectory() as out:
        cmd = [ node, str( launcher ), "--min-tokens", str( cfg[ "jscpd" ][ "min_tokens" ] ), "--min-lines", str( cfg[ "jscpd" ][ "min_lines" ] ), "--max-size", cfg[ "jscpd" ][ "max_size" ],
                "--format", JSCPD_FORMATS, "--reporters", "json", "--output", out, "." ]
        res = subprocess.run( cmd, cwd=str( root ), capture_output=True, text=True, timeout=JSCPD_TIMEOUT )
        report = pathlib.Path( out ) / "jscpd-report.json"
        if res.returncode != 0 or not report.is_file():
            raise err.SemdupError( err.RUN_INCOMPLETE, f"jscpd exit {res.returncode}, report written: {report.is_file()}; {res.stderr.strip()[ -300: ]}" )
        parsed = json.loads( report.read_text( encoding="utf-8" ) )
    inside = lambda name: any( name.startswith( d.rstrip( "/" ) + "/" ) for d in dirs )
    parsed[ "duplicates" ] = [ c for c in parsed[ "duplicates" ] if inside( c[ "firstFile" ][ "name" ] ) and inside( c[ "secondFile" ][ "name" ] ) ]
    return parsed


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


def _map_pairs( found, keys, defs, source ):
    """
    Map the exact and near pairs dups found onto definitions.

    Requires:
        - found is dups.find_duplicates' result; keys maps each dups id to a definition id; defs are the definitions the keys name; source is the tag the pairs carry

    Ensures:
        - returns pairs { ids, size, source }, ids sorted, ordered by size and then ids
        - an exact clone has similarity 1.0; a near clone carries the Jaccard dups found
        - size is the similarity times the node count of the smaller definition, rounded, so it grows with the code shared
        - a group of three exact clones gives all three pairs

    Raises:
        - ValueError if dups names a definition that keys does not hold
    """
    nodes = { d[ "id" ]: d[ "nodes" ] for d in defs }
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
        pairs[ ids ] = { "ids": list( ids ), "size": round( sim * min( nodes[ ids[ 0 ] ], nodes[ ids[ 1 ] ] ) ), "source": source }
    return sorted( pairs.values(), key=lambda p: ( -p[ "size" ], p[ "ids" ] ) )


def python_clones( spec, paths, defs, min_nodes, threshold=dups.DEFAULT_THRESH ):
    """
    Map the exact and near pairs of dups.find_duplicates onto Python definitions.

    Requires:
        - spec is the IndexSpec of the root; paths are the Python files in the order extract_tree read them
        - defs are the Python definitions extract_tree returned for those files, in its order
        - min_nodes is the frozen minimum; threshold is the near-pair Jaccard cut, the dups default unless given

    Ensures:
        - returns the pairs _map_pairs gives, with source "dups"

    Raises:
        - ValueError if a file of defs is not among the paths, or dups names a definition this package does not have
    """
    keys  = _dups_keys( spec, paths, defs )
    found = dups.find_duplicates( spec, [ pathlib.Path( p ) for p in paths ], min_nodes=min_nodes, threshold=threshold )
    return _map_pairs( found, keys, defs, "dups" )


def _script_keys( defs ):
    """
    Map the ids dups gives a script definition to the definition ids of this package.

    Requires:
        - defs are script definitions in the order extract_tree read them

    Ensures:
        - returns { "<file>#<name>": id }, numbering a repeated key "~2", "~3" as dups does
    """
    keys, seen = {}, collections.Counter()
    for d in defs:
        key = f"{d[ 'file' ]}#{d[ 'name' ]}"
        seen[ key ] += 1
        keys[ key if seen[ key ] == 1 else f"{key}~{seen[ key ]}" ] = d[ "id" ]
    return keys


def script_clones( spec, files, defs, min_nodes, threshold=dups.DEFAULT_THRESH ):
    """
    Map the exact and near pairs dups finds among script files onto their definitions.

    Requires:
        - spec is the IndexSpec of the root the files lie under; files are the script files in the order extract_tree read them
        - defs are the script definitions extract_tree returned for those files, in its order
        - min_nodes is the frozen minimum; threshold is the near-pair Jaccard cut, the dups default unless given

    Ensures:
        - returns the pairs _map_pairs gives, with source "dups"
        - script definitions are paired with script definitions only, as dups does

    Raises:
        - ValueError if dups names a definition this package does not have
    """
    found = dups.find_duplicates( spec, [], min_nodes=min_nodes, threshold=threshold, js_files=[ pathlib.Path( f ) for f in files ] )
    return _map_pairs( found, _script_keys( defs ), defs, "dups" )


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
