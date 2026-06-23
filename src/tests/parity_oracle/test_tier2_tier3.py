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


# ---------------------------------------------------------------------------
# Tier 3 carve (Cheech, 2026-06-22 — reproduce-not-trust; Tiberius-ratified).
#
# SUPERSEDES the stale "2-row-header" narrowing in 140dc3d8. That diagnosis was
# OVERTURNED by running the oracle: the persona'd CC card's `>header` node matches
# legacy dx/dy/w/h EXACTLY — the header is NOT two-row. The residual ~51px is the
# `.cc-voice-input` ROW: legacy stacks a full mic/text/send row (~51px) BETWEEN
# the header and the date accordions, so everything below the header sits ~51px
# lower and the card is ~51px taller (legacy 335.2 vs mux 283.8). The mux
# DELIBERATELY redesigned that surface — a store-driven SenderCardRecorderRenderer
# + the ratified F5 caret-splice, mounted separately (and absent from this
# component-isolation harness). Forcing pixel-parity on the card's TOTAL height or
# on the voice-input region would force a revert of a sanctioned feature.
#
# So Tier 3 proves the NOTIFICATION-SURFACE geometry — the header + every date
# accordion + every message — and CARVES the voice-input region two ways, ONLY for
# CC-session cards (sid carries a '#'; persona-less external cards have no voice
# row and keep FULL absolute-geometry parity):
#   (a) the dates-region nodes (acc[*]/msg[*]) are compared with `dy` re-anchored
#       to the card's dates-region origin (its acc[0] header), so the carved
#       voice-input height cancels — the SHAPE below the header must still match
#       within ±1px;
#   (b) the CC card NODE's height is excluded (it spans the carved region).
# A NEW divergence anywhere in the surface still fails loudly with node+axis —
# "that line IS the bug report" (Doc 01). Whether FULL parity should instead match
# legacy's inline voice-input UX is a separate Rick product call (Tiberius is
# tracking it); it does NOT gate this surface-geometry proof.
# ---------------------------------------------------------------------------


def _sid_of( key: str ) -> str:
    """The data-sender-id a contract-node key belongs to. Keys are `card:<sid>`
    or `card:<sid>>...`; sids never contain '>'."""
    body = key[ len( "card:" ): ]
    gt   = body.find( ">" )
    return body if gt < 0 else body[ :gt ]


def _dates_anchor( nodes: dict, sid: str ) -> float:
    """The dates-region origin for a card = the dy of its acc[0] header. Asserts
    presence (fail-loud) rather than branching — the parity scenario always
    renders at least one date accordion per card, so a missing anchor is itself a
    contract regression worth surfacing."""
    node = nodes.get( f"card:{sid}>acc[0]>header" )
    assert node is not None, f"Tier 3 re-scope anchor missing: card:{sid}>acc[0]>header"
    return node[ "geom" ][ "dy" ]


def test_tier3_geometry_isomorphism( page ):
    """Tier 3: notification-surface geometry (offset + size) within ±1px for every
    corresponding node — header + accordions + messages. The persona-less arbiter
    card is proven with FULL absolute geometry; the persona'd CC card's voice-input
    region is carved (see the module-level Tier 3 carve note): its dates-region
    nodes are dy-anchored to the dates-region origin and its card height is
    excluded, so a sanctioned voice-input redesign neither masks nor
    falsely-fails the surface comparison."""
    legacy = _legacy_nodes( _golden() )
    mux    = _mux_nodes( page, _card_widths( legacy ) )

    common = set( legacy ) & set( mux )
    assert common, "no aligned contract nodes between mux and golden"

    # Per-card dates-region anchors — only for CC-session cards (the carve set).
    cc_sids       = { _sid_of( k ) for k in common if "#" in _sid_of( k ) }
    legacy_anchor = { sid: _dates_anchor( legacy, sid ) for sid in cc_sids }
    mux_anchor    = { sid: _dates_anchor( mux,    sid ) for sid in cc_sids }

    unexpected: list[ str ] = []
    for key in sorted( common ):
        sid             = _sid_of( key )
        is_cc           = "#" in sid
        is_card         = ">" not in key
        is_dates_region = ">acc[" in key or ">msg[" in key
        lg, mg = legacy[ key ][ "geom" ], mux[ key ][ "geom" ]
        for axis in ( "dx", "dy", "w", "h" ):
            # Carve (b): the CC card node's total height spans the voice-input row.
            if is_cc and is_card and axis == "h":
                continue
            lv, mv   = lg[ axis ], mg[ axis ]
            anchored = is_cc and is_dates_region and axis == "dy"
            if anchored:
                # Carve (a): cancel the voice-input height by anchoring dates-region
                # dy to the card's dates-region origin (its acc[0] header).
                lv -= legacy_anchor[ sid ]
                mv -= mux_anchor[ sid ]
            if abs( lv - mv ) > GEOM_TOL_PX:
                suffix = " (anchored to dates-region origin)" if anchored else ""
                unexpected.append(
                    f"  {key}  {axis}: legacy {lg[axis]} · mux {mg[axis]} "
                    f"(Δ{round(abs(lv-mv),1)}px){suffix}"
                )

    assert not unexpected, (
        "Tier 3 surface-geometry divergence (±1px, voice-input region carved):\n"
        + "\n".join( unexpected )
    )
