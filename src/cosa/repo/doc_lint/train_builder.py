"""
Picks the approved packages that go in one day's merge train of the docs-rewrite sweep.

A package may go only when its `docs sweep: <package>` store row carries an approval. That is an amendment with
one `docs-sweep-approval:` line holding the checks directory, the commits and the verdict. The approver must not
be the author. The verdict must be pass, the checks directory must be durable and hold passing results, and every
commit must exist. The tool reads the store, writes train.json and merges nothing.
"""

import argparse
import json
import os
import re
import sys
import unicodedata

from .docs_only_diff import _git
from .sweep_packages import sweep

CORRELATION_KEY   = "epic:v022-docs-and-reuse"
TITLE_PREFIX      = "docs sweep: "
APPROVAL_PREFIX   = "docs-sweep-approval:"
DEFAULT_DATA_ROOT = "/mnt/DATA01/include/www.deepily.ai/projects-data/lupin"
DEFAULT_SIZE      = 11
TEMP_ROOTS        = ( "/tmp", "/var/tmp", "/dev/shm" )
CHECK_FILES       = ( "result.json", "history-destination.json" )
HEADER_REGEX      = re.compile( r"^\[(amendment|post-terminal addendum) · (.+?) · (\S+?)(?: · [^\]]*)?\]$", re.MULTILINE )
ACTOR_REGEX       = re.compile( r"^(.*?)\s+[0-9a-f]{8}$" )


def store_rows():
    """
    Read the sweep claim rows from the task store, with no MCP layer.

    Requires:
        - the store database is reachable through cosa.rest.db.database.get_db

    Ensures:
        - returns [ { id, title, owner_persona, status, body } ] for every lupin row under the sweep correlation key, terminal rows included
        - the query is scoped by project and correlation key, so the store's unscoped-query guard is never reached

    Raises:
        - whatever the store raises when it cannot be reached
    """
    from cosa.rest.db.database import get_db
    from cosa.rest.db.repositories.task_repository import TaskRepository
    with get_db() as session:
        items = TaskRepository( session ).query_tasks( project="lupin", correlation_key=CORRELATION_KEY, include_terminal=True, limit=1000 )
        return [ { "id": str( i.id ), "title": i.title, "owner_persona": i.owner_persona, "status": i.status, "body": i.body } for i in items ]


def persona_of( actor ):
    """
    Reduce an amendment actor, persona plus session id, to a comparable persona name.

    Requires:
        - actor is a str holding a persona name, optionally followed by an 8-hex session id

    Ensures:
        - returns the persona lowercased, accents removed, with only letters and digits kept
        - a trailing 8-hex session id is dropped

    Raises:
        - nothing
    """
    match = ACTOR_REGEX.match( actor.strip() )
    name  = match.group( 1 ) if match else actor
    return re.sub( r"[^a-z0-9]", "", unicodedata.normalize( "NFKD", name ).encode( "ascii", "ignore" ).decode().lower() )


def amendments_of( body ):
    """
    Split a row body into its amendment blocks.

    Requires:
        - body is a str, or None

    Ensures:
        - returns [ { kind, actor, ts, note } ] in body order, for each `[amendment · actor · utc]` or `[post-terminal addendum · ...]` block
        - the note runs to the next block header or the end of the body
        - a body with no block gives an empty list

    Raises:
        - nothing
    """
    body    = body or ""
    headers = list( HEADER_REGEX.finditer( body ) )
    return [ { "kind": h.group( 1 ), "actor": h.group( 2 ), "ts": h.group( 3 ), "note": body[ h.end() : headers[ i + 1 ].start() if i + 1 < len( headers ) else len( body ) ].strip() } for i, h in enumerate( headers ) ]


def approval_of( body ):
    """
    Find the latest approval line in a row body.

    Requires:
        - body is a str, or None

    Ensures:
        - returns ( actor, approval ) for the last amendment that holds a docs-sweep-approval line, approval being the parsed JSON
        - returns ( None, None ) when no amendment holds one

    Raises:
        - ValueError when the latest approval line is not a JSON object
    """
    found = ( None, None )
    for block in amendments_of( body ):
        for line in block[ "note" ].split( "\n" ):
            if not line.startswith( APPROVAL_PREFIX ): continue
            try:
                parsed = json.loads( line[ len( APPROVAL_PREFIX ) : ] )
            except json.JSONDecodeError as err:
                raise ValueError( f"the approval line is not JSON: {err.msg}" ) from err
            if not isinstance( parsed, dict ): raise ValueError( "the approval line is not a JSON object" )
            found = ( block[ "actor" ], parsed )
    return found


