"""
Unit tests for the io-files router (`cosa.rest.routers.io_files`).

Covers the polymorphic `/api/io/file` endpoint:
- path-prefix normalization (absolute io_base strip, leading-slash strip, "io/" strip)
- directory-traversal block (400) + secrets-blocklist block (400)
- directory listing branch (root + nested, via list_directory → JSONResponse)
- 404 missing file, 400 unsupported extension
- forced download (attachment) + 500 on FileResponse error
- text files → PlainTextResponse (+ 500 on read error)
- binary files → FileResponse inline (mp3) vs attachment (pptx) (+ 500 on error)
And the `/api/io/health` endpoint (io present w/ subdir counts + io absent).

Zero external dependencies — project root, os.path.isdir/isfile, os.walk, open,
list_directory, and the FastAPI response classes are all boundary-mocked. No real
filesystem access; the auth dependency is bypassed by passing current_user.
"""

import unittest
from unittest.mock import patch, MagicMock, mock_open
import asyncio
import time

from fastapi import HTTPException

from cosa.rest.routers.io_files import get_io_file, io_files_health, router, MEDIA_TYPES


class TestGetIoFile( unittest.TestCase ):
    """
    Unit tests for `get_io_file`.

    Requires:
        - project root + filesystem + response classes boundary-mocked

    Ensures:
        - every path-normalization + validation + serving branch is exercised
    """

    def setUp( self ):
        """Ensures: a stable /proj root + non-secret default per test."""
        self.user = { "uid": "u" }
        p1 = patch( "cosa.rest.routers.io_files.cu.get_project_root", return_value="/proj" )
        p1.start(); self.addCleanup( p1.stop )
        p2 = patch( "cosa.rest.routers.io_files._is_secrets_path", return_value=False )
        self.mock_secrets = p2.start(); self.addCleanup( p2.stop )

    def _call( self, path, download=False ):
        return asyncio.run( get_io_file( path=path, download=download, current_user=self.user ) )

    # ---- path normalization + text serving ----------------------------------

    def test_absolute_io_base_prefix_stripped_text_file( self ):
        """Ensures: an absolute /proj/io/ prefix is stripped; .md → PlainTextResponse."""
        with patch( "cosa.rest.routers.io_files.os.path.isdir", return_value=False ), \
             patch( "cosa.rest.routers.io_files.os.path.isfile", return_value=True ), \
             patch( "cosa.rest.routers.io_files.PlainTextResponse" ) as mock_ptr, \
             patch( "builtins.open", mock_open( read_data="hello world" ) ):
            mock_ptr.return_value = "PTR"
            result = self._call( "/proj/io/report.md" )

        self.assertEqual( result, "PTR" )
        mock_ptr.assert_called_once_with(
            content="hello world", media_type=MEDIA_TYPES[ ".md" ]
        )

    def test_leading_slash_stripped( self ):
        """Ensures: a non-io_base leading slash is stripped before join."""
        with patch( "cosa.rest.routers.io_files.os.path.isdir", return_value=False ), \
             patch( "cosa.rest.routers.io_files.os.path.isfile", return_value=True ), \
             patch( "cosa.rest.routers.io_files.PlainTextResponse", return_value="PTR" ), \
             patch( "builtins.open", mock_open( read_data="x" ) ) as m_open:
            self._call( "/report.txt" )
        # opened the io-relative resolved path (leading slash stripped)
        m_open.assert_called_once_with( "/proj/io/report.txt", "r", encoding="utf-8" )

    def test_relative_io_prefix_stripped( self ):
        """Ensures: a relative 'io/' prefix is stripped to avoid io/io doubling."""
        with patch( "cosa.rest.routers.io_files.os.path.isdir", return_value=False ), \
             patch( "cosa.rest.routers.io_files.os.path.isfile", return_value=True ), \
             patch( "cosa.rest.routers.io_files.PlainTextResponse", return_value="PTR" ), \
             patch( "builtins.open", mock_open( read_data="x" ) ) as m_open:
            self._call( "io/sub/report.json" )
        m_open.assert_called_once_with( "/proj/io/sub/report.json", "r", encoding="utf-8" )

    # ---- security blocks -----------------------------------------------------

    def test_traversal_outside_io_raises_400( self ):
        """Ensures: a path normalizing outside io/ raises 400."""
        with self.assertRaises( HTTPException ) as ctx:
            self._call( "../etc/passwd" )
        self.assertEqual( ctx.exception.status_code, 400 )
        self.assertIn( "within io/", ctx.exception.detail )

    def test_secrets_blocklist_raises_400( self ):
        """Ensures: a secrets-blocklisted path raises 400 after the traversal check."""
        self.mock_secrets.return_value = True
        with self.assertRaises( HTTPException ) as ctx:
            self._call( "config.json" )
        self.assertEqual( ctx.exception.status_code, 400 )
        self.assertIn( "secrets blocklist", ctx.exception.detail )

    # ---- directory branch ----------------------------------------------------

    def test_directory_root_returns_json_listing( self ):
        """Ensures: io-root directory → list_directory(rel_dir='') → JSONResponse."""
        def fake_list( **kw ):
            # exercise the inline parent_validator lambda
            kw[ "parent_validator" ]( "x" )
            return { "kind": "directory", "entries": [] }

        with patch( "cosa.rest.routers.io_files.os.path.isdir", return_value=True ), \
             patch( "cosa.rest.routers.io_files.list_directory", side_effect=fake_list ) as m_list, \
             patch( "cosa.rest.routers.io_files.JSONResponse" ) as m_json:
            m_json.return_value = "JSON"
            result = self._call( "" )

        self.assertEqual( result, "JSON" )
        # at io root, rel_dir is "" and scope is "io"
        _, kwargs = m_list.call_args
        self.assertEqual( kwargs[ "rel_dir" ], "" )
        self.assertEqual( kwargs[ "scope" ], "io" )

    def test_directory_nested_relpath( self ):
        """Ensures: a nested directory passes its io-relative path to list_directory."""
        with patch( "cosa.rest.routers.io_files.os.path.isdir", return_value=True ), \
             patch( "cosa.rest.routers.io_files.list_directory", return_value={} ) as m_list, \
             patch( "cosa.rest.routers.io_files.JSONResponse", return_value="JSON" ):
            self._call( "podcasts/episode1" )
        _, kwargs = m_list.call_args
        self.assertEqual( kwargs[ "rel_dir" ], "podcasts/episode1" )

    # ---- not-found / unsupported --------------------------------------------

    def test_missing_file_raises_404( self ):
        """Ensures: a non-directory, non-file path raises 404."""
        with patch( "cosa.rest.routers.io_files.os.path.isdir", return_value=False ), \
             patch( "cosa.rest.routers.io_files.os.path.isfile", return_value=False ):
            with self.assertRaises( HTTPException ) as ctx:
                self._call( "ghost.md" )
        self.assertEqual( ctx.exception.status_code, 404 )

    def test_unsupported_extension_raises_400( self ):
        """Ensures: an extension absent from MEDIA_TYPES raises 400."""
        with patch( "cosa.rest.routers.io_files.os.path.isdir", return_value=False ), \
             patch( "cosa.rest.routers.io_files.os.path.isfile", return_value=True ):
            with self.assertRaises( HTTPException ) as ctx:
                self._call( "weird.xyz" )
        self.assertEqual( ctx.exception.status_code, 400 )
        self.assertIn( "Unsupported file type", ctx.exception.detail )

    # ---- forced download -----------------------------------------------------

    def test_download_forces_attachment( self ):
        """Ensures: download=True returns a FileResponse with attachment disposition."""
        with patch( "cosa.rest.routers.io_files.os.path.isdir", return_value=False ), \
             patch( "cosa.rest.routers.io_files.os.path.isfile", return_value=True ), \
             patch( "cosa.rest.routers.io_files.FileResponse" ) as m_fr:
            m_fr.return_value = "FR"
            result = self._call( "deck.pptx", download=True )

        self.assertEqual( result, "FR" )
        _, kwargs = m_fr.call_args
        self.assertEqual( kwargs[ "content_disposition_type" ], "attachment" )
        self.assertEqual( kwargs[ "filename" ], "deck.pptx" )

    def test_download_error_raises_500( self ):
        """Ensures: a FileResponse failure during download maps to 500."""
        with patch( "cosa.rest.routers.io_files.os.path.isdir", return_value=False ), \
             patch( "cosa.rest.routers.io_files.os.path.isfile", return_value=True ), \
             patch( "cosa.rest.routers.io_files.FileResponse", side_effect=Exception( "boom" ) ):
            with self.assertRaises( HTTPException ) as ctx:
                self._call( "deck.pptx", download=True )
        self.assertEqual( ctx.exception.status_code, 500 )

    # ---- text read error -----------------------------------------------------

    def test_text_read_error_raises_500( self ):
        """Ensures: a read failure on a text file maps to 500."""
        with patch( "cosa.rest.routers.io_files.os.path.isdir", return_value=False ), \
             patch( "cosa.rest.routers.io_files.os.path.isfile", return_value=True ), \
             patch( "builtins.open", side_effect=OSError( "disk" ) ):
            with self.assertRaises( HTTPException ) as ctx:
                self._call( "report.md" )
        self.assertEqual( ctx.exception.status_code, 500 )

    # ---- binary serving ------------------------------------------------------

    def test_binary_inline_disposition_for_mp3( self ):
        """Ensures: an inline-renderable binary (.mp3) gets disposition inline."""
        with patch( "cosa.rest.routers.io_files.os.path.isdir", return_value=False ), \
             patch( "cosa.rest.routers.io_files.os.path.isfile", return_value=True ), \
             patch( "cosa.rest.routers.io_files.FileResponse" ) as m_fr:
            m_fr.return_value = "FR"
            result = self._call( "song.mp3" )
        self.assertEqual( result, "FR" )
        _, kwargs = m_fr.call_args
        self.assertEqual( kwargs[ "content_disposition_type" ], "inline" )

    def test_binary_attachment_disposition_for_pptx( self ):
        """Ensures: a non-inline binary (.pptx) defaults to attachment disposition."""
        with patch( "cosa.rest.routers.io_files.os.path.isdir", return_value=False ), \
             patch( "cosa.rest.routers.io_files.os.path.isfile", return_value=True ), \
             patch( "cosa.rest.routers.io_files.FileResponse" ) as m_fr:
            m_fr.return_value = "FR"
            self._call( "deck.pptx" )
        _, kwargs = m_fr.call_args
        self.assertEqual( kwargs[ "content_disposition_type" ], "attachment" )

    def test_binary_serve_error_raises_500( self ):
        """Ensures: a FileResponse failure while serving a binary maps to 500."""
        with patch( "cosa.rest.routers.io_files.os.path.isdir", return_value=False ), \
             patch( "cosa.rest.routers.io_files.os.path.isfile", return_value=True ), \
             patch( "cosa.rest.routers.io_files.FileResponse", side_effect=Exception( "boom" ) ):
            with self.assertRaises( HTTPException ) as ctx:
                self._call( "song.mp3" )
        self.assertEqual( ctx.exception.status_code, 500 )


