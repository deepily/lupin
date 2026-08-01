#!/usr/bin/env python3
"""
Consumer-side regression tests for the four presentation approval gates
(row fef0ed85).

The producer-side fix lives in cosa.agents.utils.voice_io and is covered by
test_voice_io_gate_failure_fallback.py. This file covers the OTHER half: the
consumer. Before 2026-08-01 every gate in
cosa/agents/presentation_generator/orchestrator.py did

    result.get( "answers", {} ).get( "<Header>", "Approve" )

and caught every exception with `return True` "so as not to block the
pipeline". So a payload that carried no answer at all, and a gate whose voice
dispatch failed outright, both became an approval. Four gates in a row could
approve a deck with no human present.

What is pinned here:
  - a MISSING answer raises instead of approving       (all four gates)
  - a FAILED dispatch raises instead of approving      (all four gates)
  - a genuine click is still honoured, both ways       (Approve -> True,
                                                        Cancel  -> False)
  - a DECLARED default is honoured but leaves a record — a defaulted
    "Approve" and a real "Approve" return the same bool, so the log line is
    the only thing that tells them apart, and it must be there.
  - the gates never pass response_default themselves, so no presentation gate
    can be answered by a default in production.

Design note: the gate inputs are duck-typed stubs, not Pydantic models. These
tests are about the approval contract, not about model construction — a real
SlideModel would add failure modes that have nothing to do with the defect.
"""

import sys
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from cosa.agents.presentation_generator.orchestrator import (
    PresentationOrchestratorAgent,
    VoiceGateNotAnsweredError,
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
    """Gate 3 input: elaborated slides."""
    return [
        SimpleNamespace(
            number=1, type="title", title="Why this matters", visual_type="text_only",
            content_bullets=[ "a", "b" ], presenter_notes=SimpleNamespace( timing_seconds=45 )
        ),
        SimpleNamespace(
            number=2, type="content", title="The mechanism", visual_type="diagram",
            content_bullets=[ "c" ], presenter_notes=SimpleNamespace( timing_seconds=75 )
        ),
    ]


def _presentation():
    """Gate 4 input: rendered presentation model."""
    return SimpleNamespace( title="Deck" )


def _agent():
    """A non-dry-run orchestrator — dry_run short-circuits every gate to True."""
    return PresentationOrchestratorAgent(
        source_path = "/tmp/does-not-need-to-exist.md",
        user_id     = "test-user",
        dry_run     = False,
        debug       = False,
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
# Tests
# =============================================================================

@pytest.mark.parametrize( "gate_name,header,method_name,factory", GATES )
class TestGateRefusesToInventConsent:

    @pytest.mark.asyncio
    async def test_missing_answer_raises_instead_of_approving( self, gate_name, header, method_name, factory ):
        """
        The production shape of the defect: voice I/O returns a payload with
        no answer for this gate's header. That must not become an approval.
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

    @pytest.mark.asyncio
    async def test_failed_dispatch_raises_instead_of_approving( self, gate_name, header, method_name, factory ):
        """
        The other twin: the dispatch itself raises (503 offline, timeout).
        The gate previously logged a warning and returned True.
        """
        agent = _agent()

        with patch( "cosa.agents.presentation_generator.orchestrator.voice_io" ) as vio:
            vio.present_choices = AsyncMock( side_effect=RuntimeError( "503 User is offline" ) )
            vio.notify          = AsyncMock()
            vio.get_input       = AsyncMock( return_value="" )

            with pytest.raises( VoiceGateNotAnsweredError ):
                await _call( agent, method_name, factory )

    @pytest.mark.asyncio
    async def test_genuine_approval_still_proceeds( self, gate_name, header, method_name, factory ):
        """The fix must not break the working path: a real click proceeds."""
        agent = _agent()

        with patch( "cosa.agents.presentation_generator.orchestrator.voice_io" ) as vio:
            vio.present_choices = AsyncMock( return_value={ "answers": { header: "Approve" }, "answered": True } )
            vio.notify          = AsyncMock()

            assert await _call( agent, method_name, factory ) is True

    @pytest.mark.asyncio
    async def test_genuine_cancel_still_stops( self, gate_name, header, method_name, factory ):
        """And a real Cancel must still stop the pipeline."""
        agent = _agent()

        with patch( "cosa.agents.presentation_generator.orchestrator.voice_io" ) as vio:
            vio.present_choices = AsyncMock( return_value={ "answers": { header: "Cancel" }, "answered": True } )
            vio.notify          = AsyncMock()

            assert await _call( agent, method_name, factory ) is False

    @pytest.mark.asyncio
    async def test_declared_default_is_honoured_but_leaves_a_record(
        self, gate_name, header, method_name, factory, caplog
    ):
        """
        A declared default IS a supported unattended path — the caller chose
        the value — so the gate proceeds. But a defaulted "Approve" and a
        human "Approve" return the identical bool, so the log line is the only
        surviving difference. If it is absent the two are indistinguishable
        after the fact, which is the defect wearing the fix's clothes.
        """
        agent = _agent()
        defaulted = {
            "answers"        : { header: "Approve" },
            "answered"       : False,
            "default_used"   : True,
            "default_source" : "dispatch_failed",
        }

        with patch( "cosa.agents.presentation_generator.orchestrator.voice_io" ) as vio:
            vio.present_choices = AsyncMock( return_value=defaulted )
            vio.notify          = AsyncMock()

            with caplog.at_level( logging.WARNING, logger="cosa.agents.presentation_generator.orchestrator" ):
                assert await _call( agent, method_name, factory ) is True

        record = " ".join( r.getMessage() for r in caplog.records )
        assert "DECLARED DEFAULT" in record, (
            f"{gate_name} accepted a defaulted approval and left no trace; it is "
            f"now indistinguishable from a human clicking Approve"
        )
        assert "dispatch_failed" in record, (
            f"{gate_name} logged the default but not WHICH path produced it"
        )


class TestGatesNeverDeclareTheirOwnDefault:
    """
    The gates are consequential enough that no default is appropriate — the
    orchestrator must never hand voice_io a response_default of its own, or it
    would be re-introducing the forged approval one layer up.
    """

    @pytest.mark.parametrize( "gate_name,header,method_name,factory", GATES )
    @pytest.mark.asyncio
    async def test_no_response_default_is_passed( self, gate_name, header, method_name, factory ):
        agent = _agent()

        with patch( "cosa.agents.presentation_generator.orchestrator.voice_io" ) as vio:
            vio.present_choices = AsyncMock( return_value={ "answers": { header: "Approve" }, "answered": True } )
            vio.notify          = AsyncMock()

            await _call( agent, method_name, factory )

            kwargs = vio.present_choices.await_args.kwargs
        assert "response_default" not in kwargs or kwargs[ "response_default" ] is None, (
            f"{gate_name} declared its own default — an unattended run would "
            f"approve itself again, just one layer further out"
        )


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
