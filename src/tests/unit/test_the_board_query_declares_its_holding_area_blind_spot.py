"""
Row d254c397 — an un-status'd board query withholds `not_approved` rows and must SAY SO,
and the terse projection must be able to answer "is this mine".

=== THE DEFECT, AND WHY THE SILENCE IS THE DEFECT RATHER THAN THE FILTER ===

`BOARD_INVISIBLE_STATUSES` is TERMINAL plus the holding area, so excluding `not_approved`
from an un-status'd query is DELIBERATE — read in the repository, not inferred. What is not
deliberate is that nothing says so. The result carries no count of what was filtered, no
warning, no hint that a status class was withheld: it returns a clean list and reads as
"this is what you own".

That is § AN EMPTY RESULT IS TWO DIFFERENT FAILURES WEARING ONE FACE arriving on the query
the hygiene mandate itself hands you — a filtered population and a complete one print
identically.

MEASURED COST, twice on 2026-09-05:
  · a seat re-minted `90147146`, a duplicate of its own 50-minute-old row, because the
    original was `not_approved` and invisible to every prescribed pass AND to the
    un-status'd catch-all
  · `task_query( accountable_manager="mr radio" )` returned 12 of the 16 non-terminal rows
    carrying that manager. Two of the four missing were park-active (documented, expected).
    The other two were `not_approved` — and one row it DID return is titled "clear the 8
    invisible not_approved rows"

=== WHAT THIS FILE DELIBERATELY DOES NOT CLAIM ===

⚠️ It does NOT claim that a row whose owner and manager disagree is invisible. That was
proposed on the row and it is FALSE — measured 2026-09-05: owner != manager is the NORMAL
case (20 of 23 live rows), and such a row appears in BOTH the owner-scoped and the
manager-scoped query. `test_a_row_whose_owner_and_manager_disagree_appears_for_BOTH` pins
that, because a future "fix" aimed at the wrong mechanism would break it.

⚠️ It does NOT fix the reason held rows never self-expire. Rick ruled 2026-09-02 that a
held row hides only until its triage chase comes due; `create_task` sets
`next_chase_ts = payload.next_chase_ts` and nothing computes a triage chase at mint, so a
row minted without one has no expiry to reach. That is a ruling, not a worker's call. This
file makes the omission VISIBLE, which is the cheaper half.
"""

import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from cosa.rest.routers import tasks
from cosa.rest.postgres_models import TaskItem


HOLDING = "not_approved"
_NOW    = datetime( 2026, 9, 5, 18, 0, tzinfo=timezone.utc )


# ---------------------------------------------------------------------------------------
# Local scaffolding, kept independent of test_tasks_router.py's fixtures ON PURPOSE: a
# guard that shares a fixture with the suite it is checking inherits that fixture's blind
# spots, and the count_tasks mock is exactly where this defect hid.
# ---------------------------------------------------------------------------------------

def _item( **overrides ):
    fields = dict(
        id                  = uuid.uuid4(),
        item_class          = "task",
        title               = "a row",
        body                = None,
        project             = "lupin",
        owner_persona       = "krishna",
        accountable_manager = "mr radio",
        created_by          = "krishna 056ca4c8",
        status              = "queued",
        blocked_by          = [ ],
        next_chase_ts       = None,
        gate_class          = "none",
        priority            = "P2",
        source_qid          = None,
        correlation_key     = None,
        # Explicit, and NOT decorative: the FULL serializer calls `.isoformat()` on both,
        # and a SQLAlchemy column `default` fires at INSERT, never at construction. Left
        # unset these arrive as None and every non-terse arm dies with
        # `'NoneType' object has no attribute 'isoformat'` — which reads like a router
        # defect and is a fixture one.
        created_ts          = _NOW,
        updated_ts          = _NOW,
        title_trimmed       = False,
    )
    fields.update( overrides )
    return TaskItem( **fields )


