"""
Password Security Service.

Handles password hashing, verification, and strength validation
using Passlib with bcrypt.
"""

from passlib.context import CryptContext
import re
from typing import Tuple

# Create password context
pwd_context = CryptContext(
    schemes    = ["bcrypt"],
    deprecated = "auto",
    bcrypt__rounds = 12  # Security vs performance balance
)


def hash_password( plain_password: str ) -> str:
    """
    Hash plaintext password using bcrypt.

    Requires:
        - plain_password is a non-empty string
        - pwd_context is initialized

    Ensures:
        - Returns bcrypt hash string (60 characters)
        - Hash includes automatic random salt
        - Hash is suitable for database storage
        - Same password produces different hashes (random salt)

    Raises:
        - ValueError if password is empty

    Returns:
        str: Bcrypt hash of password
    """
    if not plain_password:
        raise ValueError( "Password cannot be empty" )

    return pwd_context.hash( plain_password )


def verify_password( plain_password: str, hashed_password: str ) -> bool:
    """
    Verify plaintext password against stored hash.

    Requires:
        - plain_password is a string (may be empty)
        - hashed_password is a valid bcrypt hash
        - pwd_context is initialized

    Ensures:
        - Returns True if password matches hash
        - Returns False if password doesn't match or invalid input
        - Timing-attack resistant (constant-time comparison)
        - Never raises exception (returns False on error)

    Raises:
        - None (returns False on any error)

    Returns:
        bool: True if password matches, False otherwise
    """
    if not plain_password or not hashed_password:
        return False

    try:
        return pwd_context.verify( plain_password, hashed_password )
    except Exception:
        return False


def validate_password_strength( password: str ) -> Tuple[bool, str]:
    """
    Validate password meets minimum security requirements.

    Requirements:
    - Minimum 8 characters
    - At least 3 of 4 character types:
      * Lowercase letters
      * Uppercase letters
      * Digits
      * Special characters (!@#$%^&*(),.?":{}|<>)
    - Not in common password list

    Requires:
        - password is a string (may be weak or empty)

    Ensures:
        - Returns (True, "") if password acceptable
        - Returns (False, "error message") if password weak
        - Checks length, character types, common passwords
        - Never raises exception

    Raises:
        - None (returns validation result tuple)

    Returns:
        tuple: (is_valid: bool, error_message: str)
    """
    # Check minimum length
    min_length = 8
    if len( password ) < min_length:
        return False, f"Password must be at least {min_length} characters"

    # Check against common passwords FIRST (before character type validation)
    # This ensures common passwords are rejected even if they meet other requirements
    # Convert to lowercase and remove special characters for pattern matching
    # (e.g., "Password123!" matches "password123")
    password_normalized = re.sub( r'[^a-z0-9]', '', password.lower() )

    common_passwords = {
        "password", "12345678", "qwerty123", "admin123", "welcome123",
        "password123", "letmein", "abc12345", "trustno1", "passw0rd"
    }
    if password_normalized in common_passwords:
        return False, "Password is too common, please choose a stronger password"

    # Check character type requirements
    has_lowercase = bool( re.search( r'[a-z]', password ) )
    has_uppercase = bool( re.search( r'[A-Z]', password ) )
    has_digit     = bool( re.search( r'\d', password ) )
    has_special   = bool( re.search( r'[!@#$%^&*(),.?":{}|<>]', password ) )

    char_types = sum( [has_lowercase, has_uppercase, has_digit, has_special] )
    if char_types < 3:
        return False, "Password must contain at least 3 of: lowercase, uppercase, digit, special character"

    return True, ""


def quick_smoke_test():
    """
    Quick smoke test for password service.

    Requires:
        - Passlib installed
        - pwd_context initialized

    Ensures:
        - Tests password hashing
        - Tests password verification
        - Tests strength validation
        - Returns True if all tests pass

    Raises:
        - None (catches all exceptions)
    """
    import cosa.utils.util as du

    du.print_banner( "Password Service Smoke Test", prepend_nl=True )

    try:
        # Test 1: Password hashing
        print( "Testing password hashing..." )
        password = "TestPass123!"
        hash1 = hash_password( password )
        hash2 = hash_password( password )

        if hash1 and hash2 and hash1 != hash2:
            print( "✓ Password hashing working (random salts)" )
            print( f"  Hash length: {len( hash1 )} chars" )
        else:
            print( "✗ Password hashing failed" )
            return False

        # Test 2: Password verification
        print( "Testing password verification..." )
        if verify_password( password, hash1 ):
            print( "✓ Password verification working (correct password)" )
        else:
            print( "✗ Password verification failed" )
            return False

        if not verify_password( "WrongPassword", hash1 ):
            print( "✓ Password verification working (incorrect password)" )
        else:
            print( "✗ Wrong password was accepted!" )
            return False

        # Test 3: Strength validation - weak password
        print( "Testing strength validation (weak password)..." )
        is_valid, error = validate_password_strength( "weak" )
        if not is_valid and error:
            print( f"✓ Weak password rejected: {error}" )
        else:
            print( "✗ Weak password was accepted!" )
            return False

        # Test 4: Strength validation - strong password
        print( "Testing strength validation (strong password)..." )
        is_valid, error = validate_password_strength( "Strong123!" )
        if is_valid and not error:
            print( "✓ Strong password accepted" )
        else:
            print( f"✗ Strong password rejected: {error}" )
            return False

        # Test 5: Strength validation - common password
        print( "Testing strength validation (common password)..." )
        is_valid, error = validate_password_strength( "Password123!" )
        if not is_valid and "common" in error.lower():
            print( "✓ Common password rejected" )
        else:
            print( f"✗ Common password check failed: is_valid={is_valid}, error='{error}'" )
            return False

        # Test 6: Empty password handling
        print( "Testing empty password handling..." )
        try:
            hash_password( "" )
            print( "✗ Empty password was accepted!" )
            return False
        except ValueError:
            print( "✓ Empty password rejected" )

        print( "\n✓ All password service tests passed!" )
        return True

    except Exception as e:
        print( f"✗ Password service test failed: {e}" )
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    quick_smoke_test()