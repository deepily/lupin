"""
The parser's other callers, each given a string the tightened parser does not recognise.

`extract_qualifier_comment` no longer returns the whole lowercased string for a value
it cannot read. These tests pin what each caller does with ( None, None ), so the
change cannot move any of them unnoticed. The stop hook has its own test in
`test_stop_hook.py`.
"""

from unittest.mock import MagicMock, patch

from cosa.agents.runtime_argument_expeditor.expeditor import RuntimeArgumentExpeditor
from lupin_cli.claude_code.hooks.lib import anything_else_ask

UNRECOGNISED = "Maybe later"


def _response( value ):
    """A notification response carrying only what the callers read."""
    mock = MagicMock()
    mock.exit_code      = 0
    mock.response_value = value
    mock.default_used   = False
    return mock


@patch( "lupin_mcp.cosa_voice_mcp.NotificationRequest" )
@patch( "lupin_mcp.cosa_voice_mcp._normalize_abstract", return_value=None )
@patch( "lupin_mcp.cosa_voice_mcp._wait_for_sender_id", return_value="claude.code@lupin.deepily.ai#test1234" )
@patch( "lupin_mcp.cosa_voice_mcp.notify_user_sync" )
def test_the_mcp_ask_returns_an_unrecognised_answer_as_the_user_typed_it( mock_notify, mock_sender, mock_abstract, mock_request ):
    """No stance and no qualifier: the ask returns the raw value, unenriched."""
    mock_notify.return_value = _response( UNRECOGNISED )
    from lupin_mcp.cosa_voice_mcp import ask_yes_no
    assert ask_yes_no.fn.sync( "Proceed?" ) == UNRECOGNISED


@patch( "lupin_cli.claude_code.hooks.lib.anything_else_ask.build_ask_request" )
@patch( "lupin_cli.claude_code.hooks.lib.anything_else_ask.notify_user_sync" )
def test_the_idle_ask_treats_an_unrecognised_answer_as_a_timeout( mock_notify, mock_build ):
    """Anything that is not yes or no maps to "timeout", with no qualifier."""
    mock_notify.return_value = _response( UNRECOGNISED )
    result = anything_else_ask.fire_anything_else_ask( session_id="abc12345", gist=None )
    assert ( result.answer, result.qualifier, result.raw_value ) == ( "timeout", None, UNRECOGNISED )


def test_the_expeditor_confirmation_treats_an_unrecognised_answer_as_neither_yes_nor_no():
    """The expeditor reads only the comment, and an unrecognised answer has none."""
    expeditor = RuntimeArgumentExpeditor.__new__( RuntimeArgumentExpeditor )
    expeditor.debug = False
    spec = MagicMock()
    with patch.object( expeditor, "_ask_for_confirmation", return_value=UNRECOGNISED ), \
         patch.object( expeditor, "_parse_modification" ) as parse_mock:
        outcome = expeditor._confirm_and_iterate( { "k": "v" }, spec, "cmd", "user@example.test", context=MagicMock() )
    parse_mock.assert_not_called()
    assert outcome == { "k": "v" }   # neither yes nor no: it asks again until the safety valve proceeds
