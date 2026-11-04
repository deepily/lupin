#!/usr/bin/env python3
"""
DM Quality Judge — hybrid grader for a peer-DM body.

    - Length  : Python-only 5-level bucket on the word count (LLMs count badly).
    - Directness + Tone : one fixed-rubric Mistral judge call (this module).
    - Overall : Python combination, equal weight to the quantitative (Length) vs
                the qualitative (Directness+Tone) category, round-half-up.

Modeled on cosa/agents/notification_proxy/verification.py (LlmAnswerVerifier):
same LlmClientFactory client, same PromptTemplateProcessor, same 3-attempt/backoff
retry. It keeps the same graceful-degradation contract: a failure never raises to the
caller. It returns a named non-answer (weight None, with its own emoji) and the DM
still sends.

A non-answer is not a grade, on either axis. Every dimension the judge did not
actually grade carries weight None, never 0, which is `meh` and averages into Overall.
It also carries its own emoji from NONANSWER_EMOJI, never 🤷, which is `meh`'s face.
Overall falls back to Length alone as soon as either qualitative dimension is a
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
from cosa.utils.dm_text import dm_word_count
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
# ── Config-backed length thresholds (row f4bb1cdb amend-2, Rick 2026-08-02;
#    made /api/init-reachable row 00600a75, Rick 2026-08-02) ───────────────────────────
# Each threshold has ONE definition, resolved from lupin-app.ini with today's value as
# the default, so the length buckets below READ these names instead of repeating the
# numbers inline — before this, a change to a named constant left the inline bucket
# literal untouched and the two drifted silently. They stay module-level ints (so
# judge_v2, which imports QUALITATIVE_WORD_LIMIT, and the tests, which patch it as a
# module attribute, keep working untouched), but the values are (re)read by
# _reload_length_thresholds() below: once at import AND again on every /api/init
# hot-reload, via a cache_registry invalidator. So editing a threshold in the ini and
# hitting GET /api/init takes effect with NO server bounce.
def _resolve_threshold( config_key, default ):
    """Read an int length threshold from lupin-app.ini, falling back to the default.

    Never raises: a broken config read must not stop this module from importing."""
    from cosa.config.configuration_manager import ConfigurationManager
    try:
        return ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" ).get(
            config_key, default=default, return_type="int" )
    except Exception:
        return default


def _reload_length_thresholds():
    """
    Reload the five DM-length thresholds from lupin-app.ini into this module's globals.

    Runs at import and on every /api/init hot-reload (cache_registry invalidator), so an
    ini edit takes effect with no server bounce.

    Requires:
        - lupin-app.ini is readable (any error falls back to the per-key default, via
          _resolve_threshold, which never raises)

    Ensures:
        - the five module globals are rebound to the current ini values
        - judge_v2.QUALITATIVE_WORD_LIMIT (its own binding, from `from judge import ...`)
          is rebound to match if judge_v2 is already imported — a sys.modules reach, not
          a source edit, so judge_v2's import and the length tests keep working untouched
        - length_bucket, which reads these globals at call time, reflects the new values
          on its next call (no restart)
    """
    global QUALITATIVE_WORD_LIMIT, LENGTH_TARGET_WORDS, LENGTH_EXCELLENT_LIMIT
    global LENGTH_GOOD_LIMIT, LENGTH_VERBOSE_LIMIT

    QUALITATIVE_WORD_LIMIT = _resolve_threshold( "dm qualitative word limit", 150 )

    # The target every Length grade is stated against. Was a bare "~60" written into the
    # detail string; promoted to a constant when `overage` started dividing by it (row
    # 0fc5b8f0), so the number a reader is told and the number the ratio uses cannot drift
    # apart. NOT the same as the ⭐ boundary being 60 — they coincide today and are free to
    # stop coinciding, which is exactly why they are not the same literal reused twice
    # (LENGTH_EXCELLENT_LIMIT below is the ⭐ boundary, its OWN config key).
    LENGTH_TARGET_WORDS    = _resolve_threshold( "dm length target words", 60 )

    # The four Length BUCKET boundaries — each its own config key so none is an inline
    # literal a named constant could silently drift apart from. 150 is deliberately NOT
    # repeated here: the 🤷/👎 boundary IS the qualitative cap QUALITATIVE_WORD_LIMIT, the
    # word count past which the qualitative LLM pass is skipped. (It is NO LONGER the
    # emoji-repetition interval — that was decoupled to its own LENGTH_FACE_INTERVAL in row
    # 2cb46818 so the faces stop disclosing the enforced ceiling.)
    LENGTH_EXCELLENT_LIMIT = _resolve_threshold( "dm length excellent limit", 60 )    # ⭐ ≤ this
    LENGTH_GOOD_LIMIT      = _resolve_threshold( "dm length good limit", 90 )         # 👍 ≤ this
    LENGTH_VERBOSE_LIMIT   = _resolve_threshold( "dm length verbose limit", 250 )     # 👎 ≤ this

    # STALE-COPY SYNC: judge_v2 did `from judge import QUALITATIVE_WORD_LIMIT`, so it holds
    # its OWN module binding that a rebind here does not reach. Push the new value across
    # through sys.modules (a runtime reach, not a source edit) so judge_v2's own
    # `> QUALITATIVE_WORD_LIMIT` ceiling moves with the config. Guarded: judge_v2 may not be
    # imported yet at the first (import-time) call — fine, it reads the fresh value itself
    # when it loads.
    import sys
    _v2 = sys.modules.get( "cosa.agents.dm_quality_judge.judge_v2" )
    if _v2 is not None:
        _v2.QUALITATIVE_WORD_LIMIT = QUALITATIVE_WORD_LIMIT


# Resolve once at import so the globals exist for judge_v2's `from judge import ...` and
# for length_bucket; re-resolved on each /api/init by the invalidator registered next.
_reload_length_thresholds()

from cosa.config.cache_registry import register_invalidator
register_invalidator( "dm_length_thresholds", _reload_length_thresholds )

# DISPLAY-ONLY face-repetition interval (row 2cb46818, Rick 2026-08-06). The length face
# repeats once per LENGTH_FACE_INTERVAL words. This is DELIBERATELY its own constant and
# DELIBERATELY NOT QUALITATIVE_WORD_LIMIT: the display interval (100) and the enforced
# qualitative ceiling (150, still QUALITATIVE_WORD_LIMIT) must NOT be the same number, so
# that counting the faces can never recover where the enforced bound sits. Enforcement is
# unchanged — this touches display only. A fixed constant, not config-backed, because it is
# an intentional 3:2 offset from the ceiling, not an operator-tunable threshold.
LENGTH_FACE_INTERVAL       = 100

# The blunt, number-free refusal shown when a body is past the qualitative ceiling (row
# 2cb46818, Rick 2026-08-06). Carries NO threshold: a sender who learns the real bound
# writes right up to it, converting the deterrent into a budget. Rick's register.
_TOO_LONG_DETAIL           = "too f*cking long — cut it down and resubmit"

# The LENGTH grade's sender-facing wording, keyed by the grade's own weight — the same
# number-free discipline as _TOO_LONG_DETAIL above, extended to the whole scale (Rick
# 2026-08-13, "no word counts to be found anywhere"; surface found by María).
#
# Keyed on `weight` rather than on word_count so it CANNOT drift from the band it
# describes: the band decides the weight, the weight decides the words. A parallel
# threshold ladder here would be a second place to get the boundaries wrong, and the
# two could then disagree silently.
#
# Each line says which way to move without saying how far, because how-far is the
# number. The shape is the target, not a count.
_LENGTH_DETAIL = {
     2 : "tight — this is the shape",
     1 : "slightly long; tighten it",
     0 : "long; cut it back to the shape",
    -1 : "well past the shape — cut it down",
    -2 : _TOO_LONG_DETAIL,
}


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
    Recover field values from a response span whose child tags were opened but never closed.

    The wrapper is present, so the caller's fast path would return the span unmodified
    and expat would hard-fail on the unclosed children.

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

    known_fields is a parameter because this function rebuilds the span from the known
    fields it finds, so any tag not in that tuple is deleted. The v2 tone response is
    <tone-evidence> plus <tone>. Called with the v1 tuple it matched <tone> only and
    silently dropped the evidence, so the judge reported a graded tone with a blank
    justification. Nothing raised, because the XML was well-formed before and after.
    A repair layer that edits toward a hardcoded schema loses data for every other schema.
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
    Cheap pre-check for LLM output not worth running through the XML repair pipeline.

    A response of one repeated character, such as a huge run of zeros, never parses.
    Repairing it would burn a full parse cycle before the retry backoff.

    Requires:
        - text is a string (the model's verbatim response)

    Ensures:
        - returns True only if text is >=95% one repeated character (checked
          only at length >=20, so short real answers can't false-positive)
        - returns False otherwise — never a false positive on real XML or on
          the curly-brace degenerate mode
        - text with no '<' is not garbage: the curly-brace degenerate mode
          ("{ directness_meh } { tone _ good }") has no angle brackets either and is
          recoverable, so flagging it would discard a real, already-handled signal
    """
    if len( text ) >= 20:
        most_common_count = max( text.count( ch ) for ch in set( text ) )
        if most_common_count / len( text ) >= 0.95:
            return True
    return False


