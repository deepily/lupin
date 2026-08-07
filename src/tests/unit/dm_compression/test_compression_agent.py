"""
Tests for the Phase 2 compression agent — XML model, prompt construction, pipeline.

Same discipline as Phase 1: the centre of gravity is the falsification cases,
where the guard is removed and the suite is shown to go red. Two of the guards
here defend against SILENT failures, and a silent failure is exactly the kind a
test can appear to cover without covering it.

Nothing here calls a model. The live corpus run is separate.
"""

import re

import pytest

from cosa.agents.dm_compression.xml_models import (
    DmCompressionResponse,
    CDATA_OPEN,
    CDATA_CLOSE,
)
from cosa.agents.dm_compression.pipeline import compress_dm
from cosa.agents.dm_compression.freeze import freeze


# The body that made this whole file necessary: a placeholder AND a bare
# ampersand in the same message. Every structural check passes on it while the
# prose comes back wrong, so it is the shape that proves the CDATA handling.
SILENT_CORRUPTION_BODY = "Leak at [[L00]], fixed in [[L01]] & shipped Q&A"


def agent_template_of( agent ):
    """The template AFTER PromptTemplateProcessor ran, for change detection."""
    return agent.prompt_template


class TestXmlRoundTrip:

    @pytest.mark.parametrize( "payload", [
        "The queue drained cleanly overnight",
        "Q&A about the queue and a & b",
        "saw a <response> span in the log",
        "Q&A inside <tag> & more",
        SILENT_CORRUPTION_BODY,
        "first line\nsecond line\n\nfourth",
        'he said "the fix is in" yesterday',
        "already escaped &amp; and &lt;",
        "unicode 🦉 and 日本語 and — dashes",
        "trailing whitespace   ",
    ] )
    def test_payload_survives_byte_exact( self, payload ):
        model    = DmCompressionResponse( thoughts="t", compressed=payload )
        restored = DmCompressionResponse.from_xml( model.to_xml() ).compressed

        assert restored == payload

    def test_the_payload_is_carried_in_cdata_not_escaped( self ):
        """CDATA is the mechanism; entity-escaping would be a different design."""
        xml = DmCompressionResponse( thoughts="t", compressed="Q&A" ).to_xml()

        assert CDATA_OPEN in xml and CDATA_CLOSE in xml
        assert "Q&A" in xml, "the payload should sit verbatim inside CDATA"

    def test_thoughts_are_escaped_since_they_are_not_in_cdata( self ):
        model = DmCompressionResponse( thoughts="a & b < c", compressed="body" )

        assert DmCompressionResponse.from_xml( model.to_xml() ).thoughts == "a & b < c"

    def test_a_document_with_no_cdata_still_parses( self ):
        """The override must not break the ordinary path."""
        parsed = DmCompressionResponse.from_xml(
            "<response><thoughts>t</thoughts><compressed>plain body</compressed></response>"
        )
        assert parsed.compressed == "plain body"


