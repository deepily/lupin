"""
Checks that each history-labelled dropped claim has its text kept at a destination.

A reviewer sorts the claims the checker called absent into H, J, M, L and U. A claim labelled H may leave the
docstring only if its text is kept elsewhere: in a Design: document, or in a commit body. This tool reads the sort
and the destinations and reports, for each H claim, whether its whole quote is there. No model is called.

Present means the claim's quote, normalized, matches the destination text, normalized. Normalizing folds case,
collapses runs of white space and line wraps, and drops Markdown backticks. The whole quote must match, as a run
that no letter, digit or underscore touches at either end. A fragment of the quote does not count.
"""

import argparse
import json
import os
import re
import subprocess
import sys

from .docstring_lint import extract_docstrings
from .links import design_path_findings
from .cli import tracked_files

LABELS = ( "H", "J", "M", "L", "U" )
HISTORY = "H"
RESULT_NAME = "history-destination.json"


def normalize( text ):
    """
    Fold a text to the form the match is made on.

    Requires:
        - text is a str

    Ensures:
        - returns the text lowercased, with backticks removed and every run of white space, newlines included, one space
        - the result has no leading or trailing space

    Raises:
        - nothing
    """
    return re.sub( r"\s+", " ", text.replace( "`", "" ).lower() ).strip()


def quote_found( quote, text ):
    """
    Say whether the whole quote is present in a text.

    Requires:
        - quote and text are str

    Ensures:
        - True only when the normalized quote appears whole in the normalized text
        - a quote that starts or ends on a letter, digit or underscore must not touch one there, so the beginning of a
          longer word or identifier is not found
        - an empty normalized quote is never found

    Raises:
        - nothing
    """
    wanted = normalize( quote )
    if not wanted: return False
    before = r"(?<!\w)" if wanted[ 0 ].isalnum() or wanted[ 0 ] == "_" else ""
    after  = r"(?!\w)" if wanted[ -1 ].isalnum() or wanted[ -1 ] == "_" else ""
    return re.search( before + re.escape( wanted ) + after, normalize( text ) ) is not None


def load_sort( path ):
    """
    Read a reviewer's sort file.

    Requires:
        - path names a JSON Lines file, one claim per line, with an integer n and a class

    Ensures:
        - returns the rows in file order, each a dict
        - blank lines are skipped

    Raises:
        - ValueError naming the line when a line is not JSON, lacks n or class, repeats an n, carries a class outside H, J, M, L, U,
          or has an id, old_quote or quote that is not a string
        - OSError when the file cannot be read
    """
    rows, seen = [], set()
    with open( path, encoding="utf-8" ) as handle: lines = handle.read().split( "\n" )
    for number, line in enumerate( lines, 1 ):
        if not line.strip(): continue
        try:
            row = json.loads( line )
        except json.JSONDecodeError as err:
            raise ValueError( f"{path} line {number} is not JSON: {err.msg}" ) from err
        if not isinstance( row, dict ) or not isinstance( row.get( "n" ), int ) or "class" not in row:
            raise ValueError( f"{path} line {number} needs an integer n and a class" )
        if row[ "class" ] not in LABELS: raise ValueError( f"{path} line {number}: class {row[ 'class' ]!r} is not one of {' '.join( LABELS )}" )
        for key in ( "id", "old_quote", "quote" ):
            if key in row and row[ key ] is not None and not isinstance( row[ key ], str ): raise ValueError( f"{path} line {number}: {key} must be a string" )
        if row[ "n" ] in seen: raise ValueError( f"{path} line {number}: n {row[ 'n' ]} appears twice" )
        seen.add( row[ "n" ] )
        rows.append( row )
    return rows


def load_worksheet( path ):
    """
    Read the worksheet that numbers the claims.

    Requires:
        - path names a JSON list of { n, id, quote } dicts, the quote being the claim's words in the old text

    Ensures:
        - returns { n: row }

    Raises:
        - ValueError when the file is not a list of dicts that each carry an integer n, or a row has an id or quote that is not a string
        - OSError when the file cannot be read
        - json.JSONDecodeError when the file is not JSON
    """
    with open( path, encoding="utf-8" ) as handle: rows = json.load( handle )
    if not isinstance( rows, list ) or not all( isinstance( r, dict ) and isinstance( r.get( "n" ), int ) for r in rows ):
        raise ValueError( f"{path} must hold a JSON list of dicts, each with an integer n" )
    for row in rows:
        for key in ( "id", "quote" ):
            if key in row and row[ key ] is not None and not isinstance( row[ key ], str ): raise ValueError( f"{path} claim n {row[ 'n' ]}: {key} must be a string" )
    return { r[ "n" ]: r for r in rows }


