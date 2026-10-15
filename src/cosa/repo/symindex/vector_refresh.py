"""
The daily job that keeps the stored vector set current.

A run is due once per local day, from 10:00 on, next to the wiki-librarian tick. It ensures the index,
writes the missing purpose lines and rebuilds the vectors. It does nothing when three things hold.
The live set was built from the current index. Its engines still match the server. No pin lacks a purpose line.

Otherwise it rebuilds through candidate_build.run. That swaps the new set in by rename, straight into
the shared reuse-review vectors folder. Rick approved that write in design section 5.4.

A job that dies leaves the live set and the stored purpose lines as they were. A purpose-line batch
that times out is retried once, and a second timeout ends the run with the failure named.

Exit 0 means nothing was due, the set was already fresh, or the set was rebuilt.
Exit 1 means the run could not finish, or an install was refused.
Exit 2 means a named candidate-stage error stopped the run.
Exit 3 means the job is switched off.
Exit 4 means another build holds the build lock.
"""
import argparse
import datetime
import json
import os
import pathlib
import subprocess
import sys

from cosa.repo.symindex import build as sx_build
from cosa.repo.symindex import candidate_build as cb
from cosa.repo.symindex import librarian_tick as lt
from cosa.repo.symindex.candidates import freshness as fr
from cosa.repo.symindex.candidates import purpose_lines as pl
from cosa.repo.symindex.candidates import storage_paths as sp
from cosa.repo.symindex.candidates import vector_store as vs
from cosa.repo.symindex.candidates.errors import CandidateError, BUILD_LOCK_HELD
from cosa.repo.symindex.paths import data_dir

CRON_TAG       = "# reuse-vector-refresh"
CRON_SCHEDULE  = "47 10 * * *"
ENABLED_KEY    = "reuse vector refresh enabled"
FOLDER         = "refresh"
SCRIPT_NAME    = "reuse-vector-refresh.sh"
STATE_NAME     = "refresh-state.json"
LOG_NAME       = "refresh.log"
LOCK_OWNER     = "reuse-vector-refresh"
ATTEMPTS       = 2
EXIT_OK        = 0
EXIT_FAILED    = 1
EXIT_NAMED     = 2
EXIT_DISABLED  = 3
EXIT_LOCK_HELD = 4


def refresh_dir( root ):
    """
    Name the folder that holds the job's state file and log.

    Requires:
        - root is the main checkout

    Ensures:
        - returns <reuse-review data dir>/refresh; nothing is created
    """
    return data_dir( root ) / FOLDER


def missing_purpose_lines( entries, purpose_store, screen, settled=() ):
    """
    Count the sendable pins that have no stored purpose line.

    Requires:
        - entries are the public symbols of an index generation
        - screen is a Screen from purpose_lines.default_screen
        - settled are pins the last build for this index could not get a line for

    Ensures:
        - returns the number of distinct pins the screen lets through that purpose_store holds no line for
        - a settled pin is not counted, so a pin the writer never answers is not rebuilt for every day
    """
    stored      = pl.load_lines( purpose_store )
    skipped     = set( settled )
    sendable, _ = screen.sendable( entries )
    return len( { e[ "pin" ] for e in sendable if e[ "pin" ] not in stored and e[ "pin" ] not in skipped } )


def check_fresh( live, header, entries, purpose_store, client, screen ):
    """
    Say whether the live vector set needs no work.

    Requires:
        - header is the parsed header.json of the ensured index; entries are its public symbols
        - client has info()
        - screen is a Screen from purpose_lines.default_screen

    Ensures:
        - returns ( True, "fresh" ) only when the set records an index manifest equal to the index's,
          its manifest is readable, its engines match what the server reports, and every sendable pin
          has a stored purpose line or is listed in the set's unwritten_pins for this index
        - otherwise returns ( False, reason ) with the first reason found
        - an engine mismatch or an engine that is not loaded is a reason, not an error
    """
    info = fr.read_build_info( live )
    if info is None: return False, "the live set has no build info"
    if info[ "index_manifest" ] != fr.index_manifest( header ): return False, "the index changed since the set was built"
    manifest = fr.read_manifest( live )
    if manifest is None: return False, "the live set's manifest cannot be read"
    try:
        vs.check_engines( manifest, client.info() )
    except CandidateError as e:
        return False, f"engines: {e.code}"
    missing = missing_purpose_lines( entries, purpose_store, screen, info.get( "unwritten_pins", [] ) )
    if missing: return False, f"{missing} pins have no purpose line"
    return True, "fresh"


def _finish( state_path, state, now ):
    """Write the state file with the attempt time, and return the dict written."""
    state = { **state, "last_attempt_at": now.isoformat( timespec="seconds" ) }
    lt.write_state( state_path, state )
    return state


