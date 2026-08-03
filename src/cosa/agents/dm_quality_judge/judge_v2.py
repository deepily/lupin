#!/usr/bin/env python3
"""
DM Quality Judge **v2** — the model locates the verdict; Python computes the grade.

WHAT CHANGED FROM v1, AND WHY. v1 asked one model call to GRADE Directness and Tone.
Measured live 2026-08-01 over four bodies crossing {verdict leads, buried} x {plain,
jargon}, three runs each, 15/15 identical: hold the prose jargony and the model can no
longer tell a leading verdict from a buried one, and the error is always toward `good`.
It grades that same body `bad` on Tone and names the invented vocabulary correctly, so
it is not blind to the jargon — it graded the document's REGISTER instead of the first
sentence's CONTENT. A grade can never be checked. So v2 stops asking for one.

    Directness : the model quotes the earliest sentence that states a payload, gives
                 its number, and lists the stray sentences after it. Python checks all
                 three against the source text and computes the weight.
    Tone       : v1's rubric, unchanged — it was never the defect — with its evidence
                 field moved AHEAD of its grade field.
    Length     : v1's Python bucket, imported.
    Overall    : v1's combination, imported.

HOW FAR THE GUARANTEE GOES. Position is fully validated: an invented, paraphrased or
miscounted quote is REJECTED, not averaged in. The stray classification is NOT — that
is the same payload judgement the model failed at, and the indices list makes it
checkable for shape, not for truth. So the result carries BOTH weights: `weight` (final)
and `position_weight` (the grounded half), and the probe reports them as separate
columns. The plan says this out loud; so does this module.

v1 is untouched and remains the live path. Selection is by INI key, default 1.

References:
    - src/rnd/v0.1.9/2026.07.31-dm-verbosity-reduction/2026.08.01-dm-judge-v2-plan.md
    - src/cosa/agents/dm_quality_judge/xml_models_v2.py (schemas + validator + tables)
"""

import time

import cosa.utils.util as cu
from cosa.agents.llm_client_factory import LlmClientFactory
from cosa.agents.io_models.utils.prompt_template_processor import PromptTemplateProcessor

# Everything deterministic is v1's and is IMPORTED, never re-declared. The repair layer
# in particular encodes six separately-diagnosed live failure modes (spaced tags,
# multi-word tags, unclosed prolog, missing root, unclosed children, the curly-brace
# degenerate mode) — v2 gets all of them, and a fix to either version fixes both.
from cosa.agents.dm_quality_judge.judge import (
    QUALITATIVE_WORD_LIMIT,
    _repair_llm_xml,
    _is_garbage_output,
    _fallback_dimension,
    _withheld_dimension,
    _too_long_dimension,
    _get_qualitative_enabled,
    length_bucket,
    combine_overall,
)
from cosa.agents.dm_quality_judge.xml_models import WEIGHT_TO_EMOJI, NONANSWER_EMOJI
from cosa.agents.dm_quality_judge.xml_models_v2 import (
    DIRECTNESS_FIELDS,
    TONE_FIELDS,
    CONCISION_ADJUSTMENT_ENABLED,
    DmDirectnessExtraction,
    DmToneJudgement,
    ExtractionError,
    directness_weight,
    number_sentences,
    parse_index,
    parse_indices,
    position_weight,
    split_sentences,
    structural_code,
    validate_extraction,
)


DEFAULT_JUDGE_LLM_SPEC_KEY   = "dm_quality_judge_v2/phi_4"
DEFAULT_DIRECTNESS_PROMPT    = "/src/conf/prompts/dm-quality-judge-v2-directness.txt"
DEFAULT_TONE_PROMPT          = "/src/conf/prompts/dm-quality-judge-v2-tone.txt"

_DIRECTNESS_ROUTING_COMMAND  = "dm quality judge v2 directness"
_TONE_ROUTING_COMMAND        = "dm quality judge v2 tone"

