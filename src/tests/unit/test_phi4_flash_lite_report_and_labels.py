#!/usr/bin/env python3
"""
Tests for the two reader-side scripts: the run report and the blind labelling sheet.

WHY THESE EXIST. Both scripts became load-bearing the moment Rick ruled a denominator
and a floor: the report is what turns a paid run into numbers anyone quotes, and the
sheet is what a human will label from. New code under Convention 6 needs 100% lines and
branches, and neither had a single test — a gap I wrote myself.

WHAT THEY GUARD, in order of what would hurt most if it broke:
  1. the report REFUSES — no rate without a denominator, no p-value without a floor,
     and no p-value when the discordant count is under the floor. A reader that quietly
     picks a default publishes someone else's ruling under their name.
  2. latency is computed over FIRED rows only, so an unfired row (microseconds of claim
     counting) cannot drag a median toward zero.
  3. provenance backfill is RECOVERY, not invention: only from the run header, only
     where the field is missing, and nothing at all when there is no header.
  4. the labelling sheet is genuinely BLIND — no arm name, spec key or outcome label
     survives into it, and the answer key lands in a different file.

WHY THEY MOVED OUT OF src/scripts/. They started there and were loaded by path with
importlib, which is exactly the shape Tiffany's B4 finding named: coverage cannot see a
module loaded that way, so Convention 6's number is unobtainable and any `# pragma: no
cover` on it is decorative. Both now live in the package and import normally, so the
number is real — 100% lines and branches, printed rather than asserted.
"""
import json

import pytest

from cosa.research.phi4_flash_lite_study import label_sheet as labels
from cosa.research.phi4_flash_lite_study import report


def _record( arm, row_index, outcome, elapsed, fired=True, delivered=None, body=None, **extra ):
    """
    One replay record, shaped like the harness writes them.

    NOTE the deliberately NEUTRAL delivered text. A first draft used
    f"{arm} delivered {row_index}", and the blinding test caught it immediately — the
    sheet was faithfully reproducing an arm name that the FIXTURE had put in the data.
    A blinding test whose fixture leaks is testing the fixture.
    """
    record = {
        "arm"             : arm,
        "row_index"       : row_index,
        "frozen_index"    : row_index,
        "body"            : body if body is not None else f"source body {row_index}",
        "delivered"       : delivered if delivered is not None else f"delivered text for row {row_index}",
        "elapsed_seconds" : elapsed,
        "spec_key"        : f"dm_tutor/{arm}",
        "snapshot_sha256" : "deadbeef" * 8,
        "meta"            : {
            "tutor_outcome"    : outcome,
            "tutor_fired"      : fired,
            "tutor_enabled"    : True,
            "tutor_words_out"  : 50,
            "tutor_claims_out" : 3,
        },
    }
    record.update( extra )
    return record


def _paired_records( n_blocked_flash=6, n_rows=10 ):
    """n paired rows where flash_lite blocks the first n_blocked_flash and phi_4 blocks none."""
    records = []
    for i in range( n_rows ):
        records.append( _record( "phi_4", i, "rewritten", 3.0 ) )
        records.append( _record( "flash_lite", i,
                                 "fabrication_blocked" if i < n_blocked_flash else "rewritten", 6.0 ) )
    return records


# ── the refusals, which are the whole point ───────────────────────────────────

def test_rate_is_withheld_without_a_denominator( tmp_path, capsys ):
    """No denominator means no rate — and it must SAY so, not just omit it."""
    path = tmp_path / "results.jsonl"
    path.write_text( "\n".join( json.dumps( r ) for r in _paired_records() ) )
    report.main( [ "--results", str( path ) ] )
    out = capsys.readouterr().out
    assert "RATES WITHHELD" in out
    assert "denominator" in out


def test_rate_is_printed_once_a_denominator_is_given( tmp_path, capsys ):
    """The flag must actually DO something — it was parsed and ignored once (93eed7fa)."""
    path = tmp_path / "results.jsonl"
    path.write_text( "\n".join( json.dumps( r ) for r in _paired_records() ) )
    report.main( [ "--results", str( path ), "--denominator", "narrow" ] )
    out = capsys.readouterr().out
    assert "fabrication rate" in out
    assert "RATES WITHHELD" not in out


def test_statistics_are_withheld_without_a_floor( tmp_path, capsys ):
    path = tmp_path / "results.jsonl"
    path.write_text( "\n".join( json.dumps( r ) for r in _paired_records() ) )
    report.main( [ "--results", str( path ) ] )
    assert "STATISTICS WITHHELD" in capsys.readouterr().out


def test_statistics_refuse_under_the_floor( tmp_path, capsys ):
    """Two discordant pairs against a floor of 10 must refuse, not report."""
    path = tmp_path / "results.jsonl"
    path.write_text( "\n".join( json.dumps( r ) for r in _paired_records( n_blocked_flash=2 ) ) )
    report.main( [ "--results", str( path ), "--floor", "10" ] )
    assert "REFUSED" in capsys.readouterr().out


