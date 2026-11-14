"""
The on/off switch of each scheduled job: where it lives, how it is read and written.

Each job in `src/conf/job-registry.json` has one key in the main configuration file,
`cron job <job> enabled`. The job reads it at its next start (lupin_mcp.job_run). This module
reads the key fresh from disk on every call, because the configuration manager is a
process-lifetime singleton and would keep a stale value.

`write_switch` is the only function in source that writes one of these keys. The router
`cosa.rest.routers.cron_jobs` is its only caller, and a census test in the unit tier fails on
any other writer.

A small attribution file beside the write lock records who flipped each switch and when. It
holds attribution only; the switch itself is the key in the configuration file.
"""
import datetime
import json
import os

from typing import Any, Dict, List, Optional

from cosa.rest.job_cron import entry_label
from cosa.utils import atomic_json
from lupin_mcp import config_write_lock, fleet_cap_ini_io, fleet_size_cap

KEY_TEMPLATE      = "cron job {job} enabled"
INI_OVERRIDE_ENV  = "LUPIN_CRON_SWITCH_INI"
STATE_FILENAME    = "cron-job-switches-state.json"
EVENT_NAME        = "cron_job_switch_changed"


def switch_key( job: str ) -> str:
    """
    The configuration key that holds one job's switch.

    Requires:
        - job is a registry job id

    Ensures:
        - returns `cron job <job> enabled`
    """
    return KEY_TEMPLATE.format( job=job )


def ini_path() -> str:
    """
    The configuration file the switches are read from and written to.

    Ensures:
        - returns the env override when it is set, so tests never touch the live file
        - otherwise returns the main checkout's file, the one the cron jobs read, so a seat in a
          worktree never reads or edits its own tracked copy
    """
    override = os.environ.get( INI_OVERRIDE_ENV )
    if override:
        return override
    return fleet_size_cap.main_checkout_ini_path()


def state_path() -> str:
    """
    The file that records who flipped each switch and when.

    Ensures:
        - sits beside the override file when the file is overridden, so a test never rewrites the real record
        - otherwise lives in the folder that holds the write lock
    """
    override = os.environ.get( INI_OVERRIDE_ENV )
    if override:
        return f"{override}.cron-state.json"
    return os.path.join( config_write_lock.lock_dir(), STATE_FILENAME )


def read_enabled( job: str ) -> Optional[ bool ]:
    """
    Read one job's switch fresh from the configuration file.

    Requires:
        - job is a registry job id

    Ensures:
        - returns True or False for a value that is true or false, in any case
        - returns None when the key is absent, defined twice, unreadable, or holds anything else.
          The row then shows the switch as unknown, never as on
        - never raises
    """
    raw = fleet_cap_ini_io.read_value_from_disk( ini_path(), switch_key( job ) )
    if raw is None:
        return None
    lowered = raw.strip().lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    return None


def read_attribution() -> Dict[ str, Any ]:
    """
    The record of who flipped which switch.

    Ensures:
        - returns { job: { "on", "at", "by" } }
        - returns {} when the file is missing, is not valid JSON, or is not an object
        - never raises
    """
    return atomic_json.load_json_dict( state_path() )


def _write_attribution( job: str, on: bool, who: str, moment: datetime.datetime ) -> None:
    """
    Replace the attribution file with one more entry.

    Ensures:
        - the file is replaced atomically, holding every earlier job's entry too

    Raises:
        - OSError when the folder or the file cannot be written
    """
    record      = read_attribution()
    record[ job ] = { "on": bool( on ), "at": moment.astimezone().isoformat(), "by": who }
    path        = state_path()
    os.makedirs( os.path.dirname( path ), exist_ok=True )
    partial = path + ".partial"
    with open( partial, "w", encoding="utf-8" ) as handle:
        json.dump( record, handle )
        handle.flush()
        os.fsync( handle.fileno() )
    os.replace( partial, path )


def write_switch( job: str, on: bool, who: str, now: Optional[ datetime.datetime ] = None ) -> None:
    """
    Flip one job's switch. The only writer of a `cron job <job> enabled` key.

    Requires:
        - job is a registry job id the caller has already checked
        - who is the administrator's email or user id

    Ensures:
        - the key is located before anything is written, so a key the file lacks or defines twice
          is refused with nothing written: the record file is left as it was
        - then the attribution record is written and the configuration file second, so a failed
          second write (an OS error) leaves a record that disagrees with the file
        - the key is never inserted: a key the file lacks is refused, not invented

    Raises:
        - fleet_cap_ini_io.KeyNotFound when the file has no such key
        - fleet_cap_ini_io.KeyDefinedTwice when the file defines it twice
        - OSError when either file cannot be written
    """
    moment = now if now is not None else datetime.datetime.now( datetime.timezone.utc )
    fleet_cap_ini_io.locate_key( ini_path(), switch_key( job ) )
    _write_attribution( job, on, who, moment )
    fleet_cap_ini_io.write_bool_to_disk( ini_path(), switch_key( job ), on )


def is_honoured( entry: Dict[ str, Any ] ) -> bool:
    """
    Whether the job reads its switch at run time.

    Requires:
        - entry is a registry job

    Ensures:
        - returns True only for a job with `cron_managed` true, the jobs that run through
          lupin_mcp.job_run, which is the one reader of the switch
        - returns False for every other job: its switch would change a line nothing reads
    """
    return entry.get( "cron_managed" ) is True


def build_row( entry: Dict[ str, Any ], attribution: Dict[ str, Any ] ) -> Dict[ str, Any ]:
    """
    One row for the accordion, with the switch read fresh from the file.

    Requires:
        - entry is a registry job
        - attribution is what `read_attribution` returned

    Ensures:
        - returns { job, title, schedule, key, enabled, honoured, drift, last_changed_by, last_changed_at }
        - enabled is True, False, or None when the file does not say
        - honoured is computed from the registry (`cron_managed` true: the job runs through
          lupin_mcp.job_run, the one reader of the switch), never typed by hand
        - drift is true only when enabled is known, a record exists and the record disagrees with
          the file: the file was edited outside the endpoint. A job never flipped has drift false
        - the attribution is shown only when it agrees with the file; a record that disagrees
          (the file was edited by hand) shows as unknown rather than naming the wrong person
    """
    job     = entry[ "job" ]
    enabled = read_enabled( job )
    noted   = attribution.get( job )
    known   = isinstance( noted, dict ) and enabled is not None
    agrees  = known and noted.get( "on" ) is enabled
    return {
        "job"             : job,
        "title"           : entry[ "title" ],
        "schedule"        : "; ".join( entry_label( e ) for e in entry.get( "schedule", [] ) ) or "not scheduled",
        "key"             : switch_key( job ),
        "enabled"         : enabled,
        "honoured"        : is_honoured( entry ),
        "drift"           : known and not agrees,
        "last_changed_by" : noted.get( "by" ) if agrees else None,
        "last_changed_at" : noted.get( "at" ) if agrees else None,
    }


def build_rows( registry_jobs: List[ Dict[ str, Any ] ] ) -> List[ Dict[ str, Any ] ]:
    """
    A row per registry job, in registry order.

    Requires:
        - registry_jobs is the `jobs` list `load_registry` returns

    Ensures:
        - reads the attribution file once and every switch fresh from the configuration file
    """
    attribution = read_attribution()
    return [ build_row( entry, attribution ) for entry in registry_jobs ]
