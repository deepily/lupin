"""
Rick's P0 (store row f6a43e37): the session-identity alert storm.

WHAT WAS ACTUALLY WRONG, measured 2026-09-03 before a line of this was written.

Ten alerts reached the operator between 17:56:28 and 18:10:02 EDT, five pairs about
two seconds apart, each reading:

    "MCP server failed: Claude Code session ID not found. No session bridge file
     detected. Restart Claude Code to fix."

🔴 NO MCP SERVER FAILED. Claude Code keeps its own per-session log for every MCP
server it manages, at ~/.cache/claude-cli-nodejs/<project>/mcp-logs-cosa-voice/.
Every session, in every project, across that whole window shows "Successfully
connected" and ZERO errors, disconnects or restarts. So the alarm was TRUE — some
process really could not resolve a session identity — and its LABEL was FALSE. It
named a component that had not failed and told the operator to perform a restart
that could not have fixed anything.

⚠️ THE FALSE LABEL IS THE HALF THAT REACHES HIM, and it is worse than the noise.
Noise is ignorable; an instruction is actionable, and this one sends a person to do
something that cannot work. Two of these tests are about the retry and four are
about the words, because the words were the defect he actually experienced.

NOT SUPPRESSION, AND THESE TESTS ENFORCE THAT. A process that genuinely has no
session bridge must still alert — silencing a true alarm would be a worse bug than
the storm. What changes is that it alerts ONCE, after retrying, having logged every
attempt, and says what really failed.

STILL OPEN AND DELIBERATELY NOT CLOSED HERE: which process had no usable bridge.
Neither half of this depends on knowing that — a transient failure should not page a
human whoever owns it — but nobody should read this file and conclude it was found.

Venue: :7999-eligible — no server, no network, no new threads.
"""

import threading

import pytest

import lupin_mcp.cosa_voice_mcp as cv


class _Exited( BaseException ):
    """Stand-in for os._exit, which would otherwise kill the test RUN, not fail a test."""


@pytest.fixture( autouse=True )
def _isolate_session_globals( monkeypatch ):
    # Same isolation the sibling resolution tests use: a REAL watcher daemon is
    # already running from module import, so a test must never leave the live
    # Event in a state that daemon did not set.
    monkeypatch.setattr( cv, "SESSION_ID", "aaaaaaaa", raising=False )
    monkeypatch.setattr( cv, "SENDER_ID", "claude.code@lupin.deepily.ai#aaaaaaaa", raising=False )
    monkeypatch.setattr( cv, "_session_failed", False, raising=False )
    monkeypatch.setattr( cv, "_session_ready", threading.Event(), raising=False )
    monkeypatch.setattr( cv.time, "sleep", lambda *_a, **_k: None )   # no real backoff in tests


def _never_resolves( monkeypatch ):
    """Every resolution attempt fails. The condition the storm was made of."""
    def _boom( **_kwargs ):
        raise RuntimeError( "no session bridge file for this process" )
    monkeypatch.setattr( cv, "wait_for_session_id", _boom )


def _capture_alert( monkeypatch ):
    sent = []
    monkeypatch.setattr( cv, "_IS_MCP_SERVER", True )
    monkeypatch.setattr( cv, "notify_user_async", lambda request, debug: sent.append( request ) )
    monkeypatch.setattr( cv.os, "_exit", lambda code: ( _ for _ in () ).throw( _Exited( code ) ) )
    return sent


# ══════════════ HALF ONE: RETRY BEFORE YOU PAGE A HUMAN ══════════════

