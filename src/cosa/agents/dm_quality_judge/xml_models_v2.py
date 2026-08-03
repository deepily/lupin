#!/usr/bin/env python3
"""
XML response models + deterministic scoring for DM Quality Judge **v2**.

THE ONE IDEA. v1 asked the model to GRADE directness and the grade could never be
checked. v2 asks it to LOCATE the verdict — quote it, index it, name the stray
sentences after it — and computes the weight in Python. A grade can never be
validated; a quote can be compared against the source text.

WHAT IS GROUNDED AND WHAT IS NOT (say this plainly, every time):
    - The POSITION of the verdict is fully validated. The quote must equal a real
      numbered sentence, at the index the model gave, at that sentence's FIRST
      occurrence. A model that invents, paraphrases, or miscounts is REJECTED, not
      averaged in.
    - The STRAY classification is NOT. Deciding that sentence 4 carries nothing the
      reader needs is the same payload judgement the 2026-08-01 measurement showed
      this model failing at. The indices list makes it checkable for SHAPE (in range,
      after the payload, no duplicates) — not true. So position weight and final
      weight are reported SEPARATELY, and the ungrounded half stays visible.

Companion to xml_models.py (v1), which is untouched. The shared Likert table,
weight→emoji map and label normalizer are IMPORTED from there, never re-declared.

References:
    - src/rnd/v0.1.9/2026.07.31-dm-verbosity-reduction/2026.08.01-dm-judge-v2-plan.md
    - the two expert opinions in that same directory (-claude.md, -gpt.md)
"""

import re

from pydantic import Field

from cosa.agents.io_models.utils.util_xml_pydantic import BaseXMLModel
from cosa.agents.dm_quality_judge.xml_models import WEIGHT_TO_EMOJI, normalize_grade_label


# ── Structural codes (GPT expert's table) ─────────────────────────────────────
# Kept as code→weight ONLY; the emoji comes from v1's WEIGHT_TO_EMOJI so the two
# versions can never drift onto different faces for the same number.
STRUCTURE_TO_WEIGHT = {
    "lead_clean"     :  2,   # payload is sentence 1, nothing stray after it
    "lead_one_stray" :  1,   # payload is sentence 1, exactly one stray after
    "mixed"          :  0,   # payload is sentence 1 with >=2 strays, or sentence 2
    "late"           : -1,   # earliest payload is sentence 3 or later
    "missing"        : -2,   # no payload anywhere
}

# POSITION alone, with the stray count ignored. This is the FULLY VALIDATED half of
# the score: every input to it survived a check against the source text. Reported
# next to the final weight so the cost of the ungrounded half is measurable rather
# than assumed.
POSITION_TO_WEIGHT = {
    0 :  -2,   # no payload
    1 :   2,
    2 :   1,
}
_LATE_POSITION_WEIGHT = -1   # index >= 3

# 🔴 MIDCOURSE CORRECTION — Rick, 2026-08-01, after reading the first v2 table.
#
# WHAT THE MEASUREMENT SHOWED. Three runs, four bodies. The position half worked: on
# the contrast that DEFINED this bug — directness with the prose held jargony — v1
# scored +1 for both messages (a flat failure) and v2 scored +2 vs -1. DIRECT_PLAIN and
# DIRECT_JARGON landed IDENTICALLY at +2, which is the correct answer, because they
# lead with the verdict and differ only in prose. Jargon stopped reaching directness.
#
# Then the concision adjustment threw it away. Both +2 bodies collapsed to 0, because
# the model marked 2-3 sentences "stray" that the prompt itself lists as NEEDED —
# evidence, a decision, a risk. The reviewer predicted this before a line was written:
# the stray classification is the same payload judgement the model already failed at,
# and shape-checking a list of indices does not make the classification true.
#
# THE RULING. Ship the grounded half. "I want something that works approximately and at
# least better than what we had; later we can return to it to optimize." So the weight
# is POSITION ALONE — every input to it survived a check against the source text — and
# the concision path is kept, still measured, still reported, simply not weighted.
#
# WHY THE CODE STAYS. This is a deliberate park, not a deletion. The strays are still
# extracted, still validated for shape, still carried in the result as `stray_count`
# and named in the detail line, so the follow-up has data to work from instead of
# starting over. Flip this to True to re-weight them.
#
# WHAT THE FOLLOW-UP HAS TO SOLVE (do not re-derive this):
#   - the model over-marks strays on bodies whose later sentences are evidence and
#     risks — the two categories the prompt explicitly protects — so the failure is in
#     the model's reading of the rubric, not in the rubric's wording alone;
#   - any fix must be checkable in Python or it inherits this same problem;
#   - candidate not yet tried: ask for a per-sentence needed/not-needed verdict for
#     EVERY sentence rather than a free-form list, so each answer is attributable to a
#     specific sentence and can be scored one at a time.
CONCISION_ADJUSTMENT_ENABLED = False

