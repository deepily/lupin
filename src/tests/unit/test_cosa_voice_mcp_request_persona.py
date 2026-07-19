#!/usr/bin/env python3
"""
Unit tests for the cosa_voice_mcp `request_persona` tool.

Covers three units in src/lupin_mcp/cosa_voice_mcp.py:
    - _persona_error_detail()  — error-body extractor
    - _request_persona()       — the helper holding the HTTP request/swap logic
    - request_persona          — the @mcp.tool wrapper

The `requests` HTTP layer is fully mocked — no live Lupin server is needed.
Every branch of the helper is exercised so the new code holds 100% coverage.

Design: src/rnd/v0.1.7/2026.05.22-voice-persona-request-tool-and-compaction-carry-forward.md
"""
import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest
import requests

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_response( status_code, body=None, text=None ):
    """
    Build a MagicMock mimicking a requests.Response.

    When body is None, .json() raises ValueError (mimics a non-JSON body).
    """
    m = MagicMock()
    m.status_code = status_code
    if body is not None:
        m.json = MagicMock( return_value=body )
        m.text = json.dumps( body ) if text is None else text
    else:
        m.json = MagicMock( side_effect=ValueError( "no json" ) )
        m.text = text or ""
    return m


_FAKE_META   = { "session_id"        : "sess1234-1111-2222-3333-444455556666",
                 "stable_session_id" : "sess1234-1111-2222-3333-444455556666" }
_CREDS_PATCH = "lupin_cli.claude_code.hooks.lib.hook_credentials.get_hook_credentials"
_CREDS       = ( "test@deepily.ai", "secret" )


def _login_ok():
    return _make_response( 200, { "tokens": { "access_token": "fake-jwt" } } )


# ═════════════════════════════════════════════════════════════════════════════
# _persona_error_detail
# ═════════════════════════════════════════════════════════════════════════════

class TestPersonaErrorDetail:

    def test_well_formed_detail_dict_returned( self ):
        """A {"detail": {...}} body yields the inner dict."""
        from lupin_mcp import cosa_voice_mcp
        resp   = _make_response( 422, { "detail": { "requested": "Zorp", "available": [ "a" ] } } )
        detail = cosa_voice_mcp._persona_error_detail( resp )
        assert detail == { "requested": "Zorp", "available": [ "a" ] }

    def test_non_dict_detail_returns_empty( self ):
        """A non-dict `detail` (plain string) yields {}."""
        from lupin_mcp import cosa_voice_mcp
        resp = _make_response( 422, { "detail": "a plain string" } )
        assert cosa_voice_mcp._persona_error_detail( resp ) == { }

    def test_unparseable_body_returns_empty( self ):
        """A non-JSON body (.json() raises ValueError) yields {}."""
        from lupin_mcp import cosa_voice_mcp
        resp = _make_response( 500, body=None, text="<html>500</html>" )
        assert cosa_voice_mcp._persona_error_detail( resp ) == { }

    def test_json_returns_non_mapping_yields_empty( self ):
        """A JSON body that is a list (no .get) yields {} via the AttributeError branch."""
        from lupin_mcp import cosa_voice_mcp
        resp = MagicMock()
        resp.json = MagicMock( return_value=[ "not", "a", "mapping" ] )
        assert cosa_voice_mcp._persona_error_detail( resp ) == { }


# ═════════════════════════════════════════════════════════════════════════════
# _request_persona — input guards
# ═════════════════════════════════════════════════════════════════════════════