class TestItRetriesBeforeItAlerts:

    def test_a_first_failure_does_not_alert_at_all( self, monkeypatch ):
        # 🔴 THE STORM IN ONE ASSERTION. Before this change the very first
        # unresolved wait went straight to the operator, so a condition that
        # corrects itself in seconds became something he was told to act on.
        _never_resolves( monkeypatch )
        attempts = []
        monkeypatch.setattr( cv, "wait_for_session_id",
                             lambda **k: attempts.append( 1 ) or ( _ for _ in () ).throw( RuntimeError( "no bridge" ) ) )
        died = []
        monkeypatch.setattr( cv, "_die_no_session_id", lambda: died.append( True ) )

        cv._wait_for_sender_id( timeout=0.01 )

        assert len( attempts ) > 1, (
            "resolution was attempted only once before paging the operator — a transient "
            "startup condition is reported as something a human must fix"
        )
        assert died == [ True ], "the alert must still fire once the retries are exhausted"

    def test_a_resolution_that_succeeds_on_a_retry_never_reaches_the_operator( self, monkeypatch ):
        # The whole point: the storm was made of conditions that fix themselves.
        calls = { "n": 0 }
        def _second_time_lucky( **_kwargs ):
            calls[ "n" ] += 1
            if calls[ "n" ] < 2:
                raise RuntimeError( "no bridge yet" )
            return "bbbbbbbb-1111-2222"
        monkeypatch.setattr( cv, "wait_for_session_id", _second_time_lucky )
        monkeypatch.setattr( cv, "_get_cc_metadata", lambda: { "source": "session_file" } )
        monkeypatch.setattr( cv, "CANONICAL_PROJECT", "lupin", raising=False )
        died = []
        monkeypatch.setattr( cv, "_die_no_session_id", lambda: died.append( True ) )

        got = cv._wait_for_sender_id( timeout=0.01 )

        assert died == [], "a condition that resolved on retry still paged the operator"
        assert got and got.endswith( "#bbbbbbbb" ), (
            f"the retry resolved but the caller got {got!r} — a sender that is not the "
            f"resolved seat is the mis-attribution this gate exists to prevent"
        )

    def test_every_attempt_is_logged_so_the_evidence_survives_the_silence( self, monkeypatch, caplog ):
        # Retrying quietly would trade a storm for a blind spot. The log is what
        # keeps the process that genuinely has no bridge findable afterwards.
        _never_resolves( monkeypatch )
        monkeypatch.setattr( cv, "_die_no_session_id", lambda: None )

        with caplog.at_level( "WARNING" ):
            cv._wait_for_sender_id( timeout=0.01 )

        tries = [ r for r in caplog.records if "retry" in r.getMessage().lower() ]
        assert len( tries ) > 1, (
            "the retries left no record — a failure that stops alerting and stops logging "
            "has not been fixed, it has been hidden"
        )

    def test_the_operator_is_alerted_exactly_ONCE_however_many_attempts_were_made( self, monkeypatch ):
        _never_resolves( monkeypatch )
        died = []
        monkeypatch.setattr( cv, "_die_no_session_id", lambda: died.append( True ) )

        cv._wait_for_sender_id( timeout=0.01 )

        assert died == [ True ], f"the operator was alerted {len( died )} times for one failure"


# ══════════════ HALF TWO: SAY WHAT ACTUALLY FAILED ══════════════

class TestTheMessageNamesTheRealMechanism:

    def test_it_does_NOT_claim_the_MCP_server_failed( self, monkeypatch ):
        # 🔴 MEASURED FALSE on 2026-09-03: every Claude-Code-managed cosa-voice
        # server in every project connected successfully across the whole storm.
        sent = _capture_alert( monkeypatch )
        with pytest.raises( _Exited ):
            cv._die_no_session_id()

        assert "MCP server failed" not in sent[ 0 ].message, (
            "the alert still blames the MCP server, which had not failed — a false label "
            "on a true alarm sends the operator to the wrong place"
        )

    def test_it_does_NOT_tell_the_operator_to_restart_claude_code( self, monkeypatch ):
        # The instruction is the part that made this maddening rather than merely
        # noisy: a restart could not have fixed a server that never went down.
        sent = _capture_alert( monkeypatch )
        with pytest.raises( _Exited ):
            cv._die_no_session_id()

        assert "Restart Claude Code" not in sent[ 0 ].message, (
            "the alert still prescribes a restart that cannot fix this — a false instruction "
            "is worse than no instruction, because a person will act on it"
        )

    def test_it_names_the_thing_that_actually_could_not_be_done( self, monkeypatch ):
        sent = _capture_alert( monkeypatch )
        with pytest.raises( _Exited ):
            cv._die_no_session_id()

        msg = sent[ 0 ].message.lower()
        assert "session identity" in msg or "session id" in msg, (
            "the alert does not say WHAT failed — an operator cannot tell a real problem "
            "from noise if the message names no mechanism"
        )
        assert "resolve" in msg, "the alert does not say that resolution was what failed"

    def test_it_still_alerts_at_HIGH_from_the_mcp_error_sender( self, monkeypatch ):
        # 🔴 THE POSITIVE CONTROL, and it is not decoration. Every other test in
        # this class asserts an ABSENCE, and all four would pass against a function
        # that sent nothing at all. This is what makes the relabel a relabel and
        # not a silencing.
        sent = _capture_alert( monkeypatch )
        with pytest.raises( _Exited ):
            cv._die_no_session_id()

        assert len( sent ) == 1, "the alert stopped being sent — this is a relabel, not a mute"
        assert sent[ 0 ].sender_id.endswith( "#mcp-error" )
        assert sent[ 0 ].priority.value == "high"
