"""
STDIO integration for the four reuse tools (plan 2, phase W-C): start cosa-voice as a real
subprocess, call each reuse tool beside an existing voice tool, and prove the exit-gate facts at
the surface a seat actually uses.

What this adds to the in-process unit tests:
    - the tools are registered and answer over the MCP wire, in the same process as the voice tools
    - a receipt written by one server process is byte-equal after the process restarts
    - a corrupted or missing receipt answers with a named error over the wire, never a verdict
    - when `lupin_mcp.reuse_tools` raises at import, the server still starts and a voice tool answers
    - when the call-log middleware raises at import, the server still starts and says so on stderr

No live Jev is called: the transport is not built yet (plan phase W-A), so a call with no injected
transport reports KEY_UNREADABLE when the key file is absent and CALL_FAILED when it is present.
Both are asserted against the key file the server itself will look at.

Tests write only under temporary directories injected through LUPIN_REUSE_DATA_DIR and
LUPIN_REUSE_OUT_DIR, so they leave no persistent state.
"""
import json
import os
import pathlib
import re
import shutil
import sys
import textwrap
import time

import pytest

from tests.helpers.mcp_stdio_test_client import MCPStdioClient

REPO       = pathlib.Path( __file__ ).resolve().parents[ 4 ]
REUSE      = { "check_exists", "fetch_similar", "read_capability", "replay" }
ENTRY      = "cosa.rest.task_store_owed.park_reason_is_stale"
KEY_FILE   = REPO / "src" / "conf" / "keys" / "typesafe-api-key"
RECEIPT_ID = re.compile( r"[0-9a-f]{16}" )


class WireClient( MCPStdioClient ):
    """MCPStdioClient plus tools/call, which the shared helper does not have."""

    def call_tool( self, name, arguments ):
        """Ensures: returns the structured tool result (a dict), raising AssertionError on an MCP-level error."""
        req_id = self._allocate_id()
        self._send( { "jsonrpc": "2.0", "id": req_id, "method": "tools/call", "params": { "name": name, "arguments": arguments } } )
        resp = self._read_response( req_id )
        assert "error" not in resp, f"{name} answered an MCP error: {resp[ 'error' ]}"
        result = resp[ "result" ]
        assert result.get( "isError" ) is False, f"{name} answered isError: {result}"
        return result.get( "structuredContent" ) or json.loads( result[ "content" ][ 0 ][ "text" ] )


def server_env( data, out, extra_pythonpath=None ):
    """Ensures: returns the environment of a spawned cosa-voice with the reuse data and index relocated."""
    env = dict( os.environ )
    node_bins = sorted( pathlib.Path.home().glob( ".nvm/versions/node/*/bin" ) )
    path = os.pathsep.join( [ str( b ) for b in node_bins ] + [ env.get( "PATH", "" ) ] )
    pp   = os.pathsep.join( [ p for p in ( extra_pythonpath, str( REPO / "src" ) ) if p ] )
    env.update( { "LUPIN_ROOT": str( REPO ), "PYTHONPATH": pp, "PATH": path,
                  "LUPIN_REUSE_DATA_DIR": str( data ), "LUPIN_REUSE_OUT_DIR": str( out ),
                  "CLAUDE_SESSION_ID": "wcstdio-0000-0000-0000-000000000000" } )
    return env


def started( env, timeout=180.0 ):
    """Ensures: returns an initialized WireClient on a freshly spawned server, cwd at the repo root."""
    client = WireClient( env=env, cwd=str( REPO ), timeout_seconds=timeout )
    client.initialize()
    return client


@pytest.fixture( scope="module" )
def dirs( tmp_path_factory ):
    """One data directory and one generated-index directory shared by the module's servers."""
    return tmp_path_factory.mktemp( "reuse-data" ), tmp_path_factory.mktemp( "reuse-out" )


def expected_cause():
    """
    Ensures: returns ( cause, other ), the cause a call with no injected Jev transport must carry and the one it must also list.

    A tree with no `node_modules/typescript` answers DEPENDENCY_MISSING first (the decision table's
    precedence), with the key cause still listed; a tier-capable tree answers the key cause itself.
    """
    key = "CALL_FAILED" if KEY_FILE.exists() else "KEY_UNREADABLE"
    if not ( REPO / "node_modules" / "typescript" ).exists(): return "DEPENDENCY_MISSING", key
    return key, key


def test_all_four_reuse_tools_are_registered_beside_the_voice_tools( dirs ):
    with started( server_env( *dirs ) ) as client:
        names = { t[ "name" ] for t in client.list_tools() }
    assert REUSE <= names, f"missing reuse tools: {REUSE - names}"
    assert { "notify", "get_session_info", "task_query" } <= names, "voice and task tools must still be registered"


