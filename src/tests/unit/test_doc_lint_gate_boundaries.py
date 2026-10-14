"""
The commit gate at its edges: moved pages, odd file names, odd line ends, gitlinks.

Every test builds a small real git repository in a temporary directory and runs the real gate on it.
"""

import hashlib
import io
import json
import os
import shutil
import subprocess

import pytest

import cosa.utils.util as cu
from cosa.repo.doc_lint import changed_ranges as cr, cli, counts, gate, md_lint, tool_runners as tr, ts_counts, tsdoc_lint, word_list
from cosa.repo.doc_lint.text_rules import Finding

WORDS         = [ "not", "never", "the" ]
SEEDED        = "This is NOT fine.\n"
CAPS          = "caps: ALL-CAPS word NOT"
CAP_PAGE      = "src/docs/wiki/capabilities/x.md"
PREDATES_MARK = " (warn mode, commit allowed: this condition predates the commit)"
LATIN_MD      = "docs/caf\udce9.md"                                                            # the byte 0xE9, as Python reads a name from the file system
BAD_LAYOUT    = 'def f():\n    """Summary.\n    Description without a blank line.\n    """\n'
TS_ONE        = "/** This is NOT fine. */\nexport const x = 1;\n"


def _git( root, *args ):
    res = subprocess.run( [ "git", "-C", str( root ), "-c", "user.email=t@t", "-c", "user.name=t", *args ], capture_output=True, text=True )
    assert res.returncode == 0, res.stderr
    return res.stdout


@pytest.fixture
def repo( tmp_path ):
    _git( tmp_path, "init", "-q" )
    ( tmp_path / "src" / "conf" ).mkdir( parents=True )
    ( tmp_path / "src" / "conf" / "dm-tutor-lowercase-words.txt" ).write_text( "\n".join( WORDS ) + "\n", encoding="utf-8" )
    yield tmp_path
    word_list._state[ "root" ]  = None
    word_list._state[ "words" ] = None


def _stage( repo, files ):
    for rel, text in files.items():
        full = repo / rel
        full.parent.mkdir( parents=True, exist_ok=True )
        full.write_text( text, encoding="utf-8" )
    _git( repo, "add", "-f", "--", *files )


def _stage_bytes( repo, rel, data ):
    full = repo / rel
    full.parent.mkdir( parents=True, exist_ok=True )
    full.write_bytes( data )
    _git( repo, "add", "-f", rel )


def _commit( repo, files, message="base" ):
    _stage( repo, files )
    _git( repo, "commit", "-q", "--no-verify", "-m", message )


def _no_external( monkeypatch ):
    monkeypatch.setattr( gate, "run_ruff", lambda root, paths, sources=None: ( [], [] ) )
    monkeypatch.setattr( gate, "run_markdownlint", lambda root, paths: ( [], [] ) )
    monkeypatch.setattr( gate, "markdownlint_unnamed", lambda root, paths: [], raising=False )


def _blocking( repo ):
    err = io.StringIO()
    rc  = gate.main( [ "--repo-root", str( repo ), "--blocking" ], err )
    return rc, err.getvalue().split( "\n" )


def _refused( lines ):
    return sorted( ln for ln in lines if ln.startswith( "[doc-lint] REFUSED " ) )


def _page( count ):
    return "# Page\n" + "".join( f"Line {n} is fine.\n" for n in range( 2, count + 1 ) )


def _doc( line ):
    return f'def f():\n    """\n    Return it.\n\n    {line}\n    """\n'


# ---- a page moved without an edit ---------------------------------------------------------------

@pytest.mark.parametrize( "old,new,expected", [
    ( "docs/x.md",   CAP_PAGE,              [ f"[doc-lint] REFUSED {CAP_PAGE}:1: capability-length: capability page of 45 lines, limit 40" ] ),
    ( "docs/ops.md", "docs/ops-runbook.md", sorted( f"[doc-lint] REFUSED docs/ops-runbook.md:1: runbook-template: runbook has no {s} section" for s in md_lint.RUNBOOK_SECTIONS ) ),
] )
def test_a_page_moved_without_an_edit_to_a_path_that_brings_a_limit_is_refused( repo, monkeypatch, old, new, expected ):
    _no_external( monkeypatch )
    _commit( repo, { old: _page( 45 ) } )
    ( repo / new ).parent.mkdir( parents=True, exist_ok=True )
    _git( repo, "mv", old, new )
    diff = _git( repo, "diff", "--cached", "-M" )
    assert "similarity index 100%" in diff and "+++" not in diff and gate.staged_changes( str( repo ) )[ 1 ] == { new: old }
    rc, lines = _blocking( repo )
    assert rc == gate.REFUSAL_EXIT and _refused( lines ) == expected
    assert f"[doc-lint] {len( expected )} findings on staged lines, commit REFUSED: fix each REFUSED line above, stage the fix and commit again" in lines
    assert not [ ln for ln in lines if "predate" in ln ]


def test_a_page_moved_without_an_edit_between_two_paths_under_the_same_limit_is_allowed_with_the_marking( repo, monkeypatch ):
    _no_external( monkeypatch )
    _commit( repo, { "src/docs/wiki/capabilities/old.md": _page( 41 ) } )
    _git( repo, "mv", "src/docs/wiki/capabilities/old.md", CAP_PAGE )
    rc, lines = _blocking( repo )
    assert rc == 0 and f"[doc-lint] {CAP_PAGE}:1: capability-length: capability page of 41 lines, limit 40{PREDATES_MARK}" in lines
    assert "[doc-lint] 1 page-level findings predate this commit (warn mode, commit allowed)" in lines and not _refused( lines )


def test_a_page_moved_without_an_edit_keeps_its_untouched_lines_out_of_the_line_level_findings( repo, monkeypatch ):
    _no_external( monkeypatch )
    _commit( repo, { "docs/x.md": SEEDED } )
    _git( repo, "mv", "docs/x.md", "docs/y.md" )
    rc, lines = _blocking( repo )
    assert rc == 0 and "[doc-lint] 0 findings on staged lines (blocking)" in lines and not [ ln for ln in lines if "caps" in ln ]


def test_the_diff_reader_gives_a_file_moved_or_copied_without_an_edit_its_entry_and_no_range():
    text = (
        "diff --git a/docs/x.md b/src/y.md\nsimilarity index 100%\nrename from docs/x.md\nrename to src/y.md\n"
        'diff --git "a/caf\\351.md" "b/d/caf\\351.md"\nsimilarity index 100%\nrename from "caf\\351.md"\nrename to "d/caf\\351.md"\n'
        "diff --git a/a.md b/b.md\nsimilarity index 100%\ncopy from a.md\ncopy to b.md\n"
        "diff --git a/p.md b/q.md\nsimilarity index 90%\nrename from p.md\nrename to q.md\n--- a/p.md\n+++ b/q.md\n@@ -2 +2 @@\n-old\n+new\n"
    )
    assert cr.parse_diff_ranges( text ) == { "src/y.md": [], "d/caf\udce9.md": [], "b.md": [], "q.md": [ ( 2, 2 ) ] }
    kept = cr.filter_findings( [ Finding( "src/y.md", 1, "capability-length", "m" ), Finding( "src/y.md", 1, "caps", "m" ) ], cr.parse_diff_ranges( text ) )
    assert [ f.rule for f in kept ] == [ "capability-length" ]


