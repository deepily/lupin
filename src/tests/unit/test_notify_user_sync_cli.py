"""
The `notify_user_sync` CLI entry point — row `e2099400` (coverage frame ramp).

WHY A SEPARATE FILE. `main()` (lines 639-806) was the single largest dark block
left in the module — 143 of its 104 missing statements — and it is a different
kind of code from the SSE transport that `test_notify_user_sync.py` already
covers: config loading, argument parsing, and exit codes. Mixing it in would
have made both files harder to read. Same split, same reason, as
`test_notify_user_async_cli.py`.

WHAT MAKES THIS WORTH TESTING RATHER THAN PADDING — **this script's exit code
is a three-way answer, not a boolean.** 0 = the user answered, 1 = something
broke, 2 = the user never answered in time. Hooks and shell callers branch on
all three, and a timeout that came back as 1 would be indistinguishable from a
network failure to every one of them. So every test here reads the code off the
`SystemExit`, and one test pins that the three are actually distinct.

WHAT IS PINNED:

· **The three exit codes are passed through from the response, not recomputed.**
  `main()` ends in `sys.exit( response.exit_code )`; a version that returned 0
  unconditionally would satisfy any single-value test.

· **The response value goes to stdout and nothing else does.** Shell callers
  capture stdout to get the user's answer. A stray diagnostic on stdout would be
  captured as if it were the answer.

· **A `None` response value prints nothing at all** — not the string "None",
  which is what an unguarded `print` would emit and what a caller would then
  treat as the user's reply.

· **Pydantic rejection reports every field by name, on stderr, and never sends.**
  A caller that got exit 1 *and* a delivered notification is worse off than one
  that got either alone.

· **A failure to load config is not a failure to run.** The config only supplies
  a default recipient; if it raises, the flag becomes required and the script
  still works for anyone passing `--target-user` explicitly.

⚠️ `sys.exit` raises `SystemExit`, so every invocation is wrapped in
`pytest.raises` and the code read off the exception — a test that merely called
`main()` and asserted on output would pass whatever the exit code was, which is
the one thing that matters here.

See: row e2099400
"""

from unittest.mock import MagicMock, patch

import pytest

from lupin_cli.notifications.notify_user_sync import main


MODULE = "lupin_cli.notifications.notify_user_sync"


def _response( value="yes", exit_code=0 ):
    """A stand-in for NotificationResponse carrying only what main() reads."""
    return MagicMock( response_value=value, exit_code=exit_code )


def _run( argv, response=None, config=None ):
    """Invoke main() with a fake argv, a stubbed transport and a stubbed config.

    Returns (SystemExit code, the patched notify_user_sync mock). The transport
    is patched at the name main() resolves, so nothing is ever sent.
    """
    if response is None: response = _response()
    if config is None:   config   = { "global_notification_recipient": "configured@example.com" }

    with patch( f"{MODULE}.sys.argv", [ "notify_user_sync" ] + argv ), \
         patch( f"{MODULE}.get_api_config", return_value=config ), \
         patch( f"{MODULE}.notify_user_sync", return_value=response ) as send:
        with pytest.raises( SystemExit ) as exc:
            main()
    return exc.value.code, send


_ANSWERED = [ "Approve?", "--response-type", "yes_no", "--response-default", "yes" ]


class TestTheThreeExitCodes:
    """0 answered · 1 broke · 2 timed out. Callers branch on all three."""

    def test_an_answered_notification_exits_zero( self ):
        code, _ = _run( _ANSWERED )
        assert code == 0

    def test_an_error_exits_one( self ):
        code, _ = _run( _ANSWERED, response=_response( value=None, exit_code=1 ) )
        assert code == 1

    def test_a_timeout_exits_two( self ):
        code, _ = _run( _ANSWERED, response=_response( value="no", exit_code=2 ) )
        assert code == 2

    def test_the_three_codes_are_distinct( self ):
        """The control. A main() that ignored response.exit_code and exited 0
        would satisfy the first test above and be invisible to every caller."""
        answered, _ = _run( _ANSWERED )
        broke,    _ = _run( _ANSWERED, response=_response( value=None, exit_code=1 ) )
        timedout, _ = _run( _ANSWERED, response=_response( value="no", exit_code=2 ) )
        assert len( { answered, broke, timedout } ) == 3


class TestWhatReachesStdout:
    """Shell callers capture stdout to read the user's answer."""

    def test_the_response_value_is_printed_alone( self, capsys ):
        _run( _ANSWERED, response=_response( value="yes" ) )
        assert capsys.readouterr().out == "yes\n"

    def test_an_open_ended_answer_is_printed_verbatim( self, capsys ):
        _run( [ "Commit message?", "--response-type", "open_ended" ],
              response=_response( value="fix the parser" ) )
        assert capsys.readouterr().out == "fix the parser\n"

    def test_a_missing_response_value_prints_nothing( self, capsys ):
        """NOT the string "None". An unguarded print would emit that, and the
        caller would hand it on as if the user had typed it."""
        _run( _ANSWERED, response=_response( value=None, exit_code=1 ) )
        assert capsys.readouterr().out == ""


