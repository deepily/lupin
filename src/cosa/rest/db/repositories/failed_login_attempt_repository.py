"""
Failed login attempt repository for security monitoring.

Provides tracking and querying of failed authentication attempts.
"""

from typing import List
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session
from cosa.rest.postgres_models import FailedLoginAttempt
from cosa.rest.db.repositories.base import BaseRepository


class FailedLoginAttemptRepository(BaseRepository[FailedLoginAttempt]):
    """
    Repository for FailedLoginAttempt model.

    Extends BaseRepository with failed login tracking:
        - Record failed attempts
        - Query recent attempts for rate limiting
        - Cleanup old attempts
    """

    def __init__( self, session: Session ):
        """
        Initialize FailedLoginAttemptRepository with session.

        Requires:
            - session: Active SQLAlchemy session (from get_db())

        Example:
            with get_db() as session:
                attempt_repo = FailedLoginAttemptRepository( session )
                attempt_repo.record_attempt( email, ip_address )
        """
        super().__init__( FailedLoginAttempt, session )

    def record_attempt( self, email: str, ip_address: str ) -> FailedLoginAttempt:
        """
        Record a failed login attempt.

        Requires:
            - email: Email address attempted (may not be valid user)
            - ip_address: Client IP address

        Ensures:
            - Attempt recorded with current timestamp
            - created_at set automatically

        Returns:
            Created FailedLoginAttempt instance

        Example:
            # User entered wrong password
            attempt_repo.record_attempt(
                email = "test@example.com",
                ip_address = request.remote_addr
            )
        """
        return self.create(
            email = email.lower(),
            ip_address = ip_address,
            attempt_time = datetime.now( timezone.utc )
        )

    def get_recent_attempts_by_email( self, email: str, minutes: int = 15 ) -> List[FailedLoginAttempt]:
        """
        Get recent failed login attempts for an email address.

        Requires:
            - email: Email address to check
            - minutes: Look back period in minutes (default: 15)

        Ensures:
            - Returns attempts within the time window
            - Case-insensitive email matching
            - Ordered by attempt_time descending (newest first)

        Returns:
            List of FailedLoginAttempt instances

        Example:
            # Check if account is under attack
            recent = attempt_repo.get_recent_attempts_by_email(
                email = "test@example.com",
                minutes = 15
            )
            if len( recent ) > 5:
                # Too many failed attempts, temporarily lock account
        """
        cutoff_time = datetime.now( timezone.utc ) - timedelta( minutes=minutes )

        return self.session.query( FailedLoginAttempt ).filter(
            FailedLoginAttempt.email == email.lower(),
            FailedLoginAttempt.attempt_time >= cutoff_time
        ).order_by(
            FailedLoginAttempt.attempt_time.desc()
        ).all()

    def get_recent_attempts_by_ip( self, ip_address: str, minutes: int = 15 ) -> List[FailedLoginAttempt]:
        """
        Get recent failed login attempts from an IP address.

        Requires:
            - ip_address: IP address to check
            - minutes: Look back period in minutes (default: 15)

        Ensures:
            - Returns attempts within the time window
            - Ordered by attempt_time descending (newest first)

        Returns:
            List of FailedLoginAttempt instances

        Example:
            # Check if IP is brute-forcing
            recent = attempt_repo.get_recent_attempts_by_ip(
                ip_address = "192.168.1.100",
                minutes = 15
            )
            if len( recent ) > 10:
                # IP-based rate limiting triggered
        """
        cutoff_time = datetime.now( timezone.utc ) - timedelta( minutes=minutes )

        return self.session.query( FailedLoginAttempt ).filter(
            FailedLoginAttempt.ip_address == ip_address,
            FailedLoginAttempt.attempt_time >= cutoff_time
        ).order_by(
            FailedLoginAttempt.attempt_time.desc()
        ).all()

    def count_recent_by_email( self, email: str, minutes: int = 15 ) -> int:
        """
        Count recent failed login attempts for email.

        Requires:
            - email: Email address to check
            - minutes: Look back period in minutes (default: 15)

        Ensures:
            - Efficient COUNT query
            - Case-insensitive email matching

        Returns:
            Number of failed attempts

        Example:
            count = attempt_repo.count_recent_by_email( email, minutes=15 )
            if count >= 5:
                # Account temporarily locked
        """
        cutoff_time = datetime.now( timezone.utc ) - timedelta( minutes=minutes )

        return self.session.query( FailedLoginAttempt ).filter(
            FailedLoginAttempt.email == email.lower(),
            FailedLoginAttempt.attempt_time >= cutoff_time
        ).count()

    def count_recent_by_ip( self, ip_address: str, minutes: int = 15 ) -> int:
        """
        Count recent failed login attempts from IP address.

        Requires:
            - ip_address: IP address to check
            - minutes: Look back period in minutes (default: 15)

        Ensures:
            - Efficient COUNT query

        Returns:
            Number of failed attempts
        """
        cutoff_time = datetime.now( timezone.utc ) - timedelta( minutes=minutes )

        return self.session.query( FailedLoginAttempt ).filter(
            FailedLoginAttempt.ip_address == ip_address,
            FailedLoginAttempt.attempt_time >= cutoff_time
        ).count()

    def delete_by_email( self, email: str ) -> int:
        """
        Delete all failed login attempts for an email address.

        Requires:
            - email: Email address to clear attempts for

        Ensures:
            - All failed attempts for email are deleted
            - Case-insensitive email matching

        Returns:
            Number of attempts deleted

        Example:
            # Clear failed attempts after successful login
            deleted = attempt_repo.delete_by_email( "test@example.com" )
        """
        result = self.session.query( FailedLoginAttempt ).filter(
            FailedLoginAttempt.email == email.lower()
        ).delete( synchronize_session=False )

        self.session.flush()
        return result

    def cleanup_old( self, days_old: int = 30 ) -> int:
        """
        Delete old failed login attempts.

        Requires:
            - days_old: Delete attempts older than this (default: 30 days)

        Ensures:
            - Old attempts are deleted
            - Recent attempts are preserved for security monitoring

        Returns:
            Number of attempts deleted

        Example:
            # Cleanup old attempts (run daily via cron)
            deleted = attempt_repo.cleanup_old( days_old=30 )
        """
        cutoff_date = datetime.now( timezone.utc ) - timedelta( days=days_old )

        result = self.session.query( FailedLoginAttempt ).filter(
            FailedLoginAttempt.attempt_time < cutoff_date
        ).delete( synchronize_session=False )

        self.session.flush()
        return result
