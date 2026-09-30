"""
The reuse tools as mounted on the cosa-voice MCP server: the call-log middleware, the four
wrappers, the lazy-import guarantee and a real STDIO session.
"""
import asyncio
import json
import os
import pathlib
import select
import subprocess
import sys
import time

import pytest
from fastmcp import Client, FastMCP
from fastmcp.tools.tool import ToolResult

import lupin_mcp.cosa_voice_mcp as cvm
from cosa.repo.symindex.spec import git_toplevel
from lupin_mcp import reuse_call_log_middleware as mw
from lupin_mcp import reuse_tools as rt
from tests.unit.symindex_helpers import make_lupin_repo
from tests.unit.test_reuse_tools import ALL_TEXTS, FEEDS_TEXT, MATHX_TEXT, NEED, FakeJev, resp

REPO_ROOT = git_toplevel( pathlib.Path( __file__ ).resolve().parent )
REUSE     = ( "check_exists", "fetch_similar", "read_capability", "replay" )


def _ctx( tmp_path ):
    return rt.ReuseContext( tmp_path / "unused-root", tmp_path / "data" )


def _log( tmp_path, session="s1" ):
    p = tmp_path / "data" / "call-log" / f"{session}.jsonl"
    return [ json.loads( l ) for l in p.read_text( encoding="utf-8" ).splitlines() ] if p.exists() else []


def _server( tmp_path, factory=None ):
    m = FastMCP( "t" )

    @m.tool
    def check_exists( need: str ) -> dict: return { "status": "ok", "receipt_id": "abc123" }

    @m.tool
    def fetch_similar( entry: str ) -> dict: return { "status": "error", "error": "UNKNOWN_ENTRY" }

    @m.tool
    def read_capability( names: list ) -> ToolResult: return ToolResult( content="plain text, no structure" )

    @m.tool
    def replay( receipt_id: str ) -> dict: raise ValueError( "boom" )

    @m.tool
    def get_session_info() -> dict: return { "receipt_id": "not-a-reuse-call" }

    m.add_middleware( mw.ReuseCallLogMiddleware( identity=lambda: "rachel 36d80c49", session_id="s1", context_factory=factory or ( lambda: _ctx( tmp_path ) ) ) )
    return m


def test_the_middleware_logs_reuse_calls_with_receipt_error_and_caller_and_ignores_other_tools( tmp_path ):
    async def go():
        async with Client( _server( tmp_path ) ) as c:
            await c.call_tool( "check_exists", { "need": "x" } )
            await c.call_tool( "fetch_similar", { "entry": "a.b" } )
            await c.call_tool( "read_capability", { "names": [ "x" ] } )
            with pytest.raises( Exception ): await c.call_tool( "replay", { "receipt_id": "r" } )
            await c.call_tool( "get_session_info", {} )
    asyncio.run( go() )
    lines = _log( tmp_path )
    assert [ l[ "tool" ] for l in lines ] == [ "check_exists", "fetch_similar", "read_capability", "replay" ]      # get_session_info is not logged
    assert lines[ 0 ][ "receipt_id" ] == "abc123" and lines[ 0 ][ "error" ] is None and lines[ 0 ][ "caller" ] == "rachel 36d80c49"
    assert lines[ 1 ][ "receipt_id" ] is None and lines[ 1 ][ "error" ] == "UNKNOWN_ENTRY"
    assert lines[ 2 ][ "receipt_id" ] is None and lines[ 2 ][ "error" ] is None                                # a result with no structured content
    assert lines[ 3 ][ "error" ].startswith( "ToolError" ) or "boom" in lines[ 3 ][ "error" ]
    assert all( l[ "session" ] == "s1" and l[ "ts" ] and l[ "args" ] for l in lines )


def test_a_failing_log_write_never_changes_or_fails_the_tool_call( tmp_path ):
    def broken(): raise OSError( "disk full" )
    async def go():
        async with Client( _server( tmp_path, broken ) ) as c:
            r = await c.call_tool( "check_exists", { "need": "x" } )
            return r.structured_content
    assert asyncio.run( go() ) == { "status": "ok", "receipt_id": "abc123" }
    assert _log( tmp_path ) == []


def test_the_default_context_factory_is_the_environment_one( tmp_path, monkeypatch ):
    monkeypatch.setattr( rt, "context_from_environment", lambda root=None: _ctx( tmp_path ) )
    m = mw.ReuseCallLogMiddleware( identity=lambda: "x 1", session_id="s1" )
    m._log( "check_exists", {}, "r1", None )
    assert _log( tmp_path )[ 0 ][ "receipt_id" ] == "r1"


# --- mounted on the real server --------------------------------------------------------------------------------------------------

