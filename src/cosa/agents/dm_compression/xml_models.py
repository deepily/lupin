#!/usr/bin/env python3
"""
XML response model for the DM compression agent.

The rewriter receives a frozen message body, whose immutable literals were already replaced
by `[[Lnn]]` placeholders. It returns a shorter version with every placeholder untouched.

Why XML and not JSON: measured on 2,977 real DMs, 9% need XML escaping and 77% need JSON
escaping. JSON's hostile characters (double quote 55%, newline 64%) are the most common
characters after letters and spaces. 19,195 characters need escape against XML's 556.
More decisive, XML has `<![CDATA[ ... ]]>`, which tells the model "this span is literal, do not touch it".
JSON has no equivalent, so it would demand the per-character transcription accuracy.
The freeze protocol exists to stop depending on that accuracy.

The defect this file works around is the dangerous one. `BaseXMLModel.from_xml()` escapes
bare ampersands before parsing, so an LLM writing "Q&A" does not produce invalid XML.
Inside a CDATA section nothing is ever unescaped, so that injected `&amp;` survives into
the parsed value. The base class's own repair step corrupts the payload:

    sent      "Q&A about the queue"
    returned  "Q&amp;A about the queue"

The freeze validator cannot see it. A bare `&` in prose is neither a placeholder nor a
verify-tier literal. A corrupted body therefore passes every structural check and is delivered.
Fail-closed never fires, and 88 corpus bodies (3%) carry a bare `&`. The `from_xml` override
is therefore a safety fix. The falsification test pairs an ampersand with a placeholder,
the shape where every structural check passes while the prose is wrong.

The base class strips everything after the first closing root tag. It tries `</response>` first.
It moves on to `</result>` and `</output>` only when `</response>` is absent. That
handling is not relied on: our model always uses `<response>` as its root tag. A `</response>` inside the body
is lifted out with its CDATA span, so the stripper never sees it.
"""

import re

from typing import ClassVar

from pydantic import Field, field_validator

from cosa.agents.io_models.utils.util_xml_pydantic import BaseXMLModel


# The CDATA wrapper. `]]>` occurs ZERO times in 2,977 corpus bodies, so the one
# sequence that could break the wrapper does not appear in this traffic — and the
# Phase 1 extractor would freeze it as a literal anyway.
CDATA_OPEN  = "<![CDATA["
CDATA_CLOSE = "]]>"

_CDATA_SPAN = re.compile( re.escape( CDATA_OPEN ) + r".*?" + re.escape( CDATA_CLOSE ), re.DOTALL )

# The base class's repair, reproduced so it can be applied OUTSIDE CDATA spans
# only. Kept character-identical on purpose: if the base rule ever changes, this
# should be updated to match rather than quietly diverging from it.
_BARE_AMPERSAND = re.compile( r"&(?!amp;|lt;|gt;|quot;|apos;|#)" )

# The sentinel a lifted CDATA span leaves behind. Deliberately built from
# characters the base class never rewrites — no ampersand, no angle bracket —
# so that its repairs cannot damage the placeholder while the payload is away.
_SENTINEL = "__CDATA_SPAN_{}__"
_SENTINEL_RE = re.compile( r"__CDATA_SPAN_(\d+)__" )


