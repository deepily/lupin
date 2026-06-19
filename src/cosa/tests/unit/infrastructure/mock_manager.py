"""
Centralized Mock Management for CoSA Unit Tests

Provides comprehensive mocking capabilities for all external dependencies
including file systems, APIs, databases, and configuration systems.

Usage:
    from mock_manager import MockManager
    
    # Create file system mock
    with MockManager.filesystem_mock() as fs_mock:
        # Test code here
        
    # Create API mock  
    with MockManager.api_mock( "openai" ) as api_mock:
        # Test code here
"""

import os
import tempfile
import json
from typing import Dict, Any, Optional, List, Callable
from unittest.mock import Mock, patch, MagicMock
from contextlib import contextmanager
import configparser


class MockManager:
    """
    Centralized mock management for CoSA framework unit tests.
    
    Provides context managers and factory methods for creating consistent,
    reusable mocks across all test categories. Ensures proper cleanup and
    isolation between test runs.
    
    Requires:
        - unittest.mock module available
        - tempfile module for temporary file operations
        
    Ensures:
        - All mocks are properly scoped and cleaned up
        - Consistent mock behavior across test suites
        - Easy configuration of mock responses and behaviors
        
    Raises:
        - ImportError if required mocking modules unavailable
        - ValueError if invalid mock configuration provided
    """
    
    _instance = None
    _mock_registry = {}
    
    def __new__( cls ):
        """
        Singleton pattern for mock manager.
        
        Ensures:
            - Single mock manager instance across test suite
            - Consistent mock state management
        """
        if cls._instance is None:
            cls._instance = super().__new__( cls )
            cls._instance._initialized = False
        return cls._instance
    
    def __init__( self ):
        """
        Initialize mock manager with default configurations.
        
        Ensures:
            - Default mock configurations loaded
            - Mock registry initialized
            - Cleanup handlers registered
        """
        if not self._initialized:
            self._mock_registry = {}
            self._default_configs = self._load_default_configs()
            self._initialized = True
    
    def _load_default_configs( self ) -> Dict[str, Any]:
        """
        Load default mock configurations for common scenarios.
        
        Ensures:
            - Consistent default values across all mocks
            - Realistic mock responses for CoSA components
            
        Returns:
            Dictionary of default mock configurations
        """
        return {
            "config_manager": {
                "app debug": False,
                "agent_timeout": 30,
                "openai_api_key": "test_key_12345",
                "agent_math_prompt_template": "Solve: {question}",
                "embedding_model": "text-embedding-ada-002"
            },
            "openai_api": {
                "embedding_response": {
                    "data": [{"embedding": [0.1] * 1536}],
                    "usage": {"total_tokens": 10}
                },
                "completion_response": {
                    "choices": [{"message": {"content": "Test response"}}],
                    "usage": {"total_tokens": 15}
                }
            },
            "file_system": {
                "config_files": {
                    "lupin-app.ini": "[DEFAULT]\napp_debug = false\n",
                    "lupin-app-splainer.ini": "[DEFAULT]\napp_debug = Debug mode flag\n"
                }
            }
        }
    
    @contextmanager
    def filesystem_mock( self, mock_files: Optional[Dict[str, str]] = None ):
        """
        Create a mocked file system for testing file I/O operations.
        
        Requires:
            - mock_files is a dictionary mapping file paths to content strings
            
        Ensures:
            - File operations are intercepted and use mock data
            - Temporary directories are properly cleaned up
            - File existence checks work correctly
            
        Args:
            mock_files: Dictionary of file paths to file contents
            
        Yields:
            Mock file system object with read/write capabilities
        """
        if mock_files is None:
            mock_files = self._default_configs[ "file_system" ][ "config_files" ]
        
        # Create temporary directory for mock files
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create mock files in temporary directory
            for file_path, content in mock_files.items():
                full_path = os.path.join( temp_dir, file_path )
                os.makedirs( os.path.dirname( full_path ), exist_ok=True )
                with open( full_path, "w" ) as f:
                    f.write( content )
            
            # Mock file system operations
            original_exists = os.path.exists
            original_open = open
            
            def mock_exists( path ):
                # Check if path exists in our mock directory first
                mock_path = os.path.join( temp_dir, os.path.basename( path ) )
                if os.path.exists( mock_path ):
                    return True
                return original_exists( path )
            
            def mock_open( file_path, mode="r", **kwargs ):
                # Redirect to mock directory if file exists there
                mock_path = os.path.join( temp_dir, os.path.basename( file_path ) )
                if os.path.exists( mock_path ):
                    return original_open( mock_path, mode, **kwargs )
                return original_open( file_path, mode, **kwargs )
            
            with patch( "os.path.exists", side_effect=mock_exists ), \
                 patch( "builtins.open", side_effect=mock_open ):
                
                mock_fs = MagicMock()
                mock_fs.temp_dir = temp_dir
                mock_fs.mock_files = mock_files
                
                yield mock_fs
    
    @contextmanager
    def config_manager_mock( self, config_values: Optional[Dict[str, Any]] = None ):
        """
        Create a mocked ConfigurationManager for testing.
        
        Requires:
            - config_values is a dictionary of configuration key-value pairs
            
        Ensures:
            - Configuration manager returns consistent test values
            - Singleton behavior is properly mocked
            - No real configuration files are accessed
            
        Args:
            config_values: Dictionary of configuration values to return
            
        Yields:
            Mocked ConfigurationManager instance
        """
        if config_values is None:
            config_values = self._default_configs[ "config_manager" ]
        
        mock_config_mgr = MagicMock()
        
        def mock_get( key, default=None, return_type="string" ):
            value = config_values.get( key, default )
            
            if return_type == "boolean":
                if isinstance( value, str ):
                    return value.lower() in ( "true", "1", "yes" )
                return bool( value )
            elif return_type == "int":
                return int( value ) if value is not None else default
            elif return_type == "float":
                return float( value ) if value is not None else default
            else:
                return str( value ) if value is not None else default
        
        mock_config_mgr.get = mock_get
        mock_config_mgr.config_values = config_values
        
        with patch( "cosa.config.configuration_manager.ConfigurationManager" ) as MockConfigClass:
            MockConfigClass.return_value = mock_config_mgr
            MockConfigClass.side_effect = lambda *args, **kwargs: mock_config_mgr
            yield mock_config_mgr
    
    @contextmanager  
    def openai_api_mock( self, responses: Optional[Dict[str, Any]] = None ):
        """
        Create a mocked OpenAI API for testing LLM integrations.
        
        Requires:
            - responses is a dictionary of API endpoint responses
            
        Ensures:
            - No actual API calls are made
            - Consistent response formats returned
            - API errors can be simulated
            
        Args:
            responses: Dictionary of API responses for different endpoints
            
        Yields:
            Mocked OpenAI API client
        """
        if responses is None:
            responses = self._default_configs[ "openai_api" ]
        
        mock_client = MagicMock()
        
        # Mock embeddings endpoint
        mock_embeddings = MagicMock()
        mock_embeddings.create.return_value = MagicMock( 
            **responses[ "embedding_response" ]
        )
        mock_client.embeddings = mock_embeddings
        
        # Mock completions endpoint  
        mock_completions = MagicMock()
        mock_completions.create.return_value = MagicMock(
            **responses[ "completion_response" ]
        )
        mock_client.chat = MagicMock()
        mock_client.chat.completions = mock_completions
        
        with patch( "openai.OpenAI" ) as MockOpenAI:
            MockOpenAI.return_value = mock_client
            yield mock_client
    
    @contextmanager
    def environment_mock( self, env_vars: Dict[str, str] ):
        """
        Create a mocked environment for testing environment variable usage.
        
        Requires:
            - env_vars is a dictionary of environment variable names to values
            
        Ensures:
            - Environment variables return consistent test values
            - Original environment is restored after testing
            
        Args:
            env_vars: Dictionary of environment variable values
            
        Yields:
            Mocked environment context
        """
        original_env = os.environ.copy()
        
        try:
            # Clear environment and set test values
            os.environ.clear()
            os.environ.update( env_vars )
            yield os.environ
        finally:
            # Restore original environment
            os.environ.clear()
            os.environ.update( original_env )
    
    @contextmanager
    def time_mock( self, fixed_time: float = 1609459200.0 ):  # 2021-01-01 00:00:00 UTC
        """
        Create a mocked time system for testing time-dependent functionality.
        
        Requires:
            - fixed_time is a float representing Unix timestamp
            
        Ensures:
            - Consistent time values across test runs
            - Time-dependent code behaves predictably
            
        Args:
            fixed_time: Unix timestamp to use as fixed time
            
        Yields:
            Mocked time module
        """
        with patch( "time.time", return_value=fixed_time ), \
             patch( "time.sleep" ) as mock_sleep:
            
            mock_time = MagicMock()
            mock_time.time.return_value = fixed_time
            mock_time.sleep = mock_sleep
            yield mock_time
    
    def create_test_fixtures( self ) -> Dict[str, Any]:
        """
        Create standard test fixtures for CoSA components.
        
        Ensures:
            - Consistent test data across all test suites
            - Realistic data structures for testing
            - Edge cases and error conditions covered
            
        Returns:
            Dictionary of test fixtures organized by component type
        """
        return {
            "agent_questions": [
                "What is 2 + 2?",
                "Calculate the area of a circle with radius 5",
                "What's the weather like today?",
                "What time is it in New York?"
            ],
            "llm_responses": [
                "The answer is 4.",
                "The area is approximately 78.54 square units.",
                "I need current weather data to answer that.",
                "I need current time data to answer that."
            ],
            "xml_responses": [
                "<response><thoughts>Simple addition</thoughts><code>2 + 2</code><returns>4</returns></response>",
                "<response><error>Invalid input format</error></response>"
            ],
            "embeddings": [
                [0.1] * 1536,  # Standard embedding size
                [0.2] * 1536,
                [0.0] * 1536   # Zero vector for edge case
            ],
            "config_scenarios": [
                { "valid_config": True, "debug": False, "timeout": 30 },
                { "valid_config": True, "debug": True, "timeout": 60 },
                { "valid_config": False, "missing_key": True }
            ]
        }
    
    def reset_mocks( self ):
        """
        Reset all registered mocks to clean state.
        
        Ensures:
            - Clean state between test runs
            - No mock leakage between tests
        """
        self._mock_registry.clear()
    
    def register_mock( self, name: str, mock_obj: Any ):
        """
        Register a named mock for reuse across tests.
        
        Requires:
            - name is a unique string identifier
            - mock_obj is a valid mock object
            
        Ensures:
            - Mock is stored for later retrieval
            - Consistent mock instances across tests
        """
        self._mock_registry[ name ] = mock_obj
    
    def get_mock( self, name: str ) -> Optional[Any]:
        """
        Retrieve a previously registered mock by name.
        
        Requires:
            - name is a string identifier for registered mock
            
        Returns:
            Mock object if found, None otherwise
        """
        return self._mock_registry.get( name )


