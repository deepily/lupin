"""
Unit tests for cosa.rest.routers._dir_listing.

Covers the per-extension routing table in §3.4a of
src/rnd/v0.1.7/2026.05.12-doc-viewer-directory-listing.md, updated 2026-05-16
for path-prefix routing per the 2026-05-15 unification (Q-R2): the legacy
`?scope=` query param is retired; project name is now the first segment of
the URL's `path` param. Scope param to `_build_view_url` IS the project name.

Venue: :7999 (AI-discretionary) — no server contact, pure in-process.

Run:
    pytest src/tests/unit/test_dir_listing.py -v
"""

import os
import tempfile

import pytest

from cosa.rest.routers._dir_listing import _build_view_url, list_directory


# ---------------------------------------------------------------------------
# _build_view_url — routing table (§3.4a; updated 2026-05-16)
# ---------------------------------------------------------------------------

class TestBuildViewUrlRoutingTable:
    """One assertion per row of the §3.4a table (post-unification shapes)."""

    def test_directory_project_scope( self ):
        url = _build_view_url( "src/rnd/v0.1.7", "lupin", "directory", "" )
        assert url == "/app/docs?path=lupin%2Fsrc%2Frnd%2Fv0.1.7"

    def test_directory_io_scope( self ):
        url = _build_view_url( "podcasts/my-show", "io", "directory", "" )
        assert url == "/app/docs?path=io%2Fpodcasts%2Fmy-show"

    def test_md_file_project_scope( self ):
        url = _build_view_url( "src/rnd/v0.1.7/foo.md", "lupin", "file", ".md" )
        assert url == "/app/docs?path=lupin%2Fsrc%2Frnd%2Fv0.1.7%2Ffoo.md"

    def test_md_file_io_scope( self ):
        url = _build_view_url( "deep-research/report.md", "io", "file", ".md" )
        assert url == "/app/docs?path=io%2Fdeep-research%2Freport.md"

    @pytest.mark.parametrize( "ext", [ ".txt", ".json", ".yaml", ".yml" ] )
    def test_other_text_extensions_use_doc_viewer( self, ext ):
        url = _build_view_url( f"src/docs/sample{ext}", "lupin", "file", ext )
        assert url.startswith( "/app/docs?path=lupin%2Fsrc%2Fdocs%2Fsample" )
        # Legacy ?scope= retired
        assert "scope=" not in url

    def test_mp3_io_routes_to_audio_player( self ):
        url = _build_view_url( "podcasts/ep1.mp3", "io", "file", ".mp3" )
        assert url == "/app/audio?path=podcasts%2Fep1.mp3"

    def test_wav_io_routes_to_audio_player( self ):
        url = _build_view_url( "podcasts/intro.wav", "io", "file", ".wav" )
        assert url == "/app/audio?path=podcasts%2Fintro.wav"

    def test_pdf_io_routes_to_inline_render( self ):
        url = _build_view_url( "deep-research/report.pdf", "io", "file", ".pdf" )
        # NO &download flag — browser renders pdf inline
        assert url == "/api/io/file?path=deep-research%2Freport.pdf"

    def test_pptx_io_forces_download( self ):
        url = _build_view_url( "presentations/deck.pptx", "io", "file", ".pptx" )
        assert "&download=true" in url
        assert url == "/api/io/file?path=presentations%2Fdeck.pptx&download=true"

    @pytest.mark.parametrize( "ext", [ ".png", ".jpg", ".jpeg", ".gif", ".webp" ] )
    def test_image_io_routes_to_inline_render( self, ext ):
        """Images render inline in the browser via direct URL (Option A — same as PDF)."""
        url = _build_view_url( f"test-suite/screenshot{ext}", "io", "file", ext )
        assert url.startswith( "/api/io/file?path=" )
        # No &download flag — image renders inline
        assert "download" not in url

    def test_path_with_special_characters_is_encoded( self ):
        url = _build_view_url( "src/rnd/v0.1.7/foo bar+baz.md", "lupin", "file", ".md" )
        # Spaces and + must be percent-encoded; quote(safe="") encodes everything
        # except unreserved chars
        assert " " not in url
        assert "%20" in url
        # The path-portion of the URL should not contain a raw '+'
        path_value = url.split( "?path=", 1 )[ 1 ]
        assert "+" not in path_value


