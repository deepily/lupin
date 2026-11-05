"""
Unit tests for the optional need expansion of the candidate stage.

The claims fall in two groups.
The INI switch `reuse candidate need expansion enabled` turns it on.
With the switch off nothing changes: the request, the answer, the receipt block and the built stage are those of a lookup without expansion.
With it on, the paraphrases and identifier words are searched too and fused into the same shortlist.
The expansion is recorded, and a replay or a widening reuses the recorded one.
The model is a stand-in, so the merge gate makes no model call.
"""
import asyncio
import copy
import json
import types

import numpy as np
import pytest

from cosa.repo.doc_lint import model_transport
from cosa.repo.symindex.candidates import search
from cosa.repo.symindex.candidates import storage_paths as sp
from cosa.repo.symindex.candidates.errors import CandidateError
from lupin_mcp import reuse_candidates as rcand
from lupin_mcp import reuse_expansion as rex
from lupin_mcp import reuse_tools as rt
from lupin_mcp.reuse_needset import expansion_replay as ex
from tests.unit.test_candidates_search_process import ENTRIES as SEARCH_ENTRIES, FakeSet, generation, request_for, run_main     # noqa: F401  (generation is a fixture)
from tests.unit.test_reuse_candidates_client import lookup, world                                                                # noqa: F401  (world is a fixture)

EXPANSION = { "paraphrases": [ "read settings", "load a settings file", "settings loader" ], "identifiers": [ "settings", "load" ] }
Q_B       = { "prose": [ 0.0, 1.0 ], "code": [ 0.0, 1.0 ], "concat": [ 0.0, 1.0 ] }                                   # along y: py:b in FakeSet
Q_A       = { "prose": [ 1.0, 0.0 ], "code": [ 1.0, 0.0 ], "concat": [ 1.0, 0.0 ] }
ONE       = { "k": 60, "depth": 100, "head": 0 }                                                                          # no head ids are forced in, so K alone decides


class FakeConfig:
    """A config manager that answers from a dict and returns None for an absent key."""

    def __init__( self, values ): self.values = values

    def get( self, key, default=None, silent=False, return_type="string" ): return self.values.get( key, default )


# --- the search process: extra_queries ----------------------------------------------------------------------------------------------------

def test_extra_queries_add_their_own_lists_named_by_position_and_source( generation ):
    request = request_for( generation, vectors_dir="v", query_vectors=Q_A, extra_queries=[ { "need": "settings", "query_vectors": Q_B } ] )
    code, answer = run_main( request )
    assert code == 0
    assert set( answer[ "lists" ] ) == { "code", "prose", "vector_concat", "vector_prose", "vector_code", "x0_code", "x0_prose", "x0_vector_concat", "x0_vector_prose", "x0_vector_code" }
    assert answer[ "lists" ][ "x0_code" ][ 0 ] == "py:b" and answer[ "lists" ][ "x0_vector_concat" ][ 0 ] == "py:b"      # the extra need ranks py:b first, not py:a


def test_two_extra_queries_on_one_entry_outvote_the_need_itself_at_k_one( generation ):
    plain = run_main( request_for( generation, K=1, fusion=ONE, vectors_dir="v", query_vectors=Q_A ) )[ 1 ]
    more  = run_main( request_for( generation, K=1, fusion=ONE, vectors_dir="v", query_vectors=Q_A,
                                   extra_queries=[ { "need": "settings", "query_vectors": Q_B }, { "need": "load", "query_vectors": Q_B } ] ) )[ 1 ]
    assert plain[ "shortlist" ] == [ "py:a" ] and more[ "shortlist" ] == [ "py:b" ]


def test_an_empty_or_absent_extra_queries_leaves_the_answer_byte_for_byte_alone( generation ):
    base  = run_main( request_for( generation, vectors_dir="v", query_vectors=Q_A ) )[ 1 ]
    empty = run_main( request_for( generation, vectors_dir="v", query_vectors=Q_A, extra_queries=[] ) )[ 1 ]
    assert json.dumps( empty, sort_keys=True ) == json.dumps( base, sort_keys=True )
    assert not any( name.startswith( "x" ) for name in base[ "lists" ] )


