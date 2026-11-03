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
import os
import pathlib
import shlex
import subprocess
import sys
import time

from cosa.repo.doc_lint import model_transport
from cosa.repo.duplicate_check import cluster, extract, pipeline
from cosa.repo.duplicate_check import config as cfg_mod
from cosa.repo.duplicate_check import errors as err
from cosa.repo.duplicate_check.proof import label_prep, proof_cli
from cosa.repo.symindex import librarian_tick as lt
from cosa.repo.symindex.candidates import vector_build
from lupin_mcp import duplicate_check_filing as filing
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
STAGE_JUDGING     = "judging"                                   # the stage named in a result file when the pool build, the embeddings or the judge failed
UNREADABLE        = "unreadable"
CRON_TAG          = "# duplicate-check-daily"
CRON_SCHEDULE     = "7 12 * * *"      # 12:07, 30 minutes after the 11:37 shadow audit drain
BOOT_DELAY        = 300               # seconds the host waits after a boot before the reboot line runs
LOG_NAME          = "daily.log"
LOCK_OWNER        = "duplicate-check-daily"
CARRIED           = ( "LUPIN_CONFIG_MGR_CLI_ARGS", "DEEPILY_DATA_DIR", "COSA_VOICE_MANAGERS__LUPIN" )     # names copied into the cron lines from the installer's environment


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


def findings_of( groups, fresh, pool, window, parts ):
    """
    Turn the duplicate clusters into one finding per new definition.

    Requires:
        - groups are the clusters of more than one definition; fresh and pool are the definitions of the run
        - parts may hold session_of, a function from a definition to the writing seat's session id or None
    Ensures:
        - returns { id, name, file, line, text, session_id, others, window } for each new definition in a cluster, others being the rest of its cluster
        - without session_of the session is None, so the finding is unresolved to a seat
    """
    by_id  = { d[ "id" ]: d for d in [ *fresh, *pool ] }
    new    = { d[ "id" ] for d in fresh }
    return [ { "id": i, "name": by_id[ i ][ "name" ], "file": by_id[ i ][ "file" ], "line": by_id[ i ][ "line" ], "text": by_id[ i ][ "text" ],
               "session_id": parts[ "session_of" ]( by_id[ i ] ) if "session_of" in parts else None, "window": window,
               "others": [ { "id": o, "name": by_id[ o ][ "name" ], "file": by_id[ o ][ "file" ] } for o in g if o != i ] }
             for g in groups for i in g if i in new ]


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
        - an exception while building the pool, embedding or judging writes that file with status failed, stage judging and the error, and last-success does not move
        - last-success.json advances to the last commit fully judged; definitions the cap left are carried to the next run
        - a filer that raises is caught: the result holds filing { error } and the run ends as if it had filed nothing
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
    count = Counting( parts[ "backend" ] )
    try:
        fresh = new_definitions( tree, root, window )
        pool  = pool_without_earlier_versions( tree, fresh[ "defs" ] )
        out   = { "verdicts": [], "unjudged": [], "dropped": { "count": 0, "ids": [] } }
        if fresh[ "defs" ]:
            ledger = proof_cli.proof_ledger( parts[ "data_dir" ], cli_path, parts[ "backend" ], FOLDER )
            wiring = { **proof_cli.base_wiring( folder / VECTORS_DIR, parts[ "structural" ]( tree, cfg ), parallel, parts[ "client" ] ), "backend": count, "ledger": ledger }
            out    = pipeline.judge_all( fresh[ "defs" ], [ *fresh[ "defs" ], *pool ], cfg, wiring, 0, max_calls=cap )
    except Exception as exc:               # the pool build, the embeddings or the judge failed: leave a record and change nothing else
        doc.update( status="failed", stage=STAGE_JUDGING, error=f"{type( exc ).__name__}: {exc}", judge_calls=count.calls, elapsed_seconds=round( clock() - started, 3 ) )
        write_json( folder / f"{stem}.json", doc )
        return doc
    finally:
        release( root, tree )
    ids    = [ d[ "id" ] for d in [ *fresh[ "defs" ], *pool ] if d[ "id" ] not in set( out[ "dropped" ][ "ids" ] ) ]
    groups = [ g for g in cluster.clusters( ids, cluster.join_pairs( out[ "verdicts" ] ) ) if len( g ) > 1 ]
    moved  = progress( fresh[ "defs" ], fresh[ "commit_of" ], out[ "unjudged" ], window )
    doc.update( status="carried" if moved[ "carried" ] else "ok", judged=len( fresh[ "defs" ] ) - len( moved[ "carried" ] ), judge_calls=count.calls,
                carried=moved[ "carried" ], advanced_to=moved[ "advanced_to" ], clusters=groups, unreadable=[ u for u in out[ "unjudged" ] if u[ "code" ] not in CARRIED_CODES ],
                elapsed_seconds=round( clock() - started, 3 ) )
    if "filer" in parts:
        try: doc[ "filing" ] = parts[ "filer" ]( findings_of( groups, fresh[ "defs" ], pool, doc[ "window" ], parts ), folder )
        except Exception as e: doc[ "filing" ] = { "error": f"{type( e ).__name__}: {e}" }     # a broken store client or config must not stop last-success, or the next run re-judges and re-spends the cap
    write_json( folder / LAST_SUCCESS, { "commit": moved[ "advanced_to" ], "at": now.isoformat() } )
    write_json( folder / f"{stem}.json", doc )
    return doc


