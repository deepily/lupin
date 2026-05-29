"""
Authentication audit log repository for security auditing.

Provides comprehensive audit trail of authentication events.
"""

from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta, timezone
import uuid

from sqlalchemy.orm import Session
from cosa.rest.postgres_models import AuthAuditLog
from cosa.rest.db.repositories.base import BaseRepository


class AuthAuditLogRepository(BaseRepository[AuthAuditLog]):
    """
    Repository for AuthAuditLog model.

    Extends BaseRepository with audit logging:
        - Record authentication events
        - Query audit logs by user, event type, time period
        - Security monitoring and compliance reporting
    """

    def __init__( self, session: Session ):
        """
        Initialize AuthAuditLogRepository with session.

        Requires:
            - session: Active SQLAlchemy session (from get_db())

        Example:
            with get_db() as session:
                audit_repo = AuthAuditLogRepository( session )
                audit_repo.log_event( "login", user_id, email, ip, {}, True )
        """
        super().__init__( AuthAuditLog, session )

    def log_event( self, event_type: str, user_id: Optional[uuid.UUID], email: str,
                  ip_address: str, details: Dict[str, Any], success: bool ) -> AuthAuditLog:
        """
        Log an authentication event.

        Requires:
            - event_type: Type of auth event (login, logout, password_change, etc.)
            - user_id: User UUID (None if user doesn't exist yet)
            - email: Email address involved in event
            - ip_address: Client IP address
            - details: Additional event details as JSON (user_agent, error message, etc.)
            - success: Whether the event succeeded

        Ensures:
            - Event recorded with current timestamp
            - created_at set automatically
            - details stored as JSONB for flexible querying

        Returns:
            Created AuthAuditLog instance

        Example:
            # Successful login
            audit_repo.log_event(
                event_type = "login",
                user_id = user.id,
                email = user.email,
                ip_address = request.remote_addr,
                details = {
                    "user_agent": request.headers.get( "User-Agent" ),
                    "method": "password"
                },
                success = True
            )

            # Failed login attempt
            audit_repo.log_event(
                event_type = "login_failed",
                user_id = None,  # User doesn't exist or wrong password
                email = "wrong@example.com",
                ip_address = request.remote_addr,
                details = {
                    "user_agent": request.headers.get( "User-Agent" ),
                    "error": "Invalid credentials"
                },
                success = False
            )
        """
        return self.create(
            event_type = event_type,
            user_id = user_id,
            email = email.lower(),
            ip_address = ip_address,
            details = details,
            success = success,
            event_time = datetime.now( timezone.utc )
        )

    def get_by_user( self, user_id: uuid.UUID, limit: int = 100, offset: int = 0 ) -> List[AuthAuditLog]:
        """
        Get audit logs for a specific user.

        Requires:
            - user_id: User UUID
            - limit: Maximum logs to return (default: 100)
            - offset: Number of logs to skip (default: 0)

        Ensures:
            - Returns user's auth events
            - Ordered by event_time descending (newest first)
            - Includes pagination

        Returns:
            List of AuthAuditLog instances
        """
        return self.session.query( AuthAuditLog ).filter(
            AuthAuditLog.user_id == user_id
        ).order_by(
            AuthAuditLog.event_time.desc()
        ).limit( limit ).offset( offset ).all()

    def get_by_event_type( self, event_type: str, limit: int = 100, offset: int = 0 ) -> List[AuthAuditLog]:
        """
        Get audit logs by event type.

        Requires:
            - event_type: Event type to filter (login, logout, password_change, etc.)
            - limit: Maximum logs to return (default: 100)
            - offset: Number of logs to skip (default: 0)

        Ensures:
            - Returns events of specified type
            - Ordered by event_time descending (newest first)

        Returns:
            List of AuthAuditLog instances

        Example:
            # Get all password change events
            password_changes = audit_repo.get_by_event_type( "password_change" )
        """
        return self.session.query( AuthAuditLog ).filter(
            AuthAuditLog.event_type == event_type
        ).order_by(
            AuthAuditLog.event_time.desc()
        ).limit( limit ).offset( offset ).all()

    def get_failed_events( self, hours: int = 24, limit: int = 100 ) -> List[AuthAuditLog]:
        """
        Get recent failed authentication events.

        Requires:
            - hours: Look back period in hours (default: 24)
            - limit: Maximum logs to return (default: 100)

        Ensures:
            - Returns only failed events (success = False)
            - Within time window
            - Ordered by event_time descending (newest first)

        Returns:
            List of AuthAuditLog instances

        Example:
            # Security monitoring: Check recent failures
            recent_failures = audit_repo.get_failed_events( hours=24 )
            if len( recent_failures ) > 100:
                # High failure rate, possible attack
        """
        cutoff_time = datetime.now( timezone.utc ) - timedelta( hours=hours )

        return self.session.query( AuthAuditLog ).filter(
            AuthAuditLog.success == False,
            AuthAuditLog.event_time >= cutoff_time
        ).order_by(
            AuthAuditLog.event_time.desc()
        ).limit( limit ).all()

    def get_by_ip( self, ip_address: str, hours: int = 24, limit: int = 100 ) -> List[AuthAuditLog]:
        """
        Get audit logs from a specific IP address.

        Requires:
            - ip_address: IP address to query
            - hours: Look back period in hours (default: 24)
            - limit: Maximum logs to return (default: 100)

        Ensures:
            - Returns events from IP within time window
            - Ordered by event_time descending (newest first)

        Returns:
            List of AuthAuditLog instances

        Example:
            # Investigate suspicious IP
            ip_activity = audit_repo.get_by_ip( "192.168.1.100", hours=24 )
        """
        cutoff_time = datetime.now( timezone.utc ) - timedelta( hours=hours )

        return self.session.query( AuthAuditLog ).filter(
            AuthAuditLog.ip_address == ip_address,
            AuthAuditLog.event_time >= cutoff_time
        ).order_by(
            AuthAuditLog.event_time.desc()
        ).limit( limit ).all()

    def count_by_event_type( self, event_type: str, hours: int = 24 ) -> int:
        """
        Count events of specific type within time window.

        Requires:
            - event_type: Event type to count
            - hours: Look back period in hours (default: 24)

        Ensures:
            - Efficient COUNT query

        Returns:
            Number of events

        Example:
            login_count = audit_repo.count_by_event_type( "login", hours=24 )
            print( f"Logins in last 24h: {login_count}" )
        """
        cutoff_time = datetime.now( timezone.utc ) - timedelta( hours=hours )

        return self.session.query( AuthAuditLog ).filter(
            AuthAuditLog.event_type == event_type,
            AuthAuditLog.event_time >= cutoff_time
        ).count()

    def cleanup_old( self, days_old: int = 90 ) -> int:
        """
        Delete old audit log entries.

        Requires:
            - days_old: Delete logs older than this (default: 90 days for compliance)

        Ensures:
            - Old logs are deleted
            - Recent logs preserved for security monitoring
            - Compliance: 90-day retention is common requirement

        Returns:
            Number of logs deleted

        Example:
            # Cleanup old logs (run daily via cron)
            deleted = audit_repo.cleanup_old( days_old=90 )
        """
        cutoff_date = datetime.now( timezone.utc ) - timedelta( days=days_old )

        result = self.session.query( AuthAuditLog ).filter(
            AuthAuditLog.event_time < cutoff_date
        ).delete( synchronize_session=False )

        self.session.flush()
        return result
