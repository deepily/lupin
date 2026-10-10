"""
Unit tests for doc_lint.ts_counts: per-file finding counts for TypeScript and JavaScript.

The Node extractor is replaced by a stand-in that reads one-line JSDoc blocks, so these tests need no Node.
One test at the end runs the real extractor and is skipped when Node is not installed.
"""

import io
import json
import os
import shutil
import subprocess

import pytest

import cosa.utils.util as cu
from cosa.repo.doc_lint import counts, ts_counts, tsdoc_lint, word_list

WORDS = [ "not", "never", "the" ]


def _git( root, *args ):
    res = subprocess.run( [ "git", "-C", str( root ), "-c", "user.email=t@t", "-c", "user.name=t", *args ], capture_output=True, text=True )
    assert res.returncode == 0, res.stderr
    return res.stdout


@pytest.fixture
def repo( tmp_path ):
    _git( tmp_path, "init", "-q" )
    for rel in ts_counts.STAMP_FILES:
        full = tmp_path / rel
        full.parent.mkdir( parents=True, exist_ok=True )
        full.write_text( f"stamp file {rel}\n", encoding="utf-8" )
    ( tmp_path / "src" / "conf" / "dm-tutor-lowercase-words.txt" ).write_text( "\n".join( WORDS ) + "\n", encoding="utf-8" )
    yield tmp_path
    word_list._state[ "root" ]  = None
    word_list._state[ "words" ] = None


def fake_extract( root, texts ):
    """Stand in for the Node extractor: a one-line JSDoc block becomes one record."""
    out = {}
    for path, text in texts.items():
        records = [ { "kind": "file", "file": path, "ts_version": "5.9.3", "parse_errors": [ { "line": 1, "message": "broken" } ] if "BROKEN" in text else [] } ]
        for i, line in enumerate( text.split( "\n" ) ):
            if "/**" in line and "*/" in line:
                body = line.split( "/**", 1 )[ 1 ].split( "*/", 1 )[ 0 ].strip()
                records.append( { "kind": "jsdoc", "file": path, "text": body, "start_line": i + 1, "end_line": i + 1, "symbol_key": None,
                                  "directive": False, "tags": [], "ts_version": "5.9.3", "commented_code": False } )
        out[ path ] = records
    return out


@pytest.fixture
def extractor( monkeypatch ):
    monkeypatch.setattr( ts_counts, "extract", fake_extract )


def block( text ):
    return f"/** {text} */\nexport const x = 1;\n"


CLEAN = block( "Return the thing." )
ONE   = block( "This is NOT fine." )
TWO   = block( "This is NOT fine and NEVER good." )


# ---- the stamp and the table path ----------------------------------------------------------

def test_the_table_is_its_own_file_beside_the_python_table():
    assert ts_counts.TABLE_PATH == "src/conf/doc-lint-ts-counts.json" and ts_counts.TABLE_PATH != counts.TABLE_PATH


def test_the_stamp_files_are_the_python_ones_plus_the_comment_linter_and_the_extractor():
    assert set( ts_counts.STAMP_FILES ) == set( counts.STAMP_FILES ) | { "src/cosa/repo/doc_lint/tsdoc_lint.py", "src/scripts/ts_doc_extract.mjs" }


def test_the_extractor_script_is_a_rule_file_so_an_unstaged_edit_to_it_is_a_divergence():
    assert "src/scripts/ts_doc_extract.mjs" in counts.RULE_PATHS


def test_rules_stamp_moves_with_the_extractor_and_with_the_comment_linter_and_the_python_stamp_does_not( repo ):
    first_ts, first_py = ts_counts.rules_stamp( str( repo ) ), counts.rules_stamp( str( repo ) )
    ( repo / "src/scripts/ts_doc_extract.mjs" ).write_text( "changed\n", encoding="utf-8" )
    second_ts = ts_counts.rules_stamp( str( repo ) )
    assert second_ts != first_ts and counts.rules_stamp( str( repo ) ) == first_py
    ( repo / "src/cosa/repo/doc_lint/tsdoc_lint.py" ).write_text( "changed\n", encoding="utf-8" )
    assert ts_counts.rules_stamp( str( repo ) ) not in ( first_ts, second_ts )


def test_rules_stamp_reads_what_the_given_reader_returns( repo ):
    seen = []
    def read( path ):
        seen.append( path )
        return b"x"
    ts_counts.rules_stamp( str( repo ), read=read )
    assert seen == list( ts_counts.STAMP_FILES )


# ---- counting one file ---------------------------------------------------------------------

def _records( text, path="a.ts" ):
    return fake_extract( None, { path: text } )[ path ]


