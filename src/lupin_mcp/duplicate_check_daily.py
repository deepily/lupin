"""
The daily duplicate check: judge the new definitions of main against the rest of the tree.

The window runs from the last successful run to now. The pool and the new definitions come from a detached worktree
at the window's end commit. The pool leaves out every earlier version of a new definition. Judge calls are capped per run.
What the cap leaves is carried to the next run. It is the daily check of the third remediation plan.
"""
import argparse
import contextlib
import datetime
import json
import pathlib
import subprocess
import sys
import time

from cosa.repo.doc_lint import model_transport
from cosa.repo.duplicate_check import cluster, extract, pipeline
from cosa.repo.duplicate_check import config as cfg_mod
from cosa.repo.duplicate_check import errors as err
from cosa.repo.duplicate_check.proof import label_prep, proof_cli
from cosa.repo.symindex.candidates import vector_build
from lupin_mcp.reuse_needset import source_at

FOLDER            = ( "duplicate-check-daily", )
LAST_SUCCESS      = "last-success.json"
VECTORS_DIR       = "vectors"
WORKTREE_PREFIX   = "duplicate-check-daily-"
WINDOW_HOURS      = 24
BRANCH            = "main"
TRIGGERS          = ( "cron", "reboot", "hand" )
CARRIED_CODES     = ( err.JUDGE_CAP_REACHED, err.JUDGE_CALL_FAILED )
PREREQ_EMBEDDINGS = "embedding_endpoint"
PREREQ_BINARY     = "claude_binary"
PREREQ_FROZEN     = "frozen_config"
UNREADABLE        = "unreadable"


class Counting:
    """A judge backend that counts the calls made through it."""

    def __init__( self, backend ):
        self.backend, self.calls = backend, 0
        self.server_label        = backend.server_label

    async def complete( self, model, system_prompt, user_prompt ):
        """Ensures: counts the call, then returns what the real backend answers."""
        self.calls += 1
        return await self.backend.complete( model, system_prompt, user_prompt )


def git( root, *args ):
    """
    Run one git command in root.

    Ensures:
        - returns the stripped stdout

    Raises:
        - RuntimeError naming the command when git fails
    """
    out = label_prep._git( root, *args )
    if out is None: raise RuntimeError( f"git {' '.join( args )} failed in {root}" )
    return out


def read_last_success( folder ):
    """Ensures: returns the parsed last-success.json of the folder, or None when there is none."""
    path = pathlib.Path( folder ) / LAST_SUCCESS
    return json.loads( path.read_text( encoding="utf-8" ) ) if path.exists() else None


def window_of( root, last, now, branch=BRANCH, hours=WINDOW_HOURS ):
    """
    Choose the commits a run judges.

    Requires:
        - last is read_last_success's answer; now is a timezone-aware datetime
    Ensures:
        - returns { start, end, commits }: end is the tip of the branch, start the last good commit or, with none, the newest commit older than hours before now
        - with no commit that old, start is the first commit of the branch
        - commits are those after start up to end on the first-parent line, oldest first
    """
    end   = git( root, "rev-parse", branch )
    start = last[ "commit" ] if last is not None else git( root, "rev-list", "-1", f"--before={( now - datetime.timedelta( hours=hours ) ).isoformat()}", branch )
    if not start: start = git( root, "rev-list", "--max-parents=0", branch ).split()[ -1 ]
    listed = git( root, "rev-list", "--reverse", "--first-parent", f"{start}..{end}" )
    return { "start": start, "end": end, "commits": listed.split() if listed else [] }


def changed_files( root, window ):
    """Ensures: returns the sorted Python and script files added or changed in the window."""
    names = git( root, "diff", "--name-only", "--diff-filter=AM", window[ "start" ], window[ "end" ] ).split( "\n" )
    return sorted( n for n in names if n.endswith( extract.PY_SUFFIXES + extract.SCRIPT_SUFFIXES ) )


def new_definitions( tree, root, window ):
    """
    List the definitions the window added or changed, oldest commit first.

    Requires:
        - tree is a worktree at the window's end commit
    Ensures:
        - returns { defs, commit_of }: new-origin definitions of the changed files, in the order of the first-parent commit that last touched their file, then file and line
        - commit_of maps a definition id to that commit
        - a definition whose file, name and text the window's start already held is left out, so only a function that changed or is new is judged
    """
    files = changed_files( root, window )
    found = extract.extract_tree( tree, [ pathlib.Path( tree ) / f for f in files ], "new" )[ "definitions" ] if files else []
    held  = set()
    if files:
        old = source_at.ensure_worktree( root, window[ "start" ], pathlib.Path( tree ).parent / f"{pathlib.Path( tree ).name}-start" )
        try: held = { ( d[ "file" ], d[ "name" ], d[ "text" ] ) for d in extract.extract_tree( old, [ pathlib.Path( old ) / f for f in files if ( pathlib.Path( old ) / f ).exists() ], "new" )[ "definitions" ] }
        finally: release( root, old )
    rank  = { c: i for i, c in enumerate( window[ "commits" ] ) }
    touch = { f: git( root, "log", "-1", "--first-parent", "--format=%H", f"{window[ 'start' ]}..{window[ 'end' ]}", "--", f ) for f in files }
    fresh = [ d for d in found if ( d[ "file" ], d[ "name" ], d[ "text" ] ) not in held ]
    fresh.sort( key=lambda d: ( rank.get( touch[ d[ "file" ] ], len( rank ) ), d[ "file" ], d[ "line" ] ) )
    return { "defs": fresh, "commit_of": { d[ "id" ]: touch[ d[ "file" ] ] for d in fresh } }


