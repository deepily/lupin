"""
Admin Service for User Management.

Provides administrative functions for managing users, roles, and account status.
All functions include audit logging and self-protection rules.

Now using PostgreSQL repository pattern.
"""

import uuid
import secrets
import string
from typing import Optional, List, Dict, Tuple
from datetime import datetime, timezone

from sqlalchemy import func

from cosa.rest.db.database import get_db
from cosa.rest.db.repositories import UserRepository, AuthAuditLogRepository, FailedLoginAttemptRepository
from cosa.rest.user_service import get_user_by_id, get_user_by_email, create_user, mark_email_verified
from cosa.rest.password_service import hash_password, validate_password_strength
from cosa.rest.refresh_token_service import revoke_all_user_tokens
from cosa.rest.auth_audit import log_auth_event


def list_users(
    limit: int = 100,
    offset: int = 0,
    search: Optional[str] = None,
    role_filter: Optional[str] = None,
    status_filter: Optional[str] = None
) -> Tuple[List[Dict], int]:
    """
    List all users with pagination and filtering.

    Requires:
        - limit is a positive integer (max 1000)
        - offset is a non-negative integer
        - search is optional string for email filtering
        - role_filter is optional: 'admin' or 'user'
        - status_filter is optional: 'active' or 'inactive'
        - Database connection available

    Ensures:
        - Returns (users_list, total_count) tuple
        - Users list limited to specified count
        - Total count reflects filtered results
        - Users sorted by created_at DESC

    Returns:
        Tuple[List[Dict], int]: (users list, total count)

    Example:
        users, total = list_users( limit=50, offset=0, search="alice" )
        print( f"Found {total} users, showing {len( users )}" )
    """
    # Validate and cap limit
    limit = min( limit, 1000 )

    try:
        with get_db() as session:
            user_repo = UserRepository( session )
            from cosa.rest.postgres_models import User

            # Build query with filters
            query = session.query( User )

            # Email search filter
            if search:
                query = query.filter( User.email.ilike( f"%{search}%" ) )

            # Role filter
            if role_filter and role_filter in ['admin', 'user']:
                query = query.filter( User.roles.contains( [role_filter] ) )

            # Status filter
            if status_filter:
                if status_filter == 'active':
                    query = query.filter( User.is_active == True )
                elif status_filter == 'inactive':
                    query = query.filter( User.is_active == False )

            # Get total count
            total_count = query.count()

            # Get users with pagination
            users_objs = query.order_by( User.created_at.desc() ).limit( limit ).offset( offset ).all()

            users = [
                {
                    "id"              : str( user.id ),
                    "email"           : user.email,
                    "roles"           : user.roles if user.roles else ["user"],
                    "email_verified"  : user.email_verified,
                    "is_active"       : user.is_active,
                    "created_at"      : user.created_at.isoformat() if user.created_at else None,
                    "last_login_at"   : user.last_login_at.isoformat() if user.last_login_at else None
                }
                for user in users_objs
            ]

            return users, total_count

    except Exception as e:
        print( f"Error listing users: {e}" )
        return [], 0


def get_user_details( user_id: str ) -> Optional[Dict]:
    """
    Get detailed user information with additional stats.

    Requires:
        - user_id is a valid UUID string
        - Database connection available

    Ensures:
        - Returns enhanced user dict or None
        - Includes audit log count and failed login count
        - Password hash is NOT included

    Returns:
        Optional[Dict]: Enhanced user data or None if not found

    Example:
        details = get_user_details( "user-uuid-123" )
        if details:
            print( f"User has {details['audit_log_count']} audit entries" )
    """
    if not user_id:
        return None

    try:
        # Convert user_id to UUID
        user_uuid = uuid.UUID( user_id )

        with get_db() as session:
            user_repo = UserRepository( session )
            audit_repo = AuthAuditLogRepository( session )
            failed_repo = FailedLoginAttemptRepository( session )

            # Get user
            user = user_repo.get_by_id( user_uuid )
            if not user:
                return None

            # Get audit log count
            from cosa.rest.postgres_models import AuthAuditLog
            audit_count = session.query( AuthAuditLog ).filter(
                AuthAuditLog.user_id == user_uuid
            ).count()

            # Get failed login count
            from cosa.rest.postgres_models import FailedLoginAttempt
            failed_login_count = session.query( FailedLoginAttempt ).filter(
                FailedLoginAttempt.email == user.email
            ).count()

            user_details = {
                "id"                  : str( user.id ),
                "email"               : user.email,
                "roles"               : user.roles if user.roles else ["user"],
                "email_verified"      : user.email_verified,
                "is_active"           : user.is_active,
                "created_at"          : user.created_at.isoformat() if user.created_at else None,
                "last_login_at"       : user.last_login_at.isoformat() if user.last_login_at else None,
                "audit_log_count"     : audit_count,
                "failed_login_count"  : failed_login_count
            }

            return user_details

    except ValueError:
        print( f"Invalid user_id format: {user_id}" )
        return None
    except Exception as e:
        print( f"Error getting user details: {e}" )
        return None


