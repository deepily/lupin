"""
The generator embeds each cohort question, validates the vector and stamps the run.

The provider is a fake that answers from a table, so no service is called and no GPU is touched.
"""

import contextlib
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import cosa.research.preference_replay.question_vectors as qv
from cosa.research.preference_replay.question_vectors import (
    EngineChanged, cohort_texts, engine_stamp, generate, load_side_file, main, norm_band, read_side_records, write_side_file )

STAMP = { "model": "m", "revision": "r1", "dtype": "float16", "dimensions": 768 }


def _good( axis=0 ):
    """A 768-wide vector with norm 20, inside the current model's band."""
    vector = [ 0.0 ] * 768
    vector[ axis ] = 20.0
    return vector


class FakeProvider:
    """Answers describe_engines from a list of blocks and the batch call from a table."""

    def __init__( self, blocks=None, vectors=None ):
        self.blocks  = list( blocks ) if blocks is not None else [ dict( STAMP, loaded=True ) ]
        self.calls   = []
        self.vectors = vectors or {}
        self.reads   = 0

    def describe_engines( self ):
        block = self.blocks[ min( self.reads, len( self.blocks ) - 1 ) ]
        self.reads += 1
        return { "prose": block }

    def generate_embeddings_batch( self, texts, content_type="prose", role=None, pin_fastapi=False ):
        self.calls.append( ( list( texts ), content_type, role ) )
        return [ self.vectors.get( text, _good( len( text ) % 700 ) ) for text in texts ]


def test_the_stamp_is_the_four_keys_of_the_prose_block():
    assert engine_stamp( FakeProvider() ) == STAMP


@pytest.mark.parametrize( "block", [ { "model": "m" }, dict( STAMP, loaded=False ), dict( STAMP, loaded=True, revision=None ) ] )
def test_a_block_that_lacks_a_key_is_not_loaded_or_has_no_revision_is_refused( block ):
    with pytest.raises( ValueError ):
        engine_stamp( FakeProvider( [ block ] ) )


def test_the_first_twenty_are_embedded_and_timed_alone_then_the_rest_in_batches():
    pairs    = [ ( f"id{n}", f"question number {n}" ) for n in range( 50 ) ]
    provider = FakeProvider()
    ticks    = iter( [ 0.0, 2.0, 10.0 ] )
    result   = generate( pairs, provider, probe_size=20, batch_size=16, clock=lambda: next( ticks ) )
    assert [ len( call[ 0 ] ) for call in provider.calls ] == [ 16, 4, 16, 14 ]
    assert provider.calls[ 0 ][ 0 ][ 0 ] == "question number 0" and all( call[ 1:] == ( "prose", None ) for call in provider.calls )
    assert ( result[ "probe_seconds" ], result[ "total_seconds" ], result[ "texts" ] ) == ( 2.0, 10.0, 50 )
    assert len( result[ "vectors" ] ) == 50 and result[ "rejects" ] == [] and result[ "stamp" ] == STAMP


def test_probe_only_embeds_twenty_and_stops():
    provider = FakeProvider()
    result   = generate( [ ( f"id{n}", f"q{n}" ) for n in range( 50 ) ], provider, probe_only=True )
    assert sum( len( call[ 0 ] ) for call in provider.calls ) == 20 and len( result[ "vectors" ] ) == 20


def test_an_empty_text_is_rejected_and_never_sent_and_a_bad_vector_is_rejected_with_its_reason():
    provider = FakeProvider( vectors={ "bad": [ 1.0, 2.0 ] } )
    result   = generate( [ ( "a", "" ), ( "b", "bad" ), ( "c", "fine" ) ], provider )
    assert [ text for call in provider.calls for text in call[ 0 ] ] == [ "bad", "fine" ]
    assert sorted( result[ "vectors" ] ) == [ "c" ]
    assert result[ "rejects" ][ 0 ] == { "id": "a", "reason": "empty question text" }
    assert result[ "rejects" ][ 1 ][ "id" ] == "b" and result[ "rejects" ][ 1 ][ "reason" ].startswith( "wrong dimension 2" )


