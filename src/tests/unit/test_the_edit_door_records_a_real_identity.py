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
import functools
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
from cosa.rest import task_promotion_gate as promotion_gate


# ── THE ASK SEAM (row e625e608) ──────────────────────────────────────────────
#
# Tests in this file drive the transition door with a TestClient, and that door
# calls `approval_for_promotion`, whose default `ask_fn` is the LIVE HUMAN
# SURFACE. Before the containment guard existed, running this file fired real
# yes/no prompts at Rick — this file was one of the sources of the 2026-09-04
# incident, and it had no stub of any kind.
#
# 🔴 WHY A `functools.partial` AND NOT `monkeypatch.setattr( gate, "_default_ask", … )`.
# `approval_for_promotion( …, ask_fn=_default_ask )` binds that default AT
# DEFINITION TIME, so patching the module attribute leaves the bound default in
# place and the test believes it stubbed something it did not. Rio measured that.
# Binding `ask_fn` onto the function the router calls is the seam the gate
# actually documents, and it keeps the REAL gate logic — the account door these
# tests exist to exercise — under test. Only the ask is replaced.
@pytest.fixture( autouse=True )
def _no_live_ask( monkeypatch ):
    """
    Answer the promotion ask in-process so no test here can reach a person.

    Ensures:
        - `approval_for_promotion` runs for real, with only its `ask_fn` replaced
        - the fake answers "yes" as a HUMAN keypress (`default_used=False`), which
          is the case these tests were written against
        - autouse, because a test in this file that forgets it fires a real prompt
          at a person — the one failure mode worth a blanket default
    """
    def _fake_ask( **kwargs ):
        return promotion_gate.AskOutcome( answer="yes", default_used=False )

    monkeypatch.setattr(
        tasks.promotion_gate, "approval_for_promotion",
        functools.partial( promotion_gate.approval_for_promotion, ask_fn=_fake_ask ) )

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


@pytest.fixture( autouse=True )
def _the_promotion_ask_never_leaves_this_process( monkeypatch ):
    """
    Answer the promotion gate's ask IN-PROCESS, so nothing in this file fires a live
    prompt at a human.

    🔴 THIS FILE FIRED REAL YES/NO CARDS AT RICK AND NOTHING IN THE TEST OUTPUT SAID
    SO (row 1544d51e). One test below drives `not_approved -> queued` with
    `enforcement_active=True` — exactly the condition `approval_for_promotion` asks
    on. Nothing here stubbed the ask, so the gate fell through to its REAL default:
    `_default_ask` -> `notify_user_sync` -> `POST http://localhost:7999/api/notify`
    -> a live card in Rick's browser, `human_only=True`, 120 seconds to answer.
    Measured 2026-09-04 off the `:7999` container log: 20 promotion asks, 20 DISTINCT
    row ids, every one carrying a fixture title from this file or its sibling. He
    answered them believing a promotion control was double-firing.

    ⚠️ THE TEST PASSED EITHER WAY, WHICH IS WHY IT SURVIVED REVIEW. A human "yes" and
    a 120-second timeout BOTH return allowed, so the assertion was green whether Rick
    answered, ignored it, or was asleep. The only symptom was two minutes of wall
    clock nobody attributed to a test — and on a suite this size nobody would.

    ⚠️ PATCHED AT `notify_user_sync`, NOT AT `_default_ask`, AND THE DIFFERENCE IS
    LOAD-BEARING. `approval_for_promotion` binds `ask_fn=_default_ask` as a DEFAULT
    ARGUMENT, evaluated once at def time — so monkeypatching the module attribute
    `_default_ask` does not reach the caller that matters. `_default_ask` imports
    `notify_user_sync` INSIDE its body, so THAT name resolves at call time and is the
    one seam a test can move. `test_the_default_ask_path_is_exercised_not_injected_past.py`
    patches the same string for the same reason.

    ⚠️ AND IT DELIBERATELY LEAVES THE GATE'S REAL LOGIC RUNNING. Stubbing
    `approval_for_promotion` outright would be one line shorter and would stop these
    tests exercising the manager check, the answer parsing and the attribution suffix
    — the things this file is actually about. Only the outbound call is replaced, so
    what is under test is unchanged and only the live surface is gone.

    Ensures:
        - no test in this file can reach the live notification surface
        - the gate still runs its real credential and answer-parsing logic
        - the answer is a keypress "yes", matching a present Rick rather than a
          timed-out default, so `approval_source` stays the non-degenerate value
    """
    class _Answer:
        """The two fields `_default_ask` reads off a NotificationResponse."""
        response_value = "yes"
        default_used   = False
        # ⚠️ exit_code MODELS THE REAL RESPONSE AND IS NOT DECORATION (row 96d2341c).
        # `notify_user_sync` returns rather than raises on a transport failure, and 0
        # vs 1 is the ONLY thing separating "a human answered" from "we never reached
        # one". A fake without it cannot represent a failed ask at all, which is why a
        # broken ask was recorded as Rick's keypress for as long as it was.
        exit_code      = 0
        status         = "responded"

    def _answered_in_process( request, **kwargs ):
        return _Answer()

    monkeypatch.setattr(
        "lupin_cli.notifications.notify_user_sync.notify_user_sync",
        _answered_in_process
    )


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


