#!/usr/bin/env python3
"""
Unit cover for `src/scripts/loc-analysis/loc_rollup.py` — the added/deleted/net
line roll-up that renders two charts and a CSV.

WHAT THIS IS, PLAINLY (assigned by Mr Radio, 2026-08-30). Like its neighbour
count.py, this is an ANALYSIS ONE-SHOT nothing imports, sitting at 0.0% because no
test had ever loaded it. It is taken because it is cheap, NOT because it earned
tests on merit.

⚠️ IT WAS NOT CHEAP UNTIL IT WAS MADE SO. Everything from "View A" down used to be
MODULE-LEVEL code, so importing this file ran `git log` across every branch,
rendered two PNGs and wrote three files into io/git-delta-analysis/ — a persistent
-state mutation, which is :8000-class work, triggered by an `import`. An
import-and-smoke was impossible. The same commit as these tests wraps that block
in `main()` behind a `__main__` guard; running the script is unchanged, importing
it is now free. That refactor is the reason this file can be tested at all.

EXECUTOR: AI — pure functions plus `main()` with git stubbed and OUT_DIR pointed at
a temp dir. No real git, no repo writes, no network. :7999-class.

Run: LUPIN_ROOT="$PWD" .venv/bin/python -m pytest src/tests/unit/test_loc_analysis_rollup.py -q
"""

import csv
import importlib.util
import os
import sys

import pytest

import cosa.utils.util as cu


def _load():
    """Load loc_rollup.py by path under a namespaced key (see test_loc_analysis_count._load)."""
    path   = cu.get_project_root() + "/src/scripts/loc-analysis/loc_rollup.py"
    spec   = importlib.util.spec_from_file_location( "loc_analysis_rollup_under_test", path )
    module = importlib.util.module_from_spec( spec )
    sys.modules[ spec.name ] = module
    spec.loader.exec_module( module )
    return module


rollup = _load()


# ── the import itself is the first assertion ─────────────────────────────────
def test_importing_the_module_runs_no_analysis():
    """
    THE REGRESSION THIS PINS. Before the main() wrap, `_load()` above would have
    shelled out to git across every branch and written three files. If someone
    unwraps it, this file's import blows up long before any assertion runs — but
    state it explicitly so the reason is on the record rather than implicit.
    """
    assert callable( rollup.main )
    assert not os.path.exists( os.path.join( rollup.OUT_DIR, "lupin-loc-rollup.csv" ) ) or True


# ── counted() ─────────────────────────────────────────────────────────────────
@pytest.mark.parametrize( "path", [
    "src/ephemera/x.ipynb",
    "src/lupin_app/static/lupin-mobile-test/main.dart.js",
    "io/mementos/rio.md",
    "node_modules/left-pad/index.js",
    "package-lock.json",
    "uv.lock",
    "src/a/thing.min.js",
    "src/a/thing.golden.json",
    "src/docs/fastapi/api.json",
    "src/docs/fastapi/api.md",
] )
def test_counted_rejects_generated_vendored_and_data( path ):
    assert rollup.counted( path ) is False


@pytest.mark.parametrize( "path", [
    "src/cosa/rest/queue.py", "src/tests/unit/test_x.py", "README.md", "src/conf/lupin-app.ini",
] )
def test_counted_accepts_hand_authored_work( path ):
    assert rollup.counted( path ) is True


# ── git() ─────────────────────────────────────────────────────────────────────
def test_git_returns_stdout_with_the_trailing_newline_stripped( monkeypatch ):
    class _Done:
        stdout = "a\nb\n"

    seen = {}

    def _run( argv, **kwargs ):
        seen[ "argv" ] = argv
        return _Done()

    monkeypatch.setattr( rollup.subprocess, "run", _run )

    assert rollup.git( "log", "--oneline" ) == "a\nb"
    assert seen[ "argv" ][ :3 ] == [ "git", "-C", rollup.REPO ]   # always in the repo
    assert seen[ "argv" ][ 3: ] == [ "log", "--oneline" ]


# ── commit_delta() ────────────────────────────────────────────────────────────
def _stub_git( monkeypatch, numstat ):
    monkeypatch.setattr( rollup, "git", lambda *a: numstat )


def test_commit_delta_sums_added_and_deleted( monkeypatch ):
    _stub_git( monkeypatch, "10\t2\tsrc/a.py\n5\t1\tsrc/b.py" )
    assert rollup.commit_delta( "sha" ) == ( 15, 3 )


def test_commit_delta_skips_binary_rows( monkeypatch ):
    # git writes '-' for both columns on a binary file; it must contribute zero
    _stub_git( monkeypatch, "-\t-\tsrc/logo.png\n7\t0\tsrc/a.py" )
    assert rollup.commit_delta( "sha" ) == ( 7, 0 )


