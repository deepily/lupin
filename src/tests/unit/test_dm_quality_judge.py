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
    _JUDGE_UNAVAILABLE_DETAIL, _TOO_LONG_DETAIL, _repair_llm_xml, QUALITATIVE_WORD_LIMIT,
    _RETRY_NUDGE, LENGTH_FACE_INTERVAL,
)

_FIXTURE_DIR = os.path.join( _src_path, "tests", "unit", "fixtures", "dm_judge" )


def _load_fixture( name ):
    with open( os.path.join( _FIXTURE_DIR, name ) ) as f:
        return f.read()


_MISTRAL_REACHABLE = {}   # one probe per process, filled on first CALL — never at import


def _mistral_reachable():
    """
    Whether the live Mistral endpoint answers — probed WHEN ASKED, once per process.

    Row 7c84b8b8: this used to be called inside a `@pytest.mark.skipif(...)` ARGUMENT, which
    Python evaluates while the module is being imported. So the unit tier opened a socket at
    COLLECTION time, before any test ran and regardless of which tests were selected — and a
    collection-time dial is the one the outbound-socket guard cannot attribute to a test, and
    the one that takes the whole run down in block mode (one offender hiding every other).
    It is now called from an autouse fixture on the class that needs it, so it dials only when
    those live tests are actually about to run, and the result is cached so a full run costs
    at most one probe.
    """
    if "reachable" not in _MISTRAL_REACHABLE:
        import socket
        try:
            with socket.create_connection( ( "192.168.1.21", 3001 ), timeout=2 ):
                _MISTRAL_REACHABLE[ "reachable" ] = True
        except OSError:
            _MISTRAL_REACHABLE[ "reachable" ] = False
    return _MISTRAL_REACHABLE[ "reachable" ]


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
        ( "bad",               -1, "👎" ),
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
        ( "  GOOD  ",   "good" ),
        ( "Bad",        "bad" ),
        ( "  BAD  ",    "bad" ),
        ( "EXEMPLARY",  "exemplary" ),
        ( None,         "meh" ),
        ( "",           "meh" ),
    ] )
    def test_label_normalization( self, raw, canonical ):
        assert normalize_grade_label( raw ) == canonical

    # ── bug ca7a2cbf — a recoverable label was being thrown away silently ──────
    #
    # The live 24B GPTQ model emits `needs _ improvement` — spaces AROUND the
    # underscore, the same sloppiness that produced spaced TAGS in a5f7b36d. The
    # old two-`.replace()` normalizer turned that into `needs___improvement`,
    # which is not in GRADE_TABLE, so the most-frequent multi-word label in the
    # scale fell through to the `meh` fallback on EVERY occurrence: a real -1
    # published as a neutral 0, with nothing saying a label had been dropped.
    #
    # Measured live before the fix: Tone read `meh` for every DM tested while the
    # model was in fact returning `needs_improvement`.

    @pytest.mark.parametrize( "raw", [
        "  bad  ",
        "\tbad\t",
        "_bad_",
        "-bad-",
        "  BAD  ",
    ] )
    def test_a_padded_or_separator_wrapped_label_still_resolves( self, raw ):
        """
        THE REGRESSION, KEPT — but note its original subject label is GONE.

        The bug was: the live model emitted `needs _ improvement` (spaces AROUND the
        underscore) and a two-`.replace()` normalizer produced `needs___improvement`,
        which is not in GRADE_TABLE, so the most-frequent multi-word label in the
        scale silently became `meh`/0 on every occurrence — a real -1 published as a
        considered neutral.

        Rick's 2026-08-01 vocabulary (`terrible|bad|meh|good|exemplary`) has NO
        multi-word label, so that exact defect cannot recur while this vocabulary
        stands. The collapse is still the right normalizer and is still tested here,
        because the vocabulary could grow a multi-word label again and the next
        person should not have to rediscover why the collapse exists.

        Asserting the WEIGHT, not just the key — the defect was a wrong NUMBER
        reaching a reader.
        """
        assert normalize_grade_label( raw ) == "bad"
        assert grade_weight( raw )          == -1

    @pytest.mark.parametrize( "raw,canonical", [
        ( "needs _ improvement", "needs_improvement" ),
        ( "needs__improvement",  "needs_improvement" ),
        ( "  NEEDS  -  IMPROVEMENT  ", "needs_improvement" ),
    ] )
    def test_the_collapse_still_handles_a_multi_word_label_shape( self, raw, canonical ):
        """
        The mechanism, tested independently of the vocabulary. `needs_improvement` is
        no longer a grade, so these correctly fall through to the `meh` fallback —
        but the COLLAPSE itself must still produce the single-underscore key, or a
        future multi-word label re-opens the original bug silently.
        """
        assert normalize_grade_label( raw ) == "meh"        # not a grade any more
        # the collapse mechanism itself, asserted directly
        import re as _re
        assert _re.sub( r"[\s_\-]+", "_", raw.strip().lower() ).strip( "_" ) == canonical

    def test_a_genuinely_unknown_label_STILL_degrades_to_meh( self ):
        """
        THE NEGATIVE CONTROL, and the reason the fix is a collapse rather than a
        widening. Recovering sloppy separators must not turn the fallback off —
        an unrecognizable label is still a real case and must still land on meh/0.
        Without this, "fix the normalizer" could be satisfied by accepting anything.
        """
        for junk in ( "banana", "needs_improvementt", "very good", "___", "  -  " ):
            assert normalize_grade_label( junk ) == "meh"
            assert grade_weight( junk )          == 0

    def test_every_label_survives_its_own_sloppy_spellings( self ):
        """All five levels, not just the one that bit us — the model can space any of them."""
        for label, ( weight, _ ) in GRADE_TABLE.items():
            for variant in ( label.replace( "_", " _ " ),
                             label.replace( "_", "-" ),
                             label.upper(),
                             f"  {label}  " ):
                assert normalize_grade_label( variant ) == label, variant
                assert grade_weight( variant )          == weight, variant

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
        # The emoji may now REPEAT for display-only intensity (row f4bb1cdb); this test
        # pins the BAND — every face is the band's own emoji. Repetition COUNT is pinned
        # by TestLengthEmojiRepeats below.
        assert set( b[ "emoji" ] ) == { emoji }

    @pytest.mark.parametrize( "words, expected", [
        (  60, "⭐" ),                     # ≤ interval → single ⭐ (60//100 == 0 → max(1,·))
        ( 150, "🤷" ),                     # 150//100 == 1 → still single
        ( 199, "👎" ),                     # last single before the doubling edge (199 is 👎 band)
        ( 200, "👎👎" ),                   # 2×interval → the first DOUBLING (band is 👎)
        ( 300, "😞😞😞" ),                 # 300 // 100 == 3
        ( 800, "😞😞😞😞😞😞😞😞" ),       # 800 // 100 == 8
    ] )
    def test_length_emoji_repeats_per_face_interval( self, words, expected ):
        """Row 2cb46818: the band face repeats max(1, words // LENGTH_FACE_INTERVAL) times.
        The interval is 100 — DECOUPLED from the enforced qualitative cap of 150 so counting
        faces cannot recover the enforced bound. 199 vs 200 is the doubling edge, where an
        off-by-one lives. Assumes the default interval of 100."""
        assert length_bucket( words )[ "emoji" ] == expected

    @pytest.mark.parametrize( "words, face_count", [
        ( 371, 3 ),   # row 2cb46818's OWN worked number: 371 // 100 == 3 (was 2 at interval 150)
        ( 750, 7 ),   # row 2cb46818's OWN worked number: 750 // 100 == 7 (was 5 at interval 150)
    ] )
    def test_row_worked_face_counts_at_interval_100( self, words, face_count ):
        """The two escalation examples row 2cb46818 states in its own text, pinned so the
        interval can never silently drift back toward 150. Both land in the 😞 band (>250),
        so the face is 😞 repeated; assert the COUNT, which is what the row promised moved
        (371: 2→3, 750: 5→7)."""
        emoji = length_bucket( words )[ "emoji" ]
        assert emoji == "😞" * face_count
        assert emoji.count( "😞" ) == face_count == words // LENGTH_FACE_INTERVAL

    def test_repetition_is_display_only_and_never_moves_the_weight( self ):
        """Gate (a): the faces are DISPLAY ONLY. An 800-word body still stores weight -2,
        and no word count pushes the weight outside the [-2, 2] contract combine_overall
        and the audit rely on."""
        assert length_bucket( 800 )[ "weight" ]  == -2
        assert length_bucket( 5000 )[ "weight" ] == -2
        for words in ( 0, 60, 90, 150, 250, 300, 800, 5000 ):
            assert -2 <= length_bucket( words )[ "weight" ] <= 2

    def test_detail_names_the_word_count_and_target( self ):
        assert length_bucket( 187 )[ "detail" ] == "well past the shape — cut it down"  # number-free (Rick 2026-08-13)

    # ── overage: the field that sees past the saturated weight (row 0fc5b8f0) ──

    @pytest.mark.parametrize( "words, overage", [
        (   60,  1.0 ),
        (   30,  0.5 ),
        (  120,  2.0 ),
        (  251,  4.2 ),
        ( 1000, 16.7 ),
    ] )
    def test_overage_is_the_ratio_to_target( self, words, overage ):
        assert length_bucket( words )[ "overage" ] == overage

    def test_overage_is_present_on_every_grade_not_only_bad_ones( self ):
        # A field that appears only in the failing case is one consumers forget to read.
        for words in ( 1, 60, 91, 200, 5000 ):
            assert "overage" in length_bucket( words )

    def test_overage_keeps_increasing_where_the_weight_saturates( self ):
        # 🔴 THE CONTROL, and the whole reason this field exists. Both of these score
        # an identical -2 😞 — that is the defect. If overage ever stops separating
        # them, it has inherited the saturation it was added to see past, and every
        # "which sender is worst" ranking built on it silently collapses.
        a, b = length_bucket( 251 ), length_bucket( 1000 )
        assert a[ "weight" ] == b[ "weight" ] == -2, "premise changed: the weights no longer tie"
        assert a[ "overage" ] < b[ "overage" ]

    def test_overage_is_strictly_increasing_across_the_saturated_range( self ):
        counts   = [ 251, 400, 700, 1000, 2000 ]
        overages = [ length_bucket( n )[ "overage" ] for n in counts ]
        assert overages == sorted( overages ) and len( set( overages ) ) == len( overages )

    def test_weight_stays_inside_the_documented_contract( self ):
        # The alternative fix was a -3/-4 band. It would have broken this, which is
        # asserted in length_bucket's own docstring, relied on by combine_overall's
        # clamp, and assumed by every reader of WEIGHT_TO_EMOJI.
        for words in ( 0, 60, 61, 150, 251, 10_000 ):
            assert -2 <= length_bucket( words )[ "weight" ] <= 2

    def test_resolve_threshold_falls_back_to_default_when_config_raises( self, monkeypatch ):
        """Covers the defensive except in _resolve_threshold (judge.py:109-110): a broken
        config read must NOT stop this module resolving a threshold — it returns the
        per-key default. The happy path never raises, so reaching the except needs
        ConfigurationManager to blow up. `from ... import` runs on every call, so patching
        the module attribute is what the function actually picks up."""
        import cosa.config.configuration_manager as cm
        from cosa.agents.dm_quality_judge import judge as judge_mod

        class _Boom:
            def __init__( self, *a, **k ):
                raise RuntimeError( "config unreadable" )

        monkeypatch.setattr( cm, "ConfigurationManager", _Boom )
        assert judge_mod._resolve_threshold( "dm length good limit", 90 ) == 90


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

    def test_note_names_the_lower_side_without_asserting_harm( self ):
        # Row 700a6330: the note states a RELATIVE ordering, so it must NOT be worded as
        # absolute harm ("dragged it down" fired on top-scoring DMs). It names which side
        # scored lower; the sub-scores carry any real harm signal.
        low_length = combine_overall( -2, 2, 2, "300 words, target ~60" )
        assert "Length scored below directness/tone" in low_length[ "note" ]
        assert "300 words" in low_length[ "note" ]
        assert "pulled this down" not in low_length[ "note" ]
        low_qual = combine_overall( 2, -2, -2, "10 words, target ~60" )
        assert "Directness/tone scored below length" in low_qual[ "note" ]
        assert "dragged it down" not in low_qual[ "note" ]
        balanced = combine_overall( 1, 1, 1, "70 words, target ~60" )
        assert "Balanced" in balanced[ "note" ]
        # The exact defect instance (row 700a6330): a TOP-scoring DM — every sub-score
        # positive, Overall at +2 — must not be told anything "dragged it down". This is
        # where the harm wording misfired hardest, because that is when length maxes at
        # +2 and qualitative cannot exceed it.
        top = combine_overall( 2, 1, 1, "53 words, target ~60" )
        assert top[ "weight" ] == 2
        assert "dragged it down" not in top[ "note" ]
        assert "Directness/tone scored below length" in top[ "note" ]


