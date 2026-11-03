"""
The orphaned-run view and command (plan section 12.3, the orphaned-run step).

Every ledger here is a temporary file; nothing touches the shared spend ledger and nothing calls a model.
A process id that cannot exist stands for a dead process, and the test's own process id for a live one.
"""
import datetime
import json
import os

import pytest

from lupin_mcp import reuse_ledger as rl
from lupin_mcp import reuse_orphans as ro

NOW   = datetime.datetime( 2026, 11, 2, 18, 0, 0, tzinfo=datetime.timezone.utc )
DEAD  = 99_999_999                                            # above any pid_max, so /proc never holds it
CEIL  = 60_000_000


def stamp( hours_ago ):
    return ( NOW - datetime.timedelta( hours=hours_ago ) ).strftime( "%Y-%m-%dT%H:%M:%S%z" )


def name( pid, count=1 ):
    return f"shadow-audit-2026-11-02-{pid}-{count}"


def write_rows( ledger, *rows ):
    with ledger.path.open( "a", encoding="utf-8" ) as f:
        for row in rows: f.write( json.dumps( row, sort_keys=True ) + "\n" )


def begin( run, hours_ago, tokens=CEIL ):
    return { "kind": "begin", "run": run, "tokens": tokens, "at": stamp( hours_ago ) }


@pytest.fixture
def ledger( tmp_path ):
    return rl.AccountLedger.create( tmp_path / "ledger.jsonl", 500_000_000, "test", "orphan tests" )


def test_a_dead_run_is_listed_only_after_the_age_cutoff( ledger ):
    write_rows( ledger, begin( name( DEAD, 1 ), 1.5 ), begin( name( DEAD, 2 ), 2.5 ), begin( name( DEAD, 3 ), 2.0 ) )
    found = ro.orphans( ledger, NOW )
    assert [ o[ "run" ] for o in found ] == [ name( DEAD, 2 ), name( DEAD, 3 ) ], "under the cutoff is left out, the cutoff itself is in, oldest first"
    assert found[ 0 ] == { "run": name( DEAD, 2 ), "pid": DEAD, "ceiling": CEIL, "spent": 0, "age_hours": 2.5 }
    assert [ o[ "run" ] for o in ro.orphans( ledger, NOW, min_age_hours=1 ) ] == [ name( DEAD, 2 ), name( DEAD, 3 ), name( DEAD, 1 ) ]


def test_a_run_whose_process_is_alive_is_never_listed( ledger, tmp_path ):
    write_rows( ledger, begin( name( os.getpid() ), 5 ), begin( name( DEAD ), 5 ) )
    assert [ o[ "pid" ] for o in ro.orphans( ledger, NOW ) ] == [ DEAD ]
    fake_proc = tmp_path / "proc"
    ( fake_proc / str( DEAD ) ).mkdir( parents=True )
    assert [ o[ "pid" ] for o in ro.orphans( ledger, NOW, proc_root=str( fake_proc ) ) ] == [ os.getpid() ], "a recycled id makes a dead run look alive, so it is not listed"


def test_a_run_that_cannot_be_judged_is_left_out_not_guessed_at( ledger ):
    write_rows( ledger, begin( "stage-c-by-hand", 9 ),
                { "kind": "begin", "run": name( DEAD, 1 ), "tokens": CEIL },
                { "kind": "begin", "run": name( DEAD, 2 ), "tokens": CEIL, "at": "yesterday" },
                { "kind": "spend", "run": name( DEAD, 3 ), "tokens": 10 } )
    assert ro.orphans( ledger, NOW ) == [], "no process id, no time stamp, a bad time stamp, and a run that never began are all unlisted"


def test_a_closed_run_is_not_open_and_not_listed( ledger ):
    write_rows( ledger, begin( name( DEAD, 1 ), 9 ), begin( name( DEAD, 2 ), 9 ), { "kind": "end", "run": name( DEAD, 1 ) } )
    assert [ r[ "run" ] for r in ledger.open_runs() ] == [ name( DEAD, 2 ) ]
    assert [ o[ "run" ] for o in ro.orphans( ledger, NOW ) ] == [ name( DEAD, 2 ) ]


def test_the_ledger_view_carries_ceiling_spend_and_begin_time( ledger ):
    write_rows( ledger, begin( "a", 3, tokens=70 ), { "kind": "spend", "run": "a", "tokens": 5 }, { "kind": "begin", "run": "b", "tokens": 1 } )
    assert ledger.open_runs() == [ { "run": "a", "ceiling": 70, "spent": 5, "began": stamp( 3 ) }, { "run": "b", "ceiling": 1, "spent": 0, "began": None } ]


