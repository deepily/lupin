#!/usr/bin/env python3
"""
Unit tests for the task-store router — /api/tasks/* (cosa.rest.routers.tasks).

Minimal FastAPI app mounting ONLY the tasks router, with require_api_key_or_jwt
overridden and the get_db/TaskRepository seams monkeypatched — exercises HTTP
routing, structural-rule enforcement at the wire (422 with EVERY violation),
404s, and serialization without auth DB or Postgres (:7999-eligible).

100% lines/branches/functions of routers/tasks.py. All handlers are sync `def`
(C4 debt-clean) — TestClient drives them through the threadpool exactly as
production does.
"""
import os
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.rest.postgres_models import TaskItem, TaskEvent
from cosa.rest.routers import tasks
from cosa.rest import task_store_rules as rules
from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt

NOW = datetime( 2026, 6, 12, 0, 0, tzinfo=timezone.utc )


def make_item( **overrides ):
    fields = dict(
        id                  = uuid.uuid4(),
        item_class          = "task",
        title               = "build the store",
        body                = None,
        project             = "lupin",
        owner_persona       = "krishna",
        accountable_manager = "tiberius",
        created_by          = "krishna 38d15e3b",
        status              = "queued",
        blocked_by          = [ ],
        next_chase_ts       = None,
        gate_class          = "none",
        priority            = "P2",
        source_qid          = None,
        correlation_key     = None,
        created_ts          = NOW,
        updated_ts          = NOW,
        # Explicit, because a SQLAlchemy column `default` fires at INSERT and
        # NOT at construction — an unset flag here would reach the serializer as
        # None and serialize as null, which is neither True nor False.
        title_trimmed       = False,
    )
    fields.update( overrides )
    return TaskItem( **fields )


def make_event( item_id, **overrides ):
    fields = dict(
        id           = 1,
        item_id      = item_id,
        ts           = NOW,
        actor        = "krishna 38d15e3b",
        transition   = "->queued",
        receipt_refs = None,
        authority    = "standing",
    )
    fields.update( overrides )
    return TaskEvent( **fields )


@pytest.fixture
def repo( monkeypatch ):
    """Patch the router's get_db + TaskRepository seams; return the fake repo."""
    fake = MagicMock()
    # `total` (mini-plan 02 T1) is a REAL int on the list path — a bare MagicMock
    # would make `offset + count < total` a TypeError. Deliberately NOT derived
    # from query_tasks.return_value: a fixture that computed the total from the
    # page would hard-code the very identity these tests exist to falsify.
    fake.count_tasks.return_value = 0
    # `statuses_for_ids` must return a REAL dict for the same reason `total` must be a
    # real int (row 00a6bde2). A bare MagicMock is TRUTHY and supports no `in`, so
    # `blocker_is_terminal` would either raise or — worse — be reached only by rows that
    # happen to carry no item blocker, leaving the flag untested while the suite is green.
    # An empty map is also the honest default: no blocker was resolved, so no row can be
    # flagged, and any test that wants a finding sets this explicitly.
    fake.statuses_for_ids.return_value = { }
    # `count_tasks_by_project` must return a REAL dict for exactly the reasons above
    # (row d23147e8). The aperture disclosure calls `.items()` on it whenever a
    # `project=` filter is present; a bare MagicMock yields a MagicMock from
    # `.items()`, which iterates as nothing — so the disclosure would silently emit
    # no warning and every aperture assertion would pass against unfixed code. An
    # empty map is also the honest default: no other project exists, so nothing is
    # excluded, and a test wanting a finding sets this explicitly.
    fake.count_tasks_by_project.return_value = { }
    # Same reason again for the priority breakdown (Rick 2026-07-27): the count_only
    # branch returns it beside `breakdown`, and a MagicMock there would serialize as
    # a non-JSON object and 500 the route rather than failing an assertion cleanly.
    fake.count_tasks_by_priority.return_value = { }
    # `count_created_and_closed` must return REAL ints for the same reason as every entry
    # above (the closed-vs-new ratio gate, 2026-09-01). The gate computes `created / closed`
    # and compares it to 1.0; a bare MagicMock raises
    # `'<' not supported between instances of 'MagicMock' and 'float'` and 500s the route —
    # which is exactly what 22 tests in this file did the moment the gate landed.
    #
    # ZERO / ZERO is the honest default, not a convenient one: an idle window is ALLOWED by
    # ruling, so the gate stays silent and these tests keep testing what they are named for.
    # A test that wants a refusal sets this explicitly, the same contract as the empty maps
    # above.
    fake.count_created_and_closed.return_value = {
        "created"      : 0,
        "closed"       : 0,
        "window_start" : None,
        "window_end"   : None,
        "project"      : None,
    }

    @contextmanager
    def _fake_get_db():
        yield MagicMock()

    monkeypatch.setattr( tasks, "get_db", _fake_get_db )
    monkeypatch.setattr( tasks, "TaskRepository", lambda session: fake )
    return fake


@pytest.fixture
def client( repo ):
    app = FastAPI()
    app.include_router( tasks.router )
    # Override the credential (X-API-Key / JWT) so we test routing, not auth-DB.
    app.dependency_overrides[ require_api_key_or_jwt ] = lambda: "test-user"
    return TestClient( app )


@pytest.fixture( autouse=True )
def _seed_known_personas( monkeypatch ):
    # Hermetic roster for the unknown-persona soft-flag (policy 1, task c03d1870):
    # seed the lazy singleton so build_persona_advisory never reads live config.
    # Every persona the on-roster tests reference is included; off-roster tests
    # use a name NOT in this set ("ziggy stardust" / "ziggy").
    monkeypatch.setattr(
        tasks.rules, "_KNOWN_PERSONA_KEYS",
        { "krishna", "tiberius", "mr radio", "maria", "rachel", "sam" },
    )


_CREATE_BODY = {
    "item_class" : "task",
    "title"      : "build the store",
    "project"    : "lupin",
    "created_by" : "krishna 38d15e3b",
}


# ---------------------------------------------------------------------------
# POST /api/tasks
# ---------------------------------------------------------------------------

def test_create_returns_201_with_serialized_item( client, repo ):
    item = make_item()
    repo.create_item.return_value = item

    r = client.post( "/api/tasks", json=_CREATE_BODY )

    assert r.status_code == 201
    body = r.json()
    assert body[ "id" ] == str( item.id )
    assert body[ "status" ] == "queued" and body[ "item_class" ] == "task"
    assert body[ "created_ts" ] == NOW.isoformat() and body[ "next_chase_ts" ] is None
    repo.create_item.assert_called_once()


def test_create_defaults_flow_to_repository( client, repo ):
    repo.create_item.return_value = make_item()
    client.post( "/api/tasks", json=_CREATE_BODY )
    kwargs = repo.create_item.call_args.kwargs
    assert kwargs[ "authority" ] == "standing" and kwargs[ "gate_class" ] == "none"
    assert kwargs[ "priority" ] == "P2"
    # Class-scoped owner default (policy 2, task c03d1870): an owned-work class
    # (task) created WITHOUT an owner defaults to the creator's persona parsed
    # from created_by ("krishna 38d15e3b" -> "krishna") — was None pre-policy.
    assert kwargs[ "owner_persona" ] == "krishna"


def test_create_under_cap_title_guard_is_none( client, repo ):
    # Soft title guard (design 2026.06.29 §4.3): an under-cap title flows through
    # untouched and the response carries title_guard = None (the no-op advisory).
    repo.create_item.return_value = make_item()
    r = client.post( "/api/tasks", json=_CREATE_BODY )           # "build the store" — under cap
    assert r.status_code == 201
    assert r.json()[ "title_guard" ] is None
    assert repo.create_item.call_args.kwargs[ "title" ] == "build the store"


def test_create_over_cap_title_trimmed_overflow_to_empty_body( client, repo ):
    # Over-cap title + no body: the SERVER trims the stored title to the cap and
    # moves the overflow into body (non-destructive) BEFORE the repo write.
    # Derived from the cap, never a literal — a hardcoded 90 stopped being over-cap
    # the moment the cap moved 60 -> 120, and would have gone on passing at 201.
    long_title = "T" * ( tasks.rules.TITLE_SOFT_CAP + 30 )
    repo.create_item.return_value = make_item()
    r = client.post( "/api/tasks", json=dict( _CREATE_BODY, title=long_title ) )
    assert r.status_code == 201
    guard = r.json()[ "title_guard" ]
    assert guard[ "trimmed" ] is True and guard[ "overflow_moved_to_body" ] is True
    assert guard[ "original_length" ] == tasks.rules.TITLE_SOFT_CAP + 30
    kwargs = repo.create_item.call_args.kwargs
    assert kwargs[ "title" ] == "T" * tasks.rules.TITLE_SOFT_CAP and kwargs[ "body" ] == "T" * 30   # overflow → body


def test_create_over_cap_title_with_body_RELOCATES_overflow( client, repo ):
    # bug 28fc1fb4 — this asserted `overflow_moved_to_body is False` and passed,
    # which is how a silent data-loss path kept a green test beside it. The
    # overflow now survives ABOVE the pre-existing body, which is preserved whole.
    repo.create_item.return_value = make_item()
    over_cap = "W" * ( tasks.rules.TITLE_SOFT_CAP + 20 )
    r = client.post( "/api/tasks", json=dict( _CREATE_BODY, title=over_cap, body="keep me" ) )
    assert r.status_code == 201
    guard = r.json()[ "title_guard" ]
    assert guard[ "overflow_moved_to_body" ] is True
    kwargs = repo.create_item.call_args.kwargs
    assert kwargs[ "title" ] == "W" * tasks.rules.TITLE_SOFT_CAP
    assert kwargs[ "body" ].startswith( "keep me" )              # body never clobbered, and still first
    assert "W" * 20 in kwargs[ "body" ]                          # ...and the overflow survived
    assert kwargs[ "title" ] + "W" * 20 == over_cap              # round-trips to the original


def test_create_rejects_bad_enums_with_all_violations( client, repo ):
    bad = dict( _CREATE_BODY, item_class="chore", gate_class="side-gate", priority="P9", authority="by-fiat" )
    r = client.post( "/api/tasks", json=bad )
    assert r.status_code == 422
    assert len( r.json()[ "detail" ][ "errors" ] ) == 4
    repo.create_item.assert_not_called()                       # rejected BEFORE any write


def test_create_rejects_empty_required_fields( client, repo ):
    r = client.post( "/api/tasks", json=dict( _CREATE_BODY, title="" ) )
    assert r.status_code == 422                                 # Pydantic min_length
    repo.create_item.assert_not_called()


# ---------------------------------------------------------------------------
# POST /api/tasks — one-call BLOCKED mint (Rick's ruling 2026-07-20, build 1b5483f4)
# ---------------------------------------------------------------------------

_BLOCKED_BODY = dict(
    _CREATE_BODY,
    status        = "blocked",
    blocked_by    = [ { "kind": "persona", "id": "tiberius" } ],
    next_chase_ts = "2026-06-12T09:00:00+00:00",
)


@pytest.mark.parametrize( "bad_status", [ "done", "dropped", "parked", "claimed", "in_progress", "review" ] )
def test_create_rejects_non_whitelisted_mint_status( client, repo, bad_status ):
    # AC1 status whitelist: only queued|blocked are mintable. Every other status
    # is a 422 (rules violation), rejected BEFORE any write. A true allow-list.
    r = client.post( "/api/tasks", json=dict( _CREATE_BODY, status=bad_status ) )
    assert r.status_code == 422
    assert any( "cannot be minted at create" in e for e in r.json()[ "detail" ][ "errors" ] )
    repo.create_item.assert_not_called()


def test_create_blocked_mint_by_manager_succeeds( client, repo, monkeypatch ):
    # AC2 ALLOW path: a MANAGER (is_manager_figure True) mints an already-blocked
    # row in one call. status + blocked_by + next_chase_ts flow to the repository.
    monkeypatch.setattr( tasks, "is_manager_figure", lambda sid: True )
    repo.create_item.return_value = make_item(
        status        = "blocked",
        blocked_by    = [ { "kind": "persona", "id": "tiberius" } ],
        next_chase_ts = NOW,
    )
    r = client.post( "/api/tasks", json=_BLOCKED_BODY )
    assert r.status_code == 201
    assert r.json()[ "status" ] == "blocked"
    kwargs = repo.create_item.call_args.kwargs
    assert kwargs[ "status" ] == "blocked"
    assert kwargs[ "blocked_by" ] == [ { "kind": "persona", "id": "tiberius" } ]
    assert kwargs[ "next_chase_ts" ] is not None


def test_create_blocked_mint_by_non_manager_rejected_403( client, repo, monkeypatch ):
    # AC2 REJECT path: a genuinely-DENIED caller (resolved, not a manager) is 403'd
    # with the permission message — no write. bug dd3b3666: pin the message that a
    # RESOLVED non-manager gets, distinct from the stale-bridge message below.
    monkeypatch.setattr( tasks, "is_manager_figure", lambda sid: False )
    monkeypatch.setattr( tasks, "classify_manager_figure_denial", lambda sid: "denied" )
    r = client.post( "/api/tasks", json=_BLOCKED_BODY )
    assert r.status_code == 403
    assert "only a manager may mint" in r.json()[ "detail" ]
    assert "manager_figure_implicit' is false" in r.json()[ "detail" ]
    repo.create_item.assert_not_called()


def test_create_blocked_mint_stale_bridge_rejected_403_with_restart_hint( client, repo, monkeypatch ):
    # bug dd3b3666: a caller whose bridge is missing the manager_figure_implicit
    # stamp (schema-vintage, not a permission fact) is 403'd, but the message names
    # the ABSENT field and prescribes a session RESTART — NOT "you are not a manager".
    monkeypatch.setattr( tasks, "is_manager_figure", lambda sid: False )
    monkeypatch.setattr( tasks, "classify_manager_figure_denial",
                         lambda sid: tasks.DENIAL_STALE_BRIDGE )
    r = client.post( "/api/tasks", json=_BLOCKED_BODY )
    assert r.status_code == 403
    detail = r.json()[ "detail" ]
    assert "manager_figure_implicit" in detail and "RESTART" in detail
    assert "not a manager figure" not in detail          # must NOT misdiagnose as denial
    repo.create_item.assert_not_called()


def test_create_blocked_mint_unparseable_sid_rejected_403( client, repo, monkeypatch ):
    # Fail-CLOSED: a created_by with no session-id tail yields no sid → REJECTED
    # WITHOUT even consulting the predicate (short-circuit on session_id is None).
    def _boom( sid ):                                          # must NOT be reached
        raise AssertionError( "is_manager_figure consulted despite unparseable sid" )
    monkeypatch.setattr( tasks, "is_manager_figure", _boom )
    r = client.post( "/api/tasks", json=dict( _BLOCKED_BODY, created_by="nobody" ) )
    assert r.status_code == 403
    repo.create_item.assert_not_called()


def test_create_blocked_mint_persona_ref_without_chase_is_422( client, repo, monkeypatch ):
    # The blocked-invariant (I3) is enforced at CREATE via the SHARED validator: a
    # {kind:persona} blocker with no next_chase_ts is a 422 — the SAME rule a
    # transition applies, reused not forked. Whitelist/invariant (422) is checked
    # BEFORE the manager guard (403), so a manager still gets the 422 here.
    monkeypatch.setattr( tasks, "is_manager_figure", lambda sid: True )
    r = client.post( "/api/tasks", json=dict( _BLOCKED_BODY, next_chase_ts=None ) )
    assert r.status_code == 422
    assert any( "persona blocker requires a chase time" in e for e in r.json()[ "detail" ][ "errors" ] )
    repo.create_item.assert_not_called()