@pytest.mark.parametrize( "setting", [ "copies", "true", "false" ] )
def test_a_copy_is_a_new_file_with_every_line_touched_whatever_the_users_rename_setting( repo, monkeypatch, setting ):
    _no_external( monkeypatch )
    body = SEEDED + "".join( f"Line {n} is fine.\n" for n in range( 2, 12 ) )
    _commit( repo, { "docs/a.md": body } )
    _git( repo, "config", "diff.renames", setting )
    _stage( repo, { "docs/a.md": body + "One more fine line.\n", "docs/b.md": body } )         # git pairs a copy only with a file the commit also changes
    assert cr.changed_line_ranges( str( repo ), None, cached=True ) == { "docs/a.md": [ ( 12, 12 ) ], "docs/b.md": [ ( 1, 11 ) ] }
    rc, lines = _blocking( repo )
    assert rc == gate.REFUSAL_EXIT and _refused( lines ) == [ f"[doc-lint] REFUSED docs/b.md:1: {CAPS}" ]


@pytest.mark.parametrize( "setting", [ "copies", "true", "false" ] )
def test_a_move_without_an_edit_has_its_entry_whatever_the_users_rename_setting( repo, setting ):
    _commit( repo, { "docs/x.md": _page( 45 ) } )
    _git( repo, "config", "diff.renames", setting )
    ( repo / CAP_PAGE ).parent.mkdir( parents=True )
    _git( repo, "mv", "docs/x.md", CAP_PAGE )
    assert cr.changed_line_ranges( str( repo ), None, cached=True ) == { CAP_PAGE: [] }


# ---- a file name that a tool cannot read back ---------------------------------------------------

def test_the_names_that_cross_as_text_are_the_ones_without_a_byte_that_is_not_utf8():
    assert cli.crosses_as_text( "docs/café two.md" ) and cli.crosses_as_text( "docs/new\nline.md" ) and not cli.crosses_as_text( LATIN_MD )


def test_ruff_findings_keep_the_path_that_was_asked_for_when_ruff_prints_another_name( monkeypatch, tmp_path ):
    monkeypatch.setenv( "LUPIN_RUFF", str( tmp_path ) )
    asked = "src/lupin_mcp/caf\udce9.py"
    calls = []
    def fake( cmd, **kwargs ):
        calls.append( cmd )
        printed = [ { "filename": "/r/src/lupin_mcp/caf�.py", "code": "D205", "message": "m", "location": { "row": 2, "column": 1 } } ]
        return type( "Done", (), { "returncode": 1, "stdout": json.dumps( printed ), "stderr": "" } )()
    findings, warnings = tr.run_ruff( "/r", [ asked ], fake, sources={ asked: BAD_LAYOUT } )
    assert warnings == [] and [ ( f.path, f.line, f.rule ) for f in findings ] == [ ( asked, 2, "ruff:D205" ) ]
    assert calls[ 0 ][ -2: ] == [ f"--stdin-filename={asked}", "-" ]


def test_ruff_without_sources_is_not_given_a_name_it_cannot_read_back_and_says_so( monkeypatch, tmp_path ):
    monkeypatch.setenv( "LUPIN_RUFF", str( tmp_path ) )
    calls = []
    def fake( cmd, **kwargs ):
        calls.append( cmd )
        printed = [ { "filename": "/r/src/other.py", "code": "D205", "message": "m", "location": { "row": 2, "column": 1 } } ]
        return type( "Done", (), { "returncode": 1, "stdout": json.dumps( printed ), "stderr": "" } )()
    findings, warnings = tr.run_ruff( "/r", [ "src/a.py", "src/caf\udce9.py" ], fake )
    assert calls[ 0 ][ -2: ] == [ "--", "src/a.py" ] and "src/caf\udce9.py" not in calls[ 0 ]
    assert warnings == [
        "[doc-lint] WARNING: src/caf\\xe9.py has a file name that is not UTF-8 or holds a line break, so ruff cannot be given it and it was NOT checked by ruff",
        "[doc-lint] WARNING: ruff placed a finding in src/other.py, a file it was not asked about, so that finding is NOT attached to any staged file",
    ]
    assert tr.run_ruff( "/r", [ "src/caf\udce9.py" ], lambda cmd, **kwargs: pytest.fail( "no run for no name" ) ) == ( [], [ warnings[ 0 ] ] )


def test_the_real_ruff_finding_in_a_file_whose_name_is_not_utf8_is_refused( repo, monkeypatch ):
    if tr.find_tool( cu.get_project_root(), tr.RUFF_RELATIVE, "ruff", "LUPIN_RUFF" ) is None: pytest.skip( "ruff is not installed in this environment" )
    monkeypatch.setattr( gate, "run_markdownlint", lambda root, paths: ( [], [] ) )
    shutil.copy( os.path.join( cu.get_project_root(), "pyproject.toml" ), repo / "pyproject.toml" )
    outcomes = {}
    for name in ( "plain.py", "caf\udce9.py" ):
        _git( repo, "rm", "-rqf", "--cached", "--ignore-unmatch", "src/lupin_mcp" )
        _stage( repo, { f"src/lupin_mcp/{name}": BAD_LAYOUT } )
        rc, lines = _blocking( repo )
        outcomes[ name ] = ( rc, [ ln.split( ":2: ruff:D205" )[ 0 ] for ln in _refused( lines ) if "ruff:D205" in ln ] )
    assert outcomes == { "plain.py": ( 3, [ "[doc-lint] REFUSED src/lupin_mcp/plain.py" ] ), "caf\udce9.py": ( 3, [ "[doc-lint] REFUSED src/lupin_mcp/caf\\xe9.py" ] ) }


def _markdownlint_stub( tmp_path, monkeypatch ):
    """Install a markdownlint-cli2 stand-in that records the names it was given."""
    log  = tmp_path / "markdownlint-args.txt"
    tool = tmp_path / "markdownlint-cli2"
    tool.write_text( f'#!/bin/sh\nfor a in "$@"; do printf "%s\\0" "$a" >> "{log}"; done\nn=0; for a in \"$@\"; do case \"$a\" in --|--no-globs) ;; *) n=$((n+1));; esac; done; echo \"Linting: $n file(s)\"\nexit 0\n', encoding="utf-8" )
    os.chmod( tool, 0o755 )
    monkeypatch.setenv( "LUPIN_MARKDOWNLINT", str( tool ) )
    return log


