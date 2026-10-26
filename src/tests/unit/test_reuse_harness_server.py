"""
Unit tests of the run server port.

The database port keeps real per-name state, so a shared or leaked database shows up as rows that should not be there.
The docker port is a small simulator: it knows which containers exist and answers inspect, logs and remove as docker does.
The default helpers (command runner, port probe, health probe) are run for real against a local process and socket.
"""
import http.server
import socket
import sys
import threading

import pytest

from lupin_mcp.reuse_harness import errors as err
from lupin_mcp.reuse_harness import run as harness
from lupin_mcp.reuse_harness import server

ENVIRON = { "JWT_SECRET_KEY" : "jwt-secret-value", "PATH" : "/bin" }
LOGIN   = ( "tester", "db-secret-value" )


class Databases:
    """A database port with one real row list per name, shared across runs so reuse would show."""

    def __init__( self, fail_drop=False, fail_create=False ):
        """Start with no databases."""
        self.dbs         = {}
        self.fail_drop   = fail_drop
        self.fail_create = fail_create
        self.history     = []

    def create( self, name ):
        """Create an empty database, or refuse."""
        self.history.append( ( "create", name ) )
        if self.fail_create: raise err.HarnessError( err.DB_UNAVAILABLE, "no template" )
        self.dbs[ name ] = []

    def drop( self, name ):
        """Drop the database; one already gone is not an error."""
        self.history.append( ( "drop", name ) )
        if self.fail_drop: raise err.HarnessError( err.DB_UNAVAILABLE, "session of another role" )
        self.dbs.pop( name, None )

    def is_fresh( self, name ):
        """Say whether the database holds no rows."""
        return self.dbs[ name ] == []


class Docker:
    """A docker simulator that records every command and the environment it ran in."""

    def __init__( self, run_code=0, rm_code=0, rm_text="", running="true" ):
        """Choose the answers of run, rm and inspect."""
        self.run_code, self.rm_code, self.rm_text, self.running = run_code, rm_code, rm_text, running
        self.calls      = []
        self.containers = set()

    def __call__( self, argv, env ):
        """Answer one docker command."""
        self.calls.append( ( argv, env ) )
        verb = argv[ 1 ]
        if verb == "run":
            if self.run_code == 0: self.containers.add( argv[ argv.index( "--name" ) + 1 ] )
            return self.run_code, "container-id" if self.run_code == 0 else "port is already allocated"
        if verb == "inspect": return 0, self.running
        if verb == "logs": return 0, "Traceback: boot failed"
        if verb == "rm":
            name = argv[ -1 ]
            if self.rm_code != 0: return self.rm_code, self.rm_text
            if name not in self.containers: return 1, f"Error: No such container: {name}"
            self.containers.discard( name )
            return 0, name
        raise AssertionError( f"unexpected docker command {argv}" )

    def verbs( self ):
        """Return the docker verbs run so far, in order."""
        return [ argv[ 1 ] for argv, _ in self.calls ]


class Clock:
    """A clock that only moves when the code sleeps."""

    def __init__( self ):
        """Start at zero."""
        self.now = 0.0

    def __call__( self ):
        """Return the time."""
        return self.now

    def sleep( self, seconds ):
        """Move the time on."""
        self.now += seconds


def make( databases=None, docker=None, healthy_after=0, port_free=lambda port: True, environ=None, login=lambda: LOGIN, timeout=10 ):
    """Build ( Servers, databases, docker ) over simulators; health answers after N polls."""
    databases = databases or Databases()
    docker    = docker or Docker()
    clock     = Clock()
    polls     = []
    health    = lambda url: ( polls.append( url ), len( polls ) > healthy_after )[ 1 ]
    servers   = server.Servers( databases, "lupin:test-image", runner=docker, environ=ENVIRON if environ is None else environ, login=login,
                                port_free=port_free, health=health, sleep=clock.sleep, clock=clock, boot_timeout=timeout )
    return servers, databases, docker


