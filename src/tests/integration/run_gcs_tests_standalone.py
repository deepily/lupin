"""
Standalone GCS integration test runner (no FastAPI server required).

This bypasses the conftest.py server validation and runs GCS tests directly.
"""

import os
import sys
import time

# Bootstrap path - LUPIN_ROOT must be set
lupin_root = os.environ.get( 'LUPIN_ROOT' )
if lupin_root is None:
    raise RuntimeError(
        "LUPIN_ROOT environment variable not set.\n"
        "Set it before running tests:\n"
        "  export LUPIN_ROOT=/path/to/project\n"
        "  python src/tests/integration/run_gcs_tests_standalone.py"
    )

src_path = os.path.join( lupin_root, 'src' )
if src_path not in sys.path:
    sys.path.insert( 0, src_path )

import cosa.utils.util as cu
from cosa.memory.lancedb_solution_manager import LanceDBSolutionManager
from cosa.memory.solution_snapshot import SolutionSnapshot

def run_gcs_tests():
    """Run GCS integration tests standalone."""

    cu.print_banner( "LanceDB GCS Integration Tests (Standalone)", prepend_nl=True )

    # Create timestamped GCS URI
    gcs_test_bucket_uri = f"gs://lupin-lancedb-test/integration-test-{int( time.time() )}.lancedb"

    gcs_config = {
        "storage backend": "gcs",
        "gcs_uri": gcs_test_bucket_uri,
        "table_name": "solution_snapshots"
    }

    print( f"\nGCS Test Configuration:" )
    print( f"  Bucket URI: {gcs_test_bucket_uri}" )
    print( f"  Table: solution_snapshots\n" )

    # Initialize manager
    print( "Initializing GCS manager..." )
    manager = LanceDBSolutionManager( gcs_config, debug=True, verbose=False )
    manager.initialize()
    print( f"✓ Manager initialized\n" )

    # Test results
    test_results = []

    # Test 1: Add and query snapshot
    print( "="*60 )
    print( "TEST 1: Add and query snapshot" )
    print( "="*60 )

    try:
        snapshot1 = SolutionSnapshot(
            question="How do I sort a list?",
            answer="Use the sorted() function",
            code=["sorted_list = sorted(my_list)"],
            debug=False
        )

        print( f"Adding snapshot: '{snapshot1.question}'" )
        result = manager.save_snapshot( snapshot1 )
        print( f"Add result: {result}" )

        time.sleep( 2 )  # GCS consistency delay

        print( f"Querying for: 'How do I sort a list?'" )
        results = manager.get_snapshots_by_question( "How do I sort a list?" )
        print( f"Query returned {len( results )} results" )

        if len( results ) > 0:
            print( f"✓ TEST 1 PASSED" )
            test_results.append( ("Test 1", "PASS") )
        else:
            print( f"✗ TEST 1 FAILED" )
            test_results.append( ("Test 1", "FAIL") )
    except Exception as e:
        print( f"✗ TEST 1 FAILED: {e}" )
        test_results.append( ("Test 1", "FAIL") )

    # Test 2: Special characters
    print( "\n" + "="*60 )
    print( "TEST 2: Special characters" )
    print( "="*60 )

    try:
        snapshot2 = SolutionSnapshot(
            question="How do I use Python's f-strings?",
            answer="Use f-string syntax: f'{variable}'",
            debug=False
        )

        print( f"Adding snapshot: '{snapshot2.question}'" )
        result = manager.save_snapshot( snapshot2 )
        print( f"Add result: {result}" )

        time.sleep( 2 )

        print( f"Querying for: 'How do I use Python's f-strings?'" )
        results = manager.get_snapshots_by_question( "How do I use Python's f-strings?" )
        print( f"Query returned {len( results )} results" )

        if len( results ) > 0:
            print( f"✓ TEST 2 PASSED" )
            test_results.append( ("Test 2", "PASS") )
        else:
            print( f"✗ TEST 2 FAILED" )
            test_results.append( ("Test 2", "FAIL") )
    except Exception as e:
        print( f"✗ TEST 2 FAILED: {e}" )
        test_results.append( ("Test 2", "FAIL") )

    # Test 3: Multiple snapshots
    print( "\n" + "="*60 )
    print( "TEST 3: Multiple snapshots" )
    print( "="*60 )

    try:
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
            print( f"Adding: '{q}'" )
            manager.save_snapshot( snapshot )

        time.sleep( 2 )

        all_passed = True
        for q in questions:
            print( f"Querying for: '{q}'" )
            results = manager.get_snapshots_by_question( q )
            print( f"  → {len( results )} results" )
            if len( results ) == 0:
                all_passed = False

        if all_passed:
            print( f"✓ TEST 3 PASSED" )
            test_results.append( ("Test 3", "PASS") )
        else:
            print( f"✗ TEST 3 FAILED" )
            test_results.append( ("Test 3", "FAIL") )
    except Exception as e:
        print( f"✗ TEST 3 FAILED: {e}" )
        test_results.append( ("Test 3", "FAIL") )

    # Summary
    print( "\n" + "="*60 )
    print( "TEST SUMMARY" )
    print( "="*60 )

    passed = sum( 1 for _, status in test_results if status == "PASS" )
    failed = sum( 1 for _, status in test_results if status == "FAIL" )

    for test_name, status in test_results:
        print( f"{test_name}: {status}" )

    print( f"\nTotal: {passed} passed, {failed} failed" )

    if failed == 0:
        print( "\n✓ All GCS integration tests PASSED!" )
        return 0
    else:
        print( f"\n✗ {failed} test(s) failed" )
        return 1

if __name__ == "__main__":
    exit_code = run_gcs_tests()
    sys.exit( exit_code )
