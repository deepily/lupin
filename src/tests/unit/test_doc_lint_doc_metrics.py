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


def _side( tokens, unparsed=(), **counts ):
    full = { c : 0 for c in mc.MARKER_COLUMNS }
    full.update( counts )
    return { "tokens": tokens, "unparsed": len( unparsed ), "unparsed_paths": list( unparsed ), "counts": { "words": tokens, **full } }


def test_compare_rejects_a_rate_that_rose_even_when_tokens_fell():
    assert dm.compare( _side( 20 ), _side( 5, tics=1 ) ) is False
    assert dm.compare( _side( 20 ), _side( 10 ) ) is True
    assert dm.compare( _side( 10 ), _side( 10 ) ) is False


def test_compare_is_exact_where_the_one_decimal_display_would_hide_a_rise():
    before, after = _side( 10000, tics=100 ), _side( 9990, tics=100 )
    assert mc.rates_per_thousand( before[ "counts" ] )[ "tics" ] == mc.rates_per_thousand( after[ "counts" ] )[ "tics" ] == 10.0
    assert dm.compare( before, after ) is False
    assert dm.compare( before, _side( 9990, tics=99 ) ) is True


def test_compare_refuses_a_package_where_more_files_stopped_parsing():
    assert dm.compare( _side( 1000 ), _side( 500, unparsed=[ "a.py" ] ) ) is False
    assert dm.compare( _side( 1000, unparsed=[ "a.py" ] ), _side( 500, unparsed=[ "a.py" ] ) ) is True
    assert dm.compare( _side( 1000, unparsed=[ "a.py", "b.py" ] ), _side( 500, unparsed=[ "a.py" ] ) ) is True


def test_compare_refuses_one_file_breaking_while_another_is_fixed():
    assert dm.compare( _side( 12, unparsed=[ "a.py" ] ), _side( 2, unparsed=[ "b.py" ] ) ) is False


def test_table_has_a_row_per_package_with_arrows( repo ):
    word_list.configure_root( repo )
    table = dm.render_table( dm.build_report( repo, [ "pkg", "other" ], "HEAD" ) )
    lines = table.strip().split( "\n" )
    assert lines[ 0 ] == "| package | files | unparsed | tokens | em_dash | caps_words | section_refs | id_refs | tics | emphasis_glyphs | improved |"
    assert len( lines ) == 6 and lines[ 2 ].startswith( "| pkg | 3 -> 3 (+0/-0) | 1 -> 1 | " ) and lines[ 2 ].endswith( " | yes |" )
    assert lines[ 3 ].startswith( "| other | " ) and lines[ 3 ].endswith( " | no |" )
    assert lines[ 5 ].startswith( "Fewer tokens also happen when documentation is deleted" )


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


def test_a_deleted_tracked_file_and_an_untracked_new_file_are_reported_not_fatal( repo ):
    word_list.configure_root( repo )
    ( repo / "pkg" / "b.dart" ).unlink()
    ( repo / "pkg" / "fresh.py" ).write_text( '"""Fresh."""\n', encoding="utf-8" )
    report = dm.build_report( repo, [ "pkg" ], "HEAD" )
    assert report[ "pkg" ][ "added" ] == [ "pkg/fresh.py" ] and report[ "pkg" ][ "removed" ] == [ "pkg/b.dart" ]
    assert report[ "pkg" ][ "after" ][ "files" ] == 3
    assert "(+1/-1)" in dm.render_table( report )


def test_a_non_ascii_file_name_is_listed( repo ):
    word_list.configure_root( repo )
    ( repo / "pkg" / "\u00e9.py" ).write_text( '"""Doc."""\n', encoding="utf-8" )
    assert "pkg/\u00e9.py" in dm.package_files( repo, "pkg" )
    _commit_head( repo )
    assert "pkg/\u00e9.py" in dm.package_files( repo, "pkg", "HEAD" )


