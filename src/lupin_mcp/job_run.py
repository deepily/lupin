"""
The cron wrapper that gives a shell job a job-summary/1 record.

Put it in front of a cron command: `python -m lupin_mcp.job_run --job io-tmp-sweep -- sweep-io-tmp.sh --apply`.
It runs the command, passes its output through, and writes one record from the exit code.
Two optional patterns read counts from the output. The first group of --count-re is the scan debt.
The first group of --drained-re is what the run drained. A job that already writes its own record does not need it.
"""
import argparse
import contextlib
import datetime
import io
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


def recorded_since( summary_path, started ):
    """
    Say whether a job's own record was written during this run.

    Requires:
        - started is the aware time the run began
    Ensures:
        - returns True when the file holds a record whose last attempt finished at or after started, to the second, because records are stamped to the second
        - returns False for a missing, unreadable or foreign file and for a finish time that cannot be read
    """
    doc = js.read_summary( summary_path )
    try: return doc is not None and datetime.datetime.fromisoformat( doc[ "last_attempt" ][ "finished_at" ] ) >= started.replace( microsecond=0 )
    except ( KeyError, TypeError, ValueError ): return False


def run_and_report( summary_path, job, command, mode=None, count_re=None, drained_re=None, environ=None, runner=stream_run, write_record=True, clean_codes=( 0, ) ):
    """
    Run a command and write the record of the run.

    Requires:
        - command is a non-empty argv list
    Ensures:
        - returns the command's exit code, and passes its stdout and stderr through
        - an exit code in clean_codes (default only 0) is clean, any other code is failed with the code as the failure; a command that cannot start is failed with exit 127
        - the scan debt and drained figures come from the patterns, when they match
        - with write_record false (a job that writes its own record) nothing is written when the command was clean or the job wrote its own record during the run
        - a job that writes its own record and exits with a failing code before writing it still gets a failed record, so a crash never leaves the old record standing
    """
    started = datetime.datetime.now().astimezone()
    try:
        done = runner( command, capture_output=True, text=True, env=environ )
        code, out, err = done.returncode, done.stdout, done.stderr
    except OSError as error:
        code, out, err = 127, "", f"job_run: could not start {command[ 0 ]}: {error}\n"
    if runner is not stream_run: sys.stdout.write( out ); sys.stderr.write( err )      # stream_run has already passed the output through
    attempt = { "started_at": js.iso_now( started ), "finished_at": js.iso_now(), "trigger": js.trigger_from_env( "cron", environ ), "outcome": "clean" if code in clean_codes else "failed",
                "stage": None if code in clean_codes else "command", "failure": None if code in clean_codes else f"exit {code}", "evidence": None, "mode": mode }
    count, drained = last_int( count_re, out + err ), last_int( drained_re, out + err )
    scan = { "unit": "items", "count": count, "drained_last_run": drained } if count is not None else None
    if write_record or ( code not in clean_codes and not recorded_since( summary_path, started ) ): js.write_summary( summary_path, job, attempt, scan, None, count )
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


def switched_on( entry, config ):
    """
    Read a registry job's run-time switch from the configuration.

    Requires:
        - entry is a registry job; config has get_required( key, return_type="boolean" )
    Ensures:
        - returns True when the entry names no enabled_key: only the cron-managed jobs have a switch
        - otherwise returns True or False as the INI key says, with no default in code
    Raises:
        - MissingConfigKeyError when the entry names a key the INI has no value for, or a blank one
    """
    if not entry.get( "enabled_key" ): return True
    return config.get_required( entry[ "enabled_key" ], return_type="boolean" )


