#!/usr/bin/env python3
"""
A MANAGER MAY CLOSE A TICKET, AND NOTHING ELSE MOVES. Row adaf7698.

Rick, 2026-09-09: "A manager should be able to close a ticket. That is not a matter
of state security." Scope, ruled 2026-09-10 ~17:28 EDT: close only, and a manager's
close COUNTS toward the create/close ratio like any other close.
Design: Rio ⚡, src/rnd/2026.09.10-manager-can-close-a-ticket-design.md (Option A).

A manager seat's close used to be refused at three doors plus a throttle:
  · the RECEIPT rule (422) — a decision row has no commit and no test run to cite
  · the APPROVER gate (403) — `not_approved -> done` matched the admission clause
  · the PROMOTION gate — even past the approver gate, Rick would be asked whether to
    PROMOTE a row that was being closed
  · the admission THROTTLE (429) — a close out of holding spent an admission slot

WHY THESE TESTS DRIVE HTTP. Every one of those doors lives in, or is called from,
`transition_task`. A test of the pure functions alone would stay green with a call
site deleted, which is how door 1 was once found wired to nothing.

WHAT IS STOOD IN, AND WHY EACH IS NOT THE SUBJECT:
  · the session BRIDGE — `tasks.is_manager_figure`, `tasks.classify_manager_figure_denial`
    and `tasks.get_voice_persona` are replaced, so "manager" and "worker" are two
    session ids rather than files on this box. The router passes them to
    `manager_refusal` explicitly, which is the seam that makes this possible.
  · the ASK — `approval_for_promotion` and `promotion_precheck` are recorders that
    answer yes, and `_default_ask` raises. A unit test must never put a question in
    front of Rick, and a recorder that answers yes is what lets a WRONGLY reached gate
    show up as a 200 instead of hiding behind a refusal.
  · commit REACHABILITY — replaced with a recorder, so the commit arm does not depend
    on which branches this checkout happens to hold. The recorder is asserted on.
"""
import json
import os
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.rest import task_approval_settings as approval
from cosa.rest import task_promotion_gate as promotion_gate
from cosa.rest import task_promotion_resolver as promotion_resolver
from cosa.rest import task_store_rules as rules
from cosa.rest.postgres_models import TaskItem, TaskEvent
from cosa.rest.routers import tasks
from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt, authenticated_account_email
from lupin_cli.claude_code.hooks.lib.manager_figure import DENIAL_DENIED

NOW             = datetime( 2026, 9, 10, 21, 30, tzinfo=timezone.utc )
MANAGER_SID     = "d54262de"
WORKER_SID      = "5a3f00c1"
MANAGER         = f"mr radio {MANAGER_SID}"
WORKER          = f"sam {WORKER_SID}"
A_REAL_TEST_RUN = "ts-b51e63c9"
A_COMMIT        = "e4c49fd2"

# A LOGIN account mapped to an approver. Used only by the throttle's positive control
# and the account-identity arm — every manager seat in the fleet has NO login account.
APPROVER_EMAIL  = "maria@example.com"


def _item( **overrides ):
    fields = dict(
        id                  = uuid.uuid4(),
        item_class          = "task",
        title               = "a row a manager knows is finished",
        body                = None,
        project             = "lupin",
        owner_persona       = "sam",
        accountable_manager = "mr radio",
        created_by          = MANAGER,
        status              = "not_approved",
        blocked_by          = [ ],
        next_chase_ts       = None,
        gate_class          = "none",
        priority            = "P1",
        source_qid          = None,
        correlation_key     = None,
        created_ts          = NOW,
        updated_ts          = NOW,
        title_trimmed       = False,
    )
    fields.update( overrides )
    return TaskItem( **fields )


@pytest.fixture
def repo( monkeypatch ):
    """The router's db seams, faked."""
    fake = MagicMock()
    fake.statuses_for_ids.return_value = { }

    @contextmanager
    def _fake_get_db():
        yield MagicMock()

    monkeypatch.setattr( tasks, "get_db", _fake_get_db )
    monkeypatch.setattr( tasks, "TaskRepository", lambda session: fake )
    return fake


