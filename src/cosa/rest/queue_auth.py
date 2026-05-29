"""
Queue Authorization Helper

Provides role-based authorization for queue filtering operations.
Uses centralized auth utilities from auth_middleware.py for consistent role checking.
"""

from fastapi import HTTPException
from typing import Optional
from cosa.rest.auth_middleware import is_admin


def authorize_queue_filter(
    current_user: dict,
    filter_user_id: Optional[str]
) -> str:
    """
    Determine authorized user filter based on roles.

    Uses centralized is_admin() from auth_middleware for consistent role checking.
    Enforces role-based access control for queue filtering operations.

    Requires:
        - current_user is authenticated user dict from get_current_user dependency
        - current_user contains 'uid' field (user identifier)
        - current_user contains 'roles' field (list of role strings)
        - filter_user_id is query parameter (None/"*"/specific_id)

    Ensures:
        - Returns authorized filter value ("*" or specific user_id)
        - Raises 403 if unauthorized access attempted
        - Uses centralized is_admin() from auth_middleware
        - Regular users ALWAYS get their own user_id
        - Admin users get their requested filter

    Args:
        current_user: Authenticated user dict with uid and roles
        filter_user_id: Requested filter (None=self, "*"=all, or specific user_id)

    Returns:
        str: Authorized user_id to filter by ("*" for all, or specific user_id)

    Raises:
        HTTPException: 403 Forbidden if regular user attempts admin operations

    Authorization Matrix:
        | Role    | filter_user_id | Returns          | Status |
        |---------|----------------|------------------|--------|
        | User    | None           | current_user_id  | ✓ 200  |
        | User    | "*"            | HTTPException    | ✗ 403  |
        | User    | "!self"        | HTTPException    | ✗ 403  |
        | User    | other_id       | HTTPException    | ✗ 403  |
        | User    | own_id         | current_user_id  | ✓ 200  |
        | Admin   | None           | current_user_id  | ✓ 200  |
        | Admin   | "*"            | "*"              | ✓ 200  |
        | Admin   | "!self"        | "!<user_id>"     | ✓ 200  |
        | Admin   | other_id       | other_id         | ✓ 200  |

    Examples:
        # Regular user gets own jobs by default
        >>> authorize_queue_filter({"uid": "user_123", "roles": ["user"]}, None)
        "user_123"

        # Regular user cannot request all jobs
        >>> authorize_queue_filter({"uid": "user_123", "roles": ["user"]}, "*")
        HTTPException(403, "Only admin users can query all jobs...")

        # Admin can request all jobs
        >>> authorize_queue_filter({"uid": "admin_1", "roles": ["admin"]}, "*")
        "*"

        # Admin can exclude own jobs
        >>> authorize_queue_filter({"uid": "admin_1", "roles": ["admin"]}, "!self")
        "!admin_1"
    """
    requesting_user_id = current_user["uid"]

    # Use centralized auth check from auth_middleware (single source of truth)
    user_is_admin = is_admin( current_user )

    # Case 1: No filter specified → default to requesting user's own jobs
    if filter_user_id is None:
        return requesting_user_id

    # Case 2: Wildcard "*" → all users' jobs (admin only)
    if filter_user_id == "*":
        if not user_is_admin:
            raise HTTPException(
                status_code=403,
                detail="Only admin users can query all jobs. Regular users can only view their own jobs."
            )
        return "*"  # Authorized wildcard

    # Case 2b: "!self" → all jobs EXCEPT requesting user's (admin only)
    if filter_user_id == "!self":
        if not user_is_admin:
            raise HTTPException(
                status_code=403,
                detail="Only admin users can use the '!self' filter. Regular users can only view their own jobs."
            )
        return f"!{requesting_user_id}"  # Sentinel: "!" prefix signals exclusion

    # Case 3: Specific user_id requested (different from self)
    if filter_user_id != requesting_user_id:
        if not user_is_admin:
            raise HTTPException(
                status_code=403,
                detail=f"Cannot access other users' jobs. Regular users can only view their own jobs."
            )

    # Admin requesting specific user, or user requesting their own
    return filter_user_id