def test_each_reuse_tool_answers_over_stdio_beside_a_voice_tool( dirs ):
    data, _ = dirs
    with started( server_env( *dirs ) ) as client:
        before = client.call_tool( "get_session_info", {} )
        check  = client.call_tool( "check_exists", { "need": "mark a task row stale when its park reason is old" } )
        similar = client.call_tool( "fetch_similar", { "entry": ENTRY } )
        read   = client.call_tool( "read_capability", { "names": [ "no-such-capability" ] } )
        replay = client.call_tool( "replay", { "receipt_id": check[ "receipt_id" ] } )
        after  = client.call_tool( "get_session_info", {} )
    assert before[ "project" ] == "lupin" and after[ "project" ] == "lupin", "the voice tool answered before and after the reuse calls"
    assert check[ "tool" ] == "check_exists" and RECEIPT_ID.fullmatch( check[ "receipt_id" ] )
    cause, listed = expected_cause()
    assert check[ "verdict" ] == "UNCERTAIN_READ_SOURCE" and check[ "cause" ] == cause and listed in check[ "causes" ], \
        f"with no Jev transport the verdict is UNCERTAIN_READ_SOURCE with cause {cause} and {listed} listed, never NEW: {check}"
    assert similar[ "tool" ] == "fetch_similar" and RECEIPT_ID.fullmatch( similar[ "receipt_id" ] )
    assert ENTRY not in [ r[ "id" ] for r in similar[ "shortlist" ] + similar[ "nearest" ] ], "the symbol itself is excluded by id"
    assert read[ "pages" ] == { "no-such-capability": { "error": "NOT_FOUND" } }, "an unknown slug is a named error, not an empty page"
    assert replay[ "status" ] == "ok" and replay[ "receipt_id" ] == check[ "receipt_id" ], replay
    assert replay[ "stored" ][ "verdict" ] == check[ "verdict" ] and replay[ "stored" ][ "cause" ] == check[ "cause" ], "replay returns the stored result"
    assert replay[ "differences" ][ "frozen" ] == [], "a re-run against the frozen inputs reproduces the stored result"
    lines = [ json.loads( l ) for f in ( data / "call-log" ).glob( "*.jsonl" ) for l in f.read_text( encoding="utf-8" ).splitlines() ]
    logged = { r.get( "tool" ) for r in lines }
    assert REUSE <= logged, f"the server-side call log must carry every reuse tool, found {logged}"
    assert all( r.get( "tool" ) in REUSE for r in lines ), "the log carries reuse calls only, not the voice tool calls"


def test_a_receipt_is_byte_equal_after_the_server_restarts( dirs ):
    data, _ = dirs
    need = { "need": "wrap a dictionary so a missing key raises a named error" }
    with started( server_env( *dirs ) ) as first:
        one = first.call_tool( "check_exists", need )
    files = sorted( p for p in data.rglob( f"{one[ 'receipt_id' ]}*" ) if p.is_file() )
    assert files, f"no stored receipt for {one[ 'receipt_id' ]} under {data}"
    snapshot = { p: p.read_bytes() for p in files }
    with started( server_env( *dirs ) ) as second:
        two = second.call_tool( "check_exists", need )
    assert two[ "receipt_id" ] == one[ "receipt_id" ], "the same question against the same inputs shares one receipt across processes"
    assert { p: p.read_bytes() for p in files } == snapshot, "the receipt file changed after a restart: receipts must be immutable"


@pytest.mark.parametrize( "damage, named", [ ( "corrupt", "RECEIPT_CORRUPT" ), ( "delete", "RECEIPT_MISSING" ) ] )
def test_a_damaged_or_missing_receipt_answers_a_named_error_over_the_wire( dirs, damage, named ):
    data, _ = dirs
    with started( server_env( *dirs ) ) as client:
        made = client.call_tool( "read_capability", { "names": [ f"slug-{damage}" ] } )
        files = [ p for p in data.rglob( f"{made[ 'receipt_id' ]}*" ) if p.is_file() ]
        assert files, "positive control: the receipt exists before it is damaged"
        for p in files:
            if damage == "corrupt": p.write_bytes( b"\x00not a receipt" )
            else: p.unlink()
        replayed = client.call_tool( "replay", { "receipt_id": made[ "receipt_id" ] } )
    assert named in json.dumps( replayed ), f"{damage} must answer {named}, got {replayed}"
    assert "verdict" not in replayed, "a damaged receipt never yields a verdict"


SHIM = """
import importlib.abc, sys

class _Refuse( importlib.abc.MetaPathFinder ):
    def find_spec( self, name, path, target=None ):
        if name in BLOCKED:
            raise ImportError( "injected: " + name + " cannot be imported" )
        return None

BLOCKED = %r
sys.meta_path.insert( 0, _Refuse() )
"""


