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
    tool = tr.find_tool( cu.get_project_root(), tr.RUFF_RELATIVE, "ruff", "LUPIN_RUFF" )
    if tool is None: pytest.skip( "ruff is not installed in this environment" )
    shutil.copy( os.path.join( cu.get_project_root(), "pyproject.toml" ), tmp_path / "pyproject.toml" )
    ( tmp_path / "a.py" ).write_text( 'def f():\n    """Summary.\n    Description without a blank line.\n    """\n', encoding="utf-8" )
    findings, warnings = tr.run_ruff( str( tmp_path ), [ "a.py" ] )
    assert warnings == [] and "ruff:D205" in [ f.rule for f in findings ] and findings[ 0 ].path == "a.py"


def test_run_ruff_with_sources_checks_each_staged_text_through_stdin( monkeypatch, tmp_path ):
    monkeypatch.setenv( "LUPIN_RUFF", str( tmp_path ) )
    one = json.dumps( [ { "filename": "src/a.py", "code": "D205", "message": "m", "location": { "row": 4, "column": 1 } } ] )
    fake = _fake( 1, one )
    findings, warnings = tr.run_ruff( "/r", [ "src/a.py", "src/b.py" ], fake, sources={ "src/a.py": "A TEXT", "src/b.py": "B TEXT" } )
    assert warnings == [] and [ ( f.path, f.line ) for f in findings ] == [ ( "src/a.py", 4 ), ( "src/a.py", 4 ) ]
    assert [ ( c[ 0 ][ -3: ], c[ 1 ][ "input" ] ) for c in fake.calls ] == [ ( [ "--stdin-filename", "src/a.py", "-" ], "A TEXT" ), ( [ "--stdin-filename", "src/b.py", "-" ], "B TEXT" ) ]
    failing = tr.run_ruff( "/r", [ "src/a.py" ], _fake( 2, "", "boom" ), sources={ "src/a.py": "x" } )
    assert failing[ 0 ] == [] and "SKIPPED: boom" in failing[ 1 ][ 0 ]


def test_real_ruff_reads_the_staged_text_not_the_disk_copy_when_installed( repo ):
    if tr.find_tool( cu.get_project_root(), tr.RUFF_RELATIVE, "ruff", "LUPIN_RUFF" ) is None: pytest.skip( "ruff is not installed in this environment" )
    shutil.copy( os.path.join( cu.get_project_root(), "pyproject.toml" ), repo / "pyproject.toml" )
    bad = 'def f():\n    """Summary.\n    Description without a blank line.\n    """\n'
    _stage( repo, { "src/a.py": bad } )
    ( repo / "src" / "a.py" ).write_text( 'def f():\n    """Summary."""\n', encoding="utf-8" )       # fixed on disk, not staged
    err = io.StringIO()
    gate.main( [ "--repo-root", str( repo ) ], err )
    assert "src/a.py:2: ruff:D205" in err.getvalue()


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
    monkeypatch.setattr( gate, "run_ruff", lambda root, paths, sources=None: ( [], [] ) )
    monkeypatch.setattr( gate, "run_markdownlint", lambda root, paths, sources=None: ( [], [] ) )


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
    _stage( repo, { "src/lupin_mcp/a.py": source, "docs/p.md": "Line one is NOT fine.\n" } )
    ( repo / "src" / "lupin_mcp" / "a.py" ).write_text( source + "\n# NEVER committed\n", encoding="utf-8" )     # unstaged edit must not be linted
    err = io.StringIO()
    assert gate.main( [ "--repo-root", str( repo ) ], err ) == 0
    text = err.getvalue()
    assert "[doc-lint] src/lupin_mcp/a.py:5: caps: ALL-CAPS word NOT" in text and "[doc-lint] docs/p.md:1: caps: ALL-CAPS word NOT" in text
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
    _stage( repo, { "src/lupin_mcp/a.py": bad } )
    ( repo / "src" / "lupin_mcp" / "a.py" ).write_text( bad.replace( "NOT ", "" ), encoding="utf-8" )
    err = io.StringIO()
    gate.main( [ "--repo-root", str( repo ) ], err )
    assert "src/lupin_mcp/a.py:5: caps: ALL-CAPS word NOT" in err.getvalue()


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
    monkeypatch.setattr( gate, "run_ruff", lambda root, paths, sources=None: ( [ Finding( "src/lupin_mcp/a.py", 1, "ruff:D205", "m" ) ], [ "[doc-lint] WARNING: ruff not found, SKIPPED: x were NOT checked" ] ) )
    monkeypatch.setattr( gate, "run_markdownlint", lambda root, paths: ( [], [ "[doc-lint] WARNING: markdownlint-cli2 not found, SKIPPED: y were NOT checked" ] ) )
    _stage( repo, { "src/lupin_mcp/a.py": "x = 1\n", "docs/p.md": "clean\n", "notes.txt": "NOT linted\n" } )
    err = io.StringIO()
    assert gate.main( [ "--repo-root", str( repo ) ], err ) == 0
    text = err.getvalue()
    assert "ruff not found, SKIPPED" in text and "markdownlint-cli2 not found, SKIPPED" in text and "src/lupin_mcp/a.py:1: ruff:D205" in text


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


# ---- the blocking allowlist ------------------------------------------------------------------

def _doc( line ):
    return f'def f():\n    """\n    Return it.\n\n    {line}\n    """\n'


KIND_CASES = [
    ( "dated-banner",     "Added on 2026-01-02 for the parser." ),
    ( "iso-date",         "The version was cut on 2026-01-02." ),
    ( "agent-imperative", "You must call this first." ),
    ( "bare-ref",         "Tracked in row 8dbe659a." ),
    ( "bare-ref",         "Introduced in 91574fce for speed." ),
]


DESTINATION = {
    "dated-banner"     : "the commit message or the Decisions Log",
    "iso-date"         : "the commit message or the Decisions Log",
    "bare-ref"         : "the commit message, the task row or a post-game",
    "agent-imperative" : "a prompt or skill file; the docstring states what the code does",
}


def test_the_allowlist_ships_empty_so_merging_the_gate_changes_nobodys_commits():
    assert gate.BLOCKING_PACKAGES == ()


@pytest.mark.parametrize( "rule,line", KIND_CASES )
def test_each_mechanical_kind_on_an_untouched_line_is_refused_when_its_package_is_listed( repo, monkeypatch, rule, line ):
    _no_external( monkeypatch )
    monkeypatch.setattr( gate, "BLOCKING_PACKAGES", ( "src/lupin_mcp/pkg/", ) )
    old = _doc( line )
    _stage( repo, { "src/lupin_mcp/pkg/a.py": old } )
    _git( repo, "commit", "-q", "-m", "base" )
    _stage( repo, { "src/lupin_mcp/pkg/a.py": old + "\nx = 1\n" } )                      # the docstring line is not in the diff
    err = io.StringIO()
    assert gate.main( [ "--repo-root", str( repo ) ], err ) == gate.REFUSAL_EXIT
    text = err.getvalue()
    refusal = [ ln for ln in text.split( "\n" ) if ln.startswith( f"[doc-lint] REFUSED src/lupin_mcp/pkg/a.py:5: {rule}: " ) ]
    assert len( refusal ) == 1 and refusal[ 0 ].endswith( f"; this history belongs in {DESTINATION[ rule ]}" )
    assert "commit REFUSED" in text and text.count( f"REFUSED src/lupin_mcp/pkg/a.py:5: {rule}:" ) == 1