def cron_lines( root, python, log_path, cap, cli_path, carried=None ):
    """
    Build the two cron lines of the daily check.

    Requires:
        - root is the main checkout path; python is the interpreter path; cap is a whole number of judge calls; cli_path is the Claude Code binary
        - carried maps environment names to values, copied into both lines and shell-quoted
    Ensures:
        - returns [ daily line, reboot line ], each ending with CRON_TAG
        - the daily line runs at CRON_SCHEDULE with trigger cron, the reboot line BOOT_DELAY seconds after a boot with trigger reboot
        - both run from root with LUPIN_ROOT and PYTHONPATH set, append to log_path, and carry the cap and the binary
    """
    extra = "".join( f"{name}={shlex.quote( value )} " for name, value in ( carried or {} ).items() )

    def run( trigger ):
        """Ensures: returns the shell command of one line, its trigger named."""
        return ( f"cd {root} && LUPIN_ROOT={root} PYTHONPATH={root}/src {extra}{python} -m lupin_mcp.duplicate_check_daily "
                 f"--cap {cap} --claude-cli-path {cli_path} --trigger {trigger} >> {log_path} 2>&1 {CRON_TAG}" )

    return [ lt.cron_lines_for( run( "cron" ), CRON_SCHEDULE, BOOT_DELAY )[ 0 ], lt.cron_lines_for( run( "reboot" ), CRON_SCHEDULE, BOOT_DELAY )[ 1 ] ]


def install_mode( args, environ, now, out, err, crontab_cmd ):
    """
    Print, install, remove or report the cron lines.

    Requires:
        - args holds the parsed flags; exactly one of print_install, install, uninstall or status is set; out and err take one line of text
    Ensures:
        - --print-install prints the two lines and changes nothing; --install and --uninstall go through the librarian's locked crontab editor with this job's tag and owner
        - --status says whether the lines are present
        - returns 0, or 1 with the reason on err when the install is refused or the crontab call fails
    """
    root    = args.root or environ.get( "LUPIN_ROOT" ) or str( pathlib.Path.cwd() )
    log_dir = f"{root}{proof_cli.DATA_RELATIVE}/{FOLDER[ 0 ]}"
    cmd     = crontab_cmd or [ environ.get( "DUPLICATE_CHECK_DAILY_CRONTAB", "crontab" ) ]
    try:
        if args.status:
            read = subprocess.run( [ *cmd, "-l" ], capture_output=True, text=True )
            out( lt.status_text( read.stdout if read.returncode == 0 else "", CRON_TAG ) )
            return 0
        if args.uninstall:
            lt.edit_crontab( [], environ, cmd, f"{log_dir}/crontab-backups", now, tag=CRON_TAG, owner=LOCK_OWNER )
            out( "uninstalled" )
            return 0
        lines = cron_lines( root, args.python, f"{log_dir}/{LOG_NAME}", args.cap, args.claude_cli_path, { n: environ[ n ] for n in CARRIED if environ.get( n ) } )
        if args.print_install:
            out( "\n".join( lines ) )
            return 0
        lt.edit_crontab( lines, environ, cmd, f"{log_dir}/crontab-backups", now, tag=CRON_TAG, owner=LOCK_OWNER )
        out( "installed: 2 lines" )
        return 0
    except ( lt.InstallRefused, RuntimeError ) as e:
        err( f"duplicate-check-daily: {e}" )
        return 1