@pytest.fixture
def settings( tmp_path, monkeypatch ):
    """
    Holding-area enforcement ON, inside tmp_path. The fleet INI is never read, and
    turning enforcement on for real is Rick's word, not a test's.
    """
    target = tmp_path / "task-approval-settings.json"
    monkeypatch.setattr( approval, "override_path", lambda: str( target ) )
    monkeypatch.setattr( approval, "_cache", { "approvers": None, "enforcement_active": None } )
    monkeypatch.setattr( approval, "_cache_mtime", None )
    monkeypatch.setattr( approval, "get_approver_accounts", lambda: { APPROVER_EMAIL: "maria" } )
    target.write_text( json.dumps( { "approvers": [ "maria", "mr radio" ], "enforcement_active": True } ) )
    approval._cache_mtime = None
    return target


@pytest.fixture
def seats( monkeypatch ):
    """
    Two seats, told apart by session id alone, exactly as the server tells them apart.

    No `raising=False`: if the router stops naming these, the patch must fail loudly
    rather than leave the file judging a bridge on this box.
    """
    monkeypatch.setattr( tasks, "is_manager_figure", lambda session_id, *a, **k: session_id == MANAGER_SID )
    monkeypatch.setattr( tasks, "classify_manager_figure_denial", lambda session_id, *a, **k: DENIAL_DENIED )
    monkeypatch.setattr( tasks, "get_voice_persona",
                         lambda session_id: { "name": "Mr. Radio" } if session_id == MANAGER_SID else None )


@pytest.fixture
def asks( monkeypatch ):
    """Every call into the promotion gate, recorded and answered YES. A real ask raises."""
    calls = [ ]

    def _approval_for_promotion( **kw ):
        calls.append( ( "approval_for_promotion", kw ) )
        return promotion_gate.PromotionApproval( allowed=True, approval_source=promotion_gate.APPROVAL_KEYPRESS )

    def _precheck( **kw ):
        calls.append( ( "promotion_precheck", kw ) )
        return None

    def _no_real_ask( **kw ):
        raise AssertionError( "a unit test was about to put a real question in front of Rick" )

    monkeypatch.setattr( promotion_gate, "approval_for_promotion", _approval_for_promotion )
    monkeypatch.setattr( promotion_gate, "promotion_precheck", _precheck )
    monkeypatch.setattr( promotion_gate, "_default_ask", _no_real_ask )
    return calls


@pytest.fixture
def reachable( monkeypatch ):
    """Commit reachability, recorded. Not this file's subject — see the module docstring."""
    seen = [ ]

    def _reachable( sha, scope_roots ):
        seen.append( sha )
        return [ ]

    monkeypatch.setattr( rules, "_validate_commit_reachable", _reachable )
    return seen


def _client( account_email=None ):
    """A client whose login account is the one variable. None is every agent seat."""
    app = FastAPI()
    app.include_router( tasks.router )
    app.dependency_overrides[ require_api_key_or_jwt ]      = lambda: "test-user"
    app.dependency_overrides[ authenticated_account_email ] = lambda: account_email
    return TestClient( app )


def _armed( repo, item, transition ):
    repo.get_by_id_for_update.return_value = item
    repo.apply_transition.return_value = TaskEvent(
        id=1, item_id=item.id, item=item, ts=NOW, actor=MANAGER,
        transition=transition, receipt_refs=None, authority="standing",
    )


def _post( item, to_status, actor, account_email=None, **extra ):
    body = { "to_status": to_status, "actor": actor }
    body.update( extra )
    return _client( account_email ).post( f"/api/tasks/{item.id}/transition", json=body )


def _recorded_receipts( repo ):
    assert repo.apply_transition.called, "the transition never reached the repository"
    return repo.apply_transition.call_args.kwargs[ "receipt_refs" ]


def test_the_isolation_actually_isolates( settings, seats ):
    """Runs first. A green file must not also be consistent with reading real settings or real bridges."""
    assert str( settings ) == approval.override_path()
    assert approval.get_enforcement_active() is True
    assert tasks.is_manager_figure( MANAGER_SID ) is True
    assert tasks.is_manager_figure( WORKER_SID ) is False


