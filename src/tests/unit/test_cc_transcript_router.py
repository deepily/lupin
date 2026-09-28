#!/usr/bin/env python3
"""
A2.2, A2.4, A2.9, A3.4, A3.6, A3.7 — the REST backlog door and the roster projection.

Plan: `src/rnd/v0.2.1/2026.09.27-console-tee-live-stream-plan.md` §2 item 4, §3.
Module under test: `cosa/rest/routers/cc_transcript.py`.

BOTH ARMS, ALWAYS
-----------------
A criterion naming only the negative arm is satisfiable by a gate that refuses EVERYBODY, so
every auth test here has a refusal AND an acceptance. The acceptance runs at the
`dependency_overrides[ require_admin ]` tier, which is a deliberate, Rick-ruled limitation, not
an oversight: the only admin accounts are `admin@lupin.deepily.ai` and Rick's own and the fleet
holds neither password, so no test in this repo has ever watched an admin write SUCCEED. That
tier proves the route WIRING, not the live auth stack. Stated here rather than rounded down.

Venue: :7999-eligible — in-process TestClient, `tmp_path` only, no network, sub-second.
"""

import json
import os
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.rest.auth_middleware import require_admin
from cosa.rest.routers import cc_transcript as module

SEAT = "449359bc-c735-4970-8fc0-e83b635c8548"


def _write_records( path, count, start=0 ):
    """Append `count` assistant text records, each carrying its index."""
    with open( path, "a" ) as f:
        for i in range( start, start + count ):
            f.write( json.dumps( {
                "type"      : "assistant",
                "timestamp" : "2026-09-27T18:00:00Z",
                "message"   : { "role": "assistant", "content": [ { "type": "text", "text": f"block {i}" } ] },
            } ) + "\n" )
    return os.path.getsize( path )


@pytest.fixture
def app():
    """A bare app carrying only this router — nothing else can colour the result."""
    application = FastAPI()
    application.include_router( module.router )
    return application


@pytest.fixture
def transcript( tmp_path, monkeypatch ):
    """
    A real transcript file, with the bridge resolver pointed at it.

    The resolver is patched in the ROUTER's namespace, which is where the handlers look it up.
    """
    path = tmp_path / f"{SEAT}.jsonl"
    path.write_text( "" )
    _write_records( path, 30 )
    monkeypatch.setattr( module, "resolve_transcript_path",
                         lambda session_id, *a, **k: str( path ) if session_id == SEAT else "" )
    return path


def _as_admin( app ):
    """A client whose require_admin dependency is satisfied — the positive arm's tier."""
    app.dependency_overrides[ require_admin ] = lambda: { "email": "admin@example.com", "roles": [ "admin" ] }
    return TestClient( app )


def _as_anonymous( app ):
    """A client with NO override, so the real dependency runs and refuses."""
    app.dependency_overrides.clear()
    return TestClient( app )


# ── A2.2 / A3.4: both arms, on both routes ────────────────────────────────────

@pytest.mark.parametrize( "path", [
    f"/api/cc-transcript/{SEAT}",
    "/api/cc-transcript-roster",
] )
def test_an_uncredentialed_caller_is_refused_on_both_routes( app, transcript, path ):
    """
    NEGATIVE arm. Both routes, parametrised, so a failure names WHICH door was open.

    The console carries everything the seat read — file contents, tool output, possibly secrets
    from a .env or a log — so an open door here is not a cosmetic defect.
    """
    response = _as_anonymous( app ).get( path )
    assert response.status_code in ( 401, 403 ), (
        f"{path} answered {response.status_code} to an uncredentialed caller"
    )


@pytest.mark.parametrize( "path", [
    f"/api/cc-transcript/{SEAT}",
    "/api/cc-transcript-roster",
] )
def test_an_admin_caller_is_accepted_on_both_routes( app, transcript, path, monkeypatch ):
    """
    POSITIVE arm, at the override tier.

    Without this, "the gate refuses a non-admin" is satisfied by a route that refuses everyone —
    a 100%-secure endpoint that also does not work.
    """
    monkeypatch.setattr( module, "_fetch_fleet_state", _fleet_state_stub( [ ] ) )
    response = _as_admin( app ).get( path )
    assert response.status_code == 200, f"{path} refused an admin: {response.status_code} {response.text}"


