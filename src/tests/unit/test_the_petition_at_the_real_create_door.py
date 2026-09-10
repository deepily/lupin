"""
THE PETITION, DRIVEN THROUGH THE REAL CREATE DOOR — row 9c26bf04.

Sibling of `test_the_priority_firewall_at_the_real_http_door.py` and deliberately
built on its harness, because the thing under test is the SEAM between the firewall's
verdict and the router's response — and a seam is only observable at the door. The
firewall's own predicates are already unit-tested next door in
`test_the_p0_petition_routes_and_never_grants.py`; re-asserting them here would be a
second opinion that can drift from the first.

🔴 WHAT THIS FILE EXISTS TO PROVE, IN ONE LINE: the refusal still refuses, and only
its DESTINATION changed. Every negative arm below is a case where the caller must
still eat a flat 403 — those are the arms that would catch `authority` quietly
becoming a grant, which is row b8205986 reopening.

⚠️ THE POSITIVE ARM IS NOT "IT RETURNED 2xx". It is: 201 specifically, the persisted
priority is P1 specifically, and the row landed in the holding area. A test that
accepted any 2xx would pass against the 202 shape this row explicitly rejected —
Tiffany measured that `fetch`'s `response.ok` is true for any 2xx and the browser
store writes optimistic state before the call, so a 202 renders an unanswered
petition as landed.
"""

import json
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cosa.rest import task_approval_settings as approval
from cosa.rest import task_priority_firewall as firewall
from cosa.rest import task_promotion_resolver as promotion_resolver
from cosa.rest import flow_ratio_settings as frs
from cosa.rest import task_store_rules as rules
from cosa.rest.postgres_models import TaskItem
from cosa.rest.routers import tasks
from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt, authenticated_account_email


NOW            = datetime( 2026, 9, 9, 0, 0, tzinfo=timezone.utc )
WORKER_ACTOR   = "john 54250c10"
MANAGER_ACTOR  = "mr radio 81381447"
OPERATOR_EMAIL = "ricardo.felipe.ruiz@gmail.com"


_ITEM_FIELDS = (
    "item_class", "title", "body", "project", "owner_persona", "accountable_manager",
    "created_by", "status", "blocked_by", "next_chase_ts", "gate_class", "priority",
    "source_qid", "correlation_key",
)


def _item( **overrides ):
    """A REAL TaskItem — a MagicMock here serializes to a 500 that reads like a refusal."""
    fields = dict(
        id                  = uuid.uuid4(),
        item_class          = "task",
        title               = "a row somebody is filing on Rick's instruction",
        body                = None,
        project             = "lupin",
        owner_persona       = "mr radio",
        accountable_manager = "mr radio",
        created_by          = MANAGER_ACTOR,
        status              = "not_approved",
        blocked_by          = [ ],
        next_chase_ts       = None,
        gate_class          = "none",
        priority            = "P1",
        source_qid          = None,
        correlation_key     = "epic:authz-and-sandboxing",
        created_ts          = NOW,
        updated_ts          = NOW,
        title_trimmed       = False,
    )
    fields.update( overrides )
    return TaskItem( **fields )


@pytest.fixture
def added():
    """Everything the handler put on the session — the ticket is read from here."""
    return [ ]


@pytest.fixture
def created_items():
    """
    The rows `create_item` actually returned.

    ⚠️ NOT `mock.create_item.spy_return` — that is a pytest-mock attribute and a plain
    MagicMock answers it with another MagicMock rather than an error, so an assertion
    against it compares a UUID to a mock and fails for a reason that has nothing to do
    with the code. Recording the return here is the honest instrument.
    """
    return [ ]


@pytest.fixture
def repo( monkeypatch, added, created_items ):
    fake = MagicMock()
    fake.statuses_for_ids.return_value         = { }
    fake.count_created_and_closed.return_value = { "created": 0, "closed": 0 }

    def _create_item( **kw ):
        item = _item( **{ k: v for k, v in kw.items() if k in _ITEM_FIELDS } )
        created_items.append( item )
        return item

    fake.create_item.side_effect = _create_item

    @contextmanager
    def _fake_get_db():
        session     = MagicMock()
        session.add = added.append
        yield session

    monkeypatch.setattr( tasks, "get_db", _fake_get_db )
    monkeypatch.setattr( tasks, "TaskRepository", lambda session: fake )
    return fake


