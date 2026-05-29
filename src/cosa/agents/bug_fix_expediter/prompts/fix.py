"""
Prompt templates for the Bug Fix Expediter fix phase.

Contains system prompts for Coder and Tester agents, plus prompt
builders for fix application, verification, and redelegation.
"""

from typing import Optional


CODER_SYSTEM_PROMPT = """You are a senior software engineer applying a targeted bug fix.

You have full edit access via Read, Edit, and Bash tools.
Apply ONLY the changes described in the fix proposal — no extra refactoring.

RULES:
1. Read affected files before editing
2. Make minimal, focused changes
3. Do NOT modify test files
4. Do NOT run destructive commands (rm -rf, git push, git reset, etc.)
5. After making changes, summarize what you did and list all files modified
6. Verify your changes compile: python -c "import py_compile; py_compile.compile('file.py', doraise=True)"
"""


TESTER_SYSTEM_PROMPT = """You are a senior test engineer validating a bug fix.

You have edit access to write tests and Bash access to run them.
Your job: write targeted tests for the fix, run them, and report PASS or FAIL.

RULES:
1. Read the changed files to understand what was fixed
2. Write tests in src/tests/unit/ following existing patterns
3. Run tests with: python -m pytest <test_file> -v --tb=short
4. Report a clear PASS or FAIL verdict at the end of your output
5. If FAIL, explain exactly what failed and why
"""


def build_fix_prompt( selected_fix, diagnosis, dead_job_context ) -> str:
    """
    Build the fix prompt for the Coder agent.

    Requires:
        - selected_fix is a ProposedFix with populated fields
        - diagnosis is a DiagnosisResult
        - dead_job_context is a DeadJobContext

    Ensures:
        - Prompt contains fix proposal details + diagnosis context
        - Instructions to apply ONLY the proposed changes

    Args:
        selected_fix: The user-approved ProposedFix
        diagnosis: DiagnosisResult from the diagnosis phase
        dead_job_context: Original failure context

    Returns:
        str: Complete fix prompt for the Coder agent
    """
    fix  = selected_fix
    diag = diagnosis
    ctx  = dead_job_context

    # Build changes table
    changes_text = "None specified"
    if fix.changes:
        lines = [ "| File | Action | Description |", "|------|--------|-------------|" ]
        for change in fix.changes:
            lines.append(
                f"| {change.get( 'file', '?' )} | {change.get( 'action', '?' )} | {change.get( 'description', '?' )} |"
            )
        changes_text = "\n".join( lines )

    return f"""Apply the following bug fix.

## Fix Proposal

**Title**: {fix.title}
**Type**: {fix.fix_type}
**Risk**: {fix.risk_level}
**Effort**: {fix.estimated_effort}

**Description**:
{fix.description}

**Changes to Apply**:
{changes_text}

## Diagnosis Context

**Root Cause**: {diag.root_cause}
**Category**: {diag.error_category}
**Affected Components**: {', '.join( diag.affected_components ) if diag.affected_components else 'None identified'}

## Original Failure

**Job Type**: {ctx.job_type}
**Error**: {ctx.error or 'N/A'}
**Stack Trace**:
{ctx.stack_trace or 'N/A'}

## Instructions

Apply ONLY the changes described above. Do not refactor surrounding code.
After making changes, summarize what you did and list all files modified."""


def build_verification_prompt( selected_fix, coder_output, files_changed ) -> str:
    """
    Build the verification prompt for the Tester agent.

    Args:
        selected_fix: The ProposedFix that was applied
        coder_output: Coder's summary of changes made
        files_changed: List of file paths modified by the coder

    Returns:
        str: Complete verification prompt for the Tester agent
    """
    files_text = "\n".join( f"- {f}" for f in files_changed ) if files_changed else "- None reported"

    return f"""Verify the following bug fix implementation.

## Original Fix Proposal

**Title**: {selected_fix.title}
**Type**: {selected_fix.fix_type}
**Description**: {selected_fix.description}

## Coder's Changes

**Summary**:
{coder_output[ :1500 ]}

**Files Changed**:
{files_text}

## Instructions

1. Read the changed files to understand what was fixed
2. Write appropriate unit tests in src/tests/unit/
3. Run the tests with: python -m pytest <test_file> -v --tb=short
4. Report a clear PASS or FAIL verdict at the end

Focus on testing the ACTUAL changes made. Follow existing test patterns in the project."""


