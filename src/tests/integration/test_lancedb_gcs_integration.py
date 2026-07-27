"""
Integration tests for SolutionSnapshotManager with real GCS bucket.

Tests end-to-end GCS operations including manager initialization,
CRUD operations, question-based search, and data persistence.

GPU contention avoidance (Bug B fix 2026-04-22):
    Every embedding operation in this module is routed to the FastAPI
    server's `/api/embeddings/batch` endpoint via the `http_embedding_provider`
    autouse fixture (class-scoped monkeypatch of `EmbeddingProvider` and
    `EmbeddingManager` `.generate_embedding`). The pytest process never loads
    `ProseEmbeddingEngine` and never touches GPU 0. The server's already-
    loaded singleton serves every embedding via HTTP.

    See feedback memory `feedback_tests_call_server_api_not_instantiate`
    and design doc `src/rnd/v0.1.6/2026.04.22-tfe-model-flip-and-lancedb-cuda-oom-plan.md`.

Prerequisites:
    - GCS bucket: gs://lupin-lancedb-test/
    - GCS authentication configured (`gcloud auth application-default login`)
    - Test configuration block: [Lupin: Testing-GCS]
    - Test server running with companion users seeded
    - LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL/PASSWORD env vars
"""

import os
import pytest
import time
from typing import List, Dict

# Bootstrap path - LUPIN_ROOT must be set
import sys

lupin_root = os.environ.get( 'LUPIN_ROOT' )
if lupin_root is None:
    raise RuntimeError(
        "LUPIN_ROOT environment variable not set.\n"
        "Set it before running tests:\n"
        "  export LUPIN_ROOT=/path/to/project\n"
        "  pytest src/tests/integration/test_lancedb_gcs_integration.py"
    )

src_path = os.path.join( lupin_root, 'src' )
if src_path not in sys.path:
    sys.path.insert( 0, src_path )

from cosa.memory.lancedb_solution_manager import SolutionSnapshotManager
from cosa.memory.solution_snapshot import SolutionSnapshot
from cosa.config.configuration_manager import ConfigurationManager


