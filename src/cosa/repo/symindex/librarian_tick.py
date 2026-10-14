"""
The daily wiki-librarian tick: lint the wiki, queue the findings, export the misses.

One run builds or reuses the symbol index and lints the wiki against it. It then brings the store's
wiki-librarian rows in step with the findings and exports the miss records. A run is due once per
local day, from 10:00 on. A host that was off at ten catches up on its first tick after boot.
The state file records the day of the last run that finished.

It reads no fleet pause flag. Whether a pause applies to this tick is an open question.
The absence is a named gap and not a decision.

Installing the cron lines goes through the shared crontab lock and nothing else. Without that
lock module the installer refuses and writes nothing.

Exit 0 means nothing was due, or the run finished and nothing is held.
Exit 1 means the run could not finish, or an install was refused.
Exit 2 means the run finished and some rows are held in the pending file.
"""
import argparse
import datetime
import importlib.util
import json
import os
import pathlib
import subprocess
import sys

from cosa.repo.symindex import build as build_mod
from cosa.repo.symindex.librarian_queue import CORRELATION_KEY, Librarian
from cosa.repo.symindex.wiki_lint import queue

CRON_TAG         = "# wiki-librarian-tick"
CRON_SCHEDULE    = "17 10 * * *"
FIRST_HOUR       = 10
ACTOR            = "wiki-librarian tick"
STATE_NAME       = "tick-state.json"
PENDING_NAME     = "pending.jsonl"
LOG_NAME         = "librarian.log"
DEFAULT_API_BASE = "http://localhost:7999"


class InstallRefused( RuntimeError ):
    """The installer would have had to write without the shared crontab lock."""


def data_dir( root=None ):
    """
    Name the folder that holds the pending file, the log and the state.

    Requires:
        - root is a repo root path, or None for the project root

    Ensures:
        - returns <fleet data root>/reuse-review/librarian
        - nothing is created
    """
    from lupin_cli.claude_code.hooks.lib.heartbeat_hold import fleet_data_root
    return os.path.join( str( fleet_data_root( root ) ), "reuse-review", "librarian" )


def due( now, state ):
    """
    Decide whether a run is due.

    Requires:
        - now is a datetime in local time
        - state is the dict read_state returned

    Ensures:
        - returns True when it is FIRST_HOUR or later and the last finished run was on another day
        - returns False before FIRST_HOUR, and False after a run that finished today
    """
    if now.hour < FIRST_HOUR: return False
    return state.get( "last_run_date" ) != now.date().isoformat()


def read_state( path ):
    """
    Read the state file.

    Ensures:
        - returns the dict in the file, or an empty dict when the file is absent or unreadable
    """
    try:
        with open( path, encoding="utf-8" ) as handle: state = json.load( handle )
    except ( OSError, ValueError ):
        return {}
    return state if isinstance( state, dict ) else {}


def write_state( path, state ):
    """
    Write the state file by temporary name and rename.

    Requires:
        - state is a JSON-serializable dict
    """
    os.makedirs( os.path.dirname( path ), exist_ok=True )
    temp = path + ".tmp"
    with open( temp, "w", encoding="utf-8" ) as handle: json.dump( state, handle, sort_keys=True )
    os.replace( temp, path )


def make_logger( path ):
    """
    Build a function that appends one stamped line to the librarian log.

    Ensures:
        - the folder is created on the first line
        - a line that cannot be written is dropped, never raised
    """
    def log( line ):
        stamp = datetime.datetime.now().astimezone().isoformat( timespec="seconds" )
        try:
            os.makedirs( os.path.dirname( path ), exist_ok=True )
            with open( path, "a", encoding="utf-8" ) as handle: handle.write( f"{stamp} {line}\n" )
        except OSError: pass
    return log


