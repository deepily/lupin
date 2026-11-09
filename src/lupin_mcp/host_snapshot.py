"""
A host-side snapshot of the crontab and the systemd units, for the container.

The :7999 container has no crontab command and no systemctl. Host jobs write the installed crontab.
A host tick also writes the state of the systemd units, into one file in the reuse-review data folder, which the container mounts.
Each part has its own time and its own limit. A part past its limit is not trusted, and the card then says
"schedule unverified" instead of quietly using the registry's schedule.
"""
import datetime
import json
import os
import pathlib
import shlex
import subprocess
import sys
import urllib.request
import zoneinfo

from lupin_mcp.job_summary import write_atomic

SCHEMA          = "host-snapshot/1"
SNAPSHOT_FILE   = "job-host-snapshot.json"                             # in the reuse-review data folder, which the container mounts
CRONTAB_MAX_AGE = 36 * 3600                                           # the crontab changes rarely; every host job run refreshes it
UNITS_MAX_AGE   = 1800                                                # a host tick refreshes the units every five minutes


def crontab_text( run=None, cmd=None ):
    """
    Read the installed crontab.

    Requires:
        - cmd is the crontab command as a list, or None for [ "crontab" ]
    Ensures:
        - returns the text of crontab -l, or None when it cannot be run or answers an error (no crontab included)
    """
    run = subprocess.run if run is None else run
    try:
        done = run( [ *( cmd or [ "crontab" ] ), "-l" ], capture_output=True, text=True, timeout=10 )
    except ( OSError, subprocess.TimeoutExpired ):
        return None
    return done.stdout if done.returncode == 0 else None


def unit_state( unit, run=None ):
    """
    Ask systemd about a user unit.

    Ensures:
        - returns "active", "inactive" or "not-loaded"; None when systemctl cannot be run or answers nothing usable
    """
    run = subprocess.run if run is None else run
    try:
        shown = run( [ "systemctl", "--user", "show", unit, "--property=LoadState,ActiveState" ], capture_output=True, text=True, timeout=10 )
    except ( OSError, subprocess.TimeoutExpired ):
        return None
    facts = dict( line.split( "=", 1 ) for line in shown.stdout.splitlines() if "=" in line )
    if facts.get( "LoadState" ) == "not-found": return "not-loaded"
    if facts.get( "ActiveState" ) is None: return None
    return "active" if facts[ "ActiveState" ] == "active" else "inactive"


def registry_units( registry ):
    """
    List the systemd units a registry names.

    Ensures:
        - returns every unit named by a job or a target, in order, once each
    """
    units = []
    for job in registry[ "jobs" ]:
        for item in [ job, *job.get( "targets", [] ) ]:
            unit = ( item.get( "liveness" ) or {} ).get( "unit" )
            if unit and unit not in units: units.append( unit )
    return units


def host_zone_name( environ=None, localtime="/etc/localtime" ):
    """
    Name the host's time zone, such as America/New_York.

    Ensures:
        - returns the TZ variable when it names a known zone, else the zone /etc/localtime links to
        - returns None when neither names a known zone
    """
    environ = os.environ if environ is None else environ
    names = [ environ.get( "TZ" ) ]
    real  = os.path.realpath( localtime )
    if "zoneinfo/" in real: names.append( real.split( "zoneinfo/", 1 )[ 1 ] )
    for name in names:
        if name and zone_of( name ) is not None: return name
    return None


def zone_of( name ):
    """Ensures: returns the ZoneInfo for a zone name, or None when the name is empty or unknown."""
    try:
        return zoneinfo.ZoneInfo( name )
    except ( zoneinfo.ZoneInfoNotFoundError, ValueError, TypeError, OSError ):
        return None


def health_ok( url, opener=urllib.request.urlopen ):
    """
    Ask a service's health endpoint.

    Ensures:
        - returns "active" for an HTTP 200, "inactive" for any other answer or no answer within 3 seconds
    """
    try:
        with opener( url, timeout=3 ) as answer:
            return "active" if answer.status == 200 else "inactive"
    except OSError:
        return "inactive"


