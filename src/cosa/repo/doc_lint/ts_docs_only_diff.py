"""
Docs-only diff check for scripts: a comment rewrite must leave the code unchanged.

A .ts, .js or .mjs file passes when its code tokens are identical once comments are removed. Its
directive comments (ts-ignore, eslint, istanbul, hashbang, banner) must match too. In a JavaScript
file the typed documentation tags must match as well, because the compiler reads them as types.
A failure names the first difference. Every other changed file type, a mode change and an
untracked new file fail, except markdown, which is the documentation itself. Not wired into a gate.

The tokens come from src/scripts/ts_code_tokens.mjs, which walks the compiler's parse tree and
reads comment records from ts_doc_extract.mjs. The git reading is that of docs_only_diff.

What "docs-only" means here, and does not:
    - a file that does not parse on either side fails, since no proof is possible
    - a documentation tag in a .ts file is documentation; the compiler ignores it there
    - a comment that merely looks like a directive also fails; that errs toward a failure
"""

import argparse
import json
import os
import subprocess
import sys

from . import docs_only_diff as dod

SUFFIXES = ( ".ts", ".js", ".mjs" )
TOKENS_REL = "src/scripts/ts_code_tokens.mjs"


def analyse( root, items ):
    """
    Run the Node token script over texts and return its descriptions by id.

    Requires:
        - root is a git working tree that holds the token script
        - items is a list of { id, name, text }

    Ensures:
        - returns { id: description } for every item, in one Node process
        - an empty list starts no process

    Raises:
        - RuntimeError when Node cannot start, exits non-zero, or prints a line that is not JSON
        - RuntimeError naming each id that came back without a description
    """
    if not items: return {}
    script = os.path.join( str( root ), TOKENS_REL )
    try:
        res = subprocess.run( [ "node", script ], input=json.dumps( items ), capture_output=True, text=True, encoding="utf-8" )
    except OSError as err:
        raise RuntimeError( f"cannot run node: {err}" ) from err
    if res.returncode != 0: raise RuntimeError( f"token script failed: {res.stderr.strip()}" )
    found = {}
    for raw in res.stdout.split( "\n" ):
        if not raw.strip(): continue
        try:
            record = json.loads( raw )
        except json.JSONDecodeError as err:
            raise RuntimeError( f"token script printed a line that is not JSON: {raw[ : 80 ]!r}" ) from err
        found[ record[ "id" ] ] = record
    missing = [ item[ "id" ] for item in items if item[ "id" ] not in found ]
    if missing: raise RuntimeError( f"token script gave no description for: {', '.join( missing )}" )
    return found


def description_difference( old, new ):
    """
    Compare two descriptions from the token script.

    Requires:
        - old and new are descriptions as analyse returns them

    Ensures:
        - returns None when the code tokens, shebang, directives and typed tags all match
        - otherwise returns a string naming the first difference and its new-file line
        - a description with a parse error is a difference, named with its side and line

    Raises:
        - nothing
    """
    for side, record in ( ( "old", old ), ( "new", new ) ):
        if record[ "errors" ]:
            first = record[ "errors" ][ 0 ]
            return f"{side} file does not parse, line {first[ 'line' ]}: {first[ 'message' ]}"
    for ( _, kind_a, a ), ( line, kind_b, b ) in zip( old[ "tokens" ], new[ "tokens" ] ):
        if a != b or kind_a != kind_b: return f"line {line}: token {a!r} became {b!r}"
    if len( old[ "tokens" ] ) != len( new[ "tokens" ] ):
        longer = old[ "tokens" ] if len( old[ "tokens" ] ) > len( new[ "tokens" ] ) else new[ "tokens" ]
        line, _, text = longer[ min( len( old[ "tokens" ] ), len( new[ "tokens" ] ) ) ]
        return f"{'removed' if longer is old[ 'tokens' ] else 'added'} token {text!r} at line {line}"
    if old[ "shebang" ] != new[ "shebang" ]: return f"hashbang changed {old[ 'shebang' ]!r} -> {new[ 'shebang' ]!r}"
    if old[ "directives" ] != new[ "directives" ]:
        removed = [ d for d in old[ "directives" ] if d not in new[ "directives" ] ]
        added   = [ d for d in new[ "directives" ] if d not in old[ "directives" ] ]
        return f"directive comments differ, removed {removed!r}, added {added!r}"
    if old[ "tags" ] != new[ "tags" ]: return f"typed documentation tags differ, {old[ 'tags' ]!r} -> {new[ 'tags' ]!r}"
    return None


