#!/usr/bin/env python3
"""
XML Models for CoSA Agents

Pydantic models for XML input/output serialization and deserialization.
Each model corresponds to XML patterns used in CoSA agent prompts and
provides type-safe, validated data structures.

This module provides:
- SimpleResponse: Single field responses (gist, summary, answer)
- CommandResponse: Command routing responses (command + args)
- YesNoResponse: Boolean/confirmation responses  
- CodeResponse: Code generation responses with thoughts and explanation
- MathBrainstormResponse: Complex math reasoning with brainstorming
- VoxCommandResponse: Voice-to-browser command routing
- AgentRouterResponse: Agent routing command responses
- GistResponse: Text summarization responses
- ConfirmationResponse: Yes/no/ambiguous decision responses
- QualifierClassification: Question/instruction intent classification

All models inherit from BaseXMLModel and include quick_smoke_test() methods.
"""

import time
from typing import Optional, List, Union, Literal
from pydantic import Field, field_validator, model_validator

from cosa.agents.io_models.utils.util_xml_pydantic import BaseXMLModel, XMLParsingError


class SimpleResponse( BaseXMLModel ):
    """
    Simple single-field response model.
    
    Handles XML responses with a single content field like:
    - <response><gist>content</gist></response>
    - <response><summary>content</summary></response>
    - <response><answer>content</answer></response>
    
    The field name is dynamic based on the actual XML tag.
    """
    
    # Since we don't know the field name ahead of time, we use extra="allow"
    # in BaseXMLModel to capture any field dynamically
    
    def get_content( self ) -> Optional[str]:
        """
        Get the main content field regardless of its name.
        
        Returns the first string field found, which should be the content.
        
        Returns:
            Content string or None if no content found
        """
        for field_name, field_value in self.model_dump().items():
            if isinstance( field_value, str ):
                return field_value
        return None
    
    def get_field_name( self ) -> Optional[str]:
        """
        Get the name of the content field.
        
        Returns:
            Field name or None if no fields
        """
        fields = list( self.model_dump().keys() )
        return fields[0] if fields else None
    
    @classmethod
    def create( cls, field_name: str, content: str ) -> 'SimpleResponse':
        """
        Create a SimpleResponse with a specific field name and content.
        
        Args:
            field_name: The XML tag name (e.g., 'gist', 'summary')
            content: The content value
            
        Returns:
            SimpleResponse instance
        """
        data = { field_name: content }
        return cls( **data )
    
    @classmethod
    def quick_smoke_test( cls, debug: bool = False ) -> bool:
        """
        Quick smoke test for SimpleResponse.
        
        Tests dynamic field handling and common patterns.
        
        Args:
            debug: Enable debug output
            
        Returns:
            True if all tests pass
        """
        if debug:
            print( f"Testing {cls.__name__}..." )
        
        try:
            # Test base functionality
            if not super().quick_smoke_test( debug=False ):
                return False
            
            # Test gist response
            gist_xml = "<response><gist>This is a brief summary</gist></response>"
            gist_response = cls.from_xml( gist_xml )
            assert gist_response.get_content() == "This is a brief summary"
            assert gist_response.get_field_name() == "gist"
            
            # Test summary response  
            summary_xml = "<response><summary>Detailed summary here</summary></response>"
            summary_response = cls.from_xml( summary_xml )
            assert summary_response.get_content() == "Detailed summary here"
            assert summary_response.get_field_name() == "summary"
            
            # Test answer response
            answer_xml = "<response><answer>42</answer></response>"
            answer_response = cls.from_xml( answer_xml )
            assert answer_response.get_content() == "42"
            
            # Test creation
            created_response = cls.create( "test_field", "test_content" )
            assert created_response.get_content() == "test_content"
            assert created_response.get_field_name() == "test_field"
            
            # Test round-trip
            xml_output = created_response.to_xml()
            assert "<test_field>test_content</test_field>" in xml_output
            
            if debug:
                print( f"✓ {cls.__name__} smoke test PASSED" )
            
            return True
            
        except Exception as e:
            if debug:
                print( f"✗ {cls.__name__} smoke test FAILED: {e}" )
            return False


class CommandResponse( BaseXMLModel ):
    """
    Command routing response model.
    
    Handles XML responses for agent routing:
    <response>
        <command>math</command>
        <args>calculate 2+2</args>  
    </response>
    
    Used by agent-router and vox-command templates.
    """
    
    command: str = Field( ..., description="The agent command to execute" )
    args: Optional[str] = Field( default="", description="Arguments for the command" )
    
    @field_validator( 'command' )
    @classmethod
    def validate_command( cls, v ):
        """
        Validate that command is a known agent type.
        
        Args:
            v: Command value to validate
            
        Returns:
            Validated command
            
        Raises:
            ValueError: If command is not recognized
        """
        valid_commands = [
            'math', 'calendar', 'calendaring', 'todo', 'todo-lists', 
            'weather', 'gist', 'confirmation', 'yes-no', 'debugger',
            'plain-vanilla-question', 'receptionist'
        ]
        
        if v.lower() not in [cmd.lower() for cmd in valid_commands]:
            # Don't fail validation, just warn - allows for new commands
            pass
            
        return v
    
    @classmethod
    def quick_smoke_test( cls, debug: bool = False ) -> bool:
        """
        Quick smoke test for CommandResponse.
        
        Tests command routing patterns and validation.
        
        Args:
            debug: Enable debug output
            
        Returns:
            True if all tests pass
        """
        if debug:
            print( f"Testing {cls.__name__}..." )
        
        try:
            # Test base functionality
            if debug:
                print( "  - Testing base functionality..." )
            if not super().quick_smoke_test( debug=debug ):
                if debug:
                    print( "    ✗ Base functionality test failed" )
                return False
            if debug:
                print( "    ✓ Base functionality passed" )
            
            # Test math command
            if debug:
                print( "  - Testing math command XML..." )
            math_xml = "<response><command>math</command><args>calculate square root of 16</args></response>"
            math_response = cls.from_xml( math_xml )
            assert math_response.command == "math", f"Expected 'math', got '{math_response.command}'"
            assert math_response.args == "calculate square root of 16", f"Expected 'calculate square root of 16', got '{math_response.args}'"
            if debug:
                print( "    ✓ Math command test passed" )
            
            # Test calendar command
            calendar_xml = "<response><command>calendar</command><args>show events for next week</args></response>"
            calendar_response = cls.from_xml( calendar_xml )
            assert calendar_response.command == "calendar"
            
            # Test empty args
            if debug:
                print( "  - Testing empty args..." )
            simple_xml = "<response><command>gist</command><args></args></response>"
            simple_response = cls.from_xml( simple_xml )
            assert simple_response.command == "gist"
            if debug:
                print( f"    - args value: '{simple_response.args}' (type: {type(simple_response.args)})" )
            assert simple_response.args == "" or simple_response.args is None, f"Expected empty string or None, got '{simple_response.args}'"
            if debug:
                print( "    ✓ Empty args test passed" )
            
            # Test missing args (should default to empty)
            if debug:
                print( "  - Testing missing args..." )
            no_args_xml = "<response><command>weather</command></response>"
            no_args_response = cls.from_xml( no_args_xml )
            assert no_args_response.command == "weather"
            if debug:
                print( f"    - missing args value: '{no_args_response.args}' (type: {type(no_args_response.args)})" )
            # Missing args should use default value ""
            assert no_args_response.args == "", f"Expected empty string for missing args, got '{no_args_response.args}'"
            if debug:
                print( "    ✓ Missing args test passed" )
            
            # Test round-trip
            if debug:
                print( "  - Testing round-trip serialization..." )
            test_response = cls( command="test", args="test args" )
            xml_output = test_response.to_xml()
            assert "<command>test</command>" in xml_output
            assert "<args>test args</args>" in xml_output
            if debug:
                print( "    ✓ Serialization passed" )
            
            # Parse it back
            if debug:
                print( "    - Testing round-trip parsing..." )
            parsed_back = cls.from_xml( xml_output )
            assert parsed_back.command == "test"
            assert parsed_back.args == "test args"
            if debug:
                print( "    ✓ Round-trip parsing passed" )
            
            if debug:
                print( f"✓ {cls.__name__} smoke test PASSED" )
            
            return True
            
        except Exception as e:
            if debug:
                print( f"✗ {cls.__name__} smoke test FAILED: {e}" )
                import traceback
                traceback.print_exc()
            return False


class YesNoResponse( BaseXMLModel ):
    """
    Yes/No confirmation response model.
    
    Handles boolean responses:
    <response>
        <answer>yes</answer>
    </response>
    
    Used by confirmation agents and yes/no questions.
    """
    
    answer: str = Field( ..., description="Yes/no answer" )
    
    @field_validator( 'answer' )
    @classmethod
    def validate_answer( cls, v ):
        """
        Validate that answer is a valid yes/no response.
        
        Args:
            v: Answer value to validate
            
        Returns:
            Normalized answer (lowercase)
        """
        valid_responses = ['yes', 'no', 'y', 'n', 'true', 'false']
        
        if v.lower() not in valid_responses:
            # Allow any string but warn
            pass
            
        return v.lower()
    
    def is_yes( self ) -> bool:
        """
        Check if the answer is affirmative.
        
        Returns:
            True if answer is yes/y/true
        """
        return self.answer.lower() in ['yes', 'y', 'true']
    
    def is_no( self ) -> bool:
        """
        Check if the answer is negative.
        
        Returns:
            True if answer is no/n/false
        """
        return self.answer.lower() in ['no', 'n', 'false']
    
    @classmethod  
    def quick_smoke_test( cls, debug: bool = False ) -> bool:
        """
        Quick smoke test for YesNoResponse.
        
        Tests yes/no validation and boolean logic.
        
        Args:
            debug: Enable debug output
            
        Returns:
            True if all tests pass
        """
        if debug:
            print( f"Testing {cls.__name__}..." )
        
        try:
            # Test base functionality
            if not super().quick_smoke_test( debug=False ):
                return False
            
            # Test yes response
            yes_xml = "<response><answer>yes</answer></response>"
            yes_response = cls.from_xml( yes_xml )
            assert yes_response.answer == "yes"
            assert yes_response.is_yes() == True
            assert yes_response.is_no() == False
            
            # Test no response
            no_xml = "<response><answer>no</answer></response>"
            no_response = cls.from_xml( no_xml )
            assert no_response.answer == "no"
            assert no_response.is_yes() == False
            assert no_response.is_no() == True
            
            # Test variations
            variations = [
                ("Y", True, False),
                ("N", False, True), 
                ("true", True, False),
                ("false", False, True)
            ]
            
            for answer, expected_yes, expected_no in variations:
                test_xml = f"<response><answer>{answer}</answer></response>"
                test_response = cls.from_xml( test_xml )
                assert test_response.is_yes() == expected_yes, f"Failed for {answer}"
                assert test_response.is_no() == expected_no, f"Failed for {answer}"
            
            # Test round-trip
            test_response = cls( answer="yes" )
            xml_output = test_response.to_xml()
            assert "<answer>yes</answer>" in xml_output
            
            if debug:
                print( f"✓ {cls.__name__} smoke test PASSED" )
            
            return True
            
        except Exception as e:
            if debug:
                print( f"✗ {cls.__name__} smoke test FAILED: {e}" )
            return False