@pytest.mark.parametrize( "name,printed", [ ( LATIN_MD, "docs/caf\\xe9.md" ), ( "docs/new\nline.md", "docs/new\\nline.md" ), ( "docs/new\rline.md", "docs/new\\rline.md" ) ] )
def test_a_clean_markdown_file_that_markdownlint_cannot_be_given_is_refused_and_named( repo, monkeypatch, tmp_path, name, printed ):
    monkeypatch.setattr( gate, "run_ruff", lambda root, paths, sources=None: ( [], [] ) )
    log = _markdownlint_stub( tmp_path, monkeypatch )
    _stage( repo, { name: "A clean page.\n", "docs/ok.md": "A clean page.\n" } )
    rc, lines = _blocking( repo )
    assert rc == gate.REFUSAL_EXIT and "[doc-lint] 1 refusals, commit REFUSED" in lines
    assert _refused( lines ) == [ f"[doc-lint] REFUSED {printed}: the file name is not UTF-8 or holds a line break, so markdownlint-cli2 cannot be given it and its markdown structure was NOT checked; fix: rename the file; this cannot be waived" ]
    assert f"[doc-lint] WARNING: {printed} has a file name that is not UTF-8 or holds a line break, so markdownlint-cli2 cannot be given it and it was NOT checked by markdownlint-cli2" in lines
    assert log.read_bytes().split( b"\0" ) == [ b"--no-globs", b"--", b"docs/ok.md", b"" ]            # the other file was still checked


def test_a_markdown_name_that_cannot_be_given_refuses_nothing_when_markdownlint_is_not_installed( repo, monkeypatch ):
    for var in ( "LUPIN_RUFF", "LUPIN_MARKDOWNLINT" ): monkeypatch.delenv( var, raising=False )
    monkeypatch.setattr( tr.shutil, "which", lambda name: None )
    _stage( repo, { LATIN_MD: "A clean page.\n" } )
    rc, lines = _blocking( repo )
    assert rc == 0 and not _refused( lines ) and [ ln for ln in lines if "markdownlint-cli2 not found, SKIPPED" in ln ]
    assert tr.markdownlint_unnamed( str( repo ), [ LATIN_MD ] ) == []


def test_markdownlint_names_a_finding_it_places_in_a_file_it_was_not_asked_about( monkeypatch, tmp_path ):
    monkeypatch.setenv( "LUPIN_MARKDOWNLINT", str( tmp_path ) )
    done = type( "Done", (), { "returncode": 1, "stdout": "Linting: 1 file(s)\n", "stderr": "a.md:3 error MD040/fenced-code-language m\nother.md:1 error MD041/first-line-h1 m\n" } )()
    findings, warnings = tr.run_markdownlint( "/r", [ "a.md", LATIN_MD ], lambda cmd, **kwargs: done )
    assert [ ( f.path, f.line ) for f in findings ] == [ ( "a.md", 3 ), ( "other.md", 1 ) ]
    assert warnings == [
        "[doc-lint] WARNING: docs/caf\\xe9.md has a file name that is not UTF-8 or holds a line break, so markdownlint-cli2 cannot be given it and it was NOT checked by markdownlint-cli2",
        "[doc-lint] WARNING: markdownlint-cli2 placed a finding in other.md, a file it was not asked about, so that finding is NOT attached to any staged file",
    ]
    failing = type( "Done", (), { "returncode": 2, "stdout": "", "stderr": "bad config" } )()
    assert tr.run_markdownlint( "/r", [ "a.md", LATIN_MD ], lambda cmd, **kwargs: failing ) == ( [], [ warnings[ 0 ], "[doc-lint] WARNING: markdownlint-cli2 failed (exit 2), SKIPPED: bad config" ] )
    assert tr.run_markdownlint( "/r", [ LATIN_MD ], lambda cmd, **kwargs: pytest.fail( "no run for no name" ) ) == ( [], [ warnings[ 0 ] ] )


def _lossy_node( root, files, source_root=None ):
    """Stand in for Node, which reads a byte that is not UTF-8 as U+FFFD and opens another file."""
    out = { name: [] for name in files }
    for name in files:
        seen = os.fsencode( name ).decode( "utf-8", "replace" )
        full = os.path.join( str( source_root ), seen )
        if not os.path.exists( full ):
            out.setdefault( seen, [] ).append( { "kind": "file", "file": seen, "ts_version": "5.9.3", "parse_errors": [ { "line": 0, "message": "cannot extract: ENOENT" } ] } )
            continue
        with open( full, encoding="utf-8" ) as handle: text = handle.read()
        out[ seen ] = [ { "kind": "file", "file": seen, "ts_version": "5.9.3", "parse_errors": [] } ]
        for i, line in enumerate( text.split( "\n" ) ):
            if "/**" in line and "*/" in line:
                out[ seen ].append( { "kind": "jsdoc", "file": seen, "text": line.split( "/**", 1 )[ 1 ].split( "*/", 1 )[ 0 ].strip(), "start_line": i + 1, "end_line": i + 1,
                                      "symbol_key": None, "directive": False, "tags": [], "ts_version": "5.9.3", "commented_code": False } )
    return out


def test_a_script_file_whose_name_is_not_utf8_is_counted_like_one_with_a_plain_name( repo, monkeypatch ):
    monkeypatch.setattr( tsdoc_lint, "run_extractor", _lossy_node )
    texts = { "src/zzplain.ts": TS_ONE, "src/zzcaf\udce9.ts": TS_ONE, "src/d\udce9/deep.mjs": TS_ONE }
    got   = ts_counts.counts_for( str( repo ), texts )
    assert { path: result.count for path, result in got.items() } == { path: 1 for path in texts }
    assert [ f.path for f in got[ "src/zzcaf\udce9.ts" ].findings ] == [ "src/zzcaf\udce9.ts" ]


def _stand_in( path ):
    return ".git/" + hashlib.sha256( os.fsencode( path ) ).hexdigest() + os.path.splitext( path )[ 1 ]


def test_a_stand_in_name_is_a_digest_of_the_path_bytes_in_a_folder_no_real_path_sits_in():
    odd   = [ "src/caf\udce9.ts", "src/caf\udcea.ts", "d\udce9/x.min.js", "--x.ts", "-dir/y.mjs", "a" * 250 + "\udcff.ts", "src/notes/d\udcff.ts/y.ts" ]
    plain = [ "src/a.ts", "src/caf_.0.ts", "src/-b.ts", "src/notes/d_.ts" ]
    names = ts_counts.scratch_names( plain + odd )
    assert names == { **{ path: path for path in plain }, **{ path: _stand_in( path ) for path in odd } }
    assert len( set( names.values() ) ) == len( names ) and all( cli.crosses_as_text( name ) and not name.startswith( "-" ) for name in names.values() )
    assert sorted( len( names[ path ] ) for path in odd ) == [ 72, 72, 72, 72, 72, 72, 73 ]      # the folder, 64 hex digits and the suffix, whatever the path's length


