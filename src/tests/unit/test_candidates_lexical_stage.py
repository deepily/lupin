"""
Unit tests for identifier splitting, BM25, rank fusion and the candidate stage.

BM25 values are worked by hand from the formula on a three-document corpus.
Each rule has a case that fails when the rule is removed.
The rules are the id tie-break, the score rounding, the always-kept head, the depth cut and the replay.
"""
import json
import os
import subprocess
import sys

import pytest

from cosa.repo.symindex.candidates import bm25
from cosa.repo.symindex.candidates import candidate_stage as cs
from cosa.repo.symindex.candidates import rank_fusion as rf
from cosa.repo.symindex.candidates.errors import CandidateError
from cosa.repo.symindex.candidates.identifier_split import split_identifier


def doc( doc_id, name, **rest ):
    """A minimal index entry."""
    return dict( { "id": doc_id, "name": name }, **rest )


CORPUS = [ doc( "b", "alpha" ), doc( "a", "alpha beta" ), doc( "c", "gamma" ) ]


class TestSplitIdentifier:
    """Splitting on underscores, capitals, digits and path separators."""

    @pytest.mark.parametrize( "text,words", [
        ( "get_user_profile",              [ "get", "user", "profile" ] ),
        ( "getUserProfile",                [ "get", "user", "profile" ] ),
        ( "GetUserProfile",                [ "get", "user", "profile" ] ),
        ( "HTTPServer",                    [ "http", "server" ] ),
        ( "parseHTTP",                     [ "parse", "http" ] ),
        ( "utf8Decode",                    [ "utf", "8", "decode" ] ),
        ( "src/cosa/rest.py",              [ "src", "cosa", "rest", "py" ] ),
        ( "A.b::c",                        [ "a", "b", "c" ] ),
        ( "naïve_café",                    [ "na", "ïve", "caf", "é" ] ),
        ( "",                              [] ),
        ( "__init__",                      [ "init" ] ),
        ( "a_a",                           [ "a", "a" ] ),
    ] )
    def test_words( self, text, words ):
        assert split_identifier( text ) == words

    def test_paraphrase_meets_identifier( self ):
        assert split_identifier( "getUserProfile" ) == split_identifier( "Get user profile" )


class TestBm25:
    """The index against hand-computed scores."""

    def test_scores_match_hand_computation( self ):
        index = bm25.build_bm25( CORPUS, ( "name", ) )
        # idf( alpha ) = ln( 1 + ( 3 - 2 + 0.5 ) / ( 2 + 0.5 ) ) = 0.470004
        # norm = 1 + 1.2 * ( 0.25 + 0.75 * len / ( 4 / 3 ) ), len 1 -> 1.975, len 2 -> 2.65
        assert bm25.rank_scored( index, "alpha" ) == [ ( "b", 0.523548 ), ( "a", 0.390192 ) ]

    def test_unique_term_scores_higher( self ):
        index = bm25.build_bm25( CORPUS, ( "name", ) )
        assert bm25.rank_scored( index, "beta" ) == [ ( "a", 0.814273 ) ]

    def test_query_sums_terms( self ):
        index = bm25.build_bm25( CORPUS, ( "name", ) )
        assert bm25.rank_scored( index, "alpha beta" ) == [ ( "a", 1.204465 ), ( "b", 0.523548 ) ]

    def test_repeated_query_word_counts_once( self ):
        index = bm25.build_bm25( CORPUS, ( "name", ) )
        assert bm25.rank_scored( index, "alpha alpha ALPHA" ) == bm25.rank_scored( index, "alpha" )

    def test_unknown_word_and_empty_query_rank_nothing( self ):
        index = bm25.build_bm25( CORPUS, ( "name", ) )
        assert bm25.rank( index, "zeta" ) == []
        assert bm25.rank( index, "" ) == []

    def test_equal_scores_break_on_id( self ):
        entries = [ doc( "m", "alpha" ), doc( "k", "alpha" ), doc( "z", "alpha" ), doc( "a", "beta" ) ]
        index   = bm25.build_bm25( entries, ( "name", ) )
        assert bm25.rank( index, "alpha" ) == [ "k", "m", "z" ]

    def test_equal_scores_from_different_terms_break_on_id( self ):
        # z is met first through alpha and a through beta, so only the id key puts a first.
        index = bm25.build_bm25( [ doc( "z", "alpha" ), doc( "a", "beta" ) ], ( "name", ) )
        assert bm25.rank( index, "alpha beta" ) == [ "a", "z" ]

    def test_entry_order_does_not_matter( self ):
        forward  = bm25.build_bm25( CORPUS, ( "name", ) )
        backward = bm25.build_bm25( list( reversed( CORPUS ) ), ( "name", ) )
        assert bm25.rank_scored( forward, "alpha beta" ) == bm25.rank_scored( backward, "alpha beta" )

    def test_scores_round_before_the_sort( self ):
        # b is so small that the two lengths differ in the ninth decimal only.
        entries = [ doc( "z", "alpha" ), doc( "a", "alpha beta" ) ]
        index   = bm25.build_bm25( entries, ( "name", ) , b=1e-8 )
        raw     = {}
        for term in ( "alpha", ):
            for position, freq in index.postings[ term ]:
                norm = freq + index.k1 * ( 1 - index.b + index.b * index.lengths[ position ] / index.average )
                raw[ index.ids[ position ] ] = index.idf[ term ] * freq * ( index.k1 + 1 ) / norm
        assert raw[ "z" ] > raw[ "a" ]                       # the unrounded order is z first
        assert bm25.rank( index, "alpha" ) == [ "a", "z" ]   # the rounded tie goes to id order

    def test_fields_select_what_is_indexed( self ):
        entries = [ doc( "a", "x", doc="finds the profile" ), doc( "b", "profile" ) ]
        by_doc  = bm25.build_bm25( entries, ( "doc", ) )
        by_name = bm25.build_bm25( entries, ( "name", ) )
        assert bm25.rank( by_doc, "profile" ) == [ "a" ]
        assert bm25.rank( by_name, "profile" ) == [ "b" ]

    def test_missing_and_empty_fields_are_skipped( self ):
        index = bm25.build_bm25( [ { "id": "a" }, { "id": "b", "doc": "" }, { "id": "c", "doc": "word" } ], ( "doc", ) )
        assert bm25.rank( index, "word" ) == [ "c" ]

    def test_empty_corpus_ranks_nothing( self ):
        index = bm25.build_bm25( [], ( "name", ) )
        assert bm25.rank( index, "alpha" ) == []
        assert index.params()[ "documents" ] == 0

    def test_params_are_recorded( self ):
        index = bm25.build_bm25( CORPUS, ( "name", ), k1=1.5, b=0.5 )
        assert index.params() == { "fields": [ "name" ], "k1": 1.5, "b": 0.5, "score_digits": 6, "documents": 3 }

    def test_index_is_frozen( self ):
        index = bm25.build_bm25( CORPUS, ( "name", ) )
        with pytest.raises( AttributeError, match="frozen" ): index.k1 = 9.0


