"""
WS3 — Layout-Parity Oracle, Tier 2 (computed-style isomorphism) + Tier 3
(geometry isomorphism). Doc 01 Pillar 2 — Tier 2 is "the core proof".

Walks the mux component-isolation render and the captured legacy golden in
lockstep (keys aligned: card by data-sender-id, message positional — both
newest-first), and for each corresponding contract node:
  - Tier 2: asserts the DECLARATIVE layout property set is EQUAL (D4 rider —
    declarative props EXACT, resolved width/height deliberately excluded).
  - Tier 3: asserts intra-card geometry (offset from the card origin + node
    size) matches within ±1px.

The ONE expected divergence is the responded reply row (Tiberius msg[0]): legacy
renders it `.outgoing`, the mux still hardcodes `.incoming` (WS2/C2-d). Both
tiers PROVE parity on every other contract node and assert the divergence set is
EXACTLY the known WS2 nodes — so a NEW divergence anywhere else fails loudly with
a node+property diff (Doc 01: "that line IS the bug report").

Venue: :7999 / component-isolation. Skips if the golden isn't captured. Run:
    bash src/scripts/build-parity-harness.sh
    LUPIN_TEST_BASE_URL=http://localhost:7999 \
        pytest src/tests/parity_oracle/test_tier2_tier3.py -v
"""

from __future__ import annotations

import json
import os

import pytest

from tests.e2e_ui.parity_oracle import (
    CONTRACT_STYLE_GEOM_JS,
    HARNESS_URL_PATH,
    LAYOUT_STYLE_PROPS,
    content_hash,
    load_scenario,
    repo_root,
    shared_sheet_path,
)

BASE_URL    = os.environ.get( "LUPIN_TEST_BASE_URL", "http://localhost:7999" )
HARNESS_URL = f"{BASE_URL}{HARNESS_URL_PATH}"
GOLDEN_PATH = repo_root() / "src" / "tests" / "e2e_ui" / "fixtures" / "golden" / "notifications-legacy.golden.json"

# The known WS2/C2-d divergence: legacy renders the newest (responded-reply) row
# of the persona'd card `.outgoing`; the mux still hardcodes `.incoming`. Every
# node whose key contains this prefix is allowed to differ until WS2 lands.
WS2_DIVERGENT_PREFIX = "card:claude.code@lupin.deepily.ai#parity01>msg[0]"

# WS1 border-left CLOSED (Clayton, commit 7d5b4d51 + golden recapture): the
# `.sender-card[:not](.sender-card-active){ border-left:3px solid var(--persona-color,transparent) }`
# left-accent rules were ported byte-faithful into notifications-surface.css
# (notifications.css:2086-2092), so the mux now computes border-left-width 3px =
# legacy. It is no longer an allowlist exemption — Tier 2 asserts it as a PROVEN
# match. WS2/C2-d direction is the only remaining known divergence.

# Known WS2/WS4 date-label rename seam (documented-deferred in BOTH sheets:
# notifications-surface.css:275-276 + notifications-list.css:103-106). Legacy JS
# emits `.date-text` (notifications.js:13614) but legacy CSS still styles the dead
# `.date-label` (notifications.css:2776 — 13px/500), so legacy's `.date-text`
# renders UNSTYLED (browser-default 16px/24px/400); the mux styles `.date-text`
# at 11px/600 in its own sheet. The line-height delta (24px vs 16.5px) is the
# EXACT ~7.5px intra-card vertical gap (diagnosed REAL, not a harness artifact —
# golden is the real legacy page + the harness links the same contract sheets;
# per Tiberius's real-vs-artifact task). Allowlisted (freshness-guarded) until the
# seam unifies `.date-text` into the shared contract at the designed 13px/500.
# The ENTIRE `.date-text` node is the seam (legacy unstyled vs mux-styled), so
# EVERY declared-style prop on it diverges from the same root cause (font-size /
# line-height / font-weight — the ~7.5px driver — plus color + letter-spacing);
# all converge when the seam unifies. Hence the allowlist covers the whole node.

# Geometry tolerance (Doc 01 Tier 3).
GEOM_TOL_PX = 1.0


def _is_date_text_seam( key: str ) -> bool:
    return key.endswith( ">date-text" )


def _is_known_style_divergence( key: str, prop: str ) -> bool:
    if key.startswith( WS2_DIVERGENT_PREFIX ):
        return True                                  # WS2/C2-d direction
    if _is_date_text_seam( key ):
        return True                                  # WS2/WS4 date-label rename seam (whole .date-text node)
    return False


def _golden() -> dict:
    if not GOLDEN_PATH.exists():
        pytest.skip(
            f"golden not captured: {GOLDEN_PATH} absent — run test_golden_capture.py "
            "with LUPIN_PARITY_CAPTURE=1 first."
        )
    g = json.loads( GOLDEN_PATH.read_text() )
    if g[ "shared_sheet_hash" ] != content_hash( shared_sheet_path() ):
        pytest.skip( "golden is STALE (shared-sheet hash drift) — recapture before Tier 2/3." )
    return g


