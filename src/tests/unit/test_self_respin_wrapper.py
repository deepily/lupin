"""
Signature-lockdown for the self_respin() MCP tool (row 9e0678f6, WI-2).

Cheech's attack: the core's injectable seams (ask_fn, schedule_fn, resolve_tmux_fn)
are exactly what would sell the "unskippable gate" if an agent call could reach
them. So the WRAPPER must expose NONE of them, and NO session_id (a caller-supplied
id aims the /clear at another pane). This proves the front door has only the four
safe parameters — by inspecting the tool's signature and by trying to pass the
dangerous ones (which raises TypeError at argument binding, before the body runs,
so no live tmux/ask/clear is ever touched here).

The wrapper's BEHAVIOUR is covered by test_self_respin_core.py (self_respin_from_bridge,
perform_self_respin, resolve_identity_from_cc_meta); this file guards its SHAPE.
"""

import inspect

import pytest

from lupin_mcp.cosa_voice_mcp import self_respin


# FastMCP wraps the tool as a FunctionTool; the underlying function is `.fn`.
_FN = self_respin.fn


ALLOWED = { "memento_path", "memento_nonce", "delay_seconds", "cycle_window_seconds" }
FORBIDDEN = [ "session_id", "ask_fn", "schedule_fn", "resolve_tmux_fn", "read_text_fn",
              "write_json_fn", "pre_clear_status", "persona", "base_dir", "now" ]


def test_wrapper_exposes_only_the_four_safe_parameters():
    params = inspect.signature( _FN ).parameters
    assert set( params.keys() ) == ALLOWED


def test_wrapper_has_no_var_keyword_backdoor():
    """No **kwargs — a **kwargs would silently forward a seam into the core."""
    kinds = [ p.kind for p in inspect.signature( _FN ).parameters.values() ]
    assert inspect.Parameter.VAR_KEYWORD  not in kinds
    assert inspect.Parameter.VAR_POSITIONAL not in kinds


@pytest.mark.parametrize( "bad_kwarg", FORBIDDEN )
def test_passing_a_seam_or_session_id_raises_typeerror( bad_kwarg ):
    """Argument binding rejects the dangerous kwargs BEFORE the body runs — so this
    never touches live tmux, the ask, or a real /clear."""
    with pytest.raises( TypeError ):
        _FN( memento_path="/m", memento_nonce="u1", **{ bad_kwarg: "attack" } )
