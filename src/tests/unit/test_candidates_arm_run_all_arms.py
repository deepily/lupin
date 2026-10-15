"""
Unit tests for the all-arms run: vector lists, fusion selection, cache reader, page.

Venue: :7999-eligible. The index is six hand-built entries and the vectors are three-column arrays.
The cache is a dict. Nothing touches a model, the network or the shared data folder.
"""
import gzip
import json
import types

import numpy as np
import pytest

from cosa.repo.symindex.candidates import arm_report
from cosa.repo.symindex.candidates import arm_run
from cosa.repo.symindex.candidates import arms
from cosa.repo.symindex.candidates import vector_store as vs
from cosa.repo.symindex.candidates.errors import CandidateError

from test_candidates_arm_run import ENTRIES, TestTwins, cache_for, fake_env, write_needs

IDS     = [ e[ "id" ] for e in sorted( ENTRIES, key=lambda e: e[ "id" ] ) ]
GRID    = ( ( 60, 512, 5 ), ( 10, 128, 5 ) )
PURPOSE = { "pin-a": "Reads a configuration file." }


def vset( ids=None ):
    """A vector set whose rows rank the ids in id order for every query."""
    ids   = ids if ids is not None else IDS
    rows  = np.array( [ [ float( n + 1 ), 1.0, 0.0 ] for n in range( len( ids ) ) ], dtype=np.float32 )
    return types.SimpleNamespace( ids=list( ids ), matrices={ "concat": rows, "prose": rows, "code": rows }, manifest_hash="mh" * 32 )


def query( text ):
    """Every query points along the first row."""
    return { "concat": [ 1.0, 1.0, 0.0 ], "prose": [ 1.0, 1.0, 0.0 ], "code": [ 1.0, 1.0, 0.0 ] }


def snapshot( tmp_path ):
    path = tmp_path / "aaaa.json.gz"
    path.write_bytes( gzip.compress( json.dumps( { "symbols_jsonl": "\n".join( json.dumps( e ) for e in ENTRIES ) } ).encode() ) )
    return str( path )


def world( tmp_path ):
    manifest = tmp_path / "manifest.json"
    manifest.write_text( json.dumps( TestTwins.MANIFEST ) )
    return { "env": fake_env( cache_for( [ "n1", "n2" ], { "n1": "parse_config" } ) ), "snaps": [ snapshot( tmp_path ) ], "needs": write_needs( tmp_path ),
             "manifest": str( manifest ), "pages": [ { "slug": "config", "text": "read config file", "pins": [ "a", "b" ] } ] }


class TestListsFor:
    def test_a_mapping_is_returned_as_it_is( self ):
        held = { "wiki": [ "a" ] }
        assert arm_run.lists_for( held, "text" ) is held

    def test_a_callable_gets_the_query_text( self ):
        assert arm_run.lists_for( lambda t: { "wiki": [ t ] }, "q" ) == { "wiki": [ "q" ] }


class TestVectorSource:
    def test_ranks_only_the_entries_the_set_holds_and_cuts_the_rows_once( self ):
        source = arm_run.vector_source( [ "a", "b", "zz" ], vset( [ "a", "b", "c" ] ), query )
        got    = source( "q" )
        assert sorted( got ) == [ "vector_code", "vector_concat", "vector_prose" ]
        assert got[ "vector_prose" ] == [ "a", "b" ]            # the first row matches the query best, and zz is not in the set

    def test_the_query_text_reaches_the_query_source( self ):
        seen = []
        arm_run.vector_source( IDS, vset(), lambda t: seen.append( t ) or query( t ) )( "need text" )
        assert seen == [ "need text" ]


class TestSelectFusion:
    def test_returns_the_best_grid_point_and_every_recall( self, tmp_path ):
        w     = world( tmp_path )
        needs = arm_run.load_needs( w[ "needs" ], "f" * 64 )
        entries = arm_run.snapshot_entries( w[ "snaps" ][ 0 ], w[ "env" ].sendable )
        answers, _ = arm_run.load_answers( needs, entries, w[ "env" ] )
        source = arm_run.vector_source( IDS, vset(), query )
        chosen, recall = arm_run.select_fusion_constants( needs, entries, PURPOSE, answers, source, GRID )
        assert chosen in GRID and sorted( recall ) == sorted( GRID )
        assert all( 0.0 <= v <= 1.0 for v in recall.values() )
        assert recall[ chosen ] == max( recall.values() )


