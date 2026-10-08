"""
The account spend ledger: one file every live run reads before it starts and each send.

One run's own ceiling cannot see another run's spend, so the account limit lives here. An open run counts
at its ceiling and a closed run at what it spent. A file that cannot be read refuses the run.
Nothing here sends anything.
"""
import contextlib
import fcntl
import json
import math
import pathlib
import time

PRICE_PER_MILLION_USD = 0.042                                 # the pinned input price; output is counted at the same price
ACCOUNT_LIMIT_USD     = 19.31                                 # authorised for the reuse work; changes only by a dated edit in plan 11.5
STAGE1_CEILING_TOKENS = 71_000_000                            # three dollars at the price above, rounded down (plan 11.1)
LEDGER_NAME           = "jev-spend-ledger.jsonl"


class LedgerUnreadable( Exception ):
    """The ledger is missing, damaged, or has no limit row; no run may start or send on it."""


class AccountLimitReached( Exception ):
    """A run's ceiling, added to what the ledger already holds, would pass the account limit."""


def usd_to_tokens( usd, price_per_million=PRICE_PER_MILLION_USD ):
    """
    Turn dollars into whole tokens at the pinned price.

    Requires:
        - usd is a positive number
    Ensures:
        - returns the dollars over the price, in tokens, rounded down
    """
    return math.floor( usd / price_per_million * 1_000_000 )


ACCOUNT_LIMIT_TOKENS = usd_to_tokens( ACCOUNT_LIMIT_USD )


def ledger_path( index_root ):
    """
    Locate the one ledger file of the repository that index_root belongs to.

    Requires:
        - index_root is a repository root, or a worktree of one
    Ensures:
        - returns <fleet data root>/jev-spend-ledger.jsonl, the same path from every worktree and the main tree
        - does not read LUPIN_ROOT and does not create the file
    """
    from lupin_cli.claude_code.hooks.lib.heartbeat_hold import fleet_data_root
    return pathlib.Path( fleet_data_root( pathlib.Path( index_root ) ) ) / LEDGER_NAME


def _whole( value ):
    """Ensures: True for an int of at least zero that is not a bool."""
    return type( value ) is int and value >= 0


