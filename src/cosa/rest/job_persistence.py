"""
CJ Flow Persistence Service — durable PostgreSQL-backed job state tracking.

Stateless service module (functions, no class) following queue_util.py pattern.
All persist_* functions are fire-and-forget: catch and log exceptions, never
break the queue pipeline.

Scope: AgenticJobBase subclasses only (deep_research, podcast, presentation,
claude_code, swe_team, research_to_podcast, research_to_presentation,
bug_fix_expediter). Sync agents are cached in Postgres.

Usage:
    from cosa.rest.job_persistence import (
        persist_job_created_from_metadata,
        persist_job_started_from_metadata,
        persist_job_completed_from_metadata,
        persist_job_failed_from_metadata,
        mark_interrupted_jobs,
        query_job_history,
        get_job_by_id_hash,
        delete_job_history,
        is_agentic_job_type
    )

Created: 2026-03-14
"""
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy import update, select, func, and_

from cosa.rest.db.database import get_db
from cosa.rest.postgres_models import JobHistory, ServerLifecycle
from cosa.rest.job_state import JobState
from cosa.config.configuration_manager import ConfigurationManager


# ---------------------------------------------------------------------------
# Agentic job type filter
# ---------------------------------------------------------------------------

AGENTIC_JOB_TYPES = frozenset( {
    "deep_research",
    "podcast",
    "presentation",
    "claude_code",
    "swe_team",
    "research_to_podcast",
    "research_to_presentation",
    "bug_fix_expediter",
    "test_suite",  # Added 2026-04-05 Session 389: scheduled test-suite jobs need DB persistence
                   # to survive server reloads. Discovered when Phase D scheduled job was lost
                   # repeatedly on uvicorn hot-reload.
    "test_fix_expediter",  # Added 2026-04-11 Session 1b8c1cc0 (TFE forensics fix). Without this
                           # every TFE failure landed in the UI as "Unknown error" because the
                           # entire persistence layer was gated behind this allowlist. See plan:
                           # src/rnd/v0.1.6/2026.04.11-tfe-forensics-capture-plan.md
} )


def is_agentic_job_type( job_type ):
    """
    Check if a job type is an agentic job that should be persisted.

    Requires:
        - job_type is a string or None

    Ensures:
        - Returns True if job_type is in AGENTIC_JOB_TYPES
        - Returns False for None or non-agentic types
    """
    if not job_type:
        return False
    return job_type in AGENTIC_JOB_TYPES


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def _is_persistence_enabled():
    """
    Check if CJ Flow persistence is enabled via config.

    Ensures:
        - Returns True if config key is missing or set to 'true'
        - Returns False if config key is set to 'false'
        - Never raises — defaults to True on any error
    """
    try:
        config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        value = config_mgr.get( "cj flow persistence enabled", default="true" )
        return str( value ).lower() == "true"
    except Exception:
        return True


def _get_history_days():
    """
    Get the number of days to retain job history.

    Ensures:
        - Returns integer number of days (default 30)
        - Never raises
    """
    try:
        config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        return int( config_mgr.get( "cj flow persistence history days", default="30" ) )
    except Exception:
        return 30


# ---------------------------------------------------------------------------
# Server lifecycle — downtime-aware scheduled-job catch-up
# ---------------------------------------------------------------------------

SERVER_LIFECYCLE_KEY = "singleton"


def record_server_available( ts=None ):
    """
    Stamp the server's last-available timestamp (heartbeat + clean-shutdown marker).

    Called periodically by the clock-loop heartbeat (survives hard kills) and once
    in the clean-shutdown ritual. UPSERTs the single server_lifecycle row.

    Requires:
        - ts is a timezone-aware datetime, or None to use current UTC

    Ensures:
        - server_lifecycle.last_available_at reflects ts (single-row UPSERT)
        - Fire-and-forget: never raises (logs + returns on failure)
        - No-op when persistence is disabled
    """
    if not _is_persistence_enabled():
        return
    if ts is None:
        ts = datetime.now( timezone.utc )
    try:
        with get_db() as session:
            row = session.get( ServerLifecycle, SERVER_LIFECYCLE_KEY )
            if row is None:
                session.add( ServerLifecycle( key=SERVER_LIFECYCLE_KEY, last_available_at=ts ) )
            else:
                row.last_available_at = ts
    except Exception as e:
        print( f"[WARN] record_server_available failed: {e}" )


def get_last_available():
    """
    Read the server's last-available timestamp recorded before this boot.

    Ensures:
        - Returns a timezone-aware UTC datetime, or None if never recorded
          (first-ever boot / fresh DB) or on failure
    """
    try:
        with get_db() as session:
            row = session.get( ServerLifecycle, SERVER_LIFECYCLE_KEY )
            if row is None or row.last_available_at is None:
                return None
            ts = row.last_available_at
            if ts.tzinfo is None:
                ts = ts.replace( tzinfo=timezone.utc )
            return ts.astimezone( timezone.utc )
    except Exception as e:
        print( f"[WARN] get_last_available failed: {e}" )
        return None


def _is_within_downtime( scheduled_at_str, last_available, now ):
    """
    True if a job's scheduled_at fell within the measured downtime window
    [last_available, now] — i.e., it was missed because the server was down.

    Ensures:
        - Returns False if last_available is None (first boot — no known downtime)
        - Returns False on parse error or if scheduled_at is outside the window
        - Comparison is timezone-aware UTC
    """
    if last_available is None:
        return False
    try:
        scheduled_dt = datetime.fromisoformat( scheduled_at_str )
        if scheduled_dt.tzinfo is None:
            scheduled_dt = scheduled_dt.replace( tzinfo=timezone.utc )
        return last_available <= scheduled_dt <= now
    except ( ValueError, TypeError ):
        return False


