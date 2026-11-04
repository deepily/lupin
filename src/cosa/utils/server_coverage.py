"""
Fold the :8000 test server's coverage of the app entry point into the coverage gate.

The entry point is `src/lupin_app/main.py`. Its start-up work and `__main__` block run only
when a real server boots, so no unit test reaches them. The test container can run its server
under `coverage run` (env `LUPIN_SERVER_COVERAGE=1`), and the gate reads that data back.

Three rules shape this module:

  1. Only main.py's arcs are taken from the server's data. The server also touched other files,
     from whatever tree it booted on. Adding those would double-count them against the unit and
     cosa tiers.
  2. Staleness is the content hash of main.py, the value `git hash-object` prints. It is not the
     tree HEAD. Every commit moves HEAD, so the gate would be inconclusive almost always. Only
     main.py's own bytes decide whether the server's line numbers still fit.
  3. Anything short of a usable measurement is an inconclusive verdict, which is gate exit 2.
     It is never a pass and never a floor breach, because main.py is always in the frame.

Command line, run as `python -m cosa.utils.server_coverage <verb>`:

- `write-boot`: at a covered boot, clear old data and record main.py's hash.
- `data-file`: print the path the server writes its parallel data files beside.
- `verdict`: print whether the data is usable, and exit 0 if so or 2 if not.
- `fold`: run the verdict, then add main.py's arcs to `--target`, and exit 0 or 2.
"""

import argparse
import glob
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

import coverage
from coverage.exceptions import CoverageException

import cosa.utils.util as cu

CONTAINER_ROOT = "/var/lupin"
MAIN_PY_REL    = "src/lupin_app/main.py"
SERVER_DIR_REL = "io/coverage/server"
BOOT_NAME      = "boot.json"
DATA_PREFIX    = ".coverage"
DIR_ENV        = "LUPIN_SERVER_COVERAGE_DIR"

RUN_HINT = ( "Produce it with one scheduled :8000 run: bounce lupin-rest-test with "
             "LUPIN_SERVER_COVERAGE=1 (docker compose up -d --force-recreate lupin-rest-test), "
             "submit a suite through POST /api/v2/submit, stop the container gracefully "
             "(docker stop, never kill), then re-run the gate." )


def server_dir( root=None ):
    """
    Return the directory the server's coverage data lives in.

    Requires:
        - root is None or a project root path

    Ensures:
        - returns the value of LUPIN_SERVER_COVERAGE_DIR when it is set and non-empty
        - otherwise returns <root>/io/coverage/server, with root defaulting to the project root
    """
    override = os.environ.get( DIR_ENV )
    if override: return override
    root = cu.get_project_root() if root is None else root
    return os.path.join( root, SERVER_DIR_REL )


def blob_hash( path ):
    """
    Return the hash `git hash-object <path>` prints for a file, without running git.

    Requires:
        - path names a readable file

    Ensures:
        - returns a 40-character hex string equal to git's blob id for the file's bytes
        - the container has no git binary guaranteed, which is why this is computed here

    Raises:
        - FileNotFoundError if path does not exist
    """
    with open( path, "rb" ) as handle: body = handle.read()
    return hashlib.sha1( b"blob " + str( len( body ) ).encode() + b"\0" + body ).hexdigest()


def data_files( directory ):
    """
    List the parallel data files `coverage run --parallel-mode` wrote in a directory.

    Requires:
        - directory is a path, existing or not

    Ensures:
        - returns a sorted list of paths named <DATA_PREFIX>.<suffix>
        - returns an empty list when the directory is missing or holds none
        - never lists the boot sidecar
    """
    return sorted( glob.glob( os.path.join( glob.escape( directory ), DATA_PREFIX + ".*" ) ) )


def reset( directory ):
    """
    Remove the previous boot's data and sidecar so an old run cannot pass for this one.

    Requires:
        - directory is a path, existing or not

    Ensures:
        - the directory exists afterwards
        - it holds no data file and no sidecar
    """
    os.makedirs( directory, exist_ok=True )
    for stale in data_files( directory ) + [ os.path.join( directory, BOOT_NAME ) ]:
        if os.path.exists( stale ): os.remove( stale )


def write_boot( directory, main_py ):
    """
    Start a covered boot: clear the previous data and record the hash of main.py.

    Requires:
        - main_py names the readable main.py this server is about to run

    Ensures:
        - the sidecar holds main_py_hash (blob_hash of main_py) and boot_utc
        - returns the sidecar's path
    """
    reset( directory )
    boot = os.path.join( directory, BOOT_NAME )
    body = { "main_py_hash": blob_hash( main_py ),
             "boot_utc"    : datetime.now( timezone.utc ).isoformat() }
    with open( boot, "w", encoding="utf-8" ) as handle: json.dump( body, handle )
    return boot


