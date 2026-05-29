#!/usr/bin/env python3
"""
State Schemas for COSA SWE Team Agent.

Uses Pydantic for structured outputs and TypedDict for workflow state.
Designed for orchestrator-worker architecture with human-in-the-loop feedback.
"""

from enum import Enum
from typing import TypedDict, Literal, Any, Optional, List
from pydantic import BaseModel, Field


class OrchestratorState( Enum ):
    """
    State machine for the SWE Team Orchestrator.

    Active states represent work being done.
    Waiting states are yield points where control returns to event loop.
    Terminal states indicate completion or failure.
    External control states allow user intervention.
    """
    # Active states
    INITIALIZING  = "initializing"
    DECOMPOSING   = "decomposing"
    DELEGATING    = "delegating"
    CODING        = "coding"
    TESTING       = "testing"
    REVIEWING     = "reviewing"
    DEBUGGING     = "debugging"

    # Waiting states (yield control via await)
    WAITING_CONFIRMATION = "waiting_confirmation"
    WAITING_DECISION     = "waiting_decision"
    WAITING_FEEDBACK     = "waiting_feedback"

    # Terminal states
    COMPLETED = "completed"
    FAILED    = "failed"

    # External control states
    PAUSED  = "paused"
    STOPPED = "stopped"


class JobSubState( Enum ):
    """
    Sub-states for SWE Team jobs within the RUNNING queue.

    These provide finer-grained status for jobs that are in progress
    but may be blocked on various conditions.
    """
    EXECUTING            = "executing"
    WAITING_FOR_HUMAN    = "waiting_for_human"
    WAITING_FOR_SUBTASK  = "waiting_for_subtask"
    WAITING_FOR_LLM      = "waiting_for_llm"
    PAUSED               = "paused"


# =============================================================================
# Pydantic Models for Structured Outputs
# =============================================================================

class TaskSpec( BaseModel ):
    """
    A task specification for delegation to a subagent.

    Each TaskSpec represents a unit of work the lead decomposes
    from the original task description.
    """

    title          : str       = Field( description="Short title for the task" )
    objective      : str       = Field( description="What the agent must accomplish" )
    output_format  : str       = Field( description="Expected output structure" )
    tool_guidance  : str       = Field( default="", description="Guidance on which tools to use" )
    scope_boundary : str       = Field( default="", description="Explicit scope limits" )
    assigned_role  : Literal[ "coder", "tester", "reviewer", "debugger" ] = Field( default="coder" )
    priority       : int       = Field( default=1, ge=1, le=5 )
    depends_on     : Optional[ list[ int ] ] = Field( default=None )


class DelegationResult( BaseModel ):
    """
    Result of a delegated task execution.

    Returned by a subagent after completing (or failing) a TaskSpec.
    """

    task_index    : int                   = Field( description="Index of the TaskSpec" )
    task_title    : str                   = Field( description="Title from TaskSpec" )
    status        : Literal[ "success", "failure", "partial" ] = Field( default="success" )
    output        : str                   = Field( default="", description="Agent output/report" )
    files_changed : list[ str ]           = Field( default_factory=list )
    errors        : list[ str ]           = Field( default_factory=list )
    test_results  : Optional[ str ]       = Field( default=None, description="Test output if applicable" )
    confidence    : float                 = Field( default=0.0, ge=0.0, le=1.0 )


class ReviewFinding( BaseModel ):
    """
    A finding from code review.

    Returned by the reviewer agent after inspecting code changes.
    """

    severity    : Literal[ "critical", "major", "minor", "suggestion" ]
    file_path   : str
    line_number : Optional[ int ] = Field( default=None )
    description : str
    suggestion  : str = Field( default="" )


class VerificationResult( BaseModel ):
    """
    Result of a tester verification cycle.

    Returned after the tester agent writes/runs tests for a coder's
    implementation. Tracks pass/fail status, iterations, and test files.

    Requires:
        - task_index is a non-negative integer
        - task_title is a non-empty string

    Ensures:
        - Captures tester output and independent test run results
        - Tracks test files created for cleanup/reference
        - Records iteration count within the verification cycle
    """

    task_index         : int
    task_title         : str
    passed             : bool                                      = Field( default=False )
    tester_output      : str                                       = Field( default="" )
    test_run_result    : Optional[ dict ]                          = Field( default=None )
    test_files_created : List[ str ]                               = Field( default_factory=list )
    iterations         : int                                       = Field( default=1 )
    status             : Literal[ "passed", "failed", "skipped" ]  = Field( default="failed" )


# =============================================================================
# Workflow State (TypedDict)
# =============================================================================