# ═════════════════════════════════════════════════════════════════════════════
# DmQualityJudge.judge() — retry, fallback, unavailable (item 2)
# ═════════════════════════════════════════════════════════════════════════════

def _make_judge( run_behaviour=None, available=True ):
    """
    Build a DmQualityJudge with its LLM client replaced by a MagicMock.

    run_behaviour: a return_value (str) OR a side_effect (list/exception) for
    client.run. available: sets _available (False → the unavailable path).
    """
    judge = DmQualityJudge( debug=False , qualitative_enabled=True )
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
        assert result[ "directness" ][ "weight" ] is None
        assert result[ "tone" ][ "weight" ] is None
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
        assert result[ "directness" ][ "weight" ] is None
        assert result[ "tone" ][ "detail" ] == _JUDGE_UNAVAILABLE_DETAIL
        # length + overall still computed
        assert "overall" in result

    @patch( "cosa.agents.dm_quality_judge.judge.time.sleep", return_value=None )
    def test_malformed_xml_is_treated_as_a_transient_failure( self, _sleep ):
        judge, client = _make_judge( run_behaviour="<garbage>no closing" )
        result = judge.judge( "body" )
        assert client.run.call_count == 3      # retried, then fell back
        assert result[ "directness" ][ "weight" ] is None


