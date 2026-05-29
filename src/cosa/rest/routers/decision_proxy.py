"""
Decision proxy ratification API endpoints.

Provides REST endpoints for viewing pending decisions and ratifying
(approving/rejecting) them. Used by the morning ratification UI workflow.

Dependency Rule:
    This module NEVER imports from notification_proxy or swe_team.
"""

from fastapi import APIRouter, Query, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime, timezone
import uuid

from ..db.database import get_db
from ..db.repositories.proxy_decision_repository import (
    ProxyDecisionRepository,
    TrustStateRepository,
)
from ..auth import get_current_user

router = APIRouter( prefix="/api/proxy", tags=[ "decision-proxy" ] )


# =============================================================================
# In-memory proxy batch state (resets on server restart — fresh batch)
# =============================================================================

_proxy_batch_state = {
    "hex"        : uuid.uuid4().hex[ :8 ],   # Stable hex per server lifetime
    "generation" : 1,                          # Monotonic batch counter
}


def get_current_batch_id() -> str:
    """
    Return current proxy batch progress_group_id.

    Requires:
        - _proxy_batch_state is initialized

    Ensures:
        - Returns string in format pr-{8hex}-{N}
    """
    return f"pr-{_proxy_batch_state[ 'hex' ]}-{_proxy_batch_state[ 'generation' ]}"


def acknowledge_batch() -> dict:
    """
    Retire current batch and start a new one.

    Requires:
        - _proxy_batch_state is initialized

    Ensures:
        - Increments generation counter
        - Returns dict with retired_batch and new_batch IDs
    """
    old_id = get_current_batch_id()
    _proxy_batch_state[ "generation" ] += 1
    new_id = get_current_batch_id()
    return { "retired_batch": old_id, "new_batch": new_id }


@router.post(
    "/acknowledge",
    summary     = "Acknowledge proxy batch",
    description = "Retire current proxy notification batch and start a new one."
)
async def acknowledge_proxy_batch():
    """
    Retire the current proxy notification batch and start a new one.

    Requires:
        - Nothing (stateless — just increments the counter)

    Ensures:
        - Returns the retired batch ID and the new batch ID
    """
    result = acknowledge_batch()
    return { "status": "success", **result }


@router.get(
    "/batch-id",
    summary     = "Get proxy batch ID",
    description = "Return the current proxy batch progress_group_id."
)
async def get_proxy_batch_id():
    """
    Return the current proxy batch progress_group_id.

    Ensures:
        - Returns dict with status and batch_id
    """
    return { "status": "success", "batch_id": get_current_batch_id() }


@router.get(
    "/pending/{user_email}",
    summary     = "Get pending decisions",
    description = "Retrieve pending decisions awaiting ratification for a user with optional domain/category filter."
)
async def get_pending_decisions(
    user_email: str,
    domain: Optional[str] = Query( None, description="Filter by domain (e.g., 'swe')" ),
    category: Optional[str] = Query( None, description="Filter by category" ),
    limit: int = Query( 100, description="Maximum number of decisions to return" )
):
    """
    Get pending decisions awaiting ratification for a user.

    Requires:
        - user_email is a valid email address

    Ensures:
        - Returns list of pending decisions with full context
        - Applies optional domain and category filters
        - Ordered by created_at ascending (oldest first)

    Raises:
        - HTTPException with 500 for query failures

    Args:
        user_email: User's email address
        domain: Optional domain filter
        category: Optional category filter
        limit: Maximum results

    Returns:
        Dict with pending decisions and summary
    """
    try:
        with get_db() as session:
            repo = ProxyDecisionRepository( session )

            decisions = repo.get_pending( domain=domain, category=category, limit=limit )
            summary   = repo.get_pending_summary( domain=domain )

            result = []
            for d in decisions:
                result.append( {
                    "id"                  : str( d.id ),
                    "notification_id"     : d.notification_id,
                    "domain"              : d.domain,
                    "category"            : d.category,
                    "question"            : d.question,
                    "sender_id"           : d.sender_id,
                    "action"              : d.action,
                    "decision_value"      : d.decision_value,
                    "confidence"          : d.confidence,
                    "trust_level"         : d.trust_level,
                    "reason"              : d.reason,
                    "ratification_state"  : d.ratification_state,
                    "data_origin"         : d.data_origin,
                    "metadata_json"       : d.metadata_json,
                    "created_at"          : d.created_at.isoformat() if d.created_at else None,
                } )

            print( f"[DECISION PROXY] Returning {len( result )} pending decisions for {user_email}" )

            return {
                "status"    : "success",
                "decisions" : result,
                "summary"   : summary,
            }

    except Exception as e:
        print( f"[DECISION PROXY] Error getting pending decisions: {str( e )}" )
        raise HTTPException(
            status_code = 500,
            detail      = f"Failed to get pending decisions: {str( e )}"
        )