def test_the_gate_is_require_admin_on_both_routes( ):
    """
    Asks the ROUTES which dependency they carry, rather than restating the rule.

    CLAUDE.md § Tests: "A projection of a gate must ask the gate, not restate its rule." Two
    pieces of code deciding one rule agree until they do not.

    Asserted by OBJECT IDENTITY against `require_admin` itself, not by the name of the closure
    it returns. A first cut of this test matched on "check_all_roles" and failed — the closure
    is actually called `check_roles` — which is the same class of defect it is meant to catch: a
    check and the thing it checks agreeing on the field and disagreeing on the key. Identity
    cannot drift, and it also rejects a DIFFERENT role gate that happens to share the name.
    """
    for route in module.router.routes:
        calls = [ dependency.call for dependency in route.dependant.dependencies ]
        assert require_admin in calls, (
            f"{route.path} does not carry require_admin; its dependencies are "
            f"{[ getattr( c, '__name__', repr( c ) ) for c in calls ]}"
        )


# ── A2.9: the three directions, over the route ────────────────────────────────

def test_no_direction_given_opens_at_the_RULED_TAIL_not_the_start_of_the_file( app, transcript ):
    """
    The default is ruling Q6's LAST ~64 KB, not a forward read from 0.

    A forward default would hand a client with no prior offset the START of the file — silently
    contradicting Q6 while returning a plausible 200 with real blocks in it. That is the kind of
    defect that survives review, because nothing looks wrong.
    """
    client = _as_admin( app )
    default = client.get( f"/api/cc-transcript/{SEAT}" ).json()
    forward = client.get( f"/api/cc-transcript/{SEAT}", params={ "since_offset": 0 } ).json()

    size = os.path.getsize( transcript )
    assert default[ "next_offset" ] == size, "the default window did not reach the end of the file"
    assert forward[ "offset" ]      == 0
    # This fixture is far smaller than the 64 KB tail, so both windows are the whole file here.
    # The assertion that discriminates is the direction, checked below on a bounded tail.
    assert default[ "blocks" ][ -1 ][ "text" ] == "block 29"


def test_tail_bytes_reads_BACKWARD_and_since_offset_reads_forward( app, transcript ):
    """
    A2.9's discriminating arm, over HTTP.

    A forward-only implementation returns a plausible answer to both; only their difference
    shows which end was read.
    """
    client = _as_admin( app )
    half   = os.path.getsize( transcript ) // 2

    tail = client.get( f"/api/cc-transcript/{SEAT}", params={ "tail_bytes": half } ).json()
    head = client.get( f"/api/cc-transcript/{SEAT}", params={ "since_offset": 0, "max_bytes": half } ).json()

    assert tail[ "offset" ] > head[ "offset" ], "tail_bytes read FORWARD from the start"
    assert tail[ "next_offset" ] == os.path.getsize( transcript )
    assert tail[ "blocks" ][ -1 ][ "text" ] == "block 29", "the tail does not reach the last record"
    assert head[ "blocks" ][ 0 ][ "text" ]  == "block 0",  "the head does not reach the first record"


def test_before_offset_pages_earlier_and_never_crosses_its_bound( app, transcript ):
    """Ruling Q6's 'load earlier', and the two windows must not overlap."""
    client = _as_admin( app )
    half   = os.path.getsize( transcript ) // 2

    tail    = client.get( f"/api/cc-transcript/{SEAT}", params={ "tail_bytes": half } ).json()
    earlier = client.get( f"/api/cc-transcript/{SEAT}",
                          params={ "before_offset": tail[ "offset" ] } ).json()

    assert earlier[ "next_offset" ] <= tail[ "offset" ], "the backward page crossed its bound"
    assert earlier[ "blocks" ][ 0 ][ "text" ] == "block 0"

    texts = [ b[ "text" ] for b in earlier[ "blocks" ] ] + [ b[ "text" ] for b in tail[ "blocks" ] ]
    assert texts == [ f"block {i}" for i in range( 30 ) ], (
        "the backward page plus the tail do not reconstruct the file exactly — a record was "
        "dropped at the seam or served twice"
    )


