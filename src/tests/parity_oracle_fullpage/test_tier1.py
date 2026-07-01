"""
WS3 — Full-Page Chrome Parity-Oracle, Tier 1: chrome DOM Contract Conformance.

Feeds the MUX full page (`/app/multiplexer`) to headless Chromium at idle, walks
the page-chrome contract rows, and asserts the mux emits the chrome contract:

  - PRESENT-REQUIRED rows the mux must render (V1 nav + logout, V3 AR + empty
    state, V5 notif-header, V7 broadcast + toggle, V13 mux-native toolbar).
  - KNOWN-OPEN rows the mux does NOT yet render (V2 env-label + clock — H2/V2).
    Asserted STILL-ABSENT so the gap is a pinned finding, not a silent pass; the
    assertion flips (fails loudly) the instant the gap closes → the same
    break-on-close freshness discipline the sender-card allowlist uses.
  - DISPLAY-STATE divergences (Cat C) vs the legacy golden: V4 PLY (legacy hides
    it until playback; the mux shows an idle empty panel) and V9 session-strip
    (the mux hides it at idle; legacy shows it). Pinned as deterministic findings;
    the colored-accordion / sub-icon GEOMETRY parity is deferred to a future
    seeded-fixture tier (documented, NOT a silent skip).

Venue: :7999 / full-page (read-only, no state mutation, < 2 min). Run:
    LUPIN_TEST_BASE_URL=http://localhost:7999 \
        pytest src/tests/parity_oracle_fullpage/test_tier1.py -v
"""

from __future__ import annotations

import json

import pytest

from tests.e2e_ui.parity_oracle import (
    KNOWN_OPEN_CHROME_ROWS,
    MUX_FULLPAGE_PATH,
    fullpage_golden_path,
)

from ._fullpage_helpers import base_url, open_and_walk

MUX_URL = f"{base_url()}{MUX_FULLPAGE_PATH}"

# Rows the mux MUST render at idle (every chrome surface that is not a known-open
# gap, not a display-asymmetric Cat-C row, and not the legacy-absent toolbar case).
PRESENT_REQUIRED = [
    "V1-nav", "V1-logout",
    "V2-env-label", "V2-clock",   # promoted from KNOWN-OPEN at the H2 batch-merge (a81b2114) — H2's full-page proof
    "V3-AR", "V3-AR-empty",
    "V5-header", "V7-broadcast", "V7-toggle", "V13-toolbar",
]


def _mux_walk( page ) -> dict:
    return open_and_walk( page, MUX_URL, client="mux", wait_selector="#action-required-section" )


def _load_golden() -> dict:
    path = fullpage_golden_path()
    if not path.exists():
        pytest.skip(
            f"page-chrome golden not captured: {path} absent — run test_golden_capture.py "
            "with LUPIN_PARITY_FULLPAGE_CAPTURE=1 first (a SKIP here is a finding, not a pass)."
        )
    return json.loads( path.read_text() )


def test_tier1_present_required_rows( page ):
    """The mux renders every required chrome contract row at idle."""
    rows = _mux_walk( page )
    missing = [ key for key in PRESENT_REQUIRED if not rows.get( key, {} ).get( "present" ) ]
    assert not missing, (
        "mux full page is missing required chrome contract rows: " + ", ".join( missing )
    )


def test_tier1_known_open_rows_still_absent( page ):
    """
    Break-on-close sentinel: every KNOWN-OPEN chrome gap is STILL absent in the mux.
    V2 env-label + clock were promoted OUT of this set at the H2 batch-merge (a81b2114
    — they now render, and are asserted present in test_tier1_present_required_rows).
    The set is currently EMPTY (no pinned-open gaps remain); it stays as the live
    freshness-guard hook — add a future gap here and this fails loudly the instant the
    mux starts rendering it, forcing the pin to be resolved rather than silently drift.
    """
    rows = _mux_walk( page )
    unexpectedly_present = [ key for key in KNOWN_OPEN_CHROME_ROWS if rows.get( key, {} ).get( "present" ) ]
    assert not unexpectedly_present, (
        "KNOWN-OPEN chrome rows now RENDER in the mux — a pinned gap closed! Remove them from "
        "KNOWN_OPEN_CHROME_ROWS and promote to present-required: " + ", ".join( unexpectedly_present )
    )


def test_tier1_display_state_divergences( page ):
    """
    Cat-C idle display-state divergences vs the legacy golden, pinned deterministically:
      - V4 PLY: legacy `#tts-queue-section` is display:none at idle; the mux
        `#tts-pane` renders a visible idle empty panel (display != none).
      - V9 strip: the mux `#cc-session-strip` is display:none at idle; legacy
        renders it (display != none).
    Their colored-accordion / sub-icon geometry parity needs a seeded fixture → a
    future tier. If either client's idle display-state changes, this flips loudly.
    """
    golden = _load_golden()
    rows   = _mux_walk( page )

    ply_legacy = golden[ "rows" ][ "V4-PLY" ][ "display" ]
    ply_mux    = rows[ "V4-PLY" ][ "display" ]
    assert ply_legacy == "none", f"golden expected legacy PLY hidden at idle; got {ply_legacy!r} (recapture?)"
    assert ply_mux != "none", (
        f"V4 divergence changed: mux PLY idle display is now {ply_mux!r} — if the mux now hides the "
        "idle PLY panel to match legacy, update this finding."
    )

    strip_legacy = golden[ "rows" ][ "V9-strip" ][ "display" ]
    strip_mux    = rows[ "V9-strip" ][ "display" ]
    assert strip_legacy != "none", f"golden expected legacy strip visible at idle; got {strip_legacy!r} (recapture?)"
    assert strip_mux == "none", (
        f"V9 divergence changed: mux strip idle display is now {strip_mux!r} — if the mux now shows the "
        "idle strip to match legacy, update this finding (and add a seeded-fixture sub-icon geometry tier)."
    )
