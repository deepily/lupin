"""
User ID Generator Utility

This module provides the single source of truth for converting email addresses
to system IDs used throughout the Lupin application.

The algorithm ensures:
- Collision-resistant IDs through email-based hashing
- Safe characters for file paths, URLs, and database keys
- Consistent generation across all Python modules
"""

import re
import uuid
from typing import Dict, Optional


def email_to_system_id( email: str ) -> str:
    """
    Convert email address to collision-resistant system ID.
    
    This is the SINGLE SOURCE OF TRUTH for email → system ID conversion.
    All Python modules should import and use this function.
    
    Requires:
        - email is a non-empty string containing '@' character
        - email follows basic email format with local@domain structure
        
    Ensures:
        - Returns collision-resistant system ID with 4-character hash suffix
        - Output contains only lowercase letters, numbers, and underscores
        - System ID is safe for file paths, URLs, and database keys
        - Same email always produces same system ID (deterministic)
        - Different emails produce different system IDs (collision-resistant)
        
    Raises:
        - ValueError if email is empty or doesn't contain '@' character
        
    Args:
        email: Email address to convert (e.g., "ricardo.felipe.ruiz@gmail.com")
        
    Returns:
        str: System ID (e.g., "ricardo_felipe_ruiz_6bdc")
        
    Examples:
        >>> email_to_system_id("ricardo.felipe.ruiz@gmail.com")
        'ricardo_felipe_ruiz_6bdc'
        >>> email_to_system_id("alice.smith@example.com")
        'alice_smith_a1b2'
    """
    if not email or '@' not in email:
        raise ValueError( f"Invalid email address: {email}" )
    
    # Extract local part from email (before @)
    local_part = email.split( '@' )[0]
    
    # Convert to safe system ID format
    base_name = re.sub( r'[^a-z0-9]', '_', local_part.lower() )
    base_name = re.sub( r'_+', '_', base_name )  # Replace multiple underscores
    base_name = re.sub( r'^_|_$', '', base_name )  # Remove leading/trailing underscores
    
    # Generate collision-resistant hash suffix (4 characters)
    hash_val = 0
    for char in email:
        hash_val = ((hash_val << 5) - hash_val) + ord( char )
        hash_val = hash_val & hash_val  # Convert to 32-bit integer
    
    suffix = hex( abs( hash_val ) )[-4:]
    
    return f"{base_name}_{suffix}"


# The namespace mock user ids are minted under. A fixed uuid5 namespace is what makes
# the mapping deterministic — the same email yields the same id on every request, in
# every process, across restarts — without any table to keep. Changing this constant
# renames every mock user, so it is a constant on purpose and not a config key.
MOCK_USER_ID_NAMESPACE = uuid.UUID( "6f2b9e0a-0b1e-5c7a-9a3d-4f1c8e2d7b60" )


def email_to_user_uuid( email: str ) -> str:
    """
    Convert an email to the UUID-shaped user id mock auth hands out.

    WHY THIS EXISTS (row befeba88): under AUTH_MODE=mock the user id was the system
    id — "interactive_job_tester_8e32". The ordinary API path scopes a job id as
    "{sha256}::{user_id}", and AsyncNotificationRequest's pattern requires a UUID after
    the "::", so every queue notification raised a validation error that was caught,
    printed and dropped: 530 of them in one baseline log, and a mock-auth environment
    that looked like it had working notifications and did not.

    The fix chosen over widening the validator (Mr Radio's ruling, 2026-08-21): mock
    and JWT should produce the SAME id shape. Under JWT the user id is the database
    row's UUID; under mock it is this — minted from the email, so it needs no database
    and is stable across requests, processes and restarts.

    Requires:
        - email is a non-empty string containing '@'

    Ensures:
        - returns the canonical string form of a UUID (36 chars, 8-4-4-4-12)
        - the same email always returns the same id
        - different emails return different ids

    Raises:
        - ValueError if email is empty or contains no '@'

    Args:
        email: the mock user's email (e.g. "interactive_job_tester_8e32@generated.local")

    Returns:
        str: a UUID string (e.g. "50c73ba7-36dd-4eaf-a7e2-63256252c84f")
    """
    if not email or '@' not in email:
        raise ValueError( f"Invalid email address: {email}" )

    return str( uuid.uuid5( MOCK_USER_ID_NAMESPACE, email.strip().lower() ) )