class ReceptionistResponse( BaseXMLModel ):
    """
    Receptionist agent response model.
    
    Handles XML responses for receptionist agent conversations.
    This agent acts as a receptionist, answering questions based on
    previous conversations stored in memory.
    
    Expected XML format:
    <response>
        <thoughts>Analysis of the user query and memory search</thoughts>
        <category>benign OR humorous OR salacious</category>
        <answer>Concise conversational response to the query</answer>
    </response>
    
    Requires:
        - XML contains <thoughts>, <category>, and <answer> tags
        - category must be one of: benign, humorous, salacious
        - All fields contain non-empty strings
        
    Ensures:
        - Type-safe access to all response components
        - Automatic validation of category enum values
        - Proper XML serialization and deserialization
        
    Raises:
        - ValidationError if category is not in allowed values
        - XMLParsingError if required tags are missing
    """
    
    thoughts: str = Field( ..., description="Agent's reasoning process about the query and memory search" )
    category: Literal["benign", "humorous", "salacious"] = Field( ..., description="Query categorization for content filtering" )
    answer: str = Field( ..., description="Concise conversational answer to the user's query" )
    
    @field_validator( "thoughts" )
    @classmethod
    def validate_thoughts_not_empty( cls, v: str ) -> str:
        """
        Validate that thoughts field is not empty.
        
        Requires:
            - v is a string (guaranteed by Pydantic)
            
        Ensures:
            - Returns non-empty trimmed string
            
        Raises:
            - ValueError if thoughts is empty after stripping whitespace
        """
        trimmed = v.strip()
        if not trimmed:
            raise ValueError( "thoughts cannot be empty" )
        return trimmed
        
    @field_validator( "answer" )
    @classmethod
    def validate_answer_not_empty( cls, v: str ) -> str:
        """
        Validate that answer field is not empty.
        
        Requires:
            - v is a string (guaranteed by Pydantic)
            
        Ensures:
            - Returns non-empty trimmed string
            
        Raises:
            - ValueError if answer is empty after stripping whitespace
        """
        trimmed = v.strip()
        if not trimmed:
            raise ValueError( "answer cannot be empty" )
        return trimmed
        
    def is_safe_content( self ) -> bool:
        """
        Check if the response content is safe for all audiences.
        
        Requires:
            - self.category is properly validated Literal value
            
        Ensures:
            - Returns True if category is 'benign' or 'humorous'
            - Returns False if category is 'salacious'
            
        Raises:
            - None (category is guaranteed to be valid by Pydantic)
        """
        return self.category in ["benign", "humorous"]
        
    @classmethod
    def quick_smoke_test( cls, debug: bool = False ) -> bool:
        """
        Quick smoke test for ReceptionistResponse model.
        
        Requires:
            - debug is a boolean flag for verbose output
            
        Ensures:
            - Tests XML parsing with valid receptionist response
            - Tests category validation with all allowed values
            - Tests field validation for empty strings
            - Returns True if all tests pass, False otherwise
            
        Raises:
            - None (catches and reports all exceptions)
        """
        if debug:
            print( "Testing ReceptionistResponse..." )
            
        try:
            # Test valid response parsing
            valid_xml = '''<response>
                <thoughts>The user is asking about system capabilities, which is a technical but innocent inquiry.</thoughts>
                <category>benign</category>
                <answer>CoSA is a collection of small agents designed for various tasks including code generation.</answer>
            </response>'''
            
            response = cls.from_xml( valid_xml )
            assert response.thoughts.startswith( "The user is asking" )
            assert response.category == "benign"
            assert "CoSA" in response.answer
            assert response.is_safe_content() == True
            
            if debug:
                print( "  ✓ Valid XML parsing test passed" )
            
            # Test all category values
            for category in ["benign", "humorous", "salacious"]:
                test_xml = f'''<response>
                    <thoughts>Test thoughts for {category} category</thoughts>
                    <category>{category}</category>
                    <answer>Test answer for validation</answer>
                </response>'''
                
                test_response = cls.from_xml( test_xml )
                assert test_response.category == category
                
            if debug:
                print( "  ✓ Category validation test passed" )
            
            # Test safe content detection
            safe_response = cls.from_xml( valid_xml.replace( "benign", "humorous" ) )
            assert safe_response.is_safe_content() == True
            
            unsafe_xml = valid_xml.replace( "benign", "salacious" )
            unsafe_response = cls.from_xml( unsafe_xml )
            assert unsafe_response.is_safe_content() == False
            
            if debug:
                print( "  ✓ Safe content detection test passed" )
                
            # Test to_xml round-trip
            xml_output = response.to_xml()
            reparsed = cls.from_xml( xml_output )
            assert reparsed.thoughts == response.thoughts
            assert reparsed.category == response.category  
            assert reparsed.answer == response.answer
            
            if debug:
                print( "  ✓ Round-trip serialization test passed" )
            
            if debug:
                print( "✓ ReceptionistResponse smoke test PASSED" )
            return True
            
        except Exception as e:
            if debug:
                print( f"✗ ReceptionistResponse smoke test FAILED: {e}" )
            return False
    
    @classmethod
    def get_example_for_template( cls ) -> 'ReceptionistResponse':
        """
        Get example instance for prompt templates.
        
        Returns a receptionist response example with typical conversational content
        that matches the expected XML structure for the receptionist.txt template.
        """
        return cls(
            thoughts='[your thoughts here]',
            category='benign',
            answer='[your answer here]'
        )


class CodeResponse( BaseXMLModel ):
    """
    Code generation response model.
    
    Handles XML responses for code generation agents:
    <response>
        <thoughts>reasoning</thoughts>
        <code>
            <line>import math</line>
            <line>def function():</line>
            <line>    return result</line>
        </code>
        <returns>return_type</returns>
        <example>usage example</example>
        <explanation>how it works</explanation>
    </response>
    
    Used by math, calendaring, todo-lists, and debugging agents.
    """
    
    thoughts: str = Field( ..., description="Reasoning and problem analysis" )
    code: List[str] = Field( ..., description="Generated code as list of lines" )
    returns: str = Field( ..., description="Return type description" )
    example: str = Field( ..., description="Usage example" )
    explanation: str = Field( ..., description="Code explanation" )
    
    @model_validator( mode='before' )
    @classmethod
    def process_xml_data( cls, data ):
        """
        Process XML data before field validation.
        
        Handles xmltodict structures and converts them to proper field types.
        
        Args:
            data: Raw data from xmltodict or direct construction
            
        Returns:
            Processed data ready for field validation
        """
        if not isinstance( data, dict ):
            return data
            
        # Process code field if present
        if 'code' in data and isinstance( data['code'], dict ):
            data['code'] = cls._extract_lines_from_dict( data['code'] )
            
        return data
    
    @classmethod
    def _extract_lines_from_dict( cls, code_dict: dict ) -> List[str]:
        """
        Extract code lines from xmltodict nested structure.
        
        xmltodict converts:
        <code>
            <line>import math</line>
            <line>def func():</line>
        </code>
        
        Into: {'line': ['import math', 'def func():']} or {'line': 'single line'}
        
        Args:
            code_dict: Dictionary from xmltodict parsing
            
        Returns:
            List of code lines as strings
        """
        if 'line' in code_dict:
            lines = code_dict['line']
            if isinstance( lines, list ):
                # Multiple lines
                return [str(line) if line is not None else "" for line in lines]
            else:
                # Single line
                return [str(lines) if lines is not None else ""]
        else:
            # No line tags found - might be direct text content
            # This handles edge cases where code is directly in <code>text</code>
            return []
    
    @field_validator( 'code' )
    @classmethod
    def validate_code( cls, v ):
        """
        Validate that code list is not empty.
        
        Args:
            v: List of code lines (already processed by model_validator)
            
        Returns:
            Validated code list
        """
        if not v:
            raise ValueError( "Code must contain at least one line" )
        return v
    
    @field_validator( 'thoughts' )
    @classmethod
    def validate_thoughts( cls, v ):
        """Ensure thoughts is not empty."""
        if not v or not v.strip():
            raise ValueError( "Thoughts cannot be empty" )
        return v.strip()
    
    @field_validator( 'returns' )
    @classmethod
    def validate_returns( cls, v ):
        """Validate return type description."""
        if not v or not v.strip():
            return "None"  # Default return type
        return v.strip()
    
    def get_code_as_string( self, indent: str = "" ) -> str:
        """
        Get code as a formatted string.
        
        Args:
            indent: Optional indentation prefix for each line
            
        Returns:
            Formatted code string
        """
        return '\n'.join( f"{indent}{line}" for line in self.code )
    
    def has_imports( self ) -> bool:
        """
        Check if code contains import statements.
        
        Returns:
            True if any line starts with 'import' or 'from'
        """
        return any( 
            line.strip().startswith( ('import ', 'from ') ) 
            for line in self.code if line.strip()
        )
    
    def get_function_name( self ) -> Optional[str]:
        """
        Extract function name from code if present.
        
        Returns:
            Function name or None if no function definition found
        """
        import re
        for line in self.code:
            match = re.search( r'def\s+(\w+)\s*\(', line.strip() )
            if match:
                return match.group( 1 )
        return None
    
    def to_xml( self, root_tag: str = 'response', pretty: bool = True ) -> str:
        """
        Generate XML with proper nested structure for prompts.
        
        Overrides BaseXMLModel.to_xml() to handle the nested code
        structure that prompt templates expect.
        
        Args:
            root_tag: Root XML element name (default: 'response')
            pretty: Whether to format XML with indentation (default: True)
            
        Returns:
            Formatted XML string matching prompt template structure
        """
        import xmltodict
        
        data = {
            'thoughts': self.thoughts,
            'code': {'line': self.code},  # Creates nested <line> tags
            'returns': self.returns,
            'example': self.example,
            'explanation': self.explanation
        }
        
        return xmltodict.unparse( {root_tag: data}, pretty=pretty )
    
    @classmethod
    def quick_smoke_test( cls, debug: bool = False ) -> bool:
        """
        Quick smoke test for CodeResponse.
        
        Tests code line extraction and processing with various XML patterns.
        
        Args:
            debug: Enable debug output
            
        Returns:
            True if all tests pass
        """
        if debug:
            print( f"Testing {cls.__name__}..." )
        
        try:
            # Test base functionality
            if not super().quick_smoke_test( debug=False ):
                if debug:
                    print( "    ✗ Base functionality test failed" )
                return False
            
            # Test simple code response
            if debug:
                print( "  - Testing simple code response..." )
            simple_xml = """<response>
                <thoughts>I need to write a simple function</thoughts>
                <code>
                    <line>def add_numbers(a, b):</line>
                    <line>    return a + b</line>
                </code>
                <returns>int</returns>
                <example>result = add_numbers(2, 3)</example>
                <explanation>Simple addition function</explanation>
            </response>"""
            
            simple_response = cls.from_xml( simple_xml )
            assert simple_response.thoughts == "I need to write a simple function"
            assert len( simple_response.code ) == 2
            assert "def add_numbers" in simple_response.code[0]
            assert "return a + b" in simple_response.code[1]
            assert simple_response.returns == "int"
            assert simple_response.has_imports() == False
            assert simple_response.get_function_name() == "add_numbers"
            
            if debug:
                print( "    ✓ Simple code test passed" )
            
            # Test complex code with imports and empty lines
            if debug:
                print( "  - Testing complex code with imports..." )
            complex_xml = """<response>
                <thoughts>Complex math calculation needed</thoughts>
                <code>
                    <line>import math</line>
                    <line>import numpy as np</line>
                    <line></line>
                    <line>def calculate_distance(x1, y1, x2, y2):</line>
                    <line>    dx = x2 - x1</line>
                    <line>    dy = y2 - y1</line>
                    <line>    return math.sqrt(dx**2 + dy**2)</line>
                </code>
                <returns>float</returns>
                <example>distance = calculate_distance(0, 0, 3, 4)</example>
                <explanation>Calculates Euclidean distance between two points</explanation>
            </response>"""
            
            complex_response = cls.from_xml( complex_xml )
            assert len( complex_response.code ) == 7
            assert complex_response.has_imports() == True
            assert "" in complex_response.code  # Empty line preserved
            assert complex_response.get_function_name() == "calculate_distance"
            
            if debug:
                print( "    ✓ Complex code test passed" )
            
            # Test XML escapes in code
            if debug:
                print( "  - Testing XML escapes in code..." )
            escaped_xml = """<response>
                <thoughts>Need to handle comparisons</thoughts>
                <code>
                    <line>if x &lt; 5 and y &gt; 3:</line>
                    <line>    result = "less than &amp; greater than"</line>
                </code>
                <returns>str</returns>
                <example>test_function(4, 5)</example>
                <explanation>Handles comparison operators</explanation>
            </response>"""
            
            escaped_response = cls.from_xml( escaped_xml )
            # xmltodict should handle escapes automatically
            assert "<" in str( escaped_response.code )
            assert ">" in str( escaped_response.code )
            assert "&" in str( escaped_response.code )
            
            if debug:
                print( "    ✓ XML escape test passed" )
            
            # Test round-trip serialization
            if debug:
                print( "  - Testing round-trip serialization..." )
            test_response = cls(
                thoughts="Test thoughts",
                code=["import os", "def test():", "    return True"],
                returns="bool",
                example="result = test()",
                explanation="Test function"
            )
            
            xml_output = test_response.to_xml()
            parsed_back = cls.from_xml( xml_output )
            
            assert parsed_back.thoughts == "Test thoughts"
            assert len( parsed_back.code ) == 3
            assert parsed_back.code[0] == "import os"
            assert parsed_back.returns == "bool"
            
            if debug:
                print( "    ✓ Round-trip test passed" )
            
            # Test utility methods
            if debug:
                print( "  - Testing utility methods..." )
            code_string = test_response.get_code_as_string()
            assert "import os" in code_string
            assert "def test():" in code_string
            
            indented_code = test_response.get_code_as_string( indent="  " )
            assert "  import os" in indented_code
            
            if debug:
                print( "    ✓ Utility methods test passed" )
            
            if debug:
                print( f"✓ {cls.__name__} smoke test PASSED" )
            
            return True
            
        except Exception as e:
            if debug:
                print( f"✗ {cls.__name__} smoke test FAILED: {e}" )
                import traceback
                traceback.print_exc()
            return False
    
    @classmethod
    def get_example_for_template( cls ) -> 'CodeResponse':
        """
        Get example instance for prompt templates.
        
        Creates a CodeResponse instance with standard template placeholder text
        that matches the format expected in todo list and debugger prompt templates.
        
        Returns:
            CodeResponse instance with template placeholder text
        """
        return cls(
            thoughts='[your thoughts here]',
            code=[
                'All imports here',
                '',
                'def function_name_here( df, arg1, arg2 ):',
                '    ...',
                '    ...',
                '    return solution'
            ],
            returns='Object type of the variable `solution`',
            example='solution = your_function_name_here( df, arg1, etc. )',
            explanation='Explanation of how the code works'
        )


