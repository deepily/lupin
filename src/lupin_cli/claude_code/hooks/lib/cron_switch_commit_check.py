#!/usr/bin/env python3
"""
Refuse a commit that changes a cron job switch unless the endpoint recorded that change.

Each `cron job <job> enabled` line in `lupin-app.ini` is a switch Rick flips through the
scheduled-jobs accordion. The endpoint writes the line and records the new value, who flipped it,
and when, in `cron-job-switches-state.json`. Seats commit `lupin-app.ini` after Rick flips a
switch, so a commit that changes a switch line is normal. A commit whose new value differs from
the record is a hand edit, and this check refuses it.

The rule, for every staged file named `lupin-app.ini`, comparing HEAD with the index:

  - a switch whose value changed passes only when the record for that job holds the new value
  - a switch that was removed, or that the index holds twice, is refused
  - a switch the index holds with a value other than true or false is refused
  - a switch that is new in this commit passes only under three conditions. The job is listed in
    the registry (`src/conf/job-registry.json`, as staged, else as in HEAD). The line is the
    job's only one. The record holds no different value for the job. So the one-time creation
    of a registry job's key passes, and a line for an unlisted job is refused
  - a commit that changes no switch line passes, whatever else it changes in the file

The record is read from `LUPIN_CRON_SWITCH_STATE` when that is set, which tests use, and
otherwise from the folder that holds the configuration write lock. A missing or unreadable record
counts as empty, so every changed switch is refused.

`cron_switch_guard` is the control before this one, at the tool call. This one also covers a
commit that no tool call made, such as a script or a terminal outside Claude Code.

There is no escape hatch. `git commit --no-verify` skips every pre-commit gate and is out of scope.

Run from `src/scripts/pre-commit-chain.sh`. Exit 0 allows the commit and exit 3 refuses it.
Any internal error prints a loud line and exits 0.
The hook is shared by every worktree, and a gate that crashes must not stop every seat.
"""
import argparse
import json
import os
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple

from lupin_cli.claude_code.hooks.lib.cron_switch_guard import INI_BASENAME, switch_lines

STATE_ENV      = "LUPIN_CRON_SWITCH_STATE"
STATE_FILENAME = "cron-job-switches-state.json"

REGISTRY_PATH = "src/conf/job-registry.json"

EXIT_ALLOW  = 0
EXIT_REFUSE = 3

_PREFIX = "[cron-switch-check]"


def state_path( env=None ) -> str:
    """
    The file that records who flipped each switch.

    Ensures:
        - returns the env override when it is set
        - otherwise returns the record's file in the folder that holds the configuration write lock
    """
    env      = env if env is not None else os.environ
    override = env.get( STATE_ENV )
    if override:
        return override
    from lupin_mcp import config_write_lock
    return os.path.join( config_write_lock.lock_dir(), STATE_FILENAME )


def read_state( path ) -> Dict[ str, Any ]:
    """
    The switch record: { job: { "on", "at", "by" } }.

    Ensures:
        - returns {} when the file is missing, is not valid JSON, or is not an object
        - never raises
    """
    try:
        with open( path, "r", encoding="utf-8" ) as handle:
            record = json.load( handle )
    except ( OSError, ValueError ):
        return {}
    return record if isinstance( record, dict ) else {}


def _git( repo_root, *args ) -> Tuple[ int, str ]:
    """Run git in repo_root and return ( exit code, stdout )."""
    done = subprocess.run(
        [ "git", "-C", repo_root, *args ], capture_output=True, text=True, check=False,
    )
    return done.returncode, done.stdout


def staged_ini_paths( repo_root ) -> List[ str ]:
    """
    The staged paths named lupin-app.ini, in any folder.

    Ensures:
        - returns the paths, relative to repo_root, that differ between HEAD and the index
        - includes added, deleted, modified and renamed paths
    """
    code, out = _git( repo_root, "diff", "--cached", "--name-only", "-z", "--no-renames" )
    if code != 0:
        raise RuntimeError( f"git diff --cached failed with exit {code}" )
    return [ path for path in out.split( "\0" ) if path and os.path.basename( path ) == INI_BASENAME ]


def _blob_text( repo_root, spec ) -> str:
    """The text of a blob such as `HEAD:<path>` or `:<path>`, or "" when it does not exist."""
    code, out = _git( repo_root, "show", spec )
    return out if code == 0 else ""


def _as_bool( value ) -> Optional[ bool ]:
    """True or False for a value that is true or false in any case, otherwise None."""
    if value == "true":
        return True
    if value == "false":
        return False
    return None