class DmCompressionResponse( BaseXMLModel ):
    """
    The rewriter's response: its reasoning, and the compressed body.

    Shaped after `DmQualityJudgeResponse` — every field is `str`, because LLM I/O
    is always text.
    """

    xml_tag_name: ClassVar[ str ] = "response"

    thoughts   : str = Field( default="", description="Brief reasoning about what was cut and what was kept" )
    compressed : str = Field( ...,        description="The compressed message body, every [[Lnn]] placeholder intact" )

    @field_validator( "thoughts", mode="before" )
    @classmethod
    def _none_to_empty( cls, v ):
        """
        Coerce the None that an empty tag parses to into "".

        Requires:
            - v is a string or None

        Ensures:
            - returns "" for None; passes other values through unchanged
        """
        return "" if v is None else v

    @field_validator( "compressed" )
    @classmethod
    def _reject_empty_compressed( cls, v ):
        """
        Refuse an empty compressed body.

        A blank rewrite is a deletion, not a compression. Raising here puts the message on
        the fail-closed path, where the original is delivered.

        Requires:
            - v is a string

        Ensures:
            - returns v unchanged when it holds any non-whitespace character

        Raises:
            - ValueError when v is empty or whitespace only
        """
        if v is None or not v.strip():
            raise ValueError( "compressed body is empty — a blank rewrite is a deletion, not a compression" )
        return v

    # ──────────────────────────────────────────────────────────────────────────
    # Serialization
    # ──────────────────────────────────────────────────────────────────────────

    def to_xml( self, root_tag="response", pretty=True ):
        """
        Serialize with the compressed body wrapped in CDATA.

        Hand-built because xmltodict would escape the payload into entities.
        Carrying the payload verbatim is the reason for using CDATA.

        Requires:
            - self.compressed is a non-empty string

        Ensures:
            - returns a well-formed <response> document
            - the compressed payload sits inside a CDATA section, unescaped
            - from_xml( self.to_xml() ).compressed == self.compressed, exactly
        """
        thoughts = (
            _BARE_AMPERSAND.sub( "&amp;", self.thoughts )
            .replace( "<", "&lt;" )
            .replace( ">", "&gt;" )
        )

        return (
            f"<{root_tag}>\n"
            f"  <thoughts>{thoughts}</thoughts>\n"
            f"  <compressed>{CDATA_OPEN}{self.compressed}{CDATA_CLOSE}</compressed>\n"
            f"</{root_tag}>"
        )

    @classmethod
    def from_xml( cls, xml_string ):
        """
        Parse, keeping the base class's ampersand repair away from CDATA spans.

        The base class escapes every bare `&`, which corrupts CDATA, so each CDATA span
        is lifted out behind a sentinel. The rest goes to the base class for its other
        repairs, and the spans are then restored verbatim.

        Requires:
            - xml_string is a string

        Ensures:
            - CDATA payloads survive byte-exact, ampersands included
            - all non-CDATA text still receives the base class's repairs
            - a document with no CDATA behaves exactly as the base class does

        Raises:
            - XMLParsingError when the document cannot be parsed (unchanged)
        """
        spans = []

        def _lift( match ):
            spans.append( match.group( 0 )[ len( CDATA_OPEN ) : -len( CDATA_CLOSE ) ] )
            return _SENTINEL.format( len( spans ) - 1 )

        parsed = super().from_xml( _CDATA_SPAN.sub( _lift, xml_string ) )

        if not spans: return parsed

        def _restore( match ):
            index = int( match.group( 1 ) )
            # An out-of-range index means the model invented a sentinel. Leave it
            # alone rather than guessing: the validator's business, not ours.
            return spans[ index ] if index < len( spans ) else match.group( 0 )

        for field_name in cls.model_fields:
            value = getattr( parsed, field_name, None )
            if isinstance( value, str ) and "__CDATA_SPAN_" in value:
                object.__setattr__( parsed, field_name, _SENTINEL_RE.sub( _restore, value ) )

        return parsed

    @classmethod
    def get_example_for_template( cls ):
        """
        A structural example for `{{PYDANTIC_XML_EXAMPLE}}` injection.

        The content is placeholder text, because models copy a plausible-looking answer.
        The placeholder token in the example is deliberate: it shows the model that a placeholder passes through untouched.
        It returns an instance, not a string, because `PromptTemplateProcessor` calls `.to_xml()`.

        Requires:
            - nothing

        Ensures:
            - returns a DmCompressionResponse instance (not a string). A string raises `AttributeError`
              in `PromptTemplateProcessor`, and `AgentBase` swallows it silently: the template ships
              unprocessed, a literal `{{PYDANTIC_XML_EXAMPLE}}` stays in the prompt, there is no
              `</stop>` sentinel, nothing raises, and the construction test is what catches it
        """
        return cls(
            thoughts   = "What you cut, and what you kept",
            compressed = "The shortened message, with [[L00]] exactly as it arrived",
        )


def quick_smoke_test():
    """Round-trip the model against the payloads that break the base class."""
    import cosa.utils.util as du

    du.print_banner( "DmCompressionResponse smoke test" )

    cases = {
        "plain"         : "The queue drained cleanly overnight",
        "ampersand"     : "Q&A about the queue and a & b",
        "angle brackets": "saw a <response> span in the log",
        "mixed"         : "Q&A inside <tag> & more",
        "🔴 the silent one": "Leak at [[L00]], fixed in [[L01]] & shipped",
        "multiline"     : "first line\nsecond line\n\nfourth",
        "quotes"        : 'he said "the fix is in" yesterday',
        "entities"      : "already escaped &amp; and &lt;",
    }

    failures = 0
    for name, payload in cases.items():
        restored = DmCompressionResponse.from_xml(
            DmCompressionResponse( thoughts="t", compressed=payload ).to_xml()
        ).compressed
        ok        = restored == payload
        failures += 0 if ok else 1
        print( f"  {name:<18} {'✓' if ok else '✗'}  {restored!r}" )

    print()
    print( f"  round trip: {len( cases ) - failures}/{len( cases )} exact" )
    print()
    print( "  template example:" )
    print( DmCompressionResponse.get_example_for_template().to_xml() )


if __name__ == "__main__":
    quick_smoke_test()
