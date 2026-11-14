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
import argparse
import os
import sys
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


class TickSwitch:
    """
    The check a long-running loop makes at the start of every tick.

    A loop builds one TickSwitch for its job and calls `allowed()` before each tick's work.
    The key is read fresh from disk every time, so flipping it takes effect on the next tick
    with no restart. The loop itself never stops: a skipped tick still sleeps.
    """

    def __init__( self, job, ini_path_fn, summary_path_fn=None, log=print ):
        """
        Remember which job this is and where its switch and summary live.

        Requires:
            - job is a registry job id
            - ini_path_fn is a zero-argument callable that returns the configuration file's path
            - summary_path_fn is a zero-argument callable that returns the job's summary path, or None
              for a job with no summary
            - log takes one string

        Ensures:
            - nothing is read until the first `allowed()` call
        """
        self.job             = job
        self.ini_path_fn     = ini_path_fn
        self.summary_path_fn = summary_path_fn
        self.log             = log
        self.last            = "unread"

    def allowed( self, now=None ) -> bool:
        """
        Read the switch and say whether this tick may do its work.

        Requires:
            - now is a datetime for the summary's time stamp, or None for the current time

        Ensures:
            - returns True when the key reads `true`, and False when it reads `false`
            - returns False when the key is absent, defined twice, unreadable or holds another word;
              there is no default in code. Each such tick also writes the job's summary with
              outcome failed and the key name as evidence, when the job has a summary
            - logs one line each time the answer changes (on, off or unreadable), so a loop that
              stays off for a day writes one line, not one per tick
            - never raises: a failure to write the summary is reported on the log
        """
        key   = switch_key( self.job )
        value = read_switch( self.ini_path_fn(), self.job )
        state = { True: "on", False: "off", None: "unreadable" }[ value ]
        if state != self.last:
            if state == "on" and self.last != "unread": self.log( f"{self.job}: INI key '{key}' is true, so ticks run again" )
            if state == "off": self.log( f"{self.job}: INI key '{key}' is false, so ticks skip their work until it is true" )
            if state == "unreadable": self.log( f"{self.job}: ERROR: INI key '{key}' is missing or holds neither true nor false, so ticks skip their work" )
            self.last = state
        if state == "unreadable": self._write_failed_summary( key, now )
        return value is True

    def _write_failed_summary( self, key, now ):
        """
        Record an unreadable switch where the jobs page and the job's own summary show it.

        Requires:
            - key is this job's switch key

        Ensures:
            - writes the summary with outcome failed, stage switch and the key name as evidence,
              when summary_path_fn is set
            - logs the error and returns when the write fails or the summary module cannot load
        """
        if self.summary_path_fn is None: return
        try:
            from lupin_mcp import job_summary as js
            stamp   = js.iso_now( now )
            attempt = { "started_at": stamp, "finished_at": stamp, "trigger": "cron", "outcome": "failed", "stage": "switch",
                        "failure": "switch unreadable", "evidence": f"INI key '{key}' is missing or holds neither true nor false", "mode": "in-process tick" }
            js.write_summary( self.summary_path_fn(), self.job, attempt, now=now )
        except ( ImportError, OSError, ValueError ) as error:
            self.log( f"{self.job}: could not write the failed summary: {error}" )


def summary_path_in( root, job ) -> str:
    """
    Where a job's summary lives under a checkout, as the registry writes it.

    Requires:
        - root is a checkout's root folder
        - job is a registry job id whose `summary_path` is `{root}/io/jobs/<job>/job-summary.json`

    Ensures:
        - returns `<root>/io/jobs/<job>/job-summary.json`; the census test pins every switch
          reader's registry entry to this shape
    """
    return os.path.join( str( root ), "io", "jobs", job, "job-summary.json" )


def for_job( job, log=print ):
    """
    The TickSwitch a production loop uses: the main checkout's configuration file and summary.

    Requires:
        - job is a registry job id
        - log takes one string

    Ensures:
        - returns a TickSwitch that reads the main checkout's `src/conf/lupin-app.ini` at every
          tick, so a seat's worktree copy is never read, and writes failures to the job's summary
          in that checkout's `io/jobs/<job>/`
        - imports the path helpers only when called, so this module stays light to import
    """
    import cosa.utils.util as cu
    from lupin_mcp import fleet_size_cap
    from lupin_cli.claude_code.hooks.lib.heartbeat_hold import _main_repo_path
    return TickSwitch( job, fleet_size_cap.main_checkout_ini_path, lambda: summary_path_in( _main_repo_path( cu.get_project_root() ), job ), log )


def main( argv=None ):
    """
    Check one job's switch from the command line, for a service outside this tree's Python.

    Requires:
        - argv holds --job, --ini (the configuration file) and --root (the checkout whose io/jobs holds the summary)

    Ensures:
        - prints one word on stdout: on, off or unknown, where unknown means the key is missing or holds neither true nor false
        - the log lines go to stderr, so stdout stays one word
        - an unknown answer writes the job's failed summary, as every in-process loop does
        - returns 0 for every answer
    """
    parser = argparse.ArgumentParser( description="Print on, off or unknown for one job's switch." )
    parser.add_argument( "--job", required=True )
    parser.add_argument( "--ini", required=True )
    parser.add_argument( "--root", required=True )
    args   = parser.parse_args( argv )
    switch = TickSwitch( args.job, lambda: args.ini, lambda: summary_path_in( args.root, args.job ), log=lambda line: print( line, file=sys.stderr ) )
    switch.allowed()
    print( { "on": "on", "off": "off", "unreadable": "unknown" }[ switch.last ] )
    return 0


if __name__ == "__main__":  # pragma: no cover - process entry point
    sys.exit( main() )
