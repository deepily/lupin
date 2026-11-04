"""
The e2e poke mute test compares the fleet file with the server's answer.

The GET answer gained a source key, which the file never carries, so a whole-dict comparison
cannot hold. The comparison is field by field and names the source.
A wrong source or a wrong muted value still fails.

Venue: :7999 (unit, no server).
"""

import os
import sys
from pathlib import Path

import pytest

_E2E_UI_DIR = Path( __file__ ).resolve().parents[ 1 ] / "e2e_ui"
if str( _E2E_UI_DIR ) not in sys.path:
    sys.path.insert( 0, str( _E2E_UI_DIR ) )

from poke_mute_served_state import assert_served_matches_file  # noqa: E402

FILE   = { "muted": True, "set_by": "admin@x", "set_at": "2026-10-10T17:00:00-04:00" }
SERVED = { **FILE, "source": "file" }


def test_a_served_answer_that_is_the_file_plus_the_source_passes():
    assert_served_matches_file( FILE, SERVED, "file" )


def test_a_different_muted_value_fails():
    with pytest.raises( AssertionError ):
        assert_served_matches_file( FILE, { **SERVED, "muted": False }, "file" )


def test_a_different_set_by_fails():
    with pytest.raises( AssertionError ):
        assert_served_matches_file( FILE, { **SERVED, "set_by": "someone-else" }, "file" )


def test_a_wrong_source_fails():
    with pytest.raises( AssertionError ):
        assert_served_matches_file( FILE, { **SERVED, "source": "skeleton_crew" }, "file" )


def test_a_missing_source_fails():
    with pytest.raises( AssertionError ):
        assert_served_matches_file( FILE, dict( FILE ), "file" )


def test_an_extra_unknown_key_fails():
    with pytest.raises( AssertionError ):
        assert_served_matches_file( FILE, { **SERVED, "surprise": 1 }, "file" )
