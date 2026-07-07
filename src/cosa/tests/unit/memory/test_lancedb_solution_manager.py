"""
Unit tests for cosa.memory.lancedb_solution_manager.SolutionSnapshotManager.

REWRITTEN 2026-05-31 by Sam 🎙️ (memory takeover, CoSA coverage campaign) — the
prior tests targeted a stale API: they constructed the manager with no `config`
(now required), patched module-level `CanonicalSynonymsTable` / `Normalizer`
(those are LOCAL imports inside get_snapshots_by_question, lazily bound to the
`_canonical_synonyms` / `_normalizer` instance attrs), and asserted a bare-
snapshot return shape (the method actually returns `[(score, snapshot)]` tuples
behind an `is_initialized()` gate, raising ValueError on empty input).

These tests drive the CURRENT hierarchical search (Level 1 verbatim → Level 2
normalized → Level 4 similarity) by injecting mock collaborators directly onto
the instance — legitimate unit isolation, not over-mocking of the unit under
test. Construction deps (QuestionEmbeddingsTable, db-path resolution) are mocked
so no real LanceDB/embedding I/O occurs. Reviewed by Mr. Radio (no self-audit).
"""
import os
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, MagicMock, patch

import pandas as pd

from cosa.memory.lancedb_solution_manager import SolutionSnapshotManager


_CONFIG = { "table_name": "test_solutions", "db_path": "/tmp/__sam_lancedb_test__", "storage backend": "local" }


def _make_manager( debug=False, verbose=False ):
    """
    Construct a SolutionSnapshotManager with its construction-time deps mocked
    (QuestionEmbeddingsTable + db-path resolution), then mark it initialized
    with a mock table so the search/retrieval gates pass.
    """
    with patch( "cosa.memory.lancedb_solution_manager.QuestionEmbeddingsTable" ), \
         patch.object( SolutionSnapshotManager, "_resolve_db_path", return_value=_CONFIG[ "db_path" ] ):
        mgr = SolutionSnapshotManager( _CONFIG, debug=debug, verbose=verbose )
    # Pin lancedb-mode hermetically (v0.2.0 §6 backend flag): post-cutover the INI
    # default resolved to `postgres`, so without this these lancedb-path tests would
    # dispatch into the _pg_* helpers and hit a live backend. _pg_manager() re-flips
    # this to True. Mirrors the convention at test_canonical_synonyms_delete.py:24.
    mgr._use_postgres  = False
    mgr._initialized   = True
    mgr.is_initialized = Mock( return_value=True )
    mgr._table         = MagicMock()
    return mgr


def _fake_snapshot( **overrides ):
    """
    Build a SimpleNamespace standing in for a SolutionSnapshot with every
    attribute that _snapshot_to_record / similarity searches read, all set to
    JSON-serializable values. SimpleNamespace (unlike Mock) honors getattr
    defaults for any attribute we deliberately omit via overrides=<sentinel>.
    """
    base = dict(
        question                      = "What time is it?",
        id_hash                       = "hash_abc",
        user_id                       = "user_1",
        question_normalized           = "what time is it",
        question_gist                 = "time query",
        answer                        = "It is noon.",
        answer_conversational         = "It's noon!",
        solution_summary              = "a summary",
        thoughts                      = "some thoughts",
        error                         = "",
        routing_command               = "agent router go to date and time",
        agent_class_name              = "DateAndTimeAgent",
        code                          = [ "import datetime", "print( datetime.datetime.now() )" ],
        solution_summary_gist         = "summary gist",
        code_returns                  = "string",
        code_example                  = "example",
        code_type                     = "code",
        programming_language          = "python",
        language_version              = "3.10",
        synonymous_questions          = { "what is the time": 100.0 },
        synonymous_question_gists      = { "time": 100.0 },
        non_synonymous_questions      = [ "what is the weather" ],
        last_question_asked           = "What time is it?",
        created_date                  = "2026-05-31 @ 12:00:00 EST",
        updated_date                  = "2026-05-31 @ 12:00:00 EST",
        run_date                      = "2026-05-31",
        runtime_stats                 = { "run_count": 1, "last_run_ms": 5, "total_ms": 5 },
        replay_history                = [ { "ts": "x" } ],
        replay_stats                  = { "count": 1 },
        is_cache_hit                  = False,
        answer_is_correct             = None,
        question_embedding            = [ 0.1, 0.2, 0.3, 0.4 ],
        question_normalized_embedding = [ 0.1, 0.2, 0.3, 0.4 ],
        question_gist_embedding       = [ 0.1, 0.2, 0.3, 0.4 ],
        solution_embedding            = [ 0.1, 0.2, 0.3, 0.4 ],
        code_embedding                = [ 0.1, 0.2, 0.3, 0.4 ],
        thoughts_embedding            = [ 0.1, 0.2, 0.3, 0.4 ],
        solution_gist_embedding       = [ 0.1, 0.2, 0.3, 0.4 ],
    )
    base.update( overrides )
    return SimpleNamespace( **base )


def _full_record( **overrides ):
    """
    Build a LanceDB record dict with every field _record_to_snapshot reads.
    JSON-string fields default to valid JSON; override with malformed strings
    to drive the deserialization except-branches.
    """
    base = {
        "id_hash"                       : "rec_hash",
        "user_id"                       : "user_1",
        "question"                      : "What time is it?",
        "question_normalized"           : "what time is it",
        "question_gist"                 : "time query",
        "answer"                        : "Noon.",
        "answer_conversational"         : "It's noon!",
        "solution_summary"              : "summary",
        "thoughts"                      : "thoughts",
        "error"                         : "",
        "routing_command"               : "agent router go to date and time",
        "agent_class_name"              : "DateAndTimeAgent",
        "code"                          : [ "print( 'hi' )" ],
        "solution_summary_gist"         : "sgist",
        "code_returns"                  : "str",
        "code_example"                  : "ex",
        "code_type"                     : "code",
        "programming_language"          : "python",
        "language_version"              : "3.10",
        "synonymous_questions"          : "{}",
        "synonymous_question_gists"     : "{}",
        "non_synonymous_questions"      : [ "other" ],
        "last_question_asked"           : "What time is it?",
        "created_date"                  : "2026-05-31 @ 12:00:00 EST",
        "updated_date"                  : "2026-05-31 @ 12:00:00 EST",
        "run_date"                      : "2026-05-31",
        "runtime_stats"                 : "{}",
        "replay_history"                : "[]",
        "replay_stats"                  : "{}",
        "is_cache_hit"                  : False,
        "answer_is_correct"             : "null",
        "question_embedding"            : [ 0.1, 0.2, 0.3, 0.4 ],
        "question_normalized_embedding" : [ 0.1, 0.2, 0.3, 0.4 ],
        "question_gist_embedding"       : [ 0.1, 0.2, 0.3, 0.4 ],
        "solution_embedding"            : [ 0.1, 0.2, 0.3, 0.4 ],
        "code_embedding"                : [ 0.1, 0.2, 0.3, 0.4 ],
        "thoughts_embedding"            : [ 0.1, 0.2, 0.3, 0.4 ],
        "solution_gist_embedding"       : [ 0.1, 0.2, 0.3, 0.4 ],
    }
    base.update( overrides )
    return base


class TestHierarchicalSearch( unittest.TestCase ):
    """get_snapshots_by_question — Level 1/2/4 hierarchy + early exits."""

    def test_level1_verbatim_early_exit( self ):
        """A Level-1 verbatim hit returns [(100.0, snapshot)] and skips normalize/Level-2."""
        mgr = _make_manager()
        canonical = Mock()
        canonical.find_exact_verbatim.return_value = "snap_id_1"
        normalizer = Mock()
        mgr._canonical_synonyms = canonical
        mgr._normalizer = normalizer

        snap = Mock( question="What time is it?" )
        mgr.get_snapshot_by_id = Mock( return_value=snap )

        result = mgr.get_snapshots_by_question( "What time is it?" )

        canonical.find_exact_verbatim.assert_called_once_with( "What time is it?" )
        normalizer.normalize.assert_not_called()                 # early exit before Level 2
        canonical.find_exact_normalized.assert_not_called()
        self.assertEqual( result, [ ( 100.0, snap ) ] )

    def test_level2_normalized_early_exit( self ):
        """No verbatim hit → normalize → Level-2 normalized hit returns [(100.0, snapshot)]."""
        mgr = _make_manager()
        canonical = Mock()
        canonical.find_exact_verbatim.return_value = None
        canonical.find_exact_normalized.return_value = "snap_id_2"
        normalizer = Mock()
        normalizer.normalize.return_value = "what time be it"
        mgr._canonical_synonyms = canonical
        mgr._normalizer = normalizer

        snap = Mock( question="what time be it" )
        mgr.get_snapshot_by_id = Mock( return_value=snap )

        result = mgr.get_snapshots_by_question( "What time is it?" )

        canonical.find_exact_verbatim.assert_called_once_with( "What time is it?" )
        normalizer.normalize.assert_called_once_with( "What time is it?" )
        canonical.find_exact_normalized.assert_called_once_with( "what time be it" )
        self.assertEqual( result, [ ( 100.0, snap ) ] )

    def test_level1_ghost_snapshot_auto_heals( self ):
        """A Level-1 synonym pointing at a missing snapshot triggers delete_by_snapshot_id."""
        mgr = _make_manager()
        canonical = Mock()
        canonical.find_exact_verbatim.return_value = "ghost_id"
        canonical.find_exact_normalized.return_value = None
        normalizer = Mock()
        normalizer.normalize.return_value = "norm"
        mgr._canonical_synonyms = canonical
        mgr._normalizer = normalizer
        mgr.get_snapshot_by_id = Mock( return_value=None )       # ghost: id resolves to nothing

        mgr.get_snapshots_by_question( "ghost question" )

        canonical.delete_by_snapshot_id.assert_any_call( "ghost_id" )

    def test_local_cache_exact_match( self ):
        """A verbatim hit in the in-memory cache returns [(100.0, snapshot)] via _record_to_snapshot."""
        mgr = _make_manager()
        mgr._canonical_synonyms = False                          # unavailable → skip Levels 1/2
        mgr._normalizer = False
        mgr._question_lookup = { "cached q": "id_hash_9" }
        mgr._id_lookup = { "id_hash_9": { "stub": "record" } }
        snap = Mock( question="cached q" )
        mgr._record_to_snapshot = Mock( return_value=snap )

        result = mgr.get_snapshots_by_question( "cached q" )

        mgr._record_to_snapshot.assert_called_once_with( { "stub": "record" } )
        self.assertEqual( result, [ ( 100.0, snap ) ] )


class TestGuards( unittest.TestCase ):
    """Initialization + input-validation gates."""

    def test_not_initialized_raises_runtime_error( self ):
        mgr = _make_manager()
        mgr.is_initialized = Mock( return_value=False )
        with self.assertRaises( RuntimeError ):
            mgr.get_snapshots_by_question( "anything" )

    def test_empty_question_raises_value_error( self ):
        mgr = _make_manager()
        with self.assertRaises( ValueError ):
            mgr.get_snapshots_by_question( "" )

    def test_none_question_raises_value_error( self ):
        mgr = _make_manager()
        with self.assertRaises( ValueError ):
            mgr.get_snapshots_by_question( None )

    def test_out_of_range_threshold_raises_value_error( self ):
        mgr = _make_manager()
        with self.assertRaises( ValueError ):
            mgr.get_snapshots_by_question( "q", threshold_question=150.0 )


class TestGetSnapshotById( unittest.TestCase ):
    """get_snapshot_by_id — query, not-found, not-initialized, error."""

    def test_returns_snapshot_when_found( self ):
        mgr = _make_manager()
        record = { "id_hash": "abc", "question": "Q?", "answer": "A" }
        mgr._table.search.return_value.where.return_value.limit.return_value.to_list.return_value = [ record ]
        snap = Mock( question="Q?" )
        mgr._record_to_snapshot = Mock( return_value=snap )

        result = mgr.get_snapshot_by_id( "abc" )
        self.assertIs( result, snap )
        mgr._record_to_snapshot.assert_called_once_with( record )

    def test_returns_none_when_not_found( self ):
        mgr = _make_manager()
        mgr._table.search.return_value.where.return_value.limit.return_value.to_list.return_value = []
        self.assertIsNone( mgr.get_snapshot_by_id( "missing" ) )

    def test_returns_none_when_not_initialized( self ):
        mgr = _make_manager()
        mgr._initialized = False
        self.assertIsNone( mgr.get_snapshot_by_id( "abc" ) )

    def test_returns_none_on_query_error( self ):
        mgr = _make_manager()
        mgr._table.search.side_effect = RuntimeError( "lancedb boom" )
        self.assertIsNone( mgr.get_snapshot_by_id( "abc" ) )


class TestInitAndConfig( unittest.TestCase ):
    """__init__ validation + debug-output branch."""

    def test_missing_table_name_raises_keyerror( self ):
        """A config without 'table_name' fails fast with KeyError (before any I/O)."""
        with self.assertRaises( KeyError ):
            SolutionSnapshotManager( { "db_path": "/tmp/x", "storage backend": "local" } )

    def test_debug_construction_sets_attributes( self ):
        """debug=True construction prints config AND wires backend/table/embedding_dim."""
        mgr = _make_manager( debug=True, verbose=True )
        self.assertEqual( mgr.storage_backend, "local" )
        self.assertEqual( mgr.table_name, "test_solutions" )
        self.assertEqual( mgr._nprobes, 20 )                 # config default
        self.assertIsInstance( mgr._embedding_dim, int )
        self.assertEqual( mgr._question_lookup, {} )
        self.assertEqual( mgr._id_lookup, {} )


class TestResolveDbPath( unittest.TestCase ):
    """_resolve_db_path — gcs / local / unknown backends + validation."""

    def setUp( self ):
        self.mgr = _make_manager()

    def test_gcs_valid_uri_returned( self ):
        self.mgr.debug = True                                # exercise the [GCS Backend] debug print
        uri = self.mgr._resolve_db_path( { "storage backend": "gcs", "gcs_uri": "gs://bucket/db.lancedb" } )
        self.assertEqual( uri, "gs://bucket/db.lancedb" )

    def test_gcs_missing_uri_raises( self ):
        with self.assertRaises( ValueError ):
            self.mgr._resolve_db_path( { "storage backend": "gcs" } )

    def test_gcs_bad_prefix_raises( self ):
        with self.assertRaises( ValueError ):
            self.mgr._resolve_db_path( { "storage backend": "gcs", "gcs_uri": "http://nope" } )

    def test_local_absolute_path_exists( self ):
        with patch( "cosa.memory.lancedb_solution_manager.os.path.exists", return_value=True ):
            self.mgr.debug = True                            # exercise the [Local Backend] debug print
            path = self.mgr._resolve_db_path( { "storage backend": "local", "db_path": "/data/lupin.lancedb" } )
        self.assertEqual( path, "/data/lupin.lancedb" )

    def test_local_src_relative_gets_project_root_prefix( self ):
        with patch( "cosa.memory.lancedb_solution_manager.du.get_project_root", return_value="/root" ), \
             patch( "cosa.memory.lancedb_solution_manager.os.path.exists", return_value=True ):
            path = self.mgr._resolve_db_path( { "storage backend": "local", "db_path": "/src/conf/db.lancedb" } )
        self.assertEqual( path, "/root/src/conf/db.lancedb" )

    def test_local_missing_db_path_raises( self ):
        with self.assertRaises( ValueError ):
            self.mgr._resolve_db_path( { "storage backend": "local" } )

    def test_local_parent_missing_raises( self ):
        # full_path missing AND its parent missing → not creatable → ValueError
        with patch( "cosa.memory.lancedb_solution_manager.os.path.exists", return_value=False ):
            with self.assertRaises( ValueError ):
                self.mgr._resolve_db_path( { "storage backend": "local", "db_path": "/no/such/dir/db.lancedb" } )

    def test_local_path_missing_but_parent_exists_is_creatable( self ):
        # full_path missing, parent present → returned for creation (no raise)
        def exists( p ):
            return p != "/data/new.lancedb"                  # parent /data exists, target does not
        with patch( "cosa.memory.lancedb_solution_manager.os.path.exists", side_effect=exists ):
            path = self.mgr._resolve_db_path( { "storage backend": "local", "db_path": "/data/new.lancedb" } )
        self.assertEqual( path, "/data/new.lancedb" )

    def test_unknown_backend_raises( self ):
        with self.assertRaises( ValueError ):
            self.mgr._resolve_db_path( { "storage backend": "sqlite" } )


