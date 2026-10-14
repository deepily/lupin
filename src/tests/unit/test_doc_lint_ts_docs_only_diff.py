"""
ts_docs_only_diff: a comment-only change passes and a one-token code change fails.

The Node token script is replaced by a stand-in in the logic tests, so they need no Node. The
tests of the real script at the end are skipped when Node is not installed.
"""

import io
import json
import shutil
import subprocess

import pytest

import cosa.utils.util as cu
from cosa.repo.doc_lint import ts_docs_only_diff as tdd

NODE = shutil.which( "node" )


def _git( root, *args ):
    res = subprocess.run( [ "git", "-C", str( root ), "-c", "user.email=t@t", "-c", "user.name=t", *args ], capture_output=True, text=True )
    assert res.returncode == 0, res.stderr
    return res.stdout


def _desc( tokens=None, shebang=None, directives=None, tags=None, errors=None ):
    return {
        "errors"    : errors or [],
        "tokens"    : tokens if tokens is not None else [ [ 1, 80, "x" ], [ 1, 64, "=" ], [ 2, 9, "1" ] ],
        "directives": directives or [],
        "tags"      : tags or [],
        "shebang"   : shebang
    }


@pytest.fixture
def repo( tmp_path ):
    _git( tmp_path, "init", "-q" )
    ( tmp_path / "a.ts" ).write_text( "x = 1;\n", encoding="utf-8" )
    ( tmp_path / "notes.md" ).write_text( "# n\n", encoding="utf-8" )
    ( tmp_path / "conf.ini" ).write_text( "k\n", encoding="utf-8" )
    _git( tmp_path, "add", "-A" )
    _git( tmp_path, "commit", "-qm", "base" )
    return tmp_path


def _stub_run( root, items ):
    """Describe a text by its words: code tokens are the words before a double slash."""
    out = {}
    for item in items:
        words = [ w for line in item[ "text" ].split( "\n" ) for w in line.split( "//" )[ 0 ].split() ]
        out[ item[ "id" ] ] = _desc( tokens=[ [ 1, 1, w ] for w in words ] )
    return out


# ---- description_difference ----

def test_identical_descriptions_pass():
    assert tdd.description_difference( _desc(), _desc() ) is None


def test_a_changed_token_is_named_with_its_line():
    new = _desc( tokens=[ [ 1, 80, "x" ], [ 1, 64, "=" ], [ 2, 9, "2" ] ] )
    assert tdd.description_difference( _desc(), new ) == "line 2: token '1' became '2'"


def test_same_text_with_another_token_kind_is_a_difference():
    new = _desc( tokens=[ [ 1, 80, "x" ], [ 1, 64, "=" ], [ 2, 10, "1" ] ] )
    assert tdd.description_difference( _desc(), new ) is not None


def test_a_removed_or_added_token_is_named():
    short = _desc( tokens=[ [ 1, 80, "x" ], [ 1, 64, "=" ] ] )
    assert tdd.description_difference( _desc(), short ) == "removed token '1' at line 2"
    assert tdd.description_difference( short, _desc() ) == "added token '1' at line 2"


def test_a_changed_hashbang_is_a_difference():
    msg = tdd.description_difference( _desc( shebang="#!/usr/bin/env node" ), _desc( shebang=None ) )
    assert msg is not None and "hashbang" in msg


def test_a_removed_directive_comment_is_a_difference():
    msg = tdd.description_difference( _desc( directives=[ "@ts-ignore" ] ), _desc() )
    assert msg is not None and "'@ts-ignore'" in msg and "removed" in msg


def test_an_added_directive_comment_is_a_difference():
    msg = tdd.description_difference( _desc(), _desc( directives=[ "eslint-disable no-console" ] ) )
    assert msg is not None and "added" in msg


