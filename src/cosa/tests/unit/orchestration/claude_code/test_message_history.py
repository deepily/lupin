"""
Unit tests for cosa/orchestration/claude_code/message_history.py (MessageHistory).

Pure in-memory class — no I/O, no mocks needed. Harvests every assertion from
the module's legacy quick_smoke_test() into real pytest, plus the truncation /
empty-input / role-formatting branches the smoke block did and did not reach.
The quick_smoke_test() + __main__ block is MARKED FOR DELETION (manager gates the
delete post-commit per campaign runbook §9); it is already coverage-excluded via
the repo exclude_also regex.
"""
from cosa.orchestration.claude_code.message_history import MessageHistory
from cosa.orchestration import MessageHistory as ReexportedMessageHistory


# =========================================================================== #
# construction / re-export
# =========================================================================== #
def test_init_empty():
    """A fresh history has no messages and an empty original prompt."""
    h = MessageHistory()
    assert len( h ) == 0
    assert not h
    assert h.messages == []
    assert h.original_prompt == ""


def test_reexport_identity():
    """The package re-export is the same class object."""
    assert ReexportedMessageHistory is MessageHistory


# =========================================================================== #
# set_original_prompt
# =========================================================================== #
def test_set_original_prompt():
    """The original prompt is stored verbatim."""
    h = MessageHistory()
    h.set_original_prompt( "Debug jwt_service.py" )
    assert h.original_prompt == "Debug jwt_service.py"


# =========================================================================== #
# add_assistant_text
# =========================================================================== #
def test_add_assistant_text_empty_is_ignored():
    """Empty assistant text is a no-op (early return)."""
    h = MessageHistory()
    h.add_assistant_text( "" )
    assert len( h ) == 0


def test_add_assistant_text_new_turn():
    """First assistant text creates a new assistant turn."""
    h = MessageHistory()
    h.add_assistant_text( "hello" )
    assert len( h ) == 1
    assert h.messages[ 0 ] == { "role": "assistant", "content": "hello" }


def test_add_assistant_text_concatenates_consecutive():
    """Consecutive assistant texts concatenate into one turn."""
    h = MessageHistory()
    h.add_assistant_text( "I see the problem. " )
    h.add_assistant_text( "Line 42 has a bug." )
    assert len( h ) == 1
    assert h.messages[ 0 ][ "content" ] == "I see the problem. Line 42 has a bug."


def test_add_assistant_text_after_user_starts_new_turn():
    """Assistant text after a user message starts a fresh assistant turn."""
    h = MessageHistory()
    h.add_assistant_text( "first" )
    h.add_user_message( "reply" )
    h.add_assistant_text( "second" )
    assert len( h ) == 3
    assert h.messages[ 2 ] == { "role": "assistant", "content": "second" }


# =========================================================================== #
# add_user_message
# =========================================================================== #
def test_add_user_message_empty_is_ignored():
    """Empty user message is a no-op."""
    h = MessageHistory()
    h.add_user_message( "" )
    assert len( h ) == 0


def test_add_user_message_appends():
    """A non-empty user message is appended as a user turn."""
    h = MessageHistory()
    h.add_user_message( "check refresh tokens" )
    assert h.messages == [ { "role": "user", "content": "check refresh tokens" } ]


# =========================================================================== #
# get_context_prompt
# =========================================================================== #
def test_get_context_prompt_empty_returns_empty_string():
    """No messages → empty context string."""
    assert MessageHistory().get_context_prompt() == ""


def test_get_context_prompt_formats_roles_and_markers():
    """Context carries the markers, original task, and both role labels."""
    h = MessageHistory()
    h.set_original_prompt( "Original task here" )
    h.add_assistant_text( "assistant says hi" )
    h.add_user_message( "user says hi" )
    ctx = h.get_context_prompt()
    assert "[CONVERSATION CONTEXT]" in ctx
    assert "[END CONTEXT - Continue from here]" in ctx
    assert "Original task: Original task here" in ctx
    assert "- You (Claude): assistant says hi" in ctx
    assert "- User: user says hi" in ctx


def test_get_context_prompt_truncates_long_original_and_messages():
    """Original prompt and message content beyond the cap get an ellipsis."""
    h = MessageHistory()
    h.set_original_prompt( "x" * 50 )
    h.add_assistant_text( "y" * 50 )
    ctx = h.get_context_prompt( max_chars_per_message=10 )
    assert "Original task: " + ( "x" * 10 ) + "..." in ctx
    assert "- You (Claude): " + ( "y" * 10 ) + "..." in ctx


def test_get_context_prompt_no_truncation_when_short():
    """Content at/under the cap is not truncated (no ellipsis)."""
    h = MessageHistory()
    h.set_original_prompt( "short" )
    h.add_user_message( "tiny" )
    ctx = h.get_context_prompt( max_chars_per_message=100 )
    assert "..." not in ctx


# =========================================================================== #
# clear / __len__ / __bool__
# =========================================================================== #
def test_clear_resets_state():
    """clear() empties messages and the original prompt."""
    h = MessageHistory()
    h.set_original_prompt( "task" )
    h.add_user_message( "msg" )
    h.clear()
    assert len( h ) == 0
    assert h.original_prompt == ""


def test_bool_true_when_messages_present():
    """__bool__ is True once a message exists, False when empty."""
    h = MessageHistory()
    assert bool( h ) is False
    h.add_user_message( "x" )
    assert bool( h ) is True
