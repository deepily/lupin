"""Unit tests for semdup.candidates: the three lists, the pool rules and the fusion."""
import random

import numpy as np
import pytest

from cosa.repo.semdup import candidates as cd
from cosa.repo.semdup import config as cf

VOCAB = [ "red", "green", "blue", "cyan", "pink", "gold" ]
CFG   = { "list_depth": cf.LIST_DEPTH, "max_candidates": cf.MAX_CANDIDATES, "min_candidates": cf.MIN_CANDIDATES, "fusion_head": cf.FUSION_HEAD }

# ( id, name, file, text, origin, lang ): the texts use only the six colour words, so a vector is the word count of each colour.
POOL = [
    ( "d01", "alpha",   "f01.py", "red red green",       "new",    "py" ),
    ( "d02", "bravo",   "f02.py", "red green green",     "server", "py" ),
    ( "d03", "charlie", "f03.py", "blue cyan",           "new",    "py" ),
    ( "d04", "charlie", "f03.py", "blue blue cyan pink", "new",    "py" ),            # a redefinition of d03: same file, same name
    ( "d05", "echo",    "f05.py", "pink gold",           "server", "py" ),
    ( "d06", "foxtrot", "f06.py", "gold gold red",       "server", "py" ),
    ( "d07", "golf",    "f07.ts", "green",               "server", "ts" ),
    ( "d08", "hotel",   "f08.py", "cyan pink gold",      "server", "py" ),
    ( "d09", "india",   "f09.ts", "red blue",            "new",    "ts" ),
    ( "d10", "juliet",  "f10.py", "green green gold",    "server", "py" ),
    ( "d11", "kilo",    "f11.py", "cyan cyan",           "server", "py" ),
    ( "d12", "lima",    "f12.py", "blue pink",           "server", "py" ),
]


def vector( text ):
    """Embed a text as the count of each colour word in it."""
    return [ float( text.split().count( w ) ) for w in VOCAB ]


def make_defs( rows=POOL ):
    """Build definition records from the table."""
    return [ { "id": i, "name": n, "file": f, "text": t, "sig": "", "origin": o, "lang": l, "nodes": 30 } for i, n, f, t, o, l in rows ]


def make_pool( rows=POOL ):
    defs = make_defs( rows )
    return defs, cd.build_pool( defs, { d[ "id" ]: vector( d[ "text" ] ) for d in defs } )


# ---- the pool -----------------------------------------------------------------------------------------------------

def test_the_pool_is_ordered_by_id_whatever_order_the_definitions_arrive_in_and_rows_have_unit_length():
    defs, pool = make_pool()
    shuffled   = list( defs )
    random.Random( 3 ).shuffle( shuffled )
    again      = cd.build_pool( shuffled, { d[ "id" ]: vector( d[ "text" ] ) for d in defs } )
    assert [ d[ "id" ] for d in pool[ "defs" ] ] == [ d[ "id" ] for d in again[ "defs" ] ] == [ f"d{i:02d}" for i in range( 1, 13 ) ]
    assert np.array_equal( pool[ "matrix" ], again[ "matrix" ] )
    assert np.allclose( np.linalg.norm( pool[ "matrix" ], axis=1 ), 1.0 ) and pool[ "position" ][ "d05" ] == 4


def test_a_zero_vector_stays_zero_and_scores_nothing_against_anyone():
    defs = make_defs( [ POOL[ 0 ], ( "d13", "mike", "f13.py", "plain words", "new", "py" ) ] )
    pool = cd.build_pool( defs, { "d01": vector( "red" ), "d13": [ 0.0 ] * 6 } )
    assert not np.isnan( pool[ "matrix" ] ).any() and cd.embedding_list( defs[ 1 ], pool, 5 ) == [ "d01" ]
    assert cd.embedding_list( defs[ 0 ], pool, 5 ) == [ "d13" ]


def test_a_definition_without_a_vector_is_a_key_error():
    with pytest.raises( KeyError ):
        cd.build_pool( make_defs(), { "d01": vector( "red" ) } )


def test_a_definition_and_its_redefinition_are_the_same_slot_but_a_namesake_in_another_file_is_not():
    a, b = make_defs()[ 2 ], make_defs()[ 3 ]
    assert cd.same_slot( a, b ) and cd.same_slot( a, a )
    assert not cd.same_slot( a, { **b, "file": "other.py" } ) and not cd.same_slot( a, { **b, "name": "other" } )


# ---- the embedding list -------------------------------------------------------------------------------------------

def test_the_embedding_list_is_the_nearest_by_cosine_with_ties_going_to_the_smaller_id():
    defs, pool = make_pool()
    # d01 = ( red 2, green 1 ). By hand: d02 4/5 = .8, d09 2/sqrt( 10 ) = .632, d07 1/sqrt( 5 ) = .447, d06 and d10 2/5 = .4 (a tie), the rest share nothing.
    assert cd.embedding_list( defs[ 0 ], pool, 5 ) == [ "d02", "d09", "d07", "d06", "d10" ]


