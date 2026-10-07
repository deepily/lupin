"""
The TypeScript and JavaScript doc linter: scope, masking, rules per comment kind, the extractor
seam and the command line.

No test starts Node. The extractor's output is hand-written JSON records, or a fixture file under
src/tests/fixtures/ts_doc_lint/ loaded by glob; the one subprocess call is monkeypatched.

To swap in a real capture: print the extractor's JSON Lines for a few client files into a new
src/tests/fixtures/ts_doc_lint/<name>.jsonl. test_every_fixture_file_lints_without_error checks
invariants on it. Add <name>.expected.json ( { file: [ [ line, rule ], ... ] } ) to pin the findings.
"""

import glob
import io
import json
import os
import runpy
import subprocess
import sys
import types
import warnings

import pytest

import cosa.utils.util as cu
from cosa.repo.doc_lint import docstring_lint, tsdoc_lint, word_list

WORDS    = frozenset( { "not", "never", "only", "the", "none", "bounded", "red", "before" } )
FIXTURES = os.path.join( cu.get_project_root(), "src", "tests", "fixtures", "ts_doc_lint" )


@pytest.fixture( autouse=True )
def _small_word_list( tmp_path_factory ):
    root = tmp_path_factory.mktemp( "wordroot" )
    ( root / "src" / "conf" ).mkdir( parents=True )
    ( root / "src" / "conf" / "dm-tutor-lowercase-words.txt" ).write_text( "\n".join( sorted( WORDS ) ) + "\n", encoding="utf-8" )
    word_list.configure_root( root )
    yield
    word_list._state[ "root" ]  = None
    word_list._state[ "words" ] = None


def _git( root, *args ):
    res = subprocess.run( [ "git", "-C", str( root ), "-c", "user.email=t@t", "-c", "user.name=t", *args ], capture_output=True, text=True )
    assert res.returncode == 0, res.stderr
    return res.stdout


@pytest.fixture
def repo( tmp_path ):
    _git( tmp_path, "init", "-q" )
    ( tmp_path / "src" / "conf" ).mkdir( parents=True )
    ( tmp_path / "src" / "conf" / "dm-tutor-lowercase-words.txt" ).write_text( "\n".join( sorted( WORDS ) ) + "\n", encoding="utf-8" )
    return tmp_path


def _commit( root, files ):
    for rel, text in files.items():
        full = root / rel
        full.parent.mkdir( parents=True, exist_ok=True )
        full.write_text( text, encoding="utf-8" )
    _git( root, "add", "-A" )
    _git( root, "commit", "-q", "-m", "c" )


def _comment( text, kind="jsdoc", start=10, **over ):
    record = {
        "kind": kind, "file": "a.ts", "text": text, "start_line": start, "end_line": start + text.count( "\n" ),
        "symbol_key": None, "directive": False, "tags": [], "ts_version": "5.9.3", "commented_code": False
    }
    record.update( over )
    return record


def _file_record( errors=() ):
    return { "kind": "file", "file": "a.ts", "ts_version": "5.9.3", "parse_errors": list( errors ) }


def _hits( comments, **kwargs ):
    return [ ( f.line, f.rule ) for f in tsdoc_lint.lint_comments( "a.ts", comments, **kwargs ) ]


def _rules( comments ):
    return { rule for _, rule in _hits( comments ) }


# ---- scope -----------------------------------------------------------------------------------

@pytest.mark.parametrize( "path", [
    "src/a.ts", "src/lupin_app/static/js/x.js", "src/tests/unit/t/foo.test.ts", "tools/run.mjs",
    "src/lupin_app/static/js/vendor/other.js", "src/lupin_app/static/js/x.d.ts", "src/x/app.min.js"
] )
def test_in_scope_keeps_authored_files_and_test_files( path ):
    assert tsdoc_lint.in_scope( path ) is True


@pytest.mark.parametrize( "path", [
    "src/a.py", "node_modules/x/y.js", "a/.venv/b.ts", "src/lupin_app/static/dist/m.js",
    "src/lupin_app/static/js/vendor/marked.min.js", "README.md"
] )
def test_in_scope_drops_other_suffixes_vendored_trees_and_minified_vendor_files( path ):
    assert tsdoc_lint.in_scope( path ) is False