def code_of( call ):
    """Return the code of the HarnessError a call raises."""
    with pytest.raises( err.HarnessError ) as caught: call()
    return caught.value.code


def test_start_returns_the_names_derived_from_the_run_id_and_a_loopback_url():
    servers, databases, _ = make()
    handle = servers.start( "r1", "/wt/r1" )
    assert ( handle[ "container" ], handle[ "db_name" ] ) == ( harness.container_name( "r1" ), harness.db_name( "r1" ) )
    assert handle[ "url" ] == f"http://127.0.0.1:{handle[ 'port' ]}" and server.PORT_BASE <= handle[ "port" ] < server.PORT_BASE + server.PORT_SPAN
    assert databases.dbs == { harness.db_name( "r1" ) : [] }


def test_start_creates_the_database_before_the_container_and_waits_for_health_after_it():
    servers, databases, docker = make( healthy_after=2 )
    servers.start( "r1", "/wt/r1" )
    assert databases.history[ 0 ] == ( "create", harness.db_name( "r1" ) ) and docker.verbs()[ 0 ] == "run"
    assert docker.verbs() == [ "run", "inspect", "inspect" ]


def test_start_binds_loopback_mounts_the_run_tree_over_an_empty_env_and_points_the_server_at_the_runs_database():
    servers, _, docker = make()
    handle = servers.start( "r1", "/wt/r1" )
    argv   = docker.calls[ 0 ][ 0 ]
    assert f"127.0.0.1:{handle[ 'port' ]}:7999" in argv and "/wt/r1:/var/lupin" in argv and "/dev/null:/var/lupin/.env:ro" in argv
    assert f"DB_NAME={harness.db_name( 'r1' )}" in argv and "LUPIN_ENV=testing" in argv and argv[ argv.index( "--name" ) + 1 ] == harness.container_name( "r1" )
    assert argv[ -4: ] == [ "lupin:test-image", "bash", "-c", server.COMMAND ]


def test_start_passes_secrets_by_name_in_the_arguments_and_by_value_only_in_the_environment():
    servers, _, docker = make()
    servers.start( "r1", "/wt/r1" )
    argv, env = docker.calls[ 0 ]
    assert [ argv[ i + 1 ] for i, word in enumerate( argv ) if word == "-e" ][ -3: ] == [ "JWT_SECRET_KEY", "DB_USER", "DB_PASSWORD" ]
    assert "jwt-secret-value" not in " ".join( argv ) and "db-secret-value" not in " ".join( argv )
    assert ( env[ "JWT_SECRET_KEY" ], env[ "DB_USER" ], env[ "DB_PASSWORD" ] ) == ( "jwt-secret-value", "tester", "db-secret-value" )
    assert "DB_USER" not in ENVIRON


def test_two_runs_get_their_own_database_and_container_and_never_see_each_others_rows():
    servers, databases, docker = make()
    first  = servers.start( "r1", "/wt/r1" )
    databases.dbs[ first[ "db_name" ] ].append( "account" )
    second = servers.start( "r2", "/wt/r2" )
    assert servers.db_is_fresh( second ) is True and servers.db_is_fresh( first ) is False
    assert first[ "container" ] != second[ "container" ] and first[ "db_name" ] != second[ "db_name" ]
    assert docker.containers == { first[ "container" ], second[ "container" ] }


def test_the_port_is_the_first_free_one_from_the_runs_offset_and_the_range_wraps():
    offset = 267
    own    = make()[ 0 ].start( "r1", "/wt" )[ "port" ]
    assert own == server.PORT_BASE + offset
    taken  = { own }
    assert make( port_free=lambda port: port not in taken )[ 0 ].start( "r1", "/wt" )[ "port" ] == own + 1
    only_first = make( port_free=lambda port: port == server.PORT_BASE )[ 0 ].start( "r1", "/wt" )[ "port" ]
    assert only_first == server.PORT_BASE


