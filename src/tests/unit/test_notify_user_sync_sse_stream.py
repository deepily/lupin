"""
`consume_sse_stream` — the reader that turns the notification server's event stream into a
typed answer. Row `e2099400` §3d, target 2.

WHY IT MATTERS MORE THAN ITS SIZE SUGGESTS. This is the function standing between a session
that asked the user a question and the answer coming back. Every path out of it that is not a
validated event returns `None`, and `None` means the caller falls back to the default answer —
so a parsing bug here does not raise, it silently answers the user's question FOR them. That
makes the error arms the part worth pinning, and they were the part that was untested:
18 of `notify_user_sync.py`'s 51 missing statements were in this one function, measured at sha
6b7533eb on the unit tier with an isolated coverage data file.

HOW THE STREAM IS FAKED. `response.iter_lines()` yields bytes, so a fake response is a small
object yielding whatever byte lines a case needs — a malformed frame, an unknown status, a
frame that is valid JSON but not a valid event. Nothing here opens a socket.

⚠️ THE CLIENT-SIDE TIMEOUT IS TRIGGERED BY ARITHMETIC, NOT BY WAITING. The check is
`elapsed > timeout_seconds + 5`, so a NEGATIVE `timeout_seconds` makes the very first line
overdue and the branch is reached in microseconds. A test that actually slept would be a slow
test measuring the same thing, and one that patched the clock would be testing the patch.

Venue: :7999-eligible — in-process, no server, no network, no persistent-state mutation.
"""

import json
import unittest

from unittest import mock

from lupin_cli.notifications import notify_user_sync as nus
from lupin_cli.notifications.notification_models import (
    ErrorEvent, ExpiredEvent, OfflineEvent, RespondedEvent,
)


class FakeStream:
    """A stand-in for a streaming `requests.Response`, yielding raw SSE byte lines."""

    def __init__( self, *lines ):
        self._lines = lines

    def iter_lines( self ):
        for line in self._lines:
            yield line


def data_frame( **payload ):
    """One well-formed SSE `data:` line carrying `payload` as JSON."""
    return ( "data: " + json.dumps( payload ) ).encode( "utf-8" )


class TerminalEventTest( unittest.TestCase ):
    """The four statuses that end the stream, each mapped to its own typed event."""

    def test_a_responded_frame_comes_back_as_a_responded_event( self ):
        stream = FakeStream( data_frame( status="responded", notification_id="n-1", response="yes" ) )
        event  = nus.consume_sse_stream( stream, timeout_seconds=60 )

        self.assertIsInstance( event, RespondedEvent )
        self.assertEqual( event.response, "yes" )

    def test_the_other_three_terminal_statuses_map_to_their_own_types( self ):
        """
        Each status has its own class because the CALLER treats them differently — an expiry
        takes the default, an offline defers to a chase, an error is reported. Collapsing any
        two of them would lose a decision the caller has to make.
        """
        cases = [
            ( ExpiredEvent, dict( status="expired", response="no", default_used=True ) ),
            ( OfflineEvent, dict( status="offline", response="no" ) ),
            ( ErrorEvent,   dict( status="error",   message="the queue is down" ) ),
        ]
        for expected, payload in cases:
            with self.subTest( status=payload[ "status" ] ):
                stream = FakeStream( data_frame( notification_id="n-1", **payload ) )
                self.assertIsInstance( nus.consume_sse_stream( stream, timeout_seconds=60 ), expected )


class AckFrameTest( unittest.TestCase ):
    """
    The opening `ack` frame — NOT an answer, and the stream must keep reading past it.

    It carries the notification id this ask was given, which is what lets the caller re-attach
    if the stream dies mid-question. Treating ack as terminal would return None (the default
    answer) on every single ask.
    """

    def test_the_ack_id_is_captured_and_the_stream_keeps_reading( self ):
        captured = { }
        stream   = FakeStream(
            data_frame( status="ack",       notification_id="n-42" ),
            data_frame( status="responded", notification_id="n-42", response="no" ),
        )
        event = nus.consume_sse_stream( stream, timeout_seconds=60, ack_capture=captured )

        self.assertEqual( captured, { "notification_id": "n-42" } )
        self.assertIsInstance( event, RespondedEvent )

    def test_a_caller_that_does_not_ask_for_the_id_is_unaffected( self ):
        """The capture dict is optional; omitting it must not change what comes back."""
        stream = FakeStream(
            data_frame( status="ack",       notification_id="n-42" ),
            data_frame( status="responded", notification_id="n-42", response="no" ),
        )
        self.assertIsInstance( nus.consume_sse_stream( stream, timeout_seconds=60 ), RespondedEvent )

    def test_an_ack_with_no_id_captures_nothing_rather_than_a_none( self ):
        """A key present with value None would look like a real id to the re-attach path."""
        captured = { }
        stream   = FakeStream( data_frame( status="ack" ), data_frame( status="expired", response="no", default_used=True ) )
        nus.consume_sse_stream( stream, timeout_seconds=60, ack_capture=captured )

        self.assertEqual( captured, { } )


