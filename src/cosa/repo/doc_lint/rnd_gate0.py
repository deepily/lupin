"""
Gate 0 of the R&D triage: no doc that a live file cites may be called history.

For one R&D doc the gate searches every tracked file for three strings. They are the doc's
repo-relative path, its file name, and its file name without the extension. Each match is a fixed
string with no extension list. The census this descends from restored two docs. An extension list
had let it delete them. Both were named in `.css` and `.md` files outside the R&D tree.

A citer is "live" when it is not itself under an R&D root. The three match classes are kept apart.
A bare file name is cited loosely, and a stem without its extension more loosely still. The stem
class has a minimum length so a short stem such as `00-index` does not match everything. All three
block the history class, because a wrong "history" is the costly error here.

Two tracked files never count as citers. The R&D index lists every doc to prove compliance. The
ledger lists every doc because it is the ledger. This module and its test file also never count,
because they name docs as examples. None of them is a decision to keep.

The second half of the module applies the manager's ruling on the word "live". A citer holds a doc
out of history only when its category says so. `resolve` settles the classes over passes, because an
R&D citer holds a doc only while its own class is in force or new.
"""

import argparse
import json
import os
import subprocess
import sys

RND_ROOTS = ( "src/rnd/", "src/cosa/rnd/" )

MIN_STEM_LENGTH = 12

NON_CITING = frozenset( {
    "src/rnd/README.md",
    "src/docs/rnd-ledger.tsv",
    "src/cosa/repo/doc_lint/rnd_gate0.py",
    "src/tests/unit/test_doc_lint_rnd_gate0.py",
} )

ARCHIVE_PREFIXES = ( "history/", "todo-history/", "src/cosa/history/", "src/cosa/history.md" )

HOLDING_RND_CLASSES = frozenset( { "in force", "new" } )

INDEX_PATHS = ( "src/rnd/README.md", "src/cosa/rnd/README.md" )

RULING_NOTE = (
    "Which citers hold a doc out of history is a manager's ruling of 2026-10-09 on the plan's word "
    "'live'. A code, test, CLAUDE.md, src/docs, TODO.md or .claude citer holds. An R&D citer holds "
    "only while its own class is in force or new. History archives, session manifests and the "
    "two root index READMEs never hold; an initiative-folder README holds like any R&D citer. Rick may change it."
)

_KEYS    = ( "live_path_citers", "live_name_citers", "live_stem_citers",
             "rnd_path_citers", "rnd_name_citers", "rnd_stem_citers" )