def run_refresh( root, writer, client, state_path, now, force=False, log=print, config=None, environ=None, screen=None, run_fn=None ):
    """
    Run one refresh.

    Requires:
        - root is the main checkout; writer takes ids and returns { id: purpose }; client has embed and info
        - now is a datetime in local time
        - run_fn stands in for candidate_build.run, or is None

    Ensures:
        - returns ( exit_code, summary dict )
        - nothing is done and 0 is returned when the run is not due and force is False
        - a fresh set ends the run with outcome "fresh" and the day recorded
        - a rebuild is attempted up to the module's attempt count, and only a TimeoutError is retried
        - last_run_date is recorded only for a fresh set or a finished build, so a failed day is due again at the next tick
        - a failure records last_outcome "failed" and last_error, and keeps the previous last_run_date and built_at
        - a held build lock returns EXIT_LOCK_HELD and leaves the state file untouched
    """
    state = lt.read_state( state_path )
    if not force and not lt.due( now, state ): return EXIT_OK, { "ran": False, "reason": "not due" }
    screen   = screen if screen is not None else pl.default_screen()
    run_fn   = run_fn if run_fn is not None else cb.run
    try:
        data      = data_dir( root )
        live      = sp.candidate_dir( "vectors", data, config, environ )
        purpose   = sp.candidate_dir( "purpose", data, config, environ )
        gen       = sx_build.ensure( root )
        header    = sx_build.read_header( gen )
        entries   = sx_build.read_symbols( gen )
        fresh, why = check_fresh( live, header, entries, purpose / "purpose.jsonl", client, screen )
        if fresh:
            summary = { "ran": True, "outcome": "fresh", "reason": why }
            _finish( state_path, { "last_run_date": now.date().isoformat(), "last_outcome": "fresh", "last_error": None,
                                   "built_at": ( fr.read_build_info( live ) or {} ).get( "built_at" ) }, now )
            log( "refresh finished: " + json.dumps( summary, sort_keys=True ) )
            return EXIT_OK, summary
        log( f"refresh needed: {why}" )
        last_error = None
        for attempt in range( 1, ATTEMPTS + 1 ):
            try:
                report = run_fn( root, writer, client, screen=screen, config=config, environ=environ )
                break
            except TimeoutError as e:
                last_error = f"TimeoutError: {e}"
                log( f"refresh attempt {attempt} of {ATTEMPTS} timed out: {e}" )
        else:
            return _fail( state_path, state, now, last_error, log, EXIT_FAILED )
    except CandidateError as e:
        if e.code == BUILD_LOCK_HELD:
            log( f"refresh skipped: {e}" )
            return EXIT_LOCK_HELD, { "ran": False, "reason": e.code }
        return _fail( state_path, state, now, str( e ), log, EXIT_NAMED )
    except ( RuntimeError, ValueError, OSError ) as e:
        return _fail( state_path, state, now, f"{type( e ).__name__}: {e}", log, EXIT_FAILED )
    summary = { "ran": True, "outcome": "built", "reason": why, "rows": report[ "rows" ], "manifest_hash": report[ "manifest_hash" ],
                "purposes_written": report[ "purposes" ][ "written" ], "seconds": report[ "seconds" ], "built_at": report[ "built_at" ] }
    _finish( state_path, { "last_run_date": now.date().isoformat(), "last_outcome": "built", "last_error": None, "built_at": report[ "built_at" ],
                           "last_seconds": report[ "seconds" ], "rows": report[ "rows" ], "manifest_hash": report[ "manifest_hash" ] }, now )
    log( "refresh finished: " + json.dumps( summary, sort_keys=True ) )
    return EXIT_OK, summary


def _fail( state_path, previous, now, error, log, code ):
    """
    Record a failed run and build its answer.

    Ensures:
        - the state keeps the previous last_run_date and built_at, and gains last_outcome failed and last_error
        - returns ( code, summary )
    """
    log( f"refresh could not finish: {error}" )
    kept = { k: previous[ k ] for k in ( "last_run_date", "built_at" ) if k in previous }
    _finish( state_path, { **kept, "last_outcome": "failed", "last_error": error }, now )
    return code, { "ran": False, "outcome": "failed", "reason": error }


