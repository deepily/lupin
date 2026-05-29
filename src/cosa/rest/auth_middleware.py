"""
Authentication Middleware for FastAPI.

Provides dependency injection for protected routes with support for:
- Optional vs required authentication
- Role-based access control (RBAC)
- JWT and mock token validation
- User information extraction
"""

from fastapi import Depends, HTTPException, status, Header
from typing import Optional, List, Dict
from cosa.rest.auth import verify_token


async def get_current_user_optional( authorization: Optional[str] = Header( None ) ) -> Optional[Dict]:
    """
    Get current user from Authorization header (optional).

    Use this dependency when authentication is optional - the endpoint
    works for both authenticated and anonymous users.

    Requires:
        - Authorization header format: "Bearer <token>"
        - Token can be JWT or mock token based on config

    Ensures:
        - Returns user dict if valid token provided
        - Returns None if no token provided
        - Raises 401 if token provided but invalid

    Raises:
        - HTTPException 401 if token format invalid
        - HTTPException 401 if token validation fails

    Returns:
        Optional[Dict]: User information or None

    Example:
        @router.get("/optional")
        async def endpoint(user: Optional[Dict] = Depends(get_current_user_optional)):
            if user:
                return {"message": f"Hello {user['email']}"}
            else:
                return {"message": "Hello anonymous"}
    """
    if not authorization:
        return None

    # Extract token from "Bearer <token>"
    parts = authorization.split()
    if len( parts ) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code = status.HTTP_401_UNAUTHORIZED,
            detail      = "Invalid authorization header format. Expected: Bearer <token>",
            headers     = {"WWW-Authenticate": "Bearer"}
        )

    token = parts[1]

    try:
        user_info = await verify_token( token )
        return user_info
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code = status.HTTP_401_UNAUTHORIZED,
            detail      = f"Authentication failed: {str( e )}",
            headers     = {"WWW-Authenticate": "Bearer"}
        )


async def get_current_user( authorization: Optional[str] = Header( None ) ) -> Dict:
    """
    Get current user from Authorization header (required).

    Use this dependency when authentication is required - the endpoint
    only works for authenticated users.

    Requires:
        - Authorization header with Bearer token (required)
        - Token can be JWT or mock token based on config

    Ensures:
        - Returns user dict if valid token provided
        - Raises 401 if no token or invalid token

    Raises:
        - HTTPException 401 if no authorization header
        - HTTPException 401 if token format invalid
        - HTTPException 401 if token validation fails

    Returns:
        Dict: User information

    Example:
        @router.get("/protected")
        async def endpoint(user: Dict = Depends(get_current_user)):
            return {"message": f"Hello {user['email']}"}
    """
    if not authorization:
        raise HTTPException(
            status_code = status.HTTP_401_UNAUTHORIZED,
            detail      = "Authorization header required",
            headers     = {"WWW-Authenticate": "Bearer"}
        )

    user = await get_current_user_optional( authorization )

    if not user:
        raise HTTPException(
            status_code = status.HTTP_401_UNAUTHORIZED,
            detail      = "Invalid authentication credentials",
            headers     = {"WWW-Authenticate": "Bearer"}
        )

    return user


def require_roles( required_roles: List[str] ):
    """
    Create dependency that requires specific roles.

    Factory function that creates a dependency requiring the user
    to have at least one of the specified roles.

    Requires:
        - required_roles is a non-empty list of role strings

    Ensures:
        - Returns dependency function
        - Dependency validates user has required role
        - Raises 403 if user lacks required roles

    Raises:
        - ValueError if required_roles is empty

    Returns:
        function: Dependency function for FastAPI

    Example:
        require_admin = require_roles(["admin"])

        @router.delete("/users/{user_id}")
        async def delete_user(
            user_id: str,
            user: Dict = Depends(require_admin)
        ):
            # Only admins can reach this code
            return {"message": "User deleted"}
    """
    if not required_roles:
        raise ValueError( "required_roles cannot be empty" )

    async def check_roles( user: Dict = Depends( get_current_user ) ) -> Dict:
        """
        Check if user has required roles.

        Requires:
            - user dict from get_current_user dependency
            - user dict contains 'roles' field

        Ensures:
            - Returns user dict if has required role
            - Raises 403 if lacks required role

        Raises:
            - HTTPException 403 if user lacks required roles

        Returns:
            Dict: User information
        """
        user_roles = user.get( "roles", [] )

        # Check if user has any of the required roles
        has_required_role = any( role in user_roles for role in required_roles )

        if not has_required_role:
            raise HTTPException(
                status_code = status.HTTP_403_FORBIDDEN,
                detail      = f"Requires one of these roles: {', '.join( required_roles )}"
            )

        return user

    return check_roles


