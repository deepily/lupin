"""
Unit tests for EmbeddingCacheRepository (normalized_text→embedding KV cache).

100% lines/branches/functions of embedding_cache_repository.py.
"""

import os
import sys

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.rest.db.repositories.embedding_cache_repository import EmbeddingCacheRepository
from cosa.rest.db.vector_store_models import EMBEDDING_DIM


def _vec( x=1.0 ):
    return [ x ] * EMBEDDING_DIM


def test_cache_has_and_get( db_session ):
    repo = EmbeddingCacheRepository( db_session )
    assert repo.has_cached_embedding( "hello world" ) is False
    assert repo.get_cached_embedding( "hello world" ) is None

    repo.cache_embedding( "hello world", _vec( 0.25 ) )
    db_session.flush()

    assert repo.has_cached_embedding( "hello world" ) is True
    got = repo.get_cached_embedding( "hello world" )
    assert got is not None and abs( got[ 0 ] - 0.25 ) < 1e-6


def test_get_miss_returns_none( db_session ):
    repo = EmbeddingCacheRepository( db_session )
    repo.cache_embedding( "present", _vec() )
    db_session.flush()
    assert repo.get_cached_embedding( "absent" ) is None


def test_get_null_embedding_returns_none( db_session ):
    repo = EmbeddingCacheRepository( db_session )
    repo.create( normalized_text="no_vec", embedding=None )
    db_session.flush()
    assert repo.get_cached_embedding( "no_vec" ) is None
