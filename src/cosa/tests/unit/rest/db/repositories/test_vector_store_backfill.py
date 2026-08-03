"""
Unit tests for the Lane D offline backfill utility (vector_store_backfill.py).

Two tiers, all against the shared Lane B ``conftest.py`` disposable-pgvector DB:
  - PURE coercer/transform tests (no DB) — _is_na / _to_vec / _to_str_list /
    _to_datetime / _clean_scalar / _classify / _row_to_kwargs.
  - backfill_table behavioral tests against the REAL transactional db_session —
    dry-run, apply-into-empty, fail-loud-on-nonempty, truncate-reload, batch
    boundary, empty source, and dot-search vector fidelity over backfilled rows.

100% lines/branches/functions of vector_store_backfill.py's non-boundary core
(the LanceDB-read / get_db / __main__ boundary is # pragma: no cover).
"""

import os
import sys
from datetime import datetime, timezone

import numpy as np
import pytest

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.rest.db.vector_store_models import (
    EMBEDDING_DIM,
    InputAndOutput,
    SolutionSnapshot,
    CanonicalSynonym,
)
from cosa.rest.db.repositories.input_and_output_repository import InputAndOutputRepository
from cosa.rest.db import vector_store_backfill as vsb


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _vec( *first ):
    """A dim-EMBEDDING_DIM vector with `first` up front, zero-padded."""
    v = list( first ) + [ 0.0 ] * ( EMBEDDING_DIM - len( first ) )
    return v[ :EMBEDDING_DIM ]


def _io_rows( n, embed_lead=1.0 ):
    """n input_and_output source-row dicts (numpy embeddings, like LanceDB)."""
    return [
        {
            "date"                   : "2026-07-02",
            "time"                   : "12:00",
            "input_type"             : "agent router go to math",
            "input"                  : f"q{i}",
            "input_embedding"        : np.array( _vec( embed_lead ), dtype=np.float32 ),
            "output_raw"             : str( i ),
            "output_final"           : str( i ),
            "output_final_embedding" : np.array( _vec( 0.0, 1.0 ), dtype=np.float32 ),
            "solution_path_wo_root"  : f"/src/x{i}.py",
        }
        for i in range( n )
    ]


def _synonym_rows( n ):
    """n canonical_synonyms source-row dicts (numpy embeddings + datetimes, like LanceDB)."""
    return [
        {
            "id"                   : f"syn-{i}",
            "snapshot_id"          : f"snap-{i}",
            "question_verbatim"    : f"what time is it {i}",
            "question_normalized"  : f"what time is it {i}",
            "question_gist"        : "time",
            "embedding_verbatim"   : np.array( _vec( 1.0, float( i ) ), dtype=np.float32 ),
            "embedding_normalized" : np.array( _vec( 1.0 ), dtype=np.float32 ),
            "embedding_gist"       : np.array( _vec( 1.0 ), dtype=np.float32 ),
            "confidence_score"     : np.float32( 99.5 ),
            "usage_count"          : np.int32( i ),
            "last_matched"         : datetime( 2026, 7, 1, 9, 0, 0 ),
            "created_date"         : np.datetime64( "2026-06-30T00:00:00" ),
            "source"               : "runtime",
        }
        for i in range( n )
    ]


def _snapshot_rows( n ):
    """n solution_snapshots source-row dicts (array + vector cells; created_date is a string)."""
    return [
        {
            "id_hash"                  : f"hash-{i}",
            "question"                 : f"add {i} and {i}",
            "code"                     : np.array( [ f"print({i}+{i})" ] ),
            "non_synonymous_questions" : [ "subtract" ],
            "question_embedding"       : np.array( _vec( 1.0, float( i ) ), dtype=np.float32 ),
            "code_embedding"           : np.array( _vec( 0.0, 1.0 ), dtype=np.float32 ),
            "is_cache_hit"             : np.bool_( True ),
            "created_date"             : "2026-07-02",
        }
        for i in range( n )
    ]


# =========================================================================== #
# PURE — _is_na
# =========================================================================== #
def test_is_na_none():
    assert vsb._is_na( None ) is True

def test_is_na_nan_float():
    assert vsb._is_na( float( "nan" ) ) is True

def test_is_na_numpy_nat():
    assert vsb._is_na( np.datetime64( "NaT" ) ) is True

def test_is_na_ordinary_value():
    assert vsb._is_na( 5 ) is False
    assert vsb._is_na( "text" ) is False

