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
import shutil
import subprocess

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


def strip_js_comments( source ):
    r"""
    Return `source` with its comments removed, so an assertion can be made about
    the CODE rather than about the prose describing it.

    🔴 WHY THIS EXISTS. Three assertions in one sitting passed or failed on a
    comment instead of on code, and the failure is always the flattering direction
    — the file "contains" the thing because the docstring explaining it does:

      · `assert "isTerminal" in src` held against `const isTerminal = false;`
      · `assert "Overtaken by events" in page` held against the HTML comment
        explaining the option, after the option itself was deleted
      · `assert "Promise.all" not in src` FAILED against a comment that says
        "SEQUENTIAL, NOT Promise.all" — the code has never called it

    The pattern is one thing, not three: **a test that reads source cannot tell an
    implementation from an explanation of an implementation.** Absence assertions
    are the dangerous half — well-commented code is the most likely to fail them,
    which punishes exactly the code you want.

    ⚠️ BLOCK COMMENTS NEED DOTALL. `/\*.*?\*/` without it matches nothing across
    lines, and every docstring here is multi-line — the strip would silently do
    nothing and every assertion would read the prose it was meant to skip.

    ⚠️ LINE COMMENTS ARE STRIPPED ONLY AT LINE START (after whitespace), never
    mid-line. A mid-line `//` rule would eat the `//` in every `https://` URL and
    in the query strings this suite asserts on.

    Requires:
        - source is the JS text

    Ensures:
        - block comments and whole-line `//` comments are removed
        - a `//` inside a string on a code line survives untouched
        - returns a string of the same line count (comments blanked, not deleted),
          so a reported offset still points near the right place
    """
    without_blocks = re.sub( r"/\*.*?\*/", lambda m: "\n" * m.group( 0 ).count( "\n" ), source, flags=re.DOTALL )
    return re.sub( r"^\s*//.*$", "", without_blocks, flags=re.MULTILINE )


def function_body( code, signature, until=None ):
    """
    Slice one function's body out of the client source by its EXACT signature.

    🔴 DO NOT SLICE ON THE BARE FUNCTION NAME. `split( name )[ 1 ]` and
    `split( name )[ -1 ]` are each right exactly half the time and neither is
    right twice: whether the definition or a call site comes first depends on
    where the caller happens to sit in the file. Both mistakes were made in this
    suite within one sitting — `[ 1 ]` sliced the caller for a function defined
    below its use, then `[ -1 ]` sliced past the definition for one defined above
    it. Both failures LOOK like the code is missing the thing being asserted.

    The signature is unambiguous: a call site never carries the parameter list and
    the opening brace.

    Requires:
        - signature appears exactly once in `code` (asserted, not assumed)

    ⚠️ THE END OF THE SLICE MATTERS AS MUCH AS THE START. A fixed character window
    overruns into whatever method happens to sit below, and then an ABSENCE
    assertion fails on the neighbour's code — measured here: the filer-grouping
    check read on into `_taskOwnerLabel` and reported that the holding area groups
    by owner. So the default end is the NEXT method definition, not a byte count.

    Requires:
        - signature appears exactly once in `code` (asserted, not assumed)

    Ensures:
        - returns the text from the signature to `until`, or to the next
          four-space-indented method definition, whichever was asked for
        - never silently includes a neighbouring function
    """
    assert code.count( signature ) == 1, (
        f"{signature!r} appears {code.count( signature )} times — the slice would be ambiguous"
    )
    body = code.split( signature )[ 1 ]
    if until:
        return body.split( until )[ 0 ]
    # Next sibling method: a newline, exactly four spaces, a name, an open paren.
    # `async ` is matched too, or an async neighbour would not terminate the slice.
    nxt = re.search( r"\n    (?:async )?[A-Za-z_$][\w$]*\s*\(", body )
    return body[ :nxt.start() ] if nxt else body


@pytest.fixture( scope="module" )
def client_code( client_src ):
    """Ensures: the client asset with every comment stripped — code only."""
    return strip_js_comments( client_src )


# ─────────────────────────────── the corpora, and their sizes ───────────────────
#
# 🔴 WHY THESE EXIST. Every assertion in this file used to be a substring check over
# the WHOLE client asset, which cannot tell where a string SITS — in the rendered
# markup, in a handler, in a lookup table, in a comment, or in code nothing calls.
# Measured at 9efefb5c: replacing the actions cell's entire returned markup with an
# empty `<div class="task-actions"></div>` — every row on the board losing its select,
# its reason box and its Submit — left **40 of 40 green**. The strings all still
# existed somewhere; none of them was being RENDERED.
#
# ⚠️ AND THE COUNTS ARE NOT DECORATION. A guard that says "I found 5 verbs in the cell"
# fails when a verb is relocated OUT of the cell; a guard that says "park appears in
# the file" does not. The number is what converts a presence check into a locate.
#
# WHERE THESE NUMBERS COME FROM: measured off the tree at 9efefb5c, not chosen. Five
# option definitions in `_taskActionsCell`, five rows in `_verbNeeds`, four entries in
# `_verbReasonComplaint`, three controls in the cell's returned markup. The complaint
# table is FOUR because approve is the one verb that takes no reason — the asymmetry is
# pinned below rather than smoothed over, since a fifth complaint would mean approve had
# quietly grown an obligation the server does not have.
VERBS                  = ( "park", "drop", "demote", "wont_fix", "approve" )
VERBS_NEEDING_A_REASON = ( "park", "drop", "demote", "wont_fix" )
ROW_CONTROLS           = ( "task-verb-select", "task-reason-input", "task-submit-button" )


