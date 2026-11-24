"""
The read command: a returned batch answer becomes stored gold lines.
"""
import json
import runpy
import sys
import warnings
from datetime import datetime, timezone

import pytest

from cosa.repo.labelling import gold_store as gs
from cosa.repo.labelling import items as it
from cosa.repo.labelling import voice_batches as vb

NOW = datetime( 2026, 11, 25, 9, 0, tzinfo=timezone.utc )


def card( n, stance="yes" ):
    """Return an answer_meaning_card item."""
    return it.make_item( "answer_meaning_card", f"card-{n:03d}", { "card_text": f"Question {n}?", "options": [], "recommendation": None, "answer": "yes", "stance_class": stance } )


@pytest.fixture
def setup( tmp_path ):
    """Return the packet file, the first batch, the batch's headers and a store path."""
    cards = [ card( n, "no" if n == 0 else "yes" ) for n in range( 3 ) ]
    refs  = { c[ "item_id" ]: { "notification_id": f"n-{c[ 'item_id' ]}", "field_key": "answer" } for c in cards }
    packet = { "name": "gold-1", "blind": cards, "disputes": [], "refs": refs }
    pfile  = tmp_path / "packet.json"
    pfile.write_text( json.dumps( packet ), encoding="utf-8" )
    batch  = vb.voice_batches( packet, "s1", "2026-01-01T00:00:00+00:00" )[ 0 ]
    return pfile, batch, tmp_path / "gold.jsonl", tmp_path


def run( setup, answers, *extra, batch_id=None, packet=None ):
    """Run the read command on the answers and return its exit code."""
    pfile, batch, store, tmp = setup
    afile = tmp / "answers.json"
    afile.write_text( json.dumps( answers ), encoding="utf-8" )
    argv = [ "read", "--batch", batch_id or batch[ "batch_id" ], "--packet", str( packet or pfile ), "--seed", "s1", "--answers", str( afile ), "--store", str( store ), *extra ]
    return vb.main( argv, clock=lambda: NOW )


def test_a_two_card_answer_file_stores_two_lines_and_prints_the_counts( setup, capsys ):
    _, batch, store, _ = setup
    h = list( batch[ "headers" ] )
    assert run( setup, { "answers": { h[ 0 ]: "support", h[ 1 ]: "Re-frame.", h[ 2 ]: "no idea" } } ) == 0
    lines = gs.read_gold( store )
    assert [ ( l[ "item_id" ], l[ "relation" ] ) for l in lines ] == [ ( batch[ "headers" ][ h[ 0 ] ], "support" ), ( batch[ "headers" ][ h[ 1 ] ], "re_frame" ) ]
    assert all( l[ "source" ] == "human" and l[ "reader" ] == "rick" and l[ "batch_id" ] == batch[ "batch_id" ] and l[ "ts" ] == NOW.isoformat() for l in lines )
    assert lines[ 0 ][ "notification_id" ] == f"n-{lines[ 0 ][ 'item_id' ]}" and lines[ 0 ][ "field_key" ] == "answer"
    out = json.loads( capsys.readouterr().out )
    assert out[ "written" ] == 2 and [ u[ "header" ] for u in out[ "unlabelled" ] ] == [ h[ 2 ] ] and out[ "unmatched" ] == []
    assert sum( out[ "human_labelled_by_stance" ].values() ) == 2 and out[ "human_labelled_by_stance" ][ "none" ] == 0 and out[ "human_labelled_by_stance" ][ "neither" ] == 0


def test_a_bare_answers_dict_is_read_and_a_reader_source_and_name_are_recorded( setup ):
    _, batch, store, _ = setup
    h = list( batch[ "headers" ] )
    assert run( setup, { h[ 0 ]: "agrees" }, "--source", "ai_reader", "--reader", "reader-a" ) == 0
    only = gs.read_gold( store )
    assert len( only ) == 1 and only[ 0 ][ "source" ] == "ai_reader" and only[ 0 ][ "reader" ] == "reader-a"


def test_the_stance_class_of_each_stored_line_comes_from_its_card( setup ):
    _, batch, store, _ = setup
    assert run( setup, { h: "support" for h in batch[ "headers" ] } ) == 0
    stance = { l[ "item_id" ]: l[ "card_stance" ] for l in gs.read_gold( store ) }
    assert stance == { "card-000": "no", "card-001": "yes", "card-002": "yes" }


