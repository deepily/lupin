"""
The scratch-repository demonstration that gate 3 of the commit hook chain blocks.

Each test builds a throwaway repository under tmp_path and copies in the real doc_lint package and the real chain script.
The chain is installed as that repository's own commit hook, and the test then makes a real commit.
Stand-ins that report nothing replace ruff and markdownlint-cli2, so the host's tools do not change a result.
Nothing is pushed and pytest deletes the directory.
"""

import os
import shutil
import subprocess
import sys

import pytest

import cosa.utils.util as cu
from cosa.repo.doc_lint import md_lint

CHAIN         = os.path.join( cu.get_project_root(), "src", "scripts", "pre-commit-chain.sh" )
DOC_LINT      = os.path.join( cu.get_project_root(), "src", "cosa", "repo", "doc_lint" )
OLD_GATE      = os.path.join( cu.get_project_root(), "src", "tests", "unit", "fixtures", "doc-lint-gate-at-59c155252.py.txt" )
OLD_GATE_SHA  = "59c155252"
WORDS         = [ "not", "never", "the" ]
SEEDED        = "# Page\n\nThis is NOT fine.\n"
CLEAN         = "# Page\n\nThis is fine.\n"
CAPS          = "caps: ALL-CAPS word NOT"
WARN_MARK     = " (warn mode, commit allowed)"
PREDATES_MARK = " (warn mode, commit allowed: this condition predates the commit)"
CHAIN_REFUSE  = "[pre-commit-chain] doc-lint gate REFUSED the commit: fix each REFUSED line above, stage the fix with git add and commit again"
CHAIN_ALLOW_1 = "[pre-commit-chain] doc-lint gate exited 1 without a refusal verdict, commit ALLOWED: findings above, if any, were NOT enforced. If this tree's gate.py predates blocking, rebase."
GATE_CRASH    = "[doc-lint] GATE CRASHED, commit allowed: RuntimeError: injected linter crash"
GATE_REFUSE   = "[doc-lint] 1 findings on staged lines, commit REFUSED: fix each REFUSED line above, stage the fix and commit again"
WARN_SET      = "history.md or TODO.md or bug-fix-queue.md or history/ or todo-history/"
WARN_SUMMARY  = f"[doc-lint] 1 findings in {WARN_SET} (warn mode, commit allowed)"
RECORDS       = [ "history.md", "TODO.md", "bug-fix-queue.md", "history/2026-08-history.md", "todo-history/2026-08-todo.md" ]
ALIKE         = [ "x/history.md", "x/bug-fix-queue.md", "src/history.md", "historyx/a.md", "src/history/a.md", "x/todo-history/a.md", "src/cosa/history/a.md", "src/cosa/TODO.md", "src/cosa/history.md" ]
CLEAN_LINE    = "[doc-lint] 0 findings on staged lines (blocking)"
DOCSTRING_PY  = 'def f():\n    """\n    Return it.\n\n    This is NOT fine.\n    """\n'
COMMENT_PY    = "x = 1  # This is NOT fine.\n"
MD041         = "MD041/first-line-heading First line in a file should be a top-level heading"
QUIET_TOOL    = "#!/bin/sh\nexit 0\n"
COUNTING_TOOL = '#!/bin/sh\nn=0; for a in "$@"; do case "$a" in --|--no-globs) ;; *) n=$((n+1));; esac; done; echo "Linting: $n file(s)"\nexit 0\n'
LOUD_MDLINT   = '#!/bin/sh\nn=0; for a in "$@"; do case "$a" in --|--no-globs) ;; *) n=$((n+1));; esac; done; echo "Linting: $n file(s)"\nfor f in "$@"; do case "$f" in *.md) echo "$f:1 error ' + MD041 + '" >&2;; esac; done\nexit 1\n'
CAP_PAGE      = "src/docs/wiki/capabilities/x.md"
RUNBOOK       = "docs/ops-runbook.md"


