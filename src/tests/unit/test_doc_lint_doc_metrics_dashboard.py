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
    assert ( dm.EXIT_OK, dm.EXIT_ROSE, dm.EXIT_NOT_CHECKED, dm.EXIT_PAGE_STALE, dm.EXIT_NUMBERS_STALE ) == ( 0, 1, 2, 3, 4 )


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


def test_the_board_carries_a_total_of_every_swept_file_before_and_after( repo ):
    total = dm.build_dashboard( repo, "base" )[ "total" ]
    assert ( total[ "before" ][ "files" ], total[ "before" ][ "tokens" ], total[ "before" ][ "counts" ][ "em_dash" ], total[ "before" ][ "counts" ][ "caps_words" ] ) == ( 6, 17, 3, 1 )
    assert ( total[ "after" ][ "files" ], total[ "after" ][ "tokens" ], total[ "after" ][ "counts" ][ "em_dash" ], total[ "after" ][ "counts" ][ "caps_words" ] ) == ( 8, 18, 3, 1 )
    assert total[ "before" ][ "rates" ][ "em_dash" ] == 176.5 and total[ "after" ][ "rates" ][ "em_dash" ] == 166.7


def test_the_total_before_counts_a_directory_that_is_gone_at_head( repo ):
    _git( repo, "rm", "-q", "top.py" )
    board = dm.build_dashboard( repo, "base" )
    assert [ r[ "package" ] for r in board[ "rows" ] ] == [ "src/app", "src/app/sub", "src/fresh", "src/scripts" ]
    assert ( board[ "total" ][ "before" ][ "files" ], board[ "total" ][ "before" ][ "tokens" ] ) == ( 6, 17 )
    assert ( board[ "total" ][ "after" ][ "files" ], board[ "total" ][ "after" ][ "tokens" ] ) == ( 7, 16 )


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
    before, fewer_words, one_more = _side( 10000, tics=100 ), _side( 9990, tics=100 ), _side( 10090, tics=101 )
    shown = [ mc.rates_per_thousand( side[ "counts" ] )[ "tics" ] for side in ( before, fewer_words, one_more ) ]
    assert shown == [ 10.0, 10.0, 10.0 ]
    assert dm.risen( before, fewer_words ) == [], "the marker count is the same; only the token count fell"
    assert dm.risen( before, one_more ) == [ "tics" ]
    assert dm.risen( before, _side( 9990, tics=99 ) ) == []


def test_a_higher_marker_count_is_not_a_rise_when_the_rate_fell_or_held():
    assert dm.risen( _side( 10, tics=1 ), _side( 30, tics=2 ) ) == [], "three times the words and one more marker: the rate fell"
    assert dm.risen( _side( 10, tics=1 ), _side( 20, tics=2 ) ) == [], "the rate is the same"
    assert dm.risen( _side( 10, tics=1 ), _side( 19, tics=2 ) ) == [ "tics" ]


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
    assert dm.risen( _side( 10, tics=1 ), _side( 9, tics=1 ) ) == [], "fewer tokens and the same marker count is no rise under either setting"
    assert dm.risen( _side( 10, tics=1 ), _side( 9, tics=2 ) ) == [ "tics" ]
    assert dm.risen( _side( 10, tics=1 ), _side( 11, tics=2 ) ) == [ "tics", "tokens" ]


# ---- the page ----

def test_write_makes_the_page_with_a_row_per_package_and_both_values( repo ):
    rc, said = _dash( repo, "write" )
    head     = _git( repo, "rev-parse", "HEAD" )
    assert rc == 0 and said == f"doc-metrics dashboard: wrote {PAGE}, 5 rows; after: working tree at commit {head}, 0 swept files changed since it\n"
    table = _table( _page( repo ) )
    assert table[ 0 ] == [ "package", "kind", "files", "tokens", "em_dash", "caps_words", "section_refs", "id_refs", "tics", "emphasis_glyphs", "status" ]
    assert len( table ) == 7
    assert table[ 1 ] == [ ".", "loose", "1 -> 1", "2 -> 2", "0.0 -> 0.0", "0.0 -> 0.0", "0.0 -> 0.0", "0.0 -> 0.0", "0.0 -> 0.0", "0.0 -> 0.0", "ok" ]
    assert table[ 2 ] == [ "src/app", "package", "2 -> 2", "7 -> 4", "285.7 -> 0.0", "142.9 -> 0.0", "0.0 -> 0.0", "0.0 -> 0.0", "0.0 -> 0.0", "0.0 -> 0.0", "ok" ]
    assert table[ 3 ] == [ "src/app/sub", "package", "2 -> 2", "4 -> 4", "250.0 -> 250.0", "0.0 -> 0.0", "0.0 -> 0.0", "0.0 -> 0.0", "0.0 -> 0.0", "0.0 -> 0.0", "ok" ]
    assert table[ 4 ] == [ "src/fresh", "package", "- -> 2", "- -> 4", "- -> 500.0", "- -> 250.0", "- -> 0.0", "- -> 0.0", "- -> 0.0", "- -> 0.0", "new" ]
    assert table[ 5 ][ : 4 ] == [ "src/scripts", "loose", "1 -> 1", "4 -> 4" ] and table[ 5 ][ -1 ] == "ok"


