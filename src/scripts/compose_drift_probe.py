#!/usr/bin/env python3
"""
Compose-drift probe for bounce-dev-server.sh (row 92374685).

`docker restart` REUSES a container, so a tmpfs, bind mount or environment value changed
in docker-compose.yml never reaches it. Only a recreate applies those. On 2026-09-15 the
MP3 upload answered 500 on two mornings because 68ce4a7b changed the dev tmpfs and
lupin-rest-dev, created 2026-09-11, had only ever been restarted.

This probe asks the container which compose file and service built it (its own
com.docker.compose.* labels), renders that service with `docker compose config`, and
compares three things against `docker inspect`:

    tmpfs        every compose tmpfs path, with its options
    mounts       every compose volume: type, source, target, read-only
    environment  every compose environment key and value (the container may carry more,
                 from its image; only compose's own keys are compared)

It prints the drifted FIELD NAMES only. Environment values are never printed, because
compose carries secrets there.

Exit codes, read by bounce-dev-server.sh:

    0  — NO DRIFT: a restart applies everything compose asks for.
   10  — DRIFT: the script recreates the container instead of restarting it.
   20  — UNKNOWN: docker or compose could not answer, or the output was malformed.
         The script FAILS OPEN and restarts as before — a broken probe must never block
         recovery of a wedged server.

Usage:
    compose_drift_probe.py <container>
"""
import json
import subprocess
import sys

EXIT_NO_DRIFT = 0
EXIT_DRIFT    = 10
EXIT_UNKNOWN  = 20

LABEL_CONFIG_FILES = "com.docker.compose.project.config_files"
LABEL_SERVICE      = "com.docker.compose.service"
LABEL_WORKING_DIR  = "com.docker.compose.project.working_dir"
LABEL_PROJECT      = "com.docker.compose.project"

RECREATE_ARG_PREFIX = "RECREATE_ARG="


def compose_tmpfs( service ):
    """
    Normalize compose's tmpfs entries to { path: options }.

    Requires:
        - service is one rendered compose service dict

    Ensures:
        - returns {} when the service declares no tmpfs
        - accepts compose's string or list form; "path" alone maps to ""
    """
    raw = service.get( "tmpfs" ) or [ ]
    if isinstance( raw, str ): raw = [ raw ]
    entries = { }
    for entry in raw:
        path, _, options = entry.partition( ":" )
        entries[ path ] = options
    return entries


def compose_mounts( service, volume_names ):
    """
    Normalize compose's long-form volumes to a set of ( type, source, target, read_only ).

    Requires:
        - service is one rendered compose service dict (`docker compose config` always
          emits the long form)
        - volume_names maps a compose volume key to its rendered top-level `name`

    Ensures:
        - read_only defaults to False, as compose does
        - a named volume's source is the name docker actually created. The service says
          "claude-creds-dev"; docker calls it "lupin_claude-creds-dev", with the project
          prefix. Comparing the short name reported drift on every container (measured
          2026-09-15 on both lupin-rest-dev and lupin-rest-test before this mapping).
    """
    mounts = set()
    for v in service.get( "volumes" ) or [ ]:
        source = v.get( "source" )
        if v[ "type" ] == "volume": source = volume_names.get( source, source )
        mounts.add( ( v[ "type" ], source, v[ "target" ], bool( v.get( "read_only", False ) ) ) )
    return mounts


def inspect_mounts( container ):
    """
    Normalize `docker inspect` Mounts to the same tuple shape as compose_mounts.

    Requires:
        - container is one `docker inspect` object

    Ensures:
        - a named volume is keyed by its Name, which is what compose calls its source
    """
    mounts = set()
    for m in container.get( "Mounts" ) or [ ]:
        source = m[ "Name" ] if m[ "Type" ] == "volume" else m[ "Source" ]
        mounts.add( ( m[ "Type" ], source, m[ "Destination" ], not m[ "RW" ] ) )
    return mounts


def inspect_env( container ):
    """
    Split `docker inspect` Config.Env into { key: value }.

    Requires:
        - container is one `docker inspect` object
    """
    env = { }
    for pair in container[ "Config" ][ "Env" ] or [ ]:
        key, _, value = pair.partition( "=" )
        env[ key ] = value
    return env


def drifted_fields( service, container, volume_names ):
    """
    Name every compose value the running container does not carry.

    Requires:
        - service is the rendered compose service; container is its `docker inspect` object
        - volume_names maps each compose volume key to its rendered `name`

    Ensures:
        - returns a sorted list of human-readable field names, empty when nothing drifted
        - a mount the container has and compose no longer declares counts as drift too,
          since a recreate would remove it
        - environment entries name the KEY only, never the value
    """
    fields = [ ]

    want_tmpfs = compose_tmpfs( service )
    have_tmpfs = container[ "HostConfig" ].get( "Tmpfs" ) or { }
    for path in sorted( set( want_tmpfs ) | set( have_tmpfs ) ):
        if want_tmpfs.get( path ) != have_tmpfs.get( path ):
            fields.append( f"tmpfs {path}" )

    want_mounts = compose_mounts( service, volume_names )
    have_mounts = inspect_mounts( container )
    for target in sorted( { m[ 2 ] for m in want_mounts ^ have_mounts } ):
        fields.append( f"mount {target}" )

    have_env = inspect_env( container )
    for key, value in sorted( ( service.get( "environment" ) or { } ).items() ):
        if have_env.get( key ) != ( "" if value is None else str( value ) ):
            fields.append( f"env {key}" )

    return fields


