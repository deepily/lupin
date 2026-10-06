"""
Picks the approved packages that go in one day's merge train of the docs-rewrite sweep.

A package may go only when its `docs sweep: <package>` store row carries an approval. That is an amendment with one
`docs-sweep-approval:` line. The line holds the checks directory, its file hashes, the commits and the verdict.

The row's audit trail must confirm the approval. The approver must be neither the writer, whom the manager names on
the row, nor its owner. The verdict must be pass, and the checks directory must be durable and hold passing results for
this package. Every commit must be a full sha that exists. The tool reads the store and writes train.json. It merges nothing.
"""

import argparse
import hashlib
import json
import os
import re
import sys
import unicodedata
from datetime import datetime, timedelta, timezone

from .docs_only_diff import _git
from .sweep_packages import sweep

CORRELATION_KEY   = "epic:v022-docs-and-reuse"
TITLE_REGEX       = re.compile( r"^(?:\[LUPIN\] )?docs sweep: (.+)$" )
APPROVAL_PREFIX   = "docs-sweep-approval:"
CLAIM_PREFIX      = "docs-sweep-claim:"
SKIPPED_STATUSES  = ( "dropped", "parked" )
EVENT_TRANSITIONS = ( "amended", "amended_post_terminal" )
EVENT_TOLERANCE   = timedelta( seconds=120 )
DEFAULT_DATA_ROOT = "/mnt/DATA01/include/www.deepily.ai/projects-data/lupin"
DEFAULT_SIZE      = 11
TEMP_ROOTS        = ( "/tmp", "/var/tmp", "/dev/shm" )
CHECK_FILES       = ( "result.json", "history-destination.json" )
HEADER_REGEX      = re.compile( r"^\[(amendment|post-terminal addendum) · (.+?) · (\S+?)(?: · [^\]]*)?\]$", re.MULTILINE )
ACTOR_REGEX       = re.compile( r"^(.*?)\s+[0-9a-f]{8}$" )
FULL_SHA_REGEX    = re.compile( r"^[0-9a-f]{40}$" )


def store_rows():
    """
    Read the sweep claim rows from the task store, with no MCP layer.

    Requires:
        - the store database is reachable through cosa.rest.db.database.get_db

    Ensures:
        - returns [ { id, title, owner_persona, status, body, events } ] for every lupin row under the sweep correlation key, terminal rows included
        - events holds each row's audit trail as { actor, transition, ts }, which is what an approval is checked against
        - the query is scoped by project and correlation key, so the store's unscoped-query guard is never reached

    Raises:
        - whatever the store raises when it cannot be reached
    """
    from cosa.rest.db.database import get_db
    from cosa.rest.db.repositories.task_repository import TaskRepository
    with get_db() as session:
        repo  = TaskRepository( session )
        items = repo.query_tasks( project="lupin", correlation_key=CORRELATION_KEY, include_terminal=True, limit=1000 )
        return [ {
            "id"            : str( i.id ),
            "title"         : i.title,
            "owner_persona" : i.owner_persona,
            "status"        : i.status,
            "body"          : i.body,
            "events"        : [ { "actor": e.actor, "transition": e.transition, "ts": e.ts.isoformat() } for e in repo.get_events( i.id ) ]
        } for i in items ]


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
        - returns ( actor, ts, approval ) for the last amendment that holds a docs-sweep-approval line, approval being the parsed JSON
        - returns ( None, None, None ) when no amendment holds one

    Raises:
        - ValueError when the latest approval line is not a JSON object
    """
    found = ( None, None, None )
    for block in amendments_of( body ):
        for line in block[ "note" ].split( "\n" ):
            if not line.startswith( APPROVAL_PREFIX ): continue
            try:
                parsed = json.loads( line[ len( APPROVAL_PREFIX ) : ] )
            except json.JSONDecodeError as err:
                raise ValueError( f"the approval line is not JSON: {err.msg}" ) from err
            if not isinstance( parsed, dict ): raise ValueError( "the approval line is not a JSON object" )
            found = ( block[ "actor" ], block[ "ts" ], parsed )
    return found


def claim_of( body ):
    """
    Read the claim line the manager wrote when the row was minted.

    Requires:
        - body is a str, or None

    Ensures:
        - returns the parsed { package, writer } of the first docs-sweep-claim line in the text before the first amendment
        - returns None when there is no such line
        - a line that is not a JSON object with string package and writer is a ValueError, never a guess

    Raises:
        - ValueError when the claim line is malformed
    """
    body    = body or ""
    headers = HEADER_REGEX.search( body )
    for line in ( body[ : headers.start() ] if headers else body ).split( "\n" ):
        if not line.startswith( CLAIM_PREFIX ): continue
        try:
            parsed = json.loads( line[ len( CLAIM_PREFIX ) : ] )
        except json.JSONDecodeError as err:
            raise ValueError( f"the claim line is not JSON: {err.msg}" ) from err
        if not isinstance( parsed, dict ) or not isinstance( parsed.get( "package" ), str ) or not isinstance( parsed.get( "writer" ), str ):
            raise ValueError( "the claim line needs a package and a writer, both strings" )
        return parsed
    return None


def event_agrees( events, actor, stamp ):
    """
    Say whether the audit trail holds the amendment a body stamp claims.

    Requires:
        - events is [ { actor, transition, ts } ]; actor and stamp are the stamp's persona and session id and its time

    Ensures:
        - True only when an amended event, or a post-terminal one, has that actor and a time within two minutes of the stamp
        - a stamp or event time that cannot be read, or is naive, counts as UTC when naive and as no match when unreadable

    Raises:
        - nothing
    """
    try:
        stamped = datetime.fromisoformat( stamp )
    except ValueError:
        return False
    stamped = stamped if stamped.tzinfo else stamped.replace( tzinfo=timezone.utc )
    for event in events:
        if event.get( "transition" ) not in EVENT_TRANSITIONS or event.get( "actor" ) != actor: continue
        try:
            when = datetime.fromisoformat( event[ "ts" ] )
        except ( ValueError, KeyError, TypeError ):
            continue
        when = when if when.tzinfo else when.replace( tzinfo=timezone.utc )
        if abs( when - stamped ) <= EVENT_TOLERANCE: return True
    return False


def checks_problem( checks, data_root, package, hashes ):
    """
    Say what is wrong with an approval's checks directory, or None.

    Requires:
        - checks is the path the approval names; data_root is the durable root it must sit under
        - package is the claim's package; hashes is the approval's { file name: sha256 hex }

    Ensures:
        - returns a reason when the path is under a temp directory, is not under data_root, is not a directory, or lacks
          result.json or history-destination.json with pass true
        - also a reason when result.json names another package, or a file's sha256 differs from the approval's
        - otherwise None; links are resolved first, so a link into a temp directory does not pass

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
            with open( f"{real}/{name}", "rb" ) as handle: raw = handle.read()
            content = json.loads( raw )
        except ( OSError, ValueError ) as err:
            return f"{name} in {checks} cannot be read: {type( err ).__name__}"
        if not isinstance( content, dict ) or content.get( "pass" ) is not True: return f"{name} in {checks} does not say pass"
        if name == "result.json" and content.get( "package" ) != package: return f"result.json in {checks} is for {content.get( 'package' )!r}, not {package!r}"
        if hashes.get( name ) != hashlib.sha256( raw ).hexdigest(): return f"{name} in {checks} has changed since it was approved"
    return None


