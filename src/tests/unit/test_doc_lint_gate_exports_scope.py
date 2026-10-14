"""
The commit gate's third counted scope: exported script symbols with no doc comment.

The Node extractor is replaced by a stand-in that reads the scratch text, so no Node is needed.
Each test builds a scratch repository, stages files and runs gate.main, as the wording scopes' tests do.
"""

import io
import subprocess

import pytest

from cosa.repo.doc_lint import counts, gate, ts_counts, ts_doc_exists, word_list

NAME  = "exported-symbol doc"
TABLE = ts_doc_exists.TABLE_PATH

DOCUMENTED = "/** Return the thing. */\nexport const alpha = 1;\n"
ONE_GAP    = "export const alpha = 1;\n"
TWO_GAPS   = "export const alpha = 1;\nexport const beta = 2;\n"
MIXED      = "/** Return the thing. */\nexport const alpha = 1;\nexport const beta = 2;\n"


def _git( root, *args ):
    res = subprocess.run( [ "git", "-C", str( root ), "-c", "user.email=t@t", "-c", "user.name=t", *args ], capture_output=True, text=True )
    assert res.returncode == 0, res.stderr
    return res.stdout


def _stage( root, files ):
    for rel, text in files.items():
        full = root / rel
        full.parent.mkdir( parents=True, exist_ok=True )
        full.write_text( text, encoding="utf-8" )
    _git( root, "add", "-f", *files )


def _gate( root, *extra ):
    err = io.StringIO()
    return gate.main( [ "--repo-root", str( root ), *extra ], err ), err.getvalue()


def _fake_run( root, files, source_root=None ):
    """Stand in for the export extractor: a block comment above an export documents it."""
    _fake_run.seen.append( list( files ) )
    out = {}
    for path in files:
        with open( f"{source_root if source_root is not None else root}/{path}", encoding="utf-8" ) as handle: lines = handle.read().split( "\n" )
        symbols = []
        for i, line in enumerate( lines ):
            if line.startswith( "export const " ):
                symbols.append( { "name": line.split()[ 2 ], "kind": "const", "line": i + 1, "documented": i > 0 and lines[ i - 1 ].strip().endswith( "*/" ) } )
        out[ path ] = { "kind": "exports", "file": path, "parse_errors": [], "reexports": 0, "symbols": symbols }
    return out


_fake_run.seen = []


@pytest.fixture
def repo( tmp_path, monkeypatch ):
    _git( tmp_path, "init", "-q" )
    ( tmp_path / "src" / "conf" ).mkdir( parents=True )
    ( tmp_path / "src" / "conf" / "dm-tutor-lowercase-words.txt" ).write_text( "not\n", encoding="utf-8" )
    for rel in set( counts.STAMP_FILES ) | set( ts_counts.STAMP_FILES ) | set( ts_doc_exists.STAMP_FILES ):
        full = tmp_path / rel
        if not full.exists():
            full.parent.mkdir( parents=True, exist_ok=True )
            full.write_text( f"stamp file {rel}\n", encoding="utf-8" )
    _fake_run.seen.clear()
    monkeypatch.setattr( ts_doc_exists, "run_extractor", _fake_run )
    monkeypatch.setattr( ts_counts, "extract", lambda root, texts: { p: [ { "kind": "file", "file": p, "ts_version": "5.9.3", "parse_errors": [] } ] for p in texts } )
    monkeypatch.setattr( gate, "run_ruff", lambda root, paths, sources=None: ( [], [] ) )
    monkeypatch.setattr( gate, "run_markdownlint", lambda root, paths, sources=None: ( [], [] ) )
    monkeypatch.setattr( gate, "markdownlint_unnamed", lambda root, paths: [], raising=False )
    yield tmp_path
    word_list._state[ "root" ] = None
    word_list._state[ "words" ] = None


def _table( root, files, stamp=None ):
    text = counts.table_text( files, stamp if stamp is not None else ts_doc_exists.rules_stamp( str( root ) ) )
    ( root / TABLE ).parent.mkdir( parents=True, exist_ok=True )
    ( root / TABLE ).write_text( text, encoding="utf-8" )
    _git( root, "add", "-f", TABLE )


def _base( root, files, table, stamp=None ):
    _stage( root, files )
    _table( root, table, stamp )
    _git( root, "commit", "-q", "--no-verify", "-m", "base" )


def test_the_exports_scope_names_its_table_and_its_own_advice():
    assert gate.EXPORTS_SCOPE.table_path == ts_doc_exists.TABLE_PATH
    assert gate.EXPORTS_SCOPE.noun == f"{NAME} "
    assert "doc comment" in gate.EXPORTS_SCOPE.advice and "waive" not in gate.EXPORTS_SCOPE.advice
    assert gate.PYTHON_SCOPE.advice is None and gate.TS_SCOPE.advice is None


