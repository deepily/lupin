#!/usr/bin/env python3
"""
E2E — the Task-List pane's PER-GROUP accordion: click a header, that group's
rows go away, and NOBODY ELSE'S DO.

WHY THIS FILE EXISTS AT THE E2E TIER AT ALL, since the accordion already has
unit coverage. The unit tests build the table and assert the `collapsed` class
lands on the right `<tbody>`. That is a true statement about the RENDERER and it
says nothing about whether a user sees anything change: the class only hides
rows because `tbody.task-group.collapsed .task-row { display: none }` lives in
`css/multiplexer/task-list.css`, and a pane can mount, render, carry every
correct class and have no stylesheet at all — which is exactly what `4cf3febf`
repaired for two other panes while every unit test stayed green.

⇒ SO EVERY ASSERTION HERE IS ON VISIBILITY, NEVER ON THE CLASS. `is_visible()`
is the primitive that can only be satisfied by the renderer, the click wiring
AND the stylesheet all being present at once. Asserting `collapsed` in the class
list would re-create the defect this file is here to catch, one tier up.

🔴 AND "OTHER GROUPS DO NOT MOVE" IS ASSERTED AS STATE, NOT AS GEOMETRY — this
is a deliberate narrowing of the brief and the reason is that the wider version
is FALSE. Collapsing a group shortens the table, so every group BELOW it really
does shift upward on screen; that is correct accordion behaviour, and a test
pinning y-positions would fail working code and be "fixed" by deleting it. The
invariant that actually holds is that no other group's OWN state changes: its
rows stay visible, its row count is unchanged, and its header keeps
`aria-expanded="true"`. That is what a user means by "the other groups were left
alone."

⚠️ THE POSITIVE CONTROL IS LOAD-BEARING, not ceremony. "The rows are hidden
after the click" is satisfied for free by a table that never rendered any rows,
by a stubbed response that returned nothing, and by a selector with a typo in
it. Each test therefore asserts the rows are VISIBLE first, and asserts a
non-zero count, so that the after-state means something.

Venue: :8000 (monopolize, scheduled) — the `test_multiplexer_*` Playwright
batch, per the §TESTING VENUES rubric. Auth is seeded into the PLAYWRIGHT
CONTEXT (`context.add_init_script`), which is isolated from any real Chrome
profile — this suite writes `lupin_access_token` for the test user and can never
reach a signed-in human's session.

⚠️ Its launcher exits 0 on `--bg` before pytest exists (§ the `--bg` mandate
guarantees the false green). READ THE LOG, never this suite's exit code.

PROVEN TO FAIL — 2026-09-06, four :8000 runs, one variable each. A test file is
not a guard until something has watched it go red, and these three were green on
their first run, which is exactly when a suite is least trustworthy.

The mutations edit the LIVE SERVED BUNDLE named by
`dist/multiplexer/manifest.json` — gitignored build output, so no tracked source
was touched — and the bundle was md5-verified back to its original after each arm.

    arm                       bundle change                       failures
    ────────────────────────────────────────────────────────────────────────
    baseline  ts-1041f1b3     none                                0 of 3
    M1        ts-b76b564c     the header toggle becomes a no-op   2 of 3
    M2        ts-02199fed     one click collapses EVERY group     2 of 3
    restore   ts-ecdd37bc     restored (md5 identical)            0 of 3

M1 killed on: "amy's rows are still visible after clicking her header".
M2 killed on: "collapsing amy changed another group's state".

⇒ THE TWO ARMS DIE ON DIFFERENT ASSERTIONS, which is the part that matters. A
suite that reddened on both with the same message would only show it can fail,
not that it can tell two defects apart. M2 in particular is the ONLY evidence
that the "other groups untouched" check is load-bearing — the assertion this
file deliberately narrowed from the brief's "other groups do not move".

⇒ AND `test_the_fixture_renders_three_groups...` STAYED GREEN IN BOTH ARMS. That
is the discrimination control: it asserts the OPENING state, which neither
mutation touches, so a harness that simply reddened everything would have failed
it too.

⚠️ `skipped="0"` is the figure to read in the JUnit artifact, never `tests="3"`.
This file skips itself when the credentials are absent, and a skipped E2E reports
as a clean run that proved nothing.

⚠️ AND WHEN YOU READ A FAILURE HERE, the page URL prints as `localhost:7999` —
that is the CONTAINER'S internal port (`7999/tcp -> 0.0.0.0:8000`), not the dev
server. In-container :7999 is this venue. It reads like a test pointed at the
wrong box and is not one.

Usage:
    pytest src/tests/e2e_ui/test_multiplexer_task_list_group_accordion.py -v
"""

from __future__ import annotations

