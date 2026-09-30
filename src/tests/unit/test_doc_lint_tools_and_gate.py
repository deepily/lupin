"""
The external-tool runners, the warn-mode gate, and the pre-commit chain wrapper.

The gate's two promises are checked here: a missing tool prints a loud line, and a crash never
blocks a commit. The chain test runs the real pre-commit-chain.sh in a scratch repository.
"""

import io
import json
import os
import shutil
import subprocess
from types import SimpleNamespace

import pytest

import cosa.utils.util as cu
from cosa.repo.doc_lint import gate, tool_runners as tr, word_list
from cosa.repo.doc_lint.text_rules import Finding

WORDS = [ "not", "never", "the" ]


def _git( root, *args ):
    res = subprocess.run( [ "git", "-C", str( root ), "-c", "user.email=t@t", "-c", "user.name=t", *args ], capture_output=True, text=True )
    assert res.returncode == 0, res.stderr
    return res.stdout


@pytest.fixture
def repo( tmp_path ):
    _git( tmp_path, "init", "-q" )
    ( tmp_path / "src" / "conf" ).mkdir( parents=True )
    ( tmp_path / "src" / "conf" / "dm-tutor-lowercase-words.txt" ).write_text( "\n".join( WORDS ) + "\n", encoding="utf-8" )
    yield tmp_path
    word_list._state[ "root" ] = None
    word_list._state[ "words" ] = None


def _fake( returncode=0, stdout="", stderr="" ):
    calls = []
    def run( cmd, **kwargs ):
        calls.append( ( cmd, kwargs ) )
        return SimpleNamespace( returncode=returncode, stdout=stdout, stderr=stderr )
    run.calls = calls
    return run


@pytest.fixture
def no_tools( monkeypatch, tmp_path ):
    for var in ( "LUPIN_RUFF", "LUPIN_MARKDOWNLINT", "LUPIN_DART" ): monkeypatch.delenv( var, raising=False )
    monkeypatch.setattr( tr.shutil, "which", lambda name: None )
    return tmp_path


# ---- find_tool -------------------------------------------------------------------------------

def test_find_tool_prefers_the_env_override_then_the_tree_then_the_search_path( tmp_path, monkeypatch ):
    ( tmp_path / "bin" ).mkdir()
    in_tree = tmp_path / "bin" / "tool"
    in_tree.write_text( "x", encoding="utf-8" )
    override = tmp_path / "override"
    override.write_text( "x", encoding="utf-8" )
    monkeypatch.setattr( tr.shutil, "which", lambda name: "/on/path/" + name )
    monkeypatch.delenv( "DL_TOOL", raising=False )
    assert tr.find_tool( str( tmp_path ), [ "bin/tool" ], "tool", "DL_TOOL" ) == str( in_tree )
    assert tr.find_tool( str( tmp_path ), [ "bin/missing" ], "tool", "DL_TOOL" ) == "/on/path/tool"
    monkeypatch.setenv( "DL_TOOL", str( override ) )
    assert tr.find_tool( str( tmp_path ), [ "bin/tool" ], "tool", "DL_TOOL" ) == str( override )
    monkeypatch.setenv( "DL_TOOL", str( tmp_path / "does-not-exist" ) )
    assert tr.find_tool( str( tmp_path ), [ "bin/tool" ], "tool", "DL_TOOL" ) == str( in_tree )
    monkeypatch.setattr( tr.shutil, "which", lambda name: None )
    assert tr.find_tool( str( tmp_path ), [ "bin/missing" ], "tool", "DL_TOOL" ) is None


def test_missing_tool_warning_is_loud_and_names_what_was_not_checked():
    line = tr.missing_tool_warning( "ruff", "docstring layout rules" )
    assert line.startswith( "[doc-lint] WARNING:" ) and "SKIPPED" in line and "ruff" in line and "NOT checked" in line


# ---- ruff ------------------------------------------------------------------------------------

