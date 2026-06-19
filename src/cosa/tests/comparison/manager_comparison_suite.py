"""
Common test suite for empirical comparison between solution snapshot manager implementations.

This module provides a standardized test framework that can be used to validate
and compare different solution snapshot manager implementations (file-based, LanceDB, etc.)
ensuring identical functionality and enabling performance comparison.
"""

import time
import json
from typing import Dict, Any, List, Tuple
from dataclasses import dataclass

import cosa.utils.util as du
from cosa.memory.snapshot_manager_interface import SolutionSnapshotManagerInterface
from cosa.memory.solution_snapshot import SolutionSnapshot


@dataclass
class TestResult:
    """Results from a single test."""
    test_name: str
    success: bool
    duration_ms: float
    result_data: Any = None
    error_message: str = ""
    performance_metrics: Dict[str, Any] = None


class SolutionSnapshotManagerTestSuite:
    """
    Common test suite that works with any SolutionSnapshotManagerInterface implementation.
    
    Enables empirical comparison between implementations by running identical tests
    and collecting performance metrics for analysis.
    """
    
    def __init__( self, manager: SolutionSnapshotManagerInterface, test_name: str = "" ):
        """
        Initialize test suite for a specific manager implementation.
        
        Args:
            manager: Implementation to test
            test_name: Descriptive name for this test run
        """
        self.manager = manager
        self.test_name = test_name or manager.get_implementation_name()
        self.test_results = []
        
    def run_full_suite( self ) -> Dict[str, Any]:
        """
        Run complete test suite and return comprehensive results.
        
        Returns:
            Dictionary with all test results and summary statistics
        """
        du.print_banner( f"Running Test Suite: {self.test_name}", prepend_nl=True )
        
        suite_start = time.time()
        
        # Run all test categories
        self._test_initialization()
        self._test_health_checks()
        self._test_basic_operations()
        self._test_search_functionality()
        self._test_edge_cases()
        self._test_performance_characteristics()
        
        suite_duration = ( time.time() - suite_start ) * 1000
        
        # Generate summary
        summary = self._generate_summary( suite_duration )
        
        print( f"\n✅ Test Suite Complete: {self.test_name}" )
        print( f"   • Tests run: {len( self.test_results )}" )
        print( f"   • Passed: {summary['tests_passed']}" )
        print( f"   • Failed: {summary['tests_failed']}" )
        print( f"   • Success rate: {summary['success_rate']:.1f}%" )
        print( f"   • Total time: {suite_duration:.1f}ms" )
        
        return {
            "test_name": self.test_name,
            "summary": summary,
            "individual_results": [result.__dict__ for result in self.test_results],
            "manager_type": self.manager.get_implementation_name()
        }
    
    def _run_test( self, test_name: str, test_func ) -> TestResult:
        """
        Run a single test with timing and error handling.
        
        Args:
            test_name: Name of the test
            test_func: Function to execute for the test
            
        Returns:
            TestResult with outcome and timing
        """
        print( f"  🧪 {test_name}...", end=" " )
        
        start_time = time.time()
        
        try:
            result_data = test_func()
            duration = ( time.time() - start_time ) * 1000
            
            result = TestResult(
                test_name=test_name,
                success=True,
                duration_ms=duration,
                result_data=result_data
            )
            
            print( f"✓ ({duration:.1f}ms)" )
            
        except Exception as e:
            duration = ( time.time() - start_time ) * 1000
            
            result = TestResult(
                test_name=test_name,
                success=False,
                duration_ms=duration,
                error_message=str( e )
            )
            
            print( f"✗ ({duration:.1f}ms) - {e}" )
        
        self.test_results.append( result )
        return result
    
    def _test_initialization( self ) -> None:
        """Test manager initialization and basic setup."""
        print( f"\n🚀 Testing Initialization..." )
        
        def test_health_before_init():
            health = self.manager.health_check()
            assert health["backend_type"] is not None
            assert not health["initialized"]
            return health
        
        def test_initialization():
            result = self.manager.initialize()
            assert self.manager.is_initialized()
            return result
        
        def test_health_after_init():
            health = self.manager.health_check()
            assert health["initialized"]
            assert health["status"] in ["healthy", "degraded"]
            return health
        
        self._run_test( "Health check (before init)", test_health_before_init )
        self._run_test( "Manager initialization", test_initialization )
        self._run_test( "Health check (after init)", test_health_after_init )
    
    def _test_health_checks( self ) -> None:
        """Test health monitoring and diagnostics."""
        print( f"\n🏥 Testing Health Checks..." )
        
        def test_get_stats():
            stats = self.manager.get_stats()
            required_keys = {"total_snapshots", "backend_type", "last_updated"}
            assert all( key in stats for key in required_keys )
            return stats
        
        def test_health_diagnostics():
            health = self.manager.health_check()
            required_keys = {"status", "initialized", "backend_type"}
            assert all( key in health for key in required_keys )
            assert health["status"] in ["healthy", "degraded", "unhealthy"]
            return health
        
        self._run_test( "Statistics retrieval", test_get_stats )
        self._run_test( "Health diagnostics", test_health_diagnostics )
    
    def _test_basic_operations( self ) -> None:
        """Test basic CRUD operations."""
        print( f"\n📝 Testing Basic Operations..." )
        
        def test_gists_retrieval():
            gists = self.manager.get_gists()
            assert isinstance( gists, list )
            return len( gists )
        
        def test_add_snapshot():
            # Create a test snapshot
            test_snapshot = SolutionSnapshot(
                question="test question for CRUD operations",
                solution_summary="test solution",
                code="print('test')",
                programming_language="python"
            )
            
            # Set some embeddings
            test_snapshot.question_embedding = [0.1] * 1536
            test_snapshot.solution_embedding = [0.2] * 1536
            
            success = self.manager.add_snapshot( test_snapshot )
            assert success, "Failed to add test snapshot"
            return test_snapshot.question
        
        def test_search_added_snapshot():
            results = self.manager.get_snapshots_by_question( 
                "test question for CRUD operations",
                threshold_question=90.0
            )
            assert len( results ) > 0, "Could not find added snapshot"
            return len( results )
        
        def test_delete_snapshot():
            success = self.manager.delete_snapshot( "test question for CRUD operations" )
            assert success, "Failed to delete test snapshot"
            return success
        
        self._run_test( "Gists retrieval", test_gists_retrieval )
        self._run_test( "Add snapshot", test_add_snapshot )
        self._run_test( "Search added snapshot", test_search_added_snapshot )
        self._run_test( "Delete snapshot", test_delete_snapshot )
    
    def _test_search_functionality( self ) -> None:
        """Test search and similarity functions."""
        print( f"\n🔍 Testing Search Functionality..." )
        
        def test_question_search_high_threshold():
            results = self.manager.get_snapshots_by_question( 
                "nonexistent question xyz123",
                threshold_question=95.0,
                limit=5
            )
            assert isinstance( results, list )
            return {"results": len( results )}
        
        def test_question_search_low_threshold():
            results = self.manager.get_snapshots_by_question(
                "what",  # Common word that might match something
                threshold_question=50.0,
                limit=10
            )
            assert isinstance( results, list )
            return {"results": len( results )}
        
        def test_search_with_limits():
            # Test different limit values
            results_5 = self.manager.get_snapshots_by_question( "test", limit=5 )
            results_10 = self.manager.get_snapshots_by_question( "test", limit=10 )
            
            assert len( results_5 ) <= 5
            assert len( results_10 ) <= 10
            
            return {"limit_5": len( results_5 ), "limit_10": len( results_10 )}
        
        self._run_test( "Question search (high threshold)", test_question_search_high_threshold )
        self._run_test( "Question search (low threshold)", test_question_search_low_threshold )
        self._run_test( "Search with limits", test_search_with_limits )
    
    def _test_edge_cases( self ) -> None:
        """Test edge cases and error handling."""
        print( f"\n🔬 Testing Edge Cases..." )
        
        def test_empty_question_search():
            try:
                self.manager.get_snapshots_by_question( "" )
                return "No error raised for empty question"
            except ValueError:
                return "Correctly rejected empty question"
        
        def test_invalid_threshold():
            try:
                self.manager.get_snapshots_by_question( "test", threshold_question=150.0 )
                return "No error raised for invalid threshold"
            except ValueError:
                return "Correctly rejected invalid threshold"
        
        def test_delete_nonexistent():
            success = self.manager.delete_snapshot( "nonexistent question xyz789" )
            assert not success
            return "Correctly returned False for nonexistent snapshot"
        
        self._run_test( "Empty question search", test_empty_question_search )
        self._run_test( "Invalid threshold", test_invalid_threshold )
        self._run_test( "Delete nonexistent", test_delete_nonexistent )
    
    def _test_performance_characteristics( self ) -> None:
        """Test performance under various conditions."""
        print( f"\n⚡ Testing Performance..." )
        
        def test_repeated_searches():
            query = "performance test query"
            times = []
            
            for i in range( 5 ):
                start = time.time()
                results = self.manager.get_snapshots_by_question( query, limit=5 )
                duration = ( time.time() - start ) * 1000
                times.append( duration )
            
            avg_time = sum( times ) / len( times )
            consistency = max( times ) - min( times )  # Variation in timing
            
            return {
                "avg_search_time_ms": avg_time,
                "timing_consistency_ms": consistency,
                "all_times": times
            }
        
        def test_large_limit_search():
            start = time.time()
            results = self.manager.get_snapshots_by_question( 
                "test", 
                threshold_question=1.0,  # Very low threshold to potentially get many results
                limit=100  # Large limit
            )
            duration = ( time.time() - start ) * 1000
            
            return {
                "results_count": len( results ),
                "search_time_ms": duration,
                "time_per_result_ms": duration / max( len( results ), 1 )
            }
        
        self._run_test( "Repeated searches", test_repeated_searches )
        self._run_test( "Large limit search", test_large_limit_search )
    
    def _generate_summary( self, total_duration_ms: float ) -> Dict[str, Any]:
        """Generate summary statistics from test results."""
        tests_passed = sum( 1 for result in self.test_results if result.success )
        tests_failed = len( self.test_results ) - tests_passed
        success_rate = ( tests_passed / len( self.test_results ) ) * 100 if self.test_results else 0
        
        avg_test_time = sum( result.duration_ms for result in self.test_results ) / len( self.test_results ) if self.test_results else 0
        
        # Extract performance data
        search_times = []
        for result in self.test_results:
            if result.success and result.result_data and isinstance( result.result_data, dict ):
                if "time_ms" in result.result_data:
                    search_times.append( result.result_data["time_ms"] )
                elif "avg_search_time_ms" in result.result_data:
                    search_times.append( result.result_data["avg_search_time_ms"] )
        
        performance_summary = {}
        if search_times:
            performance_summary = {
                "avg_search_time_ms": sum( search_times ) / len( search_times ),
                "min_search_time_ms": min( search_times ),
                "max_search_time_ms": max( search_times ),
                "search_tests_count": len( search_times )
            }
        
        return {
            "tests_total": len( self.test_results ),
            "tests_passed": tests_passed,
            "tests_failed": tests_failed,
            "success_rate": success_rate,
            "total_duration_ms": total_duration_ms,
            "avg_test_duration_ms": avg_test_time,
            "performance_summary": performance_summary,
            "failed_tests": [result.test_name for result in self.test_results if not result.success]
        }


