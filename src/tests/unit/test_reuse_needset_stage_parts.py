"""
The live parts of the attribution and yield stages, run on fake models and fake search.
"""
import asyncio
import json
import threading
import types

import pytest

from lupin_mcp.reuse_needset import call_cap, draft, first_thousand as ft, keys, loss_trace, stage_parts as sp, stages
from lupin_mcp.reuse_needset import errors as er
from tests.unit.test_reuse_needset_first_thousand import SENTENCE, real_pair, strip_of

AGREE = json.dumps( { "result": "agree", "note": "same job" } )


def job_for_pair():
    """Return a job for the first planted pair with the meta a routed job carries."""
    job = ft.control_job( real_pair(), strip_of )
    job[ "meta" ] = { "route": "vector", "key_source": "vector", "key_lang": "py", "asked": 1 }
    return job


def renv_for( tmp_path, ask=lambda system, user: SENTENCE ):
    """Return the run namespace over the first pair, seed d-orig00 and key d-rew00."""
    job = job_for_pair()
    return types.SimpleNamespace( ctx=types.SimpleNamespace( by_id={ "d-orig00": job[ "seed" ] }, bodies={ "d-rew00": "def rewritten_body(): return 1" } ), ask=ask,
                                  ledger=draft.make_ledger( str( tmp_path / "draft.jsonl" ), None, "max-plan" ), model_id=draft.DRAFTER_MODEL, calls_log=None,
                                  by_id={ "d-orig00": job[ "seed" ] }, strip_fn=strip_of, server="max-plan", source_commit="abc", smoke=False )


def final_fn( tmp_path, reply=AGREE, job=lambda *a: job_for_pair(), renv=None, asked=None ):
    """Return ( final_need function, tally ) over fakes; asked collects the checker's prompts."""
    tally  = sp.Tally()
    seen   = [] if asked is None else asked

    def second( prompt ):
        seen.append( prompt )
        return reply

    fn = sp.final_need_fn( renv or renv_for( tmp_path ), { "d-orig00": "vector" }, second, draft.make_ledger( str( tmp_path / "second.jsonl" ), None, "max-plan" ), "second-model", tally, job_for=job )
    return fn, tally


def test_an_agreed_need_is_final_by_the_models_alone_and_the_checker_saw_the_key_source( tmp_path ):
    asked  = []
    fn, tally = final_fn( tmp_path, asked=asked )
    need   = fn( "d-orig00" )
    assert need[ "status" ] == "final" and need[ "final" ] == { "choice": None, "symbols": None, "final_source": "model_agreed" } and need[ "need" ] == SENTENCE
    assert need[ "check" ][ "model" ] == "second-model" and need[ "check" ][ "result" ] == "agree" and need[ "kind" ] == "work_alike" and need[ "key" ][ "symbols" ] == [ "d-rew00" ]
    assert len( asked ) == 1 and "def rewritten_body(): return 1" in asked[ 0 ] and sum( tally.values() ) == 0 and tally.ids == []


@pytest.mark.parametrize( "result", [ "disagree", "unsure" ] )
def test_a_disputed_need_is_counted_by_id_and_never_returned( tmp_path, result ):
    fn, tally = final_fn( tmp_path, reply=json.dumps( { "result": result, "note": "n" } ) )
    assert fn( "d-orig00" ) is None
    assert tally[ "disputed" ] == 1 and len( tally.ids ) == 1 and tally.ids[ 0 ].startswith( "n-" ) and sum( tally.values() ) == 1


def test_a_seed_outside_the_search_pool_is_counted_and_asks_nothing( tmp_path ):
    renv      = renv_for( tmp_path )
    renv.ctx.by_id.clear()
    fn, tally = final_fn( tmp_path, renv=renv, job=lambda *a: pytest.fail( "a key was looked for" ) )
    assert fn( "d-orig00" ) is None and dict( tally ) == { "not_pooled": 1 }