def _git( root, *args, check=True ):
    """Run git in root with a fixed identity and return the finished process."""
    res = subprocess.run( [ "git", "-C", str( root ), "-c", "user.email=t@t", "-c", "user.name=t", *args ], capture_output=True, text=True )
    if check: assert res.returncode == 0, res.stderr
    return res


def _commit_count( root ):
    """Return how many commits the scratch repository holds."""
    return int( _git( root, "rev-list", "--count", "--all" ).stdout.strip() )


def _committed_paths( root ):
    """Return the paths the last commit of the scratch repository holds."""
    return sorted( p for p in _git( root, "ls-tree", "-r", "--name-only", "-z", "HEAD" ).stdout.split( "\0" ) if p )


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


def _gate( root ):
    """Run the gate module in root, as the chain does, and return the finished process."""
    env = { **os.environ, "LUPIN_ROOT": str( root ), "PYTHONPATH": str( root / "src" ) }
    cmd = [ sys.executable, "-m", "cosa.repo.doc_lint.gate", "--blocking", "--repo-root", str( root ) ]
    return subprocess.run( cmd, capture_output=True, text=True, env=env, cwd=str( root ) )


def _baseline( root, files ):
    """Commit files without the hook, as the state the commit under test starts from."""
    _stage( root, files )
    _git( root, "commit", "-q", "--no-verify", "-m", "the state before the commit under test" )


def _tool( path, text ):
    """Write one executable stand-in for an external tool and return its path."""
    path.parent.mkdir( parents=True, exist_ok=True )
    path.write_text( text, encoding="utf-8" )
    os.chmod( path, 0o755 )
    return str( path )


def _page( count, changed=() ):
    """Return a page of count lines; a line number in changed gets other words."""
    return "# Page\n" + "".join( f"Line {n} is {'still ' if n in changed else ''}fine.\n" for n in range( 2, count + 1 ) )


def _cap( count ):
    """Return the finding text for a capability page of count lines."""
    return f"capability-length: capability page of {count} lines, limit 40"


@pytest.fixture
def scratch( tmp_path, monkeypatch ):
    """Build a scratch repository whose own commit hook is a copy of the real chain."""
    monkeypatch.setenv( "PLANNING_IS_PROMPTING_ROOT", "" )
    monkeypatch.setenv( "LUPIN_RUFF", _tool( tmp_path / "tools" / "ruff", QUIET_TOOL ) )
    monkeypatch.setenv( "LUPIN_MARKDOWNLINT", _tool( tmp_path / "tools" / "markdownlint-cli2", COUNTING_TOOL ) )
    root = tmp_path / "repo"
    root.mkdir()
    _git( root, "init", "-q" )
    ( root / "src" / "conf" ).mkdir( parents=True )
    ( root / "src" / "scripts" ).mkdir()
    ( root / "src" / "conf" / "dm-tutor-lowercase-words.txt" ).write_text( "\n".join( WORDS ) + "\n", encoding="utf-8" )
    shutil.copytree( DOC_LINT, root / "src" / "cosa" / "repo" / "doc_lint", ignore=shutil.ignore_patterns( "__pycache__" ) )
    for d in ( root / "src" / "cosa", root / "src" / "cosa" / "repo" ): ( d / "__init__.py" ).write_text( "", encoding="utf-8" )
    shutil.copy( CHAIN, root / "src" / "scripts" / "pre-commit-chain.sh" )
    os.chmod( root / "src" / "scripts" / "pre-commit-chain.sh", 0o755 )
    os.symlink( "../../src/scripts/pre-commit-chain.sh", root / ".git" / "hooks" / "pre-commit" )
    return root


def test_the_scratch_hook_is_the_chain_copied_from_this_tree( scratch ):
    hook = scratch / ".git" / "hooks" / "pre-commit"
    assert os.path.realpath( hook ) == os.path.realpath( scratch / "src" / "scripts" / "pre-commit-chain.sh" )
    with open( CHAIN, encoding="utf-8" ) as handle: real = handle.read()
    assert hook.read_text( encoding="utf-8" ) == real and real.count( "cosa.repo.doc_lint.gate --blocking --repo-root" ) == 1


