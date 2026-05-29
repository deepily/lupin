"""
Admin Router for FastAPI.

Provides administrative endpoints for user management.
All endpoints require admin role authorization.
"""

from fastapi import APIRouter, HTTPException, status, Depends, Request, BackgroundTasks
from typing import Optional, List, Dict
from pydantic import BaseModel, Field
import traceback

from cosa.rest.auth_middleware import require_admin
from cosa.rest.admin_service import (
    list_users,
    get_user_details,
    update_user_roles,
    toggle_user_status,
    admin_reset_password,
    admin_create_user,
    admin_delete_user
)
from cosa.config.configuration_manager import ConfigurationManager
import cosa.utils.util as du

# Module-level config manager for threshold access
_config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )


# ============================================================================
# Dependencies
# ============================================================================

def get_snapshot_manager():
    """
    Dependency to get snapshot manager from main module.

    Uses the global singleton to ensure cache consistency between
    math agent writes and admin reads.

    Requires:
        - fastapi_app.main module is available
        - main_module has snapshot_mgr attribute

    Ensures:
        - Returns the global snapshot manager instance
        - Provides access to cached snapshots (same cache as math agent)

    Raises:
        - ImportError if main module not available
        - AttributeError if snapshot_mgr not found
    """
    import fastapi_app.main as main_module
    return main_module.snapshot_mgr


# ============================================================================
# Pydantic Models
# ============================================================================

class UserListResponse( BaseModel ):
    """Response model for list users endpoint."""
    users: List[Dict]
    total: int
    limit: int
    offset: int


class UserDetailsResponse( BaseModel ):
    """Response model for user details endpoint."""
    id: str
    email: str
    roles: List[str]
    email_verified: bool
    is_active: bool
    created_at: str
    last_login_at: Optional[str]
    audit_log_count: int
    failed_login_count: int


class UpdateRolesRequest( BaseModel ):
    """Request model for updating user roles."""
    roles: List[str] = Field( ..., description="List of roles to assign (admin, user)" )


class UpdateStatusRequest( BaseModel ):
    """Request model for updating user status."""
    is_active: bool = Field( ..., description="Set user active status" )


class ResetPasswordRequest( BaseModel ):
    """Request model for admin password reset."""
    reason: Optional[str] = Field( None, description="Optional reason for audit trail" )


class ResetPasswordResponse( BaseModel ):
    """Response model for password reset."""
    message: str
    temporary_password: str
    user: Dict


class MessageResponse( BaseModel ):
    """Generic message response."""
    message: str
    user: Optional[Dict] = None


class CreateUserRequest( BaseModel ):
    """Request model for admin user creation."""
    email    : str       = Field( ..., description="Email address for new user" )
    password : str       = Field( ..., description="Initial password" )
    roles    : List[str] = Field( default=["user"], description="Roles to assign (admin, user)" )


class CreateUserResponse( BaseModel ):
    """Response model for user creation."""
    message : str
    user    : Dict
    user_id : str


class DeleteUserRequest( BaseModel ):
    """Request model for admin user deletion."""
    reason : Optional[str] = Field( None, description="Reason for audit trail" )


class BatchDeleteUsersRequest( BaseModel ):
    """Request model for batch user deletion."""
    user_ids : List[str] = Field( ..., description="List of user IDs to delete (max 50)", min_length=1, max_length=50 )
    reason   : Optional[str] = Field( None, description="Reason for audit trail" )


class BatchDeleteResult( BaseModel ):
    """Result for a single user in batch delete."""
    user_id : str
    success : bool
    message : str


class BatchDeleteUsersResponse( BaseModel ):
    """Response model for batch user deletion."""
    results       : List[BatchDeleteResult]
    total_deleted : int
    total_failed  : int


# ============================================================================
# Admin Snapshots Models
# ============================================================================

class SnapshotSearchResult( BaseModel ):
    """Individual search result for solution snapshot."""
    id_hash: str = Field( ..., description="Unique identifier (MD5 hash)" )
    question_preview: str = Field( ..., description="Truncated question (100 chars)" )
    question_gist: str = Field( ..., description="Condensed semantic summary" )
    created_date: str = Field( ..., description="Creation timestamp" )
    score: float = Field( ..., description="Similarity score (0-100)" )


class SearchSnapshotsResponse( BaseModel ):
    """Response model for snapshot search endpoint."""
    results: List[SnapshotSearchResult]
    total: int
    query: str


class SnapshotDetailResponse( BaseModel ):
    """Response model for detailed snapshot information."""
    id_hash: str
    question: str
    question_normalized: str
    question_gist: str
    answer: str
    answer_conversational: str
    runtime_stats: dict
    code: List[str]
    solution_summary: str = ""                        # verbose solution explanation
    solution_summary_gist: str = ""                   # concise gist of solution_summary
    synonymous_questions: Dict[str, float] = {}       # question → similarity score
    synonymous_question_gists: Dict[str, float] = {}  # gist → similarity score
    created_date: str
    user_id: str


