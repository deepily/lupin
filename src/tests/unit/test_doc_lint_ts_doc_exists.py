"""
Unit tests for doc_lint.ts_doc_exists, the existence check for exported-symbol docs.

The Node extractor is replaced by a stand-in that returns prepared records, so most tests need no Node.
The last tests run the real extractor and are skipped when Node is not installed.
"""

import io
import json
import shutil
import subprocess

import pytest

from cosa.repo.doc_lint import counts, ts_counts, ts_doc_exists, tsdoc_lint

REPO_ROOT = subprocess.run( [ "git", "rev-parse", "--show-toplevel" ], capture_output=True, text=True ).stdout.strip()


def _git( root, *args ):
    res = subprocess.run( [ "git", "-C", str( root ), "-c", "user.email=t@t", "-c", "user.name=t", *args ], capture_output=True, text=True )
    assert res.returncode == 0, res.stderr
    return res.stdout


def sym( name, documented, kind="function", line=1 ):
    return { "name": name, "kind": kind, "line": line, "documented": documented }


def rec( path, symbols, reexports=0, errors=None ):
    return { "kind": "exports", "file": path, "parse_errors": errors or [], "reexports": reexports, "symbols": symbols }


@pytest.fixture
def repo( tmp_path ):
    _git( tmp_path, "init", "-q" )
    for rel in ts_doc_exists.STAMP_FILES:
        full = tmp_path / rel
        full.parent.mkdir( parents=True, exist_ok=True )
        full.write_text( f"stamp file {rel}\n", encoding="utf-8" )
    ( tmp_path / "src" / "conf" ).mkdir( parents=True, exist_ok=True )
    ( tmp_path / "a.ts" ).write_text( "x\n", encoding="utf-8" )
    ( tmp_path / "b.js" ).write_text( "x\n", encoding="utf-8" )
    ( tmp_path / "c.py" ).write_text( "x\n", encoding="utf-8" )
    _git( tmp_path, "add", "a.ts", "b.js", "c.py" )
    _git( tmp_path, "commit", "-q", "-m", "seed" )
    return tmp_path


def fake_run( by_file ):
    def run( root, files, source_root=None ): return { f: by_file[ f ] for f in files }
    return run


# ---- table and stamp -----------------------------------------------------------------------

def test_the_table_is_its_own_file_beside_the_two_other_tables():
    assert ts_doc_exists.TABLE_PATH == "src/conf/doc-lint-ts-exports-counts.json"
    assert len( { ts_doc_exists.TABLE_PATH, ts_counts.TABLE_PATH, counts.TABLE_PATH } ) == 3


def test_the_stamp_files_name_this_module_and_both_extractors_and_the_scope_decision():
    assert set( ts_doc_exists.STAMP_FILES ) == {
        "src/cosa/repo/doc_lint/ts_doc_exists.py", "src/cosa/repo/doc_lint/tsdoc_lint.py",
        "src/scripts/ts_export_extract.mjs", "src/scripts/ts_doc_extract.mjs" }


def test_rules_stamp_moves_with_each_stamp_file( repo ):
    seen = { ts_doc_exists.rules_stamp( str( repo ) ) }
    for rel in ts_doc_exists.STAMP_FILES:
        ( repo / rel ).write_text( "changed\n", encoding="utf-8" )
        stamp = ts_doc_exists.rules_stamp( str( repo ) )
        assert stamp not in seen
        seen.add( stamp )


def test_the_export_extractor_is_a_rule_file_so_an_unstaged_edit_to_it_is_a_divergence():
    assert "src/scripts/ts_export_extract.mjs" in counts.RULE_PATHS


# ---- scope ---------------------------------------------------------------------------------

def test_counted_paths_are_the_scope_the_wording_linter_reads( repo ):
    assert ts_doc_exists.counted_paths( str( repo ) ) == tsdoc_lint.tracked_files( str( repo ) ) == [ "a.ts", "b.js" ]


def test_counted_paths_leave_out_rnd_and_the_flutter_bundle_but_the_wording_linter_still_reads_them( repo ):
    kept = [ "src/lupin_app/static/js/ok.js", "src/rndx/ok.js" ]
    gone = [ "src/rnd/v1/probe.js", "src/cosa/rnd/note.ts", "src/lupin_app/static/lupin-mobile-test/flutter.js" ]
    for rel in kept + gone:
        ( repo / rel ).parent.mkdir( parents=True, exist_ok=True )
        ( repo / rel ).write_text( "x\n", encoding="utf-8" )
    _git( repo, "add", *kept, *gone )
    assert set( gone ) <= set( tsdoc_lint.tracked_files( str( repo ) ) )
    assert ts_doc_exists.counted_paths( str( repo ) ) == sorted( [ "a.ts", "b.js", *kept ] )