class TestValidateEmbeddingDimensions( unittest.TestCase ):
    """_validate_embedding_dimensions — absent / match / mismatch-drops."""

    def setUp( self ):
        self.mgr = _make_manager()
        self.mgr._embedding_dim = 768

    def test_absent_table_is_noop( self ):
        db = Mock()
        db.table_names.return_value = []                     # table not present
        self.mgr._validate_embedding_dimensions( db, "solutions", "question_embedding" )
        db.open_table.assert_not_called()
        db.drop_table.assert_not_called()

    def test_matching_dim_does_not_drop( self ):
        db = Mock()
        db.table_names.return_value = [ "solutions" ]
        db.open_table.return_value.schema.field.return_value.type.list_size = 768
        self.mgr._validate_embedding_dimensions( db, "solutions", "question_embedding" )
        db.drop_table.assert_not_called()

    def test_mismatched_dim_drops_table( self ):
        db = Mock()
        db.table_names.return_value = [ "solutions" ]
        db.open_table.return_value.schema.field.return_value.type.list_size = 1536   # ≠ 768
        self.mgr._validate_embedding_dimensions( db, "solutions", "question_embedding" )
        db.drop_table.assert_called_once_with( "solutions" )


class TestSchemaAndConversion( unittest.TestCase ):
    """_get_schema, _snapshot_to_record (+ normalize_embedding), _ensure_list, _record_to_snapshot."""

    def setUp( self ):
        self.mgr = _make_manager()

    def test_get_schema_includes_core_fields( self ):
        schema = self.mgr._get_schema()
        names  = set( schema.names )
        self.assertIn( "id_hash", names )
        self.assertIn( "question_embedding", names )
        self.assertIn( "answer_is_correct", names )
        # embedding columns are fixed-size lists of the configured dim
        self.assertEqual( schema.field( "question_embedding" ).type.list_size, self.mgr._embedding_dim )

    def test_snapshot_to_record_maps_and_serializes( self ):
        snap   = _fake_snapshot()
        record = self.mgr._snapshot_to_record( snap )
        self.assertEqual( record[ "id_hash" ], "hash_abc" )
        self.assertEqual( record[ "question" ], "What time is it?" )
        self.assertEqual( record[ "user_id" ], "user_1" )
        # dict fields are JSON-serialized to strings
        self.assertEqual( json.loads( record[ "synonymous_questions" ] ), { "what is the time": 100.0 } )
        self.assertEqual( json.loads( record[ "runtime_stats" ] )[ "run_count" ], 1 )
        self.assertEqual( json.loads( record[ "replay_history" ] ), [ { "ts": "x" } ] )
        self.assertEqual( record[ "answer_is_correct" ], "null" )     # json.dumps(None)
        self.assertIsInstance( record[ "code" ], list )

    def test_snapshot_to_record_invalid_raises( self ):
        with self.assertRaises( ValueError ):
            self.mgr._snapshot_to_record( _fake_snapshot( question="" ) )
        with self.assertRaises( ValueError ):
            self.mgr._snapshot_to_record( None )

    def test_normalize_embedding_all_shapes( self ):
        self.mgr._embedding_dim = 4
        # empty → zeros
        rec = self.mgr._snapshot_to_record( _fake_snapshot( question_embedding=[] ) )
        self.assertEqual( rec[ "question_embedding" ], [ 0.0, 0.0, 0.0, 0.0 ] )
        # exact length → preserved (as floats)
        rec = self.mgr._snapshot_to_record( _fake_snapshot( question_embedding=[ 1, 2, 3, 4 ] ) )
        self.assertEqual( rec[ "question_embedding" ], [ 1.0, 2.0, 3.0, 4.0 ] )
        # shorter → padded with zeros
        rec = self.mgr._snapshot_to_record( _fake_snapshot( question_embedding=[ 9.0, 8.0 ] ) )
        self.assertEqual( rec[ "question_embedding" ], [ 9.0, 8.0, 0.0, 0.0 ] )
        # longer → truncated
        rec = self.mgr._snapshot_to_record( _fake_snapshot( question_embedding=[ 1, 2, 3, 4, 5, 6 ] ) )
        self.assertEqual( rec[ "question_embedding" ], [ 1.0, 2.0, 3.0, 4.0 ] )
        # non-list (truthy scalar) → zeros
        rec = self.mgr._snapshot_to_record( _fake_snapshot( question_embedding=3.14 ) )
        self.assertEqual( rec[ "question_embedding" ], [ 0.0, 0.0, 0.0, 0.0 ] )

    def test_ensure_list_variants( self ):
        self.assertEqual( self.mgr._ensure_list( None ), [] )
        self.assertEqual( self.mgr._ensure_list( "" ), [] )
        self.assertEqual( self.mgr._ensure_list( "x" ), [ "x" ] )
        self.assertEqual( self.mgr._ensure_list( [ 1, 2 ] ), [ 1, 2 ] )
        self.assertEqual( self.mgr._ensure_list( ( 1, 2 ) ), [ 1, 2 ] )   # iterable → list()
        self.assertEqual( self.mgr._ensure_list( 5 ), [] )                # not iterable → TypeError → []

    def test_record_to_snapshot_passes_fields_to_constructor( self ):
        record = _full_record()
        with patch( "cosa.memory.lancedb_solution_manager.SolutionSnapshot" ) as MockSnap:
            self.mgr._record_to_snapshot( record )
        kwargs = MockSnap.call_args.kwargs
        self.assertEqual( kwargs[ "question" ], "What time is it?" )
        self.assertEqual( kwargs[ "id_hash" ], "rec_hash" )
        self.assertEqual( kwargs[ "synonymous_questions" ], {} )          # parsed from "{}"
        self.assertEqual( kwargs[ "replay_history" ], [] )
        self.assertIsNone( kwargs[ "answer_is_correct" ] )                # parsed from "null"

    def test_record_to_snapshot_malformed_json_falls_back_to_defaults( self ):
        record = _full_record(
            synonymous_questions      = "{bad",
            synonymous_question_gists = "{bad",
            runtime_stats             = "not json",
            replay_history            = "[bad",
            replay_stats              = "{bad",
            answer_is_correct         = "not json",
        )
        with patch( "cosa.memory.lancedb_solution_manager.SolutionSnapshot" ) as MockSnap:
            self.mgr._record_to_snapshot( record )
        kwargs = MockSnap.call_args.kwargs
        self.assertEqual( kwargs[ "synonymous_questions" ], {} )
        self.assertEqual( kwargs[ "synonymous_question_gists" ], {} )
        self.assertEqual( kwargs[ "runtime_stats" ], {} )
        self.assertEqual( kwargs[ "replay_history" ], [] )
        self.assertEqual( kwargs[ "replay_stats" ], {} )
        self.assertIsNone( kwargs[ "answer_is_correct" ] )


class TestInitialize( unittest.TestCase ):
    """initialize() — open-existing / create-new / cache-load / failure paths."""

    def _df( self ):
        return pd.DataFrame( [
            { "question": "Q1", "id_hash": "h1" },
            { "question": "Q2", "id_hash": "h2" },
        ] )

    def test_opens_existing_table_and_loads_cache( self ):
        for debug in ( True, False ):
            with self.subTest( debug=debug ):
                mgr = _make_manager( debug=debug )
                mgr._validate_embedding_dimensions = Mock()   # validated separately
                mgr._initialized = False
                mock_table = MagicMock()
                mock_table.to_arrow.return_value.to_pandas.return_value = self._df()
                mock_db = Mock()
                mock_db.table_names.return_value = [ "test_solutions" ]
                mock_db.open_table.return_value = mock_table
                with patch( "cosa.memory.lancedb_solution_manager.lancedb" ) as mock_lancedb:
                    mock_lancedb.connect.return_value = mock_db
                    mgr.initialize()
                self.assertTrue( mgr._initialized )
                mock_db.open_table.assert_called_once_with( "test_solutions" )
                mock_db.create_table.assert_not_called()
                self.assertEqual( mgr._question_lookup, { "Q1": "h1", "Q2": "h2" } )
                self.assertEqual( set( mgr._id_lookup.keys() ), { "h1", "h2" } )

    def test_index_creation_failure_on_existing_is_swallowed( self ):
        mgr = _make_manager( debug=True )
        mgr._validate_embedding_dimensions = Mock()
        mgr._initialized = False
        mock_table = MagicMock()
        mock_table.create_scalar_index.side_effect = Exception( "index exists" )
        mock_table.to_arrow.return_value.to_pandas.return_value = self._df()
        mock_db = Mock()
        mock_db.table_names.return_value = [ "test_solutions" ]
        mock_db.open_table.return_value = mock_table
        with patch( "cosa.memory.lancedb_solution_manager.lancedb" ) as mock_lancedb:
            mock_lancedb.connect.return_value = mock_db
            mgr.initialize()
        self.assertTrue( mgr._initialized )                  # index failure does not abort init

    def test_creates_new_table_when_absent( self ):
        for debug in ( True, False ):
            with self.subTest( debug=debug ):
                mgr = _make_manager( debug=debug )
                mgr._validate_embedding_dimensions = Mock()
                mgr._initialized = False
                mock_table = MagicMock()
                mock_table.to_arrow.return_value.to_pandas.return_value = pd.DataFrame( columns=[ "question", "id_hash" ] )
                mock_db = Mock()
                mock_db.table_names.return_value = []        # absent → create path
                mock_db.create_table.return_value = mock_table
                with patch( "cosa.memory.lancedb_solution_manager.lancedb" ) as mock_lancedb:
                    mock_lancedb.connect.return_value = mock_db
                    mgr.initialize()
                mock_db.create_table.assert_called_once()
                mock_table.create_scalar_index.assert_called_once_with( "id_hash", replace=True )
                self.assertTrue( mgr._initialized )

    def test_cache_load_failure_is_swallowed( self ):
        mgr = _make_manager( debug=True )
        mgr._validate_embedding_dimensions = Mock()
        mgr._initialized = False
        mock_table = MagicMock()
        mock_table.to_arrow.side_effect = Exception( "empty table" )   # cache load blows up
        mock_db = Mock()
        mock_db.table_names.return_value = [ "test_solutions" ]
        mock_db.open_table.return_value = mock_table
        with patch( "cosa.memory.lancedb_solution_manager.lancedb" ) as mock_lancedb:
            mock_lancedb.connect.return_value = mock_db
            mgr.initialize()
        self.assertTrue( mgr._initialized )                  # init still succeeds with empty cache

    def test_connect_failure_resets_initialized_and_raises( self ):
        for debug in ( True, False ):
            with self.subTest( debug=debug ):
                mgr = _make_manager( debug=debug )
                mgr._validate_embedding_dimensions = Mock()
                mgr._initialized = True
                with patch( "cosa.memory.lancedb_solution_manager.lancedb" ) as mock_lancedb:
                    mock_lancedb.connect.side_effect = Exception( "no db" )
                    with self.assertRaises( Exception ):
                        mgr.initialize()
                self.assertFalse( mgr._initialized )


class TestReload( unittest.TestCase ):
    """reload() — gate, success, inner-cache-failure, connect-failure."""

    def test_not_initialized_raises( self ):
        mgr = _make_manager()
        mgr._initialized = False
        with self.assertRaises( RuntimeError ):
            mgr.reload()

    def test_success_refreshes_cache( self ):
        mgr = _make_manager( debug=True )
        mock_table = MagicMock()
        mock_table.to_pandas.return_value = pd.DataFrame( [ { "question": "Q1", "id_hash": "h1" } ] )
        mock_db = Mock()
        mock_db.open_table.return_value = mock_table
        with patch( "cosa.memory.lancedb_solution_manager.lancedb" ) as mock_lancedb:
            mock_lancedb.connect.return_value = mock_db
            mgr.reload()
        self.assertEqual( mgr._question_lookup, { "Q1": "h1" } )

    def test_inner_cache_failure_is_swallowed( self ):
        mgr = _make_manager( debug=True )
        mock_table = MagicMock()
        mock_table.to_pandas.side_effect = Exception( "empty" )
        mock_db = Mock()
        mock_db.open_table.return_value = mock_table
        with patch( "cosa.memory.lancedb_solution_manager.lancedb" ) as mock_lancedb:
            mock_lancedb.connect.return_value = mock_db
            mgr.reload()                                     # no raise — inner failure logged only
        self.assertEqual( mgr._question_lookup, {} )

    def test_connect_failure_raises( self ):
        mgr = _make_manager( debug=True )
        with patch( "cosa.memory.lancedb_solution_manager.lancedb" ) as mock_lancedb:
            mock_lancedb.connect.side_effect = Exception( "down" )
            with self.assertRaises( Exception ):
                mgr.reload()


class TestSaveSnapshot( unittest.TestCase ):
    """save_snapshot() — gates + new/dupe-guard/update dispatch + error."""

    def test_not_initialized_raises( self ):
        mgr = _make_manager()
        mgr.is_initialized = Mock( return_value=False )
        with self.assertRaises( RuntimeError ):
            mgr.save_snapshot( _fake_snapshot() )

    def test_invalid_snapshot_raises( self ):
        mgr = _make_manager()
        with self.assertRaises( ValueError ):
            mgr.save_snapshot( _fake_snapshot( question="" ) )

    def test_new_snapshot_inserts( self ):
        mgr = _make_manager( debug=True )
        mgr._question_lookup = {}                            # cache miss
        mgr._check_db_for_question = Mock( return_value=[] ) # db miss → truly new
        mgr._insert_new_snapshot   = Mock( return_value=True )
        mgr._update_existing_snapshot = Mock()
        result = mgr.save_snapshot( _fake_snapshot() )
        self.assertTrue( result )
        mgr._insert_new_snapshot.assert_called_once()
        mgr._update_existing_snapshot.assert_not_called()

    def test_dupe_guard_db_hit_on_cache_miss_updates( self ):
        mgr = _make_manager( debug=True )
        mgr._question_lookup = {}                            # cache miss
        mgr._check_db_for_question = Mock( return_value=[ { "id_hash": "h_db" } ] )   # but DB has it
        mgr._update_existing_snapshot = Mock( return_value=True )
        mgr._insert_new_snapshot      = Mock()
        result = mgr.save_snapshot( _fake_snapshot() )
        self.assertTrue( result )
        mgr._update_existing_snapshot.assert_called_once()
        mgr._insert_new_snapshot.assert_not_called()
        self.assertEqual( mgr._question_lookup[ "What time is it?" ], "h_db" )   # cache restored

    def test_existing_in_cache_updates( self ):
        mgr = _make_manager( debug=True )
        mgr._question_lookup = { "What time is it?": "h1" }  # cache hit
        mgr._update_existing_snapshot = Mock( return_value=True )
        mgr._insert_new_snapshot      = Mock()
        result = mgr.save_snapshot( _fake_snapshot() )
        self.assertTrue( result )
        mgr._update_existing_snapshot.assert_called_once()

    def test_exception_returns_false( self ):
        mgr = _make_manager( debug=True )
        mgr._question_lookup = {}
        mgr._check_db_for_question = Mock( side_effect=Exception( "boom" ) )
        self.assertFalse( mgr.save_snapshot( _fake_snapshot() ) )