class TestCachedQueryVectors:
    def write( self, tmp_path, text, hash_="mh", vectors=None ):
        ( tmp_path / f"{vs.query_key( text )}.json" ).write_text( json.dumps( { "manifest_hash": hash_, "vectors": vectors or query( text ) } ) )

    def test_reads_a_cached_vector_made_under_the_set( self, tmp_path ):
        self.write( tmp_path, "need one" )
        assert arm_run.cached_query_vectors( tmp_path, "mh" )( "need one" ) == query( "x" )

    @pytest.mark.parametrize( "setup", [ "absent", "unreadable", "no_hash" ] )
    def test_a_missing_or_unreadable_file_is_a_named_error( self, tmp_path, setup ):
        if setup == "unreadable": ( tmp_path / f"{vs.query_key( 't' )}.json" ).write_text( "{not json" )
        if setup == "no_hash": ( tmp_path / f"{vs.query_key( 't' )}.json" ).write_text( json.dumps( { "vectors": {} } ) )
        with pytest.raises( CandidateError ) as caught:
            arm_run.cached_query_vectors( tmp_path, "mh" )( "t" )
        assert caught.value.code == arm_run.QUERY_VECTOR_MISSING

    def test_a_vector_made_under_another_set_is_refused_and_never_recomputed( self, tmp_path ):
        self.write( tmp_path, "t", hash_="other" )
        with pytest.raises( CandidateError ) as caught:
            arm_run.cached_query_vectors( tmp_path, "mh" )( "t" )
        assert caught.value.code == arm_run.QUERY_VECTOR_MISSING and "another set" in caught.value.detail


class TestRunAllArms:
    def run( self, tmp_path, **extra ):
        w = world( tmp_path )
        return arm_run.run_all_arms( w[ "env" ], w[ "snaps" ], w[ "needs" ], "f" * 64, w[ "manifest" ], extra.pop( "vset", vset() ), PURPOSE, w[ "pages" ],
                                     query, lambda text: text, "abc123", grid=GRID, **extra )

    def test_measures_all_five_arms_on_one_snapshot_and_chooses_the_vectors( self, tmp_path ):
        out = self.run( tmp_path )
        assert sorted( out[ "measured" ] ) == sorted( arms.ARMS ) and sorted( out[ "t3" ] ) == sorted( arms.ARMS )
        assert out[ "fusion" ] in GRID and sorted( out[ "recall_by_params" ] ) == sorted( GRID )
        assert out[ "vectors_choice" ] in ( "B1", "B2" )
        assert out[ "meta" ][ "manifest_hash" ] == "mh" * 32 and out[ "meta" ][ "code_sha" ] == "abc123"
        assert out[ "needs" ] == 2 and out[ "misses" ] == 0 and out[ "pages" ] == len( world( tmp_path )[ "pages" ] )
        assert out[ "snapshot_entries" ] == len( ENTRIES ) and out[ "vector_entries" ] == len( IDS )
        ref = out[ "reference" ]
        assert ref[ "needs" ] == len( ref[ "per_need" ] ) and ref[ "items" ] == sum( ref[ "per_need" ].values() )
        assert set( ref[ "per_need" ] ) <= { "n1", "n2" } and all( c >= 1 for c in ref[ "per_need" ].values() )

    def test_the_vector_count_is_what_the_set_holds_of_the_snapshot( self, tmp_path ):
        out = self.run( tmp_path, vset=vset( IDS[ :4 ] + [ "not-in-the-index" ] ) )
        assert out[ "vector_entries" ] == 4

    def test_a_run_with_no_vector_arm_embeds_nothing_and_makes_no_choice( self, tmp_path ):
        w = world( tmp_path )
        def must_not_run( text ): raise AssertionError( "no vector arm, so no embedding" )
        out = arm_run.run_all_arms( w[ "env" ], w[ "snaps" ], w[ "needs" ], "f" * 64, w[ "manifest" ], None, PURPOSE, w[ "pages" ], must_not_run,
                                    lambda text: text, "abc123", arm_names=( "C0", "C1" ) )
        assert sorted( out[ "measured" ] ) == [ "C0", "C1" ] and out[ "vectors_choice" ] is None
        assert out[ "recall_by_params" ] == {} and out[ "fusion" ] == ( 60, 512, 5 )
        assert out[ "meta" ][ "manifest_hash" ] == "none" and out[ "vector_entries" ] == 0

    def test_a_pin_with_an_empty_purpose_that_a_reference_holds_is_reported( self, tmp_path ):
        w = world( tmp_path )
        out = arm_run.run_all_arms( w[ "env" ], w[ "snaps" ], w[ "needs" ], "f" * 64, w[ "manifest" ], None, { "pin-a": "" }, w[ "pages" ], None,
                                    lambda text: text, "abc123", arm_names=( "C0", ) )
        assert out[ "empty_purpose_entries" ] == 1 and out[ "empty_purpose_in_references" ] == [ "a" ]

    def test_the_reserved_needs_file_is_refused( self, tmp_path ):
        w = world( tmp_path )
        with pytest.raises( CandidateError ) as caught:
            arm_run.run_all_arms( w[ "env" ], w[ "snaps" ], w[ "needs" ], arm_run.sha256_of( w[ "needs" ] ), w[ "manifest" ], vset(), PURPOSE, w[ "pages" ],
                                  query, lambda text: text, "abc123" )
        assert caught.value.code == arms.FRESH_NEEDS_REFUSED