class ManagerComparisonSuite:
    """Compare multiple manager implementations empirically."""
    
    def __init__( self, managers: Dict[str, SolutionSnapshotManagerInterface] ):
        """
        Initialize comparison suite with multiple managers.
        
        Args:
            managers: Dictionary mapping names to manager implementations
        """
        self.managers = managers
        self.comparison_results = {}
    
    def run_comparative_analysis( self ) -> Dict[str, Any]:
        """
        Run tests on all managers and generate comparison report.
        
        Returns:
            Complete comparison results with side-by-side analysis
        """
        du.print_banner( "Manager Comparison Suite", prepend_nl=True )
        
        print( f"Comparing {len( self.managers )} implementations:" )
        for name, manager in self.managers.items():
            print( f"  • {name}: {manager.get_implementation_name()}" )
        
        # Run tests on each manager
        all_results = {}
        
        for name, manager in self.managers.items():
            print( f"\n" + "="*80 )
            print( f"Testing: {name}" )
            print( "="*80 )
            
            test_suite = SolutionSnapshotManagerTestSuite( manager, name )
            results = test_suite.run_full_suite()
            all_results[name] = results
        
        # Generate comparison report
        comparison = self._generate_comparison_report( all_results )
        
        print( f"\n" + "="*80 )
        print( "COMPARISON SUMMARY" )
        print( "="*80 )
        
        self._print_comparison_summary( comparison )
        
        return {
            "individual_results": all_results,
            "comparison": comparison,
            "timestamp": time.strftime( "%Y-%m-%d @ %H:%M:%S %Z" )
        }
    
    def _generate_comparison_report( self, results: Dict[str, Any] ) -> Dict[str, Any]:
        """Generate side-by-side comparison metrics."""
        comparison = {
            "success_rates": {},
            "performance_comparison": {},
            "reliability_comparison": {},
            "feature_parity": {}
        }
        
        # Compare success rates
        for name, result in results.items():
            summary = result["summary"]
            comparison["success_rates"][name] = {
                "success_rate": summary["success_rate"],
                "tests_passed": summary["tests_passed"],
                "tests_failed": summary["tests_failed"]
            }
        
        # Compare performance
        for name, result in results.items():
            summary = result["summary"]
            perf = summary.get( "performance_summary", {} )
            
            comparison["performance_comparison"][name] = {
                "avg_search_time_ms": perf.get( "avg_search_time_ms", 0 ),
                "total_duration_ms": summary["total_duration_ms"],
                "avg_test_duration_ms": summary["avg_test_duration_ms"]
            }
        
        # Compare reliability (failed tests)
        for name, result in results.items():
            summary = result["summary"]
            comparison["reliability_comparison"][name] = {
                "failed_tests": summary["failed_tests"],
                "error_rate": ( summary["tests_failed"] / summary["tests_total"] ) * 100
            }
        
        # Identify feature parity issues
        all_test_names = set()
        for result in results.values():
            for test_result in result["individual_results"]:
                all_test_names.add( test_result["test_name"] )
        
        for name, result in results.items():
            passed_tests = {tr["test_name"] for tr in result["individual_results"] if tr["success"]}
            failed_tests = all_test_names - passed_tests
            
            comparison["feature_parity"][name] = {
                "supported_features": list( passed_tests ),
                "unsupported_features": list( failed_tests ),
                "feature_coverage": ( len( passed_tests ) / len( all_test_names ) ) * 100
            }
        
        return comparison
    
    def _print_comparison_summary( self, comparison: Dict[str, Any] ) -> None:
        """Print formatted comparison summary."""
        
        # Success Rate Comparison
        print( f"\n📊 Success Rate Comparison:" )
        for name, data in comparison["success_rates"].items():
            print( f"  {name:20}: {data['success_rate']:5.1f}% ({data['tests_passed']}/{data['tests_passed'] + data['tests_failed']} tests)" )
        
        # Performance Comparison
        print( f"\n⚡ Performance Comparison:" )
        perf_data = comparison["performance_comparison"]
        
        if perf_data:
            # Find best performing for search time
            search_times = {name: data.get( "avg_search_time_ms", float( 'inf' ) ) 
                           for name, data in perf_data.items() if data.get( "avg_search_time_ms", 0 ) > 0}
            
            if search_times:
                fastest = min( search_times, key=search_times.get )
                
                print( f"  Search Performance:" )
                for name, data in perf_data.items():
                    search_time = data.get( "avg_search_time_ms", 0 )
                    if search_time > 0:
                        if name == fastest:
                            print( f"    {name:18}: {search_time:6.1f}ms (fastest)" )
                        else:
                            speedup = search_times[fastest] / search_time
                            print( f"    {name:18}: {search_time:6.1f}ms ({speedup:.1f}x slower)" )
        
        # Reliability Comparison
        print( f"\n🔧 Reliability Comparison:" )
        for name, data in comparison["reliability_comparison"].items():
            error_rate = data["error_rate"]
            failed_count = len( data["failed_tests"] )
            
            if failed_count == 0:
                print( f"  {name:20}: Perfect (0 failures)" )
            else:
                print( f"  {name:20}: {error_rate:5.1f}% error rate ({failed_count} failures)" )
                if failed_count > 0:
                    print( f"                      Failed: {', '.join( data['failed_tests'][:3] )}" )
                    if failed_count > 3:
                        print( f"                              ... and {failed_count - 3} more" )


def quick_smoke_test():
    """Test the comparison suite framework."""
    du.print_banner( "Manager Comparison Suite Smoke Test", prepend_nl=True )
    
    try:
        # This is a minimal test since we don't have initialized managers
        print( "Testing comparison suite framework..." )
        
        # Test TestResult creation
        test_result = TestResult(
            test_name="sample_test",
            success=True,
            duration_ms=50.0,
            result_data={"count": 5}
        )
        
        assert test_result.test_name == "sample_test"
        assert test_result.success == True
        assert test_result.duration_ms == 50.0
        
        print( "✓ TestResult creation working" )
        
        # Test that comparison suite can be instantiated
        comparison_suite = ManagerComparisonSuite( {} )
        assert comparison_suite.managers == {}
        
        print( "✓ ManagerComparisonSuite creation working" )
        
        print( "\n✓ Manager comparison suite smoke test completed successfully" )
        print( "  Note: Full testing requires initialized manager instances" )
        
    except Exception as e:
        print( f"✗ Error during smoke test: {e}" )
        du.print_stack_trace( e, explanation="Comparison suite smoke test failed", caller="quick_smoke_test()" )


if __name__ == "__main__":
    quick_smoke_test()