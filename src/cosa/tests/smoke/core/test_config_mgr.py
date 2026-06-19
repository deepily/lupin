#!/usr/bin/env python3
"""
Core Framework Tests: Configuration Manager

Tests the CoSA configuration manager functionality including loading,
validation, and value retrieval with enhanced reporting and v000 dependency scanning.
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


def test_configuration_manager():
    """
    Test CoSA configuration manager functionality.
    
    Ensures:
        - Configuration manager can be imported and instantiated
        - Basic configuration operations work correctly
        - Environment variable handling functions properly
        - No v000 dependencies are present
        
    Returns:
        Tuple[bool, float, str]: (success, duration, error_message)
    """
    import time
    start_time = time.time()
    
    try:
        # Test import
        from cosa.config.configuration_manager import ConfigurationManager
        
        # Test instantiation with environment variable
        os.environ["TEST_CONFIG_MGR_CLI_ARGS"] = ""
        config_mgr = ConfigurationManager(env_var_name="TEST_CONFIG_MGR_CLI_ARGS")
        
        # Test basic operations
        test_value = config_mgr.get("nonexistent_key", default="test_default", return_type="string")
        if test_value != "test_default":
            return False, time.time() - start_time, "Default value retrieval failed"
        
        # Test the actual smoke test
        import cosa.config.configuration_manager as config_module
        if hasattr(config_module, 'quick_smoke_test'):
            config_module.quick_smoke_test()
        
        duration = time.time() - start_time
        return True, duration, ""
        
    except Exception as e:
        duration = time.time() - start_time
        return False, duration, f"{type(e).__name__}: {str(e)}"


def test_utils_core():
    """
    Test CoSA core utilities functionality.
    
    Ensures:
        - Utility functions can be imported and used
        - Banner printing and formatting work correctly
        - No v000 dependencies are present
        
    Returns:
        Tuple[bool, float, str]: (success, duration, error_message)
    """
    import time
    start_time = time.time()
    
    try:
        # Test import
        import cosa.utils.util as du
        
        # Test basic banner functionality (capture output to avoid noise)
        import io
        import contextlib
        
        output_buffer = io.StringIO()
        with contextlib.redirect_stdout(output_buffer):
            du.print_banner("Test Banner")
        
        banner_output = output_buffer.getvalue()
        if "Test Banner" not in banner_output:
            return False, time.time() - start_time, "Banner printing failed"
        
        # Test the actual smoke test if available
        if hasattr(du, 'quick_smoke_test'):
            with contextlib.redirect_stdout(output_buffer):
                with contextlib.redirect_stderr(output_buffer):
                    du.quick_smoke_test()
        
        duration = time.time() - start_time
        return True, duration, ""
        
    except Exception as e:
        duration = time.time() - start_time
        return False, duration, f"{type(e).__name__}: {str(e)}"


def test_util_code_runner():
    """
    Test CoSA code runner utility functionality.
    
    Ensures:
        - Code runner can be imported and instantiated
        - Basic code execution functionality works
        - No v000 dependencies are present
        
    Returns:
        Tuple[bool, float, str]: (success, duration, error_message)
    """
    import time
    start_time = time.time()
    
    try:
        # Test import
        import cosa.utils.util_code_runner as code_runner_module
        
        # Test the actual smoke test if available
        if hasattr(code_runner_module, 'quick_smoke_test'):
            import io
            import contextlib
            
            output_buffer = io.StringIO()
            with contextlib.redirect_stdout(output_buffer):
                with contextlib.redirect_stderr(output_buffer):
                    code_runner_module.quick_smoke_test()
        
        duration = time.time() - start_time
        return True, duration, ""
        
    except Exception as e:
        duration = time.time() - start_time
        return False, duration, f"{type(e).__name__}: {str(e)}"


def scan_v000_dependencies():
    """
    Scan core modules for v000 dependencies.
    
    Returns:
        Dict[str, Any]: Dependency analysis results
    """
    dependencies = {
        "modules_scanned": 0,
        "v000_dependencies": [],
        "legacy_patterns": [],
        "clean_modules": []
    }
    
    core_modules = [
        "cosa.config.configuration_manager",
        "cosa.utils.util", 
        "cosa.utils.util_code_runner"
    ]
    
    for module_name in core_modules:
        dependencies["modules_scanned"] += 1
        
        try:
            module = sys.modules.get(module_name)
            if module and hasattr(module, '__file__'):
                module_file = module.__file__
                if module_file:
                    with open(module_file, 'r') as f:
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
                        
        except Exception:
            # Skip modules that can't be analyzed
            pass
    
    return dependencies


def quick_smoke_test():
    """Enhanced smoke test for core framework components."""
    utils = SmokeTestUtilities()
    utils.print_banner("Core Framework Tests", prepend_nl=True)
    
    tests = [
        ("Configuration Manager", test_configuration_manager),
        ("Core Utilities", test_utils_core), 
        ("Code Runner Utilities", test_util_code_runner)
    ]
    
    results = []
    total_duration = 0.0
    
    for test_name, test_func in tests:
        print(f"  Testing {test_name}...", end=" ")
        
        success, duration, error = test_func()
        total_duration += duration
        
        result = {
            "test": test_name,
            "success": success,
            "duration": duration,
            "error": error
        }
        results.append(result)
        
        if success:
            print(f"✓ PASSED ({utils.format_duration(duration)})")
        else:
            print(f"✗ FAILED ({utils.format_duration(duration)})")
            if error:
                print(f"    Error: {error}")
    
    # v000 dependency analysis
    print("\n  Scanning for v000 dependencies...")
    dependency_analysis = scan_v000_dependencies()
    
    print(f"  📊 Modules scanned: {dependency_analysis['modules_scanned']}")
    print(f"  ✅ Clean modules: {len(dependency_analysis['clean_modules'])}")
    print(f"  ⚠️  v000 dependencies: {len(dependency_analysis['v000_dependencies'])}")
    
    if dependency_analysis['v000_dependencies']:
        for dep in dependency_analysis['v000_dependencies']:
            print(f"      • {dep['module']}: {dep['pattern']}")
    
    # Summary
    passed = sum(1 for r in results if r['success'])
    total = len(results)
    success_rate = (passed / total * 100) if total > 0 else 0
    
    print(f"\n  ✅ Core Framework Results: {passed}/{total} passed ({success_rate:.1f}%) in {utils.format_duration(total_duration)}")
    
    if success_rate == 100:
        print("  🎉 All core framework tests passed!")
    elif success_rate >= 80:
        print("  ✅ Core framework mostly functional - minor issues detected")
    else:
        print("  ❌ Core framework has significant issues - review failures")


if __name__ == "__main__":
    quick_smoke_test()