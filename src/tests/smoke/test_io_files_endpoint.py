"""
Smoke tests for /api/io/file directory listing (polymorphic endpoint).

Venue: :7999 (AI-discretionary) — read-only, no state mutation, ~seconds.

Covers the scope=io case of the directory-listing extension:
- Directory listing returns JSON with scope="io"
- view_url routes per §3.4a (updated 2026-05-16 for path-prefix routing):
  * .mp3 / .wav → /app/audio?path=<io-relative>
  * .pdf → /api/io/file?path=<io-relative> (no &download)
  * .pptx → /api/io/file?path=<io-relative>&download=true
  * .md / .txt / .json / .yaml / .yml → /app/docs?path=io/<rel> (project-prefixed)
- Hidden files excluded; non-whitelisted extensions excluded
- Existing file-serving behavior unchanged

Run:
    pytest src/tests/smoke/test_io_files_endpoint.py -v

Design docs:
- src/rnd/v0.1.7/2026.05.12-doc-viewer-directory-listing.md (original)
- src/rnd/v0.1.7/2026.05.15-doc-viewer-scope-unification.md (path-prefix routing)
"""

import os

import pytest
import requests


BASE_URL = os.environ.get( "LUPIN_API_URL", "http://localhost:7999" )
IO_URL = f"{BASE_URL}/api/io/file"


