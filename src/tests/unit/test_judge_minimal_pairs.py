"""The judge's 24 minimal pairs: four of each of six kinds, each flipping on one condition."""

import collections
import json
import re

import pytest

import cosa.utils.util as cu

KINDS = ( "before_after", "staging_production", "must_may", "negated_permission", "scope_change", "time_change" )


@pytest.fixture( scope="module" )
def document():
    """Read the committed pairs file."""
    with open( cu.get_project_root() + "/src/cosa/research/judge_validation/minimal_pairs.json", encoding="utf-8" ) as handle:
        return json.load( handle )


def test_four_pairs_of_each_of_the_six_kinds( document ):
    counts = collections.Counter( pair[ "kind" ] for pair in document[ "pairs" ] )

    assert len( document[ "pairs" ] ) == 24
    assert counts == { kind: 4 for kind in KINDS }
    assert len( { pair[ "id" ] for pair in document[ "pairs" ] } ) == 24


def test_each_pair_has_three_different_texts_so_the_judge_is_asked( document ):
    assert document[ "pairs" ]
    for pair in document[ "pairs" ]:
        texts = [ pair[ key ].strip().lower() for key in ( "actual_text", "matching_text", "altered_text" ) ]
        assert all( texts ) and len( set( texts ) ) == 3, pair[ "id" ]


def test_the_two_forecasts_of_a_pair_share_most_of_their_words( document ):
    assert document[ "pairs" ]
    for pair in document[ "pairs" ]:
        matching = set( re.findall( r"\w+", pair[ "matching_text" ].lower() ) )
        altered  = set( re.findall( r"\w+", pair[ "altered_text" ].lower() ) )
        assert len( matching & altered ) / len( matching | altered ) >= 0.4, pair[ "id" ]


def test_each_pair_names_a_card_of_the_run_2_archive( document ):
    assert document[ "pairs" ]
    for case in document[ "pairs" ] + document[ "extra_cases" ]:
        assert len( case[ "source_card" ][ "notification_id" ] ) == 36, case[ "id" ]
        assert case[ "source_card" ][ "question" ], case[ "id" ]


def test_the_extra_cases_are_an_easy_pass_and_an_invented_condition_on_a_plain_answer( document ):
    cases = { case[ "kind" ]: case for case in document[ "extra_cases" ] }

    assert set( cases ) == { "easy", "invented_condition" }
    assert "altered_text" not in cases[ "easy" ] and cases[ "easy" ][ "matching_text" ]
    assert cases[ "invented_condition" ][ "actual_text" ] is None
    assert "matching_text" not in cases[ "invented_condition" ] and cases[ "invented_condition" ][ "altered_text" ]
