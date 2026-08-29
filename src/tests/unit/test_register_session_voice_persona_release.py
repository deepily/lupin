"""
`_release_voice_persona_via_http` — row `e2099400`.

WHY THIS BLOCK. Lines 1634-1672 were dark end to end — the entire two-step
release call, both its success path and every one of its seven caught exception
types. It is 39 statements and it is the second-largest contiguous hole left in
`register_session.py`.

WHAT IT DOES. On a re-spin the seat's voice persona has to be handed back, or
the next allocation finds the pool short and the frontend keeps speaking in the
dead seat's voice. The release is a login-then-POST against the server, and it
is deliberately FAIL-SOFT: any failure prints a warning and returns False, and
the hook writes its bridge either way. That design is right — a persona that
cannot be released must not stop a session from starting — but it means every
defect in here is a warning on stderr that nobody reads, and the only place the
behaviour can be pinned is a test.

WHAT IS PINNED:

· **True only on a completed two-step call.** Login, then POST /release. A
  version that returned True after the login alone would look identical to
  every caller, and the persona would stay allocated forever.

· **The release goes to the right URL with a Bearer token.** Unauthenticated it
  is a 401 the fail-soft handler swallows — a release that silently never
  happens, which is exactly the failure this function exists to prevent.

· **A login response with no `access_token` stops before the POST.** This is the
  one failure the function detects itself rather than catching; sending
  `Bearer None` would be a 401, i.e. the same silent no-op by a longer route.

· **Every caught exception type returns False rather than raising** — the full
  set the signature names, driven one at a time. This runs on the session-start
  path; an escape here takes the boot down.

· **The warning names the exception type.** stderr is the only channel this
  function has, and "release failed" without the type is not diagnosable.

· **Both calls carry the module's transport timeout**, which is sized to
  outlast a `:7999` reload window rather than fail inside one.

⚠️ NOTHING REACHES THE NETWORK. `urlopen` is patched at the module and the
credential lookup is stubbed; the unit tier runs with its network guard armed
and would fail the run on a real socket.

See: row e2099400
"""

import json
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from lupin_cli.claude_code.hooks.register_session import (
    _SERVER_TRANSPORT_TIMEOUT_SECONDS,
    _release_voice_persona_via_http,
)


MODULE  = "lupin_cli.claude_code.hooks.register_session"
CREDS   = "lupin_cli.claude_code.hooks.lib.hook_credentials.get_hook_credentials"
SERVER  = "http://localhost:7999"
PROJECT = "lupin"
SID     = "08e47ef3-147d-43bd-a0e0-d052e6b7fd7a"


def _reply( body ):
    """A urlopen context-manager stand-in returning `body` as bytes."""
    resp = MagicMock()
    resp.read.return_value = body.encode() if isinstance( body, str ) else body
    ctx = MagicMock()
    ctx.__enter__.return_value = resp
    ctx.__exit__.return_value  = False
    return ctx


_GOOD_LOGIN = json.dumps( { "tokens": { "access_token": "jwt-abc" } } )


def _release( urlopen_config, creds=( "a@b.c", "pw" ) ):
    with patch( CREDS, return_value=creds ), \
         patch( f"{MODULE}.urllib.request.urlopen", **urlopen_config ) as urlopen:
        result = _release_voice_persona_via_http( SERVER, PROJECT, SID )
    return result, urlopen


class TestTheHappyPath:

    def test_a_completed_two_step_call_returns_true( self ):
        ok, urlopen = _release( { "side_effect": [ _reply( _GOOD_LOGIN ), _reply( b"" ) ] } )
        assert ok is True
        assert urlopen.call_count == 2

    def test_the_release_is_posted_to_the_session_specific_endpoint( self ):
        _, urlopen = _release( { "side_effect": [ _reply( _GOOD_LOGIN ), _reply( b"" ) ] } )
        release_req = urlopen.call_args_list[ 1 ].args[ 0 ]
        assert release_req.full_url == f"{SERVER}/api/cosa-voice/voice-persona/{SID}/release"
        assert release_req.method   == "POST"

    def test_the_release_carries_the_token_from_the_login( self ):
        """Without it the server answers 401, the fail-soft handler swallows it,
        and the persona is never released — the exact silence this guards."""
        _, urlopen = _release( { "side_effect": [ _reply( _GOOD_LOGIN ), _reply( b"" ) ] } )
        headers = urlopen.call_args_list[ 1 ].args[ 0 ].headers
        assert headers[ "Authorization" ] == "Bearer jwt-abc"

    def test_the_login_is_posted_with_the_looked_up_credentials( self ):
        _, urlopen = _release( { "side_effect": [ _reply( _GOOD_LOGIN ), _reply( b"" ) ] },
                               creds=( "hook@example.com", "s3cret" ) )
        login_req = urlopen.call_args_list[ 0 ].args[ 0 ]
        assert login_req.full_url == f"{SERVER}/auth/login"
        assert json.loads( login_req.data.decode() ) == {
            "email": "hook@example.com", "password": "s3cret" }

    def test_both_calls_use_the_module_transport_timeout( self ):
        """Sized to outlast a :7999 reload window rather than fail inside one."""
        _, urlopen = _release( { "side_effect": [ _reply( _GOOD_LOGIN ), _reply( b"" ) ] } )
        for call in urlopen.call_args_list:
            assert call.kwargs[ "timeout" ] == _SERVER_TRANSPORT_TIMEOUT_SECONDS