class TestLanceDBGCSIntegration:
    """Integration test suite for LanceDB with GCS backend."""

    @pytest.fixture( scope="class", autouse=True )
    def http_embedding_provider( self, server_embedder ):
        """
        Route every embedding call in this test class to the server's
        HTTP endpoint. Monkeypatches `EmbeddingProvider.generate_embedding`
        and `EmbeddingManager.generate_embedding` at class scope so any
        code path in the CoSA memory stack (SolutionSnapshot.__init__,
        QuestionEmbeddingsTable.get_embedding, CanonicalSynonymsTable, etc.)
        is transparently redirected — no `ProseEmbeddingEngine` load, no
        GPU allocation in the pytest process.

        Restores originals on class teardown so other tests are unaffected.

        Ensures:
            - All `_embedding_provider.generate_embedding(...)` calls HTTP
            - All `_embedding_manager.generate_embedding(...)` calls HTTP
            - No `torch.cuda.*` memory is allocated by this process

        Raises:
            - RuntimeError if import of EmbeddingProvider/EmbeddingManager fails
        """
        from cosa.memory.embedding_provider import EmbeddingProvider
        from cosa.memory.embedding_manager  import EmbeddingManager

        original_provider = EmbeddingProvider.generate_embedding
        original_manager  = EmbeddingManager.generate_embedding

        def http_generate_provider( self, text, content_type="prose", **kwargs ):
            return server_embedder( text, content_type )

        def http_generate_manager( self, text, normalize_for_cache=True, **kwargs ):
            # EmbeddingManager produces prose embeddings; server endpoint handles normalization
            return server_embedder( text, "prose" )

        EmbeddingProvider.generate_embedding = http_generate_provider
        EmbeddingManager.generate_embedding  = http_generate_manager

        yield

        EmbeddingProvider.generate_embedding = original_provider
        EmbeddingManager.generate_embedding  = original_manager

    @pytest.fixture( scope="class", autouse=True )
    def _pin_lancedb_backend( self ):
        """
        Pin `vector store backend` to lancedb for every test in this class.

        Without this the ambient flag is `postgres` (live in [Lupin: Baseline] since
        2026-07-07), SolutionSnapshotManager routes to SolutionSnapshotRepository and
        the gs:// URI is never touched — so a GCS test suite exercises the SHARED
        postgres store and nothing in GCS. It also made
        `assert gcs_manager.db_path == gcs_test_bucket_uri` vacuous: db_path faithfully
        reported the value it was handed while the manager never used it. Decision
        2b20a6d6: a test either gets real isolation or it goes.

        Patched at the flag's single definition site — SolutionSnapshotManager,
        CanonicalSynonymsTable and QuestionEmbeddingsTable each resolve
        is_postgres_backend() from that module's globals at call time, so one patch
        covers all three. Class-scoped: the canonical-synonyms table is built lazily
        inside test methods, not only at manager construction.

        Ensures:
            - every test in this class runs against the GCS-backed LanceDB path
            - nothing in this class can reach the shared postgres store
        """
        from unittest.mock import patch
        from cosa.rest.db.repositories import vector_store_backend

        with patch.object( vector_store_backend, "get_vector_store_backend",
                           return_value=vector_store_backend.LANCEDB ):
            yield

    @pytest.fixture( scope="class" )
    def gcs_test_bucket_uri( self ):
        """Provide GCS test bucket URI with timestamp to avoid conflicts."""
        return f"gs://lupin-lancedb-test/integration-test-{int( time.time() )}.lancedb"

    @pytest.fixture( scope="class" )
    def gcs_config( self, gcs_test_bucket_uri ):
        """Configuration for GCS-backed manager."""
        return {
            "storage backend" : "gcs",
            "gcs_uri"         : gcs_test_bucket_uri,
            "table_name"      : "solution_snapshots"
        }

    @pytest.fixture( scope="class" )
    def gcs_manager( self, gcs_config, gcs_credentials_available ):
        """
        Create LanceDB manager with GCS backend for testing.
        Uses a timestamped database to avoid conflicts between test runs.

        Requires:
            gcs_credentials_available: Ensures GCS auth validated before initialization
        """
        manager = SolutionSnapshotManager( gcs_config, debug=True, verbose=False )

        # Control: the pin must actually have taken. If this ever fires, every test
        # below is exercising the SHARED postgres store rather than GCS, and the
        # db_path assertion in test_manager_initialization_with_gcs is vacuous (2b20a6d6).
        assert manager._use_postgres is False, "backend pin failed — tests would hit the shared postgres store"
        assert manager.db_path is not None,    "backend pin failed — no GCS URI resolved"

        manager.initialize()

        yield manager

        # Cleanup: GCS bucket has 7-day lifecycle, so manual cleanup not critical

    def test_manager_initialization_with_gcs( self, gcs_manager, gcs_test_bucket_uri ):
        """
        Test that manager initializes correctly with GCS backend.
        """
        assert gcs_manager is not None
        assert gcs_manager.storage_backend == "gcs"
        assert gcs_manager.db_path == gcs_test_bucket_uri
        assert gcs_manager.table_name == "solution_snapshots"

    def test_add_snapshot_to_gcs( self, gcs_manager ):
        """
        Test adding solution snapshots to GCS bucket.
        Embeddings flow through the HTTP endpoint via the autouse monkeypatch.
        """
        # Create test snapshot
        snapshot = SolutionSnapshot(
            question="What is the factorial of 5?",
            answer="The factorial of 5 is 120",
            code=["def factorial(n):", "    if n <= 1: return 1", "    return n * factorial(n-1)"],
            debug=False
        )

        # Add snapshot to GCS
        result = gcs_manager.save_snapshot( snapshot )

        assert result is True

        # Small delay for GCS consistency
        time.sleep( 2 )

    def test_query_by_question_from_gcs( self, gcs_manager ):
        """
        Test querying snapshots by question from GCS.
        """
        # Add a known snapshot
        snapshot = SolutionSnapshot(
            question="How do I sort a list?",
            answer="Use the sorted() function",
            code=["sorted_list = sorted(my_list)"],
            debug=False
        )
        gcs_manager.save_snapshot( snapshot )

        time.sleep( 2 )

        # Query for the snapshot
        results = gcs_manager.get_snapshots_by_question( "How do I sort a list?" )

        assert len( results ) > 0
        assert any( "sort" in snapshot.question.lower() for score, snapshot in results )

    @pytest.mark.xfail( reason="Known normalization mismatch between insert and query paths — not GCS-specific" )
    def test_data_persistence_across_manager_instances( self, gcs_test_bucket_uri, gcs_config ):
        """
        Test that data persists in GCS across manager instances.
        """
        # Create first manager instance and insert data
        manager1 = SolutionSnapshotManager( gcs_config, debug=False )
        manager1.initialize()

        snapshot = SolutionSnapshot(
            question="Test persistence question",
            answer="Test persistence answer",
            debug=False
        )

        manager1.save_snapshot( snapshot )

        del manager1  # Destroy first manager

        time.sleep( 2 )  # GCS consistency delay

        # Create second manager instance
        manager2 = SolutionSnapshotManager( gcs_config, debug=False )
        manager2.initialize()

        # Search for the persisted data
        results = manager2.get_snapshots_by_question( "Test persistence question" )

        assert len( results ) > 0
        assert any( "test persistence" in snapshot.question.lower() for score, snapshot in results )

    def test_multiple_snapshots_and_retrieval( self, gcs_manager ):
        """
        Test adding multiple snapshots and retrieving them.
        """
        # Add multiple related snapshots
        questions = [
            "Calculate fibonacci",
            "Find maximum value",
            "Check palindrome"
        ]

        for q in questions:
            snapshot = SolutionSnapshot(
                question=q,
                answer=f"Answer to {q}",
                debug=False
            )
            gcs_manager.save_snapshot( snapshot )

        time.sleep( 2 )

        # Verify we can retrieve them
        for q in questions:
            results = gcs_manager.get_snapshots_by_question( q )
            assert len( results ) > 0, f"Failed to retrieve: {q}"

    def test_configuration_block_loading( self ):
        """
        Test that manager can be initialized from [Lupin: Testing-GCS] config block.
        """
        # Set up ConfigurationManager environment variable
        # ConfigurationManager internally prepends cu.get_project_root(), so use relative paths
        config_path = "/src/conf/lupin-app.ini"
        splainer_path = "/src/conf/lupin-app-splainer.ini"

        # Temporarily set environment variable
        # ConfigurationManager expects space-delimited format: key=value key=value
        cli_args_str = f"config_path={config_path} splainer_path={splainer_path} config_block_id=Lupin:+Testing-GCS"
        os.environ["LUPIN_CONFIG_MGR_CLI_ARGS_TEST"] = cli_args_str

        try:
            # Initialize ConfigurationManager with atomic singleton reset
            # Using _reset_singleton=True ensures clean state before loading Testing-GCS block
            config_mgr = ConfigurationManager(
                env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS_TEST",
                _reset_singleton=True
            )

            # Verify backend configuration
            backend = config_mgr.get( "storage backend", default="local" )
            assert backend == "gcs", f"Expected GCS backend, got: {backend}"

            # Verify GCS URI configuration
            gcs_uri = config_mgr.get( "solution snapshots lancedb gcs uri", default=None )
            assert gcs_uri is not None
            assert gcs_uri.startswith( "gs://" )
            assert "lupin-lancedb-test" in gcs_uri

        finally:
            # Clean up environment
            if "LUPIN_CONFIG_MGR_CLI_ARGS_TEST" in os.environ:
                del os.environ["LUPIN_CONFIG_MGR_CLI_ARGS_TEST"]

    def test_update_existing_snapshot( self, gcs_manager ):
        """
        Test updating an existing snapshot in GCS.
        """
        # Add initial snapshot
        original_snapshot = SolutionSnapshot(
            question="Original question for update test",
            answer="Original answer",
            debug=False
        )

        gcs_manager.save_snapshot( original_snapshot )
        time.sleep( 2 )

        # Update with same question but different answer
        updated_snapshot = SolutionSnapshot(
            question="Original question for update test",
            answer="Updated answer",
            code=["# Updated code"],
            debug=False
        )

        result = gcs_manager.save_snapshot( updated_snapshot )
        assert result is True

        time.sleep( 2 )

        # Verify update
        results = gcs_manager.get_snapshots_by_question( "Original question for update test" )
        assert len( results ) > 0

    def test_gcs_backend_handles_special_characters( self, gcs_manager ):
        """
        Test that GCS backend handles questions with special characters.
        """
        snapshot = SolutionSnapshot(
            question="How do I use Python's f-strings?",
            answer="Use f-string syntax: f'{variable}'",
            debug=False
        )

        result = gcs_manager.save_snapshot( snapshot )
        assert result is True

        time.sleep( 2 )

        results = gcs_manager.get_snapshots_by_question( "How do I use Python's f-strings?" )
        assert len( results ) > 0