_COLUMNS = ( "path", "blocks_history", "live_path_citers", "live_name_citers", "live_stem_citers", "rnd_citers" )


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
        - returns { doc: { live_path_citers, live_name_citers, live_stem_citers,
          rnd_path_citers, rnd_name_citers, rnd_stem_citers, blocks_history } }
        - a citer lands in the strongest class it matches: path, then name, then stem
        - a stem is searched only when it has MIN_STEM_LENGTH characters or more
        - a file never cites itself, and the NON_CITING files cite nothing
        - blocks_history is True exactly when a live file matches the doc in any class
        - every citer list is sorted

    Raises:
        - RuntimeError naming the git error when ls-files fails
    """
    corpus = _corpus( repo_root )
    docs   = rnd_population( repo_root ) if docs is None else list( docs )
    result = {}
    for doc in docs:
        base  = os.path.basename( doc )
        stem  = os.path.splitext( base )[ 0 ]
        name  = base.encode( "utf-8" )
        full  = doc.encode( "utf-8" )
        short = stem.encode( "utf-8" ) if len( stem ) >= MIN_STEM_LENGTH else None
        found = { key: [] for key in _KEYS }
        for path, blob in corpus.items():
            if path == doc or path in NON_CITING: continue
            if name in blob:    kind = "path" if full in blob else "name"
            elif short is not None and short in blob: kind = "stem"
            else: continue
            found[ ( "rnd_" if is_rnd( path ) else "live_" ) + kind + "_citers" ].append( path )
        entry = { key: sorted( found[ key ] ) for key in _KEYS }
        entry[ "blocks_history" ] = bool( entry[ "live_path_citers" ] or entry[ "live_name_citers" ] or entry[ "live_stem_citers" ] )
        result[ doc ] = entry
    return result


def citer_kind( path ):
    """
    Put one citing file in the category the ruling table gives it.

    Requires:
        - path is a posix repo-relative str

    Ensures:
        - returns "archive" for history/, todo-history/, src/cosa/history/, a history.md and a .claude-session.md
        - returns "index" for the two root indexes src/rnd/README.md and src/cosa/rnd/README.md
        - returns "rnd" for any other file under an R&D root, an initiative-folder README included
        - returns "live" for everything else: code, tests, CLAUDE.md, src/docs, TODO.md and .claude files

    Raises:
        - nothing
    """
    if path.startswith( ARCHIVE_PREFIXES ) or path == "history.md" or path.endswith( ".claude-session.md" ): return "archive"
    if is_rnd( path ): return "index" if path in INDEX_PATHS else "rnd"
    return "live"


def _all_citers( entry ):
    """
    Gather every citer of one gate0 entry, whatever its match class.

    Requires:
        - entry is one value of the gate0 mapping

    Ensures:
        - returns a sorted list without repeats

    Raises:
        - nothing
    """
    return sorted( { citer for key in _KEYS for citer in entry[ key ] } )


def _holds( citer, classes ):
    """
    Say whether one citer holds a doc out of history under the current classes.

    Requires:
        - classes is { path: class }; a path it lacks is unclassified

    Ensures:
        - a live citer holds, an archive or index citer does not
        - an R&D citer holds when its class is in force or new, and an unclassified one counts as new

    Raises:
        - nothing
    """
    kind = citer_kind( citer )
    if kind == "live": return True
    if kind == "rnd":  return classes.get( citer, "new" ) in HOLDING_RND_CLASSES
    return False


def resolve( gate, proposed ):
    """
    Settle the final class of each doc under the live-citer ruling.

    Requires:
        - gate is a gate0 mapping over the R&D population
        - proposed is { doc: "in force" | "superseded" | "history" }; a doc it lacks is unclassified

    Ensures:
        - returns { doc: { proposed, class, holding_citers, free_citers } }
        - an unclassified doc is class new
        - a doc proposed as history becomes new when any citer holds it
        - the passes repeat until no class moves, so a doc held only by an R&D doc that was itself just held is held too
        - a doc proposed as in force or superseded keeps that class
        - holding_citers and free_citers are sorted and split by the final classes

    Raises:
        - nothing
    """
    classes = { doc: proposed.get( doc, "new" ) for doc in gate }
    moved   = True
    while moved:
        moved = False
        for doc, entry in gate.items():
            if classes[ doc ] != "history": continue
            if any( _holds( citer, classes ) for citer in _all_citers( entry ) ):
                classes[ doc ] = "new"
                moved          = True
    result = {}
    for doc, entry in gate.items():
        citers = _all_citers( entry )
        result[ doc ] = {
            "proposed"       : proposed.get( doc, "new" ),
            "class"          : classes[ doc ],
            "holding_citers" : [ c for c in citers if _holds( c, classes ) ],
            "free_citers"    : [ c for c in citers if not _holds( c, classes ) ],
        }
    return result


def describe( entry ):
    """
    Say in one line how many citers hold a doc and how many do not, by category.

    Requires:
        - entry is one value of the resolve mapping

    Ensures:
        - returns "holds N (kind n, ...); passes M (kind m, ...)" with kinds in alphabetical order
        - the parenthesis is left out for a count of zero

    Raises:
        - nothing
    """
    parts = []
    for label, citers in ( ( "holds", entry[ "holding_citers" ] ), ( "passes", entry[ "free_citers" ] ) ):
        kinds = {}
        for citer in citers: kinds[ citer_kind( citer ) ] = kinds.get( citer_kind( citer ), 0 ) + 1
        text = f"{label} {len( citers )}"
        if kinds: text += " (" + ", ".join( f"{kind} {count}" for kind, count in sorted( kinds.items() ) ) + ")"
        parts.append( text )
    return "; ".join( parts )


def precedent_violations( final, names ):
    """
    List the census docs that came out of the resolution as history.

    Requires:
        - final is a resolve mapping
        - names is a list of repo-relative doc paths from the precedent census

    Ensures:
        - returns the sorted names whose final class is history
        - a name the mapping lacks is left out

    Raises:
        - nothing
    """
    return sorted( name for name in names if name in final and final[ name ][ "class" ] == "history" )


def _read_proposed( path ):
    """
    Read a two-column TSV of doc path and proposed class.

    Requires:
        - path names a UTF-8 file with one tab-separated pair per line

    Ensures:
        - returns { doc: class }; blank lines are skipped and extra columns are ignored

    Raises:
        - OSError when the file cannot be read
    """
    proposed = {}
    with open( path, encoding="utf-8" ) as handle:
        for line in handle:
            if not line.strip(): continue
            doc, cls = line.rstrip( "\n" ).split( "\t" )[ :2 ]
            proposed[ doc ] = cls
    return proposed


def main( argv=None ):
    """
    Print the Gate 0 verdict for the named docs, or for every R&D file.

    Requires:
        - argv is None or a list of CLI args: optional paths, --repo-root, --json, --proposed

    Ensures:
        - prints a TSV with the header path, blocks_history, live_path_citers, live_name_citers, live_stem_citers, rnd_citers
        - --json prints the full gate0 mapping instead
        - --proposed FILE prints path, proposed, class, holds, passes for every R&D doc after the ruling
        - returns 0

    Raises:
        - RuntimeError naming the git error when ls-files fails
    """
    parser = argparse.ArgumentParser( description="Gate 0: which R&D docs does a live tracked file cite?" )
    parser.add_argument( "paths", nargs="*", help="repo-relative R&D docs; default is every tracked file under the R&D roots" )
    parser.add_argument( "--repo-root", default=".", help="git working tree to read" )
    parser.add_argument( "--json", action="store_true", help="print the full result as JSON" )
    parser.add_argument( "--proposed", help="TSV of doc path and proposed class; prints the classes after the live-citer ruling" )
    args   = parser.parse_args( argv )
    result = gate0( args.repo_root, args.paths or None )
    if args.proposed:
        final = resolve( result, _read_proposed( args.proposed ) )
        print( "\t".join( [ "path", "proposed", "class", "holds", "passes" ] ) )
        for doc, entry in final.items():
            print( "\t".join( [ doc, entry[ "proposed" ], entry[ "class" ],
                               str( len( entry[ "holding_citers" ] ) ), str( len( entry[ "free_citers" ] ) ) ] ) )
        return 0
    if args.json:
        print( json.dumps( result, indent=2, sort_keys=True ) )
        return 0
    print( "\t".join( _COLUMNS ) )
    for doc, found in result.items():
        print( "\t".join( [ doc, "yes" if found[ "blocks_history" ] else "no",
                           str( len( found[ "live_path_citers" ] ) ), str( len( found[ "live_name_citers" ] ) ),
                           str( len( found[ "live_stem_citers" ] ) ),
                           str( len( found[ "rnd_path_citers" ] ) + len( found[ "rnd_name_citers" ] ) + len( found[ "rnd_stem_citers" ] ) ) ] ) )
    return 0


if __name__ == "__main__":  # pragma: no cover -- module entry point, main() is what the tests drive
    sys.exit( main() )
