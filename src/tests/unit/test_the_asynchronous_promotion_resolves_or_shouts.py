#!/usr/bin/env python3
"""
THE ASYNCHRONOUS PROMOTION PATH — it resolves, or it shouts. It never goes quiet.

Row `3493ae9b`. Design: `src/rnd/v0.2.1/2026.09.06-asynchronous-promotion-approval-and-
its-observable-resolution.md`. Mr. Radio's conditional ruling: option (b) ships ONLY with
a resolution path the caller can observe.

🔴 WHAT THIS FILE IS ACTUALLY FOR, AND IT IS NOT "the 202 works". The synchronous door
holds a row lock for the whole ask, so the row cannot move between the decision and the
apply. Going asynchronous GIVES THAT UP. Every arm below exists to prove the guarantee
was bought back rather than lost:

    · phase 2 holds no DB connection               — else the waiting merely moved
    · phase 3 re-validates under a fresh lock      — else a stale intent lands on a moved row
    · a non-pending ticket is left alone           — else belt and suspenders both apply it
    · past the deadline shouts, inside it does not — else the alarm means nothing

⚠️ THE LAST PAIR IS TWO ARMS ON PURPOSE. "The alarm fires" and "the alarm fires WHEN IT
SHOULD" are different claims, and an alarm that shouted on every promotion would satisfy
the first. The in-flight ask is the COMMON case and it is the one that must stay silent.

🔴 WHY THE ENDPOINT ARMS DRIVE THE ASSEMBLED APP. A resolver test proves the resolver
resolves. It cannot prove the handler ever HANDS OFF to it — a component can be complete,
correct, fully covered and never reached. `test_the_handler_actually_hands_the_ask_off`
is the arm that catches a deleted `add_task`, and nothing else here would.

🔴 WHY `JWT_SECRET_KEY` IS SET AT MODULE SCOPE. `jwt_service.py` raises AT IMPORT when it
is unset, and the repo-root `.env` that supplies it on this host is gitignored — present
in the main checkout, absent from every worktree. A fixture runs at execution time, AFTER
the collection-time import that needs it. The value is a throwaway.

VENUE: `:7999`. No persistent-state mutation — the session is an in-memory fake and the
ask is injected — well under two minutes, no monopoly.
"""
import json
import os
import sys
import uuid
from contextlib import contextmanager
from pathlib    import Path
from datetime   import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

# MUST precede the `lupin_app.main` import below — see the module docstring.
os.environ.setdefault( "JWT_SECRET_KEY", "test-only-not-a-real-secret" )

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from fastapi.testclient import TestClient

from cosa.rest import task_approval_settings   as approval
from cosa.rest import task_promotion_gate      as gate
from cosa.rest import task_promotion_resolver  as resolver
from cosa.rest.postgres_models import TaskItem, TaskPromotionTicket
from cosa.rest.routers import tasks
from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt

# 🔨 THE APPROVAL GATE IS SATISFIED HERE, NOT STOOD DOWN — and it is NOT this file's
# subject (row b8205986, 2026-09-07).
#
# Rick closed the actor door by keypress ~21:47 EDT: a typed approver name confers
# nothing, and an approver is recognized by the LOGIN ACCOUNT on a validated token.
# Every test in this file promotes out of the holding area, so the approval gate now
# refuses them all with 403 BEFORE the promotion gate — the thing they exist to test —
# is ever reached. That is the ruling working; it just means the fixture modelled a
# caller who can no longer do the setup step.
#
# ⇒ The fixture logs in as an approver. SATISFIED rather than disabled, deliberately:
# stubbing the approval gate out would let a real regression in it pass unnoticed here,
# while a real login exercises the same door every other caller uses.
APPROVER_EMAIL = "maria@example.com"


TRANSITION_PATH = "/api/tasks/{task_id}/transition"
NOW             = datetime( 2026, 9, 6, 12, 0, tzinfo=timezone.utc )
MANAGER         = "mr radio 21dff055"


# ═══════════════════════════════════════════════════════════════════════════════════
# Fakes that HONOUR their inputs
#
# ⚠️ A fake that ignores its input answers the same however the code behaves, and every
# assertion written over its output inherits that. `_FakeSession.flush` assigns ids
# because the handler hands out `ticket.id` immediately after flushing — a fake that
# skipped it would let the endpoint return a null id and still pass every arm below.
# ═══════════════════════════════════════════════════════════════════════════════════

class _FakeSession:
    def __init__( self, tickets=None, items=None ):
        self.tickets = { t.id: t for t in ( tickets or [] ) }
        self.items   = { i.id: i for i in ( items   or [] ) }
        self.added   = []
        # Phase 3 refuses a session that already holds objects — see `_apply_resolution`.
        # A fake without this attribute could not express the failure mode at all, so the
        # guard would be untestable and every arm over it unfalsifiable.
        self.identity_map = {}

    def add( self, obj ):
        self.added.append( obj )

    def flush( self ):
        for obj in self.added:
            if getattr( obj, "id", None ) is None: obj.id = uuid.uuid4()
            if isinstance( obj, TaskPromotionTicket ): self.tickets[ obj.id ] = obj

    def get( self, model, pk, with_for_update=False ):
        if model is TaskPromotionTicket: return self.tickets.get( pk )
        return self.items.get( pk )

    def query( self, model ):
        return _FakeQuery( list( self.tickets.values() ) )


class _FakeQuery:
    """
    ⚠️ IT DOES NOT INTERPRET THE FILTERS, AND THAT IS DELIBERATE RATHER THAN LAZY.
    Re-implementing SQLAlchemy's expression semantics here would mean the test agreed
    with my model of the ORM rather than with the ORM. So this hands back EVERY ticket,
    and the arms assert on which rows the resolver then TOUCHES — a resolver that
    dropped its `state == pending` filter is caught by the untouched-row arms, not by
    this fake.
    """
    def __init__( self, rows ):      self.rows = rows
    def all( self ):                 return list( self.rows )
    def filter( self, *criteria ):   return self
    def order_by( self, *criteria ): return self
    def limit( self, n ):            return _FakeQuery( self.rows[ :n ] )


def _db_fn_for( session, ledger=None ):
    """A `db_fn` that optionally records how many connections are open at once."""
    @contextmanager
    def _fn():
        if ledger is not None: ledger.append( "open" )
        try:     yield session
        finally:
            if ledger is not None: ledger.append( "close" )
    return _fn


@contextmanager
def _repo_seam( repo ):
    """Swap the resolver's TaskRepository for the duration of one call."""
    import cosa.rest.task_promotion_resolver as mod
    original           = mod.TaskRepository
    mod.TaskRepository = lambda session: repo
    try:     yield
    finally: mod.TaskRepository = original


def _item( **overrides ):
    fields = dict(
        id                  = uuid.uuid4(),
        item_class          = "task",
        title               = "a row waiting in the holding area",
        body                = None,
        project             = "lupin",
        owner_persona       = "pocholo",
        accountable_manager = "mr radio",
        created_by          = MANAGER,
        status              = approval.NOT_APPROVED_STATUS,
        priority            = "P2",
        urgency             = "normal",
        created_ts          = NOW,
        updated_ts          = NOW,
    )
    fields.update( overrides )
    return TaskItem( **fields )


def _intent():
    return resolver.TransitionIntent(
        to_status="queued", actor=MANAGER, recorded_actor=MANAGER,
        authority="standing", receipt_refs=None, blocked_by=None,
        reason=None, park_reason=None, next_chase_ts=None,
        title="a row waiting in the holding area", session_id="21dff055",
    )