def test_the_last_row_of_the_page_is_the_total( repo ):
    _dash( repo, "write" )
    assert _table( _page( repo ) )[ -1 ] == [ "total", "-", "6 -> 8", "17 -> 18", "176.5 -> 166.7", "58.8 -> 55.6", "0.0 -> 0.0", "0.0 -> 0.0", "0.0 -> 0.0", "0.0 -> 0.0", "-" ]


def test_the_page_prints_the_before_commit_the_counts_and_the_commands( repo ):
    _dash( repo, "write" )
    text = _page( repo )
    base = _git( repo, "rev-parse", "base" )
    assert text.startswith( "# Documentation metrics dashboard\n" ) and text.endswith( "```\n" )
    assert f"- Before: commit `{base}`\n" in text
    assert "- Rows: 5 (3 packages, 2 loose directories), 1 new\n" in text
    assert "- Swept files: 6 before, 8 after\n" in text
    assert "- Compared by the check: `em_dash`, `caps_words`, `section_refs`, `id_refs`, `tics`, `emphasis_glyphs`\n" in text
    assert "- Rows where a compared value rose: 0\n" in text
    assert f"python3 -m cosa.repo.doc_lint.doc_metrics dashboard write --base {base}\n" in text
    assert f"python3 -m cosa.repo.doc_lint.doc_metrics dashboard check --base {base}\n" in text


def test_the_page_names_no_head_commit_and_no_count_of_changed_files( repo ):
    _dash( repo, "write" )
    text = _page( repo )
    assert _git( repo, "rev-parse", "HEAD" ) not in text and _git( repo, "rev-parse", "--short", "HEAD" ) not in text
    assert "changed since" not in text and "- After" not in text


def test_the_page_is_the_same_bytes_at_two_commits_whose_swept_files_are_the_same( repo ):
    _, said_one = _dash( repo, "write" )
    first       = ( repo / PAGE ).read_bytes()
    _put( repo, { "notes.txt": "edited\n", "src/app/tests/test_x.py": '"""Changed test."""\n' } )
    _git( repo, "add", "notes.txt", "src/app/tests/test_x.py" )
    _git( repo, "commit", "-qm", "a commit that touches no swept file" )
    _, said_two = _dash( repo, "write" )
    assert len( first ) > 500 and ( repo / PAGE ).read_bytes() == first
    assert said_one != said_two and _git( repo, "rev-parse", "HEAD" ) in said_two and _git( repo, "rev-parse", "HEAD~1" ) in said_one


def test_the_page_is_the_same_bytes_each_time_and_carries_no_clock( repo ):
    _dash( repo, "write" )
    first = _page( repo )
    _dash( repo, "write" )
    assert _page( repo ) == first
    assert re.search( r"\d{4}[-.]\d{2}[-.]\d{2}|\d{1,2}:\d{2}", first ) is None


def test_write_says_how_many_swept_files_differ_from_the_commit( repo ):
    _put( repo, { "src/scripts/run.py": '"""Run the job."""\n', "notes.txt": "edited\n" } )
    rc, said = _dash( repo, "write" )
    assert rc == 0 and said.endswith( ", 1 swept files changed since it\n" )
    assert _table( _page( repo ) )[ 5 ][ : 4 ] == [ "src/scripts", "loose", "1 -> 1", "4 -> 3" ]


