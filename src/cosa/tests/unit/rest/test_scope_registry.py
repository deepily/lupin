"""
Unit tests for the multi-repo doc-viewer scope registry
(`cosa.rest.routers._scope_registry`).

Covers:
- `_is_secrets_path` — universal secrets/dev-artifact blocklist (segment-wise),
  including the empty-input guard and empty-segment skip.
- `_is_whitelisted_in_scope` — manifest-authoritative + INI-fallback whitelist
  resolution (root-file exact match, prefix startswith, bare-prefix equality,
  wildcard-on-empty).
- `_is_secrets_path_for_scope` — floor-first then per-scope extra blocklist.
- `resolve_in_scope` — path resolution + directory-traversal block.
- `build_scope_registry` — INI-driven registry build across every skip/keep arm
  (blank name, reserved-name collision, missing/absent path, path/prefix config
  exceptions, manifest present/absent, extra-blocklist compilation).

Zero external dependencies — config_mgr, os.path.isdir, and load_manifest_for_scope
are boundary-mocked; no real filesystem or INI read.
"""

import unittest
from unittest.mock import patch, MagicMock
from types import SimpleNamespace
import re
import time

from cosa.rest.routers._scope_registry import (
    ScopeConfig,
    _is_secrets_path,
    _is_whitelisted_in_scope,
    _is_secrets_path_for_scope,
    resolve_in_scope,
    build_scope_registry,
)


class TestIsSecretsPath( unittest.TestCase ):
    """
    Unit tests for `_is_secrets_path`.

    Ensures:
        - empty input is a cheap False
        - blocklisted segments (creds, keys, dev artifacts) match anywhere in path
        - legitimate look-alike names do NOT false-positive
        - empty path segments are skipped
    """

    def test_empty_input_returns_false( self ):
        """Ensures: empty string short-circuits to False."""
        self.assertFalse( _is_secrets_path( "" ) )

    def test_empty_segments_skipped_and_no_match( self ):
        """Ensures: doubled separators yield empty segments that are skipped."""
        self.assertFalse( _is_secrets_path( "a//b/c.md" ) )

    def test_blocklisted_paths_match( self ):
        """Ensures: known secret-bearing names are blocked (incl. nested)."""
        for p in [
            ".env", ".env.production", "credentials.json", "secrets.yaml",
            "id_rsa", "id_ed25519", "sub/dir/credentials.json", ".netrc",
            ".pgpass", "deploy.pem", "tls.key", "CLAUDE.local.md",
        ]:
            self.assertTrue( _is_secrets_path( p ), f"should block {p!r}" )

    def test_legitimate_names_not_blocked( self ):
        """Ensures: word-boundary anchoring avoids false positives."""
        for p in [
            "environment.md", "environments.py", "pem-helper.py",
            "key_values.txt", "secretive_methods.py", "credentialism.txt",
            "src/rnd/foo.md",
        ]:
            self.assertFalse( _is_secrets_path( p ), f"should allow {p!r}" )


