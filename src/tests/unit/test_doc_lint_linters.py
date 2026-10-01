"""
The changed-lines filter, the shared command line and the four file linters.

The git-touching tests run against a real repository built in tmp_path, so the diff text the
parser reads comes from git itself and not from a hand-written fixture.
"""

import io
import json
import os
import subprocess

import pytest

from cosa.repo.doc_lint import changed_ranges as cr
from cosa.repo.doc_lint import cli, comment_lint, dartdoc_lint, docstring_lint, links, md_lint, word_list
from cosa.repo.doc_lint.text_rules import Finding

WORDS = frozenset( { "not", "never", "only", "the", "red" } )


@pytest.fixture( autouse=True )
def _small_word_list( tmp_path_factory ):
    root = tmp_path_factory.mktemp( "wordroot" )
    ( root / "src" / "conf" ).mkdir( parents=True )
    ( root / "src" / "conf" / "dm-tutor-lowercase-words.txt" ).write_text( "\n".join( sorted( WORDS ) ) + "\n", encoding="utf-8" )
    word_list.configure_root( root )
    yield
    word_list._state[ "root" ] = None
    word_list._state[ "words" ] = None


def _git( root, *args ):
    res = subprocess.run( [ "git", "-C", str( root ), "-c", "user.email=t@t", "-c", "user.name=t", *args ], capture_output=True, text=True )
    assert res.returncode == 0, res.stderr
    return res.stdout


@pytest.fixture
def repo( tmp_path ):
    _git( tmp_path, "init", "-q" )
    ( tmp_path / "src" / "conf" ).mkdir( parents=True )
    ( tmp_path / "src" / "conf" / "dm-tutor-lowercase-words.txt" ).write_text( "\n".join( sorted( WORDS ) ) + "\n", encoding="utf-8" )
    return tmp_path


def _commit( root, files ):
    for rel, text in files.items():
        full = root / rel
        full.parent.mkdir( parents=True, exist_ok=True )
        full.write_text( text, encoding="utf-8" )
    _git( root, "add", "-A" )
    _git( root, "commit", "-q", "-m", "c" )


# ---- changed_ranges --------------------------------------------------------------------------

def test_parse_diff_ranges_reads_added_lines_skips_deletions_and_deleted_files():
    diff = ( "+++ b/a.py\n@@ -1,0 +2,3 @@\n@@ -9 +11 @@\n@@ -20,2 +22,0 @@\n"
             "+++ /dev/null\n@@ -1,4 +0,0 @@\n"
             "+++ b/b.md\n@@ -5 +5,2 @@\n" )
    assert cr.parse_diff_ranges( diff ) == { "a.py": [ ( 2, 4 ), ( 11, 11 ) ], "b.md": [ ( 5, 6 ) ] }


def test_in_ranges_and_filter_keep_only_touched_lines_of_named_files():
    ranges   = { "a.py": [ ( 2, 4 ), ( 10, 10 ) ] }
    findings = [ Finding( "a.py", n, "r", "m" ) for n in ( 1, 2, 4, 5, 10 ) ] + [ Finding( "z.py", 3, "r", "m" ) ]
    assert [ f.line for f in cr.filter_findings( findings, ranges ) ] == [ 2, 4, 10 ]
    assert cr.in_ranges( 3, [] ) is False


def test_page_level_findings_survive_the_filter_when_the_file_was_touched_anywhere():
    ranges   = { "a.md": [ ( 50, 50 ) ], "b.md": [] }
    findings = [ Finding( "a.md", 1, "reference-length", "m" ), Finding( "a.md", 1, "caps", "m" ), Finding( "b.md", 1, "reference-length", "m" ),
                 Finding( "c.md", 1, "capability-length", "m" ), Finding( "a.md", 50, "caps", "m" ) ]
    assert [ ( f.path, f.rule ) for f in cr.filter_findings( findings, ranges ) ] == [ ( "a.md", "reference-length" ), ( "a.md", "caps" ) ]