def run_json( argv, env=None ):
    """
    Run a command and parse its stdout as JSON.

    Requires:
        - argv is a non-empty list of strings
        - env is None (inherit) or the complete environment for the child

    Ensures:
        - returns the parsed JSON

    Raises:
        - RuntimeError naming the command and its stderr when it exits non-zero
        - ValueError (json.JSONDecodeError) when stdout is not JSON
        - OSError when the executable cannot be run
    """
    result = subprocess.run( argv, capture_output=True, text=True, timeout=30, env=env )
    if result.returncode != 0:
        raise RuntimeError( f"{' '.join( argv[ :3 ] )} exited {result.returncode}: {result.stderr.strip()[ :300 ]}" )
    return json.loads( result.stdout )


def compose_argv( labels ):
    """
    The `docker compose` prefix that addresses the project a container was created from.

    Requires:
        - labels are the container's Config.Labels

    Ensures:
        - names the project, its directory and every config file from the container's OWN
          labels, never the caller's tree. The probe renders with this prefix and the bounce
          script recreates with it, so both act on the same compose tree. Before this, the
          recreate used $LUPIN_ROOT: run from a worktree, that compares one tree and recreates
          from another, under a project name taken from the worktree directory (María's review
          of 34a2764a, 2026-09-15)

    Raises:
        - KeyError when a compose label is missing
    """
    argv = [ "docker", "compose", "--project-name", labels[ LABEL_PROJECT ],
             "--project-directory", labels[ LABEL_WORKING_DIR ] ]
    for config_file in labels[ LABEL_CONFIG_FILES ].split( "," ):
        argv += [ "-f", config_file ]
    return argv


def probe( container_name, runner=run_json, environ=None ):
    """
    Compare the running container against the compose service that built it.

    Requires:
        - container_name names a container created by docker compose
        - runner( argv, env=None ) returns parsed JSON or raises, as run_json does
        - environ is None (compose inherits this process's environment) or the complete
          environment compose should interpolate from. Inheriting is deliberate: the
          compose file takes some required values from the shell, so the probe answers
          "what would a recreate from THIS environment produce", which is the bounce's question

    Ensures:
        - returns ( exit_code, fields, recreate ): ( EXIT_NO_DRIFT, [], argv ),
          ( EXIT_DRIFT, [names], argv ), or ( EXIT_UNKNOWN, [reason], [] )
        - recreate is the full `docker compose ... up -d --force-recreate --no-deps <service>`
          argv, built from the same labels the comparison used
        - never raises
    """
    try:
        container = runner( [ "docker", "inspect", container_name ] )[ 0 ]
        labels    = container[ "Config" ][ "Labels" ] or { }
        service   = labels[ LABEL_SERVICE ]
        prefix    = compose_argv( labels )
        rendered  = runner( prefix + [ "config", "--format", "json", service ], env=environ )
        names     = { key: spec[ "name" ] for key, spec in ( rendered.get( "volumes" ) or { } ).items() }
        fields    = drifted_fields( rendered[ "services" ][ service ], container, names )
    except ( OSError, ValueError, RuntimeError, KeyError, IndexError, TypeError, subprocess.TimeoutExpired ) as e:
        return EXIT_UNKNOWN, [ f"{type( e ).__name__}: {e}" ], [ ]
    recreate = prefix + [ "up", "-d", "--force-recreate", "--no-deps", service ]
    return ( EXIT_DRIFT if fields else EXIT_NO_DRIFT ), fields, recreate


def main( argv=None, runner=run_json ):
    """
    CLI entry: print the verdict and return the exit code.

    Requires:
        - argv is sys.argv[ 1: ]-shaped

    Ensures:
        - returns EXIT_UNKNOWN with a usage line when no container is named
        - on DRIFT, also prints one `RECREATE_ARG=<arg>` line per argument of the recreate
          command, which bounce-dev-server.sh reads so it recreates exactly what was compared
    """
    argv = sys.argv[ 1: ] if argv is None else argv
    if len( argv ) != 1:
        print( "usage: compose_drift_probe.py <container>", file=sys.stderr )
        return EXIT_UNKNOWN
    code, fields, recreate = probe( argv[ 0 ], runner=runner )
    if code == EXIT_NO_DRIFT:
        print( f"compose drift: none — {argv[ 0 ]} matches its compose service" )
    elif code == EXIT_DRIFT:
        print( f"compose drift: {argv[ 0 ]} lacks {len( fields )} compose value(s) a restart would NOT apply:" )
        for field in fields: print( f"  - {field}" )
        for arg in recreate: print( f"{RECREATE_ARG_PREFIX}{arg}" )
    else:
        print( f"compose drift: UNKNOWN for {argv[ 0 ]} ({fields[ 0 ]})" )
    return code


if __name__ == "__main__":  # pragma: no cover — the process entry; main() is tested directly
    sys.exit( main() )
