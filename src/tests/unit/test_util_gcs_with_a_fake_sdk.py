"""
Unit tests for util_gcs with a fake Google SDK injected.

The venv has no google-cloud-storage, so the module imports with GCS_AVAILABLE False and the
cosa-tier tests skip every SDK-present path. Here the module's source is loaded again under a
private name, with fake `google.*` modules in sys.modules, so those paths run with no dependency.
"""

import importlib.util
import sys
import types
from unittest.mock import MagicMock

import pytest

import cosa.utils.util_gcs as real_gcs


class FakeCredentialsError( Exception ):
    """Stands in for google.auth.exceptions.DefaultCredentialsError."""


@pytest.fixture
def sdk( monkeypatch ):
    """Load util_gcs against fakes; return (module, storage mock, auth mock)."""
    storage_mod = MagicMock( name="storage" )
    auth_default = MagicMock( name="auth_default" )
    google      = types.ModuleType( "google" )
    cloud       = types.ModuleType( "google.cloud" )
    auth        = types.ModuleType( "google.auth" )
    auth_exc    = types.ModuleType( "google.auth.exceptions" )
    cloud.storage                       = storage_mod
    auth.default                        = auth_default
    auth_exc.DefaultCredentialsError    = FakeCredentialsError
    google.cloud, google.auth           = cloud, auth
    for name, mod in ( ( "google", google ), ( "google.cloud", cloud ), ( "google.cloud.storage", storage_mod ),
                       ( "google.auth", auth ), ( "google.auth.exceptions", auth_exc ) ):
        monkeypatch.setitem( sys.modules, name, mod )
    spec = importlib.util.spec_from_file_location( "util_gcs_fake_sdk", real_gcs.__file__ )
    mod  = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( mod )
    assert mod.GCS_AVAILABLE is True
    return mod, storage_mod, auth_default


def test_credentials_found_reports_true( sdk, capsys ):
    """ADC resolves: True, and debug names the project."""
    mod, _, auth_default = sdk
    auth_default.return_value = ( object(), "proj-1" )
    assert mod.validate_gcs_credentials( debug=True ) is True
    assert "proj-1" in capsys.readouterr().out


@pytest.mark.parametrize( "error", [ FakeCredentialsError( "none" ), RuntimeError( "other" ) ] )
def test_credentials_failure_reports_false( sdk, capsys, error ):
    """Missing ADC and any other failure both read False, never raise."""
    mod, _, auth_default = sdk
    auth_default.side_effect = error
    assert mod.validate_gcs_credentials( debug=True ) is False
    assert str( error ) in capsys.readouterr().out


def test_bucket_access_true_only_when_it_exists_and_reloads( sdk ):
    """exists() and reload() both succeed: True, for the bucket the URI names."""
    mod, storage_mod, _ = sdk
    bucket = storage_mod.Client.return_value.bucket.return_value
    bucket.exists.return_value = True
    assert mod.validate_gcs_bucket_access( "gs://b1/", debug=True ) is True
    storage_mod.Client.return_value.bucket.assert_called_once_with( "b1" )
    bucket.reload.assert_called_once_with()


def test_bucket_access_false_when_the_bucket_is_missing( sdk, capsys ):
    """exists() False: False, and reload() is never tried."""
    mod, storage_mod, _ = sdk
    bucket = storage_mod.Client.return_value.bucket.return_value
    bucket.exists.return_value = False
    assert mod.validate_gcs_bucket_access( "gs://b1", debug=True ) is False
    bucket.reload.assert_not_called()
    assert "does not exist: b1" in capsys.readouterr().out


def test_bucket_access_false_when_reload_is_denied( sdk, capsys ):
    """exists() True but reload() raises: False with the cause shown."""
    mod, storage_mod, _ = sdk
    bucket = storage_mod.Client.return_value.bucket.return_value
    bucket.exists.return_value = True
    bucket.reload.side_effect = PermissionError( "denied" )
    assert mod.validate_gcs_bucket_access( "gs://b1", debug=True ) is False
    assert "Cannot access bucket: denied" in capsys.readouterr().out


@pytest.mark.parametrize( "error,expect", [ ( FakeCredentialsError( "nocreds" ), "No credentials: nocreds" ),
                                            ( RuntimeError( "kaput" ), "Bucket access check failed: kaput" ) ] )
def test_bucket_access_false_when_the_client_cannot_be_built( sdk, capsys, error, expect ):
    """Client construction failing reads False and names which kind of failure it was."""
    mod, storage_mod, _ = sdk
    storage_mod.Client.side_effect = error
    assert mod.validate_gcs_bucket_access( "gs://b1", debug=True ) is False
    assert expect in capsys.readouterr().out


