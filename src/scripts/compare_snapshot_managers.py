#!/usr/bin/env python3
"""
Comprehensive comparison between file-based and LanceDB solution snapshot managers.

This script runs empirical tests to validate that both implementations provide
identical functionality while measuring performance differences.
"""

import os
import sys
import time
import json
from typing import Dict, Any

# Add src to path for imports
sys.path.append( os.path.join( os.path.dirname( __file__ ), "..", "" ) )

import cosa.utils.util as du
from cosa.memory.solution_manager_factory import SolutionSnapshotManagerFactory
from cosa.tests.comparison.manager_comparison_suite import ManagerComparisonSuite


def run_manager_comparison( debug: bool = False ) -> Dict[str, Any]:
    """
    Run comprehensive comparison between file-based and LanceDB managers.
    
    Args:
        debug: Enable debug output
        
    Returns:
        Complete comparison results
    """
    du.print_banner( "Solution Snapshot Manager Comparison", prepend_nl=True )
    
    print( "🎯 Comparing file-based vs LanceDB implementations" )
    print( "   • Same interface, different backends" )
    print( "   • Identical test suite for empirical validation" )
    print( "   • Performance and reliability comparison" )
    
    try:
        # Create both manager implementations
        print( f"\n🏗️ Setting up managers..." )
        
        # File-based manager
        file_config = {
            "path": "/src/conf/long-term-memory/solutions/"
        }
        
        file_manager = SolutionSnapshotManagerFactory.create_manager(
            "file_based", file_config, debug=debug
        )
        
        print( f"  ✓ File-based manager created" )
        
        # LanceDB manager  
        lance_config = {
            "db_path": "/src/conf/long-term-memory/lupin.lancedb",
            "table_name": "comparison_test_snapshots"
        }
        
        lance_manager = SolutionSnapshotManagerFactory.create_manager(
            "lancedb", lance_config, debug=debug
        )
        
        print( f"  ✓ LanceDB manager created" )
        
        # Set up comparison suite
        managers = {
            "File-Based": file_manager,
            "LanceDB": lance_manager
        }
        
        comparison_suite = ManagerComparisonSuite( managers )
        
        # Run comprehensive comparison
        print( f"\n🧪 Running comparative analysis..." )
        results = comparison_suite.run_comparative_analysis()
        
        return results
        
    except Exception as e:
        print( f"✗ Comparison failed: {e}" )
        if debug:
            import traceback
            traceback.print_exc()
        
        return {
            "error": str( e ),
            "success": False
        }


def save_comparison_results( results: Dict[str, Any], output_file: str = None ) -> str:
    """
    Save comparison results to JSON file.
    
    Args:
        results: Comparison results
        output_file: Optional output file path
        
    Returns:
        Path to saved file
    """
    if output_file is None:
        timestamp = time.strftime( "%Y%m%d_%H%M%S" )
        output_file = f"/tmp/manager_comparison_{timestamp}.json"
    
    try:
        with open( output_file, "w" ) as f:
            json.dump( results, f, indent=2 )
        
        print( f"\n💾 Comparison results saved to: {output_file}" )
        return output_file
        
    except Exception as e:
        print( f"✗ Failed to save results: {e}" )
        return ""


def print_executive_summary( results: Dict[str, Any] ) -> None:
    """Print high-level summary of comparison results."""
    
    if "error" in results:
        print( f"\n❌ Comparison failed: {results['error']}" )
        return
    
    comparison = results.get( "comparison", {} )
    
    print( f"\n📋 Executive Summary" )
    print( f"   ═══════════════════" )
    
    # Success rates
    success_rates = comparison.get( "success_rates", {} )
    if success_rates:
        print( f"\n   🎯 Functionality Compatibility:" )
        for name, data in success_rates.items():
            rate = data["success_rate"]
            status = "✓ Perfect" if rate == 100.0 else f"⚠ {rate:.1f}%"
            print( f"      {name:12}: {status}" )
    
    # Performance comparison
    perf_data = comparison.get( "performance_comparison", {} )
    if perf_data:
        search_times = {name: data.get( "avg_search_time_ms", 0 ) 
                       for name, data in perf_data.items() if data.get( "avg_search_time_ms", 0 ) > 0}
        
        if len( search_times ) >= 2:
            times_list = list( search_times.values() )
            speedup = max( times_list ) / min( times_list )
            
            print( f"\n   ⚡ Performance Difference:" )
            for name, search_time in search_times.items():
                print( f"      {name:12}: {search_time:.1f}ms avg search" )
            print( f"      Speedup:     {speedup:.1f}x difference" )
    
    # Feature parity
    feature_parity = comparison.get( "feature_parity", {} )
    if feature_parity:
        print( f"\n   🔧 Feature Compatibility:" )
        for name, data in feature_parity.items():
            coverage = data["feature_coverage"]
            unsupported = len( data["unsupported_features"] )
            
            if coverage == 100.0:
                print( f"      {name:12}: ✓ Full compatibility" )
            else:
                print( f"      {name:12}: ⚠ {coverage:.1f}% ({unsupported} missing features)" )
    
    # Overall assessment
    print( f"\n   🏆 Overall Assessment:" )
    
    # Check if both managers have high success rates
    all_success_rates = [data["success_rate"] for data in success_rates.values()]
    avg_success = sum( all_success_rates ) / len( all_success_rates ) if all_success_rates else 0
    
    if avg_success >= 95.0:
        print( f"      ✓ Both implementations are highly compatible" )
        
        if len( search_times ) >= 2:
            if speedup >= 2.0:
                faster_impl = min( search_times, key=search_times.get )
                print( f"      ✓ {faster_impl} shows significant performance advantage" )
            else:
                print( f"      ≈ Performance is comparable between implementations" )
        
        print( f"      ✓ Ready for production comparison and A/B testing" )
    else:
        print( f"      ⚠ Implementation differences detected - review required" )


def main():
    """Main entry point for manager comparison."""
    import argparse
    
    parser = argparse.ArgumentParser( description="Compare solution snapshot manager implementations" )
    parser.add_argument( "--debug", action="store_true", help="Enable debug output" )
    parser.add_argument( "--save", help="Save results to specified file" )
    parser.add_argument( "--quiet", action="store_true", help="Minimal output" )
    
    args = parser.parse_args()
    
    if not args.quiet:
        print( "🔬 Starting Manager Comparison Analysis" )
        print( f"   Debug mode: {'enabled' if args.debug else 'disabled'}" )
    
    # Run comparison
    results = run_manager_comparison( debug=args.debug )
    
    # Save results if requested
    if args.save:
        save_comparison_results( results, args.save )
    elif not args.quiet:
        save_comparison_results( results )
    
    # Print summary
    if not args.quiet:
        print_executive_summary( results )
    
    return 0 if results.get( "success", True ) else 1


if __name__ == "__main__":
    exit( main() )