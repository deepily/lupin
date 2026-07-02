"""
Unit tests for PredictionDecisionRepository (question_embedding ANN, HNSW dot).

100% lines/branches/functions of prediction_decision_repository.py.
"""

import os
import sys

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.rest.db.repositories.prediction_decision_repository import PredictionDecisionRepository
from cosa.rest.db.vector_store_models import EMBEDDING_DIM


def _vec( *first ):
    v = list( first ) + [ 0.0 ] * ( EMBEDDING_DIM - len( first ) )
    return v[ :EMBEDDING_DIM ]


def _add( repo, id, emb, category="permission", data_origin="organic", response_type="yes_no" ):
    return repo.add_decision(
        id=id, question=f"q_{id}", category=category, decision_value="yes",
        ratification_state="pending", question_embedding=emb,
        created_at="2026-07-01", data_origin=data_origin, response_type=response_type,
    )


def test_add_and_exists( db_session ):
    repo = PredictionDecisionRepository( db_session )
    assert repo.exists( "d1" ) is False
    _add( repo, "d1", _vec( 1.0 ) )
    db_session.flush()
    assert repo.exists( "d1" ) is True
    assert repo.get_by_id( "d1" ).decision_value == "yes"


def test_find_similar_orders_and_thresholds( db_session ):
    repo = PredictionDecisionRepository( db_session )
    _add( repo, "near", _vec( 1.0, 0.0 ) )      # dot 1.0 → 100%
    _add( repo, "mid",  _vec( 0.5, 0.0 ) )      # dot 0.5 → 50%
    _add( repo, "far",  _vec( 0.0, 1.0 ) )      # dot 0.0 → 0%
    db_session.flush()

    # threshold 0.75 → only 'near' (>=75%) survives.
    hits = repo.find_similar( _vec( 1.0, 0.0 ), limit=5, threshold=0.75 )
    assert [ e.id for _, e in hits ] == [ "near" ]
    assert abs( hits[ 0 ][ 0 ] - 100.0 ) < 1e-6

    # threshold 0.0 → all three, strongest dot first.
    hits = repo.find_similar( _vec( 1.0, 0.0 ), limit=5, threshold=0.0 )
    assert [ e.id for _, e in hits ] == [ "near", "mid", "far" ]


def test_find_similar_scalar_filters( db_session ):
    repo = PredictionDecisionRepository( db_session )
    _add( repo, "p1", _vec( 1.0 ), category="permission", data_origin="organic", response_type="yes_no" )
    _add( repo, "c1", _vec( 1.0 ), category="confirmation", data_origin="synthetic", response_type="multiple_choice" )
    db_session.flush()

    only_perm = repo.find_similar( _vec( 1.0 ), threshold=0.0, category="permission" )
    assert [ e.id for _, e in only_perm ] == [ "p1" ]

    by_origin = repo.find_similar( _vec( 1.0 ), threshold=0.0, data_origin="synthetic" )
    assert [ e.id for _, e in by_origin ] == [ "c1" ]

    by_type = repo.find_similar( _vec( 1.0 ), threshold=0.0, response_type="yes_no" )
    assert [ e.id for _, e in by_type ] == [ "p1" ]


def test_find_similar_clamps_to_100( db_session ):
    repo = PredictionDecisionRepository( db_session )
    _add( repo, "big", _vec( 5.0, 0.0 ) )       # dot 25 → 2500% → clamped to 100
    db_session.flush()
    hits = repo.find_similar( _vec( 5.0, 0.0 ), threshold=0.0 )
    assert hits[ 0 ][ 0 ] == 100.0


def test_update_ratification_state( db_session ):
    repo = PredictionDecisionRepository( db_session )
    _add( repo, "d1", _vec( 1.0 ) )
    db_session.flush()
    updated = repo.update_ratification_state( "d1", "ratified" )
    assert updated.ratification_state == "ratified"
    assert repo.update_ratification_state( "missing", "x" ) is None


def test_delete_all_clears_table( db_session ):
    repo = PredictionDecisionRepository( db_session )
    _add( repo, "d1", _vec( 1.0 ) )
    _add( repo, "d2", _vec( 1.0 ) )
    db_session.flush()
    assert repo.count() == 2
    assert repo.delete_all() == 2
    assert repo.count() == 0
    assert repo.delete_all() == 0          # empty table → 0
