"""
Dated census of the Lupin-specific assumptions in the code-health services.

Counts fixed-string needles over `git ls-files` of a tree, with `.venv`, `node_modules` and `site-packages` left out.
It prints a markdown table stamped with the time and the commit sha. Every needle maps to an INI key, a pin or a registry key, so no row is an orphan.
A positive control runs first: the searches must find the couplings already known, at their known lines, before any count is printed.

Usage:
    python -m cosa.repo.coupling_census [--root PATH]
"""
import argparse
import datetime
import sys

import cosa.utils.util as cu
from cosa.repo.doc_lint.cli import tracked_files
from cosa.repo.doc_lint.range_gate import git

EXCLUDED_PARTS  = ( ".venv", "node_modules", "site-packages" )
NON_CODE_PREFIX = ( "src/tests/", "src/docs/", "src/rnd/", "src/cosa/rnd/", "src/cosa/tests/", "history/", "todo-history/", "src/cosa/history/" )
KINDS           = ( "ini", "pin", "registry" )
FIRST_SHOWN     = 3

NEEDLES = (
    { "group": 1, "needle": "def is_lupin_tree",                "kind": "ini",      "maps_to": "external repo <name> index languages" },
    { "group": 1, "needle": "LUPIN_PY_PACKAGES",                "kind": "ini",      "maps_to": "external repo <name> index source dirs" },
    { "group": 1, "needle": "LUPIN_JS_DIRS",                    "kind": "ini",      "maps_to": "external repo <name> index source dirs" },
    { "group": 1, "needle": "TESTS_DIRS",                       "kind": "ini",      "maps_to": "external repo <name> index test dirs" },
    { "group": 1, "needle": "src/lupin_app/static/js",          "kind": "ini",      "maps_to": "external repo <name> index source dirs" },
    { "group": 1, "needle": "HELD_PREFIXES",                    "kind": "pin",      "maps_to": "doc-lint rule list (rule_lists.py, ruling b42eb0de)" },
    { "group": 1, "needle": "cosa|lupin_",                      "kind": "pin",      "maps_to": "reuse scope regex (reuse_tools.py), Lupin's package names" },
    { "group": 2, "needle": "DATA_RELATIVE",                    "kind": "ini",      "maps_to": "code health data subdir" },
    { "group": 3, "needle": "LUPIN_CONFIG_MGR_CLI_ARGS",        "kind": "pin",      "maps_to": "settings loader is Lupin's: the new keys live in lupin-app.ini" },
    { "group": 4, "needle": "/api/embeddings",                  "kind": "pin",      "maps_to": "LUPIN_APP_SERVER_URL: the server is Lupin's own, no key" },
    { "group": 4, "needle": "LUPIN_APP_SERVER_URL",             "kind": "pin",      "maps_to": "LUPIN_APP_SERVER_URL: the server is Lupin's own, no key" },
    { "group": 5, "needle": "JEV_MODEL",                        "kind": "pin",      "maps_to": "code pin: a new model is a recalibration" },
    { "group": 5, "needle": "MODEL_ID",                         "kind": "pin",      "maps_to": "code pin: a new model is a recalibration" },
    { "group": 6, "needle": "LUPIN_REUSE_REVIEW_DATA_ROOT",     "kind": "pin",      "maps_to": "reuse review data subdir keys (not touched, Q2)" },
    { "group": 6, "needle": "projects-data/lupin",              "kind": "pin",      "maps_to": "reuse review data subdir keys (not touched, Q2)" },
    { "group": 7, "needle": "PROJECT = \"lupin\"",               "kind": "registry", "maps_to": "registry repo key (section 6.2 Scheduler)" },
    { "group": 7, "needle": "\"sender_project\": \"lupin\"", "kind": "registry", "maps_to": "registry repo key (section 6.2 Scheduler)" },
    { "group": 7, "needle": "f\"[LUPIN]",                        "kind": "ini",      "maps_to": "external repo <name> filed title prefix" },
    { "group": 8, "needle": "= \"main\"",                      "kind": "pin",      "maps_to": "registry row --branch argument; glob and main fallback in code" },
    { "group": 8, "needle": "--ceiling",                        "kind": "ini",      "maps_to": "external repo <name> duplicate check ceiling" },
    { "group": 8, "needle": "epic:dupcheck-",                   "kind": "pin",      "maps_to": "registry fix_debt_key: the filed rows' correlation prefix" },
    { "group": 9, "needle": "TestSuiteJob",                     "kind": "pin",      "maps_to": "merge gates are Lupin's pyramid; Open sub-question 1" },
)