def test_is_na_array_is_not_na():
    # a multi-element array's `!=` is array-valued → bool() raises → caught → False.
    assert vsb._is_na( np.array( [ 1.0, 2.0 ] ) ) is False


# =========================================================================== #
# PURE — _to_vec / _to_str_list
# =========================================================================== #
def test_to_vec_none():
    assert vsb._to_vec( None ) is None

def test_to_vec_empty_is_none():
    assert vsb._to_vec( [ ] ) is None

def test_to_vec_numpy_array():
    out = vsb._to_vec( np.array( [ 1.0, 2.0, 3.0 ], dtype=np.float32 ) )
    assert out == [ 1.0, 2.0, 3.0 ] and all( isinstance( x, float ) for x in out )

def test_to_vec_python_list():
    assert vsb._to_vec( [ 1, 2 ] ) == [ 1.0, 2.0 ]

def test_to_str_list_none():
    assert vsb._to_str_list( None ) is None

def test_to_str_list_numpy():
    assert vsb._to_str_list( np.array( [ "a", "b" ] ) ) == [ "a", "b" ]

def test_to_str_list_python_list():
    assert vsb._to_str_list( [ "x", "y" ] ) == [ "x", "y" ]


# =========================================================================== #
# PURE — _to_datetime
# =========================================================================== #
def test_to_datetime_na():
    assert vsb._to_datetime( None ) is None
    assert vsb._to_datetime( np.datetime64( "NaT" ) ) is None

def test_to_datetime_passthrough_datetime():
    dt = datetime( 2026, 7, 2, 12, 0, 0 )
    assert vsb._to_datetime( dt ) is dt

def test_to_datetime_numpy_datetime64():
    out = vsb._to_datetime( np.datetime64( "2026-07-02T00:00:00" ) )
    assert out == datetime( 2026, 7, 2, 0, 0, 0 )

def test_to_datetime_epoch_ms():
    out = vsb._to_datetime( 1751414400000 )
    expected = datetime.fromtimestamp( 1751414400.0, tz=timezone.utc ).replace( tzinfo=None )
    assert out == expected and out.tzinfo is None


# =========================================================================== #
# PURE — _clean_scalar
# =========================================================================== #
def test_clean_scalar_na():
    assert vsb._clean_scalar( None ) is None
    assert vsb._clean_scalar( float( "nan" ) ) is None

def test_clean_scalar_numpy_scalar():
    out = vsb._clean_scalar( np.int32( 3 ) )
    assert out == 3 and isinstance( out, int )
    assert vsb._clean_scalar( np.bool_( True ) ) is True

def test_clean_scalar_plain_passthrough():
    assert vsb._clean_scalar( "hello" ) == "hello"
    assert vsb._clean_scalar( 7 ) == 7


# =========================================================================== #
# PURE — _classify (all 4 kinds)
# =========================================================================== #
def test_classify_vector():
    assert vsb._classify( InputAndOutput.__table__.c.input_embedding ) == "vec"

def test_classify_array():
    assert vsb._classify( SolutionSnapshot.__table__.c.code ) == "array"

def test_classify_datetime():
    assert vsb._classify( CanonicalSynonym.__table__.c.last_matched ) == "dt"

def test_classify_scalar():
    assert vsb._classify( InputAndOutput.__table__.c.input ) == "scalar"


# =========================================================================== #
# PURE — _row_to_kwargs (exercises vec/array/dt/scalar + skip across 3 models)
# =========================================================================== #
def test_row_to_kwargs_input_and_output_skips_synthetic_pk():
    row = _io_rows( 1 )[ 0 ]
    kwargs = vsb._row_to_kwargs( row, InputAndOutput, frozenset( { "id" } ) )
    assert "id" not in kwargs                      # synthetic PK omitted
    assert kwargs[ "input" ] == "q0"
    assert kwargs[ "input_embedding" ] == _vec( 1.0 )
    assert kwargs[ "output_final_embedding" ] == _vec( 0.0, 1.0 )

