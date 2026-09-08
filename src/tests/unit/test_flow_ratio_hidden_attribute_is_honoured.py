"""
The flow-ratio cluster's `hidden` attribute must actually hide it.

WHY THIS TEST IS IN PYTHON AND NOT IN THE JS SUITE. The JavaScript tests for this
cluster run under happy-dom, which implements the DOM but not the CSS cascade and
does no layout. There, `root.hidden = true` reads back as hidden whatever the
stylesheet says — so a JS test asserting the hide path passes identically whether
the page honours it or not. That test is not wrong; it simply cannot see this.

WHAT WENT WRONG, MEASURED. `.flow-ratio-controls` sets `display: flex`. An author
`display` beats the UA stylesheet's `[hidden] { display: none }` in the cascade, so
the attribute was inert: measured in Chromium against the live :7999 page, setting
`root.hidden = true` left `getComputedStyle( root ).display === "flex"` with the
element still occupying space. `_paintFlowRatioSettings` hides the cluster when the
settings endpoint is unreadable, precisely so an operator is never shown sliders
parked at their HTML defaults — a threshold the create gate is not using. With the
attribute inert, that protection did nothing.

The repo already knows this trap: `.persona-popover-borrowed[hidden]` in
multiplexer/persona-modal.css carries a comment naming the same failure, and
notifications-header.css documents the other half of the idiom (set no `display`
and the browser default wins).

This test guards the CSS text. The browser is the real instrument and a Chromium
measurement is what found the defect; this is the cheap, always-run companion that
notices if the rule is deleted.
"""

import re
from pathlib import Path

import pytest

import cosa.utils.util as cu


CSS_PATH = Path( cu.get_project_root() ) / "src/lupin_app/static/css/task-list.css"


@pytest.fixture( scope="module" )
def css():
    return CSS_PATH.read_text( encoding="utf-8" )


def _rule_body( css_text, selector ):
    """
    Return the declaration block for `selector`, or None when the rule is absent.

    Requires:
        - css_text is the stylesheet source
        - selector is a literal selector string

    Ensures:
        - returns the text between the braces of the FIRST matching rule
        - returns None when no rule with that exact selector exists
    """
    match = re.search(
        re.escape( selector ) + r"\s*\{([^}]*)\}", css_text
    )
    return match.group( 1 ) if match else None


def test_the_cluster_sets_a_display_that_would_defeat_the_hidden_attribute( css ):
    """The premise of this whole file — if it ever stops being true, say so loudly."""
    body = _rule_body( css, ".flow-ratio-controls" )
    assert body is not None, "the .flow-ratio-controls rule itself is gone"
    assert re.search( r"\bdisplay\s*:", body ), (
        "`.flow-ratio-controls` no longer sets a `display`. If that is deliberate the "
        "UA `[hidden] { display: none }` now wins on its own and the companion rule "
        "below is merely redundant — but confirm that before deleting anything."
    )


def test_a_hidden_companion_exists_so_the_attribute_is_not_inert( css ):
    """Without this rule, `els.root.hidden = true` changes nothing on screen."""
    body = _rule_body( css, ".flow-ratio-controls[hidden]" )
    assert body is not None, (
        "`.flow-ratio-controls[hidden]` is missing. `.flow-ratio-controls` sets "
        "`display: flex`, which beats the UA stylesheet's `[hidden] { display: none }`, "
        "so the cluster would render even when _paintFlowRatioSettings hides it after "
        "an unreadable settings endpoint — showing an operator a threshold the create "
        "gate is not using. Add:  .flow-ratio-controls[hidden] { display: none; }"
    )
    assert re.search( r"display\s*:\s*none", body ), (
        "the `[hidden]` companion exists but does not set `display: none`, so it does "
        "not undo the `display: flex` above it"
    )


def _flow_ratio_controls_region( html ):
    """
    Return just the flow-ratio control cluster's markup.

    Requires:
        - html is the full notifications.html text

    Ensures:
        - returns the slice from the cluster's own data-testid to the status span
          that closes it, so a `.flow-ratio-field` used elsewhere on the page can
          never satisfy or break this file's assertions

    Raises:
        - AssertionError naming the missing anchor, rather than ValueError from
          str.index — a renamed testid should tell the reader what moved
    """
    opening = 'data-testid="flow-ratio-controls"'
    closing = 'id="flow-ratio-controls-status"'

    assert opening in html, f"{opening} is gone from notifications.html — this test's region anchor moved"
    start = html.index( opening )
    assert closing in html[ start: ], f"{closing} is gone — this test's closing region anchor moved"

    return html[ start : html.index( closing, start ) ]


