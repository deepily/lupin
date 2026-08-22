"""
Step 11a — the two question-shaped queue doors each answer 410 Gone.

RICK'S RULING, 2026-08-21: the doors are *"gone permanently, with the new door named …
dead by the end of the year."* Each route stays registered and refuses; the refusal
names its replacement and says REMOVE BY 2026-12-31 out loud.

WHY NOT ALL SIXTEEN AT ONCE. The submit-shaped doors could not retire while
`/api/v2/submit` did not exist — Cheech, 2026-08-21: *"a 410 that names a door that
does not exist yet is a refusal pointing at nothing."* They arrive one commit per door
now that it does, and now that it can BUILD what they hand over, which took wiring the
agentic reader into the flow: a door that exists is not a door that works. The set is
asserted below, so a table that quietly grows fails here, and the count test lists what
is still deliberately out.

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

from cosa.rest.routers._retired_doors import REMOVE_BY, RETIRED_DOORS, V2_ASK, V2_SUBMIT
from cosa.rest.routers import (
    bug_fix_expediter, deep_research, deep_research_to_podcast,
    deep_research_to_presentation, podcast_generator, presentation_generator, queues,
    swe_team, v2_ask,
)

_ROUTER_MODULES = ( bug_fix_expediter, deep_research, deep_research_to_podcast,
                    deep_research_to_presentation, podcast_generator,
                    presentation_generator, queues, swe_team, v2_ask )


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

def test_exactly_nine_doors_are_retired_at_this_commit():
    """
    THE COUNT IS RESTATED BY HAND ON PURPOSE, and it is the third of the three edits
    every new door costs (table row, this set, this name). A loop that silently covered
    whatever the table happened to hold is how door 8 stayed invisible for a day —
    clearing a red here by widening this into something derived removes the guard rather
    than satisfying it.

    Two question-shaped doors retired first, when `ask` was the only live replacement.
    `/api/bug-fix-expediter/submit` was the first submit-shaped one, and the three research
    doors followed together because ONE UI function submits to all three — retiring them
    one at a time would have meant editing that function three times, each edit leaving it
    half cut over. They could retire at all only once `/api/v2/submit` both existed AND
    could build an agentic job — it could not until the
    agentic reader was wired into the flow, and a refusal naming a door that answers "I
    do not understand" is a refusal pointing at nothing.

    `/api/presentation-generator/submit` came seventh and one commit behind its own
    groundwork. It was the only door carrying a path-escape check that nothing downstream
    repeated, so the guard moved onto the job first and the tombstone followed — retiring
    the door in the same breath would have left a window with no check at all.

    `/api/podcast-generator/submit` came eighth and is the ONLY submit-shaped-looking door
    that retires into `ask` rather than `submit`. It was never really submit-shaped: its
    description path held a conversation — fuzzy-match the user's documents, ask which one
    they meant, ask for languages and audience, possibly answer "cancelled" — which is what
    `ask` does and what `submit` refuses to do by design. Rick ruled it directly: the
    accordion is retiring and Q&A is the entrance.

    `/api/swe-team/submit` came ninth and was the last lineage-aware v1 door. A monopolizing
    sweep's child pytest submits a swe-team dry-run and echoes the sweep's id_hash back as
    `parent_id_hash` so Gate B admits it through the monopoly hold; `/api/v2/submit` carries
    that field top-level and stamps it in the factory, so the sweep keeps working.

    STILL OUT, each for its own reason, because a door absent from this set should never
    read as one nobody got to:
      · `/api/upload-and-transcribe-mp3` — a speech-to-text endpoint that queues only on
        its agent branch; `ask` takes text, not audio, so it survives (door 8).
      · `/api/mock-job/submit` — its command exists in neither JOB_ARG_CONTRACTS nor the
        factory; the router builds MockAgenticJob itself, so `submit` cannot build one.
      · the two resume-from doors — they rebuild a job from server-side state, and a
        SubmitRequest can say command and args but never "resume job X".
      · `/api/test-suite/submit` — how the gate rig schedules a :8000 run, so retiring it
        early would take away the ability to gate. It lands last.
      · the Claude Code pair — Rick ruled it an UPGRADE to the v2 door, not a tombstone.
    """
    assert set( RETIRED_DOORS ) == {
        "/api/push",
        "/api/job-history/{job_id}/retry",
        "/api/bug-fix-expediter/submit",
        "/api/deep-research/submit",
        "/api/deep-research-to-podcast/submit",
        "/api/deep-research-to-presentation/submit",
        "/api/presentation-generator/submit",
        "/api/podcast-generator/submit",
        "/api/swe-team/submit",
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
    # Two replacements exist now, and which one a door gets is a real distinction rather
    # than bookkeeping: `ask` takes a bare question and works out what it means, `submit`
    # takes work whose command the caller already chose. This used to read
    # `== V2_ASK`, which was true when every retired door was question-shaped and would
    # have gone red the moment a submit-shaped one arrived — correctly, but by failing a
    # test rather than by saying what it meant.
    assert RETIRED_DOORS[ path ] in ( V2_ASK, V2_SUBMIT ), (
        f"{path} retires into {RETIRED_DOORS[ path ]!r}, which is neither v2 door"
    )


@pytest.mark.parametrize( "path", sorted( RETIRED_DOORS ), ids=sorted( RETIRED_DOORS ) )
def test_every_refusal_describes_the_door_it_names( path, client ):
    """
    The sentence has to match the door it sends people to, per row.

    WHY THIS IS NOT PEDANTRY. There are TWO live doors now, and they are not
    interchangeable: `ask` takes a bare question and works out what it means, `submit`
    takes work whose command the caller already chose. The refusal body read "Every
    question now enters through …" for every row — true while `ask` was the only
    replacement, and a coin flip the moment a submit-shaped door retired. A caller who
    reads "send your question to /api/v2/submit" has been taught the wrong one of two
    doors that both exist and both answer, which is worse than being told nothing.

    RED ON REVERT: collapse refusal_detail back to one sentence for both replacements and
    every submit-shaped row fails here by name (Pocholo, who asked for it per row rather
    than per fix).
    """
    detail   = client.post( _concrete( path ), json={} ).json()[ "detail" ]
    expected = { V2_ASK    : "Every question now enters through",
                 V2_SUBMIT : "Work whose command is already decided now enters through",
               }[ RETIRED_DOORS[ path ] ]
    assert expected in detail, (
        f"{path} retires into {RETIRED_DOORS[ path ]} but its refusal does not describe that "
        f"door: {detail!r}"
    )


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
