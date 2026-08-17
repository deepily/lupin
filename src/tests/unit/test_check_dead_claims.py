#!/usr/bin/env python3
"""
Unit tests for src/scripts/check_dead_claims.py — the repo-wide dead-claims checker.

Row 95924f2d-adjacent (Rachel, 2026-08-16): the checker's DEFAULT_CLAIMS and a
document's human §0.0 dead-claims TABLE were two lists with no linkage, so a family
added to the table but not to the checker went unenforced silently. The new
`--check-table-sync` path closes that: extract each table row's canonical phrase and
report any the checker does not enforce. These tests pin the parser, the drift
report, the existing live-claim scan, and every main() exit arm — hermetic, no repo
files touched.

EXECUTOR: AI — pure import + in-memory / tmp-file, no server, no inference. :7999-class.
Run: PYTHONPATH=src python -m pytest src/tests/unit/test_check_dead_claims.py -v
Coverage: --cov=check_dead_claims --cov-branch --cov-report=term-missing
"""

import importlib.util
import os
import tempfile
import unittest


# ── load the standalone script (src/scripts/ is not a package) by path ──
_SCRIPT = os.path.join(
    os.path.dirname( os.path.dirname( os.path.dirname( os.path.abspath( __file__ ) ) ) ),
    "scripts", "check_dead_claims.py",
)
_spec = importlib.util.spec_from_file_location( "check_dead_claims", _SCRIPT )
cdc   = importlib.util.module_from_spec( _spec )
_spec.loader.exec_module( cdc )


# A minimal document with a §0.0-style dead-claims table, then a body. The body line
# says "read the corpus" WITHOUT a marker in its window, so the live scan flags it.
_TABLE_DOC = """# Title

## 0.0 DEAD CLAIMS — GREP THIS LIST

| grep for | why it is dead | killed by |
|---|---|---|
| `alpha-vendor` | dead vendor | `abc123` |
| "config only", "three lines" | not config | `def456` |
| `gamma` as the source | wrong source | Rick |

## 1. Body

The plan still says read the corpus every time.
"""


class TestFirstQuoted( unittest.TestCase ):
    def test_backtick_wins_when_first( self ):
        self.assertEqual( cdc._first_quoted( "`alpha` then \"beta\"" ), "alpha" )

    def test_double_quote_when_no_backtick( self ):
        self.assertEqual( cdc._first_quoted( 'says "config only" here' ), "config only" )

    def test_double_quote_first_wins( self ):
        self.assertEqual( cdc._first_quoted( '"beta" then `alpha`' ), "beta" )

    def test_none_when_unquoted( self ):
        self.assertIsNone( cdc._first_quoted( "grep for" ) )


class TestExtractTableClaims( unittest.TestCase ):
    def test_extracts_canonical_phrase_per_row_in_order( self ):
        self.assertEqual(
            cdc.extract_table_claims( _TABLE_DOC ),
            [ "alpha-vendor", "config only", "gamma" ],
        )

    def test_heading_absent_returns_empty( self ):
        self.assertEqual( cdc.extract_table_claims( "# no table here\n\nbody\n" ), [] )

    def test_table_ends_at_first_non_table_line( self ):
        # The row after the table ("## 1. Body") ends it — nothing past it is parsed,
        # even though a later body line contains a quoted phrase.
        doc = _TABLE_DOC + '\n| `late` | should not be seen | x |\n'
        self.assertNotIn( "late", cdc.extract_table_claims( doc ) )

    def test_table_at_end_of_document_exhausts_loop( self ):
        # No non-table line follows the last row — the loop exits naturally, never
        # hitting the `elif in_table: break` arm.
        doc = "## 0.0 DEAD CLAIMS\n\n| grep | why | by |\n|---|---|---|\n| `omega` | dead | x |\n"
        self.assertEqual( cdc.extract_table_claims( doc ), [ "omega" ] )

    def test_header_and_separator_rows_contribute_nothing( self ):
        # "grep for" (header) and "---" (separator) carry no quoted token.
        claims = cdc.extract_table_claims( _TABLE_DOC )
        self.assertNotIn( "grep for", claims )
        self.assertNotIn( "---", claims )