@router.post(
    "/ratify/{decision_id}",
    summary     = "Ratify decision",
    description = "Approve or reject a pending decision. Updates ratification state and trust counters."
)
async def ratify_decision(
    decision_id: str,
    approved: bool = Query( ..., description="True to approve, False to reject" ),
    feedback: str = Query( "", description="Optional feedback text" ),
    user_email: str = Query( ..., description="Email of the ratifying user" )
):
    """
    Ratify (approve or reject) a pending decision.

    Requires:
        - decision_id is a valid UUID
        - approved is a boolean
        - user_email is a valid email address

    Ensures:
        - Decision ratification_state updated to "approved" or "rejected"
        - ratified_by and ratified_at set
        - Trust state counters updated
        - Returns updated decision

    Raises:
        - HTTPException with 404 if decision not found
        - HTTPException with 400 if already ratified
        - HTTPException with 500 for update failures

    Args:
        decision_id: UUID of the decision
        approved: True to approve, False to reject
        feedback: Optional feedback text
        user_email: Ratifying user's email

    Returns:
        Dict with ratification result
    """
    try:
        with get_db() as session:
            decision_repo = ProxyDecisionRepository( session )
            trust_repo    = TrustStateRepository( session )

            # Look up the decision
            decision = decision_repo.get_by_id( uuid.UUID( decision_id ) )
            if not decision:
                raise HTTPException(
                    status_code = 404,
                    detail      = f"Decision {decision_id} not found"
                )

            # Check if already ratified
            if decision.ratification_state in ( "approved", "rejected" ):
                raise HTTPException(
                    status_code = 400,
                    detail      = f"Decision already ratified: {decision.ratification_state}"
                )

            # Ratify
            updated = decision_repo.ratify(
                decision_id = uuid.UUID( decision_id ),
                approved    = approved,
                ratified_by = user_email,
                feedback    = feedback
            )

            # Update trust state
            trust_repo.update_after_ratification(
                user_email = user_email,
                domain     = decision.domain,
                category   = decision.category,
                approved   = approved
            )

            action_word = "approved" if approved else "rejected"
            print( f"[DECISION PROXY] Decision {decision_id} {action_word} by {user_email}" )

            return {
                "status"              : "success",
                "decision_id"         : decision_id,
                "ratification_state"  : updated.ratification_state,
                "ratified_by"         : user_email,
                "ratified_at"         : updated.ratified_at.isoformat() if updated.ratified_at else None,
                "feedback"            : feedback,
                "domain"              : updated.domain,
                "category"            : updated.category,
            }

    except HTTPException:
        raise
    except Exception as e:
        print( f"[DECISION PROXY] Error ratifying decision {decision_id}: {str( e )}" )
        raise HTTPException(
            status_code = 500,
            detail      = f"Failed to ratify decision: {str( e )}"
        )


@router.delete(
    "/decision/{decision_id}",
    summary     = "Delete pending decision",
    description = "Hard-delete a decision in pending state. Approved/rejected decisions are protected."
)
async def delete_decision(
    decision_id: str,
    user_email: str = Query( ..., description="Email of the user performing deletion (audit)" )
):
    """
    Delete a pending decision permanently.

    Only decisions in "pending" state can be deleted. Approved/rejected
    decisions are protected. Does not affect trust state counters.

    Requires:
        - decision_id is a valid UUID
        - user_email is a valid email address

    Ensures:
        - Decision is hard-deleted from the database
        - Returns success with decision_id and deleted_by

    Raises:
        - HTTPException with 404 if decision not found
        - HTTPException with 400 if decision is not pending
        - HTTPException with 500 for unexpected failures

    Args:
        decision_id: UUID of the decision to delete
        user_email: Email of the user (for audit logging)

    Returns:
        Dict with deletion result
    """
    try:
        with get_db() as session:
            repo = ProxyDecisionRepository( session )

            result = repo.delete_pending( uuid.UUID( decision_id ) )

            if not result:
                raise HTTPException(
                    status_code = 404,
                    detail      = f"Decision {decision_id} not found"
                )

            print( f"[DECISION PROXY] Decision {decision_id} deleted by {user_email}" )

            return {
                "status"      : "success",
                "decision_id" : decision_id,
                "deleted_by"  : user_email,
            }

    except HTTPException:
        raise
    except ValueError as e:
        print( f"[DECISION PROXY] Cannot delete decision {decision_id}: {str( e )}" )
        raise HTTPException(
            status_code = 400,
            detail      = str( e )
        )
    except Exception as e:
        print( f"[DECISION PROXY] Error deleting decision {decision_id}: {str( e )}" )
        raise HTTPException(
            status_code = 500,
            detail      = f"Failed to delete decision: {str( e )}"
        )


