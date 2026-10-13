"""
The scratch-repository demonstration that gate 3 of the commit hook chain blocks.

Each test builds a throwaway repository under tmp_path and copies in the real doc_lint package and the real chain script.
The chain is installed as that repository's own commit hook, and the test then makes a real commit.
Nothing is pushed and pytest deletes the directory.
"""

import os
import shutil
import subprocess

import pytest

import cosa.utils.util as cu

CHAIN        = os.path.join( cu.get_project_root(), "src", "scripts", "pre-commit-chain.sh" )
DOC_LINT     = os.path.join( cu.get_project_root(), "src", "cosa", "repo", "doc_lint" )
WORDS        = [ "not", "never", "the" ]
SEEDED       = "This is NOT fine.\n"
CLEAN        = "This is fine.\n"
CAPS         = "caps: ALL-CAPS word NOT"
WARN_MARK    = " (warn mode, commit allowed)"
CHAIN_REFUSE = "[pre-commit-chain] doc-lint gate REFUSED the commit: fix each REFUSED line above, stage the fix with git add and commit again"
CHAIN_CRASH  = "[pre-commit-chain] doc-lint gate CRASHED (exit 1), commit ALLOWED and NOT CHECKED against the documentation standard"
GATE_CRASH   = "[doc-lint] GATE CRASHED, commit allowed: RuntimeError: injected linter crash"
GATE_REFUSE  = "[doc-lint] 1 findings on staged lines, commit REFUSED: fix each REFUSED line above, stage the fix and commit again"
WARN_SUMMARY = "[doc-lint] 1 findings in history.md or TODO.md (warn mode, commit allowed)"
CLEAN_LINE   = "[doc-lint] 0 findings on staged lines (blocking)"
DOCSTRING_PY = 'def f():\n    """\n    Return it.\n\n    This is NOT fine.\n    """\n'
COMMENT_PY   = "x = 1  # This is NOT fine.\n"


def _git( root, *args, check=True ):
    """Run git in root with a fixed identity and return the finished process."""
    env = { **os.environ, "PLANNING_IS_PROMPTING_ROOT": "", "LUPIN_RUFF": "", "LUPIN_MARKDOWNLINT": "" }
    res = subprocess.run( [ "git", "-C", str( root ), "-c", "user.email=t@t", "-c", "user.name=t", *args ], capture_output=True, text=True, env=env )
    if check: assert res.returncode == 0, res.stderr
    return res


def _commit_count( root ):
    """Return how many commits the scratch repository holds."""
    return int( _git( root, "rev-list", "--count", "--all" ).stdout.strip() )


def _committed_paths( root ):
    """Return the paths the last commit of the scratch repository holds."""
    return sorted( p for p in _git( root, "ls-tree", "-r", "--name-only", "HEAD" ).stdout.split( "\n" ) if p )


def _stage( root, files ):
    """Write files in the scratch repository and stage them."""
    for rel, text in files.items():
        full = root / rel
        full.parent.mkdir( parents=True, exist_ok=True )
        full.write_text( text, encoding="utf-8" )
    _git( root, "add", "-f", *files )


def _commit( root ):
    """Make a real commit attempt through the hook and return the finished process."""
    return _git( root, "commit", "-q", "-m", "a commit made by the demonstration", check=False )


def _doc_lint_lines( text ):
    """Return the lines the gate and the chain printed about the documentation standard."""
    return [ ln for ln in text.split( "\n" ) if ln.startswith( ( "[doc-lint]", "[pre-commit-chain] doc-lint" ) ) ]


