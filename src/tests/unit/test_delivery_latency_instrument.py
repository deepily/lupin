#!/usr/bin/env python3
"""
Guard for `src/scripts/delivery_latency.py` — the instrument behind §9–§9e of
`src/rnd/v0.2.1/2026.09.05-no-worker-facing-delivery-route.md`.

WHY THE PURE FUNCTIONS AND NOT THE CLI. The three functions here are the whole measurement;
everything else is `git` and `journalctl` I/O. A test that shelled out to those would be
measuring this host's boot history, which changes daily — a fixture that cannot be wrong in a
way the test could see.

⚠️ THESE ARE FIXTURES, DELIBERATELY, AND THEY HONOUR THEIR INPUTS. Per the repo's own rule, a
fake that ignores its arguments answers the same however the code behaves. Every case below
changes an input and expects a DIFFERENT number.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert( 0, str( Path( __file__ ).resolve().parents[ 2 ] / "scripts" ) )

import delivery_latency as dl


H = 3600.0


# ---------------------------------------------------------------- parse_boot_intervals

def test_boot_parse_reads_a_real_journalctl_line():
    text = ( "  -1 7322f660 Fri 2026-09-04 11:03:18 EDT—Fri 2026-09-04 23:55:09 EDT\n"
             "   0 86523828 Sat 2026-09-05 09:39:45 EDT—Sat 2026-09-05 20:38:58 EDT\n" )
    got = dl.parse_boot_intervals( text )
    assert len( got ) == 2
    assert got[ 0 ][ 1 ] - got[ 0 ][ 0 ] == pytest.approx( 12.865 * H, abs=60 )


def test_boot_parse_returns_EMPTY_rather_than_raising_on_junk():
    """
    The caller REFUSES on an empty list, and it can only do that if this returns one. An
    exception here would make "journalctl said nothing" indistinguishable from a crash.
    """
    assert dl.parse_boot_intervals( "wtmp begins Tue Sep 1\n\n" ) == []


# ---------------------------------------------------------------- up_hours

def test_up_hours_counts_only_the_overlap_and_skips_the_gap():
    # up 10:00-12:00 and 14:00-16:00; ask about 11:00-15:00 => 1h + 1h, the 12-14 gap excluded
    ups = [ ( 10 * H, 12 * H ), ( 14 * H, 16 * H ) ]
    assert dl.up_hours( ups, 11 * H, 15 * H ) == pytest.approx( 2.0 )


def test_up_hours_is_zero_when_the_whole_window_is_down():
    ups = [ ( 10 * H, 12 * H ) ]
    assert dl.up_hours( ups, 12 * H, 20 * H ) == 0.0


def test_up_hours_is_zero_for_an_inverted_window():
    assert dl.up_hours( [ ( 0, 100 * H ) ], 50 * H, 10 * H ) == 0.0


def test_up_hours_MOVES_WITH_ITS_INPUT():
    """
    THE DISCRIMINATION CHECK. A helper that ignored its interval list would satisfy every case
    above that happens to expect a number; this one fails unless the uptime actually governs.
    """
    window = ( 0.0, 24 * H )
    assert dl.up_hours( [ ( 0, 24 * H ) ], *window ) == pytest.approx( 24.0 )
    assert dl.up_hours( [ ( 0,  6 * H ) ], *window ) == pytest.approx(  6.0 )


# ---------------------------------------------------------------- largest_silent_stretch

def test_the_silent_stretch_is_the_widest_gap_between_commits():
    ups     = [ ( 0, 100 * H ) ]                       # box up throughout: wall == box-up
    commits = [ 0.0, 1 * H, 20 * H ]                   # a 19h silence between the 2nd and 3rd
    up, wall, start, end = dl.largest_silent_stretch( ups, commits, 21 * H )
    assert up == pytest.approx( 19.0 ) and wall == pytest.approx( 19.0 )
    assert ( start, end ) == ( 1 * H, 20 * H )


def test_a_gap_that_ENDS_AT_THE_LANDING_is_a_candidate():
    """
    §9e's unambiguous case — branch finished, then sat. If this gap were excluded, the 3-of-9
    'finished and waiting' count would silently become 0 and the section's conclusion with it.
    """
    ups     = [ ( 0, 100 * H ) ]
    commits = [ 0.0, 1 * H ]
    up, _, _, end = dl.largest_silent_stretch( ups, commits, 12 * H )
    assert end == 12 * H, "the stretch ending at the landing must be reachable"
    assert up == pytest.approx( 11.0 )


def test_the_stretch_counts_BOX_UP_HOURS_not_wall_clock():
    """
    The whole point of the measure: a silence spanning a shutdown is not 'nobody acted', it is
    'nobody could act'. Wall and box-up must come apart here or the measure proves nothing.
    """
    ups     = [ ( 0, 2 * H ), ( 12 * H, 24 * H ) ]     # down 02:00-12:00
    commits = [ 1 * H ]
    up, wall, _, _ = dl.largest_silent_stretch( ups, commits, 14 * H )
    assert wall == pytest.approx( 13.0 )
    assert up   == pytest.approx(  3.0 )               # 1h before the shutdown + 2h after boot
    assert up < wall


def test_a_single_commit_still_yields_the_gap_to_the_landing():
    ups = [ ( 0, 100 * H ) ]
    up, _, start, end = dl.largest_silent_stretch( ups, [ 5 * H ], 9 * H )
    assert ( start, end ) == ( 5 * H, 9 * H ) and up == pytest.approx( 4.0 )