def test_start_with_no_free_port_creates_nothing():
    servers, databases, docker = make( port_free=lambda port: False )
    assert code_of( lambda: servers.start( "r1", "/wt" ) ) == err.SERVER_START
    assert databases.history == [] and docker.calls == []


def test_start_without_a_passed_through_variable_creates_nothing_and_names_the_variable():
    servers, databases, docker = make( environ={ "PATH" : "/bin" } )
    with pytest.raises( err.HarnessError ) as caught: servers.start( "r1", "/wt" )
    assert caught.value.code == err.SERVER_START and "JWT_SECRET_KEY" in caught.value.detail
    assert databases.history == [] and docker.calls == []


def test_start_without_a_test_login_creates_nothing():
    servers, databases, docker = make( login=lambda: None )
    assert code_of( lambda: servers.start( "r1", "/wt" ) ) == err.DB_UNAVAILABLE
    assert databases.history == [] and docker.calls == []


def test_start_stops_at_a_refused_database_before_any_container_is_run():
    servers, databases, docker = make( databases=Databases( fail_create=True ) )
    assert code_of( lambda: servers.start( "r1", "/wt" ) ) == err.DB_UNAVAILABLE
    assert docker.calls == []


def test_a_refused_docker_run_removes_the_container_and_the_database_and_raises_the_cause():
    servers, databases, docker = make( docker=Docker( run_code=125 ) )
    with pytest.raises( err.HarnessError ) as caught: servers.start( "r1", "/wt" )
    assert caught.value.code == err.SERVER_START and "125" in caught.value.detail and "port is already allocated" in caught.value.detail
    assert databases.dbs == {} and docker.verbs() == [ "run", "rm" ] and getattr( caught.value, "__notes__", [] ) == []


def test_a_server_that_never_answers_is_removed_after_the_boot_timeout_and_the_database_with_it():
    servers, databases, docker = make( healthy_after=10 ** 9, timeout=3 )
    with pytest.raises( err.HarnessError ) as caught: servers.start( "r1", "/wt" )
    assert caught.value.code == err.SERVER_START and "within 3 seconds" in caught.value.detail
    assert databases.dbs == {} and docker.containers == set() and docker.verbs().count( "inspect" ) == 3


@pytest.mark.parametrize( "running", [ "false", "" ] )
def test_a_container_that_stopped_before_it_answered_reports_its_log_tail( running ):
    servers, databases, docker = make( docker=Docker( running=running ), healthy_after=5 )
    with pytest.raises( err.HarnessError ) as caught: servers.start( "r1", "/wt" )
    assert caught.value.code == err.SERVER_START and "Traceback: boot failed" in caught.value.detail
    assert databases.dbs == {} and docker.containers == set()


def test_a_cleanup_that_also_fails_is_noted_on_the_original_failure_and_never_replaces_it():
    servers, databases, docker = make( databases=Databases( fail_drop=True ), docker=Docker( run_code=125 ) )
    with pytest.raises( err.HarnessError ) as caught: servers.start( "r1", "/wt" )
    assert caught.value.code == err.SERVER_START
    assert any( "session of another role" in note for note in caught.value.__notes__ )


def test_a_failed_container_removal_during_cleanup_is_noted_too():
    servers, _, docker = make( docker=Docker( run_code=125, rm_code=1, rm_text="daemon unreachable" ) )
    with pytest.raises( err.HarnessError ) as caught: servers.start( "r1", "/wt" )
    assert any( "daemon unreachable" in note for note in caught.value.__notes__ )


def test_an_interrupt_during_the_boot_still_removes_what_was_started():
    servers, databases, docker = make()
    servers.health = lambda url: ( _ for _ in () ).throw( KeyboardInterrupt() )
    with pytest.raises( KeyboardInterrupt ): servers.start( "r1", "/wt" )
    assert databases.dbs == {} and docker.containers == set()


