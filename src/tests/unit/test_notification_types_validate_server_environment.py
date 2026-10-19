"""
Unit tests for validate_server_environment.

It is the one URL check that notify_user and notify_user_async both delegate to.
"""

from unittest.mock import patch

import pytest

from lupin_cli.notifications import notification_types as nt
from lupin_cli.notifications import notify_user, notify_user_async


def run( monkeypatch, url, capsys ):
    if url is None: monkeypatch.delenv( nt.ENV_SERVER_URL, raising=False )
    else: monkeypatch.setenv( nt.ENV_SERVER_URL, url )
    result = nt.validate_server_environment()
    return result, capsys.readouterr().out


class TestValidateServerEnvironment:

    def test_a_well_formed_url_passes_and_is_echoed( self, monkeypatch, capsys ):
        result, out = run( monkeypatch, "https://valid-server.com:8080", capsys )
        assert result is True
        assert out == "✅ Environment validation passed\n  Server URL: https://valid-server.com:8080\n"

    def test_an_unset_variable_falls_back_to_the_default_url( self, monkeypatch, capsys ):
        result, out = run( monkeypatch, None, capsys )
        assert result is True
        assert f"  Server URL: {nt.DEFAULT_SERVER_URL}" in out

    @pytest.mark.parametrize( "bad", [ "ftp://x.com", "localhost:7999", "" ] )
    def test_a_url_without_an_http_scheme_fails_with_the_scheme_message( self, monkeypatch, capsys, bad ):
        result, out = run( monkeypatch, bad, capsys )
        assert result is False
        assert out.startswith( "❌ Environment validation failed:\n" )
        assert f"  - {nt.ENV_SERVER_URL} must start with http:// or https://\n" in out

    def test_a_scheme_with_no_host_fails_with_the_format_message_only( self, monkeypatch, capsys ):
        result, out = run( monkeypatch, "http://", capsys )
        assert result is False
        assert out == "❌ Environment validation failed:\n  - Invalid server URL format: http://\n"

    def test_a_bad_scheme_and_no_host_report_both_issues( self, monkeypatch, capsys ):
        result, out = run( monkeypatch, "ftp://", capsys )
        assert result is False
        assert "must start with http:// or https://" in out and "Invalid server URL format: ftp://" in out

    def test_a_parse_exception_is_reported_as_an_issue( self, monkeypatch, capsys ):
        with patch( "urllib.parse.urlparse", side_effect=Exception( "URL parsing failed" ) ):
            result, out = run( monkeypatch, "http://ok.com", capsys )
        assert result is False
        assert "  - Error parsing server URL: URL parsing failed\n" in out


class TestBothCliWrappersDelegate:

    @pytest.mark.parametrize( "module", [ notify_user, notify_user_async ] )
    @pytest.mark.parametrize( "answer", [ True, False ] )
    def test_validate_environment_returns_the_shared_helpers_answer( self, module, answer ):
        with patch.object( module, "validate_server_environment", return_value=answer ) as helper:
            assert module.validate_environment() is answer
        helper.assert_called_once_with()
