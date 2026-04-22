"""
Test data seeding utilities for job_history table.

Provides reusable seed functions for both integration and E2E tests.
All functions insert JobHistory rows directly via SQLAlchemy into
whichever database the current engine points to (lupin_db_test when
running under test runners).

Usage:
    from tests.helpers.job_history_seed import seed_standard_job_set

    records = seed_standard_job_set( user_id="abc-123", user_email="test@example.com" )
"""

from datetime import datetime, timedelta, timezone

from cosa.rest.db.database import get_db
from cosa.rest.job_state import JobState
from cosa.rest.postgres_models import JobHistory


def seed_job_history_records( user_id, user_email, records ):
    """
    Insert job_history rows directly via SQLAlchemy.

    Requires:
        - user_id is a non-empty string (JWT uid, typically UUID from users table)
        - user_email is a non-empty string
        - records is a list of dicts with optional override keys

    Ensures:
        - Each record is inserted into the job_history table
        - Returns list of dicts representing the inserted rows
        - id_hash format: "test-job-{id_suffix}::{user_id}"

    Args:
        user_id: JWT uid string (e.g., UUID from users table)
        user_email: User email string
        records: List of dicts with optional overrides:
            id_suffix, job_type, status, question_text, error,
            duration_seconds, metadata_json, created_at

    Returns:
        List of inserted record dicts with generated id_hash values.
    """
    now      = datetime.now( timezone.utc )
    inserted = []

    with get_db() as session:
        for i, rec in enumerate( records ):
            suffix  = rec.get( "id_suffix", f"{i:03d}" )
            id_hash = f"test-job-{suffix}::{user_id}"

            row = JobHistory(
                id_hash          = id_hash,
                job_type         = rec.get( "job_type", "deep_research" ),
                user_id          = user_id,
                user_email       = user_email,
                session_id       = rec.get( "session_id", "test-session" ),
                routing_command  = rec.get( "routing_command", "deep research" ),
                status           = rec.get( "status", JobState.COMPLETED.value ),
                question_text    = rec.get( "question_text", f"Test question {suffix}" ),
                error            = rec.get( "error", None ),
                is_cache_hit     = rec.get( "is_cache_hit", False ),
                duration_seconds = rec.get( "duration_seconds", 12.5 ),
                metadata_json    = rec.get( "metadata_json", { "agent_type": "deep_research" } ),
                created_at       = rec.get( "created_at", now - timedelta( seconds=i ) ),
                started_at       = rec.get( "started_at", now - timedelta( seconds=i ) ),
                completed_at     = rec.get( "completed_at", now ),
                updated_at       = rec.get( "updated_at", now ),
            )
            session.add( row )

            inserted.append( {
                "id_hash"          : id_hash,
                "job_type"         : row.job_type,
                "user_id"          : user_id,
                "user_email"       : user_email,
                "status"           : row.status,
                "question_text"    : row.question_text,
                "error"            : row.error,
                "duration_seconds" : row.duration_seconds,
                "metadata_json"    : row.metadata_json,
                "created_at"       : row.created_at,
            } )

    return inserted