class CodeSimilarityResult( BaseModel ):
    """Individual result for code/explanation/gist similarity search."""
    id_hash: str = Field( ..., description="Unique identifier (MD5 hash)" )
    question_preview: str = Field( ..., description="Truncated question (100 chars)" )
    code_preview: str = Field( default="", description="Truncated code (200 chars)" )
    solution_summary_preview: str = Field( default="", description="Truncated explanation (200 chars)" )
    solution_summary_gist: str = Field( default="", description="Concise gist of solution_summary" )
    similarity: float = Field( ..., description="Similarity score (0-100)" )
    created_date: str = Field( ..., description="Creation timestamp" )


class SimilarSnapshotsResponse( BaseModel ):
    """Response model for similar snapshots endpoint."""
    source_id_hash: str = Field( ..., description="ID hash of source snapshot" )
    source_question: str = Field( ..., description="Question from source snapshot" )
    code_similar: List[CodeSimilarityResult] = Field( default=[], description="Snapshots with similar code" )
    explanation_similar: List[CodeSimilarityResult] = Field( default=[], description="Snapshots with similar explanations" )
    total_code_matches: int = Field( default=0, description="Count of code-similar snapshots" )
    total_explanation_matches: int = Field( default=0, description="Count of explanation-similar snapshots" )


class SnapshotPreviewResponse( BaseModel ):
    """Response model for hover preview data."""
    id_hash: str = Field( ..., description="Unique identifier (MD5 hash)" )
    code_preview: str = Field( ..., description="First 300 chars of joined code" )
    solution_summary_gist: str = Field( ..., description="Concise gist of solution_summary" )
    question: str = Field( ..., description="Full question text" )


# ============================================================================
# Router Configuration
# ============================================================================

router = APIRouter(
    prefix     = "/admin",
    tags       = ["Admin"],
    responses  = {
        401: {"description": "Unauthorized"},
        403: {"description": "Forbidden - Admin role required"},
        404: {"description": "Not Found"},
        500: {"description": "Internal Server Error"}
    }
)


# ============================================================================
# Endpoints
# ============================================================================

@router.get(
    "/users",
    response_model  = UserListResponse,
    status_code     = status.HTTP_200_OK,
    summary         = "List all users",
    description     = "Get paginated list of users with optional filters. Requires admin role."
)
async def get_users(
    limit: int = 100,
    offset: int = 0,
    search: Optional[str] = None,
    role: Optional[str] = None,
    status_filter: Optional[str] = None,
    admin_user: Dict = Depends( require_admin )
) -> UserListResponse:
    """
    List all users with pagination and filtering.

    Requires:
        - Admin role authorization
        - Valid query parameters

    Ensures:
        - Returns paginated user list
        - Includes total count
        - Applies search and filter criteria

    Query Parameters:
        - limit: Max results (1-1000, default 100)
        - offset: Pagination offset (default 0)
        - search: Email search string
        - role: Filter by role (admin/user)
        - status_filter: Filter by status (active/inactive)

    Returns:
        UserListResponse: Paginated user list with metadata
    """
    try:
        users, total = list_users(
            limit         = limit,
            offset        = offset,
            search        = search,
            role_filter   = role,
            status_filter = status_filter
        )

        return UserListResponse(
            users  = users,
            total  = total,
            limit  = limit,
            offset = offset
        )

    except Exception as e:
        raise HTTPException(
            status_code = status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail      = f"Failed to list users: {str( e )}"
        )


@router.get(
    "/users/{user_id}",
    response_model  = UserDetailsResponse,
    status_code     = status.HTTP_200_OK,
    summary         = "Get user details",
    description     = "Get detailed information for specific user. Requires admin role."
)
async def get_user(
    user_id: str,
    admin_user: Dict = Depends( require_admin )
) -> UserDetailsResponse:
    """
    Get detailed user information.

    Requires:
        - Admin role authorization
        - Valid user ID

    Ensures:
        - Returns enhanced user details
        - Includes audit statistics
        - Returns 404 if user not found

    Path Parameters:
        - user_id: User UUID

    Returns:
        UserDetailsResponse: Detailed user information
    """
    user_details = get_user_details( user_id )

    if not user_details:
        raise HTTPException(
            status_code = status.HTTP_404_NOT_FOUND,
            detail      = "User not found"
        )

    return UserDetailsResponse( **user_details )


