"""
CJ Flow Unified Job State Machine.

Provides a single JobState enum as the authoritative source of truth for job
lifecycle state, replacing the previous mix of status strings, queue container
names, and a paused boolean flag.

Requires:
    - No external dependencies (stdlib only)

Ensures:
    - All valid states represented as enum members
    - Transition validation via frozen matrix
    - Convenience sets for state grouping (terminal, pre-execution, active)
    - Mapping from state to frontend UI container name
"""

from enum import Enum


class JobState( str, Enum ):
    """
    Unified lifecycle state for all CJ Flow jobs.

    Inherits from str so that ``JobState.PENDING == "pending"`` and
    ``json.dumps( job.state )`` produce the bare string automatically.
    """

    PENDING     = "pending"       # Created, not yet in todo queue
    QUEUED      = "queued"        # In todo queue, eligible for immediate execution
    SCHEDULED   = "scheduled"     # In todo queue, future-dated (scheduled_at > now)
    PAUSED      = "paused"        # In todo queue, user-paused
    RUNNING     = "running"       # Consumer picked it up, executing
    COMPLETED   = "completed"     # Finished successfully (done queue)
    FAILED      = "failed"        # Finished with error (dead queue)
    INTERRUPTED = "interrupted"   # Server restart killed it
    CANCELLED   = "cancelled"     # User-initiated cancellation (dead queue)
    STALLED     = "stalled"      # Voice gate timeout — waiting for user, resumable


# ---------------------------------------------------------------------------
# Transition matrix — frozen dict of { state: frozenset( valid targets ) }
# ---------------------------------------------------------------------------

VALID_TRANSITIONS = {
    JobState.PENDING     : frozenset( { JobState.QUEUED, JobState.SCHEDULED, JobState.PAUSED } ),
    # QUEUED → FAILED: agentic-job construction can fail AFTER the job is queued
    # (todo_fifo_queue.push_job_agentic error path) — a queued-but-never-run job
    # whose build fails is a failure (→ dead queue), not a user cancellation.
    JobState.QUEUED      : frozenset( { JobState.RUNNING, JobState.PAUSED, JobState.SCHEDULED, JobState.CANCELLED, JobState.FAILED } ),
    JobState.SCHEDULED   : frozenset( { JobState.QUEUED, JobState.PAUSED, JobState.CANCELLED } ),
    JobState.PAUSED      : frozenset( { JobState.QUEUED, JobState.SCHEDULED, JobState.CANCELLED } ),
    JobState.RUNNING     : frozenset( { JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED, JobState.INTERRUPTED, JobState.STALLED } ),
    JobState.STALLED     : frozenset( { JobState.RUNNING, JobState.CANCELLED } ),
    JobState.COMPLETED   : frozenset(),
    JobState.FAILED      : frozenset(),
    JobState.CANCELLED   : frozenset(),
    JobState.INTERRUPTED : frozenset(),
}

# ---------------------------------------------------------------------------
# Convenience sets
# ---------------------------------------------------------------------------

TERMINAL_STATES       = frozenset( { JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED, JobState.INTERRUPTED } )
PRE_EXECUTION_STATES  = frozenset( { JobState.PENDING, JobState.QUEUED, JobState.SCHEDULED, JobState.PAUSED } )
ACTIVE_STATES         = frozenset( { JobState.RUNNING } )
RESUMABLE_STATES      = frozenset( { JobState.STALLED } )

# ---------------------------------------------------------------------------
# State → frontend UI container mapping
# ---------------------------------------------------------------------------

STATE_TO_UI_CONTAINER = {
    JobState.PENDING     : "todo",
    JobState.QUEUED      : "todo",
    JobState.SCHEDULED   : "todo",
    JobState.PAUSED      : "todo",
    JobState.RUNNING     : "run",
    JobState.COMPLETED   : "done",
    JobState.FAILED      : "dead",
    JobState.CANCELLED   : "dead",
    JobState.INTERRUPTED : "dead",
    JobState.STALLED     : "todo",
}


# ---------------------------------------------------------------------------
# Transition validation
# ---------------------------------------------------------------------------

def validate_transition( from_state, to_state ):
    """
    Check whether a state transition is valid.

    Requires:
        - from_state is a JobState enum member (or its string value)
        - to_state is a JobState enum member (or its string value)

    Ensures:
        - Returns True if the transition is in the valid matrix
        - Returns False otherwise (including for terminal states)
    """

    from_state = JobState( from_state )
    to_state   = JobState( to_state )

    return to_state in VALID_TRANSITIONS.get( from_state, frozenset() )


def assert_valid_transition( from_state, to_state ):
    """
    Assert that a state transition is valid, raising ValueError if not.

    Requires:
        - from_state is a JobState enum member (or its string value)
        - to_state is a JobState enum member (or its string value)

    Ensures:
        - Returns None if valid
        - Raises ValueError with descriptive message if invalid
    """

    from_state = JobState( from_state )
    to_state   = JobState( to_state )

    if not validate_transition( from_state, to_state ):
        valid = VALID_TRANSITIONS.get( from_state, frozenset() )
        valid_str = ", ".join( sorted( s.value for s in valid ) ) if valid else "(terminal)"
        raise ValueError(
            f"Invalid job state transition: {from_state.value} → {to_state.value}. "
            f"Valid transitions from {from_state.value}: {valid_str}"
        )
