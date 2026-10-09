"""
Gate 0 of the R&D triage: no doc that a live file cites may be called history.

For one R&D doc the gate searches every tracked file for the doc's repo-relative path and for its
file name. The match is a fixed string with no extension list. The census this descends from restored
two docs. An extension list had let it delete them. Both were named in `.css` and `.md` files
outside the R&D tree.

A citer is "live" when it is not itself under an R&D root. A path match and a name-only match are
kept apart. A bare file name such as `01-design-overview.md` is cited loosely, so it is reported
but weaker. Both block the history class, because a wrong "history" is the costly error here.

Three tracked files never count as citers. The R&D index lists every doc to prove compliance. The
ledger lists every doc because it is the ledger. The deletion census is a manifest of candidates.
None of them is a decision to keep.
"""

import argparse
import json
import os
import subprocess
import sys

RND_ROOTS = ( "src/rnd/", "src/cosa/rnd/" )

NON_CITING = frozenset( {
    "src/rnd/README.md",
    "src/docs/rnd-ledger.tsv",
    "src/docs/2026.09.22-pre-september-rnd-deletion-candidates.md",
} )

_COLUMNS = ( "path", "blocks_history", "live_path_citers", "live_name_citers", "rnd_citers" )


def is_rnd( path ):
    """
    Say whether a repo-relative path sits under an R&D root.

    Requires:
        - path is a posix repo-relative str

    Ensures:
        - True when the path starts with src/rnd/ or src/cosa/rnd/, otherwise False

    Raises:
        - nothing
    """
    return path.startswith( RND_ROOTS )


def _tracked( repo_root ):
    """
    List every git-tracked path of a working tree.

    Requires:
        - repo_root is a git working tree

    Ensures:
        - returns sorted repo-relative posix paths from git, never from a disk walk

    Raises:
        - RuntimeError naming the git error when ls-files fails
    """
    res = subprocess.run( [ "git", "-C", str( repo_root ), "ls-files", "-z", "--", ":/" ], capture_output=True, text=True, encoding="utf-8" )
    if res.returncode != 0: raise RuntimeError( f"git ls-files failed: {res.stderr.strip()}" )
    return sorted( p for p in res.stdout.split( "\0" ) if p )


def rnd_population( repo_root ):
    """
    List every tracked file under the two R&D roots, of any type.

    Requires:
        - repo_root is a git working tree

    Ensures:
        - returns sorted repo-relative posix paths, each under src/rnd/ or src/cosa/rnd/

    Raises:
        - RuntimeError naming the git error when ls-files fails
    """
    return [ p for p in _tracked( repo_root ) if is_rnd( p ) ]


def rnd_markdown( repo_root ):
    """
    List the tracked Markdown docs under the two R&D roots.

    Requires:
        - repo_root is a git working tree

    Ensures:
        - returns the .md members of rnd_population, sorted

    Raises:
        - RuntimeError naming the git error when ls-files fails
    """
    return [ p for p in rnd_population( repo_root ) if p.endswith( ".md" ) ]


def _corpus( repo_root ):
    """
    Read every tracked file's bytes, skipping the ones the work tree cannot give.

    Requires:
        - repo_root is a git working tree

    Ensures:
        - returns { path: bytes } for each tracked regular file that reads
        - a tracked path that is missing, a directory link or unreadable is left out

    Raises:
        - RuntimeError naming the git error when ls-files fails
    """
    corpus = {}
    for path in _tracked( repo_root ):
        try:
            with open( os.path.join( str( repo_root ), path ), "rb" ) as handle: corpus[ path ] = handle.read()
        except OSError:
            continue
    return corpus


def gate0( repo_root, docs=None ):
    """
    Run the citation search for R&D docs over every tracked file.

    Requires:
        - repo_root is a git working tree
        - docs is None, or a list of repo-relative posix paths

    Ensures:
        - docs=None means every tracked file under the R&D roots
        - returns { doc: { live_path_citers, live_name_citers, rnd_path_citers, rnd_name_citers, blocks_history } }
        - a file never cites itself, and the NON_CITING files cite nothing
        - blocks_history is True exactly when a live file names the doc by path or by file name
        - every citer list is sorted

    Raises:
        - RuntimeError naming the git error when ls-files fails
    """
    corpus = _corpus( repo_root )
    docs   = rnd_population( repo_root ) if docs is None else list( docs )
    result = {}
    for doc in docs:
        name      = os.path.basename( doc ).encode( "utf-8" )
        full      = doc.encode( "utf-8" )
        live_path = []
        live_name = []
        rnd_path  = []
        rnd_name  = []
        for path, blob in corpus.items():
            if path == doc or path in NON_CITING or name not in blob: continue
            by_path = full in blob
            if is_rnd( path ): ( rnd_path if by_path else rnd_name ).append( path )
            else:              ( live_path if by_path else live_name ).append( path )
        result[ doc ] = {
            "live_path_citers" : sorted( live_path ),
            "live_name_citers" : sorted( live_name ),
            "rnd_path_citers"  : sorted( rnd_path ),
            "rnd_name_citers"  : sorted( rnd_name ),
            "blocks_history"   : bool( live_path or live_name ),
        }
    return result


def main( argv=None ):
    """
    Print the Gate 0 verdict for the named docs, or for every R&D file.

    Requires:
        - argv is None or a list of CLI args: optional paths, --repo-root, --json

    Ensures:
        - prints a TSV with the header path, blocks_history, live_path_citers, live_name_citers, rnd_citers
        - --json prints the full gate0 mapping instead
        - returns 0

    Raises:
        - RuntimeError naming the git error when ls-files fails
    """
    parser = argparse.ArgumentParser( description="Gate 0: which R&D docs does a live tracked file cite?" )
    parser.add_argument( "paths", nargs="*", help="repo-relative R&D docs; default is every tracked file under the R&D roots" )
    parser.add_argument( "--repo-root", default=".", help="git working tree to read" )
    parser.add_argument( "--json", action="store_true", help="print the full result as JSON" )
    args   = parser.parse_args( argv )
    result = gate0( args.repo_root, args.paths or None )
    if args.json:
        print( json.dumps( result, indent=2, sort_keys=True ) )
        return 0
    print( "\t".join( _COLUMNS ) )
    for doc, found in result.items():
        print( "\t".join( [ doc, "yes" if found[ "blocks_history" ] else "no",
                           str( len( found[ "live_path_citers" ] ) ), str( len( found[ "live_name_citers" ] ) ),
                           str( len( found[ "rnd_path_citers" ] ) + len( found[ "rnd_name_citers" ] ) ) ] ) )
    return 0


if __name__ == "__main__":  # pragma: no cover -- module entry point, main() is what the tests drive
    sys.exit( main() )
