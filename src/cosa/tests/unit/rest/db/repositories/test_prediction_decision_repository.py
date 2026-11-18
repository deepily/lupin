"""
Unit tests for PredictionDecisionRepository (question_embedding ANN, HNSW dot).

100% lines/branches/functions of prediction_decision_repository.py.
"""

import os
import sys

import pytest

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.rest.db.repositories.prediction_decision_repository import PredictionDecisionRepository
from cosa.rest.db.vector_errors import QueryVectorRefused
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


def _add_sourced( repo, id, owner, source ):
    return repo.add_decision(
        id=id, question=f"q_{id}", category="permission", decision_value="yes",
        ratification_state="not_required", question_embedding=_vec( 1.0 ),
        created_at="2026-07-01", response_type="yes_no", owner_user_id=owner, answer_source=source,
    )


def test_a_case_stored_without_a_source_is_unknown_and_has_no_owner( db_session ):
    repo = PredictionDecisionRepository( db_session )
    _add( repo, "legacy", _vec( 1.0 ) )
    db_session.flush()
    stored = repo.get_by_id( "legacy" )
    assert ( stored.owner_user_id, stored.answer_source ) == ( None, "unknown" )


def test_only_a_human_answer_from_the_owner_casts_a_personal_vote( db_session ):
    repo = PredictionDecisionRepository( db_session )
    _add_sourced( repo, "mine", "owner-1", "human" )
    for case_id, owner, source in ( ( "timeout", "owner-1", "timeout_default" ), ( "proxy", "owner-1", "proxy" ),
                                    ( "other-user", "owner-2", "human" ), ( "unknown", None, "unknown" ),
                                    ( "hint", None, "hint_vote" ), ( "test", "owner-1", "test" ) ):
        _add_sourced( repo, case_id, owner, source )
    db_session.flush()

    hits = repo.find_similar( _vec( 1.0 ), threshold=0.0, owner_user_id="owner-1", answer_source="human" )
    assert [ entity.id for _, entity in hits ] == [ "mine" ]
    assert len( repo.find_similar( _vec( 1.0 ), threshold=0.0, limit=10 ) ) == 7


def test_find_similar_cosine_ignores_vector_length( db_session ):
    """Scaling a stored vector changes neither its rank nor its cosine score."""
    repo = PredictionDecisionRepository( db_session )
    _add( repo, "short-close", _vec( 1.0, 0.1 ) )                 # norm 1, nearly parallel to the query
    _add( repo, "long-far",    _vec( 20.0, 20.0 ) )               # norm 28, 45 degrees off
    _add( repo, "long-close",  _vec( 40.0, 4.0 ) )                # the short-close vector times 40
    db_session.flush()
    hits = repo.find_similar( _vec( 20.0, 0.0 ), threshold=0.0, metric="cosine" )
    by_id = { e.id: pct for pct, e in hits }
    assert [ e.id for _, e in hits ][ -1 ] == "long-far"
    assert abs( by_id[ "short-close" ] - by_id[ "long-close" ] ) < 1e-4
    assert abs( by_id[ "long-far" ] - 70.7107 ) < 1e-2            # cos 45 degrees, not clamped to 100


@pytest.mark.parametrize( "factor", [ 0.5, 2.0 ] )
def test_find_similar_cosine_ignores_query_length_too( db_session, factor ):
    """Scaling the query by a positive factor changes neither the order nor any score."""
    repo = PredictionDecisionRepository( db_session )
    _add( repo, "a", _vec( 20.0, 1.0 ) )
    _add( repo, "b", _vec( 20.0, 12.0 ) )
    _add( repo, "c", _vec( 3.0, 20.0 ) )
    db_session.flush()
    base   = repo.find_similar( _vec( 20.0, 4.0 ), threshold=0.0, metric="cosine" )
    scaled = repo.find_similar( _vec( 20.0 * factor, 4.0 * factor ), threshold=0.0, metric="cosine" )
    assert [ e.id for _, e in scaled ] == [ e.id for _, e in base ] == [ "a", "b", "c" ]
    assert [ round( p, 4 ) for p, _ in scaled ] == [ round( p, 4 ) for p, _ in base ]
    assert len( { round( p, 4 ) for p, _ in base } ) == 3          # the three scores differ, so order is meaningful