@pytest.mark.parametrize( "rule,line", KIND_CASES )
def test_the_same_line_in_an_unlisted_package_is_only_warned_and_only_when_touched( repo, monkeypatch, rule, line ):
    _no_external( monkeypatch )
    monkeypatch.setattr( gate, "BLOCKING_PACKAGES", ( "src/lupin_mcp/other/", ) )
    old = _doc( line )
    _stage( repo, { "src/lupin_mcp/pkg/a.py": old } )
    err = io.StringIO()
    assert gate.main( [ "--repo-root", str( repo ) ], err ) == 0                  # new file: every line is touched, so it warns
    assert f"[doc-lint] src/lupin_mcp/pkg/a.py:5: {rule}: " in err.getvalue() and "REFUSED" not in err.getvalue()
    _git( repo, "commit", "-q", "-m", "base" )
    _stage( repo, { "src/lupin_mcp/pkg/a.py": old + "\nx = 1\n" } )
    err = io.StringIO()
    assert gate.main( [ "--repo-root", str( repo ) ], err ) == 0
    assert "0 findings on staged lines (warn mode, commit allowed)" in err.getvalue()


def test_a_refused_finding_on_a_touched_line_is_printed_once_as_a_refusal_not_also_as_a_warning( repo, monkeypatch ):
    _no_external( monkeypatch )
    monkeypatch.setattr( gate, "BLOCKING_PACKAGES", ( "src/lupin_mcp/pkg/", ) )
    _stage( repo, { "src/lupin_mcp/pkg/a.py": _doc( "The version was cut on 2026-01-02." ) } )   # a new file: the line is touched
    err = io.StringIO()
    assert gate.main( [ "--repo-root", str( repo ) ], err ) == gate.REFUSAL_EXIT
    assert "[doc-lint] src/lupin_mcp/pkg/a.py:5: iso-date" not in err.getvalue() and "REFUSED src/lupin_mcp/pkg/a.py:5: iso-date" in err.getvalue()


def test_a_clean_file_passes_whether_its_package_is_listed_or_not( repo, monkeypatch ):
    _no_external( monkeypatch )
    _stage( repo, { "src/lupin_mcp/pkg/a.py": _doc( "Return the thing." ), "docs/p.md": "A clean line.\n" } )
    for packages in ( ( "src/lupin_mcp/pkg/", "docs/" ), () ):
        monkeypatch.setattr( gate, "BLOCKING_PACKAGES", packages )
        err = io.StringIO()
        assert gate.main( [ "--repo-root", str( repo ) ], err ) == 0
        assert "0 findings on staged lines (warn mode, commit allowed)" in err.getvalue()


def test_markdown_in_a_listed_package_is_refused_on_an_untouched_line( repo, monkeypatch ):
    _no_external( monkeypatch )
    monkeypatch.setattr( gate, "BLOCKING_PACKAGES", ( "docs/", ) )
    _stage( repo, { "docs/p.md": "Measured 2026-01-02 here.\n" } )
    _git( repo, "commit", "-q", "-m", "base" )
    _stage( repo, { "docs/p.md": "Measured 2026-01-02 here.\nA new clean line.\n" } )
    err = io.StringIO()
    assert gate.main( [ "--repo-root", str( repo ) ], err ) == gate.REFUSAL_EXIT
    assert "REFUSED docs/p.md:1: dated-banner" in err.getvalue()


def test_an_incident_story_and_the_non_id_references_are_not_refused( repo, monkeypatch ):
    _no_external( monkeypatch )
    monkeypatch.setattr( gate, "BLOCKING_PACKAGES", ( "src/lupin_mcp/pkg/", ) )
    story = "The parser once dropped a column after a bad merge, so the loader now checks the width. See section 4 of this module, ruling 3, AC4 and D4."
    _stage( repo, { "src/lupin_mcp/pkg/a.py": _doc( story ) } )
    err = io.StringIO()
    assert gate.main( [ "--repo-root", str( repo ) ], err ) == 0
    assert "REFUSED" not in err.getvalue()


def test_is_mechanical_sorts_the_history_kinds_from_the_rest():
    def f( rule, message="m" ): return Finding( "a.py", 1, rule, message )
    for rule in ( "dated-banner", "iso-date", "agent-imperative" ): assert gate.is_mechanical( f( rule ) )
    assert gate.is_mechanical( f( "bare-ref", "bare reference 'row 8dbe659a'" ) )
    assert gate.is_mechanical( f( "bare-ref", "bare reference '91574fce'" ) )
    assert not gate.is_mechanical( f( "bare-ref", "bare reference 'ruling 3'" ) )
    assert not gate.is_mechanical( f( "bare-ref", "bare reference 'AC4'" ) )
    assert not gate.is_mechanical( f( "bare-ref", "section reference '\u00a74' has no path" ) )
    assert not gate.is_mechanical( f( "caps" ) ) and not gate.is_mechanical( f( "ruff:D205" ) )


def test_in_blocking_package_matches_a_directory_prefix_only():
    assert gate.in_blocking_package( "src/lupin_mcp/pkg/a.py", ( "src/x/", "src/lupin_mcp/pkg/" ) )
    assert not gate.in_blocking_package( "src/pkg2/a.py", ( "src/lupin_mcp/pkg/", ) ) and not gate.in_blocking_package( "src/lupin_mcp/pkg/a.py", () )


def test_the_real_gate_in_a_listed_package_makes_the_real_chain_refuse_the_commit( repo ):
    pkg = repo / "src" / "cosa" / "repo"
    shutil.copytree( os.path.join( cu.get_project_root(), "src", "cosa", "repo", "doc_lint" ), pkg / "doc_lint", ignore=shutil.ignore_patterns( "__pycache__" ) )
    for d in ( repo / "src" / "cosa", pkg ): ( d / "__init__.py" ).write_text( "", encoding="utf-8" )
    gate_file = pkg / "doc_lint" / "gate.py"
    source    = gate_file.read_text( encoding="utf-8" )
    assert source.count( "BLOCKING_PACKAGES = ()" ) == 1                   # the copy gets the one listed package, nothing else changes
    gate_file.write_text( source.replace( "BLOCKING_PACKAGES = ()", 'BLOCKING_PACKAGES = ( "src/lupin_mcp/pkg/", )' ), encoding="utf-8" )
    _stage( repo, { "src/lupin_mcp/pkg/a.py": _doc( "Added on 2026-01-02 for the parser." ) } )
    res = _run_chain( repo, { "LUPIN_RUFF": "", "LUPIN_MARKDOWNLINT": "" } )
    assert res.returncode == 1
    assert "[doc-lint] REFUSED src/lupin_mcp/pkg/a.py:5: dated-banner" in res.stderr and "doc-lint gate REFUSED the commit" in res.stderr


def test_the_chain_refuses_the_commit_on_exit_three_and_allows_every_other_gate_failure( repo ):
    pkg = repo / "src" / "cosa" / "repo" / "doc_lint"
    pkg.mkdir( parents=True )
    for d in ( repo / "src" / "cosa", repo / "src" / "cosa" / "repo", pkg ): ( d / "__init__.py" ).write_text( "", encoding="utf-8" )
    ( pkg / "gate.py" ).write_text( "raise SystemExit( 3 )\n", encoding="utf-8" )
    res = _run_chain( repo )
    assert res.returncode == 1 and "doc-lint gate REFUSED the commit" in res.stderr


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


# ---- the swept-scope refusal -----------------------------------------------------------------

SWEPT_CAPS = _doc( "This is NOT fine." )


