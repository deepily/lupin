"""Unit tests for semdup.body_vectors: the cut, the cache and the engine key."""
import json

import pytest

from cosa.repo.semdup import body_vectors as bv
from cosa.repo.semdup import extract as ex
from cosa.repo.symindex.candidates.errors import CandidateError, EMBEDDING_SHAPE

VOCAB = [ "alpha", "beta", "gamma", "delta", "epsilon", "zeta" ]


class FakeClient:
    """Embed a text as its vocabulary word counts, so unlike texts differ, and record each call."""

    def __init__( self, revision="r1", width=None ):
        self.calls    = []
        self.revision = revision
        self.width    = width

    def embed( self, texts, content_type, role ):
        self.calls.append( ( list( texts ), content_type, role ) )
        return [ [ float( t.count( w ) ) for w in VOCAB ] + ( [ 0.0 ] * self.width if self.width else [] ) for t in texts ]

    def info( self ):
        return { "engines": { "code": { "revision": self.revision, "model": "m" }, "prose": { "revision": "p" } } }


def definition( name, text ):
    """Build a definition record the way extract does."""
    return { "id": ex.definition_id( "new", "f.py", name, text ), "text": text }


def test_a_short_text_is_whole_and_a_long_one_is_cut_and_flagged():
    d = definition( "f", "alpha beta" )
    assert bv.body_text( d, 100 ) == ( "alpha beta", False )
    assert bv.body_text( d, 10 ) == ( "alpha beta", False )             # exactly the limit is whole
    assert bv.body_text( d, 5 ) == ( "alpha", True )


def test_a_cut_below_one_is_refused():
    with pytest.raises( ValueError, match="body_chars must be 1 or more" ):
        bv.body_text( definition( "f", "x" ), 0 )


def test_vectors_come_from_the_code_engine_with_the_document_role_for_every_definition(tmp_path):
    client = FakeClient()
    defs   = [ definition( "a", "alpha alpha beta" ), definition( "b", "gamma delta" ) ]
    out    = bv.ensure_vectors( defs, client, tmp_path, 1000 )
    assert out[ "vectors" ][ defs[ 0 ][ "id" ] ] == [ 2.0, 1.0, 0.0, 0.0, 0.0, 0.0 ]
    assert out[ "vectors" ][ defs[ 1 ][ "id" ] ] == [ 0.0, 0.0, 1.0, 1.0, 0.0, 0.0 ]
    assert out[ "embedded" ] == 2 and out[ "reused" ] == 0 and out[ "truncated" ] == []
    assert [ ( c[ 1 ], c[ 2 ] ) for c in client.calls ] == [ ( "code", "document" ) ]


def test_a_second_call_over_the_same_texts_makes_no_embed_call_and_returns_the_same_vectors(tmp_path):
    client = FakeClient()
    defs   = [ definition( "a", "alpha beta" ), definition( "b", "gamma" ) ]
    first  = bv.ensure_vectors( defs, client, tmp_path, 1000 )
    again  = bv.ensure_vectors( defs, client, tmp_path, 1000 )
    assert len( client.calls ) == 1 and again[ "vectors" ] == first[ "vectors" ]
    assert ( again[ "embedded" ], again[ "reused" ] ) == ( 0, 2 )


def test_only_new_text_is_embedded_on_a_later_run(tmp_path):
    client = FakeClient()
    bv.ensure_vectors( [ definition( "a", "alpha" ) ], client, tmp_path, 1000 )
    out = bv.ensure_vectors( [ definition( "a", "alpha" ), definition( "c", "zeta zeta" ) ], client, tmp_path, 1000 )
    assert client.calls[ 1 ][ 0 ] == [ "zeta zeta" ] and ( out[ "embedded" ], out[ "reused" ] ) == ( 1, 1 )


def test_a_text_shared_by_two_definitions_is_embedded_once(tmp_path):
    client = FakeClient()
    defs   = [ definition( "a", "alpha" ), { **definition( "b", "alpha" ), "id": "d-other" } ]
    out    = bv.ensure_vectors( defs, client, tmp_path, 1000 )
    assert client.calls[ 0 ][ 0 ] == [ "alpha" ] and out[ "vectors" ][ "d-other" ] == out[ "vectors" ][ defs[ 0 ][ "id" ] ]


def test_the_cut_text_is_what_is_embedded_and_cached_and_the_ids_cut_are_reported(tmp_path):
    client = FakeClient()
    d      = definition( "a", "alpha beta gamma" )
    out    = bv.ensure_vectors( [ d ], client, tmp_path, 5 )
    assert client.calls[ 0 ][ 0 ] == [ "alpha" ] and out[ "truncated" ] == [ d[ "id" ] ]
    assert out[ "vectors" ][ d[ "id" ] ] == [ 1.0, 0.0, 0.0, 0.0, 0.0, 0.0 ]


