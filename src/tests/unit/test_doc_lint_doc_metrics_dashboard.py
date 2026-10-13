"""
doc_metrics dashboard: the generated page and the check that reads the tree again.

The fixture is a scratch git repo with a base commit and a head commit. Every expected number
is a literal worked out by hand from the docstrings written below.
"""

import io
import re
import subprocess

import pytest

from cosa.repo.doc_lint import doc_metrics as dm, marker_counts as mc, word_list

WORDS = [ "never", "very", "the", "must" ]

PAGE = "src/docs/doc-metrics-dashboard.md"

BASE_FILES = {
    "src/conf/dm-tutor-lowercase-words.txt" : "\n".join( WORDS ) + "\n",
    "src/docs/readme.txt"                   : "docs\n",
    "src/app/__init__.py"                   : '"""App package."""\n',
    "src/app/core.py"                       : '"""Core \u2014 very NEVER simple \u2014 text."""\n',
    "src/app/sub/__init__.py"               : '"""Sub package."""\n',
    "src/app/sub/deep.py"                   : '"""Deep \u2014 doc."""\n',
    "src/app/tests/test_x.py"               : '"""NEVER \u2014 never."""\n',
    "src/lupin_mcp/__init__.py"             : '"""Held package."""\n',
    "src/lupin_mcp/tool.py"                 : '"""Tool \u2014 text."""\n',
    "src/scripts/run.py"                    : '"""Run the job now."""\n',
    "top.py"                                : '"""Top file."""\n',
    "notes.txt"                             : "ignored\n"
}

HEAD_FILES = {
    "src/app/core.py"       : '"""Core text."""\n',
    "src/fresh/__init__.py" : '"""Fresh \u2014 package."""\n',
    "src/fresh/n.py"        : '"""New \u2014 NEVER."""\n'
}

SWEPT_BASE = [ "src/app/__init__.py", "src/app/core.py", "src/app/sub/__init__.py", "src/app/sub/deep.py", "src/scripts/run.py", "top.py" ]
SWEPT_HEAD = [ "src/app/__init__.py", "src/app/core.py", "src/app/sub/__init__.py", "src/app/sub/deep.py", "src/fresh/__init__.py", "src/fresh/n.py", "src/scripts/run.py", "top.py" ]


def _git( root, *args ):
    res = subprocess.run( [ "git", "-C", str( root ), "-c", "user.email=t@t", "-c", "user.name=t", *args ], capture_output=True, text=True )
    assert res.returncode == 0, res.stderr
    return res.stdout.strip()


def _put( root, files ):
    for name, text in files.items():
        ( root / name ).parent.mkdir( parents=True, exist_ok=True )
        ( root / name ).write_text( text, encoding="utf-8" )


@pytest.fixture
def repo( tmp_path ):
    _git( tmp_path, "init", "-q" )
    _put( tmp_path, BASE_FILES )
    _git( tmp_path, "add", "-A" )
    _git( tmp_path, "commit", "-qm", "base" )
    _git( tmp_path, "tag", "base" )
    _put( tmp_path, HEAD_FILES )
    _git( tmp_path, "add", "-A" )
    _git( tmp_path, "commit", "-qm", "head" )
    word_list.configure_root( tmp_path )
    yield tmp_path
    word_list._state[ "root" ] = None
    word_list._state[ "words" ] = None


def _dash( repo, action, *extra, base="base" ):
    out = io.StringIO()
    rc  = dm.main( [ "dashboard", action, "--base", base, "--repo-root", str( repo ), "--words-root", str( repo ), *extra ], out=out )
    return rc, out.getvalue()


def _page( repo ):
    return ( repo / PAGE ).read_text( encoding="utf-8" )


def _table( text ):
    block = text.split( "```text\n" )[ 1 ].split( "```" )[ 0 ]
    return [ [ cell.strip() for cell in line.split( "|" ) ] for line in block.strip( "\n" ).split( "\n" ) ]


def _row( board, name ):
    found = [ r for r in board[ "rows" ] if r[ "package" ] == name ]
    assert len( found ) == 1, f"{name} must be exactly one row, found {len( found )}"
    return found[ 0 ]


# ---- the named constants ----

