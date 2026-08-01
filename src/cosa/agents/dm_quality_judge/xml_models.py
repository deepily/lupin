#!/usr/bin/env python3
"""
XML response model for the DM Quality Judge.

Defines DmQualityJudgeResponse — the Mistral judge's grade of a peer-DM body on
the two QUALITATIVE dimensions (Directness, Tone). Length is graded separately
in Python (judge.py), so it is NOT a field here.

Modeled on cosa/agents/notification_proxy/xml_models.py (VerificationResponse):
    - all fields are `str` — "LLM I/O is always text". The model emits a grade
      LABEL ("good", "exemplary", ...); Python maps the label to a weight/emoji.
    - None values coerce to "" (xmltodict emits None for empty tags).
    - BaseXMLModel.from_xml() parses; malformed XML raises XMLParsingError.

The canonical grade label ⇄ weight ⇄ emoji table lives here (GRADE_TABLE) so the
judge, the audit counter, and the tests all read ONE source.
"""

import re

from pydantic import Field, field_validator

from cosa.agents.io_models.utils.util_xml_pydantic import BaseXMLModel


# ── The single Likert table ───────────────────────────────────────────────────
# Zero-centered 5-point scale (Rick 2026-07-31). label → (weight, emoji). Both
# the judge's per-dimension grade and the Python-computed overall bucket read
# their emoji from this same table, keyed by weight (WEIGHT_TO_EMOJI below).
GRADE_TABLE = {
    "terrible"          : ( -2, "😞" ),
    "bad"               : ( -1, "👎" ),
    "meh"               : (  0, "🤷" ),
    "good"              : (  1, "👍" ),
    "exemplary"         : (  2, "⭐" ),
}

# weight → emoji, derived from GRADE_TABLE so it can never drift from it.
WEIGHT_TO_EMOJI = { weight: emoji for weight, emoji in GRADE_TABLE.values() }

# The safe default for an unknown/blank label — meh / 0 (never raise on a
# surprise label; the judge is advisory, a bad label degrades to neutral).
_FALLBACK_LABEL = "meh"

# Observed-typo aliases from the live 24B GPTQ model (bug a5f7b36d). The model
# emits "meah" for "meh"; map it INTENTIONALLY so it lands on meh/0 as a real
# grade rather than silently via the unknown→meh fallback (which would also swallow
# a genuinely-unrecognized label). Keyed by the already-normalized form.
_LABEL_ALIASES = {
    "meah" : "meh",
}


def normalize_grade_label( label ):
    """
    Normalize an LLM-emitted grade label to a canonical GRADE_TABLE key.

    Requires:
        - label is a string or None

    Ensures:
        - returns a key present in GRADE_TABLE
        - lowercases, strips, and COLLAPSES any run of whitespace/hyphens/underscores
          to a single underscore ("Needs Improvement" / "needs-improvement" /
          "needs _ improvement" / "needs__improvement" → "needs_improvement")
        - applies observed-typo aliases (e.g. "meah" → "meh"), bug a5f7b36d
        - an unknown or blank label degrades to "meh" (never raises)

    🔴 WHY A COLLAPSE AND NOT TWO .replace() CALLS (bug ca7a2cbf, 2026-08-01). The
       live 24B GPTQ model emits `needs _ improvement` — spaces AROUND the
       underscore, the same sloppiness that produced spaced TAGS in a5f7b36d.
       Sequential replaces turned that into `needs___improvement`, which is not in
       GRADE_TABLE, so the most-frequent multi-word label in the whole scale fell
       through to the `meh` fallback SILENTLY, on every occurrence.

       That fallback exists for a genuinely unrecognizable label. It was instead
       swallowing a perfectly recoverable one and reporting 0 — a real grade of
       -1 rendered as neutral, with nothing anywhere saying a label had been
       dropped. Measured live: Tone read `meh` for every DM tested while the model
       was in fact returning `needs_improvement`.

       ⇒ The lesson is about the FALLBACK, not the spacing. A degrade-to-neutral
         that cannot distinguish "I do not recognize this" from "I failed to parse
         something I should have recognized" reports both as a considered judgement
         of `meh`.
    """
    if not label:
        return _FALLBACK_LABEL
    key = re.sub( r"[\s_\-]+", "_", str( label ).strip().lower() ).strip( "_" )
    key = _LABEL_ALIASES.get( key, key )
    return key if key in GRADE_TABLE else _FALLBACK_LABEL