# The sentinel the model returns when no sentence in the body states a payload.
NO_PAYLOAD_INDEX = 0

# The canonical child tags of each v2 schema, handed to _repair_llm_xml so it repairs
# TOWARD these instead of v1's four. It rebuilds the response from the fields it knows
# and DELETES the rest, so calling it with the wrong set silently drops data: v2's tone
# reply matched v1's <tone> only and lost <tone-evidence> entirely, reporting a graded
# tone with a blank justification and raising nothing (found live 2026-08-01).
DIRECTNESS_FIELDS = ( "first-payload-quote", "first-payload-index", "stray-after-indices" )
TONE_FIELDS       = ( "tone-evidence", "tone" )

# Words that end in a period without ending a sentence. Deliberately short — a long
# list is a liability, since every entry is a place a real sentence break can be
# swallowed. Single letters (initials) are handled separately, by length.
#
# ⚠️ NO ENTRY MAY BE A COMMON ENGLISH WORD. "no" was here first (for "No. 5") and it
# ate a real boundary: `He said "no." Then he left.` came back as ONE sentence, because
# the guard cannot tell the abbreviation from the word. The cost is asymmetric — a
# missing entry mis-splits one rare construction, while a too-common entry silently
# merges sentences in ordinary prose and shifts every index after it. When in doubt,
# leave it out.
_ABBREVIATIONS = frozenset( {
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "vs", "etc", "eg", "ie",
    "approx", "vol", "al", "inc", "ltd",
} )


class ExtractionError( ValueError ):
    """
    Raised when the model's extraction cannot be reconciled with the source text.

    This is DELIBERATELY not a grade. The whole point of v2 is that an unverifiable
    answer is refused rather than scored: judge_v2 catches this, retries, and on
    exhaustion returns a NAMED non-answer that the discrimination probe drops from
    its ordering. An ExtractionError that quietly became a `meh` would rebuild, one
    level out, the exact defect this design exists to remove.
    """


def split_sentences( body_text ):
    """
    Split a DM body into sentences — deliberately boring, and the ONLY splitter.

    The list this returns is both (a) what the model is shown, numbered, and (b) what
    the validator compares the model's quote against. Those must be the SAME list:
    two independent splits that disagree would reject correct model output and accept
    nothing useful.

    Requires:
        - body_text is a string (may be empty)

    Ensures:
        - returns a list of whitespace-normalized sentences, in order, no empties
        - an empty or whitespace-only body returns []
        - splits on . ! ? (and runs of them) followed by whitespace, tolerating
          closing quotes/brackets before the space
        - does NOT split on a decimal point ("30.5 seconds"), because the period is
          not followed by whitespace
        - does NOT split after a known abbreviation ("etc. ", "vs. ") or a single-
          letter initial ("R. Ruiz")
        - the concatenation of the result, space-joined, equals the whitespace-
          normalized input — no character is invented or dropped
    """
    text = " ".join( body_text.split() )
    if not text: return []

    cuts = []
    for m in re.finditer( r"[.!?]+[\"'”’)\]]*(?=\s)", text ):
        if m.group().startswith( "." ):
            head      = text[ : m.start() ]
            last_word = re.search( r"([A-Za-z0-9]+)$", head )
            if last_word is not None:
                word = last_word.group( 1 ).lower()
                if word in _ABBREVIATIONS: continue
                if len( word ) == 1 and word.isalpha(): continue
        cuts.append( m.end() )

    sentences = []
    previous  = 0
    for cut in cuts:
        piece = text[ previous : cut ].strip()
        if piece: sentences.append( piece )
        previous = cut
    tail = text[ previous : ].strip()
    if tail: sentences.append( tail )

    return sentences


def number_sentences( sentences ):
    """
    Render the numbered body the extraction prompt shows the model.

    Requires:
        - sentences is the list returned by split_sentences

    Ensures:
        - returns one "N. <sentence>" line per sentence, 1-based, newline-joined
        - an empty list returns ""
    """
    return "\n".join( f"{i}. {s}" for i, s in enumerate( sentences, start=1 ) )


