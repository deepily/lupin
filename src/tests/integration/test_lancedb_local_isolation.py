"""
Local backend isolation tests for LanceDB query/retrieval debugging.

This test suite replicates the FAILING GCS integration tests using a local
backend to determine if the 50% test failure rate is:
- GCS-specific (consistency delays, indexing lag)
- General code bug (normalization, canonical table, cache)

Tests replicated from test_lancedb_gcs_integration.py:
1. test_query_by_question_from_gcs → test_query_by_question_local
2. test_data_persistence_across_manager_instances → test_data_persistence_local
3. test_gcs_backend_handles_special_characters → test_special_characters_local

Expected Outcome:
- If tests PASS: Issue is GCS-specific (consistency delays, indexing)
- If tests FAIL: Issue is code bug affecting both backends (normalization)
"""

import os
import pytest
import time
import tempfile
import shutil
from typing import List

# Bootstrap path - LUPIN_ROOT must be set
import sys
import os as os_sys

lupin_root = os_sys.environ.get( 'LUPIN_ROOT' )
if lupin_root is None:
    raise RuntimeError(
        "LUPIN_ROOT environment variable not set.\n"
        "Set it before running tests:\n"
        "  export LUPIN_ROOT=/path/to/project\n"
        "  pytest src/tests/integration/test_lancedb_local_isolation.py"
    )

src_path = os_sys.path.join( lupin_root, 'src' )
if src_path not in sys.path:
    sys.path.insert( 0, src_path )

from cosa.memory.lancedb_solution_manager import LanceDBSolutionManager
from cosa.memory.solution_snapshot import SolutionSnapshot


class TestLanceDBLocalIsolation:
    """Local backend isolation tests to debug query/retrieval failures."""

    @pytest.fixture(scope="class")
    def temp_db_dir(self):
        """Create temporary directory for local database."""
        temp_dir = tempfile.mkdtemp( prefix="lancedb-test-" )
        db_path = os.path.join( temp_dir, "test.lancedb" )

        yield db_path

        # Cleanup
        shutil.rmtree( temp_dir, ignore_errors=True )

    @pytest.fixture(scope="class")
    def local_config(self, temp_db_dir):
        """Configuration for local-backed manager."""
        return {
            "storage_backend": "local",
            "db_path": temp_db_dir,
            "table_name": "solution_snapshots"
        }

    @pytest.fixture(scope="class")
    def local_manager(self, local_config):
        """
        Create LanceDB manager with LOCAL backend for isolation testing.
        Uses temporary directory to avoid conflicts.
        """
        manager = LanceDBSolutionManager( local_config, debug=True, verbose=False )
        manager.initialize()

        yield manager

        # Cleanup handled by temp_db_dir fixture

    def test_query_by_question_local(self, local_manager):
        """
        REPLICATES: test_query_by_question_from_gcs

        Test querying snapshots by question from LOCAL backend.
        This is the same test that FAILS with GCS (returns 0 results).

        Expected Result:
        - PASS: Issue is GCS-specific (consistency, indexing)
        - FAIL: Issue is code bug (normalization mismatch)
        """
        print( "\n=== TEST: Query by question (local backend) ===" )

        # Add a known snapshot
        snapshot = SolutionSnapshot(
            question="How do I sort a list?",
            answer="Use the sorted() function",
            code=["sorted_list = sorted(my_list)"],
            debug=False
        )

        print( f"Inserting snapshot: '{snapshot.question}'" )
        result = local_manager.add_snapshot( snapshot )
        print( f"Insert result: {result}" )

        # Small delay (same as GCS tests)
        time.sleep( 2 )

        # Query for the snapshot
        print( f"Querying for: 'How do I sort a list?'" )
        results = local_manager.get_snapshots_by_question( "How do I sort a list?" )
        print( f"Query returned {len( results )} results" )

        if len( results ) > 0:
            print( f"✓ Found results: {[snapshot.question for score, snapshot in results]}" )
        else:
            print( "✗ No results found (SAME FAILURE AS GCS)" )

        # Assertions
        assert len( results ) > 0, "Expected at least 1 result, got 0 (NORMALIZATION BUG)"
        assert any( "sort" in snapshot.question.lower() for score, snapshot in results ), "Expected 'sort' in question"

    def test_data_persistence_local(self, temp_db_dir, local_config):
        """
        REPLICATES: test_data_persistence_across_manager_instances

        Test that data persists locally across manager instances.
        This is the same test that FAILS with GCS.

        Expected Result:
        - PASS: Issue is GCS-specific
        - FAIL: Issue is cache/reload bug
        """
        print( "\n=== TEST: Data persistence across manager instances (local) ===" )

        # Create first manager instance and insert data
        print( "Creating first manager instance..." )
        manager1 = LanceDBSolutionManager( local_config, debug=True )
        manager1.initialize()

        snapshot = SolutionSnapshot(
            question="Test persistence question",
            answer="Test persistence answer",
            debug=False
        )

        print( f"Inserting snapshot: '{snapshot.question}'" )
        manager1.add_snapshot( snapshot )

        print( "Deleting first manager..." )
        del manager1

        time.sleep( 2 )

        # Create second manager instance
        print( "Creating second manager instance..." )
        manager2 = LanceDBSolutionManager( local_config, debug=True )
        manager2.initialize()

        # Search for the persisted data
        print( f"Querying for: 'Test persistence question'" )
        results = manager2.get_snapshots_by_question( "Test persistence question" )
        print( f"Query returned {len( results )} results" )

        if len( results ) > 0:
            print( f"✓ Found results: {[snapshot.question for score, snapshot in results]}" )
        else:
            print( "✗ No results found (CACHE/RELOAD BUG)" )

        # Assertions
        assert len( results ) > 0, "Expected at least 1 result after manager reload"
        assert any( "test persistence" in snapshot.question.lower() for score, snapshot in results ), "Expected 'test persistence' in question"

    def test_special_characters_local(self, local_manager):
        """
        REPLICATES: test_gcs_backend_handles_special_characters

        Test that local backend handles questions with special characters.
        This is the CRITICAL test - GCS test FAILS due to normalization mismatch.

        From logs: Insert normalizes to "how do i use pythons fstrings" (no apostrophe)
                  Query normalizes to "how do i use python 's f string" (apostrophe → space + 's)

        Expected Result:
        - PASS: Issue is GCS-specific (unlikely for normalization bug)
        - FAIL: Issue is normalization inconsistency (MOST LIKELY)
        """
        print( "\n=== TEST: Special characters handling (local backend) ===" )

        snapshot = SolutionSnapshot(
            question="How do I use Python's f-strings?",
            answer="Use f-string syntax: f'{variable}'",
            debug=False
        )

        print( f"Inserting snapshot: '{snapshot.question}'" )
        result = local_manager.add_snapshot( snapshot )
        print( f"Insert result: {result}" )

        time.sleep( 2 )

        print( f"Querying for: 'How do I use Python's f-strings?'" )
        results = local_manager.get_snapshots_by_question( "How do I use Python's f-strings?" )
        print( f"Query returned {len( results )} results" )

        if len( results ) > 0:
            print( f"✓ Found results: {[snapshot.question for score, snapshot in results]}" )
        else:
            print( "✗ No results found (NORMALIZATION MISMATCH)" )
            print( "This confirms the bug is NOT GCS-specific - it's a code bug!" )

        # Assertions
        assert len( results ) > 0, "Expected at least 1 result with special characters"

    def test_multiple_snapshots_local(self, local_manager):
        """
        CONTROL TEST: This test PASSES with GCS backend.

        Verify that tests WITHOUT special characters work correctly.
        This should PASS regardless of backend.
        """
        print( "\n=== CONTROL TEST: Multiple snapshots (local backend) ===" )

        # Add multiple related snapshots (no special characters)
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
            print( f"Inserting: '{q}'" )
            local_manager.add_snapshot( snapshot )

        time.sleep( 2 )

        # Verify we can retrieve them
        for q in questions:
            print( f"Querying for: '{q}'" )
            results = local_manager.get_snapshots_by_question( q )
            print( f"  → {len( results )} results" )
            assert len( results ) > 0, f"Failed to retrieve: {q}"

        print( "✓ Control test passed - simple questions work fine" )


