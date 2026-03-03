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
from unittest.mock import patch, MagicMock

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
    """Verify choose returns first option without blocking in non-interactive mode."""

    @pytest.mark.asyncio
    async def test_returns_first_option_when_non_interactive( self ):
        """choose() returns first option label in non-interactive mode."""
        from cosa.agents.utils import voice_io

        original_interface = voice_io._cosa_interface
        original_available = voice_io._voice_available
        try:
            voice_io._cosa_interface = None
            voice_io._voice_available = None

            with patch.object( sys, "stdin" ) as mock_stdin:
                mock_stdin.isatty.return_value = False
                result = await voice_io.choose(
                    "Which format?",
                    [ "Option A", "Option B", "Option C" ]
                )
                assert result == "Option A"
        finally:
            voice_io._cosa_interface = original_interface
            voice_io._voice_available = original_available

    @pytest.mark.asyncio
    async def test_returns_first_option_dict_format( self ):
        """choose() handles dict-format options in non-interactive mode."""
        from cosa.agents.utils import voice_io

        original_interface = voice_io._cosa_interface
        original_available = voice_io._voice_available
        try:
            voice_io._cosa_interface = None
            voice_io._voice_available = None

            with patch.object( sys, "stdin" ) as mock_stdin:
                mock_stdin.isatty.return_value = False
                result = await voice_io.choose(
                    "Which format?",
                    [
                        { "label": "Approve", "description": "Accept as-is" },
                        { "label": "Revise", "description": "Request changes" },
                    ]
                )
                assert result == "Approve"
        finally:
            voice_io._cosa_interface = original_interface
            voice_io._voice_available = original_available


# ============================================================================
# Test 5: present_choices() non-interactive defaults
# ============================================================================

class TestPresentChoicesNonInteractive:
    """Verify present_choices returns defaults without blocking."""

    @pytest.mark.asyncio
    async def test_returns_first_option_per_question( self ):
        """present_choices() returns first option for each question."""
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

            with patch.object( sys, "stdin" ) as mock_stdin:
                mock_stdin.isatty.return_value = False
                result = await voice_io.present_choices( questions )

                assert "answers" in result
                assert result[ "answers" ][ "Style" ] == "Casual"
                assert result[ "answers" ][ "Features" ] == [ "Intro" ]
        finally:
            voice_io._cosa_interface = original_interface
            voice_io._voice_available = original_available


# ============================================================================
# Test 6: select_themes() / select_topics() non-interactive defaults
# ============================================================================

class TestSelectThemesNonInteractive:
    """Verify select_themes selects all in non-interactive mode."""

    @pytest.mark.asyncio
    async def test_selects_all_themes_when_non_interactive( self ):
        """select_themes() returns all indices in non-interactive mode."""
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
                result = await voice_io.select_themes( themes )
                assert result == [ 0, 1 ]
        finally:
            voice_io._cosa_interface = original_interface
            voice_io._voice_available = original_available


class TestSelectTopicsNonInteractive:
    """Verify select_topics selects all in non-interactive mode."""

    @pytest.mark.asyncio
    async def test_selects_all_topics_when_non_interactive( self ):
        """select_topics() returns all indices in non-interactive mode."""
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
                result = await voice_io.select_topics( topics )
                assert result == [ 0, 1, 2 ]
        finally:
            voice_io._cosa_interface = original_interface
            voice_io._voice_available = original_available


if __name__ == "__main__":
    pytest.main( [ __file__, "-v" ] )
