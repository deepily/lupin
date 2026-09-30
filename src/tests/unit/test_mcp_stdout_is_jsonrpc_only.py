"""
The cosa-voice MCP server's stdout carries JSON-RPC and nothing else (row e4dc53a9).

THE INCIDENT, 2026-09-18. Rick answered Tiffany's four-question card at 01:00:54.69Z;
the :7999 server yielded the answer frame. Seven milliseconds later Claude Code logged
"Ignoring non-JSON line on stdout: JSON Parse error: Invalid number", no tool result ever
arrived, and the call failed at CC's 660 s ceiling. That session's stdout carried 141
non-JSON lines — ConfigurationManager's dump, printed from inside each ask. Claude Code
skips a whole junk line, but a print with no trailing newline lands IN FRONT of the next
frame, and that frame is then unparseable and dropped.

⚠️ THE FIX IS PROCESS-WIDE, NOT A SILENCED PRINT (Mr. Radio's ruling). Muting one
print leaves the channel open to the next one. `reserve_stdout_for_jsonrpc` gives the
transport a private copy of the real stdout and points fd 1 at stderr, so a `print()`,
a `sys.stdout.write`, a C extension and an inherited child all write to stderr.

THE SUBPROCESS ARMS DRIVE A REAL FastMCP OVER REAL PIPES, because the defect lives in
how two writers share one fd; an in-process fake would agree with whatever the guard
did. The CONTROL arm runs the same server without the guard and must be corrupted —
without it, a clean result from the fixed arm proves nothing.
"""
import io
import json
import os
import select
import subprocess
import sys
import textwrap
import time
import types
from pathlib import Path

from lupin_mcp.jsonrpc_stdout import reserve_stdout_for_jsonrpc

SRC = Path( __file__ ).resolve().parents[ 2 ]

# A tool that writes the incident's shape twice: a Python print with no newline, and a
# raw fd-1 write with none either (C code and children write at the fd, not through
# sys.stdout). Both are flushed so the corruption is deterministic rather than a race.
_PROBE_SERVER = textwrap.dedent( '''
    import os, sys
    if sys.argv[ 1 ] == "guard":
        from lupin_mcp.jsonrpc_stdout import reserve_stdout_for_jsonrpc
        reserve_stdout_for_jsonrpc()
    from fastmcp import FastMCP

    mcp = FastMCP( "probe" )

    @mcp.tool
    def stray() -> str:
        print( "-12", end="" )
        sys.stdout.flush()
        os.write( 1, b"-34" )
        return "the answer"

    mcp.run( show_banner=False )
''' )

_REQUESTS = [
    { "jsonrpc": "2.0", "id": 1, "method": "initialize",
      "params": { "protocolVersion": "2025-06-18", "capabilities": {},
                  "clientInfo": { "name": "t", "version": "0" } } },
    { "jsonrpc": "2.0", "method": "notifications/initialized" },
    { "jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": { "name": "stray", "arguments": {} } },
]


def _read_line( proc, deadline ):
    """One stdout line, or None once the deadline passes."""
    while time.monotonic() < deadline:
        ready, _, _ = select.select( [ proc.stdout ], [], [], 0.1 )
        if ready:
            return proc.stdout.readline()
    return None


def _drive( tmp_path, arm ):
    """
    The handshake, THEN the tool call — one at a time.

    ⚠️ SEQUENCED ON PURPOSE. Sent together, the three requests are served concurrently
    and the stray bytes land in front of WHICHEVER frame is written next — measured: 2 of
    6 bare runs corrupted the initialize reply instead and the tool result survived. A
    frame was lost either way, but a control that loses a different frame each run
    cannot say which one. Waiting for the handshake reply first makes the tool result
    the only frame the stray write can hit.
    """
    script = tmp_path / "probe_server.py"
    script.write_text( _PROBE_SERVER, encoding="utf-8" )
    env  = dict( os.environ, PYTHONPATH=str( SRC ) )
    proc = subprocess.Popen(
        [ sys.executable, str( script ), arm ],
        stdin = subprocess.PIPE, stdout = subprocess.PIPE, stderr = subprocess.PIPE,
        text = True, env = env,
    )
    lines = []
    try:
        deadline = time.monotonic() + 30
        proc.stdin.write( json.dumps( _REQUESTS[ 0 ] ) + "\n" ); proc.stdin.flush()
        first = _read_line( proc, deadline )
        assert first is not None, "the server never answered the handshake"
        lines.append( first )
        for request in _REQUESTS[ 1: ]:
            proc.stdin.write( json.dumps( request ) + "\n" )
        proc.stdin.flush()
        # The tool result, or the junk that swallowed it; then stop waiting.
        while ( line := _read_line( proc, time.monotonic() + 5 ) ):
            lines.append( line )
            if '"id":2' in line.replace( " ", "" ): break
    finally:
        proc.kill()
        stderr = proc.communicate( timeout = 10 )[ 1 ]

    frames, junk = [], []
    for line in ( l.rstrip( "\n" ) for l in lines ):
        try:
            frames.append( json.loads( line ) )
        except json.JSONDecodeError:
            junk.append( line )
    return frames, junk, stderr


