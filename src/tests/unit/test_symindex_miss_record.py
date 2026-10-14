"""
Unit tests for symindex.miss_record: the fenced miss block and the misses.jsonl export.
"""
import json
import os

import pytest

from cosa.repo.symindex import miss_record as mr

MISS = { "receipt_id": "r-1", "symbol": "pkg.mod.func", "caught_by": "tiberius", "repaired": False }


def row( *misses, extra="" ):
    return { "title": "a miss", "body": "notes\n" + "\n".join( mr.render_block( m ) for m in misses ) + "\n" + extra }


def test_a_rendered_block_parses_back_to_the_same_miss():
    assert mr.parse_block( mr.render_block( MISS ) ) == [ MISS ]


def test_one_miss_always_renders_to_the_same_bytes_with_sorted_keys():
    shuffled = { "repaired": False, "caught_by": "tiberius", "symbol": "pkg.mod.func", "receipt_id": "r-1" }
    assert mr.render_block( shuffled ) == mr.render_block( MISS )
    assert mr.render_block( MISS ).startswith( '```json\n{"caught_by"' )


@pytest.mark.parametrize( "bad", [
    { **MISS, "extra": 1 }, { k: v for k, v in MISS.items() if k != "symbol" }, { **MISS, "symbol": "  " },
    { **MISS, "receipt_id": 7 }, { **MISS, "repaired": "no" }, { **MISS, "repaired": 1 }, { **MISS, "repaired": 0 }, [ MISS ], "text" ] )
def test_render_refuses_a_malformed_miss_naming_the_fields( bad ):
    with pytest.raises( ValueError, match="receipt_id, symbol, caught_by, repaired" ): mr.render_block( bad )


def test_parse_skips_blocks_that_are_not_json_or_not_a_miss_and_keeps_order():
    other = { **MISS, "receipt_id": "r-2" }
    body  = f"{mr.render_block( MISS )}\n```json\n{{not json\n```\n```json\n{{\"a\": 1}}\n```\n{mr.render_block( other )}\n"
    assert mr.parse_block( body ) == [ MISS, other ]


def test_a_body_with_no_block_yields_an_empty_list():
    assert mr.parse_block( "just prose, ```python\nx = 1\n``` here" ) == []


def at( ts, *misses ):
    return { **row( *misses ), "updated_ts": ts }


def test_collect_sorts_and_dedupes_a_pair_to_its_newest_state():
    fixed = { **MISS, "repaired": True }
    later = { **MISS, "receipt_id": "r-0", "symbol": "z" }
    got   = mr.collect( [ at( "2026-10-14T01:00", MISS ), at( "2026-10-14T01:00", later ), at( "2026-10-14T02:00", fixed ) ] )
    assert got == [ later, fixed ]


def test_a_repair_that_was_re_broken_later_reads_as_not_repaired_in_either_list_order():
    fixed  = at( "2026-10-14T01:00", { **MISS, "repaired": True } )
    broken = at( "2026-10-14T02:00", { **MISS, "repaired": False } )
    assert mr.collect( [ fixed, broken ] ) == [ MISS ] and mr.collect( [ broken, fixed ] ) == [ MISS ]


def test_within_one_body_the_last_block_of_a_pair_wins():
    fixed = { **MISS, "repaired": True }
    assert mr.collect( [ row( fixed, MISS ) ] ) == [ MISS ]


def test_a_block_saved_with_crlf_line_endings_is_read():
    body = mr.render_block( MISS ).replace( "\n", "\r\n" )
    assert "\r\n" in body and mr.parse_block( body ) == [ MISS ]


def test_scan_blocks_names_every_block_it_could_not_use():
    body = ( mr.render_block( MISS ) + "\n```json\n{\"receipt_id\": \"r\", \"symbol\": \"s\", \"caught_by\": \"c\", \"repaired\": true, \"extra\": 1}\n```\n"
             "```json\n{oops\n```\n" )
    found, skipped = mr.scan_blocks( body )
    assert found == [ MISS ] and len( skipped ) == 2
    assert skipped[ 0 ].startswith( "not a miss: needs exactly receipt_id" ) and skipped[ 1 ].startswith( "not JSON: " )