def test_the_four_tools_and_both_middlewares_are_mounted_in_order():
    tools = asyncio.run( cvm.mcp.get_tools() )
    assert all( n in tools for n in REUSE ) and "get_session_info" in tools
    names = [ type( m ).__name__ for m in cvm.mcp.middleware ]
    assert names.index( "BridgeLivenessMiddleware" ) < names.index( "ReuseCallLogMiddleware" )


async def _run( name, args ):
    tool = await cvm.mcp.get_tool( name )
    return ( await tool.run( args ) ).structured_content


def test_each_wrapper_delegates_to_the_impl_and_answers_with_an_error_dict_when_the_import_fails( tmp_path, monkeypatch ):
    root = make_lupin_repo( tmp_path )
    fake = FakeJev( { FEEDS_TEXT: resp( 0.95, 0.03, 0.02 ) } )
    monkeypatch.setattr( rt, "context_from_environment", lambda r=None: rt.ReuseContext( root, tmp_path / "data", out_dir=tmp_path / "out", transport=fake ) )
    got = asyncio.run( _run( "check_exists", { "need": NEED } ) )
    assert got[ "verdict" ] == "REUSE" and got[ "receipt_id" ]
    assert asyncio.run( _run( "fetch_similar", { "entry": "cosa.nope" } ) )[ "error" ] == "UNKNOWN_ENTRY"
    assert asyncio.run( _run( "read_capability", { "names": [ "x" ] } ) )[ "pages" ] == { "x": { "error": "NOT_FOUND" } }
    assert asyncio.run( _run( "replay", { "receipt_id": got[ "receipt_id" ] } ) )[ "status" ] == "ok"
    import lupin_mcp
    monkeypatch.delattr( lupin_mcp, "reuse_tools" )                                              # `from lupin_mcp import x` finds the attribute first
    monkeypatch.setitem( sys.modules, "lupin_mcp.reuse_tools", None )
    for name, args in ( ( "check_exists", { "need": "x" } ), ( "fetch_similar", { "entry": "a" } ), ( "read_capability", { "names": [] } ), ( "replay", { "receipt_id": "r" } ) ):
        out = asyncio.run( _run( name, args ) )
        assert out[ "error" ] == "REUSE_TOOLS_UNAVAILABLE" and "ModuleNotFoundError" in out[ "detail" ], name
    monkeypatch.undo()
    assert lupin_mcp.reuse_tools is rt
    monkeypatch.setattr( rt, "context_from_environment", lambda r=None: ( _ for _ in () ).throw( RuntimeError( "no ctx" ) ) )
    assert asyncio.run( _run( "check_exists", { "need": "x" } ) )[ "error" ] == "REUSE_TOOLS_UNAVAILABLE"


def test_a_slow_reuse_call_does_not_starve_the_event_loop( tmp_path, monkeypatch ):
    """The heartbeat shape of test_the_human_waiting_asks_do_not_starve_the_loop, for a blocking sweep."""
    root = make_lupin_repo( tmp_path )
    class Slow( FakeJev ):
        def post( self, body ):
            time.sleep( 0.3 )
            return super().post( body )
    monkeypatch.setattr( rt, "context_from_environment", lambda r=None: rt.ReuseContext( root, tmp_path / "data", out_dir=tmp_path / "out", transport=Slow() ) )
    async def go():
        beats, stop = { "n": 0 }, asyncio.Event()
        async def heart():
            while not stop.is_set():
                beats[ "n" ] += 1; await asyncio.sleep( 0.02 )
        h = asyncio.create_task( heart() ); await asyncio.sleep( 0 ); before = beats[ "n" ]
        try: await _run( "check_exists", { "need": NEED } )
        finally: stop.set(); await h
        return beats[ "n" ] - before
    assert asyncio.run( go() ) >= 8                                                              # a blocked loop would count 0


_PROBE = '''
import sys, asyncio
for name in sys.argv[ 1: ]: sys.modules[ name ] = None
import lupin_mcp.cosa_voice_mcp as cvm
async def go():
    tools = await cvm.mcp.get_tools()
    print( "TOOLS", sorted( n for n in ( "check_exists", "fetch_similar", "read_capability", "replay", "get_session_info" ) if n in tools ) )
    print( "MW", [ type( m ).__name__ for m in cvm.mcp.middleware ] )
    t = await cvm.mcp.get_tool( "check_exists" ); print( "REUSE", ( await t.run( { "need": "x" } ) ).structured_content[ "error" ] )
    g = await cvm.mcp.get_tool( "get_session_info" ); print( "VOICE", ( await g.run( {} ) ).structured_content[ "project" ] )
asyncio.run( go() )
'''