def test_count_records_counts_each_finding_and_names_them( repo ):
    result = ts_counts.count_records( "a.ts", _records( TWO ), TWO, str( repo ) )
    assert result.count == 2 and [ ( f.line, f.rule ) for f in result.findings ] == [ ( 1, "caps" ), ( 1, "caps" ) ] and result.waivers == 0
    assert ts_counts.count_records( "a.ts", _records( CLEAN ), CLEAN, str( repo ) ).count == 0


def test_an_honoured_waiver_lowers_the_count_and_is_counted( repo ):
    text   = "/** This is NOT fine. */ // doc-lint: waive caps -- legacy wording kept\n"
    result = ts_counts.count_records( "a.ts", _records( text ), text, str( repo ) )
    assert ( result.count, result.waivers ) == ( 0, 1 )


def test_a_waiver_without_a_reason_or_for_another_rule_leaves_the_count( repo ):
    for marker in ( "doc-lint: waive caps", "doc-lint: waive caps -- ..", "doc-lint: waive tic -- some real reason" ):
        text = f"/** This is NOT fine. */ // {marker}\n"
        assert ts_counts.count_records( "a.ts", _records( text ), text, str( repo ) ).count == 1


def test_a_file_that_does_not_parse_adds_one_finding_and_its_comments_are_still_counted( repo ):
    text   = "BROKEN\n" + ONE
    result = ts_counts.count_records( "a.ts", _records( text ), text, str( repo ) )
    assert result.count == 2 and sorted( f.rule for f in result.findings ) == [ "caps", "parse-error" ]


# ---- extracting staged text ----------------------------------------------------------------

def test_extract_writes_the_given_texts_to_a_scratch_tree_and_reads_them_from_there( repo, monkeypatch ):
    seen = {}
    def fake_run( root, files, source_root=None ):
        seen[ "root" ], seen[ "files" ], seen[ "source_root" ] = root, list( files ), str( source_root )
        seen[ "disk" ] = { f: open( os.path.join( str( source_root ), f ), encoding="utf-8" ).read() for f in files }
        return { f: [] for f in files }
    monkeypatch.setattr( tsdoc_lint, "run_extractor", fake_run )
    out = ts_counts.extract( str( repo ), { "src/a.ts": "one\n", "src/deep/b.mjs": "two\n" } )
    assert out == { "src/a.ts": [], "src/deep/b.mjs": [] } and seen[ "root" ] == str( repo ) and seen[ "files" ] == [ "src/a.ts", "src/deep/b.mjs" ]
    assert seen[ "disk" ] == { "src/a.ts": "one\n", "src/deep/b.mjs": "two\n" } and seen[ "source_root" ] != str( repo )
    assert not os.path.exists( seen[ "source_root" ] )                                   # the scratch tree is gone


def test_extract_removes_the_scratch_tree_when_the_extractor_fails( repo, monkeypatch ):
    seen = {}
    def boom( root, files, source_root=None ):
        seen[ "dir" ] = str( source_root )
        raise RuntimeError( "extractor failed" )
    monkeypatch.setattr( tsdoc_lint, "run_extractor", boom )
    with pytest.raises( RuntimeError, match="extractor failed" ):
        ts_counts.extract( str( repo ), { "a.ts": "x\n" } )
    assert not os.path.exists( seen[ "dir" ] )


def test_extract_with_no_texts_starts_nothing( repo, monkeypatch ):
    monkeypatch.setattr( tsdoc_lint, "run_extractor", lambda *a, **k: pytest.fail( "no process for no files" ) )
    assert ts_counts.extract( str( repo ), {} ) == {}


def test_counts_for_counts_every_text_it_is_given( repo, extractor ):
    got = ts_counts.counts_for( str( repo ), { "a.ts": TWO, "b.ts": CLEAN } )
    assert { p: r.count for p, r in got.items() } == { "a.ts": 2, "b.ts": 0 }


# ---- the population and the census ---------------------------------------------------------

def _track( repo, files ):
    for rel, text in files.items():
        full = repo / rel
        full.parent.mkdir( parents=True, exist_ok=True )
        full.write_text( text, encoding="utf-8" )
    _git( repo, "add", "-f", *files )


def test_counted_paths_are_the_tracked_typescript_and_javascript_files_in_scope( repo ):
    _track( repo, { "src/a.ts": CLEAN, "src/b.js": CLEAN, "src/c.mjs": CLEAN, "src/d.py": "x\n", "node_modules/e.js": CLEAN, "src/x/dist/f.js": CLEAN } )
    assert ts_counts.counted_paths( str( repo ) ) == [ "src/a.ts", "src/b.js", "src/c.mjs" ]


def test_counted_paths_name_a_git_error( tmp_path ):
    with pytest.raises( RuntimeError, match="git ls-files failed" ):
        ts_counts.counted_paths( str( tmp_path ) )


