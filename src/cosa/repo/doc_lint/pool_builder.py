"""
The docstring pool builder: the input of the labelled-set seeder's plan step.

It walks the Python files of one git commit. It writes one JSON Lines row per docstring, in the
shape labelled_set_seeder reads: { id, file, symbol, old }. The files come from git at that commit,
never from the working tree. So the same commit gives the same bytes whatever is checked out.

The text of a row is inspect.cleandoc of the docstring: what a reader sees, with the indentation
that depends on nesting depth removed. The manifest records that choice.

A docstring whose text is the same as another's, after runs of whitespace are collapsed, is kept once.
The seeder splits whole directories between dev, gate and reserve but never compares text.
A copy in two directories could therefore land in dev and in the gate. The first row by id is kept;
the manifest lists every dropped id under the kept one, and the count.

A second file, <out>.manifest.json, records what the pool was built from. It holds the full source sha
and the sha256 of this builder's own file and of the pool. It also holds the counts, every file skipped
and why, and the duplicates dropped. The manifest is a separate file, so the pool stays exactly what the seeder
reads. Nothing in either file depends on the time or the machine.

The builder has no view on tests or on any other directory.
What is read is the run's --include and --exclude.
"""

import argparse
import ast
import hashlib
import json
import os
import subprocess
import sys

import cosa.utils.util as cu
from cosa.repo.doc_lint import labelled_set_seeder

# A path with one of these as a directory name is never read, tracked or not.
SKIP_PARTS    = frozenset( ( ".venv", "node_modules", "site-packages", "__pycache__" ) )
MODULE_SYMBOL = "<module>"
DEFINITIONS   = ( ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef )


def run_git( repo, args, data=None ):
    """
    Run one git command in repo and return its stdout bytes.

    Requires:
        - repo is a directory inside a git working tree; args is a list of git arguments

    Ensures:
        - returns the stdout bytes of a command that exited 0

    Raises:
        - RuntimeError naming the command and git's stderr when it exits non-zero
    """
    done = subprocess.run( [ "git", "-C", repo, *args ], input=data, capture_output=True )
    if done.returncode != 0: raise RuntimeError( f"git {' '.join( args )} failed: {done.stderr.decode( 'utf-8', 'replace' ).strip()}" )
    return done.stdout


def resolve_commit( repo, sha ):
    """Return the full 40-character sha of the commit sha names; RuntimeError when it names none."""
    return run_git( repo, [ "rev-parse", "--verify", "--quiet", sha + "^{commit}" ] ).decode( "ascii" ).strip()


def prefix_of( path ):
    """Return path as a directory prefix with one trailing slash, so src/cosa misses src/cosa_x."""
    return path.rstrip( "/" ) + "/"


def list_sources( repo, sha, include, exclude ):
    """
    List the Python blobs of one commit under the include and outside the exclude prefixes.

    Requires:
        - sha is a full commit sha; include is a non-empty list of directory prefixes; exclude is a list

    Ensures:
        - returns sorted ( path, blob oid ) pairs, tracked .py files only
        - a path with a directory named in SKIP_PARTS is left out
        - a submodule entry is left out: only blobs are listed

    Raises:
        - ValueError when include is empty, because the walk would then have no declared population
        - RuntimeError when git cannot list the commit
    """
    if not include: raise ValueError( "include at least one directory prefix: the pool's population is declared, not defaulted" )
    inside  = [ prefix_of( p ) for p in include ]
    outside = [ prefix_of( p ) for p in exclude ]
    found   = []
    for entry in run_git( repo, [ "ls-tree", "-r", "-z", "--full-tree", sha ] ).decode( "utf-8" ).split( "\0" ):
        if not entry: continue
        meta, path = entry.split( "\t", 1 )
        kind, oid  = meta.split()[ 1: 3 ]
        if kind != "blob" or not path.endswith( ".py" ): continue
        if not any( path.startswith( p ) for p in inside ) or any( path.startswith( p ) for p in outside ): continue
        if SKIP_PARTS & set( path.split( "/" )[ :-1 ] ): continue
        found.append( ( path, oid ) )
    return sorted( found )


