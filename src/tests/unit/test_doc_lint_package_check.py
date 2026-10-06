"""
package_check: the four script checks on one rewritten package, run over a small real git repo.

Each test builds the repo at a base commit, changes the working tree the way a writer would, and
runs the checks. The four named scenarios are the ones the spec asks for: a clean rewrite, a code
change, a removed docstring and a lint finding.
"""

import io
import json
import subprocess

import pytest

from cosa.repo.doc_lint import package_check as pc, word_list

WORDS = [ "not", "never", "the", "very", "must" ]

BASE_MOD = '''"""Module for tests."""


def add( x ):
    """
    Add one to a number.

    Requires:
        - x is a number

    Ensures:
        - returns x plus one
    """
    return x + 1


class Box:
    """A box."""

    def __init__( self ):
        """Make a box."""
        self.n = 0
'''

CLEAN_MOD = BASE_MOD.replace( "Module for tests.", "Holds the helpers for the tests." ).replace( "Add one to a number.", "Return a number one larger." )


def _git( root, *args ):
    res = subprocess.run( [ "git", "-C", str( root ), "-c", "user.email=t@t", "-c", "user.name=t", *args ], capture_output=True, text=True )
    assert res.returncode == 0, res.stderr
    return res.stdout.strip()


@pytest.fixture
def repo( tmp_path ):
    _git( tmp_path, "init", "-q" )
    ( tmp_path / "src" / "conf" ).mkdir( parents=True )
    ( tmp_path / "src" / "conf" / "dm-tutor-lowercase-words.txt" ).write_text( "\n".join( WORDS ) + "\n", encoding="utf-8" )
    files = {
        "pkg/__init__.py"       : '"""The package."""\n',
        "pkg/mod.py"            : BASE_MOD,
        "pkg/sub/__init__.py"   : '"""Sub."""\n',
        "pkg/sub/deep.py"       : '"""Deep."""\n',
        "pkg/test_mod.py"       : '"""A test."""\n',
        "pkg/notes.md"          : "notes\n"
    }
    for rel, text in files.items():
        path = tmp_path / rel
        path.parent.mkdir( parents=True, exist_ok=True )
        path.write_text( text, encoding="utf-8" )
    _git( tmp_path, "add", "." )
    _git( tmp_path, "commit", "-qm", "base" )
    yield tmp_path
    word_list._state[ "root" ]  = None
    word_list._state[ "words" ] = None


def _run( repo, out, package="pkg", base="HEAD" ):
    stream = io.StringIO()
    code   = pc.main( [ "--repo-root", str( repo ), "--base", base, "--package", package, "--out", str( out ) ], stream )
    return code, stream.getvalue()


def _out_of( repo, tmp_path, name ):
    _run( repo, tmp_path / name )
    return tmp_path / name


def _check( result, name ):
    return next( c for c in result[ "checks" ] if c[ "name" ] == name )


def _read( out, name ):
    return json.loads( ( out / name ).read_text( encoding="utf-8" ) )


def test_a_clean_rewrite_passes_and_pairs_hold_exactly_the_changed_docstrings( repo, tmp_path ):
    ( repo / "pkg" / "mod.py" ).write_text( CLEAN_MOD, encoding="utf-8" )
    out  = tmp_path / "out"
    code, text = _run( repo, out )
    assert code == 0, text
    result = _read( out, "result.json" )
    assert result[ "pass" ] is True and result[ "refusals" ] == []
    assert [ c[ "name" ] for c in result[ "checks" ] ] == [ "docstring_lint", "docs_only_diff", "contract_diff", "py_compile" ]
    assert all( c[ "pass" ] and c[ "ran" ] for c in result[ "checks" ] )
    assert result[ "base" ] == _git( repo, "rev-parse", "HEAD" ) and result[ "package" ] == "pkg"
    assert result[ "changed_files" ] == [ "pkg/mod.py" ]
    assert _read( out, "pairs.json" ) == [
        { "id": "pkg/mod.py::<module>#0", "old": "Module for tests.", "new": "Holds the helpers for the tests." },
        { "id": "pkg/mod.py::add#0", "old": BASE_MOD.split( '"""' )[ 3 ], "new": CLEAN_MOD.split( '"""' )[ 3 ] }
    ]
    assert result[ "counts" ] == { "docstrings": 5, "docstrings_changed": 2, "words_before": 18, "words_after": 21 }
    assert sorted( p.name for p in out.iterdir() ) == [ "pairs.json", "result.json" ]
    assert text.splitlines()[ 0 ] == "PASS docstring_lint" and "PASS pkg at base" in text


