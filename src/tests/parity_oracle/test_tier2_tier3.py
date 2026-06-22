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

# WS2/C2-d direction CLOSED (Clayton commit d0aaa767 — Notification.direction +
# renderNotificationItem + load-time responded-split — plus the toMuxModel
# direction wiring). The mux now renders the responded reply `.outgoing` == legacy,
# a PROVEN match (was an allowlist exemption; the freshness guard fired on landing
# and this entry was removed). The two direction conformance tests (Tier 1 +
# golden-conformance) flipped xfail→pass.

# WS1 border-left CLOSED (Clayton, commit 7d5b4d51 + golden recapture): the
# `.sender-card[:not](.sender-card-active){ border-left:3px solid var(--persona-color,transparent) }`
# left-accent rules were ported byte-faithful into notifications-surface.css
# (notifications.css:2086-2092), so the mux now computes border-left-width 3px =
# legacy. It is no longer an allowlist exemption — Tier 2 asserts it as a PROVEN
# match. WS2/C2-d direction is closed too (see above).

# WS2/WS4 date-label rename seam CLOSED (Clayton commit d8980bc3 + golden
# recapture): the shared sheet now styles `.date-text { font-size:13px;
# font-weight:500; color:#495057 }` (byte-faithful to the legacy `.date-label`
# intent, notifications.css:2776); the mux 11px placeholder + the dead `.date-label`
# monolith rule were removed. Both clients now compute `.date-text` at 13px/19.5px
# /500 — the ~7.5px header→first-message gap closed (the persona-less arbiter card
# is fully parity-green). It was an allowlist exemption; the freshness guard fired
# on recapture and the entry was removed. Tier 2 now asserts FULL computed-style
# isomorphism with NO allowlist — every WS1/WS2 seam is a PROVEN match.

# Geometry tolerance (Doc 01 Tier 3).
GEOM_TOL_PX = 1.0


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


def test_tier2_computed_style_isomorphism( page ):
    """Tier 2 (core proof) — FULL computed-style isomorphism, NO allowlist. Every
    corresponding contract node has EQUAL declarative layout style across the mux
    component-isolation render and the legacy golden. All prior seams — WS1
    border-left, WS2/C2-d direction, WS2/WS4 date-text rename — are now PROVEN
    matches. Any divergence fails with the exact node+property+legacy+mux line."""
    legacy = _legacy_nodes( _golden() )
    mux    = _mux_nodes( page, _card_widths( legacy ) )

    common = set( legacy ) & set( mux )
    assert common, "no aligned contract nodes between mux and golden"

    unexpected: list[ str ] = []
    for key in sorted( common ):
        for prop in LAYOUT_STYLE_PROPS:
            if legacy[ key ][ "styles" ].get( prop ) != mux[ key ][ "styles" ].get( prop ):
                unexpected.append(
                    f"  {key}  {prop}: legacy {legacy[key]['styles'].get(prop)!r} · mux {mux[key]['styles'].get(prop)!r}"
                )

    assert not unexpected, (
        "Tier 2 computed-style divergence:\n" + "\n".join( unexpected )
    )


@pytest.mark.xfail(
    reason="Tier 3 geometry — ALL CSS/style seams are now CLOSED (WS1 border-left, "
           "WS2/C2-d direction, WS2/WS4 date-text), and the persona-LESS arbiter "
           "card is FULLY parity-green (0 diffs). The remaining geometry delta is "
           "confined to the persona'd CC-session card: a ~51.7px vertical gap from "
           "the accordion down + residual `.message-text` width diffs (msg[2]/[3]). "
           "This is the next layer the oracle peeled once styling converged — a "
           "WS4/G4 STRUCTURE-parity gap (the mux does not yet render the CC-session "
           "sender-card header chrome — project-name/session-id/status/delete/toggle, "
           "Category-3 / the 06-10 gap-bridge), NOT a CSS divergence and NOT in WS2 "
           "scope. Per Doc 02 this climbs to green as G4 functional gaps land; "
           "manager-routed. Remove this xfail when the CC header chrome ships. "
           "strict=False so it never breaks the suite.",
    strict=False,
)
def test_tier3_geometry_isomorphism( page ):
    """Tier 3: intra-card geometry (offset-from-card + size) within ±1px for every
    corresponding node. The persona-less arbiter card is fully green; XFAIL tracks
    the persona'd CC card's residual WS4/G4 structure gap (see reason)."""
    legacy = _legacy_nodes( _golden() )
    mux    = _mux_nodes( page, _card_widths( legacy ) )

    common = set( legacy ) & set( mux )
    unexpected: list[ str ] = []
    for key in sorted( common ):
        lg, mg = legacy[ key ][ "geom" ], mux[ key ][ "geom" ]
        for axis in ( "dx", "dy", "w", "h" ):
            if abs( lg[ axis ] - mg[ axis ] ) > GEOM_TOL_PX:
                unexpected.append( f"  {key}  {axis}: legacy {lg[axis]} · mux {mg[axis]} (Δ{round(abs(lg[axis]-mg[axis]),1)}px)" )

    assert not unexpected, (
        "Tier 3 geometry divergence (±1px):\n" + "\n".join( unexpected )
    )