def test_a_seeded_markdown_finding_stops_a_real_commit( scratch ):
    _stage( scratch, { "docs/p.md": SEEDED } )
    res = _commit( scratch )
    assert res.returncode == 1
    assert f"[doc-lint] REFUSED docs/p.md:3: {CAPS}" in res.stderr.split( "\n" )
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
    assert CLEAN_LINE in res.stderr.split( "\n" ) and "REFUSED" not in res.stderr and "[pre-commit-chain] doc-lint" not in res.stderr
    assert "WARNING" not in res.stderr                                   # neither stand-in was reported missing or failing
    assert _commit_count( scratch ) == 1 and _committed_paths( scratch ) == [ "docs/p.md" ]


def test_a_linter_that_crashes_on_import_lets_the_commit_through_and_says_nothing_was_enforced( scratch ):
    ( scratch / "src" / "cosa" / "repo" / "doc_lint" / "md_lint.py" ).write_text( 'raise RuntimeError( "injected linter crash" )\n', encoding="utf-8" )
    _stage( scratch, { "docs/p.md": SEEDED } )
    res = _commit( scratch )
    assert res.returncode == 0
    assert "RuntimeError: injected linter crash" in res.stderr.split( "\n" ) and CHAIN_ALLOW_1 in res.stderr.split( "\n" )
    assert CAPS not in res.stderr and "REFUSED" not in res.stderr
    assert _commit_count( scratch ) == 1 and _committed_paths( scratch ) == [ "docs/p.md" ]


def test_a_linter_that_crashes_while_linting_lets_the_commit_through_with_the_gate_crashed_line( scratch ):
    target = scratch / "src" / "cosa" / "repo" / "doc_lint" / "md_lint.py"
    source = target.read_text( encoding="utf-8" )
    anchor = "    prose    = blank_non_prose( source )\n    findings = lint_text("
    assert source.count( anchor ) == 1
    target.write_text( source.replace( anchor, '    raise RuntimeError( "injected linter crash" )\n' + anchor ), encoding="utf-8" )
    _stage( scratch, { "docs/p.md": SEEDED } )
    res = _commit( scratch )
    assert res.returncode == 0
    assert GATE_CRASH in res.stderr.split( "\n" )
    assert CAPS not in res.stderr and "REFUSED" not in res.stderr and "[pre-commit-chain] doc-lint" not in res.stderr
    assert _commit_count( scratch ) == 1 and _committed_paths( scratch ) == [ "docs/p.md" ]


def test_the_older_gate_fixture_is_the_gate_of_the_commit_before_blocking():
    res = subprocess.run( [ "git", "-C", cu.get_project_root(), "show", f"{OLD_GATE_SHA}:src/cosa/repo/doc_lint/gate.py" ], capture_output=True )
    if res.returncode != 0: pytest.skip( f"commit {OLD_GATE_SHA} cannot be read from this tree, so the fixture's origin was not compared" )
    with open( OLD_GATE, "rb" ) as handle: assert handle.read() == res.stdout


def test_an_older_gate_under_the_new_chain_commits_and_the_chain_says_the_findings_were_not_enforced( scratch ):
    shutil.copy( OLD_GATE, scratch / "src" / "cosa" / "repo" / "doc_lint" / "gate.py" )
    with open( OLD_GATE, encoding="utf-8" ) as handle: assert "return 1 if args.blocking and findings else 0" in handle.read()
    _stage( scratch, { "docs/p.md": SEEDED } )
    res   = _commit( scratch )
    lines = res.stderr.split( "\n" )
    assert res.returncode == 0
    assert f"[doc-lint] docs/p.md:3: {CAPS}" in lines and "[doc-lint] 1 findings on staged lines (blocking)" in lines
    assert CHAIN_ALLOW_1 in lines and "CRASHED" not in res.stderr and "REFUSED" not in res.stderr
    assert _commit_count( scratch ) == 1 and _committed_paths( scratch ) == [ "docs/p.md" ]


