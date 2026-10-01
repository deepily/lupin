"""
doc_metrics: per-package tokens and marker rates before and after, counted by marker_counts.

The fixtures are a scratch git repo with a verbose package that is then tidied, so the
"improved" verdict and every column are checked against numbers worked out by hand.
"""

import io
import json
import subprocess

import pytest

from cosa.repo.doc_lint import doc_metrics as dm, marker_counts as mc, word_list

WORDS = [ "not", "never", "the", "very", "must" ]

BEFORE_PY = '''"""Module doc."""


def f():
    """
    This is NEVER very simple — it must not fail § 3.

    Requires:
        - nothing
    """


def g():
    """Second doc, with the row 1a2b3c4d reference."""
'''

AFTER_PY = '''"""Module doc."""


def f():
    """
    Do the simple thing.

    Requires:
        - nothing
    """


def g():
    """Second doc."""
'''

BEFORE_DART = "/// Very NEVER simple — really.\nclass A {}\n"
AFTER_DART = "/// Simple.\nclass A {}\n"


def _git( root, *args ):
    res = subprocess.run( [ "git", "-C", str( root ), "-c", "user.email=t@t", "-c", "user.name=t", *args ], capture_output=True, text=True )
    assert res.returncode == 0, res.stderr
    return res.stdout.strip()


@pytest.fixture
def repo( tmp_path ):
    _git( tmp_path, "init", "-q" )
    ( tmp_path / "src" / "conf" ).mkdir( parents=True )
    ( tmp_path / "src" / "conf" / "dm-tutor-lowercase-words.txt" ).write_text( "\n".join( WORDS ) + "\n", encoding="utf-8" )
    ( tmp_path / "pkg" / "tests" ).mkdir( parents=True )
    ( tmp_path / "pkg" / "a.py" ).write_text( BEFORE_PY, encoding="utf-8" )
    ( tmp_path / "pkg" / "b.dart" ).write_text( BEFORE_DART, encoding="utf-8" )
    ( tmp_path / "pkg" / "broken.py" ).write_text( "def (:\n", encoding="utf-8" )
    ( tmp_path / "pkg" / "test_skipped.py" ).write_text( '"""NEVER very NEVER."""\n', encoding="utf-8" )
    ( tmp_path / "pkg" / "notes.txt" ).write_text( "ignored\n", encoding="utf-8" )
    ( tmp_path / "other" ).mkdir()
    ( tmp_path / "other" / "c.py" ).write_text( '"""Plain."""\n', encoding="utf-8" )
    _git( tmp_path, "add", "." )
    _git( tmp_path, "commit", "-qm", "before" )
    ( tmp_path / "pkg" / "a.py" ).write_text( AFTER_PY, encoding="utf-8" )
    ( tmp_path / "pkg" / "b.dart" ).write_text( AFTER_DART, encoding="utf-8" )
    yield tmp_path
    word_list._state[ "root" ] = None
    word_list._state[ "words" ] = None


def _commit_head( repo ):
    _git( repo, "add", "-A" )
    _git( repo, "commit", "-qm", "after" )


def test_add_counts_and_empty_counts_sum_every_column():
    total = mc.empty_counts()
    assert set( total ) == { "words", *mc.MARKER_COLUMNS } and not any( total.values() )
    one = { k : 1 for k in total }
    mc.add_counts( mc.add_counts( total, one ), one )
    assert all( v == 2 for v in total.values() )


def test_package_files_come_from_git_and_skip_tests_and_other_suffixes( repo ):
    assert dm.package_files( repo, "pkg", "HEAD" ) == [ "pkg/a.py", "pkg/b.dart", "pkg/broken.py" ]
    assert dm.package_files( repo, "pkg" ) == [ "pkg/a.py", "pkg/b.dart", "pkg/broken.py" ]
    assert dm.package_files( repo, "other" ) == [ "other/c.py" ]


def test_doc_texts_python_dart_and_unparseable():
    assert dm.doc_texts( "x.py", '"""Hi."""\n' ) == [ "Hi." ]
    assert dm.doc_texts( "x.dart", "/// One.\n/// Two.\n" ) == [ "One.\nTwo." ]
    assert dm.doc_texts( "x.py", "def (:\n" ) is None


def test_package_metrics_before_counts_every_marker_by_hand( repo ):
    word_list.configure_root( repo )
    m = dm.package_metrics( repo, "pkg", "HEAD" )
    assert m[ "files" ] == 3 and m[ "unparsed" ] == 1
    c = m[ "counts" ]
    assert c[ "em_dash" ] == 2 and c[ "caps_words" ] == 2 and c[ "section_refs" ] == 1 and c[ "id_refs" ] == 1
    assert m[ "tokens" ] == c[ "words" ] > 0
    assert m[ "rates" ][ "em_dash" ] == round( 2 * 1000.0 / m[ "tokens" ], 1 )


def test_package_metrics_working_tree_reads_the_edited_files( repo ):
    word_list.configure_root( repo )
    now = dm.package_metrics( repo, "pkg" )
    assert now[ "counts" ][ "em_dash" ] == 0 and now[ "counts" ][ "caps_words" ] == 0


