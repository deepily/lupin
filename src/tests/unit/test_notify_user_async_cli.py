"""
The `notify_user_async` CLI entry point — row `e2099400` (coverage frame ramp).

WHY SEPARATELY FROM THE RETRY TESTS. `main()` was the largest remaining dark
block in the module (lines 379-517) after the retry loop was covered, and it is
a different kind of code: argument parsing, exit codes, and the shape of what a
human sees on stdout versus stderr. Mixing it into the transport tests would
have made both harder to read.

WHAT MAKES THIS WORTH TESTING RATHER THAN PADDING — the exit code is the whole
contract. This script is invoked from hooks and shell scripts, and every one of
them branches on `$?`. A `main()` that printed a failure and still exited 0
would be silently ignored by every caller, and nothing else in the system would
notice. So every test here asserts the exit code, not just the output.

WHAT IS PINNED:

· **Exit 0 on success, exit 1 on every failure**, checked on four distinct
  routes: a delivered notification, an undeliverable one, a Pydantic validation
  rejection, and `--validate-env` in both directions. These reach `sys.exit`
  from four different places in the function.

· **Failures go to stderr, successes to stdout.** A caller redirecting only
  stdout must not lose the error, and one grepping stdout for success must not
  match an error line.

· **`--validate-env` short-circuits before any network use.** It is a
  diagnostic; if it ever started sending a notification, the thing people run
  to check their setup would itself depend on the setup working.

· **Pydantic rejection is reported per field.** An empty message is the common
  mistake, and "Invalid parameters" alone would not tell anyone which one.

⚠️ `sys.exit` raises `SystemExit`, so every call is wrapped in `pytest.raises`
and the code is read off the exception. A test that merely called `main()` and
asserted on output would pass whatever the exit code was — which is the one
thing that matters here.

See: row e2099400
"""

from unittest.mock import MagicMock, patch

import pytest

from lupin_cli.notifications.notify_user_async import main


MODULE = "lupin_cli.notifications.notify_user_async"


def _run( argv, response=None ):
    """Invoke main() with a fake argv and a stubbed transport.

    Returns the SystemExit code. notify_user_async is patched at the name main()
    resolves, so no request is ever built against a real server."""
    if response is None:
        response = MagicMock( success=True, status="queued", message="ok",
                              connection_count=0, target_system_id=None )

    with patch( f"{MODULE}.sys.argv", [ "notify_user_async" ] + argv ), \
         patch( f"{MODULE}.notify_user_async", return_value=response ) as send:
        with pytest.raises( SystemExit ) as exc:
            main()
    return exc.value.code, send


class TestExitCodes:
    """The contract every hook and shell caller branches on."""

    def test_a_delivered_notification_exits_zero( self ):
        code, _ = _run( [ "build finished" ] )
        assert code == 0

    def test_an_undeliverable_notification_exits_one( self ):
        failed = MagicMock( success=False, status="connection_error",
                            message="cannot reach server", connection_count=0,
                            target_system_id=None )
        code, _ = _run( [ "build finished" ], response=failed )
        assert code == 1

    def test_an_invalid_message_exits_one_without_sending( self ):
        """Pydantic rejects an empty message. The send must not happen — a
        caller that got exit 1 AND a delivered notification would be worse than
        either alone."""
        code, send = _run( [ "" ] )
        assert code == 1
        send.assert_not_called()

    def test_success_and_failure_do_not_share_an_exit_code( self ):
        """The control. A main() that returned 0 unconditionally would satisfy
        the success test above and be invisible to every caller."""
        ok, _   = _run( [ "msg" ] )
        bad, _  = _run( [ "msg" ], response=MagicMock(
            success=False, status="error", message="no", connection_count=0, target_system_id=None ) )
        assert ok != bad


class TestValidateEnvShortCircuits:

    def test_it_exits_zero_when_the_environment_is_valid( self ):
        with patch( f"{MODULE}.sys.argv", [ "prog", "unused", "--validate-env" ] ), \
             patch( f"{MODULE}.validate_environment", return_value=True ), \
             patch( f"{MODULE}.notify_user_async" ) as send:
            with pytest.raises( SystemExit ) as exc:
                main()
        assert exc.value.code == 0
        send.assert_not_called()

    def test_it_exits_one_when_the_environment_is_invalid( self ):
        with patch( f"{MODULE}.sys.argv", [ "prog", "unused", "--validate-env" ] ), \
             patch( f"{MODULE}.validate_environment", return_value=False ), \
             patch( f"{MODULE}.notify_user_async" ) as send:
            with pytest.raises( SystemExit ) as exc:
                main()
        assert exc.value.code == 1
        send.assert_not_called()

    def test_it_never_sends_a_notification_in_either_direction( self ):
        """THE POINT of the flag. If the thing you run to diagnose a broken
        setup itself needs the setup to work, it is useless exactly when needed."""
        for valid in ( True, False ):
            with patch( f"{MODULE}.sys.argv", [ "prog", "unused", "--validate-env" ] ), \
                 patch( f"{MODULE}.validate_environment", return_value=valid ), \
                 patch( f"{MODULE}.notify_user_async" ) as send:
                with pytest.raises( SystemExit ):
                    main()
            send.assert_not_called()


class TestArgumentsReachTheRequest:

    def test_the_type_and_priority_flags_are_applied( self ):
        _, send = _run( [ "deploying", "--type", "progress", "--priority", "low" ] )
        request = send.call_args.kwargs[ "request" ]
        assert request.notification_type.value == "progress"
        assert request.priority.value          == "low"

    def test_the_defaults_are_custom_and_medium( self ):
        _, send = _run( [ "some message" ] )
        request = send.call_args.kwargs[ "request" ]
        assert request.notification_type.value == "custom"
        assert request.priority.value          == "medium"

    def test_the_server_override_is_passed_through_rather_than_dropped( self ):
        _, send = _run( [ "msg", "--server", "http://elsewhere:8080" ] )
        assert send.call_args.kwargs[ "server_url" ] == "http://elsewhere:8080"

    def test_debug_is_off_by_default_and_on_when_asked( self ):
        _, quiet = _run( [ "msg" ] )
        _, loud  = _run( [ "msg", "--debug" ] )
        assert quiet.call_args.kwargs[ "debug" ] is False
        assert loud.call_args.kwargs[ "debug" ]  is True


class TestWhatTheHumanSees:

    def test_success_goes_to_stdout( self, capsys ):
        _run( [ "build finished" ] )
        out = capsys.readouterr()
        assert "Notification sent" in out.out
        assert "Notification sent" not in out.err

    def test_failure_goes_to_stderr_not_stdout( self, capsys ):
        """A caller redirecting only stdout must not lose the error."""
        failed = MagicMock( success=False, status="connection_error",
                            message="cannot reach server", connection_count=0,
                            target_system_id=None )
        _run( [ "msg" ], response=failed )
        out = capsys.readouterr()
        assert "cannot reach server" in out.err
        assert "cannot reach server" not in out.out

    def test_the_connection_count_is_reported_only_when_there_is_one( self, capsys ):
        _run( [ "msg" ], response=MagicMock(
            success=True, status="queued", message="ok",
            connection_count=3, target_system_id=None ) )
        assert "3 connection(s)" in capsys.readouterr().out

        _run( [ "msg" ] )   # connection_count = 0
        assert "connection(s)" not in capsys.readouterr().out

    def test_a_validation_failure_names_the_offending_field( self, capsys ):
        """"Invalid parameters" on its own tells nobody which one."""
        _run( [ "" ] )
        err = capsys.readouterr().err
        assert "Invalid parameters" in err
        assert "message" in err
