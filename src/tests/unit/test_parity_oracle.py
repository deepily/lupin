"""
WS3 — unit coverage for the Layout-Parity Oracle Python helpers
(src/tests/e2e_ui/parity_oracle.py). Pure path/text/hash logic — no server, no
browser. Gives the helper 100% coverage independent of WS1 (which the Tier 0
test gates on), so the shared module is covered now.

Venue: :7999 / unit.
"""

from __future__ import annotations

import importlib
from pathlib import Path

oracle = importlib.import_module( "tests.e2e_ui.parity_oracle" )


def test_repo_root_is_a_path():
    root = oracle.repo_root()
    assert isinstance( root, Path )
    assert root.is_absolute()


def test_shared_sheet_path_under_repo_root():
    p = oracle.shared_sheet_path()
    assert p == oracle.repo_root() / oracle.SHARED_SHEET_RELPATH
    assert str( p ).endswith( "css/shared/notifications-surface.css" )


def test_html_path_resolves_static_html():
    p = oracle.html_path( "multiplexer.html" )
    assert str( p ).endswith( "src/lupin_app/static/html/multiplexer.html" )


def test_linked_shared_hrefs_matches_canonical_and_cachebusted():
    html = (
        '<link rel="stylesheet" href="/static/css/lupin-base.css">\n'
        '<link rel="stylesheet" href="/static/css/shared/notifications-surface.css">\n'
        '<link rel="stylesheet" href="/static/css/shared/notifications-surface.css?v=abc123">\n'
    )
    hrefs = oracle.linked_shared_hrefs( html )
    assert hrefs == [
        "/static/css/shared/notifications-surface.css",
        "/static/css/shared/notifications-surface.css?v=abc123",
    ]


def test_linked_shared_hrefs_empty_when_absent():
    html = '<link rel="stylesheet" href="/static/css/lupin-base.css">'
    assert oracle.linked_shared_hrefs( html ) == []


def test_content_hash_is_stable_12_char_digest( tmp_path ):
    f = tmp_path / "sheet.css"
    f.write_bytes( b".sender-card { display: flex; }" )
    h1 = oracle.content_hash( f )
    h2 = oracle.content_hash( f )
    assert h1 == h2
    assert len( h1 ) == 12
    # A byte change flips the hash (trip-wire behavior).
    f.write_bytes( b".sender-card { display: block; }" )
    assert oracle.content_hash( f ) != h1
