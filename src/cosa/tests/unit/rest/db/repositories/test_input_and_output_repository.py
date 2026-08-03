"""
Unit tests for InputAndOutputRepository against a real disposable pgvector DB.

Covers insert, the dot (`<#>`) nearest-k search on input_embedding, the bounded
list/stats/router-filter reads, and BaseRepository count/exists.

100% lines/branches/functions of input_and_output_repository.py.
"""

import os
import sys

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.rest.db.repositories.input_and_output_repository import InputAndOutputRepository
from cosa.rest.db.vector_store_models import EMBEDDING_DIM


def _vec( *first ):
    """A dim-768 vector whose leading components are `first`, rest zero."""
    v = list( first ) + [ 0.0 ] * ( EMBEDDING_DIM - len( first ) )
    return v[ :EMBEDDING_DIM ]


def test_insert_and_get_by_id( db_session ):
    repo = InputAndOutputRepository( db_session )
    row = repo.insert_io_row(
        date="2026-07-01", time="12:00", input_type="agent router go to math",
        input="what is 2+2", input_embedding=_vec( 1.0 ),
        output_raw="4", output_final="4", output_final_embedding=_vec( 0.0, 1.0 ),
        solution_path_wo_root="/src/x.py",
    )
    db_session.flush()
    assert row.id is not None
    fetched = repo.get_by_id( row.id )
    assert fetched.input == "what is 2+2" and fetched.output_final == "4"
    assert repo.count() == 1
    assert repo.exists( row.id ) is True


def test_get_knn_by_input_orders_by_dot( db_session ):
    repo = InputAndOutputRepository( db_session )
    repo.insert_io_row( input="a", input_embedding=_vec( 1.0, 0.0 ), output_final="A" )
    repo.insert_io_row( input="b", input_embedding=_vec( 0.0, 1.0 ), output_final="B" )
    repo.insert_io_row( input="c", input_embedding=_vec( 0.5, 0.0 ), output_final="C" )
    db_session.flush()

    # Query aligned with 'a' → strongest dot for a (1.0), then c (0.5), then b (0.0).
    results = repo.get_knn_by_input( _vec( 1.0, 0.0 ), k=3 )
    inputs  = [ entity.input for _, entity in results ]
    assert inputs == [ "a", "c", "b" ]
    # similarity_pct == dot * 100 (LanceDB scale).
    assert abs( results[ 0 ][ 0 ] - 100.0 ) < 1e-6
    assert abs( results[ 1 ][ 0 ] - 50.0 )  < 1e-6
    assert abs( results[ 2 ][ 0 ] - 0.0 )   < 1e-6


def test_get_knn_respects_k( db_session ):
    repo = InputAndOutputRepository( db_session )
    for i in range( 5 ):
        repo.insert_io_row( input=f"q{i}", input_embedding=_vec( float( i ) ), output_final=str( i ) )
    db_session.flush()
    assert len( repo.get_knn_by_input( _vec( 1.0 ), k=2 ) ) == 2


def test_get_all_io_bounded( db_session ):
    repo = InputAndOutputRepository( db_session )
    for i in range( 3 ):
        repo.insert_io_row( input=f"q{i}", input_embedding=_vec( 1.0 ) )
    db_session.flush()
    assert len( repo.get_all_io( max_rows=2 ) ) == 2
    assert len( repo.get_all_io() ) == 3


def test_get_io_stats_by_input_type( db_session ):
    repo = InputAndOutputRepository( db_session )
    repo.insert_io_row( input="x", input_type="math", input_embedding=_vec( 1.0 ) )
    repo.insert_io_row( input="y", input_type="math", input_embedding=_vec( 1.0 ) )
    repo.insert_io_row( input="z", input_type="calendar", input_embedding=_vec( 1.0 ) )
    db_session.flush()
    stats = repo.get_io_stats_by_input_type()
    assert stats == { "math": 2, "calendar": 1 }


def test_get_all_qnr_filters_router_prefix( db_session ):
    repo = InputAndOutputRepository( db_session )
    repo.insert_io_row( input="a", input_type="agent router go to math", input_embedding=_vec( 1.0 ) )
    repo.insert_io_row( input="b", input_type="something else", input_embedding=_vec( 1.0 ) )
    db_session.flush()
    rows = repo.get_all_qnr( max_rows=10 )
    assert len( rows ) == 1 and rows[ 0 ].input == "a"