def test_tracked_files_comes_from_git_and_keeps_test_files( repo, tmp_path_factory ):
    _commit( repo, {
        "src/a.ts": "", "src/tests/unit/b.test.ts": "", "src/x/c.py": "", "src/js/vendor/m.min.js": "",
        "node_modules/z/q.js": "", "src/d.mjs": ""
    } )
    ( repo / "src" / "untracked.ts" ).write_text( "", encoding="utf-8" )
    assert tsdoc_lint.tracked_files( repo ) == [ "src/a.ts", "src/d.mjs", "src/tests/unit/b.test.ts" ]
    with pytest.raises( RuntimeError, match="git ls-files failed" ):
        tsdoc_lint.tracked_files( tmp_path_factory.mktemp( "notrepo" ) )


# ---- masking ---------------------------------------------------------------------------------

def test_mask_blanks_tag_word_balanced_type_and_name_and_keeps_length():
    line   = "@param {Map<string, {a: NONE}>} items - The items."
    masked = tsdoc_lint.mask_jsdoc( line )
    assert len( masked ) == len( line )
    assert masked.strip() == "- The items."


def test_mask_handles_each_named_tag_form_and_leaves_other_text_alone():
    assert tsdoc_lint.mask_jsdoc( "@param {string} [opt=1] - Text." ).strip() == "- Text."
    assert tsdoc_lint.mask_jsdoc( "@param obj.prop - Text." ).strip() == "- Text."
    assert tsdoc_lint.mask_jsdoc( "@template NONE" ).strip() == ""
    assert tsdoc_lint.mask_jsdoc( "@returns {string} The markup." ).strip() == "The markup."
    assert tsdoc_lint.mask_jsdoc( "@param" ).strip() == ""
    assert tsdoc_lint.mask_jsdoc( "Plain prose with {braces} and @ signs." ) == "Plain prose with {braces} and @ signs."


def test_mask_does_not_mask_an_unclosed_type_or_prose_after_the_tag():
    assert tsdoc_lint.mask_jsdoc( "@param {NONE name - The value." ).strip() == "{NONE name - The value."
    assert tsdoc_lint.mask_jsdoc( "@returns {string" ).strip() == "{string"


def test_mask_blanks_link_spans_only():
    masked = tsdoc_lint.mask_jsdoc( "See {@link NONE} and {@linkcode a.b} and {@plain NONE}." )
    assert masked == "See              and                 and {@plain NONE}."


# ---- the TS-only masks, both directions ------------------------------------------------------

def test_a_type_in_braces_is_not_prose_but_the_same_word_in_prose_is():
    assert _hits( [ _comment( "\nSummary.\n\n@param {NONE} name - The value.\n" ) ] ) == []
    assert _hits( [ _comment( "\nSummary.\n\nThe value is NONE here.\n" ) ] ) == [ ( 13, "caps" ) ]


def test_generic_and_nested_object_types_are_masked_whole():
    assert _hits( [ _comment( "\nSummary.\n\n@param {Map<string, NONE>} x - The value.\n" ) ] ) == []
    assert _hits( [ _comment( "\nSummary.\n\n@param {{ a: { b: NONE } }} x - The value.\n" ) ] ) == []


def test_a_tag_name_and_a_param_name_are_not_prose():
    assert _hits( [ _comment( "\nSummary.\n\n@NEVER The value.\n" ) ] ) == []
    assert _hits( [ _comment( "\nSummary.\n\n@param {string} NONE - The value.\n" ) ] ) == []
    assert _hits( [ _comment( "\nSummary.\n\n@param {string} [NONE=1] - The value.\n" ) ] ) == []
    assert _hits( [ _comment( "\nSummary.\n\n@template NONE\n" ) ] ) == []
    assert _hits( [ _comment( "\nSummary.\n\nNEVER do that here.\n" ) ] ) == [ ( 13, "caps" ) ]


def test_only_a_named_tag_loses_its_first_word_after_the_type():
    assert _hits( [ _comment( "\nSummary.\n\n@returns {string} NONE here.\n" ) ] ) == [ ( 13, "caps" ) ]