def _ticket( item_id=None, state=resolver.TICKET_PENDING, resolves_by=None ):
    return TaskPromotionTicket(
        id           = uuid.uuid4(),
        item_id      = item_id or uuid.uuid4(),
        to_status    = "queued",
        requested_by = MANAGER,
        requested_at = NOW,
        resolves_by  = resolves_by or ( NOW + timedelta( seconds=180 ) ),
        payload      = _intent().as_payload(),
        state        = state,
    )


# 🔴 A DEFAULT ARGUMENT BINDS AT IMPORT AND NEVER REBINDS — the first cut of this file
# got four wrong answers from exactly this. `promotion_is_asynchronous( requested,
# enabled_fn=get_asynchronous_enabled )` captured the function object when the module was
# read, so `monkeypatch.setattr( gate, "get_asynchronous_enabled", … )` changed a name
# nothing looks at again, and the endpoint quietly took the SYNCHRONOUS path while the
# test believed it had opened both gates. It reported 200, which reads as "the fork is
# broken" rather than "the test never reached it".
#
# ⇒ SO PATCH WHAT IS RESOLVED AT CALL TIME, WHICH IS THE MODULE GLOBAL THE FUNCTION BODY
# READS. `_ini_value` is looked up inside `get_asynchronous_enabled` on every call, so
# faking it leaves BOTH real gates running — the real `promotion_is_asynchronous`, the
# real `get_asynchronous_enabled`, and only the INI read replaced. Stubbing the decision
# function itself would have been easier and would have measured the stub.
def _operator_flag( monkeypatch, on ):
    """Set the INI value the real `get_asynchronous_enabled` reads, not the function."""
    real = gate._ini_value
    def _fake( key, return_type, fallback ):
        if key == gate.INI_KEY_ASYNCHRONOUS: return "true" if on else "false"
        return real( key, return_type, fallback )
    monkeypatch.setattr( gate, "_ini_value", _fake )


def _refuse_the_manager( monkeypatch, refusal="not a manager" ):
    """
    Refuse at `manager_refusal`, which `promotion_precheck` resolves from module globals.

    ⚠️ NOT at `is_manager_figure` — that is bound as a default argument two frames down
    and patching it does nothing, for the reason in the block above.
    """
    monkeypatch.setattr( gate, "manager_refusal", lambda *a, **k: refusal )


def _allowed(): return gate.PromotionApproval( allowed=True, approval_source=gate.APPROVAL_KEYPRESS )
def _refused(): return gate.PromotionApproval( allowed=False, refusal="Rick answered no." )


def _resolve( ticket, session, repo, approval_obj, ledger=None, ask=None ):
    """Drive the real `resolve_ticket` with its seams injected."""
    with _repo_seam( repo ):
        return resolver.resolve_ticket(
            ticket.id,
            db_fn        = _db_fn_for( session, ledger=ledger ),
            approval_fn  = ask if ask is not None else ( lambda **k: approval_obj ),
            serialize_fn = lambda item, event: { "item": "serialized", "event": "serialized" },
            now_fn       = lambda: NOW,
        )


# ═══════════════════════════════════════════════════════════════════════════════════
# 1 · THE FORK, DRIVEN THROUGH THE ASSEMBLED APP
# ═══════════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def assembled_app():
    import lupin_app.main as main
    app   = main.app
    paths = { getattr( route, "path", None ) for route in app.routes }
    assert TRANSITION_PATH in paths, (
        f"the assembled app has no {TRANSITION_PATH} route — {len( app.routes )} routes "
        f"were mounted. This guard cannot speak to a door that is not there."
    )
    return app


@pytest.fixture
def wired( monkeypatch ):
    """
    The real endpoint over a fake session, with the ask and the handoff both recorded.

    ⚠️ `promotion_is_asynchronous` is NOT stubbed. The two real gates decide, so an arm
    that flips the operator flag is exercising the real decision function rather than a
    test double that agrees with it.
    """
    item    = _item()
    session = _FakeSession( items=[ item ] )
    repo    = MagicMock()
    repo.get_by_id_for_update.return_value = item
    handed  = []

    monkeypatch.setattr( tasks, "get_db", _db_fn_for( session ) )
    monkeypatch.setattr( tasks, "TaskRepository", lambda s: repo )
    monkeypatch.setattr( tasks.promotion_resolver, "resolve_ticket",
                         lambda ticket_id: handed.append( ticket_id ) )
    monkeypatch.setattr( approval, "get_enforcement_active", lambda: True )
    # AND THE MAP THAT MAKES THE FIXTURE'S LOGIN AN APPROVER (row b8205986). The account
    # seam supplies WHO the caller is; this supplies whether that account is an
    # approver. Both halves, or the gate sees a real login belonging to nobody and
    # refuses -- correct behaviour, and it would still stop this file at its setup step
    # before the async promotion it exists to test is ever reached.
    monkeypatch.setattr( approval, "get_approver_accounts", lambda: { APPROVER_EMAIL: "maria" } )
    monkeypatch.setattr( gate, "manager_refusal", lambda *a, **k: None )
    monkeypatch.setattr( gate, "approval_for_promotion", lambda **k: _allowed() )
    monkeypatch.setattr( gate, "approval_from_the_ask",  lambda **k: _allowed() )
    return { "item": item, "session": session, "repo": repo, "handed": handed }


@pytest.fixture
def client( assembled_app, wired ):
    assembled_app.dependency_overrides[ require_api_key_or_jwt ] = lambda: "test-user"
    # THE ACCOUNT SEAM (row b8205986). Without it the caller has no login, the approval
    # gate refuses, and this file's real subject is never reached. See APPROVER_EMAIL.
    _account_seam = getattr( tasks, "authenticated_account_email", None )
    assert _account_seam is not None, (
        "the transition door no longer exposes `authenticated_account_email` — this "
        "fixture models a caller who cannot be authorized at all"
    )
    assembled_app.dependency_overrides[ _account_seam ] = lambda: APPROVER_EMAIL

    yield TestClient( assembled_app, raise_server_exceptions=False ), wired
    assembled_app.dependency_overrides.pop( require_api_key_or_jwt, None )


def _post( c, item, **extras ):
    body = { "to_status": "queued", "actor": MANAGER, "authority": "standing" }
    body.update( extras )
    return c.post( f"/api/tasks/{item.id}/transition", json=body )


def test_the_operator_flag_OFF_keeps_a_real_boolean_opt_in_synchronous( client, monkeypatch ):
    """
    🔴 THE FAIL-CLOSED ARM. Both gates are required, and this proves the FIRST one is
    load-bearing rather than decorative: a caller sending a genuine `true` while the
    operator flag is off must still get today's behaviour and NO ticket.
    """
    c, w = client
    _operator_flag( monkeypatch, on=False )

    response = _post( c, w[ "item" ], asynchronous=True )

    assert response.status_code != 202, "the operator flag is OFF and a 202 was returned anyway"
    assert w[ "session" ].added == [], "a ticket was minted on the synchronous path"
    assert w[ "handed" ]        == [], "an ask was handed off on the synchronous path"


