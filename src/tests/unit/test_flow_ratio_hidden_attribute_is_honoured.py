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

    html = ( Path( cu.get_project_root() ) /
             "src/lupin_app/static/html/notifications.html" ).read_text( encoding="utf-8" )
    assert html.count( 'class="flow-ratio-field"' ) == 2, (
        "expected exactly two .flow-ratio-field wrappers, one per label+slider pair"
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