def _gate( repo, *extra ):
    err = io.StringIO()
    return gate.main( [ "--repo-root", str( repo ), *extra ], err ), err.getvalue()


def test_a_swept_file_with_a_capitals_docstring_is_refused_and_the_message_names_the_fix( repo, monkeypatch ):
    _no_external( monkeypatch )
    _stage( repo, { "src/pkg/a.py": SWEPT_CAPS } )
    rc, text = _gate( repo )
    assert rc == gate.REFUSAL_EXIT == 3
    line = [ ln for ln in text.split( "\n" ) if ln.startswith( "[doc-lint] REFUSED src/pkg/a.py:5: caps: ALL-CAPS word NOT" ) ]
    assert len( line ) == 1
    assert "line: 'This is NOT fine.'" in line[ 0 ] and f"fix: {gate.FIX_HOME[ 'caps' ]}" in line[ 0 ]
    assert "to waive, end the line with: doc-lint: waive caps -- <reason>" in line[ 0 ]
    assert "1 refusals, commit REFUSED" in text


def test_the_refusal_covers_a_finding_on_a_line_the_commit_did_not_touch( repo, monkeypatch ):
    _no_external( monkeypatch )
    _stage( repo, { "src/pkg/a.py": SWEPT_CAPS } )
    _git( repo, "commit", "-q", "--no-verify", "-m", "base" )
    _stage( repo, { "src/pkg/a.py": SWEPT_CAPS + "\nx = 1\n" } )
    rc, text = _gate( repo )
    assert rc == 3 and "REFUSED src/pkg/a.py:5: caps" in text


def test_a_finding_from_a_rule_other_than_caps_is_refused_with_that_rules_home( repo, monkeypatch ):
    _no_external( monkeypatch )
    _stage( repo, { "src/pkg/a.py": _doc( "word " * 30 + "end." ) } )
    rc, text = _gate( repo )
    assert rc == 3 and "REFUSED src/pkg/a.py:5: sentence-length" in text and f"fix: {gate.FIX_HOME[ 'sentence-length' ]}" in text


def test_every_rule_the_docstring_lint_can_emit_has_a_named_home():
    for rule in ( "summary-length", "preface-length", "sentence-length", "caps", "glyph", "tic", "bare-ref", "dated-banner", "iso-date", "agent-imperative", "docstring-length", "dead-design" ):
        assert rule in gate.FIX_HOME and gate.FIX_HOME[ rule ]


def test_the_refusal_line_cuts_a_long_text_and_falls_back_for_an_unnamed_rule():
    f    = Finding( "src/a.py", 7, "brand-new-rule", "m" )
    line = gate.swept_refusal_line( f, "  " + "x" * 200, "none" )
    assert "x" * gate.TEXT_LIMIT + "...'" in line and "x" * ( gate.TEXT_LIMIT + 1 ) not in line
    assert "fix: plain wording that states what the code does" in line and "gives no reason" not in line
    assert "a waiver marker is on this line but gives no reason, so it waives nothing" in gate.swept_refusal_line( f, "x", "no-reason" )


@pytest.mark.parametrize( "path,swept", [
    ( "src/pkg/a.py",                 True ),
    ( "src/cosa/deep/er/nest/a.py",   True ),
    ( "brand_new_package/a.py",       True ),
    ( "docker/lupin/scripts/a.py",    True ),
    ( "src/lupin_mcp/a.py",           False ),
    ( "src/lupin_mcp/sub/dir/a.py",   False ),
    ( "src/lupin_mcp_extra/a.py",     True ),
    ( "src/tests/unit/a.py",          False ),
    ( "src/pkg/test_a.py",            False ),
    ( "src/pkg/conftest.py",          False ),
    ( "src/rnd/v1/a.py",              False ),
    ( "src/pkg/.venv/lib/a.py",       False ),
    ( "src/pkg/a.md",                 False ),
    ( "history.md",                   False ),
    ( "src/pkg/a.pyi",                False ),
] )
def test_the_swept_predicate_matches_on_the_path_alone( path, swept ):
    assert gate.is_swept( path ) is swept


def test_files_outside_the_swept_scope_are_warned_not_refused_and_the_tracking_files_commit( repo, monkeypatch ):
    _no_external( monkeypatch )
    md = "Measured 2026-01-02. This is NOT fine. Row 8dbe659a.\n"
    _stage( repo, {
        "src/lupin_mcp/a.py"  : SWEPT_CAPS,
        "src/tests/t.py"      : SWEPT_CAPS,
        "src/pkg/test_b.py"   : SWEPT_CAPS,
        "src/rnd/doc.py"      : SWEPT_CAPS,
        "history.md"          : md,
        "TODO.md"             : md,
    } )
    rc, text = _gate( repo )
    assert rc == 0 and "REFUSED" not in text
    assert "src/lupin_mcp/a.py:5: caps" in text and "history.md:1:" in text and "TODO.md:1:" in text
    assert "swept scope: 0 files checked, 0 docstrings checked, 0 findings, 0 waivers honoured, 0 unparsed" in text


def test_a_rename_is_refused_and_a_deletion_is_not( repo, monkeypatch ):
    _no_external( monkeypatch )
    _stage( repo, { "src/pkg/old.py": SWEPT_CAPS } )
    _git( repo, "commit", "-q", "--no-verify", "-m", "base" )
    _git( repo, "mv", "src/pkg/old.py", "src/pkg/new.py" )
    rc, text = _gate( repo )
    assert rc == 3 and "REFUSED src/pkg/new.py:5: caps" in text
    _git( repo, "reset", "-q", "--hard" )
    _git( repo, "rm", "-q", "src/pkg/old.py" )
    rc, text = _gate( repo )
    assert rc == 0 and "REFUSED" not in text and "0 files checked" in text


def test_a_swept_file_that_does_not_parse_is_refused_counted_and_cannot_be_waived( repo, monkeypatch ):
    _no_external( monkeypatch )
    _stage( repo, { "src/pkg/a.py": 'def f(:\n    """This is NOT fine.  doc-lint: waive parse-error -- trying"""\n', "src/pkg/b.py": SWEPT_CAPS.replace( "NOT", "not" ) } )
    rc, text = _gate( repo )
    assert rc == 3
    assert "REFUSED src/pkg/a.py:1: parse-error: does not parse:" in text and "this cannot be waived" in text
    assert "[doc-lint] src/pkg/a.py:1: parse-error: does not parse" not in text
    assert "2 files checked, 1 docstrings checked, 0 findings, 0 waivers honoured, 1 unparsed" in text


def test_a_file_with_a_byte_order_mark_is_read_like_any_other( repo, monkeypatch ):
    _no_external( monkeypatch )
    _stage( repo, { "src/pkg/a.py": SWEPT_CAPS } )
    ( repo / "src" / "pkg" / "a.py" ).write_bytes( b"\xef\xbb\xbf" + SWEPT_CAPS.encode( "utf-8" ) )
    _git( repo, "add", "-f", "src/pkg/a.py" )
    rc, text = _gate( repo )
    assert rc == 3 and "REFUSED src/pkg/a.py:5: caps" in text and "parse-error" not in text and "0 unparsed" in text
    ( repo / "src" / "pkg" / "a.py" ).write_bytes( b"\xef\xbb\xbf" + _doc( "Return it." ).encode( "utf-8" ) )
    _git( repo, "add", "-f", "src/pkg/a.py" )
    rc, text = _gate( repo )
    assert rc == 0 and "1 files checked, 1 docstrings checked, 0 findings" in text and "0 unparsed" in text


