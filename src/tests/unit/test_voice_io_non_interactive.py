#!/usr/bin/env python3
"""
Unit tests for voice_io non-interactive fallback behavior.

Verifies that voice_io functions do NOT block on input() when running
in non-interactive contexts (Docker, queue jobs, daemons). This was
the root cause of Bug #3 (Session 283): the podcast orchestrator hung
at script review because voice was unavailable and the CLI fallback
called input(), which blocks indefinitely in non-interactive contexts.

Test groups:
    1. _is_interactive() helper
    2. ask_yes_no() non-interactive defaults
    3. get_input() non-interactive defaults
    4. choose() non-interactive defaults
    5. present_choices() non-interactive defaults
    6. select_themes() / select_topics() non-interactive defaults
"""

import os
import sys
import asyncio
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

# ============================================================================
# Bootstrap PYTHONPATH
# ============================================================================

lupin_root = os.environ.get( "LUPIN_ROOT" )
if lupin_root is None:
    lupin_root = os.path.abspath( os.path.join( os.path.dirname( __file__ ), "..", ".." ) )
src_path = os.path.join( lupin_root, "src" )
if src_path not in sys.path:
    sys.path.insert( 0, src_path )


# ============================================================================
# Test 1: _is_interactive() helper
# ============================================================================

class TestIsInteractive:
    """Verify _is_interactive() detects non-interactive stdin."""

    def test_returns_false_when_stdin_not_tty( self ):
        """Non-TTY stdin should return False."""
        from cosa.agents.utils.voice_io import _is_interactive
        with patch.object( sys, "stdin" ) as mock_stdin:
            mock_stdin.isatty.return_value = False
            assert _is_interactive() is False

    def test_returns_true_when_stdin_is_tty( self ):
        """TTY stdin should return True."""
        from cosa.agents.utils.voice_io import _is_interactive
        with patch.object( sys, "stdin" ) as mock_stdin:
            mock_stdin.isatty.return_value = True
            assert _is_interactive() is True

    def test_returns_false_when_stdin_is_none( self ):
        """None stdin (e.g., daemon) should return False."""
        from cosa.agents.utils.voice_io import _is_interactive
        with patch.object( sys, "stdin", None ):
            assert _is_interactive() is False

    def test_returns_false_on_exception( self ):
        """Exception from isatty() should return False."""
        from cosa.agents.utils.voice_io import _is_interactive
        with patch.object( sys, "stdin" ) as mock_stdin:
            mock_stdin.isatty.side_effect = OSError( "broken pipe" )
            assert _is_interactive() is False


# ============================================================================
# Test 2: ask_yes_no() non-interactive defaults
# ============================================================================

class TestAskYesNoNonInteractive:
    """Verify ask_yes_no returns default without blocking in non-interactive mode."""

    @pytest.mark.asyncio
    async def test_returns_default_yes_when_non_interactive( self ):
        """ask_yes_no(default='yes') returns True in non-interactive mode."""
        from cosa.agents.utils import voice_io

        # Force CLI fallback (no cosa_interface) + non-interactive stdin
        original_interface = voice_io._cosa_interface
        original_available = voice_io._voice_available
        try:
            voice_io._cosa_interface = None
            voice_io._voice_available = None

            with patch.object( sys, "stdin" ) as mock_stdin:
                mock_stdin.isatty.return_value = False
                result = await voice_io.ask_yes_no( "Continue?", default="yes" )
                assert result is True
        finally:
            voice_io._cosa_interface = original_interface
            voice_io._voice_available = original_available

    @pytest.mark.asyncio
    async def test_returns_default_no_when_non_interactive( self ):
        """ask_yes_no(default='no') returns False in non-interactive mode."""
        from cosa.agents.utils import voice_io

        original_interface = voice_io._cosa_interface
        original_available = voice_io._voice_available
        try:
            voice_io._cosa_interface = None
            voice_io._voice_available = None

            with patch.object( sys, "stdin" ) as mock_stdin:
                mock_stdin.isatty.return_value = False
                result = await voice_io.ask_yes_no( "Proceed?", default="no" )
                assert result is False
        finally:
            voice_io._cosa_interface = original_interface
            voice_io._voice_available = original_available

    @pytest.mark.asyncio
    async def test_does_not_call_input_when_non_interactive( self ):
        """input() should NEVER be called in non-interactive mode."""
        from cosa.agents.utils import voice_io

        original_interface = voice_io._cosa_interface
        original_available = voice_io._voice_available
        try:
            voice_io._cosa_interface = None
            voice_io._voice_available = None

            with patch.object( sys, "stdin" ) as mock_stdin:
                mock_stdin.isatty.return_value = False
                with patch( "builtins.input", side_effect=AssertionError( "input() should not be called" ) ):
                    result = await voice_io.ask_yes_no( "Question?", default="yes" )
                    assert result is True
        finally:
            voice_io._cosa_interface = original_interface
            voice_io._voice_available = original_available