def test_a_changed_typed_tag_is_a_difference():
    msg = tdd.description_difference( _desc( tags=[ [ "param", "string" ] ] ), _desc( tags=[ [ "param", "number" ] ] ) )
    assert msg is not None and "typed documentation tags" in msg


def test_a_parse_error_on_either_side_is_a_difference():
    err = [ { "line": 3, "message": "Unexpected token" } ]
    assert tdd.description_difference( _desc( errors=err ), _desc() ) == "old file does not parse, line 3: Unexpected token"
    assert tdd.description_difference( _desc(), _desc( errors=err ) ) == "new file does not parse, line 3: Unexpected token"


# ---- path_difference ----

def test_path_difference_unchecked_type_mode_added_deleted_and_pass():
    modes = ( "100644", "100644" )
    assert "not checked" in tdd.path_difference( "a.py", modes, "x", "y" )
    assert "mode changed" in tdd.path_difference( "a.ts", ( "100644", "100755" ), "x", "x", ( _desc(), _desc() ) )
    assert tdd.path_difference( "a.ts", ( "000000", "100644" ), None, "x" ) == "file added"
    assert tdd.path_difference( "a.ts", ( "100644", "000000" ), "x", None ) == "file deleted"
    assert tdd.path_difference( "a.mjs", modes, "x", "x", ( _desc(), _desc() ) ) is None


# ---- analyse ----

def test_analyse_of_nothing_starts_no_process( monkeypatch ):
    monkeypatch.setattr( tdd.subprocess, "run", lambda *a, **k: pytest.fail( "a process was started" ) )
    assert tdd.analyse( "/nowhere", [] ) == {}


def _fake_run( stdout="", returncode=0, stderr="", raises=None ):
    def run( cmd, **kwargs ):
        if raises is not None: raise raises
        return subprocess.CompletedProcess( cmd, returncode, stdout, stderr )
    return run


def test_analyse_reads_one_line_per_id( monkeypatch ):
    lines = "\n".join( json.dumps( { "id": i, **_desc() } ) for i in ( "a", "b" ) ) + "\n\n"
    monkeypatch.setattr( tdd.subprocess, "run", _fake_run( stdout=lines ) )
    items = [ { "id": "a", "name": "a.ts", "text": "" }, { "id": "b", "name": "b.ts", "text": "" } ]
    assert sorted( tdd.analyse( "/r", items ) ) == [ "a", "b" ]


def test_analyse_refuses_when_node_is_missing_fails_or_prints_garbage( monkeypatch ):
    item = [ { "id": "a", "name": "a.ts", "text": "" } ]
    monkeypatch.setattr( tdd.subprocess, "run", _fake_run( raises=OSError( "no node" ) ) )
    with pytest.raises( RuntimeError, match="cannot run node" ): tdd.analyse( "/r", item )
    monkeypatch.setattr( tdd.subprocess, "run", _fake_run( returncode=1, stderr="boom" ) )
    with pytest.raises( RuntimeError, match="token script failed: boom" ): tdd.analyse( "/r", item )
    monkeypatch.setattr( tdd.subprocess, "run", _fake_run( stdout="not json\n" ) )
    with pytest.raises( RuntimeError, match="not JSON" ): tdd.analyse( "/r", item )


def test_analyse_names_an_id_that_came_back_without_a_description( monkeypatch ):
    monkeypatch.setattr( tdd.subprocess, "run", _fake_run( stdout=json.dumps( { "id": "a", **_desc() } ) + "\n" ) )
    items = [ { "id": "a", "name": "a.ts", "text": "" }, { "id": "b", "name": "b.ts", "text": "" } ]
    with pytest.raises( RuntimeError, match="no description for: b" ): tdd.analyse( "/r", items )


# ---- check_diff and main in a scratch repo, with the stand-in ----