def test_git_tracks_no_path_inside_the_stand_in_folder( repo ):
    blob = subprocess.run( [ "git", "-C", str( repo ), "hash-object", "-w", "--stdin" ], input=b"x", capture_output=True ).stdout.decode().strip()
    for path in ( f"{ts_counts.STAND_IN_FOLDER}/x.ts", f"src/{ts_counts.STAND_IN_FOLDER}/x.ts" ):
        res = subprocess.run( [ "git", "-C", str( repo ), "update-index", "--add", "--cacheinfo", f"100644,{blob},{path}" ], capture_output=True, text=True )
        assert res.returncode != 0 and "Invalid path" in res.stderr
    _git( repo, "update-index", "--add", "--cacheinfo", f"100644,{blob},src/x.ts" )                # the control: the same command adds a plain path
    assert _git( repo, "ls-files" ) == "src/x.ts\n"


@pytest.mark.skipif( shutil.which( "node" ) is None, reason="node is not installed" )
def test_the_real_extractor_counts_a_file_whose_name_is_not_utf8( repo, monkeypatch ):
    monkeypatch.setattr( tsdoc_lint, "EXTRACTOR_REL", os.path.join( cu.get_project_root(), "src/scripts/ts_doc_extract.mjs" ) )
    text = "/**\n * This is NOT fine.\n */\nexport const x = 1;\n"
    got  = ts_counts.counts_for( str( repo ), { "src/zzplain.ts": text, "src/zzcaf\udce9.ts": text } )
    assert { path: result.count for path, result in got.items() } == { "src/zzplain.ts": 1, "src/zzcaf\udce9.ts": 1 }


def test_a_staged_script_file_whose_name_is_not_utf8_is_refused_when_its_count_rises( repo, monkeypatch ):
    _no_external( monkeypatch )
    monkeypatch.setattr( tsdoc_lint, "run_extractor", _lossy_node )
    for rel in ts_counts.STAMP_FILES:
        if not ( repo / rel ).exists(): _stage( repo, { rel: f"stamp file {rel}\n" } )
    _stage( repo, { ts_counts.TABLE_PATH: counts.table_text( {}, ts_counts.rules_stamp( str( repo ) ) ) } )
    _git( repo, "commit", "-q", "--no-verify", "-m", "base" )
    outcomes = {}
    for name in ( "src/web/zzplain.ts", "src/web/zzcaf\udce9.ts" ):
        _git( repo, "reset", "-q" )
        _stage( repo, { name: TS_ONE } )
        rc, lines = _blocking( repo )
        outcomes[ name ] = ( rc, [ ln for ln in lines if "1 findings, the count table allows 0" in ln ][ : 1 ] != [] )
    assert outcomes == { "src/web/zzplain.ts": ( 3, True ), "src/web/zzcaf\udce9.ts": ( 3, True ) }


def test_the_rule_file_listings_keep_a_name_that_is_not_utf8( repo ):
    odd = "src/cosa/repo/doc_lint/caf\udce9.py"
    _commit( repo, { odd: "x = 1\n" } )
    ( repo / odd ).write_text( "x = 2\n", encoding="utf-8" )
    assert counts.rule_files( str( repo ) ) == [ odd ] and counts.differing_rule_files( str( repo ) ) == ( 1, [ odd ] )
    assert "caf\\xe9.py" in gate.rule_divergence( 1, [ odd ], True )


def test_a_count_table_carries_a_name_that_is_not_utf8_through_its_json_and_back( repo ):
    odd  = "src/tests/caf\udce9.py"
    text = counts.table_text( { odd: 2 }, "stamp" )
    text.encode( "utf-8" )                                                                     # the table is plain text that a strict writer accepts
    assert counts.parse_table( text ).files == { odd: 2 }
    _stage( repo, { counts.TABLE_PATH: text } )
    assert counts.parse_table( gate.staged_source( str( repo ), counts.TABLE_PATH ) ).files == { odd: 2 }


# ---- an incoming-commit file that cannot be read ------------------------------------------------

@pytest.mark.skipif( os.geteuid() == 0, reason="root reads a file whatever its mode" )
@pytest.mark.parametrize( "head", [ "MERGE_HEAD", "CHERRY_PICK_HEAD" ] )
def test_an_unreadable_incoming_head_is_ignored_with_a_loud_line_and_every_finding_is_enforced( repo, monkeypatch, head ):
    _no_external( monkeypatch )
    _commit( repo, { "docs/a.md": "clean\n" } )
    _stage( repo, { "docs/p.md": SEEDED } )
    marker = repo / ".git" / head
    marker.write_text( _git( repo, "rev-parse", "HEAD" ), encoding="utf-8" )
    os.chmod( marker, 0 )
    assert gate.incoming_commit( str( repo ) ) == ( None, [ f"[doc-lint] WARNING: {head} could not be read (PermissionError), so it was ignored and every finding is enforced" ] )
    rc, lines = _blocking( repo )
    assert rc == gate.REFUSAL_EXIT and _refused( lines ) == [ f"[doc-lint] REFUSED docs/p.md:1: {CAPS}" ]
    assert f"[doc-lint] WARNING: {head} could not be read (PermissionError), so it was ignored and every finding is enforced" in lines
    assert not [ ln for ln in lines if "GATE CRASHED" in ln or "came in with" in ln ]


# ---- a file whose lines end in a bare carriage return ---------------------------------------------

CR_SOURCE = _doc( "This is NOT fine." ).replace( "\n", "\r" ).encode( "utf-8" )


def test_the_lines_of_a_source_are_split_the_way_its_parser_numbers_them():
    assert cli.split_lines( "a\rb\r\nc\nd" ) == [ "a", "b", "c", "d" ] and cli.split_lines( "a b\x0cc" ) == [ "a b\x0cc" ]
    assert cli.split_lines( "a b c\rd", cli.SCRIPT_BREAKS ) == [ "a", "b", "c", "d" ]
    lines = cli.split_lines( "one\rtwo" )
    assert [ cli.line_text( lines, n ) for n in ( 0, 1, 2, 3, -1 ) ] == [ "", "one", "two", "", "" ]


def test_a_swept_file_with_bare_carriage_returns_is_refused_for_its_docstring_finding( repo, monkeypatch ):
    _no_external( monkeypatch )
    _stage_bytes( repo, "src/pkg/cr.py", b"x = 1\r" + CR_SOURCE )
    rc, lines = _blocking( repo )
    assert rc == gate.REFUSAL_EXIT and not [ ln for ln in lines if "GATE CRASHED" in ln ]
    assert [ ln.split( "; " )[ 0 : 2 ] for ln in _refused( lines ) ] == [ [ f"[doc-lint] REFUSED src/pkg/cr.py:6: {CAPS}", "line: 'This is NOT fine.'" ] ]
    assert "[doc-lint] swept scope: 1 files checked, 1 docstrings checked, 1 findings, 0 waivers honoured, 0 unparsed, 0 undecodable" in lines