def test_a_link_span_is_masked_but_the_word_outside_it_is_not():
    assert _hits( [ _comment( "\nSummary.\n\nSee {@link NONE} for it.\n" ) ] ) == []
    assert _hits( [ _comment( "\nSummary.\n\nSee NONE for it.\n" ) ] ) == [ ( 13, "caps" ) ]


def test_an_unclosed_type_is_read_as_prose_so_its_words_fire():
    assert _hits( [ _comment( "\nSummary.\n\n@param {NONE name - The value.\n" ) ] ) == [ ( 13, "caps" ) ]


def test_a_link_over_two_lines_keeps_the_line_numbers_of_what_follows():
    text = "\nSummary.\n\nSee {@link Foo\nbar} here.\n\nNEVER do that.\n"
    assert tsdoc_lint.mask_jsdoc( text ).count( "\n" ) == text.count( "\n" )
    assert _hits( [ _comment( text ) ] ) == [ ( 16, "caps" ) ]


def test_a_type_over_several_lines_is_masked_whole_and_the_name_after_it_too():
    assert _hits( [ _comment( "\nSummary.\n\n@param {{ a: string,\n  b: NEVER }} opts - The opts.\n" ) ] ) == []
    assert _hits( [ _comment( "\nSummary.\n\n@param {{ a: string,\n  b: string }} NONE - The opts.\n" ) ] ) == []
    assert _hits( [ _comment( "\nSummary.\n\n@param {{ a: string,\n  b: string }} opts - NEVER used.\n" ) ] ) == [ ( 14, "caps" ) ]


def test_an_unclosed_type_does_not_stop_the_next_tag_from_being_masked():
    assert _hits( [ _comment( "\nSummary.\n\n@param {Foo x\n@param {string} NONE - The value.\n" ) ] ) == []


def test_the_prop_tag_names_its_first_word():
    assert _hits( [ _comment( "\nSummary.\n\n@prop {string} NONE - The value.\n" ) ] ) == []


def test_the_docstring_cap_is_exclusive_at_its_limit():
    def block( n ): return "\n" + "\n".join( [ "Summary." ] + [ "" ] * ( n - 2 ) + [ "Filler." ] ) + "\n"
    limit = tsdoc_lint.DOCSTRING_MAX_LINES
    assert _hits( [ _comment( block( limit ) ) ] ) == []
    assert _hits( [ _comment( block( limit + 1 ) ) ] ) == [ ( 10, "docstring-length" ) ]


# ---- same text, same verdict in both languages -----------------------------------------------

def _py_pairs( text ):
    return { ( f.rule, f.message ) for f in docstring_lint.lint_source( "a.py", '"""\n' + text + '\n"""\n' ) }


def _ts_pairs( text ):
    return { ( f.rule, f.message ) for f in tsdoc_lint.lint_comments( "a.ts", [ _comment( "\n" + text + "\n" ) ] ) }


# ( shape, text in the shape that might be exempt, the same words as plain prose, does text_rules flag the shape today )
SHARED_SHAPES = [
    ( "backtick label", "Summary.\n\nCluster ids look like `C1` here.", "Summary.\n\nCluster ids look like C1 here.", True ),
    ( "dotted identifier", "Summary.\n\nPass TaskType.BOUNDED here.", "Summary.\n\nPass BOUNDED here.", False ),
    ( "url", "Summary.\n\nSee https://example.com/a/b for more.", "Summary.\n\nSee example com a b for more.", False ),
    ( "url with a word in it", "Summary.\n\nSee https://example.com/NEVER/b for more.", "Summary.\n\nSee example NEVER b for more.", True ),
    ( "fenced block", "Summary.\n\n```\nconst x = NEVER;\n```\n", "Summary.\n\nconst x = NEVER;\n", False ),
    ( "example block", "Summary.\n\nExample:\n    x = NEVER\n", "Summary.\n\nx = NEVER\n", True ),
    ( "bracketed placeholder", "Summary.\n\nUsage: [--json NONE]\n", "Summary.\n\nUsage: NONE\n", True ),
    ( "key equals value line", "Summary.\n\ntest fix expediter phase 1 engine = sdk | claude_code\n", "Summary.\n\nIn phase 1 the engine is sdk.\n", False ),
    ( "file name", "Summary.\n\nSee broadcast-panel.js for it.\n", "Summary.\n\nSee broadcast-panel for it.\n", False ),
]