def _normalize_for_match( text ):
    """
    Collapse a sentence to the form the equality check compares.

    Ensures:
        - whitespace runs collapse to one space, ends stripped, case folded
        - nothing else is removed — punctuation is SIGNIFICANT here, because a quote
          that drops the final period is a paraphrase, and a paraphrase is the thing
          the check exists to catch
    """
    return " ".join( str( text ).split() ).strip().casefold()


def parse_index( raw ):
    """
    Parse the model's payload index into an int.

    Requires:
        - raw is a string (possibly empty, possibly prose)

    Ensures:
        - returns a non-negative int
        - accepts "1", " 1 ", "1." and a bare "none"/"n/a"/"" as NO_PAYLOAD_INDEX
        - raises ExtractionError on anything else — NEVER guesses, because a guessed
          index would be scored as if it had been verified
    """
    text = str( raw ).strip().lower().rstrip( "." )
    if text in ( "", "none", "n/a", "na", "null" ): return NO_PAYLOAD_INDEX
    m = re.fullmatch( r"(\d+)", text )
    if m is None:
        raise ExtractionError( f"payload index is not a number: {raw!r}" )
    return int( m.group( 1 ) )


def parse_indices( raw ):
    """
    Parse the model's stray-index list into a list of ints.

    Requires:
        - raw is a string

    Ensures:
        - accepts "4,7", "4, 7", "[4, 7]", "4 7" and returns [4, 7]
        - accepts "", "none", "n/a" and returns []
        - raises ExtractionError if any element is not a number — a list we cannot
          read is not a list we may score
    """
    text = str( raw ).strip().strip( "[]()" ).strip()
    if text.lower() in ( "", "none", "n/a", "na", "null" ): return []
    parts = [ p for p in re.split( r"[,\s]+", text ) if p ]
    out   = []
    for p in parts:
        m = re.fullmatch( r"(\d+)", p.rstrip( "." ) )
        if m is None:
            raise ExtractionError( f"stray index is not a number: {p!r} (in {raw!r})" )
        out.append( int( m.group( 1 ) ) )
    return out


def validate_extraction( quote, payload_index, stray_indices, sentences ):
    """
    Check the model's extraction against the source text. Raise, or return silently.

    This function IS the design. Everything v2 claims over v1 rests on these checks
    actually running, which is why the unit tier feeds each one an input that MUST be
    rejected — a check nobody has watched fail is not known to be running.

    Requires:
        - quote is a string; payload_index is an int; stray_indices is a list of ints
        - sentences is the split_sentences output for the SAME body

    Ensures:
        - returns None when the extraction is reconcilable with the source
        - raises ExtractionError otherwise, naming which check failed

    The checks:
        1. index in range — 1..len(sentences), or exactly 0 for "no payload"
        2. no-payload consistency — index 0 means no quote and no strays; claiming a
           quote while claiming no payload is incoherent, not lenient
        3. quote EQUALS the whole numbered sentence (whitespace/case-normalized).
           Equality, NOT containment: containment lets a model quote the clean clause
           of a sentence that also buries a blocker, land index 1 with no strays, and
           collect the top of the scale on a body that should not get it
        4. first occurrence — when the same sentence text appears twice, the index
           must be the FIRST one, or a model could pick whichever copy grades better
           and pass every other check
        5. stray indices — each in range, each strictly AFTER the payload, none
           repeated
    """
    if not sentences:
        raise ExtractionError( "no sentences to validate against (empty body)" )

    # 1 + 2 — range and no-payload coherence
    if payload_index == NO_PAYLOAD_INDEX:
        if _normalize_for_match( quote ):
            raise ExtractionError( f"index 0 (no payload) but a quote was given: {quote!r}" )
        if stray_indices:
            raise ExtractionError( f"index 0 (no payload) but stray indices were given: {stray_indices}" )
        return

    if not 1 <= payload_index <= len( sentences ):
        raise ExtractionError(
            f"payload index {payload_index} out of range 1..{len( sentences )}"
        )

    # 3 — equality against the whole sentence
    wanted = _normalize_for_match( quote )
    actual = _normalize_for_match( sentences[ payload_index - 1 ] )
    if wanted != actual:
        raise ExtractionError(
            f"quote does not equal sentence {payload_index}: quoted {quote!r}, "
            f"sentence is {sentences[ payload_index - 1 ]!r}"
        )

    # 4 — first occurrence of that text
    first = next( i for i, s in enumerate( sentences, start=1 )
                  if _normalize_for_match( s ) == wanted )
    if first != payload_index:
        raise ExtractionError(
            f"sentence {payload_index} is a repeat; its first occurrence is {first}"
        )

    # 5 — stray indices
    seen = set()
    for idx in stray_indices:
        if not 1 <= idx <= len( sentences ):
            raise ExtractionError( f"stray index {idx} out of range 1..{len( sentences )}" )
        if idx <= payload_index:
            raise ExtractionError(
                f"stray index {idx} is not after the payload at {payload_index}"
            )
        if idx in seen:
            raise ExtractionError( f"stray index {idx} is repeated" )
        seen.add( idx )


