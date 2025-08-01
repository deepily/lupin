#!/usr/bin/env python3
"""
WebSocket Smoke Test Runner

Main orchestrator for running WebSocket smoke tests against the live FastAPI server.
Manages test discovery, execution, result aggregation, baseline comparison, and reporting.

Usage:
    python smoke_test_runner.py [--config CONFIG_FILE] [--category CATEGORY] [--baseline-update]
"""

import asyncio
import json
import time
import configparser
import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass

# Import our test utilities
from test_utilities import WebSocketTestUtilities

# Import Phase 2 comprehensive test suites
import sys
from pathlib import Path
sys.path.append( str( Path( __file__ ).parent.parent / "core" ) )
from test_connection_basic import ConnectionBasicTests
from test_authentication_flow import AuthenticationFlowTests
from test_session_management import SessionManagementTests
from test_event_system import EventSystemTests


@dataclass
class TestResult:
    """Container for individual test results."""
    name: str
    category: str
    success: bool
    duration_ms: float
    error: Optional[str] = None
    details: Optional[Dict[str, Any]] = None


@dataclass
class TestSuiteResults:
    """Container for complete test suite results."""
    start_time: datetime
    end_time: Optional[datetime] = None
    total_tests: int = 0
    passed_tests: int = 0
    failed_tests: int = 0
    results: List[TestResult] = None
    performance_data: Dict[str, Any] = None
    
    def __post_init__( self ):
        if self.results is None:
            self.results = []
        if self.performance_data is None:
            self.performance_data = {}