CONTROLS = (
    { "needle": "def is_lupin_tree", "path": "src/cosa/repo/symindex/spec.py",                 "line": 77 },
    { "needle": "DATA_RELATIVE",     "path": "src/cosa/repo/duplicate_check/proof/proof_cli.py", "line": 33 },
)


class ControlFailed( Exception ):
    """A known coupling was not found where it is known to be, so no count can be trusted."""


def validate_needles( needles ):
    """
    Check that every needle maps to something.

    Requires:
        - needles is an iterable of dicts with group, needle, kind and maps_to

    Ensures:
        - returns None when every needle has one of the three allowed kinds ( ini, pin or registry ), a non-blank maps_to, and no needle is listed twice with the same text and group

    Raises:
        - ValueError naming the first needle that breaks a rule
    """
    seen = set()
    for n in needles:
        if n[ "kind" ] not in KINDS: raise ValueError( f"needle {n[ 'needle' ]!r}: kind {n[ 'kind' ]!r} is not one of {KINDS}" )
        if not n[ "maps_to" ].strip(): raise ValueError( f"needle {n[ 'needle' ]!r}: maps_to is blank" )
        key = ( n[ "group" ], n[ "needle" ] )
        if key in seen: raise ValueError( f"needle {n[ 'needle' ]!r} is listed twice in group {n[ 'group' ]}" )
        seen.add( key )


def in_population( path ):
    """
    Say whether a tracked path belongs to the census population.

    Ensures:
        - returns False when any directory name in the path is one of EXCLUDED_PARTS
    """
    return not any( part in EXCLUDED_PARTS for part in path.split( "/" ) )


def is_code( path ):
    """
    Say whether a path is production code rather than a test, a document or a history file.

    Ensures:
        - returns False for a Markdown file, a `.backup-` copy and any path under NON_CODE_PREFIX
    """
    return not path.endswith( ".md" ) and ".backup-" not in path and not path.startswith( NON_CODE_PREFIX )


def scan( root, paths, needles ):
    """
    Search each file once for every needle, as fixed strings.

    Requires:
        - paths are repo-relative, under root; needles carry a needle text

    Ensures:
        - returns { hits, unreadable }: hits is a list of ( needle, path, line ) sorted by path, line, needle; unreadable counts files that are not UTF-8 text or cannot be opened
    """
    hits, unreadable = [], 0
    for path in paths:
        try:
            with open( f"{root}/{path}", encoding="utf-8" ) as handle: lines = handle.read().splitlines()
        except ( UnicodeDecodeError, OSError ):
            unreadable += 1
            continue
        for number, text in enumerate( lines, start=1 ):
            hits.extend( ( n[ "needle" ], path, number ) for n in needles if n[ "needle" ] in text )
    return { "hits": sorted( hits, key=lambda h: ( h[ 1 ], h[ 2 ], h[ 0 ] ) ), "unreadable": unreadable }


def check_controls( hits, controls ):
    """
    Prove the search can find what is already known.

    Requires:
        - hits are ( needle, path, line ) tuples sorted by path then line; controls carry needle, path and line

    Ensures:
        - returns None when, for every control, the first hit of its needle in its file is at its line

    Raises:
        - ControlFailed naming the control, and the line found or that none was found
    """
    for c in controls:
        found = [ h[ 2 ] for h in hits if h[ 0 ] == c[ "needle" ] and h[ 1 ] == c[ "path" ] ]
        if not found: raise ControlFailed( f"control {c[ 'needle' ]!r} found nothing in {c[ 'path' ]}; expected line {c[ 'line' ]}" )
        if found[ 0 ] != c[ "line" ]: raise ControlFailed( f"control {c[ 'needle' ]!r} first hit in {c[ 'path' ]} is line {found[ 0 ]}, expected {c[ 'line' ]}" )