class MalformedStreamTest( unittest.TestCase ):
    """Every way the stream can be wrong. All of them must answer None, none may raise."""

    def test_a_frame_that_is_not_json_is_skipped_and_the_next_one_still_answers( self ):
        """
        The good frame sits AFTER the broken one on purpose: a reader that gave up on the first
        parse failure would return None here and the user's question would be answered by default.
        """
        stream = FakeStream( b"data: {not json at all",
                             data_frame( status="responded", notification_id="n-1", response="yes" ) )
        self.assertIsInstance( nus.consume_sse_stream( stream, timeout_seconds=60 ), RespondedEvent )

    def test_valid_json_that_is_not_a_valid_event_is_skipped_the_same_way( self ):
        """
        `{"status": "responded"}` with no id parses fine and fails the model. This is the arm
        that separates "the server sent nonsense" from "the server sent something new".
        """
        stream = FakeStream( b'data: {"status": "responded"}',
                             data_frame( status="expired", notification_id="n-1", response="no", default_used=True ) )
        self.assertIsInstance( nus.consume_sse_stream( stream, timeout_seconds=60 ), ExpiredEvent )

    def test_an_unknown_status_is_skipped_rather_than_guessed_at( self ):
        """Forward compatibility: a status this client has never heard of is not an answer."""
        stream = FakeStream( data_frame( status="something-new-next-year", notification_id="n-1" ),
                             data_frame( status="offline", notification_id="n-1", response="no" ) )
        self.assertIsInstance( nus.consume_sse_stream( stream, timeout_seconds=60 ), OfflineEvent )

    def test_keepalive_and_comment_lines_are_ignored( self ):
        """SSE servers send blank lines and `:` comments to hold the connection open."""
        stream = FakeStream( b"", b": keep-alive", b"event: ping",
                             data_frame( status="responded", notification_id="n-1", response="yes" ) )
        self.assertIsInstance( nus.consume_sse_stream( stream, timeout_seconds=60 ), RespondedEvent )

    def test_a_stream_that_simply_ends_answers_none( self ):
        self.assertIsNone( nus.consume_sse_stream( FakeStream(), timeout_seconds=60 ) )

    def test_a_stream_that_blows_up_mid_read_answers_none_instead_of_raising( self ):
        """
        A dropped connection raises out of `iter_lines()`. This function's contract says it
        never raises — the caller has a fallback and a traceback out of a hook is not one.
        """
        class Exploding:
            def iter_lines( self ):
                yield b": keep-alive"
                raise ConnectionResetError( "the server went away" )

        self.assertIsNone( nus.consume_sse_stream( Exploding(), timeout_seconds=60 ) )


class ClientSideTimeoutTest( unittest.TestCase ):
    """
    The client's own overdue check, independent of the server's.

    It exists because a server that stops sending without closing leaves the client reading a
    socket that will never produce another line. See this module's header for why a negative
    budget is the honest way to reach it.
    """

    def test_an_overdue_stream_stops_reading_and_answers_none( self ):
        stream = FakeStream( data_frame( status="responded", notification_id="n-1", response="yes" ) )
        self.assertIsNone( nus.consume_sse_stream( stream, timeout_seconds=-10 ) )

    def test_the_grace_period_is_real_and_a_stream_inside_it_still_answers( self ):
        """
        The check is `elapsed > timeout + 5`, so a budget of -4 leaves the first line one second
        inside the grace period. Without this case, a mutation deleting the grace period would go
        unnoticed. (-5 would put the threshold at exactly 0.0, which the real elapsed time clears
        by microseconds — a boundary this test has no reason to sit on.)
        """
        stream = FakeStream( data_frame( status="responded", notification_id="n-1", response="yes" ) )
        self.assertIsInstance( nus.consume_sse_stream( stream, timeout_seconds=-4 ), RespondedEvent )


class DebugOutputTest( unittest.TestCase ):
    """
    The debug arms. They are one-line `if debug:` guards, and they are worth a test for one
    reason: they run inside an except block that is already handling something going wrong, and
    an exception raised THERE would replace a recoverable parse failure with a crash.
    """

    def _drain( self, stream, **kwargs ):
        with mock.patch( "sys.stderr", new=mock.MagicMock() ):
            return nus.consume_sse_stream( stream, debug=True, **kwargs )

    def test_debug_on_a_healthy_stream_changes_nothing_about_the_answer( self ):
        stream = FakeStream( data_frame( status="ack", notification_id="n-7" ),
                             data_frame( status="responded", notification_id="n-7", response="yes" ) )
        captured = { }
        event = self._drain( stream, timeout_seconds=60, ack_capture=captured )

        self.assertIsInstance( event, RespondedEvent )
        self.assertEqual( captured[ "notification_id" ], "n-7" )

    def test_debug_survives_every_failure_arm( self ):
        """All four skip paths plus the overdue check, with debug printing on each."""
        noisy = FakeStream( b"data: {not json",
                            b'data: {"status": "responded"}',
                            data_frame( status="who-knows", notification_id="n-1" ),
                            data_frame( status="expired", notification_id="n-1", response="no", default_used=True ) )
        self.assertIsInstance( self._drain( noisy, timeout_seconds=60 ), ExpiredEvent )
        self.assertIsNone( self._drain( FakeStream( data_frame( status="expired", notification_id="n", response="no", default_used=True ) ),
                                        timeout_seconds=-10 ) )

    def test_debug_prints_a_traceback_when_the_stream_itself_fails( self ):
        """The only arm that imports traceback — a NameError here would mask the real error."""
        class Exploding:
            def iter_lines( self ):
                raise ConnectionResetError( "gone" )
                yield  # pragma: no cover - makes this a generator; never reached

        self.assertIsNone( self._drain( Exploding(), timeout_seconds=60 ) )
