#!/usr/bin/env python3
"""
Complete migration utility that enumerates ALL loaded snapshots directly.

This script fixes the original migration flaws by:
1. Directly accessing all loaded snapshots instead of search-based discovery
2. Ensuring 100% migration of all loaded data
3. Providing comprehensive validation and error handling
"""

import os
import sys
import time
from typing import Dict, Any, List, Set

# Add src to path for imports
sys.path.append( os.path.join( os.path.dirname( __file__ ), "..", "" ) )

import cosa.utils.util as du
from cosa.memory.solution_manager_factory import SolutionSnapshotManagerFactory


def migrate_all_snapshots( source_path: str,
                          target_db_path: str,
                          target_table: str,
                          clear_target: bool = False,
                          debug: bool = False ) -> Dict[str, Any]:
    """
    Migrate ALL loaded solution snapshots from file-based storage to LanceDB.

    This approach directly enumerates all loaded snapshots instead of using
    search-based discovery, ensuring 100% migration success.

    Args:
        source_path: Path to directory containing JSON snapshot files
        target_db_path: Path to LanceDB database
        target_table: Name of target table in LanceDB
        clear_target: Whether to clear existing target table first
        debug: Enable debug output

    Returns:
        Dictionary with complete migration results and statistics
    """
    du.print_banner( "Complete Solution Snapshot Migration: File-based → LanceDB", prepend_nl=True )

    migration_results = {
        "migration_timestamp": time.strftime( "%Y-%m-%d @ %H:%M:%S %Z" ),
        "source_path": source_path,
        "target_db_path": target_db_path,
        "target_table": target_table,
        "clear_target": clear_target,
        "source_stats": {},
        "target_stats": {},
        "migration_performance": {},
        "validation_results": {},
        "summary": {}
    }

    try:
        print( f"📁 Source: {source_path}" )
        print( f"🗄️ Target: {target_db_path}/{target_table}" )
        print( f"🧹 Clear target: {'Yes' if clear_target else 'No'}" )

        # Step 1: Initialize source (file-based) manager
        print( f"\n📊 Step 1: Loading source data..." )

        source_config = {"path": source_path}
        source_manager = SolutionSnapshotManagerFactory.create_manager(
            "file_based", source_config, debug=debug
        )

        source_init_start = time.time()
        source_manager.initialize()
        source_init_time = ( time.time() - source_init_start ) * 1000

        source_stats = source_manager.get_stats()
        migration_results["source_stats"] = {
            "total_snapshots": source_stats["total_snapshots"],
            "storage_size_mb": source_stats["storage_size_mb"],
            "initialization_time_ms": source_init_time,
            "backend_type": source_stats["backend_type"]
        }

        print( f"  ✓ Source loaded:" )
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

        # Clear target table if requested
        if clear_target:
            import lancedb
            try:
                db = lancedb.connect( target_db_path )
                if target_table in db.table_names():
                    print( f"  🧹 Clearing existing table: {target_table}" )
                    # LanceDB doesn't have a direct drop table, so we'll delete the directory
                    import shutil
                    table_dir = os.path.join( target_db_path, f"{target_table}.lance" )
                    if os.path.exists( table_dir ):
                        shutil.rmtree( table_dir )
                        print( f"    ✓ Cleared: {table_dir}" )
            except Exception as e:
                print( f"    ⚠ Warning clearing table: {e}" )

        target_manager = SolutionSnapshotManagerFactory.create_manager(
            "lancedb", target_config, debug=debug
        )

        target_init_start = time.time()
        target_manager.initialize()
        target_init_time = ( time.time() - target_init_start ) * 1000

        target_stats_before = target_manager.get_stats()

        print( f"  ✓ Target ready:" )
        print( f"    • Database: {target_db_path}" )
        print( f"    • Table: {target_table}" )
        print( f"    • Existing snapshots: {target_stats_before['total_snapshots']}" )
        print( f"    • {target_init_time:.1f}ms initialization" )

        # Step 3: Direct enumeration migration
        print( f"\n🔄 Step 3: Direct enumeration migration..." )

        migration_start = time.time()
        snapshots_migrated = 0
        migration_errors = []
        migrated_questions = set()

        # Direct access to internal snapshot storage
        print( f"  📋 Accessing all loaded snapshots directly..." )

        # Get all unique snapshots from internal storage
        all_snapshots = []
        processed_questions = set()

        # Access _snapshots_by_question (direct mapping: question → SolutionSnapshot)
        if hasattr( source_manager, '_snapshots_by_question' ) and source_manager._snapshots_by_question:
            print( f"    • Found _snapshots_by_question with {len(source_manager._snapshots_by_question)} entries" )

            for question, snapshot in source_manager._snapshots_by_question.items():
                if question not in processed_questions:
                    all_snapshots.append( snapshot )
                    processed_questions.add( question )

        print( f"    • Primary snapshots: {len(all_snapshots)}" )

        # Skip synonymous questions since they're duplicates with similarity scores
        # The _snapshots_by_synonymous_questions contains (similarity, snapshot) tuples
        # but the snapshots are the same objects as in _snapshots_by_question

        print( f"  ✓ Found {len(all_snapshots)} total snapshots for migration" )

        # Migrate each snapshot directly
        for i, snapshot in enumerate( all_snapshots, 1 ):
            try:
                # Skip duplicates
                if snapshot.question in migrated_questions:
                    if debug:
                        print( f"    ⏭️ Skipping duplicate: {du.truncate_string( snapshot.question, 50 )}" )
                    continue

                # Add to target database
                success = target_manager.add_snapshot( snapshot )

                if success:
                    snapshots_migrated += 1
                    migrated_questions.add( snapshot.question )

                    if debug:
                        print( f"    ✓ Migrated {snapshots_migrated}: {du.truncate_string( snapshot.question, 50 )}" )
                    elif snapshots_migrated % 10 == 0:
                        print( f"    ✓ Migrated {snapshots_migrated} snapshots..." )
                else:
                    migration_errors.append( f"Failed to add snapshot: {snapshot.question}" )
                    if debug:
                        print( f"    ✗ Failed: {du.truncate_string( snapshot.question, 50 )}" )

            except Exception as e:
                error_msg = f"Error migrating '{du.truncate_string( snapshot.question, 30 )}': {e}"
                migration_errors.append( error_msg )
                if debug:
                    print( f"    ✗ {error_msg}" )

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
            "validation_success": False,
            "source_vs_target_match": False
        }

        # Check if counts match
        if validation_results["snapshots_added"] == validation_results["expected_additions"]:
            validation_results["validation_success"] = True
            print( f"  ✓ Migration validation successful:" )
            print( f"    • Before: {validation_results['snapshots_before']} snapshots" )
            print( f"    • Added: {validation_results['snapshots_added']} snapshots" )
            print( f"    • After: {validation_results['snapshots_after']} snapshots" )
        else:
            print( f"  ⚠ Migration validation issues:" )
            print( f"    • Expected to add: {validation_results['expected_additions']}" )
            print( f"    • Actually added: {validation_results['snapshots_added']}" )

        # Check source vs target match
        if target_stats_after["total_snapshots"] >= source_stats["total_snapshots"]:
            validation_results["source_vs_target_match"] = True
            print( f"  ✓ Source-target validation: {source_stats['total_snapshots']} source ≤ {target_stats_after['total_snapshots']} target" )
        else:
            print( f"  ⚠ Source-target mismatch: {source_stats['total_snapshots']} source > {target_stats_after['total_snapshots']} target" )

        if migration_errors:
            print( f"  ⚠ Migration errors ({len( migration_errors )}):" )
            for error in migration_errors[:5]:  # Show first 5 errors
                print( f"    • {error}" )
            if len( migration_errors ) > 5:
                print( f"    • ... and {len( migration_errors ) - 5} more errors" )

        # Step 5: Performance comparison (simplified)
        print( f"\n📊 Step 5: Performance summary..." )

        performance_comparison = {
            "source_init_ms": source_init_time,
            "target_init_ms": target_init_time,
            "migration_time_ms": migration_time,
            "snapshots_per_second": (snapshots_migrated / (migration_time / 1000)) if migration_time > 0 else 0
        }

        print( f"  ✓ Performance summary:" )
        print( f"    • Source init: {source_init_time:.1f}ms" )
        print( f"    • Target init: {target_init_time:.1f}ms" )
        print( f"    • Migration: {migration_time:.1f}ms" )
        print( f"    • Speed: {performance_comparison['snapshots_per_second']:.1f} snapshots/sec" )

        # Final results
        overall_success = (
            validation_results["validation_success"] and
            validation_results["source_vs_target_match"] and
            len( migration_errors ) == 0
        )

        migration_results.update({
            "target_stats": {
                "total_snapshots": target_stats_after["total_snapshots"],
                "storage_size_mb": target_stats_after["storage_size_mb"],
                "backend_type": target_stats_after["backend_type"]
            },
            "migration_performance": performance_comparison,
            "validation_results": validation_results,
            "summary": {
                "success": overall_success,
                "snapshots_migrated": snapshots_migrated,
                "migration_time_ms": migration_time,
                "validation_passed": validation_results["validation_success"],
                "source_target_match": validation_results["source_vs_target_match"],
                "error_count": len( migration_errors ),
                "completion_rate": (snapshots_migrated / source_stats["total_snapshots"]) if source_stats["total_snapshots"] > 0 else 0
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
    """Main entry point for complete migration utility."""
    import argparse

    parser = argparse.ArgumentParser( description="Complete migration: all loaded snapshots to LanceDB" )
    parser.add_argument( "--source",
                        default="src/conf/long-term-memory/solutions/",
                        help="Source directory with JSON snapshot files" )
    parser.add_argument( "--target-db",
                        default="src/conf/long-term-memory/lupin.lancedb",
                        help="Target LanceDB database path" )
    parser.add_argument( "--target-table",
                        default="solution_snapshots_complete",
                        help="Target table name in LanceDB" )
    parser.add_argument( "--clear-target", action="store_true",
                        help="Clear existing target table before migration" )
    parser.add_argument( "--debug", action="store_true", help="Enable debug output" )

    args = parser.parse_args()

    print( "🚀 Complete Solution Snapshot Migration Utility" )
    print( f"   Source: {args.source}" )
    print( f"   Target: {args.target_db}/{args.target_table}" )
    print( f"   Clear target: {'Yes' if args.clear_target else 'No'}" )
    print( f"   Debug: {'enabled' if args.debug else 'disabled'}" )

    # Run migration
    results = migrate_all_snapshots(
        source_path=args.source,
        target_db_path=args.target_db,
        target_table=args.target_table,
        clear_target=args.clear_target,
        debug=args.debug
    )

    # Print summary
    print( "\n🎯 Migration Summary:" )
    if "summary" in results:
        summary = results["summary"]
        print( f"   • Success: {summary.get( 'success', False )}" )
        print( f"   • Snapshots migrated: {summary.get( 'snapshots_migrated', 0 )}" )
        print( f"   • Migration time: {summary.get( 'migration_time_ms', 0 ):.1f}ms" )
        print( f"   • Completion rate: {summary.get( 'completion_rate', 0 ):.1%}" )
        print( f"   • Validation passed: {summary.get( 'validation_passed', False )}" )
        print( f"   • Source-target match: {summary.get( 'source_target_match', False )}" )
        print( f"   • Errors: {summary.get( 'error_count', 0 )}" )

    return 0 if results.get( "summary", {} ).get( "success", False ) else 1


if __name__ == "__main__":
    exit( main() )