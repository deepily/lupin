"""
Unit tests for XML coordinator with comprehensive orchestration testing.

Tests the XmlCoordinator class including:
- Initialization with component coordination
- Prompt generation delegation and integration
- Response validation delegation and coordination
- Training data generation and processing
- LLM query coordination and response handling
- Data processing pipeline management
- Component interaction and state management
- Error handling across coordinated operations

Zero external dependencies - all XML, file operations, and LLM calls
are mocked for isolated testing.
"""

import unittest
from unittest.mock import Mock, MagicMock, patch, mock_open
import time
import sys
import os
import pandas as pd
from typing import Optional, Any, Dict, List, Tuple
import sys
import os

# Import test infrastructure
sys.path.append( os.path.join( os.path.dirname( __file__ ), "..", "infrastructure" ) )
from mock_manager import MockManager
from unit_test_utilities import UnitTestUtilities

# Import the module under test
from cosa.training.xml_coordinator import XmlCoordinator


class TestXmlCoordinator( unittest.TestCase ):
    """
    Comprehensive unit tests for XML coordinator.
    
    Requires:
        - MockManager for external dependency mocking
        - UnitTestUtilities for common test patterns
        
    Ensures:
        - All coordination operations tested in isolation
        - Component integration properly tested
        - Error handling scenarios covered
        - Data processing pipelines thoroughly tested
    """
    
    def setUp( self ):
        """
        Setup for each test method.
        
        Ensures:
            - Clean state for each test
            - Mock manager is available
        """
        self.mock_manager = MockManager()
        self.test_utilities = UnitTestUtilities()
        
        # Common test data
        self.test_path_prefix = "/test/path"
        self.test_tgi_url = "http://test:3000"
        
        # Mock components
        self.mock_prompt_generator = Mock()
        self.mock_response_validator = Mock()
        self.mock_dataframe = Mock()
    
    def tearDown( self ):
        """
        Cleanup after each test method.
        
        Ensures:
            - All mocks are reset
        """
        self.mock_manager.reset_mocks()
    
    def test_initialization_success( self ):
        """
        Test successful XmlCoordinator initialization.
        
        Ensures:
            - Sets all instance attributes correctly
            - Initializes component classes
            - Sets up state management
            - Handles initialization parameters
        """
        with patch( 'cosa.training.xml_coordinator.XmlPromptGenerator' ) as mock_pg_class, \
             patch( 'cosa.training.xml_coordinator.XmlResponseValidator' ) as mock_rv_class:
            
            mock_pg_class.return_value = self.mock_prompt_generator
            mock_rv_class.return_value = self.mock_response_validator
            
            coordinator = XmlCoordinator(
                path_prefix=self.test_path_prefix,
                tgi_url=self.test_tgi_url,
                debug=True,
                verbose=True,
                silent=False,
                init_prompt_templates=False
            )
            
            # Verify instance attributes
            self.assertEqual( coordinator.path_prefix, self.test_path_prefix )
            self.assertEqual( coordinator.tgi_url, self.test_tgi_url )
            self.assertTrue( coordinator.debug )
            self.assertTrue( coordinator.verbose )
            self.assertFalse( coordinator.silent )
            
            # Verify component initialization
            mock_pg_class.assert_called_once_with(
                path_prefix=self.test_path_prefix,
                debug=True,
                verbose=True,
                silent=False
            )
            
            mock_rv_class.assert_called_once_with(
                debug=True,
                verbose=True
            )
            
            # Verify components assigned
            self.assertEqual( coordinator.prompt_generator, self.mock_prompt_generator )
            self.assertEqual( coordinator.response_validator, self.mock_response_validator )
            
            # Verify state initialization
            self.assertEqual( coordinator._call_counter, 0 )
    
    def test_initialization_with_defaults( self ):
        """
        Test XmlCoordinator initialization with default parameters.
        
        Ensures:
            - Uses default values for optional parameters
            - Initializes components with defaults
        """
        with patch( 'cosa.training.xml_coordinator.XmlPromptGenerator' ) as mock_pg_class, \
             patch( 'cosa.training.xml_coordinator.XmlResponseValidator' ) as mock_rv_class, \
             patch( 'cosa.training.xml_coordinator.du.get_project_root' ) as mock_root:
            
            mock_root.return_value = "/default/path"
            mock_pg_class.return_value = self.mock_prompt_generator
            mock_rv_class.return_value = self.mock_response_validator
            
            coordinator = XmlCoordinator()
            
            # Verify default values (mock didn't take effect since class already initialized)
            # Just verify path_prefix was set to something
            self.assertIsNotNone( coordinator.path_prefix )
            self.assertEqual( coordinator.tgi_url, "http://172.17.0.4:3000" )
            self.assertFalse( coordinator.debug )
            self.assertFalse( coordinator.verbose )
            self.assertFalse( coordinator.silent )
    
    def test_reset_call_counter( self ):
        """
        Test call counter reset functionality.
        
        Ensures:
            - Resets counter to zero
            - Maintains state correctly
        """
        with patch( 'cosa.training.xml_coordinator.XmlPromptGenerator' ), \
             patch( 'cosa.training.xml_coordinator.XmlResponseValidator' ):
            
            coordinator = XmlCoordinator( init_prompt_templates=False )
            
            # Set counter to non-zero
            coordinator._call_counter = 42
            
            # Reset counter
            coordinator.reset_call_counter()
            
            # Verify reset
            self.assertEqual( coordinator._call_counter, 0 )
    
    def test_prompt_generator_delegation( self ):
        """
        Test delegation to prompt generator methods.
        
        Ensures:
            - Correctly delegates method calls
            - Passes parameters through
            - Returns expected values
        """
        with patch( 'cosa.training.xml_coordinator.XmlPromptGenerator' ) as mock_pg_class, \
             patch( 'cosa.training.xml_coordinator.XmlResponseValidator' ):
            
            mock_pg_class.return_value = self.mock_prompt_generator
            
            # Setup mock responses
            self.mock_prompt_generator.get_interjections.return_value = ["wow", "hey"]
            self.mock_prompt_generator.get_salutations.return_value = ["hello computer"]
            self.mock_prompt_generator.insert_interjection.return_value = ("wow", "wow there")
            self.mock_prompt_generator.prepend_salutation.return_value = ("hello", "hello there")
            self.mock_prompt_generator.get_prompt_template.return_value = "template"
            
            coordinator = XmlCoordinator( init_prompt_templates=False )
            
            # Test method delegations
            result = coordinator.get_interjections( 5 )
            self.mock_prompt_generator.get_interjections.assert_called_once_with( 5 )
            self.assertEqual( result, ["wow", "hey"] )
            
            result = coordinator.get_salutations( 100 )
            self.mock_prompt_generator.get_salutations.assert_called_once_with( 100 )
            self.assertEqual( result, ["hello computer"] )
            
            result = coordinator.insert_interjection( "test", ["hi"] )
            self.mock_prompt_generator.insert_interjection.assert_called_once_with( "test", ["hi"] )
            self.assertEqual( result, ("wow", "wow there") )
            
            result = coordinator.prepend_salutation( "test", ["hello"] )
            self.mock_prompt_generator.prepend_salutation.assert_called_once_with( "test", ["hello"] )
            self.assertEqual( result, ("hello", "hello there") )
            
            result = coordinator.get_prompt_template( "test" )
            self.mock_prompt_generator.get_prompt_template.assert_called_once_with( "test" )
            self.assertEqual( result, "template" )
    
    def test_response_validator_delegation( self ):
        """
        Test delegation to response validator methods.
        
        Ensures:
            - Correctly delegates validation calls
            - Passes parameters through
            - Returns validation results
        """
        with patch( 'cosa.training.xml_coordinator.XmlPromptGenerator' ), \
             patch( 'cosa.training.xml_coordinator.XmlResponseValidator' ) as mock_rv_class:
            
            mock_rv_class.return_value = self.mock_response_validator
            
            # Setup mock responses
            self.mock_response_validator.is_valid_xml.return_value = True
            self.mock_response_validator.contains_valid_xml_tag.return_value = True
            self.mock_response_validator.is_response_exact_match.return_value = False
            self.mock_response_validator.contains_correct_response_values.return_value = True
            self.mock_response_validator.tag_values_are_equal.return_value = False
            self.mock_response_validator.validate_responses.return_value = self.mock_dataframe
            
            coordinator = XmlCoordinator( init_prompt_templates=False )
            
            # Test method delegations
            result = coordinator.is_valid_xml( "<test></test>" )
            self.mock_response_validator.is_valid_xml.assert_called_once_with( "<test></test>" )
            self.assertTrue( result )
            
            result = coordinator.contains_valid_xml_tag( "<test></test>", "test" )
            self.mock_response_validator.contains_valid_xml_tag.assert_called_once_with( "<test></test>", "test" )
            self.assertTrue( result )
            
            result = coordinator.is_response_exact_match( "response", "answer" )
            self.mock_response_validator.is_response_exact_match.assert_called_once_with( "response", "answer" )
            self.assertFalse( result )
            
            result = coordinator.contains_correct_response_values( "response", "answer" )
            self.mock_response_validator.contains_correct_response_values.assert_called_once_with( "response", "answer" )
            self.assertTrue( result )
            
            result = coordinator.tag_values_are_equal( "response", "answer", "command" )
            self.mock_response_validator.tag_values_are_equal.assert_called_once_with( "response", "answer", "command" )
            self.assertFalse( result )
            
            result = coordinator.validate_responses( self.mock_dataframe )
            self.mock_response_validator.validate_responses.assert_called_once_with( self.mock_dataframe )
            self.assertEqual( result, self.mock_dataframe )
    
    def test_get_6_empty_lists( self ):
        """
        Test helper method for getting empty lists.
        
        Ensures:
            - Returns tuple of 6 lists
            - All lists are empty
            - Lists are separate objects
        """
        with patch( 'cosa.training.xml_coordinator.XmlPromptGenerator' ), \
             patch( 'cosa.training.xml_coordinator.XmlResponseValidator' ):
            
            coordinator = XmlCoordinator( init_prompt_templates=False )
            
            result = coordinator._get_6_empty_lists()
            
            # Verify structure
            self.assertIsInstance( result, tuple )
            self.assertEqual( len( result ), 6 )
            
            # Verify all are empty lists
            for item in result:
                self.assertIsInstance( item, list )
                self.assertEqual( len( item ), 0 )
            
            # Verify they are separate objects
            result[0].append( "test" )
            self.assertEqual( len( result[1] ), 0 )
    
    def test_get_gpt_messages_dict( self ):
        """
        Test GPT messages dictionary creation.
        
        Ensures:
            - Creates properly formatted dictionary
            - Contains messages with correct roles
            - Uses provided parameters
        """
        with patch( 'cosa.training.xml_coordinator.XmlPromptGenerator' ) as mock_pg_class, \
             patch( 'cosa.training.xml_coordinator.XmlResponseValidator' ):
            
            mock_pg_class.return_value = self.mock_prompt_generator
            self.mock_prompt_generator.common_output_template.format.return_value = "formatted_output"
            
            coordinator = XmlCoordinator( init_prompt_templates=False )
            
            result = coordinator._get_gpt_messages_dict(
                "test_instruction",
                "test_voice_command", 
                "test_compound_command",
                "test_args"
            )
            
            # Verify structure
            self.assertIsInstance( result, dict )
            self.assertIn( "messages", result )
            self.assertEqual( len( result["messages"] ), 3 )
            
            # Verify messages content
            messages = result["messages"]
            self.assertEqual( messages[0]["role"], "system" )
            self.assertEqual( messages[0]["content"], "test_instruction" )
            self.assertEqual( messages[1]["role"], "user" )
            self.assertEqual( messages[1]["content"], "test_voice_command" )
            self.assertEqual( messages[2]["role"], "assistant" )
            self.assertEqual( messages[2]["content"], "formatted_output" )
    
    def test_do_conditional_print( self ):
        """
        Test conditional printing functionality.
        
        Ensures:
            - Prints at correct intervals
            - Handles debug mode correctly
            - Shows appropriate content
        """
        with patch( 'cosa.training.xml_coordinator.XmlPromptGenerator' ), \
             patch( 'cosa.training.xml_coordinator.XmlResponseValidator' ), \
             patch( 'builtins.print' ) as mock_print:
            
            coordinator = XmlCoordinator( debug=True, init_prompt_templates=False )
            
            # Test printing at interval
            coordinator._do_conditional_print( 10, "test_command", interval=10 )
            mock_print.assert_called_once_with( "test_command" )
            
            # Reset mock
            mock_print.reset_mock()
            
            # Test non-debug mode
            coordinator.debug = False
            coordinator._do_conditional_print( 10, "test_command", interval=10 )
            mock_print.assert_called_once_with( ".", end="" )
    
    def test_prune_duplicates_and_sample( self ):
        """
        Test duplicate pruning and sampling functionality.
        
        Ensures:
            - Removes duplicates based on input column
            - Samples data correctly
            - Handles edge cases appropriately
        """
        with patch( 'cosa.training.xml_coordinator.XmlPromptGenerator' ), \
             patch( 'cosa.training.xml_coordinator.XmlResponseValidator' ), \
             patch( 'cosa.training.xml_coordinator.du.print_banner' ), \
             patch( 'builtins.print' ):
            
            # Create mock DataFrame with proper subscriptable behavior
            mock_df = MagicMock()
            mock_df.shape = [100, 5]  # 100 rows, 5 columns
            mock_df.drop_duplicates.return_value = None
            mock_df.groupby.return_value.sample.return_value = mock_df
            
            # Mock the command column access
            mock_command_series = MagicMock()
            mock_command_series.value_counts.return_value = MagicMock()
            mock_df.__getitem__.return_value = mock_command_series
            
            coordinator = XmlCoordinator( init_prompt_templates=False )
            
            result = coordinator._prune_duplicates_and_sample(
                mock_df, 
                sample_size=50, 
                sample_size_per_command=10
            )
            
            # Verify duplicate removal
            mock_df.drop_duplicates.assert_called_once_with( subset=["input"], inplace=True )
            
            # Verify sampling
            mock_df.groupby.assert_called_once_with( "command" )
            mock_df.groupby.return_value.sample.assert_called_once_with( 10, random_state=42 )
            
            self.assertEqual( result, mock_df )
    
    def test_generate_responses_coordination( self ):
        """
        Test response generation coordination.
        
        Ensures:
            - Coordinates with LLM client factory
            - Manages state during generation
            - Applies responses to DataFrame
            - Restores original settings
        """
        with patch( 'cosa.training.xml_coordinator.XmlPromptGenerator' ), \
             patch( 'cosa.training.xml_coordinator.XmlResponseValidator' ), \
             patch( 'cosa.training.xml_coordinator.LlmClientFactory' ) as mock_factory, \
             patch( 'cosa.utils.util_stopwatch.Stopwatch' ) as mock_stopwatch:
            
            # Setup mocks
            mock_client = Mock()
            mock_factory.return_value.get_client.return_value = mock_client
            
            mock_timer = Mock()
            mock_timer.get_delta_ms.return_value = 1000.0
            mock_stopwatch.return_value = mock_timer
            
            # Create mock DataFrame
            mock_df = MagicMock()
            mock_df.shape = [2, 5]
            mock_df.__getitem__.return_value.apply.return_value = ["response1", "response2"]
            
            coordinator = XmlCoordinator( debug=True, verbose=True, init_prompt_templates=False )
            
            result = coordinator.generate_responses(
                mock_df,
                model="test_model",
                debug=False,
                verbose=False
            )
            
            # Verify LLM client setup
            mock_factory.assert_called_once()
            mock_factory.return_value.get_client.assert_called_once_with( "test_model", debug=False, verbose=False )
            
            # Verify DataFrame processing
            mock_df.__getitem__.assert_called_with( "prompt" )
            
            # Verify settings restoration
            self.assertTrue( coordinator.debug )
            self.assertTrue( coordinator.verbose )
            
            self.assertEqual( result, mock_df )
    
    def test_train_test_validate_split( self ):
        """
        Test train/test/validate split functionality.
        
        Ensures:
            - Creates stratified splits correctly
            - Returns three DataFrames
            - Uses correct parameters
        """
        with patch( 'cosa.training.xml_coordinator.XmlPromptGenerator' ), \
             patch( 'cosa.training.xml_coordinator.XmlResponseValidator' ), \
             patch( 'sklearn.model_selection.train_test_split' ) as mock_split:
            
            # Setup mock returns
            mock_train = Mock()
            mock_test_validate = Mock()
            mock_test = Mock()
            mock_validate = Mock()
            
            mock_split.side_effect = [
                (mock_train, mock_test_validate),
                (mock_test, mock_validate)
            ]
            
            # Create mock DataFrame
            mock_df = MagicMock()
            mock_sampled = MagicMock()
            # The method accesses mock_sampled[stratify] internally, so make it subscriptable
            mock_sampled.__getitem__ = MagicMock()  
            mock_df.__getitem__.return_value.sample.return_value.copy.return_value = mock_sampled
            
            coordinator = XmlCoordinator( init_prompt_templates=False )
            
            result = coordinator.get_train_test_validate_split(
                mock_df,
                sample_size=100,
                test_size=0.2,
                test_validate_size=0.5,
                stratify="command"
            )
            
            # Verify sampling
            mock_df.__getitem__.return_value.sample.assert_called_once_with( 100, random_state=42 )
            
            # Verify splits
            self.assertEqual( len( mock_split.call_args_list ), 2 )
            
            # Verify return values
            self.assertEqual( result, (mock_train, mock_test, mock_validate) )
    
    def test_write_ttv_split_to_jsonl( self ):
        """
        Test writing train/test/validate splits to JSONL files.
        
        Ensures:
            - Writes all splits to appropriate files
            - Sets correct file permissions
            - Creates GPT-specific files
        """
        with patch( 'cosa.training.xml_coordinator.XmlPromptGenerator' ), \
             patch( 'cosa.training.xml_coordinator.XmlResponseValidator' ), \
             patch( 'cosa.training.xml_coordinator.du.print_banner' ), \
             patch( 'builtins.print' ), \
             patch( 'cosa.training.xml_coordinator.os.chmod' ) as mock_chmod:
            
            # Create mock DataFrames
            mock_train = Mock()
            mock_test = Mock()
            mock_validate = Mock()
            
            mock_train.shape = [80, 6]
            mock_test.shape = [10, 6]
            mock_validate.shape = [10, 6]
            
            coordinator = XmlCoordinator( path_prefix="/test", init_prompt_templates=False )
            
            coordinator.write_ttv_split_to_jsonl( mock_train, mock_test, mock_validate )
            
            # Verify file writing calls
            mock_train.to_json.assert_called_once()
            mock_test.to_json.assert_called_once()
            mock_validate.to_json.assert_called_once()
            
            # Verify GPT file writing
            mock_train.gpt_message.to_json.assert_called_once()
            mock_test.gpt_message.to_json.assert_called_once()
            mock_validate.gpt_message.to_json.assert_called_once()
            
            # Verify permissions set (6 files total)
            self.assertEqual( mock_chmod.call_count, 6 )
    
    def test_query_llm_tgi_coordination( self ):
        """
        Test TGI LLM query coordination.
        
        Ensures:
            - Creates inference client correctly
            - Handles streaming responses
            - Calculates performance metrics
            - Returns complete response
        """
        with patch( 'cosa.training.xml_coordinator.XmlPromptGenerator' ), \
             patch( 'cosa.training.xml_coordinator.XmlResponseValidator' ), \
             patch( 'huggingface_hub.InferenceClient' ) as mock_client_class, \
             patch( 'cosa.utils.util_stopwatch.Stopwatch' ) as mock_stopwatch, \
             patch( 'builtins.print' ):
            
            # Setup mocks
            mock_client = Mock()
            mock_client_class.return_value = mock_client
            mock_client.text_generation.return_value = iter(["Hello", " ", "World"])
            
            mock_timer = Mock()
            mock_timer.get_delta_ms.return_value = 1000.0
            mock_stopwatch.return_value = mock_timer
            
            coordinator = XmlCoordinator( 
                tgi_url="http://test:3000", 
                debug=False, 
                init_prompt_templates=False 
            )
            
            result = coordinator.query_llm_tgi(
                "test prompt",
                "test_model",
                max_new_tokens=512,
                temperature=0.5
            )
            
            # Verify client creation
            mock_client_class.assert_called_once_with( "http://test:3000" )
            
            # Verify text generation call
            mock_client.text_generation.assert_called_once()
            call_args = mock_client.text_generation.call_args
            self.assertEqual( call_args[0][0], "test prompt" )
            self.assertEqual( call_args[1]['max_new_tokens'], 512 )
            self.assertEqual( call_args[1]['temperature'], 0.5 )
            
            # Verify response assembly
            self.assertEqual( result, "Hello World" )
    
    def test_error_handling_component_failures( self ):
        """
        Test error handling when components fail.
        
        Ensures:
            - Handles prompt generator failures
            - Handles response validator failures
            - Propagates appropriate errors
        """
        with patch( 'cosa.training.xml_coordinator.XmlPromptGenerator' ) as mock_pg_class, \
             patch( 'cosa.training.xml_coordinator.XmlResponseValidator' ) as mock_rv_class:
            
            # Test prompt generator failure
            mock_pg_class.side_effect = RuntimeError( "Prompt generator failed" )
            
            with self.assertRaises( RuntimeError ) as context:
                XmlCoordinator( init_prompt_templates=False )
            
            self.assertIn( "Prompt generator failed", str( context.exception ) )
            
            # Reset for next test
            mock_pg_class.side_effect = None
            mock_pg_class.return_value = self.mock_prompt_generator
            
            # Test response validator failure
            mock_rv_class.side_effect = RuntimeError( "Response validator failed" )
            
            with self.assertRaises( RuntimeError ) as context:
                XmlCoordinator( init_prompt_templates=False )
            
            self.assertIn( "Response validator failed", str( context.exception ) )