class TestCheckDbForQuestion( unittest.TestCase ):
    """_check_db_for_question — SQL-escaped where + error → []."""

    def test_returns_records( self ):
        mgr = _make_manager()
        mgr._table.search.return_value.where.return_value.limit.return_value.to_list.return_value = [ { "id_hash": "h" } ]
        out = mgr._check_db_for_question( "What's up?" )
        self.assertEqual( out, [ { "id_hash": "h" } ] )
        # single quote doubled for the WHERE predicate
        mgr._table.search.return_value.where.assert_called_once_with( "question = 'What''s up?'" )

    def test_error_returns_empty( self ):
        mgr = _make_manager( debug=True )
        mgr._table.search.side_effect = Exception( "boom" )
        self.assertEqual( mgr._check_db_for_question( "q" ), [] )


class TestInsertNewSnapshot( unittest.TestCase ):
    """_insert_new_snapshot — add + cache update + synonyms; error re-raises."""

    def test_success_updates_cache_and_synonyms( self ):
        mgr = _make_manager( debug=True )
        snap = _fake_snapshot()
        mgr._snapshot_to_record    = Mock( return_value={ "id_hash": "h_new" } )
        mgr._update_canonical_synonyms = Mock()
        result = mgr._insert_new_snapshot( snap )
        self.assertTrue( result )
        mgr._table.add.assert_called_once()
        self.assertEqual( mgr._question_lookup[ snap.question ], "h_new" )
        self.assertEqual( mgr._id_lookup[ "h_new" ], { "id_hash": "h_new" } )
        mgr._update_canonical_synonyms.assert_called_once_with( snap )

    def test_error_reraises( self ):
        mgr = _make_manager( debug=True )
        mgr._snapshot_to_record = Mock( return_value={ "id_hash": "h" } )
        mgr._table.add.side_effect = Exception( "add failed" )
        with self.assertRaises( Exception ):
            mgr._insert_new_snapshot( _fake_snapshot() )


class TestUpdateExistingSnapshot( unittest.TestCase ):
    """_update_existing_snapshot — delegates to _full_replace with existing hash."""

    def test_delegates_with_existing_hash( self ):
        mgr = _make_manager()
        snap = _fake_snapshot()
        mgr._question_lookup = { snap.question: "h_existing" }
        mgr._id_lookup       = { "h_existing": { "id_hash": "h_existing" } }
        mgr._full_replace_snapshot = Mock( return_value=True )
        result = mgr._update_existing_snapshot( snap )
        self.assertTrue( result )
        mgr._full_replace_snapshot.assert_called_once_with( snap, db_id_hash="h_existing" )

    def test_missing_cache_entry_reraises( self ):
        mgr = _make_manager( debug=True )
        mgr._question_lookup = {}                            # KeyError inside → re-raise
        with self.assertRaises( Exception ):
            mgr._update_existing_snapshot( _fake_snapshot() )


class TestFullReplaceSnapshot( unittest.TestCase ):
    """_full_replace_snapshot — merge_insert + cache repopulate / fallback / override / error."""

    def _wire_merge( self, mgr ):
        merge = mgr._table.merge_insert.return_value
        merge.when_matched_update_all.return_value.when_not_matched_insert_all.return_value.execute.return_value = None

    def test_success_repopulates_from_fresh_db_read( self ):
        mgr = _make_manager()
        snap = _fake_snapshot()
        mgr._snapshot_to_record = Mock( return_value={ "id_hash": "h1", "runtime_stats": "{}" } )
        mgr._update_canonical_synonyms = Mock()
        self._wire_merge( mgr )
        fresh = { "id_hash": "h1", "runtime_stats": "{}", "question": snap.question }
        mgr._table.search.return_value.where.return_value.limit.return_value.to_list.return_value = [ fresh ]
        result = mgr._full_replace_snapshot( snap )
        self.assertTrue( result )
        self.assertEqual( mgr._id_lookup[ "h1" ], fresh )
        self.assertEqual( mgr._question_lookup[ snap.question ], "h1" )
        mgr._update_canonical_synonyms.assert_called_once_with( snap )

    def test_fresh_read_empty_falls_back_to_in_memory_record( self ):
        mgr = _make_manager()
        snap = _fake_snapshot()
        record = { "id_hash": "h2", "runtime_stats": "{}" }
        mgr._snapshot_to_record = Mock( return_value=record )
        mgr._update_canonical_synonyms = Mock()
        self._wire_merge( mgr )
        mgr._table.search.return_value.where.return_value.limit.return_value.to_list.return_value = []   # DB read empty
        result = mgr._full_replace_snapshot( snap )
        self.assertTrue( result )
        self.assertEqual( mgr._id_lookup[ "h2" ], record )      # fallback to in-memory record

    def test_db_id_hash_override_used_for_record( self ):
        mgr = _make_manager()
        snap = _fake_snapshot()
        record = { "id_hash": "object_hash", "runtime_stats": "{}" }
        mgr._snapshot_to_record = Mock( return_value=record )
        mgr._update_canonical_synonyms = Mock()
        self._wire_merge( mgr )
        mgr._table.search.return_value.where.return_value.limit.return_value.to_list.return_value = []
        # pre-seed cache so the BEFORE-merge invalidation branches execute
        mgr._id_lookup       = { "db_hash": {} }
        mgr._question_lookup = { snap.question: "db_hash" }
        mgr._full_replace_snapshot( snap, db_id_hash="db_hash" )
        self.assertEqual( record[ "id_hash" ], "db_hash" )      # override applied to the record
        merge_arg = mgr._table.merge_insert.return_value.when_matched_update_all.return_value \
                       .when_not_matched_insert_all.return_value.execute.call_args[ 0 ][ 0 ]
        self.assertEqual( merge_arg[ 0 ][ "id_hash" ], "db_hash" )

    def test_merge_error_reraises( self ):
        mgr = _make_manager( debug=True )
        mgr._snapshot_to_record = Mock( return_value={ "id_hash": "h", "runtime_stats": "{}" } )
        mgr._table.merge_insert.side_effect = Exception( "merge failed" )
        with self.assertRaises( Exception ):
            mgr._full_replace_snapshot( _fake_snapshot() )

    def test_debug_stats_verification_branch( self ):
        # debug=True drives the PRE/POST-MERGE stats prints + the consistency check
        mgr = _make_manager( debug=True )
        snap = _fake_snapshot()
        mgr._snapshot_to_record = Mock( return_value={ "id_hash": "h9", "runtime_stats": json.dumps( { "run_count": 2 } ) } )
        mgr._update_canonical_synonyms = Mock()
        mgr._verify_cache_consistency  = Mock( return_value=True )
        self._wire_merge( mgr )
        fresh = { "id_hash": "h9", "runtime_stats": json.dumps( { "run_count": 2 } ), "question": snap.question }
        mgr._table.search.return_value.where.return_value.limit.return_value.to_list.return_value = [ fresh ]
        self.assertTrue( mgr._full_replace_snapshot( snap ) )
        mgr._verify_cache_consistency.assert_called_once_with( "h9" )


class TestVerifyCacheConsistency( unittest.TestCase ):
    """_verify_cache_consistency — consistent / db-empty / cache-missing / mismatch / error."""

    def _wire_db( self, mgr, records ):
        mgr._table.search.return_value.where.return_value.limit.return_value.to_list.return_value = records

    def test_consistent_returns_true( self ):
        mgr = _make_manager( debug=True )
        stats = json.dumps( { "run_count": 3 } )
        self._wire_db( mgr, [ { "runtime_stats": stats } ] )
        mgr._id_lookup = { "h": { "runtime_stats": stats } }
        self.assertTrue( mgr._verify_cache_consistency( "h" ) )

    def test_db_empty_returns_false( self ):
        mgr = _make_manager( debug=True )
        self._wire_db( mgr, [] )
        self.assertFalse( mgr._verify_cache_consistency( "h" ) )

    def test_cache_missing_returns_false( self ):
        mgr = _make_manager( debug=True )
        self._wire_db( mgr, [ { "runtime_stats": "{}" } ] )
        mgr._id_lookup = {}                                  # DB has it, cache does not
        self.assertFalse( mgr._verify_cache_consistency( "h" ) )

    def test_run_count_mismatch_returns_false( self ):
        mgr = _make_manager( debug=True )
        self._wire_db( mgr, [ { "runtime_stats": json.dumps( { "run_count": 5 } ) } ] )
        mgr._id_lookup = { "h": { "runtime_stats": json.dumps( { "run_count": 1 } ) } }
        self.assertFalse( mgr._verify_cache_consistency( "h" ) )

    def test_error_returns_false( self ):
        mgr = _make_manager( debug=True )
        mgr._table.search.side_effect = Exception( "boom" )
        self.assertFalse( mgr._verify_cache_consistency( "h" ) )


class TestUpdateCanonicalSynonyms( unittest.TestCase ):
    """_update_canonical_synonyms — availability gate + add + error swallow."""

    def test_none_is_noop( self ):
        mgr = _make_manager( debug=True, verbose=True )
        mgr._canonical_synonyms = None
        mgr._update_canonical_synonyms( _fake_snapshot() )   # no raise, nothing to assert beyond no crash

    def test_false_is_noop( self ):
        mgr = _make_manager( debug=True, verbose=True )
        mgr._canonical_synonyms = False
        mgr._update_canonical_synonyms( _fake_snapshot() )

    def test_adds_primary_question( self ):
        mgr = _make_manager( debug=True, verbose=True )
        canonical = Mock()
        mgr._canonical_synonyms = canonical
        snap = _fake_snapshot( last_question_asked="What time is it?", id_hash="snap_h" )
        mgr._update_canonical_synonyms( snap )
        canonical.add_synonym.assert_called_once_with(
            snapshot_id="snap_h", question_verbatim="What time is it?", confidence_score=100.0, source="runtime"
        )

    def test_add_failure_swallowed( self ):
        mgr = _make_manager( debug=True )
        canonical = Mock()
        canonical.add_synonym.side_effect = Exception( "add boom" )
        mgr._canonical_synonyms = canonical
        mgr._update_canonical_synonyms( _fake_snapshot() )   # error logged, not raised

    def test_no_primary_question_skips_add( self ):
        mgr = _make_manager( debug=True, verbose=True )
        canonical = Mock()
        mgr._canonical_synonyms = canonical
        mgr._update_canonical_synonyms( _fake_snapshot( last_question_asked="" ) )
        canonical.add_synonym.assert_not_called()


class TestGetSnapshotByIdDebug( unittest.TestCase ):
    """get_snapshot_by_id — debug-branch coverage (found / not-found / not-init / error)."""

    def test_found_debug( self ):
        mgr = _make_manager( debug=True )
        record = { "id_hash": "abc", "question": "Q?" }
        mgr._table.search.return_value.where.return_value.limit.return_value.to_list.return_value = [ record ]
        snap = Mock( question="Q?" )
        mgr._record_to_snapshot = Mock( return_value=snap )
        self.assertIs( mgr.get_snapshot_by_id( "abc" ), snap )

    def test_not_found_debug( self ):
        mgr = _make_manager( debug=True )
        mgr._table.search.return_value.where.return_value.limit.return_value.to_list.return_value = []
        self.assertIsNone( mgr.get_snapshot_by_id( "missing" ) )

    def test_not_initialized_debug( self ):
        mgr = _make_manager( debug=True )
        mgr._initialized = False
        self.assertIsNone( mgr.get_snapshot_by_id( "abc" ) )

    def test_error_debug( self ):
        mgr = _make_manager( debug=True )
        mgr._table.search.side_effect = RuntimeError( "boom" )
        self.assertIsNone( mgr.get_snapshot_by_id( "abc" ) )


class TestDeleteSnapshot( unittest.TestCase ):
    """delete_snapshot — gates + cache-hit / cache-miss-db-hit / not-found / synonyms / error."""

    def test_not_initialized_raises( self ):
        mgr = _make_manager()
        mgr.is_initialized = Mock( return_value=False )
        with self.assertRaises( RuntimeError ):
            mgr.delete_snapshot( "q" )

    def test_empty_question_raises( self ):
        mgr = _make_manager()
        with self.assertRaises( ValueError ):
            mgr.delete_snapshot( "" )

    def test_cache_hit_deletes_and_cleans_synonyms( self ):
        mgr = _make_manager( debug=True )
        mgr._question_lookup = { "q": "h1" }
        mgr._id_lookup       = { "h1": { "id_hash": "h1" } }
        canonical = Mock()
        canonical.delete_by_snapshot_id.return_value = 2
        mgr._canonical_synonyms = canonical
        self.assertTrue( mgr.delete_snapshot( "q" ) )
        mgr._table.delete.assert_called_once_with( "id_hash = 'h1'" )
        canonical.delete_by_snapshot_id.assert_called_once_with( "h1" )
        self.assertNotIn( "q", mgr._question_lookup )
        self.assertNotIn( "h1", mgr._id_lookup )

    def test_cache_miss_db_hit_deletes( self ):
        mgr = _make_manager( debug=True )
        mgr._question_lookup = {}
        mgr._canonical_synonyms = None                       # synonyms cleanup skipped
        mgr._check_db_for_question = Mock( return_value=[ { "id_hash": "h_db" } ] )
        self.assertTrue( mgr.delete_snapshot( "q" ) )
        mgr._table.delete.assert_called_once_with( "id_hash = 'h_db'" )

    def test_not_found_returns_false( self ):
        mgr = _make_manager( debug=True )
        mgr._question_lookup = {}
        mgr._check_db_for_question = Mock( return_value=[] )
        self.assertFalse( mgr.delete_snapshot( "q" ) )
        mgr._table.delete.assert_not_called()

    def test_delete_error_returns_false( self ):
        mgr = _make_manager( debug=True )
        mgr._question_lookup = { "q": "h1" }
        mgr._id_lookup       = { "h1": {} }
        mgr._table.delete.side_effect = Exception( "boom" )
        self.assertFalse( mgr.delete_snapshot( "q" ) )