# ============================================================================
# Test 3: get_input() non-interactive defaults
# ============================================================================

class TestGetInputNonInteractive:
    """Verify get_input returns None without blocking in non-interactive mode."""

    @pytest.mark.asyncio
    async def test_returns_none_when_non_interactive( self ):
        """get_input() returns None in non-interactive mode."""
        from cosa.agents.utils import voice_io

        original_interface = voice_io._cosa_interface
        original_available = voice_io._voice_available
        try:
            voice_io._cosa_interface = None
            voice_io._voice_available = None

            with patch.object( sys, "stdin" ) as mock_stdin:
                mock_stdin.isatty.return_value = False
                result = await voice_io.get_input( "Enter feedback:" )
                assert result is None
        finally:
            voice_io._cosa_interface = original_interface
            voice_io._voice_available = original_available


# ============================================================================
# Test 4: choose() non-interactive defaults
# ============================================================================

class TestChooseNonInteractive:
    """
    SUPERSEDED PREMISE, kept deliberately as a record.

    This class used to assert that choose() returning options[0] when nobody
    is there is "deliberate and already gated" — and that framing is why the
    non-interactive path went unexamined while its twin was being fixed. Row
    741011ba ruled the other way: position in a list is not consent on ANY
    path, gated or not. Unattended operation is supported by DECLARING a
    default, not by the function picking one.
    """

    @pytest.mark.asyncio
    async def test_refuses_to_answer_when_non_interactive( self ):
        """choose() must not answer for an absent human, even without blocking."""
        from cosa.agents.utils import voice_io

        original_interface = voice_io._cosa_interface
        original_available = voice_io._voice_available
        try:
            voice_io._cosa_interface = None
            voice_io._voice_available = None

            with patch.object( sys, "stdin" ) as mock_stdin:
                mock_stdin.isatty.return_value = False
                with pytest.raises( voice_io.VoiceGateNoDefaultError ):
                    await voice_io.choose(
                        "Which format?",
                        [ "Option A", "Option B", "Option C" ]
                    )
                # ...and the supported unattended path still works.
                assert await voice_io.choose(
                    "Which format?",
                    [ "Option A", "Option B", "Option C" ],
                    response_default="Option C"
                ) == "Option C"
        finally:
            voice_io._cosa_interface = original_interface
            voice_io._voice_available = original_available

    @pytest.mark.asyncio
    async def test_refuses_with_dict_format_options_too( self ):
        """The refusal is not specific to string-shaped options."""
        from cosa.agents.utils import voice_io

        original_interface = voice_io._cosa_interface
        original_available = voice_io._voice_available
        try:
            voice_io._cosa_interface = None
            voice_io._voice_available = None

            with patch.object( sys, "stdin" ) as mock_stdin:
                mock_stdin.isatty.return_value = False
                with pytest.raises( voice_io.VoiceGateNoDefaultError ):
                    await voice_io.choose(
                        "Which format?",
                        [
                            { "label": "Approve", "description": "Accept as-is" },
                            { "label": "Revise", "description": "Request changes" },
                        ]
                    )
        finally:
            voice_io._cosa_interface = original_interface
            voice_io._voice_available = original_available