def seed_standard_job_set( user_id, user_email ):
    """
    Seed 5 standard records with mixed statuses and job types.

    Requires:
        - user_id is a non-empty string
        - user_email is a non-empty string

    Ensures:
        - Inserts 5 rows: 2 COMPLETED, 1 FAILED, 1 INTERRUPTED, 1 PENDING
        - Uses variety of job_type values for filter testing
        - Returns list of 5 inserted record dicts

    Returns:
        List of 5 inserted record dicts.
    """
    now = datetime.now( timezone.utc )

    records = [
        {
            "id_suffix"       : "std-001",
            "job_type"        : "deep_research",
            "status"          : JobState.COMPLETED.value,
            "question_text"   : "What are the latest advances in quantum computing?",
            "duration_seconds": 45.2,
            "metadata_json"   : { "agent_type": "deep_research", "abstract": "Quantum computing overview" },
            "created_at"      : now - timedelta( hours=2 ),
        },
        {
            "id_suffix"       : "std-002",
            "job_type"        : "podcast",
            "status"          : JobState.COMPLETED.value,
            "question_text"   : "Create a podcast about machine learning trends",
            "duration_seconds": 120.8,
            "metadata_json"   : { "agent_type": "podcast", "abstract": "ML trends discussion" },
            "created_at"      : now - timedelta( hours=1 ),
        },
        {
            "id_suffix"       : "std-003",
            "job_type"        : "deep_research",
            "status"          : JobState.FAILED.value,
            "question_text"   : "Research climate change mitigation strategies",
            "error"           : "LLM API timeout after 300 seconds",
            "duration_seconds": 300.0,
            "metadata_json"   : { "agent_type": "deep_research" },
            "created_at"      : now - timedelta( minutes=30 ),
        },
        {
            "id_suffix"       : "std-004",
            "job_type"        : "claude_code",
            "status"          : JobState.INTERRUPTED.value,
            "question_text"   : "Refactor authentication module",
            "error"           : "Server shutdown during execution",
            "duration_seconds": 60.0,
            "metadata_json"   : { "agent_type": "claude_code" },
            "created_at"      : now - timedelta( minutes=15 ),
        },
        {
            "id_suffix"       : "std-005",
            "job_type"        : "deep_research",
            "status"          : JobState.PENDING.value,
            "question_text"   : "Analyze renewable energy adoption rates",
            "duration_seconds": None,
            "metadata_json"   : { "agent_type": "deep_research" },
            "created_at"      : now - timedelta( minutes=5 ),
        },
    ]

    return seed_job_history_records( user_id, user_email, records )


def seed_time_window_jobs( user_id, user_email ):
    """
    Seed 3 jobs at different ages for time-window filter testing.

    Requires:
        - user_id is a non-empty string
        - user_email is a non-empty string

    Ensures:
        - Inserts 3 rows at: 3 days, 10 days, 40 days ago
        - All have status COMPLETED to isolate time-window behavior
        - Returns list of 3 inserted record dicts

    Returns:
        List of 3 inserted record dicts.
    """
    now = datetime.now( timezone.utc )

    records = [
        {
            "id_suffix"    : "tw-3d",
            "status"       : JobState.COMPLETED.value,
            "question_text": "Recent job (3 days old)",
            "created_at"   : now - timedelta( days=3 ),
        },
        {
            "id_suffix"    : "tw-10d",
            "status"       : JobState.COMPLETED.value,
            "question_text": "Medium-age job (10 days old)",
            "created_at"   : now - timedelta( days=10 ),
        },
        {
            "id_suffix"    : "tw-40d",
            "status"       : JobState.COMPLETED.value,
            "question_text": "Old job (40 days old)",
            "created_at"   : now - timedelta( days=40 ),
        },
    ]

    return seed_job_history_records( user_id, user_email, records )


def seed_pagination_jobs( user_id, user_email, count=25 ):
    """
    Seed N identical completed jobs for pagination testing.

    Requires:
        - user_id is a non-empty string
        - user_email is a non-empty string
        - count >= 1

    Ensures:
        - Inserts count rows, all status COMPLETED
        - Each has a unique id_suffix (pg-000 through pg-NNN)
        - Created_at staggered by 1 second for deterministic ordering
        - Returns list of count inserted record dicts

    Returns:
        List of count inserted record dicts.
    """
    now     = datetime.now( timezone.utc )
    records = []

    for i in range( count ):
        records.append( {
            "id_suffix"    : f"pg-{i:03d}",
            "status"       : JobState.COMPLETED.value,
            "question_text": f"Pagination test job {i}",
            "created_at"   : now - timedelta( seconds=i ),
        } )

    return seed_job_history_records( user_id, user_email, records )