def test_changed_line_ranges_reads_a_real_git_diff_against_a_base_and_against_the_index( repo ):
    _commit( repo, { "a.py": "one\ntwo\nthree\n" } )
    ( repo / "a.py" ).write_text( "one\nTWO\nthree\nfour\n", encoding="utf-8" )
    assert cr.changed_line_ranges( repo, "HEAD" ) == { "a.py": [ ( 2, 2 ), ( 4, 4 ) ] }
    assert cr.changed_line_ranges( repo, None, cached=True ) == {}
    _git( repo, "add", "a.py" )
    assert cr.changed_line_ranges( repo, None, cached=True ) == { "a.py": [ ( 2, 2 ), ( 4, 4 ) ] }


def test_changed_line_ranges_names_the_git_error_for_a_bad_base( repo ):
    _commit( repo, { "a.py": "x\n" } )
    with pytest.raises( RuntimeError, match="git diff failed" ):
        cr.changed_line_ranges( repo, "no-such-revision" )


# ---- cli -------------------------------------------------------------------------------------

def test_in_scope_excludes_tests_vendored_trees_and_rnd_but_keeps_source():
    assert cli.in_scope( "src/cosa/rest/a.py" ) is True
    for path in ( "src/tests/unit/a.py", "src/cosa/test_a.py", "x/conftest.py", "src/cosa/.venv/lib/a.py", "src/rnd/v1/a.md", "node_modules/x/a.md" ):
        assert cli.in_scope( path ) is False, path


def test_tracked_files_lists_git_files_by_suffix_and_refuses_a_non_repo( repo, tmp_path_factory ):
    _commit( repo, { "src/a.py": "x\n", "src/b.md": "x\n", "src/tests/t.py": "x\n", "src/c.txt": "x\n" } )
    assert cli.tracked_files( repo, ( ".py", ) ) == [ "src/a.py" ]
    assert cli.tracked_files( repo, ( ".py", ".md" ) ) == [ "src/a.py", "src/b.md" ]
    with pytest.raises( RuntimeError, match="git ls-files failed" ):
        cli.tracked_files( tmp_path_factory.mktemp( "notrepo" ), ( ".py", ) )


def _lint_every_line( path, source, root=None ):
    return [ Finding( path, n, "demo", "m" ) for n, _ in enumerate( source.split( "\n" ), start=1 ) if _.strip() ]


def test_run_linter_reports_text_json_strict_exit_and_unreadable_files( repo ):
    _commit( repo, { "src/a.py": "x\ny\n", "src/b.py": "z\n" } )
    ( repo / "src" / "bad.py" ).write_bytes( b"\xff\xfe" )
    _git( repo, "add", "-A" )
    out = io.StringIO()
    assert cli.run_linter( "d", ( ".py", ), _lint_every_line, [ "--repo-root", str( repo ) ], out ) == 0
    text = out.getvalue()
    assert "src/a.py:1: demo: m" in text and "src/a.py:2: demo: m" in text and "src/b.py:1: demo: m" in text
    assert "src/bad.py:1: unreadable" in text and text.strip().endswith( "4 findings in 3 files" )
    assert cli.run_linter( "d", ( ".py", ), _lint_every_line, [ "--repo-root", str( repo ), "--strict" ], io.StringIO() ) == 1
    assert cli.run_linter( "d", ( ".py", ), lambda p, s, r: [], [ "--repo-root", str( repo ), "--strict", "src/b.py" ], io.StringIO() ) == 0
    js = io.StringIO()
    cli.run_linter( "d", ( ".py", ), _lint_every_line, [ "--repo-root", str( repo ), "--json", "src/b.py" ], js )
    assert json.loads( js.getvalue() ) == [ { "path": "src/b.py", "line": 1, "rule": "demo", "message": "m" } ]


