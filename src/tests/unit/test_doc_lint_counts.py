"""
Unit tests for doc_lint.counts: the per-file finding counts for the Python files the sweep did not reach.
"""

import io
import json
import subprocess

import pytest

from cosa.repo.doc_lint import counts, word_list
from cosa.repo.doc_lint.text_rules import Finding

WORDS = [ "not", "never", "the" ]


def _git( root, *args ):
    res = subprocess.run( [ "git", "-C", str( root ), "-c", "user.email=t@t", "-c", "user.name=t", *args ], capture_output=True, text=True )
    assert res.returncode == 0, res.stderr
    return res.stdout


@pytest.fixture
def repo( tmp_path ):
    _git( tmp_path, "init", "-q" )
    for rel in counts.STAMP_FILES:
        full = tmp_path / rel
        full.parent.mkdir( parents=True, exist_ok=True )
        full.write_text( f"stamp file {rel}\n", encoding="utf-8" )
    ( tmp_path / "src" / "conf" / "dm-tutor-lowercase-words.txt" ).write_text( "\n".join( WORDS ) + "\n", encoding="utf-8" )
    yield tmp_path
    word_list._state[ "root" ]  = None
    word_list._state[ "words" ] = None


def _doc( line ):
    return f'def f():\n    """\n    Return it.\n\n    {line}\n    """\n'


CAPS  = _doc( "This is NOT fine." )
CLEAN = _doc( "Return the thing." )


def _stage( repo, files ):
    for rel, text in files.items():
        full = repo / rel
        full.parent.mkdir( parents=True, exist_ok=True )
        full.write_text( text, encoding="utf-8" )
    _git( repo, "add", "-f", *files )


# ---- file_count ------------------------------------------------------------------------------

def test_file_count_counts_each_finding_and_names_them( repo ):
    word_list.configure_root( repo )
    result = counts.file_count( "src/a.py", _doc( "This is NOT fine and NEVER good." ), str( repo ) )
    assert result.count == 2 and result.waivers == 0 and [ f.rule for f in result.findings ] == [ "caps", "caps" ]
    assert counts.file_count( "src/a.py", CLEAN, str( repo ) ) == counts.FileCount( 0, [], 0 )


def test_an_honoured_waiver_lowers_the_count_and_is_counted( repo ):
    word_list.configure_root( repo )
    result = counts.file_count( "src/a.py", _doc( "This is NOT fine.  doc-lint: waive caps -- quoted from the standard" ), str( repo ) )
    assert result.count == 0 and result.waivers == 1 and result.findings == []


def test_a_waiver_without_a_reason_or_for_another_rule_leaves_the_count( repo ):
    word_list.configure_root( repo )
    for marker in ( "doc-lint: waive caps", "doc-lint: waive tic -- wrong rule here" ):
        result = counts.file_count( "src/a.py", _doc( f"This is NOT fine.  {marker}" ), str( repo ) )
        assert result.count == 1 and result.waivers == 0, marker


def test_a_file_that_does_not_parse_counts_as_one_finding_and_waivers_are_not_read( repo ):
    result = counts.file_count( "src/a.py", 'def f(:\n    """x  doc-lint: waive parse-error -- trying it"""\n', str( repo ) )
    assert result.count == 1 and result.waivers == 0 and result.findings[ 0 ].rule == "parse-error"


def test_unreadable_count_is_one_finding_on_line_one():
    err    = UnicodeDecodeError( "utf-8", b"\xe9", 0, 1, "invalid continuation byte" )
    result = counts.unreadable_count( "src/a.py", err )
    assert result.count == 1 and result.waivers == 0
    assert result.findings == [ Finding( "src/a.py", 1, "not-utf-8", f"not UTF-8: {err}" ) ]


# ---- counted_paths and census ----------------------------------------------------------------