@router.put(
    "/users/{user_id}/roles",
    response_model  = MessageResponse,
    status_code     = status.HTTP_200_OK,
    summary         = "Update user roles",
    description     = "Update roles for specific user. Prevents self-demotion. Requires admin role."
)
async def update_roles(
    user_id: str,
    request_body: UpdateRolesRequest,
    request: Request,
    admin_user: Dict = Depends( require_admin )
) -> MessageResponse:
    """
    Update user roles with self-protection.

    Requires:
        - Admin role authorization
        - Valid user ID
        - Valid roles list (admin, user)

    Ensures:
        - Validates roles are allowed
        - Prevents admin self-demotion
        - Updates roles in database
        - Logs to audit trail
        - Returns updated user data

    Path Parameters:
        - user_id: User UUID

    Request Body:
        - roles: List of role strings

    Returns:
        MessageResponse: Success message with updated user
    """
    admin_ip = request.client.host if request.client else "unknown"

    success, message, updated_user = update_user_roles(
        admin_user_id  = admin_user["user_id"],
        target_user_id = user_id,
        new_roles      = request_body.roles,
        admin_email    = admin_user.get( "email", "unknown" ),
        admin_ip       = admin_ip
    )

    if not success:
        # Determine appropriate status code
        if "not found" in message.lower():
            status_code = status.HTTP_404_NOT_FOUND
        elif "cannot remove" in message.lower() or "invalid" in message.lower():
            status_code = status.HTTP_400_BAD_REQUEST
        else:
            status_code = status.HTTP_500_INTERNAL_SERVER_ERROR

        raise HTTPException(
            status_code = status_code,
            detail      = message
        )

    return MessageResponse(
        message = message,
        user    = updated_user
    )


@router.put(
    "/users/{user_id}/status",
    response_model  = MessageResponse,
    status_code     = status.HTTP_200_OK,
    summary         = "Toggle user status",
    description     = "Activate or deactivate user account. Prevents self-deactivation. Requires admin role."
)
async def update_status(
    user_id: str,
    request_body: UpdateStatusRequest,
    request: Request,
    admin_user: Dict = Depends( require_admin )
) -> MessageResponse:
    """
    Toggle user account status with session invalidation.

    Requires:
        - Admin role authorization
        - Valid user ID
        - Boolean status value

    Ensures:
        - Prevents admin self-deactivation
        - Updates is_active status
        - Revokes tokens if deactivating
        - Logs to audit trail
        - Returns updated user data

    Path Parameters:
        - user_id: User UUID

    Request Body:
        - is_active: Boolean status value

    Returns:
        MessageResponse: Success message with updated user
    """
    admin_ip = request.client.host if request.client else "unknown"

    success, message, updated_user = toggle_user_status(
        admin_user_id  = admin_user["user_id"],
        target_user_id = user_id,
        is_active      = request_body.is_active,
        admin_email    = admin_user.get( "email", "unknown" ),
        admin_ip       = admin_ip
    )

    if not success:
        # Determine appropriate status code
        if "not found" in message.lower():
            status_code = status.HTTP_404_NOT_FOUND
        elif "cannot deactivate" in message.lower():
            status_code = status.HTTP_400_BAD_REQUEST
        else:
            status_code = status.HTTP_500_INTERNAL_SERVER_ERROR

        raise HTTPException(
            status_code = status_code,
            detail      = message
        )

    return MessageResponse(
        message = message,
        user    = updated_user
    )


@router.post(
    "/users/{user_id}/reset-password",
    response_model  = ResetPasswordResponse,
    status_code     = status.HTTP_200_OK,
    summary         = "Admin password reset",
    description     = "Generate temporary password for user. Password shown once only. Requires admin role."
)
async def reset_user_password(
    user_id: str,
    request_body: ResetPasswordRequest,
    request: Request,
    admin_user: Dict = Depends( require_admin )
) -> ResetPasswordResponse:
    """
    Generate temporary password for user (admin reset).

    Requires:
        - Admin role authorization
        - Valid user ID
        - Optional reason for audit

    Ensures:
        - Generates crypto-secure password
        - Password meets strength requirements
        - Password returned ONCE (not stored)
        - Logs to audit trail with reason
        - Returns temporary password

    Path Parameters:
        - user_id: User UUID

    Request Body:
        - reason: Optional audit note

    Returns:
        ResetPasswordResponse: Message, temp password, and user data
    """
    admin_ip = request.client.host if request.client else "unknown"

    success, message, temp_password = admin_reset_password(
        admin_user_id  = admin_user["user_id"],
        target_user_id = user_id,
        admin_email    = admin_user.get( "email", "unknown" ),
        admin_ip       = admin_ip,
        reason         = request_body.reason or ""
    )

    if not success:
        # Determine appropriate status code
        if "not found" in message.lower():
            status_code = status.HTTP_404_NOT_FOUND
        else:
            status_code = status.HTTP_500_INTERNAL_SERVER_ERROR

        raise HTTPException(
            status_code = status_code,
            detail      = message
        )

    # Get user data for response
    from cosa.rest.user_service import get_user_by_id
    user_data = get_user_by_id( user_id )

    return ResetPasswordResponse(
        message            = message,
        temporary_password = temp_password,
        user               = {
            "id"    : user_data["id"],
            "email" : user_data["email"]
        }
    )


# ============================================================================
# Create / Delete User Endpoints
# ============================================================================