def quick_smoke_test():
    """
    Quick smoke test for local isolation test suite.
    """
    import cosa.utils.util as cu

    cu.print_banner( "LanceDB Local Isolation Tests - Smoke Test", prepend_nl=True )

    try:
        # Test 1: Import test module
        print( "Testing module import..." )
        import test_lancedb_local_isolation
        print( "✓ Module imported successfully" )

        # Test 2: Count test methods
        print( "Counting test methods..." )
        test_class = test_lancedb_local_isolation.TestLanceDBLocalIsolation
        test_methods = [m for m in dir( test_class ) if m.startswith( 'test_' )]
        print( f"✓ Found {len( test_methods )} test methods" )
        print( f"  Tests: {', '.join( test_methods )}" )

        # Test 3: Verify LUPIN_ROOT environment variable
        print( "Checking LUPIN_ROOT environment variable..." )
        lupin_root = os.environ.get( 'LUPIN_ROOT' )
        if lupin_root:
            print( f"✓ LUPIN_ROOT set to: {lupin_root}" )
        else:
            print( "✗ LUPIN_ROOT not set - tests will fail" )

        print( "\n✓ Smoke test completed" )
        print( f"\nRun isolation tests with:" )
        print( f"  pytest {__file__} -v -s" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


def run_standalone_tests():
    """
    Run tests as standalone script (no pytest, no server dependency).
    This bypasses the conftest.py server validation.
    """
    import cosa.utils.util as cu
    import tempfile
    import shutil

    cu.print_banner( "LanceDB Local Backend Isolation Tests", prepend_nl=True )

    # Create temporary directory
    temp_dir = tempfile.mkdtemp( prefix="lancedb-test-" )
    db_path = os.path.join( temp_dir, "test.lancedb" )

    local_config = {
        "storage_backend": "local",
        "db_path": db_path,
        "table_name": "solution_snapshots"
    }

    try:
        # Create manager
        print( "\nInitializing LanceDB manager with LOCAL backend..." )
        manager = LanceDBSolutionManager( local_config, debug=True, verbose=False )
        manager.initialize()
        print( f"✓ Manager initialized at: {db_path}" )

        # Run Test 1: Query by question
        print( "\n" + "="*60 )
        print( "TEST 1: Query by question (local backend)" )
        print( "="*60 )

        snapshot1 = SolutionSnapshot(
            question="How do I sort a list?",
            answer="Use the sorted() function",
            code=["sorted_list = sorted(my_list)"],
            debug=False
        )

        print( f"Inserting snapshot: '{snapshot1.question}'" )
        result1 = manager.add_snapshot( snapshot1 )
        print( f"Insert result: {result1}" )

        time.sleep( 2 )

        print( f"Querying for: 'How do I sort a list?'" )
        results1 = manager.get_snapshots_by_question( "How do I sort a list?" )
        print( f"Query returned {len( results1 )} results" )

        if len( results1 ) > 0:
            print( f"✓ TEST 1 PASSED - Found results: {[(score, snapshot.question) for score, snapshot in results1]}" )
        else:
            print( "✗ TEST 1 FAILED - No results found (SAME AS GCS)" )

        # Run Test 2: Special characters
        print( "\n" + "="*60 )
        print( "TEST 2: Special characters handling (CRITICAL)" )
        print( "="*60 )

        snapshot2 = SolutionSnapshot(
            question="How do I use Python's f-strings?",
            answer="Use f-string syntax: f'{variable}'",
            debug=False
        )

        print( f"Inserting snapshot: '{snapshot2.question}'" )
        result2 = manager.add_snapshot( snapshot2 )
        print( f"Insert result: {result2}" )

        time.sleep( 2 )

        print( f"Querying for: 'How do I use Python's f-strings?'" )
        results2 = manager.get_snapshots_by_question( "How do I use Python's f-strings?" )
        print( f"Query returned {len( results2 )} results" )

        if len( results2 ) > 0:
            print( f"✓ TEST 2 PASSED - Found results: {[(score, snapshot.question) for score, snapshot in results2]}" )
        else:
            print( "✗ TEST 2 FAILED - No results found (NORMALIZATION MISMATCH)" )
            print( "  This confirms the bug is NOT GCS-specific - it's a CODE BUG!" )

        # Run Test 3: Multiple snapshots (control)
        print( "\n" + "="*60 )
        print( "TEST 3: Multiple snapshots (CONTROL - should pass)" )
        print( "="*60 )

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
            print( f"Inserting: '{q}'" )
            manager.add_snapshot( snapshot )

        time.sleep( 2 )

        test3_passed = True
        for q in questions:
            print( f"Querying for: '{q}'" )
            results = manager.get_snapshots_by_question( q )
            print( f"  → {len( results )} results" )
            if len( results ) == 0:
                test3_passed = False

        if test3_passed:
            print( "✓ TEST 3 PASSED - Control test successful" )
        else:
            print( "✗ TEST 3 FAILED - Even simple questions failing" )

        # Summary
        print( "\n" + "="*60 )
        print( "TEST SUMMARY" )
        print( "="*60 )

        test1_status = "PASS" if len( results1 ) > 0 else "FAIL"
        test2_status = "PASS" if len( results2 ) > 0 else "FAIL"
        test3_status = "PASS" if test3_passed else "FAIL"

        print( f"Test 1 (Query by question):     {test1_status}" )
        print( f"Test 2 (Special characters):    {test2_status}" )
        print( f"Test 3 (Multiple snapshots):    {test3_status}" )

        # Conclusion
        print( "\n" + "="*60 )
        print( "CONCLUSION" )
        print( "="*60 )

        if test1_status == "FAIL" or test2_status == "FAIL":
            print( "✗ Local backend tests FAILED (same as GCS)" )
            print( "  → This is a CODE BUG, NOT a GCS-specific issue" )
            print( "  → Root cause: Normalization inconsistency between insert and query" )
            print( "\nNext step: Add debug logging to trace normalization paths" )
        else:
            print( "✓ Local backend tests PASSED" )
            print( "  → GCS failures are backend-specific (consistency, indexing)" )
            print( "\nNext step: Increase GCS delays and add retry logic" )

    except Exception as e:
        print( f"\n✗ Test execution failed: {e}" )
        import traceback
        traceback.print_exc()

    finally:
        # Cleanup
        shutil.rmtree( temp_dir, ignore_errors=True )
        print( f"\n✓ Cleaned up temporary directory: {temp_dir}" )


if __name__ == "__main__":
    import sys
    if len( sys.argv ) > 1 and sys.argv[1] == "--smoke":
        quick_smoke_test()
    else:
        run_standalone_tests()