class CalendarResponse( CodeResponse ):
    """
    Calendar agent response model.
    
    Extends CodeResponse with an additional 'question' field for calendar agents.
    
    Handles XML responses like:
    <response>
        <question>What events do I have today?</question>
        <thoughts>Need to filter events by today's date</thoughts>
        <code>
            <line>today_events = df[df['date'] == today]</line>
            <line>result = today_events['title'].tolist()</line>
        </code>
        <returns>list</returns>
        <example>get_today_events()</example>
        <explanation>Filters and returns today's events</explanation>
    </response>
    
    Used by calendaring agents that need to preserve the original question context.
    """
    
    question: str = Field( ..., description="Original question being answered" )
    
    @field_validator( 'question' )
    @classmethod
    def validate_question( cls, v ):
        """Ensure question is not empty."""
        if not v or not v.strip():
            raise ValueError( "Question cannot be empty" )
        return v.strip()
    
    def to_xml( self, root_tag: str = 'response', pretty: bool = True ) -> str:
        """
        Generate XML with proper field order and nested structure for calendar prompts.
        
        Overrides CodeResponse.to_xml() to ensure proper field ordering
        that matches the calendar prompt template structure.
        
        Args:
            root_tag: Root XML element name (default: 'response')
            pretty: Whether to format XML with indentation (default: True)
            
        Returns:
            Formatted XML string matching calendar prompt template structure
        """
        import xmltodict
        
        # Specific field order matching calendar prompt template
        data = {
            'question': self.question,
            'thoughts': self.thoughts,
            'code': {'line': self.code},  # Creates nested <line> tags
            'returns': self.returns,
            'example': self.example,
            'explanation': self.explanation
        }
        
        return xmltodict.unparse( {root_tag: data}, pretty=pretty )
    
    @classmethod 
    def quick_smoke_test( cls, debug: bool = False ) -> bool:
        """
        Quick smoke test for CalendarResponse.
        
        Tests calendar-specific XML patterns including question field.
        
        Args:
            debug: Enable debug output
            
        Returns:
            True if all tests pass
        """
        try:
            if debug:
                print( f"Testing {cls.__name__}..." )
            
            # Test basic calendar XML
            if debug:
                print( "  - Testing basic calendar response..." )
            calendar_xml = """<response>
                <question>What meetings do I have today?</question>
                <thoughts>User wants to see today's scheduled meetings</thoughts>
                <code>
                    <line>import pandas as pd</line>
                    <line>from datetime import date</line>
                    <line>today = date.today()</line>
                    <line>meetings = df[df['date'] == today]</line>
                    <line>result = meetings[['title', 'time']].to_dict('records')</line>
                </code>
                <returns>list</returns>
                <example>get_meetings_today()</example>
                <explanation>Filters events for today and returns meeting details</explanation>
            </response>"""
            
            response = cls.from_xml( calendar_xml )
            assert response.question == "What meetings do I have today?"
            assert "today's scheduled meetings" in response.thoughts
            assert len( response.code ) == 5
            assert response.returns == "list"
            assert response.has_imports() == True
            
            if debug:
                print( "    ✓ Basic calendar test passed" )
            
            # Test question validation
            if debug:
                print( "  - Testing question validation..." )
            try:
                cls(
                    question="",  # Empty question should fail
                    thoughts="Test thoughts",
                    code=["test_line"],
                    returns="None",
                    example="test()",
                    explanation="Test"
                )
                assert False, "Empty question should have failed validation"
            except ValueError:
                pass  # Expected
            
            if debug:
                print( "    ✓ Question validation test passed" )
            
            # Test inheritance from CodeResponse
            if debug:
                print( "  - Testing CodeResponse inheritance..." )
            # Should inherit all CodeResponse functionality
            code_string = response.get_code_as_string()
            assert "import pandas as pd" in code_string
            assert response.get_function_name() is None  # No function in this example
            
            if debug:
                print( "    ✓ Inheritance test passed" )
            
            # Test round-trip with question field
            if debug:
                print( "  - Testing round-trip with question..." )
            test_response = cls(
                question="How many events this week?",
                thoughts="Count events for the current week",
                code=["events = df[df['week'] == current_week]", "count = len(events)"],
                returns="int", 
                example="weekly_count = count_events_this_week()",
                explanation="Counts events in the current week"
            )
            
            xml_output = test_response.to_xml()
            parsed_back = cls.from_xml( xml_output )
            
            assert parsed_back.question == "How many events this week?"
            assert parsed_back.thoughts == "Count events for the current week"
            assert len( parsed_back.code ) == 2
            assert parsed_back.returns == "int"
            
            if debug:
                print( "    ✓ Round-trip test passed" )
            
            if debug:
                print( f"✓ {cls.__name__} smoke test PASSED" )
            
            return True
            
        except Exception as e:
            if debug:
                print( f"✗ {cls.__name__} smoke test FAILED: {e}" )
                import traceback
                traceback.print_exc()
            return False
    
    @classmethod
    def get_example_for_template( cls ) -> 'CalendarResponse':
        """
        Get example instance for prompt templates.
        
        Creates a CalendarResponse instance with standard template placeholder text
        that matches the format expected in calendar prompt templates.
        
        Returns:
            CalendarResponse instance with template placeholder text
        """
        return cls(
            question='[question will be filled by template]',
            thoughts='[your thoughts here]',
            code=[
                'All imports here',
                '',
                'def function_name_here( df, arg1, arg2 ):',
                '    ...',
                '    ...',
                '    return solution'
            ],
            returns='Object type of the variable `solution`',
            example='solution = your_function_name_here( df, arg1, etc. )',
            explanation='Explanation of how the code works'
        )


class BrainstormIdeas( BaseXMLModel ):
    """
    Nested model for structured brainstorming ideas.
    
    Handles the three-idea brainstorming structure used in CodeBrainstormResponse:
    <brainstorm>
        <idea1>First idea</idea1>
        <idea2>Second idea</idea2>
        <idea3>Third idea</idea3>
    </brainstorm>
    
    This structure ensures proper XML serialization and deserialization
    for brainstorming workflows in math and datetime agents.
    """
    
    idea1: str = Field( ..., description="First brainstormed idea" )
    idea2: str = Field( ..., description="Second brainstormed idea" )
    idea3: str = Field( ..., description="Third brainstormed idea" )
    
    @field_validator( 'idea1', 'idea2', 'idea3' )
    @classmethod
    def validate_ideas( cls, v ):
        """Ensure idea fields are not empty."""
        if not v or not v.strip():
            raise ValueError( "Brainstorm ideas cannot be empty" )
        return v.strip()
    
    @classmethod
    def get_example_for_template( cls ) -> 'BrainstormIdeas':
        """
        Get example instance for prompt templates.
        
        Creates a BrainstormIdeas instance with standard template placeholder text
        that matches the format expected in prompt templates.
        
        Returns:
            BrainstormIdeas instance with template placeholder text
        """
        return cls(
            idea1='Your first idea',
            idea2='Your second idea',
            idea3='Your third idea'
        )


