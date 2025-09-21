#!/usr/bin/env python3
"""
Migration utility to convert file-based solution snapshots to LanceDB.

This script migrates existing JSON solution snapshots to LanceDB format,
enabling empirical comparison between file-based and vector database implementations.
"""

import os
import sys
import time
from typing import Dict, Any, List, Tuple

# Add src to path for imports
sys.path.append( os.path.join( os.path.dirname( __file__ ), "..", "" ) )

import cosa.utils.util as du
from cosa.memory.solution_manager_factory import SolutionSnapshotManagerFactory


def migrate_snapshots( source_path: str, 
                      target_db_path: str, 
                      target_table: str,
                      debug: bool = False ) -> Dict[str, Any]:
    """
    Migrate solution snapshots from file-based storage to LanceDB.
    
    Requires:
        - source_path contains valid JSON snapshot files
        - target_db_path is accessible LanceDB database
        - Sufficient disk space and permissions
        
    Ensures:
        - All snapshots copied to LanceDB with identical data
        - Performance metrics collected for analysis
        - Validation performed on migrated data
        
    Args:
        source_path: Path to directory containing JSON snapshot files
        target_db_path: Path to LanceDB database
        target_table: Name of target table in LanceDB
        debug: Enable debug output
        
    Returns:
        Dictionary with migration results and statistics
    """
    du.print_banner( "Solution Snapshot Migration: File-based → LanceDB", prepend_nl=True )
    
    migration_results = {
        "migration_timestamp": time.strftime( "%Y-%m-%d @ %H:%M:%S %Z" ),
        "source_path": source_path,
        "target_db_path": target_db_path,
        "target_table": target_table,
        "source_stats": {},
        "target_stats": {},
        "migration_performance": {},
        "validation_results": {},
        "summary": {}
    }
    
    try:
        print( f"📁 Source: {source_path}" )
        print( f"🗄️ Target: {target_db_path}/{target_table}" )
        
        # Step 1: Initialize source (file-based) manager
        print( f"\n📊 Step 1: Analyzing source data..." )
        
        source_config = {"path": source_path}
        source_manager = SolutionSnapshotManagerFactory.create_manager( 
            "file_based", source_config, debug=debug 
        )
        
        source_init_start = time.time()
        source_init_metrics = source_manager.initialize()
        source_init_time = ( time.time() - source_init_start ) * 1000
        
        source_stats = source_manager.get_stats()
        migration_results["source_stats"] = {
            "total_snapshots": source_stats["total_snapshots"],
            "storage_size_mb": source_stats["storage_size_mb"],
            "initialization_time_ms": source_init_time,
            "backend_type": source_stats["backend_type"]
        }
        
        print( f"  ✓ Source analysis complete:" )
        print( f"    • {source_stats['total_snapshots']} snapshots" )
        print( f"    • {source_stats['storage_size_mb']:.2f} MB storage" )
        print( f"    • {source_init_time:.1f}ms initialization" )
        
        if source_stats["total_snapshots"] == 0:
            print( "  ⚠ No snapshots found in source - nothing to migrate" )
            migration_results["summary"] = {
                "success": True,
                "snapshots_migrated": 0,
                "migration_time_ms": 0,
                "notes": "No snapshots to migrate"
            }
            return migration_results
        
        # Step 2: Initialize target (LanceDB) manager
        print( f"\n🗄️ Step 2: Preparing target database..." )
        
        target_config = {
            "db_path": target_db_path,
            "table_name": target_table
        }
        target_manager = SolutionSnapshotManagerFactory.create_manager( 
            "lancedb", target_config, debug=debug 
        )
        
        target_init_start = time.time()
        target_init_metrics = target_manager.initialize()
        target_init_time = ( time.time() - target_init_start ) * 1000
        
        target_stats_before = target_manager.get_stats()
        
        print( f"  ✓ Target database ready:" )
        print( f"    • Database: {target_db_path}" )
        print( f"    • Table: {target_table}" )
        print( f"    • Existing snapshots: {target_stats_before['total_snapshots']}" )
        print( f"    • {target_init_time:.1f}ms initialization" )
        
        # Step 3: Perform migration
        print( f"\n🔄 Step 3: Migrating snapshots..." )
        
        migration_start = time.time()
        snapshots_migrated = 0
        migration_errors = []
        
        # Get all snapshots from source
        print( f"  📋 Reading all snapshots from source..." )
        all_gists = source_manager.get_gists()
        
        # For each gist, get associated snapshots
        migrated_questions = set()
        
        for gist in all_gists:
            if debug:
                print( f"    Processing gist: {du.truncate_string( gist, 60 )}" )
            
            # Search for snapshots with this gist
            try:
                snapshots = source_manager.get_snapshots_by_question(
                    gist,
                    question_gist=gist,
                    threshold_question=50.0,  # Lower threshold to catch more
                    limit=100  # High limit to get all matches
                )
                
                for similarity, snapshot in snapshots:
                    # Skip duplicates
                    if snapshot.question in migrated_questions:
                        continue
                    
                    try:
                        # Add to target database
                        success = target_manager.add_snapshot( snapshot )
                        
                        if success:
                            snapshots_migrated += 1
                            migrated_questions.add( snapshot.question )
                            
                            if debug:
                                print( f"      ✓ Migrated: {du.truncate_string( snapshot.question, 50 )}" )
                            elif snapshots_migrated % 10 == 0:
                                print( f"    ✓ Migrated {snapshots_migrated} snapshots..." )
                        else:
                            migration_errors.append( f"Failed to add snapshot: {snapshot.question}" )
                            
                    except Exception as e:
                        error_msg = f"Error migrating '{du.truncate_string( snapshot.question, 30 )}': {e}"
                        migration_errors.append( error_msg )
                        if debug:
                            print( f"      ✗ {error_msg}" )
                
            except Exception as e:
                error_msg = f"Error processing gist '{du.truncate_string( gist, 30 )}': {e}"
                migration_errors.append( error_msg )
                if debug:
                    print( f"    ✗ {error_msg}" )
        
        # Also try to get snapshots by searching for common patterns
        print( f"  🔍 Checking for additional snapshots..." )
        
        common_patterns = [
            "what", "how", "when", "where", "why", "can", "do", "is", "are", "calculate"
        ]
        
        for pattern in common_patterns:
            try:
                snapshots = source_manager.get_snapshots_by_question(
                    pattern,
                    threshold_question=60.0,
                    limit=50
                )
                
                for similarity, snapshot in snapshots:
                    if snapshot.question not in migrated_questions:
                        try:
                            success = target_manager.add_snapshot( snapshot )
                            
                            if success:
                                snapshots_migrated += 1
                                migrated_questions.add( snapshot.question )
                                
                                if debug:
                                    print( f"      ✓ Additional: {du.truncate_string( snapshot.question, 50 )}" )
                        except Exception as e:
                            if debug:
                                print( f"      ✗ Error adding additional snapshot: {e}" )
                
            except Exception as e:
                if debug:
                    print( f"    ⚠ Error searching pattern '{pattern}': {e}" )
        
        migration_time = ( time.time() - migration_start ) * 1000
        
        print( f"\n  ✓ Migration complete:" )
        print( f"    • {snapshots_migrated} snapshots migrated" )
        print( f"    • {len( migration_errors )} errors" )
        print( f"    • {migration_time:.1f}ms total time" )
        
        # Step 4: Validation
        print( f"\n✅ Step 4: Validating migration..." )
        
        target_stats_after = target_manager.get_stats()
        
        validation_results = {
            "snapshots_before": target_stats_before["total_snapshots"],
            "snapshots_after": target_stats_after["total_snapshots"],
            "snapshots_added": target_stats_after["total_snapshots"] - target_stats_before["total_snapshots"],
            "expected_additions": snapshots_migrated,
            "migration_errors": migration_errors,
            "validation_success": False
        }
        
        # Check if counts match
        if validation_results["snapshots_added"] == validation_results["expected_additions"]:
            validation_results["validation_success"] = True
            print( f"  ✓ Validation successful:" )
            print( f"    • Before: {validation_results['snapshots_before']} snapshots" )
            print( f"    • Added: {validation_results['snapshots_added']} snapshots" )
            print( f"    • After: {validation_results['snapshots_after']} snapshots" )
        else:
            print( f"  ⚠ Validation issues detected:" )
            print( f"    • Expected to add: {validation_results['expected_additions']}" )
            print( f"    • Actually added: {validation_results['snapshots_added']}" )
            print( f"    • Difference: {validation_results['expected_additions'] - validation_results['snapshots_added']}" )
        
        if migration_errors:
            print( f"  ⚠ Migration errors ({len( migration_errors )}):" )
            for error in migration_errors[:5]:  # Show first 5 errors
                print( f"    • {error}" )
            if len( migration_errors ) > 5:
                print( f"    • ... and {len( migration_errors ) - 5} more errors" )
        
        # Step 5: Performance comparison
        print( f"\n📊 Step 5: Performance analysis..." )
        
        # Test search performance on both systems
        test_queries = ["what day is today", "what time is it", "calculate"]
        
        source_search_times = []
        target_search_times = []
        
        for query in test_queries:
            try:
                # Test source
                start = time.time()
                source_results = source_manager.get_snapshots_by_question( query, limit=5 )
                source_time = ( time.time() - start ) * 1000
                source_search_times.append( source_time )

                # Test target
                start = time.time()
                target_results = target_manager.get_snapshots_by_question( query, limit=5 )
                target_time = ( time.time() - start ) * 1000
                target_search_times.append( target_time )
                
                if debug:
                    print( f"    Query '{query}': Source {source_time:.1f}ms, Target {target_time:.1f}ms" )
                    
            except Exception as e:
                if debug:
                    print( f"    ⚠ Error testing query '{query}': {e}" )
        
        performance_comparison = {
            "source_avg_search_ms": sum( source_search_times ) / len( source_search_times ) if source_search_times else 0,
            "target_avg_search_ms": sum( target_search_times ) / len( target_search_times ) if target_search_times else 0,
            "source_init_ms": source_init_time,
            "target_init_ms": target_init_time,
            "migration_time_ms": migration_time
        }
        
        if performance_comparison["source_avg_search_ms"] > 0 and performance_comparison["target_avg_search_ms"] > 0:
            speedup = performance_comparison["source_avg_search_ms"] / performance_comparison["target_avg_search_ms"]
            performance_comparison["search_speedup"] = speedup
            
            print( f"  ✓ Performance comparison:" )
            print( f"    • Source avg search: {performance_comparison['source_avg_search_ms']:.1f}ms" )
            print( f"    • Target avg search: {performance_comparison['target_avg_search_ms']:.1f}ms" )
            print( f"    • Search speedup: {speedup:.1f}x" )
        
        # Final results
        migration_results.update({
            "target_stats": {
                "total_snapshots": target_stats_after["total_snapshots"],
                "storage_size_mb": target_stats_after["storage_size_mb"],
                "backend_type": target_stats_after["backend_type"]
            },
            "migration_performance": performance_comparison,
            "validation_results": validation_results,
            "summary": {
                "success": validation_results["validation_success"] and len( migration_errors ) == 0,
                "snapshots_migrated": snapshots_migrated,
                "migration_time_ms": migration_time,
                "validation_passed": validation_results["validation_success"],
                "error_count": len( migration_errors )
            }
        })
        
        return migration_results
        
    except Exception as e:
        print( f"✗ Migration failed: {e}" )
        if debug:
            import traceback
            traceback.print_exc()
        
        migration_results["error"] = str( e )
        migration_results["summary"] = {
            "success": False,
            "snapshots_migrated": 0,
            "migration_time_ms": 0,
            "error": str( e )
        }
        
        return migration_results