@router.post(
    "/users",
    response_model  = CreateUserResponse,
    status_code     = status.HTTP_201_CREATED,
    summary         = "Create new user",
    description     = "Create a new user account with specified roles. Auto-verifies email. Requires admin role."
)
async def create_user_endpoint(
    request_body: CreateUserRequest,
    request: Request,
    admin_user: Dict = Depends( require_admin )
) -> CreateUserResponse:
    """
    Create a new user account as admin.

    Requires:
        - Admin role authorization
        - Valid email, password, and roles

    Ensures:
        - User created with specified roles
        - Email auto-verified (admin vouches)
        - Audit event logged
        - Returns 201 Created with user data

    Request Body:
        - email: Valid email address
        - password: Password meeting strength requirements
        - roles: List of roles (default ["user"])

    Returns:
        CreateUserResponse: Message, user data, and user ID
    """
    admin_ip = request.client.host if request.client else "unknown"

    success, message, user_data = admin_create_user(
        admin_user_id = admin_user["user_id"],
        email         = request_body.email,
        password      = request_body.password,
        roles         = request_body.roles,
        admin_email   = admin_user.get( "email", "unknown" ),
        admin_ip      = admin_ip
    )

    if not success:
        # Determine appropriate status code
        if "invalid" in message.lower() or "already" in message.lower() or "duplicate" in message.lower():
            status_code = status.HTTP_400_BAD_REQUEST
        elif "password" in message.lower():
            status_code = status.HTTP_400_BAD_REQUEST
        else:
            status_code = status.HTTP_500_INTERNAL_SERVER_ERROR

        raise HTTPException(
            status_code = status_code,
            detail      = message
        )

    return CreateUserResponse(
        message = message,
        user    = user_data,
        user_id = user_data["id"]
    )


@router.delete(
    "/users/{user_id}",
    response_model  = MessageResponse,
    status_code     = status.HTTP_200_OK,
    summary         = "Delete user",
    description     = "Permanently delete user account. Cannot delete self or sole admin. Requires admin role."
)
async def delete_user_endpoint(
    user_id: str,
    request: Request,
    admin_user: Dict = Depends( require_admin ),
    request_body: Optional[DeleteUserRequest] = None
) -> MessageResponse:
    """
    Permanently delete a user account (hard delete).

    Requires:
        - Admin role authorization
        - Valid user ID
        - Cannot delete self
        - Cannot delete sole admin

    Ensures:
        - User physically removed from database
        - All tokens revoked before deletion
        - Audit event logged with reason
        - Returns 200 OK on success

    Path Parameters:
        - user_id: User UUID

    Request Body (optional):
        - reason: Audit trail reason

    Returns:
        MessageResponse: Success or error message
    """
    admin_ip = request.client.host if request.client else "unknown"
    reason   = request_body.reason if request_body and request_body.reason else ""

    success, message = admin_delete_user(
        admin_user_id  = admin_user["user_id"],
        target_user_id = user_id,
        admin_email    = admin_user.get( "email", "unknown" ),
        admin_ip       = admin_ip,
        reason         = reason
    )

    if not success:
        # Determine appropriate status code
        if "not found" in message.lower():
            status_code = status.HTTP_404_NOT_FOUND
        elif "cannot delete" in message.lower() or "sole admin" in message.lower():
            status_code = status.HTTP_400_BAD_REQUEST
        else:
            status_code = status.HTTP_500_INTERNAL_SERVER_ERROR

        raise HTTPException(
            status_code = status_code,
            detail      = message
        )

    return MessageResponse( message=message )


@router.post(
    "/users/batch-delete",
    response_model  = BatchDeleteUsersResponse,
    status_code     = status.HTTP_200_OK,
    summary         = "Batch delete users",
    description     = "Delete multiple user accounts at once. Reuses single-user safety checks. Requires admin role."
)
async def batch_delete_users_endpoint(
    request_body: BatchDeleteUsersRequest,
    request: Request,
    admin_user: Dict = Depends( require_admin )
) -> BatchDeleteUsersResponse:
    """
    Batch delete multiple user accounts.

    Uses POST instead of DELETE because many HTTP clients handle DELETE+body
    inconsistently, and the existing apiCall() helper drops DELETE bodies.

    Requires:
        - Admin role authorization
        - Non-empty user_ids list (max 50)

    Ensures:
        - Each user processed through existing admin_delete_user (all safety checks)
        - Self-protection and sole-admin guards enforced per user
        - Returns per-user success/failure results
        - Audit events logged for each deletion

    Request Body:
        - user_ids: List of user UUIDs to delete
        - reason: Optional audit trail reason

    Returns:
        BatchDeleteUsersResponse: Per-user results with totals
    """
    admin_ip = request.client.host if request.client else "unknown"
    reason   = request_body.reason or "Batch delete from admin UI"

    results       = []
    total_deleted = 0
    total_failed  = 0

    for user_id in request_body.user_ids:
        success, message = admin_delete_user(
            admin_user_id  = admin_user["user_id"],
            target_user_id = user_id,
            admin_email    = admin_user.get( "email", "unknown" ),
            admin_ip       = admin_ip,
            reason         = reason
        )

        results.append( BatchDeleteResult(
            user_id = user_id,
            success = success,
            message = message
        ))

        if success:
            total_deleted += 1
        else:
            total_failed += 1

    return BatchDeleteUsersResponse(
        results       = results,
        total_deleted = total_deleted,
        total_failed  = total_failed
    )