def test_create_queued_default_never_consults_manager_guard( client, repo, monkeypatch ):
    # G2 REGRESSION TRAP (Tiffany, sharpest): the manager check + the
    # created_by→session_id parse must fire ONLY for a blocked mint. A queued
    # create — even one whose created_by has NO parseable session id — must NOT
    # touch the guard, or existing queued HTTP callers regress. Prove it by making
    # is_manager_figure EXPLODE if consulted.
    def _boom( sid ):
        raise AssertionError( "manager guard consulted on the queued default path" )
    monkeypatch.setattr( tasks, "is_manager_figure", _boom )
    repo.create_item.return_value = make_item()
    r = client.post( "/api/tasks", json=dict( _CREATE_BODY, created_by="no-sid-here" ) )
    assert r.status_code == 201                                # queued path untouched
    assert repo.create_item.call_args.kwargs[ "status" ] == "queued"


# ---------------------------------------------------------------------------
# POST /api/tasks/{id}/transition
# ---------------------------------------------------------------------------

def _transition_body( **overrides ):
    body = { "to_status": "claimed", "actor": "krishna 38d15e3b" }
    body.update( overrides )
    return body


def test_transition_404_when_item_missing( client, repo ):
    repo.get_by_id_for_update.return_value = None
    r = client.post( f"/api/tasks/{uuid.uuid4()}/transition", json=_transition_body() )
    assert r.status_code == 404 and "not found" in r.json()[ "detail" ]
    repo.apply_transition.assert_not_called()


def test_transition_422_on_malformed_uuid( client, repo ):
    r = client.post( "/api/tasks/not-a-uuid/transition", json=_transition_body() )
    assert r.status_code == 422
    repo.get_by_id_for_update.assert_not_called()


def test_transition_rejects_a_reason_ending_in_a_captured_envelope_tag( client, repo ):
    # Row 91ccbc26 — the guard rides EVERY transition, not just ->parked, because
    # `reason` was measured to carry caller markup exactly as park_reason does.
    repo.get_by_id_for_update.return_value = make_item( status="queued" )
    r = client.post( f"/api/tasks/{uuid.uuid4()}/transition",
                     json=_transition_body( reason="picking this up" + ( "<" + "/" + "invoke>" ) ) )
    assert r.status_code == 422
    assert any( "reason ends with" in e for e in r.json()[ "detail" ][ "errors" ] )
    repo.apply_transition.assert_not_called()


def test_transition_ACCEPTS_a_reason_quoting_the_tag_mid_sentence( client, repo ):
    # 🔴 THE CONTROL at the endpoint: an honest reason that quotes the offending
    # markup and keeps speaking must still transition.
    item = make_item( status="queued" )
    repo.get_by_id_for_update.return_value = item
    repo.apply_transition.return_value = make_event( item.id )
    r = client.post( f"/api/tasks/{item.id}/transition",
                     json=_transition_body( reason="the tail was " + ( "<" + "/" + "invoke>" ) + " and I removed it" ) )
    assert r.status_code == 200
    repo.apply_transition.assert_called_once()


def test_transition_rejects_done_without_receipts( client, repo ):
    repo.get_by_id_for_update.return_value = make_item( status="review" )
    r = client.post( f"/api/tasks/{uuid.uuid4()}/transition", json=_transition_body( to_status="done" ) )
    assert r.status_code == 422
    assert any( "receipt_refs" in e for e in r.json()[ "detail" ][ "errors" ] )
    repo.apply_transition.assert_not_called()


def test_transition_rejects_leaving_terminal_state( client, repo ):
    repo.get_by_id_for_update.return_value = make_item( status="done" )
    r = client.post( f"/api/tasks/{uuid.uuid4()}/transition", json=_transition_body() )
    assert r.status_code == 422
    assert any( "append-only" in e for e in r.json()[ "detail" ][ "errors" ] )


def test_transition_happy_path_returns_item_and_event( client, repo ):
    item  = make_item( status="queued", updated_ts=NOW )       # current status — body moves it to claimed
    event = make_event( item.id, transition="queued->claimed" )
    repo.get_by_id_for_update.return_value         = item
    repo.apply_transition.return_value  = event

    r = client.post( f"/api/tasks/{item.id}/transition", json=_transition_body() )

    assert r.status_code == 200
    body = r.json()
    assert body[ "item" ][ "id" ] == str( item.id )
    assert body[ "event" ][ "transition" ] == "queued->claimed"
    assert body[ "event" ][ "ts" ] == NOW.isoformat() and body[ "event" ][ "authority" ] == "standing"
    kwargs = repo.apply_transition.call_args.kwargs
    assert kwargs[ "to_status" ] == "claimed" and kwargs[ "actor" ] == "krishna 38d15e3b"


def test_transition_to_done_with_valid_receipts_passes_them_through( client, repo ):
    # A test_run, not a commit. This test is about PASS-THROUGH plumbing — that
    # whatever receipts arrive reach the repository and come back on the event.
    # The done-gate (row 9bfb4b73) now checks a commit for branch REACHABILITY
    # via the scope registry, and the registry resolves ZERO scopes on a
    # developer host (its external paths are container paths). So a commit here
    # made the test's result depend on WHERE it ran, and it would 422 before the
    # plumbing under test was ever reached. A ts- run id is an equally valid
    # checkable receipt and needs no repo, which keeps this test hermetic and
    # about its own subject.
    receipts = { "test_run": "ts-5cc305c7" }
    item     = make_item( status="done" )
    repo.get_by_id_for_update.return_value        = make_item( status="review" )
    repo.apply_transition.return_value = make_event( item.id, transition="review->done", receipt_refs=receipts )

    r = client.post( f"/api/tasks/{item.id}/transition",
                     json=_transition_body( to_status="done", receipt_refs=receipts ) )

    assert r.status_code == 200
    assert r.json()[ "event" ][ "receipt_refs" ] == receipts
    assert repo.apply_transition.call_args.kwargs[ "receipt_refs" ] == receipts


def test_transition_to_blocked_serializes_chase_ts( client, repo ):
    chase = datetime( 2026, 6, 12, 9, 0, tzinfo=timezone.utc )
    refs  = [ { "kind": "user", "id": "rick" } ]
    item  = make_item( status="blocked", next_chase_ts=chase, blocked_by=refs )
    repo.get_by_id_for_update.return_value        = make_item( status="in_progress" )
    repo.apply_transition.return_value = make_event( item.id, transition="in_progress->blocked" )
    repo.get_by_id_for_update.return_value.next_chase_ts = None

    def _apply( **kwargs ):
        loaded               = repo.get_by_id_for_update.return_value
        loaded.status        = "blocked"
        loaded.next_chase_ts = kwargs[ "next_chase_ts" ]
        loaded.blocked_by    = kwargs[ "blocked_by" ]
        return make_event( loaded.id, transition="in_progress->blocked" )
    repo.apply_transition.side_effect = _apply

    r = client.post( f"/api/tasks/{item.id}/transition",
                     json=_transition_body( to_status="blocked",
                                            next_chase_ts=chase.isoformat(),
                                            blocked_by=refs ) )

    assert r.status_code == 200
    body = r.json()
    assert body[ "item" ][ "status" ] == "blocked"
    assert body[ "item" ][ "next_chase_ts" ] == chase.isoformat()   # the non-None serialize branch
    assert body[ "item" ][ "blocked_by" ] == refs


def test_transition_rejects_blocked_without_refs( client, repo ):
    # KIND-AWARE (eab1d7da / I3): a ->blocked with NO blocked_by is rejected for the
    # empty-refs violation ALONE — with no {kind:persona} ref present, no chase is
    # required, so the chase error does NOT co-fire. (Pre-migration this asserted 2
    # errors "chase + refs at once"; that pairing is now structurally unreachable —
    # a chase error needs a persona ref, and a persona ref makes the refs valid.)
    repo.get_by_id_for_update.return_value = make_item( status="in_progress" )
    r = client.post( f"/api/tasks/{uuid.uuid4()}/transition", json=_transition_body( to_status="blocked" ) )
    assert r.status_code == 422
    errors = r.json()[ "detail" ][ "errors" ]
    assert len( errors ) == 1 and "non-empty list of typed refs" in errors[ 0 ]


def test_transition_rejects_blocked_persona_ref_without_chase( client, repo ):
    # The reachable kind-aware rejection: a {kind:persona} blocker with no chase is
    # a 422 naming the chase requirement (the refs themselves are valid, so this is
    # the ONLY error). Same shared validate_blocked_fields the create-mint path uses.
    repo.get_by_id_for_update.return_value = make_item( status="in_progress" )
    r = client.post(
        f"/api/tasks/{uuid.uuid4()}/transition",
        json=_transition_body( to_status="blocked", blocked_by=[ { "kind": "persona", "id": "tiberius" } ] ),
    )
    assert r.status_code == 422
    errors = r.json()[ "detail" ][ "errors" ]
    assert len( errors ) == 1 and "persona blocker requires a chase time" in errors[ 0 ]


def test_transition_rejects_junk_receipts_on_non_done( client, repo ):
    """N2 at the wire: junk receipts on ->review never reach the audit trail."""
    repo.get_by_id_for_update.return_value = make_item( status="in_progress" )
    r = client.post( f"/api/tasks/{uuid.uuid4()}/transition",
                     json=_transition_body( to_status="review", receipt_refs={ "vibes": "good" } ) )
    assert r.status_code == 422
    assert any( "unknown receipt key 'vibes'" in e for e in r.json()[ "detail" ][ "errors" ] )
    repo.apply_transition.assert_not_called()


def test_transition_reads_through_row_lock_seam( client, repo ):
    """N3 code-path: the transition load uses get_by_id_for_update, never the
    plain unlocked get_by_id."""
    repo.get_by_id_for_update.return_value = make_item( status="queued" )
    repo.apply_transition.return_value     = make_event( uuid.uuid4(), transition="queued->claimed" )
    r = client.post( f"/api/tasks/{uuid.uuid4()}/transition", json=_transition_body() )
    assert r.status_code == 200
    repo.get_by_id_for_update.assert_called_once()
    repo.get_by_id.assert_not_called()


def test_transition_rejects_overlong_actor( client, repo ):
    """N5: actor backs VARCHAR(255) on the event — overlong is a 422, not a DB 500."""
    r = client.post( f"/api/tasks/{uuid.uuid4()}/transition",
                     json=_transition_body( actor="k" * 256 ) )
    assert r.status_code == 422
    repo.get_by_id_for_update.assert_not_called()


# ---------------------------------------------------------------------------
# GET /api/tasks
# ---------------------------------------------------------------------------

def test_query_returns_tasks_and_count( client, repo ):
    repo.query_tasks.return_value = [ make_item(), make_item( status="claimed" ) ]
    r = client.get( "/api/tasks" )
    assert r.status_code == 200
    body = r.json()
    assert body[ "count" ] == 2 and len( body[ "tasks" ] ) == 2


def test_query_count_only_returns_count_without_rows( client, repo ):
    # O2 / §G: count_only=true returns { count } (NO "tasks" key), via count_tasks
    # (the true COUNT(*)), and NEVER materializes rows through query_tasks.
    repo.count_tasks.return_value            = 273
    repo.count_tasks_by_status.return_value  = { "queued": 273 }
    r = client.get( "/api/tasks", params={ "count_only": "true" } )
    assert r.status_code == 200
    assert r.json() == { "count": 273, "breakdown": { "queued": 273 }, "priority_breakdown": { } }   # >100, no page saturation
    repo.count_tasks.assert_called_once()
    repo.query_tasks.assert_not_called()


def test_query_count_only_forwards_filters_not_pagination( client, repo ):
    repo.count_tasks.return_value           = 0
    repo.count_tasks_by_status.return_value = { }
    r = client.get( "/api/tasks", params={
        "owner_persona" : "krishna",
        "status"        : "queued",
        "project"       : "lupin",
        "count_only"    : "true",
        "limit"         : 7,                                  # ignored in count mode
        "offset"        : 3,                                  # ignored in count mode
    } )
    assert r.status_code == 200 and r.json() == { "count": 0, "breakdown": { }, "priority_breakdown": { } }
    kwargs = repo.count_tasks.call_args.kwargs
    assert kwargs[ "owner_persona" ] == "krishna" and kwargs[ "status" ] == "queued"
    assert kwargs[ "project" ] == "lupin"
    # a count is page-independent — limit/offset are NOT forwarded to count_tasks
    assert "limit" not in kwargs and "offset" not in kwargs


def test_query_count_only_still_validates_enums( client, repo ):
    # The enum gate fires BEFORE the count/list branch — a junk filter is still 422.
    r = client.get( "/api/tasks", params={ "status": "finished", "count_only": "true" } )
    assert r.status_code == 422
    repo.count_tasks.assert_not_called()
    repo.query_tasks.assert_not_called()


def _classification_help( actual_keys ):
    """
    The failure message for the key-set guard — and it is load-bearing, not decoration
    (Chloé 🗼's finding on 2d9c779a, row 9dbffefb).

    A bare set-difference tells a reader THAT a key is unclassified and leaves them to
    guess WHICH set to add it to. The two guesses are not equally safe: DATA is the
    silent one. Declare a derived field as DATA and no recipe is ever demanded, so the
    field ships wired to whatever it likes — which is the exact residual this guard
    admits it cannot close, and a bare message walks the reader straight into it.

    So the message names the choice, names the consequence of each branch, and says
    which way the failure is silent.
    """
    declared = tasks.TERSE_DATA_FIELDS | tasks.TERSE_ADVISORY_FIELDS
    unclassified = sorted( actual_keys - declared )
    departed     = sorted( declared - actual_keys )

    lines = [ "the terse projection and its declarations disagree." ]
    if unclassified:
        lines += [
            "",
            f"UNCLASSIFIED KEY(S) IN THE PROJECTION: {unclassified}",
            "Add each to exactly ONE set in cosa/rest/routers/tasks.py, and the choice matters:",
            "",
            "  TERSE_DATA_FIELDS      — the value is CARRIED off the row (item.<attr>).",
            "                           Nothing further is required.",
            "  TERSE_ADVISORY_FIELDS  — the value is DERIVED by a predicate at serialize",
            "                           time. You must also register a True/False recipe in",
            "                           _ADVISORY_RECIPES, or test_every_advisory_field_has_a_recipe",
            "                           fails immediately and tells you so.",
            "",
            "⚠️ IF YOU ARE UNSURE, IT IS ADVISORY. The two mistakes are not symmetric:",
            "   calling a carried field advisory costs you one recipe you did not need;",
            "   calling a DERIVED field data demands nothing, so it ships unguarded and",
            "   a constant in its place stays green forever. That is the failure this",
            "   whole guard exists to prevent, and DATA is the box it hides in.",
        ]
    if departed:
        lines += [
            "",
            f"DECLARED BUT ABSENT FROM THE PROJECTION: {departed}",
            "Either the key was removed — delete its declaration (and its recipe, if advisory)",
            "— or the serializer stopped emitting it, which is the regression this catches.",
        ]
    return "\n".join( lines )