class TestHierarchicalSearchExtended( unittest.TestCase ):
    """get_snapshots_by_question — lazy init, level-2 ghost, normalizer-skip, Level-4 similarity."""

    def test_lazy_init_canonical_and_normalizer_success( self ):
        mgr = _make_manager( debug=True )
        mgr._canonical_synonyms = None                       # force lazy init
        mgr._normalizer         = None
        mgr._question_lookup     = {}
        mgr._question_embeddings_tbl = Mock()
        mgr._question_embeddings_tbl.get_embedding.return_value = []   # → returns [] after Level 4 short-circuit
        with patch( "cosa.memory.canonical_synonyms_table.CanonicalSynonymsTable" ) as MockCST, \
             patch( "cosa.memory.normalizer.Normalizer" ) as MockNorm:
            MockCST.return_value.find_exact_verbatim.return_value   = None
            MockCST.return_value.find_exact_normalized.return_value = None
            MockNorm.return_value.normalize.return_value = "norm q"
            result = mgr.get_snapshots_by_question( "What time is it?" )
        self.assertEqual( result, [] )
        self.assertIsNot( mgr._canonical_synonyms, None )    # lazily constructed
        self.assertIsNot( mgr._normalizer, None )

    def test_lazy_init_canonical_failure_marks_false( self ):
        mgr = _make_manager( debug=True )
        mgr._canonical_synonyms = None
        mgr._normalizer         = False
        mgr._question_lookup     = {}
        mgr._question_embeddings_tbl = Mock()
        mgr._question_embeddings_tbl.get_embedding.return_value = []
        with patch( "cosa.memory.canonical_synonyms_table.CanonicalSynonymsTable", side_effect=Exception( "no table" ) ):
            result = mgr.get_snapshots_by_question( "q" )
        self.assertEqual( result, [] )
        self.assertIs( mgr._canonical_synonyms, False )      # marked unavailable

    def test_lazy_init_normalizer_failure_marks_false( self ):
        mgr = _make_manager( debug=True )
        mgr._canonical_synonyms = None
        mgr._normalizer         = None
        mgr._question_lookup     = {}
        mgr._question_embeddings_tbl = Mock()
        mgr._question_embeddings_tbl.get_embedding.return_value = []
        with patch( "cosa.memory.canonical_synonyms_table.CanonicalSynonymsTable" ) as MockCST, \
             patch( "cosa.memory.normalizer.Normalizer", side_effect=Exception( "no normalizer" ) ):
            MockCST.return_value.find_exact_verbatim.return_value = None
            result = mgr.get_snapshots_by_question( "q" )
        self.assertEqual( result, [] )
        self.assertIs( mgr._normalizer, False )

    def test_level2_ghost_auto_heals( self ):
        mgr = _make_manager()
        canonical = Mock()
        canonical.find_exact_verbatim.return_value   = None
        canonical.find_exact_normalized.return_value = "ghost_norm"
        mgr._canonical_synonyms = canonical
        normalizer = Mock()
        normalizer.normalize.return_value = "norm q"
        mgr._normalizer = normalizer
        mgr._question_lookup = {}
        mgr.get_snapshot_by_id = Mock( return_value=None )   # ghost at Level 2
        mgr._question_embeddings_tbl = Mock()
        mgr._question_embeddings_tbl.get_embedding.return_value = []
        mgr.get_snapshots_by_question( "q" )
        canonical.delete_by_snapshot_id.assert_any_call( "ghost_norm" )

    def test_normalizer_false_skips_level2( self ):
        mgr = _make_manager()
        canonical = Mock()
        canonical.find_exact_verbatim.return_value = None
        mgr._canonical_synonyms = canonical
        mgr._normalizer = False                              # Level 2 skipped entirely
        mgr._question_lookup = {}
        mgr._question_embeddings_tbl = Mock()
        mgr._question_embeddings_tbl.get_embedding.return_value = []
        result = mgr.get_snapshots_by_question( "q" )
        canonical.find_exact_normalized.assert_not_called()
        self.assertEqual( result, [] )

    def test_level4_similarity_results( self ):
        mgr = _make_manager( debug=True, verbose=True )
        mgr._canonical_synonyms = False
        mgr._normalizer         = False
        mgr._question_lookup     = {}
        mgr._question_embeddings_tbl = Mock()
        mgr._question_embeddings_tbl.get_embedding.return_value = [ 0.5 ] * 4
        records = [
            { "_distance": 0.1, "id_hash": "h1", "question": "Q1", "answer": "A1", "created_date": "2026-05-31" },
            { "_distance": 0.4, "id_hash": "h2", "question": "Q2", "answer": "A2", "created_date": "2026-05-31" },
        ]
        mgr._table.search.return_value.metric.return_value.nprobes.return_value.limit.return_value.to_list.return_value = records
        snaps = [ Mock( question="Q1" ), Mock( question="Q2" ) ]
        mgr._record_to_snapshot = Mock( side_effect=snaps )
        result = mgr.get_snapshots_by_question( "q" )
        # similarity = (1 - distance) * 100 → 90.0 and 60.0, sorted desc
        self.assertEqual( [ round( s, 1 ) for s, _ in result ], [ 90.0, 60.0 ] )

    def test_level4_empty_embedding_returns_empty( self ):
        mgr = _make_manager( debug=True )
        mgr._canonical_synonyms = False
        mgr._normalizer         = False
        mgr._question_lookup     = {}
        mgr._question_embeddings_tbl = Mock()
        mgr._question_embeddings_tbl.get_embedding.return_value = None   # embedding generation failed
        self.assertEqual( mgr.get_snapshots_by_question( "q" ), [] )

    def test_level4_search_exception_reraises( self ):
        mgr = _make_manager( debug=True )
        mgr._canonical_synonyms = False
        mgr._normalizer         = False
        mgr._question_lookup     = {}
        mgr._question_embeddings_tbl = Mock()
        mgr._question_embeddings_tbl.get_embedding.side_effect = Exception( "embed boom" )
        with self.assertRaises( Exception ):
            mgr.get_snapshots_by_question( "q" )


class TestCodeSimilarity( unittest.TestCase ):
    """get_snapshots_by_code_similarity — gates, empties, threshold, self-exclude, best-below, error."""

    def _wire( self, mgr, records ):
        mgr._table.search.return_value.metric.return_value.nprobes.return_value.limit.return_value.to_list.return_value = records

    def test_not_initialized_raises( self ):
        mgr = _make_manager()
        mgr.is_initialized = Mock( return_value=False )
        with self.assertRaises( RuntimeError ):
            mgr.get_snapshots_by_code_similarity( _fake_snapshot() )

    def test_none_exemplar_raises( self ):
        mgr = _make_manager()
        with self.assertRaises( ValueError ):
            mgr.get_snapshots_by_code_similarity( None )

    def test_bad_threshold_raises( self ):
        mgr = _make_manager()
        with self.assertRaises( ValueError ):
            mgr.get_snapshots_by_code_similarity( _fake_snapshot(), threshold=200.0 )

    def test_no_embedding_returns_empty( self ):
        mgr = _make_manager()
        self.assertEqual( mgr.get_snapshots_by_code_similarity( _fake_snapshot( code_embedding=[] ), debug=True ), [] )

    def test_zero_embedding_returns_empty( self ):
        mgr = _make_manager()
        self.assertEqual( mgr.get_snapshots_by_code_similarity( _fake_snapshot( code_embedding=[ 0.0 ] * 100 ), debug=True ), [] )

    def test_above_threshold_excludes_self( self ):
        mgr = _make_manager()
        exemplar = _fake_snapshot( id_hash="self_h", code_embedding=[ 0.5 ] * 4 )
        records = [
            { "_distance": 0.0, "id_hash": "self_h" },       # self → excluded
            { "_distance": 0.1, "id_hash": "h1" },           # 90% → kept
        ]
        self._wire( mgr, records )
        kept = Mock( question="kept" )
        mgr._record_to_snapshot = Mock( return_value=kept )
        result = mgr.get_snapshots_by_code_similarity( exemplar, threshold=85.0, debug=True )
        self.assertEqual( len( result ), 1 )
        self.assertEqual( round( result[ 0 ][ 0 ], 1 ), 90.0 )

    def test_best_below_threshold_included_when_none_pass( self ):
        mgr = _make_manager()
        exemplar = _fake_snapshot( id_hash="self_h", code_embedding=[ 0.5 ] * 4 )
        records = [ { "_distance": 0.5, "id_hash": "h1" } ]  # 50% < 85% threshold
        self._wire( mgr, records )
        mgr._record_to_snapshot = Mock( return_value=Mock( question="best" ) )
        result = mgr.get_snapshots_by_code_similarity( exemplar, threshold=85.0, ensure_top_result=True, debug=True )
        self.assertEqual( len( result ), 1 )                 # best-below-threshold rescued
        self.assertEqual( round( result[ 0 ][ 0 ], 1 ), 50.0 )

    def test_limit_truncates_results( self ):
        mgr = _make_manager()
        exemplar = _fake_snapshot( id_hash="self_h", code_embedding=[ 0.5 ] * 4, question="ex" )
        records = [ { "_distance": 0.0, "id_hash": f"h{i}" } for i in range( 5 ) ]
        self._wire( mgr, records )
        mgr._record_to_snapshot = Mock( side_effect=[ Mock( question=f"q{i}" ) for i in range( 5 ) ] )
        result = mgr.get_snapshots_by_code_similarity( exemplar, threshold=10.0, limit=2, exclude_self=False )
        self.assertEqual( len( result ), 2 )

    def test_search_error_reraises( self ):
        mgr = _make_manager()
        mgr._table.search.side_effect = Exception( "boom" )
        with self.assertRaises( Exception ):
            mgr.get_snapshots_by_code_similarity( _fake_snapshot( code_embedding=[ 0.5 ] * 4 ), debug=True )


class TestSolutionSimilarity( unittest.TestCase ):
    """get_snapshots_by_solution_similarity — mirror of code-similarity contract."""

    def _wire( self, mgr, records ):
        mgr._table.search.return_value.metric.return_value.nprobes.return_value.limit.return_value.to_list.return_value = records

    def test_not_initialized_raises( self ):
        mgr = _make_manager()
        mgr.is_initialized = Mock( return_value=False )
        with self.assertRaises( RuntimeError ):
            mgr.get_snapshots_by_solution_similarity( _fake_snapshot() )

    def test_none_exemplar_raises( self ):
        mgr = _make_manager()
        with self.assertRaises( ValueError ):
            mgr.get_snapshots_by_solution_similarity( None )

    def test_bad_threshold_raises( self ):
        mgr = _make_manager()
        with self.assertRaises( ValueError ):
            mgr.get_snapshots_by_solution_similarity( _fake_snapshot(), threshold=-5.0 )

    def test_no_embedding_returns_empty( self ):
        mgr = _make_manager()
        self.assertEqual( mgr.get_snapshots_by_solution_similarity( _fake_snapshot( solution_embedding=[] ), debug=True ), [] )

    def test_zero_embedding_returns_empty( self ):
        mgr = _make_manager()
        self.assertEqual( mgr.get_snapshots_by_solution_similarity( _fake_snapshot( solution_embedding=[ 0.0 ] * 100 ), debug=True ), [] )

    def test_above_threshold_kept( self ):
        mgr = _make_manager()
        exemplar = _fake_snapshot( id_hash="self_h", solution_embedding=[ 0.5 ] * 4 )
        records = [
            { "_distance": 0.0, "id_hash": "self_h" },       # self → excluded
            { "_distance": 0.05, "id_hash": "h1" },          # 95% → kept
        ]
        self._wire( mgr, records )
        mgr._record_to_snapshot = Mock( return_value=Mock( question="kept" ) )
        result = mgr.get_snapshots_by_solution_similarity( exemplar, threshold=85.0, debug=True )
        self.assertEqual( len( result ), 1 )
        self.assertEqual( round( result[ 0 ][ 0 ], 1 ), 95.0 )

    def test_best_below_threshold_included( self ):
        mgr = _make_manager()
        exemplar = _fake_snapshot( id_hash="self_h", solution_embedding=[ 0.5 ] * 4 )
        records = [ { "_distance": 0.6, "id_hash": "h1" } ]  # 40% < 85%
        self._wire( mgr, records )
        mgr._record_to_snapshot = Mock( return_value=Mock( question="best" ) )
        result = mgr.get_snapshots_by_solution_similarity( exemplar, threshold=85.0, ensure_top_result=True, debug=True )
        self.assertEqual( len( result ), 1 )
        self.assertEqual( round( result[ 0 ][ 0 ], 1 ), 40.0 )

    def test_search_error_reraises( self ):
        mgr = _make_manager()
        mgr._table.search.side_effect = Exception( "boom" )
        with self.assertRaises( Exception ):
            mgr.get_snapshots_by_solution_similarity( _fake_snapshot( solution_embedding=[ 0.5 ] * 4 ), debug=True )


class TestGetGists( unittest.TestCase ):
    """get_gists — gate + unique collection + error."""

    def test_not_initialized_raises( self ):
        mgr = _make_manager()
        mgr.is_initialized = Mock( return_value=False )
        with self.assertRaises( RuntimeError ):
            mgr.get_gists()

    def test_returns_unique_nonempty_gists( self ):
        mgr = _make_manager( debug=True )
        mgr._id_lookup = {
            "h1": { "question_gist": "g1" },
            "h2": { "question_gist": "g1" },                 # duplicate → collapsed
            "h3": { "question_gist": "g2" },
            "h4": { "question_gist": "" },                   # empty → skipped
        }
        self.assertEqual( sorted( mgr.get_gists() ), [ "g1", "g2" ] )

    def test_error_returns_empty( self ):
        mgr = _make_manager( debug=True )
        broken = Mock()
        broken.values.side_effect = Exception( "boom" )
        mgr._id_lookup = broken
        self.assertEqual( mgr.get_gists(), [] )


class TestGetStats( unittest.TestCase ):
    """get_stats — gate + storage-size walk + path-missing + error."""

    def test_not_initialized_raises( self ):
        mgr = _make_manager()
        mgr.is_initialized = Mock( return_value=False )
        with self.assertRaises( RuntimeError ):
            mgr.get_stats()

    def test_success_with_storage_size( self ):
        mgr = _make_manager( debug=True )
        mgr._question_lookup = { "q1": "h1", "q2": "h2" }
        with patch( "cosa.memory.lancedb_solution_manager.os.path.exists", return_value=True ), \
             patch( "cosa.memory.lancedb_solution_manager.os.walk", return_value=[ ( "/db", [], [ "a", "b" ] ) ] ), \
             patch( "cosa.memory.lancedb_solution_manager.os.path.getsize", return_value=1024 * 1024 ):
            stats = mgr.get_stats()
        self.assertEqual( stats[ "total_snapshots" ], 2 )
        self.assertEqual( stats[ "backend_type" ], "lancedb" )
        self.assertEqual( stats[ "storage_size_mb" ], 2.0 )  # 2 files × 1 MB

    def test_missing_path_zero_storage( self ):
        mgr = _make_manager()
        mgr._question_lookup = { "q1": "h1" }
        with patch( "cosa.memory.lancedb_solution_manager.os.path.exists", return_value=False ):
            stats = mgr.get_stats()
        self.assertEqual( stats[ "storage_size_mb" ], 0.0 )

    def test_error_returns_error_dict( self ):
        mgr = _make_manager( debug=True )
        with patch( "cosa.memory.lancedb_solution_manager.os.path.exists", side_effect=Exception( "boom" ) ):
            stats = mgr.get_stats()
        self.assertEqual( stats[ "status" ], "error" )
        self.assertIn( "error", stats )