def test_run_linter_changed_and_staged_keep_only_touched_lines( repo ):
    _commit( repo, { "src/a.py": "x\ny\nz\n" } )
    ( repo / "src" / "a.py" ).write_text( "x\nY\nz\n", encoding="utf-8" )
    out = io.StringIO()
    cli.run_linter( "d", ( ".py", ), _lint_every_line, [ "--repo-root", str( repo ), "--changed", "HEAD" ], out )
    assert "src/a.py:2:" in out.getvalue() and "src/a.py:1:" not in out.getvalue()
    out = io.StringIO()
    cli.run_linter( "d", ( ".py", ), _lint_every_line, [ "--repo-root", str( repo ), "--staged" ], out )
    assert out.getvalue().strip() == "0 findings in 1 files"
    _git( repo, "add", "-A" )
    out = io.StringIO()
    cli.run_linter( "d", ( ".py", ), _lint_every_line, [ "--repo-root", str( repo ), "--staged" ], out )
    assert "src/a.py:2:" in out.getvalue() and "src/a.py:3:" not in out.getvalue()


# ---- docstring_lint --------------------------------------------------------------------------

PY_SOURCE = '''"""Module summary."""


def shouting( x ):
    """
    Return something.

    This is NOT fine, see row aa543525.
    """
    return x


class Plain:
    """Fine."""
'''


def test_extract_docstrings_returns_kind_name_line_and_raw_text_for_every_documented_node():
    found = docstring_lint.extract_docstrings( PY_SOURCE )
    assert [ ( k, n ) for k, n, _, _ in found ] == [ ( "Module", "<module>" ), ( "FunctionDef", "shouting" ), ( "ClassDef", "Plain" ) ]
    assert found[ 1 ][ 2 ] == 5 and found[ 1 ][ 3 ].split( "\n" )[ 3 ].strip().startswith( "This is NOT" )
    assert docstring_lint.extract_docstrings( "def f():\n    return 1\n\nx = 'not a docstring'\n" ) == []


def test_docstring_lint_reports_rules_at_file_lines_and_the_length_cap_and_parse_errors():
    findings = docstring_lint.lint_source( "a.py", PY_SOURCE )
    assert [ ( f.line, f.rule ) for f in findings if f.rule in ( "caps", "bare-ref" ) ] == [ ( 8, "bare-ref" ), ( 8, "caps" ) ]
    long_doc = 'def f():\n    """\n    Summary.\n' + "    filler\n" * 45 + '    """\n'
    assert [ f.rule for f in docstring_lint.lint_source( "a.py", long_doc ) if f.rule == "docstring-length" ] == [ "docstring-length" ]
    bad = docstring_lint.lint_source( "a.py", "def f(:\n" )
    assert [ f.rule for f in bad ] == [ "parse-error" ]


def test_docstring_lint_checks_design_paths_only_when_a_root_is_given( repo ):
    source = 'def f():\n    """\n    Do it.\n\n    Design: src/docs/missing.md\n    """\n'
    assert [ f.rule for f in docstring_lint.lint_source( "a.py", source ) if f.rule == "dead-design" ] == []
    found = docstring_lint.lint_source( "a.py", source, str( repo ) )
    assert [ ( f.rule, f.line ) for f in found if f.rule == "dead-design" ] == [ ( "dead-design", 5 ) ]


def test_docstring_lint_main_runs_over_the_repo_and_exits_one_when_strict( repo ):
    _commit( repo, { "src/a.py": PY_SOURCE } )
    out = io.StringIO()
    assert docstring_lint.main( [ "--repo-root", str( repo ), "--strict" ], out ) == 1
    assert "src/a.py:8: caps" in out.getvalue()


# ---- comment_lint ----------------------------------------------------------------------------

def test_comment_lint_flags_shouting_tics_and_dates_in_comments_but_not_strings_or_shebang():
    source = '#!/usr/bin/env python3\nx = "# NOT a comment"\n# This is NOT fine\n# measured 2026-07-25, deliberately\ny = 1  # ok\n'
    assert [ ( f.line, f.rule ) for f in comment_lint.lint_source( "a.py", source ) ] == [ ( 3, "caps" ), ( 4, "dated-banner" ), ( 4, "iso-date" ), ( 4, "tic" ) ]
    assert [ f.rule for f in comment_lint.lint_source( "a.py", "x = (\n" ) ] == [ "parse-error" ]
    assert comment_lint.lint_source( "a.py", "# NOT first line shebang\n" )[ 0 ].line == 1
    assert comment_lint.lint_source( "a.py", "#!/usr/bin/env NOT\nx = 1\n" ) == []               # a shebang is not prose