def test_check_diff_passes_comment_only_and_fails_code_change( repo ):
    ( repo / "a.ts" ).write_text( "x = 1; // why\n", encoding="utf-8" )
    assert tdd.check_diff( repo, "HEAD", None, None, _stub_run ) == [ ( "a.ts", None ), ]
    ( repo / "a.ts" ).write_text( "x = 2;\n", encoding="utf-8" )
    [ ( path, failure ) ] = tdd.check_diff( repo, "HEAD", None, None, _stub_run )
    assert path == "a.ts" and "became" in failure


def test_check_diff_markdown_is_ignored_and_other_types_are_unchecked( repo ):
    ( repo / "notes.md" ).write_text( "# changed\n", encoding="utf-8" )
    ( repo / "conf.ini" ).write_text( "other\n", encoding="utf-8" )
    results = dict( tdd.check_diff( repo, "HEAD", None, None, _stub_run ) )
    assert "notes.md" not in results and "not checked" in results[ "conf.ini" ]


def test_check_diff_an_untracked_new_script_fails_as_added( repo ):
    ( repo / "new.js" ).write_text( "let y;\n", encoding="utf-8" )
    assert dict( tdd.check_diff( repo, "HEAD", None, None, _stub_run ) )[ "new.js" ] == "file added"


def test_check_diff_a_deleted_script_fails( repo ):
    ( repo / "a.ts" ).unlink()
    assert dict( tdd.check_diff( repo, "HEAD", None, None, _stub_run ) )[ "a.ts" ] == "file deleted"


def test_check_diff_a_mode_only_change_fails( repo ):
    _git( repo, "update-index", "--chmod=+x", "a.ts" )
    _git( repo, "commit", "-qm", "mode" )
    _git( repo, "update-index", "--chmod=-x", "a.ts" )
    assert "mode changed" in dict( tdd.check_diff( repo, "HEAD", None, None, _stub_run ) )[ "a.ts" ]


def test_check_diff_paths_limit_the_check_to_whole_directory_names( repo ):
    for d in ( "lib/a", "lib/ab" ):
        ( repo / d ).mkdir( parents=True )
        ( repo / d / "x.ts" ).write_text( "x = 1;\n", encoding="utf-8" )
    _git( repo, "add", "-A" )
    _git( repo, "commit", "-qm", "libs" )
    ( repo / "lib" / "a" / "x.ts" ).write_text( "x = 2;\n", encoding="utf-8" )
    ( repo / "lib" / "ab" / "x.ts" ).write_text( "x = 3;\n", encoding="utf-8" )
    assert [ p for p, _ in tdd.check_diff( repo, "HEAD", None, [ "lib/a" ], _stub_run ) ] == [ "lib/a/x.ts" ]
    assert [ p for p, _ in tdd.check_diff( repo, "HEAD", None, [ "lib/a/x.ts", "lib/ab/" ], _stub_run ) ] == [ "lib/a/x.ts", "lib/ab/x.ts" ]
    assert tdd.check_diff( repo, "HEAD", None, [ "nothing" ], _stub_run ) == []


def test_check_diff_compares_two_revisions( repo ):
    ( repo / "a.ts" ).write_text( "x = 1; // note\n", encoding="utf-8" )
    _git( repo, "commit", "-qam", "comment" )
    assert tdd.check_diff( repo, "HEAD~1", "HEAD", None, _stub_run ) == [ ( "a.ts", None ) ]


def test_main_prints_a_line_per_file_and_returns_one_on_a_failure( repo, monkeypatch ):
    monkeypatch.setattr( tdd, "analyse", _stub_run )
    ( repo / "a.ts" ).write_text( "x = 9;\n", encoding="utf-8" )
    out = io.StringIO()
    rc  = tdd.main( [ "--base", "HEAD", "--repo-root", str( repo ) ], out=out )
    assert rc == 1 and "FAIL a.ts" in out.getvalue() and "0 passed, 1 failed" in out.getvalue()
    _git( repo, "checkout", "--", "a.ts" )
    out = io.StringIO()
    assert tdd.main( [ "--base", "HEAD", "--repo-root", str( repo ) ], out=out ) == 0
    assert "0 passed, 0 failed" in out.getvalue()


