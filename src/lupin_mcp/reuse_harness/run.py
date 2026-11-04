"""
One run of the reuse experiment (plan 3, section 7.3).

A run gets a worktree of the frozen server with an empty client folder. It gets its own server container and throwaway
database, the arm's session configuration and the pinned model. The session works in slices. After each slice the
acceptance tests give a verdict. A scored run stops when every test passes or the seat-hour cap is reached.
The pilot has no cap (its cap is None); it stops when every test passes or at the 10-working-day guard.
Each verdict records the working days used, the CPU, the peak memory and the seats (see measure).

Everything outside the process comes in through five ports, so the harness is proven with stubs:
- worktree.create( run_id, commit, remove_paths ) returns a path
- worktree.client_entries( path ) returns a list
- worktree.exists( path, relative ) returns a bool
- server.start( run_id, path ) returns a handle { url, container, db_name }
- server.db_is_fresh( handle ) returns a bool
- server.seed( handle ) gives the run's database the account that owns the sender key, after the fresh check
- server.stop( handle ) drops the database and the container
- session.bind( path, handle ) ties the sessions to the run's worktree and server
- session.probe( config, surface ) returns a bool
- server.sample( handle ) returns { mem_bytes, cpu_percent } for the run's container, or None when it cannot be read
- session.work( config, path, handle, remaining_hours ) returns { seat_hours, finished, seats }
- tests.run( handle, path, test_ids ) returns { results: { test_id: bool }, client_builds: bool }
- meter.read() returns { cpu_seconds, peak_rss_bytes } for the commands the harness has finished
- clock.now() returns the current timezone-aware moment; clock.zone names the zone working days are counted in
- log.write( record ) keeps one record
"""
import hashlib

from lupin_mcp.reuse_harness import arms
from lupin_mcp.reuse_harness import errors as err
from lupin_mcp.reuse_harness import measure