@pytest.mark.parametrize( "extra, detail", [
    ( "x",                                                           "extra_queries is not a list" ),
    ( [ "x" ],                                                       "extra_queries[0] needs a string need" ),
    ( [ { "need": 3, "query_vectors": Q_A } ],                       "extra_queries[0] needs a string need" ),
    ( [ { "need": "s" } ],                                           "extra_queries[0].query_vectors is missing or empty" ),
    ( [ { "need": "s", "query_vectors": { "concat": [ "a" ] } } ],   "query vector concat is not a non-empty list of numbers" ),
] )
def test_a_malformed_extra_queries_is_a_named_request_error( generation, extra, detail ):
    code, answer = run_main( request_for( generation, vectors_dir="v", query_vectors=Q_A, extra_queries=extra ) )
    assert code == 2 and answer[ "error" ] == search.REQUEST_ERROR and detail in answer[ "detail" ]


def test_extra_queries_need_the_vector_folder_but_an_empty_list_does_not( generation ):
    code, answer = run_main( request_for( generation, extra_queries=[ { "need": "s", "query_vectors": Q_B } ] ) )
    assert code == 2 and "extra_queries needs vectors_dir" in answer[ "detail" ]
    assert run_main( request_for( generation, extra_queries=[] ) )[ 0 ] == 0


def test_the_vector_check_names_its_label():
    seen = []
    def bad( detail ): seen.append( detail ); raise CandidateError( search.REQUEST_ERROR, detail )
    with pytest.raises( CandidateError ): search.validate_query_vectors( None, "query_vectors", bad )
    assert seen == [ "query_vectors is missing or empty" ]


def test_cosine_lists_prefix_the_names_and_keep_the_default_names_unprefixed():
    loaded = FakeSet()
    lists, scores = search.cosine_lists( loaded, { "py:a", "py:b" }, { "concat": [ 1.0, 0.0 ] } )
    assert list( lists ) == [ "vector_concat" ] and lists[ "vector_concat" ] == [ "py:a", "py:b" ] and scores[ "vector_concat" ] == [ 1.0, 0.0 ]
    assert list( search.cosine_lists( loaded, { "py:a" }, { "concat": [ 1.0, 0.0 ] }, "x2_" )[ 0 ] ) == [ "x2_vector_concat" ]


# --- the switch ---------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize( "value, want", [ ( "true", True ), ( " TRUE ", True ), ( "1", True ), ( "yes", True ), ( "On", True ), ( "false", False ), ( "0", False ),
                                          ( "", False ), ( "  ", False ), ( "enabled", False ), ( None, False ) ] )
def test_the_ini_switch_is_on_only_for_a_true_word( value, want ):
    ini = FakeConfig( {} if value is None else { "reuse candidate need expansion enabled": value } )
    assert sp.need_expansion_enabled( ini, {} ) is want


def test_a_non_blank_override_variable_decides_alone_and_a_blank_one_is_ignored():
    on  = FakeConfig( { "reuse candidate need expansion enabled": "true" } )
    off = FakeConfig( { "reuse candidate need expansion enabled": "false" } )
    assert sp.need_expansion_enabled( off, { "LUPIN_REUSE_CANDIDATE_NEED_EXPANSION": "true" } ) is True
    assert sp.need_expansion_enabled( on,  { "LUPIN_REUSE_CANDIDATE_NEED_EXPANSION": "no" } ) is False
    assert sp.need_expansion_enabled( on,  { "LUPIN_REUSE_CANDIDATE_NEED_EXPANSION": "  " } ) is True


def test_the_switch_reads_os_environ_and_builds_the_config_when_none_is_given( monkeypatch ):
    monkeypatch.setenv( "LUPIN_REUSE_CANDIDATE_NEED_EXPANSION", "yes" )
    assert sp.need_expansion_enabled() is True
    monkeypatch.delenv( "LUPIN_REUSE_CANDIDATE_NEED_EXPANSION" )
    monkeypatch.setattr( sp, "build_config", lambda: FakeConfig( { "reuse candidate need expansion enabled": "on" } ) )
    assert sp.need_expansion_enabled() is True