def test_a_waiver_on_a_line_that_ends_in_a_bare_carriage_return_is_honoured_in_both_scopes( repo, monkeypatch ):
    _no_external( monkeypatch )
    waived = _doc( "This is NOT fine. doc-lint: waive caps -- quoting a log line" ).replace( "\n", "\r" )
    _stage_bytes( repo, "src/pkg/cr.py", waived.encode( "utf-8" ) )
    rc, lines = _blocking( repo )
    assert rc == 0 and "[doc-lint] swept scope: 1 files checked, 1 docstrings checked, 1 findings, 1 waivers honoured, 0 unparsed, 0 undecodable" in lines
    assert counts.file_count( "src/tests/t.py", waived, str( repo ) ) == counts.FileCount( 0, [], 1 )
    result = counts.file_count( "src/tests/t.py", CR_SOURCE.decode( "utf-8" ), str( repo ) )
    assert ( result.count, result.waivers, [ ( f.line, f.rule ) for f in result.findings ] ) == ( 1, 0, [ ( 5, "caps" ) ] )
    _git( repo, "reset", "-q" )
    _stage_bytes( repo, "src/lupin_mcp/cr.py", waived.encode( "utf-8" ) )
    rc, lines = _blocking( repo )
    assert rc == 0 and "[doc-lint] 0 findings on staged lines (blocking)" in lines and not [ ln for ln in lines if "caps" in ln ]


def test_git_and_the_parser_number_a_carriage_return_file_differently_so_every_line_of_it_counts_as_touched( repo, monkeypatch ):
    _no_external( monkeypatch )
    _stage_bytes( repo, "src/lupin_mcp/cr.py", CR_SOURCE )
    assert cr.changed_line_ranges( str( repo ), None, cached=True ) == { "src/lupin_mcp/cr.py": [ ( 1, 1 ) ] }       # git sees one line; the finding is on the parser's line 5
    rc, lines = _blocking( repo )
    assert rc == gate.REFUSAL_EXIT and _refused( lines ) == [ f"[doc-lint] REFUSED src/lupin_mcp/cr.py:5: {CAPS}" ]


@pytest.mark.parametrize( "ending", [ "\r", " ", " ", "\r\n" ] )
def test_a_script_file_is_counted_with_the_line_ends_its_compiler_counts( repo, ending ):
    marker  = " doc-lint: waive caps -- quoting a log line"
    records = [ { "kind": "file", "file": "a.ts", "ts_version": "5.9.3", "parse_errors": [] },
                { "kind": "line-run", "file": "a.ts", "text": "This is NOT fine." + marker, "start_line": 3, "end_line": 3, "symbol_key": None, "directive": False, "tags": [], "ts_version": "5.9.3", "commented_code": False } ]
    source  = ending.join( [ "const a = 1;", "const b = 2;", "// This is NOT fine." + marker, "" ] )
    assert ts_counts.count_records( "a.ts", records, source, str( repo ) ) == counts.FileCount( 0, [], 1 )
    records[ 1 ][ "start_line" ] = 9                                                           # a line the text does not reach waives nothing and raises nothing
    assert ts_counts.count_records( "a.ts", records, source, str( repo ) ).count == 1


# ---- a staged entry that is not a file ------------------------------------------------------------

def _gitlink( repo, rel ):
    _git( repo, "update-index", "--add", "--cacheinfo", f"160000,{_git( repo, 'rev-parse', 'HEAD' ).strip()},{rel}" )


def _not_checked( rel ):
    return f"[doc-lint] WARNING: {rel} is staged as a gitlink (a submodule entry), which holds a commit and no text, so it was NOT checked"


def test_a_staged_gitlink_named_like_a_page_is_said_to_be_not_checked( repo, monkeypatch ):
    _no_external( monkeypatch )
    _commit( repo, { "docs/a.md": "clean\n" } )
    for rel in ( "z.md", "src/pkg/z.py", "src/tests/z.py", "src/web/z.ts", "vendor/lib" ): _gitlink( repo, rel )
    names, renamed_from, gitlinks = gate.staged_entries( str( repo ) )[ : 3 ]
    assert ( names, renamed_from, gitlinks ) == ( [], {}, [ "src/pkg/z.py", "src/tests/z.py", "src/web/z.ts", "vendor/lib", "z.md" ] )
    assert gate.staged_paths( str( repo ) ) == [] and gate.staged_counted( str( repo ) )[ 0 ] == [] and gate.staged_ts_counted( str( repo ) )[ 0 ] == []
    rc, lines = _blocking( repo )
    assert rc == 0 and [ ln for ln in lines if "gitlink" in ln ] == [ _not_checked( rel ) for rel in ( "src/pkg/z.py", "src/tests/z.py", "src/web/z.ts", "z.md" ) ]
    assert "[doc-lint] swept scope: 0 files checked, 0 docstrings checked, 0 findings, 0 waivers honoured, 0 unparsed, 0 undecodable" in lines


def test_a_page_replaced_by_a_gitlink_is_said_to_be_not_checked_and_a_file_beside_it_is_still_judged( repo, monkeypatch ):
    _no_external( monkeypatch )
    _commit( repo, { "docs/a.md": "clean\n", "docs/p.md": "clean\n" } )
    _git( repo, "update-index", "--cacheinfo", f"160000,{_git( repo, 'rev-parse', 'HEAD' ).strip()},docs/p.md" )
    _stage( repo, { "docs/a.md": SEEDED } )
    assert "T\tdocs/p.md" in _git( repo, "diff", "--cached", "--name-status" )
    rc, lines = _blocking( repo )
    assert rc == gate.REFUSAL_EXIT and _refused( lines ) == [ f"[doc-lint] REFUSED docs/a.md:1: {CAPS}" ] and _not_checked( "docs/p.md" ) in lines


def test_a_link_replaced_by_a_file_is_read_like_any_other_staged_file( repo, monkeypatch ):
    _no_external( monkeypatch )
    _commit( repo, { "docs/a.md": "clean\n" } )
    os.symlink( "a.md", repo / "docs" / "p.md" )
    _git( repo, "add", "-f", "docs/p.md" )
    _git( repo, "commit", "-q", "--no-verify", "-m", "a link" )
    os.remove( repo / "docs" / "p.md" )
    _stage( repo, { "docs/p.md": SEEDED } )
    assert "T\tdocs/p.md" in _git( repo, "diff", "--cached", "--name-status" ) and gate.staged_paths( str( repo ) ) == [ "docs/p.md" ]
    rc, lines = _blocking( repo )
    assert rc == gate.REFUSAL_EXIT and _refused( lines ) == [ f"[doc-lint] REFUSED docs/p.md:1: {CAPS}" ]


# ---- two equal findings on one line -----------------------------------------------------------------

def test_two_equal_docstring_findings_on_one_line_of_a_swept_file_are_two_refusals( repo, monkeypatch ):
    _no_external( monkeypatch )
    _stage( repo, { "src/pkg/a.py": _doc( "This is NOT fine and NOT good." ) } )
    rc, lines = _blocking( repo )
    assert rc == gate.REFUSAL_EXIT and "[doc-lint] 2 refusals, commit REFUSED" in lines
    assert [ ln.split( "; " )[ 0 ] for ln in _refused( lines ) ] == [ f"[doc-lint] REFUSED src/pkg/a.py:5: {CAPS}" ] * 2
    assert "[doc-lint] swept scope: 1 files checked, 1 docstrings checked, 2 findings, 0 waivers honoured, 0 unparsed, 0 undecodable" in lines


