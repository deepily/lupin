"""
Smoke test — playwright visual-regression baselines are git-TRACKED (CI-portable).

Lane C / task 6ca79dc2: the mux playwright visual-snapshot baselines used to live
under the gitignored `io/` store, so they never round-tripped into a fresh `:8000`
/ CI test container — every mux visual test ERRORed at teardown ("New snapshot(s)
created. Please review") and a re-run never cleared it (the container started each
run with no host-resident baseline).

The fix (María's design call: commit, NOT bind-mount) git-tracks the baselines via
a scoped `.gitignore` carve so they travel with the repo into any checkout the test
container builds from — no host-resident dependency. This smoke test guards the
invariant durably:

  1. pytest.ini still points the plugin at io/test-suite/visual-baselines.
  2. The mux baselines under that path are git-tracked (resolve from the index, so
     they round-trip container-side) — directly proving AC-C.1.
  3. The carve is scoped (AC-C.2): the failure-diff store stays ignored; only the
     baseline subtree is re-included.

Venue: :7999 (read-only filesystem + git probes, no server, no state mutation).

Paired build plan: src/rnd/v0.1.9/2026.06.23-proactive-manager-mechanism/01-build-plan.md §3.
"""

import configparser
import subprocess
from pathlib import Path

import cosa.utils.util as cu

SNAPSHOTS_PATH = "io/test-suite/visual-baselines"
FAILURES_PATH  = "io/test-suite/visual-failures"


def _project_root():
    """
    Ensures:
        - returns the canonical Lupin project root as a Path
    """
    return Path( cu.get_project_root() )


def _read_snapshots_path():
    """
    Read playwright_visual_snapshots_path from pytest.ini.

    Ensures:
        - returns the configured snapshots path string
    """
    parser = configparser.ConfigParser()
    parser.read( _project_root() / "pytest.ini" )
    return parser.get( "pytest", "playwright_visual_snapshots_path" )


def _git_tracked_under( rel_dir ):
    """
    List git-tracked files under rel_dir (relative to project root).

    Ensures:
        - returns the list of tracked paths reported by `git ls-files`
    """
    result = subprocess.run(
        [ "git", "ls-files", rel_dir ],
        cwd=_project_root(), capture_output=True, text=True, check=True
    )
    return result.stdout.splitlines()


def _is_git_ignored( rel_path ):
    """
    Ensures:
        - returns True iff `git check-ignore` matches rel_path (exit 0)
    """
    result = subprocess.run(
        [ "git", "check-ignore", rel_path ],
        cwd=_project_root(), capture_output=True, text=True
    )
    return result.returncode == 0


def test_pytest_ini_points_at_io_baselines():
    """The plugin wiring still resolves to the committed baseline subtree."""
    assert _read_snapshots_path() == SNAPSHOTS_PATH


def test_mux_baselines_are_git_tracked():
    """
    AC-C.1: mux visual baselines resolve from git (round-trip into a fresh container
    with no host-resident dependency). `git ls-files` reports only index-tracked
    files, so a non-empty mux set proves portability.
    """
    tracked = _git_tracked_under( SNAPSHOTS_PATH )
    mux     = [ f for f in tracked if "test_multiplexer" in f ]
    assert mux, "no mux visual baselines are git-tracked — they will not round-trip container-side"
    # The specific baseline whose teardown ERROR was confirmed twice in the bug report.
    assert any( "test_multiplexer_task_editing" in f for f in mux )


def test_carve_is_scoped_failures_stay_ignored():
    """
    AC-C.2: the carve re-includes ONLY the baseline subtree. The failure-diff store
    (a generated pixel artifact) and the rest of io/ stay ignored.
    """
    assert _is_git_ignored( FAILURES_PATH + "/some-diff.png" ) is True
    assert _is_git_ignored( SNAPSHOTS_PATH + "/test_multiplexer_task_editing/x.png" ) is False
