"""
The Dart pool builder: the Dart input of the labelled-set seeder's plan step.

A sibling of pool_builder, not a branch inside it: pool_builder's walk is `.py` files under declared
directory prefixes and its rows come from the ast module, while a Dart pool is a declared list of
files and its rows come from the doc-comment lexer. What the two share is imported from pool_builder
(git access, duplicate removal) and from dart_pairs (the lexer and the "Owner.member" naming); there
is no second lexer and no second naming rule.

It reads each listed file from git at ONE commit, never from the working tree, and writes one JSON
Lines row per doc-comment block in the shape the Python pool has: { id, file, symbol, old }. The text
is dart_pairs.block_text of the block, with the `///` markers already removed. The seeder reads the
pool without caring about language.

A block with no readable declaration under it is named "<unattached>" by dart_pairs. It documents
nothing the seeder could name, so it is left out and counted in the manifest, never silently dropped.
A block over a library, part, import or export line is kept as "<library>", the Dart counterpart of
a module docstring.

The manifest, <out>.manifest.json, records the full source sha, the file list, the sha256 of this
builder's own file, the sha256 of the pool, the counts, every file skipped and why, the unattached
blocks left out, and the duplicates dropped. It is separate so the pool stays exactly what the seeder reads.
"""

import argparse
import hashlib
import sys

from cosa.repo.doc_lint import dart_pairs, labelled_set_seeder, pool_builder

UNATTACHED = "<unattached>"


def read_file_list( path ):
    """
    Read a file list: one repo-relative path per line, blank lines ignored.

    Requires:
        - path names a readable UTF-8 text file

    Ensures:
        - returns the paths in the order given, each once
    """
    with open( path, encoding="utf-8" ) as f:
        return list( dict.fromkeys( line.strip() for line in f if line.strip() ) )


def list_blobs( repo, sha, files ):
    """
    Find the blob of each listed file at one commit.

    Requires:
        - sha is a full commit sha; files is a non-empty list of repo-relative paths ending in .dart

    Ensures:
        - returns ( path, blob oid ) pairs in the order of files

    Raises:
        - ValueError when files is empty, a path does not end in .dart, or a path is not a blob at that commit
        - RuntimeError when git cannot list the commit
    """
    if not files: raise ValueError( "give at least one file: the pool's population is declared, not defaulted" )
    wrong = [ f for f in files if not f.endswith( ".dart" ) ]
    if wrong: raise ValueError( f"not Dart files: {' '.join( wrong )}" )
    found = {}
    for entry in pool_builder.run_git( repo, [ "ls-tree", "-z", "--full-tree", sha, "--", *files ] ).decode( "utf-8" ).split( "\0" ):
        if not entry: continue
        meta, path = entry.split( "\t", 1 )
        kind, oid  = meta.split()[ 1: 3 ]
        if kind == "blob": found[ path ] = oid
    missing = [ f for f in files if f not in found ]
    if missing: raise ValueError( f"not a file at {sha}: {' '.join( missing )}" )
    return [ ( f, found[ f ] ) for f in files ]


def dart_rows( path, source ):
    """
    Return the pool rows of one Dart file, the unattached blocks left out, or the reason it was skipped.

    Requires:
        - source is the file's bytes

    Ensures:
        - returns ( rows, unattached, None ): one { id, file, symbol, old } per doc block that names a declaration or a library
          line, ids "<file>::<symbol>" with #2, #3 for a repeated name as dart_pairs gives them; unattached counts the blocks left out
        - a block that is empty after block_text is left out and not counted
        - returns ( [], 0, "encoding" ) for text that is not UTF-8
    """
    try:
        text = source.decode( "utf-8" )
    except UnicodeDecodeError:
        return [], 0, "encoding"
    rows, unattached = [], 0
    for symbol, _, block in dart_pairs.extract_blocks( text ):
        if not block.strip(): continue
        if symbol.startswith( UNATTACHED ):
            unattached += 1
            continue
        rows.append( { "id": f"{path}::{symbol}", "file": path, "symbol": symbol, "old": block } )
    return rows, unattached, None


