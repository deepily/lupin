"""
Unit tests for cosa.utils.util_gcs (Google Cloud Storage helpers).

The google-cloud-storage SDK and its auth surface are fully mocked, so the
tests touch no real GCS bucket, credentials, or network. Both the
SDK-available and SDK-unavailable code paths are exercised by toggling the
module-level GCS_AVAILABLE flag.

Assertions harvested and strengthened from the module's quick_smoke_test()
(URI parsing, console-URL encoding, invalid-URI rejection) plus the
credential/bucket/read/write branches the smoke test could not reach.
"""

import unittest
from unittest.mock import patch, MagicMock

import cosa.utils.util_gcs as gcs
from cosa.utils.util_gcs import (
    _parse_gcs_uri,
    validate_gcs_credentials,
    validate_gcs_bucket_access,
    write_text_to_gcs,
    read_text_from_gcs,
    gcs_uri_to_console_url,
    gcs_bucket_uri_exists,
)


class _FakeDefaultCredentialsError( Exception ):
    """Stand-in for google.auth.exceptions.DefaultCredentialsError."""


# CAUSE-B (task 51980026): the tests below exercise the GCS_AVAILABLE-True paths by
# patching gcs.auth_default / gcs.storage / gcs.DefaultCredentialsError. Those module
# globals are bound ONLY when `from google.cloud import storage` / `from google.auth
# import default` succeed at import time. When google-cloud-storage is NOT installed in
# the test venv (the current state), GCS_AVAILABLE is False and those names are unbound,
# so patch.object() raises AttributeError before the test body runs. This is NOT a
# product defect (util_gcs gracefully gates every entry point on GCS_AVAILABLE) and NOT a
# stale test — it is a genuine optional-dependency gap in the test environment. We skip
# the SDK-requiring tests when the SDK is absent (the SDK-UNAVAILABLE-path tests in each
# class still run). Coverage-preserving remediation = add google-cloud-storage to the
# test dependencies (a dependency decision, deferred to a maintainer).
_requires_gcs_sdk = unittest.skipUnless(
    gcs.GCS_AVAILABLE,
    "requires google-cloud-storage installed in the test venv — GCS_AVAILABLE-True paths "
    "patch gcs.auth_default/storage/DefaultCredentialsError, which are unbound when the "
    "SDK is absent (task 51980026 CAUSE-B; remediation: add google-cloud-storage to test deps)"
)


class TestParseGcsUri( unittest.TestCase ):
    """
    URI parsing: prefix validation + bucket/blob split.

    Ensures:
        - 'gs://bucket/blob' splits into (bucket, blob)
        - bucket-only URIs yield an empty blob path
        - non-'gs://' URIs raise ValueError
    """

    def test_parse_bucket_and_blob( self ):
        self.assertEqual(
            _parse_gcs_uri( "gs://bucket/path/file.md" ), ( "bucket", "path/file.md" )
        )

    def test_parse_bucket_only_yields_empty_blob( self ):
        self.assertEqual( _parse_gcs_uri( "gs://bucket-only/" ), ( "bucket-only", "" ) )

    def test_parse_bucket_only_no_trailing_slash( self ):
        self.assertEqual( _parse_gcs_uri( "gs://bucket-only" ), ( "bucket-only", "" ) )

    def test_parse_rejects_non_gs_uri( self ):
        with self.assertRaises( ValueError ):
            _parse_gcs_uri( "https://storage.googleapis.com/bucket/file" )


class TestConsoleUrl( unittest.TestCase ):
    """
    gcs_uri_to_console_url() — pure URL construction with encoding.

    Ensures:
        - produces a Cloud Console browser URL
        - special characters in the blob path (e.g. '@') are percent-encoded
    """

    def test_console_url_encodes_at_sign( self ):
        url = gcs_uri_to_console_url( "gs://b/user@email.com/report.md" )
        self.assertIn( "console.cloud.google.com", url )
        self.assertIn( "b/", url )
        self.assertIn( "%40", url )          # '@' encoded
        self.assertNotIn( "@", url )


