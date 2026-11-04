#!/usr/bin/env python3
"""
`blocked_by_persona` against the real stack: a live server, real rows, real containment.

The unit file proves the clause text and that every caller passes the argument. Only a real database can
show that the filter selects the right rows.
A fake that ignores its input answers the same whatever the code does. Rows are seeded straight into lupin_db_test and removed after each test.

Venue: :8000 monopolize mode, scheduled only. It writes task rows, so it is not :7999-eligible.
"""
import os
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import pytest
import requests
import secrets

from cosa.rest.db.database import get_db
from cosa.rest.db.repositories import UserRepository, ApiKeyRepository

BASE_URL = os.environ.get( "LUPIN_TEST_BASE_URL", "http://localhost:8000" )
ENDPOINT = f"{BASE_URL}/api/tasks"


@pytest.fixture
def headers( clean_test_db ):
    api_key  = "ck_live_" + secrets.token_urlsafe( 48 )
    key_hash = bcrypt.hashpw( api_key.encode( "utf-8" ), bcrypt.gensalt( rounds = 12 ) ).decode( "utf-8" )
    email    = f"test-{uuid.uuid4()}@test.com"
    with get_db() as session:
        user = UserRepository( session ).create_user( email = email, password_hash = "dummy_hash", roles = [ "service_account" ] )
        user.email_verified = True
        user.is_active      = True
        key     = ApiKeyRepository( session ).create_key( user_id = user.id, key_hash = key_hash, description = "blocked_by_persona probe" )
        key_id  = str( key.id )
        user_id = str( user.id )
    yield { "X-API-Key": api_key }
    with get_db() as session:
        ApiKeyRepository( session ).delete( uuid.UUID( key_id ) )
        UserRepository( session ).delete( uuid.UUID( user_id ) )


@pytest.fixture
def board( seeded_task_rows ):
    """Four rows: two blocked on tiffany (owned by others), one blocked on cheech, one queued."""
    chase = datetime.now( timezone.utc ) + timedelta( hours = 2 )
    other = str( uuid.uuid4() )
    return {
        "on_tiffany_a" : seeded_task_rows.create( "cheech", "waits on tiffany a", status = "blocked",
                             blocked_by = [ { "kind": "persona", "id": "tiffany" } ], next_chase_ts = chase )[ "id" ],
        "on_tiffany_b" : seeded_task_rows.create( "maria", "waits on tiffany b", status = "blocked",
                             blocked_by = [ { "kind": "persona", "id": "tiffany" }, { "kind": "item", "id": other } ],
                             next_chase_ts = chase )[ "id" ],
        "on_cheech"    : seeded_task_rows.create( "tiffany", "waits on cheech", status = "blocked",
                             blocked_by = [ { "kind": "persona", "id": "cheech" } ], next_chase_ts = chase )[ "id" ],
        "queued"       : seeded_task_rows.create( "tiffany", "not blocked" )[ "id" ],
    }


def _ids( response ):
    assert response.status_code == 200, response.text
    return { row[ "id" ] for row in response.json()[ "tasks" ] }


def test_a_row_blocked_on_a_persona_comes_back_for_that_persona_only( headers, board ):
    tiffany = _ids( requests.get( ENDPOINT, params = { "blocked_by_persona": "tiffany", "terse": "true" }, headers = headers, timeout = 10 ) )
    cheech  = _ids( requests.get( ENDPOINT, params = { "blocked_by_persona": "cheech",  "terse": "true" }, headers = headers, timeout = 10 ) )

    assert tiffany == { board[ "on_tiffany_a" ], board[ "on_tiffany_b" ] }
    assert cheech  == { board[ "on_cheech" ] }


def test_the_persona_is_canonicalized_like_every_other_persona_filter( headers, board ):
    ids = _ids( requests.get( ENDPOINT, params = { "blocked_by_persona": "Tiffany" }, headers = headers, timeout = 10 ) )
    assert ids == { board[ "on_tiffany_a" ], board[ "on_tiffany_b" ] }


def test_a_prefix_of_the_name_matches_nothing( headers, board ):
    assert _ids( requests.get( ENDPOINT, params = { "blocked_by_persona": "tiff" }, headers = headers, timeout = 10 ) ) == set()


def test_the_count_and_the_three_breakdowns_agree_with_the_page( headers, board ):
    params = { "blocked_by_persona": "tiffany" }
    page   = _ids( requests.get( ENDPOINT, params = params, headers = headers, timeout = 10 ) )
    counts = requests.get( ENDPOINT, params = { **params, "count_only": "true" }, headers = headers, timeout = 10 )
    assert counts.status_code == 200, counts.text
    body = counts.json()

    assert body[ "count" ] == len( page ) == 2
    assert sum( body[ "breakdown" ].values() ) == 2 and body[ "breakdown" ] == { "blocked": 2 }
    assert sum( body[ "priority_breakdown" ].values() ) == 2

    with_project = requests.get( ENDPOINT, params = { **params, "project": "lupin" }, headers = headers, timeout = 10 )
    assert with_project.status_code == 200, with_project.text
    assert { row[ "id" ] for row in with_project.json()[ "tasks" ] } == page


def test_the_filter_alone_passes_the_unscoped_size_guard( headers, board ):
    r = requests.get( ENDPOINT, params = { "blocked_by_persona": "tiffany" }, headers = headers, timeout = 10 )
    assert r.status_code == 200, r.text
