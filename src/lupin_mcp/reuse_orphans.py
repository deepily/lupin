"""
List open spend-ledger runs whose process is gone; close them on a confirmation.

A lookup closes its run in a finally block. A seat killed, reaped or cleared mid-lookup never gets there.
Its run then holds its whole ceiling against the account until somebody closes it (plan section 12.3, the orphaned-run step).
The view lists each open run older than a cutoff whose process id, kept in the run name, has no /proc entry.
The command closes those runs only when it is given the name of the person who confirmed.
Nothing here sends anything, and nothing runs a model.

Limits, so a reader does not take the list for more than it is:
    - /proc answers only for processes on this host, so a run begun on another host would look dead. The fleet runs on one host.
    - a recycled process id makes a dead run look alive, so that run is never listed. The list can miss a run; it does not name a live one.
    - a run whose name carries no process id (a name set by hand through LUPIN_REUSE_JEV_RUN_NAME) is never listed.
"""
import argparse
import datetime
import json
import os
import re
import sys

from cosa.repo.symindex.vector_status import age_hours
from lupin_mcp import reuse_ledger as rl

MIN_AGE_HOURS = 2.0                                           # a lookup normally takes minutes; Cheech may change the number
PID_IN_NAME   = re.compile( r"-\d{4}-\d{2}-\d{2}-(\d+)(?:-|$)" )  # the date, then the process id, as reuse_shadow.sweep_of names a run
PROC_ROOT     = "/proc"
UNREADABLE    = 3                                             # the exit code for a ledger that cannot be read


def pid_of( run ):
    """
    Read the process id out of a run name.

    Requires:
        - run is a string
    Ensures:
        - returns the digits after the date as an int, or None when the name carries no date followed by a number
    """
    found = PID_IN_NAME.search( run )
    return int( found.group( 1 ) ) if found else None


def orphans( ledger, now, min_age_hours=MIN_AGE_HOURS, proc_root=PROC_ROOT ):
    """
    List the open runs older than the cutoff whose process id has no entry under proc_root.

    Requires:
        - ledger is an AccountLedger
        - now is a time zone aware datetime
    Ensures:
        - returns one { run, pid, ceiling, spent, age_hours } dict per orphan, oldest first
        - a run is left out when it is younger than the cutoff, has no readable begin time, names no process id, or its process id is alive
        - writes nothing
    Raises:
        - LedgerUnreadable as the ledger does
    """
    found = []
    for row in ledger.open_runs():
        age, pid = age_hours( row[ "began" ], now ), pid_of( row[ "run" ] )   # age_hours is None for a missing or unreadable stamp
        if age is None or age < min_age_hours or pid is None or os.path.exists( f"{proc_root}/{pid}" ): continue
        found.append( { "run": row[ "run" ], "pid": pid, "ceiling": row[ "ceiling" ], "spent": row[ "spent" ], "age_hours": round( age, 2 ) } )
    return sorted( found, key=lambda o: -o[ "age_hours" ] )


def close_orphans( ledger, found, confirmed_by ):
    """
    Close each orphan, as the person who confirmed.

    Requires:
        - found comes from orphans()
        - confirmed_by is the name of the person who confirmed the close
    Ensures:
        - returns ( closed run names, { run name: why it was skipped } )
        - a run another process closed since the list was made is skipped, not an error
    Raises:
        - ValueError when confirmed_by is empty
    """
    if not confirmed_by: raise ValueError( "a close needs the name of the person who confirmed it" )
    closed, skipped = [], {}
    for o in found:
        try: ledger.close_run( o[ "run" ], by=confirmed_by, why=f"orphaned: pid {o[ 'pid' ]} has no {PROC_ROOT} entry after {o[ 'age_hours' ]} hours open" )
        except ValueError as e:
            skipped[ o[ "run" ] ] = str( e )
        else: closed.append( o[ "run" ] )
    return closed, skipped


def main( argv=None, now=None ):
    """
    List the orphaned runs, and close them when --confirmed-by names a person.

    Ensures:
        - prints one JSON object with the cutoff, the orphans, and the runs closed or skipped
        - without --confirmed-by the ledger is not written
        - returns 0, or 3 when the ledger cannot be read
    """
    ap = argparse.ArgumentParser( description=__doc__.split( "\n\n" )[ 0 ] )
    ap.add_argument( "--ledger", default=None, help="the ledger file; default is the one the current repository uses" )
    ap.add_argument( "--min-age-hours", type=float, default=MIN_AGE_HOURS )
    ap.add_argument( "--confirmed-by", default=None, help="the person who confirmed; with it the listed runs are closed, without it they are only listed" )
    args = ap.parse_args( argv )
    ledger = rl.AccountLedger( args.ledger or rl.ledger_path( os.getcwd() ) )
    now    = now or datetime.datetime.now().astimezone()
    try:
        found = orphans( ledger, now, args.min_age_hours )
        out   = { "min_age_hours": args.min_age_hours, "orphans": found, "closed": [], "skipped": {} }
        if args.confirmed_by: out[ "closed" ], out[ "skipped" ] = close_orphans( ledger, found, args.confirmed_by )
    except rl.LedgerUnreadable as e:
        print( json.dumps( { "error": str( e ) } ) )
        return UNREADABLE
    print( json.dumps( out, indent=2 ) )
    return 0


if __name__ == "__main__": sys.exit( main() )