class TestValidateCredentials( unittest.TestCase ):
    """
    validate_gcs_credentials() across SDK-availability + auth outcomes.

    Ensures:
        - SDK unavailable => False
        - auth_default success => True
        - DefaultCredentialsError => False
        - any other exception => False
    """

    def test_sdk_unavailable_returns_false( self ):
        with patch.object( gcs, "GCS_AVAILABLE", False ):
            self.assertFalse( validate_gcs_credentials( debug=True ) )

    @_requires_gcs_sdk
    def test_credentials_present_returns_true( self ):
        with patch.object( gcs, "GCS_AVAILABLE", True ), \
             patch.object( gcs, "auth_default", return_value=( MagicMock(), "proj" ) ):
            self.assertTrue( validate_gcs_credentials( debug=True ) )

    @_requires_gcs_sdk
    def test_default_credentials_error_returns_false( self ):
        with patch.object( gcs, "GCS_AVAILABLE", True ), \
             patch.object( gcs, "DefaultCredentialsError", _FakeDefaultCredentialsError ), \
             patch.object( gcs, "auth_default", side_effect=_FakeDefaultCredentialsError( "nope" ) ):
            self.assertFalse( validate_gcs_credentials( debug=True ) )

    @_requires_gcs_sdk
    def test_unexpected_exception_returns_false( self ):
        with patch.object( gcs, "GCS_AVAILABLE", True ), \
             patch.object( gcs, "DefaultCredentialsError", _FakeDefaultCredentialsError ), \
             patch.object( gcs, "auth_default", side_effect=RuntimeError( "boom" ) ):
            self.assertFalse( validate_gcs_credentials( debug=True ) )


class TestValidateBucketAccess( unittest.TestCase ):
    """
    validate_gcs_bucket_access() — existence + reachability branches.

    Ensures:
        - SDK unavailable => False
        - bucket exists and reload() succeeds => True
        - bucket does not exist => False
        - reload() raises => False (inner except)
        - DefaultCredentialsError => False
        - any other outer exception => False
    """

    def _client_with_bucket( self, bucket ):
        client = MagicMock()
        client.bucket.return_value = bucket
        storage = MagicMock()
        storage.Client.return_value = client
        return storage

    def test_sdk_unavailable_returns_false( self ):
        with patch.object( gcs, "GCS_AVAILABLE", False ):
            self.assertFalse( validate_gcs_bucket_access( "gs://b/", debug=True ) )

    @_requires_gcs_sdk
    def test_accessible_bucket_returns_true( self ):
        bucket = MagicMock()
        bucket.exists.return_value = True
        with patch.object( gcs, "GCS_AVAILABLE", True ), \
             patch.object( gcs, "storage", self._client_with_bucket( bucket ) ):
            self.assertTrue( validate_gcs_bucket_access( "gs://b/", debug=True ) )
        bucket.reload.assert_called_once()

    @_requires_gcs_sdk
    def test_missing_bucket_returns_false( self ):
        bucket = MagicMock()
        bucket.exists.return_value = False
        with patch.object( gcs, "GCS_AVAILABLE", True ), \
             patch.object( gcs, "storage", self._client_with_bucket( bucket ) ):
            self.assertFalse( validate_gcs_bucket_access( "gs://b/", debug=True ) )

    @_requires_gcs_sdk
    def test_reload_failure_returns_false( self ):
        bucket = MagicMock()
        bucket.exists.return_value = True
        bucket.reload.side_effect = RuntimeError( "iam denied" )
        with patch.object( gcs, "GCS_AVAILABLE", True ), \
             patch.object( gcs, "storage", self._client_with_bucket( bucket ) ):
            self.assertFalse( validate_gcs_bucket_access( "gs://b/", debug=True ) )

    @_requires_gcs_sdk
    def test_default_credentials_error_returns_false( self ):
        storage = MagicMock()
        storage.Client.side_effect = _FakeDefaultCredentialsError( "no creds" )
        with patch.object( gcs, "GCS_AVAILABLE", True ), \
             patch.object( gcs, "DefaultCredentialsError", _FakeDefaultCredentialsError ), \
             patch.object( gcs, "storage", storage ):
            self.assertFalse( validate_gcs_bucket_access( "gs://b/", debug=True ) )

    @_requires_gcs_sdk
    def test_outer_exception_returns_false( self ):
        storage = MagicMock()
        storage.Client.side_effect = RuntimeError( "network" )
        with patch.object( gcs, "GCS_AVAILABLE", True ), \
             patch.object( gcs, "DefaultCredentialsError", _FakeDefaultCredentialsError ), \
             patch.object( gcs, "storage", storage ):
            self.assertFalse( validate_gcs_bucket_access( "gs://b/", debug=True ) )