STOP_ALL_PASS      = "all_pass"
STOP_CAP           = "cap"
STOP_GUARD         = "guard_working_days"
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
        - returns None when spec holds every key of SPEC_KEYS, a positive cap or None (the pilot) and a non-empty list of distinct test ids

    Raises:
        - HarnessError BAD_ARM if the arm is neither the with arm nor the without arm
        - HarnessError BAD_SPEC naming the missing key, the empty field, the cap or the repeated test id
    """
    missing = [ key for key in SPEC_KEYS if key not in spec ]
    if missing: raise err.HarnessError( err.BAD_SPEC, f"the spec lacks {missing}" )
    if spec[ "arm" ] not in arms.ARMS: raise err.HarnessError( err.BAD_ARM, f"{spec[ 'arm' ]!r} is not one of {list( arms.ARMS )}" )
    empty = [ key for key in ( "run_id", "model_id", "server_commit" ) if not spec[ key ] ]
    if empty: raise err.HarnessError( err.BAD_SPEC, f"{empty} is empty" )
    if spec[ "cap_seat_hours" ] is not None and spec[ "cap_seat_hours" ] <= 0:
        raise err.HarnessError( err.BAD_SPEC, f"the cap must be positive, or None for the pilot, got {spec[ 'cap_seat_hours' ]}" )
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


def _peak( current, sample, key ):
    """Return the larger of the peak so far and a new reading; None leaves the peak alone."""
    if sample is None: return current
    return sample[ key ] if current is None else max( current, sample[ key ] )


def _record( spec, config, event, **fields ):
    """Build one log record of a run, with the keys every record carries."""
    return { "event" : event, "run" : spec[ "run_id" ], "arm_label" : config[ "arm_label" ], **fields }


def run_one( spec, ports ):
    """
    Run one arm of the experiment from a fresh worktree and database to its stop.

    Requires:
        - spec holds run_id, arm, model_id, server_commit, cap_seat_hours (a positive number, or None for the pilot) and test_ids (the distinct acceptance tests of the frozen build)
        - ports has worktree, server, session, tests, meter, clock and log as described in the module docstring

    Ensures:
        - the order is: worktree, own server and database, sender key seeded after the fresh check, session bound to both, arm proof, then slices of work each followed by a verdict
        - the session never starts before the arm is proven and the database is the run's own and fresh
        - the clock starts after the arm proof, so the time measured is the time to build, not to set up
        - a scored slice is given the seat hours that remain under the cap; a pilot slice is given the working hours that remain under the guard
        - one log record per verdict, with the run, arm label, model id, server commit, seat hours so far, the pass count and the measurements so far, and one stop record that also names working_zone and the notes of measure.NOTES
        - the run stops at the first verdict where every test passes (all_pass), else for a pilot when GUARD_WORKING_DAYS are used (guard_working_days), else for a scored run when the seat hours reach the cap (cap), else when the session reports it has finished (session_ended)
        - the server and its database are stopped on every exit, including a failure
        - returns { run, passing_tests, pass_rate, client_builds, stop, seat_hours, pilot, working_days, time_to_all_pass_working_days, wall_hours, cpu_seconds, peak_rss_bytes, server_peak_rss_bytes, server_peak_cpu_percent, peak_seats }
          the first three and client_builds being what the scorer reads; time_to_all_pass_working_days is None unless the stop is all_pass
        - a figure that could not be read is None, never a guess

    Raises:
        - HarnessError for each cause named in errors, including NO_PROGRESS when a slice reports no seat hours and has not finished
    """
    check_spec( spec )
    test_ids = list( spec[ "test_ids" ] )
    config   = arms.build_session_config( spec[ "arm" ], spec[ "model_id" ] )
    pilot    = spec[ "cap_seat_hours" ] is None
    path     = ports.worktree.create( spec[ "run_id" ], spec[ "server_commit" ], config[ "remove_paths" ] )
    _check_worktree( spec, config, path, ports.worktree )
    handle   = ports.server.start( spec[ "run_id" ], path )
    try:
        _check_own_database( spec, handle, ports.server )
        ports.server.seed( handle )
        ports.session.bind( path, handle )
        arms.verify_arm( spec[ "arm" ], config, ports.session )
        seat_hours = 0.0
        started    = ports.clock.now()
        peaks      = { "server_rss" : None, "server_cpu" : None, "seats" : 0 }
        while True:
            if pilot: remaining = ( measure.GUARD_WORKING_DAYS * measure.SECONDS_PER_DAY - measure.working_seconds( started, ports.clock.now(), ports.clock.zone ) ) / 3600
            else:     remaining = spec[ "cap_seat_hours" ] - seat_hours
            work        = ports.session.work( config, path, handle, remaining )
            seat_hours += work[ "seat_hours" ]
            peaks[ "seats" ] = max( peaks[ "seats" ], work[ "seats" ] )
            if work[ "seat_hours" ] <= 0 and not work[ "finished" ]: raise err.HarnessError( err.NO_PROGRESS, f"run {spec[ 'run_id' ]}: a slice used no seat hours and did not finish" )
            outcome     = ports.tests.run( handle, path, test_ids )
            passing     = _verdict( spec, test_ids, outcome )
            now         = ports.clock.now()
            sample      = ports.server.sample( handle )
            peaks[ "server_rss" ] = _peak( peaks[ "server_rss" ], sample, "mem_bytes" )
            peaks[ "server_cpu" ] = _peak( peaks[ "server_cpu" ], sample, "cpu_percent" )
            used        = ports.meter.read()
            measured    = { "working_days" : measure.working_days( started, now, ports.clock.zone ), "wall_hours" : ( now - started ).total_seconds() / 3600,
                            "cpu_seconds" : used[ "cpu_seconds" ], "peak_rss_bytes" : used[ "peak_rss_bytes" ],
                            "server_peak_rss_bytes" : peaks[ "server_rss" ], "server_peak_cpu_percent" : peaks[ "server_cpu" ], "peak_seats" : peaks[ "seats" ] }
            ports.log.write( _record( spec, config, "verdict", model_id=spec[ "model_id" ], server_commit=spec[ "server_commit" ], seat_hours=seat_hours,
                                      passing_tests=passing, total_tests=len( test_ids ), **measured ) )
            if passing == len( test_ids ):
                stop = STOP_ALL_PASS
            elif pilot and measure.guard_reached( started, now, ports.clock.zone ):
                stop = STOP_GUARD
            elif not pilot and seat_hours >= spec[ "cap_seat_hours" ]:
                stop = STOP_CAP
            elif work[ "finished" ]:
                stop = STOP_SESSION_ENDED
            else:
                continue
            break
        to_pass = measured[ "working_days" ] if stop == STOP_ALL_PASS else None
        ports.log.write( _record( spec, config, "stop", stop=stop, seat_hours=seat_hours, pilot=pilot, time_to_all_pass_working_days=to_pass,
                                  working_zone=ports.clock.zone, notes=list( measure.NOTES ), **measured ) )
        return { "run" : spec[ "run_id" ], "passing_tests" : passing, "pass_rate" : passing / len( test_ids ), "client_builds" : outcome[ "client_builds" ],
                 "stop" : stop, "seat_hours" : seat_hours, "pilot" : pilot, "time_to_all_pass_working_days" : to_pass, **measured }
    finally:
        ports.server.stop( handle )