def test_comment_lint_main_runs_over_tracked_python_files( repo ):
    _commit( repo, { "src/a.py": "# This is NOT fine\n" } )
    out = io.StringIO()
    assert comment_lint.main( [ "--repo-root", str( repo ) ], out ) == 0
    assert "src/a.py:1: caps" in out.getvalue()


# ---- dartdoc_lint ----------------------------------------------------------------------------

DART = '''/// Group held rows by the persona who filed them.
///
/// This is NOT fine, see row aa543525.
List<Group> groupByFiler( List<Row> rows ) {
  final s = "/// not a comment ${ "nested /// still not" } end";
  final r = r'/// raw';
  final t = """
/// triple quoted
""";
  // plain comment
  //// four slashes
  /* block /// inside */
  return [];
}

/** Block doc summary. */
class A {}

/// Unterminated "string
void f() {}
'''


def test_doc_comment_lines_skip_strings_raw_strings_plain_and_block_comments_and_read_block_docs():
    lines = dartdoc_lint.doc_comment_lines( DART )
    assert [ ( n, t ) for n, t in lines if n < 5 ] == [ ( 1, "Group held rows by the persona who filed them." ), ( 2, "" ), ( 3, "This is NOT fine, see row aa543525." ) ]
    assert [ n for n, _ in lines if 5 <= n <= 13 ] == []
    assert ( 16, "Block doc summary." ) in lines and ( 19, "Unterminated \"string" ) in lines


def test_doc_comment_lines_handle_multiline_block_docs_and_an_unterminated_block():
    source = "/**\n * First line.\n * Second.\n */\nint x;\n/* open"
    assert dartdoc_lint.doc_comment_lines( source ) == [ ( 1, "" ), ( 2, "First line." ), ( 3, "Second." ), ( 4, "" ) ]
    assert dartdoc_lint.doc_comment_lines( "x = '''abc" ) == []
    assert dartdoc_lint.doc_comment_lines( "/**/\n/// a" ) == [ ( 2, "a" ) ]
    assert dartdoc_lint.doc_comment_lines( "a // tail" ) == []
    assert dartdoc_lint.doc_comment_lines( "x = 'a${ '}' } b' /// real" ) == [ ( 1, "real" ) ]
    assert dartdoc_lint.doc_comment_lines( "var x = 'a\\'/// b'; /// real" ) == [ ( 1, "real" ) ]
    assert dartdoc_lint.doc_comment_lines( "var x = 'never closed ${ " ) == []
    assert dartdoc_lint.doc_comment_lines( "var x = 'a${ {1: 2}[1] } b'; /// real" ) == [ ( 1, "real" ) ]      # nested braces
    assert dartdoc_lint.doc_comment_lines( "var x = 'abc" ) == []
    assert dartdoc_lint.doc_comment_lines( "var x = 'abc\n/// real" ) == [ ( 2, "real" ) ]      # a single-line string ends at the newline


def test_doc_blocks_group_consecutive_lines_and_split_on_gaps():
    blocks = dartdoc_lint.doc_blocks( "/// a\n/// b\n\n/// c\n" )
    assert blocks == [ ( 1, "a\nb" ), ( 4, "c" ) ]
    assert dartdoc_lint.doc_blocks( "int x;" ) == []


def test_dartdoc_lint_reports_rules_at_file_lines_and_the_block_length_cap():
    findings = dartdoc_lint.lint_source( "a.dart", DART )
    assert [ ( f.line, f.rule ) for f in findings if f.rule in ( "caps", "bare-ref" ) ] == [ ( 3, "bare-ref" ), ( 3, "caps" ) ]
    long_block = "\n".join( [ "/// Summary." ] + [ "/// filler" ] * 25 ) + "\nint x;\n"
    assert [ f.rule for f in dartdoc_lint.lint_source( "a.dart", long_block ) if f.rule == "dartdoc-length" ] == [ "dartdoc-length" ]


def test_dartdoc_lint_main_runs_over_tracked_dart_files( repo ):
    _commit( repo, { "lib/a.dart": "/// This is NOT fine.\nint x;\n" } )
    out = io.StringIO()
    assert dartdoc_lint.main( [ "--repo-root", str( repo ) ], out ) == 0
    assert "lib/a.dart:1: caps" in out.getvalue()


