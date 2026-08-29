#!/usr/bin/env python3
"""
Gate-invocable regression for the presentation API client's stop_reason
handling (bug 98d937c2).

`PresentationAPIClient._call_api` used to seed stop_reason to "end_turn" and
coerce a None ResultMessage.stop_reason to "end_turn". Both make an UNKNOWN
completion state look COMPLETE. Downstream, orchestrator._elaborate_async reads
`is_truncated = response.stop_reason != "end_turn"`, so a coerced "end_turn"
makes the truncation-recovery chunked fallback unreachable exactly when it is
needed — a fail-open. Unknown must stay UNKNOWN (None), not "end_turn".

The peer test at src/cosa/tests/.../test_api_client.py is NOT run by the merge
gate (`pytest src/tests/unit/`), so this lives here to be gate-visible.
"""

import asyncio
from unittest.mock import patch

import cosa.agents.presentation_generator.api_client as ac
from cosa.agents.presentation_generator.api_client import PresentationAPIClient


def _run( coro ):
    return asyncio.run( coro )


# ---------------------------------------------------------------------------
# Minimal fake SDK message types + a fake sdk_query async generator
# ---------------------------------------------------------------------------
class _FakeTextBlock:
    def __init__( self, text ):
        self.text = text


class _FakeAssistantMessage:
    def __init__( self, content ):
        self.content = content


class _FakeResultMessage:
    def __init__( self, usage=None, total_cost_usd=None, stop_reason=None ):
        self.usage          = usage
        self.total_cost_usd = total_cost_usd
        self.stop_reason    = stop_reason


def _patch_sdk_types():
    return patch.multiple(
        ac,
        AssistantMessage = _FakeAssistantMessage,
        TextBlock        = _FakeTextBlock,
        ResultMessage    = _FakeResultMessage,
    )


def _fake_sdk_query( messages ):
    async def _gen( prompt, options ):
        for m in messages:
            yield m
    return _gen


def _call( messages ):
    client = PresentationAPIClient()
    with _patch_sdk_types(), patch.object( ac, "sdk_query", _fake_sdk_query( messages ) ):
        return _run( client._call_api(
            model="m", system_prompt="SYS", user_message="hi", temperature=0.7,
        ) )


# ---------------------------------------------------------------------------
# RED before the fix: unknown completion must NOT masquerade as complete
# ---------------------------------------------------------------------------
def test_none_stop_reason_stays_unknown_not_end_turn():
    """A ResultMessage with stop_reason=None yields UNKNOWN, never 'end_turn'."""
    out = _call( [ _FakeAssistantMessage( [ _FakeTextBlock( "partial" ) ] ),
                   _FakeResultMessage( stop_reason=None ) ] )
    assert out.stop_reason is None
    assert out.stop_reason != "end_turn"


def test_absent_result_message_leaves_stop_reason_unknown():
    """No ResultMessage at all → stop_reason stays UNKNOWN, not the 'end_turn' seed."""
    out = _call( [ _FakeAssistantMessage( [ _FakeTextBlock( "partial" ) ] ) ] )
    assert out.stop_reason is None


def test_unknown_stop_reason_reads_as_truncated_downstream():
    """The orchestrator predicate `stop_reason != 'end_turn'` must fire (fail-safe)
    on an unknown state, so the chunked fallback becomes reachable."""
    out = _call( [ _FakeAssistantMessage( [ _FakeTextBlock( "partial" ) ] ),
                   _FakeResultMessage( stop_reason=None ) ] )
    is_truncated = out.stop_reason != "end_turn"   # mirrors orchestrator.py:1061
    assert is_truncated is True


# ---------------------------------------------------------------------------
# GREEN both before and after: real signals are preserved verbatim
# ---------------------------------------------------------------------------
def test_explicit_end_turn_preserved():
    out = _call( [ _FakeAssistantMessage( [ _FakeTextBlock( "done" ) ] ),
                   _FakeResultMessage( stop_reason="end_turn" ) ] )
    assert out.stop_reason == "end_turn"
    assert ( out.stop_reason != "end_turn" ) is False   # not truncated


def test_explicit_truncation_reason_preserved():
    out = _call( [ _FakeAssistantMessage( [ _FakeTextBlock( "cut" ) ] ),
                   _FakeResultMessage( stop_reason="max_tokens" ) ] )
    assert out.stop_reason == "max_tokens"
    assert ( out.stop_reason != "end_turn" ) is True    # truncated → fallback fires
