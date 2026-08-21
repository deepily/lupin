"""
Step 11a — the two question-shaped queue doors each answer 410 Gone.

RICK'S RULING, 2026-08-21: the doors are *"gone permanently, with the new door named …
dead by the end of the year."* Each route stays registered and refuses; the refusal
names its replacement and says REMOVE BY 2026-12-31 out loud.

WHY TWO AND NOT SIXTEEN. `/api/v2/submit` is not built yet, so the twelve
submit-shaped doors would refuse by naming a route that answers 404 — Cheech,
2026-08-21: *"a 410 that names a door that does not exist yet is a refusal pointing at
nothing."* They land with the commit that builds `submit`. And a third door,
`/api/upload-and-transcribe-mp3`, came back out on inspection: it is a speech-to-text
endpoint that queues only on its `munger.is_agent()` branch, so `/api/v2/ask` — which
takes text, not audio — cannot replace it. The set is asserted below, so a table that
quietly grows fails here.

ONE TEST PER DOOR, ON PURPOSE. The plan's words: *"a loop that silently covers fifteen
is how door 8 stayed invisible for a day."* Every check is parametrised over
RETIRED_DOORS, so pytest reports a named result per door rather than one aggregate.

AND THE TABLE ITSELF IS CHECKED, not trusted. `test_every_retired_path_is_actually_
registered` resolves each key against the routes FastAPI really mounted, so a typo in
the table cannot produce a green run over a path nobody serves.

No auth is set up here, deliberately: a tombstone must refuse an unauthenticated caller
with the same 410 an authenticated one gets. If a stub ever regains
`Depends( get_current_user )`, these tests go red with 401 and name the door.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cosa.rest.routers._retired_doors import REMOVE_BY, RETIRED_DOORS, V2_ASK
from cosa.rest.routers import queues, v2_ask

_ROUTER_MODULES = ( queues, v2_ask )


def _app():
    app = FastAPI()
    for module in _ROUTER_MODULES:
        app.include_router( module.router )
    return app


@pytest.fixture( scope="module" )
def client():
    """One app carrying every router that holds a retired door."""
    return TestClient( _app(), raise_server_exceptions=False )


@pytest.fixture( scope="module" )
def registered_post_paths():
    """Every POST path FastAPI actually mounted, from the app itself."""
    return { route.path for route in _app().routes if "POST" in getattr( route, "methods", set() ) }


def _concrete( path ):
    """Substitute a value for any path parameter so the route matches."""
    return path.replace( "{job_id}", "abc123" ).replace( "{id_hash}", "abc123" )


# ── the count, stated once so a growing table cannot pass quietly ────────────

def test_exactly_two_doors_are_retired_in_this_commit():
    """
    Only the question-shaped doors retire here, because only their replacement exists.

    Eighteen doors put work on the queue and sixteen die, but twelve of those sixteen
    hand over work whose command is already decided — they belong to `/api/v2/submit`,
    which is not built yet. `/api/upload-and-transcribe-mp3` is out for a different
    reason: it transcribes audio and queues only when the munger says the transcription
    is an agent request, so `ask` cannot stand in for it. The Claude Code pair
    (`/api/claude-code/submit` and its alias `/api/claude-code/queue/submit`, one
    handler) is held for a third: Rick ruled the same day that a Claude Code job must be
    UPGRADED to the v2 front door, not left to die on the vine.
    """
    assert set( RETIRED_DOORS ) == {
        "/api/push",
        "/api/job-history/{job_id}/retry",
    }, sorted( RETIRED_DOORS )


def test_no_refusal_names_a_door_that_does_not_exist_yet( registered_post_paths ):
    """
    The rule that shaped this commit, pinned so the next person cannot break it quietly.

    Every replacement named in the table must be a route this app actually serves. That
    is what stops a tombstone from refusing a caller by pointing at a 404 — and it is
    the check that will go red the moment someone adds a submit-shaped door to the table
    before `/api/v2/submit` is built.
    """
    for path, replacement in RETIRED_DOORS.items():
        assert replacement in registered_post_paths, (
            f"{path} refuses by naming {replacement}, which nothing mounts. "
            f"Build the replacement first, or leave the door alone."
        )


def test_the_v2_doors_are_not_retired():
    for survivor in ( "/api/v2/ask", "/api/v2/resume" ):
        assert survivor not in RETIRED_DOORS, f"{survivor} survives — it must not be tombstoned"


# ── one result per door ──────────────────────────────────────────────────────

@pytest.mark.parametrize( "path", sorted( RETIRED_DOORS ), ids=sorted( RETIRED_DOORS ) )
def test_every_retired_path_is_actually_registered( path, registered_post_paths ):
    """A typo in the table must not produce a green run over a path nobody serves."""
    assert path in registered_post_paths, (
        f"{path} is in RETIRED_DOORS but no router mounts it — fix the table, not the test"
    )


@pytest.mark.parametrize( "path", sorted( RETIRED_DOORS ), ids=sorted( RETIRED_DOORS ) )
def test_every_retired_door_answers_410( path, client ):
    response = client.post( _concrete( path ), json={} )
    assert response.status_code == 410, (
        f"{path} answered {response.status_code}, not 410 — "
        f"body: {response.text[ :200 ]}"
    )


@pytest.mark.parametrize( "path", sorted( RETIRED_DOORS ), ids=sorted( RETIRED_DOORS ) )
def test_every_refusal_body_is_a_refusal_and_not_a_result( path, client ):
    """
    The status code alone does NOT prove a door refuses.

    Each stub carries `status_code = 410` in its decorator so `/docs` advertises the
    right answer. That makes the status a property of the ROUTE, not of the handler:
    a stub whose body was quietly restored to accept work and `return { "status":
    "queued" }` still answers 410, and the status check above stays green while the
    door is live again. Found by mutation on 2026-08-21 — `/api/push` was made to
    return a queued result and only the content checks went red, by KeyError, naming
    nothing.

    So assert the SHAPE of the body: a refusal carries `detail`. A door that starts
    returning a result fails here, by name.
    """
    body = client.post( _concrete( path ), json={} ).json()
    assert isinstance( body, dict ) and "detail" in body, (
        f"{path} answered 410 but its body is not a refusal — it returned {body!r}. "
        f"The 410 comes from the decorator; check the handler still calls gone()."
    )


@pytest.mark.parametrize( "path", sorted( RETIRED_DOORS ), ids=sorted( RETIRED_DOORS ) )
def test_every_refusal_names_the_door_that_replaces_it( path, client ):
    detail = client.post( _concrete( path ), json={} ).json()[ "detail" ]
    assert RETIRED_DOORS[ path ] in detail, (
        f"{path}'s refusal does not name {RETIRED_DOORS[ path ]}: {detail!r}"
    )
    assert RETIRED_DOORS[ path ] == V2_ASK


# The date, written out. NOT `REMOVE_BY` — asserting the constant appears in a string the
# constant was interpolated into is a tautology: Pocholo mutated REMOVE_BY to "" and the
# test stayed green, because "" is a substring of every string. The plan's verification row
# says the BODY contains the date, so the test says the date.
REMOVAL_DATE = "2026-12-31"


def test_the_constant_still_holds_the_date_this_suite_checks_for():
    """
    The one place the constant is compared to the literal, so the two cannot drift apart
    silently. If the removal date is ever moved, this fails and points at every other
    assertion that needs updating with it.
    """
    assert REMOVE_BY == REMOVAL_DATE


@pytest.mark.parametrize( "path", sorted( RETIRED_DOORS ), ids=sorted( RETIRED_DOORS ) )
def test_every_refusal_says_the_removal_date_out_loud( path, client ):
    detail = client.post( _concrete( path ), json={} ).json()[ "detail" ]
    assert REMOVAL_DATE in detail, f"{path}'s refusal omits {REMOVAL_DATE}: {detail!r}"
    assert "REMOVE BY" in detail, f"{path}'s refusal omits the words REMOVE BY: {detail!r}"