def test_the_base_commit_and_the_page_path_are_named_once():
    assert dm.BASE_SHA == "456422492f308a60dafa36325102229947c44147"
    assert dm.DASHBOARD_PATH == "src/docs/doc-metrics-dashboard.md"
    assert ( dm.EXIT_OK, dm.EXIT_ROSE, dm.EXIT_NOT_CHECKED, dm.EXIT_PAGE_STALE ) == ( 0, 1, 2, 3 )


def test_the_check_compares_the_six_marker_rates_and_not_the_token_count():
    assert dm.COMPARED_METRICS == ( "em_dash", "caps_words", "section_refs", "id_refs", "tics", "emphasis_glyphs" )
    assert dm.COMPARED_METRICS == mc.MARKER_COLUMNS and "tokens" not in dm.COMPARED_METRICS


# ---- the population and its partition ----

def test_swept_at_lists_a_revision_and_the_tree_without_tests_or_held_files( repo ):
    assert dm.swept_at( repo, "base" ) == SWEPT_BASE
    assert dm.swept_at( repo, "HEAD" ) == SWEPT_HEAD
    assert dm.swept_at( repo ) == SWEPT_HEAD


def test_swept_at_the_tree_counts_tracked_files_that_are_still_on_disk( repo ):
    _put( repo, { "src/loose/untracked.py": '"""Scratch."""\n', "src/app/added.py": '"""Added."""\n' } )
    _git( repo, "add", "src/app/added.py" )
    ( repo / "top.py" ).unlink()
    assert dm.swept_at( repo ) == [ "src/app/__init__.py", "src/app/added.py", "src/app/core.py", "src/app/sub/__init__.py", "src/app/sub/deep.py", "src/fresh/__init__.py", "src/fresh/n.py", "src/scripts/run.py" ]


def test_every_swept_file_is_counted_in_exactly_one_row( repo ):
    swept = dm.swept_at( repo )
    rows  = dm.dashboard_rows( swept )
    assert len( swept ) == 8
    assert sorted( rows ) == [ ".", "src/app", "src/app/sub", "src/fresh", "src/scripts" ]
    assert { name: row[ "kind" ] for name, row in rows.items() } == { ".": "loose", "src/app": "package", "src/app/sub": "package", "src/fresh": "package", "src/scripts": "loose" }
    counted = [ path for row in rows.values() for path in row[ "paths" ] ]
    assert len( counted ) == 8, "the loop below must have something to walk"
    for path in swept: assert counted.count( path ) == 1, path
    assert sorted( counted ) == swept


def test_a_parent_row_owns_its_direct_files_and_not_its_subpackage( repo ):
    rows = dm.dashboard_rows( dm.swept_at( repo ) )
    assert rows[ "src/app" ][ "paths" ] == [ "src/app/__init__.py", "src/app/core.py" ]
    assert rows[ "src/app/sub" ][ "paths" ] == [ "src/app/sub/__init__.py", "src/app/sub/deep.py" ]
    assert rows[ "." ][ "paths" ] == [ "top.py" ]


# ---- the numbers ----

def test_files_metrics_measures_the_listed_files_only( repo ):
    m = dm.files_metrics( repo, [ "src/app/__init__.py", "src/app/core.py" ], "base" )
    assert m[ "files" ] == 2 and m[ "tokens" ] == 7 and m[ "unparsed" ] == 0
    assert m[ "counts" ][ "em_dash" ] == 2 and m[ "counts" ][ "caps_words" ] == 1
    assert dm.files_metrics( repo, [], "base" )[ "tokens" ] == 0


def test_the_parent_row_is_measured_without_its_subpackage_before_and_after( repo ):
    board = dm.build_dashboard( repo, "base" )
    app   = _row( board, "src/app" )
    assert ( app[ "before" ][ "files" ], app[ "before" ][ "tokens" ], app[ "before" ][ "counts" ][ "em_dash" ] ) == ( 2, 7, 2 )
    assert ( app[ "after" ][ "files" ], app[ "after" ][ "tokens" ], app[ "after" ][ "counts" ][ "em_dash" ] ) == ( 2, 4, 0 )
    assert app[ "status" ] == "ok" and app[ "rose" ] == [] and app[ "kind" ] == "package"
    sub = _row( board, "src/app/sub" )
    assert ( sub[ "before" ][ "tokens" ], sub[ "before" ][ "counts" ][ "em_dash" ], sub[ "after" ][ "counts" ][ "em_dash" ] ) == ( 4, 1, 1 )
    assert sub[ "status" ] == "ok"


