"""
WS3 — Full-Page Chrome Parity-Oracle, Tier 2 (computed-style isomorphism, nav
ONLY) + Tier 3 (geometry parity: nav iso + panel width + toggle-inline).

Unlike the sender-card oracle, the page chrome is NOT uniformly single-sourced, so
Tier 2 here is SCOPED to the ONE Category-A surface — the top nav bar — where both
clients render <nav.lupin-nav> from the SAME lupin-nav.css (Tier 0 proves the
single-source; this proves the CSSOM actually matches). The re-implemented
Category-B chrome deliberately gets NO computed-style iso (that palette/border
look-fidelity is Rachel's manual STYLE verdict, not this harness).

Tier 3 asserts the geometric parity CLAIMS that ARE legitimate cross-client:
  - nav geometry isomorphism (full-viewport bar, same size);
  - Action-Required panel FULL-WIDTH on both clients (V3 — the panel spans the
    container minus symmetric padding, and the mux width equals the legacy width);
  - Broadcast ▼ toggle INLINE with its heading on both (V7 — the toggle sits in
    the card's top header band, not orphaned on its own line below).
Absolute page-offset (dy from the page top) is deliberately NOT compared — the
section ORDER legitimately differs between clients (the B1 reorder).

Venue: :7999 / full-page (read-only). Skips (a finding) if the golden is absent or
stale. Run:
    LUPIN_TEST_BASE_URL=http://localhost:7999 \
        pytest src/tests/parity_oracle_fullpage/test_tier2_tier3.py -v
"""

from __future__ import annotations

import json

import pytest

from tests.e2e_ui.parity_oracle import (
    CHROME_STYLE_PROPS,
    MUX_FULLPAGE_PATH,
    fullpage_golden_is_stale,
    fullpage_golden_path,
)

from ._fullpage_helpers import base_url, open_and_walk

MUX_URL     = f"{base_url()}{MUX_FULLPAGE_PATH}"
GEOM_TOL_PX = 1.5   # ±1.5px: full-viewport + full-width panels flex a touch more than an isolated card

# A toggle within this many px of its card's top is "inline with the heading"
# (the header band); beyond it, the toggle has dropped to its own line (the V7 bug).
INLINE_BAND_PX = 44.0


def _golden() -> dict:
    path = fullpage_golden_path()
    if not path.exists():
        pytest.skip(
            f"page-chrome golden absent: {path} — capture it first (a SKIP is a finding, not a pass)."
        )
    golden = json.loads( path.read_text() )
    if fullpage_golden_is_stale( golden ):
        pytest.skip(
            "page-chrome golden is STALE (legacy chrome-CSS hash drift) — recapture with "
            "LUPIN_PARITY_FULLPAGE_CAPTURE=1 before trusting Tier 2/3 (a SKIP is a finding)."
        )
    return golden


def _mux_walk( page ) -> dict:
    return open_and_walk( page, MUX_URL, client="mux", wait_selector="#action-required-section" )


def test_tier2_nav_computed_style_isomorphism( page ):
    """
    Tier 2 (Cat A) — the mux nav's declarative layout style EQUALS the legacy
    golden nav's, property-for-property. Both render <nav.lupin-nav> from the same
    lupin-nav.css, so any divergence is a real single-source break — reported as
    the exact property + legacy-value + mux-value line.
    """
    golden   = _golden()
    mux      = _mux_walk( page )
    leg_nav  = golden[ "rows" ][ "V1-nav" ]
    mux_nav  = mux[ "V1-nav" ]
    assert mux_nav.get( "present" ), "mux must render the top nav (V1)"

    diffs = [
        f"  {prop}: legacy {leg_nav['styles'].get( prop )!r} · mux {mux_nav['styles'].get( prop )!r}"
        for prop in CHROME_STYLE_PROPS
        if leg_nav[ "styles" ].get( prop ) != mux_nav[ "styles" ].get( prop )
    ]
    assert not diffs, "Tier 2 nav computed-style divergence (single-source break):\n" + "\n".join( diffs )