def test_a_negative_offset_is_refused_by_validation_not_by_the_handler( app, transcript ):
    """
    The bounds are declared on the Query, so FastAPI answers 422 before the handler runs.

    Better than a hand-rolled if/raise: the contract is in the signature and appears in /docs.
    """
    client = _as_admin( app )
    for params in ( { "tail_bytes": -1 }, { "since_offset": -1 },
                    { "before_offset": -1 }, { "max_bytes": -1 } ):
        assert client.get( f"/api/cc-transcript/{SEAT}", params=params ).status_code == 422


# ── A2.4: the budget reaches the route's blocks ───────────────────────────────

def test_the_block_budget_is_applied_to_the_rest_body( app, tmp_path, monkeypatch ):
    """
    A2.4 over HTTP: a block past its budget arrives truncated and flagged.

    The budget is read from the INI, not hard-coded here — the AC's own requirement.
    """
    path = tmp_path / f"{SEAT}.jsonl"
    with open( path, "w" ) as f:
        f.write( json.dumps( {
            "type"    : "assistant",
            "message" : { "role": "assistant", "content": [ { "type": "text", "text": "w" * 40000 } ] },
        } ) + "\n" )

    monkeypatch.setattr( module, "resolve_transcript_path", lambda *a, **k: str( path ) )
    monkeypatch.setattr( module, "load_settings",
                         lambda *a, **k: { "backlog_tail_bytes": 65536, "block_budget_bytes": 120 } )

    body  = _as_admin( app ).get( f"/api/cc-transcript/{SEAT}" ).json()
    block = body[ "blocks" ][ 0 ]
    assert block[ "truncated" ] is True
    assert len( block[ "text" ] ) == 120


# ── a seat with no transcript ─────────────────────────────────────────────────

def test_a_seat_with_no_resolvable_transcript_answers_200_and_says_it_is_not_watchable( app, monkeypatch ):
    """
    "This seat is not printing" is an ANSWER, not an error.

    A 404 would be wrong: the seat may exist and simply have no transcript yet, and the client
    needs to distinguish that from a bad request.
    """
    monkeypatch.setattr( module, "resolve_transcript_path", lambda *a, **k: "" )
    body = _as_admin( app ).get( "/api/cc-transcript/some-unknown-seat" ).json()
    assert body == {
        "cc_session_id" : "some-unknown-seat",
        "file_epoch"    : None,
        "offset"        : 0,
        "next_offset"   : 0,
        "blocks"        : [ ],
        "watchable"     : False,
    }


def test_the_body_names_the_seat_and_the_epoch_it_belongs_to( app, transcript ):
    """
    `file_epoch` scopes every offset, so a body without it hands the client an unscoped number.
    """
    body = _as_admin( app ).get( f"/api/cc-transcript/{SEAT}" ).json()
    assert body[ "cc_session_id" ] == SEAT
    assert body[ "file_epoch" ]    == SEAT, "the epoch should be the transcript file's own uuid"
    assert body[ "watchable" ] is True
    assert set( body ) == { "cc_session_id", "file_epoch", "offset", "next_offset", "blocks", "watchable" }


# ── A3.4 / A3.7: the roster projection ────────────────────────────────────────

def _fleet_state_stub( sessions, status="ok" ):
    """
    A stand-in for the fleet composite, shaped as `/arbiter/fleet-state` really returns it.

    The roster lives under `fleet_arbiter.sessions`, and that section is None on the
    unreachable envelope — which is the shape A3.7 turns on.
    """
    async def _stub( *args, **kwargs ):
        if status == "unreachable":
            return { "status": "unreachable", "detail": "ConnectError: refused",
                     "health_watcher": None, "fleet_arbiter": None }
        return { "status": status, "fleet_arbiter": { "sessions": sessions } }
    return _stub