def build_redelegation_prompt( selected_fix, coder_output, test_feedback, iteration ) -> str:
    """
    Build the redelegation prompt for the Coder after test failure.

    Args:
        selected_fix: The ProposedFix being applied
        coder_output: Coder's prior output summary
        test_feedback: Tester's failure output
        iteration: Current iteration number (2-based)

    Returns:
        str: Redelegation prompt for the Coder agent
    """
    return f"""Fix your implementation (iteration {iteration}).

## Original Fix Proposal

**Title**: {selected_fix.title}
**Description**: {selected_fix.description}

## Your Prior Changes

{coder_output[ :1000 ]}

## Test Failure Feedback

{test_feedback[ :1500 ]}

## Instructions

1. Read the test failure feedback carefully
2. Fix your implementation to address the failures
3. Do NOT modify test files — fix your implementation code only
4. Verify changes compile
5. Summarize what you changed and list all files modified"""


def quick_smoke_test():
    """Quick smoke test for fix prompt templates."""
    import cosa.utils.util as cu
    from cosa.agents.bug_fix_expediter.state import DeadJobContext, DiagnosisResult, ProposedFix

    cu.print_banner( "BFE Fix Prompts Smoke Test", prepend_nl=True )

    try:
        # 1: System prompts exist
        assert len( CODER_SYSTEM_PROMPT ) > 50
        assert len( TESTER_SYSTEM_PROMPT ) > 50
        assert "targeted bug fix" in CODER_SYSTEM_PROMPT
        assert "validating a bug fix" in TESTER_SYSTEM_PROMPT
        print( "✓ System prompts valid" )

        # 2: Fix prompt
        fix = ProposedFix(
            title="Add missing key", description="Add key to INI",
            fix_type="config_change", confidence=0.9,
            changes=[ { "file": "lupin-app.ini", "action": "modify", "description": "Add key" } ],
        )
        diag = DiagnosisResult(
            root_cause="Missing config key", error_category="config", confidence=0.85,
            affected_components=[ "src/conf/lupin-app.ini" ],
        )
        ctx = DeadJobContext(
            id_hash="dr-test::u1", job_type="deep_research",
            user_id="u1", user_email="t@t.com", session_id="s1",
            status="failed", question_text="test",
            error="KeyError: 'missing_key'",
        )

        prompt = build_fix_prompt( fix, diag, ctx )
        assert "Add missing key" in prompt
        assert "config_change" in prompt
        assert "lupin-app.ini" in prompt
        assert "KeyError" in prompt
        print( "✓ Fix prompt includes all context" )

        # 3: Verification prompt
        prompt = build_verification_prompt( fix, "Added key to INI", [ "lupin-app.ini" ] )
        assert "Added key to INI" in prompt
        assert "lupin-app.ini" in prompt
        assert "PASS or FAIL" in prompt
        print( "✓ Verification prompt valid" )

        # 4: Redelegation prompt
        prompt = build_redelegation_prompt( fix, "Prior changes", "Tests failed: KeyError", 2 )
        assert "iteration 2" in prompt
        assert "Prior changes" in prompt
        assert "Tests failed" in prompt
        assert "Do NOT modify test files" in prompt
        print( "✓ Redelegation prompt valid" )

        print( "\n✓ BFE Fix Prompts smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()


# ─────────────────────────────────────────────────────────────────────────
# Register BFE prompt bundle into the shared FixExecutor prompt registry.
# Session 1cfcdf73 (2026-04-10): Extract FixExecutor to shared/ for BFE+TFE
# reuse. BFE's prompts self-register under key "bfe" at import time.
# ─────────────────────────────────────────────────────────────────────────
from cosa.agents.shared.fix_executor import register_fix_prompts

register_fix_prompts(
    "bfe",
    build_fix_prompt        = build_fix_prompt,
    build_verify_prompt     = build_verification_prompt,
    build_redelegate_prompt = build_redelegation_prompt,
    coder_system_prompt     = CODER_SYSTEM_PROMPT,
    tester_system_prompt    = TESTER_SYSTEM_PROMPT,
)
