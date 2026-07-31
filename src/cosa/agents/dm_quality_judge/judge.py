#!/usr/bin/env python3
"""
DM Quality Judge — hybrid grader for a peer-DM body.

    - Length  : Python-only 5-level bucket on the word count (LLMs count badly).
    - Directness + Tone : one fixed-rubric Mistral judge call (this module).
    - Overall : Python combination, equal weight to the quantitative (Length) vs
                the qualitative (Directness+Tone) CATEGORY, round-half-up.

Modeled on cosa/agents/notification_proxy/verification.py (LlmAnswerVerifier):
same LlmClientFactory client, same PromptTemplateProcessor, same 3-attempt/backoff
retry, same graceful-degradation contract (a failure NEVER raises to the caller —
it returns a safe all-🤷/0 result and the DM still sends).

References:
    - src/cosa/agents/dm_quality_judge/xml_models.py (DmQualityJudgeResponse, GRADE_TABLE)
    - src/conf/prompts/dm-quality-judge.txt (prompt template)
    - src/rnd/v0.1.9/2026.07.31-dm-verbosity-reduction/ (design)
"""

import math
import re
import time

import cosa.utils.util as cu
from cosa.agents.llm_client_factory import LlmClientFactory
from cosa.agents.dm_quality_judge.xml_models import DmQualityJudgeResponse, WEIGHT_TO_EMOJI
from cosa.agents.io_models.utils.prompt_template_processor import PromptTemplateProcessor


# The judge's OWN model spec key (Reviewer nit, Krishna 2026-07-31): a DISTINCT
# INI entry, NOT a repurpose of the fleet-shared `confidentialmind/mistral_small_24b`.
# NOTE ON HOST: the design doc verified the endpoint as `localhost:3001`, but that
# was a HOST-shell curl. This judge runs INSIDE the FastAPI container, where
# `localhost` is the container — so the config value points at the container-
# reachable `192.168.1.21:3001` (the same box the working mistral key already
# reaches from in-container). See the ini comment on `dm_quality_judge/...`.
DEFAULT_JUDGE_LLM_SPEC_KEY  = "dm_quality_judge/mistral_small_24b"
DEFAULT_JUDGE_PROMPT_PATH   = "/src/conf/prompts/dm-quality-judge.txt"

# The routing_command the prompt template is registered under in
# PromptTemplateProcessor.MODEL_MAPPING (drives {{PYDANTIC_XML_EXAMPLE}} injection).
_JUDGE_ROUTING_COMMAND      = "dm quality judge"

_JUDGE_UNAVAILABLE_DETAIL   = "judge unavailable"

# Above this word count the qualitative LLM pass is SKIPPED and Directness/Tone
# return the honest 🤷/0 fallback (bug 2a41e141, Rick-ratified 2026-07-31 "option 1").
#
# WHY A CEILING EXISTS: the Mistral-Small-24B GPTQ judge genuinely grades and
# discriminates on short/medium DMs (measured live: a verdict-first DM → directness
# "good", a rambling no-verdict DM → "meh"/"needs_improvement", NOT parroted). But on
# long input it DEGENERATES regardless of prompt format (XML or key:value), example
# style (concrete or slot), delimiters, or markdown-cleaning — it copies the format
# placeholder token or echoes the DM's own content instead of judging. The 527-word
# MARIA-RAW reference sample parroted the prompt's worked example byte-for-byte. The
# onset is content-dependent (noisy markdown/emoji degrades earlier than clean prose,
# which holds to ~200w), so 150 is set CONSERVATIVELY below the clean-prose limit and
# far past the ~60-word DM target. This is not a loss: the Python LENGTH dimension
# already grades anything past 250w at 😞/−2, so verbosity — the signal this project
# actually targets — is still penalized directly; only the qualitative BONUS signal is
# withheld where the model cannot produce it. Chunk-and-aggregate and a stronger model
# were both considered and rejected as not worth the complexity for a bonus signal.
# Full finding: bug 2a41e141 (Krishna's evidence writeup) + this session's 8-variant probe.
QUALITATIVE_WORD_LIMIT      = 150

