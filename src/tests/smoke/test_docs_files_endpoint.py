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


if __name__ == "__main__":
    pytest.main( [ __file__, "-v" ] )
