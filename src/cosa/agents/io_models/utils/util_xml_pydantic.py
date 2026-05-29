#!/usr/bin/env python3
"""
Pydantic XML Utilities

Base classes and utilities for XML serialization and deserialization
using Pydantic models with xmltodict integration. Provides a clean API
for converting between XML strings and validated Python objects.

This module provides:
- BaseXMLModel: Base class for all XML-serializable Pydantic models
- XML parsing and generation utilities
- Error handling and validation
- Integration with existing CoSA XML patterns
"""

import json
import re
import time
from typing import TypeVar, Type, Dict, Any, Optional, Union, List
from pydantic import BaseModel, Field, ValidationError, ConfigDict

try:
    import xmltodict
except ImportError:
    raise ImportError( "xmltodict is required. Install with: pip install xmltodict" )

import cosa.utils.util as du

# Type variable for BaseXMLModel subclasses
T = TypeVar( 'T', bound='BaseXMLModel' )


def remove_xml_escapes( xml_string: str ) -> str:
    """
    Remove common XML escape sequences from a string.

    This is a utility function for unescaping XML entities, not for parsing XML.

    Requires:
        - xml_string is a string that may contain XML escapes

    Ensures:
        - Returns string with XML escapes replaced:
          - &gt; becomes >
          - &lt; becomes <
          - &amp; becomes &
        - Order of replacements prevents double-unescaping
    """
    return xml_string.replace( "&gt;", ">" ).replace( "&lt;", "<" ).replace( "&amp;", "&" )


class XMLParsingError( Exception ):
    """
    Custom exception for XML parsing errors.
    
    Raised when XML cannot be parsed or converted to Pydantic models.
    Provides more context than generic parsing errors.
    """
    
    def __init__( self, message: str, xml_content: Optional[str] = None, original_error: Optional[Exception] = None ):
        """
        Initialize XML parsing error.
        
        Args:
            message: Human-readable error description
            xml_content: The XML content that failed to parse (truncated if long)
            original_error: The underlying exception that caused this error
        """
        self.xml_content = xml_content[:200] + "..." if xml_content and len( xml_content ) > 200 else xml_content
        self.original_error = original_error
        
        full_message = message
        if self.xml_content:
            full_message += f" | XML: {self.xml_content}"
        if self.original_error:
            full_message += f" | Cause: {self.original_error}"
        
        super().__init__( full_message )