_TOO_LONG_DETAIL            = "not judged: DM too long for reliable qualitative grading"


# Matches ONE angle-bracket tag, tolerating the sloppiness the live 24B GPTQ model
# emits (bug a5f7b36d): leading/inner whitespace, a spaced slash (`< / tone >`), and
# multi-word / spaced-underscore tag names (`< directness note >`, `< directness _
# note >`). Group 1 = optional slash, group 2 = the raw (possibly spaced) tag name.
_TAG_RE = re.compile( r"<\s*(/?)\s*([A-Za-z][A-Za-z0-9_ ]*?)\s*>" )


def _repair_llm_xml( raw ):
    """
    Repair the malformed XML the live Mistral judge emits into parseable XML.

    The 24B GPTQ model produces (captured in src/tests/unit/fixtures/dm_judge/):
        - an unclosed prolog:  `<?xml version="1.0" encoding "utf-8" ?`  (no `>`)
        - spaced tags:         `< response >`, `< / directness >`
        - multi-word tags:     `< directness note >`, `< directness _ note >`

    Requires:
        - raw is a string (the model's verbatim output)

    Ensures:
        - drops any `<?xml ...` prolog (even unclosed — stops at the next `<`, so it
          never devours the real content)
        - collapses each tag's inner whitespace/underscores to ONE underscore and
          removes the spaces around the brackets/slash
        - returns only the `<response>...</response>` span when both ends are present
          (drops a trailing `</stop>` sentinel or any post-root chatter)
        - when the root wrapper is MISSING (bug 46690a76 — the model drops
          `<response>` on long input and emits bare top-level siblings, sometimes
          with an orphan `</response>`), synthesizes a single root around the known
          child-tag span so xmltodict does not reject it as multi-root
        - truly unrecoverable output (no known child tags) is returned as-is so
          from_xml() raises and the judge degrades to 🤷/0
        - returns the repaired string stripped; never raises
    """
    # Drop a (possibly unclosed) XML declaration — up to the next '<' only, so an
    # unclosed `<?xml ... ?` cannot greedily consume the opening <response> tag.
    raw = re.sub( r"<\?xml[^<]*", "", raw )

    def _fix_tag( m ):
        slash = "/" if m.group( 1 ) == "/" else ""
        name  = re.sub( r"[\s_]+", "_", m.group( 2 ).strip() )
        return f"<{slash}{name}>"

    raw = _TAG_RE.sub( _fix_tag, raw )

    start = raw.find( "<response>" )
    end   = raw.find( "</response>" )
    if start != -1 and end != -1:
        # Well-formed-enough: keep only the <response>...</response> span (drops a
        # trailing </stop> sentinel or any post-root chatter).
        return raw[ start : end + len( "</response>" ) ].strip()

    # MISSING/implicit root (bug 46690a76): strip any stray wrapper fragments and
    # rebuild ONE root around the known child-tag span (first known open tag →
    # last known close tag). Excludes any leading prose / orphan </response>.
    raw = raw.replace( "<response>", "" ).replace( "</response>", "" )
    first = re.search( r"<(?:directness|directness_note|tone|tone_note)>", raw )
    if first is not None:
        last_end = -1
        for close in ( "</tone_note>", "</tone>", "</directness_note>", "</directness>" ):
            idx = raw.rfind( close )
            if idx != -1:
                last_end = max( last_end, idx + len( close ) )
        if last_end != -1:
            return f"<response>{raw[ first.start() : last_end ]}</response>"
    return raw.strip()