def live_parts():
    """
    Build the parts a real run uses.

    Ensures:
        - returns the embedding client, the Claude Code backend, the staged structural source, verify_frozen over the live file, cli_version, the data root and the filer
        - the filer files the findings' rows over HTTP; it builds its store client, reads the roster and the configured manager only when it is called
        - writes nothing and makes no call
    """
    base = proof_cli.base_wiring( ".", lambda defs: [], 1, vector_build.EndpointClient() )
    return { "client": base[ "client" ], "backend": base[ "backend" ], "data_dir": base[ "data_dir" ], "version_fn": model_transport.cli_version,
             "verify": lambda: cfg_mod.verify_frozen( base[ "frozen_path" ], base[ "live" ] ),
             "structural": lambda tree, cfg: proof_cli.structural_source( tree, {}, cfg ), "filer": live_filer }


def live_filer( findings, folder ):
    """
    File the findings' rows in the live store.

    Requires:
        - the environment holds LUPIN_ROOT, the configuration manager's argument and the project's declared manager roster
    Ensures:
        - returns file_findings' answer, made with the HTTP store, the configured manager on duty and the roster
    """
    from cosa.rest.voice_persona_helpers import pick_declared_managers_from_env
    from cosa.config.configuration_manager import ConfigurationManager
    declared = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" ).get( "arbiter manager on duty", default="manager-on-duty" ) or "manager-on-duty"
    return filing.file_findings( findings, folder, filing.LiveStore(), declared, pick_declared_managers_from_env( filing.PROJECT ) )


def main( argv=None, parts=None, now=None, out=print, environ=None, err=None, crontab_cmd=None ):
    """
    Run the daily check from the command line.

    Requires:
        - argv holds --cap ( judge calls, no default, needed to run or to print or install the cron lines ) and --claude-cli-path, and optionally --root, --trigger ( default hand ), --branch and --parallel
        - one of --print-install, --install, --uninstall or --status, with --python, works on the cron lines instead of running
    Ensures:
        - prints the result document as JSON and returns 0, or 1 when a prerequisite failed
        - the cron modes never run the check
    """
    ap = argparse.ArgumentParser( description="Judge the day's new definitions for duplicates." )
    ap.add_argument( "--cap", type=int, default=None )
    ap.add_argument( "--claude-cli-path", default=None )
    ap.add_argument( "--root", default=None )
    ap.add_argument( "--trigger", default="hand", choices=TRIGGERS )
    ap.add_argument( "--branch", default=BRANCH )
    ap.add_argument( "--parallel", type=int, default=proof_cli.DEFAULT_PARALLEL )
    ap.add_argument( "--python", default=sys.executable )
    mode = ap.add_mutually_exclusive_group()
    for flag in ( "--install", "--uninstall", "--status", "--print-install" ): mode.add_argument( flag, action="store_true" )
    args = ap.parse_args( argv )
    cron = args.install or args.uninstall or args.status or args.print_install
    if args.cap is None and not ( args.uninstall or args.status ): ap.error( "--cap is required: the daily check has no default cap" )
    if cron: return install_mode( args, os.environ if environ is None else environ, now or datetime.datetime.now(), out, err or ( lambda line: print( line, file=sys.stderr ) ), crontab_cmd )
    model_transport.configure( args.claude_cli_path )
    root = args.root or git( ".", "rev-parse", "--show-toplevel" )
    with contextlib.redirect_stdout( sys.stderr ):
        doc = run( root, now or datetime.datetime.now().astimezone(), args.trigger, args.cap, args.claude_cli_path, parts or live_parts(), args.branch, args.parallel )
    out( json.dumps( doc, indent=2, sort_keys=True ) )
    return 1 if doc[ "status" ] == "failed" else 0


if __name__ == "__main__":  # pragma: no cover - the entry only calls main
    raise SystemExit( main() )
