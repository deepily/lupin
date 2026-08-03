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
    class AND the mux `[data-collapsed]` attribute on the DATE-ACCORDION (one
    contract, both clients). The mux sheet no longer carries a private
    date-accordion collapse rule.

    SCOPE NOTE (premise corrected 2026-06-29): C2-b single-sources ONLY the
    date-accordion collapse — the mechanism that HAS a legacy `.collapsed`
    counterpart to union with. The `.sender-card[data-collapsed]` rule is a
    SEPARATE, legitimately mux-only collapse mechanism: legacy collapsed the
    sender-card dates via inline `style.display` (no CSS-class selector), so there
    is nothing to union into the shared sheet. It stays in the mux sheet by design
    (notifications-list.css), so this test forbids only the date-accordion residual,
    not every `[data-collapsed]` token."""
    shared = _strip_css_comments( _read( SHARED_CSS ) )
    assert ".date-accordion-messages.collapsed" in shared, "C2-b union missing the legacy .collapsed selector"
    assert 'data-collapsed="true"' in shared, "C2-b union missing the mux [data-collapsed] selector"
    mux = _strip_css_comments( _read( MUX_CSS ) )
    assert ".date-accordion-messages.collapsed" not in mux, \
        "mux must NOT keep a private legacy-class date-accordion collapse rule (single-sourced into the shared C2-b union)"
    assert ".date-accordion[ data-collapsed" not in mux, \
        "mux must NOT keep a private date-accordion [data-collapsed] collapse rule (single-sourced into the shared C2-b union)"


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


def test_date_text_rename_completed_in_shared():
    """WS2 (Rick-ruled 2026-06-22): the `.date-label`→`.date-text` rename is
    COMPLETE — the shared sheet styles the real emitted `.date-text` class at the
    designed 13px/500 (byte-faithful from notifications.css:2776); the mux 11px
    placeholder and the dead monolith `.date-label` rule are removed."""
    shared = _strip_css_comments( _read( SHARED_CSS ) )
    assert ".date-text {" in shared, "shared sheet must style .date-text (rename completion)"
    block = shared.split( ".date-text {" )[ 1 ].split( "}" )[ 0 ]
    assert "font-size: 13px" in block and "font-weight: 500" in block, \
        ".date-text must carry the designed 13px/500 (notifications.css:2776 .date-label intent)"
    mux = _strip_css_comments( _read( MUX_CSS ) )
    assert ".date-text {" not in mux, "mux 11px .date-text placeholder must be removed (now shared)"
    # the dead monolith rule must be gone (no class ever emitted it)
    monolith = _strip_css_comments( _read( os.path.join( STATIC, "css", "notifications.css" ) ) )
    assert ".date-label" not in monolith, "dead .date-label rule must be removed from the monolith"


@pytest.mark.parametrize( "forbidden", [
    ".action-required-widget",      # disjoint Category-3 surface → action-required.css
    "#sender-cards-container",       # mux pane structure → mux sheet
    "#notifications-pane",           # mux pane structure → mux sheet
    ".sender-display-name",          # rename seam → mux sheet (WS2/WS4)
    # NOTE: .sender-persona-badge + data-collapsed + .date-text are NO LONGER
    # forbidden — WS2 C2-a/C2-b/.date-text legitimately live in the shared sheet.
] )
def test_shared_sheet_excludes_mux_only_rules( forbidden ):
    rules = _strip_css_comments( _read( SHARED_CSS ) )
    assert forbidden not in rules, \
        f"shared contract sheet must NOT carry mux-only/mechanism rule {forbidden!r}"


# ---------------------------------------------------------------------------
# BE2 hygiene follow-on (task 80479273, Cheech 2026-07-01) — the mux
# `.tts-preview-slider-*` component CSS is CO-LOCATED into the shared sheet
# (single-source hygiene, sibling to the legacy `.cc-tts-fraction-*` block B5
# already folded in). The standalone multiplexer/tts-preview-slider.css file is
# retired and no page <link>s it — the rules ride the already-linked shared
# sheet. ZERO parity/render impact: the mux slider classes are disjoint from
# legacy (which emits none of them), so the rules are inert on /app/notifications
# and byte-identical on /app/multiplexer.
# ---------------------------------------------------------------------------

TTS_SLIDER_CSS  = os.path.join( STATIC, "css", "multiplexer", "tts-preview-slider.css" )
TTS_SLIDER_HREF = "tts-preview-slider.css"


@pytest.mark.parametrize( "selector", [
    ".tts-preview-slider",
    ".tts-preview-slider-label",
    ".tts-preview-slider-input",
    ".tts-preview-slider-value",
] )
def test_tts_preview_slider_rules_in_shared( selector ):
    rules = _strip_css_comments( _read( SHARED_CSS ) )
    assert selector + " {" in rules or selector + "{" in rules, \
        f"BE2 co-location: {selector!r} must live in the shared sheet"


def test_tts_preview_slider_file_retired():
    assert not os.path.isfile( TTS_SLIDER_CSS ), \
        "multiplexer/tts-preview-slider.css should be retired (folded into the shared sheet)"


def test_no_page_links_retired_tts_preview_slider():
    for page in ( NOTIF_HTML, MUX_HTML ):
        hrefs = re.findall( r'href="([^"]+)"', _read( page ) )
        assert not any( TTS_SLIDER_HREF in h for h in hrefs ), \
            f"{os.path.basename( page )} still <link>s the retired tts-preview-slider.css"


# ---------------------------------------------------------------------------
# WP7 (Krishna 🦚, 2026-07-02) — TTS queue CARD classes single-sourced into the
# shared sheet. The mux emits these exact class names (render/templates/
# ttsActiveCard.ts, ttsMinimizedCard.ts, ttsChrome.ts's renderTtsEmpty) but
# styled NONE of them; legacy declared them in its monolith. Now: ONE declaration
# in the shared sheet; both pages already link it (legacy before its monolith).
# The CHROME is a divergent per-surface taxonomy — mux `.tts-chrome`/`.tts-btn*`
# vs legacy `#tts-queue-section`/`.tts-control-button` — legitimately NOT shared.
# `.tts-minimized.shrink-fade` + `@keyframes shrinkFadeOut` stay legacy-only (the
# mux applies no `.shrink-fade`; the keyframe is shared with a legacy-only rule).
# ---------------------------------------------------------------------------

MUX_TTS_CHROME_CSS = os.path.join( STATIC, "css", "multiplexer", "tts-chrome.css" )
MONOLITH_CSS       = os.path.join( STATIC, "css", "notifications.css" )

TTS_CARD_SELECTORS = [
    ".tts-queue-empty-state",
    ".tts-active-card",
    ".tts-active-card .tts-type-icon",
    ".tts-active-card .tts-message",
    ".tts-active-card .tts-stop-button",
    ".tts-minimized",
    ".tts-minimized .tts-position",
    ".tts-minimized .tts-type-badge",
    ".tts-minimized .tts-text",
    ".tts-minimized.priority",
    ".tts-delete-button",
]


@pytest.mark.parametrize( "selector", TTS_CARD_SELECTORS )
def test_wp7_tts_card_rules_in_shared( selector ):
    """WP7: each TTS card selector is declared in the shared sheet (single source)."""
    rules = _strip_css_comments( _read( SHARED_CSS ) )
    assert selector + " {" in rules, f"WP7: {selector!r} must live in the shared sheet"


@pytest.mark.parametrize( "selector", TTS_CARD_SELECTORS )
def test_wp7_tts_card_rules_single_declaration( selector ):
    """WP7 single-source: each TTS card selector is declared EXACTLY ONCE
    repo-wide (in the shared sheet) — no fork in the mux chrome sheet or the
    legacy monolith. A future re-fork fails loudly here."""
    decl  = selector + " {"
    total = sum(
        _strip_css_comments( _read( path ) ).count( decl )
        for path in ( SHARED_CSS, MUX_TTS_CHROME_CSS, MONOLITH_CSS )
    )
    assert total == 1, f"WP7: {selector!r} must have EXACTLY ONE declaration repo-wide, found {total}"


def test_wp7_mux_chrome_sheet_does_not_fork_empty_state():
    """WP7 de-fork: the mux tts-chrome.css must NOT re-declare the empty-state
    text (was `.tts-chrome-empty .tts-queue-empty-state`) — the empty panel's
    element is now styled by the single shared `.tts-queue-empty-state`."""
    mux = _strip_css_comments( _read( MUX_TTS_CHROME_CSS ) )
    assert ".tts-queue-empty-state" not in mux, \
        "mux tts-chrome.css must not re-declare .tts-queue-empty-state (de-forked to shared)"


def test_wp7_legacy_monolith_dropped_card_rules():
    """WP7: the legacy monolith no longer declares the moved card classes (they
    ride the shared sheet linked before the monolith). Legacy-only survivors: the
    CHROME (`#tts-queue-section`) and the `.tts-minimized.shrink-fade` animation."""
    monolith = _strip_css_comments( _read( MONOLITH_CSS ) )
    for selector in TTS_CARD_SELECTORS:
        assert selector + " {" not in monolith, \
            f"WP7: legacy monolith must drop {selector!r} (moved to shared)"
    assert "#tts-queue-section {" in monolith, "legacy-only chrome #tts-queue-section must stay"
    assert ".tts-minimized.shrink-fade {" in monolith, "legacy-only .shrink-fade animation must stay"