def structural_code( payload_index, stray_count ):
    """
    Map a VALIDATED (index, stray count) onto GPT's structural code.

    Requires:
        - payload_index and stray_count are non-negative ints that already passed
          validate_extraction — this function does no checking of its own

    Ensures:
        - returns a key of STRUCTURE_TO_WEIGHT
        - index 0 → "missing" regardless of stray count
        - index 1 → lead_clean / lead_one_stray / mixed on 0 / 1 / >=2 strays
        - index 2 → "mixed"; index >= 3 → "late"
    """
    if payload_index == NO_PAYLOAD_INDEX: return "missing"
    if payload_index == 1:
        if stray_count == 0: return "lead_clean"
        if stray_count == 1: return "lead_one_stray"
        return "mixed"
    if payload_index == 2: return "mixed"
    return "late"


def position_weight( payload_index ):
    """
    The weight from POSITION ALONE — the fully-validated half of the directness score.

    Requires:
        - payload_index is a non-negative int that passed validate_extraction

    Ensures:
        - returns an int in [-2, 2] per POSITION_TO_WEIGHT, with index >= 3 → -1
    """
    return POSITION_TO_WEIGHT.get( payload_index, _LATE_POSITION_WEIGHT )


def code_weight( code ):
    """
    The weight a structural code WOULD carry if the concision half were weighted.

    Requires:
        - code is a key of STRUCTURE_TO_WEIGHT

    Ensures:
        - returns the int weight; an unknown code raises KeyError rather than
          degrading to 0, because every caller derives its code from structural_code
          and a miss means the table and the mapper have drifted apart

    NOTE: this is no longer what the judge scores — see directness_weight below and
    the CONCISION_ADJUSTMENT_ENABLED note. It is kept because the structural code is
    still computed and reported, and because the follow-up work needs it.
    """
    return STRUCTURE_TO_WEIGHT[ code ]


def directness_weight( payload_index, stray_count ):
    """
    THE directness weight the judge scores.

    Requires:
        - payload_index and stray_count are non-negative ints that already passed
          validate_extraction

    Ensures:
        - with CONCISION_ADJUSTMENT_ENABLED False (the shipped state), returns
          position_weight( payload_index ) — every input to it was checked against the
          source text, so the whole score is grounded
        - with it True, returns the structural-code weight, which folds in the model's
          unvalidated stray classification
        - the two agree on `missing` (-2) and on `late` (-1); they differ only where a
          verdict leads, which is precisely where the stray count was destroying a
          correct +2
    """
    if CONCISION_ADJUSTMENT_ENABLED:
        return code_weight( structural_code( payload_index, stray_count ) )
    return position_weight( payload_index )


