#!/usr/bin/env python3
"""
Unit tests for how a live-pipeline smoke reads the WebSocket session id.

The debug route is admin-only. A missing or refused admin account must stop the run,
because a quiet fallback id would hide the cause.
"""

from unittest.mock import MagicMock, patch

import pytest

import tests.smoke.utilities.live_pipeline_base as lpb
from tests.smoke.utilities.live_pipeline_base import LivePipelineTestBase


class _Harness( LivePipelineTestBase ):
    """Minimal concrete subclass; skips the base setup."""
    BASE_URL = "http://test-server"

    def __init__( self ):
        pass


def _resp( status, body=None ):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = body if body is not None else {}
    r.text = ""
    return r


def test_unset_admin_credentials_raise_not_fallback( monkeypatch ):
    monkeypatch.delenv( "LUPIN_TEST_ADMIN_EMAIL", raising=False )
    monkeypatch.delenv( "LUPIN_TEST_ADMIN_PASSWORD", raising=False )
    with pytest.raises( RuntimeError, match="LUPIN_TEST_ADMIN_EMAIL" ):
        _Harness()._get_websocket_session_id( {} )


def test_refused_state_request_raises( monkeypatch ):
    monkeypatch.setenv( "LUPIN_TEST_ADMIN_EMAIL", "a@x.test" )
    monkeypatch.setenv( "LUPIN_TEST_ADMIN_PASSWORD", "pw" )
    login = _resp( 200, { "tokens": { "access_token": "tok" } } )
    with patch( "tests.smoke.utilities.embedded_proxy.requests.post", return_value=login ), \
         patch.object( lpb.requests, "get", return_value=_resp( 403 ) ):
        with pytest.raises( RuntimeError, match="403" ):
            _Harness()._get_websocket_session_id( {} )


def test_admin_state_request_returns_first_session( monkeypatch ):
    monkeypatch.setenv( "LUPIN_TEST_ADMIN_EMAIL", "a@x.test" )
    monkeypatch.setenv( "LUPIN_TEST_ADMIN_PASSWORD", "pw" )
    login = _resp( 200, { "tokens": { "access_token": "tok" } } )
    with patch( "tests.smoke.utilities.embedded_proxy.requests.post", return_value=login ), \
         patch.object( lpb.requests, "get", return_value=_resp( 200, { "sessions": { "s-1": {} } } ) ) as g:
        assert _Harness()._get_websocket_session_id( {} ) == "s-1"
    assert g.call_args.kwargs[ "headers" ] == { "Authorization": "Bearer tok" }
