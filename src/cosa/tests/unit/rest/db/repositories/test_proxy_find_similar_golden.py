"""
Golden-value pin for the proxy path of ``ProxyDecisionEmbeddings.find_similar``.

The retrieval repair adds an opt-in ``metric`` parameter to this wrapper and to
``PredictionDecisionRepository.find_similar``. The decision proxy builds the same wrapper and must
see no change. The committed golden file was captured at base sha c78e4b592, before that code
was written, and records

    - the SQL statement the call emits (the dialect-compiled text, parameters beside it), and
    - the neighbours and scores it returns on a fixed synthetic fixture.

Each test calls the wrapper with its defaults and asserts both equal the golden values.

To re-capture (only on a deliberate, reviewed change to the proxy path):

    LUPIN_CAPTURE_PROXY_GOLDEN=1 LUPIN_ROOT="$PWD" PYTHONPATH="$PWD/src" \\
        .venv/bin/python -m pytest src/cosa/tests/unit/rest/db/repositories/test_proxy_find_similar_golden.py -q
"""

import contextlib
import hashlib
import json
import math
import os
from unittest.mock import patch

import pytest
from sqlalchemy import event

from cosa.agents.decision_proxy.proxy_decision_embeddings import ProxyDecisionEmbeddings
from cosa.rest.db.repositories.prediction_decision_repository import PredictionDecisionRepository
from cosa.rest.db.vector_store_models import EMBEDDING_DIM

GOLDEN_PATH = os.path.join( os.path.dirname( __file__ ), "golden", "proxy_find_similar_base_c78e4b592.json" )
BASE_SHA    = "c78e4b592"


def _unit( *first ):
    """Return a unit-length 768-vector whose first components are ``first``."""
    v    = list( first ) + [ 0.0 ] * ( EMBEDDING_DIM - len( first ) )
    norm = math.sqrt( sum( x * x for x in v ) )
    return [ x / norm for x in v ]


def _scaled( scale, *first ):
    """Return ``_unit( *first )`` times ``scale`` (production norm is near 20)."""
    return [ x * scale for x in _unit( *first ) ]


# id, category, data_origin, response_type, norm, direction. Norms 20 and 1 and 0.01 on purpose:
# the dot product clamps the long vectors to 100 percent, which is the defect phase 3 repairs
# on the preference path and must leave alone on the proxy path.
_ROWS = [
    ( "g-long-exact",   "permission",   "organic",   "yes_no",          20.0, ( 1.0, 0.0, 0.0 ) ),
    ( "g-long-near",    "permission",   "organic",   "yes_no",          20.0, ( 1.0, 0.5, 0.0 ) ),
    ( "g-long-far",     "confirmation", "organic",   "multiple_choice", 20.0, ( 0.0, 1.0, 0.0 ) ),
    ( "g-unit-near",    "permission",   "synthetic", "yes_no",          1.0,  ( 1.0, 0.2, 0.0 ) ),
    ( "g-unit-mid",     "confirmation", "organic",   "yes_no",          1.0,  ( 1.0, 1.0, 0.0 ) ),
    ( "g-tiny-exact",   "permission",   "organic",   "yes_no",          0.01, ( 1.0, 0.0, 0.0 ) ),
]

_CALLS = {
    "defaults"      : {},
    "filtered"      : { "category": "permission", "limit": 3, "threshold": 0.0,
                        "data_origin": "organic", "response_type": "yes_no" },
    "all_pass_floor": { "threshold": 0.0, "limit": 10 },
}


def _query():
    """The fixed query vector: norm 20, so its dot with a norm-20 stored vector clamps to 100."""
    return _scaled( 20.0, 1.0, 0.0, 0.0 )


def _plant( session ):
    """Insert the fixed fixture rows through the repository."""
    repo = PredictionDecisionRepository( session )
    for row_id, category, origin, rtype, norm, direction in _ROWS:
        repo.add_decision(
            id=row_id, question=f"q_{row_id}", category=category, decision_value="yes",
            ratification_state="pending", question_embedding=_scaled( norm, *direction ),
            created_at="2026-07-01", data_origin=origin, response_type=rtype,
        )
    session.flush()


