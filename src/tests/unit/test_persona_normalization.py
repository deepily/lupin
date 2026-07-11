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

    def test_separator_becomes_space_not_deleted_bug_951a22be( self ):
        """bug 951a22be: a slug-form separator ("_"/"-") must map to a word-boundary
        SPACE, not VANISH. María filed a P1 with owner_persona="mr_radio"; the prior
        r"[^a-z0-9 ]" DELETE fused it to the unmatchable "mrradio", so every scoped
        query (owner_persona="mr radio") missed it and the P1 sat invisible.
        FLIP: revert the regex to the delete form and both asserts re-fuse to
        "mrradio" and fail."""
        assert canonical_persona_key( "mr_radio" ) == "mr radio"
        assert canonical_persona_key( "mr-radio" ) == "mr radio"

    def test_repeated_and_mixed_separators_collapse_to_one_space_bug_951a22be( self ):
        """A RUN of separators (and separator+space mixes) collapses to ONE space —
        never a fused token, never a double space. FLIP: the delete form fuses
        "mr__radio" -> "mrradio"."""
        assert canonical_persona_key( "mr__radio" )     == "mr radio"
        assert canonical_persona_key( "mr - radio" )    == "mr radio"
        assert canonical_persona_key( "deep_research" ) == "deep research"

    def test_idempotent_on_separator_inputs_bug_951a22be( self ):
        """The canonicalized separator form is a fixed point — a second pass over
        the already-spaced key must not drift."""
        for raw in ( "mr_radio", "mr-radio", "mr__radio", "deep_research" ):
            once = canonical_persona_key( raw )
            assert canonical_persona_key( once ) == once

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

    def test_idempotent_for_underscore_sep( self ):
        """bug 9980dd9a also covered for sep='_' (the DM-topic separator)."""
        once = persona_slug( "Mr. Radio", sep="_" )
        assert once == "mr_radio"
        assert persona_slug( once, sep="_" ) == once

    @pytest.mark.parametrize( "name", [ "Mr. Radio", "María", "Tiberius", "mr radio", "maría" ] )
    @pytest.mark.parametrize( "sep", [ "-", "_" ] )
    def test_reslugging_an_already_slugged_value_round_trips( self, name, sep ):
        """The fix's contract: an ALREADY-slugged value must survive a second slug
        pass unchanged for the SAME sep — else canonical_persona_key would fuse
        "mr-radio" → "mrradio" (the bug). FLIP: revert the idempotency fix and the
        Mr. Radio case re-fuses and this fails."""
        once = persona_slug( name, sep=sep )
        assert persona_slug( once, sep=sep ) == once

    def test_falsy_sep_strips_spaces_and_is_idempotent( self ):
        """Defensive branch: a falsy sep skips the boundary-restore step; the slug
        then strips spaces (like normalize_for_match) and is still idempotent."""
        assert persona_slug( "Mr. Radio", sep="" ) == "mrradio"
        assert persona_slug( persona_slug( "Mr. Radio", sep="" ), sep="" ) == "mrradio"


class TestCrossPrimitiveConsistency:
    """The three primitives must share ONE root, differing only in space handling."""

    @pytest.mark.parametrize( "name", [ "María", "Mr. Radio", "Tiberius", "sam", "mr_radio", "mr-radio" ] )
    def test_match_is_key_without_spaces( self, name ):
        assert normalize_for_match( name ) == canonical_persona_key( name ).replace( " ", "" )

    @pytest.mark.parametrize( "name", [ "María", "Mr. Radio", "Tiberius", "sam", "mr_radio", "mr-radio" ] )
    def test_slug_is_key_with_sep( self, name ):
        key = canonical_persona_key( name )
        assert persona_slug( name, sep="-" ) == key.replace( " ", "-" )
        assert persona_slug( name, sep="_" ) == key.replace( " ", "_" )


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
