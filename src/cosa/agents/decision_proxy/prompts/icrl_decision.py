#!/usr/bin/env python3
"""
ICRL (In-Context Reinforcement Learning) prompt template for decision disambiguation.

Provides a structured LLM prompt that includes similar past decisions
as in-context examples, enabling pattern-matching for ambiguous CBR cases.

Used only when CBR returns mixed verdicts with low confidence — a rare
fallback path for genuinely ambiguous decisions.

Dependency Rule:
    This module NEVER imports from notification_proxy or swe_team.
"""

ICRL_DECISION_PROMPT = """You are a decision proxy that approves or rejects engineering actions.

## Decision Question

{question}

## Category

{category}

## Similar Past Decisions

{history}

## Instructions

Based on the similar past decisions above, determine whether this action should be:
- **approved** — the action is safe and consistent with past approvals
- **requires_review** — the action is risky and should be reviewed by a human

Consider the category, the patterns in past decisions, and whether the ratification
outcomes support approval or rejection. If past decisions are mixed, lean toward
the majority pattern. If no clear pattern exists, prefer "requires_review" (safe default).

Respond with EXACTLY one word: "approved" or "requires_review"
"""


def format_case_history( similar_cases ):
    """
    Format a list of similar case dicts into a numbered history string.

    Requires:
        - similar_cases is a list of dicts (may be empty)
        - Each dict may have keys: question, decision_value, ratification_state, created_at

    Ensures:
        - Returns formatted string with numbered cases
        - Returns default message if empty list
        - Missing keys are handled gracefully with "unknown" fallback

    Args:
        similar_cases: List of case dicts from CBRPrediction.similar_cases

    Returns:
        Formatted history string
    """
    if not similar_cases:
        return "(No similar past decisions found)"

    lines = []
    for i, case in enumerate( similar_cases, start=1 ):
        question           = case.get( "question", "unknown" )
        decision_value     = case.get( "decision_value", "unknown" )
        ratification_state = case.get( "ratification_state", "unknown" )
        created_at         = case.get( "created_at", "unknown" )

        lines.append(
            f"{i}. [{decision_value}] (ratification: {ratification_state}, "
            f"date: {created_at})\n   Question: {question}"
        )

    return "\n".join( lines )


def build_icrl_prompt( question, category, similar_cases ):
    """
    Assemble the complete ICRL prompt from question, category, and case history.

    Requires:
        - question is a non-empty string
        - category is a non-empty string
        - similar_cases is a list of case dicts

    Ensures:
        - Returns a complete prompt string ready for LLM submission
        - History section is formatted via format_case_history()

    Args:
        question: The decision question to disambiguate
        category: The classified decision category
        similar_cases: List of similar case dicts from CBRPrediction

    Returns:
        Complete prompt string
    """
    history = format_case_history( similar_cases )

    return ICRL_DECISION_PROMPT.format(
        question = question,
        category = category,
        history  = history,
    )
