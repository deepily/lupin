"""
The driver of the run harness: build the ports of one run, run it or dry-run its arm.

It writes what the scorer reads.

A run lives in <data root>/<arm label>/<run id>/, so no folder name says which arm made it.
That folder holds the log, the junit reports
and result.json, which is the file the semantic scorer reads. The run id is chosen by the caller and must not name the arm.
"""
import argparse
import json
import os
import secrets
import types

import yaml

from lupin_mcp.reuse_harness import acceptance
from lupin_mcp.reuse_harness import arms
from lupin_mcp.reuse_harness import databases
from lupin_mcp.reuse_harness import errors as err
from lupin_mcp.reuse_harness import freeze
from lupin_mcp.reuse_harness import gitrepo
from lupin_mcp.reuse_harness import log
from lupin_mcp.reuse_harness import run as harness
from lupin_mcp.reuse_harness import server
from lupin_mcp.reuse_harness import session
from lupin_mcp.reuse_harness import worktree

COMPOSE_FILE   = "docker-compose.yml"
SERVER_SERVICE = "lupin-rest-test"
RESULT_FILE    = "result.json"
KEY_BYTES      = 48
EXIT_DONE      = 0
EXIT_REFUSED   = 2


def image_of( compose_text, service=SERVER_SERVICE ):
    """
    Read the image the test server runs from the compose file.

    Requires:
        - compose_text is the text of docker-compose.yml

    Ensures:
        - returns the image of the named service

    Raises:
        - HarnessError BAD_SPEC if the service or its image is missing
    """
    found = ( yaml.safe_load( compose_text ).get( "services" ) or {} ).get( service, {} ).get( "image" )
    if not found: raise err.HarnessError( err.BAD_SPEC, f"{COMPOSE_FILE} names no image for {service}" )
    return found


def run_dir_of( data_root, spec ):
    """Return the folder of a run, named by the arm's label and the run id."""
    return os.path.join( data_root, arms.ARM_LABELS[ spec[ "arm" ] ], spec[ "run_id" ] )


def make_key():
    """Return a fresh sender key in the format the server's keys have."""
    return f"ck_live_{secrets.token_urlsafe( KEY_BYTES )}"


def build_ports( spec, repo_root, data_root, image, mcp_config=None, environ=None ):
    """
    Build the real ports of one run.

    Requires:
        - spec passes check_spec; image names the server image; the test-role database login exists

    Ensures:
        - the run's folder exists and nothing else is created or started
        - one fresh sender key is shared by the server, the tests and the session, and appears nowhere on disk or in an argument
        - the environment gains a JWT secret for the run's server when it has none

    Raises:
        - HarnessError DB_UNAVAILABLE if there is no test-role login
    """
    environ = dict( os.environ if environ is None else environ )
    if not environ.get( "JWT_SECRET_KEY" ): environ[ "JWT_SECRET_KEY" ] = secrets.token_urlsafe( KEY_BYTES )
    run_dir = run_dir_of( data_root, spec )
    os.makedirs( os.path.join( run_dir, "reports" ) )
    key = make_key()
    return types.SimpleNamespace(
        worktree = worktree.Worktrees( repo_root ),
        server   = server.Servers( databases.Databases( databases.maintenance_url() ), image, key, environ=environ ),
        session  = session.Sessions( key, mcp_config=mcp_config, environ=environ ),
        tests    = acceptance.Acceptance( spec[ "server_commit" ], key, os.path.join( run_dir, "reports" ), environ=environ,
                                          removed=arms.build_session_config( spec[ "arm" ], spec[ "model_id" ] )[ "remove_paths" ] ),
        log      = log.RunLog( run_dir ) )


def execute( spec, ports, run_dir ):
    """
    Run one arm to its stop and write result.json beside the log.

    Requires:
        - run_dir is the run's folder and holds no result.json yet

    Ensures:
        - returns the result of run_one; result.json holds the same dict
        - a failed run writes no result.json

    Raises:
        - HarnessError from run_one
        - FileExistsError if the folder already holds a result
    """
    result = harness.run_one( spec, ports )
    with open( os.path.join( run_dir, RESULT_FILE ), "x", encoding="utf-8" ) as f: json.dump( result, f, indent=2, sort_keys=True )
    return result


def dry_run( spec, ports ):
    """
    Prove the arm switch without building anything.

    Cuts the tree, binds a session, probes the four surfaces and removes the tree.

    Requires:
        - spec passes check_spec; the ports are the run's own

    Ensures:
        - no server and no database are started
        - the worktree is removed whether or not the proof holds
        - returns { surface : answered } as verify_arm does

    Raises:
        - HarnessError SURFACE_REACHABLE or SURFACE_MISSING from the arm proof
    """
    harness.check_spec( spec )
    config = arms.build_session_config( spec[ "arm" ], spec[ "model_id" ] )
    path   = ports.worktree.create( spec[ "run_id" ], spec[ "server_commit" ], config[ "remove_paths" ] )
    try:
        ports.session.bind( path, { "url" : "http://127.0.0.1:0", "container" : harness.container_name( spec[ "run_id" ] ), "db_name" : harness.db_name( spec[ "run_id" ] ) } )
        return arms.verify_arm( spec[ "arm" ], config, ports.session )
    finally:
        ports.worktree.remove( path )


def parse( argv ):
    """Read the command line of the driver."""
    parser = argparse.ArgumentParser( prog="python -m lupin_mcp.reuse_harness", description="Run one arm of the reuse experiment." )
    parser.add_argument( "--repo-root", required=True )
    parser.add_argument( "--data-root", required=True )
    parser.add_argument( "--run-id", required=True )
    parser.add_argument( "--arm", required=True, choices=arms.ARMS )
    parser.add_argument( "--model-id", required=True )
    parser.add_argument( "--frozen-sha", required=True )
    parser.add_argument( "--cap-seat-hours", required=True, type=float )
    parser.add_argument( "--mcp-config" )
    parser.add_argument( "--dry-run", action="store_true" )
    return parser.parse_args( argv )


def main( argv, factory=build_ports, environ=None ):
    """
    Run or dry-run one arm from the command line.

    Requires:
        - argv holds the arguments of parse

    Ensures:
        - returns 0 for a run that reached a stop or a dry run that proved the arm, and 2 for a refusal, printing its code
        - a dry run prints the answers per surface; a run prints its result

    Raises:
        - nothing for a HarnessError, which becomes exit code 2
    """
    args = parse( argv )
    try:
        git     = gitrepo.GitRepo( args.repo_root )
        spec    = freeze.build_spec( git, args.run_id, args.arm, args.model_id, args.frozen_sha, args.cap_seat_hours )
        with open( os.path.join( args.repo_root, COMPOSE_FILE ), encoding="utf-8" ) as f: image = image_of( f.read() )
        ports   = factory( spec, args.repo_root, args.data_root, image, args.mcp_config, environ )
        outcome = dry_run( spec, ports ) if args.dry_run else execute( spec, ports, run_dir_of( args.data_root, spec ) )
    except err.HarnessError as error:
        print( f"REFUSED {error}" )
        return EXIT_REFUSED
    print( json.dumps( outcome, sort_keys=True ) )
    return EXIT_DONE
