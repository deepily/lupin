#!/usr/bin/env python3
"""
Agent Architecture Tests: v010 Agents

Tests all v010 agent implementations including functionality validation,
dependency scanning, and comprehensive smoke test execution with enhanced
reporting for v000 deprecation tracking.
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


def test_v010_agent_modules():
    """
    Test all v010 agent modules for functionality and smoke tests.
    
    Ensures:
        - All v010 agents can be imported
        - Smoke tests execute successfully where available
        - No v000 dependencies in v010 agents
        - Agent architecture integrity is maintained
        
    Returns:
        List[Dict]: Results for each v010 agent module tested
    """
    v010_agents = [
        ("math_agent", "cosa.agents.math_agent"),
        ("calendaring_agent", "cosa.agents.calendaring_agent"),
        ("weather_agent", "cosa.agents.weather_agent"),
        ("todo_list_agent", "cosa.agents.todo_list_agent"),
        ("receptionist_agent", "cosa.agents.receptionist_agent"),
        ("bug_injector", "cosa.agents.bug_injector"),
        ("confirmation_dialog", "cosa.agents.confirmation_dialog"),
        ("date_and_time_agent", "cosa.agents.date_and_time_agent"),
        ("gister", "cosa.agents.gister"),
        ("iterative_debugging_agent", "cosa.agents.iterative_debugging_agent"),
    ]
    
    results = []
    
    for agent_name, module_path in v010_agents:
        import time
        start_time = time.time()
        
        try:
            # Try to import the agent module
            module = __import__(module_path, fromlist=[''])
            
            # Check if it has a smoke test
            if hasattr(module, 'quick_smoke_test'):
                # Execute smoke test with output capture to avoid noise
                import io
                import contextlib
                
                output_buffer = io.StringIO()
                error_buffer = io.StringIO()
                
                with contextlib.redirect_stdout(output_buffer):
                    with contextlib.redirect_stderr(error_buffer):
                        module.quick_smoke_test()
                
                # Check for any critical errors in captured output
                error_output = error_buffer.getvalue()
                if "✗" in error_output or "Error" in error_output:
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
            "agent": agent_name,
            "module_path": module_path,
            "success": success,
            "duration": duration,
            "error": error
        })
    
    return results


def test_agent_infrastructure():
    """
    Test v010 agent infrastructure components.
    
    Ensures:
        - Core agent infrastructure is functional
        - LLM clients and factories work correctly
        - Formatters and utilities are operational
        
    Returns:
        List[Dict]: Results for each infrastructure component tested
    """
    infrastructure_modules = [
        ("agent_base", "cosa.agents.agent_base"),
        ("llm_client", "cosa.agents.llm_client"),
        ("llm_client_factory", "cosa.agents.llm_client_factory"),
        ("llm_completion", "cosa.agents.llm_completion"),
        ("prompt_formatter", "cosa.agents.prompt_formatter"),
        ("raw_output_formatter", "cosa.agents.raw_output_formatter"),
        ("runnable_code", "cosa.agents.runnable_code"),
        ("token_counter", "cosa.agents.token_counter"),
        ("two_word_id_generator", "cosa.agents.two_word_id_generator"),
    ]
    
    results = []
    
    for component_name, module_path in infrastructure_modules:
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
                # Module exists but no smoke test - still consider success
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
            "component": component_name,
            "module_path": module_path,
            "success": success,
            "duration": duration,
            "error": error
        })
    
    return results


def scan_v000_dependencies_in_agents():
    """
    Scan v010 agent modules for any remaining v000 dependencies.
    
    This is critical for v000 deprecation - v010 agents should be completely
    free of v000 dependencies.
    
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
    
    # All v010 modules to scan
    all_v010_modules = [
        "cosa.agents.math_agent",
        "cosa.agents.calendaring_agent",
        "cosa.agents.weather_agent", 
        "cosa.agents.todo_list_agent",
        "cosa.agents.receptionist_agent",
        "cosa.agents.bug_injector",
        "cosa.agents.confirmation_dialog",
        "cosa.agents.date_and_time_agent",
        "cosa.agents.gister",
        "cosa.agents.iterative_debugging_agent",
        "cosa.agents.agent_base",
        "cosa.agents.llm_client",
        "cosa.agents.llm_client_factory",
        "cosa.agents.llm_completion",
        "cosa.agents.prompt_formatter",
        "cosa.agents.raw_output_formatter",
        "cosa.agents.runnable_code",
        "cosa.agents.token_counter",
        "cosa.agents.two_word_id_generator"
    ]
    
    for module_name in all_v010_modules:
        dependencies["modules_scanned"] += 1
        
        try:
            # Try to get the module for file scanning
            try:
                module = __import__(module_name, fromlist=[''])
                if hasattr(module, '__file__') and module.__file__:
                    with open(module.__file__, 'r') as f:
                        content = f.read()
                    
                    # Check for v000 patterns - these should NOT exist in v010
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
    """Enhanced smoke test for v010 agent architecture."""
    utils = SmokeTestUtilities()
    utils.print_banner("v010 Agent Architecture Tests", prepend_nl=True)
    
    print("  Testing v010 Agent Modules...")
    agent_results = test_v010_agent_modules()
    
    print("  Testing Agent Infrastructure...")
    infrastructure_results = test_agent_infrastructure()
    
    # Combine all results
    all_results = agent_results + infrastructure_results
    
    # Print detailed results
    print("\n  📊 Detailed Results:")
    print("    v010 Agents:")
    for result in agent_results:
        status = "✓" if result["success"] else "✗"
        duration_str = utils.format_duration(result["duration"])
        print(f"      {status} {result['agent']:25} {duration_str:>8}")
        if not result["success"] and result["error"]:
            print(f"        Error: {result['error']}")
    
    print("    Infrastructure:")
    for result in infrastructure_results:
        status = "✓" if result["success"] else "✗"
        duration_str = utils.format_duration(result["duration"])
        print(f"      {status} {result['component']:25} {duration_str:>8}")
        if not result["success"] and result["error"]:
            print(f"        Error: {result['error']}")
    
    # Critical v000 dependency analysis
    print("\n  🔍 Critical: Scanning v010 agents for v000 dependencies...")
    dependency_analysis = scan_v000_dependencies_in_agents()
    
    print(f"  📊 Modules scanned: {dependency_analysis['modules_scanned']}")
    print(f"  ✅ Clean modules: {len(dependency_analysis['clean_modules'])}")
    print(f"  ❌ Import errors: {len(dependency_analysis['import_errors'])}")
    print(f"  🚨 v000 dependencies: {len(dependency_analysis['v000_dependencies'])}")
    
    # This is critical - v010 should have ZERO v000 dependencies
    if dependency_analysis['v000_dependencies']:
        print("  🚨 CRITICAL: v000 dependencies found in v010 agents!")
        for dep in dependency_analysis['v000_dependencies']:
            print(f"      • {dep['module']}: {', '.join(dep['patterns'])}")
        print("  ⚠️  These dependencies must be eliminated before v000 deprecation")
    else:
        print("  ✅ EXCELLENT: No v000 dependencies found in v010 agents!")
    
    # Show import errors for debugging
    if dependency_analysis['import_errors']:
        print("\n  ⚠️  Import/Analysis Errors:")
        for error in dependency_analysis['import_errors'][:5]:  # Show first 5
            print(f"      • {error['module']}: {error['error']}")
        if len(dependency_analysis['import_errors']) > 5:
            print(f"      ... and {len(dependency_analysis['import_errors']) - 5} more")
    
    # Summary statistics
    total_tests = len(all_results)
    passed_tests = sum(1 for r in all_results if r["success"])
    total_duration = sum(r["duration"] for r in all_results)
    success_rate = (passed_tests / total_tests * 100) if total_tests > 0 else 0
    
    print(f"\n  ✅ v010 Agent Results: {passed_tests}/{total_tests} passed ({success_rate:.1f}%) in {utils.format_duration(total_duration)}")
    
    # Agent-specific success rates
    agent_success_rate = (sum(1 for r in agent_results if r["success"]) / len(agent_results) * 100) if agent_results else 0
    infra_success_rate = (sum(1 for r in infrastructure_results if r["success"]) / len(infrastructure_results) * 100) if infrastructure_results else 0
    
    print(f"  📈 Agent Success Rate: {agent_success_rate:.1f}%")
    print(f"  📈 Infrastructure Success Rate: {infra_success_rate:.1f}%")
    
    # Status determination with v000 dependency consideration
    if dependency_analysis['v000_dependencies']:
        print("  🚨 CRITICAL ISSUE: v000 dependencies found - migration incomplete!")
        print("  ⚠️  Must eliminate v000 dependencies before proceeding with deprecation")
    elif success_rate == 100:
        print("  🎉 All v010 agents working perfectly!")
    elif success_rate >= 80:
        print("  ✅ v010 agent architecture mostly functional - minor issues detected")
    elif success_rate >= 50:
        print("  ⚠️  v010 agent architecture partially functional - review failures")
    else:
        print("  ❌ v010 agent architecture has significant issues - check dependencies")
    
    # Specific guidance
    if agent_success_rate < 50:
        print("  💡 Tip: Agent failures often indicate missing LLM client configuration")
    if infra_success_rate < 50:
        print("  💡 Tip: Infrastructure failures may indicate missing core dependencies")


if __name__ == "__main__":
    quick_smoke_test()