@pytest.fixture
def board( monkeypatch ):
    """
    A fake repository whose `count_tasks` DISCRIMINATES ON `status`.

    🔴 THIS IS THE WHOLE FIXTURE AND IT IS THE POINT. The holding disclosure asks
    `count_tasks` a SECOND question — "how many held rows match these filters?" — and a
    fake with one `return_value` answers both with one number. Such a fake cannot tell you
    whether the router passed the right status, or any status at all: a router probing the
    wrong thing looks identical to one probing the right thing. `held` is a separate knob,
    defaulting to zero, so every assertion below is about a value only the correct call can
    reach.
    """
    fake              = MagicMock()
    fake.held         = 0
    fake.rows         = [ ]
    fake.total        = 0

    def _count_tasks( **kwargs ):
        return fake.held if kwargs.get( "status" ) == HOLDING else fake.total

    def _query_tasks( **kwargs ):
        return list( fake.rows )

    fake.count_tasks.side_effect             = _count_tasks
    fake.query_tasks.side_effect             = _query_tasks
    fake.statuses_for_ids.return_value       = { }
    fake.count_tasks_by_project.return_value = { }
    fake.count_tasks_by_priority.return_value = { }
    fake.count_tasks_by_status.return_value  = { }
    fake.count_created_and_closed.return_value = { "created": 0, "closed": 0 }

    # `get_db` is used as a CONTEXT MANAGER by the router, so the seam has to be one.
    # A plain generator raises `'list_iterator' object does not support the context
    # manager protocol` inside the handler, which surfaces as a 500 and reads like a
    # router defect rather than a fixture one.
    @contextmanager
    def _fake_get_db():
        yield MagicMock()

    monkeypatch.setattr( tasks, "get_db", _fake_get_db )
    monkeypatch.setattr( tasks, "TaskRepository", lambda session: fake )
    return fake


@pytest.fixture
def api( board ):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt

    app = FastAPI()
    app.include_router( tasks.router )
    app.dependency_overrides[ require_api_key_or_jwt ] = lambda: "test-user"
    return TestClient( app )


def _holding_warnings( body ):
    return [ w for w in body.get( "warnings", [ ] ) if "HOLDING AREA" in w ]


# ---------------------------------------------------------------------------------------
# ARM A — the omission is declared
# ---------------------------------------------------------------------------------------

def test_an_unstatused_query_declares_the_rows_it_withheld( api, board ):
    board.rows  = [ _item() for _ in range( 3 ) ]
    board.total = 3
    board.held  = 4                       # four held rows match the same filters

    body = api.get( "/api/tasks", params={ "owner_persona": "krishna" } ).json()
    notices = _holding_warnings( body )

    assert len( notices ) == 1, f"expected exactly one holding notice, got {body.get( 'warnings' )}"
    notice = notices[ 0 ]
    assert "4 row(s)" in notice,      f"the notice must carry the COUNT — a bare 'some rows' is unactionable: {notice}"
    assert HOLDING in notice,         f"the notice must name the status: {notice}"
    assert "task_query(" in notice,   f"the notice must hand the reader the query that reveals them: {notice}"


def test_the_withheld_rows_are_not_folded_into_total( api, board ):
    """
    The count must stay HONEST about what it counted. Adding the held rows to `total`
    would make the number agree with the notice and disagree with the list — a page of 3
    reporting a total of 7 is a worse lie than the silence this replaces.
    """
    board.rows  = [ _item() for _ in range( 3 ) ]
    board.total = 3
    board.held  = 4

    body = api.get( "/api/tasks", params={ "owner_persona": "krishna" } ).json()
    assert body[ "total" ] == 3
    assert len( body[ "tasks" ] ) == 3
    assert "NOT in `total`" in _holding_warnings( body )[ 0 ]


# ---------------------------------------------------------------------------------------
# ARM B — the negative controls. Without these, "always warn" satisfies arm A.
# ---------------------------------------------------------------------------------------

def test_a_query_with_no_held_rows_says_nothing( api, board ):
    """
    THE CONTROL THAT MAKES ARM A MEAN SOMETHING. A notice that fires on every query is a
    notice readers learn to skip, which disarms it permanently — the `park_reason_stale`
    failure this repo already recorded.
    """
    board.rows  = [ _item() for _ in range( 3 ) ]
    board.total = 3
    board.held  = 0

    body = api.get( "/api/tasks", params={ "owner_persona": "krishna" } ).json()
    assert _holding_warnings( body ) == [ ], body.get( "warnings" )


def test_a_status_scoped_query_says_nothing( api, board ):
    """
    A caller who named a status asked a narrow question and got a complete answer to it.
    Nothing was withheld BY THIS RULE, so there is nothing to declare.
    """
    board.rows  = [ _item( status="queued" ) ]
    board.total = 1
    board.held  = 4                       # held rows exist and are still not this caller's question

    body = api.get( "/api/tasks", params={ "owner_persona": "krishna", "status": "queued" } ).json()
    assert _holding_warnings( body ) == [ ], body.get( "warnings" )


def test_asking_for_everything_says_nothing( api, board ):
    """
    `include_terminal=true` is the flag that already reveals held rows — mis-named, and
    that is this row's other finding, but it does work. When it is set nothing is
    withheld, so a notice would be false.
    """
    board.rows  = [ _item() ]
    board.total = 1
    board.held  = 4

    body = api.get(
        "/api/tasks",
        params={ "owner_persona": "krishna", "include_terminal": "true" },
    ).json()
    assert _holding_warnings( body ) == [ ], body.get( "warnings" )