def test_write_with_a_head_revision_measures_that_commit_and_not_the_tree( repo ):
    _put( repo, { "src/scripts/run.py": '"""Run the job."""\n' } )
    head = _git( repo, "rev-parse", "HEAD" )
    rc, said = _dash( repo, "write", "--head", "HEAD" )
    assert rc == 0 and said == f"doc-metrics dashboard: wrote {PAGE}, 5 rows; after: commit {head}, 0 swept files changed since it\n"
    assert _table( _page( repo ) )[ 5 ][ : 4 ] == [ "src/scripts", "loose", "1 -> 1", "4 -> 4" ]


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
    assert rc == dm.EXIT_OK == 0
    assert text == (
        f"doc-metrics dashboard: 5 rows checked against base {base}, 1 new, 0 rose, 0 not on the page; compared: em_dash, caps_words, section_refs, id_refs, tics, emphasis_glyphs\n"
        "DASHBOARD CHECK PASSED: 5 rows, no compared value rose and the page matches the tree.\n"
    )


def test_check_exits_1_and_names_the_package_and_the_raw_counts_when_a_rate_rose( repo ):
    _put( repo, { "src/scripts/run.py": '"""Run the job \u2014 now."""\n' } )
    _dash( repo, "write" )
    rc, text = _dash( repo, "check" )
    assert rc == dm.EXIT_ROSE == 1 and ", 1 rose, 0 not on the page" in text
    assert "ROSE src/scripts: em_dash 0/4 -> 1/4 per token (0.0 -> 250.0 per 1,000)\n" in text
    assert text.count( "ROSE" ) == 1 and "MISSING" not in text and "STALE" not in text and "WARNING" not in text
    assert text.endswith( "DASHBOARD CHECK FAILED: 1 values rose in 1 rows; the page matches the tree.\n" )


def test_check_recomputes_from_the_tree_and_does_not_trust_the_page( repo ):
    _put( repo, { "src/scripts/run.py": '"""Run the job \u2014 now."""\n' } )
    _dash( repo, "write" )
    page = _page( repo ).replace( "rose: em_dash", "ok" ).replace( "0.0 -> 250.0", "0.0 -> 0.0" )
    ( repo / PAGE ).write_text( page, encoding="utf-8" )
    assert "rose" not in _table( page )[ 5 ][ -1 ] and "250.0" not in " ".join( _table( page )[ 5 ] )
    rc, text = _dash( repo, "check" )
    assert rc == dm.EXIT_ROSE and "ROSE src/scripts: em_dash 0/4 -> 1/4" in text
    assert f"WARNING {PAGE}: the numbers on the page are stale, 1 of its rows differ from the tree; regenerate with: " in text
    assert text.endswith( "DASHBOARD CHECK FAILED: 1 values rose in 1 rows; the page does not match the tree.\n" )


def test_fewer_tokens_with_the_same_marker_count_pass_the_check( repo ):
    _put( repo, { "src/app/sub/__init__.py": '"""Sub."""\n' } )
    _dash( repo, "write" )
    assert _table( _page( repo ) )[ 3 ][ : 5 ] == [ "src/app/sub", "package", "2 -> 2", "4 -> 3", "250.0 -> 333.3" ]
    rc, text = _dash( repo, "check" )
    assert rc == dm.EXIT_OK and "ROSE" not in text


def test_more_tokens_alone_pass_the_check_under_the_marker_rates_setting( repo ):
    _put( repo, { "src/scripts/run.py": '"""Run the job now, and then again."""\n' } )
    _dash( repo, "write" )
    rc, text = _dash( repo, "check" )
    assert dm.files_metrics( repo, [ "src/scripts/run.py" ] )[ "tokens" ] == 7
    assert rc == dm.EXIT_OK and "ROSE" not in text


def test_more_tokens_fail_the_check_when_the_constant_also_names_tokens( repo, monkeypatch ):
    monkeypatch.setattr( dm, "COMPARED_METRICS", ( *mc.MARKER_COLUMNS, "tokens" ) )
    _dash( repo, "write" )
    assert "`emphasis_glyphs`, `tokens`\n" in _page( repo )
    assert _dash( repo, "check" )[ 0 ] == dm.EXIT_OK
    _put( repo, { "src/scripts/run.py": '"""Run the job now, and then again."""\n' } )
    _dash( repo, "write" )
    rc, text = _dash( repo, "check" )
    assert rc == dm.EXIT_ROSE and "ROSE src/scripts: tokens 4 -> 7\n" in text and text.count( "ROSE" ) == 1
    assert text.split( "\n" )[ 0 ].endswith( "emphasis_glyphs, tokens" )