@pytest.mark.parametrize( "shape,exempt_text,prose_text,flagged", SHARED_SHAPES, ids=[ s[ 0 ] for s in SHARED_SHAPES ] )
def test_a_shape_that_both_languages_can_hold_gets_the_same_verdict_in_both( shape, exempt_text, prose_text, flagged ):
    assert _py_pairs( exempt_text ) == _ts_pairs( exempt_text )
    assert _py_pairs( prose_text ) == _ts_pairs( prose_text )
    assert bool( _ts_pairs( exempt_text ) ) is flagged, f"{shape}: today's text_rules verdict moved; update SHARED_SHAPES and the design"


# ---- rules on a JSDoc block ------------------------------------------------------------------

LONG_SENTENCE = " ".join( [ "word" ] * 30 ) + "."


def test_jsdoc_summary_sentence_caps_glyph_tic_ref_and_date_rules_land_on_their_lines():
    assert _hits( [ _comment( "\n" + " ".join( [ "word" ] * 20 ) + ".\n" ) ] ) == [ ( 11, "summary-length" ) ]
    assert _hits( [ _comment( f"\nShort one.\n\n{LONG_SENTENCE}\n" ) ] ) == [ ( 13, "sentence-length" ) ]
    assert _hits( [ _comment( "\nSummary.\n\nThis is NEVER fine.\n" ) ] ) == [ ( 13, "caps" ) ]
    assert _hits( [ _comment( "\nSummary.\n\n⚠ Careful here.\n" ) ] ) == [ ( 13, "glyph" ) ]
    assert _hits( [ _comment( "\nSummary.\n\nIt is deliberately slow.\n" ) ] ) == [ ( 13, "tic" ) ]
    assert _hits( [ _comment( "\nSummary.\n\nSee row aa543525 for it.\n" ) ] ) == [ ( 13, "bare-ref" ) ]
    assert _hits( [ _comment( "\nSummary.\n\nThe date 2026-05-16 is here.\n" ) ] ) == [ ( 13, "iso-date" ) ]
    assert "dated-banner" in _rules( [ _comment( "\nSummary.\n\nUpdated 2026-05-16 by someone.\n" ) ] )


def test_a_model_order_fires_on_jsdoc_only():
    text = "\nSummary.\n\nYou must call this first.\n"
    assert _hits( [ _comment( text ) ] ) == [ ( 13, "agent-imperative" ) ]
    assert _hits( [ _comment( text, kind="line-run" ) ] ) == []
    assert _hits( [ _comment( text, kind="block" ) ] ) == []
    assert _hits( [ _comment( text, kind="trailing" ) ] ) == []


def test_jsdoc_preface_before_a_contract_header_is_capped():
    lines = [ "Summary." ] + [ "a line." ] * 7 + [ "Requires:", "    - x" ]
    assert _hits( [ _comment( "\n" + "\n".join( lines ) + "\n" ) ] ) == [ ( 10, "preface-length" ) ]
    lines = [ "Summary." ] + [ "a line." ] * 3 + [ "Requires:", "    - x" ]
    assert _hits( [ _comment( "\n" + "\n".join( lines ) + "\n" ) ] ) == []


def test_jsdoc_longer_than_the_docstring_cap_is_flagged_once_at_its_start():
    assert _hits( [ _comment( "\nSummary.\n" + "Filler.\n\n" * 23 ) ] ) == [ ( 10, "docstring-length" ) ]
    assert _hits( [ _comment( "\nSummary.\n" + "Filler.\n\n" * 5 ) ] ) == []


def test_design_path_is_checked_only_when_a_root_is_given( tmp_path ):
    ( tmp_path / "doc.md" ).write_text( "x", encoding="utf-8" )
    comment = _comment( "\nSummary.\n\nDesign: missing.md\n" )
    assert _hits( [ comment ] ) == []
    assert _hits( [ comment ], root=tmp_path ) == [ ( 13, "dead-design" ) ]
    assert _hits( [ _comment( "\nSummary.\n\nDesign: doc.md\n" ) ], root=tmp_path ) == []


