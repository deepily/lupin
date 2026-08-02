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
it returns a NAMED non-answer, weight None with its own emoji, and the DM still sends).

🔴 A NON-ANSWER IS NOT A GRADE, on either axis (Rick, 2026-08-01). Every dimension the
judge did not actually grade carries weight None — never 0, which is `meh` and averages
into Overall — and its own emoji from NONANSWER_EMOJI, never 🤷, which is `meh`'s face.
Overall falls back to Length alone the moment EITHER qualitative dimension is a
non-answer.

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
from cosa.agents.dm_quality_judge.xml_models import DmQualityJudgeResponse, WEIGHT_TO_EMOJI, NONANSWER_EMOJI
from cosa.agents.io_models.utils.prompt_template_processor import PromptTemplateProcessor


# The judge's OWN model spec key (Reviewer nit, Krishna 2026-07-31): a DISTINCT
# INI entry, NOT a repurpose of the fleet-shared `confidentialmind/mistral_small_24b`.
# NOTE ON HOST: the design doc verified the endpoint as `localhost:3001`, but that
# was a HOST-shell curl. This judge runs INSIDE the FastAPI container, where
# `localhost` is the container — so the config value points at the container-
# reachable `192.168.1.21:3001` (the same box the working mistral key already
# reaches from in-container). See the ini comment on `dm_quality_judge/...`.
#
# RENAMED 2026-08-01 (row 55a5baab), was `dm_quality_judge/mistral_small_24b`. The key
# said mistral and the endpoint served `kaitchup/Phi-4-AutoRound-GPTQ-4bit` — behaviourally
# harmless and actively misleading in every diagnosis of this component. It is also part of
# why the chat-template finding bit: the prompt below is Alpaca-style `### Instruction:`,
# written for a Mistral-family model, and it was going to a checkpoint instruction-tuned on
# `<|im_start|>` turns. Reading "the Mistral judge" made that look consistent when it was not.
DEFAULT_JUDGE_LLM_SPEC_KEY  = "dm_quality_judge/phi_4"
DEFAULT_JUDGE_PROMPT_PATH   = "/src/conf/prompts/dm-quality-judge.txt"

# The routing_command the prompt template is registered under in
# PromptTemplateProcessor.MODEL_MAPPING (drives {{PYDANTIC_XML_EXAMPLE}} injection).
_JUDGE_ROUTING_COMMAND      = "dm quality judge"

_JUDGE_UNAVAILABLE_DETAIL   = "judge unavailable"
_QUALITATIVE_OFF_DETAIL     = "not graded — qualitative judging is off (Rick 2026-08-01, row ca7a2cbf)"

# On retry, prepend this reply-anchor to break a deterministic degenerate mode
# (bug d02eaaa7): the model reads certain rambling bodies + the judge prompt and
# emits a literal " (1 of 1)" (finish_reason stop, 7 tokens) instead of the XML —
# deterministic at temp=0, so a plain retry reproduces it identically. Prepending
# this anchor breaks the attractor DETERMINISTICALLY (confirmed live: 3/3 recover a
# real grade), which a temperature bump did NOT (~50%/attempt, and it hit OTHER
# degenerate modes) — so this is preferred over temp jitter and keeps the live
# regression non-flaky. Attempt 1 is unchanged, so inputs that already parse never
# see the nudge (no regression to the normal path's determinism).
_RETRY_NUDGE                = "Begin your reply with <response>.\n\n"

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

# The target every Length grade is stated against. Was a bare "~60" written into the
# detail string; promoted to a constant when `overage` started dividing by it (row
# 0fc5b8f0), so the number a reader is told and the number the ratio uses cannot drift
# apart. NOT the same as the ⭐ boundary being 60 — they coincide today and are free to
# stop coinciding, which is exactly why they are not the same literal reused twice.
LENGTH_TARGET_WORDS         = 60

_TOO_LONG_DETAIL            = "not judged: DM too long for reliable qualitative grading"


