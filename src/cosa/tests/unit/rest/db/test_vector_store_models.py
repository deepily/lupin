"""
Unit tests for cosa.rest.db.vector_store_models — the pgvector ORM models that
replace the LanceDB backend (v0.2.0).

Pure-Python metadata tests: they assert the ORM definitions (table names, vector
dims, HNSW `vector_ip_ops` indexes, scalar btree indexes, gist_cache-is-relational,
the F6 underscore column) WITHOUT a database. Coverage of vector_store_models is
satisfied entirely here — the module is declarative plus one helper. The live-PG
apply/CRUD tests live in test_pgvector_migration.py and are gated on the pgvector
image force-recreate.
"""

import unittest

from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import ARRAY

from cosa.rest.postgres_models import Base
from cosa.rest.db import vector_store_models as vsm


def _vector_columns( table ):
    """Return the names of Vector-typed columns on a metadata Table."""
    return [ c.name for c in table.columns if isinstance( c.type, Vector ) ]


def _hnsw_index_pairs( metadata ):
    """Return the set of (table, column) pairs carrying an HNSW vector_ip_ops index."""
    pairs = set()
    for tname, table in metadata.tables.items():
        for idx in table.indexes:
            opts = idx.dialect_options.get( "postgresql", {} )
            if opts.get( "using" ) == "hnsw":
                ops = opts.get( "ops" ) or {}
                for col in idx.columns.keys():
                    if ops.get( col ) == "vector_ip_ops":
                        pairs.add( ( tname, col ) )
    return pairs


class TestRegistration( unittest.TestCase ):

    def test_all_eight_tables_registered( self ):
        want = { m.__tablename__ for m in vsm.VECTOR_STORE_MODELS }
        self.assertEqual( len( want ), 8 )
        for name in want:
            self.assertIn( name, Base.metadata.tables )

    def test_registry_covers_expected_tables( self ):
        names = { m.__tablename__ for m in vsm.VECTOR_STORE_MODELS }
        self.assertEqual(
            names,
            {
                "input_and_output", "question_embeddings", "embedding_cache",
                "gist_cache", "canonical_synonyms", "query_log",
                "prediction_decisions", "solution_snapshots",
            },
        )


class TestEmbeddingDim( unittest.TestCase ):

    def test_constant_is_768( self ):
        self.assertEqual( vsm.EMBEDDING_DIM, 768 )

    def test_every_vector_column_is_dim_768( self ):
        checked = 0
        for m in vsm.VECTOR_STORE_MODELS:
            table = Base.metadata.tables[ m.__tablename__ ]
            for c in table.columns:
                if isinstance( c.type, Vector ):
                    self.assertEqual( c.type.dim, 768, f"{table.name}.{c.name} dim" )
                    checked += 1
        # 2 + 1 + 1 + 0 + 3 + 3 + 1 + 7 = 18 vector columns across the 8 tables.
        self.assertEqual( checked, 18 )


class TestGistCacheIsRelational( unittest.TestCase ):

    def test_gist_cache_has_no_vector_column( self ):
        table = Base.metadata.tables[ "gist_cache" ]
        self.assertEqual( _vector_columns( table ), [] )


class TestHnswIndexes( unittest.TestCase ):

    def test_exactly_four_hnsw_dot_indexes_on_the_right_columns( self ):
        pairs = _hnsw_index_pairs( Base.metadata )
        self.assertEqual( pairs, set( vsm.HNSW_DOT_INDEXES ) )
        self.assertEqual( len( pairs ), 4 )

    def test_hnsw_dot_indexes_registry_is_the_four_ann_columns( self ):
        self.assertEqual(
            set( vsm.HNSW_DOT_INDEXES ),
            {
                ( "input_and_output",     "input_embedding" ),
                ( "prediction_decisions", "question_embedding" ),
                ( "solution_snapshots",   "question_embedding" ),
                ( "solution_snapshots",   "code_embedding" ),
            },
        )

    def test_non_ann_vector_columns_have_no_hnsw_index( self ):
        # These vector columns are NOT ANN-searched → must carry no HNSW index.
        ann = set( vsm.HNSW_DOT_INDEXES )
        for m in vsm.VECTOR_STORE_MODELS:
            table = Base.metadata.tables[ m.__tablename__ ]
            for c in table.columns:
                if isinstance( c.type, Vector ) and ( table.name, c.name ) not in ann:
                    for idx in table.indexes:
                        opts = idx.dialect_options.get( "postgresql", {} )
                        self.assertFalse(
                            opts.get( "using" ) == "hnsw" and c.name in idx.columns.keys(),
                            f"{table.name}.{c.name} unexpectedly has an HNSW index",
                        )

    def test_hnsw_index_helper_builds_ip_ops_with_build_params( self ):
        idx = vsm._hnsw_index( "idx_probe", "some_col" )
        opts = idx.dialect_options[ "postgresql" ]
        self.assertEqual( opts[ "using" ], "hnsw" )
        self.assertEqual( opts[ "ops" ], { "some_col": "vector_ip_ops" } )
        self.assertEqual( opts[ "with" ], { "m": vsm.HNSW_M, "ef_construction": vsm.HNSW_EF_CONSTRUCTION } )


class TestScalarBtreeIndexes( unittest.TestCase ):

    def _index_names( self, table_name ):
        return { idx.name for idx in Base.metadata.tables[ table_name ].indexes }

    def test_kv_lookup_keys_have_btree_indexes( self ):
        self.assertIn( "idx_question_embeddings_question", self._index_names( "question_embeddings" ) )
        self.assertIn( "idx_embedding_cache_normalized_text", self._index_names( "embedding_cache" ) )
        self.assertIn( "idx_gist_cache_question_normalized", self._index_names( "gist_cache" ) )


class TestF6NormalizationColumn( unittest.TestCase ):

    def test_query_log_uses_underscore_not_space( self ):
        cols = set( Base.metadata.tables[ "query_log" ].columns.keys() )
        self.assertIn( "normalization_version", cols )
        self.assertNotIn( "normalization version", cols )


class TestListColumnsAreArrays( unittest.TestCase ):

    def test_solution_snapshots_code_columns_are_text_arrays( self ):
        table = Base.metadata.tables[ "solution_snapshots" ]
        for col in ( "code", "non_synonymous_questions" ):
            self.assertIsInstance( table.columns[ col ].type, ARRAY, f"{col} should be ARRAY" )


if __name__ == "__main__":
    unittest.main()
