#!/usr/bin/env python3
"""
THE AUDIT TRAIL NAMES A PERSON, NOT A PER-SESSION GOAT.

Row 77f4e1d3, María's ruling 2026-09-04: "Correct the attribution so the edit door
records the real identity the P0 mechanism establishes. Leave the 404 behavior exactly
as it is."

WHAT WAS ACTUALLY WRONG, AND IT IS BIGGER THAN ONE DOOR. `task_approval_settings`'s
docstring claims "The authenticated user id IS recorded alongside, so a false claim is
attributable after the fact." Measured at `3862c0b9`: `authenticated_user_id` is bound
in `routers/tasks.py` TWELVE times and read in no function body. Bound everywhere, used
nowhere. The store's accountability rested on a sentence.

⚠️ THIS FILE GUARDS ATTRIBUTION AND NOTHING ELSE. The edit door still refuses nobody —
its only `HTTPException` is a 404 — and `test_the_edit_door_still_refuses_nobody` below
pins that, so a future gate arrives as a deliberate ruling rather than as drift. Whether
it SHOULD refuse is written up as a proposal for Rick, not decided here.

THE EXTRACTOR (DONE MEANS #3). The actor is read out of the SHIPPED CLIENT at test time
rather than hand-written here, so the guard follows whatever the client does. ⚠️ Its
positive control is not decoration: an extractor that finds ZERO call sites passes every
per-site assertion in the loop that follows, because a loop over nothing is green. It
asserts the COUNT first.
"""
import os
import re
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
from cosa.rest import task_actor_identity as identity
from cosa.rest.postgres_models import TaskItem, TaskEvent
from cosa.rest.routers import tasks
from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt, authenticated_account_email

import cosa.utils.util as cu

NOW            = datetime( 2026, 9, 4, tzinfo=timezone.utc )
OPERATOR_EMAIL = "the.operator@example.com"
SEAT_ACTOR     = "rio 0e3c5bd3"

_CLIENT = os.path.join( cu.get_project_root(), "src", "lupin_app", "static", "js",
                        "notifications.js" )


# ─────────────────────── the extractor + its positive control ────────────────


def _client_actor_expressions():
    """
    Every actor string the shipped client sends, read from the client itself.

    Deliberately NOT narrowed to one method: this row exists because there are TWO
    call sites and a guard narrowed to one could not see the other. Maya found the
    second only because a mutation harness refused to apply — "ANCHOR MATCHED 2x —
    NOT APPLIED" — and read it instead of counting it.
    """
    with open( _CLIENT, "r" ) as handle:
        source = handle.read()
    return re.findall( r"actor\s*:\s*`([^`]*)`", source )


def test_the_extractor_finds_BOTH_doors_before_anything_else_is_claimed():
    """
    🔴 THE POSITIVE CONTROL. Without it, every per-site assertion below is satisfied by
    an empty list, and a moved file or a changed quoting style would turn this whole
    file green while guarding nothing.
    """
    found = _client_actor_expressions()
    assert len( found ) >= 2, (
        f"expected at least the two known actor call sites (_editTask PATCH and "
        f"_transitionTask POST); the extractor found {len( found )}: {found}. "
        f"Either the client moved, its quoting changed, or this guard is now blind."
    )


def test_every_actor_the_client_sends_is_still_the_per_session_string():
    """
    The premise this whole row rests on, asserted rather than assumed — and it is a
    statement about TODAY, not a wish. The client keeps minting a per-websocket-session
    actor; the SERVER is what upgrades it. If the client is ever fixed to send a real
    identity, this reddens and the fix below can be reconsidered rather than silently
    becoming redundant.
    """
    found = _client_actor_expressions()
    assert found, "extractor found nothing — see the positive control above"
    for expr in found:
        assert "queueSessionId" in expr, (
            f"a client actor no longer derives from the websocket session: {expr!r}. "
            f"That may be good news, but this guard's premise changed — re-read it."
        )


# ─────────────────────────── the server-side upgrade ─────────────────────────