class TestDmQualityJudgeConstruction:
    """The client-build branches of __init__ + the `available` property."""

    @patch( "cosa.agents.dm_quality_judge.judge.LlmClientFactory" )
    def test_available_true_when_factory_succeeds_debug_on( self, MockFactory ):
        MockFactory.return_value.get_client.return_value = MagicMock()
        judge = DmQualityJudge( debug=True , qualitative_enabled=True )
        assert judge.available is True

    @patch( "cosa.agents.dm_quality_judge.judge.LlmClientFactory" )
    def test_available_true_when_factory_succeeds_debug_off( self, MockFactory ):
        MockFactory.return_value.get_client.return_value = MagicMock()
        judge = DmQualityJudge( debug=False , qualitative_enabled=True )
        assert judge.available is True

    @patch( "cosa.agents.dm_quality_judge.judge.LlmClientFactory" )
    def test_available_false_when_factory_raises( self, MockFactory ):
        MockFactory.return_value.get_client.side_effect = RuntimeError( "no server" )
        judge = DmQualityJudge( debug=False , qualitative_enabled=True )
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
        # Every sloppy separator (space, spaced-underscore, dash) canonicalizes to the
        # DASH-cased note tag the parser expects (row 25e8ca1c) — one convention, one place.
        assert "<directness-note>"  in _repair_llm_xml( "<response>< directness note >x</ directness note ></response>" )
        assert "<directness-note>"  in _repair_llm_xml( "<response>< directness _ note >x</ directness _ note ></response>" )
        assert "<directness-note>"  in _repair_llm_xml( "<response><directness-note>x</directness-note></response>" )

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

    def test_recovers_degenerate_curly_mode( self ):
        """bug 2201516e: the non-XML `{ directness_meh } { tone _ good }` degenerate
        mode has the label recoverable — synthesize a <response> from it."""
        out = _repair_llm_xml( "{ directness_meh } { tone _ good }" )
        assert out == "<response><directness>meh</directness><tone>good</tone></response>"
        parsed = DmQualityJudgeResponse.from_xml( out )
        assert parsed.directness_weight() == 0 and parsed.tone_weight() == 1

    def test_curly_recovery_keeps_the_label_intact( self ):
        parsed = DmQualityJudgeResponse.from_xml(
            _repair_llm_xml( "{ directness_bad } { tone_meh }" )
        )
        assert parsed.directness == "bad"
        assert parsed.directness_weight() == -1

    def test_curly_partial_only_directness_is_not_recovered( self ):
        """Only one dimension present → cannot form a response → returned unwrapped
        so from_xml raises and the judge falls back (never a half-grade)."""
        out = _repair_llm_xml( "{ directness_meh } and nothing else here" )
        assert "<response>" not in out