# ============================================================================
# Test 5: present_choices() non-interactive defaults
# ============================================================================

class TestPresentChoicesNonInteractive:
    """Verify present_choices returns defaults without blocking."""

    # Behaviour changed 2026-08-01 (row be8830a3). This class previously
    # asserted that a non-interactive present_choices() answers with
    # options[0]. It does not any more: option ORDER is not consent, so a
    # gate with no explicit response_default now raises instead of guessing.
    # The two tests below pin both halves of the replacement contract.

    @pytest.mark.asyncio
    async def test_raises_when_no_explicit_default_given( self ):
        """
        Non-interactive with no response_default must FAIL LOUDLY rather
        than answer on the user's behalf.
        """
        from cosa.agents.utils import voice_io

        original_interface = voice_io._cosa_interface
        original_available = voice_io._voice_available
        try:
            voice_io._cosa_interface = None
            voice_io._voice_available = None

            questions = [
                {
                    "question"    : "Which style?",
                    "header"      : "Style",
                    "multiSelect" : False,
                    "options"     : [
                        { "label": "Casual", "description": "Relaxed tone" },
                        { "label": "Formal", "description": "Professional tone" },
                    ]
                }
            ]

            with patch.object( sys, "stdin" ) as mock_stdin:
                mock_stdin.isatty.return_value = False
                with pytest.raises( voice_io.VoiceGateNoDefaultError ) as exc:
                    await voice_io.present_choices( questions )

                assert exc.value.reason == "non_interactive"
                assert exc.value.headers == [ "Style" ]
        finally:
            voice_io._cosa_interface = original_interface
            voice_io._voice_available = original_available

    @pytest.mark.asyncio
    async def test_explicit_default_is_applied_and_flagged( self ):
        """
        With an explicit response_default the call succeeds, returns the
        caller's chosen values, and marks them as a default so the caller
        can tell this apart from a real selection.
        """
        from cosa.agents.utils import voice_io

        original_interface = voice_io._cosa_interface
        original_available = voice_io._voice_available
        try:
            voice_io._cosa_interface = None
            voice_io._voice_available = None

            questions = [
                {
                    "question"    : "Which style?",
                    "header"      : "Style",
                    "multiSelect" : False,
                    "options"     : [
                        { "label": "Casual", "description": "Relaxed tone" },
                        { "label": "Formal", "description": "Professional tone" },
                    ]
                },
                {
                    "question"    : "Which features?",
                    "header"      : "Features",
                    "multiSelect" : True,
                    "options"     : [
                        { "label": "Intro", "description": "Opening segment" },
                        { "label": "Outro", "description": "Closing segment" },
                    ]
                }
            ]

            # Deliberately NOT option[0] for either question — proves the
            # caller's declaration is what lands, not the list ordering.
            declared = { "Style": "Formal", "Features": [ "Outro" ] }

            with patch.object( sys, "stdin" ) as mock_stdin:
                mock_stdin.isatty.return_value = False
                result = await voice_io.present_choices( questions, response_default=declared )

                assert result[ "answers" ][ "Style" ]    == "Formal"
                assert result[ "answers" ][ "Features" ] == [ "Outro" ]
                assert result[ "default_used" ]   is True
                assert result[ "answered" ]       is False
                assert result[ "default_source" ] == "non_interactive"
        finally:
            voice_io._cosa_interface = original_interface
            voice_io._voice_available = original_available


# ============================================================================
# Test 6: select_themes() / select_topics() non-interactive defaults
# ============================================================================

