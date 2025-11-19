"""
Unit tests for LanceDBSolutionManager multi-backend path resolution.

Tests the _resolve_db_path() method with various configurations to ensure
correct path resolution for both local filesystem and GCS backends.
"""

import os
import pytest
from unittest.mock import patch, MagicMock

# Bootstrap path - LUPIN_ROOT must be set
import sys
import os as os_sys

lupin_root = os_sys.environ.get( 'LUPIN_ROOT' )
if lupin_root is None:
    raise RuntimeError(
        "LUPIN_ROOT environment variable not set.\n"
        "Set it before running tests:\n"
        "  export LUPIN_ROOT=/path/to/project\n"
        "  pytest src/tests/unit/test_lancedb_gcs_manager.py"
    )

src_path = os_sys.path.join( lupin_root, 'src' )
if src_path not in sys.path:
    sys.path.insert( 0, src_path )

from cosa.memory.lancedb_solution_manager import LanceDBSolutionManager


class TestLanceDBManagerPathResolution:
    """Test suite for LanceDBSolutionManager path resolution logic."""

    def test_local_backend_with_relative_path_applies_project_root(self):
        """
        Test that local backend with /src/ prefix applies get_project_root().
        """
        config = {
            "storage_backend": "local",
            "db_path": "/src/conf/long-term-memory/test.lancedb",
            "table_name": "test_table"
        }

        with patch( 'cosa.memory.lancedb_solution_manager.du.get_project_root', return_value='/project/root' ):
            with patch( 'os.path.exists', return_value=True ):
                with patch( 'cosa.memory.lancedb_solution_manager.lancedb.connect' ):
                    manager = LanceDBSolutionManager( config, debug=False )

                    expected = '/project/root/src/conf/long-term-memory/test.lancedb'
                    assert manager.db_path == expected

    def test_local_backend_with_absolute_path_uses_as_is(self):
        """
        Test that local backend with absolute path (not /src/) uses path as-is.
        """
        config = {
            "storage_backend": "local",
            "db_path": "/absolute/path/to/test.lancedb",
            "table_name": "test_table"
        }

        with patch( 'os.path.exists', return_value=True ):
            with patch( 'cosa.memory.lancedb_solution_manager.lancedb.connect' ):
                manager = LanceDBSolutionManager( config, debug=False )

                assert manager.db_path == "/absolute/path/to/test.lancedb"

    def test_local_backend_missing_db_path_raises_error(self):
        """
        Test that local backend without db_path config key raises ValueError.
        """
        config = {
            "storage_backend": "local",
            # db_path intentionally missing
            "table_name": "test_table"
        }

        with pytest.raises( ValueError ) as exc_info:
            manager = LanceDBSolutionManager( config, debug=False )

        assert "storage_backend=local requires 'db_path' config key" in str( exc_info.value )

    def test_local_backend_parent_dir_not_exists_raises_error(self):
        """
        Test that local backend with non-existent parent directory raises ValueError.
        """
        config = {
            "storage_backend": "local",
            "db_path": "/nonexistent/parent/test.lancedb",
            "table_name": "test_table"
        }

        with patch( 'os.path.exists', return_value=False ):
            with pytest.raises( ValueError ) as exc_info:
                manager = LanceDBSolutionManager( config, debug=False )

            assert "parent directory does not exist" in str( exc_info.value )

    def test_gcs_backend_with_valid_uri(self):
        """
        Test that GCS backend with valid gs:// URI returns correctly.
        """
        config = {
            "storage_backend": "gcs",
            "gcs_uri": "gs://test-bucket/path/to/db.lancedb",
            "table_name": "test_table"
        }

        with patch( 'cosa.memory.lancedb_solution_manager.lancedb.connect' ):
            manager = LanceDBSolutionManager( config, debug=False )

            assert manager.db_path == "gs://test-bucket/path/to/db.lancedb"

    def test_gcs_backend_missing_gcs_uri_raises_error(self):
        """
        Test that GCS backend without gcs_uri config key raises ValueError.
        """
        config = {
            "storage_backend": "gcs",
            # gcs_uri intentionally missing
            "table_name": "test_table"
        }

        with pytest.raises( ValueError ) as exc_info:
            manager = LanceDBSolutionManager( config, debug=False )

        assert "storage_backend=gcs requires 'gcs_uri' config key" in str( exc_info.value )
        assert "Example:" in str( exc_info.value )

    def test_gcs_backend_invalid_uri_no_gs_prefix_raises_error(self):
        """
        Test that GCS backend with URI missing gs:// prefix raises ValueError.
        """
        config = {
            "storage_backend": "gcs",
            "gcs_uri": "s3://wrong-bucket/path/db.lancedb",  # Wrong prefix
            "table_name": "test_table"
        }

        with pytest.raises( ValueError ) as exc_info:
            manager = LanceDBSolutionManager( config, debug=False )

        assert "GCS URI must start with 'gs://'" in str( exc_info.value )
        assert "s3://wrong-bucket" in str( exc_info.value )

    def test_unknown_backend_raises_error(self):
        """
        Test that unknown storage_backend value raises ValueError.
        """
        config = {
            "storage_backend": "s3",  # Not supported
            "table_name": "test_table"
        }

        with pytest.raises( ValueError ) as exc_info:
            manager = LanceDBSolutionManager( config, debug=False )

        assert "Unknown storage_backend: 's3'" in str( exc_info.value )
        assert "Must be 'local' or 'gcs'" in str( exc_info.value )

    def test_default_backend_is_local(self):
        """
        Test that storage_backend defaults to 'local' if not specified.
        """
        config = {
            # storage_backend intentionally omitted
            "db_path": "/tmp/test.lancedb",
            "table_name": "test_table"
        }

        with patch( 'os.path.exists', return_value=True ):
            with patch( 'cosa.memory.lancedb_solution_manager.lancedb.connect' ):
                manager = LanceDBSolutionManager( config, debug=False )

                assert manager.storage_backend == "local"
                assert manager.db_path == "/tmp/test.lancedb"

    def test_error_messages_include_helpful_examples(self):
        """
        Test that error messages include config key examples and guidance.
        """
        # Test GCS missing URI
        config_gcs = {
            "storage_backend": "gcs",
            "table_name": "test_table"
        }

        with pytest.raises( ValueError ) as exc_info:
            manager = LanceDBSolutionManager( config_gcs, debug=False )

        error_msg = str( exc_info.value )
        assert "Example:" in error_msg
        assert "solution snapshots lancedb gcs uri" in error_msg

        # Test local missing path
        config_local = {
            "storage_backend": "local",
            "table_name": "test_table"
        }

        with pytest.raises( ValueError ) as exc_info:
            manager = LanceDBSolutionManager( config_local, debug=False )

        error_msg = str( exc_info.value )
        assert "Example:" in error_msg
        assert "solution snapshots lancedb path" in error_msg

    def test_gcs_uri_case_sensitivity(self):
        """
        Test that GCS URI validation is case-sensitive for gs:// prefix.
        """
        config = {
            "storage_backend": "gcs",
            "gcs_uri": "GS://test-bucket/path.lancedb",  # Uppercase
            "table_name": "test_table"
        }

        with pytest.raises( ValueError ) as exc_info:
            manager = LanceDBSolutionManager( config, debug=False )

        assert "GCS URI must start with 'gs://'" in str( exc_info.value )


def quick_smoke_test():
    """
    Quick smoke test for unit test suite - validates tests can be discovered and run.
    """
    import cosa.utils.util as cu

    cu.print_banner( "LanceDB GCS Manager Unit Tests - Smoke Test", prepend_nl=True )

    try:
        # Test 1: Import test module
        print( "Testing module import..." )
        import test_lancedb_gcs_manager
        print( "✓ Module imported successfully" )

        # Test 2: Discover test class
        print( "Testing test class discovery..." )
        assert hasattr( test_lancedb_gcs_manager, 'TestLanceDBManagerPathResolution' )
        test_class = test_lancedb_gcs_manager.TestLanceDBManagerPathResolution
        print( f"✓ Test class discovered: {test_class.__name__}" )

        # Test 3: Count test methods
        print( "Counting test methods..." )
        test_methods = [m for m in dir( test_class ) if m.startswith( 'test_' )]
        print( f"✓ Found {len( test_methods )} test methods" )

        print( "\n✓ Smoke test completed successfully" )
        print( f"\nRun full test suite with:" )
        print( f"  pytest {__file__} -v" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