def test_the_total_is_not_a_compared_row( repo ):
    _put( repo, { "src/fresh/n.py": '"""New \u2014 NEVER \u2014 yes."""\n' } )
    _dash( repo, "write" )
    total = dm.build_dashboard( repo, "base" )[ "total" ]
    assert dm.risen( total[ "before" ], total[ "after" ] ) == [ "em_dash" ], "the fixture must make the total itself rise: 3/17 to 4/19"
    assert _table( _page( repo ) )[ -1 ][ : 5 ] == [ "total", "-", "6 -> 8", "17 -> 19", "176.5 -> 210.5" ]
    rc, text = _dash( repo, "check" )
    assert rc == dm.EXIT_OK and "5 rows checked" in text and "ROSE" not in text


def test_check_exits_4_with_a_warning_line_when_a_value_on_the_page_is_not_the_trees( repo ):
    _dash( repo, "write" )
    page = _page( repo )
    base = _git( repo, "rev-parse", "base" )
    assert page.count( "7 -> 4" ) == 1
    ( repo / PAGE ).write_text( page.replace( "7 -> 4", "7 -> 5" ), encoding="utf-8" )
    rc, text = _dash( repo, "check" )
    assert rc == dm.EXIT_NUMBERS_STALE == 4 and "0 rose, 0 not on the page" in text
    assert f"WARNING {PAGE}: the numbers on the page are stale, 1 of its rows differ from the tree; regenerate with: PYTHONPATH=src python3 -m cosa.repo.doc_lint.doc_metrics dashboard write --base {base}\n" in text
    assert text.count( "WARNING" ) == 1 and "STALE " not in text and "MISSING" not in text and "FAILED" not in text
    assert text.endswith( "DASHBOARD CHECK PASSED: 5 rows, no compared value rose; the numbers on the page are stale.\n" )


def test_check_exits_4_when_a_docstring_changed_and_the_page_was_not_written_again( repo ):
    _dash( repo, "write" )
    _put( repo, { "src/scripts/run.py": '"""Run the job."""\n' } )
    rc, text = _dash( repo, "check" )
    assert rc == dm.EXIT_NUMBERS_STALE and "the numbers on the page are stale, 2 of its rows differ from the tree" in text, "the row of src/scripts and the total row"
    _dash( repo, "write" )
    rc, text = _dash( repo, "check" )
    assert rc == dm.EXIT_OK and "WARNING" not in text


def test_a_line_added_to_the_rows_of_the_page_is_stale_numbers_too( repo ):
    _dash( repo, "write" )
    page = _page( repo )
    ( repo / PAGE ).write_text( page.replace( "```text\n", "```text\nan extra line\n" ), encoding="utf-8" )
    rc, text = _dash( repo, "check" )
    assert rc == dm.EXIT_NUMBERS_STALE and "1 of its rows differ from the tree" in text


def test_check_exits_3_when_a_tracked_package_has_no_row_on_the_page( repo ):
    _dash( repo, "write" )
    _put( repo, { "src/later/__init__.py": '"""Later."""\n', "src/scratch/untracked.py": '"""Scratch."""\n' } )
    assert _dash( repo, "check" )[ 0 ] == 0, "an untracked file is not in the swept population"
    _git( repo, "add", "src/later/__init__.py" )
    rc, text = _dash( repo, "check" )
    assert rc == dm.EXIT_PAGE_STALE and "6 rows checked" in text and "2 new, 0 rose, 1 not on the page" in text
    assert f"MISSING src/later: no row on {PAGE}; regenerate with: " in text and "dashboard write" in text
    assert text.count( "MISSING" ) == 1 and "src/scratch" not in text


def test_a_missing_row_is_matched_by_its_whole_name_and_not_by_a_prefix( repo ):
    _dash( repo, "write" )
    lines = _page( repo ).split( "\n" )
    gone  = [ line for line in lines if line.split( "|" )[ 0 ].strip() == "src/app" ]
    assert len( gone ) == 1 and len( [ line for line in lines if line.startswith( "src/app/sub " ) ] ) == 1
    ( repo / PAGE ).write_text( "\n".join( line for line in lines if line != gone[ 0 ] ), encoding="utf-8" )
    rc, text = _dash( repo, "check" )
    assert rc == dm.EXIT_PAGE_STALE == 3 and f"MISSING src/app: no row on {PAGE}; " in text
    assert text.count( "MISSING" ) == 1 and "1 not on the page" in text
    assert text.endswith( "DASHBOARD CHECK FAILED: 0 values rose in 0 rows; the page does not match the tree.\n" )