# ---------------------------------------------------------------------------
# PROMOTE, DEMOTE, UN-PARK AND WON'T-FIX ARE UNCHANGED — for a MANAGER seat
# ---------------------------------------------------------------------------

def test_a_manager_seat_still_cannot_PROMOTE_out_of_holding( repo, settings, seats, asks ):
    """Rick, 2026-09-08: promoting into the live list is his alone. Closing does not widen it."""
    item = _item( status="not_approved" )
    _armed( repo, item, "not_approved->queued" )

    r = _post( item, "queued", MANAGER )

    assert r.status_code == 403, f"a manager seat PROMOTED a row out of holding: {r.status_code} {r.text}"
    assert "admitting a row out of" in r.json()[ "detail" ]
    assert asks == [ ], "the approver gate must refuse this before the promotion gate is reached"
    repo.apply_transition.assert_not_called()


def test_a_manager_seat_still_cannot_DEMOTE_into_holding( repo, settings, seats, asks ):
    item = _item( status="queued" )
    _armed( repo, item, "queued->not_approved" )

    r = _post( item, "not_approved", MANAGER, reason="does not merit the active list" )

    assert r.status_code == 403, f"a manager seat DEMOTED a row: {r.status_code} {r.text}"
    assert "demoting a row back into" in r.json()[ "detail" ]
    repo.apply_transition.assert_not_called()


def test_a_manager_seat_still_cannot_UNPARK( repo, settings, seats, asks ):
    item = _item( status="parked" )
    _armed( repo, item, "parked->queued" )

    r = _post( item, "queued", MANAGER )

    assert r.status_code == 403, f"a manager seat UN-PARKED a row: {r.status_code} {r.text}"
    assert "un-parking a row out of" in r.json()[ "detail" ]
    repo.apply_transition.assert_not_called()


def test_a_manager_seat_still_cannot_WONT_FIX( repo, settings, seats, asks ):
    """Won't-fix counts toward the ratio and is approver-only for that reason."""
    item = _item( status="queued" )
    _armed( repo, item, "queued->wont_fix" )

    r = _post( item, "wont_fix", MANAGER, reason="nobody is going to do this" )

    assert r.status_code == 403, f"a manager seat closed a row as WONT_FIX: {r.status_code} {r.text}"
    assert "wont_fix" in r.json()[ "detail" ]
    repo.apply_transition.assert_not_called()


def test_a_manager_seat_still_cannot_WONT_FIX_a_HELD_row( repo, settings, seats, asks ):
    """
    The arm that proves the carve-out's PLACEMENT matters. A won't-fix out of holding
    starts from the one status the carve-out keys on; it is refused only because the
    won't-fix clause runs first.
    """
    item = _item( status="not_approved" )
    _armed( repo, item, "not_approved->wont_fix" )

    r = _post( item, "wont_fix", MANAGER, reason="nobody is going to do this" )

    assert r.status_code == 403, f"a manager seat WONT_FIXED a held row: {r.status_code} {r.text}"
    assert "wont_fix" in r.json()[ "detail" ]
    repo.apply_transition.assert_not_called()


def test_a_manager_seat_still_cannot_close_a_PARKED_row( repo, settings, seats, asks ):
    """A park is Rick's own not-now (Mr. Radio's review ruling, 2026-09-10 17:10 EDT)."""
    item = _item( status="parked" )
    _armed( repo, item, "parked->done" )

    r = _post( item, "done", MANAGER, receipt_refs={ "test_run": A_REAL_TEST_RUN } )

    assert r.status_code == 403, f"a manager seat closed a PARKED row: {r.status_code} {r.text}"
    detail = r.json()[ "detail" ]
    assert "PARKED" in detail, f"the refusal must name the park: {detail}"
    assert "Ask Rick" in detail, f"the refusal must say what to do: {detail}"
    repo.apply_transition.assert_not_called()


# ---------------------------------------------------------------------------
# POSITIVE ARMS — the close itself
# ---------------------------------------------------------------------------

