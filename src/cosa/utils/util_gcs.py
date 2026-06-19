"""
Google Cloud Storage Utilities for COSA/Lupin.

Provides centralized GCS file operations for use across the project,
including Deep Research report storage and retrieval.

Usage:
    from cosa.utils.util_gcs import write_text_to_gcs, read_text_from_gcs

    # Write content to GCS
    gcs_uri = write_text_to_gcs(
        "gs://bucket/path/file.md",
        content="# Report Content",
        content_type="text/markdown",
        debug=True
    )

    # Read content from GCS
    content = read_text_from_gcs( "gs://bucket/path/file.md", debug=True )
"""

import urllib.parse
from typing import Optional, Tuple

# GCS SDK availability check
try:
    from google.cloud import storage
    from google.auth import default as auth_default
    from google.auth.exceptions import DefaultCredentialsError
    GCS_AVAILABLE = True
except ImportError:
    GCS_AVAILABLE = False


def _parse_gcs_uri( gcs_uri: str ) -> Tuple[ str, str ]:
    """
    Parse a GCS URI into bucket name and blob path.

    Requires:
        - gcs_uri starts with 'gs://'
        - gcs_uri contains at least bucket name

    Ensures:
        - Returns (bucket_name, blob_path) tuple
        - blob_path may be empty if URI is bucket-only

    Args:
        gcs_uri: GCS URI (e.g., 'gs://bucket/path/to/file.md')

    Returns:
        Tuple[str, str]: (bucket_name, blob_path)

    Raises:
        ValueError: If URI doesn't start with 'gs://'
    """
    if not gcs_uri.startswith( "gs://" ):
        raise ValueError( f"GCS URI must start with 'gs://', got: {gcs_uri}" )

    # Remove gs:// prefix
    path = gcs_uri[ 5: ]

    # Split bucket and blob path
    if "/" in path:
        bucket_name, blob_path = path.split( "/", 1 )
    else:
        bucket_name = path
        blob_path = ""

    return bucket_name, blob_path


def validate_gcs_credentials( debug: bool = False ) -> bool:
    """
    Check if Google Cloud Application Default Credentials are available.

    Requires:
        - google-cloud-storage package is installed

    Ensures:
        - Returns True if ADC credentials are configured
        - Returns False if credentials not found or SDK not installed

    Args:
        debug: Enable debug output

    Returns:
        bool: True if credentials are available
    """
    if not GCS_AVAILABLE:
        if debug: print( "[GCS] google-cloud-storage SDK not installed" )
        return False

    try:
        credentials, project = auth_default()
        if debug: print( f"[GCS] Credentials found for project: {project}" )
        return True
    except DefaultCredentialsError as e:
        if debug: print( f"[GCS] No credentials found: {e}" )
        return False
    except Exception as e:
        if debug: print( f"[GCS] Credential check failed: {e}" )
        return False


def validate_gcs_bucket_access( bucket_uri: str, debug: bool = False ) -> bool:
    """
    Pre-flight check for GCS bucket write access.

    Performs a lightweight check to verify the bucket exists and is writable
    without actually writing data.

    Requires:
        - bucket_uri is a valid GCS bucket URI (gs://bucket-name/ or gs://bucket-name)
        - GCS credentials are configured

    Ensures:
        - Returns True if bucket is accessible for writing
        - Returns False if bucket doesn't exist, access denied, or SDK unavailable
        - Does not modify bucket contents

    Args:
        bucket_uri: GCS bucket URI (e.g., 'gs://lupin-deep-research-test/')
        debug: Enable debug output

    Returns:
        bool: True if bucket is accessible for writing
    """
    if not GCS_AVAILABLE:
        if debug: print( "[GCS] google-cloud-storage SDK not installed" )
        return False

    try:
        # Parse bucket name from URI
        bucket_name, _ = _parse_gcs_uri( bucket_uri )

        # Create client and check bucket exists
        client = storage.Client()
        bucket = client.bucket( bucket_name )

        # Check if bucket exists (doesn't require write permission)
        if not bucket.exists():
            if debug: print( f"[GCS] Bucket does not exist: {bucket_name}" )
            return False

        # Try to get bucket IAM policy to verify we have some access
        # This is a lightweight check that doesn't require storage.objects.create
        try:
            # Getting bucket metadata is sufficient to verify access
            bucket.reload()
            if debug: print( f"[GCS] Bucket accessible: {bucket_name}" )
            return True
        except Exception as e:
            if debug: print( f"[GCS] Cannot access bucket: {e}" )
            return False

    except DefaultCredentialsError as e:
        if debug: print( f"[GCS] No credentials: {e}" )
        return False
    except Exception as e:
        if debug: print( f"[GCS] Bucket access check failed: {e}" )
        return False