def test_an_unknown_batch_id_exits_non_zero_and_writes_nothing( setup, capsys ):
    _, _, store, _ = setup
    assert run( setup, { "answers": {} }, batch_id="ffffffffffff" ) == 2
    assert not store.exists() and "unknown batch id" in capsys.readouterr().err


def test_unreadable_files_and_non_dict_answers_exit_two( setup, tmp_path, capsys ):
    _, _, store, _ = setup
    assert run( setup, [ "agrees" ] ) == 2 and "no dict" in capsys.readouterr().err
    assert run( setup, { "answers": {} }, packet=tmp_path / "missing.json" ) == 2
    bad = tmp_path / "bad.json"; bad.write_text( "{not json", encoding="utf-8" )
    assert run( setup, { "answers": {} }, packet=bad ) == 2
    empty = tmp_path / "empty.json"; empty.write_text( "{}", encoding="utf-8" )
    assert run( setup, { "answers": {} }, packet=empty ) == 2 and not store.exists()


def test_a_card_with_no_ref_stops_the_command_and_writes_nothing( setup, tmp_path, capsys ):
    pfile, _, store, _ = setup
    packet = json.loads( pfile.read_text( encoding="utf-8" ) )
    del packet[ "refs" ][ "card-001" ]
    other = tmp_path / "norefs.json"; other.write_text( json.dumps( packet ), encoding="utf-8" )
    assert run( setup, { "answers": {} }, packet=other ) == 2 and "card-001" in capsys.readouterr().err and not store.exists()
    packet[ "refs" ][ "card-001" ] = { "notification_id": "n" }
    other.write_text( json.dumps( packet ), encoding="utf-8" )
    assert run( setup, { "answers": {} }, packet=other ) == 2
    del packet[ "refs" ]
    other.write_text( json.dumps( packet ), encoding="utf-8" )
    assert run( setup, { "answers": {} }, packet=other ) == 2 and not store.exists()


def test_a_damaged_store_exits_three_and_is_left_alone( setup, capsys ):
    _, batch, store, _ = setup
    store.write_text( '{"torn": ', encoding="utf-8" )
    assert run( setup, { h: "support" for h in batch[ "headers" ] } ) == 3 and store.read_text( encoding="utf-8" ) == '{"torn": '
    assert "refused the write" in capsys.readouterr().err


def test_the_default_store_is_the_one_under_the_project_root( setup, monkeypatch, tmp_path ):
    pfile, batch, _, _ = setup
    monkeypatch.setenv( "LUPIN_ROOT", str( tmp_path / "root" ) )
    afile = tmp_path / "a.json"; afile.write_text( json.dumps( { next( iter( batch[ "headers" ] ) ): "support" } ), encoding="utf-8" )
    assert vb.main( [ "read", "--batch", batch[ "batch_id" ], "--packet", str( pfile ), "--seed", "s1", "--answers", str( afile ) ] ) == 0
    assert len( gs.read_gold( tmp_path / "root" / "io" / "gold-labels" / "answer-meaning-gold.jsonl" ) ) == 1


def test_running_the_module_as_a_script_exits_with_the_command_code( setup, monkeypatch, tmp_path ):
    pfile, batch, store, _ = setup
    afile = tmp_path / "a.json"; afile.write_text( json.dumps( { "answers": {} } ), encoding="utf-8" )
    monkeypatch.setattr( sys, "argv", [ "voice_batches", "read", "--batch", "nope", "--packet", str( pfile ), "--seed", "s1", "--answers", str( afile ), "--store", str( store ) ] )
    with warnings.catch_warnings():
        warnings.simplefilter( "ignore" )
        with pytest.raises( SystemExit ) as e: runpy.run_module( "cosa.repo.labelling.voice_batches", run_name="__main__" )
    assert e.value.code == 2


def test_the_default_clock_gives_an_aware_time( setup ):
    pfile, batch, store, tmp = setup
    afile = tmp / "a.json"; afile.write_text( json.dumps( { next( iter( batch[ "headers" ] ) ): "support" } ), encoding="utf-8" )
    assert vb.main( [ "read", "--batch", batch[ "batch_id" ], "--packet", str( pfile ), "--seed", "s1", "--answers", str( afile ), "--store", str( store ) ] ) == 0
    assert datetime.fromisoformat( gs.read_gold( store )[ 0 ][ "ts" ] ).tzinfo is not None