class TestFalsificationOfTheCdataGuard:
    """
    🔴 The guard that matters most, shown to be load-bearing.

    Without the `from_xml` override the base class's ampersand repair rewrites
    the payload — and Phase 1's validator cannot see it, because a bare `&` in
    prose is neither a placeholder nor a verify-tier literal.
    """

    def test_the_base_class_alone_corrupts_the_payload( self ):
        """
        Reproduce the defect directly against the base implementation.

        If this ever stops failing, the base class was fixed and the override
        may be removable — check before deleting it.
        """
        from cosa.agents.io_models.utils.util_xml_pydantic import BaseXMLModel

        xml = (
            f"<response><thoughts>t</thoughts>"
            f"<compressed>{CDATA_OPEN}{SILENT_CORRUPTION_BODY}{CDATA_CLOSE}</compressed></response>"
        )

        # Bypass the override deliberately: this is the un-guarded behaviour.
        base_parsed = BaseXMLModel.from_xml.__func__( DmCompressionResponse, xml )

        assert base_parsed.compressed != SILENT_CORRUPTION_BODY, \
            "the base class no longer corrupts CDATA — re-evaluate whether the override is still needed"
        assert "&amp;" in base_parsed.compressed

    def test_the_override_is_what_makes_it_exact( self ):
        parsed = DmCompressionResponse.from_xml(
            f"<response><thoughts>t</thoughts>"
            f"<compressed>{CDATA_OPEN}{SILENT_CORRUPTION_BODY}{CDATA_CLOSE}</compressed></response>"
        )
        assert parsed.compressed == SILENT_CORRUPTION_BODY

    def test_the_corruption_would_be_INVISIBLE_to_phase_1( self ):
        """
        Why this guard is a safety fix and not a tidiness one.

        The corrupted body keeps every placeholder and every verify-tier
        literal, so Phase 1's validator returns ok and the damaged prose is
        delivered. Nothing downstream can catch it. That is what makes the
        CDATA handling the only thing standing between the agent and a silent
        corruption class.
        """
        from cosa.agents.dm_compression.freeze import validate

        body      = "Leak at judge.py:572 & shipped in d256e25a, 31 rows affected"
        frozen    = freeze( body )
        corrupted = frozen.frozen_text.replace( "&", "&amp;" )

        assert validate( corrupted, frozen ).ok, \
            "if this now fails, Phase 1 grew a check that catches it — update this test's premise"


class TestEmptyBodyIsRefused:

    @pytest.mark.parametrize( "empty", [ "", "   ", "\n\n", "\t" ] )
    def test_a_blank_compressed_body_raises( self, empty ):
        """A blank rewrite is a deletion. It belongs on the fail-closed path."""
        with pytest.raises( Exception ):
            DmCompressionResponse( thoughts="t", compressed=empty )


class TestPromptConstruction:
    """
    The §3b trap, guarded.

    The `</stop>` sentinel is injected only when the template carries the marker
    AND the routing command resolves in MODEL_MAPPING. Miss the registration and
    the prompt ships with a literal `{{PYDANTIC_XML_EXAMPLE}}` and no sentinel —
    and NOTHING RAISES. There is a second silent path to the same place:
    `AgentBase` wraps template processing in a bare `except`, so an error inside
    the processor is swallowed too. This test is what catches both.
    """

    @pytest.fixture( scope="class" )
    def agent( self ):
        from cosa.agents.dm_compression.compressor import DmCompressionAgent
        return DmCompressionAgent( frozen_text="A message with [[L00]] in it, long enough to matter." )

    def test_the_stop_sentinel_is_present( self, agent ):
        assert "</stop>" in agent.prompt, \
            "no sentinel — the routing command is probably missing from MODEL_MAPPING"

    def test_the_processor_actually_CHANGED_the_template( self, agent ):
        """
        The strongest form of this guard: assert processing did something.

        Checking for `</stop>` and the absent marker are both checks on the
        RESULT, and a future failure mode could satisfy them while the processor
        did nothing useful. Comparing the processed template against the raw file
        asserts the step ran at all — which is the thing two separate silent
        paths defeat. (María's suggestion, 2026-08-07.)
        """
        import cosa.utils.util as du

        raw = du.get_file_as_string(
            du.get_project_root() + "/src/conf/prompts/agents/dm-compression.txt"
        )

        assert agent_template_of( agent ) != raw, \
            "the processed template is byte-identical to the file on disk — processing did nothing"
        assert len( agent_template_of( agent ) ) > len( raw ), \
            "processing shortened the template; the XML example should have made it longer"

    def test_the_xml_marker_was_replaced( self, agent ):
        assert "{{PYDANTIC_XML_EXAMPLE}}" not in agent.prompt, \
            "the marker survived — template processing silently did nothing"

    def test_the_frozen_body_was_substituted( self, agent ):
        assert "[[L00]]" in agent.prompt
        assert "{dm_body}" not in agent.prompt

    def test_the_example_teaches_a_placeholder_passing_through( self, agent ):
        """The one behaviour the agent depends on absolutely."""
        marker = agent.prompt.index( "</stop>" )
        assert "[[L00]]" in agent.prompt[ :marker ]

    def test_get_example_for_template_returns_an_INSTANCE_not_a_string( self ):
        """
        The second silent path, pinned.

        `PromptTemplateProcessor` calls `.to_xml()` on whatever this returns. A
        string raises AttributeError there, `AgentBase` swallows it, and the
        prompt ships unprocessed with nothing logged.
        """
        example = DmCompressionResponse.get_example_for_template()

        assert isinstance( example, DmCompressionResponse )
        assert not isinstance( example, str )
        assert "</response>" in example.to_xml()

    def test_a_body_full_of_braces_does_not_break_substitution( self ):
        """
        `.replace()`, not `.format()`.

        DM bodies carry code fences and dict literals; `str.format` reads every
        brace as a field and raises on the first one it cannot resolve.
        """
        from cosa.agents.dm_compression.compressor import DmCompressionAgent

        hostile = 'config = { "a": 1, "b": {{nested}} } and [[L00]] survived it all'
        agent   = DmCompressionAgent( frozen_text=hostile )

        assert '{ "a": 1' in agent.prompt
        assert "[[L00]]" in agent.prompt


