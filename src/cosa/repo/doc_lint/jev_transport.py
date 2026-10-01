"""
The one door the judge harness uses to reach Jev, TypeSafe's yes/no model.

One POST to /v1/systemone asks one noul question and gets back the probability of yes. The
key is read from the environment variable JEV_API_TOASTER and goes nowhere else: it is not
printed, logged, stored, or placed in an error message. Standard library HTTP only.
"""

import json
import os
import time
import urllib.error
import urllib.request

URL            = "https://api.typesafe.ai/v1/systemone"
KEY_VARIABLE   = "JEV_API_TOASTER"
QUESTION_ID    = "claim_stated"
RETRY_STATUSES = ( 429, 529 )
MAX_ATTEMPTS   = 4
BACKOFF_SECONDS = 1.0
TIMEOUT_SECONDS = 60


class JevConfigError( Exception ):
    """Jev cannot be called as configured: no key, or the server refused the key or the request."""


class JevCallError( Exception ):
    """One Jev call gave no usable answer: retries ran out, the server failed, or the body is bad."""


def _post( url, headers, body, timeout ):
    """Send one POST with urllib and return ( status, text ); an error status is returned."""
    request = urllib.request.Request( url, data=body, headers=headers, method="POST" )
    try:
        with urllib.request.urlopen( request, timeout=timeout ) as response:
            return response.status, response.read().decode( "utf-8" )
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode( "utf-8", errors="replace" )


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


def ask_noul( model, state, instructions, criteria, post_fn=None, sleep_fn=None, environ=None ):
    """
    Ask Jev one yes/no question about a state and return the probability of yes.

    Requires:
        - model is a non-empty pinned id such as jev-1.13.0; there is no default
        - post_fn, when given, has _post's signature; sleep_fn has time.sleep's; both are test stand-ins
        - environ, when given, replaces os.environ

    Ensures:
        - returns ( noul, response_model ) as parse_answer does
        - a 429 or 529 is retried up to MAX_ATTEMPTS calls in all, waiting BACKOFF_SECONDS doubled each time
        - the key appears only in the Authorization header of the request

    Raises:
        - ValueError if model is empty
        - JevConfigError if the key variable is absent or empty, or the server answers 401, 403 or 422
        - JevCallError if retries run out, any other status is not 200, or the body is unusable
    """
    if not model: raise ValueError( "model id is required: the harness has no default Jev model" )
    key = ( os.environ if environ is None else environ ).get( KEY_VARIABLE )
    if not key: raise JevConfigError( f"{KEY_VARIABLE} is not set; the Jev judge refuses to run without it" )
    post_fn  = _post if post_fn is None else post_fn
    sleep_fn = time.sleep if sleep_fn is None else sleep_fn
    headers  = { "Authorization": "Bearer " + key, "Content-Type": "application/json" }
    body     = build_body( model, state, instructions, criteria )
    for attempt in range( MAX_ATTEMPTS ):
        try:
            status, text = post_fn( URL, headers, body, TIMEOUT_SECONDS )
        except OSError as e:
            raise JevCallError( f"call to Jev failed: {type( e ).__name__}" ) from e
        if status == 200: return parse_answer( text, model )
        if status in RETRY_STATUSES:
            if attempt < MAX_ATTEMPTS - 1: sleep_fn( BACKOFF_SECONDS * 2 ** attempt )
            continue
        if status in ( 401, 403, 422 ): raise JevConfigError( f"Jev refused the request with status {status}" )
        raise JevCallError( f"Jev answered status {status}" )
    raise JevCallError( f"Jev still answered a retry status after {MAX_ATTEMPTS} calls" )
