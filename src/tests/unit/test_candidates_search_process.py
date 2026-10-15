"""
Unit tests for the search process: request in, answer out, cosine over stored matrices.

The vectors are small hand-made rows, so each cosine is worked by hand.
A fake loader stands in for the stored set; the process entry point is not run here.
"""
import io
import json
import sys
import types

import numpy as np
import pytest

from cosa.repo.symindex.candidates import search
from cosa.repo.symindex.candidates.errors import CandidateError, DEPENDENCY_MISSING

ENTRIES = [
    { "id": "py:a", "pin": "pa", "file": "a.py", "module": "a", "name": "get_user_profile", "sig": "(uid)", "doc": "Return the profile." },
    { "id": "py:b", "pin": "pb", "file": "b.py", "module": "b", "name": "load_settings",    "sig": "(path)", "doc": "Read settings." },
    { "id": "py:c", "pin": "pc", "file": "c.py", "module": "c", "name": "zero_row",         "sig": "()",     "doc": "Nothing." },
]


class FakeSet:
    """A loaded set with three rows: a along x, b along y, c all zero."""

    def __init__( self ):
        self.ids           = [ "py:a", "py:b", "py:c" ]
        self.manifest_hash = "hash-1"
        rows               = np.array( [ [ 1, 0 ], [ 0, 2 ], [ 0, 0 ] ], dtype=np.float32 )
        self.matrices      = { "prose": rows, "code": rows[ :, ::-1 ].copy(), "concat": rows }


@pytest.fixture
def generation( tmp_path ):
    gen = tmp_path / "gen"
    gen.mkdir()
    ( gen / "symbols.jsonl" ).write_text( "\n".join( json.dumps( e ) for e in ENTRIES ) + "\n", encoding="utf-8" )
    return gen


def request_for( generation, **more ):
    return dict( { "need": "profile", "K": 3, "index_dir": str( generation ) }, **more )


def run_main( request, loader=lambda d: FakeSet() ):
    out  = io.StringIO()
    code = search.main( io.StringIO( request if isinstance( request, str ) else json.dumps( request ) ), out, loader )
    return code, json.loads( out.getvalue() )


class TestCosine:
    """Cosine ranking, rounding and the zero cases."""

    def test_cosine_values_and_order( self ):
        matrix = np.array( [ [ 1, 0 ], [ 1, 1 ], [ 0, 1 ] ], dtype=np.float32 )
        pairs  = search.cosine_ranked( [ "x", "y", "z" ], matrix, [ 1.0, 0.0 ] )
        assert pairs == [ ( "x", 1.0 ), ( "y", 0.707107 ), ( "z", 0.0 ) ]

    def test_scale_does_not_change_the_score( self ):
        matrix = np.array( [ [ 3, 0 ], [ 0, 5 ] ], dtype=np.float32 )
        assert search.cosine_ranked( [ "x", "y" ], matrix, [ 100.0, 0.0 ] ) == [ ( "x", 1.0 ), ( "y", 0.0 ) ]

    def test_zero_row_and_zero_query_score_zero( self ):
        matrix = np.array( [ [ 0, 0 ], [ 1, 0 ] ], dtype=np.float32 )
        assert search.cosine_ranked( [ "a", "b" ], matrix, [ 1.0, 0.0 ] ) == [ ( "b", 1.0 ), ( "a", 0.0 ) ]
        assert search.cosine_ranked( [ "a", "b" ], matrix, [ 0.0, 0.0 ] ) == [ ( "a", 0.0 ), ( "b", 0.0 ) ]

    def test_equal_scores_break_on_id( self ):
        matrix = np.array( [ [ 1, 0 ], [ 1, 0 ] ], dtype=np.float32 )
        assert search.cosine_ranked( [ "z", "a" ], matrix, [ 1.0, 0.0 ] ) == [ ( "a", 1.0 ), ( "z", 1.0 ) ]

    def test_scores_round_before_the_sort( self ):
        # row a is about 1.8e-7 below row z in cosine, which rounds away at six places
        matrix = np.array( [ [ 1.0, 6e-4 ], [ 1.0, 0.0 ] ], dtype=np.float32 )
        pairs  = search.cosine_ranked( [ "a", "z" ], matrix, [ 1.0, 0.0 ] )
        assert pairs == [ ( "a", 1.0 ), ( "z", 1.0 ) ]

    def test_missing_numpy_is_a_named_error( self, monkeypatch ):
        monkeypatch.setitem( sys.modules, "numpy", None )
        with pytest.raises( CandidateError ) as caught: search.cosine_ranked( [ "a" ], [ [ 1.0 ] ], [ 1.0 ] )
        assert caught.value.code == DEPENDENCY_MISSING