# ---- stand-in names that clash or overflow ------------------------------------------------------

def _ts_table( repo ):
    """Commit an empty script count table cut under the repository's own stamp."""
    for rel in ts_counts.STAMP_FILES:
        if not ( repo / rel ).exists(): _stage( repo, { rel: f"stamp file {rel}\n" } )
    _stage( repo, { ts_counts.TABLE_PATH: counts.table_text( {}, ts_counts.rules_stamp( str( repo ) ) ) } )
    _git( repo, "commit", "-q", "--no-verify", "-m", "base" )


def _over( lines ):
    mark = ": 1 findings, the count table allows 0"
    return sorted( ln.split( mark )[ 0 ] for ln in lines if mark in ln )


def _crashed( lines ):
    return [ ln for ln in lines if "GATE CRASHED" in ln ]


@pytest.mark.parametrize( "odd,printed", [
    ( "src/notes/d\udcff.ts/y.ts",       "src/notes/d\\xff.ts/y.ts" ),                              # its old stand-in needed a folder where src/notes/d_.ts is a file
    ( "src/" + "a" * 250 + "\udcff.ts", "src/" + "a" * 250 + "\\xff.ts" ),                          # its old stand-in was two bytes longer than a file name may be
] )
def test_a_script_name_that_is_not_utf8_is_counted_whatever_real_path_or_length_it_comes_with( repo, monkeypatch, odd, printed ):
    _no_external( monkeypatch )
    monkeypatch.setattr( tsdoc_lint, "run_extractor", _lossy_node )
    _ts_table( repo )
    _stage( repo, { "src/notes/d_.ts": TS_ONE, odd: TS_ONE, "docs/p.md": SEEDED } )
    rc, lines = _blocking( repo )
    assert _crashed( lines ) == []
    assert rc == gate.REFUSAL_EXIT and f"[doc-lint] REFUSED docs/p.md:1: {CAPS}" in lines
    assert _over( lines ) == sorted( [ f"[doc-lint] REFUSED {printed}", "[doc-lint] REFUSED src/notes/d_.ts" ] )


# ---- a bare carriage return in a merge resolution and inside a changed line -----------------------

MERGE_PY      = "src/lupin_mcp/m.py"
CR_RESOLUTION = b'def f():\n    """Return it."""\n    return 4\rdef g():\r    """Return one.\r    More text here."""\r    return 1\n'
BARE_NOTE     = f"[doc-lint] {MERGE_PY} holds a bare carriage return, so git does not number its lines as the parser does: no finding in it is let off as merged in"
RUFF_RULES    = [ "ruff:D205:", "ruff:D209:", "ruff:D213:" ]


def _real_ruff_only( repo, monkeypatch ):
    if tr.find_tool( cu.get_project_root(), tr.RUFF_RELATIVE, "ruff", "LUPIN_RUFF" ) is None: pytest.skip( "ruff is not installed in this environment" )
    monkeypatch.setattr( gate, "run_markdownlint", lambda root, paths: ( [], [] ) )
    monkeypatch.setattr( gate, "markdownlint_unnamed", lambda root, paths: [] )
    shutil.copy( os.path.join( cu.get_project_root(), "pyproject.toml" ), repo / "pyproject.toml" )


@pytest.mark.parametrize( "merging", [ False, True ] )
def test_a_merge_lets_off_no_finding_in_a_file_that_holds_a_bare_carriage_return( repo, monkeypatch, merging ):
    _real_ruff_only( repo, monkeypatch )
    body = 'def f():\n    """Return it."""\n    return {}\n'
    _commit( repo, { MERGE_PY: body.format( 0 ) } )
    if merging:
        _git( repo, "checkout", "-q", "-b", "side" )
        _commit( repo, { MERGE_PY: body.format( 2 ) }, "side" )
        _git( repo, "checkout", "-q", "-" )
        _commit( repo, { MERGE_PY: body.format( 1 ) }, "ours" )
        res = subprocess.run( [ "git", "-C", str( repo ), "-c", "user.email=t@t", "-c", "user.name=t", "merge", "side" ], capture_output=True, text=True )
        assert res.returncode != 0 and ( repo / ".git" / "MERGE_HEAD" ).exists()
    _stage_bytes( repo, MERGE_PY, CR_RESOLUTION )
    rc, lines = _blocking( repo )
    assert _crashed( lines ) == [] and not [ ln for ln in lines if "came in with" in ln ]
    assert rc == gate.REFUSAL_EXIT and [ ln.split( " ", 4 )[ 3 ] for ln in _refused( lines ) if " ruff:" in ln ] == RUFF_RULES
    assert ( BARE_NOTE in lines ) == merging


def test_a_merge_still_lets_off_the_findings_of_a_file_without_a_bare_carriage_return( repo, monkeypatch ):
    _real_ruff_only( repo, monkeypatch )
    body = 'def f():\n    """Return it."""\n    return {}\n'
    late = 'def g():\n    """Return one.\n    More text here."""\n    return 1\n'
    _commit( repo, { MERGE_PY: body.format( 0 ) } )
    _git( repo, "checkout", "-q", "-b", "side" )
    _commit( repo, { MERGE_PY: body.format( 2 ) + late }, "side" )
    _git( repo, "checkout", "-q", "-" )
    _commit( repo, { MERGE_PY: body.format( 1 ) }, "ours" )
    res = subprocess.run( [ "git", "-C", str( repo ), "-c", "user.email=t@t", "-c", "user.name=t", "merge", "side" ], capture_output=True, text=True )
    assert res.returncode != 0 and ( repo / ".git" / "MERGE_HEAD" ).exists()
    _stage( repo, { MERGE_PY: body.format( 4 ) + late } )
    rc, lines = _blocking( repo )
    assert rc == 0 and _refused( lines ) == [] and BARE_NOTE not in lines
    assert len( [ ln for ln in lines if " ruff:" in ln and ln.endswith( gate.MERGED_MARK ) ] ) == len( RUFF_RULES )


@pytest.mark.parametrize( "second", [ "A plain line.", "text\rdiff --git a/x b/x", "text\r+++ b/docs/other.md", "text\r@@ -1 +40,3 @@" ] )
def test_a_carriage_return_inside_a_changed_line_ends_no_line_of_the_diff( repo, monkeypatch, second ):
    _no_external( monkeypatch )
    page = [ f"Line {n} is fine." for n in range( 1, 13 ) ]
    _commit( repo, { "docs/p.md": "\n".join( page ) + "\n" } )
    page[ 1 ], page[ 9 ] = second, "This is NOT fine."
    _stage_bytes( repo, "docs/p.md", ( "\n".join( page ) + "\n" ).encode( "utf-8" ) )
    rc, lines = _blocking( repo )
    assert rc == gate.REFUSAL_EXIT and _refused( lines ) == [ f"[doc-lint] REFUSED docs/p.md:10: {CAPS}" ]
    assert cr.changed_line_ranges( str( repo ), None, cached=True ) == { "docs/p.md": [ ( 2, 2 ), ( 10, 10 ) ] }


