#!/usr/bin/env python3
"""
XML response model for the DM compression agent.

The rewriter receives a FROZEN message body — one whose immutable literals have
already been replaced by `[[L00]]` placeholders — and returns a shorter version
of the same message with every placeholder untouched.

WHY XML AND NOT JSON. Measured on 2,977 real DMs: 9% need XML escaping, 77%
need JSON escaping, and JSON's hostile characters (double quote 55%, newline
64%) are the two most common characters in this traffic after letters and
spaces — 19,195 characters requiring escape versus XML's 556, a factor of 34.5.
More decisive than the ratio: XML has `<![CDATA[ ... ]]>`, which lets us tell
the model "this span is literal, do not touch it". JSON has no equivalent, so it
would demand exactly the per-character transcription accuracy the freeze
protocol exists to stop depending on.

🔴 THE DEFECT THIS FILE EXISTS TO WORK AROUND, AND WHY IT IS THE DANGEROUS ONE.

`BaseXMLModel.from_xml()` escapes bare ampersands BEFORE parsing
(`util_xml_pydantic.py:193`) so that an LLM writing "Q&A" does not produce
invalid XML. Inside a CDATA section nothing is ever unescaped, so that injected
`&amp;` survives into the parsed value. The base class's own repair step is what
corrupts the payload:

    sent      "Q&A about the queue"
    returned  "Q&amp;A about the queue"

**Phase 1's validator cannot see it.** A bare `&` in prose is neither a
placeholder nor a verify-tier literal, so a body corrupted this way passes every
structural check and gets delivered. Fail-closed never fires. 88 corpus bodies
(3%) carry a bare `&`.

That makes the `from_xml` override below a safety fix, not a tidiness one — and
it is why the falsification test pairs an ampersand WITH a placeholder: that is
the shape where every structural check passes while the prose is wrong.

**Its obvious sibling is not silent, so it needs no workaround**: a body
containing `</response>` makes the base class's suffix-stripper truncate
mid-CDATA, `from_xml` raises `XMLParsingError`, and the pipeline fails closed.
Zero corpus bodies contain a root tag. Loud is fine; silent is not.

⚠️ Do not build on the base class's `</result>` / `</output>` handling. The
closing-tag loop's `break` sits outside its `if`, so only `</response>` is ever
reached — the other two are dead branches. Ours always uses `<response>`.
(Found by María, 2026-08-07. Not ours to fix here.)
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

        A blank rewrite is not a compression, it is a deletion. Raising here puts
        the message on the fail-closed path where the original is delivered,
        instead of letting an empty string travel as though it were a result.

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

        Hand-built rather than routed through xmltodict, because xmltodict would
        escape the payload into entities — and carrying the payload verbatim is
        the entire reason for using CDATA.

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
        Parse, holding the base class's ampersand repair OUT of CDATA spans.

        The base implementation escapes every bare `&` in the document before
        parsing. That is right for ordinary tag text and wrong for CDATA, where
        nothing is ever unescaped, so the injected `&amp;` lands in the value.

        The approach: lift every CDATA span out behind a sentinel, hand the
        remainder to the base class so all of its OTHER repairs still apply
        (prefix stripping, suffix stripping, entity fixing), then restore the
        spans verbatim.

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

        PLACEHOLDER CONTENT, per the convention every agent here follows. The
        injected example teaches SHAPE and must not read as an answer, because
        models copy a plausible-looking answer verbatim. The judge's own file
        records two earlier attempts that failed in opposite directions: an enum
        hint echoed back as malformed XML, and a filled plausible grade copied
        byte-for-byte.

        The `[[L00]]` here is deliberate — it shows the model that a placeholder
        passes through untouched, which is the one behaviour this agent depends
        on absolutely.

        ⚠️ Returns an INSTANCE, not a string. `PromptTemplateProcessor` calls
        `.to_xml()` on whatever comes back (`prompt_template_processor.py:99`).
        Returning an already-serialized string raises `AttributeError` there —
        and `AgentBase` wraps the whole processing step in a bare `except`
        (`agent_base.py:159`), so the exception is SWALLOWED and the template
        ships unprocessed: a literal `{{PYDANTIC_XML_EXAMPLE}}` in the prompt and
        no `</stop>` sentinel, with nothing raised anywhere. That is a second
        silent path to the same broken prompt the plan warns about in §3b, and
        the construction test is what catches both.

        Requires:
            - nothing

        Ensures:
            - returns a DmCompressionResponse instance (NOT a string)
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
