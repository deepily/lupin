"""
The cron wrapper that gives a shell job a job-summary/1 record.

Put it in front of a cron command: `python -m lupin_mcp.job_run --job io-tmp-sweep -- sweep-io-tmp.sh --apply`.
It runs the command, passes its output through, and writes one record from the exit code.
Two optional patterns read counts from the output. The first group of --count-re is the scan debt.
The first group of --drained-re is what the run drained. A job that already writes its own record does not need it.
"""
import argparse
import datetime
import os
import pathlib
import re
import subprocess
import sys
import threading
import types

import cosa.rest.job_registry as jr
from lupin_mcp import host_snapshot as hs
from lupin_mcp import job_summary as js

EXIT_NO_JOB = 64
TRIGGER_WORDS = { "cron": "cron", "boot": "reboot" }                  # the cron entry script says cron or boot; duplicate-check's own flag calls a boot "reboot"


def last_int( pattern, text ):
    """
    Read the last integer a pattern captures.

    Requires:
        - pattern is a regex with one group, or None
    Ensures:
        - returns the int in the first group of the last match, with commas removed
        - returns None for no pattern, no match or a group that is not a number
    """
    if pattern is None: return None
    found = re.findall( pattern, text )
    if not found: return None
    digits = found[ -1 ] if isinstance( found[ -1 ], str ) else found[ -1 ][ 0 ]
    return int( digits.replace( ",", "" ) ) if digits.replace( ",", "" ).isdigit() else None


def stream_run( command, env=None, **_ignored ):
    """
    Run a command and pass its output through as it arrives, keeping a copy.

    Requires:
        - command is a non-empty argv list
    Ensures:
        - each line of stdout and stderr reaches this process's own stdout and stderr, flushed, while the command runs, so a log holds the run up to a crash or a reboot
        - returns a stand-in with returncode, stdout and stderr, the shape subprocess.run returns
        - raises OSError when the command cannot start, as subprocess.run does
    """
    proc  = subprocess.Popen( command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env )
    kept  = { "out": [], "err": [] }

    def pump( pipe, sink, key ):
        """Ensures: copies every line of pipe to sink, flushed, and into kept[ key ]."""
        for line in pipe:
            kept[ key ].append( line )
            sink.write( line ); sink.flush()

    pumps = [ threading.Thread( target=pump, args=( proc.stdout, sys.stdout, "out" ) ), threading.Thread( target=pump, args=( proc.stderr, sys.stderr, "err" ) ) ]
    for t in pumps: t.start()
    for t in pumps: t.join()
    return types.SimpleNamespace( returncode=proc.wait(), stdout="".join( kept[ "out" ] ), stderr="".join( kept[ "err" ] ) )


def run_and_report( summary_path, job, command, mode=None, count_re=None, drained_re=None, environ=None, runner=stream_run ):
    """
    Run a command and write the record of the run.

    Requires:
        - command is a non-empty argv list
    Ensures:
        - returns the command's exit code, and passes its stdout and stderr through
        - exit 0 is clean, any other code is failed with the code as the failure; a command that cannot start is failed with exit 127
        - the scan debt and drained figures come from the patterns, when they match
    """
    started = datetime.datetime.now().astimezone()
    try:
        done = runner( command, capture_output=True, text=True, env=environ )
        code, out, err = done.returncode, done.stdout, done.stderr
    except OSError as error:
        code, out, err = 127, "", f"job_run: could not start {command[ 0 ]}: {error}\n"
    if runner is not stream_run: sys.stdout.write( out ); sys.stderr.write( err )      # stream_run has already passed the output through
    attempt = { "started_at": js.iso_now( started ), "finished_at": js.iso_now(), "trigger": js.trigger_from_env( "cron", environ ), "outcome": "clean" if code == 0 else "failed",
                "stage": None if code == 0 else "command", "failure": None if code == 0 else f"exit {code}", "evidence": None, "mode": mode }
    count, drained = last_int( count_re, out + err ), last_int( drained_re, out + err )
    scan = { "unit": "items", "count": count, "drained_last_run": drained } if count is not None else None
    js.write_summary( summary_path, job, attempt, scan, None, count )
    hs.refresh_best_effort( environ )                                  # leave the container a fresh copy of the crontab
    return code


def with_trigger( argv, trigger ):
    """
    Put the cron trigger into a command that takes its own --trigger flag.

    Requires:
        - argv is a list of strings; trigger is cron or boot
    Ensures:
        - returns a copy of argv whose --trigger value is the trigger's word (cron, or reboot for boot)
        - returns an equal copy when argv has no --trigger flag, or the flag is last with no value
    """
    out = list( argv )
    for i, word in enumerate( out[ :-1 ] ):
        if word == "--trigger": out[ i + 1 ] = TRIGGER_WORDS[ trigger ]
    return out


def main( argv=None, environ=None, runner=stream_run ):
    """
    Run the wrapper from the command line.

    Requires:
        - argv holds --job, then -- and the command
        - the job is in the registry under LUPIN_ROOT

    Ensures:
        - returns the command's exit code, or EXIT_NO_JOB when the job is not registered or no command was given
    """
    environ = os.environ if environ is None else environ
    parser  = argparse.ArgumentParser( description="Run a command and write its job-summary/1 record." )
    parser.add_argument( "--job", required=True )
    parser.add_argument( "--mode", default=None )
    parser.add_argument( "--count-re", default=None )
    parser.add_argument( "--drained-re", default=None )
    parser.add_argument( "--from-registry", action="store_true", help="take the command and its environment from the job's registry entry, as Run now does" )
    parser.add_argument( "--trigger", default="cron", choices=sorted( TRIGGER_WORDS ), help="with --from-registry: how this run was started" )
    parser.add_argument( "command", nargs=argparse.REMAINDER )
    args    = parser.parse_args( argv )
    command = args.command[ 1: ] if args.command[ :1 ] == [ "--" ] else args.command
    root    = environ.get( "LUPIN_ROOT" ) or os.getcwd()
    entry   = next( ( j for j in jr.load_registry( root )[ "jobs" ] if j[ "job" ] == args.job ), None )
    if entry is not None and args.from_registry and entry.get( "run" ) and not command:
        from cosa.rest.job_service import run_command
        from cosa.repo.symindex.paths import data_dir
        command, environ = run_command( jr.load_registry( root ), entry, root, data_dir( root ), args.trigger, environ )
        command = with_trigger( command, args.trigger )
    if entry is None or not command:
        print( f"job_run: {'no job ' + args.job + ' in the registry' if entry is None else 'no command given'}", file=sys.stderr )
        return EXIT_NO_JOB
    from cosa.repo.symindex.paths import data_dir
    path = jr.resolve_path( entry[ "summary_path" ], root, data_dir( root ) )
    return run_and_report( path, args.job, command, args.mode, args.count_re, args.drained_re, environ, runner )


if __name__ == "__main__":  # pragma: no cover - process entry point
    sys.exit( main() )
