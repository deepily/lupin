#!/usr/bin/env python3
"""
Unit tests for the DM Quality Judge (Phase 2 of the DM Verbosity Reduction plan,
Rick 2026-07-31 — src/rnd/v0.1.9/2026.07.31-dm-verbosity-reduction/).

Covers, following the LlmAnswerVerifier/VerificationResponse test conventions:
    - DmQualityJudgeResponse.from_xml() parsing + grade-label→weight mapping
    - the Python-only Length bucketing table (one test per boundary)
    - the round-half-up combination math (lenient ties + Rick's worked example)
    - DmQualityJudge.judge(): retry/backoff, safe-fallback, unavailable-client

No real LLM call is made — the judge's client is replaced with a MagicMock.
"""
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.agents.io_models.utils.util_xml_pydantic import XMLParsingError
from cosa.agents.dm_quality_judge.xml_models import (
    DmQualityJudgeResponse, GRADE_TABLE, normalize_grade_label,
    grade_weight, grade_emoji,
)
from cosa.agents.dm_quality_judge.judge import (
    DmQualityJudge, length_bucket, round_half_up, combine_overall,
    _JUDGE_UNAVAILABLE_DETAIL, _repair_llm_xml, QUALITATIVE_WORD_LIMIT,
)

_FIXTURE_DIR = os.path.join( _src_path, "tests", "unit", "fixtures", "dm_judge" )


def _load_fixture( name ):
    with open( os.path.join( _FIXTURE_DIR, name ) ) as f:
        return f.read()


def _mistral_reachable():
    import socket
    try:
        with socket.create_connection( ( "192.168.1.21", 3001 ), timeout=2 ):
            return True
    except OSError:
        return False


_VALID_XML = (
    "<response>"
    "<directness>good</directness>"
    "<directness_note>leads with the verdict</directness_note>"
    "<tone>exemplary</tone>"
    "<tone_note>plain colleague voice</tone_note>"
    "</response>"
)


# ═════════════════════════════════════════════════════════════════════════════
# DmQualityJudgeResponse — parsing + label→weight/emoji mapping
# ═════════════════════════════════════════════════════════════════════════════

class TestDmQualityJudgeResponse:

    def test_valid_xml_parses( self ):
        r = DmQualityJudgeResponse.from_xml( _VALID_XML )
        assert r.directness == "good"
        assert r.tone       == "exemplary"
        assert r.directness_note == "leads with the verdict"

    def test_malformed_xml_raises_xml_parsing_error( self ):
        with pytest.raises( XMLParsingError ):
            DmQualityJudgeResponse.from_xml( "not xml at all <<<" )

    def test_empty_xml_raises_xml_parsing_error( self ):
        with pytest.raises( XMLParsingError ):
            DmQualityJudgeResponse.from_xml( "   " )

    @pytest.mark.parametrize( "label,weight,emoji", [
        ( "terrible",          -2, "😞" ),
        ( "needs_improvement", -1, "👎" ),
        ( "meh",                0, "🤷" ),
        ( "good",               1, "👍" ),
        ( "exemplary",          2, "⭐" ),
    ] )
    def test_grade_label_maps_to_weight_and_emoji_both_dimensions( self, label, weight, emoji ):
        r = DmQualityJudgeResponse( directness=label, tone=label )
        assert r.directness_weight() == weight
        assert r.tone_weight()       == weight
        assert r.directness_emoji()  == emoji
        assert r.tone_emoji()        == emoji

    def test_unknown_label_degrades_to_meh( self ):
        r = DmQualityJudgeResponse( directness="banana", tone="" )
        assert r.directness_weight() == 0
        assert r.tone_weight()       == 0
        assert r.directness_emoji()  == "🤷"

    @pytest.mark.parametrize( "raw,canonical", [
        ( "Needs Improvement", "needs_improvement" ),
        ( "needs-improvement", "needs_improvement" ),
        ( "  GOOD  ",          "good" ),
        ( None,                "meh" ),
        ( "",                  "meh" ),
    ] )
    def test_label_normalization( self, raw, canonical ):
        assert normalize_grade_label( raw ) == canonical

    def test_module_helpers_match_table( self ):
        for label, ( weight, emoji ) in GRADE_TABLE.items():
            assert grade_weight( label ) == weight
            assert grade_emoji( label )  == emoji

    def test_smoke( self ):
        assert DmQualityJudgeResponse.quick_smoke_test( debug=False )


