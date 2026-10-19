"""
Real-database tests for the two exact-key embedding readers and their shared lookup.

get_cached_embedding reads by normalized text and get_embedding by question. Both return the stored
vector as a list of floats, or None on a miss or a null vector, and only an exact key counts.
"""
import pytest

from cosa.rest.db.repositories.embedding_cache_repository import EmbeddingCacheRepository
from cosa.rest.db.repositories.question_embedding_repository import QuestionEmbeddingRepository
from cosa.rest.db.repositories.vector_search import embedding_where
from cosa.rest.db.vector_store_models import EMBEDDING_DIM, EmbeddingCache, QuestionEmbedding


def _vec( x ):
    return [ x ] * EMBEDDING_DIM


def test_the_cache_reader_returns_the_stored_vector_for_the_exact_text_only( db_session ):
    repo = EmbeddingCacheRepository( db_session )
    repo.cache_embedding( "hello world", _vec( 0.25 ) )
    repo.cache_embedding( "hello", _vec( 0.75 ) )
    db_session.flush()
    got = repo.get_cached_embedding( "hello world" )
    assert isinstance( got, list ) and len( got ) == EMBEDDING_DIM and abs( got[ 0 ] - 0.25 ) < 1e-6
    assert abs( repo.get_cached_embedding( "hello" )[ 0 ] - 0.75 ) < 1e-6
    assert [ repo.get_cached_embedding( t ) for t in ( "Hello World", "hello world ", "" ) ] == [ None ] * 3


def test_the_question_reader_returns_the_stored_vector_for_the_exact_question_only( db_session ):
    repo = QuestionEmbeddingRepository( db_session )
    repo.add_embedding( "what time is it", _vec( 0.125 ) )
    repo.add_embedding( "what time", _vec( 0.5 ) )
    db_session.flush()
    got = repo.get_embedding( "what time is it" )
    assert isinstance( got, list ) and len( got ) == EMBEDDING_DIM and abs( got[ 0 ] - 0.125 ) < 1e-6
    assert abs( repo.get_embedding( "what time" )[ 0 ] - 0.5 ) < 1e-6
    assert [ repo.get_embedding( q ) for q in ( "What Time Is It", "what time is it?", "" ) ] == [ None ] * 3


def test_a_row_with_a_null_vector_reads_as_none_in_both_readers( db_session ):
    EmbeddingCacheRepository( db_session ).create( normalized_text="nv", embedding=None )
    QuestionEmbeddingRepository( db_session ).create( question="nv", embedding=None )
    db_session.flush()
    assert EmbeddingCacheRepository( db_session ).get_cached_embedding( "nv" ) is None
    assert QuestionEmbeddingRepository( db_session ).get_embedding( "nv" ) is None


def test_the_shared_lookup_reads_by_whatever_model_and_column_it_is_given( db_session ):
    EmbeddingCacheRepository( db_session ).cache_embedding( "key", _vec( 0.5 ) )
    QuestionEmbeddingRepository( db_session ).add_embedding( "other", _vec( 0.1 ) )
    db_session.flush()
    assert abs( embedding_where( db_session, EmbeddingCache, EmbeddingCache.normalized_text, "key" )[ 0 ] - 0.5 ) < 1e-6
    assert abs( embedding_where( db_session, QuestionEmbedding, QuestionEmbedding.question, "other" )[ 0 ] - 0.1 ) < 1e-6
    assert embedding_where( db_session, EmbeddingCache, EmbeddingCache.normalized_text, "other" ) is None
