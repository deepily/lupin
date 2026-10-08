"""
Choosing the probe entry and composing the six probe packs.

Rule: María's, with Cheech's ruling on near neighbours. The probe is the clean single-run entry
whose overlap is nearest 0.5 inside 0.35 to 0.65. Neighbours are drawn at random with a recorded seed,
or by word similarity to the probe's text.
Nothing here reaches Jev.
"""
import json

import pytest

from lupin_mcp import reuse_ledger as rl
from lupin_mcp import reuse_stage1 as st
from lupin_mcp import reuse_stage1_probe as sp
from lupin_mcp import reuse_tools as rt


def probs( overlap ):
    """A Choice answer whose reuse plus extend is `overlap`."""
    return { "reuse": overlap / 2, "extend": overlap / 2, "unrelated": 1 - overlap }


def single1( overlaps, failed=(), unasked=(), not_reached=() ):
    """A single-run results record whose answers hold the given overlaps."""
    return { "format": "stage1-arm-1", "arm": "single1", "question": 1,
             "answers": [ { "id": i, "probabilities": probs( o ) } for i, o in overlaps.items() ],
             "failed": list( failed ), "unasked": list( unasked ), "not_reached": list( not_reached ) }


def catalogue( n, doc="Does a thing." ): return [ { "id": f"e{i:02d}", "sig": "()", "doc": doc } for i in range( n ) ]


def test_overlap_is_reuse_plus_extend():
    assert sp.overlap_of( { "reuse": 0.25, "extend": 0.5, "unrelated": 0.25 } ) == 0.75


def test_the_band_and_target_and_pack_are_the_plans():
    assert sp.BAND == ( 0.35, 0.65 ) and sp.TARGET == 0.5 and sp.PACK_SIZE == 200 and sp.NEIGHBOURS == 199
    assert sp.POSITIONS == { "first": 0, "middle": 100, "last": 199 }


def test_the_probe_is_the_entry_nearest_one_half_inside_the_band():
    record = single1( { "a": 0.9, "b": 0.40, "c": 0.52, "d": 0.62, "e": 0.1 } )
    assert sp.choose_probe( record ) == "c"


def test_a_tie_goes_to_the_lowest_id():
    assert sp.choose_probe( single1( { "z": 0.45, "m": 0.55, "b": 0.55 } ) ) == "b"


def test_the_band_edges_are_inside_and_just_beyond_them_is_out():
    assert sp.choose_probe( single1( { "low": 0.35 } ) ) == "low" and sp.choose_probe( single1( { "high": 0.65 } ) ) == "high"
    with pytest.raises( sp.ProbeNotFound, match="0.35" ): sp.choose_probe( single1( { "a": 0.3499, "b": 0.6501 } ) )


def test_an_entry_the_run_did_not_cleanly_answer_is_never_the_probe():
    record = single1( { "bad": 0.5, "ok": 0.6 }, failed=[ "bad" ] )
    assert sp.choose_probe( record ) == "ok"
    assert sp.choose_probe( single1( { "bad": 0.5, "ok": 0.6 }, unasked=[ "bad" ] ) ) == "ok"
    assert sp.choose_probe( single1( { "bad": 0.5, "ok": 0.6 }, not_reached=[ "bad" ] ) ) == "ok"


def test_with_no_boundary_entry_there_is_no_probe_and_the_error_says_so():
    with pytest.raises( sp.ProbeNotFound ) as caught: sp.choose_probe( single1( {} ) )
    assert isinstance( caught.value, ValueError )


@pytest.mark.parametrize( "bad", [ { "arm": "single2" }, { "format": "other" }, { "arm": "pack10" } ] )
def test_only_a_single_run_one_record_can_choose_a_probe( bad ):
    with pytest.raises( ValueError, match="single1" ): sp.choose_probe( { **single1( { "a": 0.5 } ), **bad } )