# ---- the reduced set, headers, skips, parse errors -------------------------------------------

def test_a_line_run_gets_the_reduced_rule_set_only():
    text = "This is NEVER ok, see row aa543525, deliberately, since 2026-05-16, and " + " ".join( [ "word" ] * 30 ) + ".\n"
    for kind in ( "line-run", "block", "trailing" ):
        assert _rules( [ _comment( text, kind=kind ) ] ) == { "caps", "tic", "iso-date" }


def test_only_the_file_header_run_gets_the_summary_rule():
    long_first = " ".join( [ "word" ] * 20 ) + "."
    assert _hits( [ _comment( long_first, kind="line-run", start=1, symbol_key="<file-header>" ) ] ) == [ ( 1, "summary-length" ) ]
    assert _hits( [ _comment( long_first, kind="line-run", start=1, symbol_key="FunctionDeclaration|f|0" ) ] ) == []
    assert _hits( [ _comment( long_first, kind="block", start=1, symbol_key="<file-header>" ) ] ) == []


def test_a_directive_comment_is_never_a_finding_even_when_it_shouts():
    assert _hits( [ _comment( "@ts-expect-error NEVER typed", kind="line-run", directive=True ) ] ) == []
    assert _hits( [ _comment( "\nSummary.\n\nNEVER.\n", directive=True ) ] ) == []


def test_commented_out_code_is_skipped_on_a_line_run_only():
    assert _hits( [ _comment( "const x = NEVER;", kind="line-run", commented_code=True ) ] ) == []
    assert _hits( [ _comment( "const x = NEVER;", kind="block", commented_code=True ) ] ) == [ ( 10, "caps" ) ]
    assert _hits( [ _comment( "\nSummary.\n\nNEVER.\n", commented_code=True ) ] ) == [ ( 13, "caps" ) ]
    assert _hits( [ { k: v for k, v in _comment( "const x = NEVER;", kind="line-run" ).items() if k != "commented_code" } ] ) == [ ( 10, "caps" ) ]


def test_a_parse_error_is_one_finding_at_its_first_line_and_the_comments_are_still_read():
    errors = [ { "line": 4, "message": "Unexpected token" }, { "line": 9, "message": "Another" } ]
    found  = tsdoc_lint.lint_comments( "a.ts", [ _file_record( errors ), _comment( "\nSummary.\n\nNEVER.\n" ) ] )
    assert [ ( f.line, f.rule ) for f in found ] == [ ( 4, "parse-error" ), ( 13, "caps" ) ]
    assert found[ 0 ].message == "does not parse: Unexpected token"
    assert _hits( [ _file_record() ] ) == []


def test_findings_are_sorted_by_line_then_rule():
    comments = [ _comment( "\nSummary.\n\nThis is NEVER fine, see row aa543525.\n", start=40 ), _comment( "\nSummary.\n\nNEVER.\n", start=10 ) ]
    hits     = _hits( comments )
    assert hits == sorted( hits ) and hits[ 0 ] == ( 13, "caps" ) and ( 43, "bare-ref" ) in hits


# ---- the extractor seam ----------------------------------------------------------------------

def _fake_run( monkeypatch, outputs ):
    calls = []

    def fake( cmd, **kwargs ):
        calls.append( cmd )
        return outputs( cmd ) if callable( outputs ) else outputs

    monkeypatch.setattr( tsdoc_lint.subprocess, "run", fake )
    return calls


def _done( stdout="", returncode=0, stderr="" ):
    return types.SimpleNamespace( stdout=stdout, returncode=returncode, stderr=stderr )


