"""
Unit tests for the arm wiring of the offline comparison.

Every case is hand-built on a six-entry index. Each rule has a case that fails when the rule is removed.
The purpose lines reach only the second arm and later, each arm fuses its own lists, and a reserved need is refused.
"""
import numpy as np
import pytest

from cosa.repo.symindex.candidates import arm_metrics as am
from cosa.repo.symindex.candidates import arms
from cosa.repo.symindex.candidates.errors import CandidateError


def entry( doc_id, name, doc="", pin=None ):
    """A minimal index entry."""
    return { "id": doc_id, "name": name, "doc": doc, "pin": pin or f"pin-{doc_id}", "file": f"src/{doc_id}.py", "sig": "()" }


ENTRIES  = [ entry( "a", "parse_config", "Read a config file" ), entry( "b", "load_settings", "Load settings from disk" ),
             entry( "c", "render_page", "Render a page" ), entry( "d", "send_mail", "Send a mail" ),
             entry( "e", "zip_files", "Pack files" ), entry( "x", "helper", "" ) ]
PURPOSES = { "pin-x": "zebra striping for tables" }
IDS      = sorted( e[ "id" ] for e in ENTRIES )


@pytest.fixture
def stages():
    return arms.build_arm_stages( ENTRIES, PURPOSES )


class TestArmLists:
    """Each arm fuses the lists it names."""

    AVAILABLE = { "vector_concat": [ "c", "a" ], "vector_prose": [ "b", "a" ], "vector_code": [ "d", "e" ], "wiki": [ "e" ] }

    @pytest.mark.parametrize( "arm,names", [
        ( "C0",  [] ),
        ( "C1",  [] ),
        ( "B1",  [ "vector_concat" ] ),
        ( "B2",  [ "vector_code", "vector_prose" ] ),
        ( "B2w", [ "vector_code", "vector_prose", "wiki" ] ),
    ] )
    def test_sources( self, arm, names ):
        assert sorted( arms.lists_for_arm( arm, self.AVAILABLE ) ) == names

    def test_lists_are_copied( self ):
        picked = arms.lists_for_arm( "B1", self.AVAILABLE )
        picked[ "vector_concat" ].append( "zzz" )
        assert self.AVAILABLE[ "vector_concat" ] == [ "c", "a" ]

    def test_missing_source_is_named( self ):
        with pytest.raises( CandidateError ) as caught:
            arms.lists_for_arm( "B2w", { "vector_prose": [], "vector_code": [] } )
        assert caught.value.code == arms.ARM_LIST_MISSING
        assert "wiki" in caught.value.detail

    def test_unknown_arm( self ):
        with pytest.raises( CandidateError ) as caught:
            arms.lists_for_arm( "B3", {} )
        assert caught.value.code == arms.ARM_UNKNOWN


class TestRunArm:
    """The stage and the lists reach the shortlist."""

    def test_purpose_lines_reach_c1_and_not_c0( self, stages ):
        c0 = arms.run_arm( "C0", "zebra", stages, {}, 5 )
        c1 = arms.run_arm( "C1", "zebra", stages, {}, 5 )
        assert c0[ "ranking" ] == []
        assert c1[ "ranking" ] == [ "x" ]

    def test_vector_list_moves_the_ranking( self, stages ):
        plain   = arms.run_arm( "C1", "config", stages, {}, 5 )[ "ranking" ]
        with_v  = arms.run_arm( "B1", "config", stages, { "vector_concat": [ "e", "a" ] }, 5 )[ "ranking" ]
        assert plain == [ "a" ]
        assert with_v == [ "a", "e" ]

    def test_wiki_only_in_b2w( self, stages ):
        available = { "vector_prose": [ "b" ], "vector_code": [ "b" ], "wiki": [ "e" ] }
        assert "e" not in arms.run_arm( "B2", "config", stages, available, 5 )[ "ranking" ]
        assert "e" in arms.run_arm( "B2w", "config", stages, available, 5 )[ "ranking" ]

    def test_shortlist_is_sorted_by_id( self, stages ):
        result = arms.run_arm( "B1", "config", stages, { "vector_concat": [ "e", "d", "a" ] }, 5 )
        assert result[ "shortlist" ] == sorted( result[ "shortlist" ] )


