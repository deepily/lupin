"""
Unit tests for SolutionSnapshotRepository (question + code + solution ANN dot).

100% lines/branches/functions of solution_snapshot_repository.py.
"""

import os
import sys

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.rest.db.repositories.solution_snapshot_repository import SolutionSnapshotRepository
from cosa.rest.db.vector_store_models import EMBEDDING_DIM


def _vec( *first ):
    v = list( first ) + [ 0.0 ] * ( EMBEDDING_DIM - len( first ) )
    return v[ :EMBEDDING_DIM ]


def test_upsert_insert_then_update( db_session ):
    repo = SolutionSnapshotRepository( db_session )
    created = repo.upsert_snapshot( "h1", question="q1", answer="a1", question_embedding=_vec( 1.0 ) )
    db_session.flush()
    assert created.question == "q1"

    updated = repo.upsert_snapshot( "h1", answer="a2" )
    db_session.flush()
    assert updated.id_hash == "h1" and updated.answer == "a2" and updated.question == "q1"
    assert repo.count() == 1


def test_get_and_delete( db_session ):
    repo = SolutionSnapshotRepository( db_session )
    repo.upsert_snapshot( "h1", question="q", question_embedding=_vec( 1.0 ) )
    db_session.flush()
    assert repo.get_snapshot_by_id( "h1" ) is not None
    assert repo.delete_snapshot( "h1" ) is True
    assert repo.get_snapshot_by_id( "h1" ) is None
    assert repo.delete_snapshot( "h1" ) is False


def test_search_by_question_orders_and_excludes( db_session ):
    repo = SolutionSnapshotRepository( db_session )
    repo.upsert_snapshot( "near", question="a", question_embedding=_vec( 1.0, 0.0 ) )
    repo.upsert_snapshot( "mid",  question="b", question_embedding=_vec( 0.9, 0.0 ) )
    repo.upsert_snapshot( "low",  question="c", question_embedding=_vec( 0.0, 1.0 ) )
    db_session.flush()

    hits = repo.get_snapshots_by_question( _vec( 1.0, 0.0 ), threshold=85.0, limit=7 )
    assert [ e.id_hash for _, e in hits ] == [ "near", "mid" ]     # 100%, 90% pass; 0% fails

    excl = repo.get_snapshots_by_question( _vec( 1.0, 0.0 ), threshold=85.0, limit=7, exclude_id_hash="near" )
    assert [ e.id_hash for _, e in excl ] == [ "mid" ]


def test_search_by_code_and_solution( db_session ):
    repo = SolutionSnapshotRepository( db_session )
    repo.upsert_snapshot( "h1", code_embedding=_vec( 1.0, 0.0 ), solution_embedding=_vec( 0.0, 1.0 ) )
    repo.upsert_snapshot( "h2", code_embedding=_vec( 0.0, 1.0 ), solution_embedding=_vec( 1.0, 0.0 ) )
    db_session.flush()

    code_hits = repo.get_snapshots_by_code_similarity( _vec( 1.0, 0.0 ), threshold=90.0 )
    assert [ e.id_hash for _, e in code_hits ] == [ "h1" ]

    sol_hits = repo.get_snapshots_by_solution_similarity( _vec( 1.0, 0.0 ), threshold=90.0 )
    assert [ e.id_hash for _, e in sol_hits ] == [ "h2" ]


def test_get_gists_distinct( db_session ):
    repo = SolutionSnapshotRepository( db_session )
    repo.upsert_snapshot( "h1", question_gist="g1" )
    repo.upsert_snapshot( "h2", question_gist="g1" )
    repo.upsert_snapshot( "h3", question_gist="g2" )
    repo.upsert_snapshot( "h4", question_gist=None )
    db_session.flush()
    assert sorted( repo.get_gists() ) == [ "g1", "g2" ]


def test_get_stats( db_session ):
    repo = SolutionSnapshotRepository( db_session )
    assert repo.get_stats() == { "total_snapshots": 0 }
    repo.upsert_snapshot( "h1" )
    repo.upsert_snapshot( "h2" )
    db_session.flush()
    assert repo.get_stats() == { "total_snapshots": 2 }