def test_if_the_reuse_imports_raise_cosa_voice_still_starts_and_a_voice_tool_answers( tmp_path ):
    script = tmp_path / "probe.py"; script.write_text( _PROBE, encoding="utf-8" )
    env = { **os.environ, "PYTHONPATH": str( REPO_ROOT / "src" ), "LUPIN_ROOT": str( REPO_ROOT ) }
    out = subprocess.run( [ sys.executable, str( script ), "lupin_mcp.reuse_tools", "lupin_mcp.reuse_call_log_middleware" ], capture_output=True, text=True, env=env, timeout=180 )
    assert out.returncode == 0, out.stderr[ -800: ]
    lines = { l.split( " ", 1 )[ 0 ]: l.split( " ", 1 )[ 1 ] for l in out.stdout.splitlines() if l.split( " ", 1 )[ 0 ] in ( "TOOLS", "MW", "REUSE", "VOICE" ) }
    assert "check_exists" in lines[ "TOOLS" ] and "get_session_info" in lines[ "TOOLS" ]
    assert "ReuseCallLogMiddleware" not in lines[ "MW" ] and "BridgeLivenessMiddleware" in lines[ "MW" ]
    assert lines[ "REUSE" ] == "REUSE_TOOLS_UNAVAILABLE" and lines[ "VOICE" ] == "lupin"
    assert "reuse call-log middleware not mounted" in out.stderr


# --- a real STDIO session ---------------------------------------------------------------------------------------------------------

def _rpc( proc, msg, want_id, timeout=90 ):
    proc.stdin.write( json.dumps( msg ) + "\n" ); proc.stdin.flush()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        ready, _, _ = select.select( [ proc.stdout ], [], [], 0.2 )
        if not ready: continue
        line = proc.stdout.readline()
        try: frame = json.loads( line )
        except ValueError: continue
        if frame.get( "id" ) == want_id: return frame
    raise AssertionError( f"no reply to {msg.get( 'method' )} within {timeout}s" )


@pytest.mark.skipif( ( REPO_ROOT / rt.KEY_FILE ).exists(), reason="a Jev key is present on this host, so the no-key path is not what runs" )
def test_stdio_session_calls_each_reuse_tool_alongside_a_voice_tool( tmp_path ):
    root = make_lupin_repo( tmp_path )
    env  = { **os.environ, "PYTHONPATH": str( REPO_ROOT / "src" ), "LUPIN_ROOT": str( REPO_ROOT ),
             "LUPIN_REUSE_DATA_DIR": str( tmp_path / "data" ), "LUPIN_REUSE_OUT_DIR": str( tmp_path / "out" ) }
    proc = subprocess.Popen( [ sys.executable, "-m", "lupin_mcp.cosa_voice_mcp" ], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env, cwd=str( REPO_ROOT ) )
    try:
        _rpc( proc, { "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": { "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": { "name": "t", "version": "0" } } }, 1 )
        proc.stdin.write( json.dumps( { "jsonrpc": "2.0", "method": "notifications/initialized" } ) + "\n" ); proc.stdin.flush()
        def call( i, name, args ):
            f = _rpc( proc, { "jsonrpc": "2.0", "id": i, "method": "tools/call", "params": { "name": name, "arguments": args } }, i )
            return f[ "result" ][ "structuredContent" ]
        listed = _rpc( proc, { "jsonrpc": "2.0", "id": 2, "method": "tools/list" }, 2 )[ "result" ][ "tools" ]
        assert set( REUSE ) <= { t[ "name" ] for t in listed } and "get_session_info" in { t[ "name" ] for t in listed }
        first = call( 3, "check_exists", { "need": NEED, "root": str( root ) } )
        assert ( first[ "verdict" ], first[ "cause" ] ) == ( "UNCERTAIN_READ_SOURCE", "KEY_UNREADABLE" ) and first[ "receipt_id" ]
        sim = call( 4, "fetch_similar", { "entry": "cosa.feeds.parse_feed", "root": str( root ) } )
        assert sim[ "uncertain" ] == "KEY_UNREADABLE" and sim[ "receipt_id" ] != first[ "receipt_id" ]
        cap = call( 5, "read_capability", { "names": [ "none" ], "root": str( root ) } )
        assert cap[ "pages" ] == { "none": { "error": "NOT_FOUND" } }
        rep = call( 6, "replay", { "receipt_id": first[ "receipt_id" ], "root": str( root ) } )
        assert rep[ "status" ] == "ok" and rep[ "stored" ][ "id" ] == first[ "receipt_id" ] and rep[ "differences" ][ "frozen" ] == []
        assert call( 7, "get_session_info", {} )[ "project" ] == "lupin"                          # the voice tool, same process
    finally:
        proc.kill(); proc.communicate( timeout=10 )
    logged = [ json.loads( l ) for f in ( tmp_path / "data" / "call-log" ).glob( "*.jsonl" ) for l in f.read_text( encoding="utf-8" ).splitlines() ]
    assert [ l[ "tool" ] for l in logged ] == [ "check_exists", "fetch_similar", "read_capability", "replay" ]
    assert logged[ 0 ][ "receipt_id" ] == first[ "receipt_id" ]