def test_query_terse_returns_glance_projection_only( client, repo ):
    # §G: terse=true serializes the at-a-glance projection — EXACTLY the seven
    # glance keys, with `body` (and every other full-row field) dropped.
    # park_reason_stale joined the projection 2026-07-19 (staleness §3.3): the
    # terse shape is what a board glance actually reads, so a staleness flag
    # carried ONLY by the full row would be a flag nobody sees. This assertion
    # is an exact-set match on purpose — it is the guard that catches a field
    # silently joining or leaving the token-sensitive projection.
    repo.query_tasks.return_value = [
        make_item( body="a multi-paragraph body that must NOT ride the wire", priority="P1" ),
    ]
    r = client.get( "/api/tasks", params={ "terse": "true" } )
    assert r.status_code == 200
    body = r.json()
    assert body[ "count" ] == 1
    row = body[ "tasks" ][ 0 ]
    # BUILT FROM THE ROUTER'S OWN DECLARATIONS, not a flat literal (row 9dbffefb,
    # 2026-08-31). Every key the projection carries is classified in one of the two
    # sets — DATA is carried off the row, ADVISORY is derived by a predicate — so a
    # new key cannot join without a human choosing which it is, and choosing ADVISORY
    # immediately demands a two-value recipe in TestTerseAdvisoryFieldsAreWired below.
    #
    # The individual joining arguments are preserved on the declarations themselves in
    # tasks.py; the history for each is: park_reason_stale (staleness §3.3, 2026-07-19),
    # blocker_terminal (row 00a6bde2, 2026-07-25 — a stranded blocked row is invisible in
    # exactly the way a finished one is), project (row d23147e8, 2026-07-25, a COST
    # argument: the orphan-alias census costs 1,227 full rows without it), and
    # title_trimmed (row a6cb24e8, 2026-08-31 — the trim files the tail into `body`,
    # which THIS projection drops, and leaves no mark behind).
    assert set( row.keys() ) == tasks.TERSE_DATA_FIELDS | tasks.TERSE_ADVISORY_FIELDS, \
        _classification_help( set( row.keys() ) )
    assert not ( tasks.TERSE_DATA_FIELDS & tasks.TERSE_ADVISORY_FIELDS ), \
        "a key is in BOTH TERSE_DATA_FIELDS and TERSE_ADVISORY_FIELDS: " \
        f"{sorted( tasks.TERSE_DATA_FIELDS & tasks.TERSE_ADVISORY_FIELDS )}. " \
        "A key is carried OR derived, never both — pick one."
    assert "body" not in row                                  # the token win — body dropped
    # `is False`, not a truthiness check, and a type assertion beside it: the SQL
    # twin of this predicate returns NULL (not False) on its null arms when run as
    # a PROJECTION rather than a filter, and `None` is falsy — so `assert not
    # row[...]` would pass straight over a nullable bool reaching the wire. §3.3
    # promises a bool; this is what holds the projection to it. (Null-arm defect
    # found by seat 1 in the SQL twin, 2026-07-19; the serializer uses the Python
    # predicate and is unaffected — this assertion is what keeps that true.)
    assert type( row[ "park_reason_stale" ] ) is bool         # TYPE FIRST — never None, on any arm
    assert row[ "park_reason_stale" ] is False                # a never-parked row is never stale
    assert type( row[ "blocker_terminal" ] ) is bool          # same TYPE-FIRST guard, same reason
    assert row[ "blocker_terminal" ] is False                 # an unblocked row is never stranded
    assert row[ "priority" ] == "P1" and row[ "status" ] == "queued"
    repo.query_tasks.assert_called_once()                    # rows ARE materialized (not count mode)


def test_terse_title_trimmed_reads_the_COLUMN_not_the_title_length( client, repo ):
    # DESCENDED FROM TIBERIUS 👑's test of the same name at c64da293, which drove the
    # flag through the title's LENGTH because the flag WAS the length. Bug 769b3574
    # moved it onto the row, so this fixture now has to separate two things his could
    # not: reading the stored column, and re-deriving it from the title.
    #
    # THE FIXTURE IS DELIBERATELY CROSSED, and that is the whole test. Row 0 has a
    # SHORT title and the flag True; row 1 has a title at exactly the cap and the flag
    # False. So:
    #     a constant False              -> dies on row 0
    #     a constant True               -> dies on row 1
    #     `len( title ) == cap` restored -> dies on BOTH, in opposite directions
    #
    # A fixture whose title length AGREES with its flag cannot tell the third case
    # from a correct read — the values would be interchangeable, and a test over
    # interchangeable values asserts their agreement rather than their identity. That
    # is the blind-fixture shape this file has now been bitten by twice.
    #
    # Row 1's title comes from soft_guard_title's OWN no-op arm, so "exactly at the
    # cap and NOT trimmed" is the guard's verdict rather than my arithmetic.
    at_cap_but_untrimmed = "N" * rules.TITLE_SOFT_CAP
    assert rules.soft_guard_title( at_cap_but_untrimmed, None )[ 2 ] is None   # the guard did not cut it

    repo.query_tasks.return_value = [
        make_item( title="short", title_trimmed=True ),
        make_item( title=at_cap_but_untrimmed, title_trimmed=False ),
    ]
    r = client.get( "/api/tasks", params={ "terse": "true" } )
    assert r.status_code == 200
    rows = r.json()[ "tasks" ]
    assert rows[ 0 ][ "title_trimmed" ] is True      # short title, flag set   -> not derived from length
    assert rows[ 1 ][ "title_trimmed" ] is False     # cap-length, flag clear  -> not derived from length


def test_terse_does_not_flag_an_over_cap_LEGACY_row( client, repo ):
    """
    Rachel 🕊️'s S1 projection fixture, carried onto the stored-flag branch so her
    concern survives the deletion of the predicate it was written against.

    🔴 WHAT THIS TEST DOES **NOT** PROVE, corrected after Mr Radio 🦉 caught me claiming
    it did. I wrote that against a stored column this says "the flag is not derived from
    the title's length AT ALL". IT DOES NOT. Measured: restore the length derivation in
    the serializer (sha 1e6f1ce41a5a) and THIS TEST STILL PASSES — 90 != 60, so a length
    check and a column read give the same answer on this input. A test that cannot tell
    the two apart cannot be evidence about which one is running.

    ⇒ The independence claim belongs to
    `test_terse_title_trimmed_reads_the_COLUMN_not_the_title_length`, whose fixture is
    CROSSED — a short title flagged True, a cap-length title flagged False — and which
    goes RED on that same mutant. On the length question this test is strictly subsumed
    by that one.

    WHAT IT DOES PROVE, which is Rachel's actual finding and worth keeping: a legacy
    over-cap row is not flagged. `make_item` bypasses the write path exactly as one of
    the 333 rows already in the store does, so this pins the answer for a real input
    class that the write path can no longer produce.
    """
    # OVER THE CURRENT CAP, derived — a literal 90 was over-cap at 60 and stopped
    # being over-cap when Rick raised it to 120 (bug 6ce252e7). The fixture would
    # have gone on passing while no longer posing the question it was written for:
    # a length-derived answer only reports True on a title that is actually long.
    repo.query_tasks.return_value = [ make_item( title="X" * ( tasks.rules.TITLE_SOFT_CAP + 30 ) ) ]
    r = client.get( "/api/tasks", params={ "terse": "true" } )
    assert r.status_code == 200
    assert r.json()[ "tasks" ][ 0 ][ "title_trimmed" ] is False


# ─────────────────────────────────────────────────────────────────────────────────
# THE ADVISORY-FIELD REGISTRY (row 9dbffefb, 2026-08-31)
#
# WHY IT EXISTS. `title_trimmed` reached the terse projection with its key asserted
# by the exact-set test above and its VALUE read by nothing: replacing its predicate
# call with a bare `False` left all 471 tests green (row f3230576). An advisory field
# wired to a constant is indistinguishable from a correct one that happens to be
# False, so a key-presence assertion cannot tell them apart — and the fix for that is
# a registry, not a resolution to be careful.
#
# HOW IT BINDS. `tasks.TERSE_ADVISORY_FIELDS` is the router's own declaration, and
# `test_every_advisory_field_has_a_recipe` asserts this registry covers it EXACTLY.
# So a field cannot be declared advisory without supplying a two-value recipe here,
# and the exact-set assertion above means a key cannot reach the projection without
# being declared as one thing or the other.
#
# WRITING A RECIPE — the two ways to get this wrong, both measured tonight:
#   · the FALSE arm must be false for the RIGHT reason. `title_trimmed` over-reports
#     by construction (length-only), so its false arm needs a title STRICTLY under
#     the cap — a 60-char stand-in would report True and the test would pass while
#     asserting the opposite of what it names. (Pocholo 📣 raised this; it is the
#     same shape as his 63-char fixture whose cut portion was "ign".)
#   · the two arms must differ ONLY in what drives the field. If they differ in
#     something else as well, the test can pass on the other difference.
_ADVISORY_RECIPES = { }


def _advisory_recipe( field ):
    """Register the True/False item pair for one advisory field."""
    def register( fn ):
        _ADVISORY_RECIPES[ field ] = fn
        return fn
    return register


@_advisory_recipe( "title_trimmed" )
def _recipe_title_trimmed():
    # ⚠️ REWRITTEN AT THE 769b3574 MERGE. This recipe used to set neither arm's flag and
    # let the TITLE decide — TRUE arm a guard-trimmed 60-char title, FALSE arm a short
    # one — because `title_trimmed` was RE-DERIVED from length on read. It is a STORED
    # column now, so a title alone decides nothing and the TRUE arm reported False.
    #
    # The arms are now the STRONGER pair the stored column makes available, and they
    # discriminate in a way the old ones could not: both titles sit at exactly the cap,
    # so LENGTH is held constant across the pair and only the column differs. Any
    # regression back to a length-derived answer reports True on BOTH and dies on the
    # FALSE arm. Under the old recipe that same regression passed.
    trimmed, _overflow, advisory = rules.soft_guard_title( "T" * ( rules.TITLE_SOFT_CAP + 30 ), None )
    assert advisory[ "trimmed" ] is True                    # the title still comes from
    assert len( trimmed ) == rules.TITLE_SOFT_CAP           # the guard, not a literal
    return (
        make_item( title=trimmed, title_trimmed=True  ),
        make_item( title=trimmed, title_trimmed=False ),
        { },
    )


@_advisory_recipe( "park_reason_stale" )
def _recipe_park_reason_stale():
    # The quote is FROZEN at park time; a LATER body change is what makes it stale.
    # Both arms are parked and differ only in which timestamp is the later one.
    later = NOW + timedelta( hours=1 )
    return (
        make_item( status="parked", park_reason_captured_at=NOW,   body_changed_ts=later ),
        make_item( status="parked", park_reason_captured_at=later, body_changed_ts=NOW   ),
        { },
    )


@_advisory_recipe( "blocker_terminal" )
def _recipe_blocker_terminal():
    # Both arms are blocked on a real item id and differ only in that blocker's
    # status, which is what the predicate reads.
    done_id, live_id = uuid.uuid4(), uuid.uuid4()
    return (
        _blocked_item( done_id ),
        _blocked_item( live_id ),
        { str( done_id ): "done", str( live_id ): "queued" },
    )


def test_every_advisory_field_has_a_recipe():
    """
    The binding that makes the registry mechanical instead of a habit. Declaring a
    field advisory in the router without registering its two arms here fails HERE,
    at the moment of the declaration, rather than silently shipping a flag nothing
    reads. The reverse is caught too: a recipe for a field that is no longer in the
    projection is dead weight that would keep passing.
    """
    missing = sorted( set( tasks.TERSE_ADVISORY_FIELDS ) - set( _ADVISORY_RECIPES ) )
    extra   = sorted( set( _ADVISORY_RECIPES ) - set( tasks.TERSE_ADVISORY_FIELDS ) )
    assert set( _ADVISORY_RECIPES ) == set( tasks.TERSE_ADVISORY_FIELDS ), (
        f"advisory fields with NO recipe: {missing}\n"
        f"recipes for fields no longer declared advisory: {extra}\n"
        "\n"
        "For each missing one, register a recipe with @_advisory_recipe( <field> )\n"
        "returning ( true_item, false_item, blocker_statuses ). The two items must differ\n"
        "ONLY in what drives the field, and the FALSE arm must be false for the RIGHT\n"
        "reason — see the recipe comments above for the over-report trap that makes a\n"
        "cap-length fixture report True while the test's name says otherwise."
    )


@pytest.mark.parametrize( "field", sorted( tasks.TERSE_ADVISORY_FIELDS ) )
def test_every_advisory_field_is_wired_on_the_terse_path( client, repo, field ):
    """
    Row 9dbffefb. Every DERIVED field in the terse projection must be shown to carry
    its predicate's answer, not a constant — both directions, through the endpoint.

    A constant False dies on the first assertion and a constant True on the second,
    so no constant survives for any registered field. This is the generalisation of
    the single-field test above it, which caught `title_trimmed` after a constant
    passed 471 tests green.
    """
    true_item, false_item, blocker_statuses = _ADVISORY_RECIPES[ field ]()

    repo.query_tasks.return_value      = [ true_item, false_item ]
    repo.statuses_for_ids.return_value = blocker_statuses

    r = client.get( "/api/tasks", params={ "terse": "true" } )
    assert r.status_code == 200
    rows = r.json()[ "tasks" ]

    assert type( rows[ 0 ][ field ] ) is bool                 # TYPE FIRST — never None
    assert type( rows[ 1 ][ field ] ) is bool
    assert rows[ 0 ][ field ] is True,  f"{field}: the TRUE arm did not report True"
    assert rows[ 1 ][ field ] is False, f"{field}: the FALSE arm did not report False"
def test_terse_does_not_flag_an_over_cap_LEGACY_row( client, repo ):
    """
    Rachel 🕊️'s S1, projection half. Her fixture, landed by me.

    `make_item` builds a TaskItem straight from kwargs — `soft_guard_title` appears
    nowhere in it — so an over-cap title reaches the projection here exactly as one of
    the 333 legacy rows in the store does. That is what makes the discriminating input
    two lines rather than impossible.

    She measured both arms in her own detached worktree at c64da293: pristine, this
    passes; with `==` changed to `>=` (sha 7b187f8b224d) it FAILS, alongside 472 passed.
    The mutant that survived the entire existing suite dies on the first fixture that
    hands the predicate an input the suite could not produce.
    """
    # OVER THE CURRENT CAP, derived — a literal 90 was over-cap at 60 and stopped
    # being over-cap when Rick raised it to 120 (bug 6ce252e7). The fixture would
    # have gone on passing while no longer posing the question it was written for:
    # a length-derived answer only reports True on a title that is actually long.
    repo.query_tasks.return_value = [ make_item( title="X" * ( tasks.rules.TITLE_SOFT_CAP + 30 ) ) ]
    r = client.get( "/api/tasks", params={ "terse": "true" } )
    assert r.status_code == 200
    assert r.json()[ "tasks" ][ 0 ][ "title_trimmed" ] is False


def test_query_terse_serializes_nullable_next_chase_ts( client, repo ):
    # The terse projection's only conditional: next_chase_ts → None when unset.
    repo.query_tasks.return_value = [ make_item( next_chase_ts=NOW ), make_item( next_chase_ts=None ) ]
    r = client.get( "/api/tasks", params={ "terse": "true" } )
    rows = r.json()[ "tasks" ]
    assert rows[ 0 ][ "next_chase_ts" ] == NOW.isoformat()
    assert rows[ 1 ][ "next_chase_ts" ] is None


def test_query_terse_false_returns_full_rows( client, repo ):
    # Default (terse omitted) → the full wire shape, body included (unchanged).
    repo.query_tasks.return_value = [ make_item( body="full body here" ) ]
    r = client.get( "/api/tasks" )
    row = r.json()[ "tasks" ][ 0 ]
    assert row[ "body" ] == "full body here" and "created_ts" in row


def test_query_count_only_precedes_terse( client, repo ):
    # count_only wins over terse — a count needs no rows at all, so query_tasks
    # is never called even when terse is also requested.
    repo.count_tasks.return_value           = 5
    repo.count_tasks_by_status.return_value = { "queued": 5 }
    r = client.get( "/api/tasks", params={ "count_only": "true", "terse": "true" } )
    assert r.status_code == 200 and r.json() == { "count": 5, "breakdown": { "queued": 5 }, "priority_breakdown": { } }
    repo.count_tasks.assert_called_once()
    repo.query_tasks.assert_not_called()


# ---------------------------------------------------------------------------
# breakdown on the count_only path (c191be39, 2026-07-20)
# ---------------------------------------------------------------------------

def test_count_only_returns_breakdown_beside_count( client, repo ):
    """THE SERVER HALF OF THE FIX: the status the seam used to destroy."""
    repo.count_tasks.return_value           = 16
    repo.count_tasks_by_status.return_value = { "in_progress": 2, "queued": 13, "parked": 1 }

    r = client.get( "/api/tasks", params={ "owed_only": "true", "count_only": "true" } )

    assert r.status_code == 200
    assert r.json() == { "count": 16, "breakdown": { "in_progress": 2, "queued": 13, "parked": 1 }, "priority_breakdown": { } }
    repo.query_tasks.assert_not_called()                      # still no row materialization


