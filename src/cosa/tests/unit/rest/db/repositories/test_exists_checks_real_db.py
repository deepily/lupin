"""
Real-database tests for the existence checks of the vector-store repositories.

Three repositories answer "is there a row?" by a different column. They share one query, so these
tests pin the answers per column: present, absent, and only an exact match counts.
"""
from cosa.rest.db.repositories.base import BaseRepository
from cosa.rest.db.repositories.embedding_cache_repository import EmbeddingCacheRepository
from cosa.rest.db.repositories.prediction_decision_repository import PredictionDecisionRepository
from cosa.rest.db.repositories.question_embedding_repository import QuestionEmbeddingRepository
from cosa.rest.db.vector_store_models import EMBEDDING_DIM, EmbeddingCache, QuestionEmbedding


def _vec( x=0.5 ):
    return [ x ] * EMBEDDING_DIM


def test_the_embedding_cache_check_matches_the_whole_text_only( db_session ):
    repo = EmbeddingCacheRepository( db_session )
    repo.cache_embedding( "hello world", _vec() )
    db_session.flush()
    assert repo.has_cached_embedding( "hello world" ) is True
    assert [ repo.has_cached_embedding( t ) for t in ( "hello", "hello world!", "Hello World", "" ) ] == [ False ] * 4


def test_the_question_embedding_check_matches_the_whole_question_only( db_session ):
    repo = QuestionEmbeddingRepository( db_session )
    repo.add_embedding( "what time is it", _vec() )
    db_session.flush()
    assert repo.has( "what time is it" ) is True
    assert [ repo.has( q ) for q in ( "what time", "what time is it?", "What Time Is It", "" ) ] == [ False ] * 4


def test_the_prediction_decision_check_agrees_with_the_inherited_check( db_session ):
    repo = PredictionDecisionRepository( db_session )
    repo.add_decision(
        id="d-exists", question="q", category="permission", decision_value="yes",
        ratification_state="pending", question_embedding=_vec(), created_at="2026-07-01",
        data_origin="organic", response_type="yes_no",
    )
    db_session.flush()
    for key in ( "d-exists", "d-missing", "D-EXISTS", "d-exist", "" ):
        assert repo.exists( key ) is BaseRepository.exists( repo, key ), key
    assert repo.exists( "d-exists" ) is True and repo.exists( "d-missing" ) is False


def test_the_prediction_decision_repository_uses_the_inherited_check_not_its_own():
    assert "exists" not in vars( PredictionDecisionRepository )
    assert PredictionDecisionRepository.exists is BaseRepository.exists


def test_the_shared_query_checks_any_column_it_is_given( db_session ):
    repo = QuestionEmbeddingRepository( db_session )
    row = repo.add_embedding( "alpha", _vec() )
    db_session.flush()
    assert repo._exists_where( QuestionEmbedding.question, "alpha" ) is True
    assert repo._exists_where( QuestionEmbedding.question, "beta" ) is False
    assert repo._exists_where( QuestionEmbedding.id, row.id ) is True
    cache = EmbeddingCacheRepository( db_session )
    assert cache._exists_where( EmbeddingCache.normalized_text, "alpha" ) is False
