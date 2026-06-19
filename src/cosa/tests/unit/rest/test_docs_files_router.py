"""
Unit tests for the docs-files router (`cosa.rest.routers.docs_files`).

Covers:
- `_get_scope_registry` lazy-build + cache; `_invalidate_scope_registry` reset.
- `get_docs_file` — retired-`?scope=` 400 (+ registry-read failure fallback),
  empty path, secrets floor, missing/empty project prefix, unknown project,
  whitelist rejection, per-scope extra-blocklist, traversal ValueError → 400,
  and the success dispatch to `_serve`.
- `get_scopes` — manifest vs ini-only payload shaping.
- `_serve` — directory listing, 404, unsupported extension, image FileResponse,
  text PlainTextResponse, read-error 500.
- `docs_files_health` — manifest + ini-only scope status.

NOTE (pragma PROPOSE, not applied): the `if not project_name:` guard at
docs_files.py:218-222 is UNREACHABLE — `decoded_path = unquote(path).lstrip("/")`
plus the non-empty + contains-"/" guards above it mean the pre-slash segment is
always non-empty. Proposed `# pragma: no cover  # unreachable: lstrip('/') guarantees
non-empty project segment`. Reported to manager at the cluster boundary.

Zero external dependencies — ConfigurationManager, build_scope_registry, the
scope-registry helpers, the filesystem, and the FastAPI response classes are all
boundary-mocked. Auth bypassed by passing current_user explicitly.
"""

import unittest
from unittest.mock import patch, MagicMock, mock_open
from types import SimpleNamespace
import asyncio
import time

from fastapi import HTTPException

import cosa.rest.routers.docs_files as docs_files
from cosa.rest.routers.docs_files import (
    _get_scope_registry,
    _invalidate_scope_registry,
    get_docs_file,
    get_scopes,
    _serve,
    docs_files_health,
    MEDIA_TYPES,
)
from cosa.rest.routers._scope_registry import ScopeConfig


def _ini_cfg( name="proj", root="/repo", prefixes=( "src/", ) ):
    """An ini-only ScopeConfig (no manifest)."""
    return ScopeConfig( name=name, root=root, allowed_prefixes=prefixes )


def _manifest_cfg( name="proj", root="/repo", extra=() ):
    """A manifest-backed ScopeConfig."""
    man = SimpleNamespace(
        allowed_prefixes   = [ "src/" ],
        allowed_root_files = [ "README.md" ],
        extra_blocklist    = [ "sekret" ],
    )
    return ScopeConfig(
        name=name, root=root, allowed_prefixes=(), manifest=man, extra_blocklist_patterns=extra
    )


class TestScopeRegistryCache( unittest.TestCase ):
    """
    Unit tests for the lazy registry cache + invalidator.

    Ensures:
        - first access builds once via build_scope_registry; second is cached
        - _invalidate_scope_registry drops the cache
    """

    def setUp( self ):
        """Ensures: snapshot the module global to restore after each test."""
        self._saved = docs_files._SCOPE_REGISTRY
        self.addCleanup( setattr, docs_files, "_SCOPE_REGISTRY", self._saved )

    def test_lazy_build_then_cached( self ):
        """Ensures: registry built exactly once, then served from cache."""
        docs_files._SCOPE_REGISTRY = None
        with patch( "cosa.rest.routers.docs_files.ConfigurationManager" ) as MC, \
             patch( "cosa.rest.routers.docs_files.build_scope_registry",
                    return_value={ "x": "cfg" } ) as mb:
            r1 = _get_scope_registry()
            r2 = _get_scope_registry()
        self.assertEqual( r1, { "x": "cfg" } )
        self.assertIs( r1, r2 )
        mb.assert_called_once()
        MC.assert_called_once()

    def test_invalidate_resets_cache( self ):
        """Ensures: invalidation sets the global back to the None sentinel."""
        docs_files._SCOPE_REGISTRY = { "stale": 1 }
        _invalidate_scope_registry()
        self.assertIsNone( docs_files._SCOPE_REGISTRY )


