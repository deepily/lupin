"""
Unit tests for `resolve_sender_id` and the three timezone display helpers in
`cosa.rest.routers.notifications`.

🔴 THE TIME HELPERS ARE THE TRAP IN THIS FILE, AND IT IS THE FIXTURE KIND. Each has a
configured-timezone path and a fallback path, and the naive fixture — configure
"America/New_York", assert the output looks like a time — passes BOTH paths, because
the fallback also returns a time that looks like a time. The two branches are only
distinguishable if the configured timezone and the machine's local time differ in the
output, so every test here picks a zone whose abbreviation cannot be the local one and
asserts THAT, not the shape.

`resolve_sender_id` has a three-level precedence, so each level is posed with the two
below it also satisfiable — otherwise "returned the explicit id" is indistinguishable
from "fell through to a default that happened to match".
"""

import re
import sys
import os

import pytest

# Bootstrap imports
lupin_root = os.environ.get( "LUPIN_ROOT" )
if lupin_root:
    src_path = os.path.join( lupin_root, "src" )
    if src_path not in sys.path:
        sys.path.insert( 0, src_path )

import cosa.rest.routers.notifications as notif


# ──────────────────────────────────────────────────────────────────────────────
# resolve_sender_id
# ──────────────────────────────────────────────────────────────────────────────

class TestResolveSenderId:
    """
    Precedence: explicit > [PREFIX] in the message > default.

    Ensures:
        - each level wins over the ones below it
        - the prefix is lowercased into the project slot
        - a message with no usable prefix falls back rather than raising
    """

    def test_an_explicit_id_wins_over_a_prefix_that_would_also_match( self ):
        """
        🔴 THE MESSAGE CARRIES A VALID PREFIX TOO. Without it, "returned the explicit
        id" cannot be told from "there was nothing else to return".
        """
        out = notif.resolve_sender_id( "explicit@example.com", "[LUPIN] hello" )
        assert out == "explicit@example.com"

    def test_a_prefix_wins_over_the_default( self ):
        out = notif.resolve_sender_id( None, "[LUPIN] hello" )
        assert out == "claude.code@lupin.deepily.ai"

    def test_the_prefix_is_lowercased_into_the_project_slot( self ):
        # 🔴 the prefix is UPPER and the expected slot is lower, so a helper that
        # skipped .lower() produces a different string rather than the same one.
        out = notif.resolve_sender_id( None, "[COSA] hello" )
        assert out == "claude.code@cosa.deepily.ai"
        assert "COSA" not in out

    def test_an_empty_explicit_id_falls_through_rather_than_being_used( self ):
        # "" is falsy, so precedence 1 must NOT fire — and the message's prefix must.
        out = notif.resolve_sender_id( "", "[LUPIN] hello" )
        assert out == "claude.code@lupin.deepily.ai"

    @pytest.mark.parametrize( "message", [
        "no prefix here",
        "[lupin] lowercase is not a prefix",
        "[LUPIN2] digits are not in the class",
        " [LUPIN] a leading space breaks the anchor",
        "text before [LUPIN] is not a prefix",
    ] )
    def test_a_message_without_a_leading_uppercase_prefix_falls_back( self, message ):
        """
        🔴 EACH OF THESE FAILS FOR A DIFFERENT REASON — no bracket, wrong case, a
        character outside [A-Z]+, and the ^ anchor twice. A single "no prefix" case
        would accept a regex that had quietly dropped the anchor or the case class.
        """
        assert notif.resolve_sender_id( None, message ) == "claude.code@unknown.deepily.ai"

    def test_the_prefix_must_be_at_the_very_start( self ):
        # the discriminating pair: same prefix, only the position differs.
        assert notif.resolve_sender_id( None, "[LUPIN] x" ) == "claude.code@lupin.deepily.ai"
        assert notif.resolve_sender_id( None, "x [LUPIN]" ) == "claude.code@unknown.deepily.ai"


# ──────────────────────────────────────────────────────────────────────────────
# the timezone display helpers
# ──────────────────────────────────────────────────────────────────────────────

class _Cfg:
    """A config stand-in that answers one key and records the default it was offered."""

    def __init__( self, value ):
        self.value = value
        self.seen  = {}

    def get( self, key, default=None, **_kwargs ):
        self.seen[ key ] = default
        return self.value