class TestIsWhitelistedInScope( unittest.TestCase ):
    """
    Unit tests for `_is_whitelisted_in_scope`.

    Ensures:
        - empty relative_path is always allowed (root-listing affordance)
        - manifest authority: root-file exact match, prefix startswith, bare equality
        - INI fallback: wildcard on empty prefixes, else prefix matching
    """

    def test_empty_path_allowed( self ):
        """Ensures: '' returns True regardless of scope config."""
        cfg = ScopeConfig( name="s", root="/r", allowed_prefixes=( "src/", ) )
        self.assertTrue( _is_whitelisted_in_scope( cfg, "" ) )

    def test_manifest_root_file_exact_match( self ):
        """Ensures: a top-level file in allowed_root_files is permitted."""
        man = SimpleNamespace( allowed_root_files={ "README.md" }, allowed_prefixes=[ "src/" ] )
        cfg = ScopeConfig( name="s", root="/r", allowed_prefixes=(), manifest=man )
        self.assertTrue( _is_whitelisted_in_scope( cfg, "README.md" ) )

    def test_manifest_prefix_startswith_and_bare_equality( self ):
        """Ensures: manifest prefix startswith + bare-prefix equality both pass."""
        # "docs/" trailing slash forces the equality arm for path "docs"
        # (startswith("docs/") fails → falls through to == prefix.rstrip("/")).
        man = SimpleNamespace( allowed_root_files=set(), allowed_prefixes=[ "src/", "docs/" ] )
        cfg = ScopeConfig( name="s", root="/r", allowed_prefixes=(), manifest=man )
        self.assertTrue( _is_whitelisted_in_scope( cfg, "src/app.py" ) )   # startswith
        self.assertTrue( _is_whitelisted_in_scope( cfg, "docs" ) )         # == prefix.rstrip("/")

    def test_manifest_rejects_unlisted_and_nested_nonroot( self ):
        """Ensures: unlisted paths + nested files (with '/') fail the manifest whitelist."""
        man = SimpleNamespace( allowed_root_files={ "README.md" }, allowed_prefixes=[ "src/" ] )
        cfg = ScopeConfig( name="s", root="/r", allowed_prefixes=(), manifest=man )
        self.assertFalse( _is_whitelisted_in_scope( cfg, "other.md" ) )       # not root file, no prefix
        self.assertFalse( _is_whitelisted_in_scope( cfg, "sub/README.md" ) )  # '/' present → skip root check

    def test_ini_wildcard_on_empty_prefixes( self ):
        """Ensures: no manifest + empty prefixes → wildcard True."""
        cfg = ScopeConfig( name="s", root="/r", allowed_prefixes=() )
        self.assertTrue( _is_whitelisted_in_scope( cfg, "anything/at/all.md" ) )

    def test_ini_prefix_match_and_reject( self ):
        """Ensures: no manifest + prefixes → startswith/equality pass, else reject."""
        # "docs/" trailing slash forces the equality arm for path "docs".
        cfg = ScopeConfig( name="s", root="/r", allowed_prefixes=( "src/", "docs/" ) )
        self.assertTrue( _is_whitelisted_in_scope( cfg, "src/foo.py" ) )   # startswith
        self.assertTrue( _is_whitelisted_in_scope( cfg, "docs" ) )         # bare equality
        self.assertFalse( _is_whitelisted_in_scope( cfg, "lib/foo.py" ) )  # no match
        self.assertFalse( _is_whitelisted_in_scope( cfg, "lib" ) )         # no match


class TestIsSecretsPathForScope( unittest.TestCase ):
    """
    Unit tests for `_is_secrets_path_for_scope`.

    Ensures:
        - floor blocklist matches short-circuit to True
        - no floor match + no extra patterns → False
        - per-scope extra patterns match (or not) when floor passes
    """

    def test_floor_match_short_circuits( self ):
        """Ensures: a floor (universal) match returns True before extras."""
        cfg = ScopeConfig( name="s", root="/r", allowed_prefixes=() )
        self.assertTrue( _is_secrets_path_for_scope( cfg, "secrets.json" ) )

    def test_no_floor_no_extra_false( self ):
        """Ensures: clean path with no extra patterns returns False."""
        cfg = ScopeConfig( name="s", root="/r", allowed_prefixes=() )
        self.assertFalse( _is_secrets_path_for_scope( cfg, "src/app.py" ) )

    def test_extra_pattern_match( self ):
        """Ensures: a per-scope extra pattern blocks a segment the floor allows."""
        cfg = ScopeConfig(
            name="s", root="/r", allowed_prefixes=(),
            extra_blocklist_patterns=( re.compile( "internal" ), ),
        )
        self.assertTrue( _is_secrets_path_for_scope( cfg, "internal/x.py" ) )

    def test_extra_pattern_no_match_skips_empty_segments( self ):
        """Ensures: extras that don't match return False; empty segments skipped."""
        cfg = ScopeConfig(
            name="s", root="/r", allowed_prefixes=(),
            extra_blocklist_patterns=( re.compile( "zzz" ), ),
        )
        self.assertFalse( _is_secrets_path_for_scope( cfg, "src//app.py" ) )


