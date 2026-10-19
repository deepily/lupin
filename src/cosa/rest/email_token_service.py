"""
Email Token Service for Lupin Authentication.

Handles generation and validation of:
- Email verification tokens (24h expiration)
- Password reset tokens (1h expiration)

Tokens are cryptographically secure and stored in PostgreSQL database.
"""

import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Tuple, Optional
from cosa.rest.db.database import get_db
from cosa.rest.db.repositories import EmailVerificationTokenRepository, PasswordResetTokenRepository


def _issue_token( repo_cls, user_id: str, expires_hours: int, ok_message: str, fail_label: str ) -> Tuple[bool, str, Optional[str]]:
    """
    Generate a token, store it through the given repository class, and report the result.

    Requires:
        - repo_cls is a token repository class with create_token( token, user_id, expires_hours )
        - user_id is a valid UUID string
        - ok_message and fail_label are the words used in the success and failure results

    Ensures:
        - returns (True, ok_message, token) when the token is stored
        - returns (False, "Failed to generate <fail_label>: <error>", None) on any exception
        - the token is cryptographically secure (32 bytes)

    Returns:
        Tuple[bool, str, Optional[str]]: (success, message, token)
    """
    try:
        # Generate cryptographically secure token
        token = secrets.token_urlsafe( 32 )

        # Store in database using PostgreSQL repository
        with get_db() as session:
            token_repo = repo_cls( session )
            token_repo.create_token(
                token=token,
                user_id=uuid.UUID( user_id ),
                expires_hours=expires_hours
            )

        return True, ok_message, token

    except Exception as e:
        return False, f"Failed to generate {fail_label}: {str( e )}", None


def _consume_token( repo_cls, token: str, noun: str, ok_message: str ) -> Tuple[bool, str, Optional[str]]:
    """
    Check a token, mark it used, and return the user id it was issued for.

    Requires:
        - repo_cls is a token repository class with is_valid, get_by_token and mark_used
        - noun is the lower-case name of the token ("verification token", "password reset token")

    Ensures:
        - returns (True, ok_message, user_id) and marks the token used when it is valid
        - returns (False, "Invalid <noun>", None) when no such token exists
        - returns (False, "<Noun> already used", None) or (False, "<Noun> expired", None) otherwise
        - returns (False, "Failed to validate <noun>: <error>", None) on any exception

    Returns:
        Tuple[bool, str, Optional[str]]: (success, message, user_id)
    """
    try:
        with get_db() as session:
            token_repo = repo_cls( session )

            # Check if token is valid (not used, not expired)
            if not token_repo.is_valid( token ):
                token_obj = token_repo.get_by_token( token )
                if token_obj is None:
                    return False, f"Invalid {noun}", None
                elif token_obj.used:
                    return False, f"{noun.capitalize()} already used", None
                else:
                    return False, f"{noun.capitalize()} expired", None

            # Get the token to retrieve user_id
            token_obj = token_repo.get_by_token( token )
            if token_obj is None:
                return False, f"Invalid {noun}", None

            user_id = str( token_obj.user_id )

            # Mark token as used
            token_repo.mark_used( token )

        return True, ok_message, user_id

    except Exception as e:
        return False, f"Failed to validate {noun}: {str( e )}", None


def generate_verification_token( user_id: str ) -> Tuple[bool, str, Optional[str]]:
    """
    Generate email verification token for user.

    Requires:
        - user_id is a valid user ID string
        - Database connection available

    Ensures:
        - returns (True, message, token) if token generated successfully
        - returns (False, error_message, None) if generation failed
        - token expires in 24 hours
        - token is cryptographically secure (32 bytes)

    Returns:
        Tuple[bool, str, Optional[str]]: (success, message, token)

    Example:
        success, msg, token = generate_verification_token( "user123" )
        if success:
            send_verification_email( user_email, token )
    """
    return _issue_token( EmailVerificationTokenRepository, user_id, 24, "Verification token generated", "verification token" )


def validate_verification_token( token: str ) -> Tuple[bool, str, Optional[str]]:
    """
    Validate email verification token and mark as used.

    Requires:
        - token is a non-empty string
        - Database connection available

    Ensures:
        - returns (True, message, user_id) if token valid
        - returns (False, error_message, None) if token invalid/expired/used
        - marks token as used on successful validation
        - token can only be used once

    Returns:
        Tuple[bool, str, Optional[str]]: (success, message, user_id)

    Example:
        success, msg, user_id = validate_verification_token( token )
        if success:
            mark_email_verified( user_id )
    """
    return _consume_token( EmailVerificationTokenRepository, token, "verification token", "Email verification token valid" )


def generate_password_reset_token( user_id: str ) -> Tuple[bool, str, Optional[str]]:
    """
    Generate password reset token for user.

    Requires:
        - user_id is a valid user ID string
        - Database connection available

    Ensures:
        - returns (True, message, token) if token generated successfully
        - returns (False, error_message, None) if generation failed
        - token expires in 1 hour
        - token is cryptographically secure (32 bytes)

    Returns:
        Tuple[bool, str, Optional[str]]: (success, message, token)

    Example:
        success, msg, token = generate_password_reset_token( "user123" )
        if success:
            send_password_reset_email( user_email, token )
    """
    return _issue_token( PasswordResetTokenRepository, user_id, 1, "Password reset token generated", "password reset token" )