@pytest.mark.parametrize( "field, value", [ ( "model", "other" ), ( "revision", "r2" ), ( "dtype", "float32" ), ( "dimensions", 1024 ) ] )
def test_a_change_in_any_field_between_the_two_reads_stops_the_run( field, value ):
    provider = FakeProvider( [ dict( STAMP, loaded=True ), dict( STAMP, loaded=True, **{ field: value } ) ] )
    with pytest.raises( EngineChanged ):
        generate( [ ( "a", "q" ) ], provider )


def test_each_ids_vector_is_the_one_made_for_its_own_text_across_the_probe_boundary_and_an_early_empty_text():
    texts    = [ "x" * n for n in ( 1, 0, 5, 9, 3, 7, 11, 2 ) ]
    pairs    = [ ( f"id{n}", text ) for n, text in enumerate( texts ) ]
    provider = FakeProvider()
    result   = generate( pairs, provider, probe_size=3, batch_size=2 )
    assert sorted( result[ "vectors" ] ) == sorted( ask_id for ask_id, text in pairs if text )
    assert all( result[ "vectors" ][ ask_id ] == _good( len( text ) ) for ask_id, text in pairs if text )
    assert result[ "rejects" ] == [ { "id": "id1", "reason": "empty question text" } ]


def test_the_info_block_is_read_after_the_probe_and_again_after_the_last_call():
    order    = []
    provider = FakeProvider()
    describe, batch = provider.describe_engines, provider.generate_embeddings_batch
    provider.describe_engines = lambda: order.append( "info" ) or describe()
    provider.generate_embeddings_batch = lambda texts, content_type="prose": order.append( "batch" ) or batch( texts, content_type )
    generate( [ ( f"id{n}", f"q{n}" ) for n in range( 30 ) ], provider, probe_size=20, batch_size=64 )
    assert order == [ "batch", "info", "batch", "info" ]


def test_a_lazily_loaded_engine_is_stamped_because_the_probe_ran_before_the_first_read():
    provider = FakeProvider()
    batch    = provider.generate_embeddings_batch
    provider.describe_engines = lambda: { "prose": dict( STAMP, loaded=bool( provider.calls ) ) }
    provider.generate_embeddings_batch = batch
    assert generate( [ ( "a", "q" ) ], provider )[ "stamp" ] == STAMP


def test_a_short_answer_from_the_service_is_refused():
    provider = FakeProvider()
    provider.generate_embeddings_batch = lambda texts, content_type="prose": [ _good() ]
    with pytest.raises( ValueError, match="asked for 2 vectors and got 1" ):
        generate( [ ( "a", "x" ), ( "b", "y" ) ], provider )


def test_repeated_ids_are_refused():
    with pytest.raises( ValueError, match="not distinct" ):
        generate( [ ( "a", "x" ), ( "a", "y" ) ], FakeProvider() )


def test_the_norm_band_is_the_smallest_and_largest_length_and_none_when_empty():
    assert norm_band( { "a": [ 3.0, 4.0 ], "b": [ 6.0, 8.0 ] } ) == { "min": 5.0, "max": 10.0 }
    assert norm_band( {} ) is None


def _result( vectors=None ):
    return { "stamp": STAMP, "vectors": vectors if vectors is not None else { "a": [ 3.0, 4.0 ] }, "rejects": [ { "id": "z", "reason": "r" } ],
             "probe_seconds": 1.0, "total_seconds": 2.0, "texts": 2 }