def test_a_waiver_with_a_reason_is_honoured_and_counted( repo, monkeypatch ):
    _no_external( monkeypatch )
    _stage( repo, { "src/pkg/a.py": _doc( "This is NOT fine.  doc-lint: waive caps -- the capitals are quoted from the SQL standard" ) } )
    rc, text = _gate( repo )
    assert rc == 0 and "REFUSED" not in text
    assert "1 files checked, 1 docstrings checked, 1 findings, 1 waivers honoured, 0 unparsed" in text
    assert "src/pkg/a.py:5: caps" not in text


def test_a_waiver_after_the_closing_quotes_on_a_one_line_docstring_is_honoured( repo, monkeypatch ):
    _no_external( monkeypatch )
    _stage( repo, { "src/pkg/a.py": 'def f():\n    """This is NOT fine.  doc-lint: waive caps -- SQL"""\n' } )
    rc, text = _gate( repo )
    assert rc == 0 and "1 waivers honoured" in text


def test_a_waiver_without_a_reason_does_not_waive_and_the_gate_says_so( repo, monkeypatch ):
    _no_external( monkeypatch )
    for marker in ( "doc-lint: waive caps", "doc-lint: waive caps -- ", 'doc-lint: waive caps -- "', "doc-lint: waive caps -- -", "doc-lint: waive caps -- n/a", "doc-lint: waive caps -- ok" ):
        _stage( repo, { "src/pkg/a.py": _doc( f"This is NOT fine.  {marker}" ) } )
        rc, text = _gate( repo )
        assert rc == 3, marker
        assert "REFUSED src/pkg/a.py:5: caps" in text and "gives no reason, so it waives nothing" in text and "0 waivers honoured" in text


def test_a_waiver_that_names_a_different_rule_waives_nothing( repo, monkeypatch ):
    _no_external( monkeypatch )
    _stage( repo, { "src/pkg/a.py": _doc( "This is NOT fine.  doc-lint: waive tic -- wrong rule" ) } )
    rc, text = _gate( repo )
    assert rc == 3 and "REFUSED src/pkg/a.py:5: caps" in text and "gives no reason" not in text


def test_a_waiver_on_another_line_does_not_cover_the_finding( repo, monkeypatch ):
    _no_external( monkeypatch )
    _stage( repo, { "src/pkg/a.py": 'def f():\n    """\n    Return it.\n\n    This is NOT fine.\n    doc-lint: waive caps -- next line\n    """\n' } )
    rc, text = _gate( repo )
    assert rc == 3 and "REFUSED src/pkg/a.py:5: caps" in text


def test_a_clean_swept_file_prints_the_denominator_and_commits( repo, monkeypatch ):
    _no_external( monkeypatch )
    _stage( repo, { "src/pkg/a.py": _doc( "Return the thing." ), "src/pkg/b.py": _doc( "Return the other thing." ) } )
    rc, text = _gate( repo )
    assert rc == 0 and "swept scope: 2 files checked, 2 docstrings checked, 0 findings, 0 waivers honoured, 0 unparsed" in text


def test_a_finding_already_refused_by_a_listed_package_is_printed_once( repo, monkeypatch ):
    _no_external( monkeypatch )
    monkeypatch.setattr( gate, "BLOCKING_PACKAGES", ( "src/pkg/", ) )
    _stage( repo, { "src/pkg/a.py": _doc( "The version was cut on 2026-01-02." ) } )
    rc, text = _gate( repo )
    assert rc == 3 and text.count( "REFUSED src/pkg/a.py:5: iso-date" ) == 1 and "1 refusals" in text


def test_a_crash_still_allows_the_commit_with_the_loud_line_even_for_a_swept_file( repo, monkeypatch ):
    _stage( repo, { "src/pkg/a.py": SWEPT_CAPS } )
    monkeypatch.setattr( gate.docstring_lint, "lint_source", lambda *a, **k: ( _ for _ in () ).throw( ValueError( "linter crash" ) ) )
    rc, text = _gate( repo )
    assert rc == 0 and "[doc-lint] GATE CRASHED, commit allowed: ValueError: linter crash" in text


def test_the_real_chain_refuses_a_seeded_swept_commit_and_names_the_waiver( repo ):
    os.symlink( os.path.join( cu.get_project_root(), "src", "cosa" ), repo / "src" / "cosa" )
    _stage( repo, { "src/pkg/a.py": SWEPT_CAPS } )
    res = _run_chain( repo, { "LUPIN_RUFF": "", "LUPIN_MARKDOWNLINT": "" } )
    assert res.returncode == 1
    assert "[doc-lint] REFUSED src/pkg/a.py:5: caps" in res.stderr and "doc-lint gate REFUSED the commit" in res.stderr


def test_a_refused_swept_finding_on_a_touched_line_is_printed_once_as_a_refusal_not_also_as_a_warning( repo, monkeypatch ):
    _no_external( monkeypatch )
    _stage( repo, { "src/pkg/a.py": SWEPT_CAPS } )                                   # a new file: line 5 is touched
    rc, text = _gate( repo )
    assert rc == 3
    assert "[doc-lint] src/pkg/a.py:5: caps" not in text                             # the warning form of the same finding
    assert text.count( "src/pkg/a.py:5: caps" ) == 1 and "REFUSED src/pkg/a.py:5: caps" in text


def _stage_bytes( repo, rel, data ):
    full = repo / rel
    full.parent.mkdir( parents=True, exist_ok=True )
    full.write_bytes( data )
    _git( repo, "add", "-f", rel )


LATIN_1 = b'def f():\n    """This is NOT fine \xe9."""\n'


def test_a_swept_file_that_is_not_utf8_is_refused_by_name_and_does_not_crash_the_gate( repo, monkeypatch ):
    _no_external( monkeypatch )
    _stage_bytes( repo, "src/pkg/a.py", LATIN_1 )
    _stage( repo, { "src/pkg/b.py": SWEPT_CAPS } )
    rc, text = _gate( repo )
    assert rc == 3 and "GATE CRASHED" not in text
    assert "REFUSED src/pkg/a.py: not UTF-8: " in text and "'utf-8' codec can't decode" in text and "this cannot be waived" in text
    assert "REFUSED src/pkg/b.py:5: caps" in text                                  # the other staged file is still linted
    assert "2 files checked, 1 docstrings checked, 1 findings, 0 waivers honoured, 0 unparsed, 1 undecodable" in text


def test_a_swept_file_that_is_not_utf8_is_refused_when_it_is_the_only_staged_file( repo, monkeypatch ):
    _no_external( monkeypatch )
    _stage_bytes( repo, "src/pkg/a.py", LATIN_1 )
    rc, text = _gate( repo )
    assert rc == gate.REFUSAL_EXIT
    assert "[doc-lint] REFUSED src/pkg/a.py: not UTF-8: " in text and "1 refusals, commit REFUSED" in text
    assert "WARNING: src/pkg/a.py" not in text


def test_a_file_outside_the_swept_scope_that_is_not_utf8_is_skipped_with_a_warning( repo, monkeypatch ):
    _no_external( monkeypatch )
    _stage_bytes( repo, "src/lupin_mcp/a.py", LATIN_1 )
    _stage_bytes( repo, "docs/p.md", b"caf\xe9 is NOT fine\n" )
    rc, text = _gate( repo )
    assert rc == 0 and "GATE CRASHED" not in text and "REFUSED" not in text
    assert "WARNING: src/lupin_mcp/a.py is not UTF-8, it was NOT checked" in text and "WARNING: docs/p.md is not UTF-8, it was NOT checked" in text
    assert "0 files checked" in text and "0 undecodable" in text


