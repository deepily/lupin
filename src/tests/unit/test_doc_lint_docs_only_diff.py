"""
docs_only_diff: a docs-only change must pass and a one-token code change must fail.

Covers both languages, the first-difference naming, and the git-driven CLI in a scratch repo.
"""

import io
import subprocess

import pytest

from cosa.repo.doc_lint import docs_only_diff as dod

PY_OLD = '''"""Module doc."""

class A:
    """Class doc."""

    def f( self, x ):
        """Old doc."""
        # old comment
        return x + 1


def g():
    """Only a docstring."""
'''

PY_DOCS = '''"""A much better module doc.

Requires:
    - nothing
"""

class A:
    def f( self, x ):
        """New doc."""
        return x + 1   # trailing comment


def g():
    pass
'''

DART_OLD = '''/// Old doc.
class A {
  // plain
  int f( int x ) { return x + 1; }  /* inline /* nested */ */
  String s = "// not a comment";
  String r = r'/* raw */';
}
'''

DART_DOCS = '''/// New doc line one.
/// New doc line two.
class A {
  int f( int x ) {
    return x + 1; // why
  }
  String s = "// not a comment";
  String r = r'/* raw */';
}
'''


def test_python_docs_only_change_passes():
    assert dod.python_difference( PY_OLD, PY_DOCS ) is None


def test_python_one_token_code_change_fails_and_names_the_node():
    changed = PY_DOCS.replace( "x + 1", "x + 2" )
    found   = dod.python_difference( PY_OLD, changed )
    assert found is not None
    assert "1 became 2" in found


def test_python_first_difference_is_the_earliest_not_the_last():
    two = PY_OLD.replace( "x + 1", "x + 2" ).replace( "class A", "class B" )
    found = dod.python_difference( PY_OLD, two )
    assert "'A' became 'B'" in found


def test_python_node_type_swap_and_length_changes_are_named():
    assert "Pass" in dod.python_difference( "def f():\n    pass\n", "def f():\n    return 1\n" )
    assert "added" in dod.python_difference( "x = 1\n", "x = 1\ny = 2\n" )
    assert "removed" in dod.python_difference( "x = 1\ny = 2\n", "x = 1\n" )


def test_python_syntax_error_names_the_side():
    assert dod.python_difference( "x = (\n", "x = 1\n" ).startswith( "old file does not parse" )
    assert dod.python_difference( "x = 1\n", "x = (\n" ).startswith( "new file does not parse" )


def test_python_docstring_only_function_gains_and_loses_a_docstring():
    assert dod.python_difference( "def f():\n    pass\n", 'def f():\n    """d"""\n' ) is None
    assert dod.python_difference( 'async def f():\n    """d"""\n', "async def f():\n    pass\n" ) is None


def test_python_a_non_docstring_string_statement_is_code():
    assert dod.python_difference( "def f():\n    x = 1\n    'late'\n", "def f():\n    x = 1\n" ) is not None


def test_dart_docs_only_change_passes():
    assert dod.dart_difference( DART_OLD, DART_DOCS ) is None


def test_dart_one_token_code_change_fails_with_line():
    found = dod.dart_difference( DART_OLD, DART_DOCS.replace( "x + 1", "x + 2" ) )
    assert "'1' became '2'" in found and "line 5" in found


def test_dart_string_contents_are_code():
    found = dod.dart_difference( DART_OLD, DART_DOCS.replace( "// not a comment", "// not a comments" ) )
    assert found is not None and "not a comment" in found


def test_dart_added_and_removed_tokens_are_named():
    assert dod.dart_difference( "a b", "a b c" ).startswith( "added token 'c'" )
    assert dod.dart_difference( "a b c", "a b" ).startswith( "removed token 'c'" )


def test_dart_tokens_skip_comments_and_track_lines():
    toks = dod.dart_tokens( "a // x\n/* y\nz */ b\n'q\nr' c" )
    assert [ t for _, t in toks ][ :2 ] == [ "a", "b" ]
    assert toks[ 1 ][ 0 ] == 3


def test_dart_unterminated_block_comment_and_line_comment_at_eof():
    assert dod.dart_tokens( "a /* open" ) == [ ( 1, "a" ) ]
    assert dod.dart_tokens( "a // tail" ) == [ ( 1, "a" ) ]


def test_file_difference_added_deleted_and_dispatch():
    assert dod.file_difference( "a.py", None, "x = 1\n" ) == "file added"
    assert dod.file_difference( "a.dart", "a", None ) == "file deleted"
    assert dod.file_difference( "a.py", "x = 1\n", "x = 2\n" ) is not None
    assert dod.file_difference( "a.dart", "a", "a // c" ) is None


def _git( root, *args ):
    res = subprocess.run( [ "git", "-C", str( root ), "-c", "user.email=t@t", "-c", "user.name=t", *args ], capture_output=True, text=True )
    assert res.returncode == 0, res.stderr
    return res.stdout.strip()


