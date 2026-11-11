#!/usr/bin/env python3
"""
io_models number_fields: the float-or-zero parser and the 0-to-1 clamp.

Every model that reads a confidence or an amount out of a string field goes through them.

Venue: :7999-eligible / local, pure.
"""
import os
import sys

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.agents.calculator.xml_models import CalcIntent
from cosa.agents.io_models.utils.number_fields import clamp_unit, float_or_zero
from cosa.agents.notification_proxy.xml_models import ScriptMatcherResponse


def test_float_or_zero_reads_numbers_out_of_text():
    assert float_or_zero( "0.85" ) == 0.85
    assert float_or_zero( " 300000 " ) == 300000.0
    assert float_or_zero( "-2.5" ) == -2.5
    assert float_or_zero( 7 ) == 7.0


def test_float_or_zero_gives_zero_for_blank_junk_and_none():
    assert float_or_zero( "" ) == 0.0
    assert float_or_zero( "   " ) == 0.0
    assert float_or_zero( "high" ) == 0.0
    assert float_or_zero( None ) == 0.0
    assert float_or_zero( [ 1 ] ) == 0.0


def test_clamp_unit_keeps_the_range_and_pins_outside_values():
    assert clamp_unit( 0.4 ) == 0.4
    assert clamp_unit( 0.0 ) == 0.0 and clamp_unit( 1.0 ) == 1.0
    assert clamp_unit( -3.0 ) == 0.0
    assert clamp_unit( 7.5 ) == 1.0


def test_a_model_confidence_is_parsed_then_clamped():
    assert ScriptMatcherResponse( matched_entry="1", answer="a", confidence="1.7" ).get_confidence_float() == 1.0
    assert ScriptMatcherResponse( matched_entry="1", answer="a", confidence="-1" ).get_confidence_float() == 0.0
    assert ScriptMatcherResponse( matched_entry="1", answer="a", confidence="n/a" ).get_confidence_float() == 0.0


def test_a_model_amount_is_parsed_but_not_clamped():
    intent = CalcIntent( operation="mortgage", principal="300000", annual_rate="6.5", down_payment="  " )
    assert intent.get_principal_float() == 300000.0
    assert intent.get_annual_rate_float() == 6.5
    assert intent.get_down_payment_float() == 0.0


def test_batch_script_matcher_confidence_is_parsed_then_clamped():
    from cosa.agents.notification_proxy.xml_models import BatchScriptMatcherResponse
    def conf( text ): return BatchScriptMatcherResponse( entries=[], confidence=text ).get_confidence_float()
    assert conf( "0.9" ) == 0.9
    assert conf( "1.7" ) == 1.0
    assert conf( "-1" ) == 0.0
    assert conf( "n/a" ) == 0.0
