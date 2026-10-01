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


def test_python_constant_type_change_is_code():
    for old, new in ( ( "x = 1", "x = True" ), ( "x = 0", "x = False" ), ( "t = 1", "t = 1.0" ), ( "z = 0.0", "z = -0.0" ) ):
        found = dod.python_difference( old + "\n", new + "\n" )
        assert found is not None and "became" in found, ( old, new )
    assert dod.python_difference( "x = 1\n", "x = 1\n" ) is None


PY_DIRECTIVES = [
    "x = 1  # pragma: no cover -- why\n",
    "x = f()  # type: ignore\n",
    "# -*- coding: latin-1 -*-\nx = 1\n",
    "#!/usr/bin/env python3\nx = 1\n",
    "x = f()  # noqa: E501\n",
]


@pytest.mark.parametrize( "source", PY_DIRECTIVES )
def test_python_each_directive_kind_is_code( source ):
    without = "\n".join( line.split( "#" )[ 0 ].rstrip() for line in source.split( "\n" ) if line.split( "#" )[ 0 ].strip() ) + "\n"
    assert dod.python_difference( source, without ) is not None


def test_python_directive_comments_are_code():
    assert "directive comment removed" in dod.python_difference( "x = 1  # pragma: no cover\n", "x = 1\n" )
    assert "directive comment added" in dod.python_difference( "x = 1\n", "x = 1  # type: ignore\n" )
    assert "became" in dod.python_difference( "x = 1  # noqa: E501\n", "x = 1  # noqa: E999\n" )
    assert dod.python_difference( "x = 1  # old words\n", "x = 1  # entirely new words\n" ) is None
    assert dod.python_directives( 'x = "# noqa"\n' ) == []
    assert "removed: '# noqa: b'" in dod.python_difference( "x = 1  # noqa: a\ny = 2  # noqa: b\n", "x = 1  # noqa: a\ny = 2\n" )


def test_dart_line_directive_comments_are_code():
    assert "directive comment removed" in dod.dart_difference( "// @dart=2.9\nclass A {}\n", "class A {}\n" )
    assert "directive comment removed" in dod.dart_difference( "a(); // coverage:ignore-line\n", "a();\n" )
    assert "directive comment added" in dod.dart_difference( "a();\n", "a(); // ignore: unused_element\n" )
    assert "became" in dod.dart_difference( "// ignore_for_file: a\n", "// ignore_for_file: b\n" )
    assert dod.dart_difference( "a(); // old words\n", "a(); // new words\n" ) is None
    assert dod.dart_difference( "a(); // ignore\n", "a();\n" ) is None


def test_dart_block_directive_comments_are_code():
    assert "directive comment removed" in dod.dart_difference( "/* ignore: x */ a();\n", "a();\n" )
    assert dod.dart_difference( "/* plain */ a();\n", "a();\n" ) is None


def test_cli_markdown_changes_are_ignored_and_other_types_are_unchecked( repo ):
    ( repo / "notes.md" ).write_text( "changed\n", encoding="utf-8" )
    ( repo / "conf.ini" ).write_text( "[a]\nk = 2\n", encoding="utf-8" )
    _git( repo, "add", "conf.ini" )
    rc, text = _run( repo )
    assert rc == 1
    assert "FAIL conf.ini: file type not checked" in text and "notes.md" not in text


def test_cli_mode_only_change_fails( repo ):
    ( repo / "a.py" ).chmod( 0o755 )
    rc, text = _run( repo )
    assert rc == 1 and "FAIL a.py: mode changed 100644 -> 100755" in text


def test_cli_non_ascii_path_is_checked( repo ):
    ( repo / "\u00e9.py" ).write_text( "x = 1\n", encoding="utf-8" )
    _git( repo, "add", "-A" )
    _git( repo, "commit", "-qm", "accent" )
    ( repo / "\u00e9.py" ).write_text( "x = 2\n", encoding="utf-8" )
    rc, text = _run( repo )
    assert rc == 1 and "FAIL \u00e9.py" in text and "1 became 2" in text


def test_cli_untracked_new_code_file_fails( repo ):
    ( repo / "fresh.py" ).write_text( "x = 1\n", encoding="utf-8" )
    rc, text = _run( repo )
    assert rc == 1 and "FAIL fresh.py: file added" in text


# ---- mutation check: each mutant of the module must redden the named test ----

MUTANTS = [
    ( "node.body = body[ 1 : ] or [ ast.Pass() ]", "node.body = body", "test_python_docs_only_change_passes" ),
    ( "    if type( old ) is not type( new ) or repr( old ) != repr( new ): return f\"{path}: {old!r} became {new!r}\"\n", "", "test_python_one_token_code_change_fails_and_names_the_node" ),
    ( "type( old ) is not type( new ) or repr( old ) != repr( new )", "old != new", "test_python_constant_type_change_is_code" ),
    ( "return [ c for c in comments if PY_DIRECTIVE.match( c ) ]", "return []", "test_python_directive_comments_are_code" ),
    ( "if directives is not None and DART_DIRECTIVE.match( source[ i : end ] ):", "if False:", "test_dart_line_directive_comments_are_code" ),
    ( "if directives is not None and DART_DIRECTIVE.match( source[ start : i ] ):", "if False:", "test_dart_block_directive_comments_are_code" ),
    ( "        if path.endswith( DOC_SUFFIX ): continue\n", "", "test_cli_markdown_changes_are_ignored_and_other_types_are_unchecked" ),
    ( "if not path.endswith( SUFFIXES ): return \"file type not checked, only .py and .dart are compared\"", "if False: return None", "test_cli_markdown_changes_are_ignored_and_other_types_are_unchecked" ),
    ( "if \"000000\" not in modes and old_mode != new_mode:", "if False:", "test_cli_mode_only_change_fails" ),
    ( "\"diff\", \"--raw\", \"-z\",", "\"diff\", \"--name-status\",", "test_cli_non_ascii_path_is_checked" ),
    ( "    if head is None:\n        for path in", "    if False:\n        for path in", "test_cli_untracked_new_code_file_fails" ),
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
def test_each_mutant_reddens_its_named_test( monkeypatch, repo, old, new, named_test ):
    this = globals()
    code = this[ named_test ].__code__
    kwargs = { "repo": repo } if "repo" in code.co_varnames[ : code.co_argcount ] else {}
    this[ named_test ]( **kwargs )
    monkeypatch.setitem( this, "dod", _mutant_module( old, new ) )
    with pytest.raises( Exception ):  # a crash reddens the test as surely as a failed assert
        this[ named_test ]( **kwargs )
