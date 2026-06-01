#!/usr/bin/env python3
"""
Unit tests for cosa.agents.decision_proxy.prompts.icrl_decision.

Pure prompt-template formatting: the case-history formatter (empty + populated
+ missing-key fallbacks) and the full prompt assembler. No external deps.
"""

from cosa.agents.decision_proxy.prompts.icrl_decision import (
    ICRL_DECISION_PROMPT,
    format_case_history,
    build_icrl_prompt,
)


def test_prompt_template_has_placeholders():
    assert "{question}" in ICRL_DECISION_PROMPT
    assert "{category}" in ICRL_DECISION_PROMPT
    assert "{history}" in ICRL_DECISION_PROMPT


# ----------------------------------------------------------------------------
# format_case_history
# ----------------------------------------------------------------------------
def test_format_case_history_empty_returns_default():
    assert format_case_history( [] ) == "(No similar past decisions found)"


def test_format_case_history_numbers_and_includes_fields():
    cases = [
        { "question": "Deploy?", "decision_value": "approved",
          "ratification_state": "ratified", "created_at": "2026-01-01" },
        { "question": "Rollback?", "decision_value": "requires_review",
          "ratification_state": "pending", "created_at": "2026-01-02" },
    ]
    out = format_case_history( cases )
    assert "1. [approved]" in out
    assert "2. [requires_review]" in out
    assert "ratification: ratified" in out
    assert "date: 2026-01-02" in out
    assert "Question: Deploy?" in out


def test_format_case_history_missing_keys_fall_back_to_unknown():
    out = format_case_history( [ {} ] )
    assert "[unknown]" in out
    assert "ratification: unknown" in out
    assert "date: unknown" in out
    assert "Question: unknown" in out


# ----------------------------------------------------------------------------
# build_icrl_prompt
# ----------------------------------------------------------------------------
def test_build_icrl_prompt_interpolates_all_sections():
    cases = [ { "question": "Q1", "decision_value": "approved",
                "ratification_state": "ratified", "created_at": "2026-01-01" } ]
    prompt = build_icrl_prompt( "Should I ship?", "deploy", cases )
    assert "Should I ship?" in prompt
    assert "deploy" in prompt
    assert "1. [approved]" in prompt          # history was formatted in


def test_build_icrl_prompt_empty_history_uses_default_message():
    prompt = build_icrl_prompt( "Q?", "cat", [] )
    assert "(No similar past decisions found)" in prompt
    assert "Q?" in prompt
    assert "cat" in prompt
