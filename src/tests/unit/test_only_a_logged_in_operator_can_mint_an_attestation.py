#!/usr/bin/env python3
"""
THE OPERATOR ATTESTATION, ENTERED AT THE LAYER AN AGENT WOULD ENTER AT.

Rick ruled 2026-09-04 (row 1e12cc08) that his click IS the receipt: he can already
mark a row won't-fix from the progressive-disclosure controls and could not mark one
FIXED, and "I'm not waiting around for you guys to do proper task list hygiene."
María attached one non-negotiable to that ruling, and it is what this file guards:

    AN AGENT MUST NEVER BE ABLE TO MINT ONE.

🔴 WHY THESE TESTS DRIVE HTTP AND NOT `validate_receipt_refs`.

The rules module is PURE — no request, no token, no account — so it cannot tell
Rick's attestation from a seat typing {"operator_attestation": "rick"} at the API.
It validates SHAPE and says so in its own docstring. Every enforcement fact lives in
`routers/tasks.py`, where `account_email` exists. So a test that called the
validator would pass whether or not the router check exists at all: it would enter
BELOW the layer the incident enters at, and report on a component instead of a path.

⚠️ THE DOOR IT WOULD HAVE MISSED. `payload.actor` cannot do this job even though it
looks like it can. It is caller-DECLARED and `is_approver` is a string match, so any
seat can type an approver's persona — the approval gate's own comment says it
"refuses an honest non-approver and cannot stop a dishonest one". `account_email`
comes off a signature-validated token and is the only unforgeable fact in the
request. These arms flip THAT variable, never the actor string.

WHAT THIS FILE DOES NOT COVER, said plainly rather than left to be assumed:
  · The UI. No button is asserted here — that is browser-level and belongs in the
    E2E tier, per this row's own DONE MEANS.
  · Manager-hood or the approver allowlist. This is an IDENTITY gate: any logged-in
    human may attest, only an accountless caller is refused. Narrowing it to
    approvers is a POLICY question and is Rick's to rule, not a builder's to smuggle.
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
from cosa.rest import task_store_rules as rules
from cosa.rest.postgres_models import TaskItem, TaskEvent
from cosa.rest.routers import tasks
from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt, authenticated_account_email

NOW            = datetime( 2026, 9, 4, 0, 0, tzinfo=timezone.utc )
AGENT_ACTOR    = "john 54250c10"
OPERATOR_EMAIL = "ricardo.felipe.ruiz@gmail.com"
BYSTANDER_MAIL = "somebody.else@example.com"

# A `test_run` rather than a `commit`: both are CHECKABLE, and only the commit carries
# a git-reachability probe. Using one here would make these arms depend on the state
# of a repo they are not about.
A_REAL_TEST_RUN = "ts-b51e63c9"


def _item( **overrides ):
    fields = dict(
        id                  = uuid.uuid4(),
        item_class          = "bug",
        title               = "a row an operator can see is fixed",
        body                = None,
        project             = "lupin",
        owner_persona       = "john",
        accountable_manager = "maria",
        created_by          = "maria 21979045",
        status              = "in_progress",
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
    The approval module's override file, inside tmp_path. The fleet INI is never read.
    Without this the file would be measuring whoever happens to be an approver today.
    """
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


def _client( account_email ):
    """
    A client whose ONE variable is the login account the server resolves.

    `authenticated_account_email` is overridden rather than stubbed on the module, so
    the handler resolves it exactly as it does in production — through its own
    dependency. `None` is every agent seat in the fleet: API-key auth, no account.
    """
    app = FastAPI()
    app.include_router( tasks.router )
    app.dependency_overrides[ require_api_key_or_jwt ]     = lambda: "test-user"
    app.dependency_overrides[ authenticated_account_email ] = lambda: account_email
    return TestClient( app )


def _close( client, item, **extra ):
    body = { "to_status": "done", "actor": AGENT_ACTOR }
    body.update( extra )
    return client.post( f"/api/tasks/{item.id}/transition", json=body )


def _event( item, **overrides ):
    fields = dict(
        id=1, item_id=item.id, ts=NOW, actor=AGENT_ACTOR,
        transition="in_progress->done", receipt_refs=None, authority="standing",
    )
    fields.update( overrides )
    return TaskEvent( **fields )