def require_all_roles( required_roles: List[str] ):
    """
    Create dependency that requires ALL specified roles.

    Factory function that creates a dependency requiring the user
    to have ALL of the specified roles (not just one).

    Requires:
        - required_roles is a non-empty list of role strings

    Ensures:
        - Returns dependency function
        - Dependency validates user has ALL required roles
        - Raises 403 if user lacks any required role

    Raises:
        - ValueError if required_roles is empty

    Returns:
        function: Dependency function for FastAPI

    Example:
        require_admin_and_auditor = require_all_roles(["admin", "auditor"])

        @router.post("/sensitive-action")
        async def sensitive_action(
            user: Dict = Depends(require_admin_and_auditor)
        ):
            # Only users with BOTH admin AND auditor roles can reach this
            return {"message": "Action performed"}
    """
    if not required_roles:
        raise ValueError( "required_roles cannot be empty" )

    async def check_all_roles( user: Dict = Depends( get_current_user ) ) -> Dict:
        """
        Check if user has ALL required roles.

        Requires:
            - user dict from get_current_user dependency
            - user dict contains 'roles' field

        Ensures:
            - Returns user dict if has ALL required roles
            - Raises 403 if lacks any required role

        Raises:
            - HTTPException 403 if user lacks any required role

        Returns:
            Dict: User information
        """
        user_roles = user.get( "roles", [] )

        # Check if user has ALL of the required roles
        missing_roles = [role for role in required_roles if role not in user_roles]

        if missing_roles:
            raise HTTPException(
                status_code = status.HTTP_403_FORBIDDEN,
                detail      = f"Missing required roles: {', '.join( missing_roles )}"
            )

        return user

    return check_all_roles


# Pre-defined common role checks
require_admin = require_roles( ["admin"] )
require_user = require_roles( ["user"] )


def is_admin( user: Dict ) -> bool:
    """
    Check if user has admin role.

    Utility function for manual role checking within endpoint logic.

    Requires:
        - user dict contains 'roles' field

    Ensures:
        - Returns True if user has admin role
        - Returns False otherwise

    Returns:
        bool: True if admin, False otherwise

    Example:
        @router.get("/data")
        async def get_data(user: Dict = Depends(get_current_user)):
            if is_admin(user):
                # Return full data for admins
                return {"data": get_all_data()}
            elif is_user(user):
                # Return user-specific data
                return {"data": get_user_data(user['uid'])}
    """
    return "admin" in user.get( "roles", [] )


def is_user( user: Dict ) -> bool:
    """
    Check if user has user role.

    Utility function for manual role checking within endpoint logic.

    Requires:
        - user dict contains 'roles' field

    Ensures:
        - Returns True if user has user role
        - Returns False otherwise

    Returns:
        bool: True if user role present, False otherwise
    """
    return "user" in user.get( "roles", [] )


def has_role( user: Dict, role: str ) -> bool:
    """
    Check if user has specific role.

    Generic utility function for manual role checking within endpoint logic.

    Requires:
        - user dict contains 'roles' field
        - role is a non-empty string

    Ensures:
        - Returns True if user has role
        - Returns False otherwise

    Returns:
        bool: True if user has role, False otherwise

    Example:
        @router.get("/feature")
        async def get_feature(user: Dict = Depends(get_current_user)):
            if has_role(user, "beta_tester"):
                return {"feature": get_beta_feature()}
            else:
                return {"feature": get_stable_feature()}
    """
    return role in user.get( "roles", [] )


def has_any_role( user: Dict, roles: List[str] ) -> bool:
    """
    Check if user has any of the specified roles.

    Utility function for manual role checking within endpoint logic.

    Requires:
        - user dict contains 'roles' field
        - roles is a list of role strings

    Ensures:
        - Returns True if user has at least one role
        - Returns False otherwise

    Returns:
        bool: True if user has any role, False otherwise

    Example:
        @router.get("/dashboard")
        async def dashboard(user: Dict = Depends(get_current_user)):
            if has_any_role(user, ["admin", "user"]):
                return {"data": get_user_dashboard()}
            else:
                raise HTTPException(status_code=403, detail="Not authorized")
    """
    user_roles = user.get( "roles", [] )
    return any( role in user_roles for role in roles )


def has_all_roles( user: Dict, roles: List[str] ) -> bool:
    """
    Check if user has all of the specified roles.

    Utility function for manual role checking within endpoint logic.

    Requires:
        - user dict contains 'roles' field
        - roles is a list of role strings

    Ensures:
        - Returns True if user has ALL roles
        - Returns False otherwise

    Returns:
        bool: True if user has all roles, False otherwise

    Example:
        @router.post("/critical-action")
        async def critical_action(user: Dict = Depends(get_current_user)):
            if has_all_roles(user, ["admin", "security_officer"]):
                return perform_critical_action()
            else:
                raise HTTPException(status_code=403, detail="Insufficient privileges")
    """
    user_roles = user.get( "roles", [] )
    return all( role in user_roles for role in roles )