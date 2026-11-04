"""
W6: finding where a key symbol is called, to show beside its source.
"""
import subprocess

import pytest

from cosa.repo.labelling import call_sites as cs


@pytest.fixture
def tree( tmp_path ):
    """Return a git work tree with a definition, three callers, a test and a broken file."""
    ( tmp_path / "src" ).mkdir()
    ( tmp_path / "src" / "tests" ).mkdir()
    files = {
        "src/own.py"          : "def key( x ):\n    return key( x - 1 )\n",
        "src/a.py"            : "from own import key\n\nvalue = key( 1 )\nother = unrelated( 2 )\n",
        "src/b.py"            : "class B:\n    def run( self ):\n        return self.key( 2 ) + helper.key( 3 )\n",
        "src/c.py"            : "x = [ key( i ) for i in range( 3 ) ]\nprint( key )\n",
        "src/tests/test_k.py" : "key( 1 )\n",
        "src/test_top.py"     : "key( 1 )\n",
        "src/broken.py"       : "def (\n",
    }
    for rel, text in files.items(): ( tmp_path / rel ).write_text( text )
    subprocess.run( [ "git", "init", "-q" ], cwd=tmp_path, check=True )
    subprocess.run( [ "git", "add", "-A" ], cwd=tmp_path, check=True )
    return tmp_path


def test_tracked_python_files_lists_sorted_tracked_py_files_only( tree ):
    ( tree / "src" / "untracked.py" ).write_text( "key( 1 )\n" )
    ( tree / "notes.txt" ).write_text( "x" )
    got = cs.tracked_python_files( tree )
    assert got == sorted( got ) and "src/a.py" in got and "src/untracked.py" not in got and "notes.txt" not in got


def test_tracked_python_files_raises_outside_a_git_tree( tmp_path ):
    with pytest.raises( subprocess.CalledProcessError ): cs.tracked_python_files( tmp_path )


@pytest.mark.parametrize( "path, expected", [ ( "src/tests/test_k.py", True ), ( "src/test_top.py", True ), ( "src/a.py", False ), ( "src/latest.py", False ), ( "tests/x.py", True ) ] )
def test_is_test_path( path, expected ):
    assert cs.is_test_path( path ) is expected


def test_calls_in_finds_bare_and_attribute_calls_not_mentions_or_other_names():
    assert cs.calls_in( "key( 1 )\nobj.key( 2 )\nprint( key )\nx = other( key )\nkeys( 3 )\n", "key" ) == [ 1, 2 ]
    assert cs.calls_in( "def (", "key" ) == []
    assert cs.calls_in( "f()()", "key" ) == []


def test_find_call_sites_returns_path_line_and_source_for_callers_and_skips_own_tests_and_broken_files( tree ):
    files = cs.tracked_python_files( tree )
    got   = cs.find_call_sites( "key", "src/own.py", files, tree )
    assert got == [ "src/a.py:3  value = key( 1 )", "src/b.py:3  return self.key( 2 ) + helper.key( 3 )", "src/c.py:1  x = [ key( i ) for i in range( 3 ) ]" ]


def test_find_call_sites_stops_at_the_limit( tree ):
    files = cs.tracked_python_files( tree )
    assert len( cs.find_call_sites( "key", "src/own.py", files, tree, limit=2 ) ) == 2
    assert cs.find_call_sites( "key", "src/own.py", files, tree, limit=4 )[ -1 ].startswith( "src/c.py:1" )
    assert len( cs.find_call_sites( "key", "src/own.py", files, tree, limit=1 ) ) == 1


def test_find_call_sites_default_limit_is_five():
    assert cs.LIMIT == 5


def test_find_call_sites_with_no_callers_or_unreadable_files_is_empty( tree ):
    assert cs.find_call_sites( "nobody_calls_me", "src/own.py", cs.tracked_python_files( tree ), tree ) == []
    ( tree / "src" / "bin.py" ).write_bytes( b"\xff\xfe\x00bad" )
    assert cs.find_call_sites( "key", "src/own.py", [ "src/bin.py", "src/missing.py" ], tree ) == []
