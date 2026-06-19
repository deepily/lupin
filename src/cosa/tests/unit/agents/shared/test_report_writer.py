"""
Unit tests for cosa.agents.shared.report_writer.ReportWriter.

Writes dated final-report markdown. Filesystem work is confined to a tempdir
(cu.get_project_root patched); no other I/O.

Covers: _sanitize_slug (normal / weird-chars / empty / >6-words / all-hyphens fallback),
write (with body + debug, empty-body placeholder), _get_report_path convention.

Created 2026-05-31 (CoSA coverage campaign, shared package — Tiffany 💍). New file.
"""

import os
import tempfile
import unittest
from unittest.mock import patch

from cosa.agents.shared.report_writer import ReportWriter


class TestReportWriter( unittest.TestCase ):
    """Comprehensive unit tests for ReportWriter."""

    # ------------------------------------------------------------------ #
    # _sanitize_slug                                                      #
    # ------------------------------------------------------------------ #

    def test_sanitize_slug_normal( self ):
        """Test a normal slug is lowercased and hyphen-joined."""
        self.assertEqual(
            ReportWriter._sanitize_slug( "BFE Final Report for Dead Job" ),
            "bfe-final-report-for-dead-job"
        )

    def test_sanitize_slug_strips_weird_chars_and_underscores( self ):
        """Test punctuation is stripped and underscores become hyphens."""
        self.assertEqual( ReportWriter._sanitize_slug( "!!!weird---chars!!!" ), "weird-chars" )
        self.assertEqual( ReportWriter._sanitize_slug( "dead_job_not_found" ), "dead-job-not-found" )

    def test_sanitize_slug_empty_returns_unknown( self ):
        """Test an empty/no-word slug falls back to 'unknown'."""
        self.assertEqual( ReportWriter._sanitize_slug( "" ), "unknown" )
        self.assertEqual( ReportWriter._sanitize_slug( "!!!" ), "unknown" )

    def test_sanitize_slug_truncates_to_six_words( self ):
        """Test a slug is truncated to at most six words."""
        self.assertEqual( ReportWriter._sanitize_slug( "a b c d e f g h i" ), "a-b-c-d-e-f" )

    def test_sanitize_slug_all_hyphens_fallback( self ):
        """Test a hyphen-only slug collapses + strips to the 'unknown' fallback."""
        self.assertEqual( ReportWriter._sanitize_slug( "---" ), "unknown" )

    # ------------------------------------------------------------------ #
    # write / _get_report_path                                            #
    # ------------------------------------------------------------------ #

    def test_write_report_with_body( self ):
        """
        Test write() creates the dated report file with title + agent + body.

        Ensures (debug on):
            - Path follows the dated convention under the user's reports dir
            - Title, agent tag, and body all appear in the file
        """
        with tempfile.TemporaryDirectory() as tmp, \
             patch( "cosa.agents.shared.report_writer.cu.get_project_root", return_value=tmp ):
            writer = ReportWriter( user_email="test@test.com", debug=True )
            path = writer.write(
                agent="bug_fix_expediter", slug="dead-job-found",
                title="BFE Report", body_md="## Summary\n\nDone.\n"
            )

            self.assertTrue( os.path.exists( path ) )
            self.assertTrue( path.endswith( "-bug_fix_expediter-report.md" ) )
            self.assertIn( "/io/swe-team/reports/test@test.com/", path )
            self.assertIn( "-at-", path )
            self.assertIn( "-EST-", path )
            content = open( path ).read()
            self.assertIn( "# BFE Report", content )
            self.assertIn( "**Agent**: `bug_fix_expediter`", content )
            self.assertIn( "Done.", content )

    def test_write_empty_body_gets_placeholder( self ):
        """Test an empty body is replaced with a placeholder note."""
        with tempfile.TemporaryDirectory() as tmp, \
             patch( "cosa.agents.shared.report_writer.cu.get_project_root", return_value=tmp ):
            writer = ReportWriter( user_email="u@x.com" )
            path = writer.write( agent="test_fix_expediter", slug="empty", title="Empty", body_md="" )

            self.assertIn( "_(report body was empty", open( path ).read() )


if __name__ == "__main__":
    unittest.main()
