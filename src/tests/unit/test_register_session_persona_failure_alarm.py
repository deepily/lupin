"""
Candidate A (row 5aea73f3) — the voice-persona give-up must reach a reader.

Diagnosis this guards (row 86aa79ac, closed 2026-07-19 from the hook's own
stderr in the session transcript): the REST server was unreachable at
SessionStart, the 2s urlopen budget expired, a broad except swallowed it to one
stderr line, Phase 4.5 wrote no persona, and the session ran unattributed for
hours. The server being down was the TRIGGER. The DEFECT was that the give-up
was printed to a channel with no reader.

⚠️ THE LEVER, AND THE ONE THAT LOOKS RIGHT AND IS NOT.
A DEAD PORT DOES NOT REPRODUCE THIS. A closed port yields
URLError(ConnectionRefusedError) instantly — the recorded failure was
`TimeoutError: timed out`. Anyone reaching for a dead port reproduces a
DIFFERENT bug and then matches on the same silence. (The dead-port trick is
separately forbidden because LUPIN_APP_SERVER_URL also feeds notify(), so it
destroys the signal it is built to measure.)

THE HONEST LEVER IS A BLACKHOLE SOCKET: a listening socket that never accepts.
The kernel completes the TCP handshake from the backlog, the request goes out,
and no response ever comes — which is exactly TimeoutError. It touches no
shared state, edits no config, reads no env var, and dies with the test.

`_allocate_voice_persona_via_http` takes server_url as an ARGUMENT, so the
instrument-destroys-signal trap is structurally absent here rather than merely
avoided. That is why this is the level the transport arms are tested at.
"""

import json
import socket
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert( 0, str( Path( __file__ ).resolve().parents[ 3 ] ) )

from lupin_cli.claude_code.hooks import register_session


FAST_LADDER = ( 0.25, 0.25, 0.25 )


# ═════════════════════════════════════════════════════════════════════════════
# Fixtures — the blackhole, and a credential stub
# ═════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def blackhole_url():
    """
    A URL pointing at a socket that LISTENS and never ACCEPTS.

    Connections complete from the kernel backlog, the request is written, and
    no response ever arrives => urlopen raises TimeoutError. This is the
    recorded failure, not the ConnectionRefusedError a closed port would give.
    """
    sock = socket.socket( socket.AF_INET, socket.SOCK_STREAM )
    sock.bind( ( "127.0.0.1", 0 ) )
    sock.listen( 8 )
    try:
        yield f"http://127.0.0.1:{sock.getsockname()[ 1 ]}"
    finally:
        sock.close()


@pytest.fixture
def stub_credentials( monkeypatch ):
    monkeypatch.setattr(
        "lupin_cli.claude_code.hooks.lib.hook_credentials.get_hook_credentials",
        lambda project: ( "e@x.com", "pw" )
    )


@pytest.fixture
def fast_ladder( monkeypatch ):
    monkeypatch.setattr( register_session, "_ALLOCATE_TIMEOUT_LADDER_SECONDS", FAST_LADDER )


def _json_response( body ):
    cm = MagicMock()
    cm.__enter__.return_value.read.return_value = json.dumps( body ).encode()
    cm.__exit__.return_value = False
    return cm


# ═════════════════════════════════════════════════════════════════════════════
# TestBlackholeTransport — the reproduced failure
# ═════════════════════════════════════════════════════════════════════════════

