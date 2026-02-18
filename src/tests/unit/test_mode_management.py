"""
Unit tests for agent mode management — including agentic mode switches.

Tests the MODE_TO_AGENT, AGENTIC_MODE_MAP, MODE_METADATA module-level dicts
and the set_user_mode(), get_user_mode(), clear_user_mode(), and
get_available_modes() methods on TodoFifoQueue.

Validates that:
  - All 7 agent-base modes are accepted
  - All 5 agentic modes are accepted
  - Invalid modes are rejected with ValueError
  - AGENTIC_MODE_MAP values are valid AGENTIC_AGENTS keys
  - get_available_modes() returns all 13 entries (system + 7 agents + 5 agentic)
  - MODE_METADATA has entries for every mode key plus "system"
"""

import pytest
from unittest.mock import MagicMock

from cosa.rest.todo_fifo_queue import (
    TodoFifoQueue,
    MODE_TO_AGENT,
    AGENTIC_MODE_MAP,
    MODE_METADATA,
)
from cosa.agents.runtime_argument_expeditor.agent_registry import AGENTIC_AGENTS


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def queue():
    """
    Lightweight TodoFifoQueue with heavy deps stubbed out.

    Requires:
        - None

    Ensures:
        - Returns a real TodoFifoQueue instance with mode methods functional
    """
    q       = MagicMock( spec=TodoFifoQueue )
    q.debug = True

    # Wire up real mode state and methods
    q.user_mode_state = {}
    q.get_user_mode   = TodoFifoQueue.get_user_mode.__get__( q )
    q.set_user_mode   = TodoFifoQueue.set_user_mode.__get__( q )
    q.clear_user_mode = TodoFifoQueue.clear_user_mode.__get__( q )
    q.get_available_modes = TodoFifoQueue.get_available_modes.__get__( q )

    return q


# ---------------------------------------------------------------------------
# Module-level dict consistency tests
# ---------------------------------------------------------------------------

class TestModuleDicts:
    """Tests for MODE_TO_AGENT, AGENTIC_MODE_MAP, and MODE_METADATA consistency."""

    def test_agentic_mode_map_values_are_valid_agentic_agents( self ):
        """Every AGENTIC_MODE_MAP value must be a key in AGENTIC_AGENTS."""
        for mode_key, command in AGENTIC_MODE_MAP.items():
            assert command in AGENTIC_AGENTS, (
                f"AGENTIC_MODE_MAP['{mode_key}'] = '{command}' is not a valid AGENTIC_AGENTS key"
            )

    def test_agentic_mode_map_has_five_entries( self ):
        """AGENTIC_MODE_MAP should have exactly 5 entries (one per agentic agent)."""
        assert len( AGENTIC_MODE_MAP ) == 5

    def test_mode_to_agent_has_seven_entries( self ):
        """MODE_TO_AGENT should have exactly 7 entries (the original agent-base agents)."""
        assert len( MODE_TO_AGENT ) == 7

    def test_no_overlap_between_agent_and_agentic_modes( self ):
        """MODE_TO_AGENT and AGENTIC_MODE_MAP must not share any keys."""
        overlap = set( MODE_TO_AGENT.keys() ) & set( AGENTIC_MODE_MAP.keys() )
        assert len( overlap ) == 0, f"Overlapping keys: {overlap}"

    def test_mode_metadata_covers_all_modes_plus_system( self ):
        """MODE_METADATA must have entries for system + all agent + all agentic modes."""
        expected_keys = { "system" } | set( MODE_TO_AGENT.keys() ) | set( AGENTIC_MODE_MAP.keys() )
        actual_keys   = set( MODE_METADATA.keys() )
        assert expected_keys == actual_keys, (
            f"Missing: {expected_keys - actual_keys}, Extra: {actual_keys - expected_keys}"
        )

    def test_mode_metadata_has_thirteen_entries( self ):
        """MODE_METADATA should have 13 entries: 1 system + 7 agent + 5 agentic."""
        assert len( MODE_METADATA ) == 13

    def test_mode_metadata_entries_have_required_fields( self ):
        """Every MODE_METADATA entry must have display_name and description."""
        for key, meta in MODE_METADATA.items():
            assert "display_name" in meta, f"MODE_METADATA['{key}'] missing 'display_name'"
            assert "description" in meta, f"MODE_METADATA['{key}'] missing 'description'"

    def test_agentic_mode_map_specific_keys( self ):
        """Verify the specific 5 agentic mode keys."""
        expected = { "deep_research", "podcast", "research_to_podcast", "claude_code", "swe_team" }
        assert set( AGENTIC_MODE_MAP.keys() ) == expected


# ---------------------------------------------------------------------------
# set_user_mode() tests
# ---------------------------------------------------------------------------