# The NON-ANSWER this version adds, and the reason it must be its own string.
#
# The discrimination probe classifies a dimension result by its detail text and DROPS
# non-answers from the ordering, because a real `meh` and a parse failure are both
# weight 0 and an undropped fallback can satisfy an ordering test while measuring
# nothing (row ca7a2cbf). v2 introduces a NEW way to fail — the model answered, the XML
# parsed, and the extraction did not survive checking against the source text. That is
# not "unavailable" and not "too long", so it does not get to wear either of their
# faces. Register it in the probe's non-answer set or it wears a real grade's costume.
_EXTRACTION_FAILED_DETAIL    = "not graded: extraction could not be verified against the message"

# Retry anchor, same trick as v1 (bug d02eaaa7): attempt 1 is the clean prompt, so
# inputs that already parse never see the nudge.
_RETRY_NUDGE                 = "Begin your reply with <response>.\n\n"

# A retry that repeats the identical prompt at temperature 0 gets the identical answer.
# Measured 2026-08-01: on BURIED_PLAIN the model quoted "The timeout is set to thirty
# seconds and it should be five." for a sentence reading "Anyway, the timeout is set to
# thirty seconds and it should be five." — it dropped the discourse marker, 3/3 runs,
# and all three were correctly refused. Three identical calls, one piece of information.
#
# So a retry after a FAILED CHECK carries the checker's own complaint back to the model.
# This is not leniency: the check is unchanged and still rejects a paraphrase. It just
# stops spending two of the three attempts asking the same question the same way.
_RETRY_AFTER_REJECTION = (
    "Your previous answer was REJECTED by an automatic check:\n"
    "    {reason}\n\n"
    "Copy the sentence EXACTLY as it appears on its numbered line — every word from the "
    "first to the last, including any opening word such as \"Anyway\", \"So\", or \"But\", "
    "and including its final punctuation. Do not shorten, tidy, or re-word it.\n\n"
)


def _extraction_failed_dimension( reason ):
    """
    The directness result when the model answered but its extraction did not verify.

    Ensures:
        - weight is None, like every other non-answer: the model answered but its answer
          did not survive checking, which is not an opinion of `meh`. A 0 here would be
          averaged into Overall as a considered neutral grade (measured 2026-08-01 on
          Maria's 527-word DM, which came out SOFTER than Length alone because of it)
        - the detail NAMES this as an unverified extraction — distinct from
          judge-unavailable and from over-length, because three different silences must
          not report as one
        - position_weight is None too: there is no grounded half to report when the
          extraction itself was refused
    """
    return { "emoji"           : NONANSWER_EMOJI[ "unverified" ],
             "weight"          : None,
             "position_weight" : None,
             "detail"          : f"{_EXTRACTION_FAILED_DETAIL} ({reason})" }