# ═════════════════════════════════════════════════════════════════════════════
# Length bucketing — one test per boundary (item 1, row-5 = 251+)
# ═════════════════════════════════════════════════════════════════════════════

class TestLengthBucket:

    @pytest.mark.parametrize( "words,weight,emoji", [
        (   0,  2, "⭐" ),
        (  60,  2, "⭐" ),
        (  61,  1, "👍" ),
        (  90,  1, "👍" ),
        (  91,  0, "🤷" ),
        ( 150,  0, "🤷" ),
        ( 151, -1, "👎" ),
        ( 250, -1, "👎" ),
        ( 251, -2, "😞" ),
        ( 999, -2, "😞" ),
    ] )
    def test_boundaries( self, words, weight, emoji ):
        b = length_bucket( words )
        assert b[ "weight" ] == weight
        assert b[ "emoji" ]  == emoji

    def test_detail_names_the_word_count_and_target( self ):
        assert length_bucket( 187 )[ "detail" ] == "187 words, target ~60"


# ═════════════════════════════════════════════════════════════════════════════
# round_half_up + combine_overall — the combination math (item 4)
# ═════════════════════════════════════════════════════════════════════════════

class TestCombinationMath:

    @pytest.mark.parametrize( "x,expected", [
        (  0.5,  1 ),   # tie rounds UP
        ( -0.5,  0 ),   # tie rounds UP (toward 0, the lenient side)
        (  1.5,  2 ),
        ( -1.5, -1 ),
        (  0.0,  0 ),
        (  0.49, 0 ),
        ( -0.51, -1 ),
    ] )
    def test_round_half_up( self, x, expected ):
        assert round_half_up( x ) == expected

    def test_ricks_worked_example_terrible_length_exemplary_qual_is_meh( self ):
        """length=😞(−2), directness=⭐(+2), tone=⭐(+2) → qualitative=2 →
        round_half_up(0.5*−2 + 0.5*2)=round_half_up(0)=0 → 🤷."""
        overall = combine_overall( -2, 2, 2, "300 words, target ~60" )
        assert overall[ "weight" ] == 0
        assert overall[ "emoji" ]  == "🤷"

    def test_length_boundary_tie_rounds_up( self ):
        """length=+1, qualitative=0 → raw=0.5 → round_half_up → +1 (👍)."""
        overall = combine_overall( 1, 0, 0, "70 words, target ~60" )
        assert overall[ "weight" ] == 1

    def test_negative_boundary_tie_rounds_up_toward_zero( self ):
        """length=−1, qualitative=0 → raw=−0.5 → round_half_up → 0 (🤷)."""
        overall = combine_overall( -1, 0, 0, "200 words, target ~60" )
        assert overall[ "weight" ] == 0

    def test_categories_are_equal_weight_not_three_flat_dimensions( self ):
        """A great length must not be outvoted 2-to-1 by two weak qualitative dims:
        length=+2, directness=−2, tone=−2 → qualitative=−2 → raw=0 → 🤷, NOT the
        −0.67 a flat 3-way average would give."""
        overall = combine_overall( 2, -2, -2, "10 words, target ~60" )
        assert overall[ "weight" ] == 0

    def test_overall_weight_is_clamped_to_range( self ):
        assert combine_overall(  2,  2,  2, "5 words, target ~60" )[ "weight" ] ==  2
        assert combine_overall( -2, -2, -2, "5 words, target ~60" )[ "weight" ] == -2

    def test_note_is_python_templated_naming_the_drag( self ):
        low_length = combine_overall( -2, 2, 2, "300 words, target ~60" )
        assert "Length pulled this down" in low_length[ "note" ]
        assert "300 words" in low_length[ "note" ]
        low_qual = combine_overall( 2, -2, -2, "10 words, target ~60" )
        assert "directness/tone dragged it down" in low_qual[ "note" ]
        balanced = combine_overall( 1, 1, 1, "70 words, target ~60" )
        assert "Balanced" in balanced[ "note" ]


