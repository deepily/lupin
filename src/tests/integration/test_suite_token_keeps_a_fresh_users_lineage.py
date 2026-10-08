"""
A fresh random user keeps the suite's lineage through the per-run token.

Inside a sweep the token is the only thing that vouches for that user's claim.
A refused claim on the suite itself gets a 403 and no trace row. Any other refused claim is dropped and traced.
Two tests read parent_id_hash_dropped: a good token drops nothing, and a claim that is not the suite drops.

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
from tests.helpers.suite_lineage import PARENT_ENV_NAME, lineage_request, require_sweep

from .conftest import BASE_URL

REQUEST_TIMEOUT = 60


@pytest.fixture( autouse=True )
def _sweep_exported_what_this_file_needs():
    """Skip outside a sweep; inside one without a token, fail instead of hiding."""
    require_sweep()


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


def _post_ask( token, edit=None, parent=None ):
    """POST one ask as the fresh user; parent replaces the sweep's parent id when given."""
    request = lineage_request( { "question": "What is 2+2?", "websocket_id": "token_session", "speak": False },
                               { "Authorization": f"Bearer {token}" } )
    if edit is not None: request[ "headers" ] = edit( request[ "headers" ] )
    if parent is not None: request[ "json" ][ "parent_id_hash" ] = parent
    return requests.post( f"{BASE_URL}/api/v2/ask", timeout=REQUEST_TIMEOUT, **request )


def _ask_as( token, edit=None, parent=None ):
    response = _post_ask( token, edit, parent )
    assert response.status_code == 200, response.text
    return response.json()[ "trace_id" ]


def test_a_fresh_users_ask_is_traced_with_no_dropped_stamp( clean_test_db ):
    row = _trace_row( _ask_as( _fresh_user_token() ) )
    assert row is not None, "the trace row for the request was not found, so its absence of a drop means nothing"
    assert row.get( "parent_id_hash_dropped" ) is None, row.get( "parent_id_hash_dropped" )


def test_the_same_ask_with_a_wrong_token_is_refused_with_403_naming_token_mismatch( clean_test_db ):
    """The suite's own id with a wrong token is refused loudly, naming the parent."""
    response = _post_ask( _fresh_user_token(), edit=lambda h: { **h, TOKEN_HEADER: "wrong-token-value" } )
    assert response.status_code == 403, response.text
    detail = response.json()[ "detail" ]
    assert detail[ "error" ] == "parent_id_hash_refused", detail
    assert detail[ "reason" ] == "token_mismatch", detail
    assert detail[ "parent_id_hash" ] == os.environ[ PARENT_ENV_NAME ], detail


def test_a_wrong_token_on_a_claim_that_is_not_the_suite_is_dropped_quietly_and_traced( clean_test_db ):
    """The instrument check: the reader finds a drop when there is one."""
    claimed = uuid.uuid4().hex
    row     = _trace_row( _ask_as( _fresh_user_token(), edit=lambda h: { **h, TOKEN_HEADER: "wrong-token-value" }, parent=claimed ) )
    assert row is not None, "the trace row for the request was not found, so the drop cannot be read"
    dropped = str( row.get( "parent_id_hash_dropped" ) )
    assert claimed in dropped and dropped.endswith( ":token_unknown" ), dropped
