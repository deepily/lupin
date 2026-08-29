"""
The user-facing string when a prompt could not be delivered (bug 68198c9f).

WHAT WENT WRONG. `RuntimeArgumentExpeditor.expedite()` returns a bare `None` on
every failure path, so the ONE caller — `todo_fifo_queue.py` — could only test
`if args_dict is None:` and said the same thing for all of them:

    "Job cancelled."  /  "Agentic job cancelled by user or timeout."

Measured 2026-08-02: a confirmation prompt that could NOT be delivered (the user
had no live websocket) killed the job 7 seconds into a 30-second budget and told
the user they had cancelled it. They never saw the prompt. Only a real "no" is a
user decision.

WHAT THIS FILE PINS, at two seams:
  1. The expeditor RECORDS why it failed on the CALLER'S OWN context for the
     ask paths too, not just the batch path — declined / unreachable / timed-out
     are kept apart. (Row 10c60712 moved that off the shared instance: what each
     test asserts is the context it passed in.)
  2. A pure mapping turns that reason into the (spoken, log) strings, and ONLY a
     genuine decline may tell the user they cancelled. Undeliverable, timed-out,
     malformed and incomplete are machine failures and must say so.

Venue: :7999 — no server, no DB, no network. The one network call is patched.
"""

import pytest
from unittest.mock import MagicMock, patch