def test_statistics_run_once_the_floor_is_cleared( tmp_path, capsys ):
    """12 discordant pairs against a floor of 10 — now a p-value is licensed."""
    path = tmp_path / "results.jsonl"
    path.write_text( "\n".join( json.dumps( r ) for r in _paired_records( n_blocked_flash=12, n_rows=14 ) ) )
    report.main( [ "--results", str( path ), "--floor", "10", "--denominator", "narrow" ] )
    out = capsys.readouterr().out
    assert "p_value" in out or "p-value" in out.lower()


# ── latency ───────────────────────────────────────────────────────────────────

def test_latency_counts_fired_rows_only():
    """An unfired row is microseconds of claim counting; letting it into the median
    would drag whichever arm fired less toward zero."""
    records = [ _record( "flash_lite", 0, "rewritten", 6.0 ),
                _record( "flash_lite", 1, "under_trigger", 0.0001, fired=False ) ]
    block   = report.latency_block( records )
    assert block[ "flash_lite" ][ "fired_rows" ] == 1
    assert block[ "flash_lite" ][ "median_s" ]   == 6.0


def test_latency_reports_the_ratio_on_both_bases():
    block = report.latency_block( _paired_records() )
    assert block[ "ratio" ][ "median_x" ] == 2.0                # 6.0 / 3.0
    assert block[ "ratio" ][ "total_x" ]  == 2.0


def test_latency_block_handles_an_arm_with_no_fired_rows():
    records = [ _record( "phi_4", 0, "under_trigger", 0.001, fired=False ) ]
    assert report.latency_block( records )[ "phi_4" ] == { "fired_rows": 0 }


def test_percentiles_are_nearest_rank_and_never_interpolate():
    """Every printed figure must be a value that was actually measured."""
    values = [ 1.0, 2.0, 3.0, 10.0 ]
    assert report._percentile( values, 0.90 ) in values
    assert report._percentile( values, 0.99 ) == 10.0
    assert report._percentile( [ 5.0 ], 0.99 ) == 5.0           # n=1: rank clamps to 1


# ── provenance backfill: recovery, never invention ────────────────────────────

def test_backfill_restores_only_missing_fields_from_the_header():
    header  = { "snapshot_sha256": "abc123", "drawn_row_indices": [ 7, 9 ] }
    records = [ { "row_index": 0, "meta": {} }, { "row_index": 1, "meta": {} } ]
    assert report.backfill_provenance( header, records, printer=lambda *a: None ) == 2
    assert records[ 0 ][ "snapshot_sha256" ] == "abc123"
    assert records[ 0 ][ "frozen_index" ]    == 7
    assert records[ 1 ][ "frozen_index" ]    == 9


def test_backfill_does_nothing_without_a_header():
    """No header means no provenance to recover — the pairing is allowed to fail loudly
    rather than be papered over."""
    records = [ { "row_index": 0, "meta": {} } ]
    assert report.backfill_provenance( None, records, printer=lambda *a: None ) == 0
    assert "snapshot_sha256" not in records[ 0 ]


def test_backfill_leaves_existing_values_alone():
    header  = { "snapshot_sha256": "abc123", "drawn_row_indices": [ 7 ] }
    records = [ { "row_index": 0, "snapshot_sha256": "original", "frozen_index": 42, "meta": {} } ]
    report.backfill_provenance( header, records, printer=lambda *a: None )
    assert records[ 0 ][ "snapshot_sha256" ] == "original"
    assert records[ 0 ][ "frozen_index" ]    == 42


def test_backfill_skips_an_out_of_range_row_index():
    header  = { "snapshot_sha256": "abc123", "drawn_row_indices": [ 7 ] }
    records = [ { "row_index": 99, "meta": {} } ]
    report.backfill_provenance( header, records, printer=lambda *a: None )
    assert "frozen_index" not in records[ 0 ]


def test_report_announces_the_backfill( tmp_path, capsys ):
    """A silently repaired file is one nobody can audit."""
    records = [ { k: v for k, v in r.items() if k != "snapshot_sha256" } for r in _paired_records() ]
    header  = { "record_kind": "run_header", "selection": "seeded_random_subset", "seed": 1,
                "sample_size": 10, "frozen_set_rows": 4942, "snapshot_sha256": "abc123",
                "drawn_row_indices": list( range( 10 ) ) }
    path = tmp_path / "results.jsonl"
    path.write_text( "\n".join( json.dumps( r ) for r in [ header ] + records ) )
    report.main( [ "--results", str( path ) ] )
    assert "backfilled provenance" in capsys.readouterr().out


def test_report_says_so_when_the_header_is_absent( tmp_path, capsys ):
    path = tmp_path / "results.jsonl"
    path.write_text( "\n".join( json.dumps( r ) for r in _paired_records() ) )
    report.main( [ "--results", str( path ) ] )
    assert "run header ABSENT" in capsys.readouterr().out


