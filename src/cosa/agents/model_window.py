"""
model_window.py

Ask the model server what its context window is, and how many tokens a string costs.

WHY THIS EXISTS — row a203d91d. The completion budget for kaitchup/phi_4_14b was a
constant 4096 in lupin-app.ini, sent to a server whose window is 8192. The server
checks prompt + completion against the window, so any prompt over ~4096 tokens was a
hard 400 before a single token was generated. The receptionist crossed that line and
died, taking the v2 flow's fallback with it.

WHY THE WINDOW IS NOT IN CONFIG — Mr Radio's ruling, 2026-08-19: "a number in config
that the server already knows is a second source of truth that will drift." vLLM
reports max_model_len on both GET /v1/models and POST /tokenize, so the real value is
one call away for whatever model is actually loaded.

FAIL LOUD, DO NOT ESTIMATE. If the server cannot be reached, these raise. A silent
character-count fallback would put a guess where a measurement belongs, and the guess
would be wrong in exactly the place that matters — near the ceiling.
"""

import json
import urllib.error
import urllib.request

# base_url -> { model_name -> window }; the window of a loaded model does not change
# without a server restart, so one call per process per model is enough.
_WINDOW_CACHE: dict = { }


def _server_root( base_url: str ) -> str:
    """
    The scheme://host:port an OpenAI-style completions URL belongs to.

    Requires:
        - base_url is an http(s) URL, e.g. http://host:3001/v1/completions

    Ensures:
        - returns scheme://netloc with no trailing slash and no path
    """
    from urllib.parse import urlparse

    parts = urlparse( base_url )
    return f"{parts.scheme}://{parts.netloc}"


def _post_json( url: str, payload: dict, timeout: int ) -> dict:
    """
    POST one JSON body and return the decoded JSON reply.

    Raises:
        - RuntimeError naming the url when the server cannot be reached or refuses
    """
    request = urllib.request.Request(
        url, data=json.dumps( payload ).encode(), headers={ "Content-Type": "application/json" }
    )
    try:
        with urllib.request.urlopen( request, timeout=timeout ) as response:
            return json.load( response )
    except ( urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError ) as e:
        raise RuntimeError( f"model server did not answer {url}: {type( e ).__name__}: {e}" )


def count_tokens( base_url: str, model_name: str, text: str, timeout: int=20 ) -> tuple[ int, int ]:
    """
    Token cost of `text` for `model_name`, and that model's context window.

    Both numbers come back from one POST /tokenize, which is why this returns a pair
    rather than making callers ask twice.

    Requires:
        - base_url points at a vLLM server (any path; only the host is used)
        - model_name is a model the server has loaded
        - text is a string

    Ensures:
        - returns ( token_count, context_window ), both positive integers
        - caches the window for later get_context_window() calls

    Raises:
        - RuntimeError if the server cannot be reached or answers without the fields
    """
    reply = _post_json(
        f"{_server_root( base_url )}/tokenize", { "model": model_name, "prompt": text }, timeout
    )
    if "count" not in reply or "max_model_len" not in reply:
        raise RuntimeError( f"/tokenize answered without count/max_model_len: {sorted( reply )}" )

    window = int( reply[ "max_model_len" ] )
    _WINDOW_CACHE.setdefault( _server_root( base_url ), { } )[ model_name ] = window
    return int( reply[ "count" ] ), window


def get_context_window( base_url: str, model_name: str, timeout: int=20 ) -> int:
    """
    The context window `model_name` is serving, cached per server and model.

    Requires:
        - base_url points at a vLLM server
        - model_name is a model the server has loaded

    Ensures:
        - returns the server's own max_model_len, never a configured constant
        - a second call for the same server and model does no network I/O

    Raises:
        - RuntimeError if the server cannot be reached or does not list the model
    """
    root   = _server_root( base_url )
    cached = _WINDOW_CACHE.get( root, { } ).get( model_name )
    if cached is not None: return cached

    try:
        with urllib.request.urlopen( f"{root}/v1/models", timeout=timeout ) as response:
            listing = json.load( response )
    except ( urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError ) as e:
        raise RuntimeError( f"model server did not answer {root}/v1/models: {type( e ).__name__}: {e}" )

    for entry in listing.get( "data", [ ] ):
        if entry.get( "id" ) == model_name and entry.get( "max_model_len" ) is not None:
            window = int( entry[ "max_model_len" ] )
            _WINDOW_CACHE.setdefault( root, { } )[ model_name ] = window
            return window

    raise RuntimeError(
        f"{root}/v1/models does not report max_model_len for [{model_name}]; "
        f"it lists {[ e.get( 'id' ) for e in listing.get( 'data', [ ] ) ]}"
    )


def clamp_max_tokens( requested: int, prompt_tokens: int, window: int, margin: int=64 ) -> int:
    """
    The largest completion budget that still fits the window beside this prompt.

    Requires:
        - requested, prompt_tokens and window are non-negative integers
        - margin is a non-negative integer

    Ensures:
        - returns `requested` untouched when it already fits
        - otherwise returns window - prompt_tokens - margin
        - never returns less than 1; a prompt that leaves no room at all yields 1,
          so the caller gets the server's own error about the prompt rather than a
          confusing zero-length request

    Raises:
        - None
    """
    room = window - prompt_tokens - margin
    if requested <= room: return requested
    return max( 1, room )
