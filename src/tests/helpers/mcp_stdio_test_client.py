"""
MCP stdio test client — spawn `python -m lupin_mcp.cosa_voice_mcp` as a child
process and drive it via the MCP JSON-RPC stdio protocol.

Used by AC14 (tool-registration verification) and AC12 (config-toggle verification)
in the commons MVP. Reusable by future MCP-tool tests.

Protocol summary:
- Send `initialize` request, wait for response
- Send `notifications/initialized` notification (no response)
- Send `tools/list` request, wait for response
- Server logs go to stderr; MCP traffic on stdin/stdout (newline-delimited JSON)
"""

import json
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional


class MCPStdioClient:
    """
    Drive a fastmcp stdio server subprocess via JSON-RPC.

    Requires:
        - the lupin_mcp.cosa_voice_mcp entry point is importable in the spawning env

    Ensures:
        - `__init__` spawns the subprocess and prepares pipes
        - `initialize()` completes the MCP handshake
        - `list_tools()` returns the tool catalog
        - `close()` terminates the subprocess (SIGTERM, then SIGKILL on timeout)
    """

    def __init__(
        self,
        env             : Optional[ Dict[ str, str ] ] = None,
        cwd             : Optional[ str ]              = None,
        timeout_seconds : float = 15.0,
        module          : str   = "lupin_mcp.cosa_voice_mcp",
    ):
        self.timeout_seconds = timeout_seconds
        self._next_request_id = 0
        self.stderr_text = ""   # populated by close() after the subprocess exits
        self.proc = subprocess.Popen(
            [ sys.executable, "-m", module ],
            stdin   = subprocess.PIPE,
            stdout  = subprocess.PIPE,
            stderr  = subprocess.PIPE,
            env     = env,
            cwd     = cwd,
            bufsize = 0,
        )

    def _allocate_id( self ) -> int:
        self._next_request_id += 1
        return self._next_request_id

    def _send( self, payload: Dict[ str, Any ] ) -> None:
        line = ( json.dumps( payload ) + "\n" ).encode( "utf-8" )
        self.proc.stdin.write( line )
        self.proc.stdin.flush()

    def _read_response( self, expected_id: int ) -> Dict[ str, Any ]:
        deadline = time.monotonic() + self.timeout_seconds
        while time.monotonic() < deadline:
            line = self.proc.stdout.readline()
            if not line:
                if self.proc.poll() is not None:
                    stderr = self.proc.stderr.read().decode( "utf-8", errors="replace" )
                    raise RuntimeError( f"MCP subprocess exited prematurely. stderr:\n{stderr}" )
                continue
            try:
                msg = json.loads( line.decode( "utf-8" ) )
            except json.JSONDecodeError:
                continue
            if msg.get( "id" ) == expected_id:
                return msg
        raise TimeoutError( f"No MCP response for id={expected_id} within {self.timeout_seconds}s" )

    def initialize( self ) -> Dict[ str, Any ]:
        """Run the MCP handshake. Returns the initialize-response dict."""
        req_id = self._allocate_id()
        self._send( {
            "jsonrpc" : "2.0",
            "id"      : req_id,
            "method"  : "initialize",
            "params"  : {
                "protocolVersion" : "2024-11-05",
                "capabilities"    : { },
                "clientInfo"      : { "name": "lupin-test-client", "version": "1.0" },
            },
        } )
        resp = self._read_response( req_id )
        # Notify server initialization is complete (no response expected).
        self._send( { "jsonrpc": "2.0", "method": "notifications/initialized" } )
        return resp

    def list_tools( self ) -> List[ Dict[ str, Any ] ]:
        """Send `tools/list`. Returns the tools array from the response."""
        req_id = self._allocate_id()
        self._send( { "jsonrpc": "2.0", "id": req_id, "method": "tools/list" } )
        resp = self._read_response( req_id )
        return resp.get( "result", { } ).get( "tools", [ ] )

    def close( self ) -> None:
        """
        Terminate the subprocess (SIGTERM first; SIGKILL after 2s timeout) and
        drain stderr into `self.stderr_text` before closing pipes. Tests can
        assert on `client.stderr_text` for log-line presence/absence.
        """
        if self.proc.poll() is None:
            try:
                self.proc.terminate()
                self.proc.wait( timeout=2.0 )
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        try:
            self.stderr_text = self.proc.stderr.read().decode( "utf-8", errors="replace" )
        except Exception:
            pass
        for stream in ( self.proc.stdin, self.proc.stdout, self.proc.stderr ):
            try:
                stream.close()
            except Exception:
                pass

    def __enter__( self ):
        return self

    def __exit__( self, exc_type, exc_val, exc_tb ):
        self.close()
        return False
