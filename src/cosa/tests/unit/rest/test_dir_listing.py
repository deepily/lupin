"""
Unit tests for the shared directory-listing primitives
(`cosa.rest.routers._dir_listing`).

Covers:
- `_build_view_url` — the per-extension routing table (io audio/pdf/image/pptx
  direct-binary routes + the /app/docs project-prefixed fall-through).
- `list_directory` — directory scanning with hidden-file + secrets-blocklist
  exclusion, allowed-extension filtering, dir/file entry shaping, OSError-skip,
  directories-first sort, and parent-path calculation.

Zero external dependencies — `os.scandir` is boundary-mocked with fake DirEntry
objects (no real filesystem) and `_is_secrets_path` is patched to drive the
blocklist branch deterministically.
"""

import unittest
from unittest.mock import patch, MagicMock
import time

from cosa.rest.routers._dir_listing import _build_view_url, list_directory


class _FakeEntry:
    """A minimal stand-in for os.DirEntry for scandir-mocked tests."""

    def __init__( self, name, kind="file", size=10, raise_os=False ):
        self.name   = name
        self._kind  = kind        # "dir" | "file" | "other"
        self._size  = size
        self._raise = raise_os

    def is_dir( self, follow_symlinks=True ):
        if self._raise:
            raise OSError( "permission denied" )
        return self._kind == "dir"

    def is_file( self, follow_symlinks=True ):
        return self._kind == "file"

    def stat( self ):
        s = MagicMock()
        s.st_size = self._size
        return s


def _scandir_cm( entries ):
    """Build a context-manager mock that yields `entries` from __enter__."""
    cm = MagicMock()
    cm.__enter__.return_value = iter( entries )
    cm.__exit__.return_value  = False
    return cm


class TestBuildViewUrl( unittest.TestCase ):
    """
    Unit tests for the `_build_view_url` routing table.

    Ensures:
        - io files route to audio/io-file/download per extension
        - all other (scope, kind, ext) combos route to project-prefixed /app/docs
        - rel_path is URL-encoded
    """

    def test_io_audio_extensions( self ):
        """Ensures: io .mp3/.wav files route to the /app/audio player."""
        self.assertEqual( _build_view_url( "a.mp3", "io", "file", ".mp3" ), "/app/audio?path=a.mp3" )
        self.assertEqual( _build_view_url( "a.wav", "io", "file", ".wav" ), "/app/audio?path=a.wav" )

    def test_io_pdf_inline( self ):
        """Ensures: io .pdf routes to /api/io/file (inline render)."""
        self.assertEqual( _build_view_url( "doc.pdf", "io", "file", ".pdf" ), "/api/io/file?path=doc.pdf" )

    def test_io_image_extensions( self ):
        """Ensures: io image extensions route to /api/io/file for inline rendering."""
        for ext in ( ".png", ".jpg", ".jpeg", ".gif", ".webp" ):
            self.assertEqual(
                _build_view_url( f"img{ext}", "io", "file", ext ),
                f"/api/io/file?path=img{ext}",
            )

    def test_io_pptx_download( self ):
        """Ensures: io .pptx routes to /api/io/file with download=true."""
        self.assertEqual(
            _build_view_url( "deck.pptx", "io", "file", ".pptx" ),
            "/api/io/file?path=deck.pptx&download=true",
        )

    def test_io_other_extension_falls_through_to_docs( self ):
        """Ensures: an io file with a non-binary ext falls through to /app/docs (prefixed)."""
        self.assertEqual(
            _build_view_url( "notes.md", "io", "file", ".md" ),
            "/app/docs?path=io%2Fnotes.md",
        )

    def test_non_io_scope_routes_to_docs_prefixed( self ):
        """Ensures: a registered-scope file routes to project-prefixed /app/docs."""
        self.assertEqual(
            _build_view_url( "src/rnd/x.md", "lupin", "file", ".md" ),
            "/app/docs?path=lupin%2Fsrc%2Frnd%2Fx.md",
        )

    def test_directory_routes_to_docs_prefixed( self ):
        """Ensures: a directory entry (kind=directory) routes to /app/docs prefixed."""
        self.assertEqual(
            _build_view_url( "sub", "cosa-voice", "directory", "" ),
            "/app/docs?path=cosa-voice%2Fsub",
        )

    def test_io_directory_not_treated_as_binary( self ):
        """Ensures: io + directory (kind != file) skips the binary table → /app/docs."""
        self.assertEqual(
            _build_view_url( "media", "io", "directory", "" ),
            "/app/docs?path=io%2Fmedia",
        )