@pytest.fixture( scope="module" )
def actions_cell( client_code ):
    """
    The body of `_taskActionsCell` alone — the ONE function that renders a row's
    controls.

    Requires:
        - the cell is locatable and non-trivial (asserted here, so a slice that
          silently came back empty fails ONCE and loudly rather than making every
          per-item loop below pass vacuously)

    Ensures:
        - returns only the cell's own text, never a neighbour's
    """
    cell = function_body( client_code, "_taskActionsCell( task ) {" )
    assert len( cell ) > 500, (
        f"the actions cell sliced to {len( cell )} chars — too small to be the real cell. "
        f"Every count below would then be measuring an empty corpus, which passes every "
        f"loop it is asked about."
    )
    return cell


@pytest.fixture( scope="module" )
def actions_markup( actions_cell ):
    """
    The template literal the cell RETURNS — what actually reaches the page.

    🔴 THIS IS THE SLICE THAT CATCHES A RELOCATION. The options are computed above it;
    only what is inside this return is rendered. A cell that builds five options and
    returns an empty div passes every check made against the cell as a whole.
    """
    marker = 'return `<div class="task-actions">'
    start  = actions_cell.find( marker )
    assert start != -1, (
        "the actions cell no longer returns a `.task-actions` container — either the "
        "markup moved out of the cell, or the cell stopped rendering anything at all"
    )
    return actions_cell[ start: ]


def test_the_comment_stripper_actually_strips( client_src, client_code ):
    """
    The helper the absence assertions rest on, falsified against the file itself.
    A stripper that silently returns its input makes every test below vacuous —
    and a regex without DOTALL does exactly that.
    """
    assert len( client_code ) < len( client_src ), "nothing was stripped; the DOTALL flag is the usual cause"
    assert "SEQUENTIAL, NOT Promise.all" in client_src, "fixture prose moved; this test needs a new witness"
    assert "SEQUENTIAL, NOT Promise.all" not in client_code, "block comments survived the strip"
    assert "authedFetch" in client_code, "the stripper ate code, not just comments"


# ------------------------------------------------- the controls exist and are wired

def test_actions_column_has_a_header_and_a_cell( client_src ):
    """A cell with no header silently shifts every column right of it."""
    assert 'th class="task-col-actions"' in client_src
    assert 'td class="task-col-actions"' in client_src


def test_drop_and_park_are_dispatched_from_the_delegated_handler( client_src, actions_cell ):
    """
    The row has ONE delegated click handler. A control that renders but is not
    reachable from it is a button that does nothing — which looks identical to a
    working button until it is pressed.

    ⚠️ RE-POINTED at 46a3078c — the CLAIM is unchanged, the SHAPE it lives in moved.
    Drop and Park stopped being buttons with a handler each and became options on one
    select, posted by one Submit. A verb still has to be RENDERED, the click still has
    to be ROUTED, and the route still has to reach something that knows what the verb
    MEANS. Those were one assertion each when there was a handler per verb; they are
    three now because the merge split them across three places.

    🔴 THE HANDLER-NAME CHECK DID NOT SURVIVE AS A NAME CHECK, AND IT SHOULD NOT HAVE.
    `"_handleTaskDropClick" in client_src` asserted that a verb had somewhere to go.
    After the merge every verb goes to the SAME place, so the name is no longer what
    distinguishes drop from park — the `_verbNeeds` table row is. Pinning the shared
    handler's name for both verbs would pass identically whether or not drop exists.
    """
    # ⚠️ SCOPED TO THE CELL, not the file. `option( "drop", "Drop"` appearing SOMEWHERE
    # is satisfied by a line the cell computes and throws away; appearing in the cell is
    # the claim this test's name makes.
    for verb, label, status in ( ( "drop", "Drop", "dropped" ), ( "park", "Park", "parked" ) ):
        assert f'option( "{verb}", "{label}"' in actions_cell, (
            f"{verb} is never rendered as a verb the operator can choose"
        )
        assert re.search( rf'{verb}\s*:\s*{{ status: "{status}"', client_src ), (
            f"{verb} renders as an option but no _verbNeeds row says what it posts — "
            f"the operator can choose it and Submit refuses with 'Choose an action first'"
        )
    # The delegated entry point, unchanged by the merge: still ONE closest() match.
    assert 'target.closest( ".task-action-btn" )' in client_src
    # ...and the one route that now carries every verb.
    assert 'classList.contains( "task-submit-button" )' in client_src, (
        "the shared Submit is rendered but the delegated handler never dispatches it — "
        "every verb at once is a button that does nothing"
    )


def test_the_transition_endpoint_is_actually_called( client_src ):
    """
    Before this change the client called NO transition endpoint at all — it could
    render a parked badge and could not park anything. This is the assertion that
    would have been red for the whole life of the file until today.
    """
    assert "/transition" in client_src
    assert "to_status" in client_src


# ------------------------------------------------- the server's rules, mirrored honestly