def test_the_operator_flag_ON_without_the_caller_saying_so_stays_synchronous( client, monkeypatch ):
    """
    🔴 THE ARM THAT PROTECTS EVERY BROWSER. Tiffany 💍's finding: a 202 is read as
    success by all three browser call sites, and `TaskListStore` has already written an
    optimistic "approved" row before the call. The operator flag alone must never hand
    one out — the caller's opt-in is what keeps the exposed browser surface at ZERO.
    """
    c, w = client
    _operator_flag( monkeypatch, on=True )

    response = _post( c, w[ "item" ] )          # no `asynchronous` field at all

    assert response.status_code != 202, "an un-opted-in caller was handed a 202"
    assert w[ "session" ].added == [], "a ticket was minted for a caller that never asked"


def test_both_gates_open_returns_202_with_a_ticket_the_caller_can_come_back_with( client, monkeypatch ):
    """
    THE POSITIVE CONTROL. Without it, every refusal above would be satisfied by an
    endpoint that can never return 202 at all.
    """
    c, w = client
    _operator_flag( monkeypatch, on=True )

    response = _post( c, w[ "item" ], asynchronous=True )

    assert response.status_code == 202, f"expected 202, got {response.status_code}: {response.text}"
    body = response.json()
    assert body[ "status" ]     == "awaiting_human_approval"
    assert body[ "check_with" ] == "task_promotion_status"
    assert uuid.UUID( body[ "ticket_id" ] ), "the 202 carried no usable ticket id"
    assert body[ "resolves_by" ], "the 202 did not say when this stops being in-flight"


def test_the_handler_actually_hands_the_ask_off( client, monkeypatch ):
    """
    🔴 THE IMPLEMENTED-BUT-NOT-INSTALLED ARM, AND NOTHING ELSE HERE CATCHES IT. Delete
    the `background_tasks.add_task` line and every other arm in this file still passes:
    the 202 is returned, the ticket is minted, the resolver's own tests are green — and
    no ask ever fires, so the ticket sits until the sweeper calls it an orphan. A
    promotion that silently never asks Rick is the exact defect the synchronous design
    was built to make impossible.
    """
    c, w = client
    _operator_flag( monkeypatch, on=True )

    body = _post( c, w[ "item" ], asynchronous=True ).json()

    assert w[ "handed" ] == [ uuid.UUID( body[ "ticket_id" ] ) ], (
        f"the handler minted ticket {body['ticket_id']} and handed off {w['handed']} — "
        f"the ask was never scheduled, so nothing will ever resolve this ticket."
    )


def test_the_opt_in_on_a_NON_promotion_row_is_INERT( client, monkeypatch ):
    """
    🔴 THE ARM THAT MAKES OPTING IN BY DEFAULT SAFE (row 8ed76594). The MCP verb now sends
    `asynchronous: true` on EVERY transition, not only on promotions, so the claim it rests
    on has to be measured rather than argued: off the promotion path the field is one JSON
    key the handler never consults.

    The row here is already `queued`, so the promotion branch's status pair does not match
    and the fork is never reached. Both gates are open and the caller sent a real boolean —
    every condition for a 202 EXCEPT being a promotion.

    ⚠️ ITS POSITIVE CONTROL IS `test_both_gates_open_returns_202_with_a_ticket_the_caller_
    can_come_back_with`, which is the byte-identical request against a `not_approved` row
    and DOES get the 202. Without that pairing this arm would be satisfied by an endpoint
    that can never return 202 at all.
    """
    c, w = client
    _operator_flag( monkeypatch, on=True )

    already_admitted = _item( status="queued" )
    w[ "repo" ].get_by_id_for_update.return_value = already_admitted

    response = _post( c, already_admitted, asynchronous=True )

    assert response.status_code != 202, (
        f"a row already past the holding area was handed a {response.status_code} — the "
        f"opt-in is reaching transitions that have no human to wait for" )
    assert w[ "session" ].added == [], "a ticket was minted for a non-promotion transition"
    assert w[ "handed" ]        == [], "an ask was handed off for a non-promotion transition"


def test_a_refused_caller_gets_403_and_NO_orphan_ticket_is_minted( client, monkeypatch ):
    """
    A ticket is a promise that an answer is coming. Minting one for a caller who was
    refused would create an orphan on purpose — pending forever, then swept as a stalled
    ask that never existed, firing an urgent notification at a human for nothing.
    """
    c, w = client
    _operator_flag( monkeypatch, on=True )
    _refuse_the_manager( monkeypatch )

    response = _post( c, w[ "item" ], asynchronous=True )

    assert response.status_code == 403, f"a non-manager got {response.status_code}"
    assert w[ "session" ].added == [], "a refused promotion minted a ticket"
    assert w[ "handed" ]        == [], "a refused promotion handed off an ask"


# ═══════════════════════════════════════════════════════════════════════════════════
# 2 · THE RESOLVER — four outcomes, and the lock it gave up
# ═══════════════════════════════════════════════════════════════════════════════════

def test_an_approved_ticket_applies_the_transition_and_stores_the_answer():
    """
    `response_body` is serialized INSIDE the transaction that wrote it (design §5.4.1).
    A poll re-reading the row would get a moved `updated_ts` and an event looked up
    rather than handed over.
    """
    item    = _item()
    ticket  = _ticket( item_id=item.id )
    session = _FakeSession( tickets=[ ticket ], items=[ item ] )
    repo    = MagicMock()
    repo.get_by_id_for_update.return_value = item

    state = _resolve( ticket, session, repo, _allowed() )

    assert state                == resolver.TICKET_APPROVED
    assert ticket.state         == resolver.TICKET_APPROVED
    assert ticket.response_body == { "item": "serialized", "event": "serialized" }
    assert ticket.resolved_at   is not None, "the table's own CHECK requires this"
    assert repo.apply_transition.called, "the ticket says approved and the row never moved"


def test_a_refused_ticket_records_the_refusal_and_does_not_move_the_row():
    item    = _item()
    ticket  = _ticket( item_id=item.id )
    session = _FakeSession( tickets=[ ticket ], items=[ item ] )
    repo    = MagicMock()

    state = _resolve( ticket, session, repo, _refused() )

    assert state          == resolver.TICKET_REFUSED
    assert ticket.refusal == "Rick answered no.", "the CHECK requires a refused ticket to say why"
    assert not repo.apply_transition.called, "a refusal moved the row anyway"


def test_a_row_that_moved_under_the_ask_is_SUPERSEDED_not_refused():
    """
    🔴 THE ARM THAT PROVES THE LOCK WAS BOUGHT BACK. The synchronous door holds the row
    lock across the ask so this cannot happen; the asynchronous one lets it go and must
    therefore re-validate. `superseded` rather than `refused` is the whole value: a
    refused ticket says Rick said no, a superseded one says the answer was fine and the
    WORLD moved — the only reading that sends a reader to look at what else touched the
    row.
    """
    item    = _item( status="done" )         # went terminal while Rick was thinking
    ticket  = _ticket( item_id=item.id )
    session = _FakeSession( tickets=[ ticket ], items=[ item ] )
    repo    = MagicMock()
    repo.get_by_id_for_update.return_value = item

    state = _resolve( ticket, session, repo, _allowed() )

    assert state == resolver.TICKET_SUPERSEDED, (
        "a transition that is no longer legal was applied to a moved row — the guarantee "
        "the row lock used to provide was given up and never bought back"
    )
    assert not repo.apply_transition.called
    assert "done" in ( ticket.refusal or "" ), "the ticket does not say what the row became"


def test_an_approved_promotion_whose_row_was_DELETED_is_superseded_too():
    """Rick said yes to something that no longer exists. Not a refusal."""
    ticket  = _ticket()                       # its item is not in the session
    session = _FakeSession( tickets=[ ticket ] )
    repo    = MagicMock()
    repo.get_by_id_for_update.return_value = None

    state = _resolve( ticket, session, repo, _allowed() )

    assert state == resolver.TICKET_SUPERSEDED
    assert not repo.apply_transition.called


