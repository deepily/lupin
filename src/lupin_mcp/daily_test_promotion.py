"""
Promote the newest merged build to the cloud test VM once a day, then smoke it.

One run goes in this order. It picks the head of the working branch. A stored last-promoted sha equal to the
pick ends the run with no VM contact. Otherwise it starts the VM if it is not running and reads the sha the
VM runs. An equal sha ends the run. A busy test server on the VM defers the run. Anything else is a deploy
through `lupin-vm.sh` deploy, then a short smoke. A failed deploy or smoke rolls back to the sha the VM ran
before the deploy and files one row. The VM is put back in the power state it was found in.

The smoke is the VM's own post preflight plus a venue-idle read. The preflight covers health on both servers,
schema at head, the roles and a tester login. The login is checked on the VM from its own secret files. So this
job holds no credential, passes none on a command line and sends none over the network.

A row is filed only when a person must decide. The cases are a failed promotion, a rollback that also failed and a VM that cannot be reached.
Another is a VM that stayed behind the branch for STALE_DAYS days. Deferrals count toward those days.

Usage:  python -m lupin_mcp.daily_test_promotion [--branch auto] [--trigger cron|reboot|hand] [--check]
Exit codes: 0 for promoted, up to date, deferred or skipped; 1 for any failure.
"""
import argparse
import datetime
import fcntl
import json
import os
import pathlib
import sys

import cosa.utils.util as cu
from cosa.config import app_timezone
from cosa.rest import job_cron
from cosa.utils.atomic_json import load_json_dict, write_json_atomic
from lupin_mcp import duplicate_check_daily as dcd
from lupin_mcp import duplicate_check_filing as filing
from lupin_mcp import job_summary as js
from lupin_mcp.reuse_harness import commands
from cosa.rest.task_store_rules import filer_created_by

JOB            = "test-promotion"
SLOT_HOUR      = 18
SLOT_CRON      = f"0 {SLOT_HOUR} * * *"      # the registry's cron line; job_cron finds the last firing of it
STALE_DAYS     = 3
VM_SCRIPT      = "src/scripts/lupin-vm.sh"
VM_DEPLOYED    = "/mnt/lupin-data/lupin/.deployed-ref"      # first field: the sha the last completed deploy left on the VM
REF_PREFIX     = "promote/test-"
KEY_PREFIX     = "epic:daily-test-promotion-"
RUNNING        = "RUNNING"
TRIGGER_NAMES  = { "cron": "cron", "reboot": "boot", "hand": "hand" }
TIMEOUTS       = { "status": 120, "start": 900, "suspend": 300, "stop": 300, "sha": 300, "idle": 300, "deploy": 3600, "preflight": 900 }

PROMOTED       = "promoted"
UP_TO_DATE     = "up-to-date"
DEFERRED       = "deferred"
CAUGHT_UP      = "already-run-this-slot"      # printed only: a boot that finds the slot served writes no record, so the last real result stays on the page
ROLLED_BACK    = "rolled-back"
ROLLBACK_FAIL  = "rollback-failed"
VM_FAILED      = "vm-unreachable"
SUMMARY_OF     = { PROMOTED: "clean", UP_TO_DATE: "clean", DEFERRED: "carried", ROLLED_BACK: "failed", ROLLBACK_FAIL: "failed", VM_FAILED: "failed" }


def run_command( argv, timeout ):
    """
    Run one command and capture its output.

    Requires:
        - argv is a non-empty list of strings; timeout is in seconds

    Ensures:
        - returns ( exit code, stdout )
        - returns ( 127, the error text ) when the command cannot start or runs past the timeout, as reuse_harness.commands.run_command with stdout_only
    """
    return commands.run_command( argv, timeout=timeout, stdout_only=True )


