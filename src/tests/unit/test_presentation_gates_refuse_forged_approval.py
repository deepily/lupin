#!/usr/bin/env python3
"""
Contract tests for the four presentation approval gates.

HISTORY — TWO reversals, both deliberate:
  - 2026-08-01 (row fef0ed85): every gate used to do
    `result.get("answers", {}).get("<Header>", "Approve")` and catch every
    exception with `return True`. So a payload with no answer, and a gate whose
    dispatch failed, both became an approval. That forged-approval defect was
    fixed by making the gates FAIL CLOSED: refuse anything that is not a real
    answer, and declare NO default of their own.
  - 2026-08-03 (Rick's call, reversing the manager's park): the presentation
    gates now FAIL OPEN, exactly like the podcast script-review gate. Rick's
    demo requirement is that generation must not stall when he misses a prompt:
    after the review timeout — OR when the ask cannot be delivered (the 503 that
    killed job pr-b1ea3708, operator-routed to an offline account) — the gate
    continues on its own via an explicitly-declared `response_default`.

    Fail-open is NOT the old forged approval: the value is one the caller chose
    on purpose (`{header: "Approve"}`), voice_io flags it
    `default_used=True, default_source="dispatch_failed"`, and `_read_gate_answer`
    logs a DECLARED-DEFAULT warning so a defaulted approval stays distinguishable
    from a human one.

What is pinned here (all four gates):
  - a genuine click is still honoured           (Approve -> True, Cancel -> False)
  - a payload with NO usable answer still RAISES (voice layer returned nothing —
    that is a malfunction, not consent, and is NOT a declared default)
  - a dispatch failure RESOLVED BY THE DEFAULT now CONTINUES (returns True) and
    leaves a DECLARED-DEFAULT / dispatch_failed record  ← the 503 path
  - every gate DECLARES response_default={header: "Approve"} + a timeout + a
    high-priority alert, and appends the auto-continue disclosure to the question
  - the auto-continue disclosure builder is exercised both ways

Design note: the gate inputs are duck-typed stubs, not Pydantic models. These
tests are about the approval contract, not model construction.
"""

import sys
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from cosa.agents.presentation_generator.orchestrator import (
    PresentationOrchestratorAgent,
    VoiceGateNotAnsweredError,
    _build_auto_continue_disclosure,
)


# =============================================================================
# Duck-typed gate inputs (only the attributes each summary builder reads)
# =============================================================================

def _sections():
    """Gate 1 input: narrative sections."""
    return [
        SimpleNamespace( heading="Opening", arc_position=SimpleNamespace( value="opening" ), proposed_slides=2 ),
        SimpleNamespace( heading="Body",    arc_position=SimpleNamespace( value="body"    ), proposed_slides=5 ),
    ]


def _outline():
    """Gate 2 input: slide outline entries."""
    return [
        SimpleNamespace( number=1, type="title",   title="Why this matters", visual_type="text_only", arc_position="opening" ),
        SimpleNamespace( number=2, type="content", title="The mechanism",    visual_type="diagram",   arc_position="body"    ),
    ]


def _slides():
    """Gate 3 input: elaborated slides. presenter_notes carries timing_seconds_raw
    to match the real SlideModel contract (bug d5ecb753); here raw == clamped, so
    no clamp disclosure fires for these baseline slides."""
    return [
        SimpleNamespace(
            number=1, type="title", title="Why this matters", visual_type="text_only",
            content_bullets=[ "a", "b" ],
            presenter_notes=SimpleNamespace( timing_seconds=45, timing_seconds_raw=45 )
        ),
        SimpleNamespace(
            number=2, type="content", title="The mechanism", visual_type="diagram",
            content_bullets=[ "c" ],
            presenter_notes=SimpleNamespace( timing_seconds=75, timing_seconds_raw=75 )
        ),
    ]


def _presentation():
    """Gate 4 input: rendered presentation model."""
    return SimpleNamespace( title="Deck" )


def _agent():
    """A non-offline orchestrator — offline_mode short-circuits every gate to True."""
    return PresentationOrchestratorAgent(
        source_path  = "/tmp/does-not-need-to-exist.md",
        user_id      = "test-user",
        offline_mode = False,
        debug        = False,
    )


# ( gate_name, header, bound-method-name, input-factory )
GATES = [
    ( "Gate 1", "Narrative Arc",  "_gate_1_narrative_review", _sections     ),
    ( "Gate 2", "Slide Outline",  "_gate_2_outline_review",   _outline      ),
    ( "Gate 3", "Content Review", "_gate_3_content_review",   _slides       ),
    ( "Gate 4", "Visual Review",  "_gate_4_render_review",    _presentation ),
]


