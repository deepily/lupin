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
        for entry in job.get( "schedule", [] ):
            if sum( key in entry for key in SCHEDULE_KEYS ) != 1: raise ValueError( f"job {job[ 'job' ]}: a schedule entry needs exactly one of {SCHEDULE_KEYS}" )
    return { "defaults": doc[ "defaults" ], "jobs": doc[ "jobs" ] }


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