def read_destinations( root, designs, commits ):
    """
    Read every destination text.

    Requires:
        - root is a git working tree; designs are file paths, a relative one read from root; commits are revisions

    Ensures:
        - returns [ { label, text } ], design documents first, labels design:<path> and commit:<full sha>
        - a commit body is read with git log -1 --format=%B

    Raises:
        - OSError when a design file cannot be read
        - RuntimeError naming the git error when a commit does not resolve
    """
    found = []
    for path in designs:
        with open( os.path.join( root, path ), encoding="utf-8" ) as handle: found.append( { "label": f"design:{path}", "text": handle.read() } )
    for rev in commits:
        res = subprocess.run( [ "git", "-C", str( root ), "log", "-1", "--format=%H%n%B", rev ], capture_output=True, text=True, encoding="utf-8" )
        if res.returncode != 0: raise RuntimeError( f"git log {rev} failed: {res.stderr.strip()}" )
        sha, _, body = res.stdout.partition( "\n" )
        found.append( { "label": f"commit:{sha}", "text": body } )
    return found


def design_lines_check( root, package ):
    """
    Report the Design: lines in a package's docstrings whose target does not exist.

    Requires:
        - root is a git working tree; package is a repo-relative directory, or None

    Ensures:
        - returns { checked, dead }; with package None, checked is False and dead is empty
        - the docstrings are those of the package's own in-scope .py files, read from the working tree
        - dead lists path:line: message for each Design: path that does not exist, found by the linter's own rule

    Raises:
        - OSError when a package file cannot be read
        - SyntaxError when a package file does not parse
    """
    if package is None: return { "checked": False, "dead": [] }
    dead = []
    for path in sorted( p for p in tracked_files( root, ( ".py", ) ) if p.rpartition( "/" )[ 0 ] == package ):
        with open( f"{root}/{path}", encoding="utf-8" ) as handle: source = handle.read()
        for _, _, first_line, text in extract_docstrings( source ):
            dead += [ f"{f.path}:{f.line}: {f.message}" for f in design_path_findings( text, path, first_line, root ) ]
    return { "checked": True, "dead": dead }


def empty_result( sort_path, worksheet_path, message=None ):
    """
    Build a result with every key a normal run has.

    Requires:
        - sort_path and worksheet_path are the arguments as given; message is the refusal, or None

    Ensures:
        - returns a dict with zero counts, no rows, no destinations and pass False
        - refused holds the message, so a reader tells a refusal from a run that found nothing

    Raises:
        - nothing
    """
    return {
        "sort"           : sort_path,
        "worksheet"      : worksheet_path,
        "destinations"   : [],
        "labels"         : {},
        "history_claims" : 0,
        "found"          : 0,
        "missing"        : 0,
        "rows"           : [],
        "design_lines"   : { "checked": False, "dead": [] },
        "refused"        : message,
        "message"        : message or "",
        "pass"           : False
    }