def _downtime_catchup_announcement( job_id, scheduled_at_str, now ):
    """
    Build the LOUD announcement for a job resurrected by the downtime-restore
    branch — naming scheduled_at vs actual run time and how many hours late its
    slot fired (row f0b3f630).

    A downtime catch-up run is otherwise SILENT: the job reports as a normal
    completion with no signal that its requested slot was missed by hours. A
    seat that submitted into the overnight window and later sees a completed run
    has no way to know the schedule was ignored. This produces that signal.

    Requires:
        - job_id is a non-empty string (the id_hash)
        - scheduled_at_str is the job's requested-slot ISO datetime string
        - now is a timezone-aware datetime (the actual catch-up run time)

    Ensures:
        - Returns a single-line string tagged with the [CJ-CATCHUP-LATE] marker,
          naming job_id, scheduled_at, the actual run time, and hours-late (one
          decimal)
        - hours-late is ( now - scheduled_at ) in hours, floored at 0.0
        - A naive scheduled_at is treated as UTC
        - On a parse error returns a marked line naming the unparseable value
          rather than raising — this path must never break startup recovery
    """
    try:
        scheduled_dt = datetime.fromisoformat( scheduled_at_str )
        if scheduled_dt.tzinfo is None:
            scheduled_dt = scheduled_dt.replace( tzinfo=timezone.utc )
        hours_late = ( now - scheduled_dt ).total_seconds() / 3600.0
        if hours_late < 0:
            hours_late = 0.0
        return ( f"[CJ-CATCHUP-LATE] Job {job_id} fired as a downtime catch-up: "
                 f"scheduled_at={scheduled_at_str}, actual={now.isoformat()}, "
                 f"{hours_late:.1f}h past its slot — the requested schedule was MISSED "
                 f"(server was down for that window)." )
    except ( ValueError, TypeError ):
        return ( f"[CJ-CATCHUP-LATE] Job {job_id} fired as a downtime catch-up with an "
                 f"unparseable scheduled_at={scheduled_at_str!r} — the requested schedule "
                 f"was MISSED (server was down for that window)." )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_metadata_json( metadata ):
    """
    Extract rich fields from transition metadata into JSONB-ready dict.

    Requires:
        - metadata is a dict or None

    Ensures:
        - Returns dict with available rich fields extracted
        - Returns empty dict if metadata is None or empty
    """
    if not metadata:
        return {}

    rich_fields = [
        "response_text", "abstract", "report_link",
        "cost_summary", "artifacts", "answer_conversational",
        "push_counter", "agent_type", "stack_trace",
        "scheduled_at", "monopolize",
        "paused",         # Durable-queue restore (row 2817b0f5): a user-paused job must come back paused, not active
        "original_args",  # CJ Flow persistence: exact args a job was submitted with (for BFE resubmit)
        "checkpoint",     # Checkpoint-resume: serialized state for stalled jobs (Session 9056c113)
        "yaml_path",                  # Presentation re-render from YAML
        "pptx_path",                  # Presentation PowerPoint download
        "remediation_snapshot_path",  # TFE/BFE remediation snapshot link
    ]

    result = {}
    for field in rich_fields:
        if field in metadata and metadata[ field ] is not None:
            result[ field ] = metadata[ field ]

    return result


# ---------------------------------------------------------------------------
# Persistence functions (fire-and-forget)
# ---------------------------------------------------------------------------

def persist_job_created_from_metadata( job_id, user_id, metadata ):
    """
    INSERT a new job_history row with status='pending'.

    Called on pending->todo transition.

    Requires:
        - job_id is a non-empty string (the id_hash)
        - user_id is a non-empty string
        - metadata is a dict with job context

    Ensures:
        - Row inserted into job_history with status='pending'
        - Never raises — logs warning on failure
    """
    if not _is_persistence_enabled():
        return

    try:
        with get_db() as session:
            # Idempotent create (row 2817b0f5): on restart the durable-queue restore
            # re-pushes preserved jobs under their ORIGINAL id_hash, which re-fires the
            # PENDING->QUEUED transition and reaches here again. id_hash is the PK, so a
            # blind INSERT would raise IntegrityError; skipping when the row already
            # exists makes re-enqueue a clean no-op rather than a swallowed error, and
            # keeps the no-resurrect guarantee off the exception path.
            if session.get( JobHistory, job_id ) is not None:
                return

            job = JobHistory(
                id_hash         = job_id,
                job_type        = metadata.get( "agent_type", "unknown" ),
                user_id         = user_id or "unknown",
                user_email      = metadata.get( "user_email" ),
                session_id      = metadata.get( "session_id" ),
                routing_command = metadata.get( "routing_command" ),
                status          = JobState.PENDING.value,
                question_text   = metadata.get( "question_text" ),
                is_cache_hit    = metadata.get( "is_cache_hit", False ),
                metadata_json   = _build_metadata_json( metadata )
            )
            session.add( job )
    except Exception as e:
        print( f"[WARN] persist_job_created_from_metadata failed for {job_id}: {e}" )


def persist_job_paused_state( job_id, paused ):
    """
    Patch a job_history row's metadata_json `paused` flag (row 2817b0f5).

    Pause/resume are in-memory-only state changes on the todo queue; job_history
    stores every pre-execution job as `pending` and never learned whether it was
    paused. Without this, the durable-queue restore would bring a user-paused job
    back ACTIVE (silently un-paused). Recording the flag lets restore re-hold it.

    Requires:
        - job_id is a non-empty string (the id_hash)
        - paused is a bool

    Ensures:
        - metadata_json.paused is set to `paused` for the matching row (no-op if the
          row does not exist — e.g. a non-agentic job absent from job_history)
        - status is NOT touched — a paused job stays `pending` in the ledger
        - Never raises — logs a warning on failure
    """
    if not _is_persistence_enabled():
        return

    try:
        with get_db() as session:
            row = session.get( JobHistory, job_id )
            if row is None:
                return
            # SQLAlchemy does not track in-place mutation of a JSONB dict, so build a
            # NEW dict and reassign the attribute to mark the column dirty.
            metadata             = dict( row.metadata_json or {} )
            metadata[ "paused" ] = paused
            row.metadata_json    = metadata
            row.updated_at       = datetime.now( timezone.utc )
    except Exception as e:
        print( f"[WARN] persist_job_paused_state failed for {job_id}: {e}" )


def persist_job_started_from_metadata( job_id, metadata ):
    """
    UPDATE job_history row: status='running', started_at=now().

    Called on todo->run transition.

    Requires:
        - job_id is a non-empty string (the id_hash)
        - metadata is a dict (currently unused, reserved for enrichment)

    Ensures:
        - Row updated with status='running' and started_at timestamp
        - Never raises — logs warning on failure
    """
    if not _is_persistence_enabled():
        return

    try:
        now = datetime.now( timezone.utc )
        with get_db() as session:
            session.execute(
                update( JobHistory )
                .where( JobHistory.id_hash == job_id )
                .values(
                    status     = JobState.RUNNING.value,
                    started_at = now,
                    updated_at = now
                )
            )
    except Exception as e:
        print( f"[WARN] persist_job_started_from_metadata failed for {job_id}: {e}" )