RUFF_JSON = json.dumps( [ { "filename": "/r/src/a.py", "code": "D205", "message": "1 blank line required", "location": { "row": 7, "column": 5 } },
                          { "filename": "/r/src/b.py", "code": "D213", "message": "summary on the second line", "location": { "row": 3, "column": 5 } } ] )


def test_run_ruff_parses_findings_with_the_rule_as_ruff_code( monkeypatch, tmp_path ):
    monkeypatch.setenv( "LUPIN_RUFF", str( tmp_path ) )
    fake = _fake( 1, RUFF_JSON )
    findings, warnings = tr.run_ruff( "/r", [ "src/a.py", "src/b.py" ], fake )
    assert warnings == []
    assert [ ( f.path, f.line, f.rule ) for f in findings ] == [ ( "src/a.py", 7, "ruff:D205" ), ( "src/b.py", 3, "ruff:D213" ) ]
    cmd = fake.calls[ 0 ][ 0 ]
    assert cmd[ 1 : 3 ] == [ "check", "--config" ] and cmd[ 3 ] == "/r/pyproject.toml" and cmd[ -2: ] == [ "src/a.py", "src/b.py" ]
    assert tr.run_ruff( "/r", [ "src/a.py" ], _fake( 0, "" ) ) == ( [], [] )


def test_run_ruff_warns_loudly_when_missing_and_when_ruff_itself_fails( no_tools, monkeypatch, tmp_path ):
    findings, warnings = tr.run_ruff( str( no_tools ), [ "a.py" ] )
    assert findings == [] and len( warnings ) == 1 and "ruff not found, SKIPPED" in warnings[ 0 ]
    assert tr.run_ruff( str( no_tools ), [] ) == ( [], [] )                       # nothing to check, nothing to warn about
    monkeypatch.setenv( "LUPIN_RUFF", str( tmp_path ) )
    findings, warnings = tr.run_ruff( "/r", [ "a.py" ], _fake( 2, "", "bad config" ) )
    assert findings == [] and "ruff failed (exit 2), SKIPPED: bad config" in warnings[ 0 ]


def test_real_ruff_output_parses_when_ruff_is_installed( tmp_path ):
    tool = tr.find_tool( cu.get_project_root(), [ ".venv/bin/ruff" ], "ruff", "LUPIN_RUFF" )
    if tool is None: pytest.skip( "ruff is not installed in this environment" )
    shutil.copy( os.path.join( cu.get_project_root(), "pyproject.toml" ), tmp_path / "pyproject.toml" )
    ( tmp_path / "a.py" ).write_text( 'def f():\n    """Summary.\n    Description without a blank line.\n    """\n', encoding="utf-8" )
    findings, warnings = tr.run_ruff( str( tmp_path ), [ "a.py" ] )
    assert warnings == [] and "ruff:D205" in [ f.rule for f in findings ] and findings[ 0 ].path == "a.py"


# ---- markdownlint ----------------------------------------------------------------------------

MDL_OUT = "a.md:12 error MD040/fenced-code-language Fenced code blocks should have a language specified [Context: \"```\"]\nb.md:3:5 error MD051/link-fragments Link fragments should be valid\nSummary: 2 error(s)\n"


def test_run_markdownlint_parses_lines_with_and_without_columns( monkeypatch, tmp_path ):
    monkeypatch.setenv( "LUPIN_MARKDOWNLINT", str( tmp_path ) )
    fake = _fake( 1, "", MDL_OUT )
    findings, warnings = tr.run_markdownlint( "/r", [ "a.md", "b.md" ], fake )
    assert warnings == [] and [ ( f.path, f.line, f.rule ) for f in findings ] == [ ( "a.md", 12, "markdownlint:MD040/fenced-code-language" ), ( "b.md", 3, "markdownlint:MD051/link-fragments" ) ]
    assert fake.calls[ 0 ][ 0 ][ 1 : ] == [ "--no-globs", "a.md", "b.md" ]
    assert tr.run_markdownlint( "/r", [ "a.md" ], _fake( 0 ) ) == ( [], [] )