def test_run_extractor_groups_records_by_file_and_skips_blank_lines( monkeypatch, tmp_path ):
    lines = "\n".join( [ json.dumps( _file_record() | { "file": "a.ts" } ), "", json.dumps( _comment( "x", file="a.ts" ) ), json.dumps( _comment( "y", file="other.ts" ) ) ] )
    calls = _fake_run( monkeypatch, _done( lines ) )
    found = tsdoc_lint.run_extractor( tmp_path, [ "a.ts", "b.ts" ] )
    assert [ r[ "kind" ] for r in found[ "a.ts" ] ] == [ "file", "jsdoc" ]
    assert found[ "b.ts" ] == [] and [ r[ "text" ] for r in found[ "other.ts" ] ] == [ "y" ]
    assert calls == [ [ "node", os.path.join( str( tmp_path ), "src/scripts/ts_doc_extract.mjs" ), "--repo-root", str( tmp_path ), "a.ts", "b.ts" ] ]


def test_run_extractor_sends_files_in_batches_never_one_process_per_file( monkeypatch, tmp_path ):
    files = [ f"f{i}.ts" for i in range( 450 ) ]
    calls = _fake_run( monkeypatch, _done() )
    found = tsdoc_lint.run_extractor( tmp_path, files )
    assert [ len( c ) - 4 for c in calls ] == [ 200, 200, 50 ]
    assert list( found ) == files


def test_run_extractor_with_no_files_starts_no_process( monkeypatch, tmp_path ):
    calls = _fake_run( monkeypatch, _done() )
    assert tsdoc_lint.run_extractor( tmp_path, [] ) == {} and calls == []


def test_run_extractor_refuses_a_failed_run_a_bad_line_and_a_missing_node( monkeypatch, tmp_path ):
    _fake_run( monkeypatch, _done( returncode=2, stderr="boom\n" ) )
    with pytest.raises( RuntimeError, match="extractor failed: boom" ):
        tsdoc_lint.run_extractor( tmp_path, [ "a.ts" ] )
    _fake_run( monkeypatch, _done( "not json at all" ) )
    with pytest.raises( RuntimeError, match="not JSON" ):
        tsdoc_lint.run_extractor( tmp_path, [ "a.ts" ] )

    def no_node( cmd, **kwargs ): raise FileNotFoundError( "node" )

    monkeypatch.setattr( tsdoc_lint.subprocess, "run", no_node )
    with pytest.raises( RuntimeError, match="cannot run node" ):
        tsdoc_lint.run_extractor( tmp_path, [ "a.ts" ] )


# ---- the command line ------------------------------------------------------------------------

def _canned( monkeypatch, per_file ):
    asked = []

    def fake( root, files ):
        asked.append( list( files ) )
        return { f: per_file.get( f, [ _file_record() ] ) for f in files }

    monkeypatch.setattr( tsdoc_lint, "run_extractor", fake )
    return asked


def test_main_reports_text_json_strict_exit_and_filters_the_paths_it_is_given( repo, monkeypatch ):
    _commit( repo, { "src/a.ts": "x\n", "src/b.py": "x\n", "src/tests/unit/t.test.ts": "x\n" } )
    asked = _canned( monkeypatch, { "src/a.ts": [ _file_record(), _comment( "\nSummary.\n\nNEVER.\n", start=3 ) ] } )
    out   = io.StringIO()
    assert tsdoc_lint.main( [ "--repo-root", str( repo ) ], out ) == 0
    assert asked == [ [ "src/a.ts", "src/tests/unit/t.test.ts" ] ]
    assert out.getvalue().splitlines() == [ "src/a.ts:6: caps: ALL-CAPS word NEVER", "1 findings in 2 files" ]
    assert tsdoc_lint.main( [ "--repo-root", str( repo ), "--strict" ], io.StringIO() ) == 1
    assert tsdoc_lint.main( [ "--repo-root", str( repo ), "--strict", "src/tests/unit/t.test.ts" ], io.StringIO() ) == 0
    js = io.StringIO()
    tsdoc_lint.main( [ "--repo-root", str( repo ), "--json", "src/a.ts", "src/b.py" ], js )
    assert asked[ -1 ] == [ "src/a.ts" ]
    assert [ ( f[ "line" ], f[ "rule" ] ) for f in json.loads( js.getvalue() ) ] == [ ( 6, "caps" ) ]