class TestPositiveControl:
    """An arm that returns the full-sweep order must score 1.0."""

    def test_full_order_gives_full_recall( self, stages ):
        reference = [ "a", "c", "e" ]
        available = { "vector_concat": reference + [ "b", "d", "x" ] }
        ranking   = arms.full_ranking( "B1", "unmatched words", stages, available )
        assert set( ranking ) == set( IDS )
        for k in ( 6, 10 ):
            shortlist = arms.run_arm( "B1", "unmatched words", stages, available, k )[ "shortlist" ]
            assert am.recall_at_k( shortlist, reference ) == 1.0

    def test_a_cut_below_the_reference_loses_recall( self, stages ):
        reference = [ "a", "c", "e" ]
        available = { "vector_concat": [ "b", "d", "x" ] + reference }
        shortlist = arms.run_arm( "B1", "unmatched words", stages, available, 3 )[ "shortlist" ]
        assert am.recall_at_k( shortlist, reference ) < 1.0


class TestFullRanking:
    """The whole order, uncut."""

    def test_reaches_every_entry_in_a_list( self, stages ):
        available = { "vector_concat": [ "x", "e", "d", "c", "b", "a" ] }
        assert arms.full_ranking( "B1", "zzz", stages, available ) == [ "x", "e", "d", "c", "b", "a" ]

    def test_an_entry_in_no_list_is_absent( self, stages ):
        assert arms.full_ranking( "C0", "config", stages, {} ) == [ "a" ]


class TestCosineSources:
    """Matrices to ranked id lists under the names the search process uses."""

    def test_names_and_order( self ):
        ids      = [ "a", "b", "c" ]
        matrices = { "prose": np.array( [ [ 1, 0 ], [ 0, 1 ], [ 1, 1 ] ], dtype=np.float32 ),
                     "code":  np.array( [ [ 0, 1 ], [ 1, 0 ], [ 1, 1 ] ], dtype=np.float32 ) }
        got      = arms.cosine_sources( ids, matrices, { "prose": [ 1.0, 0.0 ], "code": [ 1.0, 0.0 ] } )
        assert got == { "vector_code": [ "b", "c", "a" ], "vector_prose": [ "a", "c", "b" ] }

    def test_only_matrices_with_a_query_are_ranked( self ):
        ids      = [ "a", "b" ]
        matrices = { "prose": np.eye( 2, dtype=np.float32 ), "code": np.eye( 2, dtype=np.float32 ) }
        assert list( arms.cosine_sources( ids, matrices, { "prose": [ 0.0, 1.0 ] } ) ) == [ "vector_prose" ]


class TestRefuseFresh:
    """The reserved needs are never opened."""

    def test_prefix_is_refused( self ):
        with pytest.raises( CandidateError ) as caught:
            arms.refuse_fresh_needs( [ "f01", "fresh-07", "fresh-02" ] )
        assert caught.value.code == arms.FRESH_NEEDS_REFUSED
        assert caught.value.detail == "fresh-02, fresh-07"

    def test_explicit_ids_are_refused( self ):
        with pytest.raises( CandidateError ):
            arms.refuse_fresh_needs( [ "f01", "n9" ], fresh_ids=[ "n9" ] )

    def test_in_sample_needs_pass( self ):
        assert arms.refuse_fresh_needs( [ "f01", "f02" ], fresh_ids=[ "n9" ] ) is None

    def test_the_reserved_file_itself_is_refused_whatever_its_ids_are( self ):
        with pytest.raises( CandidateError ) as caught:
            arms.refuse_fresh_needs( [ "wa-fresh-07" ], needs_sha="abc", fresh_sha="abc" )
        assert caught.value.code == arms.FRESH_NEEDS_REFUSED

    def test_a_different_file_passes_the_hash_check( self ):
        assert arms.refuse_fresh_needs( [ "need-03" ], needs_sha="abc", fresh_sha="def" ) is None

    def test_one_hash_without_the_other_is_an_error( self ):
        with pytest.raises( ValueError ):
            arms.refuse_fresh_needs( [ "need-03" ], needs_sha="abc" )


class TestSelectFusion:
    """The constants come from in-sample recall, ties to the smaller values."""

    def test_highest_recall_wins( self ):
        assert arms.select_fusion( { ( 60, 512, 5 ): 0.80, ( 30, 512, 5 ): 0.90, ( 60, 256, 5 ): 0.85 } ) == ( 30, 512, 5 )

    def test_ties_go_to_smaller_constants( self ):
        assert arms.select_fusion( { ( 60, 512, 5 ): 0.9, ( 60, 256, 5 ): 0.9, ( 30, 512, 10 ): 0.9 } ) == ( 30, 512, 10 )

    def test_empty_is_an_error( self ):
        with pytest.raises( CandidateError ) as caught:
            arms.select_fusion( {} )
        assert caught.value.code == arms.FUSION_EMPTY
