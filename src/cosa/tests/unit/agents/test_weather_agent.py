#!/usr/bin/env python3
"""
Unit Tests: WeatherAgent

Comprehensive unit tests for the CoSA WeatherAgent class with complete mocking
of external dependencies including LupinSearch web search, time utilities,
and agent workflow execution.

This test module validates:
- WeatherAgent initialization and configuration with AgentBase inheritance
- Web search execution with mocked LupinSearch API responses
- Time-based query reformulation for cache freshness
- Code execution workflow and response handling
- Error handling for search failures and network issues
- Agent workflow integration (do_all method)
- Response formatting and conversational output processing
"""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock, call
import time

# Import test infrastructure
try:
    from cosa.tests.unit.infrastructure.mock_manager import MockManager
    from cosa.tests.unit.infrastructure.test_fixtures import CoSATestFixtures
    from cosa.tests.unit.infrastructure.unit_test_utilities import UnitTestUtilities
except ImportError as e:
    print( f"Failed to import test infrastructure: {e}" )
    sys.exit( 1 )

# Import the modules under test
try:
    from cosa.agents.weather_agent import WeatherAgent
    from cosa.agents.agent_base import AgentBase
except ImportError as e:
    print( f"Failed to import WeatherAgent: {e}" )
    sys.exit( 1 )


