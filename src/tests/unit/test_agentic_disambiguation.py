"""
Unit tests for the agentic command disambiguation confirmation loop.

Tests the _confirm_agentic_routing() method in TodoFifoQueue, which presents
the user with a multiple-choice voice prompt to confirm (or switch) the
detected agentic command before routing to the RuntimeArgumentExpeditor.

Pattern: Follows test_runtime_argument_expeditor.py — mock notify_user_sync(),
test all response paths.
"""

import json
import pytest
from unittest.mock import MagicMock, patch

from lupin_cli.notifications.notification_models import NotificationResponse
from cosa.rest.todo_fifo_queue import TodoFifoQueue, MODE_METADATA
from cosa.agents.runtime_argument_expeditor.agent_registry import AGENTIC_AGENTS


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_queue():
    """
    Lightweight mock of TodoFifoQueue — avoids heavy __init__ (ConfigurationManager, etc.).

    Requires:
        - None

    Ensures:
        - Returns MagicMock with .debug and .PRODUCT_NAMES bound
        - _confirm_agentic_routing is the real unbound method
    """
    queue       = MagicMock()
    queue.debug = True
    queue.PRODUCT_NAMES = TodoFifoQueue.PRODUCT_NAMES
    # Bind the real method to our mock instance
    queue._confirm_agentic_routing = TodoFifoQueue._confirm_agentic_routing.__get__( queue )
    return queue


def _make_response( response_value=None, exit_code=0, status="responded", is_timeout=False ):
    """
    Helper to build a NotificationResponse with sensible defaults.

    Requires:
        - exit_code in {0, 1, 2}

    Ensures:
        - Returns a valid NotificationResponse instance
    """
    return NotificationResponse(
        response_value = response_value,
        exit_code      = exit_code,
        status         = status,
        is_timeout     = is_timeout,
    )


# ---------------------------------------------------------------------------
# Test class: Product name mapping integrity
# ---------------------------------------------------------------------------

class TestProductNameMapping:
    """Verify the PRODUCT_NAMES class variable is consistent with AGENTIC_AGENTS."""

    def test_all_agentic_agents_have_product_names( self ):
        """Every key in AGENTIC_AGENTS has a corresponding PRODUCT_NAMES entry."""
        for key in AGENTIC_AGENTS:
            assert key in TodoFifoQueue.PRODUCT_NAMES, (
                f"AGENTIC_AGENTS key '{key}' has no PRODUCT_NAMES entry"
            )

    def test_product_names_are_unique( self ):
        """No two agentic commands share the same product name."""
        names  = list( TodoFifoQueue.PRODUCT_NAMES.values() )
        unique = set( names )
        assert len( names ) == len( unique ), (
            f"Duplicate product names detected: {names}"
        )

    def test_product_names_contain_descriptions( self ):
        """Each product name contains a parenthetical description."""
        for cmd, name in TodoFifoQueue.PRODUCT_NAMES.items():
            assert "(" in name and ")" in name, (
                f"Product name for '{cmd}' missing parenthetical description: '{name}'"
            )

    def test_podcast_labels_match_agent_behavior( self ):
        """
        Guard against the label INVERSION fixed in bug fc8990c6 (demo 2026-08-06).

        Behavioral contract (from each job's constructor):
          - `podcast generator` -> PodcastGeneratorJob( research_path=... ): READS an
            existing document. Its label must say so, never "from a topic".
          - `research to podcast` -> DeepResearchToPodcastJob( query=... ): RESEARCHES
            a topic from scratch, no file input. Its label must say so, never "document".

        If the two labels swap, the agentic confirm step steers the user to the wrong
        podcast agent — the exact defect this test exists to keep dead.
        """
        file_reader = TodoFifoQueue.PRODUCT_NAMES[ "agent router go to podcast generator" ].lower()
        scratch     = TodoFifoQueue.PRODUCT_NAMES[ "agent router go to research to podcast" ].lower()

        assert "document" in file_reader, (
            f"podcast-generator (the file reader) label lost its 'document' anchor: '{file_reader}'"
        )
        assert "document" not in scratch, (
            f"research-to-podcast (the scratch researcher) label wrongly claims a 'document': '{scratch}'"
        )
        assert "topic" in scratch, (
            f"research-to-podcast (the scratch researcher) label lost its 'topic' anchor: '{scratch}'"
        )
        assert "topic" not in file_reader, (
            f"podcast-generator (the file reader) label wrongly claims a 'topic': '{file_reader}'"
        )

    def test_podcast_mode_descriptions_match_agent_behavior( self ):
        """
        Sibling guard to test_podcast_labels_match_agent_behavior, for the MODE_METADATA
        dropdown descriptions (off the pure-voice path, but the same inversion could recur).

        Same behavioral contract:
          - mode "podcast" -> PodcastGeneratorJob (research_path): READS a document.
          - mode "research_to_podcast" -> DeepResearchToPodcastJob (query): RESEARCHES a topic.
        """
        file_reader = MODE_METADATA[ "podcast" ][ "description" ].lower()
        scratch     = MODE_METADATA[ "research_to_podcast" ][ "description" ].lower()

        assert "document" in file_reader, (
            f"'podcast' mode desc (file reader) lost its 'document' anchor: '{file_reader}'"
        )
        assert "document" not in scratch, (
            f"'research_to_podcast' mode desc (scratch) wrongly claims a 'document': '{scratch}'"
        )
        assert "topic" in scratch, (
            f"'research_to_podcast' mode desc (scratch) lost its 'topic' anchor: '{scratch}'"
        )
        assert "topic" not in file_reader, (
            f"'podcast' mode desc (file reader) wrongly claims a 'topic': '{file_reader}'"
        )