class TestRequestPersonaInputGuards:

    def test_non_string_name_returns_error( self ):
        """A non-string, non-None name short-circuits to status=error with no HTTP call.

        CONTRACT CHANGE 2026-07-19: this test previously passed None here and
        asserted an error. None now means "let the server auto-pick", so the
        non-string guard is exercised with an int instead. See
        test_none_name_selects_autopick for the new None behavior.
        """
        from lupin_mcp import cosa_voice_mcp
        result = cosa_voice_mcp._request_persona( 12345 )
        assert result[ "status" ] == "error"
        assert "non-empty string" in result[ "reason" ]

    def test_whitespace_name_returns_error( self ):
        """A whitespace-only name short-circuits to status=error.

        Deliberately NOT treated as a request for auto-pick: only omitting the
        argument selects that, so a bug producing "" cannot silently allocate
        an arbitrary persona.
        """
        from lupin_mcp import cosa_voice_mcp
        result = cosa_voice_mcp._request_persona( "   " )
        assert result[ "status" ] == "error"
        assert "non-empty string" in result[ "reason" ]

    def test_empty_string_name_returns_error( self ):
        """An empty-string name errors rather than falling through to auto-pick."""
        from lupin_mcp import cosa_voice_mcp
        result = cosa_voice_mcp._request_persona( "" )
        assert result[ "status" ] == "error"
        assert "non-empty string" in result[ "reason" ]

    def test_no_session_id_returns_error( self ):
        """When neither the bridge nor SESSION_ID yields an id → status=error."""
        from lupin_mcp import cosa_voice_mcp
        with patch( "lupin_mcp.cosa_voice_mcp._get_cc_metadata", return_value={ } ), \
             patch( "lupin_mcp.cosa_voice_mcp.SESSION_ID", "" ):
            result = cosa_voice_mcp._request_persona( "Tiberius" )
        assert result[ "status" ] == "error"
        assert result[ "reason" ] == "No session_id available"

    def test_metadata_failure_falls_back_to_session_id_global( self ):
        """_get_cc_metadata raising → sid falls back to the SESSION_ID global."""
        from lupin_mcp import cosa_voice_mcp
        login_resp = _login_ok()
        alloc_resp = _make_response( 200, {
            "voice_persona" : { "name": "tiberius", "display_name": "Tiberius" },
            "swapped"       : False
        } )
        with patch( "lupin_mcp.cosa_voice_mcp._get_cc_metadata", side_effect=RuntimeError( "boom" ) ), \
             patch( "lupin_mcp.cosa_voice_mcp.SESSION_ID", "fallbacksid" ), \
             patch( "lupin_mcp.cosa_voice_mcp.requests.post", side_effect=[ login_resp, alloc_resp ] ) as mp, \
             patch( _CREDS_PATCH, return_value=_CREDS ):
            result = cosa_voice_mcp._request_persona( "Tiberius" )
        assert result[ "status" ] == "ok"
        # The allocate POST URL must carry the fallback sid
        assert "fallbacksid" in mp.call_args_list[ 1 ].args[ 0 ]


# ═════════════════════════════════════════════════════════════════════════════
# _request_persona — HTTP outcomes
# ═════════════════════════════════════════════════════════════════════════════

