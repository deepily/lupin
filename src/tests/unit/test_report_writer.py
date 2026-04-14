"""
Unit tests for cosa.agents.shared.report_writer.ReportWriter.

Covers:
  - Slug sanitization (boundary conditions)
  - Path shape (project_root/io/swe-team/reports/{email}/YYYY.MM.DD-at-HH:MM-EST-{slug}-{agent}-report.md)
  - Report content (title, agent, body)
  - Empty body handling
"""

import os
import re
import tempfile

import pytest

import cosa.utils.util as cu
from cosa.agents.shared.report_writer import ReportWriter


@pytest.fixture
def tmp_project_root( monkeypatch ):
    """Redirect cu.get_project_root() to a tempdir for the test."""
    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setattr( cu, "get_project_root", lambda: tmp )
        yield tmp


class TestSlugSanitizer:

    def test_basic_lowercasing_and_word_cap( self ):
        assert ReportWriter._sanitize_slug( "BFE Final Report for Dead Job" ) == "bfe-final-report-for-dead-job"

    def test_empty_string_falls_back( self ):
        assert ReportWriter._sanitize_slug( "" ) == "unknown"

    def test_none_falls_back( self ):
        assert ReportWriter._sanitize_slug( None ) == "unknown"

    def test_strips_punctuation( self ):
        assert ReportWriter._sanitize_slug( "!!!weird---chars!!!" ) == "weird-chars"

    def test_caps_at_six_words( self ):
        assert ReportWriter._sanitize_slug( "a b c d e f g h i" ) == "a-b-c-d-e-f"

    def test_collapses_multiple_hyphens( self ):
        assert ReportWriter._sanitize_slug( "foo    bar" ) == "foo-bar"


class TestWrite:

    def test_writes_file_at_expected_path_shape( self, tmp_project_root ):
        writer = ReportWriter( user_email="test@test.com" )
        path = writer.write(
            agent   = "bug_fix_expediter",
            slug    = "dead-job-not-found",
            title   = "BFE Test Report",
            body_md = "## Summary\n\nBody.\n",
        )
        assert os.path.exists( path )
        assert "/io/swe-team/reports/test@test.com/" in path
        filename = os.path.basename( path )
        # YYYY.MM.DD-at-HH:MM-EST-{slug}-{agent}-report.md
        assert re.match( r"^\d{4}\.\d{2}\.\d{2}-at-\d{2}:\d{2}-EST-dead-job-not-found-bug_fix_expediter-report\.md$", filename )

    def test_report_contains_title_agent_and_body( self, tmp_project_root ):
        writer = ReportWriter( user_email="test@test.com" )
        path = writer.write(
            agent   = "test_fix_expediter",
            slug    = "cluster-run",
            title   = "TFE Test Report",
            body_md = "## Summary\n\nAll clusters resolved.\n",
        )
        content = open( path ).read()
        assert content.startswith( "# TFE Test Report\n" )
        assert "**Agent**: `test_fix_expediter`" in content
        assert "All clusters resolved." in content

    def test_empty_body_gets_placeholder_note( self, tmp_project_root ):
        writer = ReportWriter( user_email="test@test.com" )
        path = writer.write( agent="bug_fix_expediter", slug="empty", title="Empty", body_md="" )
        content = open( path ).read()
        assert "_(report body was empty" in content

    def test_none_body_gets_placeholder_note( self, tmp_project_root ):
        writer = ReportWriter( user_email="test@test.com" )
        path = writer.write( agent="bug_fix_expediter", slug="none", title="None", body_md=None )
        content = open( path ).read()
        assert "_(report body was empty" in content

    def test_email_partitioning_separates_users( self, tmp_project_root ):
        a = ReportWriter( user_email="alice@x.com" ).write( agent="bug_fix_expediter", slug="s", title="A", body_md="a" )
        b = ReportWriter( user_email="bob@x.com"   ).write( agent="bug_fix_expediter", slug="s", title="B", body_md="b" )
        assert "/alice@x.com/" in a
        assert "/bob@x.com/"   in b
        assert os.path.dirname( a ) != os.path.dirname( b )

    def test_filename_contains_agent_suffix( self, tmp_project_root ):
        writer = ReportWriter( user_email="test@test.com" )
        bfe_path = writer.write( agent="bug_fix_expediter",  slug="s", title="A", body_md="a" )
        tfe_path = writer.write( agent="test_fix_expediter", slug="s", title="B", body_md="b" )
        assert bfe_path.endswith( "-bug_fix_expediter-report.md" )
        assert tfe_path.endswith( "-test_fix_expediter-report.md" )