def registry_job_ids( repo_root ) -> Optional[ set ]:
    """
    The job ids the registry lists, as staged, else as in HEAD.

    Ensures:
        - returns None when neither blob holds a readable registry, so a new switch is then refused
        - never raises
    """
    for spec in ( f":{REGISTRY_PATH}", f"HEAD:{REGISTRY_PATH}" ):
        text = _blob_text( repo_root, spec )
        if not text:
            continue
        try:
            jobs = json.loads( text )[ "jobs" ]
            return { entry[ "job" ] for entry in jobs }
        except ( ValueError, KeyError, TypeError ):
            continue
    return None


def violations_for( before, after, record, registry=None ) -> List[ str ]:
    """
    One line per switch change in a file that the record does not account for.

    Requires:
        - before is the HEAD text and after is the index text of one lupin-app.ini
        - record is the switch record, { job: { "on": bool, ... } }
        - registry is the set of job ids the registry lists, or None when it could not be read

    Ensures:
        - returns [] when every changed switch matches the record, or no switch changed
        - each line names the job, the change, and what the record says
    """
    old      = switch_lines( before )
    new      = switch_lines( after )
    problems = []
    for job in sorted( set( old ) | set( new ) ):
        if old.get( job ) == new.get( job ):
            continue
        if job not in new:
            problems.append( f"{job}: the switch line was removed" )
            continue
        values = new[ job ]
        if len( values ) != 1:
            problems.append( f"{job}: the switch is defined {len( values )} times" )
            continue
        value = _as_bool( values[ 0 ] )
        if value is None:
            problems.append( f"{job}: the value {values[ 0 ]!r} is neither true nor false" )
            continue
        noted = record.get( job )
        if job not in old:
            if registry is None or job not in registry:
                problems.append( f"{job}: a new switch line for a job the registry does not list" )
            elif isinstance( noted, dict ) and isinstance( noted.get( "on" ), bool ) and noted[ "on" ] is not value:
                problems.append( f"{job}: a new switch line set to {values[ 0 ]}, but the record says {noted[ 'on' ]}" )
            continue
        if not isinstance( noted, dict ) or not isinstance( noted.get( "on" ), bool ):
            problems.append( f"{job}: set to {values[ 0 ]}, but the endpoint has no record of a flip" )
            continue
        if noted[ "on" ] is not value:
            said = "true" if noted[ "on" ] else "false"
            problems.append(
                f"{job}: set to {values[ 0 ]}, but the last flip through the endpoint set it to {said}"
                f" ({noted.get( 'by', 'unknown' )}, {noted.get( 'at', 'unknown time' )})"
            )
    return problems


def check( repo_root, env=None ) -> Tuple[ int, str ]:
    """
    Decide whether the staged commit in repo_root may proceed.

    Requires:
        - repo_root is the top of a git work tree

    Ensures:
        - returns ( EXIT_ALLOW, "" ) when no staged lupin-app.ini changes a switch off the record
        - returns ( EXIT_REFUSE, <message> ) naming each refused switch and what to do instead

    Raises:
        - RuntimeError when git cannot list the staged paths
    """
    env    = env if env is not None else os.environ
    paths  = staged_ini_paths( repo_root )
    if not paths:
        return EXIT_ALLOW, ""
    record   = read_state( state_path( env ) )
    registry = registry_job_ids( repo_root )
    found    = []
    for path in paths:
        problems = violations_for( _blob_text( repo_root, f"HEAD:{path}" ), _blob_text( repo_root, f":{path}" ), record, registry )
        found.extend( f"  {path}  {line}" for line in problems )
    if not found:
        return EXIT_ALLOW, ""
    message = (
        f"{_PREFIX} REFUSED: this commit changes a cron job switch that the endpoint did not record.\n"
        + "\n".join( found )
        + "\nRick flips switches in the scheduled-jobs accordion, which writes the line and the record together."
        "\nTo drop the change: git restore --staged --worktree -- <path>, then re-stage your other edits to the file."
        "\nIf the switch should change, ask Rick to flip it, then commit the file."
    )
    return EXIT_REFUSE, message


def main( argv=None ) -> int:
    """
    Command-line entry for the pre-commit chain.

    Ensures:
        - prints any message to stderr and returns its exit code
        - an internal error prints a loud line and returns EXIT_ALLOW, saying nothing was enforced
    """
    parser = argparse.ArgumentParser( description="Refuse a commit that changes a cron job switch off the record." )
    parser.add_argument( "--repo-root", required=True )
    args = parser.parse_args( argv )
    try:
        code, message = check( args.repo_root )
    except Exception as error:
        print( f"{_PREFIX} ERROR, commit ALLOWED, the switch check was NOT enforced: {error}", file=sys.stderr )
        return EXIT_ALLOW
    if message:
        print( message, file=sys.stderr )
    return code


if __name__ == "__main__":
    sys.exit( main() )
