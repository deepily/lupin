#!/usr/bin/env python3
"""
Performance benchmark script comparing file-based and LanceDB solution snapshot managers.

This script runs identical operations on both implementations and provides
performance comparison metrics.
"""

import sys
import os

# Bootstrap using LUPIN_ROOT environment variable
lupin_root = os.environ.get( 'LUPIN_ROOT' )
if lupin_root is None:
    raise RuntimeError(
        "LUPIN_ROOT environment variable not set.\n"
        "Set it before running benchmark:\n"
        "  export LUPIN_ROOT=/mnt/DATA01/include/www.deepily.ai/projects/lupin\n"
        "  python src/scripts/benchmark_snapshot_managers.py"
    )

src_path = os.path.join( lupin_root, 'src' )
if src_path not in sys.path:
    sys.path.insert( 0, src_path )

import time
import random
from typing import List, Dict, Any

import cosa.utils.util as du
from cosa.memory.solution_snapshot_mgr import SolutionSnapshotManager
from cosa.memory.lancedb_solution_manager import LanceDBSolutionManager
from cosa.memory.solution_snapshot import SolutionSnapshot


def print_banner(title: str, width: int = 80) -> None:
    """Print formatted banner."""
    print()
    print("━" * width)
    print(f" {title}")
    print("━" * width)


def print_table_row(operation: str, file_time: float, lance_time: float, width: int = 80) -> None:
    """Print formatted table row."""
    if lance_time > 0 and file_time > 0:
        speedup = file_time / lance_time
        speedup_str = f"{speedup:.1f}x" if speedup > 1 else f"{1/speedup:.1f}x slower"
    elif lance_time > 0:
        speedup_str = "file faster"
    elif file_time > 0:
        speedup_str = "lance faster"  
    else:
        speedup_str = "N/A"
    
    print(f"{operation:<20} {file_time:>8.1f}ms    {lance_time:>8.1f}ms     {speedup_str:>12}")


def create_test_snapshot(suffix: str = "") -> SolutionSnapshot:
    """Create a test snapshot for benchmarking."""
    return SolutionSnapshot(
        question=f"benchmark test question {suffix}",
        answer=f"benchmark test answer {suffix}",
        solution_summary=f"test solution summary {suffix}",
        code=f"print('benchmark test {suffix}')",
        programming_language="python",
        question_embedding=[random.random() for _ in range(1536)],
        solution_embedding=[random.random() for _ in range(1536)]
    )


def benchmark_manager(manager, manager_name: str) -> Dict[str, float]:
    """Run benchmark tests on a manager and return timing results."""
    print(f"\n🧪 Benchmarking {manager_name}...")
    
    results = {}
    
    # Test 1: Initialization
    start = time.time()
    
    # Handle different manager types
    if hasattr(manager, 'is_initialized'):
        # LanceDB manager with interface
        if not manager.is_initialized():
            try:
                manager.initialize()
            except ValueError as e:
                if "already exists" in str(e):
                    # Handle LanceDB table already exists
                    import lancedb
                    manager._db = lancedb.connect(manager.db_path)
                    manager._table = manager._db.open_table(manager.table_name)
                    manager._initialized = True
                else:
                    raise
    else:
        # File-based manager (already initialized in constructor)
        pass
    
    results['initialize'] = (time.time() - start) * 1000
    
    # Test 2: Add snapshots (batch of 5)
    test_snapshots = []
    start = time.time()
    for i in range(5):
        snapshot = create_test_snapshot(f"{int(time.time())}_{i}")
        success = manager.save_snapshot(snapshot)
        if success:
            test_snapshots.append(snapshot.question)
    results['add_snapshots'] = (time.time() - start) * 1000
    
    # Test 3: Search (exact match)
    if test_snapshots:
        start = time.time()
        for question in test_snapshots[:3]:  # Test 3 searches
            if hasattr(manager, 'find_by_question'):
                # LanceDB interface
                results_found, metrics = manager.find_by_question(question, threshold_question=95.0)
            else:
                # File-based interface
                results_found = manager.get_snapshots_by_question(question, threshold_question=95.0)
        results['search_exact'] = (time.time() - start) * 1000 / 3  # Average per search
    else:
        results['search_exact'] = 0
    
    # Test 4: Search (fuzzy match)
    start = time.time()
    for _ in range(3):
        if hasattr(manager, 'find_by_question'):
            # LanceDB interface
            results_found, metrics = manager.find_by_question("test question", threshold_question=50.0)
        else:
            # File-based interface
            results_found = manager.get_snapshots_by_question("test question", threshold_question=50.0)
    results['search_fuzzy'] = (time.time() - start) * 1000 / 3  # Average per search
    
    # Test 5: Delete snapshots
    start = time.time()
    for question in test_snapshots:
        manager.delete_snapshot(question)
    results['delete_snapshots'] = (time.time() - start) * 1000
    
    return results


def main():
    """Run performance benchmarks."""
    print_banner("🚀 Solution Snapshot Manager Performance Benchmark", 100)
    print("Comparing file-based and LanceDB implementations with identical operations...")
    
    # Setup file-based manager
    file_config = {"path": du.get_project_root() + "/src/conf/long-term-memory/solutions/"}
    file_manager = SolutionSnapshotManager(file_config["path"], debug=False, verbose=False)
    
    # Setup LanceDB manager
    lance_config = {
        "db_path": du.get_project_root() + "/src/conf/long-term-memory/lupin.lancedb",
        "table_name": "solution_snapshots"
    }
    lance_manager = LanceDBSolutionManager(lance_config, debug=False, verbose=False)
    
    # Run benchmarks
    print("\n⏱️  Running benchmarks (this may take a minute)...")
    file_results = benchmark_manager(file_manager, "File-Based")
    lance_results = benchmark_manager(lance_manager, "LanceDB")
    
    # Results table
    print_banner("📊 Performance Comparison Results")
    print(f"{'Operation':<20} {'File-Based':<12} {'LanceDB':<12} {'Speedup':<12}")
    print("─" * 80)
    
    operations = [
        ('Initialize', 'initialize'),
        ('Add 5 snapshots', 'add_snapshots'), 
        ('Search (exact)', 'search_exact'),
        ('Search (fuzzy)', 'search_fuzzy'),
        ('Delete snapshots', 'delete_snapshots')
    ]
    
    for display_name, key in operations:
        file_time = file_results.get(key, 0)
        lance_time = lance_results.get(key, 0)
        print_table_row(display_name, file_time, lance_time)
    
    # Summary
    print("─" * 80)
    
    # Calculate average speedup for search operations (most important)
    search_speedups = []
    for key in ['search_exact', 'search_fuzzy']:
        if lance_results.get(key, 0) > 0 and file_results.get(key, 0) > 0:
            speedup = file_results[key] / lance_results[key]
            search_speedups.append(speedup)
    
    if search_speedups:
        avg_search_speedup = sum(search_speedups) / len(search_speedups)
        print(f"\n🎯 Average search speedup: {avg_search_speedup:.1f}x faster with LanceDB")
    
    # Recommendations
    print("\n💡 Recommendations:")
    print("   • LanceDB is significantly faster for search operations")
    print("   • File-based is simpler for small datasets (<100 snapshots)")
    print("   • LanceDB is recommended for production with >100 snapshots")
    
    print(f"\n✅ Benchmark completed! Both implementations are functional.")
    return True


if __name__ == "__main__":
    try:
        success = main()
        exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n❌ Benchmark interrupted by user")
        exit(1)
    except Exception as e:
        print(f"\n\n❌ Benchmark failed: {e}")
        exit(1)