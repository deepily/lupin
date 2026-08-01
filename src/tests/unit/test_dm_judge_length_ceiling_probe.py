#!/usr/bin/env python3
"""
Unit tier for the length-ceiling probe's pure logic — the instrument, not the model.

WHY GATE A PROBE. Its whole claim is that a directness answer correct at 45 words is
still correct at 500, and that rests entirely on HOW the padding is applied: appended,
never inserted, and carrying no payload of its own. If `pad_to` ever prefixed the
filler, or the filler ever acquired an outcome sentence, the probe would keep printing
"ok" while measuring something else. Those properties are asserted here rather than
assumed, and the non-answer bookkeeping gets a control that must fail.
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert( 0, os.path.join( os.environ.get( "LUPIN_ROOT", "" ), "src" ) )
sys.path.insert( 0, os.path.join( os.environ.get( "LUPIN_ROOT", "" ), "src", "tests", "smoke" ) )

from dm_judge_length_ceiling_probe import (
    BODIES,
    EXPECTED_DIRECTNESS,
    FILLER,
    measure_cell,
    pad_to,
)
from cosa.agents.dm_quality_judge.judge import _JUDGE_UNAVAILABLE_DETAIL
from cosa.agents.dm_quality_judge.xml_models_v2 import split_sentences


BODY = "Phase one is done. I read the ticket history. The timeout is wrong."


class TestPadding:

    def test_none_target_returns_the_body_unchanged( self ):
        assert pad_to( BODY, None ) == BODY

    @pytest.mark.parametrize( "target", [ 200, 300, 500 ] )
    def test_padding_hits_the_target_word_count_exactly( self, target ):
        assert len( pad_to( BODY, target ).split() ) == target

    @pytest.mark.parametrize( "target", [ 200, 300, 500 ] )
    def test_the_original_body_stays_at_the_front( self, target ):
        # THE load-bearing property. Prefixed filler would shift the verdict's sentence
        # index, and every "expected" grade in the probe would silently become wrong
        # while the run still printed ok.
        assert pad_to( BODY, target ).startswith( BODY )

    @pytest.mark.parametrize( "target", [ 200, 300, 500 ] )
    def test_the_verdicts_sentence_index_never_moves( self, target ):
        short_sentences = split_sentences( BODY )
        long_sentences  = split_sentences( pad_to( BODY, target ) )
        assert long_sentences[ :len( short_sentences ) ] == short_sentences

    def test_filler_carries_no_payload_vocabulary( self ):
        # The filler must never qualify as a "clear payload", or it could become the
        # first payload of a BURIED body and change that body's correct answer.
        for word in ( "decision", "blocker", "risk", "failed", "done", "committed",
                      "merge", "bug", "please", "need you to" ):
            assert word not in FILLER.lower()

    def test_every_probe_body_has_a_declared_expectation( self ):
        assert { name for name, _ in BODIES } == set( EXPECTED_DIRECTNESS )

    def test_expectations_only_use_real_scale_values( self ):
        assert all( w in ( -2, -1, 0, 1, 2 ) for w in EXPECTED_DIRECTNESS.values() )


class TestMeasureCell:

    def _judge_returning( self, directness, tone ):
        judge = MagicMock()
        judge.judge = MagicMock( return_value={ "directness": directness, "tone": tone } )
        return judge

    def test_real_grades_are_collected_per_dimension( self ):
        judge = self._judge_returning(
            { "weight":  2, "detail": "the verdict leads" },
            { "weight": -1, "detail": "owed oracle" },
        )
        out = measure_cell( judge, BODY, runs=3 )
        assert out[ "directness" ] == [ 2, 2, 2 ]
        assert out[ "tone" ]       == [ -1, -1, -1 ]
        assert out[ "nonanswers" ] == [ ]

    def test_a_non_answer_is_never_recorded_as_a_weight( self ):
        # The control that must fail: if a refusal leaked into the weight list it would
        # read as a real grade, and a model that had stopped answering at length would
        # look like a model with no ceiling.
        judge = self._judge_returning(
            { "weight": None, "detail": _JUDGE_UNAVAILABLE_DETAIL },
            { "weight":    1, "detail": "plain words" },
        )
        out = measure_cell( judge, BODY, runs=2 )
        assert out[ "directness" ] == [ ]
        assert out[ "tone" ]       == [ 1, 1 ]
        assert out[ "nonanswers" ] == [ "directness:unavailable", "directness:unavailable" ]

    def test_the_ceiling_is_restored_after_the_probe_runs( self ):
        # The probe lifts the ceiling with a context manager precisely so it cannot
        # leave production behaviour changed behind it.
        from cosa.agents.dm_quality_judge import judge_v2
        before = judge_v2.QUALITATIVE_WORD_LIMIT
        measure_cell( self._judge_returning( { "weight": 2, "detail": "x" },
                                             { "weight": 2, "detail": "y" } ), BODY, runs=1 )
        assert judge_v2.QUALITATIVE_WORD_LIMIT == before

    def test_the_ceiling_is_actually_lifted_while_measuring( self ):
        # Asserting the mechanism, not just its cleanup: a patch that silently failed
        # would make every long cell return "too long" and the probe would report a
        # ceiling that its own harness had created.
        seen = { }
        def capture( _body ):
            from cosa.agents.dm_quality_judge import judge_v2
            seen[ "limit" ] = judge_v2.QUALITATIVE_WORD_LIMIT
            return { "directness": { "weight": 2, "detail": "x" },
                     "tone"      : { "weight": 2, "detail": "y" } }
        judge = MagicMock()
        judge.judge = capture
        measure_cell( judge, BODY, runs=1 )
        assert seen[ "limit" ] == 100_000