def test_the_roster_projects_project_last_ts_and_transcript_watchable( app, monkeypatch, tmp_path ):
    """
    A3.4 — the three fields the console needs, alongside the fleet-state ones.
    """
    live = tmp_path / f"{SEAT}.jsonl"
    live.write_text( "" )

    monkeypatch.setattr( module, "_fetch_fleet_state", _fleet_state_stub( [
        { "stable_session_id": SEAT, "persona": "Krishna", "project": "lupin",
          "last_ts": "2026-09-27T19:00:00Z" },
        { "stable_session_id": "dead-seat-no-file", "persona": "Nobody", "project": "lupin",
          "last_ts": "2026-09-27T18:00:00Z" },
    ] ) )
    monkeypatch.setattr( module, "resolve_transcript_path",
                         lambda session_id, *a, **k: str( live ) if session_id == SEAT else "" )

    body = _as_admin( app ).get( "/api/cc-transcript-roster" ).json()
    assert body[ "status" ]        == "ok"
    assert body[ "session_count" ] == 2

    watchable, unwatchable = body[ "seats" ]
    assert watchable[ "project" ]              == "lupin"
    assert watchable[ "last_ts" ]              == "2026-09-27T19:00:00Z"
    assert watchable[ "transcript_watchable" ] is True
    assert watchable[ "file_epoch" ]           == SEAT

    assert unwatchable[ "transcript_watchable" ] is False, "a seat with no transcript is not watchable"
    assert unwatchable[ "file_epoch" ] is None


def test_an_unreachable_arbiter_is_distinguishable_from_an_empty_fleet( app, monkeypatch ):
    """
    A3.7, with its discriminator.

    `/arbiter/fleet-state` answers HTTP 200 with {"status": "unreachable"} when :8001 is down —
    the proxy is up, the upstream is not. A projection that mapped that to [] would report a
    healthy, empty fleet and NOBODY WOULD GO LOOKING FOR THE ARBITER. The empty-fleet arm below
    is what makes this assertion mean something.
    """
    monkeypatch.setattr( module, "_fetch_fleet_state", _fleet_state_stub( [ ], status="unreachable" ) )
    down = _as_admin( app ).get( "/api/cc-transcript-roster" ).json()

    monkeypatch.setattr( module, "_fetch_fleet_state", _fleet_state_stub( [ ] ) )
    empty = _as_admin( app ).get( "/api/cc-transcript-roster" ).json()

    assert down[ "status" ]  == "unreachable"
    assert empty[ "status" ] == "ok"
    assert down[ "status" ] != empty[ "status" ], "an unreachable arbiter reads as an empty fleet"
    assert down[ "seats" ] == empty[ "seats" ] == [ ]
    assert down[ "detail" ], "the unreachable envelope lost the reason"


@pytest.mark.parametrize( "state", [
    { "status": "ok" },                                     # no fleet_arbiter section at all
    { "status": "ok", "fleet_arbiter": None },              # the awaiting shape
    { "status": "ok", "fleet_arbiter": { } },               # present but no sessions
    { "status": "ok", "fleet_arbiter": { "sessions": None } },
    { "status": "ok", "fleet_arbiter": "not a dict" },
    { "status": "ok", "fleet_arbiter": { "sessions": "not a list" } },
] )
def test_a_malformed_fleet_section_reads_as_no_sessions_rather_than_crashing( app, monkeypatch, state ):
    """
    Every shape the composite is known to take, including the `awaiting` one.

    Parametrised so a failure names WHICH shape broke the projection.
    """
    async def _stub( *args, **kwargs ):
        return state
    monkeypatch.setattr( module, "_fetch_fleet_state", _stub )

    body = _as_admin( app ).get( "/api/cc-transcript-roster" ).json()
    assert body[ "status" ]        == "ok"
    assert body[ "seats" ]         == [ ]
    assert body[ "session_count" ] == 0