def test_a_manager_seat_closes_a_HELD_row_with_a_commit( repo, settings, seats, asks, reachable ):
    item = _item( status="not_approved" )
    _armed( repo, item, "not_approved->done" )

    r = _post( item, "done", MANAGER, receipt_refs={ "commit": A_COMMIT } )

    assert r.status_code == 200, r.text
    assert reachable == [ A_COMMIT ], "the commit rule must still have run"
    assert repo.apply_transition.call_args.kwargs[ "to_status" ] == "done"


def test_a_manager_seat_closes_a_DECISION_row_from_NOT_APPROVED_on_its_own_attestation( repo, settings, seats, asks ):
    """
    The row's acceptance, named: `manager_attestation` is the receipt kind that closes a
    decision row, whose only product is a ruling. It is recorded as a plain `done` — Rick
    ruled the close COUNTS, so nothing marks it for the ratio gate to skip.
    """
    item = _item( status="not_approved", item_class="decision" )
    _armed( repo, item, "not_approved->done" )

    r = _post( item, "done", MANAGER, receipt_refs={ "manager_attestation": "Rick ruled it by keypress" } )

    assert r.status_code == 200, r.text
    assert repo.apply_transition.call_args.kwargs[ "to_status" ] == "done"
    assert set( _recorded_receipts( repo ) ) == { "manager_attestation" }


def test_a_manager_seat_closes_a_DECISION_row_from_QUEUED_on_its_own_attestation( repo, settings, seats, asks ):
    """The approver gate is not involved from `queued`; the receipt rule alone decides."""
    item = _item( status="queued", item_class="decision" )
    _armed( repo, item, "queued->done" )

    r = _post( item, "done", MANAGER, receipt_refs={ "manager_attestation": "Rick ruled it by keypress" } )

    assert r.status_code == 200, r.text
    assert set( _recorded_receipts( repo ) ) == { "manager_attestation" }


def test_a_manager_close_does_not_ask_rick( repo, settings, seats, asks ):
    """A close is not a promotion, so Rick must not be asked whether to promote it."""
    item = _item( status="not_approved" )
    _armed( repo, item, "not_approved->done" )

    r = _post( item, "done", MANAGER, receipt_refs={ "manager_attestation": "finished" } )

    assert r.status_code == 200, r.text
    assert asks == [ ], f"Rick was asked about a close: {asks}"


def test_a_manager_close_mints_no_promotion_ticket_on_the_async_path( repo, settings, seats, asks, monkeypatch ):
    """The asynchronous fork sits inside the same block; an opted-in close must not get a 202."""
    resolved = [ ]
    monkeypatch.setattr( promotion_gate, "promotion_is_asynchronous", lambda requested, *a, **k: requested is True )
    monkeypatch.setattr( promotion_resolver, "resolve_ticket", lambda ticket_id: resolved.append( ticket_id ) )
    item = _item( status="not_approved" )
    _armed( repo, item, "not_approved->done" )

    r = _post( item, "done", MANAGER, receipt_refs={ "manager_attestation": "finished" }, asynchronous=True )

    assert r.status_code == 200, f"a close was handed a promotion ticket: {r.status_code} {r.text}"
    assert asks == [ ]
    assert resolved == [ ]


def test_the_recorded_manager_attestation_is_the_SERVERS_identity( repo, settings, seats, asks ):
    """
    The discriminating arm. The manager types "rick"; the ledger must record the manager
    seat the server resolved. Without this, the helper could return its input and every
    other test here would pass.
    """
    item = _item( status="queued" )
    _armed( repo, item, "queued->done" )
    sent = { "manager_attestation": "rick" }

    r = _post( item, "done", MANAGER, receipt_refs=dict( sent ) )

    assert r.status_code == 200, r.text
    recorded = _recorded_receipts( repo )
    assert recorded[ "manager_attestation" ] == f"mr radio {MANAGER_SID}", recorded
    assert recorded is not sent


def test_a_manager_seat_whose_bridge_names_no_persona_is_recorded_by_its_seat( repo, settings, seats, asks, monkeypatch ):
    monkeypatch.setattr( tasks, "get_voice_persona", lambda session_id: None )
    item = _item( status="queued" )
    _armed( repo, item, "queued->done" )

    r = _post( item, "done", MANAGER, receipt_refs={ "manager_attestation": "rick" } )

    assert r.status_code == 200, r.text
    assert _recorded_receipts( repo )[ "manager_attestation" ] == f"manager seat {MANAGER_SID}"