def test_counted_paths_are_the_tracked_python_files_that_are_not_swept( repo ):
    _stage( repo, {
        "src/pkg/swept.py"        : CLEAN,
        "src/lupin_mcp/b.py"      : CLEAN,
        "src/tests/unit/t.py"     : CLEAN,
        "src/pkg/test_c.py"       : CLEAN,
        "src/rnd/v1/d.py"         : CLEAN,
        "src/pkg/notes.md"        : "text\n",
    } )
    assert counts.counted_paths( str( repo ) ) == [ "src/lupin_mcp/b.py", "src/pkg/test_c.py", "src/rnd/v1/d.py", "src/tests/unit/t.py" ]


def test_counted_paths_names_a_git_error( tmp_path ):
    with pytest.raises( RuntimeError, match="git ls-files failed" ):
        counts.counted_paths( str( tmp_path ) )


def test_census_counts_each_file_and_says_how_many_it_walked( repo ):
    _stage( repo, { "src/lupin_mcp/a.py": CAPS, "src/lupin_mcp/clean.py": CLEAN, "src/tests/t.py": _doc( "This is NOT fine and NEVER good." ), "src/pkg/swept.py": CAPS } )
    word_list.configure_root( repo )
    found, walked = counts.census( str( repo ) )
    assert found == { "src/lupin_mcp/a.py": 1, "src/tests/t.py": 2 } and walked == 3


def test_census_counts_a_non_utf8_file_as_one_and_uses_the_reader_it_is_given( repo ):
    _stage( repo, { "src/lupin_mcp/a.py": CLEAN, "src/lupin_mcp/b.py": CLEAN } )
    ( repo / "src" / "lupin_mcp" / "a.py" ).write_bytes( b'def f():\n    """caf\xe9."""\n' )
    word_list.configure_root( repo )
    found, walked = counts.census( str( repo ) )
    assert found == { "src/lupin_mcp/a.py": 1 } and walked == 2
    swapped, _ = counts.census( str( repo ), read=lambda path: CAPS if path.endswith( "b.py" ) else CLEAN )
    assert swapped == { "src/lupin_mcp/b.py": 1 }                                # the reader decided, not the disk


def test_census_over_an_empty_tree_reports_zero_walked( repo ):
    assert counts.census( str( repo ) ) == ( {}, 0 )


def test_census_reads_a_byte_order_mark_like_any_other_file( repo ):
    _stage( repo, { "src/lupin_mcp/a.py": CLEAN } )
    ( repo / "src" / "lupin_mcp" / "a.py" ).write_bytes( b"\xef\xbb\xbf" + _doc( "This is NOT fine and NEVER good." ).encode( "utf-8" ) )
    word_list.configure_root( repo )
    assert counts.census( str( repo ) ) == ( { "src/lupin_mcp/a.py": 2 }, 1 )       # its two findings, not one parse error


# ---- rules_stamp -----------------------------------------------------------------------------

def test_rules_stamp_is_stable_and_moves_with_any_rule_file( repo ):
    first = counts.rules_stamp( str( repo ) )
    assert first == counts.rules_stamp( str( repo ) ) and len( first ) == 16
    for rel in counts.STAMP_FILES:
        full = repo / rel
        before = full.read_text( encoding="utf-8" )
        full.write_text( before + "x\n", encoding="utf-8" )
        assert counts.rules_stamp( str( repo ) ) != first, rel
        full.write_text( before, encoding="utf-8" )
    assert counts.rules_stamp( str( repo ) ) == first


def test_rules_stamp_moves_when_a_boundary_moves_between_two_rule_files( repo ):
    one, two = repo / counts.STAMP_FILES[ 0 ], repo / counts.STAMP_FILES[ 1 ]
    one.write_text( "ab", encoding="utf-8" )
    two.write_text( "c", encoding="utf-8" )
    first = counts.rules_stamp( str( repo ) )
    one.write_text( "a", encoding="utf-8" )
    two.write_text( "bc", encoding="utf-8" )                                      # the same bytes in the same order, split elsewhere
    assert counts.rules_stamp( str( repo ) ) != first