import json
import os

import pytest
import requests

BASE_URL        = os.environ.get( "LUPIN_API_URL", "http://localhost:7999" )
MULTIPLEXER_URL = f"{BASE_URL}/app/multiplexer"

TASKS_ROUTE = "**/api/tasks*"

# The three groups the fixture below produces. Three rather than two on purpose:
# with only one "other" group, a bug that collapsed EVERYTHING and a bug that
# collapsed the RIGHT ONE PLUS ONE MORE are indistinguishable.
GROUP_AMY        = "amy"
GROUP_ZOE        = "zoe"
GROUP_UNASSIGNED = "__unassigned__"


# ---------------------------------------------------------------------------
# Auth + harness (mirrors test_multiplexer_task_list.py deliberately — same
# card, same stub seam, so the two files stay readable side by side)
# ---------------------------------------------------------------------------

def _get_credentials() -> tuple[ str, str ]:
    email    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
    password = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )
    if not email or not password:
        pytest.skip( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL / _PASSWORD env vars not set" )
    return email, password


def _login_tokens() -> tuple[ str, str ]:
    email, password = _get_credentials()
    resp = requests.post(
        f"{BASE_URL}/auth/login",
        json    = { "email": email, "password": password },
        timeout = 10,
    )
    assert resp.status_code == 200, f"login failed: { resp.status_code } { resp.text }"
    tokens = resp.json()[ "tokens" ]
    return tokens[ "access_token" ], tokens[ "refresh_token" ]


def _seed_auth( context, access_token: str, refresh_token: str ) -> None:
    """
    Seed the two auth keys into THIS PLAYWRIGHT CONTEXT only.

    Ensures:
        - writes land in an isolated browser context, never a real Chrome profile
    """
    context.add_init_script(
        f"window.localStorage.setItem('lupin_access_token', { json.dumps( access_token ) });"
        f"window.localStorage.setItem('lupin_refresh_token', { json.dumps( refresh_token ) });"
    )


def _clear_persisted_collapse( context ) -> None:
    """
    Start every test from EXPANDED, whatever a previous run persisted.

    The accordion writes collapsed owners to `lupin.taskList.collapsedOwners`.
    Without this the suite's own first click could be an EXPAND, and a test that
    silently runs backwards still passes some of its assertions.
    """
    context.add_init_script( "window.localStorage.removeItem('lupin.taskList.collapsedOwners');" )


def _open_with_tasks( page, tasks_body: dict ):
    access, refresh = _login_tokens()
    _seed_auth( page.context, access, refresh )
    _clear_persisted_collapse( page.context )
    page.route(
        TASKS_ROUTE,
        lambda route: route.fulfill(
            status=200, content_type="application/json", body=json.dumps( tasks_body )
        ),
    )
    page.goto( MULTIPLEXER_URL, wait_until="networkidle", timeout=15_000 )
    page.wait_for_function(
        "() => window.__multiplexerTestHook !== undefined && window.__multiplexerTestHook.eventBus !== undefined",
        timeout=10_000,
    )
    page.wait_for_selector( ".task-list-table", timeout=3000 )


# ---------------------------------------------------------------------------
# Fixture — three groups, every task non-terminal so none is filtered out
# ---------------------------------------------------------------------------

_THREE_GROUPS = {
    "tasks" : [
        { "id": "a1", "item_class": "task", "title": "amy one",   "status": "in_progress",
          "owner_persona": "amy", "priority": "P1", "project": "lupin",
          "blocked_by": None, "next_chase_ts": None },
        { "id": "a2", "item_class": "bug",  "title": "amy two",   "status": "queued",
          "owner_persona": "amy", "priority": "P2", "project": "lupin",
          "blocked_by": None, "next_chase_ts": None },
        { "id": "z1", "item_class": "task", "title": "zoe one",   "status": "queued",
          "owner_persona": "zoe", "priority": "P2", "project": "lupin",
          "blocked_by": None, "next_chase_ts": None },
        { "id": "z2", "item_class": "task", "title": "zoe two",   "status": "in_progress",
          "owner_persona": "zoe", "priority": "P3", "project": "lupin",
          "blocked_by": None, "next_chase_ts": None },
        { "id": "u1", "item_class": "task", "title": "orphan",    "status": "queued",
          "owner_persona": None,  "priority": "P3", "project": "lupin",
          "blocked_by": None, "next_chase_ts": None },
    ],
    "count" : 5,
}


# ---------------------------------------------------------------------------
# Readers — every one of them answers in VISIBILITY or a COUNT, never a class
# ---------------------------------------------------------------------------

def _group( page, owner: str ):
    return page.locator( f'tbody.task-group[data-owner="{ owner }"]' )


def _visible_rows( page, owner: str ) -> int:
    """How many of this group's task rows a user can actually SEE."""
    rows = _group( page, owner ).locator( "tr.task-row" )
    return sum( 1 for i in range( rows.count() ) if rows.nth( i ).is_visible() )


def _rendered_rows( page, owner: str ) -> int:
    """How many rows EXIST, visible or not — the denominator."""
    return _group( page, owner ).locator( "tr.task-row" ).count()


def _header( page, owner: str ):
    return _group( page, owner ).locator( "tr.task-group-header" )


def _aria_expanded( page, owner: str ) -> str:
    return _header( page, owner ).get_attribute( "aria-expanded" )


def _snapshot_others( page, collapsed_owner: str ) -> dict:
    """Visible/rendered row counts + aria state for every group EXCEPT one."""
    return {
        owner : {
            "visible"  : _visible_rows( page, owner ),
            "rendered" : _rendered_rows( page, owner ),
            "aria"     : _aria_expanded( page, owner ),
        }
        for owner in ( GROUP_AMY, GROUP_ZOE, GROUP_UNASSIGNED )
        if owner != collapsed_owner
    }


# ---------------------------------------------------------------------------
# The tests
# ---------------------------------------------------------------------------

def test_the_fixture_renders_three_groups_with_rows_a_user_can_see( page ):
    """
    The positive control the other two tests stand on.

    Without it, "the rows are hidden after the click" is satisfied by a table
    that rendered no rows at all, by a stub that returned nothing, and by a
    selector with a typo in it.
    """
    _open_with_tasks( page, _THREE_GROUPS )

    for owner, expected in ( ( GROUP_AMY, 2 ), ( GROUP_ZOE, 2 ), ( GROUP_UNASSIGNED, 1 ) ):
        assert _rendered_rows( page, owner ) == expected, (
            f"group { owner } should render { expected } rows; the fixture or the grouping changed"
        )
        assert _visible_rows( page, owner ) == expected, (
            f"group { owner } rendered its rows but a user cannot SEE them — the pane's "
            f"stylesheet is the first thing to check (cf. 4cf3febf)"
        )
        assert _aria_expanded( page, owner ) == "true", (
            f"group { owner } should start EXPANDED; a persisted collapse leaked into this run"
        )


def test_clicking_a_group_header_hides_only_that_groups_rows( page ):
    _open_with_tasks( page, _THREE_GROUPS )

    before = _snapshot_others( page, GROUP_AMY )
    assert _visible_rows( page, GROUP_AMY ) == 2, "precondition: amy's rows must be visible first"

    _header( page, GROUP_AMY ).click()

    # The clicked group: its rows are GONE FROM VIEW — and still in the DOM, which
    # is what makes this a collapse rather than a re-render that dropped them.
    assert _visible_rows( page, GROUP_AMY ) == 0, (
        "amy's rows are still visible after clicking her header — the click wiring fired but "
        "nothing hid them, or the stylesheet carrying `.task-group.collapsed .task-row` is absent"
    )
    assert _rendered_rows( page, GROUP_AMY ) == 2, (
        "amy's rows left the DOM entirely — that is a re-render, not an accordion collapse"
    )
    assert _aria_expanded( page, GROUP_AMY ) == "false"

    # The header itself stays put. A collapse that hides its own handle cannot be undone.
    assert _header( page, GROUP_AMY ).is_visible(), "the group header must survive its own collapse"

    # NOBODY ELSE MOVED. State, not geometry — see this module's docstring.
    assert _snapshot_others( page, GROUP_AMY ) == before, (
        "collapsing amy changed another group's state; expected every other group untouched, "
        f"before={ before } after={ _snapshot_others( page, GROUP_AMY ) }"
    )


def test_clicking_the_header_again_restores_every_row_it_hid( page ):
    _open_with_tasks( page, _THREE_GROUPS )

    full = {
        owner : _visible_rows( page, owner )
        for owner in ( GROUP_AMY, GROUP_ZOE, GROUP_UNASSIGNED )
    }
    assert all( n > 0 for n in full.values() ), f"precondition: every group starts visible, got { full }"

    _header( page, GROUP_AMY ).click()
    assert _visible_rows( page, GROUP_AMY ) == 0, "precondition: the collapse must actually take"

    _header( page, GROUP_AMY ).click()

    restored = {
        owner : _visible_rows( page, owner )
        for owner in ( GROUP_AMY, GROUP_ZOE, GROUP_UNASSIGNED )
    }
    assert restored == full, (
        f"expanding did not restore the table to its opening state: before={ full } after={ restored }"
    )
    assert _aria_expanded( page, GROUP_AMY ) == "true"
