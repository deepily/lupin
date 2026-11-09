"""
The job registry, and the run-time overrides of two of its numbers.

`src/conf/job-registry.json` is edited by a person in a reviewed commit. A job that is dead cannot rewrite its own
promise, so "missed" is measured against this file. The notification interval and the grace period of each job
can be changed without a code change or a restart. A small overrides file is read on every request and wins
over the registry. Design: planning-is-prompting src/rnd/2026.11.07-background-job-reporting-format.md sections 1.2, 11.1, 12.4.
"""
import json
import pathlib
import re

REGISTRY_SCHEMA  = "job-registry/1"
REGISTRY_FILE    = "src/conf/job-registry.json"
OVERRIDES_FILE   = "io/jobs/registry-overrides.json"
TUNABLE          = ( "grace_minutes", "notify_interval_minutes" )
SCHEDULE_KEYS    = ( "cron", "after_boot_seconds", "every_seconds" )
PERSONA_OWNER    = re.compile( r"^[a-z][a-z0-9-]*$" )                  # a seat name or "rick", never a role label such as "manager on duty"


def load_registry( root ):
    """
    Read the registry and check its shape.

    Requires:
        - root is the Lupin root; REGISTRY_FILE sits under it
    Ensures:
        - returns { "defaults": {...}, "jobs": [...] }
        - every owner is a lowercase seat name (a role label is refused: its rows are invisible)
        - every job has a unique job id (with its target when it has one), a title, an owner, and schedule entries that each hold exactly one of cron, after_boot_seconds, every_seconds
        - a job's reporting field, when present, is "on" or "off", and "off" comes with a non-blank reporting_off_reason
    Raises:
        - ValueError when the file is not a job-registry/1 document or a job breaks those rules
        - OSError when the file cannot be read
    """
    doc = json.loads( ( pathlib.Path( root ) / REGISTRY_FILE ).read_text() )
    if doc.get( "schema" ) != REGISTRY_SCHEMA: raise ValueError( f"registry schema must be {REGISTRY_SCHEMA}" )
    seen = set()
    for job in doc[ "jobs" ]:
        for key in ( "job", "title", "owner" ):
            if not job.get( key ): raise ValueError( f"registry job {job.get( 'job' )!r} lacks {key}" )
        if job[ "job" ] in seen: raise ValueError( f"registry lists job {job[ 'job' ]!r} twice" )
        if not PERSONA_OWNER.match( job[ "owner" ] ): raise ValueError( f"job {job[ 'job' ]}: owner {job[ 'owner' ]!r} is not a seat name" )
        seen.add( job[ "job" ] )
        if job.get( "reporting", "on" ) not in ( "on", "off" ): raise ValueError( f"job {job[ 'job' ]}: reporting must be \"on\" or \"off\", not {job[ 'reporting' ]!r}" )
        if job.get( "reporting" ) == "off" and not str( job.get( "reporting_off_reason", "" ) ).strip(): raise ValueError( f"job {job[ 'job' ]}: reporting off needs a reporting_off_reason" )
        for entry in job.get( "schedule", [] ):
            if sum( key in entry for key in SCHEDULE_KEYS ) != 1: raise ValueError( f"job {job[ 'job' ]}: a schedule entry needs exactly one of {SCHEDULE_KEYS}" )
    return { "defaults": doc[ "defaults" ], "jobs": doc[ "jobs" ] }


def reporting_on( job ):
    """
    Say whether a job shows in the Background Jobs list.

    Requires:
        - job is a registry entry
    Ensures:
        - returns False only when the entry says "reporting": "off"; a missing field means on
        - switching reporting off hides the job from the list and the counts; it does not stop the job
    """
    return job.get( "reporting", "on" ) != "off"


def load_overrides( root ):
    """
    Read the run-time overrides.

    Requires:
        - root is the Lupin root
    Ensures:
        - returns { job id: { grace_minutes?, notify_interval_minutes? } } holding only positive numbers for known tunables
        - returns {} when the file is missing or unreadable: no override is the normal state
        - an entry that is not a dict, an unknown key, or a non-positive or non-numeric value is ignored, so one bad edit cannot take the page down
    """
    try:
        doc = json.loads( ( pathlib.Path( root ) / OVERRIDES_FILE ).read_text() )
    except ( OSError, ValueError ):
        return {}
    if not isinstance( doc, dict ): return {}
    clean = {}
    for job, values in doc.items():
        if not isinstance( values, dict ): continue
        good = { k: v for k, v in values.items() if k in TUNABLE and isinstance( v, ( int, float ) ) and not isinstance( v, bool ) and v > 0 }
        if good: clean[ job ] = good
    return clean


def effective( job, defaults, overrides ):
    """
    Resolve one job's settings: override, then registry entry, then defaults.

    Requires:
        - job is a registry entry; defaults and overrides come from load_registry and load_overrides
    Ensures:
        - returns a copy of job with grace_minutes and notify_interval_minutes always set
        - a job with grace_seconds keeps it (the interval-job addition); the reader prefers it over grace_minutes
    """
    out = dict( job )
    for key in TUNABLE:
        out[ key ] = overrides.get( job[ "job" ], {} ).get( key, job.get( key, defaults[ key ] ) )
    return out


def crontab_schedule( text, tag ):
    """
    Read a job's schedule off the installed crontab.

    Requires:
        - text is the output of crontab -l; tag is the marker comment a job's lines end with
    Ensures:
        - returns one entry per line that ends with "# <tag>": { cron } for a five-field line, { after_boot_seconds } for an @reboot line (its leading sleep, else 0)
        - returns [] when no line carries the tag, so the caller falls back to the registry
        - a commented-out line and a line that merely mentions the tag are ignored
    """
    out = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith( "#" ) or not line.endswith( f"# {tag}" ): continue
        if line.startswith( "@reboot" ):
            m = re.match( r"@reboot\s+sleep\s+(\d+)\b", line )
            out.append( { "after_boot_seconds": int( m.group( 1 ) ) if m else 0 } )
        else:
            fields = line.split( None, 5 )
            if len( fields ) == 6: out.append( { "cron": " ".join( fields[ :5 ] ) } )
    return out


def with_installed_schedule( job, crontab_text ):
    """
    Replace a tagged job's schedule with the installed one.

    Requires:
        - job is an effective registry entry; crontab_text is the crontab, or None when it could not be read
    Ensures:
        - returns job unchanged when it has no cron_tag
        - a tagged job whose crontab is unreadable or has no line with its tag keeps the registry schedule and gets schedule_unverified true
        - otherwise returns a copy whose schedule is the installed lines and schedule_unverified false
    """
    if not job.get( "cron_tag" ): return job
    installed = [] if crontab_text is None else crontab_schedule( crontab_text, job[ "cron_tag" ] )
    return { **job, "schedule": installed, "schedule_unverified": False } if installed else { **job, "schedule_unverified": True }


def resolve_path( template, root, data ):
    """
    Turn a registry path into a real one.

    Requires:
        - template may start with {root} (the Lupin root) or {data} (the reuse-review data folder)
    Ensures:
        - returns a pathlib.Path; a template with neither prefix is taken as relative to root
    """
    if template.startswith( "{data}" ): return pathlib.Path( data ) / template[ 7: ]
    if template.startswith( "{root}" ): return pathlib.Path( root ) / template[ 7: ]
    return pathlib.Path( root ) / template
