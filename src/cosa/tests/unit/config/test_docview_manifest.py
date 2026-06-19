"""
Unit tests for cosa.config.docview_manifest.

Covers the DocviewManifest Pydantic model (strict mode, version pin, regex
validation of extra_blocklist) and load_manifest_for_scope() across all
documented failure modes: absent, oversize, unreadable, malformed YAML,
empty, non-mapping root, and validation failure — each returning None per
the wildcard-fallback contract.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

import cosa.config.docview_manifest as dm
from cosa.config.docview_manifest import (
    DocviewManifest,
    load_manifest_for_scope,
    MAX_MANIFEST_BYTES,
)


class TestDocviewManifestModel( unittest.TestCase ):
    """The strict Pydantic manifest model."""

    def test_defaults( self ):
        m = DocviewManifest()
        self.assertEqual( m.version, 1 )
        self.assertEqual( m.allowed_prefixes, [] )
        self.assertEqual( m.extra_blocklist, [] )

    def test_valid_full_manifest( self ):
        m = DocviewManifest(
            version=1,
            allowed_prefixes=[ "src/", "docs/" ],
            allowed_root_files=[ "README.md" ],
            extra_blocklist=[ r"secret_.*\.key" ],
        )
        self.assertEqual( m.allowed_prefixes, [ "src/", "docs/" ] )

    def test_unknown_field_rejected( self ):
        with self.assertRaises( ValidationError ):
            DocviewManifest( remove_from_blocklist=[ "x" ] )

    def test_version_out_of_range_rejected( self ):
        with self.assertRaises( ValidationError ):
            DocviewManifest( version=2 )

    def test_invalid_regex_in_blocklist_rejected( self ):
        with self.assertRaises( ValidationError ):
            DocviewManifest( extra_blocklist=[ "(unclosed" ] )


class TestLoadManifestForScope( unittest.TestCase ):
    """load_manifest_for_scope() failure-mode matrix."""

    def setUp( self ):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup( self._tmp.cleanup )
        self.root = self._tmp.name

    def _write_manifest( self, content ):
        ( Path( self.root ) / ".docview.yml" ).write_text( content, encoding="utf-8" )

    def test_absent_returns_none( self ):
        self.assertIsNone( load_manifest_for_scope( self.root ) )

    def test_valid_manifest_parses( self ):
        self._write_manifest( "version: 1\nallowed_prefixes:\n  - src/\n" )
        m = load_manifest_for_scope( self.root )
        self.assertIsInstance( m, DocviewManifest )
        self.assertEqual( m.allowed_prefixes, [ "src/" ] )

    def test_oversize_returns_none( self ):
        self._write_manifest( "#" * ( MAX_MANIFEST_BYTES + 10 ) )
        self.assertIsNone( load_manifest_for_scope( self.root ) )

    def test_unreadable_returns_none( self ):
        self._write_manifest( "version: 1\n" )
        with patch.object( dm.Path, "read_text", side_effect=OSError( "denied" ) ):
            self.assertIsNone( load_manifest_for_scope( self.root ) )

    def test_malformed_yaml_returns_none( self ):
        self._write_manifest( "version: 1\nbad: [unclosed\n" )
        self.assertIsNone( load_manifest_for_scope( self.root ) )

    def test_empty_yaml_returns_none( self ):
        self._write_manifest( "# only a comment\n" )
        self.assertIsNone( load_manifest_for_scope( self.root ) )

    def test_non_mapping_root_returns_none( self ):
        self._write_manifest( "- a\n- b\n" )
        self.assertIsNone( load_manifest_for_scope( self.root ) )

    def test_validation_failure_returns_none( self ):
        self._write_manifest( "version: 1\nbogus_field: nope\n" )
        self.assertIsNone( load_manifest_for_scope( self.root ) )


if __name__ == "__main__":
    unittest.main()