@pytest.mark.parametrize( "rel", RECORDS )
def test_the_gate_entry_point_exits_zero_and_marks_a_finding_in_a_record_location( scratch, rel ):
    _stage( scratch, { rel: SEEDED } )
    res   = _gate( scratch )
    lines = res.stderr.split( "\n" )
    assert res.returncode == 0
    assert f"[doc-lint] {rel}:3: {CAPS}{WARN_MARK}" in lines and WARN_SUMMARY in lines and CLEAN_LINE in lines
    assert "REFUSED" not in res.stderr and "CRASHED" not in res.stderr


@pytest.mark.parametrize( "rel", ALIKE )
def test_the_gate_entry_point_exits_three_on_a_finding_in_a_look_alike_of_a_record_location( scratch, rel ):
    _stage( scratch, { rel: SEEDED } )
    res   = _gate( scratch )
    lines = res.stderr.split( "\n" )
    assert res.returncode == 3
    assert f"[doc-lint] REFUSED {rel}:3: {CAPS}" in lines and GATE_REFUSE in lines
    assert WARN_MARK not in res.stderr and "CRASHED" not in res.stderr


@pytest.mark.parametrize( "rel", RECORDS )
def test_a_seeded_finding_in_a_record_location_is_committed_with_the_warn_marking( scratch, rel ):
    _stage( scratch, { rel: SEEDED } )
    res = _commit( scratch )
    assert res.returncode == 0
    assert f"[doc-lint] {rel}:3: {CAPS}{WARN_MARK}" in res.stderr.split( "\n" )
    assert WARN_SUMMARY in res.stderr.split( "\n" ) and CLEAN_LINE in res.stderr.split( "\n" ) and "REFUSED" not in res.stderr
    assert _commit_count( scratch ) == 1 and _committed_paths( scratch ) == [ rel ]


@pytest.mark.parametrize( "rel", ALIKE + [ "docs/history.md", "docs/TODO.md" ] )
def test_the_same_finding_in_a_look_alike_of_a_record_location_stops_a_real_commit( scratch, rel ):
    _stage( scratch, { rel: SEEDED } )
    res = _commit( scratch )
    assert res.returncode == 1
    assert f"[doc-lint] REFUSED {rel}:3: {CAPS}" in res.stderr.split( "\n" )
    assert WARN_MARK not in res.stderr and CHAIN_REFUSE in res.stderr.split( "\n" )
    assert _commit_count( scratch ) == 0


def test_a_clean_file_beside_a_finding_in_the_root_history_file_is_committed( scratch ):
    _stage( scratch, { "docs/p.md": CLEAN, "history.md": SEEDED } )
    res = _commit( scratch )
    assert res.returncode == 0
    assert f"[doc-lint] history.md:3: {CAPS}{WARN_MARK}" in res.stderr.split( "\n" ) and "REFUSED" not in res.stderr
    assert _commit_count( scratch ) == 1 and _committed_paths( scratch ) == [ "docs/p.md", "history.md" ]


def test_a_finding_in_the_root_history_file_does_not_excuse_a_finding_in_another_page( scratch ):
    _stage( scratch, { "docs/p.md": SEEDED, "history.md": SEEDED } )
    res   = _commit( scratch )
    lines = res.stderr.split( "\n" )
    assert res.returncode == 1
    assert f"[doc-lint] REFUSED docs/p.md:3: {CAPS}" in lines and f"[doc-lint] history.md:3: {CAPS}{WARN_MARK}" in lines
    refused = [ ln for ln in lines if ln.startswith( "[doc-lint] REFUSED " ) ]
    assert len( refused ) == 1 and "history.md" not in refused[ 0 ]
    assert GATE_REFUSE in lines and WARN_SUMMARY in lines and CHAIN_REFUSE in lines
    assert _commit_count( scratch ) == 0


# ---- the host's markdownlint-cli2 does not change a result -----------------------------------

