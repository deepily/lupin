"""
Unit tests for `lupin_cli.claude_code.hooks.lib.idle_settings` (row e2099400).

WHY THIS FILE DID NOT EXIST UNTIL NOW, and it is the row's own thesis in miniature: measured
2026-08-26 at `61ba041d`, this module sat at **19% (25 of 34 statements uncovered) with ZERO
unit test files naming it** — while `stop.py:51` and `idle_waiter.py:43` both import
`load_idle_settings` on the Stop-hook path. The mandate that certifies the fleet could not see
the loader the fleet's idle detection runs on.

WHAT IS PINNED HERE. The module's contract is "fall back QUIETLY when the file or the block is
absent, and fail LOUDLY when the schedule is malformed" — two opposite behaviours a few lines
apart, which is exactly the kind of pair that rots silently when nothing asserts on it. Each
fallback path and each rejection is a separate test so a failure names the case rather than
the file.

HOME is redirected per-test rather than the module being monkeypatched, so these exercise the
real `Path( os.path.expanduser( ... ) )` resolution instead of a stub of it.
"""
import json
import os
import sys

import pytest

_src_path = os.path.join( os.environ[ "LUPIN_ROOT" ], "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from lupin_cli.claude_code.hooks.lib import idle_settings as ids


@pytest.fixture
def fake_home( tmp_path, monkeypatch ):
    """A HOME with no ~/.claude yet. Tests that want a settings.json write one."""
    monkeypatch.setenv( "HOME", str( tmp_path ) )
    monkeypatch.delenv( "USERPROFILE", raising=False )   # expanduser prefers it on some platforms
    return tmp_path


def _write_settings( home, payload ):
    claude_dir = home / ".claude"
    claude_dir.mkdir( parents=True, exist_ok=True )
    path = claude_dir / "settings.json"
    path.write_text( payload if isinstance( payload, str ) else json.dumps( payload ) )
    return path


# ── the QUIET half: absence is not an error ────────────────────────────────────

class TestFallsBackQuietlyWhenThereIsNothingToRead:

    def test_a_missing_settings_file_yields_the_documented_defaults( self, fake_home ):
        assert ids.load_idle_settings() == { "enabled"         : True,
                                             "backoff_minutes" : [ 5, 10, 20, 40, 60 ] }

    def test_unparseable_json_yields_defaults_rather_than_taking_the_hook_down( self, fake_home ):
        # Deliberate, and the module says why: settings.json is SHARED with other Claude Code
        # features, so a typo elsewhere in it must not disable idle detection specifically.
        _write_settings( fake_home, "{ this is not json" )
        assert ids.load_idle_settings() == ids._defaults()

    def test_a_file_that_cannot_be_OPENED_yields_defaults( self, fake_home ):
        # The `except OSError` arm — distinct from the JSONDecodeError arm above. A directory
        # where the file should be reproduces it without depending on chmod semantics (root
        # ignores the permission bit, so a chmod-based test passes for the wrong reason).
        ( fake_home / ".claude" ).mkdir( parents=True )
        ( fake_home / ".claude" / "settings.json" ).mkdir()
        assert ids.load_idle_settings() == ids._defaults()

    def test_settings_without_the_idle_detection_block_yields_defaults( self, fake_home ):
        _write_settings( fake_home, { "some_other_feature": { "enabled": False } } )
        assert ids.load_idle_settings() == ids._defaults()

    @pytest.mark.parametrize( "block", [ None, "on", 42, [ 5, 10 ] ] )
    def test_an_idle_detection_block_that_is_not_a_dict_yields_defaults( self, fake_home, block ):
        _write_settings( fake_home, { "idle_detection": block } )
        assert ids.load_idle_settings() == ids._defaults()


class TestIndividualFieldsFallBackIndependently:

    def test_enabled_alone_keeps_the_default_schedule( self, fake_home ):
        _write_settings( fake_home, { "idle_detection": { "enabled": False } } )
        got = ids.load_idle_settings()
        assert got[ "enabled" ] is False
        assert got[ "backoff_minutes" ] == ids.DEFAULT_BACKOFF_MINUTES

    def test_a_schedule_alone_keeps_the_default_enabled( self, fake_home ):
        _write_settings( fake_home, { "idle_detection": { "backoff_minutes": [ 1, 2 ] } } )
        got = ids.load_idle_settings()
        assert got[ "enabled" ] is ids.DEFAULT_ENABLED
        assert got[ "backoff_minutes" ] == [ 1, 2 ]

    @pytest.mark.parametrize( "raw,expected", [ ( 0, False ), ( 1, True ), ( "", False ),
                                                ( "no", True ), ( [], False ), ( None, False ) ] )
    def test_enabled_is_coerced_by_python_truthiness_and_always_a_bool( self, fake_home, raw, expected ):
        # Documented as coercion, not validation — note "no" is TRUE, which is surprising
        # enough to be worth pinning rather than discovering in production.
        _write_settings( fake_home, { "idle_detection": { "enabled": raw } } )
        got = ids.load_idle_settings()[ "enabled" ]
        assert got is expected and isinstance( got, bool )


class TestTheReturnedScheduleIsAlwaysACopy:
    """A caller mutating the result must not rewrite the next caller's defaults."""

    def test_defaults_hands_out_a_fresh_list_each_time( self ):
        first = ids._defaults()
        first[ "backoff_minutes" ].append( 999 )
        assert ids._defaults()[ "backoff_minutes" ] == [ 5, 10, 20, 40, 60 ]
        assert ids.DEFAULT_BACKOFF_MINUTES == [ 5, 10, 20, 40, 60 ]

    def test_an_omitted_schedule_does_not_hand_out_the_MODULE_default_list( self, fake_home ):
        """
        🔴 THE ONE THAT MATTERS, and my first attempt at it was toothless.

        I originally wrote this against a schedule READ FROM THE FILE, mutated the result, and
        asserted the next load was clean. That test cannot fail: `load_idle_settings` re-parses
        the file every call, so the next load is clean whether or not the code copies anything.
        Deleting `list( ... )` passed all 35 tests — the mutation survived.

        The aliasing this actually guards is the OTHER branch: when `backoff_minutes` is absent,
        `block.get( ..., DEFAULT_BACKOFF_MINUTES )` returns the MODULE-LEVEL list itself. Without
        the copy, one caller appending to its result silently rewrites the defaults for every
        later caller in the process — including callers that read a settings file at all.
        """
        _write_settings( fake_home, { "idle_detection": { "enabled": True } } )   # no schedule key
        got = ids.load_idle_settings()
        got[ "backoff_minutes" ].append( 999 )

        assert ids.DEFAULT_BACKOFF_MINUTES == [ 5, 10, 20, 40, 60 ], (
            "the module default was mutated through a caller's result — load_idle_settings "
            "handed out the module's own list instead of a copy"
        )
        assert ids.load_idle_settings()[ "backoff_minutes" ] == [ 5, 10, 20, 40, 60 ]


# ── the LOUD half: a malformed schedule is a typo the user must see ────────────

class TestAMalformedScheduleRaisesRatherThanDegrading:

    @pytest.mark.parametrize( "bad,needle", [
        ( "string",      "must be a list" ),
        ( 5,             "must be a list" ),
        ( { "a": 1 },    "must be a list" ),
        ( None,          "must be a list" ),
        ( [],            "non-empty list" ),
        ( [ 5, "ten" ],  "[1] must be an int" ),
        ( [ 5.0 ],       "[0] must be an int" ),
        ( [ True, 5 ],   "[0] must be an int" ),   # bool subclasses int — rejected on purpose
        ( [ 5, False ],  "[1] must be an int" ),
        ( [ 5, 0, 10 ],  "[1] must be > 0" ),
        ( [ -1 ],        "[0] must be > 0" ),
    ] )
    def test_each_malformed_schedule_names_what_is_wrong_with_it( self, bad, needle ):
        with pytest.raises( ValueError ) as excinfo:
            ids._validate_backoff_minutes( bad )
        assert needle in str( excinfo.value ), (
            f"the message must locate the fault for the user; got: {excinfo.value}"
        )

    def test_the_error_reaches_the_caller_through_load_not_just_the_validator( self, fake_home ):
        # The validator raising is only useful if load_idle_settings does NOT swallow it —
        # the whole point is that the user sees their typo at hook startup.
        _write_settings( fake_home, { "idle_detection": { "backoff_minutes": [ 5, -3 ] } } )
        with pytest.raises( ValueError, match=r"\[1\] must be > 0" ):
            ids.load_idle_settings()

    @pytest.mark.parametrize( "good", [ [ 1 ], [ 5, 10, 20 ], [ 60, 1 ], [ 5, 10, 20, 40, 60 ] ] )
    def test_a_valid_schedule_passes_silently( self, good ):
        assert ids._validate_backoff_minutes( good ) is None


class TestTheSmokeTestBlockActuallyRuns:
    """`quick_smoke_test` is shipped in the module; an unrun smoke test is decoration."""

    def test_the_module_smoke_test_passes_against_a_clean_home( self, fake_home, capsys ):
        ids.quick_smoke_test()
        assert "All smoke tests passed." in capsys.readouterr().out