def _recorded_receipts( repo ):
    """The receipt_refs the handler actually handed the repository."""
    assert repo.apply_transition.called, "the transition never reached the repository"
    return repo.apply_transition.call_args.kwargs[ "receipt_refs" ]


# ---------------------------------------------------------------------------
# The isolation control, first — a green file must not also be consistent with
# these arms reading the real fleet settings.
# ---------------------------------------------------------------------------

def test_the_isolation_actually_isolates( settings ):
    assert str( settings ) == approval.override_path()
    assert "projects-data" not in approval.override_path()
    assert approval.approver_persona_for_account( OPERATOR_EMAIL ) == "rick"
    assert approval.approver_persona_for_account( None ) is None


# ---------------------------------------------------------------------------
# THE ARM THIS FILE EXISTS FOR
# ---------------------------------------------------------------------------

def test_an_api_key_caller_cannot_mint_an_attestation( repo, settings ):
    """
    María's constraint 2, at the door. Every seat in the fleet authenticates by API
    key and has no login account, so `account_email` is None for all of them — and
    that None is the whole enforcement. No allowlist, no new configuration, and no
    string a seat can type to get past it.
    """
    item = _item()
    repo.get_by_id_for_update.return_value = item

    r = _close( _client( account_email=None ), item,
                receipt_refs={ "operator_attestation": "rick" } )

    assert r.status_code == 403, (
        f"an API-KEY CALLER MINTED AN OPERATOR ATTESTATION. The receipts rule is now "
        f"forgeable by every agent in the fleet. Got {r.status_code}: {r.text}"
    )
    assert "cannot be minted by an API-key caller" in r.json()[ "detail" ]
    repo.apply_transition.assert_not_called()


def test_a_logged_in_operator_closes_the_row_with_nothing_but_the_attestation( repo, settings ):
    """
    THE POSITIVE CONTROL, and it is not optional: without it a door that refused
    EVERY attestation would satisfy the arm above. One variable moves — the account.

    It also pins Rick's ruling itself. No commit, no test_run, no doc_path: the
    assertion IS the receipt, which is the thing he ruled and the thing option (b)
    would have taken away.
    """
    item = _item()
    repo.get_by_id_for_update.return_value = item
    repo.apply_transition.return_value = _event( item )

    r = _close( _client( account_email=OPERATOR_EMAIL ), item,
                receipt_refs={ "operator_attestation": "rick" } )

    assert r.status_code == 200, r.text
    assert _recorded_receipts( repo ) == { "operator_attestation": "rick" }


def test_the_recorded_attestation_is_the_SERVERS_identity_not_the_callers_string( repo, settings ):
    """
    🔴 THE DISCRIMINATING ARM — a check whose result nothing consumes is not a check.

    A logged-in BYSTANDER, mapped to no approver persona, sends `"rick"`. The door
    lets them through (this is an identity gate, not an approver gate) and the ledger
    must record THEM, never the string they typed. Approving a value and then storing
    the caller's own value would leave the audit trail saying whatever they claimed.

    Without this arm, `_resolved_operator_attestation` could return its input and
    every other test in this file would still pass.
    """
    item = _item()
    repo.get_by_id_for_update.return_value = item
    repo.apply_transition.return_value = _event( item )

    r = _close( _client( account_email=BYSTANDER_MAIL ), item,
                receipt_refs={ "operator_attestation": "rick" } )

    assert r.status_code == 200, r.text
    recorded = _recorded_receipts( repo )[ "operator_attestation" ]
    assert recorded == BYSTANDER_MAIL, (
        f"the ledger recorded the caller's CLAIM instead of the server's answer: "
        f"{recorded!r}. A logged-in bystander just attested as somebody else."
    )
    assert recorded != "rick"


def test_the_callers_payload_is_not_mutated_under_them( repo, settings ):
    """
    The substitution builds a NEW dict. The payload is the record of what the caller
    SENT, and overwriting it in place would destroy the one artifact that
    distinguishes a claim from the server's ruling on it.
    """
    item = _item()
    repo.get_by_id_for_update.return_value = item
    repo.apply_transition.return_value = _event( item )
    sent = { "operator_attestation": "rick" }

    r = _close( _client( account_email=BYSTANDER_MAIL ), item, receipt_refs=dict( sent ) )

    assert r.status_code == 200, r.text
    assert _recorded_receipts( repo ) is not sent