# ---- reading one record --------------------------------------------------------------------

def test_missing_keeps_only_the_undocumented_symbols_in_order():
    record = rec( "a.ts", [ sym( "a", True ), sym( "b", False, line=4 ), sym( "c", False, line=9 ) ] )
    assert [ s[ "name" ] for s in ts_doc_exists.missing( record ) ] == [ "b", "c" ]


def test_missing_is_empty_for_a_file_with_no_exports():
    assert ts_doc_exists.missing( rec( "a.ts", [] ) ) == []


# ---- census --------------------------------------------------------------------------------

def test_census_counts_per_file_and_totals( repo ):
    run    = fake_run( { "a.ts": rec( "a.ts", [ sym( "a", False ), sym( "b", True ), sym( "c", False ) ], reexports=2 ),
                         "b.js": rec( "b.js", [ sym( "d", True ) ] ) } )
    result = ts_doc_exists.census( str( repo ), run=run )
    assert result.found == { "a.ts": 2 }
    assert ( result.walked, result.symbols, result.undocumented, result.reexports, result.unparsed ) == ( 2, 4, 2, 2, 0 )
    assert [ s[ "name" ] for s in result.missing[ "a.ts" ] ] == [ "a", "c" ]


def test_census_counts_a_file_that_did_not_parse_and_still_reads_its_symbols( repo ):
    run    = fake_run( { "a.ts": rec( "a.ts", [ sym( "a", False ) ], errors=[ { "line": 1, "message": "broken" } ] ), "b.js": rec( "b.js", [] ) } )
    result = ts_doc_exists.census( str( repo ), run=run )
    assert result.unparsed == 1 and result.found == { "a.ts": 1 }


def test_census_over_an_empty_tree_says_so( tmp_path ):
    _git( tmp_path, "init", "-q" )
    result = ts_doc_exists.census( str( tmp_path ), run=fake_run( {} ) )
    assert ( result.walked, result.found ) == ( 0, {} )


# ---- the ratchet ---------------------------------------------------------------------------

def test_raises_lists_a_file_whose_count_rose_and_a_new_file_and_not_a_fall():
    table = { "a.ts": 3, "b.ts": 2, "c.ts": 1 }
    found = { "a.ts": 4, "b.ts": 1, "d.ts": 2 }
    assert ts_doc_exists.raises( table, found ) == [ ( "a.ts", 3, 4 ), ( "d.ts", 0, 2 ) ]


def test_raises_is_empty_when_nothing_rose():
    assert ts_doc_exists.raises( { "a.ts": 3 }, { "a.ts": 3 } ) == []


# ---- reporting -----------------------------------------------------------------------------

def test_report_lists_each_symbol_then_a_count_table_largest_first_then_totals( repo ):
    run    = fake_run( { "a.ts": rec( "a.ts", [ sym( "f", False, line=7 ) ] ),
                         "b.js": rec( "b.js", [ sym( "g", False, "variable", 2 ), sym( "h", False, "class", 5 ) ] ) } )
    result = ts_doc_exists.census( str( repo ), run=run )
    lines  = ts_doc_exists.report( result ).split( "\n" )
    assert lines[ : 3 ] == [ "a.ts:7: function f", "b.js:2: variable g", "b.js:5: class h" ]
    assert lines[ 3 : 7 ] == [ "", "count  file", "     2  b.js", "     1  a.ts" ]
    assert lines[ -2 ] == "3 of 3 exported symbols have no doc comment, in 2 of 2 files"


def test_report_mentions_unparsed_files_and_reexports_when_there_are_some( repo ):
    run    = fake_run( { "a.ts": rec( "a.ts", [], reexports=4, errors=[ { "line": 1, "message": "x" } ] ), "b.js": rec( "b.js", [] ) } )
    text   = ts_doc_exists.report( ts_doc_exists.census( str( repo ), run=run ) )
    assert "re-exports not counted: 4" in text and "files that did not parse: 1" in text


def test_report_leaves_out_those_lines_when_there_are_none( repo ):
    run  = fake_run( { "a.ts": rec( "a.ts", [] ), "b.js": rec( "b.js", [] ) } )
    text = ts_doc_exists.report( ts_doc_exists.census( str( repo ), run=run ) )
    assert "re-exports" not in text and "did not parse" not in text