def test_park_is_disabled_where_the_server_would_refuse( client_src, actions_cell ):
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
    # ⚠️ SCOPED TO THE CELL. `status === "queued"` appears in handlers and predicates
    # all over this asset, so the whole-file form of this loop passed on strings that had
    # nothing to do with the park gate.
    for status in sorted( legal ):
        assert f'status === "{status}"' in actions_cell, (
            f"client does not enable park from {status!r}, which the server permits"
        )
    assert "task-action-disabled" in actions_cell
    assert 'aria-disabled="true"' in actions_cell


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
#
# 🔴 THE LITERAL CACHE-BUST GUARD THAT LIVED HERE IS DELETED, AND ITS PROPERTY IS NOW
# GUARDED DERIVED. `test_the_cache_bust_tokens_were_bumped_with_the_assets` asserted
# only that the two tokens were not equal to two hard-coded strings ("20260902g",
# "20260902c"). That goes green the moment they are bumped once and says nothing
# about every slice after — a baseline that must be hand-bumped each slice is the
# same defect it was written to catch, one level up.
#
# Replaced by two derived guards in
# `src/tests/unit/test_task_body_overlay_cache_bust.py`, over EVERY versioned asset
# on the page rather than these two:
#
#   test_versioned_asset_token_followed_its_last_change  — the token today must
#     differ from the one the page carried at the parent of the asset's last commit
#   test_uncommitted_asset_edit_bumped_its_token         — an asset dirty against
#     HEAD must carry a token that is also different from HEAD's
#
# Both read their expected value out of git at run time; no literal token appears in
# either assertion. Both were falsified before this deletion (breaks A-D): editing
# notifications.js without bumping its token reddens exactly one named case, and
# reverting the token to its pre-9e27a64f value reddens the commit-ordered case
# while the pre-existing DATE comparison stays GREEN — which is the whole reason a
# second guard was needed. That date test compares an 8-digit day against a commit
# day, and eleven commits touched notifications.js on 2026-09-02, so it cannot see
# inside the window the asset is actually edited in.


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


