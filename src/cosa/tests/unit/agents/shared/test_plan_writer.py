"""
Unit tests for cosa.agents.shared.plan_writer (PlanWriter).

NEW FILE 2026-05-31 by Extra 2 🪨 (CoSA coverage campaign, shared/ lane). PlanWriter is
the agent-agnostic structured-markdown plan writer shared by BFE/TFE. It is pure logic
(no SDK/network) — but importing it triggers shared/__init__ → fix_executor →
ClaudeAgentOptions, so this runs via run-sdk-cov.sh. The filesystem is isolated with a
tempdir + patched cu.get_project_root; contexts/diagnoses/fixes are duck-typed
SimpleNamespace stand-ins (PlanWriter reads attributes, never imports agent types).

Must run via run-sdk-cov.sh.
"""

import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from cosa.agents.shared.plan_writer import PlanWriter


def make_ctx( stack_trace="Traceback:\n  File x.py, line 1", error="KeyError: 'k'" ):
    return SimpleNamespace(
        id_hash="job-123", job_type="deep_research", error=error, stack_trace=stack_trace,
    )


def make_diag( evidence=None, components=None ):
    return SimpleNamespace(
        root_cause="Missing config key in INI",
        error_category="config",
        confidence=0.85,
        evidence=evidence if evidence is not None else [ "KeyError at line 42" ],
        affected_components=components if components is not None else [ "lupin-app.ini" ],
    )


def make_fix( title="Add key", changes=None ):
    return SimpleNamespace(
        title=title, description="desc", fix_type="config_change",
        confidence=0.9, risk_level="low", estimated_effort="minutes",
        changes=changes if changes is not None else [
            { "file": "lupin-app.ini", "action": "modify", "description": "Add key" }
        ],
    )


class TestGenerateSlug( unittest.TestCase ):

    def test_normal( self ):
        self.assertEqual(
            PlanWriter._generate_slug( "Missing config key 'foo' in lupin-app.ini" ),
            "missing-config-key-foo-in",
        )

    def test_weird_chars_collapse( self ):
        self.assertEqual( PlanWriter._generate_slug( "!!!weird---chars!!!" ), "weirdchars" )

    def test_truncates_to_five_words( self ):
        self.assertEqual( PlanWriter._generate_slug( "a b c d e f g h" ), "a-b-c-d-e" )

    def test_empty_falls_back_to_unknown( self ):
        self.assertEqual( PlanWriter._generate_slug( "" ), "unknown-fix" )


@patch( "cosa.utils.util.get_project_root" )
class TestWritePlan( unittest.TestCase ):

    def test_write_with_selected_and_changes( self, mock_root ):
        with tempfile.TemporaryDirectory() as d:
            mock_root.return_value = d
            w = PlanWriter( user_email="u@x.com", debug=True )
            fixes = [ make_fix( "Add key" ), make_fix( "Fallback", changes=[ ] ) ]
            path = w.write_plan( make_ctx(), make_diag(), fixes, selected_fix=fixes[ 0 ] )
            self.assertTrue( os.path.exists( path ) )
            content = open( path ).read()
        self.assertIn( "[SELECTED]", content )       # selected match (200 true)
        self.assertIn( "Add key", content )
        self.assertIn( "Fallback", content )          # fix with empty changes (210 false)
        self.assertIn( "| lupin-app.ini |", content ) # changes table (210 true)

    def test_write_without_selected_and_empty_evidence( self, mock_root ):
        with tempfile.TemporaryDirectory() as d:
            mock_root.return_value = d
            w = PlanWriter( user_email="u@x.com", debug=False )
            # selected_fix=None → 200 false; empty evidence/components → 171/172 false;
            # stack_trace None → 174 default.
            ctx  = make_ctx( stack_trace=None, error=None )
            diag = make_diag( evidence=[ ], components=[ ] )
            path = w.write_plan( ctx, diag, [ make_fix() ], selected_fix=None )
            content = open( path ).read()
        self.assertNotIn( "[SELECTED]", content )
        self.assertIn( "No stack trace available", content )
        self.assertIn( "No error message", content )
        self.assertIn( "- None identified", content )