# ============================================================================
# Solution Snapshots Endpoints
# ============================================================================

@router.get(
    "/snapshots/search",
    response_model  = SearchSnapshotsResponse,
    status_code     = status.HTTP_200_OK,
    summary         = "Search solution snapshots",
    description     = "Search snapshots by question text using vector similarity. Requires admin role."
)
async def search_snapshots(
    q: str,
    threshold: float = 80.0,
    limit: int = 50,
    admin_user: Dict = Depends( require_admin ),
    snapshot_mgr = Depends( get_snapshot_manager )
) -> SearchSnapshotsResponse:
    """
    Search solution snapshots using vector similarity search.

    Requires:
        - Admin role authorization
        - Non-empty query string
        - Valid threshold (0-100)
        - Valid limit (1-100)

    Ensures:
        - Returns list of matching snapshots
        - Results sorted by similarity score descending
        - Question preview truncated to 100 chars
        - Includes similarity score for each result

    Query Parameters:
        - q: Search query text
        - threshold: Min similarity % (0-100, default 80)
        - limit: Max results (1-100, default 50)

    Returns:
        SearchSnapshotsResponse: List of matching snapshots with metadata
    """
    if not q or not q.strip():
        raise HTTPException(
            status_code = status.HTTP_400_BAD_REQUEST,
            detail      = "Query parameter 'q' cannot be empty"
        )

    if threshold < 0 or threshold > 100:
        raise HTTPException(
            status_code = status.HTTP_400_BAD_REQUEST,
            detail      = "Threshold must be between 0 and 100"
        )

    if limit < 1 or limit > 100:
        raise HTTPException(
            status_code = status.HTTP_400_BAD_REQUEST,
            detail      = "Limit must be between 1 and 100"
        )

    try:
        # Use threshold from query param, debug from config
        debug = _config_mgr.get( "app debug", default=False, return_type="boolean" )

        # Search snapshots using vector similarity
        results = snapshot_mgr.get_snapshots_by_question(
            question           = q,
            threshold_question = threshold,
            limit              = limit,
            debug              = debug
        )

        # Convert results to response format
        search_results = []
        for score, snapshot in results:
            # Truncate question to 100 chars for preview
            question_preview = du.truncate_string( snapshot.question, max_len=100 )

            # Debug: Show synonyms for each search result
            print( f"[ADMIN-SEARCH] ID: {snapshot.id_hash[:8]}, Score: {score:.1f}%" )
            print( f"  Question: {snapshot.question}" )
            if snapshot.synonymous_questions:
                print( f"  Synonyms ({len( snapshot.synonymous_questions )}):" )
                for syn_q, syn_score in snapshot.synonymous_questions.items():
                    print( f"    - '{syn_q}' ({syn_score:.1f}%)" )

            search_results.append( SnapshotSearchResult(
                id_hash          = snapshot.id_hash,
                question_preview = question_preview,
                question_gist    = snapshot.question_gist,
                created_date     = snapshot.created_date,
                score            = score
            ))

        # Ensure descending order by score (highest similarity first)
        search_results.sort( key=lambda x: x.score, reverse=True )

        return SearchSnapshotsResponse(
            results = search_results,
            total   = len( search_results ),
            query   = q
        )

    except Exception as e:
        print( f"[ADMIN-SNAPSHOTS] Search failed for query '{q}': {e}" )
        traceback.print_exc()
        raise HTTPException(
            status_code = status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail      = "Search failed. Please try again or contact support if the problem persists."
        )


