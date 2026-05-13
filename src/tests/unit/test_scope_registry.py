"""
Unit tests for `cosa.rest.routers._scope_registry`.

Covers:
- ScopeConfig frozen-dataclass behavior
- Secrets blocklist (matches + non-matches, including word-boundary discipline)
- Whitelist semantics (wildcard, strict prefixes, bare-prefix root)
- Traversal-blocking resolve_in_scope
- build_scope_registry with a stub ConfigurationManager

Tier: unit (`:7999`-discretionary per CLAUDE.md TESTING VENUES).
Design doc: src/rnd/v0.1.7/2026.05.12-multi-repo-doc-viewer.md §5
"""

import os
import tempfile
import unittest

from cosa.rest.routers._scope_registry import (
    ScopeConfig,
    _is_secrets_path,
    _is_whitelisted_in_scope,
    build_scope_registry,
    resolve_in_scope,
)


class _StubConfigMgr:
    """Minimal ConfigurationManager stand-in for `build_scope_registry`."""

    def __init__( self, values: dict ):
        self._values = values

    def get( self, key, default=None, return_type=None, silent=False ):
        if key not in self._values:
            return default
        value = self._values[ key ]
        if return_type == "list-string":
            if isinstance( value, list ):
                return value
            return value.split( ", " )
        return value


class TestScopeConfig( unittest.TestCase ):

    def test_is_frozen( self ):
        sc = ScopeConfig( name="x", root="/tmp", allowed_prefixes=( ) )
        with self.assertRaises( Exception ):
            sc.name = "y"   # type: ignore[misc]

    def test_carries_fields_verbatim( self ):
        sc = ScopeConfig( name="abc", root="/var/x", allowed_prefixes=( "src/", "docs/" ) )
        self.assertEqual( sc.name, "abc" )
        self.assertEqual( sc.root, "/var/x" )
        self.assertEqual( sc.allowed_prefixes, ( "src/", "docs/" ) )


class TestSecretsBlocklist( unittest.TestCase ):

    def test_dotenv_variants( self ):
        for name in ( ".env", ".env.production", ".env.local", ".env.staging" ):
            self.assertTrue( _is_secrets_path( name ), msg=name )

    def test_netrc_and_pgpass( self ):
        self.assertTrue( _is_secrets_path( ".netrc" ) )
        self.assertTrue( _is_secrets_path( ".pgpass" ) )

    def test_credentials_word( self ):
        self.assertTrue( _is_secrets_path( "credentials.json" ) )
        self.assertTrue( _is_secrets_path( "user-credentials.txt" ) )
        self.assertTrue( _is_secrets_path( "Credential.yaml" ) )
        self.assertTrue( _is_secrets_path( "src/auth/credentials.py" ) )

    def test_secrets_word( self ):
        self.assertTrue( _is_secrets_path( "secrets.yaml" ) )
        self.assertTrue( _is_secrets_path( "my-secret.txt" ) )
        self.assertTrue( _is_secrets_path( "Secret.json" ) )

    def test_keys_and_certs( self ):
        self.assertTrue( _is_secrets_path( "deploy.pem" ) )
        self.assertTrue( _is_secrets_path( "tls.key" ) )
        self.assertTrue( _is_secrets_path( "cert.pfx" ) )
        self.assertTrue( _is_secrets_path( "client.p12" ) )

    def test_ssh_key_filenames( self ):
        self.assertTrue( _is_secrets_path( "id_rsa" ) )
        self.assertTrue( _is_secrets_path( "id_rsa.pub" ) )
        self.assertTrue( _is_secrets_path( "id_ed25519" ) )
        self.assertTrue( _is_secrets_path( "id_dsa" ) )
        self.assertTrue( _is_secrets_path( "id_ecdsa" ) )

    def test_word_boundary_no_false_positives( self ):
        # The 'secrets?' / 'credentials?' patterns are word-boundary anchored —
        # these legitimate filenames must NOT be blocked.
        self.assertFalse( _is_secrets_path( "secretive_methods.py" ) )
        self.assertFalse( _is_secrets_path( "credentialism.txt" ) )
        self.assertFalse( _is_secrets_path( "environment.md" ) )
        self.assertFalse( _is_secrets_path( "environments.py" ) )
        self.assertFalse( _is_secrets_path( "pem-helper.py" ) )
        self.assertFalse( _is_secrets_path( "key_values.txt" ) )

    def test_nested_path_segments( self ):
        # The blocklist checks every segment — a secrets-bearing intermediate
        # directory should block the whole path.
        self.assertTrue( _is_secrets_path( "src/credentials/foo.py" ) )
        self.assertTrue( _is_secrets_path( "deploy/.env" ) )

    def test_empty_path_returns_false( self ):
        self.assertFalse( _is_secrets_path( "" ) )


