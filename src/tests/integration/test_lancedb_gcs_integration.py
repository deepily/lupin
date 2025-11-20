"""
Integration tests for LanceDBSolutionManager with real GCS bucket.

Tests end-to-end GCS operations including manager initialization,
CRUD operations, question-based search, and data persistence.

Prerequisites:
- GCS bucket: gs://lupin-lancedb-test/
- GCS authentication configured (gcloud auth application-default login)
- Test configuration block: [Lupin: Testing-GCS]
"""

import os
import pytest
import time
from typing import List, Dict

# Bootstrap path - LUPIN_ROOT must be set
import sys
import os as os_sys

lupin_root = os_sys.environ.get( 'LUPIN_ROOT' )
if lupin_root is None:
    raise RuntimeError(
        "LUPIN_ROOT environment variable not set.\n"
        "Set it before running tests:\n"
        "  export LUPIN_ROOT=/path/to/project\n"
        "  pytest src/tests/integration/test_lancedb_gcs_integration.py"
    )

src_path = os_sys.path.join( lupin_root, 'src' )
if src_path not in sys.path:
    sys.path.insert( 0, src_path )

from cosa.memory.lancedb_solution_manager import LanceDBSolutionManager
from cosa.memory.solution_snapshot import SolutionSnapshot
from cosa.config.configuration_manager import ConfigurationManager


class TestLanceDBGCSIntegration:
    """Integration test suite for LanceDB with GCS backend."""

    @pytest.fixture(scope="class")
    def gcs_test_bucket_uri(self):
        """Provide GCS test bucket URI with timestamp to avoid conflicts."""
        return f"gs://lupin-lancedb-test/integration-test-{int( time.time() )}.lancedb"

    @pytest.fixture(scope="class")
    def gcs_config(self, gcs_test_bucket_uri):
        """Configuration for GCS-backed manager."""
        return {
            "storage_backend": "gcs",
            "gcs_uri": gcs_test_bucket_uri,
            "table_name": "solution_snapshots"
        }

    @pytest.fixture(scope="class")
    def gcs_manager(self, gcs_config, gcs_credentials_available):
        """
        Create LanceDB manager with GCS backend for testing.
        Uses a timestamped database to avoid conflicts between test runs.

        Requires:
            gcs_credentials_available: Ensures GCS auth validated before initialization
        """
        # gcs_credentials_available fixture already validated or skipped all tests
        manager = LanceDBSolutionManager( gcs_config, debug=True, verbose=False )
        manager.initialize()

        yield manager

        # Cleanup: GCS bucket has 7-day lifecycle, so manual cleanup not critical

    def test_manager_initialization_with_gcs(self, gcs_manager, gcs_test_bucket_uri):
        """
        Test that manager initializes correctly with GCS backend.
        """
        assert gcs_manager is not None
        assert gcs_manager.storage_backend == "gcs"
        assert gcs_manager.db_path == gcs_test_bucket_uri
        assert gcs_manager.table_name == "solution_snapshots"

    def test_add_snapshot_to_gcs(self, gcs_manager):
        """
        Test adding solution snapshots to GCS bucket.
        """
        # Create test snapshot
        snapshot = SolutionSnapshot(
            question="What is the factorial of 5?",
            answer="The factorial of 5 is 120",
            code=["def factorial(n):", "    if n <= 1: return 1", "    return n * factorial(n-1)"],
            debug=False
        )

        # Add snapshot to GCS
        result = gcs_manager.add_snapshot( snapshot )

        assert result is True

        # Small delay for GCS consistency
        time.sleep( 2 )

    def test_query_by_question_from_gcs(self, gcs_manager):
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
        gcs_manager.add_snapshot( snapshot )

        time.sleep( 2 )

        # Query for the snapshot
        results = gcs_manager.get_snapshots_by_question( "How do I sort a list?" )

        assert len( results ) > 0
        assert any( "sort" in snapshot.question.lower() for score, snapshot in results )

    def test_data_persistence_across_manager_instances(self, gcs_test_bucket_uri, gcs_config):
        """
        Test that data persists in GCS across manager instances.
        """
        # Create first manager instance and insert data
        manager1 = LanceDBSolutionManager( gcs_config, debug=False )
        manager1.initialize()

        snapshot = SolutionSnapshot(
            question="Test persistence question",
            answer="Test persistence answer",
            debug=False
        )

        manager1.add_snapshot( snapshot )

        del manager1  # Destroy first manager

        time.sleep( 2 )  # GCS consistency delay

        # Create second manager instance
        manager2 = LanceDBSolutionManager( gcs_config, debug=False )
        manager2.initialize()

        # Search for the persisted data
        results = manager2.get_snapshots_by_question( "Test persistence question" )

        assert len( results ) > 0
        assert any( "test persistence" in snapshot.question.lower() for score, snapshot in results )

    def test_multiple_snapshots_and_retrieval(self, gcs_manager):
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
            gcs_manager.add_snapshot( snapshot )

        time.sleep( 2 )

        # Verify we can retrieve them
        for q in questions:
            results = gcs_manager.get_snapshots_by_question( q )
            assert len( results ) > 0, f"Failed to retrieve: {q}"

    def test_configuration_block_loading(self):
        """
        Test that manager can be initialized from [Lupin: Testing-GCS] config block.
        """
        # Reset singleton to allow fresh initialization with GCS block
        ConfigurationManager.reset_for_testing()

        # Set up ConfigurationManager environment variable
        # ConfigurationManager internally prepends cu.get_project_root(), so use relative paths
        config_path = "/src/conf/lupin-app.ini"
        splainer_path = "/src/conf/lupin-app-splainer.ini"

        # Temporarily set environment variable
        # ConfigurationManager expects space-delimited format: key=value key=value
        cli_args_str = f"config_path={config_path} splainer_path={splainer_path} config_block_id=Lupin:+Testing-GCS"
        os.environ["LUPIN_CONFIG_MGR_CLI_ARGS_TEST"] = cli_args_str

        try:
            # Initialize ConfigurationManager
            config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS_TEST" )

            # Verify backend configuration
            backend = config_mgr.get( "storage_backend", default="local" )
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

    def test_update_existing_snapshot(self, gcs_manager):
        """
        Test updating an existing snapshot in GCS.
        """
        # Add initial snapshot
        original_snapshot = SolutionSnapshot(
            question="Original question for update test",
            answer="Original answer",
            debug=False
        )

        gcs_manager.add_snapshot( original_snapshot )
        time.sleep( 2 )

        # Update with same question but different answer
        updated_snapshot = SolutionSnapshot(
            question="Original question for update test",
            answer="Updated answer",
            code=["# Updated code"],
            debug=False
        )

        result = gcs_manager.add_snapshot( updated_snapshot )
        assert result is True

        time.sleep( 2 )

        # Verify update
        results = gcs_manager.get_snapshots_by_question( "Original question for update test" )
        assert len( results ) > 0

    def test_gcs_backend_handles_special_characters(self, gcs_manager):
        """
        Test that GCS backend handles questions with special characters.
        """
        snapshot = SolutionSnapshot(
            question="How do I use Python's f-strings?",
            answer="Use f-string syntax: f'{variable}'",
            debug=False
        )

        result = gcs_manager.add_snapshot( snapshot )
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