def test_find_similar_dot_default_still_clamps_long_vectors( db_session ):
    """The default path keeps the old scale: a long far vector reads 100 percent on dot."""
    repo = PredictionDecisionRepository( db_session )
    _add( repo, "long-far", _vec( 20.0, 20.0 ) )
    db_session.flush()
    default = repo.find_similar( _vec( 1.0, 0.0 ), threshold=0.0 )
    assert default[ 0 ][ 0 ] == 100.0
    assert repo.find_similar( _vec( 1.0, 0.0 ), threshold=0.0, metric="dot" ) == default


def test_find_similar_cosine_applies_threshold_after_ordering( db_session ):
    """The cosine score is compared with the floor, so a 70.7 percent case fails a 0.75 floor."""
    repo = PredictionDecisionRepository( db_session )
    _add( repo, "long-far", _vec( 20.0, 20.0 ) )
    db_session.flush()
    assert repo.find_similar( _vec( 20.0, 0.0 ), threshold=0.75, metric="cosine" ) == []


def test_find_similar_unknown_metric_raises( db_session ):
    repo = PredictionDecisionRepository( db_session )
    with pytest.raises( ValueError, match="metric" ):
        repo.find_similar( _vec( 1.0 ), metric="euclid" )


@pytest.mark.parametrize( "query, fragment", [
    ( None,                                  "embedder returned nothing" ),
    ( [ 1.0, 2.0, 3.0 ],                     "wrong dimension 3" ),
    ( [ 0.0 ] * EMBEDDING_DIM,               "query vector has zero norm" ),
    ( [ float( "nan" ) ] + [ 20.0 ] * ( EMBEDDING_DIM - 1 ), "non-finite" ),
    ( _vec( 1.0 ),                           "classified 'normalized'" ),
    ( _vec( 500.0 ),                         "classified 'suspect'" ),
] )
def test_cosine_refuses_an_untrustworthy_query_with_a_named_reason( db_session, query, fragment ):
    repo = PredictionDecisionRepository( db_session )
    with pytest.raises( QueryVectorRefused ) as caught:
        repo.find_similar( query, metric="cosine" )
    assert fragment in caught.value.reason
    assert str( caught.value ) == caught.value.reason


def test_dot_path_never_raises_the_refusal( db_session ):
    """A zero query on the default path behaves as it always did: no exception."""
    repo = PredictionDecisionRepository( db_session )
    _add( repo, "d1", _vec( 1.0 ) )
    db_session.flush()
    assert isinstance( repo.find_similar( [ 0.0 ] * EMBEDDING_DIM, threshold=0.0 ), list )


def test_cosine_never_returns_a_null_or_zero_norm_stored_row( db_session ):
    repo = PredictionDecisionRepository( db_session )
    _add( repo, "good",      _vec( 20.0, 1.0 ) )
    _add( repo, "null-row",  None )
    _add( repo, "zero-row",  [ 0.0 ] * EMBEDDING_DIM )
    db_session.flush()
    hits = repo.find_similar( _vec( 20.0, 0.0 ), threshold=0.0, metric="cosine" )
    assert [ e.id for _, e in hits ] == [ "good" ]


def test_cosine_filter_composes_with_the_scalar_filters( db_session ):
    repo = PredictionDecisionRepository( db_session )
    _add( repo, "p1", _vec( 20.0 ), category="permission" )
    _add( repo, "c1", _vec( 20.0 ), category="confirmation" )
    _add( repo, "null-p", None, category="permission" )
    db_session.flush()
    hits = repo.find_similar( _vec( 20.0 ), threshold=0.0, metric="cosine", category="permission" )
    assert [ e.id for _, e in hits ] == [ "p1" ]