def length_bucket( word_count ):
    """
    Deterministic 5-level Length grade on a word count (no LLM).

    The table (Rick 2026-07-31, row-5 boundary fixed to 251+ by Krishna's review
    so 250 is unambiguously row 4):

        ≤ 60   → ⭐ +2     91–150  → 🤷  0     251+ → 😞 −2
        61–90  → 👍 +1     151–250 → 👎 −1

    Requires:
        - word_count is a non-negative int

    Ensures:
        - returns {"emoji", "weight", "detail"} with a weight in [-2, 2]
        - the boundaries are inclusive-left as written above (60→⭐, 61→👍, ...)
    """
    if   word_count <=  60: emoji, weight = "⭐", 2
    elif word_count <=  90: emoji, weight = "👍", 1
    elif word_count <= 150: emoji, weight = "🤷", 0
    elif word_count <= 250: emoji, weight = "👎", -1
    else:                   emoji, weight = "😞", -2
    return { "emoji": emoji, "weight": weight, "detail": f"{word_count} words, target ~60" }


def round_half_up( x ):
    """
    Round half UP (toward +infinity on a .5 tie) — a deliberate, explicit tie-break.

    NOT Python's built-in round(), which rounds half-to-EVEN and would be
    inconsistent boundary-to-boundary. Ties are intentionally LENIENT: −0.5 → 0,
    +0.5 → 1 (a DM on a category boundary rounds toward the kinder grade).

    Requires:
        - x is a real number

    Ensures:
        - returns int( floor( x + 0.5 ) ): 0.5→1, −0.5→0, 1.5→2, −1.5→−1
    """
    return int( math.floor( x + 0.5 ) )


def combine_overall( length_weight, directness_weight, tone_weight, length_detail ):
    """
    Combine the three dimension weights into the OVERALL grade.

    Equal weight to the two CATEGORIES, not to the three dimensions (Rick's
    correction — a flat 3-way average lets the 2 LLM-judged dimensions outvote
    Length 2-to-1):

        qualitative_weight = avg( directness_weight, tone_weight )
        overall_weight     = round_half_up( 0.5*length_weight + 0.5*qualitative_weight )
        overall_weight     = clamp to [-2, 2], then bucket to its emoji

    `note` is PYTHON-TEMPLATED (never an LLM field — the overall grade is computed
    here, so its note is too): it names which category dragged the score.

    Requires:
        - the three weights are ints in [-2, 2]
        - length_detail is the Length grade's detail string (for the note)

    Ensures:
        - returns {"emoji", "weight", "note"} with weight in [-2, 2]
        - Rick's worked example: length=−2, directness=+2, tone=+2 →
          qualitative=2 → round_half_up(0.5*−2 + 0.5*2)=round_half_up(0)=0 → 🤷
    """
    qualitative_weight = ( directness_weight + tone_weight ) / 2.0
    raw                = 0.5 * length_weight + 0.5 * qualitative_weight
    overall_weight     = max( -2, min( 2, round_half_up( raw ) ) )

    if length_weight < qualitative_weight:
        note = f"Length pulled this down ({length_detail}); directness/tone were stronger."
    elif qualitative_weight < length_weight:
        note = f"Length was fine ({length_detail}); directness/tone dragged it down."
    else:
        note = f"Balanced — length and directness/tone agreed ({length_detail})."

    return { "emoji": WEIGHT_TO_EMOJI[ overall_weight ], "weight": overall_weight, "note": note }


def _fallback_dimension():
    """A safe neutral dimension result (meh/0) — used when the judge is unavailable."""
    return { "emoji": "🤷", "weight": 0, "detail": _JUDGE_UNAVAILABLE_DETAIL }


def _too_long_dimension( word_count ):
    """A neutral dimension result (🤷/0) for a body past QUALITATIVE_WORD_LIMIT — the
    honest 'not graded at this length' signal, distinct from the judge-unavailable one."""
    return { "emoji": "🤷", "weight": 0, "detail": f"{_TOO_LONG_DETAIL} ({word_count} words > {QUALITATIVE_WORD_LIMIT})" }


