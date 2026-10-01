"""
contract_diff: every dropped Requires, Ensures or Raises item must be listed.

Covers the docstring parser, the per-function diff, the git-driven CLI, and a mutation check
that each key line of the module is guarded by a named test.
"""

import io
import json
import subprocess

import pytest

from cosa.repo.doc_lint import contract_diff as cd

OLD = '''
def f( x ):
    """
    Do f.

    Requires:
        - x is an int
        - x is positive,
          and fits in a byte

    Ensures:
        - returns x
        - never mutates x

    Raises:
        - ValueError when x is negative
    """
    return x


class K:
    def m( self ):
        """
        Method.

        Ensures:
            - returns None
        """

    async def a( self ):
        """
        Raises:
            - nothing
        """


def undocumented():
    pass


def gone():
    """
    Requires:
        - old clause
    """
'''

NEW = '''
def f( x ):
    """
    Do f better.

    Requires:
        - x is an int
        - x is positive, and fits in a byte

    Ensures:
        - returns x

    Raises:
        - ValueError when x is negative
        - TypeError when x is not an int
    """
    return x


class K:
    def m( self ):
        """Method with no sections."""

    async def a( self ):
        """
        Raises:
            - nothing
        """


def brand_new():
    """
    Ensures:
        - fresh
    """
'''


def test_parse_joins_continuations_and_ends_sections():
    c = cd.parse_contract( OLD.split( '"""' )[ 1 ] )
    assert c[ "Requires" ] == [ "x is an int", "x is positive, and fits in a byte" ]
    assert c[ "Ensures" ] == [ "returns x", "never mutates x" ]
    assert c[ "Raises" ] == [ "ValueError when x is negative" ]


def test_parse_none_and_prose_only_docstrings_are_empty():
    assert cd.parse_contract( None ) == { "Requires": [], "Ensures": [], "Raises": [] }
    assert cd.parse_contract( "Just prose.\n\nMore prose with - dash." )[ "Requires" ] == []


def test_parse_section_ends_at_dedent_without_blank_line():
    c = cd.parse_contract( "Summary.\n\nRequires:\n    - a\nTrailing prose\n    - not an item\n" )
    assert c[ "Requires" ] == [ "a" ]


def test_function_contracts_qualify_methods_and_cover_async_and_undocumented():
    found = cd.function_contracts( OLD )
    assert set( found ) == { "f", "K.m", "K.a", "undocumented", "gone" }
    assert found[ "undocumented" ] == { "Requires": [], "Ensures": [], "Raises": [] }
    assert found[ "K.m" ][ "Ensures" ] == [ "returns None" ]


def test_diff_lists_every_drop_and_ignores_additions_and_new_functions():
    rows = {  ( r[ "function" ], r[ "section" ] ) : r for r in cd.diff_contracts( OLD, NEW ) }
    assert rows[ ( "f", "Requires" ) ][ "dropped" ] == []
    assert rows[ ( "f", "Ensures" ) ] == { "function": "f", "section": "Ensures", "before": 2, "after": 1, "dropped": [ "never mutates x" ] }
    assert rows[ ( "f", "Raises" ) ][ "before" ] == 1 and rows[ ( "f", "Raises" ) ][ "after" ] == 2
    assert rows[ ( "K.m", "Ensures" ) ][ "dropped" ] == [ "returns None" ]
    assert rows[ ( "gone", "Requires" ) ][ "dropped" ] == [ "old clause" ] and rows[ ( "gone", "Requires" ) ][ "after" ] == 0
    assert not any( fn == "brand_new" for fn, _ in rows )
    assert ( "undocumented", "Requires" ) not in rows


def test_diff_with_absent_sides():
    assert cd.diff_contracts( None, NEW ) == []
    assert all( r[ "after" ] == 0 for r in cd.diff_contracts( OLD, None ) )


def test_reword_counts_as_a_drop_by_text():
    rows = cd.diff_contracts( 'def f():\n    """\n    Ensures:\n        - returns 1\n    """\n', 'def f():\n    """\n    Ensures:\n        - returns one\n    """\n' )
    assert rows[ 0 ][ "before" ] == rows[ 0 ][ "after" ] == 1 and rows[ 0 ][ "dropped" ] == [ "returns 1" ]


def _git( root, *args ):
    res = subprocess.run( [ "git", "-C", str( root ), "-c", "user.email=t@t", "-c", "user.name=t", *args ], capture_output=True, text=True )
    assert res.returncode == 0, res.stderr
    return res.stdout.strip()