def test_a_label_cannot_be_wrapped_away_from_its_own_slider( css ):
    """
    Each label+slider pair is one flex item, so `flex-wrap` cannot split them.

    Measured at a 700px viewport before the fix: the "Window" label sat on row 1
    while the slider it names wrapped to row 2, leaving two labels adjacent and
    neither beside its control.
    """
    assert _rule_body( css, ".flow-ratio-field" ) is not None, (
        "`.flow-ratio-field` is gone — the six controls are direct flex children "
        "again and a wrap can separate a label from the slider it names"
    )

    # 🔴 THIS USED TO ASSERT `== 2` AND IT WENT STALE THE MOMENT A THIRD CONTROL LANDED.
    # Rick's manager-pull toggle (b2210bfd) is legitimately wrapped — it needs the same
    # no-wrap protection the sliders do — so the count reddened while nothing was wrong.
    # A count is the ENUMERATION; what the test is actually for is the PREDICATE below,
    # which passes at three, passes at four, and reddens the day somebody adds a control
    # WITHOUT a wrapper. That is the regression this file exists to catch, and the count
    # could not distinguish it from a correct addition.
    html   = ( Path( cu.get_project_root() ) /
               "src/lupin_app/static/html/notifications.html" ).read_text( encoding="utf-8" )
    region = _flow_ratio_controls_region( html )

    wrapped = re.findall( r'<span class="flow-ratio-field">.*?</span>', region, re.DOTALL )

    # Assert the loop found something BEFORE relying on it — stripping zero wrappers
    # would leave the region untouched and every assertion below would still pass.
    assert wrapped, (
        "no .flow-ratio-field wrappers in the cluster at all — either the markup lost "
        "them (a wrap can now separate a label from the control it names) or this "
        "test's region bounds no longer match the page"
    )

    # Everything a wrapper protects is now accounted for; whatever is LEFT is bare.
    bare = region
    for block in wrapped: bare = bare.replace( block, "" )

    assert "<label" not in bare, (
        f"a <label> in the flow-ratio cluster is NOT inside a .flow-ratio-field wrapper, "
        f"so a flex wrap can strand it from the control it names — the exact defect "
        f"measured at a 700px viewport. Wrap it like its {len( wrapped )} siblings."
    )
    for control in ( 'type="range"', 'type="checkbox"' ):
        assert control not in bare, (
            f"an unwrapped {control} control is a direct flex child of .flow-ratio-controls; "
            f"wrap it in a <span class=\"flow-ratio-field\"> with its label"
        )

    # And the pairing is one label per wrapper — a wrapper holding two labels re-creates
    # the adjacency the fix removed, and would survive every assertion above.
    assert len( re.findall( r"<label\b", region ) ) == len( wrapped ), (
        f"{len( re.findall( r'<label.', region ) )} labels across {len( wrapped )} wrappers — "
        f"the invariant is ONE label per wrapper, each beside the control it names"
    )


def test_the_repo_idiom_this_follows_is_still_present():
    """
    A positive control: prove the search CAN find a companion rule elsewhere.

    Without this, a passing grep above says nothing — an absent rule and a broken
    search read identically. `.persona-popover-borrowed[hidden]` is the prior
    sighting of this exact bug in this repo.
    """
    other = ( Path( cu.get_project_root() ) /
              "src/lupin_app/static/css/multiplexer/persona-modal.css" ).read_text( encoding="utf-8" )
    assert ".persona-popover-borrowed[hidden]" in other, (
        "the reference companion rule is gone; this file's premise needs re-checking"
    )