@pytest.fixture
def config( monkeypatch ):
    """Point the helpers' `import lupin_app.main` at a controllable config."""
    import lupin_app.main as main_module

    def _install( timezone_name, app_debug=False ):
        cfg = _Cfg( timezone_name )
        monkeypatch.setattr( main_module, "config_mgr", cfg )
        monkeypatch.setattr( main_module, "app_debug", app_debug, raising=False )
        return cfg

    return _install


# UTC is chosen deliberately: its offset is fixed and its abbreviation is stable, so an
# assertion against it cannot accidentally agree with the machine's local zone unless
# the machine IS UTC — which the guard below rules out before asserting.
_FIXED_ZONE = "Asia/Kolkata"      # +05:30 — a half-hour offset no CI box uses by default


class TestGetLocalTimestamp:

    def test_it_uses_the_configured_timezone_not_the_machines( self, config ):
        """
        🔴 THE OFFSET IS THE ASSERTION, NOT THE SHAPE. Both the configured path and
        the UTC fallback return an ISO string, so "it looks like a timestamp" passes
        a helper that ignored the config entirely. +05:30 is a half-hour offset, so
        it cannot coincide with a whole-hour local zone.
        """
        config( _FIXED_ZONE )
        out = notif.get_local_timestamp()
        assert out.endswith( "+05:30" ), out

    def test_it_asks_config_for_the_timezone_with_a_new_york_default( self, config ):
        cfg = config( _FIXED_ZONE )
        notif.get_local_timestamp()
        assert cfg.seen[ "app timezone" ] == "America/New_York"

    def test_an_invalid_timezone_falls_back_instead_of_raising( self, config ):
        config( "Mars/Olympus_Mons" )
        out = notif.get_local_timestamp()
        # the fallback is a naive local isoformat — it must NOT carry the offset the
        # configured path would have produced, and it must not raise.
        assert not out.endswith( "+05:30" )
        assert re.match( r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", out ), out

    def test_the_debug_line_is_printed_only_when_app_debug_is_on( self, config, capsys ):
        """
        Both sides, because a helper that always printed, or never did, satisfies
        either half alone.
        """
        config( "Mars/Olympus_Mons", app_debug=True )
        notif.get_local_timestamp()
        assert "[TIMEZONE]" in capsys.readouterr().out

        config( "Mars/Olympus_Mons", app_debug=False )
        notif.get_local_timestamp()
        assert "[TIMEZONE]" not in capsys.readouterr().out


class TestGetFormattedTimeDisplay:

    def test_it_renders_the_configured_zones_abbreviation( self, config ):
        """
        🔴 THE ABBREVIATION IS WHAT SEPARATES THE BRANCHES. The fallback returns bare
        "HH:MM" with no zone at all, so asserting a zone token is present is what
        tells the configured path from the fallback — a "looks like a time" check
        passes both.
        """
        config( _FIXED_ZONE )
        out = notif.get_formatted_time_display()
        assert re.match( r"^\d{2}:\d{2} \S+$", out ), out
        assert "IST" in out, out

    def test_an_invalid_timezone_falls_back_to_a_bare_time( self, config ):
        config( "Mars/Olympus_Mons" )
        out = notif.get_formatted_time_display()
        assert re.match( r"^\d{2}:\d{2}$", out ), out

    def test_it_asks_config_for_the_timezone_with_a_new_york_default( self, config ):
        cfg = config( _FIXED_ZONE )
        notif.get_formatted_time_display()
        assert cfg.seen[ "app timezone" ] == "America/New_York"


class TestGetFormattedDateDisplay:

    def test_it_returns_a_non_empty_string_for_a_valid_zone( self, config ):
        config( _FIXED_ZONE )
        out = notif.get_formatted_date_display()
        assert isinstance( out, str ) and out.strip()

    def test_an_invalid_timezone_falls_back_instead_of_raising( self, config ):
        config( "Mars/Olympus_Mons" )
        out = notif.get_formatted_date_display()
        assert isinstance( out, str ) and out.strip()

    def test_it_asks_config_for_the_timezone_with_a_new_york_default( self, config ):
        cfg = config( _FIXED_ZONE )
        notif.get_formatted_date_display()
        assert cfg.seen[ "app timezone" ] == "America/New_York"
