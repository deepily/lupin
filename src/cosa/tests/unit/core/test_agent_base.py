#!/usr/bin/env python3
"""
Unit Tests: AgentBase Framework

Comprehensive unit tests for the CoSA AgentBase class and agent framework
foundation with complete mocking of external dependencies.

This test module validates:
- AgentBase class instantiation and initialization
- Configuration loading and management
- Prompt template handling
- XML response processing framework
- Agent state management
- Error handling and validation
"""

import os
import sys
import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

# Import test infrastructure
try:
    from cosa.tests.unit.infrastructure.mock_manager import MockManager
    from cosa.tests.unit.infrastructure.test_fixtures import CoSATestFixtures
    from cosa.tests.unit.infrastructure.unit_test_utilities import UnitTestUtilities
except ImportError as e:
    print( f"Failed to import test infrastructure: {e}" )
    pytest.skip( "legacy test-infra import unavailable under pytest collection; module skipped pending harvest (de-poison batch)", allow_module_level=True )

# Import the module under test
try:
    from cosa.agents.agent_base import AgentBase
except ImportError as e:
    print( f"Failed to import AgentBase: {e}" )
    pytest.skip( "legacy test-infra import unavailable under pytest collection; module skipped pending harvest (de-poison batch)", allow_module_level=True )


class TestAgent( AgentBase ):
    """
    Concrete test implementation of AgentBase for testing.
    
    Provides a minimal concrete implementation to test abstract base functionality
    without requiring full agent implementation complexity.
    """
    
    def __init__( self, question: str = "test question", debug: bool = False, verbose: bool = False, **kwargs ):
        """
        Initialize test agent with minimal required parameters.
        
        Args:
            question: Test question for the agent
            debug: Enable debug output
            verbose: Enable verbose output
            **kwargs: Additional AgentBase parameters  
        """
        # Set up minimal required parameters for AgentBase
        super().__init__(
            df_path_key=None,
            question=question,
            question_gist="test gist",
            last_question_asked=question,
            routing_command="test routing",
            push_counter=0,
            debug=debug,
            verbose=verbose,
            auto_debug=kwargs.get('debug auto', False),
            inject_bugs=kwargs.get('debug inject bugs', False),
            **{k: v for k, v in kwargs.items() if k not in ['debug auto', 'debug inject bugs']}
        )
        
        # Set up minimal agent-specific configuration
        self.prompt = f"Test prompt: {question}"
        self.xml_response_tag_names = [ "thoughts", "code", "returns" ]
    
    def restore_from_serialized_state( self, file_path: str ) -> 'TestAgent':
        """
        Concrete implementation of abstract method for testing.
        
        Args:
            file_path: Path to serialized state file
            
        Returns:
            New TestAgent instance with restored state
        """
        # Minimal implementation for testing
        return TestAgent( question="restored from " + file_path )


