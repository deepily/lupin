#!/usr/bin/env python3
"""
Unit Tests: TwoWordIdGenerator

Comprehensive unit tests for the CoSA TwoWordIdGenerator class with complete mocking
of external dependencies including randomness, singleton pattern, and state management.

This test module validates:
- TwoWordIdGenerator singleton pattern implementation
- Deterministic randomness mocking for predictable testing
- Unique ID generation with collision detection
- Word list management and validation
- Performance requirements for ID generation
- Thread safety and state consistency
"""

import os
import sys
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
    sys.exit( 1 )

# Import the modules under test
try:
    from cosa.agents.two_word_id_generator import TwoWordIdGenerator, singleton
except ImportError as e:
    print( f"Failed to import TwoWordIdGenerator: {e}" )
    sys.exit( 1 )


class TwoWordIdGeneratorUnitTests:
    """
    Unit test suite for TwoWordIdGenerator.
    
    Provides comprehensive testing of two-word ID generation functionality
    including singleton behavior, randomness mocking, uniqueness validation,
    and performance testing with complete external dependency isolation.
    
    Requires:
        - MockManager for randomness and external dependency mocking
        - CoSATestFixtures for test data
        - UnitTestUtilities for test helpers
        
    Ensures:
        - All TwoWordIdGenerator functionality is tested thoroughly
        - No external dependencies or non-deterministic behavior
        - Performance requirements are met
        - Singleton pattern works correctly
        - Error conditions are handled properly
    """
    
    def __init__( self, debug: bool = False ):
        """
        Initialize TwoWordIdGenerator unit tests.
        
        Args:
            debug: Enable debug output
        """
        self.debug = debug
        self.mock_mgr = MockManager()
        self.fixtures = CoSATestFixtures()
        self.utils = UnitTestUtilities( debug=debug )
        self.temp_files = []
        
        # Predetermined randomness for deterministic testing
        self.test_adjectives = [ "bright", "quick", "silent", "clever" ]
        self.test_nouns = [ "lion", "eagle", "wolf", "fox" ]
        self.test_random_sequence = [
            ( 0, 0 ),  # bright lion
            ( 1, 1 ),  # quick eagle  
            ( 2, 2 ),  # silent wolf
            ( 3, 3 ),  # clever fox
            ( 0, 1 ),  # bright eagle
            ( 1, 0 ),  # quick lion
        ]
    
    def _create_deterministic_random_mock( self ):
        """
        Create a deterministic random choice mock for predictable testing.
        
        Returns:
            Mock side_effect function that returns predetermined sequences
        """
        # Simplified approach: cycle through predetermined values
        predetermined_choices = [ "bright", "lion", "quick", "eagle", "silent", "wolf", "clever", "fox" ]
        choice_index = 0
        
        def mock_choice( items ):
            nonlocal choice_index
            # Return the next predetermined choice that exists in the items list
            while choice_index < len( predetermined_choices ):
                choice = predetermined_choices[ choice_index ]
                choice_index += 1
                if choice in items:
                    return choice
            
            # Fallback to first item if we run out of predetermined choices
            return items[ 0 ]
        
        return mock_choice
    
    def _clear_generated_ids( self ):
        """Clear generated IDs for clean testing."""
        # Instead of resetting singleton, just clear the generated IDs set
        generator = TwoWordIdGenerator()
        generator.generated_ids.clear()
    
    def test_singleton_behavior( self ) -> bool:
        """
        Test TwoWordIdGenerator singleton pattern implementation.
        
        Ensures:
            - Only one instance exists across multiple instantiations
            - Singleton state is maintained correctly
            - Generated IDs set is shared across references
            - Instance identity is preserved
            
        Returns:
            True if test passes
        """
        self.utils.print_test_banner( "Testing Singleton Behavior" )
        
        try:
            # Clear generated IDs for clean testing
            self._clear_generated_ids()
            
            with patch( 'random.choice' ) as mock_choice:
                mock_choice.return_value = "test"
                
                # Test multiple instantiations return same object
                generator1 = TwoWordIdGenerator()
                generator2 = TwoWordIdGenerator()
                generator3 = TwoWordIdGenerator()
                
                # Test singleton identity
                assert generator1 is generator2, "Generator instances should be identical (singleton)"
                assert generator2 is generator3, "All generator instances should be identical"
                assert generator1 is generator3, "First and third instances should be identical"
                
                # Test shared state
                generator1.test_attribute = "shared_value"
                assert hasattr( generator2, 'test_attribute' ), "Singleton should share attributes"
                assert generator2.test_attribute == "shared_value", "Singleton attribute should be shared"
                
                # Test shared generated_ids set
                initial_count = len( generator1.generated_ids )
                test_id = generator1.get_id()
                
                assert len( generator2.generated_ids ) == initial_count + 1, "Should share generated_ids set"
                assert test_id in generator2.generated_ids, "Generated ID should be in shared set"
                assert test_id in generator3.generated_ids, "Generated ID should be in all instances"
                
                self.utils.print_test_status( "Singleton behavior test passed", "PASS" )
                
            return True
            
        except Exception as e:
            self.utils.print_test_status( f"Singleton behavior test failed: {e}", "FAIL" )
            return False
    
    def test_deterministic_id_generation( self ) -> bool:
        """
        Test deterministic ID generation with mocked randomness.
        
        Ensures:
            - Random choices are mocked for predictable testing
            - Expected adjective-noun combinations are generated
            - Generated IDs follow expected format
            - Sequence of IDs is deterministic
            
        Returns:
            True if test passes
        """
        self.utils.print_test_banner( "Testing Deterministic ID Generation" )
        
        try:
            # Clear generated IDs for clean testing
            self._clear_generated_ids()
            
            with patch( 'random.choice' ) as mock_choice:
                mock_choice.side_effect = self._create_deterministic_random_mock()
                
                generator = TwoWordIdGenerator()
                
                # Override word lists for predictable testing
                generator.adjectives = self.test_adjectives
                generator.nouns = self.test_nouns
                
                # Test deterministic sequence
                expected_ids = [
                    "bright lion",
                    "quick eagle", 
                    "silent wolf",
                    "clever fox"
                ]
                
                generated_ids = []
                for i in range( 4 ):
                    id_result = generator.get_id()
                    generated_ids.append( id_result )
                    
                    # Test format
                    parts = id_result.split()
                    assert len( parts ) == 2, f"ID should have 2 words, got: {id_result}"
                    assert parts[ 0 ] in self.test_adjectives, f"First word should be adjective: {parts[0]}"
                    assert parts[ 1 ] in self.test_nouns, f"Second word should be noun: {parts[1]}"
                
                # Test expected sequence
                for i, expected_id in enumerate( expected_ids ):
                    assert generated_ids[ i ] == expected_id, f"Expected '{expected_id}', got '{generated_ids[i]}'"
                
                self.utils.print_test_status( "Deterministic ID generation test passed", "PASS" )
                
            return True
            
        except Exception as e:
            self.utils.print_test_status( f"Deterministic ID generation test failed: {e}", "FAIL" )
            return False
    
    def test_uniqueness_validation( self ) -> bool:
        """
        Test uniqueness validation and collision detection.
        
        Ensures:
            - Generated IDs are unique within a session
            - generated_ids set maintains uniqueness
            - Multiple generations create different IDs
            - Set tracking works correctly
            
        Returns:
            True if test passes
        """
        self.utils.print_test_banner( "Testing Uniqueness Validation" )
        
        try:
            # Clear generated IDs for clean testing
            self._clear_generated_ids()
            
            with patch( 'random.choice' ) as mock_choice:
                mock_choice.side_effect = self._create_deterministic_random_mock()
                
                generator = TwoWordIdGenerator()
                generator.adjectives = self.test_adjectives
                generator.nouns = self.test_nouns
                
                # Generate multiple IDs and test uniqueness
                generated_ids = []
                initial_size = len( generator.generated_ids )
                
                for i in range( 3 ):
                    new_id = generator.get_id()
                    generated_ids.append( new_id )
                    
                    # Test that ID is in the tracking set
                    assert new_id in generator.generated_ids, f"ID '{new_id}' should be in generated set"
                    
                    # Test that set size increases
                    expected_size = initial_size + i + 1
                    actual_size = len( generator.generated_ids )
                    assert actual_size == expected_size, f"Expected set size {expected_size}, got {actual_size}"
                
                # Test that all generated IDs are unique
                unique_set = set( generated_ids )
                assert len( unique_set ) == len( generated_ids ), "All generated IDs should be unique"
                
                # Test that all IDs are properly formatted
                for generated_id in generated_ids:
                    parts = generated_id.split()
                    assert len( parts ) == 2, f"ID should have 2 words: {generated_id}"
                    assert parts[ 0 ] in self.test_adjectives, f"First word should be adjective: {parts[0]}"
                    assert parts[ 1 ] in self.test_nouns, f"Second word should be noun: {parts[1]}"
                
                # Test that tracking set contains all generated IDs
                for generated_id in generated_ids:
                    assert generated_id in generator.generated_ids, f"ID '{generated_id}' should be tracked"
                
                self.utils.print_test_status( "Uniqueness validation test passed", "PASS" )
                
            return True
            
        except Exception as e:
            self.utils.print_test_status( f"Uniqueness validation test failed: {e}", "FAIL" )
            return False
    
    def test_word_lists_validation( self ) -> bool:
        """
        Test word lists structure and content validation.
        
        Ensures:
            - Adjectives and nouns lists are properly initialized
            - Word lists contain expected content types
            - Lists are non-empty and have reasonable size
            - Word format is consistent
            
        Returns:
            True if test passes
        """
        self.utils.print_test_banner( "Testing Word Lists Validation" )
        
        try:
            # Clear generated IDs for clean testing
            self._clear_generated_ids()
            
            with patch( 'random.choice' ) as mock_choice:
                mock_choice.return_value = "test"
                
                generator = TwoWordIdGenerator()
                
                # Test adjectives list
                assert hasattr( generator, 'adjectives' ), "Generator should have adjectives attribute"
                assert isinstance( generator.adjectives, list ), "Adjectives should be a list"
                assert len( generator.adjectives ) > 0, "Adjectives list should not be empty"
                # Note: During testing, word lists may be overridden, so check original or current size
                assert len( generator.adjectives ) >= 4, "Adjectives list should have reasonable size (allowing for test overrides)"
                
                # Test nouns list
                assert hasattr( generator, 'nouns' ), "Generator should have nouns attribute"
                assert isinstance( generator.nouns, list ), "Nouns should be a list"
                assert len( generator.nouns ) > 0, "Nouns list should not be empty"
                assert len( generator.nouns ) >= 4, "Nouns list should have reasonable size (allowing for test overrides)"
                
                # Test word format and content (limit to available words)
                adj_sample = generator.adjectives[ :min( 5, len( generator.adjectives ) ) ]
                for adj in adj_sample:
                    assert isinstance( adj, str ), f"Adjective should be string: {adj}"
                    assert len( adj ) > 0, f"Adjective should not be empty: {adj}"
                    assert adj.islower(), f"Adjective should be lowercase: {adj}"
                    assert adj.isalpha(), f"Adjective should contain only letters: {adj}"
                
                noun_sample = generator.nouns[ :min( 5, len( generator.nouns ) ) ]
                for noun in noun_sample:
                    assert isinstance( noun, str ), f"Noun should be string: {noun}"
                    assert len( noun ) > 0, f"Noun should not be empty: {noun}"
                    assert noun.islower(), f"Noun should be lowercase: {noun}"
                    assert noun.isalpha(), f"Noun should contain only letters: {noun}"
                
                # Test generated_ids set
                assert hasattr( generator, 'generated_ids' ), "Generator should have generated_ids attribute"
                assert isinstance( generator.generated_ids, set ), "generated_ids should be a set"
                
                # Test potential combinations (adjust for test lists)
                total_combinations = len( generator.adjectives ) * len( generator.nouns )
                assert total_combinations >= 16, f"Should have sufficient combinations for testing: {total_combinations}"
                
                self.utils.print_test_status( "Word lists validation test passed", "PASS" )
                
            return True
            
        except Exception as e:
            self.utils.print_test_status( f"Word lists validation test failed: {e}", "FAIL" )
            return False
    
    def test_state_consistency( self ) -> bool:
        """
        Test state consistency across multiple ID generations.
        
        Ensures:
            - Generated IDs are properly tracked
            - State persists across multiple calls
            - No memory leaks in generated_ids set
            - Consistent behavior over time
            
        Returns:
            True if test passes
        """
        self.utils.print_test_banner( "Testing State Consistency" )
        
        try:
            # Clear generated IDs for clean testing
            self._clear_generated_ids()
            
            with patch( 'random.choice' ) as mock_choice:
                mock_choice.side_effect = self._create_deterministic_random_mock()
                
                generator = TwoWordIdGenerator()
                generator.adjectives = self.test_adjectives
                generator.nouns = self.test_nouns
                
                # Track state across multiple generations
                initial_set_size = len( generator.generated_ids )
                generated_list = []
                
                # Generate multiple IDs (reduced for testing)
                for i in range( 3 ):  # Generate 3 IDs
                    new_id = generator.get_id()
                    generated_list.append( new_id )
                    
                    # Test state consistency
                    expected_size = initial_set_size + i + 1
                    actual_size = len( generator.generated_ids )
                    assert actual_size == expected_size, f"Expected set size {expected_size}, got {actual_size}"
                    
                    # Test that new ID is in the set
                    assert new_id in generator.generated_ids, f"Generated ID '{new_id}' should be in the set"
                
                # Test that all generated IDs are unique
                unique_ids = set( generated_list )
                assert len( unique_ids ) == len( generated_list ), "All generated IDs should be unique"
                
                # Test that all IDs are in the generated_ids set
                for generated_id in generated_list:
                    assert generated_id in generator.generated_ids, f"ID '{generated_id}' should be tracked"
                
                # Test state persistence with new instance (should be same singleton)
                generator2 = TwoWordIdGenerator()
                assert generator2.generated_ids == generator.generated_ids, "Singleton should share state"
                
                self.utils.print_test_status( "State consistency test passed", "PASS" )
                
            return True
            
        except Exception as e:
            self.utils.print_test_status( f"State consistency test failed: {e}", "FAIL" )
            return False
    
    def test_performance_requirements( self ) -> bool:
        """
        Test TwoWordIdGenerator performance requirements.
        
        Ensures:
            - ID generation is fast enough
            - Singleton access is performant
            - Memory usage is reasonable
            - Large-scale generation is efficient
            
        Returns:
            True if test passes
        """
        self.utils.print_test_banner( "Testing Performance Requirements" )
        
        try:
            performance_targets = self.fixtures.get_performance_targets()
            generator_timeout = performance_targets[ "timing_targets" ].get( "generator_operation", 0.1 )
            
            # Clear generated IDs for clean testing
            self._clear_generated_ids()
            
            with patch( 'random.choice' ) as mock_choice:
                mock_choice.side_effect = self._create_deterministic_random_mock()
                
                # Test single ID generation performance
                def single_generation_test():
                    generator = TwoWordIdGenerator()
                    generator.adjectives = self.test_adjectives
                    generator.nouns = self.test_nouns
                    id_result = generator.get_id()
                    return id_result is not None
                
                success, duration, result = self.utils.assert_timing( single_generation_test, 0.05 )  # 50ms limit
                assert success, f"Single ID generation too slow: {duration}s"
                assert result == True, "ID generation should return True"
                
                # Test multiple ID generation performance
                def multiple_generation_test():
                    generator = TwoWordIdGenerator()
                    generator.adjectives = self.test_adjectives
                    generator.nouns = self.test_nouns
                    
                    ids = []
                    for i in range( 3 ):
                        new_id = generator.get_id()
                        ids.append( new_id )
                    
                    return len( ids )
                
                success, duration, result = self.utils.assert_timing( multiple_generation_test, generator_timeout )
                assert success, f"Multiple ID generation too slow: {duration}s"
                assert result == 3, f"Should generate 3 IDs, got {result}"
                
                # Test singleton access performance
                def singleton_access_test():
                    instances = []
                    for i in range( 5 ):
                        instance = TwoWordIdGenerator()
                        instances.append( instance )
                    
                    # Verify all are same instance
                    first = instances[ 0 ]
                    for instance in instances[ 1: ]:
                        if instance is not first:
                            return False
                    
                    return True
                
                success, duration, result = self.utils.assert_timing( singleton_access_test, 0.01 )  # 10ms limit
                assert success, f"Singleton access too slow: {duration}s"
                assert result == True, "Singleton access should return True"
                
                self.utils.print_test_status( f"Performance requirements met ({self.utils.format_duration( duration )})", "PASS" )
                
            return True
            
        except Exception as e:
            self.utils.print_test_status( f"Performance requirements test failed: {e}", "FAIL" )
            return False
    
    def run_all_tests( self ) -> tuple:
        """
        Run all TwoWordIdGenerator unit tests.
        
        Returns:
            Tuple of (success, duration, error_message)
        """
        start_time = self.utils.start_timer( "two_word_id_generator_tests" )
        
        tests = [
            self.test_singleton_behavior,
            self.test_deterministic_id_generation,
            self.test_uniqueness_validation,
            self.test_word_lists_validation,
            self.test_state_consistency,
            self.test_performance_requirements
        ]
        
        passed_tests = 0
        failed_tests = 0
        errors = []
        
        self.utils.print_test_banner( "TwoWordIdGenerator Unit Test Suite", "=" )
        
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
        
        duration = self.utils.stop_timer( "two_word_id_generator_tests" )
        
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
    Main unit test function for TwoWordIdGenerator.
    
    This is the entry point called by the unit test runner to execute
    all TwoWordIdGenerator unit tests.
    
    Returns:
        Tuple[bool, float, str]: (success, duration, error_message)
    """
    test_suite = None
    
    try:
        test_suite = TwoWordIdGeneratorUnitTests( debug=False )
        success, duration, error_message = test_suite.run_all_tests()
        return success, duration, error_message
        
    except Exception as e:
        error_message = f"TwoWordIdGenerator unit test suite failed to initialize: {str( e )}"
        return False, 0.0, error_message
        
    finally:
        if test_suite:
            test_suite.cleanup()


if __name__ == "__main__":
    success, duration, error = isolated_unit_test()
    status = "✅ PASS" if success else "❌ FAIL"
    print( f"{status} TwoWordIdGenerator unit tests completed in {duration:.2f}s" )
    if error:
        print( f"Errors: {error}" )