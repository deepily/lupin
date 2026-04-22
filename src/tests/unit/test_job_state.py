"""
Unit Tests for JobState Enum and Transition Validation.

Tests the unified job state machine: enum values, string serialization,
valid/invalid transitions, terminal states, convenience sets, and UI
container mapping.
"""

import pytest
from cosa.rest.job_state import (
    JobState,
    VALID_TRANSITIONS,
    TERMINAL_STATES,
    PRE_EXECUTION_STATES,
    ACTIVE_STATES,
    RESUMABLE_STATES,
    STATE_TO_UI_CONTAINER,
    validate_transition,
    assert_valid_transition,
)


# ---------------------------------------------------------------------------
# Enum basics
# ---------------------------------------------------------------------------

class TestJobStateEnum:
    """Test JobState enum values and string behavior."""

    def test_enum_has_ten_members( self ):
        assert len( JobState ) == 10

    def test_all_expected_values_present( self ):
        expected = {
            "pending", "queued", "scheduled", "paused", "running",
            "completed", "failed", "interrupted", "cancelled", "stalled",
        }
        actual = { s.value for s in JobState }
        assert actual == expected

    def test_string_equality( self ):
        """JobState inherits from str, so enum members equal their string values."""
        assert JobState.PENDING == "pending"
        assert JobState.RUNNING == "running"
        assert JobState.COMPLETED == "completed"

    def test_round_trip_from_string( self ):
        """Can construct JobState from its string value."""
        for state in JobState:
            assert JobState( state.value ) is state

    def test_invalid_string_raises_value_error( self ):
        with pytest.raises( ValueError ):
            JobState( "nonexistent" )

    def test_json_serializable( self ):
        """str(JobState.X) produces the bare value string."""
        import json
        payload = { "state": JobState.COMPLETED }
        result  = json.dumps( payload )
        assert '"completed"' in result


# ---------------------------------------------------------------------------
# Transition matrix
# ---------------------------------------------------------------------------

class TestTransitionMatrix:
    """Test VALID_TRANSITIONS dict covers all states."""

    def test_every_state_has_transition_entry( self ):
        for state in JobState:
            assert state in VALID_TRANSITIONS, f"Missing transition entry for {state}"

    def test_terminal_states_have_empty_transitions( self ):
        for state in TERMINAL_STATES:
            assert VALID_TRANSITIONS[ state ] == frozenset(), (
                f"Terminal state {state} should have no outgoing transitions"
            )

    def test_non_terminal_states_have_at_least_one_transition( self ):
        for state in JobState:
            if state not in TERMINAL_STATES:
                assert len( VALID_TRANSITIONS[ state ] ) > 0, (
                    f"Non-terminal state {state} must have at least one valid transition"
                )


# ---------------------------------------------------------------------------
# Valid transitions
# ---------------------------------------------------------------------------

class TestValidTransitions:
    """Test each valid transition returns True."""

    @pytest.mark.parametrize( "from_state,to_state", [
        # PENDING exits
        ( JobState.PENDING, JobState.QUEUED ),
        ( JobState.PENDING, JobState.SCHEDULED ),
        ( JobState.PENDING, JobState.PAUSED ),
        # QUEUED exits
        ( JobState.QUEUED, JobState.RUNNING ),
        ( JobState.QUEUED, JobState.PAUSED ),
        ( JobState.QUEUED, JobState.SCHEDULED ),
        ( JobState.QUEUED, JobState.CANCELLED ),
        # SCHEDULED exits
        ( JobState.SCHEDULED, JobState.QUEUED ),
        ( JobState.SCHEDULED, JobState.PAUSED ),
        ( JobState.SCHEDULED, JobState.CANCELLED ),
        # PAUSED exits
        ( JobState.PAUSED, JobState.QUEUED ),
        ( JobState.PAUSED, JobState.SCHEDULED ),
        ( JobState.PAUSED, JobState.CANCELLED ),
        # RUNNING exits
        ( JobState.RUNNING, JobState.COMPLETED ),
        ( JobState.RUNNING, JobState.FAILED ),
        ( JobState.RUNNING, JobState.CANCELLED ),
        ( JobState.RUNNING, JobState.INTERRUPTED ),
        ( JobState.RUNNING, JobState.STALLED ),
        # STALLED exits
        ( JobState.STALLED, JobState.RUNNING ),
        ( JobState.STALLED, JobState.CANCELLED ),
    ] )
    def test_valid_transition( self, from_state, to_state ):
        assert validate_transition( from_state, to_state ) is True

    @pytest.mark.parametrize( "from_state,to_state", [
        # PENDING exits
        ( "pending", "queued" ),
        ( "running", "completed" ),
        ( "queued", "running" ),
    ] )
    def test_valid_transition_from_strings( self, from_state, to_state ):
        """validate_transition accepts bare strings as well as enum members."""
        assert validate_transition( from_state, to_state ) is True


# ---------------------------------------------------------------------------
# Invalid transitions
# ---------------------------------------------------------------------------