def test_a_code_change_fails_docs_only_diff_and_names_the_file( repo, tmp_path ):
    ( repo / "pkg" / "mod.py" ).write_text( CLEAN_MOD.replace( "return x + 1", "return x + 2" ), encoding="utf-8" )
    code, text = _run( repo, tmp_path / "out" )
    result = _read( tmp_path / "out", "result.json" )
    check  = _check( result, "docs_only_diff" )
    assert code == 1 and result[ "pass" ] is False and check[ "pass" ] is False and check[ "ran" ] is True
    assert check[ "output" ][ 0 ][ "path" ] == "pkg/mod.py" and check[ "output" ][ 0 ][ "failure" ]
    assert _check( result, "docstring_lint" )[ "pass" ] and "FAIL docs_only_diff" in text


def test_a_removed_docstring_is_refused_with_its_key_named( repo, tmp_path ):
    ( repo / "pkg" / "mod.py" ).write_text( CLEAN_MOD.replace( '        """Make a box."""\n', "" ), encoding="utf-8" )
    code, text = _run( repo, tmp_path / "out" )
    result = _read( tmp_path / "out", "result.json" )
    assert code == 1 and result[ "pass" ] is False
    assert result[ "refusals" ] == [ { "file": "pkg/mod.py", "reason": "docstring keys differ", "added": [], "removed": [ "FunctionDef:__init__#0" ] } ]
    assert _read( tmp_path / "out", "pairs.json" ) == []
    assert "REFUSED pkg/mod.py: docstring keys differ, added [], removed ['FunctionDef:__init__#0']" in text


def test_a_rewrite_that_leaves_a_lint_finding_fails_lint( repo, tmp_path ):
    ( repo / "pkg" / "mod.py" ).write_text( CLEAN_MOD.replace( "A box.", "A NEVER box." ), encoding="utf-8" )
    code, _ = _run( repo, tmp_path / "out" )
    check   = _check( _read( tmp_path / "out", "result.json" ), "docstring_lint" )
    assert code == 1 and check[ "pass" ] is False
    assert check[ "output" ] == [ "pkg/mod.py:18: caps: ALL-CAPS word NEVER" ]


def test_a_dropped_contract_item_fails_contract_diff( repo, tmp_path ):
    ( repo / "pkg" / "mod.py" ).write_text( CLEAN_MOD.replace( "\n    Requires:\n        - x is a number\n", "" ), encoding="utf-8" )
    code, _ = _run( repo, tmp_path / "out" )
    check   = _check( _read( tmp_path / "out", "result.json" ), "contract_diff" )
    assert code == 1 and check[ "pass" ] is False
    assert check[ "output" ][ "findings" ][ 0 ].startswith( "HEADING MISSING: pkg/mod.py add Requires" )
    assert "HEADING MISSING" in check[ "output" ][ "table" ]


def test_a_file_that_does_not_parse_fails_compile_and_checks_that_cannot_run_say_so( repo, tmp_path ):
    ( repo / "pkg" / "mod.py" ).write_text( "def (:\n", encoding="utf-8" )
    code, text = _run( repo, tmp_path / "out" )
    result = _read( tmp_path / "out", "result.json" )
    assert code == 1
    compiled = _check( result, "py_compile" )
    assert compiled[ "pass" ] is False and compiled[ "ran" ] is True and compiled[ "output" ][ 0 ][ "error" ].startswith( "SyntaxError" )
    contract = _check( result, "contract_diff" )
    assert contract[ "pass" ] is False and contract[ "ran" ] is False and contract[ "output" ].startswith( "did not run: SyntaxError" )
    assert "FAIL contract_diff (did not run)" in text
    assert result[ "refusals" ] == [ { "file": "pkg/mod.py", "reason": "new text does not parse: invalid syntax" } ]
    assert "REFUSED pkg/mod.py: new text does not parse: invalid syntax\n" in text
    assert result[ "counts" ][ "docstrings" ] == 1


def test_a_file_that_is_not_utf8_cannot_be_linted_and_is_refused( repo, tmp_path ):
    ( repo / "pkg" / "mod.py" ).write_bytes( b'"""caf\xe9."""\n' )
    code, _ = _run( repo, tmp_path / "out" )
    result  = _read( tmp_path / "out", "result.json" )
    assert code == 1 and _check( result, "docstring_lint" )[ "ran" ] is False
    assert result[ "refusals" ][ 0 ][ "reason" ].startswith( "could not be compared: UnicodeDecodeError" )