def test_a_seed_with_no_partner_is_counted_and_drafts_nothing( tmp_path ):
    fn, tally = final_fn( tmp_path, job=lambda *a: None, renv=renv_for( tmp_path, ask=lambda s, u: pytest.fail( "the drafter was called" ) ) )
    assert fn( "d-orig00" ) is None and dict( tally ) == { "no_partner": 1 }


def test_a_seed_whose_sentence_never_passes_is_counted_and_not_checked( tmp_path ):
    fn, tally = final_fn( tmp_path, renv=renv_for( tmp_path, ask=lambda s, u: "no json here" ), reply=pytest.fail )
    assert fn( "d-orig00" ) is None and dict( tally ) == { "draft_failed": 1 }


def test_the_job_is_asked_for_the_seeds_language_and_route( tmp_path ):
    got = []
    fn, _ = final_fn( tmp_path, job=lambda env, kind, seed_id, lang, route: got.append( ( kind, seed_id, lang, route ) ) or job_for_pair() )
    fn( "d-orig00" )
    assert got == [ ( "work_alike", "d-orig00", "py", "vector" ) ]


def test_the_checker_may_not_be_the_drafter( tmp_path ):
    tally = sp.Tally()
    fn    = sp.final_need_fn( renv_for( tmp_path ), { "d-orig00": "vector" }, lambda p: AGREE, draft.make_ledger( str( tmp_path / "s.jsonl" ), None, "max-plan" ), draft.DRAFTER_MODEL, tally, job_for=lambda *a: job_for_pair() )
    with pytest.raises( er.NeedsetError ) as e: fn( "d-orig00" )
    assert e.value.code == er.CHECKER_EQUALS_DRAFTER


def lists_of( seed_count=5 ):
    """Return seed lists with seed_count ids per stage and language."""
    return { name: { lang: [ f"{name}-{lang}-{i}" for i in range( seed_count ) ] for lang in ( "ts", "py" ) } for name in ( stages.ATTRIBUTION, stages.YIELD ) }


def test_the_routes_cover_every_listed_seed_and_split_each_stage_and_language_evenly():
    lists  = lists_of( 6 )
    routes = sp.route_table( lists, 7 )
    assert len( routes ) == 24
    for name in ( stages.ATTRIBUTION, stages.YIELD ):
        for lang in ( "ts", "py" ): assert sorted( routes[ i ] for i in lists[ name ][ lang ] ).count( "vector" ) == 3
    assert routes == sp.route_table( lists, 7 ) and routes != sp.route_table( lists, 8 )


def test_a_yield_row_is_the_seed_the_sentence_the_key_and_the_language():
    need = { "seed": "s", "need": "n", "key": { "symbols": [ "a", "b" ] }, "write_lang": "ts" }
    assert sp.yield_row( need ) == { "seed": "s", "need": "n", "targets": [ "a", "b" ], "lang": "ts" }


def test_the_counts_name_the_four_reasons_and_the_disputed_ids():
    tally = sp.Tally()
    tally[ "disputed" ] += 1
    tally.ids.append( "n-1" )
    assert sp.counted( tally ) == { "not_pooled": 0, "no_partner": 0, "draft_failed": 0, "disputed": 1, "unreadable_reply": 0, "disputed_ids": [ "n-1" ], "skipped": [] }
    tally[ "unreadable_reply" ] += 1
    tally.skipped.append( { "seed": "s-1", "code": "UNREADABLE_REPLY", "detail": "earlier stage" } )
    since = sp.mark( tally )
    tally[ "disputed" ] += 2
    tally[ "no_partner" ] += 1
    tally.ids.append( "n-2" )
    tally[ "unreadable_reply" ] += 1
    tally.skipped.append( { "seed": "s-9", "code": "UNREADABLE_REPLY", "detail": "k" } )
    assert sp.counted( tally, since ) == { "not_pooled": 0, "no_partner": 1, "draft_failed": 0, "disputed": 2, "unreadable_reply": 1, "disputed_ids": [ "n-2" ], "skipped": [ { "seed": "s-9", "code": "UNREADABLE_REPLY", "detail": "k" } ] }


class Vectors:
    """A vector set with a fixed list of ids."""

    ids = [ "ts-0", "ts-1" ]


