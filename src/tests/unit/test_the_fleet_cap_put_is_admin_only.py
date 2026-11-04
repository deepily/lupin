#!/usr/bin/env python3
"""
Tests that only an administrator login may set the fleet cap.

The cap PUT used to answer to any API key or login, so a manager could raise the number it
was refused under. It now matches the skeleton crew switch. A Claude session authenticates with
an API key and may read the cap and may not change it. The GET stays open to every caller.

Every test writes to tmp_path. The live configuration file is never touched.
"""
import os
import sys

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.rest.auth_middleware import require_admin
from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt
from cosa.rest.routers import arbiter
from lupin_mcp import fleet_cap_ini_io as io
from lupin_mcp import fleet_size_cap


PATH = "/api/arbiter/fleet-size-cap"
BODY = """\
[Lupin: Baseline]
cc session fleet size cap                        = 8
cc session fleet size cap maximum                = 18
"""


@pytest.fixture
def ini( tmp_path, monkeypatch ):
    path = tmp_path / "lupin-app.ini"
    path.write_text( BODY, encoding="utf-8" )
    monkeypatch.setattr( fleet_size_cap, "config_file_path", lambda: str( path ) )
    return path


def _client( admin=True ):
    app = FastAPI()
    app.include_router( arbiter.router )
    app.dependency_overrides[ require_api_key_or_jwt ] = lambda: "test-user"
    if admin:
        app.dependency_overrides[ require_admin ] = lambda: { "email": "rick@example.com" }
    else:
        def refuse():
            raise HTTPException( status_code=403, detail="admin role required" )
        app.dependency_overrides[ require_admin ] = refuse
    return TestClient( app )


def _cap( ini ):
    return io.read_value_from_disk( str( ini ), fleet_size_cap.FLEET_CAP_KEY )


def test_an_api_key_without_an_admin_login_is_refused_and_changes_nothing( ini ):
    response = _client().put( PATH, json={ "cap": 12 }, headers={ "X-API-Key": "a-managers-key" } )
    assert response.status_code == 403
    assert "fleet cap" in response.json()[ "detail" ]
    assert _cap( ini ) == "8"


def test_a_signed_in_user_who_is_not_an_admin_is_refused_and_changes_nothing( ini ):
    response = _client( admin=False ).put( PATH, json={ "cap": 12 } )
    assert response.status_code == 403
    assert _cap( ini ) == "8"


def test_an_administrator_sets_the_cap_and_the_file_says_so( ini ):
    response = _client().put( PATH, json={ "cap": 12 } )
    assert response.status_code == 200
    assert response.json()[ "cap" ] == 12
    assert _cap( ini ) == "12"


def test_an_admin_token_that_arrives_with_an_api_key_is_allowed( ini ):
    response = _client().put( PATH, json={ "cap": 12 },
                              headers={ "X-API-Key": "k", "Authorization": "Bearer t" } )
    assert response.status_code == 200


def test_the_read_stays_open_to_a_caller_who_is_not_an_admin( ini ):
    assert _client( admin=False ).get( PATH ).status_code == 200
    assert _client().get( PATH, headers={ "X-API-Key": "a-managers-key" } ).status_code == 200


def test_a_refused_caller_is_refused_before_the_ceiling_is_checked( ini ):
    response = _client().put( PATH, json={ "cap": 99 }, headers={ "X-API-Key": "k" } )
    assert response.status_code == 403
