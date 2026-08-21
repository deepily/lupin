#!/usr/bin/env python3
"""
Unit tests for `DmTutorResponse` — the DM tutor's XML response model.

These cover the two failure paths the model exists to close, and both are
SILENT without a test: a CDATA payload corrupted by the base class's own
ampersand repair, and a template example returned as a string instead of an
instance. Neither raises anywhere in production; both ship a wrong result.
"""

import pytest

from cosa.agents.dm_tutor.xml_models import DmTutorResponse, NULL_ISH
from cosa.agents.io_models.utils.util_xml_pydantic import XMLParsingError


def _response( **overrides ):
    """Build a valid response, overriding whichever slots a test cares about."""
    fields = {
        "thoughts"                : "some reasoning",
        "declaration_or_question" : "The headline",
        "supporting_1st"          : "First support",
        "supporting_2nd"          : "Second support",
        "file_path_or_url"        : "",
    }
    fields.update( overrides )
    return DmTutorResponse( **fields )


class TestRoundTrip:
    """to_xml → from_xml must return every payload byte-exact."""

    @pytest.mark.parametrize( "payload", [
        "The queue drained cleanly overnight",
        "Q&A about the queue and a & b",
        "saw a <response> span in the log",
        "Q&A inside <tag> & more",
        "Leak at src/foo.py:12, fixed in f4e0370 & shipped",
        "first line\nsecond line\n\nfourth",
        'he said "the fix is in" yesterday',
        "already escaped &amp; and &lt;",
        "unicode: café — naïve · 🦉",
        "braces {like} {these} and {{doubled}}",
    ] )
    def test_payload_survives_round_trip( self, payload ):
        restored = DmTutorResponse.from_xml( _response( declaration_or_question=payload ).to_xml() )
        assert restored.declaration_or_question == payload

    def test_the_silent_one_ampersand_beside_a_literal( self ):
        """
        The shape where every structural check passes while the prose is wrong.

        A bare `&` is not a structural feature, so a body corrupted by the base
        class's pre-parse repair passes validation and gets delivered. Pairing
        the ampersand WITH a path literal is what makes this the dangerous case
        rather than a cosmetic one.
        """
        payload  = "Leak at src/cosa/rest/queue.py:412 & the fix is in f4e0370"
        restored = DmTutorResponse.from_xml( _response( supporting_1st=payload ).to_xml() )

        assert restored.supporting_1st == payload
        assert "&amp;" not in restored.supporting_1st

    def test_every_cdata_slot_round_trips_at_once( self ):
        """All four payload slots carry hostile characters in the same document."""
        original = _response(
            declaration_or_question = "Q&A: is <thing> ready?",
            supporting_1st          = "a & b < c",
            supporting_2nd          = "see <file> & weep",
            file_path_or_url        = "src/a&b/c.py:1",
        )
        restored = DmTutorResponse.from_xml( original.to_xml() )

        assert restored.declaration_or_question == original.declaration_or_question
        assert restored.supporting_1st          == original.supporting_1st
        assert restored.supporting_2nd          == original.supporting_2nd
        assert restored.file_path_or_url        == original.file_path_or_url


