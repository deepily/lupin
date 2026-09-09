"""
RICK ALONE PROMOTES AND DEMOTES — row c9fafb9d, driven through the REAL HTTP door.

His words, 2026-09-08 ~11:58 EDT, by keypress (answered=true, default_used=false):

    "Yes it is me and me alone not managers that gets to promote and demote task items
     into the live list and out of it back into the task area me alone. Only thing
     managers can do is request And there's requests default to no"

🔴 TWO CHECKS, NOT ONE, AND THIS FILE KEEPS THEM APART ON PURPOSE. He ruled PROMOTE and
DEMOTE in the same sentence, and the row they were split out of (1ec67228) spoke only
of promotion. A single test covering "the approver gate refuses a manager" would pass
with the demote clause deleted, because a demote reaches the gate down a different
branch — `requested_move` classifies it on `to_status`, not on `from_status`. Every arm
below therefore comes in a promote/demote pair.

🔴 AT THE DOOR, BECAUSE A DISABLED CONTROL IS PRESENTATION AND NOT A FIREWALL. The
client has carried a demote button since 9298715c and, until 2026-09-07, its only
restraint was JavaScript — anything posting straight to the API walked past it. So
these arms send an actual PATCH at the assembled app rather than calling the predicate.

⚠️ WHAT IS DELIBERATELY NOT ASSERTED HERE: the request path (Rick's third and fourth
rules). Its delivery mechanism was still being settled with Mr. Radio when this file
was written, and a guard written against a guess is worse than no guard — it would
freeze the guess. This file covers rules 1 and 2 only, and says so rather than implying
coverage it does not have.
"""

import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cosa.rest import task_approval_settings as approval
from cosa.rest import task_promotion_gate    as gate
from cosa.rest.postgres_models import TaskItem
from cosa.rest.routers import tasks
from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt, authenticated_account_email


NOW             = datetime( 2026, 9, 9, 0, 0, tzinfo=timezone.utc )
TRANSITION_PATH = "/api/tasks/{task_id}/transition"

MANAGER_ACTOR   = "mr radio 81381447"
OPERATOR_EMAIL  = "ricardo.felipe.ruiz@gmail.com"

# A login that maps to a MANAGER persona. Nothing in the shipped config maps one today —
# that is the measured state — so this address exists to ask the question the shipped
# config cannot: if somebody ever added a manager's email to the account map, what would
# the allowlist do about it? See `test_the_allowlist_is_a_SECOND_lock_...`.
MANAGER_EMAIL   = "mrradio@example.invalid"


# ---------------------------------------------------------------------------
# The world, declared rather than borrowed
# ---------------------------------------------------------------------------

class _FakeSession:
    """
    A session that records what was added and hands back the one row under test.

    ⚠️ `added` IS READ BY THE NEGATIVE ARMS. A refused caller must leave NOTHING behind
    — no promotion ticket, no half-written row — and "the response was a 403" does not
    say that on its own.
    """
    def __init__( self, item ):
        self.item  = item
        self.added = [ ]

    def add( self, obj ):    self.added.append( obj )
    def flush( self ):       pass
    def commit( self ):      pass
    def rollback( self ):    pass
    def get( self, model, pk, with_for_update=False ): return self.item
    def query( self, model ): return MagicMock()


def _item( status, **overrides ):
    fields = dict(
        id                  = uuid.uuid4(),
        item_class          = "task",
        title               = "a row somebody wants moved",
        body                = None,
        project             = "lupin",
        owner_persona       = "pocholo",
        accountable_manager = "mr radio",
        created_by          = MANAGER_ACTOR,
        status              = status,
        priority            = "P2",
        urgency             = "normal",
        created_ts          = NOW,
        updated_ts          = NOW,
    )
    fields.update( overrides )
    return TaskItem( **fields )


@pytest.fixture
def assembled_app():
    """
    The app with the task router mounted, and a guard that the door actually exists.

    A guard that cannot state its denominator is telling you about its corpus — so this
    asserts the route is mounted before any arm claims to have driven it.
    """
    app = FastAPI()
    app.include_router( tasks.router )
    paths = { getattr( r, "path", None ) for r in app.routes }
    assert TRANSITION_PATH in paths, (
        f"the assembled app has no {TRANSITION_PATH} route — {len( app.routes )} routes "
        f"were mounted. This guard cannot speak to a door that is not there."
    )
    return app