class TestUnenforcedTableClaims( unittest.TestCase ):
    def test_reports_table_claims_absent_from_the_checker( self ):
        claims = { "alpha-vendor": "x", "gamma": "y" }   # "config only" not enforced
        self.assertEqual( cdc.unenforced_table_claims( _TABLE_DOC, claims ), [ "config only" ] )

    def test_all_enforced_returns_empty( self ):
        claims = { "alpha-vendor": "x", "config only": "y", "gamma": "z" }
        self.assertEqual( cdc.unenforced_table_claims( _TABLE_DOC, claims ), [] )


class TestFindLiveClaims( unittest.TestCase ):
    def test_unmarked_claim_is_reported( self ):
        text = "## 1. Body\n\nplease read the corpus now\n"
        live = cdc.find_live_claims( text, { "read the corpus": "snapshot it" } )
        self.assertEqual( len( live ), 1 )
        self.assertEqual( live[ 0 ][ 1 ], "read the corpus" )

    def test_marked_claim_is_not_reported( self ):
        text = "## 1. Body\n\n~~read the corpus~~ is DEAD now\n"
        self.assertEqual( cdc.find_live_claims( text, { "read the corpus": "x" } ), [] )

    def test_skip_until_ignores_the_region_before_it( self ):
        # The phrase appears only before the skip_until prefix → not reported.
        text = "## 0.0 table\n\nread the corpus\n\n## 1. Body\n\nclean line\n"
        self.assertEqual(
            cdc.find_live_claims( text, { "read the corpus": "x" }, skip_until="## 1. " ),
            [],
        )


def _write( text ):
    handle = tempfile.NamedTemporaryFile( "w", suffix=".md", delete=False, encoding="utf-8" )
    handle.write( text )
    handle.close()
    return handle.name


class TestMain( unittest.TestCase ):
    def setUp( self ):
        self._paths = []

    def tearDown( self ):
        for path in self._paths:
            os.unlink( path )

    def _doc( self, text ):
        path = _write( text )
        self._paths.append( path )
        return path

    def test_missing_document_returns_2( self ):
        self.assertEqual( cdc.main( [ "/no/such/doc.md" ] ), 2 )

    def test_live_claim_returns_1( self ):
        doc = self._doc( "## 1. Body\n\nplease read the corpus now\n" )
        claims = self._doc( '{ "read the corpus": "snapshot it" }' )
        self.assertEqual( cdc.main( [ doc, "--claims", claims ] ), 1 )

    def test_clean_no_flag_returns_0( self ):
        doc = self._doc( "## 1. Body\n\nnothing dead here\n" )
        self.assertEqual( cdc.main( [ doc ] ), 0 )

    def test_table_sync_drift_returns_3( self ):
        # Table lists "config only"/"gamma" the default claim set does not enforce,
        # and no live claim in the body → the sync arm decides the exit.
        doc = self._doc( _TABLE_DOC.replace( "read the corpus", "nothing dead" ) )
        claims = self._doc( '{ "alpha-vendor": "x" }' )
        self.assertEqual( cdc.main( [ doc, "--claims", claims, "--check-table-sync" ], ), 3 )

    def test_table_sync_in_sync_returns_0( self ):
        doc = self._doc( _TABLE_DOC.replace( "read the corpus", "nothing dead" ) )
        claims = self._doc( '{ "alpha-vendor": "x", "config only": "y", "gamma": "z" }' )
        self.assertEqual( cdc.main( [ doc, "--claims", claims, "--check-table-sync" ] ), 0 )

    def test_live_beats_sync_returns_1_even_with_drift( self ):
        # A live claim outranks drift: exit 1, not 3, though both are present.
        doc = self._doc( _TABLE_DOC )   # body still says "read the corpus" (live)
        claims = self._doc( '{ "read the corpus": "snapshot it" }' )
        self.assertEqual( cdc.main( [ doc, "--claims", claims, "--check-table-sync" ] ), 1 )


if __name__ == "__main__":
    unittest.main()