def test_pid_reader():
    assert ro.pid_of( "shadow-audit-2026-11-02-4242-7" ) == 4242
    assert ro.pid_of( "shadow-audit-2026-11-02-4242-7-ab12cd34" ) == 4242, "D1's name: prefix, date, pid, count, 8 hex"
    assert ro.pid_of( "lookup-2026-11-02-4242-7-ab12cd34" ) == 4242
    for prefix in ( "lookup", "shadow-audit" ): assert ro.pid_of( rl.make_run_name( prefix, "2026-11-02", 4242 ) ) == 4242, "read back from the real maker's name"
    assert ro.pid_of( rl.make_run_name( "lookup" ) ) == os.getpid()
    assert ro.pid_of( "shadow-audit-2026-11-02-4242" ) == 4242
    assert ro.pid_of( "d3f71441-band-repeat-2026.10.15" ) is None


def test_closing_needs_a_name_and_closes_each_run_with_who_and_why( ledger ):
    write_rows( ledger, begin( name( DEAD, 1 ), 3 ), begin( name( DEAD, 2 ), 4 ) )
    found = ro.orphans( ledger, NOW )
    with pytest.raises( ValueError, match="who confirmed" ):
        ro.close_orphans( ledger, found, "" )
    assert len( ledger.open_runs() ) == 2, "an unconfirmed close wrote nothing"
    closed, skipped = ro.close_orphans( ledger, found, "cheech" )
    assert closed == [ name( DEAD, 2 ), name( DEAD, 1 ) ] and skipped == {}
    ends = [ json.loads( line ) for line in ledger.path.read_text( encoding="utf-8" ).splitlines() if '"end"' in line ]
    assert ends[ 0 ][ "by" ] == "cheech" and f"pid {DEAD} has no /proc entry after 4.0 hours" in ends[ 0 ][ "why" ]
    assert ledger.total() == 0, "the closed runs no longer hold their ceilings"


def test_a_run_closed_since_the_list_was_made_is_skipped_not_an_error( ledger ):
    write_rows( ledger, begin( name( DEAD, 1 ), 3 ), begin( name( DEAD, 2 ), 3 ) )
    found = ro.orphans( ledger, NOW )
    ledger.end_run( name( DEAD, 1 ) )
    closed, skipped = ro.close_orphans( ledger, found, "cheech" )
    assert closed == [ name( DEAD, 2 ) ] and list( skipped ) == [ name( DEAD, 1 ) ] and "already closed" in skipped[ name( DEAD, 1 ) ]
    closed, skipped = ro.close_orphans( ledger, [ { "run": "ghost", "pid": 1, "age_hours": 3.0 } ], "cheech" )
    assert closed == [] and "never began" in skipped[ "ghost" ]


def test_main_lists_without_confirmation_and_closes_with_it( ledger, capsys ):
    write_rows( ledger, begin( name( DEAD ), 3 ), begin( name( os.getpid() ), 3 ) )
    args = [ "--ledger", str( ledger.path ) ]
    assert ro.main( args, now=NOW ) == 0
    listed = json.loads( capsys.readouterr().out )
    assert listed[ "min_age_hours" ] == 2.0 and [ o[ "run" ] for o in listed[ "orphans" ] ] == [ name( DEAD ) ] and listed[ "closed" ] == []
    assert ledger.total() == 2 * CEIL, "not confirmed: nothing was written"
    assert ro.main( args + [ "--confirmed-by", "cheech" ], now=NOW ) == 0
    done = json.loads( capsys.readouterr().out )
    assert done[ "closed" ] == [ name( DEAD ) ] and done[ "skipped" ] == {}
    assert ledger.total() == CEIL, "the live run still holds its ceiling"
    assert ro.main( args + [ "--min-age-hours", "9" ], now=NOW ) == 0
    assert json.loads( capsys.readouterr().out )[ "orphans" ] == []


def test_main_takes_the_default_ledger_and_clock_and_refuses_an_unreadable_ledger( ledger, tmp_path, capsys, monkeypatch ):
    monkeypatch.setattr( rl, "ledger_path", lambda root: ledger.path )
    assert ro.main( [] ) == 0
    assert json.loads( capsys.readouterr().out )[ "orphans" ] == []
    monkeypatch.setattr( rl, "ledger_path", lambda root: tmp_path / "missing.jsonl" )
    assert ro.main( [ "--confirmed-by", "cheech" ] ) == ro.UNREADABLE
    assert "does not exist" in json.loads( capsys.readouterr().out )[ "error" ]