def test_the_TRANSITION_door_records_a_person_too( repo, settings ):
    """
    🔴 THE GATE READ THE TOKEN; THE LEDGER DID NOT.

    Door 1 (row 9d3a975e) let Rick through on his authenticated account and then wrote
    the event under "operator foolish goat" — the exact string the gate had just
    declined to trust. Two doors, one defect, and the second half was invisible because
    an approval that SUCCEEDS produces no error for anyone to chase.

    ⚠️ Added after measuring that the whole approval + router + guard suite — 285 tests
    — went green with the transition door still recording the goat. A fix nothing
    reddens for is a fix nobody will notice reverting.
    """
    item = _item( status="not_approved" )
    repo.get_by_id_for_update.return_value = item
    repo.apply_transition.return_value = TaskEvent(
        id=1, item_id=item.id, ts=NOW, actor="x",
        transition="not_approved->queued", receipt_refs=None, authority="user_direct",
    )
    repo.apply_transition.reset_mock()

    r = _client( OPERATOR_EMAIL ).post(
        f"/api/tasks/{item.id}/transition",
        json={ "to_status": "queued", "actor": "operator foolish goat",
               "authority": "user_direct" } )

    assert r.status_code == 200, r.text
    written = repo.apply_transition.call_args.kwargs.get( "actor" )
    assert written == "maria (operator foolish goat)", (
        f"the transition door recorded {written!r} — an approval that passed on the "
        f"authenticated account is still attributed to a per-session string"
    )


def test_a_SEAT_transition_is_recorded_exactly_as_it_declared( repo, settings ):
    """
    The negative control for the door above. One variable — whether there is a login
    account. Without it, a change that rewrote every transition actor unconditionally
    would pass, and every seat's audit history would be rewritten by a bug fix.
    """
    item = _item( status="queued" )
    repo.get_by_id_for_update.return_value = item
    repo.apply_transition.return_value = TaskEvent(
        id=1, item_id=item.id, ts=NOW, actor="x",
        transition="queued->in_progress", receipt_refs=None, authority="standing",
    )
    repo.apply_transition.reset_mock()

    r = _client( None ).post(
        f"/api/tasks/{item.id}/transition",
        json={ "to_status": "in_progress", "actor": SEAT_ACTOR, "authority": "standing" } )

    assert r.status_code == 200, r.text
    assert repo.apply_transition.call_args.kwargs.get( "actor" ) == SEAT_ACTOR


# ─────────────── every WRITE door, because the claim was about all of them ───


# The two mutating routes that write NO task-store row and therefore owe no actor.
# Named with the reason, so a future reader can refute the exemption rather than
# inherit it: both edit the flow-ratio OPERATOR SETTINGS file, not an item.
NOT_STORE_WRITERS = { "patch_flow_ratio_settings", "delete_flow_ratio_settings" }


def _mutating_handlers():
    """Every write-method handler on the router, DERIVED rather than hand-listed."""
    names = set()
    for route in tasks.router.routes:
        methods = getattr( route, "methods", set() ) or set()
        if methods & { "POST", "PATCH", "PUT", "DELETE" }:
            names.add( route.endpoint.__name__ )
    return names


def _body_of( handler_name ):
    import inspect
    source = inspect.getsource( tasks )
    return source.split( f"def {handler_name}(" )[ 1 ].split( "\n@router." )[ 0 ]


def test_the_census_DERIVES_its_own_population_and_is_not_empty():
    """
    🔴 THE ARM THAT CAUGHT MY OWN GUARD BEING VACUOUS.

    My first cut hand-listed the five write doors. A mutation that emptied that set
    SURVIVED — the loop below iterated nothing and went green, which is this repo's
    empty-corpus failure reproduced inside the guard written against it.

    ⇒ The population is now derived from the ROUTER, so a write door added tomorrow is
    in it whether or not anybody remembers this file. And the count is asserted BEFORE
    anything iterates, because a derived list can be empty too.
    """
    handlers = _mutating_handlers()
    assert len( handlers ) >= 7, (
        f"the router reports only {len( handlers )} mutating handlers: {sorted( handlers )}. "
        f"A shrunken population passes every assertion in the loop below."
    )
    store_writers = handlers - NOT_STORE_WRITERS
    assert len( store_writers ) >= 5, (
        f"only {len( store_writers )} store-writing doors discovered: {sorted( store_writers )}"
    )


