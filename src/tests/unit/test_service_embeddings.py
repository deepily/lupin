"""Unit tests for the replay's cached service embedder and the neighbour cosine recorder."""

import json
import uuid
from datetime import datetime, timezone

import os

import pytest

from cosa.agents.principle_learner import extractor_store
from cosa.research.preference_replay import extractor_replay as er
from cosa.research.preference_replay import service_embeddings as se
from cosa.research.preference_replay.scratch_db import scratch_session
from cosa.rest.postgres_models import PreferencePrinciple


def test_the_cache_key_changes_with_the_text_and_with_the_encoder():
    assert se.cache_key( "a", "e1" ) != se.cache_key( "b", "e1" ) and se.cache_key( "a", "e1" ) != se.cache_key( "a", "e2" )
    assert se.cache_key( "a", "e1" ) == se.cache_key( "a", "e1" ) and len( se.cache_key( "a", "e1" ) ) == 64


def test_a_repeated_text_is_served_from_the_cache_and_a_new_embedder_reads_the_file(tmp_path):
    path, made = str( tmp_path / "c.json" ), []
    def embed( text ):
        made.append( text )
        return [ float( len( text ) ), 1.0 ]
    one = se.CachedServiceEmbedder( path, embed=embed, encoder="e1", dimension=2 )
    assert one( "abc" ) == [ 3.0, 1.0 ] and one( "abc" ) == [ 3.0, 1.0 ]
    assert ( one.calls, one.hits, made ) == ( 1, 1, [ se.SENTINEL_TEXT, "abc" ] )
    one.flush()
    two = se.CachedServiceEmbedder( path, embed=embed, encoder="e1", dimension=2 )
    assert two( "abc" ) == [ 3.0, 1.0 ] and made == [ se.SENTINEL_TEXT, "abc", se.SENTINEL_TEXT ] and two.calls == 0
    three = se.CachedServiceEmbedder( path, embed=embed, encoder="e2", dimension=2 )
    three( "abc" )
    assert made.count( "abc" ) == 2, "another encoder version must not read the old vector"


def test_a_failing_service_raises_the_named_error_and_keeps_the_vectors_already_made(tmp_path):
    path = str( tmp_path / "c.json" )
    def embed( text ):
        if text == "bad": raise RuntimeError( "saturated" )
        return [ 1.0 ]
    one = se.CachedServiceEmbedder( path, embed=embed, encoder="e1", dimension=1 )
    one( "good" )
    with pytest.raises( se.EmbeddingServiceUnavailable, match="after 1 calls: saturated" ):
        one( "bad" )
    assert se.cache_key( "good", "e1" ) in json.load( open( path ) )


def test_a_service_that_is_down_at_construction_raises_the_named_error_and_rewrites_a_loaded_cache_whole(tmp_path):
    path = str( tmp_path / "c.json" )
    def down( text ): raise ConnectionError( "refused" )
    with pytest.raises( se.EmbeddingServiceUnavailable, match="after 0 calls: refused" ):
        se.CachedServiceEmbedder( path, embed=down, encoder="e1", dimension=1 )
    assert not os.path.exists( path )
    json.dump( { "k": [ 1.0 ] }, open( path, "w" ) )
    with pytest.raises( se.EmbeddingServiceUnavailable ):
        se.CachedServiceEmbedder( path, embed=down, encoder="e1", dimension=1 )
    assert json.load( open( path ) ) == { "k": [ 1.0 ] }


def test_a_vector_of_the_wrong_length_is_refused_and_never_cached(tmp_path):
    path = str( tmp_path / "c.json" )
    def embed( text ): return [ 1.0 ] * ( 3 if text == "wide" else 2 )
    one = se.CachedServiceEmbedder( path, embed=embed, encoder="e1", dimension=2 )
    with pytest.raises( se.WrongVectorWidth, match="returned 3 numbers, expected 2" ):
        one( "wide" )
    assert se.cache_key( "wide", "e1" ) not in one.vectors
    with pytest.raises( se.WrongVectorWidth ):
        se.CachedServiceEmbedder( path, embed=lambda text: [ 1.0 ] * 5, encoder="e1", dimension=2 )


def test_the_default_width_is_the_stored_column_width(tmp_path):
    one = se.CachedServiceEmbedder( str( tmp_path / "c.json" ), embed=lambda text: [ 1.0 ] * se.EMBEDDING_DIM, encoder="e1" )
    assert one.dimension == se.EMBEDDING_DIM == 768
    with pytest.raises( se.WrongVectorWidth ):
        se.CachedServiceEmbedder( str( tmp_path / "d.json" ), embed=lambda text: [ 1.0, 2.0 ], encoder="e1" )