def test_count_only_count_equals_sum_of_breakdown( client, repo ):
    """
    AC1 at the endpoint. The two numbers come from two INDEPENDENT repository calls
    (COUNT(*) and a GROUP BY), neither derived from the other — which is precisely
    what lets this assertion fail. An invariant true by construction is not a gate.
    """
    repo.count_tasks.return_value           = 16
    repo.count_tasks_by_status.return_value = { "in_progress": 2, "queued": 13, "parked": 1 }

    body = client.get( "/api/tasks", params={ "owed_only": "true", "count_only": "true" } ).json()
    assert sum( body[ "breakdown" ].values() ) == body[ "count" ]


def test_breakdown_receives_the_same_filters_as_count( client, repo ):
    """
    The two aggregates MUST select the same population or the sum-parity gate is
    comparing different boards. Asserted at the endpoint, where a forwarding
    omission would live.
    """
    repo.count_tasks.return_value           = 0
    repo.count_tasks_by_status.return_value = { }
    client.get( "/api/tasks", params={
        "owner_persona" : "krishna",
        "status"        : "queued",
        "project"       : "lupin",
        "owed_only"     : "true",
        "count_only"    : "true",
    } )
    assert repo.count_tasks.call_args.kwargs == repo.count_tasks_by_status.call_args.kwargs


def test_breakdown_NEVER_reaches_the_full_row_response( client, repo ):
    """
    ⛔ THE BOUNDARY GUARD (plan §4.1a). /api/tasks is NOT internal-only — the
    multiplexer parses the FULL-ROW shape (render/taskListModel.ts,
    render/TaskListRenderer.ts, notifications.js:386, and a 60s poll at
    multiplexer/boot.ts:586). `breakdown` is scoped to the count_only branch; if it
    ever leaks into the list response it changes a shape with live frontend
    consumers.
    """
    repo.query_tasks.return_value = [ ]
    r = client.get( "/api/tasks", params={ "owner_persona": "krishna" } )   # count_only=False

    assert r.status_code == 200
    assert "breakdown" not in r.json(), "breakdown leaked into the full-row shape the multiplexer parses"
    # The exact-set match SURVIVES mini-plan 02 — it just grew by the four ADDED
    # keys. `tasks` and `count` are still here, still meaning exactly what they
    # meant, which is the half of this guard the multiplexer depends on; the
    # exactness is the half that catches the next unannounced key.
    assert set( r.json().keys() ) == { "tasks", "count", "total", "has_more", "truncated", "warnings" }
    repo.count_tasks_by_status.assert_not_called()             # not even computed off the count path


def test_breakdown_not_computed_when_enum_validation_rejects( client, repo ):
    """The enum gate fires BEFORE the count branch — a junk filter costs no queries."""
    r = client.get( "/api/tasks", params={ "status": "finished", "count_only": "true" } )
    assert r.status_code == 422
    repo.count_tasks.assert_not_called()
    repo.count_tasks_by_status.assert_not_called()


def test_query_passes_all_filters_through( client, repo ):
    repo.query_tasks.return_value = [ ]
    r = client.get( "/api/tasks", params={
        "owner_persona"       : "krishna",
        "status"              : "in_progress",
        "gate_class"          : "operator",
        "urgency"             : "urgent",
        "accountable_manager" : "tiberius",
        "project"             : "lupin",
        "item_class"          : "task",
        "correlation_key"     : "cc-task:sid:5",
        "limit"               : 7,
        "offset"              : 3,
    } )
    assert r.status_code == 200 and r.json() == {
        "tasks": [ ], "count": 0, "total": 0, "has_more": False, "truncated": False, "warnings": [ ],
    }
    kwargs = repo.query_tasks.call_args.kwargs
    assert kwargs[ "owner_persona" ] == "krishna" and kwargs[ "gate_class" ] == "operator"
    assert kwargs[ "urgency" ] == "urgent"
    assert kwargs[ "correlation_key" ] == "cc-task:sid:5"
    assert kwargs[ "limit" ] == 7 and kwargs[ "offset" ] == 3


@pytest.mark.parametrize( "params, fragment", [
    ( { "status": "finished" }, "status filter" ),
    ( { "gate_class": "side-gate" }, "gate_class filter" ),
    ( { "urgency": "panic" }, "urgency filter" ),
    ( { "item_class": "chore" }, "item_class filter" ),
] )
def test_query_rejects_junk_enum_filters( client, repo, params, fragment ):
    """A typo'd filter is a caller bug surfaced as 422 — never an honest-looking empty result."""
    r = client.get( "/api/tasks", params=params )
    assert r.status_code == 422
    assert any( fragment in e for e in r.json()[ "detail" ][ "errors" ] )
    repo.query_tasks.assert_not_called()


def test_query_reports_multiple_junk_filters_at_once( client, repo ):
    r = client.get( "/api/tasks", params={ "status": "finished", "gate_class": "side-gate", "item_class": "chore" } )
    assert r.status_code == 422 and len( r.json()[ "detail" ][ "errors" ] ) == 3


# ---------------------------------------------------------------------------
# GET /api/tasks — unscoped-query guard (design 2026.07.07)
# ---------------------------------------------------------------------------

def test_query_maps_unscoped_query_error_to_educational_400( client, repo ):
    # The repository raises UnscopedQueryError on a bare over-threshold pull; the
    # router maps it to HTTP 400 whose detail NAMES the two fixes (teach-while-enforce).
    repo.query_tasks.side_effect = tasks.rules.UnscopedQueryError( 273, 50 )
    r = client.get( "/api/tasks" )
    assert r.status_code == 400
    detail = r.json()[ "detail" ]
    assert "273" in detail and "unscoped_audit=true" in detail
    assert "owner_persona" in detail                          # names a narrowing filter too


def test_query_forwards_include_terminal_and_unscoped_audit_to_repo( client, repo ):
    # Both new params reach the repository query (the UI board cards + arbiter escape).
    repo.query_tasks.return_value = [ ]
    r = client.get( "/api/tasks", params={ "unscoped_audit": "true", "include_terminal": "true" } )
    assert r.status_code == 200
    kwargs = repo.query_tasks.call_args.kwargs
    assert kwargs[ "unscoped_audit" ] is True and kwargs[ "include_terminal" ] is True


def test_query_defaults_include_terminal_and_unscoped_audit_false( client, repo ):
    # Omitted → both default False (the guarded, terminal-excluding common path).
    repo.query_tasks.return_value = [ ]
    client.get( "/api/tasks", params={ "owner_persona": "krishna" } )
    kwargs = repo.query_tasks.call_args.kwargs
    assert kwargs[ "unscoped_audit" ] is False and kwargs[ "include_terminal" ] is False


def test_query_count_only_forwards_include_terminal_to_count( client, repo ):
    # count_only path plumbs include_terminal to count_tasks (parity with the list path).
    repo.count_tasks.return_value = 0
    client.get( "/api/tasks", params={ "count_only": "true", "include_terminal": "true" } )
    assert repo.count_tasks.call_args.kwargs[ "include_terminal" ] is True


def test_query_warns_on_heavy_nonterse_pull( client, repo, capsys ):
    # María #3 warn-not-fail: a non-terse pull over the WARN threshold logs an
    # OBSERVABLE line AND still returns every row (never a rejection).
    over = tasks.rules.NONTERSE_WARN_THRESHOLD + 1
    repo.query_tasks.return_value = [ make_item() for _ in range( over ) ]
    r = client.get( "/api/tasks" )
    assert r.status_code == 200 and r.json()[ "count" ] == over  # rows NOT truncated
    assert "[task_query WARN]" in capsys.readouterr().out


def test_query_no_warn_on_terse_pull( client, repo, capsys ):
    # A terse pull of the same size does NOT warn — terse is the desired shape.
    over = tasks.rules.NONTERSE_WARN_THRESHOLD + 1
    repo.query_tasks.return_value = [ make_item() for _ in range( over ) ]
    client.get( "/api/tasks", params={ "terse": "true" } )
    assert "[task_query WARN]" not in capsys.readouterr().out


def test_query_no_warn_on_small_nonterse_pull( client, repo, capsys ):
    # A small non-terse pull (<= threshold) is silent — the WARN targets heavy pulls only.
    repo.query_tasks.return_value = [ make_item(), make_item() ]
    client.get( "/api/tasks" )
    assert "[task_query WARN]" not in capsys.readouterr().out


# ---------------------------------------------------------------------------
# GET /api/tasks — TRUTHFUL ENVELOPE (mini-plan 02, 2026-07-21)
#
# The defect: `count` is the length of THIS PAGE, published under a name every
# caller reads as the SIZE OF THE RESULT. Measured live on 2026-07-21 — a scoped
# query (owner_persona="mr radio" + include_terminal) reported count:100 while
# offset=100 returned 100 more rows, with no total / has_more / truncated to say
# so. A caller who read it and stopped had been told a false fact about the world.
# ---------------------------------------------------------------------------

def test_ARM_H_scoped_query_that_misreported_now_admits_more_rows_exist( client, repo ):
    """
    AC-1 — THE REGRESSION TEST FOR THE WHOLE ROW.

    This is the EXACT query that misreported on 2026-07-21: owner_persona="mr radio"
    + include_terminal, full rows, saturating the 100-row default page against a
    store holding more. It used to answer `count: 100` and nothing else. It now has
    to admit that more rows exist.
    """
    repo.query_tasks.return_value  = [ make_item( owner_persona="mr radio" ) for _ in range( 100 ) ]
    repo.count_tasks.return_value  = 387                       # the store holds far more than one page

    r = client.get( "/api/tasks", params={ "owner_persona": "mr radio", "include_terminal": "true" } )

    assert r.status_code == 200
    body = r.json()
    assert body[ "has_more" ] is True                           # the fact the old envelope withheld
    assert body[ "total" ] == 387
    assert body[ "total" ] > body[ "count" ]                    # count was NEVER the size of the result
    assert body[ "count" ] == 100                               # ...and it still means EXACTLY what it did


def test_result_that_fits_one_page_reports_no_more( client, repo ):
    # AC-2. The honest negative arm: when the page IS the result, has_more is False
    # and total == count. Without this the fix could be a constant `true` and pass.
    repo.query_tasks.return_value = [ make_item(), make_item(), make_item() ]
    repo.count_tasks.return_value = 3

    body = client.get( "/api/tasks", params={ "owner_persona": "krishna" } ).json()

    assert body[ "has_more" ] is False
    assert body[ "total" ] == body[ "count" ] == 3
    assert body[ "truncated" ] is False


def test_has_more_accounts_for_offset( client, repo ):
    # has_more = offset + count < total, NOT count < total: page 2 of 3 pages must
    # still say "more", and the LAST page must not.
    repo.query_tasks.return_value = [ make_item() for _ in range( 10 ) ]
    repo.count_tasks.return_value = 25

    mid = client.get( "/api/tasks", params={ "owner_persona": "krishna", "offset": 10 } ).json()
    assert mid[ "has_more" ] is True                            # 10 + 10 < 25

    repo.query_tasks.return_value = [ make_item() for _ in range( 5 ) ]
    last = client.get( "/api/tasks", params={ "owner_persona": "krishna", "offset": 20 } ).json()
    assert last[ "has_more" ] is False                          # 20 + 5 == 25, nothing beyond


def test_total_is_a_true_count_NOT_derived_from_the_page( client, repo ):
    """
    The anti-tautology guard. `total` must come from a COUNT(*) over the same
    filters — page-independent, limit/offset deliberately NOT forwarded. A `total`
    derived from len(tasks) would make has_more permanently False and every
    assertion above an unfalsifiable green.
    """
    repo.query_tasks.return_value = [ make_item() for _ in range( 4 ) ]
    repo.count_tasks.return_value = 91                          # deliberately unrelated to the page

    body = client.get( "/api/tasks", params={ "owner_persona": "krishna", "limit": 4, "offset": 8 } ).json()

    assert body[ "total" ] == 91 and body[ "count" ] == 4       # the two numbers are INDEPENDENT
    kwargs = repo.count_tasks.call_args.kwargs
    assert "limit" not in kwargs and "offset" not in kwargs      # a total is page-independent
    assert kwargs[ "owner_persona" ] == "krishna"                # ...over the SAME filter set


def test_total_forwards_the_identical_filter_set_as_the_page_query( client, repo ):
    # `total` counts what the page selected FROM. A filter that reaches query_tasks
    # but not count_tasks would produce a total for a different question entirely.
    repo.query_tasks.return_value = [ ]
    client.get( "/api/tasks", params={
        "owner_persona"       : "krishna",
        "status"              : "queued",
        "gate_class"          : "operator",
        "urgency"             : "urgent",
        "accountable_manager" : "tiberius",
        "project"             : "lupin",
        "item_class"          : "task",
        "correlation_key"     : "cc-task:sid:5",
        "include_terminal"    : "true",
        "owed_only"           : "true",
        "hide_parked"         : "false",
    } )
    page  = repo.query_tasks.call_args.kwargs
    total = repo.count_tasks.call_args.kwargs
    shared = set( total.keys() )
    assert shared, "count_tasks was called with no filters at all"
    for key in shared:
        assert total[ key ] == page[ key ], f"filter '{key}' differs between the page and its total"


def test_heavy_pull_notice_reaches_the_CALLER_and_the_log_survives( client, repo, capsys ):
    """
    AC-4 (T2). The heavy-pull nudge used to go to the server's STDOUT — an audience
    that is not the party paying the token weight and cannot act on it. A warning
    delivered to someone who cannot act on it is not a warning. It now rides the
    response body TOO; the log line is kept, not moved.
    """
    over = tasks.rules.NONTERSE_WARN_THRESHOLD + 1
    repo.query_tasks.return_value = [ make_item() for _ in range( over ) ]

    body = client.get( "/api/tasks", params={ "owner_persona": "krishna" } ).json()

    assert any( "terse=true" in w for w in body[ "warnings" ] )   # the CALLER is told
    assert "[task_query WARN]" in capsys.readouterr().out          # the operator still is too
    assert body[ "count" ] == over                                # warn-not-fail: rows still returned


def test_no_warnings_on_a_small_terse_pull( client, repo ):
    # The quiet arm — `warnings` is an empty list, never absent, never chatty.
    repo.query_tasks.return_value = [ make_item(), make_item() ]
    body = client.get( "/api/tasks", params={ "terse": "true" } ).json()
    assert body[ "warnings" ] == [ ]


def test_byte_budget_truncates_LOUDLY_with_the_honest_total( client, repo, monkeypatch, capsys ):
    """
    AC-5 (T3). `limit` caps ROWS, and a row cap is not a size cap — the same 100-row
    page measured 21,379 chars terse and 424,209 full. The byte bound stops
    serialization early, and the stop is NEVER silent: `truncated` is true, the
    warning names the budget, and `total` still reports every matching row.
    """
    repo.query_tasks.return_value = [ make_item( body="x" * 400 ) for _ in range( 50 ) ]
    repo.count_tasks.return_value = 50
    monkeypatch.setattr( tasks.rules, "RESPONSE_CHAR_BUDGET", 3_000 )

    body = client.get( "/api/tasks", params={ "owner_persona": "krishna" } ).json()

    assert body[ "truncated" ] is True
    assert body[ "count" ] < 50                                  # rows WERE dropped
    assert body[ "total" ] == 50                                 # ...and the response says how many exist
    assert body[ "has_more" ] is True
    assert any( "truncated" in w for w in body[ "warnings" ] )   # NEVER a silent stop
    assert "[task_query WARN]" in capsys.readouterr().out


def test_byte_budget_always_admits_at_least_one_oversized_row( client, repo, monkeypatch ):
    # A budget that can return ZERO rows for a non-empty result is a pagination dead
    # end — the caller advances offset forever and never makes progress. One
    # oversized row plus truncated:true is honest AND advanceable.
    repo.query_tasks.return_value = [ make_item( body="y" * 5_000 ), make_item() ]
    repo.count_tasks.return_value = 2
    monkeypatch.setattr( tasks.rules, "RESPONSE_CHAR_BUDGET", 10 )

    body = client.get( "/api/tasks", params={ "owner_persona": "krishna" } ).json()

    assert body[ "count" ] == 1 and body[ "truncated" ] is True