def test_main_changed_and_staged_keep_only_touched_lines( repo, monkeypatch ):
    _commit( repo, { "src/a.ts": "".join( f"line {i}\n" for i in range( 1, 11 ) ) } )
    ( repo / "src" / "a.ts" ).write_text( "".join( f"line {i}\n" if i != 5 else "changed\n" for i in range( 1, 11 ) ), encoding="utf-8" )
    comments = [ _file_record(), _comment( "\nSummary.\n\nNEVER.\n", start=2 ), _comment( "\nSummary.\n\nNEVER.\n", start=3 ) ]
    comments = [ comments[ 0 ], _comment( "NEVER.\n", kind="line-run", start=5 ), _comment( "NEVER.\n", kind="line-run", start=9 ) ]
    _canned( monkeypatch, { "src/a.ts": comments } )
    out = io.StringIO()
    tsdoc_lint.main( [ "--repo-root", str( repo ), "--changed", "HEAD" ], out )
    assert "src/a.ts:5: caps" in out.getvalue() and "src/a.ts:9:" not in out.getvalue()
    _git( repo, "add", "-A" )
    out = io.StringIO()
    tsdoc_lint.main( [ "--repo-root", str( repo ), "--staged" ], out )
    assert "src/a.ts:5: caps" in out.getvalue() and "src/a.ts:9:" not in out.getvalue()


def test_main_defaults_to_stdout_and_to_sys_argv( repo, monkeypatch, capsys ):
    _commit( repo, { "src/a.ts": "x\n" } )
    _canned( monkeypatch, {} )
    monkeypatch.setattr( sys, "argv", [ "tsdoc_lint", "--repo-root", str( repo ) ] )
    assert tsdoc_lint.main() == 0
    assert capsys.readouterr().out == "0 findings in 1 files\n"


def test_running_the_module_as_a_script_exits_with_main_status( repo, monkeypatch ):
    _commit( repo, { "src/a.ts": "x\n" } )
    _fake_run( monkeypatch, _done( json.dumps( _file_record() ) ) )
    monkeypatch.setattr( sys, "argv", [ "tsdoc_lint", "--repo-root", str( repo ), "src/a.ts" ] )
    with warnings.catch_warnings():
        warnings.simplefilter( "ignore", RuntimeWarning )
        with pytest.raises( SystemExit ) as stop:
            runpy.run_module( "cosa.repo.doc_lint.tsdoc_lint", run_name="__main__" )
    assert stop.value.code == 0


# ---- fixture files ---------------------------------------------------------------------------

def _load_fixture( path ):
    by_file = {}
    with open( path, encoding="utf-8" ) as handle:
        for raw in handle:
            if raw.strip():
                record = json.loads( raw )
                by_file.setdefault( record[ "file" ], [] ).append( record )
    return by_file


def test_every_fixture_file_lints_without_error():
    paths = sorted( glob.glob( os.path.join( FIXTURES, "*.jsonl" ) ) )
    assert paths, f"no fixture under {FIXTURES}"
    for path in paths:
        expected_path = path[ : -len( ".jsonl" ) ] + ".expected.json"
        expected      = json.load( open( expected_path, encoding="utf-8" ) ) if os.path.exists( expected_path ) else None
        by_file       = _load_fixture( path )
        assert by_file, path
        # A capture from the real extractor is read with the real word list; the small list belongs to the hand-written cases.
        previous = word_list._state[ "root" ]
        if os.path.basename( path ).startswith( "real-" ): word_list.configure_root( os.environ[ "LUPIN_ROOT" ] )
        for name, records in by_file.items():
            found  = tsdoc_lint.lint_comments( name, records )
            spans  = [ ( r[ "start_line" ], r[ "end_line" ] ) for r in records if r[ "kind" ] != "file" ]
            errors = { e[ "line" ] for r in records if r[ "kind" ] == "file" for e in r[ "parse_errors" ] }
            assert found == sorted( found, key=lambda f: ( f.line, f.rule, f.message ) )
            for f in found:
                assert f.line in errors or any( a <= f.line <= b for a, b in spans ), f"{path}: {f} is outside every comment"
            if expected is not None:
                assert [ [ f.line, f.rule ] for f in found ] == expected[ name ], f"{path}: {name}"
        word_list.configure_root( previous )
        if expected is not None: assert set( expected ) == set( by_file ), path
