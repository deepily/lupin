"""
GET / PATCH / DELETE /api/tasks/flow-ratio/settings — the operator's ratio controls.

🔴 THE AUTH OVERRIDE IS THE WHOLE REASON THESE ASSERTIONS MEAN ANYTHING, and it is the
lesson from `test_task_routes_resolve_literal_paths.py` applied a second time: an
unauthenticated request answers 401 from the auth dependency BEFORE anything else can
matter, so a suite written without the override passes against almost any breakage. It
is green, it is well-named, and it reads the auth layer while reporting on the handler.

Which is also why the admin gate below is asserted by REMOVING the override rather than
by trusting the decorator: the only way to know a write is admin-only is to watch a
non-admin be refused.

⚠️ EVERY TEST POINTS THE SETTINGS MODULE AT A tmp_path. The override is a real file
under `fleet_data_root()`, shared by every process on this box — an un-isolated test
would move the LIVE fleet create gate.

🔴 WHAT THESE TESTS DO NOT COVER, NAMED HERE SO NOBODY READS A GREEN RUN AS MORE THAN
IT IS. The feature is proven by TWO legs that meet in the middle and never actually
touch:

    STORAGE   cross-container, real `override_path()`, no monkeypatch — a write inside
              lupin-rest-dev lands on the host file and lupin-rest-test reads it back.
              Bypasses HTTP entirely.
    AUTH      this file, in-process — `test_the_write_is_admin_only_and_the_read_is_not`
              drops the override so the REAL dependency runs and watches a non-admin be
              refused. Bypasses the filesystem entirely (tmp_path).

⇒ THE SEAM NOBODY HAS DRIVEN: a real ADMIN's PATCH, over HTTP, through the live auth
stack, persisting to the mounted path on a running server. Every test here overrides
`require_admin`, so no test in this repo has ever watched an admin write SUCCEED — only
a non-admin fail. The two legs together make that seam very likely to work; they do not
demonstrate it.

Not covered because no admin credential is available to the fleet: the only admin
accounts are `admin@lupin.deepily.ai` and Rick's own, and neither password is held here.
An admin test credential has been requested. Until it exists this gap is REAL and
stated, not quietly rounded down to "tested".

⚠️ The storage leg also cannot run here at all — it needs both containers up with the
`LUPIN_FLOW_RATIO_DIR` mount, which resolves at container CREATE. A green unit run says
nothing about whether that mount was ever applied.

Venue: :7999-eligible — in-process TestClient, no server, no network, tmp_path only.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cosa.rest import flow_ratio_settings as frs
from cosa.rest.auth_middleware import require_admin
from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt
from cosa.rest.routers import tasks as tasks_router


SETTINGS_PATH = "/api/tasks/flow-ratio/settings"


@pytest.fixture
def isolated( tmp_path, monkeypatch ):
    """Redirect the override file into tmp_path and reset the module's mtime cache."""
    target = tmp_path / "flow-ratio-settings.json"
    monkeypatch.setattr( frs, "override_path", lambda: str( target ) )
    monkeypatch.setattr( frs, "_cache", { "window_hours": None, "allow_below": None } )
    monkeypatch.setattr( frs, "_cache_mtime", None )
    return target


@pytest.fixture
def app():
    """The tasks router with BOTH guards overridden — see the module docstring."""
    application = FastAPI()
    application.include_router( tasks_router.router )
    application.dependency_overrides[ require_api_key_or_jwt ] = lambda: "test-user"
    application.dependency_overrides[ require_admin ]          = lambda: { "email": "admin@test" }
    return application


@pytest.fixture
def client( app ):
    return TestClient( app, raise_server_exceptions=False )


def test_the_settings_path_is_not_swallowed_by_the_task_id_route( client, isolated ):
    """
    The literal path reaches its own handler.

    `/api/tasks/flow-ratio` shipped registered BELOW `/api/tasks/{task_id}` and answered
    422 — "task reference ... is neither a UUID nor a hex id prefix" — for its entire
    life. These siblings are four segments to that route's three, so it cannot swallow
    them; asserted anyway, because the arithmetic is not what anyone will remember when
    the next route is added.
    """
    response = client.get( SETTINGS_PATH )
    assert response.status_code == 200
    assert "task reference" not in response.text