def test_a_failing_markdownlint_on_the_search_path_does_not_change_a_clean_commit( scratch, tmp_path, monkeypatch ):
    _tool( tmp_path / "host-bin" / "markdownlint-cli2", LOUD_MDLINT )
    monkeypatch.setenv( "PATH", f"{tmp_path / 'host-bin'}{os.pathsep}{os.environ[ 'PATH' ]}" )
    assert shutil.which( "markdownlint-cli2" ) == str( tmp_path / "host-bin" / "markdownlint-cli2" )
    _stage( scratch, { "docs/p.md": CLEAN } )
    res = _commit( scratch )
    assert res.returncode == 0 and CLEAN_LINE in res.stderr.split( "\n" ) and "MD041" not in res.stderr
    assert _commit_count( scratch ) == 1


def test_a_markdownlint_finding_on_a_staged_line_stops_a_real_commit_for_that_reason( scratch, tmp_path, monkeypatch ):
    monkeypatch.setenv( "LUPIN_MARKDOWNLINT", _tool( tmp_path / "host-bin" / "markdownlint-cli2", LOUD_MDLINT ) )
    _stage( scratch, { "docs/p.md": CLEAN } )
    res = _commit( scratch )
    assert res.returncode == 1
    assert [ ln for ln in res.stderr.split( "\n" ) if ln.startswith( "[doc-lint] REFUSED " ) ] == [ f"[doc-lint] REFUSED docs/p.md:1: markdownlint:{MD041.replace( ' ', ': ', 1 )}" ]
    assert GATE_REFUSE in res.stderr.split( "\n" ) and CHAIN_REFUSE in res.stderr.split( "\n" ) and _commit_count( scratch ) == 0


# ---- file names git quotes -------------------------------------------------------------------

@pytest.mark.parametrize( "rel", [ "docs/café.md", "docs/two words.md", 'docs/a"quote.md' ] )
def test_a_seeded_finding_in_a_file_whose_name_git_quotes_stops_a_real_commit_and_is_named( scratch, rel ):
    _stage( scratch, { rel: SEEDED } )
    res = _commit( scratch )
    assert res.returncode == 1
    assert f"[doc-lint] REFUSED {rel}:3: {CAPS}" in res.stderr.split( "\n" ) and CHAIN_REFUSE in res.stderr.split( "\n" )
    assert _commit_count( scratch ) == 0


# ---- a page-level condition the commit did not create ----------------------------------------

def test_a_one_line_edit_to_a_page_already_over_its_limit_is_committed_with_the_predating_marking( scratch ):
    _baseline( scratch, { CAP_PAGE: _page( 41 ) } )
    _stage( scratch, { CAP_PAGE: _page( 41, changed=( 5, ) ) } )
    res = _commit( scratch )
    assert res.returncode == 0
    assert f"[doc-lint] {CAP_PAGE}:1: {_cap( 41 )}{PREDATES_MARK}" in res.stderr.split( "\n" )
    assert "[doc-lint] 1 page-level findings predate this commit (warn mode, commit allowed)" in res.stderr.split( "\n" ) and "REFUSED" not in res.stderr
    assert _commit_count( scratch ) == 2


@pytest.mark.parametrize( "before,after", [ ( 40, 41 ), ( 41, 42 ) ] )
def test_an_edit_that_takes_a_page_over_its_limit_or_makes_an_over_limit_page_longer_stops_a_real_commit( scratch, before, after ):
    _baseline( scratch, { CAP_PAGE: _page( before ) } )
    _stage( scratch, { CAP_PAGE: _page( after ) } )
    res = _commit( scratch )
    assert res.returncode == 1
    assert f"[doc-lint] REFUSED {CAP_PAGE}:1: {_cap( after )}" in res.stderr.split( "\n" ) and CHAIN_REFUSE in res.stderr.split( "\n" )
    assert PREDATES_MARK not in res.stderr and _commit_count( scratch ) == 1


def test_an_edit_that_shrinks_an_over_limit_page_is_committed( scratch ):
    _baseline( scratch, { CAP_PAGE: _page( 44 ) } )
    _stage( scratch, { CAP_PAGE: _page( 42, changed=( 5, ) ) } )
    res = _commit( scratch )
    assert res.returncode == 0
    assert f"[doc-lint] {CAP_PAGE}:1: {_cap( 42 )}{PREDATES_MARK}" in res.stderr.split( "\n" ) and _commit_count( scratch ) == 2