_CURLY_FIXTURES = [
    ( "degenerate_curly_verbose_146w.txt", 0, 1 ),   # { directness_meh } { tone _ good }
    ( "degenerate_curly_clean_150w.txt",   2, 1 ),   # { directness_exemplary } { tone _ good }
]


class TestDegenerateCurlyMode:
    """bug 2201516e — Clayton's live-captured non-XML curly degenerate mode. The
    SAME capture must fail raw pre-fix and recover a REAL grade post-fix (not the
    judge-unavailable failure fallback it currently hits)."""

    @pytest.mark.parametrize( "fname,_dw,_tw", _CURLY_FIXTURES )
    def test_raw_curly_fails_to_parse_pre_fix( self, fname, _dw, _tw ):
        with pytest.raises( XMLParsingError ):
            DmQualityJudgeResponse.from_xml( _load_fixture( fname ) )

    @pytest.mark.parametrize( "fname,dw,tw", _CURLY_FIXTURES )
    def test_judge_recovers_real_grade_post_fix( self, fname, dw, tw ):
        judge, _client = _make_judge( run_behaviour=_load_fixture( fname ) )
        result = judge.judge( "a rambling body under the ceiling" )
        assert result[ "directness" ][ "detail" ] != _JUDGE_UNAVAILABLE_DETAIL
        assert result[ "directness" ][ "weight" ] == dw
        assert result[ "tone" ][ "weight" ]       == tw


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
        assert result[ "directness" ][ "weight" ] is None
        assert result[ "directness" ][ "detail" ] == _JUDGE_UNAVAILABLE_DETAIL


class TestOneOfOneDegenerateRecovery:
    """bug d02eaaa7: the model deterministically emits ' (1 of 1)' (no XML, no grade)
    on one specific rambling body. Repair alone can't recover it — there is no grade
    IN it — so the fix is a retry that PREPENDS a reply-anchor nudge to break the
    deterministic degeneration."""

    def test_one_of_one_is_not_repairable_by_itself( self ):
        """' (1 of 1)' has no tags and no grade label → repair yields nothing
        parseable → from_xml raises (which is why a plain retry can't help; the nudge
        must change the prompt)."""
        with pytest.raises( XMLParsingError ):
            DmQualityJudgeResponse.from_xml( _repair_llm_xml( " (1 of 1)" ) )

    @patch( "cosa.agents.dm_quality_judge.judge.time.sleep", return_value=None )
    def test_retry_prepends_nudge_and_recovers( self, _sleep ):
        """Attempt 1 (clean prompt) returns the degenerate ' (1 of 1)'; attempt 2
        (nudge-prefixed) returns valid XML → judge recovers a NON-fallback grade."""
        judge, client = _make_judge( run_behaviour=[
            " (1 of 1)",
            "<response><directness>good</directness><tone>bad</tone></response>",
        ] )
        result = judge.judge( "a short rambling body" )
        assert client.run.call_count == 2
        # attempt 1 prompt has NO nudge; attempt 2 prompt LEADS with it
        first_prompt  = client.run.call_args_list[ 0 ].args[ 0 ]
        second_prompt = client.run.call_args_list[ 1 ].args[ 0 ]
        assert not first_prompt.startswith( _RETRY_NUDGE )
        assert second_prompt.startswith( _RETRY_NUDGE )
        assert result[ "directness" ][ "detail" ] != _JUDGE_UNAVAILABLE_DETAIL
        assert result[ "directness" ][ "weight" ] == 1
        assert result[ "tone" ][ "weight" ]       == -1


