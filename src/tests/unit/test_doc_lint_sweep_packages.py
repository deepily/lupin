"""
sweep_packages: the package lister, run over a small real git repo built in a temp directory.

The fixture repo has two packages, a nested package, a file in no package, a test file, an
R&D file, a file that does not parse and one that is not UTF-8. Every count is worked out by hand.
"""

import io
import json
import subprocess

import pytest

from cosa.repo.doc_lint import sweep_packages as sp, word_list

WORDS = [ "not", "never", "the", "very", "must" ]

BAD_PY = '''"""Module doc."""


def f():
    """
    This is NEVER very simple.

    Requires:
        - nothing
    """


def g():
    """Second doc."""
'''

GOOD_PY = '''"""Plain."""
'''


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
        "bad/__init__.py"     : "",
        "bad/mod.py"          : BAD_PY,
        "bad/broken.py"       : "def (:\n",
        "bad/sub/__init__.py" : "",
        "bad/sub/deep.py"     : GOOD_PY,
        "good/__init__.py"    : '"""Good."""\n',
        "good/mod.py"         : GOOD_PY,
        "loose/script.py"     : BAD_PY,
        "top.py"              : GOOD_PY,
        "bad/test_skipped.py" : BAD_PY,
        "bad/tests/__init__.py" : BAD_PY,
        "src/rnd/probe.py"    : BAD_PY,
        "bad/notes.txt"       : "ignored\n"
    }
    for rel, text in files.items():
        path = tmp_path / rel
        path.parent.mkdir( parents=True, exist_ok=True )
        path.write_text( text, encoding="utf-8" )
    ( tmp_path / "good" / "latin.py" ).write_bytes( b'"""caf\xe9."""\n' )
    _git( tmp_path, "add", "." )
    _git( tmp_path, "commit", "-qm", "first" )
    yield tmp_path
    word_list._state[ "root" ]  = None
    word_list._state[ "words" ] = None


def test_split_packages_keeps_subpackages_apart_and_reports_loose_files():
    paths = [ "a/__init__.py", "a/x.py", "a/b/__init__.py", "a/b/y.py", "c/z.py", "top.py" ]
    packages, orphans = sp.split_packages( paths )
    assert packages == { "a": [ "a/__init__.py", "a/x.py" ], "a/b": [ "a/b/__init__.py", "a/b/y.py" ] }
    assert orphans == [ "c/z.py", "top.py" ]
    assert sp.split_packages( [ "__init__.py", "m.py" ] ) == ( { "": [ "__init__.py", "m.py" ] }, [] )


def test_split_packages_sorts_unsorted_input():
    paths = [ "c/y.py", "b/z.py", "b/__init__.py", "c/x.py", "b/a.py", "a.py" ]
    assert sp.split_packages( paths ) == ( { "b": [ "b/__init__.py", "b/a.py", "b/z.py" ] }, [ "a.py", "c/x.py", "c/y.py" ] )


def test_measure_file_counts_flagged_docstrings_and_their_words( repo ):
    word_list.configure_root( repo )
    counts = sp.measure_file( "bad/mod.py", BAD_PY, repo )
    assert counts[ "files" ] == 1 and counts[ "docstrings" ] == 3 and counts[ "unparsed" ] == 0
    assert counts[ "flagged" ] == 1 and counts[ "findings" ] >= 1
    assert counts[ "words_flagged" ] == 7


def test_measure_file_unparseable_has_one_finding_and_no_docstrings( repo ):
    word_list.configure_root( repo )
    counts = sp.measure_file( "bad/broken.py", "def (:\n", repo )
    assert ( counts[ "docstrings" ], counts[ "findings" ], counts[ "unparsed" ] ) == ( 0, 1, 1 )


def test_density_is_findings_per_docstring_and_zero_without_docstrings():
    assert sp.density( { "findings": 6, "docstrings": 4 } ) == 1.5
    assert sp.density( { "findings": 3, "docstrings": 0 } ) == 0.0


def test_sweep_over_a_real_git_repo( repo ):
    result = sp.sweep( repo )
    names  = [ r[ "package" ] for r in result[ "packages" ] ]
    assert names[ 0 ] == "bad" and set( names ) == { "bad", "bad/sub", "good" }
    assert [ r[ "density" ] for r in result[ "packages" ] ] == sorted( ( r[ "density" ] for r in result[ "packages" ] ), reverse=True )
    bad = result[ "packages" ][ 0 ]
    assert bad[ "files" ] == 3 and bad[ "docstrings" ] == 3 and bad[ "unparsed" ] == 1 and bad[ "flagged" ] == 1
    assert [ o[ "path" ] for o in result[ "orphans" ] ] == [ "loose/script.py", "top.py" ]
    assert result[ "totals" ][ "packages" ][ "packages" ] == 3
    assert result[ "totals" ][ "all" ][ "files" ] == 10
    assert result[ "totals" ][ "all" ][ "docstrings" ] == sum( p[ "docstrings" ] for p in result[ "packages" ] + result[ "orphans" ] )
    assert result[ "sha" ] == _git( repo, "rev-parse", "HEAD" ) and result[ "tree_dirty" ] is False
    assert "test_skipped" not in json.dumps( result ) and "probe.py" not in json.dumps( result )


