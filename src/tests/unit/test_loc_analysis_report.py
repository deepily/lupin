#!/usr/bin/env python3
"""
Unit cover for `src/scripts/loc-analysis/report.py` — the markdown renderer over
the rows JSON that count.py writes.

WHAT THIS IS, PLAINLY. The third analysis one-shot in `src/scripts/loc-analysis/`,
alongside count.py and loc_rollup.py, and taken for the same reason: cheap to move
a long way, NOT a claim it earned tests on merit.

⚠️ IT COULD NOT BE IMPORTED AT ALL, WHICH IS WHY IT WAS AT 0.0%. Line 5 was
`rows = json.load( open( sys.argv[1] ) )` at MODULE level, so an import read argv
and parsed a file. Measured before the fix: bare, `IndexError: list index out of
range`; under pytest, whose argv[1] is a test path, `FileNotFoundError`. Its
sibling loc_rollup.py had the same shape one notch milder — that one imported
successfully and merely ran a full git analysis while doing so. The same commit
wraps this in `main( argv=None )` behind a `__main__` guard; the executed body is
byte-identical, proven by dedenting it and diffing against the old module-level
code.

EXECUTOR: AI — pure aggregation over in-memory row dicts plus `main()` against a
temp JSON file. No server, no git, no repo writes. :7999-class.

Run: LUPIN_ROOT="$PWD" .venv/bin/python -m pytest src/tests/unit/test_loc_analysis_report.py -q
"""

import importlib.util
import json
import sys

import pytest

import cosa.utils.util as cu


def _load():
    """Load report.py by path under a namespaced key (see test_loc_analysis_count._load)."""
    path   = cu.get_project_root() + "/src/scripts/loc-analysis/report.py"
    spec   = importlib.util.spec_from_file_location( "loc_analysis_report_under_test", path )
    module = importlib.util.module_from_spec( spec )
    sys.modules[ spec.name ] = module
    spec.loader.exec_module( module )
    return module


report = _load()


def _row( path, bucket, lang, excluded=False, **counts ):
    """One count.py output row, with every numeric field the aggregators read."""
    base = { "total": 10, "code": 6, "comment": 2, "doc": 1, "blank": 1, "bytes": 100 }
    base.update( counts )
    return { "path": path, "bucket": bucket, "lang": lang, "excluded": excluded, **base }


_ROWS = [
    _row( "src/cosa/rest/queue.py", "A1 Application code + config", "Python" ),
    _row( "src/lupin_app/main.py",  "A1 Application code + config", "Python" ),
    _row( "src/tests/unit/t.py",    "A2 Tests",                     "Python" ),
    _row( "src/docs/ws.md",         "B Documentation",              "Markdown" ),
    _row( "src/rnd/design.md",      "C R&D / design / history docs", "Markdown" ),
    _row( "logo.png",               "X7 Binary assets",             "Other", excluded=True,
          total=0, code=0, comment=0, doc=0, blank=0, bytes=900 ),
    _row( "readme",                 "A1 Application code + config", "Other (no extension)" ),
]


# ── the import itself is the first assertion ─────────────────────────────────
def test_importing_the_module_reads_no_argv():
    """
    THE REGRESSION THIS PINS. Before the main() wrap, `_load()` above raised on
    import — IndexError bare, FileNotFoundError under pytest. If someone unwraps
    it, this file cannot even be collected; state the reason explicitly so it is
    on the record rather than implied by a collection error.
    """
    assert callable( report.main )


# ── agg ───────────────────────────────────────────────────────────────────────
def test_agg_sums_every_field_and_counts_files():
    d = report.agg( _ROWS[ :2 ] )
    assert ( d[ "files" ], d[ "total" ], d[ "code" ], d[ "bytes" ] ) == ( 2, 20, 12, 200 )


def test_agg_of_nothing_is_empty_not_a_keyerror():
    # a defaultdict, so an absent tier must read 0 rather than raise
    d = report.agg( [] )
    assert d[ "files" ] == 0 and d[ "total" ] == 0


