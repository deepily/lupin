#!/usr/bin/env python3
"""
Unit tests for the DM Style Contract inside cosa_voice_mcp.py
(DM Verbosity Reduction, Rick 2026-07-31 —
src/rnd/v0.1.9/2026.07.31-dm-verbosity-reduction/).

The contract is ALWAYS ON — the Phase 1 toggle has been retired. Both the
`instructions` payload § DM Style Contract section and the dm_send docstring
addendum are spliced unconditionally at module import time.

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

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )


def _reload_module():
    """
    Reload lupin_mcp.cosa_voice_mcp fresh.

    Ensures:
        - returns the freshly reloaded module object
    """
    import lupin_mcp.cosa_voice_mcp as m
    importlib.reload( m )
    return m


class TestDmStyleContractAlwaysOn:
    """Both send-side surfaces (instructions + docstring) carry the tag, unconditionally."""

    def test_instructions_section_carries_the_tag( self ):
        m = _reload_module()
        assert m.DM_STYLE_TAG in m._DM_STYLE_CONTRACT_SECTION

    def test_instructions_payload_has_dm_style_contract_heading( self ):
        m = _reload_module()
        assert "## DM Style Contract" in m.mcp.instructions

    def test_dm_send_fn_doc_carries_style_marker( self ):
        m = _reload_module()
        assert "STYLE (governs" in m._dm_send_fn.__doc__
        assert m.DM_STYLE_TAG in m._dm_send_fn.__doc__

    def test_registered_tool_description_carries_style_marker( self ):
        """
        THE load-bearing assertion: proves the doc mutation happened BEFORE
        mcp.tool() registration, not just on the plain Python function.
        """
        m = _reload_module()
        assert "STYLE (governs" in m.dm_send.description

    def test_registered_description_matches_mutated_fn_doc( self ):
        m = _reload_module()
        assert m.dm_send.description.strip() == m._dm_send_fn.__doc__.strip()

    def test_mechanics_only_docstring_is_preserved_verbatim( self ):
        """The addendum is APPENDED — the original mechanics-only doc survives untouched."""
        m = _reload_module()
        assert "PREFERRED" in m._dm_send_fn.__doc__
        assert "~204 tokens" in m._dm_send_fn.__doc__


if __name__ == "__main__":
    pytest.main( [ __file__, "-v" ] )
