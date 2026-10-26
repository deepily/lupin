"""
Importing `cosa_voice_mcp` must leave the SIGTERM handler alone.

The module used to install its SIGTERM handler at import. A test process that imported it
turned an outside SIGTERM into `SystemExit(0)` inside whichever test was running. That test
failed with an exit it never asked for. The server entry point installs the handler instead.
"""

import pathlib
import signal
import subprocess
import sys

_IMPORT_PROBE = (
    "import signal, sys; sys.path.insert( 0, sys.argv[ 1 ] ); "
    "before = signal.getsignal( signal.SIGTERM ); "
    "import lupin_mcp.cosa_voice_mcp; "
    "print( 'UNCHANGED' if signal.getsignal( signal.SIGTERM ) is before else 'REPLACED' )"
)


def test_importing_the_module_does_not_replace_the_sigterm_handler( tmp_path ):
    """A fresh interpreter that imports the module keeps its own SIGTERM handler."""
    from lupin_mcp import cosa_voice_mcp as mcp_module     # imported here: the suite evicts modules between tests
    src = str( pathlib.Path( mcp_module.__file__ ).parents[ 1 ] )
    out = subprocess.run( [ sys.executable, "-I", "-c", _IMPORT_PROBE, src ], capture_output=True, text=True, timeout=120 )
    assert out.stdout.strip().splitlines()[ -1 ] == "UNCHANGED", out.stdout + out.stderr


def test_the_entry_point_installs_the_handler():
    """install_sigterm_handler sets _handle_sigterm, and the handler exits with code 0."""
    from lupin_mcp import cosa_voice_mcp as mcp_module
    previous = signal.getsignal( signal.SIGTERM )
    try:
        mcp_module.install_sigterm_handler()
        assert signal.getsignal( signal.SIGTERM ) is mcp_module._handle_sigterm
    finally:
        signal.signal( signal.SIGTERM, previous )
    try:
        mcp_module._handle_sigterm( signal.SIGTERM, None )
    except SystemExit as stop:
        assert stop.code == 0
    else:
        raise AssertionError( "the handler must exit" )


def _main_block_calls():
    """The names of the plain function calls in the module's `__main__` block, in source order."""
    import ast
    import pathlib
    from lupin_mcp import cosa_voice_mcp as mcp_module
    tree = ast.parse( pathlib.Path( mcp_module.__file__ ).read_text() )
    blocks = [ n for n in tree.body if isinstance( n, ast.If ) and ast.unparse( n.test ) == "__name__ == '__main__'" ]
    per_block = [ [ ast.unparse( c.func ) for stmt in b.body for c in ast.walk( stmt ) if isinstance( c, ast.Call ) ] for b in blocks ]
    servers = [ calls for calls in per_block if "mcp.run" in calls ]
    assert len( servers ) == 1, f"expected one __main__ block that runs the server, found {len( servers )}"
    return servers[ 0 ]


def test_the_main_block_installs_the_handler_before_the_server_runs():
    """The __main__ block calls install_sigterm_handler, and does so before mcp.run."""
    calls = _main_block_calls()
    assert "install_sigterm_handler" in calls
    assert "mcp.run" in calls
    assert calls.index( "install_sigterm_handler" ) < calls.index( "mcp.run" )
