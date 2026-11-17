"""
One JSON request over urllib, shared by the callers that each built their own.

The hook library under `lupin_cli/claude_code/hooks/lib` keeps its own copies, because
a hook must not import `cosa`.
"""

import json
import urllib.error
import urllib.request


def send_json( url, payload=None, headers=None, timeout=30, method="POST", opener=None ):
    """
    Send one request with a JSON body and return what the server answered.

    Requires:
        - url is a full http(s) URL
        - payload is None for an empty body, a dict or list to be encoded with json.dumps,
          or str or bytes already encoded
        - headers is None or a dict; Content-Type application/json is added unless it is given
        - timeout is a positive number of seconds
        - opener is None for urllib.request.urlopen, or a callable with its signature

    Ensures:
        - returns ( status, text, reply_headers ) for any HTTP answer, a 4xx or 5xx included,
          because an error status is an answer and its body carries the reason
        - text is the body decoded as UTF-8 with undecodable bytes replaced
        - reply_headers is a plain dict

    Raises:
        - urllib.error.URLError or OSError when no HTTP answer came (refused, timeout, DNS)
    """
    if payload is None:                       data = None
    elif isinstance( payload, bytes ):        data = payload
    elif isinstance( payload, str ):          data = payload.encode( "utf-8" )
    else:                                     data = json.dumps( payload ).encode( "utf-8" )
    merged  = { "Content-Type": "application/json" }
    merged.update( headers or {} )
    request = urllib.request.Request( url, data=data, headers=merged, method=method )
    opener  = opener if opener is not None else urllib.request.urlopen
    try:
        with opener( request, timeout=timeout ) as response:
            return response.status, response.read().decode( "utf-8", errors="replace" ), dict( response.headers.items() )
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode( "utf-8", errors="replace" ), dict( e.headers.items() )
