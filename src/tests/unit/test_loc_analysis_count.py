#!/usr/bin/env python3
"""
Unit cover for `src/scripts/loc-analysis/count.py` — the git-tracked line-count
and composition analyzer.

WHAT THIS IS, PLAINLY (assigned by Mr Radio, 2026-08-30). count.py is an ANALYSIS
ONE-SHOT that nothing imports. It sat at 0.0% not because it is subtle but because
no test had ever loaded it. It is taken because it is cheap to move a long way —
its classifiers are pure string work over paths and text, the easiest thing in the
repo to pin down — NOT because it earned tests on merit. Read the coverage this
buys as cheap, not as evidence that this is important code.

EXECUTOR: AI — pure functions plus `main()` run against a temp tree with git and
chdir stubbed. No server, no real git, no repo writes. :7999-class.

Run: LUPIN_ROOT="$PWD" .venv/bin/python -m pytest src/tests/unit/test_loc_analysis_count.py -q
"""

import importlib.util
import json
import os
import sys

import pytest

import cosa.utils.util as cu


def _load():
    """
    Load count.py under a UNIQUE module name.

    The directory is `loc-analysis` (a dash), so it is not a package, and the file
    is named `count.py` — generic enough that putting it on sys.path as `count`
    invites exactly the collision src/tests/unit/test_scripts_name_collision_guard.py
    exists to catch. Loading by path under a namespaced key avoids adding one.
    """
    path   = cu.get_project_root() + "/src/scripts/loc-analysis/count.py"
    spec   = importlib.util.spec_from_file_location( "loc_analysis_count_under_test", path )
    module = importlib.util.module_from_spec( spec )
    sys.modules[ spec.name ] = module
    spec.loader.exec_module( module )
    return module


count = _load()


# ── lang_of / ext_of ──────────────────────────────────────────────────────────
@pytest.mark.parametrize( "path,expected", [
    ( "docker/lupin/Dockerfile", "Dockerfile"           ),
    ( "docker/Dockerfile.prod",  "Dockerfile"           ),   # startswith, case-folded
    ( "src/cosa/util.py",        "Python"               ),
    ( "src/static/js/app.ts",    "TypeScript"           ),
    ( "src/conf/lupin-app.ini",  "YAML/INI/config"      ),
    ( "README.md",               "Markdown"             ),
    ( "src/scripts/run.sh",      "Shell"                ),
    ( "src/terraform/main.tf",   "Terraform/HCL"        ),
    ( "LICENSE",                 "Other (no extension)" ),
    ( "weird.zzz",               "Other"                ),
] )
def test_lang_of_classifies_by_basename( path, expected ):
    assert count.lang_of( path ) == expected


def test_ext_of_handles_both_shapes():
    assert count.ext_of( "a/b/c.PY" )    == "py"   # lower-cased
    assert count.ext_of( "a/b/LICENSE" ) == ""     # no dot → empty, never an IndexError


# ── is_test ───────────────────────────────────────────────────────────────────
@pytest.mark.parametrize( "path", [
    "src/tests/unit/x.py", "src/cosa/tests/y.py", "src/a/test_thing.py",
    "src/a/thing_test.py", "src/a/thing.test.ts", "src/a/thing.spec.ts",
    "src/conftest.py", "src/cosa/rest/conftest.py",
] )
def test_is_test_recognises_every_shape( path ):
    assert count.is_test( path ) is True


def test_is_test_is_false_for_ordinary_code():
    assert count.is_test( "src/cosa/rest/queue.py" ) is False


# ── bucket_of: exclusions first, in order ─────────────────────────────────────
@pytest.mark.parametrize( "path,bucket", [
    ( "io/mementos/rio.md",                                  "X1 Agent output (io/)" ),
    ( "src/lupin_app/static/lupin-mobile-test/main.dart.js", "X2 Flutter web build output (vendored)" ),
    ( "src/lupin_app/static/js/vendor/jquery.js",            "X3 Vendored third-party JS" ),
    ( "src/a/thing.min.js",                                  "X3 Vendored third-party JS" ),
    ( "src/a/thing.min.css",                                 "X3 Vendored third-party JS" ),
    ( "package-lock.json",                                   "X4 Lockfiles" ),
    ( "uv.lock",                                             "X4 Lockfiles" ),
    ( "src/docs/fastapi/api.json",                           "X5 Generated API docs (OpenAPI spec + rendered md)" ),
    ( "src/tests/fixtures/golden/x.json",                    "X9 Captured golden snapshots" ),
    ( "src/a/thing.golden.json",                             "X9 Captured golden snapshots" ),
    ( "src/ephemera/notebook.ipynb",                         "X6 Ephemera (archived notebooks / prompt data)" ),
    ( "src/static/logo.png",                                 "X7 Binary assets" ),
    ( "src/conf/data.csv",                                   "X8 Data files (csv/jsonl/tsv)" ),
] )
def test_bucket_of_excludes( path, bucket ):
    assert count.bucket_of( path ) == ( bucket, True )