class TestIoFilesHealth( unittest.TestCase ):
    """
    Unit tests for `io_files_health`.

    Ensures:
        - io present → counts files in existing subdirs, skips missing ones
        - io absent → empty subdirs map
    """

    def test_health_io_present_counts_subdirs( self ):
        """Ensures: existing subdir files are counted; missing subdir skipped."""
        def fake_isdir( path ):
            return path in ( "/proj/io", "/proj/io/deep-research" )  # podcasts missing

        with patch( "cosa.rest.routers.io_files.cu.get_project_root", return_value="/proj" ), \
             patch( "cosa.rest.routers.io_files.os.path.isdir", side_effect=fake_isdir ), \
             patch( "cosa.rest.routers.io_files.os.walk",
                    return_value=[ ( "/proj/io/deep-research", [], [ "a.md", "b.md" ] ) ] ):
            result = asyncio.run( io_files_health() )

        self.assertEqual( result[ "status" ], "ok" )
        self.assertTrue( result[ "io_exists" ] )
        self.assertEqual( result[ "subdirs" ], { "deep-research": 2 } )
        self.assertEqual( result[ "media_types" ], list( MEDIA_TYPES.keys() ) )

    def test_health_io_absent_empty_subdirs( self ):
        """Ensures: a missing io/ dir yields io_exists False + empty subdirs."""
        with patch( "cosa.rest.routers.io_files.cu.get_project_root", return_value="/proj" ), \
             patch( "cosa.rest.routers.io_files.os.path.isdir", return_value=False ):
            result = asyncio.run( io_files_health() )

        self.assertFalse( result[ "io_exists" ] )
        self.assertEqual( result[ "subdirs" ], {} )