# Global mock manager instance
mock_manager = MockManager()


def isolated_unit_test():
    """
    Quick smoke test for MockManager functionality.
    
    Ensures:
        - Mock manager can be instantiated
        - Basic mocking capabilities work
        - Context managers function properly
        
    Returns:
        Tuple[bool, float, str]: (success, duration, error_message)
    """
    import time
    start_time = time.time()
    
    try:
        # Test basic instantiation
        mgr = MockManager()
        assert mgr is not None, "Failed to create MockManager instance"
        
        # Test filesystem mock
        with mgr.filesystem_mock() as fs_mock:
            assert fs_mock.temp_dir is not None, "Filesystem mock failed"
        
        # Test config manager mock
        with mgr.config_manager_mock() as config_mock:
            value = config_mock.get( "app debug", default=False, return_type="boolean" )
            assert isinstance( value, bool ), "Config mock failed"
        
        # Test fixtures creation
        fixtures = mgr.create_test_fixtures()
        assert "agent_questions" in fixtures, "Fixtures creation failed"
        assert len( fixtures[ "agent_questions" ] ) > 0, "Empty fixtures"
        
        duration = time.time() - start_time
        return True, duration, ""
        
    except Exception as e:
        duration = time.time() - start_time
        return False, duration, f"MockManager test failed: {str( e )}"


if __name__ == "__main__":
    success, duration, error = isolated_unit_test()
    status = "✅ PASS" if success else "❌ FAIL"
    print( f"{status} MockManager unit test completed in {duration:.2f}s" )
    if error:
        print( f"Error: {error}" )