@pytest.fixture
def repo( tmp_path ):
    _git( tmp_path, "init", "-q" )
    ( tmp_path / "a.py" ).write_text( PY_OLD, encoding="utf-8" )
    ( tmp_path / "b.dart" ).write_text( DART_OLD, encoding="utf-8" )
    ( tmp_path / "notes.md" ).write_text( "x\n", encoding="utf-8" )
    _git( tmp_path, "add", "." )
    _git( tmp_path, "commit", "-qm", "base" )
    return tmp_path


def _run( root, *extra ):
    out = io.StringIO()
    rc  = dod.main( [ "--base", "HEAD", "--repo-root", str( root ), *extra ], out=out )
    return rc, out.getvalue()


def test_cli_docs_only_working_tree_passes_and_ignores_other_files( repo ):
    ( repo / "a.py" ).write_text( PY_DOCS, encoding="utf-8" )
    ( repo / "b.dart" ).write_text( DART_DOCS, encoding="utf-8" )
    ( repo / "notes.md" ).write_text( "changed\n", encoding="utf-8" )
    rc, text = _run( repo )
    assert rc == 0
    assert "PASS a.py" in text and "PASS b.dart" in text and "notes.md" not in text
    assert "2 passed, 0 failed" in text


def test_cli_one_token_code_change_fails_that_file_only( repo ):
    ( repo / "a.py" ).write_text( PY_DOCS.replace( "x + 1", "x + 2" ), encoding="utf-8" )
    ( repo / "b.dart" ).write_text( DART_DOCS, encoding="utf-8" )
    rc, text = _run( repo )
    assert rc == 1
    assert "FAIL a.py" in text and "PASS b.dart" in text and "1 passed, 1 failed" in text


def test_cli_between_two_revisions_and_added_deleted_files( repo ):
    ( repo / "a.py" ).write_text( PY_DOCS, encoding="utf-8" )
    ( repo / "c.py" ).write_text( "x = 1\n", encoding="utf-8" )
    ( repo / "b.dart" ).unlink()
    _git( repo, "add", "-A" )
    _git( repo, "commit", "-qm", "head" )
    out = io.StringIO()
    rc  = dod.main( [ "--base", "HEAD~1", "--head", "HEAD", "--repo-root", str( repo ) ], out=out )
    text = out.getvalue()
    assert rc == 1
    assert "PASS a.py" in text and "FAIL c.py: file added" in text and "FAIL b.dart: file deleted" in text


def test_cli_no_changes_passes( repo ):
    rc, text = _run( repo )
    assert rc == 0 and "0 passed, 0 failed" in text


def test_cli_bad_revision_raises( repo ):
    with pytest.raises( RuntimeError, match="git diff" ):
        dod.main( [ "--base", "nope", "--repo-root", str( repo ) ], out=io.StringIO() )


def test_main_defaults_to_stdout_and_dunder_main_guard( repo, capsys ):
    assert dod.main( [ "--base", "HEAD", "--repo-root", str( repo ) ] ) == 0
    assert "0 passed" in capsys.readouterr().out


def test_cli_file_deleted_in_working_tree_fails( repo ):
    ( repo / "a.py" ).unlink()
    rc, text = _run( repo )
    assert rc == 1 and "FAIL a.py: file deleted" in text


def test_python_added_named_node_is_named_with_its_name():
    found = dod.python_difference( "def f():\n    pass\n", "def f():\n    pass\n\n\ndef g():\n    pass\n" )
    assert "added FunctionDef(g) line 5" in found


# ---- mutation check: each mutant of the module must redden the named test ----

MUTANTS = [
    ( "node.body = body[ 1 : ] or [ ast.Pass() ]", "node.body = body", "test_python_docs_only_change_passes" ),
    ( "    if old != new: return f\"{path}: {old!r} became {new!r}\"\n", "", "test_python_one_token_code_change_fails_and_names_the_node" ),
    ( "elif source.startswith( \"//\", i ):", "elif False:", "test_dart_docs_only_change_passes" ),
    ( "    if len( old ) != len( new ):\n        longer = old if len( old ) > len( new ) else new\n        line, text", "    if False:\n        longer = old if len( old ) > len( new ) else new\n        line, text", "test_dart_added_and_removed_tokens_are_named" ),
    ( "if old_source is None: return \"file added\"", "if False: return \"file added\"", "test_file_difference_added_deleted_and_dispatch" ),
]


def _mutant_module( old, new ):
    path   = dod.__file__
    source = open( path, encoding="utf-8" ).read()
    assert source.count( old ) == 1, f"anchor must match exactly once: {old!r}"
    module = type( dod )( dod.__name__ )
    module.__file__, module.__package__ = path, dod.__package__
    exec( compile( source.replace( old, new ), path, "exec" ), module.__dict__ )
    return module


@pytest.mark.parametrize( "old,new,named_test", MUTANTS )
def test_each_mutant_reddens_its_named_test( monkeypatch, old, new, named_test ):
    this = globals()
    this[ named_test ]()
    monkeypatch.setitem( this, "dod", _mutant_module( old, new ) )
    with pytest.raises( Exception ):  # a crash reddens the test as surely as a failed assert
        this[ named_test ]()
