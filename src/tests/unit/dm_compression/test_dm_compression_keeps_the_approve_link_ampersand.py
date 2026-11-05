"""
Does the DM compression path turn the `&` in an approve link into `&amp;`?

Measured lead: the base XML model escapes bare ampersands before parsing, and the payload sits in
CDATA, where nothing is unescaped. dm_compression overrides that. These tests send the link through
the whole path (freeze, the model's XML, parse, validate, restore) and require it byte-identical.

Venue: :7999 (unit, no model call, no server).
"""

from cosa.agents.dm_compression.freeze import compress_or_original, freeze
from cosa.agents.dm_compression.xml_models import DmCompressionResponse
from cosa.agents.io_models.utils.util_xml_pydantic import BaseXMLModel, CDATA_CLOSE, CDATA_OPEN

LINK   = "[approve](/app/tasks/approve?row=x&priority=P0)"
FILLER = "which is a long sentence that the rewriter is allowed to shorten because it carries no facts at all"
BODY   = (
    f"Row x is held and needs your approval, {FILLER}, and the whole message has to be long enough "
    f"that freezing it is worth the rewriter's time and the minimum word count is passed: {LINK} "
    "then a few more plain words after the link so there is something left to compress, "
    "including this sentence which also adds nothing and can be cut without losing a single fact."
)


def test_the_instrument_is_live_the_message_is_not_bypassed_and_the_link_is_frozen():
    frozen = freeze( BODY )
    assert frozen.should_bypass is False, frozen.bypass_reason
    assert "&" not in frozen.frozen_text, "the & of the link should be inside a placeholder"
    assert len( frozen.placeholders ) >= 2


def test_the_link_survives_freeze_xml_parse_and_restore_byte_for_byte():
    frozen  = freeze( BODY )
    shorter = frozen.frozen_text.replace( FILLER + ", ", "" )
    parsed  = DmCompressionResponse.from_xml( DmCompressionResponse( thoughts="cut", compressed=shorter ).to_xml() ).compressed
    out, fallback = compress_or_original( parsed, frozen )
    assert fallback is None, fallback
    assert LINK in out
    assert "&amp;" not in out
    assert len( out ) < len( BODY ), "the rewrite should really have shortened the message"


def test_an_unfrozen_ampersand_in_the_models_reply_still_comes_back_unescaped():
    """A bare & in prose, which freezing misses, is kept by the override and escaped by the base."""
    xml = f"<response><thoughts>t</thoughts><compressed>{CDATA_OPEN}a=1&priority=P0{CDATA_CLOSE}</compressed></response>"
    assert DmCompressionResponse.from_xml( xml ).compressed == "a=1&priority=P0"
    assert "&amp;" in BaseXMLModel.from_xml.__func__( DmCompressionResponse, xml ).compressed, \
        "the base class escapes it, so the override is what protects the link"