def test_a_non_dict_fleet_state_reads_as_unreachable( app, monkeypatch ):
    """A composite that is not even a dict must not crash the roster."""
    async def _stub( *args, **kwargs ):
        return [ "not", "a", "dict" ]
    monkeypatch.setattr( module, "_fetch_fleet_state", _stub )
    body = _as_admin( app ).get( "/api/cc-transcript-roster" ).json()
    assert body[ "status" ] == "unreachable"
    assert body[ "detail" ] is None


def test_a_non_dict_session_entry_is_skipped_not_fatal( app, monkeypatch ):
    """One junk row must not cost the whole roster."""
    monkeypatch.setattr( module, "resolve_transcript_path", lambda *a, **k: "" )
    monkeypatch.setattr( module, "_fetch_fleet_state", _fleet_state_stub( [
        "a bare string", None, 42,
        { "session_id": "real-seat", "project": "lupin" },
    ] ) )
    body = _as_admin( app ).get( "/api/cc-transcript-roster" ).json()
    assert [ row[ "session_id" ] for row in body[ "seats" ] ] == [ "real-seat" ]
    assert body[ "session_count" ] == 4, "session_count reports the FLEET's count, not the projected rows'"


def test_a_session_with_neither_id_field_projects_an_empty_id_and_is_unwatchable( app, monkeypatch ):
    """
    A row with no id cannot be watched, and must not be silently dropped either — a dropped row
    is a seat that vanished from the roster with no explanation.
    """
    monkeypatch.setattr( module, "_fetch_fleet_state", _fleet_state_stub( [ { "project": "lupin" } ] ) )
    row = _as_admin( app ).get( "/api/cc-transcript-roster" ).json()[ "seats" ][ 0 ]
    assert row[ "session_id" ] == ""
    assert row[ "transcript_watchable" ] is False


# ── A3.6: one string at one width, across the two surfaces ────────────────────

def test_the_seat_id_is_one_string_at_one_width_across_the_roster_and_the_stream( app, tmp_path, monkeypatch ):
    """
    A3.6, from a FIXTURED bridge — no live seat, so the check is deterministic.

    Three id widths circulate in this fleet: the full stable_session_id, `sender_id`'s 8-hex
    suffix, and a DM's `recipient_session_hash8`. A silent mismatch shows up as a roster row
    that cannot be watched, and it is asserted ACROSS the two surfaces rather than within one —
    within one surface the comparison is a tautology.
    """
    live = tmp_path / f"{SEAT}.jsonl"
    live.write_text( "" )
    _write_records( live, 2 )

    monkeypatch.setattr( module, "resolve_transcript_path",
                         lambda session_id, *a, **k: str( live ) if session_id == SEAT else "" )
    monkeypatch.setattr( module, "_fetch_fleet_state", _fleet_state_stub( [
        { "stable_session_id": SEAT, "project": "lupin", "last_ts": "2026-09-27T19:00:00Z" },
    ] ) )

    client       = _as_admin( app )
    roster_id    = client.get( "/api/cc-transcript-roster" ).json()[ "seats" ][ 0 ][ "session_id" ]
    stream_id    = client.get( f"/api/cc-transcript/{roster_id}" ).json()[ "cc_session_id" ]

    assert roster_id == stream_id == SEAT
    assert len( roster_id ) == 36, f"the roster id is {len( roster_id )} chars, not a full uuid"
    assert client.get( f"/api/cc-transcript/{roster_id}" ).json()[ "watchable" ] is True, (
        "the roster advertised a watchable seat that the stream route cannot serve — the "
        "id-width mismatch A3.6 exists to catch"
    )


