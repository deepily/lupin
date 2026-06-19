"""
Unit tests for cosa.repo.branch_change_analysis.

Pure classifiers (get_file_type / is_python_comment_or_docstring /
is_javascript_comment) are tested directly. analyze_diff() runs two
`git diff` subprocesses; both are mocked with canned diff text crafted to
exercise the python/javascript/other categorization, docstring + multiline-
comment state tracking, removed-line counting, and the per-type file-count
report. No real git repo is touched.
"""

import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch, MagicMock

import cosa.repo.branch_change_analysis as bca


def _proc( stdout="", returncode=0, stderr="" ):
    return MagicMock( stdout=stdout, returncode=returncode, stderr=stderr )


def _run_analyze( diff_text, name_only="", diff_rc=0, name_rc=0 ):
    """Patch the two subprocess.run calls and capture analyze_diff()'s stdout."""
    results = [ _proc( diff_text, diff_rc ) ]
    if diff_rc == 0:
        results.append( _proc( name_only, name_rc ) )
    buf = io.StringIO()
    with patch( "cosa.repo.branch_change_analysis.subprocess.run", side_effect=results ):
        with redirect_stdout( buf ):
            bca.analyze_diff()
    return buf.getvalue()


class TestGetFileType( unittest.TestCase ):
    """get_file_type() — extension mapping + defaults."""

    def test_known_extensions( self ):
        self.assertEqual( bca.get_file_type( "a.py" ), "python" )
        self.assertEqual( bca.get_file_type( "a.js" ), "javascript" )
        self.assertEqual( bca.get_file_type( "a.md" ), "markdown" )
        self.assertEqual( bca.get_file_type( "a.yml" ), "yaml" )

    def test_unknown_extension_is_other( self ):
        self.assertEqual( bca.get_file_type( "a.rs" ), "other" )

    def test_empty_and_dev_null_are_other( self ):
        self.assertEqual( bca.get_file_type( "" ), "other" )
        self.assertEqual( bca.get_file_type( "/dev/null" ), "other" )


class TestPythonClassifier( unittest.TestCase ):
    """is_python_comment_or_docstring()."""

    def test_empty_is_none( self ):
        self.assertIsNone( bca.is_python_comment_or_docstring( "   " ) )

    def test_hash_comment( self ):
        self.assertEqual( bca.is_python_comment_or_docstring( "  # hi" ), "comment" )

    def test_docstring_start_and_end( self ):
        self.assertEqual( bca.is_python_comment_or_docstring( '"""doc' ), "docstring" )
        self.assertEqual( bca.is_python_comment_or_docstring( "doc'''" ), "docstring" )

    def test_code( self ):
        self.assertEqual( bca.is_python_comment_or_docstring( "x = 1" ), "code" )


class TestJavascriptClassifier( unittest.TestCase ):
    """is_javascript_comment()."""

    def test_empty_is_none( self ):
        self.assertIsNone( bca.is_javascript_comment( "" ) )

    def test_line_comment( self ):
        self.assertEqual( bca.is_javascript_comment( "// hi" ), "comment" )

    def test_block_comment_markers( self ):
        self.assertEqual( bca.is_javascript_comment( "/* open" ), "comment" )
        self.assertEqual( bca.is_javascript_comment( "* mid" ), "comment" )
        self.assertEqual( bca.is_javascript_comment( "close */" ), "comment" )

    def test_code( self ):
        self.assertEqual( bca.is_javascript_comment( "let x = 1;" ), "code" )


class TestAnalyzeDiff( unittest.TestCase ):
    """analyze_diff() — end-to-end diff parsing + report rendering."""

    def test_git_error_returns_early( self ):
        out = _run_analyze( "", diff_rc=1 )
        self.assertIn( "Error running git diff", out )

    def test_full_diff_renders_all_sections( self ):
        diff = "\n".join( [
            "diff --git a/foo.py b/foo.py",
            "index 111..222 100644",
            "--- a/foo.py",
            "+++ b/foo.py",
            "@@ -1,2 +1,6 @@",
            "+def f():",            # code
            "+    # a comment",     # comment
            "+    '''",             # docstring toggle ON
            "+    body text",       # in-docstring -> docstring
            "+    '''",             # docstring toggle OFF -> end docstring
            "+",                    # blank added -> uncategorized
            "-old_code = 1",        # removed
            " context",             # context (ignored)
            "diff --git a/bar.js b/bar.js",
            "index 333..444 100644",
            "--- a/bar.js",
            "+++ b/bar.js",
            "@@ -1,1 +1,5 @@",
            "+// line comment",     # js comment
            "+/* open",             # js multiline start
            "+ still inside",       # in multiline -> comment
            "+close */",            # multiline end marker -> comment
            "+let x = 1;",          # js code
            "-var old = 2;",        # js removed
            "diff --git a/notes.txt b/notes.txt",
            "+just text",           # other added
            "-old text",            # other removed
            "Binary files differ",  # ignored
            "diff --git malformed",  # < 4 parts -> no file set
        ] )
        name_only = "foo.py\nbar.js\nnotes.txt\n"
        out = _run_analyze( diff, name_only=name_only )

        self.assertIn( "CODE CHANGES ANALYSIS", out )
        self.assertIn( "OVERALL SUMMARY", out )
        self.assertIn( "BREAKDOWN BY FILE TYPE", out )
        self.assertIn( "PYTHON FILES - SOURCE vs DOCUMENTATION", out )
        self.assertIn( "JAVASCRIPT FILES - SOURCE vs DOCUMENTATION", out )
        self.assertIn( "FILES CHANGED BY TYPE", out )
        self.assertIn( "Total files:", out )

    def test_name_only_failure_skips_file_count( self ):
        diff = "\n".join( [
            "diff --git a/foo.py b/foo.py",
            "+x = 1",
        ] )
        out = _run_analyze( diff, name_rc=1 )
        self.assertIn( "FILES CHANGED BY TYPE", out )
        self.assertNotIn( "Total files:", out )   # name-only failed -> section skipped

    def test_python_blank_only_hits_zero_total_percentages( self ):
        # python file whose only added line is blank -> stats added>0 but py_total==0,
        # exercising the `if py_total > 0 else 0` percentage fallback.
        diff = "\n".join( [
            "diff --git a/foo.py b/foo.py",
            "+",
        ] )
        out = _run_analyze( diff, name_only="foo.py\n" )
        self.assertIn( "PYTHON FILES", out )
        self.assertIn( "0.0%", out )

    def test_javascript_blank_only_hits_zero_total_percentages( self ):
        diff = "\n".join( [
            "diff --git a/bar.js b/bar.js",
            "+",
        ] )
        out = _run_analyze( diff, name_only="bar.js\n" )
        self.assertIn( "JAVASCRIPT FILES", out )
        self.assertIn( "0.0%", out )

    def test_name_only_with_internal_blank_skips_empty_entry( self ):
        # An internal blank line survives .strip().split('\n') as "" -> the
        # `if f:` guard skips it (the empty-filename branch).
        diff = "\n".join( [ "diff --git a/foo.py b/foo.py", "+x = 1" ] )
        out = _run_analyze( diff, name_only="foo.py\n\nbar.py\n" )
        self.assertIn( "Total files:", out )


if __name__ == "__main__":
    unittest.main()