class TestFuse:
    """Rank fusion: positions only, ties on id, head always kept."""

    def test_reciprocal_rank_order( self ):
        # a: 1/61 + 1/62, b: 1/62 + 1/61, so a and b tie and c is third
        assert rf.fuse( [ [ "a", "b", "c" ], [ "b", "a", "d" ] ], k=60 ) == [ "a", "b", "c", "d" ]

    def test_ties_break_on_id( self ):
        assert rf.fuse( [ [ "m" ], [ "k" ] ], k=60 ) == [ "k", "m" ]

    def test_scores_round_before_the_sort( self ):
        # 1 / ( 10**9 + 1 ) and 1 / ( 10**9 + 2 ) differ at the 18th decimal and round to the same value.
        assert rf.fuse( [ [ "z", "a" ] ], k=10 ** 9 ) == [ "a", "z" ]

    def test_depth_cuts_each_list( self ):
        assert rf.fuse( [ [ "a", "b", "c" ] ], depth=2, head=1 ) == [ "a", "b" ]

    def test_limit_cuts_the_order( self ):
        assert rf.fuse( [ [ "a", "b", "c", "d" ] ], head=0, limit=2 ) == [ "a", "b" ]

    def test_head_of_every_list_survives_the_limit( self ):
        lists = [ [ "a", "b", "c" ], [ "a", "b", "z" ] ]
        assert rf.fuse( lists, head=0, limit=2 ) == [ "a", "b" ]
        assert rf.fuse( lists, head=3, limit=2 ) == [ "a", "b", "c", "z" ]

    def test_head_ids_stay_in_fused_order( self ):
        lists = [ [ "a", "b" ], [ "a", "b" ], [ "y", "x" ] ]
        assert rf.fuse( lists, head=2, limit=1 ) == [ "a", "b", "y", "x" ]

    def test_score_never_enters( self ):
        # a list of ids carries no score, so two lists that differ only in a hidden score fuse alike
        assert rf.fuse( [ [ "a", "b" ] ] ) == rf.fuse( [ [ "a", "b" ] ] )

    def test_no_lists( self ):
        assert rf.fuse( [] ) == []
        assert rf.fuse( [], limit=3 ) == []