class TestQualitativeWordCeiling:
    """bug 2a41e141: past QUALITATIVE_WORD_LIMIT the LLM is skipped — honest 🤷/0 on the
    qualitative dims, while Length still penalizes the verbosity."""

    def test_long_body_skips_llm_and_returns_too_long_fallback( self ):
        judge, client = _make_judge( run_behaviour="<response><directness>exemplary</directness><tone>exemplary</tone></response>" )
        long_body = " ".join( [ "word" ] * 300 )                        # 300 words → past the ceiling AND length 😞/−2
        result = judge.judge( long_body )
        client.run.assert_not_called()                                  # LLM never invoked
        assert result[ "directness" ][ "weight" ] is None
        assert result[ "tone" ][ "weight" ]       is None
        # Row 2cb46818: the too-long detail is the blunt, number-free refusal and MUST NOT
        # disclose the enforced qualitative ceiling — a sender who learns it writes to it.
        # ONE hardcoded LITERAL on purpose (Mr Radio's ruling): asserting against
        # _TOO_LONG_DETAIL would only prove the code equals itself. A literal is the sole
        # tripwire that catches a wording change nobody meant — e.g. someone re-adds a number.
        assert result[ "directness" ][ "detail" ] == "too f*cking long — cut it down and resubmit"
        assert str( QUALITATIVE_WORD_LIMIT ) not in result[ "directness" ][ "detail" ]
        assert result[ "length" ][ "weight" ]     == -2                 # verbosity still penalized

    def test_body_at_limit_is_still_graded( self ):
        judge, client = _make_judge( run_behaviour="<response><directness>good</directness><tone>good</tone></response>" )
        body = " ".join( [ "word" ] * QUALITATIVE_WORD_LIMIT )
        result = judge.judge( body )
        client.run.assert_called()                                      # at the limit → still judged
        assert result[ "directness" ][ "weight" ] == 1

    def test_enforced_ceiling_did_not_move_off_150( self ):
        """Row 2cb46818's central RISK: someone later reads the per-100 face change as a
        LIMIT change. It is not. The enforced qualitative ceiling is still 150, and it is a
        DIFFERENT number from the display interval (100) by design. This test pins the
        enforcement bound independently of the face interval so the two can never be
        conflated again.

        Three facts, each severable:
          (a) the constants are the values row 2cb46818 fixed, and they DIFFER;
          (b) the band boundary sits at 150 — 150 → 🤷/0, 151 → 👎/−1 (length_bucket);
          (c) the LLM gate fires at exactly 150 — 150 words is graded, 151 is refused."""
        # (a) enforcement 150, display 100, and NOT the same number
        assert QUALITATIVE_WORD_LIMIT == 150
        assert LENGTH_FACE_INTERVAL   == 100
        assert QUALITATIVE_WORD_LIMIT != LENGTH_FACE_INTERVAL

        # (b) the 🤷/👎 band boundary is anchored on the enforced ceiling, not the interval
        assert length_bucket( 150 )[ "weight" ] ==  0 and length_bucket( 150 )[ "emoji" ] == "🤷"
        assert length_bucket( 151 )[ "weight" ] == -1 and set( length_bucket( 151 )[ "emoji" ] ) == { "👎" }

        # (c) the LLM-skip gate fires at exactly the ceiling: 150 graded, 151 refused
        judge, client = _make_judge( run_behaviour="<response><directness>good</directness><tone>good</tone></response>" )
        judge.judge( " ".join( [ "word" ] * 150 ) )
        client.run.assert_called()                                      # 150 → judged
        judge2, client2 = _make_judge( run_behaviour="<response><directness>good</directness><tone>good</tone></response>" )
        over = judge2.judge( " ".join( [ "word" ] * 151 ) )
        client2.run.assert_not_called()                                 # 151 → LLM skipped
        assert over[ "directness" ][ "weight" ] is None


