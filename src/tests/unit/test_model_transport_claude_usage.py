"""The Claude Code transport tallies reported usage and names a rate-limited call."""
import asyncio

import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock

from cosa.repo.doc_lint import model_transport as mt

MODEL = "claude-haiku-5-5"


@pytest.fixture( autouse=True )
def fresh_tally():
    """Ensures: the tally starts at zero and is restored afterwards."""
    saved = dict( mt.CLAUDE_USAGE )
    mt.CLAUDE_USAGE.update( { k: 0 for k in mt.CLAUDE_USAGE_FIELDS }, calls=0, cost_usd=0.0 )
    yield
    mt.CLAUDE_USAGE.update( saved )


def result( usage=None, cost=None, error=False, text="denied", subtype=None ):
    """Ensures: returns a ResultMessage; an error defaults to subtype error_during_execution."""
    return ResultMessage( subtype=subtype or ( "error_during_execution" if error else "success" ), duration_ms=1, duration_api_ms=1, is_error=error, num_turns=1, session_id="s", result=text, usage=usage, total_cost_usd=cost )


def call( *messages ):
    """Ensures: runs one complete() whose SDK stand-in yields the messages."""
    async def fake( prompt, options ):
        for m in messages: yield m
    return asyncio.run( mt.complete( MODEL, "s", "u", query_fn=fake ) )


def answer( text="ok" ): return AssistantMessage( content=[ TextBlock( text=text ) ], model=MODEL )


def test_a_finished_call_adds_the_tokens_the_sdk_reported_and_its_notional_cost():
    usage = { "input_tokens": 2, "output_tokens": 4, "cache_creation_input_tokens": 65460, "cache_read_input_tokens": 11382 }
    assert call( answer(), result( usage, 0.0132 ) ) == "ok"
    assert call( answer(), result( usage, 0.0132 ) ) == "ok"
    assert mt.claude_usage_summary() == { "input_tokens": 4, "output_tokens": 8, "cache_creation_input_tokens": 130920, "cache_read_input_tokens": 22764, "calls": 2, "cost_usd": 0.0264 }


def test_a_field_the_sdk_leaves_out_or_reports_as_something_else_adds_nothing_but_the_call_is_counted():
    call( answer(), result( None, None ) )
    call( answer(), result( { "input_tokens": True, "output_tokens": "9", "cache_read_input_tokens": 3 }, True ) )
    assert mt.claude_usage_summary() == { "input_tokens": 0, "output_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 3, "calls": 2, "cost_usd": 0.0 }


def test_the_summary_is_a_copy():
    mt.claude_usage_summary()[ "calls" ] = 99
    assert mt.claude_usage_summary()[ "calls" ] == 0


@pytest.mark.parametrize( "text", [ "Claude usage limit reached", "429 Too Many Requests", "rate_limit_error", "API Error: overloaded" ] )
def test_an_error_result_that_names_a_limit_raises_the_rate_limited_error_which_is_still_a_model_call_error( text ):
    with pytest.raises( mt.ModelRateLimited, match="ended in an error result" ) as caught: call( result( { "input_tokens": 1 }, 0.1, error=True, text=text ) )
    assert isinstance( caught.value, mt.ModelCallError ) and mt.claude_usage_summary()[ "calls" ] == 1, "a refused call is still counted"


REAL_PLAN_LIMIT = "You've reached your Fable limit. Switch to another model, or manage usage credits at https://claude.ai/settings/usage?from=cc_cli_limit_message, to continue."   # captured from a live call, 11 Nov 2026


def test_the_plan_limit_text_a_live_call_returned_raises_the_rate_limited_error():
    with pytest.raises( mt.ModelRateLimited, match="reached your Fable limit" ): call( result( None, None, error=True, text=REAL_PLAN_LIMIT ) )


def test_any_other_error_result_stays_a_plain_model_call_error():
    with pytest.raises( mt.ModelCallError ) as caught: call( result( None, None, error=True, text="boom" ) )
    assert not isinstance( caught.value, mt.ModelRateLimited )


LIVE_PLAN_LIMIT = "You've hit your Fable limit · resets Nov 16, 10am (America/New_York). Switch to another model, or manage usage credits at https://claude.ai/settings/usage?from=cc_cli_limit_message, to continue."   # captured from a live call, 13 Nov 2026: is_error true under subtype "success"


def test_the_plan_limit_of_13_nov_is_a_rate_limit_though_no_marker_names_it():
    assert not any( m in LIVE_PLAN_LIMIT.lower() for m in mt.RATE_LIMIT_MARKERS ), "the live wording must not rely on a marker"
    with pytest.raises( mt.ModelRateLimited ): call( result( None, None, error=True, text=LIVE_PLAN_LIMIT, subtype="success" ) )


@pytest.mark.parametrize( "text, subtype", [ ( "Quota exhausted for this model. Try again later.", "success" ), ( "Fable is out of credit.", "success" ), ( "Out of quota. Resets Monday.", "error_during_execution" ) ] )
def test_a_reworded_limit_is_still_a_rate_limit_by_the_shape_of_the_error_result( text, subtype ):
    with pytest.raises( mt.ModelRateLimited ): call( result( None, None, error=True, text=text, subtype=subtype ) )


def test_a_failure_the_cli_names_with_no_reset_time_stays_a_plain_model_call_error():
    with pytest.raises( mt.ModelCallError ) as caught: call( result( None, None, error=True, text="Reached the turn limit of 1", subtype="error_max_turns" ) )
    assert not isinstance( caught.value, mt.ModelRateLimited )
