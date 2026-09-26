"""
Decision proxy ratification API endpoints.

Provides REST endpoints for viewing pending decisions and ratifying
(approving/rejecting) them. Used by the morning ratification UI workflow.

Dependency Rule:
    This module NEVER imports from notification_proxy or swe_team.
"""

from fastapi import APIRouter, Query, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import Annotated, Optional, Dict, Any
from datetime import datetime, timezone
import uuid

from ..db.database import get_db
from ..db.repositories.proxy_decision_repository import (
    ProxyDecisionRepository,
    TrustStateRepository,
)
from ..auth import get_current_user
from ..middleware.api_key_auth import require_api_key_or_jwt
from ..middleware.path_identity import require_path_identity_owner, require_query_identity_owner

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
    # 🔴 CREDENTIAL REQUIRED SINCE 2026-09-26 (row 44d8e89c). MEASURED AT THE PATH: a
    # TestClient call carrying no credential returned 200 and reached the handler. Row
    # 2d6f2221 gated the two routes naming a user in their PATH and left this one for a
    # separate decision, which this row rules on: `require_api_key_or_jwt`, so any valid
    # key or token is admitted and none is not.
    dependencies = [ Depends( require_api_key_or_jwt ) ],
    responses    = { 401 : { "description": "Unauthorized — no valid credential" } },
    description = "Retire current proxy notification batch and start a new one. Requires a credential."
)
async def acknowledge_proxy_batch():
    """
    Retire the current proxy notification batch and start a new one.

    Requires:
        - a valid credential (route-level `require_api_key_or_jwt`)

    Ensures:
        - Returns the retired batch ID and the new batch ID

    🔴 NO OWNER CHECK, AND THAT IS A FINDING RATHER THAN AN OMISSION. Row 44d8e89c ruled an
    owner check onto this route alongside ratify and delete. There is nothing here to own:
    `_proxy_batch_state` is a single process-global counter, not a per-user record, and this
    route takes no identity parameter in its path, query or body — both callers
    (`notifications.js` and `ApiClient.acknowledgeProxy`) POST it body-less. Inventing a
    required `user_email` would break both of them and would gate a counter that is shared
    anyway. So the credential is the whole available fix, and the residue is real: any
    credentialed caller can retire another user's displayed batch. Making the batch per-user
    is a design change, not an authorization fix.
    """
    result = acknowledge_batch()
    return { "status": "success", **result }


@router.get(
    "/batch-id",
    summary     = "Get proxy batch ID",
    # 🔴 CREDENTIAL REQUIRED SINCE 2026-09-26 (row 44d8e89c). MEASURED AT THE PATH: a
    # TestClient call carrying no credential returned 200 and reached the handler. Row
    # 2d6f2221 gated the two routes naming a user in their PATH and left this one for a
    # separate decision, which this row rules on: `require_api_key_or_jwt`, so any valid
    # key or token is admitted and none is not.
    dependencies = [ Depends( require_api_key_or_jwt ) ],
    responses    = { 401 : { "description": "Unauthorized — no valid credential" } },
    description = "Return the current proxy batch progress_group_id. Requires a credential."
)
async def get_proxy_batch_id():
    """
    Return the current proxy batch progress_group_id.

    Requires:
        - a valid credential (route-level `require_api_key_or_jwt`)

    Ensures:
        - Returns dict with status and batch_id

    ⚠️ ITS SERVER-TO-SERVER CALLER HAD TO BE FIXED IN THE SAME PASS. Row 2d6f2221 left this
    route open BECAUSE of that caller — `swe_team/orchestrator.py`'s proxy-summary
    notification fetched it with no credential, so gating it would have broken the SWE
    orchestrator. That caller now sends its API key; see
    `SweTeamOrchestrator._emit_proxy_summary_notification`.
    """
    return { "status": "success", "batch_id": get_current_batch_id() }


