#!/usr/bin/env python3
"""
power: paired power and minimum detectable gain against hand-worked closed forms.

Venue: :7999-eligible / local, pure.
"""
import os
import sys

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

import pytest

from cosa.research.preference_replay import power as pw

# Two parameter sets, with z = 1.959964 and z at 80% power = 0.841621.
# Set 1: disagreement 0.2, 1000 cards, gain 0.05: (1.581139 - 0.876523) / sqrt(0.1975) = 1.585510
# Set 2: disagreement 0.1,  500 cards, gain 0.03: (0.670820 - 0.619795) / sqrt(0.0991) = 0.162086


def test_power_matches_the_closed_form_answer_at_two_parameter_sets():
    assert pw.power( 0.05, 0.2, 1000 ) == pytest.approx( 0.94357, abs=1e-4 )
    assert pw.power( 0.03, 0.1, 500 )  == pytest.approx( 0.56438, abs=1e-4 )


def test_the_minimum_detectable_gain_matches_the_closed_form_answer_at_two_parameter_sets():
    first, second = pw.minimum_detectable_gain( 0.2, 1000 ), pw.minimum_detectable_gain( 0.1, 500 )
    assert first[ "gain" ]  == pytest.approx( 0.039574, abs=1e-5 ) and first[ "reason" ] is None
    assert second[ "gain" ] == pytest.approx( 0.039527, abs=1e-5 )
    assert ( first[ "disagreement" ], first[ "cards" ], first[ "power" ], first[ "alpha" ] ) == ( 0.2, 1000, 0.8, 0.05 )


def test_the_gain_found_has_the_target_power():
    for target in ( 0.5, 0.8, 0.95 ):
        gain = pw.minimum_detectable_gain( 0.15, 1926, target=target )[ "gain" ]
        assert pw.power( gain, 0.15, 1926 ) == pytest.approx( target )


def test_power_at_the_edges():
    assert pw.power( 0.0, 0.2, 100 ) == pytest.approx( 0.025 )
    assert pw.power( 1.0, 1.0, 100 ) == 1.0 and pw.power( 1.0, 1.0, 1 ) == 0.0


# at ( 0.5, 10 ) the equation has a root, 0.555, above the disagreement rate; at the other two it has none
@pytest.mark.parametrize( "disagreement, cards", [ ( 0.01, 2 ), ( 0.5, 3 ), ( 0.5, 10 ) ] )
def test_too_few_cards_give_no_gain_and_say_why( disagreement, cards ):
    got = pw.minimum_detectable_gain( disagreement, cards )
    assert got[ "gain" ] is None and got[ "reason" ] == pw.NO_GAIN_LARGE_ENOUGH


def test_a_negative_root_term_gives_no_gain():
    got = pw.minimum_detectable_gain( 1.0, 1, target=0.5, alpha=0.001 )
    assert got[ "gain" ] is None and got[ "reason" ] == pw.NO_GAIN_LARGE_ENOUGH


@pytest.mark.parametrize( "call, reason", [
    ( lambda: pw.power( 0.0, 0.0, 10 ),                         "disagreement rate" ),
    ( lambda: pw.power( 0.0, 1.5, 10 ),                         "disagreement rate" ),
    ( lambda: pw.power( 0.0, 0.2, 0 ),                          "at least 1 card" ),
    ( lambda: pw.power( 0.0, 0.2, 10, alpha=0 ),                "alpha" ),
    ( lambda: pw.power( -0.01, 0.2, 10 ),                       "the gain must be" ),
    ( lambda: pw.power( 0.3, 0.2, 10 ),                         "the gain must be" ),
    ( lambda: pw.minimum_detectable_gain( 0.2, 10, target=0.4 ), "target power" ),
    ( lambda: pw.minimum_detectable_gain( 0.2, 10, target=1 ),   "target power" ),
    ( lambda: pw.minimum_detectable_gain( 2, 10 ),               "disagreement rate" ),
] )
def test_inputs_with_no_answer_are_refused( call, reason ):
    with pytest.raises( ValueError, match=reason ): call()
