"""
PARITY-EXEMPT: A-2 #2a — mirrors no legacy passage: this pins a CSS-cascade
invariant found while building #2a, and the legacy client has no counterpart to it.

Every section the multiplexer toolbar toggles must really disappear when hidden.

SectionToolbarRenderer hides a section by setting its `hidden` attribute. The
browser's own `[hidden] { display: none }` loses to any author rule that sets a
`display`, so a section styled `#some-section { display: flex }` stays on screen
with its toolbar button dimmed. happy-dom has no cascade, so the TypeScript
toolbar tests read `hidden` back as hidden either way and cannot see this.

Found building parity A-2 #2a (2026-09-16): `#action-required-section` sets
`display: flex` in two sheets, so its new `⚠️` toggle would have hidden nothing.
`#commons-activity-pane[hidden]` is the precedent companion rule;
test_flow_ratio_hidden_attribute_is_honoured.py is the same trap on one element.

The predicate, rather than a list: for every toggled id, if any rule whose
selector is exactly `#<id>` sets a display other than `none` in a sheet the page
links, then some linked sheet must carry `#<id>[hidden]` with `display: none`.
It reads id selectors only; a class rule on the same element is not checked.
"""

import re
from pathlib import Path

import pytest

import cosa.utils.util as cu


ROOT          = Path( cu.get_project_root() )
HTML_PATH     = ROOT / "src/lupin_app/static/html/multiplexer.html"
TOGGLES_PATH  = ROOT / "src/lupin_app/static/js/multiplexer/render/templates/sectionToolbar.ts"
STATIC_CSS    = ROOT / "src/lupin_app/static/css"


def _toggled_ids():
    """
    Read the section ids from SECTION_TOGGLES in the toolbar template source.

    Ensures:
        - returns the ids in declaration order, one per `sectionId: "…"` entry
    """
    return re.findall( r'sectionId:\s*"([^"]+)"', TOGGLES_PATH.read_text( encoding="utf-8" ) )


def _linked_css():
    """
    Return the text of every stylesheet multiplexer.html links, comments stripped.

    Ensures:
        - one string per `/static/css/….css` href that exists on disk
    """
    html  = HTML_PATH.read_text( encoding="utf-8" )
    hrefs = re.findall( r'href="/static/css/([^"]+\.css)"', html )
    texts = []
    for href in hrefs:
        path = STATIC_CSS / href
        if path.exists():
            texts.append( re.sub( r"/\*.*?\*/", "", path.read_text( encoding="utf-8" ), flags=re.S ) )
    return texts


def _displays_for( css_texts, selector ):
    """
    Return every `display` value set by a rule whose selector list names `selector` exactly.

    Requires:
        - css_texts holds comment-free stylesheet sources
    """
    values = []
    for text in css_texts:
        for sel, body in re.findall( r"([^{}]+)\{([^{}]*)\}", text ):
            if selector in [ part.strip() for part in sel.split( "," ) ]:
                values += [ v.strip() for v in re.findall( r"\bdisplay\s*:\s*([^;]+)", body ) ]
    return values


@pytest.fixture( scope="module" )
def css_texts():
    return _linked_css()


def test_the_sweeps_reach_real_populations( css_texts ):
    """Positive controls: a sweep over nothing would pass every assertion below."""
    ids = _toggled_ids()
    assert len( ids ) >= 10, f"only { len( ids ) } toggled ids read from { TOGGLES_PATH }"
    assert "action-required-section" in ids
    assert len( css_texts ) >= 10, f"only { len( css_texts ) } linked stylesheets read"
    assert any( v != "none" for v in _displays_for( css_texts, "#action-required-section" ) ), (
        "the instrument can no longer see #action-required-section's display rule — the case "
        "that motivated this file. Either the rule is gone (then say so) or the parser broke"
    )
    assert "none" in _displays_for( css_texts, "#commons-activity-pane[hidden]" ), (
        "the instrument cannot find the known-good companion rule for the commons pane"
    )


def test_every_toggled_section_with_a_display_has_a_hidden_companion( css_texts ):
    """A toggle that dims its button but leaves the section on screen is a dead control."""
    inert = []
    for section_id in _toggled_ids():
        sets_display = any( v != "none" for v in _displays_for( css_texts, f"#{ section_id }" ) )
        if sets_display and "none" not in _displays_for( css_texts, f"#{ section_id }[hidden]" ):
            inert.append( section_id )
    assert inert == [], (
        f"these toggled sections set a `display`, which beats `[hidden]`, and have no "
        f"`#<id>[hidden] {{ display: none }}` rule, so the toolbar cannot hide them: { inert }"
    )