def test_the_roster_prefers_the_stable_id_over_the_transient_one( app, monkeypatch ):
    """
    `cc_session_id` is the STABLE id — the one that survives a `/clear`.

    A row carrying both must project the stable one, or every watch breaks at the next clear.
    """
    monkeypatch.setattr( module, "resolve_transcript_path", lambda *a, **k: "" )
    monkeypatch.setattr( module, "_fetch_fleet_state", _fleet_state_stub( [
        { "session_id": "transient-post-clear-id", "stable_session_id": SEAT },
    ] ) )
    row = _as_admin( app ).get( "/api/cc-transcript-roster" ).json()[ "seats" ][ 0 ]
    assert row[ "session_id" ] == SEAT


def test_the_roster_falls_back_to_session_id_when_there_is_no_stable_one( app, monkeypatch ):
    """Older fleet rows carry only `session_id`; they are still listable."""
    monkeypatch.setattr( module, "resolve_transcript_path", lambda *a, **k: "" )
    monkeypatch.setattr( module, "_fetch_fleet_state", _fleet_state_stub( [
        { "session_id": "only-this-one" },
    ] ) )
    row = _as_admin( app ).get( "/api/cc-transcript-roster" ).json()[ "seats" ][ 0 ]
    assert row[ "session_id" ] == "only-this-one"


@pytest.mark.parametrize( "session,expected_ts", [
    ( { "session_id": "s", "last_ts": "A" },   "A" ),
    ( { "session_id": "s", "last_seen": "B" }, "B" ),
    ( { "session_id": "s" },                   None ),
] )
def test_last_ts_accepts_either_field_the_fleet_uses( app, monkeypatch, session, expected_ts ):
    """The composite has used both names; the projection reads either rather than guessing one."""
    monkeypatch.setattr( module, "resolve_transcript_path", lambda *a, **k: "" )
    monkeypatch.setattr( module, "_fetch_fleet_state", _fleet_state_stub( [ session ] ) )
    row = _as_admin( app ).get( "/api/cc-transcript-roster" ).json()[ "seats" ][ 0 ]
    assert row[ "last_ts" ] == expected_ts


@pytest.mark.parametrize( "session,expected", [
    ( { "session_id": "s", "persona": "Krishna" },      "Krishna" ),
    ( { "session_id": "s", "persona_name": "Rio" },     "Rio" ),
    ( { "session_id": "s" },                            None ),
] )
def test_persona_accepts_either_field_the_fleet_uses( app, monkeypatch, session, expected ):
    """Same two-name tolerance for the persona, which the UI labels rows with."""
    monkeypatch.setattr( module, "resolve_transcript_path", lambda *a, **k: "" )
    monkeypatch.setattr( module, "_fetch_fleet_state", _fleet_state_stub( [ session ] ) )
    row = _as_admin( app ).get( "/api/cc-transcript-roster" ).json()[ "seats" ][ 0 ]
    assert row[ "persona" ] == expected


# ── the fleet-state fetch reuses the arbiter handler ──────────────────────────

@pytest.mark.asyncio
async def test_the_fetch_reuses_the_arbiter_handler_rather_than_re_pulling_8001( monkeypatch ):
    """
    ONE place knows the upstream URL, the timeout and the unreachable envelope's shape.

    A second implementation would be a second thing to keep in step, and the two would agree
    until they did not.
    """
    import cosa.rest.routers.arbiter as arbiter_module

    called = { }

    async def fake_get_fleet_state( authenticated_user_id ):
        called[ "as" ] = authenticated_user_id
        return { "status": "ok", "fleet_arbiter": { "sessions": [ ] } }

    monkeypatch.setattr( arbiter_module, "get_fleet_state", fake_get_fleet_state )
    state = await module._fetch_fleet_state()
    assert state[ "status" ] == "ok"
    assert called[ "as" ], "the arbiter handler was not called"


@pytest.mark.asyncio
async def test_a_raising_arbiter_handler_becomes_an_unreachable_envelope( monkeypatch ):
    """
    The roster degrades rather than 500-ing when the composite cannot be read at all.

    A 500 here would take the console's entry point down because a monitoring service is down.
    """
    import cosa.rest.routers.arbiter as arbiter_module

    async def boom( authenticated_user_id ):
        raise RuntimeError( "upstream exploded" )

    monkeypatch.setattr( arbiter_module, "get_fleet_state", boom )
    state = await module._fetch_fleet_state()
    assert state[ "status" ] == "unreachable"
    assert "RuntimeError" in state[ "detail" ]