def test_the_board_names_both_commits_and_its_rows_in_order( repo ):
    board = dm.build_dashboard( repo, "base" )
    assert board[ "base" ] == _git( repo, "rev-parse", "base" ) and board[ "head" ] == _git( repo, "rev-parse", "HEAD" )
    assert len( board[ "base" ] ) == 40 and board[ "base" ] != board[ "head" ]
    assert [ r[ "package" ] for r in board[ "rows" ] ] == [ ".", "src/app", "src/app/sub", "src/fresh", "src/scripts" ]
    assert board[ "head_is_tree" ] is True and board[ "changed" ] == 0
    assert ( board[ "files_before" ], board[ "files_after" ] ) == ( 6, 8 )


def test_a_package_with_no_before_is_marked_new_and_is_not_a_failure( repo ):
    fresh = _row( dm.build_dashboard( repo, "base" ), "src/fresh" )
    assert fresh[ "before" ] is None and fresh[ "status" ] == "new" and fresh[ "rose" ] == []
    assert ( fresh[ "after" ][ "tokens" ], fresh[ "after" ][ "counts" ][ "em_dash" ], fresh[ "after" ][ "counts" ][ "caps_words" ] ) == ( 4, 2, 1 )
    _dash( repo, "write" )
    rc, text = _dash( repo, "check" )
    assert rc == 0 and "1 new" in text and "ROSE" not in text


def _side( tokens, **counts ):
    full = { c : 0 for c in mc.MARKER_COLUMNS }
    full.update( counts )
    return { "tokens": tokens, "counts": { "words": tokens, **full } }


def test_risen_names_each_compared_value_that_is_above_its_before():
    assert dm.risen( _side( 10, tics=1 ), _side( 10, tics=1 ) ) == []
    assert dm.risen( _side( 10, tics=1 ), _side( 10, tics=2, em_dash=1 ) ) == [ "em_dash", "tics" ]
    assert dm.risen( _side( 10, tics=2 ), _side( 10, tics=1 ) ) == []


def test_risen_is_exact_where_the_one_decimal_display_would_hide_a_rise():
    before, after = _side( 10000, tics=100 ), _side( 9990, tics=100 )
    assert mc.rates_per_thousand( before[ "counts" ] )[ "tics" ] == mc.rates_per_thousand( after[ "counts" ] )[ "tics" ] == 10.0
    assert dm.risen( before, after ) == [ "tics" ]
    assert dm.risen( before, _side( 9990, tics=99 ) ) == []


def test_a_side_with_no_tokens_has_rate_zero_so_markers_after_it_are_a_rise():
    assert dm.risen( _side( 0 ), _side( 5, em_dash=1 ) ) == [ "em_dash" ]
    assert dm.risen( _side( 5, em_dash=1 ), _side( 0 ) ) == []
    assert dm.risen( _side( 0 ), _side( 0 ) ) == []


def test_token_count_is_left_out_by_default_and_compared_when_the_constant_names_it( monkeypatch ):
    before, after = _side( 10 ), _side( 11 )
    assert dm.risen( before, after ) == []
    monkeypatch.setattr( dm, "COMPARED_METRICS", ( *mc.MARKER_COLUMNS, "tokens" ) )
    assert dm.risen( before, after ) == [ "tokens" ]
    assert dm.risen( _side( 10 ), _side( 10 ) ) == [] and dm.risen( _side( 10 ), _side( 9 ) ) == []
    assert dm.risen( _side( 10, tics=1 ), _side( 9, tics=1 ) ) == [ "tics" ]


# ---- the page ----

