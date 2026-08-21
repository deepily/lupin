"""
Step 11 THROUGH-PATH: the tombstones refuse through the app main.py really builds.

WHY THIS EXISTS, AND WHY IT IS NOT A DUPLICATE OF test_retired_queue_doors_410.py.

    That suite mounts `queues.router` and `v2_ask.router` onto a FastAPI it builds
    itself. Every assertion in it is true of the ROUTERS. None of them is true of the
    SERVER, because nothing in it reads `main.py`. If `main.py` ever stopped including
    `queues.router` — or included an older copy, or mounted something ahead of it that
    shadowed the path — that suite would stay green while `/api/push` was live again.

    This is the plan's own trap, stated in its Verification section: *"a test that
    exercises `todo_fifo_queue` directly keeps passing when `push_job` stops reaching
    that code … Every parity claim needs a test that runs THROUGH the new path, or it
    proves nothing."* Same shape, different subject.

    ⇒ THIS FILE IMPORTS `lupin_app.main` AND DRIVES ITS `app` OBJECT. The route table
    under test is the one the server serves.

WHY IMPORTING, WHEN THE NEIGHBOURING BOOT-ORDER PIN DELIBERATELY DOES NOT.
    `test_main_boot_order_v2_submit.py` checks CONSTRUCTION ORDER, which is a fact
    about source text, so it parses the source and never pays the import. This file
    checks WHAT A ROUTE ANSWERS, which no amount of source reading can establish — a
    handler that returns 410 in the source still answers 200 if something mounted
    later shadows its path. Measured cost of the import: ~5.6s, once, at module scope.

WHY `JWT_SECRET_KEY` IS SET HERE.
    `main.py` raises at import if it is missing — deliberately, so no environment ever
    gets a default signing secret. The value below is a test-only string that never
    signs anything: the lifespan never runs (TestClient is not entered as a context
    manager), so no token is issued. If the variable is already set, it is left alone.

WHAT WOULD GO RED HERE AND NOWHERE ELSE: main.py dropping `queues.router`, mounting a
stale copy of it, or registering any route that shadows a tombstone's path.
"""

import os
import sys

import pytest


@pytest.fixture( scope="module" )
def real_app():
    """The FastAPI object `main.py` itself assembles — not one built by this test."""
    root = os.environ.get( "LUPIN_ROOT" )
    assert root, "LUPIN_ROOT must be set — see CLAUDE.md § PATH MANAGEMENT"

    os.environ.setdefault( "JWT_SECRET_KEY", "test-only-never-signs-anything" )
    src = os.path.join( root, "src" )
    if src not in sys.path: sys.path.insert( 0, src )

    import lupin_app.main as main_module
    return main_module.app


@pytest.fixture( scope="module" )
def real_client( real_app ):
    """A client over the real app. NOT entered as a context manager: no lifespan runs."""
    from fastapi.testclient import TestClient
    return TestClient( real_app, raise_server_exceptions=False )


@pytest.fixture( scope="module" )
def retired_doors():
    """The tombstone table, read from the module that owns it rather than restated."""
    from cosa.rest.routers._retired_doors import RETIRED_DOORS
    return RETIRED_DOORS


def _concrete( path ):
    """Substitute a value for any path parameter so the route matches."""
    return path.replace( "{job_id}", "abc123" ).replace( "{id_hash}", "abc123" )


def test_the_real_app_mounts_every_retired_door( real_app, retired_doors ):
    """A tombstone that main.py does not mount is a 404, which teaches a caller nothing."""
    mounted = { route.path for route in real_app.routes if "POST" in getattr( route, "methods", set() ) }
    missing = sorted( path for path in retired_doors if path not in mounted )
    assert not missing, (
        f"main.py does not mount {missing} — the tombstones exist in the router but the "
        f"server does not serve them, so a stale caller gets 404 and learns nothing"
    )


def test_the_real_app_still_mounts_the_door_every_refusal_names( real_app, retired_doors ):
    """A refusal pointing at a route the SERVER does not serve is a refusal pointing at nothing."""
    mounted = { route.path for route in real_app.routes if "POST" in getattr( route, "methods", set() ) }
    for path, replacement in retired_doors.items():
        assert replacement in mounted, (
            f"{path} refuses by naming {replacement}, which main.py does not mount"
        )


@pytest.mark.parametrize( "door_index", [ 0, 1 ], ids=[ "door_0", "door_1" ] )
def test_each_retired_door_refuses_through_the_real_app( door_index, real_client, retired_doors ):
    """410, and a body that both names the replacement and says the removal date.

    One reported case per door, per the plan: *"a loop that silently covers fifteen is
    how door 8 stayed invisible for a day."* Indexed rather than parametrised over the
    table directly because the table is a fixture, and a fixture cannot parametrise ids.
    """
    paths = sorted( retired_doors )
    if door_index >= len( paths ):
        pytest.skip( f"only {len( paths )} doors retired at this commit" )
    path = paths[ door_index ]

    response = real_client.post( _concrete( path ), json={} )
    assert response.status_code == 410, (
        f"{path} answered {response.status_code} through the REAL app, not 410 — "
        f"the router refuses but the server does not. body: {response.text[ :200 ]}"
    )

    body = response.json()
    assert isinstance( body, dict ) and "detail" in body, (
        f"{path} answered 410 through the real app but returned a result, not a refusal: {body!r}"
    )
    detail = body[ "detail" ]
    assert retired_doors[ path ] in detail, f"{path}'s refusal does not name {retired_doors[ path ]}: {detail!r}"
    assert "2026-12-31" in detail, f"{path}'s refusal omits the removal date: {detail!r}"


def test_every_retired_door_is_covered_by_a_case( retired_doors ):
    """The anti-loop guard: if a door is added to the table, a case must be added here.

    ⚠️ The parametrisation above is fixed at two ids. That is deliberate — a
    table-driven loop grows silently and covers the new door with no new reported
    case. This test fails the moment the table outgrows the cases, naming the gap.
    """
    assert len( retired_doors ) == 2, (
        f"the tombstone table now holds {len( retired_doors )} doors: {sorted( retired_doors )}. "
        f"Add a case id to test_each_retired_door_refuses_through_the_real_app for each new door, "
        f"then update this count — do NOT widen the parametrisation into an open loop."
    )