class TestSetUserMode:
    """Tests for set_user_mode() validation."""

    def test_accepts_agent_base_modes( self, queue ):
        """set_user_mode() should accept all MODE_TO_AGENT keys."""
        for mode in MODE_TO_AGENT.keys():
            queue.set_user_mode( "user1", mode )
            assert queue.get_user_mode( "user1" ) == mode

    def test_accepts_agentic_modes( self, queue ):
        """set_user_mode() should accept all AGENTIC_MODE_MAP keys."""
        for mode in AGENTIC_MODE_MAP.keys():
            queue.set_user_mode( "user1", mode )
            assert queue.get_user_mode( "user1" ) == mode

    def test_accepts_none_for_system( self, queue ):
        """set_user_mode( None ) should clear mode to system."""
        queue.set_user_mode( "user1", "math" )
        queue.set_user_mode( "user1", None )
        assert queue.get_user_mode( "user1" ) is None

    def test_rejects_invalid_mode( self, queue ):
        """set_user_mode() should raise ValueError for unknown mode keys."""
        with pytest.raises( ValueError, match="Invalid mode" ):
            queue.set_user_mode( "user1", "nonexistent_mode" )

    def test_rejects_empty_string_mode( self, queue ):
        """set_user_mode() should raise ValueError for empty string."""
        with pytest.raises( ValueError, match="Invalid mode" ):
            queue.set_user_mode( "user1", "" )

    def test_returns_previous_mode( self, queue ):
        """set_user_mode() should return the previous mode."""
        assert queue.set_user_mode( "user1", "math" ) is None
        assert queue.set_user_mode( "user1", "swe_team" ) == "math"
        assert queue.set_user_mode( "user1", None ) == "swe_team"

    def test_error_message_includes_all_valid_modes( self, queue ):
        """ValueError message should list both agent-base and agentic modes."""
        with pytest.raises( ValueError ) as exc_info:
            queue.set_user_mode( "user1", "bogus" )
        error_msg = str( exc_info.value )
        # Should include at least one agent-base and one agentic mode
        assert "math" in error_msg
        assert "swe_team" in error_msg


# ---------------------------------------------------------------------------
# get_available_modes() tests
# ---------------------------------------------------------------------------

class TestGetAvailableModes:
    """Tests for get_available_modes()."""

    def test_returns_thirteen_modes( self, queue ):
        """get_available_modes() should return 13 mode dicts."""
        modes = queue.get_available_modes()
        assert len( modes ) == 13

    def test_system_mode_is_present( self, queue ):
        """System mode must be in the returned list."""
        modes = queue.get_available_modes()
        keys  = [ m[ "key" ] for m in modes ]
        assert "system" in keys

    def test_all_agent_base_modes_present( self, queue ):
        """All 7 agent-base mode keys should be in the returned list."""
        modes = queue.get_available_modes()
        keys  = set( m[ "key" ] for m in modes )
        for agent_key in MODE_TO_AGENT.keys():
            assert agent_key in keys, f"Agent mode '{agent_key}' missing from available modes"

    def test_all_agentic_modes_present( self, queue ):
        """All 5 agentic mode keys should be in the returned list."""
        modes = queue.get_available_modes()
        keys  = set( m[ "key" ] for m in modes )
        for agentic_key in AGENTIC_MODE_MAP.keys():
            assert agentic_key in keys, f"Agentic mode '{agentic_key}' missing from available modes"

    def test_mode_dicts_have_required_keys( self, queue ):
        """Each mode dict should have key, display_name, and description."""
        modes = queue.get_available_modes()
        for mode in modes:
            assert "key" in mode, f"Mode dict missing 'key': {mode}"
            assert "display_name" in mode, f"Mode dict missing 'display_name': {mode}"
            assert "description" in mode, f"Mode dict missing 'description': {mode}"


# ---------------------------------------------------------------------------
# clear_user_mode() tests
# ---------------------------------------------------------------------------

class TestClearUserMode:
    """Tests for clear_user_mode()."""

    def test_clear_returns_previous_agentic_mode( self, queue ):
        """clear_user_mode() should return the previous agentic mode."""
        queue.set_user_mode( "user1", "deep_research" )
        previous = queue.clear_user_mode( "user1" )
        assert previous == "deep_research"
        assert queue.get_user_mode( "user1" ) is None

    def test_clear_when_no_mode_set( self, queue ):
        """clear_user_mode() should return None if no mode was set."""
        previous = queue.clear_user_mode( "user1" )
        assert previous is None


# ---------------------------------------------------------------------------
# AGENTIC_MODE_MAP command mapping tests
# ---------------------------------------------------------------------------

class TestAgenticModeMapping:
    """Tests for specific AGENTIC_MODE_MAP command values."""

    def test_deep_research_maps_correctly( self ):
        assert AGENTIC_MODE_MAP[ "deep_research" ] == "agent router go to deep research"

    def test_podcast_maps_correctly( self ):
        assert AGENTIC_MODE_MAP[ "podcast" ] == "agent router go to podcast generator"

    def test_research_to_podcast_maps_correctly( self ):
        assert AGENTIC_MODE_MAP[ "research_to_podcast" ] == "agent router go to research to podcast"

    def test_claude_code_maps_correctly( self ):
        assert AGENTIC_MODE_MAP[ "claude_code" ] == "agent router go to claude code"

    def test_swe_team_maps_correctly( self ):
        assert AGENTIC_MODE_MAP[ "swe_team" ] == "agent router go to swe team"