def test_a_ticket_that_is_already_resolved_is_left_alone_and_no_ask_fires():
    """
    🔴 THIS IS WHAT MAKES BELT AND SUSPENDERS SAFE. The worker and the sweeper both
    refuse a non-pending ticket under its own lock, so whoever arrives first applies the
    transition and the other finds it applied. Without this, both apply.
    """
    ticket  = _ticket( state=resolver.TICKET_APPROVED )
    session = _FakeSession( tickets=[ ticket ] )
    asked   = []

    state = resolver.resolve_ticket(
        ticket.id,
        db_fn       = _db_fn_for( session ),
        approval_fn = lambda **k: asked.append( 1 ) or _allowed(),
        now_fn      = lambda: NOW,
    )

    assert state == resolver.TICKET_APPROVED
    assert asked == [], "a settled ticket put a second question in front of Rick"


def test_a_missing_ticket_returns_None_rather_than_a_silent_success():
    session = _FakeSession()
    got = resolver.resolve_ticket(
        uuid.uuid4(), db_fn=_db_fn_for( session ),
        approval_fn=lambda **k: _allowed(), now_fn=lambda: NOW,
    )
    assert got is None


def test_an_apply_that_blows_up_STALLS_the_ticket_rather_than_leaving_it_pending():
    """
    🔴 DECLINE RATHER THAN NO-OP. The transaction rolls back, so without this the ticket
    stays `pending` and looks exactly like a healthy in-flight ask — and the sweeper
    would call it an orphan minutes later with the actual exception long gone.
    """
    item    = _item()
    ticket  = _ticket( item_id=item.id )
    session = _FakeSession( tickets=[ ticket ], items=[ item ] )
    repo    = MagicMock()
    repo.get_by_id_for_update.return_value = item
    repo.apply_transition.side_effect = RuntimeError( "the ledger refused the write" )

    with _repo_seam( repo ):
        state = resolver.resolve_ticket(
            ticket.id,
            db_fn        = _db_fn_for( session ),
            approval_fn  = lambda **k: _allowed(),
            serialize_fn = lambda i, e: {},
            now_fn       = lambda: NOW,
            alarm_fn     = lambda *a, **k: None,
        )

    assert state        == resolver.TICKET_STALLED
    assert ticket.state == resolver.TICKET_STALLED
    assert "the ledger refused the write" in ( ticket.refusal or "" ), (
        "the ticket was stalled without naming what went wrong, so the caller polling it "
        "learns only that it died"
    )


def test_the_ask_runs_with_NO_database_connection_open():
    """
    🔴 THE ARM THE WHOLE ROW EXISTS FOR. The synchronous door holds a threadpool worker
    AND a pooled connection AND a `SELECT … FOR UPDATE` row lock for the entire ask. If
    the resolver kept a session open across phase 2 it would have moved the caller's wait
    and kept every bit of the pool cost — and EVERY OTHER ARM IN THIS FILE WOULD STILL
    PASS, because the outcome would be identical.

    The ledger records open/close, so an ask firing between an open and its close is
    caught by construction rather than by reading the source.
    """
    item    = _item()
    ticket  = _ticket( item_id=item.id )
    session = _FakeSession( tickets=[ ticket ], items=[ item ] )
    repo    = MagicMock()
    repo.get_by_id_for_update.return_value = item
    ledger  = []
    seen    = {}

    def _ask( **kwargs ):
        seen[ "open_connections" ] = ledger.count( "open" ) - ledger.count( "close" )
        return _allowed()

    _resolve( ticket, session, repo, None, ledger=ledger, ask=_ask )

    assert seen[ "open_connections" ] == 0, (
        f"{seen['open_connections']} database connection(s) were open while Rick was "
        f"being asked. The 202 would remove the caller's wait and keep the pool cost — "
        f"the defect this row was opened to fix, in a smaller size."
    )


# ── TIFFANY 💍'S POINT 3 — "does that prove it, or did my fake count to zero?" ──────
#
# MEASURED, both directions, before this arm was written:
#   · hold a connection through `db_fn` across the ask -> the arm above reddens, and it
#     is the ONLY test in this file that does (1 failed, 44 passed). So it is genuinely
#     discriminating and NOT merely counting a fake to zero.
#   · hold one that BYPASSES `db_fn` -> all 45 pass. It observes ONE seam.
#
# ⚠️ AND THE FIRST ATTEMPT AT THAT MEASUREMENT LIED, WHICH IS WHY THIS COMMENT EXISTS.
# `_held = db_fn().__enter__()` SURVIVED — and it survived because the orphaned context
# manager was refcount-collected the instant the statement ended, running its own
# `finally` and logging the close. The mutation repaired its own damage, and it read as
# "the arm is blind". Binding the manager (`_cm = db_fn(); _cm.__enter__()`) is what
# makes the connection actually stay open.
#
# ⇒ So her instinct was right and the limit is NARROWER than she feared: the ledger is
# honest about the seam it watches, and blind to everything that goes around it. This
# arm closes that by watching the CHOKEPOINT instead of the seam.

def test_the_ask_opens_no_session_by_ANY_path_not_only_the_INJECTED_seam( monkeypatch ):
    """
    Every real session in this codebase comes from one factory — `database.get_db` is
    literally `session = SessionLocal()` — so counting that factory's calls during the ask
    catches a connection opened by a path the injected `db_fn` never sees.

    ⚠️ THIS ARM IS WORTHLESS WITHOUT THE POSITIVE CONTROL BELOW IT. Nothing in this file
    calls `SessionLocal` at all, so a counter that never fired for the WRONG reason would
    read exactly like one that never fired for the right one — an empty result and a real
    one printing the same thing.
    """
    import cosa.rest.db.database as database

    calls = []
    monkeypatch.setattr( database, "SessionLocal", lambda *a, **k: calls.append( "opened" ) )

    item    = _item()
    ticket  = _ticket( item_id=item.id )
    session = _FakeSession( tickets=[ ticket ], items=[ item ] )
    repo    = MagicMock()
    repo.get_by_id_for_update.return_value = item
    seen    = {}

    def _ask( **kwargs ):
        seen[ "factory_calls_during_the_ask" ] = len( calls )
        return _allowed()

    _resolve( ticket, session, repo, None, ask=_ask )

    assert seen[ "factory_calls_during_the_ask" ] == 0, (
        f"the session factory was called {seen['factory_calls_during_the_ask']} time(s) "
        f"before Rick was asked, by a path the db_fn ledger cannot see"
    )


def test_the_session_factory_counter_ACTUALLY_SEES_A_SESSION_being_opened( monkeypatch ):
    """
    POSITIVE CONTROL for the arm above, and the reason it is a separate test rather than
    a second assertion inside it: an assertion added behind a currently-passing one is
    reached, but an assertion added behind a FAILING one is carried and never executed,
    and the failing set cannot tell the two apart.
    """
    import cosa.rest.db.database as database

    calls = []
    monkeypatch.setattr( database, "SessionLocal", lambda *a, **k: calls.append( "opened" ) )

    assert len( calls ) == 0
    database.SessionLocal()
    assert len( calls ) == 1, "the counter cannot see a session being opened at all"


# ═══════════════════════════════════════════════════════════════════════════════════
# 3 · THE ALARM — both arms, because "it fires" is not "it fires when it should"
# ═══════════════════════════════════════════════════════════════════════════════════

