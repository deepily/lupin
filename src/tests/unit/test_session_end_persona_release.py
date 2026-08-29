"""
Session-end voice-persona release and listener shutdown — row `e2099400`.

WHY THESE TWO FUNCTIONS. `session_end.py` sat at 63% with 52 statements
uncovered, and almost all of the dark region was `_release_voice_persona`
(lines 160-221) plus `_stop_listener`. Both run on EVERY session teardown, both
promise "Never raises exceptions" in their own docstrings, and neither had a
test proving it.

WHAT A FAILURE HERE ACTUALLY COSTS, which is why it is worth real tests:
a persona that is never released stays allocated to a dead session, so the pool
hands the next session a borrowed name or none at all — and this fleet
identifies its sessions BY persona. A listener that is never stopped outlives
its session and keeps holding its notification channel.

Neither failure is loud. Both look like "the session ended fine."

`_release_voice_persona` HAS SEVEN DISTINCT EXITS and six of them are failures,
so a test that only walked the happy path would leave the entire degradation
surface dark:

    no bridge path            -> False
    no stable/session id      -> False
    no persona allocated      -> False, and NO HTTP at all
    detect_project raises     -> falls back to "lupin" and continues
    login returns no token    -> False
    release succeeds          -> True
    any listed exception      -> warns on stderr, False

⚠️ THE THIRD ONE IS THE INTERESTING ONE. Skipping the HTTP round trip when no
persona is allocated is not an optimisation detail — session teardown happens
constantly, and a login-plus-release pair against `:7999` for every session that
never had a persona is pure load. It is asserted by proving `urlopen` is never
reached, not by inspecting the return value, because the return value is `False`
on that path either way.

See: row e2099400
"""

import json
import signal
from unittest.mock import MagicMock, mock_open, patch

import pytest

from lupin_cli.claude_code.hooks.session_end import (
    _release_voice_persona,
    _stop_listener,
)


MODULE = "lupin_cli.claude_code.hooks.session_end"
BRIDGE = "lupin_cli.claude_code.hooks.lib.session_bridge"
CREDS  = "lupin_cli.claude_code.hooks.lib.hook_credentials"


def _urlopen_pair( access_token="tok-123" ):
    """A urlopen stub that answers the login call then the release call."""
    login = MagicMock()
    login.read.return_value = json.dumps(
        { "tokens": { "access_token": access_token } } if access_token else { "tokens": {} }
    ).encode()
    login.__enter__ = MagicMock( return_value=login )
    login.__exit__  = MagicMock( return_value=False )

    release = MagicMock()
    release.__enter__ = MagicMock( return_value=release )
    release.__exit__  = MagicMock( return_value=False )

    return MagicMock( side_effect=[ login, release ] )


def _release( *, path="/tmp/bridge.json", bridge_data=None, persona="maria",
              urlopen=None, detect_raises=False ):
    """Drive _release_voice_persona with every collaborator stubbed.

    Only ONE input varies per test; everything else is held at a working value,
    so a difference in outcome is attributable to the thing under test."""
    if bridge_data is None:
        bridge_data = { "stable_session_id": "abc12345" }
    if urlopen is None:
        urlopen = _urlopen_pair()

    detect = MagicMock( side_effect=RuntimeError( "no repo" ) ) if detect_raises \
             else MagicMock( return_value="lupin" )

    with patch( f"{BRIDGE}.find_session_path_by_id", return_value=path ), \
         patch( f"{BRIDGE}.get_voice_persona", return_value=persona ), \
         patch( f"{CREDS}.get_hook_credentials", return_value=( "a@b.deepily.ai", "pw" ) ), \
         patch( "cosa.agents.utils.sender_id.detect_project", detect ), \
         patch( "builtins.open", mock_open( read_data=json.dumps( bridge_data ) ) ), \
         patch( f"{MODULE}.urllib.request.urlopen", urlopen ):
        result = _release_voice_persona( "sess-1" )
    return result, urlopen


class TestReleaseSucceeds:

    def test_a_complete_round_trip_returns_true( self ):
        result, urlopen = _release()
        assert result is True
        assert urlopen.call_count == 2, "expected a login call and a release call"

    def test_it_falls_back_to_the_session_id_when_there_is_no_stable_id( self ):
        result, _ = _release( bridge_data={ "session_id": "fallback1" } )
        assert result is True

    def test_a_failing_project_detection_does_not_abort_the_release( self ):
        """detect_project is best-effort — it only picks which credentials to
        use. A repo it cannot classify must not cost the session its persona."""
        result, _ = _release( detect_raises=True )
        assert result is True