class TestParsingRealResponses:
    """What the model actually sends back, well-formed and not."""

    def test_plain_text_slots_without_cdata( self ):
        """A model that ignores the CDATA instruction still parses, if its prose is clean."""
        xml = (
            "<response>\n"
            "  <thoughts>thinking</thoughts>\n"
            "  <declaration-or-question>The headline</declaration-or-question>\n"
            "  <supporting-statement-1st>One</supporting-statement-1st>\n"
            "  <supporting-statement-2nd>Two</supporting-statement-2nd>\n"
            "  <file-path-or-url-if-present></file-path-or-url-if-present>\n"
            "</response>"
        )
        parsed = DmTutorResponse.from_xml( xml )

        assert parsed.declaration_or_question == "The headline"
        assert parsed.file_path_or_url        == ""

    def test_bare_angle_bracket_outside_cdata_is_a_loud_failure( self ):
        """
        The defect that killed the first live call, pinned as a test.

        A literal `<file>` in un-wrapped prose is an unclosed tag. This MUST
        raise — the prompt's CDATA instruction is what prevents it, and a silent
        pass here would mean the parser had guessed at the model's intent.
        """
        xml = (
            "<response>\n"
            "  <thoughts>use git show HEAD:<file> for the baseline</thoughts>\n"
            "  <declaration-or-question>The headline</declaration-or-question>\n"
            "  <supporting-statement-1st>One</supporting-statement-1st>\n"
            "  <supporting-statement-2nd>Two</supporting-statement-2nd>\n"
            "  <file-path-or-url-if-present></file-path-or-url-if-present>\n"
            "</response>"
        )
        with pytest.raises( XMLParsingError ):
            DmTutorResponse.from_xml( xml )

    def test_same_bracket_inside_cdata_survives( self ):
        """The instruction's whole purpose: the identical payload, wrapped, is fine."""
        xml = (
            "<response>\n"
            "  <thoughts>thinking</thoughts>\n"
            "  <declaration-or-question><![CDATA[use git show HEAD:<file>]]></declaration-or-question>\n"
            "  <supporting-statement-1st><![CDATA[One]]></supporting-statement-1st>\n"
            "  <supporting-statement-2nd><![CDATA[Two]]></supporting-statement-2nd>\n"
            "  <file-path-or-url-if-present><![CDATA[]]></file-path-or-url-if-present>\n"
            "</response>"
        )
        assert DmTutorResponse.from_xml( xml ).declaration_or_question == "use git show HEAD:<file>"

    def test_trailing_garbage_after_root_is_stripped( self ):
        """The base class's suffix stripper still applies — CDATA lifting must not disable it."""
        xml = _response().to_xml() + "\n\nAnd here is some more chatter the model kept writing."
        assert DmTutorResponse.from_xml( xml ).declaration_or_question == "The headline"

    def test_an_invented_sentinel_is_left_alone( self ):
        """
        A model echoing our internal placeholder must not be able to reach into
        the span table. Out of range means leave it as text, never guess.
        """
        xml = (
            "<response>\n"
            "  <thoughts>t</thoughts>\n"
            "  <declaration-or-question><![CDATA[real]]></declaration-or-question>\n"
            "  <supporting-statement-1st>__CDATA_SPAN_99__</supporting-statement-1st>\n"
            "  <supporting-statement-2nd>Two</supporting-statement-2nd>\n"
            "  <file-path-or-url-if-present><![CDATA[]]></file-path-or-url-if-present>\n"
            "</response>"
        )
        assert DmTutorResponse.from_xml( xml ).supporting_1st == "__CDATA_SPAN_99__"


class TestRequiredSlots:
    """The three delivered slots are required; a dropped one must fail closed."""

    @pytest.mark.parametrize( "field", [
        "declaration_or_question", "supporting_1st", "supporting_2nd"
    ] )
    @pytest.mark.parametrize( "empty", [ "", "   ", "\n\t " ] )
    def test_empty_required_slot_raises( self, field, empty ):
        with pytest.raises( Exception ):
            _response( **{ field : empty } )

    @pytest.mark.parametrize( "field", [ "thoughts", "file_path_or_url" ] )
    def test_optional_slots_accept_empty( self, field ):
        assert getattr( _response( **{ field : "" } ), field ) == ""

    @pytest.mark.parametrize( "field", [ "thoughts", "file_path_or_url" ] )
    def test_optional_slots_coerce_none_to_empty( self, field ):
        """An empty XML tag parses to None; it must land as "" and never as the string "None"."""
        assert getattr( _response( **{ field : None } ), field ) == ""

    def test_a_missing_required_slot_raises( self ):
        with pytest.raises( Exception ):
            DmTutorResponse( declaration_or_question="d", supporting_1st="s1" )