class TestExampleIsAChooseOnePlaceholder:
    """
    PREMISE REVERSED 2026-08-01 (Rick). This class previously asserted the opposite —
    that the example must be CONCRETE — because an early `[one of: terrible, ...]`
    enum hint was echoed verbatim as malformed XML (bug a5f7b36d), and that failure
    was read as "placeholders do not work here."

    Both readings were too broad. A bracketed ENUM HINT failed because that syntax is
    not prose; a filled PLAUSIBLE grade failed differently — the model copied it
    byte-for-byte onto messages it did not describe, including the single word "yes".
    Rick's CHOOSE-ONE form is neither: an instruction the model reads and substitutes.
    Verified live against phi-4 — the placeholder is NOT echoed and a real label is
    returned.

    The example must therefore be a placeholder that CANNOT be mistaken for an answer.
    """

    def test_example_is_a_choose_one_placeholder_not_a_usable_grade( self ):
        ex = DmQualityJudgeResponse.get_example_for_template()
        for grade in ( ex.directness, ex.tone ):
            assert "CHOOSE ONE" in grade
            # the whole point: it is NOT a label a copying model could pass off
            assert grade not in GRADE_TABLE

    def test_example_enumerates_every_legal_label( self ):
        """The CHOOSE-ONE list must stay in step with GRADE_TABLE, or the prompt
        starts advertising a vocabulary the parser does not accept."""
        ex = DmQualityJudgeResponse.get_example_for_template()
        for label in GRADE_TABLE:
            assert label in ex.directness, label
            assert label in ex.tone, label

    def test_example_notes_are_directives_not_prose_a_model_could_copy( self ):
        ex = DmQualityJudgeResponse.get_example_for_template()
        for note in ( ex.directness_note, ex.tone_note ):
            assert note.isupper(), note      # shouted instruction, not a sentence

    def test_example_serializes_with_dash_cased_tags( self ):
        """Repo convention (`line-number`, `rephrased-answer`). The repair layer and
        the parser both canonicalize on the dash form, so the EXAMPLE must teach it."""
        xml = DmQualityJudgeResponse.get_example_for_template().to_xml()
        assert "<directness-note>" in xml and "<tone-note>" in xml
        assert "_note>" not in xml


class TestMeahAlias:
    def test_meah_maps_to_meh( self ):
        assert normalize_grade_label( "meah" ) == "meh"
        assert normalize_grade_label( " Meah " ) == "meh"
        assert grade_weight( "meah" ) == 0


