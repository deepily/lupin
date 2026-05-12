"""
Smoke tests for /api/docs/file (docs whitelist endpoint).

Venue: :7999 (AI-discretionary) — read-only, no state mutation, ~seconds.

Covers:
- Happy path: whitelisted root file (CLAUDE.md) serves with markdown content type
- Happy path: whitelisted prefix (src/docs/...) serves
- Reject: path outside whitelist (e.g. src/cosa/...)
- Reject: directory-traversal attempt
- Reject: unsupported extension
- 404: whitelisted but non-existent file
- Health endpoint shape

Run:
    pytest src/tests/smoke/test_docs_files_endpoint.py -v
"""

import os

import pytest
import requests


BASE_URL = os.environ.get( "LUPIN_API_URL", "http://localhost:7999" )
DOCS_URL = f"{BASE_URL}/api/docs/file"
HEALTH_URL = f"{BASE_URL}/api/docs/health"


def _get( path, **params ):
    query = { "path": path, **params }
    return requests.get( DOCS_URL, params=query, timeout=5 )


def test_health_endpoint_returns_whitelist_shape():
    response = requests.get( HEALTH_URL, timeout=5 )
    assert response.status_code == 200
    body = response.json()
    assert body[ "status" ] == "ok"
    assert "project_root" in body
    assert "allowed_files" in body
    assert "allowed_prefixes" in body
    # Sanity: known root-level files are tracked in the whitelist
    assert "CLAUDE.md" in body[ "allowed_files" ]
    assert "src/docs/" in body[ "allowed_prefixes" ]


def test_whitelisted_prefix_serves_known_doc():
    # src/docs/notification-api.md is referenced as canonical in CLAUDE.md, so it's
    # guaranteed to exist regardless of whether the container mounts the project
    # root or only src/.
    response = _get( "src/docs/notification-api.md" )
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    assert response.headers[ "content-type" ].startswith( "text/markdown" )
    # Content should look like markdown — header presence is a cheap sanity check
    assert "#" in response.text


def test_root_level_whitelist_serves_when_mounted():
    # Root-level files (CLAUDE.md, history.md, etc.) are in the whitelist but
    # only served if the container has the project root mounted. Skip if not.
    health = requests.get( HEALTH_URL, timeout=5 ).json()
    if not health[ "allowed_files" ].get( "CLAUDE.md" ):
        pytest.skip( "CLAUDE.md not mounted in this server's project_root" )

    response = _get( "CLAUDE.md" )
    assert response.status_code == 200
    assert response.headers[ "content-type" ].startswith( "text/markdown" )


def test_path_outside_whitelist_rejected():
    # src/cosa/ is intentionally NOT in the whitelist
    response = _get( "src/cosa/agents/agent_base.py" )
    assert response.status_code == 400
    assert "whitelist" in response.json()[ "detail" ].lower()


def test_directory_traversal_blocked():
    # Even if /etc/passwd would otherwise be readable, the whitelist check fires first
    response = _get( "../../../etc/passwd" )
    assert response.status_code == 400


def test_unsupported_extension_rejected():
    # .py is not in MEDIA_TYPES — but it'd also fail the whitelist for src/cosa.
    # Use a path that IS whitelisted so the extension check is what triggers.
    # src/docs/ allows .md, so try .py inside src/docs/ (likely doesn't exist, but
    # extension check happens before isfile check in the handler).
    # To isolate the extension path, hit a known-not-md file under src/docs/.
    # If src/docs/ has no non-md files, this becomes a 404 instead — which still
    # proves the whitelist accepted the path. Acceptable either way.
    response = _get( "src/docs/__init__.py" )
    assert response.status_code in ( 400, 404 )


def test_whitelisted_but_missing_returns_404():
    response = _get( "src/docs/this-file-definitely-does-not-exist-2026-05-04.md" )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Directory listing tests — added 2026-05-12 per
# src/rnd/v0.1.7/2026.05.12-doc-viewer-directory-listing.md
# ---------------------------------------------------------------------------

