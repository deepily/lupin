"""
Guard for `src/scripts/sweep-io-tmp.sh` — row 730b33f2.

WHY THIS FILE IS NAMED FOR THE OFF-BY-ONE. The row's first acceptance pair was
"an 8-day-old file is deleted and a 1-day-old file survives", and that pair
CANNOT DO ITS JOB: `find -mtime +7` truncates age to whole 24h units and matches
only age > 7, so it first deletes at eight days — and the 8d/1d pair passes under
`-mtime +7` and under an exact 7-day sweep alike. It would have certified a sweep
that is a full day late. Rachel caught it on the row before any code existed;
María ruled 2026-09-26 13:46 that seven days means seven days.

So the discriminating cases are the two either side of the boundary:

    age 7 days + 1 minute  -> deleted
    age 7 days - 1 minute  -> survives

Only those two separate `-mmin +10080` from `-mtime +7`, and the mutation arm in
this file's docstring is the proof: swapping the script back to `-mtime +7`
reddens `test_a_file_one_minute_past_seven_days_is_deleted` and nothing else.

WHAT ELSE IS PINNED HERE, and why each one is a property rather than an example:
  - the DRY RUN DEFAULT. Rachel stated she would refuse a version that acts
    without --apply. A sweep pointed at the wrong directory by a typo deletes on
    its first cron tick with nothing left to review, so "deletes nothing by
    default" is a gate condition and gets its own case.
  - the DIRECTORY ITSELF SURVIVES an emptying sweep. The doc viewer serves
    io/tmp/, and a missing folder is a 404 for every future write.
  - AN ABSENT DIRECTORY EXITS 0 AND SAYS SO. A janitor that prints nothing is
    indistinguishable from a janitor that died — the exact failure
    test_disk_hygiene_report_cannot_die_silently.py exists for, one script over.

VENUE: :7999. Everything happens under pytest's tmp_path, nothing outside it is
read or written, and the whole file runs in well under a second.
"""

import os
import subprocess
import time

import pytest

import cosa.utils.util as cu

SCRIPT = cu.get_project_root() + "/src/scripts/sweep-io-tmp.sh"

MINUTE       = 60
DAY          = 24 * 60 * MINUTE
SEVEN_DAYS   = 7 * DAY


def _run( lupin_root, *args ):
    """
    Run the sweep against lupin_root.

    Requires:
        - lupin_root is a path whose io/tmp may or may not exist

    Ensures:
        - returns CompletedProcess with text stdout/stderr
    """
    env = dict( os.environ )
    env[ "LUPIN_ROOT" ] = str( lupin_root )
    return subprocess.run(
        [ "bash", SCRIPT, *args ], capture_output=True, text=True, env=env, timeout=120
    )


def _plant( tmp_dir, name, age_seconds ):
    """
    Write a file and back-date its mtime by age_seconds.

    Requires:
        - tmp_dir exists
        - age_seconds is a non-negative number

    Ensures:
        - returns the created Path
        - the file's mtime is now - age_seconds, to the second
    """
    p = tmp_dir / name
    p.write_text( f"one-off doc: {name}\n" )
    when = time.time() - age_seconds
    os.utime( p, ( when, when ) )
    return p


@pytest.fixture
def io_tmp( tmp_path ):
    """
    A LUPIN_ROOT stand-in with an empty io/tmp/.

    Ensures:
        - returns ( root, io_tmp_dir ), both existing
    """
    root    = tmp_path / "lupin"
    tmp_dir = root / "io" / "tmp"
    tmp_dir.mkdir( parents=True )
    return root, tmp_dir


# ---------------------------------------------------------------------------
# The boundary — the only two cases that distinguish -mmin +10080 from -mtime +7
# ---------------------------------------------------------------------------

def test_a_file_one_minute_past_seven_days_is_deleted( io_tmp ):
    root, tmp_dir = io_tmp
    old = _plant( tmp_dir, "2026.09.19-old.md", SEVEN_DAYS + MINUTE )

    result = _run( root, "--apply" )

    assert result.returncode == 0, result.stderr
    assert not old.exists(), (
        "a file one minute past seven days must be swept — this is the case a "
        f"`-mtime +7` sweep leaves behind for another day. stdout:\n{result.stdout}"
    )


def test_a_file_one_minute_short_of_seven_days_survives( io_tmp ):
    root, tmp_dir = io_tmp
    young = _plant( tmp_dir, "2026.09.19-young.md", SEVEN_DAYS - MINUTE )

    result = _run( root, "--apply" )

    assert result.returncode == 0, result.stderr
    assert young.exists(), f"a file inside the window must survive. stdout:\n{result.stdout}"