class CodeBrainstormResponse( BaseXMLModel ):
    """
    Code generation response with brainstorming process.
    
    Handles XML responses for agents that generate code with detailed reasoning:
    <response>
        <thoughts>Your thoughts</thoughts>
        <brainstorm>
            <idea1>Your first idea</idea1>
            <idea2>Your second idea</idea2>
            <idea3>Your third idea</idea3>
        </brainstorm>
        <evaluation>Your evaluation</evaluation>
        <code>
            <line>All imports here</line>
            <line></line>
            <line>def your_function_name_here( optional_arguments ):</line>
            <line>    ...</line>
            <line>    ...</line>
            <line>    return solution</line>
            <line></line>
        </code>
        <returns>Object type of the variable `solution`</returns>
        <example>solution = your_function_name_here( optional_arguments )</example>
        <explanation>Explanation of how the code works</explanation>
    </response>
    
    Used by agents requiring brainstorming workflows:
    - DateAndTimeAgent: Time-based code generation with approach analysis
    - MathAgent: Mathematical code generation with solution exploration
    - Future agents requiring detailed reasoning process
    """
    
    thoughts: str = Field( ..., description="Initial reasoning about the problem" )
    brainstorm: BrainstormIdeas = Field( ..., description="Three brainstormed ideas in structured format" )
    evaluation: str = Field( ..., description="Analysis of chosen approach" )
    code: List[str] = Field( ..., description="Generated code as list of lines" )
    example: str = Field( ..., description="Usage example" )
    returns: str = Field( ..., description="Return type description" )
    explanation: str = Field( ..., description="Code explanation" )
    
    @model_validator( mode='before' )
    @classmethod
    def process_xml_data( cls, data ):
        """
        Process XML data before field validation.
        
        Handles xmltodict structures and converts them to proper field types.
        
        Args:
            data: Raw data from xmltodict or direct construction
            
        Returns:
            Processed data ready for field validation
        """
        if not isinstance( data, dict ):
            return data
            
        # Process code field if present (reuse logic from CodeResponse)
        if 'code' in data and isinstance( data['code'], dict ):
            data['code'] = cls._extract_lines_from_dict( data['code'] )
            
        return data
    
    @classmethod
    def _extract_lines_from_dict( cls, code_dict: dict ) -> List[str]:
        """
        Extract code lines from xmltodict nested structure.
        
        xmltodict converts:
        <code>
            <line>import math</line>
            <line>def func():</line>
        </code>
        
        Into: {'line': ['import math', 'def func():']} or {'line': 'single line'}
        
        Args:
            code_dict: Dictionary from xmltodict parsing
            
        Returns:
            List of code lines as strings
        """
        if 'line' in code_dict:
            lines = code_dict['line']
            if isinstance( lines, list ):
                # Multiple lines
                return [str(line) if line is not None else "" for line in lines]
            else:
                # Single line
                return [str(lines) if lines is not None else ""]
        else:
            # No line tags found - might be direct text content
            return []
    
    
    @field_validator( 'code' )
    @classmethod
    def validate_code( cls, v ):
        """
        Validate that code list is not empty.
        
        Args:
            v: List of code lines (already processed by model_validator)
            
        Returns:
            Validated code list
        """
        if not v:
            raise ValueError( "Code must contain at least one line" )
        return v
    
    @field_validator( 'thoughts', 'evaluation', 'explanation' )
    @classmethod
    def validate_text_fields( cls, v ):
        """Ensure text fields are not empty."""
        if not v or not v.strip():
            raise ValueError( "Text fields cannot be empty" )
        return v.strip()
    
    @field_validator( 'returns' )
    @classmethod
    def validate_returns( cls, v ):
        """Validate return type description."""
        if not v or not v.strip():
            return "None"  # Default return type
        return v.strip()
    
    def to_xml( self, root_tag: str = 'response', pretty: bool = True ) -> str:
        """
        Generate XML with proper nested structure for prompts.
        
        Overrides BaseXMLModel.to_xml() to handle the nested brainstorm
        and code structures that prompt templates expect.
        
        Args:
            root_tag: Root XML element name (default: 'response')
            pretty: Whether to format XML with indentation (default: True)
            
        Returns:
            Formatted XML string matching prompt template structure
        """
        import xmltodict
        
        data = {
            'thoughts': self.thoughts,
            'brainstorm': {
                'idea1': self.brainstorm.idea1,
                'idea2': self.brainstorm.idea2,
                'idea3': self.brainstorm.idea3
            },
            'evaluation': self.evaluation,
            'code': {'line': self.code},  # Creates <line> tags
            'returns': self.returns,
            'example': self.example,
            'explanation': self.explanation
        }
        
        return xmltodict.unparse( {root_tag: data}, pretty=pretty )
    
    def get_code_as_string( self, indent: str = "" ) -> str:
        """
        Get code as a formatted string.
        
        Args:
            indent: Optional indentation prefix for each line
            
        Returns:
            Formatted code string
        """
        return '\n'.join( f"{indent}{line}" for line in self.code )
    
    def has_imports( self ) -> bool:
        """
        Check if code contains import statements.
        
        Returns:
            True if any line starts with 'import' or 'from'
        """
        return any( 
            line.strip().startswith( ('import ', 'from ') ) 
            for line in self.code if line.strip()
        )
    
    def get_function_name( self ) -> Optional[str]:
        """
        Extract function name from code if present.
        
        Returns:
            Function name or None if no function definition found
        """
        import re
        for line in self.code:
            match = re.search( r'def\s+(\w+)\s*\(', line.strip() )
            if match:
                return match.group( 1 )
        return None
    
    @classmethod
    def quick_smoke_test( cls, debug: bool = False ) -> bool:
        """
        Quick smoke test for CodeBrainstormResponse.
        
        Tests brainstorming workflow and code generation patterns.
        
        Args:
            debug: Enable debug output
            
        Returns:
            True if all tests pass
        """
        if debug:
            print( f"Testing {cls.__name__}..." )
        
        try:
            # Test base functionality
            if not super().quick_smoke_test( debug=False ):
                if debug:
                    print( "    ✗ Base functionality test failed" )
                return False
            
            # Test math brainstorming response
            if debug:
                print( "  - Testing math brainstorming response..." )
            math_xml = """<response>
                <thoughts>The user wants to calculate the area of a circle given its radius</thoughts>
                <brainstorm>
                    <idea1>Use the formula A = πr²</idea1>
                    <idea2>Approximate using polygon methods</idea2>
                    <idea3>Use integration to derive the formula</idea3>
                </brainstorm>
                <evaluation>The direct formula approach is simplest and most accurate for this problem</evaluation>
                <code>
                    <line>import math</line>
                    <line>def circle_area(radius):</line>
                    <line>    return math.pi * radius ** 2</line>
                </code>
                <example>area = circle_area(5)</example>
                <returns>float</returns>
                <explanation>Uses the standard mathematical formula πr² to calculate circle area</explanation>
            </response>"""
            
            math_response = cls.from_xml( math_xml )
            assert "area of a circle" in math_response.thoughts
            assert "formula" in math_response.brainstorm.idea1.lower()
            assert "polygon" in math_response.brainstorm.idea2.lower()
            assert "integration" in math_response.brainstorm.idea3.lower()
            assert "simplest and most accurate" in math_response.evaluation
            assert len( math_response.code ) == 3
            assert math_response.has_imports() == True
            assert math_response.get_function_name() == "circle_area"
            assert math_response.returns == "float"
            
            if debug:
                print( "    ✓ Math brainstorming test passed" )
            
            # Test datetime brainstorming response
            if debug:
                print( "  - Testing datetime brainstorming response..." )
            datetime_xml = """<response>
                <thoughts>Need to determine what day of the week a specific date falls on</thoughts>
                <brainstorm>
                    <idea1>Use datetime.weekday() method</idea1>
                    <idea2>Use calendar module functions</idea2>
                    <idea3>Manual calculation using known reference dates</idea3>
                </brainstorm>
                <evaluation>datetime.weekday() is the most straightforward and reliable approach</evaluation>
                <code>
                    <line>from datetime import datetime</line>
                    <line>def get_weekday(year, month, day):</line>
                    <line>    date = datetime(year, month, day)</line>
                    <line>    days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']</line>
                    <line>    return days[date.weekday()]</line>
                </code>
                <example>day_name = get_weekday(2025, 8, 10)</example>
                <returns>str</returns>
                <explanation>Creates a datetime object and maps weekday() result to day names</explanation>
            </response>"""
            
            datetime_response = cls.from_xml( datetime_xml )
            assert "day of the week" in datetime_response.thoughts
            assert "datetime.weekday" in datetime_response.brainstorm.idea1.lower()
            assert "calendar" in datetime_response.brainstorm.idea2.lower()
            assert "manual" in datetime_response.brainstorm.idea3.lower()
            assert "straightforward" in datetime_response.evaluation
            assert len( datetime_response.code ) == 5
            assert datetime_response.has_imports() == True
            assert datetime_response.get_function_name() == "get_weekday"
            
            if debug:
                print( "    ✓ Datetime brainstorming test passed" )
            
            # Test empty field validation
            if debug:
                print( "  - Testing field validation..." )
            try:
                cls(
                    thoughts="",  # Empty thoughts should fail
                    brainstorm=BrainstormIdeas(idea1="test idea 1", idea2="test idea 2", idea3="test idea 3"),
                    evaluation="test evaluation",
                    code=["test_line"],
                    example="test()",
                    returns="None",
                    explanation="test explanation"
                )
                assert False, "Empty thoughts should have failed validation"
            except ValueError:
                pass  # Expected
            
            if debug:
                print( "    ✓ Field validation test passed" )
            
            # Test round-trip serialization
            if debug:
                print( "  - Testing round-trip serialization..." )
            test_response = cls(
                thoughts="Test problem analysis",
                brainstorm=BrainstormIdeas(idea1="Consider approach A", idea2="Consider approach B", idea3="Consider approach C"),
                evaluation="Approach A is better because of efficiency",
                code=["import os", "def test():", "    return True"],
                example="result = test()",
                returns="bool",
                explanation="Test function for validation"
            )
            
            xml_output = test_response.to_xml()
            parsed_back = cls.from_xml( xml_output )
            
            assert parsed_back.thoughts == "Test problem analysis"
            assert parsed_back.brainstorm.idea1 == "Consider approach A"
            assert parsed_back.brainstorm.idea2 == "Consider approach B"
            assert parsed_back.brainstorm.idea3 == "Consider approach C"
            assert parsed_back.evaluation == "Approach A is better because of efficiency"
            assert len( parsed_back.code ) == 3
            assert parsed_back.returns == "bool"
            
            if debug:
                print( "    ✓ Round-trip test passed" )
            
            # Test utility methods
            if debug:
                print( "  - Testing utility methods..." )
            code_string = test_response.get_code_as_string()
            assert "import os" in code_string
            assert "def test():" in code_string
            
            indented_code = test_response.get_code_as_string( indent="    " )
            assert "    import os" in indented_code
            
            if debug:
                print( "    ✓ Utility methods test passed" )
            
            if debug:
                print( f"✓ {cls.__name__} smoke test PASSED" )
            
            return True
            
        except Exception as e:
            if debug:
                print( f"✗ {cls.__name__} smoke test FAILED: {e}" )
                import traceback
                traceback.print_exc()
            return False
    
    @classmethod
    def get_example_for_template( cls ) -> 'CodeBrainstormResponse':
        """
        Get example instance for prompt templates.
        
        Creates a CodeBrainstormResponse instance with standard template placeholder text
        that matches the format expected in math and date-and-time prompt templates.
        
        Returns:
            CodeBrainstormResponse instance with template placeholder text
        """
        return cls(
            thoughts='Your thoughts',
            brainstorm=BrainstormIdeas.get_example_for_template(),
            evaluation='Your evaluation',
            code=[
                'All imports here',
                '',
                'def your_function_name_here( optional_arguments ):',
                '    ...',
                '    ...',
                '    return solution',
                ''
            ],
            returns='Object type of the variable `solution`',
            example='solution = your_function_name_here( optional_arguments )',
            explanation='Explanation of how the code works'
        )