# ═════════════════════════════════════════════════════════════════════════════
# DmQualityJudge.judge() — retry, fallback, unavailable (item 2)
# ═════════════════════════════════════════════════════════════════════════════

def _make_judge( run_behaviour=None, available=True ):
    """
    Build a DmQualityJudge with its LLM client replaced by a MagicMock.

    run_behaviour: a return_value (str) OR a side_effect (list/exception) for
    client.run. available: sets _available (False → the unavailable path).
    """
    judge = DmQualityJudge( debug=False )
    client = MagicMock()
    if isinstance( run_behaviour, ( list, Exception ) ) or callable( run_behaviour ):
        client.run.side_effect = run_behaviour
    else:
        client.run.return_value = run_behaviour
    judge._client    = client
    judge._available = available
    return judge, client


class TestDmQualityJudge:

    def test_length_is_always_python_computed( self ):
        """Even with the client unavailable, Length is graded from the word count."""
        judge, _ = _make_judge( available=False )
        result = judge.judge( "one two three four five" )   # 5 words → ⭐/+2
        assert result[ "length" ][ "weight" ] == 2

    def test_unavailable_client_returns_meh_qualitative_never_raises( self ):
        judge, client = _make_judge( available=False )
        result = judge.judge( "short body" )
        assert result[ "directness" ][ "weight" ] == 0
        assert result[ "tone" ][ "weight" ] == 0
        assert result[ "directness" ][ "detail" ] == _JUDGE_UNAVAILABLE_DETAIL
        client.run.assert_not_called()

    def test_happy_path_full_shape( self ):
        judge, _ = _make_judge( run_behaviour=_VALID_XML )
        result = judge.judge( "lead with the verdict; two supporting facts." )
        assert set( result.keys() ) == { "length", "directness", "tone", "overall" }
        assert result[ "directness" ][ "weight" ] == 1   # good
        assert result[ "tone" ][ "weight" ] == 2         # exemplary
        assert result[ "directness" ][ "detail" ] == "leads with the verdict"

    @patch( "cosa.agents.dm_quality_judge.judge.time.sleep", return_value=None )
    def test_retry_then_succeed( self, _sleep ):
        """Two transient failures then a valid parse — judge recovers on attempt 3."""
        judge, client = _make_judge( run_behaviour=[ RuntimeError( "empty" ), RuntimeError( "truncated" ), _VALID_XML ] )
        result = judge.judge( "body" )
        assert client.run.call_count == 3
        assert result[ "tone" ][ "weight" ] == 2

    @patch( "cosa.agents.dm_quality_judge.judge.time.sleep", return_value=None )
    def test_exhausted_retries_return_fallback_never_raises( self, _sleep ):
        judge, client = _make_judge( run_behaviour=RuntimeError( "always down" ) )
        result = judge.judge( "body" )
        assert client.run.call_count == 3
        assert result[ "directness" ][ "weight" ] == 0
        assert result[ "tone" ][ "detail" ] == _JUDGE_UNAVAILABLE_DETAIL
        # length + overall still computed
        assert "overall" in result

    @patch( "cosa.agents.dm_quality_judge.judge.time.sleep", return_value=None )
    def test_malformed_xml_is_treated_as_a_transient_failure( self, _sleep ):
        judge, client = _make_judge( run_behaviour="<garbage>no closing" )
        result = judge.judge( "body" )
        assert client.run.call_count == 3      # retried, then fell back
        assert result[ "directness" ][ "weight" ] == 0