def test_rules_stamp_reads_what_the_given_reader_returns( repo ):
    on_disk = counts.rules_stamp( str( repo ) )
    staged  = counts.rules_stamp( str( repo ), read=lambda path: b"staged " + path.encode( "utf-8" ) )
    assert staged != on_disk and staged == counts.rules_stamp( str( repo ), read=lambda path: b"staged " + path.encode( "utf-8" ) )
    assert counts.rules_stamp( str( repo ), read=lambda path: ( repo / path ).read_bytes() ) == on_disk


def test_rules_stamp_names_a_missing_rule_file( tmp_path ):
    with pytest.raises( OSError ):
        counts.rules_stamp( str( tmp_path ) )


# ---- the table text --------------------------------------------------------------------------

def test_table_text_is_one_sorted_entry_per_line_and_round_trips():
    text = counts.table_text( { "src/b.py": 2, "src/a.py": 10 }, "abc123" )
    assert text == '{\n  "format": 1,\n  "rules_stamp": "abc123",\n  "files": {\n    "src/a.py": 10,\n    "src/b.py": 2\n  }\n}\n'
    assert counts.parse_table( text ) == counts.Table( "abc123", { "src/a.py": 10, "src/b.py": 2 } )
    assert json.loads( text )[ "files" ] == { "src/a.py": 10, "src/b.py": 2 }


def test_an_empty_table_is_valid_json_and_round_trips():
    text = counts.table_text( {}, "abc123" )
    assert json.loads( text ) == { "format": 1, "rules_stamp": "abc123", "files": {} }
    assert counts.parse_table( text ) == counts.Table( "abc123", {} )


@pytest.mark.parametrize( "text,message", [
    ( "not json",                                                              "table is not JSON" ),
    ( "[1]",                                                                   "table format is not 1" ),
    ( '{"format": 2, "rules_stamp": "a", "files": {}}',                        "table format is not 1" ),
    ( '{"format": 1, "files": {}}',                                            "table has no rules_stamp" ),
    ( '{"format": 1, "rules_stamp": "a"}',                                     "table has no files object" ),
    ( '{"format": 1, "rules_stamp": "a", "files": {"a.py": 0}}',               "not an integer above zero" ),
    ( '{"format": 1, "rules_stamp": "a", "files": {"a.py": -2}}',              "not an integer above zero" ),
    ( '{"format": 1, "rules_stamp": "a", "files": {"a.py": true}}',            "not an integer above zero" ),
    ( '{"format": 1, "rules_stamp": "a", "files": {"a.py": "3"}}',             "not an integer above zero" ),
] )
def test_parse_table_refuses_each_malformed_shape_by_name( text, message ):
    with pytest.raises( counts.TableError, match=message ):
        counts.parse_table( text )


# ---- allowance and table_raises --------------------------------------------------------------

def test_allowance_is_the_entry_then_the_renamed_from_entry_then_zero():
    files = { "src/a.py": 5, "src/old.py": 7 }
    assert counts.allowance( "src/a.py", files, {} ) == 5
    assert counts.allowance( "src/new.py", files, { "src/new.py": "src/old.py" } ) == 7
    assert counts.allowance( "src/a.py", files, { "src/a.py": "src/old.py" } ) == 5          # its own entry wins
    assert counts.allowance( "src/fresh.py", files, {} ) == 0
    assert counts.allowance( "src/new.py", files, { "src/new.py": "src/gone.py" } ) == 0


def test_table_raises_lists_a_raised_or_new_entry_and_not_a_lowered_or_deleted_one():
    head   = { "src/a.py": 5, "src/b.py": 3, "src/c.py": 2 }
    staged = { "src/a.py": 6, "src/b.py": 2, "src/d.py": 1 }                                     # a up, b down, c deleted, d new
    assert counts.table_raises( staged, head ) == [ ( "src/a.py", 5, 6 ), ( "src/d.py", 0, 1 ) ]
    assert counts.table_raises( head, head ) == [] and counts.table_raises( {}, head ) == []