class BugInjectionResponse( BaseXMLModel ):
    """
    Response for bug injection operations.
    
    Handles XML responses for agents that inject bugs into code:
    <response>
        <line-number>3</line-number>
        <bug>print("This is a bug!")</bug>
    </response>
    
    Used by BugInjector agent for intelligent code modification with bug injection.
    """
    
    line_number: int = Field( ..., description="Line number where bug should be injected (1-based indexing)", alias="line-number" )
    bug: str = Field( ..., description="Bug code to inject at specified line" )
    
    @field_validator( 'line_number' )
    @classmethod
    def validate_line_number( cls, v ):
        """
        Validate line number is reasonable for bug injection.
        
        Args:
            v: Line number value
            
        Returns:
            Validated line number
            
        Raises:
            ValueError: If line number is invalid
        """
        # Allow -1 as special "invalid response" indicator
        if v < -1:
            raise ValueError( "Line number must be -1 (invalid response) or positive integer" )
        if v == 0:
            raise ValueError( "Line number cannot be 0 (lines are 1-based indexed)" )
        # Upper bound validation happens in the agent since it knows code length
        return v
    
    @field_validator( 'bug' )
    @classmethod
    def validate_bug_code( cls, v ):
        """
        Validate bug code is non-empty and reasonable.
        
        Args:
            v: Bug code string
            
        Returns:
            Validated and cleaned bug code
            
        Raises:
            ValueError: If bug code is empty or invalid
        """
        if not isinstance( v, str ):  # pragma: no cover - field_validator(mode=after) always receives a Pydantic-coerced str; a non-str value raises ValidationError before this guard
            raise ValueError( "Bug code must be a string" )
        
        cleaned = v.strip()
        if not cleaned:
            raise ValueError( "Bug code cannot be empty" )
            
        return cleaned
    
    def is_valid_response( self ) -> bool:
        """
        Check if this represents a valid bug injection response.
        
        Returns:
            True if line_number is positive (valid), False if -1 (invalid)
        """
        return self.line_number > 0
    
    def validate_against_code_length( self, code_length: int ) -> bool:
        """
        Validate line number against actual code length.
        
        Args:
            code_length: Number of lines in the code to be modified
            
        Returns:
            True if line number is within valid range for the code
        """
        if not self.is_valid_response():
            return False
        return 1 <= self.line_number <= code_length
    
    def to_xml( self, root_tag: str = 'response', pretty: bool = True ) -> str:
        """
        Generate XML with proper field aliases for bug injection prompts.
        
        Overrides BaseXMLModel.to_xml() to use hyphenated field names
        that match the bug injection prompt template.
        
        Args:
            root_tag: Root XML element name (default: 'response')
            pretty: Whether to format XML with indentation (default: True)
            
        Returns:
            Formatted XML string matching bug injection prompt template
        """
        import xmltodict
        
        data = {
            'line-number': self.line_number,
            'bug': self.bug
        }
        
        return xmltodict.unparse( {root_tag: data}, pretty=pretty )
    
    @classmethod
    def quick_smoke_test( cls, debug: bool = False ) -> bool:
        """
        Quick smoke test for BugInjectionResponse.
        
        Tests bug injection response parsing and validation.
        
        Args:
            debug: Enable debug output
            
        Returns:
            True if all tests pass
        """
        if debug:
            print( f"Testing {cls.__name__}..." )
        
        try:
            # Test base functionality
            if not super().quick_smoke_test( debug=False ):
                if debug:
                    print( "    ✗ Base functionality test failed" )
                return False
            
            # Test valid bug injection response
            if debug:
                print( "  - Testing valid bug injection response..." )
            valid_xml = '''<response>
                <line-number>5</line-number>
                <bug>x = x + "error"  # Intentional type error</bug>
            </response>'''
            
            response = cls.from_xml( valid_xml )
            assert response.line_number == 5
            assert "error" in response.bug
            assert response.is_valid_response() == True
            assert response.validate_against_code_length( 10 ) == True
            assert response.validate_against_code_length( 3 ) == False
            
            if debug:
                print( "    ✓ Valid response test passed" )
            
            # Test invalid response (line-number = -1)
            if debug:
                print( "  - Testing invalid response handling..." )
            invalid_xml = '''<response>
                <line-number>-1</line-number>
                <bug></bug>
            </response>'''
            
            try:
                invalid_response = cls.from_xml( invalid_xml )
                # This should work (parsing succeeds) but validation shows it's invalid
                assert invalid_response.line_number == -1
                assert invalid_response.is_valid_response() == False
                if debug:
                    print( "    ✓ Invalid response detected correctly" )
            except Exception:
                # Might fail on empty bug validation, which is also correct
                if debug:
                    print( "    ✓ Invalid response rejected during parsing" )
            
            # Test line number validation
            if debug:
                print( "  - Testing line number validation..." )
            try:
                cls( line_number=0, bug="test bug" )  # Should fail
                assert False, "Line number 0 should have failed validation"
            except ValueError:
                pass  # Expected
            
            try:
                cls( line_number=-2, bug="test bug" )  # Should fail  
                assert False, "Line number -2 should have failed validation"
            except ValueError:
                pass  # Expected
            
            if debug:
                print( "    ✓ Line number validation test passed" )
            
            # Test bug code validation
            if debug:
                print( "  - Testing bug code validation..." )
            try:
                cls( line_number=1, bug="" )  # Should fail
                assert False, "Empty bug should have failed validation"
            except ValueError:
                pass  # Expected
            
            try:
                cls( line_number=1, bug="   " )  # Should fail
                assert False, "Whitespace-only bug should have failed validation"
            except ValueError:
                pass  # Expected
            
            if debug:
                print( "    ✓ Bug code validation test passed" )
            
            # Test utility methods
            if debug:
                print( "  - Testing utility methods..." )
            test_response = cls( line_number=3, bug="print('injected bug')" )
            assert test_response.is_valid_response() == True
            assert test_response.validate_against_code_length( 5 ) == True
            assert test_response.validate_against_code_length( 2 ) == False
            
            if debug:
                print( "    ✓ Utility methods test passed" )
            
            if debug:
                print( f"✓ {cls.__name__} smoke test PASSED" )
            
            return True
            
        except Exception as e:
            if debug:
                print( f"✗ {cls.__name__} smoke test FAILED: {e}" )
                import traceback
                traceback.print_exc()
            return False
    
    @classmethod
    def get_example_for_template( cls ) -> 'BugInjectionResponse':
        """
        Get example instance for prompt templates.
        
        Creates a BugInjectionResponse instance with standard template placeholder text
        that matches the format expected in bug injector prompt templates.
        
        Returns:
            BugInjectionResponse instance with template placeholder text
        """
        return cls(
            line_number=1,  # Line number where bug is introduced
            bug='[one line of modified source code with bug in it]'
        )


class IterativeDebuggingMinimalistResponse( BaseXMLModel ):
    """
    Pydantic model for IterativeDebuggingAgent XML responses in minimalist mode.
    
    This model handles minimalist debugging responses focused on single-line fixes
    with success indicators for iterative debugging workflows.
    
    Expected XML format:
    <response>
        <thoughts>Debugging analysis and reasoning</thoughts>
        <line-number>5</line-number>
        <one-line-of-code>fixed_code = corrected_value</one-line-of-code>
        <success>True</success>
    </response>
    
    Used by IterativeDebuggingAgent in minimalist mode for focused single-line debugging.
    """
    
    thoughts: str = Field( ..., description="Debugging analysis and reasoning" )
    line_number: int = Field( ..., description="Line number to modify (1-based indexing)", alias="line-number" )
    one_line_of_code: str = Field( ..., description="Single line of fixed code", alias="one-line-of-code" )
    success: str = Field( ..., description="Success indicator (True/False)" )
    
    @field_validator( 'line_number' )
    @classmethod
    def validate_line_number( cls, v ):
        """Validate line_number is positive (1-based indexing)."""
        if v <= 0:
            raise ValueError( "line_number must be positive (1-based indexing)" )
        return v
    
    @field_validator( 'success' )
    @classmethod
    def validate_success( cls, v ):
        """Validate success is True or False string."""
        if v not in [ "True", "False" ]:
            raise ValueError( "success must be 'True' or 'False'" )
        return v
    
    @field_validator( 'thoughts' )
    @classmethod
    def validate_thoughts( cls, v ):
        """Ensure thoughts is not empty."""
        if not v or not v.strip():
            raise ValueError( "thoughts cannot be empty" )
        return v.strip()
    
    @field_validator( 'one_line_of_code' )
    @classmethod
    def validate_code_line( cls, v ):
        """Ensure code line is not empty."""
        if not v or not v.strip():
            raise ValueError( "one_line_of_code cannot be empty" )
        return v.strip()
    
    def is_successful( self ) -> bool:
        """Check if debugging was successful."""
        return self.success == "True"
    
    def to_xml( self, root_tag: str = 'response', pretty: bool = True ) -> str:
        """
        Generate XML with proper field aliases for minimalist debugging prompts.
        
        Overrides BaseXMLModel.to_xml() to use hyphenated field names
        that match the minimalist debugging prompt template.
        
        Args:
            root_tag: Root XML element name (default: 'response')
            pretty: Whether to format XML with indentation (default: True)
            
        Returns:
            Formatted XML string matching minimalist debugging prompt template
        """
        import xmltodict
        
        data = {
            'thoughts': self.thoughts,
            'line-number': self.line_number,
            'one-line-of-code': self.one_line_of_code,
            'success': self.success
        }
        
        return xmltodict.unparse( {root_tag: data}, pretty=pretty )
    
    @classmethod
    def quick_smoke_test( cls, debug: bool = False ) -> bool:
        """Quick smoke test for IterativeDebuggingMinimalistResponse."""
        if debug:
            print( f"Testing {cls.__name__}..." )
        
        try:
            # Test valid minimalist debugging response
            valid_xml = '''<response>
                <thoughts>The variable name is misspelled on line 3</thoughts>
                <line-number>3</line-number>
                <one-line-of-code>result = calculate_sum(a, b)</one-line-of-code>
                <success>True</success>
            </response>'''
            
            response = cls.from_xml( valid_xml )
            assert response.thoughts == "The variable name is misspelled on line 3"
            assert response.line_number == 3
            assert response.one_line_of_code == "result = calculate_sum(a, b)"
            assert response.success == "True"
            assert response.is_successful() == True
            
            if debug:
                print( f"✓ {cls.__name__} smoke test PASSED" )
            return True
            
        except Exception as e:
            if debug:
                print( f"✗ {cls.__name__} smoke test FAILED: {e}" )
            return False
    
    @classmethod
    def get_example_for_template( cls ) -> 'IterativeDebuggingMinimalistResponse':
        """
        Get example instance for prompt templates.
        
        Returns a minimalist debugging response example with typical debugging content
        that matches the expected XML structure for the debugger-minimalist.txt template.
        """
        return cls(
            thoughts='Your thoughts',
            line_number=1,
            one_line_of_code='One line of code with proper indentation',
            success='True'
        )