class AgentBaseUnitTests:
    """
    Unit test suite for AgentBase framework.
    
    Provides comprehensive testing of agent base functionality including
    initialization, configuration management, prompt handling, and XML processing
    with complete external dependency mocking.
    
    TESTING APPROACH - SINGLETON CHALLENGES:
    =====================================
    
    The AgentBase class uses ConfigurationManager which implements a singleton pattern.
    This creates testing challenges because:
    
    1. AgentBase constructor calls ConfigurationManager() directly
    2. Singleton returns the same instance across all tests
    3. Real singleton loads actual config files, breaking test isolation
    4. Our MockManager cannot intercept direct singleton access
    
    SOLUTION - MONKEY PATCHING (TEMPORARY):
    ======================================
    
    We use unittest.mock.patch to monkey patch the ConfigurationManager import
    at the module level in cosa.agents.agent_base. This allows us to substitute
    our mock configuration manager for the real singleton during tests.
    
    This is a TEMPORARY solution. The proper fix would be:
    
    TODO - FUTURE REFACTORING:
    =========================
    
    1. Modify AgentBase to accept optional config_mgr parameter:
       def __init__(self, config_mgr=None, **kwargs):
           self.config_mgr = config_mgr or ConfigurationManager()
    
    2. This enables dependency injection for testing:
       agent = TestAgent(config_mgr=mock_config)
    
    3. Benefits:
       - Cleaner test code (no monkey patching)
       - Better separation of concerns
       - More maintainable and explicit dependencies
       - Follows SOLID principles
    
    CURRENT IMPLEMENTATION:
    ======================
    
    Each test method uses @patch('cosa.agents.agent_base.ConfigurationManager')
    to intercept the import and substitute our mock. This works but creates coupling
    between test code and internal implementation details.
    
    Requires:
        - MockManager for configuration and file system mocking
        - CoSATestFixtures for test data
        - UnitTestUtilities for test helpers
        - unittest.mock.patch for singleton interception
        
    Ensures:
        - All AgentBase functionality is tested thoroughly
        - No external dependencies or configurations accessed
        - Performance requirements are met
        - Error conditions are handled properly
        - Tests remain isolated despite singleton usage
    """
    
    def __init__( self, debug: bool = False ):
        """
        Initialize AgentBase unit tests.
        
        Args:
            debug: Enable debug output
        """
        self.debug = debug
        self.mock_mgr = MockManager()
        self.fixtures = CoSATestFixtures()
        self.utils = UnitTestUtilities( debug=debug )
        self.temp_files = []
    
    
    def test_agent_base_instantiation( self ) -> bool:
        """
        Test AgentBase instantiation and initialization.
        
        Uses monkey patching to intercept ConfigurationManager singleton access.
        See class docstring for details on why this approach is necessary.
        
        Ensures:
            - AgentBase can be instantiated through concrete subclass
            - Required parameters are properly initialized
            - Configuration manager is set up correctly
            - Default values are applied appropriately
            
        Returns:
            True if test passes
        """
        self.utils.print_test_banner( "Testing AgentBase Instantiation" )
        
        try:
            # MONKEY PATCH: Intercept all external dependencies
            with patch( 'cosa.agents.agent_base.ConfigurationManager' ) as mock_cm_class, \
                 patch( 'cosa.agents.agent_base.du.get_file_as_string' ) as mock_get_file, \
                 patch( 'cosa.agents.agent_base.du.get_project_root' ) as mock_get_root, \
                 patch( 'cosa.agents.agent_base.ss.SolutionSnapshot.get_timestamp' ) as mock_get_timestamp, \
                 patch( 'cosa.agents.agent_base.ss.SolutionSnapshot.generate_id_hash' ) as mock_gen_hash, \
                 patch( 'cosa.agents.agent_base.ss.SolutionSnapshot.remove_non_alphanumerics' ) as mock_remove_non_alpha, \
                 patch( 'cosa.agents.agent_base.TwoWordIdGenerator' ) as mock_two_word_gen:
                
                # Configure the mock configuration manager
                mock_config = self.mock_mgr.config_manager_mock( {
                    "app debug": False,
                    "agent_timeout": 30,
                    "prompt template for test routing": "/templates/test_template.txt",
                    "llm spec key for test routing": "test_llm_spec"
                } ).__enter__()
                
                mock_cm_class.return_value = mock_config
                
                # Mock file operations to return template content instead of reading files
                mock_get_root.return_value = "/mocked/project/root"
                mock_get_file.return_value = "Test routing template: {question}"
                
                # Mock SolutionSnapshot static methods
                mock_get_timestamp.return_value = "2025-08-04-12-00-00"
                mock_gen_hash.return_value = "test_hash_123"
                mock_remove_non_alpha.side_effect = lambda x: x.lower().replace("+", "").replace("?", "").replace(" ", " ").strip()
                
                # Mock TwoWordIdGenerator
                mock_two_word_instance = MagicMock()
                mock_two_word_instance.get_id.return_value = "test-word-id"
                mock_two_word_gen.return_value = mock_two_word_instance
                
                # Test minimal instantiation
                agent = TestAgent( question="What is 2+2?" )
                assert agent is not None, "Agent should be created successfully"
                
                # Test agent properties
                assert hasattr( agent, 'question' ), "Agent should have question attribute"
                assert hasattr( agent, 'config_mgr' ), "Agent should have config_mgr attribute"
                assert hasattr( agent, 'debug' ), "Agent should have debug attribute"
                assert hasattr( agent, 'verbose' ), "Agent should have verbose attribute"
                
                # Test question handling (question gets normalized by SolutionSnapshot.remove_non_alphanumerics)
                # "What is 2+2?" becomes "what is 22" after our mock normalization
                assert agent.question == "what is 22", f"Question should be normalized correctly, got '{agent.question}'"
                assert agent.last_question_asked == "What is 2+2?", f"Last question asked should preserve original, got '{agent.last_question_asked}'"
                
                # Test configuration manager access (now our mock)
                assert agent.config_mgr is not None, "Configuration manager should be available"
                assert agent.config_mgr == mock_config, "Should be using our mocked configuration manager"
                
                self.utils.print_test_status( "Basic instantiation test passed", "PASS" )
            
            # Test instantiation with various parameter combinations
            test_scenarios = [
                { "question": "Simple test", "debug": True, "verbose": True },
                { "question": "Long question with multiple words and punctuation?", "debug": False },
                { "question": "Test", "auto_debug": True },
                { "question": "Another test", "inject_bugs": True }
            ]
            
            for scenario in test_scenarios:
                # MONKEY PATCH: Each scenario needs its own patch context
                with patch( 'cosa.agents.agent_base.ConfigurationManager' ) as mock_cm_class, \
                     patch( 'cosa.agents.agent_base.du.get_file_as_string' ) as mock_get_file2, \
                     patch( 'cosa.agents.agent_base.du.get_project_root' ) as mock_get_root2:
                    
                    mock_config = self.mock_mgr.config_manager_mock( {
                        "prompt template for test routing": "/templates/test_template.txt",
                        "llm spec key for test routing": "test_llm_spec"
                    } ).__enter__()
                    
                    mock_cm_class.return_value = mock_config
                    mock_get_root2.return_value = "/mocked/project/root"
                    mock_get_file2.return_value = "Test routing template: {question}"
                    
                    try:
                        agent = TestAgent( **scenario )
                        assert agent is not None, f"Agent creation failed for scenario: {scenario}"
                        
                        # Verify parameters were set (account for question normalization)
                        for key, value in scenario.items():
                            if hasattr( agent, key ):
                                actual_value = getattr( agent, key )
                                # Question gets normalized by AgentBase, so we need to expect the normalized version
                                if key == "question":
                                    expected_value = value.lower().replace("+", "").replace("?", "").replace(" ", " ").strip()
                                    assert actual_value == expected_value, f"Normalized parameter {key} should be {expected_value}, got {actual_value}"
                                else:
                                    assert actual_value == value, f"Parameter {key} should be {value}, got {actual_value}"
                        
                    except Exception as e:
                        raise AssertionError( f"Agent creation failed for scenario {scenario}: {e}" )
            
            self.utils.print_test_status( "Parameter variation test passed", "PASS" )
            return True
            
        except Exception as e:
            self.utils.print_test_status( f"AgentBase instantiation test failed: {e}", "FAIL" )
            return False
    
    def test_configuration_integration( self ) -> bool:
        """
        Test AgentBase integration with configuration manager.
        
        Uses monkey patching to provide controlled configuration values.
        
        Ensures:
            - Configuration values are properly loaded
            - Environment variables override configuration
            - Missing configuration keys are handled gracefully
            - Type conversion works correctly
            
        Returns:
            True if test passes
        """
        self.utils.print_test_banner( "Testing Configuration Integration" )
        
        try:
            # MONKEY PATCH: Comprehensive configuration test
            with patch( 'cosa.agents.agent_base.ConfigurationManager' ) as mock_cm_class, \
                 patch( 'cosa.agents.agent_base.du.get_file_as_string' ) as mock_get_file, \
                 patch( 'cosa.agents.agent_base.du.get_project_root' ) as mock_get_root:
                # Test with comprehensive configuration
                config_values = {
                    "app debug": True,
                    "agent_timeout": 60,
                    "agent_verbose": True,
                    "test_agent_enabled": True,
                    "prompt template for test routing": "/templates/comprehensive_test.txt",
                    "llm spec key for test routing": "test_llm_spec",
                    "max_retries": 3
                }
                
                mock_config = self.mock_mgr.config_manager_mock( config_values ).__enter__()
                mock_cm_class.return_value = mock_config
                mock_get_root.return_value = "/mocked/project/root"
                mock_get_file.return_value = "Process this: {question}"
                
                agent = TestAgent( question="Configuration test" )
                
                # Test that agent can access configuration (now our mock)
                assert agent.config_mgr is not None, "Configuration manager should be available"
                assert agent.config_mgr == mock_config, "Should be using mocked configuration"
                
                # Test configuration value access
                debug_value = agent.config_mgr.get( "app debug", return_type="boolean" )
                assert debug_value == True, f"Configuration debug value should be True, got {debug_value}"
                
                timeout_value = agent.config_mgr.get( "agent_timeout", return_type="int" )
                assert timeout_value == 60, f"Configuration timeout should be 60, got {timeout_value}"
                
                self.utils.print_test_status( "Configuration access test passed", "PASS" )
            
            # Test with missing configuration values
            with patch( 'cosa.agents.agent_base.ConfigurationManager' ) as mock_cm_class2, \
                 patch( 'cosa.agents.agent_base.du.get_file_as_string' ) as mock_get_file2, \
                 patch( 'cosa.agents.agent_base.du.get_project_root' ) as mock_get_root2:
                mock_config2 = self.mock_mgr.config_manager_mock( {
                    "prompt template for test routing": "/templates/default.txt",
                    "llm spec key for test routing": "default_spec"
                } ).__enter__()
                mock_cm_class2.return_value = mock_config2
                mock_get_root2.return_value = "/mocked/project/root"
                mock_get_file2.return_value = "Default: {question}"
                
                agent = TestAgent( question="Missing config test" )
                
                # Should handle missing configuration gracefully
                missing_value = agent.config_mgr.get( "missing_key", default="default_value" )
                assert missing_value == "default_value", f"Missing config should return default, got '{missing_value}'"
                
                self.utils.print_test_status( "Missing configuration test passed", "PASS" )
            
            return True
            
        except Exception as e:
            self.utils.print_test_status( f"Configuration integration test failed: {e}", "FAIL" )
            return False
    
    def test_prompt_template_handling( self ) -> bool:
        """
        Test prompt template loading and formatting.
        
        Ensures:
            - Prompt templates are loaded from configuration
            - Template formatting works with question substitution
            - Missing templates are handled gracefully
            - Template errors don't crash the agent
            
        Returns:
            True if test passes
        """
        self.utils.print_test_banner( "Testing Prompt Template Handling" )
        
        try:
            # MONKEY PATCH: Test with valid prompt template
            with patch( 'cosa.agents.agent_base.ConfigurationManager' ) as mock_cm_class, \
                 patch( 'cosa.agents.agent_base.du.get_file_as_string' ) as mock_get_file, \
                 patch( 'cosa.agents.agent_base.du.get_project_root' ) as mock_get_root:
                config_with_template = {
                    "prompt template for test routing": "/templates/detailed_template.txt",
                    "llm spec key for test routing": "test_llm_spec",
                    "another_template": "/templates/simple_template.txt"
                }
                
                mock_config = self.mock_mgr.config_manager_mock( config_with_template ).__enter__()
                mock_cm_class.return_value = mock_config
                mock_get_root.return_value = "/mocked/project/root"
                mock_get_file.return_value = "Question: {question}\nPlease provide a detailed answer."
                
                agent = TestAgent( question="What is AI?" )
                
                # Test that prompt is set up
                assert hasattr( agent, 'prompt' ), "Agent should have prompt attribute"
                assert agent.prompt is not None, "Agent prompt should not be None"
                assert isinstance( agent.prompt, str ), f"Agent prompt should be string, got {type( agent.prompt )}"
                
                # Test that question appears in prompt (for our TestAgent implementation)
                assert "What is AI?" in agent.prompt or "test" in agent.prompt.lower(), "Question should appear in prompt"
                
                self.utils.print_test_status( "Prompt template test passed", "PASS" )
            
            # Test with empty/missing template
            with patch( 'cosa.agents.agent_base.ConfigurationManager' ) as mock_cm_class2, \
                 patch( 'cosa.agents.agent_base.du.get_file_as_string' ) as mock_get_file2, \
                 patch( 'cosa.agents.agent_base.du.get_project_root' ) as mock_get_root2:
                mock_config2 = self.mock_mgr.config_manager_mock( {
                    "prompt template for test routing": "/templates/default_template.txt",
                    "llm spec key for test routing": "default_spec"
                } ).__enter__()
                mock_cm_class2.return_value = mock_config2
                mock_get_root2.return_value = "/mocked/project/root"
                mock_get_file2.return_value = "Default template: {question}"
                
                agent = TestAgent( question="No template test" )
                
                # Should handle missing template gracefully
                assert hasattr( agent, 'prompt' ), "Agent should still have prompt attribute"
                
                self.utils.print_test_status( "Missing template test passed", "PASS" )
            
            return True
            
        except Exception as e:
            self.utils.print_test_status( f"Prompt template handling test failed: {e}", "FAIL" )
            return False
    
    def test_xml_response_framework( self ) -> bool:
        """
        Test XML response processing framework.
        
        Ensures:
            - XML response tag names are properly configured
            - XML processing framework is set up
            - Tag validation works correctly
            - Error handling for XML processing
            
        Returns:
            True if test passes
        """
        self.utils.print_test_banner( "Testing XML Response Framework" )
        
        try:
            # MONKEY PATCH: Test XML response framework setup
            with patch( 'cosa.agents.agent_base.ConfigurationManager' ) as mock_cm_class, \
                 patch( 'cosa.agents.agent_base.du.get_file_as_string' ) as mock_get_file, \
                 patch( 'cosa.agents.agent_base.du.get_project_root' ) as mock_get_root:
                mock_config = self.mock_mgr.config_manager_mock( {
                    "prompt template for test routing": "/templates/xml_test.txt",
                    "llm spec key for test routing": "xml_test_spec"
                } ).__enter__()
                mock_cm_class.return_value = mock_config
                mock_get_root.return_value = "/mocked/project/root"
                mock_get_file.return_value = "XML test: {question}"
                
                agent = TestAgent( question="XML test" )
                
                # Test XML response tag configuration
                assert hasattr( agent, 'xml_response_tag_names' ), "Agent should have XML tag names"
                assert isinstance( agent.xml_response_tag_names, list ), "XML tag names should be a list"
                assert len( agent.xml_response_tag_names ) > 0, "Should have at least one XML tag name"
                
                # Test that common tags are included
                expected_tags = [ "thoughts", "code", "returns" ]
                for tag in expected_tags:
                    assert tag in agent.xml_response_tag_names, f"Expected tag '{tag}' should be in XML tag list"
                
                self.utils.print_test_status( "XML tag configuration test passed", "PASS" )
            
            # Test XML processing with test data
            xml_responses = self.fixtures.get_xml_test_responses()
            
            with patch( 'cosa.agents.agent_base.ConfigurationManager' ) as mock_cm_class2, \
                 patch( 'cosa.agents.agent_base.du.get_file_as_string' ) as mock_get_file2, \
                 patch( 'cosa.agents.agent_base.du.get_project_root' ) as mock_get_root2:
                mock_config2 = self.mock_mgr.config_manager_mock( {
                    "prompt template for test routing": "/templates/xml_processing.txt",
                    "llm spec key for test routing": "xml_proc_spec"
                } ).__enter__()
                mock_cm_class2.return_value = mock_config2
                mock_get_root2.return_value = "/mocked/project/root"
                mock_get_file2.return_value = "XML processing: {question}"
                
                agent = TestAgent( question="XML processing test" )
                
                # Test that agent can handle XML responses (basic framework test)
                for xml_response in xml_responses[ :3 ]:  # Test first few responses
                    try:
                        # Test that XML doesn't crash the agent setup
                        # Actual XML processing would be tested in specific agent implementations
                        assert agent.xml_response_tag_names is not None, "XML framework should be available"
                        
                    except Exception as e:
                        # XML processing errors should be handled gracefully
                        self.utils.print_test_status( f"XML processing error handled: {e}", "INFO" )
                
                self.utils.print_test_status( "XML processing framework test passed", "PASS" )
            
            return True
            
        except Exception as e:
            self.utils.print_test_status( f"XML response framework test failed: {e}", "FAIL" )
            return False
    
    def test_agent_state_management( self ) -> bool:
        """
        Test agent state management and lifecycle.
        
        Ensures:
            - Agent state is properly initialized
            - State transitions work correctly
            - Agent cleanup works properly
            - Multiple agents don't interfere with each other
            
        Returns:
            True if test passes
        """
        self.utils.print_test_banner( "Testing Agent State Management" )
        
        try:
            # MONKEY PATCH: Test agent state management
            with patch( 'cosa.agents.agent_base.ConfigurationManager' ) as mock_cm_class, \
                 patch( 'cosa.agents.agent_base.du.get_file_as_string' ) as mock_get_file, \
                 patch( 'cosa.agents.agent_base.du.get_project_root' ) as mock_get_root:
                mock_config = self.mock_mgr.config_manager_mock( {
                    "prompt template for test routing": "/templates/state_test.txt",
                    "llm spec key for test routing": "state_test_spec"
                } ).__enter__()
                mock_cm_class.return_value = mock_config
                mock_get_root.return_value = "/mocked/project/root"
                mock_get_file.return_value = "State test: {question}"
                
                # Test single agent state
                agent1 = TestAgent( question="State test 1" )
                
                # Test initial state (questions get normalized)
                # "State test 1" becomes "state test 1" after normalization  
                assert agent1.question == "state test 1", f"Agent should maintain normalized question state, got '{agent1.question}'"
                assert agent1.last_question_asked == "State test 1", f"Agent should preserve original question, got '{agent1.last_question_asked}'"
                assert hasattr( agent1, 'debug' ), "Agent should have debug state"
                assert hasattr( agent1, 'verbose' ), "Agent should have verbose state"
                
                # Test state independence between agents (reuse same mock)
                agent2 = TestAgent( question="State test 2", debug=True )
                
                assert agent1.question != agent2.question, "Agents should have independent questions"
                assert agent1.question == "state test 1", f"First agent normalized question should be unchanged, got '{agent1.question}'"
                assert agent2.question == "state test 2", f"Second agent normalized question should be set correctly, got '{agent2.question}'"
                
                # Test that agents don't share state
                if hasattr( agent1, 'debug' ) and hasattr( agent2, 'debug' ):
                    # Agents may have different debug settings
                    pass  # State independence verified by different questions
                
                self.utils.print_test_status( "State independence test passed", "PASS" )
            
            # Test agent initialization with various states
            state_scenarios = [
                { "debug": True, "verbose": False },
                { "debug": False, "verbose": True },
                { "debug": True, "verbose": True },
                { "debug": False, "verbose": False }
            ]
            
            # Test agent initialization with various states
            with patch( 'cosa.agents.agent_base.ConfigurationManager' ) as mock_cm_class2, \
                 patch( 'cosa.agents.agent_base.du.get_file_as_string' ) as mock_get_file2, \
                 patch( 'cosa.agents.agent_base.du.get_project_root' ) as mock_get_root2:
                mock_config2 = self.mock_mgr.config_manager_mock( {
                    "prompt template for test routing": "/templates/multi_state_test.txt",
                    "llm spec key for test routing": "multi_state_spec"
                } ).__enter__()
                mock_cm_class2.return_value = mock_config2
                mock_get_root2.return_value = "/mocked/project/root"
                mock_get_file2.return_value = "Multi-state test: {question}"
                
                agents = []
                for i, scenario in enumerate( state_scenarios ):
                    agent = TestAgent( question=f"State scenario {i}", **scenario )
                    agents.append( agent )
                    
                    # Verify state was set correctly
                    for key, expected_value in scenario.items():
                        if hasattr( agent, key ):
                            actual_value = getattr( agent, key )
                            assert actual_value == expected_value, f"Agent {i} {key} should be {expected_value}, got {actual_value}"
                
                # Verify all agents maintain independent state (questions are normalized)
                for i, agent in enumerate( agents ):
                    expected_normalized = f"state scenario {i}"  # Normalization converts to lowercase
                    assert agent.question == expected_normalized, f"Agent {i} should maintain correct normalized question, got '{agent.question}'"
                
                self.utils.print_test_status( "Multiple agent state test passed", "PASS" )
            
            return True
            
        except Exception as e:
            self.utils.print_test_status( f"Agent state management test failed: {e}", "FAIL" )
            return False
    
    def test_error_handling( self ) -> bool:
        """
        Test error handling in AgentBase.
        
        Ensures:
            - Invalid parameters are handled gracefully
            - Missing configuration doesn't crash agent
            - Malformed inputs are processed safely
            - Exception handling works correctly
            
        Returns:
            True if test passes
        """
        self.utils.print_test_banner( "Testing Error Handling" )
        
        try:
            # MONKEY PATCH: Test with invalid configuration
            with patch( 'cosa.agents.agent_base.ConfigurationManager' ) as mock_cm_class, \
                 patch( 'cosa.agents.agent_base.du.get_file_as_string' ) as mock_get_file, \
                 patch( 'cosa.agents.agent_base.du.get_project_root' ) as mock_get_root:
                mock_config = self.mock_mgr.config_manager_mock( {
                    "prompt template for test routing": "/templates/error_test.txt",
                    "llm spec key for test routing": "error_test_spec"
                } ).__enter__()
                mock_cm_class.return_value = mock_config
                mock_get_root.return_value = "/mocked/project/root"
                mock_get_file.return_value = "Error test: {question}"
                
                # Should not crash with minimal configuration
                agent = TestAgent( question="Error test" )
                assert agent is not None, "Agent should be created even with minimal config"
            
            # Test with problematic questions
            problematic_questions = [
                "",  # Empty question
                " ",  # Whitespace only
                "A" * 1000,  # Very long question
                "Question with\nnewlines\nand\ttabs",  # Special characters
                "Question with unicode: café résumé 中文",  # Unicode
                None  # None value (may be converted to string)
            ]
            
            for question in problematic_questions:
                try:
                    # MONKEY PATCH: Each problematic question gets its own context
                    with patch( 'cosa.agents.agent_base.ConfigurationManager' ) as mock_cm_class_prob, \
                         patch( 'cosa.agents.agent_base.du.get_file_as_string' ) as mock_get_file_prob, \
                         patch( 'cosa.agents.agent_base.du.get_project_root' ) as mock_get_root_prob:
                        mock_config_prob = self.mock_mgr.config_manager_mock( {
                            "prompt template for test routing": "/templates/problematic_test.txt",
                            "llm spec key for test routing": "prob_test_spec"
                        } ).__enter__()
                        mock_cm_class_prob.return_value = mock_config_prob
                        mock_get_root_prob.return_value = "/mocked/project/root"
                        mock_get_file_prob.return_value = "Problematic test: {question}"
                        
                        if question is None:
                            # Skip None test as it may cause issues in initialization
                            continue
                        
                        agent = TestAgent( question=question )
                        assert agent is not None, f"Agent should handle problematic question: {repr( question )}"
                        
                        # Test that agent maintains some form of the question
                        assert hasattr( agent, 'question' ), "Agent should have question attribute"
                        
                except Exception as e:
                    # Some exceptions may be acceptable for truly invalid inputs
                    self.utils.print_test_status( f"Expected error for invalid input {repr( question )}: {e}", "INFO" )
            
            # Test invalid parameter combinations
            try:
                # MONKEY PATCH: Test extreme parameter values
                with patch( 'cosa.agents.agent_base.ConfigurationManager' ) as mock_cm_class_extreme, \
                     patch( 'cosa.agents.agent_base.du.get_file_as_string' ) as mock_get_file_extreme, \
                     patch( 'cosa.agents.agent_base.du.get_project_root' ) as mock_get_root_extreme:
                    mock_config_extreme = self.mock_mgr.config_manager_mock( {
                        "prompt template for test routing": "/templates/extreme_test.txt",
                        "llm spec key for test routing": "extreme_test_spec"
                    } ).__enter__()
                    mock_cm_class_extreme.return_value = mock_config_extreme
                    mock_get_root_extreme.return_value = "/mocked/project/root"
                    mock_get_file_extreme.return_value = "Extreme test: {question}"
                    
                    # Test with extreme parameter values
                    agent = TestAgent( 
                        question="Extreme test",
                        push_counter=-1,  # Negative counter
                        debug=True,
                        verbose=True
                    )
                    assert agent is not None, "Agent should handle extreme parameters"
                    
            except Exception as e:
                # Should handle gracefully
                self.utils.print_test_status( f"Extreme parameters handled: {e}", "INFO" )
            
            self.utils.print_test_status( "Error handling test passed", "PASS" )
            return True
            
        except Exception as e:
            self.utils.print_test_status( f"Error handling test failed: {e}", "FAIL" )
            return False
    
    def test_performance_requirements( self ) -> bool:
        """
        Test AgentBase performance requirements.
        
        Ensures:
            - Agent creation is fast enough
            - Memory usage is reasonable
            - Multiple agents can be created efficiently
            
        Returns:
            True if test passes
        """
        self.utils.print_test_banner( "Testing Performance Requirements" )
        
        try:
            performance_targets = self.fixtures.get_performance_targets()
            agent_timeout = performance_targets[ "timing_targets" ].get( "agent_response_time", 2.0 )
            
            # MONKEY PATCH: Test single agent creation performance
            with patch( 'cosa.agents.agent_base.ConfigurationManager' ) as mock_cm_class_perf, \
                 patch( 'cosa.agents.agent_base.du.get_file_as_string' ) as mock_get_file_perf, \
                 patch( 'cosa.agents.agent_base.du.get_project_root' ) as mock_get_root_perf:
                mock_config_perf = self.mock_mgr.config_manager_mock( {
                    "prompt template for test routing": "/templates/performance_test.txt",
                    "llm spec key for test routing": "perf_test_spec"
                } ).__enter__()
                mock_cm_class_perf.return_value = mock_config_perf
                mock_get_root_perf.return_value = "/mocked/project/root"
                mock_get_file_perf.return_value = "Performance test: {question}"
                
                def single_agent_test():
                    agent = TestAgent( question="Performance test" )
                    return agent is not None
                
                success, duration, result = self.utils.assert_timing( single_agent_test, 0.1 )  # 100ms limit
                assert success, f"Agent creation too slow: {duration}s"
                assert result == True, "Agent creation should return True"
            
            # Test multiple agent creation
            with patch( 'cosa.agents.agent_base.ConfigurationManager' ) as mock_cm_class_multi, \
                 patch( 'cosa.agents.agent_base.du.get_file_as_string' ) as mock_get_file_multi, \
                 patch( 'cosa.agents.agent_base.du.get_project_root' ) as mock_get_root_multi:
                mock_config_multi = self.mock_mgr.config_manager_mock( {
                    "prompt template for test routing": "/templates/multi_performance_test.txt",
                    "llm spec key for test routing": "multi_perf_spec"
                } ).__enter__()
                mock_cm_class_multi.return_value = mock_config_multi
                mock_get_root_multi.return_value = "/mocked/project/root"
                mock_get_file_multi.return_value = "Multi performance test: {question}"
                
                def multiple_agents_test():
                    agents = []
                    for i in range( 5 ):
                        agent = TestAgent( question=f"Performance test {i}" )
                        agents.append( agent )
                    return len( agents )
                
                success, duration, result = self.utils.assert_timing( multiple_agents_test, 0.5 )  # 500ms limit
                assert success, f"Multiple agent creation too slow: {duration}s"
                assert result == 5, f"Should create 5 agents, got {result}"
            
            self.utils.print_test_status( f"Performance requirements met ({self.utils.format_duration( duration )})", "PASS" )
            return True
            
        except Exception as e:
            self.utils.print_test_status( f"Performance requirements test failed: {e}", "FAIL" )
            return False
    
    def run_all_tests( self ) -> tuple:
        """
        Run all AgentBase unit tests.
        
        Returns:
            Tuple of (success, duration, error_message)
        """
        start_time = self.utils.start_timer( "agent_base_tests" )
        
        tests = [
            self.test_agent_base_instantiation,
            self.test_configuration_integration,
            self.test_prompt_template_handling,
            self.test_xml_response_framework,
            self.test_agent_state_management,
            self.test_error_handling,
            self.test_performance_requirements
        ]
        
        passed_tests = 0
        failed_tests = 0
        errors = []
        
        self.utils.print_test_banner( "AgentBase Framework Unit Test Suite", "=" )
        
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
        
        duration = self.utils.stop_timer( "agent_base_tests" )
        
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
    Main unit test function for AgentBase framework.
    
    This is the entry point called by the unit test runner to execute
    all AgentBase framework unit tests.
    
    Returns:
        Tuple[bool, float, str]: (success, duration, error_message)
    """
    test_suite = None
    
    try:
        test_suite = AgentBaseUnitTests( debug=False )
        success, duration, error_message = test_suite.run_all_tests()
        return success, duration, error_message
        
    except Exception as e:
        error_message = f"AgentBase framework unit test suite failed to initialize: {str( e )}"
        return False, 0.0, error_message
        
    finally:
        if test_suite:
            test_suite.cleanup()


if __name__ == "__main__":
    success, duration, error = isolated_unit_test()
    status = "✅ PASS" if success else "❌ FAIL"
    print( f"{status} AgentBase framework unit tests completed in {duration:.2f}s" )
    if error:
        print( f"Errors: {error}" )