#!/usr/bin/env python3
"""
Unit tests for the slide-count check of the research-to-presentation live smoke.

The check reads a row of the done queue. That row carries `abstract` and `response_text` but no
`artifacts` dict, so the count has to come from the abstract's "Slides" line.
"""

from tests.smoke.test_research_to_presentation_live_smoke import ResearchToPresentationLiveSmokeTest

ANSWER = "Pipeline complete! Research report and presentation generated. Total cost: $1.6925. Presentation: /var/lupin/io/presentations/x"


def _check( job_data ):
    check = ResearchToPresentationLiveSmokeTest.__new__( ResearchToPresentationLiveSmokeTest )
    return check._check_slide_count( job_data )


def test_a_done_queue_row_carries_its_slide_count_in_the_abstract():
    row = { "response_text": ANSWER, "abstract": "**Research → Presentation Complete!**\n\n**Slides**: 12 slides\n\n**Cost**: $1.6925" }
    found = _check( row )
    assert found[ "ok" ] is True and "12" in found[ "detail" ]


def test_a_row_with_no_count_anywhere_still_fails_and_a_zero_count_fails():
    assert _check( { "response_text": ANSWER, "abstract": "**Research → Presentation Complete!**" } )[ "ok" ] is False
    assert _check( { "response_text": ANSWER, "abstract": "**Slides**: 0 slides" } )[ "ok" ] is False
    assert _check( { "response_text": ANSWER } )[ "ok" ] is False


def test_the_artifacts_value_still_wins_when_the_row_has_one():
    assert _check( { "artifacts": { "slide_count": 7 }, "response_text": ANSWER } )[ "ok" ] is True
    assert _check( { "artifacts": { "slide_count": 0 }, "response_text": ANSWER } )[ "ok" ] is False