@pytest.mark.parametrize( "path,bucket", [
    ( "src/rnd/2026.08.30-thing.md", "C R&D / design / history docs" ),
    ( "history.md",                  "C R&D / design / history docs" ),
    ( "src/docs/websocket.md",       "B Documentation" ),
    ( "CLAUDE.md",                   "B Documentation" ),
    ( "src/cosa/rest/notes.md",      "B Documentation" ),   # stray .md in a code dir
    ( "src/tests/unit/test_x.py",    "A2 Tests" ),
    ( "src/cosa/rest/queue.py",      "A1 Application code + config" ),
] )
def test_bucket_of_includes( path, bucket ):
    assert count.bucket_of( path ) == ( bucket, False )


def test_exclusion_beats_classification_because_first_match_wins():
    # an .md under io/ is agent output, NOT documentation — rule ORDER is the contract
    assert count.bucket_of( "io/mementos/rio.md" )[ 1 ] is True


# ── count_python ──────────────────────────────────────────────────────────────
def test_count_python_separates_all_four_kinds():
    src = (
        '"""module docstring"""\n'   # docstring
        "\n"                         # blank
        "# a comment\n"              # comment
        "x = 1\n"                    # code
    )
    assert count.count_python( src ) == ( 1, 1, 1, 1 )


def test_count_python_counts_a_multiline_docstring_by_line():
    code, _comment, doc, _blank = count.count_python( '"""one\ntwo\nthree"""\nx = 1\n' )
    assert doc == 3 and code == 1


def test_count_python_does_not_call_an_assigned_string_a_docstring():
    # a STRING that is not the whole logical statement is code, not documentation
    code, _comment, doc, _blank = count.count_python( 'x = "not a docstring"\n' )
    assert doc == 0 and code == 1


def test_count_python_falls_back_to_the_heuristic_on_unparseable_source():
    # tokenize raises → the comment-prefix fallback, which cannot see docstrings at all
    code, comment, doc, blank = count.count_python( "def broken( :\n# a comment\n\nx = 1\n" )
    assert doc == 0
    assert comment == 1 and blank == 1 and code >= 1


# ── count_cstyle ──────────────────────────────────────────────────────────────
def test_count_cstyle_splits_line_block_and_doc_comments():
    src = (
        "const a = 1;\n"     # code
        "// line comment\n"  # comment
        "/** jsdoc\n"        # doc — block opens
        " * more\n"          # doc — inside
        " */\n"              # doc — closes
        "/* plain\n"         # comment — block opens
        " */\n"              # comment — closes
        "\n"                 # blank
    )
    code, comment, doc, blank = count.count_cstyle( src )
    assert ( code, doc, blank ) == ( 1, 3, 1 )
    assert comment == 3      # the // line plus the two-line plain block


def test_count_cstyle_handles_a_block_that_opens_and_closes_on_one_line():
    assert count.count_cstyle( "/* one liner */\nconst a = 1;\n" ) == ( 1, 1, 0, 0 )


# ── count_hash_style / count_generic ──────────────────────────────────────────
def test_count_hash_style_accepts_all_three_comment_markers():
    assert count.count_hash_style( "# hash\n; semi\n-- dash\nkey = v\n\n" ) == ( 1, 3, 0, 1 )


def test_count_generic_only_splits_blank_from_not_blank():
    assert count.count_generic( "text\n\nmore\n" ) == ( 2, 0, 0, 1 )