def test_stop_removes_the_container_and_the_database():
    servers, databases, docker = make()
    handle = servers.start( "r1", "/wt" )
    servers.stop( handle )
    assert databases.dbs == {} and docker.containers == set()


def test_stop_twice_is_not_an_error():
    servers, databases, docker = make()
    handle = servers.start( "r1", "/wt" )
    servers.stop( handle )
    servers.stop( handle )
    assert databases.history.count( ( "drop", handle[ "db_name" ] ) ) == 2


def test_stop_drops_the_database_even_when_the_container_removal_fails_and_reports_both_failures():
    servers, databases, _ = make( docker=Docker( rm_code=1, rm_text="daemon unreachable" ), databases=Databases( fail_drop=True ) )
    handle = { "container" : "c", "db_name" : "rrun_x" }
    with pytest.raises( err.HarnessError ) as caught: servers.stop( handle )
    assert caught.value.code == err.SERVER_STOP and "daemon unreachable" in caught.value.detail and "session of another role" in caught.value.detail
    assert databases.history == [ ( "drop", "rrun_x" ) ]


def test_stop_drops_the_database_when_only_the_container_removal_fails():
    servers, databases, _ = make( docker=Docker( rm_code=1, rm_text="daemon unreachable" ) )
    databases.dbs[ "rrun_x" ] = []
    assert code_of( lambda: servers.stop( { "container" : "c", "db_name" : "rrun_x" } ) ) == err.SERVER_STOP
    assert databases.dbs == {}


def test_the_default_ports_are_the_real_ones():
    servers = server.Servers( Databases(), "img" )
    assert ( servers.runner, servers.port_free, servers.health, servers.boot_timeout ) == ( server.run_command, server.port_is_free, server.answers_health, server.BOOT_TIMEOUT )
    import os
    assert servers.environ is os.environ


def test_run_command_returns_the_exit_code_and_both_output_streams():
    code, output = server.run_command( [ sys.executable, "-c", "import sys; print( 'out' ); print( 'err', file=sys.stderr ); sys.exit( 3 )" ] )
    assert code == 3 and output == "out\nerr"


def test_run_command_passes_the_given_environment():
    code, output = server.run_command( [ sys.executable, "-c", "import os; print( os.environ[ 'HARNESS_PROBE' ] )" ], env={ "HARNESS_PROBE" : "seen" } )
    assert ( code, output ) == ( 0, "seen" )


def test_run_command_reports_a_command_that_cannot_start_as_127():
    code, output = server.run_command( [ "/no/such/binary" ] )
    assert code == 127 and "FileNotFoundError" in output


def test_port_is_free_tells_a_listening_port_from_a_quiet_one():
    with socket.socket() as listener:
        listener.bind( ( "127.0.0.1", 0 ) )
        listener.listen()
        busy = listener.getsockname()[ 1 ]
        assert server.port_is_free( busy ) is False
    assert server.port_is_free( busy ) is True


class Handler( http.server.BaseHTTPRequestHandler ):
    """Answers /health with the status the server was given."""

    def do_GET( self ):
        """Answer with the configured status."""
        self.send_response( self.server.status )
        self.end_headers()

    def log_message( self, *args ):
        """Stay quiet."""


@pytest.mark.parametrize( "status, expected", [ ( 200, True ), ( 500, False ) ] )
def test_answers_health_reads_the_status_of_a_real_server( status, expected ):
    httpd        = http.server.HTTPServer( ( "127.0.0.1", 0 ), Handler )
    httpd.status = status
    thread       = threading.Thread( target=httpd.serve_forever, daemon=True )
    thread.start()
    try:
        assert server.answers_health( f"http://127.0.0.1:{httpd.server_address[ 1 ]}" ) is expected
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_answers_health_is_false_when_nothing_listens():
    with socket.socket() as probe:
        probe.bind( ( "127.0.0.1", 0 ) )
        quiet = probe.getsockname()[ 1 ]
    assert server.answers_health( f"http://127.0.0.1:{quiet}" ) is False