def test_random_neighbours_come_from_the_id_sorted_others_with_the_given_seed():
    entries = catalogue( 20 )
    assert sp.random_neighbours( entries, "e03", 7, count=5 ) == [ "e11", "e05", "e13", "e01", "e16" ]
    assert sp.random_neighbours( entries, "e03", 8, count=5 ) == [ "e08", "e12", "e13", "e05", "e04" ]


def test_random_neighbours_never_hold_the_probe_or_a_repeat_whatever_the_input_order():
    entries = catalogue( 30 )
    got = sp.random_neighbours( list( reversed( entries ) ), "e10", 3, count=20 )
    assert "e10" not in got and len( set( got ) ) == 20
    assert got == sp.random_neighbours( entries, "e10", 3, count=20 )


def test_the_default_is_one_hundred_ninety_nine_neighbours():
    got = sp.random_neighbours( catalogue( 250 ), "e10", 1 )
    assert len( got ) == 199 == sp.NEIGHBOURS


def test_too_few_entries_for_a_pack_is_refused():
    with pytest.raises( ValueError, match="neighbours" ): sp.random_neighbours( catalogue( 150 ), "e10", 1 )
    with pytest.raises( ValueError, match="neighbours" ): sp.similar_neighbours( catalogue( 150 ), "e10" )


@pytest.mark.parametrize( "seed", [ "7", 7.0, True, None ] )
def test_the_seed_is_a_whole_number_so_it_can_be_recorded_and_repeated( seed ):
    with pytest.raises( ValueError, match="seed" ): sp.random_neighbours( catalogue( 250 ), "e10", seed )


def test_the_probe_must_be_in_the_catalogue():
    with pytest.raises( ValueError, match="not in the catalogue" ): sp.random_neighbours( catalogue( 250 ), "nope", 1 )
    with pytest.raises( ValueError, match="not in the catalogue" ): sp.similar_neighbours( catalogue( 250 ), "nope" )


def test_a_catalogue_with_a_repeated_id_is_refused():
    with pytest.raises( ValueError, match="repeated" ): sp.random_neighbours( catalogue( 250 ) + [ catalogue( 1 )[ 0 ] ], "e10", 1 )


def test_similar_neighbours_are_ranked_by_word_token_jaccard_then_lowest_id():
    probe  = { "id": "p.feed", "sig": "()", "doc": "parse rss feed articles" }
    others = [ { "id": "z.same", "sig": "()", "doc": "parse rss feed articles" },        # same words as the probe's text apart from its id
               { "id": "a.same", "sig": "()", "doc": "parse rss feed articles" },        # ties with z.same on score: a first
               { "id": "m.half", "sig": "()", "doc": "parse rss" },
               { "id": "n.none", "sig": "()", "doc": "unrelated thing entirely" } ]
    got = sp.similar_neighbours( [ probe ] + others, "p.feed", count=3 )
    assert got == [ "a.same", "z.same", "m.half" ] and "p.feed" not in got


def test_jaccard_is_over_the_sets_of_lower_case_alphanumeric_words_of_the_entry_text():
    assert sp.jaccard( "Parse RSS, feed!", "parse rss" ) == pytest.approx( 2 / 3 )
    assert sp.jaccard( "a b", "c d" ) == 0 and sp.jaccard( "", "" ) == 0


def test_the_six_probe_packs_hold_the_probe_at_the_first_middle_and_last_place_with_fixed_neighbours():
    entries = catalogue( 260 )
    plan = sp.build_probe_plan( entries, single1( { "e07": 0.5, "e08": 0.9 } ), 11 )
    assert sorted( plan[ "arms" ] ) == sorted( [ f"probe-{place}-{near}" for place in ( "first", "middle", "last" ) for near in ( "random", "near" ) ] )
    for near in ( "random", "near" ):
        ids = { place: [ e[ "id" ] for e in plan[ "arms" ][ f"probe-{place}-{near}" ][ "entries" ] ] for place in sp.POSITIONS }
        assert all( len( v ) == 200 and len( set( v ) ) == 200 for v in ids.values() )
        assert ids[ "first" ][ 0 ] == ids[ "middle" ][ 100 ] == ids[ "last" ][ 199 ] == "e07"
        rest = { place: [ i for i in v if i != "e07" ] for place, v in ids.items() }
        assert rest[ "first" ] == rest[ "middle" ] == rest[ "last" ]