class LiveStore:
    """
    The store adapter the tick uses: the task-store HTTP client behind four calls.

    Requires:
        - settings is the dict load_task_store_settings returns
        - api_key is the outbound key string
        - client is the task_store_client module, or a stand-in with the same functions
    """

    def __init__( self, settings, api_key, client ):
        """Keep the three collaborators."""
        self.settings = settings
        self.api_key  = api_key
        self.client   = client

    def query( self, correlation_key ):
        """Return ( ok, status, body ) for the open rows under one correlation key."""
        return self.client.query_by_correlation_key( self.settings, self.api_key, correlation_key )

    def create( self, payload ):
        """Return ( ok, status, body ) for one create; the actor is stamped here."""
        return self.client.create_task( self.settings, self.api_key, { **payload, "created_by": ACTOR, "authority": "standing" } )

    def amend( self, item_id, note ):
        """Return ( ok, status, body ) for one append-only amendment."""
        return self.client.amend_task( self.settings, self.api_key, item_id, { "note": note, "actor": ACTOR, "authority": "standing" } )

    def close( self, item_id, reason ):
        """Return ( ok, status, body ) for a move to done with a reason."""
        return self.client.transition_task( self.settings, self.api_key, item_id, { "to_status": "done", "actor": ACTOR, "authority": "standing", "reason": reason } )


def notify_owner( persona, text, environ, post=None, api_key=None ):
    """
    Send one direct message to the persona that owns the librarian rows.

    Requires:
        - persona is a non-empty persona name
        - post is a callable ( base, key, path, payload ) returning ( status, text ), or None for the live one

    Ensures:
        - returns True when the server answered 201
        - never raises: a missing key or a failed post returns False
    """
    from cosa.utils import hook_link_tick as hlt
    post = post or hlt.post_json
    base = environ.get( "LUPIN_API_BASE", DEFAULT_API_BASE ).rstrip( "/" )
    try: key = ( api_key or hlt._api_key )()
    except Exception: return False
    status, _ = post( base, key, "/api/dm/send", { "sender_session_id": "wiki-librarian-tick", "sender_persona": "wiki librarian tick",
                                                    "sender_icon": "📚", "sender_project": "lupin", "recipient_persona": persona, "body": text } )
    return status == 201


def run_tick( root, wiki_dir, out_dir, librarian, export_fn, misses_path, state_path, now, force=False, log=print ):
    """
    Run one tick.

    Requires:
        - librarian is a Librarian
        - export_fn is a callable ( rows, path ) returning the number of lines written
        - now is a datetime in local time

    Ensures:
        - returns ( exit_code, summary dict )
        - nothing is done and 0 is returned when the run is not due and force is False
        - the state file records today's date only when the sync finished
        - a store that could not be read returns 1 and leaves the state and pending file as they were
    """
    state = read_state( state_path )
    if not force and not due( now, state ): return 0, { "ran": False, "reason": "not due" }
    gen      = build_mod.ensure( root, out_dir )
    findings = queue( pathlib.Path( wiki_dir ), gen )
    try:
        counts = librarian.sync( findings )
        ok, status, body = librarian.store.query( CORRELATION_KEY )
    except RuntimeError as error:
        log( f"tick could not finish: {error}" )
        return 1, { "ran": False, "reason": str( error ) }
    if not ok:
        log( f"tick could not read rows to export: status {status}" )
        return 1, { "ran": False, "reason": f"export query failed: {status}" }
    exported = export_fn( body.get( "tasks", [] ), misses_path )
    write_state( state_path, { "last_run_date": now.date().isoformat(), "findings": len( findings ), **counts, "misses": exported } )
    summary = { "ran": True, "findings": len( findings ), "misses": exported, **counts }
    log( "tick finished: " + json.dumps( summary, sort_keys=True ) )
    return ( 2 if counts[ "pending" ] else 0 ), summary