def test_get_reports_the_live_pair_and_its_provenance( client, isolated ):
    """
    The read carries the SOURCE of each value, not just the number.

    A number alone cannot tell an operator whether their config edit is in force or is
    being masked by a saved override — the one confusion a two-layer scheme creates.
    """
    body = client.get( SETTINGS_PATH ).json()
    # Widened 2026-09-02 for `enforcement_active` — Rick moved the gate's enforcement
    # switch out of a Python constant into this same settings layer, so the endpoint
    # reports THREE values and three provenances rather than two and two.
    #
    # Kept as an EXACT set rather than relaxed to a subset: that is what makes a field
    # joining this payload a deliberate act with a diff, and it is the assertion that
    # caught this very change.
    assert set( body ) == {
        "window_hours", "allow_below", "enforcement_active",
        "window_source", "threshold_source", "enforcement_source",
    }
    assert body[ "window_source" ]    == "config"
    assert body[ "threshold_source" ] == "config"


def test_patch_persists_and_the_read_agrees( client, isolated ):
    """A write is visible to the next read, and reported as an override."""
    written = client.patch( SETTINGS_PATH, json={ "allow_below": 1.4 } )
    assert written.status_code == 200
    assert written.json()[ "allow_below" ] == 1.4

    read = client.get( SETTINGS_PATH ).json()
    assert read[ "allow_below" ]       == 1.4
    assert read[ "threshold_source" ]  == "override"


def test_patch_is_a_partial_update_not_a_replace( client, isolated ):
    """An omitted field is left alone — a threshold write must not reset the window."""
    client.patch( SETTINGS_PATH, json={ "window_hours": 168, "allow_below": 1.25 } )
    body = client.patch( SETTINGS_PATH, json={ "allow_below": 0.8 } ).json()

    assert body[ "allow_below" ]  == 0.8
    assert body[ "window_hours" ] == 168


def test_a_body_naming_neither_field_is_refused( client, isolated ):
    """
    422 rather than a cheerful no-op.

    Reporting success for a request that changed nothing is how a slider appears to work
    while doing nothing at all.
    """
    response = client.patch( SETTINGS_PATH, json={} )
    assert response.status_code == 422
    assert "window_hours" in response.text


@pytest.mark.parametrize( "body", [
    { "window_hours" : 0        },     # below the floor
    { "window_hours" : 99_999   },     # above the ceiling
    { "allow_below"  : -1       },     # negative
    { "nonsense"     : 1        },     # unknown field — extra="forbid"
    { "allow_below"  : "banana" },     # not a number
    { "allow_below"  : 1_000_001 },    # above the ceiling — a LITERAL, see below
] )
def test_an_unusable_body_is_refused_at_the_door( client, isolated, body ):
    """
    Validation rejects rather than clamping silently at the API boundary.

    The module clamps because it must tolerate whatever is already on disk; the ENDPOINT
    refuses, because an operator who typed a number deserves to be told it was not the
    number applied.
    """
    assert client.patch( SETTINGS_PATH, json=body ).status_code == 422
    assert not isolated.exists(), "a refused request still wrote the override file"


def test_delete_clears_the_override_and_returns_to_config( client, isolated ):
    """The reset drops the override and reports config as the source again."""
    client.patch( SETTINGS_PATH, json={ "allow_below": 1.9 } )
    assert isolated.exists()

    body = client.delete( SETTINGS_PATH ).json()
    assert not isolated.exists()
    assert body[ "threshold_source" ] == "config"


def test_the_threshold_reaches_the_ratio_endpoints_verdict( client, isolated, monkeypatch ):
    """
    THE POINT OF THE WHOLE BUILD: one number, and the header obeys it.

    The verdict was `ratio < 1.0` hardcoded in the endpoint AND `ratio < 1.0` hardcoded
    in the create gate. This drives the SAME counts past a moved threshold and watches
    the verdict flip — which is only possible if the endpoint reads the operator's value
    rather than a literal.

    The repository is stubbed so the counts are fixed and the THRESHOLD is the only
    variable; a live count would let a passing test hide a frozen threshold.
    """
    class _Repo:
        def __init__( self, session ): pass
        def count_created_and_closed( self, since, project=None ):
            return { "created": 12, "closed": 10 }        # ratio 1.20

    monkeypatch.setattr( tasks_router, "TaskRepository", _Repo )
    monkeypatch.setattr( tasks_router, "get_db", _null_session )

    client.delete( SETTINGS_PATH )
    at_default = client.get( "/api/tasks/flow-ratio" ).json()
    assert at_default[ "ratio" ]       == 1.2
    assert at_default[ "allow_below" ] == 1.0
    assert at_default[ "verdict" ]     == "refuse"

    client.patch( SETTINGS_PATH, json={ "allow_below": 1.5 } )
    at_relaxed = client.get( "/api/tasks/flow-ratio" ).json()
    assert at_relaxed[ "ratio" ]       == 1.2, "the counts must not move — only the threshold"
    assert at_relaxed[ "allow_below" ] == 1.5
    assert at_relaxed[ "verdict" ]     == "allow", "the verdict ignored the operator's threshold"