@router.get(
    "/trust/{user_email}",
    summary     = "Get trust state",
    description = "Return all trust state records for a user across domains and categories."
)
async def get_trust_state(
    user_email: str,
    domain: Optional[str] = Query( None, description="Filter by domain" )
):
    """
    Get trust state for a user across all domains/categories.

    Requires:
        - user_email is a valid email address

    Ensures:
        - Returns all trust states for the user
        - Applies optional domain filter
        - Ordered by domain, then category

    Raises:
        - HTTPException with 500 for query failures

    Args:
        user_email: User's email address
        domain: Optional domain filter

    Returns:
        Dict with trust states
    """
    try:
        with get_db() as session:
            repo = TrustStateRepository( session )

            states = repo.get_all_for_user( user_email, domain=domain )

            result = []
            for s in states:
                result.append( {
                    "id"                    : str( s.id ),
                    "domain"                : s.domain,
                    "category"              : s.category,
                    "trust_level"           : s.trust_level,
                    "total_decisions"       : s.total_decisions,
                    "successful_decisions"  : s.successful_decisions,
                    "rejected_decisions"    : s.rejected_decisions,
                    "circuit_breaker_state" : s.circuit_breaker_state,
                    "created_at"            : s.created_at.isoformat() if s.created_at else None,
                    "updated_at"            : s.updated_at.isoformat() if s.updated_at else None,
                } )

            print( f"[DECISION PROXY] Returning {len( result )} trust states for {user_email}" )

            return {
                "status"       : "success",
                "user_email"   : user_email,
                "trust_states" : result,
            }

    except Exception as e:
        print( f"[DECISION PROXY] Error getting trust state for {user_email}: {str( e )}" )
        raise HTTPException(
            status_code = 500,
            detail      = f"Failed to get trust state: {str( e )}"
        )


@router.get(
    "/decisions/{domain}/{category}",
    summary     = "Get decisions by domain",
    description = "Return decision history for a specific domain and category combination."
)
async def get_decisions_by_domain_category(
    domain: str,
    category: str,
    limit: int = Query( 50, description="Maximum number of decisions to return" )
):
    """
    Get decision history for a specific domain and category.

    Requires:
        - domain is a valid domain identifier
        - category is a valid category name

    Ensures:
        - Returns decisions matching domain+category
        - Ordered by created_at descending (newest first)

    Raises:
        - HTTPException with 500 for query failures

    Args:
        domain: Domain identifier (e.g., "swe")
        category: Decision category (e.g., "testing")
        limit: Maximum results

    Returns:
        Dict with decisions
    """
    try:
        with get_db() as session:
            repo = ProxyDecisionRepository( session )

            decisions = repo.get_by_domain_category( domain, category, limit=limit )

            result = []
            for d in decisions:
                result.append( {
                    "id"                  : str( d.id ),
                    "notification_id"     : d.notification_id,
                    "question"            : d.question,
                    "sender_id"           : d.sender_id,
                    "action"              : d.action,
                    "decision_value"      : d.decision_value,
                    "confidence"          : d.confidence,
                    "trust_level"         : d.trust_level,
                    "reason"              : d.reason,
                    "ratification_state"  : d.ratification_state,
                    "created_at"          : d.created_at.isoformat() if d.created_at else None,
                } )

            return {
                "status"    : "success",
                "domain"    : domain,
                "category"  : category,
                "decisions" : result,
            }

    except Exception as e:
        print( f"[DECISION PROXY] Error getting decisions for {domain}/{category}: {str( e )}" )
        raise HTTPException(
            status_code = 500,
            detail      = f"Failed to get decisions: {str( e )}"
        )


# =============================================================================
# Trust Mode Hot-Reload (Phase 8)
# =============================================================================

VALID_TRUST_MODES = ( "disabled", "shadow", "suggest", "active" )


class TrustModeUpdateRequest( BaseModel ):
    """Request body for updating trust mode at runtime."""
    mode   : str = Field( ..., pattern=r'^(disabled|shadow|suggest|active)$' )
    domain : str = Field( "swe", description="Domain (currently only 'swe')" )


def get_run_queue():
    """
    Dependency to get the running job queue from main module.

    Requires:
        - fastapi_app.main module is available
        - main_module has jobs_run_queue attribute

    Ensures:
        - Returns RunningFifoQueue instance

    Returns:
        RunningFifoQueue: The run queue instance
    """
    import fastapi_app.main as main_module
    return main_module.jobs_run_queue