def test_a_ticket_past_its_deadline_is_stalled_and_SHOUTS():
    overdue = _ticket( resolves_by=NOW - timedelta( seconds=1 ) )
    session = _FakeSession( tickets=[ overdue ] )
    alarms  = []

    stalled = resolver.sweep_stalled_tickets(
        db_fn=_db_fn_for( session ), now_fn=lambda: NOW,
        alarm_fn=lambda *a, **k: alarms.append( a ),
    )

    assert stalled == [ overdue.id ]
    assert overdue.state       == resolver.TICKET_STALLED
    assert overdue.resolved_at is not None, "the table's own CHECK requires this"
    assert len( alarms ) == 1, (
        "a promotion ask died and nothing was pushed at a human. Mr. Radio's measurement "
        "on this row: three rows past their chase times rejoined the owed count silently "
        "and nothing fired at him. A state that expires into a list is one nobody reads."
    )


def test_a_ticket_INSIDE_its_deadline_is_untouched_and_SILENT():
    """
    🔴 THE DISCRIMINATING HALF. An alarm that shouted on every promotion would satisfy
    the arm above and be worthless — the in-flight ask is the COMMON case. This is what
    separates "the alarm fires" from "the alarm fires when it should".
    """
    live    = _ticket( resolves_by=NOW + timedelta( seconds=120 ) )
    session = _FakeSession( tickets=[ live ] )
    alarms  = []

    stalled = resolver.sweep_stalled_tickets(
        db_fn=_db_fn_for( session ), now_fn=lambda: NOW,
        alarm_fn=lambda *a, **k: alarms.append( a ),
    )

    assert stalled == [], "an ask still inside its deadline was declared an orphan"
    assert live.state == resolver.TICKET_PENDING
    assert alarms == [], "an urgent notification fired at a human about a healthy ask"


def test_the_sweeper_leaves_an_already_resolved_ticket_alone():
    """
    The idempotency half, from the sweeper's side. It runs BESIDE a live worker, so an
    overdue-LOOKING ticket the worker has just settled must not be re-opened and must
    not shout.
    """
    done    = _ticket( state=resolver.TICKET_APPROVED, resolves_by=NOW - timedelta( seconds=1 ) )
    session = _FakeSession( tickets=[ done ] )
    alarms  = []

    stalled = resolver.sweep_stalled_tickets(
        db_fn=_db_fn_for( session ), now_fn=lambda: NOW,
        alarm_fn=lambda *a, **k: alarms.append( a ),
    )

    assert stalled == []
    assert done.state == resolver.TICKET_APPROVED
    assert alarms == []


def test_startup_stalls_a_pending_ticket_even_INSIDE_its_deadline():
    """
    🔴 THE PROCESS BOUNDARY IS STRONGER EVIDENCE THAN THE DEADLINE, and this arm is what
    distinguishes reconciliation from the sweeper. An ask runs on a worker inside the
    process; a ticket pending at startup was minted by a process that no longer exists,
    so its worker is already dead. Waiting for `resolves_by` would leave a known-dead ask
    looking healthy for the whole ask timeout plus the grace.
    """
    live    = _ticket( resolves_by=NOW + timedelta( seconds=120 ) )
    session = _FakeSession( tickets=[ live ] )
    alarms  = []

    stalled = resolver.reconcile_on_startup(
        db_fn=_db_fn_for( session ), now_fn=lambda: NOW,
        alarm_fn=lambda *a, **k: alarms.append( a ),
    )

    assert stalled == [ live.id ]
    assert live.state == resolver.TICKET_STALLED
    assert len( alarms ) == 1


def test_startup_leaves_an_already_resolved_ticket_alone():
    """
    The negative half: reconciliation must not re-open settled history.

    🔴 POCHOLO 📣'S POINT, 2026-09-06, AND IT IS THE REASON THIS ARM IS NAMED FOR THE
    CONTRACT RATHER THAN THE CASE. Startup and the sweeper are two callers, and if they
    held two idempotency contracts there would be two writers able to disagree about a
    settled ticket. They hold ONE: both write through `_mark_stalled`, which takes the
    ticket's own lock and refuses anything not `pending`. This arm is what would go red
    if a third writer ever grew its own copy.
    """
    done    = _ticket( state=resolver.TICKET_APPROVED )
    session = _FakeSession( tickets=[ done ] )
    alarms  = []

    stalled = resolver.reconcile_on_startup(
        db_fn=_db_fn_for( session ), now_fn=lambda: NOW,
        alarm_fn=lambda *a, **k: alarms.append( a ),
    )

    assert stalled == []
    assert done.state == resolver.TICKET_APPROVED
    assert alarms == []


# ═══════════════════════════════════════════════════════════════════════════════════
# 4 · THE DEADLINE, AND THE SHAPE THE MINT AND THE RESOLVE BOTH SPEAK
# ═══════════════════════════════════════════════════════════════════════════════════

def test_the_deadline_is_the_ask_timeout_plus_grace_plus_margin_read_at_MINT_time():
    """
    Stored on the row rather than re-derived by the sweeper. An operator lowering either
    dial must not retroactively declare in-flight tickets overdue.
    """
    got = resolver.resolves_by_for( NOW, timeout_fn=lambda: 120, grace_fn=lambda: 300,
                                    apply_margin_seconds=60 )
    assert got == NOW + timedelta( seconds=480 )
    assert got > NOW


def test_the_deadline_MOVES_with_the_operator_dial_so_it_is_really_being_read():
    """
    POSITIVE CONTROL for the arm above. A `resolves_by_for` that ignored its timeout and
    returned a fixed offset would satisfy that assertion for one value of the dial.
    """
    short = resolver.resolves_by_for( NOW, timeout_fn=lambda: 30,  grace_fn=lambda: 0,
                                      apply_margin_seconds=0 )
    long_ = resolver.resolves_by_for( NOW, timeout_fn=lambda: 300, grace_fn=lambda: 0,
                                      apply_margin_seconds=0 )
    assert long_ > short, "the ask timeout is not reaching the deadline at all"


# ── POCHOLO 📣'S FINDING — THE FRESH SESSION IS THE GUARANTEE, AND IT IS INJECTABLE ──
#
# `_apply_resolution( ..., db_fn=get_db )`. The default is safe: `get_db` builds a new
# SessionLocal per call. But the seam is open, so until the refusal landed the whole
# re-validation guarantee rested on what callers happened to pass — and the failure is
# silent, because a stale read under a correct FOR UPDATE looks MORE careful, not less.

def test_a_session_that_already_holds_objects_is_REFUSED_not_quietly_trusted():
    """
    THE ARM POCHOLO'S FINDING BUYS. A caller threading an open session through for
    efficiency must be stopped at the door, not discovered later as a wrong answer.

    ⚠️ ASSERTS ON THE MESSAGE'S SUBSTANCE, not merely that something raised. A refusal
    that does not say WHY sends the next reader to the lock, which is the one place the
    problem is not.
    """
    dirty = _FakeSession( tickets=[], items=[] )
    dirty.identity_map = { "some-key": object() }

    with pytest.raises( RuntimeError ) as caught:
        resolver._apply_resolution(
            uuid.uuid4(), uuid.uuid4(), None, None,
            db_fn=_db_fn_for( dirty ),
        )

    message = str( caught.value )
    assert "FRESH session" in message
    assert "stale"        in message


