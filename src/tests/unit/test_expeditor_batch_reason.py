"""
A batch collection must say WHY it came back empty (bug 2aaab1bf).

WHAT WENT WRONG. `_batch_collect_args` returned a bare `None` for five
structurally different outcomes — could-not-deliver, timed-out, malformed
payload, incomplete answers, and a genuine user cancel. The caller printed one
line for all of them:

    [Expeditor] User cancelled batch collection
    -> "Agentic job cancelled by user or timeout."

So when the prompt could not be delivered (HTTP 503 — no websocket registered
for that user, so the user was NEVER ASKED), the job announced that the user had
cancelled it. Observed live on 2026-08-02:

    _batch_collect_args response: success=False, status=http_error_503,
                                  exit_code=1, is_timeout=False, value=None
    [Expeditor] User cancelled batch collection

Note `is_timeout=False` — the code did not even mistake it for a timeout. Every
field needed to tell these apart was captured and printed one line before being
discarded.

WHY IT MATTERED: a `:7999` restart wipes `ws_manager`, after which every blocking
ask 503s as "user offline" while the user is sitting right there. A browser blip
mid-prompt therefore reported the user as having cancelled their own job, with no
error and nothing to retry.

WHAT THIS FILE PINS: the reason travels. Only BATCH_DECLINED is a human decision;
every other outcome must be reported as a machine failure, never as something the
user did.

These tests drive the REAL `_batch_collect_args` with `notify_user_sync` patched,
rather than re-implementing its branching — a mirror of the branch would keep
passing while the branch itself regressed.

Venue: :7999 — no server, no DB, no network. The one network call is patched.
"""

import sys
import types
from unittest.mock import MagicMock, patch

import pytest

from cosa.agents.runtime_argument_expeditor.expeditor import (
    RuntimeArgumentExpeditor,
    BATCH_ANSWERED,
    BATCH_DECLINED,
    BATCH_UNREACHABLE,
    BATCH_MALFORMED,
    BATCH_INCOMPLETE,
)

ARGS      = [ "query", "budget" ]
QUESTIONS = { "query": "What topic?", "budget": "What budget?" }


def _expeditor():
    """An expeditor with config reads stubbed — none of them matter to this path."""
    config = MagicMock()
    config.get.return_value = "unused/for/this/test"
    with patch( "cosa.agents.runtime_argument_expeditor.expeditor.LlmClientFactory" ):
        exp = RuntimeArgumentExpeditor( config, debug=False, verbose=False )
    exp._job_id       = None
    exp._bearer_token = None
    return exp


def _response( success, value, status="ok", is_timeout=False ):
    r = MagicMock()
    r.success        = success
    r.response_value = value
    r.status         = status
    r.is_timeout     = is_timeout
    r.exit_code      = 0 if success else 1
    return r


def _collect( response ):
    """Drive the REAL method with notify_user_sync patched to a given response."""
    exp = _expeditor()
    with patch( "cosa.agents.runtime_argument_expeditor.expeditor.notify_user_sync", return_value=response ):
        return exp._batch_collect_args( ARGS, QUESTIONS, "someone@example.com" )


# --------------------------------------------------------------------------- #
# The defect itself
# --------------------------------------------------------------------------- #

def test_undeliverable_is_unreachable_not_declined():
    """
    THE BUG. A 503 means the user was never asked. It must not be reported as a
    decision the user made.
    """
    answers, reason = _collect( _response( False, None, status="http_error_503", is_timeout=False ) )

    assert answers is None
    assert reason == BATCH_UNREACHABLE, (
        f"a 503 must be {BATCH_UNREACHABLE}, got {reason!r} — the user was never asked"
    )
    assert reason != BATCH_DECLINED, "an undeliverable prompt is not a user decision"


def test_timeout_is_also_unreachable_not_declined():
    """A timeout is a non-answer too — the user may never have seen the prompt."""
    answers, reason = _collect( _response( False, None, status="timeout", is_timeout=True ) )

    assert answers is None
    assert reason == BATCH_UNREACHABLE
    assert reason != BATCH_DECLINED


# --------------------------------------------------------------------------- #
# The outcomes that ARE the user's decision — must stay distinguishable
# --------------------------------------------------------------------------- #

def test_explicit_cancel_flag_is_declined():
    answers, reason = _collect( _response( True, '{"cancelled": true}' ) )

    assert answers is None
    assert reason == BATCH_DECLINED