class TestDmQualityJudgeConstruction:
    """The client-build branches of __init__ + the `available` property."""

    @patch( "cosa.agents.dm_quality_judge.judge.LlmClientFactory" )
    def test_available_true_when_factory_succeeds_debug_on( self, MockFactory ):
        MockFactory.return_value.get_client.return_value = MagicMock()
        judge = DmQualityJudge( debug=True )
        assert judge.available is True

    @patch( "cosa.agents.dm_quality_judge.judge.LlmClientFactory" )
    def test_available_true_when_factory_succeeds_debug_off( self, MockFactory ):
        MockFactory.return_value.get_client.return_value = MagicMock()
        judge = DmQualityJudge( debug=False )
        assert judge.available is True

    @patch( "cosa.agents.dm_quality_judge.judge.LlmClientFactory" )
    def test_available_false_when_factory_raises( self, MockFactory ):
        MockFactory.return_value.get_client.side_effect = RuntimeError( "no server" )
        judge = DmQualityJudge( debug=False )
        assert judge.available is False


def test_judge_module_smoke():
    from cosa.agents.dm_quality_judge.judge import quick_smoke_test
    assert quick_smoke_test()


# ═════════════════════════════════════════════════════════════════════════════
# _repair_llm_xml — tolerate the live 24B GPTQ model's sloppy XML (bug a5f7b36d)
# ═════════════════════════════════════════════════════════════════════════════

class TestRepairLlmXml:

    def test_drops_unclosed_prolog_without_eating_content( self ):
        raw = '<?xml version="1.0" encoding "utf-8" ? <response><directness>good</directness></response>'
        out = _repair_llm_xml( raw )
        assert out.startswith( "<response>" )
        assert "<?xml" not in out

    def test_collapses_spaced_tags( self ):
        raw = "< response > < directness > good < / directness > </response>"
        out = _repair_llm_xml( raw )
        assert "<response>" in out and "<directness>" in out and "</directness>" in out
        assert "< " not in out and " >" not in out

    def test_collapses_multi_word_and_spaced_underscore_tags( self ):
        assert "<directness_note>"  in _repair_llm_xml( "<response>< directness note >x</ directness note ></response>" )
        assert "<directness_note>"  in _repair_llm_xml( "<response>< directness _ note >x</ directness _ note ></response>" )

    def test_extracts_only_the_response_span_dropping_trailing_stop( self ):
        raw = "<response><tone>good</tone></response></stop> trailing junk"
        out = _repair_llm_xml( raw )
        assert out == "<response><tone>good</tone></response>"

    def test_wraps_bare_siblings_when_root_missing( self ):
        """bug 46690a76: model drops <response> on long input → wrap the siblings."""
        raw = "<directness>good</directness> <tone>meh</tone>"
        out = _repair_llm_xml( raw )
        assert out.startswith( "<response>" ) and out.endswith( "</response>" )
        assert "<directness>good</directness>" in out
        DmQualityJudgeResponse.from_xml( out )   # now parseable

    def test_strips_orphan_close_and_synthesizes_single_root( self ):
        raw = ( "<directness>good</directness> <directness_note>x</directness_note> "
                "<tone>meh</tone> <tone_note>y</tone_note> </response>" )
        out = _repair_llm_xml( raw )
        assert out.count( "<response>" ) == 1 and out.count( "</response>" ) == 1
        parsed = DmQualityJudgeResponse.from_xml( out )
        assert parsed.directness == "good"

    def test_unrecoverable_output_returned_unwrapped_so_parse_fails( self ):
        """No known child tags → nothing to wrap → from_xml raises → judge falls back."""
        out = _repair_llm_xml( "totally not xml, no tags at all" )
        assert "<response>" not in out
        with pytest.raises( XMLParsingError ):
            DmQualityJudgeResponse.from_xml( out )

    def test_open_child_without_close_is_unrecoverable( self ):
        """A child open tag with no matching close (last_end == -1) → not wrapped."""
        out = _repair_llm_xml( "<directness>good" )
        assert not out.startswith( "<response>" )


# ═════════════════════════════════════════════════════════════════════════════
# Captured-Mistral fixtures — Krishna's acceptance bar: the SAME real malformed
# response must FAIL pre-fix (raw parse) and PASS post-fix (repaired parse).
# These fixtures are verbatim live captures, not synthetic XML.
# ═════════════════════════════════════════════════════════════════════════════