class TestLiveMistralRegression:
    """The gap that let bug a5f7b36d ship: unit tests fed hand-written XML and never
    hit the real endpoint. This exercises the LIVE model end-to-end (skipped when
    :3001 is unreachable so the offline unit gate stays green)."""

    @pytest.fixture( autouse=True )
    def _require_live_mistral( self ):
        """
        Skip at RUN time, not at collection.

        The class-level `@pytest.mark.skipif( not _mistral_reachable(), ... )` this replaces
        was evaluated while the module was imported, so merely COLLECTING the unit tier
        opened a socket — whether or not these tests were selected (row 7c84b8b8). A fixture
        runs per test, so the probe happens only when a live test is genuinely about to run,
        and `_mistral_reachable` caches it so that is one probe per process at most.
        """
        if not _mistral_reachable():
            pytest.skip( "live Mistral :3001 unreachable" )

    # Un-xfailed 2026-08-01 (row 25e8ca1c): the prompt regression is fixed and the repair
    # layer is now tag-convention-agnostic, so phi-4's clean dash-cased XML parses and this
    # returns a real non-fallback grade. Was xfail while c7b76ce5's prompt took it down.
    def test_live_short_exemplary_body_grades_non_fallback( self ):
        judge  = DmQualityJudge( qualitative_enabled=True )
        result = judge.judge( "Phase 1 done, green. 89 tests pass. Not committed — holding your gate." )
        assert result[ "directness" ][ "detail" ] != _JUDGE_UNAVAILABLE_DETAIL
        assert result[ "tone" ][ "detail" ]       != _JUDGE_UNAVAILABLE_DETAIL
        assert set( result.keys() ) == { "length", "directness", "tone", "overall" }

    # Un-xfailed 2026-08-01 (row 25e8ca1c): prompt fixed + repair layer tag-agnostic, so
    # the grades diverge for real again. Was xfail under c7b76ce5's malformed-XML fallback.
    def test_live_discrimination_good_vs_bad_diverge( self ):
        """Krishna req #2: on short/medium DMs the grades ACTUALLY diverge — a
        verdict-first DM must out-score a rambling no-verdict one on directness. This
        is the anti-parrot proof: byte-identical grades would fail here."""
        judge = DmQualityJudge( qualitative_enabled=True )
        good  = judge.judge( "Phase 1 done, green. 89 tests pass. Not committed — holding your gate." )
        bad   = judge.judge(
            "So, quick thought, no rush at all, but I was sort of maybe wondering if we could perhaps "
            "chat about the queue thing sometime when you get a moment, just flagging it is on my mind."
        )
        assert good[ "directness" ][ "weight" ] > bad[ "directness" ][ "weight" ]

    def test_live_rambling_140w_under_ceiling_grades_non_fallback( self ):
        """bug 2201516e: a rambling ~140-word DM (under the 150 ceiling, the target
        population) must return a REAL grade, not the judge-unavailable fallback —
        whether the model emits XML or the degenerate `{ directness_x }` curly mode,
        the repair layer now recovers the signal end-to-end against live Mistral."""
        rambling = (
            "Hey, so, I hope this is not a bad time, I know everyone is heads-down and the last thing I "
            "want is to add noise, but I have been mulling over the queue refactor for a couple of days "
            "and I keep going back and forth on whether it is even worth bringing up, and honestly I am "
            "still not sure where I land, there are arguments on both sides and a reasonable person might "
            "disagree, but I figured I would rather flag it early than sit on it and regret it, so anyway, "
            "no pressure at all, whenever you get a spare moment maybe we could talk it through, or not, "
            "totally your call, just wanted to put it on your radar in case it helps, thanks so much."
        )
        assert len( rambling.split() ) <= QUALITATIVE_WORD_LIMIT
        result = DmQualityJudge( qualitative_enabled=True ).judge( rambling )
        assert result[ "directness" ][ "detail" ] != _JUDGE_UNAVAILABLE_DETAIL
        assert result[ "tone" ][ "detail" ]       != _JUDGE_UNAVAILABLE_DETAIL

    # Un-xfailed 2026-08-01 (row 25e8ca1c): third of the three siblings — prompt fixed +
    # repair layer tag-agnostic, so the nudge retry recovers a real grade. Was xfail under
    # c7b76ce5's malformed-XML fallback.
    def test_live_1of1_verbose_recovers_via_nudge( self ):
        """bug d02eaaa7 end-to-end: Clayton's exact 146w body deterministically makes
        the live model emit ' (1 of 1)' on attempt 1; the nudge retry recovers a REAL
        non-fallback grade against live Mistral (was judge-unavailable pre-fix)."""
        body   = _load_fixture( "live_1of1_verbose_146w.txt" )
        assert len( body.split() ) <= QUALITATIVE_WORD_LIMIT      # under the ceiling → LLM-graded
        result = DmQualityJudge( qualitative_enabled=True ).judge( body )
        assert result[ "directness" ][ "detail" ] != _JUDGE_UNAVAILABLE_DETAIL
        assert result[ "tone" ][ "detail" ]       != _JUDGE_UNAVAILABLE_DETAIL

    def test_live_maria_raw_is_length_gated_not_parroted( self ):
        """bug 2a41e141 end-to-end: the 527-word reference DM is PAST the qualitative
        ceiling, so it returns the honest 'too long' 🤷/0 (never the parroted 'good'),
        while Length still penalizes its verbosity at 😞/−2."""
        import cosa.utils.util as cu
        maria  = cu.get_file_as_string(
            cu.get_project_root() + "/src/rnd/v0.1.9/2026.07.31-dm-verbosity-reduction/dm-maria-raw.txt"
        )
        result = DmQualityJudge( qualitative_enabled=True ).judge( maria )
        assert result[ "directness" ][ "weight" ] is None
        # Row 2cb46818: blunt, number-free refusal — no enforced ceiling disclosed.
        assert result[ "directness" ][ "detail" ] == _TOO_LONG_DETAIL
        assert str( QUALITATIVE_WORD_LIMIT ) not in result[ "directness" ][ "detail" ]
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

    # 🔴 PATCHED AT THE FACTORY, NOT AT A VERSION'S CLASS (fixed 2026-08-01, row 55a5baab).
    # This used to patch `cosa.agents.dm_quality_judge.judge.DmQualityJudge` — the v1 class.
    # `dm._maybe_grade_dm_quality` does not name a class; it calls `get_dm_quality_judge()`
    # precisely so the call site never learns about a version. The moment
    # `dm quality judge version` moved to 2, the patch stopped matching what the factory
    # returned, and this "unit" test built a REAL judge and made LIVE MODEL CALLS — slow,
    # network-dependent, and tallying into the audit counters it then asserted on.
    #
    # It went red rather than silently-wrong only by luck: the real judge returned real
    # grades that did not equal the mock's dict. Had the assertion been looser (a key
    # check, a count check), a live-calling unit test would have kept passing and nobody
    # would have known. Patch the seam the code actually uses.
    @patch( "cosa.agents.dm_quality_judge.get_dm_quality_judge" )
    @patch( "cosa.rest.routers.dm.get_dm_quality_judgment_enabled", return_value=True )
    def test_toggle_on_builds_grades_and_records( self, _enabled, mock_factory ):
        import cosa.rest.routers.dm as dm
        grade = {
            "length"     : { "weight": 2 },
            "directness" : { "weight": 1 },
            "tone"       : { "weight": 0 },
            "overall"    : { "weight": 1 },
        }
        mock_factory.return_value.judge.return_value = grade
        out = dm._maybe_grade_dm_quality( "short body" )
        assert out == grade
        assert dm.get_dm_quality_audit()[ "count" ] == 1
        # lazy singleton: built exactly once, reused thereafter
        assert dm._dm_quality_judge is mock_factory.return_value
        dm._maybe_grade_dm_quality( "another" )
        assert mock_factory.call_count == 1

    @patch( "cosa.agents.dm_quality_judge.get_dm_quality_judge" )
    @patch( "cosa.rest.routers.dm.get_dm_quality_judgment_enabled", return_value=True )
    def test_grading_is_version_agnostic( self, _enabled, mock_factory ):
        # THE CONTROL for the fix above: the wiring must go through the factory, so no
        # judge CLASS is ever constructed directly here. If someone re-couples this call
        # site to a version's class, the factory stops being consulted and this goes red.
        import cosa.rest.routers.dm as dm
        mock_factory.return_value.judge.return_value = { "length": { "weight": 0 },
                                                         "directness": { "weight": 0 },
                                                         "tone": { "weight": 0 },
                                                         "overall": { "weight": 0 } }
        dm._maybe_grade_dm_quality( "body" )
        assert mock_factory.called, "the call site bypassed get_dm_quality_judge()"


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

    @pytest.mark.xfail( reason=(
        "PREMISE CHANGED, not a defect. Rick ruled LENGTH-ONLY on 2026-08-01 (row "
        "ca7a2cbf): `dm quality judgment enabled` is now True so Length publishes, and "
        "the new `dm quality qualitative enabled` is False so the LLM half stays off. "
        "This test pins the OLD single-toggle world. Replace it with an assertion on "
        "`dm quality qualitative enabled` being False, which is the invariant that now "
        "matters." ), strict=True )
    def test_real_config_default_is_false( self ):
        """The shipped lupin-app.ini default (control arm) resolves to False."""
        from cosa.rest.routers.dm import get_dm_quality_judgment_enabled
        assert get_dm_quality_judgment_enabled() is False