class SweTeamState( TypedDict ):
    """
    Main workflow state for the SWE Team orchestrator.

    Tracks all phases and intermediate results through the
    task execution lifecycle.
    """

    # Input
    original_task : str

    # Decomposition Phase
    task_specs              : list[ TaskSpec ]
    decomposition_rationale : Optional[ str ]

    # Execution Phase
    current_task_index : int
    delegation_results : list[ DelegationResult ]
    iteration_count    : int

    # Review Phase
    review_findings      : list[ ReviewFinding ]
    review_passed        : bool

    # Verification Phase (Phase 3)
    verification_results          : list    # list[ VerificationResult ]
    total_verification_iterations : int

    # Final Output
    final_summary        : Optional[ str ]
    files_changed        : list[ str ]
    execution_metadata   : dict[ str, Any ]


def create_initial_state( task_description: str ) -> SweTeamState:
    """
    Create the initial state for an SWE Team task.

    Requires:
        - task_description is a non-empty string

    Ensures:
        - Returns fully initialized SweTeamState with defaults
        - All counters start at 0
        - All optional fields are None or empty

    Args:
        task_description: The user's task description

    Returns:
        SweTeamState: Initialized state dictionary
    """
    return SweTeamState(
        original_task                 = task_description,
        task_specs                    = [],
        decomposition_rationale       = None,
        current_task_index            = 0,
        delegation_results            = [],
        iteration_count               = 0,
        review_findings               = [],
        review_passed                 = False,
        verification_results          = [],
        total_verification_iterations = 0,
        final_summary                 = None,
        files_changed                 = [],
        execution_metadata            = {},
    )


def quick_smoke_test():
    """Quick smoke test for state schemas."""
    import cosa.utils.util as cu

    cu.print_banner( "SWE Team State Smoke Test", prepend_nl=True )

    try:
        # Test 1: OrchestratorState enum
        print( "Testing OrchestratorState enum..." )
        assert OrchestratorState.INITIALIZING.value == "initializing"
        assert OrchestratorState.COMPLETED.value == "completed"
        assert len( OrchestratorState ) == 14
        print( f"✓ OrchestratorState enum valid ({len( OrchestratorState )} states)" )

        # Test 2: JobSubState enum
        print( "Testing JobSubState enum..." )
        assert JobSubState.EXECUTING.value == "executing"
        assert JobSubState.WAITING_FOR_HUMAN.value == "waiting_for_human"
        assert len( JobSubState ) == 5
        print( f"✓ JobSubState enum valid ({len( JobSubState )} states)" )

        # Test 3: TaskSpec model validation
        print( "Testing TaskSpec model..." )
        spec = TaskSpec(
            title="Implement auth module",
            objective="Add JWT authentication",
            output_format="Modified auth.py with tests",
        )
        assert spec.assigned_role == "coder"
        assert spec.priority == 1
        print( "✓ TaskSpec model validates" )

        # Test 4: DelegationResult model validation
        print( "Testing DelegationResult model..." )
        result = DelegationResult(
            task_index=0,
            task_title="Implement auth module",
            status="success",
            output="Auth module implemented",
            files_changed=[ "src/auth.py", "tests/test_auth.py" ],
            confidence=0.9,
        )
        assert result.status == "success"
        assert len( result.files_changed ) == 2
        assert result.errors == []
        print( "✓ DelegationResult model validates" )

        # Test 5: ReviewFinding model validation
        print( "Testing ReviewFinding model..." )
        finding = ReviewFinding(
            severity="minor",
            file_path="src/auth.py",
            line_number=42,
            description="Missing docstring",
            suggestion="Add DBC docstring",
        )
        assert finding.severity == "minor"
        print( "✓ ReviewFinding model validates" )

        # Test 6: VerificationResult model validation
        print( "Testing VerificationResult model..." )
        vr = VerificationResult(
            task_index=0,
            task_title="Test auth module",
        )
        assert vr.passed is False
        assert vr.status == "failed"
        assert vr.tester_output == ""
        assert vr.test_run_result is None
        assert vr.test_files_created == []
        assert vr.iterations == 1

        vr_pass = VerificationResult(
            task_index    = 1,
            task_title    = "Test endpoint",
            passed        = True,
            status        = "passed",
            tester_output = "All tests pass",
            iterations    = 2,
        )
        assert vr_pass.passed is True
        assert vr_pass.status == "passed"
        print( "✓ VerificationResult model validates" )

        # Test 7: create_initial_state
        print( "Testing create_initial_state..." )
        state = create_initial_state( "Implement health check endpoint" )
        assert state[ "original_task" ] == "Implement health check endpoint"
        assert state[ "iteration_count" ] == 0
        assert state[ "review_passed" ] is False
        assert state[ "task_specs" ] == []
        assert state[ "verification_results" ] == []
        assert state[ "total_verification_iterations" ] == 0
        print( f"✓ create_initial_state works ({len( state )} keys)" )

        print( "\n✓ SWE Team State smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