def test_a_CLEAN_session_is_not_refused_which_is_what_makes_the_arm_above_mean_anything():
    """
    POSITIVE CONTROL. A guard that raised on every session would satisfy the arm above
    and take phase 3 down entirely — and every other arm in this file injects a clean
    fake, so this states the property rather than leaving it implied by their silence.
    """
    ticket = _ticket( state=resolver.TICKET_PENDING )
    clean  = _FakeSession( tickets=[ ticket ] )
    assert clean.identity_map == {}

    resolver._apply_resolution(
        ticket.id, ticket.item_id, resolver.TransitionIntent(
            to_status="queued", actor=MANAGER, recorded_actor=MANAGER,
            authority="standing", receipt_refs=None, blocked_by=None, reason=None,
            park_reason=None, next_chase_ts=None, title="t", session_id=None,
        ),
        gate.PromotionApproval( allowed=False, refusal="no" ),
        db_fn=_db_fn_for( clean ), now_fn=lambda: NOW,
    )
    assert ticket.state == resolver.TICKET_REFUSED


# ── TIFFANY 💍'S WINDOW, AND THE ARMS THAT HOLD ITS COMPUTABLE HALF SHUT ────────────
#
# She found a window in which the notification API would still ACCEPT Rick's answer while
# this deadline had already declared the ticket an orphan and fired an urgent alarm at a
# human. Mr. Radio ruled the fix: derive the room from the notification grace at MINT
# time, rather than raising a local constant to match it by convention.
#
# ⚠️ THESE ARE NOT ONE ARM WRITTEN FOUR WAYS. The first says the deadline clears the
# window; the second says the notification dial is genuinely reaching the deadline rather
# than a local constant that happens to be big enough; the third says the path PRODUCTION
# takes reads config at all; the fourth says the two halves read ONE key rather than two
# literals that match today.
#
# 🔴 AND WHAT NO ARM HERE CLAIMS: that the window is CLOSED. See `resolves_by_for`'s own
# docstring — on a bounce the notification is never marked expired, so a `delivered` row
# is answerable with no time check whatever, and no finite deadline reaches that. These
# arms hold the computable half. The rest is design 6.3's recovery path, a separate row.

def test_the_deadline_CLEARS_the_window_in_which_a_late_answer_is_still_accepted():
    """
    THE ARM TIFFANY'S FINDING BUYS. `routers/notifications.py:616-629` takes a response
    for `notification grace period seconds` AFTER the ask expired, so an answer is still
    valid until `expires_at + grace`. A deadline inside that is an alarm fired at a human
    about a ticket the world could still legitimately resolve.

    ⚠️ ASSERTED AS AN INEQUALITY AGAINST THE WINDOW, NOT AN EQUALITY AGAINST 480. A
    hard-coded total would pass just as happily on a build that had dropped the grace out
    of the sum, because at the shipped values it is the same number either way.
    """
    ask_timeout, grace = 120, 300

    answer_still_valid_until = NOW + timedelta( seconds=ask_timeout + grace )
    deadline                 = resolver.resolves_by_for(
        NOW, timeout_fn=lambda: ask_timeout, grace_fn=lambda: grace,
        apply_margin_seconds=resolver.APPLY_MARGIN_SECONDS,
    )

    assert deadline > answer_still_valid_until, (
        "the ticket stalls while the notification API would still take Rick's answer — "
        "this is exactly Tiffany's window, re-opened"
    )


def test_the_deadline_MOVES_with_the_NOTIFICATION_grace_dial_specifically():
    """
    POSITIVE CONTROL for the arm above, and a DIFFERENT control from the ask-timeout one.
    A `resolves_by_for` that ignored the grace and carried a large enough local constant
    would satisfy the clearance assertion at today's values and silently re-open the
    window the day an operator raised the grace.
    """
    small = resolver.resolves_by_for( NOW, timeout_fn=lambda: 120, grace_fn=lambda: 10,
                                      apply_margin_seconds=0 )
    large = resolver.resolves_by_for( NOW, timeout_fn=lambda: 120, grace_fn=lambda: 900,
                                      apply_margin_seconds=0 )
    assert ( large - small ).total_seconds() == 890, (
        "the notification grace is not reaching the deadline one-for-one"
    )


def test_the_DEFAULT_call_reads_config_rather_than_a_value_bound_at_import( monkeypatch ):
    """
    🔴 THE TRAP THIS ARM EXISTS FOR IS A DEFAULT ARGUMENT BINDING AT IMPORT. `grace_fn`
    defaults to `get_notification_grace_seconds`, and the mint site calls
    `resolves_by_for( requested_at )` with no injection at all — so every arm above,
    each passing its own `grace_fn`, proves nothing whatever about the path production
    actually takes.

    Patches the module global the function BODY reads (`_ini_value`), never the accessor
    captured in the signature: patching the latter leaves the default pointing at the
    original object, and the arm would pass while measuring nothing.
    """
    seen = []

    def fake_ini( key, return_type, fallback ):
        seen.append( key )
        return 900 if key == resolver.INI_KEY_NOTIFICATION_GRACE else fallback

    monkeypatch.setattr( resolver, "_ini_value", fake_ini )

    got = resolver.resolves_by_for( NOW, timeout_fn=lambda: 120 )

    assert resolver.INI_KEY_NOTIFICATION_GRACE in seen, "the default path never read the key"
    assert got == NOW + timedelta( seconds=120 + 900 + resolver.APPLY_MARGIN_SECONDS )


def test_the_grace_is_read_from_the_SAME_key_the_notification_router_reads():
    """
    ONE DECIDER, NOT TWO NUMBERS THAT MATCH TODAY — Mr. Radio's stated reason for refusing
    to simply raise the local constant to 300.

    ⚠️ THE ROUTER'S SIDE IS DERIVED FROM ITS SOURCE, NOT RE-TYPED HERE. A literal copied
    into this file would be a third derivation of one value, and the guard would then
    compare two of my own copies rather than this module against the router.

    Also pins the FALLBACK: if the key is unreadable both halves must land on the same
    assumption, or a config one reads as 300 and the other as 0 re-creates the very
    disagreement the derivation removes.
    """
    router_src = ( Path( resolver.__file__ ).parent / "routers" / "notifications.py" ).read_text()

    assert f'"{resolver.INI_KEY_NOTIFICATION_GRACE}"' in router_src, (
        f"the router no longer reads {resolver.INI_KEY_NOTIFICATION_GRACE!r} — the two "
        "halves of the late-answer window have drifted onto different keys"
    )
    assert f"default={resolver.FALLBACK_NOTIFICATION_GRACE_SECONDS}" in router_src, (
        "the router's fallback for that key no longer matches this module's"
    )


def test_the_intent_survives_the_round_trip_through_JSONB():
    """
    One class knows the shape in both directions. A writer and a reader that each knew it
    independently would agree until somebody added a field to one of them.
    """
    chase    = datetime( 2026, 9, 7, 9, 0, tzinfo=timezone.utc )
    original = resolver.TransitionIntent(
        to_status="queued", actor=MANAGER, recorded_actor="rick@example.com",
        authority="standing", receipt_refs={ "commit": "abc1234" },
        blocked_by=[ { "kind": "persona", "id": "maria" } ],
        reason="because", park_reason=None, next_chase_ts=chase,
        title="a row", session_id="21dff055",
    )
    assert resolver.TransitionIntent.from_payload( original.as_payload() ) == original


def test_the_stored_payload_is_JSON_safe():
    """A datetime in a JSONB column is an error at COMMIT time, far from here."""
    json.dumps( _ticket().payload )      # raises if any value is not JSON-serializable