def read_snapshot( data, now ):
    """
    Read the snapshot file.

    Ensures:
        - returns { crontab, units, zone } where each part is None when its time is missing or past its limit; zone is the host's tzinfo, or None
        - returns all three None when the file is missing, unreadable or of another schema
        - a crontab that was unreadable when written reads as None too
    """
    empty = { "crontab": None, "units": None, "zone": None }
    try:
        doc = json.loads( ( pathlib.Path( data ) / SNAPSHOT_FILE ).read_text() )
        if doc.get( "schema" ) != SCHEMA: return empty
    except ( OSError, ValueError, AttributeError ):
        return empty

    def fresh( key, limit ):
        try: when = datetime.datetime.fromisoformat( doc[ key ] )
        except ( KeyError, ValueError, TypeError ): return False
        return when.tzinfo is not None and ( now - when ).total_seconds() <= limit

    return { "crontab": doc.get( "crontab" ) if fresh( "crontab_at", CRONTAB_MAX_AGE ) else None,
             "units": doc.get( "units" ) if fresh( "units_at", UNITS_MAX_AGE ) else None,
             "zone": zone_of( doc.get( "zone" ) ) }


def write_snapshot( data, now, units=None, run=None ):
    """
    Refresh the snapshot, keeping the part that was not asked for.

    Requires:
        - data is the reuse-review data folder; units is a list of unit names for a host tick, or None for a job run
    Ensures:
        - the crontab and its time are always rewritten
        - the units and their time are rewritten only when units is given; otherwise the previous ones are kept
        - the file is replaced by rename
    """
    run = subprocess.run if run is None else run
    path = pathlib.Path( data ) / SNAPSHOT_FILE
    try: old = json.loads( path.read_text() )
    except ( OSError, ValueError ): old = {}
    doc = { "schema": SCHEMA, "crontab": crontab_text( run ), "crontab_at": now.isoformat(), "zone": host_zone_name(), "units": old.get( "units" ), "units_at": old.get( "units_at" ) }
    if units is not None: doc.update( units={ u: unit_state( u, run ) for u in units }, units_at=now.isoformat() )
    write_atomic( path, doc )
    return doc


def refresh_best_effort( environ=None, now=None, run=None ):
    """
    Refresh the crontab part from a host job's own run.

    Ensures:
        - never raises and never fails the job: any problem finding the data folder or writing the file is ignored
        - does nothing in a process with no crontab command (the container)
    """
    run = subprocess.run if run is None else run
    environ = os.environ if environ is None else environ
    try:
        from cosa.repo.symindex.paths import data_dir
        data = environ.get( "LUPIN_REUSE_REVIEW_DATA_ROOT" ) or data_dir( environ.get( "LUPIN_ROOT" ) or os.getcwd() )
        write_snapshot( data, now or datetime.datetime.now().astimezone(), None, run )
    except Exception:                                                  # a snapshot is a convenience for the reader; it must never fail a job
        return False
    return True


CRON_TAG      = "# job-host-snapshot"
CRON_SCHEDULE = "*/5 * * * *"
LOCK_OWNER    = "job-host-snapshot"
CARRIED       = ( "DEEPILY_DATA_DIR", "LUPIN_CONFIG_MGR_CLI_ARGS", "LUPIN_REUSE_REVIEW_DATA_ROOT" )
DEFAULT_CLI   = "config_path=/src/conf/lupin-app.ini splainer_path=/src/conf/lupin-app-splainer.ini config_block_id=Lupin:+Development"


