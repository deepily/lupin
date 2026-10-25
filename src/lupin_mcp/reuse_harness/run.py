"""
One run of the reuse experiment (plan 3, section 7.3).

A run gets a worktree of the frozen server with an empty client folder. It gets its own server container and throwaway
database, the arm's session configuration and the pinned model. The session works in slices. After each slice the
acceptance tests give a verdict. The run stops when every test passes or the seat-hour cap is reached.

Everything outside the process comes in through five ports, so the harness is proven with stubs:
- worktree.create( run_id, commit, remove_paths ) returns a path
- worktree.client_entries( path ) returns a list
- worktree.exists( path, relative ) returns a bool
- server.start( run_id, path ) returns a handle { url, container, db_name }
- server.db_is_fresh( handle ) returns a bool
- server.stop( handle ) drops the database and the container
- session.probe( config, surface ) returns a bool
- session.work( config, path, handle, remaining_hours ) returns { seat_hours, finished }
- tests.run( handle, path, test_ids ) returns { results: { test_id: bool }, client_builds: bool }
- log.write( record ) keeps one record
"""
import hashlib

from lupin_mcp.reuse_harness import arms
from lupin_mcp.reuse_harness import errors as err

STOP_ALL_PASS      = "all_pass"
STOP_CAP           = "cap"
STOP_SESSION_ENDED = "session_ended"

SPEC_KEYS = ( "run_id", "arm", "model_id", "server_commit", "cap_seat_hours", "test_ids" )


def db_name( run_id ):
    """
    Name the throwaway database of a run.

    Requires:
        - run_id is a non-empty string

    Ensures:
        - the name is a valid unquoted Postgres identifier: lowercase letters, digits and underscores, under 63 characters
        - the same run_id gives the same name, and two run_ids give two names
    """
    return "rrun_" + hashlib.sha1( run_id.encode( "utf-8" ) ).hexdigest()[ :16 ]


def container_name( run_id ):
    """
    Name the server container of a run.

    Requires:
        - run_id is a non-empty string

    Ensures:
        - the name carries the database name's hash, so a container and its database name the same run
    """
    return "rrun-server-" + db_name( run_id )[ len( "rrun_" ): ]


def check_spec( spec ):
    """
    Refuse a run spec that cannot start a run.

    Requires:
        - spec is a dict

    Ensures:
        - returns None when spec holds every key of SPEC_KEYS, a positive cap and a non-empty list of distinct test ids

    Raises:
        - HarnessError BAD_ARM if the arm is neither the with arm nor the without arm
        - HarnessError BAD_SPEC naming the missing key, the empty field, the cap or the repeated test id
    """
    missing = [ key for key in SPEC_KEYS if key not in spec ]
    if missing: raise err.HarnessError( err.BAD_SPEC, f"the spec lacks {missing}" )
    if spec[ "arm" ] not in arms.ARMS: raise err.HarnessError( err.BAD_ARM, f"{spec[ 'arm' ]!r} is not one of {list( arms.ARMS )}" )
    empty = [ key for key in ( "run_id", "model_id", "server_commit" ) if not spec[ key ] ]
    if empty: raise err.HarnessError( err.BAD_SPEC, f"{empty} is empty" )
    if spec[ "cap_seat_hours" ] <= 0: raise err.HarnessError( err.BAD_SPEC, f"the cap must be positive, got {spec[ 'cap_seat_hours' ]}" )
    if not spec[ "test_ids" ]: raise err.HarnessError( err.BAD_SPEC, "test_ids is empty" )
    if len( set( spec[ "test_ids" ] ) ) != len( spec[ "test_ids" ] ): raise err.HarnessError( err.BAD_SPEC, "test_ids repeats an id" )


def _check_worktree( spec, config, path, worktree ):
    """
    Check the worktree is the frozen server with no client and the arm's skill folder state.

    Raises:
        - HarnessError CLIENT_NOT_EMPTY if the client folder holds anything
        - HarnessError SURFACE_REACHABLE if a path the arm removes is still there
        - HarnessError SURFACE_MISSING if the arm with the tools lacks the skill folder
    """
    entries = worktree.client_entries( path )
    if entries: raise err.HarnessError( err.CLIENT_NOT_EMPTY, f"the client folder holds {entries}" )
    for relative in config[ "remove_paths" ]:
        if worktree.exists( path, relative ): raise err.HarnessError( err.SURFACE_REACHABLE, f"{relative} is still in the worktree of the arm without it" )
    if spec[ "arm" ] == arms.ARM_WITH and not worktree.exists( path, arms.SKILL_PATH ):
        raise err.HarnessError( err.SURFACE_MISSING, f"{arms.SKILL_PATH} is not in the worktree of the arm with the tools" )


