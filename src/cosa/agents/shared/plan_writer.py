"""
Structured markdown plan document writer (agent-agnostic).

Originally extracted from cosa.agents.bug_fix_expediter.plan_writer into this
shared module so both BugFixExpediter and TestFixExpediter (and future repair
agents) can reuse the same plan-doc machinery.

This module has zero back-dependencies on any specific agent package. The
`write_plan()` method accepts any object with the attributes it reads
(duck-typed), so a BFE DeadJobContext and a TFE TestRemediationContext can
both be passed in without changes here.
"""

import os
import re
from datetime import datetime
from typing import Optional

import cosa.utils.util as cu


class PlanWriter:
    """
    Writes structured markdown plan documents to disk.

    Requires:
        - user_email is a non-empty string
        - project root is accessible via cu.get_project_root()

    Ensures:
        - Plan directory created if not exists
        - Plan file written with structured markdown
        - Returns absolute path to written file
    """

    PLANS_DIR = "io/swe-team/plans"

    def __init__( self, user_email: str, debug: bool = False ):
        """
        Initialize the PlanWriter.

        Args:
            user_email: User email for plan directory partitioning
            debug: Enable debug output
        """
        self.user_email = user_email
        self.debug      = debug

    def write_plan(
        self,
        dead_job_context,
        diagnosis,
        proposed_fixes: list,
        selected_fix = None,
    ) -> str:
        """
        Write a plan document to disk.

        Requires:
            - dead_job_context has .id_hash, .job_type, .error, .stack_trace attributes
            - diagnosis has .root_cause, .error_category, .confidence, .evidence, .affected_components attributes
            - proposed_fixes is a non-empty list of objects with .title, .description,
              .fix_type, .confidence, .risk_level, .estimated_effort, .changes attributes

        Ensures:
            - Plan file written to {project_root}/io/swe-team/plans/{email}/YYYY.MM.DD-{slug}-plan.md
            - Directory created if needed

        Args:
            dead_job_context: Forensic context (BFE dead job OR TFE test remediation)
            diagnosis: Root cause analysis result
            proposed_fixes: List of proposed fixes
            selected_fix: The user-selected fix (optional)

        Returns:
            str: Absolute path to the written plan file
        """
        slug      = self._generate_slug( diagnosis.root_cause )
        plan_path = self._get_plan_path( slug )

        # Ensure directory exists
        plan_dir = os.path.dirname( plan_path )
        os.makedirs( plan_dir, exist_ok=True )

        # Build document sections
        header    = self._render_header( dead_job_context, diagnosis, slug )
        diag_sect = self._render_diagnosis_section( dead_job_context, diagnosis )
        fix_sect  = self._render_fixes_section( proposed_fixes, selected_fix )
        footer    = self._render_footer()

        content = f"{header}\n{diag_sect}\n{fix_sect}\n{footer}"

        with open( plan_path, "w" ) as f:
            f.write( content )

        if self.debug: print( f"[PlanWriter] Plan written: {plan_path}" )

        return plan_path

    def _get_plan_path( self, slug: str ) -> str:
        """
        Generate the plan file path.

        Args:
            slug: URL-safe slug from root cause

        Returns:
            str: Absolute path for the plan file
        """
        date_str  = datetime.now().strftime( "%Y.%m.%d" )
        filename  = f"{date_str}-{slug}-plan.md"
        return os.path.join(
            cu.get_project_root(),
            self.PLANS_DIR,
            self.user_email,
            filename,
        )

    @staticmethod
    def _generate_slug( root_cause: str ) -> str:
        """
        Generate a URL-safe slug from the root cause description.

        Requires:
            - root_cause is a non-empty string

        Ensures:
            - Lowercase, alphanumeric + hyphens only
            - Max 5 words (truncated)
            - No leading/trailing hyphens

        Args:
            root_cause: Root cause description

        Returns:
            str: Slug for use in filename
        """
        # Lowercase, replace non-alphanumeric with spaces
        cleaned = re.sub( r"[^a-z0-9\s]", "", root_cause.lower() )
        # Split into words, take first 5
        words = cleaned.split()[ :5 ]
        slug  = "-".join( words )
        # Remove any double hyphens
        slug = re.sub( r"-+", "-", slug )
        return slug.strip( "-" ) or "unknown-fix"

    @staticmethod
    def _render_header( dead_job_context, diagnosis, slug: str ) -> str:
        """Render the plan document header."""
        ctx  = dead_job_context
        diag = diagnosis
        ts   = datetime.now().strftime( "%Y-%m-%d %H:%M:%S" )

        return f"""# Bug Fix Plan: {slug}

**Dead Job**: {ctx.id_hash} ({ctx.job_type})
**Diagnosed**: {ts}
**Root Cause**: {diag.root_cause}
**Category**: {diag.error_category}
**Confidence**: {diag.confidence:.0%}

---
"""

    @staticmethod
    def _render_diagnosis_section( dead_job_context, diagnosis ) -> str:
        """Render the diagnosis section of the plan."""
        ctx  = dead_job_context
        diag = diagnosis

        evidence = "\n".join( f"- {e}" for e in diag.evidence ) if diag.evidence else "- None"
        components = "\n".join( f"- {c}" for c in diag.affected_components ) if diag.affected_components else "- None identified"

        stack_trace = ctx.stack_trace or "No stack trace available"

        return f"""## Diagnosis

**Error**: {ctx.error or 'No error message'}

**Stack Trace**:
```
{stack_trace}
```

**Evidence**:
{evidence}

**Affected Components**:
{components}

---
"""

    @staticmethod
    def _render_fixes_section( proposed_fixes: list, selected_fix = None ) -> str:
        """Render the proposed fixes section."""
        lines = [ "## Proposed Fixes\n" ]

        for i, fix in enumerate( proposed_fixes, 1 ):
            selected_tag = " [SELECTED]" if selected_fix and fix.title == selected_fix.title else ""
            lines.append( f"### Fix {i}: {fix.title}{selected_tag}" )
            lines.append( f"- **Type**: {fix.fix_type}" )
            lines.append( f"- **Confidence**: {fix.confidence:.0%}" )
            lines.append( f"- **Risk**: {fix.risk_level}" )
            lines.append( f"- **Effort**: {fix.estimated_effort}" )
            lines.append( "" )
            lines.append( fix.description )
            lines.append( "" )

            if fix.changes:
                lines.append( "**Changes**:" )
                lines.append( "| File | Action | Description |" )
                lines.append( "|------|--------|-------------|" )
                for change in fix.changes:
                    file_path   = change.get( "file", "?" )
                    action      = change.get( "action", "?" )
                    description = change.get( "description", "?" )
                    lines.append( f"| {file_path} | {action} | {description} |" )
                lines.append( "" )

        lines.append( "---\n" )
        return "\n".join( lines )

    def update_implementation_log(
        self,
        plan_path: str,
        fix_result,
        files_changed: list,
        coder_output: str = "",
    ) -> None:
        """
        Update an existing plan document's Implementation Log section.

        Reads the plan file and replaces the placeholder with actual results.

        Requires:
            - plan_path exists and is writable
            - fix_result has .applied, .success, .details, .retry_eligible attributes

        Ensures:
            - Placeholder text replaced with structured implementation results

        Args:
            plan_path: Path to existing plan file
            fix_result: FixResult from the fix phase
            files_changed: List of files modified by coder
            coder_output: Coder's summary text
        """
        if not os.path.exists( plan_path ):
            if self.debug: print( f"[PlanWriter] Plan file not found: {plan_path}" )
            return

        content = open( plan_path ).read()

        status  = "Applied" if fix_result.applied else "Failed"
        outcome = "Success" if fix_result.success else "Failure"
        files_text = "\n".join( f"- {f}" for f in files_changed ) if files_changed else "- None"
        summary = coder_output[ :1000 ] if coder_output else "No summary available"

        log_content = f"""**Status**: {status} — {outcome}

**Files Changed**:
{files_text}

**Coder Summary**:
{summary}

**Details**: {fix_result.details or 'N/A'}

**Retry Eligible**: {'Yes' if fix_result.retry_eligible else 'No'}"""

        placeholder = "(Phase 4 — populated after fix is applied)"
        if placeholder in content:
            content = content.replace( placeholder, log_content )
            with open( plan_path, "w" ) as f:
                f.write( content )
            if self.debug: print( f"[PlanWriter] Implementation log updated: {plan_path}" )
        else:
            if self.debug: print( f"[PlanWriter] Placeholder not found in {plan_path}" )

    def update_git_references(
        self,
        plan_path: str,
        fix_result,
    ) -> None:
        """
        Update an existing plan document's Git References section (Phase 5).

        Reads the plan file and replaces the placeholder with git strategy results.
        Silently no-ops if plan file missing or placeholder already replaced.

        Requires:
            - plan_path is a string path
            - fix_result has git_strategy, commit_hash, branch_name, pr_url attrs

        Ensures:
            - Placeholder text replaced with structured git references
            - No-op (with debug log) if placeholder not found

        Args:
            plan_path: Path to existing plan file
            fix_result: FixResult with Phase 5 git fields populated
        """
        if not os.path.exists( plan_path ):
            if self.debug: print( f"[PlanWriter] Plan file not found: {plan_path}" )
            return

        content = open( plan_path ).read()

        git_content = f"""**Strategy**: {fix_result.git_strategy or 'N/A'}
**Commit**: {fix_result.commit_hash or 'N/A'}
**Branch**: {fix_result.branch_name or 'N/A'}
**PR**: {fix_result.pr_url or 'N/A'}"""

        placeholder = "(Phase 5 — populated after git operations)"
        if placeholder in content:
            content = content.replace( placeholder, git_content )
            with open( plan_path, "w" ) as f:
                f.write( content )
            if self.debug: print( f"[PlanWriter] Git references updated: {plan_path}" )
        else:
            if self.debug: print( f"[PlanWriter] Git placeholder not found in {plan_path}" )

    @staticmethod
    def _render_footer() -> str:
        """Render the plan document footer with placeholder sections."""
        return """## Implementation Log
(Phase 4 — populated after fix is applied)

---

## Git References
(Phase 5 — populated after git operations)

---

## Retry Result
(Phase 6 — populated after retry)
"""