def test_the_window_reaches_the_ratio_endpoint( client, isolated, monkeypatch ):
    """
    The endpoint counts over the OPERATOR's window when the caller names none.

    ⚠️ An explicit ?window_hours= still wins — the caller asked a specific question, and
    silently answering a different one would make the endpoint unusable for comparison.
    """
    seen = {}

    class _Repo:
        def __init__( self, session ): pass
        def count_created_and_closed( self, since, project=None ):
            seen[ "since" ] = since
            return { "created": 1, "closed": 1 }

    monkeypatch.setattr( tasks_router, "TaskRepository", _Repo )
    monkeypatch.setattr( tasks_router, "get_db", _null_session )

    client.patch( SETTINGS_PATH, json={ "window_hours": 168 } )
    assert client.get( "/api/tasks/flow-ratio" ).json()[ "window_hours" ] == 168

    explicit = client.get( "/api/tasks/flow-ratio?window_hours=24" ).json()
    assert explicit[ "window_hours" ] == 24, "an explicit window was overridden by the default"


def test_the_write_is_admin_only_and_the_read_is_not( isolated ):
    """
    A non-admin is REFUSED the write and still allowed the read.

    Asserted by dropping only the admin override, so the real dependency runs. Trusting
    the decorator would prove nothing — this is the same "run the broken arm underneath
    the guard" rule the routing tests learned: a gate nobody has watched refuse is a gate
    nobody has tested.

    ⇒ If this ever fails OPEN, any authenticated user can move the threshold the create
    gate refuses other people's rows on.
    """
    application = FastAPI()
    application.include_router( tasks_router.router )
    application.dependency_overrides[ require_api_key_or_jwt ] = lambda: "test-user"
    # require_admin deliberately NOT overridden.
    non_admin = TestClient( application, raise_server_exceptions=False )

    assert non_admin.get( SETTINGS_PATH ).status_code == 200
    assert non_admin.patch( SETTINGS_PATH, json={ "allow_below": 1.4 } ).status_code in ( 401, 403 )
    assert non_admin.delete( SETTINGS_PATH ).status_code in ( 401, 403 )
    assert not isolated.exists(), "a refused write still persisted an override"


class _NullSession:
    """Stands in for the DB session context manager — the repository is stubbed anyway."""
    def __enter__( self ): return None
    def __exit__( self, *args ): return False


def _null_session():
    return _NullSession()


def test_a_threshold_well_inside_the_ceiling_is_ACCEPTED( client, isolated ):
    """
    The upper clamp on `allow_below` was asserted NOWHERE, and lowering it from
    1000.0 to 10.0 left all fourteen tests in this file green (audit 2026-09-01,
    src/rnd/v0.2.1/2026.09.01-guard-audit-sixteen-files-run-against-broken-arms.md).
    Every value the file exercised — 1.4, 1.25, 0.8, 1.9, 1.0, -1, "banana" — sits
    below 10, so nothing could tell the two ceilings apart.

    🔴 THE DISCRIMINATING CASE IS AN ACCEPTANCE, NOT ANOTHER REFUSAL. Lowering the
    ceiling makes values in (new, old] newly REFUSED, so only a case asserting one is
    still ACCEPTED can see it. A second refusal case above the old ceiling stays
    refused under both and is blind by construction — which is the same reason the
    refusal case added above is written as the LITERAL 1_000_001 and not as
    `frs.MAX_ALLOW_BELOW + 1`: a bound derived from the constant moves WITH the
    constant, and the test would follow the defect rather than catch it.

    MEASURED, NOT ARGUED — two arms, ONE mutated state (MAX_ALLOW_BELOW 1000.0 -> 10.0),
    the only variable being how the two new cases are written:

        LITERAL   (500.0 and 1_000_001)                 -> 1 failed, 15 passed
                                                           and the failure NAMES this test
        DERIVED   (MAX/2 and MAX + 1)                    -> 16 passed — BLIND

    The derived variant moves with the constant, so it reports the mutated ceiling as
    correct. Neither arm alone would have shown that: a lone red proves only that a
    test can fail.
    """
    assert 500.0 < frs.MAX_ALLOW_BELOW, (
        "this case must sit INSIDE the ceiling or it stops testing what it says"
    )
    response = client.patch( SETTINGS_PATH, json={ "allow_below" : 500.0 } )
    assert response.status_code == 200, (
        f"a threshold well inside the ceiling was refused: {response.text}"
    )
    assert response.json()[ "allow_below" ] == 500.0
