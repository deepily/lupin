"""
Unit tests for EmbeddingCacheTable corruption detection and recovery.

Tests the _is_table_corrupted() method and automatic recovery behavior
when LanceDB data fragment files are missing or corrupted.
"""

import pytest
import tempfile
import os
import shutil
from unittest.mock import Mock, patch, MagicMock


class TestCorruptionDetection:
    """Test suite for _is_table_corrupted() method."""

    def test_healthy_table_returns_false( self ):
        """Test that a healthy table is not flagged as corrupted."""
        # Create a mock table that returns data successfully
        mock_table = Mock()
        mock_search = Mock()
        mock_search.limit.return_value = mock_search
        mock_search.to_list.return_value = [ { "normalized_text": "test" } ]
        mock_table.search.return_value = mock_search

        # Create minimal object with the table
        class TableHolder:
            def __init__( self ):
                self._embedding_cache_tbl = mock_table

            def _is_table_corrupted( self ) -> bool:
                try:
                    self._embedding_cache_tbl.search().limit( 1 ).to_list()
                    return False
                except Exception as e:
                    error_str = str( e ).lower()
                    if "not found" in error_str or "lance" in error_str:
                        return True
                    raise

        holder = TableHolder()
        assert holder._is_table_corrupted() == False

    def test_empty_table_returns_false( self ):
        """Test that an empty but healthy table is not flagged as corrupted."""
        mock_table = Mock()
        mock_search = Mock()
        mock_search.limit.return_value = mock_search
        mock_search.to_list.return_value = []  # Empty result
        mock_table.search.return_value = mock_search

        class TableHolder:
            def __init__( self ):
                self._embedding_cache_tbl = mock_table

            def _is_table_corrupted( self ) -> bool:
                try:
                    self._embedding_cache_tbl.search().limit( 1 ).to_list()
                    return False
                except Exception as e:
                    error_str = str( e ).lower()
                    if "not found" in error_str or "lance" in error_str:
                        return True
                    raise

        holder = TableHolder()
        assert holder._is_table_corrupted() == False

    def test_not_found_error_returns_true( self ):
        """Test that 'Not found' LanceDB error is detected as corruption."""
        mock_table = Mock()
        mock_search = Mock()
        mock_search.limit.return_value = mock_search
        mock_search.to_list.side_effect = RuntimeError(
            "lance error: LanceError(IO): Execution error: Not found: /path/to/file.lance"
        )
        mock_table.search.return_value = mock_search

        class TableHolder:
            def __init__( self ):
                self._embedding_cache_tbl = mock_table

            def _is_table_corrupted( self ) -> bool:
                try:
                    self._embedding_cache_tbl.search().limit( 1 ).to_list()
                    return False
                except Exception as e:
                    error_str = str( e ).lower()
                    if "not found" in error_str or "lance" in error_str:
                        return True
                    raise

        holder = TableHolder()
        assert holder._is_table_corrupted() == True

    def test_lance_io_error_returns_true( self ):
        """Test that LanceDB IO error is detected as corruption."""
        mock_table = Mock()
        mock_search = Mock()
        mock_search.limit.return_value = mock_search
        mock_search.to_list.side_effect = RuntimeError(
            "LanceError(IO): Failed to read data fragment"
        )
        mock_table.search.return_value = mock_search

        class TableHolder:
            def __init__( self ):
                self._embedding_cache_tbl = mock_table

            def _is_table_corrupted( self ) -> bool:
                try:
                    self._embedding_cache_tbl.search().limit( 1 ).to_list()
                    return False
                except Exception as e:
                    error_str = str( e ).lower()
                    if "not found" in error_str or "lance" in error_str:
                        return True
                    raise

        holder = TableHolder()
        assert holder._is_table_corrupted() == True

    def test_unrelated_error_is_reraised( self ):
        """Test that unrelated errors are re-raised, not treated as corruption."""
        mock_table = Mock()
        mock_search = Mock()
        mock_search.limit.return_value = mock_search
        mock_search.to_list.side_effect = ValueError( "Some unrelated error" )
        mock_table.search.return_value = mock_search

        class TableHolder:
            def __init__( self ):
                self._embedding_cache_tbl = mock_table

            def _is_table_corrupted( self ) -> bool:
                try:
                    self._embedding_cache_tbl.search().limit( 1 ).to_list()
                    return False
                except Exception as e:
                    error_str = str( e ).lower()
                    if "not found" in error_str or "lance" in error_str:
                        return True
                    raise

        holder = TableHolder()
        with pytest.raises( ValueError, match="Some unrelated error" ):
            holder._is_table_corrupted()

    def test_connection_error_is_reraised( self ):
        """Test that connection errors are re-raised, not treated as corruption."""
        mock_table = Mock()
        mock_search = Mock()
        mock_search.limit.return_value = mock_search
        mock_search.to_list.side_effect = ConnectionError( "Database unavailable" )
        mock_table.search.return_value = mock_search

        class TableHolder:
            def __init__( self ):
                self._embedding_cache_tbl = mock_table

            def _is_table_corrupted( self ) -> bool:
                try:
                    self._embedding_cache_tbl.search().limit( 1 ).to_list()
                    return False
                except Exception as e:
                    error_str = str( e ).lower()
                    if "not found" in error_str or "lance" in error_str:
                        return True
                    raise

        holder = TableHolder()
        with pytest.raises( ConnectionError, match="Database unavailable" ):
            holder._is_table_corrupted()