class TestHealthCheck( unittest.TestCase ):
    """health_check — healthy / unhealthy / degraded permutations + error."""

    def test_healthy_when_all_good( self ):
        mgr = _make_manager()
        mgr._db    = Mock()
        mgr._table = Mock()
        mgr._question_lookup = { "q": "h" }
        with patch( "cosa.memory.lancedb_solution_manager.os.path.exists", return_value=True ), \
             patch( "cosa.memory.lancedb_solution_manager.os.access", return_value=True ):
            health = mgr.health_check()
        self.assertEqual( health[ "status" ], "healthy" )
        self.assertEqual( health[ "connection_status" ], "connected" )
        self.assertEqual( health[ "snapshot_count" ], 1 )

    def test_unhealthy_when_path_missing_and_not_initialized( self ):
        # Path-missing sets unhealthy; only stays unhealthy if NOT initialized
        # (an initialized manager with a live connection downgrades to degraded instead).
        mgr = _make_manager()
        mgr.is_initialized = Mock( return_value=False )
        with patch( "cosa.memory.lancedb_solution_manager.os.path.exists", return_value=False ):
            health = mgr.health_check()
        self.assertEqual( health[ "status" ], "unhealthy" )

    def test_degraded_when_not_readable( self ):
        mgr = _make_manager()
        with patch( "cosa.memory.lancedb_solution_manager.os.path.exists", return_value=True ), \
             patch( "cosa.memory.lancedb_solution_manager.os.access", return_value=False ):
            health = mgr.health_check()
        self.assertEqual( health[ "status" ], "degraded" )

    def test_degraded_when_not_writable( self ):
        mgr = _make_manager()
        # readable but not writable: R_OK→True, W_OK→False
        def access( path, mode ):
            return mode == os.R_OK
        with patch( "cosa.memory.lancedb_solution_manager.os.path.exists", return_value=True ), \
             patch( "cosa.memory.lancedb_solution_manager.os.access", side_effect=access ):
            health = mgr.health_check()
        self.assertEqual( health[ "status" ], "degraded" )

    def test_degraded_when_initialized_but_no_connection( self ):
        mgr = _make_manager()
        mgr._db    = None
        mgr._table = None
        mgr._question_lookup = {}
        with patch( "cosa.memory.lancedb_solution_manager.os.path.exists", return_value=True ), \
             patch( "cosa.memory.lancedb_solution_manager.os.access", return_value=True ):
            health = mgr.health_check()
        self.assertEqual( health[ "status" ], "degraded" )

    def test_degraded_when_not_initialized( self ):
        mgr = _make_manager()
        mgr.is_initialized = Mock( return_value=False )
        with patch( "cosa.memory.lancedb_solution_manager.os.path.exists", return_value=True ), \
             patch( "cosa.memory.lancedb_solution_manager.os.access", return_value=True ):
            health = mgr.health_check()
        self.assertEqual( health[ "status" ], "degraded" )

    def test_degraded_when_snapshot_access_errors( self ):
        mgr = _make_manager()
        mgr._db    = Mock()
        mgr._table = Mock()
        broken = Mock()
        broken.__len__ = Mock( side_effect=Exception( "boom" ) )
        mgr._question_lookup = broken
        with patch( "cosa.memory.lancedb_solution_manager.os.path.exists", return_value=True ), \
             patch( "cosa.memory.lancedb_solution_manager.os.access", return_value=True ):
            health = mgr.health_check()
        self.assertEqual( health[ "status" ], "degraded" )

    def test_unhealthy_on_top_level_exception( self ):
        mgr = _make_manager()
        mgr.is_initialized = Mock( side_effect=Exception( "boom" ) )
        health = mgr.health_check()
        self.assertEqual( health[ "status" ], "unhealthy" )


class TestDebugFalseArcs( unittest.TestCase ):
    """
    debug=False / debug-arg=False companion passes. The methods above are exercised
    with debug ON; these runs close the `if self.debug:` / `if debug:` FALSE-side
    branch arcs so both sides of every debug guard are covered. Behavior asserted is
    debug-independent — these confirm the non-debug path produces identical results.
    """

    def _wire_merge( self, mgr ):
        merge = mgr._table.merge_insert.return_value
        merge.when_matched_update_all.return_value.when_not_matched_insert_all.return_value.execute.return_value = None

    def _wire_search( self, mgr, records ):
        mgr._table.search.return_value.metric.return_value.nprobes.return_value.limit.return_value.to_list.return_value = records

    # ---- _resolve_db_path (debug off) ----
    def test_resolve_gcs_no_debug( self ):
        mgr = _make_manager()
        self.assertEqual( mgr._resolve_db_path( { "storage backend": "gcs", "gcs_uri": "gs://b/d" } ), "gs://b/d" )

    def test_resolve_local_no_debug( self ):
        mgr = _make_manager()
        with patch( "cosa.memory.lancedb_solution_manager.os.path.exists", return_value=True ):
            self.assertEqual( mgr._resolve_db_path( { "storage backend": "local", "db_path": "/d/x.lancedb" } ), "/d/x.lancedb" )

    # ---- initialize (debug off) ----
    def test_initialize_index_fail_no_debug( self ):
        mgr = _make_manager()                                # debug False
        mgr._validate_embedding_dimensions = Mock()
        mgr._initialized = False
        mock_table = MagicMock()
        mock_table.create_scalar_index.side_effect = Exception( "exists" )
        mock_table.to_arrow.return_value.to_pandas.return_value = pd.DataFrame( [ { "question": "Q", "id_hash": "h" } ] )
        mock_db = Mock()
        mock_db.table_names.return_value = [ "test_solutions" ]
        mock_db.open_table.return_value = mock_table
        with patch( "cosa.memory.lancedb_solution_manager.lancedb" ) as mock_lancedb:
            mock_lancedb.connect.return_value = mock_db
            mgr.initialize()
        self.assertTrue( mgr._initialized )

    def test_initialize_cache_fail_no_debug( self ):
        mgr = _make_manager()
        mgr._validate_embedding_dimensions = Mock()
        mgr._initialized = False
        mock_table = MagicMock()
        mock_table.to_arrow.side_effect = Exception( "empty" )
        mock_db = Mock()
        mock_db.table_names.return_value = [ "test_solutions" ]
        mock_db.open_table.return_value = mock_table
        with patch( "cosa.memory.lancedb_solution_manager.lancedb" ) as mock_lancedb:
            mock_lancedb.connect.return_value = mock_db
            mgr.initialize()
        self.assertTrue( mgr._initialized )

    # ---- reload (debug off) ----
    def test_reload_success_no_debug( self ):
        mgr = _make_manager()
        mock_table = MagicMock()
        mock_table.to_pandas.return_value = pd.DataFrame( [ { "question": "Q1", "id_hash": "h1" } ] )
        mock_db = Mock()
        mock_db.open_table.return_value = mock_table
        with patch( "cosa.memory.lancedb_solution_manager.lancedb" ) as mock_lancedb:
            mock_lancedb.connect.return_value = mock_db
            mgr.reload()
        self.assertEqual( mgr._question_lookup, { "Q1": "h1" } )

    def test_reload_inner_fail_no_debug( self ):
        mgr = _make_manager()
        mock_table = MagicMock()
        mock_table.to_pandas.side_effect = Exception( "empty" )
        mock_db = Mock()
        mock_db.open_table.return_value = mock_table
        with patch( "cosa.memory.lancedb_solution_manager.lancedb" ) as mock_lancedb:
            mock_lancedb.connect.return_value = mock_db
            mgr.reload()
        self.assertEqual( mgr._question_lookup, {} )

    def test_reload_connect_fail_no_debug( self ):
        mgr = _make_manager()
        with patch( "cosa.memory.lancedb_solution_manager.lancedb" ) as mock_lancedb:
            mock_lancedb.connect.side_effect = Exception( "down" )
            with self.assertRaises( Exception ):
                mgr.reload()

    # ---- save_snapshot dispatch (debug off) ----
    def test_save_new_no_debug( self ):
        mgr = _make_manager()
        mgr._question_lookup = {}
        mgr._check_db_for_question = Mock( return_value=[] )
        mgr._insert_new_snapshot   = Mock( return_value=True )
        self.assertTrue( mgr.save_snapshot( _fake_snapshot() ) )

    def test_save_dupe_guard_no_debug( self ):
        mgr = _make_manager()
        mgr._question_lookup = {}
        mgr._check_db_for_question = Mock( return_value=[ { "id_hash": "h_db" } ] )
        mgr._update_existing_snapshot = Mock( return_value=True )
        self.assertTrue( mgr.save_snapshot( _fake_snapshot() ) )

    def test_save_existing_no_debug( self ):
        mgr = _make_manager()
        mgr._question_lookup = { "What time is it?": "h1" }
        mgr._update_existing_snapshot = Mock( return_value=True )
        self.assertTrue( mgr.save_snapshot( _fake_snapshot() ) )

    def test_save_exception_no_debug( self ):
        mgr = _make_manager()
        mgr._question_lookup = {}
        mgr._check_db_for_question = Mock( side_effect=Exception( "boom" ) )
        self.assertFalse( mgr.save_snapshot( _fake_snapshot() ) )

    # ---- _check_db_for_question / _insert / _update / _full_replace (debug off) ----
    def test_check_db_error_no_debug( self ):
        mgr = _make_manager()
        mgr._table.search.side_effect = Exception( "boom" )
        self.assertEqual( mgr._check_db_for_question( "q" ), [] )

    def test_insert_success_no_debug( self ):
        mgr = _make_manager()
        mgr._snapshot_to_record = Mock( return_value={ "id_hash": "h_new" } )
        mgr._update_canonical_synonyms = Mock()
        self.assertTrue( mgr._insert_new_snapshot( _fake_snapshot() ) )

    def test_insert_error_no_debug( self ):
        mgr = _make_manager()
        mgr._snapshot_to_record = Mock( return_value={ "id_hash": "h" } )
        mgr._table.add.side_effect = Exception( "boom" )
        with self.assertRaises( Exception ):
            mgr._insert_new_snapshot( _fake_snapshot() )

    def test_update_existing_error_no_debug( self ):
        mgr = _make_manager()
        mgr._question_lookup = {}
        with self.assertRaises( Exception ):
            mgr._update_existing_snapshot( _fake_snapshot() )

    def test_full_replace_success_no_debug( self ):
        mgr = _make_manager()
        snap = _fake_snapshot()
        mgr._snapshot_to_record = Mock( return_value={ "id_hash": "h1", "runtime_stats": "{}" } )
        mgr._update_canonical_synonyms = Mock()
        self._wire_merge( mgr )
        mgr._table.search.return_value.where.return_value.limit.return_value.to_list.return_value = [ { "id_hash": "h1", "runtime_stats": "{}" } ]
        self.assertTrue( mgr._full_replace_snapshot( snap ) )

    def test_full_replace_merge_error_no_debug( self ):
        mgr = _make_manager()
        mgr._snapshot_to_record = Mock( return_value={ "id_hash": "h", "runtime_stats": "{}" } )
        mgr._table.merge_insert.side_effect = Exception( "boom" )
        with self.assertRaises( Exception ):
            mgr._full_replace_snapshot( _fake_snapshot() )

    # ---- _verify_cache_consistency (debug off) ----
    def test_verify_all_outcomes_no_debug( self ):
        # consistent
        mgr = _make_manager()
        stats = json.dumps( { "run_count": 1 } )
        mgr._table.search.return_value.where.return_value.limit.return_value.to_list.return_value = [ { "runtime_stats": stats } ]
        mgr._id_lookup = { "h": { "runtime_stats": stats } }
        self.assertTrue( mgr._verify_cache_consistency( "h" ) )
        # db empty
        mgr = _make_manager()
        mgr._table.search.return_value.where.return_value.limit.return_value.to_list.return_value = []
        self.assertFalse( mgr._verify_cache_consistency( "h" ) )
        # cache missing
        mgr = _make_manager()
        mgr._table.search.return_value.where.return_value.limit.return_value.to_list.return_value = [ { "runtime_stats": "{}" } ]
        mgr._id_lookup = {}
        self.assertFalse( mgr._verify_cache_consistency( "h" ) )
        # mismatch
        mgr = _make_manager()
        mgr._table.search.return_value.where.return_value.limit.return_value.to_list.return_value = [ { "runtime_stats": json.dumps( { "run_count": 5 } ) } ]
        mgr._id_lookup = { "h": { "runtime_stats": json.dumps( { "run_count": 1 } ) } }
        self.assertFalse( mgr._verify_cache_consistency( "h" ) )
        # error
        mgr = _make_manager()
        mgr._table.search.side_effect = Exception( "boom" )
        self.assertFalse( mgr._verify_cache_consistency( "h" ) )

    # ---- _update_canonical_synonyms (debug off) ----
    def test_update_canonical_no_debug( self ):
        mgr = _make_manager()
        mgr._canonical_synonyms = None
        mgr._update_canonical_synonyms( _fake_snapshot() )
        mgr = _make_manager()
        canonical = Mock()
        mgr._canonical_synonyms = canonical
        mgr._update_canonical_synonyms( _fake_snapshot( last_question_asked="Q?", id_hash="s" ) )
        canonical.add_synonym.assert_called_once()
        mgr = _make_manager()
        canonical = Mock()
        canonical.add_synonym.side_effect = Exception( "boom" )
        mgr._canonical_synonyms = canonical
        mgr._update_canonical_synonyms( _fake_snapshot() )   # swallowed
        mgr = _make_manager()
        canonical = Mock()
        mgr._canonical_synonyms = canonical
        mgr._update_canonical_synonyms( _fake_snapshot( last_question_asked="" ) )
        canonical.add_synonym.assert_not_called()

    # ---- delete_snapshot (debug off) ----
    def test_delete_cache_hit_no_debug( self ):
        mgr = _make_manager()
        mgr._question_lookup = { "q": "h1" }
        mgr._id_lookup       = { "h1": {} }
        mgr._canonical_synonyms = Mock()
        self.assertTrue( mgr.delete_snapshot( "q" ) )

    def test_delete_cache_miss_db_hit_no_debug( self ):
        mgr = _make_manager()
        mgr._question_lookup = {}
        mgr._canonical_synonyms = None
        mgr._check_db_for_question = Mock( return_value=[ { "id_hash": "h_db" } ] )
        self.assertTrue( mgr.delete_snapshot( "q" ) )

    def test_delete_not_found_no_debug( self ):
        mgr = _make_manager()
        mgr._question_lookup = {}
        mgr._check_db_for_question = Mock( return_value=[] )
        self.assertFalse( mgr.delete_snapshot( "q" ) )

    def test_delete_error_no_debug( self ):
        mgr = _make_manager()
        mgr._question_lookup = { "q": "h1" }
        mgr._id_lookup       = { "h1": {} }
        mgr._table.delete.side_effect = Exception( "boom" )
        self.assertFalse( mgr.delete_snapshot( "q" ) )

    # ---- get_snapshots_by_question lazy-init (debug off) ----
    def test_lazy_init_success_no_debug( self ):
        mgr = _make_manager()
        mgr._canonical_synonyms = None
        mgr._normalizer         = None
        mgr._question_lookup     = {}
        mgr._question_embeddings_tbl = Mock()
        mgr._question_embeddings_tbl.get_embedding.return_value = []
        with patch( "cosa.memory.canonical_synonyms_table.CanonicalSynonymsTable" ) as MockCST, \
             patch( "cosa.memory.normalizer.Normalizer" ) as MockNorm:
            MockCST.return_value.find_exact_verbatim.return_value   = None
            MockCST.return_value.find_exact_normalized.return_value = None
            MockNorm.return_value.normalize.return_value = "n"
            self.assertEqual( mgr.get_snapshots_by_question( "q" ), [] )

    def test_lazy_init_canonical_fail_no_debug( self ):
        mgr = _make_manager()
        mgr._canonical_synonyms = None
        mgr._normalizer         = False
        mgr._question_lookup     = {}
        mgr._question_embeddings_tbl = Mock()
        mgr._question_embeddings_tbl.get_embedding.return_value = []
        with patch( "cosa.memory.canonical_synonyms_table.CanonicalSynonymsTable", side_effect=Exception( "x" ) ):
            self.assertEqual( mgr.get_snapshots_by_question( "q" ), [] )
        self.assertIs( mgr._canonical_synonyms, False )

    def test_lazy_init_normalizer_fail_no_debug( self ):
        mgr = _make_manager()
        mgr._canonical_synonyms = None
        mgr._normalizer         = None
        mgr._question_lookup     = {}
        mgr._question_embeddings_tbl = Mock()
        mgr._question_embeddings_tbl.get_embedding.return_value = []
        with patch( "cosa.memory.canonical_synonyms_table.CanonicalSynonymsTable" ) as MockCST, \
             patch( "cosa.memory.normalizer.Normalizer", side_effect=Exception( "x" ) ):
            MockCST.return_value.find_exact_verbatim.return_value = None
            self.assertEqual( mgr.get_snapshots_by_question( "q" ), [] )
        self.assertIs( mgr._normalizer, False )

    def test_level4_results_no_debug( self ):
        mgr = _make_manager()
        mgr._canonical_synonyms = False
        mgr._normalizer         = False
        mgr._question_lookup     = {}
        mgr._question_embeddings_tbl = Mock()
        mgr._question_embeddings_tbl.get_embedding.return_value = [ 0.5 ] * 4
        self._wire_search( mgr, [ { "_distance": 0.2, "id_hash": "h1", "question": "Q1", "answer": "A1", "created_date": "2026-05-31" } ] )
        mgr._record_to_snapshot = Mock( return_value=Mock( question="Q1" ) )
        result = mgr.get_snapshots_by_question( "q" )
        self.assertEqual( round( result[ 0 ][ 0 ], 1 ), 80.0 )

    # ---- code / solution similarity (debug-arg off + loop/limit arcs) ----
    def test_code_sim_success_no_debug( self ):
        mgr = _make_manager()
        self._wire_search( mgr, [ { "_distance": 0.05, "id_hash": "h1" } ] )
        mgr._record_to_snapshot = Mock( return_value=Mock( question="k" ) )
        result = mgr.get_snapshots_by_code_similarity( _fake_snapshot( id_hash="self", code_embedding=[ 0.5 ] * 4 ), threshold=85.0 )
        self.assertEqual( len( result ), 1 )

    def test_code_sim_two_below_threshold_only_first_tracked( self ):
        # second below-threshold record hits the `elif ... best is None` FALSE arc
        mgr = _make_manager()
        self._wire_search( mgr, [ { "_distance": 0.5, "id_hash": "h1" }, { "_distance": 0.6, "id_hash": "h2" } ] )
        mgr._record_to_snapshot = Mock( side_effect=[ Mock( question="a" ), Mock( question="b" ) ] )
        result = mgr.get_snapshots_by_code_similarity( _fake_snapshot( id_hash="self", code_embedding=[ 0.5 ] * 4 ), threshold=85.0, ensure_top_result=True )
        self.assertEqual( len( result ), 1 )                 # only the single best-below rescued
        self.assertEqual( round( result[ 0 ][ 0 ], 1 ), 50.0 )

    def test_code_sim_unlimited_limit_arc( self ):
        # limit <= 0 → the `if limit > 0` truncation FALSE arc
        mgr = _make_manager()
        self._wire_search( mgr, [ { "_distance": 0.0, "id_hash": "h1" } ] )
        mgr._record_to_snapshot = Mock( return_value=Mock( question="k" ) )
        result = mgr.get_snapshots_by_code_similarity( _fake_snapshot( id_hash="self", code_embedding=[ 0.5 ] * 4 ), threshold=10.0, limit=-1, exclude_self=False )
        self.assertEqual( len( result ), 1 )

    def test_solution_sim_success_no_debug( self ):
        mgr = _make_manager()
        self._wire_search( mgr, [ { "_distance": 0.05, "id_hash": "h1" } ] )
        mgr._record_to_snapshot = Mock( return_value=Mock( question="k" ) )
        result = mgr.get_snapshots_by_solution_similarity( _fake_snapshot( id_hash="self", solution_embedding=[ 0.5 ] * 4 ), threshold=85.0 )
        self.assertEqual( len( result ), 1 )

    def test_solution_sim_two_below_threshold( self ):
        mgr = _make_manager()
        self._wire_search( mgr, [ { "_distance": 0.5, "id_hash": "h1" }, { "_distance": 0.7, "id_hash": "h2" } ] )
        mgr._record_to_snapshot = Mock( side_effect=[ Mock( question="a" ), Mock( question="b" ) ] )
        result = mgr.get_snapshots_by_solution_similarity( _fake_snapshot( id_hash="self", solution_embedding=[ 0.5 ] * 4 ), threshold=85.0, ensure_top_result=True )
        self.assertEqual( len( result ), 1 )

    def test_solution_sim_unlimited_limit_arc( self ):
        mgr = _make_manager()
        self._wire_search( mgr, [ { "_distance": 0.0, "id_hash": "h1" } ] )
        mgr._record_to_snapshot = Mock( return_value=Mock( question="k" ) )
        result = mgr.get_snapshots_by_solution_similarity( _fake_snapshot( id_hash="self", solution_embedding=[ 0.5 ] * 4 ), threshold=10.0, limit=-1, exclude_self=False )
        self.assertEqual( len( result ), 1 )

    # ---- gists / stats (debug off) ----
    def test_gists_success_no_debug( self ):
        mgr = _make_manager()
        mgr._id_lookup = { "h1": { "question_gist": "g1" } }
        self.assertEqual( mgr.get_gists(), [ "g1" ] )

    def test_stats_success_no_debug( self ):
        mgr = _make_manager()
        mgr._question_lookup = { "q": "h" }
        with patch( "cosa.memory.lancedb_solution_manager.os.path.exists", return_value=False ):
            stats = mgr.get_stats()
        self.assertEqual( stats[ "total_snapshots" ], 1 )