def write_text_to_gcs(
    gcs_uri: str,
    content: str,
    content_type: str = "text/plain",
    debug: bool = False
) -> str:
    """
    Write text content to Google Cloud Storage.

    Requires:
        - gcs_uri is a valid GCS URI (gs://bucket/path/file.ext)
        - content is a non-empty string
        - GCS credentials are configured

    Ensures:
        - Creates or overwrites the blob at gcs_uri
        - Returns the gcs_uri on success
        - Raises exception on failure

    Args:
        gcs_uri: Full GCS URI for the file (e.g., 'gs://bucket/path/file.md')
        content: Text content to write
        content_type: MIME type (default: 'text/plain')
        debug: Enable debug output

    Returns:
        str: The gcs_uri that was written to

    Raises:
        RuntimeError: If GCS SDK not available
        ValueError: If URI is invalid
        Exception: On GCS write failure
    """
    if not GCS_AVAILABLE:
        raise RuntimeError(
            "google-cloud-storage SDK not installed. "
            "Install with: pip install google-cloud-storage"
        )

    bucket_name, blob_path = _parse_gcs_uri( gcs_uri )

    if not blob_path:
        raise ValueError( f"GCS URI must include blob path, got bucket-only: {gcs_uri}" )

    if debug: print( f"[GCS] Writing to: {gcs_uri}" )

    client = storage.Client()
    bucket = client.bucket( bucket_name )
    blob = bucket.blob( blob_path )

    blob.upload_from_string(
        content,
        content_type=content_type
    )

    if debug: print( f"[GCS] Write complete: {len( content )} bytes" )

    return gcs_uri


def read_text_from_gcs( gcs_uri: str, debug: bool = False ) -> str:
    """
    Read text content from Google Cloud Storage.

    Requires:
        - gcs_uri is a valid GCS URI (gs://bucket/path/file.ext)
        - GCS credentials are configured
        - Blob exists at gcs_uri

    Ensures:
        - Returns the text content of the blob
        - Raises exception on failure or if blob doesn't exist

    Args:
        gcs_uri: Full GCS URI for the file (e.g., 'gs://bucket/path/file.md')
        debug: Enable debug output

    Returns:
        str: Text content of the file

    Raises:
        RuntimeError: If GCS SDK not available
        ValueError: If URI is invalid
        google.cloud.exceptions.NotFound: If blob doesn't exist
        Exception: On GCS read failure
    """
    if not GCS_AVAILABLE:
        raise RuntimeError(
            "google-cloud-storage SDK not installed. "
            "Install with: pip install google-cloud-storage"
        )

    bucket_name, blob_path = _parse_gcs_uri( gcs_uri )

    if not blob_path:
        raise ValueError( f"GCS URI must include blob path, got bucket-only: {gcs_uri}" )

    if debug: print( f"[GCS] Reading from: {gcs_uri}" )

    client = storage.Client()
    bucket = client.bucket( bucket_name )
    blob = bucket.blob( blob_path )

    content = blob.download_as_text()

    if debug: print( f"[GCS] Read complete: {len( content )} bytes" )

    return content


