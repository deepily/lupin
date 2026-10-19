"""
Unit tests for the fenced-block parser shared by the diagnosis and result parsers.

Twin refactor slice output-contract-parse: both public functions were the same body around two regexes.
"""

import re

import pytest

from cosa.agents.tfe_to_cc.prompts.output_contract import (
    _parse_fenced_clusters_block, parse_diagnosis_block, parse_result_block
)

FENCE = re.compile( r"```demo\s*\n(?P<body>.*?)\n```", re.DOTALL )


class TestParseFencedClustersBlock:

    def test_returns_the_object_when_clusters_is_a_dict( self ):
        text = 'prose\n```demo\n{ "clusters": { "C1": {} }, "extra": 1 }\n```\ntail'
        assert _parse_fenced_clusters_block( text, FENCE ) == { "clusters": { "C1": {} }, "extra": 1 }

    @pytest.mark.parametrize( "text", [
        None,
        "",
        "no fence at all",
        "```demo\nnot json\n```",
        "```demo\n[1, 2]\n```",
        '```demo\n{ "other": 1 }\n```',
        '```demo\n{ "clusters": [1] }\n```',
    ] )
    def test_every_failure_is_none( self, text ):
        assert _parse_fenced_clusters_block( text, FENCE ) is None

    def test_the_fence_argument_selects_the_block( self ):
        text = '```tfe-diagnosis\n{ "clusters": { "D": {} } }\n```\n```tfe-result\n{ "clusters": { "R": {} } }\n```'
        assert parse_diagnosis_block( text ) == { "clusters": { "D": {} } }
        assert parse_result_block( text )    == { "clusters": { "R": {} } }