def quick_smoke_test():
    """
    Quick smoke test for integration test suite.
    """
    import cosa.utils.util as cu

    cu.print_banner( "LanceDB GCS Integration Tests - Smoke Test", prepend_nl=True )

    try:
        # Test 1: Import test module
        print( "Testing module import..." )
        import test_lancedb_gcs_integration
        print( "✓ Module imported successfully" )

        # Test 2: Check GCS authentication
        print( "Testing GCS authentication..." )
        import subprocess
        result = subprocess.run(
            ["gcloud", "auth", "application-default", "print-access-token"],
            capture_output=True,
            text=True
        )

        if result.returncode == 0:
            print( "✓ GCS authentication configured" )
        else:
            print( "✗ GCS authentication not configured" )
            print( "  Run: gcloud auth application-default login" )

        # Test 3: Check test bucket access
        print( "Testing GCS bucket access..." )
        result = subprocess.run(
            ["gcloud", "storage", "ls", "gs://lupin-lancedb-test/"],
            capture_output=True,
            text=True
        )

        if result.returncode == 0:
            print( "✓ GCS test bucket accessible" )
        else:
            print( "✗ GCS test bucket not accessible" )
            print( "  Bucket: gs://lupin-lancedb-test/" )

        # Test 4: Count test methods
        print( "Counting test methods..." )
        test_class = test_lancedb_gcs_integration.TestLanceDBGCSIntegration
        test_methods = [m for m in dir( test_class ) if m.startswith( 'test_' )]
        print( f"✓ Found {len( test_methods )} test methods" )

        print( "\n✓ Smoke test completed" )
        print( f"\nRun full integration tests with:" )
        print( f"  pytest {__file__} -v -s" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