def cron_lines( root, python, log_path ):
    """
    Build the two cron lines.

    Requires:
        - root is the main checkout path; python is the interpreter path

    Ensures:
        - returns [ daily line, reboot line ], each ending with CRON_TAG
        - the daily line is inside the 10:00 to 13:00 window
        - each line runs the wrapper script, which sources the credential file named in REUSE_VECTOR_REFRESH_ENV
        - the reboot line gives a slow start 240 seconds before the run, after the librarian's 120
    """
    run = f"cd {root} && LUPIN_ROOT={root} REUSE_VECTOR_REFRESH_PYTHON={python} {root}/src/scripts/{SCRIPT_NAME} >> {log_path} 2>&1 {CRON_TAG}"
    return [ f"{CRON_SCHEDULE} {run}", f"@reboot sleep 240 && {run}" ]


def main( argv=None, environ=None, now=None, out=sys.stdout, err=sys.stderr, crontab_cmd=None, writer_factory=None, client=None, enabled_fn=None ):
    """
    Run the command line.

    Requires:
        - argv is a list of arguments, or None for sys.argv

    Ensures:
        - with no mode flag, runs one refresh and returns its exit code
        - a job that is switched off logs one line and returns EXIT_DISABLED before the index is built
        - --print-install prints the cron lines and changes nothing
        - --install, --uninstall and --status go through the librarian's locked crontab editor with this job's tag
        - an InstallRefused or a RuntimeError prints one line to err and returns 1
        - a worktree root or a missing credential prints the named error as JSON and returns EXIT_NAMED
    """
    environ = os.environ if environ is None else environ
    now     = now or datetime.datetime.now()
    parser  = argparse.ArgumentParser( prog="python -m cosa.repo.symindex.vector_refresh", description=__doc__.split( "\n\n" )[ 0 ] )
    mode    = parser.add_mutually_exclusive_group()
    for flag in ( "--install", "--uninstall", "--status", "--print-install" ): mode.add_argument( flag, action="store_true" )
    parser.add_argument( "--force", action="store_true" )
    parser.add_argument( "--root" )
    parser.add_argument( "--python", default=sys.executable )
    parser.add_argument( "--base-url", default=environ.get( "LUPIN_APP_SERVER_URL", "http://localhost:7999" ) )
    args    = parser.parse_args( argv )
    root    = args.root or environ.get( "LUPIN_ROOT" ) or os.getcwd()
    cmd     = crontab_cmd or [ environ.get( "REUSE_VECTOR_REFRESH_CRONTAB", "crontab" ) ]
    try:
        folder = refresh_dir( root )
    except CandidateError as e:
        print( json.dumps( { "error": e.code, "detail": e.detail } ), file=out )
        return EXIT_NAMED
    lines   = cron_lines( root, args.python, os.path.join( folder, LOG_NAME ) )
    if args.print_install:
        print( "\n".join( lines ), file=out )
        return EXIT_OK
    try:
        if args.install or args.uninstall:
            lt.edit_crontab( [] if args.uninstall else lines, environ, cmd, os.path.join( folder, "crontab-backups" ), now, tag=CRON_TAG, owner=LOCK_OWNER )
            print( "uninstalled" if args.uninstall else "installed: 2 lines", file=out )
            return EXIT_OK
        if args.status:
            read = subprocess.run( [ *cmd, "-l" ], capture_output=True, text=True )
            print( lt.status_text( read.stdout if read.returncode == 0 else "", CRON_TAG ), file=out )
            return EXIT_OK
    except ( lt.InstallRefused, RuntimeError ) as error:
        print( f"reuse-vector-refresh: {error}", file=err )
        return EXIT_FAILED
    log         = lt.make_logger( os.path.join( folder, LOG_NAME ) )
    read_errors = []
    if not ( enabled_fn or ( lambda: lt.read_enabled( errors=read_errors, key=ENABLED_KEY ) ) )():
        log( f"refresh could not read {ENABLED_KEY}, so it stays off: {read_errors[ 0 ]}" if read_errors else f"refresh is switched off: {ENABLED_KEY} is not true" )
        print( json.dumps( { "ran": False, "reason": "switched off" }, sort_keys=True ), file=out )
        return EXIT_DISABLED
    try:
        writer = ( writer_factory or ( lambda a: cb.make_job_writer( root, a.base_url, environ ) ) )( args )
    except ValueError as error:
        print( json.dumps( { "error": "WORKTREE_ROOT", "detail": str( error ) } ), file=out )
        return EXIT_NAMED
    except CandidateError as error:
        print( json.dumps( { "error": error.code, "detail": error.detail } ), file=out )
        return EXIT_NAMED
    code, summary = run_refresh( root, writer, client if client is not None else cb.vb.EndpointClient(),
                                 os.path.join( folder, STATE_NAME ), now, force=args.force, log=log, environ=environ )
    print( json.dumps( summary, sort_keys=True ), file=out )
    return code


if __name__ == "__main__":  # pragma: no cover - process entry point
    sys.exit( main() )
