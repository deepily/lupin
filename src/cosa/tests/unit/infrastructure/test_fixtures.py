"""
Test Fixtures for CoSA Unit Tests

Provides reusable test data, mock responses, and test scenarios for all
CoSA component unit tests. Ensures consistent test data across the suite.

Usage:
    from test_fixtures import CoSATestFixtures
    
    fixtures = CoSATestFixtures()
    agent_questions = fixtures.get_agent_test_questions()
    mock_responses = fixtures.get_llm_mock_responses()
"""

import json
import datetime
from typing import Dict, List, Any, Optional
from dataclasses import dataclass


@dataclass
class TestScenario:
    """
    Represents a complete test scenario with inputs, expected outputs, and metadata.
    
    Attributes:
        name: Human-readable test scenario name
        description: Detailed description of what the scenario tests
        inputs: Dictionary of input parameters
        expected_outputs: Dictionary of expected results
        should_fail: Whether this scenario should result in failure
        metadata: Additional scenario metadata
    """
    name: str
    description: str
    inputs: Dict[str, Any]
    expected_outputs: Dict[str, Any]
    should_fail: bool = False
    metadata: Dict[str, Any] = None


class CoSATestFixtures:
    """
    Centralized test fixtures for CoSA framework unit tests.
    
    Provides consistent, realistic test data for all components including
    agent questions, LLM responses, configuration scenarios, and error cases.
    
    Requires:
        - None (self-contained test data)
        
    Ensures:
        - Consistent test data across all test suites
        - Realistic data structures matching production usage
        - Comprehensive edge cases and error scenarios
        
    Raises:
        - None (all methods are safe and return default values)
    """
    
    def __init__( self ):
        """
        Initialize test fixtures with all predefined test data.
        
        Ensures:
            - All fixture categories are loaded
            - Data structures are validated
            - Edge cases are included
        """
        self._agent_questions = self._load_agent_questions()
        self._llm_responses = self._load_llm_responses()
        self._xml_responses = self._load_xml_responses()
        self._config_scenarios = self._load_config_scenarios()
        self._embedding_data = self._load_embedding_data()
        self._error_scenarios = self._load_error_scenarios()
        self._performance_data = self._load_performance_data()
    
    def _load_agent_questions( self ) -> Dict[str, List[str]]:
        """
        Load test questions for different agent types.
        
        Returns:
            Dictionary mapping agent types to lists of test questions
        """
        return {
            "math": [
                "What is 2 + 2?",
                "Calculate the square root of 144",
                "What is 15% of 200?",
                "Solve for x: 2x + 5 = 15",
                "What is the area of a circle with radius 7?",
                "Convert 100 Fahrenheit to Celsius",
                "What is 12 factorial?",
                "",  # Empty question edge case
                "Invalid math expression: 2 + + 3",  # Invalid input
                "Calculate infinity divided by zero"  # Error condition
            ],
            "weather": [
                "What's the weather like in San Francisco?",
                "Is it going to rain today in New York?",
                "What's the temperature in London?",
                "Weather forecast for Tokyo this week",
                "",  # Empty location
                "Weather in InvalidCityName12345",  # Invalid location
                "What's the weather on Mars?"  # Impossible request
            ],
            "datetime": [
                "What time is it?",
                "What's today's date?",
                "What time is it in Tokyo?",
                "Convert 3 PM PST to EST",
                "What day of the week is January 1, 2025?",
                "",  # Empty query
                "What time is it in InvalidTimezone/Fake"  # Invalid timezone
            ],
            "calendar": [
                "Schedule a meeting for tomorrow at 2 PM",
                "What meetings do I have today?",
                "Add birthday reminder for next Friday",
                "Cancel my 3 PM appointment",
                "",  # Empty request
                "Schedule meeting for invalid date: 32nd of January"  # Invalid date
            ],
            "todo": [
                "Add buy groceries to my todo list",
                "Mark homework as completed",
                "Show all pending tasks",
                "Delete completed items",
                "",  # Empty task
                "Add extremely long task description that goes on and on and might cause issues with storage or display systems"  # Long input
            ]
        }
    
    def _load_llm_responses( self ) -> Dict[str, List[str]]:
        """
        Load mock LLM responses for testing.
        
        Returns:
            Dictionary of response types to response lists
        """
        return {
            "math_responses": [
                "The answer is 4.",
                "The square root of 144 is 12.",
                "15% of 200 is 30.",
                "Solving 2x + 5 = 15: x = 5",
                "The area of a circle with radius 7 is approximately 153.94 square units.",
                "100°F equals 37.78°C.",
                "12! = 479,001,600"
            ],
            "weather_responses": [
                "The weather in San Francisco is currently 68°F and partly cloudy.",
                "There is a 30% chance of rain in New York today.",
                "The current temperature in London is 15°C (59°F).",
                "Tokyo weather forecast: Sunny with highs of 25°C this week."
            ],
            "error_responses": [
                "I don't have access to current weather data.",
                "Unable to process that mathematical expression.",
                "Invalid location specified.",
                "An error occurred while processing your request."
            ],
            "generic_responses": [
                "I understand your request and will help you with that.",
                "Let me process that information for you.",
                "Here's what I found based on your query.",
                "I'll need more information to provide an accurate response."
            ]
        }
    
    def _load_xml_responses( self ) -> List[str]:
        """
        Load mock XML responses for agent testing.
        
        Returns:
            List of XML response strings for different scenarios
        """
        return [
            # Valid math response
            """<response>
<thoughts>This is a simple addition problem.</thoughts>
<brainstorm>I need to add 2 and 2 together.</brainstorm>
<evaluation>This is straightforward arithmetic.</evaluation>
<code>result = 2 + 2</code>
<example>2 + 2 = 4</example>
<returns>4</returns>
<explanation>The sum of 2 and 2 is 4.</explanation>
</response>""",
            
            # Valid weather response  
            """<response>
<thoughts>User is asking about weather information.</thoughts>
<brainstorm>I need current weather data for the specified location.</brainstorm>
<evaluation>This requires external API access.</evaluation>
<code>weather_data = get_weather("San Francisco")</code>
<example>Current weather: 68°F, partly cloudy</example>
<returns>Weather information for San Francisco</returns>
<explanation>Current conditions show partly cloudy skies with mild temperatures.</explanation>
</response>""",
            
            # Error response
            """<response>
<thoughts>This request contains invalid input.</thoughts>
<error>Unable to process malformed mathematical expression</error>
</response>""",
            
            # Minimal valid response
            """<response>
<returns>Simple answer</returns>
</response>""",
            
            # Malformed XML
            """<response>
<thoughts>Missing closing tag
<returns>This will cause parsing errors</returns>""",
            
            # Empty response
            """<response></response>""",
            
            # Large response (edge case)
            """<response>
<thoughts>{}</thoughts>
<code>{}</code>
<returns>{}</returns>
</response>""".format(
                'Very long thoughts section. ' * 100,
                'print("test")\n' * 50,
                'Large response data. ' * 200
            )
        ]
    
    def _load_config_scenarios( self ) -> List[TestScenario]:
        """
        Load configuration test scenarios.
        
        Returns:
            List of TestScenario objects for configuration testing
        """
        return [
            TestScenario(
                name="valid_default_config",
                description="Test with valid default configuration values",
                inputs={
                    "config_file": "lupin-app.ini",
                    "env_var_name": "LUPIN_CONFIG_MGR_CLI_ARGS"
                },
                expected_outputs={
                    "app debug": False,
                    "agent_timeout": 30,
                    "config_loaded": True
                },
                should_fail=False,
                metadata={ "priority": "high", "category": "core" }
            ),
            
            TestScenario(
                name="debug_enabled_config",
                description="Test with debug mode enabled",
                inputs={
                    "config_values": {
                        "app debug": "true",
                        "agent_timeout": "60",
                        "verbose_logging": "yes"
                    }
                },
                expected_outputs={
                    "app debug": True,
                    "agent_timeout": 60,
                    "verbose_logging": True
                },
                should_fail=False,
                metadata={ "priority": "medium", "category": "core" }
            ),
            
            TestScenario(
                name="missing_config_file",
                description="Test behavior when configuration file is missing",
                inputs={
                    "config_file": "nonexistent-config.ini",
                    "use_defaults": True
                },
                expected_outputs={
                    "config_loaded": False,
                    "uses_defaults": True,
                    "error_handled": True
                },
                should_fail=False,
                metadata={ "priority": "high", "category": "error_handling" }
            ),
            
            TestScenario(
                name="invalid_config_values",
                description="Test with invalid configuration values",
                inputs={
                    "config_values": {
                        "agent_timeout": "invalid_number",
                        "app debug": "maybe",
                        "missing_required_key": None
                    }
                },
                expected_outputs={
                    "validation_errors": True,
                    "fallback_used": True
                },
                should_fail=True,
                metadata={ "priority": "medium", "category": "validation" }
            )
        ]
    
    def _load_embedding_data( self ) -> Dict[str, List[List[float]]]:
        """
        Load test embedding vectors for memory system testing.
        
        Returns:
            Dictionary of embedding scenarios to vector lists
        """
        return {
            "standard_embeddings": [
                [0.1] * 1536,  # Standard OpenAI embedding size
                [0.2, 0.3, 0.1] * 512,  # Varied values
                [0.0] * 1536,  # Zero vector
                [1.0] * 1536,  # Max values
                [-1.0] * 1536  # Negative values
            ],
            "small_embeddings": [
                [0.1, 0.2, 0.3],  # Minimal size for testing
                [0.0, 0.0, 0.0],  # Zero vector
                [1.0, -1.0, 0.5]  # Mixed values
            ],
            "malformed_embeddings": [
                [],  # Empty vector
                [float( "inf" )],  # Infinity
                [float( "nan" )],  # NaN
                ["invalid", "data"],  # Wrong type
                None  # Null vector
            ]
        }
    
    def _load_error_scenarios( self ) -> List[TestScenario]:
        """
        Load error condition test scenarios.
        
        Returns:
            List of TestScenario objects for error testing
        """
        return [
            TestScenario(
                name="network_timeout",
                description="Simulate network timeout during API call",
                inputs={ "timeout_duration": 30, "api_endpoint": "openai" },
                expected_outputs={ "timeout_handled": True, "fallback_used": True },
                should_fail=True,
                metadata={ "error_type": "timeout", "category": "network" }
            ),
            
            TestScenario(
                name="invalid_api_key",
                description="Test with invalid API credentials",
                inputs={ "api_key": "invalid_key_12345" },
                expected_outputs={ "auth_error": True, "graceful_degradation": True },
                should_fail=True,
                metadata={ "error_type": "authentication", "category": "security" }
            ),
            
            TestScenario(
                name="malformed_input",
                description="Test with malformed input data",
                inputs={ "malformed_json": '{"invalid": json}' },
                expected_outputs={ "parsing_error": True, "error_logged": True },
                should_fail=True,
                metadata={ "error_type": "parsing", "category": "input_validation" }
            ),
            
            TestScenario(
                name="memory_limit_exceeded",
                description="Test behavior when memory limits are exceeded",
                inputs={ "large_data_size": 1024 * 1024 * 100 },  # 100MB
                expected_outputs={ "memory_error": True, "cleanup_performed": True },
                should_fail=True,
                metadata={ "error_type": "resource", "category": "performance" }
            )
        ]
    
    def _load_performance_data( self ) -> Dict[str, Any]:
        """
        Load performance benchmarking data.
        
        Returns:
            Dictionary of performance metrics and targets
        """
        return {
            "timing_targets": {
                "config_load_time": 0.1,  # 100ms
                "agent_response_time": 2.0,  # 2 seconds
                "embedding_generation": 0.5,  # 500ms
                "unit_test_execution": 0.1  # 100ms per test
            },
            "memory_targets": {
                "max_memory_usage": 100 * 1024 * 1024,  # 100MB
                "memory_leak_threshold": 1024 * 1024,  # 1MB
                "cache_size_limit": 50 * 1024 * 1024  # 50MB
            },
            "throughput_targets": {
                "requests_per_second": 100,
                "concurrent_agents": 10,
                "queue_processing_rate": 1000  # items per second
            }
        }
    
    # Public API methods
    
    def get_agent_test_questions( self, agent_type: str = "all" ) -> List[str]:
        """
        Get test questions for specific agent type or all agents.
        
        Requires:
            - agent_type is a valid agent type or "all"
            
        Ensures:
            - Returns appropriate test questions
            - Includes edge cases and error conditions
            
        Args:
            agent_type: Type of agent ("math", "weather", "datetime", etc.) or "all"
            
        Returns:
            List of test questions for the specified agent type
        """
        if agent_type == "all":
            all_questions = []
            for questions in self._agent_questions.values():
                all_questions.extend( questions )
            return all_questions
        
        return self._agent_questions.get( agent_type, [] )
    
    def get_llm_mock_responses( self, response_type: str = "all" ) -> List[str]:
        """
        Get mock LLM responses for testing.
        
        Args:
            response_type: Type of responses ("math_responses", "error_responses", etc.)
            
        Returns:
            List of mock LLM response strings
        """
        if response_type == "all":
            all_responses = []
            for responses in self._llm_responses.values():
                all_responses.extend( responses )
            return all_responses
        
        return self._llm_responses.get( response_type, [] )
    
    def get_xml_test_responses( self ) -> List[str]:
        """
        Get XML response strings for XML parsing tests.
        
        Returns:
            List of XML response strings including valid, invalid, and edge cases
        """
        return self._xml_responses.copy()
    
    def get_config_test_scenarios( self ) -> List[TestScenario]:
        """
        Get configuration testing scenarios.
        
        Returns:
            List of TestScenario objects for configuration testing
        """
        return self._config_scenarios.copy()
    
    def get_embedding_test_data( self, category: str = "standard_embeddings" ) -> List[List[float]]:
        """
        Get test embedding vectors.
        
        Args:
            category: Category of embeddings ("standard_embeddings", "small_embeddings", etc.)
            
        Returns:
            List of embedding vectors
        """
        return self._embedding_data.get( category, [] )
    
    def get_error_test_scenarios( self ) -> List[TestScenario]:
        """
        Get error condition testing scenarios.
        
        Returns:
            List of TestScenario objects for error testing
        """
        return self._error_scenarios.copy()
    
    def get_performance_targets( self ) -> Dict[str, Any]:
        """
        Get performance benchmarking targets.
        
        Returns:
            Dictionary of performance metrics and target values
        """
        return self._performance_data.copy()
    
    def create_test_scenario( self, name: str, description: str, inputs: Dict[str, Any], 
                            expected_outputs: Dict[str, Any], should_fail: bool = False,
                            metadata: Optional[Dict[str, Any]] = None ) -> TestScenario:
        """
        Create a custom test scenario.
        
        Args:
            name: Test scenario name
            description: Detailed description
            inputs: Input parameters
            expected_outputs: Expected results
            should_fail: Whether scenario should fail
            metadata: Additional metadata
            
        Returns:
            TestScenario object
        """
        return TestScenario(
            name=name,
            description=description,
            inputs=inputs,
            expected_outputs=expected_outputs,
            should_fail=should_fail,
            metadata=metadata or {}
        )


