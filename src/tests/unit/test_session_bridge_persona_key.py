#!/usr/bin/env python3
"""
Unit tests for session_bridge.canonical_persona_key — THE single persona-name
normalizer the owed-work READ seam (stop hook) and the task-store WRITE seam must
agree on. Guards the persona-axis false-idle bug class (2026-06-18): an accented /
punctuated persona name was bare-.lower()-ed on the read side ("María" → "maría"),
matching ZERO of the store's "maria" rows → false "nothing owed".
"""
import os
import sys

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from lupin_cli.claude_code.hooks.lib.session_bridge import canonical_persona_key


class TestCanonicalPersonaKey:

    def test_accent_stripped_lowercased( self ):
        """display "María" → store key "maria" (the accent-axis miss)."""
        assert canonical_persona_key( "María" ) == "maria"

    def test_punctuation_dropped_internal_space_kept( self ):
        """display "Mr. Radio" → "mr radio": period dropped, INTERNAL SPACE KEPT
        (exactly the store form — NOT _norm_persona's space-stripped "mrradio")."""
        assert canonical_persona_key( "Mr. Radio" ) == "mr radio"

    def test_clean_ascii_just_lowercases( self ):
        assert canonical_persona_key( "Clayton" )  == "clayton"
        assert canonical_persona_key( "Tiberius" ) == "tiberius"

    def test_emoji_and_punctuation_removed_space_collapsed( self ):
        assert canonical_persona_key( "Mr.  Radio 🦉" ) == "mr radio"

    def test_idempotent_on_already_normalized( self ):
        """Regression-safety: the live bridge already holds the pool form; the key
        must be a no-op on it so the read query still matches the store."""
        for already in ( "maria", "mr radio", "clayton", "sam" ):
            assert canonical_persona_key( already ) == already
            assert canonical_persona_key( canonical_persona_key( already ) ) == canonical_persona_key( already )

    def test_leading_trailing_whitespace_trimmed( self ):
        assert canonical_persona_key( "  María  " ) == "maria"

    @pytest.mark.parametrize( "bad", [ None, "", "   ", 42, [ "x" ], { } ] )
    def test_falsy_or_non_string_returns_empty_sentinel( self, bad ):
        assert canonical_persona_key( bad ) == ""

    def test_punctuation_only_collapses_to_empty( self ):
        assert canonical_persona_key( "!!! ..." ) == ""


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
