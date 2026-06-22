"""
WS1 single-sourcing smoke — multiplexer ↔ notifications layout parity (v0.1.9).

Plan: src/rnd/v0.1.9/2026.06.19-multiplexer-layout-parity-methodology/
      02-bridging-work-plan.md (WS1; Decisions D1 Rider A + D2)

Static / pure-Python (:7999-eligible — no server, no state mutation). This is
the WS1 *wiring* guard: it proves the contract surfaces are single-sourced from
ONE shared sheet linked by BOTH pages, in the cascade order D1 Rider A mandates,
with the D2 spacing reconciliation applied. The full computed-style Layout-Parity
Oracle (Tiers 0-3) is WS3 (a sibling builds it); this file does not duplicate it.

Verifies:
  - css/shared/notifications-surface.css exists and carries the contract surfaces.
  - notifications.html links the shared sheet BEFORE its monolith (RIDER A:
    the monolith wins any cascade conflict → legacy is the parity reference).
  - multiplexer.html links the shared sheet BEFORE the trimmed mux sheet.
  - The retired page-frame.css is no longer referenced by any page.
  - D2: the shared sheet encodes the legacy `.collapsible-section` margin model
    and the mux sheet dropped the drift-invented `#sender-cards-container` gap.
  - The mux keeps its `[data-collapsed]` collapse MECHANISM (no functional
    regression — accordions still collapse).
  - The shared contract sheet does NOT carry mux-only / mux-mechanism / disjoint
    action-required-widget rules.
"""

import os
import re

import pytest

import cosa.utils.util as cu

STATIC      = os.path.join( cu.get_project_root(), "src", "lupin_app", "static" )
SHARED_CSS  = os.path.join( STATIC, "css", "shared", "notifications-surface.css" )
MUX_CSS     = os.path.join( STATIC, "css", "multiplexer", "notifications-list.css" )
NOTIF_HTML  = os.path.join( STATIC, "html", "notifications.html" )
MUX_HTML    = os.path.join( STATIC, "html", "multiplexer.html" )

SHARED_HREF = "/static/css/shared/notifications-surface.css"
MONOLITH    = "notifications.css?v"
MUX_HREF    = "/static/css/multiplexer/notifications-list.css"


def _read( path ):
    with open( path, encoding="utf-8" ) as fh:
        return fh.read()


def _strip_css_comments( css ):
    """Return css with /* ... */ comments removed (so substring checks only see rules)."""
    return re.sub( r"/\*.*?\*/", "", css, flags=re.DOTALL )


# ---------------------------------------------------------------------------
# Shared sheet exists + carries the contract surfaces
# ---------------------------------------------------------------------------

def test_shared_sheet_exists_and_nonempty():
    assert os.path.isfile( SHARED_CSS ), f"missing shared sheet: {SHARED_CSS}"
    assert os.path.getsize( SHARED_CSS ) > 0


@pytest.mark.parametrize( "selector", [
    "*",
    ".container",
    ".sender-card",
    ".sender-card-header",
    ".date-accordion",
    ".date-accordion-messages",
    ".sender-message",
    ".message-text",
    ".expired-badge",
    ".abstract-indicator",
    ".progress-group-head",
] )
def test_shared_sheet_carries_contract_surface( selector ):
    rules = _strip_css_comments( _read( SHARED_CSS ) )
    assert selector + " {" in rules or selector + "{" in rules, \
        f"contract selector {selector!r} absent from shared sheet rules"


# ---------------------------------------------------------------------------
# Both pages link the shared sheet (single source)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize( "page", [ NOTIF_HTML, MUX_HTML ] )
def test_both_pages_link_shared_sheet( page ):
    assert SHARED_HREF in _read( page ), f"{os.path.basename( page )} does not link the shared sheet"


# ---------------------------------------------------------------------------
# RIDER A — legacy links shared BEFORE the monolith (monolith wins conflicts)
# ---------------------------------------------------------------------------

def test_legacy_links_shared_before_monolith():
    html = _read( NOTIF_HTML )
    i_shared   = html.index( SHARED_HREF )
    i_monolith = html.index( MONOLITH )
    assert i_shared < i_monolith, \
        "RIDER A violated: shared sheet must be linked BEFORE notifications.css so the monolith wins"


def test_mux_links_shared_before_mux_overrides():
    html = _read( MUX_HTML )
    i_shared = html.index( SHARED_HREF )
    i_mux    = html.index( MUX_HREF )
    assert i_shared < i_mux, \
        "shared sheet must be linked BEFORE the mux override sheet so mux overrides win where intended"


# ---------------------------------------------------------------------------
# Retired page-frame.css is gone
# ---------------------------------------------------------------------------

def test_page_frame_css_retired():
    assert not os.path.isfile( os.path.join( STATIC, "css", "multiplexer", "page-frame.css" ) ), \
        "page-frame.css should be retired (folded into the shared sheet)"
    for page in ( NOTIF_HTML, MUX_HTML ):
        # No <link> may reference the retired sheet (a doc comment naming it is fine).
        hrefs = re.findall( r'href="([^"]+)"', _read( page ) )
        assert not any( "page-frame.css" in h for h in hrefs ), \
            f"{os.path.basename( page )} still <link>s the retired page-frame.css"