@pytest.fixture
def resolver_calls( monkeypatch ):
    """
    🔴 THE BACKGROUND TASK IS STUBBED, AND WITHOUT THIS THE SUITE TALKS TO POSTGRES.
    TestClient RUNS background tasks after the response, so an un-stubbed
    `resolve_ticket` would fire the real resolver against a MagicMock session and fail
    somewhere far from the assertion being made.
    """
    calls = [ ]
    monkeypatch.setattr( promotion_resolver, "resolve_ticket",
                         lambda ticket_id: calls.append( ticket_id ) )
    return calls


@pytest.fixture
def settings( tmp_path, monkeypatch ):
    """The approval override file inside tmp_path — the fleet INI is never read."""
    target = tmp_path / "task-approval-settings.json"
    monkeypatch.setattr( approval, "override_path", lambda: str( target ) )
    monkeypatch.setattr( approval, "_cache", { "approvers": None, "enforcement_active": None } )
    monkeypatch.setattr( approval, "_cache_mtime", None )
    target.write_text( json.dumps( {
        "approvers"         : [ "rick" ],
        "enforcement_active": False,
        "approver_accounts" : { OPERATOR_EMAIL: "rick" },
    } ) )
    approval._cache_mtime = None
    return target


@pytest.fixture
def manager_bridge( monkeypatch ):
    """A bridge that says every session is a MANAGER — the petition's positive arms."""
    monkeypatch.setattr( firewall, "caller_is_manager_by_bridge",
                         lambda actor, account_email=None, manager_fn=None: True )


@pytest.fixture
def worker_bridge( monkeypatch ):
    """
    A bridge that says every session is a WORKER.

    Left un-stubbed, the live predicate reads whatever bridges are on this machine — so
    the arm would pass or fail depending on which seats happen to be running, which is
    not a fact about the code.
    """
    monkeypatch.setattr( firewall, "caller_is_manager_by_bridge",
                         lambda actor, account_email=None, manager_fn=None:
                             firewall.caller_is_operator( account_email ) )


def _client( account_email=None ):
    app = FastAPI()
    app.include_router( tasks.router )
    app.dependency_overrides[ require_api_key_or_jwt ]      = lambda: "test-user"
    app.dependency_overrides[ authenticated_account_email ] = lambda: account_email
    return TestClient( app )


def _create( client, priority="P0", authority="user_direct", created_by=MANAGER_ACTOR ):
    return client.post( "/api/tasks", json={
        "item_class"      : "task",
        "title"           : "the sort row Rick ordered out loud",
        "project"         : "lupin",
        "created_by"      : created_by,
        "priority"        : priority,
        "authority"       : authority,
        "correlation_key" : "epic:authz-and-sandboxing",
    } )


def _ticket( added ):
    tickets = [ a for a in added if isinstance( a, tasks.TaskPromotionTicket ) ]
    assert len( tickets ) == 1, f"expected exactly one ticket on the session, got {len( tickets )}"
    return tickets[ 0 ]


# ---------------------------------------------------------------------------
# The isolation control FIRST — a green file must not also be consistent with
# these arms reading the live fleet settings or the live bridge.
# ---------------------------------------------------------------------------

def test_the_isolation_actually_isolates( settings, manager_bridge ):
    # A FROZENSET, not a list — asserting the shape the module actually returns rather
    # than the shape the override file was written in.
    assert approval.get_approvers() == frozenset( { "rick" } )
    assert firewall.caller_is_manager_by_bridge( WORKER_ACTOR ) is True


# ---------------------------------------------------------------------------
# THE NEGATIVES — the refusal still refuses. These are the b8205986 guards.
# ---------------------------------------------------------------------------

def test_a_worker_relaying_an_instruction_is_still_refused_flat(
    settings, repo, worker_bridge, resolver_calls, added
):
    """
    Rick's sentence order is "a worker escalates through their MANAGER, who petitions
    the operator" — so the worker's path is their manager, never this door.
    """
    r = _create( _client(), created_by=WORKER_ACTOR )
    assert r.status_code == 403
    assert added == [ ], "a refused caller must leave NO ticket behind"


def test_a_manager_exercising_its_OWN_judgement_is_still_refused_flat(
    settings, repo, manager_bridge, resolver_calls, added
):
    """
    No `authority="user_direct"` claim ⇒ no relay ⇒ the flat refusal, unchanged. This
    arm proves the petition is opt-in rather than an automatic softening of the
    firewall for anyone who happens to be a manager.
    """
    r = _create( _client(), authority="standing" )
    assert r.status_code == 403
    assert added == [ ]


