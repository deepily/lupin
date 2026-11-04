"""
Pins for the three SolutionSnapshotRepository nearest-k methods.

The session and dot_topk are replaced. What each method hands to dot_topk is then the
whole behaviour: column, limit, threshold, metric and exclusion filter.
"""

import os
import sys

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from unittest.mock import MagicMock, patch

import pytest

import cosa.rest.db.repositories.solution_snapshot_repository as ssr
from cosa.rest.db.repositories.solution_snapshot_repository import SolutionSnapshotRepository
from cosa.rest.db.vector_store_models import SolutionSnapshot

# method name, embedding column, default threshold, default limit
_CASES = [
    ( "get_snapshots_by_question",            SolutionSnapshot.question_embedding,  90.0, 7  ),
    ( "get_snapshots_by_code_similarity",     SolutionSnapshot.code_embedding,      85.0, 20 ),
    ( "get_snapshots_by_solution_similarity", SolutionSnapshot.solution_embedding,  85.0, 20 ),
]


@pytest.mark.parametrize( "name,column,threshold,limit", _CASES )
def test_defaults_are_forwarded_to_dot_topk( name, column, threshold, limit ):
    session = MagicMock()
    repo    = SolutionSnapshotRepository( session )
    with patch.object( ssr, "dot_topk", return_value=[ ( 99.0, "row" ) ] ) as topk:
        result = getattr( repo, name )( [ 0.5 ] )
    assert result == [ ( 99.0, "row" ) ]
    args, kwargs = topk.call_args
    assert args[ 0 ] is session and args[ 1 ] is SolutionSnapshot
    assert args[ 2 ] is column and args[ 3 ] == [ 0.5 ]
    assert kwargs == { "limit": limit, "exclude_filter": None, "threshold_pct": threshold, "metric": "cosine" }


@pytest.mark.parametrize( "name,column,threshold,limit", _CASES )
def test_explicit_arguments_and_exclusion_are_forwarded( name, column, threshold, limit ):
    repo = SolutionSnapshotRepository( MagicMock() )
    with patch.object( ssr, "dot_topk", return_value=[] ) as topk:
        getattr( repo, name )( [ 1.0 ], threshold=50.0, limit=3, exclude_id_hash="skip" )
    args, kwargs = topk.call_args
    assert args[ 2 ] is column
    assert kwargs[ "limit" ] == 3 and kwargs[ "threshold_pct" ] == 50.0 and kwargs[ "metric" ] == "cosine"
    assert str( kwargs[ "exclude_filter" ] ) == str( SolutionSnapshot.id_hash != "skip" )