class DmDirectnessExtraction( BaseXMLModel ):
    """
    The model's OBSERVATIONS about where the verdict sits. Carries NO grade.

    Field order is generation order, and generation order matters: a grade token
    emitted before its evidence cannot have been informed by that evidence. Here the
    question does not arise, because there is no grade field at all — Python computes
    the weight from these three observations after checking them.

    Requires:
        - the LLM returns <response> with the three dash-cased child tags

    Ensures:
        - all fields are str ("LLM I/O is always text"); parsing to int happens in
          parse_index / parse_indices, which raise rather than guess
    """

    first_payload_quote  : str = Field( default="", description="The earliest sentence that states a payload, copied verbatim", alias="first-payload-quote" )
    first_payload_index  : str = Field( default="", description="1-based number of that sentence, or 0 if no sentence states a payload", alias="first-payload-index" )
    stray_after_indices  : str = Field( default="", description="Comma-separated numbers of sentences after it that carry nothing the reader needs, or none", alias="stray-after-indices" )

    def to_xml( self, root_tag="response", pretty=True ):
        """
        Serialize with DASH-cased tags, matching this repo's XML convention.

        BaseXMLModel.to_xml() calls model_dump() without by_alias, so a declared alias
        is honoured parsing IN and ignored going OUT. Ask Pydantic for the aliases it
        already knows rather than hand-building a dict, so a renamed field cannot
        drift from its tag.
        """
        import xmltodict
        return xmltodict.unparse(
            { root_tag: self.model_dump( by_alias=True, exclude_none=True ) }, pretty=pretty
        )

    @classmethod
    def get_example_for_template( cls ):
        """
        Structure-teaching example for {{PYDANTIC_XML_EXAMPLE}} injection.

        The injected example is a ROUND TRIP — the template processor fills the marker
        from this instance's own to_xml() — so it is well-formed BY CONSTRUCTION. That
        property is why the marker exists and why v2 keeps it: the 2026-08-01 session
        removed a structural example from the v1 prompt to stop the model copying a
        plausible grade, and the model immediately began emitting unclosed tags.

        The content is descriptive prose, never a usable answer. There is no grade to
        copy here, which removes the failure mode entirely for this schema.
        """
        return cls( **{
            "first-payload-quote" : "COPY THE EARLIEST SENTENCE THAT STATES A PAYLOAD, WORD FOR WORD",
            "first-payload-index" : "ITS NUMBER, OR 0 IF NO SENTENCE STATES ONE",
            "stray-after-indices" : "NUMBERS OF ANY LATER SENTENCES THE READER DOES NOT NEED, OR none",
        } )


class DmToneJudgement( BaseXMLModel ):
    """
    The tone half of v2 — the SAME rubric v1 uses, with one change: evidence first.

    Tone was never the defect. On the 2026-08-01 2x2 it graded all four bodies
    correctly, including naming the invented vocabulary in the body whose directness
    it got wrong. So the rubric is left alone and only the field ORDER changes: the
    evidence tag now precedes the grade tag, so the grade token is generated after
    the words it is supposed to rest on (Claude expert §3.1).

    Requires:
        - the LLM returns <response> with <tone-evidence> then <tone>

    Ensures:
        - tone is a grade-label string; tone_weight() maps it via v1's GRADE_TABLE
    """

    tone_evidence : str = Field( default="", description="The specific words or phrases the grade rests on", alias="tone-evidence" )
    tone          : str = Field( default="meh", description="Tone grade label (terrible/bad/meh/good/exemplary)" )

    def to_xml( self, root_tag="response", pretty=True ):
        """Serialize with dash-cased tags — see DmDirectnessExtraction.to_xml."""
        import xmltodict
        return xmltodict.unparse(
            { root_tag: self.model_dump( by_alias=True, exclude_none=True ) }, pretty=pretty
        )

    def tone_weight( self ):
        """Integer weight for the tone grade, via v1's shared table (unknown → 0)."""
        from cosa.agents.dm_quality_judge.xml_models import grade_weight
        return grade_weight( self.tone )

    def tone_emoji( self ):
        """Emoji for the tone grade, via v1's shared table (unknown → 🤷)."""
        return WEIGHT_TO_EMOJI[ self.tone_weight() ]

    @classmethod
    def get_example_for_template( cls ):
        """
        Structure-teaching example — evidence tag first, grade tag second.

        The grade placeholder keeps Rick's verbatim CHOOSE-ONE form (2026-08-01): the
        live Phi-4 substitutes a real label rather than echoing the brackets, which
        retired the earlier "placeholders do not work here" conclusion.
        """
        return cls( **{
            "tone-evidence" : "QUOTE THE SPECIFIC WORDS YOUR GRADE RESTS ON",
            "tone"          : "[CHOOSE ONE: {terrible|bad|meh|good|exemplary}]",
        } )


