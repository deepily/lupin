"""
Unit tests for cosa.agents.utils.sender_id.

detect_project walks up from cwd to the nearest .git and applies legacy aliases;
build_sender_id assembles the routing string. Tests use tempdir trees with .git
markers and patch os.getcwd — no other I/O.

Covers: detect_project (top-level / nested / walk-up / alias / basename fallback /
fallback-alias), build_sender_id (auto-detect / explicit / suffix / no-suffix), and
the _assert_detect_for_cwd helper.

Created 2026-05-31 (CoSA coverage campaign, utils package — Tiffany 💍). New file.
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cosa.agents.utils import sender_id as sid


class TestDetectProject( unittest.TestCase ):
    """Unit tests for detect_project()."""

    def _detect_at( self, path ):
        with patch( "os.getcwd", return_value=str( path ) ):
            return sid.detect_project()

    def test_top_level_repo( self ):
        """Test cwd at a repo root returns its basename."""
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path( tmp ) / "myproj"
            ( proj / ".git" ).mkdir( parents=True )
            self.assertEqual( self._detect_at( proj ), "myproj" )

    def test_nested_repo_wins( self ):
        """Test the nearest enclosing .git wins for nested repos."""
        with tempfile.TemporaryDirectory() as tmp:
            cosa = Path( tmp ) / "lupin" / "src" / "cosa"
            ( Path( tmp ) / "lupin" / ".git" ).mkdir( parents=True )
            ( cosa / ".git" ).mkdir( parents=True )
            self.assertEqual( self._detect_at( cosa ), "cosa" )

    def test_walks_up_to_repo_root( self ):
        """Test a subdir with no .git walks up to the enclosing repo."""
        with tempfile.TemporaryDirectory() as tmp:
            sub = Path( tmp ) / "lupin" / "src" / "deep" / "sub"
            ( Path( tmp ) / "lupin" / ".git" ).mkdir( parents=True )
            sub.mkdir( parents=True )
            self.assertEqual( self._detect_at( sub ), "lupin" )

    def test_alias_applied_on_repo_name( self ):
        """Test a legacy alias maps the repo basename (planning-is-prompting → plan)."""
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path( tmp ) / "planning-is-prompting"
            ( proj / ".git" ).mkdir( parents=True )
            self.assertEqual( self._detect_at( proj ), "plan" )

    def test_basename_fallback_no_git( self ):
        """Test a tree with no .git ancestor falls back to the cwd basename."""
        with tempfile.TemporaryDirectory() as tmp:
            loose = Path( tmp ) / "loose-dir"
            loose.mkdir( parents=True )
            self.assertEqual( self._detect_at( loose ), "loose-dir" )

    def test_basename_fallback_applies_alias( self ):
        """Test the basename fallback also applies the alias map."""
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path( tmp ) / "planning-is-prompting"
            proj.mkdir( parents=True )   # no .git anywhere
            self.assertEqual( self._detect_at( proj ), "plan" )


class TestBuildSenderId( unittest.TestCase ):
    """Unit tests for build_sender_id()."""

    def test_auto_detect_project( self ):
        """Test a None project triggers auto-detection."""
        with patch( "cosa.agents.utils.sender_id.detect_project", return_value="lupin" ):
            self.assertEqual( sid.build_sender_id( "deep.research" ), "deep.research@lupin.deepily.ai" )

    def test_explicit_project_with_suffix( self ):
        """Test an explicit project + suffix renders the full id."""
        self.assertEqual(
            sid.build_sender_id( "swe.lead", project="testproj", suffix="abc123" ),
            "swe.lead@testproj.deepily.ai#abc123"
        )

    def test_no_suffix( self ):
        """Test omitting the suffix yields a bare id."""
        result = sid.build_sender_id( "claude.code.job", project="lupin" )
        self.assertEqual( result, "claude.code.job@lupin.deepily.ai" )
        self.assertNotIn( "#", result )


class TestAssertHelper( unittest.TestCase ):
    """Unit test for the _assert_detect_for_cwd helper."""

    def test_assert_detect_for_cwd_passes( self ):
        """Test the helper asserts detect_project matches the expected name."""
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path( tmp ) / "helperproj"
            ( proj / ".git" ).mkdir( parents=True )
            # Should not raise when expectation matches
            sid._assert_detect_for_cwd( proj, "helperproj" )

    def test_assert_detect_for_cwd_raises_on_mismatch( self ):
        """Test the helper raises AssertionError on a wrong expectation."""
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path( tmp ) / "helperproj"
            ( proj / ".git" ).mkdir( parents=True )
            with self.assertRaises( AssertionError ):
                sid._assert_detect_for_cwd( proj, "wrong-name" )


if __name__ == "__main__":
    unittest.main()
