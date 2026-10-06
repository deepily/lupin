#!/usr/bin/env python3
"""
XML response model for the DM tutor agent.

The tutor receives a whole DM body and returns it distilled into the shape Rick specified.
That is one headline, which is a declaration or a question, and two supporting statements.
It also returns the most relevant file path or URL when the message carries one.

The prompt requires the model to return that path or URL, so the response has five slots.
Without the fifth slot the model had to smuggle the path into a statement slot, and a URL
ended up wedged mid-sentence. The fifth slot is optional. Most DMs carry no path, so
requiring it would reject messages for following the prompt correctly.

The format is XML and not JSON, as in the sibling model. Measured on 2,977 real DMs, 9% need
XML escaping and 77% need JSON escaping. JSON's two hostile characters are the double quote
(55%) and the newline (64%). They are the most common characters in this traffic after
letters and spaces. More decisive, XML has `<![CDATA[ ... ]]>`, which tells the model a span is literal.

Two silent failure paths shape this file.

The first is the ampersand repair. `BaseXMLModel.from_xml()` escapes bare ampersands before
parsing, so an LLM writing "Q&A" does not produce invalid XML. Nothing is ever unescaped
inside CDATA, so the injected `&amp;` survives into the parsed value. The base class's own
repair step corrupts the payload:

    sent      "Q&A about the queue"
    returned  "Q&amp;A about the queue"

Nothing downstream can see this, because a bare `&` in prose is not a structural feature.
A corrupted body passes every check and gets delivered. In the 2,977-body corpus, 88 bodies
(3%) carry a bare `&`. The `from_xml` override below is a correctness fix.

The second is the example, which must be an instance. `get_example_for_template()` returns
an instance, never a string. `PromptTemplateProcessor` calls `.to_xml()` on whatever comes
back, and `AgentBase` wraps that whole step in a bare `except`. Returning a string raises
`AttributeError`, the exception is swallowed, and the template ships unprocessed. The prompt
then holds a literal `{{PYDANTIC_XML_EXAMPLE}}` and no `</stop>` sentinel, and nothing is
raised anywhere. A missing `MODEL_MAPPING` entry produces the same broken prompt.
The construction smoke test asserts against both.

In the base class's closing-tag loop the `break` sits outside its `if`, so only `</response>`
is ever reached. This model always uses `<response>`, and the base class is left as it is.
"""

import re

from typing import ClassVar

from pydantic import Field, field_validator

from cosa.agents.io_models.utils.util_xml_pydantic import BaseXMLModel


# The CDATA wrapper. `]]>` occurs ZERO times in 2,977 corpus bodies, so the one
# sequence that could break the wrapper does not appear in this traffic.
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
_SENTINEL    = "__CDATA_SPAN_{}__"
_SENTINEL_RE = re.compile( r"__CDATA_SPAN_(\d+)__" )

# What an empty path slot may come back as. Models reach for a null word rather
# than leaving a tag blank, and a delivered line reading "N/A" is worse than no
# line at all. Compared lowercased and stripped.
NULL_ISH = {
    "", "none", "n/a", "na", "null", "nil", "-", "—", "not present",
    "no path", "no url", "none present", "not applicable", "empty"
}