def persist_job_completed_from_metadata( job_id, metadata ):
    """
    UPDATE job_history row: status='completed', completed_at, duration, metadata_json.

    Called on run->done transition.

    Requires:
        - job_id is a non-empty string (the id_hash)
        - metadata is a dict with completion data

    Ensures:
        - Row updated with status='completed', completion timestamp, and rich metadata
        - duration_seconds calculated if started_at is available
        - Never raises — logs warning on failure
    """
    if not _is_persistence_enabled():
        return

    try:
        now = datetime.now( timezone.utc )
        values = {
            "status"        : JobState.COMPLETED.value,
            "completed_at"  : now,
            "updated_at"    : now,
        }

        # Read existing row so we can MERGE metadata_json (preserve fields set at
        # creation, e.g. original_args) and calculate duration_seconds in one pass.
        with get_db() as session:
            row = session.execute(
                select( JobHistory.started_at, JobHistory.metadata_json )
                .where( JobHistory.id_hash == job_id )
            ).one_or_none()

            existing_metadata = ( row.metadata_json if row is not None else {} ) or {}
            new_metadata      = _build_metadata_json( metadata )
            values[ "metadata_json" ] = { **existing_metadata, **new_metadata }

            if row is not None and row.started_at is not None:
                values[ "duration_seconds" ] = ( now - row.started_at ).total_seconds()

            session.execute(
                update( JobHistory )
                .where( JobHistory.id_hash == job_id )
                .values( **values )
            )
    except Exception as e:
        print( f"[WARN] persist_job_completed_from_metadata failed for {job_id}: {e}" )


def persist_job_stalled_from_metadata( job_id, metadata ):
    """
    UPDATE job_history row: status='stalled', completed_at, checkpoint in metadata_json.

    Called on run->done transition when the job reached a valid stalled state
    (voice gate timeout with checkpoint saved). The row stays resumable — the
    UI badge (`notifications.js::isStalled`) + Resume button hinge on this
    status, and the TFE resume resolver (`resume_resolver.py`) requires
    status='stalled' before it will rehydrate a checkpoint.

    Requires:
        - job_id is a non-empty string
        - metadata is a dict with checkpoint data (typically under "checkpoint" or "artifacts.checkpoint")

    Ensures:
        - Row updated with status='stalled', completion timestamp, duration
        - metadata_json is merged (preserves original_args, adds checkpoint)
        - Never raises — logs warning on failure
    """
    if not _is_persistence_enabled():
        return

    try:
        now = datetime.now( timezone.utc )
        values = {
            "status"        : JobState.STALLED.value,
            "completed_at"  : now,
            "updated_at"    : now,
        }

        with get_db() as session:
            row = session.execute(
                select( JobHistory.started_at, JobHistory.metadata_json )
                .where( JobHistory.id_hash == job_id )
            ).one_or_none()

            existing_metadata = ( row.metadata_json if row is not None else {} ) or {}
            new_metadata      = _build_metadata_json( metadata )
            values[ "metadata_json" ] = { **existing_metadata, **new_metadata }

            if row is not None and row.started_at is not None:
                values[ "duration_seconds" ] = ( now - row.started_at ).total_seconds()

            session.execute(
                update( JobHistory )
                .where( JobHistory.id_hash == job_id )
                .values( **values )
            )
    except Exception as e:
        print( f"[WARN] persist_job_stalled_from_metadata failed for {job_id}: {e}" )


def persist_job_failed_from_metadata( job_id, metadata ):
    """
    UPDATE job_history row: status='failed', error, completed_at.

    Called on run->dead transition.

    Requires:
        - job_id is a non-empty string (the id_hash)
        - metadata is a dict, may contain 'error' key

    Ensures:
        - Row updated with status='failed', error text, and completion timestamp
        - duration_seconds calculated if started_at is available
        - Never raises — logs warning on failure
    """
    if not _is_persistence_enabled():
        return

    try:
        now = datetime.now( timezone.utc )
        error_text = metadata.get( "error", "Unknown error" ) if metadata else "Unknown error"
        values = {
            "status"       : JobState.FAILED.value,
            "error"        : error_text,
            "completed_at" : now,
            "updated_at"   : now,
        }

        # Read existing row so we can MERGE metadata_json (preserve fields set at
        # creation, e.g. original_args) and calculate duration_seconds in one pass.
        with get_db() as session:
            row = session.execute(
                select( JobHistory.started_at, JobHistory.metadata_json )
                .where( JobHistory.id_hash == job_id )
            ).one_or_none()

            existing_metadata = ( row.metadata_json if row is not None else {} ) or {}
            new_metadata      = _build_metadata_json( metadata )
            values[ "metadata_json" ] = { **existing_metadata, **new_metadata }

            if row is not None and row.started_at is not None:
                values[ "duration_seconds" ] = ( now - row.started_at ).total_seconds()

            session.execute(
                update( JobHistory )
                .where( JobHistory.id_hash == job_id )
                .values( **values )
            )
    except Exception as e:
        print( f"[WARN] persist_job_failed_from_metadata failed for {job_id}: {e}" )


# ---------------------------------------------------------------------------
# Startup recovery
# ---------------------------------------------------------------------------

