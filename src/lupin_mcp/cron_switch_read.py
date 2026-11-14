"""
The one parse rule for a scheduled job's on/off switch, shared by every reader.

Each job has one key in the main configuration file, `cron job <job> enabled`. Three places read
it: the cron wrapper (`lupin_mcp.job_run`), the accordion (`cosa.rest.cron_job_switches`) and, one by
one, the in-process loops. They must agree on every value, so they all call `parse_switch`.
A value is on when it is `true`, off when it is `false`, in any case, and unknown otherwise.
Words such as `yes` or `1` are unknown here, never on and never off.

The module imports only the standard library and `fleet_cap_ini_io`, so the standalone arbiter,
which runs in a light virtual environment, can import it.
"""
from typing import Optional

from lupin_mcp import fleet_cap_ini_io

KEY_TEMPLATE = "cron job {job} enabled"


def switch_key( job: str ) -> str:
    """
    The configuration key that holds one job's switch.

    Requires:
        - job is a registry job id

    Ensures:
        - returns `cron job <job> enabled`
    """
    return KEY_TEMPLATE.format( job=job )


def parse_switch( raw ) -> Optional[ bool ]:
    """
    Read a switch value as on, off or unknown.

    Requires:
        - raw is whatever a reader found for the key: a string, or None when it found nothing

    Ensures:
        - returns True for `true` and False for `false`, in any case and with spaces around
        - returns None for anything else: None, a blank value, `yes`, `1` or a non-string
        - never raises
    """
    if not isinstance( raw, str ):
        return None
    lowered = raw.strip().lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    return None


def read_switch( ini_path: str, job: str ) -> Optional[ bool ]:
    """
    Read one job's switch fresh from a configuration file on disk.

    Requires:
        - ini_path names the configuration file to read
        - job is a registry job id

    Ensures:
        - returns True or False for a value `parse_switch` accepts
        - returns None when the key is absent, defined twice, unreadable or holds anything else
        - never raises
    """
    return parse_switch( fleet_cap_ini_io.read_value_from_disk( ini_path, switch_key( job ) ) )