def _wire( monkeypatch, item, approvers, accounts ):
    """
    Point the router at a fake session and DECLARE the approval world.

    🔴 THE ALLOWLIST AND THE ACCOUNT MAP ARE BOTH STUBBED, BECAUSE THE GATE READS BOTH
    AND A TEST THAT STUBS ONE IS READING FLEET CONFIGURATION FOR THE OTHER. That is not
    hypothetical: `test_the_asynchronous_promotion_resolves_or_shouts.py` stubbed only
    the map, borrowed `task approval approver personas` from the live INI, and three of
    its arms went red at their setup the moment this row emptied that key — for a policy
    change with nothing to do with the asynchronous fork they guard.

    ⚠️ THE SHIPPED VALUE IS PINNED SEPARATELY, in
    `test_the_shipped_allowlist_delegates_to_nobody`. Declaring the world here proves
    the CODE enforces the rule; that one proves the CONFIG asks for it. Neither test
    can do the other's job, and a file carrying only the first would ship a correct gate
    wired to a list that still named three managers.
    """
    session = _FakeSession( item )
    repo    = MagicMock()
    repo.get_by_id_for_update.return_value  = item
    repo.count_admissions_since.return_value = 0

    @contextmanager
    def _fake_get_db():
        yield session

    monkeypatch.setattr( tasks, "get_db", _fake_get_db )
    monkeypatch.setattr( tasks, "TaskRepository", lambda s: repo )
    monkeypatch.setattr( approval, "get_enforcement_active", lambda: True )
    monkeypatch.setattr( approval, "get_approvers",         lambda: frozenset( approvers ) )
    monkeypatch.setattr( approval, "get_approver_accounts", lambda: dict( accounts ) )
    # The promotion ask is a LIVE HUMAN SURFACE. Left unstubbed, a passing positive arm
    # would mean a notification actually went at Rick. Stubbed to allow, so what these
    # arms measure is the APPROVER gate rather than his patience.
    monkeypatch.setattr( gate, "approval_for_promotion", lambda **k:
                         gate.PromotionApproval( allowed=True,
                                                 approval_source=gate.APPROVAL_SELF ) )
    return session, repo


def _client( app, account_email ):
    app.dependency_overrides[ require_api_key_or_jwt ]      = lambda: "test-user"
    app.dependency_overrides[ authenticated_account_email ] = lambda: account_email
    return TestClient( app )


def _move( client, item, to_status, **extras ):
    """
    Drive the real door.

    ⚠️ POST, NOT PATCH, AND THIS COST A ROUND OF RED. The first cut of this file sent
    PATCH — the verb every neighbouring approval endpoint uses — and got 405 back from
    all six negative arms. The two POSITIVE arms PASSED anyway, because they asserted
    `!= 403` and a 405 satisfies that: an assertion satisfiable by more than one path
    cannot tell you which one ran. That is why they now name the status they expect.
    """
    body = {
        "to_status" : to_status,
        "actor"     : MANAGER_ACTOR,
        "authority" : "standing",
        # 🔴 A REASON ON EVERY ARM, INCLUDING THE PROMOTES THAT DO NOT NEED ONE, AND
        # THE UNIFORMITY IS THE POINT. `validate_transition` REQUIRES a non-blank
        # reason for a demote — "a demote whose justification is not written down is
        # indistinguishable from a row that was never approved" — and it runs BEFORE
        # the approver gate, shape first and policy second. So the first cut of this
        # file got 422 on all four demote arms and never reached the policy it exists
        # to measure. A negative arm refused for the WRONG reason is a guard that
        # reddens when the gate is deleted, which is the failure it must not have.
        "reason"    : "a guard driving the real door",
    }
    body.update( extras )
    return client.post( f"/api/tasks/{item.id}/transition", json=body )


# The two moves Rick named, as data, so every arm below runs BOTH and no arm can quietly
# cover one of them. `(label, from_status, to_status)`.
PROMOTE = ( "promote", approval.NOT_APPROVED_STATUS, "queued" )
DEMOTE  = ( "demote",  "queued", approval.NOT_APPROVED_STATUS )
BOTH    = [ PROMOTE, DEMOTE ]

RICK_ONLY   = ( { "rick" }, { OPERATOR_EMAIL: "rick" } )
# The world BEFORE this row: managers delegated, and a manager's login mapped.
OLD_WORLD   = ( { "rick", "mr radio", "cheech", "maria" },
                { OPERATOR_EMAIL: "rick", MANAGER_EMAIL: "mr radio" } )
# This row's world, with the SAME manager login mapped — so the two differ in the
# allowlist and in nothing else.
NEW_WORLD   = ( { "rick" }, { OPERATOR_EMAIL: "rick", MANAGER_EMAIL: "mr radio" } )


# ---------------------------------------------------------------------------
# The isolation control FIRST — a green file must not also be consistent with
# these arms reading the live fleet settings.
# ---------------------------------------------------------------------------