def test_the_intent_does_not_persist_the_callers_account_identity():
    """
    🔴 A RESOLVED AUTHORIZATION DECISION THAT GETS STORED BECOMES A FORGEABLE ONE.
    `account_persona` decides whether Rick is ask-exempt. It is settled synchronously by
    `promotion_precheck` and deliberately never written to the ticket, so anyone who
    could write this JSON still cannot skip the ask.
    """
    payload = _ticket().payload
    for forbidden in ( "account_persona", "account_email" ):
        assert forbidden not in payload, (
            f"the ticket persists {forbidden!r} — a later resolver could replay an "
            f"authorization decision instead of the credentials that earned it"
        )


# ═══════════════════════════════════════════════════════════════════════════════════
# 5 · THE DEFAULTS — the seams every arm above injects around
#
# 🔴 EVERY TEST ABOVE REPLACES THESE, WHICH IS EXACTLY WHY THEY NEED THEIR OWN ARMS.
# `task_promotion_gate._default_ask` shipped BROKEN once for this precise reason: it
# imported a module that does not exist, every test injected `ask_fn`, and the real
# default never ran — a 500 through the door and Rick never asked. Maya found it at
# `47cff912`. A seam that is convenient to inject around is a seam nothing exercises.
# ═══════════════════════════════════════════════════════════════════════════════════

def test_the_default_serializer_produces_the_shape_a_synchronous_200_carries():
    """
    🔴 IT CALLS THE ROUTER'S OWN SERIALIZERS RATHER THAN REBUILDING THE SHAPE, and this
    arm is what proves the lazy import inside it actually resolves. A second serializer
    would be a second derivation of the response body — and the whole reason the body is
    stored is that a re-derived answer is not the same answer.
    """
    item  = _item()
    event = MagicMock()
    event.id = uuid.uuid4(); event.item_id = item.id; event.ts = NOW
    event.actor = MANAGER; event.transition = "not_approved -> queued"
    event.receipt_refs = None; event.authority = "standing"; event.reason = None

    body = resolver._default_serialize( item, event )

    assert set( body ) == { "item", "event" }, f"got {sorted( body )}"
    assert body[ "item" ][ "id" ] == str( item.id )


def test_the_default_clock_returns_an_aware_utc_instant():
    """A naive datetime compared against a timezone-aware `resolves_by` raises."""
    now = resolver._now()
    assert now.tzinfo is not None, "a naive clock would blow up every deadline comparison"


def test_the_default_alarm_fires_URGENT_and_names_the_row( monkeypatch ):
    """
    The real alarm, with only the transport replaced. `urgent` is the one priority that
    reaches somebody who is not already looking at the screen.
    """
    import lupin_cli.notifications.notify_user_async as nua
    sent = []
    monkeypatch.setattr( nua, "notify_user_async", lambda request: sent.append( request ) )

    ticket_id, item_id = uuid.uuid4(), uuid.uuid4()
    resolver._default_alarm( ticket_id, item_id, MANAGER,
                             NOW - timedelta( minutes=7 ), "it died", NOW )

    assert len( sent ) == 1, "a stalled promotion pushed nothing at a human"
    assert sent[ 0 ].priority.value == "urgent"
    assert str( ticket_id ) in sent[ 0 ].abstract, "the alarm does not name the ticket"
    assert str( item_id )   in sent[ 0 ].abstract, "the alarm does not name the row"


def test_an_alarm_that_BLOWS_UP_does_not_take_the_sweeper_down_with_it( monkeypatch, capsys ):
    """
    🔴 SWALLOWED AND NAMED, DELIBERATELY. The sweeper's job is to report EVERY orphan.
    A raise here would abandon the rest of the batch to report this one — silencing
    every later orphan in order to shout about this one's transport.
    """
    import lupin_cli.notifications.notify_user_async as nua
    def _boom( request ): raise RuntimeError( "the notification surface is down" )
    monkeypatch.setattr( nua, "notify_user_async", _boom )

    resolver._default_alarm( uuid.uuid4(), uuid.uuid4(), MANAGER, NOW, "it died", NOW )

    assert "the notification surface is down" in capsys.readouterr().out, (
        "the alarm failed silently — a swallowed exception that says nothing is the "
        "failure mode this codebase spends its length refusing"
    )


def test_the_alarm_survives_a_ticket_with_no_deadline():
    """`resolves_by` is NOT NULL in the schema, so this is defence rather than a case."""
    import lupin_cli.notifications.notify_user_async as nua
    original = nua.notify_user_async
    nua.notify_user_async = lambda request: None
    try:
        resolver._default_alarm( uuid.uuid4(), uuid.uuid4(), MANAGER, None, "it died", NOW )
    finally:
        nua.notify_user_async = original


def test_one_ticket_that_explodes_does_not_abandon_the_rest_of_the_sweep( monkeypatch, capsys ):
    """
    🔴 A BATCH THAT STOPS AT ITS FIRST FAILURE REPORTS FEWER ORPHANS THAN EXIST, and a
    monitor that dies partway and reports fewer sessions than exist is a monitor that
    lies. Both tickets below are overdue; the first one raises.
    """
    bad  = _ticket( resolves_by=NOW - timedelta( seconds=2 ) )
    good = _ticket( resolves_by=NOW - timedelta( seconds=1 ) )
    session = _FakeSession( tickets=[ bad, good ] )

    real = resolver._mark_stalled
    def _explode_on_the_first( ticket_id, **kwargs ):
        if ticket_id == bad.id: raise RuntimeError( "row is wedged" )
        return real( ticket_id, **kwargs )
    monkeypatch.setattr( resolver, "_mark_stalled", _explode_on_the_first )

    stalled = resolver.sweep_stalled_tickets(
        db_fn=_db_fn_for( session ), now_fn=lambda: NOW,
        alarm_fn=lambda *a, **k: None,
    )

    assert stalled == [ good.id ], f"the sweep abandoned the batch: {stalled}"
    assert "row is wedged" in capsys.readouterr().out, "the failure was swallowed unnamed"


def test_one_ticket_that_explodes_does_not_abandon_the_rest_of_startup( monkeypatch, capsys ):
    """The same claim for reconciliation, which is a different loop with the same duty."""
    bad  = _ticket()
    good = _ticket()
    session = _FakeSession( tickets=[ bad, good ] )

    real = resolver._mark_stalled
    def _explode_on_the_first( ticket_id, **kwargs ):
        if ticket_id == bad.id: raise RuntimeError( "row is wedged" )
        return real( ticket_id, **kwargs )
    monkeypatch.setattr( resolver, "_mark_stalled", _explode_on_the_first )

    stalled = resolver.reconcile_on_startup(
        db_fn=_db_fn_for( session ), now_fn=lambda: NOW,
        alarm_fn=lambda *a, **k: None,
    )

    assert stalled == [ good.id ]
    assert "row is wedged" in capsys.readouterr().out


def test_stalling_a_ticket_that_no_longer_exists_reports_False():
    """A ticket deleted between the sweep's query and its lock. Not an error."""
    assert resolver._mark_stalled(
        uuid.uuid4(), db_fn=_db_fn_for( _FakeSession() ), now_fn=lambda: NOW,
        alarm_fn=lambda *a, **k: None,
    ) is False


def test_the_apply_phase_on_a_ticket_that_vanished_returns_None():
    """
    Phase 3 re-reads the ticket under its own lock, so it can find it gone even though
    phase 1 read it. Returning None rather than raising keeps the background task quiet
    about a row somebody legitimately deleted.
    """
    got = resolver._apply_resolution(
        uuid.uuid4(), uuid.uuid4(), _intent(), _allowed(),
        db_fn=_db_fn_for( _FakeSession() ), now_fn=lambda: NOW,
    )
    assert got is None


