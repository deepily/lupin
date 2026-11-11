#!/usr/bin/env python3
"""
Unit tests for the two helpers the research and status prompts share.

Each prompt builder used to repeat the clip and the audience block inline. Both now call
clip_to_ceiling and audience_block, so the two prompt families cannot drift apart.
"""

from cosa.agents.podcast_generator.prompts.script_generation import (
    AUDIENCE_DIALOGUE_GUIDELINES,
    audience_block,
    clip_to_ceiling,
    get_content_analysis_prompt,
    get_script_generation_prompt,
)
from cosa.agents.podcast_generator.prompts.status_report import get_status_analysis_prompt


def test_clip_leaves_text_alone_with_no_ceiling_or_room_to_spare():
    assert clip_to_ceiling( "abcdef", None ) == "abcdef"
    assert clip_to_ceiling( "abcdef", 6 ) == "abcdef"
    assert clip_to_ceiling( "abcdef", 100 ) == "abcdef"


def test_clip_cuts_to_exactly_the_ceiling():
    assert clip_to_ceiling( "abcdef", 3 ) == "abc"
    assert clip_to_ceiling( "abcdef", 0 ) == ""


def test_audience_block_is_empty_when_nothing_is_given_or_the_audience_is_unknown():
    assert audience_block( None, None ) == ""
    assert audience_block( "no such audience", None ) == ""


def test_audience_block_puts_the_guidelines_before_the_context():
    guidelines = AUDIENCE_DIALOGUE_GUIDELINES[ "expert" ]
    assert audience_block( "expert", None ) == f"\n{guidelines}\n"
    assert audience_block( None, "for a board" ) == "\n**Additional Audience Context**: for a board\n"
    assert audience_block( "expert", "for a board" ) == f"\n{guidelines}\n\n**Additional Audience Context**: for a board\n"


def test_all_three_prompt_builders_use_the_shared_pieces():
    marker = "for a board"
    text   = "x" * 50
    analysis = get_content_analysis_prompt( text, audience="expert", audience_context=marker, max_source_chars=10 )
    status   = get_status_analysis_prompt( text, audience="expert", audience_context=marker, max_source_chars=10 )
    assert audience_block( "expert", marker ) in analysis and audience_block( "expert", marker ) in status
    assert "x" * 10 in analysis and "x" * 11 not in analysis
    assert "x" * 10 in status and "x" * 11 not in status
    script = get_script_generation_prompt(
        content_analysis={}, research_content=text, host_a_personality=_host(), host_b_personality=_host(),
        audience="expert", audience_context=marker, max_source_chars=10 )
    assert audience_block( "expert", marker ) in script and "x" * 11 not in script


def _host():
    from cosa.agents.podcast_generator.config import DEFAULT_CURIOUS_HOST
    return DEFAULT_CURIOUS_HOST