def quick_smoke_test():
    """Smoke test for the v2 primitives — pure Python, no LLM call."""
    print( "\n" + "=" * 60 )
    print( "DM Quality Judge v2 — models + scoring smoke test" )
    print( "=" * 60 )

    passed = failed = 0

    def check( name, fn ):
        nonlocal passed, failed
        try:
            fn()
            print( f"   ✓ {name}" ); passed += 1
        except Exception as e:
            print( f"   ✗ {name}: {type( e ).__name__}: {e}" ); failed += 1

    print( "\n1. Sentence splitting..." )
    check( "plain three-sentence body", lambda: _assert(
        split_sentences( "One thing. Two thing! Three?" ) == [ "One thing.", "Two thing!", "Three?" ] ) )
    check( "decimal is not a boundary", lambda: _assert(
        len( split_sentences( "The timeout is 30.5 seconds and it should be 5." ) ) == 1 ) )
    check( "abbreviation is not a boundary", lambda: _assert(
        len( split_sentences( "Tests, docs, etc. are done. Ship it." ) ) == 2 ) )
    check( "empty body", lambda: _assert( split_sentences( "   " ) == [] ) )

    print( "\n2. Structural codes..." )
    check( "lead_clean",     lambda: _assert( structural_code( 1, 0 ) == "lead_clean" ) )
    check( "lead_one_stray", lambda: _assert( structural_code( 1, 1 ) == "lead_one_stray" ) )
    check( "mixed via strays", lambda: _assert( structural_code( 1, 2 ) == "mixed" ) )
    check( "mixed via index",  lambda: _assert( structural_code( 2, 0 ) == "mixed" ) )
    check( "late",             lambda: _assert( structural_code( 3, 0 ) == "late" ) )
    check( "missing",          lambda: _assert( structural_code( 0, 0 ) == "missing" ) )

    print( "\n3. Controls — each MUST be rejected..." )
    body = "Phase one is done. I read the ticket history. The timeout is wrong."
    sents = split_sentences( body )
    check( "fabricated quote", lambda: _assert_raises(
        lambda: validate_extraction( "I invented this sentence.", 1, [], sents ) ) )
    check( "wrong index", lambda: _assert_raises(
        lambda: validate_extraction( "Phase one is done.", 2, [], sents ) ) )
    check( "sub-clause, not whole sentence", lambda: _assert_raises(
        lambda: validate_extraction( "Phase one", 1, [], sents ) ) )
    check( "stray before the payload", lambda: _assert_raises(
        lambda: validate_extraction( "The timeout is wrong.", 3, [ 1 ], sents ) ) )
    check( "stray out of range", lambda: _assert_raises(
        lambda: validate_extraction( "Phase one is done.", 1, [ 99 ], sents ) ) )
    check( "duplicate stray", lambda: _assert_raises(
        lambda: validate_extraction( "Phase one is done.", 1, [ 2, 2 ], sents ) ) )
    check( "quote given with index 0", lambda: _assert_raises(
        lambda: validate_extraction( "Phase one is done.", 0, [], sents ) ) )
    dup = split_sentences( "Same line. Other line. Same line." )
    check( "second copy of a repeated sentence", lambda: _assert_raises(
        lambda: validate_extraction( "Same line.", 3, [], dup ) ) )

    print( "\n4. A valid extraction passes..." )
    check( "verdict first, one stray", lambda: validate_extraction(
        "Phase one is done.", 1, [ 2 ], sents ) )
    check( "weights split out", lambda: _assert(
        position_weight( 1 ) == 2 and code_weight( structural_code( 1, 1 ) ) == 1 ) )
    check( "strays do NOT move the shipped score", lambda: _assert(
        not CONCISION_ADJUSTMENT_ENABLED
        and directness_weight( 1, 0 ) == directness_weight( 1, 3 ) == 2 ) )
    check( "position and code still agree on late/missing", lambda: _assert(
        directness_weight( 3, 0 ) == -1 and directness_weight( 0, 0 ) == -2 ) )

    print( "\n5. Schema round trips..." )
    check( "directness round trip", lambda: _assert(
        DmDirectnessExtraction.from_xml(
            DmDirectnessExtraction( **{ "first-payload-quote": "A.", "first-payload-index": "1",
                                        "stray-after-indices": "2,3" } ).to_xml()
        ).stray_after_indices == "2,3" ) )
    check( "tone round trip", lambda: _assert(
        DmToneJudgement.from_xml(
            DmToneJudgement( **{ "tone-evidence": "owed oracle", "tone": "bad" } ).to_xml()
        ).tone_weight() == -1 ) )
    check( "evidence tag precedes grade tag", lambda: _assert(
        DmToneJudgement.get_example_for_template().to_xml().index( "tone-evidence" )
        < DmToneJudgement.get_example_for_template().to_xml().index( "<tone>" ) ) )

    print( f"\n{'=' * 60}" )
    print( f"v2 models smoke test: {passed} passed, {failed} failed" )
    print( "=" * 60 )
    return failed == 0


def _assert( condition ):
    if not condition: raise AssertionError( "condition was false" )


def _assert_raises( fn ):
    try:
        fn()
    except ExtractionError:
        return
    raise AssertionError( "expected ExtractionError, none raised" )


if __name__ == "__main__":
    exit( 0 if quick_smoke_test() else 1 )