# ── the route shapes themselves ───────────────────────────────────────────────

# The two routes and the verb every arm in this file sends. Pinned as constants so the METHOD
# is asserted against the route table rather than assumed — a door that moved to POST would
# otherwise leave the path assertions GREEN and redden the auth arms with a message about
# permissions, which is a routing change wearing a permissions failure and sends the next
# reader into innocent code. Worked example: test_rick_alone_promotes_and_demotes.py.
SEAT_PATH     = "/api/cc-transcript/{cc_session_id}"
ROSTER_PATH   = "/api/cc-transcript-roster"
CONSOLE_METHOD = "GET"


def _methods_mounted_for( path ):
    """
    The HTTP verbs the route table actually mounts for one path.

    Ensures:
        - returns the union of every matching route's `.methods`
        - returns an empty set when nothing matches, so the caller's assertion names the path
    """
    matching = [ route for route in module.router.routes if route.path == path ]
    return set().union( *( getattr( route, "methods", set() ) or set() for route in matching ) ) \
        if matching else set()


@pytest.mark.parametrize( "path", [ SEAT_PATH, ROSTER_PATH ] )
def test_each_route_is_mounted_for_the_verb_these_arms_send( path ):
    """
    ASKS THE ROUTE TABLE for the verb rather than restating what I believe it is.

    Every other test in this file sends GET. If a door moved to POST, those arms would answer
    405 and their messages would talk about auth — so the verb is pinned here, by name.
    """
    mounted = _methods_mounted_for( path )
    assert mounted, f"{path} is not mounted at all"
    assert CONSOLE_METHOD in mounted, (
        f"{path} is mounted for {sorted( mounted )} and these arms send {CONSOLE_METHOD}. "
        f"Every arm below would answer 405 — a routing change wearing a permissions failure."
    )


def test_the_roster_is_a_sibling_path_that_cannot_collide_with_the_seat_route( ):
    """
    The collision this module was shaped to avoid, asserted so nobody "tidies" it back.

    `/api/cc-transcript/roster` would ALSO match `/api/cc-transcript/{cc_session_id}`, and which
    one wins depends on decorator order — correct today, silently broken after a reorder, with
    the symptom being a roster request answered as a lookup for a seat named "roster".
    """
    paths = { route.path for route in module.router.routes }
    assert ROSTER_PATH in paths
    assert "/api/cc-transcript/roster" not in paths
    assert SEAT_PATH in paths


def test_the_seat_route_would_have_swallowed_a_roster_subpath( app, monkeypatch ):
    """
    PROVES the collision is real rather than theoretical.

    Requesting the sub-path that was NOT used resolves to the seat route, with "roster" read as
    a session id. That is exactly the silent failure the sibling path avoids.
    """
    monkeypatch.setattr( module, "resolve_transcript_path", lambda *a, **k: "" )
    body = _as_admin( app ).get( "/api/cc-transcript/roster" ).json()
    assert body[ "cc_session_id" ] == "roster", (
        "the sub-path did not fall through to the seat route — re-check the collision claim"
    )
    assert body[ "blocks" ] == [ ]


def test_both_routes_are_registered_on_the_real_app_not_only_in_this_test( ):
    """
    Drive the assembled app, not only the router.

    A component can be complete, correct, fully covered and NEVER MOUNTED, and every test that
    builds the component stays green (CLAUDE.md § Tests). This asserts main.py includes it.
    """
    main_py = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src", "lupin_app", "main.py" )
    with open( main_py, "r" ) as f:
        source = f.read()
    assert "cc_transcript" in source, "the router is not imported in main.py"
    assert "app.include_router(cc_transcript.router)" in source, "the router is never mounted"