class TestSelectThemesNonInteractive:
    """Same superseded premise as TestChooseNonInteractive — see its docstring."""

    @pytest.mark.asyncio
    async def test_refuses_rather_than_selecting_all_themes( self ):
        """"Nobody answered" must not silently become "wants every theme"."""
        from cosa.agents.utils import voice_io

        original_interface = voice_io._cosa_interface
        original_available = voice_io._voice_available
        try:
            voice_io._cosa_interface = None
            voice_io._voice_available = None

            themes = [
                { "name": "AI Safety", "description": "Risk mitigation", "subquery_indices": [ 0, 1 ] },
                { "name": "ML Ops", "description": "Infrastructure", "subquery_indices": [ 2, 3, 4 ] },
            ]

            with patch.object( sys, "stdin" ) as mock_stdin:
                mock_stdin.isatty.return_value = False
                with pytest.raises( voice_io.VoiceGateNoDefaultError ):
                    await voice_io.select_themes( themes )
                assert await voice_io.select_themes(
                    themes, response_default=[ 0, 1 ]
                ) == [ 0, 1 ]
        finally:
            voice_io._cosa_interface = original_interface
            voice_io._voice_available = original_available


class TestSelectTopicsNonInteractive:
    """Same superseded premise as TestChooseNonInteractive — see its docstring."""

    @pytest.mark.asyncio
    async def test_refuses_rather_than_selecting_all_topics( self ):
        """This one also spends real search budget per selected topic."""
        from cosa.agents.utils import voice_io

        original_interface = voice_io._cosa_interface
        original_available = voice_io._voice_available
        try:
            voice_io._cosa_interface = None
            voice_io._voice_available = None

            topics = [
                { "topic": "GPT-5 capabilities", "objective": "Compare with GPT-4" },
                { "topic": "Safety benchmarks", "objective": "Evaluate alignment" },
                { "topic": "Deployment patterns", "objective": "Production readiness" },
            ]

            with patch.object( sys, "stdin" ) as mock_stdin:
                mock_stdin.isatty.return_value = False
                with pytest.raises( voice_io.VoiceGateNoDefaultError ):
                    await voice_io.select_topics( topics )
                assert await voice_io.select_topics(
                    topics, response_default=[ 0, 1, 2 ]
                ) == [ 0, 1, 2 ]
        finally:
            voice_io._cosa_interface = original_interface
            voice_io._voice_available = original_available


# ============================================================================
# Test 7: set_job_id() / clear_job_id() auto-injection
# ============================================================================

