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
import os
import pathlib
import time

PRICE_PER_MILLION_USD = 0.042                                 # the pinned input price; output is counted at the same price
ACCOUNT_LIMIT_USD     = 40.00                                 # Rick raised the Jev account to about 44 dollars; was 19.31
STAGE1_CEILING_TOKENS = 71_000_000                            # three dollars at the price above, rounded down (plan 11.1)
LEDGER_NAME           = "jev-spend-ledger.jsonl"
ANCHOR_BYTES          = 256                                   # the last bytes read, compared on the next read to catch a rewrite in place


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
        - each call parses only the rows appended since the last read of this instance, under the same lock
    Raises:
        - LedgerUnreadable for a missing file, a line that is not a JSON object, a bad row, or no limit row
    """

    def __init__( self, path ):
        self.path = pathlib.Path( path )
        self._forget()

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

    def _forget( self, identity=None ):
        """Ensures: nothing of the file is remembered but its ( device, inode ), when given."""
        self._identity, self._offset, self._anchor, self._line_no = identity, 0, b"", 0
        self._limit, self._runs = None, {}

    def _unchanged_before_offset( self, raw ):
        """Ensures: True when the bytes just before the read offset are the bytes read last time."""
        if not self._anchor: return True
        raw.seek( self._offset - len( self._anchor ) )
        return raw.read( len( self._anchor ) ) == self._anchor

    @staticmethod
    def _row_of( n, chunk ):
        """Ensures: returns the checked row on line n, or None for a blank line."""
        try: line = chunk.decode( "utf-8" )
        except UnicodeDecodeError as e: raise LedgerUnreadable( f"line {n} is not JSON" ) from e
        if not line.strip(): return None
        try: row = json.loads( line )
        except ValueError as e: raise LedgerUnreadable( f"line {n} is not JSON" ) from e
        if not isinstance( row, dict ) or row.get( "kind" ) not in ( "limit", "begin", "spend", "end" ):
            raise LedgerUnreadable( f"line {n} is not a ledger row" )
        if row[ "kind" ] != "end" and not _whole( row.get( "tokens" ) ):
            raise LedgerUnreadable( f"line {n} has no whole token count" )
        if row[ "kind" ] != "limit" and not isinstance( row.get( "run" ), str ):
            raise LedgerUnreadable( f"line {n} names no run" )
        return row

    def _fold( self, row ):
        """Ensures: the row is counted in the remembered limit and runs."""
        if row[ "kind" ] == "limit":
            self._limit = row[ "tokens" ]
            return
        run = self._runs.setdefault( row[ "run" ], { "ceiling": 0, "spent": 0, "closed": False } )
        if row[ "kind" ] == "begin": run[ "ceiling" ] = row[ "tokens" ]
        elif row[ "kind" ] == "spend": run[ "spent" ] += row[ "tokens" ]
        else: run[ "closed" ] = True

    def _state( self, f ):
        """
        Read what was appended since the last read and fold it in.

        Requires:
            - f is the open ledger file, held under the exclusive lock
        Ensures:
            - returns ( limit, total, runs ) for the whole file
            - only bytes past the remembered offset are parsed; the file is read again from the start when it
              was replaced, shrank, or no longer holds the bytes read last time
            - the offset moves past a row only after the row was checked and counted, so a refused line is
              refused again until it is repaired and no row is ever counted twice
        Raises:
            - LedgerUnreadable for a line that is not JSON, not a ledger row, has no whole token count or names
              no run, and when no limit row exists
        """
        raw, stat = f.buffer, os.fstat( f.fileno() )
        if ( stat.st_dev, stat.st_ino ) != self._identity or stat.st_size < self._offset or not self._unchanged_before_offset( raw ):
            self._forget( ( stat.st_dev, stat.st_ino ) )
        raw.seek( self._offset )
        tail, start = raw.read(), 0
        while start < len( tail ):
            end   = tail.find( b"\n", start )
            end   = len( tail ) if end == -1 else end + 1
            chunk = tail[ start:end ]
            row   = self._row_of( self._line_no + 1, chunk )
            if row is not None: self._fold( row )
            self._line_no += 1
            self._offset  += len( chunk )
            self._anchor   = ( self._anchor + chunk )[ -ANCHOR_BYTES: ]
            start          = end
        if self._limit is None: raise LedgerUnreadable( "the ledger has no limit row" )
        total = sum( r[ "spent" ] if r[ "closed" ] else max( r[ "ceiling" ], r[ "spent" ] ) for r in self._runs.values() )
        return self._limit, total, self._runs

    def _append( self, f, row ):
        f.write( json.dumps( { **row, "at": time.strftime( "%Y-%m-%dT%H:%M:%S%z" ) }, sort_keys=True ) + "\n" )
        f.flush()

    def snapshot( self ):
        """Ensures: returns ( account limit, total ) as one read."""
        with self._locked() as f: limit, total, _ = self._state( f )
        return limit, total

    def total( self ):
        """Ensures: returns the tokens the ledger holds against the account."""
        return self.snapshot()[ 1 ]

    def held_by_prefix( self, prefix ):
        """
        Count what the runs whose name starts with prefix hold against the account.

        Ensures:
            - a closed run counts at its spend and an open one at the larger of its ceiling and its spend
            - returns 0 when no run has that prefix
        Raises:
            - LedgerUnreadable as snapshot does
        """
        with self._locked() as f: runs = self._state( f )[ 2 ]
        return sum( r[ "spent" ] if r[ "closed" ] else max( r[ "ceiling" ], r[ "spent" ] ) for name, r in runs.items() if name.startswith( prefix ) )

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
            self._state( f )
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
            limit, total, runs = self._state( f )
            if run in runs:
                raise ValueError( f"run {run!r} already began in this ledger" )
            if total + ceiling_tokens > limit:
                raise AccountLimitReached( f"{total} already held plus a ceiling of {ceiling_tokens} passes the account limit of {limit}" )
            self._append( f, { "kind": "begin", "run": run, "tokens": ceiling_tokens } )

    def spend( self, run, tokens ):
        """Ensures: appends one settled attempt's tokens; ValueError for a run that never began."""
        with self._locked() as f:
            if run not in self._state( f )[ 2 ]:
                raise ValueError( f"run {run!r} never began" )
            self._append( f, { "kind": "spend", "run": run, "tokens": tokens } )

    def close_run( self, run, by, why ):
        """
        Close a run that never ended, such as a dead process's, so it counts at its spend.

        Requires:
            - by and why are non-empty strings saying who closed it and for what reason
        Raises:
            - ValueError for a missing by or why, a run that never began, or a run already closed
        """
        if not isinstance( by, str ) or not by or not isinstance( why, str ) or not why: raise ValueError( "by and why must say who closed the run and why" )
        with self._locked() as f:
            runs = self._state( f )[ 2 ]
            if run not in runs:
                raise ValueError( f"run {run!r} never began" )
            if runs[ run ][ "closed" ]:
                raise ValueError( f"run {run!r} is already closed" )
            self._append( f, { "kind": "end", "run": run, "by": by, "why": why } )

    def end_run( self, run ):
        """Ensures: appends an end row, so the run counts at what it spent."""
        with self._locked() as f:
            if run not in self._state( f )[ 2 ]:
                raise ValueError( f"run {run!r} never began" )
            self._append( f, { "kind": "end", "run": run } )