def main( argv=None, environ=None, runner=stream_run, config=None ):
    """
    Run the wrapper from the command line.

    Requires:
        - argv holds --job, then -- and the command
        - the job is in the registry under LUPIN_ROOT

    Ensures:
        - returns the command's exit code, or EXIT_NO_JOB when the job is not registered or no command was given
        - returns 0 after one line naming the INI key when the job's switch is false: it writes one record with outcome disabled, never starts the command; cron, boot and manual runs all pass here
        - a job whose registry entry has no enabled_key has no switch and runs as before
        - config is the ConfigurationManager the switch is read from; None builds one from LUPIN_CONFIG_MGR_CLI_ARGS
        - with --from-registry and --root, the registry command gets --root <value> appended, so a job of another repo runs against that repo's checkout
    """
    environ = os.environ if environ is None else environ
    parser  = argparse.ArgumentParser( description="Run a command and write its job-summary/1 record." )
    parser.add_argument( "--job", required=True )
    parser.add_argument( "--mode", default=None )
    parser.add_argument( "--count-re", default=None )
    parser.add_argument( "--drained-re", default=None )
    parser.add_argument( "--from-registry", action="store_true", help="take the command and its environment from the job's registry entry, as Run now does" )
    parser.add_argument( "--trigger", default="cron", choices=sorted( TRIGGER_WORDS ), help="with --from-registry: how this run was started" )
    parser.add_argument( "--root", default=None, help="with --from-registry: the checkout of the repo this row belongs to, passed to the command as --root" )
    parser.add_argument( "command", nargs=argparse.REMAINDER )
    args    = parser.parse_args( argv )
    command = args.command[ 1: ] if args.command[ :1 ] == [ "--" ] else args.command
    root    = environ.get( "LUPIN_ROOT" ) or os.getcwd()
    registry = jr.load_registry( root )
    entry    = next( ( j for j in registry[ "jobs" ] if j[ "job" ] == args.job ), None )
    if entry is None or not ( command or ( args.from_registry and entry.get( "run" ) ) ):
        print( f"job_run: {'no job ' + args.job + ' in the registry' if entry is None else 'no command given'}", file=sys.stderr )
        return EXIT_NO_JOB
    from cosa.rest.job_service import bootstrap_env, run_command
    from cosa.repo.symindex.paths import data_dir
    if config is None:
        from cosa.config.configuration_manager import ConfigurationManager
        if "LUPIN_CONFIG_MGR_CLI_ARGS" not in environ: environ.update( bootstrap_env( registry, root ) )
        with contextlib.redirect_stdout( io.StringIO() ):      # the manager prints a startup banner that silent=True does not cover, and it would fill every cron log
            config = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS", silent=True, mute_splainer=True )
    if not switched_on( entry, config ):
        now     = js.iso_now()
        attempt = { "started_at": now, "finished_at": now, "trigger": js.trigger_from_env( args.trigger, environ ), "outcome": "disabled", "stage": None, "failure": None,
                    "evidence": f"INI key '{entry[ 'enabled_key' ]}' is false", "mode": args.mode }
        js.write_summary( jr.resolve_path( entry[ "summary_path" ], root, data_dir( root ) ), args.job, attempt )      # a disabled run is a run: the job reads as off, never overdue
        print( f"job_run: job {args.job} is switched off: INI key '{entry[ 'enabled_key' ]}' is false, so nothing ran" )
        return 0
    if args.from_registry and not command: environ.update( bootstrap_env( registry, root ) )    # data_dir reads the configuration manager's settings, so they come first
    data = data_dir( root )
    if args.from_registry and not command:
        command, environ = run_command( registry, entry, root, data, args.trigger, environ )
        command = with_trigger( command, args.trigger )
        if args.root is not None: command = [ *command, "--root", args.root ]
    path = jr.resolve_path( entry[ "summary_path" ], root, data )
    return run_and_report( path, args.job, command, args.mode, args.count_re, args.drained_re, environ, runner, write_record=not entry.get( "own_summary" ), clean_codes=tuple( entry.get( "clean_exit_codes", [ 0 ] ) ) )


if __name__ == "__main__":  # pragma: no cover - process entry point
    sys.exit( main() )
