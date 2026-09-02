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
    assert js.group( 1 )  != "20260902c", "js token not bumped past the drop/park slice"
    assert css.group( 1 ) != "20260902a", "css token not bumped past the drop/park slice"


# ------------------------------------------------- slice 2: won't-fix · demote · approve
#
# The store grew two statuses (`not_approved`, `wont_fix`) and the client had to
# grow with them in three separate places, only one of which is a button. The
# other two are the ones that would have gone wrong quietly.


def test_wont_fix_is_terminal_in_the_client_open_predicate( client_src ):
    """
    🔴 THE ONE THAT WAS ALREADY BROKEN. `isTaskOpenStatus` knew only done/dropped,
    so a won't-fixed row still counted as work owed — a refusal that keeps
    reporting itself as owed work is precisely what the status exists to stop.

    Reads the terminal set from `task_store_rules` rather than restating it, for
    the same reason the park test does: a literal here is a second copy of the
    rule, free to drift from the one the server enforces.
    """
    terminal = set( rules.TERMINAL_STATUSES )
    assert terminal == { "done", "dropped", "wont_fix" }, (
        f"the terminal set moved to {terminal}; isTaskOpenStatus must move with it"
    )
    for status in sorted( terminal ):
        assert f'status !== "{status}"' in client_src, (
            f"isTaskOpenStatus does not treat {status!r} as terminal, but the store does"
        )


def test_not_approved_is_NOT_treated_as_terminal( client_src ):
    """
    The negative control, and it is not symmetry for its own sake. The store's own
    comment says adding `not_approved` to the terminal set would tell every reader
    that a row in the holding area is FINISHED — the opposite of the truth, since
    an unapproved row's whole point is that it is waiting for movement.
    """
    assert rules.NOT_APPROVED_STATUS not in rules.TERMINAL_STATUSES
    assert 'status !== "not_approved"' not in client_src, (
        "the client treats not_approved as terminal; the store deliberately does not"
    )


def test_every_store_status_has_a_client_colour( client_src ):
    """
    A status with no branch in `_taskStatusClass` renders as `unknown` grey. That
    makes a deliberate refusal, a row awaiting triage and a typo'd status
    indistinguishable at a glance — three situations, one colour.

    Enumerated from VALID_STATUSES so a status added server-side reddens here
    instead of shipping as grey.
    """
    for status in rules.VALID_STATUSES:
        assert f'word === "{status}"' in client_src, (
            f"{status!r} is a valid store status with no branch in _taskStatusClass"
        )


def test_the_three_new_controls_are_rendered_and_dispatched( client_src ):
    """
    A control that renders but is unreachable from the ONE delegated click handler
    is a button that does nothing — which looks identical to a working button until
    it is pressed.
    """
    for cls, handler in (
        ( "task-wont-fix-button", "_handleTaskWontFixClick" ),
        ( "task-demote-button",   "_handleTaskDemoteClick" ),
        ( "task-approve-button",  "_handleTaskApproveClick" ),
    ):
        assert cls in client_src,     f"{cls} is never rendered"
        assert handler in client_src, f"{handler} is never defined"
        assert f'classList.contains( "{cls}" )' in client_src, (
            f"{cls} renders but the delegated handler never dispatches it"
        )


def test_wont_fix_requires_a_reason_because_the_server_does( client_src ):
    """
    `->wont_fix` carries the SAME non-blank reason obligation as `->dropped`. The
    receipt gate fires only on `->done`, so a won't-fix has no commit behind it and
    the reason is the only thing standing between a deliberate refusal and work
    that got forgotten.

    Asserted against the server rule, not against a remembered string.
    """
    errors = rules.validate_transition(
        from_status="queued", to_status="wont_fix", authority="user_direct", reason="   "
    )
    assert any( "reason is REQUIRED" in e for e in errors ), (
        f"the server no longer requires a won't-fix reason; the client check is now the only one: {errors}"
    )
    assert "A won't-fix reason is required" in client_src