# ---- run_extractor -------------------------------------------------------------------------

class Done:
    def __init__( self, code=0, out="", err="" ): self.returncode, self.stdout, self.stderr = code, out, err


def test_run_extractor_batches_files_and_groups_records( monkeypatch ):
    calls = []
    def fake( cmd, **kw ):
        calls.append( cmd )
        files = [ c for c in cmd[ 4 : ] ]
        return Done( out="".join( json.dumps( rec( f, [] ) ) + "\n" for f in files ) + "\n" )
    monkeypatch.setattr( ts_doc_exists, "CHUNK_SIZE", 2 )
    monkeypatch.setattr( ts_doc_exists.subprocess, "run", fake )
    out = ts_doc_exists.run_extractor( "/r", [ "a.ts", "b.ts", "c.ts" ], source_root="/s" )
    assert sorted( out ) == [ "a.ts", "b.ts", "c.ts" ] and len( calls ) == 2
    assert calls[ 0 ][ 0 ] == "node" and calls[ 0 ][ 1 ].endswith( "src/scripts/ts_export_extract.mjs" ) and calls[ 0 ][ 3 ] == "/s"


def test_run_extractor_reads_the_repo_root_when_no_source_root_is_given( monkeypatch ):
    seen = []
    def fake( cmd, **kw ):
        seen.append( cmd[ 3 ] )
        return Done( out=json.dumps( rec( "a.ts", [] ) ) + "\n" )
    monkeypatch.setattr( ts_doc_exists.subprocess, "run", fake )
    ts_doc_exists.run_extractor( "/r", [ "a.ts" ] )
    assert seen == [ "/r" ]


def test_run_extractor_starts_nothing_for_no_files( monkeypatch ):
    monkeypatch.setattr( ts_doc_exists.subprocess, "run", lambda *a, **k: pytest.fail( "started" ) )
    assert ts_doc_exists.run_extractor( "/r", [] ) == {}


def test_run_extractor_refuses_when_node_cannot_start( monkeypatch ):
    def boom( *a, **k ): raise OSError( "no node" )
    monkeypatch.setattr( ts_doc_exists.subprocess, "run", boom )
    with pytest.raises( RuntimeError, match="cannot run node" ): ts_doc_exists.run_extractor( "/r", [ "a.ts" ] )


def test_run_extractor_refuses_on_a_nonzero_exit( monkeypatch ):
    monkeypatch.setattr( ts_doc_exists.subprocess, "run", lambda *a, **k: Done( code=1, err="bad" ) )
    with pytest.raises( RuntimeError, match="export extractor failed: bad" ): ts_doc_exists.run_extractor( "/r", [ "a.ts" ] )


def test_run_extractor_refuses_a_line_that_is_not_json( monkeypatch ):
    monkeypatch.setattr( ts_doc_exists.subprocess, "run", lambda *a, **k: Done( out="not json\n" ) )
    with pytest.raises( RuntimeError, match="not JSON" ): ts_doc_exists.run_extractor( "/r", [ "a.ts" ] )


def test_run_extractor_refuses_when_a_file_comes_back_without_a_record( monkeypatch ):
    monkeypatch.setattr( ts_doc_exists.subprocess, "run", lambda *a, **k: Done( out=json.dumps( rec( "a.ts", [] ) ) + "\n" ) )
    with pytest.raises( RuntimeError, match="NOT checked: b.ts" ): ts_doc_exists.run_extractor( "/r", [ "a.ts", "b.ts" ] )


# ---- command line --------------------------------------------------------------------------

def _main( repo, monkeypatch, by_file, *argv ):
    monkeypatch.setattr( ts_doc_exists, "run_extractor", lambda root, files, source_root=None: { f: by_file[ f ] for f in files } )
    out  = io.StringIO()
    code = ts_doc_exists.main( [ "--repo-root", str( repo ), *argv ], out )
    return code, out.getvalue()


def test_write_then_check_is_tight_and_a_new_undocumented_export_breaks_it( repo, monkeypatch ):
    by_file = { "a.ts": rec( "a.ts", [ sym( "a", False ) ] ), "b.js": rec( "b.js", [ sym( "b", True ) ] ) }
    code, text = _main( repo, monkeypatch, by_file, "--write" )
    assert code == 0 and "wrote 1 entries from 2 counted files" in text
    table = counts.parse_table( ( repo / ts_doc_exists.TABLE_PATH ).read_text( encoding="utf-8" ) )
    assert table.files == { "a.ts": 1 }
    code, text = _main( repo, monkeypatch, by_file, "--check" )
    assert code == 0 and "2 counted files walked, 0 problems" in text
    by_file[ "b.js" ] = rec( "b.js", [ sym( "b", False ) ] )
    code, text = _main( repo, monkeypatch, by_file, "--check" )
    assert code == 1 and "b.js: table 0, census 1" in text