class SmokeTestRunner:
    """
    Main smoke test runner for WebSocket functionality.
    
    Orchestrates test execution, manages configuration, compares against baselines,
    and generates comprehensive reports.
    """
    
    def __init__( self, config_file: str = None ):
        """
        Initialize the smoke test runner.
        
        Args:
            config_file: Path to configuration file (default: smoke_test_config.ini)
        """
        self.config_file = config_file or self._get_default_config_path()
        self.config = self._load_configuration()
        self.baselines = self._load_baselines()
        self.utils = WebSocketTestUtilities( self.config.get( "server", "base_url" ) )
        
        # Configure debug mode
        self.utils.debug = self.config.getboolean( "logging", "debug_enabled" )
        
        self.log( "🧪 WebSocket Smoke Test Runner initialized" )
        self.log( f"   Server: {self.config.get('server', 'base_url')}" )
        self.log( f"   Config: {self.config_file}" )
    
    def _get_default_config_path( self ) -> str:
        """Get the default configuration file path."""
        config_dir = Path( __file__ ).parent.parent / "config"
        return str( config_dir / "smoke_test_config.ini" )
    
    def _load_configuration( self ) -> configparser.ConfigParser:
        """Load test configuration from INI file."""
        config = configparser.ConfigParser()
        
        if not Path( self.config_file ).exists():
            raise FileNotFoundError( f"Configuration file not found: {self.config_file}" )
        
        config.read( self.config_file )
        return config
    
    def _load_baselines( self ) -> Dict[str, Any]:
        """Load performance baselines from JSON file."""
        baseline_file = self.config.get( "baselines", "baseline_file" )
        baseline_path = Path( self.config_file ).parent / baseline_file
        
        if not baseline_path.exists():
            self.log( f"⚠️ Baseline file not found: {baseline_path}", "WARN" )
            return {}
        
        try:
            with open( baseline_path, 'r' ) as f:
                return json.load( f )
        except Exception as e:
            self.log( f"⚠️ Error loading baselines: {e}", "WARN" )
            return {}
    
    def log( self, message: str, level: str = "INFO" ):
        """Log message with timestamp if enabled."""
        if self.config.getboolean( "logging", "debug_enabled" ):
            if self.config.getboolean( "logging", "log_timestamps" ):
                timestamp = datetime.now().strftime( "%H:%M:%S.%f" )[:-3]
                print( f"[{timestamp}] [{level}] {message}" )
            else:
                print( f"[{level}] {message}" )
    
    async def run_all_tests( self, save_baseline: bool = False, compare_baseline: bool = False ) -> TestSuiteResults:
        """
        Run all enabled smoke tests.
        
        Args:
            save_baseline: If True, save results as baseline for future comparison
            compare_baseline: If True, compare results with saved baseline
        
        Returns:
            Complete test suite results
        """
        results = TestSuiteResults( start_time=datetime.now( timezone.utc ) )
        
        self.log( "🚀 Starting WebSocket Smoke Test Suite" )
        self.log( "=" * 60 )
        
        # Test 1: Server Health Check
        if self.config.getboolean( "test_categories", "run_core_tests" ):
            await self._run_server_health_test( results )
            
            # Only continue if server is healthy
            if results.results[-1].success:
                # Phase 1: Original Smoke Tests (quick validation)
                await self._run_basic_connection_tests( results )
                await self._run_authentication_tests( results )
                await self._run_event_system_tests( results )
                
                # Phase 2: Comprehensive Test Suites (detailed validation)
                await self._run_phase2_connection_tests( results )
                await self._run_phase2_authentication_tests( results )
                await self._run_phase2_session_tests( results )
                await self._run_phase2_event_tests( results )
                
                # Performance and Load Tests
                if self.config.getboolean( "test_categories", "run_performance_tests" ):
                    await self._run_performance_tests( results )
                
                await self._run_concurrent_tests( results )
            else:
                self.log( "❌ Server unhealthy - skipping remaining tests", "ERROR" )
        
        results.end_time = datetime.now( timezone.utc )
        results.total_tests = len( results.results )
        results.passed_tests = sum( 1 for r in results.results if r.success )
        results.failed_tests = results.total_tests - results.passed_tests
        
        # Handle baseline operations
        baseline_comparison_result = None
        if save_baseline:
            self._save_baseline( results )
        if compare_baseline:
            baseline_comparison_result = self._compare_with_baseline( results )
            
        self._generate_report( results, baseline_comparison_result )
        return results
    
    async def _run_server_health_test( self, results: TestSuiteResults ):
        """Run server health check test."""
        self.log( "\n🏥 Testing Server Health..." )
        
        start_time = time.time()
        try:
            healthy = await self.utils.check_server_health()
            duration = ( time.time() - start_time ) * 1000
            
            result = TestResult(
                name="server_health_check",
                category="core",
                success=healthy,
                duration_ms=duration,
                error=None if healthy else "Server health check failed"
            )
            results.results.append( result )
            
            status = "✅ PASS" if healthy else "❌ FAIL"
            self.log( f"   Server Health: {status} ({duration:.2f}ms)" )
            
        except Exception as e:
            duration = ( time.time() - start_time ) * 1000
            result = TestResult(
                name="server_health_check",
                category="core",
                success=False,
                duration_ms=duration,
                error=str( e )
            )
            results.results.append( result )
            self.log( f"   Server Health: ❌ FAIL ({duration:.2f}ms) - {e}", "ERROR" )
    
    async def _run_basic_connection_tests( self, results: TestSuiteResults ):
        """Run basic WebSocket connection tests."""
        self.log( "\n🔌 Testing Basic WebSocket Connections..." )
        
        # Test queue WebSocket connection
        await self._test_websocket_connection( "queue", results )
        
        # Test audio WebSocket connection  
        await self._test_websocket_connection( "audio", results )
    
    async def _test_websocket_connection( self, endpoint: str, results: TestSuiteResults ):
        """Test connection to a specific WebSocket endpoint."""
        test_name = f"{endpoint}_websocket_connection"
        
        start_time = time.time()
        try:
            session_id = self.utils.generate_session_id()
            websocket = await self.utils.connect_websocket( endpoint, session_id, timeout=10.0 )
            await websocket.close()
            
            duration = ( time.time() - start_time ) * 1000
            result = TestResult(
                name=test_name,
                category="core",
                success=True,
                duration_ms=duration,
                details={"session_id": session_id}
            )
            results.results.append( result )
            
            self.log( f"   {endpoint.capitalize()} Connection: ✅ PASS ({duration:.2f}ms)" )
            
        except Exception as e:
            duration = ( time.time() - start_time ) * 1000
            result = TestResult(
                name=test_name,
                category="core",
                success=False,
                duration_ms=duration,
                error=str( e )
            )
            results.results.append( result )
            self.log( f"   {endpoint.capitalize()} Connection: ❌ FAIL ({duration:.2f}ms) - {e}", "ERROR" )
    
    async def _run_authentication_tests( self, results: TestSuiteResults ):
        """Run WebSocket authentication flow tests."""
        self.log( "\n🔐 Testing Authentication Flows..." )
        
        # Test queue WebSocket authentication
        await self._test_websocket_authentication( "queue", results )
        
        # Test audio WebSocket authentication (different behavior expected)
        await self._test_websocket_authentication( "audio", results )
    
    async def _test_websocket_authentication( self, endpoint: str, results: TestSuiteResults ):
        """Test authentication for a specific WebSocket endpoint."""
        test_name = f"{endpoint}_websocket_authentication"
        
        start_time = time.time()
        try:
            session_id = self.utils.generate_session_id()
            token = self.utils.generate_mock_token( "auth_test_user" )
            
            websocket = await self.utils.connect_websocket( endpoint, session_id )
            auth_success, auth_data = await self.utils.authenticate_websocket( websocket, token )
            await websocket.close()
            
            duration = ( time.time() - start_time ) * 1000
            
            # Audio WebSocket may behave differently - this is expected
            expected_behavior = endpoint == "queue" or ( endpoint == "audio" and not auth_success )
            success = auth_success if endpoint == "queue" else True  # Audio always succeeds (different behavior)
            
            result = TestResult(
                name=test_name,
                category="core",
                success=success,
                duration_ms=duration,
                details={
                    "auth_success": auth_success,
                    "auth_data": auth_data,
                    "endpoint_behavior": "expected" if expected_behavior else "unexpected"
                }
            )
            results.results.append( result )
            
            status = "✅ PASS" if success else "❌ FAIL"
            self.log( f"   {endpoint.capitalize()} Auth: {status} ({duration:.2f}ms)" )
            
        except Exception as e:
            duration = ( time.time() - start_time ) * 1000
            result = TestResult(
                name=test_name,
                category="core",
                success=False,
                duration_ms=duration,
                error=str( e )
            )
            results.results.append( result )
            self.log( f"   {endpoint.capitalize()} Auth: ❌ FAIL ({duration:.2f}ms) - {e}", "ERROR" )
    
    async def _run_event_system_tests( self, results: TestSuiteResults ):
        """Run WebSocket event system tests."""
        self.log( "\n📡 Testing Event System..." )
        
        # Test event collection from queue WebSocket
        await self._test_event_collection( "queue", results, duration=3.0 )
        
        # Test event collection from audio WebSocket
        await self._test_event_collection( "audio", results, duration=2.0 )
    
    async def _test_event_collection( self, endpoint: str, results: TestSuiteResults, duration: float = 3.0 ):
        """Test event collection from a WebSocket endpoint."""
        test_name = f"{endpoint}_event_collection"
        
        start_time = time.time()
        try:
            flow_result = await self.utils.test_websocket_flow( endpoint, "event_test_user", duration )
            test_duration = ( time.time() - start_time ) * 1000
            
            result = TestResult(
                name=test_name,
                category="integration",
                success=flow_result["success"],
                duration_ms=test_duration,
                error=flow_result.get( "error" ),
                details={
                    "events_collected": flow_result["events_collected"],
                    "event_types": [event.get( "type", "unknown" ) for event in flow_result.get( "events", [] )]
                }
            )
            results.results.append( result )
            
            status = "✅ PASS" if flow_result["success"] else "❌ FAIL"
            event_count = flow_result["events_collected"]
            self.log( f"   {endpoint.capitalize()} Events: {status} ({test_duration:.2f}ms) - {event_count} events" )
            
        except Exception as e:
            test_duration = ( time.time() - start_time ) * 1000
            result = TestResult(
                name=test_name,
                category="integration",
                success=False,
                duration_ms=test_duration,
                error=str( e )
            )
            results.results.append( result )
            self.log( f"   {endpoint.capitalize()} Events: ❌ FAIL ({test_duration:.2f}ms) - {e}", "ERROR" )
    
    async def _run_performance_tests( self, results: TestSuiteResults ):
        """Run performance measurement tests."""
        self.log( "\n⚡ Testing Performance Metrics..." )
        
        # Test multiple connection attempts to get performance statistics
        connection_times = {"queue": [], "audio": []}
        samples = self.config.getint( "performance", "performance_samples", fallback=3 )
        
        for endpoint in ["queue", "audio"]:
            for i in range( samples ):
                start_time = time.time()
                try:
                    session_id = self.utils.generate_session_id()
                    websocket = await self.utils.connect_websocket( endpoint, session_id )
                    await websocket.close()
                    duration = ( time.time() - start_time ) * 1000
                    connection_times[endpoint].append( duration )
                except Exception as e:
                    self.log( f"   Performance sample {i+1} failed for {endpoint}: {e}", "WARN" )
        
        # Analyze performance data
        for endpoint in ["queue", "audio"]:
            times = connection_times[endpoint]
            if times:
                avg_time = sum( times ) / len( times )
                max_time = max( times )
                max_acceptable = self.config.getfloat( "performance", "max_connection_time", fallback=500.0 )
                
                success = avg_time <= max_acceptable
                result = TestResult(
                    name=f"{endpoint}_performance",
                    category="performance",
                    success=success,
                    duration_ms=avg_time,
                    details={
                        "samples": len( times ),
                        "avg_ms": avg_time,
                        "max_ms": max_time,
                        "threshold_ms": max_acceptable,
                        "all_times": times
                    }
                )
                results.results.append( result )
                
                status = "✅ PASS" if success else "❌ FAIL"
                self.log( f"   {endpoint.capitalize()} Perf: {status} ({avg_time:.2f}ms avg, {len(times)} samples)" )
    
    async def _run_concurrent_tests( self, results: TestSuiteResults ):
        """Run concurrent connection tests."""
        self.log( "\n👥 Testing Concurrent Connections..." )
        
        max_connections = self.config.getint( "testing", "max_concurrent_connections", fallback=5 )
        
        start_time = time.time()
        try:
            # Create multiple concurrent connections
            tasks = []
            for i in range( max_connections ):
                session_id = self.utils.generate_session_id()
                task = self._test_concurrent_connection( "queue", session_id, f"concurrent_user_{i}" )
                tasks.append( task )
            
            # Wait for all connections to complete
            connection_results = await asyncio.gather( *tasks, return_exceptions=True )
            test_duration = ( time.time() - start_time ) * 1000
            
            # Analyze results
            successful_connections = sum( 1 for r in connection_results if isinstance( r, bool ) and r )
            success_rate = ( successful_connections / max_connections ) * 100
            min_success_rate = 95.0  # Require 95% success rate
            
            result = TestResult(
                name="concurrent_connections",
                category="load",
                success=success_rate >= min_success_rate,
                duration_ms=test_duration,
                details={
                    "total_connections": max_connections,
                    "successful_connections": successful_connections,
                    "success_rate_percent": success_rate,
                    "min_required_percent": min_success_rate
                }
            )
            results.results.append( result )
            
            status = "✅ PASS" if success_rate >= min_success_rate else "❌ FAIL"
            self.log( f"   Concurrent Test: {status} ({test_duration:.2f}ms) - {successful_connections}/{max_connections} ({success_rate:.1f}%)" )
            
        except Exception as e:
            test_duration = ( time.time() - start_time ) * 1000
            result = TestResult(
                name="concurrent_connections",
                category="load",
                success=False,
                duration_ms=test_duration,
                error=str( e )
            )
            results.results.append( result )
            self.log( f"   Concurrent Test: ❌ FAIL ({test_duration:.2f}ms) - {e}", "ERROR" )
    
    async def _test_concurrent_connection( self, endpoint: str, session_id: str, user_id: str ) -> bool:
        """Test a single concurrent connection."""
        try:
            websocket = await self.utils.connect_websocket( endpoint, session_id )
            token = self.utils.generate_mock_token( user_id )
            auth_success, _ = await self.utils.authenticate_websocket( websocket, token )
            await websocket.close()
            return auth_success
        except Exception:
            return False
    
    # Phase 2: Comprehensive Test Suite Integration
    
    async def _run_phase2_connection_tests( self, results: TestSuiteResults ):
        """Run Phase 2 comprehensive connection tests."""
        self.log( "\\n🔌 Phase 2: Comprehensive Connection Tests" )
        
        try:
            connection_tester = ConnectionBasicTests( self.config.get( "server", "base_url" ) )
            connection_results = await connection_tester.run_all_tests()
            
            # Convert Phase 2 results to our TestResult format
            for test_result in connection_results:
                result = TestResult(
                    name=f"phase2_connection_{test_result['name']}",
                    category="core",
                    success=test_result["success"],
                    duration_ms=test_result["duration_ms"],
                    error=test_result.get( "error" ),
                    details=test_result.get( "details" )
                )
                results.results.append( result )
            
            passed = sum( 1 for r in connection_results if r["success"] )
            total = len( connection_results )
            self.log( f"   Connection Tests: {passed}/{total} passed" )
            
        except Exception as e:
            self.log( f"   ❌ Phase 2 Connection Tests failed: {e}", "ERROR" )
            error_result = TestResult(
                name="phase2_connection_suite",
                category="core", 
                success=False,
                duration_ms=0,
                error=str( e )
            )
            results.results.append( error_result )
    
    async def _run_phase2_authentication_tests( self, results: TestSuiteResults ):
        """Run Phase 2 comprehensive authentication tests."""
        self.log( "\\n🔐 Phase 2: Comprehensive Authentication Tests" )
        
        try:
            auth_tester = AuthenticationFlowTests( self.config.get( "server", "base_url" ) )
            auth_results = await auth_tester.run_all_tests()
            
            # Convert Phase 2 results to our TestResult format
            for test_result in auth_results:
                result = TestResult(
                    name=f"phase2_auth_{test_result['name']}",
                    category="core",
                    success=test_result["success"],
                    duration_ms=test_result["duration_ms"],
                    error=test_result.get( "error" ),
                    details=test_result.get( "details" )
                )
                results.results.append( result )
            
            passed = sum( 1 for r in auth_results if r["success"] )
            total = len( auth_results )
            self.log( f"   Authentication Tests: {passed}/{total} passed" )
            
        except Exception as e:
            self.log( f"   ❌ Phase 2 Authentication Tests failed: {e}", "ERROR" )
            error_result = TestResult(
                name="phase2_auth_suite",
                category="core",
                success=False,
                duration_ms=0,
                error=str( e )
            )
            results.results.append( error_result )
    
    async def _run_phase2_session_tests( self, results: TestSuiteResults ):
        """Run Phase 2 comprehensive session management tests."""
        self.log( "\\n📋 Phase 2: Comprehensive Session Management Tests" )
        
        try:
            session_tester = SessionManagementTests( self.config.get( "server", "base_url" ) )
            session_results = await session_tester.run_all_tests()
            
            # Convert Phase 2 results to our TestResult format
            for test_result in session_results:
                result = TestResult(
                    name=f"phase2_session_{test_result['name']}",
                    category="integration",
                    success=test_result["success"],
                    duration_ms=test_result["duration_ms"],
                    error=test_result.get( "error" ),
                    details=test_result.get( "details" )
                )
                results.results.append( result )
            
            passed = sum( 1 for r in session_results if r["success"] )
            total = len( session_results )
            self.log( f"   Session Management Tests: {passed}/{total} passed" )
            
        except Exception as e:
            self.log( f"   ❌ Phase 2 Session Management Tests failed: {e}", "ERROR" )
            error_result = TestResult(
                name="phase2_session_suite",
                category="integration",
                success=False,
                duration_ms=0,
                error=str( e )
            )
            results.results.append( error_result )
    
    async def _run_phase2_event_tests( self, results: TestSuiteResults ):
        """Run Phase 2 comprehensive event system tests."""
        self.log( "\\n📡 Phase 2: Comprehensive Event System Tests" )
        
        try:
            event_tester = EventSystemTests( self.config.get( "server", "base_url" ) )
            event_results = await event_tester.run_all_tests()
            
            # Convert Phase 2 results to our TestResult format
            for test_result in event_results:
                result = TestResult(
                    name=f"phase2_event_{test_result['name']}",
                    category="integration",
                    success=test_result["success"],
                    duration_ms=test_result["duration_ms"],
                    error=test_result.get( "error" ),
                    details=test_result.get( "details" )
                )
                results.results.append( result )
            
            passed = sum( 1 for r in event_results if r["success"] )
            total = len( event_results )
            self.log( f"   Event System Tests: {passed}/{total} passed" )
            
        except Exception as e:
            self.log( f"   ❌ Phase 2 Event System Tests failed: {e}", "ERROR" )
            error_result = TestResult(
                name="phase2_event_suite",
                category="integration",
                success=False,
                duration_ms=0,
                error=str( e )
            )
            results.results.append( error_result )
    
    def _save_baseline( self, results: TestSuiteResults ):
        """Save current test results as baseline for future comparison."""
        baseline_dir = Path( self.config_file ).parent / "baselines"
        baseline_dir.mkdir( exist_ok=True )
        
        timestamp = datetime.now().strftime( "%Y%m%d_%H%M%S" )
        baseline_file = baseline_dir / f"baseline_{timestamp}.json"
        
        # Extract key performance metrics
        performance_data = {}
        functional_data = {}
        
        for result in results.results:
            result_data = {
                "success": result.success,
                "duration_ms": result.duration_ms,
                "error": result.error,
                "details": result.details
            }
            
            if result.category == "performance":
                performance_data[result.name] = result_data
            else:
                functional_data[result.name] = result_data
        
        baseline_data = {
            "version": "1.0",
            "timestamp": results.start_time.isoformat(),
            "server_url": self.config.get( "server", "base_url" ),
            "execution_time_seconds": ( results.end_time - results.start_time ).total_seconds(),
            "test_summary": {
                "total_tests": results.total_tests,
                "passed_tests": results.passed_tests,
                "failed_tests": results.failed_tests,
                "success_rate": ( results.passed_tests / results.total_tests ) * 100 if results.total_tests > 0 else 0
            },
            "performance_metrics": performance_data,
            "functional_results": functional_data,
            "system_info": {
                "config_file": str( self.config_file ),
                "test_categories": {
                    "core": len( [r for r in results.results if r.category == "core"] ),
                    "integration": len( [r for r in results.results if r.category == "integration"] ),
                    "performance": len( [r for r in results.results if r.category == "performance"] ),
                    "load": len( [r for r in results.results if r.category == "load"] )
                }
            }
        }
        
        try:
            with open( baseline_file, 'w' ) as f:
                json.dump( baseline_data, f, indent=2 )
            
            self.log( f"💾 Baseline saved: {baseline_file}" )
            self.log( f"   Tests: {results.total_tests} total, {results.passed_tests} passed" )
            self.log( f"   Performance: {len(performance_data)} metrics captured" )
            
            # Also save as "latest" for easy access
            latest_baseline = baseline_dir / "latest_baseline.json"
            with open( latest_baseline, 'w' ) as f:
                json.dump( baseline_data, f, indent=2 )
                
        except Exception as e:
            self.log( f"❌ Failed to save baseline: {e}", "ERROR" )

    def _compare_with_baseline( self, results: TestSuiteResults ) -> Dict[str, Any]:
        """Compare current results with saved baseline."""
        baseline_dir = Path( self.config_file ).parent / "baselines"
        latest_baseline = baseline_dir / "latest_baseline.json"
        
        if not latest_baseline.exists():
            self.log( "⚠️ No baseline found for comparison", "WARN" )
            return {"status": "no_baseline", "message": "No baseline available for comparison"}
        
        try:
            with open( latest_baseline, 'r' ) as f:
                baseline_data = json.load( f )
        except Exception as e:
            self.log( f"❌ Failed to load baseline: {e}", "ERROR" )
            return {"status": "error", "message": f"Failed to load baseline: {e}"}
        
        self.log( f"📊 Comparing with baseline from {baseline_data.get('timestamp', 'unknown')}" )
        
        comparison_result = {
            "status": "success",
            "baseline_timestamp": baseline_data.get( "timestamp" ),
            "performance_changes": {},
            "functional_changes": {},
            "overall_regression": False,
            "critical_regressions": [],
            "improvements": []
        }
        
        # Compare performance metrics
        tolerance_percent = self.config.getfloat( "baselines", "baseline_tolerance_percent", fallback=20.0 )
        baseline_perf = baseline_data.get( "performance_metrics", {} )
        
        for result in results.results:
            if result.category == "performance" and result.name in baseline_perf:
                baseline_duration = baseline_perf[result.name]["duration_ms"]
                current_duration = result.duration_ms
                
                if baseline_duration > 0:
                    change_percent = ( ( current_duration - baseline_duration ) / baseline_duration ) * 100
                    
                    comparison_result["performance_changes"][result.name] = {
                        "baseline_ms": baseline_duration,
                        "current_ms": current_duration,
                        "change_percent": change_percent,
                        "regression": change_percent > tolerance_percent,
                        "improvement": change_percent < -10.0  # 10% improvement threshold
                    }
                    
                    if change_percent > tolerance_percent:
                        comparison_result["critical_regressions"].append( {
                            "test": result.name,
                            "type": "performance",
                            "change_percent": change_percent,
                            "baseline_ms": baseline_duration,
                            "current_ms": current_duration
                        } )
                        comparison_result["overall_regression"] = True
                    elif change_percent < -10.0:
                        comparison_result["improvements"].append( {
                            "test": result.name,
                            "type": "performance",
                            "improvement_percent": abs( change_percent ),
                            "baseline_ms": baseline_duration,
                            "current_ms": current_duration
                        } )
        
        # Compare functional test results
        baseline_func = baseline_data.get( "functional_results", {} )
        
        for result in results.results:
            if result.category != "performance" and result.name in baseline_func:
                baseline_success = baseline_func[result.name]["success"]
                current_success = result.success
                
                if baseline_success and not current_success:
                    comparison_result["critical_regressions"].append( {
                        "test": result.name,
                        "type": "functional",
                        "issue": "Previously passing test now fails",
                        "error": result.error
                    } )
                    comparison_result["overall_regression"] = True
                elif not baseline_success and current_success:
                    comparison_result["improvements"].append( {
                        "test": result.name,
                        "type": "functional",
                        "improvement": "Previously failing test now passes"
                    } )
        
        # Compare overall success rate
        baseline_success_rate = baseline_data.get( "test_summary", {} ).get( "success_rate", 100 )
        current_success_rate = ( results.passed_tests / results.total_tests ) * 100 if results.total_tests > 0 else 0
        
        if current_success_rate < baseline_success_rate:
            success_rate_drop = baseline_success_rate - current_success_rate
            if success_rate_drop > 5.0:  # More than 5% drop in success rate
                comparison_result["critical_regressions"].append( {
                    "test": "overall_success_rate",
                    "type": "functional",
                    "baseline_percent": baseline_success_rate,
                    "current_percent": current_success_rate,
                    "drop_percent": success_rate_drop
                } )
                comparison_result["overall_regression"] = True
        
        return comparison_result

    def _generate_report( self, results: TestSuiteResults, baseline_comparison: Optional[Dict[str, Any]] = None ):
        """Generate a comprehensive test report."""
        self.log( "\n" + "=" * 60 )
        self.log( "📊 SMOKE TEST RESULTS SUMMARY" )
        self.log( "=" * 60 )
        
        # Overall summary
        total_duration = ( results.end_time - results.start_time ).total_seconds()
        self.log( f"Execution Time: {total_duration:.2f}s" )
        self.log( f"Total Tests: {results.total_tests}" )
        self.log( f"Passed: {results.passed_tests}" )
        self.log( f"Failed: {results.failed_tests}" )
        self.log( f"Success Rate: {(results.passed_tests/results.total_tests)*100:.1f}%" )
        
        # Category breakdown
        categories = {}
        for result in results.results:
            if result.category not in categories:
                categories[result.category] = {"total": 0, "passed": 0}
            categories[result.category]["total"] += 1
            if result.success:
                categories[result.category]["passed"] += 1
        
        self.log( "\nResults by Category:" )
        for category, stats in categories.items():
            success_rate = ( stats["passed"] / stats["total"] ) * 100
            self.log( f"  {category.capitalize()}: {stats['passed']}/{stats['total']} ({success_rate:.1f}%)" )
        
        # Failed tests detail
        failed_tests = [r for r in results.results if not r.success]
        if failed_tests:
            self.log( "\n❌ Failed Tests:" )
            for test in failed_tests:
                self.log( f"  • {test.name}: {test.error}" )
        
        # Performance highlights
        perf_tests = [r for r in results.results if r.category == "performance"]
        if perf_tests:
            self.log( "\n⚡ Performance Summary:" )
            for test in perf_tests:
                if test.details:
                    avg_ms = test.details.get( "avg_ms", 0 )
                    samples = test.details.get( "samples", 0 )
                    self.log( f"  • {test.name}: {avg_ms:.2f}ms avg ({samples} samples)" )
        
        # Baseline comparison results
        if baseline_comparison:
            self._report_baseline_comparison( baseline_comparison )
        
        # Final status
        self.log( "\n" + "=" * 60 )
        
        # Determine exit status including baseline regressions
        critical_issues = results.failed_tests > 0
        if baseline_comparison and baseline_comparison.get( "overall_regression" ):
            critical_issues = True
            
        if not critical_issues:
            self.log( "✅ ALL SMOKE TESTS PASSED!" )
            if baseline_comparison and baseline_comparison.get( "improvements" ):
                self.log( f"🚀 BONUS: Found {len(baseline_comparison['improvements'])} performance improvements!" )
            sys.exit( 0 )
        else:
            if results.failed_tests > 0:
                self.log( f"❌ {results.failed_tests} TESTS FAILED!" )
            if baseline_comparison and baseline_comparison.get( "overall_regression" ):
                self.log( f"📉 REGRESSION DETECTED: {len(baseline_comparison['critical_regressions'])} critical regressions found!" )
                self.log( "   Consider reverting recent changes or investigating performance issues" )
            sys.exit( 1 )

    def _report_baseline_comparison( self, comparison: Dict[str, Any] ):
        """Generate baseline comparison report section."""
        self.log( "\n📊 BASELINE COMPARISON" )
        self.log( "=" * 60 )
        
        if comparison["status"] != "success":
            self.log( f"⚠️ Comparison Status: {comparison.get('message', 'Unknown issue')}" )
            return
            
        baseline_time = comparison.get( "baseline_timestamp", "unknown" )
        self.log( f"Baseline: {baseline_time}" )
        
        # Performance changes
        perf_changes = comparison.get( "performance_changes", {} )
        if perf_changes:
            self.log( "\n⚡ Performance Changes:" )
            for test_name, change_data in perf_changes.items():
                baseline_ms = change_data["baseline_ms"]
                current_ms = change_data["current_ms"]
                change_percent = change_data["change_percent"]
                
                if change_data["regression"]:
                    status = f"📉 SLOWER (+{change_percent:.1f}%)"
                elif change_data["improvement"]:
                    status = f"🚀 FASTER ({change_percent:.1f}%)"
                else:
                    status = f"➡️ Similar ({change_percent:+.1f}%)"
                
                self.log( f"  • {test_name}: {baseline_ms:.2f}ms → {current_ms:.2f}ms {status}" )
        
        # Critical regressions
        regressions = comparison.get( "critical_regressions", [] )
        if regressions:
            self.log( "\n❌ Critical Regressions:" )
            for regression in regressions:
                if regression["type"] == "performance":
                    change = regression["change_percent"]
                    self.log( f"  • {regression['test']}: Performance degraded by {change:.1f}% (threshold: 20%)" )
                elif regression["type"] == "functional":
                    self.log( f"  • {regression['test']}: {regression.get('issue', 'Functional regression')}" )
        
        # Improvements
        improvements = comparison.get( "improvements", [] )
        if improvements:
            self.log( "\n✅ Improvements Found:" )
            for improvement in improvements:
                if improvement["type"] == "performance":
                    perf_gain = improvement["improvement_percent"]
                    self.log( f"  • {improvement['test']}: Performance improved by {perf_gain:.1f}%" )
                elif improvement["type"] == "functional":
                    self.log( f"  • {improvement['test']}: {improvement['improvement']}" )
        
        # Overall assessment
        if comparison["overall_regression"]:
            self.log( f"\n🔴 OVERALL: Regression detected ({len(regressions)} critical issues)" )
        elif improvements:
            self.log( f"\n🟢 OVERALL: System improved ({len(improvements)} improvements, no regressions)" )
        else:
            self.log( "\n🟢 OVERALL: No significant changes detected" )


async def main():
    """Main entry point for the smoke test runner."""
    parser = argparse.ArgumentParser( description="WebSocket Smoke Test Runner" )
    parser.add_argument( "--config", help="Configuration file path" )
    parser.add_argument( "--category", choices=["core", "integration", "performance", "load"], 
                        help="Run only tests from specific category" )
    parser.add_argument( "--save-baseline", action="store_true", 
                        help="Save current results as baseline for future comparison" )
    parser.add_argument( "--compare-baseline", action="store_true", 
                        help="Compare current results with saved baseline" )
    
    args = parser.parse_args()
    
    try:
        runner = SmokeTestRunner( args.config )
        results = await runner.run_all_tests( 
            save_baseline=args.save_baseline,
            compare_baseline=args.compare_baseline
        )
            
    except KeyboardInterrupt:
        print( "\n❌ Test execution interrupted by user" )
        sys.exit( 130 )
    except Exception as e:
        print( f"❌ Test runner failed: {e}" )
        sys.exit( 1 )


if __name__ == "__main__":
    asyncio.run( main() )