class TestPurposes:
    """The purpose-line reader."""

    def test_none_is_empty( self ):
        assert search.read_purposes( None ) == {}

    def test_first_row_of_a_pin_wins( self, tmp_path ):
        path = tmp_path / "purpose.jsonl"
        path.write_text( "\n" + json.dumps( { "pin": "pa", "purpose": "first" } ) + "\n" + json.dumps( { "pin": "pa", "purpose": "second" } ) + "\n" )
        assert search.read_purposes( path ) == { "pa": "first" }


class TestAnswer:
    """One request, one answer."""

    def test_lexical_only( self, generation ):
        code, body = run_main( request_for( generation ) )
        assert code == 0
        assert body[ "ranking" ] == [ "py:a" ] and body[ "manifest_hash" ] is None and body[ "K" ] == 3
        assert body[ "lists" ] == { "code": [ "py:a" ], "prose": [ "py:a" ] }
        assert len( body[ "scores" ][ "code" ] ) == 1 and body[ "scores" ][ "code" ][ 0 ] > 0
        assert set( body[ "bm25" ] ) == { "code", "prose", "fusion" }

    def test_vectors_join_the_fusion( self, generation ):
        loaded = []
        def loader( folder ):
            loaded.append( folder )
            return FakeSet()
        request = request_for( generation, vectors_dir="/vec", query_vectors={ "prose": [ 0.0, 1.0 ] } )
        code, body = run_main( request, loader )
        assert code == 0 and loaded == [ "/vec" ]
        assert body[ "manifest_hash" ] == "hash-1"
        assert body[ "lists" ][ "vector_prose" ] == [ "py:b", "py:a", "py:c" ]
        assert body[ "lists" ][ "prose" ] == [ "py:a" ]            # the lexical list is untouched
        assert body[ "scores" ][ "vector_prose" ] == [ 1.0, 0.0, 0.0 ]
        assert body[ "ranking" ] == [ "py:a", "py:b", "py:c" ]

    def test_wiki_list_is_a_source( self, generation ):
        code, body = run_main( request_for( generation, wiki=[ "wiki:page" ] ) )
        assert code == 0 and "wiki:page" in body[ "ranking" ] and body[ "lists" ][ "wiki" ] == [ "wiki:page" ]

    def test_purpose_file_and_fusion_constants_are_used( self, generation, tmp_path ):
        path = tmp_path / "purpose.jsonl"
        path.write_text( json.dumps( { "pin": "pb", "purpose": "Parse configuration." } ) + "\n" )
        code, body = run_main( request_for( generation, need="parse configuration", purposes=str( path ), fusion={ "k": 7, "depth": 9, "head": 2 } ) )
        assert code == 0 and body[ "ranking" ] == [ "py:b" ]
        assert body[ "bm25" ][ "fusion" ] == { "k": 7, "depth": 9, "head": 2 }

    def test_same_request_same_bytes( self, generation ):
        out = []
        for _ in range( 2 ):
            buf = io.StringIO()
            search.main( io.StringIO( json.dumps( request_for( generation, wiki=[ "w" ] ) ) ), buf, lambda d: FakeSet() )
            out.append( buf.getvalue() )
        assert out[ 0 ] == out[ 1 ]