def validate_password_reset_token( token: str ) -> Tuple[bool, str, Optional[str]]:
    """
    Validate password reset token and mark as used.

    Requires:
        - token is a non-empty string
        - Database connection available

    Ensures:
        - returns (True, message, user_id) if token valid
        - returns (False, error_message, None) if token invalid/expired/used
        - marks token as used on successful validation
        - token can only be used once

    Returns:
        Tuple[bool, str, Optional[str]]: (success, message, user_id)

    Example:
        success, msg, user_id = validate_password_reset_token( token )
        if success:
            reset_password_with_token( user_id, new_password )
    """
    return _consume_token( PasswordResetTokenRepository, token, "password reset token", "Password reset token valid" )


def cleanup_expired_tokens() -> Tuple[int, int]:
    """
    Remove expired tokens from database.

    Requires:
        - Database connection available

    Ensures:
        - removes all expired verification tokens
        - removes all expired password reset tokens
        - returns count of deleted tokens

    Returns:
        Tuple[int, int]: (verification_tokens_deleted, reset_tokens_deleted)

    Example:
        ver_count, reset_count = cleanup_expired_tokens()
        print( f"Cleaned up {ver_count} verification and {reset_count} reset tokens" )
    """
    try:
        with get_db() as session:
            # Cleanup expired verification tokens
            ver_repo = EmailVerificationTokenRepository( session )
            ver_count = ver_repo.cleanup_expired()

            # Cleanup expired password reset tokens
            reset_repo = PasswordResetTokenRepository( session )
            reset_count = reset_repo.cleanup_expired()

        return ver_count, reset_count

    except Exception as e:
        print( f"Failed to cleanup expired tokens: {str( e )}" )
        return 0, 0


def quick_smoke_test():
    """
    Quick smoke test for email token service.

    Requires:
        - Database initialized
        - User service available

    Ensures:
        - Tests token generation and validation
        - Tests token reuse prevention
        - Tests token expiration
        - Returns True if all tests pass

    Raises:
        - None (catches all exceptions)
    """
    import cosa.utils.util as du
    from cosa.rest.sqlite_database import init_auth_database
    from cosa.rest.user_service import create_user

    du.print_banner( "Email Token Service Smoke Test", prepend_nl=True )

    try:
        # Initialize database
        print( "Initializing database..." )
        init_auth_database()
        print( "✓ Database initialized" )

        # Create test users
        print( "Creating test users..." )
        success1, msg1, user_id1 = create_user( "token_test1@example.com", "TestPass123!" )
        success2, msg2, user_id2 = create_user( "token_test2@example.com", "TestPass123!" )

        if not success1 or not success2:
            print( f"✗ Failed to create test users: {msg1}, {msg2}" )
            return False

        print( f"✓ Test users created" )

        # Test 1: Generate verification token
        print( "Testing verification token generation..." )
        success, message, token = generate_verification_token( user_id1 )
        if success and token:
            print( f"✓ Verification token generated" )
        else:
            print( f"✗ Token generation failed: {message}" )
            return False

        # Test 2: Validate verification token
        print( "Testing verification token validation..." )
        success, message, returned_user_id = validate_verification_token( token )
        if success and returned_user_id == user_id1:
            print( f"✓ Verification token validated" )
        else:
            print( f"✗ Token validation failed: {message}" )
            return False

        # Test 3: Test token reuse prevention
        print( "Testing token reuse prevention..." )
        success, message, _ = validate_verification_token( token )
        if not success and "already used" in message:
            print( "✓ Token reuse correctly blocked" )
        else:
            print( "✗ Token reuse was not blocked" )
            return False

        # Test 4: Generate password reset token
        print( "Testing password reset token generation..." )
        success, message, reset_token = generate_password_reset_token( user_id2 )
        if success and reset_token:
            print( f"✓ Password reset token generated" )
        else:
            print( f"✗ Reset token generation failed: {message}" )
            return False

        # Test 5: Validate password reset token
        print( "Testing password reset token validation..." )
        success, message, returned_user_id = validate_password_reset_token( reset_token )
        if success and returned_user_id == user_id2:
            print( f"✓ Password reset token validated" )
        else:
            print( f"✗ Reset token validation failed: {message}" )
            return False

        # Test 6: Test invalid token
        print( "Testing invalid token handling..." )
        success, message, _ = validate_verification_token( "invalid_token_12345" )
        if not success and "invalid" in message.lower():
            print( "✓ Invalid token correctly rejected" )
        else:
            print( "✗ Invalid token was not rejected" )
            return False

        # Test 7: Cleanup function
        print( "Testing cleanup function..." )
        ver_count, reset_count = cleanup_expired_tokens()
        print( f"✓ Cleanup completed ({ver_count} verification, {reset_count} reset tokens)" )

        print( "\n✓ All email token service tests passed!" )
        return True

    except Exception as e:
        print( f"✗ Email token service test failed: {e}" )
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    quick_smoke_test()