# ALL four captures — used for the _repair_llm_xml PARSER regression (raw fails,
# repaired parses). maria_raw is the long-input root-drop case (bug 46690a76).
_PARSER_FIXTURES = [
    "malformed_mistral_exemplary.txt",
    "malformed_mistral_buried.txt",
    "malformed_mistral_jargon.txt",
    "malformed_mistral_maria_raw.txt",
]

# The SHORT/medium captures only — these are LLM-graded (≤ QUALITATIVE_WORD_LIMIT),
# so a grade VALUE can be asserted. maria_raw is EXCLUDED: at 527 words it is
# threshold-gated (never LLM-graded), and asserting its parroted "good" was exactly
# the false-green Krishna caught (bug 2a41e141) — so no grade assertion on it.
_JUDGE_FIXTURES = [
    ( "malformed_mistral_exemplary.txt", 1 ),   # verdict-first body → directness "good" (+1)
    ( "malformed_mistral_buried.txt",    0 ),   # rambling body → "meh" (0)
    ( "malformed_mistral_jargon.txt",    0 ),   # jargon-heavy body → "meh"/"meah"→meh (0)
]


class TestCapturedMistralFixtures:

    @pytest.mark.parametrize( "fname", _PARSER_FIXTURES )
    def test_raw_capture_fails_to_parse_pre_fix( self, fname ):
        """PRE-FIX proof: the raw captured Mistral output does NOT parse — this is
        exactly why every qualitative grade fell back to 🤷/0."""
        with pytest.raises( XMLParsingError ):
            DmQualityJudgeResponse.from_xml( _load_fixture( fname ) )

    @pytest.mark.parametrize( "fname", _PARSER_FIXTURES )
    def test_repaired_capture_parses_post_fix( self, fname ):
        """POST-FIX proof: _repair_llm_xml makes the SAME capture PARSE (spaced-tag +
        root-synthesis). Parser regression only — no grade-VALUE assertion on the
        long maria case (its grade is a parrot, not truth — bug 2a41e141)."""
        parsed = DmQualityJudgeResponse.from_xml( _repair_llm_xml( _load_fixture( fname ) ) )
        assert parsed.directness in GRADE_TABLE or parsed.directness_weight() in ( -2, -1, 0, 1, 2 )

    @pytest.mark.parametrize( "fname,exp_directness_weight", _JUDGE_FIXTURES )
    def test_judge_grades_short_fixture_non_fallback( self, fname, exp_directness_weight ):
        """End-to-end through the judge on SHORT captures: a real NON-fallback grade
        (pre-fix this was 🤷/0 'judge unavailable'). Judged with a short body so the
        150-word ceiling does not gate it."""
        judge, _client = _make_judge( run_behaviour=_load_fixture( fname ) )
        result = judge.judge( "short body" )
        assert result[ "directness" ][ "detail" ] != _JUDGE_UNAVAILABLE_DETAIL
        assert result[ "directness" ][ "weight" ] == exp_directness_weight

    def test_maria_raw_is_the_root_synthesis_parser_regression( self ):
        """maria_raw's role (per Krishna): the root-synthesis parser regression — the
        model dropped <response> on this long input, and _repair_llm_xml rebuilds it."""
        raw = _load_fixture( "malformed_mistral_maria_raw.txt" )
        with pytest.raises( XMLParsingError ):
            DmQualityJudgeResponse.from_xml( raw )                       # raw: multi-root reject
        repaired = _repair_llm_xml( raw )
        assert repaired.startswith( "<response>" ) and repaired.endswith( "</response>" )
        DmQualityJudgeResponse.from_xml( repaired )                     # now parses

    def test_fallback_still_intact_for_unrepairable_garbage( self ):
        """Genuinely unparseable output still degrades to 🤷/0 and the judge never
        raises (the DM still sends)."""
        judge, _client = _make_judge( run_behaviour="totally not xml, no tags at all" )
        with patch( "cosa.agents.dm_quality_judge.judge.time.sleep", return_value=None ):
            result = judge.judge( "short body" )
        assert result[ "directness" ][ "weight" ] == 0
        assert result[ "directness" ][ "detail" ] == _JUDGE_UNAVAILABLE_DETAIL