# ---------------------------------------------------------------------------
# The "updated" stamp's own line (Rick, 2026-09-01).
#
# 🔴 AUTHORSHIP: THE TWO TESTS BELOW ARE KRISHNA 🦚's, AND `a936601f` SAYS OTHERWISE.
# That commit's message claims "I wrote two" — Pocholo 📣. It is wrong. These functions,
# their docstrings and the 826px/493px Chromium measurement in them are Krishna's; the
# measurement is the same one his `a4595654` reports as "the first row loses 333px".
#
# HOW: they sat uncommitted in the shared working tree, and I assumed a file I had worked
# in was mine rather than measuring. Then `git commit -F msg -- <path>` committed them,
# which is the part worth knowing — from `git commit --help`, verbatim:
#
#     "When pathspec is given on the command line, commit the contents of the files
#      that match the pathspec without recording the changes already added to the index."
#
# It takes the WORKING TREE content of the named paths. So the pathspec form protects the
# file LIST and not the file CONTENT: it correctly kept `epic-stories.json` and two of
# worker 3's websocket files out of that commit, and could do nothing about a peer's
# uncommitted edits INSIDE a path I named. The commit looked perfectly scoped, which is
# why I reported it as clean. Krishna found it and diagnosed it; the fix he and I could
# both see — read `git diff HEAD -- <paths>` before committing and recognise whose work
# it is — is a human check, and this fleet's own doctrine says a human check is not a
# control. Left for Rick as a real gap rather than papered over.
#
# NOT REWRITTEN: a peer has built on `a936601f`. The correction lives here, in the
# artifact, because a retraction that reaches only the conversation reaches nobody.
#
# ⚠️ SCOPE OF THE SECOND TEST, also Krishna's correction. It cannot fail on the
# pre-stamp tree — it asserts `display: block` has NOT migrated onto the shared class,
# which was true before `a4595654` and after. It is a real guard on the SCOPING decision
# (a mutation moving the declaration onto `.task-list-updated` does turn it red), but it
# is not evidence for the stamp move, and it must not be counted as an arm proving it.
# ---------------------------------------------------------------------------

def test_the_updated_stamp_gets_its_own_line_left_aligned( css ):
    """
    `#task-list-updated` must be block-level with no left margin.

    It used to sit at the far right of the toggle bar — not because anything pushed
    it there, but because it was the last inline element on the row. Going block puts
    it on its own line at the h3's left edge and hands the whole first line back to
    the counts and the gate verdict. Measured in Chromium: the first row went from
    826px to 493px and the stamp's x matched the h3's own x exactly.

    Both halves matter. `display: block` alone leaves the 8px indent from the base
    rule, so the stamp would sit one notch in from everything above it.
    """
    body = _rule_body( css, "#task-list-updated" )
    assert body is not None, (
        "`#task-list-updated` is gone — the stamp is inline again and back on the "
        "first row, spending ~111px of a bar that had ~27px of slack"
    )
    assert re.search( r"display\s*:\s*block", body ), (
        "the stamp is no longer block-level, so there is no line break before it"
    )
    assert re.search( r"margin-left\s*:\s*0", body ), (
        "`display: block` without `margin-left: 0` leaves the base rule's 8px indent, "
        "so the stamp sits one notch right of the text it should line up under"
    )


def test_the_stamp_rule_is_scoped_to_the_id_not_the_shared_class( css ):
    """
    The ID scoping is a DECISION, not an accident, so it is asserted.

    `.task-list-updated` is shared: `#epic-board-updated` wears the same class in the
    Epic Board header. Rick asked about the task-list bar only, so the twin is left
    alone. If someone later moves these declarations onto the class they will change
    the Epic Board too — which may well be right, but it should be a choice somebody
    makes rather than a side effect they ship.
    """
    shared = _rule_body( css, ".task-list-updated" )
    assert shared is not None, "the shared base rule is gone"
    assert not re.search( r"display\s*:\s*block", shared ), (
        "`display: block` has moved onto the SHARED `.task-list-updated` class, which "
        "silently restyles #epic-board-updated in the Epic Board header too. If that "
        "is intended, say so — and update this test — rather than letting it ride along"
    )

    html = ( Path( cu.get_project_root() ) /
             "src/lupin_app/static/html/notifications.html" ).read_text( encoding="utf-8" )
    assert 'id="epic-board-updated" class="task-list-updated"' in html, (
        "the Epic Board stamp no longer shares this class, so the scoping rationale "
        "above is stale — re-check whether the ID scoping is still worth keeping"
    )
