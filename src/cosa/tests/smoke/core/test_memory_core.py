#!/usr/bin/env python3
"""
Core Framework Tests: Memory System

Tests the CoSA memory system components including embeddings, snapshots,
and normalization with enhanced reporting and v000 dependency scanning.
"""

import os
import sys
from pathlib import Path

try:
    from cosa.tests.smoke.infrastructure.test_utilities import SmokeTestUtilities
except ImportError:
    # Fallback for development
    class SmokeTestUtilities:
        @staticmethod
        def print_banner(message, prepend_nl=False):
            if prepend_nl:
                print()
            print("=" * 60)
            print(f" {message}")
            print("=" * 60)
        
        @staticmethod
        def format_duration(seconds):
            return f"{seconds:.2f}s"


def test_memory_modules():
    """
    Test CoSA memory system modules.
    
    Ensures:
        - Memory modules can be imported
        - Smoke tests execute without critical errors
        - v000 dependencies are identified
        
    Returns:
        List[Dict]: Results for each memory module tested
    """
    memory_modules = [
        ("solution_snapshot", "cosa.memory.solution_snapshot"),
        ("solution_snapshot_mgr", "cosa.memory.solution_snapshot_mgr"),
        ("normalizer", "cosa.memory.normalizer"),
        ("gist_normalizer", "cosa.memory.gist_normalizer"),
        ("embedding_manager", "cosa.memory.embedding_manager"),
        ("embedding_cache_table", "cosa.memory.embedding_cache_table"),
        ("input_and_output_table", "cosa.memory.input_and_output_table")
    ]
    
    results = []
    
    for module_name, module_path in memory_modules:
        import time
        start_time = time.time()
        
        try:
            # Try to import the module
            module = __import__(module_path, fromlist=[''])
            
            # Check if it has a smoke test
            if hasattr(module, 'quick_smoke_test'):
                # Execute smoke test with output capture
                import io
                import contextlib
                
                output_buffer = io.StringIO()
                error_buffer = io.StringIO()
                
                with contextlib.redirect_stdout(output_buffer):
                    with contextlib.redirect_stderr(error_buffer):
                        module.quick_smoke_test()
                
                success = True
                error = ""
            else:
                # Module exists but no smoke test
                success = True
                error = "No smoke test available"
            
            duration = time.time() - start_time
            
        except ImportError as e:
            duration = time.time() - start_time
            success = False
            error = f"ImportError: {str(e)}"
            
        except Exception as e:
            duration = time.time() - start_time
            success = False
            error = f"{type(e).__name__}: {str(e)}"
        
        results.append({
            "module": module_name,
            "module_path": module_path,
            "success": success,
            "duration": duration,
            "error": error
        })
    
    return results


def test_cli_system():
    """
    Test CoSA CLI and notification system.
    
    Ensures:
        - CLI modules can be imported
        - Notification system is functional
        - No critical v000 dependencies
        
    Returns:
        List[Dict]: Results for each CLI module tested
    """
    cli_modules = [
        ("notify_user", "cosa.cli.notify_user"),
        ("test_notifications", "cosa.cli.test_notifications")
    ]
    
    results = []
    
    for module_name, module_path in cli_modules:
        import time
        start_time = time.time()
        
        try:
            # Try to import the module
            module = __import__(module_path, fromlist=[''])
            
            # For notification modules, just test import - don't run actual notifications
            if module_name == "notify_user":
                # Test basic function availability
                if hasattr(module, 'notify_user') and hasattr(module, 'validate_environment'):
                    success = True
                    error = ""
                else:
                    success = False
                    error = "Required functions not found"
            elif hasattr(module, 'quick_smoke_test'):
                # Execute smoke test with output capture for other modules
                import io
                import contextlib
                
                output_buffer = io.StringIO()
                with contextlib.redirect_stdout(output_buffer):
                    with contextlib.redirect_stderr(output_buffer):
                        module.quick_smoke_test()
                
                success = True
                error = ""
            else:
                success = True
                error = "Import successful, no smoke test"
            
            duration = time.time() - start_time
            
        except ImportError as e:
            duration = time.time() - start_time
            success = False
            error = f"ImportError: {str(e)}"
            
        except Exception as e:
            duration = time.time() - start_time
            success = False  
            error = f"{type(e).__name__}: {str(e)}"
        
        results.append({
            "module": module_name,
            "module_path": module_path,
            "success": success,
            "duration": duration,
            "error": error
        })
    
    return results