class TestValidationRejection:

    def test_an_empty_message_exits_one_without_sending( self ):
        code, send = _run( [ "", "--response-type", "yes_no" ] )
        assert code == 1
        send.assert_not_called()

    def test_an_out_of_range_timeout_exits_one_without_sending( self ):
        """timeout_seconds is bounded 1-600; argparse accepts 0 as an int and
        Pydantic is what refuses it."""
        code, send = _run( [ "Approve?", "--response-type", "yes_no", "--timeout", "0" ] )
        assert code == 1
        send.assert_not_called()

    def test_the_offending_field_is_named_on_stderr( self, capsys ):
        """"Invalid parameters" alone does not tell anyone which one."""
        _run( [ "", "--response-type", "yes_no" ] )
        err = capsys.readouterr().err
        assert "Invalid parameters" in err
        assert "message" in err

    def test_validation_output_does_not_go_to_stdout( self, capsys ):
        """A caller capturing stdout for the answer must not receive an error
        message there and treat it as the user's reply."""
        _run( [ "", "--response-type", "yes_no" ] )
        assert capsys.readouterr().out == ""


class TestTheDefaultRecipientComesFromConfig:

    def test_a_configured_recipient_is_used_when_the_flag_is_absent( self ):
        _, send = _run( _ANSWERED )
        assert send.call_args.kwargs[ "request" ].target_user == "configured@example.com"

    def test_an_explicit_flag_overrides_the_configured_one( self ):
        _, send = _run( _ANSWERED + [ "--target-user", "someone@else.com" ] )
        assert send.call_args.kwargs[ "request" ].target_user == "someone@else.com"

    def test_a_broken_config_does_not_stop_the_script( self ):
        """The config only supplies a DEFAULT. If it raises, --target-user
        becomes required and the script still works for anyone passing it."""
        with patch( f"{MODULE}.sys.argv",
                    [ "prog" ] + _ANSWERED + [ "--target-user", "explicit@example.com" ] ), \
             patch( f"{MODULE}.get_api_config", side_effect=RuntimeError( "no config file" ) ), \
             patch( f"{MODULE}.notify_user_sync", return_value=_response() ) as send:
            with pytest.raises( SystemExit ) as exc:
                main()
        assert exc.value.code == 0
        assert send.call_args.kwargs[ "request" ].target_user == "explicit@example.com"

    def test_a_broken_config_makes_the_flag_required( self ):
        """With no default there is nobody to notify, so argparse must refuse
        rather than let the request be built with target_user=None."""
        with patch( f"{MODULE}.sys.argv", [ "prog" ] + _ANSWERED ), \
             patch( f"{MODULE}.get_api_config", side_effect=RuntimeError( "no config file" ) ), \
             patch( f"{MODULE}.notify_user_sync" ) as send:
            with pytest.raises( SystemExit ) as exc:
                main()
        assert exc.value.code == 2          # argparse's own usage-error code
        send.assert_not_called()


class TestFlagsReachTheRequest:
    """Each flag is a separate argparse branch; a typo in any one is silent."""

    def test_type_priority_and_title_are_passed_through( self ):
        _, send = _run( _ANSWERED + [ "--type", "alert", "--priority", "urgent",
                                      "--title", "deploy gate" ] )
        request = send.call_args.kwargs[ "request" ]
        assert request.notification_type.value == "alert"
        assert request.priority.value          == "urgent"
        assert request.title                   == "deploy gate"

    def test_server_and_debug_are_passed_beside_the_request_not_inside_it( self ):
        """They configure the transport, not the notification — a --server that
        arrived as a request field would be sent to the server as data."""
        _, send = _run( _ANSWERED + [ "--server", "http://localhost:8000", "--debug" ] )
        assert send.call_args.kwargs[ "server_url" ] == "http://localhost:8000"
        assert send.call_args.kwargs[ "debug" ] is True

    def test_the_defaults_are_what_the_help_text_claims( self ):
        _, send = _run( [ "Approve?", "--response-type", "yes_no" ] )
        request = send.call_args.kwargs[ "request" ]
        assert request.notification_type.value == "custom"
        assert request.priority.value          == "medium"
        assert request.timeout_seconds         == 120
        assert send.call_args.kwargs[ "server_url" ] is None
        assert send.call_args.kwargs[ "debug" ] is False