def read_blobs( repo, oids ):
    """
    Read blobs by oid with one git process.

    Requires:
        - oids is a list of blob oids

    Ensures:
        - returns { oid: bytes } for every oid asked for

    Raises:
        - RuntimeError when git reports an oid missing or its answer cannot be parsed
    """
    wanted = list( dict.fromkeys( oids ) )
    out    = run_git( repo, [ "cat-file", "--batch" ], data=( "\n".join( wanted ) + "\n" ).encode( "ascii" ) ) if wanted else b""
    blobs  = {}
    pos    = 0
    for oid in wanted:
        end    = out.index( b"\n", pos )
        header = out[ pos:end ].decode( "ascii" ).split()
        if header[ :1 ] != [ oid ] or header[ 1: 2 ] != [ "blob" ]: raise RuntimeError( f"git cat-file did not return blob {oid}: {out[ pos:end ]!r}" )
        size        = int( header[ 2 ] )
        blobs[ oid ] = out[ end + 1:end + 1 + size ]
        pos          = end + 1 + size + 1
    return blobs


def docstrings_of( tree ):
    """
    Return ( symbol, docstring ) for the module and each class or function with one, in order.

    Requires:
        - tree is an ast.Module

    Ensures:
        - the docstring is inspect.cleandoc of the raw text, which is what ast.get_docstring returns
        - symbol is MODULE_SYMBOL for the module and a dotted name for the rest, so a method is Class.method
        - the whole tree is walked: a definition under an if, a try, a with or a loop is found, and is named
          as if it sat beside its neighbours
        - a docstring that is blank after strip is left out
    """
    found = []

    def visit( node, prefix ):
        text = ast.get_docstring( node )
        if text is not None and text.strip(): found.append( ( prefix or MODULE_SYMBOL, text ) )
        walk( node, prefix )

    def walk( node, prefix ):
        for child in ast.iter_child_nodes( node ):
            if isinstance( child, DEFINITIONS ): visit( child, prefix + "." + child.name if prefix else child.name )
            else:                                walk( child, prefix )

    visit( tree, "" )
    return found


def pool_rows( path, source ):
    """
    Return the pool rows of one source file, or the reason it was skipped.

    Requires:
        - source is the file's bytes

    Ensures:
        - returns ( rows, None ) with one { id, file, symbol, old } per docstring, or ( [], reason )
          where reason is "encoding" for text that is not UTF-8 or "syntax" for text that does not parse
        - ids are "<file>::<symbol>", and a second definition of the same name in one file gets "#2", "#3" in source order
    """
    try:
        tree = ast.parse( source.decode( "utf-8" ) )
    except UnicodeDecodeError:
        return [], "encoding"
    except ( SyntaxError, ValueError ):
        return [], "syntax"
    seen = {}
    rows = []
    for symbol, text in docstrings_of( tree ):
        seen[ symbol ] = seen.get( symbol, 0 ) + 1
        suffix = "" if seen[ symbol ] == 1 else f"#{seen[ symbol ]}"
        rows.append( { "id": f"{path}::{symbol}{suffix}", "file": path, "symbol": symbol, "old": text } )
    return rows, None


def normalised( text ):
    """Return text with each run of whitespace collapsed to one space, for duplicate comparison."""
    return " ".join( text.split() )


def drop_duplicates( rows ):
    """
    Keep one row for each distinct docstring text.

    Requires:
        - rows is a list of pool rows with unique ids

    Ensures:
        - returns ( kept, duplicates ): kept holds the rows in their original order, one per
          whitespace-normalised text, the one with the smallest id
        - duplicates is a list of { kept, dropped } sorted by the kept id, dropped being the other ids
          of that text in id order; it is empty when every text is distinct
    """
    groups = {}
    for row in rows: groups.setdefault( normalised( row[ "old" ] ), [] ).append( row[ "id" ] )
    keep   = { min( group ) for group in groups.values() }
    dups   = sorted( ( { "kept": min( group ), "dropped": sorted( group )[ 1: ] } for group in groups.values() if len( group ) > 1 ), key=lambda d: d[ "kept" ] )
    return [ row for row in rows if row[ "id" ] in keep ], dups