def test_the_three_new_controls_are_rendered_and_dispatched( client_src, actions_cell ):
    """
    A control that renders but is unreachable from the ONE delegated click handler
    is a button that does nothing — which looks identical to a working button until
    it is pressed.
    """
    # ⚠️ RE-POINTED at 46a3078c. Three buttons with three handlers became three
    # options on one select behind one Submit. Every assertion below is the same
    # question asked of the new shape: is it rendered, does something know what it
    # means, and does a click reach that something.
    for verb, label, status in (
        ( "wont_fix", "Won\'t fix", "wont_fix" ),
        ( "demote",   "Demote",     "not_approved" ),
        ( "approve",  "Approve",    "queued" ),
    ):
        assert f'option( "{verb}", "{label}"' in actions_cell, f"{verb} is never rendered"
        assert re.search( rf'{verb}\s*:\s*{{ status: "{status}"', client_src ), (
            f"{verb} has no _verbNeeds row — nothing knows what it posts"
        )
    # ONE dispatch now serves all three, so this is asserted once rather than per verb.
    # 🔴 AND THE VERB MUST BE READ OFF THE SELECT INSIDE THAT HANDLER, or the shared
    # route reaches a handler that cannot tell the three apart — which is a dispatch
    # that exists and still does nothing, the exact defect this test is named for.
    assert 'classList.contains( "task-submit-button" )' in client_src, (
        "the shared Submit renders but the delegated handler never dispatches it"
    )
    assert 'const verb  = select ? select.value : "";' in client_src, (
        "the shared handler does not read the chosen verb — one route to one action "
        "is five controls merged into one that only ever does the same thing"
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


def test_terminal_rows_offer_no_controls_at_all( client_src, client_code, actions_cell, actions_markup ):
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
    # ...and that each verb's enabled flag actually READS it.
    # ⚠️ RE-POINTED at 46a3078c: the three buttons became options, so the thing that
    # carries the gate is the option's `enabled` argument rather than a button class.
    for verb, gate in ( ( "drop", "!isTerminal" ), ( "wont_fix", "!isTerminal" ),
                        ( "demote", "demoteLegal" ) ):
        assert re.search( rf'option\( "{verb}", "[^"]+",\s*{re.escape( gate )}', actions_cell ), (
            f"the {verb} option no longer gates on {gate} — it is offered on a row the "
            f"server refuses outright"
        )
    assert re.search( r"demoteLegal = !isTerminal", client_src ), (
        "demoteLegal no longer derives from isTerminal — the demote gate is now a "
        "second, independent rule that can drift from the terminal one"
    )
    assert "!isTerminal" in client_code, "no control gates on isTerminal at all"
    assert "terminal rows are append-only and have no transitions out" in client_src
    # 🔴 AND THE SELECT, THE BOX AND SUBMIT THEMSELVES — NOT ONLY THE OPTIONS. Rio's
    # TypeScript twin found this by a SURVIVING MUTATION: deleting the terminal
    # `disabled` from the three controls reddened nothing, because with every option
    # greyed Submit refuses with "Choose an action first" and the row is not exploitable.
    # Present, correct, and untestable-if-wrong — which is a third state, not a pass.
    assert 'const off = isTerminal ?' in actions_cell, (
        "the select / reason box / Submit are no longer disabled on a terminal row; "
        "the greyed options alone leave three live controls on an append-only row"
    )
    assert 'disabled aria-disabled="true"' in actions_cell, (
        "the terminal controls are disabled for the mouse and not for a screen reader"
    )
    # ...and `off` has to be INTERPOLATED into all three controls, not merely computed.
    # Counted, because "off appears in the markup" is true of one control as easily as
    # of three, and one live Submit on an append-only row is the whole defect.
    assert actions_markup.count( "${off}" ) == 3, (
        f"the terminal-disable flag reaches {actions_markup.count( '${off}' )} of 3 "
        f"controls — the rest stay live on a row the server refuses outright"
    )


def test_the_cell_RENDERS_the_controls_it_computes( actions_markup ):
    """
    🔴 THE GUARD THE WHOLE FILE WAS MISSING, AND THE ARM THAT PROVES IT. At 9efefb5c I
    replaced this cell's returned markup with an empty `<div class="task-actions"></div>`
    — no select, no reason box, no Submit, on every row of every pane — and the suite
    reported **40 passed**. Not two reds, not one. Zero.

    Nothing was wrong with the assertions. They asked whether strings EXISTED, and the
    strings still existed: `task-verb-select` in a querySelector, `option( "park"` in the
    lines above the return, `task-submit-button` in the delegated dispatcher. Deleting
    every control from the page moved none of them.

    ⇒ So this asks the only question that separates a rendered control from a mentioned
    one: is it inside what the cell RETURNS, and is the computed option list actually
    interpolated into it.

    Ensures:
        - all three row controls appear in the returned markup, counted not merely found
        - the computed `options` string reaches the markup rather than being discarded
    """
    found = [ c for c in ROW_CONTROLS if f"task-action-input {c}" in actions_markup
                                      or f'class="{c}"' in actions_markup
                                      or f"task-action-btn {c}" in actions_markup ]
    assert len( found ) == len( ROW_CONTROLS ), (
        f"the cell returns {len( found )} of {len( ROW_CONTROLS )} row controls "
        f"({found}) — the missing ones are computed and never rendered"
    )
    # 🔴 THE INTERPOLATION IS THE OTHER HALF. Five options built and not placed into the
    # select is the same defect one level in: the verbs exist, the operator cannot reach
    # them, and every count taken over the cell as a whole still reads five.
    assert "${options}" in actions_markup, (
        "the option list is built and never interpolated into the select — the row "
        "renders a chooser with nothing to choose"
    )


def test_every_verb_has_a_row_in_EVERY_table_that_governs_it( actions_cell, client_code ):
    """
    Three tables govern a verb and they are in three different functions: the cell says
    it can be CHOSEN, `_verbNeeds` says what it POSTS, `_verbReasonComplaint` says what it
    COMPLAINS when its reason is blank. A verb present in one and absent from another is
    a control the operator can select and that then refuses, or refuses without saying why.

    ⚠️ THE EXPECTED SETS ARE LITERALS, DELIBERATELY. Comparing the cell's verbs against
    `_verbNeeds`' verbs would be two sides of one `==` that both move when the client
    moves — a tautology that cannot fail. `VERBS` is written out by hand, so one side of
    every comparison here is something the client cannot edit.

    Ensures:
        - each corpus is located and counted before any per-verb claim is made
        - the reason-complaint table stays one SHORT, and approve is the one missing
    """
    options   = re.findall( r'option\( "(\w+)"', actions_cell )
    needs     = function_body( client_code, "_verbNeeds( verb ) {" )
    posted    = re.findall( r'^\s*(\w+)\s*:\s*\{ status:', needs, re.M )
    complaint = function_body( client_code, "_verbReasonComplaint( verb ) {" )
    griped    = re.findall( r'^\s*(\w+)\s*:\s*"', complaint, re.M )

    # POSITIVE CONTROLS FIRST — an empty corpus satisfies every set comparison below by
    # being a subset of nothing, so each one has to prove it found something at all.
    assert len( options ) >= len( VERBS ), (
        f"the cell defines {len( options )} options, expected at least {len( VERBS )}: {options}"
    )
    assert len( posted ) >= len( VERBS ), (
        f"_verbNeeds holds {len( posted )} rows, expected at least {len( VERBS )}: {posted}"
    )
    assert len( griped ) >= len( VERBS_NEEDING_A_REASON ), (
        f"_verbReasonComplaint holds {len( griped )} entries, expected at least "
        f"{len( VERBS_NEEDING_A_REASON )}: {griped}"
    )

    assert set( options ) == set( VERBS ), f"the cell offers {sorted( set( options ) )}"
    assert set( posted )  == set( VERBS ), f"_verbNeeds covers {sorted( set( posted ) )}"
    assert set( griped )  == set( VERBS_NEEDING_A_REASON ), (
        f"_verbReasonComplaint covers {sorted( set( griped ) )} — five complaints would "
        f"mean approve had grown a reason requirement the server does not have; three "
        f"would mean a verb refuses a blank reason without saying which obligation it is"
    )


def test_approve_and_demote_are_never_both_live_on_one_row( client_src, actions_cell ):
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
    assert 'status === "not_approved"' in actions_cell, "the client never computes the held case"
    assert "isHeld" in actions_cell
    assert "demoteLegal = !isTerminal && !isHeld" in actions_cell
    # Counted: approve is live on exactly the held case and demote on its complement.
    assert actions_cell.count( 'option( "approve", "Approve", isHeld' ) == 1, (
        "approve is no longer gated on isHeld alone — the exclusion has a second rule "
        "that can drift from demote's"
    )


def test_approve_does_not_second_guess_the_server_allowlist( client_src, client_code ):
    """
    Rick ruled that either a manager or he suffices — "for now" — so the approver
    allowlist is server-side configuration, editable without a deploy. A client-side
    copy of a rule that is explicitly provisional would refuse people the server
    would have allowed, and would drift the moment the configuration changed.

    So approve sends the transition and SURFACES the refusal rather than pre-empting
    it: no allowlist, no persona check, no is-approver branch in the client.
    """
    # ⚠️ RE-POINTED at 46a3078c. The literal "Approve refused: " was built by the
    # approve handler; the five handlers became one, so the stripe is now composed from
    # the verb's own label. Same claim: the client SHOWS the server's refusal rather
    # than pre-empting it — and it still names the verb, so a refusal on a busy board
    # says which action was refused.
    assert 'refused: ${result.message}' in client_src, (
        "the client no longer surfaces the server's own refusal message verbatim"
    )
    assert 'approve: "Approve"' in client_src, (
        "approve has no label for the refusal stripe — a refusal that cannot name its "
        "verb is a refusal the operator cannot act on"
    )
    for forbidden in ( "isApprover", "approverAllowlist", "APPROVER_ALLOWLIST" ):
        assert forbidden not in client_code, (
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


# ------------------------------------------------- slice 3: the holding-area view
#
# `not_approved` rows are invisible to the board query BY DESIGN, so the holding
# area is a second pane fed by a second query. Most of what can go wrong here is
# a batch that reports success it did not have.

SHARED_QUERY = REPO_ROOT / "src" / "lupin_app" / "static" / "js" / "shared" / "task-list-query.js"


@pytest.fixture( scope="module" )
def query_src():
    """Ensures: the shared query module's text. Fails loudly when absent."""
    assert SHARED_QUERY.is_file(), f"shared query module missing: {SHARED_QUERY}"
    return SHARED_QUERY.read_text( encoding="utf-8" )


def test_held_rows_are_invisible_to_the_board_query( client_src ):
    """
    The premise the whole pane rests on. `not_approved` is in the repository's
    BOARD_INVISIBLE_STATUSES, so the board CANNOT show these rows — which is the
    gate working, not a discrepancy. If this ever stops being true the second pane
    is redundant and the board is leaking unapproved work as live work.
    """
    assert rules.NOT_APPROVED_STATUS in rules.BOARD_INVISIBLE_STATUSES, (
        "not_approved is no longer hidden from the board; the board is now showing "
        "unapproved rows as live work, which is what the gate exists to prevent"
    )


def test_the_holding_query_names_the_status_which_is_what_defeats_the_denylist( query_src ):
    """
    🔴 THE NON-OBVIOUS MECHANIC. `_apply_owed_filter` applies the invisible-status
    denylist only `if not include_terminal and status is None`. So naming the
    status explicitly is what takes the row OUT of the denylist's reach — there is
    no `include_not_approved` flag, and adding one would have been the wrong fix.

    Asserted against the repository source rather than remembered, because the
    whole pane silently returns nothing if that condition changes shape.
    """
    repo = ( REPO_ROOT / "src" / "cosa" / "rest" / "db" / "repositories" / "task_repository.py" ).read_text( encoding="utf-8" )
    assert "if not include_terminal and status is None:" in repo, (
        "the denylist's bypass condition changed shape; the holding-area query may "
        "now return an empty pane with no error"
    )
    # Asserted on the EXPORTED LITERAL, not on the file: this module explains
    # `status=not_approved` at length in its own comment, so a source-wide search
    # stayed green after the query itself was changed to status=queued.
    assert 'export const HOLDING_AREA_QUERY = "/api/tasks?limit=500&unscoped_audit=true&status=not_approved&char_budget=0";' in query_src, (
        "the holding query no longer asks for not_approved by name — it will now "
        "either return the wrong rows or be caught by the invisible-status denylist "
        "and return none, with no error either way"
    )


def test_the_holding_query_is_not_a_second_hand_maintained_literal( client_src, client_code, query_src ):
    """
    Two task-list literals had already drifted once — one carried
    `include_terminal=true` and silently dropped 671 rows. The holding query lives
    in the SAME shared module for the same reason, and the client reads it off
    `window` at call time rather than carrying a fallback string.
    """
    assert "LUPIN_HOLDING_AREA_QUERY" in query_src, "the query is not published for the classic-script consumer"
    assert "window.LUPIN_HOLDING_AREA_QUERY" in client_src, "the client does not read the shared query"
    assert "/api/tasks?limit=500&unscoped_audit=true&status=not_approved" not in client_code, (
        "the client carries its own copy of the holding query — the exact duplication "
        "that let the task-list literals drift"
    )


def test_a_missing_query_module_is_its_own_state_not_an_outage( client_code ):
    """
    A 404'd static asset and a downed store are different failures with different
    remedies, and this poll repeats every 60s. Collapsing them has an operator
    triaging a deploy defect as an outage indefinitely.
    """
    # Counted in CODE, not in the file: both fetchers document this state at length,
    # so counting the raw source found four "occurrences" of a return that had been
    # deleted. Proved by changing the holding fetcher's return and watching this stay
    # green.
    assert client_code.count( 'return { status: "query_unavailable", tasks: null };' ) == 2, (
        "the holding-area fetch does not distinguish a missing query module from an "
        "outage — an operator then triages a deploy defect as an outage, every 60s, "
        "indefinitely"
    )
    assert "Holding-area query missing" in client_code


def test_the_batch_reports_partial_failure_instead_of_looking_successful( client_src ):
    """
    🔴 THE ONE THAT EARNS ITS KEEP IN THIS SLICE. The obvious batch fires N
    requests, awaits them and refreshes — rendering a shorter list, which LOOKS
    like success. Two rows refused out of eight are still on screen with nothing
    saying why, and the operator reads the shrunken list as "it worked".

    So the batch counts both outcomes and keeps the FIRST server message, which is
    the one carrying the actor and the allowlist on a 403.
    """
    assert "refused. First refusal:" in client_src, "a partial batch failure renders as success"
    assert "firstError" in client_src


def test_the_batch_is_sequential_so_its_failure_report_is_reproducible( client_src, client_code ):
    """
    The refusals worth reading here are authorization refusals. Firing eight at
    once against an allowlist check produces eight identical 403s in a race whose
    order is not reproducible, so "the first refusal" would name a different row
    each run. One at a time is slower and its report is stable.
    """
    assert "Promise.all" not in function_body( client_code, "_applyHoldingBatch( filer, toStatus, extras, verb ) {" ), (
        "the holding batch fires concurrently; its first-refusal report is then a race"
    )
    assert "for ( const id of ids )" in client_src


def test_the_batch_reads_row_ids_from_the_DOM_not_from_a_cached_list( client_code ):
    """
    The pane repaints on every 60s poll. A list captured at render time goes stale
    the moment a peer approves something, and the batch would then act on ids that
    had already moved. What is on screen is what the operator pressed about.
    """
    assert "_heldRowIdsForFiler" in client_code
    body = function_body( client_code, "_heldRowIdsForFiler( filer ) {" )
    # The ids must come off the GROUP ELEMENT found in the live DOM. Asserting only
    # that "querySelectorAll" appears somewhere in the body survives neutering the
    # element lookup above it, which is how a cached list would actually be
    # reintroduced.
    assert "document.querySelector(" in body, "the group element is not looked up in the live DOM"
    assert "group.querySelectorAll(" in body, "the ids are not read from that group element"


def test_batch_wont_fix_requires_its_one_reason_up_front( client_src ):
    """
    The server requires a non-blank reason on EACH `->wont_fix`. Without the
    up-front check the operator gets N identical 422s and has to read them one at a
    time to learn a single fact.
    """
    errors = rules.validate_transition(
        from_status="not_approved", to_status="wont_fix", authority="user_direct", reason=""
    )
    assert any( "reason is REQUIRED" in e for e in errors )
    assert "A reason is required — it will be applied to every row in this group." in client_src


def test_an_empty_holding_area_says_so_in_words( client_src ):
    """
    This pane is expected to be empty most of the time, which is exactly when a
    silent blank is most likely to be read as "broken" and least likely to be
    checked against anything.
    """
    assert "Nothing waiting on triage." in client_src


def test_the_table_header_has_one_source_shared_with_the_rows( client_code ):
    """
    The holding area renders `_renderTaskRow` output — twelve cells. A second
    hand-written <thead> there could drift from the row renderer and would then
    mislabel every column to the right of the drift, silently, because the table
    still renders perfectly.

    The row's error stripe spans the same twelve columns, so the colspan is part of
    the same contract.
    """
    assert client_code.count( '<th class="task-col-id">ID</th>' ) == 1, (
        "the table header exists in more than one place and can drift from the rows"
    )
    # ...and the holding table must actually CALL it. Asserting the header exists
    # once stays true when the second table simply stops rendering one — measured:
    # deleting the call left this test green and the pane headerless.
    group_renderer = function_body( client_code, "_renderHoldingAreaGroup( filer, tasks ) {" )
    assert "_taskTableHeaderRow()" in group_renderer, (
        "the holding-area table renders rows with no header; twelve unlabelled columns"
    )
    assert 'colspan="12"' in client_code


def test_the_holding_area_rides_the_task_list_tick( client_code ):
    """
    Two panes on two timers read as a bug the first time they disagree. The
    holding area cannot share the board's COMPOSITE (different query), so it shares
    its TICK instead.
    """
    # SCOPED TO refreshTaskList. An unscoped search matched the identical call at the
    # end of _applyHoldingBatch, so deleting the one on the tick left this green and
    # the pane only ever refreshed when somebody pressed a batch button — i.e. it
    # went stale for every reader who was just watching.
    tick = client_code.split( "async refreshTaskList()" )[ -1 ].split( "startTaskListPolling" )[ 0 ]
    assert "await this.refreshHoldingArea();" in tick, (
        "the holding area is not refreshed by the task-list tick; it will only update "
        "when an operator presses a batch control"
    )
    assert "_holdingAreaFetchInFlight" in client_code, "no in-flight debounce; a manual press on a tick double-fetches"


def test_the_holding_pane_is_grouped_by_filer_not_owner( client_src, client_code ):
    """
    Triage asks "what did this person file". `created_by` and `owner_persona`
    disagree on 3 of 13 live rows, so grouping on the owner would file roughly a
    quarter of the rows under the wrong person in the one view whose entire
    organising principle is who put them there.
    """
    assert "_groupHeldRowsByFiler" in client_src
    grouper = function_body( client_code, "_groupHeldRowsByFiler( tasks ) {" )
    assert "_taskFilerLabel" in grouper
    assert "owner_persona" not in grouper, "the holding area groups on the owner, not the filer"


# ------------------------------------------------- the epic board acts, it does not only report


def test_the_epic_board_carries_the_same_controls( client_code ):
    """
    Rick's order named three panes, not two: "the UI toggles and controls that I
    need to manage the holding area along with the epic board along with the task
    list". The epic row was read-only, so a row noticed here had to be found again
    in the pane above before anything could be done about it.

    The narrowness rule for this pane is about not duplicating INFORMATION. A
    control is not information.
    """
    assert 'th class="epic-col-actions"' in client_code, "the epic board has no Actions header"
    assert 'td class="epic-col-actions"' in client_code, "the epic board has no Actions cell"


def test_the_epic_board_reuses_the_shared_actions_cell( client_code ):
    """
    🔴 THE PROPERTY THAT MATTERS, not the presence of buttons. `_taskActionsCell`
    carries every legality rule — park's legal-from set, the terminal lockout, the
    approve/demote mutual exclusion. A hand-rolled copy in the epic renderer would
    be a second place for all of those to drift out of step with the server, and
    the drift would surface as 422s on one pane and not the other.
    """
    epic_row = function_body( client_code, "_renderEpicRow( task ) {" )
    assert "this._taskActionsCell( task )" in epic_row, (
        "the epic board builds its own controls instead of reusing the shared cell"
    )
    for rolled_by_hand in ( "task-drop-button", "task-park-button", "task-wont-fix-button" ):
        assert rolled_by_hand not in epic_row, (
            f"the epic renderer emits {rolled_by_hand} directly — a second copy of the legality rules"
        )


def test_the_epic_colspans_moved_with_the_new_column( client_code ):
    """
    A group header, a story row and an error stripe all span the epic table. Add a
    column and leave a colspan behind and the table still renders perfectly — it
    just stops spanning, which reads as a styling quirk rather than as the missed
    edit it is. Same coupling the twelve-column task table documents.
    """
    epic = function_body( client_code, "_renderEpicRow( task ) {", until="renderEpicBoard(" )
    assert 'colspan="4"' not in epic, (
        "an epic-table colspan still says 4 after the Actions column was added"
    )
    assert epic.count( 'colspan="5"' ) >= 3, (
        "expected the error stripe, the group header and the story row to span 5 columns"
    )


# ------------------------------------------------- the check the other 34 cannot make


def test_the_shipped_client_actually_parses():
    """
    🔴 EVERY OTHER TEST IN THIS FILE READS THE CLIENT AS TEXT AND NONE OF THEM RUNS
    IT. A stray brace, a bad template literal, a duplicate `const` — the file would
    still contain every string these tests search for, all 34 would pass, and the
    browser would fail to parse the script and render a dead page. The suite would
    be entirely green about an application that does not start.

    That is not a hypothetical gap in careful work; it is the STRUCTURAL limit of
    asserting on source text, and it applies hardest to a 22,000-line file edited by
    string replacement, which is exactly how this slice was built.

    ⚠️ A SKIP HERE IS A REAL RESULT, NOT A PASS. If node is missing the check did not
    happen, and the message says so rather than letting an absent tool read as a
    clean bill of health.
    """
    node = shutil.which( "node" )
    if node is None:
        pytest.skip( "node not on PATH — THE PARSE CHECK DID NOT RUN; the other tests cannot cover this" )

    for asset in ( CLIENT, SHARED_QUERY ):
        result = subprocess.run(
            [ node, "--check", str( asset ) ],
            capture_output=True, text=True, timeout=60
        )
        assert result.returncode == 0, (
            f"{asset.name} does not parse — the browser would render a dead page while "
            f"every source-text assertion in this file stayed green:\n{result.stderr}"
        )


def test_the_holding_area_cannot_truncate_silently( client_code ):
    """
    🔴 MEASURED AGAINST THE LIVE SERVER, not reasoned from symmetry. Called
    :7999 today with the same endpoint and the same limit the holding query uses:

        status=done  ->  HTTP 200, count 500, total 1912, has_more true

    Exactly 500 of 1,912 rows, and the row-cap overflow raises neither `truncated`
    nor a `warnings` entry that the client keys on. The holding area asks a
    status-filtered question of that same endpoint with that same limit, so it
    inherits the same silence the moment the triage queue passes 500 — which is
    precisely the state a holding area is supposed to reach if nobody triages it.

    The board already had this banner because silent truncation once cost 671 rows.
    The second pane shipped without it.
    """
    render = function_body( client_code, "renderHoldingArea( composite ) {" )
    assert "_renderTaskListTruncationBanner(" in render, (
        "the holding area renders no truncation banner — it will silently show 500 "
        "of N held rows, and a triage queue is the one list expected to grow"
    )
    assert render.count( "truncation +" ) == 2, (
        "the banner must prefix BOTH the empty branch and the populated one; a "
        "truncated fetch whose page happens to render empty is the quietest case"
    )


def test_each_pane_measures_itself_against_its_OWN_limit( client_code ):
    """
    The full-page trigger compares `count` to the limit the panel ASKED for. With
    two panes reading two queries, a shared hardcoded limit — or a helper that only
    ever reads the board's query — makes that trigger wrong for the second pane the
    moment the two diverge. A guard that cannot fire is the failure this whole
    mechanism exists to remove, so it must not be reintroduced one pane over.
    """
    limit_fn = function_body( client_code, "_taskListQueryLimit( queryString ) {" )
    assert "queryString" in limit_fn, "the limit helper cannot be asked about a second query"
    assert "LUPIN_TASK_LIST_QUERY" in limit_fn, "the board fallback was dropped"
    render = function_body( client_code, "renderHoldingArea( composite ) {" )
    assert "LUPIN_HOLDING_AREA_QUERY" in render, (
        "the holding pane measures itself against the BOARD's limit, not its own"
    )


def test_demote_stamps_a_triage_by_date_per_ricks_ruling( client_code ):
    """
    ⭐ RICK'S RULING, 2026-09-02 — a real keypress, not a timeout default: a held row
    comes back on a chase the way a parked row does.

    His own demotion feature is why it was needed. Demotion means the holding area
    fills from BOTH ends — new rows at the front, demoted rows at the back — so with
    no eviction the gate's own waiting room becomes the unbounded backlog the gate
    exists to prevent, moved one room over.

    ⚠️ THE STORE DOES NOT EXPIRE HELD ROWS YET, and that is a split of lanes rather
    than a gap. The read-time predicate is the store half. What matters here is that
    the client STAMPS the field from the very first demotion, so the predicate lands
    on rows that already carry a date instead of arriving to a backlog with none.
    """
    # ⚠️ RE-POINTED at 46a3078c. The per-verb `task-demote-chase` box became ONE
    # `task-chase-input`, built by _handleVerbSelectChange for whichever verb asks for a
    # date. So "demote collects a date" is now two facts, not one: the shared box exists,
    # AND demote is a verb that requires it.
    assert "task-chase-input" in client_code, "no row control collects a date at all"
    assert re.search( r'demote\s*:\s*{ status: "not_approved",\s*reason: true,\s*date: true',
                      client_code ), (
        "demote no longer requires a date — a demotion with no chase puts a row in the "
        "holding area that nothing will ever bring back"
    )
    handler = function_body( client_code, "_handleTaskSubmitClick( button ) {" )
    # 🔴 PIN THE GUARD, NOT ITS WORDING. The first cut asserted the error MESSAGE was
    # present, which survives `if ( false )` — the message sits inside the dead branch,
    # the requirement is gone, and the test is happy. Measured: I broke the condition
    # and this stayed green, in a test written after learning that exact lesson twice
    # today. The message is the symptom; the condition is the control.
    assert "if ( needs.date && !chaseDay ) {" in handler, (
        "the triage-by date is collected but not REQUIRED — a demotion with no date "
        "puts a row in the holding area that nothing will ever bring back"
    )
    assert "A triage-by date is required" in handler
    assert "next_chase_ts" in handler, "the date is collected but never sent"


def test_the_demote_date_is_converted_through_the_browser_zone( client_code ):
    """
    The same trap park already documents. `<input type="date">` yields a bare calendar
    day with no time and no zone; sent as-is it reads as midnight UTC, which lands the
    chase on the PREVIOUS EVENING for every zone west of Greenwich — i.e. all of ours.
    A held row would come back a day early, every time, and nothing would look wrong.
    """
    handler = function_body( client_code, "_handleTaskSubmitClick( button ) {" )
    assert "T09:00:00" in handler, "the demote date is not stamped with a local time"
    assert "toISOString()" in handler, "the demote date is not converted to an instant"


def test_the_holding_area_has_its_own_toolbar_toggle():
    """
    ⭐ RICK BY VOICE, 2026-09-02: "we need a toggle button in the Notifications Client
    Toolbar that hides and unhides the holding area, it needs its own toggle button."

    🔴 THE PAIRING IS THE WHOLE THING, AND EITHER HALF ALONE LOOKS FINE. The dispatcher
    is `toggleSectionVisibility( sectionId )`, which looks the section up by ID and the
    button up by `data-section`. A button whose `data-section` names no section logs
    "Section not found" to a console nobody is tailing and does nothing on screen; a
    section with no button can never be reopened once hidden. Both halves render
    perfectly in either broken state.
    """
    page = PAGE.read_text( encoding="utf-8" )
    assert 'data-section="section-holding-area"' in page, "the toolbar has no holding-area toggle"
    assert 'id="section-holding-area"'           in page, "the toggle names a section that does not exist"
    assert 'data-testid="holding-area-toolbar-btn"' in page, "the toggle is not addressable from a test"


def test_the_toggle_uses_the_shared_dispatcher_rather_than_a_second_implementation( client_code ):
    """
    `toggleSectionVisibility` already persists the choice to localStorage, dims the
    button, and scrolls the section into view. A bespoke handler for this one section
    would be a second implementation of a working mechanism — and it would be the one
    that forgets to persist, so the pane silently reappears on every reload.

    The button is therefore DECLARATIVE: `class="toolbar-btn"` + `data-section`, and no
    holding-area-specific branch anywhere in the dispatcher.
    """
    page = PAGE.read_text( encoding="utf-8" )
    assert re.search( r'class="toolbar-btn[^"]*"[^>]*data-section="section-holding-area"', page ), (
        "the holding-area toggle is not a toolbar-btn, so the section dispatcher ignores it"
    )
    body = function_body( client_code, "toggleSectionVisibility( sectionId ) {" )
    assert "section-holding-area" not in body, (
        "the dispatcher carries a holding-area special case — the toggle should need none"
    )