class TestGetDocsFile( unittest.TestCase ):
    """
    Unit tests for `get_docs_file` across all validation + dispatch branches.

    Requires:
        - _get_scope_registry + scope helpers + _serve boundary-mocked

    Ensures:
        - retired ?scope=, empty path, secrets, prefix, unknown project, whitelist,
          per-scope blocklist, traversal, and success dispatch are all exercised
    """

    def _call( self, path, scope=None ):
        return asyncio.run( get_docs_file( path=path, scope=scope, current_user={ "uid": "u" } ) )

    # ---- retired ?scope= -----------------------------------------------------

    def test_retired_scope_param_400_lists_projects( self ):
        """Ensures: presence of ?scope= raises 400 and lists registered projects."""
        with patch( "cosa.rest.routers.docs_files._get_scope_registry",
                    return_value={ "lupin": _ini_cfg() } ):
            with self.assertRaises( HTTPException ) as ctx:
                self._call( "lupin/x.md", scope="docs" )
        self.assertEqual( ctx.exception.status_code, 400 )
        self.assertIn( "RETIRED", ctx.exception.detail )
        self.assertIn( "lupin", ctx.exception.detail )

    def test_retired_scope_param_registry_failure_fallback( self ):
        """Ensures: a registry-read failure falls back to the generic pointer."""
        with patch( "cosa.rest.routers.docs_files._get_scope_registry",
                    side_effect=Exception( "boom" ) ):
            with self.assertRaises( HTTPException ) as ctx:
                self._call( "lupin/x.md", scope="docs" )
        self.assertEqual( ctx.exception.status_code, 400 )
        self.assertIn( "GET /api/docs/scopes", ctx.exception.detail )

    # ---- path validation -----------------------------------------------------

    def test_empty_path_400( self ):
        """Ensures: an empty (slash-only) path raises 400 'Empty path'."""
        with self.assertRaises( HTTPException ) as ctx:
            self._call( "/" )
        self.assertEqual( ctx.exception.status_code, 400 )
        self.assertEqual( ctx.exception.detail, "Empty path" )

    def test_secrets_floor_400( self ):
        """Ensures: a secrets-blocklisted path is rejected before project lookup."""
        with patch( "cosa.rest.routers.docs_files._is_secrets_path", return_value=True ):
            with self.assertRaises( HTTPException ) as ctx:
                self._call( "lupin/credentials.json" )
        self.assertEqual( ctx.exception.status_code, 400 )
        self.assertIn( "secrets blocklist", ctx.exception.detail )

    def test_missing_project_prefix_400( self ):
        """Ensures: a path with no '/' raises the missing-prefix 400."""
        with patch( "cosa.rest.routers.docs_files._is_secrets_path", return_value=False ):
            with self.assertRaises( HTTPException ) as ctx:
                self._call( "justafile.md" )
        self.assertEqual( ctx.exception.status_code, 400 )
        self.assertIn( "Missing project prefix", ctx.exception.detail )

    def test_unknown_project_400( self ):
        """Ensures: an unregistered project name raises 400."""
        with patch( "cosa.rest.routers.docs_files._is_secrets_path", return_value=False ), \
             patch( "cosa.rest.routers.docs_files._get_scope_registry", return_value={} ):
            with self.assertRaises( HTTPException ) as ctx:
                self._call( "ghost/x.md" )
        self.assertEqual( ctx.exception.status_code, 400 )
        self.assertIn( "Unknown project", ctx.exception.detail )

    def test_whitelist_rejection_400( self ):
        """Ensures: a path failing the scope whitelist raises 400."""
        with patch( "cosa.rest.routers.docs_files._is_secrets_path", return_value=False ), \
             patch( "cosa.rest.routers.docs_files._get_scope_registry",
                    return_value={ "proj": _ini_cfg() } ), \
             patch( "cosa.rest.routers.docs_files._is_whitelisted_in_scope", return_value=False ):
            with self.assertRaises( HTTPException ) as ctx:
                self._call( "proj/secret/area.md" )
        self.assertEqual( ctx.exception.status_code, 400 )
        self.assertIn( "not in scope whitelist", ctx.exception.detail )

    def test_per_scope_extra_blocklist_400( self ):
        """Ensures: a per-scope extra-blocklist match raises 400."""
        cfg = ScopeConfig(
            name="proj", root="/repo", allowed_prefixes=(),
            extra_blocklist_patterns=( __import__( "re" ).compile( "sekret" ), ),
        )
        with patch( "cosa.rest.routers.docs_files._is_secrets_path", return_value=False ), \
             patch( "cosa.rest.routers.docs_files._get_scope_registry", return_value={ "proj": cfg } ), \
             patch( "cosa.rest.routers.docs_files._is_whitelisted_in_scope", return_value=True ), \
             patch( "cosa.rest.routers._scope_registry._is_secrets_path_for_scope", return_value=True ):
            with self.assertRaises( HTTPException ) as ctx:
                self._call( "proj/src/sekret.md" )
        self.assertEqual( ctx.exception.status_code, 400 )
        self.assertIn( "per-scope", ctx.exception.detail )

    def test_per_scope_extra_blocklist_passes_through( self ):
        """
        Ensures:
            - When extra_blocklist_patterns is set but the path does NOT match,
              resolution proceeds (covers the False arm of the per-scope check)
        """
        import re
        cfg = ScopeConfig(
            name="proj", root="/repo", allowed_prefixes=(),
            extra_blocklist_patterns=( re.compile( "sekret" ), ),
        )
        with patch( "cosa.rest.routers.docs_files._is_secrets_path", return_value=False ), \
             patch( "cosa.rest.routers.docs_files._get_scope_registry", return_value={ "proj": cfg } ), \
             patch( "cosa.rest.routers.docs_files._is_whitelisted_in_scope", return_value=True ), \
             patch( "cosa.rest.routers._scope_registry._is_secrets_path_for_scope", return_value=False ), \
             patch( "cosa.rest.routers.docs_files.resolve_in_scope", return_value="/repo/src/a.md" ), \
             patch( "cosa.rest.routers.docs_files._serve", return_value="OK" ):
            result = self._call( "proj/src/a.md" )
        self.assertEqual( result, "OK" )

    def test_traversal_value_error_400( self ):
        """Ensures: resolve_in_scope ValueError maps to 400."""
        with patch( "cosa.rest.routers.docs_files._is_secrets_path", return_value=False ), \
             patch( "cosa.rest.routers.docs_files._get_scope_registry",
                    return_value={ "proj": _ini_cfg() } ), \
             patch( "cosa.rest.routers.docs_files._is_whitelisted_in_scope", return_value=True ), \
             patch( "cosa.rest.routers.docs_files.resolve_in_scope",
                    side_effect=ValueError( "escape" ) ):
            with self.assertRaises( HTTPException ) as ctx:
                self._call( "proj/../etc.md" )
        self.assertEqual( ctx.exception.status_code, 400 )
        self.assertEqual( ctx.exception.detail, "escape" )

    def test_success_dispatches_to_serve_and_binds_validator( self ):
        """
        Ensures:
            - On success the resolved path is dispatched to _serve, and the
              bound parent_validator lambda delegates to _is_whitelisted_in_scope
        """
        captured = {}

        def fake_serve( full_path, rel_path, scope, parent_validator ):
            captured[ "scope" ]    = scope
            captured[ "rel" ]      = rel_path
            captured[ "full" ]     = full_path
            captured[ "pv_call" ]  = parent_validator( "src" )   # exercise the lambda
            return "SERVED"

        with patch( "cosa.rest.routers.docs_files._is_secrets_path", return_value=False ), \
             patch( "cosa.rest.routers.docs_files._get_scope_registry",
                    return_value={ "proj": _ini_cfg() } ), \
             patch( "cosa.rest.routers.docs_files._is_whitelisted_in_scope", return_value=True ) as m_wl, \
             patch( "cosa.rest.routers.docs_files.resolve_in_scope", return_value="/repo/src/a.md" ), \
             patch( "cosa.rest.routers.docs_files._serve", side_effect=fake_serve ):
            result = self._call( "proj/src/a.md" )

        self.assertEqual( result, "SERVED" )
        self.assertEqual( captured[ "scope" ], "proj" )
        self.assertEqual( captured[ "rel" ], "src/a.md" )
        self.assertEqual( captured[ "full" ], "/repo/src/a.md" )
        self.assertTrue( captured[ "pv_call" ] )           # lambda returned the mock's True
        self.assertTrue( m_wl.called )


