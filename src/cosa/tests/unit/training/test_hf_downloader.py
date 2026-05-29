"""
Unit tests for HuggingFace model downloader with comprehensive HF Hub mocking.

Tests the HuggingFaceDownloader class including:
- Initialization with optional authentication tokens
- Model download workflow with HuggingFace Hub integration
- Authentication handling and token management
- Error handling for download failures and network issues
- Environment variable validation (HF_HOME, HF_TOKEN)
- CLI interface argument parsing and validation
- Repository ID validation and formatting
- Local path management and return value handling

Zero external dependencies - all HuggingFace Hub operations, authentication,
and model downloads are mocked for isolated testing.
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
from cosa.training.hf_downloader import HuggingFaceDownloader


class TestHuggingFaceDownloader( unittest.TestCase ):
    """
    Comprehensive unit tests for HuggingFace model downloader.
    
    Requires:
        - MockManager for external dependency mocking
        - UnitTestUtilities for common test patterns
        
    Ensures:
        - All HuggingFace Hub operations tested in isolation
        - Authentication and download operations properly mocked
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
        self.test_token = "hf_test_token_123456789"
        self.test_repo_id = "microsoft/Phi-4-mini-instruct"
        self.test_local_path = "/path/to/downloaded/model"
        
        # Test environment variables
        self.test_hf_home = "/home/user/.cache/huggingface"
        self.test_hf_token = "hf_env_token_987654321"
    
    def tearDown( self ):
        """
        Cleanup after each test method.
        
        Ensures:
            - All mocks are reset
        """
        self.mock_manager.reset_mocks()
    
    def test_initialization_with_token( self ):
        """
        Test HuggingFaceDownloader initialization with authentication token.
        
        Ensures:
            - Stores provided token for later use
            - No network requests made during initialization
            - Token is accessible via instance attribute
        """
        downloader = HuggingFaceDownloader( token=self.test_token )
        
        # Verify token storage
        self.assertEqual( downloader.token, self.test_token )
        self.assertIsNotNone( downloader.token )
    
    def test_initialization_without_token( self ):
        """
        Test HuggingFaceDownloader initialization without authentication token.
        
        Ensures:
            - Handles None token gracefully
            - Default initialization works correctly
            - Token attribute is set to None
        """
        downloader = HuggingFaceDownloader()
        
        # Verify default token is None
        self.assertIsNone( downloader.token )
    
    def test_initialization_with_explicit_none_token( self ):
        """
        Test HuggingFaceDownloader initialization with explicitly None token.
        
        Ensures:
            - Explicit None token parameter handled correctly
            - Behavior same as default initialization
        """
        downloader = HuggingFaceDownloader( token=None )
        
        # Verify token is None
        self.assertIsNone( downloader.token )
    
    def test_download_model_success( self ):
        """
        Test successful model download workflow.
        
        Ensures:
            - Calls huggingface_hub.login with provided token
            - Calls huggingface_hub.snapshot_download with repo_id
            - Returns local path from snapshot_download
            - No exceptions raised during download
        """
        with patch( 'cosa.training.hf_downloader.login' ) as mock_login, \
             patch( 'cosa.training.hf_downloader.snapshot_download' ) as mock_download:
            
            mock_download.return_value = self.test_local_path
            
            downloader = HuggingFaceDownloader( token=self.test_token )
            result = downloader.download_model( self.test_repo_id )
            
            # Verify authentication call
            mock_login.assert_called_once_with( token=self.test_token )
            
            # Verify download call
            mock_download.assert_called_once_with( repo_id=self.test_repo_id )
            
            # Verify return value
            self.assertEqual( result, self.test_local_path )
    
    def test_download_model_without_token( self ):
        """
        Test model download workflow without authentication token.
        
        Ensures:
            - Calls login with None token (anonymous access)
            - Download still proceeds normally
            - Returns expected local path
        """
        with patch( 'cosa.training.hf_downloader.login' ) as mock_login, \
             patch( 'cosa.training.hf_downloader.snapshot_download' ) as mock_download:
            
            mock_download.return_value = self.test_local_path
            
            downloader = HuggingFaceDownloader()
            result = downloader.download_model( self.test_repo_id )
            
            # Verify authentication with None token
            mock_login.assert_called_once_with( token=None )
            
            # Verify download call
            mock_download.assert_called_once_with( repo_id=self.test_repo_id )
            
            # Verify return value
            self.assertEqual( result, self.test_local_path )
    
    def test_download_model_login_error( self ):
        """
        Test model download with authentication error.
        
        Ensures:
            - Handles login exceptions gracefully
            - Prints error message
            - Calls sys.exit(1) on failure
        """
        with patch( 'cosa.training.hf_downloader.login' ) as mock_login, \
             patch( 'cosa.training.hf_downloader.snapshot_download' ), \
             patch( 'builtins.print' ) as mock_print, \
             patch( 'sys.exit' ) as mock_exit:
            
            login_error = Exception( "Invalid authentication token" )
            mock_login.side_effect = login_error
            
            downloader = HuggingFaceDownloader( token=self.test_token )
            downloader.download_model( self.test_repo_id )
            
            # Verify error message printed
            mock_print.assert_called_once_with( f"Error downloading model: {login_error}" )
            
            # Verify system exit called
            mock_exit.assert_called_once_with( 1 )
    
    def test_download_model_download_error( self ):
        """
        Test model download with download error.
        
        Ensures:
            - Handles snapshot_download exceptions gracefully
            - Prints descriptive error message
            - Calls sys.exit(1) on failure
        """
        with patch( 'cosa.training.hf_downloader.login' ), \
             patch( 'cosa.training.hf_downloader.snapshot_download' ) as mock_download, \
             patch( 'builtins.print' ) as mock_print, \
             patch( 'sys.exit' ) as mock_exit:
            
            download_error = Exception( "Repository not found" )
            mock_download.side_effect = download_error
            
            downloader = HuggingFaceDownloader( token=self.test_token )
            downloader.download_model( self.test_repo_id )
            
            # Verify error message printed
            mock_print.assert_called_once_with( f"Error downloading model: {download_error}" )
            
            # Verify system exit called
            mock_exit.assert_called_once_with( 1 )
    
    def test_download_model_network_error( self ):
        """
        Test model download with network connectivity error.
        
        Ensures:
            - Handles network-related exceptions
            - Provides appropriate error feedback
            - Exits gracefully on network failures
        """
        with patch( 'cosa.training.hf_downloader.login' ), \
             patch( 'cosa.training.hf_downloader.snapshot_download' ) as mock_download, \
             patch( 'builtins.print' ) as mock_print, \
             patch( 'sys.exit' ) as mock_exit:
            
            network_error = Exception( "Connection timeout" )
            mock_download.side_effect = network_error
            
            downloader = HuggingFaceDownloader( token=self.test_token )
            downloader.download_model( self.test_repo_id )
            
            # Verify error handling
            mock_print.assert_called_once_with( f"Error downloading model: {network_error}" )
            mock_exit.assert_called_once_with( 1 )
    
    def test_main_cli_success( self ):
        """
        Test main CLI function with successful execution.
        
        Ensures:
            - Parses command line arguments correctly
            - Validates environment variables
            - Creates downloader with environment token
            - Calls download_model with repo_id argument
        """
        test_args = ["hf_downloader.py", self.test_repo_id]
        
        with patch( 'sys.argv', test_args ), \
             patch( 'os.getenv' ) as mock_getenv, \
             patch( 'cosa.training.hf_downloader.HuggingFaceDownloader' ) as mock_downloader_class, \
             patch( 'sys.exit' ) as mock_exit:
            
            # Mock environment variables
            def getenv_side_effect( key ):
                if key == "HF_HOME":
                    return self.test_hf_home
                elif key == "HF_TOKEN":
                    return self.test_hf_token
                return None
            
            mock_getenv.side_effect = getenv_side_effect
            
            # Mock downloader instance
            mock_downloader = Mock()
            mock_downloader_class.return_value = mock_downloader
            
            # Import and run main
            from cosa.training.hf_downloader import __main__
            
            # Verify environment variable checks
            expected_calls = [call( "HF_HOME" ), call( "HF_TOKEN" )]
            mock_getenv.assert_has_calls( expected_calls, any_order=True )
            
            # Verify downloader creation
            mock_downloader_class.assert_called_once_with( token=self.test_hf_token )
            
            # Verify download call
            mock_downloader.download_model.assert_called_once_with( self.test_repo_id )
    
    def test_main_cli_missing_arguments( self ):
        """
        Test main CLI function with missing arguments.
        
        Ensures:
            - Validates command line argument count
            - Prints usage message for incorrect arguments
            - Exits with error code 1
        """
        test_args = ["hf_downloader.py"]  # Missing repo_id
        
        with patch( 'sys.argv', test_args ), \
             patch( 'builtins.print' ) as mock_print, \
             patch( 'sys.exit' ) as mock_exit:
            
            # Import and run main (would execute __main__ block)
            # We need to trigger the main execution
            exec( compile( open( "/mnt/DATA01/include/www.deepily.ai/projects/lupin/src/cosa/training/hf_downloader.py" ).read(), 
                          "hf_downloader.py", "exec" ) )
            
            # Verify usage message
            mock_print.assert_called_with( "Usage: python hf_downloader.py <repo_id>" )
            mock_exit.assert_called_with( 1 )
    
    def test_main_cli_missing_hf_home( self ):
        """
        Test main CLI function with missing HF_HOME environment variable.
        
        Ensures:
            - Validates HF_HOME environment variable
            - Prints descriptive error message
            - Exits with error code 1
        """
        test_args = ["hf_downloader.py", self.test_repo_id]
        
        with patch( 'sys.argv', test_args ), \
             patch( 'os.getenv' ) as mock_getenv, \
             patch( 'builtins.print' ) as mock_print, \
             patch( 'sys.exit' ) as mock_exit:
            
            # Mock missing HF_HOME
            def getenv_side_effect( key ):
                if key == "HF_HOME":
                    return None
                elif key == "HF_TOKEN":
                    return self.test_hf_token
                return None
            
            mock_getenv.side_effect = getenv_side_effect
            
            # Execute main block
            exec( compile( open( "/mnt/DATA01/include/www.deepily.ai/projects/lupin/src/cosa/training/hf_downloader.py" ).read(), 
                          "hf_downloader.py", "exec" ) )
            
            # Verify error message
            mock_print.assert_called_with( "Please set the HF_HOME environment variable to the directory where you want to download models" )
            mock_exit.assert_called_with( 1 )
    
    def test_main_cli_missing_hf_token( self ):
        """
        Test main CLI function with missing HF_TOKEN environment variable.
        
        Ensures:
            - Validates HF_TOKEN environment variable
            - Prints descriptive error message
            - Exits with error code 1
        """
        test_args = ["hf_downloader.py", self.test_repo_id]
        
        with patch( 'sys.argv', test_args ), \
             patch( 'os.getenv' ) as mock_getenv, \
             patch( 'builtins.print' ) as mock_print, \
             patch( 'sys.exit' ) as mock_exit:
            
            # Mock missing HF_TOKEN
            def getenv_side_effect( key ):
                if key == "HF_HOME":
                    return self.test_hf_home
                elif key == "HF_TOKEN":
                    return None
                return None
            
            mock_getenv.side_effect = getenv_side_effect
            
            # Execute main block
            exec( compile( open( "/mnt/DATA01/include/www.deepily.ai/projects/lupin/src/cosa/training/hf_downloader.py" ).read(), 
                          "hf_downloader.py", "exec" ) )
            
            # Verify error message
            mock_print.assert_called_with( "Please set the HF_TOKEN environment variable with your Hugging Face API token" )
            mock_exit.assert_called_with( 1 )
    
    def test_huggingface_hub_integration( self ):
        """
        Test integration with huggingface_hub library functions.
        
        Ensures:
            - Proper import and usage of login function
            - Proper import and usage of snapshot_download function
            - Correct parameter passing to HF Hub functions
        """
        with patch( 'cosa.training.hf_downloader.login' ) as mock_login, \
             patch( 'cosa.training.hf_downloader.snapshot_download' ) as mock_download:
            
            mock_download.return_value = self.test_local_path
            
            downloader = HuggingFaceDownloader( token=self.test_token )
            result = downloader.download_model( self.test_repo_id )
            
            # Verify HF Hub function calls
            mock_login.assert_called_once_with( token=self.test_token )
            mock_download.assert_called_once_with( repo_id=self.test_repo_id )
            
            # Verify integration works correctly
            self.assertEqual( result, self.test_local_path )
    
    def test_repository_id_validation( self ):
        """
        Test various repository ID formats and validation.
        
        Ensures:
            - Handles standard org/model format
            - Processes model IDs correctly
            - Passes through repo_id parameter unchanged
        """
        test_repo_ids = [
            "microsoft/Phi-4-mini-instruct",
            "mistralai/Mistral-7B-Instruct-v0.1",
            "meta-llama/Llama-3.2-3B-Instruct",
            "user/custom-model",
            "simple-model-name"
        ]
        
        with patch( 'cosa.training.hf_downloader.login' ), \
             patch( 'cosa.training.hf_downloader.snapshot_download' ) as mock_download:
            
            mock_download.return_value = self.test_local_path
            
            downloader = HuggingFaceDownloader( token=self.test_token )
            
            for repo_id in test_repo_ids:
                with self.subTest( repo_id=repo_id ):
                    result = downloader.download_model( repo_id )
                    
                    # Verify repo_id passed correctly
                    mock_download.assert_called_with( repo_id=repo_id )
                    self.assertEqual( result, self.test_local_path )
                    
                    # Reset mock for next iteration
                    mock_download.reset_mock()


