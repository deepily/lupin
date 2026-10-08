"""
The account ledger across processes, its path and its price constant (plan 11.5).

Live runs are separate processes and seats, so a thread lock cannot serialise them. The file lock must.
"""
import fcntl
import json
import os
import subprocess
import sys
import time

import pytest

from lupin_mcp import reuse_ledger as rl

SRC = os.path.dirname( os.path.dirname( os.path.abspath( rl.__file__ ) ) )                        # the src directory this module was loaded from

SPENDER = """
import os, sys, time
from lupin_mcp import reuse_ledger as rl
led, run, n, go = rl.AccountLedger( sys.argv[ 1 ] ), sys.argv[ 2 ], int( sys.argv[ 3 ] ), sys.argv[ 4 ]
while not os.path.exists( go ): time.sleep( 0.005 )
for _ in range( n ): led.spend( run, 7 )
"""

BEGINNER = """
import os, sys, time
from lupin_mcp import reuse_ledger as rl
from lupin_mcp import reuse_ceiling as rc
led, run, ceiling, go = rl.AccountLedger( sys.argv[ 1 ] ), sys.argv[ 2 ], int( sys.argv[ 3 ] ), sys.argv[ 4 ]
while not os.path.exists( go ): time.sleep( 0.005 )
try:
    rc.TokenBudget( 10, ceiling, ledger=led, run=run )
    print( "admitted" )
except rl.AccountLimitReached:
    print( "refused http_calls=0" )
"""


def spawn( code, *args ):
    env = { **os.environ, "PYTHONPATH": os.pathsep.join( p for p in ( SRC, os.environ.get( "PYTHONPATH", "" ) ) if p ) }
    return subprocess.Popen( [ sys.executable, "-c", code, *map( str, args ) ], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True )


@pytest.fixture
def ledger( tmp_path ):
    return rl.AccountLedger.create( tmp_path / "ledger.jsonl", limit_tokens=100_000, by="test", why="fixture" )


def test_two_processes_appending_at_once_lose_no_row( ledger, tmp_path ):
    go = tmp_path / "go"
    ledger.begin_run( "a", 90_000 )
    procs = [ spawn( SPENDER, ledger.path, "a", 60, go ) for _ in range( 2 ) ]
    go.write_text( "go" )
    outs = [ p.communicate( timeout=60 ) for p in procs ]
    assert [ p.returncode for p in procs ] == [ 0, 0 ], outs
    spends = [ json.loads( line ) for line in ledger.path.read_text( encoding="utf-8" ).splitlines() if '"spend"' in line ]
    assert len( spends ) == 120 and sum( r[ "tokens" ] for r in spends ) == 120 * 7


def test_a_process_holding_the_file_lock_makes_another_processs_begin_run_wait( ledger, tmp_path ):
    go = tmp_path / "go"
    go.write_text( "go" )
    with ledger.path.open( "a+", encoding="utf-8" ) as held:
        fcntl.flock( held, fcntl.LOCK_EX )
        child = spawn( BEGINNER, ledger.path, "a", 60_000, go )
        time.sleep( 1.0 )
        waiting = child.poll() is None
        fcntl.flock( held, fcntl.LOCK_UN )
    out = child.communicate( timeout=60 )[ 0 ].strip()
    assert waiting, "begin_run did not wait for the file lock"
    assert out == "admitted"


def test_a_process_holding_the_file_lock_makes_another_processs_spend_wait( ledger, tmp_path ):
    go = tmp_path / "go"
    go.write_text( "go" )
    ledger.begin_run( "a", 10_000 )
    with ledger.path.open( "a+", encoding="utf-8" ) as held:
        fcntl.flock( held, fcntl.LOCK_EX )
        child = spawn( SPENDER, ledger.path, "a", 1, go )
        time.sleep( 1.0 )
        waiting = child.poll() is None
        fcntl.flock( held, fcntl.LOCK_UN )
    child.communicate( timeout=60 )
    assert waiting, "spend did not wait for the file lock"
    assert child.returncode == 0


def test_a_second_process_reading_after_the_first_is_admitted_is_refused_with_zero_http( ledger, tmp_path ):
    go = tmp_path / "go"
    go.write_text( "go" )
    first, second = spawn( BEGINNER, ledger.path, "a", 60_000, go ), None
    assert first.communicate( timeout=60 )[ 0 ].strip() == "admitted"
    second = spawn( BEGINNER, ledger.path, "b", 60_000, go )
    assert second.communicate( timeout=60 )[ 0 ].strip() == "refused http_calls=0"
    assert [ json.loads( line )[ "kind" ] for line in ledger.path.read_text( encoding="utf-8" ).splitlines() ].count( "begin" ) == 1


def test_the_ledger_path_is_the_same_from_a_worktree_and_from_the_main_tree( tmp_path, monkeypatch ):
    main = tmp_path / "projects" / "demo"
    main.mkdir( parents=True )
    subprocess.run( [ "git", "init", "-q", str( main ) ], check=True )
    subprocess.run( [ "git", "-C", str( main ), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "x" ], check=True )
    tree = tmp_path / "projects" / "demo-tree"
    subprocess.run( [ "git", "-C", str( main ), "worktree", "add", "-q", "--detach", str( tree ) ], check=True )
    monkeypatch.delenv( "DEEPILY_DATA_DIR", raising=False )
    monkeypatch.setenv( "LUPIN_ROOT", str( main ) )
    from_main = rl.ledger_path( main )
    monkeypatch.setenv( "LUPIN_ROOT", str( tree ) )
    from_tree = rl.ledger_path( tree )
    assert str( from_main ) == str( from_tree )
    assert from_main.name == "jev-spend-ledger.jsonl" and "projects-data" in from_main.parts and from_main.parent.name == "demo"


def test_the_price_is_written_once_and_the_account_limit_comes_from_it():
    assert rl.PRICE_PER_MILLION_USD == 0.042
    assert rl.ACCOUNT_LIMIT_USD == 40.00
    assert rl.ACCOUNT_LIMIT_TOKENS == rl.usd_to_tokens( rl.ACCOUNT_LIMIT_USD ) == 952_380_952


def test_the_stage_one_ceiling_is_three_dollars_rounded_down_to_a_round_number():
    assert rl.STAGE1_CEILING_TOKENS == 71_000_000
    assert rl.usd_to_tokens( 3.00 ) - 1_000_000 < rl.STAGE1_CEILING_TOKENS <= rl.usd_to_tokens( 3.00 )


def test_the_end_to_end_estimate_of_420_million_tokens_fits_eighteen_dollars():
    assert 420_000_000 <= rl.usd_to_tokens( 18.00 ) < 430_000_000


def test_stage_one_plus_stage_two_plus_end_to_end_fits_the_account_limit_with_room_to_spare():
    """The 11.2 table sums to 487M tokens; the 40 dollar limit holds 952M, so about half is left."""
    total = 56_000_000 + 11_000_000 + 420_000_000
    assert total < rl.ACCOUNT_LIMIT_TOKENS and rl.ACCOUNT_LIMIT_TOKENS - total > 400_000_000