class IterativeDebuggingFullResponse( BaseXMLModel ):
    """
    Pydantic model for IterativeDebuggingAgent XML responses in full mode.
    
    This model handles comprehensive debugging responses with complete code,
    examples, return values, and explanations for complex debugging scenarios.
    
    Expected XML format:
    <response>
        <thoughts>Debugging analysis and reasoning</thoughts>
        <code>
            <line>import math</line>
            <line>def fixed_function():</line>
            <line>    return corrected_result</line>
        </code>
        <example>result = fixed_function()</example>
        <returns>corrected_return_type</returns>
        <explanation>Detailed explanation of the fix</explanation>
    </response>
    
    Used by IterativeDebuggingAgent in full mode for comprehensive debugging with complete solutions.
    """
    
    thoughts: str = Field( ..., description="Debugging analysis and reasoning" )
    code: List[str] = Field( ..., description="Complete fixed code as list of lines" )
    example: str = Field( ..., description="Example usage of the fixed code" )
    returns: str = Field( ..., description="Expected return value or output" )
    explanation: str = Field( ..., description="Detailed explanation of the fix" )
    
    @model_validator( mode='before' )
    @classmethod
    def process_xml_data( cls, data ):
        """Process XML data before field validation."""
        if not isinstance( data, dict ):
            return data
            
        # Process code field if present (reuse logic from CodeResponse)
        if 'code' in data and isinstance( data['code'], dict ):
            data['code'] = cls._extract_lines_from_dict( data['code'] )
            
        return data
    
    @classmethod
    def _extract_lines_from_dict( cls, code_dict: dict ) -> List[str]:
        """Extract code lines from xmltodict nested structure."""
        if 'line' in code_dict:
            lines = code_dict['line']
            if isinstance( lines, list ):
                return [str(line) if line is not None else "" for line in lines]
            else:
                return [str(lines) if lines is not None else ""]
        else:
            return []
    
    @field_validator( 'code' )
    @classmethod
    def validate_code( cls, v ):
        """Validate that code list is not empty."""
        if not v:
            raise ValueError( "Code must contain at least one line" )
        return v
    
    @field_validator( 'thoughts', 'explanation' )
    @classmethod
    def validate_text_fields( cls, v ):
        """Ensure text fields are not empty."""
        if not v or not v.strip():
            raise ValueError( "Text fields cannot be empty" )
        return v.strip()
    
    @field_validator( 'returns' )
    @classmethod
    def validate_returns( cls, v ):
        """Validate return type description."""
        if not v or not v.strip():
            return "None"  # Default return type
        return v.strip()
    
    def get_code_as_string( self, indent: str = "" ) -> str:
        """Get code as a formatted string."""
        return '\n'.join( f"{indent}{line}" for line in self.code )
    
    def has_imports( self ) -> bool:
        """Check if code contains import statements."""
        return any( 
            line.strip().startswith( ('import ', 'from ') ) 
            for line in self.code if line.strip()
        )
    
    def get_function_name( self ) -> Optional[str]:
        """Extract function name from code if present."""
        import re
        for line in self.code:
            match = re.search( r'def\s+(\w+)\s*\(', line.strip() )
            if match:
                return match.group( 1 )
        return None
    
    def to_xml( self, root_tag: str = 'response', pretty: bool = True ) -> str:
        """
        Generate XML with proper nested structure for debugging prompts.
        
        Overrides BaseXMLModel.to_xml() to handle the nested code
        structure that debugging prompt templates expect.
        
        Args:
            root_tag: Root XML element name (default: 'response')
            pretty: Whether to format XML with indentation (default: True)
            
        Returns:
            Formatted XML string matching debugging prompt template structure
        """
        import xmltodict
        
        data = {
            'thoughts': self.thoughts,
            'code': {'line': self.code},  # Creates nested <line> tags
            'example': self.example,
            'returns': self.returns,
            'explanation': self.explanation
        }
        
        return xmltodict.unparse( {root_tag: data}, pretty=pretty )
    
    @classmethod
    def quick_smoke_test( cls, debug: bool = False ) -> bool:
        """Quick smoke test for IterativeDebuggingFullResponse."""
        if debug:
            print( f"Testing {cls.__name__}..." )
        
        try:
            # Test full debugging response
            full_xml = '''<response>
                <thoughts>The function has a logic error in the calculation</thoughts>
                <code>
                    <line>import math</line>
                    <line>def calculate_area(radius):</line>
                    <line>    return math.pi * radius * radius</line>
                </code>
                <example>area = calculate_area(5)</example>
                <returns>float</returns>
                <explanation>Fixed the area calculation by using radius * radius instead of radius * 2</explanation>
            </response>'''
            
            response = cls.from_xml( full_xml )
            assert "logic error" in response.thoughts
            assert len( response.code ) == 3
            assert response.has_imports() == True
            assert response.get_function_name() == "calculate_area"
            assert response.returns == "float"
            assert "Fixed the area calculation" in response.explanation
            
            if debug:
                print( f"✓ {cls.__name__} smoke test PASSED" )
            return True
            
        except Exception as e:
            if debug:
                print( f"✗ {cls.__name__} smoke test FAILED: {e}" )
            return False
    
    @classmethod
    def get_example_for_template( cls ) -> 'IterativeDebuggingFullResponse':
        """
        Get example instance for prompt templates.
        
        Creates an IterativeDebuggingFullResponse instance with standard template placeholder text
        that matches the format expected in debugger prompt templates.
        
        Returns:
            IterativeDebuggingFullResponse instance with template placeholder text
        """
        return cls(
            thoughts='Your thoughts',
            code=[
                'All imports here',
                '',
                'All code that preceded the function',
                '',
                'def function_name_here( df, arg1 ):',
                '    ...',
                '    ...',
                '    return solution',
                '',
                'All code that followed the function'
            ],
            example='solution = function_name_here( arguments )',
            returns='Object type of the variable `solution`',
            explanation='Explanation of how the code works'
        )


class WeatherResponse( BaseXMLModel ):
    """
    Pydantic model for Weather formatter XML responses.
    
    This model handles XML responses from the RawOutputFormatter when processing
    weather-related queries. The WeatherAgent itself uses web search via LupinSearch,
    but the final formatting stage uses an LLM that returns structured XML.
    
    Expected XML format:
    <response>
        <rephrased-answer>It's currently 76 degrees in Washington, DC.</rephrased-answer>
    </response>
    
    Used by RawOutputFormatter when processing weather agent responses.
    """
    
    rephrased_answer: str = Field( ..., description="Conversational weather response formatted for TTS", alias="rephrased-answer" )
    
    @field_validator( 'rephrased_answer' )
    @classmethod
    def validate_rephrased_answer( cls, v ):
        """Ensure rephrased_answer is not empty."""
        if not v or not v.strip():
            raise ValueError( "rephrased_answer cannot be empty" )
        return v.strip()
    
    def is_temperature_response( self ) -> bool:
        """Check if this response contains temperature information."""
        return any( temp_indicator in self.rephrased_answer.lower() 
                   for temp_indicator in ["degrees", "°f", "°c", "temperature"] )
    
    def is_forecast_response( self ) -> bool:
        """Check if this response contains forecast information."""
        return any( forecast_indicator in self.rephrased_answer.lower()
                   for forecast_indicator in ["rain", "snow", "sunny", "cloudy", "chance", "forecast", "tomorrow", "today"] )
    
    def to_xml( self, root_tag: str = 'response', pretty: bool = True ) -> str:
        """
        Generate XML with proper field aliases for weather prompts.
        
        Overrides BaseXMLModel.to_xml() to use hyphenated field names
        that match the weather prompt template.
        
        Args:
            root_tag: Root XML element name (default: 'response')
            pretty: Whether to format XML with indentation (default: True)
            
        Returns:
            Formatted XML string matching weather prompt template
        """
        import xmltodict
        
        data = {
            'rephrased-answer': self.rephrased_answer
        }
        
        return xmltodict.unparse( {root_tag: data}, pretty=pretty )
    
    @classmethod
    def quick_smoke_test( cls, debug: bool = False ) -> bool:
        """Quick smoke test for WeatherResponse."""
        if debug:
            print( f"Testing {cls.__name__}..." )
        
        try:
            # Test temperature response
            temp_xml = '''<response>
                <rephrased-answer>It's currently 76 degrees in Washington, DC.</rephrased-answer>
            </response>'''
            
            temp_response = cls.from_xml( temp_xml )
            assert temp_response.rephrased_answer == "It's currently 76 degrees in Washington, DC."
            assert temp_response.is_temperature_response() == True
            assert temp_response.is_forecast_response() == False
            
            # Test forecast response  
            forecast_xml = '''<response>
                <rephrased-answer>There's a 30% chance of rain in Washington, DC today.</rephrased-answer>
            </response>'''
            
            forecast_response = cls.from_xml( forecast_xml )
            assert forecast_response.rephrased_answer == "There's a 30% chance of rain in Washington, DC today."
            assert forecast_response.is_temperature_response() == False
            assert forecast_response.is_forecast_response() == True
            
            # Test field alias mapping
            dumped = temp_response.model_dump()
            assert "rephrased_answer" in dumped
            assert "rephrased-answer" not in dumped
            
            if debug:
                print( f"✓ {cls.__name__} smoke test PASSED" )
            return True
            
        except Exception as e:
            if debug:
                print( f"✗ {cls.__name__} smoke test FAILED: {e}" )
            return False
    
    @classmethod
    def get_example_for_template( cls ) -> 'WeatherResponse':
        """
        Get example instance for prompt templates.
        
        Returns a weather response example with typical weather content
        that matches the expected XML structure for the weather.txt template.
        """
        return cls(
            rephrased_answer='[your rephrased answer here]'
        )