def scan_v000_dependencies_in_memory():
    """
    Scan memory and CLI modules for v000 dependencies.
    
    Returns:
        Dict[str, Any]: Dependency analysis results
    """
    dependencies = {
        "modules_scanned": 0,
        "v000_dependencies": [],
        "legacy_patterns": [],
        "clean_modules": []
    }
    
    # All modules we want to scan
    all_modules = [
        "cosa.memory.solution_snapshot",
        "cosa.memory.solution_snapshot_mgr", 
        "cosa.memory.normalizer",
        "cosa.memory.gist_normalizer",
        "cosa.memory.embedding_manager",
        "cosa.memory.embedding_cache_table",
        "cosa.memory.input_and_output_table",
        "cosa.cli.notify_user",
        "cosa.cli.test_notifications"
    ]
    
    for module_name in all_modules:
        dependencies["modules_scanned"] += 1
        
        try:
            # Try to get the module file for scanning
            try:
                module = __import__(module_name, fromlist=[''])
                if hasattr(module, '__file__') and module.__file__:
                    with open(module.__file__, 'r') as f:
                        content = f.read()
                    
                    # Check for v000 patterns
                    v000_patterns = ["v000", "agents.v000", "from cosa.agents.v000"]
                    found_v000 = False
                    
                    for pattern in v000_patterns:
                        if pattern in content:
                            dependencies["v000_dependencies"].append({
                                "module": module_name,
                                "pattern": pattern
                            })
                            found_v000 = True
                    
                    if not found_v000:
                        dependencies["clean_modules"].append(module_name)
                        
            except ImportError:
                # Module not available - skip
                dependencies["modules_scanned"] -= 1
                
        except Exception:
            # Skip modules that can't be analyzed
            pass
    
    return dependencies


def quick_smoke_test():
    """Enhanced smoke test for memory system and CLI components."""
    utils = SmokeTestUtilities()
    utils.print_banner("Memory System & CLI Tests", prepend_nl=True)
    
    print("  Testing Memory System Components...")
    memory_results = test_memory_modules()
    
    print("  Testing CLI System Components...")
    cli_results = test_cli_system()
    
    # Combine all results
    all_results = memory_results + cli_results
    
    # Print detailed results
    print("\n  📊 Detailed Results:")
    for result in all_results:
        status = "✓" if result["success"] else "✗"
        duration_str = utils.format_duration(result["duration"])
        print(f"    {status} {result['module']:25} {duration_str:>8}")
        if not result["success"] and result["error"]:
            print(f"      Error: {result['error']}")
    
    # v000 dependency analysis
    print("\n  🔍 Scanning for v000 dependencies...")
    dependency_analysis = scan_v000_dependencies_in_memory()
    
    print(f"  📊 Modules scanned: {dependency_analysis['modules_scanned']}")
    print(f"  ✅ Clean modules: {len(dependency_analysis['clean_modules'])}")
    print(f"  ⚠️  v000 dependencies: {len(dependency_analysis['v000_dependencies'])}")
    
    if dependency_analysis['v000_dependencies']:
        for dep in dependency_analysis['v000_dependencies']:
            print(f"      • {dep['module']}: {dep['pattern']}")
    
    # Summary statistics
    total_tests = len(all_results)
    passed_tests = sum(1 for r in all_results if r["success"])
    total_duration = sum(r["duration"] for r in all_results)
    success_rate = (passed_tests / total_tests * 100) if total_tests > 0 else 0
    
    print(f"\n  ✅ Memory & CLI Results: {passed_tests}/{total_tests} passed ({success_rate:.1f}%) in {utils.format_duration(total_duration)}")
    
    # Status determination
    if success_rate == 100:
        print("  🎉 All memory and CLI components working perfectly!")
    elif success_rate >= 80:
        print("  ✅ Memory and CLI systems mostly functional - minor issues detected")
    elif success_rate >= 50:
        print("  ⚠️  Memory and CLI systems partially functional - review failures")
    else:
        print("  ❌ Memory and CLI systems have significant issues - check dependencies")
    
    # Specific guidance for memory system
    memory_success_rate = (sum(1 for r in memory_results if r["success"]) / len(memory_results) * 100) if memory_results else 0
    if memory_success_rate < 50:
        print("  💡 Tip: Memory failures often indicate missing LanceDB or embedding dependencies")


if __name__ == "__main__":
    quick_smoke_test()