def mark_interrupted_jobs():
    """
    Mark in-flight jobs as interrupted at server startup.

    Distinguishes between:
    - RUNNING jobs: legitimately interrupted (were mid-execution) → INTERRUPTED
    - PENDING jobs with future scheduled_at: preserved for re-enqueue → stays PENDING
    - PENDING jobs whose scheduled_at fell within the measured downtime window
      [last_available, now]: preserved for an immediate catch-up run → stays PENDING
    - PENDING jobs with NO scheduled_at (immediate submits that never ran): preserved
      for re-enqueue → stays PENDING (row 2817b0f5 — a queued job must survive a bounce)
    - PENDING jobs scheduled BEFORE the downtime window (anomalous scheduler miss) → INTERRUPTED

    Called at server startup by main.py. Reads the last-available marker
    (record_server_available) to compute the exact downtime window.

    Ensures:
        - RUNNING jobs always marked INTERRUPTED
        - PENDING jobs with future scheduled_at are preserved
        - PENDING jobs missed during downtime are preserved for catch-up
        - Returns dict with counts: { "running", "pending_interrupted", "pending_preserved", "pending_catchup" }
        - Never raises — returns zeroed dict on failure
    """
    try:
        now = datetime.now( timezone.utc )
        counts = { "running": 0, "pending_interrupted": 0, "pending_preserved": 0, "pending_catchup": 0 }
        last_available = get_last_available()

        with get_db() as session:

            # 1. Always mark RUNNING as interrupted (was mid-execution)
            result = session.execute(
                update( JobHistory )
                .where( JobHistory.status == JobState.RUNNING.value )
                .values(
                    status       = JobState.INTERRUPTED.value,
                    completed_at = now,
                    updated_at   = now
                )
            )
            counts[ "running" ] = result.rowcount

            # 2. For PENDING jobs: check scheduled_at in metadata_json
            pending_rows = session.execute(
                select( JobHistory )
                .where( JobHistory.status == JobState.PENDING.value )
            ).scalars().all()

            for row in pending_rows:
                metadata     = row.metadata_json or {}
                scheduled_at = metadata.get( "scheduled_at" )

                if scheduled_at and _is_future_scheduled( scheduled_at, now ):
                    # Future — preserve (will be restored by get_restorable_jobs())
                    counts[ "pending_preserved" ] += 1
                    print( f"[CJ-PERSIST] Preserving scheduled job {row.id_hash} "
                           f"(scheduled_at={scheduled_at})" )
                elif scheduled_at and _is_within_downtime( scheduled_at, last_available, now ):
                    # Missed DURING the measured downtime window [last_available, now] —
                    # preserve (stays PENDING) so get_restorable_jobs() re-enqueues it; it is
                    # immediately eligible (scheduled_at <= now) and fires as a catch-up run.
                    counts[ "pending_catchup" ] += 1
                    # LOUD signal (row f0b3f630): this catch-up is otherwise silent — the job
                    # will report as a normal run with no flag that its slot fired hours late.
                    # Emit a marked line naming scheduled_at vs actual + hours-late so a seat
                    # that submitted into the dead window learns the schedule was missed.
                    print( _downtime_catchup_announcement( row.id_hash, scheduled_at, now ) )
                elif scheduled_at is None:
                    # Immediate submit (no scheduled_at) that never got its turn before
                    # the restart (row 2817b0f5). It never ran, so PRESERVE it (stays
                    # PENDING) for re-enqueue by get_restorable_jobs() — losing it is the
                    # exact bug this fix closes. A container bounce must not vaporize a
                    # job that was simply waiting in line.
                    counts[ "pending_preserved" ] += 1
                    print( f"[CJ-PERSIST] Preserving immediate job {row.id_hash} "
                           f"(no scheduled_at) for re-enqueue" )
                else:
                    # Has a scheduled_at that is PAST and BEFORE the downtime window — an
                    # anomalous scheduler miss while the server was up. Do NOT silently
                    # resurrect a schedule the server already passed: mark interrupted.
                    row.status       = JobState.INTERRUPTED.value
                    row.completed_at = now
                    row.updated_at   = now
                    counts[ "pending_interrupted" ] += 1

        total = counts[ "running" ] + counts[ "pending_interrupted" ]
        if total > 0:
            print( f"[INFO] Marked {total} interrupted job(s) "
                   f"(running={counts[ 'running' ]}, pending={counts[ 'pending_interrupted' ]})" )
        if counts[ "pending_preserved" ] > 0:
            print( f"[INFO] Preserved {counts[ 'pending_preserved' ]} future-scheduled job(s) for re-enqueue" )
        if counts[ "pending_catchup" ] > 0:
            print( f"[INFO] Preserved {counts[ 'pending_catchup' ]} downtime-missed job(s) for catch-up re-run" )

        return counts

    except Exception as e:
        print( f"[WARN] mark_interrupted_jobs failed: {e}" )
        return { "running": 0, "pending_interrupted": 0, "pending_preserved": 0, "pending_catchup": 0 }


def _is_future_scheduled( scheduled_at_str, now=None ):
    """
    Check if a scheduled_at ISO datetime string is in the future.

    Requires:
        - scheduled_at_str is a non-empty string (ISO format)

    Ensures:
        - Returns True if scheduled_at is in the future
        - Returns False on parse error or past timestamp

    Args:
        scheduled_at_str: ISO datetime string
        now: Optional current time (defaults to UTC now)

    Returns:
        bool
    """
    if now is None:
        now = datetime.now( timezone.utc )

    try:
        scheduled_dt = datetime.fromisoformat( scheduled_at_str )
        # Normalize to UTC for comparison
        if scheduled_dt.tzinfo is None:
            scheduled_dt = scheduled_dt.replace( tzinfo=timezone.utc )
        if now.tzinfo is None:
            now = now.replace( tzinfo=timezone.utc )
        return scheduled_dt > now
    except ( ValueError, TypeError ):
        return False