def build( tmp_path, final=None, trace_all=None, identity=None, ledgers=None, monkeypatch=None ):
    """Build the parts over three index records, two of them with a vector row."""
    rows  = [ { "id": i, "lang": "ts", "file": f"{i}.ts", "name": i, "module": "m", "sig": i, "doc": "" } for i in ( "ts-0", "ts-1", "ts-2" ) ]
    built = ( { r[ "id" ]: r for r in rows }, rows, "MEASURES", None, { r[ "id" ]: "body" for r in rows } )
    env   = types.SimpleNamespace( root="/r", seed=7, source_commit="abc", server="max-plan", strip_fn=strip_of, ctx=types.SimpleNamespace( candidate_stage=types.SimpleNamespace( vectors_dir="/v" ) ) )
    seen  = {}
    monkeypatch.setattr( sp, "final_need_fn", lambda renv, routes, second_ask, second_ledger, second_model, tally, **kw: seen.update( renv=renv, routes=routes, second=second_ask( "p" ), model=second_model ) or final )
    monkeypatch.setattr( sp.rt, "prepare", lambda ctx: ( None, None, "sha", "GEN" ) )
    parts = sp.build_parts( env, built, lists_of( 2 ), { "second": "M2", "probe": "MP" }, "DRAFT", lambda system, user: f"{system}|{user}", ledgers or { "draft": "LD", "second": "LS", "trace": "LT" },
                            trace_all=trace_all, identity=identity or ( lambda gen, vdir: { "gen": gen, "vdir": vdir } ), load_vectors=lambda folder: Vectors() )
    return parts, seen, env


def test_the_parts_search_only_seeds_with_a_vector_row_and_route_every_listed_seed( tmp_path, monkeypatch ):
    parts, seen, _ = build( tmp_path, monkeypatch=monkeypatch )
    assert sorted( seen[ "renv" ].ctx.by_id ) == [ "ts-0", "ts-1" ] and seen[ "renv" ].ask == "DRAFT" and seen[ "renv" ].ledger == "LD" and seen[ "renv" ].model_id == draft.DRAFTER_MODEL
    assert seen[ "renv" ].ctx.bodies[ "ts-2" ] == "body" and seen[ "renv" ].ctx.seed == 7 and seen[ "renv" ].smoke is False and len( seen[ "routes" ] ) == 8
    assert seen[ "second" ] == f"{sp.SECOND_SYSTEM}|p" and seen[ "model" ] == "M2"
    assert parts[ "index" ].ids == ( "ts-0", "ts-1", "ts-2" ) and isinstance( parts[ "tally" ], sp.Tally )


def test_make_need_and_prepare_fn_run_on_a_worker_thread_under_the_callers_cap_stage( tmp_path, monkeypatch ):
    seen = {}

    def final( seed_id ):
        seen[ seed_id ] = ( threading.current_thread() is threading.main_thread(), call_cap._STAGE.get() )
        return None if seed_id == "none" else { "seed": seed_id, "need": "n", "key": { "symbols": [ "k" ] }, "write_lang": "ts" }

    parts, _, _ = build( tmp_path, final=final, monkeypatch=monkeypatch )

    async def go():
        with call_cap.stage( "attribution" ): one = await parts[ "make_need" ]( "a" )
        with call_cap.stage( "yield" ): two = await parts[ "prepare_fn" ]( "b" )
        return one, two, await parts[ "prepare_fn" ]( "none" )

    one, two, nothing = asyncio.run( go() )
    assert one[ "seed" ] == "a" and two == { "seed": "b", "need": "n", "targets": [ "k" ], "lang": "ts" } and nothing is None
    assert seen[ "a" ] == ( False, "attribution" ) and seen[ "b" ] == ( False, "yield" )