def build_pool( repo, sha, include, exclude ):
    """
    Build the pool rows and the facts the manifest records.

    Requires:
        - sha names a commit in repo; include is a non-empty list of directory prefixes

    Ensures:
        - rows are sorted by file and then source order, so the same commit gives the same rows
        - rows hold one docstring text once: see drop_duplicates
        - facts holds source_sha (full), include, exclude, files_read, files_skipped ( file, reason ), docstring_text,
          rows_before_dedupe, rows, duplicate_rows_dropped and duplicates

    Raises:
        - ValueError when include is empty or the pool would have no rows
        - RuntimeError when git cannot resolve or read the commit
    """
    full    = resolve_commit( repo, sha )
    sources = list_sources( repo, full, include, exclude )
    blobs   = read_blobs( repo, [ oid for _, oid in sources ] )
    rows    = []
    skipped = []
    for path, oid in sources:
        got, reason = pool_rows( path, blobs[ oid ] )
        rows.extend( got )
        if reason: skipped.append( [ path, reason ] )
    if not rows: raise ValueError( f"no docstrings found at {full} under {include}: refusing to write an empty pool" )
    kept, dups = drop_duplicates( rows )
    facts = { "source_sha": full, "include": list( include ), "exclude": list( exclude ), "files_read": len( sources ),
              "files_skipped": skipped, "docstring_text": "inspect.cleandoc", "rows_before_dedupe": len( rows ), "rows": len( kept ),
              "duplicate_rows_dropped": len( rows ) - len( kept ), "duplicates": dups }
    return kept, facts


def builder_sha256():
    """Return the sha256 of this module's own file, which the manifest records."""
    with open( __file__, "rb" ) as f: return hashlib.sha256( f.read() ).hexdigest()


def write_pool( rows, facts, out ):
    """
    Write the pool and its manifest.

    Requires:
        - rows and facts come from build_pool; out is the pool path

    Ensures:
        - out holds the rows as the seeder writes them: sorted keys, one per line
        - out + ".manifest.json" holds facts plus builder_sha256 and pool_sha256 (of the bytes just written)
    """
    labelled_set_seeder.write_jsonl( out, rows )
    labelled_set_seeder.write_json( out + ".manifest.json", dict( facts, builder_sha256=builder_sha256(), pool_sha256=labelled_set_seeder.sha256_file( out ) ) )


def build_parser():
    """Return the command-line parser."""
    parser = argparse.ArgumentParser( description="Build the docstring pool the labelled-set seeder's plan step reads." )
    parser.add_argument( "--sha", required=True, help="the one source commit to read; recorded in full in the manifest" )
    parser.add_argument( "--include", action="append", required=True, help="directory prefix to read, repeatable" )
    parser.add_argument( "--exclude", action="append", default=[], help="directory prefix to leave out, repeatable" )
    parser.add_argument( "--out", required=True, help="where to write pool.jsonl; the manifest goes beside it" )
    parser.add_argument( "--repo", help="git working tree to read from; default is the project root" )
    return parser


def main( argv ):
    """Build one pool; returns 0, or 2 after printing why it refused."""
    args = build_parser().parse_args( argv )
    repo = args.repo if args.repo else cu.get_project_root()
    try:
        rows, facts = build_pool( repo, args.sha, args.include, args.exclude )
    except ( ValueError, RuntimeError ) as e:
        print( f"REFUSED: {e}", file=sys.stderr )
        return 2
    write_pool( rows, facts, args.out )
    print( f"pool: {facts[ 'rows' ]} docstrings from {facts[ 'files_read' ]} files at {facts[ 'source_sha' ]}; "
           f"{len( facts[ 'files_skipped' ] )} files skipped, {facts[ 'duplicate_rows_dropped' ]} duplicate docstrings dropped" )
    return 0


if __name__ == "__main__":  # pragma: no cover - thin process entry, main() is what the tests drive
    sys.exit( main( sys.argv[ 1: ] ) )
