"""
Authentication Audit Logging for Lupin (Phase 8).

Provides security event logging for:
- Login successes and failures
- Registration events
- Password changes
- Email verification
- Token operations
- Other authentication events

Now using PostgreSQL repository pattern.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from cosa.rest.db.database import get_db
from cosa.rest.db.repositories import AuthAuditLogRepository


def log_auth_event(
    event_type: str,
    user_id: Optional[str] = None,
    email: Optional[str] = None,
    ip_address: Optional[str] = None,
    details: Optional[str] = None,
    success: bool = True
) -> None:
    """
    Log authentication event to audit log.

    Requires:
        - event_type is a non-empty string
        - Database connection available

    Ensures:
        - Event logged with timestamp
        - All provided fields stored
        - Success/failure status recorded

    Raises:
        - None (catches all exceptions)

    Event Types:
        - login_success: Successful login
        - login_failure: Failed login attempt
        - logout: User logout
        - register: User registration
        - password_change: Password updated
        - password_reset_request: Password reset requested
        - password_reset_complete: Password reset completed
        - email_verify_request: Email verification requested
        - email_verify_complete: Email verified
        - token_refresh: Refresh token used
        - token_revoke: Token revoked
        - account_lockout: Account locked due to failed attempts
        - account_unlock: Account unlocked

    Example:
        log_auth_event(
            event_type  = "login_success",
            user_id     = "user123",
            email       = "user@example.com",
            ip_address  = "192.168.1.1",
            details     = "Login via web interface",
            success     = True
        )
    """
    try:
        # Convert user_id to UUID if provided
        user_uuid = None
        if user_id:
            try:
                user_uuid = uuid.UUID( user_id )
            except ValueError:
                print( f"Invalid user_id format: {user_id}" )
                # Continue logging anyway, just without user_id

        with get_db() as session:
            audit_repo = AuthAuditLogRepository( session )

            audit_repo.log_event(
                event_type = event_type,
                user_id    = user_uuid,
                email      = email or "unknown",
                ip_address = ip_address or "unknown",
                details    = {"message": details} if isinstance( details, str ) else details or {},
                success    = success
            )

    except Exception as e:
        print( f"Failed to log auth event: {str( e )}" )


def get_user_audit_log( user_id: str, limit: int = 50 ) -> list:
    """
    Get audit log entries for specific user.

    Requires:
        - user_id is a non-empty string
        - limit is a positive integer
        - Database connection available

    Ensures:
        - Returns list of audit log entries
        - Sorted by most recent first
        - Limited to specified number of entries

    Returns:
        list: List of audit log entry dicts

    Example:
        entries = get_user_audit_log( "user123", limit=20 )
        for entry in entries:
            print( f"{entry['event_time']}: {entry['event_type']}" )
    """
    try:
        # Convert user_id to UUID
        user_uuid = uuid.UUID( user_id )

        with get_db() as session:
            audit_repo = AuthAuditLogRepository( session )

            logs = audit_repo.get_by_user( user_uuid, limit=limit )

            return [
                {
                    "event_type"  : log.event_type,
                    "user_id"     : str( log.user_id ) if log.user_id else None,
                    "email"       : log.email,
                    "ip_address"  : log.ip_address,
                    "details"     : log.details.get( "message", str( log.details ) ) if isinstance( log.details, dict ) else str( log.details ),
                    "success"     : log.success,
                    "event_time"  : log.event_time.isoformat() if log.event_time else None
                }
                for log in logs
            ]

    except ValueError:
        print( f"Invalid user_id format: {user_id}" )
        return []
    except Exception as e:
        print( f"Failed to get user audit log: {str( e )}" )
        return []


def get_failed_logins( email: Optional[str] = None, limit: int = 50 ) -> list:
    """
    Get failed login attempts.

    Requires:
        - limit is a positive integer
        - Database connection available

    Ensures:
        - Returns list of failed login events
        - Filtered by email if provided
        - Sorted by most recent first
        - Limited to specified number of entries

    Returns:
        list: List of failed login entry dicts

    Example:
        failures = get_failed_logins( "user@example.com", limit=10 )
        for failure in failures:
            print( f"{failure['event_time']}: {failure['ip_address']}" )
    """
    try:
        with get_db() as session:
            audit_repo = AuthAuditLogRepository( session )

            # Get failed login events
            failed_logs = audit_repo.get_failed_events( hours=24*365, limit=limit )  # Get all in last year

            # Filter by email if provided
            if email:
                failed_logs = [log for log in failed_logs if log.email and log.email.lower() == email.lower()]

            return [
                {
                    "event_type"  : log.event_type,
                    "user_id"     : str( log.user_id ) if log.user_id else None,
                    "email"       : log.email,
                    "ip_address"  : log.ip_address,
                    "details"     : log.details.get( "message", str( log.details ) ) if isinstance( log.details, dict ) else str( log.details ),
                    "success"     : log.success,
                    "event_time"  : log.event_time.isoformat() if log.event_time else None
                }
                for log in failed_logs[:limit]
            ]

    except Exception as e:
        print( f"Failed to get failed logins: {str( e )}" )
        return []


def get_suspicious_activity( hours: int = 24, threshold: int = 5 ) -> list:
    """
    Get accounts with suspicious activity (multiple failed logins).

    Requires:
        - hours is a positive integer
        - threshold is a positive integer
        - Database connection available

    Ensures:
        - Returns list of emails with suspicious activity
        - Counted within specified time window
        - Only includes accounts exceeding threshold

    Returns:
        list: List of tuples (email, failure_count)

    Example:
        suspicious = get_suspicious_activity( hours=24, threshold=5 )
        for email, count in suspicious:
            print( f"{email}: {count} failed attempts" )
    """
    try:
        with get_db() as session:
            audit_repo = AuthAuditLogRepository( session )

            # Get failed events in time window
            failed_logs = audit_repo.get_failed_events( hours=hours, limit=10000 )

            # Group by email and count
            email_counts = {}
            for log in failed_logs:
                if log.email:
                    email_counts[log.email] = email_counts.get( log.email, 0 ) + 1

            # Filter by threshold and sort
            suspicious = [
                (email, count)
                for email, count in email_counts.items()
                if count >= threshold
            ]
            suspicious.sort( key=lambda x: x[1], reverse=True )

            return suspicious

    except Exception as e:
        print( f"Failed to get suspicious activity: {str( e )}" )
        return []


def quick_smoke_test():
    """Quick smoke test for auth audit logging (PostgreSQL)."""
    import cosa.utils.util as du
    from cosa.rest.user_service import create_user

    du.print_banner( "Auth Audit Smoke Test (PostgreSQL)", prepend_nl=True )

    try:
        # Create test user
        print( "Creating test user..." )
        success, msg, user_id = create_user( "audit_test@example.com", "TestPass123!" )
        if not success:
            print( f"✗ Failed to create user: {msg}" )
            return False
        print( f"✓ Test user created: {user_id}" )

        # Test logging various events
        print( "Testing event logging..." )
        log_auth_event( "login_success", user_id, "audit_test@example.com", "192.168.1.1", "Test login", True )
        log_auth_event( "login_failure", None, "bad@example.com", "192.168.1.2", "Wrong password", False )
        log_auth_event( "register", user_id, "audit_test@example.com", "192.168.1.1", "New user", True )
        print( "✓ Events logged" )

        # Test get user audit log
        print( "Testing get user audit log..." )
        entries = get_user_audit_log( user_id, limit=10 )
        if len( entries ) >= 2:
            print( f"✓ Retrieved {len( entries )} audit entries" )
        else:
            print( f"✗ Expected at least 2 entries, got {len( entries )}" )
            return False

        # Test get failed logins
        print( "Testing get failed logins..." )
        failures = get_failed_logins( "bad@example.com", limit=10 )
        if len( failures ) >= 1:
            print( f"✓ Retrieved {len( failures )} failed login(s)" )
        else:
            print( "✗ Expected at least 1 failed login" )
            return False

        # Cleanup: Delete test user
        print( "Cleanup: Deleting test user..." )
        from cosa.rest.db.database import get_db
        from cosa.rest.db.repositories import UserRepository
        with get_db() as session:
            user_repo = UserRepository( session )
            user_uuid = uuid.UUID( user_id )
            deleted = user_repo.delete( user_uuid )
            if deleted:
                print( "✓ Test user deleted" )

        print( "\n✓ All auth audit tests passed!" )
        return True

    except Exception as e:
        print( f"✗ Auth audit test failed: {e}" )
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    quick_smoke_test()