# ---- links -----------------------------------------------------------------------------------

def test_markdown_links_resolve_relative_to_the_page_and_skip_external_and_anchor_links( repo ):
    _commit( repo, { "docs/a.md": "x\n", "docs/sub/b.md": "x\n", "top.md": "x\n" } )
    text = "[ok](a.md) [ok2](sub/b.md#frag) [up](../top.md) [abs](/top.md) [gone](nope.md) [ext](https://x.y) [anch](#a) [viewer](/app/docs?path=x) [q](a.md?x=1) [empty](#) [onlyquery](?x=1)"
    found = links.markdown_link_findings( text, "docs/page.md", str( repo ) )
    assert [ f.message for f in found ] == [ "link target 'nope.md' does not exist" ]
    assert links.markdown_link_findings( "x\n\n[g](nope.md)", "docs/page.md", str( repo ) )[ 0 ].line == 3


def test_design_paths_resolve_from_the_repo_root_and_skip_lines_with_a_removal_note( repo ):
    _commit( repo, { "src/docs/real.md": "x\n" } )
    text = "Design: src/docs/real.md\nDesign: `src/docs/gone.md`\nDesign: src/rnd/x.md *(REMOVED by abc; recover: git show)*"
    found = links.design_path_findings( text, "a.py", 10, str( repo ) )
    assert [ ( f.line, f.message ) for f in found ] == [ ( 11, "Design path 'src/docs/gone.md' does not exist" ) ]


# ---- md_lint ---------------------------------------------------------------------------------

def test_md_lint_blanks_code_and_frontmatter_keeps_line_numbers_and_checks_prose_and_links( repo ):
    source = "---\ntitle: NOT here\n---\n# Page\n\n```\nNEVER here\n```\n\nThis is NOT fine, see [gone](nope.md).\n"
    found = md_lint.lint_source( "docs/p.md", source, str( repo ) )
    assert [ ( f.line, f.rule ) for f in found ] == [ ( 10, "caps" ), ( 10, "dead-link" ) ]
    assert [ f.rule for f in md_lint.lint_source( "docs/p.md", source ) ] == [ "caps" ]


def test_md_lint_template_caps_by_page_kind():
    capability = "\n".join( [ "Line." ] * 41 )
    assert [ f.rule for f in md_lint.lint_source( "src/docs/wiki/capabilities/x.md", capability ) ] == [ "capability-length" ]
    assert md_lint.lint_source( "src/docs/wiki/capabilities/x.md", "\n".join( [ "Line." ] * 40 ) ) == []
    reference = " ".join( [ "word" ] * 1501 )
    assert [ f.rule for f in md_lint.lint_source( "src/docs/ref.md", reference ) if f.rule == "reference-length" ] == [ "reference-length" ]
    assert [ f.rule for f in md_lint.lint_source( "src/docs/fastapi/api.md", reference ) if f.rule == "reference-length" ] == []
    assert [ f.rule for f in md_lint.lint_source( "README.md", reference ) if f.rule == "reference-length" ] == []
    assert md_lint.lint_source( "src/docs/short.md", "a short page" ) == []


def test_md_lint_runbook_needs_four_sections_and_reports_each_missing_one():
    page = "# Runbook\n## Prerequisites\nx\n## Steps\nx\n"
    assert [ f.message for f in md_lint.lint_source( "ops/tmux-runbook.md", page ) ] == [ "runbook has no rollback section", "runbook has no verify section" ]
    full = page + "## Verify\nx\n## Rollback\nx\n"
    assert md_lint.lint_source( "ops/tmux-runbook.md", full ) == []


def test_md_page_rates_and_main( repo ):
    assert md_lint.page_rates( "It is NOT so — dash.\n" )[ "em_dash" ] > 0
    _commit( repo, { "docs/p.md": "This is NOT fine.\n" } )
    out = io.StringIO()
    assert md_lint.main( [ "--repo-root", str( repo ) ], out ) == 0
    assert "docs/p.md:1: caps" in out.getvalue()