class TestGetScopes( unittest.TestCase ):
    """
    Unit tests for `get_scopes`.

    Ensures:
        - manifest scopes emit manifest-sourced fields; ini-only scopes emit fallback
    """

    def test_manifest_and_ini_only_payloads( self ):
        """Ensures: both payload shapes (manifest + ini-only) are produced + sorted."""
        registry = { "zeta": _ini_cfg( name="zeta" ), "alpha": _manifest_cfg( name="alpha" ) }
        with patch( "cosa.rest.routers.docs_files._get_scope_registry", return_value=registry ), \
             patch( "cosa.rest.routers.docs_files.JSONResponse", side_effect=lambda content: content ):
            payload = asyncio.run( get_scopes( current_user={ "uid": "u" } ) )

        scopes = { s[ "name" ]: s for s in payload[ "scopes" ] }
        self.assertEqual( scopes[ "alpha" ][ "source" ], "manifest" )
        self.assertEqual( scopes[ "alpha" ][ "allowed_root_files" ], [ "README.md" ] )
        self.assertEqual( scopes[ "alpha" ][ "extra_blocklist" ], [ "sekret" ] )
        self.assertEqual( scopes[ "zeta" ][ "source" ], "ini-only" )
        self.assertEqual( scopes[ "zeta" ][ "allowed_root_files" ], [] )
        # sorted alphabetically → alpha first
        self.assertEqual( payload[ "scopes" ][ 0 ][ "name" ], "alpha" )