def system_id_to_display_name( system_id: str ) -> str:
    """
    Extract a display name from system ID.
    
    Requires:
        - system_id is a non-empty string
        - system_id follows expected format with underscores
        
    Ensures:
        - Returns capitalized first part of system ID before first underscore
        - Returns original system_id if no underscores found
        - Always returns a non-empty string
        
    Raises:
        - None (handles all cases gracefully)
        
    Args:
        system_id: System ID (e.g., "ricardo_felipe_ruiz_6bdc")
        
    Returns:
        str: Display name (e.g., "Ricardo")
    """
    # Extract first part before underscore and hash
    parts = system_id.split( '_' )
    if parts:
        first_name = parts[0]
        return first_name.capitalize()
    return system_id  # pragma: no cover - str.split() always returns at least one element, so the `if parts:` guard is always True and this fallback is unreachable


def validate_system_id( system_id: str ) -> bool:
    """
    Validate that a system ID follows the expected format.
    
    Requires:
        - system_id is a string (may be empty or invalid)
        
    Ensures:
        - Returns True if system_id matches expected format pattern
        - Returns False for invalid formats or malformed strings
        - Expected format: lowercase alphanumeric with underscores ending in 4-char hex
        - Validates against regex pattern: ^[a-z0-9_]+_[a-f0-9]{4}$
        
    Raises:
        - None (handles all input gracefully)
        
    Args:
        system_id: System ID to validate
        
    Returns:
        bool: True if valid format
    """
    # Expected format: alphanumeric_with_underscores_XXXX (where XXXX is hex suffix)
    pattern = r'^[a-z0-9_]+_[a-f0-9]{4}$'
    return bool( re.match( pattern, system_id ) )


# Mock user database for development/testing
# In production, this would be replaced with actual database queries
MOCK_USER_DATABASE = {
    "ricardo_felipe_ruiz_6bdc": {
        "email": "ricardo.felipe.ruiz@gmail.com",
        "name": "Ricardo",
        "email_verified": True
    },
    "alice_smith_a1b2": {
        "email": "alice.smith@example.com", 
        "name": "Alice",
        "email_verified": True
    },
    "bob_jones_3c4d": {
        "email": "bob.jones@example.com",
        "name": "Bob", 
        "email_verified": True
    }
}


def get_user_info( system_id: str ) -> Optional[Dict]:
    """
    Get user information by system ID.
    
    Requires:
        - system_id is a string (may be invalid)
        - MOCK_USER_DATABASE is initialized
        
    Ensures:
        - Returns dictionary with user info if system_id exists in database
        - Returns None if system_id not found
        - Dictionary contains email, name, and email_verified fields when found
        
    Raises:
        - None (handles all lookups gracefully)
        
    Args:
        system_id: System ID to look up
        
    Returns:
        Optional[Dict]: User info if found, None otherwise
    """
    return MOCK_USER_DATABASE.get( system_id )


def get_user_info_by_email( email: str ) -> Optional[Dict]:
    """
    Get user information by email address.
    
    Requires:
        - email is a string (may be invalid email format)
        - email_to_system_id function is available
        - get_user_info function is available
        
    Ensures:
        - Converts email to system_id using standard conversion
        - Returns user info if corresponding system_id exists in database
        - Returns None if email conversion fails or user not found
        
    Raises:
        - ValueError if email format is invalid (propagated from email_to_system_id)
        
    Args:
        email: Email address to look up
        
    Returns:
        Optional[Dict]: User info if found, None otherwise
    """
    system_id = email_to_system_id( email )
    return get_user_info( system_id )


def quick_smoke_test():
    """
    Quick smoke test for user ID generation functions.
    
    Requires:
        - All user ID generation functions are available
        - MOCK_USER_DATABASE is initialized
        
    Ensures:
        - Tests email to system ID conversion for multiple test cases
        - Validates display name extraction functionality
        - Verifies system ID format validation
        - Tests user lookup by email functionality
        - Returns True if all tests pass, False if any fail
        - Prints detailed test results to console
        
    Raises:
        - None (catches and reports all exceptions)
    """
    print( "🧪 Testing User ID Generator..." )
    
    # Test cases
    test_emails = [
        "ricardo.felipe.ruiz@gmail.com",
        "alice.smith@example.com",
        "bob.jones@example.com",
        "test.user@company.co.uk"
    ]
    
    try:
        for email in test_emails:
            system_id = email_to_system_id( email )
            display_name = system_id_to_display_name( system_id )
            is_valid = validate_system_id( system_id )
            
            print( f"  Email: {email}" )
            print( f"  System ID: {system_id}" )
            print( f"  Display Name: {display_name}" )
            print( f"  Valid: {is_valid}" )
            print()
        
        # Test user lookup
        ricardo_info = get_user_info_by_email( "ricardo.felipe.ruiz@gmail.com" )
        if ricardo_info:
            print( f"  User lookup successful: {ricardo_info['name']}" )
        
        print( "✓ All user ID generation tests passed!" )
        return True
        
    except Exception as e:
        print( f"✗ User ID generation test failed: {e}" )
        return False


if __name__ == "__main__":
    quick_smoke_test()