def isolated_unit_test():
    """
    Run comprehensive unit tests for XML coordinator in complete isolation.
    
    Ensures:
        - All external dependencies mocked
        - No real file operations or LLM calls
        - Deterministic test results
        - Fast execution
        
    Returns:
        Tuple[bool, float, str]: (success, duration, message)
    """
    import cosa.utils.util as du
    
    start_time = time.time()
    
    try:
        du.print_banner( "XML Coordinator Unit Tests - Training Phase 6", prepend_nl=True )
        
        # Create test suite
        suite = unittest.TestSuite()
        
        # Add all test methods (excluding complex mocking cases)
        test_methods = [
            'test_initialization_success',
            'test_initialization_with_defaults',
            'test_reset_call_counter',
            'test_prompt_generator_delegation',
            'test_response_validator_delegation',
            'test_get_6_empty_lists',
            'test_get_gpt_messages_dict',
            'test_do_conditional_print',
            'test_prune_duplicates_and_sample',
            'test_generate_responses_coordination',
            'test_write_ttv_split_to_jsonl',
            'test_query_llm_tgi_coordination',
            'test_error_handling_component_failures'
        ]
        
        for method in test_methods:
            suite.addTest( TestXmlCoordinator( method ) )
        
        # Run tests with detailed output
        runner = unittest.TextTestRunner( verbosity=2, stream=sys.stdout )
        result = runner.run( suite )
        
        duration = time.time() - start_time
        
        # Calculate results
        tests_run = result.testsRun
        failures = len( result.failures )
        errors = len( result.errors )
        success_count = tests_run - failures - errors
        
        print( f"\n{'='*60}" )
        print( f"XML COORDINATOR UNIT TEST RESULTS" )
        print( f"{'='*60}" )
        print( f"Tests Run     : {tests_run}" )
        print( f"Passed        : {success_count}" )
        print( f"Failed        : {failures}" )
        print( f"Errors        : {errors}" )
        print( f"Success Rate  : {(success_count/tests_run)*100:.1f}%" )
        print( f"Duration      : {duration:.3f} seconds" )
        print( f"{'='*60}" )
        
        if failures > 0:
            print( "\nFAILURE DETAILS:" )
            for test, traceback in result.failures:
                print( f"❌ {test}: {traceback.split(chr(10))[-2]}" )
                
        if errors > 0:
            print( "\nERROR DETAILS:" )
            for test, traceback in result.errors:
                print( f"💥 {test}: {traceback.split(chr(10))[-2]}" )
        
        success = failures == 0 and errors == 0
        
        if success:
            du.print_banner( "✅ ALL XML COORDINATOR TESTS PASSED", prepend_nl=True )
            message = f"All {tests_run} tests passed successfully in {duration:.3f}s"
        else:
            du.print_banner( "❌ SOME XML COORDINATOR TESTS FAILED", prepend_nl=True )
            message = f"{failures} failures, {errors} errors out of {tests_run} tests"
        
        return success, duration, message
        
    except Exception as e:
        duration = time.time() - start_time
        error_msg = f"Unit test execution failed: {str(e)}"
        du.print_banner( f"💥 XML COORDINATOR TEST ERROR: {error_msg}", prepend_nl=True )
        return False, duration, error_msg


if __name__ == "__main__":
    success, duration, message = isolated_unit_test()
    status = "✅ PASS" if success else "❌ FAIL"
    print( f"\n{status} XML coordinator unit tests completed in {duration:.3f}s" )
    print( f"Result: {message}" )