class TestBlackholeTransport:

    def test_blackhole_produces_timeout_failure_not_silent_none(
        self, blackhole_url, stub_credentials, fast_ladder
    ):
        """THE ROW'S CORE RECEIPT: a real timeout yields a STRUCTURED give-up."""
        persona, failure = register_session._allocate_voice_persona_via_http(
            blackhole_url, "lupin", "sid-1"
        )

        assert persona is None
        assert failure is not None, "a null persona with no failure record IS the defect"
        assert failure[ "stage" ]      == "transport"
        assert failure[ "exception" ]  == "TimeoutError"
        assert failure[ "attempts" ]   == len( FAST_LADDER )
        assert failure[ "server_url" ] == blackhole_url

    def test_blackhole_exhausts_the_whole_ladder( self, blackhole_url, stub_credentials, fast_ladder ):
        """A1 hedge receipt: every rung is spent before giving up."""
        import urllib.request
        seen_timeouts = [ ]
        real_urlopen  = urllib.request.urlopen

        def counting_urlopen( req, timeout=None ):
            seen_timeouts.append( timeout )
            return real_urlopen( req, timeout=timeout )

        urllib.request.urlopen = counting_urlopen
        try:
            register_session._allocate_voice_persona_via_http( blackhole_url, "lupin", "sid-1" )
        finally:
            urllib.request.urlopen = real_urlopen

        assert seen_timeouts == list( FAST_LADDER )


# ═════════════════════════════════════════════════════════════════════════════
# TestControlArms — arms that MUST stay quiet, or the detector is broken
# ═════════════════════════════════════════════════════════════════════════════

class TestControlArms:
    """
    Crew rule 6: a control that has never gone red is indistinguishable from
    one that cannot. If the healthy arm ever reports a failure, the alarm is
    firing on the wrong condition and every red above is worthless.
    """

    _LOGIN = { "tokens": { "access_token": "tok" } }

    def _patch_healthy( self, monkeypatch, alloc_body ):
        import urllib.request
        calls = [ ]

        def fake_urlopen( req, timeout=None ):
            calls.append( req.full_url )
            return _json_response( self._LOGIN if "/auth/login" in req.full_url else alloc_body )

        monkeypatch.setattr( urllib.request, "urlopen", fake_urlopen )
        return calls

    def test_healthy_allocation_reports_no_failure( self, monkeypatch, stub_credentials, fast_ladder ):
        calls = self._patch_healthy( monkeypatch, { "voice_persona": { "name": "nora" } } )

        persona, failure = register_session._allocate_voice_persona_via_http(
            "http://srv", "lupin", "sid-1"
        )

        assert persona == { "name": "nora" }
        assert failure is None
        assert len( calls ) == 2, "success must not spend a second ladder rung"

    def test_previous_persona_name_still_rides_the_retried_path( self, monkeypatch, stub_credentials, fast_ladder ):
        """The /clear handoff param survived the rewrite into the retry loop."""
        import urllib.parse
        calls = self._patch_healthy( monkeypatch, { "voice_persona": { "name": "nora" } } )

        register_session._allocate_voice_persona_via_http(
            "http://srv", "lupin", "sid-1", previous_persona_name="Cheech"
        )

        alloc = [ u for u in calls if "/allocate" in u ]
        query = urllib.parse.parse_qs( urllib.parse.urlsplit( alloc[ 0 ] ).query )
        assert query[ "previous_persona_name" ] == [ "Cheech" ]

    def test_healthy_allocation_emits_no_alarm_block( self ):
        assert register_session._build_persona_failure_block( None, "sid-1" ) == ""


# ═════════════════════════════════════════════════════════════════════════════
# TestStageDiscrimination — A3: identical silence, opposite fixes
# ═════════════════════════════════════════════════════════════════════════════