class Vm:
    """
    The cloud test VM, reached only through lupin-vm.sh.

    Every method makes one wrapper call through the runner and returns what it said.
    """

    def __init__( self, root, runner=run_command ):
        """
        Remember the wrapper's path and the runner.

        Requires:
            - root is the checkout that holds src/scripts/lupin-vm.sh
            - runner takes ( argv, timeout ) and returns ( exit code, stdout )

        Ensures:
            - nothing is called until a method is used
        """
        self.script = str( pathlib.Path( root ) / VM_SCRIPT )
        self.runner = runner

    def call( self, kind, *args ):
        """Ensures: returns ( exit code, stdout ) of one wrapper call under its kind's timeout."""
        return self.runner( [ self.script, *args ], TIMEOUTS[ kind ] )

    def power( self ):
        """Ensures: returns the upper-case instance state word, or None when it cannot be read."""
        code, out = self.call( "status", "vm-status" )
        words = out.split()
        return words[ -1 ].upper() if code == 0 and words else None

    def start( self ):
        """Ensures: returns True when vm-start finished with exit 0."""
        return self.call( "start", "vm-start" )[ 0 ] == 0

    def restore( self, found ):
        """
        Put the VM back in the power state it was found in.

        Requires:
            - found is the word `power` returned before the start

        Ensures:
            - returns True when nothing needed doing or the wrapper call exited 0
            - suspends a VM found suspended or suspending, and stops one found stopped or terminated
            - leaves a VM alone when its state was unknown or already running
        """
        if found in ( "SUSPENDED", "SUSPENDING" ): return self.call( "suspend", "vm-suspend" )[ 0 ] == 0
        if found in ( "STOPPED", "TERMINATED" ):   return self.call( "stop", "vm-stop" )[ 0 ] == 0
        return True

    def deployed_sha( self ):
        """Ensures: returns the sha the VM's last deploy stamped, or None when it could not be read."""
        code, out = self.call( "sha", "run", f"cat {VM_DEPLOYED}" )
        words = out.split()
        return words[ 0 ] if code == 0 and words else None

    def idle( self ):
        """Ensures: returns venue_idle's exit code there: 0 idle, 1 busy, 2 unknown, 127 not reached."""
        return self.call( "idle", "test-server", "idle" )[ 0 ]

    def deploy( self, ref ):
        """Ensures: returns True when `deploy <ref>` exited 0."""
        return self.call( "deploy", "deploy", ref )[ 0 ] == 0

    def smoke( self ):
        """
        Say whether the VM answers after a deploy.

        Ensures:
            - returns None when the post preflight exited 0 and the test server answered idle or busy
            - returns the name of the first check that failed otherwise
        """
        if self.call( "preflight", "preflight", "post" )[ 0 ] != 0: return "post preflight"
        if self.idle() not in ( 0, 1 ): return "test server idle read"
        return None


def app_zone( config=None ):
    """
    The user's time zone, read from the `app timezone` key.

    Requires:
        - config has get_required and config_block_id as the configuration manager does, or is None to build one from LUPIN_CONFIG_MGR_CLI_ARGS

    Ensures:
        - returns the ZoneInfo the key names; no zone is written in code

    Raises:
        - MissingConfigKeyError when the key is absent or blank
        - InvalidAppTimezoneError when it names no zone
    """
    if config is None:
        from cosa.config.configuration_manager import ConfigurationManager
        config = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS", silent=True, mute_splainer=True )
    return app_timezone.get_app_zone( config )


def due( trigger, state, now, zone ):
    """
    Whether this entry should run.

    Requires:
        - trigger is cron, boot or hand; state is the stored dict; now is aware; zone is a ZoneInfo

    Ensures:
        - returns True for cron and hand
        - returns True for boot only when no attempt is recorded since the latest 18:00 slot in zone, so a
          reboot never repeats a day that already ran and never skips a day the host slept through
    """
    if trigger != "boot": return True
    last = state.get( "last_attempt_at" )
    return last is None or datetime.datetime.fromisoformat( last ) < job_cron.cron_last( SLOT_CRON, now.astimezone( zone ) )


def row_payload( kind, sha, detail, owner, extra_key=None ):
    """
    Build the store row for one decision.

    Requires:
        - kind is failed, rollback-failed, vm-unreachable or stale; sha is the picked sha; owner is a persona

    Ensures:
        - returns a payload whose correlation key names the kind and the sha (or extra_key), so a repeat of the same fault is one row
    """
    titles = { "failed": "the daily promotion failed and was rolled back", "rollback-failed": "URGENT, the daily promotion failed and its rollback failed too",
               "vm-unreachable": "the daily promotion could not reach the test VM", "stale": f"the test VM has been behind the branch for {STALE_DAYS} days" }
    return { "item_class": "task", "title": f"[LUPIN] Daily test promotion: {titles[ kind ]} ({sha[ :12 ]})", "project": "lupin", "body": detail, "owner_persona": owner,
             "accountable_manager": owner, "priority": "P2", "created_by": filer_created_by( owner, JOB ),
             "correlation_key": f"{KEY_PREFIX}{kind}-{extra_key or sha[ :12 ]}" }


def pick_sha( root, branch ):
    """
    The commit to promote.

    Requires:
        - branch is a branch name or auto

    Ensures:
        - returns ( branch name, full sha of its tip )

    Raises:
        - RuntimeError when git cannot resolve the branch
    """
    name = dcd.resolve_branch( root, branch )
    return name, dcd.git( root, "rev-parse", f"refs/heads/{name}" )


def with_ref( root, sha, action ):
    """
    Run action on a temporary branch at sha, then delete the branch.

    Requires:
        - action takes the temporary branch name and returns a value

    Ensures:
        - returns whatever action returns
        - deletes the temporary branch whether action returns or raises
    """
    name = f"{REF_PREFIX}{sha[ :12 ]}"
    dcd.git( root, "update-ref", f"refs/heads/{name}", sha )
    try:
        return action( name )
    finally:
        dcd.git( root, "update-ref", "-d", f"refs/heads/{name}" )