# ═══════════════════════════════════════════════════════════════════════════════════
# 6 · THE POLL TARGET — the condition of the ruling, not a convenience
#
# 🔴 A 202 WHOSE TICKET ID NOTHING CAN READ IS THE SAME DEFECT WITH THE WAITING MOVED
# SOMEWHERE NOBODY LOOKS. That is María 🌸's binding requirement on going asynchronous,
# and it means the 202 and these two doors are ONE feature. Shipping the first without
# the second would have met the letter of the ruling and none of it.
# ═══════════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def ticket_client( assembled_app, monkeypatch ):
    """The real app over a fake session holding two tickets in different states."""
    pending  = _ticket()
    resolved = _ticket( state=resolver.TICKET_APPROVED )
    resolved.response_body = { "item": { "id": str( resolved.item_id ) }, "event": {} }
    resolved.resolved_at   = NOW
    session = _FakeSession( tickets=[ pending, resolved ] )

    monkeypatch.setattr( tasks, "get_db", _db_fn_for( session ) )
    assembled_app.dependency_overrides[ require_api_key_or_jwt ] = lambda: "test-user"
    yield TestClient( assembled_app, raise_server_exceptions=False ), pending, resolved
    assembled_app.dependency_overrides.pop( require_api_key_or_jwt, None )


def test_the_literal_promotions_path_reaches_its_OWN_route_not_the_task_lookup():
    """
    🔴 THE SHADOWING ARM, AND THIS REPO HAS ALREADY PAID FOR IT ONCE. Starlette matches
    on path AND method in registration order, so a literal `/tasks/promotions` declared
    AFTER the parameterised `/tasks/{task_id}` is swallowed by it and answers 422 on a
    ticket id that is not a task UUID — which is exactly how `/api/tasks/flow-ratio`
    answered 422 for an evening.

    ⚠️ IT ASKS THE ASSEMBLED APP WHICH ENDPOINT THE PATH RESOLVES TO, rather than
    comparing registration indices. An index comparison is arithmetic about a list; this
    is the question the router actually answers.
    """
    import lupin_app.main as main
    from starlette.routing import Match

    scope = { "type": "http", "method": "GET", "path": "/api/tasks/promotions",
              "path_params": {}, "headers": [], "query_string": b"", "root_path": "" }
    reached = None
    for route in main.app.routes:
        match, _ = route.matches( scope )
        if match == Match.FULL:
            reached = getattr( route, "name", None )
            break

    assert reached == "list_promotion_tickets", (
        f"GET /api/tasks/promotions resolves to {reached!r}. A literal path swallowed by "
        f"a parameterised sibling is how /api/tasks/flow-ratio answered 422 all evening."
    )


def test_one_ticket_is_readable_and_a_resolved_one_carries_the_answer( ticket_client ):
    c, pending, resolved = ticket_client

    got = c.get( f"/api/tasks/promotions/{resolved.id}" )

    assert got.status_code == 200, got.text
    body = got.json()
    assert body[ "state" ]         == resolver.TICKET_APPROVED
    assert body[ "ticket_id" ]     == str( resolved.id )
    assert body[ "response_body" ] == resolved.response_body, (
        "the poll did not hand back the { item, event } a synchronous 200 would have "
        "carried — which is the whole reason that column exists"
    )


def test_a_ticket_that_does_not_exist_is_a_404_not_an_empty_success( ticket_client ):
    c, _, _ = ticket_client
    assert c.get( f"/api/tasks/promotions/{uuid.uuid4()}" ).status_code == 404


def test_the_listing_defaults_to_PENDING_which_is_what_is_waiting_on_rick( ticket_client ):
    """
    Design §4: the task row cannot be this surface. A row awaiting promotion is still
    `not_approved`, which `task_store_rules` puts outside every board query BY DESIGN, so
    a pending marker there would be visible only to somebody who already knows the id —
    the one person who does not need telling.
    """
    c, pending, resolved = ticket_client

    body = c.get( "/api/tasks/promotions" ).json()

    ids = [ t[ "ticket_id" ] for t in body[ "tickets" ] ]
    assert str( pending.id ) in ids
    assert body[ "count" ] == len( body[ "tickets" ] ), "the count disagrees with the rows"


def test_the_listing_can_be_asked_for_EVERY_state( ticket_client ):
    """
    POSITIVE CONTROL for the arm above. Without it, a listing that returned everything
    regardless of the filter would satisfy the pending assertion perfectly.
    """
    c, pending, resolved = ticket_client

    ids = [ t[ "ticket_id" ] for t in c.get( "/api/tasks/promotions?state=all" ).json()[ "tickets" ] ]

    assert str( pending.id )  in ids
    assert str( resolved.id ) in ids, "state=all did not reach a resolved ticket"


def test_a_ticket_with_NO_deadline_is_not_swept_because_SQL_would_never_select_it():
    """
    🔴 TIFFANY 💍'S FINDING, 2026-09-06, ON THIS EXACT HUNK. The first cut read
    `resolves_by is not None and resolves_by >= now`, so a NULL deadline fell THROUGH the
    guard and the ticket was stalled — while SQL's `resolves_by < now` is NULL for that
    row, which is not TRUE, so the sweeper's own query would never have selected it.

    ⚠️ TWO LAYERS, ONE QUESTION, OPPOSITE ANSWERS — the exact defect the Python re-check
    was ADDED to close, committed inside the fix for it. And it diverged in the unsafe
    direction for an alarm: every stall pushes an urgent notification, so the Python side
    would have woken a human about a ticket the SQL side considers permanently out of
    scope.

    `resolves_by` is NOT NULL in the schema, so this is unreachable from the database
    today. A check that disagrees with the query it is paired with is wrong anyway.
    """
    dateless = _ticket()
    dateless.resolves_by = None
    session = _FakeSession( tickets=[ dateless ] )
    alarms  = []

    stalled = resolver.sweep_stalled_tickets(
        db_fn=_db_fn_for( session ), now_fn=lambda: NOW,
        alarm_fn=lambda *a, **k: alarms.append( a ),
    )

    assert stalled == [], "a ticket SQL would never select was stalled by the Python check"
    assert dateless.state == resolver.TICKET_PENDING
    assert alarms == [], "an urgent notification fired about a ticket with no deadline"


def test_startup_STILL_stalls_a_ticket_with_no_deadline_because_its_evidence_is_different():
    """
    🔴 THE DISCRIMINATING HALF OF TIFFANY'S FIX, and without it the alignment above would
    have quietly widened into reconciliation and broken the bounce case. Startup passes
    `require_overdue=False` because its evidence is the PROCESS BOUNDARY, not the clock:
    a ticket pending at startup was minted by a process that no longer exists. A missing
    deadline changes nothing about that.
    """
    dateless = _ticket()
    dateless.resolves_by = None
    session = _FakeSession( tickets=[ dateless ] )
    alarms  = []

    stalled = resolver.reconcile_on_startup(
        db_fn=_db_fn_for( session ), now_fn=lambda: NOW,
        alarm_fn=lambda *a, **k: alarms.append( a ),
    )

    assert stalled == [ dateless.id ], (
        "the NULL-deadline alignment leaked into startup, where the clock is not the "
        "evidence — a known-dead ask would now sit pending forever"
    )
    assert len( alarms ) == 1