def test_staged_source_raises_the_decode_error_for_non_utf8_bytes( repo ):
    _stage_bytes( repo, "src/pkg/a.py", LATIN_1 )
    with pytest.raises( UnicodeDecodeError ):
        gate.staged_source( str( repo ), "src/pkg/a.py" )


def test_a_file_that_is_not_utf8_is_not_handed_to_ruff_or_markdownlint( repo, monkeypatch ):
    seen = { "ruff": None, "md": None }
    def fake_ruff( root, paths, sources=None ):
        seen[ "ruff" ] = list( paths )
        return [], []
    def fake_md( root, paths, sources=None ):
        seen[ "md" ] = list( paths )
        return [], []
    monkeypatch.setattr( gate, "run_ruff", fake_ruff )
    monkeypatch.setattr( gate, "run_markdownlint", fake_md )
    _stage_bytes( repo, "src/lupin_mcp/a.py", LATIN_1 )
    _stage_bytes( repo, "docs/p.md", b"caf\xe9\n" )
    _stage( repo, { "src/lupin_mcp/ok.py": "x = 1\n", "docs/ok.md": "fine\n" } )
    rc, _ = _gate( repo )
    assert rc == 0 and seen == { "ruff": [ "src/lupin_mcp/ok.py" ], "md": [ "docs/ok.md" ] }


# ---- the counted scope -----------------------------------------------------------------------

from cosa.repo.doc_lint import counts

TABLE = counts.TABLE_PATH
CLEAN = _doc( "Return the thing." )
ONE   = _doc( "This is NOT fine." )                                  # one caps finding
TWO   = _doc( "This is NOT fine and NEVER good." )                   # two caps findings
TIC   = _doc( "At the end of the day it works." )                    # one tic finding


@pytest.fixture
def stamped( repo ):
    for rel in counts.STAMP_FILES:
        full = repo / rel
        if not full.exists():
            full.parent.mkdir( parents=True, exist_ok=True )
            full.write_text( f"stamp file {rel}\n", encoding="utf-8" )
    return repo


def _table( repo, files, stamp=None ):
    text = counts.table_text( files, stamp if stamp is not None else counts.rules_stamp( str( repo ) ) )
    ( repo / TABLE ).parent.mkdir( parents=True, exist_ok=True )
    ( repo / TABLE ).write_text( text, encoding="utf-8" )
    _git( repo, "add", "-f", TABLE )


def _base( repo, files, table, stamp=None ):
    """Commit the files and the table as the base the next commit is judged against."""
    _stage( repo, files )
    _table( repo, table, stamp )
    _git( repo, "commit", "-q", "--no-verify", "-m", "base" )


def test_the_counted_scope_without_a_table_is_reported_not_checked_and_refuses_nothing( stamped, monkeypatch ):
    _no_external( monkeypatch )
    _stage( stamped, { "src/lupin_mcp/a.py": TWO } )
    rc, text = _gate( stamped )
    assert rc == 0 and "REFUSED" not in text
    assert "WARNING: there is no count table at HEAD or staged, so the counted scope was NOT checked" in text
    assert "counted scope: 0 files checked, 0 at or below their count, 0 over, 0 waivers honoured, table absent" in text


def test_with_no_counted_file_staged_and_no_table_there_is_nothing_to_warn_about( stamped, monkeypatch ):
    _no_external( monkeypatch )
    _stage( stamped, { "src/pkg/a.py": CLEAN } )
    rc, text = _gate( stamped )
    assert rc == 0 and "no count table" not in text and "table absent" in text


def test_a_counted_file_that_rises_above_its_entry_is_refused_with_the_count_and_the_findings( stamped, monkeypatch ):
    _no_external( monkeypatch )
    _base( stamped, { "src/lupin_mcp/a.py": ONE }, { "src/lupin_mcp/a.py": 1 } )
    _stage( stamped, { "src/lupin_mcp/a.py": TWO } )
    rc, text = _gate( stamped )
    assert rc == 3
    assert "REFUSED src/lupin_mcp/a.py: 2 findings, the count table allows 1 (+1); reword the text you added, or waive a finding on its own line with: doc-lint: waive <rule> -- <reason>" in text
    assert "[doc-lint]   src/lupin_mcp/a.py:5: caps: ALL-CAPS word NOT" in text and "[doc-lint]   src/lupin_mcp/a.py:5: caps: ALL-CAPS word NEVER" in text
    assert "1 over" in text and "table ok" in text and "1 refusals, commit REFUSED" in text


def test_a_counted_file_at_or_below_its_entry_is_allowed( stamped, monkeypatch ):
    _no_external( monkeypatch )
    _base( stamped, { "src/tests/t.py": TWO }, { "src/tests/t.py": 2 } )
    _stage( stamped, { "src/tests/t.py": TWO + "\nx = 1\n" } )                       # flat
    rc, text = _gate( stamped )
    assert rc == 0 and "1 files checked, 1 at or below their count, 0 over" in text
    _stage( stamped, { "src/tests/t.py": CLEAN } )                                   # fell, the table not lowered
    rc, text = _gate( stamped )
    assert rc == 0 and "1 at or below their count" in text


def test_a_new_counted_file_starts_at_zero( stamped, monkeypatch ):
    _no_external( monkeypatch )
    _base( stamped, { "src/pkg/keep.py": CLEAN }, {} )
    _stage( stamped, { "src/tests/new_a.py": ONE } )
    rc, text = _gate( stamped )
    assert rc == 3 and "REFUSED src/tests/new_a.py: 1 findings, the count table allows 0 (+1)" in text
    assert "also deletes" not in text and "rename" not in text                      # nothing was deleted, so no rename hint
    _git( stamped, "reset", "-q", "--hard" )
    _stage( stamped, { "src/tests/new_b.py": CLEAN } )
    rc, text = _gate( stamped )
    assert rc == 0 and "1 at or below their count" in text


def test_a_rule_swap_at_a_flat_count_is_allowed( stamped, monkeypatch ):
    _no_external( monkeypatch )
    _base( stamped, { "src/lupin_mcp/a.py": ONE }, { "src/lupin_mcp/a.py": 1 } )
    _stage( stamped, { "src/lupin_mcp/a.py": TIC } )                                 # one caps finding became one tic finding
    rc, text = _gate( stamped )
    assert rc == 0 and "REFUSED" not in text and "1 at or below their count" in text


def test_a_renamed_counted_file_keeps_its_entry_and_a_rise_in_it_is_refused( stamped, monkeypatch ):
    _no_external( monkeypatch )
    body = "".join( f"value_{i} = {i}\n" for i in range( 40 ) )                         # enough shared text for git to see a rename
    _base( stamped, { "src/lupin_mcp/old.py": TWO + body }, { "src/lupin_mcp/old.py": 2 } )
    _git( stamped, "mv", "src/lupin_mcp/old.py", "src/lupin_mcp/new.py" )
    rc, text = _gate( stamped )
    assert rc == 0 and "1 at or below their count" in text
    _stage( stamped, { "src/lupin_mcp/new.py": _doc( "This is NOT fine and NEVER good and NOT again." ) + body } )
    rc, text = _gate( stamped )
    assert rc == 3 and "REFUSED src/lupin_mcp/new.py: 3 findings, the count table allows 2 (+1)" in text


