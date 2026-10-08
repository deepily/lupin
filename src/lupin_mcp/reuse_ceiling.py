"""
The token ceiling of one live run, checked before every attempt to Jev.

TokenBudget is a CallBudget, so jev_transport asks it before each HTTP attempt, retries included.
It also counts tokens: input and output together, as one number. Nothing here sends anything.
"""
import math
import threading

from cosa.repo.doc_lint import jev_transport as jt
from lupin_mcp import reuse_ledger as rl
from lupin_mcp import reuse_tools as rt

INPUT_FACTOR           = 1.5                                  # the share of the length-based estimate held back as input
OUTPUT_TOKENS_PER_ENTRY = 60                                  # 1.4 times the 42 measured in 7,705 cached single-entry answers


def input_reserve( body ):
    """Ensures: returns 1.5 times the body's canonical length over four, rounded up."""
    return math.ceil( INPUT_FACTOR * len( rt.canonical( body ) ) / 4 )


def reserve_tokens( body, entries ):
    """
    Price one request before it is sent.

    Requires:
        - entries is the number of entries the request asks about
    Ensures:
        - returns the input reserve plus OUTPUT_TOKENS_PER_ENTRY for each entry
    """
    return input_reserve( body ) + OUTPUT_TOKENS_PER_ENTRY * entries


class _Open( threading.local ):
    """The request this thread has open: its two reserves and the reserve now held."""

    input_estimate = None
    output_reserve = 0
    held           = 0


class TokenBudget( jt.CallBudget ):
    """
    An attempt ceiling and a token ceiling in one budget.

    Requires:
        - attempt_limit and ceiling_tokens are positive integers
        - the caller opens a request before posting it, and closes or fails it after
    Ensures:
        - take() refuses with JevBudgetSpent, and makes no HTTP, when spent plus every reserve still in flight
          plus this attempt's reserve would pass the ceiling; the check and the reserve are one step under one lock
        - an attempt that drew no answer is charged the input part of its reserve when the next attempt
          starts or when the request fails; the retry reserves again because it sends the body again
        - close_request() replaces the held reserve with the reported input plus output tokens, or keeps
          the whole reserve as spent when the response had no usage
        - a refusal for the ceiling is counted in ceiling_refusals, apart from any failure
        - the attempt limit still applies; an attempt it refuses releases the reserve it took
        - with a ledger, the run is admitted when the budget is built, every settled charge is appended to the
          ledger, and the ledger is read again before each attempt: an unreadable ledger or a total past the
          account limit refuses the attempt with no HTTP and sets stop_reason
    Raises:
        - AccountLimitReached or LedgerUnreadable from the ledger when the run is not admitted
        - ValueError for a ceiling or attempt limit that is not a positive integer
        - RuntimeError when take() is called with no open request
    """

    def __init__( self, attempt_limit, ceiling_tokens, ledger=None, run=None ):
        super().__init__( attempt_limit )
        if type( ceiling_tokens ) is not int or ceiling_tokens < 1: raise ValueError( f"token ceiling must be a positive integer, got {ceiling_tokens!r}" )
        if ledger is not None and not run: raise ValueError( "a ledger needs the name of the run" )
        if ledger is not None: ledger.begin_run( run, ceiling_tokens )
        self.ledger, self.run, self.stop_reason = ledger, run, None
        self.ceiling_tokens   = ceiling_tokens
        self.spent_tokens     = 0
        self.reserved_tokens  = 0
        self.ceiling_refusals = 0
        self._token_lock      = threading.Lock()
        self._open            = _Open()

    def open_request( self, body, entries ):
        """Ensures: this thread's next attempts are priced from body and entries."""
        self._open.input_estimate = input_reserve( body )
        self._open.output_reserve = OUTPUT_TOKENS_PER_ENTRY * entries
        self._open.held           = 0

    def take( self ):
        """Ensures: reserves the attempt's tokens, then counts it; JevBudgetSpent for either limit."""
        o = self._open
        if o.input_estimate is None: raise RuntimeError( "take() needs open_request() first" )
        self._read_ledger()
        charged = 0
        try:
            with self._token_lock:
                if o.held:
                    self.reserved_tokens -= o.held
                    self.spent_tokens    += o.input_estimate
                    charged               = o.input_estimate
                    o.held                = 0
                need = o.input_estimate + o.output_reserve
                if self.spent_tokens + self.reserved_tokens + need > self.ceiling_tokens:
                    self.ceiling_refusals += 1
                    raise jt.JevBudgetSpent( f"token ceiling of {self.ceiling_tokens} is reached" )
                self.reserved_tokens += need
                o.held                = need
        finally:
            self._record( charged )
        try:
            super().take()
        except jt.JevBudgetSpent:
            with self._token_lock:
                self.reserved_tokens -= o.held
                o.held                = 0
            raise

    def _read_ledger( self ):
        """Ensures: returns if the ledger reads and fits the limit; else sets stop_reason, refuses."""
        if self.ledger is None: return
        if self.stop_reason is not None: raise jt.JevBudgetSpent( f"stopped: {self.stop_reason}" )
        try: limit, total = self.ledger.snapshot()
        except rl.LedgerUnreadable as e:
            self.stop_reason = f"ledger unreadable: {e}"
            raise jt.JevBudgetSpent( f"stopped: {self.stop_reason}" ) from e
        if total > limit:
            self.stop_reason = f"ledger total {total} passes the account limit of {limit}"
            raise jt.JevBudgetSpent( f"stopped: {self.stop_reason}" )

    def _record( self, tokens ):
        """Ensures: appends a settled charge; a failing ledger stops the run but keeps the response."""
        if self.ledger is None or not tokens: return
        try: self.ledger.spend( self.run, tokens )
        except ( rl.LedgerUnreadable, ValueError ) as e: self.stop_reason = f"ledger unreadable: {e}"

    def end( self ):
        """Ensures: closes the run in the ledger, so it counts at what it spent."""
        if self.ledger is not None: self.ledger.end_run( self.run )

    def close_request( self, usage ):
        """
        Settle the open request that was answered.

        Requires:
            - usage is ( input_tokens, output_tokens ), or None when the response reported none
        """
        o, charged = self._open, 0
        with self._token_lock:
            if o.held:
                charged               = sum( usage ) if usage is not None else o.held
                self.reserved_tokens -= o.held
                self.spent_tokens    += charged
        o.input_estimate, o.output_reserve, o.held = None, 0, 0
        self._record( charged )

    def fail_request( self ):
        """Ensures: charges the open request's last attempt at its input reserve; releases the rest."""
        o, charged = self._open, 0
        with self._token_lock:
            if o.held:
                charged               = o.input_estimate
                self.reserved_tokens -= o.held
                self.spent_tokens    += charged
        o.input_estimate, o.output_reserve, o.held = None, 0, 0
        self._record( charged )