def test_a_failed_diff_names_the_git_error_as_text( tmp_path ):
    with pytest.raises( RuntimeError, match="^git diff failed: .*(cannot change to|No such file)" ): cr.changed_line_ranges( str( tmp_path / "nowhere" ), None, cached=True )


# ---- a staged file git treats as binary ----------------------------------------------------------

def _binary_line( rel, word="REFUSED" ):
    return f"[doc-lint] {word}: {rel} could NOT be checked because git treats it as binary, so the lines this commit touches in it are not known"


def test_a_staged_page_that_git_treats_as_binary_is_refused_in_blocking_mode_and_named( repo, monkeypatch ):
    _no_external( monkeypatch )
    nul = _page( 101 ).replace( "Line 50 is fine.", "Line 50 is\0 fine." )
    _stage( repo, { CAP_PAGE: nul, "docs/tests/skipped.md": nul, "docs/ok.md": "A clean page.\n" } )
    _stage_bytes( repo, "docs/logo.png", b"\x89PNG\0\0" )
    rc, lines = _blocking( repo )
    assert rc == gate.REFUSAL_EXIT and [ ln for ln in lines if "binary" in ln ] == [ _binary_line( CAP_PAGE ) ]
    assert gate.staged_binary( str( repo ) ) == [ "docs/logo.png", "docs/tests/skipped.md", CAP_PAGE ]
    assert "[doc-lint] 1 checks could not be made, commit REFUSED: each is a REFUSED line above that says what was not checked" in lines
    err = io.StringIO()
    assert gate.main( [ "--repo-root", str( repo ) ], err ) == 0                                    # warn mode names it and lets the commit through
    assert [ ln for ln in err.getvalue().split( "\n" ) if "binary" in ln ] == [ _binary_line( CAP_PAGE, "WARNING" ) ]


def test_the_same_page_without_the_nul_byte_is_refused_for_its_length( repo, monkeypatch ):
    _no_external( monkeypatch )
    _stage( repo, { CAP_PAGE: _page( 101 ) } )
    rc, lines = _blocking( repo )
    assert rc == gate.REFUSAL_EXIT and not [ ln for ln in lines if "binary" in ln ]
    assert _refused( lines ) == [ f"[doc-lint] REFUSED {CAP_PAGE}:1: capability-length: capability page of 101 lines, limit 40" ]


def test_a_page_that_becomes_binary_as_it_moves_is_named_by_its_new_path_and_a_deleted_one_is_not( repo, monkeypatch ):
    _no_external( monkeypatch )
    _commit( repo, { "docs/old.md": _page( 30 ), "docs/gone.md": "A page\0.\n" } )
    _git( repo, "mv", "docs/old.md", "docs/new.md" )
    _git( repo, "rm", "-q", "docs/gone.md" )
    _stage( repo, { "docs/new.md": _page( 30 ) + "One more\0 line.\n" } )
    rc, lines = _blocking( repo )
    assert rc == gate.REFUSAL_EXIT and [ ln for ln in lines if "binary" in ln ] == [ _binary_line( "docs/new.md" ) ]
    assert gate.staged_binary( str( repo ) ) == [ "docs/new.md" ]


def test_the_binary_listing_names_the_git_error_when_it_fails( tmp_path ):
    with pytest.raises( RuntimeError, match="^git diff --cached failed: " ): gate.staged_binary( str( tmp_path / "nowhere" ) )


def test_a_staged_python_file_that_git_treats_as_binary_is_refused_in_blocking_mode_and_named( repo, monkeypatch ):
    _no_external( monkeypatch )
    _stage( repo, { "src/pkg/a.py": 'X = "a\0b"\n', "src/pkg/b.py": "X = 1\n" } )
    rc, lines = _blocking( repo )
    assert _crashed( lines ) == [] and gate.staged_binary( str( repo ) ) == [ "src/pkg/a.py" ]
    assert rc == gate.REFUSAL_EXIT and [ ln for ln in lines if "binary" in ln ] == [ _binary_line( "src/pkg/a.py" ) ]


# ---- a binary file in a warn-only path, and one whose content the commit did not make ------------

BINARY = "A page\0 number {}.\n"
HELD   = "[doc-lint] 1 checks could not be made, commit REFUSED: each is a REFUSED line above that says what was not checked"


def _binary_said( repo ):
    rc, lines = _blocking( repo )
    assert _crashed( lines ) == [] and ( HELD in lines ) == ( rc == gate.REFUSAL_EXIT )
    return rc, [ ln for ln in lines if "binary" in ln ]


def _merge_bringing( repo, ours, theirs ):
    """Leave a merge of the branch side waiting, with its one conflict resolved and staged."""
    _commit( repo, { "docs/ok.md": "Base text.\n", **ours } )
    _git( repo, "checkout", "-q", "-b", "side" )
    _commit( repo, { "docs/ok.md": "Side text.\n", **theirs }, "side" )
    _git( repo, "checkout", "-q", "-" )
    _commit( repo, { "docs/ok.md": "Our text.\n" }, "ours" )
    res = subprocess.run( [ "git", "-C", str( repo ), "-c", "user.email=t@t", "-c", "user.name=t", "merge", "side" ], capture_output=True, text=True )
    assert res.returncode != 0 and ( repo / ".git" / "MERGE_HEAD" ).exists()
    _stage( repo, { "docs/ok.md": "Resolved text.\n" } )


@pytest.mark.parametrize( "rel", [ "history.md", "TODO.md" ] )
def test_a_binary_warn_only_file_is_named_in_a_warning_and_the_same_name_in_a_folder_is_refused( repo, monkeypatch, rel ):
    _no_external( monkeypatch )
    assert gate.is_warn_only( rel ) and not gate.is_warn_only( f"docs/{rel}" )
    _commit( repo, { rel: "A note.\n" } )
    _stage( repo, { rel: "\0A note.\n" } )
    assert gate.staged_binary( str( repo ) ) == [ rel ]
    assert _binary_said( repo ) == ( 0, [ _binary_line( rel, "WARNING" ) ] )
    _stage( repo, { f"docs/{rel}": "\0A note.\n" } )
    rc, said = _binary_said( repo )
    assert rc == gate.REFUSAL_EXIT and sorted( said ) == [ _binary_line( f"docs/{rel}" ), _binary_line( rel, "WARNING" ) ]


@pytest.mark.parametrize( "how,new", [ ( "mode", "docs/b.md" ), ( "move", "docs/c.md" ) ] )
def test_a_committed_binary_page_is_refused_only_when_the_commit_changes_its_content( repo, monkeypatch, how, new ):
    _no_external( monkeypatch )
    _commit( repo, { "docs/b.md": BINARY.format( 1 ) } )
    if how == "mode": _git( repo, "update-index", "--chmod=+x", "docs/b.md" )
    else: _git( repo, "mv", "docs/b.md", "docs/c.md" )
    assert gate.staged_binary( str( repo ) ) == [ new ] and gate.staged_entries( str( repo ) )[ 3 ] == set()
    assert _binary_said( repo ) == ( 0, [ _binary_line( new, "WARNING" ) ] )
    _stage( repo, { new: BINARY.format( 2 ) } )
    assert gate.staged_binary( str( repo ) ) == [ new ] and gate.staged_entries( str( repo ) )[ 3 ] == { new }
    assert _binary_said( repo ) == ( gate.REFUSAL_EXIT, [ _binary_line( new ) ] )