class TestServe( unittest.TestCase ):
    """
    Unit tests for the `_serve` dispatch helper.

    Ensures:
        - directory → JSONResponse; missing → 404; bad ext → 400
        - image media type → FileResponse; text → PlainTextResponse; read error → 500
    """

    def _serve( self, full="/repo/src/a.md", rel="src/a.md" ):
        return _serve( full, rel, scope="proj", parent_validator=lambda p: True )

    def test_directory_returns_json( self ):
        """Ensures: a directory path returns a JSONResponse listing."""
        with patch( "cosa.rest.routers.docs_files.os.path.isdir", return_value=True ), \
             patch( "cosa.rest.routers.docs_files.list_directory", return_value={ "k": "dir" } ), \
             patch( "cosa.rest.routers.docs_files.JSONResponse", side_effect=lambda content: content ):
            result = self._serve( full="/repo/src" )
        self.assertEqual( result, { "k": "dir" } )

    def test_missing_path_404( self ):
        """Ensures: a non-dir, non-file path raises 404."""
        with patch( "cosa.rest.routers.docs_files.os.path.isdir", return_value=False ), \
             patch( "cosa.rest.routers.docs_files.os.path.isfile", return_value=False ):
            with self.assertRaises( HTTPException ) as ctx:
                self._serve()
        self.assertEqual( ctx.exception.status_code, 404 )

    def test_unsupported_extension_400( self ):
        """Ensures: an extension absent from MEDIA_TYPES raises 400."""
        with patch( "cosa.rest.routers.docs_files.os.path.isdir", return_value=False ), \
             patch( "cosa.rest.routers.docs_files.os.path.isfile", return_value=True ):
            with self.assertRaises( HTTPException ) as ctx:
                self._serve( full="/repo/src/a.exe", rel="src/a.exe" )
        self.assertEqual( ctx.exception.status_code, 400 )
        self.assertIn( "Unsupported file type", ctx.exception.detail )

    def test_image_returns_file_response( self ):
        """Ensures: an image/* media type is served via FileResponse (no decode)."""
        with patch( "cosa.rest.routers.docs_files.os.path.isdir", return_value=False ), \
             patch( "cosa.rest.routers.docs_files.os.path.isfile", return_value=True ), \
             patch( "cosa.rest.routers.docs_files.FileResponse" ) as m_fr:
            m_fr.return_value = "FR"
            result = self._serve( full="/repo/img/x.png", rel="img/x.png" )
        self.assertEqual( result, "FR" )
        m_fr.assert_called_once_with( path="/repo/img/x.png", media_type=MEDIA_TYPES[ ".png" ] )

    def test_text_returns_plain_text_response( self ):
        """Ensures: a text file is read utf-8 and returned via PlainTextResponse."""
        with patch( "cosa.rest.routers.docs_files.os.path.isdir", return_value=False ), \
             patch( "cosa.rest.routers.docs_files.os.path.isfile", return_value=True ), \
             patch( "cosa.rest.routers.docs_files.PlainTextResponse",
                    side_effect=lambda content, media_type: ( content, media_type ) ), \
             patch( "builtins.open", mock_open( read_data="# Title" ) ):
            content, media_type = self._serve()
        self.assertEqual( content, "# Title" )
        self.assertEqual( media_type, MEDIA_TYPES[ ".md" ] )

    def test_text_read_error_500( self ):
        """Ensures: a read failure on a text file maps to 500."""
        with patch( "cosa.rest.routers.docs_files.os.path.isdir", return_value=False ), \
             patch( "cosa.rest.routers.docs_files.os.path.isfile", return_value=True ), \
             patch( "builtins.open", side_effect=OSError( "disk" ) ):
            with self.assertRaises( HTTPException ) as ctx:
                self._serve()
        self.assertEqual( ctx.exception.status_code, 500 )