class DmQualityJudge:
    """
    Grade a peer-DM body on Length (Python) + Directness/Tone (Mistral).

    Requires:
        - for the LLM dimensions: a vLLM server serving the judge's model spec key
          (a missing server degrades gracefully — see Ensures)

    Ensures:
        - judge() returns {"length", "directness", "tone", "overall"} — ALWAYS the
          same shape, ALWAYS present, and NEVER raises
        - a judge-call failure (client unavailable, or 3 exhausted retries) yields
          🤷/0 Directness+Tone with detail="judge unavailable"; Length + Overall
          are still computed normally (Length is Python-only)
    """

    def __init__(
        self,
        llm_spec_key         = DEFAULT_JUDGE_LLM_SPEC_KEY,
        prompt_template_path = DEFAULT_JUDGE_PROMPT_PATH,
        debug                = False,
        verbose              = False,
    ):
        """
        Initialize the judge with its LLM configuration.

        Requires:
            - llm_spec_key is a model key resolvable by LlmClientFactory

        Ensures:
            - builds the LLM client + prompt processor; sets available=True on success
            - a client-build failure sets available=False (judge() then falls back)

        Args:
            llm_spec_key: model identifier for LlmClientFactory (the DISTINCT judge key)
            prompt_template_path: path (relative to project root) for the judge template
            debug: enable debug output
            verbose: enable verbose output
        """
        self.debug                = debug
        self.verbose              = verbose
        self.llm_spec_key         = llm_spec_key
        self.prompt_template_path = prompt_template_path
        self._available           = False
        self._client              = None

        try:
            factory         = LlmClientFactory( debug=debug, verbose=verbose )
            self._client    = factory.get_client( llm_spec_key, debug=debug, verbose=verbose )
            self._available = True
            if self.debug: print( f"[DmQualityJudge] LLM client ready ({llm_spec_key})" )
        except Exception as e:
            print( f"[DmQualityJudge] LLM client unavailable: {e}" )
            self._available = False

        self._processor = PromptTemplateProcessor( debug=debug, verbose=verbose )

    @property
    def available( self ):
        """Whether the LLM client is available for the qualitative dimensions."""
        return self._available

    def judge( self, body_text ):
        """
        Grade one DM body. Length in Python; Directness/Tone via the LLM.

        Requires:
            - body_text is a string (the composed DM body, before any stamp/frame)

        Ensures:
            - returns {"length", "directness", "tone", "overall"} — always this shape
            - never raises: an LLM failure degrades Directness/Tone to 🤷/0
            - Overall is combined from the (real) Length + the (real or fallback)
              qualitative weights per combine_overall

        Args:
            body_text: the DM body to grade

        Returns:
            dict: the full quality grade
        """
        word_count = len( body_text.split() )
        length     = length_bucket( word_count )

        # Qualitative ceiling (bug 2a41e141): past QUALITATIVE_WORD_LIMIT the model
        # cannot reliably judge — skip the LLM call and return the honest 🤷/0. Length
        # (above) still penalizes the verbosity, which is what actually matters here.
        if word_count > QUALITATIVE_WORD_LIMIT:
            directness = _too_long_dimension( word_count )
            tone       = _too_long_dimension( word_count )
        else:
            directness, tone = self._grade_qualitative( body_text )

        overall = combine_overall(
            length[ "weight" ], directness[ "weight" ], tone[ "weight" ], length[ "detail" ]
        )
        return { "length": length, "directness": directness, "tone": tone, "overall": overall }

    def _grade_qualitative( self, body_text ):
        """
        Grade Directness + Tone via the Mistral judge (3-attempt/backoff retry).

        Requires:
            - body_text is a string

        Ensures:
            - returns ( directness_dict, tone_dict ), each {"emoji","weight","detail"}
            - the client being unavailable, or 3 exhausted retries, returns the
              all-🤷/0 fallback (detail="judge unavailable") — never raises
        """
        if not self._available:
            if self.debug: print( "[DmQualityJudge] LLM unavailable — qualitative fallback" )
            return _fallback_dimension(), _fallback_dimension()

        template_raw = cu.get_file_as_string(
            cu.get_project_root() + self.prompt_template_path
        )
        template_processed = self._processor.process_template(
            template_raw, _JUDGE_ROUTING_COMMAND
        )
        prompt = template_processed.format( dm_body=body_text )

        last_error   = None
        max_attempts = 3
        for attempt in range( 1, max_attempts + 1 ):
            try:
                response_text = self._client.run( prompt )
                if self.debug: print( f"[DmQualityJudge] Raw response (attempt {attempt}): {response_text[ :200 ]}" )

                # Repair the live model's sloppy XML (spaced/multi-word tags,
                # unclosed prolog) before parsing — bug a5f7b36d.
                parsed = DmQualityJudgeResponse.from_xml( _repair_llm_xml( response_text ) )

                directness = {
                    "emoji"  : parsed.directness_emoji(),
                    "weight" : parsed.directness_weight(),
                    "detail" : parsed.directness_note,
                }
                tone = {
                    "emoji"  : parsed.tone_emoji(),
                    "weight" : parsed.tone_weight(),
                    "detail" : parsed.tone_note,
                }
                return directness, tone

            except Exception as e:
                last_error = e
                if attempt < max_attempts:
                    backoff = 0.5 * attempt   # 0.5s, 1.0s — gentle, bounded
                    print( f"[DmQualityJudge] LLM transient on attempt {attempt}, retrying in {backoff}s: {e}" )
                    time.sleep( backoff )
                    continue
                print( f"[DmQualityJudge] LLM error after {max_attempts} attempts: {e}" )

        return _fallback_dimension(), _fallback_dimension()