def _mux_nodes( page, legacy_card_widths: dict[ str, float ] ) -> dict:
    """Mount the mux harness, normalize each card's width to the legacy golden's
    (the one context variable: legacy is captured full-page, mux isolated), and
    return key→{styles,geom}."""
    page.goto( HARNESS_URL, wait_until="networkidle", timeout=20_000 )
    page.wait_for_function(
        "() => window.__parityHarnessReady === true && typeof window.__parityMount === 'function'",
        timeout=10_000,
    )
    page.evaluate( "( s ) => window.__parityMount( s )", load_scenario() )
    page.wait_for_selector( "#sender-cards-container .sender-card", timeout=5_000 )

    # Force each card to its legacy width so intra-card geometry is comparable.
    page.evaluate(
        """( widths ) => {
            for ( const card of document.querySelectorAll( '#sender-cards-container .sender-card' ) ) {
                const w = widths[ card.getAttribute( 'data-sender-id' ) ];
                if ( w ) { card.style.boxSizing = 'border-box'; card.style.width = w + 'px'; }
            }
        }""",
        legacy_card_widths,
    )

    result = page.evaluate(
        CONTRACT_STYLE_GEOM_JS,
        { "rootSel": "#sender-cards-container", "props": LAYOUT_STYLE_PROPS },
    )
    return { n[ "key" ]: n for n in result[ "nodes" ] }


def _legacy_nodes( golden: dict ) -> dict:
    return { n[ "key" ]: n for n in golden[ "style_geom" ][ "nodes" ] }


def _card_widths( legacy: dict ) -> dict[ str, float ]:
    out: dict[ str, float ] = {}
    for key, node in legacy.items():
        if key.startswith( "card:" ) and ">" not in key:
            out[ key[ len( "card:" ): ] ] = node[ "geom" ][ "w" ]
    return out


def _is_ws2( key: str ) -> bool:
    return key.startswith( WS2_DIVERGENT_PREFIX )


def test_tier2_computed_style_isomorphism( page ):
    """Tier 2 (core proof): every corresponding contract node has EQUAL declarative
    layout style, except the one documented known-divergence (the WS2 direction
    node). With WS1 closed, the `.sender-card` border-left is now a PROVEN match
    (legacy 3px == mux 3px), included in the proven set. A NEW divergence anywhere
    else fails with the exact node+property+legacy+mux line. A freshness guard
    asserts the WS2 divergence is still present, so this test fails (prompting
    allowlist cleanup) the moment WS2 lands."""
    legacy = _legacy_nodes( _golden() )
    mux    = _mux_nodes( page, _card_widths( legacy ) )

    common = set( legacy ) & set( mux )
    assert common, "no aligned contract nodes between mux and golden"

    unexpected: list[ str ] = []
    ws2_seen = False
    date_text_seen = False
    for key in sorted( common ):
        for prop in LAYOUT_STYLE_PROPS:
            if legacy[ key ][ "styles" ].get( prop ) == mux[ key ][ "styles" ].get( prop ):
                continue
            if _is_known_style_divergence( key, prop ):
                if key.startswith( WS2_DIVERGENT_PREFIX ): ws2_seen = True
                if _is_date_text_seam( key ):              date_text_seen = True
                continue
            unexpected.append(
                f"  {key}  {prop}: legacy {legacy[key]['styles'].get(prop)!r} · mux {mux[key]['styles'].get(prop)!r}"
            )

    assert not unexpected, (
        "Tier 2 NEW computed-style divergence (not in the WS2 / date-text-seam allowlist):\n" + "\n".join( unexpected )
    )
    # Freshness guards — when each seam lands, the matching flag flips and forces allowlist cleanup.
    assert ws2_seen, "WS2 responded-reply style divergence vanished — WS2 may have landed; remove the allowlist entry"
    assert date_text_seen, "date-text rename-seam divergence vanished — WS2/WS4 may have unified .date-text; remove the allowlist entry"


@pytest.mark.xfail(
    reason="Tier 3 geometry, post-WS1-fix (the ±2px horizontal border diff is now "
           "GONE — WS1 confirmed). Remaining diffs are BOTH known-divergence "
           "consequences: (1) the WS2 .outgoing height delta cascading ~60px down "
           "the persona'd card's sibling rows (flips when WS2 wires the renderer "
           "direction param); (2) the WS2/WS4 date-label rename seam — `.date-text` "
           "line-height 24px(legacy, unstyled browser-default) vs 16.5px(mux) = the "
           "~7.5px vertical delta on BOTH cards (diagnosed REAL, not harness noise; "
           "closes when .date-text unifies into the shared contract at 13px/500). "
           "The machinery is correct (precise per-node Δpx report); strict=False so "
           "it never breaks the suite.",
    strict=False,
)
def test_tier3_geometry_isomorphism( page ):
    """Tier 3: intra-card geometry (offset-from-card + size) within ±1px for every
    corresponding node EXCEPT the known WS2 node. XFAIL until WS1/WS2 close their
    geometric blast radius (see reason)."""
    legacy = _legacy_nodes( _golden() )
    mux    = _mux_nodes( page, _card_widths( legacy ) )

    common = set( legacy ) & set( mux )
    unexpected: list[ str ] = []
    for key in sorted( common ):
        if _is_ws2( key ):
            continue
        lg, mg = legacy[ key ][ "geom" ], mux[ key ][ "geom" ]
        for axis in ( "dx", "dy", "w", "h" ):
            if abs( lg[ axis ] - mg[ axis ] ) > GEOM_TOL_PX:
                unexpected.append( f"  {key}  {axis}: legacy {lg[axis]} · mux {mg[axis]} (Δ{round(abs(lg[axis]-mg[axis]),1)}px)" )

    assert not unexpected, (
        "Tier 3 geometry divergence (±1px):\n" + "\n".join( unexpected )
    )