def _repair_llm_xml( raw, known_fields=_KNOWN_FIELDS ):
    """
    Repair the malformed XML the live Mistral judge emits into parseable XML.

    The model emits an unclosed `<?xml` prolog (fixtures: src/tests/unit/fixtures/dm_judge/).
    It also emits spaced tags (`< / directness >`) and multi-word tags (`< directness _ note >`).

    Requires:
        - raw is a string (the model's verbatim output)

    Ensures:
        - drops any `<?xml ...` prolog (even unclosed — stops at the next `<`, so it
          never devours the real content)
        - collapses each tag's inner whitespace/underscores to one underscore and
          removes the spaces around the brackets/slash
        - returns only the `<response>...</response>` span when both ends are present
          (drops a trailing `</stop>` sentinel or any post-root chatter)
        - when the root wrapper is missing (the model drops
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

        ≤ 60   → ⭐ +2     91–150  → 🤷  0     251+ → 😞 −2
        61–90  → 👍 +1     151–250 → 👎 −1

    Requires:
        - word_count is a non-negative int

    Ensures:
        - returns {"emoji", "weight", "detail", "overage"} with a weight in [-2, 2]
        - this judge exists to curb token burn; the length grade is its quantitative half
        - "emoji" is the band's face repeated max(1, word_count // LENGTH_FACE_INTERVAL)
          times (display-only intensity); "weight" is unaffected
        - the top row starts at 251+, so 250 is unambiguously in the -1 row
        - the boundaries are the resolved config thresholds (defaults 60/90/150/250),
          inclusive-left as written above (≤60→⭐, 61→👍, ...); these are re-read on
          every /api/init hot-reload (_reload_length_thresholds), so a call after an ini
          edit + GET /api/init reflects the new boundaries with no server bounce
        - overage is word_count / LENGTH_TARGET_WORDS, rounded to 1dp (60 words → 1.0,
          1000 words → 16.7), and is strictly increasing in word_count past the
          saturation point
        - the scale saturates at 251: 251 words and 1000 words both score -2, so a reader
          of the weight cannot tell a message 4x over target from one 16x over, and
          overage carries that ranking information instead
        - the weight is never widened to -3/-4: weight in [-2, 2] is relied on by
          combine_overall's clamp and by every reader of WEIGHT_TO_EMOJI, so the ranking
          number is added alongside the grade and no consumer changes behaviour
        - overage is on every result, not only the saturated ones, because a field that
          appears only in the bad case is a field consumers forget to read
    """
    if   word_count <= LENGTH_EXCELLENT_LIMIT: emoji, weight = "⭐", 2
    elif word_count <= LENGTH_GOOD_LIMIT:      emoji, weight = "👍", 1
    elif word_count <= QUALITATIVE_WORD_LIMIT: emoji, weight = "🤷", 0
    elif word_count <= LENGTH_VERBOSE_LIMIT:   emoji, weight = "👎", -1
    else:                                      emoji, weight = "😞", -2
    # DISPLAY-ONLY intensity (row f4bb1cdb, Rick 2026-08-02; interval decoupled row
    # 2cb46818, Rick 2026-08-06): repeat the message's OWN length-grade face once per
    # LENGTH_FACE_INTERVAL words. The interval is a SEPARATE constant (100), NOT the
    # qualitative ceiling QUALITATIVE_WORD_LIMIT (150) — they used to coincide, and that
    # coincidence let a reader recover the enforced 150 by counting faces, so the two
    # numbers are now deliberately different. count = max(1, word_count // LENGTH_FACE_INTERVAL):
    # the faces never contradict the band (a 160-word 👎 shows 👎, never 😞) and the first
    # DOUBLING is at 2×the interval. This RENDERS intensity that `overage` already carries as
    # a number — the `weight` is untouched and stays in [-2, 2], so combine_overall, the
    # audit, and the stored len_grade are unaffected. A wider weight would be clamped back
    # by combine_overall anyway AND would break the corpus mid-collection for the demo.
    faces = emoji * max( 1, word_count // LENGTH_FACE_INTERVAL )
    # 🔴 THE SENDER-FACING STRING NAMES NO NUMBER (Rick 2026-08-13, found by María).
    # It used to read "{word_count} words, target ~{LENGTH_TARGET_WORDS}", handing the
    # sender both their count AND the target — in the DM response envelope, the exact
    # channel his instruction was about.
    #
    # This is not a new principle, it is the one already ruled TWICE in this file:
    # `_TOO_LONG_DETAIL` is deliberately number-free because "a sender who learns the
    # real bound writes right up to it, converting the deterrent into a budget", and
    # LENGTH_FACE_INTERVAL was decoupled from the ceiling precisely so nobody could
    # recover the bound by counting faces. A detail line stating both numbers outright
    # defeated both of those at once.
    #
    # ⚠️ THE DATA IS UNTOUCHED, and that separation is the whole design: `weight` and
    # `overage` keep their exact prior values and the corpus keeps `words`, so every
    # existing analysis still has the numbers. What changed is only what is SAID to the
    # sender — the measurement stays, the disclosure goes.
    return { "emoji"   : faces,
             "weight"  : weight,
             "detail"  : _LENGTH_DETAIL[ weight ],
             "overage" : round( word_count / LENGTH_TARGET_WORDS, 1 ) }


def round_half_up( x ):
    """
    Round half up (toward +infinity on a .5 tie), as an explicit tie-break.

    This is not Python's built-in round(), which rounds half-to-even and would be
    inconsistent boundary to boundary. Ties are intentionally lenient: −0.5 → 0,
    +0.5 → 1 (a DM on a category boundary rounds toward the kinder grade).

    Requires:
        - x is a real number

    Ensures:
        - returns int( floor( x + 0.5 ) ): 0.5→1, −0.5→0, 1.5→2, −1.5→−1
    """
    return int( math.floor( x + 0.5 ) )


def combine_overall( length_weight, directness_weight, tone_weight, length_detail ):
    """
    Combine the three dimension weights into the overall grade.

    Equal weight goes to the two categories, Length and Directness plus Tone.
    A flat 3-way average would let the two LLM-judged dimensions outvote Length 2-to-1.

    Requires:
        - the three weights are ints in [-2, 2]
        - length_detail is the Length grade's detail string (for the note)

    Ensures:
        - returns {"emoji", "weight", "note"} with weight in [-2, 2]
        - worked example: length=−2, directness=+2, tone=+2 →
          qualitative=2 → round_half_up(0.5*−2 + 0.5*2)=round_half_up(0)=0 → 🤷
        - qualitative_weight = avg( directness_weight, tone_weight ), and
          overall_weight = round_half_up( 0.5*length_weight + 0.5*qualitative_weight ),
          clamped to [-2, 2], then bucketed to its emoji
        - note is python-templated (never an LLM field, since the overall grade is
          computed here): it names which category scored lower as a plain ordering,
          without asserting that anything caused harm
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
        - weight is None, not 0. 0 is `meh` — a real grade on this scale — and a judge
          that never ran has not said `meh` about anything. The emoji stays 🤷 because
          that is what "no opinion" has always looked like here, but the weight has to
          be un-averageable or combine_overall will blend a silence into a score.
    """
    return { "emoji": NONANSWER_EMOJI[ "unavailable" ], "weight": None, "detail": _JUDGE_UNAVAILABLE_DETAIL }


def _withheld_dimension():
    """
    The dimension result when the qualitative half is switched off.

    Ensures:
        - weight is None, not 0. 0 is `meh`, a real grade on this scale, and a
          non-answer published in the same value space as an answer gets mistaken for one.
          None cannot be averaged, cannot be compared, and cannot be mistaken for an
          opinion by any consumer that does not explicitly handle it
        - the emoji is 🚫 rather than 🤷: 🤷 is what an unavailable judge and an
          over-length body already return, and "we chose not to grade this" is a third
          thing that must not wear either of their faces
    """
    return { "emoji": NONANSWER_EMOJI[ "withheld" ], "weight": None, "detail": _QUALITATIVE_OFF_DETAIL }


def _too_long_dimension():
    """A non-answer dimension result for a body past QUALITATIVE_WORD_LIMIT.

    This is the honest "not graded at this length" signal, distinct from the judge-unavailable one.
    It takes no arguments, and the detail carries no threshold and no word count.
    Disclosing the enforced limit would turn the deterrent into a budget.
    A bare word count would only invite arithmetic against the advertised target."""
    return { "emoji": NONANSWER_EMOJI[ "too_long" ], "weight": None, "detail": _TOO_LONG_DETAIL }


def _get_qualitative_enabled():
    """
    Read `dm quality qualitative enabled` from lupin-app.ini at construction.

    Ensures:
        - returns a bool; defaults to False, because the qualitative
          half does not work and a default that turns it on would
          re-publish grades that were switched off
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
        - judge() returns {"length", "directness", "tone", "overall"} — always the
          same shape, always present, and never raises
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
            llm_spec_key: model identifier for LlmClientFactory (the distinct judge key)
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
        word_count = dm_word_count( body_text )
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
            directness = _too_long_dimension()
            tone       = _too_long_dimension()
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