def test_both_sides_of_the_boundary_in_one_run( io_tmp ):
    """
    The pair together, in a single sweep.

    Separate runs can each pass for the wrong reason — a sweep that deletes
    everything passes the first case above, and one that deletes nothing passes
    the second. Only one run holding both files can fail a sweep that is merely
    indiscriminate in the convenient direction.
    """
    root, tmp_dir = io_tmp
    old   = _plant( tmp_dir, "past.md",   SEVEN_DAYS + MINUTE )
    young = _plant( tmp_dir, "inside.md", SEVEN_DAYS - MINUTE )

    result = _run( root, "--apply" )

    assert result.returncode == 0, result.stderr
    assert not old.exists(), f"the older side must go. stdout:\n{result.stdout}"
    assert young.exists(),   f"the younger side must stay. stdout:\n{result.stdout}"


# ---------------------------------------------------------------------------
# Dry run is the default — a gate condition, per Rachel
# ---------------------------------------------------------------------------

def test_the_default_run_deletes_nothing( io_tmp ):
    root, tmp_dir = io_tmp
    old = _plant( tmp_dir, "ancient.md", 90 * DAY )

    result = _run( root )   # NO --apply

    assert result.returncode == 0, result.stderr
    assert old.exists(), "the default run must not delete — --apply is the only door"
    assert "DRY RUN" in result.stdout, f"the dry run must SAY so. stdout:\n{result.stdout}"


def test_the_dry_run_still_reports_what_it_would_delete( io_tmp ):
    """
    A dry run that reports nothing is useless as a review step — the whole point
    of the default is that a human can read what --apply would have done.
    """
    root, tmp_dir = io_tmp
    _plant( tmp_dir, "a.md", 90 * DAY )
    _plant( tmp_dir, "b.md", 90 * DAY )
    _plant( tmp_dir, "c.md", MINUTE )

    result = _run( root )

    assert "eligible : 2" in result.stdout, f"stdout:\n{result.stdout}"
    assert "before   : 3" in result.stdout, f"stdout:\n{result.stdout}"


# ---------------------------------------------------------------------------
# Properties of the sweep itself
# ---------------------------------------------------------------------------

def test_nested_files_are_swept_and_their_emptied_directories_pruned( io_tmp ):
    root, tmp_dir = io_tmp
    nested = tmp_dir / "2026.09.19-report-assets"
    nested.mkdir()
    buried = _plant( nested, "chart.png", SEVEN_DAYS + MINUTE )

    result = _run( root, "--apply" )

    assert result.returncode == 0, result.stderr
    assert not buried.exists(), "a file nested one level down is still in scope"
    assert not nested.exists(), "a directory the sweep emptied is pruned"


def test_the_tmp_directory_itself_always_survives( io_tmp ):
    """
    io/tmp/ is served by the doc viewer. If the sweep removed the folder once it
    was empty, the next write would land in a missing directory and every link to
    it would 404 — a self-clearing folder that clears itself away is not the ask.
    """
    root, tmp_dir = io_tmp
    _plant( tmp_dir, "only.md", 90 * DAY )

    result = _run( root, "--apply" )

    assert result.returncode == 0, result.stderr
    assert tmp_dir.is_dir(), "io/tmp/ must outlive its contents"


def test_retention_is_overridable_for_operators( io_tmp ):
    root, tmp_dir = io_tmp
    hour_old = _plant( tmp_dir, "recent.md", 90 * MINUTE )

    result = _run( root, "--apply" )
    assert hour_old.exists(), "90 minutes is well inside the 7-day default"

    env = dict( os.environ )
    env[ "LUPIN_ROOT" ]      = str( root )
    env[ "RETAIN_MINUTES" ]  = "60"
    result = subprocess.run(
        [ "bash", SCRIPT, "--apply" ], capture_output=True, text=True, env=env, timeout=120
    )
    assert result.returncode == 0, result.stderr
    assert not hour_old.exists(), f"RETAIN_MINUTES=60 must sweep a 90-minute-old file. stdout:\n{result.stdout}"


# ---------------------------------------------------------------------------
# It cannot die silently
# ---------------------------------------------------------------------------

def test_an_absent_directory_exits_zero_and_says_so( tmp_path ):
    root = tmp_path / "lupin"
    root.mkdir()   # no io/tmp at all

    result = _run( root, "--apply" )

    assert result.returncode == 0, result.stderr
    assert "nothing to do" in result.stdout, (
        f"an absent directory must be ANNOUNCED, not silently skipped. stdout:\n{result.stdout!r}"
    )


def test_a_missing_lupin_root_refuses_rather_than_sweeping_something_else( tmp_path ):
    """
    `${LUPIN_ROOT:?}` — without it the path would collapse to `/io/tmp`, and a
    deletion tool that resolves to the wrong absolute path is the failure mode the
    dry-run default exists to contain. Belt and braces, both asserted.
    """
    env = { k: v for k, v in os.environ.items() if k != "LUPIN_ROOT" }
    result = subprocess.run(
        [ "bash", SCRIPT, "--apply" ], capture_output=True, text=True, env=env, timeout=120
    )
    assert result.returncode != 0, "a missing LUPIN_ROOT must refuse"
    assert "LUPIN_ROOT" in result.stderr, f"and must say which variable. stderr:\n{result.stderr!r}"