def _call( agent, method_name, factory ):
    """Invoke a gate with its input; Gate 4 also needs rendered visuals."""
    agent._presentation_state[ "visuals_rendered" ] = 3   # else Gate 4 short-circuits
    return getattr( agent, method_name )( factory() )


# =============================================================================
# Genuine clicks — the working path must survive the fail-open change
# =============================================================================

@pytest.mark.parametrize( "gate_name,header,method_name,factory", GATES )
class TestGateHonoursGenuineClick:

    @pytest.mark.asyncio
    async def test_genuine_approval_still_proceeds( self, gate_name, header, method_name, factory ):
        agent = _agent()
        with patch( "cosa.agents.presentation_generator.orchestrator.voice_io" ) as vio:
            vio.present_choices = AsyncMock( return_value={ "answers": { header: "Approve" }, "answered": True } )
            vio.notify          = AsyncMock()
            assert await _call( agent, method_name, factory ) is True

    @pytest.mark.asyncio
    async def test_genuine_cancel_still_stops( self, gate_name, header, method_name, factory ):
        agent = _agent()
        with patch( "cosa.agents.presentation_generator.orchestrator.voice_io" ) as vio:
            vio.present_choices = AsyncMock( return_value={ "answers": { header: "Cancel" }, "answered": True } )
            vio.notify          = AsyncMock()
            assert await _call( agent, method_name, factory ) is False


# =============================================================================
# A payload with no usable answer is still a refusal, not consent
# =============================================================================

@pytest.mark.parametrize( "gate_name,header,method_name,factory", GATES )
class TestGateStillRefusesGarbage:

    @pytest.mark.asyncio
    async def test_missing_answer_raises_instead_of_approving( self, gate_name, header, method_name, factory ):
        """
        voice_io returned a payload with no answer for this header AND no
        declared default resolved it — that is the voice layer malfunctioning,
        not a human, and not the caller's chosen default. It must NOT proceed.
        (The fail-open default protects against silence/503; it does not turn a
        genuinely empty payload into an approval.)
        """
        agent = _agent()
        with patch( "cosa.agents.presentation_generator.orchestrator.voice_io" ) as vio:
            vio.present_choices = AsyncMock( return_value={ "answers": {} } )
            vio.notify          = AsyncMock()
            vio.get_input       = AsyncMock( return_value="" )
            with pytest.raises( VoiceGateNotAnsweredError ) as exc:
                await _call( agent, method_name, factory )
        assert header in str( exc.value ), (
            f"{gate_name} refused, but its error does not name the header it "
            f"was waiting on — a caller cannot tell which gate failed"
        )


# =============================================================================
# The 503 path — a dispatch failure resolved by the default now CONTINUES
# =============================================================================

@pytest.mark.parametrize( "gate_name,header,method_name,factory", GATES )
class TestGateFailsOpenOnDispatchFailure:

    @pytest.mark.asyncio
    async def test_dispatch_failure_default_continues_with_a_record(
        self, gate_name, header, method_name, factory, caplog
    ):
        """
        This is the exact failure that killed pr-b1ea3708: the gate ask was
        undeliverable (503, operator-routed to an offline account). With the
        fail-open default declared, voice_io no longer raises — it RESOLVES the
        gate to the caller's default and flags it. The gate must CONTINUE
        (return True), and the DECLARED-DEFAULT / dispatch_failed record must be
        present so a defaulted approval stays distinguishable from a human one.
        """
        agent = _agent()
        resolved_default = {
            "answers"        : { header: "Approve" },
            "answered"       : False,
            "default_used"   : True,
            "default_source" : "dispatch_failed",
        }
        with patch( "cosa.agents.presentation_generator.orchestrator.voice_io" ) as vio:
            vio.present_choices = AsyncMock( return_value=resolved_default )
            vio.notify          = AsyncMock()
            with caplog.at_level( logging.WARNING, logger="cosa.agents.presentation_generator.orchestrator" ):
                assert await _call( agent, method_name, factory ) is True

        record = " ".join( r.getMessage() for r in caplog.records )
        assert "DECLARED DEFAULT" in record, (
            f"{gate_name} continued on a defaulted approval but left no trace — it "
            f"is now indistinguishable from a human clicking Approve"
        )
        assert "dispatch_failed" in record, (
            f"{gate_name} logged the default but not WHICH path produced it"
        )


# =============================================================================
# Every gate declares the fail-open shape (mirror of the podcast gate)
# =============================================================================