class TestStageDiscrimination:

    def test_credential_failure_never_reaches_the_wire( self, monkeypatch, fast_ladder ):
        """
        A3's whole value: missing creds and a down server used to produce the
        SAME silent None while demanding opposite fixes.
        """
        import urllib.request

        def exploding_urlopen( req, timeout=None ):
            raise AssertionError( "credentials must fail before any transport" )

        monkeypatch.setattr( urllib.request, "urlopen", exploding_urlopen )
        monkeypatch.setattr(
            "lupin_cli.claude_code.hooks.lib.hook_credentials.get_hook_credentials",
            MagicMock( side_effect=FileNotFoundError( "~/.lupin/config missing" ) )
        )

        persona, failure = register_session._allocate_voice_persona_via_http(
            "http://srv", "lupin", "sid-1"
        )

        assert persona is None
        assert failure[ "stage" ]     == "credentials"
        assert failure[ "exception" ] == "FileNotFoundError"
        assert failure[ "attempts" ]  == 0

    def test_login_without_token_is_not_retried( self, monkeypatch, stub_credentials, fast_ladder ):
        """The server ANSWERED; retrying a definite answer is noise."""
        import urllib.request
        calls = [ ]

        def fake_urlopen( req, timeout=None ):
            calls.append( req.full_url )
            return _json_response( { "tokens": { } } )

        monkeypatch.setattr( urllib.request, "urlopen", fake_urlopen )

        persona, failure = register_session._allocate_voice_persona_via_http(
            "http://srv", "lupin", "sid-1"
        )

        assert persona is None
        assert failure[ "stage" ]    == "login_no_token"
        assert failure[ "attempts" ] == 1
        assert len( calls ) == 1, "a definite wrong answer must not spend the ladder"

    def test_200_without_persona_alarms_instead_of_returning_silent_none(
        self, monkeypatch, stub_credentials, fast_ladder
    ):
        """
        Mr Radio proved every 200 on /allocate carries a non-None persona
        (voice_persona.py :268 :296 :344 :527) — so this branch should be
        unreachable. If it EVER fires it must alarm, not hand back the silent
        None this row exists to delete.
        """
        import urllib.request

        def fake_urlopen( req, timeout=None ):
            body = { "tokens": { "access_token": "tok" } } if "/auth/login" in req.full_url else { }
            return _json_response( body )

        monkeypatch.setattr( urllib.request, "urlopen", fake_urlopen )

        persona, failure = register_session._allocate_voice_persona_via_http(
            "http://srv", "lupin", "sid-1"
        )

        assert persona is None
        assert failure[ "stage" ]     == "empty_response"
        assert failure[ "exception" ] == "MissingVoicePersona"

    def test_transient_failure_recovers_on_a_later_rung( self, monkeypatch, stub_credentials, fast_ladder ):
        """The A1 hedge's ONLY payoff mode: loaded-but-alive, never observed live."""
        import urllib.request
        attempts = { "n": 0 }

        def flaky_urlopen( req, timeout=None ):
            if "/auth/login" in req.full_url:
                attempts[ "n" ] += 1
                if attempts[ "n" ] == 1: raise TimeoutError( "timed out" )
                return _json_response( { "tokens": { "access_token": "tok" } } )
            return _json_response( { "voice_persona": { "name": "nora" } } )

        monkeypatch.setattr( urllib.request, "urlopen", flaky_urlopen )

        persona, failure = register_session._allocate_voice_persona_via_http(
            "http://srv", "lupin", "sid-1"
        )

        assert persona == { "name": "nora" }
        assert failure is None


# ═════════════════════════════════════════════════════════════════════════════
# TestAlarmBlock — what the session actually reads
# ═════════════════════════════════════════════════════════════════════════════

class TestAlarmBlock:

    _FAILURE = {
        "stage"      : "transport",
        "exception"  : "TimeoutError",
        "message"    : "timed out",
        "attempts"   : 3,
        "server_url" : "http://localhost:7999"
    }

    def test_block_names_the_session_id( self ):
        """
        BINDING CONSTRAINT inherited from candidate D: a null session has no
        badge and no persona voice, so the session_id is the ONLY identity
        left. An alarm that omits it is unactionable.
        """
        block = register_session._build_persona_failure_block( self._FAILURE, "sid-abc123" )
        assert "sid-abc123" in block

    def test_block_names_the_cause_and_the_stage( self ):
        block = register_session._build_persona_failure_block( self._FAILURE, "sid-1" )
        assert "TimeoutError"          in block
        assert "timed out"             in block
        assert "transport"             in block
        assert "http://localhost:7999" in block
        assert "UNATTRIBUTED"          in block

    def test_block_tolerates_a_missing_session_id( self ):
        block = register_session._build_persona_failure_block( self._FAILURE, None )
        assert "unknown" in block