def get_config_mgr():
    """
    Dependency to get ConfigurationManager from main module.

    Returns:
        ConfigurationManager: The configuration manager instance
    """
    import fastapi_app.main as main_module
    return main_module.config_mgr


def _find_running_swe_job( run_queue ):
    """
    Find the first running SweTeamJob in the run queue.

    Requires:
        - run_queue has get_all_jobs() method

    Ensures:
        - Returns SweTeamJob instance or None
        - Only returns jobs with a live _orchestrator reference

    Args:
        run_queue: RunningFifoQueue instance

    Returns:
        SweTeamJob or None
    """
    from cosa.agents.swe_team.job import SweTeamJob

    if run_queue is None:
        return None

    for job in run_queue.get_all_jobs():
        if isinstance( job, SweTeamJob ) and job._orchestrator is not None:
            return job

    return None


@router.get(
    "/mode",
    summary     = "Get trust mode",
    description = "Return current effective trust mode from INI config and any running job orchestrator."
)
async def get_trust_mode(
    current_user: dict = Depends( get_current_user ),
    run_queue=Depends( get_run_queue ),
    config_mgr=Depends( get_config_mgr )
):
    """
    Get current effective trust mode from INI config and running orchestrator.

    Requires:
        - Authenticated user

    Ensures:
        - Returns INI mode, running mode (if any), and effective mode
        - effective = running mode if orchestrator exists, else INI mode

    Returns:
        Dict with ini_mode, running_mode, effective, has_running_job
    """
    # INI config mode
    ini_mode = "shadow"
    try:
        ini_mode = config_mgr.get( "swe team trust mode", default="shadow" )
    except Exception:
        pass

    # Running orchestrator mode
    running_mode    = None
    has_running_job = False
    swe_job         = _find_running_swe_job( run_queue )

    if swe_job and swe_job._orchestrator and swe_job._orchestrator.proxy:
        running_mode    = swe_job._orchestrator.proxy.trust_mode
        has_running_job = True

    effective = running_mode if running_mode else ini_mode

    return {
        "status"          : "success",
        "ini_mode"        : ini_mode,
        "running_mode"    : running_mode,
        "effective"       : effective,
        "has_running_job" : has_running_job,
    }


@router.put(
    "/mode",
    summary     = "Update trust mode",
    description = "Hot-reload trust mode at runtime. Persists to INI and updates running proxy if available."
)
async def update_trust_mode(
    request_body: TrustModeUpdateRequest,
    current_user: dict = Depends( get_current_user ),
    run_queue=Depends( get_run_queue ),
    config_mgr=Depends( get_config_mgr )
):
    """
    Update trust mode at runtime for running orchestrator and/or INI config.

    Requires:
        - Authenticated user
        - request_body.mode is one of: disabled, shadow, suggest, active

    Ensures:
        - If running SWE job exists with proxy: updates proxy.trust_mode immediately
        - Always updates INI config for persistence (next job uses new mode)
        - Returns status indicating whether running job was updated or queued for next

    Args:
        request_body: TrustModeUpdateRequest with mode and domain

    Returns:
        Dict with status, old_mode, new_mode, target
    """
    new_mode = request_body.mode
    domain   = request_body.domain

    if new_mode not in VALID_TRUST_MODES:
        raise HTTPException( status_code=422, detail=f"Invalid mode: {new_mode}" )

    # Update INI config for persistence
    old_ini_mode = "shadow"
    try:
        old_ini_mode = config_mgr.get( "swe team trust mode", default="shadow" )
        config_mgr.put( "swe team trust mode", new_mode )
    except Exception as e:
        print( f"[DECISION PROXY] Warning: Failed to update INI config: {e}" )

    # Try to hot-reload running orchestrator
    swe_job = _find_running_swe_job( run_queue )

    if swe_job and swe_job._orchestrator and swe_job._orchestrator.proxy:
        old_mode = swe_job._orchestrator.proxy.trust_mode
        swe_job._orchestrator.proxy.trust_mode = new_mode

        print( f"[DECISION PROXY] Trust mode hot-reloaded: {old_mode} → {new_mode} (job {swe_job.id_hash})" )

        return {
            "status"   : "updated",
            "old_mode" : old_mode,
            "new_mode" : new_mode,
            "target"   : "running",
            "job_id"   : swe_job.id_hash,
        }

    print( f"[DECISION PROXY] Trust mode queued: {old_ini_mode} → {new_mode} (no running job)" )

    return {
        "status"   : "queued",
        "old_mode" : old_ini_mode,
        "new_mode" : new_mode,
        "target"   : "next_job",
        "message"  : "No running SWE job — mode will apply to next job",
    }