def test_a_copy_of_a_counted_file_inherits_nothing( stamped, monkeypatch ):
    _no_external( monkeypatch )
    _base( stamped, { "src/lupin_mcp/old.py": TWO }, { "src/lupin_mcp/old.py": 2 } )
    _stage( stamped, { "src/lupin_mcp/copy.py": TWO } )                              # old.py stays, so this is an addition
    rc, text = _gate( stamped )
    assert rc == 3 and "REFUSED src/lupin_mcp/copy.py: 2 findings, the count table allows 0 (+2)" in text


def test_a_waiver_lowers_a_counted_files_count_and_is_counted( stamped, monkeypatch ):
    _no_external( monkeypatch )
    _base( stamped, { "src/pkg/keep.py": CLEAN }, {} )
    _stage( stamped, { "src/tests/t.py": _doc( "This is NOT fine.  doc-lint: waive caps -- quoted from the standard" ) } )
    rc, text = _gate( stamped )
    assert rc == 0 and "1 files checked, 1 at or below their count, 0 over, 1 waivers honoured" in text
    _stage( stamped, { "src/tests/t.py": _doc( "This is NOT fine.  doc-lint: waive caps" ) } )
    rc, text = _gate( stamped )
    assert rc == 3 and "REFUSED src/tests/t.py: 1 findings, the count table allows 0" in text


def test_the_refusal_shows_ten_findings_with_the_touched_ones_first_and_says_how_many_more( stamped, monkeypatch ):
    _no_external( monkeypatch )
    words = [ "NOT", "NEVER", "NOT", "NEVER", "NOT", "NEVER", "NOT", "NEVER", "NOT", "NEVER", "NOT", "NEVER" ]
    old   = "def f():\n    \"\"\"\n    Return it.\n\n" + "".join( f"    This is {w} line {i}.\n" for i, w in enumerate( words ) ) + "    \"\"\"\n"
    _base( stamped, { "src/tests/t.py": old }, { "src/tests/t.py": 12 } )
    _stage( stamped, { "src/tests/t.py": old[ : -len( "    \"\"\"\n" ) ] + "    This is NOT last.\n    \"\"\"\n" } )
    rc, text = _gate( stamped )
    shown = [ ln for ln in text.split( "\n" ) if ln.startswith( "[doc-lint]   src/tests/t.py:" ) ]
    assert rc == 3 and len( shown ) == gate.SHOWN_FINDINGS and shown[ 0 ] == "[doc-lint]   src/tests/t.py:17: caps: ALL-CAPS word NOT"
    assert "[doc-lint]   and 3 more" in text and "13 findings, the count table allows 12 (+1)" in text


def test_a_counted_file_that_is_not_utf8_counts_as_one_finding( stamped, monkeypatch ):
    _no_external( monkeypatch )
    _base( stamped, { "src/pkg/keep.py": CLEAN }, {} )
    _stage_bytes( stamped, "src/tests/t.py", LATIN_1.replace( b" NOT", b"" ) )
    rc, text = _gate( stamped )
    assert rc == 3 and "REFUSED src/tests/t.py: 1 findings, the count table allows 0 (+1)" in text and "not-utf-8" in text
    _git( stamped, "reset", "-q", "--hard" )
    _base( stamped, { "src/pkg/keep2.py": CLEAN }, { "src/tests/t.py": 1 } )
    _stage_bytes( stamped, "src/tests/t.py", LATIN_1.replace( b" NOT", b"" ) )
    rc, text = _gate( stamped )
    assert rc == 0 and "1 at or below their count" in text


def test_markdown_and_other_files_are_not_in_the_counted_scope( stamped, monkeypatch ):
    _no_external( monkeypatch )
    _base( stamped, { "src/pkg/keep.py": CLEAN }, {} )
    _stage( stamped, { "history.md": "This is NOT fine.\n", "TODO.md": "NEVER mind.\n", "src/tests/data.txt": "NOT\n" } )
    rc, text = _gate( stamped )
    assert rc == 0 and "0 files checked, 0 at or below their count, 0 over" in text


def test_a_staged_table_that_raises_an_entry_or_adds_one_is_refused( stamped, monkeypatch ):
    _no_external( monkeypatch )
    _base( stamped, { "src/lupin_mcp/a.py": ONE }, { "src/lupin_mcp/a.py": 1 } )
    _table( stamped, { "src/lupin_mcp/a.py": 2 } )
    rc, text = _gate( stamped )
    assert rc == 3 and f"REFUSED {TABLE}: src/lupin_mcp/a.py raised from 1 to 2; the table may only fall" in text
    _table( stamped, { "src/lupin_mcp/a.py": 1, "src/lupin_mcp/b.py": 1 } )
    rc, text = _gate( stamped )
    assert rc == 3 and f"REFUSED {TABLE}: src/lupin_mcp/b.py raised from 0 to 1; the table may only fall" in text


def test_a_staged_table_that_lowers_or_deletes_an_entry_is_allowed_and_is_the_allowance_for_the_commit( stamped, monkeypatch ):
    _no_external( monkeypatch )
    _base( stamped, { "src/lupin_mcp/a.py": TWO, "src/lupin_mcp/b.py": ONE }, { "src/lupin_mcp/a.py": 2, "src/lupin_mcp/b.py": 1 } )
    _stage( stamped, { "src/lupin_mcp/a.py": ONE, "src/lupin_mcp/b.py": CLEAN } )
    _table( stamped, { "src/lupin_mcp/a.py": 1 } )                                   # a lowered, b deleted
    rc, text = _gate( stamped )
    assert rc == 0 and "REFUSED" not in text and "2 at or below their count" in text
    _stage( stamped, { "src/lupin_mcp/a.py": _doc( "This is NOT fine and NEVER bad." ) } )   # the file now rises against the staged entry
    rc, text = _gate( stamped )
    assert rc == 3 and "REFUSED src/lupin_mcp/a.py: 2 findings, the count table allows 1 (+1)" in text


def test_a_regenerated_table_under_a_new_stamp_may_raise_when_it_equals_the_census( stamped, monkeypatch ):
    _no_external( monkeypatch )
    _base( stamped, { "src/lupin_mcp/a.py": ONE }, { "src/lupin_mcp/a.py": 1 }, stamp="oldstamp" )
    _stage( stamped, { "src/lupin_mcp/a.py": TWO } )
    _table( stamped, { "src/lupin_mcp/a.py": 2 } )                                   # the stamp is now the current one
    rc, text = _gate( stamped )
    assert rc == 0 and "REFUSED" not in text and "table regenerated" in text


def test_a_regenerated_table_that_does_not_equal_the_census_is_refused_and_the_problems_are_named( stamped, monkeypatch ):
    _no_external( monkeypatch )
    _base( stamped, { "src/lupin_mcp/a.py": ONE }, { "src/lupin_mcp/a.py": 1 }, stamp="oldstamp" )
    _table( stamped, { "src/lupin_mcp/a.py": 5 } )
    rc, text = _gate( stamped )
    assert rc == 3 and f"REFUSED {TABLE}: a regenerated table must equal a census of the staged tree under the current rules" in text
    assert "[doc-lint]   src/lupin_mcp/a.py: table 5, census 1" in text and "table stale" in text
    _table( stamped, { "src/lupin_mcp/a.py": 1 }, stamp="notcurrent" )
    rc, text = _gate( stamped )
    assert rc == 3 and "is not the current" in text


def test_a_regenerated_table_with_many_problems_shows_ten_and_counts_the_rest( stamped, monkeypatch ):
    _no_external( monkeypatch )
    files = { f"src/lupin_mcp/f{i:02d}.py": ONE for i in range( 12 ) }
    _base( stamped, files, {}, stamp="oldstamp" )
    _table( stamped, {} )                                                            # the census holds 12 files the table lacks
    rc, text = _gate( stamped )
    assert rc == 3 and "[doc-lint]   and 2 more" in text and text.count( "table 0, census 1" ) == gate.SHOWN_FINDINGS


