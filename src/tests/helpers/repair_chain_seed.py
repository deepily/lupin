"""
Seed helper for automated repair loop E2E tests.

Creates a 3-job repair chain in the job_history table:
  Job 1: Original presentation job — FAILED
  Job 2: BFE job that fixed it — COMPLETED
  Job 3: Resubmitted presentation job — COMPLETED

Usage:
    from tests.helpers.repair_chain_seed import seed_repair_chain

    records = seed_repair_chain( user_id="abc-123", user_email="test@example.com" )
"""

from datetime import datetime, timedelta, timezone

from cosa.rest.job_state import JobState

from tests.helpers.job_history_seed import seed_job_history_records


def seed_repair_chain( user_id, user_email ):
    """
    Seed a 3-job repair chain: failed → BFE fix → resubmitted success.

    Requires:
        - user_id is a non-empty string
        - user_email is a non-empty string

    Ensures:
        - 3 rows inserted with linked metadata (repair_chain_id, parent_bfe_job_id)
        - Chronological: Job 1 (10 min ago) → Job 2 (5 min ago) → Job 3 (1 min ago)
        - Returns list of 3 inserted record dicts

    Args:
        user_id: JWT uid string
        user_email: User email string

    Returns:
        List of 3 inserted record dicts with id_hash values.
    """
    now = datetime.now( timezone.utc )

    # Build id_hashes up front so we can cross-reference
    original_id = f"test-job-repair-001::{user_id}"
    bfe_id      = f"test-job-repair-bfe-002::{user_id}"
    resubmit_id = f"test-job-repair-003::{user_id}"

    records = [
        # Job 1: Original presentation job — FAILED
        {
            "id_suffix"       : "repair-001",
            "job_type"        : "presentation",
            "status"          : JobState.FAILED.value,
            "question_text"   : "Create presentation from quantum computing research",
            "routing_command" : "agent router go to presentation generator",
            "error"           : "KeyError: 'missing_slide_config' in orchestrator.py line 412",
            "duration_seconds": 45.3,
            "metadata_json"   : {
                "agent_type"      : "presentation",
                "repair_chain_id" : None,
                "abstract"        : "Presentation generation failed during slide layout phase",
            },
            "created_at"      : now - timedelta( minutes=10 ),
            "started_at"      : now - timedelta( minutes=10 ),
            "completed_at"    : now - timedelta( minutes=9 ),
        },
        # Job 2: BFE job — COMPLETED (fixed the bug)
        {
            "id_suffix"       : "repair-bfe-002",
            "job_type"        : "bug_fix_expediter",
            "status"          : JobState.COMPLETED.value,
            "question_text"   : f"[Bug Fix Expediter] Fix job: {original_id}",
            "routing_command" : "agent router go to bug fix expediter",
            "error"           : None,
            "duration_seconds": 120.5,
            "metadata_json"   : {
                "agent_type"        : "bug_fix_expediter",
                "repair_chain_id"   : original_id,
                "attempt_number"    : 1,
                "fix_gist"          : "Added missing slide_config key to presentation orchestrator",
                "resubmitted_job_id": resubmit_id,
                "abstract"          : "Root cause: missing config key. Fix applied and committed.",
            },
            "created_at"      : now - timedelta( minutes=5 ),
            "started_at"      : now - timedelta( minutes=5 ),
            "completed_at"    : now - timedelta( minutes=3 ),
        },
        # Job 3: Resubmitted presentation job — COMPLETED
        {
            "id_suffix"       : "repair-003",
            "job_type"        : "presentation",
            "status"          : JobState.COMPLETED.value,
            "question_text"   : "Create presentation from quantum computing research",
            "routing_command" : "agent router go to presentation generator",
            "error"           : None,
            "duration_seconds": 55.7,
            "metadata_json"   : {
                "agent_type"       : "presentation",
                "repair_chain_id"  : original_id,
                "parent_bfe_job_id": bfe_id,
                "attempt_number"   : 1,
                "abstract"         : "Presentation generated successfully (15 slides, auto-fixed)",
            },
            "created_at"      : now - timedelta( minutes=1 ),
            "started_at"      : now - timedelta( minutes=1 ),
            "completed_at"    : now,
        },
    ]

    return seed_job_history_records( user_id, user_email, records )