def test_char_budget_zero_opts_the_DELIBERATE_SWEEP_out_of_truncation( client, repo, monkeypatch ):
    """
    THE ESCAPE, mirroring unscoped_audit. The multiplexer's dashboard poll
    (limit=500 + unscoped_audit=true) documents its own invariant in
    TaskListStore.ts — "the human's view is never silently truncated" — and the
    default budget cut it from 1100 available rows to 30 (measured live,
    2026-07-21). A protection that quietly shrinks the caller who asked for the
    whole board ON PURPOSE has become the defect it was built to prevent.
    """
    repo.query_tasks.return_value = [ make_item( body="q" * 2_000 ) for _ in range( 30 ) ]
    repo.count_tasks.return_value = 30
    monkeypatch.setattr( tasks.rules, "RESPONSE_CHAR_BUDGET", 5_000 )

    capped = client.get( "/api/tasks", params={ "unscoped_audit": "true" } ).json()
    assert capped[ "truncated" ] is True and capped[ "count" ] < 30      # the default protects

    swept = client.get( "/api/tasks", params={ "unscoped_audit": "true", "char_budget": 0 } ).json()
    assert swept[ "truncated" ] is False and swept[ "count" ] == 30      # ...and the escape releases
    assert swept[ "warnings" ] == [ ] or all( "truncated" not in w for w in swept[ "warnings" ] )


def test_char_budget_override_is_honored_over_the_default( client, repo, monkeypatch ):
    # A non-zero char_budget REPLACES the default in both directions — a caller can
    # tighten it as well as loosen it. Escapable by a caller who names the escape,
    # never escapable by accident (the default is what an unaware caller gets).
    repo.query_tasks.return_value = [ make_item( body="w" * 1_000 ) for _ in range( 20 ) ]
    repo.count_tasks.return_value = 20
    monkeypatch.setattr( tasks.rules, "RESPONSE_CHAR_BUDGET", 1_000_000 )   # default would NOT truncate

    body = client.get( "/api/tasks", params={ "owner_persona": "krishna", "char_budget": 2_500 } ).json()

    assert body[ "truncated" ] is True and body[ "count" ] < 20


def test_char_budget_rejects_a_negative_value( client, repo ):
    # ge=0 at the wire — a negative budget is a caller bug surfaced as 422, never
    # silently coerced into "unbounded" (which is what 0 means, deliberately).
    r = client.get( "/api/tasks", params={ "owner_persona": "krishna", "char_budget": -1 } )
    assert r.status_code == 422


def test_small_narrow_query_is_unchanged_except_for_the_added_keys( client, repo ):
    """
    AC-6 — THE NEGATIVE CONTROL. The everyday scoped query must be byte-for-byte
    what it was, plus the four new keys. If this arm ever truncates or drops a
    field, the size cap has started charging the callers it was meant to protect.
    """
    items = [ make_item( body="a normal body" ), make_item( status="claimed" ) ]
    repo.query_tasks.return_value = items
    repo.count_tasks.return_value = 2

    body = client.get( "/api/tasks", params={ "owner_persona": "krishna" } ).json()

    assert body[ "tasks" ] == [ tasks._serialize_item( i ) for i in items ]   # rows IDENTICAL
    assert body[ "count" ] == 2
    assert body[ "truncated" ] is False and body[ "warnings" ] == [ ]


def test_terse_page_at_the_measured_size_does_NOT_truncate( client, repo ):
    # The budget was sized so the CHEAP shape is never the thing it punishes: the
    # heaviest terse page measured 21,379 chars against a 100,000-char budget.
    repo.query_tasks.return_value = [ make_item( body="z" * 4_000 ) for _ in range( 100 ) ]
    repo.count_tasks.return_value = 100

    body = client.get( "/api/tasks", params={ "owner_persona": "krishna", "terse": "true" } ).json()

    assert body[ "truncated" ] is False and body[ "count" ] == 100


@pytest.mark.parametrize( "params", [
    { "limit": -1 },          # Postgres InvalidRowCountInLimitClause — was an authenticated 500
    { "limit": 501 },         # above the wire cap
    { "offset": -1 },
] )
def test_query_rejects_out_of_bounds_pagination( client, repo, params ):
    """N4: limit/offset bounds enforced at the wire (Query ge/le), never a DB 500."""
    r = client.get( "/api/tasks", params=params )
    assert r.status_code == 422
    repo.query_tasks.assert_not_called()


@pytest.mark.parametrize( "field, limit", [
    ( "project", 255 ),
    ( "created_by", 255 ),
    ( "owner_persona", 255 ),
    ( "accountable_manager", 255 ),
    ( "source_qid", 64 ),
    ( "correlation_key", 255 ),
] )
def test_create_rejects_overlong_varchar_backed_fields( client, repo, field, limit ):
    """N5: max_length mirrors the VARCHAR widths — overlong is a 422, not a DataError 500."""
    r = client.post( "/api/tasks", json=dict( _CREATE_BODY, **{ field: "x" * ( limit + 1 ) } ) )
    assert r.status_code == 422
    repo.create_item.assert_not_called()


# ---------------------------------------------------------------------------
# GET /api/tasks/{id} + /events
# ---------------------------------------------------------------------------

def test_get_task_404_when_missing( client, repo ):
    repo.get_by_id.return_value = None
    r = client.get( f"/api/tasks/{uuid.uuid4()}" )
    assert r.status_code == 404


def test_get_task_returns_serialized_item( client, repo ):
    item = make_item( body="framing payload", source_qid="c8c73fde-6ce4-4e8d-83d7-c55b5cce65a3" )
    repo.get_by_id.return_value = item
    r = client.get( f"/api/tasks/{item.id}" )
    assert r.status_code == 200
    body = r.json()
    assert body[ "body" ] == "framing payload" and body[ "source_qid" ].startswith( "c8c73fde" )


def test_get_events_404_when_item_missing( client, repo ):
    repo.get_by_id.return_value = None
    r = client.get( f"/api/tasks/{uuid.uuid4()}/events" )
    assert r.status_code == 404
    repo.get_events.assert_not_called()


def test_get_events_returns_trail_in_order( client, repo ):
    item = make_item()
    repo.get_by_id.return_value = item
    repo.get_events.return_value = [
        make_event( item.id, id=1, transition="->queued" ),
        make_event( item.id, id=2, transition="queued->claimed",
                    receipt_refs=None, authority="manager_relay" ),
    ]
    r = client.get( f"/api/tasks/{item.id}/events" )
    assert r.status_code == 200
    body = r.json()
    assert body[ "count" ] == 2
    assert [ e[ "transition" ] for e in body[ "events" ] ] == [ "->queued", "queued->claimed" ]
    assert body[ "events" ][ 1 ][ "authority" ] == "manager_relay"


# ---------------------------------------------------------------------------
# Phase 2 — reason on transitions (C12 pulled forward)
# ---------------------------------------------------------------------------

def test_transition_rejects_dropped_without_reason( client, repo ):
    repo.get_by_id_for_update.return_value = make_item( status="queued" )
    r = client.post( f"/api/tasks/{uuid.uuid4()}/transition",
                     json={ "to_status": "dropped", "actor": "tiffany d03e6219" } )
    assert r.status_code == 422
    assert any( "reason is REQUIRED" in e for e in r.json()[ "detail" ][ "errors" ] )


def test_transition_to_dropped_with_reason_serializes_it( client, repo ):
    item = make_item( status="queued" )
    repo.get_by_id_for_update.return_value = item
    repo.apply_transition.return_value = make_event(
        item.id, transition="queued->dropped", reason="superseded-by-rewrite" )

    r = client.post( f"/api/tasks/{item.id}/transition",
                     json={ "to_status": "dropped", "actor": "tiffany d03e6219",
                            "reason": "superseded-by-rewrite" } )

    assert r.status_code == 200
    assert r.json()[ "event" ][ "reason" ] == "superseded-by-rewrite"
    assert repo.apply_transition.call_args.kwargs[ "reason" ] == "superseded-by-rewrite"


def test_transition_reason_defaults_to_none_in_serialization( client, repo ):
    item = make_item( status="queued" )
    repo.get_by_id_for_update.return_value = item
    repo.apply_transition.return_value = make_event( item.id, transition="queued->claimed" )
    r = client.post( f"/api/tasks/{item.id}/transition",
                     json={ "to_status": "claimed", "actor": "a b" } )
    assert r.status_code == 200 and r.json()[ "event" ][ "reason" ] is None


def test_transition_rejects_overlong_reason( client, repo ):
    r = client.post( f"/api/tasks/{uuid.uuid4()}/transition",
                     json={ "to_status": "dropped", "actor": "a b", "reason": "x" * 4001 } )
    assert r.status_code == 422   # Pydantic max_length — never a DB error


# ---------------------------------------------------------------------------
# Phase 2 — POST /api/tasks/{id}/correlate (respawn adoption)
# ---------------------------------------------------------------------------

_CORRELATE_BODY = { "correlation_key": "cc-task:new-sid:8", "actor": "tiffany d03e6219" }


def test_correlate_404_when_missing( client, repo ):
    repo.get_by_id_for_update.return_value = None
    r = client.post( f"/api/tasks/{uuid.uuid4()}/correlate", json=_CORRELATE_BODY )
    assert r.status_code == 404


def test_correlate_422_on_malformed_uuid( client, repo ):
    r = client.post( "/api/tasks/not-a-uuid/correlate", json=_CORRELATE_BODY )
    assert r.status_code == 422
    repo.get_by_id_for_update.assert_not_called()


@pytest.mark.parametrize( "terminal", [ "done", "dropped" ] )
def test_correlate_rejects_terminal_items( client, repo, terminal ):
    repo.get_by_id_for_update.return_value = make_item( status=terminal )
    r = client.post( f"/api/tasks/{uuid.uuid4()}/correlate", json=_CORRELATE_BODY )
    assert r.status_code == 422
    assert any( "immutable" in e for e in r.json()[ "detail" ][ "errors" ] )
    repo.apply_correlation.assert_not_called()


def test_correlate_rejects_bad_authority( client, repo ):
    repo.get_by_id_for_update.return_value = make_item()
    r = client.post( f"/api/tasks/{uuid.uuid4()}/correlate",
                     json={ **_CORRELATE_BODY, "authority": "divine_right" } )
    assert r.status_code == 422
    assert any( "authority" in e for e in r.json()[ "detail" ][ "errors" ] )


def test_correlate_reports_terminal_and_authority_together( client, repo ):
    repo.get_by_id_for_update.return_value = make_item( status="done" )
    r = client.post( f"/api/tasks/{uuid.uuid4()}/correlate",
                     json={ **_CORRELATE_BODY, "authority": "divine_right" } )
    assert r.status_code == 422 and len( r.json()[ "detail" ][ "errors" ] ) == 2


def test_correlate_happy_path_returns_item_and_event( client, repo ):
    item = make_item( correlation_key="cc-task:old-sid:3" )
    repo.get_by_id_for_update.return_value = item
    repo.apply_correlation.return_value = make_event(
        item.id, transition="re-correlated",
        reason="correlation_key: cc-task:old-sid:3 -> cc-task:new-sid:8" )

    r = client.post( f"/api/tasks/{item.id}/correlate", json=_CORRELATE_BODY )

    assert r.status_code == 200
    body = r.json()
    assert body[ "event" ][ "transition" ] == "re-correlated"
    assert body[ "event" ][ "reason" ].endswith( "-> cc-task:new-sid:8" )
    kwargs = repo.apply_correlation.call_args.kwargs
    assert kwargs[ "correlation_key" ] == "cc-task:new-sid:8"
    assert kwargs[ "actor" ] == "tiffany d03e6219" and kwargs[ "authority" ] == "standing"
    # Row-locked read (N3 parity): the terminal check must not be raceable.
    repo.get_by_id_for_update.assert_called_once()
    repo.get_by_id.assert_not_called()


@pytest.mark.parametrize( "field,limit", [ ( "correlation_key", 255 ), ( "actor", 255 ) ] )
def test_correlate_rejects_overlong_fields( client, repo, field, limit ):
    r = client.post( f"/api/tasks/{uuid.uuid4()}/correlate",
                     json={ **_CORRELATE_BODY, field: "x" * ( limit + 1 ) } )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Phase 2.1 — PATCH /api/tasks/{id} (item-field edit)
# ---------------------------------------------------------------------------

_PATCH_BODY = { "title": "edited title", "actor": "krishna a38ee857" }


def test_patch_happy_path_returns_item_and_event( client, repo ):
    item = make_item( title="old title" )
    repo.get_by_id_for_update.return_value = item
    repo.apply_patch.return_value = make_event(
        item.id, transition="patched", reason="title: 'old title' -> 'edited title'" )

    r = client.patch( f"/api/tasks/{item.id}", json=_PATCH_BODY )

    assert r.status_code == 200
    body = r.json()
    assert body[ "event" ][ "transition" ] == "patched"
    args, kwargs = repo.apply_patch.call_args.args, repo.apply_patch.call_args.kwargs
    # fields passed positionally; actor/authority excluded from it. The
    # `title_trimmed` key rides along on every title edit (bug 769b3574) — it is
    # the flag being written to match the title now stored.
    assert args[ 1 ] == { "title": "edited title", "title_trimmed": False }
    assert kwargs[ "actor" ] == "krishna a38ee857" and kwargs[ "authority" ] == "standing"
    repo.get_by_id_for_update.assert_called_once()               # N3 row-lock parity
    repo.get_by_id.assert_not_called()


# ---------------------------------------------------------------------------
# PATCH — the SECOND write path (bug 28fc1fb4, 2026-07-21)
#
# This path whitelisted `title` and never called soft_guard_title, so the SAME
# string was capped at 60 through create and unbounded through PATCH — two write
# paths, two contradictory contracts, neither announced. The door widened when
# task_edit (3ac79d1d, 2026-07-21) shipped over PATCH.
#
# 🔴 THE TWO DOORS DISAGREE AGAIN AS OF 2026-09-01, AND THAT IS THE RULING
# (Rick, bug 6ce252e7: "Raise to 120 with a 422 over it."). The cap is one number
# in one place, as 28fc1fb4 required; what differs is the ANSWER above it — a
# create trims fail-open, an edit answers 422. The tests below assert the
# asymmetry deliberately, so nobody re-unifies the doors and calls it a fix.
# ---------------------------------------------------------------------------

def test_patch_over_cap_title_is_REJECTED_where_create_would_trim_it( client, repo ):
    """
    Rick's ruling, 2026-09-01 (bug 6ce252e7). This test used to assert the opposite
    — that an over-cap PATCH title was trimmed by the same helper create uses — and
    it is reversed here rather than deleted, because the reversal IS the change.

    An over-cap edit now answers 422 naming the ACTUAL LENGTH, and nothing is
    written: no trim, no relocated overflow, no apply_patch at all.
    """
    item = make_item( title="old title", body="the existing body" )
    repo.get_by_id_for_update.return_value = item
    long_title = "P" * ( tasks.rules.TITLE_SOFT_CAP + 35 )

    r = client.patch( f"/api/tasks/{item.id}", json={ "title": long_title, "actor": "krishna a38ee857" } )

    assert r.status_code == 422
    errors = r.json()[ "detail" ][ "errors" ]
    # The NUMBER is the point: "too long" without one makes the writer count
    # characters by hand to find out how much to cut.
    assert any( str( len( long_title ) ) in e and str( tasks.rules.TITLE_SOFT_CAP ) in e for e in errors )
    repo.apply_patch.assert_not_called()                          # nothing was written


def test_patch_at_EXACTLY_the_cap_is_accepted( client, repo ):
    """
    THE BOUNDARY, both sides of it. The test above uses cap+35; a rejection at the
    cap itself would be an off-by-one that the over-cap case cannot see, because
    both a `>` and a `>=` reject cap+35 identically.
    """
    item = make_item( title="old title", body="the existing body" )
    repo.get_by_id_for_update.return_value = item
    repo.apply_patch.return_value = make_event( item.id, transition="patched" )
    at_cap = "P" * tasks.rules.TITLE_SOFT_CAP

    r = client.patch( f"/api/tasks/{item.id}", json={ "title": at_cap, "actor": "krishna a38ee857" } )

    assert r.status_code == 200
    fields = repo.apply_patch.call_args.args[ 1 ]
    assert fields[ "title" ] == at_cap                            # stored whole, not cut
    assert fields[ "title_trimmed" ] is False
    assert "body" not in fields                                   # an edit never relocates


