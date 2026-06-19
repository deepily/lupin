"""
Rate Limiter for Lupin Authentication (Phase 8).

Provides failed login tracking and account lockout functionality:
- Records failed login attempts
- Checks account lockout status
- Clears attempts after successful login
- Cleanup of old attempts
"""

from datetime import datetime, timedelta, timezone
from typing import Tuple, Optional
from cosa.rest.db.database import get_db
from cosa.rest.db.repositories import FailedLoginAttemptRepository
from cosa.config.configuration_manager import ConfigurationManager


# Initialize configuration manager
config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )


def record_failed_login( email: str, ip_address: Optional[str] = None ) -> None:
    """
    Record failed login attempt in database.

    Requires:
        - email is a non-empty string
        - Database connection available

    Ensures:
        - Failed attempt recorded with timestamp
        - IP address stored if provided

    Raises:
        - None (catches all exceptions)

    Example:
        record_failed_login( "user@example.com", "192.168.1.1" )
    """
    try:
        with get_db() as session:
            attempt_repo = FailedLoginAttemptRepository( session )
            attempt_repo.record_attempt( email, ip_address or "0.0.0.0" )

    except Exception as e:
        print( f"Failed to record failed login: {str( e )}" )


def check_account_lockout( email: str ) -> Tuple[bool, Optional[str]]:
    """
    Check if account is locked due to failed login attempts.

    Requires:
        - email is a non-empty string
        - Database connection available
        - Configuration has max_failed_attempts and lockout_duration_minutes

    Ensures:
        - returns (True, unlock_time) if account is locked
        - returns (False, None) if account is not locked
        - checks attempts within lockout window

    Returns:
        Tuple[bool, Optional[str]]: (is_locked, unlock_time_iso_string)

    Example:
        is_locked, unlock_time = check_account_lockout( "user@example.com" )
        if is_locked:
            print( f"Account locked until {unlock_time}" )
    """
    try:
        # Get configuration
        max_attempts = config_mgr.get( "auth max failed attempts", 5, return_type="int" )
        lockout_minutes = config_mgr.get( "auth lockout duration minutes", 15, return_type="int" )

        with get_db() as session:
            attempt_repo = FailedLoginAttemptRepository( session )

            # Count attempts in lockout window
            attempt_count = attempt_repo.count_recent_by_email( email, minutes=lockout_minutes )

            # Check if locked
            if attempt_count >= max_attempts:
                # Get most recent attempt to calculate unlock time
                recent_attempts = attempt_repo.get_recent_attempts_by_email( email, minutes=lockout_minutes )

                if recent_attempts:
                    last_attempt_time = recent_attempts[0].attempt_time
                    unlock_time = last_attempt_time + timedelta( minutes=lockout_minutes )

                    # Check if still locked
                    if datetime.now( timezone.utc ) < unlock_time:
                        return True, unlock_time.isoformat()

        return False, None

    except Exception as e:
        print( f"Failed to check account lockout: {str( e )}" )
        return False, None


def clear_failed_attempts( email: str ) -> None:
    """
    Clear all failed login attempts for email (after successful login).

    Requires:
        - email is a non-empty string
        - Database connection available

    Ensures:
        - All failed attempts for email are deleted

    Raises:
        - None (catches all exceptions)

    Example:
        clear_failed_attempts( "user@example.com" )
    """
    try:
        with get_db() as session:
            attempt_repo = FailedLoginAttemptRepository( session )
            attempt_repo.delete_by_email( email )

    except Exception as e:
        print( f"Failed to clear failed attempts: {str( e )}" )


def cleanup_old_attempts( hours: int = 24 ) -> int:
    """
    Remove failed login attempts older than specified hours.

    Requires:
        - hours is a positive integer
        - Database connection available

    Ensures:
        - Removes attempts older than cutoff time
        - Returns count of deleted attempts

    Returns:
        int: Number of attempts deleted

    Example:
        deleted = cleanup_old_attempts( 24 )
        print( f"Cleaned up {deleted} old attempts" )
    """
    try:
        with get_db() as session:
            attempt_repo = FailedLoginAttemptRepository( session )

            # Convert hours to days for cleanup_old() method
            days = hours / 24.0
            deleted_count = attempt_repo.cleanup_old( days_old=int( days ) if days >= 1 else 1 )

        return deleted_count

    except Exception as e:
        print( f"Failed to cleanup old attempts: {str( e )}" )
        return 0