class TestDebugOnlyLines( unittest.TestCase ):
    """
    Lines that execute ONLY when debug (and sometimes verbose) is ON, and which the
    debug-OFF originals never reach. Each asserts the surrounding behavior so the
    debug branch is covered without coverage-coloring.
    """

    def test_level1_found_debug_print( self ):
        mgr = _make_manager( debug=True )
        canonical = Mock()
        canonical.find_exact_verbatim.return_value = "s1"
        mgr._canonical_synonyms = canonical
        mgr._normalizer = Mock()
        snap = Mock( question="q" )
        mgr.get_snapshot_by_id = Mock( return_value=snap )
        self.assertEqual( mgr.get_snapshots_by_question( "q" ), [ ( 100.0, snap ) ] )

    def test_level2_found_debug_print( self ):
        mgr = _make_manager( debug=True )
        canonical = Mock()
        canonical.find_exact_verbatim.return_value   = None
        canonical.find_exact_normalized.return_value = "s2"
        mgr._canonical_synonyms = canonical
        normalizer = Mock()
        normalizer.normalize.return_value = "n"
        mgr._normalizer = normalizer
        snap = Mock( question="q" )
        mgr.get_snapshot_by_id = Mock( return_value=snap )
        self.assertEqual( mgr.get_snapshots_by_question( "q" ), [ ( 100.0, snap ) ] )

    def test_cache_hit_debug_print( self ):
        mgr = _make_manager( debug=True )
        mgr._canonical_synonyms = False
        mgr._normalizer         = False
        mgr._question_lookup     = { "q": "h" }
        mgr._id_lookup           = { "h": { "rec": 1 } }
        snap = Mock( question="q" )
        mgr._record_to_snapshot = Mock( return_value=snap )
        self.assertEqual( mgr.get_snapshots_by_question( "q" ), [ ( 100.0, snap ) ] )

    def test_level4_zeros_embedding_and_no_results_verbose( self ):
        # debug+verbose + a non-empty all-zeros embedding + empty search → zeros warning
        # AND the "no results" verbose branch both execute.
        mgr = _make_manager( debug=True, verbose=True )
        mgr._canonical_synonyms = False
        mgr._normalizer         = False
        mgr._question_lookup     = {}
        mgr._question_embeddings_tbl = Mock()
        mgr._question_embeddings_tbl.get_embedding.return_value = [ 0.0 ] * 4
        mgr._table.search.return_value.metric.return_value.nprobes.return_value.limit.return_value.to_list.return_value = []
        self.assertEqual( mgr.get_snapshots_by_question( "q" ), [] )

    def test_full_replace_stats_persisted_ok_debug( self ):
        # debug + matching pre/post run_count → the "stats successfully persisted" branch
        mgr = _make_manager( debug=True )
        snap = _fake_snapshot( runtime_stats={ "run_count": 7 } )
        stats_json = json.dumps( { "run_count": 7 } )
        mgr._snapshot_to_record = Mock( return_value={ "id_hash": "h7", "runtime_stats": stats_json } )
        mgr._update_canonical_synonyms = Mock()
        mgr._verify_cache_consistency  = Mock( return_value=True )
        merge = mgr._table.merge_insert.return_value
        merge.when_matched_update_all.return_value.when_not_matched_insert_all.return_value.execute.return_value = None
        fresh = { "id_hash": "h7", "runtime_stats": stats_json, "question": snap.question }
        mgr._table.search.return_value.where.return_value.limit.return_value.to_list.return_value = [ fresh ]
        self.assertTrue( mgr._full_replace_snapshot( snap ) )

    def test_update_canonical_debug_verbose_empty_synonyms( self ):
        # debug+verbose + falsy synonymous_questions → the trailing `if ...synonymous_questions:`
        # FALSE arc (method exits without the "skipping N synonymous questions" log).
        mgr = _make_manager( debug=True, verbose=True )
        canonical = Mock()
        mgr._canonical_synonyms = canonical
        mgr._update_canonical_synonyms( _fake_snapshot( last_question_asked="", synonymous_questions={} ) )
        canonical.add_synonym.assert_not_called()

    def test_get_snapshots_exception_no_debug( self ):
        mgr = _make_manager()                                # debug False
        mgr._canonical_synonyms = False
        mgr._normalizer         = False
        mgr._question_lookup     = {}
        mgr._question_embeddings_tbl = Mock()
        mgr._question_embeddings_tbl.get_embedding.side_effect = Exception( "boom" )
        with self.assertRaises( Exception ):
            mgr.get_snapshots_by_question( "q" )

    def test_code_sim_exception_no_debug( self ):
        mgr = _make_manager()
        mgr._table.search.side_effect = Exception( "boom" )
        with self.assertRaises( Exception ):
            mgr.get_snapshots_by_code_similarity( _fake_snapshot( code_embedding=[ 0.5 ] * 4 ) )

    def test_solution_sim_exception_no_debug( self ):
        mgr = _make_manager()
        mgr._table.search.side_effect = Exception( "boom" )
        with self.assertRaises( Exception ):
            mgr.get_snapshots_by_solution_similarity( _fake_snapshot( solution_embedding=[ 0.5 ] * 4 ) )

    def test_gists_error_no_debug( self ):
        mgr = _make_manager()
        broken = Mock()
        broken.values.side_effect = Exception( "boom" )
        mgr._id_lookup = broken
        self.assertEqual( mgr.get_gists(), [] )

    def test_stats_error_no_debug( self ):
        mgr = _make_manager()
        with patch( "cosa.memory.lancedb_solution_manager.os.path.exists", side_effect=Exception( "boom" ) ):
            stats = mgr.get_stats()
        self.assertEqual( stats[ "status" ], "error" )

    def test_full_replace_debug_empty_fresh_falls_back( self ):
        # debug + empty fresh-read → the debug-block `if fresh_records:` FALSE arc AND
        # the in-memory fallback debug print both execute.
        mgr = _make_manager( debug=True )
        snap = _fake_snapshot( runtime_stats={ "run_count": 7 } )
        record = { "id_hash": "h8", "runtime_stats": json.dumps( { "run_count": 7 } ) }
        mgr._snapshot_to_record = Mock( return_value=record )
        mgr._update_canonical_synonyms = Mock()
        mgr._verify_cache_consistency  = Mock( return_value=True )
        merge = mgr._table.merge_insert.return_value
        merge.when_matched_update_all.return_value.when_not_matched_insert_all.return_value.execute.return_value = None
        mgr._table.search.return_value.where.return_value.limit.return_value.to_list.return_value = []   # both reads empty
        self.assertTrue( mgr._full_replace_snapshot( snap ) )
        self.assertEqual( mgr._id_lookup[ "h8" ], record )


# ======================================================================================
# Postgres+pgvector backend (v0.2.0 Lane C batch 3b) — _use_postgres dispatch + _pg_* helpers.
#
# Isolation: get_db is patched to yield a MagicMock session; SolutionSnapshotRepository is
# patched where the _pg_* methods import it. Entities stand in as SimpleNamespace(**_full_record())
# so _pg_record_from_entity + _record_to_snapshot run for REAL against realistic row shapes.
# ======================================================================================

from contextlib import contextmanager as _contextmanager


def _pg_manager( debug=False, verbose=False ):
    """A _make_manager() flipped into postgres mode."""
    mgr = _make_manager( debug=debug, verbose=verbose )
    mgr._use_postgres = True
    return mgr


def _get_db_patch( session ):
    """Patch cosa.rest.db.database.get_db to yield the given mock session."""
    @_contextmanager
    def _cm():
        yield session
    return patch( "cosa.rest.db.database.get_db", side_effect=_cm )


def _get_db_raises( exc=None ):
    """Patch get_db to raise on call (drives the _pg_* except arcs)."""
    return patch( "cosa.rest.db.database.get_db", side_effect=( exc or Exception( "db boom" ) ) )


def _repo_patch( **returns ):
    """
    Patch SolutionSnapshotRepository (where _pg_* import it) with a MagicMock class.
    Each kwarg sets the instance method's return_value. Returns (patcher, repo_cls_mock).
    """
    repo_cls = MagicMock()
    for name, value in returns.items():
        getattr( repo_cls.return_value, name ).return_value = value
    return patch( "cosa.rest.db.repositories.solution_snapshot_repository.SolutionSnapshotRepository", repo_cls ), repo_cls


def _entity( **overrides ):
    """A SolutionSnapshot ORM stand-in carrying all _SNAPSHOT_RECORD_COLUMNS attrs."""
    return SimpleNamespace( **_full_record( **overrides ) )


def _mock_session( first=None ):
    """A MagicMock session whose .query(...).filter(...).first() yields `first`."""
    session = MagicMock()
    session.query.return_value.filter.return_value.first.return_value = first
    return session


class TestPgDispatch( unittest.TestCase ):
    """Each public method's `if self._use_postgres: return self._pg_*(...)` True arc."""

    def test_initialize_dispatches( self ):
        mgr = _pg_manager()
        mgr._pg_initialize = Mock( return_value=None )
        self.assertIsNone( mgr.initialize() )
        mgr._pg_initialize.assert_called_once_with()

    def test_reload_dispatches( self ):
        mgr = _pg_manager()
        mgr._pg_reload = Mock( return_value=None )
        mgr.reload()
        mgr._pg_reload.assert_called_once_with()

    def test_save_snapshot_dispatches( self ):
        mgr = _pg_manager()
        mgr._pg_save_snapshot = Mock( return_value=True )
        snap = _fake_snapshot()
        self.assertTrue( mgr.save_snapshot( snap ) )
        mgr._pg_save_snapshot.assert_called_once_with( snap )

    def test_get_snapshot_by_id_dispatches( self ):
        mgr = _pg_manager()
        mgr._pg_get_snapshot_by_id = Mock( return_value="SENTINEL" )
        self.assertEqual( mgr.get_snapshot_by_id( "h1" ), "SENTINEL" )
        mgr._pg_get_snapshot_by_id.assert_called_once_with( "h1" )

    def test_delete_snapshot_dispatches( self ):
        mgr = _pg_manager()
        mgr._pg_delete_snapshot = Mock( return_value=True )
        self.assertTrue( mgr.delete_snapshot( "q", True ) )
        mgr._pg_delete_snapshot.assert_called_once_with( "q", True )

    def test_get_snapshots_by_question_dispatches( self ):
        mgr = _pg_manager()
        mgr._pg_get_snapshots_by_question = Mock( return_value=[] )
        self.assertEqual( mgr.get_snapshots_by_question( "q", "g", 80.0, 70.0, 5, True ), [] )
        mgr._pg_get_snapshots_by_question.assert_called_once_with( "q", "g", 80.0, 70.0, 5, True )

    def test_get_snapshots_by_code_similarity_dispatches( self ):
        mgr = _pg_manager()
        mgr._pg_get_snapshots_by_code_similarity = Mock( return_value=[] )
        ex = _fake_snapshot()
        self.assertEqual( mgr.get_snapshots_by_code_similarity( ex, 60.0, 10, False, False, True ), [] )
        mgr._pg_get_snapshots_by_code_similarity.assert_called_once_with( ex, 60.0, 10, False, False, True )

    def test_get_snapshots_by_solution_similarity_dispatches( self ):
        mgr = _pg_manager()
        mgr._pg_get_snapshots_by_solution_similarity = Mock( return_value=[] )
        ex = _fake_snapshot()
        self.assertEqual( mgr.get_snapshots_by_solution_similarity( ex, 60.0, 10, False, False, True ), [] )
        mgr._pg_get_snapshots_by_solution_similarity.assert_called_once_with( ex, 60.0, 10, False, False, True )

    def test_get_gists_dispatches( self ):
        mgr = _pg_manager()
        mgr._pg_get_gists = Mock( return_value=[ "g" ] )
        self.assertEqual( mgr.get_gists(), [ "g" ] )
        mgr._pg_get_gists.assert_called_once_with()

    def test_get_stats_dispatches( self ):
        mgr = _pg_manager()
        mgr._pg_get_stats = Mock( return_value={ "backend_type": "postgres" } )
        self.assertEqual( mgr.get_stats()[ "backend_type" ], "postgres" )
        mgr._pg_get_stats.assert_called_once_with()

    def test_health_check_dispatches( self ):
        mgr = _pg_manager()
        mgr._pg_health_check = Mock( return_value={ "status": "healthy" } )
        self.assertEqual( mgr.health_check()[ "status" ], "healthy" )
        mgr._pg_health_check.assert_called_once_with()