class TestRenderAllArmsPage:
    REDACT = { "count": 1, "ids": [ "n1" ], "of": 2, "control": True }

    def test_the_page_carries_every_arm_the_fusion_table_and_the_counts( self, tmp_path ):
        w = world( tmp_path )
        out = arm_run.run_all_arms( w[ "env" ], w[ "snaps" ], w[ "needs" ], "f" * 64, w[ "manifest" ], vset(), PURPOSE, w[ "pages" ], query,
                                    lambda text: text, "abc123", grid=GRID )
        page = arm_run.render_all_arms_page( out, self.REDACT )
        for arm in arms.ARMS: assert f"| {arm} |" in page
        assert "## Fusion constants chosen on the in-sample needs" in page and "| 60 | 512 | 5 |" in page
        assert out[ "vectors_choice" ] in ( "B1", "B2" ) and f"{out[ 'vectors_choice' ]} by the rule" in page and "so a tie is B1" in page
        assert f"holds {out[ 'snapshot_entries' ]} sendable entries" in page and "abc123" in page
        assert out[ "pages" ] == 1 and "Capability pages offered to the wiki list: 1." in page
        ref = out[ "reference" ]
        assert f"mean over the {ref[ 'needs' ]} needs whose repeat-1 reference is not empty, which hold {ref[ 'items' ]} reference items" in page

    def test_a_run_without_vectors_says_the_choice_and_the_selection_were_not_made( self, tmp_path ):
        w = world( tmp_path )
        out = arm_run.run_all_arms( w[ "env" ], w[ "snaps" ], w[ "needs" ], "f" * 64, w[ "manifest" ], None, PURPOSE, w[ "pages" ], None,
                                    lambda text: text, "abc123", arm_names=( "C0", "C1" ) )
        page = arm_run.render_all_arms_page( out, self.REDACT )
        assert "not decided: no vector arm was measured" in page and "Not selected: no vector arm was measured" in page
        assert "| C1 |" in page and "| B1 |" not in page

    def test_a_result_with_a_missing_meta_key_is_refused( self, tmp_path ):
        w = world( tmp_path )
        out = arm_run.run_all_arms( w[ "env" ], w[ "snaps" ], w[ "needs" ], "f" * 64, w[ "manifest" ], None, PURPOSE, w[ "pages" ], None,
                                    lambda text: text, "", arm_names=( "C0", ) )
        with pytest.raises( CandidateError ) as caught:
            arm_run.render_all_arms_page( out, self.REDACT )
        assert caught.value.code == arm_report.REPORT_META_MISSING