def update_user_roles(
    admin_user_id: str,
    target_user_id: str,
    new_roles: List[str],
    admin_email: str = "unknown",
    admin_ip: str = "unknown"
) -> Tuple[bool, str, Optional[Dict]]:
    """
    Update user roles with self-protection and audit logging.

    Requires:
        - admin_user_id is valid UUID of admin performing action
        - target_user_id is valid UUID of user being modified
        - new_roles is non-empty list of valid role strings
        - Valid roles are: 'admin', 'user'

    Ensures:
        - Validates roles are in allowed list
        - Prevents admin from removing own admin role
        - Updates roles in database
        - Logs action to audit trail
        - Returns (success, message, updated_user)

    Raises:
        - None (returns error in tuple)

    Returns:
        Tuple[bool, str, Optional[Dict]]: (success, message, user_data)

    Example:
        success, msg, user = update_user_roles(
            admin_user_id = "admin-uuid",
            target_user_id = "user-uuid",
            new_roles = ["user", "admin"],
            admin_email = "admin@example.com",
            admin_ip = "192.168.1.1"
        )
    """
    # Validate roles
    valid_roles = ["admin", "user"]
    if not new_roles or not all( role in valid_roles for role in new_roles ):
        return False, f"Invalid roles. Allowed: {', '.join( valid_roles )}", None

    # Self-protection: Cannot remove own admin role
    if admin_user_id == target_user_id and "admin" not in new_roles:
        return False, "Cannot remove your own admin role", None

    try:
        # Get current user data
        target_user = get_user_by_id( target_user_id )
        if not target_user:
            return False, "User not found", None

        old_roles = target_user["roles"]

        # Convert target_user_id to UUID
        target_uuid = uuid.UUID( target_user_id )

        with get_db() as session:
            user_repo = UserRepository( session )

            # Get and update user
            user = user_repo.get_by_id( target_uuid )
            if not user:
                return False, "User not found", None

            user.roles = new_roles
            session.flush()

        # Log to audit
        log_auth_event(
            event_type  = "admin_role_update",
            user_id     = admin_user_id,
            email       = admin_email,
            ip_address  = admin_ip,
            details     = f"Updated roles for {target_user['email']}: {old_roles} → {new_roles}",
            success     = True
        )

        # Get updated user
        updated_user = get_user_by_id( target_user_id )

        return True, "User roles updated successfully", updated_user

    except ValueError:
        return False, "Invalid UUID format", None
    except Exception as e:
        return False, f"Role update failed: {e}", None


def toggle_user_status(
    admin_user_id: str,
    target_user_id: str,
    is_active: bool,
    admin_email: str = "unknown",
    admin_ip: str = "unknown"
) -> Tuple[bool, str, Optional[Dict]]:
    """
    Toggle user account status with self-protection and session invalidation.

    Requires:
        - admin_user_id is valid UUID of admin performing action
        - target_user_id is valid UUID of user being modified
        - is_active is boolean status value

    Ensures:
        - Prevents admin from deactivating self
        - Updates is_active status in database
        - Revokes all refresh tokens if deactivating
        - Logs action to audit trail
        - Returns (success, message, updated_user)

    Raises:
        - None (returns error in tuple)

    Returns:
        Tuple[bool, str, Optional[Dict]]: (success, message, user_data)

    Example:
        success, msg, user = toggle_user_status(
            admin_user_id = "admin-uuid",
            target_user_id = "user-uuid",
            is_active = False,  # Deactivate
            admin_email = "admin@example.com",
            admin_ip = "192.168.1.1"
        )
    """
    # Self-protection: Cannot deactivate self
    if admin_user_id == target_user_id and not is_active:
        return False, "Cannot deactivate your own account", None

    try:
        # Get current user data
        target_user = get_user_by_id( target_user_id )
        if not target_user:
            return False, "User not found", None

        # Convert target_user_id to UUID
        target_uuid = uuid.UUID( target_user_id )

        with get_db() as session:
            user_repo = UserRepository( session )

            # Get and update user
            user = user_repo.get_by_id( target_uuid )
            if not user:
                return False, "User not found", None

            user.is_active = is_active
            session.flush()

        # Revoke all tokens if deactivating
        if not is_active:
            revoke_all_user_tokens( target_user_id )

        # Log to audit
        status_text = "activated" if is_active else "deactivated"
        log_auth_event(
            event_type  = "admin_status_update",
            user_id     = admin_user_id,
            email       = admin_email,
            ip_address  = admin_ip,
            details     = f"User {target_user['email']} {status_text}",
            success     = True
        )

        # Get updated user
        updated_user = get_user_by_id( target_user_id )

        message = f"User {status_text} successfully"
        return True, message, updated_user

    except ValueError:
        return False, "Invalid UUID format", None
    except Exception as e:
        return False, f"Status update failed: {e}", None