def test_the_shipped_ini_has_the_switch_and_it_is_false():
    import pathlib, re
    ini = pathlib.Path( rt.__file__ ).resolve().parents[ 1 ] / "conf" / "lupin-app.ini"
    assert re.findall( r"^reuse candidate need expansion enabled\s*=\s*(\S+)\s*$", ini.read_text( encoding="utf-8" ), re.M ) == [ "false" ]
    splainer = ini.with_name( "lupin-app-splainer.ini" ).read_text( encoding="utf-8" )
    assert re.search( r"^reuse candidate need expansion enabled\s*= Whether", splainer, re.M )


def test_the_environment_builds_a_stage_with_no_expander_unless_the_switch_is_on( monkeypatch, tmp_path ):
    monkeypatch.setattr( rt, "data_dir", lambda top: tmp_path )
    monkeypatch.setattr( sp, "candidate_dir", lambda name, data, config=None, environ=None: tmp_path / name )
    monkeypatch.setattr( sp, "shortlist_arm", lambda default, config=None, environ=None: default )
    from cosa.memory.embedding_provider import EmbeddingProvider
    monkeypatch.setattr( EmbeddingProvider, "_resolve_http_target", staticmethod( lambda secure: ( "http://lupin:7999", "k", "" ) ) )
    def never_read( config=None, environ=None ): raise AssertionError( "the protected head is read only when the switch is on" )
    monkeypatch.setattr( sp, "need_expansion_protected_head", never_read )
    monkeypatch.setattr( sp, "need_expansion_enabled", lambda config=None, environ=None: False )
    off = rt._candidate_stage( tmp_path )
    assert off._expander is None and off._protected_head is None
    monkeypatch.setattr( sp, "need_expansion_enabled", lambda config=None, environ=None: True )
    monkeypatch.setattr( sp, "need_expansion_protected_head", lambda config=None, environ=None: 64 )
    on = rt._candidate_stage( tmp_path )
    assert callable( on._expander ) and on._protected_head == 64


def test_a_bad_protected_head_with_the_switch_on_is_a_named_unconfigured_error( monkeypatch, tmp_path ):
    monkeypatch.setattr( rt, "data_dir", lambda top: tmp_path )
    monkeypatch.setattr( sp, "candidate_dir", lambda name, data, config=None, environ=None: tmp_path / name )
    monkeypatch.setattr( sp, "shortlist_arm", lambda default, config=None, environ=None: default )
    monkeypatch.setattr( sp, "need_expansion_enabled", lambda config=None, environ=None: True )
    monkeypatch.setenv( "LUPIN_REUSE_CANDIDATE_NEED_EXPANSION_PROTECTED_HEAD", "many" )
    with pytest.raises( rt.ReuseError, match="CANDIDATE_STAGE_UNCONFIGURED" ): rt._candidate_stage( tmp_path )


# --- the expander -------------------------------------------------------------------------------------------------------------------------

def reply_of( expansion=None ): return json.dumps( EXPANSION if expansion is None else expansion )


def test_the_expander_asks_the_measured_prompt_with_the_need_sentence_only():
    asked = []
    def ask( system, user ): asked.append( ( system, user ) ); return reply_of()
    got = rex.make_expander( ask )( "read an rss feed" )
    assert got == EXPANSION and asked == [ ( ex.SYSTEM, ex.expansion_prompt( "read an rss feed" ) ) ]
    assert "read an rss feed" in asked[ 0 ][ 1 ] and asked[ 0 ][ 1 ].count( "\n" ) == ex.expansion_prompt( "read an rss feed" ).count( "\n" )


@pytest.mark.parametrize( "error", [ model_transport.ModelCallError( "boom" ), model_transport.CallBudgetExceeded( "spent" ) ] )
def test_a_failed_model_call_searches_without_expansion_and_says_so( error ):
    lines = []
    def ask( system, user ): raise error
    assert rex.make_expander( ask, out=lines.append )( "need" ) is None
    assert len( lines ) == 1 and "searching without expansion" in lines[ 0 ] and type( error ).__name__ in lines[ 0 ]


def test_a_reply_that_is_not_three_paraphrases_and_identifiers_searches_without_expansion_and_says_so():
    lines = []
    assert rex.make_expander( lambda s, u: "not json at all", out=lines.append )( "need" ) is None
    assert len( lines ) == 1 and "not three paraphrases" in lines[ 0 ]
    assert rex.make_expander( lambda s, u: reply_of( { "paraphrases": [ "one" ], "identifiers": [ "x" ] } ), out=lines.append )( "need" ) is None


