#!/usr/bin/env python3
"""
temperature_to_steer: the one rule behind the three bounded-CC clients' creativity steer.

The cut-offs and the sentences are each client's own, so each is pinned to its literal here.

Venue: :7999-eligible / local, pure.
"""
import os
import sys

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

import pytest

from cosa.agents.deep_research.api_client import _temperature_to_steer as research_steer
from cosa.agents.podcast_generator.api_client import _temperature_to_steer as podcast_steer
from cosa.agents.presentation_generator.api_client import _temperature_to_steer as presentation_steer
from cosa.agents.shared.bounded_cc_client import temperature_to_steer


def test_the_shared_rule_is_inclusive_at_both_cut_offs_and_empty_between():
    assert temperature_to_steer( 0.8, 0.8, 0.2, "HI", "LO" ) == "HI"
    assert temperature_to_steer( 0.9, 0.8, 0.2, "HI", "LO" ) == "HI"
    assert temperature_to_steer( 0.2, 0.8, 0.2, "HI", "LO" ) == "LO"
    assert temperature_to_steer( 0.1, 0.8, 0.2, "HI", "LO" ) == "LO"
    assert temperature_to_steer( 0.5, 0.8, 0.2, "HI", "LO" ) == ""
    assert temperature_to_steer( 0.7999, 0.8, 0.2, "HI", "LO" ) == ""
    assert temperature_to_steer( 0.2001, 0.8, 0.2, "HI", "LO" ) == ""


@pytest.mark.parametrize( "temperature, expected", [
    ( 1.0, "Be expansive and creative in your reasoning; explore multiple angles." ),
    ( 0.9, "Be expansive and creative in your reasoning; explore multiple angles." ),
    ( 0.89, "" ),
    ( 0.51, "" ),
    ( 0.5, "Be precise, literal, and deterministic; avoid speculation." ),
] )
def test_research_keeps_its_cut_offs_and_wording( temperature, expected ):
    assert research_steer( temperature ) == expected


@pytest.mark.parametrize( "steer, low_sentence", [
    ( podcast_steer,      "Write with precise, focused, deterministic phrasing." ),
    ( presentation_steer, "Write with precise, focused, deterministic output." ),
] )
def test_podcast_and_presentation_keep_their_cut_offs_and_wording( steer, low_sentence ):
    assert steer( 0.75 ) == "Write with creative, natural, varied phrasing."
    assert steer( 0.74 ) == ""
    assert steer( 0.56 ) == ""
    assert steer( 0.55 ) == low_sentence