def test_patch_NEVER_relocates_an_overflow_into_a_body_any_more( client, repo ):
    """
    The retired behaviour, asserted as absent.

    This path used to relocate an over-cap title's overflow into the body the PATCH
    was writing, and a careful test guarded WHICH body it landed in. A rejection
    removes the whole question: an edit that cannot trim has no overflow to file.

    Driven with a title well over the cap AND a body in the same call — the exact
    input the old relocation logic existed for — and nothing is written.
    """
    item = make_item( title="old", body="about to be replaced" )
    repo.get_by_id_for_update.return_value = item

    r = client.patch( f"/api/tasks/{item.id}", json={
        "title": "R" * ( tasks.rules.TITLE_SOFT_CAP + 10 ),
        "body" : "the NEW body",
        "actor": "krishna a38ee857",
    } )

    assert r.status_code == 422
    repo.apply_patch.assert_not_called()                          # not even the body landed


def test_patch_under_cap_title_is_a_strict_no_op( client, repo ):
    # THE NEGATIVE CONTROL, byte-for-byte. A normal title edit must not acquire a
    # body delta: a `patched` audit event claiming a body change that never
    # happened is the audit trail lying about what it recorded.
    item = make_item( title="old title", body="untouched body" )
    repo.get_by_id_for_update.return_value = item
    repo.apply_patch.return_value = make_event( item.id, transition="patched" )

    r = client.patch( f"/api/tasks/{item.id}", json=_PATCH_BODY )

    assert r.json()[ "title_guard" ] is None
    fields = repo.apply_patch.call_args.args[ 1 ]
    # `title_trimmed: False` is NOT a manufactured delta — it is the flag being
    # written to match the title now stored (bug 769b3574). Every title edit writes
    # it; a body key would still be a fabrication and is still absent.
    assert fields == { "title": "edited title", "title_trimmed": False }


def test_patch_without_a_title_never_touches_the_body( client, repo ):
    # A non-title PATCH must not route through the guard at all.
    item = make_item( body="untouched body" )
    repo.get_by_id_for_update.return_value = item
    repo.apply_patch.return_value = make_event( item.id, transition="patched" )

    r = client.patch( f"/api/tasks/{item.id}", json={ "priority": "P1", "actor": "krishna a38ee857" } )

    assert r.json()[ "title_guard" ] is None
    assert repo.apply_patch.call_args.args[ 1 ] == { "priority": "P1" }


def test_create_STORES_the_trim_verdict_rather_than_leaving_it_to_be_re_derived( client, repo ):
    """
    Bug 769b3574. The create path already held soft_guard_title's third return value
    and threw it away; the flag was then re-computed at read time from the title's
    LENGTH, against whatever the cap happened to be.

    Both arms in one test, because a constant passes either one alone.
    """
    repo.create_item.return_value = make_item()

    # Derived from the cap, not a literal — the cap moved 60 -> 120 on 2026-09-01
    # and a hardcoded 90 silently became an UNDER-cap string, flipping this arm to
    # False while still reading like an over-cap test.
    r = client.post( "/api/tasks", json=dict( _CREATE_BODY, title="T" * ( tasks.rules.TITLE_SOFT_CAP + 30 ) ) )
    assert r.status_code == 201
    assert repo.create_item.call_args.kwargs[ "title_trimmed" ] is True

    r = client.post( "/api/tasks", json=dict( _CREATE_BODY, title="a title well under the cap" ) )
    assert r.status_code == 201
    assert repo.create_item.call_args.kwargs[ "title_trimmed" ] is False


def test_patch_CLEARS_the_flag_when_a_retitle_repairs_a_trimmed_title( client, repo ):
    """
    THE BUG I NEARLY BUILT, asserted so nobody else can.

    A stored flag is tempting to write only when the guard fires. That is wrong: six
    live rows were trimmed once and later REPAIRED by a shorter retitle, and their
    titles are complete sentences now. False is the correct answer for them, and a
    set-only flag would report True forever — getting on purpose the answer the old
    length check got right by accident.

    So the row starts flagged, takes an under-cap retitle, and must come out clear.
    """
    item = make_item( title="X" * 60, title_trimmed=True )
    repo.get_by_id_for_update.return_value = item
    repo.apply_patch.return_value = make_event( item.id, transition="patched" )

    r = client.patch( f"/api/tasks/{item.id}", json={ "title": "a repaired, complete title", "actor": "pocholo 056e2aeb" } )

    assert r.status_code == 200
    assert r.json()[ "title_guard" ] is None                       # nothing was cut this time
    assert repo.apply_patch.call_args.args[ 1 ][ "title_trimmed" ] is False


def test_patch_CANNOT_SET_the_flag_because_an_over_cap_retitle_is_refused( client, repo ):
    """
    The negative control for the clearing test above, rewritten to the new door.

    It used to assert the other direction — that an over-cap retitle came out
    FLAGGED — which was the proof that clearing was not unconditional. Under the
    2026-09-01 ruling an edit can never trim, so `title_trimmed` on this path is
    always False, and the thing that must not be unconditional is now the ACCEPTANCE:
    an over-cap retitle is refused and the row keeps the flag it already had.
    """
    item = make_item( title="a short clean title", title_trimmed=False )
    repo.get_by_id_for_update.return_value = item

    r = client.patch( f"/api/tasks/{item.id}", json={
        "title": "Y" * ( tasks.rules.TITLE_SOFT_CAP + 1 ), "actor": "pocholo 056e2aeb",
    } )

    assert r.status_code == 422
    repo.apply_patch.assert_not_called()


def test_a_patch_that_does_not_touch_the_title_leaves_the_flag_alone( client, repo ):
    """
    Scope control. The flag describes the TITLE, so a priority-only edit must not
    write it — otherwise an unrelated edit would stamp a verdict on a field it never
    looked at, which is the shape of bug 54924128 one column over.
    """
    item = make_item( title="X" * 60, title_trimmed=True )
    repo.get_by_id_for_update.return_value = item
    repo.apply_patch.return_value = make_event( item.id, transition="patched" )

    r = client.patch( f"/api/tasks/{item.id}", json={ "priority": "P1", "actor": "pocholo 056e2aeb" } )

    assert r.status_code == 200
    assert repo.apply_patch.call_args.args[ 1 ] == { "priority": "P1" }   # no title_trimmed key at all


def test_create_TRIMS_and_patch_REJECTS_the_very_same_over_cap_title( client, repo ):
    """
    THE ASYMMETRY ASSERTION, and it is the exact inverse of the parity assertion it
    replaces — recorded that way on purpose.

    The old test drove one over-cap title through both doors and required identical
    results, because bug 28fc1fb4 was the two doors disagreeing silently. Rick's
    2026-09-01 ruling makes them disagree deliberately: create trims fail-open
    because it is unattended and rejecting it loses the filing; edit answers 422
    because a writer is present and is the only party who knows which half of the
    string is the qualifier.

    Both arms in ONE test, driven from ONE string, so neither door can be changed
    without the other's behaviour being restated here.
    """
    long_title  = "S" * ( tasks.rules.TITLE_SOFT_CAP + 28 )
    shared_body = "a body on both paths"

    repo.create_item.return_value = make_item()
    created = client.post( "/api/tasks", json=dict( _CREATE_BODY, title=long_title, body=shared_body ) )

    item = make_item( body=shared_body )
    repo.get_by_id_for_update.return_value = item
    patched = client.patch( f"/api/tasks/{item.id}", json={ "title": long_title, "actor": "krishna a38ee857" } )

    # CREATE: accepted, trimmed to the cap, overflow relocated, advisory reported.
    assert created.status_code == 201
    assert created.json()[ "title_guard" ][ "trimmed" ] is True
    assert repo.create_item.call_args.kwargs[ "title" ] == long_title[ :tasks.rules.TITLE_SOFT_CAP ]

    # EDIT: refused outright, naming the length. Nothing written.
    assert patched.status_code == 422
    assert any( str( len( long_title ) ) in e for e in patched.json()[ "detail" ][ "errors" ] )
    repo.apply_patch.assert_not_called()

    # AND THE ONE NUMBER IS STILL ONE NUMBER — the doors differ in their ANSWER
    # above the cap, never in where the cap is. That is what 28fc1fb4 required and
    # this ruling does not undo.
    assert len( repo.create_item.call_args.kwargs[ "title" ] ) == tasks.rules.TITLE_SOFT_CAP


def test_patch_empty_editable_set_rejected( client, repo ):
    # Only actor, no editable field → 422 before any DB touch.
    r = client.patch( f"/api/tasks/{uuid.uuid4()}", json={ "actor": "a b" } )
    assert r.status_code == 422
    assert any( "at least one editable field" in e for e in r.json()[ "detail" ][ "errors" ] )
    repo.get_by_id_for_update.assert_not_called()
    repo.apply_patch.assert_not_called()


@pytest.mark.parametrize( "forbidden", [
    { "status": "done" },
    { "correlation_key": "cc-task:x:1" },
    { "blocked_by": [ ] },
    { "next_chase_ts": "2026-06-15T00:00:00+00:00" },
    { "receipt_refs": { "commit": "abc1234" } },
] )
def test_patch_forbids_oracle_fields_at_the_wire( client, repo, forbidden ):
    # extra='forbid' — naming a transition-oracle field is a 422, never a silent
    # drop. The hard no-bypass invariant (reviewer ruling 2026-06-15).
    r = client.patch( f"/api/tasks/{uuid.uuid4()}", json={ **forbidden, "actor": "a b" } )
    assert r.status_code == 422
    repo.apply_patch.assert_not_called()


def test_patch_rejects_junk_enum_fields( client, repo ):
    r = client.patch( f"/api/tasks/{uuid.uuid4()}",
                      json={ "priority": "P9", "gate_class": "side-gate", "actor": "a b" } )
    assert r.status_code == 422
    errors = r.json()[ "detail" ][ "errors" ]
    assert any( "priority" in e for e in errors ) and any( "gate_class" in e for e in errors )
    repo.get_by_id_for_update.assert_not_called()


def test_patch_rejects_bad_authority( client, repo ):
    r = client.patch( f"/api/tasks/{uuid.uuid4()}",
                      json={ **_PATCH_BODY, "authority": "divine_right" } )
    assert r.status_code == 422
    assert any( "authority" in e for e in r.json()[ "detail" ][ "errors" ] )
    repo.get_by_id_for_update.assert_not_called()


def test_patch_404_when_missing( client, repo ):
    repo.get_by_id_for_update.return_value = None
    r = client.patch( f"/api/tasks/{uuid.uuid4()}", json=_PATCH_BODY )
    assert r.status_code == 404
    repo.apply_patch.assert_not_called()


@pytest.mark.parametrize( "terminal", [ "done", "dropped" ] )
def test_patch_rejects_terminal_items( client, repo, terminal ):
    repo.get_by_id_for_update.return_value = make_item( status=terminal )
    r = client.patch( f"/api/tasks/{uuid.uuid4()}", json=_PATCH_BODY )
    assert r.status_code == 422
    assert any( "terminal" in e for e in r.json()[ "detail" ][ "errors" ] )
    repo.apply_patch.assert_not_called()


def test_patch_422_on_malformed_uuid( client, repo ):
    r = client.patch( "/api/tasks/not-a-uuid", json=_PATCH_BODY )
    assert r.status_code == 422
    repo.get_by_id_for_update.assert_not_called()


# ---------------------------------------------------------------------------
# GET /api/tasks/events (cross-item stream)
# ---------------------------------------------------------------------------

def test_event_stream_returns_events_and_count( client, repo ):
    item_id = uuid.uuid4()
    repo.query_events.return_value = [
        make_event( item_id, id=2, transition="queued->in_progress" ),
        make_event( item_id, id=1, transition="->queued" ),
    ]
    r = client.get( "/api/tasks/events" )
    assert r.status_code == 200
    body = r.json()
    assert body[ "count" ] == 2 and len( body[ "events" ] ) == 2
    assert body[ "events" ][ 0 ][ "transition" ] == "queued->in_progress"


def test_event_stream_static_path_wins_over_uuid_route( client, repo ):
    # /tasks/events must resolve to the stream handler, NOT /tasks/{task_id}
    # (which would 422 parsing "events" as a UUID). Declaration order is the
    # guarantee — pin it so a future reorder can't silently regress it.
    repo.query_events.return_value = [ ]
    r = client.get( "/api/tasks/events" )
    assert r.status_code == 200
    repo.query_events.assert_called_once()
    repo.get_by_id.assert_not_called()                       # the per-item route is never touched


def test_event_stream_passes_all_filters_through( client, repo ):
    repo.query_events.return_value = [ ]
    r = client.get( "/api/tasks/events", params={
        "actor"      : "krishna a38ee857",
        "transition" : "queued->done",
        "project"    : "lupin",
        "since"      : "2026-06-01T00:00:00+00:00",
        "until"      : "2026-06-30T00:00:00+00:00",
        "limit"      : 12,
        "offset"     : 6,
    } )
    assert r.status_code == 200 and r.json() == { "events": [ ], "count": 0 }
    kwargs = repo.query_events.call_args.kwargs
    assert kwargs[ "actor" ]      == "krishna a38ee857"
    assert kwargs[ "transition" ] == "queued->done"
    assert kwargs[ "project" ]    == "lupin"
    assert kwargs[ "since" ].isoformat() == "2026-06-01T00:00:00+00:00"
    assert kwargs[ "until" ].isoformat() == "2026-06-30T00:00:00+00:00"
    assert kwargs[ "limit" ] == 12 and kwargs[ "offset" ] == 6


@pytest.mark.parametrize( "params", [
    { "limit": -1 },
    { "offset": -1 },
    { "limit": 501 },
] )
def test_event_stream_rejects_out_of_bounds_pagination( client, repo, params ):
    r = client.get( "/api/tasks/events", params=params )
    assert r.status_code == 422
    repo.query_events.assert_not_called()


# ---------------------------------------------------------------------------
# Phase 2 — persona-identity canonicalization at the /api/tasks choke point.
# Each test is a FLIP: it asserts the value REACHING the repo (write) or the
# repo query (read) is the canonical store key. Revert the router's _canon_*
# helpers to the raw payload value and the "maria"/"mr radio" assertions fail.
# ---------------------------------------------------------------------------

def test_create_canonicalizes_owner_and_manager_FLIP( client, repo ):
    repo.create_item.return_value = make_item()
    client.post( "/api/tasks", json=dict( _CREATE_BODY,
                 owner_persona="María", accountable_manager="Mr. Radio" ) )
    kwargs = repo.create_item.call_args.kwargs
    assert kwargs[ "owner_persona" ]       == "maria"        # was "María"
    assert kwargs[ "accountable_manager" ] == "mr radio"     # was "Mr. Radio"


def test_create_blank_persona_stays_none( client, repo ):
    # A blank owner canonicalizes to None (a falsy create field stays falsy —
    # never the "" sentinel) so it does not turn into an empty-string owner.
    # Uses a NON-owned class (decision) so the policy-2 class-scoped owner default
    # does not fill it — isolating the _canon_persona blank->None behavior guarded.
    repo.create_item.return_value = make_item()
    client.post( "/api/tasks", json=dict( _CREATE_BODY, item_class="decision", owner_persona="  !!  " ) )
    assert repo.create_item.call_args.kwargs[ "owner_persona" ] is None


def test_query_canonicalizes_owner_filter_FLIP( client, repo ):
    # The READ seam — the direct fix for the 2026-06-18 false-idle: a "María"
    # filter must query the store's "maria" rows.
    repo.query_tasks.return_value = [ ]
    client.get( "/api/tasks", params={ "owner_persona": "María", "accountable_manager": "Mr. Radio" } )
    kwargs = repo.query_tasks.call_args.kwargs
    assert kwargs[ "owner_persona" ]       == "maria"
    assert kwargs[ "accountable_manager" ] == "mr radio"


