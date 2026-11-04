"""
Seam: the account ledger file the live runs read, which a person made by hand.

`ledger-init` refuses `--live`, so `AccountLedger.create` did not make the live ledger.
Until now every test read a file that `create` had made.
The fixture is the first seven rows of the live file `jev-spend-ledger.jsonl`, byte for byte.
It holds the limit row, the canary run whole, and the first two spends of an open run.
Nothing here sends a request.
"""
import hashlib
import json
import pathlib
import shutil

import pytest

from lupin_mcp import reuse_ledger as rl

FIXTURE    = pathlib.Path( __file__ ).resolve().parent.parent / "fixtures" / "reuse_e2e" / "jev-spend-ledger-live-prefix-7-rows-20261008.jsonl"
PREFIX_SHA = "56d8add4aa7206080014e74d0be87e3bc81162ad7332a3aec131aed2d9cdb68c"
LIMIT      = 952380952                                                # the live limit row: $40 at the pinned price
HELD       = 2498 + 4_000_000                                         # canary closed at its spend, single1 open at its ceiling


@pytest.fixture
def live( tmp_path ):
    """Ensures: a private copy of the live prefix, so an append never touches the fixture."""
    path = tmp_path / "jev-spend-ledger.jsonl"
    shutil.copyfile( FIXTURE, path )
    return path


def test_the_fixture_is_the_first_seven_rows_of_the_live_file_and_ends_on_a_newline():
    raw = FIXTURE.read_bytes()
    assert hashlib.sha256( raw ).hexdigest() == PREFIX_SHA and raw.endswith( b"\n" )
    kinds = [ json.loads( l )[ "kind" ] for l in raw.decode( "utf-8" ).splitlines() ]
    assert kinds == [ "limit", "begin", "spend", "end", "begin", "spend", "spend" ]


def test_the_live_file_reads_through_the_real_reader_at_the_limit_and_what_it_holds( live ):
    led = rl.AccountLedger( live )
    assert led.snapshot() == ( LIMIT, HELD ) and led.total() == HELD
    assert led.held_by_prefix( "s1-q1-single" ) == 4_000_000 and led.held_by_prefix( "s1-q1-canary" ) == 2498


def test_a_run_is_admitted_up_to_the_room_left_and_refused_one_token_past_it( live ):
    led = rl.AccountLedger( live )
    with pytest.raises( rl.AccountLimitReached ): led.begin_run( "next", LIMIT - HELD + 1 )
    led.begin_run( "next", LIMIT - HELD )
    assert rl.AccountLedger( live ).snapshot() == ( LIMIT, LIMIT )
    with pytest.raises( ValueError, match="already began" ): rl.AccountLedger( live ).begin_run( "s1-q1-canary", 1 )


def test_a_ledger_typed_by_hand_without_a_closing_newline_still_takes_a_run_and_reads_back( tmp_path ):
    path = tmp_path / "hand.jsonl"
    path.write_bytes( b'{"kind":"limit","tokens":1000}' )               # one line, as an editor or echo -n leaves it
    led = rl.AccountLedger( path )
    assert led.snapshot() == ( 1000, 0 )
    led.begin_run( "first", 100 )
    assert rl.AccountLedger( path ).snapshot() == ( 1000, 100 )