def render( hits, needles, stats ):
    """
    Build the markdown census.

    Requires:
        - hits are ( needle, path, line ) tuples sorted by path then line
        - stats holds stamp, sha, tracked, population, scanned, unreadable and controls (the count of controls that passed)

    Ensures:
        - returns the stamp line, a table with one row per needle (group, needle, hits in code, files in code, first locations, mapping) and the population line
        - hits in tests, documents and history are counted in their own column, not in the code columns
    """
    rows = [ "| Group | Needle | Hits in code | Files in code | First locations | Maps to |", "|---|---|---|---|---|---|" ]
    for n in needles:
        mine = [ h for h in hits if h[ 0 ] == n[ "needle" ] ]
        code = [ h for h in mine if is_code( h[ 1 ] ) ]
        firsts = ", ".join( f"`{h[ 1 ]}:{h[ 2 ]}`" for h in code[ :FIRST_SHOWN ] ) or "none in code"
        rows.append( f"| {n[ 'group' ]} | `{n[ 'needle' ]}` | {len( code )} | {len( { h[ 1 ] for h in code } )} | {firsts} | {n[ 'kind' ]}: {n[ 'maps_to' ]} |" )
    head = f"Census taken {stats[ 'stamp' ]} at commit `{stats[ 'sha' ]}`."
    foot = ( f"Population: {stats[ 'tracked' ]} tracked files, {stats[ 'tracked' ] - stats[ 'population' ]} left out as `.venv`, `node_modules` or `site-packages`, "
             f"{stats[ 'population' ]} counted, {stats[ 'scanned' ]} read as UTF-8 text, {stats[ 'unreadable' ]} not readable as text. "
             f"Positive controls passed: {stats[ 'controls' ]} of {len( CONTROLS )}." )
    return "\n".join( [ head, "", *rows, "", foot ] )


def run( root, now, needles=NEEDLES, controls=CONTROLS ):
    """
    Take the census of one tree.

    Requires:
        - root is a directory inside a git working tree; now is an aware datetime

    Ensures:
        - returns the markdown from render, after the controls passed

    Raises:
        - ValueError from validate_needles; ControlFailed from check_controls; RuntimeError from git
    """
    validate_needles( needles )
    tracked = tracked_files( root, ( "", ), scoped=False )
    paths   = [ p for p in tracked if in_population( p ) ]
    found   = scan( root, paths, needles )
    check_controls( found[ "hits" ], controls )
    stats = { "stamp": now.isoformat( timespec="seconds" ), "sha": git( root, "rev-parse", "--short", "HEAD" ).strip(), "tracked": len( tracked ), "population": len( paths ),
              "scanned": len( paths ) - found[ "unreadable" ], "unreadable": found[ "unreadable" ], "controls": len( controls ) }
    return render( found[ "hits" ], needles, stats )


def main( argv=None ):
    """
    Print the census of a tree.

    Requires:
        - argv is a list of arguments or None for sys.argv

    Ensures:
        - prints the markdown and returns 0; prints the failure to stderr and returns 1 when a control fails or git cannot list the tree
    """
    parser = argparse.ArgumentParser( description="Dated census of Lupin-specific assumptions" )
    parser.add_argument( "--root", default=None, help="tree to census (default: the project root)" )
    args = parser.parse_args( argv )
    try:
        print( run( args.root if args.root is not None else cu.get_project_root(), datetime.datetime.now().astimezone() ) )
    except ( ControlFailed, RuntimeError ) as err:
        print( f"census refused: {err}", file=sys.stderr )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit( main() )