def test_a_logged_in_approver_attests_as_their_ACCOUNT( repo, settings, seats, asks ):
    """A login account is the stronger identity, so it is the one recorded — not the typed actor."""
    item = _item( status="queued" )
    _armed( repo, item, "queued->done" )

    r = _post( item, "done", "somebody typed this", account_email=APPROVER_EMAIL,
               receipt_refs={ "manager_attestation": "rick" } )

    assert r.status_code == 200, r.text
    assert _recorded_receipts( repo )[ "manager_attestation" ] == "maria"


# ---------------------------------------------------------------------------
# REFUSAL ARMS — a worker seat is exactly where it was
# ---------------------------------------------------------------------------

def test_a_worker_seat_cannot_mint_a_manager_attestation( repo, settings, seats, asks ):
    item = _item( status="queued", item_class="decision" )
    _armed( repo, item, "queued->done" )

    r = _post( item, "done", WORKER, receipt_refs={ "manager_attestation": "trust me" } )

    assert r.status_code == 403, f"a WORKER seat minted a manager attestation: {r.status_code} {r.text}"
    detail = r.json()[ "detail" ]
    assert "is not a manager" in detail, f"the refusal must say why: {detail}"
    assert "ask your manager to close this row" in detail, f"the refusal must say what to do: {detail}"
    repo.apply_transition.assert_not_called()


def test_a_worker_seat_still_cannot_close_a_held_row( repo, settings, seats, asks ):
    item = _item( status="not_approved" )
    _armed( repo, item, "not_approved->done" )

    r = _post( item, "done", WORKER, receipt_refs={ "test_run": A_REAL_TEST_RUN } )

    assert r.status_code == 403, f"a WORKER seat closed a held row: {r.status_code} {r.text}"
    assert "a manager may close it" in r.json()[ "detail" ]
    repo.apply_transition.assert_not_called()


# ---------------------------------------------------------------------------
# THE THROTTLE — a close does not spend an admission slot
# ---------------------------------------------------------------------------

def test_the_admission_throttle_is_live_in_this_fixture( repo, settings, seats, asks, monkeypatch ):
    """The positive control. Without it the arm below passes against a throttle that is off."""
    monkeypatch.setattr( approval, "get_admission_window_seconds", lambda: 60 )
    repo.count_admissions_since.return_value = 3
    item = _item( status="not_approved" )
    _armed( repo, item, "not_approved->queued" )

    r = _post( item, "queued", "maria 611e3c47", account_email=APPROVER_EMAIL )

    assert r.status_code == 429, r.text


def test_a_manager_close_does_not_spend_an_admission_slot( repo, settings, seats, asks, monkeypatch ):
    monkeypatch.setattr( approval, "get_admission_window_seconds", lambda: 60 )
    repo.count_admissions_since.return_value = 3
    item = _item( status="not_approved" )
    _armed( repo, item, "not_approved->done" )

    r = _post( item, "done", MANAGER, receipt_refs={ "manager_attestation": "finished" } )

    assert r.status_code == 200, f"a manager's close was throttled as an admission: {r.status_code} {r.text}"
    repo.count_admissions_since.assert_not_called()


# ---------------------------------------------------------------------------
# THE PULL GATE — measured, not read: it takes no interest in a close
# ---------------------------------------------------------------------------

def test_the_pull_gate_is_silent_on_every_close( monkeypatch ):
    monkeypatch.setattr( approval, "get_manager_pull_disabled", lambda: True )

    # The control first: the toggle is ON here, so the gate CAN refuse.
    assert approval.refusal_for_pull( "queued", "in_progress", "somebody 1234", None,
                                      item_owner="rachel", item_manager="mr radio" ) is not None

    closable = [ s for s in rules.VALID_STATUSES if s not in rules.TERMINAL_STATUSES ]
    assert closable, "the loop below must have something to check"
    for from_status in closable:
        assert approval.refusal_for_pull( from_status, "done", WORKER, None,
                                          item_owner="sam", item_manager="mr radio" ) is None, from_status