def test_an_ordinary_priority_mints_no_petition(
    settings, repo, manager_bridge, resolver_calls, added
):
    """
    P1-P4 already have a door — a manager sets them directly — so there is nothing to
    petition for. The create succeeds and no ticket is minted.
    """
    r = _create( _client(), priority="P2" )
    assert r.status_code == 201
    assert added == [ ], "an ordinary P2 create must not mint a petition"
    assert "petition" not in r.json()


# ---------------------------------------------------------------------------
# THE POSITIVE — and it asserts the SHAPE, not merely a 2xx.
# ---------------------------------------------------------------------------

def test_a_manager_relaying_an_instruction_gets_201_and_a_petition(
    settings, repo, manager_bridge, resolver_calls, added
):
    r = _create( _client() )

    # 🔴 201 EXACTLY. `assert r.ok` would pass against the 202 shape this row rejected.
    assert r.status_code == 201, f"expected 201, got {r.status_code}: {r.text}"

    petition = r.json()[ "petition" ]
    assert petition[ "ticket_id" ]
    assert petition[ "minted_at" ]  == "P1"
    assert petition[ "requesting" ] == "P0"


def test_the_row_is_PERSISTED_at_P1_so_the_petition_granted_nothing(
    settings, repo, manager_bridge, resolver_calls
):
    """
    THE INVARIANT, READ OFF THE WRITE ITSELF rather than off the response. The response
    is what the handler chose to say; `create_item`'s kwargs are what actually went to
    the database.
    """
    _create( _client() )

    kwargs = repo.create_item.call_args.kwargs
    assert kwargs[ "priority" ] == "P1", "a petition must never persist P0"
    assert kwargs[ "status" ]   == rules.NOT_APPROVED_STATUS


def test_the_caller_declared_authority_reaches_the_write_unrewritten(
    settings, repo, manager_bridge, resolver_calls
):
    """
    The payload is the caller's evidence of what they SENT. The downgrade rides on a
    local, so the request we adjudicated is still legible as the request that was made.
    """
    _create( _client() )
    assert repo.create_item.call_args.kwargs[ "authority" ] == "user_direct"


# ---------------------------------------------------------------------------
# THE TICKET — what Rick's single keypress will actually apply.
# ---------------------------------------------------------------------------

def test_the_ticket_carries_P0_pinned_and_admits_the_row(
    settings, repo, manager_bridge, resolver_calls, added
):
    """
    One approval RAISES and ADMITS — Rick chose both ("reprioritized and then pushed
    into the live queue"). Both effects must ride on the ticket, or his one keypress
    does half a job.
    """
    _create( _client() )
    ticket = _ticket( added )

    assert ticket.payload[ "priority" ]  == "P0"
    assert ticket.payload[ "to_status" ] == "queued"
    assert ticket.to_status              == "queued"
    assert ticket.state                  == promotion_resolver.TICKET_PENDING


def test_the_ticket_names_the_row_that_was_actually_created(
    settings, repo, manager_bridge, resolver_calls, added, created_items
):
    """
    Minted AFTER create_item and against `item.id` — so there is no window in which
    Rick is asked about a row that does not exist.
    """
    _create( _client() )
    assert _ticket( added ).item_id == created_items[ 0 ].id


def test_the_resolver_is_scheduled_when_a_petition_is_minted(
    settings, repo, manager_bridge, resolver_calls
):
    """A ticket nobody resolves is an ask that never reaches Rick."""
    _create( _client() )
    assert len( resolver_calls ) == 1


def test_an_ordinary_create_schedules_no_resolver_work(
    settings, repo, manager_bridge, resolver_calls
):
    """
    The POSITIVE CONTROL for the arm above. Without it, `len(...) == 1` is equally
    consistent with the handler scheduling a resolver on every single create.
    """
    _create( _client(), priority="P3" )
    assert resolver_calls == [ ]


# ---------------------------------------------------------------------------
# THE RATIO GATE — a petition buys no exemption, and that is deliberate.
# ---------------------------------------------------------------------------