def test_only_the_packages_own_files_count( repo, tmp_path ):
    ( repo / "pkg" / "sub" / "deep.py" ).write_text( '"""Deep, changed NEVER."""\n', encoding="utf-8" )
    ( repo / "pkg" / "test_mod.py" ).write_text( '"""A NEVER test."""\ndef broken(:\n', encoding="utf-8" )
    ( repo / "pkg" / "notes.md" ).write_text( "changed\n", encoding="utf-8" )
    ( repo / "pkg" / "mod.py" ).write_text( CLEAN_MOD, encoding="utf-8" )
    code, _ = _run( repo, tmp_path / "out", package="pkg/" )
    result  = _read( tmp_path / "out", "result.json" )
    assert code == 0 and result[ "changed_files" ] == [ "pkg/mod.py" ] and result[ "package" ] == "pkg"


def test_a_data_file_in_the_package_fails_docs_only_diff( repo, tmp_path ):
    ( repo / "pkg" / "data.json" ).write_text( "{ not python\n", encoding="utf-8" )
    code, _ = _run( repo, tmp_path / "out" )
    result  = _read( tmp_path / "out", "result.json" )
    assert code == 1 and result[ "changed_files" ] == [ "pkg/data.json" ]
    assert "file type not checked" in _check( result, "docs_only_diff" )[ "output" ][ 0 ][ "failure" ]
    assert _check( result, "contract_diff" )[ "ran" ] is True and _check( result, "contract_diff" )[ "pass" ] is True


def test_a_deleted_file_and_an_added_file_are_refused( repo, tmp_path ):
    ( repo / "pkg" / "mod.py" ).unlink()
    ( repo / "pkg" / "fresh.py" ).write_text( '"""Fresh."""\n', encoding="utf-8" )
    code, _ = _run( repo, tmp_path / "out" )
    result  = _read( tmp_path / "out", "result.json" )
    reasons = { r[ "file" ]: r for r in result[ "refusals" ] }
    assert code == 1
    assert reasons[ "pkg/mod.py" ][ "removed" ][ 0 ] == "Module:<module>#0" and reasons[ "pkg/fresh.py" ][ "added" ] == [ "Module:<module>#0" ]
    assert _check( result, "py_compile" )[ "pass" ] is True
    assert _check( result, "docstring_lint" )[ "ran" ] is True
    failures = { row[ "path" ]: row[ "failure" ] for row in _check( result, "docs_only_diff" )[ "output" ] }
    assert failures == { "pkg/mod.py": "file deleted", "pkg/fresh.py": "file added" }


def test_match_docstrings_old_text_that_does_not_parse_is_refused():
    pairs, refusal = pc.match_docstrings( "a.py", "def (:\n", '"""x."""\n' )
    assert pairs == [] and refusal == { "file": "a.py", "reason": "old text does not parse: invalid syntax" }


def test_keyed_docstrings_number_repeated_names_and_none_is_empty():
    source = 'class A:\n    def __init__( self ):\n        """One."""\n\nclass B:\n    def __init__( self ):\n        """Two."""\n'
    assert pc.keyed_docstrings( source ) == { ( "FunctionDef", "__init__", 0 ): "One.", ( "FunctionDef", "__init__", 1 ): "Two." }
    assert pc.keyed_docstrings( None ) == {}


def test_run_records_a_check_that_raises_as_did_not_run():
    def boom(): raise OSError( "gone" )
    assert pc._run( "x", boom ) == { "name": "x", "pass": False, "ran": False, "output": "did not run: OSError: gone" }
    assert pc._run( "x", lambda: ( 1, [] ) ) == { "name": "x", "pass": True, "ran": True, "output": [] }


def test_a_base_that_does_not_resolve_and_an_empty_package_refuse_with_a_full_result_and_no_pairs_file( repo, tmp_path ):
    keys = set( _read( _out_of( repo, tmp_path, "ok" ), "result.json" ) )
    code, text = _run( repo, tmp_path / "a", base="no-such-rev" )
    result = _read( tmp_path / "a", "result.json" )
    assert code == 2 and text.startswith( "REFUSED: git rev-parse" ) and result[ "pass" ] is False and result[ "refused" ].startswith( "git rev-parse" )
    assert set( result ) == keys | { "refused" } and result[ "checks" ] == [] and result[ "refusals" ] == [] and result[ "changed_files" ] == []
    assert result[ "counts" ] == { "docstrings": 0, "docstrings_changed": 0, "words_before": 0, "words_after": 0 } and result[ "base" ] is None
    assert [ p.name for p in ( tmp_path / "a" ).iterdir() ] == [ "result.json" ]
    code, text = _run( repo, tmp_path / "b", package="nowhere/" )
    result = _read( tmp_path / "b", "result.json" )
    assert code == 2 and "no in-scope .py files directly in nowhere" in text and result[ "refused" ] == "no in-scope .py files directly in nowhere" and result[ "package" ] == "nowhere"
    assert set( result ) == keys | { "refused" } and not ( tmp_path / "b" / "pairs.json" ).exists()


