"""
Docs-only diff check for scripts: a comment rewrite must leave the code unchanged.

A .ts, .js or .mjs file passes when its code tokens are identical once comments are removed.
So is the line break before each token, since a moved break changes parsing after return.
Every comment that a tool reads must keep its text and its place: ts-ignore, eslint, coverage,
pure, bundler and banner comments. In a JavaScript file the typed documentation tags must match
too, because the compiler reads them as types. A failure names the first difference.
Every other changed file type, a mode change and an untracked new file fail, except markdown,
which is the documentation itself. Not wired into a gate.

The tokens come from src/scripts/ts_code_tokens.mjs, which walks the compiler's parse tree and
reads comment records from ts_doc_extract.mjs. The git reading is local, so that a name or a
text that is not UTF-8 fails one file and does not stop the run.

What "docs-only" means here, and does not:
    - a file that does not parse on either side fails, since no proof is possible
    - a documentation tag in a .ts file is documentation; the compiler ignores it there
    - a comment that merely looks like a directive also fails; that errs toward a failure
    - a block comment that gains a line break between two tokens fails, since it moves a break
    - a JSDoc tag such as @private, @readonly, @override or @deprecated is not compared
    - the position of a typed tag in a .js file is not compared, only the tags and their types
    - a prose line comment that starts with global, exported or region is refused as a directive
"""

import argparse
import json
import os
import subprocess
import sys

from . import docs_only_diff as dod

SUFFIXES   = ( ".ts", ".js", ".mjs" )
TOKENS_REL = "src/scripts/ts_code_tokens.mjs"
NOT_UTF8   = object()


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


def _git( root, *args ):
    """
    Run git in root and return stdout as bytes.

    Requires:
        - root is a git working tree

    Ensures:
        - returns the raw stdout, so a name or text that is not UTF-8 is not decoded here

    Raises:
        - RuntimeError naming the git error when the command fails
    """
    res = subprocess.run( [ "git", "-C", str( root ), *args ], capture_output=True )
    if res.returncode != 0: raise RuntimeError( f"git {' '.join( args )} failed: {res.stderr.decode( 'utf-8', 'replace' ).strip()}" )
    return res.stdout


def _show( root, rev, path ):
    """
    Read a file at a revision, or the working tree when rev is None.

    Requires:
        - root is a git working tree; path may hold surrogate-escaped bytes

    Ensures:
        - returns the bytes, or None when the file does not exist there

    Raises:
        - nothing
    """
    raw = os.fsencode( path )
    if rev is None:
        try:
            with open( os.path.join( os.fsencode( str( root ) ), raw ), "rb" ) as handle: return handle.read()
        except FileNotFoundError: return None
    res = subprocess.run( [ "git", "-C", str( root ), "show", rev.encode() + b":" + raw ], capture_output=True )
    return res.stdout if res.returncode == 0 else None


def changed_files( root, base, head=None ):
    """
    List every path that differs between base and head, with its modes.

    Requires:
        - root is a git working tree; base is a revision
        - head is a revision, or None for the working tree

    Ensures:
        - returns { path: ( old_mode, new_mode ) } read with -z, so a non-ASCII name is not quoted
        - a name that is not UTF-8 comes back surrogate-escaped, and os.fsencode restores its bytes
        - renames count as a delete plus an add
        - in working-tree mode, untracked files that git does not ignore have old mode "000000"

    Raises:
        - RuntimeError from git when a command fails
    """
    args  = [ "diff", "--raw", "-z", "--no-renames", base ] + ( [ head ] if head else [] )
    parts = _git( root, *args ).split( b"\0" )
    found = {}
    for meta, path in zip( parts[ 0::2 ], parts[ 1::2 ] ):
        modes = meta.split()
        found[ os.fsdecode( path ) ] = ( modes[ 0 ][ 1: ].decode(), modes[ 1 ].decode() )
    if head is None:
        for path in _git( root, "ls-files", "--others", "--exclude-standard", "-z" ).split( b"\0" ):
            if path: found[ os.fsdecode( path ) ] = ( "000000", "100644" )
    return found


