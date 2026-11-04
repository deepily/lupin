"""
One place where an integration test claims the monopolizing suite as its parent.

Under a monopoly hold the queue defers every job that is not the monopolizer's child.
The suite job exports its id and, where the server accepts it, a per-run token.
`lineage_request` returns the keyword arguments for requests.post: the body with its
parent_id_hash, and the headers with the token. Outside a suite both are unchanged.

The token is built inside this frame and returned, never bound to a name in a test.
That keeps it out of the locals pytest renders, where only the redaction layer stands.
"""

import os

import pytest

from cosa.rest.suite_run_token import TOKEN_ENV_NAME, TOKEN_HEADER

PARENT_ENV_NAME = "LUPIN_TEST_MONOPOLIZE_PARENT_ID"


def lineage_request( body: dict, headers: dict ) -> dict:
    """
    The json and headers keyword arguments for one /api/v2/ask or /api/v2/submit post.

    Requires:
        - body and headers are dicts the caller owns; neither is modified

    Ensures:
        - parent_id_hash is added to the body only when the suite exported its id
        - the token header is added only when the suite exported a token
        - with neither variable set, the copies equal the inputs
    """
    parent_id = os.environ.get( PARENT_ENV_NAME )
    token     = os.environ.get( TOKEN_ENV_NAME )
    return {
        "json"    : { **body, "parent_id_hash": parent_id } if parent_id else dict( body ),
        "headers" : { **headers, TOKEN_HEADER: token } if token else dict( headers ),
    }


def sweep_state( environ: dict = None ) -> str:
    """
    Say what the sweep exported, so a test can skip, fail or run.

    Ensures:
        - returns "outside" when no parent id is exported: not inside a sweep, skip
        - returns "missing_token" when the parent id is set and the token is not: a failed
          or disabled issue, which a test about the token must report, not skip
        - returns "ready" when both are set
    """
    environ = os.environ if environ is None else environ
    if not environ.get( PARENT_ENV_NAME ): return "outside"
    if not environ.get( TOKEN_ENV_NAME ): return "missing_token"
    return "ready"


MISSING_TOKEN_MESSAGE = ( "The sweep exported its parent id but no per-run token, so the token was not issued "
                          "(switch off, or the issue failed). A test about the token must not hide this." )


def require_sweep( environ: dict = None ) -> None:
    """
    Skip outside a sweep, fail inside one that has no token, return when both are exported.

    Ensures:
        - outside a sweep raises the pytest skip exception
        - a parent id without a token raises the pytest failure, with MISSING_TOKEN_MESSAGE
        - with both exported returns None
    """
    state = sweep_state( environ )
    if state == "outside": pytest.skip( "Needs a sweep that exported the parent id" )
    if state == "missing_token": pytest.fail( MISSING_TOKEN_MESSAGE, pytrace=False )