def test_write_makes_the_page_with_a_row_per_package_and_both_values( repo ):
    rc, said = _dash( repo, "write" )
    assert rc == 0 and said == f"doc-metrics dashboard: wrote {PAGE}, 5 rows\n"
    table = _table( _page( repo ) )
    assert table[ 0 ] == [ "package", "kind", "files", "tokens", "em_dash", "caps_words", "section_refs", "id_refs", "tics", "emphasis_glyphs", "status" ]
    assert len( table ) == 6
    assert table[ 1 ] == [ ".", "loose", "1 -> 1", "2 -> 2", "0.0 -> 0.0", "0.0 -> 0.0", "0.0 -> 0.0", "0.0 -> 0.0", "0.0 -> 0.0", "0.0 -> 0.0", "ok" ]
    assert table[ 2 ] == [ "src/app", "package", "2 -> 2", "7 -> 4", "285.7 -> 0.0", "142.9 -> 0.0", "0.0 -> 0.0", "0.0 -> 0.0", "0.0 -> 0.0", "0.0 -> 0.0", "ok" ]
    assert table[ 3 ] == [ "src/app/sub", "package", "2 -> 2", "4 -> 4", "250.0 -> 250.0", "0.0 -> 0.0", "0.0 -> 0.0", "0.0 -> 0.0", "0.0 -> 0.0", "0.0 -> 0.0", "ok" ]
    assert table[ 4 ] == [ "src/fresh", "package", "- -> 2", "- -> 4", "- -> 500.0", "- -> 250.0", "- -> 0.0", "- -> 0.0", "- -> 0.0", "- -> 0.0", "new" ]
    assert table[ 5 ][ : 4 ] == [ "src/scripts", "loose", "1 -> 1", "4 -> 4" ] and table[ 5 ][ -1 ] == "ok"


def test_the_page_prints_both_commits_the_counts_and_the_commands( repo ):
    _dash( repo, "write" )
    text = _page( repo )
    base, head = _git( repo, "rev-parse", "base" ), _git( repo, "rev-parse", "HEAD" )
    assert text.startswith( "# Documentation metrics dashboard\n" ) and text.endswith( "```\n" )
    assert f"- Before: commit `{base}`\n" in text
    assert f"- After: working tree at commit `{head}`\n" in text
    assert "- Swept files changed since that commit: 0\n" in text
    assert "- Rows: 5 (3 packages, 2 loose directories), 1 new\n" in text
    assert "- Swept files: 6 before, 8 after\n" in text
    assert "- Compared by the check: `em_dash`, `caps_words`, `section_refs`, `id_refs`, `tics`, `emphasis_glyphs`\n" in text
    assert "- Rows where a compared value rose: 0\n" in text
    assert f"python3 -m cosa.repo.doc_lint.doc_metrics dashboard write --base {base}\n" in text
    assert f"python3 -m cosa.repo.doc_lint.doc_metrics dashboard check --base {base}\n" in text


def test_the_page_is_the_same_bytes_each_time_and_carries_no_clock( repo ):
    _dash( repo, "write" )
    first = _page( repo )
    _dash( repo, "write" )
    assert _page( repo ) == first
    assert re.search( r"\d{4}[-.]\d{2}[-.]\d{2}|\d{1,2}:\d{2}", first ) is None


def test_the_page_says_when_the_tree_differs_from_its_commit( repo ):
    _put( repo, { "src/scripts/run.py": '"""Run the job."""\n', "notes.txt": "edited\n" } )
    _dash( repo, "write" )
    text = _page( repo )
    assert "- Swept files changed since that commit: 1\n" in text
    assert _table( text )[ 5 ][ : 4 ] == [ "src/scripts", "loose", "1 -> 1", "4 -> 3" ]


def test_write_with_a_head_revision_measures_that_commit_and_not_the_tree( repo ):
    _put( repo, { "src/scripts/run.py": '"""Run the job."""\n' } )
    head = _git( repo, "rev-parse", "HEAD" )
    rc, _ = _dash( repo, "write", "--head", "HEAD" )
    text  = _page( repo )
    assert rc == 0 and f"- After: commit `{head}`\n" in text and "- After: working tree" not in text
    assert "- Swept files changed since that commit: 0\n" in text
    assert _table( text )[ 5 ][ : 4 ] == [ "src/scripts", "loose", "1 -> 1", "4 -> 4" ]


