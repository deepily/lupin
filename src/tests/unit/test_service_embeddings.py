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
    one = se.CachedServiceEmbedder( path, embed=embed, encoder="e1" )
    assert one( "abc" ) == [ 3.0, 1.0 ] and one( "abc" ) == [ 3.0, 1.0 ]
    assert ( one.calls, one.hits, made ) == ( 1, 1, [ "abc" ] )
    one.flush()
    two = se.CachedServiceEmbedder( path, embed=embed, encoder="e1" )
    assert two( "abc" ) == [ 3.0, 1.0 ] and made == [ "abc" ] and two.calls == 0
    three = se.CachedServiceEmbedder( path, embed=embed, encoder="e2" )
    three( "abc" )
    assert made == [ "abc", "abc" ], "another encoder version must not read the old vector"


def test_a_failing_service_raises_the_named_error_and_keeps_the_vectors_already_made(tmp_path):
    path = str( tmp_path / "c.json" )
    def embed( text ):
        if text == "bad": raise RuntimeError( "saturated" )
        return [ 1.0 ]
    one = se.CachedServiceEmbedder( path, embed=embed, encoder="e1" )
    one( "good" )
    with pytest.raises( se.EmbeddingServiceUnavailable, match="after 1 calls: saturated" ):
        one( "bad" )
    assert len( json.load( open( path ) ) ) == 1


def test_the_defaults_are_the_live_extractors_embed_function_and_encoder_version(tmp_path, monkeypatch):
    monkeypatch.setattr( se, "default_embed", lambda text: [ 9.0 ] )
    monkeypatch.setattr( se, "encoder_version", lambda: "m:r" )
    one = se.CachedServiceEmbedder( str( tmp_path / "c.json" ) )
    assert one.encoder == "m:r" and one( "x" ) == [ 9.0 ]


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
    assert len( made ) == before and "0 service calls" in capsys.readouterr().out


FIXTURE = os.path.join( os.path.dirname( __file__ ), "fixtures", "episode_view", "synthetic-context-50.json" )


def er_fixture():
    return FIXTURE