class TestResolveInScope( unittest.TestCase ):
    """
    Unit tests for `resolve_in_scope`.

    Ensures:
        - sub-paths resolve under root
        - empty decoded path resolves to root itself
        - traversal outside root raises ValueError
    """

    def test_resolves_subpath( self ):
        """Ensures: a sub-path joins under the scope root."""
        cfg = ScopeConfig( name="s", root="/root", allowed_prefixes=() )
        self.assertEqual( resolve_in_scope( cfg, "sub/f.md" ), "/root/sub/f.md" )

    def test_empty_path_resolves_to_root( self ):
        """Ensures: '' resolves to the root path itself (== root branch)."""
        cfg = ScopeConfig( name="s", root="/root", allowed_prefixes=() )
        self.assertEqual( resolve_in_scope( cfg, "" ), "/root" )

    def test_traversal_raises_value_error( self ):
        """Ensures: a path escaping root raises ValueError."""
        cfg = ScopeConfig( name="s", root="/root", allowed_prefixes=() )
        with self.assertRaises( ValueError ):
            resolve_in_scope( cfg, "../etc/passwd" )


class TestBuildScopeRegistry( unittest.TestCase ):
    """
    Unit tests for `build_scope_registry`.

    Requires:
        - config_mgr boundary-mocked with per-key responses
        - os.path.isdir + load_manifest_for_scope patched

    Ensures:
        - blank names, reserved-name collisions, missing/absent paths are skipped
        - path/prefix config exceptions are swallowed (skip / empty-prefix fallback)
        - manifest present → extra_blocklist compiled; absent/empty → empty tuple
        - prefixes are whitespace-stripped with empties dropped
    """

    def test_build_covers_all_arms( self ):
        """
        Ensures:
            - One realistic INI drives every keep/skip branch of the build loop
        """
        names = [
            "",             # blank → skip
            "docs",         # reserved → skip
            "ghost",        # path None → skip
            "good",         # kept, no manifest
            "withmanifest", # kept, manifest w/o extra_blocklist
            "withextra",    # kept, manifest w/ extra_blocklist (compiled)
            "prefixerr",    # kept, prefixes get raises → empty prefixes
            "patherr",      # path get raises → skip
        ]
        paths = {
            "ghost"        : None,
            "good"         : "/r/good",
            "withmanifest" : "/r/wm",
            "withextra"    : "/r/we",
            "prefixerr"    : "/r/pe",
        }
        prefixes = {
            "good"         : [ "src/", "", "  ", "docs/" ],   # empties dropped
            "withmanifest" : [ "docs/" ],
            "withextra"    : [],
        }

        def cfg_get( key, default=None, return_type=None, silent=False ):
            if key == "external repos":
                return names
            parts = key.split()
            name  = parts[ 2 ]
            if key.endswith( "path" ):
                if name == "patherr":
                    raise RuntimeError( "boom-path" )
                return paths.get( name )
            if key.endswith( "prefixes" ):
                if name == "prefixerr":
                    raise RuntimeError( "boom-prefix" )
                return prefixes.get( name, [] )
            return default

        config_mgr = MagicMock()
        config_mgr.get.side_effect = cfg_get

        manifests = {
            "/r/good" : None,
            "/r/wm"   : SimpleNamespace( extra_blocklist=None ),
            "/r/we"   : SimpleNamespace( extra_blocklist=[ "topsecret" ] ),
            "/r/pe"   : None,
        }

        with patch( "cosa.rest.routers._scope_registry.os.path.isdir", return_value=True ), \
             patch( "cosa.rest.routers._scope_registry.load_manifest_for_scope",
                    side_effect=lambda root: manifests[ root ] ):
            registry = build_scope_registry( config_mgr )

        self.assertEqual( set( registry.keys() ), { "good", "withmanifest", "withextra", "prefixerr" } )

        # good: prefixes stripped + empties dropped; no manifest → no extras
        self.assertEqual( registry[ "good" ].allowed_prefixes, ( "src/", "docs/" ) )
        self.assertEqual( registry[ "good" ].extra_blocklist_patterns, () )
        self.assertIsNone( registry[ "good" ].manifest )

        # withmanifest: manifest present but no extra_blocklist → empty tuple
        self.assertEqual( registry[ "withmanifest" ].extra_blocklist_patterns, () )
        self.assertIsNotNone( registry[ "withmanifest" ].manifest )

        # withextra: one compiled extra pattern
        self.assertEqual( len( registry[ "withextra" ].extra_blocklist_patterns ), 1 )
        self.assertTrue( registry[ "withextra" ].extra_blocklist_patterns[ 0 ].search( "topsecret" ) )

        # prefixerr: prefix get raised → empty prefixes fallback
        self.assertEqual( registry[ "prefixerr" ].allowed_prefixes, () )

    def test_missing_path_skips_via_isdir_false( self ):
        """
        Ensures:
            - A configured path that fails os.path.isdir is skipped (the
              `not os.path.isdir(root)` arm, distinct from the None-path arm)
        """
        def cfg_get( key, default=None, return_type=None, silent=False ):
            if key == "external repos":
                return [ "absent" ]
            if key.endswith( "path" ):
                return "/does/not/exist"
            if key.endswith( "prefixes" ):
                return []
            return default

        config_mgr = MagicMock()
        config_mgr.get.side_effect = cfg_get

        with patch( "cosa.rest.routers._scope_registry.os.path.isdir", return_value=False ), \
             patch( "cosa.rest.routers._scope_registry.load_manifest_for_scope", return_value=None ):
            registry = build_scope_registry( config_mgr )

        self.assertEqual( registry, {} )