def test_the_page_shows_a_rise_in_its_status_column( repo ):
    _put( repo, { "src/scripts/run.py": '"""Run the job \u2014 now."""\n' } )
    _dash( repo, "write" )
    text = _page( repo )
    assert _table( text )[ 5 ] == [ "src/scripts", "loose", "1 -> 1", "4 -> 4", "0.0 -> 250.0", "0.0 -> 0.0", "0.0 -> 0.0", "0.0 -> 0.0", "0.0 -> 0.0", "0.0 -> 0.0", "rose: em_dash" ]
    assert "- Rows where a compared value rose: 1\n" in text


def test_page_packages_reads_the_row_names_and_not_the_header( repo ):
    _dash( repo, "write" )
    assert dm.page_packages( _page( repo ) ) == { ".", "src/app", "src/app/sub", "src/fresh", "src/scripts" }
    assert dm.page_packages( "# A page with no table\n" ) == set()


# ---- the check ----

def test_check_passes_on_a_page_written_from_the_same_tree( repo ):
    _dash( repo, "write" )
    rc, text = _dash( repo, "check" )
    base = _git( repo, "rev-parse", "base" )
    assert rc == 0
    assert text == f"doc-metrics dashboard: 5 rows checked against base {base}, 1 new, 0 rose, 0 not on the page; compared: em_dash, caps_words, section_refs, id_refs, tics, emphasis_glyphs\n"


def test_check_exits_1_and_names_the_package_and_the_raw_counts_when_a_rate_rose( repo ):
    _dash( repo, "write" )
    _put( repo, { "src/scripts/run.py": '"""Run the job \u2014 now."""\n' } )
    rc, text = _dash( repo, "check" )
    assert rc == 1 and ", 1 rose, 0 not on the page" in text
    assert "ROSE src/scripts: em_dash 0/4 -> 1/4 per token (0.0 -> 250.0 per 1,000)\n" in text
    assert text.count( "ROSE" ) == 1 and "MISSING" not in text


def test_check_recomputes_from_the_tree_and_does_not_trust_the_page( repo ):
    _put( repo, { "src/scripts/run.py": '"""Run the job \u2014 now."""\n' } )
    _dash( repo, "write" )
    page = _page( repo ).replace( "rose: em_dash", "ok" ).replace( "0.0 -> 250.0", "0.0 -> 0.0" )
    ( repo / PAGE ).write_text( page, encoding="utf-8" )
    assert "rose" not in _table( page )[ 5 ][ -1 ] and "250.0" not in " ".join( _table( page )[ 5 ] )
    rc, text = _dash( repo, "check" )
    assert rc == 1 and "ROSE src/scripts: em_dash 0/4 -> 1/4" in text


def test_more_tokens_alone_pass_the_check_under_the_marker_rates_setting( repo ):
    _dash( repo, "write" )
    _put( repo, { "src/scripts/run.py": '"""Run the job now, and then again."""\n' } )
    rc, text = _dash( repo, "check" )
    assert dm.files_metrics( repo, [ "src/scripts/run.py" ] )[ "tokens" ] == 7
    assert rc == 0 and "ROSE" not in text


def test_more_tokens_fail_the_check_when_the_constant_also_names_tokens( repo, monkeypatch ):
    monkeypatch.setattr( dm, "COMPARED_METRICS", ( *mc.MARKER_COLUMNS, "tokens" ) )
    _dash( repo, "write" )
    assert "`emphasis_glyphs`, `tokens`\n" in _page( repo )
    assert _dash( repo, "check" )[ 0 ] == 0
    _put( repo, { "src/scripts/run.py": '"""Run the job now, and then again."""\n' } )
    rc, text = _dash( repo, "check" )
    assert rc == 1 and "ROSE src/scripts: tokens 4 -> 7\n" in text and text.count( "ROSE" ) == 1
    assert text.split( "\n" )[ 0 ].endswith( "emphasis_glyphs, tokens" )


def test_check_exits_3_when_a_tracked_package_has_no_row_on_the_page( repo ):
    _dash( repo, "write" )
    _put( repo, { "src/later/__init__.py": '"""Later."""\n', "src/scratch/untracked.py": '"""Scratch."""\n' } )
    assert _dash( repo, "check" )[ 0 ] == 0, "an untracked file is not in the swept population"
    _git( repo, "add", "src/later/__init__.py" )
    rc, text = _dash( repo, "check" )
    assert rc == 3 and "6 rows checked" in text and "2 new, 0 rose, 1 not on the page" in text
    assert f"MISSING src/later: no row on {PAGE}; regenerate with: " in text and "dashboard write" in text
    assert text.count( "MISSING" ) == 1 and "src/scratch" not in text