@router.get(
    "/snapshots/{id_hash}",
    response_model  = SnapshotDetailResponse,
    status_code     = status.HTTP_200_OK,
    summary         = "Get snapshot details",
    description     = "Retrieve full snapshot details by ID. Requires admin role."
)
async def get_snapshot_details(
    id_hash: str,
    admin_user: Dict = Depends( require_admin ),
    snapshot_mgr = Depends( get_snapshot_manager )
) -> SnapshotDetailResponse:
    """
    Get complete snapshot data for display in detail modal.

    Requires:
        - Admin role authorization
        - Valid snapshot ID hash

    Ensures:
        - Returns full snapshot data if found
        - Returns 404 if snapshot not found
        - All text fields included (question, answer, etc.)

    Path Parameters:
        - id_hash: Snapshot ID (MD5 hash)

    Returns:
        SnapshotDetailResponse: Complete snapshot information
    """
    try:
        # Get snapshot by ID
        snapshot = snapshot_mgr.get_snapshot_by_id( id_hash )

        if not snapshot:
            print( f"[ADMIN-SNAPSHOTS] Snapshot not found: {id_hash}" )
            raise HTTPException(
                status_code = status.HTTP_404_NOT_FOUND,
                detail      = "Snapshot not found"
            )

        return SnapshotDetailResponse(
            id_hash                   = snapshot.id_hash,
            question                  = snapshot.question,
            question_normalized       = snapshot.question_normalized,
            question_gist             = snapshot.question_gist,
            answer                    = snapshot.answer,
            answer_conversational     = snapshot.answer_conversational,
            runtime_stats             = snapshot.runtime_stats,
            code                      = snapshot.code,
            solution_summary          = snapshot.solution_summary,
            solution_summary_gist     = snapshot.solution_summary_gist,
            synonymous_questions      = dict( snapshot.synonymous_questions ),
            synonymous_question_gists = dict( snapshot.synonymous_question_gists ),
            created_date              = snapshot.created_date,
            user_id                   = snapshot.user_id
        )

    except HTTPException:
        raise
    except Exception as e:
        print( f"[ADMIN-SNAPSHOTS] Failed to retrieve snapshot {id_hash}: {e}" )
        traceback.print_exc()
        raise HTTPException(
            status_code = status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail      = "Failed to retrieve snapshot details. Please try again."
        )


@router.delete(
    "/snapshots/{id_hash}",
    response_model  = MessageResponse,
    status_code     = status.HTTP_200_OK,
    summary         = "Delete snapshot",
    description     = "Permanently delete snapshot from database. Requires admin role."
)
async def delete_snapshot(
    id_hash: str,
    admin_user: Dict = Depends( require_admin ),
    snapshot_mgr = Depends( get_snapshot_manager )
) -> MessageResponse:
    """
    Delete snapshot with physical removal from LanceDB.

    Requires:
        - Admin role authorization
        - Valid snapshot ID hash

    Ensures:
        - Snapshot physically removed from database
        - Returns success message if deleted
        - Returns 404 if snapshot not found

    Path Parameters:
        - id_hash: Snapshot ID (MD5 hash)

    Returns:
        MessageResponse: Success or error message
    """
    try:
        print( f"[ADMIN-SNAPSHOTS] DELETE request for snapshot ID: {id_hash}" )

        # Get snapshot first to retrieve the question
        print( f"[ADMIN-SNAPSHOTS] Retrieving snapshot for deletion..." )
        snapshot = snapshot_mgr.get_snapshot_by_id( id_hash )

        if not snapshot:
            print( f"[ADMIN-SNAPSHOTS] Snapshot not found for deletion: {id_hash}" )
            raise HTTPException(
                status_code = status.HTTP_404_NOT_FOUND,
                detail      = "Snapshot not found"
            )

        print( f"[ADMIN-SNAPSHOTS] Found snapshot, question: '{snapshot.question[:50]}...'" )
        print( f"[ADMIN-SNAPSHOTS] Question length: {len(snapshot.question)} chars" )
        print( f"[ADMIN-SNAPSHOTS] Attempting physical deletion..." )

        # Delete snapshot using question (LanceDB delete requires question)
        success = snapshot_mgr.delete_snapshot(
            question        = snapshot.question,
            delete_physical = True
        )

        if success:
            print( f"[ADMIN-SNAPSHOTS] Successfully deleted snapshot {id_hash}" )
            return MessageResponse(
                message = f"Snapshot deleted successfully: {id_hash}"
            )
        else:
            print( f"[ADMIN-SNAPSHOTS] Delete operation returned False for {id_hash}" )
            raise HTTPException(
                status_code = status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail      = "Failed to delete snapshot"
            )

    except HTTPException:
        raise
    except Exception as e:
        print( f"[ADMIN-SNAPSHOTS] Delete failed for snapshot {id_hash}: {e}" )
        print( f"[ADMIN-SNAPSHOTS] Exception type: {type( e ).__name__}" )
        print( f"[ADMIN-SNAPSHOTS] Exception details: {str( e )}" )
        traceback.print_exc()
        raise HTTPException(
            status_code = status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail      = "Failed to delete snapshot. Please try again."
        )


# ============================================================================
# Snapshot Similarity Endpoints
# ============================================================================