@pytest.mark.parametrize( "gate_name,header,method_name,factory", GATES )
class TestGatesDeclareFailOpenShape:

    @pytest.mark.asyncio
    async def test_gate_declares_default_timeout_priority_and_disclosure(
        self, gate_name, header, method_name, factory
    ):
        agent = _agent()
        with patch( "cosa.agents.presentation_generator.orchestrator.voice_io" ) as vio:
            vio.present_choices = AsyncMock( return_value={ "answers": { header: "Approve" }, "answered": True } )
            vio.notify          = AsyncMock()
            await _call( agent, method_name, factory )
            kwargs = vio.present_choices.await_args.kwargs

        assert kwargs.get( "response_default" ) == { header: "Approve" }, (
            f"{gate_name} must declare a fail-open default of Approve so a silent "
            f"or undeliverable gate continues instead of dead-lettering the job"
        )
        assert kwargs.get( "timeout" ) == 600, (
            f"{gate_name} must pass the review timeout (600s) so the default has a "
            f"window to fire on silence"
        )
        assert kwargs.get( "priority" ) == "high", (
            f"{gate_name} approval prompt must alert at HIGH so the TTS reaches Rick"
        )
        question = kwargs[ "questions" ][ 0 ][ "question" ]
        assert "finish the presentation automatically" in question, (
            f"{gate_name} must tell the user, in the spoken question, that silence "
            f"continues generation (Rick's 15:07 requirement)"
        )


# =============================================================================
# The auto-continue disclosure builder
# =============================================================================

class TestAutoContinueDisclosure:

    def test_wording_names_the_minutes_and_the_presentation( self ):
        text = _build_auto_continue_disclosure( 600 )
        assert "10 minutes" in text
        assert "finish the presentation automatically" in text

    def test_floors_to_whole_minutes_minimum_one( self ):
        assert "1 minute" in _build_auto_continue_disclosure( 30 )   # 30s floors to 1 min, singular
        assert "2 minutes" in _build_auto_continue_disclosure( 150 ) # 150s -> 2 min, plural

    @pytest.mark.parametrize( "bad", [ 0, -1, 3.5, True, "600" ] )
    def test_non_positive_int_raises( self, bad ):
        with pytest.raises( ValueError ):
            _build_auto_continue_disclosure( bad )


# =============================================================================
# Gate 3 discloses a clamp-affected duration (bug d5ecb753)
# =============================================================================

def _clamped_slides():
    """Gate 3 input where one slide's raw timing overshot the ceiling and was
    clamped: slide 1 raw 300 → clamped 180, slide 2 raw 60 → 60 (untouched)."""
    return [
        SimpleNamespace(
            number=1, type="content", title="Dense", visual_type="text_only",
            content_bullets=[ "a" ],
            presenter_notes=SimpleNamespace( timing_seconds=180, timing_seconds_raw=300 )
        ),
        SimpleNamespace(
            number=2, type="title", title="Intro", visual_type="text_only",
            content_bullets=[ "b" ],
            presenter_notes=SimpleNamespace( timing_seconds=60, timing_seconds_raw=60 )
        ),
    ]


class TestGate3ClampDisclosure:
    """Gate 3 is the surface the reader acts on, so a clamp-affected duration must
    be disclosed THERE — not only in a log (Cheech, bug d5ecb753)."""

    async def _capture_abstract( self, slides ):
        agent = _agent()
        with patch( "cosa.agents.presentation_generator.orchestrator.voice_io" ) as vio:
            vio.present_choices = AsyncMock( return_value={ "answers": { "Content Review": "Approve" }, "answered": True } )
            vio.notify          = AsyncMock()
            await agent._gate_3_content_review( slides )
            return vio.present_choices.await_args.kwargs[ "abstract" ]

    @pytest.mark.asyncio
    async def test_discloses_clamp_with_counts_and_both_totals( self ):
        abstract = await self._capture_abstract( _clamped_slides() )
        assert "model-estimated and clamp-affected" in abstract
        assert "1 of 2 slides" in abstract          # how many the clamp hit
        assert "6.0m" in abstract                    # raw total (300+60)/60
        assert "4.0m" in abstract                    # clamped total (180+60)/60
        # Both model numbers are unreliable — the real measure is the script word
        # count (Cheech: raw overshoots too; "floor" wrongly implied raw is truer).
        assert "BOTH unreliable" in abstract
        assert "word count" in abstract
        assert "floor" not in abstract

    @pytest.mark.asyncio
    async def test_no_disclosure_when_nothing_clamped( self ):
        # Baseline slides (raw == clamped) → the confident number stands alone,
        # no false alarm.
        abstract = await self._capture_abstract( _slides() )
        assert "clamp-affected" not in abstract


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
