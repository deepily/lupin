"""
The service behind /api/jobs.

`build_response` is pure given a `Deps` object, so every path is testable with a fake clock and fake inputs. `LiveDeps` is the
real thing: boot time from /proc/stat, a systemd unit's state, a non-blocking flock probe, and the task store's row counts.
`run_now` starts one run of a job outside its schedule. It is the only management action Rick allowed.
"""
import datetime
import fcntl
import os
import pathlib
import subprocess
import threading

import cosa.rest.job_health as jh
import cosa.rest.job_registry as jr
from cosa.rest.task_store_rules import TERMINAL_STATUSES
from lupin_mcp import host_snapshot as hs
from lupin_mcp import job_summary as js
from lupin_mcp.reuse_needset.stage_c_score import lowest

SCHEMA          = "jobs-summary/1"
MARK_PREFIX     = "prefix:"
MARK_PROJECT    = "lupin"
RUN_NOW_LOG     = "io/jobs/run-now.log"
NOT_RUNNABLE    = "not_runnable"
LOCK_HELD       = "lock_held"
UNKNOWN_JOB     = "unknown_job"
LAUNCH_FAILED   = "launch_failed"


def boot_time_from( stat_text ):
    """
    Read the machine's boot time out of /proc/stat text.

    Requires:
        - stat_text has a line "btime <epoch seconds>"
    Ensures:
        - returns an aware datetime in the host's time zone
    Raises:
        - ValueError when there is no btime line
    """
    for line in stat_text.splitlines():
        if line.startswith( "btime " ): return datetime.datetime.fromtimestamp( int( line.split()[ 1 ] ) ).astimezone()
    raise ValueError( "no btime line in /proc/stat" )


def store_counts_from_rows( rows, now, days ):
    """
    Count a job's own rows in the store.

    Requires:
        - rows are every row carrying the job's mark, terminal ones included (each with status, created_ts, updated_ts, aware)
    Ensures:
        - open_now counts rows not done or dropped
        - opened_in_window counts rows created in the last days; closed_in_window counts terminal rows last updated in that window
        - open_at_window_start counts rows created before the window that were not yet closed then
    """
    start = now - datetime.timedelta( days=days )
    closed = lambda r: r.status in TERMINAL_STATUSES
    return { "open_now": sum( not closed( r ) for r in rows ),
             "opened_in_window": sum( r.created_ts >= start for r in rows ),
             "closed_in_window": sum( closed( r ) and r.updated_ts >= start for r in rows ),
             "open_at_window_start": sum( r.created_ts < start and ( not closed( r ) or r.updated_ts >= start ) for r in rows ) }