# Matches ONE angle-bracket tag, tolerating the sloppiness the live models emit
# (bug a5f7b36d): leading/inner whitespace, a spaced slash (`< / tone >`), and
# multi-word / spaced-underscore tag names (`< directness note >`, `< directness _
# note >`). The char class also includes '-' so a DASH-cased tag (`<directness-note>`,
# the repo convention as of 2026-08-01) is CAPTURED for canonicalization rather than
# slipping past the repair layer unrewritten — which mangled it (row 25e8ca1c).
# Group 1 = optional slash, group 2 = the raw (possibly spaced/dashed) tag name.
_TAG_RE = re.compile( r"<\s*(/?)\s*([A-Za-z][A-Za-z0-9_ -]*?)\s*>" )

# The 4 known child fields in the CANONICAL form the parser expects: bare grade tags,
# DASH-cased note tags — DmQualityJudgeResponse declares alias="directness-note" /
# "tone-note", so dash is the shape from_xml() parses. Used by the unclosed-tag
# fallback below and to detect "well-formed enough" spans.
_KNOWN_FIELDS = ( "directness", "directness-note", "tone", "tone-note" )

# A field looked up by its SEPARATOR-AGNOSTIC key: lowercased, with any run of
# whitespace / underscore / dash collapsed to a single underscore. Lets _fix_tag map
# every sloppy variant — `<directness_note>`, `< directness note >`, `<directness-note>`
# — onto the one canonical `<directness-note>` tag. The tag convention thus lives in
# exactly ONE place (_KNOWN_FIELDS); a future change to it needs no edit here.
_CANONICAL_BY_KEY = { re.sub( r"[\s_-]+", "_", f ): f for f in _KNOWN_FIELDS }


def _canonical_by_key( known_fields ):
    """
    Build the separator-agnostic lookup for one field set.

    Requires:
        - known_fields is a sequence of canonical tag names

    Ensures:
        - returns { collapsed_key: canonical_name }, where the key lowercases the name
          and collapses any run of whitespace/underscore/dash to one underscore
    """
    return { re.sub( r"[\s_-]+", "_", f ): f for f in known_fields }


def _extract_unclosed_fields( span, known_fields=_KNOWN_FIELDS ):
    """
    Recover field values from a <response>...</response> span whose child tags
    were opened but never closed (bug d9c3e1a2's failure-2 shape: <directness>,
    <directness_note>, <tone>, <tone_note> all open, none closed — but the
    <response>/</response> wrapper IS present, so the caller's fast path would
    otherwise return the span unmodified and expat would hard-fail on the
    unclosed children).

    Requires:
        - span is the extracted "<response>...</response>" string, tags already
          passed through _fix_tag (spacing/underscores normalized)

    Ensures:
        - returns None if none of the 4 known open tags are found (nothing to
          recover — caller falls back to returning the span unmodified)
        - otherwise returns a well-formed "<response>...</response>" string:
          each found field's text runs from just after its open tag to the next
          known tag (open or close) or the end of the span, with any matching
          close tag for that field stripped from the tail
        - idempotent on ALREADY-well-formed input: a properly closed
          "<directness>good</directness><tone>..." round-trips unchanged, since
          the close tag immediately precedes the next open tag and gets
          stripped the same way

    ⚠️ known_fields IS A PARAMETER, and it has to be (found live 2026-08-01 while
       wiring v2). This function REBUILDS the span from the known fields it finds,
       so any tag NOT in that tuple is DELETED. v2's tone response is
       <tone-evidence> + <tone>: called with v1's tuple it matched <tone> only,
       silently dropped the evidence, and the judge reported a graded tone with a
       blank justification. Nothing raised — the XML was well-formed both before
       and after, so only reading the emitted detail caught it. A repair layer that
       edits toward a hardcoded schema is a data-loss bug for every other schema.
    """
    inner = span
    if inner.startswith( "<response>" ):
        inner = inner[ len( "<response>" ) : ]
    if inner.endswith( "</response>" ):
        inner = inner[ : -len( "</response>" ) ]

    positions = []
    for field in known_fields:
        m = re.search( rf"<{field}>", inner )
        if m is not None:
            positions.append( ( m.start(), m.end(), field ) )
    if not positions:
        return None

    positions.sort()
    parts = []
    for i, ( _start, end, field ) in enumerate( positions ):
        next_start = positions[ i + 1 ][ 0 ] if i + 1 < len( positions ) else len( inner )
        text = inner[ end : next_start ]
        text = re.sub( rf"</{field}>\s*$", "", text ).strip()
        parts.append( f"<{field}>{text}</{field}>" )

    return f"<response>{''.join( parts )}</response>"