class TestDocsFilesHealth( unittest.TestCase ):
    """
    Unit tests for `docs_files_health`.

    Ensures:
        - per-scope status reports manifest vs ini-only allowed_prefixes + existence
        - io/ root presence is reported
    """

    def test_health_reports_scope_status( self ):
        """Ensures: manifest + ini-only scopes both surface in the status map."""
        registry = { "m": _manifest_cfg( name="m", root="/m" ), "i": _ini_cfg( name="i", root="/i" ) }
        with patch( "cosa.rest.routers.docs_files.cu.get_project_root", return_value="/proj" ), \
             patch( "cosa.rest.routers.docs_files._get_scope_registry", return_value=registry ), \
             patch( "cosa.rest.routers.docs_files.os.path.isdir", return_value=True ):
            result = asyncio.run( docs_files_health() )

        self.assertEqual( result[ "status" ], "ok" )
        self.assertEqual( result[ "project_root" ], "/proj" )
        self.assertTrue( result[ "io" ][ "exists" ] )
        self.assertTrue( result[ "scopes" ][ "m" ][ "manifest" ] )
        self.assertEqual( result[ "scopes" ][ "m" ][ "allowed_prefixes" ], [ "src/" ] )   # manifest's
        self.assertFalse( result[ "scopes" ][ "i" ][ "manifest" ] )
        self.assertEqual( result[ "scopes" ][ "i" ][ "allowed_prefixes" ], [ "src/" ] )   # ini fallback


def isolated_unit_test():
    """
    Run the docs-files router unit tests in isolation.

    Ensures:
        - Executes all TestCases and reports (success, duration, message)
    """
    import cosa.utils.util as du

    start_time = time.time()
    try:
        loader = unittest.TestLoader()
        suite  = unittest.TestSuite()
        for tc in (
            TestScopeRegistryCache, TestGetDocsFile, TestGetScopes,
            TestServe, TestDocsFilesHealth,
        ):
            suite.addTests( loader.loadTestsFromTestCase( tc ) )
        result = unittest.TextTestRunner( verbosity=2 ).run( suite )

        duration  = time.time() - start_time
        tests_run = result.testsRun
        failures  = len( result.failures )
        errors    = len( result.errors )

        success = failures == 0 and errors == 0
        if success:
            du.print_banner( "✅ ALL DOCS-FILES ROUTER TESTS PASSED", prepend_nl=True )
            message = f"All {tests_run} tests passed successfully in {duration:.3f}s"
        else:
            du.print_banner( "❌ SOME DOCS-FILES ROUTER TESTS FAILED", prepend_nl=True )
            message = f"{failures} failures, {errors} errors out of {tests_run} tests"

        return success, duration, message

    except Exception as e:
        duration  = time.time() - start_time
        error_msg = f"Unit test execution failed: {str(e)}"
        du.print_banner( f"💥 DOCS-FILES ROUTER TEST ERROR: {error_msg}", prepend_nl=True )
        return False, duration, error_msg


if __name__ == "__main__":
    success, duration, message = isolated_unit_test()
    status = "✅ PASS" if success else "❌ FAIL"
    print( f"\n{status} Docs-files router unit tests completed in {duration:.3f}s" )
    print( f"Result: {message}" )