class DmQualityJudgeV2:
    """
    Grade a peer-DM body on Length (Python) + Directness (extraction) + Tone (rubric).

    Requires:
        - for the qualitative dimensions: a vLLM server serving the v2 spec key
          (a missing server degrades gracefully — see Ensures)

    Ensures:
        - judge() returns {"length", "directness", "tone", "overall"} — the SAME shape
          v1 returns, so the caller in rest/routers/dm.py needs no branch
        - never raises: any failure degrades to a NAMED non-answer
        - the directness dict additionally carries "position_weight" and "structure",
          which v1 has no analogue for; consumers that do not know about them ignore
          them harmlessly
    """

    def __init__(
        self,
        llm_spec_key             = DEFAULT_JUDGE_LLM_SPEC_KEY,
        directness_prompt_path   = DEFAULT_DIRECTNESS_PROMPT,
        tone_prompt_path         = DEFAULT_TONE_PROMPT,
        debug                    = False,
        verbose                  = False,
        qualitative_enabled      = None,
    ):
        """
        Initialize the v2 judge.

        Requires:
            - llm_spec_key is a model key resolvable by LlmClientFactory

        Ensures:
            - builds the LLM client + prompt processor; available=True on success
            - a client-build failure sets available=False (judge() then falls back)
            - qualitative_enabled=None reads the INI; an explicit bool is the INJECTION
              SEAM the discrimination probe uses. Without it the probe would run at the
              operator's ambient toggle — which is OFF — and measure withheld
              non-answers, i.e. pass while measuring nothing. v1 has the same seam and
              the probe already uses it; v2 must keep it or the probe cannot see v2.
        """
        self.debug                  = debug
        self.verbose                = verbose
        self.llm_spec_key           = llm_spec_key
        self.directness_prompt_path = directness_prompt_path
        self.tone_prompt_path       = tone_prompt_path
        self._available             = False
        self._client                = None
        self.qualitative_enabled    = ( _get_qualitative_enabled()
                                        if qualitative_enabled is None else bool( qualitative_enabled ) )

        if not self.qualitative_enabled:
            print( "[DmQualityJudgeV2] qualitative judging OFF — Length only (row ca7a2cbf)" )

        try:
            factory         = LlmClientFactory( debug=debug, verbose=verbose )
            self._client    = factory.get_client( llm_spec_key, debug=debug, verbose=verbose )
            self._available = True
            if self.debug: print( f"[DmQualityJudgeV2] LLM client ready ({llm_spec_key})" )
        except Exception as e:
            print( f"[DmQualityJudgeV2] LLM client unavailable: {e}" )
            self._available = False

        self._processor = PromptTemplateProcessor( debug=debug, verbose=verbose )

    @property
    def available( self ):
        """Whether the LLM client is available for the qualitative dimensions."""
        return self._available

    def judge( self, body_text ):
        """
        Grade one DM body. Same contract and same return shape as v1.judge().

        Requires:
            - body_text is a string (the composed DM body, before any stamp/frame)

        Ensures:
            - returns {"length", "directness", "tone", "overall"} — always this shape
            - never raises
            - Length and Overall are v1's, unchanged

        Args:
            body_text: the DM body to grade

        Returns:
            dict: the full quality grade
        """
        word_count = len( body_text.split() )
        length     = length_bucket( word_count )

        if not self.qualitative_enabled:
            directness = _withheld_dimension()
            tone       = _withheld_dimension()
        elif word_count > QUALITATIVE_WORD_LIMIT:
            directness = _too_long_dimension( word_count )
            tone       = _too_long_dimension( word_count )
        else:
            directness = self._grade_directness( body_text )
            tone       = self._grade_tone( body_text )

        overall = combine_overall(
            length[ "weight" ], directness[ "weight" ], tone[ "weight" ], length[ "detail" ]
        )
        return { "length": length, "directness": directness, "tone": tone, "overall": overall }

    def _build_prompt( self, template_path, routing_command, marker, value ):
        """
        Load a v2 template, inject its XML example, and substitute the one placeholder.

        Requires:
            - template_path is project-root-relative; routing_command is registered in
              PromptTemplateProcessor.MODEL_MAPPING
            - marker is the literal placeholder text (e.g. "{dm_body}")

        Ensures:
            - returns the finished prompt string
            - uses .replace(), NEVER .format(): str.format treats every brace in the
              string as a field, and two independent sources put literal braces here —
              the injected example's {terrible|bad|meh|good|exemplary} placeholder, and
              any DM body containing a dict, f-string or JSON snippet, which peers paste
              constantly. That crash lived OUTSIDE v1's retry block and broke its own
              never-raises contract until it was found on 2026-08-01.
        """
        raw       = cu.get_file_as_string( cu.get_project_root() + template_path )
        processed = self._processor.process_template( raw, routing_command )
        return processed.replace( marker, value )

    def _call_with_retry( self, prompt, parse_fn, known_fields ):
        """
        Run one prompt through the model with v1's 3-attempt/backoff discipline.

        Requires:
            - prompt is the finished prompt string
            - parse_fn takes the model's raw text and returns the caller's dimension
              dict, raising on anything it cannot verify
            - known_fields is the schema's canonical child tags. The repair layer
              rebuilds the response from the fields it is told about and drops the
              rest, so passing the wrong tuple deletes data silently rather than
              raising — the two v2 schemas therefore pass their OWN tuples

        Ensures:
            - returns parse_fn's result on the first attempt that succeeds
            - returns ( None, last_error ) shape? NO — returns None on exhaustion, and
              the caller decides which named non-answer that becomes, because "the
              server is down" and "the model's answer did not verify" are different
              silences and must not collapse into one
            - never raises
        """
        last_error = None
        for attempt in range( 1, 4 ):
            try:
                effective = prompt
                if attempt > 1:
                    # A rejected CHECK gets a specific complaint; anything else (bad
                    # XML, degenerate output) gets the generic reply-anchor.
                    if isinstance( last_error, ExtractionError ):
                        effective = _RETRY_AFTER_REJECTION.format( reason=last_error ) + prompt
                    else:
                        effective = _RETRY_NUDGE + prompt
                raw       = self._client.run( effective )
                if self.debug: print( f"[DmQualityJudgeV2] raw (attempt {attempt}): {raw[ :200 ]}" )
                if _is_garbage_output( raw ):
                    raise ValueError( "garbage output: degenerate repeated-character response" )
                return parse_fn( _repair_llm_xml( raw, known_fields ) ), None
            except Exception as e:
                last_error = e
                if attempt < 3:
                    backoff = 0.5 * attempt
                    print( f"[DmQualityJudgeV2] transient on attempt {attempt}, retrying in {backoff}s: {e}" )
                    time.sleep( backoff )
                    continue
                print( f"[DmQualityJudgeV2] failed after 3 attempts: {e}" )
        return None, last_error

    def _grade_directness( self, body_text ):
        """
        Locate the verdict, verify the location, and compute the weight in Python.

        Requires:
            - body_text is a string

        Ensures:
            - returns {"emoji","weight","position_weight","structure","detail"}
            - the model NEVER supplies the weight — it supplies a quote, an index and a
              stray list, each checked against the source before any number is derived
            - an unverifiable extraction returns the NAMED extraction-failed non-answer,
              not a grade
            - the client being unavailable returns v1's judge-unavailable fallback
        """
        if not self._available:
            if self.debug: print( "[DmQualityJudgeV2] LLM unavailable — directness fallback" )
            return _fallback_dimension()

        # ONE split, ONE list: the sentences shown to the model and the sentences the
        # validator checks against are the same value passed through. Two independent
        # splits could disagree and would reject correct model output.
        sentences = split_sentences( body_text )
        if not sentences:
            return _extraction_failed_dimension( "body has no sentences" )

        prompt = self._build_prompt(
            self.directness_prompt_path, _DIRECTNESS_ROUTING_COMMAND,
            "{numbered_dm_body}", number_sentences( sentences )
        )

        def parse( repaired ):
            parsed        = DmDirectnessExtraction.from_xml( repaired )
            index         = parse_index( parsed.first_payload_index )
            strays        = parse_indices( parsed.stray_after_indices )
            quote         = parsed.first_payload_quote
            validate_extraction( quote, index, strays, sentences )
            structure     = structural_code( index, len( strays ) )
            weight        = directness_weight( index, len( strays ) )
            # stray_count and structure are REPORTED but (by default) NOT SCORED — see
            # CONCISION_ADJUSTMENT_ENABLED. Carrying them keeps the follow-up work
            # supplied with data instead of making it start over.
            return { "emoji"           : WEIGHT_TO_EMOJI[ weight ],
                     "weight"          : weight,
                     "position_weight" : position_weight( index ),
                     "structure"       : structure,
                     "stray_count"     : len( strays ),
                     "detail"          : self._directness_detail( structure, index, strays, sentences ) }

        result, error = self._call_with_retry( prompt, parse, DIRECTNESS_FIELDS )
        if result is not None: return result
        if isinstance( error, ExtractionError ):
            return _extraction_failed_dimension( str( error ) )
        return _fallback_dimension()

    def _directness_detail( self, structure, index, strays, sentences ):
        """
        A human-readable one-liner for the directness result.

        Ensures:
            - names the structure, where the verdict sits, and how many strays followed
            - says nothing the checks did not establish
        """
        if structure == "missing":
            return f"no sentence states a result, decision, or request ({len( sentences )} sentences)"
        where = "leads" if index == 1 else f"is sentence {index} of {len( sentences )}"
        if not strays:
            return f"the verdict {where}"
        # Say "not scored" out loud when the strays are observed but unweighted. A
        # detail line that reports a count next to a grade reads as if the count moved
        # the grade; on the shipped setting it did not, and a reader should not have to
        # know a flag's value to tell which.
        scored = "" if CONCISION_ADJUSTMENT_ENABLED else ", not scored"
        return f"the verdict {where}; {len( strays )} stray sentence(s) after it{scored}"

    def _grade_tone( self, body_text ):
        """
        Grade Tone on v1's rubric, evidence field first.

        Requires:
            - body_text is a string

        Ensures:
            - returns {"emoji","weight","detail"} — v1's dimension shape exactly
            - a failure returns v1's judge-unavailable fallback
        """
        if not self._available:
            if self.debug: print( "[DmQualityJudgeV2] LLM unavailable — tone fallback" )
            return _fallback_dimension()

        prompt = self._build_prompt(
            self.tone_prompt_path, _TONE_ROUTING_COMMAND, "{dm_body}", body_text
        )

        def parse( repaired ):
            parsed = DmToneJudgement.from_xml( repaired )
            return { "emoji"  : parsed.tone_emoji(),
                     "weight" : parsed.tone_weight(),
                     "detail" : parsed.tone_evidence }

        result, _error = self._call_with_retry( prompt, parse, TONE_FIELDS )
        return result if result is not None else _fallback_dimension()


