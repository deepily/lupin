"""
The time-sliced replay store retrieves what production retrieves.

The replay harness tunes thresholds on ``TimeSlicedDecisionStore``. If that store ranked, scored or filtered
differently from the SQL path that ships, the tuned floors would not carry over. So this file plants one fixture
in the real pgvector table and in the store. It calls both with the same arguments. It compares neighbours in
order, scores and the record shape, for ``dot`` and for ``cosine``.

The fixture is the golden fixture of the retrieval repair (``test_proxy_find_similar_golden._ROWS``, norms 20, 1
and 0.01). It adds rows the golden file lacks. These are an opposite vector that clamps to 0, a zero-norm vector
and a row with no vector. Others carry an owner and each answer source.
"""

import itertools
import math
from datetime import datetime, timezone

import pytest

from cosa.agents.decision_proxy.proxy_decision_embeddings import ProxyDecisionEmbeddings
from cosa.research.preference_replay.time_sliced_store import RECORD_FIELDS, TimeSlicedDecisionStore
from cosa.rest.db.repositories.prediction_decision_repository import PredictionDecisionRepository
from cosa.rest.db.vector_errors import QueryVectorRefused
from cosa.rest.db.vector_store_models import EMBEDDING_DIM
from cosa.tests.unit.rest.db.repositories.test_proxy_find_similar_golden import _ROWS, _query, _scaled

ANSWERED_AT = datetime( 2026, 7, 1, tzinfo=timezone.utc )
ASK_AT      = datetime( 2026, 8, 1, tzinfo=timezone.utc )

# id, category, data_origin, response_type, owner, source, vector (None for no vector)
_EXTRA = [
    ( "e-opposite",  "permission",   "organic", "yes_no",          None,    "unknown", _scaled( 20.0, -1.0, 0.0, 0.0 ) ),
    ( "e-zero-norm", "permission",   "organic", "yes_no",          None,    "unknown", [ 0.0 ] * EMBEDDING_DIM ),
    ( "e-no-vector", "permission",   "organic", "yes_no",          None,    "unknown", None ),
    ( "e-rick-yes",  "permission",   "organic", "yes_no",          "rick",  "human",   _scaled( 20.0, 1.0, 0.1, 0.0 ) ),
    ( "e-rick-mc",   "confirmation", "organic", "multiple_choice", "rick",  "human",   _scaled( 20.0, 0.3, 1.0, 0.0 ) ),
    ( "e-ana-proxy", "permission",   "organic", "yes_no",          "ana",   "proxy",   _scaled( 20.0, 1.0, 0.3, 0.3 ) ),
]


def _rows():
    """Every fixture row as ``( id, category, origin, rtype, owner, source, vector )``."""
    golden = [ ( row_id, category, origin, rtype, None, "unknown", _scaled( norm, *direction ) )
               for row_id, category, origin, rtype, norm, direction in _ROWS ]
    return golden + _EXTRA


def _plant( session ):
    """Insert the fixture through the repository, the way production does."""
    repo = PredictionDecisionRepository( session )
    for row_id, category, origin, rtype, owner, source, vector in _rows():
        repo.add_decision( id=row_id, question=f"q_{row_id}", category=category, decision_value="yes",
                           ratification_state="pending", question_embedding=vector, created_at="2026-07-01",
                           data_origin=origin, response_type=rtype, owner_user_id=owner, answer_source=source )
    session.flush()


def _store( rows=None, answered_at=ANSWERED_AT ):
    """Build the store from the same rows, every case answered at ``answered_at``."""
    cases = [ { "id": row_id, "question": f"q_{row_id}", "category": category, "decision_value": "yes",
                "ratification_state": "pending", "data_origin": origin, "response_type": rtype,
                "question_embedding": vector, "created_at": "2026-07-01", "owner_user_id": owner,
                "answer_source": source, "responded_at": answered_at }
              for row_id, category, origin, rtype, owner, source, vector in ( rows or _rows() ) ]
    store = TimeSlicedDecisionStore( cases )
    store.advance_to( ASK_AT )
    return store


def _sql( session, query, **kwargs ):
    """The SQL path, projected to the record shape the wrapper returns."""
    return [ ( pct, ProxyDecisionEmbeddings._record_to_dict( entity ) )
             for pct, entity in PredictionDecisionRepository( session ).find_similar( query, **kwargs ) ]


