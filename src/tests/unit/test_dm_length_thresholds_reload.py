#!/usr/bin/env python3
"""
Unit tier for row 00600a75 — the five DM-length thresholds must be reachable by a live
/api/init hot-reload, not frozen at judge.py import.

THE DEFECT THIS GUARDS. The thresholds bind to module globals when judge.py imports, and
judge_v2 takes its OWN copy of QUALITATIVE_WORD_LIMIT via `from judge import ...`. Before
this row, /api/init flushed the config caches but never re-read those globals, so a
tuned ini value did nothing until a server bounce — and the splainer told the operator
"bounce to apply", which was the false claim the row exists to kill.

WHAT MAKES THESE CHECKS REAL. Each one is written so the OLD (frozen-at-import) behaviour
would turn it RED:
  - the sync test fails if judge_v2's stale copy is left un-updated (the trap Maria named)
  - the boundary/face-count tests fail if length_bucket kept reading the import-time value
  - the invalidate_all test fails if the invalidator was defined but never registered
"""

import os
import sys

import pytest

sys.path.insert( 0, os.path.join( os.environ.get( "LUPIN_ROOT", "" ), "src" ) )

from cosa.agents.dm_quality_judge import judge, judge_v2
from cosa.config import cache_registry


def _fake_resolver( cap ):
    """A _resolve_threshold stand-in yielding `cap` for the qualitative word limit and
    the production defaults for the other four keys — so a test can move ONE threshold
    and watch every reader follow."""
    values = {
        "dm qualitative word limit" : cap,
        "dm length target words"    : 60,
        "dm length excellent limit" : 60,
        "dm length good limit"      : 90,
        "dm length verbose limit"   : 250,
    }
    def _resolver( config_key, default ):
        return values.get( config_key, default )
    return _resolver


class TestLengthThresholdReload:
    """Every test restores the real (ini-backed) thresholds in teardown so it cannot
    leave production values changed for the rest of the suite."""

    def teardown_method( self, method ):
        judge._reload_length_thresholds()   # re-read from the real ini, restore globals

    # ── the invalidator is actually REGISTERED, not merely defined ───────────────────
    def test_the_invalidator_is_registered( self ):
        assert "dm_length_thresholds" in cache_registry._registered_names()

    # ── a reload rebinds judge's own globals ─────────────────────────────────────────
    def test_reload_moves_judge_globals( self ):
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr( judge, "_resolve_threshold", _fake_resolver( 100 ) )
            judge._reload_length_thresholds()
            assert judge.QUALITATIVE_WORD_LIMIT == 100

    # ── the stale-copy trap: judge_v2's OWN binding must move too ─────────────────────
    def test_reload_syncs_judge_v2_stale_copy( self ):
        assert judge_v2.QUALITATIVE_WORD_LIMIT == 150   # precondition: at the default
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr( judge, "_resolve_threshold", _fake_resolver( 100 ) )
            judge._reload_length_thresholds()
            # If the hook forgot the sys.modules reach, this stays 150 and the check reddens.
            assert judge_v2.QUALITATIVE_WORD_LIMIT == 100

    # ── length_bucket reflects the new boundary with no restart ──────────────────────
    def test_reload_moves_length_bucket_boundary( self ):
        # 120 words is 🤷/0 at cap 150; drop the cap to 100 and it must fall to 👎/-1.
        assert judge.length_bucket( 120 )[ "weight" ] == 0
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr( judge, "_resolve_threshold", _fake_resolver( 100 ) )
            judge._reload_length_thresholds()
            assert judge.length_bucket( 120 )[ "weight" ] == -1

    # ── the emoji-repetition interval is DECOUPLED from the cap (row 2cb46818) ─────────
    def test_reload_does_not_move_face_repetition_interval( self ):
        # PREMISE FLIPPED (row 2cb46818): the face interval is its OWN constant
        # LENGTH_FACE_INTERVAL (100), NOT the reloadable qualitative cap. A 300-word DM
        # shows 300//100 == 3 faces, and moving the cap must NOT change that count — that
        # decoupling is the whole point: counting faces can no longer recover the cap.
        assert judge.length_bucket( 300 )[ "emoji" ].count( "😞" ) == 3   # 300 // LENGTH_FACE_INTERVAL
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr( judge, "_resolve_threshold", _fake_resolver( 100 ) )
            judge._reload_length_thresholds()
            assert judge.QUALITATIVE_WORD_LIMIT == 100                       # the cap DID move
            assert judge.length_bucket( 300 )[ "emoji" ].count( "😞" ) == 3   # the face count did NOT

    # ── the /api/init path: invalidate_all() must trigger the reload end-to-end ───────
    def test_invalidate_all_triggers_the_reload( self ):
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr( judge, "_resolve_threshold", _fake_resolver( 100 ) )
            succeeded = cache_registry.invalidate_all()
            assert "dm_length_thresholds" in succeeded
            assert judge.QUALITATIVE_WORD_LIMIT    == 100
            assert judge_v2.QUALITATIVE_WORD_LIMIT == 100