def test_a_brand_new_over_limit_page_stops_a_real_commit( scratch ):
    _baseline( scratch, { "docs/other.md": CLEAN } )
    _stage( scratch, { CAP_PAGE: _page( 41 ) } )
    res = _commit( scratch )
    assert res.returncode == 1
    assert f"[doc-lint] REFUSED {CAP_PAGE}:1: {_cap( 41 )}" in res.stderr.split( "\n" ) and _commit_count( scratch ) == 1


def test_a_line_added_to_a_runbook_that_already_lacked_its_sections_is_committed( scratch ):
    _baseline( scratch, { RUNBOOK: "# Ops\n\nSome text.\n" } )
    _stage( scratch, { RUNBOOK: "# Ops\n\nSome text.\n\nOne more line.\n" } )
    res    = _commit( scratch )
    marked = [ ln for ln in res.stderr.split( "\n" ) if ln.endswith( PREDATES_MARK ) ]
    assert res.returncode == 0
    assert sorted( marked ) == sorted( f"[doc-lint] {RUNBOOK}:1: runbook-template: runbook has no {section} section{PREDATES_MARK}" for section in md_lint.RUNBOOK_SECTIONS )
    assert len( marked ) == 4 and "REFUSED" not in res.stderr and _commit_count( scratch ) == 2


def test_an_edit_that_removes_a_section_from_a_runbook_stops_a_real_commit_for_that_section_only( scratch ):
    _baseline( scratch, { RUNBOOK: "# Ops\n\n## Steps\n\nSome text.\n" } )
    _stage( scratch, { RUNBOOK: "# Ops\n\n## Procedure\n\nSome text.\n" } )
    res = _commit( scratch )
    assert res.returncode == 1
    assert [ ln for ln in res.stderr.split( "\n" ) if ln.startswith( "[doc-lint] REFUSED " ) ] == [ f"[doc-lint] REFUSED {RUNBOOK}:1: runbook-template: runbook has no steps section" ]
    assert "[doc-lint] 3 page-level findings predate this commit (warn mode, commit allowed)" in res.stderr.split( "\n" ) and _commit_count( scratch ) == 1


# ---- names that are not UTF-8, and lines that look like a header ---------------------------------

def test_a_seeded_finding_in_a_file_whose_name_is_not_utf8_stops_a_real_commit_and_is_named_readably( scratch ):
    _stage( scratch, { "docs/caf\udce9.md": SEEDED } )
    res = _commit( scratch )
    assert res.returncode == 1
    assert f"[doc-lint] REFUSED docs/caf\\xe9.md:3: {CAPS}" in res.stderr.split( "\n" ) and "GATE CRASHED" not in res.stderr
    assert CHAIN_REFUSE in res.stderr.split( "\n" ) and _commit_count( scratch ) == 0


@pytest.mark.parametrize( "page", [ '# Page\n\n++ "a\\"\n', "# Page\n\n" + "\udce9".join( [ "clean", "text\n" ] ) ] )
def test_a_page_the_diff_reader_or_the_decoder_cannot_read_does_not_let_a_swept_finding_through( scratch, page ):
    full = scratch / "docs" / "p.md"
    full.parent.mkdir( parents=True )
    full.write_bytes( os.fsencode( page ) )
    _git( scratch, "add", "-f", "docs/p.md" )
    _stage( scratch, { "src/pkg/a.py": DOCSTRING_PY } )
    res = _commit( scratch )
    assert res.returncode == 1
    assert "GATE CRASHED" not in res.stderr and "[doc-lint] 1 refusals, commit REFUSED" in res.stderr.split( "\n" ) and _commit_count( scratch ) == 0


# ---- concluding a merge or a cherry-pick --------------------------------------------------------

MERGED_MARK = " (warn mode, commit allowed: this line came in with the merged or picked commit)"
BASE_A      = "# A\n\nThe base text.\n"
SIDE_A      = "# A\n\nThe side text.\n"
MAIN_A      = "# A\n\nThe main text.\n"
CLEAN_A     = "# A\n\nThe merged text.\n"
SEEDED_A    = "# A\n\nThe merged text is NOT fine.\n"


