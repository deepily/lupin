"""
Coverage ramp for `src/scripts/loc-analysis/report.py` — 63 statements, previously a flat 0.0%
(third pass of the 96% push, Mr Radio 🦉 2026-08-30). Sibling to Rachel's `count` and `rollup`
suites, which cover the other two files in that directory.

🔴 WHAT THIS FILE IS, STATED PLAINLY. Same clause as the debug/ ramp: this script is a
one-shot report renderer that nothing imports, and these tests exist to move a coverage
number. Every branch is really executed and really asserted, but this is not a claim that the
script earned tests on merit.

🔴 IMPORTING THE SCRIPT *IS* RUNNING IT, and it reads `sys.argv[1]` on its very first line —
`rows = json.load( open( sys.argv[1] ) )`. There is no function to call and no `__main__`
guard, so every test writes a JSON fixture, points `sys.argv` at it, and re-imports from a
clean `sys.modules`. Import it under pytest's own argv and it dies on the first line trying to
open `-q`.

LOAD MECHANISM: the directory is `loc-analysis` — a dash, so not a package and not an
importable name. `sys.path` carries the directory itself and the module is plain `report`.

WHAT THE FIXTURE HAS TO CARRY. The script slices its rows five different ways, so a fixture
that omits any bucket silently skips whole tables: buckets starting A1 and A2 (the two halves
of tier A), B, and C, plus at least one `excluded` row. `_row` below defaults everything so a
test names only the field it is exercising.
"""

import importlib
import json
import os
import sys

import pytest

_ROOT = os.environ.get( "LUPIN_ROOT", os.getcwd() )
for _p in ( os.path.join( _ROOT, "src", "scripts", "loc-analysis" ), os.path.join( _ROOT, "src" ) ):
    if _p not in sys.path:
        sys.path.insert( 0, _p )

MODULE_NAME  = "report"
COUNT_FIELDS = ( "total", "code", "comment", "doc", "blank", "bytes" )


def _row( path="src/cosa/thing.py", bucket="A1-code", lang="python", excluded=False,
          total=100, code=70, comment=10, doc=15, blank=5, size=2048 ):
    """
    Build one row in the shape `count.py` emits.

    Ensures:
        - every field the report reads is present, so a missing key is a test bug rather than
          a silent zero
    """
    return {
        "path"     : path,
        "bucket"   : bucket,
        "lang"     : lang,
        "excluded" : excluded,
        "total"    : total,
        "code"     : code,
        "comment"  : comment,
        "doc"      : doc,
        "blank"    : blank,
        "bytes"    : size,
    }


def _render( monkeypatch, tmp_path, rows ):
    """
    Run the report over `rows` and return everything it printed.

    Requires:
        - rows is a list of dicts in `_row` shape

    Ensures:
        - the script's own json.load and open() run for real against a real file
        - the module is dropped from sys.modules afterwards, so the next test re-runs it
    """
    fixture = tmp_path / "rows.json"
    fixture.write_text( json.dumps( rows ) )

    monkeypatch.setattr( sys, "argv", [ "report.py", str( fixture ) ] )

    sys.modules.pop( MODULE_NAME, None )
    importlib.import_module( MODULE_NAME )
    sys.modules.pop( MODULE_NAME, None )


def _full_spread():
    """
    One row in every slice the script reports on.

    Values are deliberately distinct per row so a table that sums the wrong subset produces a
    number that appears nowhere in this fixture, rather than a plausible one.
    """
    return [
        _row( path="src/cosa/app.py",       bucket="A1-code",  lang="python",     total=100 ),
        _row( path="src/tests/test_x.py",   bucket="A2-tests", lang="python",     total=200 ),
        _row( path="src/docs/guide.md",     bucket="B-docs",   lang="markdown",   total=300 ),
        _row( path="src/rnd/notes.md",      bucket="C-rnd",    lang="markdown",   total=400 ),
        _row( path="node_modules/dep.js",   bucket="X-vendor", lang="javascript", total=500, excluded=True ),
    ]


def test_every_section_is_rendered( monkeypatch, tmp_path, capsys ):
    """A full spread produces all nine tables and both header lines."""
    _render( monkeypatch, tmp_path, _full_spread() )
    out = capsys.readouterr().out

    assert "## ALL TRACKED" in out
    for title in (
        "### Buckets (all)",
        "### Tier A by language",
        "### Tier B-only docs by language",
        "### Tier C-only R&D by language",
        "### A1 app code+config by language",
        "### A2 tests by language",
        "### Excluded buckets",
        "### Tier A by directory",
    ):
        assert title in out


