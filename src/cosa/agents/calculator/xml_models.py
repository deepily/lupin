#!/usr/bin/env python3
"""
XML response model for Calculator intent extraction.

Defines CalcIntent as a BaseXMLModel subclass for LLM-extracted calculation
operations. All fields are strings (LLM I/O convention).

Pattern follows CRUDIntent in cosa.crud_for_dataframes.xml_models.
"""

import json
from typing import ClassVar, List

from pydantic import Field, field_validator

from cosa.agents.io_models.utils.util_xml_pydantic import BaseXMLModel


class CalcIntent( BaseXMLModel ):
    """
    Calculator intent extracted from natural language by LLM.

    Handles XML responses for calculator operations:
    <calc_intent>
        <operation>convert</operation>
        <value>10</value>
        <value_2></value_2>
        <from_unit>kilometers</from_unit>
        <to_unit>miles</to_unit>
        <items></items>
        <principal></principal>
        <annual_rate></annual_rate>
        <term_years></term_years>
        <down_payment></down_payment>
        <confidence>0.95</confidence>
        <raw_query>how many miles is 10 kilometers</raw_query>
    </calc_intent>

    Fields (all str per BaseXMLModel convention — LLM I/O is always text):
        operation: Calculation type (convert, compare_prices, mortgage)
        value: Primary numeric value (amount to convert)
        value_2: Secondary numeric value (unused currently, reserved)
        from_unit: Source unit for conversion
        to_unit: Target unit for conversion
        items: JSON array of {name, price, quantity, unit} for price comparison
        principal: Loan amount for mortgage
        annual_rate: Interest rate (%) for mortgage
        term_years: Loan term in years for mortgage
        down_payment: Down payment amount for mortgage
        confidence: Float-as-string confidence score (0.0-1.0)
        raw_query: Original natural language query
    """

    operation   : str = Field( ..., description="Calculation type: convert, compare_prices, mortgage, unsupported" )
    value       : str = Field( default="", description="Primary numeric value" )
    value_2     : str = Field( default="", description="Secondary numeric value (reserved)" )
    from_unit   : str = Field( default="", description="Source unit for conversion" )
    to_unit     : str = Field( default="", description="Target unit for conversion" )
    items       : str = Field( default="", description="JSON array of {name, price, quantity, unit} for price comparison" )
    principal   : str = Field( default="", description="Loan amount for mortgage" )
    annual_rate : str = Field( default="", description="Interest rate (%) for mortgage" )
    term_years  : str = Field( default="", description="Loan term in years for mortgage" )
    down_payment: str = Field( default="", description="Down payment amount for mortgage" )
    confidence  : str = Field( default="0.0", description="Confidence score as string (0.0-1.0)" )
    raw_query   : str = Field( default="", description="Original natural language query" )

    @field_validator( "*", mode="before" )
    @classmethod
    def _coerce_none_to_empty_string( cls, v, info ):
        """
        Coerce None values to empty strings.

        xmltodict returns None for empty XML tags like <value_2></value_2>.
        Pydantic str fields reject None, so we convert at the boundary.
        """
        if v is None and info.field_name != "operation":
            return ""
        return v

    # Valid operations (ClassVar to avoid Pydantic treating as fields)
    VALID_OPERATIONS: ClassVar[ List[ str ] ] = [
        "convert", "compare_prices", "mortgage", "unsupported"
    ]

    def get_confidence_float( self ):
        """
        Parse confidence string to float.

        Requires:
            - self.confidence is a numeric string

        Ensures:
            - Returns float between 0.0 and 1.0
            - Returns 0.0 if parsing fails
        """
        try:
            return max( 0.0, min( 1.0, float( self.confidence ) ) )
        except ( ValueError, TypeError ):
            return 0.0

    def get_value_float( self ):
        """
        Parse value string to float.

        Requires:
            - self.value is a numeric string

        Ensures:
            - Returns float value
            - Returns 0.0 if parsing fails
        """
        try:
            return float( self.value )
        except ( ValueError, TypeError ):
            return 0.0

    def get_items_list( self ):
        """
        Parse items JSON string to list of dicts.

        Requires:
            - self.items is a JSON array string or empty

        Ensures:
            - Returns list of {name, price, quantity, unit} dicts
            - Returns empty list if parsing fails or empty
        """
        if not self.items or not self.items.strip() or self.items.strip() == "[]":
            return []
        try:
            parsed = json.loads( self.items )
            return parsed if isinstance( parsed, list ) else []
        except ( json.JSONDecodeError, TypeError ):
            return []

    def get_principal_float( self ):
        """
        Parse principal string to float.

        Requires:
            - self.principal is a numeric string

        Ensures:
            - Returns float value
            - Returns 0.0 if parsing fails
        """
        try:
            return float( self.principal )
        except ( ValueError, TypeError ):
            return 0.0

    def get_annual_rate_float( self ):
        """
        Parse annual_rate string to float.

        Requires:
            - self.annual_rate is a numeric string (percentage)

        Ensures:
            - Returns float value (as percentage, e.g. 6.5)
            - Returns 0.0 if parsing fails
        """
        try:
            return float( self.annual_rate )
        except ( ValueError, TypeError ):
            return 0.0

    def get_term_years_int( self ):
        """
        Parse term_years string to integer.

        Requires:
            - self.term_years is a numeric string

        Ensures:
            - Returns positive integer
            - Returns 0 if parsing fails
        """
        try:
            val = int( float( self.term_years ) )
            return val if val > 0 else 0
        except ( ValueError, TypeError ):
            return 0

    def get_down_payment_float( self ):
        """
        Parse down_payment string to float.

        Requires:
            - self.down_payment is a numeric string

        Ensures:
            - Returns float value
            - Returns 0.0 if parsing fails or empty
        """
        if not self.down_payment or not self.down_payment.strip():
            return 0.0
        try:
            return float( self.down_payment )
        except ( ValueError, TypeError ):
            return 0.0

    def to_xml( self, root_tag="calc_intent", pretty=True ):
        """
        Serialize CalcIntent to XML with <calc_intent> as default root tag.

        Requires:
            - root_tag is a non-empty string

        Ensures:
            - Returns XML string with specified root tag (default: "calc_intent")
        """
        return super().to_xml( root_tag=root_tag, pretty=pretty )

    @classmethod
    def get_example_for_template( cls ):
        """
        Get example instance with generic placeholder values for prompt templates.

        Returns a CalcIntent with "serving suggestion" placeholders so the LLM
        sees the XML structure without interpreting concrete data as the answer.

        Requires:
            - None

        Ensures:
            - Returns CalcIntent with generic placeholder values
            - Placeholders are descriptive but clearly not real data
        """
        return cls(
            operation    = "[operation: convert, compare_prices, mortgage, or unsupported]",
            value        = "[numeric value to convert]",
            value_2      = "[secondary value if needed]",
            from_unit    = "[source unit name]",
            to_unit      = "[target unit name]",
            items        = "[JSON array of items with name, price, quantity, unit fields for price comparison]",
            principal    = "[loan amount for mortgage]",
            annual_rate  = "[annual interest rate as percentage for mortgage]",
            term_years   = "[loan term in years for mortgage]",
            down_payment = "[down payment amount for mortgage]",
            confidence   = "[confidence score between 0.0 and 1.0]",
            raw_query    = "[original user query exactly as spoken]"
        )

    @classmethod
    def quick_smoke_test( cls, debug=False ):
        """
        Quick smoke test for CalcIntent.

        Requires:
            - None

        Ensures:
            - Returns True if all tests pass, False otherwise
        """
        if debug: print( f"Testing {cls.__name__}..." )

        try:
            # Test base functionality
            if not super().quick_smoke_test( debug=False ):
                return False

            # Test creation with all fields (generic placeholders)
            intent = cls.get_example_for_template()
            assert intent.operation.startswith( "[operation" )
            if debug: print( "  ✓ Creation with all fields (generic placeholders)" )

            # Test confidence parsing (placeholder is non-numeric, returns 0.0)
            assert intent.get_confidence_float() == 0.0
            if debug: print( "  ✓ Confidence parsing (placeholder)" )

            # Test value parsing
            convert_intent = cls( operation="convert", value="10", from_unit="km", to_unit="miles" )
            assert convert_intent.get_value_float() == 10.0
            if debug: print( "  ✓ Value parsing" )

            # Test items parsing
            items_json = '[{"name": "Brand A", "price": 3.49, "quantity": 12, "unit": "oz"}]'
            price_intent = cls( operation="compare_prices", items=items_json )
            items_list = price_intent.get_items_list()
            assert len( items_list ) == 1
            assert items_list[ 0 ][ "name" ] == "Brand A"
            if debug: print( "  ✓ Items JSON parsing" )

            # Test mortgage field parsing
            mortgage_intent = cls(
                operation="mortgage", principal="300000", annual_rate="6.5",
                term_years="30", down_payment="50000"
            )
            assert mortgage_intent.get_principal_float() == 300000.0
            assert mortgage_intent.get_annual_rate_float() == 6.5
            assert mortgage_intent.get_term_years_int() == 30
            assert mortgage_intent.get_down_payment_float() == 50000.0
            if debug: print( "  ✓ Mortgage field parsing" )

            # Test None coercion
            none_intent = cls( operation="convert", value=None, from_unit=None )
            assert none_intent.value == ""
            assert none_intent.from_unit == ""
            if debug: print( "  ✓ None coercion to empty string" )

            # Test XML round-trip
            xml_str = convert_intent.to_xml()
            assert "<operation>convert</operation>" in xml_str
            parsed = cls.from_xml( xml_str, root_tag="calc_intent" )
            assert parsed.operation == "convert"
            assert parsed.value == "10"
            assert parsed.from_unit == "km"
            if debug: print( "  ✓ XML round-trip" )

            # Test unsupported operation XML round-trip
            unsupported_intent = cls( operation="unsupported", confidence="0.95", raw_query="What is 2 plus 2?" )
            assert unsupported_intent.operation == "unsupported"
            xml_str = unsupported_intent.to_xml()
            assert "<operation>unsupported</operation>" in xml_str
            parsed = cls.from_xml( xml_str, root_tag="calc_intent" )
            assert parsed.operation == "unsupported"
            assert parsed.confidence == "0.95"
            assert parsed.raw_query == "What is 2 plus 2?"
            if debug: print( "  ✓ Unsupported operation XML round-trip" )

            if debug: print( f"✓ {cls.__name__} smoke test PASSED" )
            return True

        except Exception as e:
            if debug: print( f"✗ {cls.__name__} smoke test FAILED: {e}" )
            import traceback
            traceback.print_exc()
            return False


def quick_smoke_test():
    """Module-level smoke test following CoSA convention."""
    return CalcIntent.quick_smoke_test( debug=True )


if __name__ == "__main__":
    success = quick_smoke_test()
    exit( 0 if success else 1 )