@pytest.mark.parametrize( "door", sorted( _mutating_handlers() - NOT_STORE_WRITERS ) )
def test_a_derived_write_door_attributes( door ):
    """
    `authenticated_user_id` was bound 12x in this router and read 0x, which made
    `task_approval_settings.py:23`'s accountability sentence false.

    ⚠️ "12 broken doors" OVER-STATES IT, and the honest number is smaller: 7 of the 12
    are READS, and an unused binding on a read is CORRECT — the dependency's whole job
    there is to refuse an unauthenticated caller, and it does that by existing. Only
    the WRITE doors owe attribution. Inflating the count would have been the overclaim.

    🔴 PARAMETRIZED, NOT A LOOP, AND THAT IS NOT A STYLE CHOICE. A single test looping
    the doors gives every regression the SAME test id, so three different doors
    breaking produce one identical failing set — and this repo's rule is that a failing
    set has to carry information rather than collapse several reasons into one id. Each
    door now reddens under its own name: `…[create_task]`, `…[amend_task]`.

    ⚠️ The parametrize list is DERIVED at collection time, so a write door added
    tomorrow gets its own case without anyone editing this file. Its non-emptiness is
    asserted separately above — a parametrize over an empty list collects zero tests
    and reports green, which is the same vacuum one level up.
    """
    assert "recorded_actor(" in _body_of( door ), (
        f"{door} WRITES to the task store and still records a caller-declared "
        f"string — the defect behind `authenticated_user_id` bound 12x, read 0x"
    )


# Every method on TaskRepository that WRITES. Derived by reading the repository's own
# surface, not by pattern-guessing names — my first sweep guessed and missed two.
REPO_WRITE_METHODS = (
    "create_item", "apply_transition", "apply_correlation", "apply_amendment", "apply_patch",
)


def test_the_route_derived_census_agrees_with_a_REPO_derived_one():
    """
    🔴 THE GAP A ROUTE-DERIVED CENSUS CANNOT SEE ON ITS OWN: a handler that writes to
    the store without being a POST/PATCH/PUT/DELETE route would never enter the
    population, and the census would report complete while missing a door.

    ⇒ So the population is derived a SECOND time, by a genuinely different route — which
    handlers call a repository WRITE method — and the two are required to agree. The
    provenances are independent: one reads the ASGI route table's HTTP methods, the
    other reads the source for repository calls. A disagreement is real information in
    both directions: a write door with no write method, or a write method behind a door
    the route table calls a read.

    ⚠️ This is NOT the tautology CLAUDE.md warns about, and the difference is worth
    stating because the shapes look alike. A tautology is two sides sharing ONE source
    so they cannot disagree. These two share nothing — kill either derivation and the
    other still produces its own answer.

    ⚠️ AND IT IS NOT A COINCIDENCE-CHECK EITHER: the condition that would make them
    differ is a write path that is not an HTTP route, which is a thing that can happen
    and is exactly what this asserts has not.
    """
    import inspect
    source = inspect.getsource( tasks )

    from_repo_calls = set()
    for handler in _mutating_handlers() | { "query_tasks", "get_task", "get_task_events" }:
        body = source.split( f"def {handler}(" )[ 1 ].split( "\n@router." )[ 0 ]
        if any( f"repo.{m}(" in body for m in REPO_WRITE_METHODS ):
            from_repo_calls.add( handler )

    assert from_repo_calls, (
        "the repo-derived population is EMPTY — that is a broken derivation, not a "
        "clean bill of health, and it would agree with anything"
    )
    from_routes = _mutating_handlers() - NOT_STORE_WRITERS
    assert from_repo_calls == from_routes, (
        f"the two derivations disagree.\n"
        f"  route-derived : {sorted( from_routes )}\n"
        f"  repo-derived  : {sorted( from_repo_calls )}\n"
        f"Either a write door is not an HTTP write route, or a route the table calls a "
        f"write does not write. Both are findings."
    )


def test_no_repository_write_method_is_reachable_without_being_censused():
    """
    The repository exposes `apply_chase`, which no router calls today — so it is a write
    path with no HTTP door and nothing to attribute. Asserted rather than assumed,
    because the day something exposes it, it inherits this defect on day one and the
    census above would not notice: it only looks at handlers that already exist.
    """
    import inspect
    source = inspect.getsource( tasks )
    assert "repo.apply_chase(" not in source, (
        "a router now calls apply_chase — it is a store WRITE and owes attribution, "
        "so add it to REPO_WRITE_METHODS and give its door the helper"
    )


def test_a_READ_door_correctly_attributes_nothing():
    """
    The other direction, and it is what stops "attribute everything" from passing. A
    read owes no actor, and a census that demanded one everywhere would be as wrong as
    one that demanded it nowhere.
    """
    body = _body_of( "query_tasks" )
    assert "recorded_actor(" not in body
    assert len( body ) > 200, "the slice came back implausibly short — check the split"


def test_the_flow_ratio_settings_exemption_is_real_and_not_a_shrug():
    """
    An exemption list is where a census goes to die, so this one is checked rather than
    trusted: both exempt handlers must genuinely be on the router, and must genuinely
    not write a store row.
    """
    handlers = _mutating_handlers()
    for name in NOT_STORE_WRITERS:
        assert name in handlers, f"exemption names {name}, which is not a route at all"
        body = _body_of( name )
        assert "repo." not in body, (
            f"{name} is exempted as a non-store-writer but touches a repository"
        )


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