class LiveDeps:
    """The real inputs: the machine, systemd, the lock files and the task store."""

    def __init__( self, root, data ):
        """
        Hold the two folders the live inputs read from.

        Requires:
            - root is the Lupin root; data is the reuse-review data folder

        Ensures:
            - holds both paths; reads nothing yet
        """
        self.root = pathlib.Path( root )
        self.data = pathlib.Path( data )
        self.zone = None

    def boot_time( self ):
        """Ensures: returns the machine's boot time."""
        return boot_time_from( pathlib.Path( "/proc/stat" ).read_text() )

    def crontab_text( self ):
        """
        Read the installed crontab, from the host snapshot when this process cannot ask.

        Ensures:
            - returns the text of crontab -l when it can be run (the host), else the copy a host job wrote, if that is fresh
            - returns None when neither answers, or the snapshot names no time zone: the card then says its schedule is unverified
        """
        direct = hs.crontab_text()
        self.zone = None
        if direct is not None: return direct
        snap = hs.read_snapshot( self.data, datetime.datetime.now().astimezone() )
        self.zone = snap[ "zone" ]
        return snap[ "crontab" ] if self.zone is not None else None            # hours with no zone cannot be read: schedule unverified

    def host_zone( self ):
        """
        Name the zone the crontab's hours are written in.

        Ensures:
            - returns the host's tzinfo when the crontab came from the snapshot (the container runs in UTC), else None: the clock is already local
            - answers for the last crontab_text call, so call that first
        """
        return self.zone

    def unit_state( self, unit, health_url=None ):
        """
        Say whether a service is up.

        The sources are systemd, then the host tick's snapshot, then the service's health endpoint.

        Ensures:
            - returns "active", "inactive" or "not-loaded"; None when no source answers (the container has no systemctl)
        """
        direct = hs.unit_state( unit )
        if direct is not None: return direct
        units = hs.read_snapshot( self.data, datetime.datetime.now().astimezone() )[ "units" ]
        if units is not None and units.get( unit ) is not None: return units[ unit ]
        return hs.health_ok( health_url ) if health_url else None

    def lock_held( self, path ):
        """
        Say whether a live process holds a flock on a file.

        Ensures:
            - returns True when a shared lock cannot be taken at once; the probe releases at once, so it never blocks the job
            - returns False when the file is missing, unreadable or free
        """
        try:
            with open( path, "a" ) as handle:
                try: fcntl.flock( handle, fcntl.LOCK_SH | fcntl.LOCK_NB )
                except BlockingIOError: return True
                fcntl.flock( handle, fcntl.LOCK_UN )
                return False
        except OSError:
            return False

    def store_counts( self, key, now, days ):
        """
        Count the rows that carry a job's own mark.

        Requires:
            - key is "prefix:<text>": every row the job files has a correlation_key starting with <text> (the key is per finding or per run, so only its start names the job)

        Ensures:
            - reads only rows in project lupin whose correlation_key starts with <text>
            - returns the store_counts_from_rows dict, terminal rows included
            - returns None when the store cannot be reached: the page then says "open rows: not reported", never zero
        """
        try:
            from cosa.rest.db.database import get_db
            from cosa.rest.db.repositories.task_repository import TaskRepository
            with get_db() as session:
                rows = TaskRepository( session ).query_tasks( project=MARK_PROJECT, correlation_key_prefix=key.split( MARK_PREFIX, 1 )[ 1 ], include_terminal=True, limit=500 )
                return store_counts_from_rows( rows, now, days )
        except Exception:                                              # the store is an outside service; any failure is "not reported"
            return None


def expand( value, root, data, home, pip, deepily_data ):
    """
    Fill the placeholders of a run command.

    Ensures:
        - returns value with {root}, {data}, {home}, {pip}, {deepily_data} and {python} replaced, inside lists and dicts too
    """
    if isinstance( value, str ):
        for name, real in ( ( "root", root ), ( "data", data ), ( "home", home ), ( "pip", pip ), ( "deepily_data", deepily_data ), ( "python", f"{root}/.venv/bin/python" ) ):
            value = value.replace( "{" + name + "}", str( real ) )
        return value
    if isinstance( value, list ): return [ expand( v, root, data, home, pip, deepily_data ) for v in value ]
    if isinstance( value, dict ): return { k: expand( v, root, data, home, pip, deepily_data ) for k, v in value.items() }
    return value


def home_and_pip( root ):
    """Ensures: returns ( home, planning-is-prompting root ) from the environment, with defaults."""
    return os.environ.get( "HOME", "/root" ), os.environ.get( "PLANNING_IS_PROMPTING_ROOT", f"{pathlib.Path( root ).parent}/planning-is-prompting" )


def paths_of( root, data ):
    """
    Work out the placeholder values for run commands.

    Ensures:
        - home, the planning-is-prompting root and the deepily data folder come from the environment
    """
    home, pip = home_and_pip( root )
    return root, data, home, pip, os.environ.get( "DEEPILY_DATA_DIR", str( pathlib.Path( data ).parents[ 1 ] ) )


def assess_read( merged, target, summary, defaults, ctx ):
    """
    Ask the live inputs what one summary needs, then assess it.

    Requires:
        - merged is the effective entry with the target's own keys; summary is a record or None
    Ensures:
        - the run lock is probed only for a job that has reported, and the store only for a job with a mark that has reported
        - returns the JobEntry dict from job_health.assess
    Raises:
        - KeyError, TypeError, ValueError or AttributeError when the record is missing a field or holds a wrong type
    """
    root, data, now, deps = ctx[ "root" ], ctx[ "data" ], ctx[ "now" ], ctx[ "deps" ]
    live = merged.get( "liveness" )
    lock = None
    if merged.get( "lock_path" ) and summary is not None and deps.lock_held( jr.resolve_path( merged[ "lock_path" ], root, data ) ):
        lock = ( now - jh.parse_time( summary[ "last_attempt" ][ "started_at" ] ) ).total_seconds()
    store = deps.store_counts( merged[ "fix_debt_key" ], now, defaults[ "window_days" ] ) if merged.get( "fix_debt" ) and merged.get( "fix_debt_key" ) and summary is not None else None
    return jh.assess( merged, summary, now, deps.boot_time(), defaults, store=store, lock_age=lock,
                      unit_state=deps.unit_state( live[ "unit" ], live.get( "health_url" ) ) if live else None, target=target[ "target" ] if target else None )