def _item( **overrides ):
    fields = dict(
        id                  = uuid.uuid4(),
        item_class          = "bug",
        title               = "a row somebody edits from a browser",
        body                = None,
        project             = "lupin",
        owner_persona       = "rio",
        accountable_manager = "maria",
        created_by          = "maria 4f98d12f",
        status              = "queued",
        blocked_by          = [ ],
        next_chase_ts       = None,
        gate_class          = "none",
        priority            = "P2",
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
    """The approval module's override file inside tmp_path. The INI is never read."""
    target = tmp_path / "task-approval-settings.json"
    monkeypatch.setattr( approval, "override_path", lambda: str( target ) )
    monkeypatch.setattr( approval, "_cache", {
        "approvers": None, "enforcement_active": None,
        "default_to_holding": None, "approver_accounts": None,
    } )
    monkeypatch.setattr( approval, "_cache_mtime", None )
    target.write_text( '{"approvers": ["maria"], "enforcement_active": true, '
                       '"approver_accounts": {"%s": "maria"}}' % OPERATOR_EMAIL )
    approval._cache_mtime = None
    return target


def _client( account_email ):
    app = FastAPI()
    app.include_router( tasks.router )
    app.dependency_overrides[ require_api_key_or_jwt ]      = lambda: "test-user"
    app.dependency_overrides[ authenticated_account_email ] = lambda: account_email
    return TestClient( app )


def _patch( account_email, repo, actor ):
    item = _item()
    repo.get_by_id_for_update.return_value = item
    # `apply_patch` returns the EVENT alone — read off the call site at
    # tasks.py:1330 rather than guessed. A tuple here made three tests fail inside
    # the router's serializer, which looks like a defect in the door and is not.
    repo.apply_patch.return_value = TaskEvent(
        id=1, item_id=item.id, ts=NOW, actor=actor,
        transition="patched", receipt_refs=None, authority="user_direct",
    )
    repo.apply_patch.reset_mock()
    r = _client( account_email ).patch(
        f"/api/tasks/{item.id}",
        json={ "priority": "P1", "actor": actor, "authority": "user_direct" } )
    return r, repo.apply_patch


def test_a_browser_edit_is_recorded_under_the_PERSON_not_the_session( repo, settings ):
    """
    🔴 THE ONE THIS FILE EXISTS FOR. The client sends its goat; the ledger names a human.
    """
    r, called = _patch( OPERATOR_EMAIL, repo, "operator foolish goat" )

    assert r.status_code == 200, r.text
    written = called.call_args.kwargs.get( "actor" )
    assert written == "maria (operator foolish goat)", (
        f"the edit door recorded {written!r} — the audit trail still names a "
        f"per-session string instead of the authenticated account (row 77f4e1d3)"
    )


def test_a_SEAT_is_recorded_exactly_as_it_declared( repo, settings ):
    """
    THE NEGATIVE CONTROL, AND IT IS NOT OPTIONAL. One variable moves against the test
    above — whether there is a login account. Without this arm, a change that rewrote
    EVERY actor unconditionally would pass, and the whole fleet's audit trail would be
    rewritten by a bug fix.
    """
    r, called = _patch( None, repo, SEAT_ACTOR )

    assert r.status_code == 200, r.text
    assert called.call_args.kwargs.get( "actor" ) == SEAT_ACTOR, (
        "an API-key caller's declared actor was rewritten — API-key callers have no "
        "login account and must be untouched"
    )


def test_the_edit_door_still_refuses_nobody( repo, settings ):
    """
    MARÍA'S RULING, PINNED: "leave the 404 behavior exactly as it is."

    A logged-in stranger — an account mapped to no approver at all — still edits. This
    is the arm that would catch attribution work quietly growing a gate, which is the
    thing she explicitly did not authorise.
    """
    r, called = _patch( "a.total.stranger@example.com", repo, "operator wise penguin" )

    assert r.status_code == 200, (
        f"the edit door has started REFUSING somebody (got {r.status_code}). That is "
        f"new policy and it is Rick's ruling, not a side effect of attribution."
    )
    called.assert_called_once()


# ───────────────────────────── the helper's own edges ────────────────────────


def test_an_account_nobody_mapped_is_still_named():
    """
    Attribution is not a privilege. An account that can approve nothing is precisely the
    one whose edits you most want traceable, so it is recorded under its own address.
    """
    assert identity.identity_for_account( "nobody@example.com" ) == "nobody@example.com"


def test_an_api_key_caller_has_no_identity_to_record():
    assert identity.identity_for_account( None ) is None
    assert identity.identity_for_account( "   " ) is None


def test_an_overlong_pair_drops_the_DECLARED_half_and_says_so():
    """
    `task_events.actor` is String(255) and a declared actor may already be 255, so any
    prefix can overflow. The identity is the load-bearing half and is never what gets
    cut — and the cut is ANNOUNCED, because a silently clipped string is
    indistinguishable from one somebody typed that way.
    """
    written = identity.recorded_actor( "x" * 250, "nobody@example.com" )
    assert len( written ) <= identity.ACTOR_COLUMN_LIMIT
    assert written.startswith( "nobody@example.com" )
    assert identity.ELIDED_MARKER in written


def test_an_identity_that_cannot_fit_declines_rather_than_writing_a_half_name():
    """
    A truncated identity is worse than an un-upgraded one: it would name a person who
    does not exist. The step that cannot finish declines and hands back the caller's
    own string.
    """
    huge = "a" * 300 + "@example.com"
    assert identity.recorded_actor( "operator foolish goat", huge ) == "operator foolish goat"
