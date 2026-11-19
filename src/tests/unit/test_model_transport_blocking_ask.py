"""Tests for blocking_ask, the one blocking ask builder."""
from cosa.repo.doc_lint import model_transport


def test_a_stand_in_call_gets_the_model_the_prompts_and_the_options_and_its_reply_comes_back():
    seen = []

    async def stand_in( model, system, user, **options ):
        seen.append( ( model, system, user, options ) )
        return "reply"

    ask = model_transport.blocking_ask( "m-1", call=stand_in, query_fn="q" )
    assert ask( "sys", "usr" ) == "reply"
    assert ask( "sys2", "usr2" ) == "reply"
    assert seen == [ ( "m-1", "sys", "usr", { "query_fn": "q" } ), ( "m-1", "sys2", "usr2", { "query_fn": "q" } ) ]


def test_with_no_call_it_sends_through_complete_looked_up_when_the_ask_runs(monkeypatch):
    ask   = model_transport.blocking_ask( "m-2", query_fn="q" )
    seen  = []

    async def replacement( model, system, user, **options ):
        seen.append( ( model, system, user, options ) )
        return "late"

    monkeypatch.setattr( model_transport, "complete", replacement )
    assert ask( "s", "u" ) == "late"
    assert seen == [ ( "m-2", "s", "u", { "query_fn": "q" } ) ]
