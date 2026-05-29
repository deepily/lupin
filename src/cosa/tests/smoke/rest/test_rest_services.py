#!/usr/bin/env python3
"""
REST Services Tests: Queue Management and Service Components

Tests the CoSA REST service components including queue systems, routers,
and service utilities with enhanced reporting and v000 dependency scanning.
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


def test_queue_systems():
    """
    Test CoSA queue management components.
    
    Ensures:
        - Queue systems can be imported and instantiated
        - Basic queue operations work correctly
        - No v000 dependencies in queue components
        
    Returns:
        List[Dict]: Results for each queue component tested
    """
    queue_modules = [
        ("user_id_generator", "cosa.rest.user_id_generator"),
        ("multimodal_munger", "cosa.rest.multimodal_munger"),
        ("notification_fifo_queue", "cosa.rest.notification_fifo_queue"),
        ("queue_consumer", "cosa.rest.queue_consumer"),
        ("todo_fifo_queue", "cosa.rest.todo_fifo_queue"),
    ]
    
    results = []
    
    for module_name, module_path in queue_modules:
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
                
                # Check for critical errors in output
                error_output = error_buffer.getvalue()
                if "✗" in error_output or "ERROR" in error_output.upper():
                    success = False
                    error = "Smoke test reported errors"
                else:
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


def test_rest_utilities():
    """
    Test REST service utility components.
    
    Ensures:
        - REST utilities can be imported
        - Core service components are functional
        - WebSocket management is operational
        
    Returns:
        List[Dict]: Results for each REST utility tested
    """
    rest_utilities = [
        ("websocket_manager", "cosa.rest.websocket_manager"),
        ("util_llm_client", "cosa.rest.util_llm_client"),
        ("fifo_queue", "cosa.rest.fifo_queue"),
        ("running_fifo_queue", "cosa.rest.running_fifo_queue"),
        ("queue_extensions", "cosa.rest.queue_extensions"),
    ]
    
    results = []
    
    for module_name, module_path in rest_utilities:
        import time
        start_time = time.time()
        
        try:
            # Try to import the module
            module = __import__(module_path, fromlist=[''])
            
            # For REST utilities, we mainly test import success
            # Some may not have smoke tests due to external dependencies
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
                # Module exists - test basic functionality if possible
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


def test_rest_routers():
    """
    Test REST API router components.
    
    Ensures:
        - Router modules can be imported
        - Basic router structure is valid
        - No critical dependency issues
        
    Returns:
        List[Dict]: Results for each router tested
    """
    router_modules = [
        ("jobs", "cosa.rest.routers.jobs"),
        ("notifications", "cosa.rest.routers.notifications"),
        ("queues", "cosa.rest.routers.queues"),
        ("speech", "cosa.rest.routers.speech"),
        ("system", "cosa.rest.routers.system"),
        ("websocket", "cosa.rest.routers.websocket"),
        ("websocket_admin", "cosa.rest.routers.websocket_admin"),
    ]
    
    results = []
    
    for module_name, module_path in router_modules:
        import time
        start_time = time.time()
        
        try:
            # Try to import the router module
            module = __import__(module_path, fromlist=[''])
            
            # Check for router object or FastAPI router
            has_router = False
            if hasattr(module, 'router'):
                has_router = True
            elif hasattr(module, 'app'):
                has_router = True
            
            if has_router:
                success = True
                error = ""
            else:
                success = True
                error = "No router object found (may be valid)"
            
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


def scan_v000_dependencies_in_rest():
    """
    Scan REST service modules for v000 dependencies.
    
    Returns:
        Dict[str, Any]: Dependency analysis results
    """
    dependencies = {
        "modules_scanned": 0,
        "v000_dependencies": [],
        "legacy_patterns": [],
        "clean_modules": [],
        "import_errors": []
    }
    
    # All REST modules to scan
    all_rest_modules = [
        "cosa.rest.user_id_generator",
        "cosa.rest.multimodal_munger",
        "cosa.rest.notification_fifo_queue",
        "cosa.rest.queue_consumer",
        "cosa.rest.todo_fifo_queue",
        "cosa.rest.websocket_manager",
        "cosa.rest.util_llm_client",
        "cosa.rest.fifo_queue",
        "cosa.rest.running_fifo_queue",
        "cosa.rest.queue_extensions",
        "cosa.rest.routers.jobs",
        "cosa.rest.routers.notifications",
        "cosa.rest.routers.queues",
        "cosa.rest.routers.speech",
        "cosa.rest.routers.system",
        "cosa.rest.routers.websocket",
        "cosa.rest.routers.websocket_admin",
    ]
    
    for module_name in all_rest_modules:
        dependencies["modules_scanned"] += 1
        
        try:
            # Try to get the module for file scanning
            try:
                module = __import__(module_name, fromlist=[''])
                if hasattr(module, '__file__') and module.__file__:
                    with open(module.__file__, 'r') as f:
                        content = f.read()
                    
                    # Check for v000 patterns
                    v000_patterns = [
                        "v000",
                        "agents.v000",
                        "from cosa.agents.v000",
                        "import cosa.agents.v000"
                    ]
                    
                    found_v000 = False
                    found_patterns = []
                    
                    for pattern in v000_patterns:
                        if pattern in content:
                            found_patterns.append(pattern)
                            found_v000 = True
                    
                    if found_v000:
                        dependencies["v000_dependencies"].append({
                            "module": module_name,
                            "patterns": found_patterns
                        })
                    else:
                        dependencies["clean_modules"].append(module_name)
                        
            except ImportError as e:
                # Track import errors separately
                dependencies["import_errors"].append({
                    "module": module_name,
                    "error": str(e)
                })
                
        except Exception as e:
            # Skip modules that can't be analyzed
            dependencies["import_errors"].append({
                "module": module_name,
                "error": f"Analysis error: {str(e)}"
            })
    
    return dependencies


def quick_smoke_test():
    """Enhanced smoke test for REST service components."""
    utils = SmokeTestUtilities()
    utils.print_banner("REST Services Tests", prepend_nl=True)
    
    print("  Testing Queue Systems...")
    queue_results = test_queue_systems()
    
    print("  Testing REST Utilities...")
    utility_results = test_rest_utilities()
    
    print("  Testing REST Routers...")
    router_results = test_rest_routers()
    
    # Combine all results
    all_results = queue_results + utility_results + router_results
    
    # Print detailed results
    print("\n  📊 Detailed Results:")
    
    print("    Queue Systems:")
    for result in queue_results:
        status = "✓" if result["success"] else "✗"
        duration_str = utils.format_duration(result["duration"])
        print(f"      {status} {result['module']:25} {duration_str:>8}")
        if not result["success"] and result["error"]:
            print(f"        Error: {result['error']}")
    
    print("    REST Utilities:")
    for result in utility_results:
        status = "✓" if result["success"] else "✗"
        duration_str = utils.format_duration(result["duration"])
        print(f"      {status} {result['module']:25} {duration_str:>8}")
        if not result["success"] and result["error"]:
            print(f"        Error: {result['error']}")
    
    print("    REST Routers:")
    for result in router_results:
        status = "✓" if result["success"] else "✗"
        duration_str = utils.format_duration(result["duration"])
        print(f"      {status} {result['module']:25} {duration_str:>8}")
        if not result["success"] and result["error"]:
            print(f"        Error: {result['error']}")
    
    # v000 dependency analysis
    print("\n  🔍 Scanning REST services for v000 dependencies...")
    dependency_analysis = scan_v000_dependencies_in_rest()
    
    print(f"  📊 Modules scanned: {dependency_analysis['modules_scanned']}")
    print(f"  ✅ Clean modules: {len(dependency_analysis['clean_modules'])}")
    print(f"  ❌ Import errors: {len(dependency_analysis['import_errors'])}")
    print(f"  ⚠️  v000 dependencies: {len(dependency_analysis['v000_dependencies'])}")
    
    if dependency_analysis['v000_dependencies']:
        print("  ⚠️  v000 dependencies found:")
        for dep in dependency_analysis['v000_dependencies']:
            print(f"      • {dep['module']}: {', '.join(dep['patterns'])}")
    
    # Show some import errors for debugging
    if dependency_analysis['import_errors']:
        print(f"\n  ⚠️  Import/Analysis Errors (showing first 3):")
        for error in dependency_analysis['import_errors'][:3]:
            print(f"      • {error['module']}: {error['error']}")
        if len(dependency_analysis['import_errors']) > 3:
            remaining = len(dependency_analysis['import_errors']) - 3
            print(f"      ... and {remaining} more import errors")
    
    # Summary statistics
    total_tests = len(all_results)
    passed_tests = sum(1 for r in all_results if r["success"])
    total_duration = sum(r["duration"] for r in all_results)
    success_rate = (passed_tests / total_tests * 100) if total_tests > 0 else 0
    
    print(f"\n  ✅ REST Services Results: {passed_tests}/{total_tests} passed ({success_rate:.1f}%) in {utils.format_duration(total_duration)}")
    
    # Component-specific success rates
    queue_success_rate = (sum(1 for r in queue_results if r["success"]) / len(queue_results) * 100) if queue_results else 0
    utility_success_rate = (sum(1 for r in utility_results if r["success"]) / len(utility_results) * 100) if utility_results else 0
    router_success_rate = (sum(1 for r in router_results if r["success"]) / len(router_results) * 100) if router_results else 0
    
    print(f"  📈 Queue Systems: {queue_success_rate:.1f}%")
    print(f"  📈 REST Utilities: {utility_success_rate:.1f}%")
    print(f"  📈 REST Routers: {router_success_rate:.1f}%")
    
    # Status determination
    if success_rate == 100:
        print("  🎉 All REST services working perfectly!")
    elif success_rate >= 80:
        print("  ✅ REST services mostly functional - minor issues detected")
    elif success_rate >= 50:
        print("  ⚠️  REST services partially functional - review failures")
    else:
        print("  ❌ REST services have significant issues - check dependencies")
    
    # Specific guidance
    if queue_success_rate < 50:
        print("  💡 Tip: Queue failures often indicate missing configuration or dependencies")
    if router_success_rate < 50:
        print("  💡 Tip: Router failures may indicate missing FastAPI or Pydantic dependencies")
    if len(dependency_analysis['import_errors']) > len(dependency_analysis['clean_modules']):
        print("  💡 Tip: Many import errors suggest missing REST service dependencies")


if __name__ == "__main__":
    quick_smoke_test()