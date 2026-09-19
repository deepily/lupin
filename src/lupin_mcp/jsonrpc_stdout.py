"""
jsonrpc_stdout.py — the MCP server's stdout carries JSON-RPC and nothing else (row e4dc53a9).

THE DEFECT THIS CLOSES. cosa-voice is a STDIO MCP server: its stdout IS the protocol
channel back to Claude Code. On 2026-09-18 one of Tiffany's sessions carried 141
non-JSON lines on it — ConfigurationManager's dump, printed from inside each ask. Claude
Code skips a whole junk line, so that looked harmless. But a print with no trailing
newline lands IN FRONT of the next frame, and that frame is then unparseable and
dropped: Rick answered a four-question card at 01:00:54.69Z, Claude Code logged
"Ignoring non-JSON line on stdout: JSON Parse error: Invalid number" seven milliseconds
later, and the call failed at its 660 s ceiling with the answer on the server.

⚠️ THE CURE IS THE CHANNEL, NOT THE PRINT (Mr. Radio's ruling). Silencing
configuration_manager.py's print closes this one and leaves the channel open to the
next. So the whole process loses the ability to write to the real stdout:

  1. the real stdout fd is duplicated to a PRIVATE fd — the JSON-RPC channel
  2. fd 1 is pointed at stderr, so `print()`, `sys.stdout.write`, a C extension and an
     inherited child all write to stderr, where Claude Code logs them and nothing parses
  3. FastMCP's transport is handed the private channel

⚠️ STEP 3 IS WHY THIS PATCHES A NAME IN FastMCP. `mcp.server.stdio.stdio_server`
wraps `sys.stdout.buffer` when it is entered, and FastMCP's `run_stdio_async` calls it
with no arguments — so after step 2 it would write the protocol to stderr. The wrapper
fills in `stdout` only when the caller named none. If FastMCP ever stops looking the name
up in its own module, the server writes JSON-RPC to stderr and fails on the first
handshake — loudly, which is the direction to fail in.
"""

import io
import os
import sys

import anyio


def reserve_stdout_for_jsonrpc( stdout_fd=1, stderr_fd=2, transport_module=None ):
    """
    Give JSON-RPC a private copy of stdout, and send every other write to stderr.

    Call once, as the FIRST thing a stdio MCP server does, before any import that might
    print. Never call it from an imported module: it rewires the process's fd 1.

    Requires:
        - stdout_fd / stderr_fd are open file descriptors (1 and 2 in production)
        - transport_module exposes `stdio_server( stdin=None, stdout=None )`;
          None means FastMCP's own server module

    Ensures:
        - returns an unbuffered binary writer on a private duplicate of what stdout_fd
          was — the JSON-RPC channel
        - stdout_fd now refers to what stderr_fd refers to
        - transport_module.stdio_server, called with no stdout, writes to the channel;
          a caller that names its own stdout keeps it
    """
    sys.stdout.flush()   # anything already buffered belongs to the old stdout, not stderr
    channel = os.fdopen( os.dup( stdout_fd ), "wb", buffering=0 )
    os.dup2( stderr_fd, stdout_fd )

    if transport_module is None:
        import fastmcp.server.server as transport_module

    original = transport_module.stdio_server

    def stdio_server( stdin=None, stdout=None ):
        if stdout is None:
            stdout = anyio.wrap_file( io.TextIOWrapper( channel, encoding="utf-8" ) )
        return original( stdin=stdin, stdout=stdout )

    transport_module.stdio_server = stdio_server
    return channel
