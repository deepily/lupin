#!/usr/bin/env python3
"""
Unit tier for DM Quality Judge v2 — the extraction judge.

WHAT THIS SUITE IS FOR. v2's entire claim over v1 is that the directness inputs are
CHECKED against the source text before any number is derived. A check nobody has
watched fail is not known to be running, so the bulk of this file is controls: inputs
that MUST be rejected, each aimed at one specific way a model could be wrong and still
look right.

WHAT IT DELIBERATELY DOES NOT DO. It never calls a model. The 2026-07-31 lesson stands:
a suite that hand-feeds clean XML measures the PARSER, not whether the prompt makes the
model discriminate. That question belongs to src/tests/smoke/dm_judge_discrimination_probe.py
and cannot be answered here — so this file does not pretend to.
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert( 0, os.path.join( os.environ.get( "LUPIN_ROOT", "" ), "src" ) )

from cosa.agents.dm_quality_judge import get_dm_quality_judge, DEFAULT_JUDGE_VERSION
from cosa.agents.dm_quality_judge.judge import DmQualityJudge, _repair_llm_xml
from cosa.agents.dm_quality_judge.judge_v2 import (
    DmQualityJudgeV2,
    _EXTRACTION_FAILED_DETAIL,
    _extraction_failed_dimension,
)
from cosa.agents.dm_quality_judge.xml_models_v2 import (
    CONCISION_ADJUSTMENT_ENABLED,
    DIRECTNESS_FIELDS,
    TONE_FIELDS,
    DmDirectnessExtraction,
    DmToneJudgement,
    ExtractionError,
    NO_PAYLOAD_INDEX,
    code_weight,
    directness_weight,
    number_sentences,
    parse_index,
    parse_indices,
    position_weight,
    split_sentences,
    structural_code,
    validate_extraction,
)


BODY      = "Phase one is done. I read the ticket history. The timeout is wrong."
SENTENCES = split_sentences( BODY )


# ══════════════════════════════════════════════════════════════════════════════
# Sentence splitting — the list is shown to the model AND checked against, so a
# miscount here poisons every index downstream
# ══════════════════════════════════════════════════════════════════════════════

class TestSplitSentences:

    def test_splits_on_terminal_punctuation( self ):
        assert split_sentences( "One. Two! Three?" ) == [ "One.", "Two!", "Three?" ]

    def test_empty_and_whitespace_bodies_yield_no_sentences( self ):
        assert split_sentences( "" )      == [ ]
        assert split_sentences( "   \n " ) == [ ]

    def test_decimal_point_is_not_a_boundary( self ):
        assert len( split_sentences( "The timeout is 30.5 seconds and should be 5." ) ) == 1

    @pytest.mark.parametrize( "text", [
        "Tests, docs, etc. are done. Ship it.",
        "Checked it vs. the baseline. All green.",
        "Ask Dr. Ruiz about it. He wrote it.",
    ] )
    def test_abbreviation_is_not_a_boundary( self, text ):
        assert len( split_sentences( text ) ) == 2

    def test_single_letter_initial_is_not_a_boundary( self ):
        assert len( split_sentences( "Ask R. Ruiz about it. He wrote it." ) ) == 2

    def test_ellipsis_makes_one_boundary_not_three( self ):
        assert len( split_sentences( "I paused... Then I shipped it." ) ) == 2

    def test_trailing_fragment_without_punctuation_is_kept( self ):
        assert split_sentences( "Done. And one more thing" )[ -1 ] == "And one more thing"

    def test_no_character_is_invented_or_dropped( self ):
        body = "One. Two! Three? A trailing bit"
        assert " ".join( split_sentences( body ) ) == " ".join( body.split() )

    def test_whitespace_is_normalized( self ):
        assert split_sentences( "One.\n\n  Two." ) == [ "One.", "Two." ]

    def test_closing_quote_before_the_space_still_splits( self ):
        # This caught a real defect: "no" was in the abbreviation list (for "No. 5") and
        # swallowed this boundary, merging two sentences and shifting every index after
        # it. An abbreviation entry that is also a common English word is a trap.
        assert len( split_sentences( 'He said "no." Then he left.' ) ) == 2

    @pytest.mark.parametrize( "word", [ "no", "fig", "act", "sec", "min", "art" ] )
    def test_common_words_are_not_treated_as_abbreviations( self, word ):
        from cosa.agents.dm_quality_judge.xml_models_v2 import _ABBREVIATIONS
        assert word not in _ABBREVIATIONS

    def test_a_boundary_after_a_non_word_character_still_splits( self ):
        # The abbreviation guard only applies when a word precedes the period; here a
        # closing bracket does, so there is no word to look up.
        assert len( split_sentences( "He left (really). Then he came back." ) ) == 2


class TestNumberSentences:

    def test_numbers_are_one_based( self ):
        assert number_sentences( [ "A.", "B." ] ) == "1. A.\n2. B."

    def test_empty_list_renders_empty( self ):
        assert number_sentences( [ ] ) == ""


# ══════════════════════════════════════════════════════════════════════════════
# Parsing — the model emits text; a value we cannot read is never guessed
# ══════════════════════════════════════════════════════════════════════════════

class TestParseIndex:

    @pytest.mark.parametrize( "raw,expected", [
        ( "1", 1 ), ( " 2 ", 2 ), ( "3.", 3 ), ( "0", 0 ),
        ( "", 0 ), ( "none", 0 ), ( "N/A", 0 ), ( "null", 0 ),
    ] )
    def test_accepts_the_shapes_the_model_actually_emits( self, raw, expected ):
        assert parse_index( raw ) == expected

    @pytest.mark.parametrize( "raw", [ "first", "1 or 2", "sentence 1", "-1", "1.5" ] )
    def test_refuses_to_guess( self, raw ):
        with pytest.raises( ExtractionError ):
            parse_index( raw )


class TestParseIndices:

    @pytest.mark.parametrize( "raw,expected", [
        ( "4,7", [ 4, 7 ] ), ( "4, 7", [ 4, 7 ] ), ( "[4, 7]", [ 4, 7 ] ),
        ( "4 7", [ 4, 7 ] ), ( "2", [ 2 ] ),
        ( "", [ ] ), ( "none", [ ] ), ( "N/A", [ ] ),
    ] )
    def test_accepts_the_shapes_the_model_actually_emits( self, raw, expected ):
        assert parse_indices( raw ) == expected

    @pytest.mark.parametrize( "raw", [ "two, three", "4 and 7", "sentence 4" ] )
    def test_refuses_to_guess( self, raw ):
        with pytest.raises( ExtractionError ):
            parse_indices( raw )


# ══════════════════════════════════════════════════════════════════════════════
# THE CONTROLS. Each one is a way a model can be wrong and still look right.
# If any of these starts passing, v2's central claim is false.
# ══════════════════════════════════════════════════════════════════════════════

class TestValidationControls:

    def test_a_correct_extraction_is_accepted( self ):
        validate_extraction( "Phase one is done.", 1, [ 2 ], SENTENCES )

    def test_fabricated_quote_is_rejected( self ):
        with pytest.raises( ExtractionError, match="does not equal" ):
            validate_extraction( "I invented this sentence.", 1, [ ], SENTENCES )

    def test_correct_quote_with_wrong_index_is_rejected( self ):
        with pytest.raises( ExtractionError, match="does not equal" ):
            validate_extraction( "Phase one is done.", 2, [ ], SENTENCES )

    def test_sub_clause_is_rejected_because_the_check_is_equality( self ):
        # The reviewer's finding: containment would let a model quote the clean clause
        # of a sentence that also buries a blocker, land index 1 with no strays, and
        # collect the top of the scale.
        with pytest.raises( ExtractionError, match="does not equal" ):
            validate_extraction( "Phase one", 1, [ ], SENTENCES )

    def test_dropping_a_leading_discourse_marker_is_rejected( self ):
        # Observed live 3/3 on BURIED_PLAIN: the model quoted "The timeout is set..."
        # for a sentence reading "Anyway, the timeout is set...". A truncation is a
        # paraphrase, and a paraphrase is what this check exists to catch.
        sents = split_sentences( "Anyway, the timeout is wrong. I will fix it." )
        with pytest.raises( ExtractionError, match="does not equal" ):
            validate_extraction( "The timeout is wrong.", 1, [ ], sents )

    def test_index_past_the_end_is_rejected( self ):
        with pytest.raises( ExtractionError, match="out of range" ):
            validate_extraction( "Phase one is done.", 99, [ ], SENTENCES )

    def test_second_copy_of_a_repeated_sentence_is_rejected( self ):
        sents = split_sentences( "Same line. Other line. Same line." )
        with pytest.raises( ExtractionError, match="repeat" ):
            validate_extraction( "Same line.", 3, [ ], sents )

    def test_first_copy_of_a_repeated_sentence_is_accepted( self ):
        sents = split_sentences( "Same line. Other line. Same line." )
        validate_extraction( "Same line.", 1, [ ], sents )

    def test_stray_before_the_payload_is_rejected( self ):
        with pytest.raises( ExtractionError, match="not after the payload" ):
            validate_extraction( "The timeout is wrong.", 3, [ 1 ], SENTENCES )

    def test_stray_equal_to_the_payload_is_rejected( self ):
        with pytest.raises( ExtractionError, match="not after the payload" ):
            validate_extraction( "Phase one is done.", 1, [ 1 ], SENTENCES )

    def test_stray_out_of_range_is_rejected( self ):
        with pytest.raises( ExtractionError, match="out of range" ):
            validate_extraction( "Phase one is done.", 1, [ 99 ], SENTENCES )

    def test_repeated_stray_is_rejected( self ):
        with pytest.raises( ExtractionError, match="repeated" ):
            validate_extraction( "Phase one is done.", 1, [ 2, 2 ], SENTENCES )

    def test_no_payload_with_a_quote_is_rejected( self ):
        with pytest.raises( ExtractionError, match="no payload" ):
            validate_extraction( "Phase one is done.", NO_PAYLOAD_INDEX, [ ], SENTENCES )

    def test_no_payload_with_strays_is_rejected( self ):
        with pytest.raises( ExtractionError, match="no payload" ):
            validate_extraction( "", NO_PAYLOAD_INDEX, [ 2 ], SENTENCES )

    def test_no_payload_clean_is_accepted( self ):
        validate_extraction( "", NO_PAYLOAD_INDEX, [ ], SENTENCES )

    def test_empty_sentence_list_is_rejected( self ):
        with pytest.raises( ExtractionError, match="empty body" ):
            validate_extraction( "anything", 1, [ ], [ ] )

    def test_case_and_whitespace_differences_are_tolerated( self ):
        # Normalization is deliberate: a model that re-wraps lines or changes case has
        # not paraphrased. Punctuation is NOT normalized away — dropping the final
        # period IS a paraphrase, covered by the sub-clause control above.
        validate_extraction( "  phase   ONE is done.  ", 1, [ ], SENTENCES )


# ══════════════════════════════════════════════════════════════════════════════
# Scoring — and the midcourse correction that made position the whole score
# ══════════════════════════════════════════════════════════════════════════════

class TestStructuralCode:

    @pytest.mark.parametrize( "index,strays,expected", [
        ( 1, 0, "lead_clean" ), ( 1, 1, "lead_one_stray" ),
        ( 1, 2, "mixed" ),      ( 1, 9, "mixed" ),
        ( 2, 0, "mixed" ),      ( 2, 5, "mixed" ),
        ( 3, 0, "late" ),       ( 7, 2, "late" ),
        ( 0, 0, "missing" ),
    ] )
    def test_every_branch( self, index, strays, expected ):
        assert structural_code( index, strays ) == expected

    def test_every_code_has_a_weight( self ):
        for index, strays in ( ( 1, 0 ), ( 1, 1 ), ( 1, 2 ), ( 2, 0 ), ( 3, 0 ), ( 0, 0 ) ):
            assert code_weight( structural_code( index, strays ) ) in ( -2, -1, 0, 1, 2 )

    def test_an_unknown_code_raises_rather_than_degrading( self ):
        with pytest.raises( KeyError ):
            code_weight( "not_a_code" )


class TestPositionWeight:

    @pytest.mark.parametrize( "index,expected", [
        ( 0, -2 ), ( 1, 2 ), ( 2, 1 ), ( 3, -1 ), ( 12, -1 ),
    ] )
    def test_every_branch( self, index, expected ):
        assert position_weight( index ) == expected


class TestMidcourseCorrection:
    """
    Rick, 2026-08-01, after reading the first v2 table: score the grounded half only.

    Measured that day, the position half separated the contrast that DEFINED this bug
    (+2 vs -1, where v1 gave +1 vs +1), and the stray classification then collapsed both
    +2 bodies to 0 by marking evidence and risks as stray. Position is validated against
    the source text; the stray classification is not. So position is the score.
    """

    def test_the_shipped_setting_is_position_only( self ):
        assert CONCISION_ADJUSTMENT_ENABLED is False

    def test_strays_do_not_move_the_score( self ):
        assert directness_weight( 1, 0 ) == directness_weight( 1, 5 ) == 2

    def test_a_leading_verdict_keeps_its_full_credit( self ):
        # This is the regression the correction exists to prevent: under the concision
        # adjustment this same input scored 0.
        assert directness_weight( 1, 2 ) == 2
        assert code_weight( structural_code( 1, 2 ) ) == 0

    @pytest.mark.parametrize( "index", [ 0, 3, 8 ] )
    def test_both_settings_agree_where_no_verdict_leads( self, index ):
        assert directness_weight( index, 0 ) == code_weight( structural_code( index, 0 ) )

    def test_the_concision_path_still_works_when_re_enabled( self ):
        # The path is PARKED, not deleted — the follow-up has to be able to turn it back
        # on without rebuilding it.
        with patch( "cosa.agents.dm_quality_judge.xml_models_v2.CONCISION_ADJUSTMENT_ENABLED", True ):
            assert directness_weight( 1, 1 ) == 1
            assert directness_weight( 1, 2 ) == 0


# ══════════════════════════════════════════════════════════════════════════════
# Schemas — evidence before grade, dash-cased tags, round trips
# ══════════════════════════════════════════════════════════════════════════════

class TestSchemas:

    def test_directness_round_trips_through_xml( self ):
        original = DmDirectnessExtraction( **{
            "first-payload-quote" : "Phase one is done.",
            "first-payload-index" : "1",
            "stray-after-indices" : "2,3",
        } )
        parsed = DmDirectnessExtraction.from_xml( original.to_xml() )
        assert parsed.first_payload_quote == "Phase one is done."
        assert parsed.first_payload_index == "1"
        assert parsed.stray_after_indices == "2,3"

    def test_directness_carries_no_grade_field( self ):
        # The point of the design: the model has no way to state a grade at all.
        assert "grade" not in DmDirectnessExtraction.model_fields
        assert not any( "weight" in f for f in DmDirectnessExtraction.model_fields )

    def test_tone_round_trips_and_maps_to_v1s_table( self ):
        parsed = DmToneJudgement.from_xml(
            DmToneJudgement( **{ "tone-evidence": "owed oracle", "tone": "bad" } ).to_xml() )
        assert parsed.tone_weight() == -1
        assert parsed.tone_emoji()  == "👎"

    def test_tone_evidence_precedes_the_grade_in_generation_order( self ):
        xml = DmToneJudgement.get_example_for_template().to_xml()
        assert xml.index( "tone-evidence" ) < xml.index( "<tone>" )

    def test_unknown_tone_label_degrades_to_meh( self ):
        assert DmToneJudgement( tone="banana" ).tone_weight() == 0

    @pytest.mark.parametrize( "cls", [ DmDirectnessExtraction, DmToneJudgement ] )
    def test_examples_are_well_formed_by_construction( self, cls ):
        cls.from_xml( cls.get_example_for_template().to_xml() )


class TestRepairLayerFieldSets:
    """
    The repair layer rebuilds a response from the fields it is TOLD about and drops the
    rest. Found live 2026-08-01: called with v1's tuple, v2's tone reply matched <tone>
    only, silently lost <tone-evidence>, and the judge reported a graded tone with a
    blank justification. Nothing raised — the XML was well-formed before and after.
    """

    def test_v2_tone_keeps_its_evidence_with_the_right_field_set( self ):
        raw    = "<response><tone-evidence>owed oracle</tone-evidence><tone>bad</tone></response>"
        parsed = DmToneJudgement.from_xml( _repair_llm_xml( raw, TONE_FIELDS ) )
        assert parsed.tone_evidence == "owed oracle"
        assert parsed.tone          == "bad"

    def test_the_wrong_field_set_is_what_loses_the_evidence( self ):
        raw      = "<response><tone-evidence>owed oracle</tone-evidence><tone>bad</tone></response>"
        repaired = _repair_llm_xml( raw )   # v1's default tuple — the bug, pinned
        assert "tone-evidence" not in repaired

    def test_v1_callers_are_unchanged_by_the_new_parameter( self ):
        raw      = "< response >< directness >good</ directness >< tone >meh</ tone ></ response >"
        repaired = _repair_llm_xml( raw )
        assert "<directness>good</directness>" in repaired
        assert "<tone>meh</tone>"              in repaired

    def test_markdown_code_fences_survive_repair( self ):
        # The chat endpoint wraps its answer in ```xml fences; the span extraction
        # already handles it, and this pins that so a future change cannot lose it.
        raw = "```xml\n<response><tone-evidence>x</tone-evidence><tone>good</tone></response>\n```"
        assert DmToneJudgement.from_xml( _repair_llm_xml( raw, TONE_FIELDS ) ).tone == "good"

    def test_directness_fields_survive_repair( self ):
        raw = ( "```xml\n<?xml version=\"1.0\"?>\n<response>"
                "<first-payload-quote>A.</first-payload-quote>"
                "<first-payload-index>1</first-payload-index>"
                "<stray-after-indices>none</stray-after-indices></response>\n```" )
        parsed = DmDirectnessExtraction.from_xml( _repair_llm_xml( raw, DIRECTNESS_FIELDS ) )
        assert parsed.first_payload_index == "1"


# ══════════════════════════════════════════════════════════════════════════════
# The judge — contract, non-answers, and the seam the probe depends on
# ══════════════════════════════════════════════════════════════════════════════

def _judge_with_client( responses ):
    """A v2 judge whose client returns the given texts in order, without a real model."""
    with patch( "cosa.agents.dm_quality_judge.judge_v2.LlmClientFactory" ) as factory:
        client     = MagicMock()
        client.run = MagicMock( side_effect=responses )
        factory.return_value.get_client.return_value = client
        judge = DmQualityJudgeV2( qualitative_enabled=True )
    return judge


_GOOD_DIRECTNESS = ( "<response><first-payload-quote>Phase one is done.</first-payload-quote>"
                     "<first-payload-index>1</first-payload-index>"
                     "<stray-after-indices>2</stray-after-indices></response>" )
_GOOD_TONE       = "<response><tone-evidence>plain words</tone-evidence><tone>good</tone></response>"


class TestJudgeContract:

    def test_returns_v1s_shape_so_the_caller_needs_no_branch( self ):
        judge  = _judge_with_client( [ _GOOD_DIRECTNESS, _GOOD_TONE ] )
        result = judge.judge( BODY )
        assert set( result ) == { "length", "directness", "tone", "overall" }

    def test_a_leading_verdict_scores_the_top_of_the_scale( self ):
        judge  = _judge_with_client( [ _GOOD_DIRECTNESS, _GOOD_TONE ] )
        d      = judge.judge( BODY )[ "directness" ]
        assert d[ "weight" ]          == 2
        assert d[ "position_weight" ] == 2
        assert d[ "stray_count" ]     == 1
        assert "not scored"           in d[ "detail" ]

    def test_length_only_mode_withholds_both_qualitative_dimensions( self ):
        judge  = DmQualityJudgeV2( qualitative_enabled=False )
        result = judge.judge( "Short and to the point." )
        assert result[ "directness" ][ "weight" ] is None
        assert result[ "tone" ][ "weight" ]       is None
        assert result[ "overall" ][ "weight" ]    == result[ "length" ][ "weight" ]

    def test_an_over_length_body_skips_the_model_entirely( self ):
        judge  = _judge_with_client( [ ] )
        result = judge.judge( "word " * 400 )
        assert "too long" in result[ "directness" ][ "detail" ]

    def test_an_unavailable_client_degrades_without_raising( self ):
        with patch( "cosa.agents.dm_quality_judge.judge_v2.LlmClientFactory",
                    side_effect=RuntimeError( "no server" ) ):
            judge = DmQualityJudgeV2( qualitative_enabled=True )
        assert judge.available is False
        result = judge.judge( BODY )
        assert result[ "directness" ][ "detail" ] == "judge unavailable"
        assert result[ "tone" ][ "detail" ]       == "judge unavailable"

    def test_a_body_with_no_sentences_is_an_extraction_failure_not_a_grade( self ):
        judge = _judge_with_client( [ _GOOD_TONE ] )
        d     = judge._grade_directness( "   " )
        assert d[ "detail" ].startswith( _EXTRACTION_FAILED_DETAIL )


class TestNonAnswersStayDistinguishable:
    """
    A real `meh` and a refusal are both weight 0. The probe tells them apart by DETAIL
    alone, so three different silences must never share a string.
    """

    def test_the_extraction_failure_names_itself( self ):
        d = _extraction_failed_dimension( "quote does not equal sentence 1" )
        assert d[ "weight" ]          is None
        assert d[ "position_weight" ] is None
        assert _EXTRACTION_FAILED_DETAIL in d[ "detail" ]

    def test_it_is_not_confusable_with_the_other_two_silences( self ):
        from cosa.agents.dm_quality_judge.judge import (
            _JUDGE_UNAVAILABLE_DETAIL, _TOO_LONG_DETAIL, _QUALITATIVE_OFF_DETAIL )
        detail = _extraction_failed_dimension( "why" )[ "detail" ]
        assert detail != _JUDGE_UNAVAILABLE_DETAIL
        assert detail != _QUALITATIVE_OFF_DETAIL
        assert not detail.startswith( _TOO_LONG_DETAIL )

    def test_the_probe_classifies_it_as_a_non_answer( self ):
        sys.path.insert( 0, os.path.join( os.environ[ "LUPIN_ROOT" ], "src", "tests", "smoke" ) )
        from dm_judge_discrimination_probe import nonanswer_kind, is_measurement, NONANSWER_KINDS
        d = _extraction_failed_dimension( "why" )
        assert nonanswer_kind( d ) == "unverified"
        assert "unverified" in NONANSWER_KINDS
        assert is_measurement( d ) is False

    def test_an_unverifiable_extraction_is_refused_after_exhausting_retries( self ):
        bad   = ( "<response><first-payload-quote>Not in the body.</first-payload-quote>"
                  "<first-payload-index>1</first-payload-index>"
                  "<stray-after-indices>none</stray-after-indices></response>" )
        judge = _judge_with_client( [ bad, bad, bad ] )
        with patch( "cosa.agents.dm_quality_judge.judge_v2.time.sleep" ):
            d = judge._grade_directness( BODY )
        assert d[ "detail" ].startswith( _EXTRACTION_FAILED_DETAIL )
        assert d[ "position_weight" ] is None

    def test_a_transient_failure_recovers_on_retry( self ):
        judge = _judge_with_client( [ "garbage <<<", _GOOD_DIRECTNESS ] )
        with patch( "cosa.agents.dm_quality_judge.judge_v2.time.sleep" ):
            d = judge._grade_directness( BODY )
        assert d[ "weight" ] == 2

    def test_a_degenerate_repeated_character_response_never_reaches_the_parser( self ):
        judge = _judge_with_client( [ "0" * 200, "0" * 200, "0" * 200 ] )
        with patch( "cosa.agents.dm_quality_judge.judge_v2.time.sleep" ):
            d = judge._grade_directness( BODY )
        assert d[ "detail" ] == "judge unavailable"

    def test_tone_falls_back_when_every_attempt_fails( self ):
        judge = _judge_with_client( [ "junk", "junk", "junk" ] )
        with patch( "cosa.agents.dm_quality_judge.judge_v2.time.sleep" ):
            t = judge._grade_tone( BODY )
        assert t[ "detail" ] == "judge unavailable"


class TestANonAnswerNeverWearsAGradesFace:
    """
    Rick, 2026-08-01: *"we cannot conflate none with `meh` or 🤷"*.

    🤷 is not a neutral shrug here — it is the emoji of `meh`, weight 0, a real grade on
    the scale. Every non-answer used to return it, so a dimension the judge had never run
    on looked exactly like one it had graded neutrally. The weight side was fixed first
    (all non-answers are None, so nothing can average them); this is the same hole on the
    surface a human actually reads.
    """

    def test_no_non_answer_emoji_is_a_grade_emoji( self ):
        from cosa.agents.dm_quality_judge.xml_models import NONANSWER_EMOJI, WEIGHT_TO_EMOJI
        assert not ( set( NONANSWER_EMOJI.values() ) & set( WEIGHT_TO_EMOJI.values() ) )

    def test_meh_specifically_is_not_reachable_as_a_non_answer( self ):
        from cosa.agents.dm_quality_judge.xml_models import NONANSWER_EMOJI, grade_emoji
        assert grade_emoji( "meh" ) == "🤷"
        assert "🤷" not in NONANSWER_EMOJI.values()

    def test_the_four_silences_have_four_distinct_faces( self ):
        from cosa.agents.dm_quality_judge.xml_models import NONANSWER_EMOJI
        assert len( set( NONANSWER_EMOJI.values() ) ) == len( NONANSWER_EMOJI ) == 4

    @pytest.mark.parametrize( "builder,kind", [
        ( lambda: __import__( "cosa.agents.dm_quality_judge.judge", fromlist=[ "x" ] )._fallback_dimension(), "unavailable" ),
        ( lambda: __import__( "cosa.agents.dm_quality_judge.judge", fromlist=[ "x" ] )._withheld_dimension(), "withheld" ),
        ( lambda: __import__( "cosa.agents.dm_quality_judge.judge", fromlist=[ "x" ] )._too_long_dimension( 300 ), "too_long" ),
        ( lambda: _extraction_failed_dimension( "why" ), "unverified" ),
    ] )
    def test_every_non_answer_path_returns_none_and_its_own_face( self, builder, kind ):
        from cosa.agents.dm_quality_judge.xml_models import NONANSWER_EMOJI
        d = builder()
        assert d[ "weight" ] is None
        assert d[ "emoji" ]  == NONANSWER_EMOJI[ kind ]

    def test_an_over_length_dm_reports_length_only_at_full_penalty( self ):
        # Rick's ruling: past the ceiling it is "too long, I don't care how well it's
        # written." Length's own bucket already delivers that (251+ → −2); Overall must
        # equal it rather than being softened by two ungraded dimensions.
        judge  = DmQualityJudgeV2( qualitative_enabled=True )
        result = judge.judge( " ".join( [ "word" ] * 300 ) )
        assert result[ "length" ][ "weight" ]  == -2
        assert result[ "overall" ][ "weight" ] == -2
        assert "Length only" in result[ "overall" ][ "note" ]


class TestVersionFactory:

    def test_explicit_version_1_builds_v1( self ):
        assert isinstance( get_dm_quality_judge( version=1, qualitative_enabled=False ),
                           DmQualityJudge )

    def test_explicit_version_2_builds_v2( self ):
        assert isinstance( get_dm_quality_judge( version=2, qualitative_enabled=False ),
                           DmQualityJudgeV2 )

    def test_an_unknown_version_falls_back_to_v1_rather_than_failing_a_dm_send( self ):
        assert isinstance( get_dm_quality_judge( version=99, qualitative_enabled=False ),
                           DmQualityJudge )

    def test_an_unreadable_config_falls_back_to_v1( self ):
        with patch( "cosa.config.configuration_manager.ConfigurationManager",
                    side_effect=RuntimeError( "no config" ) ):
            assert isinstance( get_dm_quality_judge( qualitative_enabled=False ), DmQualityJudge )

    def test_the_default_version_is_1( self ):
        assert DEFAULT_JUDGE_VERSION == 1

    def test_kwargs_reach_the_constructor_so_the_probe_can_inject_its_seam( self ):
        # Without this the probe would run at the operator's ambient toggle — which is
        # OFF — and would measure withheld non-answers while reporting a pass.
        judge = get_dm_quality_judge( version=2, qualitative_enabled=True )
        assert judge.qualitative_enabled is True


class TestDetailLines:
    """
    The detail string is not decoration — it is how the probe tells a refusal from a
    real grade, and how a human reads why a DM scored what it did.
    """

    def _detail( self, structure, index, strays, sentences=None ):
        judge = DmQualityJudgeV2( qualitative_enabled=False )
        return judge._directness_detail( structure, index, strays, sentences or SENTENCES )

    def test_missing_says_no_sentence_qualified( self ):
        assert "no sentence states" in self._detail( "missing", 0, [ ] )

    def test_a_leading_verdict_with_no_strays_says_so_plainly( self ):
        assert self._detail( "lead_clean", 1, [ ] ) == "the verdict leads"

    def test_a_later_verdict_names_its_position( self ):
        assert "is sentence 3 of 3" in self._detail( "late", 3, [ ] )

    def test_strays_are_reported_as_not_scored_while_the_correction_stands( self ):
        detail = self._detail( "mixed", 1, [ 2, 3 ] )
        assert "2 stray sentence(s)" in detail
        assert "not scored"          in detail

    def test_strays_drop_the_not_scored_note_when_re_enabled( self ):
        with patch( "cosa.agents.dm_quality_judge.judge_v2.CONCISION_ADJUSTMENT_ENABLED", True ):
            assert "not scored" not in self._detail( "mixed", 1, [ 2, 3 ] )


class TestSmokeTestsRun:
    """
    The modules' own quick_smoke_test blocks are executable documentation. v1 pins its
    smoke test the same way (test_dm_quality_judge.py), so v2 does too — an example that
    has silently stopped working teaches the wrong thing.
    """

    def test_models_smoke_test_passes( self ):
        from cosa.agents.dm_quality_judge.xml_models_v2 import quick_smoke_test
        assert quick_smoke_test() is True

    def test_judge_smoke_test_passes( self ):
        from cosa.agents.dm_quality_judge.judge_v2 import quick_smoke_test
        assert quick_smoke_test() is True

    def test_the_smoke_helper_itself_fails_when_nothing_raises( self ):
        # Auditing the instrument: _assert_raises must not pass a control silently.
        from cosa.agents.dm_quality_judge.xml_models_v2 import _assert_raises
        with pytest.raises( AssertionError, match="expected ExtractionError" ):
            _assert_raises( lambda: None )


class TestSharedV1PathsReachedByV2:
    """
    v2 imports v1's deterministic helpers rather than copying them, so v2's suite is
    where several of them finally get exercised. These close the package's remaining
    coverage gaps; the behaviour they pin is v1's, unchanged.
    """

    def test_repair_returns_none_when_no_known_field_is_present( self ):
        from cosa.agents.dm_quality_judge.judge import _extract_unclosed_fields
        assert _extract_unclosed_fields( "<response>nothing useful</response>" ) is None

    def test_repair_handles_a_span_with_no_wrapper_tags( self ):
        from cosa.agents.dm_quality_judge.judge import _extract_unclosed_fields
        recovered = _extract_unclosed_fields( "<tone>good</tone>", ( "tone", ) )
        assert recovered == "<response><tone>good</tone></response>"

    def test_repair_strips_only_the_wrapper_it_finds( self ):
        from cosa.agents.dm_quality_judge.judge import _extract_unclosed_fields
        assert _extract_unclosed_fields( "<response><tone>good", ( "tone", ) ) == \
               "<response><tone>good</tone></response>"

    def test_the_qualitative_toggle_defaults_off_when_config_is_unreadable( self ):
        from cosa.agents.dm_quality_judge.judge import _get_qualitative_enabled
        with patch( "cosa.config.configuration_manager.ConfigurationManager",
                    side_effect=RuntimeError( "no config" ) ):
            assert _get_qualitative_enabled() is False

    @pytest.mark.parametrize( "configured", [ True, False ] )
    def test_the_qualitative_toggle_returns_what_the_config_says( self, configured ):
        # The config manager is STUBBED rather than read: a test that asserted the
        # ambient INI value would flip with an operator's toggle and would be measuring
        # the machine it runs on, not the code.
        from cosa.agents.dm_quality_judge.judge import _get_qualitative_enabled
        stub = MagicMock()
        stub.return_value.get.return_value = configured
        with patch( "cosa.config.configuration_manager.ConfigurationManager", stub ):
            assert _get_qualitative_enabled() is configured

    def test_v1_length_only_mode_withholds_both_dimensions( self ):
        judge  = DmQualityJudge( qualitative_enabled=False )
        result = judge.judge( "Short and to the point." )
        assert result[ "directness" ][ "weight" ] is None
        assert result[ "tone" ][ "weight" ]       is None

    def test_v1_garbage_guard_short_circuits_before_the_parser( self ):
        with patch( "cosa.agents.dm_quality_judge.judge.LlmClientFactory" ) as factory:
            client     = MagicMock()
            client.run = MagicMock( return_value="0" * 200 )
            factory.return_value.get_client.return_value = client
            judge = DmQualityJudge( qualitative_enabled=True )
        with patch( "cosa.agents.dm_quality_judge.judge.time.sleep" ):
            directness, tone = judge._grade_qualitative( BODY )
        assert directness[ "detail" ] == "judge unavailable"
        assert tone[ "detail" ]       == "judge unavailable"

    def test_v1_module_smoke_test_passes( self ):
        from cosa.agents.dm_quality_judge.judge import quick_smoke_test
        assert quick_smoke_test() is True