def test_tier3_nav_geometry_isomorphism( page ):
    """Tier 3 (Cat A) — the mux nav box matches the legacy golden nav box (x / w /
    h) within ±tol. The nav is a full-viewport bar on both, so this is a clean
    absolute-geometry claim (the ONE chrome node exempt from the no-absolute rule,
    because it is not inside the reordered container)."""
    golden  = _golden()
    mux     = _mux_walk( page )
    lg      = golden[ "rows" ][ "V1-nav" ][ "geom" ]
    mg      = mux[ "V1-nav" ][ "geom" ]

    diffs = [
        f"  nav {axis}: legacy {lg[axis]} · mux {mg[axis]} (Δ{round( abs( lg[axis] - mg[axis] ), 1 )}px)"
        for axis in ( "x", "w", "h" )
        if abs( lg[ axis ] - mg[ axis ] ) > GEOM_TOL_PX
    ]
    assert not diffs, "Tier 3 nav geometry divergence:\n" + "\n".join( diffs )


def test_tier3_action_required_full_width( page ):
    """Tier 3 (V3) — the Action-Required panel is FULL-WIDTH on both clients (it
    spans the container minus symmetric side padding) AND the mux width equals the
    legacy width. This is a genuine cross-client structural claim (both panels are
    full-bleed), unlike the broadcast card whose width legitimately differs."""
    golden = _golden()
    mux    = _mux_walk( page )
    lg     = golden[ "rows" ][ "V3-AR" ][ "geom" ]
    mg     = mux[ "V3-AR" ][ "geom" ]

    # Full-width ⇔ node width ≈ container width minus its symmetric left inset.
    for label, g in ( ( "legacy", lg ), ( "mux", mg ) ):
        expected = g[ "cw" ] - 2 * g[ "dx" ]
        assert abs( g[ "w" ] - expected ) <= GEOM_TOL_PX, (
            f"{label} Action-Required panel is not full-width: w={g['w']} vs expected "
            f"{round( expected, 1 )} (cw={g['cw']} dx={g['dx']})"
        )
    assert abs( lg[ "w" ] - mg[ "w" ] ) <= GEOM_TOL_PX, (
        f"Action-Required panel width differs: legacy {lg['w']} · mux {mg['w']} "
        f"(Δ{round( abs( lg['w'] - mg['w'] ), 1 )}px)"
    )


def test_tier3_notifications_header_full_width( page ):
    """Tier 3 (V5) — the notifications HEADER REGION is full-width on both clients.
    Legacy nests the TTS-fraction slider inside its section-header (~956px); the mux
    splits the slider to a sibling mount, so #notifications-header-mount ALONE reads
    ~733px — a FALSE width gap. Measured at the region boundary
    (.notifications-header-region, which spans both mounts) the mux is full-width,
    matching legacy — Rachel's boundary correction, encoded so V5 stops false-flagging.
    The legitimate STRUCTURAL claim is that EACH region is full-width (spans its
    container minus its own symmetric inset) — which proves the mux measures the full
    ~960px region, NOT the cramped ~733px sub-mount. The exact cross-client width
    (legacy 956 vs mux 960 — a 2px-per-side container-inset difference) is Cat-B
    look-fidelity the iso deliberately SKIPS, so it is NOT asserted here (Rachel's
    verdict). Absolute page-dy is excluded as elsewhere."""
    golden = _golden()
    mux    = _mux_walk( page )
    lg     = golden[ "rows" ][ "V5-header" ][ "geom" ]
    mg     = mux[ "V5-header" ][ "geom" ]

    for label, g in ( ( "legacy", lg ), ( "mux", mg ) ):
        expected = g[ "cw" ] - 2 * g[ "dx" ]
        assert abs( g[ "w" ] - expected ) <= GEOM_TOL_PX, (
            f"{label} notifications header region is not full-width: w={g['w']} vs expected "
            f"{round( expected, 1 )} (cw={g['cw']} dx={g['dx']}) — if this is the mux, the V5 node "
            "boundary regressed off .notifications-header-region back onto the cramped sub-mount."
        )


def test_tier3_broadcast_toggle_inline( page ):
    """Tier 3 (V7) — the broadcast ▼ toggle sits INLINE in the card's top header
    band (not orphaned on its own line below the title) on BOTH clients. Measured
    as the toggle's vertical offset from its card's top edge."""
    golden = _golden()
    mux    = _mux_walk( page )

    for label, rows in ( ( "legacy", golden[ "rows" ] ), ( "mux", mux ) ):
        card_y   = rows[ "V7-broadcast" ][ "geom" ][ "y" ]
        toggle_y = rows[ "V7-toggle" ][ "geom" ][ "y" ]
        offset   = toggle_y - card_y
        assert 0 <= offset <= INLINE_BAND_PX, (
            f"{label} broadcast toggle is not inline with the heading: it sits {round( offset, 1 )}px "
            f"below the card top (band = {INLINE_BAND_PX}px) — the ▼ has dropped to its own line (V7)."
        )