def test_terminal_rows_offer_no_controls_at_all( client_src ):
    """
    `done` / `dropped` / `wont_fix` are append-only — `validate_transition` refuses
    every edge out of them. The first cut of the actions cell rendered Drop enabled
    for EVERY row, so the status that had just been made terminal was also the one
    the board invited you to act on.
    """
    errors = rules.validate_transition(
        from_status="wont_fix", to_status="queued", authority="user_direct"
    )
    assert any( "terminal" in e for e in errors ), (
        f"the store now permits transitions out of wont_fix; the client gate must move with it: {errors}"
    )
    # 🔴 PIN THE DERIVATION, NOT THE NAME. The first cut of this test asserted that
    # the string "isTerminal" appeared in the file. It passed happily against
    # `const isTerminal = false;` — the variable was still named, still mentioned in
    # every tooltip, and the gate was wide open. A presence check cannot tell a live
    # predicate from a dead constant, and this one was proved unfalsifiable by
    # setting the constant and watching the suite stay green.
    assert "const isTerminal  = !this.isTaskOpenStatus( status );" in client_src, (
        "isTerminal is no longer derived from the open-status predicate — a constant "
        "or a rewritten derivation here reopens every control on a terminal row"
    )
    # ...and that each control's enabled flag actually READS it.
    for control in ( "task-drop-button", "task-wont-fix-button", "task-demote-button" ):
        assert f'"{control}"' in client_src
    assert "!isTerminal" in client_src, "no control gates on isTerminal at all"
    assert "terminal rows are append-only and have no transitions out" in client_src


def test_approve_and_demote_are_never_both_live_on_one_row( client_src ):
    """
    Approve is the holding area's EXIT (`not_approved -> queued`); Demote is its
    ENTRANCE. Offering both on one row hands the operator a move that is a no-op in
    one direction — and the store rejects a no-op edge as a failure, not as nothing
    happening.
    """
    errors = rules.validate_transition(
        from_status="not_approved", to_status="not_approved", authority="user_direct"
    )
    assert errors, "a no-op edge is no longer refused; the mutual-exclusion gate loses its reason"
    assert 'status === "not_approved"' in client_src, "the client never computes the held case"
    assert "isHeld" in client_src
    assert "demoteLegal = !isTerminal && !isHeld" in client_src


def test_approve_does_not_second_guess_the_server_allowlist( client_src ):
    """
    Rick ruled that either a manager or he suffices — "for now" — so the approver
    allowlist is server-side configuration, editable without a deploy. A client-side
    copy of a rule that is explicitly provisional would refuse people the server
    would have allowed, and would drift the moment the configuration changed.

    So approve sends the transition and SURFACES the refusal rather than pre-empting
    it: no allowlist, no persona check, no is-approver branch in the client.
    """
    assert "Approve refused: " in client_src
    for forbidden in ( "isApprover", "approverAllowlist", "APPROVER_ALLOWLIST" ):
        assert forbidden not in client_src, (
            f"the client carries {forbidden!r} — a second copy of a provisional server rule"
        )


def test_demote_reason_is_client_only_until_the_server_catches_up( client_src ):
    """
    🔴 A SELF-RETIRING GUARD, and it is here so a known gap cannot go quiet.

    The design (amendment 5) says demotion "needs its own legality entry and its own
    reason". The client enforces the reason; `validate_transition` does NOT yet. A
    client-only rule is not enforcement — anything posting straight to the API
    bypasses it.

    This test PINS THE GAP. When the server adds the rule it goes RED, and whoever
    sees it deletes this test and moves the assertion into the won't-fix-shaped one
    above. It must never be "fixed" by loosening the client.
    """
    errors = rules.validate_transition(
        from_status="queued", to_status="not_approved", authority="user_direct", reason=""
    )
    assert not any( "reason is REQUIRED" in e for e in errors ), (
        "THE SERVER NOW REQUIRES A DEMOTE REASON — good. Delete this test and assert it "
        "the way test_wont_fix_requires_a_reason_because_the_server_does does."
    )
    assert "A demote reason is required" in client_src, (
        "the client no longer enforces it either, so nothing does"
    )


def test_overtaken_by_events_is_a_reason_and_not_a_fourth_status():
    """
    Rick's phrase for a row the world moved past. Amendment 6 ruled it belongs in
    the drop REASON, not in the status vocabulary: a status must be legal-from
    somewhere, ranked, coloured and counted, and this phrase needs none of that.

    So it ships as a datalist suggestion on the drop-reason input — easy to type,
    invisible to every status-shaped code path.
    """
    page = PAGE.read_text( encoding="utf-8" )
    assert 'id="task-drop-reason-suggestions"' in page
    # 🔴 MATCH THE OPTION, NOT THE PHRASE. The first cut asserted `"Overtaken by
    # events" in page`, which the HTML COMMENT above the datalist satisfies all by
    # itself — deleting the actual <option> left the suite green. The test was
    # reading my own prose explaining the feature and reporting it as the feature.
    assert '<option value="Overtaken by events">' in page, (
        "the suggestion is gone from the datalist; a mention in a comment is not an affordance"
    )
    assert "overtaken_by_events" not in rules.VALID_STATUSES
    assert "overtaken" not in " ".join( rules.VALID_STATUSES ).lower()