def release( root, tree ):
    """Ensures: the detached worktree is unlocked and removed, and nothing is raised."""
    source_at.unlock( root, tree )
    subprocess.run( [ "git", "-C", str( root ), "worktree", "remove", "--force", str( tree ) ], capture_output=True, text=True )


def pool_without_earlier_versions( tree, fresh ):
    """
    Build the server pool of a tree without the earlier versions of the new definitions.

    Ensures:
        - returns the tree's server and client definitions, less every one whose file and name a new definition shares
        - so no new definition can be paired with its own earlier version
    """
    parts = label_prep.tree_definitions( tree )
    taken = { ( d[ "file" ], d[ "name" ] ) for d in fresh }
    return [ d for d in [ *parts[ "server_defs" ], *parts[ "client_defs" ] ] if ( d[ "file" ], d[ "name" ] ) not in taken ]


def progress( defs, commit_of, unjudged, window ):
    """
    Say how far the window was judged.

    Requires:
        - defs are in commit order; unjudged is judge_run's list
    Ensures:
        - returns { advanced_to, carried }: advanced_to is the last commit before the first one that has a carried definition, the window's start when that is the first commit or a commit the window does not list
        - a definition left unjudged by the cap or a failed call is carried; an unreadable reply was ledgered and is not carried
        - with nothing carried, advanced_to is the window's end
    """
    carried = sorted( u[ "id" ] for u in unjudged if u[ "code" ] in CARRIED_CODES )
    if not carried: return { "advanced_to": window[ "end" ], "carried": [] }
    rank    = { c: i for i, c in enumerate( window[ "commits" ] ) }
    first   = min( rank.get( commit_of[ i ], -1 ) for i in carried )
    return { "advanced_to": window[ "start" ] if first <= 0 else window[ "commits" ][ first - 1 ], "carried": carried }


def write_json( path, doc ):
    """Ensures: writes the document to the path, making the folder, and returns the path."""
    path = pathlib.Path( path )
    path.parent.mkdir( parents=True, exist_ok=True )
    path.write_text( json.dumps( doc, indent=2, sort_keys=True ), encoding="utf-8" )
    return path


def failed_prerequisite( client, cli_path, verify, version_fn ):
    """
    Check the three prerequisites in order.

    Ensures:
        - returns None when all hold, else { prerequisite, detail } for the first that does not: the embedding endpoint answers, the binary reports a version, the frozen configuration matches the live one
    """
    try: client.info()
    except Exception as e: return { "prerequisite": PREREQ_EMBEDDINGS, "detail": f"{type( e ).__name__}: {e}" }
    version = version_fn( cli_path )
    if cli_path is None or version in ( None, UNREADABLE ): return { "prerequisite": PREREQ_BINARY, "detail": f"the binary {cli_path!r} reports no version" }
    try: verify()
    except err.DuplicateCheckError as e: return { "prerequisite": PREREQ_FROZEN, "detail": f"{e.code}: {e.detail}" }
    return None