def _is_garbage_output( text ):
    """
    Cheap pre-check for LLM output not worth running through the XML repair
    pipeline at all (bug d9c3e1a2's failure-1: a response of 10^100+ repeated
    "0" characters — previously burned a full repair+parse+expat-exception
    cycle before the retry backoff, for output that was never going to parse).

    Deliberately does NOT flag "no '<' present" as garbage — the curly-brace
    degenerate mode ("{ directness_meh } { tone _ good }", bug 2201516e) has no
    angle brackets either and IS recoverable; that check would have discarded
    a real, already-handled signal.

    Requires:
        - text is a string (the model's verbatim response)

    Ensures:
        - returns True only if text is >=95% one repeated character (checked
          only at length >=20, so short real answers can't false-positive)
        - returns False otherwise — NEVER a false positive on real XML or on
          the curly-brace degenerate mode
    """
    if len( text ) >= 20:
        most_common_count = max( text.count( ch ) for ch in set( text ) )
        if most_common_count / len( text ) >= 0.95:
            return True
    return False


def _repair_llm_xml( raw, known_fields=_KNOWN_FIELDS ):
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

    Args:
        raw: the model's verbatim output
        known_fields: the canonical child tags of the schema being parsed. Defaults
            to v1's four, so every existing caller is unchanged. v2 passes its own —
            see the warning on _extract_unclosed_fields for why a hardcoded set
            silently deletes another schema's fields.
    """
    canonical_by_key = _canonical_by_key( known_fields )
    # Drop a (possibly unclosed) XML declaration — up to the next '<' only, so an
    # unclosed `<?xml ... ?` cannot greedily consume the opening <response> tag.
    raw = re.sub( r"<\?xml[^<]*", "", raw )

    def _fix_tag( m ):
        slash = "/" if m.group( 1 ) == "/" else ""
        # Separator-agnostic key (collapse whitespace/underscore/dash → one '_',
        # lowercase), then map a KNOWN field onto its canonical (dash-cased) tag.
        # An unknown tag (e.g. <response>) keeps its collapsed form unchanged.
        key   = re.sub( r"[\s_-]+", "_", m.group( 2 ).strip().lower() )
        name  = canonical_by_key.get( key, key )
        return f"<{slash}{name}>"

    raw = _TAG_RE.sub( _fix_tag, raw )

    start = raw.find( "<response>" )
    end   = raw.find( "</response>" )
    if start != -1 and end != -1:
        # Well-formed-enough: keep only the <response>...</response> span (drops a
        # trailing </stop> sentinel or any post-root chatter). If its child tags
        # were opened but never closed, recover them field-by-field rather than
        # returning the span as-is for expat to hard-fail on (bug d9c3e1a2).
        span      = raw[ start : end + len( "</response>" ) ].strip()
        recovered = _extract_unclosed_fields( span, known_fields )
        return recovered if recovered is not None else span

    # MISSING/implicit root (bug 46690a76): strip any stray wrapper fragments and
    # rebuild ONE root around the known child-tag span (first known open tag →
    # last known close tag). Excludes any leading prose / orphan </response>.
    raw = raw.replace( "<response>", "" ).replace( "</response>", "" )
    first = re.search( "|".join( re.escape( f"<{f}>" ) for f in known_fields ), raw )
    if first is not None:
        last_end = -1
        for field in known_fields:
            close = f"</{field}>"
            idx   = raw.rfind( close )
            if idx != -1:
                last_end = max( last_end, idx + len( close ) )
        if last_end != -1:
            return f"<response>{raw[ first.start() : last_end ]}</response>"

    # Degenerate NON-XML curly mode (bug 2201516e): the model sometimes emits, on
    # rambling DMs, `{ directness_meh } { tone _ good }` — no tags at all, but the
    # GRADE LABEL is right there after the dimension name (separated by spaces/
    # underscores). Recover it rather than discard the signal. The label run is
    # `[a-z_]+` (covers the underscored `needs_improvement`); normalize_grade_label
    # downstream strips/aliases it.
    d = re.search( r"directness[\s_]+([a-z][a-z_]*)", raw, re.I )
    t = re.search( r"tone[\s_]+([a-z][a-z_]*)", raw, re.I )
    if d is not None and t is not None:
        return f"<response><directness>{d.group( 1 )}</directness><tone>{t.group( 1 )}</tone></response>"

    return raw.strip()


def length_bucket( word_count ):
    """
    Deterministic 5-level Length grade on a word count (no LLM).

    The table (Rick 2026-07-31, row-5 boundary fixed to 251+ by Krishna's review
    so 250 is unambiguously row 4):

        ≤ 60   → ⭐ +2     91–150  → 🤷  0     251+ → 😞 −2
        61–90  → 👍 +1     151–250 → 👎 −1

    THE SCALE SATURATES AT 251, AND `overage` IS HOW A CONSUMER SEES PAST IT (row
    0fc5b8f0, 2026-08-01). Surfaced by Rick's broadcast about a ~1000-word DM: 251
    words and 1000 words both score 😞 −2, so every consumer reading the WEIGHT — the
    audit averages, Overall, any future gate — cannot tell a message 4× over target
    from one 16× over. This judge exists to curb token burn, and a scale that cannot
    rank the worst offenders against each other is blind exactly where it is aimed.

    THE WEIGHT IS DELIBERATELY UNCHANGED. Adding a −3/−4 would be the other obvious
    fix and it breaks a documented contract: `weight in [-2, 2]` is asserted in this
    docstring, relied on by combine_overall's clamp, and assumed by every reader of
    WEIGHT_TO_EMOJI. So the ranking information is added ALONGSIDE the grade instead
    of by stretching it — no consumer changes behaviour, and one that wants to rank
    over-long DMs now has a number to rank on.

    `overage` is the ratio to target, rounded to one decimal: 60 words → 1.0,
    1000 words → 16.7. It is on EVERY result, not only the saturated ones, because a
    field that appears only in the bad case is a field consumers forget to read.

    Requires:
        - word_count is a non-negative int

    Ensures:
        - returns {"emoji", "weight", "detail", "overage"} with a weight in [-2, 2]
        - the boundaries are inclusive-left as written above (60→⭐, 61→👍, ...)
        - overage is word_count / LENGTH_TARGET_WORDS, rounded to 1dp, and is
          STRICTLY INCREASING in word_count past the saturation point — which is the
          whole reason it exists
    """
    if   word_count <=  60: emoji, weight = "⭐", 2
    elif word_count <=  90: emoji, weight = "👍", 1
    elif word_count <= 150: emoji, weight = "🤷", 0
    elif word_count <= 250: emoji, weight = "👎", -1
    else:                   emoji, weight = "😞", -2
    return { "emoji"   : emoji,
             "weight"  : weight,
             "detail"  : f"{word_count} words, target ~{LENGTH_TARGET_WORDS}",
             "overage" : round( word_count / LENGTH_TARGET_WORDS, 1 ) }


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
    here, so its note is too): it names which category scored lower as a plain
    ordering, WITHOUT asserting that anything caused harm.

    Requires:
        - the three weights are ints in [-2, 2]
        - length_detail is the Length grade's detail string (for the note)

    Ensures:
        - returns {"emoji", "weight", "note"} with weight in [-2, 2]
        - Rick's worked example: length=−2, directness=+2, tone=+2 →
          qualitative=2 → round_half_up(0.5*−2 + 0.5*2)=round_half_up(0)=0 → 🤷
    """
    # LENGTH-ONLY MODE (Rick, 2026-08-01: "stick with length for now — that's quantitative
    # and we can calculate a grade very easily"). When the qualitative half carries NO
    # judgement, blending it in would let non-answers drag Overall toward 0 and publish
    # that as a considered score — the exact defect this package spent the day on.
    # Overall IS the Length grade, and its note says so.
    #
    # 🔴 EITHER, NOT BOTH (found 2026-08-01 by running Maria's 527-word DM through it).
    # This used to require BOTH weights to be None, which quietly covered only the
    # feature-off case. Every OTHER silence — over-length, judge unavailable, an
    # extraction that failed its check — returned weight 0, and 0 is `meh`, a real grade
    # on this scale. Measured on the worst DM we have: Length said 😞 −2, both
    # qualitative dimensions said "not judged: too long", and Overall came out 👎 −1,
    # SOFTER than Length alone, over a note reading "directness/tone were stronger."
    # They were not stronger. They were never graded. One un-graded dimension is enough
    # to make the average meaningless, so either one triggers Length-only.
    if directness_weight is None or tone_weight is None:
        overall_weight = max( -2, min( 2, int( length_weight ) ) )
        return { "emoji"  : WEIGHT_TO_EMOJI[ overall_weight ],
                 "weight" : overall_weight,
                 "note"   : f"Length only ({length_detail}); directness/tone not graded." }

    qualitative_weight = ( directness_weight + tone_weight ) / 2.0
    raw                = 0.5 * length_weight + 0.5 * qualitative_weight
    overall_weight     = max( -2, min( 2, round_half_up( raw ) ) )

    # NEUTRAL ORDERING, NOT HARM (row 700a6330, 2026-08-02). These branches compare
    # length against qualitative — a RELATIVE ordering — so they must NOT be worded as
    # absolute harm. "dragged it down" / "pulled this down" fired on top-scoring DMs
    # (every sub-score positive, Overall +2) because qualitative merely being lower than
    # length is enough to take the branch. The note is the only prose in the payload —
    # the whole teaching surface — so it misfired hardest on writers already complying.
    # State which side scored lower; let the sub-scores carry any actual harm signal.
    if length_weight < qualitative_weight:
        note = f"Length scored below directness/tone ({length_detail})."
    elif qualitative_weight < length_weight:
        note = f"Directness/tone scored below length ({length_detail})."
    else:
        note = f"Balanced — length and directness/tone agreed ({length_detail})."

    return { "emoji": WEIGHT_TO_EMOJI[ overall_weight ], "weight": overall_weight, "note": note }


