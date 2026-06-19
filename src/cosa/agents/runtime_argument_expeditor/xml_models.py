#!/usr/bin/env python3
"""
XML response model for Runtime Argument Expeditor.

Defines ExpeditorResponse for LLM gap analysis of user-provided arguments
against an agent's required CLI arguments. The LLM determines which args
are present and which are missing; the static registry provides deterministic
fallback questions.
"""

from typing import List
from pydantic import Field, field_validator

from cosa.agents.io_models.utils.util_xml_pydantic import BaseXMLModel


class ExpeditorResponse( BaseXMLModel ):
    """
    Runtime argument expeditor response model.

    Handles XML responses for argument gap analysis:
    <response>
        <all_required_met>false</all_required_met>
        <args_present>query=biodiversity loss</args_present>
        <args_missing>budget</args_missing>
    </response>

    Fields:
        all_required_met: "true" or "false" indicating if all required args are satisfied
        args_present: Comma-separated key=value pairs for arguments found in user input
        args_missing: Comma-separated list of missing required argument names
    """

    all_required_met: str = Field(
        ...,
        description="'true' if all required user-facing arguments are present, 'false' otherwise"
    )

    args_present: str = Field(
        ...,
        description="Comma-separated key=value pairs of arguments found in the user's input"
    )

    args_missing: str = Field(
        ...,
        description="Comma-separated list of missing required argument names, or empty string if none"
    )

    @field_validator( "*", mode="before" )
    @classmethod
    def coerce_none_to_empty_str( cls, v ):
        """Coerce None (from empty XML tags like <foo></foo>) to empty string."""
        if v is None:
            return ""
        return v

    def is_complete( self ):
        """
        Check if all required arguments are met.

        Requires:
            - self.all_required_met is a string

        Ensures:
            - Returns True if all_required_met is "true" (case-insensitive)
            - Returns False otherwise

        Returns:
            bool: Whether all required arguments are satisfied
        """
        return self.all_required_met.strip().lower() == "true"

    def get_missing_list( self ):
        """
        Get missing arguments as a list.

        Requires:
            - self.args_missing is a string

        Ensures:
            - Returns list of trimmed, non-empty argument names
            - Returns empty list if args_missing is empty or whitespace-only

        Returns:
            List of missing argument name strings
        """
        if not self.args_missing or not self.args_missing.strip():
            return []

        return [ m.strip() for m in self.args_missing.split( ',' ) if m.strip() ]

    def get_present_dict( self ):
        """
        Get present arguments as a dictionary.

        Requires:
            - self.args_present is a string of comma-separated key=value pairs

        Ensures:
            - Returns dict mapping arg names to their values
            - Returns empty dict if args_present is empty
            - Handles values with = signs correctly (splits on first = only)

        Returns:
            dict: Mapping of argument names to their values
        """
        if not self.args_present or not self.args_present.strip():
            return {}

        result = {}
        for pair in self.args_present.split( ',' ):
            pair = pair.strip()
            if '=' in pair:
                key, value = pair.split( '=', 1 )
                result[ key.strip() ] = value.strip()

        return result

    @classmethod
    def get_example_for_template( cls ):
        """
        Get example instance for prompt templates.

        Returns an expeditor response example that matches the expected
        XML structure for the runtime-argument-expeditor.txt template.

        Requires:
            - None

        Ensures:
            - Returns ExpeditorResponse with sample gap analysis data
        """
        return cls(
            all_required_met = "false",
            args_present     = "query=biodiversity loss",
            args_missing     = "budget"
        )

    @classmethod
    def quick_smoke_test( cls, debug=False ):
        """
        Quick smoke test for ExpeditorResponse.

        Args:
            debug: Enable debug output

        Returns:
            True if all tests pass
        """
        if debug: print( f"Testing {cls.__name__}..." )

        try:
            # Test base functionality
            if not super().quick_smoke_test( debug=False ):
                return False

            # Test creation with all fields
            response = cls(
                all_required_met = "false",
                args_present     = "query=quantum computing, budget=10",
                args_missing     = "audience"
            )
            assert response.all_required_met == "false"

            # Test is_complete
            assert not response.is_complete()
            complete = cls(
                all_required_met = "true",
                args_present     = "query=test",
                args_missing     = ""
            )
            assert complete.is_complete()

            # Test get_missing_list
            missing = response.get_missing_list()
            assert len( missing ) == 1
            assert missing[ 0 ] == "audience"

            # Test get_present_dict
            present = response.get_present_dict()
            assert present[ "query" ] == "quantum computing"
            assert present[ "budget" ] == "10"

            # Test empty missing
            empty_missing = complete.get_missing_list()
            assert empty_missing == []

            # Test XML round-trip
            xml_str = response.to_xml()
            assert "<all_required_met>false</all_required_met>" in xml_str
            parsed = cls.from_xml( xml_str )
            assert parsed.all_required_met == response.all_required_met
            assert parsed.args_present == response.args_present

            # Test None coercion (empty XML tags like <args_missing></args_missing>)
            none_response = cls(
                all_required_met = "true",
                args_present     = None,
                args_missing     = None
            )
            assert none_response.args_present == ""
            assert none_response.args_missing == ""
            assert none_response.is_complete()
            assert none_response.get_missing_list() == []
            assert none_response.get_present_dict() == {}

            # Test template example
            example = cls.get_example_for_template()
            assert "biodiversity" in example.args_present

            if debug: print( f"✓ {cls.__name__} smoke test PASSED" )
            return True

        except Exception as e:
            if debug: print( f"✗ {cls.__name__} smoke test FAILED: {e}" )
            return False