class DmTutorResponse( BaseXMLModel ):
    """
    The tutor's response: its reasoning, the headline, two supports, one pointer.

    Shaped after `DmCompressionResponse`. Every field is `str`, because LLM I/O is text.
    Hyphenated tag names are not valid Python identifiers, so the fields use underscores
    and are aliased to the hyphenated tags Rick specified. Parsing reads his tags.
    """

    xml_tag_name: ClassVar[ str ] = "response"

    # The four tags carried in CDATA, in the order they are emitted. `thoughts`
    # is deliberately NOT in this list — it is reasoning, not payload, and it is
    # escaped conventionally so the base class's repairs apply to it in full.
    CDATA_FIELDS: ClassVar[ tuple ] = (
        "declaration_or_question", "supporting_1st", "supporting_2nd", "file_path_or_url"
    )

    # field name → the hyphenated tag it serializes to. Single source of truth
    # for both directions; a tag added here needs no other edit in this file.
    TAG_FOR_FIELD: ClassVar[ dict ] = {
        "thoughts"                : "thoughts",
        "declaration_or_question" : "declaration-or-question",
        "supporting_1st"          : "supporting-statement-1st",
        "supporting_2nd"          : "supporting-statement-2nd",
        "file_path_or_url"        : "file-path-or-url-if-present",
    }

    thoughts                : str = Field( default="", description="Reasoning about what this DM is actually saying" )
    declaration_or_question : str = Field( ...,        description="The single most important declaration, or the most important question asked",
                                           alias="declaration-or-question" )
    supporting_1st          : str = Field( ...,        description="The first supporting statement",
                                           alias="supporting-statement-1st" )
    supporting_2nd          : str = Field( ...,        description="The second supporting statement",
                                           alias="supporting-statement-2nd" )
    file_path_or_url        : str = Field( default="", description="The most relevant file path or URL from the DM, verbatim; empty when the DM contains none",
                                           alias="file-path-or-url-if-present" )

    model_config = { "populate_by_name": True }

    @field_validator( "thoughts", "file_path_or_url", mode="before" )
    @classmethod
    def _none_to_empty( cls, v ):
        """
        Coerce the None that an empty tag parses to into "".

        Both guarded fields are optional. An empty tag is the correct answer for each,
        for a model that skipped its reasoning and for a DM with no path in it.

        Requires:
            - v is a string or None

        Ensures:
            - returns "" for None; passes other values through unchanged
        """
        return "" if v is None else v

    @field_validator( "declaration_or_question", "supporting_1st", "supporting_2nd" )
    @classmethod
    def _reject_empty_required( cls, v ):
        """
        Refuse an empty headline or supporting statement.

        These three slots are the delivered message, so a blank one is a dropped slot, not a terse rewrite.
        Raising here puts the message on the fail-closed path, where the original is delivered.
        Otherwise a two-line delivery would travel as though it were a three-line one.

        Requires:
            - v is a string

        Ensures:
            - returns v unchanged when it holds any non-whitespace character

        Raises:
            - ValueError when v is empty or whitespace only
        """
        if v is None or not v.strip():
            raise ValueError( "a required slot came back empty — a dropped slot is not a rewrite" )
        return v

    # ──────────────────────────────────────────────────────────────────────────
    # Delivery
    # ──────────────────────────────────────────────────────────────────────────

    @property
    def pointer( self ):
        """
        The path/URL slot, or "" when it holds nothing worth delivering.

        A bare identifier in this slot is not a pointer. `to_delivery` appends the slot as its own line, so a row id there
        would arrive as a bare hash line. Rick's rule is that an out-of-context hash has no place there.
        An id is therefore treated like "N/A": the model signalled a pointer it does not have.

        Requires:
            - nothing

        Ensures:
            - returns "" for a blank slot or any of the NULL_ISH null-words
            - returns "" for a bare 8-hex row id, tested directly rather than through
              is_bare_identifier, whose precondition is a token the pointer grammar
              already matched and which on a raw value eats Makefile, README and src
            - returns the stripped value otherwise, so a real path, a bare
              filename.ext and a URL are all delivered unchanged
        """
        from cosa.agents.dm_tutor.sentences import is_bare_row_id

        value = ( self.file_path_or_url or "" ).strip()
        if value.lower() in NULL_ISH: return ""
        if is_bare_row_id( value ):   return ""
        return value

    @property
    def pointer_cleared( self ):
        """
        The value the pointer slot was refused for holding, or "" when nothing was.

        `pointer` silently drops a bare identifier, which is right for delivery but leaves nothing to audit.
        This names the refused value so the agent can log it. Null-words are not reported, because "N/A" is
        the model correctly saying it has no path, and reporting it would bury the real case in noise.

        Requires:
            - nothing

        Ensures:
            - returns the stripped value when it was refused as a bare identifier
            - returns "" for a real pointer, a blank slot and every null-word

        Raises:
            - nothing
        """
        from cosa.agents.dm_tutor.sentences import is_bare_row_id

        value = ( self.file_path_or_url or "" ).strip()
        if value.lower() in NULL_ISH: return ""
        return value if is_bare_row_id( value ) else ""

    def to_delivery( self ):
        """
        Assemble the lines a recipient would actually see.

        The path/URL is appended as its own final line and never folded into a statement.
        That separation is the reason the fifth slot exists.

        Requires:
            - the three required slots are non-empty (the validators guarantee it)

        Ensures:
            - returns headline + both supporting statements, newline-joined
            - appends the pointer as a fourth line when one is present
            - never emits a null-word line such as "N/A"
        """
        lines = [ self.declaration_or_question, self.supporting_1st, self.supporting_2nd ]
        if self.pointer: lines.append( self.pointer )
        return "\n".join( lines )

    # ──────────────────────────────────────────────────────────────────────────
    # Serialization
    # ──────────────────────────────────────────────────────────────────────────

    def to_xml( self, root_tag="response", pretty=True ):
        """
        Serialize with every payload slot wrapped in CDATA.

        Hand-built rather than routed through xmltodict, which would escape the payloads into entities.
        Carrying them verbatim is the reason for CDATA. `thoughts` is escaped conventionally, because it
        is reasoning, never delivered, and never required to survive byte-exact.

        Requires:
            - the three required slots are non-empty

        Ensures:
            - returns a well-formed <response> document
            - each CDATA payload sits unescaped inside its section
            - from_xml( self.to_xml() ) round-trips every payload byte-exact
        """
        thoughts = (
            _BARE_AMPERSAND.sub( "&amp;", self.thoughts )
            .replace( "<", "&lt;" )
            .replace( ">", "&gt;" )
        )

        lines = [ f"<{root_tag}>", f"  <thoughts>{thoughts}</thoughts>" ]

        for field_name in self.CDATA_FIELDS:
            tag   = self.TAG_FOR_FIELD[ field_name ]
            value = getattr( self, field_name )
            lines.append( f"  <{tag}>{CDATA_OPEN}{value}{CDATA_CLOSE}</{tag}>" )

        lines.append( f"</{root_tag}>" )
        return "\n".join( lines )

    @classmethod
    def from_xml( cls, xml_string ):
        """
        Parse, keeping the base class's ampersand repair out of CDATA spans.

        The base class escapes every bare `&` before parsing, which is wrong inside CDATA, where nothing is unescaped.
        This method lifts every CDATA span out behind a sentinel and hands the remainder to the base class.
        Its other repairs still apply (prefix, suffix and entity fixing), and the spans are restored verbatim.

        Requires:
            - xml_string is a string

        Ensures:
            - CDATA payloads survive byte-exact, ampersands included
            - all non-CDATA text still receives the base class's repairs
            - a document with no CDATA behaves exactly as the base class does

        Raises:
            - XMLParsingError when the document cannot be parsed (unchanged)
            - ValidationError when a required slot is missing or empty
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
            # alone rather than guessing: the caller's business, not ours.
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

        The content is placeholder text. The example teaches shape and must not read as an answer, because models copy one verbatim.
        The path slot's placeholder states its own emptiness rule, since its correct value is often nothing and a model shown only
        filled examples invents one. This returns an instance, not a string; the module docstring says what breaks otherwise.

        Requires:
            - nothing

        Ensures:
            - returns a DmTutorResponse instance, not a string
        """
        return cls(
            thoughts                = "Your reasoning about what this DM is actually saying",
            declaration_or_question = "The single most important declaration, or the most important question asked",
            supporting_1st          = "The first supporting statement",
            supporting_2nd          = "The second supporting statement",
            file_path_or_url        = "The most relevant file path or URL from the DM, verbatim; empty when the DM contains none",
        )