class TestRequestPersonaHttp:

    def test_login_non_200_returns_error( self ):
        """A non-200 login response → status=error, no allocate POST."""
        from lupin_mcp import cosa_voice_mcp
        login_401 = _make_response( 401, { "detail": "bad credentials" } )
        with patch( "lupin_mcp.cosa_voice_mcp._get_cc_metadata", return_value=_FAKE_META ), \
             patch( "lupin_mcp.cosa_voice_mcp.requests.post", return_value=login_401 ) as mp, \
             patch( _CREDS_PATCH, return_value=_CREDS ):
            result = cosa_voice_mcp._request_persona( "Tiberius" )
        assert result[ "status" ] == "error"
        assert "login HTTP 401" in result[ "reason" ]
        assert mp.call_count == 1  # never reached the allocate endpoint

    def test_success_with_display_name( self ):
        """200 with a full persona → status=ok, swapped flag, 'You are now <display_name>.'"""
        from lupin_mcp import cosa_voice_mcp
        persona    = { "name": "mr radio", "display_name": "Mr. Radio", "icon": "🦉" }
        alloc_resp = _make_response( 200, { "voice_persona": persona, "swapped": True } )
        with patch( "lupin_mcp.cosa_voice_mcp._get_cc_metadata", return_value=_FAKE_META ), \
             patch( "lupin_mcp.cosa_voice_mcp.requests.post", side_effect=[ _login_ok(), alloc_resp ] ) as mp, \
             patch( _CREDS_PATCH, return_value=_CREDS ):
            result = cosa_voice_mcp._request_persona( "Mr. Radio" )
        assert result[ "status" ]        == "ok"
        assert result[ "voice_persona" ] == persona
        assert result[ "swapped" ]       is True
        assert result[ "message" ]       == "You are now Mr. Radio."
        # allocate POST carries the requested_persona_name query param
        alloc_call = mp.call_args_list[ 1 ]
        assert alloc_call.args[ 0 ].endswith( f"/api/cosa-voice/voice-persona/{_FAKE_META['stable_session_id']}/allocate" )
        assert alloc_call.kwargs[ "params" ] == { "requested_persona_name": "Mr. Radio" }
        assert alloc_call.kwargs[ "headers" ][ "Authorization" ] == "Bearer fake-jwt"

    def test_success_falls_back_to_name_when_no_display_name( self ):
        """200 with persona lacking display_name → message uses `name`."""
        from lupin_mcp import cosa_voice_mcp
        alloc_resp = _make_response( 200, { "voice_persona": { "name": "rachel" } } )
        with patch( "lupin_mcp.cosa_voice_mcp._get_cc_metadata", return_value=_FAKE_META ), \
             patch( "lupin_mcp.cosa_voice_mcp.requests.post", side_effect=[ _login_ok(), alloc_resp ] ), \
             patch( _CREDS_PATCH, return_value=_CREDS ):
            result = cosa_voice_mcp._request_persona( "rachel" )
        assert result[ "status" ]  == "ok"
        assert result[ "swapped" ] is False           # `swapped` key absent → default False
        assert result[ "message" ] == "You are now rachel."

    def test_success_falls_back_to_requested_when_persona_empty( self ):
        """200 with no voice_persona block → message uses the requested name."""
        from lupin_mcp import cosa_voice_mcp
        alloc_resp = _make_response( 200, { "swapped": False } )
        with patch( "lupin_mcp.cosa_voice_mcp._get_cc_metadata", return_value=_FAKE_META ), \
             patch( "lupin_mcp.cosa_voice_mcp.requests.post", side_effect=[ _login_ok(), alloc_resp ] ), \
             patch( _CREDS_PATCH, return_value=_CREDS ):
            result = cosa_voice_mcp._request_persona( "Tiberius" )
        assert result[ "status" ]        == "ok"
        assert result[ "voice_persona" ] == { }
        assert result[ "message" ]       == "You are now Tiberius."

    def test_422_not_in_pool( self ):
        """A 422 from allocate → status=not_in_pool with the available list."""
        from lupin_mcp import cosa_voice_mcp
        alloc_422 = _make_response( 422, { "detail": {
            "message"   : "not in pool",
            "requested" : "Zaphod",
            "available" : [ "maria", "rachel", "tiberius" ]
        } } )
        with patch( "lupin_mcp.cosa_voice_mcp._get_cc_metadata", return_value=_FAKE_META ), \
             patch( "lupin_mcp.cosa_voice_mcp.requests.post", side_effect=[ _login_ok(), alloc_422 ] ), \
             patch( _CREDS_PATCH, return_value=_CREDS ):
            result = cosa_voice_mcp._request_persona( "Zaphod" )
        assert result[ "status" ]    == "not_in_pool"
        assert result[ "requested" ] == "Zaphod"
        assert result[ "available" ] == [ "maria", "rachel", "tiberius" ]

    def test_409_occupied( self ):
        """A 409 from allocate → status=occupied with the holding-session fields."""
        from lupin_mcp import cosa_voice_mcp
        alloc_409 = _make_response( 409, { "detail": {
            "message"              : "held",
            "requested"            : "Mr. Radio",
            "holding_session_id"   : "other999",
            "holding_persona_name" : "mr radio",
            "available"            : [ "maria" ]
        } } )
        with patch( "lupin_mcp.cosa_voice_mcp._get_cc_metadata", return_value=_FAKE_META ), \
             patch( "lupin_mcp.cosa_voice_mcp.requests.post", side_effect=[ _login_ok(), alloc_409 ] ), \
             patch( _CREDS_PATCH, return_value=_CREDS ):
            result = cosa_voice_mcp._request_persona( "Mr. Radio" )
        assert result[ "status" ]               == "occupied"
        assert result[ "holding_session_id" ]   == "other999"
        assert result[ "holding_persona_name" ] == "mr radio"
        assert result[ "available" ]            == [ "maria" ]

    def test_other_status_returns_error( self ):
        """Any other allocate status (e.g. 500) → status=error carrying the code."""
        from lupin_mcp import cosa_voice_mcp
        alloc_500 = _make_response( 500, { "detail": "internal" } )
        with patch( "lupin_mcp.cosa_voice_mcp._get_cc_metadata", return_value=_FAKE_META ), \
             patch( "lupin_mcp.cosa_voice_mcp.requests.post", side_effect=[ _login_ok(), alloc_500 ] ), \
             patch( _CREDS_PATCH, return_value=_CREDS ):
            result = cosa_voice_mcp._request_persona( "Tiberius" )
        assert result[ "status" ] == "error"
        assert "allocate HTTP 500" in result[ "reason" ]

    def test_transport_error_returns_error( self ):
        """A requests transport error → status=error, never raises."""
        from lupin_mcp import cosa_voice_mcp
        with patch( "lupin_mcp.cosa_voice_mcp._get_cc_metadata", return_value=_FAKE_META ), \
             patch( "lupin_mcp.cosa_voice_mcp.requests.post",
                    side_effect=requests.ConnectionError( "server down" ) ), \
             patch( _CREDS_PATCH, return_value=_CREDS ):
            result = cosa_voice_mcp._request_persona( "Tiberius" )
        assert result[ "status" ]     == "error"
        assert "ConnectionError" in result[ "reason" ]
        assert result[ "session_id" ] == _FAKE_META[ "stable_session_id" ]

    def test_malformed_login_body_returns_error( self ):
        """Login 200 but body missing `tokens` → KeyError caught → status=error."""
        from lupin_mcp import cosa_voice_mcp
        login_no_tokens = _make_response( 200, { "unexpected": "shape" } )
        with patch( "lupin_mcp.cosa_voice_mcp._get_cc_metadata", return_value=_FAKE_META ), \
             patch( "lupin_mcp.cosa_voice_mcp.requests.post", side_effect=[ login_no_tokens ] ), \
             patch( _CREDS_PATCH, return_value=_CREDS ):
            result = cosa_voice_mcp._request_persona( "Tiberius" )
        assert result[ "status" ] == "error"
        assert "KeyError" in result[ "reason" ]