def test_census_counts_each_file_and_says_how_many_it_walked( repo, extractor ):
    _track( repo, { "src/a.ts": TWO, "src/b.ts": CLEAN, "src/c.js": ONE } )
    found, walked = ts_counts.census( str( repo ) )
    assert found == { "src/a.ts": 2, "src/c.js": 1 } and walked == 3


def test_census_counts_a_file_that_is_not_utf8_as_one_finding_and_uses_the_reader_it_is_given( repo, extractor ):
    _track( repo, { "src/a.ts": CLEAN, "src/b.ts": CLEAN } )
    def read( path ):
        if path == "src/a.ts": raise UnicodeDecodeError( "utf-8", b"\xff", 0, 1, "invalid start byte" )
        return TWO
    found, walked = ts_counts.census( str( repo ), read=read )
    assert found == { "src/a.ts": 1, "src/b.ts": 2 } and walked == 2


def test_census_over_an_empty_tree_reports_zero_walked( repo, monkeypatch ):
    monkeypatch.setattr( tsdoc_lint, "run_extractor", lambda *a, **k: pytest.fail( "no process for no files" ) )
    assert ts_counts.census( str( repo ) ) == ( {}, 0 )


def test_the_disk_census_reads_the_working_tree_text_and_drops_a_byte_order_mark( repo, extractor ):
    _track( repo, { "src/a.ts": ONE } )
    ( repo / "src/b.ts" ).write_bytes( b"\xef\xbb\xbf" + TWO.encode( "utf-8" ) )
    _git( repo, "add", "-f", "src/b.ts" )
    assert ts_counts.census( str( repo ) ) == ( { "src/a.ts": 1, "src/b.ts": 2 }, 2 )


# ---- the command line ----------------------------------------------------------------------

def _run( repo, *flags ):
    out = io.StringIO()
    rc  = ts_counts.main( [ *flags, "--repo-root", str( repo ) ], out )
    return rc, out.getvalue()


def test_write_then_check_is_exact_and_prints_the_denominator( repo, extractor ):
    _track( repo, { "src/a.ts": TWO, "src/b.ts": CLEAN } )
    rc, text = _run( repo, "--write" )
    assert rc == ts_counts.EXIT_TIGHT and "wrote 1 entries from 2 counted files" in text
    assert json.loads( ( repo / ts_counts.TABLE_PATH ).read_text() )[ "files" ] == { "src/a.ts": 2 }
    rc, text = _run( repo, "--check" )
    assert rc == ts_counts.EXIT_TIGHT and "2 counted files walked, 0 problems" in text


def test_check_reports_a_file_that_rose_and_one_that_fell( repo, extractor ):
    _track( repo, { "src/a.ts": ONE, "src/b.ts": TWO } )
    _run( repo, "--write" )
    _track( repo, { "src/a.ts": TWO, "src/b.ts": ONE } )
    rc, text = _run( repo, "--check" )
    assert rc == ts_counts.EXIT_MISMATCH and "src/a.ts: table 1, census 2" in text and "src/b.ts: table 2, census 1" in text


def test_check_is_not_checked_when_the_table_is_missing_or_malformed_or_the_tree_is_not_git( repo, tmp_path_factory, extractor ):
    rc, text = _run( repo, "--check" )
    assert rc == ts_counts.EXIT_NOT_CHECKED and "not checked" in text
    ( repo / ts_counts.TABLE_PATH ).write_text( "not json", encoding="utf-8" )
    rc, text = _run( repo, "--check" )
    assert rc == ts_counts.EXIT_NOT_CHECKED and "TableError" in text
    rc, text = _run( tmp_path_factory.mktemp( "nogit" ), "--check" )
    assert rc == ts_counts.EXIT_NOT_CHECKED


def test_the_command_line_needs_exactly_one_mode( repo, capsys ):
    with pytest.raises( SystemExit ):
        ts_counts.main( [ "--repo-root", str( repo ) ] )
    capsys.readouterr()


# ---- the real extractor --------------------------------------------------------------------

@pytest.mark.skipif( shutil.which( "node" ) is None, reason="node is not installed" )
def test_the_real_extractor_counts_the_staged_text_in_a_scratch_tree( repo, monkeypatch ):
    monkeypatch.setattr( tsdoc_lint, "EXTRACTOR_REL", os.path.join( cu.get_project_root(), "src/scripts/ts_doc_extract.mjs" ) )
    texts = { "src/a.ts": "/**\n * This is NOT fine.\n */\nexport const x = 1;\n", "src/b.ts": "/** Return the thing. */\nexport const y = 1;\n" }
    got = ts_counts.counts_for( str( repo ), texts )
    assert { p: r.count for p, r in got.items() } == { "src/a.ts": 1, "src/b.ts": 0 }