def _assert_same( sql_hits, store_hits ):
    """Same neighbours in the same order, scores within float32 noise, same record shape."""
    assert [ r[ "id" ] for _, r in store_hits ] == [ r[ "id" ] for _, r in sql_hits ]
    for ( sql_pct, sql_record ), ( store_pct, store_record ) in zip( sql_hits, store_hits ):
        assert store_pct == pytest.approx( sql_pct, abs=1e-3 )
        assert list( store_record.keys() ) == list( sql_record.keys() ) == list( RECORD_FIELDS )
        for field in RECORD_FIELDS:
            if field == "question_embedding":
                assert store_record[ field ] == pytest.approx( sql_record[ field ], abs=1e-5 )
            else:
                assert store_record[ field ] == sql_record[ field ], field


# Neither query is perpendicular to a fixture row, so no two rows tie on the raw score. The golden query is exact
# on the x axis, where the zero vector and the y-axis row both score 0 and SQL breaks that tie arbitrarily.
_QUERIES = { "near_axis": _scaled( 20.0, 1.0, 0.02, 0.0 ), "slanted": _scaled( 20.0, 1.0, 0.3, 0.0 ) }

_FILTERS = {
    "none"          : {},
    "category"      : { "category": "permission" },
    "origin"        : { "data_origin": "organic" },
    "response_type" : { "response_type": "yes_no" },
    "owner"         : { "owner_user_id": "rick" },
    "source"        : { "answer_source": "human" },
    "all_five"      : { "category": "permission", "data_origin": "organic", "response_type": "yes_no",
                        "owner_user_id": "ana", "answer_source": "proxy" },
    "no_match"      : { "category": "nothing-has-this-category" },
}
_LIMITS     = [ 1, 3, 8 ]
_THRESHOLDS = [ 0.0, 0.5, 0.95 ]


@pytest.mark.parametrize( "metric", [ "dot", "cosine" ] )
@pytest.mark.parametrize( "query_name", sorted( _QUERIES ) )
def test_the_store_and_the_sql_path_agree_on_every_filter_limit_and_threshold( db_session, metric, query_name ):
    """Neighbours, order, scores and records match across the filter, limit and threshold grid."""
    _plant( db_session )
    store    = _store()
    compared = 0
    non_empty = 0
    for ( filter_name, filters ), limit, threshold in itertools.product( _FILTERS.items(), _LIMITS, _THRESHOLDS ):
        # On the dot path a NULL vector would fall inside a limit wider than the vectored rows; the
        # next test measures that. These limits stay inside it.
        sql_hits   = _sql( db_session, _QUERIES[ query_name ], limit=limit, threshold=threshold, metric=metric, **filters )
        store_hits = store.find_similar( _QUERIES[ query_name ], limit=limit, threshold=threshold, metric=metric, **filters )
        _assert_same( sql_hits, store_hits )
        compared  += 1
        non_empty += 1 if sql_hits else 0
    assert compared == len( _FILTERS ) * len( _LIMITS ) * len( _THRESHOLDS )
    assert non_empty > compared // 3, "most calls must return neighbours, or the grid compares empty lists"


def test_the_clamp_holds_a_long_vector_at_100_on_the_dot_path_in_both( db_session ):
    """Norm-20 vectors have a dot product far above 1, so the dot score reads 100 in both."""
    _plant( db_session )
    sql_hits   = _sql( db_session, _query(), limit=3, threshold=0.0 )
    store_hits = _store().find_similar( _query(), limit=3, threshold=0.0 )
    assert sql_hits[ 0 ][ 0 ] == 100.0 and store_hits[ 0 ][ 0 ] == 100.0
    _assert_same( sql_hits, store_hits )


def test_the_clamp_holds_a_negative_cosine_at_0_in_both( db_session ):
    """A cosine of -1 clamps to 0 in both paths and survives a zero threshold."""
    _plant( db_session )
    sql_hits   = _sql( db_session, _query(), limit=20, threshold=0.0, metric="cosine" )
    store_hits = _store().find_similar( _query(), limit=20, threshold=0.0, metric="cosine" )
    assert dict( ( r[ "id" ], pct ) for pct, r in sql_hits )[ "e-opposite" ] == 0.0
    assert dict( ( r[ "id" ], pct ) for pct, r in store_hits )[ "e-opposite" ] == 0.0
    _assert_same( sql_hits, store_hits )


