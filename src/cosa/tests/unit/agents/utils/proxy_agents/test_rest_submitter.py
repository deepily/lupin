"""
Unit tests for cosa/agents/utils/proxy_agents/rest_submitter.py.

The only external seam is `requests.post` — boundary-mocked, so NO HTTP request
leaves the process. ZERO API spend.
"""
from unittest.mock import MagicMock, patch

import requests

import cosa.agents.utils.proxy_agents.rest_submitter as mod
from cosa.agents.utils.proxy_agents.rest_submitter import submit_notification_response


def _post_resp( status_code=200, json_data=None, text="" ):
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = json_data or { "status": "ok", "message": "done" }
    r.text = text
    return r


def test_submit_success_returns_true():
    with patch.object( mod.requests, "post", return_value=_post_resp( 200 ) ) as m:
        assert submit_notification_response( "nid", "answer" ) is True
        # url + payload shape
        assert m.call_args[ 0 ][ 0 ].endswith( "/api/notify/response" )
        assert m.call_args[ 1 ][ "json" ] == { "notification_id": "nid", "response_value": "answer" }


def test_submit_success_verbose_prints_and_returns_true( capsys ):
    with patch.object( mod.requests, "post", return_value=_post_resp( 200, { "status": "queued", "message": "ok" } ) ):
        assert submit_notification_response( "nid", "answer", verbose=True ) is True
    assert "API response" in capsys.readouterr().out


def test_submit_non_200_returns_false():
    with patch.object( mod.requests, "post", return_value=_post_resp( 500, text="boom" ) ):
        assert submit_notification_response( "nid", "answer" ) is False


def test_submit_connection_error_returns_false():
    with patch.object( mod.requests, "post", side_effect=requests.ConnectionError( "down" ) ):
        assert submit_notification_response( "nid", "answer" ) is False


def test_submit_timeout_returns_false():
    with patch.object( mod.requests, "post", side_effect=requests.Timeout( "slow" ) ):
        assert submit_notification_response( "nid", "answer" ) is False


def test_submit_generic_exception_returns_false():
    with patch.object( mod.requests, "post", side_effect=RuntimeError( "weird" ) ):
        assert submit_notification_response( "nid", "answer" ) is False