def checks_problem( checks, data_root ):
    """
    Say what is wrong with an approval's checks directory, or None.

    Requires:
        - checks is the path the approval names; data_root is the durable root it must sit under

    Ensures:
        - returns a reason when the path is under a temp directory, is not under data_root, is not a directory,
          or lacks result.json or history-destination.json with pass true; otherwise None
        - links are resolved first, so a link into a temp directory does not pass

    Raises:
        - nothing
    """
    real = os.path.realpath( checks )
    root = os.path.realpath( data_root )
    if any( real == t or real.startswith( t + "/" ) for t in TEMP_ROOTS ): return f"checks directory {checks} is under a temp directory"
    if not ( real == root or real.startswith( root + "/" ) ): return f"checks directory {checks} is not under {data_root}"
    if not os.path.isdir( real ): return f"checks directory {checks} does not exist"
    for name in CHECK_FILES:
        try:
            with open( f"{real}/{name}", encoding="utf-8" ) as handle: content = json.load( handle )
        except ( OSError, ValueError ) as err:
            return f"{name} in {checks} cannot be read: {type( err ).__name__}"
        if not isinstance( content, dict ) or content.get( "pass" ) is not True: return f"{name} in {checks} does not say pass"
    return None


def judge_package( row, root, data_root ):
    """
    Decide whether one claim row's package may go in the train.

    Requires:
        - row is { id, owner_persona, body, ... }; root is a git working tree

    Ensures:
        - returns ( entry, None ) for an approved package, entry being { package row id, approver, checks, commits }, commits full shas
        - returns ( None, reason ) when there is no approval, the approval line is malformed, the approver is the row's owner, the
          verdict is not pass, the checks directory is not durable or does not hold passing results, or a commit does not exist

    Raises:
        - nothing
    """
    try:
        actor, approval = approval_of( row[ "body" ] )
    except ValueError as err:
        return None, str( err )
    if approval is None: return None, "no approval amendment"
    checks, commits, verdict = approval.get( "checks" ), approval.get( "commits" ), approval.get( "verdict" )
    if not isinstance( checks, str ) or not isinstance( verdict, str ) or not isinstance( commits, list ) or not commits or not all( isinstance( c, str ) for c in commits ):
        return None, "the approval line needs checks (a path), commits (a non-empty list) and verdict"
    if persona_of( actor ) == persona_of( row[ "owner_persona" ] or "" ): return None, f"approved by its author ({actor})"
    if verdict.strip().lower() != "pass": return None, f"verdict is {verdict!r}, not pass"
    problem = checks_problem( checks, data_root )
    if problem is not None: return None, problem
    full = []
    for sha in commits:
        try:
            full.append( _git( root, "rev-parse", "--verify", f"{sha}^{{commit}}" ).strip() )
        except RuntimeError:
            return None, f"commit {sha} does not exist"
    return { "row_id": row[ "id" ], "approver": actor, "checks": checks, "commits": full }, None