def test_run_markdownlint_warns_loudly_when_missing_and_when_the_tool_fails( no_tools, monkeypatch, tmp_path ):
    findings, warnings = tr.run_markdownlint( str( no_tools ), [ "a.md" ] )
    assert findings == [] and "markdownlint-cli2 not found, SKIPPED" in warnings[ 0 ]
    assert tr.run_markdownlint( str( no_tools ), [] ) == ( [], [] )
    monkeypatch.setenv( "LUPIN_MARKDOWNLINT", str( tmp_path ) )
    findings, warnings = tr.run_markdownlint( "/r", [ "a.md" ], _fake( 2, "", "config error" ) )
    assert findings == [] and "exit 2), SKIPPED: config error" in warnings[ 0 ]


def test_real_markdownlint_output_parses_when_the_tool_is_installed( tmp_path ):
    tool = tr.find_tool( cu.get_project_root(), [ "node_modules/.bin/markdownlint-cli2" ], "markdownlint-cli2", "LUPIN_MARKDOWNLINT" )
    if tool is None: pytest.skip( "markdownlint-cli2 is not installed in this environment" )
    ( tmp_path / "a.md" ).write_text( "# T\n\n```\ncode\n```\n", encoding="utf-8" )
    findings, warnings = tr.run_markdownlint( str( tmp_path ), [ "a.md" ] )
    assert warnings == [] and [ ( f.path, f.line ) for f in findings if f.rule.startswith( "markdownlint:MD040" ) ] == [ ( "a.md", 3 ) ]


# ---- dart analyze ----------------------------------------------------------------------------

DART_OUT = ( "INFO|LINT|public_member_api_docs|/r/lib/a.dart|10|7|3|Missing documentation for a public member.\n"
             "ERROR|COMPILE_TIME_ERROR|URI_DOES_NOT_EXIST|/r/lib/a.dart|1|8|22|Target of URI doesn't exist.\n"
             "INFO|LINT|slash_for_doc_comments|/r/lib/b.dart|4|1|2|Use /// | not /** */.\n" )


def test_run_dart_analyze_keeps_documentation_diagnostics_and_ignores_the_rest( monkeypatch, tmp_path ):
    monkeypatch.setenv( "LUPIN_DART", str( tmp_path ) )
    fake = _fake( 3, DART_OUT )
    findings, warnings = tr.run_dart_analyze( "/r", "lib", fake )
    assert warnings == []
    assert [ ( f.path, f.line, f.rule ) for f in findings ] == [ ( "lib/a.dart", 10, "dart:public_member_api_docs" ), ( "lib/b.dart", 4, "dart:slash_for_doc_comments" ) ]
    assert findings[ 1 ].message == "Use /// | not /** */."
    assert fake.calls[ 0 ][ 0 ][ 1 : ] == [ "analyze", "--format=machine", "lib" ]


def test_run_dart_analyze_warns_when_dart_is_missing_or_crashes( no_tools, monkeypatch, tmp_path ):
    findings, warnings = tr.run_dart_analyze( str( no_tools ), "lib" )
    assert findings == [] and "dart not found, SKIPPED" in warnings[ 0 ]
    monkeypatch.setenv( "LUPIN_DART", str( tmp_path ) )
    findings, warnings = tr.run_dart_analyze( "/r", "lib", _fake( 64, "", "usage" ) )
    assert findings == [] and "exit 64), SKIPPED: usage" in warnings[ 0 ]


# ---- gate ------------------------------------------------------------------------------------

def _stage( repo, files ):
    for rel, text in files.items():
        full = repo / rel
        full.parent.mkdir( parents=True, exist_ok=True )
        full.write_text( text, encoding="utf-8" )
    _git( repo, "add", "-f", *files )


