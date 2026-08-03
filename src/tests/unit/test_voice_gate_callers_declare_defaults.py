#!/usr/bin/env python3
"""
Source-level gate: every caller of a refusing voice gate must declare what to
do when no human can be reached.

Row 741011ba. The library half of that row makes choose(), select_themes() and
select_topics() RAISE when nobody answered and the caller named no default —
which is correct, and which also means the callers now carry the decision.

Two of the deep_research call sites wrap their call in `except RuntimeError`,
and VoiceGateNoDefaultError IS a RuntimeError. So a call site that quietly
loses its `response_default=` does not crash loudly: it makes every unattended
research run abort into a cancelled result with a logged reason. That failure
is invisible in a green unit suite and would only surface as "deep research
stopped working in the queue."

This gate is cheap and structural on purpose. Exercising run_research
end-to-end to prove the same thing would cost API spend and a live server, and
would still not fail on the specific edit this is guarding against.

It reads the SOURCE rather than importing and calling, because the thing being
asserted is a property of the call site as written, not of one execution path
through it.
"""

import ast
import sys
from pathlib import Path

import pytest

import cosa.utils.util as cu


# Gates that refuse rather than guess. Keep in step with voice_io.
REFUSING_GATES = { "choose", "select_themes", "select_topics" }

# Files that call them in production. Tests are excluded deliberately: a test
# asserting the REFUSAL must be able to call without a default.
CALLER_FILES = [
    "src/cosa/agents/deep_research/cli.py",
    "src/cosa/agents/deep_research/narrowing_harness.py",
]


def _gate_calls( path: Path ):
    """
    Yield ( function_name, gate_name, lineno, has_default ) for every call to a
    refusing gate in this file.
    """
    tree = ast.parse( path.read_text() )

    for fn in [ n for n in ast.walk( tree ) if isinstance( n, ( ast.FunctionDef, ast.AsyncFunctionDef ) ) ]:
        for node in ast.walk( fn ):
            if not isinstance( node, ast.Call ):
                continue
            func = node.func
            # Only attribute calls — voice_io.choose(...), not a local choose()
            if not isinstance( func, ast.Attribute ) or func.attr not in REFUSING_GATES:
                continue
            has_default = any( kw.arg == "response_default" for kw in node.keywords )
            yield fn.name, func.attr, node.lineno, has_default


def _all_calls():
    root = Path( cu.get_project_root() )
    found = []
    for rel in CALLER_FILES:
        path = root / rel
        assert path.exists(), f"caller file has moved or been renamed: {rel}"
        found.extend( ( rel, ) + c for c in _gate_calls( path ) )
    return found


def test_the_gate_can_actually_see_the_call_sites():
    """
    Control. If a refactor moves these calls, renames the module alias, or
    switches to a bare `choose(...)` import, this file would go green by
    finding nothing at all — a gate that passes because it is blind.
    """
    calls = _all_calls()
    assert len( calls ) >= 6, (
        f"expected at least 6 refusing-gate call sites across {CALLER_FILES}, "
        f"found {len( calls )}. Either the callers moved (update CALLER_FILES) "
        f"or the calls stopped being attribute calls — in which case this gate "
        f"is no longer watching anything."
    )


@pytest.mark.parametrize( "rel,fn_name,gate,lineno,has_default", _all_calls() )
def test_every_gate_call_declares_a_default( rel, fn_name, gate, lineno, has_default ):
    """
    Each production call to a refusing gate must say what to do when no human
    is reachable — because the alternative is not a crash, it is a silent
    cancelled run.
    """
    assert has_default, (
        f"{rel}:{lineno} in {fn_name}() calls {gate}() with no response_default. "
        f"Unattended, that raises VoiceGateNoDefaultError; two of these call "
        f"sites catch RuntimeError and turn it into a cancelled run, so the "
        f"failure is silent. Declare what an absent human means here."
    )


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
