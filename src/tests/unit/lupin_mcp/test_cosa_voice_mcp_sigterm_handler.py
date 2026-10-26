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
