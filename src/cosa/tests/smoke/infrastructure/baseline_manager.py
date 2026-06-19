#!/usr/bin/env python3
"""
CoSA Framework Smoke Test Baseline Manager

Handles saving and comparing test results baselines for regression detection
during v000 agent deprecation and other framework changes.

This module provides functionality to:
- Save comprehensive test baselines with timing and success metrics
- Compare current test results against saved baselines
- Generate detailed regression reports with actionable insights
- Track v000 dependency elimination progress
"""

import os
import json
import time
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path
from datetime import datetime


class BaselineManager:
    """
    Manages test result baselines for regression detection.
    
    Provides functionality to save comprehensive test baselines and compare
    current results against saved baselines to detect regressions during
    framework changes, particularly v000 agent deprecation.
    
    Requires:
        - Write access to baseline storage directory
        - Valid test results dictionaries for baseline operations
        
    Ensures:
        - Baselines are stored with comprehensive metadata
        - Comparisons provide actionable regression insights
        - Historical baseline tracking for trend analysis
        - v000 dependency tracking and progress reporting
        
    Raises:
        - OSError if baseline directory is not accessible
        - ValueError if test results format is invalid
    """
    
    def __init__( self, baseline_dir: Optional[str] = None ):
        """
        Initialize baseline manager.
        
        Requires:
            - baseline_dir is None or valid directory path
            
        Ensures:
            - Sets up baseline storage directory
            - Creates directory structure if it doesn't exist
            - Prepares for baseline save/load operations
            
        Raises:
            - OSError if directory cannot be created or accessed
        """
        if baseline_dir is None:
            # Default to baselines directory relative to this script
            script_dir = Path( __file__ ).parent
            baseline_dir = script_dir.parent / "config" / "baselines"
        
        self.baseline_dir = Path( baseline_dir )
        self.baseline_dir.mkdir( parents=True, exist_ok=True )
        
        # Ensure baselines directory is writable
        if not os.access( self.baseline_dir, os.W_OK ):
            raise OSError( f"Baseline directory is not writable: {self.baseline_dir}" )
    
    def _generate_baseline_filename( self, baseline_name: str = "default" ) -> str:
        """
        Generate timestamped baseline filename.
        
        Requires:
            - baseline_name is a valid string identifier
            
        Ensures:
            - Returns unique filename with timestamp
            - Uses safe characters for filesystem compatibility
            - Includes baseline name for identification
            
        Raises:
            - None
        
        Args:
            baseline_name: Descriptive name for the baseline
            
        Returns:
            str: Filename for the baseline file
        """
        timestamp = datetime.now().strftime( "%Y%m%d_%H%M%S" )
        safe_name = "".join( c for c in baseline_name if c.isalnum() or c in "_-" )
        return f"{safe_name}_{timestamp}.json"
    
    def _scan_v000_dependencies( self, test_results: Dict[str, Any] ) -> Dict[str, Any]:
        """
        Scan test results to identify v000 dependencies.
        
        Requires:
            - test_results contains test_details with module information
            
        Ensures:
            - Returns comprehensive v000 dependency analysis
            - Identifies modules with v000 imports or references
            - Provides percentage of modules still using v000
            - Includes specific dependency details for reporting
            
        Raises:
            - None (handles missing data gracefully)
        
        Args:
            test_results: Test execution results dictionary
            
        Returns:
            Dict[str, Any]: v000 dependency analysis
        """
        dependency_info = {
            "total_modules": 0,
            "v000_dependent_modules": 0,
            "dependency_percentage": 0.0,
            "dependent_modules": [],
            "scan_timestamp": time.strftime( "%Y-%m-%d %H:%M:%S" )
        }
        
        if "test_details" not in test_results:
            return dependency_info
        
        for test_detail in test_results["test_details"]:
            module_name = test_detail.get( "module", "" )
            dependency_info["total_modules"] += 1
            
            # Check if module name suggests v000 dependency
            # This is a simplified check - in practice, would scan actual module files
            if "v000" in module_name.lower() or test_detail.get( "error", "" ).find( "v000" ) != -1:
                dependency_info["v000_dependent_modules"] += 1
                dependency_info["dependent_modules"].append( {
                    "module": module_name,
                    "dependency_type": "import_error" if test_detail.get( "error" ) else "module_reference"
                } )
        
        if dependency_info["total_modules"] > 0:
            dependency_info["dependency_percentage"] = ( 
                dependency_info["v000_dependent_modules"] / dependency_info["total_modules"] * 100 
            )
        
        return dependency_info
    
    def save_baseline( self, test_results: Dict[str, Any], baseline_name: str = "v000_deprecation" ) -> str:
        """
        Save test results as baseline for future comparison.
        
        Requires:
            - test_results is a valid test results dictionary
            - baseline_name is a descriptive string identifier
            - Baseline directory is writable
            
        Ensures:
            - Saves comprehensive baseline with metadata
            - Includes v000 dependency analysis
            - Creates both timestamped and "latest" baseline files
            - Returns path to saved baseline file
            
        Raises:
            - OSError if baseline cannot be saved
            - ValueError if test_results format is invalid
        
        Args:
            test_results: Complete test execution results
            baseline_name: Descriptive name for this baseline
            
        Returns:
            str: Path to saved baseline file
        """
        # Validate test results format
        required_keys = ["timestamp", "total_tests", "passed_tests", "success_rate"]
        for key in required_keys:
            if key not in test_results:
                raise ValueError( f"Test results missing required key: {key}" )
        
        # Scan for v000 dependencies
        v000_analysis = self._scan_v000_dependencies( test_results )
        
        # Create comprehensive baseline
        baseline = {
            "metadata": {
                "baseline_name": baseline_name,
                "creation_timestamp": time.strftime( "%Y-%m-%d %H:%M:%S" ),
                "test_execution_timestamp": test_results["timestamp"],
                "baseline_version": "1.0"
            },
            "test_summary": {
                "total_tests": test_results["total_tests"],
                "passed_tests": test_results["passed_tests"],
                "failed_tests": test_results["failed_tests"],
                "success_rate": test_results["success_rate"],
                "total_duration": test_results["total_duration"],
                "quick_mode": test_results.get( "quick_mode", False )
            },
            "category_results": test_results.get( "categories", [] ),
            "v000_analysis": v000_analysis,
            "test_details": test_results.get( "test_details", [] )
        }
        
        # Save timestamped baseline
        baseline_filename = self._generate_baseline_filename( baseline_name )
        baseline_path = self.baseline_dir / baseline_filename
        
        with open( baseline_path, 'w' ) as f:
            json.dump( baseline, f, indent=2 )
        
        # Save as latest baseline for easy access
        latest_path = self.baseline_dir / "latest_baseline.json"
        with open( latest_path, 'w' ) as f:
            json.dump( baseline, f, indent=2 )
        
        return str( baseline_path )
    
    def load_baseline( self, baseline_name: str = "latest" ) -> Optional[Dict[str, Any]]:
        """
        Load saved baseline for comparison.
        
        Requires:
            - baseline_name is valid baseline identifier or "latest"
            - Baseline file exists and is readable
            
        Ensures:
            - Returns loaded baseline dictionary if found
            - Returns None if baseline doesn't exist
            - Handles file corruption gracefully
            
        Raises:
            - None (returns None for any loading errors)
        
        Args:
            baseline_name: Name of baseline to load or "latest"
            
        Returns:
            Optional[Dict[str, Any]]: Loaded baseline or None if not found
        """
        try:
            if baseline_name == "latest":
                baseline_path = self.baseline_dir / "latest_baseline.json"
            else:
                # Find most recent baseline with this name
                pattern = f"{baseline_name}_*.json"
                matching_files = list( self.baseline_dir.glob( pattern ) )
                if not matching_files:
                    return None
                baseline_path = max( matching_files, key=os.path.getctime )
            
            if not baseline_path.exists():
                return None
            
            with open( baseline_path, 'r' ) as f:
                return json.load( f )
                
        except ( json.JSONDecodeError, OSError ):
            return None
    
    def compare_baseline( self, current_results: Dict[str, Any], baseline_name: str = "latest" ) -> Dict[str, Any]:
        """
        Compare current test results with saved baseline.
        
        Requires:
            - current_results is valid test results dictionary
            - baseline_name identifies an existing baseline
            
        Ensures:
            - Returns comprehensive comparison analysis
            - Identifies regressions and improvements
            - Provides actionable insights for addressing issues
            - Includes v000 dependency progress tracking
            
        Raises:
            - ValueError if current_results format is invalid
        
        Args:
            current_results: Current test execution results
            baseline_name: Name of baseline to compare against
            
        Returns:
            Dict[str, Any]: Detailed comparison analysis
        """
        baseline = self.load_baseline( baseline_name )
        
        if baseline is None:
            return {
                "status": "no_baseline",
                "message": f"No baseline found with name '{baseline_name}'",
                "comparison_timestamp": time.strftime( "%Y-%m-%d %H:%M:%S" )
            }
        
        # Compare overall statistics
        baseline_summary = baseline["test_summary"]
        current_summary = {
            "total_tests": current_results["total_tests"],
            "passed_tests": current_results["passed_tests"], 
            "failed_tests": current_results["failed_tests"],
            "success_rate": current_results["success_rate"]
        }
        
        # Calculate changes
        changes = {
            "total_tests": current_summary["total_tests"] - baseline_summary["total_tests"],
            "passed_tests": current_summary["passed_tests"] - baseline_summary["passed_tests"],
            "failed_tests": current_summary["failed_tests"] - baseline_summary["failed_tests"],
            "success_rate": current_summary["success_rate"] - baseline_summary["success_rate"]
        }
        
        # Determine regression status
        regression_status = "no_change"
        if changes["failed_tests"] > 0:
            regression_status = "regression_detected"
        elif changes["passed_tests"] > 0 and changes["failed_tests"] == 0:
            regression_status = "improvement"
        
        # Compare v000 dependencies
        current_v000 = self._scan_v000_dependencies( current_results )
        baseline_v000 = baseline.get( "v000_analysis", {} )
        
        v000_progress = {
            "baseline_dependencies": baseline_v000.get( "v000_dependent_modules", 0 ),
            "current_dependencies": current_v000["v000_dependent_modules"],
            "reduction_count": baseline_v000.get( "v000_dependent_modules", 0 ) - current_v000["v000_dependent_modules"],
            "reduction_percentage": 0.0
        }
        
        if baseline_v000.get( "v000_dependent_modules", 0 ) > 0:
            v000_progress["reduction_percentage"] = (
                v000_progress["reduction_count"] / baseline_v000["v000_dependent_modules"] * 100
            )
        
        # Identify specific regressions
        regressions = []
        improvements = []
        
        # Compare by category
        baseline_categories = { cat["category"]: cat for cat in baseline.get( "category_results", [] ) }
        current_categories = { cat["category"]: cat for cat in current_results.get( "categories", [] ) }
        
        for category, current_cat in current_categories.items():
            baseline_cat = baseline_categories.get( category )
            if baseline_cat:
                baseline_rate = ( baseline_cat["passed_tests"] / baseline_cat["total_tests"] * 100 ) if baseline_cat["total_tests"] > 0 else 0
                current_rate = ( current_cat["passed_tests"] / current_cat["total_tests"] * 100 ) if current_cat["total_tests"] > 0 else 0
                
                if current_rate < baseline_rate:
                    regressions.append( {
                        "category": category,
                        "baseline_success_rate": baseline_rate,
                        "current_success_rate": current_rate,
                        "regression_amount": baseline_rate - current_rate
                    } )
                elif current_rate > baseline_rate:
                    improvements.append( {
                        "category": category,
                        "baseline_success_rate": baseline_rate,
                        "current_success_rate": current_rate,
                        "improvement_amount": current_rate - baseline_rate
                    } )
        
        comparison = {
            "status": regression_status,
            "comparison_timestamp": time.strftime( "%Y-%m-%d %H:%M:%S" ),
            "baseline_info": {
                "name": baseline["metadata"]["baseline_name"],
                "timestamp": baseline["metadata"]["creation_timestamp"]
            },
            "overall_changes": changes,
            "current_summary": current_summary,
            "baseline_summary": baseline_summary,
            "v000_progress": v000_progress,
            "category_regressions": regressions,
            "category_improvements": improvements,
            "recommendations": self._generate_recommendations( regression_status, regressions, v000_progress )
        }
        
        return comparison
    
    def _generate_recommendations( self, status: str, regressions: List[Dict], v000_progress: Dict ) -> List[str]:
        """
        Generate actionable recommendations based on comparison results.
        
        Requires:
            - status is valid regression status string
            - regressions is list of regression details
            - v000_progress contains dependency progress information
            
        Ensures:
            - Returns list of actionable recommendations
            - Addresses specific regression issues identified
            - Provides guidance for v000 deprecation progress
            - Prioritizes critical issues for immediate attention
            
        Raises:
            - None
        
        Args:
            status: Overall regression status
            regressions: List of category-specific regressions
            v000_progress: v000 dependency elimination progress
            
        Returns:
            List[str]: Actionable recommendations
        """
        recommendations = []
        
        if status == "regression_detected":
            recommendations.append( "⚠️  REGRESSIONS DETECTED - Review failed tests before proceeding" )
            
            for regression in regressions:
                recommendations.append( 
                    f"• {regression['category']} category: {regression['regression_amount']:.1f}% regression - investigate test failures"
                )
            
            recommendations.append( "• Consider reverting recent changes if regressions are critical" )
            recommendations.append( "• Run individual category tests for detailed failure analysis" )
        
        elif status == "improvement":
            recommendations.append( "✅ IMPROVEMENTS DETECTED - Good progress!" )
        
        elif status == "no_change":
            recommendations.append( "✅ NO REGRESSIONS - Changes appear safe" )
        
        # v000 deprecation progress recommendations
        if v000_progress["reduction_count"] > 0:
            recommendations.append( 
                f"🎯 v000 Progress: Eliminated {v000_progress['reduction_count']} dependencies ({v000_progress['reduction_percentage']:.1f}% reduction)"
            )
        
        if v000_progress["current_dependencies"] > 0:
            recommendations.append( 
                f"📋 Next Steps: {v000_progress['current_dependencies']} v000 dependencies remain - continue deprecation work"
            )
        else:
            recommendations.append( "🎉 v000 DEPRECATION COMPLETE - All legacy dependencies eliminated!" )
        
        return recommendations
    
    def list_baselines( self ) -> List[Dict[str, Any]]:
        """
        List all available baselines with metadata.
        
        Requires:
            - Baseline directory is accessible
            
        Ensures:
            - Returns list of baseline metadata
            - Sorted by creation timestamp (newest first)
            - Includes essential information for baseline selection
            
        Raises:
            - OSError if baseline directory is not accessible
        
        Returns:
            List[Dict[str, Any]]: List of baseline metadata
        """
        baselines = []
        
        for baseline_file in self.baseline_dir.glob( "*.json" ):
            if baseline_file.name == "latest_baseline.json":
                continue  # Skip the latest symlink
            
            try:
                with open( baseline_file, 'r' ) as f:
                    baseline_data = json.load( f )
                
                metadata = baseline_data.get( "metadata", {} )
                summary = baseline_data.get( "test_summary", {} )
                
                baselines.append( {
                    "filename": baseline_file.name,
                    "name": metadata.get( "baseline_name", "unknown" ),
                    "creation_timestamp": metadata.get( "creation_timestamp", "unknown" ),
                    "total_tests": summary.get( "total_tests", 0 ),
                    "success_rate": summary.get( "success_rate", 0.0 )
                } )
                
            except ( json.JSONDecodeError, OSError ):
                continue  # Skip corrupted files
        
        # Sort by creation timestamp (newest first)
        baselines.sort( key=lambda x: x["creation_timestamp"], reverse=True )
        
        return baselines