def test_the_embedding_list_never_holds_the_definition_itself_or_its_redefinition_and_may_cross_languages():
    defs, pool = make_pool()
    d03 = defs[ 2 ]
    got = cd.embedding_list( d03, pool, 11 )
    assert "d03" not in got and "d04" not in got and len( got ) == 10
    assert "d09" in cd.embedding_list( defs[ 0 ], pool, 5 ) and defs[ 8 ][ "lang" ] == "ts"            # a ts definition is a candidate of a py one


def test_the_embedding_list_is_cut_at_the_depth_and_does_not_depend_on_input_order():
    defs, pool = make_pool()
    shuffled   = list( defs )
    random.Random( 9 ).shuffle( shuffled )
    again      = cd.build_pool( shuffled, { d[ "id" ]: vector( d[ "text" ] ) for d in defs } )
    assert cd.embedding_list( defs[ 0 ], pool, 2 ) == [ "d02", "d09" ]
    assert cd.embedding_list( defs[ 0 ], again, 5 ) == cd.embedding_list( defs[ 0 ], pool, 5 )


def test_a_definition_outside_the_pool_is_a_key_error():
    defs, pool = make_pool()
    with pytest.raises( KeyError ):
        cd.embedding_list( { **defs[ 0 ], "id": "d99" }, pool, 5 )


# ---- the word list ------------------------------------------------------------------------------------------------

def test_the_word_list_ranks_by_shared_words_and_skips_the_definition_and_its_redefinition():
    defs, pool = make_pool()
    index = cd.word_index( pool )
    assert index.ids == tuple( f"d{i:02d}" for i in range( 1, 13 ) ) and index.fields == cd.WORD_FIELDS
    # d01 is "red red green". By BM25 the pinned order is d02 (both words), d10 and d07 (the rarer word, green), then d09 and d06 (red only); d01 itself is skipped.
    assert cd.word_list( defs[ 0 ], pool, index, 10 ) == [ "d02", "d10", "d07", "d09", "d06" ]
    # d03 and d04 are one slot: d04 outscores everything for d03 and is still left out; d09 and d12 tie on "blue" and go by id.
    assert cd.word_list( defs[ 2 ], pool, index, 10 ) == [ "d11", "d09", "d12", "d08" ]
    assert cd.word_list( defs[ 0 ], pool, index, 2 ) == [ "d02", "d10" ]


def test_the_word_list_is_empty_when_nothing_shares_a_word():
    defs = make_defs( [ POOL[ 0 ], ( "d13", "mike", "f13.py", "plain words", "new", "py" ) ] )
    pool = cd.build_pool( defs, { d[ "id" ]: vector( d[ "text" ] ) for d in defs } )
    assert cd.word_list( defs[ 1 ], pool, cd.word_index( pool ), 5 ) == []


# ---- the structural list ------------------------------------------------------------------------------------------

def test_partner_map_keeps_the_pair_order_and_each_partner_once():
    pairs = [ { "ids": [ "d01", "d02" ], "size": 90 }, { "ids": [ "d01", "d05" ], "size": 80 }, { "ids": [ "d02", "d01" ], "size": 10 }, { "ids": [ "d05", "d06" ], "size": 5 } ]
    assert cd.partner_map( pairs ) == { "d01": [ "d02", "d05" ], "d02": [ "d01" ], "d05": [ "d01", "d06" ], "d06": [ "d05" ] }
    assert cd.partner_map( [] ) == {}


def test_the_structural_list_is_the_clone_partners_in_order_cut_at_the_depth_without_redefinitions():
    defs, pool = make_pool()
    partners = { "d03": [ "d04", "d08", "d12", "d05" ], "d01": [] }
    assert cd.structural_list( defs[ 2 ], pool, partners, 10 ) == [ "d08", "d12", "d05" ]            # d04 is a redefinition of d03
    assert cd.structural_list( defs[ 2 ], pool, partners, 2 ) == [ "d08", "d12" ]
    assert cd.structural_list( defs[ 0 ], pool, partners, 10 ) == [] and cd.structural_list( defs[ 5 ], pool, partners, 10 ) == []


# ---- fusion -------------------------------------------------------------------------------------------------------

def ids( n, prefix="c" ):
    return [ f"{prefix}{i:02d}" for i in range( 1, n + 1 ) ]


def test_every_list_keeps_its_top_two_even_when_the_fusion_would_drop_them():
    defs, _ = make_pool()
    shared  = ids( 10 )
    lists   = { "embedding": shared, "words": shared, "structural": [ "z01", "z02" ] }
    row     = cd.candidates_for( defs[ 0 ], None, lists, CFG )
    got     = [ c[ "id" ] for c in row[ "candidates" ] ]
    assert len( got ) == 10 and "z01" in got and "z02" in got                                    # without the head rule only the shared ids would fit
    assert got[ -1 ] != "c10" and "c10" not in got and "c09" not in got