def test_the_isolation_actually_isolates( monkeypatch ):
    _wire( monkeypatch, _item( "queued" ), *OLD_WORLD )
    assert approval.get_approvers() == frozenset( OLD_WORLD[ 0 ] )
    assert approval.get_approver_accounts() == OLD_WORLD[ 1 ]


# ---------------------------------------------------------------------------
# RULE 1 and RULE 2 — a manager is refused BOTH moves
# ---------------------------------------------------------------------------

@pytest.mark.parametrize( "label,frm,to", BOTH )
def test_a_manager_with_no_login_account_is_refused_both_moves(
    assembled_app, monkeypatch, label, frm, to
):
    """
    The API-key caller — every agent seat. `actor` is caller-DECLARED, so this is the
    arm that would catch the actor door being "restored" as an authorization check.
    """
    item             = _item( frm )
    session, _       = _wire( monkeypatch, item, *RICK_ONLY )
    response         = _move( _client( assembled_app, None ), item, to )

    assert response.status_code == 403, f"{label} was not refused for an account-less manager"
    assert session.added == [ ], f"a refused {label} left something behind on the session"


@pytest.mark.parametrize( "label,frm,to", BOTH )
def test_a_login_that_maps_to_nobody_is_refused_both_moves(
    assembled_app, monkeypatch, label, frm, to
):
    """
    A REAL, signature-validated login that the account map does not know. Distinct from
    the arm above, and the distinction is the one Rick's b8205986 ruling turned on:
    "require a real account" was rejected as too weak precisely because having ANY login
    must not be the qualification.
    """
    item       = _item( frm )
    session, _ = _wire( monkeypatch, item, *RICK_ONLY )
    response   = _move( _client( assembled_app, "someone.else@example.invalid" ), item, to )

    assert response.status_code == 403, f"{label} was allowed for an unmapped login"
    assert session.added == [ ]


# ---------------------------------------------------------------------------
# THE POSITIVE ARMS — without these the file proves only that the door can say no
# ---------------------------------------------------------------------------

@pytest.mark.parametrize( "label,frm,to", BOTH )
def test_RICKS_OWN_account_makes_both_moves( assembled_app, monkeypatch, label, frm, to ):
    """
    🔴 THE ARM THAT MAKES EVERY REFUSAL ABOVE MEAN SOMETHING. A gate that refuses
    everybody is indistinguishable, from the outside, from a gate that refuses the right
    people — and it would be a P0 of its own, because it would lock Rick out of his own
    board. That has happened here before: row 9d3a975e, where the approver gate had
    never been shown the authenticated account and he could not approve anything.
    """
    item     = _item( frm )
    _wire( monkeypatch, item, *RICK_ONLY )
    response = _move( _client( assembled_app, OPERATOR_EMAIL ), item, to )

    # 200 BY NAME, not `!= 403`. A negative assertion here is satisfied by a 404, a 405
    # or a 500 — this file's first cut asserted exactly that and passed against a 405
    # from the wrong HTTP verb, while every negative arm was correctly red.
    assert response.status_code == 200, (
        f"Rick's own account did not complete a {label}: "
        f"{response.status_code} {response.json()}"
    )


# ---------------------------------------------------------------------------
# THE ALLOWLIST IS LOAD-BEARING — two arms that differ in one value
# ---------------------------------------------------------------------------

@pytest.mark.parametrize( "label,frm,to", BOTH )
def test_the_allowlist_is_a_SECOND_lock_and_not_decoration(
    assembled_app, monkeypatch, label, frm, to
):
    """
    🔴 WHY THIS ARM EXISTS AT ALL. Emptying `task approval approver personas` changes NO
    behaviour against the shipped account map, because that map names exactly one email
    and it is Rick's — measured 2026-09-09. A test written only against today's config
    would therefore pass identically with the config change reverted, which makes it a
    test of nothing.

    ⇒ So this arm gives BOTH worlds the same manager login and differs in the allowlist
    ALONE. Under the old list that login promotes and demotes; under Rick's ruling it
    does neither. That is the lock the config line actually buys: adding a manager's
    email to the account map now fails closed instead of quietly granting.
    """
    old_item          = _item( frm )
    _wire( monkeypatch, old_item, *OLD_WORLD )
    before = _move( _client( assembled_app, MANAGER_EMAIL ), old_item, to )

    new_item          = _item( frm )
    _wire( monkeypatch, new_item, *NEW_WORLD )
    after  = _move( _client( assembled_app, MANAGER_EMAIL ), new_item, to )

    assert before.status_code == 200, (
        f"the BEFORE arm did not reproduce the old permission, so the AFTER arm's 403 "
        f"proves nothing about the allowlist: {before.status_code} {before.json()}"
    )
    assert after.status_code == 403, (
        f"a manager login still {label}s with the allowlist narrowed to Rick alone"
    )


