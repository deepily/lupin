"""
Unit tests for `_parse_optional_boolean()` and the test_suite branch's
`auto_fix_on_failure` threading in `cosa.rest.agentic_job_factory`.

Session 1cfcdf73 (2026-04-10): The factory must thread tri-state booleans
(None / True / False) from REST kwargs through to TestSuiteJob without
collapsing None into False (which would silently disable per-run override).
"""

import pytest

from cosa.rest.agentic_job_factory import _parse_optional_boolean


class TestParseOptionalBoolean:

    def test_none_returns_none( self ):
        assert _parse_optional_boolean( None ) is None

    def test_explicit_true_bool_returns_true( self ):
        assert _parse_optional_boolean( True ) is True

    def test_explicit_false_bool_returns_false( self ):
        assert _parse_optional_boolean( False ) is False

    @pytest.mark.parametrize( "value", [ "true", "True", "TRUE", "yes", "1", "enable", "enabled" ] )
    def test_truthy_strings_return_true( self, value ):
        assert _parse_optional_boolean( value ) is True

    @pytest.mark.parametrize( "value", [ "false", "False", "FALSE", "0", "disable", "disabled", "off" ] )
    def test_falsy_strings_return_false( self, value ):
        assert _parse_optional_boolean( value ) is False

    @pytest.mark.parametrize( "value", [ "", "default", "no limit", "none", "skip", "no" ] )
    def test_semantic_none_returns_none( self, value ):
        assert _parse_optional_boolean( value ) is None

    def test_unparseable_string_returns_none( self ):
        """Unknown values are treated as 'no override' rather than collapsed to False."""
        assert _parse_optional_boolean( "maybe" ) is None
        assert _parse_optional_boolean( "garbage" ) is None