def _fallback_dimension():
    """
    The dimension result when the judge could not produce one at all.

    Ensures:
        - weight is None, NOT 0. 0 is `meh` — a real grade on this scale — and a judge
          that never ran has not said `meh` about anything. The emoji stays 🤷 because
          that is what "no opinion" has always looked like here, but the WEIGHT has to
          be un-averageable or combine_overall will blend a silence into a score.
    """
    return { "emoji": NONANSWER_EMOJI[ "unavailable" ], "weight": None, "detail": _JUDGE_UNAVAILABLE_DETAIL }


def _withheld_dimension():
    """
    The dimension result when the qualitative half is SWITCHED OFF (Rick, 2026-08-01).

    Ensures:
        - weight is None, NOT 0 — and that is the whole point. 0 is `meh`, a real grade
          on this scale, and today's investigation was one long demonstration of what
          happens when a non-answer is published in the same value space as an answer.
          None cannot be averaged, cannot be compared, and cannot be mistaken for an
          opinion by any consumer that does not explicitly handle it
        - the emoji is 🚫 rather than 🤷: 🤷 is what an UNAVAILABLE judge and an
          OVER-LENGTH body already return, and "we chose not to grade this" is a third
          thing that must not wear either of their faces
    """
    return { "emoji": NONANSWER_EMOJI[ "withheld" ], "weight": None, "detail": _QUALITATIVE_OFF_DETAIL }


