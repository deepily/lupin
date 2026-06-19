#!/usr/bin/env python3
"""
Bridge-liveness middleware for the cosa-voice MCP server.

The v2.1 direct-state-visibility **SERVER per-MCP-call stamp** lane
(arbiter design `03` §10.1 / §10.7). On every inbound MCP tool call, the
server bumps THIS session's bridge-file mtime — making the bridge file a live
liveness signal even while the session is heads-down working and never hits a
`Stop` (the Stop hook is edge-triggered, so it cannot report a busy session;
the server stamp does).

**Convergence (redline C4):** the stamp reuses the ONE host-side clock —
`touch_bridge_mtime()` (`os.utime` on `~/.claude/sessions/cc-*.json`), the same
file the idle-waiter re-arm, the Stop hook, and the tool-use hook bump. One
signal, many writers — NO parallel last-seen store. Because the bridge file is
written host-side (never through `:7999`), the clock survives a server wedge.

**Cost:** negligible — MCP tool calls are roughly per-turn (far below the
per-tool-call frequency the hook-lane C1 redline guards), and the stamp is a
bare metadata-only `os.utime` that never raises.

Kept in its own module so the stamp behavior is unit-testable in isolation
(no live MCP server needed); `cosa_voice_mcp.py` only registers it via
`mcp.add_middleware( BridgeLivenessMiddleware() )`.
"""
from fastmcp.server.middleware import Middleware

from lupin_cli.claude_code.hooks.lib.session_bridge import touch_bridge_mtime


class BridgeLivenessMiddleware( Middleware ):
    """
    FastMCP middleware that stamps the session bridge mtime per tool call.

    Requires:
        - mounted on the cosa-voice FastMCP server via add_middleware
        - touch_bridge_mtime() resolves this server process's own bridge file
          (PPID/grandparent walk — the MCP server is a child of the CC process)

    Ensures:
        - bumps the bridge mtime (host-side liveness clock, C4) BEFORE the tool
          runs, so liveness is refreshed on every inbound MCP call
        - the tool call always proceeds (the stamp never raises — it is the
          never-raising touch_bridge_mtime primitive) and its result is
          returned unchanged
    """

    async def on_call_tool( self, context, call_next ):
        """
        Stamp the bridge mtime, then delegate to the next handler.

        Ensures:
            - calls touch_bridge_mtime() (bare os.utime; swallows its own errors)
            - returns await call_next( context ) unchanged — the stamp is purely
              a side effect and never alters the tool result or short-circuits
        """
        # COUPLING CONTRACT (Krishna review N2): this site is intentionally
        # guard-free because touch_bridge_mtime() is TOTAL-no-throw (catches
        # Exception, not just OSError — proven by fault injection in
        # test_session_bridge_mtime.py). The stamp runs BEFORE call_next, so any
        # exception escaping it would be tool-fatal for EVERY MCP call fleet-wide.
        # If that primitive's catch is ever narrowed, THIS line MUST gain its own
        # try/except or it becomes a fleet-wide outage vector.
        touch_bridge_mtime()
        return await call_next( context )


def quick_smoke_test():
    """
    Self-contained smoke test (async, no live server).

    Ensures:
        - Returns True if on_call_tool stamps + delegates + passes the result
          through; raises AssertionError otherwise.
    """
    import asyncio
    import sys
    from unittest.mock import patch

    calls = { "stamped": 0, "next": 0 }

    async def _fake_next( ctx ):
        calls[ "next" ] += 1
        return "tool-result"

    def _fake_touch():
        calls[ "stamped" ] += 1
        return True

    mw = BridgeLivenessMiddleware()
    # Patch on the running module object so this works whether the module is
    # imported by package path or executed directly as __main__.
    this_module = sys.modules[ BridgeLivenessMiddleware.__module__ ]
    with patch.object( this_module, "touch_bridge_mtime", _fake_touch ):
        result = asyncio.run( mw.on_call_tool( object(), _fake_next ) )

    assert result == "tool-result", result
    assert calls[ "stamped" ] == 1, calls
    assert calls[ "next" ] == 1, calls
    return True


if __name__ == "__main__":   # pragma: no cover - manual smoke entrypoint
    ok = quick_smoke_test()
    print( f"bridge_liveness_middleware smoke: {'PASS' if ok else 'FAIL'}" )