def test_the_first_table_is_allowed_only_when_it_equals_the_census( stamped, monkeypatch ):
    _no_external( monkeypatch )
    _stage( stamped, { "src/lupin_mcp/a.py": ONE } )
    _table( stamped, { "src/lupin_mcp/a.py": 1 } )
    rc, text = _gate( stamped )
    assert rc == 0 and "table regenerated" in text
    _table( stamped, { "src/lupin_mcp/a.py": 0 + 3 } )
    rc, text = _gate( stamped )
    assert rc == 3 and "a regenerated table must equal a census" in text


def test_a_table_cut_under_other_rules_refuses_a_commit_that_stages_a_counted_file( stamped, monkeypatch ):
    _no_external( monkeypatch )
    _base( stamped, { "src/pkg/keep.py": CLEAN }, {}, stamp="oldstamp" )
    _stage( stamped, { "src/tests/t.py": CLEAN } )
    rc, text = _gate( stamped )
    assert rc == 3 and "REFUSED: the count table was cut under other rules (stamp oldstamp, now " in text and "table stale" in text
    assert 'regenerate it with: LUPIN_ROOT="$PWD" PYTHONPATH="$PWD/src" python3 -m cosa.repo.doc_lint.counts --repo-root "$PWD" --write and stage the table with the rule change' in text
    _git( stamped, "reset", "-q", "--hard" )
    _stage( stamped, { "history.md": "A note.\n", "src/pkg/other.py": CLEAN } )     # no counted file staged
    rc, text = _gate( stamped )
    assert rc == 0 and "REFUSED" not in text and "table stale" in text


def test_a_malformed_staged_table_is_refused_and_a_malformed_committed_table_only_warns( stamped, monkeypatch ):
    _no_external( monkeypatch )
    _stage( stamped, { "src/pkg/keep.py": CLEAN, TABLE: "garbage" } )
    rc, text = _gate( stamped )
    assert rc == 3 and f"REFUSED {TABLE}: the staged table is malformed: table is not JSON" in text and "table malformed" in text
    _git( stamped, "commit", "-q", "--no-verify", "-m", "bad table" )
    _stage( stamped, { "src/tests/t.py": ONE } )
    rc, text = _gate( stamped )
    assert rc == 0 and "[doc-lint] WARNING: the count table at HEAD is malformed" in text and "table malformed" in text


def test_staged_counted_reads_paths_renames_and_the_table_with_odd_names( stamped ):
    shared = "".join( f"value_{i} = {i}\n" for i in range( 40 ) )
    _stage( stamped, { "src/tests/old name.py": CLEAN + shared, "src/pkg/swept.py": "swept = 1\n", "src/tests/unï.py": "other = 2\n" } )
    _git( stamped, "commit", "-q", "--no-verify", "-m", "base" )
    _git( stamped, "mv", "src/tests/old name.py", "src/tests/new name.py" )
    _stage( stamped, { "src/pkg/swept2.py": "swept = 3\n", "src/lupin_mcp/b.py": "unrelated = 4\n", TABLE: "{}", "notes.md": "x\n" } )
    paths, renamed, table_staged = gate.staged_counted( str( stamped ) )
    assert paths == [ "src/lupin_mcp/b.py", "src/tests/new name.py" ] and renamed == { "src/tests/new name.py": "src/tests/old name.py" } and table_staged is True
    with pytest.raises( RuntimeError, match="git diff --cached failed" ):
        gate.staged_counted( str( stamped / "nope" ) )


def test_staged_counted_without_a_table_or_a_rename_says_so( stamped ):
    _stage( stamped, { "src/tests/t.py": CLEAN } )
    assert gate.staged_counted( str( stamped ) ) == ( [ "src/tests/t.py" ], {}, False )
    assert gate.staged_counted( str( stamped ) )[ 0 ] and gate.head_table_text( str( stamped ) ) is None
    _git( stamped, "commit", "-q", "--no-verify", "-m", "base" )
    assert gate.head_table_text( str( stamped ) ) is None
    _base( stamped, { "src/pkg/a.py": CLEAN }, { "src/tests/t.py": 1 } )
    assert counts.parse_table( gate.head_table_text( str( stamped ) ) ).files == { "src/tests/t.py": 1 }


def test_a_crash_in_the_counted_check_still_allows_the_commit_with_the_loud_line( stamped, monkeypatch ):
    _no_external( monkeypatch )
    _base( stamped, { "src/pkg/keep.py": CLEAN }, {} )
    _stage( stamped, { "src/tests/t.py": ONE } )
    monkeypatch.setattr( gate.counts, "rules_stamp", lambda root, read=None: ( _ for _ in () ).throw( OSError( "rule file gone" ) ) )
    rc, text = _gate( stamped )
    assert rc == 0 and "[doc-lint] GATE CRASHED, commit allowed: OSError: rule file gone" in text


def test_the_real_chain_refuses_a_counted_file_that_rises_and_allows_one_that_does_not( repo ):
    stamped = repo                                                                     # the rule files come from the linked tree
    os.symlink( os.path.join( cu.get_project_root(), "src", "cosa" ), stamped / "src" / "cosa" )
    _stage( stamped, { "src/tests/t.py": ONE } )
    _table( stamped, { "src/tests/t.py": 1 } )
    _git( stamped, "commit", "-q", "--no-verify", "-m", "base" )
    _stage( stamped, { "src/tests/t.py": TWO } )
    res = _run_chain( stamped, { "LUPIN_RUFF": "", "LUPIN_MARKDOWNLINT": "" } )
    assert res.returncode == 1
    assert "[doc-lint] REFUSED src/tests/t.py: 2 findings, the count table allows 1 (+1)" in res.stderr and "doc-lint gate REFUSED the commit" in res.stderr
    _stage( stamped, { "src/tests/t.py": ONE + "\nx = 1\n" } )
    res = _run_chain( stamped, { "LUPIN_RUFF": "", "LUPIN_MARKDOWNLINT": "" } )
    assert res.returncode == 0 and "counted scope: 1 files checked, 1 at or below their count" in res.stderr


def test_a_new_file_beside_a_deleted_entry_is_told_it_may_be_a_rename_git_could_not_pair( stamped, monkeypatch ):
    _no_external( monkeypatch )
    unique = "".join( f"unique_{i} = {i * 7}\n" for i in range( 30 ) )                          # nothing in common with the new file
    old    = TWO + "".join( f"old_{i} = {i}\n" for i in range( 30 ) )
    _base( stamped, { "src/lupin_mcp/old.py": old, "src/lupin_mcp/other.py": unique }, { "src/lupin_mcp/old.py": 2 } )
    _git( stamped, "rm", "-q", "src/lupin_mcp/old.py", "src/lupin_mcp/other.py" )
    _stage( stamped, { "src/lupin_mcp/new.py": _doc( "This is NOT fine and NEVER bad." ) } )         # too different for git to pair with old.py
    assert sorted( gate.staged_deleted( str( stamped ) ) ) == [ "src/lupin_mcp/old.py", "src/lupin_mcp/other.py" ]
    rc, text = _gate( stamped )
    assert rc == 3
    assert "REFUSED src/lupin_mcp/new.py: 2 findings, the count table allows 0 (+2)" in text
    assert "this commit also deletes src/lupin_mcp/old.py, which had an entry: if this file is a rename that git no longer pairs because too much changed, rename it in one commit and rewrite it in the next" in text
    assert "other.py" not in text                                                                      # a deleted file with no entry is not named