class TestQualitativeWordCeiling:
    """bug 2a41e141: past QUALITATIVE_WORD_LIMIT the LLM is skipped — honest 🤷/0 on the
    qualitative dims, while Length still penalizes the verbosity."""

    def test_long_body_skips_llm_and_returns_too_long_fallback( self ):
        judge, client = _make_judge( run_behaviour="<response><directness>exemplary</directness><tone>exemplary</tone></response>" )
        long_body = " ".join( [ "word" ] * 300 )                        # 300 words → past the ceiling AND length 😞/−2
        result = judge.judge( long_body )
        client.run.assert_not_called()                                  # LLM never invoked
        assert result[ "directness" ][ "weight" ] == 0
        assert result[ "tone" ][ "weight" ]       == 0
        assert "too long" in result[ "directness" ][ "detail" ]
        assert result[ "length" ][ "weight" ]     == -2                 # verbosity still penalized

    def test_body_at_limit_is_still_graded( self ):
        judge, client = _make_judge( run_behaviour="<response><directness>good</directness><tone>good</tone></response>" )
        body = " ".join( [ "word" ] * QUALITATIVE_WORD_LIMIT )
        result = judge.judge( body )
        client.run.assert_called()                                      # at the limit → still judged
        assert result[ "directness" ][ "weight" ] == 1


class TestConcreteExampleNotPlaceholder:
    """The prompt example must be CONCRETE — a `[one of: ...]` placeholder is what
    the 24B model echoed as literal malformed XML (bug a5f7b36d)."""

    def test_example_carries_no_bracket_placeholder( self ):
        ex = DmQualityJudgeResponse.get_example_for_template()
        for field in ( ex.directness, ex.directness_note, ex.tone, ex.tone_note ):
            assert "[" not in field and "]" not in field

    def test_example_uses_real_labels_and_two_differ( self ):
        ex = DmQualityJudgeResponse.get_example_for_template()
        assert ex.directness_weight() in ( -2, -1, 0, 1, 2 )
        assert ex.tone_weight()       in ( -2, -1, 0, 1, 2 )
        assert ex.directness != ex.tone   # forces the model to choose, not parrot


class TestMeahAlias:
    def test_meah_maps_to_meh( self ):
        assert normalize_grade_label( "meah" ) == "meh"
        assert normalize_grade_label( " Meah " ) == "meh"
        assert grade_weight( "meah" ) == 0


@pytest.mark.skipif( not _mistral_reachable(), reason="live Mistral :3001 unreachable" )
class TestLiveMistralRegression:
    """The gap that let bug a5f7b36d ship: unit tests fed hand-written XML and never
    hit the real endpoint. This exercises the LIVE model end-to-end (skipped when
    :3001 is unreachable so the offline unit gate stays green)."""

    def test_live_short_exemplary_body_grades_non_fallback( self ):
        judge  = DmQualityJudge()
        result = judge.judge( "Phase 1 done, green. 89 tests pass. Not committed — holding your gate." )
        assert result[ "directness" ][ "detail" ] != _JUDGE_UNAVAILABLE_DETAIL
        assert result[ "tone" ][ "detail" ]       != _JUDGE_UNAVAILABLE_DETAIL
        assert set( result.keys() ) == { "length", "directness", "tone", "overall" }

    def test_live_discrimination_good_vs_bad_diverge( self ):
        """Krishna req #2: on short/medium DMs the grades ACTUALLY diverge — a
        verdict-first DM must out-score a rambling no-verdict one on directness. This
        is the anti-parrot proof: byte-identical grades would fail here."""
        judge = DmQualityJudge()
        good  = judge.judge( "Phase 1 done, green. 89 tests pass. Not committed — holding your gate." )
        bad   = judge.judge(
            "So, quick thought, no rush at all, but I was sort of maybe wondering if we could perhaps "
            "chat about the queue thing sometime when you get a moment, just flagging it is on my mind."
        )
        assert good[ "directness" ][ "weight" ] > bad[ "directness" ][ "weight" ]

    def test_live_maria_raw_is_length_gated_not_parroted( self ):
        """bug 2a41e141 end-to-end: the 527-word reference DM is PAST the qualitative
        ceiling, so it returns the honest 'too long' 🤷/0 (never the parroted 'good'),
        while Length still penalizes its verbosity at 😞/−2."""
        import cosa.utils.util as cu
        maria  = cu.get_file_as_string(
            cu.get_project_root() + "/src/rnd/v0.1.9/2026.07.31-dm-verbosity-reduction/dm-maria-raw.txt"
        )
        result = DmQualityJudge().judge( maria )
        assert result[ "directness" ][ "weight" ] == 0
        assert "too long" in result[ "directness" ][ "detail" ]
        assert result[ "length" ][ "weight" ] == -2