# ============================================================================
# Smoke Test
# ============================================================================

def quick_smoke_test():
    """Quick smoke test for the DM Quality Judge Python primitives (no LLM call)."""
    print( "\n" + "=" * 60 )
    print( "DM Quality Judge Smoke Test (Python primitives)" )
    print( "=" * 60 )

    tests_passed = 0
    tests_failed = 0

    # Test 1: Length bucketing at every boundary
    print( "\n1. Testing length bucketing boundaries..." )
    try:
        assert length_bucket(  60 )[ "weight" ] ==  2
        assert length_bucket(  61 )[ "weight" ] ==  1
        assert length_bucket(  90 )[ "weight" ] ==  1
        assert length_bucket(  91 )[ "weight" ] ==  0
        assert length_bucket( 150 )[ "weight" ] ==  0
        assert length_bucket( 151 )[ "weight" ] == -1
        assert length_bucket( 250 )[ "weight" ] == -1
        assert length_bucket( 251 )[ "weight" ] == -2
        print( "   ✓ All 8 boundaries bucket correctly (row-5 = 251+)" )
        tests_passed += 1
    except Exception as e:
        print( f"   ✗ Failed: {e}" ); tests_failed += 1

    # Test 2: round_half_up lenient ties
    print( "\n2. Testing round_half_up lenient ties..." )
    try:
        assert round_half_up(  0.5 ) ==  1
        assert round_half_up( -0.5 ) ==  0
        assert round_half_up(  1.5 ) ==  2
        assert round_half_up( -1.5 ) == -1
        print( "   ✓ Ties break UP (−0.5→0, +0.5→1)" )
        tests_passed += 1
    except Exception as e:
        print( f"   ✗ Failed: {e}" ); tests_failed += 1

    # Test 3: Rick's worked example
    print( "\n3. Testing Rick's worked example (😞/⭐/⭐ → 🤷)..." )
    try:
        overall = combine_overall( -2, 2, 2, "300 words, target ~60" )
        assert overall[ "weight" ] == 0
        assert overall[ "emoji" ]  == "🤷"
        print( "   ✓ length=−2 + directness/tone=+2 → overall 🤷/0" )
        tests_passed += 1
    except Exception as e:
        print( f"   ✗ Failed: {e}" ); tests_failed += 1

    print( f"\n{'=' * 60}" )
    print( f"DM Quality Judge Smoke Test: {tests_passed} passed, {tests_failed} failed" )
    print( "=" * 60 )
    return tests_failed == 0


if __name__ == "__main__":
    success = quick_smoke_test()
    exit( 0 if success else 1 )