@router.get(
    "/snapshots/{id_hash}/preview",
    response_model  = SnapshotPreviewResponse,
    status_code     = status.HTTP_200_OK,
    summary         = "Get snapshot preview",
    description     = "Get code and explanation preview for hover display. Requires admin role."
)
async def get_snapshot_preview(
    id_hash: str,
    admin_user: Dict = Depends( require_admin ),
    snapshot_mgr = Depends( get_snapshot_manager )
) -> SnapshotPreviewResponse:
    """
    Get snapshot preview data for hover tooltips.

    Requires:
        - Admin role authorization
        - Valid snapshot ID hash

    Ensures:
        - Returns code preview (first 300 chars)
        - Returns solution_summary_gist (concise explanation)
        - Returns 404 if snapshot not found

    Path Parameters:
        - id_hash: Snapshot ID (MD5 hash)

    Returns:
        SnapshotPreviewResponse: Preview data for UI display
    """
    try:
        # Get snapshot by ID
        snapshot = snapshot_mgr.get_snapshot_by_id( id_hash )

        if not snapshot:
            raise HTTPException(
                status_code = status.HTTP_404_NOT_FOUND,
                detail      = "Snapshot not found"
            )

        # Build code preview (first 300 chars of joined code)
        code_lines = snapshot.code if isinstance( snapshot.code, list ) else []
        code_text = "\n".join( code_lines )
        code_preview = code_text[:300] + ( "..." if len( code_text ) > 300 else "" )

        # Get solution gist with fallback:
        # 1. solution_summary_gist (concise gist - generated from solution_summary)
        # 2. solution_summary (verbose explanation of the solution)
        solution_summary_gist = getattr( snapshot, "solution_summary_gist", "" ) or ""
        if not solution_summary_gist.strip():
            solution_summary_gist = getattr( snapshot, "solution_summary", "" ) or ""

        return SnapshotPreviewResponse(
            id_hash               = id_hash,
            code_preview          = code_preview,
            solution_summary_gist = solution_summary_gist,
            question              = snapshot.question or ""
        )

    except HTTPException:
        raise
    except Exception as e:
        print( f"[ADMIN-SNAPSHOTS] Preview failed for {id_hash}: {e}" )
        traceback.print_exc()
        raise HTTPException(
            status_code = status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail      = "Failed to retrieve snapshot preview"
        )


@router.get(
    "/snapshots/{id_hash}/similar",
    response_model  = SimilarSnapshotsResponse,
    status_code     = status.HTTP_200_OK,
    summary         = "Find similar snapshots",
    description     = "Find snapshots with similar code or explanation. Requires admin role."
)
async def get_similar_snapshots(
    id_hash: str,
    code_threshold: float = 85.0,
    explanation_threshold: float = 85.0,
    limit: int = 20,
    ensure_top_result: bool = True,
    admin_user: Dict = Depends( require_admin ),
    snapshot_mgr = Depends( get_snapshot_manager )
) -> SimilarSnapshotsResponse:
    """
    Find snapshots with similar code or explanation using vector similarity.

    Requires:
        - Admin role authorization
        - Valid snapshot ID hash
        - Thresholds between 0.0 and 100.0

    Ensures:
        - Returns list of code-similar snapshots
        - Returns list of explanation-similar snapshots
        - Excludes source snapshot from results
        - If ensure_top_result=True, always returns at least 1 result per category
        - Returns 404 if source snapshot not found

    Path Parameters:
        - id_hash: Source snapshot ID (MD5 hash)

    Query Parameters:
        - code_threshold: Min code similarity % (default 85.0)
        - explanation_threshold: Min explanation similarity % (default 85.0)
        - limit: Max results per category (default 20)
        - ensure_top_result: Always return best match even if below threshold (default True)

    Returns:
        SimilarSnapshotsResponse: Similar snapshots grouped by type
    """
    debug = _config_mgr.get( "app debug" )

    try:
        if debug: print( f"[ADMIN-SIMILAR] Finding similar snapshots for {id_hash}" )

        # Get source snapshot
        source_snapshot = snapshot_mgr.get_snapshot_by_id( id_hash )

        if not source_snapshot:
            raise HTTPException(
                status_code = status.HTTP_404_NOT_FOUND,
                detail      = "Source snapshot not found"
            )

        if debug:
            print( f"[ADMIN-SIMILAR] Source: '{source_snapshot.question[:60]}...'" )

        # Find code-similar snapshots
        code_similar_results = []
        try:
            code_matches = snapshot_mgr.get_snapshots_by_code_similarity(
                exemplar_snapshot  = source_snapshot,
                threshold          = code_threshold,
                limit              = limit,
                exclude_self       = True,
                ensure_top_result  = ensure_top_result,
                debug              = debug
            )

            for score, snap in code_matches:
                # Build previews for all content types
                code_text         = "\n".join( snap.code ) if snap.code else ""
                code_preview      = code_text[:400] + ( "..." if len( code_text ) > 400 else "" )
                solution_text     = snap.solution_summary or ""
                solution_preview  = solution_text[:200] + ( "..." if len( solution_text ) > 200 else "" )

                code_similar_results.append( CodeSimilarityResult(
                    id_hash                  = snap.id_hash,
                    question_preview         = ( snap.question[:100] + "..." ) if len( snap.question ) > 100 else snap.question,
                    code_preview             = code_preview,
                    solution_summary_preview = solution_preview,
                    solution_summary_gist    = snap.solution_summary_gist or "",
                    similarity               = round( score, 1 ),
                    created_date             = snap.created_date or ""
                ) )
        except Exception as e:
            if debug: print( f"[ADMIN-SIMILAR] Code similarity search failed: {e}" )

        # Find explanation-similar snapshots
        explanation_similar_results = []
        try:
            explanation_matches = snapshot_mgr.get_snapshots_by_solution_similarity(
                exemplar_snapshot  = source_snapshot,
                threshold          = explanation_threshold,
                limit              = limit,
                exclude_self       = True,
                ensure_top_result  = ensure_top_result,
                debug              = debug
            )

            for score, snap in explanation_matches:
                # Build previews for all content types
                code_text         = "\n".join( snap.code ) if snap.code else ""
                code_preview      = code_text[:400] + ( "..." if len( code_text ) > 400 else "" )
                solution_text     = snap.solution_summary or ""
                solution_preview  = solution_text[:200] + ( "..." if len( solution_text ) > 200 else "" )

                explanation_similar_results.append( CodeSimilarityResult(
                    id_hash                  = snap.id_hash,
                    question_preview         = ( snap.question[:100] + "..." ) if len( snap.question ) > 100 else snap.question,
                    code_preview             = code_preview,
                    solution_summary_preview = solution_preview,
                    solution_summary_gist    = snap.solution_summary_gist or "",
                    similarity               = round( score, 1 ),
                    created_date             = snap.created_date or ""
                ) )
        except Exception as e:
            if debug: print( f"[ADMIN-SIMILAR] Explanation similarity search failed: {e}" )

        if debug:
            print( f"[ADMIN-SIMILAR] Found {len( code_similar_results )} code, {len( explanation_similar_results )} explanation matches" )

        return SimilarSnapshotsResponse(
            source_id_hash            = id_hash,
            source_question           = source_snapshot.question or "",
            code_similar              = code_similar_results,
            explanation_similar       = explanation_similar_results,
            total_code_matches        = len( code_similar_results ),
            total_explanation_matches = len( explanation_similar_results )
        )

    except HTTPException:
        raise
    except Exception as e:
        print( f"[ADMIN-SIMILAR] Failed for {id_hash}: {e}" )
        traceback.print_exc()
        raise HTTPException(
            status_code = status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail      = "Failed to find similar snapshots"
        )