def quick_smoke_test():
    """Smoke test for the v2 judge's Python-only paths (no LLM call)."""
    print( "\n" + "=" * 60 )
    print( "DM Quality Judge v2 — judge smoke test (no LLM)" )
    print( "=" * 60 )

    passed = failed = 0

    print( "\n1. Length-only mode returns v1's withheld shape..." )
    try:
        judge  = DmQualityJudgeV2( qualitative_enabled=False )
        result = judge.judge( "Short and to the point." )
        assert result[ "directness" ][ "weight" ] is None
        assert result[ "tone" ][ "weight" ]       is None
        assert result[ "overall" ][ "weight" ]    == result[ "length" ][ "weight" ]
        print( "   ✓ directness/tone withheld, overall IS the length grade" ); passed += 1
    except Exception as e:
        print( f"   ✗ {type( e ).__name__}: {e}" ); failed += 1

    print( "\n2. The extraction-failed non-answer is its own string..." )
    try:
        d = _extraction_failed_dimension( "quote does not equal sentence 1" )
        assert d[ "weight" ] is None and d[ "position_weight" ] is None
        assert _EXTRACTION_FAILED_DETAIL in d[ "detail" ]
        from cosa.agents.dm_quality_judge.judge import _JUDGE_UNAVAILABLE_DETAIL, _TOO_LONG_DETAIL
        assert d[ "detail" ] != _JUDGE_UNAVAILABLE_DETAIL
        assert not d[ "detail" ].startswith( _TOO_LONG_DETAIL )
        print( "   ✓ distinct from judge-unavailable and from too-long" ); passed += 1
    except Exception as e:
        print( f"   ✗ {type( e ).__name__}: {e}" ); failed += 1

    print( f"\n{'=' * 60}" )
    print( f"v2 judge smoke test: {passed} passed, {failed} failed" )
    print( "=" * 60 )
    return failed == 0


if __name__ == "__main__":
    exit( 0 if quick_smoke_test() else 1 )