def _tool_result( frames ):
    return next( ( f for f in frames if f.get( "id" ) == 2 ), None )


def test_CONTROL_without_the_guard_a_stray_print_destroys_the_tool_result( tmp_path ):
    frames, junk, _ = _drive( tmp_path, "bare" )
    assert _tool_result( frames ) is None, "the control must reproduce the loss, or the fixed arm proves nothing"
    assert any( "the answer" in line and line.startswith( "-12-34" ) for line in junk ), junk


def test_with_the_guard_the_tool_result_survives_and_stdout_is_pure_jsonrpc( tmp_path ):
    frames, junk, stderr = _drive( tmp_path, "guard" )
    assert junk == [], f"non-JSON on the JSON-RPC channel: {junk}"
    result = _tool_result( frames )
    assert result is not None, frames
    assert "the answer" in json.dumps( result[ "result" ] )
    assert "-12" in stderr and "-34" in stderr, "the stray writes must land on stderr, not vanish"


# ── in-process, on pipes standing in for fds 1 and 2 ─────────────────────────
def _pipes():
    out_r, out_w = os.pipe()
    err_r, err_w = os.pipe()
    return out_r, out_w, err_r, err_w


def _drain( fd ):
    os.set_blocking( fd, False )
    try:
        return os.read( fd, 65536 )
    except BlockingIOError:
        return b""


def test_the_reserved_channel_writes_to_the_old_stdout_and_the_fd_now_reaches_stderr():
    out_r, out_w, err_r, err_w = _pipes()
    transport = types.SimpleNamespace( stdio_server=lambda stdin=None, stdout=None: None )

    channel = reserve_stdout_for_jsonrpc( stdout_fd=out_w, stderr_fd=err_w, transport_module=transport )
    channel.write( b"{}\n" ); channel.flush()
    os.write( out_w, b"stray" )

    assert _drain( out_r ) == b"{}\n", "the channel must reach what stdout USED to be"
    assert _drain( err_r ) == b"stray", "the old stdout fd must now reach stderr"
    channel.close()
    for fd in ( out_r, out_w, err_r, err_w ): os.close( fd )


def test_the_transport_is_handed_the_channel_when_it_names_no_stdout():
    out_r, out_w, err_r, err_w = _pipes()
    seen = []
    transport = types.SimpleNamespace(
        stdio_server=lambda stdin=None, stdout=None: seen.append( ( stdin, stdout ) ) or "ctx" )

    channel = reserve_stdout_for_jsonrpc( stdout_fd=out_w, stderr_fd=err_w, transport_module=transport )
    assert transport.stdio_server() == "ctx"
    stdin, stdout = seen[ 0 ]
    assert stdin is None and stdout is not None
    assert isinstance( stdout.wrapped, io.TextIOWrapper ) and stdout.wrapped.buffer is channel

    # A caller that names its own stdout keeps it — the wrapper only fills the gap.
    mine = object()
    transport.stdio_server( stdout=mine )
    assert seen[ 1 ] == ( None, mine )
    channel.close()
    for fd in ( out_r, out_w, err_r, err_w ): os.close( fd )


def test_the_default_transport_is_fastmcps_own_stdio_server_name( monkeypatch ):
    """The patch must land on the name FastMCP's run_stdio_async looks up at call time."""
    import fastmcp.server.server as fastmcp_server
    original = fastmcp_server.stdio_server
    monkeypatch.setattr( fastmcp_server, "stdio_server", original )   # restored after the test
    out_r, out_w, err_r, err_w = _pipes()

    channel = reserve_stdout_for_jsonrpc( stdout_fd=out_w, stderr_fd=err_w )
    assert fastmcp_server.stdio_server is not original
    channel.close()
    for fd in ( out_r, out_w, err_r, err_w ): os.close( fd )


def test_the_mcp_server_reserves_stdout_before_it_imports_anything_that_prints():
    """Static, because running the real server needs :7999. The guard must run first."""
    text  = ( SRC / "lupin_mcp" / "cosa_voice_mcp.py" ).read_text( encoding="utf-8" )
    guard = text.index( "reserve_stdout_for_jsonrpc()" )
    for later in ( "\nimport anyio", "\nfrom fastmcp import FastMCP", "\nimport cosa.utils.util" ):
        assert guard < text.index( later ), f"stdout is reserved only after {later.strip()!r}"
    block = text.rindex( 'if __name__ == "__main__":', 0, guard )
    assert text[ block:guard ].count( "\n" ) <= 12, "the reservation must sit inside a __main__ guard, never run on import"
