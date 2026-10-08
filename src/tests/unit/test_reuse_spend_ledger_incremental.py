"""
The account ledger parses only the rows appended since its last read.

A send used to parse every line twice under the exclusive lock. The file stays the only source of truth.
These tests pin what the cheaper read must still get right.
"""
import json
import os
import subprocess
import sys
import types

import pytest

from lupin_mcp import reuse_ledger as rl

SRC = os.path.dirname( os.path.dirname( os.path.abspath( rl.__file__ ) ) )                        # the src directory this module was loaded from

BEGINNER = """
import sys
from lupin_mcp import reuse_ledger as rl
rl.AccountLedger( sys.argv[ 1 ] ).begin_run( sys.argv[ 2 ], int( sys.argv[ 3 ] ) )
"""


@pytest.fixture
def ledger( tmp_path ):
    return rl.AccountLedger.create( tmp_path / "jev-spend-ledger.jsonl", limit_tokens=100_000, by="test", why="fixture" )


def prefill( led, runs ):
    """Ensures: the file holds `runs` closed runs of three spends each, 5 rows apiece."""
    lines = []
    for k in range( runs ):
        lines.append( json.dumps( { "kind": "begin", "run": f"old-{k}", "tokens": 10 } ) )
        lines += [ json.dumps( { "kind": "spend", "run": f"old-{k}", "tokens": 1 } ) ] * 3
        lines.append( json.dumps( { "kind": "end", "run": f"old-{k}" } ) )
    with led.path.open( "a", encoding="utf-8" ) as f: f.write( "\n".join( lines ) + "\n" )


def count_parses( monkeypatch ):
    """Ensures: the returned list gains one item per json.loads the ledger module makes."""
    calls = []
    def counting( *a, **k ):
        calls.append( 1 )
        return json.loads( *a, **k )
    monkeypatch.setattr( rl, "json", types.SimpleNamespace( loads=counting, dumps=json.dumps ) )
    return calls


def test_a_send_parses_the_rows_added_since_the_last_read_not_the_whole_file( ledger, monkeypatch ):
    prefill( ledger, 600 )                                           # 3,000 rows
    ledger.begin_run( "live", 5_000 )
    ledger.snapshot()                                                # the first read may be a full one
    calls = count_parses( monkeypatch )
    ledger.snapshot()
    ledger.spend( "live", 7 )
    ledger.snapshot()
    ledger.spend( "live", 7 )
    assert len( calls ) <= 8, f"{len( calls )} rows parsed for two sends on a 3,000-row ledger"


def test_the_totals_after_many_sends_are_what_a_full_read_gives( ledger ):
    prefill( ledger, 50 )
    ledger.begin_run( "live", 5_000 )
    for _ in range( 40 ):
        ledger.snapshot()
        ledger.spend( "live", 3 )
    fresh = rl.AccountLedger( ledger.path )                          # a new instance has no memory of the file
    assert ledger.snapshot() == fresh.snapshot() == ( 100_000, 50 * 3 + 5_000 )


def test_a_row_another_process_appended_between_two_sends_is_seen_before_the_next_reservation( ledger ):
    ledger.begin_run( "mine", 10_000 )
    assert ledger.snapshot() == ( 100_000, 10_000 )
    done = subprocess.run( [ sys.executable, "-c", BEGINNER, str( ledger.path ), "theirs", "60000" ], env={ **os.environ, "PYTHONPATH": SRC }, capture_output=True, text=True )
    assert done.returncode == 0, done.stderr
    assert ledger.snapshot() == ( 100_000, 70_000 )
    with pytest.raises( rl.AccountLimitReached ):
        ledger.begin_run( "late", 40_000 )                           # 70,000 held plus 40,000 passes 100,000
    ledger.begin_run( "fits", 30_000 )                               # exactly fills it
    assert ledger.total() == 100_000


def test_a_file_replaced_by_a_shorter_one_is_read_again_from_the_start( ledger, tmp_path ):
    prefill( ledger, 20 )
    ledger.begin_run( "live", 500 )
    assert ledger.total() == 20 * 3 + 500
    other = rl.AccountLedger.create( tmp_path / "other.jsonl", limit_tokens=50_000, by="test", why="replacement" )
    os.replace( other.path, ledger.path )                            # a new inode, far fewer rows
    assert ledger.snapshot() == ( 50_000, 0 )


def test_a_file_rewritten_in_place_to_something_longer_is_read_again_from_the_start( ledger ):
    ledger.begin_run( "live", 500 )
    ledger.spend( "live", 100 )
    assert ledger.total() == 500
    rewritten = [ { "kind": "limit", "tokens": 70_000, "by": "x", "why": "rewritten", "at": "t" } ]
    rewritten += [ { "kind": "begin", "run": f"r{k}", "tokens": 1_000 } for k in range( 20 ) ]
    with ledger.path.open( "r+", encoding="utf-8" ) as f:            # the same inode, and longer than what was read
        f.write( "\n".join( json.dumps( r ) for r in rewritten ) + "\n" )
        f.truncate()
    assert ledger.snapshot() == ( 70_000, 20_000 )