class TestPointerAndDelivery:
    """The optional fifth slot, and the lines a recipient actually sees."""

    def test_pointer_returns_a_real_path( self ):
        assert _response( file_path_or_url="src/a.py:12" ).pointer == "src/a.py:12"

    def test_pointer_strips_surrounding_whitespace( self ):
        assert _response( file_path_or_url="\n  src/a.py:12  \n" ).pointer == "src/a.py:12"

    @pytest.mark.parametrize( "null_word", sorted( NULL_ISH ) )
    def test_null_words_are_suppressed( self, null_word ):
        """A delivered line reading "N/A" is worse than no line at all."""
        assert _response( file_path_or_url=null_word ).pointer == ""

    @pytest.mark.parametrize( "null_word", [ "N/A", "None", "NOT APPLICABLE", "  n/a  " ] )
    def test_null_word_matching_ignores_case_and_padding( self, null_word ):
        assert _response( file_path_or_url=null_word ).pointer == ""

    def test_a_bare_row_id_in_the_slot_is_not_a_pointer( self ):
        """
        🔴 THE LIVE ONE (row 56a3c48d). a0151611 stopped the prompt ordering hash lists
        and stopped the restore appending row ids, and a DM STILL arrived as three
        sentences and a bare line reading "fb9faba7" — the model had put the id in the
        PATH slot, which nothing checked. The id is treated like "N/A": a pointer the
        model signalled and does not have.
        """
        assert _response( file_path_or_url="fb9faba7" ).pointer == ""

    def test_the_delivered_message_gains_no_bare_id_line( self ):
        """The end-to-end shape a recipient sees. This is the assertion Rick's rule is."""
        lines = _response( file_path_or_url="fb9faba7" ).to_delivery().splitlines()
        assert lines == [ "The headline", "First support", "Second support" ]

    @pytest.mark.parametrize( "identifier", [ "fb9faba7", "a0151611", "e0bb5a94", "FB9FABA7" ] )
    def test_every_row_id_shape_is_suppressed( self, identifier ):
        assert _response( file_path_or_url=identifier ).pointer == ""

    @pytest.mark.parametrize( "real", [ "src/a.py:12", "job.py", "running_fifo_queue.py:422",
                                        "https://example.com/x", "/tmp/probe.py", "src/rnd/note.md",
                                        # 🔴 María's refutation, row 6dbba874. The first cut asked
                                        # is_bare_identifier — whose precondition is a token the
                                        # pointer grammar already matched — about the RAW slot
                                        # value, where it degenerates to "no dot and no slash" and
                                        # ate every extensionless real filename. Three of these six
                                        # are tracked files in this repo.
                                        "Makefile", "README", "LICENSE", "Dockerfile", "src", "io" ] )
    def test_a_real_pointer_is_still_delivered( self, real ):
        """
        CONTROL, and the one that catches an over-wide guard. Every value here says
        where to look. Delete the row-id guard and the suppression tests go red; widen
        it back to "anything without a slash" and the last six of these do.
        """
        assert _response( file_path_or_url=real ).pointer == real

    @pytest.mark.parametrize( "punctuated", [ "#fb9faba7", "fb9faba7,", "fb9faba7.",
                                              "(fb9faba7)", '"fb9faba7"', " fb9faba7 " ] )
    def test_one_punctuation_mark_does_not_smuggle_an_id_through( self, punctuated ):
        """
        🔴 María, row 68601b65. The anchors that make the row-id test safe on a raw
        value are defeated by one adjacent character, so "#fb9faba7" arrived as a bare
        line — and "#hash8" is live fleet vocabulary, so it is the likeliest form to
        land in the slot. Delete the punctuation strip and every one of these goes red.
        """
        assert _response( file_path_or_url=punctuated ).pointer == ""

    @pytest.mark.parametrize( "punctuated", [ "#fb9faba7", "fb9faba7,", "fb9faba7." ] )
    def test_a_punctuated_id_is_disclosed_with_the_value_as_written( self, punctuated ):
        """The disclosure names what the model actually typed, not the stripped form."""
        assert _response( file_path_or_url=punctuated ).pointer_cleared == punctuated

    @pytest.mark.parametrize( "real", [ ".gitignore", "src/a.py,", "my-notes-file",
                                        ".dockerignore", "notes.md." ] )
    def test_the_strip_does_not_eat_a_real_name( self, real ):
        """
        CONTROL, and the one that bounds the strip. ".gitignore" is a real file and a
        strip that ate a leading dot would take it; it survives because what remains is
        not the row-id shape. Hyphen and underscore are excluded from the strip set on
        purpose — they belong INSIDE filenames.
        """
        assert _response( file_path_or_url=real ).pointer == real

    @pytest.mark.parametrize( "real", [ "Makefile", "README", "LICENSE", "Dockerfile", "src", "io" ] )
    def test_an_extensionless_filename_is_not_reported_as_refused_either( self, real ):
        """The disclosure must agree with the delivery — nothing was refused here."""
        assert _response( file_path_or_url=real ).pointer_cleared == ""

    def test_the_refused_value_is_named_for_the_log( self ):
        """
        A suppression nobody can see is unauditable (María's second requirement). The
        slot drops the id; this says WHICH id, so the reader asking "why did this DM
        carry no path" has something to read.
        """
        assert _response( file_path_or_url="fb9faba7" ).pointer_cleared == "fb9faba7"

    @pytest.mark.parametrize( "quiet", [ "src/a.py:12", "https://example.com/x", "", "N/A", "none" ] )
    def test_nothing_is_reported_when_nothing_was_refused( self, quiet ):
        """
        A real pointer is not a refusal, and neither is a null-word — "N/A" is the model
        correctly saying it has no path. Reporting either would bury the real case.
        """
        assert _response( file_path_or_url=quiet ).pointer_cleared == ""

    def test_delivery_is_three_lines_without_a_pointer( self ):
        lines = _response().to_delivery().splitlines()
        assert lines == [ "The headline", "First support", "Second support" ]

    def test_delivery_appends_the_pointer_as_a_fourth_line( self ):
        lines = _response( file_path_or_url="src/a.py:12" ).to_delivery().splitlines()
        assert len( lines )  == 4
        assert lines[ -1 ]   == "src/a.py:12"

    def test_delivery_never_emits_a_null_word_line( self ):
        assert len( _response( file_path_or_url="N/A" ).to_delivery().splitlines() ) == 3

    def test_a_url_containing_a_null_word_is_not_suppressed( self ):
        """Substring matching would eat a real path. The comparison is on the WHOLE value."""
        url = "http://localhost:7999/app/docs?path=lupin/none/notes.md"
        assert _response( file_path_or_url=url ).pointer == url


