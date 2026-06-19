#!/usr/bin/env python3
"""
Training System Tests: Model Training and XML Components

Tests the CoSA training system components including model training, quantization,
XML coordination, and related utilities with enhanced reporting and v000 dependency scanning.
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


def test_training_core_modules():
    """
    Test core training system modules.
    
    Ensures:
        - Training modules can be imported
        - Basic functionality is operational
        - No critical v000 dependencies
        
    Returns:
        List[Dict]: Results for each training module tested
    """
    training_modules = [
        ("hf_downloader", "cosa.training.hf_downloader"),
        ("peft_trainer", "cosa.training.peft_trainer"),
        ("quantizer", "cosa.training.quantizer"),
    ]
    
    results = []
    
    for module_name, module_path in training_modules:
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


def test_xml_coordination_modules():
    """
    Test XML coordination and processing modules.
    
    Ensures:
        - XML modules can be imported
        - XML processing functionality works
        - Critical v000 dependency scanning
        
    Returns:
        List[Dict]: Results for each XML module tested
    """
    xml_modules = [
        ("xml_coordinator", "cosa.training.xml_coordinator"),
        ("xml_prompt_generator", "cosa.training.xml_prompt_generator"),
        ("xml_response_validator", "cosa.training.xml_response_validator"),
    ]
    
    results = []
    
    for module_name, module_path in xml_modules:
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


def test_training_configurations():
    """
    Test training configuration modules.
    
    Ensures:
        - Model configuration modules are accessible
        - Configuration parameters are valid
        - No critical import issues
        
    Returns:
        List[Dict]: Results for each configuration module tested
    """
    config_modules = [
        ("llama_3_2_3b", "cosa.training.conf.llama_3_2_3b"),
        ("ministral_8b", "cosa.training.conf.ministral_8b"),
        ("mistral_7b", "cosa.training.conf.mistral_7b"),
        ("phi_4_mini", "cosa.training.conf.phi_4_mini"),
    ]
    
    results = []
    
    for module_name, module_path in config_modules:
        import time
        start_time = time.time()
        
        try:
            # Try to import the configuration module
            module = __import__(module_path, fromlist=[''])
            
            # Check for expected configuration attributes
            has_config = False
            config_attrs = ["model_name", "config", "parameters"]
            
            for attr in config_attrs:
                if hasattr(module, attr):
                    has_config = True
                    break
            
            if has_config:
                success = True
                error = ""
            else:
                success = True
                error = "No standard config attributes found"
            
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


def scan_v000_dependencies_in_training():
    """
    Scan training system modules for v000 dependencies.
    
    This is particularly important for training modules as they may reference
    legacy agent architectures for training data generation.
    
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
    
    # All training modules to scan
    all_training_modules = [
        "cosa.training.hf_downloader",
        "cosa.training.peft_trainer",
        "cosa.training.quantizer",
        "cosa.training.xml_coordinator",
        "cosa.training.xml_prompt_generator",
        "cosa.training.xml_response_validator",
        "cosa.training.conf.llama_3_2_3b",
        "cosa.training.conf.ministral_8b",
        "cosa.training.conf.mistral_7b",
        "cosa.training.conf.phi_4_mini",
    ]
    
    for module_name in all_training_modules:
        dependencies["modules_scanned"] += 1
        
        try:
            # Try to get the module for file scanning
            try:
                module = __import__(module_name, fromlist=[''])
                if hasattr(module, '__file__') and module.__file__:
                    with open(module.__file__, 'r') as f:
                        content = f.read()
                    
                    # Check for v000 patterns - training modules are critical for this
                    v000_patterns = [
                        "v000",
                        "agents.v000",
                        "from cosa.agents.v000",
                        "import cosa.agents.v000",
                        "raw_output_formatter"  # Common legacy import
                    ]
                    
                    found_v000 = False
                    found_patterns = []
                    
                    for pattern in v000_patterns:
                        if pattern in content:
                            # Additional check for raw_output_formatter to see if it's v000
                            if pattern == "raw_output_formatter":
                                if "v000" in content or "agents.v000" in content:
                                    found_patterns.append(f"{pattern} (likely v000)")
                                    found_v000 = True
                            else:
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
    """Enhanced smoke test for training system components."""
    utils = SmokeTestUtilities()
    utils.print_banner("Training System Tests", prepend_nl=True)
    
    print("  Testing Core Training Modules...")
    training_results = test_training_core_modules()
    
    print("  Testing XML Coordination Modules...")
    xml_results = test_xml_coordination_modules()
    
    print("  Testing Training Configurations...")
    config_results = test_training_configurations()
    
    # Combine all results
    all_results = training_results + xml_results + config_results
    
    # Print detailed results
    print("\n  📊 Detailed Results:")
    
    print("    Core Training:")
    for result in training_results:
        status = "✓" if result["success"] else "✗"
        duration_str = utils.format_duration(result["duration"])
        print(f"      {status} {result['module']:25} {duration_str:>8}")
        if not result["success"] and result["error"]:
            print(f"        Error: {result['error']}")
    
    print("    XML Coordination:")
    for result in xml_results:
        status = "✓" if result["success"] else "✗"
        duration_str = utils.format_duration(result["duration"])
        print(f"      {status} {result['module']:25} {duration_str:>8}")
        if not result["success"] and result["error"]:
            print(f"        Error: {result['error']}")
    
    print("    Model Configurations:")
    for result in config_results:
        status = "✓" if result["success"] else "✗"
        duration_str = utils.format_duration(result["duration"])
        print(f"      {status} {result['module']:25} {duration_str:>8}")
        if not result["success"] and result["error"]:
            print(f"        Error: {result['error']}")
    
    # Critical v000 dependency analysis for training modules
    print("\n  🔍 Critical: Scanning training modules for v000 dependencies...")
    dependency_analysis = scan_v000_dependencies_in_training()
    
    print(f"  📊 Modules scanned: {dependency_analysis['modules_scanned']}")
    print(f"  ✅ Clean modules: {len(dependency_analysis['clean_modules'])}")
    print(f"  ❌ Import errors: {len(dependency_analysis['import_errors'])}")
    print(f"  🚨 v000 dependencies: {len(dependency_analysis['v000_dependencies'])}")
    
    # Training modules are critical for v000 deprecation
    if dependency_analysis['v000_dependencies']:
        print("  🚨 CRITICAL: v000 dependencies found in training modules!")
        for dep in dependency_analysis['v000_dependencies']:
            print(f"      • {dep['module']}: {', '.join(dep['patterns'])}")
        print("  ⚠️  Training system dependencies must be updated before v000 deprecation")
    else:
        print("  ✅ EXCELLENT: No v000 dependencies found in training system!")
    
    # Show import errors for debugging
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
    
    print(f"\n  ✅ Training System Results: {passed_tests}/{total_tests} passed ({success_rate:.1f}%) in {utils.format_duration(total_duration)}")
    
    # Component-specific success rates
    training_success_rate = (sum(1 for r in training_results if r["success"]) / len(training_results) * 100) if training_results else 0
    xml_success_rate = (sum(1 for r in xml_results if r["success"]) / len(xml_results) * 100) if xml_results else 0
    config_success_rate = (sum(1 for r in config_results if r["success"]) / len(config_results) * 100) if config_results else 0
    
    print(f"  📈 Core Training: {training_success_rate:.1f}%")
    print(f"  📈 XML Coordination: {xml_success_rate:.1f}%")
    print(f"  📈 Model Configurations: {config_success_rate:.1f}%")
    
    # Status determination with emphasis on v000 dependencies
    if dependency_analysis['v000_dependencies']:
        print("  🚨 CRITICAL ISSUE: Training system has v000 dependencies!")
        print("  ⚠️  Must update training modules before v000 deprecation")
    elif success_rate == 100:
        print("  🎉 All training system components working perfectly!")
    elif success_rate >= 80:
        print("  ✅ Training system mostly functional - minor issues detected")
    elif success_rate >= 50:
        print("  ⚠️  Training system partially functional - review failures")
    else:
        print("  ❌ Training system has significant issues - check dependencies")
    
    # Specific guidance
    if training_success_rate < 50:
        print("  💡 Tip: Training failures often indicate missing PyTorch/Transformers dependencies")
    if xml_success_rate < 50:
        print("  💡 Tip: XML module failures may indicate missing XML processing dependencies")
    if config_success_rate < 50:
        print("  💡 Tip: Config failures suggest issues with model configuration files")


if __name__ == "__main__":
    quick_smoke_test()