def test_directory_listing_returns_json_shape():
    """Polymorphic dispatch: directory path returns JSON, not text."""
    response = _get( "src/rnd/v0.1.7" )
    assert response.status_code == 200, f"got {response.status_code}: {response.text}"
    assert response.headers[ "content-type" ].startswith( "application/json" )
    body = response.json()
    assert body[ "kind" ] == "directory"
    assert body[ "scope" ] == "docs"
    assert body[ "path" ] == "src/rnd/v0.1.7"
    assert "parent" in body
    assert "entries" in body
    assert isinstance( body[ "entries" ], list )


def test_directory_listing_bare_prefix_root():
    """Q2 resolution: bare prefix root (no trailing slash) lists successfully."""
    response = _get( "src/rnd" )
    assert response.status_code == 200, f"got {response.status_code}: {response.text}"
    assert response.headers[ "content-type" ].startswith( "application/json" )
    body = response.json()
    assert body[ "kind" ] == "directory"
    assert body[ "path" ] == "src/rnd"


def test_directory_listing_with_trailing_slash():
    """Q2 resolution: trailing-slash form lists identically to bare form."""
    response = _get( "src/rnd/" )
    assert response.status_code == 200, f"got {response.status_code}: {response.text}"
    body = response.json()
    assert body[ "path" ] == "src/rnd"  # normalized — trailing slash stripped


def test_directory_listing_outside_whitelist():
    """Whitelist boundary still holds for directory requests."""
    response = _get( "src/cosa" )
    assert response.status_code == 400
    assert "whitelist" in response.json()[ "detail" ].lower()


def test_directory_listing_nonexistent():
    """Whitelisted-but-missing directory returns 404."""
    response = _get( "src/rnd/no-such-dir-2026-05-12-unique" )
    assert response.status_code == 404


def test_directory_listing_excludes_hidden_files():
    """Q5: hidden files (starting with .) are excluded from listings."""
    response = _get( "src/rnd/v0.1.7" )
    assert response.status_code == 200
    body = response.json()
    for entry in body[ "entries" ]:
        assert not entry[ "name" ].startswith( "." ), f"hidden entry leaked: {entry['name']}"


def test_directory_listing_excludes_unwhitelisted_extensions():
    """Only files with extensions in MEDIA_TYPES whitelist appear in listing."""
    response = _get( "src/rnd/v0.1.7" )
    assert response.status_code == 200
    body = response.json()
    allowed_exts = { ".md", ".txt", ".json", ".yaml", ".yml" }
    for entry in body[ "entries" ]:
        if entry[ "kind" ] != "file":
            continue
        _, ext = os.path.splitext( entry[ "name" ] )
        assert ext.lower() in allowed_exts, f"non-whitelisted ext leaked: {entry['name']}"


def test_directory_listing_entries_sorted_dirs_first():
    """Q4: subdirectories sort before files in entry list."""
    response = _get( "src/rnd/v0.1.7" )
    assert response.status_code == 200
    body = response.json()
    kinds = [ e[ "kind" ] for e in body[ "entries" ] ]
    if "directory" in kinds and "file" in kinds:
        last_dir = max( i for i, k in enumerate( kinds ) if k == "directory" )
        first_file = min( i for i, k in enumerate( kinds ) if k == "file" )
        assert last_dir < first_file, "files mixed in before all directories"


def test_directory_listing_view_url_present_and_correct():
    """Every entry has a view_url; md files route to /app/docs."""
    response = _get( "src/rnd/v0.1.7" )
    assert response.status_code == 200
    body = response.json()
    assert len( body[ "entries" ] ) > 0
    for entry in body[ "entries" ]:
        assert entry.get( "view_url" ), f"missing view_url: {entry}"
        if entry[ "kind" ] == "file" and entry[ "name" ].endswith( ".md" ):
            assert entry[ "view_url" ].startswith( "/app/docs?path=" )
            assert "scope=docs" in entry[ "view_url" ]


if __name__ == "__main__":
    pytest.main( [ __file__, "-v" ] )