class TestMalformedRequests:
    """Each wrong shape answers BAD_SEARCH_REQUEST, never a traceback."""

    @pytest.mark.parametrize( "more,detail", [
        ( { "vectors_dir": "/v" },                                            "query_vectors" ),
        ( { "vectors_dir": "/v", "query_vectors": {} },                       "query_vectors" ),
        ( { "vectors_dir": "/v", "query_vectors": [ 1.0 ] },                  "query_vectors" ),
        ( { "vectors_dir": "/v", "query_vectors": { "prose": [] } },          "finite numbers" ),
        ( { "vectors_dir": "/v", "query_vectors": { "prose": [ "x" ] } },     "finite numbers" ),
        ( { "vectors_dir": "/v", "query_vectors": { "prose": [ True ] } },    "finite numbers" ),
        ( { "vectors_dir": "/v", "query_vectors": { "prose": [ float( "nan" ), 0.0 ] } }, "finite numbers" ),
        ( { "vectors_dir": 3, "query_vectors": { "prose": [ 1.0 ] } },        "vectors_dir" ),
        ( { "vectors_dir": "/v", "query_vectors": { "nope": [ 1.0, 0.0 ] } }, "no matrix nope" ),
        ( { "vectors_dir": "/v", "query_vectors": { "prose": [ 1.0, 0.0, 0.0 ] } }, "3 values" ),
        ( { "K": "3" },                                                       "K" ),
        ( { "K": 0 },                                                         "K" ),
        ( { "K": True },                                                      "K" ),
        ( { "need": 5 },                                                      "need" ),
        ( { "index_dir": 5 },                                                 "index_dir" ),
        ( { "purposes": 5 },                                                  "purposes" ),
        ( { "wiki": "page" },                                                 "wiki" ),
        ( { "wiki": [ 1 ] },                                                  "wiki" ),
        ( { "fusion": { "k": 7 } },                                           "fusion" ),
        ( { "fusion": "x" },                                                  "fusion" ),
        ( { "fusion": { "k": 0, "depth": 9, "head": 2 } },                    "k and depth" ),
        ( { "fusion": { "k": 7, "depth": "9", "head": 2 } },                  "k and depth" ),
        ( { "fusion": { "k": 7, "depth": 9, "head": -1 } },                   "head" ),
        ( { "fusion": { "k": 7, "depth": 9, "head": 10 } },                   "head" ),
    ] )
    def test_bad_shape( self, generation, more, detail ):
        code, body = run_main( request_for( generation, **more ) )
        assert code == 2
        assert body[ "error" ] == search.REQUEST_ERROR and detail in body[ "detail" ]

    def test_unreadable_index( self, tmp_path ):
        code, body = run_main( { "need": "x", "K": 1, "index_dir": str( tmp_path / "nowhere" ) } )
        assert code == 2 and body[ "error" ] == search.INDEX_UNREADABLE

    def test_unreadable_purpose_file( self, generation, tmp_path ):
        bad = tmp_path / "purpose.jsonl"
        bad.write_text( json.dumps( { "pin": "pa" } ) + "\n" )
        code, body = run_main( request_for( generation, purposes=str( bad ) ) )
        assert code == 2 and body[ "error" ] == search.INDEX_UNREADABLE


class TestIndexAgainstVectors:
    """A vector set must belong to the index."""

    def test_ids_outside_the_index_are_refused_by_name( self, generation ):
        class Ghosty( FakeSet ):
            def __init__( self ):
                super().__init__()
                self.ids = [ "py:a", "py:b", "gone::g" ]
        request = request_for( generation, vectors_dir="/v", query_vectors={ "prose": [ 0.0, 1.0 ] } )
        code, body = run_main( request, lambda d: Ghosty() )
        assert code == 2 and body[ "error" ] == search.VECTOR_IDS_NOT_INDEX and "gone::g" in body[ "detail" ]

    def test_index_ids_without_a_vector_are_counted( self, generation ):
        class Short( FakeSet ):
            def __init__( self ):
                super().__init__()
                self.ids      = [ "py:a", "py:b" ]
                self.matrices = { k: v[ :2 ] for k, v in self.matrices.items() }
        request = request_for( generation, vectors_dir="/v", query_vectors={ "prose": [ 0.0, 1.0 ] } )
        code, body = run_main( request, lambda d: Short() )
        assert code == 0 and body[ "index_ids_without_vectors" ] == 1

    def test_full_set_counts_zero( self, generation ):
        code, body = run_main( request_for( generation, vectors_dir="/v", query_vectors={ "prose": [ 0.0, 1.0 ] } ) )
        assert code == 0 and body[ "index_ids_without_vectors" ] == 0