def test_main_writes_pass_lines_to_stdout_by_default( repo, monkeypatch, capsys ):
    monkeypatch.setattr( tdd, "analyse", _stub_run )
    ( repo / "a.ts" ).write_text( "x = 1; // c\n", encoding="utf-8" )
    assert tdd.main( [ "--base", "HEAD", "--repo-root", str( repo ) ] ) == 0
    assert "PASS a.ts" in capsys.readouterr().out


# ---- the real token script ----

needs_node = pytest.mark.skipif( NODE is None, reason="Node is not installed" )


def _real( root, items ):
    return tdd.analyse( cu.get_project_root(), items )


def _diff_of( repo, name, old, new ):
    ( repo / name ).write_text( old, encoding="utf-8" )
    _git( repo, "add", "-A" )
    _git( repo, "commit", "-qm", f"add {name}" )
    ( repo / name ).write_text( new, encoding="utf-8" )
    return dict( tdd.check_diff( repo, "HEAD", None, None, _real ) )[ name ]


@needs_node
def test_real_comment_only_change_passes( repo ):
    old = "#!/usr/bin/env node\n// @ts-check\n/** Old. */\nexport function f( a: number ) { return a / 2 / 3; }\n"
    new = "#!/usr/bin/env node\n// @ts-check\n/**\n * A much better doc line.\n */\nexport function f( a: number ) { return a / 2 / 3; } // why\n"
    assert _diff_of( repo, "m.ts", old, new ) is None


@needs_node
def test_real_one_token_code_change_fails_and_names_it( repo ):
    msg = _diff_of( repo, "m.ts", "export const n = 1; // c\n", "export const n = 2; // c\n" )
    assert msg == "line 1: token '1' became '2'"


@needs_node
def test_real_comment_markers_inside_strings_and_regex_are_code( repo ):
    old = 'const s = "// not a comment"; const r = /a\\/b/; const t = `x${ 1 }`;\n'
    new = 'const s = "// a different one"; const r = /a\\/b/; const t = `x${ 1 }`;\n'
    assert _diff_of( repo, "s.ts", old, new ) is not None


@needs_node
def test_real_removed_directive_and_hashbang_fail( repo ):
    assert "directive" in _diff_of( repo, "d.ts", "// @ts-ignore\nlet a: number = 'x';\n", "let a: number = 'x';\n" )
    assert "hashbang" in _diff_of( repo, "h.mjs", "#!/usr/bin/env node\nlet a = 1;\n", "let a = 1;\n" )


@needs_node
def test_real_javascript_typed_tag_change_fails_but_typescript_tag_does_not( repo ):
    old_js = "/**\n * @param {string} s the s\n */\nfunction f( s ) { return s; }\n"
    assert "typed documentation tags" in _diff_of( repo, "t.js", old_js, old_js.replace( "{string}", "{number}" ) )
    old_ts = "/**\n * @param {string} s the s\n */\nfunction f( s: string ) { return s; }\n"
    assert _diff_of( repo, "t.ts", old_ts, old_ts.replace( "{string}", "{number}" ) ) is None


@needs_node
def test_real_template_and_typedef_names_in_javascript_are_type_code( repo ):
    old = "/**\n * @template T\n * @typedef {Object} Opt\n */\nfunction f( s ) { return s; }\n"
    assert "typed documentation tags" in _diff_of( repo, "n.js", old, old.replace( "@template T", "@template U" ) )


@needs_node
def test_real_a_file_that_does_not_parse_fails( repo ):
    assert "does not parse" in _diff_of( repo, "p.ts", "let a = 1;\n", "let a = ;\n" )