def test_the_real_call_goes_through_model_transport_on_a_thread_of_its_own_even_inside_a_running_loop( monkeypatch ):
    calls = []
    async def complete( model, system, user, **kw ): calls.append( ( model, system, user ) ); return reply_of()
    monkeypatch.setattr( model_transport, "complete", complete )
    async def inside_a_loop(): return rex.make_expander()( "a need" )
    assert asyncio.run( inside_a_loop() ) == EXPANSION
    assert calls == [ ( rex.EXPANSION_MODEL, ex.SYSTEM, ex.expansion_prompt( "a need" ) ) ]


def test_the_expander_model_is_the_one_the_measured_replay_used():
    from lupin_mcp.reuse_needset import draft
    assert rex.EXPANSION_MODEL == draft.DRAFTER_MODEL


# --- the client: off is today, on adds the lists -------------------------------------------------------------------------------------------

def test_with_no_expander_the_request_and_the_answer_are_those_of_a_lookup_that_never_heard_of_expansion( world ):
    make, bridge, *_ = world
    plain = lookup( make() )
    body  = bridge.seen[ -1 ][ 2 ]
    assert "extra_queries" not in body and "expansion" not in plain and not any( name.startswith( "x" ) for name in plain[ "lists" ] )
    bridge.seen.clear()
    blank = lookup( make( expander=lambda text: None ) )                                    # an expander that gives nothing is the same lookup
    assert bridge.seen[ -1 ][ 2 ] == body and blank == plain


def test_an_expander_adds_four_queries_embeds_them_and_records_the_expansion( world ):
    make, bridge, embedder, *_ = world
    asked = []
    def expander( text ): asked.append( text ); return copy.deepcopy( EXPANSION )
    got   = lookup( make( expander=expander ), "profile" )
    extra = bridge.seen[ -1 ][ 2 ][ "extra_queries" ]
    assert asked == [ "profile" ] and got[ "expansion" ] == EXPANSION
    assert [ q[ "need" ] for q in extra ] == EXPANSION[ "paraphrases" ] + [ "settings load" ] and all( set( q[ "query_vectors" ] ) == { "concat" } for q in extra )
    assert {"settings load", "read settings"} <= { t for texts, *_ in embedder.embeds for t in texts }
    assert {"x0_code", "x0_prose", "x0_vector_concat", "x3_code", "x3_prose", "x3_vector_concat"} <= set( got[ "lists" ] )


def test_a_recorded_expansion_replays_from_the_cache_without_asking_the_expander( world ):
    make, bridge, embedder, *_ = world
    first = lookup( make( expander=lambda text: copy.deepcopy( EXPANSION ) ), "profile" )
    def never( text ): raise AssertionError( "the expander must not be asked on a replay" )
    embedder.embeds.clear()
    again = lookup( make( expander=never ), "profile", cache_only=True, expansion=first[ "expansion" ] )
    assert again[ "ids" ] == first[ "ids" ] and again[ "expansion" ] == EXPANSION
    assert embedder.embeds == []                                                           # every extra vector came from the cache


def test_a_replay_with_no_recorded_expansion_does_not_expand_even_when_an_expander_is_set( world ):
    make, bridge, *_ = world
    lookup( make(), "profile" )                                                            # warms the cache for the need itself
    def never( text ): raise AssertionError( "cache_only must not call the expander" )
    got = lookup( make( expander=never ), "profile", cache_only=True )
    assert "expansion" not in got and "extra_queries" not in bridge.seen[ -1 ][ 2 ]


def test_a_recorded_expansion_given_to_a_live_lookup_replaces_the_expander( world ):
    make, bridge, *_ = world
    def never( text ): raise AssertionError( "a recorded expansion is never asked again" )
    got = lookup( make( expander=never ), "profile", expansion=copy.deepcopy( EXPANSION ) )
    assert got[ "expansion" ] == EXPANSION and len( bridge.seen[ -1 ][ 2 ][ "extra_queries" ] ) == 4


# --- the receipt, the replay and the widening ----------------------------------------------------------------------------------------------