class TestPgRecordFromEntity( unittest.TestCase ):
    """_pg_record_from_entity marshals an ORM entity to the 38-column record dict."""

    def test_all_columns_marshalled( self ):
        from cosa.memory.lancedb_solution_manager import _SNAPSHOT_RECORD_COLUMNS
        mgr = _pg_manager()
        entity = _entity( id_hash="xyz", question="hello?" )
        record = mgr._pg_record_from_entity( entity )
        self.assertEqual( set( record.keys() ), set( _SNAPSHOT_RECORD_COLUMNS ) )
        self.assertEqual( len( record ), 38 )
        self.assertEqual( record[ "id_hash" ], "xyz" )
        self.assertEqual( record[ "question" ], "hello?" )


class TestPgInitialize( unittest.TestCase ):
    """_pg_initialize — cache bypass, no in-memory lookups built."""

    def test_sets_initialized_debug_true( self ):
        mgr = _pg_manager( debug=True )
        mgr._initialized = False
        self.assertIsNone( mgr._pg_initialize() )
        self.assertTrue( mgr._initialized )

    def test_sets_initialized_debug_false( self ):
        mgr = _pg_manager( debug=False )
        mgr._initialized = False
        mgr._pg_initialize()
        self.assertTrue( mgr._initialized )


class TestPgReload( unittest.TestCase ):
    """_pg_reload — no-op, but gated on initialization."""

    def test_not_initialized_raises( self ):
        mgr = _pg_manager()
        mgr._initialized = False
        with self.assertRaises( RuntimeError ):
            mgr._pg_reload()

    def test_noop_debug_true( self ):
        mgr = _pg_manager( debug=True )
        mgr._initialized = True
        self.assertIsNone( mgr._pg_reload() )

    def test_noop_debug_false( self ):
        mgr = _pg_manager( debug=False )
        mgr._initialized = True
        self.assertIsNone( mgr._pg_reload() )


class TestPgSaveSnapshot( unittest.TestCase ):
    """_pg_save_snapshot — resolve-by-question + upsert, cache-free."""

    def test_not_initialized_raises( self ):
        mgr = _pg_manager()
        mgr.is_initialized = Mock( return_value=False )
        with self.assertRaises( RuntimeError ):
            mgr._pg_save_snapshot( _fake_snapshot() )

    def test_none_snapshot_raises( self ):
        mgr = _pg_manager()
        with self.assertRaises( ValueError ):
            mgr._pg_save_snapshot( None )

    def test_empty_question_raises( self ):
        mgr = _pg_manager()
        with self.assertRaises( ValueError ):
            mgr._pg_save_snapshot( _fake_snapshot( question="" ) )

    def test_insert_new_when_no_existing( self ):
        mgr = _pg_manager()
        snap = _fake_snapshot( question="brand new?", id_hash="new_hash" )
        session = _mock_session( first=None )
        p, repo = _repo_patch()
        with _get_db_patch( session ), p:
            self.assertTrue( mgr._pg_save_snapshot( snap ) )
        args, kwargs = repo.return_value.upsert_snapshot.call_args
        self.assertEqual( args[ 0 ], "new_hash" )      # id_hash popped + passed positionally
        self.assertNotIn( "id_hash", kwargs )
        self.assertEqual( kwargs[ "question" ], "brand new?" )

    def test_update_overrides_id_hash_when_existing( self ):
        mgr = _pg_manager()
        snap = _fake_snapshot( question="dupe?", id_hash="compound_hash" )
        existing = SimpleNamespace( id_hash="base_hash" )
        session = _mock_session( first=existing )
        p, repo = _repo_patch()
        with _get_db_patch( session ), p:
            self.assertTrue( mgr._pg_save_snapshot( snap ) )
        args, _ = repo.return_value.upsert_snapshot.call_args
        self.assertEqual( args[ 0 ], "base_hash" )     # Session-108 base-hash override

    def test_exception_returns_false_debug_true( self ):
        mgr = _pg_manager( debug=True )
        with _get_db_raises():
            self.assertFalse( mgr._pg_save_snapshot( _fake_snapshot() ) )

    def test_exception_returns_false_debug_false( self ):
        mgr = _pg_manager( debug=False )
        with _get_db_raises():
            self.assertFalse( mgr._pg_save_snapshot( _fake_snapshot() ) )


class TestPgGetSnapshotById( unittest.TestCase ):
    """_pg_get_snapshot_by_id — fetch + in-session marshalling."""

    def test_not_initialized_debug_true( self ):
        mgr = _pg_manager( debug=True )
        mgr._initialized = False
        self.assertIsNone( mgr._pg_get_snapshot_by_id( "h1" ) )

    def test_not_initialized_debug_false( self ):
        mgr = _pg_manager( debug=False )
        mgr._initialized = False
        self.assertIsNone( mgr._pg_get_snapshot_by_id( "h1" ) )

    def test_entity_none_debug_true( self ):
        mgr = _pg_manager( debug=True )
        p, repo = _repo_patch( get_snapshot_by_id=None )
        with _get_db_patch( _mock_session() ), p:
            self.assertIsNone( mgr._pg_get_snapshot_by_id( "missing" ) )

    def test_entity_none_debug_false( self ):
        mgr = _pg_manager( debug=False )
        p, repo = _repo_patch( get_snapshot_by_id=None )
        with _get_db_patch( _mock_session() ), p:
            self.assertIsNone( mgr._pg_get_snapshot_by_id( "missing" ) )

    def test_found_debug_true( self ):
        mgr = _pg_manager( debug=True )
        p, repo = _repo_patch( get_snapshot_by_id=_entity( id_hash="h1", question="what time?" ) )
        with _get_db_patch( _mock_session() ), p:
            snap = mgr._pg_get_snapshot_by_id( "h1" )
        self.assertEqual( snap.id_hash, "h1" )
        self.assertEqual( snap.question, "what time?" )

    def test_found_debug_false( self ):
        mgr = _pg_manager( debug=False )
        p, repo = _repo_patch( get_snapshot_by_id=_entity( id_hash="h2" ) )
        with _get_db_patch( _mock_session() ), p:
            snap = mgr._pg_get_snapshot_by_id( "h2" )
        self.assertEqual( snap.id_hash, "h2" )

    def test_exception_debug_true( self ):
        mgr = _pg_manager( debug=True )
        with _get_db_raises():
            self.assertIsNone( mgr._pg_get_snapshot_by_id( "h1" ) )

    def test_exception_debug_false( self ):
        mgr = _pg_manager( debug=False )
        with _get_db_raises():
            self.assertIsNone( mgr._pg_get_snapshot_by_id( "h1" ) )


class TestPgDeleteSnapshot( unittest.TestCase ):
    """_pg_delete_snapshot — resolve-by-question + delete + canonical cascade."""

    def test_not_initialized_raises( self ):
        mgr = _pg_manager()
        mgr.is_initialized = Mock( return_value=False )
        with self.assertRaises( RuntimeError ):
            mgr._pg_delete_snapshot( "q" )

    def test_empty_question_raises( self ):
        mgr = _pg_manager()
        with self.assertRaises( ValueError ):
            mgr._pg_delete_snapshot( "" )

    def test_not_found_returns_false_debug( self ):
        mgr = _pg_manager( debug=True )
        p, repo = _repo_patch()
        with _get_db_patch( _mock_session( first=None ) ), p:
            self.assertFalse( mgr._pg_delete_snapshot( "missing?" ) )

    def test_success_no_canonical( self ):
        mgr = _pg_manager()
        mgr._canonical_synonyms = None   # cascade guard skipped
        existing = SimpleNamespace( id_hash="h_del" )
        p, repo = _repo_patch()
        with _get_db_patch( _mock_session( first=existing ) ), p:
            self.assertTrue( mgr._pg_delete_snapshot( "gone?" ) )
        repo.return_value.delete_snapshot.assert_called_once_with( "h_del" )

    def test_success_with_canonical_cascade_debug( self ):
        mgr = _pg_manager( debug=True )
        mgr._canonical_synonyms = Mock()
        mgr._canonical_synonyms.delete_by_snapshot_id = Mock( return_value=3 )
        existing = SimpleNamespace( id_hash="h_del2" )
        p, repo = _repo_patch()
        with _get_db_patch( _mock_session( first=existing ) ), p:
            self.assertTrue( mgr._pg_delete_snapshot( "gone?" ) )
        mgr._canonical_synonyms.delete_by_snapshot_id.assert_called_once_with( "h_del2" )

    def test_exception_returns_false_debug_true( self ):
        mgr = _pg_manager( debug=True )
        with _get_db_raises():
            self.assertFalse( mgr._pg_delete_snapshot( "q" ) )

    def test_exception_returns_false_debug_false( self ):
        mgr = _pg_manager( debug=False )
        with _get_db_raises():
            self.assertFalse( mgr._pg_delete_snapshot( "q" ) )


class TestPgGetSnapshotsByQuestion( unittest.TestCase ):
    """_pg_get_snapshots_by_question — hierarchical L1/L2 + L4 pgvector, cache bypass."""

    def test_not_initialized_raises( self ):
        mgr = _pg_manager()
        mgr.is_initialized = Mock( return_value=False )
        with self.assertRaises( RuntimeError ):
            mgr._pg_get_snapshots_by_question( "q" )

    def test_empty_question_raises( self ):
        mgr = _pg_manager()
        with self.assertRaises( ValueError ):
            mgr._pg_get_snapshots_by_question( "" )

    def test_bad_threshold_question_raises( self ):
        mgr = _pg_manager()
        with self.assertRaises( ValueError ):
            mgr._pg_get_snapshots_by_question( "q", threshold_question=150.0 )

    def test_bad_threshold_gist_raises( self ):
        mgr = _pg_manager()
        with self.assertRaises( ValueError ):
            mgr._pg_get_snapshots_by_question( "q", threshold_gist=-1.0 )

    def test_lazy_init_components_fail_debug_true( self ):
        # canonical + normalizer imports raise → both set False (+debug prints), skip to L4
        mgr = _pg_manager( debug=True )
        mgr._canonical_synonyms = None
        mgr._normalizer = None
        mgr._question_embeddings_tbl.get_embedding = Mock( return_value=None )   # L4 → []
        with patch( "cosa.memory.canonical_synonyms_table.CanonicalSynonymsTable", side_effect=Exception( "no cst" ) ), \
             patch( "cosa.memory.normalizer.Normalizer", side_effect=Exception( "no norm" ) ):
            self.assertEqual( mgr._pg_get_snapshots_by_question( "q" ), [] )
        self.assertIs( mgr._canonical_synonyms, False )
        self.assertIs( mgr._normalizer, False )

    def test_lazy_init_components_fail_debug_false( self ):
        mgr = _pg_manager( debug=False )
        mgr._canonical_synonyms = None
        mgr._normalizer = None
        mgr._question_embeddings_tbl.get_embedding = Mock( return_value=None )
        with patch( "cosa.memory.canonical_synonyms_table.CanonicalSynonymsTable", side_effect=Exception( "no cst" ) ), \
             patch( "cosa.memory.normalizer.Normalizer", side_effect=Exception( "no norm" ) ):
            self.assertEqual( mgr._pg_get_snapshots_by_question( "q" ), [] )
        self.assertIs( mgr._canonical_synonyms, False )

    def test_lazy_init_components_succeed_debug( self ):
        # canonical + normalizer import OK (+debug prints); no exact match → L4 empty
        mgr = _pg_manager( debug=True )
        mgr._canonical_synonyms = None
        mgr._normalizer = None
        cst = Mock()
        cst.find_exact_verbatim   = Mock( return_value=None )
        cst.find_exact_normalized = Mock( return_value=None )
        norm = Mock()
        norm.normalize = Mock( return_value="normed" )
        mgr._question_embeddings_tbl.get_embedding = Mock( return_value=None )
        with patch( "cosa.memory.canonical_synonyms_table.CanonicalSynonymsTable", return_value=cst ), \
             patch( "cosa.memory.normalizer.Normalizer", return_value=norm ):
            self.assertEqual( mgr._pg_get_snapshots_by_question( "q" ), [] )

    def test_components_already_set_skip_lazy_init( self ):
        # both already truthy (not None) → skip both is-None blocks
        mgr = _pg_manager()
        mgr._canonical_synonyms = Mock( find_exact_verbatim=Mock( return_value=None ),
                                        find_exact_normalized=Mock( return_value=None ) )
        mgr._normalizer = Mock( normalize=Mock( return_value="n" ) )
        mgr._question_embeddings_tbl.get_embedding = Mock( return_value=None )
        self.assertEqual( mgr._pg_get_snapshots_by_question( "q" ), [] )

    def test_level1_verbatim_hit( self ):
        mgr = _pg_manager( debug=True )
        mgr._canonical_synonyms = Mock( find_exact_verbatim=Mock( return_value="sid1" ) )
        mgr._normalizer = Mock()
        snap = _fake_snapshot()
        mgr.get_snapshot_by_id = Mock( return_value=snap )
        result = mgr._pg_get_snapshots_by_question( "q" )
        self.assertEqual( result, [ ( 100.0, snap ) ] )
        mgr.get_snapshot_by_id.assert_called_once_with( "sid1" )

    def test_level1_ghost_then_l4_empty( self ):
        mgr = _pg_manager()
        mgr._canonical_synonyms = Mock( find_exact_verbatim=Mock( return_value="ghost1" ),
                                        find_exact_normalized=Mock( return_value=None ) )
        mgr._canonical_synonyms.delete_by_snapshot_id = Mock()
        mgr._normalizer = Mock( normalize=Mock( return_value="n" ) )
        mgr.get_snapshot_by_id = Mock( return_value=None )   # ghost
        mgr._question_embeddings_tbl.get_embedding = Mock( return_value=None )
        self.assertEqual( mgr._pg_get_snapshots_by_question( "q" ), [] )
        mgr._canonical_synonyms.delete_by_snapshot_id.assert_called_once_with( "ghost1" )

    def test_canonical_truthy_normalizer_false_skips_level2( self ):
        # canonical present (no verbatim match) but normalizer False → L2 block skipped → L4
        mgr = _pg_manager()
        mgr._canonical_synonyms = Mock( find_exact_verbatim=Mock( return_value=None ) )
        mgr._normalizer = False
        mgr._question_embeddings_tbl.get_embedding = Mock( return_value=None )
        self.assertEqual( mgr._pg_get_snapshots_by_question( "q" ), [] )

    def test_level2_normalized_hit( self ):
        mgr = _pg_manager( debug=True )
        mgr._canonical_synonyms = Mock( find_exact_verbatim=Mock( return_value=None ),
                                        find_exact_normalized=Mock( return_value="sid2" ) )
        mgr._normalizer = Mock( normalize=Mock( return_value="normed" ) )
        snap = _fake_snapshot()
        mgr.get_snapshot_by_id = Mock( return_value=snap )
        result = mgr._pg_get_snapshots_by_question( "q" )
        self.assertEqual( result, [ ( 100.0, snap ) ] )

    def test_level2_ghost_then_l4_empty( self ):
        mgr = _pg_manager()
        mgr._canonical_synonyms = Mock( find_exact_verbatim=Mock( return_value=None ),
                                        find_exact_normalized=Mock( return_value="ghost2" ) )
        mgr._canonical_synonyms.delete_by_snapshot_id = Mock()
        mgr._normalizer = Mock( normalize=Mock( return_value="normed" ) )
        mgr.get_snapshot_by_id = Mock( return_value=None )
        mgr._question_embeddings_tbl.get_embedding = Mock( return_value=None )
        self.assertEqual( mgr._pg_get_snapshots_by_question( "q" ), [] )
        mgr._canonical_synonyms.delete_by_snapshot_id.assert_called_once_with( "ghost2" )

    def test_level4_qe_empty_debug_true( self ):
        mgr = _pg_manager( debug=True )
        mgr._canonical_synonyms = False   # skip L1/L2 entirely
        mgr._normalizer = False
        mgr._question_embeddings_tbl.get_embedding = Mock( return_value=None )
        self.assertEqual( mgr._pg_get_snapshots_by_question( "q" ), [] )

    def test_level4_qe_empty_debug_false( self ):
        mgr = _pg_manager( debug=False )
        mgr._canonical_synonyms = False
        mgr._normalizer = False
        mgr._question_embeddings_tbl.get_embedding = Mock( return_value=None )
        self.assertEqual( mgr._pg_get_snapshots_by_question( "q" ), [] )

    def test_level4_hits_marshalled_and_sorted( self ):
        mgr = _pg_manager()
        mgr._canonical_synonyms = False
        mgr._normalizer = False
        mgr._question_embeddings_tbl.get_embedding = Mock( return_value=[ 0.1, 0.2, 0.3, 0.4 ] )
        hits = [ ( 80.0, _entity( id_hash="a" ) ), ( 95.0, _entity( id_hash="b" ) ) ]
        p, repo = _repo_patch( get_snapshots_by_question=hits )
        with _get_db_patch( _mock_session() ), p:
            result = mgr._pg_get_snapshots_by_question( "q", limit=5 )
        self.assertEqual( len( result ), 2 )
        self.assertEqual( result[ 0 ][ 0 ], 95.0 )    # sorted descending
        self.assertEqual( result[ 1 ][ 0 ], 80.0 )
        repo.return_value.get_snapshots_by_question.assert_called_once_with(
            [ 0.1, 0.2, 0.3, 0.4 ], threshold=None, limit=5 )

    def test_level4_limit_nonpositive_uses_100( self ):
        mgr = _pg_manager()
        mgr._canonical_synonyms = False
        mgr._normalizer = False
        mgr._question_embeddings_tbl.get_embedding = Mock( return_value=[ 0.1, 0.2, 0.3, 0.4 ] )
        p, repo = _repo_patch( get_snapshots_by_question=[] )
        with _get_db_patch( _mock_session() ), p:
            self.assertEqual( mgr._pg_get_snapshots_by_question( "q", limit=0 ), [] )
        _, kwargs = repo.return_value.get_snapshots_by_question.call_args
        self.assertEqual( kwargs[ "limit" ], 100 )

    def test_exception_reraises_debug_true( self ):
        mgr = _pg_manager( debug=True )
        mgr._canonical_synonyms = False
        mgr._normalizer = False
        mgr._question_embeddings_tbl.get_embedding = Mock( side_effect=Exception( "embed boom" ) )
        with self.assertRaises( Exception ):
            mgr._pg_get_snapshots_by_question( "q" )

    def test_exception_reraises_debug_false( self ):
        mgr = _pg_manager( debug=False )
        mgr._canonical_synonyms = False
        mgr._normalizer = False
        mgr._question_embeddings_tbl.get_embedding = Mock( side_effect=Exception( "embed boom" ) )
        with self.assertRaises( Exception ):
            mgr._pg_get_snapshots_by_question( "q" )