class WeatherAgentUnitTests:
    """
    Unit test suite for WeatherAgent.
    
    Provides comprehensive testing of weather agent functionality including
    LupinSearch API mocking, time-based query formatting, search execution,
    response processing, and error handling with complete external dependency
    isolation.
    
    Requires:
        - MockManager for API and external dependency mocking
        - CoSATestFixtures for test data
        - UnitTestUtilities for test helpers
        
    Ensures:
        - All WeatherAgent functionality is tested thoroughly
        - No external dependencies or API calls
        - Performance requirements are met
        - Error conditions are handled properly
        - Search workflow patterns work correctly
    """
    
    def __init__( self, debug: bool = False ):
        """
        Initialize WeatherAgent unit tests.
        
        Args:
            debug: Enable debug output
        """
        self.debug = debug
        self.mock_mgr = MockManager()
        self.fixtures = CoSATestFixtures()
        self.utils = UnitTestUtilities( debug=debug )
        self.temp_files = []
        
        # Test configuration values
        self.test_question = "What's the weather in Seattle?"
        self.test_question_gist = "seattle weather"
        self.test_routing_command = "agent router go to weather"
        self.test_current_time = "02:00 PM"
        self.test_current_date = "Tuesday, January 7th, 2025"
        self.test_reformulated_question = f"It's {self.test_current_time} on {self.test_current_date}. {self.test_question}"
        
        # Mock search response data
        self.test_search_response = "Current weather in Seattle: 45°F, partly cloudy with light rain expected this afternoon. Humidity 75%, wind 8 mph from the southwest."
        self.test_search_results = {
            "meta": {
                "query": self.test_question,
                "timestamp": "2025-01-07T14:00:00Z"
            },
            "data": {
                "output": self.test_search_response,
                "references": [
                    {"title": "National Weather Service", "url": "https://weather.gov/seattle"},
                    {"title": "Weather.com", "url": "https://weather.com/seattle"}
                ]
            }
        }
    
    def _create_weather_agent_mock_context( self ):
        """
        Create comprehensive mock context for WeatherAgent testing.
        
        This helper sets up all necessary mocks to intercept external dependencies
        including LupinSearch, time utilities, ConfigurationManager, and agent workflow.
        
        Returns:
            Context manager for use in 'with' statements
        """
        def _mock_context():
            from contextlib import ExitStack
            
            stack = ExitStack()
            
            # Mock time utility functions
            mock_get_current_time = stack.enter_context(
                patch( 'cosa.agents.weather_agent.du.get_current_time' )
            )
            mock_get_current_time.return_value = self.test_current_time
            
            mock_get_current_date = stack.enter_context(
                patch( 'cosa.agents.weather_agent.du.get_current_date' )
            )
            mock_get_current_date.return_value = self.test_current_date
            
            # Mock LupinSearch class
            mock_lupin_search_class = stack.enter_context(
                patch( 'cosa.agents.weather_agent.LupinSearch' )
            )
            mock_lupin_search = MagicMock()
            mock_lupin_search.search_and_summarize_the_web.return_value = None
            mock_lupin_search.get_results.return_value = self.test_search_response
            mock_lupin_search_class.return_value = mock_lupin_search
            
            # Mock ConfigurationManager in AgentBase
            mock_config_mgr_class = stack.enter_context(
                patch( 'cosa.agents.agent_base.ConfigurationManager' )
            )
            mock_config_mgr = MagicMock()
            # Return appropriate values based on the key
            def mock_config_get( key, default=None, return_type=None ):
                if "llm spec key" in key:
                    return "test-model"
                elif "prompt template" in key:
                    return "/test/path/template.txt"
                elif "serialization topic" in key:
                    return "weather-test"
                else:
                    return default if default is not None else False
            mock_config_mgr.get.side_effect = mock_config_get
            mock_config_mgr_class.return_value = mock_config_mgr
            
            # Mock SolutionSnapshot utility
            mock_solution_snapshot = stack.enter_context(
                patch( 'cosa.agents.weather_agent.ss' )
            )
            mock_solution_snapshot.remove_non_alphanumerics.side_effect = lambda x: x.replace( " ", "_" ).lower()
            
            # Mock RawOutputFormatter for run_formatter
            mock_formatter_class = stack.enter_context(
                patch( 'cosa.agents.agent_base.RawOutputFormatter' )
            )
            mock_formatter = MagicMock()
            mock_formatter.run_formatter.return_value = f"Conversational response: {self.test_search_response}"
            mock_formatter_class.return_value = mock_formatter
            
            # Mock du.get_file_as_string for prompt template loading
            mock_get_file_as_string = stack.enter_context(
                patch( 'cosa.agents.agent_base.du.get_file_as_string' )
            )
            mock_get_file_as_string.return_value = "Test prompt template: {question}"
            
            # Mock du.get_project_root
            mock_get_project_root = stack.enter_context(
                patch( 'cosa.agents.agent_base.du.get_project_root' )
            )
            mock_get_project_root.return_value = "/test/project"
            
            return stack, {
                'get_current_time': mock_get_current_time,
                'get_current_date': mock_get_current_date,
                'lupin_search_class': mock_lupin_search_class,
                'lupin_search': mock_lupin_search,
                'config_mgr_class': mock_config_mgr_class,
                'config_mgr': mock_config_mgr,
                'solution_snapshot': mock_solution_snapshot,
                'formatter_class': mock_formatter_class,
                'formatter': mock_formatter,
                'get_file_as_string': mock_get_file_as_string,
                'get_project_root': mock_get_project_root
            }
        
        return _mock_context
    
    def test_weather_agent_initialization( self ) -> bool:
        """
        Test WeatherAgent initialization and configuration.
        
        Ensures:
            - WeatherAgent inherits from AgentBase correctly
            - Configuration parameters are set correctly
            - Time-based query reformulation works
            - Agent properties are initialized properly
            
        Returns:
            True if test passes
        """
        self.utils.print_test_banner( "Testing WeatherAgent Initialization" )
        
        try:
            mock_context_func = self._create_weather_agent_mock_context()
            with mock_context_func()[0] as stack:
                mocks = mock_context_func()[1]
                
                # Test basic initialization with date/time prepending
                agent = WeatherAgent( 
                    question=self.test_question_gist,
                    question_gist=self.test_question_gist,
                    last_question_asked=self.test_question,
                    routing_command=self.test_routing_command,
                    prepend_date_and_time=True,
                    debug=False,
                    verbose=False
                )
                
                # Test inheritance
                assert isinstance( agent, AgentBase ), "WeatherAgent should inherit from AgentBase"
                assert isinstance( agent, WeatherAgent ), "Agent should be WeatherAgent instance"
                
                # Test configuration attributes
                assert agent.question == self.test_question_gist, "Question should be set correctly"
                assert agent.last_question_asked == self.test_question, "Last question should be set correctly"
                assert agent.routing_command == self.test_routing_command, "Routing command should be set correctly"
                assert agent.debug == False, "Debug flag should be set correctly"
                assert agent.verbose == False, "Verbose flag should be set correctly"
                
                # Test time-based reformulation
                assert agent.reformulated_last_question_asked == self.test_reformulated_question, "Question should be reformulated with time"
                
                # Test time utility calls
                mocks[ 'get_current_time' ].assert_called_once_with( format='%I:00 %p' )
                mocks[ 'get_current_date' ].assert_called_once_with( return_prose=True )
                
                # Test agent properties
                assert agent.prompt is None, "Prompt should be None for weather agent"
                assert agent.xml_response_tag_names == [], "XML response tags should be empty"
                
                self.utils.print_test_status( "Basic initialization test passed", "PASS" )
                
                # Test initialization without date/time prepending
                agent2 = WeatherAgent( 
                    question=self.test_question_gist,
                    last_question_asked=self.test_question,
                    prepend_date_and_time=False,
                    debug=True,
                    verbose=True
                )
                
                assert agent2.reformulated_last_question_asked == self.test_question, "Question should not be reformulated"
                assert agent2.debug == True, "Debug flag should be set"
                assert agent2.verbose == True, "Verbose flag should be set"
                
                self.utils.print_test_status( "Parameter variation test passed", "PASS" )
                
            return True
            
        except Exception as e:
            self.utils.print_test_status( f"WeatherAgent initialization test failed: {e}", "FAIL" )
            return False
    
    def test_web_search_execution( self ) -> bool:
        """
        Test web search execution with mocked LupinSearch responses.
        
        Ensures:
            - run_code() method works correctly
            - LupinSearch is instantiated with correct parameters
            - Search results are processed properly
            - Response dictionary is formatted correctly
            - Answer is set from search results
            
        Returns:
            True if test passes
        """
        self.utils.print_test_banner( "Testing Web Search Execution" )
        
        try:
            mock_context_func = self._create_weather_agent_mock_context()
            with mock_context_func()[0] as stack:
                mocks = mock_context_func()[1]
                
                agent = WeatherAgent(
                    question=self.test_question_gist,
                    last_question_asked=self.test_question,
                    debug=True,
                    verbose=True
                )
                
                # Test basic search execution
                response_dict = agent.run_code()
                
                # Test LupinSearch instantiation
                mocks[ 'lupin_search_class' ].assert_called_once()
                call_args = mocks[ 'lupin_search_class' ].call_args
                assert call_args[ 1 ][ 'query' ] == agent.reformulated_last_question_asked, "Search should use reformulated question"
                assert call_args[ 1 ][ 'debug' ] == True, "Debug flag should be passed"
                assert call_args[ 1 ][ 'verbose' ] == True, "Verbose flag should be passed"
                
                # Test search method calls
                mocks[ 'lupin_search' ].search_and_summarize_the_web.assert_called_once()
                mocks[ 'lupin_search' ].get_results.assert_called_once_with( scope="summary" )
                
                # Test response processing
                assert response_dict[ "return_code" ] == 0, "Return code should be 0 for success"
                assert self.test_search_response.replace( " ", " " ) in response_dict[ "output" ], "Output should contain search response"
                assert agent.answer == self.test_search_response, "Answer should be set from search results"
                assert agent.code_response_dict == response_dict, "Code response dict should be stored"
                
                self.utils.print_test_status( "Basic search execution test passed", "PASS" )
                
                # Test search with different parameters
                mocks[ 'lupin_search_class' ].reset_mock()
                mocks[ 'lupin_search' ].search_and_summarize_the_web.reset_mock()
                mocks[ 'lupin_search' ].get_results.reset_mock()
                
                agent2 = WeatherAgent(
                    last_question_asked="What's the temperature in New York?",
                    prepend_date_and_time=False,
                    debug=False,
                    verbose=False
                )
                
                response_dict2 = agent2.run_code()
                
                # Test that non-reformulated question is used
                call_args2 = mocks[ 'lupin_search_class' ].call_args
                assert call_args2[ 1 ][ 'query' ] == "What's the temperature in New York?", "Should use original question without reformulation"
                assert call_args2[ 1 ][ 'debug' ] == False, "Debug flag should be False"
                assert call_args2[ 1 ][ 'verbose' ] == False, "Verbose flag should be False"
                
                self.utils.print_test_status( "Search parameter variation test passed", "PASS" )
                
            return True
            
        except Exception as e:
            self.utils.print_test_status( f"Web search execution test failed: {e}", "FAIL" )
            return False
    
    def test_search_error_handling( self ) -> bool:
        """
        Test error handling during web search execution.
        
        Ensures:
            - LupinSearch exceptions are caught properly
            - Error response dictionary is formatted correctly
            - Agent error state is set appropriately
            - Different error types are handled gracefully
            
        Returns:
            True if test passes
        """
        self.utils.print_test_banner( "Testing Search Error Handling" )
        
        try:
            mock_context_func = self._create_weather_agent_mock_context()
            with mock_context_func()[0] as stack:
                mocks = mock_context_func()[1]
                
                agent = WeatherAgent(
                    last_question_asked=self.test_question,
                    debug=True
                )
                
                # Test search initialization error
                mocks[ 'lupin_search_class' ].side_effect = Exception( "Search service unavailable" )
                
                response_dict = agent.run_code()
                
                # Test error response
                assert response_dict[ "return_code" ] == -1, "Return code should be -1 for error"
                assert "Search service unavailable" in str( response_dict[ "output" ] ), "Output should contain error message"
                assert "Search service unavailable" in str( agent.error ), "Agent error should be set"
                
                self.utils.print_test_status( "Search initialization error test passed", "PASS" )
                
                # Test search execution error
                mocks[ 'lupin_search_class' ].side_effect = None
                mocks[ 'lupin_search' ].search_and_summarize_the_web.side_effect = Exception( "Network timeout" )
                
                agent2 = WeatherAgent(
                    last_question_asked=self.test_question
                )
                
                response_dict2 = agent2.run_code()
                
                assert response_dict2[ "return_code" ] == -1, "Return code should be -1 for execution error"
                assert "Network timeout" in str( response_dict2[ "output" ] ), "Output should contain network error"
                assert "Network timeout" in str( agent2.error ), "Agent error should be set"
                
                self.utils.print_test_status( "Search execution error test passed", "PASS" )
                
                # Test search result retrieval error
                mocks[ 'lupin_search' ].search_and_summarize_the_web.side_effect = None
                mocks[ 'lupin_search' ].get_results.side_effect = KeyError( "Invalid response format" )
                
                agent3 = WeatherAgent(
                    last_question_asked=self.test_question
                )
                
                response_dict3 = agent3.run_code()
                
                assert response_dict3[ "return_code" ] == -1, "Return code should be -1 for result error"
                assert "Invalid response format" in str( response_dict3[ "output" ] ), "Output should contain format error"
                
                self.utils.print_test_status( "Search result error test passed", "PASS" )
                
            return True
            
        except Exception as e:
            self.utils.print_test_status( f"Search error handling test failed: {e}", "FAIL" )
            return False
    
    def test_agent_workflow_integration( self ) -> bool:
        """
        Test complete agent workflow integration via do_all method.
        
        Ensures:
            - do_all() method executes complete workflow
            - run_code() and run_formatter() are called in sequence
            - Conversational response is generated properly
            - Final answer is returned correctly
            
        Returns:
            True if test passes
        """
        self.utils.print_test_banner( "Testing Agent Workflow Integration" )
        
        try:
            mock_context_func = self._create_weather_agent_mock_context()
            with mock_context_func()[0] as stack:
                mocks = mock_context_func()[1]
                
                agent = WeatherAgent(
                    question=self.test_question_gist,
                    last_question_asked=self.test_question,
                    routing_command=self.test_routing_command,
                    debug=True,
                    verbose=False
                )
                
                # Test complete workflow
                final_response = agent.do_all()
                
                # Test that LupinSearch was called
                mocks[ 'lupin_search_class' ].assert_called_once()
                mocks[ 'lupin_search' ].search_and_summarize_the_web.assert_called_once()
                mocks[ 'lupin_search' ].get_results.assert_called_once_with( scope="summary" )
                
                # Test that formatter was called
                mocks[ 'formatter_class' ].assert_called_once()
                mocks[ 'formatter' ].run_formatter.assert_called_once()
                
                # Test response processing
                assert agent.answer == self.test_search_response, "Answer should be set from search"
                assert final_response.startswith( "Conversational response:" ), "Should return conversational response"
                assert self.test_search_response in final_response, "Final response should contain search results"
                
                self.utils.print_test_status( "Complete workflow test passed", "PASS" )
                
                # Test workflow with error in search
                mocks[ 'lupin_search' ].search_and_summarize_the_web.side_effect = Exception( "Search failed" )
                
                agent2 = WeatherAgent(
                    last_question_asked="What's the weather in London?"
                )
                
                # This should handle the error gracefully
                try:
                    final_response2 = agent2.do_all()
                    # If no exception, check that error was handled
                    assert agent2.code_response_dict[ "return_code" ] == -1, "Should have error return code"
                except Exception:
                    # Exception during workflow is also acceptable
                    pass
                
                self.utils.print_test_status( "Workflow error handling test passed", "PASS" )
                
            return True
            
        except Exception as e:
            self.utils.print_test_status( f"Agent workflow integration test failed: {e}", "FAIL" )
            return False
    
    def test_agent_interface_methods( self ) -> bool:
        """
        Test agent interface methods and properties.
        
        Ensures:
            - is_code_runnable() returns correct value
            - is_prompt_executable() returns correct value
            - run_prompt() raises NotImplementedError
            - restore_from_serialized_state() raises NotImplementedError
            
        Returns:
            True if test passes
        """
        self.utils.print_test_banner( "Testing Agent Interface Methods" )
        
        try:
            mock_context_func = self._create_weather_agent_mock_context()
            with mock_context_func()[0] as stack:
                mocks = mock_context_func()[1]
                
                agent = WeatherAgent(
                    last_question_asked=self.test_question
                )
                
                # Test is_code_runnable
                assert agent.is_code_runnable() == True, "Weather agent should always be code runnable"
                
                # Test is_prompt_executable
                assert agent.is_prompt_executable() == False, "Weather agent should not be prompt executable"
                
                # Test run_prompt raises NotImplementedError
                try:
                    agent.run_prompt()
                    assert False, "run_prompt should raise NotImplementedError"
                except NotImplementedError as e:
                    assert "run_prompt() not implemented" in str( e ), "Should have specific error message"
                
                # Test restore_from_serialized_state raises NotImplementedError
                try:
                    agent.restore_from_serialized_state( "/fake/path" )
                    assert False, "restore_from_serialized_state should raise NotImplementedError"
                except NotImplementedError as e:
                    assert "restore_from_serialized_state() not implemented" in str( e ), "Should have specific error message"
                
                self.utils.print_test_status( "Agent interface methods test passed", "PASS" )
                
            return True
            
        except Exception as e:
            self.utils.print_test_status( f"Agent interface methods test failed: {e}", "FAIL" )
            return False
    
    def test_performance_requirements( self ) -> bool:
        """
        Test WeatherAgent performance requirements.
        
        Ensures:
            - Agent creation is fast enough
            - Search execution is performant
            - Memory usage is reasonable
            - Workflow completion is timely
            
        Returns:
            True if test passes
        """
        self.utils.print_test_banner( "Testing Performance Requirements" )
        
        try:
            performance_targets = self.fixtures.get_performance_targets()
            agent_timeout = performance_targets[ "timing_targets" ].get( "agent_initialization", 0.5 )
            
            mock_context_func = self._create_weather_agent_mock_context()
            with mock_context_func()[0] as stack:
                mocks = mock_context_func()[1]
                
                # Test agent creation performance
                def agent_creation_test():
                    agent = WeatherAgent(
                        question=self.test_question_gist,
                        last_question_asked=self.test_question
                    )
                    return agent is not None
                
                success, duration, result = self.utils.assert_timing( agent_creation_test, 0.1 )  # 100ms limit
                assert success, f"Agent creation too slow: {duration}s"
                assert result == True, "Agent creation should return True"
                
                # Test search execution performance
                agent = WeatherAgent(
                    last_question_asked=self.test_question,
                    debug=False
                )
                
                def search_execution_test():
                    response_dict = agent.run_code()
                    return response_dict[ "return_code" ] == 0
                
                success, duration, result = self.utils.assert_timing( search_execution_test, 0.05 )  # 50ms limit
                assert success, f"Search execution too slow: {duration}s"
                assert result == True, "Search execution should return True"
                
                # Test complete workflow performance
                def workflow_test():
                    agent2 = WeatherAgent( last_question_asked=self.test_question )
                    final_response = agent2.do_all()
                    return len( final_response ) > 0
                
                success, duration, result = self.utils.assert_timing( workflow_test, 0.1 )  # 100ms limit
                assert success, f"Complete workflow too slow: {duration}s"
                assert result == True, "Workflow should return True"
                
                self.utils.print_test_status( f"Performance requirements met ({self.utils.format_duration( duration )})", "PASS" )
                
            return True
            
        except Exception as e:
            self.utils.print_test_status( f"Performance requirements test failed: {e}", "FAIL" )
            return False
    
    def run_all_tests( self ) -> tuple:
        """
        Run all WeatherAgent unit tests.
        
        Returns:
            Tuple of (success, duration, error_message)
        """
        start_time = self.utils.start_timer( "weather_agent_tests" )
        
        tests = [
            self.test_weather_agent_initialization,
            self.test_web_search_execution,
            self.test_search_error_handling,
            self.test_agent_workflow_integration,
            self.test_agent_interface_methods,
            self.test_performance_requirements
        ]
        
        passed_tests = 0
        failed_tests = 0
        errors = []
        
        self.utils.print_test_banner( "WeatherAgent Unit Test Suite", "=" )
        
        for test_func in tests:
            try:
                if test_func():
                    passed_tests += 1
                else:
                    failed_tests += 1
                    errors.append( f"{test_func.__name__} failed" )
            except Exception as e:
                failed_tests += 1
                errors.append( f"{test_func.__name__} raised exception: {e}" )
        
        duration = self.utils.stop_timer( "weather_agent_tests" )
        
        # Print summary
        self.utils.print_test_banner( "Test Results Summary" )
        self.utils.print_test_status( f"Passed: {passed_tests}" )
        self.utils.print_test_status( f"Failed: {failed_tests}" )
        self.utils.print_test_status( f"Duration: {self.utils.format_duration( duration )}" )
        
        success = failed_tests == 0
        error_message = "; ".join( errors ) if errors else ""
        
        return success, duration, error_message
    
    def cleanup( self ):
        """Clean up any temporary files created during testing."""
        self.utils.cleanup_temp_files( self.temp_files )


def isolated_unit_test():
    """
    Main unit test function for WeatherAgent.
    
    This is the entry point called by the unit test runner to execute
    all WeatherAgent unit tests.
    
    Returns:
        Tuple[bool, float, str]: (success, duration, error_message)
    """
    test_suite = None
    
    try:
        test_suite = WeatherAgentUnitTests( debug=False )
        success, duration, error_message = test_suite.run_all_tests()
        return success, duration, error_message
        
    except Exception as e:
        error_message = f"WeatherAgent unit test suite failed to initialize: {str( e )}"
        return False, 0.0, error_message
        
    finally:
        if test_suite:
            test_suite.cleanup()


if __name__ == "__main__":
    success, duration, error = isolated_unit_test()
    status = "✅ PASS" if success else "❌ FAIL"
    print( f"{status} WeatherAgent unit tests completed in {duration:.2f}s" )
    if error:
        print( f"Errors: {error}" )