#!/usr/bin/env python3
"""
The status-report prompt asks for humor and keeps every fact tied to the digest.

Rick asked the two hosts to lean into humor, wordplay and wry observations.
"""

from cosa.agents.podcast_generator import script_types as st
from cosa.agents.podcast_generator.prompts.status_report import STATUS_REPORT_SYSTEM_PROMPT


def tone_block() -> str:
    """
    Cut the tone block out of the prompt.

    Ensures:
        - returns the text from the tone heading up to the output-format heading
        - fails the test when either heading is missing or out of order
    """
    start = STATUS_REPORT_SYSTEM_PROMPT.find( "\nTONE:\n" )
    end   = STATUS_REPORT_SYSTEM_PROMPT.find( "\nOUTPUT FORMAT:" )
    assert 0 < start < end, "the prompt has no TONE block ahead of OUTPUT FORMAT"
    return STATUS_REPORT_SYSTEM_PROMPT[ start : end ]


def test_the_tone_block_asks_both_hosts_for_humor_wordplay_and_wry_observations():
    block = tone_block()
    assert "Both hosts lean into humor, wordplay and wry observations" in block
    assert "Where a topic offers one, make a wry remark or a play on words" in block
    assert "at least one" not in block, "a quota pushes the writer to invent a joke"


def test_every_joke_must_rest_on_the_digest_and_change_no_fact():
    block = tone_block()
    assert "rests on a fact in the digest and changes none of them" in block
    assert "When a joke and accuracy disagree, cut the joke" in block


def test_the_old_rule_to_say_only_what_the_digest_supports_stays_once_and_in_the_guidelines():
    prompt = STATUS_REPORT_SYSTEM_PROMPT
    assert prompt.count( "2. Say only what the digest supports" ) == 1
    assert prompt.index( "2. Say only what the digest supports" ) < prompt.index( "\nTONE:\n" )


def test_the_tone_block_adds_no_bracketed_stage_direction_and_forbids_them():
    block = tone_block()
    assert "[" not in block and "]" not in block, "a bracketed tag in the tone text would teach the model to write one"
    assert "Add no bracketed stage directions" in block


def test_the_tone_block_does_not_license_jokes_about_people_or_mistakes():
    assert "Never joke about a person, a mistake or the listener" in tone_block()


def test_the_status_report_type_sends_this_prompt_to_the_script_writer():
    assert st.get_profile( "status_report" ).system_prompt is STATUS_REPORT_SYSTEM_PROMPT


def test_an_irony_may_be_used_only_when_the_digest_states_it():
    block = tone_block()
    assert "Use an irony only when the digest itself states it" in block
    assert "an irony in the order of events" not in block