# ---------------------------------------------------------------------------
# list_directory — filtering, sorting, parent calc
# ---------------------------------------------------------------------------

class TestListDirectory:
    """Behavioral tests against a temp directory."""

    @pytest.fixture
    def temp_dir_with_mixed_content( self, tmp_path ):
        """
        Create a temp directory with:
        - 2 subdirectories (one hidden)
        - 3 whitelisted files (.md, .txt, .json)
        - 2 non-whitelisted files (.py, .png)
        - 1 hidden file
        """
        ( tmp_path / "subdir_a" ).mkdir()
        ( tmp_path / "subdir_b" ).mkdir()
        ( tmp_path / ".hidden_dir" ).mkdir()

        ( tmp_path / "alpha.md" ).write_text( "# Alpha\n" )
        ( tmp_path / "beta.txt" ).write_text( "beta content" )
        ( tmp_path / "config.json" ).write_text( '{"k": "v"}' )

        ( tmp_path / "script.py" ).write_text( "print('x')\n" )
        ( tmp_path / "image.png" ).write_bytes( b"\x89PNG" )
        ( tmp_path / ".DS_Store" ).write_bytes( b"\x00\x01" )

        return tmp_path

    def test_returns_top_level_shape( self, temp_dir_with_mixed_content ):
        listing = list_directory(
            abs_dir          = str( temp_dir_with_mixed_content ),
            rel_dir          = "src/docs/sample",
            scope            = "docs",
            allowed_exts     = { ".md", ".txt", ".json" },
            parent_validator = lambda p: True,
        )
        assert listing[ "kind" ] == "directory"
        assert listing[ "scope" ] == "docs"
        assert listing[ "path" ] == "src/docs/sample"
        assert "entries" in listing
        assert "parent" in listing

    def test_excludes_hidden_entries( self, temp_dir_with_mixed_content ):
        listing = list_directory(
            abs_dir          = str( temp_dir_with_mixed_content ),
            rel_dir          = "src/docs",
            scope            = "docs",
            allowed_exts     = { ".md", ".txt", ".json" },
            parent_validator = lambda p: True,
        )
        names = { e[ "name" ] for e in listing[ "entries" ] }
        assert ".hidden_dir" not in names
        assert ".DS_Store" not in names

    def test_excludes_non_whitelisted_extensions( self, temp_dir_with_mixed_content ):
        listing = list_directory(
            abs_dir          = str( temp_dir_with_mixed_content ),
            rel_dir          = "src/docs",
            scope            = "docs",
            allowed_exts     = { ".md", ".txt", ".json" },
            parent_validator = lambda p: True,
        )
        names = { e[ "name" ] for e in listing[ "entries" ] }
        assert "script.py" not in names
        assert "image.png" not in names

    def test_directories_sorted_before_files( self, temp_dir_with_mixed_content ):
        listing = list_directory(
            abs_dir          = str( temp_dir_with_mixed_content ),
            rel_dir          = "src/docs",
            scope            = "docs",
            allowed_exts     = { ".md", ".txt", ".json" },
            parent_validator = lambda p: True,
        )
        kinds_in_order = [ e[ "kind" ] for e in listing[ "entries" ] ]
        # All directories must come before any file
        if "directory" in kinds_in_order and "file" in kinds_in_order:
            last_dir_idx = max( i for i, k in enumerate( kinds_in_order ) if k == "directory" )
            first_file_idx = min( i for i, k in enumerate( kinds_in_order ) if k == "file" )
            assert last_dir_idx < first_file_idx

    def test_entries_alphabetical_within_group( self, temp_dir_with_mixed_content ):
        listing = list_directory(
            abs_dir          = str( temp_dir_with_mixed_content ),
            rel_dir          = "src/docs",
            scope            = "docs",
            allowed_exts     = { ".md", ".txt", ".json" },
            parent_validator = lambda p: True,
        )
        dirs = [ e[ "name" ] for e in listing[ "entries" ] if e[ "kind" ] == "directory" ]
        files = [ e[ "name" ] for e in listing[ "entries" ] if e[ "kind" ] == "file" ]
        assert dirs == sorted( dirs, key=str.lower )
        assert files == sorted( files, key=str.lower )

    def test_file_entries_carry_size_and_view_url( self, temp_dir_with_mixed_content ):
        listing = list_directory(
            abs_dir          = str( temp_dir_with_mixed_content ),
            rel_dir          = "src/docs",
            scope            = "docs",
            allowed_exts     = { ".md", ".txt", ".json" },
            parent_validator = lambda p: True,
        )
        file_entries = [ e for e in listing[ "entries" ] if e[ "kind" ] == "file" ]
        assert len( file_entries ) > 0
        for entry in file_entries:
            assert isinstance( entry[ "size" ], int )
            assert entry[ "size" ] >= 0
            assert entry[ "view_url" ].startswith( "/app/docs?path=" )

    def test_directory_entries_have_null_size( self, temp_dir_with_mixed_content ):
        listing = list_directory(
            abs_dir          = str( temp_dir_with_mixed_content ),
            rel_dir          = "src/docs",
            scope            = "docs",
            allowed_exts     = { ".md", ".txt", ".json" },
            parent_validator = lambda p: True,
        )
        dir_entries = [ e for e in listing[ "entries" ] if e[ "kind" ] == "directory" ]
        for entry in dir_entries:
            assert entry[ "size" ] is None
            assert entry[ "view_url" ].startswith( "/app/docs?path=" )

    def test_parent_set_when_validator_passes( self, temp_dir_with_mixed_content ):
        listing = list_directory(
            abs_dir          = str( temp_dir_with_mixed_content ),
            rel_dir          = "src/rnd/v0.1.7",
            scope            = "docs",
            allowed_exts     = { ".md" },
            parent_validator = lambda p: True,
        )
        assert listing[ "parent" ] == "src/rnd"

    def test_parent_null_when_validator_rejects( self, temp_dir_with_mixed_content ):
        listing = list_directory(
            abs_dir          = str( temp_dir_with_mixed_content ),
            rel_dir          = "src/rnd",
            scope            = "docs",
            allowed_exts     = { ".md" },
            parent_validator = lambda p: False,  # always reject — simulates "src" not whitelisted
        )
        assert listing[ "parent" ] is None

    def test_parent_null_at_root( self, temp_dir_with_mixed_content ):
        listing = list_directory(
            abs_dir          = str( temp_dir_with_mixed_content ),
            rel_dir          = "",  # io-scope root case
            scope            = "io",
            allowed_exts     = { ".md" },
            parent_validator = lambda p: True,
        )
        assert listing[ "parent" ] is None

    def test_trailing_slash_in_rel_dir_normalized( self, temp_dir_with_mixed_content ):
        listing_a = list_directory(
            abs_dir          = str( temp_dir_with_mixed_content ),
            rel_dir          = "src/rnd",
            scope            = "docs",
            allowed_exts     = { ".md" },
            parent_validator = lambda p: True,
        )
        listing_b = list_directory(
            abs_dir          = str( temp_dir_with_mixed_content ),
            rel_dir          = "src/rnd/",
            scope            = "docs",
            allowed_exts     = { ".md" },
            parent_validator = lambda p: True,
        )
        assert listing_a[ "path" ] == listing_b[ "path" ] == "src/rnd"

    def test_io_scope_propagates_to_view_url( self, temp_dir_with_mixed_content ):
        listing = list_directory(
            abs_dir          = str( temp_dir_with_mixed_content ),
            rel_dir          = "podcasts",
            scope            = "io",
            allowed_exts     = { ".md" },
            parent_validator = lambda p: True,
        )
        assert listing[ "scope" ] == "io"
        for entry in listing[ "entries" ]:
            view = entry[ "view_url" ]
            # Path-prefix routing: /app/docs URLs include io/ as the first segment.
            # Direct binary routes (/app/audio, /api/io/file) keep io-relative paths.
            assert (
                view.startswith( "/app/docs?path=io%2F" )
                or view.startswith( "/app/audio" )
                or view.startswith( "/api/io/file" )
            ), f"unexpected view_url shape: {view}"


if __name__ == "__main__":
    pytest.main( [ __file__, "-v" ] )