def run( root, now, trigger, cap, cli_path, parts, branch=BRANCH, parallel=proof_cli.DEFAULT_PARALLEL, clock=time.monotonic ):
    """
    Run the daily check once.

    Requires:
        - root is the main checkout; now is a timezone-aware datetime; trigger is cron, reboot or hand; cap is a whole number of judge calls, at least 0
        - parts holds client, backend, structural ( a function taking the tree and the frozen configuration and giving judge_all's structural_pairs ), verify, version_fn and data_dir
    Ensures:
        - writes <data_dir>/duplicate-check-daily/<date>-<time>-<trigger>.json: the verdicts' clusters, the window, the judge calls and elapsed_seconds
        - a failed prerequisite writes that file with status failed, the prerequisite named, and changes nothing else
        - last-success.json advances to the last commit fully judged; definitions the cap left are carried to the next run
        - the detached worktrees are removed whether the run ends or fails
        - returns the result document
    Raises:
        - ValueError for a trigger that is not cron, reboot or hand
    """
    if trigger not in TRIGGERS: raise ValueError( f"trigger must be one of {TRIGGERS}, got {trigger!r}" )
    started = clock()
    folder  = pathlib.Path( parts[ "data_dir" ] ).joinpath( *FOLDER )
    stem    = f"{now.date().isoformat()}-{now.strftime( '%H%M%S' )}-{trigger}"
    base    = { "date": now.date().isoformat(), "trigger": trigger, "cap": cap }
    miss    = failed_prerequisite( parts[ "client" ], cli_path, parts[ "verify" ], parts[ "version_fn" ] )
    if miss is not None:
        doc = { **base, "status": "failed", **miss, "judge_calls": 0, "elapsed_seconds": round( clock() - started, 3 ) }
        write_json( folder / f"{stem}.json", doc )
        return doc
    cfg    = parts[ "verify" ]()
    last   = read_last_success( folder )
    window = window_of( root, last, now, branch )
    doc    = { **base, "window": { "start": window[ "start" ], "end": window[ "end" ], "commits": len( window[ "commits" ] ) } }
    tree   = source_at.ensure_worktree( root, window[ "end" ], pathlib.Path( root ) / source_at.WORKTREES / f"{WORKTREE_PREFIX}{window[ 'end' ][ :9 ]}" )
    try:
        fresh = new_definitions( tree, root, window )
        pool  = pool_without_earlier_versions( tree, fresh[ "defs" ] )
        count = Counting( parts[ "backend" ] )
        out   = { "verdicts": [], "unjudged": [], "dropped": { "count": 0, "ids": [] } }
        if fresh[ "defs" ]:
            ledger = proof_cli.proof_ledger( parts[ "data_dir" ], cli_path, parts[ "backend" ], FOLDER )
            wiring = { **proof_cli.base_wiring( folder / VECTORS_DIR, parts[ "structural" ]( tree, cfg ), parallel, parts[ "client" ] ), "backend": count, "ledger": ledger }
            out    = pipeline.judge_all( fresh[ "defs" ], [ *fresh[ "defs" ], *pool ], cfg, wiring, 0, max_calls=cap )
    finally:
        release( root, tree )
    ids    = [ d[ "id" ] for d in [ *fresh[ "defs" ], *pool ] if d[ "id" ] not in set( out[ "dropped" ][ "ids" ] ) ]
    groups = [ g for g in cluster.clusters( ids, cluster.join_pairs( out[ "verdicts" ] ) ) if len( g ) > 1 ]
    moved  = progress( fresh[ "defs" ], fresh[ "commit_of" ], out[ "unjudged" ], window )
    doc.update( status="carried" if moved[ "carried" ] else "ok", judged=len( fresh[ "defs" ] ) - len( moved[ "carried" ] ), judge_calls=count.calls,
                carried=moved[ "carried" ], advanced_to=moved[ "advanced_to" ], clusters=groups, unreadable=[ u for u in out[ "unjudged" ] if u[ "code" ] not in CARRIED_CODES ],
                elapsed_seconds=round( clock() - started, 3 ) )
    write_json( folder / LAST_SUCCESS, { "commit": moved[ "advanced_to" ], "at": now.isoformat() } )
    write_json( folder / f"{stem}.json", doc )
    return doc


def live_parts():
    """
    Build the parts a real run uses.

    Ensures:
        - returns the embedding client, the Claude Code backend, the staged structural source, verify_frozen over the live file, cli_version and the data root
        - writes nothing and makes no call
    """
    base = proof_cli.base_wiring( ".", lambda defs: [], 1, vector_build.EndpointClient() )
    return { "client": base[ "client" ], "backend": base[ "backend" ], "data_dir": base[ "data_dir" ], "version_fn": model_transport.cli_version,
             "verify": lambda: cfg_mod.verify_frozen( base[ "frozen_path" ], base[ "live" ] ),
             "structural": lambda tree, cfg: proof_cli.structural_source( tree, {}, cfg ) }


def main( argv=None, parts=None, now=None, out=print ):
    """
    Run the daily check from the command line.

    Requires:
        - argv holds --cap ( judge calls, required, no default ), --claude-cli-path, and optionally --root, --trigger ( default hand ), --branch and --parallel
    Ensures:
        - prints the result document as JSON and returns 0, or 1 when a prerequisite failed
    """
    ap = argparse.ArgumentParser( description="Judge the day's new definitions for duplicates." )
    ap.add_argument( "--cap", type=int, required=True )
    ap.add_argument( "--claude-cli-path", default=None )
    ap.add_argument( "--root", default=None )
    ap.add_argument( "--trigger", default="hand", choices=TRIGGERS )
    ap.add_argument( "--branch", default=BRANCH )
    ap.add_argument( "--parallel", type=int, default=proof_cli.DEFAULT_PARALLEL )
    args = ap.parse_args( argv )
    model_transport.configure( args.claude_cli_path )
    root = args.root or git( ".", "rev-parse", "--show-toplevel" )
    with contextlib.redirect_stdout( sys.stderr ):
        doc = run( root, now or datetime.datetime.now().astimezone(), args.trigger, args.cap, args.claude_cli_path, parts or live_parts(), args.branch, args.parallel )
    out( json.dumps( doc, indent=2, sort_keys=True ) )
    return 1 if doc[ "status" ] == "failed" else 0


if __name__ == "__main__":  # pragma: no cover - the entry only calls main
    raise SystemExit( main() )