class TestListDirectory( unittest.TestCase ):
    """
    Unit tests for `list_directory`.

    Requires:
        - os.scandir boundary-mocked with _FakeEntry objects
        - _is_secrets_path patched to drive the blocklist branch

    Ensures:
        - hidden + secrets entries excluded; disallowed extensions filtered
        - dir/file entries shaped per §3.2 with view_url + size
        - OSError entries skipped; neither-dir-nor-file entries ignored
        - directories-first sort; parent calculation across both arms
    """

    def test_full_listing_with_all_entry_branches( self ):
        """
        Ensures:
            - hidden (.git), secrets (creds.env), disallowed (.xyz), OSError,
              and neither-type entries are all excluded
            - one directory + one allowed file remain, correctly shaped + sorted
            - parent kept when parent_validator accepts a truthy parent
        """
        entries = [
            _FakeEntry( "readme.md", kind="file", size=42 ),     # allowed file
            _FakeEntry( "Zeta",      kind="dir" ),               # directory (sorts first)
            _FakeEntry( ".git",      kind="dir" ),               # hidden → excluded
            _FakeEntry( "creds.env", kind="file" ),              # secrets → excluded
            _FakeEntry( "skip.xyz",  kind="file" ),              # disallowed ext → excluded
            _FakeEntry( "boom",      kind="dir", raise_os=True ),# OSError → skipped
            _FakeEntry( "weird",     kind="other" ),             # neither dir nor file → ignored
        ]

        with patch( "cosa.rest.routers._dir_listing.os.scandir", return_value=_scandir_cm( entries ) ), \
             patch( "cosa.rest.routers._dir_listing._is_secrets_path",
                    side_effect=lambda name: name == "creds.env" ):
            result = list_directory(
                abs_dir          = "/abs/docs/sub",
                rel_dir          = "docs/sub/",             # scope-relative; trailing slash → rstrip
                scope            = "lupin",
                allowed_exts     = { ".md", ".txt" },
                parent_validator = lambda p: True,
            )

        self.assertEqual( result[ "kind" ], "directory" )
        self.assertEqual( result[ "scope" ], "lupin" )
        self.assertEqual( result[ "path" ], "docs/sub" )
        self.assertEqual( result[ "parent" ], "docs" )        # dirname truthy + validator True

        names = [ e[ "name" ] for e in result[ "entries" ] ]
        self.assertEqual( names, [ "Zeta", "readme.md" ] )    # directory first, then file

        d_entry = result[ "entries" ][ 0 ]
        self.assertEqual( d_entry[ "kind" ], "directory" )
        self.assertIsNone( d_entry[ "size" ] )
        self.assertEqual( d_entry[ "rel_path" ], "docs/sub/Zeta" )
        self.assertEqual( d_entry[ "view_url" ], "/app/docs?path=lupin%2Fdocs%2Fsub%2FZeta" )

        f_entry = result[ "entries" ][ 1 ]
        self.assertEqual( f_entry[ "kind" ], "file" )
        self.assertEqual( f_entry[ "size" ], 42 )
        self.assertEqual( f_entry[ "rel_path" ], "docs/sub/readme.md" )
        self.assertEqual( f_entry[ "view_url" ], "/app/docs?path=lupin%2Fdocs%2Fsub%2Freadme.md" )

    def test_root_listing_empty_rel_dir_and_parent_none( self ):
        """
        Ensures:
            - rel_dir="" (io root) takes the else-arm of child_rel for both dir + file
            - parent is None when dirname("") is falsy
        """
        entries = [
            _FakeEntry( "song.mp3", kind="file", size=7 ),
            _FakeEntry( "folder",   kind="dir" ),
        ]
        with patch( "cosa.rest.routers._dir_listing.os.scandir", return_value=_scandir_cm( entries ) ), \
             patch( "cosa.rest.routers._dir_listing._is_secrets_path", return_value=False ):
            result = list_directory(
                abs_dir          = "/abs/io",
                rel_dir          = "",
                scope            = "io",
                allowed_exts     = { ".mp3" },
                parent_validator = lambda p: True,
            )

        self.assertEqual( result[ "path" ], "" )
        self.assertIsNone( result[ "parent" ] )
        by_name = { e[ "name" ]: e for e in result[ "entries" ] }
        self.assertEqual( by_name[ "folder" ][ "rel_path" ], "folder" )   # else-arm (no rel prefix)
        self.assertEqual( by_name[ "song.mp3" ][ "rel_path" ], "song.mp3" )
        self.assertEqual( by_name[ "song.mp3" ][ "view_url" ], "/app/audio?path=song.mp3" )

    def test_parent_rejected_by_validator( self ):
        """
        Ensures:
            - A truthy parent_rel that parent_validator rejects yields parent=None
              (covers the second arm of the `or`)
        """
        entries = [ _FakeEntry( "a.md", kind="file" ) ]
        with patch( "cosa.rest.routers._dir_listing.os.scandir", return_value=_scandir_cm( entries ) ), \
             patch( "cosa.rest.routers._dir_listing._is_secrets_path", return_value=False ):
            result = list_directory(
                abs_dir          = "/abs/docs/sub",
                rel_dir          = "lupin/sub",
                scope            = "lupin",
                allowed_exts     = { ".md" },
                parent_validator = lambda p: False,
            )

        self.assertIsNone( result[ "parent" ] )