def _vector_digest( value ):
    """Replace a 768-float parameter by a short, stable digest so the golden file stays small."""
    text = json.dumps( [ round( x, 9 ) for x in value ] ) if isinstance( value, ( list, tuple ) ) else str( value )
    return "vector:" + hashlib.sha256( text.encode() ).hexdigest()[ :16 ]


def _normalise_parameters( parameters ):
    """Reduce the cursor parameters to plain JSON-safe values, with vector literals digested."""
    out = {}
    for key, value in parameters.items():
        if isinstance( value, str ) and value.startswith( "[" ) and value.count( "," ) > 100:
            out[ key ] = "vector:" + hashlib.sha256( value.encode() ).hexdigest()[ :16 ]
        else:
            out[ key ] = value if isinstance( value, ( int, float, str, bool, type( None ) ) ) else _vector_digest( value )
    return out


def _run( session, call_kwargs ):
    """
    Call the wrapper with ``call_kwargs`` and capture what it emits and returns.

    Ensures:
        - returns ``{ "statements": [...], "results": [...] }``; statements are the SELECTs
          against prediction_decisions, as the driver receives them
    """
    statements = []

    def _capture( conn, cursor, statement, parameters, context, executemany ):
        if statement.lstrip().upper().startswith( "SELECT" ) and "prediction_decisions" in statement:
            statements.append( { "statement": statement, "parameters": _normalise_parameters( dict( parameters ) ) } )

    @contextlib.contextmanager
    def _fake_get_db():
        yield session

    bind = session.get_bind()
    event.listen( bind, "before_cursor_execute", _capture )
    try:
        with patch( "cosa.rest.db.database.get_db", _fake_get_db ):
            hits = ProxyDecisionEmbeddings().find_similar( _query(), **call_kwargs )
    finally:
        event.remove( bind, "before_cursor_execute", _capture )

    results = [ { "similarity_pct": round( pct, 9 ), "id": record[ "id" ], "category": record[ "category" ],
                  "data_origin": record[ "data_origin" ], "response_type": record[ "response_type" ] }
                for pct, record in hits ]
    return { "statements": statements, "results": results }


def _capture_all( session ):
    """Run every named call and return the whole golden document."""
    _plant( session )
    return {
        "base_sha"    : BASE_SHA,
        "note"        : "Captured from ProxyDecisionEmbeddings.find_similar before any phase 3 change.",
        "call_kwargs" : _CALLS,
        "calls"       : { name: _run( session, kwargs ) for name, kwargs in _CALLS.items() },
    }


def test_capture_golden_values( db_session ):
    """Writes the golden file when LUPIN_CAPTURE_PROXY_GOLDEN=1, and is skipped otherwise."""
    if os.environ.get( "LUPIN_CAPTURE_PROXY_GOLDEN" ) != "1":
        pytest.skip( "capture mode is off; set LUPIN_CAPTURE_PROXY_GOLDEN=1 to re-capture" )
    document = _capture_all( db_session )
    os.makedirs( os.path.dirname( GOLDEN_PATH ), exist_ok=True )
    with open( GOLDEN_PATH, "w" ) as handle:
        json.dump( document, handle, indent=2, sort_keys=True )
        handle.write( "\n" )


@pytest.mark.parametrize( "name", sorted( _CALLS ) )
def test_proxy_find_similar_matches_golden( db_session, name ):
    """The wrapper, called as the proxy calls it, emits the golden SQL and neighbours."""
    if os.environ.get( "LUPIN_CAPTURE_PROXY_GOLDEN" ) == "1":
        pytest.skip( "capture mode" )
    with open( GOLDEN_PATH ) as handle:
        golden = json.load( handle )
    assert golden[ "base_sha" ] == BASE_SHA
    assert golden[ "call_kwargs" ][ name ] == _CALLS[ name ]
    _plant( db_session )
    now = _run( db_session, _CALLS[ name ] )
    assert now[ "statements" ] == golden[ "calls" ][ name ][ "statements" ]
    assert now[ "results" ]    == golden[ "calls" ][ name ][ "results" ]
    assert len( now[ "statements" ] ) == 1
    if name == "defaults":
        assert len( now[ "results" ] ) > 0, "defaults must return neighbours, or the pin guards nothing"
