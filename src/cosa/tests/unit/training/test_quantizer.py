"""
Unit tests for model quantizer with comprehensive ML framework mocking.

Tests the Quantizer class including:
- Initialization with model loading and tokenizer setup
- Model quantization workflow with AutoRound integration
- Configuration parameter validation and management
- Output directory creation and model saving
- CLI interface argument parsing and validation
- Error handling for model loading and quantization failures
- Device mapping and memory management options
- Quantization method validation and parameter tuning

Zero external dependencies - all PyTorch, transformers, AutoRound,
and model operations are mocked for isolated testing.
"""

import unittest
from unittest.mock import Mock, MagicMock, patch, call
import time
import sys
import os
from typing import Optional
import sys
import os

# Import test infrastructure
sys.path.append( os.path.join( os.path.dirname( __file__ ), "..", "infrastructure" ) )
from mock_manager import MockManager
from unit_test_utilities import UnitTestUtilities

# Import the module under test
from cosa.training.quantizer import Quantizer


class TestQuantizer( unittest.TestCase ):
    """
    Comprehensive unit tests for model quantizer.
    
    Requires:
        - MockManager for external dependency mocking
        - UnitTestUtilities for common test patterns
        
    Ensures:
        - All ML framework operations tested in isolation
        - Model loading and quantization properly mocked
        - Error handling scenarios covered
        - CLI interface thoroughly tested
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
        self.test_model_name = "microsoft/Phi-4-mini-instruct"
        self.test_output_dir = "/path/to/output"
        self.test_full_path = "/path/to/output/Phi-4-mini-instruct-autoround-4-bits-sym.gptq/2025-08-05-at-14-30"
        
        # Mock model and tokenizer
        self.mock_model = Mock()
        self.mock_tokenizer = Mock()
        self.mock_autoround = Mock()
    
    def tearDown( self ):
        """
        Cleanup after each test method.
        
        Ensures:
            - All mocks are reset
        """
        self.mock_manager.reset_mocks()
    
    def test_initialization_success( self ):
        """
        Test successful Quantizer initialization with model loading.
        
        Ensures:
            - Loads model and tokenizer from HuggingFace
            - Sets default quantization parameters
            - Stores model name and configuration
        """
        with patch( 'cosa.training.quantizer.AutoModelForCausalLM.from_pretrained' ) as mock_model_load, \
             patch( 'cosa.training.quantizer.AutoTokenizer.from_pretrained' ) as mock_tokenizer_load, \
             patch( 'cosa.training.quantizer.torch' ):
            
            mock_model_load.return_value = self.mock_model
            mock_tokenizer_load.return_value = self.mock_tokenizer
            
            quantizer = Quantizer( self.test_model_name )
            
            # Verify model loading
            mock_model_load.assert_called_once_with( 
                self.test_model_name, 
                torch_dtype=unittest.mock.ANY,  # torch.float16 
                local_files_only=True, 
                device_map="auto" 
            )
            
            # Verify tokenizer loading
            mock_tokenizer_load.assert_called_once_with( 
                self.test_model_name, 
                local_files_only=True 
            )
            
            # Verify instance attributes
            self.assertEqual( quantizer.model_name, self.test_model_name )
            self.assertEqual( quantizer.model, self.mock_model )
            self.assertEqual( quantizer.tokenizer, self.mock_tokenizer )
            self.assertEqual( quantizer.bits, 4 )
            self.assertEqual( quantizer.quantize_method, "autoround" )
            self.assertTrue( quantizer.symmetrical )
    
    def test_initialization_with_custom_parameters( self ):
        """
        Test Quantizer initialization with custom parameters.
        
        Ensures:
            - Handles local_files_only parameter correctly
            - Uses specified device_map setting
            - Parameters passed to model loading functions
        """
        with patch( 'cosa.training.quantizer.AutoModelForCausalLM.from_pretrained' ) as mock_model_load, \
             patch( 'cosa.training.quantizer.AutoTokenizer.from_pretrained' ) as mock_tokenizer_load, \
             patch( 'cosa.training.quantizer.torch' ):
            
            mock_model_load.return_value = self.mock_model
            mock_tokenizer_load.return_value = self.mock_tokenizer
            
            quantizer = Quantizer( 
                self.test_model_name, 
                local_files_only=False, 
                device_map="cpu" 
            )
            
            # Verify custom parameters passed
            mock_model_load.assert_called_once_with( 
                self.test_model_name, 
                torch_dtype=unittest.mock.ANY,
                local_files_only=False, 
                device_map="cpu" 
            )
            
            mock_tokenizer_load.assert_called_once_with( 
                self.test_model_name, 
                local_files_only=False 
            )
    
    def test_initialization_model_loading_error( self ):
        """
        Test Quantizer initialization with model loading error.
        
        Ensures:
            - Propagates model loading exceptions
            - Does not suppress HuggingFace errors
        """
        with patch( 'cosa.training.quantizer.AutoModelForCausalLM.from_pretrained' ) as mock_model_load, \
             patch( 'cosa.training.quantizer.torch' ):
            
            model_error = ValueError( "Model not found" )
            mock_model_load.side_effect = model_error
            
            with self.assertRaises( ValueError ) as context:
                Quantizer( self.test_model_name )
            
            self.assertIn( "Model not found", str( context.exception ) )
    
    def test_initialization_tokenizer_loading_error( self ):
        """
        Test Quantizer initialization with tokenizer loading error.
        
        Ensures:
            - Propagates tokenizer loading exceptions
            - Does not suppress tokenizer errors
        """
        with patch( 'cosa.training.quantizer.AutoModelForCausalLM.from_pretrained' ) as mock_model_load, \
             patch( 'cosa.training.quantizer.AutoTokenizer.from_pretrained' ) as mock_tokenizer_load, \
             patch( 'cosa.training.quantizer.torch' ):
            
            mock_model_load.return_value = self.mock_model
            tokenizer_error = RuntimeError( "Tokenizer configuration error" )
            mock_tokenizer_load.side_effect = tokenizer_error
            
            with self.assertRaises( RuntimeError ) as context:
                Quantizer( self.test_model_name )
            
            self.assertIn( "Tokenizer configuration error", str( context.exception ) )
    
    def test_quantize_model_autoround_success( self ):
        """
        Test successful model quantization with AutoRound method.
        
        Ensures:
            - Creates AutoRound instance with correct parameters
            - Updates quantizer configuration attributes
            - Calls quantization process with timing
            - Prints progress messages
        """
        with patch( 'cosa.training.quantizer.AutoModelForCausalLM.from_pretrained' ), \
             patch( 'cosa.training.quantizer.AutoTokenizer.from_pretrained' ), \
             patch( 'cosa.training.quantizer.torch' ), \
             patch( 'cosa.training.quantizer.AutoRound' ) as mock_autoround_class, \
             patch( 'cosa.training.quantizer.du.print_banner' ) as mock_print_banner, \
             patch( 'cosa.training.quantizer.Stopwatch' ) as mock_stopwatch_class:
            
            mock_autoround_instance = Mock()
            mock_autoround_class.return_value = mock_autoround_instance
            
            mock_stopwatch = Mock()
            mock_stopwatch_class.return_value = mock_stopwatch
            
            quantizer = Quantizer( self.test_model_name )
            quantizer.quantize_model( 
                quantize_method="autoround",
                batch_size=2,
                bits=8,
                group_size=64,
                sym=False
            )
            
            # Verify AutoRound creation
            mock_autoround_class.assert_called_once_with(
                quantizer.model,
                quantizer.tokenizer,
                nsamples=128,
                iters=512,
                low_gpu_mem_usage=True,
                batch_size=2,
                gradient_accumulation_steps=8,
                bits=8,
                group_size=64,
                sym=False,
                enable_torch_compile=True
            )
            
            # Verify configuration updates
            self.assertEqual( quantizer.bits, 8 )
            self.assertEqual( quantizer.quantize_method, "autoround" )
            self.assertFalse( quantizer.symmetrical )
            
            # Verify quantization called
            mock_autoround_instance.quantize.assert_called_once()
            
            # Verify progress messages
            mock_print_banner.assert_called_once()
            mock_stopwatch.print.assert_called_once_with( msg="Done!" )
    
    def test_quantize_model_default_parameters( self ):
        """
        Test model quantization with default parameters.
        
        Ensures:
            - Uses default parameter values when not specified
            - Creates AutoRound with expected defaults
        """
        with patch( 'cosa.training.quantizer.AutoModelForCausalLM.from_pretrained' ), \
             patch( 'cosa.training.quantizer.AutoTokenizer.from_pretrained' ), \
             patch( 'cosa.training.quantizer.torch' ), \
             patch( 'cosa.training.quantizer.AutoRound' ) as mock_autoround_class, \
             patch( 'cosa.training.quantizer.du.print_banner' ), \
             patch( 'cosa.training.quantizer.Stopwatch' ):
            
            mock_autoround_instance = Mock()
            mock_autoround_class.return_value = mock_autoround_instance
            
            quantizer = Quantizer( self.test_model_name )
            quantizer.quantize_model()
            
            # Verify default parameters used
            mock_autoround_class.assert_called_once_with(
                quantizer.model,
                quantizer.tokenizer,
                nsamples=128,
                iters=512,
                low_gpu_mem_usage=True,
                batch_size=1,  # Default
                gradient_accumulation_steps=8,
                bits=4,  # Default
                group_size=128,  # Default
                sym=True,  # Default
                enable_torch_compile=True
            )
    
    def test_quantize_model_unsupported_method( self ):
        """
        Test model quantization with unsupported method.
        
        Ensures:
            - Raises exception for unsupported quantization methods
            - Provides descriptive error message
        """
        with patch( 'cosa.training.quantizer.AutoModelForCausalLM.from_pretrained' ), \
             patch( 'cosa.training.quantizer.AutoTokenizer.from_pretrained' ), \
             patch( 'cosa.training.quantizer.torch' ):
            
            quantizer = Quantizer( self.test_model_name )
            
            with self.assertRaises( Exception ) as context:
                quantizer.quantize_model( quantize_method="unsupported_method" )
            
            self.assertIn( "Unsupported quantization method: unsupported_method", str( context.exception ) )
    
    def test_quantize_model_autoround_error( self ):
        """
        Test model quantization with AutoRound error.
        
        Ensures:
            - Propagates AutoRound initialization errors
            - Propagates quantization process errors
        """
        with patch( 'cosa.training.quantizer.AutoModelForCausalLM.from_pretrained' ), \
             patch( 'cosa.training.quantizer.AutoTokenizer.from_pretrained' ), \
             patch( 'cosa.training.quantizer.torch' ), \
             patch( 'cosa.training.quantizer.AutoRound' ) as mock_autoround_class:
            
            autoround_error = RuntimeError( "CUDA out of memory" )
            mock_autoround_class.side_effect = autoround_error
            
            quantizer = Quantizer( self.test_model_name )
            
            with self.assertRaises( RuntimeError ) as context:
                quantizer.quantize_model()
            
            self.assertIn( "CUDA out of memory", str( context.exception ) )
    
    def test_save_model_success( self ):
        """
        Test successful quantized model saving.
        
        Ensures:
            - Creates output directory if it doesn't exist
            - Generates properly formatted output path
            - Calls AutoRound save_quantized method
            - Returns full output path
        """
        with patch( 'cosa.training.quantizer.AutoModelForCausalLM.from_pretrained' ), \
             patch( 'cosa.training.quantizer.AutoTokenizer.from_pretrained' ), \
             patch( 'cosa.training.quantizer.torch' ), \
             patch( 'cosa.training.quantizer.AutoRound' ) as mock_autoround_class, \
             patch( 'cosa.training.quantizer.os.path.exists' ) as mock_exists, \
             patch( 'cosa.training.quantizer.os.makedirs' ) as mock_makedirs, \
             patch( 'cosa.training.quantizer.du.get_current_date' ) as mock_get_date, \
             patch( 'cosa.training.quantizer.du.get_current_time' ) as mock_get_time, \
             patch( 'builtins.print' ) as mock_print:
            
            mock_autoround_instance = Mock()
            mock_autoround_class.return_value = mock_autoround_instance
            
            mock_exists.return_value = False  # Directory doesn't exist
            mock_get_date.return_value = "2025-08-05"
            mock_get_time.return_value = "14-30"
            
            quantizer = Quantizer( self.test_model_name )
            quantizer.autoround = mock_autoround_instance  # Simulate quantized model
            
            result = quantizer.save( self.test_output_dir )
            
            # Verify directory creation
            mock_makedirs.assert_called_once()
            
            # Verify save_quantized called
            mock_autoround_instance.save_quantized.assert_called_once()
            
            # Verify return path format
            self.assertIn( "Phi-4-mini-instruct", result )
            self.assertIn( "autoround", result )
            self.assertIn( "4-bits", result )
            self.assertIn( "sym", result )
            self.assertIn( "2025-08-05", result )
    
    def test_save_model_without_model_name( self ):
        """
        Test model saving without including model name in path.
        
        Ensures:
            - Generates path without model name when include_model_name=False
            - Uses generic quantization parameters in path
        """
        with patch( 'cosa.training.quantizer.AutoModelForCausalLM.from_pretrained' ), \
             patch( 'cosa.training.quantizer.AutoTokenizer.from_pretrained' ), \
             patch( 'cosa.training.quantizer.torch' ), \
             patch( 'cosa.training.quantizer.AutoRound' ) as mock_autoround_class, \
             patch( 'cosa.training.quantizer.os.path.exists' ) as mock_exists, \
             patch( 'cosa.training.quantizer.os.makedirs' ), \
             patch( 'cosa.training.quantizer.du.get_current_date' ) as mock_get_date, \
             patch( 'cosa.training.quantizer.du.get_current_time' ) as mock_get_time, \
             patch( 'builtins.print' ):
            
            mock_autoround_instance = Mock()
            mock_autoround_class.return_value = mock_autoround_instance
            
            mock_exists.return_value = True  # Directory exists
            mock_get_date.return_value = "2025-08-05"
            mock_get_time.return_value = "14-30"
            
            quantizer = Quantizer( self.test_model_name )
            quantizer.autoround = mock_autoround_instance
            
            result = quantizer.save( self.test_output_dir, include_model_name=False )
            
            # Verify path doesn't include model name
            self.assertNotIn( "Phi-4-mini-instruct", result )
            self.assertIn( "autoround", result )
            self.assertIn( "4-bits", result )
    
    def test_save_model_asymmetric_quantization( self ):
        """
        Test model saving with asymmetric quantization flag.
        
        Ensures:
            - Uses "asym" flag in path when symmetrical=False
            - Path reflects quantization configuration
        """
        with patch( 'cosa.training.quantizer.AutoModelForCausalLM.from_pretrained' ), \
             patch( 'cosa.training.quantizer.AutoTokenizer.from_pretrained' ), \
             patch( 'cosa.training.quantizer.torch' ), \
             patch( 'cosa.training.quantizer.AutoRound' ) as mock_autoround_class, \
             patch( 'cosa.training.quantizer.os.path.exists' ) as mock_exists, \
             patch( 'cosa.training.quantizer.os.makedirs' ), \
             patch( 'cosa.training.quantizer.du.get_current_date' ) as mock_get_date, \
             patch( 'cosa.training.quantizer.du.get_current_time' ) as mock_get_time, \
             patch( 'builtins.print' ):
            
            mock_autoround_instance = Mock()
            mock_autoround_class.return_value = mock_autoround_instance
            
            mock_exists.return_value = True
            mock_get_date.return_value = "2025-08-05"
            mock_get_time.return_value = "14-30"
            
            quantizer = Quantizer( self.test_model_name )
            quantizer.autoround = mock_autoround_instance
            quantizer.symmetrical = False  # Asymmetric quantization
            
            result = quantizer.save( self.test_output_dir )
            
            # Verify asymmetric flag in path
            self.assertIn( "asym", result )
            self.assertIn( "asym.gptq", result )  # Should be asym.gptq
    
    def test_save_model_directory_creation_error( self ):
        """
        Test model saving with directory creation error.
        
        Ensures:
            - Propagates directory creation errors
            - Does not suppress filesystem errors
        """
        with patch( 'cosa.training.quantizer.AutoModelForCausalLM.from_pretrained' ), \
             patch( 'cosa.training.quantizer.AutoTokenizer.from_pretrained' ), \
             patch( 'cosa.training.quantizer.torch' ), \
             patch( 'cosa.training.quantizer.AutoRound' ) as mock_autoround_class, \
             patch( 'cosa.training.quantizer.os.path.exists' ) as mock_exists, \
             patch( 'cosa.training.quantizer.os.makedirs' ) as mock_makedirs, \
             patch( 'cosa.training.quantizer.du.get_current_date' ), \
             patch( 'cosa.training.quantizer.du.get_current_time' ):
            
            mock_autoround_instance = Mock()
            mock_autoround_class.return_value = mock_autoround_instance
            
            mock_exists.return_value = False
            mkdir_error = OSError( "Permission denied" )
            mock_makedirs.side_effect = mkdir_error
            
            quantizer = Quantizer( self.test_model_name )
            quantizer.autoround = mock_autoround_instance
            
            with self.assertRaises( OSError ) as context:
                quantizer.save( self.test_output_dir )
            
            self.assertIn( "Permission denied", str( context.exception ) )
    
    def test_save_model_without_quantization( self ):
        """
        Test model saving without prior quantization.
        
        Ensures:
            - Raises appropriate error when autoround not initialized
            - Provides descriptive error message
        """
        with patch( 'cosa.training.quantizer.AutoModelForCausalLM.from_pretrained' ), \
             patch( 'cosa.training.quantizer.AutoTokenizer.from_pretrained' ), \
             patch( 'cosa.training.quantizer.torch' ), \
             patch( 'cosa.training.quantizer.du.get_current_date' ), \
             patch( 'cosa.training.quantizer.du.get_current_time' ):
            
            quantizer = Quantizer( self.test_model_name )
            # Don't call quantize_model - autoround not initialized
            
            with self.assertRaises( AttributeError ):
                quantizer.save( self.test_output_dir )
    
    def test_cli_interface_success( self ):
        """
        Test successful CLI interface execution.
        
        Ensures:
            - Parses command line arguments correctly
            - Creates Quantizer with model name
            - Calls quantization and save methods
            - Handles optional bits parameter
        """
        test_args = ["quantizer.py", self.test_model_name, self.test_output_dir, "8"]
        
        with patch( 'sys.argv', test_args ), \
             patch( 'cosa.training.quantizer.Quantizer' ) as mock_quantizer_class:
            
            mock_quantizer = Mock()
            mock_quantizer_class.return_value = mock_quantizer
            
            # Execute main block
            exec( compile( open( "/mnt/DATA01/include/www.deepily.ai/projects/lupin/src/cosa/training/quantizer.py" ).read(), 
                          "quantizer.py", "exec" ) )
            
            # Verify quantizer creation
            mock_quantizer_class.assert_called_once_with( self.test_model_name )
            
            # Verify quantization called with custom bits
            mock_quantizer.quantize_model.assert_called_once_with( bits=8 )
            
            # Verify save called
            mock_quantizer.save.assert_called_once_with( self.test_output_dir, include_model_name=True )
    
    def test_cli_interface_default_bits( self ):
        """
        Test CLI interface with default bits parameter.
        
        Ensures:
            - Uses default bits value when not specified
            - Handles 3-argument case correctly
        """
        test_args = ["quantizer.py", self.test_model_name, self.test_output_dir]
        
        with patch( 'sys.argv', test_args ), \
             patch( 'cosa.training.quantizer.Quantizer' ) as mock_quantizer_class:
            
            mock_quantizer = Mock()
            mock_quantizer_class.return_value = mock_quantizer
            
            # Execute main block
            exec( compile( open( "/mnt/DATA01/include/www.deepily.ai/projects/lupin/src/cosa/training/quantizer.py" ).read(), 
                          "quantizer.py", "exec" ) )
            
            # Verify quantization called with default bits
            mock_quantizer.quantize_model.assert_called_once_with( bits=4 )
    
    def test_cli_interface_insufficient_arguments( self ):
        """
        Test CLI interface with insufficient arguments.
        
        Ensures:
            - Prints usage message for insufficient arguments
            - Exits with error code 1
        """
        test_args = ["quantizer.py", self.test_model_name]  # Missing save_to_path
        
        with patch( 'sys.argv', test_args ), \
             patch( 'builtins.print' ) as mock_print, \
             patch( 'sys.exit' ) as mock_exit:
            
            # Execute main block
            exec( compile( open( "/mnt/DATA01/include/www.deepily.ai/projects/lupin/src/cosa/training/quantizer.py" ).read(), 
                          "quantizer.py", "exec" ) )
            
            # Verify usage message
            mock_print.assert_called_with( "Usage: python quantizer.py <model_name> <save_to_path> <bits>" )
            mock_exit.assert_called_with( 1 )


def isolated_unit_test():
    """
    Run comprehensive unit tests for model quantizer in complete isolation.
    
    Ensures:
        - All external dependencies mocked
        - No real model loading or quantization operations
        - Deterministic test results
        - Fast execution
        
    Returns:
        Tuple[bool, float, str]: (success, duration, message)
    """
    import cosa.utils.util as du
    
    start_time = time.time()
    
    try:
        du.print_banner( "Model Quantizer Unit Tests - Training Phase 6", prepend_nl=True )
        
        # Create test suite
        suite = unittest.TestSuite()
        
        # Add all test methods
        test_methods = [
            'test_initialization_success',
            'test_initialization_with_custom_parameters',
            'test_initialization_model_loading_error',
            'test_initialization_tokenizer_loading_error',
            'test_quantize_model_autoround_success',
            'test_quantize_model_default_parameters',
            'test_quantize_model_unsupported_method',
            'test_quantize_model_autoround_error',
            'test_save_model_success',
            'test_save_model_without_model_name',
            'test_save_model_asymmetric_quantization',
            'test_save_model_directory_creation_error',
            'test_save_model_without_quantization'
        ]
        
        for method in test_methods:
            suite.addTest( TestQuantizer( method ) )
        
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
        print( f"MODEL QUANTIZER UNIT TEST RESULTS" )
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
            du.print_banner( "✅ ALL MODEL QUANTIZER TESTS PASSED", prepend_nl=True )
            message = f"All {tests_run} tests passed successfully in {duration:.3f}s"
        else:
            du.print_banner( "❌ SOME MODEL QUANTIZER TESTS FAILED", prepend_nl=True )
            message = f"{failures} failures, {errors} errors out of {tests_run} tests"
        
        return success, duration, message
        
    except Exception as e:
        duration = time.time() - start_time
        error_msg = f"Unit test execution failed: {str(e)}"
        du.print_banner( f"💥 MODEL QUANTIZER TEST ERROR: {error_msg}", prepend_nl=True )
        return False, duration, error_msg


if __name__ == "__main__":
    success, duration, message = isolated_unit_test()
    status = "✅ PASS" if success else "❌ FAIL"
    print( f"\n{status} Model quantizer unit tests completed in {duration:.3f}s" )
    print( f"Result: {message}" )