def test_collect_with_skips_carries_the_row_title_of_each_skipped_block():
    good, bad = row( MISS ), { "title": "broken row", "body": "```json\n[1]\n```" }
    misses, skipped = mr.collect_with_skips( [ good, bad ] )
    assert misses == [ MISS ] and [ s[ "title" ] for s in skipped ] == [ "broken row" ]


def test_export_report_returns_the_skipped_blocks_beside_the_count( tmp_path ):
    bad = { "title": "broken row", "body": "```json\n{x\n```" }
    got = mr.export_report( [ row( MISS ), bad ], str( tmp_path / "m.jsonl" ) )
    assert got.written == 1 and [ s[ "title" ] for s in got.skipped ] == [ "broken row" ]


def test_an_empty_export_will_not_replace_a_populated_file( tmp_path ):
    path = tmp_path / "m.jsonl"
    path.write_text( "{}\n", encoding="utf-8" )
    with pytest.raises( ValueError, match="refusing to replace a populated" ): mr.export_misses( [], str( path ) )
    assert path.read_text( encoding="utf-8" ) == "{}\n"


def test_an_empty_export_replaces_a_populated_file_when_allowed( tmp_path ):
    path = tmp_path / "m.jsonl"
    path.write_text( "{}\n", encoding="utf-8" )
    assert mr.export_misses( [], str( path ), allow_empty=True ) == 0 and path.read_text( encoding="utf-8" ) == ""


def test_the_exported_file_is_world_readable( tmp_path ):
    path = tmp_path / "m.jsonl"
    mr.export_misses( [ row( MISS ) ], str( path ) )
    assert oct( os.stat( path ).st_mode & 0o777 ) == "0o644"


def test_collect_accepts_a_row_whose_body_is_none():
    assert mr.collect( [ { "title": "t", "body": None }, row( MISS ) ] ) == [ MISS ]


def test_export_writes_one_sorted_line_per_miss_atomically( tmp_path ):
    path = tmp_path / "misses.jsonl"
    path.write_text( "old\n", encoding="utf-8" )
    n = mr.export_misses( [ row( MISS, { **MISS, "receipt_id": "r-0" } ) ], str( path ) )
    lines = path.read_text( encoding="utf-8" ).splitlines()
    assert n == 2 and [ json.loads( l )[ "receipt_id" ] for l in lines ] == [ "r-0", "r-1" ]
    assert sorted( os.listdir( tmp_path ) ) == [ "misses.jsonl" ]


def test_export_with_no_misses_writes_an_empty_file( tmp_path ):
    path = tmp_path / "misses.jsonl"
    assert mr.export_misses( [], str( path ) ) == 0 and path.read_text( encoding="utf-8" ) == ""


def test_a_failed_write_leaves_the_old_file_and_no_temporary( tmp_path, monkeypatch ):
    path = tmp_path / "misses.jsonl"
    path.write_text( "old\n", encoding="utf-8" )
    def boom( src, dst ): raise OSError( "disk full" )
    monkeypatch.setattr( mr.os, "replace", boom )
    with pytest.raises( OSError, match="disk full" ): mr.export_misses( [ row( MISS ) ], str( path ) )
    assert path.read_text( encoding="utf-8" ) == "old\n" and os.listdir( tmp_path ) == [ "misses.jsonl" ]


def test_export_matches_a_literal_expected_line( tmp_path ):
    path = tmp_path / "m.jsonl"
    mr.export_misses( [ row( MISS ) ], str( path ) )
    assert path.read_text( encoding="utf-8" ) == '{"caught_by": "tiberius", "receipt_id": "r-1", "repaired": false, "symbol": "pkg.mod.func"}\n'


def test_export_sorts_the_keys_of_a_hand_written_block( tmp_path ):
    body = '```json\n{"symbol": "s", "repaired": true, "receipt_id": "r", "caught_by": "c"}\n```'
    path = tmp_path / "m.jsonl"
    mr.export_misses( [ { "title": "t", "body": body } ], str( path ) )
    assert path.read_text( encoding="utf-8" ) == '{"caught_by": "c", "receipt_id": "r", "repaired": true, "symbol": "s"}\n'


def test_an_empty_export_may_replace_an_empty_file( tmp_path ):
    path = tmp_path / "m.jsonl"
    path.write_text( "", encoding="utf-8" )
    assert mr.export_misses( [], str( path ) ) == 0