@pytest.fixture
def repo( tmp_path ):
    _git( tmp_path, "init", "-q" )
    ( tmp_path / "a.py" ).write_text( OLD, encoding="utf-8" )
    ( tmp_path / "same.py" ).write_text( "x = 1\n", encoding="utf-8" )
    ( tmp_path / "b.dart" ).write_text( "a\n", encoding="utf-8" )
    _git( tmp_path, "add", "." )
    _git( tmp_path, "commit", "-qm", "base" )
    ( tmp_path / "a.py" ).write_text( NEW, encoding="utf-8" )
    ( tmp_path / "same.py" ).write_text( "x = 2\n", encoding="utf-8" )
    ( tmp_path / "b.dart" ).write_text( "b\n", encoding="utf-8" )
    return tmp_path


def _run( root, *extra ):
    out = io.StringIO()
    rc  = cd.main( [ "--base", "HEAD", "--repo-root", str( root ), *extra ], out=out )
    return rc, out.getvalue()


def test_cli_table_lists_drops_and_skips_files_without_contracts( repo ):
    rc, text = _run( repo )
    assert rc == 0
    assert text.startswith( "| file | function | section | before | after | dropped |" )
    assert "| a.py | f | Ensures | 2 | 1 | never mutates x |" in text
    assert "| a.py | f | Requires | 2 | 2 | - |" in text
    assert "same.py" not in text and "b.dart" not in text


def test_cli_strict_exits_one_when_anything_dropped( repo ):
    assert _run( repo, "--strict" )[ 0 ] == 1


def test_cli_strict_exits_zero_when_nothing_dropped( repo ):
    ( repo / "a.py" ).write_text( OLD.replace( "Do f.", "Do f again." ), encoding="utf-8" )
    assert _run( repo, "--strict" )[ 0 ] == 0


def test_cli_json_and_head_revision( repo ):
    _git( repo, "add", "-A" )
    _git( repo, "commit", "-qm", "head" )
    out = io.StringIO()
    rc  = cd.main( [ "--base", "HEAD~1", "--head", "HEAD", "--repo-root", str( repo ), "--json" ], out=out )
    data = json.loads( out.getvalue() )
    assert rc == 0 and list( data ) == [ "a.py" ]
    assert { "function": "f", "section": "Ensures", "before": 2, "after": 1, "dropped": [ "never mutates x" ] } in data[ "a.py" ]


def test_main_defaults_to_stdout( repo, capsys ):
    cd.main( [ "--base", "HEAD", "--repo-root", str( repo ) ] )
    assert "| file |" in capsys.readouterr().out


def test_cli_bad_revision_raises( repo ):
    with pytest.raises( RuntimeError, match="git diff" ):
        cd.main( [ "--base", "nope", "--repo-root", str( repo ) ], out=io.StringIO() )


# ---- mutation check: each mutant of the module must redden its named test ----

MUTANTS = [
    ( "if not before and not after: continue", "if False: continue", "test_diff_lists_every_drop_and_ignores_additions_and_new_functions" ),
    ( "[ item for item in before if item not in after ]", "[]", "test_diff_lists_every_drop_and_ignores_additions_and_new_functions" ),
    ( "contract[ current ][ -1 ] += \" \" + line", "pass", "test_parse_joins_continuations_and_ends_sections" ),
    ( "elif not line or ( current is not None and depth <= indent ):", "elif not line:", "test_parse_section_ends_at_dedent_without_blank_line" ),
    ( "if not isinstance( child, ast.ClassDef ): found[ name ]", "if True: found[ name ]", "test_function_contracts_qualify_methods_and_cover_async_and_undocumented" ),
    ( "return 1 if args.strict and dropped else 0", "return 0", "test_cli_strict_exits_one_when_anything_dropped" ),
]


def _mutant_module( old, new ):
    path   = cd.__file__
    source = open( path, encoding="utf-8" ).read()
    assert source.count( old ) == 1, f"anchor must match exactly once: {old!r}"
    module = type( cd )( cd.__name__ )
    module.__file__, module.__package__ = path, cd.__package__
    exec( compile( source.replace( old, new ), path, "exec" ), module.__dict__ )
    return module


@pytest.mark.parametrize( "old,new,named_test", MUTANTS )
def test_each_mutant_reddens_its_named_test( monkeypatch, repo, old, new, named_test ):
    this = globals()
    kwargs = { "repo": repo } if "repo" in this[ named_test ].__code__.co_varnames[ : this[ named_test ].__code__.co_argcount ] else {}
    this[ named_test ]( **kwargs )
    monkeypatch.setitem( this, "cd", _mutant_module( old, new ) )
    with pytest.raises( Exception ):  # a crash reddens the test as surely as a failed assert
        this[ named_test ]( **kwargs )