def _check_own_database( spec, handle, server ):
    """
    Check the server and database are this run's own and hold nothing yet.

    Raises:
        - HarnessError DB_NOT_OWN if the container or database name is not the one derived from the run id
        - HarnessError DB_NOT_FRESH if the database already holds rows
    """
    if handle[ "db_name" ] != db_name( spec[ "run_id" ] ) or handle[ "container" ] != container_name( spec[ "run_id" ] ):
        raise err.HarnessError( err.DB_NOT_OWN, f"got {handle[ 'container' ]} and {handle[ 'db_name' ]} for run {spec[ 'run_id' ]}" )
    if not server.db_is_fresh( handle ): raise err.HarnessError( err.DB_NOT_FRESH, f"{handle[ 'db_name' ]} already holds rows" )


def _verdict( spec, test_ids, outcome ):
    """
    Count the passing tests of one test run.

    Raises:
        - HarnessError BAD_SPEC if the results name other tests than the run's
    """
    results = outcome[ "results" ]
    if set( results ) != set( test_ids ): raise err.HarnessError( err.BAD_SPEC, f"run {spec[ 'run_id' ]}: the results name other tests than the run's" )
    return sum( 1 for test_id in test_ids if results[ test_id ] )


def run_one( spec, ports ):
    """
    Run one arm of the experiment from a fresh worktree and database to its stop.

    Requires:
        - spec holds run_id, arm, model_id, server_commit, cap_seat_hours (a positive number) and test_ids (the distinct acceptance tests of the frozen build)
        - ports has worktree, server, session, tests and log as described in the module docstring

    Ensures:
        - the order is: worktree, own server and database, arm proof, then slices of work each followed by a verdict
        - the session never starts before the arm is proven and the database is the run's own and fresh
        - a slice is given the seat hours that remain under the cap
        - one log record per verdict, with the run, arm label, model id, server commit, seat hours so far and the pass count, and one stop record
        - the run stops at the first verdict where every test passes (all_pass), else when the seat hours reach the cap (cap), else when the session reports it has finished (session_ended)
        - the server and its database are stopped on every exit, including a failure
        - returns { run, passing_tests, pass_rate, client_builds, stop, seat_hours }, the first three and client_builds being what the scorer reads

    Raises:
        - HarnessError for each cause named in errors, including NO_PROGRESS when a slice reports no seat hours and has not finished
    """
    check_spec( spec )
    test_ids = list( spec[ "test_ids" ] )
    config   = arms.build_session_config( spec[ "arm" ], spec[ "model_id" ] )
    path     = ports.worktree.create( spec[ "run_id" ], spec[ "server_commit" ], config[ "remove_paths" ] )
    _check_worktree( spec, config, path, ports.worktree )
    handle   = ports.server.start( spec[ "run_id" ], path )
    try:
        _check_own_database( spec, handle, ports.server )
        arms.verify_arm( spec[ "arm" ], config, ports.session )
        seat_hours = 0.0
        while True:
            work        = ports.session.work( config, path, handle, spec[ "cap_seat_hours" ] - seat_hours )
            seat_hours += work[ "seat_hours" ]
            if work[ "seat_hours" ] <= 0 and not work[ "finished" ]: raise err.HarnessError( err.NO_PROGRESS, f"run {spec[ 'run_id' ]}: a slice used no seat hours and did not finish" )
            outcome     = ports.tests.run( handle, path, test_ids )
            passing     = _verdict( spec, test_ids, outcome )
            ports.log.write( { "event" : "verdict", "run" : spec[ "run_id" ], "arm_label" : config[ "arm_label" ], "model_id" : spec[ "model_id" ],
                               "server_commit" : spec[ "server_commit" ], "seat_hours" : seat_hours, "passing_tests" : passing, "total_tests" : len( test_ids ) } )
            if passing == len( test_ids ):
                stop = STOP_ALL_PASS
            elif seat_hours >= spec[ "cap_seat_hours" ]:
                stop = STOP_CAP
            elif work[ "finished" ]:
                stop = STOP_SESSION_ENDED
            else:
                continue
            break
        ports.log.write( { "event" : "stop", "run" : spec[ "run_id" ], "arm_label" : config[ "arm_label" ], "stop" : stop, "seat_hours" : seat_hours } )
        return { "run" : spec[ "run_id" ], "passing_tests" : passing, "pass_rate" : passing / len( test_ids ),
                 "client_builds" : outcome[ "client_builds" ], "stop" : stop, "seat_hours" : seat_hours }
    finally:
        ports.server.stop( handle )