class TestJobIdAutoInjection:
    """Verify set_job_id() auto-injects into notify() and clear_job_id() resets."""

    def _save_and_clear_state( self, voice_io ):
        """Save module state and reset for clean testing."""
        saved = {
            "interface" : voice_io._cosa_interface,
            "available" : voice_io._voice_available,
            "job_id"    : voice_io._job_id,
            "cli_mode"  : voice_io._force_cli_mode,
        }
        voice_io._cosa_interface = None
        voice_io._voice_available = None
        voice_io._job_id = None
        voice_io._force_cli_mode = False
        return saved

    def _restore_state( self, voice_io, saved ):
        """Restore module state after testing."""
        voice_io._cosa_interface  = saved[ "interface" ]
        voice_io._voice_available = saved[ "available" ]
        voice_io._job_id          = saved[ "job_id" ]
        voice_io._force_cli_mode  = saved[ "cli_mode" ]

    def test_set_job_id_stores_value( self ):
        """set_job_id() stores the job ID in module state."""
        from cosa.agents.utils import voice_io

        saved = self._save_and_clear_state( voice_io )
        try:
            voice_io.set_job_id( "pg-abc12345" )
            assert voice_io._job_id == "pg-abc12345"
        finally:
            self._restore_state( voice_io, saved )

    def test_clear_job_id_resets_to_none( self ):
        """clear_job_id() resets _job_id to None."""
        from cosa.agents.utils import voice_io

        saved = self._save_and_clear_state( voice_io )
        try:
            voice_io.set_job_id( "dr-def67890" )
            assert voice_io._job_id == "dr-def67890"
            voice_io.clear_job_id()
            assert voice_io._job_id is None
        finally:
            self._restore_state( voice_io, saved )

    @pytest.mark.asyncio
    async def test_notify_auto_injects_job_id( self ):
        """notify() auto-injects module-level _job_id when caller omits it."""
        from cosa.agents.utils import voice_io

        saved = self._save_and_clear_state( voice_io )
        try:
            # Set up: mock cosa_interface with voice available
            mock_interface = MagicMock()
            mock_notify = AsyncMock( return_value=None )
            mock_interface.notify_progress = mock_notify

            voice_io._cosa_interface  = mock_interface
            voice_io._voice_available = True
            voice_io.set_job_id( "pg-test1234" )

            # Call notify WITHOUT explicit job_id
            await voice_io.notify( "Test message", priority="low" )

            # Verify auto-injected job_id was passed to cosa_interface
            mock_notify.assert_called_once()
            call_kwargs = mock_notify.call_args[ 1 ]
            assert call_kwargs[ "job_id" ] == "pg-test1234"

        finally:
            self._restore_state( voice_io, saved )

    @pytest.mark.asyncio
    async def test_notify_explicit_job_id_overrides_module_level( self ):
        """Explicit job_id in notify() call overrides module-level _job_id."""
        from cosa.agents.utils import voice_io

        saved = self._save_and_clear_state( voice_io )
        try:
            mock_interface = MagicMock()
            mock_notify = AsyncMock( return_value=None )
            mock_interface.notify_progress = mock_notify

            voice_io._cosa_interface  = mock_interface
            voice_io._voice_available = True
            voice_io.set_job_id( "pg-module-level" )

            # Call notify WITH explicit job_id
            await voice_io.notify( "Test", priority="low", job_id="dr-explicit" )

            mock_notify.assert_called_once()
            call_kwargs = mock_notify.call_args[ 1 ]
            assert call_kwargs[ "job_id" ] == "dr-explicit"

        finally:
            self._restore_state( voice_io, saved )

    @pytest.mark.asyncio
    async def test_notify_no_injection_when_job_id_not_set( self ):
        """notify() passes None for job_id when _job_id is not set."""
        from cosa.agents.utils import voice_io

        saved = self._save_and_clear_state( voice_io )
        try:
            mock_interface = MagicMock()
            mock_notify = AsyncMock( return_value=None )
            mock_interface.notify_progress = mock_notify

            voice_io._cosa_interface  = mock_interface
            voice_io._voice_available = True
            # Do NOT call set_job_id — _job_id stays None

            await voice_io.notify( "Test", priority="low" )

            mock_notify.assert_called_once()
            call_kwargs = mock_notify.call_args[ 1 ]
            assert call_kwargs[ "job_id" ] is None

        finally:
            self._restore_state( voice_io, saved )

    def test_configure_accepts_job_id( self ):
        """configure() accepts optional job_id parameter."""
        from cosa.agents.utils import voice_io

        saved = self._save_and_clear_state( voice_io )
        try:
            mock_interface = MagicMock()
            mock_interface.__name__ = "mock_cosa_interface"

            voice_io.configure( mock_interface, job_id="pg-via-configure" )
            assert voice_io._job_id == "pg-via-configure"

        finally:
            self._restore_state( voice_io, saved )

    def test_configure_without_job_id_preserves_existing( self ):
        """configure() without job_id does not clear existing _job_id."""
        from cosa.agents.utils import voice_io

        saved = self._save_and_clear_state( voice_io )
        try:
            voice_io._job_id = "pg-existing"

            mock_interface = MagicMock()
            mock_interface.__name__ = "mock_cosa_interface"

            voice_io.configure( mock_interface )
            assert voice_io._job_id == "pg-existing"

        finally:
            self._restore_state( voice_io, saved )


if __name__ == "__main__":
    pytest.main( [ __file__, "-v" ] )
