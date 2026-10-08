"""
The one door the judge harness uses to reach Jev, TypeSafe's yes/no model.

One POST to /v1/systemone asks one noul question and gets back the probability of yes. The
key is read from the environment variable JEV_API_TOASTER and goes nowhere else: it is not
printed, logged, stored, or placed in an error message. Standard library HTTP only.
"""

import json
import math
import os
import random
import threading
import time
import urllib.error
import urllib.request

URL            = "https://api.typesafe.ai/v1/systemone"
KEY_VARIABLE   = "JEV_API_TOASTER"
QUESTION_ID    = "claim_stated"
RETRY_STATUSES = ( 429, 529, 500, 502, 503, 504, 408 )
MAX_ATTEMPTS   = 4
BACKOFF_SECONDS = 1.0
JITTER          = 0.25      # each backoff wait is scaled by a factor between 1 - JITTER and 1 + JITTER
RETRY_AFTER_CAP = 60.0      # the longest wait a retry-after header can ask for; a larger value is still recorded
TIMEOUT_SECONDS = 60


class JevConfigError( Exception ):
    """Jev cannot be called as configured: no key, or the server refused the key or the request."""

    def __init__( self, message, status=None ):
        super().__init__( message )
        self.status = status        # the HTTP status of a refusal (401, 403 or 422), or None when no request was made


class JevCallError( Exception ):
    """A Jev call gave no usable answer: retries ran out, the server failed, or the body is bad."""

    def __init__( self, message, status=None ):
        super().__init__( message )
        self.status = status        # the last HTTP status seen, or None when no response came (a timeout or a reset)


class JevBudgetSpent( Exception ):
    """The call budget is used up: no further HTTP attempt may be made."""


class _Tally( threading.local ):
    """One thread's running count of the attempts it took, or None when it is not counting."""
    count = None


class CallBudget:
    """
    A ceiling on HTTP attempts to Jev, shared by every thread of one sweep.

    Requires:
        - limit is a positive integer

    Ensures:
        - take() counts one attempt and returns, or raises JevBudgetSpent without counting when the limit is reached
        - used never exceeds limit, whatever the number of threads
        - between begin_tally() and end_tally() on one thread, the attempts that thread took are also counted
          separately, so one entry's attempts can be told from another's
    """

    def __init__( self, limit ):
        if type( limit ) is not int or limit < 1: raise ValueError( f"call budget must be a positive integer, got {limit!r}" )
        self.limit, self.used, self._lock, self._tally = limit, 0, threading.Lock(), _Tally()

    def take( self ):
        """Count one attempt, or raise JevBudgetSpent when the limit is already reached."""
        with self._lock:
            refused = self.used >= self.limit
            if not refused: self.used += 1
        if refused: raise JevBudgetSpent( f"call budget of {self.limit} attempts is spent" )
        if self._tally.count is not None: self._tally.count += 1

    def begin_tally( self ):
        """Start counting this thread's attempts from zero."""
        self._tally.count = 0

    def end_tally( self ):
        """Stop counting on this thread and return how many attempts it took since begin_tally()."""
        taken, self._tally.count = self._tally.count, None
        return taken

    @property
    def spent( self ):
        """True when no attempt is left."""
        with self._lock: return self.used >= self.limit


def _post( url, headers, body, timeout ):
    """Send one POST with urllib; return ( status, text, headers ), an error status included."""
    request = urllib.request.Request( url, data=body, headers=headers, method="POST" )
    try:
        with urllib.request.urlopen( request, timeout=timeout ) as response:
            return response.status, response.read().decode( "utf-8" ), dict( response.headers.items() )
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode( "utf-8", errors="replace" ), dict( e.headers.items() )


def retry_after_seconds( headers ):
    """
    Read a retry-after header as a number of seconds.

    Ensures:
        - returns the seconds as a float when the header is present, any letter case, and a finite number of at least zero
        - returns None when it is absent, a date, negative, not finite or not a number
    """
    if not isinstance( headers, dict ): return None
    value = next( ( v for k, v in headers.items() if isinstance( k, str ) and k.lower() == "retry-after" ), None )
    try:
        seconds = float( value )
    except ( TypeError, ValueError ):
        return None
    return seconds if math.isfinite( seconds ) and seconds >= 0 else None


def build_body( model, state, instructions, criteria ):
    """
    Build the request body for one noul question.

    Requires:
        - model is a pinned model id; state is any JSON-serialisable value
        - instructions is a str; criteria is a dict with "true" and "false"

    Ensures:
        - returns the JSON bytes of one request holding one noul question under QUESTION_ID
    """
    question = { "type": "noul", "instructions": instructions, "criteria": { "true": criteria[ "true" ], "false": criteria[ "false" ] } }
    return json.dumps( { "state": state, "model": model, "questions": { QUESTION_ID: question } } ).encode( "utf-8" )


def parse_answer( text, model ):
    """
    Read the noul probability and the model string out of a response body.

    Requires:
        - text is the response body; model is the id the request asked for

    Ensures:
        - returns ( noul, response_model ) where noul is a float from 0 to 1 and response_model
          equals the requested model, so a silently changed model cannot enter a ledger under a
          pinned id

    Raises:
        - JevCallError for invalid JSON, a missing answer, a noul that is not a number from 0 to 1,
          or a response model other than the one requested
    """
    try:
        data = json.loads( text )
        noul = data[ "answers" ][ QUESTION_ID ][ "noul" ]
        got  = data[ "model" ]
    except ( ValueError, KeyError, TypeError ) as e:
        raise JevCallError( f"response is not the expected shape: {type( e ).__name__}" ) from e
    if type( noul ) not in ( int, float ) or not 0 <= noul <= 1:
        raise JevCallError( f"noul must be a number from 0 to 1, got {noul!r}" )
    if got != model:
        raise JevCallError( f"asked for model {model!r} but the response names {got!r}" )
    return float( noul ), got