def build_train( root, rows, order, size, data_root ):
    """
    Build one train from the claim rows.

    Requires:
        - rows come from store_rows; order lists package directories in sweep order; size is at least 1

    Ensures:
        - returns { head, size, packages, commits, bisect_order, deferred, refused, not_claimed }
        - packages are the approved ones in sweep order, cut at size; deferred names the approved ones past the cut
        - commits are each package's commits in package order, without repeats; bisect_order is the package order
        - a package with two claim rows is refused, not guessed; a package with no claim row is only counted in not_claimed
        - a refused package never stops the others

    Raises:
        - RuntimeError from git when HEAD cannot be read
    """
    claims = {}
    for row in rows:
        if row[ "title" ].startswith( TITLE_PREFIX ): claims.setdefault( row[ "title" ][ len( TITLE_PREFIX ) : ], [] ).append( row )
    approved, refused, not_claimed = [], [], 0
    for package in order:
        if package not in claims:
            not_claimed += 1
            continue
        if len( claims[ package ] ) > 1:
            refused.append( { "package": package, "reason": f"{len( claims[ package ] )} claim rows for this package" } )
            continue
        entry, reason = judge_package( claims[ package ][ 0 ], root, data_root )
        if entry is None: refused.append( { "package": package, "reason": reason } )
        else: approved.append( { "package": package, **entry } )
    packages = approved[ : size ]
    commits  = []
    for entry in packages: commits += [ c for c in entry[ "commits" ] if c not in commits ]
    return {
        "head"         : _git( root, "rev-parse", "HEAD" ).strip(),
        "size"         : size,
        "packages"     : packages,
        "commits"      : commits,
        "bisect_order" : [ e[ "package" ] for e in packages ],
        "deferred"     : [ e[ "package" ] for e in approved[ size : ] ],
        "refused"      : refused,
        "not_claimed"  : not_claimed
    }


def main( argv=None, out=None ):
    """
    Command-line entry point.

    Requires:
        - argv is a list of arguments, or None for sys.argv[ 1: ]

    Ensures:
        - writes train.json in --out, which it creates, and prints one line per refused package and a summary
        - returns 0 when the train holds at least one package, 1 when it holds none, 2 when the run could not start
        - on a run that could not start, train.json holds every key with an empty train and refused_run naming the cause
        - rows come from the store unless --rows-json names a file; the order comes from a live sweep unless --sweep-json names one

    Raises:
        - nothing
    """
    out    = out if out is not None else sys.stdout
    parser = argparse.ArgumentParser( description="Build one merge train from the approved sweep packages." )
    parser.add_argument( "--repo-root", default=".", help="git working tree" )
    parser.add_argument( "--out", required=True, help="directory to create for train.json" )
    parser.add_argument( "--size", type=int, default=DEFAULT_SIZE, help=f"packages in one train (default {DEFAULT_SIZE})" )
    parser.add_argument( "--data-root", default=DEFAULT_DATA_ROOT, help="the durable root every checks directory must sit under" )
    parser.add_argument( "--sweep-json", help="a sweep_packages --json output that fixes the order" )
    parser.add_argument( "--rows-json", help="a JSON list of claim rows to use instead of reading the store" )
    args   = parser.parse_args( sys.argv[ 1: ] if argv is None else argv )
    empty  = { "head": None, "size": args.size, "packages": [], "commits": [], "bisect_order": [], "deferred": [], "refused": [], "not_claimed": 0, "refused_run": None }
    try:
        if args.size < 1: raise ValueError( "--size must be at least 1" )
        if args.rows_json:
            with open( args.rows_json, encoding="utf-8" ) as handle: rows = json.load( handle )
        else:
            rows = store_rows()
        if args.sweep_json:
            with open( args.sweep_json, encoding="utf-8" ) as handle: order = [ p[ "package" ] for p in json.load( handle )[ "packages" ] ]
        else:
            order = [ p[ "package" ] for p in sweep( args.repo_root )[ "packages" ] ]
        train = { **build_train( args.repo_root, rows, order, args.size, args.data_root ), "refused_run": None }
    except ( ValueError, KeyError, TypeError, OSError, RuntimeError ) as err:
        train = { **empty, "refused_run": f"{type( err ).__name__}: {err}" }
    os.makedirs( args.out, exist_ok=True )
    with open( f"{args.out}/train.json", "w", encoding="utf-8" ) as handle:
        json.dump( train, handle, indent=2 )
        handle.write( "\n" )
    if train[ "refused_run" ] is not None:
        out.write( f"REFUSED: {train[ 'refused_run' ]}\n" )
        return 2
    for item in train[ "refused" ]: out.write( f"REFUSED {item[ 'package' ]}: {item[ 'reason' ]}\n" )
    out.write( f"train of {len( train[ 'packages' ] )} packages, {len( train[ 'commits' ] )} commits, {len( train[ 'refused' ] )} refused, {len( train[ 'deferred' ] )} deferred, at {train[ 'head' ]}\n" )
    return 0 if train[ "packages" ] else 1


if __name__ == "__main__":
    sys.exit( main() )