def test_the_probe_carries_the_callers_own_filters( api, board ):
    """
    🔴 THE ARM THAT CATCHES A PROBE ASKING THE WRONG QUESTION. A holding count taken
    WITHOUT the caller's filters would report the whole fleet's held rows to a seat asking
    about its own — a number that is large, plausible, and about somebody else. Nothing in
    the notice's wording would reveal it.
    """
    board.rows  = [ _item() ]
    board.total = 1
    board.held  = 1

    api.get( "/api/tasks", params={ "owner_persona": "krishna", "project": "lupin" } )

    probes = [
        c.kwargs for c in board.count_tasks.call_args_list
        if c.kwargs.get( "status" ) == HOLDING
    ]
    assert len( probes ) == 1, f"expected exactly one holding probe, got {len( probes )}"
    assert probes[ 0 ][ "owner_persona" ] == "krishna", probes[ 0 ]
    assert probes[ 0 ][ "project" ]       == "lupin",   probes[ 0 ]


# ---------------------------------------------------------------------------------------
# ARM C — the terse projection can answer "is this mine"
# ---------------------------------------------------------------------------------------

def test_terse_carries_owner_and_manager( api, board ):
    """
    Three seats in one evening asked a question this projection could not answer and took
    its silence for an answer. `terse` is the view a board glance reads; ownership was only
    in the full shape, so the check that would have caught a mis-routed row was unavailable
    where anyone would think to run it.
    """
    board.rows  = [ _item( owner_persona="rio", accountable_manager="mr radio" ) ]
    board.total = 1

    body = api.get( "/api/tasks", params={ "terse": "true" } ).json()
    row  = body[ "tasks" ][ 0 ]

    assert row[ "owner_persona" ]       == "rio"
    assert row[ "accountable_manager" ] == "mr radio"
    assert "body" not in row, "the token win must survive — terse still drops body"


def test_the_two_ownership_fields_are_declared_as_carried_not_derived():
    """
    The router classifies every terse key as DATA (carried off the row) or ADVISORY
    (derived by a predicate). These are read straight off their columns, so a future editor
    cannot quietly re-classify them as derived without this failing.
    """
    assert "owner_persona"       in tasks.TERSE_DATA_FIELDS
    assert "accountable_manager" in tasks.TERSE_DATA_FIELDS
    assert not ( tasks.TERSE_DATA_FIELDS & tasks.TERSE_ADVISORY_FIELDS )


# ---------------------------------------------------------------------------------------
# ARM D — the mechanism that was PROPOSED and is FALSE, pinned so nobody "fixes" it
# ---------------------------------------------------------------------------------------

def test_a_row_whose_owner_and_manager_disagree_appears_for_BOTH( api, board ):
    """
    🔴 THIS PINS A CORRECTION, NOT A FEATURE.

    It was proposed on row d254c397 that "the accountable-manager field decides whose board
    query returns it, and when owner and manager disagree the row is invisible to at least
    one person." That is FALSE, and acting on it would break the worker/manager model:
    owner != manager is the NORMAL case — measured 2026-09-05 on `lupin_db_dev`, 20 of 23
    live rows — because a worker owns and a manager is accountable.

    The incident behind that proposal has a simpler cause, established from the audit trail
    rather than reasoned: `bf4f65c3` was not returned by a manager-scoped query because at
    that moment its `accountable_manager` was `maria`. Event 11961, 2026-09-05 22:26:42Z,
    records `accountable_manager: 'maria' -> 'mr radio'`. The query was correct; the FIELD
    was wrong, and nothing surfaced that.

    ⇒ A wrong mechanism sends the next reader at innocent code. This arm makes sure the
    innocent code stays put.
    """
    row = _item( owner_persona="rio", accountable_manager="mr radio" )
    board.rows  = [ row ]
    board.total = 1

    owned   = api.get( "/api/tasks", params={ "owner_persona": "rio", "terse": "true" } ).json()
    managed = api.get( "/api/tasks", params={ "accountable_manager": "mr radio", "terse": "true" } ).json()

    assert [ t[ "id" ] for t in owned[ "tasks" ] ] == [ str( row.id ) ], \
        "a row must be visible to the persona who OWNS it"
    assert [ t[ "id" ] for t in managed[ "tasks" ] ] == [ str( row.id ) ], \
        "the same row must be visible to the manager ACCOUNTABLE for it"

    # And the filters really did reach the repository — otherwise both calls above would
    # pass against a router that ignores them entirely and returns `board.rows` regardless.
    forwarded = [ c.kwargs for c in board.query_tasks.call_args_list ]
    assert forwarded[ 0 ][ "owner_persona" ]       == "rio"
    assert forwarded[ 0 ][ "accountable_manager" ] is None
    assert forwarded[ 1 ][ "owner_persona" ]       is None
    assert forwarded[ 1 ][ "accountable_manager" ] == "mr radio"
