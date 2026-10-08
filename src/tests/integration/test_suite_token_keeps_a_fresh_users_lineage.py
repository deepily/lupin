"""
A fresh random user keeps the suite's lineage through the per-run token.

Inside a sweep the token is the only thing that vouches for that user's claim.
The request trace records a refused claim in parent_id_hash_dropped.
One test reads the field for a good token, another for a wrong one, so the reader is proven.

Requires:
    - a sweep that exported the parent id and the token variable
    - the server and this process share io/v2-flow (the :8000 container does)
"""

import json
import os
import uuid
from datetime import datetime, timedelta

import pytest
import requests

import cosa.utils.util as cu
from cosa.rest.suite_run_token import TOKEN_ENV_NAME, TOKEN_HEADER
from tests.helpers.suite_lineage import lineage_request, sweep_state

from .conftest import BASE_URL

REQUEST_TIMEOUT = 60
MISSING_TOKEN   = ( "The sweep exported its parent id but no per-run token, so the token was not issued "
                    "(switch off, or the issue failed). This file exists to prove the token works." )


@pytest.fixture( autouse=True )
def _sweep_exported_what_this_file_needs():
    """Skip outside a sweep; inside one without a token, fail instead of hiding."""
    state = sweep_state()
    if state == "outside": pytest.skip( "Needs a sweep that exported the parent id" )
    if state == "missing_token": pytest.fail( MISSING_TOKEN, pytrace=False )


def _fresh_user_token():
    email    = f"token_{uuid.uuid4().hex[ :8 ]}@test.com"
    password = uuid.uuid4().hex + "Aa1!"
    register = requests.post( f"{BASE_URL}/auth/register", json={ "email": email, "password": password }, timeout=REQUEST_TIMEOUT )
    assert register.status_code == 201, f"Registration failed: {register.text}"
    login = requests.post( f"{BASE_URL}/auth/login", json={ "email": email, "password": password }, timeout=REQUEST_TIMEOUT )
    assert login.status_code == 200, f"Login failed: {login.text}"
    return login.json()[ "tokens" ][ "access_token" ]


def _trace_row( trace_id ):
    """The trace record for one request, from today's file or yesterday's."""
    directory = os.path.join( cu.get_project_root(), "io", "v2-flow" )
    for day in ( datetime.now(), datetime.now() - timedelta( days=1 ) ):
        path = os.path.join( directory, f"trace-{day.strftime( '%Y-%m-%d' )}.jsonl" )
        if not os.path.exists( path ): continue
        with open( path ) as handle:
            for line in handle:
                row = json.loads( line )
                if row.get( "trace_id" ) == trace_id: return row
    return None


def _ask_as( token, edit=None ):
    request = lineage_request( { "question": "What is 2+2?", "websocket_id": "token_session", "speak": False },
                               { "Authorization": f"Bearer {token}" } )
    if edit is not None: request[ "headers" ] = edit( request[ "headers" ] )
    response = requests.post( f"{BASE_URL}/api/v2/ask", timeout=REQUEST_TIMEOUT, **request )
    assert response.status_code == 200, response.text
    return response.json()[ "trace_id" ]


def test_a_fresh_users_ask_is_traced_with_no_dropped_stamp( clean_test_db ):
    row = _trace_row( _ask_as( _fresh_user_token() ) )
    assert row is not None, "the trace row for the request was not found, so its absence of a drop means nothing"
    assert row.get( "parent_id_hash_dropped" ) is None, row.get( "parent_id_hash_dropped" )


def test_the_same_ask_with_a_wrong_token_is_traced_as_token_mismatch( clean_test_db ):
    """The instrument check: the reader finds a drop when there is one."""
    row = _trace_row( _ask_as( _fresh_user_token(), edit=lambda h: { **h, TOKEN_HEADER: "wrong-token-value" } ) )
    assert row is not None
    assert str( row.get( "parent_id_hash_dropped" ) ).endswith( ":token_mismatch" ), row.get( "parent_id_hash_dropped" )
