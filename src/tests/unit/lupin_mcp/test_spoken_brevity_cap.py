"""
Unit tests for the caller-side TTS spoken-brevity cap in cosa_voice_mcp.

Covers `_enforce_spoken_brevity` — the guard wired into notify / converse /
ask_yes_no / ask_multiple_choice / ask_open_ended_batch — the config-driven,
runtime-tunable cap resolver `_get_spoken_char_cap`, and the global enforce
kill-switch `_get_spoken_enforce` (Rick 2026-06-09: False disables the guard
for ALL callers).

Venue: :7999-eligible (pure unit, no server, no state mutation).
"""

import os

import pytest

import lupin_mcp.cosa_voice_mcp as cv
from lupin_mcp.cosa_voice_mcp import (
    _enforce_spoken_brevity,
    _get_spoken_char_cap,
    _get_spoken_enforce,
    _refresh_spoken_cfg,
    SPOKEN_CHAR_CAP_DEFAULT,
    SPOKEN_ENFORCE_DEFAULT,
)

# Resolve the configured cap once (reads lupin-app.ini via ConfigurationManager).
CAP = _get_spoken_char_cap()


class TestCapResolver:

    def test_default_is_500( self ):
        assert SPOKEN_CHAR_CAP_DEFAULT == 500

    def test_resolver_returns_int( self ):
        assert isinstance( _get_spoken_char_cap(), int )

    def test_resolver_positive( self ):
        assert _get_spoken_char_cap() > 0


class TestEnforceResolver:

    def test_default_is_true( self ):
        assert SPOKEN_ENFORCE_DEFAULT is True

    def test_resolver_returns_bool( self ):
        assert isinstance( _get_spoken_enforce(), bool )

    def test_refresh_swallows_read_errors( self, monkeypatch ):
        # Force the mtime read to raise → _refresh_spoken_cfg must swallow it and
        # leave the last good cached values in place (never propagates).
        cv._spoken_cap_cache[ "ini_mtime" ] = None   # force a re-read attempt
        def _boom( _path ):
            raise OSError( "simulated stat failure" )
        monkeypatch.setattr( os.path, "getmtime", _boom )
        _refresh_spoken_cfg()                          # no raise
        assert isinstance( _get_spoken_char_cap(), int )
        assert isinstance( _get_spoken_enforce(), bool )


class TestSpokenBrevityCap:
    """Cap-enforcement behavior — pinned to enforce=ON so it is independent of the
    live INI kill-switch value."""

    @pytest.fixture( autouse=True )
    def _force_enforce_on( self, monkeypatch ):
        monkeypatch.setattr( cv, "_get_spoken_enforce", lambda: True )

    def test_short_string_passes( self ):
        # well under the cap → no raise
        _enforce_spoken_brevity( "x" * ( CAP // 4 ), False, field="message" )

    def test_at_cap_passes( self ):
        # boundary: exactly == cap is allowed (raise only when strictly over)
        _enforce_spoken_brevity( "x" * CAP, False )

    def test_over_cap_raises_with_actionable_message( self ):
        with pytest.raises( ValueError ) as exc:
            _enforce_spoken_brevity( "x" * ( CAP + 1 ), False, field="message" )
        msg = str( exc.value )
        assert str( CAP ) in msg                        # names the cap
        assert "abstract" in msg                        # tells where detail goes
        assert "override_size_limitation" in msg        # tells the escape hatch

    def test_override_bypasses_long_string( self ):
        # knowingly long → override lets it through, no raise
        _enforce_spoken_brevity( "x" * ( CAP * 5 ), True )

    def test_questions_list_all_short_passes( self ):
        _enforce_spoken_brevity(
            [ { "question": "x" * 10 }, { "question": "y" * 20 } ], False, field="questions"
        )

    def test_questions_list_one_over_raises_with_index( self ):
        with pytest.raises( ValueError ) as exc:
            _enforce_spoken_brevity(
                [ { "question": "x" * 10 }, { "question": "z" * ( CAP + 1 ) } ],
                False, field="questions"
            )
        assert "questions[1].question" in str( exc.value )

    def test_questions_list_override_bypasses( self ):
        _enforce_spoken_brevity(
            [ { "question": "z" * ( CAP + 1 ) } ], True, field="questions"
        )

    def test_malformed_question_entries_are_skipped( self ):
        # entries lacking a str "question" are ignored, not crashed on
        _enforce_spoken_brevity(
            [ { "header": "h" }, { "question": 123 } ], False, field="questions"
        )


class TestEnforceKillSwitch:
    """Global enforce flag (Rick 2026-06-09): False disables the guard for everyone."""

    def test_disabled_lets_over_cap_string_through( self, monkeypatch ):
        monkeypatch.setattr( cv, "_get_spoken_enforce", lambda: False )
        # would raise under enforce=True; kill-switch OFF → no raise
        _enforce_spoken_brevity( "x" * ( CAP * 10 ), False, field="message" )

    def test_disabled_lets_over_cap_questions_through( self, monkeypatch ):
        monkeypatch.setattr( cv, "_get_spoken_enforce", lambda: False )
        _enforce_spoken_brevity(
            [ { "question": "z" * ( CAP + 1 ) } ], False, field="questions"
        )

    def test_enabled_still_raises_over_cap( self, monkeypatch ):
        monkeypatch.setattr( cv, "_get_spoken_enforce", lambda: True )
        with pytest.raises( ValueError ):
            _enforce_spoken_brevity( "x" * ( CAP + 1 ), False )