def judge_package( row, package, root, data_root ):
    """
    Decide whether one claim row's package may go in the train.

    Requires:
        - row is { id, owner_persona, status, body, events }; package is the package its title names; root is a git working tree

    Ensures:
        - returns ( entry, None ) for an approved package, entry being { row_id, approver, checks, commits }, commits full shas
        - returns ( None, reason ) when the row is dropped or parked, has no claim line or one for another package, has no
          approval, has an approval whose stamp no amended event confirms, was approved by its writer or its owner, has a
          verdict that is not pass, has a checks directory that is not durable, whole, passing and for this package, or lists
          a commit that is not a full sha of an existing commit

    Raises:
        - nothing
    """
    if row[ "status" ] in SKIPPED_STATUSES: return None, f"the claim row is {row[ 'status' ]}"
    try:
        claim = claim_of( row[ "body" ] )
        actor, stamp, approval = approval_of( row[ "body" ] )
    except ValueError as err:
        return None, str( err )
    if claim is None: return None, "no docs-sweep-claim line naming the writer"
    if claim[ "package" ] != package: return None, f"the claim line names {claim[ 'package' ]!r}, not {package!r}"
    if approval is None: return None, "no approval amendment"
    if not event_agrees( row.get( "events" ) or [], actor, stamp ): return None, f"no amended event by {actor} confirms the approval stamp"
    checks, commits, verdict, hashes = approval.get( "checks" ), approval.get( "commits" ), approval.get( "verdict" ), approval.get( "sha256" )
    if not isinstance( checks, str ) or not isinstance( verdict, str ) or not isinstance( hashes, dict ) or not isinstance( commits, list ) or not commits or not all( isinstance( c, str ) for c in commits ):
        return None, "the approval line needs checks (a path), commits (a non-empty list), verdict and sha256 (a dict)"
    approver = persona_of( actor )
    if approver == persona_of( claim[ "writer" ] ): return None, f"approved by its writer ({actor})"
    if approver == persona_of( row[ "owner_persona" ] or "" ): return None, f"approved by its owner ({actor})"
    if verdict.strip().lower() != "pass": return None, f"verdict is {verdict!r}, not pass"
    problem = checks_problem( checks, data_root, package, hashes )
    if problem is not None: return None, problem
    full = []
    for sha in commits:
        if not FULL_SHA_REGEX.match( sha ): return None, f"commit {sha} is not a full 40-character sha"
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
        - a claim title is `docs sweep: <dir>` with an optional leading `[LUPIN] ` and nothing else before it
        - packages are the approved ones in sweep order, cut at size; deferred names the approved ones past the cut
        - commits are each package's commits in package order, without repeats; bisect_order is the package order
        - a package with two claim rows is refused, not guessed; a package with no claim row is only counted in not_claimed
        - a claim for a package that is not in the sweep order is refused by name, never dropped
        - a refused package never stops the others

    Raises:
        - RuntimeError from git when HEAD cannot be read
        - AttributeError or TypeError when a row has no usable title
    """
    claims = {}
    for row in rows:
        match = TITLE_REGEX.match( row[ "title" ] )
        if match: claims.setdefault( match.group( 1 ), [] ).append( row )
    approved, refused, not_claimed = [], [], 0
    for package in order:
        if package not in claims:
            not_claimed += 1
            continue
        if len( claims[ package ] ) > 1:
            refused.append( { "package": package, "reason": f"{len( claims[ package ] )} claim rows for this package" } )
            continue
        entry, reason = judge_package( claims[ package ][ 0 ], package, root, data_root )
        if entry is None: refused.append( { "package": package, "reason": reason } )
        else: approved.append( { "package": package, **entry } )
    refused += [ { "package": package, "reason": "a claim for a package that is not in the sweep list" } for package in sorted( claims ) if package not in order ]
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
    except Exception as err:
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
