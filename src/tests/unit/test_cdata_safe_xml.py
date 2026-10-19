"""
Unit tests for CDATA-safe parsing of the DM compression and DM tutor responses.

Twin refactor slice xml-cdata-mixin: both response models carried the same from_xml and the
same CDATA constants.
"""

import pytest

from cosa.agents.dm_compression.xml_models import DmCompressionResponse
from cosa.agents.dm_tutor.xml_models import DmTutorResponse
from cosa.agents.io_models.utils.util_xml_pydantic import BaseXMLModel, XMLParsingError


def _compression( compressed, thoughts = "plain" ):
    return f"<response><thoughts>{thoughts}</thoughts><compressed>{compressed}</compressed></response>"


def _tutor( first, second = "<![CDATA[two]]>", thoughts = "plain" ):
    return (
        f"<response><thoughts>{thoughts}</thoughts>"
        f"<declaration-or-question>{first}</declaration-or-question>"
        f"<supporting-statement-1st>{second}</supporting-statement-1st>"
        f"<supporting-statement-2nd><![CDATA[three]]></supporting-statement-2nd></response>"
    )


class TestCompression:

    def test_cdata_payload_survives_byte_exact_with_ampersands_and_angles( self ):
        r = DmCompressionResponse.from_xml( _compression( "<![CDATA[Q&A <b>& more &amp; ]] x]]>" ) )
        assert r.compressed == "Q&A <b>& more &amp; ]] x"

    def test_bare_ampersand_outside_cdata_is_still_repaired( self ):
        r = DmCompressionResponse.from_xml( _compression( "<![CDATA[a & b]]>", thoughts = "cut Q&A" ) )
        assert r.thoughts == "cut Q&A"
        assert r.compressed == "a & b"

    def test_two_cdata_spans_come_back_in_their_own_fields( self ):
        xml = _compression( "<![CDATA[one & two]]>", thoughts = "<![CDATA[t & u]]>" )
        r   = DmCompressionResponse.from_xml( xml )
        assert ( r.thoughts, r.compressed ) == ( "t & u", "one & two" )

    def test_document_without_cdata_matches_the_base_class( self ):
        xml = _compression( "plain text" )
        assert DmCompressionResponse.from_xml( xml ) == BaseXMLModel.from_xml.__func__( DmCompressionResponse, xml )

    def test_an_invented_sentinel_is_left_alone( self ):
        r = DmCompressionResponse.from_xml( _compression( "<![CDATA[real]]> __CDATA_SPAN_7__" ) )
        assert r.compressed == "real __CDATA_SPAN_7__"

    @pytest.mark.parametrize( "index, expected", [ ( 0, "real" ), ( 1, "__CDATA_SPAN_1__" ) ] )
    def test_the_sentinel_index_boundary_is_the_span_count( self, index, expected ):
        """One real span: index 0 is restored, index 1 (one past the end) is not."""
        r = DmCompressionResponse.from_xml( _compression( f"<![CDATA[real]]>|__CDATA_SPAN_{index}__" ) )
        assert r.compressed == f"real|{expected}"

    def test_unparseable_document_still_raises_the_base_error( self ):
        with pytest.raises( XMLParsingError ):
            DmCompressionResponse.from_xml( "not xml at all" )

    def test_only_xml_string_is_accepted( self ):
        """The override takes no root_tag, as before."""
        with pytest.raises( TypeError ):
            DmCompressionResponse.from_xml( _compression( "x" ), "response" )


class TestTutor:

    def test_every_cdata_slot_survives_byte_exact( self ):
        r = DmTutorResponse.from_xml( _tutor( "<![CDATA[Is R&D <ok>?]]>", "<![CDATA[a & b]]>" ) )
        assert r.declaration_or_question == "Is R&D <ok>?"
        assert r.supporting_1st == "a & b"
        assert r.supporting_2nd == "three"

    def test_bare_ampersand_outside_cdata_is_still_repaired( self ):
        r = DmTutorResponse.from_xml( _tutor( "<![CDATA[q]]>", thoughts = "R&D notes" ) )
        assert r.thoughts == "R&D notes"

    def test_an_invented_sentinel_is_left_alone( self ):
        r = DmTutorResponse.from_xml( _tutor( "<![CDATA[q __CDATA_SPAN_9__]]>" ) )
        assert r.declaration_or_question == "q __CDATA_SPAN_9__"

    def test_unparseable_document_still_raises_the_base_error( self ):
        with pytest.raises( XMLParsingError ):
            DmTutorResponse.from_xml( "not xml at all" )


def test_the_wrapper_constants_are_the_same_in_both_modules():
    import cosa.agents.dm_compression.xml_models as a
    import cosa.agents.dm_tutor.xml_models as b
    assert ( a.CDATA_OPEN, a.CDATA_CLOSE ) == ( b.CDATA_OPEN, b.CDATA_CLOSE ) == ( "<![CDATA[", "]]>" )


class TestThoughtsEscaping:
    """to_xml escapes a bare ampersand in thoughts and leaves existing entities alone."""

    THOUGHTS = "a & b &apos; &#35; &amp; <x>"
    ESCAPED  = "a &amp; b &apos; &#35; &amp; &lt;x&gt;"

    def test_compression_to_xml( self ):
        r = DmCompressionResponse( thoughts = self.THOUGHTS, compressed = "c & d" )
        assert f"<thoughts>{self.ESCAPED}</thoughts>" in r.to_xml()
        assert "<compressed><![CDATA[c & d]]></compressed>" in r.to_xml()

    def test_tutor_to_xml( self ):
        r = DmTutorResponse( thoughts = self.THOUGHTS, declaration_or_question = "q & r", supporting_1st = "s", supporting_2nd = "t" )
        assert f"<thoughts>{self.ESCAPED}</thoughts>" in r.to_xml()
        assert "<![CDATA[q & r]]>" in r.to_xml()
