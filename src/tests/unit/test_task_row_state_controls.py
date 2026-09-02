#!/usr/bin/env python3
"""
test_task_row_state_controls.py — the per-row Drop / Park controls in the
notifications client (Rick's P0, store row 8af64f5a, 2026-09-02).

Run:  .venv/bin/pytest src/tests/unit/test_task_row_state_controls.py -q

WHY THESE ASSERT ON THE SHIPPED ASSET. The client is plain JS served as a static
file; there is no import seam. So these read `notifications.js` off disk, the same
pattern `test_browser_fallback_session_id_is_server_valid.py` established — what a
browser is served is the only thing that matters, and a test that reads anything
else can pass while the page is broken.

THE PROPERTY THAT MATTERS MOST is `test_park_is_disabled_where_the_server_would_refuse`.
`PARK_LEGAL_FROM_STATUSES` is ( "queued", "in_progress" ), so a park control offered
on a blocked/review/claimed row produces a 422 the operator cannot act on. The rule
is enforced server-side either way; rendering it disabled is what stops the operator
learning it from a failure.
"""

import re

from pathlib import Path

import pytest

import cosa.rest.task_store_rules as rules


REPO_ROOT = Path( __file__ ).resolve().parents[ 3 ]
CLIENT    = REPO_ROOT / "src" / "lupin_app" / "static" / "js" / "notifications.js"
PAGE      = REPO_ROOT / "src" / "lupin_app" / "static" / "html" / "notifications.html"


@pytest.fixture( scope="module" )
def client_src():
    """Ensures: the shipped client asset's text. Fails loudly when absent."""
    assert CLIENT.is_file(), f"shipped client asset missing: {CLIENT}"
    return CLIENT.read_text( encoding="utf-8" )


# ------------------------------------------------- the controls exist and are wired

def test_actions_column_has_a_header_and_a_cell( client_src ):
    """A cell with no header silently shifts every column right of it."""
    assert 'th class="task-col-actions"' in client_src
    assert 'td class="task-col-actions"' in client_src


def test_drop_and_park_are_dispatched_from_the_delegated_handler( client_src ):
    """
    The row has ONE delegated click handler. A control that renders but is not
    reachable from it is a button that does nothing — which looks identical to a
    working button until it is pressed.
    """
    assert "_handleTaskDropClick" in client_src
    assert "_handleTaskParkClick" in client_src
    assert 'target.closest( ".task-action-btn" )' in client_src


def test_the_transition_endpoint_is_actually_called( client_src ):
    """
    Before this change the client called NO transition endpoint at all — it could
    render a parked badge and could not park anything. This is the assertion that
    would have been red for the whole life of the file until today.
    """
    assert "/transition" in client_src
    assert "to_status" in client_src


# ------------------------------------------------- the server's rules, mirrored honestly

def test_park_is_disabled_where_the_server_would_refuse( client_src ):
    """
    THE ONE THAT EARNS ITS KEEP. Park is legal ONLY from the statuses the store
    names, and the client must not offer it elsewhere.

    Reads the legal set from `task_store_rules` rather than restating it — a
    literal here would be a second copy of the rule, free to drift from the one
    the server enforces, and the drift would show up as a 422 nobody can act on.
    """
    legal = set( rules.PARK_LEGAL_FROM_STATUSES )
    assert legal == { "queued", "in_progress" }, (
        f"the park-legal set moved to {legal}; the client's gate must move with it"
    )
    for status in sorted( legal ):
        assert f'status === "{status}"' in client_src, (
            f"client does not enable park from {status!r}, which the server permits"
        )
    assert "task-action-disabled" in client_src
    assert 'aria-disabled="true"' in client_src


def test_both_required_reasons_are_checked_before_the_call( client_src ):
    """
    `->dropped` requires a non-blank reason and `->parked` requires BOTH a
    park_reason and a next_chase_ts. The server rejects either way; checking first
    is what puts the message beside the field instead of in a failed request.
    """
    assert "A drop reason is required." in client_src
    assert "A park reason is required" in client_src
    assert "A chase date is required" in client_src
    assert "park_reason" in client_src
    assert "next_chase_ts" in client_src


def test_the_park_placeholder_asks_for_a_QUOTE_not_a_reason( client_src ):
    """
    `park_reason` must carry the row's OWN decisive sentence. A bare "reason…"
    placeholder produces paraphrases, and a paraphrase cannot be refuted row-by-row
    by the next reader — which is the entire job of that field.
    """
    assert "quote the sentence that decided this" in client_src


def test_the_chase_date_is_converted_through_the_browser_zone( client_src ):
    """
    `<input type="date">` yields a bare calendar day. Sent as-is it reads as
    midnight UTC, which lands the chase on the PREVIOUS EVENING for every zone west
    of Greenwich — i.e. all of ours. The client stamps a local time and converts.
    """
    assert "T09:00:00" in client_src
    assert "toISOString()" in client_src


# ------------------------------------------------- the asset actually reaches the browser

def test_the_cache_bust_tokens_were_bumped_with_the_assets():
    """
    A `?v=` token is part of the browser's cache KEY. Ship a changed asset behind an
    unchanged token and a returning browser serves the OLD copy — the change looks
    landed in git and absent on screen, which is the least diagnosable failure of
    the set (row a501a714 hit exactly this).
    """
    page = PAGE.read_text( encoding="utf-8" )
    js   = re.search( r"notifications\.js\?v=(\w+)", page )
    css  = re.search( r"task-list\.css\?v=(\w+)", page )
    assert js  is not None, "notifications.js is not versioned on the page"
    assert css is not None, "task-list.css is not versioned on the page"
    assert js.group( 1 )  != "20260902b", "js token not bumped past the filer-column release"
    assert css.group( 1 ) != "20260901c", "css token not bumped past its previous release"