class TestTheTokenlessLoginIsCaughtHere:

    def test_a_login_without_an_access_token_returns_false( self ):
        ok, _ = _release( { "side_effect": [ _reply( json.dumps( { "tokens": {} } ) ) ] } )
        assert ok is False

    def test_it_never_reaches_the_release_call( self ):
        """Posting `Bearer None` would be a 401 the handler swallows — the same
        silent no-op, reached by a longer route."""
        _, urlopen = _release( { "side_effect": [ _reply( json.dumps( { "tokens": {} } ) ) ] } )
        assert urlopen.call_count == 1

    def test_a_login_body_with_no_tokens_key_at_all_returns_false( self ):
        ok, _ = _release( { "side_effect": [ _reply( json.dumps( { "detail": "nope" } ) ) ] } )
        assert ok is False

    def test_it_warns_on_stderr_about_the_missing_token( self, capsys ):
        _release( { "side_effect": [ _reply( json.dumps( { "tokens": {} } ) ) ] } )
        err = capsys.readouterr().err
        assert "voice persona release" in err
        assert "access_token" in err


class TestEveryFailureIsSoft:
    """The signature names seven exception types. Each is driven separately —
    a handler that caught only the first would pass a single-case test."""

    @pytest.mark.parametrize( "boom", [
        urllib.error.URLError( "unreachable" ),
        urllib.error.HTTPError( SERVER, 500, "boom", {}, None ),
        OSError( "socket died" ),
        ValueError( "bad value" ),
    ] )
    def test_a_transport_failure_returns_false_rather_than_raising( self, boom ):
        ok, _ = _release( { "side_effect": boom } )
        assert ok is False

    def test_an_unparseable_login_body_returns_false( self ):
        ok, _ = _release( { "side_effect": [ _reply( "{ not json" ) ] } )
        assert ok is False

    def test_missing_hook_credentials_return_false( self ):
        """No credentials file is an ordinary state on a fresh box."""
        with patch( CREDS, side_effect=FileNotFoundError( "no creds file" ) ), \
             patch( f"{MODULE}.urllib.request.urlopen" ) as urlopen:
            assert _release_voice_persona_via_http( SERVER, PROJECT, SID ) is False
        urlopen.assert_not_called()

    def test_a_keyerror_from_the_credential_lookup_returns_false( self ):
        with patch( CREDS, side_effect=KeyError( "lupin" ) ), \
             patch( f"{MODULE}.urllib.request.urlopen" ):
            assert _release_voice_persona_via_http( SERVER, PROJECT, SID ) is False

    def test_a_failure_on_the_release_call_returns_false_not_true( self ):
        """The login succeeded; returning True here would report a release that
        never happened."""
        ok, urlopen = _release( { "side_effect": [ _reply( _GOOD_LOGIN ),
                                                   urllib.error.URLError( "gone" ) ] } )
        assert ok is False
        assert urlopen.call_count == 2

    def test_the_warning_names_the_exception_type( self, capsys ):
        """stderr is the only channel this function has; "release failed" alone
        is not diagnosable."""
        _release( { "side_effect": urllib.error.URLError( "unreachable" ) } )
        assert "URLError" in capsys.readouterr().err

    def test_success_and_failure_do_not_return_the_same_thing( self ):
        """The control — a function returning False unconditionally would pass
        every failure test above."""
        ok, _   = _release( { "side_effect": [ _reply( _GOOD_LOGIN ), _reply( b"" ) ] } )
        bad, _  = _release( { "side_effect": urllib.error.URLError( "x" ) } )
        assert ok is True and bad is False
