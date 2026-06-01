"""
Unit tests for the CJ Flow unified job state machine (cosa.rest.job_state).

Covers the JobState enum, the VALID_TRANSITIONS matrix, the convenience state
sets, the STATE_TO_UI_CONTAINER mapping, and the validate_transition /
assert_valid_transition helpers — to genuine 100% line + branch + function.

Zero external dependencies — job_state is stdlib-only (enum).
"""

import unittest
import time

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


class TestJobStateEnum( unittest.TestCase ):
    """
    Validate the JobState enum's str-inheritance + membership.

    Ensures:
        - JobState is a str-Enum so members compare equal to their values
        - All ten documented lifecycle states are present
    """

    def test_str_enum_equals_value( self ):
        # str-Enum: member == its string value, and is itself a str
        self.assertEqual( JobState.PENDING, "pending" )
        self.assertIsInstance( JobState.RUNNING, str )

    def test_all_states_present( self ):
        expected = {
            "pending", "queued", "scheduled", "paused", "running",
            "completed", "failed", "interrupted", "cancelled", "stalled"
        }
        self.assertEqual( { s.value for s in JobState }, expected )


class TestStateGroupings( unittest.TestCase ):
    """
    Validate the convenience sets + the UI-container mapping.

    Ensures:
        - Terminal / pre-execution / active / resumable sets hold the right members
        - Every JobState maps to a UI container
    """

    def test_terminal_states( self ):
        self.assertEqual(
            TERMINAL_STATES,
            frozenset( { JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED, JobState.INTERRUPTED } )
        )

    def test_pre_execution_states( self ):
        self.assertEqual(
            PRE_EXECUTION_STATES,
            frozenset( { JobState.PENDING, JobState.QUEUED, JobState.SCHEDULED, JobState.PAUSED } )
        )

    def test_active_and_resumable_states( self ):
        self.assertEqual( ACTIVE_STATES, frozenset( { JobState.RUNNING } ) )
        self.assertEqual( RESUMABLE_STATES, frozenset( { JobState.STALLED } ) )

    def test_every_state_maps_to_ui_container( self ):
        # Every enum member has an entry, and each entry is a known container.
        self.assertEqual( set( STATE_TO_UI_CONTAINER.keys() ), set( JobState ) )
        self.assertEqual( set( STATE_TO_UI_CONTAINER.values() ), { "todo", "run", "done", "dead" } )

    def test_transition_matrix_covers_every_state( self ):
        # Defensive contract: every JobState is a key in VALID_TRANSITIONS
        # (so validate_transition's .get default is genuinely unreachable).
        self.assertEqual( set( VALID_TRANSITIONS.keys() ), set( JobState ) )


class TestValidateTransition( unittest.TestCase ):
    """
    Validate validate_transition() — the boolean transition check.

    Ensures:
        - Returns True for a transition in the matrix
        - Returns False for a transition not in the matrix
        - Accepts bare string values (coerced via JobState(...))
        - Terminal states (empty target set) always return False
    """

    def test_valid_transition_returns_true( self ):
        self.assertTrue( validate_transition( JobState.PENDING, JobState.QUEUED ) )

    def test_invalid_transition_returns_false( self ):
        # PENDING → RUNNING is not allowed (must go through QUEUED)
        self.assertFalse( validate_transition( JobState.PENDING, JobState.RUNNING ) )

    def test_accepts_string_values( self ):
        # String inputs are coerced to JobState members
        self.assertTrue( validate_transition( "queued", "running" ) )
        self.assertFalse( validate_transition( "queued", "completed" ) )

    def test_terminal_state_has_no_valid_transitions( self ):
        self.assertFalse( validate_transition( JobState.COMPLETED, JobState.RUNNING ) )


class TestAssertValidTransition( unittest.TestCase ):
    """
    Validate assert_valid_transition() — the raising variant.

    Ensures:
        - Returns None silently for a valid transition
        - Raises ValueError listing the valid targets for an invalid non-terminal source
        - Raises ValueError with "(terminal)" for an invalid terminal source
    """

    def test_valid_transition_returns_none( self ):
        self.assertIsNone( assert_valid_transition( JobState.RUNNING, JobState.COMPLETED ) )

    def test_invalid_from_non_terminal_lists_valid_targets( self ):
        with self.assertRaises( ValueError ) as ctx:
            assert_valid_transition( JobState.PENDING, JobState.RUNNING )
        msg = str( ctx.exception )
        self.assertIn( "Invalid job state transition: pending → running", msg )
        # Non-terminal source → the valid-targets branch (sorted list) is taken
        self.assertIn( "Valid transitions from pending:", msg )
        self.assertIn( "queued", msg )
        self.assertNotIn( "(terminal)", msg )

    def test_invalid_from_terminal_says_terminal( self ):
        with self.assertRaises( ValueError ) as ctx:
            assert_valid_transition( JobState.COMPLETED, JobState.RUNNING )
        msg = str( ctx.exception )
        # Terminal source → empty valid set → the "(terminal)" branch is taken
        self.assertIn( "(terminal)", msg )


def isolated_unit_test():
    """
    Run the job_state unit tests in isolation and report a single-line result.

    Ensures:
        - Returns (success, duration, message) for the smoke-runner harness
    """
    import cosa.utils.util as du

    start_time = time.time()
    suite = unittest.TestLoader().loadTestsFromModule( __import__( __name__ ) )
    result = unittest.TextTestRunner( verbosity=2 ).run( suite )
    duration = time.time() - start_time

    success = result.wasSuccessful()
    message = f"{result.testsRun} run, {len( result.failures )} failed, {len( result.errors )} errors"
    return success, duration, message


if __name__ == "__main__":
    ok, secs, msg = isolated_unit_test()
    print( f"\n{'✅ PASS' if ok else '❌ FAIL'} job_state tests in {secs:.3f}s — {msg}" )
