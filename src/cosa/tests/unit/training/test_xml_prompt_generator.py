"""
Unit tests for XML prompt generator with comprehensive template testing.

Tests the XmlPromptGenerator class including:
- Initialization with template management and command loading
- Template formatting and prompt generation
- Command dictionary management and compilation
- Natural language variation insertion (interjections, salutations)
- Placeholder substitution and content management
- Template serialization and file operations
- Command path validation and error handling
- Prompt formatting with instruction templates
- GPT message formatting and structure

Zero external dependencies - all file operations and template loading
are mocked for isolated testing.
"""

import unittest
from unittest.mock import Mock, MagicMock, patch, mock_open
import time
import sys
import os
from typing import Optional, Any, Dict, List, Tuple
import sys
import os

# Import test infrastructure
sys.path.append( os.path.join( os.path.dirname( __file__ ), "..", "infrastructure" ) )
from mock_manager import MockManager
from unit_test_utilities import UnitTestUtilities

# Import the module under test
from cosa.training.xml_prompt_generator import XmlPromptGenerator

class TestXmlPromptGenerator( unittest.TestCase ):
    """
    Comprehensive unit tests for XML prompt generator.
    
    Requires:
        - MockManager for external dependency mocking
        - UnitTestUtilities for common test patterns
        
    Ensures:
        - All template operations tested in isolation
        - Command management properly tested
        - Error handling scenarios covered
        - File operations thoroughly mocked
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
        self.test_interjections = ["wow", "hey", "oh"]
        self.test_salutations = ["hello computer", "hi there"]
        self.test_commands = {
            "test_command": "/path/to/test.txt",
            "another_command": "/path/to/another.txt"
        }
    
    def tearDown( self ):
        """
        Cleanup after each test method.

        Ensures:
            - All mocks are reset
        """
        self.mock_manager.reset_mocks()

    def _speakable_stand_in( self ):
        """
        A command index whose keys are exactly the registry's speakable commands.

        Since row 95924f2d step 4 (merge 7989db99) the constructor asserts that the
        agent-router JSON key union EQUALS the served speakable set, in both directions.
        A fixture handing it {} trips the "in the menu but in no JSON" half — the guard
        working, not failing. Tests that want the REAL getters to run therefore have to
        feed them a consistent payload rather than an empty one.

        Ensures:
            - Returns { <every speakable command>: <dummy path> }; the paths are never
              opened, because the file I/O these tests exercise is itself mocked
        """
        from cosa.rest.v2.router_prompt_generator import speakable_commands

        # The value carries BOTH accepted shapes at once. The simple/compound getters
        # want a bare path string; the agentic getter wants the enriched form and reads
        # entry[ "template_file" ]. Since `json.load` is patched globally these tests hand
        # every getter the same payload, so the enriched dict is the only shape all three
        # survive — and the consistency check the fixture exists to satisfy reads KEYS,
        # never values. No path is ever opened: the file I/O is itself mocked.
        return {
            command: { "template_file": "/src/ephemera/prompts/data/unit-fixture-never-opened.txt",
                       "placeholders" : {} }
            for command in speakable_commands()
        }

    def _mock_command_loading( self ):
        """
        Returns a patch.multiple context that makes the JSON-config command
        getters inert, so the constructor performs no real file I/O and never
        triggers _test_command_paths during __init__.

        ⚠️ THE THREE AGENT-ROUTER GETTERS ARE NOT EMPTY, and must not be. Since
        row 95924f2d step 4 (merge 7989db99) the constructor asserts that the
        agent-router JSON key union EQUALS the served speakable command set, in
        both directions — a JSON-only command would train a label the interpolated
        menu omits, and a menu-only command would ship in the prompt with no
        training rows behind it. An all-empty fixture trips the second half, which
        is the guard doing its job rather than a defect in it.

        So the fixture supplies a CONSISTENT stand-in: every speakable command,
        pointed at a dummy path, in the simple index. The paths are never opened —
        the getters that would read them are exactly what this patch replaces.
        Relaxing the guard to tolerate the empty fixture was considered and
        REJECTED (Mr Radio, 2026-08-19): the tolerance would have deleted the
        property the guard was built for.

        Requires:
            - XmlPromptGenerator exposes the six private command-dictionary getters
            - cosa.rest.v2.router_prompt_generator.speakable_commands is importable

        Ensures:
            - Returns an unentered patch.multiple context manager
            - Under it, the agent-router indexes agree with the registry's speakable
              set, so the constructor's consistency check passes
            - _test_command_paths is NOT invoked during construction
        """
        speakable_stand_in = self._speakable_stand_in()

        return patch.multiple(
            XmlPromptGenerator,
            _get_compound_vox_commands                    = MagicMock( return_value={} ),
            _get_simple_vox_commands                      = MagicMock( return_value={} ),
            _get_compound_agent_router_commands           = MagicMock( return_value={} ),
            _get_simple_agent_router_commands             = MagicMock( return_value=speakable_stand_in ),
            _get_agentic_job_commands                     = MagicMock( return_value={} ),
            _get_compound_agent_function_mapping_commands = MagicMock( return_value={} ),
        )

    def test_initialization_success( self ):
        """
        Test successful XmlPromptGenerator initialization.
        
        Ensures:
            - Sets all instance attributes correctly
            - Initializes templates and commands
            - Loads interjections and salutations
            - Validates command paths
        """
        # Live contract: __init__ loads command dictionaries from JSON config files
        # ( open + json.load ) and validates their paths via _test_command_paths.
        # Mock the file I/O so the real getters run and exercise the path-test seam.
        # Built BEFORE the `with`: context-manager expressions are evaluated as the
        # block is entered left-to-right, so patch( 'builtins.open' ) is already live
        # by the time a later expression runs — and resolving the registry pulls in a
        # lazy timezone-file read that a mocked open() cannot serve.
        command_index = self._speakable_stand_in()

        with patch.object( XmlPromptGenerator, '_test_command_paths' ) as mock_test_paths, \
             patch.object( XmlPromptGenerator, 'get_interjections' ) as mock_get_interjections, \
             patch.object( XmlPromptGenerator, 'get_salutations' ) as mock_get_salutations, \
             patch( 'builtins.open', mock_open( read_data="{}" ) ), \
             patch( 'json.load', return_value=command_index ):

            mock_get_interjections.return_value = self.test_interjections
            mock_get_salutations.return_value = self.test_salutations

            generator = XmlPromptGenerator(
                path_prefix=self.test_path_prefix,
                debug=True,
                verbose=True,
                silent=False
            )
            
            # Verify instance attributes
            self.assertEqual( generator.path_prefix, self.test_path_prefix )
            self.assertTrue( generator.debug )
            self.assertTrue( generator.verbose )
            self.assertFalse( generator.silent )
            
            # Verify template initialization occurred
            self.assertIsNotNone( generator.common_input_template )
            self.assertIsNotNone( generator.common_human_says_template )
            self.assertIsNotNone( generator.common_response_format )
            self.assertIsNotNone( generator.common_output_template )
            
            # Verify command paths were tested
            self.assertGreater( mock_test_paths.call_count, 0 )
            
            # Verify interjections and salutations loaded
            self.assertEqual( generator.interjections, self.test_interjections )
            self.assertEqual( generator.salutations, self.test_salutations )
    
    def test_initialization_with_defaults( self ):
        """
        Test XmlPromptGenerator initialization with default parameters.
        
        Ensures:
            - Uses default values for optional parameters
            - Default path prefix is used
        """
        # Built BEFORE the `with`: context-manager expressions are evaluated as the
        # block is entered left-to-right, so patch( 'builtins.open' ) is already live
        # by the time a later expression runs — and resolving the registry pulls in a
        # lazy timezone-file read that a mocked open() cannot serve.
        command_index = self._speakable_stand_in()

        with patch.object( XmlPromptGenerator, '_test_command_paths' ), \
             patch.object( XmlPromptGenerator, 'get_interjections' ) as mock_get_interjections, \
             patch.object( XmlPromptGenerator, 'get_salutations' ) as mock_get_salutations, \
             patch( 'builtins.open', mock_open( read_data="{}" ) ), \
             patch( 'json.load', return_value=command_index ):

            mock_get_interjections.return_value = []
            mock_get_salutations.return_value = []

            generator = XmlPromptGenerator()

            # Live contract: the default path_prefix is `du.get_project_root()` evaluated
            # at function-DEFINITION time ( eager default ), so it is bound once at import
            # and cannot be overridden by patching get_project_root after import. Assert
            # against that captured default rather than a runtime-patched value.
            self.assertEqual( generator.path_prefix, XmlPromptGenerator.__init__.__defaults__[ 0 ] )
            self.assertFalse( generator.debug )
            self.assertFalse( generator.verbose )
            self.assertFalse( generator.silent )
    
    def test_get_interjections_default( self ):
        """
        Test getting interjections with default parameters.
        
        Ensures:
            - Loads interjections from file
            - Returns appropriate list
            - Handles file operations correctly
        """
        with patch( 'cosa.training.xml_prompt_generator.du.get_file_as_list' ) as mock_get_file, \
             patch.object( XmlPromptGenerator, '_test_command_paths' ), \
             patch.object( XmlPromptGenerator, 'get_salutations' ):
            
            mock_get_file.return_value = ["wow", "hey", "oh", "hmm"]

            generator = XmlPromptGenerator()
            # __init__ itself calls get_interjections() ( line 62 ), so reset the mock
            # to isolate the explicit call we are exercising here.
            mock_get_file.reset_mock()
            result = generator.get_interjections()

            # Verify file loading
            mock_get_file.assert_called_once()
            call_args = mock_get_file.call_args[0][0]
            self.assertIn( "interjections", call_args )
            
            # Verify result
            self.assertEqual( result, ["wow", "hey", "oh", "hmm"] )
    
    def test_get_interjections_with_length( self ):
        """
        Test getting interjections with specific length.
        
        Ensures:
            - Returns requested number of interjections
            - Handles length parameter correctly
        """
        with patch( 'cosa.training.xml_prompt_generator.du.get_file_as_list' ) as mock_get_file, \
             patch.object( XmlPromptGenerator, '_test_command_paths' ), \
             patch.object( XmlPromptGenerator, 'get_salutations' ):
            
            mock_get_file.return_value = ["wow", "hey", "oh", "hmm", "uh"]
            
            generator = XmlPromptGenerator()
            result = generator.get_interjections( requested_length=3 )
            
            # Verify result length
            self.assertEqual( len( result ), 3 )
            
            # Verify all items are from original list
            for item in result:
                self.assertIn( item, ["wow", "hey", "oh", "hmm", "uh"] )
    
    def test_get_salutations_success( self ):
        """
        Test successful salutation generation.
        
        Ensures:
            - Loads computer names from file
            - Generates salutations with names
            - Returns requested number of salutations
        """
        # Live contract: get_salutations reads TWO placeholder files ( receptionist
        # names, then receptionist salutations ) and substitutes the COMPUTER_NAME
        # placeholder with a randomly-chosen name.
        with self._mock_command_loading(), \
             patch( 'cosa.training.xml_prompt_generator.du.get_file_as_list' ) as mock_get_file, \
             patch.object( XmlPromptGenerator, 'get_interjections', return_value=[] ), \
             patch( 'random.choice', return_value="Alice" ):

            def fake_get_file( path, **kwargs ):
                # Names file vs salutations file are distinguished by filename.
                return [ "Alice", "Bob" ] if "names" in path else [ "hello COMPUTER_NAME", "hi COMPUTER_NAME" ]

            # Function side_effect is reusable, so the __init__ call to get_salutations
            # consumes it harmlessly; reset only the call counters before the explicit call.
            mock_get_file.side_effect = fake_get_file

            generator = XmlPromptGenerator( path_prefix="/test/path" )
            mock_get_file.reset_mock()

            result = generator.get_salutations( requested_length=2 )

            # Verify both placeholder files were read, salutations file last
            self.assertEqual( mock_get_file.call_count, 2 )
            self.assertIn( "receptionist-salutations", mock_get_file.call_args[0][0] )

            # Verify result: COMPUTER_NAME substituted with the chosen name
            self.assertEqual( result, [ "hello Alice", "hi Alice" ] )
    
    def test_insert_interjection_success( self ):
        """
        Test successful interjection insertion.
        
        Ensures:
            - Inserts interjection at random position
            - Returns tuple with interjection and modified text
            - Handles word boundaries correctly
        """
        with patch.object( XmlPromptGenerator, '_test_command_paths' ), \
             patch.object( XmlPromptGenerator, 'get_interjections' ), \
             patch.object( XmlPromptGenerator, 'get_salutations' ), \
             patch( 'random.choice' ) as mock_choice, \
             patch( 'random.randint' ) as mock_randint:
            
            mock_choice.return_value = "wow"
            mock_randint.return_value = 1  # Insert after first word
            
            generator = XmlPromptGenerator()
            interjections = ["wow", "hey"]
            
            result = generator.insert_interjection( "hello world test", interjections )
            
            # Verify return type
            self.assertIsInstance( result, tuple )
            self.assertEqual( len( result ), 2 )
            
            # Verify interjection and modified text
            chosen_interjection, modified_text = result
            self.assertEqual( chosen_interjection, "wow" )
            self.assertIn( "wow", modified_text )
            self.assertIn( "hello", modified_text )
            self.assertIn( "world", modified_text )
    
    def test_insert_interjection_with_defaults( self ):
        """
        Test interjection insertion with default interjections.
        
        Ensures:
            - Uses instance interjections when none provided
            - Handles default parameter correctly
        """
        with patch.object( XmlPromptGenerator, '_test_command_paths' ), \
             patch.object( XmlPromptGenerator, 'get_salutations' ), \
             patch( 'random.choice' ) as mock_choice, \
             patch( 'random.randint' ) as mock_randint:
            
            mock_choice.return_value = "hey"
            mock_randint.return_value = 0

            # Mock get_interjections to return specific list
            with patch.object( XmlPromptGenerator, 'get_interjections' ) as mock_get_interjections:
                mock_get_interjections.return_value = ["hey", "wow"]

                generator = XmlPromptGenerator()
                result = generator.insert_interjection( "test text" )

                # Verify interjection was used. Live contract: when inserted at
                # index 0 the interjection is Capitalized, so "hey" -> "Hey".
                chosen_interjection, modified_text = result
                self.assertEqual( chosen_interjection, "hey" )
                self.assertIn( "Hey", modified_text )
                self.assertTrue( modified_text.startswith( "Hey" ) )
    
    def test_prepend_salutation_success( self ):
        """
        Test successful salutation prepending.
        
        Ensures:
            - Prepends salutation to text
            - Returns tuple with salutation and modified text
            - Handles spacing correctly
        """
        with patch.object( XmlPromptGenerator, '_test_command_paths' ), \
             patch.object( XmlPromptGenerator, 'get_interjections' ), \
             patch.object( XmlPromptGenerator, 'get_salutations' ), \
             patch( 'random.choice' ) as mock_choice:
            
            mock_choice.return_value = "Hello Computer"
            
            generator = XmlPromptGenerator()
            salutations = ["Hello Computer", "Hi there"]
            
            result = generator.prepend_salutation( "test message", salutations )
            
            # Verify return type
            self.assertIsInstance( result, tuple )
            self.assertEqual( len( result ), 2 )
            
            # Verify salutation and modified text
            chosen_salutation, modified_text = result
            self.assertEqual( chosen_salutation, "Hello Computer" )
            self.assertTrue( modified_text.startswith( "Hello Computer" ) )
            self.assertIn( "test message", modified_text )
    
    def test_get_prompt_template_success( self ):
        """
        Test successful prompt template retrieval.
        
        Ensures:
            - Returns correct template for known names
            - Templates are properly formatted
        """
        # Live contract: get_prompt_template accepts only "vox command" or
        # "agent router" and returns a fully-formatted, de-indented prompt string
        # embedding the appropriate command-block markup.
        with self._mock_command_loading(), \
             patch.object( XmlPromptGenerator, 'get_interjections', return_value=[] ), \
             patch.object( XmlPromptGenerator, 'get_salutations', return_value=[] ):

            generator = XmlPromptGenerator( path_prefix="/test/path" )

            cases = [
                ( "vox command",  "<browser-commands>" ),
                ( "agent router", "<agent-routing-commands>" ),
            ]

            for name, command_block in cases:
                with self.subTest( template_name=name ):
                    result = generator.get_prompt_template( name )

                    self.assertIsInstance( result, str )
                    self.assertIn( command_block, result )
                    self.assertIn( "### Instruction:", result )
                    self.assertIn( "### Response:", result )
    
    def test_get_prompt_template_unknown( self ):
        """
        Test prompt template retrieval with unknown name.
        
        Ensures:
            - Raises ValueError for unknown template names
            - Provides descriptive error message
        """
        with self._mock_command_loading(), \
             patch.object( XmlPromptGenerator, 'get_interjections', return_value=[] ), \
             patch.object( XmlPromptGenerator, 'get_salutations', return_value=[] ):

            generator = XmlPromptGenerator( path_prefix="/test/path" )

            with self.assertRaises( ValueError ) as context:
                generator.get_prompt_template( "unknown_template" )

            # Live contract: message reads "Unknown prompt template name [...]"
            error_message = str( context.exception )
            self.assertIn( "Unknown prompt template name", error_message )
            self.assertIn( "unknown_template", error_message )
    
    def test_get_prompt_instruction_format( self ):
        """
        Test prompt instruction formatting.
        
        Ensures:
            - Combines instruction and input correctly
            - Returns properly formatted prompt
        """
        with patch.object( XmlPromptGenerator, '_test_command_paths' ), \
             patch.object( XmlPromptGenerator, 'get_interjections' ), \
             patch.object( XmlPromptGenerator, 'get_salutations' ):
            
            generator = XmlPromptGenerator()
            
            instruction = "Test instruction"
            input_text = "Test input"
            
            result = generator._get_prompt_instruction_format( instruction, input_text )
            
            # Verify format
            self.assertIsInstance( result, str )
            self.assertIn( instruction, result )
            self.assertIn( input_text, result )
            self.assertIn( "### Instruction:", result )
            self.assertIn( "### Input:", result )
    
    def test_get_prompt_with_output( self ):
        """
        Test prompt generation when an output argument is supplied.

        Live contract note: get_prompt accepts an `output` parameter but the
        current implementation does NOT incorporate it into the returned prompt
        ( the body never references `output`; all production callers pass "" ).
        This test pins the actual behaviour — the output text is NOT embedded —
        and is flagged as a vestigial-parameter smell for manager review.

        Ensures:
            - Returns a formatted prompt with instruction + input embedded
            - The "### Response:" trailer is always present
            - The supplied output is NOT embedded ( vestigial parameter )
        """
        with self._mock_command_loading(), \
             patch.object( XmlPromptGenerator, 'get_interjections', return_value=[] ), \
             patch.object( XmlPromptGenerator, 'get_salutations', return_value=[] ):

            generator = XmlPromptGenerator( path_prefix="/test/path" )

            instruction = "Test instruction"
            input_text = "Test input"
            output = "Test output"

            result = generator.get_prompt( instruction, input_text, output )

            # Verify format
            self.assertIsInstance( result, str )
            self.assertIn( instruction, result )
            self.assertIn( input_text, result )
            self.assertIn( "### Response:", result )
            # Vestigial-parameter contract: output is accepted but not embedded
            self.assertNotIn( output, result )
    
    def test_get_prompt_without_output( self ):
        """
        Test prompt generation without an output argument.

        Live contract: _get_prompt_instruction_format ALWAYS appends a trailing
        "### Response:" section, whether or not output is supplied — so the
        trailer is present even in the no-output case.

        Ensures:
            - Returns a formatted prompt with instruction + input embedded
            - The "### Response:" trailer is present ( always emitted )
        """
        with self._mock_command_loading(), \
             patch.object( XmlPromptGenerator, 'get_interjections', return_value=[] ), \
             patch.object( XmlPromptGenerator, 'get_salutations', return_value=[] ):

            generator = XmlPromptGenerator( path_prefix="/test/path" )

            instruction = "Test instruction"
            input_text = "Test input"

            result = generator.get_prompt( instruction, input_text )

            # Verify format
            self.assertIsInstance( result, str )
            self.assertIn( instruction, result )
            self.assertIn( input_text, result )
            self.assertIn( "### Response:", result )
    
    # NOTE: test_format_gpt_message was REMOVED ( 2026-06-01, Rio ⚡ WAVE-2 training lane ).
    # It exercised XmlPromptGenerator.format_gpt_message, a method that has NEVER existed
    # in the tracked production source ( `git log -S format_gpt_message` on the prod file
    # returns nothing; zero non-test references repo-wide ). With no live contract to bind,
    # the stale test is deleted rather than rewritten.

    def test_serialize_prompt( self ):
        """
        Test prompt serialization to file.
        
        Ensures:
            - Writes prompt to specified file
            - Handles file operations correctly
        """
        # Live contract: serialize_prompt writes via du.write_string_to_file( path, prompt )
        # where path = self.path_prefix + prompt_path ( NOT a bare open(path,"w") ).
        with self._mock_command_loading(), \
             patch.object( XmlPromptGenerator, 'get_interjections', return_value=[] ), \
             patch.object( XmlPromptGenerator, 'get_salutations', return_value=[] ), \
             patch( 'cosa.training.xml_prompt_generator.du.write_string_to_file' ) as mock_write, \
             patch( 'cosa.training.xml_prompt_generator.du.print_banner' ):

            generator = XmlPromptGenerator( path_prefix="/test/path" )

            test_prompt = "This is a test prompt"
            test_path = "/path/to/prompt.txt"

            generator.serialize_prompt( test_prompt, test_path )

            # Verify the write goes to path_prefix-joined path with the prompt body
            mock_write.assert_called_once_with( "/test/path/path/to/prompt.txt", test_prompt )
    
    def test_serialize_prompts( self ):
        """
        Test serialization of all prompt templates.
        
        Ensures:
            - Serializes all available templates
            - Creates files with correct names
            - Handles multiple template types
        """
        with patch.object( XmlPromptGenerator, '_test_command_paths' ), \
             patch.object( XmlPromptGenerator, 'get_interjections' ), \
             patch.object( XmlPromptGenerator, 'get_salutations' ), \
             patch.object( XmlPromptGenerator, 'serialize_prompt' ) as mock_serialize:
            
            generator = XmlPromptGenerator()
            
            # Set up mock templates
            generator.vox_cmd_instruction_template = "vox template"
            generator.agent_router_instruction_template = "router template"
            
            test_prefix = "/test/prefix"
            generator.serialize_prompts( test_prefix )
            
            # Verify serialize_prompt was called for templates
            self.assertGreater( mock_serialize.call_count, 0 )
            
            # Verify calls included expected templates
            call_args_list = [call[0] for call in mock_serialize.call_args_list]
            template_contents = [args[0] for args in call_args_list]
            
            # Should include at least some of our mock templates
            found_templates = any( "template" in content for content in template_contents )
            self.assertTrue( found_templates )
    
    def test_test_command_paths_success( self ):
        """
        Test successful command path validation.
        
        Ensures:
            - Validates all command paths exist
            - Prints status when not silent
        """
        # Make construction inert ( command getters mocked ) so os.path.exists is
        # exercised ONLY by the explicit _test_command_paths call below, not by __init__.
        with self._mock_command_loading(), \
             patch.object( XmlPromptGenerator, 'get_interjections', return_value=[] ), \
             patch.object( XmlPromptGenerator, 'get_salutations', return_value=[] ), \
             patch( 'os.path.exists' ) as mock_exists, \
             patch( 'builtins.print' ) as mock_print:

            mock_exists.return_value = True

            generator = XmlPromptGenerator( debug=True, silent=False )
            mock_exists.reset_mock()
            mock_print.reset_mock()
            generator._test_command_paths( self.test_commands )

            # Verify path checking: one existence check per command
            self.assertEqual( mock_exists.call_count, len( self.test_commands ) )

            # Verify debug output
            self.assertGreater( mock_print.call_count, 0 )
    
    def test_test_command_paths_missing_file( self ):
        """
        Test command path validation with missing file.
        
        Ensures:
            - Raises exception for missing files
            - Provides descriptive error message
        """
        # Make construction inert ( command getters mocked ) so the missing-file
        # exception is raised by the explicit call, not during __init__ validation.
        with self._mock_command_loading(), \
             patch.object( XmlPromptGenerator, 'get_interjections', return_value=[] ), \
             patch.object( XmlPromptGenerator, 'get_salutations', return_value=[] ), \
             patch( 'os.path.exists' ) as mock_exists:

            mock_exists.return_value = False

            generator = XmlPromptGenerator( path_prefix="/test/path" )

            with self.assertRaises( Exception ) as context:
                generator._test_command_paths( self.test_commands )
            
            error_message = str( context.exception )
            self.assertIn( "doesn't exist", error_message )
            # Should mention one of the test commands
            command_mentioned = any( cmd in error_message for cmd in self.test_commands.keys() )
            self.assertTrue( command_mentioned )
    
    def test_error_handling_file_operations( self ):
        """
        Test error handling during file operations.
        
        Ensures:
            - Handles file reading errors gracefully
            - Propagates appropriate exceptions
        """
        with patch( 'cosa.training.xml_prompt_generator.du.get_file_as_list' ) as mock_get_file, \
             patch.object( XmlPromptGenerator, '_test_command_paths' ), \
             patch.object( XmlPromptGenerator, 'get_salutations' ):
            
            # Simulate file reading error
            mock_get_file.side_effect = IOError( "File not found" )
            
            with self.assertRaises( IOError ):
                XmlPromptGenerator()


def isolated_unit_test():
    """
    Run comprehensive unit tests for XML prompt generator in complete isolation.
    
    Ensures:
        - All external dependencies mocked
        - No real file operations or template loading
        - Deterministic test results
        - Fast execution
        
    Returns:
        Tuple[bool, float, str]: (success, duration, message)
    """
    import cosa.utils.util as du
    
    start_time = time.time()
    
    try:
        du.print_banner( "XML Prompt Generator Unit Tests - Training Phase 6", prepend_nl=True )
        
        # Create test suite
        suite = unittest.TestSuite()
        
        # Add working test methods (focus on testable core functionality)
        test_methods = [
            'test_initialization_success',
            'test_get_interjections_with_length',
            'test_insert_interjection_success',
            'test_prepend_salutation_success',
            'test_get_prompt_instruction_format',
            'test_serialize_prompts',
            'test_error_handling_file_operations'
        ]
        
        for method in test_methods:
            suite.addTest( TestXmlPromptGenerator( method ) )
        
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
        print( f"XML PROMPT GENERATOR UNIT TEST RESULTS" )
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
            du.print_banner( "✅ ALL XML PROMPT GENERATOR TESTS PASSED", prepend_nl=True )
            message = f"All {tests_run} tests passed successfully in {duration:.3f}s"
        else:
            du.print_banner( "❌ SOME XML PROMPT GENERATOR TESTS FAILED", prepend_nl=True )
            message = f"{failures} failures, {errors} errors out of {tests_run} tests"
        
        return success, duration, message
        
    except Exception as e:
        duration = time.time() - start_time
        error_msg = f"Unit test execution failed: {str(e)}"
        du.print_banner( f"💥 XML PROMPT GENERATOR TEST ERROR: {error_msg}", prepend_nl=True )
        return False, duration, error_msg


if __name__ == "__main__":
    success, duration, message = isolated_unit_test()
    status = "✅ PASS" if success else "❌ FAIL"
    print( f"\n{status} XML prompt generator unit tests completed in {duration:.3f}s" )
    print( f"Result: {message}" )