def isolated_unit_test():
    """
    Run the _dir_listing unit tests in isolation.

    Ensures:
        - Executes all TestCases and reports (success, duration, message)
    """
    import cosa.utils.util as du

    start_time = time.time()
    try:
        loader = unittest.TestLoader()
        suite  = unittest.TestSuite()
        suite.addTests( loader.loadTestsFromTestCase( TestBuildViewUrl ) )
        suite.addTests( loader.loadTestsFromTestCase( TestListDirectory ) )
        result = unittest.TextTestRunner( verbosity=2 ).run( suite )

        duration  = time.time() - start_time
        tests_run = result.testsRun
        failures  = len( result.failures )
        errors    = len( result.errors )

        success = failures == 0 and errors == 0
        if success:
            du.print_banner( "✅ ALL DIR-LISTING TESTS PASSED", prepend_nl=True )
            message = f"All {tests_run} tests passed successfully in {duration:.3f}s"
        else:
            du.print_banner( "❌ SOME DIR-LISTING TESTS FAILED", prepend_nl=True )
            message = f"{failures} failures, {errors} errors out of {tests_run} tests"

        return success, duration, message

    except Exception as e:
        duration  = time.time() - start_time
        error_msg = f"Unit test execution failed: {str(e)}"
        du.print_banner( f"💥 DIR-LISTING TEST ERROR: {error_msg}", prepend_nl=True )
        return False, duration, error_msg


if __name__ == "__main__":
    success, duration, message = isolated_unit_test()
    status = "✅ PASS" if success else "❌ FAIL"
    print( f"\n{status} Dir-listing unit tests completed in {duration:.3f}s" )
    print( f"Result: {message}" )
