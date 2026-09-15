"""
No fleet-cap refusal may tell its reader how to raise the cap (row e55b3480).

Rick, 2026-09-15: "All changes in the fleet cap are driven by me the operator not by
managers and I do not want instructions for how to circumvent my decisions to be
propagated as an error message." Three refusals did exactly that — the launch guard
named the INI key and file, the spawn refusal said "Raise the cap above N", and the
slider's over-ceiling 422 said "Raise that key first".

Each arm drives the real producer of the text into its refusing branch, asserts the
branch fired (so a refusal that stopped being produced cannot pass vacuously), then
asserts none of the coaching phrases survive.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt
from cosa.rest.routers import arbiter
from lupin_mcp import fleet_cap_admission as fca
from lupin_mcp import fleet_size_cap as fsc


COACHING = [
    "raise the cap",
    "raise `cc session fleet size cap`",
    "raise that key",
    "lupin-app.ini",
    "fleet size cap maximum",
]


def _assert_no_coaching( text ):
    lowered = text.lower()
    found   = [ phrase for phrase in COACHING if phrase.lower() in lowered ]
    assert not found, f"a fleet-cap refusal coaches raising the cap via {found}: {text}"


def test_the_launch_guard_refusal_does_not_coach_raising_the_cap( tmp_path ):
    verdict = fca.admit(
        "cc-worker-1",
        headless      = True,
        cap_fn        = lambda: 3,
        census_fn     = lambda: [ object() ] * 3,
        bridge_lookup = lambda name: False,
        directory     = tmp_path / fca.RESERVATION_SUBDIR,
        now_fn        = lambda: 1000.0,
        ttl_seconds   = fca.DEFAULT_RESERVATION_TTL_SECONDS,
    )
    assert verdict[ "admitted" ] is False
    assert "FLEET CAP REFUSED THIS LAUNCH" in verdict[ "reason" ]
    _assert_no_coaching( verdict[ "reason" ] )


@pytest.mark.parametrize( "split", [
    { "total": 3, "managers": 3, "workers": 0 },                 # managers alone fill the cap
    { "total": 3, "managers": 1, "workers": 1, "unknown": 1 },   # unclassified seats
    { "total": 3, "managers": 1, "workers": 2 },                 # ordinary over-cap
] )
def test_the_spawn_refusal_does_not_coach_raising_the_cap( split ):
    msg = fsc.refusal_for_spawn( 1, split, cap=3 )
    assert msg is not None and "FLEET CAP REFUSED THIS SPAWN" in msg
    _assert_no_coaching( msg )


def test_the_slider_over_ceiling_refusal_does_not_coach_raising_the_ceiling( monkeypatch ):
    import cosa.rest.dependencies.config as config_dep
    monkeypatch.setattr( config_dep, "get_config_manager", lambda: None )
    monkeypatch.setattr( fsc, "resolve_fleet_ceiling", lambda config_mgr: 18 )

    app = FastAPI()
    app.include_router( arbiter.router )
    app.dependency_overrides[ require_api_key_or_jwt ] = lambda: "test-user"

    response = TestClient( app ).put( "/api/arbiter/fleet-size-cap", json={ "cap": 42 } )
    assert response.status_code == 422
    detail = response.json()[ "detail" ]
    assert "Nothing was written" in detail
    _assert_no_coaching( detail )