@pytest.mark.parametrize( "ours", [ {}, { "docs/b.md": BINARY.format( 0 ) } ] )
def test_a_merge_that_brings_in_a_binary_page_as_the_other_side_has_it_is_allowed_with_a_warning( repo, monkeypatch, ours ):
    _no_external( monkeypatch )
    _merge_bringing( repo, ours, { "docs/b.md": BINARY.format( 1 ) } )
    incoming = _git( repo, "rev-parse", "MERGE_HEAD" ).strip()
    assert gate.staged_entries( str( repo ) )[ 3 ] == { "docs/b.md", "docs/ok.md" } and gate.staged_entries( str( repo ), incoming )[ 3 ] == { "docs/ok.md" }
    assert _binary_said( repo ) == ( 0, [ _binary_line( "docs/b.md", "WARNING" ) ] )
    _stage( repo, { "docs/b.md": BINARY.format( 3 ) } )                                             # a resolution that is neither side's copy
    assert gate.staged_entries( str( repo ), incoming )[ 3 ] == { "docs/b.md", "docs/ok.md" }
    assert _binary_said( repo ) == ( gate.REFUSAL_EXIT, [ _binary_line( "docs/b.md" ) ] )


def test_a_merge_that_moves_the_incoming_binary_page_is_refused_since_the_other_side_has_it_at_another_path( repo, monkeypatch ):
    _no_external( monkeypatch )
    _merge_bringing( repo, {}, { "docs/b.md": BINARY.format( 1 ) } )
    _git( repo, "mv", "docs/b.md", "docs/c.md" )
    assert gate.staged_entries( str( repo ), _git( repo, "rev-parse", "MERGE_HEAD" ).strip() )[ 3 ] == { "docs/c.md", "docs/ok.md" }
    assert _binary_said( repo ) == ( gate.REFUSAL_EXIT, [ _binary_line( "docs/c.md" ) ] )


def test_a_merge_lets_off_the_finding_of_a_page_that_holds_a_bare_carriage_return( repo, monkeypatch ):
    _no_external( monkeypatch )
    _merge_bringing( repo, {}, { "docs/cr.md": SEEDED + "A line\rwith a bare return in it.\n" } )
    assert gate.BARE_RETURN.search( gate.staged_source( str( repo ), "docs/cr.md" ) )
    rc, lines = _blocking( repo )
    assert rc == 0 and _refused( lines ) == [] and f"[doc-lint] docs/cr.md:1: {CAPS}{gate.MERGED_MARK}" in lines
    assert not [ ln for ln in lines if "bare carriage return" in ln ]


# ---- a file name that starts with a dash, and a tool that fails on what it was given -----------

def test_ruff_is_given_a_name_that_starts_with_a_dash_as_a_name_and_never_as_an_option( monkeypatch, tmp_path ):
    monkeypatch.setenv( "LUPIN_RUFF", str( tmp_path ) )
    calls = []
    def fake( cmd, **kwargs ):
        calls.append( cmd )
        return type( "Done", (), { "returncode": 0, "stdout": "[]", "stderr": "" } )()
    assert tr.run_ruff( "/r", [ "--x.py" ], fake, sources={ "--x.py": "x = 1\n" } ) == ( [], [] )
    assert tr.run_ruff( "/r", [ "--x.py", "a.py" ], fake ) == ( [], [] )
    assert [ call[ 7 : ] for call in calls ] == [ [ "--stdin-filename=--x.py", "-" ], [ "--", "--x.py", "a.py" ] ]


def test_the_real_ruff_judges_a_file_whose_name_starts_with_two_dashes_and_the_file_beside_it( repo, monkeypatch ):
    _real_ruff_only( repo, monkeypatch )
    _stage( repo, { "--x.py": BAD_LAYOUT, "src/lupin_mcp/plain.py": BAD_LAYOUT } )
    rc, lines = _blocking( repo )
    assert not [ ln for ln in lines if "ruff failed" in ln ]
    assert rc == gate.REFUSAL_EXIT and [ ln.split( ":2: ruff:D205" )[ 0 ] for ln in _refused( lines ) if "ruff:D205" in ln ] == [ "[doc-lint] REFUSED --x.py", "[doc-lint] REFUSED src/lupin_mcp/plain.py" ]


@pytest.mark.skipif( shutil.which( "node" ) is None, reason="node is not installed" )
def test_the_real_extractor_counts_a_staged_file_whose_name_starts_with_two_dashes( repo, monkeypatch ):
    _no_external( monkeypatch )
    monkeypatch.setattr( tsdoc_lint, "EXTRACTOR_REL", os.path.join( cu.get_project_root(), "src/scripts/ts_doc_extract.mjs" ) )
    _ts_table( repo )
    _stage( repo, { "--x.ts": "/**\n * This is NOT fine.\n */\nexport const x = 1;\n", "docs/p.md": SEEDED } )
    rc, lines = _blocking( repo )
    assert _crashed( lines ) == []
    assert rc == gate.REFUSAL_EXIT and _over( lines ) == [ "[doc-lint] REFUSED --x.ts" ] and f"[doc-lint] REFUSED docs/p.md:1: {CAPS}" in lines


@pytest.mark.parametrize( "tool,var,rel,text", [
    ( "ruff",              "LUPIN_RUFF",         "src/lupin_mcp/a.py", "x = 1\n" ),
    ( "markdownlint-cli2", "LUPIN_MARKDOWNLINT", "docs/a.md",          "A clean page.\n" ),
] )
def test_a_tool_that_fails_on_the_files_it_was_given_refuses_the_commit_in_blocking_mode( repo, monkeypatch, tmp_path, tool, var, rel, text ):
    stub = tmp_path / tool
    stub.write_text( "#!/bin/sh\necho 'unexpected argument' >&2\nexit 2\n", encoding="utf-8" )
    os.chmod( stub, 0o755 )
    monkeypatch.setenv( var, str( stub ) )
    _stage( repo, { rel: text } )
    said = f"{tool} failed (exit 2), SKIPPED: unexpected argument"
    rc, lines = _blocking( repo )
    assert rc == gate.REFUSAL_EXIT and f"[doc-lint] REFUSED: {said}" in lines and f"[doc-lint] WARNING: {said}" not in lines
    assert "[doc-lint] 1 checks could not be made, commit REFUSED: each is a REFUSED line above that says what was not checked" in lines
    err = io.StringIO()
    assert gate.main( [ "--repo-root", str( repo ) ], err ) == 0                                    # warn mode says so and lets the commit through
    assert f"[doc-lint] WARNING: {said}" in err.getvalue().split( "\n" ) and "REFUSED" not in err.getvalue()