# ---------------------------------------------------------------------------
# THE RECEIPT KEY ITSELF
# ---------------------------------------------------------------------------

def test_the_manager_attestation_closes_but_is_NOT_independently_checkable():
    assert rules.MANAGER_ATTESTATION_KEY == "manager_attestation"
    assert rules.MANAGER_ATTESTATION_KEY in rules.RECEIPT_KEY_WHITELIST
    assert rules.MANAGER_ATTESTATION_KEY in rules.CLOSING_RECEIPT_KEYS
    assert rules.MANAGER_ATTESTATION_KEY not in rules.CHECKABLE_RECEIPT_KEYS


# ---------------------------------------------------------------------------
# THE MANAGER CHECK RUNS ONLY WHERE IT CAN MATTER (Mr. Radio's review, 2026-09-10)
# ---------------------------------------------------------------------------

@pytest.fixture
def manager_checks( monkeypatch ):
    """Every call the door makes into `manager_refusal`, passed through to the real function."""
    calls = [ ]
    real  = promotion_gate.manager_refusal

    def _recording( *a, **k ):
        calls.append( a )
        return real( *a, **k )

    monkeypatch.setattr( promotion_gate, "manager_refusal", _recording )
    return calls


def test_a_non_close_transition_never_calls_the_manager_check( repo, settings, seats, asks, manager_checks, monkeypatch ):
    """A pull reads no bridge. The pull toggle is stood down so the request itself succeeds."""
    monkeypatch.setattr( approval, "get_manager_pull_disabled", lambda: False )
    item = _item( status="queued" )
    _armed( repo, item, "queued->in_progress" )

    r = _post( item, "in_progress", MANAGER )

    assert r.status_code == 200, r.text
    assert manager_checks == [ ], f"a queued->in_progress transition ran the manager check: {manager_checks}"


def test_a_close_calls_the_manager_check_exactly_once( repo, settings, seats, asks, manager_checks, reachable ):
    """The positive control for the arm above: the same recorder DOES see a close."""
    item = _item( status="queued" )
    _armed( repo, item, "queued->done" )

    r = _post( item, "done", MANAGER, receipt_refs={ "commit": A_COMMIT } )

    assert r.status_code == 200, r.text
    assert len( manager_checks ) == 1, manager_checks


def test_a_worker_claiming_the_manager_key_OFF_a_close_is_still_checked( repo, settings, seats, asks ):
    """The check's second trigger: the key claimed on a transition that is not a close."""
    item = _item( status="queued" )
    _armed( repo, item, "queued->blocked" )

    r = _post( item, "blocked", WORKER, receipt_refs={ "manager_attestation": "trust me" },
               blocked_by=[ { "kind": "user", "id": "rick" } ], next_chase_ts="2026-09-11T11:00:00-04:00" )

    assert r.status_code == 403, f"a worker slipped the manager key past the check: {r.status_code} {r.text}"
    assert "is not a manager" in r.json()[ "detail" ]
    repo.apply_transition.assert_not_called()


def test_the_carve_out_itself_refuses_a_manager_PROMOTE( settings ):
    """
    The door never hands this gate a manager on a promote, so only a pure call can watch
    the carve-out's own `to_status == done` clause refuse one.
    """
    promote = approval.refusal_for_admission( "not_approved", "queued", MANAGER, None, closer_is_manager=True )
    assert promote is not None and "admitting a row out of" in promote, promote

    # Its neighbours, so the refusal above is the carve-out's clause and not a gate that refuses everything.
    assert approval.refusal_for_admission( "not_approved", "done", MANAGER, None, closer_is_manager=True ) is None
    assert approval.refusal_for_admission( "parked", "done", MANAGER, None, closer_is_manager=True ) is not None


def test_a_manager_attestation_is_shape_checked_like_the_operators():
    errors = rules.validate_receipt_refs( { "manager_attestation": "bell\x07" } )
    assert any( "receipt manager_attestation" in e for e in errors ), errors
    assert rules.validate_receipt_refs( { "manager_attestation": "a clean sentence" } ) == [ ]