def test_row_to_kwargs_canonical_synonym_datetime_and_vecs():
    row = {
        "id"                   : "syn-1",
        "snapshot_id"          : "snap-1",
        "question_verbatim"    : "what time is it",
        "question_normalized"  : "what time is it",
        "question_gist"        : "time",
        "embedding_verbatim"   : np.array( _vec( 1.0 ), dtype=np.float32 ),
        "embedding_normalized" : np.array( _vec( 1.0 ), dtype=np.float32 ),
        "embedding_gist"       : np.array( _vec( 1.0 ), dtype=np.float32 ),
        "confidence_score"     : np.float32( 99.5 ),
        "usage_count"          : np.int32( 4 ),
        "last_matched"         : datetime( 2026, 7, 1, 9, 0, 0 ),
        "created_date"         : np.datetime64( "2026-06-30T00:00:00" ),
        "source"               : "runtime",
    }
    kwargs = vsb._row_to_kwargs( row, CanonicalSynonym, frozenset() )
    assert kwargs[ "id" ] == "syn-1"
    assert kwargs[ "confidence_score" ] == pytest.approx( 99.5, abs=1e-3 )
    assert kwargs[ "usage_count" ] == 4
    assert kwargs[ "last_matched" ] == datetime( 2026, 7, 1, 9, 0, 0 )
    assert kwargs[ "created_date" ] == datetime( 2026, 6, 30, 0, 0, 0 )
    assert kwargs[ "embedding_gist" ] == _vec( 1.0 )

def test_row_to_kwargs_solution_snapshot_array_and_sparse():
    # sparse row: only a few keys present; the rest read as None.
    row = {
        "id_hash"            : "hash-1",
        "question"           : "add 2 and 2",
        "code"               : np.array( [ "print(2+2)" ] ),
        "non_synonymous_questions" : [ "subtract" ],
        "question_embedding" : np.array( _vec( 1.0 ), dtype=np.float32 ),
        "is_cache_hit"       : np.bool_( True ),
    }
    kwargs = vsb._row_to_kwargs( row, SolutionSnapshot, frozenset() )
    assert kwargs[ "id_hash" ] == "hash-1"
    assert kwargs[ "code" ] == [ "print(2+2)" ]
    assert kwargs[ "non_synonymous_questions" ] == [ "subtract" ]
    assert kwargs[ "is_cache_hit" ] is True
    assert kwargs[ "question_embedding" ] == _vec( 1.0 )
    # a column absent from the sparse row coerces to None.
    assert kwargs[ "answer" ] is None
    assert kwargs[ "thoughts_embedding" ] is None
    assert kwargs[ "created_date" ] is None


# =========================================================================== #
# backfill_table — behavioral, against the REAL disposable pgvector db_session
# =========================================================================== #
def test_backfill_dry_run_writes_nothing( db_session ):
    report = vsb.backfill_table( db_session, InputAndOutput, _io_rows( 3 ),
                                 skip=frozenset( { "id" } ), apply=False )
    assert report == { "source_count": 3, "existing_before": 0, "purged": 0, "inserted": 0 }
    assert db_session.query( InputAndOutput ).count() == 0

def test_backfill_apply_into_empty( db_session ):
    report = vsb.backfill_table( db_session, InputAndOutput, _io_rows( 3 ),
                                 skip=frozenset( { "id" } ), apply=True )
    assert report[ "inserted" ] == 3 and report[ "existing_before" ] == 0
    assert report[ "purged" ] == 0
    assert db_session.query( InputAndOutput ).count() == 3

def test_backfill_apply_into_empty_canonical_synonyms( db_session ):
    # Cheech pre-RUN advisory: prove the synonym-heal table round-trips (insert → read back).
    # canonical_synonyms carries the L1/L2 fast-path; a broken round-trip would silently
    # re-drop the mappings the backfill exists to preserve.
    report = vsb.backfill_table( db_session, CanonicalSynonym, _synonym_rows( 3 ), apply=True )
    assert report[ "inserted" ] == 3 and report[ "existing_before" ] == 0 and report[ "purged" ] == 0
    assert db_session.query( CanonicalSynonym ).count() == 3
    read = db_session.query( CanonicalSynonym ).filter_by( id="syn-1" ).one()
    assert read.question_normalized == "what time is it 1"
    assert read.source              == "runtime"
    assert read.usage_count         == 1
    assert read.confidence_score    == pytest.approx( 99.5, abs=1e-3 )
    assert read.last_matched        == datetime( 2026, 7, 1, 9, 0, 0 )     # DateTime column
    assert read.created_date        == datetime( 2026, 6, 30, 0, 0, 0 )    # DateTime column
    assert list( read.embedding_verbatim )[ :2 ] == pytest.approx( [ 1.0, 1.0 ] )   # vec round-trip

