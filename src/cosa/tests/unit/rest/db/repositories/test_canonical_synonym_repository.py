"""
Unit tests for CanonicalSynonymRepository (exact-match lookups; 3 stored vectors).

100% lines/branches/functions of canonical_synonym_repository.py.
"""

import os
import sys
from datetime import datetime

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.rest.db.repositories.canonical_synonym_repository import CanonicalSynonymRepository
from cosa.rest.db.vector_store_models import EMBEDDING_DIM


def _vec( x=1.0 ):
    return [ x ] * EMBEDDING_DIM


def _add( repo, id, snapshot_id, verbatim, normalized, gist ):
    return repo.add_synonym(
        id=id, snapshot_id=snapshot_id, question_verbatim=verbatim,
        question_normalized=normalized, question_gist=gist,
        embedding_verbatim=_vec( 0.1 ), embedding_normalized=_vec( 0.2 ),
        embedding_gist=_vec( 0.3 ), confidence_score=95.0, usage_count=1,
        last_matched=datetime( 2026, 7, 1 ), created_date=datetime( 2026, 7, 1 ),
        source="test",
    )


def test_add_and_find_exact( db_session ):
    repo = CanonicalSynonymRepository( db_session )
    _add( repo, "id1", "snap1", "How old are you?", "how old are you", "age query" )
    db_session.flush()

    assert repo.find_exact_verbatim( "How old are you?" ) == "snap1"
    assert repo.find_exact_normalized( "how old are you" ) == "snap1"
    assert repo.find_exact_gist( "age query" ) == "snap1"


def test_find_exact_misses_return_none( db_session ):
    repo = CanonicalSynonymRepository( db_session )
    assert repo.find_exact_verbatim( "x" ) is None
    assert repo.find_exact_normalized( "x" ) is None
    assert repo.find_exact_gist( "x" ) is None


def test_delete_by_snapshot_id( db_session ):
    repo = CanonicalSynonymRepository( db_session )
    _add( repo, "id1", "snapA", "v1", "n1", "g1" )
    _add( repo, "id2", "snapA", "v2", "n2", "g2" )
    _add( repo, "id3", "snapB", "v3", "n3", "g3" )
    db_session.flush()

    deleted = repo.delete_by_snapshot_id( "snapA" )
    assert deleted == 2
    assert repo.find_exact_verbatim( "v1" ) is None
    assert repo.find_exact_verbatim( "v3" ) == "snapB"
    assert repo.delete_by_snapshot_id( "missing" ) == 0


def test_get_statistics( db_session ):
    repo = CanonicalSynonymRepository( db_session )
    assert repo.get_statistics() == { "total_synonyms": 0, "total_usage_count": 0 }
    _add( repo, "id1", "s1", "v1", "n1", "g1" )
    _add( repo, "id2", "s2", "v2", "n2", "g2" )
    db_session.flush()
    stats = repo.get_statistics()
    assert stats[ "total_synonyms" ] == 2 and stats[ "total_usage_count" ] == 2


def test_add_synonym_defaults( db_session ):
    repo = CanonicalSynonymRepository( db_session )
    row = repo.add_synonym(
        id="d1", snapshot_id="s", question_verbatim="v", question_normalized="n", question_gist="g",
    )
    db_session.flush()
    assert row.confidence_score == 100.0 and row.usage_count == 0 and row.source == "runtime"
    assert row.embedding_verbatim is None