def assess_target( ent, target, defaults, ctx ):
    """
    Assess one job, or one target of a job.

    Requires:
        - ent is an effective registry entry; target is a dict { target, summary_path?, liveness? } or None
        - ctx is { root, data, now, deps }
    Ensures:
        - returns the JobEntry dict from job_health.assess
        - a target without its own summary_path reads <job summary folder>/<target>/job-summary.json
        - an unreadable or foreign-schema summary file reads as unknown, with its own reason
    """
    root, data = ctx[ "root" ], ctx[ "data" ]
    merged = { **ent, **( { k: v for k, v in target.items() if k != "target" } if target else {} ) }
    path   = jr.resolve_path( merged[ "summary_path" ], root, data )
    if target and "summary_path" not in target: path = path.parent / target[ "target" ] / path.name
    summary = js.read_summary( path )
    try:
        got = assess_read( merged, target, summary, defaults, ctx )
    except ( KeyError, TypeError, ValueError, AttributeError ):          # a record with the right schema but a missing or wrong-typed field
        got, summary = assess_read( merged, target, None, defaults, ctx ), None
        got[ "unknown_reason" ] = "unreadable"
    if summary is None and not merged.get( "liveness" ) and path.exists(): got[ "unknown_reason" ] = "unreadable"
    return got


def worst( entries ):
    """
    Pick the worst state among entries.

    Ensures:
        - returns the first of unknown, silent, failing, behind, healthy that any entry has
    """
    return lowest( ( e[ "state" ] for e in entries ), jh.STATE_ORDER )


def assess_job( ent, defaults, ctx ):
    """
    Assess a registry job, with its targets drawn under it when it has some.

    Ensures:
        - a job with targets takes the worst state of its targets, lists their reasons with the target name in front, and carries each as an entry of its own
        - a job without targets is one entry
    """
    if not ent.get( "targets" ): return assess_target( ent, None, defaults, ctx )
    kids = [ assess_target( ent, t, defaults, ctx ) for t in ent[ "targets" ] ]
    base = dict( kids[ 0 ] )
    base.update( target=None, state=worst( kids ), running=any( k[ "running" ] for k in kids ), machine_was_off=any( k[ "machine_was_off" ] for k in kids ),
                 reasons=[ { **r, "text": f"{k[ 'target' ]}: {r[ 'text' ]}" } for k in kids for r in k[ "reasons" ] ], unknown_reason="a target has not reported" if any( k[ "state" ] == "unknown" for k in kids ) else None,
                 targets=kids )
    return base


def build_response( root, data, now, deps ):
    """
    Build the GET /api/jobs/summary response.

    Requires:
        - root holds src/conf/job-registry.json; now is aware; deps offers boot_time, crontab_text, host_zone, unit_state, lock_held and store_counts
    Ensures:
        - returns { schema, generated_at, jobs, reporting_off, reporting_off_line }, one entry per registry job whose reporting is on, worst state first and then by title
        - a job with "reporting": "off" is left out of jobs; reporting_off counts those jobs and reporting_off_line says so in one sentence (None when none are off)
        - cron times are read in the zone of the crontab, so a UTC container agrees with the host
        - a job with a cron_tag takes the schedule of its installed crontab lines, else the registry's
        - the registry's overrides file is read on this call, so a changed grace or notification interval applies at once
    Raises:
        - ValueError or OSError when the registry itself is unreadable or invalid: the page cannot say anything honest then
    """
    registry  = jr.load_registry( root )
    overrides = jr.load_overrides( root )
    cron      = deps.crontab_text()
    zone      = deps.host_zone()
    if zone is not None: now = now.astimezone( zone )                    # cron hours are in the host's zone, whatever zone this process runs in
    ctx       = { "root": root, "data": data, "now": now, "deps": deps }
    shown     = [ j for j in registry[ "jobs" ] if jr.reporting_on( j ) ]
    off       = len( registry[ "jobs" ] ) - len( shown )
    jobs      = [ assess_job( jr.with_installed_schedule( jr.effective( j, registry[ "defaults" ], overrides ), cron ), registry[ "defaults" ], ctx ) for j in shown ]
    jobs.sort( key=lambda e: ( jh.STATE_ORDER.index( e[ "state" ] ), e[ "title" ] ) )
    line      = None if off == 0 else f"{off} {'job has' if off == 1 else 'jobs have'} reporting switched off"
    return { "schema": SCHEMA, "generated_at": now.isoformat(), "jobs": jobs, "reporting_off": off, "reporting_off_line": line }