class Client:
    """The part of the stage client the receipt and replay code reads."""

    arm, K = "B1", 128


def stage_dict( **more ):
    return dict( { "K": 128, "manifest_hash": "m" * 64, "embed_models": { "code": "c", "prose": "p" }, "lists": {}, "widened": False, "ids": [ "a" ], "ranking_hash": "r" * 64,
                   "stage_key": "k" * 32, "wiki": 0, "wiki_ids": [] }, **more )


def test_the_receipt_block_records_an_expansion_only_when_the_lookup_had_one():
    routed = { "deciding": [ { "id": "a" } ] }
    plain  = rt._candidate_receipt( stage_dict(), None, Client(), "need", [], 1, routed )
    wide   = rt._candidate_receipt( stage_dict( expansion=EXPANSION, protected_head=64 ), None, Client(), "need", [], 1, routed )
    assert "expansion" not in plain and "protected_head" not in plain and wide[ "expansion" ] == EXPANSION and wide[ "protected_head" ] == 64
    assert { k: v for k, v in wide.items() if k not in ( "expansion", "protected_head" ) } == plain


def test_the_expansion_keyword_is_empty_for_a_block_without_one():
    assert rt._expansion_of( { "ids": [] } ) == {} and rt._expansion_of( { "expansion": EXPANSION } ) == { "expansion": EXPANSION }
    assert rt._expansion_of( { "expansion": EXPANSION, "protected_head": 64, "ids": [] } ) == { "expansion": EXPANSION, "protected_head": 64 }


class Recorder:
    """A stage client that records the keywords of each shortlist call."""

    arm, K = "B1", 128

    def __init__( self, ids=( "a", ) ): self.calls, self.ids = [], list( ids )

    def manifest( self ): return { "manifest_hash": "m" * 64 }

    def shortlist( self, *args, **kwargs ):
        self.calls.append( kwargs )
        return { "ids": sorted( self.ids ), "ranking": self.ids, "K": kwargs.get( "K", 128 ) }


def test_the_widening_asks_again_with_the_first_calls_expansion():
    stage  = { "ids": [ "a" ], "wiki_ids": [], "expansion": EXPANSION, "protected_head": 64 }
    client = Recorder()
    out    = rt._widen( types.SimpleNamespace( pages=[] ), client, stage, "routed", "need", [], [], [], set(), None, "text", "sha", None, "all" )
    assert out == ( "routed", stage, None )                                                # nothing extra to ask: the widening ends there
    assert client.calls[ 0 ][ "expansion" ] == EXPANSION and client.calls[ 0 ][ "protected_head" ] == 64


def test_the_widening_of_a_plain_lookup_passes_no_expansion_keyword_at_all():
    client = Recorder()
    rt._widen( types.SimpleNamespace( pages=[] ), client, { "ids": [ "a" ], "wiki_ids": [] }, "routed", "need", [], [], [], set(), None, "text", "sha", None, "all" )
    assert "expansion" not in client.calls[ 0 ] and "protected_head" not in client.calls[ 0 ]


def stored_receipt( **block ):
    cs = dict( { "arm": "B1", "K": 128, "manifest_hash": "m" * 64, "ranking_text": "need", "wiki_ids": [], "ids": [ "a" ] }, **block )
    return { "candidate_stage": cs, "index_sha": "sha", "pack_size": 10, "requests": [] }


def test_a_replay_gives_the_stage_the_recorded_expansion():
    client = Recorder()
    ids, wide = rt._frozen_candidate_ids( types.SimpleNamespace( candidate_stage=client ), stored_receipt( expansion=EXPANSION, protected_head=64 ), [ { "id": "a", "lang": "py" } ], None, "all" )
    assert ids == [ "a" ] and wide == [] and client.calls[ 0 ][ "expansion" ] == EXPANSION and client.calls[ 0 ][ "protected_head" ] == 64 and client.calls[ 0 ][ "cache_only" ] is True


def test_a_replay_of_a_plain_receipt_passes_no_expansion_keyword_at_all():
    client = Recorder()
    rt._frozen_candidate_ids( types.SimpleNamespace( candidate_stage=client ), stored_receipt(), [ { "id": "a", "lang": "py" } ], None, "all" )
    assert "expansion" not in client.calls[ 0 ] and "protected_head" not in client.calls[ 0 ]