@pytest.fixture
def merging( scratch, tmp_path, monkeypatch ):
    """Give the scratch repository two conflicting branches and a core.hooksPath hook."""
    monkeypatch.setenv( "GIT_EDITOR", "true" )
    os.remove( scratch / ".git" / "hooks" / "pre-commit" )
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    shutil.copy( CHAIN, hooks / "pre-commit" )
    os.chmod( hooks / "pre-commit", 0o755 )
    _git( scratch, "config", "core.hooksPath", str( hooks ) )
    _baseline( scratch, { "docs/a.md": BASE_A } )
    _git( scratch, "branch", "-M", "main" )
    _git( scratch, "checkout", "-q", "-b", "side" )
    _baseline( scratch, { "docs/a.md": SIDE_A, "docs/legacy.md": SEEDED } )
    _git( scratch, "checkout", "-q", "main" )
    _baseline( scratch, { "docs/a.md": MAIN_A } )
    return scratch


def _start( root, how ):
    """Start a merge or a cherry-pick of the side branch and check that it stopped."""
    res = _git( root, how, "side", check=False )
    assert res.returncode != 0 and "onflict" in res.stdout + res.stderr and _commit_count( root ) == 3


@pytest.mark.parametrize( "how,conclude", [ ( "merge", [ "commit", "-q", "--no-edit" ] ), ( "merge", [ "merge", "--continue" ] ), ( "cherry-pick", [ "cherry-pick", "--continue" ] ) ] )
def test_concluding_a_conflicted_merge_or_pick_commits_a_finding_that_came_from_the_other_side( merging, how, conclude ):
    _start( merging, how )
    _stage( merging, { "docs/a.md": CLEAN_A } )
    res = _git( merging, *conclude, check=False )
    assert res.returncode == 0, res.stderr
    assert f"[doc-lint] docs/legacy.md:3: {CAPS}{MERGED_MARK}" in res.stderr.split( "\n" ) and "REFUSED" not in res.stderr
    assert "[doc-lint] 1 findings came in with the merged or picked commit (warn mode, commit allowed)" in res.stderr.split( "\n" )
    assert _commit_count( merging ) == 4 and _committed_paths( merging ) == [ "docs/a.md", "docs/legacy.md" ]


@pytest.mark.parametrize( "how,conclude", [ ( "merge", [ "commit", "-q", "--no-edit" ] ), ( "merge", [ "merge", "--continue" ] ), ( "cherry-pick", [ "cherry-pick", "--continue" ] ) ] )
def test_concluding_a_conflicted_merge_or_pick_is_refused_for_a_finding_the_resolution_adds( merging, how, conclude ):
    _start( merging, how )
    _stage( merging, { "docs/a.md": SEEDED_A } )
    res = _git( merging, *conclude, check=False )
    assert res.returncode != 0
    assert [ ln for ln in res.stderr.split( "\n" ) if ln.startswith( "[doc-lint] REFUSED " ) ] == [ f"[doc-lint] REFUSED docs/a.md:3: {CAPS}" ]
    assert f"[doc-lint] docs/legacy.md:3: {CAPS}{MERGED_MARK}" in res.stderr.split( "\n" ) and CHAIN_REFUSE in res.stderr.split( "\n" )
    assert _commit_count( merging ) == 3


def test_an_ordinary_commit_through_the_hooks_path_is_judged_as_before( merging ):
    _stage( merging, { "docs/p.md": SEEDED } )
    res = _commit( merging )
    assert res.returncode == 1 and f"[doc-lint] REFUSED docs/p.md:3: {CAPS}" in res.stderr.split( "\n" ) and MERGED_MARK not in res.stderr
    _stage( merging, { "docs/p.md": CLEAN } )
    res = _commit( merging )
    assert res.returncode == 0 and CLEAN_LINE in res.stderr.split( "\n" ) and _commit_count( merging ) == 4