# ═════════════════════════════════════════════════════════════════════════════
# TestPhase7Wiring — the reader. THIS is the fix; everything above feeds it.
# ═════════════════════════════════════════════════════════════════════════════

class TestPhase7Wiring:
    """
    The give-up was never silent — it printed to the hook's stderr, which
    lands as a hook_success attachment inside the session's own transcript and
    took a dedicated hunt to locate. `additionalContext` is stdout the session
    READS at boot. These are the tests that distinguish "prints" from "prints
    where someone reads it".
    """

    TEST_CC_PID     = 987654
    TEST_SESSION_ID = "aaaaaaaa-1111-2222-3333-444444444444"

    @pytest.fixture
    def hook_env( self, tmp_path, monkeypatch ):
        monkeypatch.setenv( "HOME", str( tmp_path ) )
        ( tmp_path / ".claude" / "sessions" ).mkdir( parents=True, exist_ok=True )

        mocks = {
            "read_hook_input"                 : MagicMock( return_value={
                "session_id"      : self.TEST_SESSION_ID,
                "transcript_path" : "/tmp/transcript.jsonl",
                "cwd"             : "/mnt/DATA01/test"
            } ),
            "_resolve_cc_pid"                 : MagicMock( return_value=self.TEST_CC_PID ),
            "_find_tmux_session"              : MagicMock( return_value=None ),
            "_cleanup_old_listener"           : MagicMock(),
            "_release_voice_persona_via_http" : MagicMock( return_value=False ),
            "send_tts"                        : MagicMock(),
            "_spawn_listener"                 : MagicMock( return_value=None ),
            "log_payload"                     : MagicMock(),
            "emit_json"                       : MagicMock(),
            "_check_cosa_voice_status"        : MagicMock( return_value="" ),
            "detect_project"                  : MagicMock( return_value="lupin" )
        }
        for name, mock in mocks.items():
            monkeypatch.setattr( register_session, name, mock )
        return mocks

    def _emitted_context( self, mocks ):
        return mocks[ "emit_json" ].call_args.args[ 0 ][ "additionalContext" ]

    def test_failed_allocation_reaches_the_session_context( self, hook_env, monkeypatch ):
        monkeypatch.setattr( register_session, "_allocate_voice_persona_via_http",
                             MagicMock( return_value=( None, {
                                 "stage": "transport", "exception": "TimeoutError",
                                 "message": "timed out", "attempts": 3,
                                 "server_url": "http://localhost:7999"
                             } ) ) )

        register_session.main()

        context = self._emitted_context( hook_env )
        assert "VOICE PERSONA ALLOCATION FAILED" in context
        assert "TimeoutError"                    in context
        assert self.TEST_SESSION_ID              in context

    def test_successful_allocation_emits_no_alarm( self, hook_env, monkeypatch ):
        """The control. If this goes red, the alarm fires on the wrong condition."""
        monkeypatch.setattr( register_session, "_allocate_voice_persona_via_http",
                             MagicMock( return_value=( { "name": "nora" }, None ) ) )

        register_session.main()

        assert "VOICE PERSONA ALLOCATION FAILED" not in self._emitted_context( hook_env )

    def test_phase_level_exception_still_alarms( self, hook_env, monkeypatch ):
        """Phase 4.5's outer handler must produce a give-up record too."""
        monkeypatch.setattr( register_session, "_allocate_voice_persona_via_http",
                             MagicMock( side_effect=RuntimeError( "boom" ) ) )

        register_session.main()

        context = self._emitted_context( hook_env )
        assert "VOICE PERSONA ALLOCATION FAILED" in context
        assert "RuntimeError"                    in context