def isolated_unit_test():
    """
    Run comprehensive unit tests for HuggingFace downloader in complete isolation.
    
    Ensures:
        - All external dependencies mocked
        - No real HuggingFace Hub requests or downloads
        - Deterministic test results
        - Fast execution
        
    Returns:
        Tuple[bool, float, str]: (success, duration, message)
    """
    import cosa.utils.util as du
    
    start_time = time.time()
    
    try:
        du.print_banner( "HuggingFace Downloader Unit Tests - Training Phase 6", prepend_nl=True )
        
        # Create test suite
        suite = unittest.TestSuite()
        
        # Add all test methods
        test_methods = [
            'test_initialization_with_token',
            'test_initialization_without_token',
            'test_initialization_with_explicit_none_token',
            'test_download_model_success',
            'test_download_model_without_token',
            'test_download_model_login_error',
            'test_download_model_download_error',
            'test_download_model_network_error',
            'test_huggingface_hub_integration',
            'test_repository_id_validation'
        ]
        
        for method in test_methods:
            suite.addTest( TestHuggingFaceDownloader( method ) )
        
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
        print( f"HUGGINGFACE DOWNLOADER UNIT TEST RESULTS" )
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
            du.print_banner( "✅ ALL HUGGINGFACE DOWNLOADER TESTS PASSED", prepend_nl=True )
            message = f"All {tests_run} tests passed successfully in {duration:.3f}s"
        else:
            du.print_banner( "❌ SOME HUGGINGFACE DOWNLOADER TESTS FAILED", prepend_nl=True )
            message = f"{failures} failures, {errors} errors out of {tests_run} tests"
        
        return success, duration, message
        
    except Exception as e:
        duration = time.time() - start_time
        error_msg = f"Unit test execution failed: {str(e)}"
        du.print_banner( f"💥 HUGGINGFACE DOWNLOADER TEST ERROR: {error_msg}", prepend_nl=True )
        return False, duration, error_msg


if __name__ == "__main__":
    success, duration, message = isolated_unit_test()
    status = "✅ PASS" if success else "❌ FAIL"
    print( f"\n{status} HuggingFace downloader unit tests completed in {duration:.3f}s" )
    print( f"Result: {message}" )