def test_the_threshold_applies_after_the_limit_in_both( db_session ):
    """With limit 1, a threshold above the strongest case empties the answer in both."""
    _plant( db_session )
    store = _store()
    query = _scaled( 20.0, 1.0, 1.0, 0.0 )
    for metric in ( "dot", "cosine" ):
        everything = _sql( db_session, query, limit=1, threshold=0.0, metric=metric )
        assert len( everything ) == 1
        threshold = everything[ 0 ][ 0 ] / 100.0 + 0.001
        if threshold > 1.0: continue
        sql_hits   = _sql( db_session, query, limit=1, threshold=threshold, metric=metric )
        store_hits = store.find_similar( query, limit=1, threshold=threshold, metric=metric )
        assert sql_hits == [] and store_hits == []


def test_cosine_leaves_out_a_null_vector_and_a_zero_norm_vector_in_both( db_session ):
    """Neither the row with no vector nor the zero vector is ever returned on the cosine path."""
    _plant( db_session )
    sql_ids   = [ r[ "id" ] for _, r in _sql( db_session, _query(), limit=50, threshold=0.0, metric="cosine" ) ]
    store_ids = [ r[ "id" ] for _, r in _store().find_similar( _query(), limit=50, threshold=0.0, metric="cosine" ) ]
    assert "e-no-vector" not in sql_ids and "e-zero-norm" not in sql_ids
    assert sql_ids == store_ids and len( sql_ids ) == len( _rows() ) - 2


def test_dot_scores_a_zero_norm_vector_as_0_in_both( db_session ):
    """On the dot path a zero vector scores 0 and stays in both."""
    _plant( db_session )
    query      = _QUERIES[ "slanted" ]
    sql_hits   = _sql( db_session, query, limit=len( _rows() ) - 1, threshold=0.0 )
    store_hits = _store().find_similar( query, limit=len( _rows() ) - 1, threshold=0.0 )
    assert "e-zero-norm" in [ r[ "id" ] for _, r in sql_hits ]
    _assert_same( sql_hits, store_hits )


def test_the_dot_path_difference_for_a_null_vector_is_the_one_documented( db_session ):
    """A wide limit pulls the NULL row into the SQL window, which raises; the store skips it."""
    _plant( db_session )
    with pytest.raises( TypeError ):
        _sql( db_session, _query(), limit=len( _rows() ), threshold=0.0 )
    store_ids = [ r[ "id" ] for _, r in _store().find_similar( _query(), limit=len( _rows() ), threshold=0.0 ) ]
    assert "e-no-vector" not in store_ids and len( store_ids ) == len( _rows() ) - 1


@pytest.mark.parametrize( "bad_query", [ None, [ 1.0, 2.0 ], [ 0.0 ] * EMBEDDING_DIM, [ float( "nan" ) ] + [ 1.0 ] * ( EMBEDDING_DIM - 1 ),
                                          _scaled( 1.0, 1.0, 0.0, 0.0 ), _scaled( 500.0, 1.0, 0.0, 0.0 ) ] )
def test_a_cosine_query_the_repository_refuses_is_refused_by_the_store_with_the_same_reason( db_session, bad_query ):
    """Each unusable cosine query raises QueryVectorRefused in both, with one message."""
    _plant( db_session )
    with pytest.raises( QueryVectorRefused ) as from_sql:
        _sql( db_session, bad_query, metric="cosine" )
    with pytest.raises( QueryVectorRefused ) as from_store:
        _store().find_similar( bad_query, metric="cosine" )
    assert str( from_store.value ) == str( from_sql.value )


def test_an_unknown_metric_raises_value_error_in_both( db_session ):
    """Both paths refuse a metric that is neither dot nor cosine."""
    _plant( db_session )
    with pytest.raises( ValueError ):
        _sql( db_session, _query(), metric="euclid" )
    with pytest.raises( ValueError ):
        _store().find_similar( _query(), metric="euclid" )