class BaseXMLModel( BaseModel ):
    """
    Base class for all XML-serializable Pydantic models.
    
    Provides bidirectional XML conversion using xmltodict while maintaining
    full Pydantic validation and type checking. Compatible with existing
    CoSA XML patterns and util_xml.py behavior.
    
    Key Features:
    - .from_xml() class method for parsing XML strings
    - .to_xml() instance method for generating XML strings
    - Full Pydantic validation and type checking
    - Error handling with meaningful messages
    - Compatibility with CoSA XML patterns
    - Built-in quick_smoke_test() for validation
    
    Usage:
        class MyResponse(BaseXMLModel):
            field1: str
            field2: Optional[int] = None
        
        # Parse XML
        obj = MyResponse.from_xml("<response><field1>value</field1></response>")
        
        # Generate XML
        xml_string = obj.to_xml()
    """
    
    # Pydantic v2 configuration
    model_config = ConfigDict(
        # Allow population by field name or alias
        populate_by_name=True,
        # Validate assignment to prevent invalid data after creation
        validate_assignment=True,
        # Use enum values instead of names
        use_enum_values=True,
        # Allow arbitrary user types (needed for some CoSA patterns)
        arbitrary_types_allowed=True,
        # Allow extra fields for flexibility during migration
        extra="allow"
    )

    @classmethod
    def from_xml( cls: Type[T], xml_string: str, root_tag: Optional[str] = None ) -> T:
        """
        Parse XML string into Pydantic model instance.
        
        Converts XML to dictionary using xmltodict, then validates and
        constructs the Pydantic model. Handles nested structures and
        maintains compatibility with existing CoSA XML patterns.
        
        Args:
            xml_string: The XML string to parse
            root_tag: Optional root tag to extract (default: 'response')
            
        Returns:
            Validated Pydantic model instance
            
        Raises:
            XMLParsingError: If XML parsing or validation fails
            ValidationError: If data doesn't match model schema
            
        Example:
            xml = "<response><command>math</command><args>2+2</args></response>"
            response = CommandResponse.from_xml(xml)
        """
        if not xml_string or not xml_string.strip():
            raise XMLParsingError( "XML string is empty or whitespace" )

        # Strip any prefix before XML declaration or root tag
        # LLMs sometimes output text like "Output" or "Here is the response:" before XML
        xml_cleaned = xml_string.strip()
        xml_start = -1

        # Look for XML declaration first
        decl_pos = xml_cleaned.find( '<?xml' )
        if decl_pos > 0:
            xml_start = decl_pos
            print( f"[XML-PARSER] WARNING: Stripping {decl_pos} chars before XML declaration: '{xml_cleaned[:min( decl_pos, 50 )]}...'" )

        # If no declaration, look for common root tags
        if xml_start < 0:
            for tag in [ '<response>', '<response ', '<result>', '<result ', '<output>', '<output ' ]:
                tag_pos = xml_cleaned.find( tag )
                if tag_pos > 0:
                    xml_start = tag_pos
                    print( f"[XML-PARSER] WARNING: Stripping {tag_pos} chars before root tag: '{xml_cleaned[:min( tag_pos, 50 )]}...'" )
                    break

        # Apply the fix if we found a prefix to strip
        if xml_start > 0:
            xml_cleaned = xml_cleaned[xml_start:]

        # Strip any suffix after closing root tag
        # LLMs sometimes echo prompt content or continue generating after valid XML
        # Use find() not rfind() - we want the FIRST closing tag (the actual XML),
        # not a later mention of "</response>" in explanation text
        for closing_tag in [ '</response>', '</result>', '</output>' ]:
            closing_pos = xml_cleaned.find( closing_tag )  # find = first occurrence
            if closing_pos > 0:
                end_pos = closing_pos + len( closing_tag )
                if end_pos < len( xml_cleaned ):
                    suffix_len = len( xml_cleaned ) - end_pos
                    suffix_preview = xml_cleaned[ end_pos : end_pos + 50 ].replace( '\n', '\\n' )
                    print( f"[XML-PARSER] WARNING: Stripping {suffix_len} chars after closing tag: '{suffix_preview}...'" )
                    xml_cleaned = xml_cleaned[ :end_pos ]
                break

        # Escape bare & that aren't already part of XML entities.
        # LLMs write content like "Q&A" which is invalid XML (bare ampersand).
        # This safely converts "Q&A" → "Q&amp;A" without double-escaping
        # existing entities like &amp; &lt; &gt; &quot; &apos; or &#NNN;
        xml_cleaned = re.sub( r'&(?!amp;|lt;|gt;|quot;|apos;|#)', '&amp;', xml_cleaned )

        try:
            # Parse XML to dictionary
            # Preserve whitespace in XML text content to maintain code indentation
            # See: https://github.com/deepily/lupin/issues/5 - Math Agent code generation fails due to stripped indentation
            xml_dict = xmltodict.parse( xml_cleaned, strip_whitespace=False )
            
            # Extract data based on root tag
            if root_tag is None:
                root_tag = 'response'  # Default CoSA pattern
            
            if root_tag in xml_dict:
                model_data = xml_dict[root_tag]
            elif len( xml_dict ) == 1:
                # Single root element - use it regardless of name
                model_data = list( xml_dict.values() )[0]
            else:
                # Multiple root elements or no response wrapper
                model_data = xml_dict
            
            # Handle case where model_data is None (empty tags)
            if model_data is None:
                model_data = {}
            
            # Convert to model instance with validation
            return cls( **model_data )
            
        except xmltodict.expat.ExpatError as e:
            raise XMLParsingError( 
                f"Invalid XML format: {str(e)}", 
                xml_content=xml_string,
                original_error=e 
            )
        except ValidationError as e:
            raise XMLParsingError(
                f"Data validation failed: {str(e)}",
                xml_content=xml_string,
                original_error=e
            )
        except Exception as e:
            raise XMLParsingError(
                f"Unexpected error parsing XML: {str(e)}",
                xml_content=xml_string,
                original_error=e
            )

    def to_xml( self, root_tag: str = 'response', pretty: bool = True ) -> str:
        """
        Serialize Pydantic model to XML string.
        
        Converts the model to a dictionary using Pydantic's dict() method,
        then generates XML using xmltodict.unparse(). Maintains compatibility
        with CoSA XML patterns.
        
        Args:
            root_tag: Root XML element name (default: 'response')
            pretty: Whether to format XML with indentation (default: True)
            
        Returns:
            Formatted XML string
            
        Example:
            response = CommandResponse(command="math", args="2+2")
            xml = response.to_xml()
            # Result: <response><command>math</command><args>2+2</args></response>
        """
        try:
            # Get model data as dictionary, excluding None values
            model_dict = self.model_dump( exclude_none=True )
            
            # Wrap in root tag
            data_dict = { root_tag: model_dict }
            
            # Generate XML
            xml_string = xmltodict.unparse( data_dict, pretty=pretty )
            
            return xml_string
            
        except Exception as e:
            raise XMLParsingError(
                f"Failed to serialize model to XML: {str(e)}",
                original_error=e
            )

    @classmethod
    def quick_smoke_test( cls: Type[T], debug: bool = False ) -> bool:
        """
        Quick smoke test for XML model validation.
        
        Tests basic XML parsing and serialization functionality using
        sample data. Follows CoSA convention for component self-testing.
        
        Args:
            debug: Enable debug output
            
        Returns:
            True if smoke test passes, False otherwise
            
        Note:
            Subclasses should override this method with model-specific tests
            but should call super().quick_smoke_test() for base functionality.
        """
        if debug:
            print( f"Testing {cls.__name__}..." )
        
        try:
            # Test basic serialization (empty model)
            if debug:
                print( "  - Testing empty model serialization..." )
            
            # Create empty instance (if possible)
            try:
                empty_instance = cls()
                xml_output = empty_instance.to_xml()
                assert xml_output is not None, "XML output should not be None"
                if debug:
                    print( f"    ✓ Empty serialization: {xml_output[:50]}..." )
            except ValidationError:
                # Some models might not allow empty construction
                if debug:
                    print( "    ○ Empty model not supported (OK)" )
            
            # Test round-trip with basic XML - only for base class
            if debug:
                print( "  - Testing basic round-trip..." )
            
            if cls.__name__ == "BaseXMLModel":
                # BaseModel allows extra fields, so this should work
                basic_xml = f"<response><test_field>test_value</test_field></response>"
                try:
                    parsed = cls.from_xml( basic_xml )
                    regenerated_xml = parsed.to_xml()
                    if debug:
                        print( f"    ✓ Basic round-trip successful: {regenerated_xml[:50]}..." )
                except (ValidationError, XMLParsingError) as e:
                    if debug:
                        print( f"    ○ Basic round-trip failed (expected): {e}" )
            else:
                # For subclasses, skip this test as they have specific fields
                if debug:
                    print( "    ○ Basic round-trip skipped for subclass (OK)" )
            
            # Test error handling
            if debug:
                print( "  - Testing error handling..." )
            
            try:
                cls.from_xml( "invalid xml content" )
                if debug:
                    print( "    ✗ Should have raised XMLParsingError" )
                return False
            except XMLParsingError:
                if debug:
                    print( "    ✓ Error handling works" )
            
            if debug:
                print( f"✓ {cls.__name__} smoke test PASSED" )
            
            return True
            
        except Exception as e:
            if debug:
                print( f"✗ {cls.__name__} smoke test FAILED: {e}" )
            return False

    def __str__( self ) -> str:
        """String representation showing XML format."""
        try:
            return self.to_xml( pretty=False )
        except Exception:
            return super().__str__()

    def __repr__( self ) -> str:
        """Developer-friendly representation."""
        return f"{self.__class__.__name__}({dict(self)})"