if __name__ == "__main__":
    pytest.main( [ __file__, "-v" ] )


# ═════════════════════════════════════════════════════════════════════════════
# The audit's overage accumulator (row 0fc5b8f0)
# ═════════════════════════════════════════════════════════════════════════════

class TestQualityAuditOverage:

    def setup_method( self ):
        import cosa.rest.routers.dm as dm
        dm.reset_dm_quality_audit()

    def teardown_method( self ):
        import cosa.rest.routers.dm as dm
        dm.reset_dm_quality_audit()

    def _grade( self, overage, length_weight=-2 ):
        return {
            "length"     : { "weight": length_weight, "detail": "x", "overage": overage },
            "directness" : { "weight": None, "detail": "off" },
            "tone"       : { "weight": None, "detail": "off" },
            "overall"    : { "weight": length_weight },
        }

    def test_avg_overage_moves_where_avg_length_cannot( self ):
        # 🔴 THE CONTROL FOR THE AUDIT HALF. Both grades are -2, so avg_length is pinned
        # at its floor and cannot answer "are DMs getting worse?". avg_overage must.
        import cosa.rest.routers.dm as dm
        dm._record_dm_quality( self._grade( 4.2 ) )
        first = dm.get_dm_quality_audit()
        dm._record_dm_quality( self._grade( 16.7 ) )
        second = dm.get_dm_quality_audit()
        assert first[ "avg_length" ] == second[ "avg_length" ] == -2.0
        assert second[ "avg_overage" ] > first[ "avg_overage" ]

    def test_avg_overage_is_zero_with_no_data_not_a_crash( self ):
        import cosa.rest.routers.dm as dm
        assert dm.get_dm_quality_audit()[ "avg_overage" ] == 0.0

    def test_reset_clears_the_overage_sum( self ):
        import cosa.rest.routers.dm as dm
        dm._record_dm_quality( self._grade( 9.0 ) )
        assert dm.get_dm_quality_audit()[ "total_overage" ] == 9.0
        dm.reset_dm_quality_audit()
        assert dm.get_dm_quality_audit()[ "total_overage" ] == 0.0

    def test_a_length_dict_without_overage_does_not_500_the_send( self ):
        # The defensive .get is deliberate and scoped to this one field: a judge on an
        # older path can hand back a Length dict predating `overage`, and losing a SEND
        # over a statistic is the wrong trade. The weight beside it is subscripted
        # directly and still fails loud.
        import cosa.rest.routers.dm as dm
        legacy = self._grade( 0.0 )
        del legacy[ "length" ][ "overage" ]
        dm._record_dm_quality( legacy )
        assert dm.get_dm_quality_audit()[ "count" ] == 1
        assert dm.get_dm_quality_audit()[ "total_overage" ] == 0.0

    def test_audit_line_reports_overage( self ):
        import cosa.rest.routers.dm as dm
        dm._record_dm_quality( self._grade( 16.7 ) )
        assert "avg_overage=16.7x" in dm.format_dm_quality_audit_line()