def _no_external( monkeypatch ):
    monkeypatch.setattr( gate, "run_ruff", lambda root, paths: ( [], [] ) )
    monkeypatch.setattr( gate, "run_markdownlint", lambda root, paths: ( [], [] ) )


def test_staged_paths_lists_added_and_modified_files_in_scope_only( repo ):
    _stage( repo, { "src/a.py": "x\n", "src/tests/t.py": "x\n", "docs/b.md": "x\n", "src/c.txt": "x\n" } )
    assert gate.staged_paths( str( repo ) ) == [ "docs/b.md", "src/a.py", "src/c.txt" ]


def test_staged_paths_and_staged_source_and_toplevel_name_git_errors( tmp_path ):
    with pytest.raises( RuntimeError, match="not a git working tree" ):
        gate.git_toplevel( str( tmp_path ) )
    with pytest.raises( RuntimeError, match="git diff --cached failed" ):
        gate.staged_paths( str( tmp_path ) )
    with pytest.raises( RuntimeError, match="git show" ):
        gate.staged_source( str( tmp_path ), "nope.py" )


def test_gate_reports_findings_on_staged_lines_only_and_reads_the_index_not_the_disk( repo, monkeypatch ):
    _no_external( monkeypatch )
    _git( repo, "commit", "-q", "--allow-empty", "-m", "base" )
    source = 'def f():\n    """\n    Return it.\n\n    This is NOT fine.\n    """\n'
    _stage( repo, { "src/a.py": source, "docs/p.md": "Line one is NOT fine.\n" } )
    ( repo / "src" / "a.py" ).write_text( source + "\n# NEVER committed\n", encoding="utf-8" )     # unstaged edit must not be linted
    err = io.StringIO()
    assert gate.main( [ "--repo-root", str( repo ) ], err ) == 0
    text = err.getvalue()
    assert "[doc-lint] src/a.py:5: caps: ALL-CAPS word NOT" in text and "[doc-lint] docs/p.md:1: caps: ALL-CAPS word NOT" in text
    assert "NEVER" not in text and "2 findings on staged lines (warn mode, commit allowed)" in text
    assert gate.main( [ "--repo-root", str( repo ), "--blocking" ], io.StringIO() ) == 1


def test_gate_lints_what_is_staged_even_when_the_disk_copy_was_cleaned_afterwards( repo, monkeypatch ):
    _no_external( monkeypatch )
    _stage( repo, { "docs/p.md": "Line one is NOT fine.\n" } )
    ( repo / "docs" / "p.md" ).write_text( "Line one is fine.\n", encoding="utf-8" )           # fixed on disk, not re-staged
    err = io.StringIO()
    gate.main( [ "--repo-root", str( repo ) ], err )
    assert "docs/p.md:1: caps: ALL-CAPS word NOT" in err.getvalue()
    bad = 'def f():\n    """\n    Return it.\n\n    This is NOT fine.\n    """\n'
    _stage( repo, { "src/a.py": bad } )
    ( repo / "src" / "a.py" ).write_text( bad.replace( "NOT ", "" ), encoding="utf-8" )
    err = io.StringIO()
    gate.main( [ "--repo-root", str( repo ) ], err )
    assert "src/a.py:5: caps: ALL-CAPS word NOT" in err.getvalue()


def test_gate_drops_findings_on_lines_the_commit_did_not_touch( repo, monkeypatch ):
    _no_external( monkeypatch )
    old = "line one\nThis is NOT fine.\n"
    _stage( repo, { "docs/p.md": old } )
    _git( repo, "commit", "-q", "-m", "base" )
    _stage( repo, { "docs/p.md": old + "a new clean line\n" } )
    err = io.StringIO()
    assert gate.main( [ "--repo-root", str( repo ), "--blocking" ], err ) == 0
    assert "0 findings on staged lines (blocking)" in err.getvalue()


