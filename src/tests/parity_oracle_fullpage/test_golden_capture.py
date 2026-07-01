"""
WS3 — Full-Page Chrome Parity-Oracle: golden-capture (page-chrome analogue of
parity_oracle/test_golden_capture.py).

Drives the LEGACY notifications client ONCE at its full page (`/app/notifications
?classic=1`) in its IDLE state, walks the page-chrome contract rows (V1 nav,
V2 env-label/clock, V3 AR panel, V4 PLY panel, V5 notif-header, V7 broadcast +
toggle, V9 session-strip; V13 has no legacy equivalent), and serializes each
row's presence + computed display + declarative style subset + geometry to a
NEW git-tracked golden:

    src/tests/e2e_ui/fixtures/golden/notifications-legacy-fullpage.golden.json

This golden is SEPARATE from the sender-card golden (notifications-legacy.golden
.json) — it is never overwritten by this capture. The golden bakes the legacy
chrome-sheet content hashes (lupin-nav / notifications / broadcast-panel) as the
Rider-C staleness trip-wire: a chrome-CSS drift fails Tier 2/3 and forces a
recapture.

This is a CAPTURE / recalibration step, gated behind LUPIN_PARITY_FULLPAGE_CAPTURE
=1 so a normal suite run never rewrites the golden. Tiers 1–3 read it and run
every time.

Venue: :7999 (legacy reachable; read-only — loading a page + reading DOM mutates
no persistent state). Run:
    LUPIN_PARITY_FULLPAGE_CAPTURE=1 LUPIN_TEST_BASE_URL=http://localhost:7999 \
        pytest src/tests/parity_oracle_fullpage/test_golden_capture.py -v -s
"""

from __future__ import annotations

import json
import os

import pytest

from tests.e2e_ui.parity_oracle import (
    LEGACY_FULLPAGE_PATH,
    chrome_css_hashes,
    fullpage_golden_path,
)

from ._fullpage_helpers import CONTAINER_SEL, base_url, open_and_walk

LEGACY_URL = f"{base_url()}{LEGACY_FULLPAGE_PATH}"

_CAPTURE_ENABLED = os.environ.get( "LUPIN_PARITY_FULLPAGE_CAPTURE" ) == "1"

pytestmark = pytest.mark.skipif(
    not _CAPTURE_ENABLED,
    reason="page-chrome golden-capture is a gated recalibration step — set LUPIN_PARITY_FULLPAGE_CAPTURE=1 to run",
)


def test_capture_legacy_fullpage_golden( page ):
    """Drive legacy full-page at idle; walk the chrome rows; serialize the golden."""
    rows = open_and_walk( page, LEGACY_URL, client="legacy", wait_selector="#action-required-section" )

    golden = {
        "captured_from" : "legacy notifications.html full page (idle, ?classic=1)",
        "container_sel" : CONTAINER_SEL,
        "css_hashes"    : chrome_css_hashes(),
        "rows"          : rows,
    }
    path = fullpage_golden_path()
    path.parent.mkdir( parents=True, exist_ok=True )
    path.write_text( json.dumps( golden, indent=2 ) + "\n" )

    present = [ k for k, v in rows.items() if v.get( "present" ) ]
    print( f"\n✓ wrote full-page chrome golden ({len( present )}/{len( rows )} rows present) → {path}" )
    print( "  present rows:", ", ".join( present ) )

    # V13-toolbar has no legacy equivalent (mux-native) — expected absent in the
    # LEGACY golden; every other row is a real legacy chrome surface.
    assert rows[ "V1-nav" ][ "present" ] is True, "legacy must render the top nav"
    assert rows[ "V3-AR" ][ "present" ] is True, "legacy must render the Action-Required section"
    assert rows[ "V2-env-label" ][ "present" ] is True, "legacy must render the env label (V2 reference)"