def test_each_arms_probe_record_is_what_the_driver_checks():
    plan = sp.build_probe_plan( catalogue( 260 ), single1( { "e07": 0.5 } ), 11 )
    for arm, body in plan[ "arms" ].items():
        st._check_probe( arm, body[ "probe" ], body[ "entries" ] )
        assert body[ "probe" ][ "id" ] == "e07"
    assert plan[ "arms" ][ "probe-last-near" ][ "probe" ] == { "id": "e07", "placement": "last", "neighbours": "near_duplicate" }
    assert plan[ "arms" ][ "probe-first-random" ][ "probe" ][ "neighbours" ] == "random"


def test_the_plan_records_the_seed_both_neighbour_lists_the_probe_and_the_rule():
    plan = sp.build_probe_plan( catalogue( 260 ), single1( { "e07": 0.52, "e08": 0.9 } ), 11 )[ "plan" ]
    assert plan[ "seed" ] == 11 and plan[ "probe_id" ] == "e07" and plan[ "probe_overlap" ] == pytest.approx( 0.52 )
    assert plan[ "band" ] == [ 0.35, 0.65 ] and plan[ "target" ] == 0.5 and plan[ "neighbour_rule" ] == sp.NEIGHBOUR_RULE == "jaccard-word-tokens-v1"
    assert len( plan[ "random_ids" ] ) == len( plan[ "near_ids" ] ) == 199 and plan[ "question" ] == 1
    assert plan[ "random_ids" ] == sp.random_neighbours( catalogue( 260 ), "e07", 11 ) and plan[ "near_ids" ] == sp.similar_neighbours( catalogue( 260 ), "e07" )
    json.dumps( plan )


def test_the_plan_is_written_once_beside_the_results_and_never_replaced( tmp_path ):
    env  = st.Stage1Env( tmp_path, tmp_path / "data", rl.AccountLedger.create( tmp_path / "ledger.jsonl", rl.ACCOUNT_LIMIT_TOKENS, "t", "t" ) )
    plan = sp.build_probe_plan( catalogue( 260 ), single1( { "e07": 0.5 } ), 11 )
    path = sp.write_probe_plan( env, plan )
    assert path == env.results_dir / "s1-q1-probe-plan.json" and json.loads( path.read_text() ) == plan[ "plan" ]
    first = path.read_bytes()
    with pytest.raises( FileExistsError ): sp.write_probe_plan( env, sp.build_probe_plan( catalogue( 260 ), single1( { "e07": 0.5 } ), 12 ) )
    assert path.read_bytes() == first and not list( env.results_dir.glob( "*.tmp" ) )


def test_the_probe_arms_run_through_the_driver_unchanged( tmp_path ):
    """The packs are what run_arm expects: a probe in its place, a pack of 200."""
    plan = sp.build_probe_plan( catalogue( 260 ), single1( { "e07": 0.5 } ), 11 )
    assert all( st.ARMS[ arm ][ 1 ] == len( body[ "entries" ] ) for arm, body in plan[ "arms" ].items() )
    assert all( rt.entry_text( e ) for body in plan[ "arms" ].values() for e in body[ "entries" ] )


def test_each_kind_of_pack_holds_its_own_neighbour_list_in_order():
    built = sp.build_probe_plan( catalogue( 260 ), single1( { "e07": 0.5 } ), 11 )
    for near, listed in ( ( "random", built[ "plan" ][ "random_ids" ] ), ( "near", built[ "plan" ][ "near_ids" ] ) ):
        for place in sp.POSITIONS:
            ids = [ e[ "id" ] for e in built[ "arms" ][ f"probe-{place}-{near}" ][ "entries" ] ]
            assert [ i for i in ids if i != "e07" ] == listed
    assert built[ "plan" ][ "random_ids" ] != built[ "plan" ][ "near_ids" ]