def test_a_candidate_names_the_lists_that_held_it_and_ranks_run_from_one_in_fused_order():
    defs, _ = make_pool()
    lists   = { "embedding": [ "a", "b", "c" ], "words": [ "b", "a" ], "structural": [ "c" ] }
    row     = cd.candidates_for( defs[ 0 ], None, lists, CFG )
    by_id   = { c[ "id" ]: c for c in row[ "candidates" ] }
    assert by_id[ "a" ][ "from" ] == [ "embedding", "words" ] and by_id[ "b" ][ "from" ] == [ "embedding", "words" ] and by_id[ "c" ][ "from" ] == [ "embedding", "structural" ]
    assert [ c[ "rank" ] for c in row[ "candidates" ] ] == [ 1, 2, 3 ] and row[ "id" ] == "d01"
    assert [ c[ "id" ] for c in row[ "candidates" ] ] == [ "a", "b", "c" ]                      # a and b tie on fused score and a is the smaller id


def test_at_most_ten_candidates_are_kept_and_short_means_fewer_than_five():
    defs, _ = make_pool()
    full  = cd.candidates_for( defs[ 0 ], None, { "embedding": ids( 10 ), "words": ids( 10, "w" ), "structural": ids( 10, "s" ) }, CFG )
    assert len( full[ "candidates" ] ) == 10 and full[ "short" ] is False
    four  = cd.candidates_for( defs[ 0 ], None, { "embedding": ids( 4 ), "words": [], "structural": [] }, CFG )
    five  = cd.candidates_for( defs[ 0 ], None, { "embedding": ids( 5 ), "words": [], "structural": [] }, CFG )
    assert four[ "short" ] is True and five[ "short" ] is False


def test_the_frozen_list_depth_governs_the_fusion_and_the_from_flags():
    defs, _ = make_pool()
    lists = { "embedding": ids( 6 ), "words": [], "structural": [] }
    row   = cd.candidates_for( defs[ 0 ], None, lists, { **CFG, "list_depth": 3, "max_candidates": 10 } )
    assert [ c[ "id" ] for c in row[ "candidates" ] ] == [ "c01", "c02", "c03" ]                  # depth 3: the rest are not read


def test_candidate_rows_build_one_row_per_new_definition_from_the_three_lists():
    defs, pool = make_pool()
    index    = cd.word_index( pool )
    partners = { "d01": [ "d12" ] }
    new      = [ d for d in defs if d[ "origin" ] == "new" ]
    rows     = cd.candidate_rows( new, pool, index, partners, CFG )
    assert [ r[ "id" ] for r in rows ] == [ "d01", "d03", "d04", "d09" ]
    d01 = rows[ 0 ]
    got = { c[ "id" ]: c[ "from" ] for c in d01[ "candidates" ] }
    assert "structural" in got[ "d12" ] and got[ "d02" ][ 0 ] == "embedding" and "d01" not in got
    assert all( r[ "short" ] is False for r in rows ) and [ r[ "outside_pool" ] for r in rows ] == [ 0, 0, 0, 0 ]


def test_a_clone_partner_outside_the_pool_is_passed_over_and_counted_instead_of_crashing():
    defs, pool = make_pool()
    partners   = { "d01": [ "x-gone", "d12", "x-also-gone", "d05" ] }
    assert cd.structural_list( defs[ 0 ], pool, partners, 10 ) == [ "d12", "d05" ]
    assert cd.structural_list( defs[ 0 ], pool, partners, 1 ) == [ "d12" ]
    assert cd.outside_pool( defs[ 0 ], pool, partners ) == 2 and cd.outside_pool( defs[ 1 ], pool, partners ) == 0
    row = cd.candidate_rows( [ defs[ 0 ] ], pool, cd.word_index( pool ), partners, CFG )[ 0 ]
    assert row[ "outside_pool" ] == 2 and "structural" in dict( ( c[ "id" ], c[ "from" ] ) for c in row[ "candidates" ] )[ "d12" ]
    assert all( not c[ "id" ].startswith( "x-" ) for c in row[ "candidates" ] )


def test_a_server_definition_cannot_be_given_a_candidate_row():
    defs, pool = make_pool()
    with pytest.raises( ValueError, match="d02 has origin 'server'" ):
        cd.candidate_rows( [ defs[ 1 ] ], pool, cd.word_index( pool ), {}, CFG )


def test_a_new_definition_that_is_not_in_the_pool_is_refused_by_name():
    defs, pool = make_pool()
    with pytest.raises( ValueError, match="d99 is not in the pool" ):
        cd.candidate_rows( [ { **defs[ 0 ], "id": "d99" } ], pool, cd.word_index( pool ), {}, CFG )