def quick_smoke_test():
    """Round-trip the model against the payloads that break the base class."""
    import cosa.utils.util as du

    du.print_banner( "DmTutorResponse smoke test" )

    cases = {
        "plain"            : "The queue drained cleanly overnight",
        "ampersand"        : "Q&A about the queue and a & b",
        "angle brackets"   : "saw a <response> span in the log",
        "mixed"            : "Q&A inside <tag> & more",
        "🔴 the silent one" : "Leak at src/foo.py:12, fixed in f4e0370 & shipped",
        "multiline"        : "first line\nsecond line\n\nfourth",
        "quotes"           : 'he said "the fix is in" yesterday',
        "entities"         : "already escaped &amp; and &lt;",
    }

    failures = 0
    for name, payload in cases.items():
        restored = DmTutorResponse.from_xml(
            DmTutorResponse(
                thoughts="t", declaration_or_question=payload,
                supporting_1st="s1", supporting_2nd="s2", file_path_or_url=""
            ).to_xml()
        ).declaration_or_question
        ok        = restored == payload
        failures += 0 if ok else 1
        print( f"  {name:<18} {'✓' if ok else '✗'}  {restored!r}" )

    print()
    print( f"  round trip: {len( cases ) - failures}/{len( cases )} exact" )

    # The optional slot, both ways.
    filled = DmTutorResponse(
        declaration_or_question="d", supporting_1st="s1", supporting_2nd="s2",
        file_path_or_url="src/cosa/agents/dm_tutor/agent.py:42"
    )
    empty = DmTutorResponse(
        declaration_or_question="d", supporting_1st="s1", supporting_2nd="s2",
        file_path_or_url="N/A"
    )

    print()
    print( f"  pointer, filled : {filled.pointer!r}" )
    print( f"  pointer, N/A    : {empty.pointer!r}  (null-word suppressed)" )
    print( f"  delivery lines  : {len( filled.to_delivery().splitlines() )} filled / "
           f"{len( empty.to_delivery().splitlines() )} empty" )

    print()
    print( "  template example:" )
    print( DmTutorResponse.get_example_for_template().to_xml() )


if __name__ == "__main__":
    quick_smoke_test()