# ---- check_table -----------------------------------------------------------------------------

def test_check_table_is_empty_for_an_exact_table():
    assert counts.check_table( counts.Table( "s", { "src/lupin_mcp/a.py": 2 } ), { "src/lupin_mcp/a.py": 2 }, "s" ) == []


def test_check_table_names_a_stale_stamp_and_a_difference_in_each_direction():
    table    = counts.Table( "old", { "src/lupin_mcp/a.py": 3, "src/lupin_mcp/gone.py": 1 } )
    problems = counts.check_table( table, { "src/lupin_mcp/a.py": 2, "src/lupin_mcp/new.py": 4 }, "new" )
    assert problems == [
        "rules_stamp old is not the current new: regenerate the table",
        "src/lupin_mcp/a.py: table 3, census 2",
        "src/lupin_mcp/gone.py: table 1, census 0",
        "src/lupin_mcp/new.py: table 0, census 4",
    ]


def test_check_table_refuses_an_entry_for_a_swept_path():
    problems = counts.check_table( counts.Table( "s", { "src/pkg/a.py": 1 } ), { "src/pkg/a.py": 1 }, "s" )
    assert problems == [ "src/pkg/a.py: swept, so no entry is allowed" ]


# ---- the command line ------------------------------------------------------------------------

def _run( repo, *flags ):
    out = io.StringIO()
    rc  = counts.main( [ "--repo-root", str( repo ), *flags ], out )
    return rc, out.getvalue()


def test_write_then_check_is_exact_and_prints_the_denominator( repo ):
    _stage( repo, { "src/lupin_mcp/a.py": CAPS, "src/tests/t.py": CLEAN } )
    rc, text = _run( repo, "--write" )
    assert rc == counts.EXIT_TIGHT and text == "wrote 1 entries from 2 counted files\n"
    written = ( repo / counts.TABLE_PATH ).read_text( encoding="utf-8" )
    assert counts.parse_table( written ) == counts.Table( counts.rules_stamp( str( repo ) ), { "src/lupin_mcp/a.py": 1 } )
    rc, text = _run( repo, "--check" )
    assert rc == counts.EXIT_TIGHT and text == "2 counted files walked, 0 problems\n"


def test_check_reports_a_file_that_rose_and_one_that_fell( repo ):
    _stage( repo, { "src/lupin_mcp/a.py": CAPS, "src/lupin_mcp/b.py": CAPS } )
    _run( repo, "--write" )
    ( repo / "src" / "lupin_mcp" / "a.py" ).write_text( _doc( "This is NOT fine and NEVER good." ), encoding="utf-8" )
    ( repo / "src" / "lupin_mcp" / "b.py" ).write_text( CLEAN, encoding="utf-8" )
    rc, text = _run( repo, "--check" )
    assert rc == counts.EXIT_MISMATCH
    assert "src/lupin_mcp/a.py: table 1, census 2" in text and "src/lupin_mcp/b.py: table 1, census 0" in text and "2 problems" in text


def test_check_is_not_checked_when_the_table_is_missing_or_malformed_or_the_tree_is_not_git( repo, tmp_path_factory ):
    rc, text = _run( repo, "--check" )
    assert rc == counts.EXIT_NOT_CHECKED and text.startswith( "not checked: FileNotFoundError" )
    ( repo / counts.TABLE_PATH ).write_text( "garbage", encoding="utf-8" )
    rc, text = _run( repo, "--check" )
    assert rc == counts.EXIT_NOT_CHECKED and "TableError: table is not JSON" in text
    rc, text = _run( tmp_path_factory.mktemp( "nogit" ), "--check" )
    assert rc == counts.EXIT_NOT_CHECKED and "RuntimeError: git ls-files failed" in text


def test_the_command_line_needs_exactly_one_mode( repo ):
    with pytest.raises( SystemExit ):
        counts.main( [ "--repo-root", str( repo ) ], io.StringIO() )