def test_the_second_lock_refuses_BY_THE_LIST_and_not_by_the_account_door( monkeypatch ):
    """
    🔴 THE ARM ABOVE PROVES A 403 APPEARS; THIS ONE PROVES WHICH CHECK PRODUCED IT.
    Mr. Radio 🦉 raised it, 2026-09-09, and he is right: a status code is satisfiable by
    more than one path, so `after.status_code == 403` is also consistent with the ACCOUNT
    door having refused — if the mapping were dropped from the fixture, that arm would
    stay green while the allowlist did nothing at all. An assertion satisfiable by more
    than one path cannot tell you which one ran, and this file has already been bitten
    by exactly that once (see `_move`, where a 405 satisfied a `!= 403`).

    ⇒ SO THIS NAMES THE PATH, in three assertions that only the allowlist can satisfy
    together:

      1. the ACCOUNT DOOR STILL HAS SOMETHING TO ADMIT — the map resolves the manager's
         email to a persona, so it is not an unmapped-login refusal wearing the same 403;
      2. `approver_persona_for_account` nevertheless returns None. Given (1), the ONLY
         remaining statement in that function that can produce None is
         `if persona not in get_approvers(): return None`;
      3. and the SAME call with the same map returns the persona under the OLD list. That
         is the discriminator: the two calls differ in the allowlist and in nothing else,
         so the None in (2) is attributable to the list rather than to the mapping, the
         email, or the persona spelling.

    ⚠️ IT DELIBERATELY DOES NOT DRIVE THE HTTP DOOR. The door is where the arm above
    belongs, because that is where a control has to actually refuse. This one asks which
    of the two locks turned, and the answer is only observable at the function that holds
    both — the router sees one verdict and cannot say where it came from.
    """
    # -- NEW WORLD: the manager's email is mapped, and the list no longer names them --
    _wire( monkeypatch, _item( "queued" ), *NEW_WORLD )

    mapped = approval.get_approver_accounts()
    assert mapped.get( MANAGER_EMAIL ) == "mr radio", (
        "the fixture's manager email is not in the account map, so a refusal here would "
        "be the ACCOUNT door and this arm would be measuring the wrong lock"
    )
    assert "mr radio" not in approval.get_approvers(), (
        "the new world still lists the manager as an approver — the arm below would then "
        "be asserting nothing"
    )
    assert approval.approver_persona_for_account( MANAGER_EMAIL ) is None, (
        "the account resolved to an approver persona even though the allowlist does not "
        "name it — the second lock did not fire"
    )

    # -- OLD WORLD: same map, same email, same persona spelling; only the list differs --
    _wire( monkeypatch, _item( "queued" ), *OLD_WORLD )

    assert approval.get_approver_accounts().get( MANAGER_EMAIL ) == "mr radio", (
        "the two worlds differ in the account map as well as the allowlist, so the "
        "comparison below is not attributable to the list"
    )
    assert approval.approver_persona_for_account( MANAGER_EMAIL ) == "mr radio", (
        "the old allowlist did not resolve this account either, so the None above is not "
        "evidence about the list — it is evidence about something both worlds share"
    )


# ---------------------------------------------------------------------------
# THE SHIPPED CONFIG — the deliverable itself, not a model of it
# ---------------------------------------------------------------------------

def test_the_shipped_allowlist_delegates_to_nobody():
    """
    🔴 THIS ONE READS THE REAL CONFIGURATION ON PURPOSE, AND IT IS THE ONLY ARM THAT
    DOES. Rules 1 and 2 ship as a CONFIG change; every arm above declares its own world
    and so would pass unchanged against a list that still delegated to three managers.
    Somebody has to look at what is actually shipping.

    ⚠️ IT ASKS THE GATE RATHER THAN READING THE INI. `get_approvers()` is what the door
    consults, and it folds in the unconditional set, the override file and the INI key.
    Parsing the file here would be a second implementation of that rule — and it would
    miss the very thing worth asserting, that emptying the key leaves exactly ONE
    approver rather than none.
    """
    approvers = approval.get_approvers()

    assert approvers == frozenset( { "rick" } ), (
        f"the shipped approver allowlist is {sorted( approvers )}. Rick ruled 2026-09-08 "
        f"that he alone promotes and demotes; anyone else here is a live delegation he "
        f"withdrew. The sanctioned change is PATCH /api/tasks/approval-settings."
    )
    assert approvers == frozenset( approval.UNCONDITIONAL_APPROVERS ), (
        "the allowlist no longer equals the unconditional set, which means the emptied "
        "INI key is not what is producing this result — read the override file."
    )