class TestWriteText( unittest.TestCase ):
    """
    write_text_to_gcs() — guard rails + happy path.

    Ensures:
        - SDK unavailable => RuntimeError
        - bucket-only URI => ValueError
        - valid URI => uploads via blob and returns the URI
    """

    def test_sdk_unavailable_raises_runtime_error( self ):
        with patch.object( gcs, "GCS_AVAILABLE", False ):
            with self.assertRaises( RuntimeError ):
                write_text_to_gcs( "gs://b/f.md", "hi" )

    @_requires_gcs_sdk
    def test_bucket_only_uri_raises_value_error( self ):
        with patch.object( gcs, "GCS_AVAILABLE", True ), \
             patch.object( gcs, "storage", MagicMock() ):
            with self.assertRaises( ValueError ):
                write_text_to_gcs( "gs://bucket-only/", "hi" )

    @_requires_gcs_sdk
    def test_write_uploads_and_returns_uri( self ):
        blob   = MagicMock()
        bucket = MagicMock()
        bucket.blob.return_value = blob
        client = MagicMock()
        client.bucket.return_value = bucket
        storage = MagicMock()
        storage.Client.return_value = client
        with patch.object( gcs, "GCS_AVAILABLE", True ), \
             patch.object( gcs, "storage", storage ):
            uri = write_text_to_gcs(
                "gs://b/path/f.md", "content", content_type="text/markdown", debug=True
            )
        self.assertEqual( uri, "gs://b/path/f.md" )
        blob.upload_from_string.assert_called_once_with(
            "content", content_type="text/markdown"
        )


class TestReadText( unittest.TestCase ):
    """
    read_text_from_gcs() — guard rails + happy path.

    Ensures:
        - SDK unavailable => RuntimeError
        - bucket-only URI => ValueError
        - valid URI => returns downloaded text
    """

    def test_sdk_unavailable_raises_runtime_error( self ):
        with patch.object( gcs, "GCS_AVAILABLE", False ):
            with self.assertRaises( RuntimeError ):
                read_text_from_gcs( "gs://b/f.md" )

    @_requires_gcs_sdk
    def test_bucket_only_uri_raises_value_error( self ):
        with patch.object( gcs, "GCS_AVAILABLE", True ), \
             patch.object( gcs, "storage", MagicMock() ):
            with self.assertRaises( ValueError ):
                read_text_from_gcs( "gs://bucket-only/" )

    @_requires_gcs_sdk
    def test_read_returns_downloaded_text( self ):
        blob   = MagicMock()
        blob.download_as_text.return_value = "# Report"
        bucket = MagicMock()
        bucket.blob.return_value = blob
        client = MagicMock()
        client.bucket.return_value = bucket
        storage = MagicMock()
        storage.Client.return_value = client
        with patch.object( gcs, "GCS_AVAILABLE", True ), \
             patch.object( gcs, "storage", storage ):
            content = read_text_from_gcs( "gs://b/path/f.md", debug=True )
        self.assertEqual( content, "# Report" )


class TestBucketExists( unittest.TestCase ):
    """
    gcs_bucket_uri_exists() — availability + existence + failure branches.

    Ensures:
        - SDK unavailable => False
        - delegates to bucket.exists() when available
        - any exception => False
    """

    def test_sdk_unavailable_returns_false( self ):
        with patch.object( gcs, "GCS_AVAILABLE", False ):
            self.assertFalse( gcs_bucket_uri_exists( "gs://b/" ) )

    @_requires_gcs_sdk
    def test_returns_bucket_exists_result( self ):
        bucket = MagicMock()
        bucket.exists.return_value = True
        client = MagicMock()
        client.bucket.return_value = bucket
        storage = MagicMock()
        storage.Client.return_value = client
        with patch.object( gcs, "GCS_AVAILABLE", True ), \
             patch.object( gcs, "storage", storage ):
            self.assertTrue( gcs_bucket_uri_exists( "gs://b/" ) )

    @_requires_gcs_sdk
    def test_exception_returns_false( self ):
        storage = MagicMock()
        storage.Client.side_effect = RuntimeError( "boom" )
        with patch.object( gcs, "GCS_AVAILABLE", True ), \
             patch.object( gcs, "storage", storage ):
            self.assertFalse( gcs_bucket_uri_exists( "gs://b/", debug=True ) )


class TestImportFallback( unittest.TestCase ):
    """
    The module-load ImportError fallback (GCS_AVAILABLE = False).

    google-cloud-storage IS installed in this environment, so the fallback is
    normally unreachable. We exercise it hermetically by reloading the module
    with 'google.cloud' shadowed to None (forcing `from google.cloud import
    storage` to raise ImportError), then reload once more to restore the real
    state. No production source is modified.
    """

    @_requires_gcs_sdk
    def test_missing_sdk_sets_unavailable_false( self ):
        import importlib
        import sys

        try:
            with patch.dict( sys.modules, { "google.cloud": None } ):
                importlib.reload( gcs )
                self.assertFalse( gcs.GCS_AVAILABLE )
        finally:
            # Restore the module with the real SDK imports for downstream tests.
            importlib.reload( gcs )
        self.assertTrue( gcs.GCS_AVAILABLE )


if __name__ == "__main__":
    unittest.main()