def cron_lines( root, python, log_path ):
    """
    Build the two cron lines.

    Requires:
        - root is the main checkout path; python is the interpreter path

    Ensures:
        - returns [ daily line, reboot line ], each ending with CRON_TAG
        - the reboot line gives a slow start 120 seconds before the run
    """
    run = f"cd {root} && LUPIN_ROOT={root} PYTHONPATH={root}/src {python} -m cosa.repo.symindex.librarian_tick >> {log_path} 2>&1 {CRON_TAG}"
    return [ f"{CRON_SCHEDULE} {run}", f"@reboot sleep 120 && {run}" ]


def merge_lines( current, lines ):
    """
    Replace every tagged line of a crontab text with lines.

    Requires:
        - current is the crontab text; lines is the list from cron_lines or an empty list

    Ensures:
        - lines that do not carry CRON_TAG keep their text and order
        - the tagged lines end the text, once each
    """
    kept = [ line for line in current.splitlines() if not line.rstrip().endswith( CRON_TAG ) ]
    return "\n".join( kept + list( lines ) ) + "\n"


def load_crontab_lock( environ ):
    """
    Load the shared crontab lock context manager from the planning-is-prompting repo.

    Requires:
        - environ names PLANNING_IS_PROMPTING_ROOT

    Ensures:
        - returns the crontab_lock context manager function
        - raises InstallRefused when the variable is unset or the module file is absent
    """
    home = environ.get( "PLANNING_IS_PROMPTING_ROOT" )
    if not home: raise InstallRefused( "PLANNING_IS_PROMPTING_ROOT is not set, so the shared crontab lock cannot be found" )
    path = os.path.join( home, "workflow", "scripts", "crontab_lock.py" )
    if not os.path.isfile( path ): raise InstallRefused( f"{path} does not exist, so the shared crontab lock cannot be loaded" )
    spec   = importlib.util.spec_from_file_location( "crontab_lock", path )
    module = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( module )
    return module.crontab_lock


def _rewrite( lines, crontab_cmd, backup_dir, now ):
    """
    Do the read, backup and write of one crontab edit; the caller holds the lock.

    Ensures:
        - returns ( new text, None ) on success and ( None, failure text ) on any failed step
        - nothing is written after a failed read or a failed backup
    """
    read = subprocess.run( [ *crontab_cmd, "-l" ], capture_output=True, text=True )
    if read.returncode not in ( 0, 1 ): return None, f"crontab -l failed: {read.stderr.strip()}"
    old = read.stdout if read.returncode == 0 else ""
    try:
        os.makedirs( backup_dir, exist_ok=True )
        with open( os.path.join( backup_dir, f"crontab-{now.strftime( '%Y%m%d-%H%M%S' )}.txt" ), "w", encoding="utf-8" ) as handle: handle.write( old )
    except OSError as error: return None, f"no backup, so no write: {error}"
    new   = merge_lines( old, lines )
    write = subprocess.run( [ *crontab_cmd, "-" ], input=new, capture_output=True, text=True )
    if write.returncode != 0: return None, f"crontab write failed: {write.stderr.strip()}"
    return new, None


def edit_crontab( lines, environ, crontab_cmd, backup_dir, now ):
    """
    Read, back up and rewrite the crontab under the shared lock.

    Requires:
        - lines is the list to install, or an empty list to remove ours
        - crontab_cmd is the command list, for example [ "crontab" ]

    Ensures:
        - the whole read and write sit inside the lock
        - a timestamped backup of the old text is written first; no backup means no write
        - returns the new crontab text
        - raises InstallRefused when the lock module is missing, and RuntimeError when a crontab call or the backup fails
    """
    lock = load_crontab_lock( environ )
    with lock( owner="wiki-librarian-tick" ):
        new, failure = _rewrite( lines, crontab_cmd, backup_dir, now )
    if failure is not None: raise RuntimeError( failure )
    return new