def get_failed_attempts_count( email: str, minutes: int = 15 ) -> int:
    """
    Get count of failed login attempts for email in time window.

    Requires:
        - email is a non-empty string
        - minutes is a positive integer
        - Database connection available

    Ensures:
        - Returns count of attempts in time window
        - Returns 0 on error

    Returns:
        int: Count of failed attempts

    Example:
        count = get_failed_attempts_count( "user@example.com", 15 )
        print( f"{count} failed attempts in last 15 minutes" )
    """
    try:
        with get_db() as session:
            attempt_repo = FailedLoginAttemptRepository( session )
            count = attempt_repo.count_recent_by_email( email, minutes=minutes )

        return count

    except Exception as e:
        print( f"Failed to get failed attempts count: {str( e )}" )
        return 0


def quick_smoke_test():
    """
    Quick smoke test for rate limiter.

    Requires:
        - Database initialized
        - Configuration available

    Ensures:
        - Tests failed login recording
        - Tests account lockout logic
        - Tests lockout threshold
        - Tests clearing attempts
        - Returns True if all tests pass

    Raises:
        - None (catches all exceptions)
    """
    import cosa.utils.util as du
    from cosa.rest.sqlite_database import init_auth_database

    du.print_banner( "Rate Limiter Smoke Test", prepend_nl=True )

    try:
        # Initialize database
        print( "Initializing database..." )
        init_auth_database()
        print( "✓ Database initialized" )

        test_email = "ratelimit_test@example.com"
        test_ip = "192.168.1.100"

        # Test 1: Record failed login attempts
        print( f"Testing failed login recording (5 attempts)..." )
        for i in range( 5 ):
            record_failed_login( test_email, test_ip )
        print( "✓ Failed login attempts recorded" )

        # Test 2: Check account lockout (should be locked after 5 attempts)
        print( "Testing account lockout after threshold..." )
        is_locked, unlock_time = check_account_lockout( test_email )
        if is_locked and unlock_time:
            print( f"✓ Account locked correctly (unlock at {unlock_time})" )
        else:
            print( "✗ Account should be locked but isn't" )
            return False

        # Test 3: Verify attempt count
        print( "Testing failed attempts count..." )
        count = get_failed_attempts_count( test_email, minutes=15 )
        if count == 5:
            print( f"✓ Failed attempts count correct: {count}" )
        else:
            print( f"✗ Expected 5 attempts, got {count}" )
            return False

        # Test 4: Clear failed attempts
        print( "Testing clear failed attempts..." )
        clear_failed_attempts( test_email )
        count_after = get_failed_attempts_count( test_email, minutes=15 )
        if count_after == 0:
            print( "✓ Failed attempts cleared" )
        else:
            print( f"✗ Attempts not cleared, still have {count_after}" )
            return False

        # Test 5: Verify account no longer locked after clearing
        print( "Testing account unlocked after clearing..." )
        is_locked_after, _ = check_account_lockout( test_email )
        if not is_locked_after:
            print( "✓ Account unlocked after clearing attempts" )
        else:
            print( "✗ Account still locked after clearing" )
            return False

        # Test 6: Test cleanup function
        print( "Testing cleanup of old attempts..." )
        # Record some attempts
        record_failed_login( "cleanup_test@example.com", test_ip )
        record_failed_login( "cleanup_test@example.com", test_ip )

        # Cleanup (won't delete recent ones)
        deleted = cleanup_old_attempts( hours=24 )
        print( f"✓ Cleanup completed ({deleted} old attempts removed)" )

        print( "\n✓ All rate limiter tests passed!" )
        return True

    except Exception as e:
        print( f"✗ Rate limiter test failed: {e}" )
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    quick_smoke_test()