def test_report_improved_requires_fewer_tokens_and_no_rate_above( repo ):
    word_list.configure_root( repo )
    report = dm.build_report( repo, [ "pkg", "other" ], "HEAD" )
    assert report[ "pkg" ][ "improved" ] is True
    assert report[ "pkg" ][ "after" ][ "tokens" ] < report[ "pkg" ][ "before" ][ "tokens" ]
    assert report[ "other" ][ "improved" ] is False


def test_compare_rejects_a_rate_that_rose_even_when_tokens_fell():
    low  = { "tokens": 10, "rates": { c : 0.0 for c in mc.MARKER_COLUMNS } }
    high = { "tokens": 5, "rates": { **low[ "rates" ], "tics": 0.1 } }
    assert dm.compare( { "tokens": 20, "rates": low[ "rates" ] }, high ) is False
    assert dm.compare( { "tokens": 20, "rates": low[ "rates" ] }, low ) is True
    assert dm.compare( low, low ) is False


def test_table_has_a_row_per_package_with_arrows( repo ):
    word_list.configure_root( repo )
    table = dm.render_table( dm.build_report( repo, [ "pkg", "other" ], "HEAD" ) )
    lines = table.strip().split( "\n" )
    assert lines[ 0 ] == "| package | tokens | em_dash | caps_words | section_refs | id_refs | tics | emphasis_glyphs | improved |"
    assert len( lines ) == 4 and lines[ 2 ].startswith( "| pkg | " ) and lines[ 2 ].endswith( " | yes |" )
    assert lines[ 3 ].startswith( "| other | " ) and lines[ 3 ].endswith( " | no |" )
    assert " -> " in lines[ 2 ]


def _run( repo, *extra ):
    out = io.StringIO()
    rc  = dm.main( [ "pkg", "--base", "HEAD", "--repo-root", str( repo ), *extra ], out=out )
    return rc, out.getvalue()


def test_cli_table_json_and_strict( repo ):
    rc, text = _run( repo )
    assert rc == 0 and "| pkg |" in text
    rc, text = _run( repo, "--format", "json", "--strict" )
    data = json.loads( text )
    assert rc == 0 and data[ "pkg" ][ "improved" ] is True and data[ "pkg" ][ "before" ][ "counts" ][ "em_dash" ] == 2
    out = io.StringIO()
    assert dm.main( [ "pkg", "other", "--base", "HEAD", "--repo-root", str( repo ), "--strict" ], out=out ) == 1


def test_cli_between_revisions( repo ):
    _commit_head( repo )
    out = io.StringIO()
    rc  = dm.main( [ "pkg", "--base", "HEAD~1", "--head", "HEAD", "--repo-root", str( repo ), "--format", "json" ], out=out )
    assert rc == 0 and json.loads( out.getvalue() )[ "pkg" ][ "improved" ] is True


def test_main_defaults_to_stdout( repo, capsys ):
    dm.main( [ "pkg", "--base", "HEAD", "--repo-root", str( repo ) ] )
    assert "| package |" in capsys.readouterr().out


def test_bad_revision_raises( repo ):
    with pytest.raises( RuntimeError, match="git ls-tree" ):
        dm.main( [ "pkg", "--base", "nope", "--repo-root", str( repo ) ], out=io.StringIO() )


# ---- mutation check: each mutant of the module must redden its named test ----

MUTANTS = [
    ( "return after[ \"tokens\" ] < before[ \"tokens\" ] and", "return True or", "test_compare_rejects_a_rate_that_rose_even_when_tokens_fell" ),
    ( "after[ \"tokens\" ] < before[ \"tokens\" ]", "after[ \"tokens\" ] <= before[ \"tokens\" ]", "test_compare_rejects_a_rate_that_rose_even_when_tokens_fell" ),
    ( "if texts is None:\n            unparsed += 1\n            continue", "if texts is None:\n            continue", "test_package_metrics_before_counts_every_marker_by_hand" ),
    ( "and in_scope( p )", "", "test_package_files_come_from_git_and_skip_tests_and_other_suffixes" ),
    ( "p.endswith( SUFFIXES ) and", "", "test_package_files_come_from_git_and_skip_tests_and_other_suffixes" ),
    ( "if rev is None:\n        with open", "if False:\n        with open", "test_package_metrics_working_tree_reads_the_edited_files" ),
    ( "return 1 if args.strict and not all( r[ \"improved\" ] for r in report.values() ) else 0", "return 0", "test_cli_table_json_and_strict" ),
]


def _mutant_module( old, new ):
    path   = dm.__file__
    source = open( path, encoding="utf-8" ).read()
    assert source.count( old ) == 1, f"anchor must match exactly once: {old!r}"
    module = type( dm )( dm.__name__ )
    module.__file__, module.__package__ = path, dm.__package__
    exec( compile( source.replace( old, new ), path, "exec" ), module.__dict__ )
    return module


@pytest.mark.parametrize( "old,new,named_test", MUTANTS )
def test_each_mutant_reddens_its_named_test( monkeypatch, repo, old, new, named_test ):
    this = globals()
    code = this[ named_test ].__code__
    kwargs = { "repo": repo } if "repo" in code.co_varnames[ : code.co_argcount ] else {}
    this[ named_test ]( **kwargs )
    monkeypatch.setitem( this, "dm", _mutant_module( old, new ) )
    with pytest.raises( Exception ):  # a crash reddens the test as surely as a failed assert
        this[ named_test ]( **kwargs )