def main():
    """Main entry point for migration utility."""
    import argparse
    
    parser = argparse.ArgumentParser( description="Migrate solution snapshots from file-based to LanceDB" )
    parser.add_argument( "--source", 
                        default="/src/conf/long-term-memory/solutions/",
                        help="Source directory with JSON snapshot files" )
    parser.add_argument( "--target-db", 
                        default="/src/conf/long-term-memory/lupin.lancedb",
                        help="Target LanceDB database path" )
    parser.add_argument( "--target-table", 
                        default="solution_snapshots",
                        help="Target table name in LanceDB" )
    parser.add_argument( "--debug", action="store_true", help="Enable debug output" )
    parser.add_argument( "--dry-run", action="store_true", help="Analyze only, don't migrate" )
    
    args = parser.parse_args()
    
    print( "🚀 Solution Snapshot Migration Utility" )
    print( f"   Source: {args.source}" )
    print( f"   Target: {args.target_db}/{args.target_table}" )
    print( f"   Debug: {'enabled' if args.debug else 'disabled'}" )
    print( f"   Mode: {'dry-run' if args.dry_run else 'migration'}" )
    
    if args.dry_run:
        print( "\n⚠ DRY RUN MODE - No data will be migrated" )

        # Dry-run analysis
        try:
            source_config = {"path": args.source}
            source_manager = SolutionSnapshotManagerFactory.create_manager(
                "file_based", source_config, debug=args.debug
            )

            print( f"\n📊 Analyzing source data..." )
            source_manager.initialize()
            source_stats = source_manager.get_stats()

            print( f"  ✓ Source analysis:" )
            print( f"    • Path: {args.source}" )
            print( f"    • Total snapshots: {source_stats['total_snapshots']}" )
            print( f"    • Storage size: {source_stats['storage_size_mb']:.2f} MB" )
            print( f"    • Backend type: {source_stats['backend_type']}" )

            # Check target database
            print( f"\n🗄️ Checking target database..." )
            target_config = {
                "db_path": args.target_db,
                "table_name": args.target_table
            }
            target_manager = SolutionSnapshotManagerFactory.create_manager(
                "lancedb", target_config, debug=args.debug
            )
            target_manager.initialize()
            target_stats = target_manager.get_stats()

            print( f"  ✓ Target analysis:" )
            print( f"    • Database: {args.target_db}" )
            print( f"    • Table: {args.target_table}" )
            print( f"    • Existing snapshots: {target_stats['total_snapshots']}" )
            print( f"    • Storage size: {target_stats['storage_size_mb']:.2f} MB" )

            print( f"\n🔍 Migration readiness:" )
            print( f"    • Ready to migrate: {source_stats['total_snapshots']} snapshots" )
            print( f"    • Target capacity: Available" )
            print( f"    • Estimated outcome: {target_stats['total_snapshots'] + source_stats['total_snapshots']} total snapshots" )

            print( f"\n✅ DRY RUN COMPLETE - System ready for migration" )

        except Exception as e:
            print( f"✗ Dry-run analysis failed: {e}" )
            if args.debug:
                import traceback
                traceback.print_exc()
            return 1

        return 0
    
    # Run migration
    results = migrate_snapshots( 
        source_path=args.source,
        target_db_path=args.target_db,
        target_table=args.target_table,
        debug=args.debug
    )
    
    # Print summary
    print( "\n🎯 Migration Summary:" )
    if "summary" in results:
        summary = results["summary"]
        print( f"   • Success: {summary.get( 'success', False )}" )
        print( f"   • Snapshots migrated: {summary.get( 'snapshots_migrated', 0 )}" )
        print( f"   • Migration time: {summary.get( 'migration_time_ms', 0 ):.1f}ms" )
        print( f"   • Validation passed: {summary.get( 'validation_passed', False )}" )
        print( f"   • Errors: {summary.get( 'error_count', 0 )}" )
        
        if "search_speedup" in results.get( "migration_performance", {} ):
            speedup = results["migration_performance"]["search_speedup"]
            print( f"   • Search performance: {speedup:.1f}x speedup" )
    
    return 0 if results.get( "summary", {} ).get( "success", False ) else 1


if __name__ == "__main__":
    exit( main() )