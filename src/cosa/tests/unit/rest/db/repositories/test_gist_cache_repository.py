"""
Unit tests for GistCacheRepository (relational, no vector column).

100% lines/branches/functions of gist_cache_repository.py.
"""

import os
import sys

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.rest.db.repositories.gist_cache_repository import GistCacheRepository


def test_cache_and_two_tier_lookup( db_session ):
    repo = GistCacheRepository( db_session )
    repo.cache_gist(
        question_verbatim="What is the capital of France?",
        question_gist="capital france",
        question_normalized="what is the capital of france",
        created_date="2026-07-01", access_count=3, last_accessed="2026-07-01",
    )
    db_session.flush()

    assert repo.get_by_verbatim( "What is the capital of France?" ).question_gist == "capital france"
    assert repo.get_by_normalized( "what is the capital of france" ).question_gist == "capital france"
    # verbatim tier wins first
    assert repo.get_cached_gist( question_verbatim="What is the capital of France?" ) == "capital france"
    # normalized tier fallback
    assert repo.get_cached_gist( question_normalized="what is the capital of france" ) == "capital france"
    assert repo.has_cached_gist( question_verbatim="What is the capital of France?" ) is True


def test_lookup_misses_return_none( db_session ):
    repo = GistCacheRepository( db_session )
    assert repo.get_by_verbatim( "nope" ) is None
    assert repo.get_by_normalized( "nope" ) is None
    assert repo.get_cached_gist( question_verbatim="nope", question_normalized="nope" ) is None
    assert repo.get_cached_gist() is None                     # neither key supplied
    assert repo.has_cached_gist( question_verbatim="nope" ) is False


def test_normalized_only_when_verbatim_absent( db_session ):
    repo = GistCacheRepository( db_session )
    repo.cache_gist( question_verbatim="V", question_gist="G", question_normalized="n" )
    db_session.flush()
    # verbatim miss falls through to the normalized tier
    assert repo.get_cached_gist( question_verbatim="other", question_normalized="n" ) == "G"


def test_get_statistics( db_session ):
    repo = GistCacheRepository( db_session )
    assert repo.get_statistics() == { "total_entries": 0, "total_access_count": 0 }
    repo.cache_gist( question_verbatim="a", question_gist="g1", access_count=2 )
    repo.cache_gist( question_verbatim="b", question_gist="g2", access_count=5 )
    db_session.flush()
    assert repo.get_statistics() == { "total_entries": 2, "total_access_count": 7 }
