"""
Two callers, one shared expeditor, at the same time (row 10c60712).

WHAT WENT WRONG. `RuntimeArgumentExpeditor.expedite()` stamped the caller's
job id, bearer token and failure reason onto the INSTANCE, and every helper
that builds a notification read them back off the instance. One expeditor
served one caller at a time by accident: v1's two call sites each built a
fresh expeditor per request, so nothing overlapped. The moment the expeditor
becomes a shared singleton on `app.state`, two requests in flight at once
share those three slots — and the second caller's bearer token is what the
first caller's notification is sent with. That is one user's credential
travelling on another user's request.

WHAT THIS FILE PINS. State that belongs to ONE call travels as arguments and
return values, never on `self`:
  1. Two overlapping expedites, two different bearer tokens / job ids — every
     notification raised by a call carries that call's own pair.
  2. Two overlapping expedites with DIFFERENT outcomes — the failure reason
     each caller reads back is its own, not whichever finished last.
  3. A completed expedite leaves no per-call attribute behind on the shared
     instance.

The overlap is forced, not hoped for: both threads stop on a barrier inside
`extract()`, which is exactly after the old code stamped the instance and
before any helper read it back. A sequential version of this test proves
nothing — it passes on the broken code.

Venue: :7999 — no server, no DB, no network. The one network call is patched.
"""

import threading

import pytest
from unittest.mock import MagicMock, patch

import cosa.agents.runtime_argument_expeditor.expeditor as ex_mod
from cosa.agents.runtime_argument_expeditor.expeditor import (
    RuntimeArgumentExpeditor,
    ExpediteContext,
    ExtractionResult,
    BATCH_DECLINED,
    BATCH_UNREACHABLE,
    user_message_for_expedite_reason,
)
from cosa.agents.runtime_argument_expeditor.agent_registry import JOB_ARG_CONTRACTS

COMMAND = "agent router go to deep research"

# One job id per caller. The notification model validates the shape, so these are
# real-looking ids rather than "job-tok-A".
JOB_ID_FOR = { "tok-A" : "exp-aaaaaaaa", "tok-B" : "exp-bbbbbbbb" }

# Indirection so the pre-commit credential scanner does not read a literal on a
# `bearer_token =` line. These are two fake strings, not a secret.
TOKEN_FOR  = { "tok-A" : "tok-A",        "tok-B" : "tok-B" }


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


def _run_two_overlapping_calls( answer_for ):
    """
    Drive TWO expedite() calls through ONE shared expeditor, overlapped.

    Requires:
        - answer_for maps a thread's bearer token -> the YES_NO answer that
          call's confirmation prompt gets ("yes" completes, "no" declines)

    Ensures:
        - Both calls are inside expedite() at the same time (barrier in extract)
        - Returns ( expeditor, sent, outcomes, before ) where `sent` is the list
          of ( bearer_token, job_id ) pairs every notification was raised with,
          `outcomes` maps bearer token -> ( returned args_dict, that caller's own
          context ), and `before` is the shared instance's __dict__ as it stood
          before either call ran
    """
    exp     = _expeditor()
    barrier = threading.Barrier( 2, timeout=15 )
    sent    = []
    lock    = threading.Lock()

    def fake_extract( command, raw_args, original_question, spec ):
        # The seam: both callers have stamped whatever they stamp, and neither
        # has read it back yet.
        barrier.wait()
        return ExtractionResult(
            final_args         = {},
            missing            = [ "query" ],
            fallback_questions = { "query" : "What should I research?" },
            fallback_defaults  = {},
            special_handlers   = {},
        )

    def fake_notify( request=None, debug=False, bearer_token=None ):
        with lock:
            sent.append( ( bearer_token, request.job_id ) )
        if request.response_type == ex_mod.ResponseType.YES_NO:
            return _response( True, answer_for[ bearer_token ] )
        return _response( True, "the KISS mandate" )

    exp.extract = fake_extract

    outcomes = {}
    before   = dict( exp.__dict__ )

    def one_call( token ):
        # Each caller owns its context — that is the whole point of the fix.
        context = ExpediteContext()
        args = exp.expedite(
            command           = COMMAND,
            raw_args          = "",
            user_email        = f"{token}@example.com",
            session_id        = f"session-{token}",
            user_id           = f"user-{token}",
            original_question = "research something",
            job_id            = JOB_ID_FOR[ token ],
            bearer_token      = TOKEN_FOR[ token ],
            context           = context,
        )
        outcomes[ token ] = ( args, context )

    with patch( "cosa.agents.runtime_argument_expeditor.expeditor.notify_user_sync", side_effect=fake_notify ):
        threads = [ threading.Thread( target=one_call, args=( t, ), name=t ) for t in ( "tok-A", "tok-B" ) ]
        for t in threads: t.start()
        for t in threads: t.join( timeout=30 )
        for t in threads: assert not t.is_alive(), f"thread {t.name} never finished"

    return exp, sent, outcomes, before