# ---------------------------------------------------------------------------
# Test class: _confirm_agentic_routing() response handling
# ---------------------------------------------------------------------------

class TestConfirmAgenticRouting:
    """Test all response paths through _confirm_agentic_routing()."""

    DEEP_RESEARCH = "agent router go to deep research"
    PODCAST_GEN   = "agent router go to podcast generator"
    RES_TO_POD    = "agent router go to research to podcast"

    @patch( "cosa.rest.todo_fifo_queue.notify_user_sync" )
    def test_confirm_detected_command( self, mock_notify, mock_queue ):
        """User confirms the detected command → returns same command."""
        detected_name = TodoFifoQueue.PRODUCT_NAMES[ self.DEEP_RESEARCH ]
        mock_notify.return_value = _make_response( response_value=detected_name )

        result = mock_queue._confirm_agentic_routing(
            self.DEEP_RESEARCH, "", "user1", "user@test.com", "do a deep dive"
        )

        assert result == self.DEEP_RESEARCH
        mock_notify.assert_called_once()

    @patch( "cosa.rest.todo_fifo_queue.notify_user_sync" )
    def test_switch_to_alternative( self, mock_notify, mock_queue ):
        """User picks a different product name → returns that command."""
        # Detected: deep research, but user switches to podcast generator
        alt_name = TodoFifoQueue.PRODUCT_NAMES[ self.PODCAST_GEN ]
        mock_notify.return_value = _make_response( response_value=alt_name )

        result = mock_queue._confirm_agentic_routing(
            self.DEEP_RESEARCH, "", "user1", "user@test.com", "make something"
        )

        assert result == self.PODCAST_GEN

    @patch( "cosa.rest.todo_fifo_queue.notify_user_sync" )
    def test_cancel_returns_none( self, mock_notify, mock_queue ):
        """User picks 'Cancel' → returns None."""
        mock_notify.return_value = _make_response( response_value="Cancel" )

        result = mock_queue._confirm_agentic_routing(
            self.DEEP_RESEARCH, "", "user1", "user@test.com", "something"
        )

        assert result is None

    @patch( "cosa.rest.todo_fifo_queue.notify_user_sync" )
    def test_timeout_aborts_returns_none( self, mock_notify, mock_queue ):
        """
        Timeout → ABORTS (None), row cad45cf1.

        This used to assert the detected command came back, on the reasoning
        that proceeding was the safe default. It is not: silence is not a
        confirmation, and detection is the very thing this gate exists to
        doubt. fc4ccfe6 measured a whole class of sentences that route wrong,
        so proceeding on silence lands the wrong agent and looks like it worked.
        """
        mock_notify.return_value = _make_response(
            exit_code=2, status="expired", is_timeout=True
        )

        result = mock_queue._confirm_agentic_routing(
            self.PODCAST_GEN, "", "user1", "user@test.com", "create a podcast"
        )

        assert result is None

    @patch( "cosa.rest.todo_fifo_queue.notify_user_sync" )
    def test_error_aborts_returns_none( self, mock_notify, mock_queue ):
        """
        Notification error → ABORTS (None), row cad45cf1.

        A failed notification is not a confirmation either — nobody was asked,
        so nothing was answered.
        """
        mock_notify.return_value = _make_response(
            exit_code=1, status="connection_error"
        )

        result = mock_queue._confirm_agentic_routing(
            self.RES_TO_POD, "", "user1", "user@test.com", "convert research"
        )

        assert result is None

    @patch( "cosa.rest.todo_fifo_queue.notify_user_sync" )
    def test_json_response_format( self, mock_notify, mock_queue ):
        """Response in JSON format {"answers": {"Command": "..."}} → parses correctly."""
        detected_name = TodoFifoQueue.PRODUCT_NAMES[ self.RES_TO_POD ]
        json_response = json.dumps( { "answers": { "Command": detected_name } } )
        mock_notify.return_value = _make_response( response_value=json_response )

        result = mock_queue._confirm_agentic_routing(
            self.RES_TO_POD, "", "user1", "user@test.com", "doc to pod"
        )

        assert result == self.RES_TO_POD

    @patch( "cosa.rest.todo_fifo_queue.notify_user_sync" )
    def test_none_response_returns_none( self, mock_notify, mock_queue ):
        """response_value=None → returns None (treated as cancel)."""
        mock_notify.return_value = _make_response( response_value=None )

        result = mock_queue._confirm_agentic_routing(
            self.DEEP_RESEARCH, "", "user1", "user@test.com", "something"
        )

        assert result is None

    @patch( "cosa.rest.todo_fifo_queue.notify_user_sync" )
    def test_unknown_response_returns_original( self, mock_notify, mock_queue ):
        """Unrecognized string response → fallback to original command."""
        mock_notify.return_value = _make_response( response_value="some random text" )

        result = mock_queue._confirm_agentic_routing(
            self.PODCAST_GEN, "", "user1", "user@test.com", "something"
        )

        assert result == self.PODCAST_GEN

    @patch( "cosa.rest.todo_fifo_queue.notify_user_sync" )
    def test_options_detected_first( self, mock_notify, mock_queue ):
        """Detected command is always the FIRST option in the list, regardless of PRODUCT_NAMES order."""
        # Use podcast_generator (NOT deep_research which is naturally first in dict)
        detected_name = TodoFifoQueue.PRODUCT_NAMES[ self.PODCAST_GEN ]
        mock_notify.return_value = _make_response( response_value=detected_name )

        mock_queue._confirm_agentic_routing(
            self.PODCAST_GEN, "", "user1", "user@test.com", "podcast"
        )

        # Inspect the NotificationRequest passed to notify_user_sync
        call_args = mock_notify.call_args
        request   = call_args[ 0 ][ 0 ] if call_args[ 0 ] else call_args[ 1 ][ "request" ]

        # Extract options from response_options
        options = request.response_options[ "questions" ][ 0 ][ "options" ]

        # First option must be the detected command
        assert options[ 0 ][ "label" ] == detected_name, (
            f"Expected first option to be '{detected_name}', got '{options[ 0 ][ 'label' ]}'"
        )
        assert options[ 0 ][ "description" ] == "This is what I detected"

        # Last option must be Cancel
        assert options[ -1 ][ "label" ] == "Cancel"

        # Detected command should NOT appear again in alternatives
        alternative_labels = [ opt[ "label" ] for opt in options[ 1:-1 ] ]
        assert detected_name not in alternative_labels, (
            f"Detected command '{detected_name}' should not appear in alternatives"
        )

    @patch( "cosa.rest.todo_fifo_queue.notify_user_sync" )
    def test_json_response_keyed_by_index( self, mock_notify, mock_queue ):
        """Response as {"answers": {"0": "PodMaker ..."}} (index key) → parses correctly."""
        alt_name = TodoFifoQueue.PRODUCT_NAMES[ self.RES_TO_POD ]
        json_response = json.dumps( { "answers": { "0": alt_name } } )
        mock_notify.return_value = _make_response( response_value=json_response )

        result = mock_queue._confirm_agentic_routing(
            self.DEEP_RESEARCH, "", "user1", "user@test.com", "convert something"
        )

        assert result == self.RES_TO_POD

    @patch( "cosa.rest.todo_fifo_queue.notify_user_sync" )
    def test_malformed_json_falls_through( self, mock_notify, mock_queue ):
        """Malformed JSON string starting with '{' → treated as raw string, fallback to original."""
        mock_notify.return_value = _make_response( response_value="{not valid json" )

        result = mock_queue._confirm_agentic_routing(
            self.DEEP_RESEARCH, "", "user1", "user@test.com", "something"
        )

        # Malformed JSON can't be parsed → raw string doesn't match any product name → fallback
        assert result == self.DEEP_RESEARCH

    @patch( "cosa.rest.todo_fifo_queue.notify_user_sync" )
    def test_all_three_commands_route_correctly( self, mock_notify, mock_queue ):
        """Each of the 3 agentic commands can be confirmed individually."""
        for command in [ self.DEEP_RESEARCH, self.PODCAST_GEN, self.RES_TO_POD ]:
            name = TodoFifoQueue.PRODUCT_NAMES[ command ]
            mock_notify.return_value = _make_response( response_value=name )

            result = mock_queue._confirm_agentic_routing(
                command, "", "user1", "user@test.com", "test"
            )

            assert result == command, f"Expected '{command}', got '{result}'"