class ArgConfirmationResponse( BaseXMLModel ):
    """
    Parses user intent during argument confirmation loop.

    Handles XML responses for modification intent:
    <response>
        <action>modify</action>
        <arg_name>budget</arg_name>
        <new_value>50</new_value>
    </response>

    Fields:
        action: User intent — 'approve', 'modify', or 'cancel'
        arg_name: Argument to modify (empty if approve/cancel)
        new_value: New value for the argument (empty if approve/cancel)
    """

    action    : str = Field( ..., description="User intent: 'approve', 'modify', or 'cancel'" )
    arg_name  : str = Field( ..., description="Argument to modify (empty if approve/cancel)" )
    new_value : str = Field( ..., description="New value for the argument (empty if approve/cancel)" )

    @field_validator( "*", mode="before" )
    @classmethod
    def coerce_none_to_empty_str( cls, v ):
        """Coerce None (from empty XML tags like <foo></foo>) to empty string."""
        if v is None:
            return ""
        return v

    def is_approval( self ):
        """
        Check if the user approved the arguments.

        Requires:
            - self.action is a string

        Ensures:
            - Returns True if action indicates approval
            - Returns False otherwise
        """
        return self.action.strip().lower() in ( "approve", "yes", "ok" )

    def is_cancel( self ):
        """
        Check if the user wants to cancel.

        Requires:
            - self.action is a string

        Ensures:
            - Returns True if action indicates cancellation
            - Returns False otherwise
        """
        return self.action.strip().lower() in ( "cancel", "stop", "quit" )

    def is_modify( self ):
        """
        Check if the user wants to modify an argument.

        Requires:
            - self.action is a string

        Ensures:
            - Returns True if action is 'modify'
            - Returns False otherwise
        """
        return self.action.strip().lower() == "modify"

    @classmethod
    def get_example_for_template( cls ):
        """
        Get example instance for prompt templates.

        Requires:
            - None

        Ensures:
            - Returns ArgConfirmationResponse with sample modify data
        """
        return cls( action="modify", arg_name="budget", new_value="50" )

    @classmethod
    def quick_smoke_test( cls, debug=False ):
        """
        Quick smoke test for ArgConfirmationResponse.

        Args:
            debug: Enable debug output

        Returns:
            True if all tests pass
        """
        if debug: print( f"Testing {cls.__name__}..." )

        try:
            # Test base functionality
            if not super().quick_smoke_test( debug=False ):
                return False

            # Test creation with all fields
            response = cls( action="modify", arg_name="budget", new_value="50" )
            assert response.action == "modify"
            assert response.arg_name == "budget"
            assert response.new_value == "50"

            # Test is_approval
            approve = cls( action="approve", arg_name="", new_value="" )
            assert approve.is_approval()
            assert not approve.is_cancel()
            assert not approve.is_modify()

            # Test is_cancel
            cancel = cls( action="cancel", arg_name="", new_value="" )
            assert cancel.is_cancel()
            assert not cancel.is_approval()
            assert not cancel.is_modify()

            # Test is_modify
            assert response.is_modify()
            assert not response.is_approval()
            assert not response.is_cancel()

            # Test XML round-trip
            xml_str = response.to_xml()
            assert "<action>modify</action>" in xml_str
            parsed = cls.from_xml( xml_str )
            assert parsed.action == response.action
            assert parsed.arg_name == response.arg_name
            assert parsed.new_value == response.new_value

            # Test None coercion (empty XML tags like <arg_name></arg_name>)
            none_response = cls( action="approve", arg_name=None, new_value=None )
            assert none_response.arg_name == ""
            assert none_response.new_value == ""
            assert none_response.is_approval()

            # Test template example
            example = cls.get_example_for_template()
            assert example.action == "modify"
            assert example.arg_name == "budget"

            if debug: print( f"✓ {cls.__name__} smoke test PASSED" )
            return True

        except Exception as e:
            if debug: print( f"✗ {cls.__name__} smoke test FAILED: {e}" )
            return False


def quick_smoke_test():
    """Module-level smoke test following CoSA convention."""
    result1 = ExpeditorResponse.quick_smoke_test( debug=True )
    result2 = ArgConfirmationResponse.quick_smoke_test( debug=True )
    return result1 and result2


if __name__ == "__main__":
    success = quick_smoke_test()
    exit( 0 if success else 1 )
