"""
The gold-label store: append-only lines, settled labels derived on read.
"""
import json
import multiprocessing
import fcntl

import pytest

from cosa.repo.labelling import errors as er
from cosa.repo.labelling import gold_store as gs


def line( item="c1", source="human", reader="rick", relation="support", stance="yes", **over ):
    """Return one gold line."""
    return { "item_id": item, "notification_id": f"n-{item}", "field_key": "answer", "relation": relation, "card_stance": stance,
             "source": source, "reader": reader, "batch_id": "b1", "ts": "2026-11-24T10:00:00+00:00", **over }


def code_of( fn, *args ):
    """Return the code of the LabellingError that fn raises."""
    with pytest.raises( er.LabellingError ) as e: fn( *args )
    return e.value.code


def test_a_line_round_trips_and_an_absent_or_empty_store_reads_as_nothing( tmp_path ):
    path = tmp_path / "sub" / "gold.jsonl"
    assert gs.read_gold( path ) == []
    assert gs.append_gold( path, [ line( "c1" ), line( "c2", relation="dissent" ) ] ) == 2
    assert gs.read_gold( path ) == [ line( "c1" ), line( "c2", relation="dissent" ) ]
    path.write_text( "", encoding="utf-8" )
    assert gs.read_gold( path ) == []


def test_a_second_line_for_one_item_replaces_the_first_on_read_and_the_first_stays_on_disk( tmp_path ):
    path = tmp_path / "gold.jsonl"
    gs.append_gold( path, [ line( relation="support" ) ] )
    gs.append_gold( path, [ line( relation="dissent", ts="2026-11-24T11:00:00+00:00" ) ] )
    everything = gs.read_gold( path )
    assert [ l[ "relation" ] for l in everything ] == [ "support", "dissent" ] and len( path.read_text( encoding="utf-8" ).splitlines() ) == 2
    assert [ l[ "relation" ] for l in gs.latest_lines( everything ) ] == [ "dissent" ]
    assert len( gs.latest_lines( [ line( reader="a", source="ai_reader" ), line( reader="b", source="ai_reader" ), line() ] ) ) == 3


def test_each_bad_line_is_refused_and_nothing_is_written( tmp_path ):
    path = tmp_path / "gold.jsonl"
    extra = line(); extra[ "forecast" ] = "x"
    short = line(); del short[ "batch_id" ]
    for bad in ( line( source="model" ), line( relation="maybe" ), line( stance="maybe" ), line( reader="" ), line( ts=5 ), extra, short, "text", None ):
        assert code_of( gs.append_gold, path, [ line( "ok" ), bad ] ) == "BAD_LABEL"
    assert not path.exists() or path.read_text( encoding="utf-8" ) == ""


def test_a_torn_last_line_or_a_broken_line_is_refused_loudly_never_skipped( tmp_path ):
    path = tmp_path / "gold.jsonl"
    gs.append_gold( path, [ line( "c1" ) ] )
    torn = path.read_text( encoding="utf-8" ) + json.dumps( line( "c2" ) )[ :30 ]
    path.write_text( torn, encoding="utf-8" )
    assert code_of( gs.read_gold, path ) == "BAD_LABEL" and code_of( gs.append_gold, path, [ line( "c3" ) ] ) == "BAD_LABEL"
    assert path.read_text( encoding="utf-8" ) == torn
    path.write_text( "not json\n", encoding="utf-8" )
    assert code_of( gs.read_gold, path ) == "BAD_LABEL"
    path.write_text( json.dumps( line( relation="maybe" ) ) + "\n", encoding="utf-8" )
    assert code_of( gs.read_gold, path ) == "BAD_LABEL"


def test_two_agreeing_reader_lines_settle_without_rick_and_rick_does_not_overrule_them():
    lines = [ line( "c1", "ai_reader", "a", "agrees", "none" ), line( "c1", "ai_reader", "b", "agrees", "none" ), line( "c1", "human", "rick", "dissent", "none" ) ]
    assert gs.settled( lines ) == { "settled": { "c1": { "relation": "agrees", "card_stance": "none", "settled_by": "readers_agreed" } }, "unsettled": [] }