def shim_dir( tmp_path, blocked ):
    """Ensures: returns a directory whose sitecustomize makes importing any module in `blocked` raise ImportError."""
    ( tmp_path / "sitecustomize.py" ).write_text( textwrap.dedent( SHIM ) % ( set( blocked ), ), encoding="utf-8" )
    return str( tmp_path )


def test_when_the_reuse_import_raises_the_server_starts_and_a_voice_tool_answers( dirs, tmp_path ):
    env = server_env( *dirs, extra_pythonpath=shim_dir( tmp_path, { "lupin_mcp.reuse_tools" } ) )
    with started( env ) as client:
        names   = { t[ "name" ] for t in client.list_tools() }
        voice   = client.call_tool( "get_session_info", {} )
        answers = { t: client.call_tool( t, args ) for t, args in
                    { "check_exists": { "need": "anything" }, "fetch_similar": { "entry": ENTRY },
                      "read_capability": { "names": [ "x" ] }, "replay": { "receipt_id": "0123456789abcdef" } }.items() }
    assert REUSE <= names, "the wrappers still load, so the tools stay listed"
    assert voice[ "project" ] == "lupin", "a voice tool answers while reuse_tools cannot be imported"
    for tool, answer in answers.items():
        assert answer[ "error" ] == "REUSE_TOOLS_UNAVAILABLE" and "injected" in answer[ "detail" ], \
            f"{tool} must report the import failure by name: {answer}"
    assert not any( "verdict" in a for a in answers.values() ), "an import failure is never a verdict"


def test_when_the_call_log_middleware_import_raises_the_server_says_so_and_still_serves( dirs, tmp_path ):
    env = server_env( *dirs, extra_pythonpath=shim_dir( tmp_path, { "lupin_mcp.reuse_call_log_middleware" } ) )
    with started( env ) as client:
        voice = client.call_tool( "get_session_info", {} )
        check = client.call_tool( "check_exists", { "need": "something to look up" } )
    assert voice[ "project" ] == "lupin" and check[ "tool" ] == "check_exists", "both families still answer without the middleware"
    assert "reuse call-log middleware not mounted" in client.stderr_text, "the failure is reported on stderr, not silent"


class OverlappingClient( WireClient ):
    """A client that can have two calls in flight and keeps every response it reads, whichever call it answers."""

    def __init__( self, *a, **k ):
        super().__init__( *a, **k )
        self.seen = {}

    def send_call( self, name, arguments ):
        """Ensures: sends tools/call without waiting; returns the request id."""
        req_id = self._allocate_id()
        self._send( { "jsonrpc": "2.0", "id": req_id, "method": "tools/call", "params": { "name": name, "arguments": arguments } } )
        return req_id

    def wait_for( self, req_id ):
        """Ensures: returns ( response, seconds waited ), keeping other responses that arrive first in self.seen."""
        t0 = time.monotonic()
        while req_id not in self.seen:
            line = self.proc.stdout.readline()
            if not line: raise RuntimeError( "server closed stdout while a call was pending" )
            try: msg = json.loads( line.decode( "utf-8" ) )
            except json.JSONDecodeError: continue
            if "id" in msg: self.seen[ msg[ "id" ] ] = msg
        return self.seen[ req_id ], time.monotonic() - t0


def test_a_slow_reuse_call_does_not_starve_a_voice_tool( tmp_path ):
    """
    The heartbeat-shaped test for the reuse tools (plan 2 section 5): a seat has ONE STDIO process, so
    a reuse call that blocks the event loop silences every other verb. A fresh index directory forces
    check_exists into a real index build (seconds), and a voice tool called while it runs must answer
    before it finishes, not after.
    """
    env = server_env( tmp_path / "data", tmp_path / "out" )
    with OverlappingClient( env=env, cwd=str( REPO ), timeout_seconds=180.0 ) as client:
        client.initialize()
        slow = client.send_call( "check_exists", { "need": "a need that makes the server build its index first" } )
        time.sleep( 1.0 )                                                     # let the server start the build
        fast = client.send_call( "get_session_info", {} )
        fast_resp, fast_wait = client.wait_for( fast )
        slow_done_when_fast_answered = slow in client.seen
        slow_resp, slow_wait = client.wait_for( slow )
    assert fast_resp[ "result" ][ "isError" ] is False, "the voice tool answered normally"
    assert not slow_done_when_fast_answered, "positive control: the reuse call was still in flight when the voice tool answered"
    assert fast_wait < 5.0, f"the voice tool waited {fast_wait:.1f}s behind a running reuse call: the event loop was blocked"
    assert slow_wait + fast_wait > 3.0, "the reuse call must have been slow enough to prove anything"
    assert slow_resp[ "result" ][ "isError" ] is False
