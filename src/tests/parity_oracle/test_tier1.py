"""
WS3 — Layout-Parity Oracle, Tier 1: DOM Contract Conformance (component-isolation).

Doc 01 Pillar 2, Tier 1: feed the canonical fixture to the MUX renderer in the
component-isolation harness, walk the produced subtree, and assert it conforms
to the Layout Contract — the contract classes/attributes are present and the D3
responded-split produced its synthetic outgoing row. This localizes a regression
to the mux client (dropped `.incoming`, renamed a contract class, lost
`.date-accordion-messages`, etc.) without cross-diff noise.

Venue: :7999 / component-isolation (read-only, no state mutation, <2 min) — the
harness page + bundle are static assets served by the dev server. Run the build
preamble first so the bundle is fresh:
    bash src/scripts/build-parity-harness.sh
    LUPIN_TEST_BASE_URL=http://localhost:7999 \
        pytest src/tests/parity_oracle/test_tier1.py -v
"""

from __future__ import annotations

import os

import pytest

from tests.e2e_ui.parity_oracle import CONTRACT_SKELETON_JS, HARNESS_URL_PATH, load_scenario

# Component-isolation is :7999-eligible — default there, override via env.
BASE_URL    = os.environ.get( "LUPIN_TEST_BASE_URL", "http://localhost:7999" )
HARNESS_URL = f"{BASE_URL}{HARNESS_URL_PATH}"

TIBERIUS = "claude.code@lupin.deepily.ai#parity01"
ARBITER  = "lupin-arbiter-app-8001"


def _mount_and_skeleton( page ) -> dict:
    """Load the harness, inject the canonical scenario, return the contract skeleton."""
    page.goto( HARNESS_URL, wait_until="networkidle", timeout=20_000 )
    page.wait_for_function(
        "() => window.__parityHarnessReady === true && typeof window.__parityMount === 'function'",
        timeout=10_000,
    )
    count = page.evaluate( "( s ) => window.__parityMount( s )", load_scenario() )
    assert count == 2, f"harness must mount 2 sender cards; got {count}"
    page.wait_for_selector( "#sender-cards-container .sender-card", timeout=5_000 )
    skeleton = page.evaluate( CONTRACT_SKELETON_JS, "#sender-cards-container" )
    assert skeleton is not None, "contract skeleton walker found no root"
    return skeleton


def _card( skeleton: dict, sender_id: str ) -> dict:
    card = next( ( c for c in skeleton[ "cards" ] if c[ "sender_id" ] == sender_id ), None )
    assert card is not None, f"no sender card for {sender_id}"
    return card


def test_tier1_mux_emits_contract_skeleton( page ):
    """
    Ensures the mux renderer emits the Layout-Contract skeleton on the canonical
    fixture: 2 cards, header + dates container per card, a date accordion with
    its header/text/count/toggle, and messages each with time + text. Persona'd
    sender carries the badge; the persona-less external sender does not.
    """
    skeleton = _mount_and_skeleton( page )
    assert len( skeleton[ "cards" ] ) == 2

    tib = _card( skeleton, TIBERIUS )
    assert tib[ "has_header" ] and tib[ "has_dates" ]
    assert tib[ "persona_badge" ] is True, "persona'd sender must render .sender-persona-badge"
    assert len( tib[ "accordions" ] ) == 1, "all Tiberius messages share one date → one accordion"
    acc = tib[ "accordions" ][ 0 ]
    assert acc[ "has_header" ] and acc[ "has_text" ] and acc[ "has_count" ] and acc[ "has_toggle" ]
    for m in acc[ "messages" ]:
        assert m[ "has_time" ] and m[ "has_text" ], f"message {m['id_hash']} missing time/text"

    ext = _card( skeleton, ARBITER )
    assert ext[ "persona_badge" ] is False, "persona-less external sender must NOT render a badge"
    assert len( ext[ "accordions" ][ 0 ][ "messages" ] ) == 1


def test_tier1_responded_split_and_badges_present( page ):
    """
    Ensures the D3 responded-split materialized in the DOM and the abstract /
    expired contract widgets render:
        - Tiberius card holds 5 message rows (4 originals + 1 synthetic response)
        - the synthetic `parity-responded-1-response` row exists
        - the abstract row carries .abstract-indicator; the expired row .expired-badge
    """
    skeleton = _mount_and_skeleton( page )
    msgs = _card( skeleton, TIBERIUS )[ "accordions" ][ 0 ][ "messages" ]
    ids  = [ m[ "id_hash" ] for m in msgs ]

    assert len( msgs ) == 5, f"4 originals + 1 responded-split = 5 rows; got {ids}"
    assert "parity-responded-1" in ids, "the responded prompt must render"
    assert "parity-responded-1-response" in ids, "the synthetic outgoing response row must render (D3 split)"

    by_id = { m[ "id_hash" ]: m for m in msgs }
    assert by_id[ "parity-abstract-1" ][ "abstract_indicator" ] is True
    assert by_id[ "parity-expired-1" ][ "expired_badge" ] is True


def test_tier1_outgoing_direction_conformance( page ):
    """
    Layout-Contract direction referee: the synthetic response row renders as
    `.sender-message.outgoing` and the prompt as `.incoming`. PASSES since WS2/C2-d
    landed (Clayton d0aaa767: renderNotificationItem reads notification.direction;
    toMuxModel wires it) — was xfail until then.
    """
    skeleton = _mount_and_skeleton( page )
    msgs  = _card( skeleton, TIBERIUS )[ "accordions" ][ 0 ][ "messages" ]
    by_id = { m[ "id_hash" ]: m for m in msgs }

    assert by_id[ "parity-responded-1" ][ "direction" ] == "incoming"
    assert by_id[ "parity-responded-1-response" ][ "direction" ] == "outgoing"
