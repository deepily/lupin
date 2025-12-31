"""
GCS credential validation utilities for integration tests.

This module provides utilities to validate Google Cloud Storage (GCS) credentials
before running integration tests that depend on GCS access. This prevents cryptic
test failures and provides clear remediation instructions.

Usage:
    from gcs_utils import check_gcs_credentials, validate_gcs_or_skip

    # In pytest fixtures:
    is_valid, message = check_gcs_credentials()
    if not is_valid:
        pytest.skip( message )

    # Or use the helper:
    validate_gcs_or_skip()
"""

from typing import Tuple


def check_gcs_credentials() -> Tuple[bool, str]:
    """
    Validate GCS credentials using google.auth library.

    Attempts to:
    1. Get default credentials via google.auth.default()
    2. Refresh the token to ensure it's not expired
    3. Catch specific error patterns (invalid_rapt, invalid_grant, etc.)

    This validation happens at pytest session start (once), not per test,
    so the performance impact is minimal (~200ms).

    Requires:
        - google-auth library (already installed as LanceDB dependency)
        - Either:
          - GOOGLE_APPLICATION_CREDENTIALS env var set, OR
          - gcloud auth application-default login completed

    Ensures:
        - Returns (True, success_message) if credentials valid
        - Returns (False, error_message) if credentials invalid/missing/expired
        - Error messages include remediation steps

    Returns:
        Tuple of (is_valid: bool, message: str)
        - is_valid: True if credentials work, False otherwise
        - message: User-friendly message explaining status
    """
    try:
        from google.auth import default
        from google.auth.exceptions import DefaultCredentialsError
        from google.auth.transport.requests import Request

        # Get default credentials
        # This reads from:
        # 1. GOOGLE_APPLICATION_CREDENTIALS env var, or
        # 2. ~/.config/gcloud/application_default_credentials.json
        credentials, project = default()

        # Attempt token refresh to validate they're not expired
        # This will raise an exception if the RAPT token is invalid
        if not credentials.valid:
            credentials.refresh( Request() )

        project_info = f"project: {project}" if project else "no project detected"
        return True, f"✓ GCS credentials valid ({project_info})"

    except DefaultCredentialsError as e:
        return False, (
            "GCS credentials not found.\n"
            "\n"
            "To fix this:\n"
            "  gcloud auth application-default login\n"
            "\n"
            f"Details: {e}"
        )

    except Exception as e:
        error_str = str( e )

        # Check for RAPT (Risk-based Authentication Protection Token) errors
        # This is Google's security mechanism requiring periodic re-authentication
        if "invalid_rapt" in error_str or "reauth" in error_str.lower():
            return False, (
                "GCS credentials expired (RAPT token invalid).\n"
                "\n"
                "This happens when Google's security policy requires re-authentication.\n"
                "\n"
                "To fix this:\n"
                "  gcloud auth application-default login\n"
                "\n"
                "Then re-run the tests."
            )

        # Check for general OAuth2 invalid_grant errors
        if "invalid_grant" in error_str:
            return False, (
                "GCS credentials invalid (OAuth2 token rejected).\n"
                "\n"
                "To fix this:\n"
                "  gcloud auth application-default login\n"
                "\n"
                f"Error details: {error_str}"
            )

        # Check for network/connectivity errors
        if "connection" in error_str.lower() or "timeout" in error_str.lower():
            return False, (
                "GCS credential validation failed due to network error.\n"
                "\n"
                "Check your internet connection and try again.\n"
                "\n"
                f"Error: {e}"
            )

        # Generic error catch-all
        return False, (
            "GCS credential validation failed.\n"
            "\n"
            "Try re-authenticating:\n"
            "  gcloud auth application-default login\n"
            "\n"
            f"Error: {e}"
        )


def validate_gcs_or_skip():
    """
    Validate GCS credentials, skip current test if invalid.

    This is a convenience function that calls check_gcs_credentials()
    and raises pytest.skip() if credentials are invalid.

    Call this from pytest fixtures or test functions that require GCS access.

    Usage:
        def test_something_with_gcs():
            validate_gcs_or_skip()
            # Test code that needs GCS...

    Raises:
        pytest.skip: If credentials are invalid, with detailed message
    """
    import pytest

    is_valid, message = check_gcs_credentials()

    if not is_valid:
        pytest.skip(
            f"\n{'='*70}\n"
            f"GCS Credentials Not Available\n"
            f"{'='*70}\n\n"
            f"{message}\n\n"
            f"These tests require GCS authentication.\n"
            f"To enable them, authenticate with:\n"
            f"  gcloud auth application-default login\n"
            f"{'='*70}\n"
        )
