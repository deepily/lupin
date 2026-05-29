"""
Structured markdown final-report writer (agent-agnostic).

Complements `plan_writer.py`: PlanWriter captures pre-run intent and in-flight
state via placeholder sections; ReportWriter captures the comprehensive
post-run outcome as a single self-contained document.

Used by Bug Fix Expediter and Test Fix Expediter to produce the "View Full
Report" artifact surfaced on completed job cards. Populating
`self.artifacts["report_path"]` with this file's output path causes the UI's
`renderReportLinkSection()` (notifications.js) to render a "📋 View Full
Report" link that opens the report in /app/docs.

Zero back-dependencies on any specific agent package — `write()` accepts
plain strings + a slug, so any caller can use it.
"""

import os
import re
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

import cosa.utils.util as cu


class ReportWriter:
    """
    Writes final-report markdown files to disk.

    Path convention:
        {project_root}/io/swe-team/reports/{email}/YYYY.MM.DD-at-HH:MM-EST-{slug}-{agent}-report.md

    The `EST` token in the filename is fixed — it reflects the user's dated-
    filename convention. Times use America/New_York (handles EST/EDT automatically).
    """

    REPORTS_DIR = "io/swe-team/reports"
    TZ          = ZoneInfo( "America/New_York" )

    def __init__( self, user_email: str, debug: bool = False ):
        """
        Initialize the ReportWriter.

        Args:
            user_email: User email for report directory partitioning
            debug: Enable debug output
        """
        self.user_email = user_email
        self.debug      = debug

    def write( self, agent: str, slug: str, title: str, body_md: str ) -> str:
        """
        Write a final report to disk.

        Requires:
            - agent is a non-empty string (e.g., "bug_fix_expediter")
            - slug is a short kebab-case identifier
            - title is a non-empty human-readable title
            - body_md is a string (may be empty; will be padded with a note)

        Ensures:
            - Report directory created if not exists
            - Report file written with h1 title + timestamp header + body
            - Returns absolute path to the written file

        Args:
            agent: Agent key (used in filename suffix)
            slug: Short kebab-case subject slug
            title: H1 title rendered at top of report
            body_md: Markdown body rendered below the header

        Returns:
            str: Absolute path to the written report
        """
        report_path = self._get_report_path( agent, slug )
        report_dir  = os.path.dirname( report_path )
        os.makedirs( report_dir, exist_ok=True )

        ts_iso   = datetime.now( tz=self.TZ ).isoformat( timespec="seconds" )
        body_md  = body_md or "_(report body was empty — agent produced no structured output)_"
        content  = f"# {title}\n\n**Generated**: {ts_iso}\n**Agent**: `{agent}`\n\n---\n\n{body_md}\n"

        with open( report_path, "w" ) as f:
            f.write( content )

        if self.debug: print( f"[ReportWriter] Report written: {report_path}" )

        return report_path

    def _get_report_path( self, agent: str, slug: str ) -> str:
        """
        Generate the report file path following the project's dated-filename convention.

        Filename: YYYY.MM.DD-at-HH:MM-EST-{slug}-{agent}-report.md

        The `EST` token is fixed per the project's filename convention; the actual
        timestamp uses America/New_York (handles EST/EDT automatically).
        """
        now_et    = datetime.now( tz=self.TZ )
        date_str  = now_et.strftime( "%Y.%m.%d" )
        time_str  = now_et.strftime( "%H:%M" )
        safe_slug = self._sanitize_slug( slug )
        filename  = f"{date_str}-at-{time_str}-EST-{safe_slug}-{agent}-report.md"
        return os.path.join(
            cu.get_project_root(),
            self.REPORTS_DIR,
            self.user_email,
            filename,
        )

    @staticmethod
    def _sanitize_slug( slug: str ) -> str:
        """
        Coerce a slug candidate to [a-z0-9-]+, max 6 words, non-empty fallback.
        Underscores are normalized to hyphens so status tokens like
        `dead_job_not_found_dry_run` become `dead-job-not-found-dry-run`
        rather than collapsing to `deadjobnotfounddryrun`.
        """
        normalized = (slug or "").lower().replace( "_", "-" )
        cleaned    = re.sub( r"[^a-z0-9\s-]", "", normalized )
        words      = cleaned.split()[ :6 ]
        result     = "-".join( words ) if words else "unknown"
        result     = re.sub( r"-+", "-", result )
        return result.strip( "-" ) or "unknown"


def quick_smoke_test():
    """Quick smoke test for shared ReportWriter."""
    import tempfile
    import cosa.utils.util as cu

    cu.print_banner( "Shared ReportWriter Smoke Test", prepend_nl=True )

    try:
        # 1: Slug sanitizer
        assert ReportWriter._sanitize_slug( "BFE Final Report for Dead Job" ) == "bfe-final-report-for-dead-job"
        assert ReportWriter._sanitize_slug( "!!!weird---chars!!!" ) == "weird-chars"
        assert ReportWriter._sanitize_slug( "" ) == "unknown"
        assert ReportWriter._sanitize_slug( "a b c d e f g h i" ) == "a-b-c-d-e-f"
        print( "✓ Slug sanitizer works" )

        # 2: Write a report to tempdir
        with tempfile.TemporaryDirectory() as tmpdir:
            original_root = cu.get_project_root
            cu.get_project_root = lambda: tmpdir
            try:
                writer = ReportWriter( user_email="test@test.com", debug=True )
                path = writer.write(
                    agent   = "bug_fix_expediter",
                    slug    = "dead-job-not-found-smoke",
                    title   = "BFE Smoke Test Report",
                    body_md = "## Summary\n\nSmoke test body.\n",
                )
                assert os.path.exists( path )
                assert path.endswith( "-bug_fix_expediter-report.md" )
                assert "/io/swe-team/reports/test@test.com/" in path
                assert "-at-" in path and "-EST-" in path
                content = open( path ).read()
                assert "# BFE Smoke Test Report" in content
                assert "**Agent**: `bug_fix_expediter`" in content
                assert "Smoke test body." in content
                print( f"✓ Report written: {path}" )

                # 3: Empty body gets a placeholder
                path2 = writer.write( agent="test_fix_expediter", slug="empty-body", title="Empty", body_md="" )
                c2 = open( path2 ).read()
                assert "_(report body was empty" in c2
                print( "✓ Empty body handled" )

            finally:
                cu.get_project_root = original_root

        print( "\n✓ Shared ReportWriter smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