def test_a_new_undocumented_export_is_refused_and_the_refusal_says_add_a_doc_comment( repo ):
    _base( repo, { "src/a.ts": DOCUMENTED }, {} )
    _stage( repo, { "src/a.ts": MIXED } )
    rc, text = _gate( repo )
    assert rc == 3
    assert "REFUSED src/a.ts: 1 findings, the count table allows 0 (+1); add a doc comment to each exported symbol listed below" in text
    assert "waive" not in "\n".join( ln for ln in text.split( "\n" ) if "REFUSED src/a.ts" in ln )
    assert "[doc-lint]   src/a.ts:3: undocumented-export: exported const beta has no doc comment" in text
    assert f"{NAME} counted scope: 1 files checked, 0 at or below their count, 1 over, 0 waivers honoured, table ok" in text


def test_a_file_at_or_below_its_entry_is_allowed_and_counted_in_the_denominator( repo ):
    _base( repo, { "src/a.ts": TWO_GAPS }, { "src/a.ts": 2 } )
    _stage( repo, { "src/a.ts": ONE_GAP } )
    rc, text = _gate( repo )
    assert rc == 0 and "REFUSED" not in text
    assert f"{NAME} counted scope: 1 files checked, 1 at or below their count, 0 over, 0 waivers honoured, table ok" in text


def test_a_new_file_starts_at_zero_so_a_documented_one_passes_and_an_undocumented_one_does_not( repo ):
    _base( repo, { "src/keep.ts": DOCUMENTED }, {} )
    _stage( repo, { "src/new.js": ONE_GAP } )
    rc, text = _gate( repo )
    assert rc == 3 and "REFUSED src/new.js: 1 findings, the count table allows 0 (+1)" in text
    _git( repo, "reset", "-q", "--hard" )
    _stage( repo, { "src/new.js": DOCUMENTED } )
    rc, text = _gate( repo )
    assert rc == 0 and "1 files checked, 1 at or below their count" in text


def test_a_commit_that_stages_no_script_file_runs_no_export_extractor_and_still_prints_the_denominator( repo ):
    _base( repo, { "src/a.ts": ONE_GAP }, { "src/a.ts": 1 } )
    _fake_run.seen.clear()
    _stage( repo, { "notes.md": "x\n" } )
    rc, text = _gate( repo )
    assert rc == 0 and _fake_run.seen == []
    assert f"{NAME} counted scope: 0 files checked, 0 at or below their count, 0 over, 0 waivers honoured, table ok" in text


def test_the_extractor_reads_the_staged_text_not_the_disk_copy( repo ):
    _base( repo, { "src/a.ts": ONE_GAP }, { "src/a.ts": 1 } )
    _stage( repo, { "src/a.ts": DOCUMENTED } )
    ( repo / "src/a.ts" ).write_text( TWO_GAPS, encoding="utf-8" )
    rc, text = _gate( repo )
    assert rc == 0 and "REFUSED" not in text and "1 at or below their count" in text


def test_a_file_under_an_excluded_folder_is_not_counted_even_though_the_wording_scope_reads_it( repo ):
    _base( repo, { "src/keep.ts": DOCUMENTED }, {} )
    _stage( repo, { "src/rnd/probe.ts": ONE_GAP } )
    rc, text = _gate( repo )
    assert rc == 0 and f"{NAME} counted scope: 0 files checked" in text


def test_no_table_at_head_or_staged_warns_that_the_scope_was_not_checked( repo ):
    _stage( repo, { "src/a.ts": ONE_GAP } )
    rc, text = _gate( repo )
    assert rc == 0 and "REFUSED" not in text
    assert f"WARNING: there is no {NAME} count table at HEAD or staged, so the {NAME} counted scope was NOT checked" in text
    assert f"{NAME} counted scope: 0 files checked, 0 at or below their count, 0 over, 0 waivers honoured, table absent" in text


def test_a_table_cut_under_other_rules_refuses_a_staged_script_file_and_names_the_command( repo ):
    _base( repo, { "src/keep.ts": DOCUMENTED }, {}, stamp="oldstamp" )
    _stage( repo, { "src/a.ts": DOCUMENTED } )
    rc, text = _gate( repo )
    assert rc == 3 and f"REFUSED: the {NAME} count table was cut under other rules (stamp oldstamp, now " in text
    assert "python3 -m cosa.repo.doc_lint.ts_doc_exists --repo-root \"$PWD\" --write" in text