ENTRIES = [
    { "id": "py:a", "file": "src/cosa/users/profile.py", "module": "cosa.users.profile", "name": "get_user_profile", "sig": "(user_id: int) -> Profile", "doc": "Return the profile of one user." },
    { "id": "py:b", "file": "src/cosa/users/other.py",   "module": "cosa.users.other",   "name": "load_settings",     "sig": "(path)",                   "doc": "Read the settings file." },
    { "id": "js:c", "file": "src/static/js/profile.js",  "module": "",                   "name": "renderProfileCard", "sig": "(profile)",                "doc": "Draw a user card." },
]


class TestStage:
    """The stage, its shortlist and the replay check."""

    def test_paraphrase_finds_the_identifier( self ):
        stage  = cs.build_stage( ENTRIES )
        result = cs.shortlist( "get user profile", stage, 2 )
        assert result[ "ranking" ][ 0 ] == "py:a"
        assert "py:b" not in result[ "shortlist" ]

    def test_shortlist_is_sorted_by_id_and_ranking_is_not( self ):
        stage  = cs.build_stage( ENTRIES )
        result = cs.shortlist( "user profile", stage, 3 )
        assert result[ "shortlist" ] == sorted( result[ "ranking" ] )
        assert result[ "ranking" ] != result[ "shortlist" ]

    def test_purpose_line_is_searched_when_present( self ):
        with_purpose = cs.build_stage( ENTRIES, purposes={ "py:b": "Parse configuration." } )
        without      = cs.build_stage( ENTRIES )
        assert "py:b" in cs.shortlist( "parse configuration", with_purpose, 3 )[ "lists" ][ "prose" ]
        assert cs.shortlist( "parse configuration", without, 3 )[ "lists" ][ "prose" ] == []

    def test_entries_are_not_changed( self ):
        before = json.dumps( ENTRIES, sort_keys=True )
        cs.build_stage( ENTRIES, purposes={ "py:b": "x" } )
        assert json.dumps( ENTRIES, sort_keys=True ) == before

    def test_extra_lists_are_fused_in_source_order_of_name( self ):
        stage  = cs.build_stage( ENTRIES )
        result = cs.shortlist( "zzz", stage, 3, extra_lists={ "wiki": [ "js:c" ], "cosine": [ "py:b", "js:c" ] } )
        assert list( result[ "lists" ] ) == [ "code", "cosine", "prose", "wiki" ]
        assert result[ "ranking" ] == [ "js:c", "py:b" ]

    def test_head_keeps_the_top_of_a_vector_list( self ):
        stage  = cs.build_stage( ENTRIES, head=1 )
        result = cs.shortlist( "get user profile", stage, 1, extra_lists={ "cosine": [ "py:b" ] } )
        assert "py:b" in result[ "shortlist" ]

    def test_manifest_records_parameters( self ):
        manifest = cs.build_stage( ENTRIES, k=30, depth=100, head=4 ).manifest()
        assert manifest[ "fusion" ] == { "k": 30, "depth": 100, "head": 4 }
        assert manifest[ "code" ][ "fields" ] == [ "id", "file", "module", "name", "sig" ]
        assert manifest[ "prose" ][ "fields" ] == [ "doc", "purpose" ]

    def test_stage_is_frozen( self ):
        with pytest.raises( AttributeError, match="frozen" ): cs.build_stage( ENTRIES ).ids = ()

    def test_replay_gives_the_same_bytes( self ):
        stage    = cs.build_stage( ENTRIES )
        recorded = cs.shortlist_bytes( cs.shortlist( "user profile", stage, 2 ) )
        first    = cs.replay( "user profile", stage, 2, recorded )
        assert first == cs.replay( "user profile", stage, 2, recorded )

    def test_replay_refuses_a_changed_shortlist( self ):
        stage    = cs.build_stage( ENTRIES )
        recorded = cs.shortlist_bytes( cs.shortlist( "user profile", stage, 2 ) )
        with pytest.raises( CandidateError ) as caught: cs.replay( "load settings", stage, 2, recorded )
        assert caught.value.code == cs.REPLAY_MISMATCH

    def test_replay_across_processes_with_different_hash_seeds( self ):
        script = ( "import json,sys\n"
                   "from cosa.repo.symindex.candidates import candidate_stage as cs\n"
                   "e = json.loads( sys.argv[ 1 ] )\n"
                   "sys.stdout.buffer.write( cs.shortlist_bytes( cs.shortlist( 'user profile card', cs.build_stage( e ), 3 ) ) )\n" )
        outputs = []
        for seed in ( "0", "1", "12345" ):
            env = dict( os.environ, PYTHONHASHSEED=seed )
            outputs.append( subprocess.run( [ sys.executable, "-c", script, json.dumps( ENTRIES ) ], capture_output=True, env=env, check=True ).stdout )
        assert outputs[ 0 ] == outputs[ 1 ] == outputs[ 2 ]
        assert outputs[ 0 ] == cs.shortlist_bytes( cs.shortlist( "user profile card", cs.build_stage( ENTRIES ), 3 ) )
