"""
Unit tests for QueryLogRepository (write-only telemetry; unsearched vectors).

100% lines/branches/functions of query_log_repository.py.
"""

import os
import sys
from datetime import datetime

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.rest.db.repositories.query_log_repository import QueryLogRepository
from cosa.rest.db.vector_store_models import EMBEDDING_DIM


def _vec( x=1.0 ):
    return [ x ] * EMBEDDING_DIM


def test_log_query_full_row( db_session ):
    repo = QueryLogRepository( db_session )
    row = repo.log_query(
        id="q1", query_verbatim="hi", query_normalized="hi", query_gist="greeting",
        user_id="u1", session_id="s1", input_type="voice",
        timestamp=datetime( 2026, 7, 1, 10, 0, 0 ),
        embedding_verbatim=_vec( 0.1 ), embedding_normalized=_vec( 0.2 ), embedding_gist=_vec( 0.3 ),
        matched_snapshot_id="snap1", match_type="verbatim", match_confidence=0.9,
        processing_time_ms=42, user_satisfaction="good",
        normalization_version="v2", gist_model_version="g1",
        cache_hit_verbatim=True, cache_hit_normalized=False, cache_hit_gist=True,
    )
    db_session.flush()
    got = repo.get_by_id( "q1" )
    assert got.query_verbatim == "hi" and got.normalization_version == "v2"
    assert got.cache_hit_verbatim is True and got.processing_time_ms == 42


def test_log_query_minimal_defaults( db_session ):
    repo = QueryLogRepository( db_session )
    repo.log_query( id="q2", query_verbatim="a", query_normalized="a", query_gist="a", user_id="u" )
    db_session.flush()
    got = repo.get_by_id( "q2" )
    assert got.session_id == "unknown" and got.input_type == "api"
    assert got.cache_hit_verbatim is False and got.embedding_gist is None


def test_get_recent_queries_ordering_and_filter( db_session ):
    repo = QueryLogRepository( db_session )
    repo.log_query( id="a", query_verbatim="a", query_normalized="a", query_gist="a",
                    user_id="u1", timestamp=datetime( 2026, 7, 1, 9, 0 ) )
    repo.log_query( id="b", query_verbatim="b", query_normalized="b", query_gist="b",
                    user_id="u1", timestamp=datetime( 2026, 7, 1, 11, 0 ) )
    repo.log_query( id="c", query_verbatim="c", query_normalized="c", query_gist="c",
                    user_id="u2", timestamp=datetime( 2026, 7, 1, 10, 0 ) )
    db_session.flush()

    recent = repo.get_recent_queries( limit=10 )
    assert [ r.id for r in recent ] == [ "b", "c", "a" ]        # newest first
    assert len( repo.get_recent_queries( limit=1 ) ) == 1
    u1 = repo.get_recent_queries( user_id="u1" )
    assert [ r.id for r in u1 ] == [ "b", "a" ]


def test_cache_hit_stats_empty( db_session ):
    repo = QueryLogRepository( db_session )
    assert repo.get_cache_hit_stats() == {
        "total_queries": 0, "verbatim_hit_rate": 0.0,
        "normalized_hit_rate": 0.0, "gist_hit_rate": 0.0,
    }


def test_cache_hit_stats_rates_and_since( db_session ):
    repo = QueryLogRepository( db_session )
    repo.log_query( id="a", query_verbatim="a", query_normalized="a", query_gist="a", user_id="u",
                    timestamp=datetime( 2026, 7, 1, 8, 0 ), cache_hit_verbatim=True, cache_hit_gist=True )
    repo.log_query( id="b", query_verbatim="b", query_normalized="b", query_gist="b", user_id="u",
                    timestamp=datetime( 2026, 7, 1, 12, 0 ), cache_hit_verbatim=True, cache_hit_normalized=True )
    db_session.flush()

    stats = repo.get_cache_hit_stats()
    assert stats[ "total_queries" ] == 2
    assert stats[ "verbatim_hit_rate" ] == 1.0
    assert stats[ "normalized_hit_rate" ] == 0.5
    assert stats[ "gist_hit_rate" ] == 0.5

    # `since` window drops the earlier row.
    since_stats = repo.get_cache_hit_stats( since=datetime( 2026, 7, 1, 10, 0 ) )
    assert since_stats[ "total_queries" ] == 1
    assert since_stats[ "normalized_hit_rate" ] == 1.0