def check_history( root, sort_path, worksheet_path, designs, commits, package=None ):
    """
    Check that every history-labelled claim has its quote at a destination.

    Requires:
        - root is a git working tree; sort_path and worksheet_path name the reviewer's sort and the claim worksheet
        - designs and commits are lists of destination paths and revisions; package is a directory or None

    Ensures:
        - returns the result dict: sort, worksheet, destinations, labels (count per class), history_claims, found, missing,
          rows (one per H claim: n, id, quote, found, where), design_lines, refused, message and pass
        - a row's quote is the worksheet's quote for its n; a sort row that carries id or old_quote overrides the worksheet
        - pass is True only when nothing was refused, every H claim is found, and no Design: line is dead
        - zero H claims is a pass whose message says history_claims: 0
        - every claim in the worksheet must be in the sort, or the run is refused naming the missing numbers
        - a refusal returns the empty result with the reason, never a partial one, and any exception becomes one

    Raises:
        - nothing
    """
    result = empty_result( sort_path, worksheet_path )
    try:
        sort      = load_sort( sort_path )
        worksheet = load_worksheet( worksheet_path )
        unsorted  = sorted( set( worksheet ) - { r[ "n" ] for r in sort } )
        if unsorted: raise ValueError( f"the sort lacks claims of {worksheet_path}: n {' '.join( str( n ) for n in unsorted )}" )
        history   = [ r for r in sort if r[ "class" ] == HISTORY ]
        rows      = []
        for row in history:
            sheet = worksheet.get( row[ "n" ] )
            quote = row.get( "old_quote" ) or ( sheet.get( "quote" ) if sheet is not None else None )
            claim_id = row.get( "id" ) or ( sheet.get( "id" ) if sheet is not None else None )
            if not quote or not normalize( quote ): raise ValueError( f"history claim n {row[ 'n' ]} has no quote in the sort row or in {worksheet_path}" )
            rows.append( { "n": row[ "n" ], "id": claim_id, "quote": quote } )
        if rows and not ( designs or commits ): raise ValueError( "there are history claims and no destination: give --design or --commit" )
        destinations = read_destinations( root, designs, commits )
        design_lines = design_lines_check( root, package )
    except Exception as err:
        return empty_result( sort_path, worksheet_path, f"{type( err ).__name__}: {err}" )
    for row in rows:
        row[ "where" ] = [ d[ "label" ] for d in destinations if quote_found( row[ "quote" ], d[ "text" ] ) ]
        row[ "found" ] = bool( row[ "where" ] )
    found = sum( 1 for r in rows if r[ "found" ] )
    result.update( {
        "destinations"   : [ d[ "label" ] for d in destinations ],
        "labels"         : { label: sum( 1 for r in sort if r[ "class" ] == label ) for label in LABELS },
        "history_claims" : len( rows ),
        "found"          : found,
        "missing"        : len( rows ) - found,
        "rows"           : rows,
        "design_lines"   : design_lines,
    } )
    result[ "pass" ] = result[ "missing" ] == 0 and not design_lines[ "dead" ]
    result[ "message" ] = "history_claims: 0, nothing to check" if not rows else f"{found} of {len( rows )} history claims found"
    return result


def main( argv=None, out=None ):
    """
    Command-line entry point.

    Requires:
        - argv is a list of arguments, or None for sys.argv[ 1: ]

    Ensures:
        - writes history-destination.json in --out, which it creates, and prints a summary and each missing claim
        - returns 0 only when the result passes, 1 when a history claim is missing or a Design: line is dead, 2 on a refusal
        - the result file is written on every outcome, with every key a normal run has

    Raises:
        - nothing
    """
    out    = out if out is not None else sys.stdout
    parser = argparse.ArgumentParser( description="Check that each history-labelled dropped claim has its text at a destination." )
    parser.add_argument( "--repo-root", default=".", help="git working tree" )
    parser.add_argument( "--sort", required=True, help="the reviewer's sort, JSON Lines of { n, class, note }" )
    parser.add_argument( "--worksheet", required=True, help="the claim worksheet, a JSON list of { n, id, quote }" )
    parser.add_argument( "--design", action="append", default=[], help="a Design: document; repeat for more" )
    parser.add_argument( "--commit", action="append", default=[], help="a commit whose body is a destination; repeat for more" )
    parser.add_argument( "--package", help="repo-relative package directory, to check its Design: lines too" )
    parser.add_argument( "--out", required=True, help="directory to create for history-destination.json" )
    args   = parser.parse_args( sys.argv[ 1: ] if argv is None else argv )
    result = check_history( args.repo_root, args.sort, args.worksheet, args.design, args.commit, args.package.rstrip( "/" ) if args.package else None )
    os.makedirs( args.out, exist_ok=True )
    with open( f"{args.out}/{RESULT_NAME}", "w", encoding="utf-8" ) as handle:
        json.dump( result, handle, indent=2 )
        handle.write( "\n" )
    if result[ "refused" ] is not None:
        out.write( f"REFUSED: {result[ 'refused' ]}\n" )
        return 2
    for row in result[ "rows" ]:
        if not row[ "found" ]: out.write( f"MISSING n {row[ 'n' ]} {row[ 'id' ]}: {row[ 'quote' ]}\n" )
    for line in result[ "design_lines" ][ "dead" ]: out.write( f"DEAD DESIGN {line}\n" )
    out.write( f"{'PASS' if result[ 'pass' ] else 'FAIL'} {result[ 'message' ]}\n" )
    return 0 if result[ "pass" ] else 1


if __name__ == "__main__":
    sys.exit( main() )