def test_two_disagreeing_readers_settle_only_on_ricks_line_and_otherwise_the_card_is_unsettled():
    a, b = line( "c1", "ai_reader", "a", "support" ), line( "c1", "ai_reader", "b", "dissent" )
    assert gs.settled( [ a, b ] ) == { "settled": {}, "unsettled": [ "c1" ] }
    got = gs.settled( [ a, b, line( "c1", "human", "rick", "re_frame" ) ] )
    assert got[ "settled" ][ "c1" ] == { "relation": "re_frame", "card_stance": "yes", "settled_by": "rick_tiebreak" } and got[ "unsettled" ] == []
    assert gs.settled( [ line( "c1", "ai_reader", "a", "support" ), line( "c1", "human", "rick", "dissent" ) ] )[ "settled" ][ "c1" ][ "settled_by" ] == "rick_tiebreak"
    assert gs.settled( [ line( "z" ), line( "c9", "ai_reader", "a" ) ] )[ "unsettled" ] == [ "c9" ] and gs.settled( [] ) == { "settled": {}, "unsettled": [] }


def test_a_readers_later_line_replaces_its_earlier_one_in_the_settling():
    first  = [ line( "c1", "ai_reader", "a", "support" ), line( "c1", "ai_reader", "b", "dissent" ) ]
    assert gs.settled( first )[ "unsettled" ] == [ "c1" ]
    assert gs.settled( first + [ line( "c1", "ai_reader", "b", "support", ts="2026-11-24T12:00:00+00:00" ) ] )[ "settled" ][ "c1" ][ "settled_by" ] == "readers_agreed"


def test_human_card_counts_count_distinct_cards_by_stance_and_only_ricks():
    lines = [ line( "c1", stance="no" ), line( "c1", stance="no", relation="dissent" ), line( "c2", stance="neither" ), line( "c3", stance="yes" ),
              line( "c4", "ai_reader", "a", stance="no" ) ]
    assert gs.human_card_counts( lines ) == { "yes": 1, "no": 1, "neither": 1, "none": 0 }
    assert gs.human_card_counts( [] ) == { "yes": 0, "no": 0, "neither": 0, "none": 0 }


def test_the_default_path_sits_under_the_project_root( monkeypatch, tmp_path ):
    monkeypatch.setenv( "LUPIN_ROOT", str( tmp_path ) )
    assert str( gs.default_path() ) == f"{tmp_path}/io/gold-labels/answer-meaning-gold.jsonl"


def test_a_store_held_by_another_process_refuses_the_write_and_changes_nothing( tmp_path ):
    path = tmp_path / "gold.jsonl"
    gs.append_gold( path, [ line( "c1" ) ] )
    before = path.read_bytes()
    code = multiprocessing.get_context( "fork" ).Value( "i", 0 )
    with open( path, "a+b" ) as holder:
        fcntl.flock( holder, fcntl.LOCK_EX )
        ctx = multiprocessing.get_context( "fork" )
        p = ctx.Process( target=_try_append, args=( str( path ), code ) )
        p.start(); p.join( 30 )
    assert p.exitcode == 0 and code.value == 1 and path.read_bytes() == before
    assert gs.append_gold( path, [ line( "c2" ) ] ) == 1


def _try_append( path, code ):
    """Child: append one line and record 1 when the store was locked, 2 on success."""
    try:
        gs.append_gold( path, [ line( "child" ) ] )
        code.value = 2
    except er.LabellingError as e:
        code.value = 1 if e.code == er.STORE_LOCKED else 3


def _write_one( path, n, out ):
    """Child: append one line; record 1 when it was written, 0 when the store was locked."""
    try:
        gs.append_gold( path, [ line( f"w{n}" ) ] )
        out[ n ] = 1
    except er.LabellingError as e:
        out[ n ] = 0 if e.code == er.STORE_LOCKED else -1


def test_writers_started_together_each_write_a_whole_line_or_refuse_to_start( tmp_path ):
    path = tmp_path / "gold.jsonl"
    ctx = multiprocessing.get_context( "fork" )
    out = ctx.Array( "i", [ -9 ] * 6 )
    procs = [ ctx.Process( target=_write_one, args=( str( path ), n, out ) ) for n in range( 6 ) ]
    for p in procs: p.start()
    for p in procs: p.join( 30 )
    assert all( p.exitcode == 0 for p in procs ) and set( out[ : ] ) <= { 0, 1 } and sum( out[ : ] ) >= 1
    assert len( gs.read_gold( path ) ) == sum( out[ : ] )


def test_a_lock_held_on_another_file_description_refuses_the_write_in_this_process( tmp_path ):
    path = tmp_path / "gold.jsonl"
    gs.append_gold( path, [ line( "c1" ) ] )
    with open( path, "a+b" ) as holder:
        fcntl.flock( holder, fcntl.LOCK_EX )
        assert code_of( gs.append_gold, path, [ line( "c2" ) ] ) == "STORE_LOCKED"
    assert [ l[ "item_id" ] for l in gs.read_gold( path ) ] == [ "c1" ]