def status_text( crontab_text ):
    """
    Describe the tagged lines found in a crontab text.

    Ensures:
        - returns "installed: 2 lines", "partly installed: n lines" or "not installed"
    """
    count = sum( 1 for line in crontab_text.splitlines() if line.rstrip().endswith( CRON_TAG ) )
    if count == 0: return "not installed"
    return f"installed: {count} lines" if count == 2 else f"partly installed: {count} lines"


def _live_librarian( environ, pending_path, log ):
    """Build the Librarian with the live store and the owner notice."""
    from lupin_cli.claude_code.hooks.lib import task_store_client as client
    from lupin_cli.claude_code.hooks.lib.task_store_settings import load_task_store_settings
    owner = environ.get( "WIKI_LIBRARIAN_OWNER", "cheech" )
    store = LiveStore( load_task_store_settings(), client.read_api_key(), client )
    return Librarian( store, pending_path, log, notify=lambda text: notify_owner( owner, text, environ ), owner=owner )


def _live_export():
    """Return the miss exporter from miss_record."""
    from cosa.repo.symindex.miss_record import export_misses
    return export_misses


def main( argv=None, environ=None, now=None, out=sys.stdout, err=sys.stderr, crontab_cmd=None, make_librarian=None, export_fn=None ):
    """
    Run the command line.

    Requires:
        - argv is a list of arguments, or None for sys.argv

    Ensures:
        - with no mode flag, runs one tick and returns its exit code
        - --print-install prints the cron lines and changes nothing
        - --install, --uninstall and --status go through edit_crontab or read the crontab
        - an InstallRefused or a RuntimeError prints one line to err and returns 1
    """
    environ = os.environ if environ is None else environ
    now     = now or datetime.datetime.now()
    parser  = argparse.ArgumentParser( prog="python -m cosa.repo.symindex.librarian_tick", description=__doc__.split( "\n\n" )[ 0 ] )
    mode    = parser.add_mutually_exclusive_group()
    for flag in ( "--install", "--uninstall", "--status", "--print-install" ): mode.add_argument( flag, action="store_true" )
    parser.add_argument( "--force", action="store_true" )
    parser.add_argument( "--root" )
    parser.add_argument( "--python", default=sys.executable )
    args    = parser.parse_args( argv )
    root    = args.root or os.environ.get( "LUPIN_ROOT" ) or os.getcwd()
    folder  = data_dir( root )
    cmd     = crontab_cmd or [ environ.get( "WIKI_LIBRARIAN_CRONTAB", "crontab" ) ]
    lines   = cron_lines( root, args.python, os.path.join( folder, LOG_NAME ) )
    if args.print_install:
        print( "\n".join( lines ), file=out )
        return 0
    try:
        if args.install or args.uninstall:
            edit_crontab( [] if args.uninstall else lines, environ, cmd, os.path.join( folder, "crontab-backups" ), now )
            print( "uninstalled" if args.uninstall else "installed: 2 lines", file=out )
            return 0
        if args.status:
            read = subprocess.run( [ *cmd, "-l" ], capture_output=True, text=True )
            print( status_text( read.stdout if read.returncode == 0 else "" ), file=out )
            return 0
    except ( InstallRefused, RuntimeError ) as error:
        print( f"wiki-librarian-tick: {error}", file=err )
        return 1
    log       = make_logger( os.path.join( folder, LOG_NAME ) )
    pending   = os.path.join( folder, PENDING_NAME )
    wiki_dir  = os.path.join( root, "src", "docs", "wiki" )
    librarian = ( make_librarian or _live_librarian )( environ, pending, log )
    code, summary = run_tick( root, wiki_dir, None, librarian, export_fn or _live_export(), os.path.join( wiki_dir, "misses.jsonl" ),
                              os.path.join( folder, STATE_NAME ), now, force=args.force, log=log )
    print( json.dumps( summary, sort_keys=True ), file=out )
    return code


if __name__ == "__main__":  # pragma: no cover - process entry point
    sys.exit( main() )
