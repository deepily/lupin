"""
The live check of the run harness, which needs a real session and a real container.

The plan's pilot (section 7.4) is the first time the real command line and a real container run together.
This script does that check on its own, before any pilot run is paid for.
It proves three things.
The real CLI refuses the arm without the tools all four surfaces.
The arm with them reaches all four.
A run's server boots, is seeded, answers the acceptance tests and is removed again.

Run with no flag it only prints its plan: the exact command, what will start and how many probe sessions it pays for.
Nothing starts until --execute is given.
"""
import argparse
import json
import os

from lupin_mcp.reuse_harness import arms
from lupin_mcp.reuse_harness import driver
from lupin_mcp.reuse_harness import errors as err
from lupin_mcp.reuse_harness import freeze
from lupin_mcp.reuse_harness import gitrepo
from lupin_mcp.reuse_harness import session

SUMMARY_FILE = "live-check.json"
RUN_IDS      = { arms.ARM_WITH : "livecheck-a", arms.ARM_WITHOUT : "livecheck-b", "boot" : "livecheck-boot" }


def plan_text( args ):
    """
    Describe what --execute would do, with the exact command.

    Requires:
        - args holds the parsed command line of main

    Ensures:
        - names the command, the sessions it pays for, the container and database it creates and removes, and the files it writes
        - starts nothing
    """
    root    = os.path.abspath( args.repo_root )
    probes  = len( arms.ARMS ) * len( arms.SURFACES )
    command = ( f"cd {root} && LUPIN_ROOT={root} PYTHONPATH={root}/src {root}/.venv/bin/python -m lupin_mcp.reuse_harness.live_check "
                f"--repo-root {root} --data-root {os.path.abspath( args.data_root )} --frozen-sha {args.frozen_sha} --model-id {args.model_id}"
                + ( f" --mcp-config {args.mcp_config}" if args.mcp_config else "" ) + " --execute" )
    return "\n".join( [ "PLAN (nothing has been started):", f"  command  : {command}",
                        f"  sessions : {probes} short probe sessions of the real CLI, {len( arms.SURFACES )} per arm, model {args.model_id}, permission mode {session.PERMISSION_MODE}",
                        "  container: one run server and one throwaway database, created, seeded, sampled, queried by the acceptance tests and removed",
                        "  worktrees: one per probe arm and one for the boot, each removed at the end",
                        f"  writes   : {SUMMARY_FILE} and one init event per arm under the data root's live-check folder; scrub the events before committing one as a fixture" ] )


def boot_check( spec, ports ):
    """
    Boot a run's server for real, seed it, run the acceptance tests against it and remove it.

    Requires:
        - spec passes check_spec; ports are the real ports of that run

    Ensures:
        - the order is: worktree, server and database, fresh check, seed, one container sample, one acceptance run
        - the server, the database and the worktree are removed on every exit
        - returns { url, fresh, sample, passing_tests, total_tests, client_builds, gone_after_stop }
        - gone_after_stop is true when a sample taken after the stop finds no container

    Raises:
        - HarnessError from any port
    """
    config = arms.build_session_config( spec[ "arm" ], spec[ "model_id" ] )
    path   = ports.worktree.create( spec[ "run_id" ], spec[ "server_commit" ], config[ "remove_paths" ] )
    try:
        handle = ports.server.start( spec[ "run_id" ], path )
        try:
            fresh   = ports.server.db_is_fresh( handle )
            ports.server.seed( handle )
            sample  = ports.server.sample( handle )
            outcome = ports.tests.run( handle, path, list( spec[ "test_ids" ] ) )
        finally:
            ports.server.stop( handle )
    finally:
        ports.worktree.remove( path )
    return { "url" : handle[ "url" ], "fresh" : fresh, "sample" : sample, "passing_tests" : sum( outcome[ "results" ].values() ), "total_tests" : len( outcome[ "results" ] ),
             "client_builds" : outcome[ "client_builds" ], "gone_after_stop" : ports.server.sample( handle ) is None }


def parse( argv ):
    """Read the command line of the live check."""
    parser = argparse.ArgumentParser( prog="python -m lupin_mcp.reuse_harness.live_check", description="Prove the arm switch and a container boot with the real CLI and docker." )
    parser.add_argument( "--repo-root", required=True )
    parser.add_argument( "--data-root", required=True )
    parser.add_argument( "--frozen-sha", required=True )
    parser.add_argument( "--model-id", required=True )
    parser.add_argument( "--mcp-config" )
    parser.add_argument( "--execute", action="store_true", help="start the sessions and the container; without it only the plan is printed" )
    return parser.parse_args( argv )


def main( argv, factory=driver.build_ports, environ=None ):
    """
    Print the plan, or with --execute run the check and write its summary.

    Requires:
        - argv holds the arguments of parse
        - with --execute: the real CLI, docker and the test-role database login are available

    Ensures:
        - returns 0 for the plan alone or for a check whose both arms and boot held, and 2 for a refusal, printing its code
        - each arm is proven through driver.dry_run, which refuses a wrong answer on any surface
        - the init event of the latest probe of each arm is written under <data root>/live-check/, named by the arm's label
        - the summary holds the answers per surface for each arm and the boot result

    Raises:
        - nothing for a HarnessError, which becomes exit code 2
    """
    args = parse( argv )
    if not args.execute:
        print( plan_text( args ) )
        return driver.EXIT_DONE
    out_dir = os.path.join( args.data_root, "live-check" )
    os.makedirs( out_dir, exist_ok=True )
    try:
        git      = gitrepo.GitRepo( args.repo_root )
        with open( os.path.join( args.repo_root, driver.COMPOSE_FILE ), encoding="utf-8" ) as f: image = driver.image_of( f.read() )
        summary  = { "arms" : {} }
        for arm in arms.ARMS:
            spec  = freeze.build_spec( git, RUN_IDS[ arm ], arm, args.model_id, args.frozen_sha, None )
            ports = factory( spec, args.repo_root, args.data_root, image, args.mcp_config, environ )
            summary[ "arms" ][ arm ] = driver.dry_run( spec, ports )
            with open( os.path.join( out_dir, f"init-event-{arms.ARM_LABELS[ arm ]}.json" ), "w", encoding="utf-8" ) as f:
                json.dump( session.init_of( session.events_of( ports.session.last_output ) ), f, indent=2, sort_keys=True )
        spec  = freeze.build_spec( git, RUN_IDS[ "boot" ], arms.ARM_WITH, args.model_id, args.frozen_sha, None )
        summary[ "boot" ] = boot_check( spec, factory( spec, args.repo_root, args.data_root, image, args.mcp_config, environ ) )
    except err.HarnessError as error:
        print( f"REFUSED {error}" )
        return driver.EXIT_REFUSED
    with open( os.path.join( out_dir, SUMMARY_FILE ), "w", encoding="utf-8" ) as f: json.dump( summary, f, indent=2, sort_keys=True )
    print( json.dumps( summary, sort_keys=True ) )
    return driver.EXIT_DONE


if __name__ == "__main__":
    import sys
    raise SystemExit( main( sys.argv[ 1: ] ) )