# --- protecting the plain need: the protected head -------------------------------------------------------------------------------------------

TWO_B = [ { "need": "settings", "query_vectors": Q_B }, { "need": "load", "query_vectors": Q_B } ]


def shortlist_of( generation, **more ):
    return run_main( request_for( generation, K=1, fusion=ONE, vectors_dir="v", query_vectors=Q_A, **more ) )[ 1 ][ "shortlist" ]


def test_the_plain_needs_top_id_survives_expansion_lists_that_all_disagree( generation ):
    assert shortlist_of( generation, extra_queries=TWO_B ) == [ "py:b" ]                                      # six expansion lists outvote the plain three
    assert shortlist_of( generation, extra_queries=TWO_B, protect_head=1 ) == [ "py:a" ]                       # the plain need's own first id is kept


def test_a_protected_head_fills_the_rest_from_the_expanded_fusion_and_keeps_fused_order( generation ):
    request = request_for( generation, K=2, fusion=ONE, vectors_dir="v", query_vectors=Q_A, extra_queries=TWO_B, protect_head=1 )
    answer  = run_main( request )[ 1 ]
    assert answer[ "shortlist" ] == [ "py:a", "py:b" ] and set( answer[ "ranking" ] ) == { "py:a", "py:b" }
    assert answer[ "ranking" ][ 0 ] == "py:b"                                                              # still in the order of the fusion of all the lists


@pytest.mark.parametrize( "more", [ {}, { "protect_head": 0 }, { "protect_head": None }, { "protect_head": 5, "extra_queries": [] } ] )
def test_with_no_expansion_or_a_zero_head_the_answer_is_byte_for_byte_the_old_one( generation, more ):
    base = run_main( request_for( generation, vectors_dir="v", query_vectors=Q_A ) )[ 1 ]
    got  = run_main( request_for( generation, vectors_dir="v", query_vectors=Q_A, **more ) )[ 1 ]
    assert json.dumps( got, sort_keys=True ) == json.dumps( base, sort_keys=True )


def test_a_zero_protected_head_with_expansion_is_plain_expansion( generation ):
    assert shortlist_of( generation, extra_queries=TWO_B, protect_head=0 ) == shortlist_of( generation, extra_queries=TWO_B )


def test_a_protected_head_larger_than_k_is_cut_to_k( generation ):
    request = request_for( generation, K=1, fusion=ONE, vectors_dir="v", query_vectors=Q_A, extra_queries=TWO_B, protect_head=50 )
    assert run_main( request )[ 1 ][ "shortlist" ] == [ "py:a" ]


@pytest.mark.parametrize( "value", [ -1, "3", True, 2.5 ] )
def test_a_bad_protect_head_is_a_named_request_error( generation, value ):
    code, answer = run_main( request_for( generation, vectors_dir="v", query_vectors=Q_A, protect_head=value ) )
    assert code == 2 and "protect_head is not a non-negative integer" in answer[ "detail" ]


def test_the_protected_order_is_what_the_stage_returns_directly():
    from cosa.repo.symindex.candidates import candidate_stage as cstage
    stage = cstage.build_stage( SEARCH_ENTRIES, None, 60, 100, 0 )
    lists = { "vector_concat": [ "py:a", "py:b", "py:c" ], "x0_vector_concat": [ "py:b", "py:c", "py:a" ], "x1_vector_concat": [ "py:b", "py:c", "py:a" ] }
    plain = cstage.shortlist( "zzz", stage, 1, lists )
    held  = cstage.shortlist( "zzz", stage, 1, lists, { "head": 1, "skip": [ "x0_vector_concat", "x1_vector_concat" ] } )
    assert plain[ "shortlist" ] == [ "py:b" ] and held[ "shortlist" ] == [ "py:a" ]
    assert cstage.shortlist( "zzz", stage, 1, lists, { "head": 0, "skip": [] } ) == plain


# --- the protected head key ---------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize( "value, want", [ ( None, 64 ), ( "", 64 ), ( "  ", 64 ), ( "64", 64 ), ( " 96 ", 96 ), ( "0", 0 ), ( "1", 1 ) ] )
def test_the_protected_head_is_the_ini_value_or_64( value, want ):
    ini = FakeConfig( {} if value is None else { "reuse candidate need expansion protected head": value } )
    assert sp.need_expansion_protected_head( ini, {} ) == want