def build_dart_pool( repo, sha, files ):
    """
    Build the pool rows and the facts the manifest records.

    Requires:
        - sha names a commit in repo; files is a non-empty list of repo-relative .dart paths

    Ensures:
        - rows are in file-list order and source order within a file, one per distinct doc text (pool_builder.drop_duplicates)
        - facts holds language, source_sha (full), files, files_read, files_skipped ( file, reason ), unattached_dropped,
          docstring_text, rows_before_dedupe, rows, duplicate_rows_dropped and duplicates

    Raises:
        - ValueError when the list is bad (see list_blobs) or the pool would have no rows
        - RuntimeError when git cannot resolve or read the commit
    """
    full    = pool_builder.resolve_commit( repo, sha )
    sources = list_blobs( repo, full, files )
    blobs   = pool_builder.read_blobs( repo, [ oid for _, oid in sources ] )
    rows, skipped, unattached = [], [], 0
    for path, oid in sources:
        got, left_out, reason = dart_rows( path, blobs[ oid ] )
        rows.extend( got )
        unattached += left_out
        if reason: skipped.append( [ path, reason ] )
    if not rows: raise ValueError( f"no doc comments found at {full} in {len( files )} files: refusing to write an empty pool" )
    kept, dups = pool_builder.drop_duplicates( rows )
    facts = { "language": "dart", "source_sha": full, "files": list( files ), "files_read": len( sources ), "files_skipped": skipped,
              "unattached_dropped": unattached, "docstring_text": "dart_pairs.block_text of the doc block, markers removed",
              "rows_before_dedupe": len( rows ), "rows": len( kept ), "duplicate_rows_dropped": len( rows ) - len( kept ), "duplicates": dups }
    return kept, facts


def builder_sha256():
    """Return the sha256 of this module's own file, which the manifest records."""
    with open( __file__, "rb" ) as f: return hashlib.sha256( f.read() ).hexdigest()


def write_pool( rows, facts, out ):
    """
    Write the pool and its manifest.

    Requires:
        - rows and facts come from build_dart_pool; out is the pool path

    Ensures:
        - out holds the rows as the seeder writes them: sorted keys, one per line
        - out + ".manifest.json" holds facts plus builder_sha256 and pool_sha256 (of the bytes just written)
    """
    labelled_set_seeder.write_jsonl( out, rows )
    labelled_set_seeder.write_json( out + ".manifest.json", dict( facts, builder_sha256=builder_sha256(), pool_sha256=labelled_set_seeder.sha256_file( out ) ) )


def build_parser():
    """Return the command-line parser."""
    parser = argparse.ArgumentParser( description="Build the Dart doc-comment pool the labelled-set seeder's plan step reads." )
    parser.add_argument( "--repo", required=True, help="git working tree to read from; only read-only git commands are run in it" )
    parser.add_argument( "--sha", required=True, help="the one source commit to read; recorded in full in the manifest" )
    parser.add_argument( "--files-from", required=True, help="text file with one repo-relative .dart path per line" )
    parser.add_argument( "--out", required=True, help="where to write pool.jsonl; the manifest goes beside it" )
    return parser


def main( argv ):
    """Build one Dart pool; returns 0, or 2 after printing why it refused."""
    args = build_parser().parse_args( argv )
    try:
        rows, facts = build_dart_pool( args.repo, args.sha, read_file_list( args.files_from ) )
    except ( ValueError, RuntimeError, OSError ) as e:
        print( f"REFUSED: {e}", file=sys.stderr )
        return 2
    write_pool( rows, facts, args.out )
    print( f"pool: {facts[ 'rows' ]} doc blocks from {facts[ 'files_read' ]} files at {facts[ 'source_sha' ]}; {len( facts[ 'files_skipped' ] )} files skipped, "
           f"{facts[ 'unattached_dropped' ]} unattached blocks left out, {facts[ 'duplicate_rows_dropped' ]} duplicates dropped" )
    return 0


if __name__ == "__main__":  # pragma: no cover - thin process entry, main() is what the tests drive
    sys.exit( main( sys.argv[ 1: ] ) )
