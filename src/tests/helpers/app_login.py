"""
Log in to the app for a test, and tell a refused login from no server.

A skip reads green. A test that skips because the app refused its login hides a wrong password or a
locked account. It looks the same as a server that is not running. `login` skips only when
nothing answered; every answer that is not a good login fails, naming the account and the host.
"""

import json
import urllib.error
import urllib.request

import pytest

ENV_HINT = "check LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL and LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD"


def login( base_url, email, password, timeout=10 ):
    """
    POST {base_url}/auth/login and return the response body.

    Requires:
        - base_url is the app's address without a trailing slash
        - email and password are non-empty strings

    Ensures:
        - returns the parsed JSON body, a dict whose "tokens" holds a non-empty "access_token"
        - skips the test when no server answered (connection refused, unreachable, timed out)
        - fails the test when the server answered with an HTTP error, naming email and base_url
        - fails the test when the server answered 200 without an access token

    Raises:
        - ValueError if a 200 answer is not JSON
    """
    body    = json.dumps( { "email": email, "password": password } ).encode( "utf-8" )
    request = urllib.request.Request(
        f"{base_url}/auth/login",
        data    = body,
        headers = { "Content-Type": "application/json" },
        method  = "POST"
    )
    try:
        with urllib.request.urlopen( request, timeout=timeout ) as response:
            payload = json.loads( response.read() )
    except urllib.error.HTTPError as error:
        pytest.fail( f"{base_url} refused the login for {email} (HTTP {error.code}): {ENV_HINT}" )
    except ( urllib.error.URLError, TimeoutError, ConnectionError ) as error:
        pytest.skip( f"no server answered at {base_url}: {error}" )

    tokens = payload.get( "tokens" ) if isinstance( payload, dict ) else None
    if not tokens or not tokens.get( "access_token" ):
        pytest.fail( f"{base_url} answered the login for {email} without an access token" )
    return payload