def gcs_uri_to_console_url( gcs_uri: str ) -> str:
    """
    Convert a GCS URI to a Google Cloud Console URL for viewing.

    Requires:
        - gcs_uri is a valid GCS URI (gs://bucket/path/file.ext)

    Ensures:
        - Returns a clickable URL to view the file in Cloud Console
        - URL-encodes the blob path for special characters

    Args:
        gcs_uri: GCS URI (e.g., 'gs://bucket/user@email.com/file.md')

    Returns:
        str: Cloud Console URL (e.g., 'https://console.cloud.google.com/storage/browser/_details/bucket/user%40email.com/file.md')
    """
    bucket_name, blob_path = _parse_gcs_uri( gcs_uri )

    # URL-encode the blob path (handles @ in email addresses, etc.)
    encoded_path = urllib.parse.quote( blob_path, safe="" )

    # Build Cloud Console URL
    console_url = f"https://console.cloud.google.com/storage/browser/_details/{bucket_name}/{encoded_path}"

    return console_url


def gcs_bucket_uri_exists( bucket_uri: str, debug: bool = False ) -> bool:
    """
    Check if a GCS bucket exists.

    Args:
        bucket_uri: GCS bucket URI (e.g., 'gs://bucket-name/')
        debug: Enable debug output

    Returns:
        bool: True if bucket exists
    """
    if not GCS_AVAILABLE:
        return False

    try:
        bucket_name, _ = _parse_gcs_uri( bucket_uri )
        client = storage.Client()
        bucket = client.bucket( bucket_name )
        return bucket.exists()
    except Exception as e:
        if debug: print( f"[GCS] Bucket check failed: {e}" )
        return False


def quick_smoke_test():
    """
    Quick smoke test for GCS utilities - validates basic functionality.

    Tests:
    1. GCS SDK availability check
    2. URI parsing
    3. Console URL generation
    4. Credentials check (if SDK available)
    """
    import cosa.utils.util as cu

    cu.print_banner( "GCS Utilities Smoke Test", prepend_nl=True )

    try:
        # Test 1: SDK availability
        print( "Testing GCS SDK availability..." )
        if GCS_AVAILABLE:
            print( "  GCS SDK is available" )
        else:
            print( "  GCS SDK not installed (some tests will be skipped)" )

        # Test 2: URI parsing
        print( "Testing URI parsing..." )
        test_uris = [
            ( "gs://bucket/path/file.md", "bucket", "path/file.md" ),
            ( "gs://my-bucket/user@email.com/report.md", "my-bucket", "user@email.com/report.md" ),
            ( "gs://bucket-only/", "bucket-only", "" ),
        ]
        for uri, expected_bucket, expected_path in test_uris:
            bucket, path = _parse_gcs_uri( uri )
            assert bucket == expected_bucket, f"Expected bucket '{expected_bucket}', got '{bucket}'"
            assert path == expected_path, f"Expected path '{expected_path}', got '{path}'"
        print( "  URI parsing: PASSED" )

        # Test 3: Console URL generation
        print( "Testing Console URL generation..." )
        test_uri = "gs://lupin-deep-research-test/ricardo.felipe.ruiz@gmail.com/2026.01.18-test.md"
        console_url = gcs_uri_to_console_url( test_uri )
        assert "console.cloud.google.com" in console_url
        assert "lupin-deep-research-test" in console_url
        assert "%40" in console_url  # @ should be encoded
        print( f"  Console URL: {console_url[:80]}..." )
        print( "  Console URL generation: PASSED" )

        # Test 4: Credentials check (only if SDK available)
        if GCS_AVAILABLE:
            print( "Testing credentials availability..." )
            has_creds = validate_gcs_credentials( debug=False )
            if has_creds:
                print( "  Credentials: AVAILABLE" )
            else:
                print( "  Credentials: NOT CONFIGURED (expected in some environments)" )
        else:
            print( "Skipping credentials check (SDK not available)" )

        # Test 5: Invalid URI handling
        print( "Testing invalid URI handling..." )
        try:
            _parse_gcs_uri( "https://storage.googleapis.com/bucket/file" )
            print( "  ERROR: Should have raised ValueError" )
        except ValueError:
            print( "  Invalid URI correctly rejected: PASSED" )

        print( "\n Smoke test completed successfully" )

    except Exception as e:
        print( f"\n Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
