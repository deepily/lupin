#!/usr/bin/env python3
"""
Unit tests for cosa.agents.notification_proxy.scalar_answers.

drop_non_scalar_answers is the row-ceca10f3 guard: a predicted batch answer
that is a non-scalar (object / list) must be DROPPED, never coerced, before it
is stamped as a high-confidence answer for the user. These tests exercise every
branch with hand-built dicts (zero external dependencies).
"""

import pytest

from cosa.agents.notification_proxy.scalar_answers import drop_non_scalar_answers


class TestScalarsKept:
    """Scalar values survive; numbers and bools are stringified."""

    def test_strings_kept_verbatim( self ):
        out = drop_non_scalar_answers( { "A": "yes", "B": "no" }, "test" )
        assert out == { "A": "yes", "B": "no" }

    def test_int_and_float_stringified( self ):
        out = drop_non_scalar_answers( { "A": 3, "B": 1.5 }, "test" )
        assert out == { "A": "3", "B": "1.5" }

    def test_bool_kept_as_string_not_int( self ):
        """
        Ensures:
            - True/False survive as "True"/"False" (bool is a subclass of int,
              so the guard must test bool BEFORE int)
        """
        out = drop_non_scalar_answers( { "A": True, "B": False }, "test" )
        assert out == { "A": "True", "B": "False" }


class TestNonScalarsDropped:
    """Objects and lists are dropped; co-located scalars survive."""

    def test_dict_value_dropped( self ):
        out = drop_non_scalar_answers( { "A": "keep", "B": { "x": 1 } }, "test" )
        assert out == { "A": "keep" }

    def test_list_value_dropped( self ):
        out = drop_non_scalar_answers( { "A": "keep", "B": [ 1, 2, 3 ] }, "test" )
        assert out == { "A": "keep" }

    def test_none_value_dropped( self ):
        out = drop_non_scalar_answers( { "A": "keep", "B": None }, "test" )
        assert out == { "A": "keep" }

    def test_all_non_scalar_degrades_to_empty( self ):
        """
        Ensures:
            - an all-non-scalar map returns {}, so the producer's not-answers
              guard returns None and the client cleanly falls back
        """
        out = drop_non_scalar_answers( { "A": { "x": 1 }, "B": [ 1 ] }, "test" )
        assert out == {}


class TestDefensiveInputs:
    """Non-dict inputs never raise; the input is never mutated."""

    @pytest.mark.parametrize( "bad", [ None, "not a dict", 42, [ 1, 2 ] ] )
    def test_non_dict_yields_empty( self, bad ):
        assert drop_non_scalar_answers( bad, "test" ) == {}

    def test_input_not_mutated( self ):
        original = { "A": "keep", "B": { "x": 1 } }
        drop_non_scalar_answers( original, "test" )
        assert original == { "A": "keep", "B": { "x": 1 } }, "input must not be mutated"

    def test_returns_new_object( self ):
        original = { "A": "keep" }
        out = drop_non_scalar_answers( original, "test" )
        assert out is not original, "must return a NEW dict, not the input"


class TestDropIsLoggedLoud:
    """A dropped non-scalar is logged unconditionally (not gated on debug)."""

    def test_drop_prints_header_type_and_context( self, capsys ):
        drop_non_scalar_answers( { "Region": { "x": 1 } }, "expediter_rules.batch" )
        captured = capsys.readouterr().out
        assert "DROPPED" in captured
        assert "Region" in captured
        assert "dict" in captured
        assert "expediter_rules.batch" in captured