def grade_weight( label ):
    """
    Map a grade label to its integer weight (via normalize_grade_label).

    Ensures:
        - returns an int in [-2, 2]; unknown/blank → 0 (meh)
    """
    return GRADE_TABLE[ normalize_grade_label( label ) ][ 0 ]


def grade_emoji( label ):
    """
    Map a grade label to its emoji (via normalize_grade_label).

    Ensures:
        - returns the emoji string; unknown/blank → 🤷 (meh)
    """
    return GRADE_TABLE[ normalize_grade_label( label ) ][ 1 ]


class DmQualityJudgeResponse( BaseXMLModel ):
    """
    XML response from the Mistral DM Quality Judge.

    Grades a peer-DM body on the two qualitative dimensions. Length is Python-only
    and is NOT part of this response.

    Requires:
        - the LLM returns XML with a <response> root and <directness>/<tone>
          grade LABELS drawn from GRADE_TABLE

    Ensures:
        - directness / tone are grade-label strings (default "meh")
        - directness_note / tone_note are short free-text justifications (may be "")
        - directness_weight()/tone_weight() map to ints; unknown labels → 0
    """

    # Tag names are DASH-cased via alias, matching this repo's convention
    # (`line-number`, `one-line-of-code`, `rephrased-answer` in io_models/xml_models.py).
    # The Python attribute stays snake_case; only the XML tag carries the dash.
    directness      : str = Field( default="meh", description="Directness grade label (terrible/bad/meh/good/exemplary)" )
    directness_note : str = Field( default="",    description="One short sentence justifying the directness grade", alias="directness-note" )
    tone            : str = Field( default="meh", description="Tone grade label (terrible/bad/meh/good/exemplary)" )
    tone_note       : str = Field( default="",    description="One short sentence justifying the tone grade", alias="tone-note" )

    @field_validator( "*", mode="before" )
    @classmethod
    def _coerce_none_to_empty_string( cls, v ):
        """
        Coerce None (xmltodict's empty-tag value) to "" for all fields.

        Requires:
            - v is the field value (may be None from xmltodict)

        Ensures:
            - returns "" for None; passes through non-None values unchanged
        """
        if v is None:
            return ""
        return v

    def to_xml( self, root_tag="response", pretty=True ):
        """
        Serialize with DASH-cased tags, matching this repo's XML convention.

        Requires:
            - the model's dash aliases are declared on the note fields

        Ensures:
            - `<directness-note>` / `<tone-note>` in the output, never underscores
            - every other field is unchanged

        BaseXMLModel.to_xml() calls model_dump() WITHOUT by_alias, so a declared
        alias is honoured on the way IN (parsing) and silently ignored on the way
        OUT. Every other dash-cased model in this repo works around that by
        hand-building a literal dict in its own to_xml() override; this does the
        same job by asking Pydantic for the aliases it already knows about, so a
        renamed field cannot drift from its tag.
        """
        import xmltodict
        return xmltodict.unparse(
            { root_tag: self.model_dump( by_alias=True, exclude_none=True ) }, pretty=pretty
        )

    def directness_weight( self ):
        """Integer weight for the directness grade (unknown/blank → 0)."""
        return grade_weight( self.directness )

    def tone_weight( self ):
        """Integer weight for the tone grade (unknown/blank → 0)."""
        return grade_weight( self.tone )

    def directness_emoji( self ):
        """Emoji for the directness grade (unknown/blank → 🤷)."""
        return grade_emoji( self.directness )

    def tone_emoji( self ):
        """Emoji for the tone grade (unknown/blank → 🤷)."""
        return grade_emoji( self.tone )

    @classmethod
    def get_example_for_template( cls ):
        """
        Get an example instance for prompt-template injection.

        PLACEHOLDER CONTENT, matching the shape every other agent in this repo uses
        (`agents/math.txt` injects `<thoughts>Your thoughts</thoughts>`,
        `<idea1>Your first idea</idea1>`). The injected example teaches STRUCTURE;
        it must not read as an ANSWER.

        Two earlier attempts here were both wrong, in opposite directions, and the
        history matters because each one looks correct on its own:

          - `[one of: terrible, needs_improvement, ...]` (bug a5f7b36d) — an ENUM
            HINT in brackets. The 24B echoed the brackets verbatim as malformed
            XML. That failure was read as "placeholders don't work here," and the
            conclusion drawn was to go fully concrete.
          - `good` / "Leads with the verdict in the first sentence." — a filled,
            PLAUSIBLE grade. It is well-formed, and the model copied it byte-for-
            byte onto messages it did not describe, including the single word
            "yes". Removing it to stop the copying took the well-formedness
            lesson with it, and the model began emitting unclosed tags.

        Neither failure was about placeholders-vs-concrete. `[one of: ...]` failed
        because bracket-enum syntax is not prose; a plausible grade failed because
        it is a usable answer. Math's form is neither: plain descriptive prose that
        no model would mistake for a verdict. The grade vocabulary is already
        stated in the prompt's Task section, so nothing is lost by not repeating it
        here.
        """
        return cls(
            directness        = "[CHOOSE ONE: {terrible|bad|meh|good|exemplary}]",
            **{ "directness-note" : "YOUR COMMENTS ON DIRECTNESS HERE",
                "tone"            : "[CHOOSE ONE: {terrible|bad|meh|good|exemplary}]",
                "tone-note"       : "YOUR COMMENTS ON TONE HERE" }
        )

    @classmethod
    def quick_smoke_test( cls, debug=False ):
        """
        Quick smoke test for DmQualityJudgeResponse.

        Args:
            debug: Enable debug output

        Returns:
            True if all checks pass
        """
        if debug: print( f"Testing {cls.__name__}..." )

        try:
            if not super().quick_smoke_test( debug=False ):
                return False

            # Construction + weight/emoji mapping across all 5 levels
            for label, ( weight, emoji ) in GRADE_TABLE.items():
                r = cls( directness=label, tone=label )
                assert r.directness_weight() == weight
                assert r.tone_weight()       == weight
                assert r.directness_emoji()  == emoji

            # Unknown label degrades to meh/0
            junk = cls( directness="banana", tone="" )
            assert junk.directness_weight() == 0
            assert junk.tone_weight()       == 0
            assert junk.directness_emoji()  == "🤷"

            # Label normalization (padding / separators / case). Rick's 2026-08-01
            # vocabulary has no multi-word label, so the multi-word case that
            # motivated the collapse is exercised in the unit suite rather than here.
            assert normalize_grade_label( "  BAD  " )   == "bad"
            assert normalize_grade_label( "_bad_" )     == "bad"
            assert normalize_grade_label( "Exemplary" ) == "exemplary"
            assert normalize_grade_label( None )        == "meh"

            # XML round-trip
            xml_str = r.to_xml()
            parsed  = cls.from_xml( xml_str )
            assert parsed.tone == r.tone

            # None coercion
            none_r = cls( directness="good", directness_note=None, tone="meh", tone_note=None )
            assert none_r.directness_note == ""
            assert none_r.tone_note       == ""

            if debug: print( f"✓ {cls.__name__} smoke test PASSED" )
            return True

        except Exception as e:
            if debug: print( f"✗ {cls.__name__} smoke test FAILED: {e}" )
            return False


def quick_smoke_test():
    """Module-level smoke test following CoSA convention."""
    return DmQualityJudgeResponse.quick_smoke_test( debug=True )


if __name__ == "__main__":
    success = quick_smoke_test()
    exit( 0 if success else 1 )