# ═════════════════════════════════════════════════════════════════════════════
# request_persona — the @mcp.tool wrapper
# ═════════════════════════════════════════════════════════════════════════════

class TestRequestPersonaTool:

    def test_tool_delegates_to_helper( self ):
        """The @mcp.tool wrapper forwards to _request_persona and returns its dict."""
        from lupin_mcp import cosa_voice_mcp
        tool_fn = cosa_voice_mcp.request_persona.fn \
            if hasattr( cosa_voice_mcp.request_persona, "fn" ) \
            else cosa_voice_mcp.request_persona

        alloc_resp = _make_response( 200, {
            "voice_persona" : { "name": "tiberius", "display_name": "Tiberius" },
            "swapped"       : True
        } )
        with patch( "lupin_mcp.cosa_voice_mcp._get_cc_metadata", return_value=_FAKE_META ), \
             patch( "lupin_mcp.cosa_voice_mcp.requests.post", side_effect=[ _login_ok(), alloc_resp ] ), \
             patch( _CREDS_PATCH, return_value=_CREDS ):
            result = tool_fn( "Tiberius" )
        assert result[ "status" ]  == "ok"
        assert result[ "message" ] == "You are now Tiberius."

    def test_tool_is_registered_function_tool( self ):
        """request_persona is registered as a FastMCP FunctionTool."""
        from lupin_mcp import cosa_voice_mcp
        assert "FunctionTool" in str( type( cosa_voice_mcp.request_persona ) )

    def test_tool_callable_with_no_arguments( self ):
        """The @mcp.tool wrapper accepts a bare call and delegates None through.

        This is the surface a null-persona session actually reaches for; if the
        signature regressed to a required arg, this raises TypeError.
        """
        from lupin_mcp import cosa_voice_mcp
        tool_fn = cosa_voice_mcp.request_persona.fn \
            if hasattr( cosa_voice_mcp.request_persona, "fn" ) \
            else cosa_voice_mcp.request_persona

        with patch( "lupin_mcp.cosa_voice_mcp._request_persona", return_value={ "status": "ok" } ) as helper:
            result = tool_fn()

        helper.assert_called_once_with( None )
        assert result == { "status": "ok" }


# ═════════════════════════════════════════════════════════════════════════════
# _request_persona — auto-pick (name omitted -> server-side Mode 1)
#
# The allocate endpoint picks uniformly at random from the unallocated pool
# when `requested_persona_name` is ABSENT. Sending it as None or "" does not
# select that mode, so these tests assert on the params dict itself rather than
# on the response — the response would look identical either way.
#
# ⚠️ Every test here MUST mock requests.post. Before the contract change, a
# None name short-circuited before any HTTP call, so the guard tests needed no
# mocks; None now proceeds to a real request. An unmocked test in this class
# performs a LIVE persona allocation against the running server.
# ═════════════════════════════════════════════════════════════════════════════