def cron_line( root, python, log_path, environ ):
    """
    Build the one cron line of the snapshot tick.

    Requires:
        - root is the main checkout; python is the interpreter; log_path is the file the line appends to
    Ensures:
        - returns one line that runs every five minutes from root with LUPIN_ROOT, PYTHONPATH, LUPIN_CONFIG_MGR_CLI_ARGS and DEEPILY_DATA_DIR set
        - the two settings come from environ, shell-quoted; the config arguments default to the Development block when environ has none
        - the line ends with CRON_TAG
    """
    carried = { "LUPIN_CONFIG_MGR_CLI_ARGS": environ.get( "LUPIN_CONFIG_MGR_CLI_ARGS" ) or DEFAULT_CLI }
    carried.update( { n: environ[ n ] for n in CARRIED if environ.get( n ) and n != "LUPIN_CONFIG_MGR_CLI_ARGS" } )
    extra = "".join( f"{name}={shlex.quote( value )} " for name, value in carried.items() )
    return f"{CRON_SCHEDULE} cd {root} && LUPIN_ROOT={root} PYTHONPATH={root}/src {extra}{python} -m lupin_mcp.host_snapshot >> {log_path} 2>&1 {CRON_TAG}"


def install_mode( args, environ, now, out, err, crontab_cmd ):
    """
    Print, install, remove or report the cron line.

    Requires:
        - args holds root, python and one of print_install, install, uninstall, status
    Ensures:
        - --print-install prints the line and changes nothing
        - --uninstall goes through the librarian's locked crontab editor with this job's tag and owner, after a timestamped backup; --install is retired: it prints where the installer went on err and returns 1
        - --status says whether the line is present
        - returns 0, or 1 with the reason on err when the install is refused or the crontab call fails
    """
    from cosa.repo.symindex import librarian_tick as lt
    root = args.root or environ.get( "LUPIN_ROOT" ) or os.getcwd()
    cmd  = crontab_cmd or lt.crontab_command( environ )
    logs = f"{root}/io/jobs"
    if args.install:
        err( lt.install_moved_text( root ) )
        return 1
    try:
        if args.status:
            read = subprocess.run( [ *cmd, "-l" ], capture_output=True, text=True )
            out( lt.status_text( read.stdout if read.returncode == 0 else "", CRON_TAG, 1 ) )
            return 0
        if args.uninstall:
            lt.edit_crontab( [], environ, cmd, f"{logs}/crontab-backups", now, tag=CRON_TAG, owner=LOCK_OWNER )
            out( "uninstalled" )
            return 0
        out( cron_line( root, args.python, f"{logs}/host-snapshot.log", environ ) )    # the one mode left is --print-install
        return 0
    except ( lt.InstallRefused, RuntimeError ) as error:
        err( f"job-host-snapshot: {error}" )
        return 1


def main( argv=None, environ=None, now=None, run=None, out=print, err=None, crontab_cmd=None ):
    """
    Write the snapshot, or manage its cron line.

    Requires:
        - argv is a list of arguments or None for sys.argv

    Ensures:
        - with no verb, reads the registry under LUPIN_ROOT for the unit names, writes crontab, zone and units, and returns 0
        - --print-install, --install, --uninstall and --status work on the cron line instead
    """
    import argparse
    environ = os.environ if environ is None else environ
    parser  = argparse.ArgumentParser( prog="python -m lupin_mcp.host_snapshot", description="Write the host snapshot for the jobs reader." )
    mode    = parser.add_mutually_exclusive_group()
    for flag in ( "--install", "--uninstall", "--status", "--print-install" ): mode.add_argument( flag, action="store_true" )
    parser.add_argument( "--root" )
    parser.add_argument( "--python", default=sys.executable )
    args    = parser.parse_args( argv )
    now     = now or datetime.datetime.now().astimezone()
    if args.install or args.uninstall or args.status or args.print_install:
        return install_mode( args, environ, now, out, err or ( lambda line: print( line, file=sys.stderr ) ), crontab_cmd )
    from cosa.rest.job_registry import load_registry
    from cosa.repo.symindex.paths import data_dir
    run     = subprocess.run if run is None else run
    root    = args.root or environ.get( "LUPIN_ROOT" ) or os.getcwd()
    data    = environ.get( "LUPIN_REUSE_REVIEW_DATA_ROOT" ) or data_dir( root )
    write_snapshot( data, now, registry_units( load_registry( root ) ), run )
    return 0


if __name__ == "__main__":  # pragma: no cover - process entry point
    sys.exit( main() )