@patch( "cosa.utils.util.get_project_root" )
class TestUpdateImplementationLog( unittest.TestCase ):

    def _written_plan( self, d, debug=False ):
        w = PlanWriter( user_email="u@x.com", debug=debug )
        path = w.write_plan( make_ctx(), make_diag(), [ make_fix() ] )
        return w, path

    def test_missing_file_noop_debug( self, mock_root ):
        with tempfile.TemporaryDirectory() as d:
            mock_root.return_value = d
            w = PlanWriter( user_email="u@x.com", debug=True )
            # must not raise
            w.update_implementation_log( "/no/such/plan.md", SimpleNamespace(), [ ], "" )

    def test_missing_file_noop_no_debug( self, mock_root ):
        with tempfile.TemporaryDirectory() as d:
            mock_root.return_value = d
            w = PlanWriter( user_email="u@x.com", debug=False )
            w.update_implementation_log( "/no/such/plan.md", SimpleNamespace(), [ ], "" )

    def test_placeholder_replaced_applied_success( self, mock_root ):
        with tempfile.TemporaryDirectory() as d:
            mock_root.return_value = d
            w, path = self._written_plan( d, debug=True )
            fr = SimpleNamespace( applied=True, success=True, details="did it", retry_eligible=False )
            w.update_implementation_log( path, fr, [ "a.py", "b.py" ], "coder summary" )
            content = open( path ).read()
        self.assertIn( "Status**: Applied — Success", content )
        self.assertIn( "- a.py", content )

    def test_placeholder_replaced_failed_no_files_no_summary( self, mock_root ):
        # applied False / success False / retry_eligible True; empty files + summary arms.
        with tempfile.TemporaryDirectory() as d:
            mock_root.return_value = d
            w, path = self._written_plan( d )
            fr = SimpleNamespace( applied=False, success=False, details=None, retry_eligible=True )
            w.update_implementation_log( path, fr, [ ], "" )
            content = open( path ).read()
        self.assertIn( "Failed — Failure", content )
        self.assertIn( "Retry Eligible**: Yes", content )
        self.assertIn( "No summary available", content )

    def test_placeholder_absent_noop( self, mock_root ):
        with tempfile.TemporaryDirectory() as d:
            mock_root.return_value = d
            w, path = self._written_plan( d, debug=True )
            fr = SimpleNamespace( applied=True, success=True, details="x", retry_eligible=False )
            # first call consumes the placeholder; second finds none → else branch.
            w.update_implementation_log( path, fr, [ "a.py" ], "s" )
            w.update_implementation_log( path, fr, [ "a.py" ], "s" )


@patch( "cosa.utils.util.get_project_root" )
class TestUpdateGitReferences( unittest.TestCase ):

    def _written_plan( self, debug=False ):
        w = PlanWriter( user_email="u@x.com", debug=debug )
        path = w.write_plan( make_ctx(), make_diag(), [ make_fix() ] )
        return w, path

    def test_missing_file_noop( self, mock_root ):
        with tempfile.TemporaryDirectory() as d:
            mock_root.return_value = d
            w = PlanWriter( user_email="u@x.com", debug=True )
            w.update_git_references( "/no/such/plan.md", SimpleNamespace() )

    def test_placeholder_replaced( self, mock_root ):
        with tempfile.TemporaryDirectory() as d:
            mock_root.return_value = d
            w, path = self._written_plan( debug=True )
            fr = SimpleNamespace( git_strategy="commit_only", commit_hash="abc1234",
                                  branch_name="main", pr_url=None )
            w.update_git_references( path, fr )
            content = open( path ).read()
        self.assertIn( "abc1234", content )

    def test_placeholder_absent_noop( self, mock_root ):
        with tempfile.TemporaryDirectory() as d:
            mock_root.return_value = d
            w, path = self._written_plan( debug=True )
            fr = SimpleNamespace( git_strategy="x", commit_hash="h", branch_name="b", pr_url=None )
            w.update_git_references( path, fr )
            w.update_git_references( path, fr )   # placeholder already gone → else branch


if __name__ == "__main__":
    unittest.main()
