"""
Pin tests for the two API-key-only refusals in cosa.rest.routers.arbiter.

Both dependencies are called directly. The exact 403 text, the status code and the
pass-through cases are fixed before the two bodies are merged.
"""

import asyncio

import pytest
from fastapi import HTTPException

from cosa.rest.routers import arbiter

CAP_DETAIL  = "Only an administrator may change the fleet cap."
FLIP_DETAIL = "Only an administrator may change the skeleton crew switch."

REFUSALS = [
    ( arbiter.refuse_api_key_cap_writer, CAP_DETAIL ),
    ( arbiter.refuse_api_key_flipper,     FLIP_DETAIL ),
]


@pytest.mark.parametrize( "dependency, detail", REFUSALS )
def test_api_key_alone_is_refused_with_the_exact_detail( dependency, detail ):
    """
    Ensures:
        - X-API-Key without Authorization raises 403 carrying the exact wording
    """
    with pytest.raises( HTTPException ) as caught:
        asyncio.run( dependency( x_api_key="k", authorization=None ) )
    assert caught.value.status_code == 403
    assert caught.value.detail      == detail


@pytest.mark.parametrize( "dependency, detail", REFUSALS )
@pytest.mark.parametrize( "x_api_key, authorization", [
    ( None, None ),
    ( None, "Bearer t" ),
    ( "k",  "Bearer t" ),
    ( "",   None ),
] )
def test_every_other_header_combination_passes_through( dependency, detail, x_api_key, authorization ):
    """
    Ensures:
        - returns None, leaving the admin check to decide, unless the key is alone
    """
    assert asyncio.run( dependency( x_api_key=x_api_key, authorization=authorization ) ) is None


def test_the_two_refusals_are_distinct_named_functions():
    """
    Ensures:
        - both dependencies keep their public names and stay distinct objects
    """
    assert arbiter.refuse_api_key_cap_writer.__name__ == "refuse_api_key_cap_writer"
    assert arbiter.refuse_api_key_flipper.__name__    == "refuse_api_key_flipper"
    assert arbiter.refuse_api_key_cap_writer is not arbiter.refuse_api_key_flipper