# ---------------------------------------------------------------------------
# NEGATIVE CONTROLS — the agent-side rule must be exactly as hard as it was
# ---------------------------------------------------------------------------

def test_the_agent_receipt_rule_is_UNCHANGED_by_this_widening( repo, settings ):
    """
    The 9bfb4b73 refusal, re-asserted through the door after the closing set grew.
    A path-only receipt from an agent must still be refused, and refused by the RULES
    layer (422) rather than by the new identity gate (403) — the caller is not
    claiming an attestation, so the new door must not be what turns them away.
    """
    item = _item()
    repo.get_by_id_for_update.return_value = item

    r = _close( _client( account_email=None ), item,
                receipt_refs={ "doc_path": "lupin/CLAUDE.md" } )

    assert r.status_code == 422, (
        f"a path-only agent close was accepted — the widening leaked into the agent "
        f"path. Got {r.status_code}: {r.text}"
    )
    repo.apply_transition.assert_not_called()


def test_an_agent_closing_with_a_real_checkable_receipt_still_works( repo, settings ):
    """
    The other direction, so the file cannot degrade into "agents may not close rows".
    An API-key caller citing a test_run closes exactly as before this change.
    """
    item = _item()
    repo.get_by_id_for_update.return_value = item
    repo.apply_transition.return_value = _event( item )

    r = _close( _client( account_email=None ), item,
                receipt_refs={ "test_run": A_REAL_TEST_RUN } )

    assert r.status_code == 200, r.text
    assert _recorded_receipts( repo ) == { "test_run": A_REAL_TEST_RUN }


def test_a_transition_that_claims_nothing_is_untouched_by_the_new_gate( repo, settings ):
    """
    The gate must be silent on every request that does not claim an attestation.
    A gate that fires on every call would satisfy the refusal arm above while
    breaking the whole endpoint — the noise arm that makes the others mean something.
    """
    item = _item( status="queued" )
    repo.get_by_id_for_update.return_value = item
    repo.apply_transition.return_value = _event( item, transition="queued->in_progress" )

    r = _close( _client( account_email=None ), item, to_status="in_progress" )

    assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------
# The two properties kept apart on purpose
# ---------------------------------------------------------------------------

def test_the_attestation_is_sufficient_to_close_but_NOT_independently_checkable():
    """
    CHECKABLE and CLOSING are different sets, and collapsing them is the one-line
    version of this change that would have been wrong. Adding the attestation to
    CHECKABLE_RECEIPT_KEYS would silently redefine that constant — and with it the
    stated reason for the doc_path/log_line refusal, "something a third party can
    independently check".
    """
    assert rules.OPERATOR_ATTESTATION_KEY in rules.CLOSING_RECEIPT_KEYS
    assert rules.OPERATOR_ATTESTATION_KEY not in rules.CHECKABLE_RECEIPT_KEYS
    assert set( rules.CHECKABLE_RECEIPT_KEYS ).issubset( set( rules.CLOSING_RECEIPT_KEYS ) )


def test_a_reader_can_tell_an_operator_close_from_a_test_backed_one( repo, settings ):
    """
    María's constraint 1, and it falls out of the data model rather than out of a
    convention somebody has to remember: the KEY is the discriminator. A reader
    looking at a closed row cannot mistake one for the other.
    """
    item = _item()
    repo.get_by_id_for_update.return_value = item
    repo.apply_transition.return_value = _event( item )
    _close( _client( account_email=OPERATOR_EMAIL ), item,
            receipt_refs={ "operator_attestation": "rick" } )
    operator_close = _recorded_receipts( repo )

    repo.apply_transition.reset_mock()
    repo.apply_transition.return_value = _event( item )
    _close( _client( account_email=None ), item, receipt_refs={ "test_run": A_REAL_TEST_RUN } )
    test_backed_close = _recorded_receipts( repo )

    assert set( operator_close ) != set( test_backed_close )
    assert "operator_attestation" in operator_close
    assert "operator_attestation" not in test_backed_close