def admin_reset_password(
    admin_user_id: str,
    target_user_id: str,
    admin_email: str = "unknown",
    admin_ip: str = "unknown",
    reason: str = ""
) -> Tuple[bool, str, Optional[str]]:
    """
    Generate temporary password for user (admin password reset).

    Requires:
        - admin_user_id is valid UUID of admin performing action
        - target_user_id is valid UUID of user being reset
        - reason is optional audit note

    Ensures:
        - Generates crypto-secure 16-character password
        - Password meets strength requirements
        - Password is hashed and stored
        - Password is returned ONCE (not stored plain)
        - Logs action to audit trail
        - Returns (success, message, temp_password)

    Raises:
        - None (returns error in tuple)

    Returns:
        Tuple[bool, str, Optional[str]]: (success, message, temporary_password)

    Example:
        success, msg, temp_pw = admin_reset_password(
            admin_user_id = "admin-uuid",
            target_user_id = "user-uuid",
            admin_email = "admin@example.com",
            admin_ip = "192.168.1.1",
            reason = "User forgot password, email unavailable"
        )
        if success:
            print( f"Temporary password: {temp_pw}" )
    """
    # Get target user
    target_user = get_user_by_id( target_user_id )
    if not target_user:
        return False, "User not found", None

    # Generate crypto-secure temporary password
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    temp_password = ''.join( secrets.choice( alphabet ) for _ in range( 16 ) )

    # Validate password meets strength requirements
    is_valid, error_msg = validate_password_strength( temp_password )
    if not is_valid:
        # Retry with longer password if validation fails
        temp_password = ''.join( secrets.choice( alphabet ) for _ in range( 20 ) )
        is_valid, error_msg = validate_password_strength( temp_password )
        if not is_valid:
            return False, f"Failed to generate valid password: {error_msg}", None

    # Hash password
    try:
        password_hash = hash_password( temp_password )
    except Exception as e:
        return False, f"Password hashing failed: {e}", None

    try:
        # Convert target_user_id to UUID
        target_uuid = uuid.UUID( target_user_id )

        with get_db() as session:
            user_repo = UserRepository( session )

            # Update password using repository
            updated_user = user_repo.update_password( target_uuid, password_hash )

            if not updated_user:
                return False, "Password update failed", None

        # Log to audit
        audit_details = f"Admin password reset for {target_user['email']}"
        if reason:
            audit_details += f" - Reason: {reason}"

        log_auth_event(
            event_type  = "admin_password_reset",
            user_id     = admin_user_id,
            email       = admin_email,
            ip_address  = admin_ip,
            details     = audit_details,
            success     = True
        )

        return True, "Password reset successfully", temp_password

    except ValueError:
        return False, "Invalid UUID format", None
    except Exception as e:
        return False, f"Password reset failed: {e}", None