# ── main(), against a temp tree with git and chdir stubbed ────────────────────
def _stub_scan( module, monkeypatch, tmp_path, tracked_bytes, out_path ):
    """
    Point main() at `tmp_path` with `git ls-files` answering `tracked_bytes`.

    `module.os` IS the stdlib `os`, so a stub that itself calls `os.chdir` patches
    the very function it then calls and recurses until the stack ends. pytest's own
    `monkeypatch.chdir` does the move (and undoes it); main()'s chdir to its
    hardcoded REPO is neutralised to a no-op so it cannot walk back out.
    """
    class _Done:
        stdout = tracked_bytes

    monkeypatch.chdir( tmp_path )
    monkeypatch.setattr( module.os,         "chdir", lambda _p: None )
    monkeypatch.setattr( module.subprocess, "run",   lambda *a, **k: _Done() )
    monkeypatch.setattr( module.sys,        "argv",  [ "count.py", str( out_path ) ] )


def test_main_writes_one_row_per_tracked_file( tmp_path, monkeypatch, capsys ):
    """
    One file per COUNTER ARM, because main()'s dispatch on `lang` is where a new
    extension silently lands in the wrong bucket: Python, c-style, hash-style, the
    generic fallback, and a binary that is never read at all.
    """
    ( tmp_path / "src" ).mkdir()
    ( tmp_path / "src" / "app.py"   ).write_text( "# c\nx = 1\n",       encoding="utf-8" )
    ( tmp_path / "src" / "app.ts"   ).write_text( "// c\nconst a = 1;\n", encoding="utf-8" )
    ( tmp_path / "src" / "run.sh"   ).write_text( "# c\necho hi\n",     encoding="utf-8" )
    ( tmp_path / "src" / "notes.md" ).write_text( "# title\n",           encoding="utf-8" )
    ( tmp_path / "logo.png"         ).write_bytes( b"\x89PNG\r\n" )

    out = tmp_path / "rows.json"
    _stub_scan( count, monkeypatch, tmp_path,
                b"src/app.py\x00src/app.ts\x00src/run.sh\x00src/notes.md\x00logo.png\x00", out )

    count.main()

    rows = { r[ "path" ]: r for r in json.load( open( out ) ) }
    assert set( rows ) == { "src/app.py", "src/app.ts", "src/run.sh", "src/notes.md", "logo.png" }

    # each arm ran and split code from comment
    assert ( rows[ "src/app.py" ][ "lang" ], rows[ "src/app.py" ][ "code" ], rows[ "src/app.py" ][ "comment" ] ) == ( "Python",     1, 1 )
    assert ( rows[ "src/app.ts" ][ "lang" ], rows[ "src/app.ts" ][ "code" ], rows[ "src/app.ts" ][ "comment" ] ) == ( "TypeScript", 1, 1 )
    assert ( rows[ "src/run.sh" ][ "lang" ], rows[ "src/run.sh" ][ "code" ], rows[ "src/run.sh" ][ "comment" ] ) == ( "Shell",      1, 1 )
    # the generic fallback does not pretend to find comments
    assert ( rows[ "src/notes.md" ][ "lang" ], rows[ "src/notes.md" ][ "code" ], rows[ "src/notes.md" ][ "comment" ] ) == ( "Markdown", 1, 0 )
    # a binary is never opened: no lines, and excluded from the tiered totals
    assert rows[ "logo.png" ][ "binary" ] is True and rows[ "logo.png" ][ "total" ] == 0
    assert rows[ "logo.png" ][ "excluded" ] is True

    assert "scanned 5 tracked files" in capsys.readouterr().out


def test_main_survives_a_tracked_file_that_is_not_utf8( tmp_path, monkeypatch, capsys ):
    # undecodable bytes under a TEXT extension: the reader must fall back to binary
    # rather than raise and take the whole scan down with it.
    ( tmp_path / "odd.py" ).write_bytes( b"\xff\xfe\x00bad" )
    out = tmp_path / "rows.json"
    _stub_scan( count, monkeypatch, tmp_path, b"odd.py\x00", out )

    count.main()

    row = json.load( open( out ) )[ 0 ]
    assert row[ "binary" ] is True and row[ "total" ] == 0
    capsys.readouterr()


def test_main_tolerates_a_tracked_path_that_is_not_on_disk( tmp_path, monkeypatch, capsys ):
    # git lists it, the working tree does not have it — size 0, no crash.
    out = tmp_path / "rows.json"
    _stub_scan( count, monkeypatch, tmp_path, b"deleted/thing.py\x00", out )

    count.main()

    row = json.load( open( out ) )[ 0 ]
    assert row[ "bytes" ] == 0 and row[ "total" ] == 0
    capsys.readouterr()