def test_check_reports_a_table_that_cannot_be_read_as_not_checked( repo, monkeypatch ):
    code, text = _main( repo, monkeypatch, { "a.ts": rec( "a.ts", [] ), "b.js": rec( "b.js", [] ) }, "--check" )
    assert code == 2 and text.startswith( "not checked: " )


def test_check_reports_an_extractor_failure_as_not_checked( repo, monkeypatch ):
    def boom( root, files, source_root=None ): raise RuntimeError( "extractor failed" )
    monkeypatch.setattr( ts_doc_exists, "run_extractor", boom )
    out = io.StringIO()
    assert ts_doc_exists.main( [ "--repo-root", str( repo ), "--list" ], out ) == 2 and "not checked: RuntimeError: extractor failed" in out.getvalue()


def test_list_prints_the_report_and_exits_zero( repo, monkeypatch ):
    code, text = _main( repo, monkeypatch, { "a.ts": rec( "a.ts", [ sym( "a", False, line=3 ) ] ), "b.js": rec( "b.js", [] ) }, "--list" )
    assert code == 0 and text.startswith( "a.ts:3: function a" )


def test_a_mode_is_required( repo ):
    with pytest.raises( SystemExit ): ts_doc_exists.main( [ "--repo-root", str( repo ) ], io.StringIO() )


def test_main_reads_sys_argv_and_stdout_when_given_nothing( repo, monkeypatch, capsys ):
    monkeypatch.setattr( ts_doc_exists, "run_extractor", lambda root, files, source_root=None: { f: rec( f, [] ) for f in files } )
    monkeypatch.setattr( ts_doc_exists.sys, "argv", [ "x", "--repo-root", str( repo ), "--list" ] )
    assert ts_doc_exists.main() == 0 and "0 of 0 exported symbols" in capsys.readouterr().out


# ---- the real extractor --------------------------------------------------------------------

SOURCE = """\
/** Documented function. */
export function documented() {}

export function bare() {}

/** Overload set doc. */
export function over( a: string ): void;
export function over( a: number ): void;
export function over( a: any ) {}

export const x = 1, y = 2;

/** Pair doc. */
export const { p, q } = obj;

/**/
export class Empty {}

/** */
export interface Blank {}

// @ts-ignore
/** Directive then doc. */
export type T = string;

/** Local doc. */
function local() {}
export { local, bare as renamed };
import { Imported } from "./m";
export { Imported };
export { z } from "./z";
export * from "./all";
export default 5;
"""


@pytest.mark.skipif( shutil.which( "node" ) is None, reason="node is not installed" )
def test_the_real_extractor_reads_every_export_form_and_pairs_the_blocks_above_them( tmp_path ):
    ( tmp_path / "s.ts" ).write_text( SOURCE, encoding="utf-8" )
    got  = ts_doc_exists.run_extractor( REPO_ROOT, [ "s.ts" ], source_root=str( tmp_path ) )[ "s.ts" ]
    seen = { ( s[ "kind" ], s[ "name" ] ): s[ "documented" ] for s in got[ "symbols" ] }
    assert seen == {
        ( "function", "documented" ): True, ( "function", "bare" ): False, ( "function", "over" ): True,
        ( "variable", "x" ): False, ( "variable", "y" ): False, ( "variable", "p" ): True, ( "variable", "q" ): True,
        ( "class", "Empty" ): False, ( "interface", "Blank" ): False, ( "type", "T" ): True,
        ( "list", "local" ): True, ( "list", "renamed" ): False, ( "assignment", "default" ): False }
    assert got[ "reexports" ] == 3 and got[ "parse_errors" ] == []


@pytest.mark.skipif( shutil.which( "node" ) is None, reason="node is not installed" )
def test_the_real_census_runs_over_this_repository_and_reads_every_file( ):
    result = ts_doc_exists.census( REPO_ROOT )
    assert result.walked == len( ts_doc_exists.counted_paths( REPO_ROOT ) ) > 100 and result.symbols >= result.undocumented > 0
    assert set( result.found ) == set( result.missing )