class TestLowNotes:
    """Krishna's three low notes: float32 range, loader OSError, ids and rows that disagree."""

    def test_value_beyond_float32_is_refused( self, generation ):
        request = request_for( generation, vectors_dir="/v", query_vectors={ "prose": [ 1e300, 1e300 ] } )
        code, body = run_main( request )
        assert code == 2 and body[ "error" ] == search.REQUEST_ERROR and "float32" in body[ "detail" ]

    def test_value_inside_float32_whose_norm_overflows_is_refused( self, generation ):
        request = request_for( generation, vectors_dir="/v", query_vectors={ "prose": [ 3.4e38, 0.0 ] } )
        code, body = run_main( request )
        assert code == 2 and body[ "error" ] == search.REQUEST_ERROR and "not finite" in body[ "detail" ]

    def test_scores_that_overflow_are_refused( self, generation ):
        request = request_for( generation, vectors_dir="/v", query_vectors={ "prose": [ 3e19, 3e19 ] } )
        code, body = run_main( request )
        assert code == 2 and body[ "error" ] == search.REQUEST_ERROR and "not finite" in body[ "detail" ]

    def test_loader_oserror_is_a_named_error( self, generation ):
        def loader( folder ): raise PermissionError( "denied" )
        request = request_for( generation, vectors_dir="/v", query_vectors={ "prose": [ 0.0, 1.0 ] } )
        code, body = run_main( request, loader )
        assert code == 2 and body[ "error" ] == "VECTOR_SET_UNAVAILABLE" and "denied" in body[ "detail" ]

    def test_ids_and_rows_that_disagree_are_refused( self, generation ):
        class Skewed( FakeSet ):
            def __init__( self ):
                super().__init__()
                self.matrices = { k: v[ :2 ] for k, v in self.matrices.items() }
        request = request_for( generation, vectors_dir="/v", query_vectors={ "prose": [ 0.0, 1.0 ] } )
        code, body = run_main( request, lambda d: Skewed() )
        assert code == 2 and body[ "error" ] == "VECTOR_SET_CORRUPT" and "2 rows" in body[ "detail" ]


class TestShortlistSize:
    """K is a hard cap on the answer."""

    def test_answer_never_exceeds_k( self, generation ):
        request = request_for( generation, K=3, wiki=[ f"w:{i}" for i in range( 20 ) ], fusion={ "k": 60, "depth": 100, "head": 1 },
                               vectors_dir="/v", query_vectors={ "prose": [ 0.0, 1.0 ], "code": [ 1.0, 0.0 ], "concat": [ 0.0, 1.0 ] } )
        code, body = run_main( request )
        assert code == 0 and len( body[ "shortlist" ] ) == 3 and len( body[ "ranking" ] ) == 3

    def test_heads_larger_than_k_are_refused( self, generation ):
        request = request_for( generation, K=1, wiki=[ "w:1" ], fusion={ "k": 60, "depth": 100, "head": 1 } )
        code, body = run_main( request )
        assert code == 2 and body[ "error" ] == "HEAD_EXCEEDS_LIMIT"

    def test_repeated_wiki_ids_count_once( self, generation ):
        once  = run_main( request_for( generation, wiki=[ "w:1", "w:2" ] ) )[ 1 ]
        twice = run_main( request_for( generation, wiki=[ "w:1", "w:1", "w:2" ] ) )[ 1 ]
        assert once[ "ranking" ] == twice[ "ranking" ]


class TestErrors:
    """Failures answer with a code and exit 2."""

    def test_missing_key( self, generation ):
        code, body = run_main( { "need": "x", "K": 1 } )
        assert code == 2 and body[ "error" ] == search.REQUEST_ERROR and "index_dir" in body[ "detail" ]

    def test_not_json( self ):
        code, body = run_main( "{nope" )
        assert code == 2 and body[ "error" ] == search.REQUEST_ERROR

    def test_not_an_object( self ):
        code, body = run_main( "[1]" )
        assert code == 2 and "not a JSON object" in body[ "detail" ]

    def test_loader_error_is_passed_through( self, generation ):
        def loader( folder ): raise CandidateError( "VECTOR_SET_UNAVAILABLE", "no manifest" )
        code, body = run_main( request_for( generation, vectors_dir="/v", query_vectors={ "prose": [ 0.0, 1.0 ] } ), loader )
        assert code == 2 and body == { "error": "VECTOR_SET_UNAVAILABLE", "detail": "no manifest" }


class TestDefaultLoader:
    """The default loader reaches the vector store."""

    def test_calls_load_vectors( self, monkeypatch ):
        fake = types.ModuleType( "cosa.repo.symindex.candidates.vector_store" )
        fake.load_vectors = lambda folder: ( "loaded", folder )
        monkeypatch.setitem( sys.modules, "cosa.repo.symindex.candidates.vector_store", fake )
        monkeypatch.setattr( "cosa.repo.symindex.candidates.vector_store", fake, raising=False )
        assert search.default_loader( "/v" ) == ( "loaded", "/v" )


class TestStreams:
    """main falls back to the process streams."""

    def test_defaults_are_stdin_and_stdout( self, monkeypatch, generation, capsys ):
        monkeypatch.setattr( sys, "stdin", io.StringIO( json.dumps( request_for( generation ) ) ) )
        assert search.main() == 0
        assert json.loads( capsys.readouterr().out )[ "ranking" ] == [ "py:a" ]
