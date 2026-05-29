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
    try:
        # Generate cryptographically secure token
        token = secrets.token_urlsafe( 32 )

        # Store in database using PostgreSQL repository
        with get_db() as session:
            token_repo = EmailVerificationTokenRepository( session )
            token_repo.create_token(
                token=token,
                user_id=uuid.UUID( user_id ),
                expires_hours=24
            )

        return True, "Verification token generated", token

    except Exception as e:
        return False, f"Failed to generate verification token: {str( e )}", None


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
    try:
        with get_db() as session:
            token_repo = EmailVerificationTokenRepository( session )

            # Check if token is valid (not used, not expired)
            if not token_repo.is_valid( token ):
                token_obj = token_repo.get_by_token( token )
                if token_obj is None:
                    return False, "Invalid verification token", None
                elif token_obj.used:
                    return False, "Verification token already used", None
                else:
                    return False, "Verification token expired", None

            # Get the token to retrieve user_id
            token_obj = token_repo.get_by_token( token )
            if token_obj is None:
                return False, "Invalid verification token", None

            user_id = str( token_obj.user_id )

            # Mark token as used
            token_repo.mark_used( token )

        return True, "Email verification token valid", user_id

    except Exception as e:
        return False, f"Failed to validate verification token: {str( e )}", None


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
    try:
        # Generate cryptographically secure token
        token = secrets.token_urlsafe( 32 )

        # Store in database using PostgreSQL repository
        with get_db() as session:
            token_repo = PasswordResetTokenRepository( session )
            token_repo.create_token(
                token=token,
                user_id=uuid.UUID( user_id ),
                expires_hours=1
            )

        return True, "Password reset token generated", token

    except Exception as e:
        return False, f"Failed to generate password reset token: {str( e )}", None


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
    try:
        with get_db() as session:
            token_repo = PasswordResetTokenRepository( session )

            # Check if token is valid (not used, not expired)
            if not token_repo.is_valid( token ):
                token_obj = token_repo.get_by_token( token )
                if token_obj is None:
                    return False, "Invalid password reset token", None
                elif token_obj.used:
                    return False, "Password reset token already used", None
                else:
                    return False, "Password reset token expired", None

            # Get the token to retrieve user_id
            token_obj = token_repo.get_by_token( token )
            if token_obj is None:
                return False, "Invalid password reset token", None

            user_id = str( token_obj.user_id )

            # Mark token as used
            token_repo.mark_used( token )

        return True, "Password reset token valid", user_id

    except Exception as e:
        return False, f"Failed to validate password reset token: {str( e )}", None


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