@pytest.fixture
def scratch( tmp_path ):
    """Build a scratch repository whose own commit hook is a copy of the real chain."""
    _git( tmp_path, "init", "-q" )
    ( tmp_path / "src" / "conf" ).mkdir( parents=True )
    ( tmp_path / "src" / "scripts" ).mkdir()
    ( tmp_path / "src" / "conf" / "dm-tutor-lowercase-words.txt" ).write_text( "\n".join( WORDS ) + "\n", encoding="utf-8" )
    shutil.copytree( DOC_LINT, tmp_path / "src" / "cosa" / "repo" / "doc_lint", ignore=shutil.ignore_patterns( "__pycache__" ) )
    for d in ( tmp_path / "src" / "cosa", tmp_path / "src" / "cosa" / "repo" ): ( d / "__init__.py" ).write_text( "", encoding="utf-8" )
    shutil.copy( CHAIN, tmp_path / "src" / "scripts" / "pre-commit-chain.sh" )
    os.chmod( tmp_path / "src" / "scripts" / "pre-commit-chain.sh", 0o755 )
    os.symlink( "../../src/scripts/pre-commit-chain.sh", tmp_path / ".git" / "hooks" / "pre-commit" )
    return tmp_path


def test_the_scratch_hook_is_the_chain_copied_from_this_tree( scratch ):
    hook = scratch / ".git" / "hooks" / "pre-commit"
    assert os.path.realpath( hook ) == os.path.realpath( scratch / "src" / "scripts" / "pre-commit-chain.sh" )
    with open( CHAIN, encoding="utf-8" ) as handle: real = handle.read()
    assert hook.read_text( encoding="utf-8" ) == real and real.count( "cosa.repo.doc_lint.gate --blocking --repo-root" ) == 1


def test_a_seeded_markdown_finding_stops_a_real_commit( scratch ):
    _stage( scratch, { "docs/p.md": SEEDED } )
    res = _commit( scratch )
    assert res.returncode == 1
    assert f"[doc-lint] REFUSED docs/p.md:1: {CAPS}" in res.stderr.split( "\n" )
    assert GATE_REFUSE in res.stderr.split( "\n" ) and CHAIN_REFUSE in res.stderr.split( "\n" )
    assert _commit_count( scratch ) == 0


@pytest.mark.parametrize( "rel,source,line", [
    ( "src/pkg/a.py",       COMMENT_PY,   1 ),          # a comment in a swept file: the docstring refusal does not reach it
    ( "src/lupin_mcp/b.py", DOCSTRING_PY, 5 ),          # a docstring outside the swept scope, with no count table to hold it
] )
def test_a_seeded_finding_on_the_touched_lines_of_a_python_file_stops_a_real_commit( scratch, rel, source, line ):
    _stage( scratch, { rel: source } )
    res = _commit( scratch )
    assert res.returncode == 1
    assert f"[doc-lint] REFUSED {rel}:{line}: {CAPS}" in res.stderr.split( "\n" )
    assert GATE_REFUSE in res.stderr.split( "\n" ) and CHAIN_REFUSE in res.stderr.split( "\n" )
    assert _commit_count( scratch ) == 0


def test_a_clean_page_is_committed( scratch ):
    _stage( scratch, { "docs/p.md": CLEAN } )
    res = _commit( scratch )
    assert res.returncode == 0
    assert CLEAN_LINE in res.stderr.split( "\n" ) and "REFUSED" not in res.stderr and "CRASHED" not in res.stderr
    assert _commit_count( scratch ) == 1 and _committed_paths( scratch ) == [ "docs/p.md" ]


def test_a_linter_that_crashes_on_import_lets_the_commit_through_and_says_it_was_not_checked( scratch ):
    ( scratch / "src" / "cosa" / "repo" / "doc_lint" / "md_lint.py" ).write_text( 'raise RuntimeError( "injected linter crash" )\n', encoding="utf-8" )
    _stage( scratch, { "docs/p.md": SEEDED } )
    res = _commit( scratch )
    assert res.returncode == 0
    assert "RuntimeError: injected linter crash" in res.stderr.split( "\n" ) and CHAIN_CRASH in res.stderr.split( "\n" )
    assert CAPS not in res.stderr and "REFUSED" not in res.stderr
    assert _commit_count( scratch ) == 1 and _committed_paths( scratch ) == [ "docs/p.md" ]