def test_the_cache_keeps_a_sentinel_vector_and_a_cache_filled_by_another_model_is_rejected(tmp_path):
    path = str( tmp_path / "c.json" )
    one = se.CachedServiceEmbedder( path, embed=lambda text: [ 1.0, 0.0 ], encoder="e1", dimension=2 )
    one.flush()
    assert json.load( open( path ) )[ se.SENTINEL_KEY ] == [ 1.0, 0.0 ]
    se.CachedServiceEmbedder( path, embed=lambda text: [ 2.0, 0.01 ], encoder="e1", dimension=2 )
    with pytest.raises( se.CacheSentinelMismatch, match="another model: probe cosine 0.7071" ):
        se.CachedServiceEmbedder( path, embed=lambda text: [ 1.0, 1.0 ], encoder="e1", dimension=2 )


def test_a_cache_file_with_no_sentinel_is_stamped_with_the_fresh_probe(tmp_path):
    path = str( tmp_path / "c.json" )
    json.dump( { "old": [ 5.0, 5.0 ] }, open( path, "w" ) )
    one = se.CachedServiceEmbedder( path, embed=lambda text: [ 0.0, 1.0 ], encoder="e1", dimension=2 )
    one.flush()
    assert json.load( open( path ) ) == { "old": [ 5.0, 5.0 ], se.SENTINEL_KEY: [ 0.0, 1.0 ] }


def test_the_defaults_are_the_live_extractors_embed_function_and_encoder_version(tmp_path, monkeypatch):
    monkeypatch.setattr( se, "default_embed", lambda text: [ 9.0 ] * se.EMBEDDING_DIM )
    monkeypatch.setattr( se, "encoder_version", lambda: "m:r" )
    one = se.CachedServiceEmbedder( str( tmp_path / "c.json" ) )
    assert one.encoder == "m:r" and one( "x" ) == [ 9.0 ] * se.EMBEDDING_DIM


def test_the_recorder_logs_one_cosine_per_neighbour_returns_the_result_unchanged_and_restores_the_function():
    original = extractor_store.fetch_neighbours
    with scratch_session() as session:
        stamp = datetime( 2026, 1, 1, tzinfo=timezone.utc )
        for vector in ( [ 1.0 ] + [ 0.0 ] * 767, [ 0.0, 1.0 ] + [ 0.0 ] * 766 ):
            session.add( PreferencePrinciple( id=uuid.uuid4(), owner_id="o", kind="decision", dimension="d", statement=str( vector[ :2 ] ), scope="global",
                                              encoder_version="e", extractor_version="x", embedding=vector, created_at=stamp ) )
        session.flush()
        log = []
        query = [ 1.0 ] + [ 0.0 ] * 767
        with se.record_neighbour_cosines( log ):
            found = extractor_store.fetch_neighbours( session, "o", "e", [ query ], datetime( 2026, 2, 1, tzinfo=timezone.utc ) )
        assert len( found ) == 2 and sorted( round( c, 3 ) for c in log ) == [ 0.0, 1.0 ]
    assert extractor_store.fetch_neighbours is original
    with pytest.raises( ValueError ):
        with se.record_neighbour_cosines( [] ):
            raise ValueError( "boom" )
    assert extractor_store.fetch_neighbours is original


def test_main_with_service_embeddings_uses_the_cache_prints_totals_and_writes_the_cosines(tmp_path, capsys, monkeypatch):
    made = []
    def embed( text ):
        made.append( text )
        return er.stand_in_vector( text )
    monkeypatch.setattr( se, "default_embed", embed )
    monkeypatch.setattr( se, "encoder_version", lambda: "enc:test" )
    out, cos = tmp_path / "p.json", tmp_path / "cos.json"
    argv = [ "--export", er_fixture(), "--out", str( out ), "--dry-run", "--lag-seconds", "0", "--embeddings", "service", "--neighbour-cosines-out", str( cos ) ]
    assert er.main( argv ) == 0
    first = capsys.readouterr().out
    assert "embeddings: " in first and "encoder enc:test" in first and "extractor totals: " in first and "off-vocabulary" in first
    assert made and isinstance( json.loads( cos.read_text() ), list ) and ( tmp_path / "p.json.embeddings.json" ).exists()
    before = len( made )
    assert er.main( argv ) == 0
    assert made[ before: ] == [ se.SENTINEL_TEXT ] and "0 service calls" in capsys.readouterr().out, "a rerun makes the one probe call and no other"


FIXTURE = os.path.join( os.path.dirname( __file__ ), "fixtures", "episode_view", "synthetic-context-50.json" )


def er_fixture():
    return FIXTURE
