"""
The child of the work-alike run-check: runs one function on given inputs and reports.

It is started by run_check as `python -s -P <this file>` inside a bubblewrap sandbox: no network, no host files, a memory-only work folder.
It reads one JSON request on stdin and writes one JSON answer on stdout.
"""
import asyncio
import contextlib
import copy
import hashlib
import inspect
import io
import json
import os
import re
import resource
import sys

CPU_SECONDS  = 4
MEMORY_BYTES = 512 * 1024 * 1024
FILE_BYTES   = 1024 * 1024
ADDRESS_RE   = re.compile( r"0x[0-9a-fA-F]+" )


def limit_resources():
    """
    Cap this process's CPU time, memory, written file size and number of processes.

    Ensures:
        - later allocations over MEMORY_BYTES fail, CPU time over CPU_SECONDS ends the process, and no file grows past FILE_BYTES
        - no new process or thread can start, so a fork or exec fails
    """
    resource.setrlimit( resource.RLIMIT_CPU, ( CPU_SECONDS, CPU_SECONDS ) )
    resource.setrlimit( resource.RLIMIT_AS, ( MEMORY_BYTES, MEMORY_BYTES ) )
    resource.setrlimit( resource.RLIMIT_FSIZE, ( FILE_BYTES, FILE_BYTES ) )
    resource.setrlimit( resource.RLIMIT_NPROC, ( 0, 0 ) )


def settle( value ):
    """Return repr( value ) with memory addresses masked, so equal objects compare equal."""
    return ADDRESS_RE.sub( "0x?", repr( value ) )


def folder_state( folder ):
    """Return { relative path: sha256 of content } for every file under folder."""
    state = {}
    for here, _, names in os.walk( folder ):
        for name in names:
            path = os.path.join( here, name )
            with open( path, "rb" ) as f: state[ os.path.relpath( path, folder ) ] = hashlib.sha256( f.read() ).hexdigest()
    return state


def clear_folder( folder ):
    """Remove every file under folder, leaving the folder itself."""
    for here, _, names in os.walk( folder ):
        for name in names: os.remove( os.path.join( here, name ) )


def run_case( fn, args, folder ):
    """
    Call fn once on a deep copy of args and describe the outcome.

    Requires:
        - the current working folder is folder

    Ensures:
        - returns { returned, raised, args_after, stdout, files }, each a string or mapping that compares by equality
        - raised is the exception's type name, or None; a coroutine function is run to completion
        - the folder is empty again afterwards
    """
    live, out, outcome = copy.deepcopy( args ), io.StringIO(), { "returned": None, "raised": None }
    with contextlib.redirect_stdout( out ):
        try:
            result = fn( *live )
            if inspect.isawaitable( result ): result = asyncio.run( result )
            outcome[ "returned" ] = settle( result )
        except Exception as exc:
            outcome[ "raised" ] = type( exc ).__name__
    outcome.update( args_after=settle( live ), stdout=out.getvalue(), files=folder_state( folder ) )
    clear_folder( folder )
    return outcome


def run_request( request, folder ):
    """
    Define the function from its source and run it on every argument list.

    Requires:
        - request is { source, name, cases } with cases a list of argument lists

    Ensures:
        - returns { "outcomes": [ run_case result per case ] }
        - returns { "setup_error": <type name> } when the source does not define the name
    """
    space = {}
    try:
        exec( compile( request[ "source" ], "<run-check>", "exec" ), space )
        fn = space[ request[ "name" ] ]
    except Exception as exc:
        return { "setup_error": type( exc ).__name__ }
    return { "outcomes": [ run_case( fn, args, folder ) for args in request[ "cases" ] ] }


def main( stdin=None, stdout=None ):
    """
    Read one request, limit the process, run it, print the answer as JSON.

    Ensures:
        - returns 0 after writing the answer
    """
    request = json.load( stdin or sys.stdin )
    limit_resources()
    json.dump( run_request( request, os.getcwd() ), stdout or sys.stdout )
    return 0


if __name__ == "__main__":  # pragma: no cover -- only the child process takes this branch; main() is tested in-process and by a real child
    sys.exit( main() )