def test_a_linter_that_crashes_while_linting_lets_the_commit_through_with_the_gate_crashed_line( scratch ):
    md_lint = scratch / "src" / "cosa" / "repo" / "doc_lint" / "md_lint.py"
    source  = md_lint.read_text( encoding="utf-8" )
    anchor  = "    prose    = blank_non_prose( source )\n    findings = lint_text("
    assert source.count( anchor ) == 1
    md_lint.write_text( source.replace( anchor, '    raise RuntimeError( "injected linter crash" )\n' + anchor ), encoding="utf-8" )
    _stage( scratch, { "docs/p.md": SEEDED } )
    res = _commit( scratch )
    assert res.returncode == 0
    assert GATE_CRASH in res.stderr.split( "\n" )
    assert CAPS not in res.stderr and "REFUSED" not in res.stderr and "[pre-commit-chain] doc-lint" not in res.stderr
    assert _commit_count( scratch ) == 1 and _committed_paths( scratch ) == [ "docs/p.md" ]


@pytest.mark.parametrize( "rel", [ "history.md", "TODO.md" ] )
def test_a_seeded_finding_in_the_root_history_or_todo_file_is_committed_with_the_warn_marking( scratch, rel ):
    _stage( scratch, { rel: SEEDED } )
    res = _commit( scratch )
    assert res.returncode == 0
    assert f"[doc-lint] {rel}:1: {CAPS}{WARN_MARK}" in res.stderr.split( "\n" )
    assert WARN_SUMMARY in res.stderr.split( "\n" ) and CLEAN_LINE in res.stderr.split( "\n" ) and "REFUSED" not in res.stderr
    assert _commit_count( scratch ) == 1 and _committed_paths( scratch ) == [ rel ]


@pytest.mark.parametrize( "rel", [ "src/cosa/history.md", "src/cosa/TODO.md", "docs/history.md", "docs/TODO.md" ] )
def test_the_same_finding_in_another_history_or_todo_file_stops_a_real_commit( scratch, rel ):
    _stage( scratch, { rel: SEEDED } )
    res = _commit( scratch )
    assert res.returncode == 1
    assert f"[doc-lint] REFUSED {rel}:1: {CAPS}" in res.stderr.split( "\n" )
    assert WARN_MARK not in res.stderr and CHAIN_REFUSE in res.stderr.split( "\n" )
    assert _commit_count( scratch ) == 0


def test_a_clean_file_beside_a_finding_in_the_root_history_file_is_committed( scratch ):
    _stage( scratch, { "docs/p.md": CLEAN, "history.md": SEEDED } )
    res = _commit( scratch )
    assert res.returncode == 0
    assert f"[doc-lint] history.md:1: {CAPS}{WARN_MARK}" in res.stderr.split( "\n" ) and "REFUSED" not in res.stderr
    assert _commit_count( scratch ) == 1 and _committed_paths( scratch ) == [ "docs/p.md", "history.md" ]


def test_a_finding_in_the_root_history_file_does_not_excuse_a_finding_in_another_page( scratch ):
    _stage( scratch, { "docs/p.md": SEEDED, "history.md": SEEDED } )
    res = _commit( scratch )
    lines = _doc_lint_lines( res.stderr )
    assert res.returncode == 1
    assert f"[doc-lint] REFUSED docs/p.md:1: {CAPS}" in lines and f"[doc-lint] history.md:1: {CAPS}{WARN_MARK}" in lines
    refused = [ ln for ln in lines if ln.startswith( "[doc-lint] REFUSED " ) ]
    assert len( refused ) == 1 and "history.md" not in refused[ 0 ]
    assert GATE_REFUSE in lines and WARN_SUMMARY in lines and CHAIN_REFUSE in lines
    assert _commit_count( scratch ) == 0
