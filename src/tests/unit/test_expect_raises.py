"""
Unit tests for cosa.utils.expect_raises.

The helper proves that a smoke test's guard fires.
A silent pass here would make every control using it worthless.
Each test pins one way it could pass wrongly.
"""

import pytest

from cosa.utils.expect_raises import expect_raises


class _Boom( ValueError ):
    pass


def _raises_boom( message="boom" ):
    raise _Boom( message )


def _returns_quietly( *args, **kwargs ):
    return None


def test_returns_the_exception_the_function_raised():
    raised = expect_raises( _Boom, _raises_boom )
    assert isinstance( raised, _Boom )


def test_passes_positional_and_keyword_arguments_through():
    raised = expect_raises( _Boom, _raises_boom, "first" )
    assert str( raised ) == "first"
    raised = expect_raises( _Boom, _raises_boom, message="second" )
    assert str( raised ) == "second"


def test_a_silent_function_is_a_failure_that_names_it_and_the_expected_type():
    with pytest.raises( AssertionError, match="_returns_quietly did NOT raise _Boom — the guard is asleep" ):
        expect_raises( _Boom, _returns_quietly )


def test_a_different_exception_type_propagates_unchanged():
    with pytest.raises( KeyError ):
        expect_raises( _Boom, lambda: {}[ "x" ] )


def test_a_subclass_of_the_expected_type_counts():
    assert isinstance( expect_raises( ValueError, _raises_boom ), _Boom )