def isolated_unit_test():
    """
    Run the scope-registry unit tests in isolation.

    Ensures:
        - Executes all TestCases and reports (success, duration, message)
    """
    import cosa.utils.util as du

    start_time = time.time()
    try:
        loader = unittest.TestLoader()
        suite  = unittest.TestSuite()
        for tc in (
            TestIsSecretsPath, TestIsWhitelistedInScope, TestIsSecretsPathForScope,
            TestResolveInScope, TestBuildScopeRegistry,
        ):
            suite.addTests( loader.loadTestsFromTestCase( tc ) )
        result = unittest.TextTestRunner( verbosity=2 ).run( suite )

        duration  = time.time() - start_time
        tests_run = result.testsRun
        failures  = len( result.failures )
        errors    = len( result.errors )

        success = failures == 0 and errors == 0
        if success:
            du.print_banner( "✅ ALL SCOPE-REGISTRY TESTS PASSED", prepend_nl=True )
            message = f"All {tests_run} tests passed successfully in {duration:.3f}s"
        else:
            du.print_banner( "❌ SOME SCOPE-REGISTRY TESTS FAILED", prepend_nl=True )
            message = f"{failures} failures, {errors} errors out of {tests_run} tests"

        return success, duration, message

    except Exception as e:
        duration  = time.time() - start_time
        error_msg = f"Unit test execution failed: {str(e)}"
        du.print_banner( f"💥 SCOPE-REGISTRY TEST ERROR: {error_msg}", prepend_nl=True )
        return False, duration, error_msg


if __name__ == "__main__":
    success, duration, message = isolated_unit_test()
    status = "✅ PASS" if success else "❌ FAIL"
    print( f"\n{status} Scope-registry unit tests completed in {duration:.3f}s" )
    print( f"Result: {message}" )
