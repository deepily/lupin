"""
Every Jev HTTP attempt, retries included, counts against the shared call cap.
"""
import asyncio
import json

import pytest
from claude_agent_sdk import AssistantMessage, TextBlock

from cosa.repo.doc_lint import jev_transport as jt
from cosa.repo.doc_lint import model_transport as mt
from lupin_mcp import reuse_tools as rt
from lupin_mcp.reuse_needset import call_cap, errors as er

JEV_MODEL = "jev-model-x"
BODY      = { "state": "s", "model": JEV_MODEL, "questions": { } }
ANSWER    = json.dumps( { "answers": { "fit": { "probabilities": { "true": 0.9, "false": 0.1 } } } } )


@pytest.fixture( autouse=True )
def no_hook_left_over():
    yield
    mt.set_charge_hook( None )
    mt.set_budget( None, { } )
    jt.set_charge_hook( None )


class Poster:
    """A stand-in for the HTTP post: answers per script and counts the requests actually sent."""

    def __init__( self, statuses ):
        self.statuses, self.sent = list( statuses ), 0

    def __call__( self, url, headers, body, timeout ):
        self.sent += 1
        status = self.statuses.pop( 0 ) if self.statuses else 200
        return status, ANSWER, { }


def transport( poster, transient=False ):
    """Return a live Jev transport over the stand-in post, with a key and no waiting."""
    return rt.LiveJevTransport( post_fn=poster, sleep_fn=lambda s: None, environ={ jt.KEY_VARIABLE: "k" }, random_fn=lambda: 0.5, clock_fn=lambda: 0.0, transient=transient )


class Llm:
    """A stand-in for sdk_query."""

    async def __call__( self, prompt, options ):
        yield AssistantMessage( content=[ TextBlock( "ok" ) ], model=options.model )


def test_the_hook_sees_the_model_of_each_attempt_and_is_removed_when_unset():
    seen = []
    jt.set_charge_hook( seen.append )
    transport( Poster( [] ) ).post_with_meta( BODY )
    jt.set_charge_hook( None )
    transport( Poster( [] ) ).post_with_meta( BODY )
    assert seen == [ JEV_MODEL ]


def test_a_body_that_names_no_model_is_charged_as_jev():
    seen = []
    jt.set_charge_hook( seen.append )
    for raw in ( b"not json", b"[]", b"{}" ): jt.send_with_meta( raw, Poster( [] ), lambda s: None, { jt.KEY_VARIABLE: "k" } )
    assert seen == [ "jev", "jev", "jev" ]


def test_a_retried_attempt_is_charged_again( tmp_path ):
    cap, poster = call_cap.CallCap( str( tmp_path / "c.jsonl" ) ), Poster( [ 429, 429 ] )
    with cap.installed(): transport( poster ).post_with_meta( BODY )
    assert poster.sent == 3 and cap.used() == 3


def test_the_1001st_attempt_is_refused_by_name_and_sends_nothing( tmp_path ):
    cap, poster = call_cap.CallCap( str( tmp_path / "c.jsonl" ), 1000 ), Poster( [] )
    t = transport( poster )
    with cap.installed():
        for _ in range( 1000 ): t.post_with_meta( BODY )
        with pytest.raises( er.NeedsetError ) as e: t.post_with_meta( BODY )
    assert e.value.code == er.CALL_CAP_REACHED and poster.sent == 1000 and cap.used() == 1000


def test_a_retry_that_would_pass_the_limit_is_refused_before_its_request( tmp_path ):
    cap, poster = call_cap.CallCap( str( tmp_path / "c.jsonl" ), 2 ), Poster( [ 429, 429, 429 ] )
    with cap.installed(), pytest.raises( er.NeedsetError ) as e: transport( poster ).post_with_meta( BODY )
    assert e.value.code == er.CALL_CAP_REACHED and poster.sent == 2 and cap.used() == 2


def test_drafter_calls_and_jev_attempts_share_one_count( tmp_path ):
    cap, poster = call_cap.CallCap( str( tmp_path / "c.jsonl" ), 5 ), Poster( [] )
    with cap.installed(), call_cap.stage( "mixed" ):
        asyncio.run( mt.complete( "claude-fable-5-1", "system", "user", query_fn=Llm() ) )
        transport( poster ).post_with_meta( BODY )
        asyncio.run( mt.complete( "claude-fable-5-1", "system", "user", query_fn=Llm() ) )
        transport( poster ).post_with_meta( BODY )
        transport( poster ).post_with_meta( BODY )
        with pytest.raises( er.NeedsetError ) as e: transport( poster ).post_with_meta( BODY )
    assert e.value.code == er.CALL_CAP_REACHED and poster.sent == 3 and cap.used() == 5 and cap.by_stage() == { "mixed": 5 }
    assert [ r[ "model" ] for r in cap.rows() ] == [ "claude-fable-5-1", JEV_MODEL, "claude-fable-5-1", JEV_MODEL, JEV_MODEL ]


def test_the_hooks_that_were_set_before_come_back_after_the_block( tmp_path ):
    mark, jmark = (lambda m: None), (lambda m: None)
    mt.set_charge_hook( mark )
    jt.set_charge_hook( jmark )
    with call_cap.CallCap( str( tmp_path / "c.jsonl" ) ).installed(): assert mt.CHARGE_HOOK is not mark and jt.CHARGE_HOOK is not jmark
    assert mt.CHARGE_HOOK is mark and jt.CHARGE_HOOK is jmark


def test_without_the_cap_installed_jev_attempts_are_not_counted( tmp_path ):
    cap, poster = call_cap.CallCap( str( tmp_path / "c.jsonl" ) ), Poster( [] )
    transport( poster ).post_with_meta( BODY )
    assert poster.sent == 1 and cap.used() == 0 and jt.CHARGE_HOOK is None
