"""
Prompt templates for the Bug Fix Expediter diagnosis phase.

Contains the system prompt for the forensic analyst Lead agent
and the user prompt builder for dead job context analysis.
"""

import json
from typing import Optional


DIAGNOSIS_SYSTEM_PROMPT = """You are a senior software forensic analyst. Your job is to diagnose why a background job failed.

You have READ-ONLY access to the codebase via Read, Glob, Grep, and Bash (for git log/blame only).
You MUST NOT modify any files. Your only output is a structured diagnosis.

INVESTIGATION STRATEGY:
1. Read the error message and stack trace carefully
2. Use Grep to find the failing code path in the codebase
3. Use Read to examine the relevant source files
4. Use Bash for `git log` or `git blame` if you need recent change context
5. Classify the root cause into one of: config, code_bug, dependency, timeout, resource, unknown
6. Assess whether the failure is transient (would succeed on retry) or persistent

OUTPUT FORMAT: You MUST end your response with a JSON block containing your diagnosis:
{
    "root_cause": "<clear description of what caused the failure>",
    "error_category": "<config|code_bug|dependency|timeout|resource|unknown>",
    "confidence": <0.0-1.0>,
    "evidence": ["<evidence item 1>", "<evidence item 2>"],
    "affected_components": ["<file or module 1>", "<file or module 2>"],
    "is_transient": <true|false>
}"""


def build_diagnosis_prompt(
    ctx,
    extra_context: str = "",
    iteration: int = 1,
    prior_diagnosis = None,
    user_messages: Optional[ list ] = None
) -> str:
    """
    Build the diagnosis prompt for the Lead agent.

    Requires:
        - ctx is a DeadJobContext with required fields populated
        - iteration >= 1
        - prior_diagnosis provided when iteration > 1

    Ensures:
        - Iteration 1: Full forensic context from dead job
        - Iteration 2+: Prior diagnosis + refinement instructions
        - User messages incorporated when provided

    Args:
        ctx: DeadJobContext with failure forensics
        extra_context: Optional user-provided context about the failure
        iteration: Current diagnosis iteration (1-based)
        prior_diagnosis: DiagnosisResult from previous iteration (for refinement)
        user_messages: Optional list of ad hoc user messages to incorporate

    Returns:
        str: Complete diagnosis prompt for the Lead agent
    """
    parts = []

    if iteration == 1:
        parts.append( _build_initial_prompt( ctx, extra_context ) )
    else:
        parts.append( _build_refinement_prompt( prior_diagnosis ) )

    # Append user messages if any were queued during execution
    if user_messages:
        messages_text = "\n".join( f"  - {m}" for m in user_messages )
        parts.append( f"\nADDITIONAL USER INPUT (received during analysis):\n{messages_text}" )

    parts.append( "\nInvestigate the codebase using your tools, then provide your diagnosis as a JSON object." )

    return "\n".join( parts )


def _build_initial_prompt( ctx, extra_context: str ) -> str:
    """
    Build the full forensic context prompt for iteration 1.

    Args:
        ctx: DeadJobContext with failure forensics
        extra_context: Optional user-provided context

    Returns:
        str: Initial diagnosis prompt
    """
    metadata_str = "None"
    if ctx.metadata_json:
        try:
            metadata_str = json.dumps( ctx.metadata_json, indent=2 )
        except ( TypeError, ValueError ):
            metadata_str = str( ctx.metadata_json )

    return f"""Diagnose the following failed job.

JOB TYPE: {ctx.job_type}
JOB ID: {ctx.id_hash}
STATUS: {ctx.status}
DURATION: {ctx.duration_seconds or 'N/A'}s

ERROR MESSAGE:
{ctx.error or 'No error message available'}

STACK TRACE:
{ctx.stack_trace or 'No stack trace available'}

ORIGINAL QUESTION:
{ctx.question_text}

ROUTING COMMAND: {ctx.routing_command or 'N/A'}

METADATA:
{metadata_str}

ADDITIONAL CONTEXT FROM USER:
{extra_context or 'None provided'}

TIMESTAMPS:
  Created:   {ctx.created_at or 'N/A'}
  Started:   {ctx.started_at or 'N/A'}
  Completed: {ctx.completed_at or 'N/A'}"""


def _build_refinement_prompt( prior_diagnosis ) -> str:
    """
    Build a refinement prompt for iteration 2+.

    Args:
        prior_diagnosis: DiagnosisResult from previous iteration

    Returns:
        str: Refinement prompt with prior diagnosis context
    """
    prior_json = json.dumps( prior_diagnosis.model_dump(), indent=2 )

    return f"""Your previous diagnosis had confidence {prior_diagnosis.confidence:.0%}, which is below the required threshold.

PREVIOUS DIAGNOSIS:
{prior_json}

Please investigate more deeply. Use Grep and Read to trace the code path more thoroughly.
Look for additional evidence that either confirms or revises your root cause analysis.
Then provide an updated diagnosis as a JSON object with higher confidence."""


def quick_smoke_test():
    """Quick smoke test for diagnosis prompt templates."""
    import cosa.utils.util as cu
    from cosa.agents.bug_fix_expediter.state import DeadJobContext, DiagnosisResult

    cu.print_banner( "BFE Diagnosis Prompts Smoke Test", prepend_nl=True )

    try:
        # 1: System prompt exists and is non-empty
        assert len( DIAGNOSIS_SYSTEM_PROMPT ) > 100
        assert "forensic analyst" in DIAGNOSIS_SYSTEM_PROMPT
        print( "✓ DIAGNOSIS_SYSTEM_PROMPT is valid" )

        # 2: Initial prompt with full context
        ctx = DeadJobContext(
            id_hash="dr-test1234::user1", job_type="deep_research",
            user_id="user1", user_email="t@t.com", session_id="s1",
            status="failed", question_text="What is quantum computing?",
            error="KeyError: 'missing_key'",
            stack_trace="Traceback (most recent call last):\n  File \"cli.py\", line 42",
            metadata_json={ "model": "opus" }
        )
        prompt = build_diagnosis_prompt( ctx, extra_context="User says it worked yesterday" )
        assert "deep_research" in prompt
        assert "KeyError" in prompt
        assert "quantum computing" in prompt
        assert "worked yesterday" in prompt
        assert "opus" in prompt
        print( "✓ Initial prompt includes all context fields" )

        # 3: Prompt with None fields
        ctx_minimal = DeadJobContext(
            id_hash="bfe-min::u1", job_type="math_agent",
            user_id="u1", user_email="u@u.com", session_id="s1",
            status="interrupted", question_text="2+2"
        )
        prompt = build_diagnosis_prompt( ctx_minimal )
        assert "No error message available" in prompt
        assert "No stack trace available" in prompt
        assert "None provided" in prompt
        print( "✓ None fields handled gracefully" )

        # 4: Refinement prompt
        diag = DiagnosisResult(
            root_cause="Missing config key", error_category="config", confidence=0.4
        )
        prompt = build_diagnosis_prompt( ctx, iteration=2, prior_diagnosis=diag )
        assert "40%" in prompt
        assert "Missing config key" in prompt
        assert "investigate more deeply" in prompt.lower()
        print( "✓ Refinement prompt includes prior diagnosis" )

        # 5: User messages
        prompt = build_diagnosis_prompt(
            ctx, user_messages=[ "Check the config file", "It might be a typo" ]
        )
        assert "Check the config file" in prompt
        assert "ADDITIONAL USER INPUT" in prompt
        print( "✓ User messages incorporated" )

        print( "\n✓ BFE Diagnosis Prompts smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