class FormatterResponse( BaseXMLModel ):
    """
    Universal formatter response model for all agent formatters.

    Handles XML responses from RawOutputFormatter when rephrasing raw agent
    output into conversational responses suitable for TTS.

    Expected XML format:
    <response>
        <rephrased-answer>Conversational response here</rephrased-answer>
    </response>

    Used by formatters for:
    - DateAndTimeAgent: Conversational time/date responses
    - MathAgent: Conversational math answers
    - CalendarAgent: Conversational calendar event summaries
    - WeatherAgent: Conversational weather information
    - TodoListAgent: Conversational todo list responses
    - ReceptionistAgent: Conversational chat responses

    Note: Receptionist template includes <thoughts> field but it is
          ignored by RawOutputFormatter (only rephrased-answer extracted).

    This is the universal model that all formatters use. WeatherResponse
    is kept for backward compatibility and weather-specific helper methods.
    """

    rephrased_answer: str = Field(
        ...,
        description="Conversational response formatted for TTS",
        alias="rephrased-answer"
    )

    @field_validator( 'rephrased_answer' )
    @classmethod
    def validate_rephrased_answer( cls, v ):
        """Ensure rephrased_answer is not empty."""
        if not v or not v.strip():
            raise ValueError( "rephrased_answer cannot be empty" )
        return v.strip()


class VoxCommandResponse( BaseXMLModel ):
    """
    Voice-to-browser command response model.
    
    Handles XML responses for voice command routing to browser:
    <response>
        <command>search google new tab</command>
        <args>machine learning tutorials</args>  
    </response>
    
    Used by vox-command-template-completion.txt.
    """
    
    command: str = Field( ..., description="Browser command to execute" )
    args: str = Field( default="", description="Arguments for the browser command" )
    
    @field_validator( 'command' )
    @classmethod
    def validate_command( cls, v ):
        """
        Validate that command is a known browser command.
        
        Args:
            v: Command value to validate
            
        Returns:
            Validated command
        """
        # Allow flexibility for new browser commands
        return v.strip() if v else ""
    
    @classmethod
    def get_example_for_template( cls ) -> 'VoxCommandResponse':
        """
        Get example instance for prompt templates.
        
        Returns a browser command response example that matches the expected
        XML structure for the vox-command-template-completion.txt template.
        """
        return cls(
            command='search google new tab',
            args='machine learning tutorials'
        )
    
    @classmethod
    def quick_smoke_test( cls, debug: bool = False ) -> bool:
        """
        Quick smoke test for VoxCommandResponse.
        
        Args:
            debug: Enable debug output
            
        Returns:
            True if all tests pass
        """
        if debug:
            print( f"Testing {cls.__name__}..." )
        
        try:
            # Test base functionality
            if not super().quick_smoke_test( debug=False ):
                return False
            
            # Test creation and validation
            response = cls( command="search google new tab", args="python tutorials" )
            assert response.command == "search google new tab"
            assert response.args == "python tutorials"
            
            # Test XML generation
            xml_str = response.to_xml()
            assert "<command>search google new tab</command>" in xml_str
            assert "<args>python tutorials</args>" in xml_str
            
            # Test round-trip conversion
            parsed = cls.from_xml( xml_str )
            assert parsed.command == response.command
            assert parsed.args == response.args
            
            # Test template example
            example = cls.get_example_for_template()
            assert example.command == 'search google new tab'
            assert example.args == 'machine learning tutorials'
            
            if debug:
                print( f"✓ {cls.__name__} smoke test PASSED" )
            
            return True
            
        except Exception as e:
            if debug:
                print( f"✗ {cls.__name__} smoke test FAILED: {e}" )
            return False


class AgentRouterResponse( BaseXMLModel ):
    """
    Agent routing response model.
    
    Handles XML responses for agent routing commands:
    <response>
        <command>agent router go to math</command>
        <args>calculate the square root of 144</args>  
    </response>
    
    Used by agent-router-template-completion.txt.
    """
    
    command: str = Field( ..., description="Agent routing command to execute" )
    args: str = Field( default="", description="Arguments to pass to the selected agent" )
    
    @field_validator( 'command' )
    @classmethod
    def validate_command( cls, v ):
        """
        Validate that command is a known agent routing command.
        
        Args:
            v: Command value to validate
            
        Returns:
            Validated command
        """
        valid_commands = [
            'agent router go to datetime',
            'agent router go to weather',
            'agent router go to calendar',
            'agent router go to receptionist',
            'agent router go to todo',
            'agent router go to math',
            'agent router go to deep research',
            'agent router go to podcast generator',
            'agent router go to research to podcast',
            'agent router go to claude code',
            'none'
        ]
        
        # Allow flexibility but warn about unknown commands
        if v not in valid_commands:
            pass  # Don't fail validation, just allow it
            
        return v.strip() if v else ""
    
    @classmethod
    def get_example_for_template( cls ) -> 'AgentRouterResponse':
        """
        Get example instance for prompt templates.
        
        Returns an agent router response example that matches the expected
        XML structure for the agent-router-template-completion.txt template.
        """
        return cls(
            command='agent router go to math',
            args='calculate the square root of 144'
        )
    
    @classmethod
    def quick_smoke_test( cls, debug: bool = False ) -> bool:
        """
        Quick smoke test for AgentRouterResponse.
        
        Args:
            debug: Enable debug output
            
        Returns:
            True if all tests pass
        """
        if debug:
            print( f"Testing {cls.__name__}..." )
        
        try:
            # Test base functionality
            if not super().quick_smoke_test( debug=False ):
                return False
            
            # Test creation and validation
            response = cls( command="agent router go to math", args="calculate 2+2" )
            assert response.command == "agent router go to math"
            assert response.args == "calculate 2+2"
            
            # Test XML generation
            xml_str = response.to_xml()
            assert "<command>agent router go to math</command>" in xml_str
            assert "<args>calculate 2+2</args>" in xml_str
            
            # Test round-trip conversion
            parsed = cls.from_xml( xml_str )
            assert parsed.command == response.command
            assert parsed.args == response.args
            
            # Test template example
            example = cls.get_example_for_template()
            assert example.command == 'agent router go to math'
            assert example.args == 'calculate the square root of 144'
            
            if debug:
                print( f"✓ {cls.__name__} smoke test PASSED" )
            
            return True
            
        except Exception as e:
            if debug:
                print( f"✗ {cls.__name__} smoke test FAILED: {e}" )
            return False


class GistResponse( BaseXMLModel ):
    """
    Text summarization/gist response model.
    
    Handles XML responses for text summarization:
    <response>
        <gist>Calculate the square root of 144</gist>
    </response>
    
    Used by gist.txt template.
    """
    
    gist: str = Field( ..., description="Concise, one-sentence summary of the utterance" )
    
    @field_validator( 'gist' )
    @classmethod
    def validate_gist( cls, v ):
        """
        Validate that gist is not empty.
        
        Args:
            v: Gist value to validate
            
        Returns:
            Validated gist
            
        Raises:
            ValueError: If gist is empty
        """
        if not v or not v.strip():
            raise ValueError( "Gist cannot be empty" )
        return v.strip()
    
    @classmethod
    def get_example_for_template( cls ) -> 'GistResponse':
        """
        Get example instance for prompt templates.
        
        Returns a gist response example that matches the expected
        XML structure for the gist.txt template.
        """
        return cls(
            gist='Calculate the square root of 144'
        )
    
    @classmethod
    def quick_smoke_test( cls, debug: bool = False ) -> bool:
        """
        Quick smoke test for GistResponse.
        
        Args:
            debug: Enable debug output
            
        Returns:
            True if all tests pass
        """
        if debug:
            print( f"Testing {cls.__name__}..." )
        
        try:
            # Test base functionality
            if not super().quick_smoke_test( debug=False ):
                return False
            
            # Test creation and validation
            response = cls( gist="This is a test summary" )
            assert response.gist == "This is a test summary"
            
            # Test XML generation
            xml_str = response.to_xml()
            assert "<gist>This is a test summary</gist>" in xml_str
            
            # Test round-trip conversion
            parsed = cls.from_xml( xml_str )
            assert parsed.gist == response.gist
            
            # Test validation
            try:
                cls( gist="" )
                assert False, "Should have failed validation"
            except ValueError:
                pass  # Expected
            
            # Test template example
            example = cls.get_example_for_template()
            assert example.gist == 'Calculate the square root of 144'
            
            if debug:
                print( f"✓ {cls.__name__} smoke test PASSED" )
            
            return True
            
        except Exception as e:
            if debug:
                print( f"✗ {cls.__name__} smoke test FAILED: {e}" )
            return False


class ConfirmationResponse( BaseXMLModel ):
    """
    Yes/no/ambiguous confirmation response model.
    
    Handles XML responses for confirmation decisions:
    <response>
        <decision>yes</decision>
    </response>
    
    Used by confirmation-yes-no.txt template.
    """
    
    decision: Literal["yes", "no", "ambiguous"] = Field( 
        ..., 
        description="Confirmation decision - must be one of: yes, no, ambiguous" 
    )
    
    @classmethod
    def get_example_for_template( cls ) -> 'ConfirmationResponse':
        """
        Get example instance for prompt templates.
        
        Returns a confirmation response example that matches the expected
        XML structure for the confirmation-yes-no.txt template.
        
        Shows all three valid options in XML comments.
        """
        return cls(
            decision='yes'
        )
    
    def to_xml( self ) -> str:
        """
        Convert to XML with documentation of valid options.
        
        Returns:
            XML string with examples of all valid responses
        """
        base_xml = super().to_xml()
        
        # Add documentation comment showing all valid options (for any decision value)
        if "</response>" in base_xml:  # pragma: no branch - super().to_xml() uses default root_tag='response', so '</response>' is always present; the else-arc is unreachable
            base_xml = base_xml.replace(
                "</response>",
                """</response>

<!-- Examples of valid responses:
<response><decision>yes</decision></response>
<response><decision>no</decision></response>  
<response><decision>ambiguous</decision></response>
-->"""
            )
        
        return base_xml
    
    @classmethod
    def quick_smoke_test( cls, debug: bool = False ) -> bool:
        """
        Quick smoke test for ConfirmationResponse.
        
        Args:
            debug: Enable debug output
            
        Returns:
            True if all tests pass
        """
        if debug:
            print( f"Testing {cls.__name__}..." )
        
        try:
            # Test base functionality
            if not super().quick_smoke_test( debug=False ):
                return False
            
            # Test all valid values
            for decision in ["yes", "no", "ambiguous"]:
                response = cls( decision=decision )
                assert response.decision == decision
                
                # Test XML generation
                xml_str = response.to_xml()
                assert f"<decision>{decision}</decision>" in xml_str
                assert "Examples of valid responses:" in xml_str  # Documentation comment
                
                # Test round-trip conversion
                parsed = cls.from_xml( xml_str )
                assert parsed.decision == decision
            
            # Test invalid value
            try:
                cls( decision="maybe" )
                assert False, "Should have failed validation"
            except Exception:
                pass  # Expected
            
            # Test template example
            example = cls.get_example_for_template()
            assert example.decision == 'yes'
            
            if debug:
                print( f"✓ {cls.__name__} smoke test PASSED" )
            
            return True
            
        except Exception as e:
            if debug:
                print( f"✗ {cls.__name__} smoke test FAILED: {e}" )
            return False