class TestPipelineFailClosed:
    """Every path that is not a clean success delivers the original."""

    BODY = (
        "I spent the morning tracing the leak and I am fairly confident it sits at "
        "judge.py:572, which is the line that shipped in d256e25a last Tuesday. The "
        "consumer thread returns before the pool callback has run, so the job stays "
        "in the running queue even though the work behind it finished cleanly. Have "
        "a look at src/cosa/rest/queue.py when you get a moment."
    )

    def _factory( self, transform ):
        class _Stub:
            def __init__( self, frozen_text ): self.frozen_text = frozen_text
            def run_prompt( self ): return { "thoughts": "t", "compressed": transform( self.frozen_text ) }
        return _Stub

    def test_a_good_rewrite_is_delivered_compressed( self ):
        shorten = lambda t: t.replace(
            "I spent the morning tracing the leak and I am fairly confident it sits at", "Leak at" )
        text, reason = compress_dm( self.BODY, agent_factory=self._factory( shorten ) )

        assert reason is None
        assert len( text ) < len( self.BODY )
        assert "judge.py:572" in text

    @pytest.mark.parametrize( "label,transform", [
        ( "dropped placeholder", lambda t: t.replace( "[[L00]]", "" ) ),
        ( "duplicated",          lambda t: t.replace( "[[L00]]", "[[L00]] [[L00]]" ) ),
        ( "mangled delimiter",   lambda t: t.replace( "[[L00]]", "(L00)" ) ),
        ( "invented",            lambda t: t + " [[L99]]" ),
        ( "glued neighbour",     lambda t: t.replace( "[[L00]]", "[[L00]]s" ) ),
        ( "altered integer",     lambda t: t.replace( "morning", "morning 42" ) ),
        ( "emptied",             lambda t: "" ),
    ] )
    def test_a_corrupted_rewrite_delivers_the_original( self, label, transform ):
        text, reason = compress_dm( self.BODY, agent_factory=self._factory( transform ) )

        assert text == self.BODY, f"{label} was delivered instead of the original"
        assert reason is not None

    def test_a_dead_model_delivers_the_original( self ):
        class _Dies:
            def __init__( self, frozen_text ): pass
            def run_prompt( self ): raise RuntimeError( "vLLM unreachable" )

        text, reason = compress_dm( self.BODY, agent_factory=_Dies )

        assert text == self.BODY
        assert "model call failed" in reason

    def test_a_truncated_response_delivers_the_original( self ):
        """
        The max_tokens degradation path, tested rather than assumed.

        Truncation means no `</response>` and no `</stop>`, so parsing fails and
        the original goes out. Too small is a YIELD problem, never a SAFETY one.
        """
        def _truncate( frozen ): return frozen[ : len( frozen ) // 2 ]

        text, reason = compress_dm( self.BODY, agent_factory=self._factory( _truncate ) )

        assert text == self.BODY
        assert reason is not None

    @pytest.mark.parametrize( "label,transform", [
        ( "longer than the original", lambda t: t + " and some extra words tacked on the end here" ),
        ( "byte-identical",           lambda t: t ),
        ( "trivially shorter",        lambda t: t.replace( "perfectly ", "" ) ),
    ] )
    def test_a_rewrite_that_bought_nothing_delivers_the_original( self, label, transform ):
        """
        🔴 "Valid" and "shorter" are different questions.

        Every structural check passes on a rewrite that is LONGER than what went
        in. The live run produced exactly that — three messages came back at
        -0.3%, -0.3% and -0.5% and were delivered as compressed. Paying seconds
        of delivery latency to make a message bigger is the worst outcome
        available, and nothing above this gate was asking.
        """
        text, reason = compress_dm( self.BODY, agent_factory=self._factory( transform ) )

        assert text == self.BODY, f"{label} was delivered as a compression"
        assert "no useful compression" in reason

    def test_a_genuinely_shorter_rewrite_still_gets_through( self ):
        """The gate must not reject real wins."""
        shorten = lambda t: t.replace(
            "I spent the morning tracing the leak and I am fairly confident it sits at", "Leak at" )
        text, reason = compress_dm( self.BODY, agent_factory=self._factory( shorten ) )

        assert reason is None
        assert len( text ) < len( self.BODY )

    def test_a_short_message_bypasses_without_calling_the_model( self ):
        called = []

        class _Tracker:
            def __init__( self, frozen_text ): called.append( 1 )
            def run_prompt( self ): return { "compressed": "x" }

        text, reason = compress_dm( "too short to bother with", agent_factory=_Tracker )

        assert text == "too short to bother with"
        assert "bypass" in reason
        assert not called, "the model must not be called on a bypassed message"

    @pytest.mark.parametrize( "blow_up", [
        lambda: ( _ for _ in () ).throw( RuntimeError( "vLLM said no" ) ),
        lambda: ( _ for _ in () ).throw( ValueError( "malformed XML" ) ),
        lambda: ( _ for _ in () ).throw( TimeoutError( "took too long" ) ),
        lambda: ( _ for _ in () ).throw( AttributeError( "something internal" ) ),
    ] )
    def test_the_pipeline_never_raises( self, blow_up ):
        """
        It sits in the delivery path, so an exception here drops a message.

        ⚠️ Deliberately `Exception` subclasses only. `KeyboardInterrupt` and
        `SystemExit` are `BaseException` and MUST still propagate — swallowing
        those would mean Ctrl-C could not stop a run. An earlier version of this
        test raised `KeyboardInterrupt` and read the correct behaviour as a
        failure.
        """
        class _Chaos:
            def __init__( self, frozen_text ): pass
            def run_prompt( self ): blow_up()

        text, reason = compress_dm( self.BODY, agent_factory=_Chaos )

        assert text == self.BODY
        assert reason is not None

    def test_no_path_delivers_an_unrestored_placeholder( self ):
        transforms = [
            lambda t: t,
            lambda t: t.replace( "[[L00]]", "" ),
            lambda t: t + " [[L99]]",
            lambda t: t[ :20 ],
        ]
        for transform in transforms:
            text, _ = compress_dm( self.BODY, agent_factory=self._factory( transform ) )
            assert not re.search( r"\[\[L\d+\]\]", text )


if __name__ == "__main__":
    pytest.main( [ __file__, "-v" ] )