def test_check_exits_3_when_the_page_was_written_against_another_base( repo ):
    _dash( repo, "write" )
    rc, text = _dash( repo, "check", base="HEAD" )
    head = _git( repo, "rev-parse", "HEAD" )
    assert rc == 3 and f"STALE {PAGE}: the page does not name base {head}; regenerate with: " in text
    assert "0 rose, 0 not on the page" in text


def test_a_rise_outranks_a_missing_row_and_both_are_printed( repo ):
    _dash( repo, "write" )
    _put( repo, { "src/later/__init__.py": '"""Later."""\n', "src/scripts/run.py": '"""Run the job \u2014 now."""\n' } )
    _git( repo, "add", "src/later/__init__.py" )
    rc, text = _dash( repo, "check" )
    assert rc == 1 and "ROSE src/scripts: em_dash" in text and "MISSING src/later: " in text


def test_check_exits_2_when_there_is_no_page( repo ):
    rc, text = _dash( repo, "check" )
    assert rc == 2 and text.startswith( "doc-metrics dashboard: could not check: " ) and PAGE in text


def test_check_and_write_exit_2_when_the_base_does_not_resolve( repo ):
    _dash( repo, "write" )
    rc, text = _dash( repo, "check", base="nope" )
    assert rc == 2 and text.startswith( "doc-metrics dashboard: could not check: git rev-parse" )
    rc, text = _dash( repo, "write", base="nope" )
    assert rc == 2 and text.startswith( "doc-metrics dashboard: could not write: git rev-parse" )


def test_write_exits_2_when_the_page_cannot_be_written( repo ):
    rc, text = _dash( repo, "write", "--page", "no-such-dir/page.md" )
    assert rc == 2 and text.startswith( "doc-metrics dashboard: could not write: " ) and not ( repo / "no-such-dir" ).exists()


def test_the_page_option_moves_both_the_write_and_the_check( repo ):
    rc, said = _dash( repo, "write", "--page", "src/docs/other.md" )
    assert rc == 0 and said == "doc-metrics dashboard: wrote src/docs/other.md, 5 rows\n" and not ( repo / PAGE ).exists()
    assert _dash( repo, "check", "--page", "src/docs/other.md" )[ 0 ] == 0
    assert _dash( repo, "check" )[ 0 ] == 2


def test_the_dashboard_defaults_to_the_named_base_and_to_stdout( repo, capsys, monkeypatch ):
    monkeypatch.setattr( dm, "BASE_SHA", _git( repo, "rev-parse", "base" ) )
    assert dm.main( [ "dashboard", "write", "--repo-root", str( repo ), "--words-root", str( repo ) ] ) == 0
    assert capsys.readouterr().out == f"doc-metrics dashboard: wrote {PAGE}, 5 rows\n"
    assert f"- Before: commit `{dm.BASE_SHA}`\n" in _page( repo )
    assert dm.main( [ "dashboard", "check", "--repo-root", str( repo ), "--words-root", str( repo ) ] ) == 0


def test_the_packages_command_still_runs_beside_the_dashboard( repo ):
    out = io.StringIO()
    rc  = dm.main( [ "src/app", "--base", "base", "--repo-root", str( repo ), "--words-root", str( repo ) ], out=out )
    assert rc == 0 and out.getvalue().split( "\n" )[ 2 ].startswith( "| src/app | 4 -> 4 (+0/-0) | 0 -> 0 | 11 -> 8 | " )


# ---- mutation check: each mutant of the module must redden its named test ----