def test_the_trace_is_trace_all_over_the_runs_context_ledger_models_and_identities( tmp_path, monkeypatch ):
    got   = {}
    turns = iter( [ { "g": 1 }, { "g": 2 } ] )

    async def trace_all( needs, ctx, ledger, root, model, checker_commit, manifest, live ):
        got.update( needs=needs, ctx=ctx, ledger=ledger, root=root, model=model, commit=checker_commit, manifest=manifest, live=live )
        return [ "record" ]

    parts, _, env = build( tmp_path, trace_all=trace_all, identity=lambda gen, vdir: next( turns ), monkeypatch=monkeypatch )
    assert asyncio.run( parts[ "trace_fn" ]( [ "need" ] ) ) == [ "record" ]
    assert got == { "needs": [ "need" ], "ctx": env.ctx, "ledger": "LT", "root": "/r", "model": "MP", "commit": "abc", "manifest": { "g": 1 }, "live": { "g": 2 } }


def test_a_moved_index_or_vector_set_is_refused_before_any_call( tmp_path, monkeypatch ):
    names = iter( [ { k: "a" for k in ( "index_manifest", "symbols_sha", "vector_build_info_sha" ) }, { k: "b" for k in ( "index_manifest", "symbols_sha", "vector_build_info_sha" ) } ] )
    parts, _, _ = build( tmp_path, trace_all=loss_trace.trace_all, identity=lambda gen, vdir: next( names ), monkeypatch=monkeypatch )
    with pytest.raises( er.NeedsetError ) as e: asyncio.run( parts[ "trace_fn" ]( [ { "id": "n-1" } ] ) )
    assert e.value.code == er.INDEX_DIFFERS


def test_an_unreadable_same_job_reply_skips_the_seed_with_the_reason_recorded_and_the_next_seed_goes_on( tmp_path ):
    ledger = draft.make_ledger( str( tmp_path / "keys.jsonl" ), None, "max-plan" )
    turns  = iter( [ "garbage", "garbage" ] )
    tally  = sp.Tally()

    def job( env, kind, seed_id, lang, route ):
        if seed_id == "bad": return keys.ruled( lambda prompt: next( turns ), ledger, "k-1", "p", "same_job" )
        return job_for_pair()

    renv = renv_for( tmp_path )
    renv.ctx.by_id[ "bad" ] = renv.by_id[ "bad" ] = renv.by_id[ "d-orig00" ]
    fn   = sp.final_need_fn( renv, { "bad": "vector", "d-orig00": "vector" }, lambda p: AGREE, draft.make_ledger( str( tmp_path / "s.jsonl" ), None, "max-plan" ), "second-model", tally, job_for=job )
    assert fn( "bad" ) is None and tally[ "unreadable_reply" ] == 1 and tally.skipped == [ { "seed": "bad", "code": er.UNREADABLE_REPLY, "detail": "k-1" } ]
    assert fn( "d-orig00" )[ "status" ] == "final" and tally[ "unreadable_reply" ] == 1


def test_an_unreadable_check_reply_skips_the_seed_the_same_way_and_another_error_still_stops_the_stage( tmp_path ):
    tally = sp.Tally()

    def unreadable( *a, **k ): raise er.NeedsetError( er.UNREADABLE_REPLY, "check-key" )

    fn = sp.final_need_fn( renv_for( tmp_path ), { "d-orig00": "vector" }, lambda p: AGREE, draft.make_ledger( str( tmp_path / "s.jsonl" ), None, "max-plan" ), "second-model", tally, job_for=lambda *a: job_for_pair(), check_fn=unreadable )
    assert fn( "d-orig00" ) is None and tally.skipped[ 0 ][ "detail" ] == "check-key" and tally[ "unreadable_reply" ] == 1

    def capped( *a, **k ): raise er.NeedsetError( er.CALL_CAP_REACHED, "1000 of 1000" )

    fn = sp.final_need_fn( renv_for( tmp_path ), { "d-orig00": "vector" }, lambda p: AGREE, draft.make_ledger( str( tmp_path / "s2.jsonl" ), None, "max-plan" ), "second-model", tally, job_for=capped )
    with pytest.raises( er.NeedsetError ) as e: fn( "d-orig00" )
    assert e.value.code == er.CALL_CAP_REACHED and tally[ "unreadable_reply" ] == 1