def _decode( data ):
    """
    Decode file bytes as UTF-8.

    Requires:
        - data is bytes, or None for a file that is absent

    Ensures:
        - returns the text, None for absent, or NOT_UTF8 when the bytes do not decode

    Raises:
        - nothing
    """
    if data is None: return None
    try:
        return data.decode( "utf-8" )
    except UnicodeDecodeError:
        return NOT_UTF8


def description_difference( old, new ):
    """
    Compare two descriptions from the token script.

    Requires:
        - old and new are descriptions as analyse returns them

    Ensures:
        - returns None when the code tokens, line breaks, shebang, directives, marks and typed tags all match
        - otherwise returns a string naming the first difference and its new-file line
        - a description with a parse error is a difference, named with its side and line

    Raises:
        - nothing
    """
    for side, record in ( ( "old", old ), ( "new", new ) ):
        if record[ "errors" ]:
            first = record[ "errors" ][ 0 ]
            return f"{side} file does not parse, line {first[ 'line' ]}: {first[ 'message' ]}"
    for ( _, kind_a, a, break_a ), ( line, kind_b, b, break_b ) in zip( old[ "tokens" ], new[ "tokens" ] ):
        if a != b or kind_a != kind_b: return f"line {line}: token {a!r} became {b!r}"
        if break_a != break_b: return f"line {line}: a line break before token {b!r} was {'added' if break_b else 'removed'}"
    if len( old[ "tokens" ] ) != len( new[ "tokens" ] ):
        longer = old[ "tokens" ] if len( old[ "tokens" ] ) > len( new[ "tokens" ] ) else new[ "tokens" ]
        line, _, text, _ = longer[ min( len( old[ "tokens" ] ), len( new[ "tokens" ] ) ) ]
        return f"{'removed' if longer is old[ 'tokens' ] else 'added'} token {text!r} at line {line}"
    if old[ "shebang" ] != new[ "shebang" ]: return f"hashbang changed {old[ 'shebang' ]!r} -> {new[ 'shebang' ]!r}"
    if old[ "directives" ] != new[ "directives" ]:
        removed = [ d for d in old[ "directives" ] if d not in new[ "directives" ] ]
        added   = [ d for d in new[ "directives" ] if d not in old[ "directives" ] ]
        return f"directive comments differ, removed {removed!r}, added {added!r}"
    if old[ "marks" ] != new[ "marks" ]:
        removed = [ m[ 1 ] for m in old[ "marks" ] if m not in new[ "marks" ] ]
        added   = [ m[ 1 ] for m in new[ "marks" ] if m not in old[ "marks" ] ]
        return f"a comment read by a tool moved or changed, removed {removed!r}, added {added!r}"
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
    for path, modes in sorted( changed_files( root, base, head ).items() ):
        if path.endswith( dod.DOC_SUFFIX ): continue
        if paths is not None and not any( path == p or path.startswith( p.rstrip( "/" ) + "/" ) for p in paths ): continue
        chosen.append( ( path, modes, _decode( _show( root, base, path ) ), _decode( _show( root, head, path ) ) ) )
    items = []
    for path, _, old, new in chosen:
        if path.endswith( SUFFIXES ) and isinstance( old, str ) and isinstance( new, str ):
            items.append( { "id": f"old:{path}", "name": path, "text": old } )
            items.append( { "id": f"new:{path}", "name": path, "text": new } )
    described = run( root, items )
    results   = []
    for path, modes, old, new in chosen:
        if path.endswith( SUFFIXES ) and ( old is NOT_UTF8 or new is NOT_UTF8 ):
            results.append( ( path, "file content is not valid UTF-8, not compared" ) )
            continue
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
    for path, failure in results:
        shown = path.encode( "utf-8", "backslashreplace" ).decode( "utf-8" )
        out.write( f"PASS {shown}\n" if failure is None else f"FAIL {shown}: {failure}\n" )
    failed = sum( 1 for _, failure in results if failure is not None )
    out.write( f"{len( results ) - failed} passed, {failed} failed (docs-only means no code token or directive changed)\n" )
    return 1 if failed else 0


if __name__ == "__main__": sys.exit( main() )  # pragma: no cover -- script entry, main() is tested