def path_difference( path, modes, old_source, new_source, described=None ):
    """
    Judge one changed path.

    Requires:
        - modes is ( old_mode, new_mode ) from docs_only_diff.changed_files
        - old_source and new_source are the file text on each side, or None when absent
        - described is ( old_description, new_description ) when both sides exist and the path is a script

    Ensures:
        - a file type other than .ts, .js and .mjs fails as unchecked
        - a mode change on a file present on both sides fails
        - a file added or deleted fails, because its code appeared or vanished
        - otherwise the answer is description_difference

    Raises:
        - nothing
    """
    if not path.endswith( SUFFIXES ): return "file type not checked, only .ts, .js and .mjs are compared"
    old_mode, new_mode = modes
    if "000000" not in modes and old_mode != new_mode: return f"mode changed {old_mode} -> {new_mode}"
    if old_source is None: return "file added"
    if new_source is None: return "file deleted"
    return description_difference( *described )


def check_diff( root, base, head=None, paths=None, run=None ):
    """
    Check every changed file between base and head.

    Requires:
        - root is a git working tree; base is a revision
        - head is a revision, or None for the working tree
        - paths is a list of repo-relative prefixes, or None for every changed file
        - run replaces analyse in a test; it takes ( root, items ) and returns descriptions by id

    Ensures:
        - returns [ ( path, None or failure string ) ] sorted by path, one entry per changed file that is not markdown
        - with paths given, only files under one of those prefixes are checked, by whole directory names
        - both sides of every script file go to Node in one process
        - renames count as a delete plus an add, so a moved file fails

    Raises:
        - RuntimeError from git or from the token script when a command fails
    """
    run     = analyse if run is None else run
    chosen  = []
    for path, modes in sorted( dod.changed_files( root, base, head ).items() ):
        if path.endswith( dod.DOC_SUFFIX ): continue
        if paths is not None and not any( path == p or path.startswith( p.rstrip( "/" ) + "/" ) for p in paths ): continue
        chosen.append( ( path, modes, dod._show( root, base, path ), dod._show( root, head, path ) ) )
    items = []
    for path, _, old, new in chosen:
        if path.endswith( SUFFIXES ) and old is not None and new is not None:
            items.append( { "id": f"old:{path}", "name": path, "text": old } )
            items.append( { "id": f"new:{path}", "name": path, "text": new } )
    described = run( root, items )
    results   = []
    for path, modes, old, new in chosen:
        pair = ( described.get( f"old:{path}" ), described.get( f"new:{path}" ) )
        results.append( ( path, path_difference( path, modes, old, new, pair ) ) )
    return results


def main( argv=None, out=None ):
    """
    Command-line entry: print a pass or fail line per changed file.

    Requires:
        - argv is a list of arguments, or None for sys.argv

    Ensures:
        - returns 0 when every changed file is docs-only, 1 when any is not
        - an empty change list passes

    Raises:
        - RuntimeError from git or the token script when a command fails
    """
    out    = out if out is not None else sys.stdout
    parser = argparse.ArgumentParser( description="Prove a diff changed only comments in scripts" )
    parser.add_argument( "--base", required=True, help="revision to compare from" )
    parser.add_argument( "--head", help="revision to compare to; default is the working tree" )
    parser.add_argument( "--repo-root", default=".", help="git working tree to read" )
    parser.add_argument( "--paths", nargs="+", help="check only files under these repo-relative directories or files" )
    args    = parser.parse_args( argv )
    results = check_diff( args.repo_root, args.base, args.head, args.paths )
    for path, failure in results: out.write( f"PASS {path}\n" if failure is None else f"FAIL {path}: {failure}\n" )
    failed = sum( 1 for _, failure in results if failure is not None )
    out.write( f"{len( results ) - failed} passed, {failed} failed (docs-only means no code token or directive changed)\n" )
    return 1 if failed else 0


if __name__ == "__main__": sys.exit( main() )  # pragma: no cover -- script entry, main() is tested