def test_the_side_file_is_json_lines_a_header_then_one_record_per_ask_and_round_trips( tmp_path ):
    path = str( tmp_path / "v.json" )
    write_side_file( path, _result( { "b": [ 6.0, 8.0 ], "a": [ 3.0, 4.0 ] } ), { "database": "d" } )
    lines = ( tmp_path / "v.json" ).read_text().splitlines()
    head  = json.loads( lines[ 0 ] )
    assert ( head[ "kind" ], head[ "model" ], head[ "revision" ], head[ "count" ], head[ "engines" ] ) == ( "header", "m", "r1", 2, STAMP )
    assert [ json.loads( line ) for line in lines[ 1: ] ] == [ { "id": "a", "model": "m", "revision": "r1", "vector": [ 3.0, 4.0 ] },
                                                               { "id": "b", "model": "m", "revision": "r1", "vector": [ 6.0, 8.0 ] } ]
    header, vectors = load_side_file( path )
    assert vectors == { "a": [ 3.0, 4.0 ], "b": [ 6.0, 8.0 ] }
    assert ( header[ "texts" ], header[ "rejects" ], header[ "norm_band" ] ) == ( 2, [ { "id": "z", "reason": "r" } ], { "min": 5.0, "max": 10.0 } )
    assert header[ "facts" ] == { "database": "d" } and header[ "text_rule" ] == "message.strip()"
    assert [ p.name for p in tmp_path.iterdir() ] == [ "v.json" ]


def _edit( path, change ):
    lines = open( path ).read().splitlines()
    change( lines )
    open( path, "w" ).write( "\n".join( lines ) + "\n" )


def _fresh( tmp_path ):
    path = str( tmp_path / "v.json" )
    write_side_file( path, _result(), {} )
    return path


def _swap( key, value ):
    return lambda lines: lines.__setitem__( 1, json.dumps( dict( json.loads( lines[ 1 ] ), **{ key: value } ) ) )


def test_a_file_that_is_empty_headerless_of_another_version_miscounted_or_inconsistent_is_refused( tmp_path ):
    path = str( tmp_path / "v.json" )
    open( path, "w" ).write( "\n" )
    with pytest.raises( ValueError, match="empty" ): load_side_file( path )
    path = _fresh( tmp_path )
    _edit( path, lambda lines: lines.__setitem__( 0, lines[ 1 ] ) )
    with pytest.raises( ValueError, match="not a header" ): load_side_file( path )
    _fresh( tmp_path )
    _edit( path, lambda lines: lines.__setitem__( 0, json.dumps( dict( json.loads( lines[ 0 ] ), version=99 ) ) ) )
    with pytest.raises( ValueError, match="version 99" ): load_side_file( path )
    _fresh( tmp_path )
    _edit( path, lambda lines: lines.__setitem__( 0, json.dumps( dict( json.loads( lines[ 0 ] ), count=5 ) ) ) )
    with pytest.raises( ValueError, match="says 5 vectors" ): load_side_file( path )
    _fresh( tmp_path )
    _edit( path, _swap( "revision", "r2" ) )
    with pytest.raises( ValueError, match="different model or revision" ): load_side_file( path )
    _fresh( tmp_path )
    _edit( path, _swap( "model", "other" ) )
    with pytest.raises( ValueError, match="different model or revision" ): load_side_file( path )


class _Refused( Exception ):
    """A stand-in for a caller's own refusal class."""


def test_a_header_without_a_model_is_refused_in_the_callers_own_exception_class( tmp_path ):
    path = _fresh( tmp_path )
    _edit( path, lambda lines: lines.__setitem__( 0, json.dumps( { k: v for k, v in json.loads( lines[ 0 ] ).items() if k != "model" } ) ) )
    with pytest.raises( _Refused, match="lacks model or revision" ): read_side_records( path, refuse=_Refused )
    with pytest.raises( ValueError, match="lacks model or revision" ): load_side_file( path )


def test_another_version_is_read_only_when_the_caller_skips_the_version_check( tmp_path ):
    path = _fresh( tmp_path )
    _edit( path, lambda lines: lines.__setitem__( 0, json.dumps( dict( json.loads( lines[ 0 ] ), version=99 ) ) ) )
    header, records = read_side_records( path, expected_version=None )
    assert header[ "version" ] == 99 and [ record[ "id" ] for record in records ] == [ "a" ]
    with pytest.raises( ValueError, match="version 99" ): read_side_records( path )


def test_a_repeated_id_is_refused( tmp_path ):
    path = _fresh( tmp_path )
    _edit( path, lambda lines: ( lines.append( lines[ 1 ] ), lines.__setitem__( 0, json.dumps( dict( json.loads( lines[ 0 ] ), count=2 ) ) ) ) )
    with pytest.raises( ValueError, match="appears twice" ): load_side_file( path )


