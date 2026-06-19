"""
Prompt templates for the Bug Fix Expediter proposal phase.

Contains the system prompt for the proposal Lead agent
and the user prompt builder for fix proposal generation.
"""

import json
from typing import Optional


PROPOSAL_SYSTEM_PROMPT = """You are a senior software engineer proposing fixes for a diagnosed software failure.

You have READ-ONLY access to the codebase via Read, Glob, Grep, and Bash (for git log/blame only).
You MUST NOT modify any files. Your job is to propose 1-3 concrete fix options.

PROPOSAL STRATEGY:
1. Review the diagnosis (root cause, error category, affected components)
2. Read the affected files to understand the current code
3. Consider fix complexity: Is it a config tweak, code patch, dependency fix, or manual intervention?
4. For each proposed fix, list specific files and changes needed
5. Assess risk level and effort for each proposal
6. Rank proposals by confidence (best fix first)

OUTPUT FORMAT: End your response with a JSON array of fix proposals:
[
    {
        "title": "<short title>",
        "description": "<detailed description of what to change and why>",
        "fix_type": "<config_change|code_patch|retry|manual>",
        "confidence": <0.0-1.0>,
        "risk_level": "<low|medium|high>",
        "estimated_effort": "<minimal|small|medium|large>",
        "changes": [
            {"file": "<path>", "action": "<modify|create|delete>", "description": "<what to change>"}
        ]
    }
]"""


def build_proposal_prompt(
    diagnosis,
    dead_job_context,
    extra_context: str = "",
    user_feedback: Optional[ str ] = None
) -> str:
    """
    Build the proposal prompt for the Lead agent.

    Requires:
        - diagnosis is a DiagnosisResult with populated fields
        - dead_job_context is a DeadJobContext with failure forensics

    Ensures:
        - Prompt contains diagnosis summary + dead job context
        - User feedback incorporated when provided (retry after rejection)

    Args:
        diagnosis: DiagnosisResult from the diagnosis phase
        dead_job_context: DeadJobContext with original failure info
        extra_context: Optional user-provided context
        user_feedback: Optional feedback from a rejected proposal (for retry)

    Returns:
        str: Complete proposal prompt for the Lead agent
    """
    ctx  = dead_job_context
    diag = diagnosis

    evidence_lines    = "\n".join( f"  - {e}" for e in diag.evidence ) if diag.evidence else "  - None"
    components_lines  = "\n".join( f"  - {c}" for c in diag.affected_components ) if diag.affected_components else "  - None identified"

    parts = [
        f"""Propose fixes for the following diagnosed failure.

## Diagnosis Summary

**Root Cause**: {diag.root_cause}
**Category**: {diag.error_category}
**Confidence**: {diag.confidence:.0%}
**Transient**: {"Yes" if diag.is_transient else "No"}

**Evidence**:
{evidence_lines}

**Affected Components**:
{components_lines}

## Original Failure Context

**Job Type**: {ctx.job_type}
**Job ID**: {ctx.id_hash}
**Status**: {ctx.status}
**Duration**: {ctx.duration_seconds or 'N/A'}s

**Error**:
{ctx.error or 'No error message available'}

**Stack Trace**:
{ctx.stack_trace or 'No stack trace available'}

**Original Question**:
{ctx.question_text}"""
    ]

    if extra_context:
        parts.append( f"\n**Additional Context**: {extra_context}" )

    if user_feedback:
        parts.append( f"\n## User Feedback on Previous Proposal\n\nThe user rejected the previous proposal and said:\n> {user_feedback}\n\nPlease revise your proposals to address this feedback." )

    parts.append( "\nInvestigate the affected files using your tools, then propose 1-3 concrete fixes as a JSON array." )

    return "\n".join( parts )


def quick_smoke_test():
    """Quick smoke test for proposal prompt templates."""
    import cosa.utils.util as cu
    from cosa.agents.bug_fix_expediter.state import DeadJobContext, DiagnosisResult

    cu.print_banner( "BFE Proposal Prompts Smoke Test", prepend_nl=True )

    try:
        # 1: System prompt exists and is non-empty
        assert len( PROPOSAL_SYSTEM_PROMPT ) > 100
        assert "proposing fixes" in PROPOSAL_SYSTEM_PROMPT
        assert "JSON array" in PROPOSAL_SYSTEM_PROMPT
        print( "✓ PROPOSAL_SYSTEM_PROMPT is valid" )

        # 2: Build prompt with full context
        ctx = DeadJobContext(
            id_hash="dr-test1234::user1", job_type="deep_research",
            user_id="user1", user_email="t@t.com", session_id="s1",
            status="failed", question_text="What is quantum computing?",
            error="KeyError: 'missing_key'",
            stack_trace="Traceback:\n  File \"cli.py\", line 42",
        )
        diag = DiagnosisResult(
            root_cause="Missing config key 'missing_key' in lupin-app.ini",
            error_category="config",
            confidence=0.85,
            evidence=[ "KeyError at cli.py:42" ],
            affected_components=[ "src/conf/lupin-app.ini" ],
        )

        prompt = build_proposal_prompt( diag, ctx, extra_context="Worked yesterday" )
        assert "Missing config key" in prompt
        assert "config" in prompt
        assert "85%" in prompt
        assert "KeyError" in prompt
        assert "Worked yesterday" in prompt
        print( "✓ Proposal prompt includes all context" )

        # 3: Prompt with user feedback
        prompt = build_proposal_prompt( diag, ctx, user_feedback="Try a different approach" )
        assert "Try a different approach" in prompt
        assert "rejected" in prompt.lower()
        print( "✓ User feedback incorporated" )

        # 4: Prompt with minimal context
        diag_min = DiagnosisResult(
            root_cause="Unknown failure", error_category="unknown", confidence=0.3
        )
        ctx_min = DeadJobContext(
            id_hash="bfe-min::u1", job_type="math_agent",
            user_id="u1", user_email="u@u.com", session_id="s1",
            status="interrupted", question_text="2+2"
        )
        prompt = build_proposal_prompt( diag_min, ctx_min )
        assert "Unknown failure" in prompt
        assert "No error message available" in prompt
        print( "✓ Minimal context handled gracefully" )

        print( "\n✓ BFE Proposal Prompts smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
