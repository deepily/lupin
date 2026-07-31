#!/usr/bin/env python3
"""
Unit tests for the DM Style Contract toggle inside cosa_voice_mcp.py
(Phase 1 of the DM Verbosity Reduction plan, Rick 2026-07-31 —
src/rnd/v0.1.9/2026.07.31-dm-verbosity-reduction/).

Both the toggle-read and the `instructions` payload / dm_send docstring
addendum are computed at MODULE IMPORT time (the MCP subprocess is spawned
fresh per Claude Code session, so this is the intended cost model — see the
plan's "flip between runs, not mid-session" note). To exercise both the
control (off) and treatment (on) arms in one test run, these tests patch
cu.get_dm_style_contract_enabled() BEFORE importing/reloading the module.

Risk under test: FastMCP's `mcp.tool()` could snapshot the tool description
at decoration/registration time, which would make a docstring mutation
applied AFTER decoration a no-op. cosa_voice_mcp.py guards against this by
defining `_dm_send_fn` first, mutating `.__doc__`, and decorating last
(`dm_send = mcp.tool(_dm_send_fn)`) — these tests assert on the REGISTERED
`FunctionTool.description`, not just the raw function's `.__doc__`, to prove
that ordering actually works end to end.
"""
import importlib
import os
import sys
from unittest.mock import patch

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )


def _reload_with_toggle( enabled ):
    """
    Reload lupin_mcp.cosa_voice_mcp with cu.get_dm_style_contract_enabled()
    patched to return `enabled`, so the module-load-time toggle read picks up
    the patched value.

    Ensures:
        - returns the freshly reloaded module object
    """
    import cosa.utils.util as cu
    with patch.object( cu, "get_dm_style_contract_enabled", return_value=enabled ):
        import lupin_mcp.cosa_voice_mcp as m
        importlib.reload( m )
        return m


class TestDmStyleContractToggleOff:
    """Control arm — default/off must reproduce today's shipped behavior exactly."""

    def test_instructions_section_is_empty( self ):
        m = _reload_with_toggle( False )
        assert m._DM_STYLE_CONTRACT_SECTION == ""

    def test_dm_send_fn_doc_has_no_style_marker( self ):
        m = _reload_with_toggle( False )
        assert "STYLE (governs" not in m._dm_send_fn.__doc__

    def test_registered_tool_description_has_no_style_marker( self ):
        """Proves the OFF path never mutates the registered tool at all."""
        m = _reload_with_toggle( False )
        assert "STYLE (governs" not in m.dm_send.description

    def test_instructions_payload_has_no_dm_style_contract_heading( self ):
        m = _reload_with_toggle( False )
        assert "## DM Style Contract" not in m.mcp.instructions


class TestDmStyleContractToggleOn:
    """Treatment arm — both send-side surfaces (instructions + docstring) carry the tag."""

    def test_instructions_section_carries_the_tag( self ):
        m = _reload_with_toggle( True )
        assert m.DM_STYLE_TAG in m._DM_STYLE_CONTRACT_SECTION

    def test_instructions_payload_has_dm_style_contract_heading( self ):
        m = _reload_with_toggle( True )
        assert "## DM Style Contract" in m.mcp.instructions

    def test_dm_send_fn_doc_carries_style_marker( self ):
        m = _reload_with_toggle( True )
        assert "STYLE (governs" in m._dm_send_fn.__doc__
        assert m.DM_STYLE_TAG in m._dm_send_fn.__doc__

    def test_registered_tool_description_carries_style_marker( self ):
        """
        THE load-bearing assertion: proves the doc mutation happened BEFORE
        mcp.tool() registration, not just on the plain Python function.
        """
        m = _reload_with_toggle( True )
        assert "STYLE (governs" in m.dm_send.description

    def test_registered_description_matches_mutated_fn_doc( self ):
        m = _reload_with_toggle( True )
        assert m.dm_send.description.strip() == m._dm_send_fn.__doc__.strip()

    def test_mechanics_only_docstring_is_preserved_verbatim( self ):
        """The addendum is APPENDED — the original mechanics-only doc survives untouched."""
        m = _reload_with_toggle( True )
        assert "PREFERRED" in m._dm_send_fn.__doc__
        assert "~204 tokens" in m._dm_send_fn.__doc__


if __name__ == "__main__":
    pytest.main( [ __file__, "-v" ] )