@needs_node
def test_real_script_reports_an_error_for_non_json_input():
    res = subprocess.run( [ "node", f"{cu.get_project_root()}/src/scripts/ts_code_tokens.mjs" ], input="not json", capture_output=True, text=True )
    assert res.returncode == 2 and "usage" in res.stderr


# ---- mutation check: each mutant of the module must redden the named test ----

MUTANTS = [
    ( "if a != b or kind_a != kind_b: return", "if a != b: return", "test_same_text_with_another_token_kind_is_a_difference" ),
    ( "if a != b or kind_a != kind_b: return", "if kind_a != kind_b: return", "test_a_changed_token_is_named_with_its_line" ),
    ( "    if len( old[ \"tokens\" ] ) != len( new[ \"tokens\" ] ):\n", "    if False:\n", "test_a_removed_or_added_token_is_named" ),
    ( "if old[ \"shebang\" ] != new[ \"shebang\" ]:", "if False:", "test_a_changed_hashbang_is_a_difference" ),
    ( "if old[ \"directives\" ] != new[ \"directives\" ]:", "if False:", "test_a_removed_directive_comment_is_a_difference" ),
    ( "if old[ \"tags\" ] != new[ \"tags\" ]:", "if False:", "test_a_changed_typed_tag_is_a_difference" ),
    ( "        if record[ \"errors\" ]:\n", "        if False:\n", "test_a_parse_error_on_either_side_is_a_difference" ),
    ( "if not path.endswith( SUFFIXES ): return \"file type not checked, only .ts, .js and .mjs are compared\"", "if False: return None", "test_path_difference_unchecked_type_mode_added_deleted_and_pass" ),
    ( "if \"000000\" not in modes and old_mode != new_mode:", "if False:", "test_check_diff_a_mode_only_change_fails" ),
    ( "if old_source is None: return \"file added\"", "if False: return \"file added\"", "test_check_diff_an_untracked_new_script_fails_as_added" ),
    ( "if new_source is None: return \"file deleted\"", "if False: return \"file deleted\"", "test_check_diff_a_deleted_script_fails" ),
    ( "        if path.endswith( dod.DOC_SUFFIX ): continue\n", "", "test_check_diff_markdown_is_ignored_and_other_types_are_unchecked" ),
    ( "path == p or path.startswith( p.rstrip( \"/\" ) + \"/\" )", "path.startswith( p )", "test_check_diff_paths_limit_the_check_to_whole_directory_names" ),
    ( "if missing: raise RuntimeError", "if False: raise RuntimeError", "test_analyse_names_an_id_that_came_back_without_a_description" ),
    ( "if not items: return {}", "if False: return {}", "test_analyse_of_nothing_starts_no_process" ),
    ( "return 1 if failed else 0", "return 0", "test_main_prints_a_line_per_file_and_returns_one_on_a_failure" ),
]


def _mutant_module( old, new ):
    path   = tdd.__file__
    source = open( path, encoding="utf-8" ).read()
    assert source.count( old ) == 1, f"anchor must match exactly once: {old!r}"
    module = type( tdd )( tdd.__name__ )
    module.__file__, module.__package__ = path, tdd.__package__
    exec( compile( source.replace( old, new ), path, "exec" ), module.__dict__ )
    return module


@pytest.mark.parametrize( "old,new,named_test", MUTANTS )
def test_each_mutant_reddens_its_named_test( monkeypatch, repo, old, new, named_test ):
    this   = globals()
    code   = this[ named_test ].__code__
    names  = code.co_varnames[ : code.co_argcount ]
    kwargs = {}
    if "repo" in names: kwargs[ "repo" ] = repo
    if "monkeypatch" in names: kwargs[ "monkeypatch" ] = monkeypatch
    this[ named_test ]( **kwargs )
    monkeypatch.setitem( this, "tdd", _mutant_module( old, new ) )
    with pytest.raises( BaseException ):  # a crash, a failed assert and a DID NOT RAISE outcome all redden the test
        this[ named_test ]( **kwargs )