def has_key( environ=None ):
    """
    Report whether the key variable is set to a non-empty value.

    Ensures:
        - returns True when it is set; the value is never returned
    """
    return bool( ( os.environ if environ is None else environ ).get( KEY_VARIABLE ) )


def send_with_meta( body, post_fn=None, sleep_fn=None, environ=None, budget=None, random_fn=None, clock_fn=None ):
    """
    Send one request body to Jev and return the response text with what the transport saw.

    Requires:
        - body is the JSON bytes of one request
        - post_fn, when given, has _post's signature, and may return ( status, text ) with no headers; sleep_fn
          has time.sleep's; random_fn returns a float from 0 up to 1; clock_fn has time.monotonic's; all are test stand-ins
        - environ, when given, replaces os.environ
        - budget, when given, is a CallBudget; each HTTP attempt, retries included, takes one from it first

    Ensures:
        - returns ( text, meta ) for a 200 response; meta is { status, attempts, retry_after, latency_ms }
        - attempts counts the HTTP attempts this call took, latency_ms is the final attempt's own time in whole
          milliseconds, and retry_after is the largest retry-after (seconds) any attempt saw, or None
        - a status in RETRY_STATUSES, a timeout or a reset is retried up to MAX_ATTEMPTS calls in all, whatever the
          mix of causes; each wait is the larger of the retry-after
          (at most RETRY_AFTER_CAP) and BACKOFF_SECONDS doubled each time and scaled by a jitter factor
          between 1 - JITTER and 1 + JITTER, so a retry never comes sooner than the server asked
        - the key appears only in the Authorization header of the request

    Raises:
        - JevConfigError if the key variable is absent or empty (status None), or the server answers 401, 403 or 422 (status set)
        - JevBudgetSpent before any attempt the budget has no room for; no HTTP is made for it
        - JevCallError if retries run out or any other status is not 200; its status is the last HTTP status seen,
          None when the last attempt got no response
    """
    key = ( os.environ if environ is None else environ ).get( KEY_VARIABLE )
    if not key: raise JevConfigError( f"{KEY_VARIABLE} is not set; the Jev judge refuses to run without it" )
    post_fn   = _post if post_fn is None else post_fn
    sleep_fn  = time.sleep if sleep_fn is None else sleep_fn
    random_fn = random.random if random_fn is None else random_fn
    clock_fn  = time.monotonic if clock_fn is None else clock_fn
    headers   = { "Authorization": "Bearer " + key, "Content-Type": "application/json" }
    seen      = None
    failure   = None
    last_status = None
    for attempt in range( MAX_ATTEMPTS ):
        if budget is not None: budget.take()
        started = clock_fn()
        try:
            reply = post_fn( URL, headers, body, TIMEOUT_SECONDS )
        except OSError as e:
            last_status, failure = None, e
            if attempt < MAX_ATTEMPTS - 1: sleep_fn( max( 0.0, BACKOFF_SECONDS * 2 ** attempt * ( 1 - JITTER + 2 * JITTER * random_fn() ) ) )
            continue
        latency_ms = int( round( ( clock_fn() - started ) * 1000 ) )
        status, text, reply_headers = reply if len( reply ) == 3 else ( reply[ 0 ], reply[ 1 ], None )
        last_status, failure = status, None
        if status == 200: return text, { "status": 200, "attempts": attempt + 1, "retry_after": seen, "latency_ms": latency_ms }
        if status in RETRY_STATUSES:
            asked = retry_after_seconds( reply_headers )
            if asked is not None and ( seen is None or asked > seen ): seen = asked
            if attempt < MAX_ATTEMPTS - 1:
                jitter = 1 - JITTER + 2 * JITTER * random_fn()
                sleep_fn( max( min( asked, RETRY_AFTER_CAP ) if asked is not None else 0.0, BACKOFF_SECONDS * 2 ** attempt * jitter ) )
            continue
        if status in ( 401, 403, 422 ): raise JevConfigError( f"Jev refused the request with status {status}", status )
        raise JevCallError( f"Jev answered status {status}", status )
    if failure is not None: raise JevCallError( f"call to Jev failed after {MAX_ATTEMPTS} sends: {type( failure ).__name__}" ) from failure
    raise JevCallError( f"Jev still answered status {last_status} after {MAX_ATTEMPTS} calls", last_status )


def send( body, post_fn=None, sleep_fn=None, environ=None, budget=None, random_fn=None ):
    """
    Send one request body to Jev and return the response text. The only HTTP path to Jev.

    Requires:
        - the arguments are send_with_meta's

    Ensures:
        - returns the text of a 200 response, and behaves as send_with_meta does otherwise
    """
    return send_with_meta( body, post_fn, sleep_fn, environ, budget, random_fn )[ 0 ]


def ask_noul( model, state, instructions, criteria, post_fn=None, sleep_fn=None, environ=None, random_fn=None ):
    """
    Ask Jev one yes/no question about a state and return the probability of yes.

    Requires:
        - model is a non-empty pinned id such as jev-1.13.0; there is no default
        - post_fn, sleep_fn, environ and random_fn are send's test stand-ins

    Ensures:
        - returns ( noul, response_model ) as parse_answer does

    Raises:
        - ValueError if model is empty
        - JevConfigError and JevCallError as send does, and JevCallError for an unusable body
    """
    if not model: raise ValueError( "model id is required: the harness has no default Jev model" )
    body = build_body( model, state, instructions, criteria )
    return parse_answer( send( body, post_fn, sleep_fn, environ, None, random_fn ), model )