def quick_smoke_test():
    """
    Quick smoke test for shared PlanWriter.

    Uses SimpleNamespace mocks instead of BFE/TFE-specific types so this
    module has zero back-dependencies on any agent package.
    """
    import tempfile
    from types import SimpleNamespace
    import cosa.utils.util as cu

    cu.print_banner( "Shared PlanWriter Smoke Test", prepend_nl=True )

    try:
        # 1: Slug generation
        assert PlanWriter._generate_slug( "Missing config key 'foo' in lupin-app.ini" ) == "missing-config-key-foo-in"
        assert PlanWriter._generate_slug( "!!!weird---chars!!!" ) == "weirdchars"
        assert PlanWriter._generate_slug( "a b c d e f g h" ) == "a-b-c-d-e"
        assert PlanWriter._generate_slug( "" ) == "unknown-fix"
        print( "✓ Slug generation works" )

        # 2: Write plan to tempdir using SimpleNamespace mocks
        with tempfile.TemporaryDirectory() as tmpdir:
            # Monkey-patch project root for test
            original_root = cu.get_project_root
            cu.get_project_root = lambda: tmpdir

            try:
                writer = PlanWriter( user_email="test@test.com", debug=True )

                ctx = SimpleNamespace(
                    id_hash     = "test-job-123",
                    job_type    = "test_type",
                    error       = "KeyError: 'missing_key'",
                    stack_trace = "Traceback:\n  File cli.py, line 42",
                )
                diag = SimpleNamespace(
                    root_cause          = "Missing config key in INI",
                    error_category      = "config",
                    confidence          = 0.85,
                    evidence            = [ "KeyError at line 42" ],
                    affected_components = [ "src/conf/lupin-app.ini" ],
                )
                fixes = [
                    SimpleNamespace(
                        title            = "Add missing key",
                        description      = "Add 'missing_key' to INI file",
                        fix_type         = "config_change",
                        confidence       = 0.9,
                        risk_level       = "low",
                        estimated_effort = "minutes",
                        changes          = [ { "file": "lupin-app.ini", "action": "modify", "description": "Add key" } ],
                    ),
                    SimpleNamespace(
                        title            = "Add fallback default",
                        description      = "Add getattr fallback in code",
                        fix_type         = "code_patch",
                        confidence       = 0.6,
                        risk_level       = "medium",
                        estimated_effort = "hours",
                        changes          = [],
                    ),
                ]

                plan_path = writer.write_plan( ctx, diag, fixes, selected_fix=fixes[ 0 ] )

                assert os.path.exists( plan_path )
                print( f"✓ Plan file created: {plan_path}" )

                content = open( plan_path ).read()
                assert "Missing config key" in content
                assert "[SELECTED]" in content
                assert "Add missing key" in content
                assert "Add fallback default" in content
                assert "Implementation Log" in content
                assert "Retry Result" in content
                print( "✓ Plan content is correct" )

                # 3: Update implementation log
                fix_result = SimpleNamespace(
                    applied         = True,
                    success         = True,
                    details         = "Added the missing key",
                    retry_eligible  = False,
                )
                writer.update_implementation_log(
                    plan_path, fix_result, [ "lupin-app.ini" ], "Coder applied the fix"
                )
                content = open( plan_path ).read()
                assert "Status**: Applied — Success" in content
                print( "✓ Implementation log update works" )

                # 4: Update git references
                git_result = SimpleNamespace(
                    git_strategy = "commit_only",
                    commit_hash  = "abc1234",
                    branch_name  = "main",
                    pr_url       = None,
                )
                writer.update_git_references( plan_path, git_result )
                content = open( plan_path ).read()
                assert "abc1234" in content
                print( "✓ Git references update works" )

            finally:
                cu.get_project_root = original_root

        print( "\n✓ Shared PlanWriter smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
