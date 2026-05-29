#!/usr/bin/env python3
"""
XML response model for open-ended prediction synthesis.

Defines OpenEndedSynthesisResponse as a BaseXMLModel subclass for LLM-synthesized
open-ended predictions. All fields are strings (LLM I/O convention).

Pattern follows CalcIntent in cosa.agents.calculator.xml_models.
"""

from pydantic import Field, field_validator

from cosa.agents.io_models.utils.util_xml_pydantic import BaseXMLModel


class OpenEndedSynthesisResponse( BaseXMLModel ):
    """
    LLM-synthesized prediction for open-ended notification responses.

    Handles XML responses for prediction synthesis:
    <open_ended_synthesis_response>
        <predicted_answer>The synthesized prediction text</predicted_answer>
        <reasoning>Brief explanation of synthesis logic</reasoning>
        <confidence>0.85</confidence>
    </open_ended_synthesis_response>

    Fields (all str per BaseXMLModel convention — LLM I/O is always text):
        predicted_answer: Synthesized prediction of user's response
        reasoning: Brief explanation of synthesis logic
        confidence: Float-as-string confidence score (0.0-1.0)
    """

    predicted_answer : str = Field( ..., description="Synthesized prediction of user's response" )
    reasoning        : str = Field( default="", description="Brief explanation of synthesis logic" )
    confidence       : str = Field( default="0.0", description="Confidence score 0.0-1.0 as string" )

    @field_validator( "*", mode="before" )
    @classmethod
    def _coerce_none_to_empty_string( cls, v, info ):
        """
        Coerce None values to empty strings.

        xmltodict returns None for empty XML tags like <reasoning></reasoning>.
        Pydantic str fields reject None, so we convert at the boundary.
        """
        if v is None and info.field_name != "predicted_answer":
            return ""
        return v

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

    def to_xml( self, root_tag="open_ended_synthesis_response", pretty=True ):
        """
        Serialize to XML with default root tag.

        Requires:
            - root_tag is a non-empty string

        Ensures:
            - Returns XML string with specified root tag
        """
        return super().to_xml( root_tag=root_tag, pretty=pretty )

    @classmethod
    def get_example_for_template( cls ):
        """
        Get example instance with placeholder values for prompt templates.

        Requires:
            - None

        Ensures:
            - Returns instance with descriptive placeholder values
        """
        return cls(
            predicted_answer = "[your synthesized prediction of the user's most likely response]",
            reasoning        = "[brief explanation of why you predicted this answer based on the patterns in past cases]",
            confidence       = "[confidence score between 0.0 and 1.0]"
        )

    @classmethod
    def quick_smoke_test( cls, debug=False ):
        """
        Quick smoke test for OpenEndedSynthesisResponse.

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

            # Test creation with placeholder values
            example = cls.get_example_for_template()
            assert example.predicted_answer.startswith( "[your" )
            if debug: print( "  ✓ Creation with placeholder values" )

            # Test confidence parsing (placeholder is non-numeric, returns 0.0)
            assert example.get_confidence_float() == 0.0
            if debug: print( "  ✓ Confidence parsing (placeholder)" )

            # Test real confidence
            real = cls(
                predicted_answer = "yes, proceed",
                reasoning        = "consistent pattern",
                confidence       = "0.85"
            )
            assert real.get_confidence_float() == 0.85
            if debug: print( "  ✓ Confidence parsing (real value)" )

            # Test None coercion
            none_resp = cls( predicted_answer="test", reasoning=None, confidence=None )
            assert none_resp.reasoning == ""
            assert none_resp.confidence == ""
            if debug: print( "  ✓ None coercion to empty string" )

            # Test XML round-trip
            xml_str = real.to_xml()
            assert "<predicted_answer>yes, proceed</predicted_answer>" in xml_str
            parsed = cls.from_xml( xml_str, root_tag="open_ended_synthesis_response" )
            assert parsed.predicted_answer == "yes, proceed"
            assert parsed.reasoning == "consistent pattern"
            assert parsed.confidence == "0.85"
            if debug: print( "  ✓ XML round-trip" )

            if debug: print( f"✓ {cls.__name__} smoke test PASSED" )
            return True

        except Exception as e:
            if debug: print( f"✗ {cls.__name__} smoke test FAILED: {e}" )
            import traceback
            traceback.print_exc()
            return False


def quick_smoke_test():
    """Module-level smoke test following CoSA convention."""
    return OpenEndedSynthesisResponse.quick_smoke_test( debug=True )


if __name__ == "__main__":
    success = quick_smoke_test()
    exit( 0 if success else 1 )
