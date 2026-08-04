#!/usr/bin/env python3
"""
Contract test: the presentation agent's cosa_interface.present_choices MUST
accept and forward a `priority` kwarg to the dispatcher.

WHY THIS EXISTS — the gap the gate tests could not see:
  The 2026-08-03 fail-open fix made every presentation gate call
  voice_io.present_choices(..., priority="high") so the gate alert reaches the
  user's TTS channel. voice_io.present_choices forwards that priority down to
  the agent's cosa_interface.present_choices. But the presentation
  cosa_interface signature did not accept `priority`, so EVERY gate raised
  `TypeError: present_choices() got an unexpected keyword argument 'priority'`,
  which voice_io caught as a dispatch failure and fail-opened. Net effect: the
  human-answer path was unreachable — the question never dispatched to a human
  (observed live on job pr-bf7ac6f5: all four gates resolved by DECLARED
  DEFAULT / dispatch_failed).

  test_presentation_gates_refuse_forged_approval.py could NOT catch this: it
  mocks present_choices, so it never exercises the real signature. This test
  calls the REAL cosa_interface.present_choices (only the dispatcher mocked),
  so it FAILS (TypeError) without the fix and PASSES with it.
"""

from unittest.mock import AsyncMock, patch

import pytest

from cosa.agents.presentation_generator import cosa_interface


def _one_question():
    return [ {
        "question" : "How does this narrative arc look?",
        "header"   : "Narrative Arc",
        "options"  : [ { "label": "Approve", "description": "Proceed" } ]
    } ]


@pytest.mark.asyncio
async def test_present_choices_forwards_priority_to_dispatcher():
    """A blocking gate's priority='high' must reach the dispatcher unchanged."""
    fake = AsyncMock( return_value={ "answers": { "Narrative Arc": "Approve" } } )
    with patch.object( cosa_interface._dispatcher, "present_choices", fake ):
        result = await cosa_interface.present_choices(
            questions=_one_question(), timeout=120, priority="high"
        )

    assert result[ "answers" ][ "Narrative Arc" ] == "Approve"
    # The whole point: priority is forwarded. Before the fix this call raised
    # TypeError and never reached the dispatcher at all.
    _, kwargs = fake.call_args
    assert kwargs[ "priority" ] == "high"


@pytest.mark.asyncio
async def test_present_choices_default_priority_is_none():
    """Omitting priority forwards None — non-gate callers are unaffected."""
    fake = AsyncMock( return_value={ "answers": { "Narrative Arc": "Approve" } } )
    with patch.object( cosa_interface._dispatcher, "present_choices", fake ):
        await cosa_interface.present_choices( questions=_one_question(), timeout=120 )

    _, kwargs = fake.call_args
    assert kwargs[ "priority" ] is None