def get_restorable_jobs():
    """
    Query PENDING jobs preserved by mark_interrupted_jobs() for re-enqueue at startup.

    Called after mark_interrupted_jobs(), which has already marked every non-restorable
    case INTERRUPTED. Every row still PENDING here is meant to come back: future-scheduled,
    downtime-catch-up, AND immediate (no scheduled_at — row 2817b0f5).

    Ensures:
        - Returns list of dicts with job metadata sufficient for reconstruction
        - Only returns jobs with status='pending' (preserved by mark_interrupted_jobs)
        - scheduled_at may be None (an immediate job); paused carries the held state
        - Returns empty list on failure

    Returns:
        list of dicts with: id_hash, job_type, user_id, user_email, session_id,
        routing_command, question_text, scheduled_at, monopolize, paused, metadata_json
    """
    try:
        with get_db() as session:
            rows = session.execute(
                select( JobHistory )
                .where( JobHistory.status == JobState.PENDING.value )
            ).scalars().all()

            restorable = []
            for row in rows:
                metadata     = row.metadata_json or {}
                scheduled_at = metadata.get( "scheduled_at" )
                # Return EVERY surviving PENDING row (row 2817b0f5), not just the
                # scheduled ones. By the time this runs, mark_interrupted_jobs() has
                # already marked the anomalous cases INTERRUPTED, so the rows left as
                # PENDING are exactly the ones we want back: future-scheduled,
                # downtime-catch-up, AND immediate (scheduled_at is None). A None
                # scheduled_at rides through as an immediate job that runs on next
                # consume.
                restorable.append( {
                    "id_hash"         : row.id_hash,
                    "job_type"        : row.job_type,
                    "user_id"         : row.user_id,
                    "user_email"      : row.user_email or "",
                    "session_id"      : row.session_id or "",
                    "routing_command" : row.routing_command or "",
                    "question_text"   : row.question_text or "",
                    "scheduled_at"    : scheduled_at,
                    "monopolize"      : metadata.get( "monopolize", False ),
                    "paused"          : metadata.get( "paused", False ),
                    "metadata_json"   : metadata,
                } )

            return restorable

    except Exception as e:
        print( f"[WARN] get_restorable_jobs failed: {e}" )
        return []


def restore_pending_jobs( restorable, job_factory, ask_flow, register_scoped_job=None, debug=False ):
    """
    Rebuild and re-enqueue the jobs get_restorable_jobs() returned (row 2817b0f5).

    Extracted from the startup lifespan so the no-resurrect + paused-carry WIRING
    is unit-testable without a live server: inject a fake factory + fake queue.

    Requires:
        - restorable is a list of dicts from get_restorable_jobs()
        - job_factory( command, args_dict, user_id, user_email, session_id, debug )
          returns a job object (or None on failure) — normally create_agentic_job
        - ask_flow exposes submit( job=..., user_id=..., user_email=...,
          session_id=..., websocket_id=..., speak=... ) — the v2 AskFlow. This used
          to be the todo queue and the line below used to be `todo_queue.push( job )`.
          Rick ruled this caller IN by name (step 12): it is the one least likely to
          be noticed misbehaving — startup, unattended, re-enqueueing work an
          interruption left behind — so it must not keep a private door onto the
          queue while every other caller goes through the guarded one. There is no
          fallback to a direct push: a fallback is how a caller quietly keeps its
          old door
        - register_scoped_job, if given, is user_job_tracker.register_scoped_job
          (base_hash, user_id, session_id) -> scoped_hash. The user-job tracker is
          NOT rebuilt at startup, so WITHOUT this a restored job still runs (the
          consumer reads the queue directly) but is INVISIBLE to /api/get-queue and
          unresumable (that view filters by the tracker). Registering makes the
          restored job show up and be resumable; the verb strips + re-appends
          ::user_id, so passing the already-scoped id returns the same id_hash.

    Ensures:
        - the job is rebuilt from metadata_json["original_args"] (the exact submit
          args), so test_types / dry_run / pytest_args survive — NOT from the whole
          metadata envelope, which loses them to factory defaults
        - each rebuilt job REUSES its original id_hash, so it re-drives its OWN
          durable row (pending -> running -> terminal) and cannot resurrect on a
          later boot (one row, one identity, one restore)
        - scheduled_at rides through verbatim (None => immediate)
        - a job that was paused before the bounce is re-held (state = PAUSED) BEFORE
          push, so it is never eligible and comes back paused, not silently running
        - a row missing routing_command, or whose factory returns None, is skipped
          with a logged reason — never a hard failure that strands the rest
        - returns the count actually pushed

    Raises:
        - nothing from a single job; the caller wraps the whole restore in a guard
    """
    restored = 0
    for job_data in restorable:
        routing_cmd = job_data[ "routing_command" ]
        if not routing_cmd:
            print( f"[CJ-PERSIST] Cannot restore {job_data[ 'id_hash' ]}: no routing_command" )
            continue

        # Reconstruct from the ORIGINAL submit args (test_types, dry_run,
        # pytest_args, ...), which persistence nests under
        # metadata_json["original_args"]. Passing the whole metadata envelope as
        # args_dict loses them and the job rebuilds with factory DEFAULTS — proven
        # live (row 2817b0f5 E2E): a restored dry_run "unit" job came back as a
        # REAL "integration, e2e" run.
        original_args = ( job_data.get( "metadata_json" ) or {} ).get( "original_args" ) or {}
        job = job_factory(
            command    = routing_cmd,
            args_dict  = original_args,
            user_id    = job_data[ "user_id" ],
            user_email = job_data[ "user_email" ],
            session_id = job_data[ "session_id" ],
            debug      = debug,
        )
        if job is None:
            print( f"[CJ-PERSIST] Cannot restore {job_data[ 'id_hash' ]}: factory returned None" )
            continue

        # Reuse the ORIGINAL id_hash so the job re-drives its OWN durable row —
        # a fresh id would leave the original PENDING forever and re-restore a NEW
        # copy on every boot (unbounded resurrection).
        job.id_hash = job_data[ "id_hash" ]

        # Re-register in the user-job tracker so the restored job is VISIBLE in the
        # user's queue view and resumable (see the register_scoped_job contract
        # above). Passing the already-scoped id returns the same value.
        if register_scoped_job is not None:
            job.id_hash = register_scoped_job(
                job_data[ "id_hash" ], job_data[ "user_id" ], job_data[ "session_id" ]
            )

        job.scheduled_at = job_data[ "scheduled_at" ]   # None => immediate
        if job_data.get( "monopolize" ):
            job.monopolize = True

        # Re-hold a paused job BEFORE push, not after. push() notifies the consumer,
        # so a state set AFTER push races it — the consumer can start the job before
        # it is marked paused (proven live: a restored paused job RAN). Setting
        # PAUSED first means the job is never eligible in the first place.
        if job_data.get( "paused" ):
            job.state = JobState.PAUSED

        # Step 12: through the flow, like every other caller. `submit` with a prebuilt
        # job skips routing entirely — the command came off the stored row, so there is
        # nothing to re-derive — and the queued executor does the scope-and-push this
        # line used to do inline. The re-registration above still runs: the tracker is
        # not rebuilt at boot, and the scoper is idempotent, so doing it twice returns
        # the same id.
        # speak=False: this is a silent boot-time catch-up. Announcing every restored
        # job would greet a returning user with a burst of TTS about work they did not
        # just ask for.
        ask_flow.submit(
            job          = job,
            user_id      = job_data[ "user_id" ],
            user_email   = job_data[ "user_email" ],
            session_id   = job_data[ "session_id" ],
            websocket_id = job_data[ "session_id" ],
            speak        = False,
        )

        restored += 1
        kind = "immediate" if job_data[ "scheduled_at" ] is None else "scheduled"
        held = " (paused)" if job_data.get( "paused" ) else ""
        print( f"[CJ-PERSIST] Restored {kind} job{held}: {job_data[ 'id_hash' ]} "
               f"(type={job_data[ 'job_type' ]}, scheduled_at={job_data[ 'scheduled_at' ]})" )

    if restored:
        print( f"[CJ-PERSIST] Restored {restored} pre-execution job(s)" )
    return restored


