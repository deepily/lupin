"""
WS3 — Full-Page Chrome Parity-Oracle, Tier 0: chrome CSS Source Identity (static).

The sender-card Tier 0 (parity_oracle/test_tier0.py) proves the SENDER-CARD
contract sheet (notifications-surface.css) is single-sourced across both clients.
This file is its page-CHROME analogue: it proves the top nav bar (V1) is
single-sourced — both notifications.html (legacy) and multiplexer.html (mux)
<link> the SAME lupin-nav.css + lupin-base.css. That single-sourcing is what
makes the nav the ONE Category-A chrome surface where Tier 2 computed-style
ISOMORPHISM is a valid parity claim (the re-implemented Category-B chrome
deliberately gets no style-iso).

If it passes, the nav is styled from the same bytes on both pages and copy-drift
is impossible there. A pure-Python test — no browser, no server, no state
mutation, < 2 min → :7999 / unit-eligible per CLAUDE.md §TESTING VENUES.

Run:
    pytest src/tests/parity_oracle_fullpage/test_tier0.py -v
"""

from __future__ import annotations

import pytest

from tests.e2e_ui.parity_oracle import (
    SHARED_CHROME_SHEETS,
    chrome_css_hashes,
    html_path,
    links_stylesheet,
)


@pytest.mark.parametrize( "sheet", SHARED_CHROME_SHEETS )
def test_tier0_chrome_css_source_identity( sheet ):
    """
    Both the legacy and the mux page shell must <link> each shared chrome sheet —
    proving the top nav (V1) styles from identical bytes on both clients. A
    half-wired state (one page links it, the other doesn't) is a real regression,
    so this fails loud rather than skips.
    """
    mux_html   = html_path( "multiplexer.html" ).read_text()
    notif_html = html_path( "notifications.html" ).read_text()

    assert links_stylesheet( mux_html, sheet ), (
        f"multiplexer.html must <link> the shared chrome sheet {sheet}"
    )
    assert links_stylesheet( notif_html, sheet ), (
        f"notifications.html must <link> the shared chrome sheet {sheet}"
    )


def test_tier0_chrome_css_hashes_are_stable():
    """
    Every legacy chrome sheet hashed into the page-chrome golden yields a stable
    12-char digest (the golden's staleness trip-wire reference). A missing sheet
    would raise before returning, so a clean return proves all three exist.
    """
    hashes = chrome_css_hashes()
    assert set( hashes ) == { "lupin-nav.css", "notifications.css", "broadcast-panel.css" }
    for name, digest in hashes.items():
        assert len( digest ) == 12, f"{name}: content hash must be a 12-char digest; got {digest!r}"