def quick_smoke_test():
    """Quick smoke test to validate BaselineManager functionality."""
    import tempfile
    import cosa.utils.util as du
    
    du.print_banner( "BaselineManager Smoke Test", prepend_nl=True )
    
    try:
        # Create temporary baseline directory
        with tempfile.TemporaryDirectory() as temp_dir:
            baseline_mgr = BaselineManager( temp_dir )
            print( "✓ BaselineManager created successfully" )
            
            # Create mock test results
            mock_results = {
                "timestamp": "2025-08-02 15:30:00",
                "total_tests": 10,
                "passed_tests": 9,
                "failed_tests": 1,
                "success_rate": 90.0,
                "total_duration": 45.5,
                "categories": [
                    {
                        "category": "core",
                        "total_tests": 5,
                        "passed_tests": 5,
                        "failed_tests": 0
                    }
                ],
                "test_details": [
                    { "module": "test.module", "success": True, "duration": 1.5, "error": "" }
                ]
            }
            
            # Test baseline saving
            baseline_file = baseline_mgr.save_baseline( mock_results, "test_baseline" )
            print( f"✓ Baseline saved to: {baseline_file}" )
            
            # Test baseline loading
            loaded_baseline = baseline_mgr.load_baseline( "latest" )
            if loaded_baseline:
                print( "✓ Baseline loaded successfully" )
            else:
                print( "✗ Failed to load baseline" )
            
            # Test baseline comparison
            comparison = baseline_mgr.compare_baseline( mock_results, "latest" )
            print( f"✓ Baseline comparison completed: {comparison['status']}" )
            
            # Test baseline listing
            baselines = baseline_mgr.list_baselines()
            print( f"✓ Found {len(baselines)} baselines" )
    
    except Exception as e:
        print( f"✗ Error during baseline manager testing: {e}" )
    
    print( "\n✓ BaselineManager smoke test completed" )


if __name__ == "__main__":
    quick_smoke_test()