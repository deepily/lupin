#!/usr/bin/env python3
"""
Unit tests for the cosa-voice SERVER per-MCP-call bridge-mtime stamp middleware
(arbiter design `03` §10.1 / §10.7 — v2.1 direct-state visibility, redline C4).

100% line + branch + function coverage of bridge_liveness_middleware (SWE-team
hard gate).
"""
import os
import sys

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

import lupin_mcp.bridge_liveness_middleware as mod
from lupin_mcp.bridge_liveness_middleware import BridgeLivenessMiddleware


class TestOnCallTool:

    @pytest.mark.asyncio
    async def test_stamps_then_delegates_and_passes_result_through( self, monkeypatch ):
        """on_call_tool stamps the bridge mtime, calls call_next, returns its result."""
        order   = [ ]
        ctx     = object()

        def _fake_touch():
            order.append( "stamp" )
            return True

        async def _call_next( received_ctx ):
            order.append( "next" )
            assert received_ctx is ctx          # context passed through unchanged
            return "the-tool-result"

        monkeypatch.setattr( mod, "touch_bridge_mtime", _fake_touch )

        result = await BridgeLivenessMiddleware().on_call_tool( ctx, _call_next )

        assert result == "the-tool-result"      # result returned unchanged
        assert order == [ "stamp", "next" ]      # stamp fires BEFORE the tool runs

    @pytest.mark.asyncio
    async def test_tool_proceeds_even_if_stamp_reports_false( self, monkeypatch ):
        """A failed stamp (touch returns False) never blocks the tool call."""
        async def _call_next( ctx ):
            return "ok"

        monkeypatch.setattr( mod, "touch_bridge_mtime", lambda: False )

        assert await BridgeLivenessMiddleware().on_call_tool( object(), _call_next ) == "ok"


def test_quick_smoke_test_passes():
    """The module's self-contained smoke test returns True (function coverage)."""
    assert mod.quick_smoke_test() is True


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