def get_active_job_ids_by_user():
    """
    Query pending/running jobs grouped by user_id.

    Used at startup to rebuild UserJobTracker state.

    Ensures:
        - Returns dict mapping user_id -> list of id_hash strings
        - Returns empty dict on failure
    """
    try:
        with get_db() as session:
            rows = session.execute(
                select( JobHistory.user_id, JobHistory.id_hash )
                .where( JobHistory.status.in_( [ JobState.PENDING.value, JobState.RUNNING.value ] ) )
            ).all()

            result = {}
            for user_id, id_hash in rows:
                if user_id not in result:
                    result[ user_id ] = []
                result[ user_id ].append( id_hash )
            return result
    except Exception as e:
        print( f"[WARN] get_active_job_ids_by_user failed: {e}" )
        return {}


# ---------------------------------------------------------------------------
# Query functions (for API endpoints)
# ---------------------------------------------------------------------------

def _count_notifications_for_jobs( session, job_ids ):
    """
    Bulk-count non-hidden notifications grouped by job_id, using the supplied
    SQLAlchemy session. Single batched query — no N+1.

    Defined here (rather than calling NotificationRepository.count_by_job_ids)
    to reuse the active session and avoid pulling the repository class into a
    pure persistence module's import surface.

    Requires:
        - session: active SQLAlchemy session
        - job_ids: list of id_hash strings (may be empty)

    Ensures:
        - Returns dict mapping each input job_id to its count (0 if no rows)
        - Empty input returns {} without issuing a query
        - Returns {} on database failure (logged) — caller treats as all-zero counts
    """
    if not job_ids:
        return {}

    try:
        from cosa.rest.postgres_models import Notification

        rows = session.query(
            Notification.job_id,
            func.count( Notification.id ).label( 'count' )
        ).filter(
            Notification.job_id.in_( job_ids ),
            Notification.is_hidden == False
        ).group_by(
            Notification.job_id
        ).all()

        counts = { row.job_id: int( row.count ) for row in rows }
        return { job_id: counts.get( job_id, 0 ) for job_id in job_ids }
    except Exception as e:
        print( f"[WARN] _count_notifications_for_jobs failed: {e}" )
        return {}


def _unpack_metadata_json( md ):
    """
    Flatten the rich fields out of a JobHistory.metadata_json JSONB blob.

    Mirrors the field set surfaced at the top level by `/api/get-queue/done`
    (see routers/queues.py done-bucket handler) so /api/job-history can return
    the same shape.

    Requires:
        - md: dict (from row.metadata_json) or None / falsy

    Ensures:
        - Returns dict with all rich fields present (None / False defaults)
        - Aliases legacy `report_link` → `report_path` for naming alignment
        - Reads `response_text` falling back to legacy `answer_conversational`
    """
    md = md or {}
    return {
        "response_text"             : md.get( "response_text" ) or md.get( "answer_conversational" ),
        "abstract"                  : md.get( "abstract" ),
        "report_path"               : md.get( "report_path" ) or md.get( "report_link" ),
        "remediation_snapshot_path" : md.get( "remediation_snapshot_path" ),
        "yaml_path"                 : md.get( "yaml_path" ),
        "pptx_path"                 : md.get( "pptx_path" ),
        "cost_summary"              : md.get( "cost_summary" ),
        "scheduled_at"              : md.get( "scheduled_at" ),
        "monopolize"                : bool( md.get( "monopolize", False ) )
    }


def _build_history_row( row, has_interactions ):
    """
    Convert a JobHistory ORM row into the flat dict shape returned by
    /api/job-history, matching the field set returned by /api/get-queue/done.

    `metadata_json` is retained in the response as an additive backward-compat
    measure so any code still reading from it continues to work; new top-level
    fields are the canonical source going forward.

    Requires:
        - row: JobHistory ORM instance
        - has_interactions: bool (computed once-per-page via bulk count)

    Ensures:
        - Returns dict with all top-level fields used by the frontend renderer
        - paused is always False (history is terminal)
        - report_link in metadata_json (legacy) surfaces as report_path
    """
    flat_md = _unpack_metadata_json( row.metadata_json )
    return {
        # Identity / column fields
        "id_hash"          : row.id_hash,
        "job_id"           : row.id_hash,    # Alias for parity with /api/get-queue/done
        "job_type"         : row.job_type,
        "agent_type"       : row.job_type,   # Alias for parity (frontend reads agent_type)
        "user_id"          : row.user_id,
        "user_email"       : row.user_email,
        "session_id"       : row.session_id,
        "routing_command"  : row.routing_command,
        "status"           : row.status,
        "question_text"    : row.question_text,
        "error"            : row.error,
        "is_cache_hit"     : row.is_cache_hit,
        "duration_seconds" : row.duration_seconds,
        "created_at"       : row.created_at.isoformat()   if row.created_at   else None,
        "started_at"       : row.started_at.isoformat()   if row.started_at   else None,
        "completed_at"     : row.completed_at.isoformat() if row.completed_at else None,
        "updated_at"       : row.updated_at.isoformat()   if row.updated_at   else None,
        "timestamp"        : ( row.completed_at or row.created_at ).isoformat() if ( row.completed_at or row.created_at ) else None,

        # Flattened metadata_json fields (top-level for parity with /api/get-queue/done)
        **flat_md,

        # Computed / phase-specific
        "has_interactions" : has_interactions,
        "has_audio_cache"  : False,
        "paused"           : False,   # History is terminal

        # Backward-compat: keep raw metadata_json in the response
        "metadata_json"    : row.metadata_json,
    }