def test_backfill_apply_into_empty_solution_snapshots( db_session ):
    # Cheech pre-RUN advisory: prove the curated-snapshot table round-trips its ARRAY
    # (code / non_synonymous_questions) + vector cells + the STRING created_date column.
    report = vsb.backfill_table( db_session, SolutionSnapshot, _snapshot_rows( 3 ), apply=True )
    assert report[ "inserted" ] == 3 and report[ "existing_before" ] == 0 and report[ "purged" ] == 0
    assert db_session.query( SolutionSnapshot ).count() == 3
    read = db_session.query( SolutionSnapshot ).filter_by( id_hash="hash-2" ).one()
    assert read.question                 == "add 2 and 2"
    assert read.code                     == [ "print(2+2)" ]               # ARRAY(Text) round-trip
    assert read.non_synonymous_questions == [ "subtract" ]                 # ARRAY(Text) round-trip
    assert read.is_cache_hit is True
    assert read.created_date             == "2026-07-02"                   # Text column (NOT DateTime)
    assert list( read.question_embedding )[ :2 ] == pytest.approx( [ 1.0, 2.0 ] )   # vec round-trip

def test_backfill_apply_nonempty_without_truncate_raises( db_session ):
    vsb.backfill_table( db_session, InputAndOutput, _io_rows( 2 ),
                        skip=frozenset( { "id" } ), apply=True )
    with pytest.raises( ValueError, match="refusing a silent double-load" ):
        vsb.backfill_table( db_session, InputAndOutput, _io_rows( 2 ),
                            skip=frozenset( { "id" } ), apply=True, truncate=False )

def test_backfill_apply_with_truncate_reloads( db_session ):
    vsb.backfill_table( db_session, InputAndOutput, _io_rows( 3 ),
                        skip=frozenset( { "id" } ), apply=True )
    report = vsb.backfill_table( db_session, InputAndOutput, _io_rows( 2 ),
                                 skip=frozenset( { "id" } ), apply=True, truncate=True )
    assert report[ "existing_before" ] == 3
    assert report[ "purged" ] == 3
    assert report[ "inserted" ] == 2
    assert db_session.query( InputAndOutput ).count() == 2

def test_backfill_batch_boundary_flushes( db_session ):
    # 5 rows, batch_size 2 → flush at 2 and 4, final flush of the trailing 1.
    report = vsb.backfill_table( db_session, InputAndOutput, _io_rows( 5 ),
                                 skip=frozenset( { "id" } ), apply=True, batch_size=2 )
    assert report[ "inserted" ] == 5
    assert db_session.query( InputAndOutput ).count() == 5

def test_backfill_empty_source( db_session ):
    # empty source under apply → loop never runs, final-flush branch not taken.
    report = vsb.backfill_table( db_session, InputAndOutput, [ ],
                                 skip=frozenset( { "id" } ), apply=True )
    assert report == { "source_count": 0, "existing_before": 0, "purged": 0, "inserted": 0 }
    assert db_session.query( InputAndOutput ).count() == 0

def test_backfill_vector_fidelity_dot_search( db_session ):
    # backfilled input_embedding must serve the dot (<#>) nearest-k path.
    rows = [
        { "input": "aligned", "input_embedding": np.array( _vec( 1.0, 0.0 ), dtype=np.float32 ),
          "output_final": "A" },
        { "input": "orthogonal", "input_embedding": np.array( _vec( 0.0, 1.0 ), dtype=np.float32 ),
          "output_final": "B" },
    ]
    vsb.backfill_table( db_session, InputAndOutput, rows, skip=frozenset( { "id" } ), apply=True )
    results = InputAndOutputRepository( db_session ).get_knn_by_input( _vec( 1.0, 0.0 ), k=2 )
    assert results[ 0 ][ 1 ].input == "aligned"
    assert abs( results[ 0 ][ 0 ] - 100.0 ) < 1e-6      # dot*100 == 100 for the aligned row


def test_backfill_specs_registry_shape():
    labels = [ spec.label for spec in vsb.BACKFILL_SPECS ]
    assert labels == [ "input_and_output", "solution_snapshots", "canonical_synonyms" ]
    io_spec = vsb.BACKFILL_SPECS[ 0 ]
    assert io_spec.model is InputAndOutput and io_spec.skip == frozenset( { "id" } )
    assert io_spec.source_table == "input_and_output_tbl"