class XMLUtilities:
    """
    Utility functions for XML processing with Pydantic models.
    
    Provides helper functions for common XML operations and compatibility
    with existing CoSA util_xml.py patterns.
    """
    
    @staticmethod
    def validate_xml_structure( xml_string: str, required_tags: Optional[List[str]] = None ) -> Dict[str, Any]:
        """
        Validate XML structure and return analysis.
        
        Args:
            xml_string: XML content to validate
            required_tags: Optional list of required tag names
            
        Returns:
            Dictionary with validation results and structure analysis
        """
        try:
            xml_dict = xmltodict.parse( xml_string )
            
            analysis = {
                "valid_xml": True,
                "root_tags": list( xml_dict.keys() ),
                "has_response_wrapper": "response" in xml_dict,
                "structure": xml_dict
            }
            
            if required_tags:
                missing_tags = []
                data = xml_dict.get( "response", xml_dict )
                
                for tag in required_tags:
                    if tag not in data:
                        missing_tags.append( tag )
                
                analysis["required_tags_present"] = len( missing_tags ) == 0
                analysis["missing_tags"] = missing_tags
            
            return analysis
            
        except Exception as e:
            return {
                "valid_xml": False,
                "error": str( e ),
                "structure": None
            }

    @staticmethod
    def compare_with_baseline( pydantic_result: Any, baseline_result: str, debug: bool = False ) -> Dict[str, Any]:
        """
        Compare Pydantic parsing result with baseline util_xml.py result.
        
        Used during migration to ensure compatibility.
        
        Args:
            pydantic_result: Result from Pydantic model
            baseline_result: Result from util_xml.py function
            debug: Enable debug output
            
        Returns:
            Comparison analysis dictionary
        """
        comparison = {
            "pydantic_type": type( pydantic_result ).__name__,
            "baseline_type": type( baseline_result ).__name__,
            "values_match": str( pydantic_result ) == str( baseline_result ),
            "pydantic_value": str( pydantic_result ),
            "baseline_value": str( baseline_result )
        }
        
        if debug:
            if comparison["values_match"]:
                print( f"✓ Values match: {comparison['pydantic_value']}" )
            else:
                print( f"✗ Values differ:" )
                print( f"  Pydantic: {comparison['pydantic_value']}" )
                print( f"  Baseline: {comparison['baseline_value']}" )
        
        return comparison


def quick_smoke_test() -> bool:
    """
    Quick smoke test for the entire util_xml_pydantic module.
    
    Tests BaseXMLModel functionality and utilities.
    Follows CoSA convention for module-level testing.
    
    Returns:
        True if all tests pass
    """
    print( "Testing util_xml_pydantic module..." )
    
    try:
        # Test BaseXMLModel directly
        result = BaseXMLModel.quick_smoke_test( debug=True )
        
        if result:
            print( "✓ util_xml_pydantic module smoke test PASSED" )
        else:
            print( "✗ util_xml_pydantic module smoke test FAILED" )
        
        return result
        
    except Exception as e:
        print( f"✗ util_xml_pydantic module smoke test FAILED: {e}" )
        return False


if __name__ == "__main__":
    # Run smoke test when executed directly
    success = quick_smoke_test()
    exit( 0 if success else 1 )