class TestPgSimilaritySearch( unittest.TestCase ):
    """_pg_similarity_search (via the code wrapper) + the solution wrapper delegation."""

    def test_not_initialized_raises( self ):
        mgr = _pg_manager()
        mgr.is_initialized = Mock( return_value=False )
        with self.assertRaises( RuntimeError ):
            mgr._pg_get_snapshots_by_code_similarity( _fake_snapshot() )

    def test_none_exemplar_raises( self ):
        mgr = _pg_manager()
        with self.assertRaises( ValueError ):
            mgr._pg_get_snapshots_by_code_similarity( None )

    def test_bad_threshold_raises( self ):
        mgr = _pg_manager()
        with self.assertRaises( ValueError ):
            mgr._pg_get_snapshots_by_code_similarity( _fake_snapshot(), threshold=101.0 )

    def test_empty_embedding_returns_empty( self ):
        mgr = _pg_manager()
        self.assertEqual( mgr._pg_get_snapshots_by_code_similarity( _fake_snapshot( code_embedding=[] ) ), [] )

    def test_zero_embedding_returns_empty( self ):
        mgr = _pg_manager()
        self.assertEqual(
            mgr._pg_get_snapshots_by_code_similarity( _fake_snapshot( code_embedding=[ 0.0 ] * 10 ) ), [] )

    def test_exclude_self_skips_matching_id( self ):
        mgr = _pg_manager()
        ex = _fake_snapshot( id_hash="me", code_embedding=[ 0.1, 0.2, 0.3, 0.4 ] )
        hits = [ ( 90.0, _entity( id_hash="me" ) ), ( 80.0, _entity( id_hash="other" ) ) ]
        p, repo = _repo_patch( get_snapshots_by_code_similarity=hits )
        with _get_db_patch( _mock_session() ), p:
            result = mgr._pg_get_snapshots_by_code_similarity( ex, threshold=50.0, exclude_self=True )
        self.assertEqual( len( result ), 1 )
        self.assertAlmostEqual( result[ 0 ][ 0 ], 80.0 )

    def test_below_threshold_best_below_appended( self ):
        mgr = _pg_manager()
        ex = _fake_snapshot( id_hash="me", code_embedding=[ 0.1, 0.2, 0.3, 0.4 ] )
        hits = [ ( 40.0, _entity( id_hash="a" ) ) ]
        p, repo = _repo_patch( get_snapshots_by_code_similarity=hits )
        with _get_db_patch( _mock_session() ), p:
            result = mgr._pg_get_snapshots_by_code_similarity(
                ex, threshold=50.0, exclude_self=False, ensure_top_result=True )
        self.assertEqual( len( result ), 1 )
        self.assertAlmostEqual( result[ 0 ][ 0 ], 40.0 )

    def test_below_threshold_best_below_only_first_kept( self ):
        # two below-threshold hits → elif fires only for the first (best_below already set)
        mgr = _pg_manager()
        ex = _fake_snapshot( id_hash="me", code_embedding=[ 0.1, 0.2, 0.3, 0.4 ] )
        hits = [ ( 40.0, _entity( id_hash="a" ) ), ( 30.0, _entity( id_hash="b" ) ) ]
        p, repo = _repo_patch( get_snapshots_by_code_similarity=hits )
        with _get_db_patch( _mock_session() ), p:
            result = mgr._pg_get_snapshots_by_code_similarity(
                ex, threshold=50.0, exclude_self=False, ensure_top_result=True )
        self.assertEqual( len( result ), 1 )
        self.assertAlmostEqual( result[ 0 ][ 0 ], 40.0 )   # the best (first) below-threshold

    def test_limit_truncation( self ):
        mgr = _pg_manager()
        ex = _fake_snapshot( id_hash="me", code_embedding=[ 0.1, 0.2, 0.3, 0.4 ] )
        hits = [ ( 90.0, _entity( id_hash="a" ) ), ( 85.0, _entity( id_hash="b" ) ),
                 ( 80.0, _entity( id_hash="c" ) ) ]
        p, repo = _repo_patch( get_snapshots_by_code_similarity=hits )
        with _get_db_patch( _mock_session() ), p:
            result = mgr._pg_get_snapshots_by_code_similarity(
                ex, threshold=50.0, limit=2, exclude_self=False )
        self.assertEqual( len( result ), 2 )

    def test_limit_nonpositive_no_truncation_exclude_self_false( self ):
        mgr = _pg_manager()
        ex = _fake_snapshot( id_hash="me", code_embedding=[ 0.1, 0.2, 0.3, 0.4 ] )
        hits = [ ( 90.0, _entity( id_hash="a" ) ), ( 85.0, _entity( id_hash="b" ) ) ]
        p, repo = _repo_patch( get_snapshots_by_code_similarity=hits )
        with _get_db_patch( _mock_session() ), p:
            result = mgr._pg_get_snapshots_by_code_similarity(
                ex, threshold=50.0, limit=0, exclude_self=False )
        self.assertEqual( len( result ), 2 )
        _, kwargs = repo.return_value.get_snapshots_by_code_similarity.call_args
        self.assertEqual( kwargs[ "limit" ], 100 )   # limit<=0 + no exclude_self → 100

    def test_no_results_no_ensure_top( self ):
        mgr = _pg_manager()
        ex = _fake_snapshot( id_hash="me", code_embedding=[ 0.1, 0.2, 0.3, 0.4 ] )
        hits = [ ( 40.0, _entity( id_hash="a" ) ) ]
        p, repo = _repo_patch( get_snapshots_by_code_similarity=hits )
        with _get_db_patch( _mock_session() ), p:
            result = mgr._pg_get_snapshots_by_code_similarity(
                ex, threshold=50.0, exclude_self=False, ensure_top_result=False )
        self.assertEqual( result, [] )   # below threshold + no ensure_top → empty

    def test_solution_wrapper_delegates( self ):
        mgr = _pg_manager()
        mgr._pg_similarity_search = Mock( return_value=[ ( 99.0, "snap" ) ] )
        ex = _fake_snapshot()
        result = mgr._pg_get_snapshots_by_solution_similarity( ex, threshold=70.0, limit=3 )
        self.assertEqual( result, [ ( 99.0, "snap" ) ] )
        mgr._pg_similarity_search.assert_called_once_with(
            ex, "solution_embedding", "get_snapshots_by_solution_similarity", 70.0, 3, True, True )

    def test_solution_similarity_end_to_end( self ):
        # exercise the solution wrapper's real body once (function-coverage of _pg_similarity_search
        # via the solution repo method name)
        mgr = _pg_manager()
        ex = _fake_snapshot( id_hash="me", solution_embedding=[ 0.1, 0.2, 0.3, 0.4 ] )
        hits = [ ( 88.0, _entity( id_hash="s1" ) ) ]
        p, repo = _repo_patch( get_snapshots_by_solution_similarity=hits )
        with _get_db_patch( _mock_session() ), p:
            result = mgr._pg_get_snapshots_by_solution_similarity( ex, threshold=50.0, exclude_self=False )
        self.assertEqual( len( result ), 1 )
        self.assertAlmostEqual( result[ 0 ][ 0 ], 88.0 )


class TestPgGetGists( unittest.TestCase ):
    """_pg_get_gists — distinct non-empty, order-preserving dedup."""

    def test_not_initialized_raises( self ):
        mgr = _pg_manager()
        mgr.is_initialized = Mock( return_value=False )
        with self.assertRaises( RuntimeError ):
            mgr._pg_get_gists()

    def test_dedup_and_skip_empty_debug_true( self ):
        mgr = _pg_manager( debug=True )
        p, repo = _repo_patch( get_gists=[ "g1", "g1", "g2", "" ] )
        with _get_db_patch( _mock_session() ), p:
            self.assertEqual( mgr._pg_get_gists(), [ "g1", "g2" ] )

    def test_dedup_debug_false( self ):
        mgr = _pg_manager( debug=False )
        p, repo = _repo_patch( get_gists=[ "g3" ] )
        with _get_db_patch( _mock_session() ), p:
            self.assertEqual( mgr._pg_get_gists(), [ "g3" ] )

    def test_exception_returns_empty_debug_true( self ):
        mgr = _pg_manager( debug=True )
        with _get_db_raises():
            self.assertEqual( mgr._pg_get_gists(), [] )

    def test_exception_returns_empty_debug_false( self ):
        mgr = _pg_manager( debug=False )
        with _get_db_raises():
            self.assertEqual( mgr._pg_get_gists(), [] )


class TestPgGetStats( unittest.TestCase ):
    """_pg_get_stats — postgres backend_type + zero storage size."""

    def test_not_initialized_raises( self ):
        mgr = _pg_manager()
        mgr.is_initialized = Mock( return_value=False )
        with self.assertRaises( RuntimeError ):
            mgr._pg_get_stats()

    def test_success_debug_true( self ):
        mgr = _pg_manager( debug=True )
        p, repo = _repo_patch( get_stats={ "total_snapshots": 5 } )
        with _get_db_patch( _mock_session() ), p:
            stats = mgr._pg_get_stats()
        self.assertEqual( stats[ "total_snapshots" ], 5 )
        self.assertEqual( stats[ "backend_type" ], "postgres" )
        self.assertEqual( stats[ "storage_size_mb" ], 0.0 )

    def test_success_debug_false( self ):
        mgr = _pg_manager( debug=False )
        p, repo = _repo_patch( get_stats={ "total_snapshots": 2 } )
        with _get_db_patch( _mock_session() ), p:
            stats = mgr._pg_get_stats()
        self.assertEqual( stats[ "total_snapshots" ], 2 )

    def test_exception_error_dict_debug_true( self ):
        mgr = _pg_manager( debug=True )
        with _get_db_raises():
            stats = mgr._pg_get_stats()
        self.assertEqual( stats[ "status" ], "error" )
        self.assertEqual( stats[ "backend_type" ], "postgres" )

    def test_exception_error_dict_debug_false( self ):
        mgr = _pg_manager( debug=False )
        with _get_db_raises():
            stats = mgr._pg_get_stats()
        self.assertEqual( stats[ "status" ], "error" )


class TestPgHealthCheck( unittest.TestCase ):
    """_pg_health_check — healthy / degraded / unhealthy."""

    def test_healthy_when_initialized( self ):
        mgr = _pg_manager()
        p, repo = _repo_patch( get_stats={ "total_snapshots": 3 } )
        with _get_db_patch( _mock_session() ), p:
            health = mgr._pg_health_check()
        self.assertEqual( health[ "status" ], "healthy" )
        self.assertEqual( health[ "connection_status" ], "connected" )
        self.assertEqual( health[ "snapshot_count" ], 3 )
        self.assertEqual( health[ "backend_type" ], "postgres" )

    def test_degraded_when_not_initialized( self ):
        mgr = _pg_manager()
        mgr.is_initialized = Mock( return_value=False )
        p, repo = _repo_patch( get_stats={ "total_snapshots": 0 } )
        with _get_db_patch( _mock_session() ), p:
            health = mgr._pg_health_check()
        self.assertEqual( health[ "status" ], "degraded" )

    def test_unhealthy_on_exception( self ):
        mgr = _pg_manager()
        with _get_db_raises():
            health = mgr._pg_health_check()
        self.assertEqual( health[ "status" ], "unhealthy" )
        self.assertEqual( health[ "connection_status" ], "disconnected" )
        self.assertTrue( health[ "errors" ] )


if __name__ == "__main__":
    unittest.main()