def test_check_exits_3_when_the_page_was_written_against_another_base( repo ):
    _dash( repo, "write" )
    rc, text = _dash( repo, "check", base="HEAD" )
    head = _git( repo, "rev-parse", "HEAD" )
    assert rc == dm.EXIT_PAGE_STALE and f"STALE {PAGE}: the page does not name base {head}; regenerate with: " in text
    assert "0 rose, 0 not on the page" in text


def test_a_rise_outranks_a_missing_row_and_both_are_printed( repo ):
    _dash( repo, "write" )
    _put( repo, { "src/later/__init__.py": '"""Later."""\n', "src/scripts/run.py": '"""Run the job \u2014 now."""\n' } )
    _git( repo, "add", "src/later/__init__.py" )
    rc, text = _dash( repo, "check" )
    assert rc == dm.EXIT_ROSE and "ROSE src/scripts: em_dash" in text and "MISSING src/later: " in text


def test_check_exits_2_when_there_is_no_page( repo ):
    rc, text = _dash( repo, "check" )
    assert rc == dm.EXIT_NOT_CHECKED == 2 and text.startswith( "doc-metrics dashboard: could not check: FileNotFoundError: " ) and PAGE in text
    assert "DASHBOARD CHECK" not in text


def test_check_exits_2_and_not_1_when_the_page_is_not_utf8( repo ):
    ( repo / PAGE ).write_bytes( b"\xff\xfe" )
    rc, text = _dash( repo, "check" )
    assert rc == dm.EXIT_NOT_CHECKED and rc != dm.EXIT_ROSE
    assert text.startswith( "doc-metrics dashboard: could not check: UnicodeDecodeError: " ) and text.count( "\n" ) == 1


def test_check_and_write_exit_2_when_the_base_does_not_resolve( repo ):
    _dash( repo, "write" )
    rc, text = _dash( repo, "check", base="nope" )
    assert rc == dm.EXIT_NOT_CHECKED and text.startswith( "doc-metrics dashboard: could not check: RuntimeError: git rev-parse" )
    rc, text = _dash( repo, "write", base="nope" )
    assert rc == dm.EXIT_NOT_CHECKED and text.startswith( "doc-metrics dashboard: could not write: RuntimeError: git rev-parse" )


def test_write_exits_2_when_the_page_cannot_be_written( repo ):
    rc, text = _dash( repo, "write", "--page", "no-such-dir/page.md" )
    assert rc == dm.EXIT_NOT_CHECKED and text.startswith( "doc-metrics dashboard: could not write: FileNotFoundError: " ) and not ( repo / "no-such-dir" ).exists()


def test_the_page_option_moves_both_the_write_and_the_check( repo ):
    rc, said = _dash( repo, "write", "--page", "src/docs/other.md" )
    assert rc == 0 and said.startswith( "doc-metrics dashboard: wrote src/docs/other.md, 5 rows; " ) and not ( repo / PAGE ).exists()
    assert _dash( repo, "check", "--page", "src/docs/other.md" )[ 0 ] == 0
    assert _dash( repo, "check" )[ 0 ] == 2


def test_the_dashboard_defaults_to_the_named_base_and_to_stdout( repo, capsys, monkeypatch ):
    monkeypatch.setattr( dm, "BASE_SHA", _git( repo, "rev-parse", "base" ) )
    assert dm.main( [ "dashboard", "write", "--repo-root", str( repo ), "--words-root", str( repo ) ] ) == 0
    assert capsys.readouterr().out.startswith( f"doc-metrics dashboard: wrote {PAGE}, 5 rows; " )
    assert f"- Before: commit `{dm.BASE_SHA}`\n" in _page( repo )
    assert dm.main( [ "dashboard", "check", "--repo-root", str( repo ), "--words-root", str( repo ) ] ) == 0


def test_the_packages_command_still_runs_beside_the_dashboard( repo ):
    out = io.StringIO()
    rc  = dm.main( [ "src/app", "--base", "base", "--repo-root", str( repo ), "--words-root", str( repo ) ], out=out )
    assert rc == 0 and out.getvalue().split( "\n" )[ 2 ].startswith( "| src/app | 4 -> 4 (+0/-0) | 0 -> 0 | 11 -> 8 | " )