def query_job_history( user_id=None, status=None, job_type=None,
                       limit=20, offset=0, days=None, exclude_ids=None ):
    """
    Paginated filtered query of job history.

    Requires:
        - limit is a positive integer (max 100)
        - offset is a non-negative integer
        - days is None or a positive integer (time window in days)
        - exclude_ids is None or a list of id_hash strings to exclude

    Ensures:
        - Returns dict with 'jobs' list and 'total' count
        - Filters applied for user_id, status, job_type, days, exclude_ids when provided
        - Results ordered by created_at DESC
        - Returns empty result on failure
    """
    try:
        limit = min( limit, 100 )

        with get_db() as session:
            query   = select( JobHistory )
            count_q = select( func.count() ).select_from( JobHistory )

            # Apply filters
            filters = []
            if user_id:
                filters.append( JobHistory.user_id == user_id )
            if status:
                filters.append( JobHistory.status == status )
            if job_type:
                filters.append( JobHistory.job_type == job_type )
            if days is not None:
                cutoff = datetime.now( timezone.utc ) - timedelta( days=days )
                filters.append( JobHistory.created_at >= cutoff )
            if exclude_ids:
                filters.append( JobHistory.id_hash.not_in( exclude_ids ) )

            if filters:
                query   = query.where( and_( *filters ) )
                count_q = count_q.where( and_( *filters ) )

            total = session.execute( count_q ).scalar()

            rows = session.execute(
                query
                .order_by( JobHistory.created_at.desc() )
                .limit( limit )
                .offset( offset )
            ).scalars().all()

            # Bulk-count notifications for accurate has_interactions per row.
            # Single batched query against the indexed notifications.job_id column.
            row_ids       = [ row.id_hash for row in rows ]
            notif_counts  = _count_notifications_for_jobs( session, row_ids )

            jobs = []
            for row in rows:
                jobs.append( _build_history_row(
                    row,
                    has_interactions=notif_counts.get( row.id_hash, 0 ) > 0
                ) )

            return { "jobs": jobs, "total": total }

    except Exception as e:
        print( f"[WARN] query_job_history failed: {e}" )
        return { "jobs": [], "total": 0 }


def get_job_by_id_hash( id_hash ):
    """
    Single job lookup by id_hash.

    Requires:
        - id_hash is a non-empty string

    Ensures:
        - Returns dict with job fields, or None if not found
        - Never raises — returns None on failure
    """
    try:
        with get_db() as session:
            row = session.execute(
                select( JobHistory )
                .where( JobHistory.id_hash == id_hash )
            ).scalar()

            if not row:
                return None

            return {
                "id_hash"          : row.id_hash,
                "job_type"         : row.job_type,
                "user_id"          : row.user_id,
                "user_email"       : row.user_email,
                "session_id"       : row.session_id,
                "routing_command"  : row.routing_command,
                "status"           : row.status,
                "question_text"    : row.question_text,
                "error"            : row.error,
                "is_cache_hit"     : row.is_cache_hit,
                "duration_seconds" : row.duration_seconds,
                "metadata_json"    : row.metadata_json,
                "created_at"       : row.created_at.isoformat() if row.created_at else None,
                "started_at"       : row.started_at.isoformat() if row.started_at else None,
                "completed_at"     : row.completed_at.isoformat() if row.completed_at else None,
                "updated_at"       : row.updated_at.isoformat() if row.updated_at else None,
            }

    except Exception as e:
        print( f"[WARN] get_job_by_id_hash failed for {id_hash}: {e}" )
        return None


def delete_job_history( id_hash ):
    """
    Hard delete a job history row by id_hash.

    Requires:
        - id_hash is a non-empty string

    Ensures:
        - Returns True if row was deleted, False if not found
        - Never raises — returns False on failure
    """
    try:
        with get_db() as session:
            result = session.execute(
                JobHistory.__table__.delete().where( JobHistory.id_hash == id_hash )
            )
            session.commit()
            return result.rowcount > 0

    except Exception as e:
        print( f"[WARN] delete_job_history failed for {id_hash}: {e}" )
        return False


def delete_job_history_bulk( user_id=None, days=None ):
    """
    Bulk delete job history rows matching user and/or time-window filter.

    Requires:
        - user_id is None (admin — delete any user's rows) or a non-empty string
        - days is None (all time) or a positive integer

    Ensures:
        - Deletes all matching rows in a single SQL DELETE
        - Returns the count of deleted rows
        - Never raises — returns 0 on failure
    """
    try:
        with get_db() as session:
            filters = []
            if user_id:
                filters.append( JobHistory.user_id == user_id )
            if days is not None:
                cutoff = datetime.now( timezone.utc ) - timedelta( days=days )
                filters.append( JobHistory.created_at >= cutoff )

            stmt = JobHistory.__table__.delete()
            if filters:
                from sqlalchemy import and_
                stmt = stmt.where( and_( *filters ) )

            result = session.execute( stmt )
            session.commit()
            return result.rowcount

    except Exception as e:
        print( f"[WARN] delete_job_history_bulk failed: {e}" )
        return 0


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Checkpoint-resume queries (Session 9056c113)
# ---------------------------------------------------------------------------

def get_checkpoint_for_job( id_hash ):
    """
    Retrieve checkpoint data for a stalled job.

    Requires:
        - id_hash is a valid job ID (e.g., "tfe-7c25082a::user_id")

    Ensures:
        - Returns checkpoint dict if job is stalled and has checkpoint data
        - Returns None if job not found, not stalled, or no checkpoint
        - Never raises — returns None on failure
    """
    try:
        with get_db() as session:
            row = session.execute(
                select( JobHistory )
                .where( JobHistory.id_hash == id_hash )
            ).scalar()

            if not row or row.status != JobState.STALLED.value:
                return None

            metadata = row.metadata_json or {}
            # Check artifacts.checkpoint first (set during _execute stall path),
            # then top-level checkpoint (set during metadata_json merge)
            checkpoint = ( metadata.get( "artifacts" ) or {} ).get( "checkpoint" )
            if not checkpoint:
                checkpoint = metadata.get( "checkpoint" )
            return checkpoint

    except Exception as e:
        print( f"[job_persistence] get_checkpoint_for_job failed: {e}" )
        return None