def test_a_staged_table_that_raises_an_entry_is_refused( repo ):
    _base( repo, { "src/a.ts": ONE_GAP }, { "src/a.ts": 1 } )
    _table( repo, { "src/a.ts": 2 } )
    rc, text = _gate( repo )
    assert rc == 3 and f"REFUSED {TABLE}: src/a.ts raised from 1 to 2; the table may only fall" in text


def test_a_regenerated_table_must_equal_a_census_of_the_staged_tree( repo ):
    _base( repo, { "src/a.ts": ONE_GAP }, { "src/a.ts": 1 }, stamp="oldstamp" )
    _stage( repo, { "src/a.ts": TWO_GAPS } )
    _table( repo, { "src/a.ts": 2 } )
    rc, text = _gate( repo )
    assert rc == 0 and "table regenerated" in text
    _table( repo, { "src/a.ts": 5 } )
    rc, text = _gate( repo )
    assert rc == 3 and "[doc-lint]   src/a.ts: table 5, census 2" in text and "table stale" in text


def test_a_rule_file_that_differs_between_index_and_disk_marks_the_exports_scope_diverged( repo ):
    rule = "src/scripts/ts_export_extract.mjs"
    _git( repo, "add", "-f", rule )
    _git( repo, "commit", "-q", "--no-verify", "-m", "rules" )
    ( repo / rule ).write_text( "weakened\n", encoding="utf-8" )
    _stage( repo, { "src/a.ts": DOCUMENTED } )
    rc, text = _gate( repo )
    assert rc == 3 and f"{NAME} counted scope: 0 files checked, 0 at or below their count, 0 over, 0 waivers honoured, table diverged" in text


def test_a_staged_exports_table_alone_is_judged_so_the_divergence_check_applies_to_it( repo ):
    rule = "src/scripts/ts_export_extract.mjs"
    _git( repo, "add", "-f", rule )
    _git( repo, "commit", "-q", "--no-verify", "-m", "rules" )
    ( repo / rule ).write_text( "weakened\n", encoding="utf-8" )
    _table( repo, {} )
    rc, text = _gate( repo )
    assert rc == 3 and f"rule file {rule} is not the same staged and in the working tree" in text


def test_staged_exports_counted_lists_scope_files_less_excluded_folders_and_the_table_flag( repo ):
    _stage( repo, { "src/a.ts": ONE_GAP, "src/b.js": ONE_GAP, "src/c.py": "x\n", "src/rnd/d.ts": ONE_GAP, TABLE: counts.table_text( {}, "s" ) } )
    paths, renamed, table_staged = gate.staged_exports_counted( str( repo ) )
    assert paths == [ "src/a.ts", "src/b.js" ] and renamed == {} and table_staged is True


def test_counts_for_gives_one_finding_per_undocumented_export_with_its_line( repo ):
    got = ts_doc_exists.counts_for( str( repo ), { "src/a.ts": MIXED, "src/b.ts": DOCUMENTED } )
    assert got[ "src/b.ts" ] == counts.FileCount( 0, [], 0 )
    assert got[ "src/a.ts" ].count == 1
    finding = got[ "src/a.ts" ].findings[ 0 ]
    assert ( finding.path, finding.line, finding.rule ) == ( "src/a.ts", 3, "undocumented-export" )
    assert finding.message == "exported const beta has no doc comment"


def test_counts_for_counts_a_file_the_compiler_could_not_parse_as_one_more_finding( repo, monkeypatch ):
    def broken( root, files, source_root=None ):
        return { f: { "kind": "exports", "file": f, "parse_errors": [ "x" ], "reexports": 0, "symbols": [] } for f in files }
    monkeypatch.setattr( ts_doc_exists, "run_extractor", broken )
    got = ts_doc_exists.counts_for( str( repo ), { "src/a.ts": "export const (\n" } )
    assert got[ "src/a.ts" ].count == 1 and got[ "src/a.ts" ].findings[ 0 ].rule == "parse-error"


def test_counts_for_starts_no_process_for_no_texts( repo ):
    assert ts_doc_exists.counts_for( str( repo ), {} ) == {}
    assert _fake_run.seen == []


def test_census_of_texts_counts_each_counted_file_and_a_non_utf8_file_as_one( repo ):
    _stage( repo, { "src/a.ts": TWO_GAPS, "src/b.ts": DOCUMENTED, "src/rnd/c.ts": ONE_GAP } )
    _git( repo, "commit", "-q", "--no-verify", "-m", "files" )
    def read( path ):
        if path == "src/b.ts": raise UnicodeDecodeError( "utf-8", b"\xe9", 0, 1, "invalid" )
        return ( repo / path ).read_text( encoding="utf-8" )
    found, walked = ts_doc_exists.census_of_texts( str( repo ), read )
    assert walked == 2 and found == { "src/a.ts": 2, "src/b.ts": 1 }