def _too_long_dimension( word_count ):
    """A neutral dimension result (🤷/0) for a body past QUALITATIVE_WORD_LIMIT — the
    honest 'not graded at this length' signal, distinct from the judge-unavailable one."""
    return { "emoji": NONANSWER_EMOJI[ "too_long" ], "weight": None, "detail": f"{_TOO_LONG_DETAIL} ({word_count} words > {QUALITATIVE_WORD_LIMIT})" }


def _get_qualitative_enabled():
    """
    Read `dm quality qualitative enabled` from lupin-app.ini at construction.

    Ensures:
        - returns a bool; DEFAULTS TO FALSE, because as of 2026-08-01 the qualitative
          half does not work (row ca7a2cbf) and a default that turns it on would
          re-publish grades Rick switched off
        - a missing key or unreadable config returns False rather than raising — the
          judge must never take a DM send down, and False is the safe direction here
    """
    try:
        from cosa.config.configuration_manager import ConfigurationManager
        config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        return config_mgr.get( "dm quality qualitative enabled", default=False, return_type="boolean" )
    except Exception as e:
        print( f"[DmQualityJudge] could not read the qualitative toggle ({type( e ).__name__}) — defaulting OFF" )
        return False


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
        qualitative_enabled  = None,
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
        # None => read the INI. An explicit bool is an INJECTION SEAM for tests, which
        # must not depend on ambient config: a suite whose verdict flips with an operator's
        # toggle is measuring the machine it runs on, not the code.
        self.qualitative_enabled  = ( _get_qualitative_enabled()
                                      if qualitative_enabled is None else bool( qualitative_enabled ) )

        # Length-only is the CONFIGURED state as of 2026-08-01, not a degraded one — say
        # so at build time so an operator reading logs is not left inferring it from a 🚫.
        if not self.qualitative_enabled:
            print( "[DmQualityJudge] qualitative judging OFF — Length only (row ca7a2cbf)" )

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

        # LENGTH-ONLY MODE (Rick, 2026-08-01, row ca7a2cbf). Measured that day, the 24B
        # recognizes exactly ONE of four message types — a message that is direct AND
        # plainly written. Hold the prose jargony and it cannot tell a leading verdict
        # from a buried one; bury the verdict and it cannot tell plain prose from jargon.
        # Everything not good-on-both collapses to `meh`. His ruling: keep Length, which
        # is Python-computed and has never been in doubt, and pursue the qualitative half
        # separately via fine-tuning on purpose-built training data.
        if not self.qualitative_enabled:
            directness = _withheld_dimension()
            tone       = _withheld_dimension()

        # Qualitative ceiling (bug 2a41e141): past QUALITATIVE_WORD_LIMIT the model
        # cannot reliably judge — skip the LLM call and return the honest 🤷/0. Length
        # (above) still penalizes the verbosity, which is what actually matters here.
        elif word_count > QUALITATIVE_WORD_LIMIT:
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
        # .replace(), NOT .format() — str.format treats EVERY brace in the string as a
        # format field, and two independent sources put literal braces in here:
        #   1. the injected XML example carries `{terrible|bad|meh|good|exemplary}`
        #      (the CHOOSE-ONE placeholder), which format() reads as a field name and
        #      dies on with KeyError — outside the retry block, so judge() RAISED and
        #      broke its own never-raises contract;
        #   2. any DM body containing a brace — a dict literal, an f-string, a JSON
        #      snippet — would do the same, and peers paste code into DMs constantly.
        # The template has exactly one substitution point and no need for format()'s
        # grammar, so the narrower tool is the correct one.
        prompt = template_processed.replace( "{dm_body}", body_text )

        last_error   = None
        max_attempts = 3
        for attempt in range( 1, max_attempts + 1 ):
            try:
                # Retries prepend the reply-anchor nudge to break the deterministic
                # " (1 of 1)" degenerate mode (bug d02eaaa7). Attempt 1 is the clean
                # prompt so the normal path is untouched.
                effective_prompt = prompt if attempt == 1 else _RETRY_NUDGE + prompt
                response_text = self._client.run( effective_prompt )
                if self.debug: print( f"[DmQualityJudge] Raw response (attempt {attempt}): {response_text[ :200 ]}" )

                # Cheap garbage guard (bug d9c3e1a2, failure-1): skip straight past
                # the repair/parse pipeline for output that was never going to
                # parse (no XML tags at all, or a degenerate repeated-character run).
                if _is_garbage_output( response_text ):
                    raise ValueError( "garbage output: no XML tags or degenerate repeated-character response" )

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
