#!/usr/bin/env python3
"""
Baseline performance measurement for solution snapshot systems.

This script establishes baseline performance metrics for the current file-based
solution snapshot system to enable empirical comparison with the LanceDB implementation.
"""

import os
import sys
import time
import json
from typing import Dict, Any, List

# Add src to path for imports
sys.path.append( os.path.join( os.path.dirname( __file__ ), "..", "" ) )

import cosa.utils.util as du
from cosa.memory.solution_manager_factory import SolutionSnapshotManagerFactory


def run_baseline_performance_tests( debug: bool = False ) -> Dict[str, Any]:
    """
    Run comprehensive baseline performance tests on file-based solution snapshot manager.
    
    Requires:
        - File-based snapshots exist in expected location
        - System has sufficient memory and disk space
        
    Ensures:
        - Returns comprehensive performance baseline metrics
        - Tests various query patterns and dataset sizes
        - Measures initialization, search, and memory usage
        
    Args:
        debug: Enable debug output during testing
        
    Returns:
        Dictionary with baseline performance metrics
    """
    du.print_banner( "Solution Snapshot Manager Baseline Performance Test", prepend_nl=True )
    
    baseline_results = {
        "test_timestamp": time.strftime( "%Y-%m-%d @ %H:%M:%S %Z" ),
        "manager_type": "file_based",
        "system_info": {},
        "initialization": {},
        "search_performance": {},
        "memory_usage": {},
        "dataset_info": {},
        "summary": {}
    }
    
    try:
        # Create file-based manager
        config = {"path": "/src/conf/long-term-memory/solutions/"}
        manager = SolutionSnapshotManagerFactory.create_manager( "file_based", config, debug=debug )
        
        print( f"Created {manager.get_implementation_name()} manager" )
        
        # Test 1: Initialization Performance
        print( "\n🚀 Test 1: Initialization Performance..." )
        init_start = time.time()
        init_metrics = manager.initialize()
        init_duration = ( time.time() - init_start ) * 1000
        
        baseline_results["initialization"] = {
            "duration_ms": init_duration,
            "snapshots_loaded": init_metrics.result_count,
            "memory_increase_mb": init_metrics.memory_usage_mb,
            "success": manager.is_initialized()
        }
        
        print( f"  ✓ Initialization: {init_duration:.1f}ms, {init_metrics.result_count} snapshots loaded" )
        
        # Test 2: Dataset Information
        print( "\n📊 Test 2: Dataset Analysis..." )
        stats = manager.get_stats()
        gists = manager.get_all_gists()
        
        baseline_results["dataset_info"] = {
            "total_snapshots": stats["total_snapshots"],
            "storage_size_mb": stats["storage_size_mb"],
            "unique_gists": len( gists ),
            "avg_size_per_snapshot_kb": ( stats["storage_size_mb"] * 1024 ) / max( stats["total_snapshots"], 1 )
        }
        
        print( f"  ✓ Dataset: {stats['total_snapshots']} snapshots, {stats['storage_size_mb']:.2f} MB, {len( gists )} unique gists" )
        
        # Test 3: Search Performance with Various Query Types
        print( "\n🔍 Test 3: Search Performance..." )
        
        test_queries = [
            # Exact matches (should be fast)
            {"question": "what day is today", "type": "exact_match", "expected_results": 1},
            {"question": "what time is it", "type": "exact_or_synonymous", "expected_results": ">=1"},
            
            # Similarity searches (more intensive)
            {"question": "what is the date", "type": "similarity_search", "expected_results": ">=1"},
            {"question": "current time", "type": "similarity_search", "expected_results": ">=0"},
            {"question": "mathematical calculation", "type": "similarity_search", "expected_results": ">=0"},
            
            # Broader searches
            {"question": "help me", "type": "broad_search", "expected_results": ">=0"},
        ]
        
        search_results = []
        total_search_time = 0
        
        for i, query in enumerate( test_queries ):
            print( f"  Query {i+1}: '{query['question']}' ({query['type']})" )
            
            try:
                results, search_metrics = manager.find_by_question( 
                    query["question"], 
                    limit=10,
                    threshold_question=75.0  # Lower threshold for similarity testing
                )
                
                search_result = {
                    "query": query["question"],
                    "type": query["type"],
                    "results_count": len( results ),
                    "search_time_ms": search_metrics.search_time_ms,
                    "memory_usage_mb": search_metrics.memory_usage_mb,
                    "top_similarity": results[0][0] if results else 0.0
                }
                
                search_results.append( search_result )
                total_search_time += search_metrics.search_time_ms
                
                print( f"    ✓ {len( results )} results in {search_metrics.search_time_ms:.1f}ms" )
                if results and debug:
                    print( f"      Top match: {results[0][0]:.1f}% similarity" )
                
            except Exception as e:
                print( f"    ✗ Query failed: {e}" )
                search_results.append({
                    "query": query["question"],
                    "type": query["type"],
                    "error": str( e ),
                    "results_count": 0,
                    "search_time_ms": 0.0
                })
        
        baseline_results["search_performance"] = {
            "individual_queries": search_results,
            "total_search_time_ms": total_search_time,
            "average_search_time_ms": total_search_time / len( test_queries ),
            "queries_tested": len( test_queries ),
            "successful_queries": len( [r for r in search_results if "error" not in r] )
        }
        
        print( f"  ✓ Search Performance: {len( test_queries )} queries, avg {total_search_time / len( test_queries ):.1f}ms per query" )
        
        # Test 4: Memory Usage Analysis
        print( "\n💾 Test 4: Memory Usage Analysis..." )
        
        # Get current memory usage
        try:
            import psutil
            process = psutil.Process( os.getpid() )
            memory_info = process.memory_info()
            
            baseline_results["memory_usage"] = {
                "rss_mb": memory_info.rss / 1024 / 1024,
                "vms_mb": memory_info.vms / 1024 / 1024,
                "memory_per_snapshot_kb": ( memory_info.rss / 1024 ) / max( stats["total_snapshots"], 1 ),
                "psutil_available": True
            }
            
            print( f"  ✓ Memory Usage: {memory_info.rss / 1024 / 1024:.1f} MB RSS, {( memory_info.rss / 1024 ) / max( stats['total_snapshots'], 1 ):.1f} KB per snapshot" )
            
        except ImportError:
            baseline_results["memory_usage"] = {
                "psutil_available": False,
                "note": "psutil not available for detailed memory analysis"
            }
            print( "  ⚠ psutil not available for memory analysis" )
        
        # Test 5: Code Similarity Search (if we have snapshots with code)
        print( "\n🔧 Test 5: Code Similarity Search..." )
        
        code_search_results = []
        snapshots_with_code = []
        
        # Find snapshots that have code embeddings
        for query in ["what is 5 times 5", "what is two plus two", "what day is today"]:
            try:
                results, _ = manager.find_by_question( query, limit=1 )
                if results and results[0][1].code_embedding:
                    snapshots_with_code.append( results[0][1] )
                    if len( snapshots_with_code ) >= 3:  # Limit to 3 for performance
                        break
            except:
                continue
        
        if snapshots_with_code:
            for i, exemplar in enumerate( snapshots_with_code ):
                try:
                    results, search_metrics = manager.find_by_code_similarity( 
                        exemplar, 
                        threshold=70.0, 
                        limit=5 
                    )
                    
                    code_search_results.append({
                        "exemplar_question": exemplar.question,
                        "results_count": len( results ),
                        "search_time_ms": search_metrics.search_time_ms,
                        "top_similarity": results[0][0] if results else 0.0
                    })
                    
                    print( f"  ✓ Code search {i+1}: {len( results )} results in {search_metrics.search_time_ms:.1f}ms" )
                    
                except Exception as e:
                    print( f"  ✗ Code search {i+1} failed: {e}" )
        else:
            print( "  ⚠ No snapshots with code embeddings found" )
        
        baseline_results["code_similarity"] = {
            "snapshots_tested": len( snapshots_with_code ),
            "search_results": code_search_results
        }
        
        # Generate Summary
        print( "\n📋 Test Summary..." )
        
        summary = {
            "overall_performance": "good" if baseline_results["initialization"]["success"] else "poor",
            "total_test_time_ms": ( time.time() - init_start ) * 1000,
            "snapshots_loaded": baseline_results["initialization"]["snapshots_loaded"],
            "average_search_time_ms": baseline_results["search_performance"]["average_search_time_ms"],
            "storage_efficiency_kb_per_snapshot": baseline_results["dataset_info"]["avg_size_per_snapshot_kb"],
            "ready_for_comparison": True
        }
        
        baseline_results["summary"] = summary
        
        print( f"  ✓ Overall Performance: {summary['overall_performance']}" )
        print( f"  ✓ Average Search Time: {summary['average_search_time_ms']:.1f}ms" )
        print( f"  ✓ Storage Efficiency: {summary['storage_efficiency_kb_per_snapshot']:.1f} KB per snapshot" )
        print( f"  ✓ Ready for LanceDB comparison: {summary['ready_for_comparison']}" )
        
        return baseline_results
        
    except Exception as e:
        print( f"✗ Baseline test failed: {e}" )
        if debug:
            import traceback
            traceback.print_exc()
        
        baseline_results["error"] = str( e )
        baseline_results["summary"] = {
            "overall_performance": "failed",
            "ready_for_comparison": False
        }
        
        return baseline_results