def _login():
    email    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
    password = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )
    if not email or not password:
        pytest.skip( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_{EMAIL,PASSWORD} not set" )
    resp = requests.post(
        f"{BASE_URL}/auth/login",
        json    = { "email": email, "password": password },
        timeout = 10,
    )
    resp.raise_for_status()
    return resp.json()[ "tokens" ][ "access_token" ]


# Module-scoped token cached on first use — avoids 14 logins per test session.
_TOKEN: str = None


def _token():
    global _TOKEN
    if _TOKEN is None:
        _TOKEN = _login()
    return _TOKEN


def _get( path, **params ):
    query   = { "path": path, **params }
    headers = { "Authorization": f"Bearer {_token()}" }
    return requests.get( IO_URL, params=query, headers=headers, timeout=5 )


# ---------------------------------------------------------------------------
# Directory listing — shape + routing per §3.4a
# ---------------------------------------------------------------------------

def test_io_root_directory_lists():
    """Empty path lists the io root."""
    response = _get( "" )
    assert response.status_code == 200, f"got {response.status_code}: {response.text}"
    assert response.headers[ "content-type" ].startswith( "application/json" )
    body = response.json()
    assert body[ "kind" ] == "directory"
    assert body[ "scope" ] == "io"
    assert body[ "path" ] == ""
    assert body[ "parent" ] is None


def test_io_subdirectory_lists():
    """A known stable io subdir lists successfully."""
    response = _get( "podcasts" )
    assert response.status_code == 200, f"got {response.status_code}: {response.text}"
    body = response.json()
    assert body[ "kind" ] == "directory"
    assert body[ "scope" ] == "io"
    assert body[ "path" ] == "podcasts"


def test_io_listing_entries_have_view_urls():
    """Every entry carries a non-empty view_url."""
    response = _get( "" )
    assert response.status_code == 200
    body = response.json()
    assert len( body[ "entries" ] ) > 0
    for entry in body[ "entries" ]:
        assert entry.get( "view_url" ), f"missing view_url: {entry}"


def test_io_mp3_entries_route_to_audio_player():
    """mp3 view_url goes to /app/audio per Q1 resolution (NOT a download URL)."""
    response = _get( "" )
    assert response.status_code == 200
    body = response.json()
    mp3_entries = [ e for e in body[ "entries" ] if e[ "kind" ] == "file" and e[ "name" ].endswith( ".mp3" ) ]
    if not mp3_entries:
        pytest.skip( "no .mp3 files at io root in this environment" )
    for entry in mp3_entries:
        assert entry[ "view_url" ].startswith( "/app/audio?path=" ), \
            f"mp3 should route to /app/audio: {entry['view_url']}"
        assert "download" not in entry[ "view_url" ]


def test_io_wav_entries_route_to_audio_player():
    """wav view_url goes to /app/audio (same as mp3)."""
    response = _get( "" )
    assert response.status_code == 200
    body = response.json()
    wav_entries = [ e for e in body[ "entries" ] if e[ "kind" ] == "file" and e[ "name" ].endswith( ".wav" ) ]
    if not wav_entries:
        pytest.skip( "no .wav files at io root in this environment" )
    for entry in wav_entries:
        assert entry[ "view_url" ].startswith( "/app/audio?path=" )


def test_io_pdf_entries_route_inline_no_download():
    """pdf view_url goes to /api/io/file WITHOUT &download=true (browser renders inline)."""
    response = _get( "" )
    assert response.status_code == 200
    body = response.json()
    pdf_entries = [ e for e in body[ "entries" ] if e[ "kind" ] == "file" and e[ "name" ].endswith( ".pdf" ) ]
    if not pdf_entries:
        pytest.skip( "no .pdf files at io root in this environment" )
    for entry in pdf_entries:
        assert entry[ "view_url" ].startswith( "/api/io/file?path=" )
        assert "download=true" not in entry[ "view_url" ]


def test_io_text_entries_route_to_doc_viewer_with_io_prefix():
    """.md/.txt/.json/.yaml/.yml route to /app/docs?path=io/<rel> (path-prefix routing)."""
    response = _get( "" )
    assert response.status_code == 200
    body = response.json()
    text_entries = [
        e for e in body[ "entries" ]
        if e[ "kind" ] == "file" and any( e[ "name" ].endswith( ext ) for ext in ( ".md", ".txt", ".json", ".yaml", ".yml" ) )
    ]
    if not text_entries:
        pytest.skip( "no renderable text files at io root in this environment" )
    for entry in text_entries:
        view = entry[ "view_url" ]
        # New path-prefix form: /app/docs?path=io%2F<rel>
        assert view.startswith( "/app/docs?path=io%2F" ), \
            f"expected io-prefixed view_url, got: {view}"
        # Legacy ?scope= retired
        assert "scope=" not in view


def test_io_listing_excludes_unwhitelisted_extensions():
    """.py files at io root must NOT appear in the listing."""
    response = _get( "" )
    assert response.status_code == 200
    body = response.json()
    allowed = { ".md", ".txt", ".json", ".yaml", ".yml", ".mp3", ".wav", ".pdf", ".pptx" }
    for entry in body[ "entries" ]:
        if entry[ "kind" ] != "file":
            continue
        _, ext = os.path.splitext( entry[ "name" ] )
        assert ext.lower() in allowed, f"non-whitelisted extension leaked: {entry['name']}"


def test_io_listing_excludes_hidden_entries():
    """Names starting with . are excluded."""
    response = _get( "" )
    assert response.status_code == 200
    body = response.json()
    for entry in body[ "entries" ]:
        assert not entry[ "name" ].startswith( "." ), f"hidden entry leaked: {entry['name']}"


def test_io_listing_dirs_sorted_before_files():
    """Q4: subdirectories first, then files."""
    response = _get( "" )
    assert response.status_code == 200
    body = response.json()
    kinds = [ e[ "kind" ] for e in body[ "entries" ] ]
    if "directory" in kinds and "file" in kinds:
        last_dir = max( i for i, k in enumerate( kinds ) if k == "directory" )
        first_file = min( i for i, k in enumerate( kinds ) if k == "file" )
        assert last_dir < first_file


# ---------------------------------------------------------------------------
# Regression: existing file-serving behavior unchanged
# ---------------------------------------------------------------------------

def test_io_existing_file_serving_unchanged():
    """A known io text file still serves as text (no Content-Type change)."""
    # chat_history.txt is referenced as a stable artifact in io root
    response = _get( "chat_history.txt" )
    if response.status_code == 404:
        pytest.skip( "chat_history.txt not present in this environment" )
    assert response.status_code == 200
    assert response.headers[ "content-type" ].startswith( "text/plain" )


# ---------------------------------------------------------------------------
# Inline rendering (Content-Disposition: inline for browser-renderable types)
# Added 2026-05-12 per Rick's "I want to view PNGs in place" request.
# ---------------------------------------------------------------------------

PNG_PATH = (
    "test-suite/visual-baselines/test_doc_viewer_directory/"
    "test_visual_docs_scope_listing/doc_viewer_directory_listing_docs.png"
)


def test_png_serves_with_inline_content_disposition():
    """PNG default response has Content-Disposition: inline so browser renders in place."""
    response = _get( PNG_PATH )
    if response.status_code == 404:
        pytest.skip( "visual baseline PNG not present in this environment" )
    assert response.status_code == 200
    assert response.headers[ "content-type" ] == "image/png"
    cd = response.headers.get( "content-disposition", "" ).lower()
    assert "inline" in cd, f"expected inline disposition, got: {cd}"
    assert "attachment" not in cd


def test_png_with_download_flag_forces_attachment():
    """?download=true still forces attachment for PNGs (override preserved)."""
    response = _get( PNG_PATH, download="true" )
    if response.status_code == 404:
        pytest.skip( "visual baseline PNG not present in this environment" )
    assert response.status_code == 200
    cd = response.headers.get( "content-disposition", "" ).lower()
    assert "attachment" in cd, f"expected attachment with download flag, got: {cd}"


def test_pptx_still_defaults_to_attachment():
    """pptx (non-inline-renderable) defaults to attachment without download flag."""
    # Find any pptx in io/ — skip if none exist
    listing = _get( "" ).json()
    pptx_entries = [ e for e in listing.get( "entries", [ ] ) if e[ "name" ].endswith( ".pptx" ) ]
    if not pptx_entries:
        pytest.skip( "no .pptx files at io root in this environment" )
    response = _get( pptx_entries[ 0 ][ "rel_path" ] )
    assert response.status_code == 200
    cd = response.headers.get( "content-disposition", "" ).lower()
    assert "attachment" in cd, f"pptx should default to attachment, got: {cd}"


def test_png_listed_in_directory_with_inline_view_url():
    """PNG entries appear in directory listings with /api/io/file view_url (no download flag)."""
    response = _get( "test-suite/visual-baselines/test_doc_viewer_directory/test_visual_docs_scope_listing" )
    if response.status_code == 404:
        pytest.skip( "visual baseline directory not present in this environment" )
    body = response.json()
    png_entries = [ e for e in body[ "entries" ] if e[ "name" ].endswith( ".png" ) ]
    assert len( png_entries ) > 0, "PNG should appear in listing now that it's whitelisted"
    for entry in png_entries:
        assert entry[ "view_url" ].startswith( "/api/io/file?path=" )
        assert "download" not in entry[ "view_url" ]


if __name__ == "__main__":
    pytest.main( [ __file__, "-v" ] )