def test_a_torn_last_line_refuses_the_ledger_and_once_repaired_nothing_is_counted_twice( ledger ):
    ledger.begin_run( "live", 1_000 )
    ledger.spend( "live", 40 )
    assert ledger.total() == 1_000
    good = json.dumps( { "kind": "spend", "run": "live", "tokens": 60 } ) + "\n"
    size = ledger.path.stat().st_size
    with ledger.path.open( "a", encoding="utf-8" ) as f: f.write( good + '{"kind": "sp' )     # a crash mid-write
    with pytest.raises( rl.LedgerUnreadable ):
        ledger.total()
    with ledger.path.open( "r+b" ) as f: f.truncate( size + len( good ) )                    # the torn bytes are cut away
    fresh = rl.AccountLedger( ledger.path )
    assert ledger.snapshot() == fresh.snapshot() == ( 100_000, 1_000 )
    ledger.close_run( "live", "test", "closing" )
    assert ledger.total() == 100 == fresh.total()                    # 40 + 60, each counted once


def test_a_bad_line_in_the_middle_keeps_the_rows_before_it_and_names_its_line( ledger ):
    ledger.begin_run( "live", 1_000 )
    ledger.snapshot()
    with ledger.path.open( "a", encoding="utf-8" ) as f: f.write( json.dumps( { "kind": "spend", "run": "live", "tokens": 5 } ) + "\n{not json\n" )
    with pytest.raises( rl.LedgerUnreadable, match="line 4 is not JSON" ):
        ledger.total()
    with pytest.raises( rl.LedgerUnreadable, match="line 4 is not JSON" ):
        ledger.total()                                               # still refused, and the line number has not moved


def test_two_instances_in_one_process_take_turns_and_agree_on_every_total( ledger ):
    other = rl.AccountLedger( ledger.path )
    ledger.begin_run( "a", 30_000 )
    other.begin_run( "b", 30_000 )
    ledger.spend( "a", 11 )
    other.spend( "b", 13 )
    assert ledger.snapshot() == other.snapshot() == ( 100_000, 60_000 )
    with pytest.raises( rl.AccountLimitReached ):
        other.begin_run( "c", 40_001 )


def test_a_line_that_is_not_utf8_refuses_the_ledger_with_its_line_number( ledger ):
    with ledger.path.open( "ab" ) as f: f.write( b"\xff\xfe\n" )
    with pytest.raises( rl.LedgerUnreadable, match="line 2 is not JSON" ):
        ledger.total()


def test_an_empty_file_has_no_limit_row_however_often_it_is_read( tmp_path ):
    path = tmp_path / "empty.jsonl"
    path.write_text( "", encoding="utf-8" )
    led = rl.AccountLedger( path )
    for _ in range( 2 ):
        with pytest.raises( rl.LedgerUnreadable, match="limit" ):
            led.total()


@pytest.fixture
def anchor_blind( monkeypatch ):
    """The anchor check reports the file unchanged, so the guard under test has to stand alone."""
    monkeypatch.setattr( rl.AccountLedger, "_unchanged_before_offset", lambda self, raw: True )


def test_the_shrink_check_alone_reads_a_same_inode_file_cut_shorter_from_the_start( ledger, anchor_blind ):
    prefill( ledger, 20 )
    ledger.begin_run( "live", 500 )
    assert ledger.total() == 20 * 3 + 500
    limit_row = ledger.path.read_text( encoding="utf-8" ).splitlines()[ 0 ]
    inode     = ledger.path.stat().st_ino
    with ledger.path.open( "r+", encoding="utf-8" ) as f:            # the same inode, now far shorter than what was read
        f.write( limit_row + "\n" + json.dumps( { "kind": "begin", "run": "z", "tokens": 7 } ) + "\n" )
        f.truncate()
    assert ledger.path.stat().st_ino == inode
    assert ledger.snapshot() == ( 100_000, 7 )


def test_the_inode_check_alone_reads_a_longer_replacement_file_from_the_start( ledger, tmp_path, anchor_blind ):
    ledger.begin_run( "live", 500 )
    assert ledger.total() == 500
    other = rl.AccountLedger.create( tmp_path / "other.jsonl", limit_tokens=50_000, by="test", why="replacement" )
    prefill( other, 30 )                                             # far longer than what was read
    os.replace( other.path, ledger.path )
    assert ledger.snapshot() == ( 50_000, 30 * 3 )


def test_a_bad_line_stays_refused_and_its_neighbour_is_counted_once_with_the_anchor_blind( ledger, anchor_blind ):
    ledger.begin_run( "live", 1_000 )
    ledger.snapshot()
    good = json.dumps( { "kind": "spend", "run": "live", "tokens": 60 } ) + "\n"
    size = ledger.path.stat().st_size
    with ledger.path.open( "a", encoding="utf-8" ) as f: f.write( good + "{not json\n" )
    for _ in range( 2 ):
        with pytest.raises( rl.LedgerUnreadable, match="line 4 is not JSON" ):
            ledger.total()                                           # a skipped line would make the second read pass
    with ledger.path.open( "r+b" ) as f: f.truncate( size + len( good ) )
    ledger.close_run( "live", "test", "closing" )
    assert ledger.total() == 60