def save_baseline_results( results: Dict[str, Any], output_file: str = None ) -> str:
    """
    Save baseline results to JSON file.
    
    Args:
        results: Baseline test results
        output_file: Optional custom output file path
        
    Returns:
        Path to saved results file
    """
    if output_file is None:
        timestamp = time.strftime( "%Y%m%d_%H%M%S" )
        output_file = f"/tmp/solution_snapshot_baseline_{timestamp}.json"
    
    try:
        with open( output_file, "w" ) as f:
            json.dump( results, f, indent=2 )
        
        print( f"\n💾 Baseline results saved to: {output_file}" )
        return output_file
        
    except Exception as e:
        print( f"✗ Failed to save results: {e}" )
        return ""


def main():
    """Main entry point for baseline performance testing."""
    import argparse
    
    parser = argparse.ArgumentParser( description="Measure baseline performance of solution snapshot manager" )
    parser.add_argument( "--debug", action="store_true", help="Enable debug output" )
    parser.add_argument( "--save", help="Save results to specified file" )
    parser.add_argument( "--quiet", action="store_true", help="Minimal output" )
    
    args = parser.parse_args()
    
    if not args.quiet:
        print( "🔬 Starting Solution Snapshot Manager Baseline Performance Test" )
        print( f"   Debug mode: {'enabled' if args.debug else 'disabled'}" )
    
    # Run baseline tests
    results = run_baseline_performance_tests( debug=args.debug )
    
    # Save results if requested
    if args.save:
        save_baseline_results( results, args.save )
    elif not args.quiet:
        save_baseline_results( results )
    
    # Print final summary
    if not args.quiet:
        print( "\n🎯 Baseline Performance Summary:" )
        if "summary" in results:
            summary = results["summary"]
            print( f"   • Performance: {summary.get( 'overall_performance', 'unknown' )}" )
            print( f"   • Snapshots: {summary.get( 'snapshots_loaded', 0 )}" )
            print( f"   • Avg Search: {summary.get( 'average_search_time_ms', 0 ):.1f}ms" )
            print( f"   • Storage: {summary.get( 'storage_efficiency_kb_per_snapshot', 0 ):.1f} KB/snapshot" )
            print( f"   • Ready for comparison: {summary.get( 'ready_for_comparison', False )}" )
        
    return 0 if results.get( "summary", {} ).get( "ready_for_comparison", False ) else 1


if __name__ == "__main__":
    exit( main() )