class TestInvalidTransitions:
    """Test that forbidden transitions are rejected."""

    @pytest.mark.parametrize( "from_state,to_state", [
        # Can't skip to RUNNING from PENDING
        ( JobState.PENDING, JobState.RUNNING ),
        # Can't go back to PENDING from anywhere
        ( JobState.QUEUED, JobState.PENDING ),
        ( JobState.RUNNING, JobState.PENDING ),
        # Terminal states have no outgoing transitions
        ( JobState.COMPLETED, JobState.RUNNING ),
        ( JobState.FAILED, JobState.RUNNING ),
        ( JobState.CANCELLED, JobState.QUEUED ),
        ( JobState.INTERRUPTED, JobState.QUEUED ),
        # Can't go from COMPLETED to FAILED
        ( JobState.COMPLETED, JobState.FAILED ),
        # STALLED cannot go directly to COMPLETED or FAILED (must go through RUNNING first)
        ( JobState.STALLED, JobState.COMPLETED ),
        ( JobState.STALLED, JobState.FAILED ),
        # Self-transitions are not in the matrix
        ( JobState.RUNNING, JobState.RUNNING ),
        ( JobState.QUEUED, JobState.QUEUED ),
    ] )
    def test_invalid_transition( self, from_state, to_state ):
        assert validate_transition( from_state, to_state ) is False

    def test_assert_raises_on_invalid_transition( self ):
        with pytest.raises( ValueError, match="Invalid job state transition" ):
            assert_valid_transition( JobState.COMPLETED, JobState.RUNNING )

    def test_assert_error_message_lists_valid_targets( self ):
        with pytest.raises( ValueError, match="terminal" ):
            assert_valid_transition( JobState.COMPLETED, JobState.RUNNING )

    def test_assert_succeeds_on_valid_transition( self ):
        """assert_valid_transition returns None (no exception) for valid transitions."""
        result = assert_valid_transition( JobState.PENDING, JobState.QUEUED )
        assert result is None


# ---------------------------------------------------------------------------
# Convenience sets
# ---------------------------------------------------------------------------

class TestConvenienceSets:
    """Test TERMINAL_STATES, PRE_EXECUTION_STATES, ACTIVE_STATES."""

    def test_terminal_states( self ):
        assert TERMINAL_STATES == frozenset( {
            JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED, JobState.INTERRUPTED
        } )

    def test_pre_execution_states( self ):
        assert PRE_EXECUTION_STATES == frozenset( {
            JobState.PENDING, JobState.QUEUED, JobState.SCHEDULED, JobState.PAUSED
        } )

    def test_active_states( self ):
        assert ACTIVE_STATES == frozenset( { JobState.RUNNING } )

    def test_resumable_states( self ):
        assert RESUMABLE_STATES == frozenset( { JobState.STALLED } )

    def test_stalled_is_not_terminal( self ):
        assert JobState.STALLED not in TERMINAL_STATES

    def test_sets_are_exhaustive( self ):
        """Every JobState member belongs to exactly one convenience set."""
        all_sets = TERMINAL_STATES | PRE_EXECUTION_STATES | ACTIVE_STATES | RESUMABLE_STATES
        assert all_sets == frozenset( JobState )

    def test_sets_are_disjoint( self ):
        """No state belongs to more than one convenience set."""
        all_groups = [ TERMINAL_STATES, PRE_EXECUTION_STATES, ACTIVE_STATES, RESUMABLE_STATES ]
        for i, a in enumerate( all_groups ):
            for b in all_groups[ i + 1: ]:
                assert a & b == frozenset(), f"Sets {a} and {b} overlap"


# ---------------------------------------------------------------------------
# UI container mapping
# ---------------------------------------------------------------------------

class TestUIContainerMapping:
    """Test STATE_TO_UI_CONTAINER mapping."""

    def test_every_state_has_container( self ):
        for state in JobState:
            assert state in STATE_TO_UI_CONTAINER, f"Missing UI container for {state}"

    def test_pre_execution_states_map_to_todo( self ):
        for state in PRE_EXECUTION_STATES:
            assert STATE_TO_UI_CONTAINER[ state ] == "todo"

    def test_running_maps_to_run( self ):
        assert STATE_TO_UI_CONTAINER[ JobState.RUNNING ] == "run"

    def test_completed_maps_to_done( self ):
        assert STATE_TO_UI_CONTAINER[ JobState.COMPLETED ] == "done"

    def test_failure_states_map_to_dead( self ):
        for state in ( JobState.FAILED, JobState.CANCELLED, JobState.INTERRUPTED ):
            assert STATE_TO_UI_CONTAINER[ state ] == "dead"

    def test_stalled_maps_to_todo( self ):
        assert STATE_TO_UI_CONTAINER[ JobState.STALLED ] == "todo"

    def test_container_values_are_expected_set( self ):
        containers = set( STATE_TO_UI_CONTAINER.values() )
        assert containers == { "todo", "run", "done", "dead" }
