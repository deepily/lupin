"""
Unit tests for the DM-judge XML repair layer's tag-convention agnosticism (row 25e8ca1c).

WHY THIS EXISTS. The note fields declare Pydantic aliases — directness-note / tone-note —
so the shape from_xml() parses is DASH-cased. The repair layer used to normalize every
tag to UNDERSCORE and its tag regex excluded '-', so a clean dash-cased response from the
model slipped past the rewriter, then _extract_unclosed_fields (searching underscore
names) mangled it into a mismatched-tag parse error. Every call fell back to 0.

THE FIX these tests pin: _repair_llm_xml canonicalizes every separator variant
(underscore, spaces, dash) onto the one dash-cased form the parser accepts.

THE MUTATION CONTROL is test_clean_dash_xml_parses_after_repair: reverting the '-' out of
_TAG_RE (the pre-fix state) turns it red — the proof the test catches the real defect and
is not passing by construction.
"""
import re

import pytest

from cosa.agents.dm_quality_judge.judge import _repair_llm_xml
from cosa.agents.dm_quality_judge.xml_models import DmQualityJudgeResponse


def _parse( raw ):
    """Repair then parse, returning the model instance (or raising as the judge would)."""
    return DmQualityJudgeResponse.from_xml( _repair_llm_xml( raw ) )


# The shape phi-4 actually emits: clean, well-formed, DASH-cased note tags.
_CLEAN_DASH = (
    "<response>"
    "<directness>good</directness>"
    "<directness-note>Leads with the verdict in the first sentence.</directness-note>"
    "<tone>bad</tone>"
    "<tone-note>Rambles before the point.</tone-note>"
    "</response>"
)


def test_clean_dash_xml_parses_after_repair():
    # THE regression + THE mutation-control target. Pre-fix this raised a mismatched-tag
    # error; the fix must parse it AND populate the note fields (not leave them "").
    p = _parse( _CLEAN_DASH )
    assert p.directness == "good" and p.directness_weight() == 1
    assert p.tone       == "bad"  and p.tone_weight()       == -1
    assert p.directness_note == "Leads with the verdict in the first sentence."
    assert p.tone_note       == "Rambles before the point."


def test_underscore_variant_still_parses():
    raw = _CLEAN_DASH.replace( "directness-note", "directness_note" ).replace( "tone-note", "tone_note" )
    p   = _parse( raw )
    assert p.directness_note == "Leads with the verdict in the first sentence."
    assert p.tone_note       == "Rambles before the point."


def test_spaced_multiword_variant_still_parses():
    raw = (
        "<response>< directness >good</ directness >"
        "< directness note >x</ directness note >"
        "< tone >meh</ tone >< tone note >y</ tone note ></response>"
    )
    p = _parse( raw )
    assert p.directness == "good"
    assert p.directness_note == "x" and p.tone_note == "y"


def test_unclosed_dash_fields_are_recovered():
    # Open-but-never-closed dash tags — the recovery path must find them by their
    # canonical dash names, not underscore.
    raw = "<response><directness>good<directness-note>x<tone>bad<tone-note>y</response>"
    p   = _parse( raw )
    assert p.directness == "good" and p.tone == "bad"
    assert p.directness_note == "x" and p.tone_note == "y"


def test_stop_sentinel_and_prolog_are_dropped():
    raw = '<?xml version="1.0"?>' + _CLEAN_DASH + "</stop>"
    p   = _parse( raw )
    assert p.directness == "good" and p.tone_note == "Rambles before the point."


def test_repaired_clean_dash_is_idempotent():
    # Repairing already-clean XML must not corrupt it: the note tags survive a round trip.
    repaired = _repair_llm_xml( _CLEAN_DASH )
    assert "<directness-note>" in repaired and "<tone-note>" in repaired
    assert "mismatched" not in repaired.lower()
