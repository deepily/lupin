"""
Tests for the stored-against-fresh vector comparison, on tiny vectors and fakes.

No test touches a database, the embedding service or a GPU.
"""

import contextlib
import json
from types import SimpleNamespace

import pytest

import cosa.research.preference_replay.vector_comparison as vc
from cosa.research.preference_replay.vector_comparison import (
    ControlFailed, band_counts, compare, cosine, main, negative_control, norm, parse_vector, positive_control, read_stored, report, summarize )


def test_parse_reads_pgvector_text_and_sequences():
    assert parse_vector( "[1,2.5,-3]" ) == [ 1.0, 2.5, -3.0 ]
    assert parse_vector( ( 1, 2 ) ) == [ 1.0, 2.0 ]


def test_norm_and_cosine_on_known_vectors():
    assert norm( [ 3.0, 4.0 ] ) == 5.0
    assert cosine( [ 1.0, 0.0 ], [ 2.0, 0.0 ] ) == pytest.approx( 1.0 )
    assert cosine( [ 1.0, 0.0 ], [ 0.0, 3.0 ] ) == pytest.approx( 0.0 )
    assert cosine( [ 1.0, 0.0 ], [ -1.0, 0.0 ] ) == pytest.approx( -1.0 )


def test_cosine_refuses_unequal_widths_and_zero_vectors():
    with pytest.raises( ValueError, match="differ in width" ): cosine( [ 1.0 ], [ 1.0, 2.0 ] )
    with pytest.raises( ValueError, match="zero norm" ): cosine( [ 0.0, 0.0 ], [ 1.0, 0.0 ] )


def test_summarize_gives_count_min_median_max():
    assert summarize( [ 3.0, 1.0, 2.0, 10.0 ] ) == { "n": 4, "min": 1.0, "median": 2.5, "max": 10.0 }


def test_bands_place_each_value_in_exactly_one_band_at_the_edges():
    counts = band_counts( [ 1.0, 0.999, 0.9989, 0.99, 0.9899, 0.9, 0.8999, -1.0 ] )
    assert counts == { "at or above 0.999": 2, "0.99 to 0.999": 2, "0.9 to 0.99": 2, "below 0.9": 2 }
    assert sum( counts.values() ) == 8


def test_compare_measures_cosine_and_norm_ratio_per_ask():
    result = compare( { "a": [ 1.0, 0.0 ], "b": [ 0.0, 2.0 ] }, { "a": [ 2.0, 0.0 ], "b": [ 2.0, 0.0 ] } )
    assert result[ "a" ] == { "cosine": pytest.approx( 1.0 ), "norm_ratio": pytest.approx( 2.0 ) }
    assert result[ "b" ] == { "cosine": pytest.approx( 0.0 ), "norm_ratio": pytest.approx( 1.0 ) }
    with pytest.raises( KeyError ): compare( { "a": [ 1.0 ], "c": [ 1.0 ] }, { "a": [ 1.0 ] } )


class FakeProvider:
    """Answers a batch from a table; a later call can drift, like a non-deterministic service."""

    def __init__( self, table, drift=0.0 ):
        self.table, self.drift, self.calls = table, drift, 0

    def generate_embeddings_batch( self, texts, content_type="prose", role=None ):
        self.calls += 1
        shift = self.drift * ( self.calls - 1 )
        return [ [ self.table[ text ][ 0 ] + shift, self.table[ text ][ 1 ] ] for text in texts ]


PAIRS = [ ( "a", "text a" ), ( "b", "text b" ) ]
TABLE = { "text a": [ 1.0, 0.0 ], "text b": [ 0.0, 1.0 ] }
FRESH = { "a": [ 1.0, 0.0 ], "b": [ 0.0, 1.0 ] }


def test_positive_control_passes_when_two_runs_and_the_file_agree():
    result = positive_control( FakeProvider( TABLE ), PAIRS, FRESH )
    assert result[ "twice_now_min_cosine" ] == pytest.approx( 1.0 ) and result[ "run_vs_side_file_min_cosine" ] == pytest.approx( 1.0 )


def test_positive_control_fails_when_two_runs_differ():
    with pytest.raises( ControlFailed, match="positive control" ): positive_control( FakeProvider( TABLE, drift=0.5 ), PAIRS, FRESH )


def test_positive_control_fails_when_the_run_differs_from_the_side_file():
    with pytest.raises( ControlFailed, match="against the side file" ):
        positive_control( FakeProvider( TABLE ), PAIRS, { "a": [ 0.0, 1.0 ], "b": [ 1.0, 0.0 ] } )


def test_negative_control_reports_mismatched_pairs_and_fails_when_texts_look_alike():
    stored = { "a": [ 1.0, 0.0 ], "b": [ 0.0, 1.0 ], "c": [ -1.0, 0.0 ] }
    fresh  = { "a": [ 1.0, 0.0 ], "b": [ 0.0, 1.0 ], "c": [ -1.0, 0.0 ] }
    result = negative_control( stored, fresh )
    assert result[ "mismatched_median_cosine" ] == pytest.approx( 0.0 ) and result[ "mismatched_max_cosine" ] == pytest.approx( 0.0 )
    same = { "a": [ 1.0, 0.0 ], "b": [ 1.0, 0.0 ] }
    with pytest.raises( ControlFailed, match="negative control" ): negative_control( same, same )