def test_unreadable_file_counts_as_one_finding( repo ):
    result = sp.sweep( repo )
    good   = next( r for r in result[ "packages" ] if r[ "package" ] == "good" )
    assert good[ "files" ] == 3 and good[ "unreadable" ] == 1 and good[ "unparsed" ] == 0 and good[ "findings" ] == 1


def test_ties_break_by_path_and_dirty_tree_is_reported( repo ):
    ( repo / "good" / "mod.py" ).write_text( GOOD_PY + "# edited\n", encoding="utf-8" )
    result = sp.sweep( repo )
    assert result[ "tree_dirty" ] is True
    zero   = [ r[ "package" ] for r in result[ "packages" ] if r[ "density" ] == 0.0 ]
    assert zero == sorted( zero )


def test_format_report_lists_packages_orphans_totals_and_sha( repo ):
    text = sp.format_report( sp.sweep( repo ) )
    assert text.splitlines()[ 1 ].startswith( "bad  3" )
    assert "2 files in no package" in text and "  loose/script.py  " in text
    assert "total packages: " in text and "total orphans: " in text and "total all: " in text
    assert f"ran at {_git( repo, 'rev-parse', 'HEAD' )}\n" in text
    ( repo / "top.py" ).write_text( "x = 1\n", encoding="utf-8" )
    assert "tracked files edited since" in sp.format_report( sp.sweep( repo ) )


def test_main_prints_text_and_json( repo ):
    out = io.StringIO()
    assert sp.main( [ "--repo-root", str( repo ) ], out ) == 0
    assert out.getvalue().startswith( "package  docstrings" )
    out = io.StringIO()
    assert sp.main( [ "--repo-root", str( repo ), "--json" ], out ) == 0
    assert json.loads( out.getvalue() )[ "totals" ][ "packages" ][ "packages" ] == 3


def test_main_defaults_to_stdout_and_sys_argv( repo, monkeypatch, capsys ):
    monkeypatch.setattr( "sys.argv", [ "x", "--repo-root", str( repo ) ] )
    assert sp.main() == 0
    assert "ran at " in capsys.readouterr().out


def test_git_failure_names_the_error( tmp_path ):
    with pytest.raises( RuntimeError, match="git rev-parse HEAD failed" ):
        sp._git( tmp_path, "rev-parse", "HEAD" )


def _make_repo( root, files ):
    _git( root, "init", "-q" )
    ( root / "src" / "conf" ).mkdir( parents=True )
    ( root / "src" / "conf" / "dm-tutor-lowercase-words.txt" ).write_text( "\n".join( WORDS ) + "\n", encoding="utf-8" )
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir( parents=True, exist_ok=True )
        path.write_text( text, encoding="utf-8" )
    _git( root, "add", "." )
    _git( root, "commit", "-qm", "x" )


@pytest.fixture
def clean_word_list():
    yield
    word_list._state[ "root" ]  = None
    word_list._state[ "words" ] = None


def test_order_is_findings_per_docstring_then_path_not_raw_findings( tmp_path, clean_word_list ):
    _make_repo( tmp_path, {
        "hi/__init__.py"   : "",
        "hi/m.py"          : '''"""NEVER VERY."""\n''',
        "lo/__init__.py"   : "",
        "lo/m.py"          : '''"""NEVER."""\n\n\ndef f():\n    """NEVER."""\n\n\ndef g():\n    """VERY."""\n\n\ndef h():\n    """Plain."""\n''',
        "a/__init__.py"    : '''"""NEVER."""\n''',
        "a-x/__init__.py"  : '''"""NEVER."""\n'''
    } )
    rows = sp.sweep( tmp_path )[ "packages" ]
    assert [ ( r[ "package" ], r[ "findings" ], r[ "docstrings" ] ) for r in rows ] == [ ( "hi", 2, 1 ), ( "a", 1, 1 ), ( "a-x", 1, 1 ), ( "lo", 3, 4 ) ]


def test_flagged_docstring_boundaries_are_its_first_and_last_lines( repo ):
    word_list.configure_root( repo )
    source = '''def f():
    """NEVER on the first
    middle plain
    """


def g():
    """Plain
    ends VERY"""


def h():
    """Plain."""
'''
    counts = sp.measure_file( "pkg/edge.py", source, repo )
    assert ( counts[ "docstrings" ], counts[ "flagged" ], counts[ "findings" ] ) == ( 3, 2, 2 )
    assert counts[ "words_flagged" ] == len( "NEVER on the first middle plain".split() ) + len( "Plain ends VERY".split() )


def test_a_root_package_is_labelled_dot( tmp_path, clean_word_list ):
    _make_repo( tmp_path, { "__init__.py": "", "m.py": '''"""NEVER."""\n''' } )
    rows = sp.sweep( tmp_path )[ "packages" ]
    assert [ r[ "package" ] for r in rows ] == [ "." ] and rows[ 0 ][ "files" ] == 2


def test_a_tracked_file_deleted_from_the_tree_is_unreadable_not_unparsed( tmp_path, clean_word_list ):
    _make_repo( tmp_path, { "p/__init__.py": "", "p/gone.py": '''"""Plain."""\n''' } )
    ( tmp_path / "p" / "gone.py" ).unlink()
    result = sp.sweep( tmp_path )
    row    = result[ "packages" ][ 0 ]
    assert ( row[ "unreadable" ], row[ "unparsed" ], row[ "findings" ] ) == ( 1, 0, 1 )
    assert result[ "tree_dirty" ] is True