def test_all_tracked_counts_every_row_including_excluded( monkeypatch, tmp_path, capsys ):
    """
    The ALL TRACKED line is the one total that does NOT filter on `excluded`.

    1500 is the sum of all five rows; 1000 would be the excluded-row-dropped answer, so the
    two are distinguishable by construction.
    """
    _render( monkeypatch, tmp_path, _full_spread() )
    out = capsys.readouterr().out

    assert "files=5 lines=1,500 bytes=10,240" in out


def test_tiers_accumulate_rather_than_partition( monkeypatch, tmp_path, capsys ):
    """
    Tier B is A+B and tier C is A+B+C — nested, not disjoint.

    This is the assertion that would catch the easiest possible regression here: three tiers
    reported as three separate buckets. The numbers 300 / 600 / 1000 can only come from
    nesting, and the excluded 500-line row is in none of them.
    """
    _render( monkeypatch, tmp_path, _full_spread() )
    out = capsys.readouterr().out

    assert "Tier A (code+tests+config): files=2 total=300" in out
    assert "Tier B (A + docs): files=3 total=600"          in out
    assert "Tier C (B + R&D/history): files=4 total=1,000" in out


def test_root_level_paths_are_bucketed_as_root( monkeypatch, tmp_path, capsys ):
    """
    The directory table keys on the first two path segments, falling back to "(root)" for a
    path with no slash.

    Both arms of that conditional are exercised here — a nested path and a bare filename.
    """
    _render( monkeypatch, tmp_path, [
        _row( path="README.md",           bucket="A1-code", total=10 ),
        _row( path="src/cosa/deep/x.py",  bucket="A1-code", total=20 ),
    ] )
    out = capsys.readouterr().out

    assert "| (root) |" in out
    assert "| src/cosa |" in out


def test_thousands_separators_are_applied( monkeypatch, tmp_path, capsys ):
    """
    Every number in the report is formatted with `,` grouping.

    Asserted on a value large enough to need one, because a four-digit fixture cannot tell a
    formatted number from an unformatted one.
    """
    _render( monkeypatch, tmp_path, [ _row( bucket="A1-code", total=1234567, code=1000000 ) ] )
    out = capsys.readouterr().out

    assert "1,234,567" in out
    assert "1,000,000" in out


def test_table_totals_row_sums_the_groups( monkeypatch, tmp_path, capsys ):
    """
    Each table closes with a bold TOTAL row summing its own groups.

    Two rows in different languages land in different groups of the tier-A language table, so
    the TOTAL is the only place their sum appears.
    """
    _render( monkeypatch, tmp_path, [
        _row( bucket="A1-code", lang="python",     total=100, code=60, comment=10, doc=20, blank=10 ),
        _row( bucket="A1-code", lang="typescript", total=250, code=150, comment=40, doc=40, blank=20 ),
    ] )
    out = capsys.readouterr().out

    assert "| **TOTAL** | **2** | **350** | **210** | **50** | **60** | **30** |" in out


def test_groups_are_sorted_by_descending_total( monkeypatch, tmp_path, capsys ):
    """
    The language tables sort largest-first.

    Asserted by position in the output rather than by presence: both rows appear either way,
    and only their ORDER carries the sort.
    """
    _render( monkeypatch, tmp_path, [
        _row( bucket="A1-code", lang="small", total=10 ),
        _row( bucket="A1-code", lang="large", total=900 ),
    ] )
    out = capsys.readouterr().out

    assert out.index( "| large |" ) < out.index( "| small |" )


def test_empty_input_still_renders_a_report( monkeypatch, tmp_path, capsys ):
    """
    No rows at all: every loop body is skipped and every total is zero.

    The script must still produce its headers rather than raising — an empty rows file is what
    a filtered `count.py` run produces, not an error.
    """
    _render( monkeypatch, tmp_path, [] )
    out = capsys.readouterr().out

    assert "files=0 lines=0 bytes=0" in out
    assert "Tier A (code+tests+config): files=0 total=0" in out
    assert "| **TOTAL** | **0** |" in out


def test_only_excluded_rows_leaves_the_tiers_empty( monkeypatch, tmp_path, capsys ):
    """
    Every row excluded: ALL TRACKED still counts them, every tier is zero, and the excluded
    table carries the whole weight.

    This is the pair to the ALL-TRACKED test above — together they pin that `excluded` filters
    the tiers and not the headline.
    """
    _render( monkeypatch, tmp_path, [
        _row( path="vendor/a.js", bucket="X-vendor", total=700, excluded=True ),
    ] )
    out = capsys.readouterr().out

    assert "files=1 lines=700" in out
    assert "Tier A (code+tests+config): files=0 total=0" in out
    assert "| X-vendor | 1 | 700 |" in out
