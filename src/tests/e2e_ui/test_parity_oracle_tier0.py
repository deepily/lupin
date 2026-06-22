"""
WS3 — Layout-Parity Oracle, Tier 0: CSS Source Identity (static, pure-Python).

Doc 01 Pillar 2, Tier 0: assert `notifications.html` and `multiplexer.html` BOTH
`<link>` the SAME shared `notifications-surface.css`. If it passes, the two
clients are styling from the same bytes and copy-drift (Doc 00 §3 Premise A) is
impossible — this single check is what makes the brief's hypothesis true.

DEPENDENCY (WS1 / Clayton's lane): the shared sheet does not exist until WS1
lands. Per the WS3 brief — "write Tier 0 against the expected path; it greens
once WS1 lands." So while the shared sheet is absent this test SKIPS with a loud
WS1 pointer; the moment Clayton's sheet + its `<link>`s land, the assertions run
for real with no edit here.

Venue: :7999 / unit-eligible — no server, no browser, no state mutation, <2 min.
"""

from __future__ import annotations

import pytest

from .parity_oracle import (
    SHARED_SHEET_HREF,
    content_hash,
    html_path,
    linked_shared_hrefs,
    shared_sheet_path,
)


def test_tier0_css_source_identity():
    """
    Ensures (once WS1 lands):
        - both pages <link> notifications-surface.css
        - both resolve to the SAME served href (single source of truth)
        - the on-disk shared sheet exists and yields a stable 12-char hash
          (the Rider-C golden trip-wire reference)

    Until WS1 lands: SKIP with a WS1 dependency pointer (no false green/red).
    """
    mux_links   = linked_shared_hrefs( html_path( "multiplexer.html" ).read_text() )
    notif_links = linked_shared_hrefs( html_path( "notifications.html" ).read_text() )

    sheet = shared_sheet_path()
    if not sheet.exists():
        pytest.skip(
            "WS1 dependency not yet landed: "
            f"{sheet} is absent (Clayton's lane). Tier 0 greens automatically "
            "once the shared contract sheet + its <link>s exist — no edit here."
        )

    # Shared sheet exists → BOTH pages must link it (a half-wired state is a
    # real regression, so fail loud rather than skip).
    assert mux_links, "multiplexer.html must <link> notifications-surface.css once WS1 lands"
    assert notif_links, "notifications.html must <link> notifications-surface.css once WS1 lands"

    # Single source of truth — both pages point at the canonical served path.
    assert SHARED_SHEET_HREF in mux_links, (
        f"multiplexer.html must link the canonical {SHARED_SHEET_HREF}; got {mux_links}"
    )
    assert SHARED_SHEET_HREF in notif_links, (
        f"notifications.html must link the canonical {SHARED_SHEET_HREF}; got {notif_links}"
    )

    # Content hash binds — both clients style from these exact bytes (Tier 0
    # proper + the golden's staleness trip-wire reference).
    h = content_hash( sheet )
    assert len( h ) == 12, f"shared-sheet content hash must be a 12-char digest; got {h!r}"
