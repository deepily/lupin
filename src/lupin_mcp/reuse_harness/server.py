"""
The server port of the run harness: one container and one database per run.

A run's container serves the run's worktree on a port of its own and reads the run's own database. Secrets reach the
container as variables the harness passes through by name, so no value appears in a command line or a log. Whatever
fails after the database exists, the database and the container are removed, and any leftover is noted on the failure.
"""
import hashlib
import os
import socket
import time
import urllib.error
import urllib.request

import cosa.utils.dotenv_password as dp
from lupin_mcp.reuse_harness import commands
from lupin_mcp.reuse_harness import errors as err
from lupin_mcp.reuse_harness import run as harness

PORT_BASE       = 18000
PORT_SPAN       = 1000
INNER_PORT      = 7999
BOOT_TIMEOUT    = 180
POLL_SECONDS    = 1
LOG_TAIL        = 20
MOUNT_AT        = "/var/lupin"
# Variables the container receives from the harness's own environment, by name only. DB_USER and DB_PASSWORD come from the test login.
PASSED_THROUGH  = ( "JWT_SECRET_KEY", )
LOGIN_VARIABLES = ( "DB_USER", "DB_PASSWORD" )
COMMAND         = "cd /var/lupin/src && exec python3 -m lupin_app.main"


def port_is_free( port ):
    """Say whether nothing on this host is listening on the port."""
    with socket.socket( socket.AF_INET, socket.SOCK_STREAM ) as probe:
        return probe.connect_ex( ( "127.0.0.1", port ) ) != 0


def answers_health( url ):
    """Say whether GET <url>/health answers 200."""
    try:
        with urllib.request.urlopen( f"{url}/health", timeout=5 ) as response: return response.status == 200
    except ( urllib.error.URLError, OSError ): return False