def test_main_defaults_to_stdout_and_sys_argv( repo, tmp_path, monkeypatch, capsys ):
    monkeypatch.setattr( "sys.argv", [ "x", "--repo-root", str( repo ), "--base", "HEAD", "--package", "pkg", "--out", str( tmp_path / "o" ) ] )
    assert pc.main() == 0
    assert "PASS pkg at base" in capsys.readouterr().out
    assert ( tmp_path / "o" / "result.json" ).exists()


def test_a_tag_as_base_resolves_to_the_commit_sha( repo, tmp_path ):
    _git( repo, "tag", "-a", "v1", "-m", "tag" )
    _run( repo, tmp_path / "out", base="v1" )
    assert _read( tmp_path / "out", "result.json" )[ "base" ] == _git( repo, "rev-parse", "HEAD" )


def test_a_dead_design_path_is_a_lint_finding_because_the_linter_gets_the_repo_root( repo, tmp_path ):
    ( repo / "pkg" / "mod.py" ).write_text( CLEAN_MOD.replace( "A box.", "A box.\n\n    Design: src/nowhere.md" ), encoding="utf-8" )
    _run( repo, tmp_path / "out" )
    output = _check( _read( tmp_path / "out", "result.json" ), "docstring_lint" )[ "output" ]
    assert any( "dead-design" in line for line in output )


@pytest.mark.parametrize( "error", [ KeyError( "odd" ), RuntimeError( "git failed" ), AttributeError( "x" ) ] )
def test_a_check_that_raises_anything_is_did_not_run_and_result_json_is_still_written( repo, tmp_path, monkeypatch, error ):
    def boom( *args ): raise error
    monkeypatch.setattr( pc.contract_diff, "diff_contracts", boom )
    ( repo / "pkg" / "mod.py" ).write_text( CLEAN_MOD, encoding="utf-8" )
    code, text = _run( repo, tmp_path / "out" )
    result = _read( tmp_path / "out", "result.json" )
    check  = _check( result, "contract_diff" )
    assert code == 1 and result[ "pass" ] is False and check[ "ran" ] is False and check[ "pass" ] is False
    assert check[ "output" ].startswith( f"did not run: {type( error ).__name__}" )
    assert all( c[ "ran" ] for c in result[ "checks" ] if c[ "name" ] != "contract_diff" ) and "FAIL contract_diff (did not run)" in text


def test_a_comparison_that_raises_is_a_refusal_not_a_crash( repo, tmp_path, monkeypatch ):
    def boom( *args ): raise KeyError( "odd" )
    monkeypatch.setattr( pc, "match_docstrings", boom )
    ( repo / "pkg" / "mod.py" ).write_text( CLEAN_MOD, encoding="utf-8" )
    code, _ = _run( repo, tmp_path / "out" )
    assert code == 1 and _read( tmp_path / "out", "result.json" )[ "refusals" ] == [ { "file": "pkg/mod.py", "reason": "could not be compared: KeyError: 'odd'" } ]


def test_lint_reads_every_package_file_not_only_the_last_or_the_changed_ones( tmp_path, repo ):
    ( repo / "pkg" / "a_first.py" ).write_text( '"""A NEVER thing."""\n', encoding="utf-8" )
    _git( repo, "add", "." )
    _git( repo, "commit", "-qm", "an unchanged file with a finding" )
    ( repo / "pkg" / "mod.py" ).write_text( CLEAN_MOD, encoding="utf-8" )
    code, _ = _run( repo, tmp_path / "out" )
    check   = _check( _read( tmp_path / "out", "result.json" ), "docstring_lint" )
    assert code == 1 and check[ "pass" ] is False and check[ "output" ] == [ "pkg/a_first.py:1: caps: ALL-CAPS word NEVER" ]


def test_lint_reaches_a_new_untracked_file( repo, tmp_path ):
    ( repo / "pkg" / "zz_new.py" ).write_text( '"""A NEVER thing."""\n', encoding="utf-8" )
    _run( repo, tmp_path / "out" )
    output = _check( _read( tmp_path / "out", "result.json" ), "docstring_lint" )[ "output" ]
    assert output == [ "pkg/zz_new.py:1: caps: ALL-CAPS word NEVER" ]


def test_source_with_a_null_byte_fails_compile_without_crashing( repo, tmp_path ):
    ( repo / "pkg" / "mod.py" ).write_bytes( b'"""x."""\x00\n' )
    code, _ = _run( repo, tmp_path / "out" )
    result  = _read( tmp_path / "out", "result.json" )
    assert code == 1 and _check( result, "py_compile" )[ "pass" ] is False