class TestWhitelistSemantics( unittest.TestCase ):

    def test_empty_prefixes_is_wildcard( self ):
        sc = ScopeConfig( name="wild", root="/tmp", allowed_prefixes=( ) )
        self.assertTrue( _is_whitelisted_in_scope( sc, "anything/at/all.md" ) )
        self.assertTrue( _is_whitelisted_in_scope( sc, "deep/nested/path/file.py" ) )
        self.assertTrue( _is_whitelisted_in_scope( sc, "" ) )

    def test_strict_prefixes_match( self ):
        sc = ScopeConfig( name="s", root="/tmp", allowed_prefixes=( "src/", "docs/" ) )
        self.assertTrue( _is_whitelisted_in_scope( sc, "src/foo.py" ) )
        self.assertTrue( _is_whitelisted_in_scope( sc, "docs/readme.md" ) )

    def test_bare_prefix_root_matches( self ):
        # Q2 resolution from doc-viewer-directory-listing — `src` should match
        # the `src/` prefix so /app/docs?path=src&scope=... renders the listing.
        sc = ScopeConfig( name="s", root="/tmp", allowed_prefixes=( "src/", ) )
        self.assertTrue( _is_whitelisted_in_scope( sc, "src" ) )

    def test_non_matching_prefix_rejected( self ):
        sc = ScopeConfig( name="s", root="/tmp", allowed_prefixes=( "src/", ) )
        self.assertFalse( _is_whitelisted_in_scope( sc, "lib/foo.py" ) )
        self.assertFalse( _is_whitelisted_in_scope( sc, "etc" ) )

    def test_empty_path_listing_always_allowed( self ):
        # The scope root itself is always listable; per-entry filtering decides
        # what shows up inside.
        sc = ScopeConfig( name="s", root="/tmp", allowed_prefixes=( "src/", ) )
        self.assertTrue( _is_whitelisted_in_scope( sc, "" ) )


class TestResolveInScope( unittest.TestCase ):

    def test_normal_resolution( self ):
        with tempfile.TemporaryDirectory() as tmp:
            sc = ScopeConfig( name="t", root=tmp, allowed_prefixes=( ) )
            resolved = resolve_in_scope( sc, "subdir/file.md" )
            self.assertEqual( resolved, os.path.join( tmp, "subdir/file.md" ) )

    def test_traversal_blocked( self ):
        with tempfile.TemporaryDirectory() as tmp:
            sc = ScopeConfig( name="t", root=tmp, allowed_prefixes=( ) )
            with self.assertRaises( ValueError ):
                resolve_in_scope( sc, "../etc/passwd" )

    def test_empty_path_resolves_to_root( self ):
        with tempfile.TemporaryDirectory() as tmp:
            sc = ScopeConfig( name="t", root=tmp, allowed_prefixes=( ) )
            resolved = resolve_in_scope( sc, "" )
            # os.path.normpath collapses "tmp/." → "tmp" so resolved == root
            self.assertEqual( resolved.rstrip( os.sep ), tmp.rstrip( os.sep ) )

    def test_dot_dot_in_middle_blocked( self ):
        with tempfile.TemporaryDirectory() as tmp:
            sc = ScopeConfig( name="t", root=tmp, allowed_prefixes=( ) )
            with self.assertRaises( ValueError ):
                resolve_in_scope( sc, "subdir/../../etc/passwd" )


class TestBuildScopeRegistry( unittest.TestCase ):

    def test_empty_list_returns_empty_registry( self ):
        cfg = _StubConfigMgr( { "external repos": [ ] } )
        self.assertEqual( build_scope_registry( cfg ), { } )

    def test_single_valid_scope( self ):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _StubConfigMgr( {
                "external repos"                : [ "alpha" ],
                "external repo alpha path"      : tmp,
                "external repo alpha allowed prefixes" : [ "src/" ],
            } )
            reg = build_scope_registry( cfg )
            self.assertIn( "alpha", reg )
            self.assertEqual( reg[ "alpha" ].name, "alpha" )
            self.assertEqual( reg[ "alpha" ].root, tmp )
            self.assertEqual( reg[ "alpha" ].allowed_prefixes, ( "src/", ) )

    def test_missing_path_is_skipped_not_fatal( self ):
        cfg = _StubConfigMgr( {
            "external repos"                : [ "ghost" ],
            "external repo ghost path"      : "/nonexistent/path/that/does/not/exist",
            "external repo ghost allowed prefixes" : [ ],
        } )
        reg = build_scope_registry( cfg )
        self.assertNotIn( "ghost", reg )
        self.assertEqual( reg, { } )

    def test_reserved_name_collisions_rejected( self ):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _StubConfigMgr( {
                "external repos"             : [ "docs", "io", "valid" ],
                "external repo docs path"    : tmp,
                "external repo io path"      : tmp,
                "external repo valid path"   : tmp,
            } )
            reg = build_scope_registry( cfg )
            self.assertNotIn( "docs", reg )
            self.assertNotIn( "io", reg )
            self.assertIn( "valid", reg )

    def test_empty_prefix_list_becomes_empty_tuple( self ):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _StubConfigMgr( {
                "external repos"             : [ "wild" ],
                "external repo wild path"    : tmp,
                "external repo wild allowed prefixes" : [ ],
            } )
            reg = build_scope_registry( cfg )
            self.assertEqual( reg[ "wild" ].allowed_prefixes, ( ) )

    def test_whitespace_stripped_from_names_and_prefixes( self ):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _StubConfigMgr( {
                "external repos"             : [ "  spaced  ", "" ],
                "external repo spaced path"  : tmp,
                "external repo spaced allowed prefixes" : [ "  src/  ", "", "   " ],
            } )
            reg = build_scope_registry( cfg )
            self.assertIn( "spaced", reg )
            # Empty / whitespace-only prefix entries drop out
            self.assertEqual( reg[ "spaced" ].allowed_prefixes, ( "src/", ) )

    def test_multiple_scopes_some_valid_some_not( self ):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _StubConfigMgr( {
                "external repos"               : [ "good", "missing", "another_good" ],
                "external repo good path"      : tmp,
                "external repo missing path"   : "/nope",
                "external repo another_good path"        : tmp,
                "external repo another_good allowed prefixes" : [ "lib/" ],
            } )
            reg = build_scope_registry( cfg )
            self.assertIn( "good", reg )
            self.assertIn( "another_good", reg )
            self.assertNotIn( "missing", reg )
            self.assertEqual( len( reg ), 2 )


if __name__ == "__main__":
    unittest.main( verbosity=2 )
