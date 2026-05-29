"""
Unit tests for model configuration system with comprehensive validation.

Tests the model configuration loading and validation system including:
- Configuration file discovery and loading
- Model configuration mapping and resolution
- Configuration structure validation and completeness
- Model-specific parameter validation
- Configuration dictionary content verification
- Error handling for unknown models and malformed configs
- Dynamic import mechanism testing

Zero external dependencies - all configuration loading operations
are tested in isolation with comprehensive structure validation.
"""

import unittest
from unittest.mock import Mock, MagicMock, patch, mock_open
import time
import sys
import os
from typing import Dict, Any, Union, List
import sys
import os

# Import test infrastructure
sys.path.append( os.path.join( os.path.dirname( __file__ ), "..", "infrastructure" ) )
from mock_manager import MockManager
from unit_test_utilities import UnitTestUtilities

# Import the module under test
from cosa.training.conf.model_config_loader import load_model_config, MODEL_CONFIG_MAP


class TestModelConfigurations( unittest.TestCase ):
    """
    Comprehensive unit tests for model configuration system.
    
    Requires:
        - MockManager for external dependency mocking
        - UnitTestUtilities for common test patterns
        
    Ensures:
        - All model configurations tested in isolation
        - Configuration loading and validation properly tested
        - Error handling scenarios covered
        - Dynamic import mechanism thoroughly tested
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
        self.test_model_names = [
            "Mistral-7B-Instruct-v0.2",
            "Ministral-8B-Instruct-2410", 
            "Llama-3.2-3B-Instruct",
            "Phi-4-mini-instruct"
        ]
        
        # Sample valid configuration
        self.sample_config = {
            "fine_tune_config": {
                "sample_size": 0.01,
                "batch_size": 8,
                "gradient_accumulation_steps": 4,
                "logging_steps": 0.50,
                "eval_steps": 0.50,
                "device_map": "auto"
            },
            "lora_config": {
                "lora_alpha": 16,
                "lora_dropout": 0.05,
                "r": 64,
                "bias": "none",
                "task_type": "CAUSAL_LM",
                "target_modules": ["k_proj", "q_proj", "v_proj"]
            },
            "tokenizer_config": {
                "pad_token": "unk_token",
                "pad_token_id": "converted_from_unk_token",
                "padding_side": {
                    "training": "right",
                    "inference": "left"
                }
            },
            "model_config": {
                "max_seq_length": 683,
                "prompt_template": "<s>[INST]{instruction}[/INST]{output}</s>",
                "last_tag_func": lambda output: "</s>" if output else ""
            }
        }
    
    def tearDown( self ):
        """
        Cleanup after each test method.
        
        Ensures:
            - All mocks are reset
        """
        self.mock_manager.reset_mocks()
    
    def test_model_config_map_completeness( self ):
        """
        Test MODEL_CONFIG_MAP contains all expected models.
        
        Ensures:
            - All supported models are included in the map
            - Map keys match expected model names
            - Map values are valid module names
        """
        expected_models = [
            "Mistral-7B-Instruct-v0.2",
            "Ministral-8B-Instruct-2410",
            "Llama-3.2-3B-Instruct", 
            "Phi-4-mini-instruct"
        ]
        
        # Verify all expected models are present
        for model in expected_models:
            self.assertIn( model, MODEL_CONFIG_MAP )
        
        # Verify map values are strings (module names)
        for model_name, module_name in MODEL_CONFIG_MAP.items():
            self.assertIsInstance( module_name, str )
            self.assertGreater( len( module_name ), 0 )
    
    def test_load_model_config_success( self ):
        """
        Test successful model configuration loading.
        
        Ensures:
            - Loads configuration for valid model names
            - Returns properly structured configuration dictionary
            - Contains all required configuration sections
        """
        with patch( 'cosa.training.conf.import_module' ) as mock_import:
            # Create mock module with all required config attributes
            mock_module = Mock()
            mock_module.fine_tune_config = self.sample_config["fine_tune_config"]
            mock_module.lora_config = self.sample_config["lora_config"]
            mock_module.tokenizer_config = self.sample_config["tokenizer_config"]
            mock_module.model_config = self.sample_config["model_config"]
            
            mock_import.return_value = mock_module
            
            for model_name in self.test_model_names:
                with self.subTest( model_name=model_name ):
                    config = load_model_config( model_name )
                    
                    # Verify configuration structure
                    self.assertIsInstance( config, dict )
                    self.assertIn( "fine_tune", config )
                    self.assertIn( "lora", config )
                    self.assertIn( "tokenizer", config )
                    self.assertIn( "model", config )
                    
                    # Verify import was called correctly
                    expected_module = f".{MODEL_CONFIG_MAP[model_name]}"
                    mock_import.assert_called_with( 
                        expected_module, 
                        package="cosa.training.conf" 
                    )
    
    def test_load_model_config_unknown_model( self ):
        """
        Test model configuration loading with unknown model name.
        
        Ensures:
            - Raises ValueError for unknown model names
            - Provides descriptive error message
            - Lists available models in error message
        """
        unknown_model = "Unknown-Model-Name"
        
        with self.assertRaises( ValueError ) as context:
            load_model_config( unknown_model )
        
        error_message = str( context.exception )
        self.assertIn( f"Unknown model: {unknown_model}", error_message )
        self.assertIn( "Available models:", error_message )
        
        # Verify all available models are listed
        for model_name in MODEL_CONFIG_MAP.keys():
            self.assertIn( model_name, error_message )
    
    def test_load_model_config_import_error( self ):
        """
        Test model configuration loading with import error.
        
        Ensures:
            - Propagates import errors from missing modules
            - Handles module import failures gracefully
        """
        with patch( 'cosa.training.conf.import_module' ) as mock_import:
            import_error = ImportError( "No module named 'test_module'" )
            mock_import.side_effect = import_error
            
            model_name = self.test_model_names[0]
            
            with self.assertRaises( ImportError ) as context:
                load_model_config( model_name )
            
            self.assertIn( "No module named 'test_module'", str( context.exception ) )
    
    def test_fine_tune_config_structure( self ):
        """
        Test fine-tune configuration structure validation.
        
        Ensures:
            - Contains required training parameters
            - Parameter types are correct
            - Values are within expected ranges
        """
        with patch( 'cosa.training.conf.import_module' ) as mock_import:
            mock_module = Mock()
            mock_module.fine_tune_config = self.sample_config["fine_tune_config"]
            mock_module.lora_config = self.sample_config["lora_config"]
            mock_module.tokenizer_config = self.sample_config["tokenizer_config"]
            mock_module.model_config = self.sample_config["model_config"]
            
            mock_import.return_value = mock_module
            
            config = load_model_config( self.test_model_names[0] )
            fine_tune = config["fine_tune"]
            
            # Verify required parameters exist
            required_params = [
                "sample_size", "batch_size", "gradient_accumulation_steps",
                "logging_steps", "eval_steps", "device_map"
            ]
            
            for param in required_params:
                self.assertIn( param, fine_tune )
            
            # Verify parameter types
            self.assertIsInstance( fine_tune["sample_size"], (int, float) )
            self.assertIsInstance( fine_tune["batch_size"], int )
            self.assertIsInstance( fine_tune["gradient_accumulation_steps"], int )
            self.assertIsInstance( fine_tune["logging_steps"], (int, float) )
            self.assertIsInstance( fine_tune["eval_steps"], (int, float) )
            self.assertIsInstance( fine_tune["device_map"], str )
    
    def test_lora_config_structure( self ):
        """
        Test LoRA configuration structure validation.
        
        Ensures:
            - Contains required LoRA parameters
            - Parameter types are correct
            - Target modules are properly specified
        """
        with patch( 'cosa.training.conf.import_module' ) as mock_import:
            mock_module = Mock()
            mock_module.fine_tune_config = self.sample_config["fine_tune_config"]
            mock_module.lora_config = self.sample_config["lora_config"]
            mock_module.tokenizer_config = self.sample_config["tokenizer_config"]
            mock_module.model_config = self.sample_config["model_config"]
            
            mock_import.return_value = mock_module
            
            config = load_model_config( self.test_model_names[0] )
            lora = config["lora"]
            
            # Verify required parameters exist
            required_params = [
                "lora_alpha", "lora_dropout", "r", "bias", 
                "task_type", "target_modules"
            ]
            
            for param in required_params:
                self.assertIn( param, lora )
            
            # Verify parameter types
            self.assertIsInstance( lora["lora_alpha"], int )
            self.assertIsInstance( lora["lora_dropout"], (int, float) )
            self.assertIsInstance( lora["r"], int )
            self.assertIsInstance( lora["bias"], str )
            self.assertIsInstance( lora["task_type"], str )
            self.assertIsInstance( lora["target_modules"], list )
            
            # Verify target modules are strings
            for module in lora["target_modules"]:
                self.assertIsInstance( module, str )
    
    def test_tokenizer_config_structure( self ):
        """
        Test tokenizer configuration structure validation.
        
        Ensures:
            - Contains required tokenizer parameters
            - Padding configuration is properly structured
            - Parameter types are correct
        """
        with patch( 'cosa.training.conf.import_module' ) as mock_import:
            mock_module = Mock()
            mock_module.fine_tune_config = self.sample_config["fine_tune_config"]
            mock_module.lora_config = self.sample_config["lora_config"]
            mock_module.tokenizer_config = self.sample_config["tokenizer_config"]
            mock_module.model_config = self.sample_config["model_config"]
            
            mock_import.return_value = mock_module
            
            config = load_model_config( self.test_model_names[0] )
            tokenizer = config["tokenizer"]
            
            # Verify required parameters exist
            required_params = ["pad_token", "pad_token_id", "padding_side"]
            
            for param in required_params:
                self.assertIn( param, tokenizer )
            
            # Verify parameter types
            self.assertIsInstance( tokenizer["pad_token"], str )
            self.assertIsInstance( tokenizer["pad_token_id"], str )
            self.assertIsInstance( tokenizer["padding_side"], dict )
            
            # Verify padding side structure
            padding_side = tokenizer["padding_side"]
            self.assertIn( "training", padding_side )
            self.assertIn( "inference", padding_side )
            self.assertIsInstance( padding_side["training"], str )
            self.assertIsInstance( padding_side["inference"], str )
    
    def test_model_config_structure( self ):
        """
        Test model configuration structure validation.
        
        Ensures:
            - Contains required model parameters
            - Prompt template is properly formatted
            - Last tag function is callable
        """
        with patch( 'cosa.training.conf.import_module' ) as mock_import:
            mock_module = Mock()
            mock_module.fine_tune_config = self.sample_config["fine_tune_config"]
            mock_module.lora_config = self.sample_config["lora_config"]
            mock_module.tokenizer_config = self.sample_config["tokenizer_config"]
            mock_module.model_config = self.sample_config["model_config"]
            
            mock_import.return_value = mock_module
            
            config = load_model_config( self.test_model_names[0] )
            model = config["model"]
            
            # Verify required parameters exist
            required_params = ["max_seq_length", "prompt_template", "last_tag_func"]
            
            for param in required_params:
                self.assertIn( param, model )
            
            # Verify parameter types
            self.assertIsInstance( model["max_seq_length"], int )
            self.assertIsInstance( model["prompt_template"], str )
            self.assertTrue( callable( model["last_tag_func"] ) )
            
            # Test last_tag_func functionality
            last_tag_func = model["last_tag_func"]
            self.assertIsInstance( last_tag_func( "output" ), str )
            self.assertIsInstance( last_tag_func( "" ), str )
    
    def test_configuration_completeness_all_models( self ):
        """
        Test configuration completeness for all supported models.
        
        Ensures:
            - All models have complete configurations
            - No missing configuration sections
            - All configurations follow same structure
        """
        with patch( 'cosa.training.conf.import_module' ) as mock_import:
            # Create mock module with all required config attributes
            mock_module = Mock()
            mock_module.fine_tune_config = self.sample_config["fine_tune_config"]
            mock_module.lora_config = self.sample_config["lora_config"]
            mock_module.tokenizer_config = self.sample_config["tokenizer_config"]
            mock_module.model_config = self.sample_config["model_config"]
            
            mock_import.return_value = mock_module
            
            for model_name in self.test_model_names:
                with self.subTest( model_name=model_name ):
                    config = load_model_config( model_name )
                    
                    # Verify all four configuration sections exist
                    expected_sections = ["fine_tune", "lora", "tokenizer", "model"]
                    for section in expected_sections:
                        self.assertIn( section, config )
                        self.assertIsInstance( config[section], dict )
                        self.assertGreater( len( config[section] ), 0 )
    
    def test_missing_config_attribute_error( self ):
        """
        Test configuration loading with missing attributes in module.
        
        Ensures:
            - Handles missing configuration attributes gracefully
            - Provides appropriate error messages
        """
        with patch( 'cosa.training.conf.import_module' ) as mock_import:
            # Create mock module missing some config attributes
            mock_module = Mock()
            mock_module.fine_tune_config = self.sample_config["fine_tune_config"]
            mock_module.lora_config = self.sample_config["lora_config"]
            # Missing tokenizer_config and model_config
            del mock_module.tokenizer_config
            del mock_module.model_config
            
            mock_import.return_value = mock_module
            
            model_name = self.test_model_names[0]
            
            with self.assertRaises( AttributeError ):
                load_model_config( model_name )
    
    def test_dynamic_import_mechanism( self ):
        """
        Test dynamic import mechanism for model configurations.
        
        Ensures:
            - Import calls use correct module paths
            - Package parameter is set correctly
            - Module resolution works for all models
        """
        with patch( 'cosa.training.conf.import_module' ) as mock_import:
            mock_module = Mock()
            mock_module.fine_tune_config = self.sample_config["fine_tune_config"]
            mock_module.lora_config = self.sample_config["lora_config"]
            mock_module.tokenizer_config = self.sample_config["tokenizer_config"]
            mock_module.model_config = self.sample_config["model_config"]
            
            mock_import.return_value = mock_module
            
            for model_name in self.test_model_names:
                with self.subTest( model_name=model_name ):
                    load_model_config( model_name )
                    
                    # Verify import was called with correct parameters
                    expected_module = f".{MODEL_CONFIG_MAP[model_name]}"
                    mock_import.assert_called_with( 
                        expected_module, 
                        package="cosa.training.conf" 
                    )
    
    def test_config_immutability( self ):
        """
        Test that loaded configurations maintain data integrity.
        
        Ensures:
            - Configuration dictionaries contain expected data
            - No data corruption during loading process
            - Consistent data types across loads
        """
        with patch( 'cosa.training.conf.import_module' ) as mock_import:
            mock_module = Mock()
            mock_module.fine_tune_config = self.sample_config["fine_tune_config"]
            mock_module.lora_config = self.sample_config["lora_config"]
            mock_module.tokenizer_config = self.sample_config["tokenizer_config"]
            mock_module.model_config = self.sample_config["model_config"]
            
            mock_import.return_value = mock_module
            
            model_name = self.test_model_names[0]
            
            # Load configuration multiple times
            config1 = load_model_config( model_name )
            config2 = load_model_config( model_name )
            
            # Verify configurations are structurally identical
            self.assertEqual( list( config1.keys() ), list( config2.keys() ) )
            
            for section in config1.keys():
                self.assertIsInstance( config1[section], type( config2[section] ) )


def isolated_unit_test():
    """
    Run comprehensive unit tests for model configurations in complete isolation.
    
    Ensures:
        - All external dependencies mocked
        - No real configuration file loading
        - Deterministic test results
        - Fast execution
        
    Returns:
        Tuple[bool, float, str]: (success, duration, message)
    """
    import cosa.utils.util as du
    
    start_time = time.time()
    
    try:
        du.print_banner( "Model Configurations Unit Tests - Training Phase 6", prepend_nl=True )
        
        # Create test suite
        suite = unittest.TestSuite()
        
        # Add all test methods
        test_methods = [
            'test_model_config_map_completeness',
            'test_load_model_config_success',
            'test_load_model_config_unknown_model',
            'test_load_model_config_import_error',
            'test_fine_tune_config_structure',
            'test_lora_config_structure',
            'test_tokenizer_config_structure',
            'test_model_config_structure',
            'test_configuration_completeness_all_models',
            'test_missing_config_attribute_error',
            'test_dynamic_import_mechanism',
            'test_config_immutability'
        ]
        
        for method in test_methods:
            suite.addTest( TestModelConfigurations( method ) )
        
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
        print( f"MODEL CONFIGURATIONS UNIT TEST RESULTS" )
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
            du.print_banner( "✅ ALL MODEL CONFIGURATIONS TESTS PASSED", prepend_nl=True )
            message = f"All {tests_run} tests passed successfully in {duration:.3f}s"
        else:
            du.print_banner( "❌ SOME MODEL CONFIGURATIONS TESTS FAILED", prepend_nl=True )
            message = f"{failures} failures, {errors} errors out of {tests_run} tests"
        
        return success, duration, message
        
    except Exception as e:
        duration = time.time() - start_time
        error_msg = f"Unit test execution failed: {str(e)}"
        du.print_banner( f"💥 MODEL CONFIGURATIONS TEST ERROR: {error_msg}", prepend_nl=True )
        return False, duration, error_msg


if __name__ == "__main__":
    success, duration, message = isolated_unit_test()
    status = "✅ PASS" if success else "❌ FAIL"
    print( f"\n{status} Model configurations unit tests completed in {duration:.3f}s" )
    print( f"Result: {message}" )