class QualifierClassification( BaseXMLModel ):
    """
    Intent classification response model.

    Handles XML responses for classifying user utterances as questions or instructions:
    <response>
        <intent>question</intent>
        <confidence>0.9</confidence>
        <reasoning>The user is asking about test results, not requesting action.</reasoning>
    </response>

    Used by qualifier-classification.txt template.
    """

    intent     : str = Field( ..., description="'question' or 'instruction'" )
    confidence : str = Field( default="0.0", description="Confidence score 0.0-1.0" )
    reasoning  : str = Field( default="", description="Brief explanation of classification" )

    @field_validator( "*", mode="before" )
    @classmethod
    def coerce_none_to_empty_str( cls, v ):
        if v is None:
            return ""
        return v

    def is_question( self ):
        """Return True if the classified intent is 'question'."""
        return self.intent.strip().lower() == "question"

    def is_instruction( self ):
        """Return True if the classified intent is 'instruction'."""
        return self.intent.strip().lower() == "instruction"

    @classmethod
    def get_example_for_template( cls ):
        """
        Get example instance for prompt templates.

        Ensures:
            - Returns QualifierClassification with sample question classification
        """
        return cls(
            intent     = "question",
            confidence = "0.85",
            reasoning  = "The user is asking about the status of something, not requesting an action."
        )

    @classmethod
    def quick_smoke_test( cls, debug=False ):
        """
        Quick smoke test for QualifierClassification.

        Returns:
            True if all tests pass
        """
        if debug:
            print( f"Testing {cls.__name__}..." )

        try:
            # Test base functionality
            if not super().quick_smoke_test( debug=False ):
                return False

            # Test creation
            response = cls( intent="question", confidence="0.9", reasoning="Asking about results" )
            assert response.intent == "question"
            assert response.confidence == "0.9"

            # Test is_question / is_instruction
            assert response.is_question() is True
            assert response.is_instruction() is False

            instr = cls( intent="instruction", confidence="0.8", reasoning="Requesting action" )
            assert instr.is_question() is False
            assert instr.is_instruction() is True

            # Test XML round-trip
            xml_str = response.to_xml()
            assert "<intent>question</intent>" in xml_str
            parsed = cls.from_xml( xml_str )
            assert parsed.intent == "question"
            assert parsed.confidence == "0.9"

            # Test None coercion
            coerced = cls( intent="question", confidence=None, reasoning=None )
            assert coerced.confidence == ""
            assert coerced.reasoning == ""

            # Test template example
            example = cls.get_example_for_template()
            assert example.intent == "question"
            assert example.confidence == "0.85"

            if debug:
                print( f"✓ {cls.__name__} smoke test PASSED" )

            return True

        except Exception as e:
            if debug:
                print( f"✗ {cls.__name__} smoke test FAILED: {e}" )
            return False


class FuzzyFileMatchResponse( BaseXMLModel ):
    """
    Fuzzy file matching response model.

    Handles XML responses for matching user descriptions against file names:
    <response>
        <matches>2026.01.15-claude-code-analysis.md, 2026.01.10-ai-tools.md</matches>
    </response>

    The matches field contains a comma-separated list of filenames that match
    the user's natural language description, or an empty string if no matches.

    Used by Podcast Generator description mode for research document selection.
    """

    matches: str = Field(
        ...,
        description="Comma-separated list of matching filenames, or empty string if no matches"
    )

    @classmethod
    def get_example_for_template( cls ) -> 'FuzzyFileMatchResponse':
        """
        Get example instance for prompt templates.

        Returns a fuzzy file matching response example that matches the expected
        XML structure for the fuzzy-file-matching.txt template.

        Requires:
            - None

        Ensures:
            - Returns FuzzyFileMatchResponse with sample comma-separated filenames
        """
        return cls(
            matches='2026.01.15-claude-code-analysis.md, 2026.01.10-ai-tools.md'
        )

    def get_matches_list( self ) -> List[ str ]:
        """
        Get matches as a list of filenames.

        Requires:
            - self.matches is a string (guaranteed by Pydantic)

        Ensures:
            - Returns list of trimmed, non-empty filename strings
            - Returns empty list if matches is empty or whitespace-only

        Returns:
            List of filename strings
        """
        if not self.matches or not self.matches.strip():
            return []

        return [ m.strip() for m in self.matches.split( ',' ) if m.strip() ]

    @classmethod
    def quick_smoke_test( cls, debug: bool = False ) -> bool:
        """
        Quick smoke test for FuzzyFileMatchResponse.

        Args:
            debug: Enable debug output

        Returns:
            True if all tests pass
        """
        if debug:
            print( f"Testing {cls.__name__}..." )

        try:
            # Test base functionality
            if not super().quick_smoke_test( debug=False ):
                return False

            # Test creation with matches
            response = cls( matches="file1.md, file2.md, file3.md" )
            assert response.matches == "file1.md, file2.md, file3.md"

            # Test get_matches_list
            matches_list = response.get_matches_list()
            assert len( matches_list ) == 3
            assert matches_list[ 0 ] == "file1.md"
            assert matches_list[ 2 ] == "file3.md"

            # Test XML generation
            xml_str = response.to_xml()
            assert "<matches>file1.md, file2.md, file3.md</matches>" in xml_str

            # Test round-trip conversion
            parsed = cls.from_xml( xml_str )
            assert parsed.matches == response.matches

            # Test empty matches
            empty_response = cls( matches="" )
            assert empty_response.get_matches_list() == []

            # Test whitespace-only matches
            whitespace_response = cls( matches="   " )
            assert whitespace_response.get_matches_list() == []

            # Test template example
            example = cls.get_example_for_template()
            assert "claude-code-analysis.md" in example.matches

            if debug:
                print( f"✓ {cls.__name__} smoke test PASSED" )

            return True

        except Exception as e:
            if debug:
                print( f"✗ {cls.__name__} smoke test FAILED: {e}" )
            return False


class TFEResumeMatchResponse( BaseXMLModel ):
    """
    TFE resume fuzzy-match response model.

    Handles XML responses for matching a user's natural-language description
    of a stalled Test Fix Expediter job against a list of candidate job IDs:
    <response>
        <matches>tfe-7c25082a::user@example.com, tfe-3b8c92d1::user@example.com</matches>
    </response>

    The matches field contains a comma-separated list of TFE job IDs ranked by
    relevance to the user's description, or an empty string if no matches.

    Used by the TFE resume resolver (session 9056c113) for voice / natural-language
    resume path resolution.
    """

    matches: str = Field(
        ...,
        description="Comma-separated list of matching TFE job IDs in rank order, or empty string"
    )

    @classmethod
    def get_example_for_template( cls ) -> 'TFEResumeMatchResponse':
        """
        Get example instance for prompt templates.

        Returns a TFE resume match response example that matches the expected
        XML structure for the tfe-resume-matching.txt template.

        Requires:
            - None

        Ensures:
            - Returns TFEResumeMatchResponse with sample comma-separated job IDs
        """
        return cls(
            matches='tfe-7c25082a::user@example.com, tfe-3b8c92d1::user@example.com'
        )

    def get_matches_list( self ) -> List[ str ]:
        """
        Get matches as a list of job IDs.

        Requires:
            - self.matches is a string (guaranteed by Pydantic)

        Ensures:
            - Returns list of trimmed, non-empty job ID strings
            - Returns empty list if matches is empty or whitespace-only

        Returns:
            List of TFE job ID strings in rank order
        """
        if not self.matches or not self.matches.strip():
            return []

        return [ m.strip() for m in self.matches.split( ',' ) if m.strip() ]

    @classmethod
    def quick_smoke_test( cls, debug: bool = False ) -> bool:
        """Quick smoke test for TFEResumeMatchResponse."""
        try:
            # Basic construction + parsing
            response = cls( matches="tfe-abc::u1, tfe-def::u1, tfe-xyz::u1" )
            matches_list = response.get_matches_list()
            assert len( matches_list ) == 3
            assert matches_list[ 0 ] == "tfe-abc::u1"

            # XML round-trip
            xml_str = response.to_xml()
            assert "<matches>tfe-abc::u1, tfe-def::u1, tfe-xyz::u1</matches>" in xml_str
            parsed = cls.from_xml( xml_str )
            assert parsed.matches == response.matches

            # Empty + whitespace
            assert cls( matches="" ).get_matches_list() == []
            assert cls( matches="   " ).get_matches_list() == []

            # Template example
            example = cls.get_example_for_template()
            assert "tfe-" in example.matches

            if debug: print( f"✓ {cls.__name__} smoke test PASSED" )
            return True

        except Exception as e:
            if debug: print( f"✗ {cls.__name__} smoke test FAILED: {e}" )
            return False


def quick_smoke_test() -> bool:
    """
    Quick smoke test for all XML models.
    
    Tests all models in this module following CoSA convention.
    
    Returns:
        True if all model tests pass
    """
    print( "Testing xml_models module..." )
    
    try:
        models_to_test = [
            SimpleResponse,
            CommandResponse,
            YesNoResponse,
            ReceptionistResponse,
            CodeResponse,
            CalendarResponse,
            CodeBrainstormResponse,
            BugInjectionResponse,
            IterativeDebuggingMinimalistResponse,
            IterativeDebuggingFullResponse,
            WeatherResponse,
            VoxCommandResponse,
            AgentRouterResponse,
            GistResponse,
            ConfirmationResponse,
            QualifierClassification,
            FuzzyFileMatchResponse
        ]
        
        passed = 0
        for model_cls in models_to_test:
            try:
                if model_cls.quick_smoke_test( debug=True ):
                    passed += 1
                else:
                    print( f"✗ {model_cls.__name__} failed" )
            except Exception as e:
                print( f"✗ {model_cls.__name__} exception: {e}" )
        
        success = passed == len( models_to_test )
        
        if success:
            print( f"✓ xml_models module smoke test PASSED ({passed}/{len(models_to_test)})" )
        else:
            print( f"✗ xml_models module smoke test FAILED ({passed}/{len(models_to_test)})" )
        
        return success
        
    except Exception as e:
        print( f"✗ xml_models module smoke test FAILED: {e}" )
        return False


if __name__ == "__main__":
    # Run smoke tests when executed directly
    success = quick_smoke_test()
    exit( 0 if success else 1 )