def isolated_unit_test():
    """
    Quick smoke test for CoSATestFixtures functionality.
    
    Ensures:
        - Fixtures can be loaded and accessed
        - All fixture categories contain data
        - Test scenarios are properly formatted
        
    Returns:
        Tuple[bool, float, str]: (success, duration, error_message)
    """
    import time
    start_time = time.time()
    
    try:
        # Test basic instantiation
        fixtures = CoSATestFixtures()
        assert fixtures is not None, "Failed to create CoSATestFixtures instance"
        
        # Test agent questions
        math_questions = fixtures.get_agent_test_questions( "math" )
        assert len( math_questions ) > 0, "No math questions loaded"
        assert isinstance( math_questions[ 0 ], str ), "Invalid question format"
        
        # Test LLM responses
        responses = fixtures.get_llm_mock_responses( "math_responses" )
        assert len( responses ) > 0, "No LLM responses loaded"
        
        # Test XML responses
        xml_responses = fixtures.get_xml_test_responses()
        assert len( xml_responses ) > 0, "No XML responses loaded"
        assert "<response>" in xml_responses[ 0 ], "Invalid XML format"
        
        # Test config scenarios
        config_scenarios = fixtures.get_config_test_scenarios()
        assert len( config_scenarios ) > 0, "No config scenarios loaded"
        assert isinstance( config_scenarios[ 0 ], TestScenario ), "Invalid scenario type"
        
        # Test embeddings
        embeddings = fixtures.get_embedding_test_data()
        assert len( embeddings ) > 0, "No embeddings loaded"
        assert len( embeddings[ 0 ] ) == 1536, "Invalid embedding size"
        
        # Test performance targets
        perf_targets = fixtures.get_performance_targets()
        assert "timing_targets" in perf_targets, "Missing performance targets"
        
        duration = time.time() - start_time
        return True, duration, ""
        
    except Exception as e:
        duration = time.time() - start_time
        return False, duration, f"CoSATestFixtures test failed: {str( e )}"


if __name__ == "__main__":
    success, duration, error = isolated_unit_test()
    status = "✅ PASS" if success else "❌ FAIL"
    print( f"{status} CoSATestFixtures unit test completed in {duration:.2f}s" )
    if error:
        print( f"Error: {error}" )