def test_write_uploads_the_text_with_its_content_type( sdk, capsys ):
    """The blob path is everything after the bucket; content and type reach upload_from_string."""
    mod, storage_mod, _ = sdk
    client = storage_mod.Client.return_value
    assert mod.write_text_to_gcs( "gs://b1/dir/f.md", "hello", content_type="text/markdown", debug=True ) == "gs://b1/dir/f.md"
    client.bucket.assert_called_once_with( "b1" )
    client.bucket.return_value.blob.assert_called_once_with( "dir/f.md" )
    client.bucket.return_value.blob.return_value.upload_from_string.assert_called_once_with( "hello", content_type="text/markdown" )
    assert "Write complete: 5 bytes" in capsys.readouterr().out


def test_write_and_read_refuse_a_bucket_only_uri( sdk ):
    """No blob path: ValueError before any client is built."""
    mod, storage_mod, _ = sdk
    with pytest.raises( ValueError, match="blob path" ):
        mod.write_text_to_gcs( "gs://b1/", "x" )
    with pytest.raises( ValueError, match="blob path" ):
        mod.read_text_from_gcs( "gs://b1" )
    storage_mod.Client.assert_not_called()


def test_read_returns_the_downloaded_text( sdk, capsys ):
    """download_as_text() is returned verbatim from the named blob."""
    mod, storage_mod, _ = sdk
    blob = storage_mod.Client.return_value.bucket.return_value.blob
    blob.return_value.download_as_text.return_value = "body"
    assert mod.read_text_from_gcs( "gs://b1/a/b.md", debug=True ) == "body"
    blob.assert_called_once_with( "a/b.md" )
    assert "Read complete: 4 bytes" in capsys.readouterr().out


def test_bucket_uri_exists_follows_the_bucket_and_swallows_errors( sdk, capsys ):
    """True and False come from exists(); a failing client reads False."""
    mod, storage_mod, _ = sdk
    bucket = storage_mod.Client.return_value.bucket.return_value
    bucket.exists.return_value = True
    assert mod.gcs_bucket_uri_exists( "gs://b1/" ) is True
    bucket.exists.return_value = False
    assert mod.gcs_bucket_uri_exists( "gs://b1/" ) is False
    storage_mod.Client.side_effect = RuntimeError( "down" )
    assert mod.gcs_bucket_uri_exists( "gs://b1/", debug=True ) is False
    assert "Bucket check failed: down" in capsys.readouterr().out


def test_without_the_sdk_every_entry_point_degrades_or_refuses( monkeypatch, capsys ):
    """GCS_AVAILABLE False: booleans read False, write and read raise RuntimeError naming pip."""
    monkeypatch.setattr( real_gcs, "GCS_AVAILABLE", False )
    assert real_gcs.validate_gcs_credentials( debug=True ) is False
    assert real_gcs.validate_gcs_bucket_access( "gs://b", debug=True ) is False
    assert real_gcs.gcs_bucket_uri_exists( "gs://b" ) is False
    for call in ( lambda: real_gcs.write_text_to_gcs( "gs://b/f", "x" ), lambda: real_gcs.read_text_from_gcs( "gs://b/f" ) ):
        with pytest.raises( RuntimeError, match="pip install google-cloud-storage" ):
            call()
    assert capsys.readouterr().out.count( "SDK not installed" ) == 2


def test_quick_smoke_test_runs_both_credential_branches( sdk, capsys ):
    """The inline smoke passes with the SDK present (creds found, then not) and absent."""
    mod, _, auth_default = sdk
    auth_default.return_value = ( object(), "p" )
    mod.quick_smoke_test()
    assert "Credentials: AVAILABLE" in capsys.readouterr().out
    auth_default.side_effect = FakeCredentialsError( "x" )
    mod.quick_smoke_test()
    out = capsys.readouterr().out
    assert "NOT CONFIGURED" in out and "Smoke test completed successfully" in out


def test_quick_smoke_test_without_the_sdk_skips_the_credential_check( monkeypatch, capsys ):
    """No SDK: the smoke says so and still completes."""
    monkeypatch.setattr( real_gcs, "GCS_AVAILABLE", False )
    real_gcs.quick_smoke_test()
    out = capsys.readouterr().out
    assert "Skipping credentials check" in out and "completed successfully" in out


def test_quick_smoke_test_reports_a_failure_instead_of_raising( monkeypatch, capsys ):
    """An exception inside the smoke is printed with a traceback and swallowed."""
    monkeypatch.setattr( real_gcs, "_parse_gcs_uri", MagicMock( side_effect = RuntimeError( "bad parse" ) ) )
    real_gcs.quick_smoke_test()
    assert "Smoke test failed: bad parse" in capsys.readouterr().out
