"""
Pins `_git`, `read_deliveries` and `main` of `src/scripts/delivery_latency.py`.

`test_delivery_latency_instrument.py` holds the pure functions. This file covers the rest.
One test builds a real repository and fast-forwards a branch into `main`, so the reflog is the
one git writes. The others feed `read_deliveries` and `main` text in the shapes git and
journalctl print, with fakes that answer according to what they are asked.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert( 0, str( Path( __file__ ).resolve().parents[ 2 ] / "scripts" ) )

import delivery_latency as dl


H = 3600.0

JOURNAL = "  0 86523828 Sat 2026-09-05 09:39:45 EDT—Sat 2026-09-05 21:39:45 EDT\n"


class _Out:
    def __init__( self, stdout ):
        self.stdout = stdout


def _git_env( at ):
    return dict( os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com",
                 GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.com",
                 GIT_AUTHOR_DATE=f"{at} +0000", GIT_COMMITTER_DATE=f"{at} +0000" )


def _run( repo, at, *args ):
    subprocess.run( [ "git", "-C", str( repo ), *args ], check=True, capture_output=True, env=_git_env( at ) )


# ---------------------------------------------------------------- _git and read_deliveries, real git

def test_a_fast_forward_into_the_branch_reads_back_with_the_authors_dates( tmp_path ):
    _run( tmp_path, 1700000000, "init", "-q", "-b", "main" )
    _run( tmp_path, 1700000000, "commit", "-q", "--allow-empty", "-m", "base" )
    _run( tmp_path, 1700000100, "checkout", "-q", "-b", "feat" )
    _run( tmp_path, 1700001000, "commit", "-q", "--allow-empty", "-m", "one" )
    _run( tmp_path, 1700002000, "commit", "-q", "--allow-empty", "-m", "two" )
    _run( tmp_path, 1700003000, "checkout", "-q", "main" )
    _run( tmp_path, 1700004000, "merge", "-q", "--ff-only", "feat" )

    got = dl.read_deliveries( str( tmp_path ), "main" )

    assert len( got ) == 1
    assert got[ 0 ][ "times" ] == [ 1700001000, 1700002000 ]
    assert got[ 0 ][ "subject" ].startswith( "merge feat" )


def test_git_output_for_a_missing_repo_is_empty_rather_than_raising( tmp_path ):
    assert dl._git( str( tmp_path / "absent" ), "log" ) == ""


# ---------------------------------------------------------------- read_deliveries, shaped text

def test_only_merge_entries_with_commits_between_their_shas_are_deliveries( monkeypatch ):
    reflog = "\n".join( [
        "c3|main@{1700003000}|merge feat: Fast-forward",
        "garbage with no separators",
        "c2|main@{1700002000}|commit: x",
        "cX|no-braces-here|merge ignored",
        "c1|main@{1700001000}|merge empty: Fast-forward",
        "c0|main@{1700000000}|commit (initial): a",
    ] )
    asked = []

    def fake_git( repo, *args ):
        asked.append( args )
        if args[ 0 ] == "reflog":
            return reflog
        if args[ -1 ] == "c2..c3":
            return "h1 1699990000\nh2 1699995000\nbadline\n"
        return ""

    monkeypatch.setattr( dl, "_git", fake_git )

    got = dl.read_deliveries( "/repo", "main" )

    assert got == [ dict( landed=1700003000, times=[ 1699990000, 1699995000 ], subject="merge feat: Fast-forward" ) ]
    assert any( a[ -1 ] == "c0..c1" for a in asked )
    assert not any( a[ -1 ] == "c1..c2" for a in asked )


# ---------------------------------------------------------------- main

def _run_main( monkeypatch, capsys, journal, deliveries ):
    monkeypatch.setattr( sys, "argv", [ "delivery_latency.py", "--repo", "/r", "--branch", "b" ] )
    monkeypatch.setattr( dl.subprocess, "run", lambda *a, **k: _Out( journal ) )
    monkeypatch.setattr( dl, "read_deliveries", lambda repo, branch: deliveries )
    dl.main()
    return capsys.readouterr().out


def test_main_refuses_when_no_boot_interval_parses( monkeypatch, capsys ):
    with pytest.raises( SystemExit ) as e:
        _run_main( monkeypatch, capsys, "nothing useful\n", [ dict( landed=1, times=[ 0 ], subject="merge x" ) ] )

    assert "parsed 0 boot intervals" in str( e.value )


def test_main_refuses_when_the_branch_has_no_deliveries( monkeypatch, capsys ):
    with pytest.raises( SystemExit ) as e:
        _run_main( monkeypatch, capsys, JOURNAL, [] )

    assert "0 handoff deliveries" in str( e.value )


def test_main_reports_the_tail_episodes_and_which_end_at_the_landing( monkeypatch, capsys ):
    start = dl.parse_boot_intervals( JOURNAL )[ 0 ][ 0 ]
    landed = start + 10 * H
    deliveries = [
        # silence ends at the landing: the branch finished at +1h and then sat 9h
        dict( landed=landed, times=[ start, start + 1 * H ], subject="merge a" ),
        # silence ends before the landing: a 9h gap, then a commit an hour before landing
        dict( landed=landed, times=[ start, start + 9 * H ], subject="merge b" ),
    ]

    out = _run_main( monkeypatch, capsys, JOURNAL, deliveries )

    assert "boot intervals: 1" in out
    assert "handoff deliveries 2   commits 4   tail >=6h 3" in out
    assert "TAIL EPISODES (the real n): 2   carrying 4 commits" in out
    assert "box-up hours across tail episodes      : 20.0" in out
    assert "(90%)" in out
    assert "episodes whose silence ENDS AT THE LANDING: 1/2" in out
    assert "never evidence that a person failed to act" in out