class TestReleaseDegradesWithoutRaising:
    """Six failure exits. The docstring promises 'Never raises exceptions', and
    the caller is a teardown hook with nowhere to put one."""

    def test_no_bridge_path_returns_false( self ):
        result, urlopen = _release( path=None )
        assert result is False
        urlopen.assert_not_called()

    def test_a_bridge_file_with_no_usable_id_returns_false( self ):
        result, urlopen = _release( bridge_data={ "unrelated": "x" } )
        assert result is False
        urlopen.assert_not_called()

    def test_no_allocated_persona_skips_the_http_round_trip_entirely( self ):
        """NOT an optimisation detail. Session teardown happens constantly, and
        a login-plus-release pair for every session that never had a persona is
        pure load on :7999. Asserted on urlopen, because the RETURN VALUE is
        False on this path either way and would not discriminate."""
        result, urlopen = _release( persona=None )
        assert result is False
        urlopen.assert_not_called()

    def test_a_login_that_returns_no_token_returns_false( self ):
        result, _ = _release( urlopen=_urlopen_pair( access_token=None ) )
        assert result is False

    def test_a_transport_error_warns_on_stderr_and_returns_false( self, capsys ):
        import urllib.error
        result, _ = _release( urlopen=MagicMock( side_effect=urllib.error.URLError( "server down" ) ) )
        assert result is False
        err = capsys.readouterr().err
        assert "voice persona release failed" in err
        assert "URLError" in err, "the warning should name the exception type, not just fail quietly"

    def test_malformed_login_json_is_caught_rather_than_propagating( self ):
        broken = MagicMock()
        broken.read.return_value = b"not json at all"
        broken.__enter__ = MagicMock( return_value=broken )
        broken.__exit__  = MagicMock( return_value=False )
        result, _ = _release( urlopen=MagicMock( side_effect=[ broken ] ) )
        assert result is False

    def test_the_success_and_failure_paths_do_not_return_the_same_thing( self ):
        """The control: a function returning False unconditionally would satisfy
        every failure test above."""
        ok, _  = _release()
        bad, _ = _release( path=None )
        assert ok != bad


class TestStopListener:
    """Also promises 'Never raises exceptions'. It signals a process it does not
    own, which is exactly where surprises come from."""

    def test_a_graceful_exit_needs_no_sigkill( self ):
        """SIGTERM lands, the next liveness probe finds it gone."""
        with patch( f"{MODULE}.os.kill", side_effect=[ None, ProcessLookupError() ] ) as kill, \
             patch( f"{MODULE}.time.sleep" ):
            _stop_listener( 4242 )
        assert signal.SIGKILL not in [ c.args[ 1 ] for c in kill.call_args_list ]

    def test_an_already_dead_process_returns_immediately( self ):
        with patch( f"{MODULE}.os.kill", side_effect=ProcessLookupError() ) as kill, \
             patch( f"{MODULE}.time.sleep" ) as sleep:
            _stop_listener( 4242 )
        assert kill.call_count == 1
        sleep.assert_not_called()

    def test_a_process_we_may_not_signal_returns_immediately( self ):
        with patch( f"{MODULE}.os.kill", side_effect=PermissionError() ) as kill, \
             patch( f"{MODULE}.time.sleep" ) as sleep:
            _stop_listener( 4242 )
        assert kill.call_count == 1
        sleep.assert_not_called()

    def test_a_process_that_ignores_sigterm_is_eventually_sigkilled( self ):
        """The escalation is the whole reason this function exists rather than
        a bare os.kill — a listener that ignores SIGTERM would otherwise outlive
        its session and keep holding its notification channel."""
        with patch( f"{MODULE}.os.kill", return_value=None ) as kill, \
             patch( f"{MODULE}.time.sleep" ):
            _stop_listener( 4242 )
        assert kill.call_args_list[ -1 ].args[ 1 ] == signal.SIGKILL

    def test_it_waits_before_escalating_rather_than_killing_at_once( self ):
        """A SIGKILL with no grace period gives the listener no chance to flush."""
        with patch( f"{MODULE}.os.kill", return_value=None ), \
             patch( f"{MODULE}.time.sleep" ) as sleep:
            _stop_listener( 4242 )
        assert sleep.call_count == 10

    def test_a_process_that_dies_during_the_final_sigkill_does_not_raise( self ):
        """The race: it exits between the last liveness probe and the SIGKILL."""
        calls = [ None ] * 21 + [ ProcessLookupError() ]
        with patch( f"{MODULE}.os.kill", side_effect=calls ), \
             patch( f"{MODULE}.time.sleep" ):
            _stop_listener( 4242 )   # must not raise