@router.get(
    "/pending/{user_email}",
    summary     = "Get pending decisions",
    # 🔴 OWNER-ONLY SINCE 2026-09-25 (row 2d6f2221). MEASURED AT THE PATH, not inferred
    # from the decorator: a TestClient call carrying NO credential returned 200 and
    # reached the handler. `main.py` includes this router with no `dependencies=`, and
    # the only middleware is CORS plus a security-header pass, so anyone who could reach
    # the port could read any user's data by writing their email into the URL.
    # `require_path_identity_owner` (from d90baf3d) refuses an absent or bad credential
    # with 401 via `require_api_key_or_jwt`, then 403s a caller who is not the user named
    # in the path. Owner-only, no admin bypass — Mr. Radio's ruling on d90baf3d.
    dependencies = [ Depends( require_path_identity_owner ) ],
    responses    = {
        401 : { "description": "Unauthorized — no valid credential" },
        403 : { "description": "Forbidden — the path names a different user" }
    },
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
    # 🔴 OWNER-ONLY SINCE 2026-09-26 (row 44d8e89c). MEASURED AT THE PATH: with no credential
    # at all this route reached the DATABASE. A BARE call answered 422 for the missing
    # `user_email`, which reads like a refusal and is not one — well formed, it returned
    # "Decision <id> not found", a database lookup by an anonymous caller. Because
    # `user_email` sits in the QUERY string rather than the path, `require_path_identity_owner`
    # cannot cover it: that guard reads `request.path_params` and deliberately raises 500 for a
    # route naming no user in its path. `require_query_identity_owner` is the sibling that
    # reads the query — same 401 via `require_api_key_or_jwt`, same 403 for a caller who is not
    # the user named. A route-level Depends raising 401 preempts the handler's 422, measured.
    responses    = {
        401 : { "description": "Unauthorized — no valid credential" },
        403 : { "description": "Forbidden — the query names a different user" }
    },
    description = "Approve or reject a pending decision. Updates ratification state and trust counters. Owner-only."
)
async def ratify_decision(
    decision_id: str,
    audit_identity: Annotated[ str, Depends( require_query_identity_owner ) ],
    approved: bool = Query( ..., description="True to approve, False to reject" ),
    feedback: str = Query( "", description="Optional feedback text" ),
    user_email: str = Query( ..., description="Email of the ratifying user — must be the authenticated caller" )
):
    """
    Ratify (approve or reject) a pending decision.

    Requires:
        - decision_id is a valid UUID
        - approved is a boolean
        - user_email names the authenticated caller (enforced by the route-level guard)

    Ensures:
        - Decision ratification_state updated to "approved" or "rejected"
        - ratified_by and ratified_at set — from `audit_identity`, NOT from `user_email`
        - Trust state counters updated, keyed on `audit_identity`
        - Returns updated decision

    Raises:
        - HTTPException with 404 if decision not found
        - HTTPException with 400 if already ratified
        - HTTPException with 500 for update failures

    Args:
        decision_id: UUID of the decision
        audit_identity: the caller's account email, resolved from their credential by
            `require_query_identity_owner`. This is what gets STORED. `user_email` is only the
            claim the guard checked — accepting it here would let the same person write two
            different strings (their bare user id, or their email in another case) into the
            same audit column, and before this row it let an anonymous caller write anything.
        approved: True to approve, False to reject
        feedback: Optional feedback text
        user_email: Ratifying user's email, which must be the caller's own

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
                ratified_by = audit_identity,
                feedback    = feedback
            )

            # Update trust state
            trust_repo.update_after_ratification(
                user_email = audit_identity,
                domain     = decision.domain,
                category   = decision.category,
                approved   = approved
            )

            action_word = "approved" if approved else "rejected"
            print( f"[DECISION PROXY] Decision {decision_id} {action_word} by {audit_identity}" )

            return {
                "status"              : "success",
                "decision_id"         : decision_id,
                "ratification_state"  : updated.ratification_state,
                "ratified_by"         : audit_identity,
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
    # 🔴 OWNER-ONLY SINCE 2026-09-26 (row 44d8e89c). MEASURED AT THE PATH: with no credential
    # at all this route reached the DATABASE and hard-deleted by id. A BARE call answered 422
    # for the missing `user_email`, which reads like a refusal and is not one. `user_email` sits
    # in the QUERY string, so `require_path_identity_owner` cannot cover it — see
    # `require_query_identity_owner`, its sibling that reads the query string.
    responses    = {
        401 : { "description": "Unauthorized — no valid credential" },
        403 : { "description": "Forbidden — the query names a different user" }
    },
    description = "Hard-delete a decision in pending state. Approved/rejected decisions are protected. Owner-only."
)
async def delete_decision(
    decision_id: str,
    audit_identity: Annotated[ str, Depends( require_query_identity_owner ) ],
    user_email: str = Query( ..., description="Email of the user performing deletion — must be the authenticated caller" )
):
    """
    Delete a pending decision permanently.

    Only decisions in "pending" state can be deleted. Approved/rejected
    decisions are protected. Does not affect trust state counters.

    Requires:
        - decision_id is a valid UUID
        - user_email names the authenticated caller (enforced by the route-level guard)

    Ensures:
        - Decision is hard-deleted from the database
        - Returns success with decision_id and deleted_by, taken from `audit_identity`

    Raises:
        - HTTPException with 404 if decision not found
        - HTTPException with 400 if decision is not pending
        - HTTPException with 500 for unexpected failures

    Args:
        decision_id: UUID of the decision to delete
        audit_identity: the caller's account email, resolved from their credential. This is what
            gets logged and returned as `deleted_by`; `user_email` is only the claim the guard
            checked. An audit line naming a string the caller typed records a claim, not a fact.
        user_email: Email of the user performing the deletion, which must be their own

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

            print( f"[DECISION PROXY] Decision {decision_id} deleted by {audit_identity}" )

            return {
                "status"      : "success",
                "decision_id" : decision_id,
                "deleted_by"  : audit_identity,
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
    # 🔴 OWNER-ONLY SINCE 2026-09-25 (row 2d6f2221). MEASURED AT THE PATH, not inferred
    # from the decorator: a TestClient call carrying NO credential returned 200 and
    # reached the handler. `main.py` includes this router with no `dependencies=`, and
    # the only middleware is CORS plus a security-header pass, so anyone who could reach
    # the port could read any user's data by writing their email into the URL.
    # `require_path_identity_owner` (from d90baf3d) refuses an absent or bad credential
    # with 401 via `require_api_key_or_jwt`, then 403s a caller who is not the user named
    # in the path. Owner-only, no admin bypass — Mr. Radio's ruling on d90baf3d.
    dependencies = [ Depends( require_path_identity_owner ) ],
    responses    = {
        401 : { "description": "Unauthorized — no valid credential" },
        403 : { "description": "Forbidden — the path names a different user" }
    },
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
    # 🔴 CREDENTIAL REQUIRED SINCE 2026-09-26 (row 44d8e89c). MEASURED AT THE PATH: a
    # TestClient call carrying no credential returned 200 and reached the handler. Row
    # 2d6f2221 gated the two routes naming a user in their PATH and left this one for a
    # separate decision, which this row rules on: `require_api_key_or_jwt`, so any valid
    # key or token is admitted and none is not.
    dependencies = [ Depends( require_api_key_or_jwt ) ],
    responses    = { 401 : { "description": "Unauthorized — no valid credential" } },
    description = "Return decision history for a specific domain and category combination. Requires a credential."
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
        - lupin_app.main module is available
        - main_module has jobs_run_queue attribute

    Ensures:
        - Returns RunningFifoQueue instance

    Returns:
        RunningFifoQueue: The run queue instance
    """
    import lupin_app.main as main_module
    return main_module.jobs_run_queue


def get_config_mgr():
    """
    Dependency to get ConfigurationManager from main module.

    Returns:
        ConfigurationManager: The configuration manager instance
    """
    import lupin_app.main as main_module
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