def test_the_protected_head_override_variable_wins_and_a_blank_one_is_ignored():
    ini = FakeConfig( { "reuse candidate need expansion protected head": "32" } )
    assert sp.need_expansion_protected_head( ini, { "LUPIN_REUSE_CANDIDATE_NEED_EXPANSION_PROTECTED_HEAD": "8" } ) == 8
    assert sp.need_expansion_protected_head( ini, { "LUPIN_REUSE_CANDIDATE_NEED_EXPANSION_PROTECTED_HEAD": " " } ) == 32


@pytest.mark.parametrize( "bad", [ "-1", "many", "6.5", "1e3" ] )
def test_a_protected_head_that_is_not_a_whole_number_is_a_named_error( bad ):
    with pytest.raises( CandidateError ) as e: sp.need_expansion_protected_head( FakeConfig( { "reuse candidate need expansion protected head": bad } ), {} )
    assert e.value.code == sp.PROTECTED_HEAD_INVALID and bad in e.value.detail


def test_the_protected_head_reads_os_environ_and_builds_the_config_when_none_is_given( monkeypatch ):
    monkeypatch.setenv( "LUPIN_REUSE_CANDIDATE_NEED_EXPANSION_PROTECTED_HEAD", "12" )
    assert sp.need_expansion_protected_head() == 12
    monkeypatch.delenv( "LUPIN_REUSE_CANDIDATE_NEED_EXPANSION_PROTECTED_HEAD" )
    monkeypatch.setattr( sp, "build_config", lambda: FakeConfig( { "reuse candidate need expansion protected head": "7" } ) )
    assert sp.need_expansion_protected_head() == 7


def test_the_shipped_ini_protects_64_and_the_splainer_describes_the_key():
    import pathlib, re
    ini = pathlib.Path( rt.__file__ ).resolve().parents[ 1 ] / "conf" / "lupin-app.ini"
    assert re.findall( r"^reuse candidate need expansion protected head\s*=\s*(\S+)\s*$", ini.read_text( encoding="utf-8" ), re.M ) == [ "64" ]
    assert re.search( r"^reuse candidate need expansion protected head\s*= How many", ini.with_name( "lupin-app-splainer.ini" ).read_text( encoding="utf-8" ), re.M )


# --- the client sends and records the protected head -----------------------------------------------------------------------------------------

def test_with_an_expansion_the_client_sends_its_protected_head_and_records_it( world ):
    make, bridge, *_ = world
    got = lookup( make( expander=lambda text: copy.deepcopy( EXPANSION ), protected_head=64 ), "profile" )
    assert bridge.seen[ -1 ][ 2 ][ "protect_head" ] == 64 and got[ "protected_head" ] == 64 and got[ "expansion" ] == EXPANSION


def test_without_an_expansion_or_with_a_zero_head_no_protect_head_is_sent( world ):
    make, bridge, *_ = world
    lookup( make( protected_head=64 ), "profile" )                                                       # no expander: nothing to protect against
    assert "protect_head" not in bridge.seen[ -1 ][ 2 ] and "extra_queries" not in bridge.seen[ -1 ][ 2 ]
    got = lookup( make( expander=lambda text: copy.deepcopy( EXPANSION ), protected_head=0 ), "profile" )
    assert "protect_head" not in bridge.seen[ -1 ][ 2 ] and "protected_head" not in got
    got = lookup( make( expander=lambda text: copy.deepcopy( EXPANSION ) ), "profile" )                  # no head given at all
    assert "protect_head" not in bridge.seen[ -1 ][ 2 ] and "protected_head" not in got


def test_a_recorded_protected_head_replaces_the_clients_own( world ):
    make, bridge, *_ = world
    lookup( make( expander=lambda text: copy.deepcopy( EXPANSION ), protected_head=64 ), "profile" )
    got = lookup( make( protected_head=2 ), "profile", cache_only=True, expansion=copy.deepcopy( EXPANSION ), protected_head=64 )
    assert bridge.seen[ -1 ][ 2 ][ "protect_head" ] == 64 and got[ "protected_head" ] == 64