class TestTemplateExample:
    """
    The example must be an INSTANCE.

    A string here raises AttributeError inside PromptTemplateProcessor, AgentBase
    swallows it in a bare except (agent_base.py:161), and the template ships
    unprocessed — a literal marker in the prompt and no </stop> sentinel, with
    nothing raised anywhere. This test is the only thing standing between that
    and production.
    """

    def test_returns_an_instance_not_a_string( self ):
        example = DmTutorResponse.get_example_for_template()
        assert isinstance( example, DmTutorResponse )
        assert not isinstance( example, str )

    def test_the_instance_serializes( self ):
        xml = DmTutorResponse.get_example_for_template().to_xml()
        assert xml.startswith( "<response>" )
        assert xml.rstrip().endswith( "</response>" )

    def test_the_example_teaches_every_tag( self ):
        xml = DmTutorResponse.get_example_for_template().to_xml()
        for tag in DmTutorResponse.TAG_FOR_FIELD.values():
            assert f"<{tag}>" in xml, f"the example never shows the model <{tag}>"

    def test_the_example_teaches_cdata( self ):
        """The prompt instructs CDATA; the example must demonstrate it."""
        assert "<![CDATA[" in DmTutorResponse.get_example_for_template().to_xml()

    def test_the_example_round_trips( self ):
        """Whatever we teach must itself be parseable by the parser we ship."""
        example  = DmTutorResponse.get_example_for_template()
        restored = DmTutorResponse.from_xml( example.to_xml() )
        assert restored.declaration_or_question == example.declaration_or_question


class TestTagNaming:
    """Rick specified hyphenated tags; Python cannot name them. Both must hold."""

    def test_field_names_alias_to_the_hyphenated_tags( self ):
        xml = _response().to_xml()
        for tag in DmTutorResponse.TAG_FOR_FIELD.values():
            assert f"<{tag}>" in xml

    def test_construction_by_alias_works( self ):
        parsed = DmTutorResponse( **{
            "thoughts"                    : "t",
            "declaration-or-question"     : "d",
            "supporting-statement-1st"    : "s1",
            "supporting-statement-2nd"    : "s2",
            "file-path-or-url-if-present" : "",
        } )
        assert parsed.declaration_or_question == "d"

    def test_model_dump_keys_are_field_names( self ):
        """
        AgentBase hands run_prompt's dict straight to DmTutorResponse( **fields ),
        so model_dump's keys and the constructor's parameters must agree.
        """
        dumped = _response().model_dump()
        assert DmTutorResponse( **dumped ).supporting_2nd == "Second support"