def test_report_handles_a_single_arm( tmp_path, capsys ):
    path = tmp_path / "results.jsonl"
    path.write_text( json.dumps( _record( "phi_4", 0, "rewritten", 3.0 ) ) )
    report.main( [ "--results", str( path ) ] )
    assert "nothing to pair" in capsys.readouterr().out


# ── the labelling sheet: blind, or it is worthless ────────────────────────────

def test_the_sheet_leaks_no_arm_attribution( tmp_path ):
    """A labeller who can see which model wrote a line is not measuring the line."""
    records = _paired_records()
    items, _ = labels.build_items( records, sample_size=5, seed=1 )
    sheet    = labels.render_sheet( items, seed=1 )
    for leak in ( "phi_4", "flash_lite", "dm_tutor", "fabrication_blocked", "rewritten" ):
        assert leak not in sheet


def test_the_key_records_the_arm_behind_each_slot():
    items, key = labels.build_items( _paired_records(), sample_size=5, seed=1 )
    assert len( key ) == len( items ) == 5
    for entry in key.values():
        assert { entry[ "A" ][ "arm" ], entry[ "B" ][ "arm" ] } == { "phi_4", "flash_lite" }


def test_slot_assignment_varies_across_seeds():
    """A stuck shuffle would put one arm in slot A every time and blind nothing. On a
    small draw a run of identical slots is chance (a first 4-item check came out 4/4),
    so this asks across many items."""
    _, key = labels.build_items( _paired_records( n_rows=40 ), sample_size=40, seed=7 )
    in_slot_a = { entry[ "A" ][ "arm" ] for entry in key.values() }
    assert in_slot_a == { "phi_4", "flash_lite" }


def test_identical_deliveries_are_flagged_not_dropped():
    """Agreement is data; dropping it would bias the sample toward disagreement."""
    records = [ _record( "phi_4", 0, "rewritten", 3.0, delivered="same text" ),
                _record( "flash_lite", 0, "rewritten", 6.0, delivered="same text" ) ]
    items, _ = labels.build_items( records, sample_size=1, seed=1 )
    assert items[ 0 ][ "identical" ] is True
    assert "identical text" in labels.render_sheet( items, seed=1 )


def test_a_row_missing_one_arm_is_never_drawn():
    """An unpaired row cannot be labelled as a pair; it is excluded from the draw."""
    records  = _paired_records( n_rows=3 ) + [ _record( "phi_4", 99, "rewritten", 3.0 ) ]
    items, _ = labels.build_items( records, sample_size=10, seed=1 )
    assert { item[ "row_index" ] for item in items } == { 0, 1, 2 }


def test_sample_size_larger_than_the_population_is_clamped():
    items, _ = labels.build_items( _paired_records( n_rows=3 ), sample_size=99, seed=1 )
    assert len( items ) == 3


def test_main_writes_the_sheet_and_the_key_to_separate_files( tmp_path ):
    results = tmp_path / "results.jsonl"
    header  = { "record_kind": "run_header", "seed": 1 }
    results.write_text( "\n".join( json.dumps( r ) for r in [ header ] + _paired_records() ) )
    sheet_path = tmp_path / "sheet.md"
    key_path   = tmp_path / "key.json"
    labels.main( [ "--results", str( results ), "--out-sheet", str( sheet_path ),
                   "--out-key", str( key_path ), "--sample-size", "4", "--seed", "3" ],
                 printer=lambda *a: None )
    assert "phi_4" not in sheet_path.read_text()
    assert "phi_4" in key_path.read_text()                      # the attribution lives ONLY here


def test_missing_delivery_renders_as_nothing_delivered():
    records  = [ _record( "phi_4", 0, "model_failed", 3.0, delivered="" ),
                 _record( "flash_lite", 0, "rewritten", 6.0 ) ]
    items, _ = labels.build_items( records, sample_size=1, seed=1 )
    assert "(nothing delivered)" in labels.render_sheet( items, seed=1 )


def test_build_items_rejects_a_half_paired_row( monkeypatch ):
    """The guard exists so a malformed grouping cannot silently produce a one-sided item."""
    records = _paired_records( n_rows=1 )
    items, _ = labels.build_items( records, sample_size=1, seed=1 )
    assert len( items[ 0 ][ "outputs" ] ) == 2
    with pytest.raises( ValueError ):
        labels.build_items( [], sample_size=0, seed=1 ) if False else _raise_for_unpaired( labels )


def _raise_for_unpaired( module ):
    """Drive build_items' unpaired branch directly: a row map with one arm."""
    records = [ _record( "phi_4", 0, "rewritten", 3.0 ) ]
    original = module.random.Random

    class _AlwaysDraw( original ):
        def sample( self, population, k ):                      # force the incomplete row in
            return [ 0 ]

    module.random.Random = _AlwaysDraw
    try:
        return module.build_items( records, sample_size=1, seed=1 )
    finally:
        module.random.Random = original


if __name__ == "__main__":
    import sys
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
