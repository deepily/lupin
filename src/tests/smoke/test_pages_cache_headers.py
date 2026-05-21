"""
Smoke tests for the /app/* SPA-shell Cache-Control header policy.

Tier: smoke (:7999, AI-discretionary per CLAUDE.md TESTING VENUES).

Driven by 2026-05-21 PNG-render bug (Rachel's plot URL rendered as bytecode
because the browser cached a pre-image-MIME-dispatch document-viewer.html
that didn't have the image/* dispatch branch yet). Fix: `_serve_file` in
`src/cosa/rest/routers/pages.py` sets `Cache-Control: no-cache` so browsers
always revalidate. ETag + Last-Modified remain (FileResponse default), so
revalidation is a cheap conditional GET — 304 when content is unchanged.

Covered:
- `Cache-Control: no-cache` on /app/docs (the route that bit us)
- Same header on /app/notifications and /app (regression-guards for the
  shared `_serve_file` helper)
- `ETag` and `Last-Modified` still emitted (revalidation must remain cheap)
"""

import os
import urllib.request


BASE_URL = os.environ.get( "LUPIN_API_URL", "http://localhost:7999" )

# Routes covered by the shared _serve_file helper in pages.py.
SHELL_ROUTES = [
    "/app",
    "/app/docs",
    "/app/notifications",
    "/app/multiplexer",
    "/app/audio",
]


def _head_like_get( path: str ):
    """
    GET the URL and return (status, headers_dict).

    Uses urllib because HEAD against /app/* returns 405 in this app — only
    GET is allowed. We discard the body and inspect headers only.
    """
    url = f"{BASE_URL}{path}"
    req = urllib.request.Request( url, method="GET" )
    with urllib.request.urlopen( req, timeout=10 ) as resp:
        # Drain body so connection closes; we only care about headers
        resp.read()
        return resp.status, { k.lower(): v for k, v in resp.headers.items() }


def test_app_docs_sends_no_cache_header():
    """The route that bit us: /app/docs must carry Cache-Control: no-cache."""
    status, headers = _head_like_get( "/app/docs" )
    assert status == 200
    assert headers.get( "cache-control" ) == "no-cache", \
        f"unexpected cache-control: {headers.get( 'cache-control' )!r}"


def test_all_spa_shells_send_no_cache_header():
    """Regression guard — every /app/* SPA shell shares the _serve_file path."""
    for route in SHELL_ROUTES:
        status, headers = _head_like_get( route )
        assert status == 200, f"{route} returned {status}"
        cc = headers.get( "cache-control" )
        assert cc == "no-cache", f"{route} cache-control: {cc!r}"


def test_app_docs_keeps_etag_and_last_modified():
    """Revalidation must stay cheap — ETag + Last-Modified preserved."""
    _status, headers = _head_like_get( "/app/docs" )
    assert headers.get( "etag" ), "ETag missing — conditional GET would re-transfer body"
    assert headers.get( "last-modified" ), "Last-Modified missing — same concern"


if __name__ == "__main__":
    import pytest
    pytest.main( [ __file__, "-v" ] )