def holds_commit( root, sha ):
    """Ensures: returns True when this checkout holds the commit, so it can be put on a branch."""
    try:
        dcd.git( root, "cat-file", "-e", f"{sha}^{{commit}}" )
    except RuntimeError:
        return False
    return True


def deploy_and_smoke( vm ):
    """Ensures: returns a function that deploys a branch, smokes it and gives None or the stage."""
    return lambda name: "deploy" if not vm.deploy( name ) else vm.smoke()


def behind_state( state, now, ahead ):
    """
    Track how long the VM has been behind the branch.

    Requires:
        - ahead is True when the run ended with the VM still behind the pick

    Ensures:
        - sets behind_since on the first run that ends behind and keeps it after that
        - clears behind_since and the stale mark when the run ended with the VM current
    """
    if ahead:
        state.setdefault( "behind_since", js.iso_now( now ) )
    else:
        state.pop( "behind_since", None )
        state.pop( "stale_filed_for", None )


def stale_due( state, now ):
    """Ensures: returns behind_since when the stretch is old enough and unfiled, else None."""
    since = state.get( "behind_since" )
    if since is None or state.get( "stale_filed_for" ) == since: return None
    return since if now - datetime.datetime.fromisoformat( since ) >= datetime.timedelta( days=STALE_DAYS ) else None


def promote( root, vm, sha, previous ):
    """
    Deploy the sha, smoke it and roll back when either fails.

    Requires:
        - previous is the sha the VM ran before the deploy, or None

    Ensures:
        - returns ( result, stage, detail ) where result is promoted, rolled-back or rollback-failed
        - a failure rolls back to previous and smokes again; with no previous or a previous this checkout does not hold, the rollback fails and says why
        - every temporary branch is deleted
    """
    failed = with_ref( root, sha, deploy_and_smoke( vm ) )
    if failed is None: return PROMOTED, None, f"the VM now runs {sha[ :12 ]}"
    if previous is None or not holds_commit( root, previous ):
        return ROLLBACK_FAIL, failed, f"{failed} failed on {sha[ :12 ]}; the sha the VM ran before ({previous}) is unknown here, so no rollback was possible"
    again = with_ref( root, previous, deploy_and_smoke( vm ) )
    if again is None: return ROLLED_BACK, failed, f"{failed} failed on {sha[ :12 ]}; the VM was rolled back to {previous[ :12 ]} and passed its smoke"
    return ROLLBACK_FAIL, failed, f"{failed} failed on {sha[ :12 ]}; the rollback to {previous[ :12 ]} also failed at {again}"


def settle( root, vm, sha, state, found ):
    """
    The part of a run that needs the VM running.

    Requires:
        - found is the power state read before this call; the VM is started here when it was not running

    Ensures:
        - returns ( result, stage, detail ); updates state with last_promoted_sha when the VM ends on sha
    """
    if found != RUNNING and not vm.start(): return VM_FAILED, "vm-start", f"the instance was {found} and could not be started"
    current = vm.deployed_sha()
    if current == sha:
        state[ "last_promoted_sha" ] = sha
        return UP_TO_DATE, None, f"the VM already runs {sha[ :12 ]} (read)"
    if current is None: return VM_FAILED, "vm-sha", "the sha the VM runs could not be read"
    if vm.idle() != 0: return DEFERRED, "venue", f"the VM's test server is busy or unknown, so {sha[ :12 ]} waits for the next run"
    result, stage, detail = promote( root, vm, sha, current )
    if result == PROMOTED: state[ "last_promoted_sha" ] = sha
    return result, stage, detail


def decide( root, vm, sha, state ):
    """
    Settle one run for a picked sha.

    Requires:
        - state is the stored dict; it is updated in place with last_promoted_sha on success

    Ensures:
        - returns ( result, stage, detail ), touching the VM only when the stored sha cannot settle the run
        - a stored last_promoted_sha equal to sha settles the run with no VM contact
        - any other case starts the VM when needed, reads the sha it runs and settles the run when equal
        - a busy or unknown test server defers the run
        - the VM's power state is restored before returning, in every case that started it
    """
    if state.get( "last_promoted_sha" ) == sha: return UP_TO_DATE, None, f"the VM already runs {sha[ :12 ]} (stored)"
    found = vm.power()
    if found is None: return VM_FAILED, "vm-status", "the instance state could not be read"
    try:
        return settle( root, vm, sha, state, found )
    finally:
        if found != RUNNING: vm.restore( found )