def test_the_word_dashboard_after_the_first_argument_is_a_package_of_the_old_command( repo ):
    out = io.StringIO()
    rc  = dm.main( [ "src/app", "dashboard", "--base", "base", "--repo-root", str( repo ), "--words-root", str( repo ) ], out=out )
    rows = out.getvalue().split( "\n" )
    assert rc == 0 and rows[ 0 ].startswith( "| package | files | unparsed | tokens | " )
    assert rows[ 2 ].startswith( "| src/app | 4 -> 4 (+0/-0) | " ) and rows[ 3 ].startswith( "| dashboard | 0 -> 0 (+0/-0) | " )
    assert "doc-metrics dashboard" not in out.getvalue()


# ---- mutation check: each mutant of the module must redden its named test ----

MUTANTS = [
    ( "return sorted( n for n in names if is_swept( n ) )", "return sorted( n for n in names if n.endswith( \".py\" ) )", "test_swept_at_lists_a_revision_and_the_tree_without_tests_or_held_files" ),
    ( "names = [ n for n in _git( root, \"ls-files\", \"-z\" ).split( \"\\0\" ) if os.path.exists( f\"{root}/{n}\" ) ]", "names = _git( root, \"ls-files\", \"-z\" ).split( \"\\0\" )", "test_swept_at_the_tree_counts_tracked_files_that_are_still_on_disk" ),
    ( "befores   = { name: files_metrics( root, old[ name ][ \"paths\" ], base_sha ) for name in old }", "befores   = { name: package_metrics( root, name, base_sha ) for name in old }", "test_the_parent_row_is_measured_without_its_subpackage_before_and_after" ),
    ( "after  = files_metrics( root, row[ \"paths\" ], head )", "after  = package_metrics( root, name, head )", "test_the_parent_row_is_measured_without_its_subpackage_before_and_after" ),
    ( "rose   = [] if before is None else risen( before, after )", "rose   = risen( before or files_metrics( root, [], base_sha ), after )", "test_a_package_with_no_before_is_marked_new_and_is_not_a_failure" ),
    ( "\"before\": sum_metrics( list( befores.values() ) )", "\"before\": sum_metrics( [ r[ \"before\" ] for r in rows if r[ \"before\" ] ] )", "test_the_total_before_counts_a_directory_that_is_gone_at_head" ),
    ( "if metric_value( after, name ) <= metric_value( before, name ): return False", "if metric_value( after, name ) < metric_value( before, name ): return False", "test_a_higher_marker_count_is_not_a_rise_when_the_rate_fell_or_held" ),
    ( "if metric_value( after, name ) <= metric_value( before, name ): return False", "if False: return False", "test_a_higher_marker_count_is_not_a_rise_when_the_rate_fell_or_held" ),
    ( "if metric_value( after, name ) <= metric_value( before, name ): return False", "if name != \"tokens\" and rates_per_thousand( after[ \"counts\" ] )[ name ] <= rates_per_thousand( before[ \"counts\" ] )[ name ]: return False", "test_risen_is_exact_where_the_one_decimal_display_would_hide_a_rise" ),
    ( "return name == \"tokens\" or after[ \"counts\" ][ name ] > before[ \"counts\" ][ name ]", "return True", "test_risen_is_exact_where_the_one_decimal_display_would_hide_a_rise" ),
    ( "return name == \"tokens\" or after[ \"counts\" ][ name ] > before[ \"counts\" ][ name ]", "return True", "test_fewer_tokens_with_the_same_marker_count_pass_the_check" ),
    ( "return name == \"tokens\" or after[ \"counts\" ][ name ] > before[ \"counts\" ][ name ]", "return name == \"tokens\" or after[ \"counts\" ][ name ] >= before[ \"counts\" ][ name ]", "test_risen_is_exact_where_the_one_decimal_display_would_hide_a_rise" ),
    ( "return [ name for name in COMPARED_METRICS if has_risen( before, after, name ) ]", "return [ name for name in MARKER_COLUMNS if has_risen( before, after, name ) ]", "test_more_tokens_fail_the_check_when_the_constant_also_names_tokens" ),
    ( "COMPARED_METRICS = MARKER_COLUMNS", "COMPARED_METRICS = ( *MARKER_COLUMNS, \"tokens\" )", "test_more_tokens_alone_pass_the_check_under_the_marker_rates_setting" ),
    ( "board  = build_dashboard( root, base )\n    names  = page_packages( text )", "board  = build_dashboard( root, base, \"HEAD\" )\n    names  = page_packages( text )", "test_check_exits_1_and_names_the_package_and_the_raw_counts_when_a_rate_rose" ),
    ( "missing    = [ r[ \"package\" ] for r in board[ \"rows\" ] if r[ \"package\" ] not in names ]", "missing    = []", "test_check_exits_3_when_a_tracked_package_has_no_row_on_the_page" ),
    ( "missing    = [ r[ \"package\" ] for r in board[ \"rows\" ] if r[ \"package\" ] not in names ]", "missing    = [ r[ \"package\" ] for r in board[ \"rows\" ] if not any( n.startswith( r[ \"package\" ] ) for n in names ) ]", "test_a_missing_row_is_matched_by_its_whole_name_and_not_by_a_prefix" ),
    ( "stale_base = BEFORE_LINE.format( board[ \"base\" ] ) not in text.split( \"\\n\" )", "stale_base = False", "test_check_exits_3_when_the_page_was_written_against_another_base" ),
    ( "stale_rows = differ > 0 or page_rows != fresh_rows", "stale_rows = False", "test_check_exits_4_with_a_warning_line_when_a_value_on_the_page_is_not_the_trees" ),
    ( "stale_rows = differ > 0 or page_rows != fresh_rows", "stale_rows = False", "test_check_exits_4_when_a_docstring_changed_and_the_page_was_not_written_again" ),
    ( "return EXIT_NUMBERS_STALE, lines + [", "return EXIT_PAGE_STALE, lines + [", "test_check_exits_4_with_a_warning_line_when_a_value_on_the_page_is_not_the_trees" ),
    ( "return EXIT_NUMBERS_STALE, lines + [", "return EXIT_OK, lines + [", "test_check_exits_4_when_a_docstring_changed_and_the_page_was_not_written_again" ),
    ( "if stale_rows: lines.append( NUMBERS_LINE.format(", "if False: lines.append( NUMBERS_LINE.format(", "test_check_exits_4_with_a_warning_line_when_a_value_on_the_page_is_not_the_trees" ),
    ( "differ     = max( len( fresh_rows - page_rows ), len( page_rows - fresh_rows ) )", "differ     = len( fresh_rows - page_rows )", "test_a_line_added_to_the_rows_of_the_page_is_stale_numbers_too" ),
    ( "if rose or missing or stale_base:", "if rose or stale_base:", "test_a_missing_row_is_matched_by_its_whole_name_and_not_by_a_prefix" ),
    ( "return ( EXIT_ROSE if rose else EXIT_PAGE_STALE ), lines", "return ( EXIT_ROSE if rose and not missing else EXIT_PAGE_STALE ), lines", "test_a_rise_outranks_a_missing_row_and_both_are_printed" ),
    ( "return ( EXIT_ROSE if rose else EXIT_PAGE_STALE ), lines", "return ( EXIT_ROSE if rose and not stale_rows else EXIT_PAGE_STALE ), lines", "test_check_recomputes_from_the_tree_and_does_not_trust_the_page" ),
    ( "board = build_dashboard( root, args.base, args.head )", "board = build_dashboard( root, args.base )", "test_write_with_a_head_revision_measures_that_commit_and_not_the_tree" ),
    ( "except Exception as err:", "except ( RuntimeError, OSError ) as err:", "test_check_exits_2_and_not_1_when_the_page_is_not_utf8" ),
    ( "if argv[ : 1 ] == [ \"dashboard\" ]: return dashboard_main( argv[ 1: ], out )", "if \"dashboard\" in argv: return dashboard_main( argv[ 1: ], out )", "test_the_word_dashboard_after_the_first_argument_is_a_package_of_the_old_command" ),
    ( "return { line.split( \"|\" )[ 0 ].strip() for line in rows_block( text ).split( \"\\n\" )[ 1 : -2 ] }", "return { line.split( \"|\" )[ 0 ].strip() for line in rows_block( text ).split( \"\\n\" )[ 1 : -1 ] }", "test_page_packages_reads_the_row_names_and_not_the_header" ),
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
    with pytest.raises( ( AssertionError, UnicodeDecodeError, SystemExit ) ):  # two mutants leave by an uncaught error, not by a failed assert
        this[ named_test ]( **kwargs() )
