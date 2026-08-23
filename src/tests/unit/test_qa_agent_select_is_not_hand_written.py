#!/usr/bin/env python3
"""
GATE 2 — no hand-written agent list survives in the Q&A card (2026.08.22 plan §6).

The plan's wording: "a grep test over notifications.html and notifications.js for
`agent router go to` string literals and for `<option value=` inside #agent-mode."

🔴 THE BLOCKER FIX (Mr. Radio's review §3). As specified, this gate FIRES ON ITS OWN
SCAFFOLDING: the Auto-Route option is legitimately hand-written and must stay, so the
grep would hit it and the gate would need an exemption — "and an exemption without a
written reason is how these guards get quietly widened later."

The fix taken is the second one he offered, because it removes the problem instead of
documenting it: Auto-Route is now a SENTINEL served in the GET /api/v2/agents response
(registry.AUTO_ROUTE_VALUE) and rendered like every other option. The page therefore
hand-writes NO option at all, and this gate needs no exemption for the dropdown —
`<option>` inside #agent-mode is simply forbidden, with nothing carved out.

WHAT IS STILL ON THE BOOKS, AND WHY THAT IS NOT THE SAME THING. Five `agent router go
to` literals remain in notifications.js. None is in the Q&A card: every one belongs to
a SUBMIT CARD that phase 6 deletes. They are pinned below as a NAMED INVENTORY rather
than skipped by a predicate — a sixth literal goes red immediately, and when phase 6
removes the cards the inventory empties and this gate tightens to zero on its own. An
inventory has an expiry; a predicate does not.

Run: PYTHONPATH=src .venv/bin/pytest src/tests/unit/test_qa_agent_select_is_not_hand_written.py -v
"""

import re

import cosa.utils.util as cu


HTML = "/src/lupin_app/static/html/notifications.html"
JS   = "/src/lupin_app/static/js/notifications.js"


def _read( relative_path ):
    return cu.get_file_as_string( cu.get_project_root() + relative_path )


def _agent_mode_select():
    """The #agent-mode element's markup, opening tag through closing tag.

    Scoped deliberately: notifications.html holds other <select>s that are correctly
    hand-written (the TTS-mode picker, for one), and a whole-file grep for <option>
    would fire on those. This gate is about the AGENT list, not about options.
    """
    html  = _read( HTML )
    start = html.index( '<select id="agent-mode"' )
    end   = html.index( "</select>", start ) + len( "</select>" )
    return html[ start:end ]


def _submit_qa_body():
    """The body of submitQA(), where the Q&A card decides where a question goes."""
    js    = _read( JS )
    start = js.index( "async submitQA()" )
    end   = js.index( "handleServerError( error )", start )
    return js[ start:end ]


# ══════════════════════════════════════════════════════════════════════════════
# The dropdown itself — no exemption, because there is nothing to exempt
# ══════════════════════════════════════════════════════════════════════════════

def test_the_agent_mode_select_contains_no_hand_written_option():
    markup = _agent_mode_select()
    assert "<option" not in markup, (
        "an <option> was hand-written back into #agent-mode. Every option, INCLUDING "
        "Auto-Route, is rendered from GET /api/v2/agents by shared/agent-select.js — "
        "a hand-written value would also be a short mode key, which /api/v2/submit "
        f"cannot route.\n{markup}"
    )


def test_the_agent_mode_select_contains_no_optgroup_either():
    # The headings are rendered too. A hand-written <optgroup> would survive the
    # option check above while quietly reintroducing half the hand-maintained list —
    # the grouping — and grouping is where the receptionist exception lives.
    assert "<optgroup" not in _agent_mode_select()


def test_the_page_names_no_routing_command():
    # The HTML must not carry a command literal in any form: not as an option value,
    # not as a data attribute, not in an onclick.
    html = _read( HTML )
    assert "agent router go to" not in html, (
        "notifications.html names a routing command — the agent list belongs in the "
        "registry, and the page should learn it from GET /api/v2/agents"
    )


def test_the_select_still_exists_and_is_still_addressable():
    # The counterweight to the three assertions above: emptying the element is the
    # goal, DELETING it would satisfy every one of them and break the card. Its
    # data-testid is what the E2E suite locates it by.
    markup = _agent_mode_select()
    assert 'data-testid="notifications-qa-mode-select"' in markup


def test_the_page_loads_the_module_that_fills_the_select():
    # And the other counterweight: an empty select plus no renderer is a card with no
    # agent list at all. notifications.js is a classic script and cannot import, so
    # the module has to be loaded by its own tag.
    html = _read( HTML )
    assert re.search( r'<script type="module" src="/static/js/shared/agent-select\.js', html ), (
        "notifications.html does not load shared/agent-select.js — #agent-mode would "
        "render empty"
    )


# ══════════════════════════════════════════════════════════════════════════════
# The remaining literals — a named inventory with an expiry, not an exemption
# ══════════════════════════════════════════════════════════════════════════════

# Every `agent router go to` literal left in notifications.js, with the card it
# belongs to and the phase that deletes it. NOT a pattern and NOT a count: adding a
# new literal turns the set-equality below red even if it also removes an old one.
KNOWN_SUBMIT_CARD_LITERALS = {
    "agent router go to claude code"              : "claude-code submit card — phase 6 deletes it",
    "agent router go to deep research"            : "research submit card — phase 6 deletes it",
    "agent router go to research to presentation" : "research submit card, presentation variant — phase 6",
    "agent router go to research to podcast"      : "research submit card, podcast variant — phase 6",
    "agent router go to presentation generator"   : "research submit card, direct-presentation path — phase 6",
}


def _literals_in_js():
    return set( re.findall( r"agent router go to [a-z]+(?: [a-z]+)*", _read( JS ) ) )


def test_no_new_routing_command_literal_appears_in_the_front_end():
    found = _literals_in_js()
    assert found == set( KNOWN_SUBMIT_CARD_LITERALS ), (
        f"new literals: {sorted( found - set( KNOWN_SUBMIT_CARD_LITERALS ) )}; "
        f"gone (delete them from KNOWN_SUBMIT_CARD_LITERALS): "
        f"{sorted( set( KNOWN_SUBMIT_CARD_LITERALS ) - found )}"
    )


def test_none_of_the_remaining_literals_is_in_the_qa_card():
    # What makes the inventory acceptable: none of these is the Q&A dropdown's
    # business. Every one sits inside a submit-card handler. If a literal ever
    # appeared inside submitQA, the dropdown would have grown a hand-written route
    # and this gate's whole subject would be back.
    assert "agent router go to" not in _submit_qa_body(), (
        "submitQA names a routing command directly — it should read the command from "
        "the #agent-mode option value, which comes from the registry"
    )


def test_the_qa_card_reads_its_command_from_the_rendered_select():
    # The positive form of the same fact, so "no literal" cannot be satisfied by a
    # card that stopped routing at all.
    assert "LUPIN_AGENT_SELECT" in _submit_qa_body(), (
        "submitQA does not consult the rendered agent select"
    )