@pytest.mark.parametrize( "word", [ "cancel", "nevermind", "never mind", "stop", "quit", "  CANCEL  " ] )
def test_cancellation_keyword_in_an_answer_is_declined( word ):
    answers, reason = _collect( _response( True, '{"answers": {"query": "%s", "budget": "10"}}' % word ) )

    assert answers is None
    assert reason == BATCH_DECLINED


# --------------------------------------------------------------------------- #
# The other machine failures — each keeps its own identity
# --------------------------------------------------------------------------- #

def test_unparseable_payload_is_malformed():
    answers, reason = _collect( _response( True, "not json at all {{{" ) )

    assert answers is None
    assert reason == BATCH_MALFORMED


def test_empty_answers_is_malformed():
    answers, reason = _collect( _response( True, '{"answers": {}}' ) )

    assert answers is None
    assert reason == BATCH_MALFORMED


def test_missing_required_arg_is_incomplete():
    """Answered, but one arg never came back — not a cancel, not a transport fault."""
    answers, reason = _collect( _response( True, '{"answers": {"query": "brevity"}}' ) )

    assert answers is None
    assert reason == BATCH_INCOMPLETE


def test_blank_required_arg_is_incomplete():
    answers, reason = _collect( _response( True, '{"answers": {"query": "brevity", "budget": "   "}}' ) )

    assert answers is None
    assert reason == BATCH_INCOMPLETE


# --------------------------------------------------------------------------- #
# The happy path, and the shape of the contract
# --------------------------------------------------------------------------- #

def test_complete_answers_come_back_with_answered():
    answers, reason = _collect( _response( True, '{"answers": {"query": "brevity", "budget": "10"}}' ) )

    assert reason == BATCH_ANSWERED
    assert answers == { "query": "brevity", "budget": "10" }


@pytest.mark.parametrize( "response", [
    _response( False, None, status="http_error_503" ),
    _response( True, "not json" ),
    _response( True, '{"cancelled": true}' ),
    _response( True, '{"answers": {"query": "x", "budget": "y"}}' ),
] )
def test_every_path_returns_a_two_tuple( response ):
    """
    The contract itself. A bare return from ANY branch would crash the caller's
    tuple unpack — which is the failure mode a partial fix would introduce.
    """
    result = _collect( response )

    assert isinstance( result, tuple ) and len( result ) == 2, (
        f"every return must be ( answers, reason ); got {result!r}"
    )
    answers, reason = result
    assert reason in ( BATCH_ANSWERED, BATCH_DECLINED, BATCH_UNREACHABLE,
                       BATCH_MALFORMED, BATCH_INCOMPLETE ), f"unknown reason {reason!r}"


def test_the_five_reasons_are_distinct():
    """
    Guards against a well-meaning 'simplification' that collapses two reasons back
    into one — which is the original defect, just with nicer names.
    """
    reasons = [ BATCH_ANSWERED, BATCH_DECLINED, BATCH_UNREACHABLE, BATCH_MALFORMED, BATCH_INCOMPLETE ]

    assert len( set( reasons ) ) == 5, "the BATCH_* reasons must not share values"


def test_only_declined_is_treated_as_a_user_decision_by_the_caller():
    """
    CONTACT CHECK on the real caller. The tests above prove the reason is
    produced; this proves the caller ACTS on it — that it says "user declined"
    only for BATCH_DECLINED, and reports everything else as a machine failure.

    Source-level, not behavioural: driving the full expedite() needs an LLM, a
    registry entry and a notification round-trip. It proves the branch exists and
    is keyed on the right constant, NOT that it executes.
    """
    import os

    root = os.environ.get( "LUPIN_ROOT" )
    assert root, "LUPIN_ROOT not set — export LUPIN_ROOT=/path/to/project"

    with open( os.path.join( root, "src/cosa/agents/runtime_argument_expeditor/expeditor.py" ) ) as fh:
        src = fh.read()

    assert "batch_answers, batch_reason = self._batch_collect_args(" in src, (
        "the caller no longer unpacks the reason — it cannot distinguish a "
        "cancellation from a delivery failure, and bug 2aaab1bf is back"
    )
    assert "if batch_reason == BATCH_DECLINED:" in src, (
        "the caller must branch on BATCH_DECLINED specifically"
    )
    # ⚠️ Match the CODE, not a description of it. An earlier version of this
    # assertion looked for the bare string "User cancelled batch collection" and
    # failed — because the docstring in expeditor.py QUOTES that line while
    # explaining the bug. A predicate that matches prose about the defect is not
    # a predicate about the defect.
    assert 'print( "[Expeditor] User cancelled batch collection" )' not in src, (
        "the old unconditional 'User cancelled' print is back — it reports every "
        "failure, including an undelivered prompt, as the user's decision"
    )