def test_the_cohort_texts_are_stripped_messages_in_cohort_order():
    rows = { "yes_no": [ SimpleNamespace( notification_id="y1" ) ], "multiple_choice": [ SimpleNamespace( notification_id="m1" ) ] }

    class Session:
        def get( self, model, key ): return SimpleNamespace( message=f"  text of {key} \n" )

    with patch.object( qv, "scored_rows", side_effect=lambda session, kind: rows[ kind ] ):
        assert cohort_texts( Session() ) == [ ( "y1", "text of y1" ), ( "m1", "text of m1" ) ]


class FakeResult:
    def __init__( self, rows ): self.rows = rows
    def fetchall( self ): return self.rows


class FakeSession:
    def __init__( self ):
        self.statements  = []
        self.rolled_back = False

    def execute( self, statement ):
        self.statements.append( str( statement ) )
        return FakeResult( [ ( "lupin_db_dev", "lupin_host", "2026-11-19" ) ] )

    def rollback( self ): self.rolled_back = True


def _main( tmp_path, argv, pairs, provider, printed ):
    session = FakeSession()
    with patch.object( qv, "cohort_texts", return_value=pairs ):
        code = main( argv, printer=printed.append, session_factory=lambda: contextlib.nullcontext( session ),
                     provider_factory=lambda: provider, clock=iter( [ 0.0, 2.0, 5.0 ] * 3 ).__next__ )
    return code, session


def test_the_command_reads_read_only_prints_the_probe_and_writes_the_file( tmp_path ):
    out, printed = tmp_path / "v.json", []
    pairs = [ ( f"id{n}", f"q{n}" ) for n in range( 40 ) ]
    code, session = _main( tmp_path, [ "--out", str( out ) ], pairs, FakeProvider(), printed )
    assert code == 0 and session.statements[ 0 ] == "SET TRANSACTION READ ONLY" and session.rolled_back
    assert printed[ 0 ] == "probe: 20 texts in 2.00s, projected 4.0s for 40"
    assert printed[ 1 ].startswith( f"wrote {out}: 40 vectors, 0 rejects, model m" )
    header, vectors = load_side_file( str( out ) )
    assert len( vectors ) == 40 and header[ "facts" ][ "database" ] == "lupin_db_dev"


def test_probe_only_writes_nothing( tmp_path ):
    out, printed = tmp_path / "v.json", []
    code, _ = _main( tmp_path, [ "--out", str( out ), "--probe-only" ], [ ( "a", "q" ) ], FakeProvider(), printed )
    assert code == 0 and not out.exists() and printed == [ "probe: 1 texts in 2.00s, projected 2.0s for 1" ]


def test_a_rejected_ask_makes_the_exit_code_one_and_the_file_is_still_written( tmp_path ):
    out, printed = tmp_path / "v.json", []
    code, _ = _main( tmp_path, [ "--out", str( out ) ], [ ( "a", "" ), ( "b", "q" ) ], FakeProvider(), printed )
    assert code == 1 and out.exists()


def test_with_no_asks_the_probe_line_does_not_divide_by_zero( tmp_path ):
    printed = []
    code, _ = _main( tmp_path, [ "--out", str( tmp_path / "v.json" ), "--probe-only" ], [], FakeProvider(), printed )
    assert code == 0 and printed == [ "probe: 0 texts in 2.00s, projected 0.0s for 0" ]


def test_without_injected_factories_the_command_uses_get_db_and_the_real_provider_getter( tmp_path ):
    printed, session, opened = [], FakeSession(), []
    with patch.object( qv, "get_db", lambda: opened.append( "db" ) or contextlib.nullcontext( session ) ), \
         patch.object( qv, "get_embedding_provider", lambda: opened.append( "provider" ) or FakeProvider() ), \
         patch.object( qv, "cohort_texts", return_value=[ ( "a", "q" ) ] ):
        assert main( [ "--out", str( tmp_path / "v.json" ), "--probe-only" ], printer=printed.append ) == 0
    assert opened == [ "provider", "db" ]