# ═════════════════════════════════════════════════════════════════════════════
# dm.py wiring — the toggle read + _maybe_grade_dm_quality gate
# ═════════════════════════════════════════════════════════════════════════════

class TestMaybeGradeDmQualityWiring:

    def setup_method( self ):
        import cosa.rest.routers.dm as dm
        dm.reset_dm_quality_audit()
        dm._dm_quality_judge = None

    def teardown_method( self ):
        import cosa.rest.routers.dm as dm
        dm._dm_quality_judge = None

    @patch( "cosa.rest.routers.dm.get_dm_quality_judgment_enabled", return_value=False )
    def test_toggle_off_returns_none_and_does_not_tally( self, _enabled ):
        import cosa.rest.routers.dm as dm
        assert dm._maybe_grade_dm_quality( "body" ) is None
        assert dm.get_dm_quality_audit()[ "count" ] == 0

    @patch( "cosa.agents.dm_quality_judge.judge.DmQualityJudge" )
    @patch( "cosa.rest.routers.dm.get_dm_quality_judgment_enabled", return_value=True )
    def test_toggle_on_builds_grades_and_records( self, _enabled, MockJudge ):
        import cosa.rest.routers.dm as dm
        grade = {
            "length"     : { "weight": 2 },
            "directness" : { "weight": 1 },
            "tone"       : { "weight": 0 },
            "overall"    : { "weight": 1 },
        }
        MockJudge.return_value.judge.return_value = grade
        out = dm._maybe_grade_dm_quality( "short body" )
        assert out == grade
        assert dm.get_dm_quality_audit()[ "count" ] == 1
        # lazy singleton: built exactly once, reused thereafter
        assert dm._dm_quality_judge is MockJudge.return_value
        dm._maybe_grade_dm_quality( "another" )
        assert MockJudge.call_count == 1


class TestQualityToggleRead:

    @patch( "cosa.config.configuration_manager.ConfigurationManager" )
    def test_returns_true_when_configured_true( self, MockCM ):
        MockCM.return_value.get.return_value = True
        from cosa.rest.routers.dm import get_dm_quality_judgment_enabled
        assert get_dm_quality_judgment_enabled() is True

    @patch( "cosa.config.configuration_manager.ConfigurationManager" )
    def test_returns_false_when_configured_false( self, MockCM ):
        MockCM.return_value.get.return_value = False
        from cosa.rest.routers.dm import get_dm_quality_judgment_enabled
        assert get_dm_quality_judgment_enabled() is False

    @patch( "cosa.config.configuration_manager.ConfigurationManager", side_effect=RuntimeError( "boom" ) )
    def test_config_error_returns_false( self, _cm ):
        from cosa.rest.routers.dm import get_dm_quality_judgment_enabled
        assert get_dm_quality_judgment_enabled() is False

    def test_real_config_default_is_false( self ):
        """The shipped lupin-app.ini default (control arm) resolves to False."""
        from cosa.rest.routers.dm import get_dm_quality_judgment_enabled
        assert get_dm_quality_judgment_enabled() is False


if __name__ == "__main__":
    pytest.main( [ __file__, "-v" ] )
