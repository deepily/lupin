#!/usr/bin/env python3
"""
Unit tests for ICRL prompt template and formatting functions.

Tests format_case_history(), build_icrl_prompt(), and edge cases
for missing fields and empty inputs.
"""

import pytest

from cosa.agents.decision_proxy.prompts.icrl_decision import (
    format_case_history,
    build_icrl_prompt,
    ICRL_DECISION_PROMPT,
)


class TestFormatCaseHistory:
    """Tests for format_case_history()."""

    def test_format_empty_cases( self ):
        """No cases → default message."""
        result = format_case_history( [] )
        assert result == "(No similar past decisions found)"

    def test_format_single_case( self ):
        """One case formatted with all fields."""
        cases = [ {
            "question"           : "Should we deploy to production?",
            "decision_value"     : "approved",
            "ratification_state" : "ratified",
            "created_at"         : "2026-02-20T10:00:00",
        } ]

        result = format_case_history( cases )

        assert "1." in result
        assert "[approved]" in result
        assert "ratification: ratified" in result
        assert "2026-02-20T10:00:00" in result
        assert "Should we deploy to production?" in result

    def test_format_multiple_cases( self ):
        """Multiple cases numbered 1-N."""
        cases = [
            { "question": "Deploy v1?", "decision_value": "approved",         "ratification_state": "ratified", "created_at": "2026-02-20" },
            { "question": "Deploy v2?", "decision_value": "requires_review",  "ratification_state": "pending",  "created_at": "2026-02-21" },
            { "question": "Deploy v3?", "decision_value": "approved",         "ratification_state": "ratified", "created_at": "2026-02-22" },
        ]

        result = format_case_history( cases )

        assert "1." in result
        assert "2." in result
        assert "3." in result
        assert result.count( "[approved]" ) == 2
        assert result.count( "[requires_review]" ) == 1


class TestBuildIcrlPrompt:
    """Tests for build_icrl_prompt()."""

    def test_build_prompt_has_all_sections( self ):
        """Complete prompt contains question, category, and history."""
        cases = [ {
            "question"           : "Run tests?",
            "decision_value"     : "approved",
            "ratification_state" : "ratified",
            "created_at"         : "2026-02-20",
        } ]

        result = build_icrl_prompt( "Should we run integration tests?", "testing", cases )

        assert "Should we run integration tests?" in result
        assert "testing" in result
        assert "[approved]" in result
        assert "Run tests?" in result

    def test_build_prompt_with_real_case_data( self ):
        """Use realistic case dicts matching CBRPrediction.similar_cases schema."""
        cases = [
            {
                "question"           : "Approve deployment of auth service to staging?",
                "decision_value"     : "approved",
                "ratification_state" : "ratified",
                "created_at"         : "2026-02-18T14:30:00+00:00",
                "category"           : "deployment",
                "confidence"         : 0.85,
            },
            {
                "question"           : "Allow production database migration?",
                "decision_value"     : "requires_review",
                "ratification_state" : "pending",
                "created_at"         : "2026-02-19T09:15:00+00:00",
                "category"           : "deployment",
                "confidence"         : 0.72,
            },
        ]

        result = build_icrl_prompt(
            "Deploy notification service to production?",
            "deployment",
            cases
        )

        assert "Deploy notification service to production?" in result
        assert "deployment" in result
        assert "1." in result
        assert "2." in result
        assert "[approved]" in result
        assert "[requires_review]" in result

    def test_prompt_handles_missing_fields( self ):
        """Case dict with missing keys doesn't crash — falls back to 'unknown'."""
        cases = [
            { "question": "Partial case" },
            {},
        ]

        result = build_icrl_prompt( "Test question?", "general", cases )

        assert "unknown" in result
        assert "Partial case" in result
        assert "Test question?" in result