def test_count_only_canonicalizes_owner_filter_FLIP( client, repo ):
    repo.count_tasks.return_value = 0
    client.get( "/api/tasks", params={ "owner_persona": "Mr. Radio", "count_only": "true" } )
    assert repo.count_tasks.call_args.kwargs[ "owner_persona" ] == "mr radio"


def test_transition_canonicalizes_persona_blocked_by_FLIP( client, repo ):
    # A persona-typed blocked_by ref ("Mr. Radio") is stored canonical so a
    # "blocked on Mr. Radio" item lines up with that persona's owner rows; a
    # user-typed ref is left untouched (only kind=="persona" is canonicalized).
    item  = make_item( status="claimed", updated_ts=NOW )
    repo.get_by_id_for_update.return_value = item
    repo.apply_transition.return_value     = make_event( item.id, transition="claimed->blocked" )
    blocked = [ { "kind": "persona", "id": "Mr. Radio" }, { "kind": "user", "id": "Rick" } ]
    client.post( f"/api/tasks/{item.id}/transition",
                 json=_transition_body( to_status="blocked",
                                        next_chase_ts="2026-06-30T00:00:00+00:00",
                                        blocked_by=blocked ) )
    sent = repo.apply_transition.call_args.kwargs[ "blocked_by" ]
    assert sent[ 0 ] == { "kind": "persona", "id": "mr radio" }   # was "Mr. Radio"
    assert sent[ 1 ] == { "kind": "user", "id": "Rick" }          # user ref untouched


def test_patch_canonicalizes_owner_persona_FLIP( client, repo ):
    # Re-owning an item via PATCH must store the canonical key, same as create.
    item = make_item()
    repo.get_by_id_for_update.return_value = item
    repo.apply_patch.return_value = make_event( item.id, transition="patched" )
    client.patch( f"/api/tasks/{item.id}",
                  json={ "owner_persona": "María", "actor": "krishna a38ee857" } )
    fields = repo.apply_patch.call_args.args[ 1 ]
    assert fields[ "owner_persona" ] == "maria"                   # was "María"


# ---------------------------------------------------------------------------
# Bug de653086 — project-alias canonicalization at the /api/tasks choke point.
# The project-axis twin of the persona FLIPs above: each asserts the project
# value REACHING the repo (write) or the repo query (read) is the canonical
# alias form ("planning-is-prompting" -> "plan"). Revert the router's
# _canon_project helper to the raw payload value and the "plan" assertions
# fail. Closes the false-idle gap where a row written under the raw repo name
# splits out of the owed-oracle's alias-normalized project filter.
# ---------------------------------------------------------------------------

def test_create_canonicalizes_project_FLIP( client, repo ):
    # A new row must store the canonical alias form, so the owed-oracle (which
    # queries project="plan") finds it — symmetric with persona canonicalization.
    repo.create_item.return_value = make_item()
    client.post( "/api/tasks", json=dict( _CREATE_BODY, project="planning-is-prompting" ) )
    assert repo.create_item.call_args.kwargs[ "project" ] == "plan"   # was "planning-is-prompting"


def test_create_non_aliased_project_unchanged( client, repo ):
    # A non-aliased repo name is returned verbatim (idempotent / no false rewrite).
    repo.create_item.return_value = make_item()
    client.post( "/api/tasks", json=dict( _CREATE_BODY, project="lupin" ) )
    assert repo.create_item.call_args.kwargs[ "project" ] == "lupin"


def test_query_canonicalizes_project_filter_FLIP( client, repo ):
    # The READ seam: a query by the raw repo name must match rows stored under
    # the canonical alias — read and write agree on one form at the server.
    repo.query_tasks.return_value = [ ]
    client.get( "/api/tasks", params={ "project": "planning-is-prompting" } )
    assert repo.query_tasks.call_args.kwargs[ "project" ] == "plan"


def test_count_only_canonicalizes_project_filter_FLIP( client, repo ):
    repo.count_tasks.return_value = 0
    client.get( "/api/tasks", params={ "project": "planning-is-prompting", "count_only": "true" } )
    assert repo.count_tasks.call_args.kwargs[ "project" ] == "plan"


# ---------------------------------------------------------------------------
# Phase 2.2 — POST /api/tasks/{id}/amend (append-only body amendment)
# ---------------------------------------------------------------------------

_AMEND_BODY = { "note": "SCOPE REFRAME: subscriber path now.", "actor": "arnold 8b7225c4" }


def test_amend_404_when_missing( client, repo ):
    repo.get_by_id_for_update.return_value = None
    r = client.post( f"/api/tasks/{uuid.uuid4()}/amend", json=_AMEND_BODY )
    assert r.status_code == 404
    repo.apply_amendment.assert_not_called()


def test_amend_422_on_malformed_uuid( client, repo ):
    r = client.post( "/api/tasks/not-a-uuid/amend", json=_AMEND_BODY )
    assert r.status_code == 422
    repo.get_by_id_for_update.assert_not_called()


@pytest.mark.parametrize( "terminal", [ "done", "dropped" ] )
def test_amend_allowed_on_terminal_items( client, repo, terminal ):
    # Rick's ruling 2026-08-02 (row 3c569786): amend is the ONE write verb allowed
    # on a CLOSED row — a gate verdict written after a worker self-closes has a
    # durable home. No 422; the router calls apply_amendment (repo marks the block
    # a post-terminal addendum + stamps 'amended_post_terminal'). Status untouched.
    item = make_item( status=terminal, body="CLOSED BY WORKER." )
    repo.get_by_id_for_update.return_value = item
    repo.apply_amendment.return_value = make_event(
        item.id, transition="amended_post_terminal", reason="gate: I re-ran the suite, verified" )
    r = client.post( f"/api/tasks/{item.id}/amend",
                     json={ **_AMEND_BODY, "reason": "gate: I re-ran the suite, verified" } )
    assert r.status_code == 200
    assert r.json()[ "event" ][ "transition" ] == "amended_post_terminal"
    repo.apply_amendment.assert_called_once()
    # The router never rejects a closed row for BEING closed.
    assert item.status == terminal


def test_amend_rejects_bad_authority( client, repo ):
    repo.get_by_id_for_update.return_value = make_item()
    r = client.post( f"/api/tasks/{uuid.uuid4()}/amend",
                     json={ **_AMEND_BODY, "authority": "divine_right" } )
    assert r.status_code == 422
    assert any( "authority" in e for e in r.json()[ "detail" ][ "errors" ] )
    repo.apply_amendment.assert_not_called()


def test_amend_rejects_blank_note( client, repo ):
    # min_length=1 lets a whitespace-only note THROUGH the wire; the handler's
    # strip-guard rejects it so no meaningless empty amendment block is written.
    repo.get_by_id_for_update.return_value = make_item()
    r = client.post( f"/api/tasks/{uuid.uuid4()}/amend",
                     json={ **_AMEND_BODY, "note": "   " } )
    assert r.status_code == 422
    assert any( "note" in e for e in r.json()[ "detail" ][ "errors" ] )
    repo.apply_amendment.assert_not_called()


def test_amend_rejects_empty_note_at_wire( client, repo ):
    # An empty-string note is a Pydantic min_length 422 BEFORE the handler runs.
    r = client.post( f"/api/tasks/{uuid.uuid4()}/amend",
                     json={ **_AMEND_BODY, "note": "" } )
    assert r.status_code == 422
    repo.get_by_id_for_update.assert_not_called()


# ---------------------------------------------------------------------------
# Envelope-tail refusal on the amend path (row 91ccbc26, Mr. Radio 2026-08-29)
# ---------------------------------------------------------------------------
#
# `note` is the THIRD carrier the differential probe measured — it stored a
# canary verbatim exactly as park_reason did. These pin the ENDPOINT, not just
# the predicate: the guard is only worth having if a real POST is refused and
# apply_amendment is never reached.

_INVOKE_CLOSE = "<" + "/" + "invoke>"


def test_amend_rejects_a_note_ending_in_a_captured_envelope_tag( client, repo ):
    repo.get_by_id_for_update.return_value = make_item()
    r = client.post( f"/api/tasks/{uuid.uuid4()}/amend",
                     json={ **_AMEND_BODY, "note": "the checklist is done." + _INVOKE_CLOSE } )
    assert r.status_code == 422
    assert any( "note ends with" in e for e in r.json()[ "detail" ][ "errors" ] )
    repo.apply_amendment.assert_not_called()


def test_amend_rejects_a_reason_ending_in_a_captured_envelope_tag( client, repo ):
    # The amend payload's own `reason` rides the same transport as the note.
    repo.get_by_id_for_update.return_value = make_item()
    r = client.post( f"/api/tasks/{uuid.uuid4()}/amend",
                     json={ **_AMEND_BODY, "reason": "recording the verdict" + _INVOKE_CLOSE } )
    assert r.status_code == 422
    assert any( "reason ends with" in e for e in r.json()[ "detail" ][ "errors" ] )
    repo.apply_amendment.assert_not_called()


def test_amend_ACCEPTS_a_note_that_quotes_the_tag_mid_sentence( client, repo ):
    # 🔴 THE CONTROL, at the endpoint. Under a refusal policy a false positive
    # blocks real work — and an amendment DOCUMENTING this defect must quote the
    # offending tag. Row 91ccbc26's own amendments do exactly this.
    item = make_item()
    repo.get_by_id_for_update.return_value = item
    repo.apply_amendment.return_value = make_event( item.id, transition="amended" )
    r = client.post( f"/api/tasks/{item.id}/amend",
                     json={ **_AMEND_BODY,
                            "note": "The tail was " + _INVOKE_CLOSE + " and I stripped it by hand." } )
    assert r.status_code == 200
    repo.apply_amendment.assert_called_once()


def test_amend_reports_a_blank_note_and_a_captured_tag_together( client, repo ):
    # One round trip, every violation — the module's existing discipline.
    repo.get_by_id_for_update.return_value = make_item()
    r = client.post( f"/api/tasks/{uuid.uuid4()}/amend",
                     json={ **_AMEND_BODY, "note": "   ",
                            "reason": "see above" + _INVOKE_CLOSE } )
    assert r.status_code == 422
    errors = r.json()[ "detail" ][ "errors" ]
    assert any( "note must be a non-blank string" in e for e in errors )
    assert any( "reason ends with" in e for e in errors )
    repo.apply_amendment.assert_not_called()


def test_amend_reports_all_violations_together( client, repo ):
    repo.get_by_id_for_update.return_value = make_item( status="done" )
    r = client.post( f"/api/tasks/{uuid.uuid4()}/amend",
                     json={ **_AMEND_BODY, "authority": "divine_right", "note": "   " } )
    # bad authority + blank note -> both at once. A terminal item is NO LONGER a
    # violation (Rick 2026-08-02), so it is not among the reported errors.
    assert r.status_code == 422 and len( r.json()[ "detail" ][ "errors" ] ) == 2
    assert not any( "closed history" in e for e in r.json()[ "detail" ][ "errors" ] )
    repo.apply_amendment.assert_not_called()


def test_amend_happy_path_returns_item_and_event( client, repo ):
    item = make_item( body="ORIGINAL." )
    repo.get_by_id_for_update.return_value = item
    repo.apply_amendment.return_value = make_event(
        item.id, transition="amended", reason="manager ruling" )

    r = client.post( f"/api/tasks/{item.id}/amend",
                     json={ **_AMEND_BODY, "reason": "manager ruling" } )

    assert r.status_code == 200
    body = r.json()
    assert body[ "event" ][ "transition" ] == "amended"
    kwargs = repo.apply_amendment.call_args.kwargs
    assert kwargs[ "note" ]      == "SCOPE REFRAME: subscriber path now."
    assert kwargs[ "actor" ]     == "arnold 8b7225c4"
    assert kwargs[ "authority" ] == "standing"
    assert kwargs[ "reason" ]    == "manager ruling"
    # The router owns the clock -> passes a tz-aware datetime the repo stamps.
    assert kwargs[ "now" ].tzinfo is not None
    # Row-locked read (N3 parity): the terminal check must not be raceable.
    repo.get_by_id_for_update.assert_called_once()
    repo.get_by_id.assert_not_called()


@pytest.mark.parametrize( "field,limit", [ ( "note", 4000 ), ( "actor", 255 ), ( "reason", 4000 ) ] )
def test_amend_rejects_overlong_fields( client, repo, field, limit ):
    r = client.post( f"/api/tasks/{uuid.uuid4()}/amend",
                     json={ **_AMEND_BODY, field: "x" * ( limit + 1 ) } )
    assert r.status_code == 422   # Pydantic max_length — never a DB error


# ---------------------------------------------------------------------------
# Persona-key follow-on policy (2026-07-11, task c03d1870):
#   (2) class-scoped owner default on CREATE, and
#   (1) unknown-persona soft-flag on the CREATE and reassign(PATCH) paths.
# Design: src/rnd/v0.1.9/2026.07.11-persona-key-followon-policy.md
# ---------------------------------------------------------------------------

@pytest.mark.parametrize( "ownerless_class", [ "decision", "gate" ] )
def test_create_ownerless_classes_do_not_default_owner( client, repo, ownerless_class ):
    # decision/gate are operator-queue rows — ownerless BY DESIGN, so an omitted
    # owner is NOT defaulted (they are not in DEFAULT_OWNER_CLASSES).
    repo.create_item.return_value = make_item()
    client.post( "/api/tasks", json=dict( _CREATE_BODY, item_class=ownerless_class ) )
    assert repo.create_item.call_args.kwargs[ "owner_persona" ] is None


@pytest.mark.parametrize( "owned_class", [ "task", "bug", "review_request" ] )
def test_create_owned_classes_default_owner_to_creator( client, repo, owned_class ):
    repo.create_item.return_value = make_item()
    client.post( "/api/tasks", json=dict( _CREATE_BODY, item_class=owned_class ) )
    assert repo.create_item.call_args.kwargs[ "owner_persona" ] == "krishna"


def test_create_explicit_owner_not_overridden_by_default( client, repo ):
    # An explicit owner is kept as-is; the default only fills an OMITTED owner.
    repo.create_item.return_value = make_item()
    client.post( "/api/tasks", json=dict( _CREATE_BODY, owner_persona="Tiberius" ) )
    assert repo.create_item.call_args.kwargs[ "owner_persona" ] == "tiberius"


def test_create_on_roster_owner_no_flag( client, repo ):
    repo.create_item.return_value = make_item()
    r = client.post( "/api/tasks", json=dict( _CREATE_BODY, owner_persona="krishna" ) )
    assert r.json()[ "persona_flag" ] is None
    assert repo.create_item.call_args.kwargs[ "flag_suffix" ] is None


def test_create_off_roster_owner_soft_flagged( client, repo ):
    repo.create_item.return_value = make_item()
    r = client.post( "/api/tasks", json=dict( _CREATE_BODY, owner_persona="Ziggy Stardust" ) )
    assert r.status_code == 201                                # soft-flag, NEVER a 422
    assert r.json()[ "persona_flag" ] == { "owner_persona": "ziggy stardust" }
    assert repo.create_item.call_args.kwargs[ "flag_suffix" ] == "[persona_flag: owner 'ziggy stardust' off-roster]"


def test_create_off_roster_default_owner_flagged( client, repo ):
    # A NEW persona (off-roster) filing its own founding item: the DEFAULTED owner
    # is itself off-roster and gets flagged — but the write still succeeds (María's
    # founding-P1 scenario: soft-flag, not a hard gate that would have blocked it).
    repo.create_item.return_value = make_item()
    r = client.post( "/api/tasks", json=dict( _CREATE_BODY, created_by="ziggy 5a1f17f8" ) )
    assert r.status_code == 201
    assert r.json()[ "persona_flag" ] == { "owner_persona": "ziggy" }
    assert repo.create_item.call_args.kwargs[ "owner_persona" ] == "ziggy"


