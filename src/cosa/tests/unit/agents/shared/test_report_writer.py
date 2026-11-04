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
from cosa.config.app_timezone import InvalidAppTimezoneError


class _Cfg:
    """A config answering `app timezone` through get_required."""

    config_block_id = "Lupin:+Stub"

    def __init__( self, zone="America/New_York" ):
        self.zone = zone

    def get_required( self, key, **_kwargs ):
        return self.zone


def _configured( zone="America/New_York" ):
    """Patch the ConfigurationManager the writer builds, so the zone is the one given."""
    return patch( "cosa.agents.shared.report_writer.ConfigurationManager", return_value=_Cfg( zone ) )


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
        with tempfile.TemporaryDirectory() as tmp, _configured(), \
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
            self.assertRegex( path, r"-(EST|EDT)-" )
            content = open( path ).read()
            self.assertIn( "# BFE Report", content )
            self.assertIn( "**Agent**: `bug_fix_expediter`", content )
            self.assertIn( "Done.", content )

    def test_write_empty_body_gets_placeholder( self ):
        """Test an empty body is replaced with a placeholder note."""
        with tempfile.TemporaryDirectory() as tmp, _configured(), \
             patch( "cosa.agents.shared.report_writer.cu.get_project_root", return_value=tmp ):
            writer = ReportWriter( user_email="u@x.com" )
            path = writer.write( agent="test_fix_expediter", slug="empty", title="Empty", body_md="" )

            self.assertIn( "_(report body was empty", open( path ).read() )

    def test_the_filename_zone_token_follows_the_configured_zone( self ):
        """Kolkata is IST, which no Eastern literal could produce."""
        with tempfile.TemporaryDirectory() as tmp, _configured( "Asia/Kolkata" ), \
             patch( "cosa.agents.shared.report_writer.cu.get_project_root", return_value=tmp ):
            path = ReportWriter( user_email="u@x.com" ).write( agent="a", slug="s", title="T", body_md="b" )
            self.assertIn( "-IST-", path )
            self.assertNotRegex( path, r"-(EST|EDT)-" )
            self.assertTrue( open( path ).read().split( "**Generated**: " )[ 1 ].split( "\n" )[ 0 ].endswith( "+05:30" ) )

    def test_an_unknown_configured_zone_stops_the_writer( self ):
        with _configured( "Mars/Olympus_Mons" ), self.assertRaises( InvalidAppTimezoneError ):
            ReportWriter( user_email="u@x.com" )


if __name__ == "__main__":
    unittest.main()