def run_command( registry, ent, root, data, trigger, base_env=None ):
    """
    Build the argv and the environment of one run of a registry job.

    Requires:
        - ent is a registry job with a run block; trigger is cron, boot or hand
    Ensures:
        - returns ( argv, env ): argv is run.argv expanded; env is base_env (default os.environ), then the registry's run_env, then the job's run.env, then LUPIN_JOB_TRIGGER set to trigger
        - this is the one place Run now and the cron entry script both read a job's command from
    """
    values = paths_of( root, data )
    env    = { **( os.environ if base_env is None else base_env ), **expand( registry[ "defaults" ][ "run_env" ], *values ), **expand( ent[ "run" ].get( "env", {} ), *values ), js.TRIGGER_ENV: trigger }
    return expand( ent[ "run" ][ "argv" ], *values ), env


def bootstrap_env( registry, root ):
    """
    Pick the registry settings a process needs before it can find the data folder.

    Requires:
        - registry is the dict load_registry returns; root is the Lupin root
    Ensures:
        - returns the defaults.run_env entries whose value names neither {data} nor {deepily_data}, expanded with the root, home and planning-is-prompting paths
        - these are the settings (for example LUPIN_CONFIG_MGR_CLI_ARGS) the configuration manager reads when data_dir runs, so cron needs no copy of them in the shell
    """
    home, pip = home_and_pip( root )
    return { name: expand( value, root, "", home, pip, "" ) for name, value in registry[ "defaults" ][ "run_env" ].items() if "{data}" not in value and "{deepily_data}" not in value }


def run_now( root, data, job, target, deps, now, spawn=subprocess.Popen ):
    """
    Start one run of a job outside its schedule.

    Requires:
        - the caller has already proved the login is Rick's
        - spawn is subprocess.Popen, or a stand-in with the same call shape
    Ensures:
        - returns ( http status, body )
        - 404 { reason: unknown_job } when the registry has no such job
        - 422 { reason: not_runnable } when the job has no run command
        - 409 { status: refused, reason: lock_held } when its run lock is held: Run now never queues behind or jumps a live run
        - 422 { status: refused, reason: launch_failed, detail } when the command cannot be started (for example its script is not on this machine); detail names the path the operating system could not open, and nothing is left running
        - 200 { job, target, status: started, trigger: hand, pid, started_at } otherwise; the run's output is appended to RUN_NOW_LOG
        - the child starts with LUPIN_JOB_TRIGGER=hand, so its summary records trigger hand
    """
    registry = jr.load_registry( root )
    ent = next( ( j for j in registry[ "jobs" ] if j[ "job" ] == job ), None )
    if ent is None: return 404, { "status": "refused", "reason": UNKNOWN_JOB }
    if not ent.get( "run" ): return 422, { "status": "refused", "reason": NOT_RUNNABLE }
    if ent.get( "lock_path" ) and deps.lock_held( jr.resolve_path( ent[ "lock_path" ], root, data ) ): return 409, { "status": "refused", "reason": LOCK_HELD }
    argv, env = run_command( registry, ent, root, data, "hand" )
    log    = pathlib.Path( root ) / RUN_NOW_LOG
    log.parent.mkdir( parents=True, exist_ok=True )
    try:
        with open( log, "a" ) as sink:
            proc = spawn( argv, env=env, cwd=str( root ), stdout=sink, stderr=sink, stdin=subprocess.DEVNULL, start_new_session=True )
    except OSError as error:
        missing = error.filename if error.filename is not None else argv[ 0 ]
        return 422, { "status": "refused", "reason": LAUNCH_FAILED, "detail": f"Not started: this server cannot launch {missing} ({error.strerror or error})." }
    threading.Thread( target=proc.wait, daemon=True ).start()           # reap the child when it ends, so Run now leaves no zombie
    return 200, { "job": job, "target": target, "status": "started", "trigger": "hand", "pid": proc.pid, "started_at": now.isoformat() }
