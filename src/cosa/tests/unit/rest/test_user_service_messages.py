"""
Pin tests for the exact result tuples of deactivate_user and mark_email_verified.

The sibling file asserts substrings, so the exact wording is fixed here
before the two bodies are merged.
"""

from unittest.mock import patch, MagicMock

import pytest

from cosa.rest.user_service import deactivate_user, mark_email_verified

MODULE = "cosa.rest.user_service"

CASES = [
    ( deactivate_user,     "deactivate",          "User deactivated successfully", "Deactivation failed: " ),
    ( mark_email_verified, "mark_email_verified", "Email verified successfully",   "Email verification failed: " ),
]


@pytest.mark.parametrize( "fn, method, ok_msg, fail_prefix", CASES )
def test_empty_id( fn, method, ok_msg, fail_prefix ):
    """
    Ensures:
        - an empty id returns exactly (False, "User ID required")
    """
    assert fn( "" ) == ( False, "User ID required" )


@pytest.mark.parametrize( "fn, method, ok_msg, fail_prefix", CASES )
def test_bad_uuid( fn, method, ok_msg, fail_prefix ):
    """
    Ensures:
        - a bad id returns exactly (False, "Invalid user ID format"), no session opened
    """
    with patch( f"{MODULE}.get_db" ) as db:
        assert fn( "not-a-uuid" ) == ( False, "Invalid user ID format" )
    db.assert_not_called()


@pytest.mark.parametrize( "fn, method, ok_msg, fail_prefix", CASES )
def test_not_found( fn, method, ok_msg, fail_prefix ):
    """
    Ensures:
        - a falsy repository result returns exactly (False, "User not found")
    """
    uid = "12345678-1234-5678-1234-567812345678"
    with patch( f"{MODULE}.get_db" ), patch( f"{MODULE}.UserRepository" ) as repo_cls:
        getattr( repo_cls.return_value, method ).return_value = None
        assert fn( uid ) == ( False, "User not found" )


@pytest.mark.parametrize( "fn, method, ok_msg, fail_prefix", CASES )
def test_success_calls_the_repository_with_a_uuid( fn, method, ok_msg, fail_prefix ):
    """
    Ensures:
        - returns exactly (True, ok_msg); the named method gets the UUID
    """
    import uuid
    uid = "12345678-1234-5678-1234-567812345678"
    with patch( f"{MODULE}.get_db" ), patch( f"{MODULE}.UserRepository" ) as repo_cls:
        getattr( repo_cls.return_value, method ).return_value = MagicMock()
        assert fn( uid ) == ( True, ok_msg )
        getattr( repo_cls.return_value, method ).assert_called_once_with( uuid.UUID( uid ) )


@pytest.mark.parametrize( "fn, method, ok_msg, fail_prefix", CASES )
def test_other_error( fn, method, ok_msg, fail_prefix ):
    """
    Ensures:
        - any other exception returns exactly (False, fail_prefix + the exception text)
    """
    uid = "12345678-1234-5678-1234-567812345678"
    with patch( f"{MODULE}.get_db" ), patch( f"{MODULE}.UserRepository" ) as repo_cls:
        getattr( repo_cls.return_value, method ).side_effect = Exception( "db down" )
        assert fn( uid ) == ( False, fail_prefix + "db down" )
