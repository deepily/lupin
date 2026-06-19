"""
Smoke test — document-viewer iframe embedding (X-Frame-Options).

Regression (fixed 2026-05-30, Speedy 🌿 session fb0bc8a5): the global
`add_security_headers` middleware in src/lupin_app/main.py set
`X-Frame-Options: DENY` on EVERY response. DENY blocks ALL framing — even
same-origin — so the notifications master-detail Reading Pane (which embeds
`/app/docs?path=...` in an iframe) failed with Chrome's "localhost refused to
connect" when a user followed a doc-link.

Fix: serve the document-viewer page (`/app/docs`) with `X-Frame-Options:
SAMEORIGIN` (still blocks cross-origin clickjacking) while keeping `DENY`
everywhere else.

Venue: :7999 (AI-discretionary — read-only header probes, no state mutation,
fast). Base URL parameterized via LUPIN_API_URL (default :7999).

Run:
    LUPIN_API_URL=http://localhost:7999 pytest src/tests/smoke/test_doc_viewer_iframe_embedding.py -v
"""

import os

import pytest
import requests

BASE_URL = os.environ.get( "LUPIN_API_URL", "http://localhost:7999" )


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


def test_notifications_page_still_denies_framing():
    """Control: non-viewer routes keep the stricter DENY (clickjacking defense)."""
    status, xfo = _x_frame_options( "/app/notifications" )
    assert xfo == "DENY", (
        f"/app/notifications must keep X-Frame-Options: DENY (only the doc-viewer "
        f"is intentionally frameable); got {xfo!r}"
    )


def test_health_endpoint_still_denies_framing():
    """Control: API/health routes keep DENY — the SAMEORIGIN carve-out is /app/docs only."""
    status, xfo = _x_frame_options( "/health" )
    assert xfo == "DENY", f"/health must keep X-Frame-Options: DENY; got {xfo!r}"
