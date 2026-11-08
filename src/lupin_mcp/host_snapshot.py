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
import subprocess
import sys
import urllib.request

from lupin_mcp.job_summary import write_atomic

SCHEMA          = "host-snapshot/1"
SNAPSHOT_FILE   = "job-host-snapshot.json"                             # in the reuse-review data folder, which the container mounts
CRONTAB_MAX_AGE = 36 * 3600                                           # the crontab changes rarely; every host job run refreshes it
UNITS_MAX_AGE   = 1800                                                # a host tick refreshes the units every five minutes


def crontab_text( run=None ):
    """
    Read the installed crontab.

    Ensures:
        - returns the text of crontab -l, or None when it cannot be run or answers an error (no crontab included)
    """
    run = subprocess.run if run is None else run
    try:
        done = run( [ "crontab", "-l" ], capture_output=True, text=True, timeout=10 )
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
        - returns { crontab, units } where each part is None when its time is missing or past its limit
        - returns { crontab: None, units: None } when the file is missing, unreadable or of another schema
        - a crontab that was unreadable when written reads as None too
    """
    empty = { "crontab": None, "units": None }
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
             "units": doc.get( "units" ) if fresh( "units_at", UNITS_MAX_AGE ) else None }


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
    doc = { "schema": SCHEMA, "crontab": crontab_text( run ), "crontab_at": now.isoformat(), "units": old.get( "units" ), "units_at": old.get( "units_at" ) }
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


def main( argv=None, environ=None, now=None, run=None ):
    """
    Write the whole snapshot from the command line.

    A host cron line runs it every five minutes.

    Ensures:
        - reads the registry under LUPIN_ROOT for the unit names, writes crontab and units, returns 0
    """
    run = subprocess.run if run is None else run
    from cosa.rest.job_registry import load_registry
    from cosa.repo.symindex.paths import data_dir
    environ = os.environ if environ is None else environ
    root    = environ.get( "LUPIN_ROOT" ) or os.getcwd()
    data    = environ.get( "LUPIN_REUSE_REVIEW_DATA_ROOT" ) or data_dir( root )
    write_snapshot( data, now or datetime.datetime.now().astimezone(), registry_units( load_registry( root ) ), run )
    return 0


if __name__ == "__main__":  # pragma: no cover - process entry point
    sys.exit( main() )