def test_a_rise_in_a_file_with_an_entry_gets_no_rename_hint_even_when_something_is_deleted( stamped, monkeypatch ):
    _no_external( monkeypatch )
    _base( stamped, { "src/lupin_mcp/a.py": ONE, "src/lupin_mcp/gone.py": TWO }, { "src/lupin_mcp/a.py": 1, "src/lupin_mcp/gone.py": 2 } )
    _git( stamped, "rm", "-q", "src/lupin_mcp/gone.py" )
    _stage( stamped, { "src/lupin_mcp/a.py": TWO } )
    rc, text = _gate( stamped )
    assert rc == 3 and "REFUSED src/lupin_mcp/a.py: 2 findings, the count table allows 1 (+1)" in text and "also deletes" not in text


def test_staged_deleted_lists_the_deletions_and_names_a_git_error( stamped ):
    _stage( stamped, { "src/tests/a b.py": CLEAN, "src/tests/c.py": CLEAN } )
    _git( stamped, "commit", "-q", "--no-verify", "-m", "base" )
    assert gate.staged_deleted( str( stamped ) ) == []
    _git( stamped, "rm", "-q", "src/tests/a b.py" )
    assert gate.staged_deleted( str( stamped ) ) == [ "src/tests/a b.py" ]
    with pytest.raises( RuntimeError, match="git diff --cached failed" ):
        gate.staged_deleted( str( stamped / "nope" ) )


def test_a_regeneration_commit_counts_the_staged_file_not_the_one_on_disk( stamped, monkeypatch ):
    _no_external( monkeypatch )
    _base( stamped, { "src/lupin_mcp/a.py": ONE }, { "src/lupin_mcp/a.py": 1 }, stamp="oldstamp" )
    _stage( stamped, { "src/lupin_mcp/a.py": TWO } )                                  # two findings go into the index
    ( stamped / "src" / "lupin_mcp" / "a.py" ).write_text( ONE, encoding="utf-8" )     # and the disk copy is put back
    _table( stamped, { "src/lupin_mcp/a.py": 1 } )                                    # a table that matches the disk, not the index
    rc, text = _gate( stamped )
    assert rc == 3 and "[doc-lint]   src/lupin_mcp/a.py: table 1, census 2" in text and "table stale" in text


def test_a_stale_table_commit_prints_no_counted_file_refusal_and_checks_no_file( stamped, monkeypatch ):
    _no_external( monkeypatch )
    _base( stamped, { "src/lupin_mcp/a.py": ONE }, { "src/lupin_mcp/a.py": 1 }, stamp="oldstamp" )
    _stage( stamped, { "src/lupin_mcp/a.py": TWO } )                                  # would rise against the entry, if the table were trusted
    rc, text = _gate( stamped )
    assert rc == 3 and text.count( "REFUSED" ) == 2 and "the count table was cut under other rules" in text   # one refusal line plus the summary line
    assert "findings, the count table allows" not in text
    assert "counted scope: 0 files checked, 0 at or below their count, 0 over, 0 waivers honoured, table stale" in text


RULE_FILE = counts.STAMP_FILES[ 0 ]


def _commit_rules_and_table( repo, files, table ):
    """Commit the rule files too, so the index holds them, with a table cut under the rules as they stand."""
    _git( repo, "add", "-f", *counts.STAMP_FILES )
    _base( repo, files, table )


def test_a_staged_rule_edit_makes_the_table_stale( stamped, monkeypatch ):
    _no_external( monkeypatch )
    _commit_rules_and_table( stamped, { "src/pkg/keep.py": CLEAN }, {} )
    ( stamped / RULE_FILE ).write_text( "an edited rule\n", encoding="utf-8" )
    _git( stamped, "add", "-f", RULE_FILE )
    _stage( stamped, { "src/tests/t.py": CLEAN } )
    rc, text = _gate( stamped )
    assert rc == 3 and "the count table was cut under other rules" in text and "table stale" in text


def test_an_unstaged_rule_edit_leaves_the_table_current_and_is_reported( stamped, monkeypatch ):
    _no_external( monkeypatch )
    _commit_rules_and_table( stamped, { "src/pkg/keep.py": CLEAN }, {} )
    ( stamped / RULE_FILE ).write_text( "an edit nobody staged\n", encoding="utf-8" )
    _stage( stamped, { "src/tests/t.py": CLEAN } )
    rc, text = _gate( stamped )
    assert rc == 0 and "REFUSED" not in text and "table ok" in text
    assert "WARNING: the rule files in the working tree differ from the staged ones" in text


def test_a_rule_edit_staged_and_then_put_back_on_disk_still_stales_the_table( stamped, monkeypatch ):
    _no_external( monkeypatch )
    _commit_rules_and_table( stamped, { "src/pkg/keep.py": CLEAN }, {} )
    original = ( stamped / RULE_FILE ).read_text( encoding="utf-8" )
    ( stamped / RULE_FILE ).write_text( "an edited rule\n", encoding="utf-8" )
    _git( stamped, "add", "-f", RULE_FILE )
    ( stamped / RULE_FILE ).write_text( original, encoding="utf-8" )                 # the disk copy matches the table again
    _stage( stamped, { "src/tests/t.py": CLEAN } )
    rc, text = _gate( stamped )
    assert rc == 3 and "the count table was cut under other rules" in text


def test_the_stamp_the_gate_reads_is_the_staged_one_and_a_clean_tree_has_no_warning( stamped, monkeypatch ):
    _no_external( monkeypatch )
    _commit_rules_and_table( stamped, { "src/pkg/keep.py": CLEAN }, {} )
    _stage( stamped, { "src/tests/t.py": CLEAN } )
    rc, text = _gate( stamped )
    assert rc == 0 and "table ok" in text and "differ from the staged ones" not in text


def test_staged_bytes_reads_the_index_then_the_working_tree_then_raises( stamped ):
    _stage( stamped, { "src/tests/a.py": "indexed\n" } )
    ( stamped / "src" / "tests" / "a.py" ).write_text( "on disk\n", encoding="utf-8" )
    assert gate.staged_bytes( str( stamped ), "src/tests/a.py" ) == b"indexed\n"
    ( stamped / "loose.txt" ).write_text( "untracked\n", encoding="utf-8" )
    assert gate.staged_bytes( str( stamped ), "loose.txt" ) == b"untracked\n"
    with pytest.raises( OSError ):
        gate.staged_bytes( str( stamped ), "nowhere.txt" )


def test_the_rename_hint_names_at_most_three_deleted_entries( stamped, monkeypatch ):
    _no_external( monkeypatch )
    old   = lambda i: TWO + "".join( f"old{i}_{n} = {n}\n" for n in range( 30 ) )          # four unrelated files, none pairable
    files = { f"src/lupin_mcp/d{i}.py": old( i ) for i in range( 4 ) }
    _base( stamped, files, { path: 2 for path in files } )
    _git( stamped, "rm", "-q", *files )
    _stage( stamped, { "src/lupin_mcp/new.py": _doc( "This is NOT fine and NEVER bad." ) } )
    rc, text = _gate( stamped )
    named = text.split( "also deletes " )[ 1 ].split( ", which had an entry" )[ 0 ]
    assert rc == 3 and named == "src/lupin_mcp/d0.py, src/lupin_mcp/d1.py, src/lupin_mcp/d2.py" and "d3.py" not in text