# ── table ─────────────────────────────────────────────────────────────────────
def test_table_prints_a_row_per_group_plus_a_total( capsys ):
    groups = {
        "Python":   { "files": 2, "total": 20, "code": 12, "comment": 4, "doc": 2, "blank": 2 },
        "Markdown": { "files": 1, "total": 10, "code": 6,  "comment": 2, "doc": 1, "blank": 1 },
    }
    report.table( "My Title", groups )
    out = capsys.readouterr().out

    assert "### My Title" in out
    assert "| Python | 2 | 20 |" in out
    assert "| Markdown | 1 | 10 |" in out
    assert "**TOTAL**" in out and "**3**" in out      # files summed across groups


def test_table_orders_by_the_key_function( capsys ):
    groups = {
        "small": { "files": 1, "total": 5,   "code": 1, "comment": 0, "doc": 0, "blank": 0 },
        "big":   { "files": 1, "total": 500, "code": 1, "comment": 0, "doc": 0, "blank": 0 },
    }
    report.table( "Ordered", groups )                 # default key = -total, biggest first
    body = capsys.readouterr().out
    assert body.index( "| big |" ) < body.index( "| small |" )


def test_table_accepts_a_custom_key( capsys ):
    groups = {
        "b": { "files": 1, "total": 500, "code": 0, "comment": 0, "doc": 0, "blank": 0 },
        "a": { "files": 1, "total": 5,   "code": 0, "comment": 0, "doc": 0, "blank": 0 },
    }
    report.table( "Custom", groups, key=lambda d: d[ "total" ] )   # smallest first
    body = capsys.readouterr().out
    assert body.index( "| a |" ) < body.index( "| b |" )


def test_table_of_no_groups_still_prints_a_total_row( capsys ):
    report.table( "Empty", {} )
    out = capsys.readouterr().out
    assert "### Empty" in out and "**TOTAL**" in out and "**0**" in out


# ── main() ────────────────────────────────────────────────────────────────────
def _run( tmp_path, rows, capsys ):
    path = tmp_path / "rows.json"
    path.write_text( json.dumps( rows ), encoding="utf-8" )
    returned = report.main( [ "report.py", str( path ) ] )
    return returned, capsys.readouterr().out


def test_main_renders_every_section( tmp_path, capsys ):
    returned, out = _run( tmp_path, _ROWS, capsys )

    assert returned == _ROWS
    for heading in ( "## ALL TRACKED", "### Buckets (all)", "### Tier A by language",
                     "### Tier B-only docs by language", "### Tier C-only R&D by language",
                     "### A1 app code+config by language", "### A2 tests by language",
                     "### Excluded buckets", "### Tier A by directory" ):
        assert heading in out


def test_main_tiers_are_cumulative( tmp_path, capsys ):
    _returned, out = _run( tmp_path, _ROWS, capsys )

    # A = 3 included A-bucket rows (two A1 + one A2) plus the extensionless A1 row = 4
    # B adds the one doc, C adds the one R&D doc → 4, 5, 6
    assert "Tier A (code+tests+config): files=4"  in out
    assert "Tier B (A + docs): files=5"           in out
    assert "Tier C (B + R&D/history): files=6"    in out


def test_main_keeps_excluded_rows_out_of_the_tiers_but_in_all_tracked( tmp_path, capsys ):
    _returned, out = _run( tmp_path, _ROWS, capsys )

    assert "files=7" in out                       # ALL TRACKED counts the binary
    assert "X7 Binary assets" in out              # and it appears under Excluded buckets
    assert "Tier C (B + R&D/history): files=6" in out   # but never in a tier


def test_main_groups_tier_a_by_top_two_path_segments( tmp_path, capsys ):
    _returned, out = _run( tmp_path, _ROWS, capsys )

    assert "| src/cosa |"      in out
    assert "| src/lupin_app |" in out
    assert "| (root) |"        in out             # a path with no "/" falls to (root)


def test_main_reads_sys_argv_when_given_none( tmp_path, monkeypatch, capsys ):
    path = tmp_path / "rows.json"
    path.write_text( json.dumps( _ROWS[ :1 ] ), encoding="utf-8" )
    monkeypatch.setattr( report.sys, "argv", [ "report.py", str( path ) ] )

    assert report.main() == _ROWS[ :1 ]
    capsys.readouterr()


def test_main_on_an_empty_rows_file_reports_zero_rather_than_raising( tmp_path, capsys ):
    returned, out = _run( tmp_path, [], capsys )

    assert returned == []
    assert "files=0 lines=0 bytes=0" in out
