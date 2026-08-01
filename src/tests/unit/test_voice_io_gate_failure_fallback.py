#!/usr/bin/env python3
"""
Regression tests for the voice-gate DISPATCH-FAILURE fallback in
cosa.agents.utils.voice_io.present_choices().

Distinct from test_voice_io_non_interactive.py, which covers the
NON-INTERACTIVE path (voice unavailable / no interface / not a tty). That
path returning option[0] is deliberate and already gated.

THIS file covers the other twin: voice IS available, the dispatch is
actually attempted, and the dispatcher RAISES (e.g. the notification API
answers 503 "User is offline and no default response provided"). The
handler at voice_io.py:659-667 catches every Exception and returns
options[0]["label"] as though the user had chosen it.

Observed 2026-08-01, podcast job pg-3995f8a3: the script-review gate
offered [Approve script, Revise script, Cancel], the user was offline,
the dispatch 503'd, and the fallback answered "Approve script". An
unapproved script was rendered to audio and the job reported success.

The dispatcher deliberately raises VoiceGateTimeoutError on a non-zero
exit code (agent_notification_dispatcher.py:576-580, "Bug 12") precisely
so callers can stall and checkpoint-resume. This blanket except defeats
that one layer up.
"""

import sys
import pytest
from unittest.mock import AsyncMock, patch


SCRIPT_REVIEW_QUESTION = [ {
    "question"    : "Podcast script is ready. How would you like to proceed?",
    "header"      : "Script Review",
    "multiSelect" : False,
    "options"     : [
        { "label": "Approve script", "description": "Keep script and continue" },
        { "label": "Revise script",  "description": "Provide feedback for changes" },
        { "label": "Cancel",         "description": "Discard script and stop" }
    ]
} ]


class _StubInterface:
    """Stands in for a configured cosa_interface whose dispatch fails."""

    def __init__( self, exc ):
        self.present_choices = AsyncMock( side_effect=exc )


@pytest.fixture
def voice_io_with_failing_dispatch():
    """
    Yield ( voice_io, make_interface ) with voice forced AVAILABLE so the
    dispatch path is taken, restoring module globals afterwards.
    """
    from cosa.agents.utils import voice_io

    original_interface  = voice_io._cosa_interface
    original_available  = voice_io._voice_available
    original_force_cli  = voice_io._force_cli_mode

    def make_interface( exc ):
        iface = _StubInterface( exc )
        voice_io._cosa_interface = iface
        voice_io._voice_available = True
        voice_io._force_cli_mode  = False
        return iface

    try:
        yield voice_io, make_interface
    finally:
        voice_io._cosa_interface  = original_interface
        voice_io._voice_available = original_available
        voice_io._force_cli_mode  = original_force_cli


class TestPresentChoicesDispatchFailure:
    """A failed dispatch must not be reported as a user selection."""

    @pytest.mark.asyncio
    async def test_offline_user_does_not_silently_approve( self, voice_io_with_failing_dispatch ):
        """
        The exact production shape: dispatch raises because the user is
        offline. The gate must NOT answer "Approve script" on their behalf.

        Either outcome is acceptable as a fix:
          - the exception propagates (caller stalls / checkpoints), or
          - an explicit no-answer marker comes back (empty answers).

        What is NOT acceptable is a confident selection nobody made.
        """
        voice_io, make_interface = voice_io_with_failing_dispatch
        make_interface( RuntimeError( "503 User is offline and no default response provided" ) )

        with patch.object( sys, "stdin" ) as mock_stdin:
            mock_stdin.isatty.return_value = False
            try:
                result = await voice_io.present_choices( SCRIPT_REVIEW_QUESTION )
            except Exception:
                return  # propagating is a valid fix

            answer = result.get( "answers", {} ).get( "Script Review" )
            assert answer != "Approve script", (
                "voice gate manufactured an approval for an unreachable user — "
                f"returned {answer!r} after the dispatch failed"
            )

    @pytest.mark.asyncio
    async def test_failure_is_distinguishable_from_a_real_choice( self, voice_io_with_failing_dispatch ):
        """
        A caller must be able to tell "dispatch failed" from "user picked
        option 1". Today both return the identical payload, so no caller
        can branch on it.
        """
        voice_io, make_interface = voice_io_with_failing_dispatch

        make_interface( RuntimeError( "boom" ) )
        with patch.object( sys, "stdin" ) as mock_stdin:
            mock_stdin.isatty.return_value = False
            try:
                failed = await voice_io.present_choices( SCRIPT_REVIEW_QUESTION )
            except Exception:
                return  # propagating is a valid fix

        real_choice = { "answers": { "Script Review": "Approve script" } }
        assert failed != real_choice, (
            "a failed gate is byte-identical to a genuine 'Approve script' click; "
            "no caller can distinguish them"
        )

    @pytest.mark.asyncio
    async def test_cancel_first_ordering_would_invert_the_bug( self, voice_io_with_failing_dispatch ):
        """
        Pins WHY this is dangerous rather than merely wrong: the fallback's
        answer is decided by option ORDER, not by safety. Reordering the
        same gate silently changes what an offline user is deemed to have
        chosen.
        """
        voice_io, make_interface = voice_io_with_failing_dispatch
        make_interface( RuntimeError( "boom" ) )

        reordered = [ {
            "question"    : "Podcast script is ready. How would you like to proceed?",
            "header"      : "Script Review",
            "multiSelect" : False,
            "options"     : [
                { "label": "Cancel",         "description": "Discard script and stop" },
                { "label": "Approve script", "description": "Keep script and continue" },
            ]
        } ]

        with patch.object( sys, "stdin" ) as mock_stdin:
            mock_stdin.isatty.return_value = False
            try:
                result = await voice_io.present_choices( reordered )
            except Exception:
                return  # propagating is a valid fix

            answer = result.get( "answers", {} ).get( "Script Review" )
            assert answer is None or answer == "", (
                "the fallback's verdict tracks option ORDER, not intent — "
                f"same failure, different answer: {answer!r}"
            )