class AccountLedger:
    """
    The ledger file, appended under a file lock by every process.

    Requires:
        - the file was made by create(); a missing file is never read as an empty one
    Ensures:
        - each row is one JSON line with a kind: limit, begin, spend or end
        - total() counts an open run at the larger of its ceiling and its spend, a closed run at its spend
        - begin_run() reads and appends under one lock, so two processes cannot both be admitted past the limit
        - the latest limit row is the account limit; earlier ones stay in the file
    Raises:
        - LedgerUnreadable for a missing file, a line that is not a JSON object, a bad row, or no limit row
    """

    def __init__( self, path ):
        self.path = pathlib.Path( path )

    @classmethod
    def create( cls, path, limit_tokens, by, why ):
        """
        Start a new ledger with its first limit.

        Raises:
            - FileExistsError when the file is already there, so a limit is never reset by accident
            - ValueError for a limit that is not a positive integer
        """
        led = cls( path )
        led._check_limit( limit_tokens )
        with led.path.open( "x", encoding="utf-8" ) as f:
            f.write( json.dumps( led._limit_row( limit_tokens, by, why ), sort_keys=True ) + "\n" )
        return led

    @staticmethod
    def _check_limit( tokens ):
        if type( tokens ) is not int or tokens < 1: raise ValueError( f"the account limit must be a positive integer of tokens, got {tokens!r}" )

    @staticmethod
    def _limit_row( tokens, by, why ):
        return { "kind": "limit", "tokens": tokens, "by": by, "why": why, "at": time.strftime( "%Y-%m-%dT%H:%M:%S%z" ) }

    @contextlib.contextmanager
    def _locked( self ):
        """Ensures: yields the open file under an exclusive lock; LedgerUnreadable if it is absent."""
        if not self.path.exists(): raise LedgerUnreadable( f"{self.path} does not exist; create the ledger first" )
        try:
            with self.path.open( "a+", encoding="utf-8" ) as f:
                fcntl.flock( f, fcntl.LOCK_EX )
                try: yield f
                finally: fcntl.flock( f, fcntl.LOCK_UN )
        except OSError as e:
            raise LedgerUnreadable( f"{self.path}: {e}" ) from e

    def _rows( self, f ):
        f.seek( 0 )
        rows = []
        for n, line in enumerate( f.read().splitlines(), 1 ):
            if not line.strip(): continue
            try: row = json.loads( line )
            except ValueError as e: raise LedgerUnreadable( f"line {n} is not JSON" ) from e
            if not isinstance( row, dict ) or row.get( "kind" ) not in ( "limit", "begin", "spend", "end" ):
                raise LedgerUnreadable( f"line {n} is not a ledger row" )
            if row[ "kind" ] != "end" and not _whole( row.get( "tokens" ) ): raise LedgerUnreadable( f"line {n} has no whole token count" )
            if row[ "kind" ] != "limit" and not isinstance( row.get( "run" ), str ): raise LedgerUnreadable( f"line {n} names no run" )
            rows.append( row )
        return rows

    @staticmethod
    def _summary( rows ):
        """Ensures: returns ( limit, total, runs ); LedgerUnreadable when no limit row exists."""
        limits = [ r[ "tokens" ] for r in rows if r[ "kind" ] == "limit" ]
        if not limits: raise LedgerUnreadable( "the ledger has no limit row" )
        runs = {}
        for r in rows:
            if r[ "kind" ] == "limit": continue
            run = runs.setdefault( r[ "run" ], { "ceiling": 0, "spent": 0, "closed": False } )
            if r[ "kind" ] == "begin": run[ "ceiling" ] = r[ "tokens" ]
            elif r[ "kind" ] == "spend": run[ "spent" ] += r[ "tokens" ]
            else: run[ "closed" ] = True
        total = sum( r[ "spent" ] if r[ "closed" ] else max( r[ "ceiling" ], r[ "spent" ] ) for r in runs.values() )
        return limits[ -1 ], total, runs

    def _append( self, f, row ):
        f.write( json.dumps( { **row, "at": time.strftime( "%Y-%m-%dT%H:%M:%S%z" ) }, sort_keys=True ) + "\n" )
        f.flush()

    def snapshot( self ):
        """Ensures: returns ( account limit, total ) as one read."""
        with self._locked() as f: limit, total, _ = self._summary( self._rows( f ) )
        return limit, total

    def total( self ):
        """Ensures: returns the tokens the ledger holds against the account."""
        return self.snapshot()[ 1 ]

    def limit_tokens( self ):
        """Ensures: returns the latest account limit in tokens."""
        return self.snapshot()[ 0 ]

    def set_limit( self, tokens, by, why ):
        """
        Record a new account limit.

        Requires:
            - by and why say who set it and for what reason
        Raises:
            - ValueError for a limit that is not a positive integer
        """
        self._check_limit( tokens )
        with self._locked() as f:
            self._summary( self._rows( f ) )
            f.write( json.dumps( self._limit_row( tokens, by, why ), sort_keys=True ) + "\n" )
            f.flush()

    def begin_run( self, run, ceiling_tokens ):
        """
        Admit a run, or refuse it.

        Ensures:
            - appends a begin row only when the total plus the ceiling fits the limit
        Raises:
            - AccountLimitReached when it would not fit
            - ValueError when the run name was used before
        """
        with self._locked() as f:
            limit, total, runs = self._summary( self._rows( f ) )
            if run in runs: raise ValueError( f"run {run!r} already began in this ledger" )
            if total + ceiling_tokens > limit:
                raise AccountLimitReached( f"{total} already held plus a ceiling of {ceiling_tokens} passes the account limit of {limit}" )
            self._append( f, { "kind": "begin", "run": run, "tokens": ceiling_tokens } )

    def spend( self, run, tokens ):
        """Ensures: appends one settled attempt's tokens; ValueError for a run that never began."""
        with self._locked() as f:
            if run not in self._summary( self._rows( f ) )[ 2 ]: raise ValueError( f"run {run!r} never began" )
            self._append( f, { "kind": "spend", "run": run, "tokens": tokens } )

    def end_run( self, run ):
        """Ensures: appends an end row, so the run counts at what it spent."""
        with self._locked() as f:
            if run not in self._summary( self._rows( f ) )[ 2 ]: raise ValueError( f"run {run!r} never began" )
            self._append( f, { "kind": "end", "run": run } )