def test_a_petition_does_NOT_inherit_the_P0_ratio_exemption(
    settings, repo, manager_bridge, resolver_calls, monkeypatch, added
):
    """
    🔴 THE ANTI-GRANT ARM. P0 is exempt from the throughput gate; a petition is a P0
    that has been REQUESTED and not granted. If the gate read the REQUESTED priority,
    any caller could skip it by declaring authority="user_direct" — a caller-declared
    string granting something, which is the one thing this mechanism must never be.

    The refusal the caller gets is about THROUGHPUT (422), not authority (403), and
    that difference is the point: the two gates are independent.
    """
    monkeypatch.setattr( frs, "get_enforcement_active", lambda: True )
    monkeypatch.setattr( frs, "get_allow_below",        lambda: 1.30 )
    monkeypatch.setattr( frs, "get_window_hours",       lambda: 24 )
    repo.count_created_and_closed.return_value = { "created": 257, "closed": 196 }

    r = _create( _client() )
    assert r.status_code == 422, f"expected the throughput refusal, got {r.status_code}"
    assert added == [ ], "a create the ratio gate refused must mint no ticket"


def test_the_ratio_gate_POSITIVE_control_a_real_P0_is_still_exempt(
    settings, repo, manager_bridge, resolver_calls, monkeypatch
):
    """
    Proves the instrument above can find something. With the SAME counts, the
    operator's own P0 — never refused by the firewall, so never a petition — sails
    through the exemption. Without this arm the 422 above is equally consistent with
    the gate refusing everything put in front of it.
    """
    monkeypatch.setattr( frs, "get_enforcement_active", lambda: True )
    monkeypatch.setattr( frs, "get_allow_below",        lambda: 1.30 )
    monkeypatch.setattr( frs, "get_window_hours",       lambda: 24 )
    repo.count_created_and_closed.return_value = { "created": 257, "closed": 196 }

    r = _create( _client( OPERATOR_EMAIL ), authority="standing" )
    assert r.status_code == 201, f"the operator's own P0 must stay exempt, got {r.text}"


# ---------------------------------------------------------------------------
# THE REFUSAL AND THE LOG MUST TELL THE TRUTH ABOUT A REFUSED PETITION — row d2b1b59a,
# Findings 4 and 4b, measured live 2026-09-10 21:31Z.
# ---------------------------------------------------------------------------

def _ratio_gate_shut( monkeypatch, repo ):
    """The same counts the two ratio arms above use — 257/196 against 1.30 refuses."""
    monkeypatch.setattr( frs, "get_enforcement_active", lambda: True )
    monkeypatch.setattr( frs, "get_allow_below",        lambda: 1.30 )
    monkeypatch.setattr( frs, "get_window_hours",       lambda: 24 )
    repo.count_created_and_closed.return_value = { "created": 257, "closed": 196 }


def test_a_refused_petition_is_not_told_a_P0_is_exempt_at_the_door(
    settings, repo, manager_bridge, resolver_calls, monkeypatch
):
    """
    Reads the 422 DETAIL, which the anti-grant arm above does not: the status was right
    all along, and the sentence under it told a manager who had just asked for P0 that
    P0 is exempt.
    """
    _ratio_gate_shut( monkeypatch, repo )

    r = _create( _client() )
    assert r.status_code == 422, f"expected the throughput refusal, got {r.status_code}"
    detail = r.json()[ "detail" ]
    assert "A P0 is exempt" not in detail
    assert "judged it at P1" in detail


def test_CONTROL_an_ordinary_create_the_gate_refuses_still_hears_about_the_P0_exemption(
    settings, repo, manager_bridge, resolver_calls, monkeypatch
):
    """Without this, the arm above is equally consistent with the router dropping the hint for everyone."""
    _ratio_gate_shut( monkeypatch, repo )

    r = _create( _client(), priority="P2", authority="standing" )
    assert r.status_code == 422, f"expected the throughput refusal, got {r.status_code}"
    detail = r.json()[ "detail" ]
    assert "(A P0 is exempt if this genuinely cannot wait.)" in detail
    assert "judged it at P1" not in detail


def test_a_petition_the_ratio_gate_refuses_logs_no_petition_opened(
    settings, repo, manager_bridge, resolver_calls, monkeypatch, capsys
):
    """4b: the line used to print before the gate, logging a petition that never existed."""
    _ratio_gate_shut( monkeypatch, repo )

    r = _create( _client() )
    assert r.status_code == 422
    assert "P0 PETITION opened" not in capsys.readouterr().out


def test_CONTROL_a_minted_petition_logs_that_it_opened_against_the_real_row(
    settings, repo, manager_bridge, resolver_calls, created_items, capsys
):
    """Without this, the arm above is equally consistent with the line having been deleted outright."""
    r = _create( _client() )
    assert r.status_code == 201
    out = capsys.readouterr().out
    assert "P0 PETITION opened" in out
    assert str( created_items[ 0 ].id ) in out, "the log line must name the row it opened"