from cosa.agents.runtime_argument_expeditor.expeditor import (
    RuntimeArgumentExpeditor,
    ArgSpec,
    BATCH_DECLINED,
    BATCH_UNREACHABLE,
    BATCH_TIMEOUT,
    BATCH_MALFORMED,
    BATCH_INCOMPLETE,
    BATCH_INTERNAL,
    ExpediteContext,
    user_message_for_expedite_reason,
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _expeditor():
    config = MagicMock()
    config.get.return_value = "unused/for/this/test"
    with patch( "cosa.agents.runtime_argument_expeditor.expeditor.LlmClientFactory" ):
        return RuntimeArgumentExpeditor( config, debug=False, verbose=False )


def _response( success, value, status="ok", is_timeout=False ):
    r = MagicMock()
    r.success        = success
    r.response_value = value
    r.status         = status
    r.is_timeout     = is_timeout
    r.exit_code      = 0 if success else ( 2 if is_timeout else 1 )
    return r


def _ask_arg( response ):
    exp = _expeditor()
    ctx = ExpediteContext()
    with patch( "cosa.agents.runtime_argument_expeditor.expeditor.notify_user_sync", return_value=response ):
        value = exp._ask_for_arg( "query", "What topic?", "someone@example.com", context=ctx )
    return value, ctx


def _ask_confirm( response ):
    exp = _expeditor()
    ctx = ExpediteContext()
    with patch( "cosa.agents.runtime_argument_expeditor.expeditor.notify_user_sync", return_value=response ):
        value = exp._ask_for_confirmation( "Does this look right?", "someone@example.com", context=ctx )
    return value, ctx


# --------------------------------------------------------------------------- #
# Seam 1 — the ask paths record WHY, not just None
# --------------------------------------------------------------------------- #

def test_ask_for_arg_delivery_failure_is_unreachable():
    """A 503 means the user was never asked — not a decision they made."""
    value, ctx = _ask_arg( _response( False, None, status="http_error_503", is_timeout=False ) )
    assert value is None
    assert ctx.reason == BATCH_UNREACHABLE


def test_ask_for_arg_timeout_is_timeout():
    value, ctx = _ask_arg( _response( False, None, status="timeout", is_timeout=True ) )
    assert value is None
    assert ctx.reason == BATCH_TIMEOUT


def test_ask_for_arg_empty_success_is_malformed():
    """Delivered (exit 0) but no usable value — a garbled answer, not a cancel."""
    value, ctx = _ask_arg( _response( True, None ) )
    assert value is None
    assert ctx.reason == BATCH_MALFORMED


@pytest.mark.parametrize( "word", [ "cancel", "nevermind", "never mind", "stop", "quit", "  CANCEL  " ] )
def test_ask_for_arg_cancel_keyword_is_declined( word ):
    value, ctx = _ask_arg( _response( True, word ) )
    assert value is None
    assert ctx.reason == BATCH_DECLINED


def test_ask_for_arg_success_sets_no_failure_reason():
    """A real answer leaves the failure reason untouched (None)."""
    value, ctx = _ask_arg( _response( True, "brevity" ) )
    assert value == "brevity"
    assert ctx.reason is None


def test_ask_for_confirmation_delivery_failure_is_unreachable():
    value, ctx = _ask_confirm( _response( False, None, status="http_error_503" ) )
    assert value is None
    assert ctx.reason == BATCH_UNREACHABLE


def test_ask_for_confirmation_timeout_is_timeout():
    value, ctx = _ask_confirm( _response( False, None, is_timeout=True ) )
    assert value is None
    assert ctx.reason == BATCH_TIMEOUT


def test_confirm_and_iterate_plain_no_is_declined():
    """A confirmation the user answered 'no' to IS a user decision."""
    exp = _expeditor()
    agent_entry = ArgSpec(
        arg_mapping={}, system_provided=[], required_user_args=[], fallback_questions={},
        fallback_defaults={}, special_handlers={}, display_name=None, cli_module=None,
        file_args={},
    )
    ctx = ExpediteContext()
    with patch.object( exp, "_ask_for_confirmation", return_value="no" ):
        result = exp._confirm_and_iterate( { "query": "brevity" }, agent_entry, "cmd", "someone@example.com", context=ctx )
    assert result is None
    assert ctx.reason == BATCH_DECLINED


def test_confirm_and_iterate_undelivered_keeps_machine_reason():
    """When the confirm never reached the user, the reason stays a machine failure."""
    exp = _expeditor()
    agent_entry = ArgSpec(
        arg_mapping={}, system_provided=[], required_user_args=[], fallback_questions={},
        fallback_defaults={}, special_handlers={}, display_name=None, cli_module=None,
        file_args={},
    )
    # _ask_for_confirmation returns None AND records unreachable (as it would
    # live) — on the context it was handed, which is the caller's.
    ctx = ExpediteContext()
    def _fake_confirm( *a, **k ):
        k[ "context" ].reason = BATCH_UNREACHABLE
        return None
    with patch.object( exp, "_ask_for_confirmation", side_effect=_fake_confirm ):
        result = exp._confirm_and_iterate( { "query": "brevity" }, agent_entry, "cmd", "someone@example.com", context=ctx )
    assert result is None
    assert ctx.reason == BATCH_UNREACHABLE


# --------------------------------------------------------------------------- #
# Seam 2 — the reason becomes the user-facing string
# --------------------------------------------------------------------------- #

def test_only_declined_tells_the_user_they_cancelled():
    spoken, _log = user_message_for_expedite_reason( BATCH_DECLINED )
    assert "cancel" in spoken.lower()


@pytest.mark.parametrize( "reason", [
    BATCH_UNREACHABLE, BATCH_TIMEOUT, BATCH_MALFORMED, BATCH_INCOMPLETE, BATCH_INTERNAL, None,
] )
def test_machine_failures_never_say_the_user_cancelled( reason ):
    """The defect Rick reads on stage: a user who was never asked told they declined."""
    spoken, log_line = user_message_for_expedite_reason( reason )
    for text in ( spoken.lower(), log_line.lower() ):
        assert "cancel" not in text, f"{reason!r} must not blame the user: {text!r}"
        assert "declined" not in text, f"{reason!r} must not blame the user: {text!r}"


def test_unreachable_and_timeout_are_distinct_messages():
    """Mr Radio's steer: undeliverable, timed-out and declined must read apart."""
    unreachable, _ = user_message_for_expedite_reason( BATCH_UNREACHABLE )
    timed_out,   _ = user_message_for_expedite_reason( BATCH_TIMEOUT )
    declined,    _ = user_message_for_expedite_reason( BATCH_DECLINED )
    assert len( { unreachable, timed_out, declined } ) == 3


def test_every_reason_maps_to_a_two_tuple_of_nonempty_strings():
    for reason in ( BATCH_DECLINED, BATCH_UNREACHABLE, BATCH_TIMEOUT,
                    BATCH_MALFORMED, BATCH_INCOMPLETE, BATCH_INTERNAL, None, "garbage" ):
        result = user_message_for_expedite_reason( reason )
        assert isinstance( result, tuple ) and len( result ) == 2
        spoken, log_line = result
        assert spoken and log_line, f"{reason!r} produced an empty string"
