"""
Unit tests for tests.helpers.typed_config.

The fake exists so a test cannot pass by ignoring return_type, so it must convert exactly as
the real ConfigurationManager does. Each case below is read through the real manager and through
the fake, and the two answers must be equal and of the same type.
"""

import pytest

from cosa.tests.unit.config.test_configuration_manager import _CfgBase
from tests.helpers.typed_config import TypedConfigFake

CASES = [
    ( "true",      "boolean" ), ( "True",    "boolean" ), ( "  True  ", "boolean" ), ( "false", "boolean" ),
    ( "yes",       "boolean" ), ( "1",       "boolean" ), ( True,       "boolean" ), ( False,   "boolean" ),
    ( "42",        "int"     ), ( 7,         "int"     ), ( "3.5",      "float"   ), ( 2,       "float"   ),
    ( "text",      "string"  ), ( "text",    "str"     ), ( "a, b, c",  "list-string" ),
    ( '{"k": 1}',  "json"    ), ( "{'k': 1}", "dict"    ), ( "42",      "INT"     ),
]


class TestTypedConfigFake( _CfgBase ):

    def setUp( self ):
        super().setUp()
        self.mgr = self._build( block_id="child" )

    def test_the_fake_converts_like_the_real_manager_for_every_case( self ):
        assert len( CASES ) == 18
        for value, return_type in CASES:
            real = self.mgr._get_typed_value( value, return_type )
            fake = TypedConfigFake( every_key=value ).get( "any key", return_type=return_type )
            assert fake == real and type( fake ) is type( real ), ( value, return_type )

    def test_the_fake_rejects_an_unknown_return_type_like_the_manager( self ):
        with pytest.raises( ValueError ): self.mgr._get_typed_value( "x", "nonsense" )
        with pytest.raises( ValueError ): TypedConfigFake( every_key="x" ).get( "k", return_type="nonsense" )


def test_a_stored_value_wins_over_the_default_and_both_are_converted():
    fake = TypedConfigFake( { "a": "true" } )
    assert fake.get( "a", default="false", return_type="boolean" ) is True
    assert fake.get( "b", default="false", return_type="boolean" ) is False
    assert fake.get( "b", default=3, return_type="int" ) == 3


def test_an_absent_key_with_no_default_converts_none_like_the_manager_would():
    assert TypedConfigFake( {} ).get( "missing" ) is None


def test_every_key_answers_every_key_and_can_be_replaced():
    fake = TypedConfigFake( { "a": "false" }, every_key="true" )
    assert fake.get( "a", return_type="boolean" ) is True
    assert fake.get( "zzz", return_type="boolean" ) is True
    fake.set_every_key( "false" )
    assert fake.get( "a", return_type="boolean" ) is False


def test_the_default_return_type_is_string_so_a_boolean_ask_differs_from_a_plain_ask():
    fake = TypedConfigFake( { "k": "false" } )
    assert fake.get( "k" ) == "false"
    assert fake.get( "k", return_type="boolean" ) is False
