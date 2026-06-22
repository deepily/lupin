#!/usr/bin/env python3
"""
Unit tests for lupin_mcp.persona_normalization — THE single source of truth for
persona-name normalization (one identity root + two thin derivations).

Guards the persona-axis drift bug class:
  - 2026-06-18 owed-oracle false-idle ("María" -> "maría" matched zero store rows)
  - 2026-06-11 arbiter role misclassification (Mr. Radio badged as worker)

Decision rule the three primitives encode:
  - canonical_persona_key -> structured identity / store key (keep internal spaces)
  - normalize_for_match   -> lenient free-text match (drop spaces)
  - persona_slug          -> filesystem / DM-topic / session name (spaces -> sep)

R&D: src/rnd/v0.1.9/2026.06.19-persona-name-normalization/01-centralized-persona-normalization-plan.md
"""
import os
import sys

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from lupin_mcp.persona_normalization import (
    canonical_persona_key,
    normalize_for_match,
    persona_slug,
)


class TestCanonicalPersonaKey:
    """The IDENTITY root — keep internal spaces; output equals the store key."""

    def test_accent_stripped_lowercased( self ):
        """display "María" -> store key "maria" (the accent-axis miss)."""
        assert canonical_persona_key( "María" ) == "maria"

    def test_punctuation_dropped_internal_space_kept( self ):
        """display "Mr. Radio" -> "mr radio": period dropped, INTERNAL SPACE KEPT
        (exactly the store form — NOT the space-stripped "mrradio")."""
        assert canonical_persona_key( "Mr. Radio" ) == "mr radio"

    def test_clean_ascii_just_lowercases( self ):
        assert canonical_persona_key( "Clayton" )  == "clayton"
        assert canonical_persona_key( "Tiberius" ) == "tiberius"

    def test_emoji_and_punctuation_removed_space_collapsed( self ):
        assert canonical_persona_key( "Mr.  Radio 🦉" ) == "mr radio"

    def test_idempotent_on_already_normalized( self ):
        """The live bridge already holds the pool form; the key must be a no-op on
        it so the read query still matches the store."""
        for already in ( "maria", "mr radio", "clayton", "sam" ):
            assert canonical_persona_key( already ) == already
            assert canonical_persona_key( canonical_persona_key( already ) ) == canonical_persona_key( already )

    def test_leading_trailing_whitespace_trimmed( self ):
        assert canonical_persona_key( "  María  " ) == "maria"

    def test_digits_preserved( self ):
        assert canonical_persona_key( "Agent 007" ) == "agent 007"

    @pytest.mark.parametrize( "bad", [ None, "", "   ", 42, [ "x" ], { } ] )
    def test_falsy_or_non_string_returns_empty_sentinel( self, bad ):
        assert canonical_persona_key( bad ) == ""

    def test_punctuation_only_collapses_to_empty( self ):
        assert canonical_persona_key( "!!! ..." ) == ""


class TestNormalizeForMatch:
    """The LENIENT derivation — identity root with internal spaces removed."""

    def test_all_mr_radio_variants_collapse( self ):
        for variant in ( "Mr. Radio", "mr radio", "mrradio", "MR.RADIO" ):
            assert normalize_for_match( variant ) == "mrradio"

    def test_accent_now_stripped_FIXES_prior_bug( self ):
        """Prior `_normalize_for_match` kept the accent ("María" -> "maría") and so
        disagreed with the store; routing through the root makes it "maria"."""
        assert normalize_for_match( "María" ) == "maria"

    def test_empty_and_punctuation_only( self ):
        assert normalize_for_match( "" )      == ""
        assert normalize_for_match( "..." )   == ""
        assert normalize_for_match( None )    == ""

    def test_idempotent( self ):
        for raw in ( "Mr. Radio", "María", "sam" ):
            once = normalize_for_match( raw )
            assert normalize_for_match( once ) == once


class TestPersonaSlug:
    """The FILESYSTEM/TOPIC derivation — identity root with spaces -> separator."""

    def test_default_sep_hyphen( self ):
        assert persona_slug( "Mr. Radio" ) == "mr-radio"

    def test_underscore_sep( self ):
        assert persona_slug( "Mr. Radio", sep="_" ) == "mr_radio"

    def test_accent_proof( self ):
        assert persona_slug( "María" ) == "maria"

    def test_single_token_unchanged_by_sep( self ):
        assert persona_slug( "Clayton" )            == "clayton"
        assert persona_slug( "Clayton", sep="_" )   == "clayton"

    @pytest.mark.parametrize( "bad", [ None, "", "   ", "!!! ...", 42 ] )
    def test_unusable_input_returns_empty( self, bad ):
        assert persona_slug( bad ) == ""

    def test_idempotent_for_fixed_sep( self ):
        once = persona_slug( "Mr. Radio", sep="-" )
        assert persona_slug( once, sep="-" ) == once


class TestCrossPrimitiveConsistency:
    """The three primitives must share ONE root, differing only in space handling."""

    @pytest.mark.parametrize( "name", [ "María", "Mr. Radio", "Tiberius", "sam" ] )
    def test_match_is_key_without_spaces( self, name ):
        assert normalize_for_match( name ) == canonical_persona_key( name ).replace( " ", "" )

    @pytest.mark.parametrize( "name", [ "María", "Mr. Radio", "Tiberius", "sam" ] )
    def test_slug_is_key_with_sep( self, name ):
        key = canonical_persona_key( name )
        assert persona_slug( name, sep="-" ) == key.replace( " ", "-" )
        assert persona_slug( name, sep="_" ) == key.replace( " ", "_" )


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