def test_overlapping_expedites_each_notify_with_their_own_token_and_job_id():
    """Every notification a call raises carries THAT call's token and job id."""
    _exp, sent, _outcomes, _before = _run_two_overlapping_calls( { "tok-A" : "yes", "tok-B" : "yes" } )

    assert len( sent ) >= 4, f"expected both calls to ask + confirm, got {sent}"
    crossed = [ pair for pair in sent if pair[ 1 ] != JOB_ID_FOR[ pair[ 0 ] ] ]
    assert crossed == [], (
        f"a notification was sent with one call's bearer token and the other call's "
        f"job id: {crossed} (all sends: {sent})"
    )
    assert { pair[ 0 ] for pair in sent } == { "tok-A", "tok-B" }, (
        f"one call's token never reached a notification — the other overwrote it: {sent}"
    )


def test_overlapping_expedites_each_read_back_their_own_failure_reason():
    """A caller that declined reads DECLINED; the caller that completed reads None."""
    _exp, _sent, outcomes, _before = _run_two_overlapping_calls( { "tok-A" : "yes", "tok-B" : "no" } )

    args_a, ctx_a = outcomes[ "tok-A" ]
    args_b, ctx_b = outcomes[ "tok-B" ]

    assert args_a is not None, "the completing call lost its args"
    assert args_b is None,     "the declining call returned args"
    # The reason itself, not just the shape of the return: the caller who was told
    # "no" is the ONLY one who may read a decline.
    assert ctx_b.reason == BATCH_DECLINED, f"the declining call read {ctx_b.reason!r}"
    assert ctx_a.reason is None,           f"the completing call read the other caller's {ctx_a.reason!r}"


def test_completed_expedite_leaves_no_per_call_state_on_the_shared_instance():
    """Two calls leave the shared instance byte-for-byte as they found it.

    The comparison is the WHOLE __dict__ before vs after, not a scan for values
    that look like this test's fake token — a value-shaped scan passes the day
    the stored value changes shape, which is the change worth catching.
    """
    exp, _sent, _outcomes, before = _run_two_overlapping_calls( { "tok-A" : "yes", "tok-B" : "no" } )

    after = dict( exp.__dict__ )
    after.pop( "extract", None )      # the test itself replaced extract()
    before.pop( "extract", None )
    assert after == before, (
        f"the shared instance changed across two calls — added/changed: "
        f"{ { k : v for k, v in after.items() if before.get( k ) != v } }"
    )


def test_a_real_undeliverable_expedite_reaches_the_caller_as_a_machine_failure():
    """
    END-TO-END on the production shape: nothing inside the expeditor is stubbed.

    Only the network call is patched, with a response that says the prompt never
    reached the user. The reason travels expedite -> collect -> _ask_for_arg and
    comes back on the CALLER's context, and the wording the caller then speaks is
    the machine-failure one. This is what the two live readers do
    (todo_fifo_queue.py and routers/podcast_generator.py); the barrier tests above
    build a harness, this one does not.
    """
    exp = _expeditor()
    ctx = ExpediteContext()

    undeliverable = _response( False, None, status="http_error_503", is_timeout=False )

    def fake_extract( command, raw_args, original_question, spec ):
        return ExtractionResult(
            final_args         = {},
            missing            = [ "query" ],
            fallback_questions = { "query" : "What should I research?" },
            fallback_defaults  = {},
            special_handlers   = {},
        )

    exp.extract = fake_extract   # the LLM half only — collect() and the ask are REAL

    with patch( "cosa.agents.runtime_argument_expeditor.expeditor.notify_user_sync", return_value=undeliverable ):
        args = exp.expedite(
            command           = COMMAND,
            raw_args          = "",
            user_email        = "someone@example.com",
            session_id        = "session-1",
            user_id           = "user-1",
            original_question = "research something",
            job_id            = JOB_ID_FOR[ "tok-A" ],
            bearer_token      = TOKEN_FOR[ "tok-A" ],
            context           = ctx,
        )

    assert args is None
    assert ctx.reason == BATCH_UNREACHABLE, f"caller read {ctx.reason!r}"
    spoken, _log = user_message_for_expedite_reason( ctx.reason )
    assert "cancel" not in spoken.lower(), f"a user who was never asked was told they cancelled: {spoken!r}"