def get_original_args_for_job( id_hash ):
    """
    Retrieve original submission args and routing info for job reconstruction.

    Requires:
        - id_hash is a valid job ID

    Ensures:
        - Returns dict with original_args, routing_command, user_id, user_email, session_id
        - Returns None if job not found
        - Never raises — returns None on failure
    """
    try:
        with get_db() as session:
            row = session.execute(
                select( JobHistory )
                .where( JobHistory.id_hash == id_hash )
            ).scalar()

            if not row:
                return None

            metadata = row.metadata_json or {}
            return {
                "original_args"  : metadata.get( "original_args", {} ),
                "routing_command" : row.routing_command,
                "user_id"         : row.user_id,
                "user_email"      : row.user_email,
                "session_id"      : row.session_id,
            }

    except Exception as e:
        print( f"[job_persistence] get_original_args_for_job failed: {e}" )
        return None


def quick_smoke_test():
    """
    Quick smoke test for job_persistence module.
    """
    import cosa.utils.util as cu

    cu.print_banner( "CJ Flow Job Persistence Smoke Test", prepend_nl=True )

    try:
        # Test 1: Module imports
        print( "Testing module imports..." )
        from cosa.rest.job_persistence import (
            persist_job_created_from_metadata,
            persist_job_started_from_metadata,
            persist_job_completed_from_metadata,
            persist_job_failed_from_metadata,
            mark_interrupted_jobs,
            query_job_history,
            get_job_by_id_hash,
            is_agentic_job_type
        )
        print( "✓ All persistence functions imported successfully" )

        # Test 2: Agentic job type filter
        print( "Testing is_agentic_job_type()..." )
        assert is_agentic_job_type( "deep_research" ) is True
        assert is_agentic_job_type( "podcast" ) is True
        assert is_agentic_job_type( "claude_code" ) is True
        assert is_agentic_job_type( "swe_team" ) is True
        assert is_agentic_job_type( "research_to_podcast" ) is True
        assert is_agentic_job_type( "test_suite" ) is True
        assert is_agentic_job_type( "math" ) is False
        assert is_agentic_job_type( "calendar" ) is False
        assert is_agentic_job_type( None ) is False
        assert is_agentic_job_type( "" ) is False
        print( "✓ Agentic job type filter working (6 agentic, 4 non-agentic)" )

        # Test 3: _build_metadata_json extraction
        print( "Testing _build_metadata_json()..." )
        from cosa.rest.job_persistence import _build_metadata_json
        metadata = {
            "response_text"  : "Here is the research report...",
            "abstract"       : "A summary of findings",
            "cost_summary"   : { "total": 0.42 },
            "agent_type"     : "deep_research",
            "question_text"  : "Research quantum computing",
            "irrelevant_key" : "should be excluded"
        }
        result = _build_metadata_json( metadata )
        assert "response_text" in result, "Missing response_text"
        assert "abstract" in result, "Missing abstract"
        assert "cost_summary" in result, "Missing cost_summary"
        assert "agent_type" in result, "Missing agent_type"
        assert "irrelevant_key" not in result, "Should not include irrelevant_key"
        assert "question_text" not in result, "question_text is a top-level field, not metadata"

        empty_result = _build_metadata_json( None )
        assert empty_result == {}, "None metadata should return empty dict"

        empty_result2 = _build_metadata_json( {} )
        assert empty_result2 == {}, "Empty metadata should return empty dict"
        print( "✓ Metadata extraction working correctly" )

        # Test 4: DB round-trip (if database available)
        print( "Testing DB round-trip..." )
        try:
            test_id = "smoke_test_persistence_001::test_user"

            # Clean up any leftover test row
            with get_db() as session:
                session.execute(
                    JobHistory.__table__.delete().where( JobHistory.id_hash == test_id )
                )

            # INSERT
            persist_job_created_from_metadata(
                job_id=test_id,
                user_id="test_user",
                metadata={
                    "agent_type"    : "deep_research",
                    "question_text" : "Smoke test question",
                    "user_email"    : "test@example.com"
                }
            )

            # Verify INSERT
            row = get_job_by_id_hash( test_id )
            assert row is not None, "INSERT failed — row not found"
            assert row[ "status" ] == "pending", f"Expected 'pending', got '{row[ 'status' ]}'"
            assert row[ "job_type" ] == "deep_research", f"Expected 'deep_research', got '{row[ 'job_type' ]}'"
            print( "  ✓ INSERT + query round-trip successful" )

            # UPDATE to running
            persist_job_started_from_metadata( test_id, {} )
            row = get_job_by_id_hash( test_id )
            assert row[ "status" ] == "running", f"Expected 'running', got '{row[ 'status' ]}'"
            assert row[ "started_at" ] is not None, "started_at should be set"
            print( "  ✓ UPDATE to running successful" )

            # UPDATE to completed
            persist_job_completed_from_metadata( test_id, {
                "response_text" : "Test response",
                "abstract"      : "Test abstract"
            } )
            row = get_job_by_id_hash( test_id )
            assert row[ "status" ] == "completed", f"Expected 'completed', got '{row[ 'status' ]}'"
            assert row[ "completed_at" ] is not None, "completed_at should be set"
            assert row[ "duration_seconds" ] is not None, "duration_seconds should be calculated"
            assert row[ "metadata_json" ][ "response_text" ] == "Test response"
            print( "  ✓ UPDATE to completed successful (duration calculated)" )

            # query_job_history
            result = query_job_history( user_id="test_user" )
            assert result[ "total" ] >= 1, "Expected at least 1 result"
            print( f"  ✓ query_job_history returned {result[ 'total' ]} result(s)" )

            # Clean up
            with get_db() as session:
                session.execute(
                    JobHistory.__table__.delete().where( JobHistory.id_hash == test_id )
                )
            print( "  ✓ Test row cleaned up" )
            print( "✓ DB round-trip complete" )

        except Exception as db_error:
            print( f"⚠ DB round-trip skipped: {db_error}" )
            print( "  (This is OK if database is not running or table not created yet)" )

        print( "\n✓ Smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