# ============================================================================
# Refresh Source (test-env only) — re-exec the Python process in place so
# bind-mounted source edits take effect without a full container restart.
# Companion to src/scripts/refresh-test-server.sh.
# ============================================================================

class RefreshSourceResponse( BaseModel ):
    """Response model for refresh-source endpoint."""
    status : str
    pid    : int
    env    : str


def _refresh_source_allowed() -> tuple[ bool, str ]:
    """
    Guard check for the refresh-source endpoint.

    Requires:
        - LUPIN_ENV env var and config key are independently set

    Ensures:
        - Returns (True, env) only when LUPIN_ENV is "test"/"testing" AND
          config key "admin refresh source enabled" is True
        - Returns (False, reason) otherwise
    """
    import os as _os
    env = _os.environ.get( "LUPIN_ENV", "" ).lower()
    if env not in [ "test", "testing" ]:
        return False, f"refresh-source disabled: LUPIN_ENV={env!r} (must be test/testing)"
    enabled = _config_mgr.get( "admin refresh source enabled", default=False, return_type="boolean" )
    if not enabled:
        return False, "refresh-source disabled: config key 'admin refresh source enabled' is false"
    return True, env


def _reexec_process():
    """Replace the current process image with a fresh python invocation."""
    import os as _os, sys as _sys
    print( "[ADMIN-REFRESH] Re-executing process via os.execv to reload source" )
    _sys.stdout.flush()
    _sys.stderr.flush()
    _os.execv( _sys.executable, [ _sys.executable, "-m", "fastapi_app.main" ] )


@router.post(
    "/admin/refresh-source",
    response_model = RefreshSourceResponse,
    status_code    = status.HTTP_202_ACCEPTED,
    summary        = "Force test server to reload source (test env only)",
    description    = "Re-execs the uvicorn process in place so bind-mounted source edits take effect. Gated by LUPIN_ENV in {test,testing} AND config 'admin refresh source enabled'. Discards in-memory state."
)
async def refresh_source(
    background_tasks : BackgroundTasks,
    admin_user       : Dict = Depends( require_admin )
) -> RefreshSourceResponse:
    import os as _os, asyncio as _asyncio

    allowed, detail = _refresh_source_allowed()
    if not allowed:
        raise HTTPException(
            status_code = status.HTTP_403_FORBIDDEN,
            detail      = detail
        )

    async def _delayed_reexec():
        # Give FastAPI a moment to flush the HTTP response before we vanish.
        await _asyncio.sleep( 0.2 )
        _reexec_process()

    background_tasks.add_task( _delayed_reexec )

    return RefreshSourceResponse(
        status = "refreshing",
        pid    = _os.getpid(),
        env    = _os.environ.get( "LUPIN_ENV", "" ).lower()
    )