def test_a_repo_with_no_word_list_is_measured_with_the_lupin_trees_list( repo, tmp_path, monkeypatch ):
    other = tmp_path / "other-root"
    other.mkdir()
    _git( other, "init", "-q" )
    ( other / "lib" ).mkdir()
    ( other / "lib" / "a.dart" ).write_text( "/// Very NEVER simple.\nclass A {}\n", encoding="utf-8" )
    _git( other, "add", "-A" )
    _git( other, "commit", "-qm", "base" )
    ( other / "lib" / "a.dart" ).write_text( "/// Simple.\nclass A {}\n", encoding="utf-8" )
    assert not ( other / "src" ).exists(), "precondition: the measured repo has no word list"
    monkeypatch.setenv( "LUPIN_ROOT", str( repo ) )
    word_list._state[ "root" ] = None
    word_list._state[ "words" ] = None
    out = io.StringIO()
    rc  = dm.main( [ "lib", "--base", "HEAD", "--repo-root", str( other ), "--format", "json", "--strict" ], out=out )
    data = json.loads( out.getvalue() )
    assert rc == 0 and data[ "lib" ][ "improved" ] is True and data[ "lib" ][ "before" ][ "counts" ][ "caps_words" ] == 1
    out = io.StringIO()
    dm.main( [ "lib", "--base", "HEAD", "--repo-root", str( other ), "--format", "json", "--words-root", str( repo ) ], out=out )
    assert json.loads( out.getvalue() )[ "lib" ][ "before" ][ "counts" ][ "caps_words" ] == 1


# ---- mutation check: each mutant of the module must redden its named test ----

MUTANTS = [
    ( "or not set( after[ \"unparsed_paths\" ] ) <= set( before[ \"unparsed_paths\" ] ): return False", "or len( after[ \"unparsed_paths\" ] ) > len( before[ \"unparsed_paths\" ] ): return False", "test_compare_refuses_one_file_breaking_while_another_is_fixed" ),
    ( "or not set( after[ \"unparsed_paths\" ] ) <= set( before[ \"unparsed_paths\" ] ): return False", ": return False", "test_compare_refuses_a_package_where_more_files_stopped_parsing" ),
    ( "if after[ \"tokens\" ] >= before[ \"tokens\" ] or", "if after[ \"tokens\" ] > before[ \"tokens\" ] or", "test_compare_rejects_a_rate_that_rose_even_when_tokens_fell" ),
    ( "after[ \"counts\" ][ c ] * before[ \"tokens\" ] <= before[ \"counts\" ][ c ] * after[ \"tokens\" ]", "after[ \"rates\" ][ c ] <= before[ \"rates\" ][ c ]", "test_compare_is_exact_where_the_one_decimal_display_would_hide_a_rise" ),
    ( "if texts is None:\n            unparsed.append( path )\n            continue", "if texts is None:\n            continue", "test_package_metrics_before_counts_every_marker_by_hand" ),
    ( "p.endswith( SUFFIXES ) and in_scope( p )", "p.endswith( SUFFIXES )", "test_package_files_come_from_git_and_skip_tests_and_other_suffixes" ),
    ( "if rev is None:\n        with open", "if False:\n        with open", "test_package_metrics_working_tree_reads_the_edited_files" ),
    ( "names  = [ n for n in names if os.path.exists( f\"{root}/{n}\" ) ]", "names  = names", "test_a_deleted_tracked_file_and_an_untracked_new_file_are_reported_not_fatal" ),
    ( "names += _git( root, \"ls-files\", \"--others\", \"--exclude-standard\", \"-z\", \"--\", package ).split( \"\\0\" )", "pass", "test_a_deleted_tracked_file_and_an_untracked_new_file_are_reported_not_fatal" ),
    ( "\"removed\"  : sorted( set( before[ \"paths\" ] ) - set( after[ \"paths\" ] ) ),", "\"removed\"  : [],", "test_a_deleted_tracked_file_and_an_untracked_new_file_are_reported_not_fatal" ),
    ( "\"-z\", rev, \"--\", package ).split( \"\\0\" )", "rev, \"--\", package ).split( \"\\0\" )", "test_a_non_ascii_file_name_is_listed" ),
    ( "rows.append( \"Fewer tokens also happen when documentation is deleted; read this table beside contract_diff and the claim judge.\" )", "pass", "test_table_has_a_row_per_package_with_arrows" ),
    ( "configure_root( args.words_root or cu.get_project_root() )", "configure_root( args.repo_root )", "test_a_repo_with_no_word_list_is_measured_with_the_lupin_trees_list" ),
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
def test_each_mutant_reddens_its_named_test( monkeypatch, repo, tmp_path_factory, old, new, named_test ):
    this  = globals()
    names = this[ named_test ].__code__.co_varnames[ : this[ named_test ].__code__.co_argcount ]

    def kwargs():
        found = {}
        if "repo" in names: found[ "repo" ] = repo
        if "tmp_path" in names: found[ "tmp_path" ] = tmp_path_factory.mktemp( "arm" )
        if "monkeypatch" in names: found[ "monkeypatch" ] = monkeypatch
        return found

    this[ named_test ]( **kwargs() )
    monkeypatch.setitem( this, "dm", _mutant_module( old, new ) )
    with pytest.raises( Exception ):  # a crash reddens the test as surely as a failed assert
        this[ named_test ]( **kwargs() )
