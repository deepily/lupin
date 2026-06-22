"""
WS3 — Layout-Parity Oracle: cross-client skeleton conformance (mux ↔ legacy golden).

Doc 01 Pillar 2: the multiplexer component-isolation render vs the captured
legacy golden. This is the *structural* half of the cross-client proof — same
sender cards, same per-card message counts, same badge presence — walked from
the SAME contract walker (CONTRACT_SKELETON_JS) on both sides. The *style* half
(Tier 2 computed-style isomorphism) and the *geometry* half (Tier 3) layer onto
the same proven golden-capture next (the golden already carries shared_sheet_hash
as the Rider-C staleness trip-wire; the capture is proven in test_golden_capture).

The ONE known structural divergence — the responded row's direction — is the
WS2/C2-d gap: legacy renders the response bubble `.outgoing`, the mux still
hardcodes `.incoming`. The oracle REPORTS it precisely (xfail below), which is
exactly the "even a failing oracle is a precise, actionable artifact" property.

Venue: :7999 / component-isolation (read-only). Skips if the golden has not been
captured (run test_golden_capture with LUPIN_PARITY_CAPTURE=1 first). Run:
    bash src/scripts/build-parity-harness.sh
    LUPIN_TEST_BASE_URL=http://localhost:7999 \
        pytest src/tests/parity_oracle/test_golden_conformance.py -v
"""

from __future__ import annotations

import json
import os

import pytest

from tests.e2e_ui.parity_oracle import (
    CONTRACT_SKELETON_JS,
    HARNESS_URL_PATH,
    content_hash,
    load_scenario,
    repo_root,
    shared_sheet_path,
)

BASE_URL    = os.environ.get( "LUPIN_TEST_BASE_URL", "http://localhost:7999" )
HARNESS_URL = f"{BASE_URL}{HARNESS_URL_PATH}"
GOLDEN_PATH = repo_root() / "src" / "tests" / "e2e_ui" / "fixtures" / "golden" / "notifications-legacy.golden.json"


def _load_golden() -> dict:
    if not GOLDEN_PATH.exists():
        pytest.skip(
            f"golden not captured: {GOLDEN_PATH} absent — run test_golden_capture.py "
            "with LUPIN_PARITY_CAPTURE=1 first (recalibration step)."
        )
    return json.loads( GOLDEN_PATH.read_text() )


def _mux_skeleton( page ) -> dict:
    page.goto( HARNESS_URL, wait_until="networkidle", timeout=20_000 )
    page.wait_for_function(
        "() => window.__parityHarnessReady === true && typeof window.__parityMount === 'function'",
        timeout=10_000,
    )
    page.evaluate( "( s ) => window.__parityMount( s )", load_scenario() )
    page.wait_for_selector( "#sender-cards-container .sender-card", timeout=5_000 )
    return page.evaluate( CONTRACT_SKELETON_JS, "#sender-cards-container" )


def _by_sender( skeleton: dict ) -> dict:
    return { c[ "sender_id" ]: c for c in skeleton[ "cards" ] }


def test_golden_shared_sheet_hash_is_current( ):
    """Rider C: the golden's baked shared-sheet hash must match the live WS1 sheet.
    A mismatch means legacy-contract CSS drifted and the golden is stale → recapture."""
    golden = _load_golden()
    assert golden[ "shared_sheet_hash" ] == content_hash( shared_sheet_path() ), (
        "golden is STALE — css/shared/notifications-surface.css changed since capture. "
        "Recapture: LUPIN_PARITY_CAPTURE=1 pytest src/tests/parity_oracle/test_golden_capture.py"
    )


def test_mux_matches_golden_card_and_message_structure( page ):
    """
    Cross-client structural conformance: the mux render and the legacy golden
    agree on sender cards, badge presence, accordion count, and per-card message
    counts (the D3 responded-split produces the SAME 5/1 row counts on both).
    """
    golden     = _load_golden()
    mux        = _by_sender( _mux_skeleton( page ) )
    legacy     = _by_sender( golden[ "skeleton" ] )

    assert set( mux ) == set( legacy ), "mux and legacy must render the same sender cards"

    for sender_id, lcard in legacy.items():
        mcard = mux[ sender_id ]
        assert mcard[ "persona_badge" ] == lcard[ "persona_badge" ], f"{sender_id}: badge presence differs"
        assert len( mcard[ "accordions" ] ) == len( lcard[ "accordions" ] ), f"{sender_id}: accordion count differs"
        for i, lacc in enumerate( lcard[ "accordions" ] ):
            macc = mcard[ "accordions" ][ i ]
            assert len( macc[ "messages" ] ) == len( lacc[ "messages" ] ), (
                f"{sender_id} accordion[{i}]: message count differs — "
                f"mux {len( macc['messages'] )} vs legacy {len( lacc['messages'] )} "
                "(D3 responded-split must produce identical row counts)"
            )


def test_mux_matches_golden_message_widgets( page ):
    """
    Each message row's contract widgets (time, text, expired badge, abstract
    indicator) match position-for-position between mux and the legacy golden —
    both sort newest-first, so positional alignment is valid.
    """
    golden = _load_golden()
    mux    = _by_sender( _mux_skeleton( page ) )
    legacy = _by_sender( golden[ "skeleton" ] )

    for sender_id, lcard in legacy.items():
        for i, lacc in enumerate( lcard[ "accordions" ] ):
            macc = mux[ sender_id ][ "accordions" ][ i ]
            for j, lmsg in enumerate( lacc[ "messages" ] ):
                mmsg = macc[ "messages" ][ j ]
                for widget in ( "has_time", "has_text", "expired_badge", "abstract_indicator" ):
                    assert mmsg[ widget ] == lmsg[ widget ], (
                        f"{sender_id} msg[{i}][{j}] widget '{widget}' differs: "
                        f"mux {mmsg[widget]} vs legacy {lmsg[widget]}"
                    )


@pytest.mark.xfail(
    reason="WS2/C2-d pending: legacy renders the responded reply .outgoing; the mux "
           "still hardcodes .incoming. The oracle reports this precise gap — it flips "
           "to xpass when WS2 wires the renderer direction param.",
    strict=False,
)
def test_mux_matches_golden_message_direction( page ):
    """
    Cross-client direction conformance — the strongest structural claim. Position
    0 (the newest row) is the responded reply: legacy `.outgoing`, mux currently
    `.incoming`. XFAIL until WS2. This single assertion is the oracle's actionable
    WS2 work-item.
    """
    golden = _load_golden()
    mux    = _by_sender( _mux_skeleton( page ) )
    legacy = _by_sender( golden[ "skeleton" ] )

    for sender_id, lcard in legacy.items():
        for i, lacc in enumerate( lcard[ "accordions" ] ):
            macc = mux[ sender_id ][ "accordions" ][ i ]
            for j, lmsg in enumerate( lacc[ "messages" ] ):
                assert macc[ "messages" ][ j ][ "direction" ] == lmsg[ "direction" ], (
                    f"{sender_id} msg[{i}][{j}] direction: mux "
                    f"{macc['messages'][j]['direction']} vs legacy {lmsg['direction']}"
                )