class TestIoFilesRouterRegistration( unittest.TestCase ):
    """
    Ensures:
        - The file + health routes are registered
    """

    def test_routes_registered( self ):
        """Ensures: /api/io/file + /api/io/health are present."""
        paths = { route.path for route in router.routes }
        self.assertIn( "/api/io/file", paths )
        self.assertIn( "/api/io/health", paths )


def isolated_unit_test():
    """
    Run the io-files router unit tests in isolation.

    Ensures:
        - Executes all TestCases and reports (success, duration, message)
    """
    import cosa.utils.util as du

    start_time = time.time()
    try:
        loader = unittest.TestLoader()
        suite  = unittest.TestSuite()
        for tc in (
            TestGetIoFile, TestIoFilesHealth, TestIoFilesRouterRegistration,
        ):
            suite.addTests( loader.loadTestsFromTestCase( tc ) )
        result = unittest.TextTestRunner( verbosity=2 ).run( suite )

        duration  = time.time() - start_time
        tests_run = result.testsRun
        failures  = len( result.failures )
        errors    = len( result.errors )

        success = failures == 0 and errors == 0
        if success:
            du.print_banner( "✅ ALL IO-FILES ROUTER TESTS PASSED", prepend_nl=True )
            message = f"All {tests_run} tests passed successfully in {duration:.3f}s"
        else:
            du.print_banner( "❌ SOME IO-FILES ROUTER TESTS FAILED", prepend_nl=True )
            message = f"{failures} failures, {errors} errors out of {tests_run} tests"

        return success, duration, message

    except Exception as e:
        duration  = time.time() - start_time
        error_msg = f"Unit test execution failed: {str(e)}"
        du.print_banner( f"💥 IO-FILES ROUTER TEST ERROR: {error_msg}", prepend_nl=True )
        return False, duration, error_msg


if __name__ == "__main__":
    success, duration, message = isolated_unit_test()
    status = "✅ PASS" if success else "❌ FAIL"
    print( f"\n{status} IO-files router unit tests completed in {duration:.3f}s" )
    print( f"Result: {message}" )