class Servers:
    """Starts, inspects and stops the server of each run."""

    def __init__( self, databases, image, sender_key, runner=commands.run_command, environ=None, login=dp.clone_login, port_free=port_is_free,
                  health=answers_health, sleep=time.sleep, clock=time.monotonic, boot_timeout=BOOT_TIMEOUT ):
        """
        Remember the ports this adapter works through.

        Requires:
            - databases has create, drop and is_fresh
            - image names the server image, the one the test service of docker-compose.yml runs
            - sender_key is the plaintext key the run's tests send; seed stores its hash in the run's database
            - runner( argv, env ) returns ( exit code, output ); login() returns ( user, password ) or None

        Ensures:
            - nothing is started yet; environ defaults to os.environ
        """
        self.databases    = databases
        self.image        = image
        self.sender_key   = sender_key
        self.runner       = runner
        self.environ      = os.environ if environ is None else environ
        self.login        = login
        self.port_free    = port_free
        self.health       = health
        self.sleep        = sleep
        self.clock        = clock
        self.boot_timeout = boot_timeout

    def start( self, run_id, path ):
        """
        Create the run's database, start its container and wait until the server answers.

        Requires:
            - run_id is a non-empty string and path is the run's worktree
            - the environment holds every variable of PASSED_THROUGH and a test-role login exists

        Ensures:
            - returns { url, container, db_name, port } with the names derived from run_id
            - the container binds 127.0.0.1 only and mounts path read-write with an empty .env over the repo's
            - on any failure the container and the database are removed before the failure is raised

        Raises:
            - HarnessError SERVER_START naming a missing variable, a missing port, a refused docker run or a server that never answered
            - HarnessError DB_UNAVAILABLE from the database port
        """
        env       = self._container_env()
        name      = harness.db_name( run_id )
        container = harness.container_name( run_id )
        port      = self._pick_port( run_id )
        self.databases.create( name )
        try:
            code, output = self.runner( self._docker_run( container, name, port, path ), env )
            if code != 0: raise err.HarnessError( err.SERVER_START, f"docker run answered {code}: {output}" )
            url = f"http://127.0.0.1:{port}"
            self._wait_until_healthy( url, container )
        except BaseException as failure:
            for leftover in self._remove( container, name ): failure.add_note( f"cleanup also failed: {leftover}" )
            raise
        return { "url" : url, "container" : container, "db_name" : name, "port" : port }

    def seed( self, handle ):
        """
        Give the run's database the account that owns the sender key.

        Requires:
            - the server answered health, so the database is migrated; the freshness check came first

        Raises:
            - HarnessError DB_UNAVAILABLE from the database port
        """
        self.databases.provision_sender_key( handle[ "db_name" ], self.sender_key )

    def db_is_fresh( self, handle ):
        """Say whether the run's database holds no account and no notification yet."""
        return self.databases.is_fresh( handle[ "db_name" ] )

    def stop( self, handle ):
        """
        Remove the container, then drop the database.

        Requires:
            - handle is the result of start, or one for a start that failed halfway

        Ensures:
            - both removals are attempted even when the first fails
            - a container or database already gone is not an error

        Raises:
            - HarnessError SERVER_STOP naming every removal that failed
        """
        failures = self._remove( handle[ "container" ], handle[ "db_name" ] )
        if failures: raise err.HarnessError( err.SERVER_STOP, "; ".join( failures ) )

    def _container_env( self ):
        """Build the environment of the docker command, so secret values never enter its arguments."""
        missing = [ key for key in PASSED_THROUGH if not self.environ.get( key ) ]
        if missing: raise err.HarnessError( err.SERVER_START, f"the harness environment lacks {missing}" )
        found = self.login()
        if found is None: raise err.HarnessError( err.DB_UNAVAILABLE, "no test-role login: set LUPIN_TEST_DB_USER and LUPIN_TEST_DB_PASSWORD" )
        env = dict( self.environ )
        env.update( dict( zip( LOGIN_VARIABLES, found ) ) )
        return env

    def _pick_port( self, run_id ):
        """Pick the first free port at or after the run's own offset, wrapping inside the range."""
        offset = int( hashlib.sha1( run_id.encode( "utf-8" ) ).hexdigest()[ :8 ], 16 ) % PORT_SPAN
        for step in range( PORT_SPAN ):
            port = PORT_BASE + ( offset + step ) % PORT_SPAN
            if self.port_free( port ): return port
        raise err.HarnessError( err.SERVER_START, f"no free port in {PORT_BASE}-{PORT_BASE + PORT_SPAN - 1}" )

    def _docker_run( self, container, db_name, port, path ):
        """Build the docker run command of one run's server; secrets are named, never valued."""
        argv = [ "docker", "run", "-d", "--init", "--name", container, "--user", "1001:1001", "-p", f"127.0.0.1:{port}:{INNER_PORT}",
                 "--add-host", "host.docker.internal:host-gateway", "-v", f"{path}:{MOUNT_AT}", "-v", f"/dev/null:{MOUNT_AT}/.env:ro",
                 "-e", f"LUPIN_ROOT={MOUNT_AT}", "-e", "LUPIN_ENV=testing", "-e", f"DB_NAME={db_name}", "-e", "DB_HOST=host.docker.internal", "-e", "DB_PORT=5432" ]
        for key in ( *PASSED_THROUGH, *LOGIN_VARIABLES ): argv += [ "-e", key ]
        return argv + [ self.image, "bash", "-c", COMMAND ]

    def _wait_until_healthy( self, url, container ):
        """Poll /health until it answers, the container stops, or the boot timeout passes."""
        started = self.clock()
        while self.clock() - started < self.boot_timeout:
            if self.health( url ): return
            code, output = self.runner( [ "docker", "inspect", "-f", "{{.State.Running}}", container ], None )
            if code != 0 or output != "true":
                _, logs = self.runner( [ "docker", "logs", "--tail", str( LOG_TAIL ), container ], None )
                raise err.HarnessError( err.SERVER_START, f"the container stopped before it answered: {logs}" )
            self.sleep( POLL_SECONDS )
        raise err.HarnessError( err.SERVER_START, f"{url}/health did not answer within {self.boot_timeout} seconds" )

    def _remove( self, container, db_name ):
        """Remove the container, then the database, and return the removals that failed."""
        failures     = []
        code, output = self.runner( [ "docker", "rm", "-f", container ], None )
        if code != 0 and "No such container" not in output: failures.append( f"docker rm answered {code}: {output}" )
        try:
            self.databases.drop( db_name )
        except err.HarnessError as error:
            failures.append( str( error ) )
        return failures