def test_create_off_roster_manager_flagged( client, repo ):
    repo.create_item.return_value = make_item()
    r = client.post( "/api/tasks", json=dict( _CREATE_BODY, accountable_manager="Ziggy" ) )
    assert r.json()[ "persona_flag" ] == { "accountable_manager": "ziggy" }
    assert repo.create_item.call_args.kwargs[ "flag_suffix" ] == "[persona_flag: manager 'ziggy' off-roster]"


def test_patch_off_roster_owner_soft_flagged( client, repo ):
    item = make_item()
    repo.get_by_id_for_update.return_value = item
    repo.apply_patch.return_value = make_event( item.id, transition="patched" )
    r = client.patch( f"/api/tasks/{item.id}",
                      json={ "owner_persona": "Ziggy Stardust", "actor": "mr radio 372f9dc9" } )
    assert r.status_code == 200                                # soft-flag, NEVER a 422
    assert r.json()[ "persona_flag" ] == { "owner_persona": "ziggy stardust" }
    assert repo.apply_patch.call_args.kwargs[ "flag_suffix" ] == "[persona_flag: owner 'ziggy stardust' off-roster]"


def test_patch_on_roster_owner_no_flag( client, repo ):
    item = make_item()
    repo.get_by_id_for_update.return_value = item
    repo.apply_patch.return_value = make_event( item.id, transition="patched" )
    r = client.patch( f"/api/tasks/{item.id}",
                      json={ "owner_persona": "tiberius", "actor": "mr radio 372f9dc9" } )
    assert r.json()[ "persona_flag" ] is None
    assert repo.apply_patch.call_args.kwargs[ "flag_suffix" ] is None


def test_patch_non_persona_field_not_flagged( client, repo ):
    # A PATCH touching no persona field never flags (owner/manager absent → None).
    item = make_item()
    repo.get_by_id_for_update.return_value = item
    repo.apply_patch.return_value = make_event( item.id, transition="patched" )
    r = client.patch( f"/api/tasks/{item.id}",
                      json={ "priority": "P0", "actor": "mr radio 372f9dc9" } )
    assert r.json()[ "persona_flag" ] is None
    assert repo.apply_patch.call_args.kwargs[ "flag_suffix" ] is None


# ---------------------------------------------------------------------------
# PARKED-STATUS (2026-07-19) — R1 WIRING guards (Krishna, seat 2)
# ---------------------------------------------------------------------------
#
# These live HERE, not in Rachel's parity gate, for a structural reason: her
# harness proves the PREDICATE against in-memory SQLite and never builds a
# router call, so a wiring DEFAULT is invisible to it. Mutant (a) is the one we
# most risked each assuming the other covered — it is a default, the easiest
# thing in this diff to flip by accident and the hardest to notice, because
# flipping it leaves every predicate test green while park-active rows silently
# return to the board (the entire user-visible point of the feature).

def test_query_defaults_to_hiding_park_active_rows( client, repo ):
    """MUTANT GUARD (a): flip the router's hide_parked default True->False and
    this goes RED. Nothing else in the suite would."""
    repo.query_tasks.return_value = [ ]
    client.get( "/api/tasks?owner_persona=krishna" )
    assert repo.query_tasks.call_args.kwargs[ "hide_parked" ] is True, (
        "park-ACTIVE rows must be hidden by DEFAULT — a flipped default silently "
        "returns them to the board while every predicate test stays green"
    )


def test_count_only_path_also_defaults_to_hiding_park_active( client, repo ):
    """The COUNT(*) seam must carry the SAME default as the page. Asserted even
    though _apply_owed_filter is shared by both: a shared helper is not proof
    that both callers actually reached it."""
    repo.count_tasks.return_value = 0
    client.get( "/api/tasks?owner_persona=krishna&count_only=true" )
    assert repo.count_tasks.call_args.kwargs[ "hide_parked" ] is True


def test_include_parked_false_surfaces_park_active_rows( client, repo ):
    """The audit surface: hide_parked=false must reach the repository, so
    task_query(include_parked=True) can see what is parked and why."""
    repo.query_tasks.return_value = [ ]
    client.get( "/api/tasks?owner_persona=krishna&hide_parked=false" )
    assert repo.query_tasks.call_args.kwargs[ "hide_parked" ] is False


def test_owed_only_defaults_off_and_forwards_when_asked( client, repo ):
    """owed_only is OPT-IN and must never become the board's default: it would
    narrow the UI to queued/in_progress/expired-parked and silently vanish every
    blocked / claimed / review row — the same widening class rejected at the
    Stop-hook seam, arriving through the opposite door."""
    repo.query_tasks.return_value = [ ]
    client.get( "/api/tasks?owner_persona=krishna" )
    assert repo.query_tasks.call_args.kwargs[ "owed_only" ] is False
    client.get( "/api/tasks?owner_persona=krishna&owed_only=true" )
    assert repo.query_tasks.call_args.kwargs[ "owed_only" ] is True


# ---------------------------------------------------------------------------
# blocker_terminal + the unsatisfiable-blocker reject (store row 00a6bde2)
# ---------------------------------------------------------------------------

def _blocked_item( blocker_id, **overrides ):
    return make_item( status="blocked",
                      blocked_by=[ { "kind": "item", "id": str( blocker_id ) } ],
                      next_chase_ts=NOW,
                      **overrides )


@pytest.mark.parametrize( "terse", [ True, False ] )
@pytest.mark.parametrize( "blocker_status,expected", [ ( "done", True ), ( "dropped", True ), ( "queued", False ) ] )
def test_blocker_terminal_rides_both_projections_and_they_agree( client, repo, terse, blocker_status, expected ):
    """
    The flag must reach BOTH shapes and mean the same thing in each. The terse
    projection is what a board glance reads, and a stranded row is excluded from the
    workable-now count by design — a flag carried only by the full row is a flag nobody
    sees, on exactly the rows nobody looks at.
    """
    blocker_id = uuid.uuid4()
    repo.query_tasks.return_value       = [ _blocked_item( blocker_id ) ]
    repo.statuses_for_ids.return_value  = { str( blocker_id ): blocker_status }

    r = client.get( "/api/tasks", params={ "owner_persona": "krishna", "terse": str( terse ).lower() } )

    row = r.json()[ "tasks" ][ 0 ]
    assert type( row[ "blocker_terminal" ] ) is bool         # TYPE FIRST — None is falsy
    assert row[ "blocker_terminal" ] is expected


def test_blocker_statuses_resolve_in_ONE_query_for_the_whole_page( client, repo ):
    """
    One query per PAGE, not per row: resolving inside the serializer would put an N+1
    on the glance the terse projection exists to make cheap. Also pins the SCOPE — only
    the page's own blockers are asked about, which is what keeps un-asked ids silent
    rather than accidentally flagged.
    """
    a, b = uuid.uuid4(), uuid.uuid4()
    repo.query_tasks.return_value      = [ _blocked_item( a ), _blocked_item( b ), make_item() ]
    repo.statuses_for_ids.return_value = { str( a ): "done", str( b ): "queued" }

    client.get( "/api/tasks", params={ "owner_persona": "krishna" } )

    repo.statuses_for_ids.assert_called_once()
    asked = list( repo.statuses_for_ids.call_args.args[ 0 ] )
    assert sorted( asked ) == sorted( [ str( a ), str( b ) ] )   # the unblocked row adds nothing


def test_get_one_task_carries_the_flag_too( client, repo ):
    """
    `task_get` is what row 00a6bde2's own body tells a builder to use to re-derive a
    blocker's status by hand. A flag on the list surface but not here would send exactly
    that reader to the one projection that cannot answer the question.
    """
    blocker_id = uuid.uuid4()
    item       = _blocked_item( blocker_id )
    repo.get_by_id.return_value        = item
    repo.statuses_for_ids.return_value = { str( blocker_id ): "dropped" }

    r = client.get( f"/api/tasks/{item.id}" )

    assert r.status_code == 200
    assert r.json()[ "blocker_terminal" ] is True


@pytest.mark.parametrize( "blocker_status,fragment", [
    ( "done",    "already done" ),
    ( "dropped", "already dropped" ),
    ( None,      "no such item" ),
] )
def test_transition_to_blocked_rejects_an_unsatisfiable_edge( client, repo, blocker_status, fragment ):
    """
    THE CHEAP HALF, at the seam where the mistake is made. Note what it does NOT reach:
    all six live instances had blockers that went terminal LONG AFTER the edge was
    written, so this 422 is structurally incapable of catching them. That is why the
    read-side flag above is the load-bearing half.
    """
    blocker_id = uuid.uuid4()
    repo.get_by_id_for_update.return_value = make_item( status="queued" )
    repo.statuses_for_ids.return_value     = { str( blocker_id ): blocker_status }

    r = client.post( f"/api/tasks/{uuid.uuid4()}/transition", json=_transition_body(
        to_status     = "blocked",
        blocked_by    = [ { "kind": "item", "id": str( blocker_id ) } ],
        next_chase_ts = NOW.isoformat(),
    ) )

    assert r.status_code == 422
    assert fragment in r.json()[ "detail" ]
    repo.apply_transition.assert_not_called()


def test_transition_to_blocked_on_a_LIVE_item_still_works( client, repo ):
    """
    THE CONTROL THAT MUST FAIL IF THE GATE IS INVERTED. A guard that blocks correct work
    is an outage, and an outage gets disabled.
    """
    blocker_id = uuid.uuid4()
    item       = make_item( status="queued" )
    repo.get_by_id_for_update.return_value = item
    repo.statuses_for_ids.return_value     = { str( blocker_id ): "in_progress" }
    repo.apply_transition.return_value     = make_event( item.id, transition="queued->blocked" )

    r = client.post( f"/api/tasks/{item.id}/transition", json=_transition_body(
        to_status     = "blocked",
        blocked_by    = [ { "kind": "item", "id": str( blocker_id ) } ],
        next_chase_ts = NOW.isoformat(),
    ) )

    assert r.status_code == 200
    repo.apply_transition.assert_called_once()


def test_the_reject_names_EVERY_offending_id_not_just_the_first( client, repo ):
    """
    A caller fixing one edge should not have to submit again to discover the next —
    same contract as _reject_if_errors, which carries every violation at once.
    """
    dead_a, dead_b, live = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    repo.get_by_id_for_update.return_value = make_item( status="queued" )
    repo.statuses_for_ids.return_value     = {
        str( dead_a ): "done", str( dead_b ): None, str( live ): "queued",
    }

    r = client.post( f"/api/tasks/{uuid.uuid4()}/transition", json=_transition_body(
        to_status     = "blocked",
        blocked_by    = [ { "kind": "item", "id": str( x ) } for x in ( dead_a, dead_b, live ) ],
        next_chase_ts = NOW.isoformat(),
    ) )

    assert r.status_code == 422
    detail = r.json()[ "detail" ]
    assert str( dead_a ) in detail and str( dead_b ) in detail
    assert str( live ) not in detail                         # a live blocker is not an offence


@pytest.mark.parametrize( "ref", [ { "kind": "persona", "id": "sam" }, { "kind": "user", "id": "rick" } ] )
def test_the_reject_never_fires_on_a_persona_or_user_ref( client, repo, ref ):
    """
    Neither arm has a resolvable lifecycle. Rejecting on one would block legitimate
    writes on the strength of an instrument that does not exist (rows 6f8fd858 / 91067e47).
    """
    item = make_item( status="queued" )
    repo.get_by_id_for_update.return_value = item
    repo.apply_transition.return_value     = make_event( item.id, transition="queued->blocked" )

    r = client.post( f"/api/tasks/{item.id}/transition", json=_transition_body(
        to_status="blocked", blocked_by=[ ref ], next_chase_ts=NOW.isoformat(),
    ) )

    assert r.status_code == 200
    repo.statuses_for_ids.assert_not_called()                # no item arm => no query at all


def test_terse_carries_project_so_the_census_is_cheap( client, repo ):
    """
    Row d23147e8. Without `project` in terse, answering "which project strings exist in this
    store?" costs 1,227 FULL rows — so the census that catches an orphan alias is heroic rather
    than routine, and the next orphan gets found by accident too.

    Asserted as a VALUE, not merely a key: a present-but-null field would satisfy an exact-set
    check and still leave the census impossible.
    """
    repo.query_tasks.return_value = [ make_item( project="skills-distillation" ) ]
    row = client.get( "/api/tasks", params={ "owner_persona": "krishna", "terse": "true" } ).json()[ "tasks" ][ 0 ]
    assert row[ "project" ] == "skills-distillation"


def test_terse_and_full_agree_about_project( client, repo ):
    """
    THE PARITY ARM. A terse row is documented as a strict SUBSET of the full shape; if the two
    ever disagreed about `project`, a cheap census would return different answers from an
    expensive one and nobody would know which to believe.
    """
    repo.query_tasks.return_value = [ make_item( project="plan" ) ]
    terse = client.get( "/api/tasks", params={ "owner_persona": "k", "terse": "true"  } ).json()[ "tasks" ][ 0 ]
    full  = client.get( "/api/tasks", params={ "owner_persona": "k", "terse": "false" } ).json()[ "tasks" ][ 0 ]
    assert terse[ "project" ] == full[ "project" ] == "plan"


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )


# ---------------------------------------------------------------------------
# row-cap overflow must NAME itself (row a5f4eb3f)
# ---------------------------------------------------------------------------
#
# /api/tasks has TWO truncation modes and only the char-budget one announced itself.
# The row cap is the mode that actually bit: the notifications dashboard polled with
# include_terminal=true, inflating the board to 1,171 rows against the 500 cap — 671
# dropped, no flag, no warning, and newest-first ordering meant the EVICTED rows were
# the OPEN ones the panel exists to display.

def test_row_cap_overflow_emits_a_named_warning( client, repo ):
    """THE REGRESSION. `has_more` alone was ignored by both consumers; a warning names it."""
    repo.query_tasks.return_value = [ make_item() for _ in range( 3 ) ]
    repo.count_tasks.return_value = 10                      # 3 of 10 -> 7 unshown

    body = client.get( "/api/tasks", params={ "owner_persona": "krishna", "limit": 3 } ).json()

    assert body[ "has_more" ] is True
    assert len( body[ "warnings" ] ) == 1
    notice = body[ "warnings" ][ 0 ]
    assert "row-cap truncation" in notice
    assert "3 of 10" in notice and "7 rows" in notice       # the count AND the shortfall
    assert "OLDEST" in notice                               # which rows were evicted


def test_row_cap_overflow_does_NOT_set_truncated( client, repo ):
    """
    `truncated` means "stopped at the CHAR BUDGET" to every existing consumer.
    Overloading it would silently change a live signal's meaning — the same class of
    defect as `count` being read as a total, which this very endpoint already carries.
    """
    repo.query_tasks.return_value = [ make_item() for _ in range( 3 ) ]
    repo.count_tasks.return_value = 10

    body = client.get( "/api/tasks", params={ "owner_persona": "krishna", "limit": 3 } ).json()
    assert body[ "truncated" ] is False


def test_a_COMPLETE_page_warns_about_nothing( client, repo ):
    """
    THE NEGATIVE CONTROL. Without it the warning could fire on every query and the
    test above would still pass — a notice nobody can trust is worse than none.
    """
    repo.query_tasks.return_value = [ make_item() for _ in range( 3 ) ]
    repo.count_tasks.return_value = 3                       # everything matched is shown

    body = client.get( "/api/tasks", params={ "owner_persona": "krishna" } ).json()
    assert body[ "has_more" ] is False
    assert body[ "warnings" ] == [ ]


def test_offset_paging_stops_warning_on_the_LAST_page( client, repo ):
    """The shortfall is computed from offset, not from the page length alone."""
    repo.query_tasks.return_value = [ make_item() for _ in range( 4 ) ]
    repo.count_tasks.return_value = 10

    mid  = client.get( "/api/tasks", params={ "owner_persona": "k", "limit": 4, "offset": 0 } ).json()
    last = client.get( "/api/tasks", params={ "owner_persona": "k", "limit": 4, "offset": 6 } ).json()

    assert any( "row-cap truncation" in w for w in mid[ "warnings" ] )
    assert last[ "warnings" ] == [ ]                        # 6 + 4 == 10, nothing unshown