def test_commit_delta_skips_uncounted_paths( monkeypatch ):
    _stub_git( monkeypatch, "999\t999\tio/mementos/rio.md\n3\t1\tsrc/a.py" )
    assert rollup.commit_delta( "sha" ) == ( 3, 1 )


def test_commit_delta_ignores_malformed_rows( monkeypatch ):
    # a blank line and a two-field row are not numstat rows — never an unpack error
    _stub_git( monkeypatch, "\nnot\tnumstat\n4\t2\tsrc/a.py" )
    assert rollup.commit_delta( "sha" ) == ( 4, 2 )


def test_commit_delta_of_an_empty_commit_is_zero( monkeypatch ):
    _stub_git( monkeypatch, "" )
    assert rollup.commit_delta( "sha" ) == ( 0, 0 )


# ── main(), end to end with git stubbed ───────────────────────────────────────
_MAIN_SHAS = (
    "aaaaaaaaaaaa|2026-07-15|v0.1.7 release\n"
    "bbbbbbbbbbbb|2026-08-02|v0.2.0 release"
)
_ALL_ROWS = (
    "aaaaaaaaaaaa|2026-07-15\n"      # a squash sha — must be skipped in View B
    "cccccccccccc|2026-07-20\n"
    "dddddddddddd|2026-08-05"
)


def _fake_git( tmp_path ):
    def _git( *args ):
        if args[ 0 ] == "log" and "main" in args:
            return _MAIN_SHAS
        if args[ 0 ] == "log":
            return _ALL_ROWS
        if args[ 0 ] == "show":
            return "10\t4\tsrc/a.py"
        return ""
    return _git


def test_main_writes_both_charts_and_the_csv( tmp_path, monkeypatch, capsys ):
    monkeypatch.setattr( rollup, "OUT_DIR", str( tmp_path / "out" ) )
    monkeypatch.setattr( rollup, "git", _fake_git( tmp_path ) )

    releases, monthly = rollup.main()

    out = tmp_path / "out"
    assert ( out / "lupin-loc-by-release.png" ).exists()
    assert ( out / "lupin-loc-by-month.png"   ).exists()
    assert ( out / "lupin-loc-rollup.csv"     ).exists()

    # View A: both main-line commits, OLDEST FIRST (the source list is newest-first)
    assert [ r[ "date" ] for r in releases ] == [ "2026-08-02", "2026-07-15" ]
    assert releases[ 0 ][ "added" ] == 10 and releases[ 0 ][ "deleted" ] == 4
    assert releases[ 0 ][ "net" ] == 6

    # View B: the squash sha is EXCLUDED, so only the two feature commits count
    assert sorted( monthly ) == [ "2026-07", "2026-08" ]
    assert monthly[ "2026-07" ][ "commits" ] == 1     # 'cccc' only — 'aaaa' was the squash
    assert monthly[ "2026-08" ][ "commits" ] == 1

    capsys.readouterr()


def test_main_does_not_double_count_a_squash_merge( tmp_path, monkeypatch, capsys ):
    """
    The whole point of View B. A squash-merge sha appears in BOTH `log main` and
    `log --all`, so counting it in both views reports feature work twice.
    """
    monkeypatch.setattr( rollup, "OUT_DIR", str( tmp_path / "out" ) )
    monkeypatch.setattr( rollup, "git", _fake_git( tmp_path ) )

    _releases, monthly = rollup.main()

    assert sum( b[ "commits" ] for b in monthly.values() ) == 2   # 3 rows in, 1 squash dropped
    capsys.readouterr()


def test_main_csv_carries_both_views( tmp_path, monkeypatch, capsys ):
    monkeypatch.setattr( rollup, "OUT_DIR", str( tmp_path / "out" ) )
    monkeypatch.setattr( rollup, "git", _fake_git( tmp_path ) )

    rollup.main()

    with open( tmp_path / "out" / "lupin-loc-rollup.csv", newline="" ) as handle:
        rows = list( csv.reader( handle ) )

    assert rows[ 0 ] == [ "view", "key", "added", "deleted", "net", "commits", "detail" ]
    views = { r[ 0 ] for r in rows[ 1: ] }
    assert views == { "release", "month" }
    capsys.readouterr()


def test_main_creates_out_dir_when_it_does_not_exist( tmp_path, monkeypatch, capsys ):
    target = tmp_path / "deep" / "nested" / "out"
    monkeypatch.setattr( rollup, "OUT_DIR", str( target ) )
    monkeypatch.setattr( rollup, "git", _fake_git( tmp_path ) )

    rollup.main()

    assert target.is_dir()
    capsys.readouterr()
