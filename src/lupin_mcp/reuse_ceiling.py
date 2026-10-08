"""
The token ceiling of one live run, checked before every attempt to Jev.

TokenBudget is a CallBudget, so jev_transport asks it before each HTTP attempt, retries included.
It also counts tokens: input and output together, as one number. Nothing here sends anything.
"""
import math
import threading

from cosa.repo.doc_lint import jev_transport as jt
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
    Raises:
        - ValueError for a ceiling or attempt limit that is not a positive integer
        - RuntimeError when take() is called with no open request
    """

    def __init__( self, attempt_limit, ceiling_tokens ):
        super().__init__( attempt_limit )
        if type( ceiling_tokens ) is not int or ceiling_tokens < 1: raise ValueError( f"token ceiling must be a positive integer, got {ceiling_tokens!r}" )
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
        with self._token_lock:
            if o.held:
                self.reserved_tokens -= o.held
                self.spent_tokens    += o.input_estimate
                o.held                = 0
            need = o.input_estimate + o.output_reserve
            if self.spent_tokens + self.reserved_tokens + need > self.ceiling_tokens:
                self.ceiling_refusals += 1
                raise jt.JevBudgetSpent( f"token ceiling of {self.ceiling_tokens} is reached" )
            self.reserved_tokens += need
            o.held                = need
        try:
            super().take()
        except jt.JevBudgetSpent:
            with self._token_lock:
                self.reserved_tokens -= o.held
                o.held                = 0
            raise

    def close_request( self, usage ):
        """
        Settle the open request that was answered.

        Requires:
            - usage is ( input_tokens, output_tokens ), or None when the response reported none
        """
        o = self._open
        with self._token_lock:
            if o.held:
                self.reserved_tokens -= o.held
                self.spent_tokens    += sum( usage ) if usage is not None else o.held
        o.input_estimate, o.output_reserve, o.held = None, 0, 0

    def fail_request( self ):
        """Ensures: charges the open request's last attempt at its input reserve; releases the rest."""
        o = self._open
        with self._token_lock:
            if o.held:
                self.reserved_tokens -= o.held
                self.spent_tokens    += o.input_estimate
        o.input_estimate, o.output_reserve, o.held = None, 0, 0
