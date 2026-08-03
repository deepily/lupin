"""
Unit tests for QuestionEmbeddingRepository (exact-match KV cache).

100% lines/branches/functions of question_embedding_repository.py.
"""

import os
import sys

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.rest.db.repositories.question_embedding_repository import QuestionEmbeddingRepository
from cosa.rest.db.vector_store_models import EMBEDDING_DIM


def _vec( x=1.0 ):
    return [ x ] * EMBEDDING_DIM


def test_add_has_and_get( db_session ):
    repo = QuestionEmbeddingRepository( db_session )
    assert repo.has( "q1" ) is False
    assert repo.get_embedding( "q1" ) is None

    repo.add_embedding( "q1", _vec( 0.5 ) )
    db_session.flush()

    assert repo.has( "q1" ) is True
    got = repo.get_embedding( "q1" )
    assert got is not None and len( got ) == EMBEDDING_DIM
    assert abs( got[ 0 ] - 0.5 ) < 1e-6


def test_get_embedding_miss_returns_none( db_session ):
    repo = QuestionEmbeddingRepository( db_session )
    repo.add_embedding( "present", _vec() )
    db_session.flush()
    assert repo.get_embedding( "absent" ) is None


def test_get_embedding_null_embedding_returns_none( db_session ):
    repo = QuestionEmbeddingRepository( db_session )
    repo.create( question="no_vec", embedding=None )
    db_session.flush()
    assert repo.get_embedding( "no_vec" ) is None