def test_vectors_cached_under_another_engine_revision_are_not_used(tmp_path):
    bv.ensure_vectors( [ definition( "a", "alpha" ) ], FakeClient( revision="r1" ), tmp_path, 1000 )
    second = FakeClient( revision="r2" )
    out    = bv.ensure_vectors( [ definition( "a", "alpha" ) ], second, tmp_path, 1000 )
    assert len( second.calls ) == 1 and out[ "embedded" ] == 1
    assert len( [ p for p in tmp_path.iterdir() if p.is_dir() ] ) == 2


def test_the_engine_tag_ignores_key_order_and_changes_with_the_block():
    class Reordered( FakeClient ):
        def info( self ): return { "engines": { "code": { "model": "m", "revision": "r1" } } }
    assert bv.engine_tag( Reordered() ) == bv.engine_tag( FakeClient() ) and bv.engine_tag( FakeClient( revision="r9" ) ) != bv.engine_tag( FakeClient() )
    assert len( bv.engine_tag( FakeClient() ) ) == 16


def test_cached_and_new_vectors_of_different_lengths_are_refused(tmp_path):
    bv.ensure_vectors( [ definition( "a", "alpha" ) ], FakeClient(), tmp_path, 1000 )
    with pytest.raises( CandidateError ) as caught:
        bv.ensure_vectors( [ definition( "a", "alpha" ), definition( "b", "beta" ) ], FakeClient( width=2 ), tmp_path, 1000 )
    assert caught.value.code == EMBEDDING_SHAPE


def test_the_cache_holds_one_complete_file_per_text_and_no_temporary_file(tmp_path):
    bv.ensure_vectors( [ definition( "a", "alpha beta" ) ], FakeClient(), tmp_path, 1000 )
    files = [ p for sub in tmp_path.iterdir() for p in sub.iterdir() ]
    assert len( files ) == 1 and files[ 0 ].suffix == ".json" and json.loads( files[ 0 ].read_text() ) == [ 1.0, 1.0, 0.0, 0.0, 0.0, 0.0 ]


def cached_file( tmp_path ):
    """Return the one cache file left after embedding a single text."""
    return [ p for sub in tmp_path.iterdir() for p in sub.iterdir() ][ 0 ]


@pytest.mark.parametrize( "damage", [ "{not json", "", "{\"a\": 1}", "[]", "[\"x\", 1.0]", "[true, false]", "null" ] )
def test_a_corrupt_or_wrong_shaped_cache_file_is_embedded_again_and_repaired( tmp_path, damage ):
    d = definition( "a", "alpha beta" )
    bv.ensure_vectors( [ d ], FakeClient(), tmp_path, 1000 )
    cached_file( tmp_path ).write_text( damage, encoding="utf-8" )
    client = FakeClient()
    out    = bv.ensure_vectors( [ d ], client, tmp_path, 1000 )
    assert len( client.calls ) == 1 and out[ "embedded" ] == 1 and out[ "vectors" ][ d[ "id" ] ] == [ 1.0, 1.0, 0.0, 0.0, 0.0, 0.0 ]
    assert json.loads( cached_file( tmp_path ).read_text() ) == [ 1.0, 1.0, 0.0, 0.0, 0.0, 0.0 ]
    assert len( bv.ensure_vectors( [ d ], client, tmp_path, 1000 )[ "vectors" ] ) == 1 and len( client.calls ) == 1


def test_an_unreadable_cache_file_is_embedded_again(tmp_path):
    d = definition( "a", "alpha" )
    bv.ensure_vectors( [ d ], FakeClient(), tmp_path, 1000 )
    cached_file( tmp_path ).write_bytes( b"\xff\xfe\x00" )                                   # not valid utf-8
    client = FakeClient()
    assert bv.ensure_vectors( [ d ], client, tmp_path, 1000 )[ "embedded" ] == 1 and len( client.calls ) == 1


def test_integers_in_a_cached_vector_are_read_as_floats(tmp_path):
    d = definition( "a", "alpha" )
    bv.ensure_vectors( [ d ], FakeClient(), tmp_path, 1000 )
    cached_file( tmp_path ).write_text( "[1, 0, 0, 0, 0, 0]", encoding="utf-8" )
    out = bv.ensure_vectors( [ d ], FakeClient(), tmp_path, 1000 )
    assert out[ "reused" ] == 1 and out[ "vectors" ][ d[ "id" ] ] == [ 1.0, 0.0, 0.0, 0.0, 0.0, 0.0 ] and all( isinstance( x, float ) for x in out[ "vectors" ][ d[ "id" ] ] )


def test_two_writes_of_the_same_text_use_different_temporary_names_that_carry_the_process_id(tmp_path, monkeypatch):
    sources = []
    real    = bv.os.replace
    monkeypatch.setattr( bv.os, "replace", lambda src, dst: ( sources.append( str( src ) ), real( src, dst ) )[ 1 ] )
    bv._write( tmp_path, "abc", [ 1.0 ] )
    bv._write( tmp_path, "abc", [ 2.0 ] )
    assert len( set( sources ) ) == 2 and all( f".{bv.os.getpid()}." in s and s.endswith( ".tmp" ) for s in sources )
    assert json.loads( ( tmp_path / "abc.json" ).read_text() ) == [ 2.0 ] and sorted( p.name for p in tmp_path.iterdir() ) == [ "abc.json" ]