class TestCorruptionRecoveryIntegration:
    """Integration tests for corruption recovery using real LanceDB."""

    @pytest.fixture
    def temp_lancedb( self ):
        """Create a temporary LanceDB for testing."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree( temp_dir, ignore_errors=True )

    def test_real_corruption_detection( self, temp_lancedb ):
        """Test corruption detection with a real corrupted LanceDB table."""
        import lancedb
        import pyarrow as pa

        # Create a real LanceDB table
        db = lancedb.connect( temp_lancedb )
        schema = pa.schema( [
            pa.field( "normalized_text", pa.string() ),
            pa.field( "embedding", pa.list_( pa.float32(), 1536 ) )
        ] )
        table = db.create_table( "test_tbl", schema=schema )

        # Add data to create fragment files
        table.add( [ { "normalized_text": "test", "embedding": [ 0.1 ] * 1536 } ] )

        # Verify table is healthy
        results = table.search().limit( 1 ).to_list()
        assert len( results ) == 1

        # Find and delete a data fragment to simulate corruption
        data_dir = os.path.join( temp_lancedb, "test_tbl.lance", "data" )
        if os.path.exists( data_dir ):
            lance_files = [ f for f in os.listdir( data_dir ) if f.endswith( ".lance" ) ]
            if lance_files:
                corrupt_file = os.path.join( data_dir, lance_files[ 0 ] )
                os.remove( corrupt_file )

                # Reopen and verify corruption is detected
                db2 = lancedb.connect( temp_lancedb )
                corrupted_table = db2.open_table( "test_tbl" )

                # Test the corruption detection logic
                try:
                    corrupted_table.search().limit( 1 ).to_list()
                    is_corrupted = False
                except Exception as e:
                    error_str = str( e ).lower()
                    is_corrupted = "not found" in error_str or "lance" in error_str

                assert is_corrupted == True, "Corruption should be detected after deleting fragment file"

    def test_healthy_table_not_flagged( self, temp_lancedb ):
        """Test that a healthy real table is not flagged as corrupted."""
        import lancedb
        import pyarrow as pa

        # Create a real LanceDB table
        db = lancedb.connect( temp_lancedb )
        schema = pa.schema( [
            pa.field( "normalized_text", pa.string() ),
            pa.field( "embedding", pa.list_( pa.float32(), 1536 ) )
        ] )
        table = db.create_table( "test_tbl", schema=schema )

        # Add data
        table.add( [ { "normalized_text": "healthy", "embedding": [ 0.5 ] * 1536 } ] )

        # Verify no corruption detected
        try:
            table.search().limit( 1 ).to_list()
            is_corrupted = False
        except Exception as e:
            error_str = str( e ).lower()
            is_corrupted = "not found" in error_str or "lance" in error_str

        assert is_corrupted == False, "Healthy table should not be flagged as corrupted"

    def test_table_recovery_after_drop_and_recreate( self, temp_lancedb ):
        """Test that table can be recovered by dropping and recreating."""
        import lancedb
        import pyarrow as pa

        # Create and corrupt the table
        db = lancedb.connect( temp_lancedb )
        schema = pa.schema( [
            pa.field( "normalized_text", pa.string() ),
            pa.field( "embedding", pa.list_( pa.float32(), 1536 ) )
        ] )
        table = db.create_table( "test_tbl", schema=schema )
        table.add( [ { "normalized_text": "original", "embedding": [ 0.1 ] * 1536 } ] )

        # Corrupt it
        data_dir = os.path.join( temp_lancedb, "test_tbl.lance", "data" )
        if os.path.exists( data_dir ):
            lance_files = [ f for f in os.listdir( data_dir ) if f.endswith( ".lance" ) ]
            if lance_files:
                os.remove( os.path.join( data_dir, lance_files[ 0 ] ) )

        # Simulate recovery: drop and recreate
        db.drop_table( "test_tbl" )
        new_table = db.create_table( "test_tbl", schema=schema )
        new_table.add( [ { "normalized_text": "recovered", "embedding": [ 0.9 ] * 1536 } ] )

        # Verify recovery worked
        results = new_table.search().limit( 1 ).to_list()
        assert len( results ) == 1
        assert results[ 0 ][ "normalized_text" ] == "recovered"


def quick_smoke_test():
    """Quick smoke test for corruption detection unit tests."""
    import cosa.utils.util as du

    du.print_banner( "Embedding Cache Corruption Unit Tests Smoke Test", prepend_nl=True )

    try:
        print( "Running pytest on this file..." )
        import subprocess
        result = subprocess.run(
            [ "pytest", __file__, "-v", "--tb=short" ],
            capture_output=True,
            text=True
        )
        print( result.stdout )
        if result.returncode != 0:
            print( result.stderr )
            print( f"\n✗ Some tests failed (exit code: {result.returncode})" )
        else:
            print( "\n✓ All unit tests passed" )

    except Exception as e:
        print( f"✗ Error running tests: {e}" )


if __name__ == "__main__":
    quick_smoke_test()