def conclude( parts, now, trigger, result, stage, detail, started, state ):
    """
    Write the run's record and the state, and file the row the result calls for.

    Requires:
        - parts holds root, store, owner and the picked sha

    Ensures:
        - writes the job summary and the state file
        - files at most one row: the failure row, else the stale row; a row that cannot be sent is named in the evidence
        - returns the exit code, 0 unless the result is a failure
    """
    root, store, owner, sha = parts[ "root" ], parts[ "store" ], parts[ "owner" ], parts[ "sha" ]
    state[ "last_attempt_at" ] = js.iso_now( now )
    state[ "last_result" ]     = result
    behind_state( state, now, result in ( DEFERRED, ROLLED_BACK, ROLLBACK_FAIL, VM_FAILED ) )
    kind  = { ROLLED_BACK: "failed", ROLLBACK_FAIL: "rollback-failed", VM_FAILED: "vm-unreachable" }.get( result )
    since = None if kind else stale_due( state, now )
    if since is not None: kind = "stale"
    note = detail
    if kind is not None:
        sent = filing.send_row( row_payload( kind, sha, detail, owner, since[ :10 ] if since else None ), store )
        note = f"{detail}; row {sent[ 'outcome' ]}"
        if since is not None and sent[ "outcome" ] in ( filing.FILED, filing.ALREADY ): state[ "stale_filed_for" ] = since
    outcome = SUMMARY_OF[ result ]
    attempt = { "started_at": started, "finished_at": js.iso_now(), "trigger": trigger, "outcome": outcome,
                "stage": stage if outcome == "failed" else None, "failure": result if outcome == "failed" else None, "evidence": note, "mode": result }
    js.write_summary( parts[ "summary" ], JOB, attempt, now=now )
    write_json_atomic( parts[ "state_path" ], state )
    print( f"test-promotion: {result}: {note}" )
    return 1 if outcome == "failed" else 0


def run( root, now, trigger, branch, vm, store, owner, zone, check=False ):
    """
    One entry of the job.

    Requires:
        - trigger is cron, boot or hand; vm is a Vm; zone is a ZoneInfo; store has query and create as the filer's store does

    Ensures:
        - returns the exit code
        - holds the run lock, and a second run that finds it held exits 0 at once
        - with check, prints what would happen and changes nothing, VM and files alike
    """
    folder     = pathlib.Path( root ) / "io" / "jobs" / JOB
    folder.mkdir( parents=True, exist_ok=True )
    state_path = folder / "state.json"
    state      = load_json_dict( state_path )
    started    = js.iso_now( now )
    name, sha  = pick_sha( root, branch )
    if check:
        print( f"test-promotion --check: branch {name} at {sha[ :12 ]}; stored last promoted {state.get( 'last_promoted_sha' )}; "
               f"{'due' if due( trigger, state, now, zone ) else 'not due'} for {trigger}; the VM is not contacted" )
        return 0
    with open( folder / "run.lock", "w" ) as lock:
        try:
            fcntl.flock( lock, fcntl.LOCK_EX | fcntl.LOCK_NB )
        except OSError:
            print( "test-promotion: another run holds the lock, so this one exits" )
            return 0
        parts = { "root": root, "store": store, "owner": owner, "sha": sha, "summary": str( folder / "job-summary.json" ), "state_path": state_path }
        if not due( trigger, state, now, zone ):
            print( f"test-promotion: {CAUGHT_UP}: an attempt is already recorded since the {SLOT_HOUR}:00 slot" )
            return 0
        result, stage, detail = decide( root, vm, sha, state )
        return conclude( parts, now, trigger, result, stage, detail, started, state )


def main( argv=None, environ=None, runner=run_command, store=None, now=None, config=None ):
    """
    Run the job from the command line.

    Requires:
        - the checkout holds the registry, so LUPIN_ROOT or the project root names it

    Ensures:
        - returns the exit code of run
        - store None builds the live store and config None builds the configuration manager; runner and now are test seams
    """
    environ = os.environ if environ is None else environ
    parser  = argparse.ArgumentParser( description="Promote the newest merged build to the cloud test VM, then smoke it." )
    parser.add_argument( "--branch", default=dcd.BRANCH_AUTO )
    parser.add_argument( "--trigger", default="cron", choices=sorted( TRIGGER_NAMES ) )
    parser.add_argument( "--owner", default="mr radio", help="the persona the failure rows are filed for" )
    parser.add_argument( "--check", action="store_true", help="print what would happen and change nothing" )
    args    = parser.parse_args( argv )
    root    = environ.get( "LUPIN_ROOT" ) or cu.get_project_root()
    now     = now or datetime.datetime.now().astimezone()
    trigger = TRIGGER_NAMES[ args.trigger ]
    return run( root, now, trigger, args.branch, Vm( root, runner ), store or ( None if args.check else filing.LiveStore() ), args.owner, app_zone( config ), args.check )


if __name__ == "__main__":  # pragma: no cover - process entry point
    sys.exit( main() )