class TestProvenanceIsReadableByCallers:
    """
    The fix is inert unless a caller can ACT on the difference. These pin
    the contract from the consumer's side, not the producer's.
    """

    @pytest.mark.asyncio
    async def test_caller_can_distinguish_consent_from_silence( self, voice_io_with_failing_dispatch ):
        """
        A gate-keeping caller written the obvious way must reject a
        defaulted answer and accept a genuine one — using only the payload.
        """
        voice_io, make_interface = voice_io_with_failing_dispatch

        def caller_accepts( payload ):
            """How a consequential gate should read the result."""
            return payload.get( "answered", False ) and not payload.get( "default_used", False )

        # 1. Genuine selection -> accepted
        iface = make_interface( RuntimeError( "unused" ) )
        iface.present_choices = AsyncMock(
            return_value={ "answers": { "Script Review": "Approve script" } }
        )
        real = await voice_io.present_choices( SCRIPT_REVIEW_QUESTION )
        assert caller_accepts( real ), "a genuine user selection must be accepted"

        # 2. Dispatch failed, caller declared a default -> REJECTED as consent
        make_interface( RuntimeError( "503 offline" ) )
        defaulted = await voice_io.present_choices(
            SCRIPT_REVIEW_QUESTION,
            response_default={ "Script Review": "Approve script" }
        )
        assert defaulted[ "answers" ][ "Script Review" ] == "Approve script"
        assert not caller_accepts( defaulted ), (
            "a defaulted answer carries the same LABEL as a real approval; "
            "the caller must still be able to refuse it as consent"
        )

    @pytest.mark.asyncio
    async def test_default_source_names_the_path( self, voice_io_with_failing_dispatch ):
        """
        Provenance is specific enough to branch on: a transport failure is
        distinguishable from a queue/Docker run, not just 'some default'.
        """
        voice_io, make_interface = voice_io_with_failing_dispatch
        make_interface( RuntimeError( "503 offline" ) )

        result = await voice_io.present_choices(
            SCRIPT_REVIEW_QUESTION,
            response_default={ "Script Review": "Cancel" }
        )
        assert result[ "default_source" ] == "dispatch_failed"
        assert result[ "answers" ][ "Script Review" ] == "Cancel"

    @pytest.mark.asyncio
    async def test_partial_default_is_refused( self, voice_io_with_failing_dispatch ):
        """
        Covering only some questions is still a guess for the rest, so it
        raises and names exactly which headers were uncovered.
        """
        voice_io, make_interface = voice_io_with_failing_dispatch
        make_interface( RuntimeError( "503 offline" ) )

        two_questions = SCRIPT_REVIEW_QUESTION + [ {
            "question"    : "Which voice?",
            "header"      : "Voice",
            "multiSelect" : False,
            "options"     : [ { "label": "Maria" }, { "label": "Mr. Radio" } ]
        } ]

        with pytest.raises( voice_io.VoiceGateNoDefaultError ) as exc:
            await voice_io.present_choices(
                two_questions,
                response_default={ "Script Review": "Cancel" }   # 'Voice' uncovered
            )
        assert exc.value.headers == [ "Voice" ]


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
