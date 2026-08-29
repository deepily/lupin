#!/usr/bin/env python3
"""
SEAM regression (bug 98d937c2): the join between the API client and the
orchestrator's elaboration truncation-recovery.

Every prior test proved ONE side. The orchestrator tests hand `_elaborate_async`
a stop_reason by hand; the api_client tests check the produced stop_reason in
isolation. Nobody crossed the seam — so the coercion that made an UNKNOWN
completion look COMPLETE could pass both suites while the real pipeline failed
(Krishna's 40-run + the 60-run both died in elaboration with truncation
signatures the fallback never got to recover).

This test drives a REAL APIResponse out of the REAL client path (sdk_query
mocked to yield unparseable content and NO ResultMessage → stop_reason produced,
not handed in), feeds it through the orchestrator's REAL `_elaborate_async`, and
asserts the chunked fallback is ENTERED. It goes RED against the old coercion:
a seeded/coerced "end_turn" makes is_truncated False, the parse ValueError
propagates fail-loud, and the fallback is never reached.

Scope: exercises orchestrator._elaborate_async but EDITS nothing there — the
only orchestrator interaction is a test-side spy on `_elaborate_chunked`.
Lives in src/tests/unit/ so the merge gate (`pytest src/tests/unit/`) runs it.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from cosa.agents.presentation_generator import orchestrator as orch_mod
from cosa.agents.presentation_generator.orchestrator import PresentationOrchestratorAgent
from cosa.agents.presentation_generator.state import SlideOutline
import cosa.agents.presentation_generator.api_client as ac
from cosa.agents.presentation_generator.api_client import PresentationAPIClient


def _run( coro ):
    return asyncio.run( coro )


# ---------------------------------------------------------------------------
# Fake SDK message types + fake sdk_query (drives the REAL client)
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


# An unrecoverable, truncated-looking elaboration body: the model was cut off
# mid-JSON. parse_elaboration_response cannot recover an object → raises. This
# is Krishna's "did not contain a recoverable JSON object" signature.
_TRUNCATED_BODY = 'Here are the slides: {"slides": [ {"number": 1, "title": "Intro'


def _outline():
    return [ SlideOutline( number=1, arc_position="opening", type="title",
                           title="Intro", visual_type="text_only", source_hint=None ) ]


def _silence_voice_io():
    return patch.multiple(
        orch_mod.voice_io,
        notify          = AsyncMock(),
        present_choices = AsyncMock(),
        ask_yes_no      = AsyncMock( return_value=True ),
        get_input       = AsyncMock( return_value="" ),
    )


def _drive_elaboration( result_messages ):
    """Run _elaborate_async with a REAL client whose sdk_query yields
    result_messages. Returns the _elaborate_chunked spy so callers assert entry."""
    agent = PresentationOrchestratorAgent( source_path="/x.md", user_id="u" )
    agent._api_client = PresentationAPIClient()        # REAL client — produces the stop_reason
    agent._presentation_state[ "source_content" ] = "some source"

    # Spy on the fallback; a valid return lets _elaborate_async finish cleanly.
    chunked_spy = AsyncMock( return_value=[ {
        "number": 1, "arc_position": "opening", "type": "title", "title": "Intro",
        "visual_type": "text_only", "content_bullets": [],
        "presenter_notes": { "transition": None, "talking_points": [], "timing_seconds": 60, "emphasis": None },
    } ] )
    agent._elaborate_chunked = chunked_spy

    messages = [ _FakeAssistantMessage( [ _FakeTextBlock( _TRUNCATED_BODY ) ] ) ] + result_messages
    with _silence_voice_io(), _patch_sdk_types(), patch.object( ac, "sdk_query", _fake_sdk_query( messages ) ):
        _run( agent._elaborate_async( _outline() ) )
    return chunked_spy


# ---------------------------------------------------------------------------
# The seam: unknown completion → fallback ENTERED (RED against old coercion)
# ---------------------------------------------------------------------------
def test_none_stop_reason_across_seam_enters_chunked_fallback():
    """None stop_reason from the real client → orchestrator treats it as
    truncated and ENTERS the chunked fallback. Old coercion (→'end_turn')
    made this RED: parse ValueError propagated, fallback never reached."""
    spy = _drive_elaboration( [ _FakeResultMessage( stop_reason=None ) ] )
    spy.assert_awaited_once()


def test_absent_result_message_across_seam_enters_chunked_fallback():
    """No ResultMessage at all (seed stop_reason stands) → fallback ENTERED.
    Old seed of 'end_turn' made this RED."""
    spy = _drive_elaboration( [] )
    spy.assert_awaited_once()


def test_explicit_truncation_reason_across_seam_enters_chunked_fallback():
    """A real 'max_tokens' truncation signal → fallback ENTERED (unchanged by fix)."""
    spy = _drive_elaboration( [ _FakeResultMessage( stop_reason="max_tokens" ) ] )
    spy.assert_awaited_once()


# ---------------------------------------------------------------------------
# _slides_from_dicts carries the raw pre-clamp timing onto the model (d5ecb753)
# ---------------------------------------------------------------------------
def test_slides_from_dicts_propagates_timing_seconds_raw():
    """The dict→SlideModel conversion must carry timing_seconds_raw through, or
    the persisted raw dies at the model boundary and Gate 3 / Phase 8 lose the
    truth the parser captured. DELETE-THE-STEP: drop the timing_seconds_raw
    kwarg in _slides_from_dicts and this assertion fails (None instead of 300)."""
    agent = PresentationOrchestratorAgent( source_path="/x.md", user_id="u" )
    dicts = [ {
        "number": 1, "arc_position": "body", "type": "key_point", "title": "T",
        "visual_type": "text_only", "content_bullets": [],
        "presenter_notes": { "talking_points": [], "timing_seconds": 180,
                             "timing_seconds_raw": 300 },
    } ]
    slides = agent._slides_from_dicts( dicts )
    assert slides[ 0 ].presenter_notes.timing_seconds     == 180   # clamped, for layout
    assert slides[ 0 ].presenter_notes.timing_seconds_raw == 300   # raw truth survives

def test_slides_from_dicts_raw_absent_is_none():
    """A dict lacking timing_seconds_raw (e.g. a legacy/partial payload) yields
    None on the model — honest absence, never a guessed value."""
    agent = PresentationOrchestratorAgent( source_path="/x.md", user_id="u" )
    dicts = [ {
        "number": 1, "arc_position": "body", "type": "key_point", "title": "T",
        "visual_type": "text_only", "content_bullets": [],
        "presenter_notes": { "talking_points": [], "timing_seconds": 60 },
    } ]
    slides = agent._slides_from_dicts( dicts )
    assert slides[ 0 ].presenter_notes.timing_seconds_raw is None