def test_gate_prints_every_missing_tool_warning_and_includes_tool_findings( repo, monkeypatch ):
    monkeypatch.setattr( gate, "run_ruff", lambda root, paths: ( [ Finding( "src/a.py", 1, "ruff:D205", "m" ) ], [ "[doc-lint] WARNING: ruff not found, SKIPPED: x were NOT checked" ] ) )
    monkeypatch.setattr( gate, "run_markdownlint", lambda root, paths: ( [], [ "[doc-lint] WARNING: markdownlint-cli2 not found, SKIPPED: y were NOT checked" ] ) )
    _stage( repo, { "src/a.py": "x = 1\n", "docs/p.md": "clean\n", "notes.txt": "NOT linted\n" } )
    err = io.StringIO()
    assert gate.main( [ "--repo-root", str( repo ) ], err ) == 0
    text = err.getvalue()
    assert "ruff not found, SKIPPED" in text and "markdownlint-cli2 not found, SKIPPED" in text and "src/a.py:1: ruff:D205" in text


def test_gate_allows_the_commit_and_says_so_loudly_when_it_crashes( repo, monkeypatch ):
    def boom( root ): raise ValueError( "injected crash" )
    monkeypatch.setattr( gate, "collect", boom )
    err = io.StringIO()
    assert gate.main( [ "--repo-root", str( repo ), "--blocking" ], err ) == 0
    assert "[doc-lint] GATE CRASHED, commit allowed: ValueError: injected crash" in err.getvalue()


def test_gate_allows_the_commit_outside_a_repository( tmp_path ):
    err = io.StringIO()
    assert gate.main( [ "--repo-root", str( tmp_path ) ], err ) == 0
    assert "GATE CRASHED, commit allowed: RuntimeError" in err.getvalue()


# ---- the chain wrapper -----------------------------------------------------------------------

CHAIN = os.path.join( cu.get_project_root(), "src", "scripts", "pre-commit-chain.sh" )


def _run_chain( repo, env_extra=None ):
    env = { **os.environ, "PLANNING_IS_PROMPTING_ROOT": "", **( env_extra or {} ) }
    return subprocess.run( [ "bash", CHAIN ], cwd=repo, capture_output=True, text=True, env=env )


def test_the_chain_runs_the_gate_in_warn_mode_and_still_exits_zero_with_findings( repo ):
    os.symlink( os.path.join( cu.get_project_root(), "src", "cosa" ), repo / "src" / "cosa" )
    _stage( repo, { "docs/p.md": "This is NOT fine.\n" } )
    res = _run_chain( repo, { "LUPIN_RUFF": "", "LUPIN_MARKDOWNLINT": "" } )
    assert res.returncode == 0
    assert "[doc-lint] docs/p.md:1: caps: ALL-CAPS word NOT" in res.stderr and "commit allowed" in res.stderr


def test_the_chain_allows_the_commit_when_the_gate_process_itself_fails( repo ):
    pkg = repo / "src" / "cosa" / "repo" / "doc_lint"
    pkg.mkdir( parents=True )
    for d in ( repo / "src" / "cosa", repo / "src" / "cosa" / "repo", pkg ): ( d / "__init__.py" ).write_text( "", encoding="utf-8" )
    ( pkg / "gate.py" ).write_text( "raise SystemExit( 7 )\n", encoding="utf-8" )
    res = _run_chain( repo )
    assert res.returncode == 0
    assert "doc-lint gate exited 7, commit allowed (warn mode)" in res.stderr


def test_the_chain_gate_does_not_depend_on_planning_is_prompting_root( repo ):
    os.symlink( os.path.join( cu.get_project_root(), "src", "cosa" ), repo / "src" / "cosa" )
    _stage( repo, { "docs/p.md": "clean text\n" } )
    res = _run_chain( repo )
    assert "SKIPPED rnd-guard" in res.stderr                      # the other gate is skipped without the variable
    assert "0 findings on staged lines" in res.stderr              # this one ran anyway