def admin_create_user(
    admin_user_id: str,
    email: str,
    password: str,
    roles: List[str],
    admin_email: str = "unknown",
    admin_ip: str = "unknown"
) -> Tuple[bool, str, Optional[Dict]]:
    """
    Create a new user account as admin, auto-verified.

    Requires:
        - admin_user_id is valid UUID of admin performing action
        - email is a valid email address
        - password is a non-empty string meeting strength requirements
        - roles is a list of valid role strings ("admin", "user")

    Ensures:
        - Validates roles against allowed list
        - Creates user via user_service.create_user()
        - Auto-verifies email (admin vouches for user)
        - Logs audit event "admin_user_create"
        - Returns (success, message, user_data_dict)

    Returns:
        Tuple[bool, str, Optional[Dict]]: (success, message, user_data)

    Example:
        success, msg, user = admin_create_user(
            admin_user_id = "admin-uuid",
            email         = "newuser@example.com",
            password      = "StrongPass123!",
            roles         = ["user"],
            admin_email   = "admin@example.com",
            admin_ip      = "192.168.1.1"
        )
    """
    # Validate roles
    valid_roles = ["admin", "user"]
    if not roles or not all( role in valid_roles for role in roles ):
        return False, f"Invalid roles. Allowed: {', '.join( valid_roles )}", None

    try:
        # Create user via existing service
        success, message, user_id = create_user(
            email    = email,
            password = password,
            roles    = roles
        )

        if not success:
            return False, message, None

        # Auto-verify email since admin is creating the account
        verify_success, verify_msg = mark_email_verified( user_id )
        if not verify_success:
            print( f"Warning: User created but email verification failed: {verify_msg}" )

        # Log audit event
        log_auth_event(
            event_type = "admin_user_create",
            user_id    = admin_user_id,
            email      = admin_email,
            ip_address = admin_ip,
            details    = f"Admin created user {email} with roles {roles}",
            success    = True
        )

        # Get full user data
        user_data = get_user_by_id( user_id )

        return True, "User created successfully", user_data

    except Exception as e:
        return False, f"User creation failed: {e}", None


def admin_delete_user(
    admin_user_id: str,
    target_user_id: str,
    admin_email: str = "unknown",
    admin_ip: str = "unknown",
    reason: str = ""
) -> Tuple[bool, str]:
    """
    Permanently delete a user account (hard delete).

    Requires:
        - admin_user_id is valid UUID of admin performing action
        - target_user_id is valid UUID of user to delete
        - admin_user_id != target_user_id (cannot delete self)
        - Target is not the sole admin

    Ensures:
        - Self-protection: rejects if admin tries to delete self
        - Sole-admin guard: rejects if target is last admin
        - Revokes all tokens before deletion
        - Physically deletes user from database
        - Logs audit event "admin_user_delete" with target email and reason
        - Returns (success, message)

    Returns:
        Tuple[bool, str]: (success, message)

    Example:
        success, msg = admin_delete_user(
            admin_user_id  = "admin-uuid",
            target_user_id = "user-uuid",
            admin_email    = "admin@example.com",
            admin_ip       = "192.168.1.1",
            reason         = "Account no longer needed"
        )
    """
    # Self-protection: Cannot delete self
    if admin_user_id == target_user_id:
        return False, "Cannot delete your own account"

    try:
        # Get target user data
        target_user = get_user_by_id( target_user_id )
        if not target_user:
            return False, "User not found"

        target_email = target_user["email"]
        target_roles = target_user.get( "roles", [] )

        # Protected-account guard: seed companions can never be deleted
        with get_db() as session:
            from cosa.rest.postgres_models import User as UserModel
            _tgt = session.query( UserModel ).filter(
                UserModel.id == uuid.UUID( target_user_id )
            ).first()
            if _tgt and _tgt.is_protected:
                return False, f"Cannot delete system-protected account '{target_email}'"

        # Sole-admin guard: if target has admin role, check admin count
        if "admin" in target_roles:
            with get_db() as session:
                from cosa.rest.postgres_models import User
                admin_count = session.query( User ).filter(
                    User.roles.contains( ["admin"] ),
                    User.is_active == True
                ).count()

            if admin_count <= 1:
                return False, "Cannot delete the sole admin account"

        # Revoke all tokens before deletion
        revoke_all_user_tokens( target_user_id )

        # Physical delete via repository
        target_uuid = uuid.UUID( target_user_id )

        with get_db() as session:
            user_repo = UserRepository( session )
            deleted = user_repo.delete( target_uuid )

            if not deleted:
                return False, "Failed to delete user"

        # Log audit event (after successful deletion)
        audit_details = f"Admin deleted user {target_email} (ID: {target_user_id})"
        if reason:
            audit_details += f" - Reason: {reason}"

        log_auth_event(
            event_type = "admin_user_delete",
            user_id    = admin_user_id,
            email      = admin_email,
            ip_address = admin_ip,
            details    = audit_details,
            success    = True
        )

        return True, f"User {target_email} deleted successfully"

    except ValueError:
        return False, "Invalid UUID format"
    except Exception as e:
        return False, f"User deletion failed: {e}"