def _main_arcs( data_file, container_root ):
    """
    Read main.py's arcs from one server data file.

    Requires:
        - data_file is a path

    Ensures:
        - returns ( reason, arcs ) where reason is None and arcs is a list on success
        - reason is "unreadable" when coverage cannot open the file
        - reason is "empty" when the file records no measured file at all
        - reason is "main-missing" when main.py is not among the measured files
        - reason is "no-arcs" when main.py was measured by line only
    """
    data = coverage.CoverageData( basename=data_file )
    try:
        data.read()
        measured = data.measured_files()
    except ( CoverageException, OSError ) as error:
        return "unreadable", str( error )
    if not measured: return "empty", None
    wanted = os.path.normpath( os.path.join( container_root, MAIN_PY_REL ) )
    for name in measured:
        if os.path.normpath( name ) != wanted: continue
        if not data.has_arcs(): return "no-arcs", None
        return None, list( data.arcs( name ) )
    return "main-missing", None


def _read_boot( directory ):
    """
    Read the sidecar.

    Requires:
        - directory is a path

    Ensures:
        - returns ( None, hash ) when the sidecar holds a main_py_hash string
        - returns ( "no-boot", None ) when there is no sidecar
        - returns ( "bad-boot", None ) when it is not JSON or lacks a string main_py_hash
    """
    boot = os.path.join( directory, BOOT_NAME )
    if not os.path.exists( boot ): return "no-boot", None
    try:
        with open( boot, encoding="utf-8" ) as handle: recorded = json.load( handle )
        value = recorded[ "main_py_hash" ]
    except ( ValueError, KeyError, TypeError, OSError ):
        return "bad-boot", None
    if not isinstance( value, str ): return "bad-boot", None
    return None, value


def verdict( directory, main_py, container_root=CONTAINER_ROOT ):
    """
    Decide whether the server's data can stand in for main.py's runtime coverage.

    Requires:
        - directory is the server data directory, existing or not
        - main_py names the main.py of the tree the gate is measuring

    Ensures:
        - returns ( reason, message, arcs )
        - reason is "ok" with a list of arcs only when every check passed
        - otherwise reason is one of no-data, no-boot, bad-boot, stale, unreadable, empty,
          main-missing, no-arcs, and arcs is None
        - every message for a non-ok reason names the scheduled :8000 run that produces it
    """
    files = data_files( directory )
    if not files:
        return "no-data", f"no server coverage data in {directory}. {RUN_HINT}", None
    problem, recorded = _read_boot( directory )
    if problem == "no-boot":
        return problem, f"server data is present but {BOOT_NAME} is not, so its main.py is unknown. {RUN_HINT}", None
    if problem == "bad-boot":
        return problem, f"{BOOT_NAME} in {directory} is unreadable or lacks main_py_hash. {RUN_HINT}", None
    current = blob_hash( main_py )
    if recorded != current:
        return "stale", ( f"server data was recorded on main.py {recorded[ :12 ]} but this tree has "
                          f"{current[ :12 ]}; its line numbers no longer fit. {RUN_HINT}" ), None
    arcs = set()
    for path in files:
        reason, found = _main_arcs( path, container_root )
        if reason is not None:
            return reason, f"{path}: {reason} {found if found else ''}. {RUN_HINT}".replace( " .", "." ), None
        arcs.update( found )
    return "ok", f"server data covers main.py {current[ :12 ]}", sorted( arcs )


def fold( directory, main_py, target, container_root=CONTAINER_ROOT ):
    """
    Add main.py's arcs from the server data to the gate's data file.

    Requires:
        - target is the gate's data file; it may already hold the unit and cosa tiers
        - main_py is the main.py of the tree the gate is measuring

    Ensures:
        - returns ( reason, message ) as verdict does
        - on "ok", target gains main_py's arcs under main_py's own path and nothing else
        - on any other reason, target is left untouched
    """
    reason, message, arcs = verdict( directory, main_py, container_root )
    if reason != "ok": return reason, message
    data = coverage.CoverageData( basename=target )
    data.read()
    data.add_arcs( { os.path.abspath( main_py ): arcs } )
    data.write()
    return reason, message


def _main( argv=None ):
    """
    Run one verb of the command line.

    Requires:
        - argv is a list of arguments or None for sys.argv

    Ensures:
        - returns 0 on success and 2 when the data is not usable
    """
    parser = argparse.ArgumentParser( prog="server_coverage" )
    parser.add_argument( "verb", choices=[ "write-boot", "data-file", "verdict", "fold" ] )
    parser.add_argument( "--target", default=None )
    args      = parser.parse_args( argv )
    directory = server_dir()
    main_py   = os.path.join( cu.get_project_root(), MAIN_PY_REL )
    if args.verb == "write-boot":
        print( write_boot( directory, main_py ) )
        return 0
    if args.verb == "data-file":
        print( os.path.join( directory, DATA_PREFIX ) )
        return 0
    if args.verb == "verdict":
        reason, message, _ = verdict( directory, main_py )
    else:
        reason, message = fold( directory, main_py, args.target )
    print( f"[server-coverage] {reason}: {message}" )
    return 0 if reason == "ok" else 2


if __name__ == "__main__":
    sys.exit( _main() )