# ---------------------------------------------------------------------------
# D2 — legacy margin spacing model is the contract; mux gap dropped
# ---------------------------------------------------------------------------

def test_d2_shared_encodes_collapsible_section_margin():
    rules = _strip_css_comments( _read( SHARED_CSS ) )
    assert ".collapsible-section" in rules and "margin-bottom: 30px" in rules


def test_d2_mux_dropped_sender_cards_container_gap():
    rules = _strip_css_comments( _read( MUX_CSS ) )
    # the container rule survives (structure) but its gap declaration is gone
    assert "#sender-cards-container" in rules
    container_block = rules.split( "#action-required-section" )[ 1 ].split( "}" )[ 0 ]
    assert "gap" not in container_block, "drift-invented gap not dropped from the mux container rule"


# ---------------------------------------------------------------------------
# WS2 C2-a / C2-b — selector unions single-sourced into the shared sheet
# ---------------------------------------------------------------------------

def test_c2a_persona_badge_union_in_shared():
    """C2-a: the shared sheet unions the legacy span + mux button selectors so the
    mux `<button.sender-persona-badge>` computes like the legacy `<span.persona-badge>`.
    The mux sheet no longer carries a private `.sender-persona-badge` rule."""
    shared = _strip_css_comments( _read( SHARED_CSS ) )
    assert ".persona-badge," in shared and ".sender-persona-badge" in shared, \
        "shared sheet must union .persona-badge, .sender-persona-badge (C2-a)"
    # the <button> reset that makes the button render as the span
    union_block = shared.split( ".sender-persona-badge {" )[ 1 ].split( "}" )[ 0 ]
    assert "appearance: none" in union_block and "font-family: inherit" in union_block, \
        "C2-a union must carry the <button> reset (appearance/font-family)"
    mux = _strip_css_comments( _read( MUX_CSS ) )
    assert ".sender-persona-badge {" not in mux, \
        "mux sheet must NOT keep a private .sender-persona-badge rule (moved to shared union)"


def test_c2b_collapse_union_in_shared():
    """C2-b: the shared sheet's collapse rule fires for BOTH the legacy `.collapsed`
    class AND the mux `[data-collapsed]` attribute (one contract, both clients).
    The mux sheet no longer carries a private collapse mechanism rule."""
    shared = _strip_css_comments( _read( SHARED_CSS ) )
    assert ".date-accordion-messages.collapsed" in shared, "C2-b union missing the legacy .collapsed selector"
    assert 'data-collapsed="true"' in shared, "C2-b union missing the mux [data-collapsed] selector"
    mux = _strip_css_comments( _read( MUX_CSS ) )
    assert "data-collapsed" not in mux, \
        "mux sheet must NOT keep a private [data-collapsed] collapse rule (moved to shared union)"


# ---------------------------------------------------------------------------
# Shared contract sheet stays pure — no mux-only / disjoint rules leak in
# ---------------------------------------------------------------------------

def test_shared_sheet_carries_left_accent_stripe():
    """Extraction-completeness guard (Tier-2 oracle finding, 2026-06-22): the
    monolith's `.sender-card:not(.sender-card-active) { border-left: 3px ... }`
    (notifications.css:2090-2092) must live in the shared sheet — it matches
    EVERY card the mux renders, so dropping it makes the mux compute a 1px left
    border vs legacy's 3px. Locks the rule in so a future re-drop fails loudly."""
    rules = _strip_css_comments( _read( SHARED_CSS ) )
    assert ".sender-card:not( .sender-card-active )" in rules, \
        "shared sheet dropped the .sender-card:not(.sender-card-active) left-accent rule"
    # the 3px width is the property the Tier-2 oracle measures (border-left-width)
    stripe_block = rules.split( ".sender-card:not( .sender-card-active )" )[ 1 ].split( "}" )[ 0 ]
    assert "border-left: 3px solid var( --persona-color, transparent )" in stripe_block, \
        "left-accent stripe must be byte-faithful 3px solid var( --persona-color, transparent )"


@pytest.mark.parametrize( "forbidden", [
    ".action-required-widget",      # disjoint Category-3 surface → action-required.css
    "#sender-cards-container",       # mux pane structure → mux sheet
    "#notifications-pane",           # mux pane structure → mux sheet
    ".sender-display-name",          # rename seam → mux sheet (WS2/WS4)
    ".date-text",                    # rename seam → mux sheet (WS2/WS4)
    # NOTE: .sender-persona-badge + data-collapsed are NO LONGER forbidden — WS2
    # C2-a/C2-b legitimately UNION them into the shared sheet (see the C2 tests).
] )
def test_shared_sheet_excludes_mux_only_rules( forbidden ):
    rules = _strip_css_comments( _read( SHARED_CSS ) )
    assert forbidden not in rules, \
        f"shared contract sheet must NOT carry mux-only/mechanism rule {forbidden!r}"
