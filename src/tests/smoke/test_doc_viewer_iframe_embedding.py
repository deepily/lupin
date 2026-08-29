"""
Smoke test — same-origin iframe embedding (X-Frame-Options).

HISTORY, because the shape of this file changed with the rule it guards.

Originally (fixed 2026-05-30) the global `add_security_headers` middleware in
src/lupin_app/main.py set `X-Frame-Options: DENY` on EVERY response. DENY blocks
ALL framing — even same-origin — so the notifications Reading Pane, which embeds
`/app/docs?path=...` in an iframe, failed with Chrome's "localhost refused to
connect". The fix carved `/app/docs` out to SAMEORIGIN. On 2026-08-03 the identical
fix was needed again for `/app/audio` (bug 4cfabc0f, the podcast overlay rendered
blank). Two instances of one fix is a pattern, and the failure mode is silent — the
next embeddable page just comes up blank until someone remembers a tuple in main.py.

So the allowlist was retired for a RULE (row c9ef4ef5): `X-Frame-Options: SAMEORIGIN`
globally. That still blocks every cross-origin framer — which is the whole of the
clickjacking defense — while permitting this app to frame its own pages. Every
framing in this app is same-origin; Cheech's 2026-08-03 sweep measured the
notifications client setting exactly two iframe srcs and no others.

WHAT THIS FILE NOW ASSERTS. The two embed cases below are unchanged in intent. The
two control cases changed shape ON PURPOSE: under the old rule they asserted that
non-frameable routes kept DENY, and that distinction no longer exists by design.
Re-pointing them at "still DENY" would be asserting the bug back. What survives, and
is what actually protects users, is that the header is PRESENT and SAMEORIGIN on
every route — never absent, and never a value that lets a third-party site frame us.

⚠️ SERVES-STALE WARNING. :7999 does not auto-reload (policy change 2026-08-01), so a
middleware edit is NOT live until the container is bounced. Run this against a server
booted AFTER the change or it reports on the old bytes — a green here would then mean
nothing at all.

Venue: :7999 (AI-discretionary — read-only header probes, no state mutation, fast).
Base URL parameterized via LUPIN_API_URL (default :7999).

Run:
    LUPIN_API_URL=http://localhost:7999 pytest src/tests/smoke/test_doc_viewer_iframe_embedding.py -v
"""

import os

import pytest
import requests

BASE_URL = os.environ.get( "LUPIN_API_URL", "http://localhost:7999" )

# Values that would permit a third-party origin to frame us. `None` is included
# deliberately: deleting the header is the quietest way to lose the defense, and a
# test that only compares strings would pass right through it.
PERMISSIVE_VALUES = ( None, "", "ALLOWALL", "ALLOW-FROM *" )


def _x_frame_options( path ):
    """GET <path> and return (status_code, X-Frame-Options header value)."""
    resp = requests.get( f"{BASE_URL}{path}", timeout=10, allow_redirects=False )
    return resp.status_code, resp.headers.get( "X-Frame-Options" )


def test_doc_viewer_page_allows_same_origin_framing():
    """The document-viewer page must be SAMEORIGIN so the Reading Pane can frame it."""
    status, xfo = _x_frame_options( "/app/docs" )
    assert status == 200, f"/app/docs should serve the viewer page (got {status})"
    assert xfo == "SAMEORIGIN", (
        f"/app/docs must send X-Frame-Options: SAMEORIGIN so the notifications "
        f"Reading Pane iframe can embed it; got {xfo!r}. DENY here is the "
        f"'localhost refused to connect' regression."
    )


def test_audio_player_page_allows_same_origin_framing():
    """The audio-player page must be SAMEORIGIN so the floating podcast overlay
    can frame it. DENY here is bug 4cfabc0f — the overlay iframe stayed blank
    (standalone worked because top-level navigation ignores X-Frame-Options)."""
    status, xfo = _x_frame_options( "/app/audio" )
    assert status == 200, f"/app/audio should serve the player page (got {status})"
    assert xfo == "SAMEORIGIN", (
        f"/app/audio must send X-Frame-Options: SAMEORIGIN so the podcast overlay "
        f"iframe can embed it; got {xfo!r}. DENY here is bug 4cfabc0f — the "
        f"overlay renders blank."
    )


@pytest.mark.parametrize( "path", [ "/app/notifications", "/health" ] )
def test_every_route_still_blocks_cross_origin_framing( path ):
    """
    The control, restated for the rule that replaced the allowlist (row c9ef4ef5).

    It no longer asserts DENY — under a global SAMEORIGIN there is no
    frameable/non-frameable split, and asserting DENY here would be asserting the
    retired allowlist back into existence. What must remain true is that no route
    can be framed by another origin.

    Covers an app page and an API route, because the middleware is global and a
    future change that scoped it to /app/* would silently strip /health.
    """
    status, xfo = _x_frame_options( path )
    assert xfo not in PERMISSIVE_VALUES, (
        f"{path} sent X-Frame-Options: {xfo!r}, which does not block cross-origin "
        f"framing. A missing or permissive header here is the clickjacking hole the "
        f"global SAMEORIGIN rule exists to close."
    )
    assert xfo == "SAMEORIGIN", (
        f"{path} should send the global X-Frame-Options: SAMEORIGIN set by "
        f"add_security_headers; got {xfo!r}. If this is DENY, the per-path allowlist "
        f"has been reintroduced — see row c9ef4ef5 for why that pattern was retired."
    )
