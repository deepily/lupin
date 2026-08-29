#!/usr/bin/env python3
"""
Contract test: the deep_research agent's cosa_interface.present_choices MUST
accept and forward a `priority` kwarg to the dispatcher.

WHY THIS EXISTS — parity with podcast/presentation, closing a LATENT gap:
  The 2026-08-03 fail-open work made presentation gates call
  voice_io.present_choices(..., priority="high"); voice_io forwards priority
  down to the agent's cosa_interface.present_choices. The presentation
  interface lacked the kwarg and every gate raised
  `TypeError: present_choices() got an unexpected keyword argument 'priority'`
  (fixed in 8ac39294). deep_research shares the same interface shape.

  deep_research gates do NOT pass priority today (orchestrator.py:189 omits it),
  so this is a LATENT gap, not a live failure — but the moment a deep_research
  gate passes priority it would fail identically. This test pins the contract so
  the interface accepts+forwards priority before any gate relies on it. It calls
  the REAL cosa_interface.present_choices (only the dispatcher mocked), so it
  FAILS (TypeError) without the fix and PASSES with it.
"""

from unittest.mock import AsyncMock, patch

import pytest

from cosa.agents.deep_research import cosa_interface


def _one_question():
    return [ {
        "question" : "Research plan ready. How should we proceed?",
        "header"   : "Plan",
        "options"  : [ { "label": "Execute plan", "description": "Proceed" } ]
    } ]


@pytest.mark.asyncio
async def test_present_choices_forwards_priority_to_dispatcher():
    """A blocking gate's priority='high' must reach the dispatcher unchanged."""
    fake = AsyncMock( return_value={ "answers": { "Plan": "Execute plan" } } )
    with patch.object( cosa_interface._dispatcher, "present_choices", fake ):
        result = await cosa_interface.present_choices(
            questions=_one_question(), timeout=120, priority="high"
        )

    assert result[ "answers" ][ "Plan" ] == "Execute plan"
    # The whole point: priority is forwarded. Before the fix this call raised
    # TypeError and never reached the dispatcher at all.
    _, kwargs = fake.call_args
    assert kwargs[ "priority" ] == "high"


@pytest.mark.asyncio
async def test_present_choices_default_priority_is_none():
    """Omitting priority forwards None — non-gate callers are unaffected."""
    fake = AsyncMock( return_value={ "answers": { "Plan": "Execute plan" } } )
    with patch.object( cosa_interface._dispatcher, "present_choices", fake ):
        await cosa_interface.present_choices( questions=_one_question(), timeout=120 )

    _, kwargs = fake.call_args
    assert kwargs[ "priority" ] is None