class FakeSession:
    """Rows for the stored-vector query and messages by id, recording rollbacks and statements."""

    def __init__( self, rows, messages ):
        self.rows, self.messages, self.statements, self.rollbacks = rows, messages, [], 0

    def execute( self, statement, params=None ):
        self.statements.append( str( statement ) )
        return SimpleNamespace( fetchall=lambda: self.rows )

    def get( self, model, row_id ):
        return SimpleNamespace( message=f"  {self.messages[ row_id ]}  " )

    def rollback( self ): self.rollbacks += 1


ROWS     = [ ( "a", "text a", "[1.0,0.0]" ), ( "b", "text b", "[0.0,1.0]" ) ]
MESSAGES = { "a": "text a", "b": "text b" }


def test_read_stored_returns_vectors_questions_and_stripped_messages():
    vectors, questions, messages = read_stored( FakeSession( ROWS, MESSAGES ), [ "a", "b" ] )
    assert vectors == { "a": [ 1.0, 0.0 ], "b": [ 0.0, 1.0 ] } and questions == { "a": "text a", "b": "text b" } and messages == MESSAGES


def _side_file( tmp_path, vectors ):
    header  = { "kind": "header", "version": 1, "model": "m", "revision": "r", "count": len( vectors ) }
    records = [ { "id": key, "model": "m", "revision": "r", "vector": vector } for key, vector in vectors.items() ]
    path    = tmp_path / "side.jsonl"
    path.write_text( "\n".join( [ json.dumps( header ) ] + [ json.dumps( record ) for record in records ] ) + "\n", encoding="utf-8" )
    return str( path )


def test_report_runs_the_controls_then_summarises_all_and_same_text_asks( tmp_path ):
    rows   = ROWS + [ ( "c", "old wording", "[1.0,1.0]" ), ( "d", "text d", "[1.0,0.1]" ) ]   # d sits at cosine 0.995 from its fresh vector
    result = report( _side_file( tmp_path, dict( FRESH, c=[ 0.0, 1.0 ], d=[ 1.0, 0.0 ] ) ), FakeSession( rows, dict( MESSAGES, c="new wording", d="text d" ) ),
                     FakeProvider( dict( TABLE, **{ "new wording": [ 0.0, 1.0 ] } ) ), control_size=2 )
    assert result[ "model" ] == "m" and len( result[ "side_file_sha256" ] ) == 64
    assert result[ "all_with_a_stored_vector" ][ "asks" ] == 4 and result[ "stored_question_equals_message" ][ "asks" ] == 3
    assert result[ "stored_question_differs_from_message" ] == 1
    assert result[ "all_with_a_stored_vector" ][ "at_or_above_0.999" ] == 2 and result[ "stored_question_equals_message" ][ "at_or_above_0.999" ] == 2
    assert result[ "all_with_a_stored_vector" ][ "bands" ][ "0.99 to 0.999" ] == 1
    assert result[ "controls" ][ "twice_now_min_cosine" ] == pytest.approx( 1.0 )


def test_main_prints_the_report_writes_the_out_file_and_rolls_back( tmp_path ):
    session = FakeSession( ROWS, MESSAGES )
    out     = tmp_path / "out.json"
    lines   = []
    code    = main( [ "--side-file", _side_file( tmp_path, FRESH ), "--out", str( out ) ], printer=lines.append,
                    session_factory=lambda: contextlib.nullcontext( session ), provider_factory=lambda: FakeProvider( TABLE ) )
    assert code == 0 and json.loads( lines[ 0 ] ) == json.loads( out.read_text() ) and session.rollbacks == 1
    assert session.statements[ 0 ] == "SET TRANSACTION READ ONLY"


def test_main_without_an_out_file_only_prints( tmp_path ):
    lines = []
    code  = main( [ "--side-file", _side_file( tmp_path, FRESH ) ], printer=lines.append,
                  session_factory=lambda: contextlib.nullcontext( FakeSession( ROWS, MESSAGES ) ), provider_factory=lambda: FakeProvider( TABLE ) )
    assert code == 0 and len( lines ) == 1


def test_main_stops_with_no_verdict_when_a_control_fails( tmp_path ):
    session = FakeSession( ROWS, MESSAGES )
    lines   = []
    code    = main( [ "--side-file", _side_file( tmp_path, FRESH ) ], printer=lines.append,
                    session_factory=lambda: contextlib.nullcontext( session ), provider_factory=lambda: FakeProvider( TABLE, drift=0.5 ) )
    assert code == 3 and len( lines ) == 1 and lines[ 0 ].startswith( "CONTROL FAILED, no verdict" ) and session.rollbacks == 1


@pytest.mark.parametrize( "cos_value,fails", [ ( 0.96, True ), ( 0.94, False ) ] )
def test_negative_control_threshold_sits_at_0_95( cos_value, fails ):
    other  = [ cos_value, ( 1 - cos_value ** 2 ) ** 0.5 ]
    stored = { "a": [ 1.0, 0.0 ], "b": [ 1.0, 0.0 ] }
    fresh  = { "a": other, "b": other }
    if fails:
        with pytest.raises( ControlFailed ): negative_control( stored, fresh )
    else:
        assert negative_control( stored, fresh )[ "mismatched_median_cosine" ] == pytest.approx( cos_value )