class TestRequestPersonaAutoPick:

    def test_name_omitted_sends_no_requested_persona_name( self ):
        """Omitting the name must leave `requested_persona_name` out of params entirely."""
        from lupin_mcp import cosa_voice_mcp
        alloc_resp = _make_response( 200, {
            "voice_persona" : { "name": "rachel", "display_name": "Rachel" },
            "swapped"       : False
        } )
        with patch( "lupin_mcp.cosa_voice_mcp._get_cc_metadata", return_value=_FAKE_META ), \
             patch( "lupin_mcp.cosa_voice_mcp.requests.post", side_effect=[ _login_ok(), alloc_resp ] ) as mp, \
             patch( _CREDS_PATCH, return_value=_CREDS ):
            result = cosa_voice_mcp._request_persona()

        alloc_kwargs = mp.call_args_list[ 1 ].kwargs
        assert "requested_persona_name" not in alloc_kwargs[ "params" ]
        assert alloc_kwargs[ "params" ] == { }
        assert result[ "status" ]  == "ok"
        assert result[ "message" ] == "You are now Rachel."

    def test_name_supplied_sends_requested_persona_name( self ):
        """Supplying a name must send it — the strict request-or-swap path is unchanged."""
        from lupin_mcp import cosa_voice_mcp
        alloc_resp = _make_response( 200, {
            "voice_persona" : { "name": "tiberius", "display_name": "Tiberius" },
            "swapped"       : False
        } )
        with patch( "lupin_mcp.cosa_voice_mcp._get_cc_metadata", return_value=_FAKE_META ), \
             patch( "lupin_mcp.cosa_voice_mcp.requests.post", side_effect=[ _login_ok(), alloc_resp ] ) as mp, \
             patch( _CREDS_PATCH, return_value=_CREDS ):
            result = cosa_voice_mcp._request_persona( "Tiberius" )

        alloc_kwargs = mp.call_args_list[ 1 ].kwargs
        assert alloc_kwargs[ "params" ] == { "requested_persona_name": "Tiberius" }
        assert result[ "status" ] == "ok"

    def test_none_name_selects_autopick_not_error( self ):
        """Explicit None is auto-pick, NOT the non-empty-string error.

        Pins the contract change directly: None used to short-circuit to
        status=error, and callers relying on that would now silently allocate.
        """
        from lupin_mcp import cosa_voice_mcp
        alloc_resp = _make_response( 200, {
            "voice_persona" : { "name": "sam", "display_name": "Sam" },
            "swapped"       : False
        } )
        with patch( "lupin_mcp.cosa_voice_mcp._get_cc_metadata", return_value=_FAKE_META ), \
             patch( "lupin_mcp.cosa_voice_mcp.requests.post", side_effect=[ _login_ok(), alloc_resp ] ), \
             patch( _CREDS_PATCH, return_value=_CREDS ):
            result = cosa_voice_mcp._request_persona( None )

        assert result[ "status" ] != "error"
        assert result[ "status" ] == "ok"

    def test_autopick_message_falls_back_when_server_returns_no_name( self ):
        """With no name requested and none returned, the message must not render None."""
        from lupin_mcp import cosa_voice_mcp
        alloc_resp = _make_response( 200, { "voice_persona": { }, "swapped": False } )
        with patch( "lupin_mcp.cosa_voice_mcp._get_cc_metadata", return_value=_FAKE_META ), \
             patch( "lupin_mcp.cosa_voice_mcp.requests.post", side_effect=[ _login_ok(), alloc_resp ] ), \
             patch( _CREDS_PATCH, return_value=_CREDS ):
            result = cosa_voice_mcp._request_persona()

        assert result[ "status" ] == "ok"
        assert "None" not in result[ "message" ]
        assert result[ "message" ] == "You are now unnamed."

    def test_autopick_422_reports_requested_as_none( self ):
        """A 422 on the auto-pick path carries requested=None rather than crashing."""
        from lupin_mcp import cosa_voice_mcp
        alloc_422 = _make_response( 422, { "detail": { "available": [ ] } } )
        with patch( "lupin_mcp.cosa_voice_mcp._get_cc_metadata", return_value=_FAKE_META ), \
             patch( "lupin_mcp.cosa_voice_mcp.requests.post", side_effect=[ _login_ok(), alloc_422 ] ), \
             patch( _CREDS_PATCH, return_value=_CREDS ):
            result = cosa_voice_mcp._request_persona()

        assert result[ "status" ]    == "not_in_pool"
        assert result[ "requested" ] is None


# ── Standalone ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    pytest.main( [ __file__, "-v" ] )