MUTANTS = [
    ( "return sorted( n for n in names if is_swept( n ) )", "return sorted( n for n in names if n.endswith( \".py\" ) )", "test_swept_at_lists_a_revision_and_the_tree_without_tests_or_held_files" ),
    ( "names = [ n for n in _git( root, \"ls-files\", \"-z\" ).split( \"\\0\" ) if os.path.exists( f\"{root}/{n}\" ) ]", "names = _git( root, \"ls-files\", \"-z\" ).split( \"\\0\" )", "test_swept_at_the_tree_counts_tracked_files_that_are_still_on_disk" ),
    ( "before = files_metrics( root, old[ name ][ \"paths\" ], base_sha ) if name in old else None", "before = package_metrics( root, name, base_sha ) if name in old else None", "test_the_parent_row_is_measured_without_its_subpackage_before_and_after" ),
    ( "after  = files_metrics( root, row[ \"paths\" ], head )", "after  = package_metrics( root, name, head )", "test_the_parent_row_is_measured_without_its_subpackage_before_and_after" ),
    ( "rose   = [] if before is None else risen( before, after )", "rose   = risen( before or files_metrics( root, [], base_sha ), after )", "test_a_package_with_no_before_is_marked_new_and_is_not_a_failure" ),
    ( "return [ name for name in COMPARED_METRICS if metric_value( after, name ) > metric_value( before, name ) ]", "return [ name for name in COMPARED_METRICS if metric_value( after, name ) >= metric_value( before, name ) ]", "test_risen_names_each_compared_value_that_is_above_its_before" ),
    ( "return [ name for name in COMPARED_METRICS if metric_value( after, name ) > metric_value( before, name ) ]", "return [ name for name in COMPARED_METRICS if name != \"tokens\" and rates_per_thousand( after[ \"counts\" ] )[ name ] > rates_per_thousand( before[ \"counts\" ] )[ name ] ]", "test_risen_is_exact_where_the_one_decimal_display_would_hide_a_rise" ),
    ( "return [ name for name in COMPARED_METRICS if metric_value( after, name ) > metric_value( before, name ) ]", "return [ name for name in MARKER_COLUMNS if metric_value( after, name ) > metric_value( before, name ) ]", "test_more_tokens_fail_the_check_when_the_constant_also_names_tokens" ),
    ( "COMPARED_METRICS = MARKER_COLUMNS", "COMPARED_METRICS = ( *MARKER_COLUMNS, \"tokens\" )", "test_more_tokens_alone_pass_the_check_under_the_marker_rates_setting" ),
    ( "board  = build_dashboard( root, base )\n    names  = page_packages( text )", "board  = build_dashboard( root, base, \"HEAD\" )\n    names  = page_packages( text )", "test_check_exits_1_and_names_the_package_and_the_raw_counts_when_a_rate_rose" ),
    ( "missing = [ r[ \"package\" ] for r in board[ \"rows\" ] if r[ \"package\" ] not in names ]", "missing = []", "test_check_exits_3_when_a_tracked_package_has_no_row_on_the_page" ),
    ( "stale   = board[ \"base\" ] not in text", "stale   = False", "test_check_exits_3_when_the_page_was_written_against_another_base" ),
    ( "if rose: return EXIT_ROSE, lines", "if rose and not missing: return EXIT_ROSE, lines", "test_a_rise_outranks_a_missing_row_and_both_are_printed" ),
    ( "if rose: return EXIT_ROSE, lines", "if rose: return EXIT_PAGE_STALE, lines", "test_check_recomputes_from_the_tree_and_does_not_trust_the_page" ),
    ( "board = build_dashboard( root, args.base, args.head )", "board = build_dashboard( root, args.base )", "test_write_with_a_head_revision_measures_that_commit_and_not_the_tree" ),
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
def test_each_dashboard_mutant_reddens_its_named_test( monkeypatch, repo, old, new, named_test ):
    this  = globals()
    names = this[ named_test ].__code__.co_varnames[ : this[ named_test ].__code__.co_argcount ]

    def kwargs():
        found = {}
        if "repo" in names: found[ "repo" ] = repo
        if "monkeypatch" in names: found[ "monkeypatch" ] = monkeypatch
        return found

    this[ named_test ]( **kwargs() )
    _git( repo, "reset", "-q", "--hard", "HEAD" )
    _git( repo, "clean", "-qfdx" )
    monkeypatch.setitem( this, "dm", _mutant_module( old, new ) )
    with pytest.raises( AssertionError ):
        this[ named_test ]( **kwargs() )
